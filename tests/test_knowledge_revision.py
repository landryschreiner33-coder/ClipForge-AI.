"""A stale browser note cannot replace a newer reviewed lesson, even after the newer request completed."""
import pytest
from fastapi.testclient import TestClient

from clipfoundry import db
from clipfoundry.api import app

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "profile"))
    db.init()
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


def note(client):
    response = client.post("/api/brain/knowledge", headers=H, json={
        "kind": "instruction", "title": "Readable captions", "content": "Keep the caption quiet.",
        "preferences": {"caption_style": "minimal"},
    })
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("change", [
    {"content": "Outdated text"}, {"enabled": False}, {"content": "New reviewed text"},
])
def test_completed_newer_review_is_not_overwritten_by_a_stale_browser(client, change):
    original = note(client)
    url = f"/api/brain/knowledge/{original['id']}"
    updated = client.patch(url, headers=H, json={"content": "New reviewed text", "expected_revision": 1})
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    approved = client.post(url + "/approve", headers=H, json={"revision": 2})
    assert approved.status_code == 200 and approved.json()["approved"]
    stale = client.patch(url, headers=H, json={**change, "expected_revision": 1})
    assert stale.status_code == 409
    saved = client.get("/api/brain/knowledge").json()[0]
    assert saved["content"] == "New reviewed text" and saved["enabled"] and saved["approved"]
    assert saved["revision"] == 2


@pytest.mark.parametrize("bad", [None, False, 0, 1.5, "1"])
def test_client_revision_must_be_a_whole_positive_revision(client, bad):
    original = note(client)
    response = client.patch(f"/api/brain/knowledge/{original['id']}", headers=H,
                            json={"expected_revision": bad, "content": "Do not save this"})
    assert response.status_code == 422
    assert client.get("/api/brain/knowledge").json()[0]["content"] == original["content"]


def test_matching_client_revision_can_save_and_older_clients_remain_compatible(client):
    original = note(client)
    url = f"/api/brain/knowledge/{original['id']}"
    response = client.patch(url, headers=H, json={"content": "Fresh edit", "expected_revision": 1})
    assert response.status_code == 200 and response.json()["revision"] == 2
    legacy = client.patch(url, headers=H, json={"content": "Legacy edit"})
    assert legacy.status_code == 200 and legacy.json()["revision"] == 3

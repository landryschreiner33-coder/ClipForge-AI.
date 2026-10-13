"""Form drafts stay local and truthful; their presets request only the permissions they describe."""
from __future__ import annotations

import io
import json
import struct
import zipfile
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from fake_platforms import FakeTikTok

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8999") as c:
        yield c


def test_setup_uses_actual_callback_and_cannot_turn_a_checklist_into_an_approval(client):
    from clipfoundry import db

    original = db.get_settings()
    packet = client.get("/api/publish/tiktok/setup").json()
    assert packet["redirect_uri"] == "http://127.0.0.1:8999/api/oauth/tiktok/callback"
    assert "single-user" in packet["description"] and "not a public multi-user service" in packet["description"]
    assert "private/personal" in packet["limits"][0]
    assert packet["completed_count"] == 0
    draft = {"completed": [row["id"] for row in packet["checklist"]] + ["approved"]}
    # An unbounded or unknown progress field cannot become an approval knob.
    assert client.post("/api/publish/tiktok/setup", json={"audited": True}, headers=H).status_code == 422
    assert client.post("/api/publish/tiktok/setup", json=draft, headers=H).status_code == 422
    done = client.post("/api/publish/tiktok/setup", json={
        "completed": [row["id"] for row in packet["checklist"]],
    }, headers=H).json()
    assert done["completed_count"] == len(done["checklist"])
    assert "cannot verify" in done["portal_status"]
    assert db.get_settings() == original
    assert db.get_account("tiktok") is None


@pytest.mark.parametrize("bad", [
    "", "http://127.0.0.1:8999/legal/", "https://localhost/legal/", "https://192.168.1.2/privacy.html",
    "https://example.com/privacy", "https://site.local/", "https://name:secret@real-site.com/privacy",
    "https://real-site.com/privacy?access_token=private", "https://real-site.com/#privacy",
    "https://real-site.com:bad/privacy", "https://real-site.com\\@localhost/privacy",
])
def test_public_website_fields_reject_local_or_secret_bearing_links(bad):
    from clipfoundry.publish.tiktok_setup import public_url

    assert public_url(bad)


def test_public_website_check_is_format_only_and_does_not_fetch(client, monkeypatch):
    import httpx

    def forbidden(*args, **kwargs):
        raise AssertionError("The form helper must not fetch user-supplied websites")

    monkeypatch.setattr(httpx, "get", forbidden)
    packet = client.post("/api/publish/tiktok/setup", json={
        "website": "https://my-clipfoundry-site.com/", "terms": "https://my-clipfoundry-site.com/terms.html",
        "privacy": "https://my-clipfoundry-site.com/privacy.html",
    }, headers=H).json()
    assert packet["url_errors"] == {}
    assert "unverified" in packet["url_check"]


def test_form_export_uses_curated_fields_only_and_includes_real_1024_pngs(client):
    from clipfoundry import db

    db.save_settings({"tiktok_client_key": "fake-private-client-key", "tiktok_client_secret": "fake-secret-only",
                      "youtube_client_secret": "fake-google-secret", "openai_api_key": "fake-ai-key"})
    response = client.post("/api/publish/tiktok/setup/export", json={"mode": "inbox"}, headers=H)
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        expected = {"form-draft.txt", "form-draft.json", "app-icon-dark.png", "app-icon-light.png",
                    "website-preview/index.html", "website-preview/privacy.html", "website-preview/terms.html",
                    "website-preview/site.css", "website-preview/READ-ME.txt"}
        assert set(z.namelist()) == expected
        for name in expected:
            data = z.read(name)
            assert all(s.encode() not in data for s in ("fake-private-client-key", "fake-secret-only",
                                                       "fake-google-secret", "fake-ai-key"))
        packet = json.loads(z.read("form-draft.json"))
        assert packet["scopes"] == ["user.info.basic", "video.upload"]
        assert "[add your real published HTTPS page]" in z.read("form-draft.txt").decode()
        assert "not a deployed website" in z.read("website-preview/READ-ME.txt").decode()
        for theme in ("dark", "light"):
            png = z.read(f"app-icon-{theme}.png")
            assert png[:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", png[16:24]) == (1024, 1024)
            assert len(png) < 5 * 1024 * 1024
            direct = client.get(f"/api/publish/tiktok/setup/icon/{theme}")
            assert direct.status_code == 200 and direct.content == png
    assert client.get("/api/publish/tiktok/setup/icon/other").status_code == 404


def test_form_routes_are_local_only_and_post_requests_need_the_app_header(client):
    assert client.get("/api/publish/tiktok/setup", headers={"Host": "remote.example.org"}).status_code == 403
    assert client.get("/api/publish/tiktok/setup/icon/dark", headers={"Host": "remote.example.org"}).status_code == 403
    for path in ("/api/publish/tiktok/setup", "/api/publish/tiktok/setup/export"):
        assert client.post(path, json={}).status_code == 403
        assert client.post(path, json={}, headers={**H, "Host": "remote.example.org"}).status_code == 403
    assert client.post("/api/publish/tiktok/setup", json={"mode": "unknown"}, headers=H).status_code == 400


@pytest.mark.parametrize("field,url", [
    ("website", "https://owner:private-do-not-export@my-clipfoundry-site.com/"),
    ("terms", "https://my-clipfoundry-site.com/terms?token=private-do-not-export"),
    ("privacy", "https://my-clipfoundry-site.com/privacy#private-do-not-export"),
])
def test_invalid_public_urls_are_blocked_before_any_secret_bearing_export(client, field, url):
    from clipfoundry import db

    original = db.get_settings()
    response = client.post("/api/publish/tiktok/setup/export", json={field: url}, headers=H)
    assert response.status_code == 400
    assert field in response.json()["detail"]
    assert "private-do-not-export" not in response.text
    assert "application/zip" not in response.headers["content-type"]
    assert db.get_settings() == original


def test_public_valid_urls_can_be_exported_alongside_blank_draft_fields(client):
    response = client.post("/api/publish/tiktok/setup/export", json={
        "website": "https://my-clipfoundry-site.com/", "terms": "", "privacy": "",
    }, headers=H)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        packet = json.loads(z.read("form-draft.json"))
        assert packet["urls"] == {"website": "https://my-clipfoundry-site.com/", "terms": "", "privacy": ""}


@pytest.mark.parametrize("mode,stats,expected", [
    ("inbox", False, ["user.info.basic", "video.upload"]),
    ("direct", False, ["user.info.basic", "video.publish"]),
    ("both", True, ["user.info.basic", "video.upload", "video.publish", "video.list"]),
])
def test_form_presets_match_actual_oauth_grants_and_account_capabilities(client, monkeypatch, mode, stats, expected):
    from clipfoundry.publish import tiktok

    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    fake = FakeTikTok()
    fake.scope = ",".join(expected)
    monkeypatch.setattr(tiktok, "AUTH_URL", f"{fake.url}/v2/auth/authorize/")
    monkeypatch.setattr(tiktok, "API_URL", f"{fake.url}/v2")
    try:
        packet = client.post("/api/publish/tiktok/setup", json={"mode": mode, "read_stats": stats}, headers=H).json()
        assert packet["scopes"] == expected
        client.put("/api/settings", json={**packet["preferences"], "tiktok_client_key": "tkkey",
                                           "tiktok_client_secret": "tksecret"})
        auth = client.post("/api/publish/tiktok/connect", headers=H).json()["auth_url"]
        query = parse_qs(urlparse(auth).query)
        assert query["scope"] == [",".join(expected)]
        assert query["redirect_uri"] == [packet["redirect_uri"]]
        page = client.get("/api/oauth/tiktok/callback", params={"state": query["state"][0],
                                                                 "code": fake.approve(auth)})
        assert "TikTok connected" in page.text
        account = client.get("/api/publish/accounts").json()["tiktok"]
        assert account["scopes"] == sorted(expected)
        assert account["can_inbox"] == ("video.upload" in expected)
        assert account["can_direct_post"] == ("video.publish" in expected)
        assert account["can_read_stats"] == stats
    finally:
        fake.stop()


def test_historical_permissions_stay_both_and_disabled_posting_never_gets_silent_extra_scope():
    from clipfoundry.publish.tiktok import scopes

    assert scopes({}) == ["user.info.basic", "video.upload", "video.publish", "video.list"]
    assert scopes({"tiktok_inbox_upload": False, "tiktok_direct_post": False, "tiktok_read_stats": False}) == [
        "user.info.basic"]

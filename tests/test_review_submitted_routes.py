"""Submitted inputs use safe application routes and never depend on discovery credentials."""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from test_autopilot_intake import data  # noqa: F401 - isolated DB and deterministic public-address resolver

H = {"X-ClipFoundry": "1"}


def local_options():
    return {"auto_upload": False}


def test_advanced_source_route_redirects_submitted_mode_without_breaking_explicit_discovery(data):
    from clipfoundry import db
    from clipfoundry.api import app

    body = {"url": "https://example.com/advanced-source.mp4"}
    before = {table: db.select(table) for table in ("sources", "source_submissions", "worker_jobs", "source_rights")}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        denied = client.post("/api/autopilot/sources", headers=H, json=body)
        assert denied.status_code == 409, denied.text
        assert "Use Add video in Missions" in denied.json()["detail"]
        assert {table: db.select(table) for table in before} == before
        db.save_settings({"autopilot_input_mode": "discovery"})
        accepted = client.post("/api/autopilot/sources", headers=H, json=body)
        assert accepted.status_code == 200, accepted.text
    sources = db.select("sources")
    assert len(sources) == 1 and sources[0]["url"] == body["url"]
    assert not db.select("source_submissions") and not db.select("source_rights")
    assert db.select("worker_jobs", "kind='source_scout'")


def test_file_submission_requires_app_request_and_strict_options_and_stays_managed(data):
    from clipfoundry import config, db
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        files = {"file": ("sample.mp4", b"isolated source", "video/mp4")}
        denied = client.post("/api/autopilot/submissions/file", files=files, data={"options": json.dumps(local_options())})
        assert denied.status_code == 403 and not db.select("sources")
        malformed = client.post("/api/autopilot/submissions/file", headers=H, files=files,
                                data={"options": '{"auto_upload":"false"}'})
        assert malformed.status_code == 400 and not db.select("sources")
        accepted = client.post("/api/autopilot/submissions/file", headers=H,
                              files={"file": ("C:\\outside\\..\\sample.mp4", b"isolated source", "video/mp4")},
                              data={"options": json.dumps(local_options())})
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()
        source = db.fetch("sources", body["item"]["id"])
        path = __import__("pathlib").Path(source["local_path"])
        assert path.is_relative_to(config.data_dir() / "submitted") and path.name == "source.mp4"
        assert path.read_bytes() == b"isolated source" and source["title"] == "sample"
        assert body["item"]["submission"] == body["submission"]
        assert body["submission"]["auto_upload"] is False
        listed = client.get("/api/autopilot/submissions").json()
        assert listed[0]["id"] == source["id"] and listed[0]["submission"]["progress"]["posts_uploaded"] == 0
        assert not db.select("scheduled_publications") and not db.select("publications")


def test_submitted_youtube_input_bypasses_broken_search_keys_without_fabricating_ownership(data, monkeypatch):
    from clipfoundry import db, media_import
    from clipfoundry.api import app
    from clipfoundry.autopilot import access, host, intake, providers, queue, rights

    db.save_settings({"youtube_api_key": "not-a-real-search-key", "tavily_api_key": "not-a-real-tavily-key",
                      "rights_allow_remote_download": False, "autopilot_public_videos": False})
    def no_search(*args, **kwargs):
        raise AssertionError("A submitted video must not use search credentials")
    monkeypatch.setattr(providers, "YouTubeDiscovery", no_search)
    observed = []
    def public_inspection(url):
        observed.append(url)
        return {"title": "Public supplied video", "kind": "recorded", "live_status": "", "duration": 120}
    monkeypatch.setattr(media_import, "inspect_video", public_inspection)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        rejected = client.post("/api/autopilot/submissions/link", headers=H,
                               json={"url": "http://127.0.0.1/hidden.mp4", **local_options()})
        assert rejected.status_code == 400 and not db.select("sources")
        response = client.post("/api/autopilot/submissions/link", headers=H,
                               json={"url": "https://youtu.be/submitted01?tracking=1", **local_options()})
        assert response.status_code == 200, response.text
    source = db.fetch("sources", response.json()["item"]["id"])
    host.WorkerHost(periodic=False)
    row = queue.claim("source_scout", "submitted-route-test")
    assert row and row["kind"] == "identify_link"
    result = intake.identify_link(host.Job(row, "submitted-route-test"))
    queue.complete(row, "submitted-route-test", result)
    source = db.fetch("sources", source["id"])
    assert observed == ["https://www.youtube.com/watch?v=submitted01"]
    assert source["title"] == "Public supplied video" and rights.evaluate(source)["status"] == rights.MANUAL
    assert access.resolve(source, db.get_settings())["ok"]
    assert db.select("worker_jobs", "kind='hunt_source'")[0]["payload"]["source_id"] == source["id"]
    assert not db.select("source_rights") and not db.select("publish_consents")
    assert not db.select("publications")


@pytest.mark.parametrize("failure", ["oversized", "disk", "empty"])
def test_failed_streamed_file_submission_leaves_no_partial_input_or_source_copy(data, monkeypatch, failure):
    from clipfoundry import config, db
    from clipfoundry.autopilot import hunter, queue, submissions

    if failure == "oversized":
        monkeypatch.setattr(hunter, "max_source_bytes", lambda _: 4)
    if failure == "disk":
        def no_space(*args):
            raise queue.Wait("disk", 1800, "Not enough disk space")
        monkeypatch.setattr(hunter, "require_disk_space", no_space)
    with pytest.raises(ValueError):
        submissions.add_file(io.BytesIO(b"" if failure == "empty" else b"more than four bytes"), "sample.mp4", local_options())
    assert not db.select("sources") and not db.select("source_submissions") and not db.select("worker_jobs")
    assert not list((config.data_dir() / "submitted").rglob("source.*"))


@pytest.mark.parametrize("input_kind", ["link", "file"])
@pytest.mark.parametrize("reuse_basis", ["owned", "permission", "legal_exception"])
def test_reuse_details_limit_includes_selected_basis_before_any_input_is_saved(data, input_kind, reuse_basis):
    from clipfoundry import config, db
    from clipfoundry.api import app
    from clipfoundry.autopilot import submissions

    db.save_account("youtube", tokens={"access_token": "isolated-route-token"}, account_id="UCsubmitted-route")
    setup = submissions.setup()
    basis = next(row for row in setup["reuse_bases"] if row["id"] == reuse_basis)
    max_details = 4000 - len(basis["text"]) - len(" Details: ")
    options = {"auto_upload": True, "account_id": setup["account_id"], "privacy": setup["privacy"],
               "made_for_kids": False, "audience_version": setup["audience"]["group_version"],
               "reuse_basis": reuse_basis, "agreed": True}

    def submit(client, details):
        chosen = {**options, "reuse_statement": details}
        if input_kind == "link":
            return client.post("/api/autopilot/submissions/link", headers=H,
                               json={"url": "https://youtu.be/submitted02", **chosen})
        return client.post("/api/autopilot/submissions/file", headers=H,
                           files={"file": ("sample.mp4", b"isolated route original", "video/mp4")},
                           data={"options": json.dumps(chosen)})

    tables = ("sources", "source_submissions", "projects", "worker_jobs", "brain_knowledge", "source_rights")
    before = {table: db.select(table) for table in tables}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        rejected = submit(client, "x" * (max_details + 1))
        assert rejected.status_code == 400, rejected.text
        assert "including the selected basis" in rejected.json()["detail"]
        assert {table: db.select(table) for table in tables} == before
        assert not list((config.data_dir() / "submitted").rglob("source.*"))
        accepted = submit(client, "x" * max_details)
        assert accepted.status_code == 200, accepted.text
    grant = submissions.for_source(db.fetch("sources", accepted.json()["item"]["id"]))
    expected = basis["text"] + " Details: " + "x" * max_details
    assert len(expected) == 4000 and grant["settings"]["reuse_statement"] == expected
    assert not db.select("scheduled_publications") and not db.select("publications")

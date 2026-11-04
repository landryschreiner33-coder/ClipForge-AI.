"""Fresh YouTube-only setup and stale automatic permissions, using local Google stand-ins only."""
from __future__ import annotations

import time

import pytest
from fake_platforms import FakeGoogle
from quality_stub import passed_report

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry import config, db
    from clipfoundry.publish import youtube

    # Most scheduling tests pre-confirm audiences globally. This is the actual fresh-install state.
    monkeypatch.setitem(config.DEFAULT_SETTINGS, "audience_youtube_confirmed_at", 0.0)
    monkeypatch.setitem(config.DEFAULT_SETTINGS, "audience_tiktok_confirmed_at", 0.0)
    google = FakeGoogle()
    for name, value in {"AUTH_URL": f"{google.url}/o/oauth2/v2/auth", "TOKEN_URL": f"{google.url}/token",
                        "REVOKE_URL": f"{google.url}/revoke", "API_URL": f"{google.url}/youtube/v3",
                        "UPLOAD_URL": f"{google.url}/upload/youtube/v3/videos", "CHUNK": 256 * 1024}.items():
        monkeypatch.setattr(youtube, name, value)
    db.init()
    db.save_settings({"youtube_client_id": "cid.apps.googleusercontent.com", "youtube_client_secret": "csecret",
                      "library_discovery": False})
    from clipfoundry.publish.common import challenge_s256, code_verifier

    verifier = code_verifier()
    callback = "http://127.0.0.1:8765/cb"
    code = google.approve(youtube.auth_url(db.get_settings(), callback, "local", challenge_s256(verifier)))
    youtube.exchange_code(db.get_settings(), code, verifier, callback)
    yield google, tmp_path
    google.stop()


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


def _ready_clip(tmp_path):
    from clipfoundry import db

    video = tmp_path / "ready.mp4"
    video.write_bytes(b"local placeholder for scheduling and fake-upload contracts")
    project = db.create_project("Owned talk", status="ready", origin="autopilot")
    clip = db.create_clip(project["id"], start=0, end=30, duration=30, status="ready", title="Talk to customers",
                          output_path=str(video), caption_text="Talk to customers", score=80)
    db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": "youtube", "selected": 1,
                                      "title": "Talk to customers", "description": "Talk to customers",
                                      "score": 80})
    passed_report(clip, ("youtube",))
    return clip


def test_fresh_youtube_only_needs_audience_and_permission_then_posts_once(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import host, publisher, queue, scheduler, state

    google, tmp_path = env
    result = client.post("/api/autopilot/start", headers=H, json={"topics": "business"})
    assert result.status_code == 200
    settings = db.get_settings()
    assert settings["autopilot_youtube"] and not settings["autopilot_tiktok"]
    assert not db.get_account("tiktok")
    clip = _ready_clip(tmp_path)
    now = time.time()
    assert scheduler.plan_new(settings, now)["created"] == 0
    scheduler.audience_reminders(settings)
    assert any(a["key"] == "audience_setup:youtube" for a in state.open_actions())
    assert not db.select("scheduled_publications") and not google.sessions

    # The owner confirms Public explicitly. No other platform or existing post is changed.
    confirmed = client.post("/api/audience/youtube", headers=H, json={"intent": "public", "confirm": True})
    assert confirmed.status_code == 200 and confirmed.json()["youtube"]["confirmed"]
    assert db.get_settings()["audience_tiktok_confirmed_at"] == 0
    permission = client.post("/api/autopilot/auto-publish", headers=H, json={
        "platform": "youtube", "visibility": "public", "made_for_kids": False, "daily_limit": 3,
        "start_hour": 9, "end_hour": 21, "agreed": True,
    })
    assert permission.status_code == 200 and permission.json()["youtube"]["enabled"]
    assert scheduler.plan_new(db.get_settings(), now)["created"] == 1
    item = db.select("scheduled_publications")[0]
    assert item["clip_id"] == clip["id"] and item["platform"] == "youtube"
    assert item["status"] == "approved" and item["approval"]["by"] == "automatic"
    assert item["privacy"] == "public" and item["audience"]["intent"] == "PUBLIC"
    assert not db.get_settings()["youtube_project_verified"]  # The informational audit flag is not a gate.

    assert scheduler.process_due(db.get_settings(), item["planned_at"] - 1)["publishing"] == 0
    assert scheduler.process_due(db.get_settings(), item["planned_at"])["publishing"] == 1
    row = queue.claim("publisher", "local-test")
    assert row is not None
    outcome = publisher.publish(host.Job(row, "local-test"))
    queue.complete(row, "local-test", outcome)
    assert db.fetch("scheduled_publications", item["id"])["status"] == "published"
    assert len(google.sessions) == len(google.videos) == 1
    assert next(iter(google.videos.values()))["status"]["privacyStatus"] == "public"
    assert scheduler.process_due(db.get_settings(), item["planned_at"] + 1)["publishing"] == 0
    assert scheduler.plan_new(db.get_settings(), item["planned_at"] + 1)["created"] == 0
    assert len(google.sessions) == 1 and not db.select("scheduled_publications", "platform = 'tiktok'")


@pytest.mark.parametrize("changed", ["channel", "visibility", "audience_confirmation"])
def test_stale_permission_does_not_hide_waiting_for_approval(env, client, changed):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler, state

    _, tmp_path = env
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_tiktok": False,
                      "audience_youtube_confirmed_at": time.time()})
    _ready_clip(tmp_path)
    scheduler.plan_new(db.get_settings(), time.time())
    item = db.select("scheduled_publications")[0]
    autopublish.enable("youtube", "private", False, 3, 9, 21, True)
    if changed == "channel":
        db.save_account("youtube", account_id="UCanotherlocal0000")
    elif changed == "visibility":
        client.post("/api/audience/youtube", headers=H, json={"intent": "public", "confirm": True})
        # A new Public choice preserves the old Private plan and permission. Only the newly Public plan waits.
        assert scheduler.auto_approve(item, db.get_settings(), time.time())
        newer = _ready_clip(tmp_path)
        scheduler.plan_new(db.get_settings(), time.time())
        item = db.select("scheduled_publications", "clip_id = ?", (newer["id"],))[0]
    else:
        db.save_settings({"audience_youtube_confirmed_at": 0.0})
    assert autopublish.active("youtube") and not autopublish.view(db.get_settings())["youtube"]["enabled"]
    assert not scheduler.auto_approve(item, db.get_settings(), time.time())
    assert scheduler.remind_approvals() == 1
    action = next(a for a in state.open_actions() if a["key"] == "approvals")
    assert action["kind"] == "approve" and "waiting for your OK" in action["title"]
    assert not env[0].sessions


@pytest.mark.parametrize("intent", ["selected", "owner_only", "local_only"])
def test_private_permission_refuses_unconfirmed_or_local_only_without_writes(env, client, intent):
    from clipfoundry import db

    db.save_settings({"audience_youtube": intent,
                      "audience_youtube_confirmed_at": time.time() if intent == "local_only" else 0.0})
    current = client.get("/api/autopilot/auto-publish").json()
    assert not current["youtube"]["enabled"] and not current["youtube"]["can_enable"]
    before = db.get_settings()
    result = client.post("/api/autopilot/auto-publish", headers=H, json={
        "platform": "youtube", "visibility": "private", "made_for_kids": False, "daily_limit": 3,
        "start_hour": 9, "end_hour": 21, "agreed": True,
    })
    assert result.status_code == 400 and "who watches" in result.json()["detail"]
    assert not db.select("publish_consents") and db.get_settings() == before
    assert not env[0].sessions


def test_handoff_failure_cannot_stop_existing_approved_posts(env, client, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host, hunter, queue, scheduler

    _, tmp_path = env
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_tiktok": False,
                      "audience_youtube_confirmed_at": time.time()})
    _ready_clip(tmp_path)
    scheduler.plan_new(db.get_settings(), time.time())
    item = db.select("scheduled_publications")[0]
    scheduler.approve(item["id"], {"options": {"made_for_kids": False}})
    db.update("scheduled_publications", item["id"], planned_at=time.time())

    def broken(**kwargs):
        raise OSError("local test failure")

    monkeypatch.setattr(hunter, "recover_ready_clips", broken)
    row = queue.enqueue("schedule_tick", {})
    result = scheduler.schedule_tick(host.Job(row, "local-test"))
    assert result["publishing"] == 1 and result["recovered_ready_clips"] == 0
    assert db.fetch("scheduled_publications", item["id"])["status"] == "publishing"

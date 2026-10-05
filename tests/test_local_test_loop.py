"""Local test discovery runs real media workers while fake connected accounts receive no uploads."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from fake_platforms import FakeGoogle
from zero_touch_support import BROKEN, FIRST, MANUAL, SECOND, CompleteLoopFixture

H = {"X-ClipFoundry": "1"}
UNKNOWN_CHANNEL = "UCunknown00000000001"


def wait_for(fixture: CompleteLoopFixture, condition, timeout: float = 240.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition()
        if result:
            return result
        time.sleep(0.1)
    snapshot = fixture.snapshot()
    raise AssertionError({
        "sources": [(s["external_id"], s["status"], s["status_note"]) for s in snapshot["sources"]],
        "jobs": [(j["kind"], j["status"], j["message"], j["error"]) for j in snapshot["jobs"][-20:]],
        "reports": [(r["status"], r["blockers"], r["warnings"]) for r in snapshot["reports"]],
        "posts": [(p["status"], p["status_note"]) for p in snapshot["posts"]],
    })


@pytest.mark.slow
def test_unknown_trends_make_checked_local_files_refill_and_survive_restart_without_uploads(monkeypatch, tmp_path):
    """Unknown reuse rights remain unknown while production workers select, render and check real clips.

    Only external platform/media inputs and Whisper are replaced. The broken input, refill, scoring, rendering,
    quality reports, scheduling checks and restart recovery all use production handlers and durable jobs.
    """
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.autopilot import autopublish, host, rights, state, verify
    from clipfoundry.pipeline import artifact
    from clipfoundry.publish import youtube
    from clipfoundry.publish.common import challenge_s256, code_verifier

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    google = FakeGoogle()
    fixture = worker = None
    try:
        for name, suffix in (("AUTH_URL", "/o/oauth2/v2/auth"), ("TOKEN_URL", "/token"), ("REVOKE_URL", "/revoke"),
                             ("API_URL", "/youtube/v3"), ("UPLOAD_URL", "/upload/youtube/v3/videos")):
            monkeypatch.setattr(youtube, name, google.url + suffix)
        db.init()
        db.save_settings({"youtube_client_id": "cid.apps.googleusercontent.com", "youtube_client_secret": "csecret"})
        verifier = code_verifier()
        callback = "http://127.0.0.1:8765/cb"
        code = google.approve(youtube.auth_url(db.get_settings(), callback, "state", challenge_s256(verifier)))
        youtube.exchange_code(db.get_settings(), code, verifier, callback)
        add_video = google.add_video

        def unknown_videos(external_id, title, channel="UCother0000000000", **options):
            if external_id in (BROKEN, FIRST, SECOND):
                channel = UNKNOWN_CHANNEL
            return add_video(external_id, title, channel, **options)

        # Set the public metadata before exposing each input, including repeat(), to avoid a discovery race.
        monkeypatch.setattr(google, "add_video", unknown_videos)
        fixture = CompleteLoopFixture(tmp_path / "data", google, monkeypatch.setattr)
        # Keep this scenario about automatic discovery: the fixture's separate manual-intake input is unused.
        google.catalog.pop(MANUAL)

        def checked_source(external_id):
            sources = db.select("sources", "external_id = ? AND status = 'analyzed'", (external_id,))
            if not sources:
                return None
            source = sources[0]
            clips = db.list_clips(source["project_id"])
            if len(clips) != 1 or clips[0]["status"] != "ready":
                return None
            reports = db.select("quality_reports", "clip_id = ? AND status = 'passed'", (clips[0]["id"],))
            return (source, clips[0], reports[0]) if reports else None

        def assert_local_file(source, clip, report):
            assert source["rights_status"] == rights.MANUAL and not source["user_added"]
            assert source["channel_id"] == UNKNOWN_CHANNEL and verify.confirmed(source)
            assert source["channel_id"] != db.get_account("youtube")["account_id"]
            assert not rights.evaluate(source, db.get_settings())["auto_allowed"]
            assert not source["rights_rule_id"]
            project = db.get_project(source["project_id"])
            assert project["origin"] == "autopilot" and project["options"]["local_test_mode"]
            output = Path(clip["output_path"])
            assert output.is_file() and output.stat().st_size > 0
            sha256 = artifact.sha256_file(output)
            assert sha256 == report["artifact_sha256"] == clip["render_info"]["artifact"]["sha256"]
            hunts = db.select("worker_jobs", "kind = 'hunt_source' AND ref_id = ?", (source["id"],))
            assert len(hunts) == 1 and hunts[0]["status"] == "completed" and hunts[0]["priority"] == 0
            assert source["id"] in fixture.transcriptions
            return hunts[0]

        def assert_no_uploads():
            assert not db.select("scheduled_publications") and not db.list_publications()
            assert not google.videos and not google.sessions
            assert not any(path.startswith("/upload/") or path.startswith("/session/") for path in google.calls)
            assert not db.select("worker_jobs", "kind = 'publish'")

        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            # Even a connected account with standing publishing consent stays idle in Local test mode.
            consent = client.post("/api/autopilot/auto-publish", headers=H, json={"platform": "youtube",
                                  "visibility": "public", "made_for_kids": False, "daily_limit": 4,
                                  "start_hour": 0, "end_hour": 24, "agreed": True})
            assert consent.status_code == 200 and autopublish.active("youtube")
            mode = client.put("/api/settings", json={"autopilot_local_test_mode": True,
                              "rights_allow_remote_download": False, "trend_topics": "",
                              "youtube_derived_metrics_approved": False, "autopilot_keep_awake": False})
            assert mode.status_code == 200 and mode.json()["autopilot_local_test_mode"]
            assert client.post("/api/autopilot/start", headers=H).status_code == 200
            worker = host.WorkerHost(poll=0.05)
            assert worker.start()
            failed = wait_for(fixture, lambda: db.select("sources", "external_id = ? AND status = 'failed'", (BROKEN,)))
            first, first_clip, first_report = wait_for(fixture, lambda: checked_source(FIRST))
            first_hunt = assert_local_file(first, first_clip, first_report)
            broken_hunt = db.select("worker_jobs", "kind = 'hunt_source' AND ref_id = ?", (failed[0]["id"],))[0]
            assert broken_hunt["status"] == "failed" and first_hunt["created_at"] >= broken_hunt["finished_at"]
            assert_no_uploads()
            finished = {job["kind"] for job in db.select("worker_jobs", "status = 'completed'")}
            assert {"trend_scan", "source_scout", "hunt_source", "analyze_source", "package_clip",
                    "quality_check", "schedule_tick"} <= finished

            saved = (first_clip["id"], first_clip["output_path"], first_report["id"],
                     first_report["artifact_sha256"], Path(first_clip["output_path"]).stat().st_mtime_ns)
            first_transcriptions = fixture.transcriptions.count(first["id"])
            worker.stop(timeout=30)
            worker = host.WorkerHost(poll=0.05)
            assert worker.start(wait_for_lock=10)
            assert state.enabled(db.get_settings()) and db.get_settings()["autopilot_local_test_mode"]
            assert not db.get_settings()["rights_allow_remote_download"]
            assert_no_uploads()
            fixture.repeat()
            second, second_clip, second_report = wait_for(fixture, lambda: checked_source(SECOND))
            assert_local_file(second, second_clip, second_report)
            assert second["id"] != first["id"] and second_clip["id"] != first_clip["id"]
            first_after, clip_after, report_after = checked_source(FIRST)
            assert saved == (clip_after["id"], clip_after["output_path"], report_after["id"],
                             report_after["artifact_sha256"], Path(clip_after["output_path"]).stat().st_mtime_ns)
            assert artifact.sha256_file(clip_after["output_path"]) == saved[3]
            assert first_after["id"] == first["id"]
            assert fixture.transcriptions.count(first["id"]) == first_transcriptions == 1
            assert_no_uploads()
    finally:
        if worker:
            worker.stop(timeout=30)
        if fixture:
            fixture.stop()
        google.stop()

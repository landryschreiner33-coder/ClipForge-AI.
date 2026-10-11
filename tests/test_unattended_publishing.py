"""Unattended posting and interrupted uploads, using disposable data and local fake platforms only."""
from __future__ import annotations

import copy
import datetime as dt
import time
from urllib.parse import urlparse

import pytest

from test_audience import api, env  # noqa: F401
from test_autopilot_publish import H, connect, make_item, run_publish
from test_public_publishing import public_item, public_setup


def test_all_day_window_keeps_midnight():
    from clipfoundry.autopilot import scheduler

    settings = {"autopilot_timezone": "UTC", "autopilot_active_start": 0, "autopilot_active_end": 24,
                "autopilot_min_gap_minutes": 45}
    times = scheduler.grid(settings, dt.date(2026, 10, 11), 3)
    assert [dt.datetime.fromtimestamp(t, dt.timezone.utc).hour for t in times] == [4, 12, 20]


def test_final_byte_evidence_without_a_session_cannot_initiate_an_upload(env):
    from clipfoundry.publish import youtube
    from clipfoundry.publish.common import PublishError

    google, _tiktok, tmp = env
    video = tmp / "previously-sent.mp4"
    video.write_bytes(b"synthetic previous transfer")
    with pytest.raises(PublishError) as held:
        youtube.upload(str(video), {}, None, may_be_complete=True)
    assert held.value.code == youtube.OUTCOME_UNKNOWN and not google.sessions


def test_scheduled_transport_retry_preserves_the_original_unfinished_session(env, api, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import queue
    from clipfoundry.publish import youtube

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    monkeypatch.setattr(youtube, "_pause", lambda *_args: None)
    google.fail_puts = 7
    item = public_item(tmp)
    with pytest.raises(queue.Retry):
        run_publish(item["id"])
    row = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(row["publication_id"])
    assert pub["info"]["upload_session"] and not pub["info"].get("final_chunk_at")
    assert len(google.sessions) == 1 and not google.videos
    run_publish(item["id"])
    completed = db.fetch("scheduled_publications", item["id"])
    assert completed["status"] == "published" and completed["publication_id"] == pub["id"]
    assert len(google.sessions) == 1 and len(google.videos) == 1


@pytest.mark.parametrize("hold", ["pause", "permission", "quality", "audience"])
def test_unstarted_scheduled_upload_rechecks_controls_after_initial_platform_wait(env, api, monkeypatch, hold):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, publisher, queue, scheduler, state

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    consent = autopublish.enable("youtube", "public", False, 3, 0, 24, True)
    item = make_item(tmp)
    from clipfoundry.publish import audience

    db.update("scheduled_publications", item["id"], privacy="public",
              audience=audience.check("youtube", "public", db.get_settings()))
    assert scheduler.auto_approve(db.fetch("scheduled_publications", item["id"]), db.get_settings(), time.time())
    original = google.handle
    remaining = [1]

    def initially_busy(handler, method, body):
        if remaining[0] and method == "POST" and urlparse(handler.path).path == "/upload/youtube/v3/videos":
            remaining[0] -= 1
            return handler._send(429, {"error": {"code": 429, "message": "rate limited",
                                                "errors": [{"reason": "rateLimitExceeded"}]}},
                                 {"Retry-After": "600"})
        return original(handler, method, body)

    monkeypatch.setattr(google, "handle", initially_busy)
    with pytest.raises(queue.Wait) as waiting:
        run_publish(item["id"])
    assert waiting.value.reason == "platform_wait"
    row = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(row["publication_id"])
    assert not pub["info"].get("upload_session") and not google.sessions
    # Simulate the recorded platform wait becoming due; all owner controls still apply to a new session.
    monkeypatch.setattr(publisher, "blocked_until", lambda _platform: (0.0, ""))
    if hold == "pause":
        db.save_settings({"autopilot_publishing_paused": True})
        with pytest.raises(queue.Wait) as held:
            run_publish(item["id"])
        assert held.value.reason == "publishing_paused"
        db.save_settings({"autopilot_publishing_paused": False})
        run_publish(item["id"])
        finished = db.fetch("scheduled_publications", item["id"])
        assert finished["publication_id"] == pub["id"] and finished["status"] == "published"
        assert len(google.sessions) == 1 and len(google.videos) == 1
        return
    if hold == "permission":
        db.update("publish_consents", consent["id"], revoked_at=time.time())
        with pytest.raises(queue.Fail, match="permission"):
            run_publish(item["id"])
        assert not db.fetch("scheduled_publications", item["id"])["publication_id"]
    elif hold == "quality":
        report = db.select("quality_reports", "clip_id = ?", (item["clip_id"],))[0]
        db.update("quality_reports", report["id"], status="failed", blockers=["Failed final-file check"])
        with pytest.raises(queue.Fail, match="final quality"):
            run_publish(item["id"])
    else:
        state.put("audience_halt:youtube", {"detail": "Check a previous video's audience"})
        with pytest.raises(queue.Wait) as held:
            run_publish(item["id"])
        assert held.value.reason == "audience_halt"
    assert not google.sessions and not google.videos


@pytest.mark.parametrize("evidence", ["older", "missing_time", "different_metadata", "ambiguous"])
def test_scheduled_unknown_outcome_never_adopts_an_unrelated_same_title(env, api, monkeypatch, evidence):
    from clipfoundry import db
    from clipfoundry.publish import youtube

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    monkeypatch.setattr(youtube, "_pause", lambda *_args: None)
    google.drop_final_reply = google.expire_sessions = google.hide_uploads = True
    item = public_item(tmp)
    run_publish(item["id"])
    row = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(row["publication_id"])
    assert row["status"] == "reconciling" and pub["info"]["outcome_unknown"]
    video = next(iter(google.videos.values()))
    if evidence == "older":
        video["uploaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(pub["info"]["session_started"] - 60))
    elif evidence == "missing_time":
        video["uploaded_at"] = "not a platform timestamp"
    elif evidence == "different_metadata":
        video["snippet"]["description"] = "An unrelated video with the same title"
    else:
        other = copy.deepcopy(video)
        other["id"] = "another-same-title-video"
        google.videos[other["id"]] = other
    google.hide_uploads = False
    calls = len(google.log)
    run_publish(item["id"])
    row = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(row["publication_id"])
    assert row["status"] == "reconciling" and not pub["remote_id"]
    assert pub["info"]["outcome_unknown"]
    assert all(method == "GET" for method, _path in google.log[calls:])


@pytest.mark.parametrize("status", ["uploading", "queued"])
def test_manual_crash_after_final_bytes_becomes_durable_read_only_unknown_hold(env, api, monkeypatch, status):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    class SimulatedCrash(BaseException):
        pass

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    clip_id = make_item(tmp)["clip_id"]
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    writer = jobs._progress_writer

    def crashing_writer(pub_id):
        write = writer(pub_id)

        def progress(fraction):
            write(fraction)
            if fraction == 1:
                raise SimulatedCrash()

        return progress

    monkeypatch.setattr(jobs, "_progress_writer", crashing_writer)
    body = {"title": "Exactly one interrupted upload", "description": "Original confirmed description",
            "privacy": "public", "made_for_kids": False, "confirm": True}
    result = api.post(f"/api/clips/{clip_id}/publish/youtube", headers=H, json=body)
    assert result.status_code == 200, result.text
    pub_id = result.json()["id"]
    with pytest.raises(SimulatedCrash):
        jobs.worker._run(pub_id)
    pub = db.get_publication(pub_id)
    assert pub["info"]["final_chunk_at"] and len(google.videos) == 1
    if status == "queued":
        db.update_publication(pub_id, status="queued", info={**pub["info"], "retry_at": time.time() + 600})
    google.hide_uploads = True
    db.interrupted_work()
    held = db.get_publication(pub_id)
    assert held["status"] == "processing" and held["info"]["outcome_unknown"]
    assert jobs.worker.resume_waiting() == 0
    assert api.post(f"/api/clips/{clip_id}/publish/youtube", headers=H, json=body).status_code == 409
    calls = len(google.log)
    jobs.worker._run(pub_id)
    assert db.get_publication(pub_id)["info"]["outcome_unknown"]
    assert all(method == "GET" for method, _path in google.log[calls:])
    google.hide_uploads = False
    found = api.post(f"/api/publications/{pub_id}/refresh", headers=H)
    assert found.status_code == 200, found.text
    assert found.json()["status"] == "done" and found.json()["privacy"] == "public"
    assert found.json()["delivery"]["audience_setup"] == "public_api_verified"
    assert len(google.videos) == 1 and len(google.sessions) == 1


@pytest.mark.parametrize("manual", [False, True])
def test_exhausted_final_chunk_errors_hold_without_another_upload_session(env, api, monkeypatch, manual):
    from clipfoundry import db
    from clipfoundry.publish import jobs, youtube

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    monkeypatch.setattr(youtube, "_pause", lambda *_args: None)
    # Fail data transfers and all their status probes after the final-byte marker. The outcome remains unknown.
    google.fail_puts = 20
    monkeypatch.setattr(youtube, "_resume_offset", lambda *_args: (0, None))
    item = make_item(tmp, size=100_000)
    if manual:
        monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
        result = api.post(f"/api/clips/{item['clip_id']}/publish/youtube", headers=H, json={
            "title": "One file despite interrupted replies", "privacy": "public", "made_for_kids": False,
            "confirm": True})
        assert result.status_code == 200, result.text
        pub_id = result.json()["id"]
        jobs.worker._run(pub_id)
        assert db.get_publication(pub_id)["status"] == "processing"
    else:
        from clipfoundry.autopilot import scheduler

        item = scheduler.approve(item["id"], {"privacy": "public", "options": {"made_for_kids": False}})
        run_publish(item["id"])
        row = db.fetch("scheduled_publications", item["id"])
        pub_id = row["publication_id"]
        assert row["status"] == "reconciling"
    assert db.get_publication(pub_id)["info"]["outcome_unknown"]
    assert len(google.sessions) == 1 and not google.videos
    calls = len(google.log)
    if manual:
        jobs.worker._run(pub_id)
    else:
        run_publish(item["id"])
    assert all(method == "GET" for method, _path in google.log[calls:])
    assert len(google.sessions) == 1


@pytest.mark.parametrize("manual", [False, True])
def test_cancel_after_final_byte_marker_retains_uncertainty(env, api, monkeypatch, manual):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler
    from clipfoundry.publish import jobs
    from clipfoundry.publish.common import Cancelled

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    original = jobs.run_youtube

    def canceled_after_final(pub, cancelled):
        def stop(_fraction):
            raise Cancelled()

        with monkeypatch.context() as during_transfer:
            during_transfer.setattr(jobs, "_progress_writer", lambda _pub_id: stop)
            original(pub, cancelled)

    monkeypatch.setitem(jobs.RUNNERS, "youtube", canceled_after_final)
    item = make_item(tmp, size=100_000)
    if manual:
        monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
        result = api.post(f"/api/clips/{item['clip_id']}/publish/youtube", headers=H, json={
            "title": "Canceled reply after upload", "privacy": "public", "made_for_kids": False, "confirm": True})
        assert result.status_code == 200, result.text
        pub_id = result.json()["id"]
        jobs.worker._run(pub_id)
        pub = db.get_publication(pub_id)
        assert pub["status"] == "processing" and pub["info"]["outcome_unknown"]
        assert "Nothing was published" not in pub["message"]
        assert api.post(f"/api/clips/{item['clip_id']}/publish/youtube", headers=H, json={
            "title": "Canceled reply after upload", "privacy": "public", "made_for_kids": False,
            "confirm": True}).status_code == 409
    else:
        item = scheduler.approve(item["id"], {"privacy": "public", "options": {"made_for_kids": False}})
        with pytest.raises(queue.Canceled):
            run_publish(item["id"])
        row = db.fetch("scheduled_publications", item["id"])
        pub_id = row["publication_id"]
        assert row["status"] == "published"  # Strict read-back found the accepted file even though work was canceled.
        assert db.get_publication(pub_id)["privacy"] == "public"
    assert len(google.videos) == 1 and len(google.sessions) == 1


def test_manual_callback_error_after_upload_acceptance_holds_existing_outcome(env, api, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    item = make_item(tmp, size=100_000)
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)

    def failed_writer(_pub_id):
        def progress(_fraction):
            raise RuntimeError("A local callback failed after YouTube accepted the file")

        return progress

    monkeypatch.setattr(jobs, "_progress_writer", failed_writer)
    result = api.post(f"/api/clips/{item['clip_id']}/publish/youtube", headers=H, json={
        "title": "One accepted upload", "privacy": "public", "made_for_kids": False, "confirm": True})
    assert result.status_code == 200, result.text
    pub_id = result.json()["id"]
    jobs.worker._run(pub_id)
    held = db.get_publication(pub_id)
    assert held["status"] == "processing" and held["info"]["outcome_unknown"]
    assert held["progress"] == 0  # A failed measurement cannot establish that all bytes were confirmed.
    assert len(google.videos) == 1
    calls = len(google.log)
    jobs.worker._run(pub_id)
    assert db.get_publication(pub_id)["status"] == "done"
    assert all(method == "GET" for method, _path in google.log[calls:])
    assert len(google.sessions) == 1 and len(google.videos) == 1


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("code", ["reconnect", "setup", "scope", "quotaExceeded", "quota_budget",
                                 "insufficientPermissions"])
def test_late_error_after_accepted_final_bytes_keeps_hold_through_reconnection(env, api, monkeypatch, manual, code):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, state
    from clipfoundry.publish import jobs, youtube
    from clipfoundry.publish.common import PublishError

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    google.drop_final_reply = google.hide_uploads = True
    monkeypatch.setattr(youtube, "_pause", lambda *_args: None)

    def late_probe_error(*_args):
        assert len(google.videos) == 1  # The platform accepted the exact final bytes before its reply was lost.
        if code == "reconnect":
            google.revoked = True
            youtube.Token(db.get_settings()).get(force=True)  # Exercise actual invalid_grant handling.
        raise PublishError(f"Late status read failed ({code})", f"Resolve {code} before checking the upload.", code)

    monkeypatch.setattr(youtube, "_resume_offset", late_probe_error)
    item = make_item(tmp, size=100_000)
    body = {"title": "Exactly one accepted upload despite late error", "privacy": "public",
            "made_for_kids": False, "confirm": True}
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    if manual:
        result = api.post(f"/api/clips/{item['clip_id']}/publish/youtube", headers=H, json=body)
        assert result.status_code == 200, result.text
        pub_id = result.json()["id"]
        jobs.worker._run(pub_id)
    else:
        item = scheduler.approve(item["id"], {"privacy": "public", "options": {"made_for_kids": False}})
        run_publish(item["id"])
        row = db.fetch("scheduled_publications", item["id"])
        assert row["status"] == "reconciling"
        pub_id = row["publication_id"]
        if code in ("reconnect", "setup", "scope", "insufficientPermissions"):
            assert any(a["key"] == "connect:youtube" for a in state.open_actions())
    held = db.get_publication(pub_id)
    assert held["info"]["outcome_unknown"] and held["info"]["final_chunk_at"]
    assert held["info"]["outcome_error"]["code"] == code
    assert held["info"]["outcome_error"]["fix"] in held["fix"]
    session = held["info"]["upload_session"]
    assert len(google.sessions) == len(google.videos) == 1

    google.revoked = False
    connect(google, tiktok)  # Restoring access must not authorize a second upload.
    assert api.post(f"/api/clips/{item['clip_id']}/publish/youtube", headers=H, json=body).status_code == 409
    calls = len(google.log)
    if manual:
        jobs.worker._run(pub_id)
    else:
        run_publish(item["id"])
        assert db.fetch("scheduled_publications", item["id"])["publication_id"] == pub_id
    assert db.get_publication(pub_id)["info"]["upload_session"] == session
    assert db.get_publication(pub_id)["info"]["outcome_unknown"]
    assert all(method == "GET" for method, _path in google.log[calls:])

    google.hide_uploads = False
    calls = len(google.log)
    if manual:
        found = api.post(f"/api/publications/{pub_id}/refresh", headers=H)
        assert found.status_code == 200, found.text
        assert found.json()["status"] == "done"
    else:
        run_publish(item["id"])
        assert db.fetch("scheduled_publications", item["id"])["status"] == "published"
    assert db.get_publication(pub_id)["privacy"] == "public"
    assert all(method == "GET" for method, _path in google.log[calls:])
    assert len(google.sessions) == len(google.videos) == 1

"""Durable, safe link intake and official metadata checks without real accounts or downloads."""
from __future__ import annotations

import ipaddress
import time
import pytest

from fake_platforms import FakeGoogle

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def data(monkeypatch, tmp_path):
    from clipfoundry import db, netguard

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))

    def resolve(host):
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            return [ipaddress.ip_address("127.0.0.1" if host == "localhost" else "8.8.8.8")]

    monkeypatch.setattr(netguard, "resolve", resolve)
    db.init()
    return tmp_path


@pytest.fixture()
def google(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import youtube

    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    fake = FakeGoogle()
    monkeypatch.setattr(youtube, "API_URL", fake.url + "/youtube/v3")
    db.save_settings({"youtube_api_key": fake.api_key, "rights_allow_remote_download": True,
                      "autopilot_enabled": True})
    yield fake
    fake.stop()


def run_identifier(source_id):
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    row = queue.claim("source_scout", "intake-test")
    assert row and row["kind"] == "identify_link" and row["payload"]["source_id"] == source_id
    job = host.Job(row, "intake-test")
    try:
        result = host.HANDLERS["identify_link"](job)
        queue.complete(row, "intake-test", result)
        return result
    except queue.Wait as exc:
        queue.wait(row, "intake-test", exc.reason, exc.seconds, exc.message)
        raise
    except queue.Fail as exc:
        queue.fail(row, "intake-test", str(exc))
        raise


def test_platform_aliases_share_one_source_and_preserve_queue_across_restart(data):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue

    first = intake.add("https://youtu.be/abc12345678?si=tracking")
    repeated = intake.add("https://www.youtube.com/shorts/abc12345678?feature=share")
    assert not first["already_added"] and repeated["already_added"]
    assert first["item"]["id"] == repeated["item"]["id"]
    assert first["item"]["status_label"] == "Waiting"
    row = queue.jobs()[0]
    assert row["kind"] == "identify_link" and row["priority"] == 80
    assert len(db.select("sources")) == len(queue.jobs()) == 1
    db._ready.clear()
    assert intake.links()[0]["id"] == first["item"]["id"]
    assert queue.jobs()[0]["payload"] == {"source_id": first["item"]["id"]}


@pytest.mark.parametrize("url", ["file:///tmp/movie.mp4", "javascript:alert(1)", "https://user:pass@example.org/a.mp4",
                                   "http://127.0.0.1/video.mp4", "http://[::1]/live.m3u8",
                                   "http://169.254.169.254/latest", "http://192.168.1.2/video.mp4",
                                   "https://www.youtube.com/playlist?list=PL1"])
def test_private_auth_and_non_video_platform_urls_are_refused(data, url):
    from clipfoundry import db
    from clipfoundry.autopilot import intake

    with pytest.raises(ValueError):
        intake.add(url)
    assert not db.select("sources")


def test_priority_move_does_not_cancel_or_interrupt_a_running_gpu_step(data):
    from clipfoundry.autopilot import intake, queue

    running = queue.enqueue("hunt_source", {"source_id": "existing"}, priority=60)
    claimed = queue.claim("clip_hunter", "gpu-worker")
    assert claimed["id"] == running["id"]
    a = intake.add("https://www.youtube.com/watch?v=link0000001")["item"]
    b = intake.add("https://www.youtube.com/watch?v=link0000002")["item"]
    intake.action(a["id"], "prioritize")
    intake.action(b["id"], "prioritize")
    assert queue.source_priority(a["id"], 99) == 98
    assert queue.source_priority(b["id"], 80) == 99
    assert queue.source_priority(b["id"], 100) == 100
    claimed_intake = queue.claim("source_scout", "scout")
    assert claimed_intake["payload"]["source_id"] == b["id"] and claimed_intake["priority"] == 99
    gpu_job = queue.get(running["id"])
    assert gpu_job["status"] == "running" and gpu_job["cancel_requested"] == 0


def test_official_youtube_metadata_hands_off_local_work_without_claiming_reuse_rights(google):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue, rights, verify

    google.add_video("abc12345678", "Public interview", "UCother0000000000")
    row = intake.add("https://youtu.be/abc12345678")["item"]
    run_identifier(row["id"])
    source = db.fetch("sources", row["id"])
    assert source["title"] == "Public interview" and verify.confirmed(source)
    assert source["user_added"] and source["rights_status"] == rights.MANUAL
    assert not rights.evaluate(source)["auto_allowed"] and rights.local_allowed(source)
    handoff = next(j for j in queue.jobs() if j["kind"] == "hunt_source")
    assert handoff["priority"] == 80 and handoff["idem_key"] == f"hunt:{row['id']}"
    assert not db.select("source_rights")  # A pasted link never invents a license or ownership.


def test_upcoming_live_wait_is_durable_nonblocking_and_transitions_to_capture(google):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue

    google.add_video("stream12345", "Press conference")
    video = google.catalog["stream12345"]
    video["snippet"]["liveBroadcastContent"] = "upcoming"
    video["liveStreamingDetails"] = {"scheduledStartTime": "2026-10-02T23:00:00Z"}
    added = intake.add("https://www.youtube.com/live/stream12345")["item"]
    with pytest.raises(queue.Wait) as waiting:
        run_identifier(added["id"])
    assert waiting.value.reason == "stream_start"
    before = intake.links()[0]
    assert before["status"] == "waiting_stream" and before["scheduled_at"]
    other = queue.enqueue("trend_scan", priority=0)
    assert queue.claim("trend_scout", "another-worker")["id"] == other["id"]
    db._ready.clear()
    assert intake.links()[0]["status"] == "waiting_stream"
    video["snippet"]["liveBroadcastContent"] = "live"
    db.execute("DELETE FROM api_cache")
    identifier = next(j for j in queue.jobs() if j["kind"] == "identify_link")
    queue.wake(identifier["id"])
    run_identifier(added["id"])
    captures = [j for j in queue.jobs() if j["kind"] == "live_capture"]
    assert len(captures) == 1 and captures[0]["priority"] == 80
    assert db.fetch("sources", added["id"])["live_status"] == "live"


def test_access_failure_keeps_item_and_does_not_stop_another_link(google):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue

    db.save_settings({"rights_allow_remote_download": False})
    google.add_video("bad12345678", "Video without supported download")
    bad = intake.add("https://youtu.be/bad12345678")["item"]
    good = intake.add("https://youtu.be/ok123456789")["item"]
    with pytest.raises(queue.Fail, match="cannot access the video file"):
        run_identifier(bad["id"])
    result = next(i for i in intake.links() if i["id"] == bad["id"])
    assert result["status"] == "inaccessible" and result["can_retry"]
    assert next(i for i in intake.links() if i["id"] == good["id"])["status"] == "waiting"
    assert not db.select("action_items") and db.get_settings()["autopilot_enabled"]
    assert queue.claim("source_scout", "next-worker")["payload"]["source_id"] == good["id"]


def test_cancel_remove_retry_and_duplicate_do_not_restart_without_explicit_retry(data):
    from clipfoundry.autopilot import intake, queue

    added = intake.add("https://youtu.be/cancel12345")["item"]
    canceled = intake.action(added["id"], "cancel")
    assert canceled["status"] == "canceled" and canceled["can_retry"]
    assert intake.add(added["url"])["already_added"]
    assert queue.jobs()[0]["status"] == "canceled"
    retried = intake.action(added["id"], "retry")
    assert retried["status"] == "waiting" and queue.jobs()[0]["status"] == "queued"
    intake.action(added["id"], "remove")
    assert not intake.links()
    # Identity stays durable even when hidden; re-adding does not cause duplicate processing.
    assert intake.add(added["url"])["item"]["id"] == added["id"]
    assert queue.jobs()[0]["status"] == "canceled"


def test_api_actions_are_local_and_app_request_guarded(data):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        assert c.post("/api/autopilot/links", json={"url": "https://youtu.be/api12345678"}).status_code == 403
        response = c.post("/api/autopilot/links", headers=H, json={"url": "https://youtu.be/api12345678"})
        assert response.status_code == 200
        row = response.json()["item"]
        assert c.get("/api/autopilot/links").json()[0]["id"] == row["id"]
        assert c.post(f"/api/autopilot/links/{row['id']}/cancel", headers=H).json()["status"] == "canceled"
        assert c.post("/api/autopilot/links/missing/cancel", headers=H).status_code == 404
        assert c.post(f"/api/autopilot/links/{row['id']}/unknown", headers=H).status_code == 409


def test_old_link_cancellation_is_not_lost_among_new_system_jobs(data):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue

    added = intake.add("https://youtu.be/oldlink1234")["item"]
    original = queue.jobs()[0]
    now = time.time() + 1
    with db.connect() as conn:
        conn.executemany("INSERT INTO worker_jobs (id,kind,worker,status,created_at,updated_at) "
                         "VALUES (?,'selftest','maintenance','completed',?,?)",
                         [(f"new-{i}", now + i, now + i) for i in range(2100)])
    assert intake.links()[0]["can_cancel"]
    intake.action(added["id"], "cancel")
    assert queue.get(original["id"])["status"] == "canceled"


def test_retry_resumes_prepared_analysis_without_restarting_its_upstream_jobs(data):
    from clipfoundry import config, db
    from clipfoundry.autopilot import intake, queue

    added = intake.add("https://youtu.be/retry1234567")["item"]
    project = db.create_project("Interrupted interview", origin="autopilot", source_id=added["id"])
    pdir = config.projects_dir() / project["id"]
    pdir.mkdir(parents=True, exist_ok=True)
    for name, value in (("transcript.json", "{}"), ("loudness.json", "{}"), ("candidates.json", "[]")):
        (pdir / name).write_text(value)
    media = pdir / "source.mp4"
    media.write_bytes(b"preserved original")
    db.update_project(project["id"], source_path=str(media))
    db.update("sources", added["id"], project_id=project["id"], status="failed", error="Interrupted render")
    identifier = queue.jobs()[0]
    db.update("worker_jobs", identifier["id"], status="failed")
    hunt = queue.enqueue("hunt_source", {"source_id": added["id"]}, ref=("source", added["id"]))
    db.update("worker_jobs", hunt["id"], status="failed")
    analyzer = queue.enqueue("analyze_source", {"source_id": added["id"], "project_id": project["id"]},
                             ref=("source", added["id"]))
    db.update("worker_jobs", analyzer["id"], status="failed")
    intake.action(added["id"], "retry")
    assert queue.get(analyzer["id"])["status"] == "queued"
    assert queue.get(hunt["id"])["status"] == queue.get(identifier["id"])["status"] == "failed"
    assert media.read_bytes() == b"preserved original"


def test_ended_stream_with_partial_recording_resumes_capture_recovery(google):
    from clipfoundry import config, db
    from clipfoundry.autopilot import intake, queue

    video = google.add_video("ended123456", "Completed press conference")
    video["liveStreamingDetails"] = {"actualStartTime": "2026-10-02T01:00:00Z",
                                     "actualEndTime": "2026-10-02T02:00:00Z"}
    added = intake.add("https://www.youtube.com/live/ended123456")["item"]
    project = db.create_project("Partial recording", origin="live", source_id=added["id"])
    live_dir = config.projects_dir() / project["id"] / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "state.json").write_text('{"segments": [{"name": "r001_00000.mkv"}]}')
    db.update("sources", added["id"], project_id=project["id"], kind="live")
    run_identifier(added["id"])
    assert db.fetch("sources", added["id"])["live_status"] == "ended"
    assert [j["kind"] for j in queue.jobs() if j["status"] == "queued"] == ["live_capture"]


def test_live_capture_wait_keeps_watching_status_and_retry_waits_for_safe_cancel(data):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue

    added = intake.add("https://example.org/live.m3u8")["item"]
    identifier = queue.jobs()[0]
    db.update("worker_jobs", identifier["id"], status="completed")
    db.update("sources", added["id"], live_status="live", status="ingesting")
    capture = queue.enqueue("live_capture", {"source_id": added["id"]}, ref=("source", added["id"]))
    db.update("worker_jobs", capture["id"], status="waiting", wait_reason="live")
    assert intake.links()[0]["status"] == "watching_live"
    claimed = queue.claim("live_monitor", "capture-owner")
    assert claimed["id"] == capture["id"]
    view = intake.action(added["id"], "cancel")
    assert view["status"] == "canceled" and not view["can_retry"]
    with pytest.raises(ValueError, match="already waiting"):
        intake.action(added["id"], "retry")
    assert queue.get(capture["id"])["cancel_requested"] == 1


def test_cancel_preserves_ready_local_clip_and_existing_upload_outcomes_but_cancels_future_posts(data):
    import hashlib

    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue, rights

    added = intake.add("https://example.org/owned.mp4")["item"]
    rights.add_rule("source", added["id"], rights.OWNED, "My recording")
    project = db.create_project("My recording", origin="autopilot", source_id=added["id"])
    output = data / "completed.mp4"
    output.write_bytes(b"completed local clip")
    clip = db.create_clip(project["id"], start=0, end=20, status="ready", output_path=str(output))
    db.insert("quality_reports", {"clip_id": clip["id"], "artifact_path": str(output), "status": "passed",
                                  "artifact_sha256": hashlib.sha256(output.read_bytes()).hexdigest()})
    db.update("sources", added["id"], project_id=project["id"], status="analyzed", clips_selected=1)
    posts = {status: db.insert("scheduled_publications", {"clip_id": clip["id"], "source_id": added["id"],
                                                         "platform": "youtube", "status": status})
             for status in ("approved", "awaiting_approval", "publishing", "reconciling", "published")}
    queued = queue.enqueue("publish", {"scheduled_id": posts["approved"]["id"]},
                           ref=("scheduled", posts["approved"]["id"]))
    uncertain = queue.enqueue("publish", {"scheduled_id": posts["reconciling"]["id"]},
                              ref=("scheduled", posts["reconciling"]["id"]))
    intake.action(added["id"], "cancel")
    assert all(db.fetch("scheduled_publications", posts[status]["id"])["status"] == "canceled"
               for status in ("approved", "awaiting_approval"))
    assert all(db.fetch("scheduled_publications", posts[status]["id"])["status"] == status
               for status in ("publishing", "reconciling", "published"))
    assert queue.get(queued["id"])["status"] == "canceled"
    assert queue.get(uncertain["id"])["status"] == "queued"
    assert db.get_clip(clip["id"])["status"] == "ready" and output.read_bytes() == b"completed local clip"
    assert db.select("quality_reports")[0]["status"] == "passed"


def test_completed_source_does_not_show_historical_access_failure(data):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue

    added = intake.add("https://youtu.be/ready123456")["item"]
    identifier = queue.jobs()[0]
    db.update("worker_jobs", identifier["id"], status="failed", error="Old server failure")
    db.update("sources", added["id"], status="analyzed", clips_selected=2, error="")
    assert intake.links()[0]["status"] == "ready"


def test_pasted_link_reuses_legacy_stream_identity_project_and_job(data):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue, rights

    original = db.insert("sources", {"platform": "stream", "external_id": "legacy-feed-sha1",
                                     "url": "https://EXAMPLE.org:443/live.m3u8?token=signed&view=main#player",
                                     "title": "Configured press conference", "kind": "live", "live_status": "live",
                                     "status": "ingesting", "feed_id": "configured-stream"})
    rights.add_rule("source", original["id"], rights.OWNED, "My public stream")
    project = db.create_project("Existing recording", origin="live", source_id=original["id"])
    db.update("sources", original["id"], project_id=project["id"])
    capture = queue.enqueue("live_capture", {"source_id": original["id"]}, priority=0,
                            idem_key=f"live:{original['id']}", ref=("source", original["id"]))
    result = intake.add("https://example.org/live.m3u8?token=signed&view=main")
    assert result["already_added"] and result["item"]["id"] == original["id"]
    assert result["item"]["project_id"] == project["id"]
    assert len(db.select("sources")) == len(db.select("projects")) == len(queue.jobs()) == 1
    current = db.fetch("sources", original["id"])
    assert current["external_id"] == "legacy-feed-sha1" and current["feed_id"] == "configured-stream"
    assert rights.evaluate(current)["status"] == rights.OWNED
    assert queue.get(capture["id"])["priority"] == 80


def test_pasting_canceled_legacy_video_does_not_create_a_job_until_explicit_retry(data):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue

    original = db.insert("sources", {"platform": "url", "external_id": "old-manual-sha1",
                                     "url": "https://example.org/video.mp4?version=1", "title": "Canceled video",
                                     "status": "canceled", "status_note": "Canceled by you"})
    result = intake.add(original["url"])
    assert result["already_added"] and result["item"]["id"] == original["id"]
    assert result["item"]["status"] == "canceled" and result["item"]["can_retry"]
    assert not queue.jobs() and len(db.select("sources")) == 1
    intake.action(original["id"], "retry")
    assert len(queue.jobs()) == 1 and queue.jobs()[0]["kind"] == "identify_link"
    assert queue.jobs()[0]["payload"] == {"source_id": original["id"]}


def test_legacy_dedup_preserves_blocks_and_distinct_direct_query_parameters(data):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue, rights

    original = db.insert("sources", {"platform": "url", "external_id": "blocked-sha1",
                                     "url": "https://example.org/video.mp4?version=1", "title": "Blocked video",
                                     "status": "blocked"})
    rights.add_rule("source", original["id"], rights.BLOCKED, "Do not process")
    repeated = intake.add(original["url"])
    assert repeated["already_added"] and repeated["item"]["id"] == original["id"]
    assert not queue.jobs() and rights.evaluate(db.fetch("sources", original["id"]))["status"] == rights.BLOCKED
    different = intake.add("https://example.org/video.mp4?version=2")
    assert not different["already_added"] and different["item"]["id"] != original["id"]


def test_move_to_top_keeps_manual_work_claimable_while_autopilot_is_off(data):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue

    db.save_settings({"autopilot_enabled": False})
    added = intake.add("https://youtu.be/manual12345")["item"]
    manual = queue.enqueue("hunt_source", {"source_id": added["id"]}, priority=100,
                           ref=("source", added["id"]))
    intake.action(added["id"], "prioritize")
    claimed = queue.claim("clip_hunter", "manual-step", min_priority=100)
    assert claimed and claimed["id"] == manual["id"] and claimed["priority"] == 100


def test_explicit_retry_keeps_user_link_priority_above_automatic_work(data):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue

    added = intake.add("https://example.org/retry.mp4")["item"]
    identifier = queue.jobs()[0]
    db.update("worker_jobs", identifier["id"], status="completed")
    db.update("sources", added["id"], status="failed", error="Interrupted download")
    failed = queue.enqueue("hunt_source", {"source_id": added["id"]}, priority=0,
                           ref=("source", added["id"]))
    db.update("worker_jobs", failed["id"], status="failed")
    queue.enqueue("hunt_source", {"source_id": "automatic"}, priority=10)
    intake.action(added["id"], "retry")
    claimed = queue.claim("clip_hunter", "next-step")
    assert claimed and claimed["id"] == failed["id"] and claimed["priority"] == 80


@pytest.mark.parametrize("official_category, expected_category, expected_reuse", [
    ("10", "Music", "MANUAL_CONFIRMATION_REQUIRED"),
    ("22", "People & Blogs", "ALLOWLISTED"),
])
def test_official_category_replaces_stale_metadata_before_creator_only_reuse_is_evaluated(
        google, official_category, expected_category, expected_reuse):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, rights

    channel = "UCperformer000001"
    google.add_video("category123", "Evening performance", channel, category=official_category)
    added = intake.add("https://youtu.be/category123")["item"]
    db.update("sources", added["id"], category="Music" if official_category == "22" else "People & Blogs")
    rights.add_rule("channel", channel, rights.ALLOWLISTED, "Creator's original material", platform="youtube")
    run_identifier(added["id"])
    source = db.fetch("sources", added["id"])
    assert source["category"] == expected_category
    decision = rights.evaluate(source)
    assert decision["status"] == expected_reuse
    assert rights.local_allowed(source)  # Both remain usable locally; this metadata grants no publishing right.
    if official_category == "10":
        assert not decision["auto_allowed"]
        with pytest.raises(rights.RightsBlocked):
            rights.gate(source, "schedule")

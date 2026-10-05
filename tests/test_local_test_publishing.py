"""Local AI tests hold every upload and keep interrupted uploads resumable without creating another post."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from test_autopilot_publish import connect, env, make_item, run_publish
from test_autopilot_scheduler import make_clip

H = {"X-ClipFoundry": "1"}


def publication(item: dict) -> dict:
    from clipfoundry import db

    clip = db.get_clip(item["clip_id"])
    return db.create_publication(clip["id"], item["platform"], project_id=clip["project_id"],
                                 status="queued", title=item["title"], description=item["description"],
                                 requested_privacy="private" if item["platform"] == "youtube" else "SELF_ONLY",
                                 options={"made_for_kids": False, "duration": 20}, video_path=clip["output_path"])


def test_local_test_mode_holds_planning_due_posts_and_orphans(env):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler

    _, _, tmp = env
    make_clip(tmp, "Ordinary automatic clip", 80)
    due = make_item(tmp, approve={"options": {"made_for_kids": False}}, planned_in=60)
    orphan = make_item(tmp)
    db.update("scheduled_publications", orphan["id"], status="publishing", updated_at=time.time() - 600)
    before = db.select("scheduled_publications")
    stale_settings = db.get_settings()
    db.save_settings({"autopilot_local_test_mode": True})

    assert scheduler.candidates(stale_settings, time.time()) == []
    assert scheduler.plan_new(stale_settings, time.time())["created"] == 0
    assert scheduler.process_due(stale_settings, time.time())["publishing"] == 0
    assert scheduler.reconcile_orphans(time.time()) == 0
    assert not scheduler.auto_approve(due, stale_settings, time.time())
    assert db.select("scheduled_publications") == before
    assert queue.jobs(worker="publisher") == []


def test_local_test_projects_never_enter_automatic_schedule_after_mode_is_off(env):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    _, _, tmp = env
    clip = make_clip(tmp, "A good local test clip", 90)
    db.update_project(clip["project_id"], options={"local_test_mode": True})
    db.save_settings({"autopilot_local_test_mode": False})
    assert scheduler.candidates(db.get_settings(), time.time()) == []
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 0

    normal = make_clip(tmp, "The next regular video has a different moment", 80)
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] >= 1
    assert all(p["clip_id"] == normal["id"] for p in db.select("scheduled_publications"))


@pytest.mark.parametrize("platform,mode", [("youtube", "direct"), ("tiktok", "direct"), ("tiktok", "inbox")])
def test_manual_upload_endpoint_refuses_even_private_uploads_and_inbox_drafts(env, platform, mode):
    from clipfoundry import db
    from clipfoundry.api import app

    g, t, tmp = env
    item = make_item(tmp)
    db.save_settings({"autopilot_local_test_mode": True})
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        r = client.post(f"/api/clips/{item['clip_id']}/publish/{platform}", headers=H,
                        json={"confirm": True, "privacy": "private", "made_for_kids": False, "mode": mode})
    assert r.status_code == 409 and "Local test mode" in r.json()["detail"]
    assert db.list_publications() == [] and not g.sessions and not t.uploads


@pytest.mark.parametrize("platform", ["youtube", "tiktok"])
def test_shared_runners_refuse_before_creating_a_platform_session(env, platform):
    from clipfoundry import db
    from clipfoundry.publish import jobs
    from clipfoundry.publish.common import PublishError

    g, t, tmp = env
    item = make_item(tmp, platform)
    pub = publication(item)
    db.save_settings({"autopilot_local_test_mode": True})
    with pytest.raises(PublishError) as blocked:
        jobs.RUNNERS[platform](pub, lambda: False)
    assert blocked.value.code == "local_test_mode"
    assert not g.sessions and not t.uploads


def test_scheduled_publisher_holds_existing_approval_without_touching_history(env):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    g, t, tmp = env
    item = make_item(tmp, approve={"options": {"made_for_kids": False}})
    db.save_settings({"autopilot_local_test_mode": True})
    with pytest.raises(queue.Wait) as held:
        run_publish(item["id"])
    assert held.value.reason == "local_test_mode"
    assert db.fetch("scheduled_publications", item["id"]) == item
    assert db.list_publications() == [] and not g.sessions and not t.uploads


@pytest.mark.parametrize("platform", ["youtube", "tiktok"])
def test_mode_enabled_between_chunks_holds_manual_upload_and_resumes_same_id(env, monkeypatch, platform):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp, platform, size=22_000_000 if platform == "tiktok" else 700_000)
    pub = publication(item)
    worker = jobs.PublishWorker()
    held_times = []
    monkeypatch.setattr(worker, "later", lambda pub_id, at: held_times.append((pub_id, at)))
    original_writer = jobs._progress_writer

    def pause_after_first_chunk(pub_id):
        write = original_writer(pub_id)

        def progress(frac):
            write(frac)
            if 0 < frac < 1:
                db.save_settings({"autopilot_local_test_mode": True})

        return progress

    monkeypatch.setattr(jobs, "_progress_writer", pause_after_first_chunk)
    worker._run(pub["id"])
    held = db.get_publication(pub["id"])
    assert held["status"] == "uploading" and held["info"]["local_test_hold"]
    assert "Nothing was published" not in held["message"]
    assert held_times and held_times[0][0] == pub["id"]
    upload_id = held["info"].get("upload_session") if platform == "youtube" else held["remote_id"]
    assert upload_id
    assert len(g.sessions if platform == "youtube" else t.uploads) == 1

    db.save_settings({"autopilot_local_test_mode": False})
    monkeypatch.setattr(jobs, "_progress_writer", original_writer)
    worker._run(pub["id"])
    finished = db.get_publication(pub["id"])
    assert finished["status"] == "done", finished
    assert len(g.sessions if platform == "youtube" else t.uploads) == 1
    assert len(g.videos if platform == "youtube" else t.uploads) == 1
    resumed_id = finished["info"].get("upload_session") if platform == "youtube" else finished["remote_id"]
    assert resumed_id == upload_id


def test_manual_hold_preserves_final_byte_uncertainty_and_recovers_after_restart(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    _, _, tmp = env
    pub = publication(make_item(tmp))
    saved = {"upload_session": "saved-session", "final_chunk_at": time.time(), "retry_at": time.time() + 120}
    db.update_publication(pub["id"], status="uploading", info=saved)
    db.save_settings({"autopilot_local_test_mode": True})
    worker = jobs.PublishWorker()
    held_times = []
    monkeypatch.setattr(worker, "later", lambda pub_id, at: held_times.append((pub_id, at)))
    worker._run(pub["id"])
    held = db.get_publication(pub["id"])
    assert held["status"] == "uploading"
    assert all(held["info"][key] == value for key, value in saved.items())
    assert worker.resume_waiting() == 1
    assert all(at >= saved["retry_at"] for _, at in held_times)


def test_scheduled_upload_pauses_between_chunks_without_losing_session_or_approval(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import queue
    from clipfoundry.publish import jobs

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp, size=700_000, approve={"options": {"made_for_kids": False}})
    original_writer = jobs._progress_writer

    def pause_after_first_chunk(pub_id):
        def progress(frac):
            original_writer(pub_id)(frac)
            if 0 < frac < 1:
                db.save_settings({"autopilot_local_test_mode": True})

        return progress

    monkeypatch.setattr(jobs, "_progress_writer", pause_after_first_chunk)
    with pytest.raises(queue.Wait) as held:
        run_publish(item["id"])
    assert held.value.reason == "local_test_mode"
    after = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(after["publication_id"])
    session = pub["info"]["upload_session"]
    assert after["approval"] == item["approval"] and after["status"] == "publishing"
    assert pub["status"] == "uploading" and not g.videos
    db.save_settings({"autopilot_local_test_mode": False})
    monkeypatch.setattr(jobs, "_progress_writer", original_writer)
    run_publish(item["id"])
    finished = db.fetch("scheduled_publications", item["id"])
    assert finished["status"] == "published"
    assert db.get_publication(finished["publication_id"])["info"]["upload_session"] == session
    assert len(g.sessions) == 1 and len(g.videos) == 1


def test_fresh_project_marker_rejects_a_previously_selected_schedule_candidate(env):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler

    _, _, tmp = env
    clip = make_clip(tmp, "The source was selected before test mode", 80)
    settings = db.get_settings()
    candidate = scheduler.candidates(settings, time.time())[0]
    db.update_project(clip["project_id"], options={"local_test_mode": True})
    with pytest.raises(queue.Fail, match="stay local"):
        scheduler.create_item(candidate, time.time() + 3600, {}, settings, time.time())
    assert db.select("scheduled_publications") == []


def test_tiktok_mode_enabled_after_final_marker_sends_no_video_bytes(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    g, t, tmp = env
    connect(g, t)
    pub = publication(make_item(tmp, "tiktok", size=300_000))
    original_update = db.update_publication

    def enable_mode_at_final_marker(pub_id, **fields):
        original_update(pub_id, **fields)
        if (fields.get("info") or {}).get("final_chunk_at"):
            db.save_settings({"autopilot_local_test_mode": True})

    worker = jobs.PublishWorker()
    monkeypatch.setattr(worker, "later", lambda *args: None)
    monkeypatch.setattr(db, "update_publication", enable_mode_at_final_marker)
    worker._run(pub["id"])
    held = db.get_publication(pub["id"])
    assert held["status"] == "uploading" and held["info"]["final_chunk_at"]
    assert held["info"]["local_test_hold"]
    assert held["remote_id"] and len(t.uploads) == 1
    assert t.uploads[held["remote_id"]]["data"] == b""
    assert not any(method == "PUT" for method, _ in t.log)


@pytest.mark.parametrize("platform", ["youtube", "tiktok"])
def test_mode_enabled_while_getting_token_prevents_upload_initialization(env, monkeypatch, platform):
    from clipfoundry import db
    from clipfoundry.publish import jobs, tiktok, youtube

    g, t, tmp = env
    connect(g, t)
    pub = publication(make_item(tmp, platform))
    if platform == "tiktok":
        db.update_publication(pub["id"], mode="inbox")
    token_type = youtube.Token if platform == "youtube" else tiktok.Token
    original_get = token_type.get

    def enable_mode_before_returning_token(token, *args, **kwargs):
        result = original_get(token, *args, **kwargs)
        db.save_settings({"autopilot_local_test_mode": True})
        return result

    worker = jobs.PublishWorker()
    monkeypatch.setattr(worker, "later", lambda *args: None)
    monkeypatch.setattr(token_type, "get", enable_mode_before_returning_token)
    worker._run(pub["id"])
    held = db.get_publication(pub["id"])
    assert held["status"] == "uploading" and held["info"]["local_test_hold"]
    assert not g.sessions and not t.uploads


def test_marked_project_holds_old_schedule_and_queued_upload_until_explicit_publish_now(env):
    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.autopilot import queue, scheduler

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp, planned_in=60, approve={"options": {"made_for_kids": False}})
    clip = db.get_clip(item["clip_id"])
    db.update_project(clip["project_id"], options={"local_test_mode": True})
    assert scheduler.process_due(db.get_settings(), time.time())["publishing"] == 0
    assert db.fetch("scheduled_publications", item["id"]) == item
    with pytest.raises(queue.Wait) as held:
        run_publish(item["id"])
    assert held.value.reason == "local_test_clip" and not g.sessions

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.post(f"/api/autopilot/scheduled/{item['id']}/publish-now", headers=H)
    assert response.status_code == 200, response.text
    run_publish(item["id"])
    assert db.fetch("scheduled_publications", item["id"])["status"] == "published"
    assert len(g.sessions) == 1 and len(g.videos) == 1


def mark_test_source(item: dict, covered: bool = False) -> dict:
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    source = db.insert("sources", {"platform": "url", "external_id": f"test-{item['id']}",
                                   "url": "https://example.com/video.mp4", "title": "A recorded test video",
                                   "status": "analyzed"})
    if covered:
        rights.add_rule("source", source["id"], rights.OWNED, "My own original recording")
    clip = db.get_clip(item["clip_id"])
    db.update_project(clip["project_id"], source_id=source["id"], options={"local_test_mode": True})
    return source


@pytest.mark.parametrize("platform", ["youtube", "tiktok"])
def test_manual_endpoint_still_requires_reuse_permission_when_test_mode_is_off(env, platform):
    from clipfoundry import db
    from clipfoundry.api import app

    g, t, tmp = env
    item = make_item(tmp, platform)
    mark_test_source(item)
    db.save_settings({"autopilot_local_test_mode": False})
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.post(f"/api/clips/{item['clip_id']}/publish/{platform}", headers=H,
                               json={"confirm": True, "privacy": "private", "made_for_kids": False})
    assert response.status_code == 400 and response.json()["code"] == "rights_blocked", response.text
    assert db.list_publications() == [] and not g.sessions and not t.uploads


@pytest.mark.parametrize("platform", ["youtube", "tiktok"])
@pytest.mark.parametrize("resuming", [False, True])
def test_direct_runner_cannot_bypass_unknown_test_reuse_permission_after_mode_is_off(env, platform, resuming):
    from clipfoundry import db
    from clipfoundry.publish import jobs
    from clipfoundry.publish.common import PublishError

    g, t, tmp = env
    item = make_item(tmp, platform)
    mark_test_source(item)
    pub = publication(item)
    if resuming:
        db.update_publication(pub["id"], status="uploading", remote_id="existing-publish-id",
                              info={"upload_session": "existing-session", "final_chunk_at": time.time()})
        pub = db.get_publication(pub["id"])
    db.save_settings({"autopilot_local_test_mode": False})
    with pytest.raises(PublishError) as blocked:
        jobs.RUNNERS[platform](pub, lambda: False)
    assert blocked.value.code == "rights_blocked"
    assert db.get_publication(pub["id"]) == pub
    assert not g.sessions and not t.uploads
    if resuming:
        jobs.PublishWorker()._run(pub["id"])
        held = db.get_publication(pub["id"])
        assert held["status"] == "uploading" and held["info"] == pub["info"]
        assert held["remote_id"] == pub["remote_id"] and not g.sessions and not t.uploads


def test_covered_manual_test_upload_requires_the_current_file_to_pass_quality(env, monkeypatch):
    from pathlib import Path

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.publish import jobs
    from quality_stub import passed_report

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp)
    mark_test_source(item, covered=True)
    clip = db.get_clip(item["clip_id"])
    video = Path(clip["output_path"])
    video.write_bytes(b"changed exact rendered bytes")
    submitted = []
    monkeypatch.setattr(jobs.worker, "submit", submitted.append)
    body = {"confirm": True, "title": item["title"], "description": item["description"],
            "privacy": "private", "made_for_kids": False}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        url = f"/api/clips/{item['clip_id']}/publish/youtube"
        blocked = client.post(url, headers=H, json=body)
        assert blocked.status_code == 400 and blocked.json()["code"] == "quality_pending", blocked.text
        assert submitted == [] and db.list_publications() == [] and not g.sessions
        passed_report(clip)
        allowed = client.post(url, headers=H, json=body)
        assert allowed.status_code == 200, allowed.text
        pub = allowed.json()
    assert submitted == [pub["id"]]
    jobs.run_youtube(db.get_publication(pub["id"]), lambda: False)
    assert db.get_publication(pub["id"])["status"] == "done"
    assert len(g.sessions) == 1 and len(g.videos) == 1


@pytest.mark.parametrize("platform", ["youtube", "tiktok"])
def test_manual_worker_preserves_an_existing_upload_when_test_reuse_is_unknown(env, platform):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    g, t, tmp = env
    item = make_item(tmp, platform)
    mark_test_source(item)
    pub = publication(item)
    saved = {"upload_session": "saved-session", "final_chunk_at": time.time()}
    db.update_publication(pub["id"], status="uploading", remote_id="saved-remote-id", info=saved)
    jobs.PublishWorker()._run(pub["id"])
    held = db.get_publication(pub["id"])
    assert held["status"] == "uploading" and held["remote_id"] == "saved-remote-id"
    assert held["info"] == saved and "existing upload record is kept" in held["message"]
    assert not g.sessions and not t.uploads

"""Local test mode gives truthful discovery and local-output feedback without asking to upload."""
from __future__ import annotations

import time

import pytest

from clipfoundry import db
from clipfoundry.autopilot import home, queue, rights, state


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_local_test_mode": True,
                      "library_discovery": False})
    monkeypatch.setattr(home, "keep_awake", lambda settings: "off")
    return tmp_path


def discovered(status="needs_rights", **fields):
    signal = db.insert("trend_signals", {"provider": "youtube_search", "platform": "youtube",
                                         "external_id": db.new_id(), "title": "A trending interview",
                                         "status": "active", "score": 85, "first_seen": time.time(),
                                         "last_checked": time.time()})
    return db.insert("sources", {"platform": "youtube", "external_id": signal["external_id"],
                                 "title": signal["title"], "signal_id": signal["id"], "kind": "recorded",
                                 "url": "https://www.youtube.com/watch?v=video000001", "status": status,
                                 "rights_status": rights.MANUAL, "source_score": 85, **fields})


def rendered(data, source=None, **fields):
    project = db.create_project("Local test video", origin="autopilot", source_id=(source or {}).get("id", ""))
    path = data / f"{project['id']}.mp4"
    path.write_bytes(b"Finished local output; no media processing runs in these view tests")
    return db.create_clip(project["id"], start=0, end=30, title="A strong local clip", status="ready",
                          output_path=str(path), **fields)


def scheduled(status, **fields):
    return db.insert("scheduled_publications", {"clip_id": db.new_id(), "platform": "youtube", "status": status,
                                                "title": "An earlier post", "planned_at": time.time() + 3600,
                                                **fields})


def test_finished_clips_show_real_local_files_without_reuse_permission(data):
    src = discovered("analyzed", clips_selected=1)
    clip = rendered(data, src)
    missing = rendered(data)
    db.update("clips", missing["id"], output_path=str(data / "missing.mp4"))
    unfinished = rendered(data)
    db.update("clips", unfinished["id"], status="rendering")
    manual = rendered(data)
    db.update_project(manual["project_id"], origin="manual")

    view = home.view(db.get_settings(), {}, True)
    assert view["local_test_mode"] is True
    assert view["local_ready"] == [{"id": clip["id"], "title": clip["title"], "project_id": clip["project_id"]}]
    assert view["currently"] == "Local clips are ready on this PC"
    assert "uploads are off" in view["pc_note"].lower()
    assert "Posts go out between" not in view["pc_note"]
    assert rights.evaluate(src)["status"] == rights.MANUAL
    assert not rights.evaluate(src)["auto_allowed"]
    assert db.get_clip(clip["id"])["output_path"] == clip["output_path"]


def test_missing_original_does_not_hide_a_rendered_alternative(data):
    clip = rendered(data)
    alternative = data / "alternative.mp4"
    alternative.write_bytes(b"A finished alternative")
    version = db.insert("clip_versions", {"clip_id": clip["id"], "kind": "alternative", "status": "ready",
                                         "output_path": str(alternative)})
    db.update("clips", clip["id"], output_path=str(data / "missing.mp4"), active_version=version["id"])
    assert home.local_ready() == [{"id": clip["id"], "title": clip["title"], "project_id": clip["project_id"]}]


def test_unknown_recordings_are_waiting_for_local_clipping_but_blocks_stay_hidden(data):
    src = discovered()
    blocked = discovered()
    rights.add_rule("source", blocked["id"], rights.BLOCKED, "Do not clip this video")
    state.put("trend:last_scan", {"at": time.time(), "signals": 2})

    view = home.view(db.get_settings(), {}, True)
    assert [(item["source_id"], item["stage"]) for item in view["opportunities"]] == [
        (src["id"], "Waiting for local clipping")]
    assert "covered" not in view["currently"].lower()
    activity = {item["id"]: item for item in home.activity()}
    assert activity[src["id"]]["stage"] == "Waiting for local clipping"
    assert "uploads are off" in activity[src["id"]]["why"].lower()
    assert activity[src["id"]]["rights"] == "Not covered"
    assert db.fetch("sources", src["id"])["rights_status"] == rights.MANUAL
    assert home.needs_videos(db.get_settings()) is None


def test_empty_search_keeps_youtube_connection_or_search_key_requirement_truthful(data):
    settings = db.get_settings()
    view = home.view(settings, {}, True)
    assert not view["setup"]["can_discover"]
    assert "Connect YouTube" in view["empty"] and "YouTube search key" in view["empty"]
    assert "Uploads stay off" in view["empty"]

    with_key = {**settings, "youtube_api_key": "test-search-key"}
    assert home.can_discover(with_key, {})
    assert "looking for public videos" in home.view(with_key, {}, True)["empty"]
    assert home.can_discover(settings, {"youtube": {"connected": True, "needs_reconnect": False}})
    assert not home.can_discover(settings, {"youtube": {"connected": True, "needs_reconnect": True}})

    state.put("trend:last_scan", {"at": time.time(), "signals": 1})
    discovered("needs_file")
    empty = home.view(with_key, {}, True)["empty"]
    assert "keeps looking" in empty
    assert "belong to other people" not in empty and "your own videos" not in empty


def test_post_requests_hide_while_uncertain_upload_reviews_remain(data):
    src = discovered()
    pending = scheduled("awaiting_approval")
    uncertain = scheduled("reconciling")
    state.action(f"approve:{pending['id']}", "approve", "Approve the post", ref_type="scheduled",
                 ref_id=pending["id"])
    state.action(f"rights:{src['id']}", "rights", "Can you use this video?", ref_type="source", ref_id=src["id"])
    state.action("connect:youtube", "publish", "Reconnect YouTube")
    state.action(f"publish:{pending['id']}", "publish", "Publish now", ref_type="scheduled", ref_id=pending["id"])
    state.action(f"review:{uncertain['id']}", "publish", "Check YouTube for this earlier upload",
                 "The platform may already have the video.", ref_type="scheduled", ref_id=uncertain["id"])
    db.save_settings({"rights_ask_per_video": True})
    accounts = {"youtube": {"connected": True, "needs_reconnect": True}}

    items = home.needs_you(db.get_settings(), accounts)
    assert [item["key"] for item in items] == [f"review:{uncertain['id']}"]
    assert db.fetch("scheduled_publications", pending["id"])["status"] == "awaiting_approval"
    assert len(state.open_actions()) == 5  # Viewing a local-only page never deletes earlier requests or history.


def test_local_view_keeps_already_uploaded_and_uncertain_posts_without_promising_new_posts(data):
    pending = scheduled("approved")
    reconciling = scheduled("reconciling")
    uploaded = scheduled("published")
    items = home.upcoming(settings=db.get_settings())
    assert {item["id"] for item in items} == {reconciling["id"], uploaded["id"]}
    assert next(item for item in items if item["id"] == uploaded["id"])["on_platform"]
    assert db.fetch("scheduled_publications", pending["id"])["status"] == "approved"


def test_local_mode_masks_effective_publishing_but_keeps_saved_permission(data):
    db.insert("publish_consents", {"platform": "youtube", "settings": {"visibility": "private"},
                                   "text": "An earlier publishing permission"})
    view = home.view(db.get_settings(), {}, True)
    assert all(not item["enabled"] for item in view["auto_publish"].values())
    assert all("All uploads are off" in item["note"] for item in view["auto_publish"].values())
    normal = {**db.get_settings(), "autopilot_local_test_mode": False}
    normal_view = home.view(normal, {}, True)
    assert normal_view["auto_publish"]["youtube"]["enabled"]
    assert "local_test_mode" not in normal_view and "local_ready" not in normal_view
    assert "Posts go out between" in normal_view["pc_note"]
    assert db.select("publish_consents")[0]["revoked_at"] is None


def test_pending_uploads_are_not_the_next_local_step_and_pause_is_respected(data):
    queue.enqueue("publish", priority=100)
    queue.enqueue("schedule_tick", priority=100)
    queue.enqueue("hunt_source", priority=0)
    settings = db.get_settings()
    assert home.next_step(settings) == "Getting a video ready"
    state.put("emergency_stop", True)
    assert home.currently(settings, True) == "Stopped: all jobs are on hold"
    assert home.working(settings) is None
    assert home.next_step(settings) == "Continue when you start Autopilot again"

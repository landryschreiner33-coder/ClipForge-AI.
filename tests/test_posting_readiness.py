"""Why finished clips have not posted: disposable data, exact-file report stand-ins, and no platform calls."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from quality_stub import passed_report


@pytest.fixture()
def data(monkeypatch, tmp_path):
    from clipfoundry import db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_tiktok": False,
                      "audience_youtube": "public", "audience_youtube_confirmed_at": 1.0,
                      "audience_youtube_group_version": 1, "autopilot_auto_schedule": True,
                      "autopilot_auto_publish": True, "autopilot_active_start": 0, "autopilot_active_end": 24})
    # A local synthetic saved account is enough; reading posting readiness must not refresh its token.
    db.save_account("youtube", tokens={"access_token": "synthetic-offline"}, account_id="synthetic-channel")
    return tmp_path


def platforms() -> dict:
    return {"youtube": {"connected": True, "needs_reconnect": False}, "tiktok": {"connected": False}}


def permission() -> dict:
    from clipfoundry.autopilot import autopublish

    return autopublish.enable("youtube", "public", False, 3, 0, 24, True)


def finished(tmp: Path, *, source_id: str = "", origin: str = "autopilot") -> dict:
    from clipfoundry import db

    project = db.create_project("Synthetic original", origin=origin, source_id=source_id, status="ready")
    video = tmp / f"finished-{project['id']}.mp4"
    video.write_bytes(b"synthetic rendered bytes; media validity is covered by the real-file gate tests")
    return db.create_clip(project["id"], start=0, end=20, duration=20, title="Complete useful answer",
                          status="ready", output_path=str(video))


def metadata(clip: dict, *, selected: bool = True) -> dict:
    from clipfoundry import db

    return db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": "youtube", "selected": selected,
                                             "title": "Complete useful answer", "description": "Useful answer"})


def post(clip: dict, status: str) -> dict:
    from clipfoundry import db

    return db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "youtube", "status": status,
                                                "planned_at": time.time() + 3600, "privacy": "public"})


def shown() -> tuple[dict, dict]:
    from clipfoundry import db
    from clipfoundry.autopilot import readiness

    value = readiness.view(db.get_settings(), platforms(), True)
    assert [p["platform"] for p in value["platforms"]] == ["youtube"]
    return value, value["platforms"][0]


def test_approved_post_without_a_time_is_a_wait_not_a_confirmed_schedule(data):
    from clipfoundry import db

    permission()
    clip = finished(data)
    item = post(clip, "approved")
    db.update("scheduled_publications", item["id"], planned_at=None)
    _, youtube = shown()
    assert youtube["code"] == "waiting_time"
    assert youtube["counts"]["waiting_time"] == 1
    assert youtube["counts"]["scheduled"] == 0


def snapshot() -> str:
    from clipfoundry import db

    with db.connect() as conn:
        return "\n".join(conn.iterdump())


def test_finished_clips_require_separate_permission_despite_connected_youtube(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home

    finished(data)
    before = snapshot()
    value, youtube = shown()
    assert value["finished"] == 1 and youtube["counts"]["preparing"] == 1
    assert youtube["code"] == "permission" and not youtube["automatic"]
    needs = home.needs_you(db.get_settings(), platforms())
    assert [n["key"] for n in needs] == ["auto_publish_setup:youtube"]
    assert "Connecting YouTube" in needs[0]["detail"] and needs[0]["link"] == "#/missions"
    assert snapshot() == before


def test_fresh_unconfirmed_audience_is_visible_without_scheduler_reminder(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home, readiness

    finished(data)
    db.save_settings({"audience_youtube_confirmed_at": 0.0})
    before = snapshot()
    assert shown()[1]["code"] == "audience"
    assert [n["key"] for n in home.needs_you(db.get_settings(), platforms())] == ["audience_setup:youtube"]
    assert readiness.setup_needs(db.get_settings(), platforms())[0]["link"] == "#/settings/integrations"
    assert snapshot() == before  # The warning is derived even if workers never wrote an action item.


def test_derived_audience_hold_does_not_duplicate_existing_action(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    db.save_settings({"audience_youtube_confirmed_at": 0.0})
    state.action("audience_setup:youtube", "audience", "Older persisted audience warning")
    before = snapshot()
    needs = home.needs_you(db.get_settings(), platforms())
    assert [n["key"] for n in needs].count("audience_setup:youtube") == 1
    assert snapshot() == before


@pytest.mark.parametrize("change", ["revoked", "different_channel", "different_audience"])
def test_permission_bound_to_current_channel_and_audience_is_needed(data, change):
    from clipfoundry import db
    from clipfoundry.autopilot import home

    consent = permission()
    finished(data)
    if change == "revoked":
        db.update("publish_consents", consent["id"], revoked_at=time.time())
    elif change == "different_channel":
        db.save_account("youtube", account_id="another-synthetic-channel")
    else:
        db.save_settings({"audience_youtube_group_version": 2})
    assert shown()[1]["code"] == "permission" and not shown()[1]["automatic"]
    assert any(n["key"] == "auto_publish_setup:youtube" for n in home.needs_you(db.get_settings(), platforms()))


def test_valid_permission_removes_setup_hold_and_keeps_preparation_truthful(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home

    permission()
    finished(data)
    _, youtube = shown()
    assert youtube["automatic"] and youtube["code"] == "preparing"
    assert not home.needs_you(db.get_settings(), platforms())


@pytest.mark.parametrize("status", ["failed", "canceled"])
def test_stopped_post_preparation_is_explained_without_restarting_it(data, status):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    permission()
    clip = finished(data)
    job = queue.enqueue("package_clip", {"clip_id": clip["id"]}, ref=("clip", clip["id"]))
    db.update("worker_jobs", job["id"], status=status)
    before = snapshot()
    _, youtube = shown()
    assert youtube["code"] == "preparation_stopped" and youtube["counts"]["preparation_stopped"] == 1
    assert db.fetch("worker_jobs", job["id"])["status"] == status
    assert snapshot() == before


def test_running_new_preparation_takes_precedence_over_older_failed_attempt(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    permission()
    clip = finished(data)
    old = queue.enqueue("package_clip", {"clip_id": clip["id"]}, ref=("clip", clip["id"]))
    db.update("worker_jobs", old["id"], status="failed")
    current = queue.enqueue("package_clip", {"clip_id": clip["id"]}, ref=("clip", clip["id"]))
    db.update("worker_jobs", current["id"], status="running")
    _, youtube = shown()
    assert youtube["code"] == "preparing" and youtube["counts"]["preparation_stopped"] == 0
    assert youtube["counts"]["preparing"] == 1


@pytest.mark.parametrize("patch, expected", [
    ({"autopilot_auto_schedule": False}, "schedule_off"),
    ({"audience_youtube": "local_only"}, "local_only"),
    ({"autopilot_youtube": False}, "platform_off"),
    ({"autopilot_enabled": False}, "paused"),
    ({"autopilot_publishing_paused": True}, "publishing_paused"),
    ({"autopilot_auto_publish": False}, "publish_off"),
    ({"autopilot_youtube_daily_limit": 0}, "limit"),
    ({"autopilot_active_start": 9, "autopilot_active_end": 9}, "window"),
])
def test_explicit_owner_controls_are_explained_without_changing_them(data, patch, expected):
    from clipfoundry import db

    permission()
    finished(data)
    db.save_settings(patch)
    before = snapshot()
    assert shown()[1]["code"] == expected
    assert snapshot() == before


def test_finished_public_discovery_video_is_not_misrepresented_as_upload_ready(data):
    from clipfoundry import db

    permission()
    source = db.insert("sources", {"platform": "youtube", "external_id": "synthetic-public-video",
                                    "status": "analyzed", "title": "A public video without reuse coverage"})
    finished(data, source_id=source["id"])
    _, youtube = shown()
    assert youtube["code"] == "rights"
    assert youtube["counts"]["local_only"] == 1 and youtube["counts"]["ready"] == 0
    assert "being public does not grant permission" in youtube["detail"]


@pytest.mark.parametrize("stage", ["not_selected", "missing_report", "different_metadata", "failed_file",
                                   "failed_text", "changed_file", "passed"])
def test_selected_post_text_and_current_exact_file_report_determine_pipeline_stage(data, stage):
    from clipfoundry import db

    permission()
    clip = finished(data)
    meta = metadata(clip, selected=stage != "not_selected")
    if stage not in ("not_selected", "missing_report"):
        report = passed_report(clip, ("youtube",))
        if stage == "different_metadata":
            db.update("metadata_candidates", meta["id"], selected=False)
            metadata(clip)
        elif stage == "failed_file":
            db.update("quality_reports", report["id"], status="failed")
        elif stage == "failed_text":
            db.update("quality_reports", report["id"], metadata={"youtube": {
                "status": "failed", "metadata_id": meta["id"], "problems": ["ungrounded claim"]}})
        elif stage == "changed_file":
            Path(clip["output_path"]).write_bytes(b"different rendered file, invalidating its saved report")
    expected = {"not_selected": ("preparing", "preparing"), "missing_report": ("checking", "checking"),
                "different_metadata": ("checking", "checking"), "failed_file": ("quality", "failed_check"),
                "failed_text": ("quality", "failed_check"), "changed_file": ("checking", "checking"),
                "passed": ("planning", "ready")}[stage]
    before = snapshot()
    _, youtube = shown()
    assert youtube["code"] == expected[0] and youtube["counts"][expected[1]] == 1
    assert snapshot() == before


@pytest.mark.parametrize("status, expected_code, count", [
    ("approved", "scheduled", "scheduled"), ("publishing", "scheduled", "scheduled"),
    ("awaiting_approval", "review", "review"), ("reconciling", "problems", "problems"),
    ("action_needed", "problems", "problems"), ("published", "waiting", None),
])
def test_planned_published_and_unknown_outcome_posts_are_not_new_ready_clips(data, status, expected_code, count):
    permission()
    clip = finished(data)
    metadata(clip)
    passed_report(clip, ("youtube",))
    post(clip, status)
    _, youtube = shown()
    assert youtube["code"] == expected_code and youtube["counts"]["ready"] == 0
    if count:
        assert youtube["counts"][count] == 1


def test_readiness_poll_does_not_call_platforms_walk_folders_hash_or_queue_work(data, monkeypatch):
    import httpx

    from clipfoundry import db
    from clipfoundry.autopilot import gate, home, myvideos, queue, readiness
    from clipfoundry.pipeline import artifact

    permission()
    clip = finished(data)
    metadata(clip)
    passed_report(clip, ("youtube",))
    finished(data)  # An unfinished package must also remain merely an explanation during polling.

    def forbidden(*args, **kwargs):
        raise AssertionError("A read-only posting poll tried to perform work")

    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
    monkeypatch.setattr(queue, "enqueue", forbidden)
    monkeypatch.setattr(gate, "request", forbidden)
    monkeypatch.setattr(myvideos, "view", forbidden)
    monkeypatch.setattr(Path, "rglob", forbidden)
    monkeypatch.setattr(artifact, "sha256_file", forbidden)
    before = snapshot()
    for _ in range(2):
        value, youtube = shown()
        assert value["finished"] == 2 and youtube["counts"]["ready"] == 1
        assert youtube["counts"]["preparing"] == 1
        assert not readiness.setup_needs(db.get_settings(), platforms())
        assert not home.needs_you(db.get_settings(), platforms())
    assert snapshot() == before


def test_manual_clips_are_not_counted_and_limited_scan_is_explicit(data, monkeypatch):
    from clipfoundry.autopilot import readiness

    permission()
    finished(data, origin="manual")
    for _ in range(3):
        finished(data)
    monkeypatch.setattr(readiness, "LIMIT", 2)
    value, youtube = shown()
    assert value["finished"] == 3 and value["checked"] == 2 and value["sampled"]
    assert youtube["counts"]["preparing"] == 2


def test_account_failure_and_absent_workers_are_visible_before_pipeline_waits(data):
    from clipfoundry import db
    from clipfoundry.autopilot import readiness

    permission()
    finished(data)
    accounts = platforms()
    accounts["youtube"]["needs_reconnect"] = True
    assert readiness.view(db.get_settings(), accounts, True)["platforms"][0]["code"] == "account"
    assert readiness.view(db.get_settings(), platforms(), False)["platforms"][0]["code"] == "workers"


def test_setup_warnings_respect_local_only_disabled_and_paused_modes(data):
    from clipfoundry import db
    from clipfoundry.autopilot import readiness, state

    finished(data)
    for patch in ({"audience_youtube": "local_only"}, {"audience_youtube": "public", "autopilot_youtube": False},
                  {"autopilot_youtube": True, "autopilot_enabled": False}):
        db.save_settings(patch)
        assert not readiness.setup_needs(db.get_settings(), platforms())
    db.save_settings({"autopilot_enabled": True})
    state.put("emergency_stop", True)
    assert not readiness.setup_needs(db.get_settings(), platforms())

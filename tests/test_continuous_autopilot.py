"""Uncapped local scheduling keeps permissions, platform holds and a bounded production queue."""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

import pytest

from test_autopilot_auto import _clip, _consent, client, env  # noqa: F401


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    return tmp_path


def test_uncapped_defaults_and_zero_validation(data):
    from clipfoundry import config, db

    settings = db.get_settings()
    for key in ("autopilot_daily_target", "autopilot_sources_per_day", "autopilot_youtube_daily_limit",
                "autopilot_tiktok_daily_limit", "autopilot_min_gap_minutes"):
        assert settings[key] == 0
        assert config.validate_settings({key: 0})[key] == 0
    assert (settings["autopilot_active_start"], settings["autopilot_active_end"]) == (0, 24)


def test_zero_is_uncapped_but_a_platform_reported_zero_still_stops_posting(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    settings = {**db.get_settings(), "autopilot_youtube_daily_limit": 0, "autopilot_daily_target": 0,
                "autopilot_min_gap_minutes": 0}
    assert scheduler.daily_limit(settings, "youtube") is None
    now = time.time()
    plan = scheduler.Plan(settings, now)
    plan.items = [{"id": str(i), "platform": "youtube", "clip_id": str(i), "planned_at": now,
                   "status": "published"} for i in range(40)]
    assert plan.free("youtube", now, "new")
    db.insert("platform_limits", {"platform": "youtube", "key": "daily_posts", "value": 0}, key="platform")
    assert scheduler.daily_limit(settings, "youtube") == 0
    assert not plan.free("youtube", now, "new")


def test_continuous_slot_is_prompt_at_night_and_obeys_exact_platform_wait(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    settings = {**db.get_settings(), "autopilot_youtube_daily_limit": 0, "autopilot_daily_target": 0,
                "autopilot_min_gap_minutes": 0, "autopilot_active_start": 0, "autopilot_active_end": 24}
    now = dt.datetime(2026, 10, 14, 23, 43, tzinfo=ZoneInfo("America/Chicago")).timestamp()
    plan = scheduler.Plan(settings, now)
    slot = plan.best_slot("youtube", "new", 0.0, scheduler.Timing("youtube", settings))
    assert slot and now <= slot[0] <= now + 60
    until = now + 73 * 60
    scheduler.block_platform("youtube", until, "Retry after 73 minutes")
    slot = scheduler.Plan(settings, now).best_slot("youtube", "new", 0.0, scheduler.Timing("youtube", settings))
    assert slot and until <= slot[0] <= until + 60


def test_unlimited_grant_approves_more_than_fifteen_qualified_clips(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    response = _consent(client, daily_limit=0, start_hour=0, end_hour=24)
    assert response.status_code == 200, response.text
    consent = response.json()["youtube"]["consent"]
    assert "without an app daily cap" in consent["text"]
    db.save_settings({"autopilot_tiktok": False})
    for index in range(18):
        _clip(env, f"Distinct qualified clip {index}")
    now = time.time()
    result = scheduler.plan_new(db.get_settings(), now)
    assert result["created"] == 18
    items = db.select("scheduled_publications")
    assert all(item["status"] == "approved" for item in items)
    assert all(now <= item["planned_at"] <= now + 60 for item in items)
    assert scheduler.plan_new(db.get_settings(), now)["created"] == 0


def test_unlimited_sources_refill_after_done_but_active_queue_stays_bounded(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scout

    settings = {**db.get_settings(), "autopilot_sources_per_day": 0, "autopilot_daily_target": 0,
                "discovery_queue_limit": 6}
    yesterday = scout.local_day(settings, time.time() - 86400)
    for index in range(9):
        db.insert("sources", {"platform": "local", "external_id": str(index), "status": "analyzed",
                              "selected_day": scout.local_day(settings), "clips_selected": 5})
    assert scout.still_needed(settings) == 6
    assert scout.discovery_attempts_remaining(settings) is None
    rows = [db.insert("sources", {"platform": "local", "external_id": f"busy{index}", "status": "queued",
                                  "selected_day": yesterday}) for index in range(6)]
    assert scout.still_needed(settings) == 0
    db.update("sources", rows[0]["id"], status="analyzed")
    assert scout.still_needed(settings) == 1


def test_legacy_volume_migrates_once_without_changing_posts_audiences_or_other_budgets(data):
    from clipfoundry import config, db

    db.save_settings({"autopilot_youtube_daily_limit": 15, "autopilot_tiktok_daily_limit": 15,
                      "autopilot_daily_target": 15, "autopilot_sources_per_day": 3,
                      "autopilot_active_start": 9, "autopilot_active_end": 21, "autopilot_min_gap_minutes": 45,
                      "autopilot_enabled": False, "audience_youtube": "public", "youtube_quota_uploads": 7,
                      "discovery_monthly_budget_usd": 0, "nvidia_daily_requests": 20})
    consent = db.insert("publish_consents", {
        "platform": "youtube", "text": "Original permission for this channel and Public audience.",
        "settings": {"visibility": "public", "account_id": "UCfake", "audience_intent": "PUBLIC",
                     "group_version": 2, "text_version": 3, "made_for_kids": False, "daily_limit": 3,
                     "start_hour": 9, "end_hour": 21}})
    post = db.insert("scheduled_publications", {"clip_id": "original-private-clip", "platform": "youtube",
                                               "privacy": "private", "status": "approved", "planned_at": 1234,
                                               "audience": {"intent": "SELECTED_AUDIENCE"},
                                               "approval": {"by": "automatic", "consent_id": consent["id"]}})
    db.insert("platform_limits", {"platform": "youtube", "key": "daily_posts", "value": 4}, key="platform")
    with db.connect() as conn:
        conn.execute("DELETE FROM autopilot_state WHERE key = ?", (db.CONTINUOUS_VOLUME_MIGRATION,))
        conn.execute("UPDATE settings SET value = 'bad-json' WHERE key = 'autopilot_tiktok_daily_limit'")
    db._ready.discard(str(config.db_path()))
    db.init()
    settings = db.get_settings()
    assert settings["autopilot_sources_per_day"] == settings["autopilot_daily_target"] == 0
    assert settings["autopilot_youtube_daily_limit"] == settings["autopilot_tiktok_daily_limit"] == 0
    assert (settings["autopilot_active_start"], settings["autopilot_active_end"]) == (0, 24)
    assert settings["autopilot_min_gap_minutes"] == 0
    assert not settings["autopilot_enabled"]
    assert settings["audience_youtube"] == "public" and settings["youtube_quota_uploads"] == 7
    assert settings["nvidia_daily_requests"] == 20 and settings["discovery_monthly_budget_usd"] == 0
    amended = db.fetch("publish_consents", consent["id"])
    assert amended["settings"]["daily_limit"] == 0
    assert amended["settings"]["volume_amendment"]["previous"]["daily_limit"] == 3
    for key in ("visibility", "account_id", "audience_intent", "group_version", "text_version", "made_for_kids"):
        assert amended["settings"][key] == consent["settings"][key]
    assert amended["text"].startswith(consent["text"]) and "Volume update:" in amended["text"]
    assert db.fetch("scheduled_publications", post["id"]) == post
    assert db.scalar("SELECT value FROM platform_limits WHERE platform = 'youtube'") == 4
    db.save_settings({"autopilot_sources_per_day": 2, "autopilot_youtube_daily_limit": 8,
                      "autopilot_active_start": 9})
    db._ready.discard(str(config.db_path()))
    db.init()
    assert db.get_settings()["autopilot_youtube_daily_limit"] == 8
    assert db.get_settings()["autopilot_sources_per_day"] == 2
    assert db.get_settings()["autopilot_active_start"] == 9
    assert db.fetch("publish_consents", consent["id"])["text"] == amended["text"]


def test_volume_migration_never_restores_a_revoked_permission(data):
    from clipfoundry import config, db
    from clipfoundry.autopilot import autopublish

    consent = db.insert("publish_consents", {"platform": "youtube", "settings": {"daily_limit": 3},
                                            "text": "Turned off", "revoked_at": time.time()})
    with db.connect() as conn:
        conn.execute("DELETE FROM autopilot_state WHERE key = ?", (db.CONTINUOUS_VOLUME_MIGRATION,))
    db._ready.discard(str(config.db_path()))
    db.init()
    assert db.fetch("publish_consents", consent["id"]) == consent
    assert autopublish.active("youtube") is None


def test_old_past_due_consent_hold_recovers_under_unlimited_permission(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler

    assert _consent(client, daily_limit=0, start_hour=0, end_hour=24).status_code == 200
    db.save_settings({"autopilot_tiktok": False})
    now = time.time()
    clip = _clip(env, "A finished clip from before the unlimited update")
    meta = db.select("metadata_candidates", "clip_id = ? AND platform = 'youtube'", (clip["id"],))[0]
    post = db.insert("scheduled_publications", {
        "clip_id": clip["id"], "metadata_id": meta["id"], "platform": "youtube", "title": clip["title"],
        "description": meta["description"], "tags": meta["tags"], "privacy": "private",
        "options": {"made_for_kids": False}, "planned_at": now - 3600, "status": "awaiting_approval",
        "status_note": "Held: old automatic daily limit was reached"})
    scheduler.process_due(db.get_settings(), now)
    recovered = db.fetch("scheduled_publications", post["id"])
    assert recovered["status"] == "approved"
    assert recovered["privacy"] == "private" and recovered["planned_at"] >= now
    scheduler.process_due(db.get_settings(), now + 1)
    assert db.fetch("scheduled_publications", post["id"])["status"] == "publishing"
    assert len(queue.jobs(worker="publisher")) == 1


def test_old_edited_post_still_needs_its_owners_review(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    assert _consent(client, daily_limit=0, start_hour=0, end_hour=24).status_code == 200
    clip = _clip(env, "A post changed by its owner")
    now = time.time()
    item = db.insert("scheduled_publications", {
        "clip_id": clip["id"], "platform": "youtube", "privacy": "private", "planned_at": now - 3600,
        "status": "awaiting_approval", "audit": [{"event": "edited"}]})
    scheduler.process_due(db.get_settings(), now)
    scheduler.process_due(db.get_settings(), now + 1)
    assert db.fetch("scheduled_publications", item["id"])["status"] == "awaiting_approval"


def test_reported_zero_holds_already_approved_post_then_recovers(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler

    assert _consent(client, daily_limit=0, start_hour=0, end_hour=24).status_code == 200
    db.save_settings({"autopilot_tiktok": False})
    _clip(env, "Eligible clip planned before a reported platform hold")
    now = time.time()
    assert scheduler.plan_new(db.get_settings(), now)["created"] == 1
    original = db.select("scheduled_publications")[0]
    db.insert("platform_limits", {"platform": "youtube", "key": "daily_posts", "value": 0}, key="platform")
    for when in (now + 1, now + 3600):
        assert scheduler.process_due(db.get_settings(), when)["publishing"] == 0
        held = db.fetch("scheduled_publications", original["id"])
        assert held["status"] == "approved" and "platform allowance" in held["status_note"]
        for field in ("planned_at", "privacy", "audience", "approval", "title", "description"):
            assert held[field] == original[field]
        assert not queue.jobs(worker="publisher")
    db.execute("UPDATE platform_limits SET value = 1 WHERE platform = 'youtube' AND key = 'daily_posts'")
    assert scheduler.process_due(db.get_settings(), now + 3601)["publishing"] == 0
    recovered = db.fetch("scheduled_publications", original["id"])
    assert recovered["planned_at"] >= now + 3601 and recovered["approval"] == original["approval"]
    assert scheduler.process_due(db.get_settings(), now + 3602)["publishing"] == 1
    assert db.fetch("scheduled_publications", original["id"])["status"] == "publishing"
    assert len(queue.jobs(worker="publisher")) == 1


@pytest.mark.parametrize("weak_status,weak_time", [("published", "past"), ("approved", None)])
def test_past_replacement_lost_slot_recovers_without_touching_its_original(env, client, weak_status, weak_time):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    assert _consent(client, daily_limit=0, start_hour=0, end_hour=24).status_code == 200
    db.save_settings({"autopilot_tiktok": False})
    now = time.time()
    weak = db.insert("scheduled_publications", {"clip_id": "already-posted", "platform": "youtube",
                                               "status": weak_status, "privacy": "private",
                                               "planned_at": now - 3600 if weak_time == "past" else None})
    clip = _clip(env, "Stronger replacement from before an interrupted approval")
    meta = db.select("metadata_candidates", "clip_id = ? AND platform = 'youtube'", (clip["id"],))[0]
    post = db.insert("scheduled_publications", {
        "clip_id": clip["id"], "metadata_id": meta["id"], "platform": "youtube", "title": clip["title"],
        "description": meta["description"], "tags": meta["tags"], "privacy": "private",
        "options": {"made_for_kids": False}, "planned_at": now - 30, "status": "awaiting_approval",
        "replaces": weak["id"]})
    scheduler.process_due(db.get_settings(), now)
    recovered = db.fetch("scheduled_publications", post["id"])
    assert recovered["status"] == "approved" and recovered["planned_at"] >= now and not recovered["replaces"]
    # A published original is immutable; an approved timeless original may itself be rescheduled normally.
    original = db.fetch("scheduled_publications", weak["id"])
    assert original["status"] == weak_status and not original["replaced_by"]
    if weak_status == "published":
        assert original == weak

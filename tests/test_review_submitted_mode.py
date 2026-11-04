"""Only explicit video submissions may admit new work in the owner's submitted-video mode."""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def data(tmp_path, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True})
    host.WorkerHost(periodic=False)
    return tmp_path


def test_production_default_and_periodic_jobs_do_not_search_or_watch_folders(data):
    from clipfoundry import config, db
    from clipfoundry.autopilot import host, state

    settings = db.get_settings()
    assert settings["autopilot_input_mode"] == "submitted"
    assert settings["autopilot_review_before_publish"] is True
    assert not config.discovery_enabled(settings)
    started = host.run_periodic(settings, time.time())
    assert "schedule_tick" in started and "maintenance" in started
    assert not set(started) & {"trend_scan", "feed_scan", "live_watch"}
    assert not any(state.get(f"next:{kind}") for kind in ("trend_scan", "feed_scan", "live_watch"))


@pytest.mark.parametrize("kind", ["trend_scan", "feed_scan", "source_scout", "live_watch"])
def test_already_queued_discovery_is_noop_without_network_or_new_sources(data, monkeypatch, kind):
    from clipfoundry import db
    from clipfoundry.autopilot import host, providers, queue, state

    def unexpected(*args, **kwargs):
        raise AssertionError("Submitted-video mode must not search or scan watched sources")

    db.save_settings({"youtube_api_key": "invalid-discovery-key", "tavily_api_key": "invalid-web-key"})
    db.insert("trend_signals", {"platform": "url", "provider": "old-feed", "external_id": "old-signal",
                                "url": "https://example.com/v.mp4", "title": "Old broad discovery", "status": "active",
                                "first_seen": time.time(), "last_checked": time.time()})
    source = db.insert("sources", {"platform": "url", "external_id": "old-source", "status": "eligible"})
    monkeypatch.setattr(providers, "client", unexpected)
    for name in list(providers.FEED_SCANNERS):
        monkeypatch.setitem(providers.FEED_SCANNERS, name, unexpected)
    original = db.fetch("sources", source["id"])
    row = queue.enqueue(kind, priority=100, ref=("source", source["id"]))
    claim = queue.claim(queue.KIND_WORKER[kind], "input-mode-test")
    result = host.HANDLERS[kind](host.Job(claim, "input-mode-test"))
    queue.complete(claim, "input-mode-test", result)
    assert db.scalar("SELECT COUNT(*) FROM sources") == 1
    assert db.fetch("sources", source["id"]) == original
    assert db.scalar("SELECT COUNT(*) FROM api_cache") == 0
    assert db.scalar("SELECT COUNT(*) FROM quota_usage") == 0
    assert not state.get("providers") and not state.get("trend:last_scan")
    assert db.fetch("worker_jobs", row["id"])["status"] == "completed"


def test_no_implicit_folder_or_discovery_refill_but_existing_files_stay(data):
    from clipfoundry import db
    from clipfoundry.autopilot import myvideos, scout, state

    assert myvideos.ensure() is None
    assert not myvideos.feed()
    assert not db.select("source_rights")
    assert scout.refill({"id": "old-failed-source"}) is None
    assert scout.select_for_today(db.get_settings()) == []
    assert not state.get("my_videos:feed")


def test_status_reads_explain_input_mode_without_old_api_errors_or_database_writes(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state
    from clipfoundry.office import health

    state.put("providers", {"youtube": {"status": "error", "detail": "old bad key"},
                            "web_search": {"status": "error", "detail": "old bad web key"}})
    state.action("youtube:discovery", "youtube", "Old search failed", "Old invalid key", "Replace the search key")
    with db.connect() as conn:
        before = list(conn.iterdump())
    settings = db.get_settings()
    reading = health.discovery(settings)
    assert reading["status"] == "healthy" and "Only videos you add" in reading["reason"]
    assert not home.can_discover(settings, {})
    assert home.next_look(settings) is None
    assert home.currently(settings, True) == "Ready for a video link or file"
    assert "video link or file" in home.empty_message(settings, False, [])
    assert "another video link or file" in home.next_step(settings)
    assert home.needs_videos(settings) is None
    assert home.discovery_status()["problems"] == []
    assert home.discovery_status()["next_scan"] is None
    assert not any(item["key"] == "youtube:discovery" for item in home.needs_you(settings, {}))
    with db.connect() as conn:
        assert list(conn.iterdump()) == before


def test_reapplying_source_terms_does_not_require_discovery_keys(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue, scout, verify

    def unexpected(*args, **kwargs):
        raise AssertionError("Reapplying local source terms must not call a discovery API")

    source = db.insert("sources", {"platform": "url", "external_id": "manual-input", "status": "discovered"})
    monkeypatch.setattr(verify, "ensure", unexpected)
    row = queue.enqueue("rights_check", priority=100)
    result = scout.rights_check(host.Job(row, "terms-test"))
    assert result["checked"] == 1
    assert db.fetch("sources", source["id"])


def test_upcoming_identifies_the_source_request_instead_of_claiming_manual_review(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home

    post = db.insert("scheduled_publications", {"clip_id": "submitted-clip", "platform": "youtube",
                                               "status": "approved", "approval": {"by": "submission"}})
    upcoming = next(item for item in home.upcoming() if item["id"] == post["id"])
    assert upcoming["approval_by"] == "submission"
    assert upcoming["auto"] is False


def test_one_time_profile_migration_keeps_brain_settings_approvals_and_later_mode_choice(data):
    from clipfoundry import db

    db.execute("DELETE FROM autopilot_state WHERE key = ?", (db.SUBMITTED_INPUT_MIGRATION,))
    db.execute("DELETE FROM settings WHERE key = 'autopilot_input_mode'")
    db.save_settings({"brain_paused": True, "caption_style": "minimal", "autopilot_publishing_paused": True})
    note = db.insert("brain_knowledge", {"kind": "reference", "title": "Keep my notes", "content": "My style"})
    post = db.insert("scheduled_publications", {"clip_id": "old-clip", "platform": "youtube",
                                               "status": "awaiting_approval", "approval": {},
                                               "reuse_confirmation": {"basis": "old exact-post record"}})
    old_note = db.fetch("brain_knowledge", note["id"])
    old_post = db.fetch("scheduled_publications", post["id"])
    db.init()
    settings = db.get_settings()
    assert settings["autopilot_input_mode"] == "submitted"
    assert settings["brain_paused"] is True and settings["autopilot_publishing_paused"] is True
    assert settings["caption_style"] == "minimal"
    assert db.fetch("brain_knowledge", note["id"]) == old_note
    assert db.fetch("scheduled_publications", post["id"]) == old_post
    assert not db.select("publish_consents")
    db.save_settings({"autopilot_input_mode": "discovery"})
    db.init()
    assert db.get_settings()["autopilot_input_mode"] == "discovery"


def test_optional_discovery_mode_can_still_be_selected_and_invalid_mode_is_ignored(data):
    from clipfoundry import config, db

    db.save_settings({"autopilot_input_mode": "discovery"})
    assert config.discovery_enabled(db.get_settings())
    db.save_settings({"autopilot_input_mode": "invented"})
    assert db.get_settings()["autopilot_input_mode"] == "discovery"


@pytest.mark.parametrize("publishing_paused", [False, True])
def test_readiness_and_activity_explain_source_request_without_enabling_broad_uploads(data, publishing_paused):
    import io

    from clipfoundry import db
    from clipfoundry.autopilot import home, readiness, rights, submissions

    db.save_settings({"autopilot_youtube": False, "autopilot_auto_schedule": False,
                      "autopilot_auto_publish": False, "autopilot_publishing_paused": publishing_paused})
    db.save_account("youtube", tokens={"access_token": "isolated-status-token"}, account_id="UC-status-only")
    setup = submissions.setup()
    result = submissions.add_file(io.BytesIO(b"isolated original"), "status.mp4", {
        "auto_upload": True, "account_id": setup["account_id"], "privacy": setup["privacy"],
        "made_for_kids": False, "audience_version": setup["audience"]["group_version"],
        "reuse_basis": "owned", "agreed": True})
    source = db.fetch("sources", result["item"]["id"])
    project = db.create_project("Submitted status", origin="autopilot", source_id=source["id"])
    db.update("sources", source["id"], project_id=project["id"])
    db.insert("clips", {"project_id": project["id"], "start": 0, "end": 20, "status": "ready"})
    with db.connect() as conn:
        before = list(conn.iterdump())
    settings = db.get_settings()
    view = readiness.view(settings, {"youtube": {"connected": True}}, True)
    youtube = view["platforms"][0]
    assert youtube["automatic"] is True
    assert youtube["counts"]["preparing"] == 1 and youtube["counts"]["local_only"] == 0
    assert youtube["code"] == ("publishing_paused" if publishing_paused else "preparing")
    assert "Add a video link or file" in view["source_guidance"]["title"]
    activity = next(item for item in home.activity() if item["id"] == source["id"])
    assert "Make & upload request" in activity["posting"]
    assert rights.evaluate(source)["status"] == rights.MANUAL
    assert not settings["autopilot_youtube"] and not settings["autopilot_auto_publish"]
    assert not settings["autopilot_auto_schedule"]
    with db.connect() as conn:
        assert list(conn.iterdump()) == before
    db.update("source_submissions", result["submission"]["id"], revoked_at=time.time())
    assert readiness.view(settings, {"youtube": {"connected": True}}, True)["platforms"][0]["automatic"] is False
    assert "Uploads held" in next(item for item in home.activity() if item["id"] == source["id"])["posting"]

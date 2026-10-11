"""Discovery uses video evidence and durable preferences, with isolated data and no external calls."""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def signal(**patch):
    return {"id": "s1", "provider": "youtube_search", "platform": "youtube", "external_id": "abcdefghijk",
            "kind": "video", "title": "NFL interview: why teams change their game plan", "query": "NFL",
            "region": "US", "language": "", "published_at": time.time() - 3600,
            "score": 80, "score_mode": "platform_order", "components": {}, "metrics": {}, "raw": {}, **patch}


def test_search_hints_are_not_evidence_of_language_topics_or_audience():
    from clipfoundry.autopilot import providers, trends

    item = {"id": "abcdefghijk", "snippet": {"title": "Gardening in spring", "channelId": "UCgarden"},
            "contentDetails": {"duration": "PT30M"}, "statistics": {}}
    got = providers.signal_from_video(item, "youtube_search", 1, 5, "NFL", region="US", language="en")
    assert got["language"] == "" and got["raw"]["requested_language"] == "en"
    settings = {"trend_topics": "NFL", "trend_language": "en", "discovery_audience_terms": "United States"}
    assert "No match" in trends.preference_reason(got, settings)
    parts = trends.audience_parts(got, settings)
    assert parts["topic_fit"]["value"] == 0 and parts["language"]["value"] is None
    assert parts["audience_context"]["value"] is None
    assert "actual viewer location unknown" in parts["audience_context"]["note"]
    # Old stored rows recorded the requested language; they must not turn it into evidence after the upgrade.
    assert trends.reported_language({**got, "language": "en"}) == ""


def test_reported_language_and_excluded_topics_are_filtered():
    from clipfoundry.autopilot import trends

    settings = {"trend_topics": "NFL", "trend_language": "en", "discovery_excluded_topics": "gambling"}
    foreign = signal(language="es-MX", raw={"language_basis": "audio"})
    assert "language es" in trends.preference_reason(foreign, settings)
    english = {**foreign, "language": "en-US"}
    assert trends.preference_reason(english, settings) == ""
    assert "gambling" in trends.preference_reason({**english, "title": "NFL gambling interview"}, settings)
    assert "gambling" not in trends.preference_reason({**english, "title": "NFL antigambling campaign"}, settings)


def test_live_and_age_filters_preserve_curated_recordings():
    from clipfoundry.autopilot import trends

    settings = {"trend_topics": "NFL", "trend_max_age_hours": 72}
    assert "ambient loop" in trends.preference_reason(signal(kind="live", title="NFL countdown live"), settings)
    assert "Upcoming" in trends.preference_reason(signal(raw={"live_status": "upcoming"}), settings)
    old = signal(published_at=time.time() - 100 * 3600)
    assert "Older" in trends.preference_reason(old, settings)
    assert trends.preference_reason({**old, "provider": "youtube_channel"}, settings) == ""
    assert trends.preference_reason({**old, "title": "Garden tour", "raw": {"curated_channel": True}}, settings) == ""
    assert trends.preference_reason(signal(kind="live", title="NFL interview live"), settings) == ""


def test_audience_context_improves_ranking_without_claiming_viewer_data(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scout

    settings = {**db.get_settings(), "trend_topics": "Sports", "discovery_audience_terms": "NFL",
                "trend_language": "en"}
    src = {"platform": "youtube", "kind": "recorded", "duration": 1800, "category": "Sports"}
    generic = scout.score_source(src, signal(title="Sports interview"), settings, time.time())
    relevant = scout.score_source(src, signal(title="NFL sports interview"), settings, time.time())
    assert relevant["score"] > generic["score"]
    assert relevant["components"]["audience_context"]["status"] == "estimated"
    assert "actual viewer location unknown" in relevant["components"]["audience_context"]["note"]
    assert "clip_structure" in relevant["missing"] and "language" in relevant["missing"]
    assert relevant["confidence"] != "high"  # one metadata listing cannot prove transcript quality


def test_story_check_needs_actual_structure_and_skips_repetition():
    from clipfoundry.autopilot import scout

    complete = {"analysis": {"structure": {"hook": True, "context": True, "payoff": True}, "flags": []}}
    assert scout.clip_reason(complete, {}) == ""
    assert "payoff" in scout.clip_reason({"analysis": {"structure": {"hook": True, "context": True}}}, {})
    assert "hook, context, payoff" in scout.clip_reason({"title": "A powerful hook with an incredible payoff"}, {})
    repeat = {"analysis": {**complete["analysis"], "flags": [{"id": "repetitive", "severity": "warn"}]}}
    assert "repetitive" in scout.clip_reason(repeat, {})
    assert scout.clip_reason(repeat, {"discovery_require_complete_clips": False}) == ""
    assert "language es" in scout.transcript_reason({"platform": "youtube"}, "es", {"trend_language": "en"})
    assert scout.transcript_reason({"platform": "youtube"}, "", {"trend_language": "en"}) == ""
    assert scout.transcript_reason({"platform": "local"}, "es", {"trend_language": "en"}) == ""


def test_a_daily_target_never_fills_with_low_scoring_or_blocked_videos(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, rights, scout

    settings = {**db.get_settings(), "autopilot_sources_per_day": 10, "discovery_min_source_score": 60}
    rows = []
    for external, score in (("strong", 75), ("weak", 55), ("blocked", 99)):
        rows.append(db.insert("sources", {"platform": "url", "external_id": external, "kind": "recorded",
                                           "url": f"https://public.example/{external}.mp4", "title": external,
                                           "signal_id": "test-signal", "status": "eligible", "source_score": score,
                                           "expected_clips": 2}))
    rights.add_rule("source", rows[2]["id"], rights.BLOCKED, "Explicit block wins")
    picked = scout.select_for_today(settings)
    assert [s["id"] for s in picked] == [rows[0]["id"]]
    assert db.fetch("sources", rows[1]["id"])["status"] == "skipped"
    assert db.fetch("sources", rows[2]["id"])["status"] == "blocked"
    assert [j["ref_id"] for j in queue.jobs(worker="clip_hunter")] == [rows[0]["id"]]
    # Public local clipping remains separate from the reuse permission needed by both scheduling and publishing.
    with pytest.raises(rights.RightsBlocked):
        rights.gate(db.fetch("sources", rows[0]["id"]), "schedule", settings)
    with pytest.raises(rights.RightsBlocked):
        rights.gate(db.fetch("sources", rows[0]["id"]), "publish", settings)


def test_preferences_are_validated_and_survive_database_restart(data):
    from clipfoundry import db

    db.save_settings({"discovery_min_source_score": 999, "trend_language": "EN-US",
                      "discovery_excluded_topics": "gambling", "discovery_audience_terms": "NBA"})
    db.init()
    settings = db.get_settings()
    assert settings["discovery_min_source_score"] == 100 and settings["trend_language"] == "en-us"
    assert settings["discovery_excluded_topics"] == "gambling" and settings["discovery_audience_terms"] == "NBA"


def test_changed_preferences_reconsider_auto_skips_and_preserve_manual_skips(data):
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue, scout

    now = time.time()
    db.save_settings({"trend_topics": "NFL"})
    stored = scout.upsert_signal({**signal(provider="web_search", platform="url", title="Gardening interview"),
                                  "url": "https://public.example/garden.mp4", "raw": {"duration_s": 1800}}, now)
    host.WorkerHost(periodic=False)

    def scan():
        row = queue.enqueue("source_scout")
        return scout.source_scout(host.Job(row, "test"))

    scan()
    source = db.select("sources", "signal_id = ?", (stored["id"],))[0]
    assert source["status"] == "skipped" and "discovery_filter" in source["components"]
    manual_signal = scout.upsert_signal({**signal(provider="web_search", platform="url", external_id="manual",
                                                 title="Gardening interview"),
                                         "url": "https://public.example/manual.mp4"}, now)
    manual = db.insert("sources", {"platform": "url", "external_id": "manual", "status": "skipped",
                                    "status_note": "Skipped by you", "signal_id": manual_signal["id"]})
    db.save_settings({"trend_topics": "gardening"})
    scan()
    after = db.fetch("sources", source["id"])
    assert after["status"] == "queued" and "discovery_filter" not in after["components"]
    assert db.fetch("sources", manual["id"])["status_note"] == "Skipped by you"

"""Review-first discovery prepares unknown reuse terms without creating an upload permission."""
from __future__ import annotations

import time

import pytest

from test_quality_discovery import candidate, scan


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db
    from clipfoundry.autopilot import host

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"trend_topics": "interview", "autopilot_review_before_publish": True,
                      "autopilot_discovery_uploadable_only": True, "autopilot_public_videos": False,
                      "autopilot_sources_per_day": 0})
    host.WorkerHost(periodic=False)
    return tmp_path


def test_review_is_the_production_default(data):
    from clipfoundry import config

    assert config.DEFAULT_SETTINGS["autopilot_review_before_publish"] is True


def test_unknown_sources_enter_bounded_quality_queue_without_relabeling_rights(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, rights

    for index in range(15):
        candidate(f"review{index}", 65 + 2 * index)
    result = scan()
    assert {s["external_id"] for s in db.select("sources")} == {"review12", "review13", "review14"}
    assert all(s["rights_status"] == rights.MANUAL and s["status"] == "queued" for s in db.select("sources"))
    assert result["shortlist"]["admitted"] == 3
    assert len(queue.jobs(worker="clip_hunter")) == 3
    assert not db.select("source_rights") and not db.select("scheduled_publications")
    scan()
    assert len(db.select("sources")) == 6
    assert scan()["sources_new"] == 0
    assert len(queue.jobs(worker="clip_hunter")) == 6


def test_explicit_block_still_wins_when_reuse_is_reviewed_later(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    candidate("blocked", 100)
    candidate("allowed-for-review", 95)
    rights.add_rule("source", "url:blocked", rights.BLOCKED, "Owner excluded this source")
    result = scan()
    assert [s["external_id"] for s in db.select("sources")] == ["allowed-for-review"]
    assert result["shortlist"]["reasons"]["Blocked by your saved permissions"] == 1


def test_previously_filtered_unknown_source_recovers_without_deleting_history(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scout

    signal = candidate("old-filter", 95)
    saved = db.insert("sources", {**scout.source_from_signal(signal), "status": "skipped",
                                  "status_note": "Local use only: no recorded reuse permission",
                                  "components": {"discovery_filter": {"at": time.time(), "reason": "reuse"}}})
    result = scan()
    restored = db.fetch("sources", saved["id"])
    assert result["picked"] == [saved["id"]] and restored["status"] == "queued"
    assert restored["external_id"] == "old-filter" and not db.select("source_rights")


def test_manual_owner_skip_is_not_reactivated(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scout

    signal = candidate("owner-skipped", 100)
    saved = db.insert("sources", {**scout.source_from_signal(signal), "status": "skipped",
                                  "status_note": "Skipped by you"})
    assert scan()["picked"] == []
    assert db.fetch("sources", saved["id"])["status_note"] == "Skipped by you"


@pytest.mark.parametrize("review,filtered", [(True, False), (False, True)])
def test_official_topic_search_filter_matches_review_mode(data, monkeypatch, review, filtered):
    from clipfoundry import db
    from clipfoundry.autopilot import providers

    settings = {**db.get_settings(), "autopilot_review_before_publish": review, "youtube_api_key": "fake"}
    client = providers.YouTubeDiscovery(settings)
    calls = []
    monkeypatch.setattr(client, "most_popular", lambda region: [])
    monkeypatch.setattr(client, "search", lambda *args, **kwargs: calls.append(kwargs) or [])
    client.discover(["interview"], [], include_live=False)
    assert calls and all(call["creative_commons"] is filtered for call in calls)


def test_guidance_is_read_only_and_explains_review_without_upload_grant(data):
    from clipfoundry import db
    from clipfoundry.autopilot import readiness

    with db.connect() as connection:
        before = "\n".join(connection.iterdump())
    shown = readiness.source_guidance(db.get_settings())
    assert shown["review_before_publish"] and not shown["uploadable_only"]
    assert "Nothing uploads" in shown["detail"]
    assert shown["options"][0]["link"] == "#/queue/review"
    with db.connect() as connection:
        assert "\n".join(connection.iterdump()) == before

"""Quality-first searches shortlist real evidence without changing explicit intake or posting eligibility."""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db
    from clipfoundry.autopilot import host

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"trend_topics": "interview", "autopilot_sources_per_day": 30})
    host.WorkerHost(periodic=False)
    return tmp_path


def candidate(key: str, score: float = 90, **patch) -> dict:
    from clipfoundry import db

    return db.insert("trend_signals", {"provider": "web_search", "platform": "url", "external_id": key,
                                      "title": f"Interview {key}", "url": f"https://public.example/{key}.mp4",
                                      "kind": "video", "score": score, "score_mode": "momentum",
                                      "published_at": time.time() - 3600, "first_seen": time.time(),
                                      "last_checked": time.time(),
                                      "metrics": {}, "raw": {}, **patch})


def scan() -> dict:
    from clipfoundry.autopilot import host, queue, scout

    queued = queue.enqueue("source_scout")
    claimed = queue.claim("source_scout", "quality-test")
    assert claimed["id"] == queued["id"]
    result = scout.source_scout(host.Job(claimed, "quality-test"))
    queue.complete(claimed, "quality-test", result)
    return result


def test_default_shortlist_admits_only_three_best_sources_and_jobs(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, state

    for i in range(15):
        candidate(f"choice{i}", 65 + i * 2)
    result = scan()
    assert len(db.select("trend_signals")) == 15  # evidence remains; unchosen signals can compete again
    assert {s["external_id"] for s in db.select("sources")} == {"choice12", "choice13", "choice14"}
    assert len(queue.jobs(worker="clip_hunter")) == 3
    assert result["shortlist"]["admitted"] == 3 and result["shortlist"]["held"] == 12
    assert state.get("discovery:shortlist")["message"].endswith("estimate until analysis.")


def test_unfinished_backlog_stops_new_admission_without_changing_existing_work(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    for i in range(18):
        candidate(f"backlog{i}", 65 + i)
    scan()
    scan()
    before_sources = db.select("sources")
    before_jobs = queue.jobs(worker="clip_hunter")
    result = scan()
    assert result["sources_new"] == 0 and result["shortlist"]["backlog"] == 6
    assert result["shortlist"]["held"] == 12
    assert {s["id"] for s in db.select("sources")} == {s["id"] for s in before_sources}
    assert queue.jobs(worker="clip_hunter") == before_jobs


def test_waiting_for_rights_stays_bounded_and_chosen_inputs_bypass_the_full_backlog(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, rights

    db.save_settings({"autopilot_public_videos": False})
    for i in range(9):
        candidate(f"uncovered{i}", 70 + i)
    first, second, third = scan(), scan(), scan()
    assert first["sources_new"] == second["sources_new"] == 3
    assert third["sources_new"] == 0
    sources = db.select("sources")
    assert len(sources) == 6
    assert all(src["status"] == "needs_rights" and not src["selected_day"] for src in sources)
    assert all(src["rights_status"] == rights.MANUAL for src in sources)
    assert third["shortlist"]["backlog"] == 6 and third["shortlist"]["held"] == 3
    assert "Waiting for unfinished search picks" in third["shortlist"]["reasons"]
    assert queue.jobs(worker="clip_hunter") == []
    # A selected feed and recorded grant retain the owner's intent even while general search is full.
    candidate("chosen", provider="signal_feed", title="Selected creator's own explanation")
    rights.add_rule("url_prefix", "https://public.example/chosen.mp4", rights.ALLOWLISTED,
                    "Recorded creator permission for this direct original")
    after = scan()
    chosen = db.select("sources", "external_id = 'chosen'")[0]
    assert after["picked"] == [chosen["id"]] and chosen["status"] == "queued"
    assert chosen["rights_status"] == rights.ALLOWLISTED
    assert after["shortlist"]["backlog"] == 6
    assert len(db.select("sources", "status = 'needs_rights'")) == 6


def test_creator_topic_diversity_and_unknown_creator_do_not_form_a_fake_group(data):
    from clipfoundry import db

    candidate("strong-a", 99, channel_id="creator-a", topic="topic-a")
    candidate("same-creator", 98, channel_id="creator-a", topic="topic-b")
    candidate("second-a", 97, channel_id="creator-b", topic="topic-a")
    candidate("third-a", 96, channel_id="creator-c", topic="topic-a")
    candidate("other-topic", 95, topic="topic-b")
    result = scan()
    assert {s["external_id"] for s in db.select("sources")} == {"strong-a", "second-a", "other-topic"}
    assert result["shortlist"]["reasons"]["Keeping room for another creator"] == 1
    assert result["shortlist"]["reasons"]["Keeping room for another topic"] == 1


def test_high_popularity_cannot_override_topics_blocks_or_the_saved_floor(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    candidate("wrong-topic", 100, title="Gambling jackpot compilation", metrics={"views": {"value": 10**9}})
    candidate("blocked", 100)
    rights.add_rule("source", "url:blocked", rights.BLOCKED, "Do not use this video")
    candidate("weak", 30)
    candidate("strong", 99)
    db.save_settings({"discovery_min_source_score": 60})
    result = scan()
    assert [s["external_id"] for s in db.select("sources")] == ["strong"]
    assert result["shortlist"]["filtered"] == 3 and len(result["picked"]) == 1
    assert db.get_settings()["discovery_min_source_score"] == 60


def test_simultaneous_reuploads_do_not_both_become_sources(data):
    from clipfoundry import db

    title = "Interview about learning to cook Italian pasta safely"
    candidate("original", 99, title=title)
    candidate("copy", 98, title=title)
    candidate("different", 97, title="Interview investigating a lost historical temple")
    result = scan()
    assert {s["external_id"] for s in db.select("sources")} == {"original", "different"}
    assert result["shortlist"]["reasons"]["Likely duplicate of a stronger shortlisted video"] == 1


def test_weak_search_picks_stop_at_daily_attempt_budget_but_owned_files_still_refill(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scout

    db.save_settings({"autopilot_sources_per_day": 1})
    candidate("first", 99)
    candidate("next", 98)
    first = scan()["picked"][0]
    db.update("sources", first, status="weak", clips_selected=0)
    result = scan()
    assert result["picked"] == [] and result["shortlist"]["daily_attempts_remaining"] == 0
    video = data / "own.mp4"
    video.write_bytes(b"local access only")
    rights.add_rule("folder", str(data), rights.OWNED, "My videos")
    own = db.insert("sources", {"platform": "local", "external_id": "owned", "local_path": str(video),
                                "status": "eligible", "expected_clips": 2, "source_score": 80})
    assert [s["id"] for s in scout.select_for_today(db.get_settings())] == [own["id"]]


def test_quality_mode_opt_out_restores_all_results_and_target_refill(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scout

    db.save_settings({"discovery_quality_first": False, "autopilot_sources_per_day": 1})
    for i in range(8):
        candidate(f"legacy{i}", 80 + i)
    first = scan()["picked"][0]
    assert len(db.select("sources")) == 8
    db.update("sources", first, status="analyzed", clips_selected=0)
    assert scout.still_needed(db.get_settings()) == 1
    assert len(scan()["picked"]) == 1


def test_chosen_channels_and_confirmed_agreements_keep_explicit_intent(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, verify

    db.save_settings({"discovery_candidates_per_scan": 1, "discovery_queue_limit": 1})
    for i in range(4):
        candidate(f"selected{i}", provider="youtube_channel", platform="youtube", channel_id="UCselected",
                  url=f"https://www.youtube.com/watch?v=selected{i}", title=f"A chosen topic number {i}",
                  raw={"reported_by": verify.YOUTUBE_DATA, "duration_s": 1800})
    candidate("agreement", platform="youtube", provider="youtube_search", channel_id="UCagreement",
              url="https://www.youtube.com/watch?v=agreement", raw={"reported_by": verify.YOUTUBE_DATA,
                                                                             "duration_s": 1800})
    rights.add_rule("channel", "UCagreement", rights.ALLOWLISTED, "Recorded creator agreement", platform="youtube")
    result = scan()
    assert len(db.select("sources")) == 5 and len(result["picked"]) == 5
    assert result["shortlist"]["checked"] == 0
    agreed = next(s for s in db.select("sources") if s["external_id"] == "agreement")
    assert agreed["rights_status"] == rights.ALLOWLISTED


def test_missing_metrics_and_transcript_structure_remain_unknown(data):
    from clipfoundry import db

    candidate("unknown", 99)
    scan()
    source = db.select("sources")[0]
    assert source["metrics"] == {}
    evidence = source["components"]["evidence"]
    assert "clip_structure" in evidence["missing"] and "language" in evidence["missing"]
    assert evidence["confidence"] == "low"


def test_shortlist_settings_are_bounded_and_survive_restart(data):
    from clipfoundry import db

    db.save_settings({"discovery_quality_first": False, "discovery_candidates_per_scan": 500,
                      "discovery_queue_limit": -4, "discovery_creator_limit": 0})
    db.init()
    settings = db.get_settings()
    assert settings["discovery_quality_first"] is False
    assert settings["discovery_candidates_per_scan"] == 30
    assert settings["discovery_queue_limit"] == settings["discovery_creator_limit"] == 1


def test_broad_live_picks_share_daily_budget_and_explicit_streams_keep_running(data):
    from clipfoundry import db
    from clipfoundry.autopilot import host, live, queue, scout

    db.save_settings({"autopilot_sources_per_day": 1})
    # Deliberately represent existing candidates, which quality mode never deletes or cancels.
    for i in range(2):
        sig = candidate(f"live{i}", 99 - i, kind="live")
        src = scout.source_from_signal(sig)
        db.insert("sources", {**src, "status": "eligible", "source_score": 99 - i})
    explicit = db.insert("sources", {"platform": "stream", "external_id": "manual-live", "user_added": 1,
                                     "kind": "live", "url": "https://public.example/manual.m3u8",
                                     "status": "eligible"})
    row = queue.enqueue("live_watch")
    result = live.live_watch(host.Job(row, "live-test"))
    assert len(result["started"]) == 2 and explicit["id"] in result["started"]
    broad = db.select("sources", "user_added = 0 AND status = 'ingesting'")
    assert len(broad) == 1 and broad[0]["external_id"] == "live0"
    assert broad[0]["selected_day"] == scout.local_day(db.get_settings())
    assert db.select("sources", "external_id = 'live1'")[0]["status"] == "eligible"
    assert scout.discovery_attempts_remaining(db.get_settings()) == 0
    assert sum(j["kind"] == "live_capture" for j in queue.jobs(worker="live_monitor")) == 2


def test_held_and_filtered_searches_are_not_shown_as_found_opportunities(data):
    from clipfoundry.autopilot import home

    for i in range(8):
        candidate(f"listing{i}", 70 + i)
    result = scan()
    opportunities = home.opportunities(20)
    assert {item["source_id"] for item in opportunities} == set(result["picked"])
    assert len(opportunities) == 3


def test_empty_quality_shortlist_explains_rejected_finds_without_claiming_work(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    db.save_settings({"autopilot_enabled": True, "discovery_min_source_score": 100})
    for i in range(8):
        candidate(f"uncertain{i}", 90 + i)
    state.put("trend:last_scan", {"at": time.time(), "signals": 8})
    result = scan()
    assert home.opportunities() == []
    assert db.select("sources") == [] and result["shortlist"]["filtered"] == 8
    assert "8 weaker or unsuitable finds were ignored" in home.empty_message(db.get_settings(), True, [])


def test_simultaneous_recorded_and_live_workers_do_not_exceed_the_daily_budget(data):
    import concurrent.futures
    import threading

    from clipfoundry import db
    from clipfoundry.autopilot import host, live, queue, scout

    db.save_settings({"autopilot_sources_per_day": 1})
    for key, kind in (("recorded", "video"), ("stream", "live")):
        signal = candidate(key, kind=kind)
        db.insert("sources", {**scout.source_from_signal(signal), "status": "eligible",
                              "source_score": 80, "expected_clips": 2})
    row = queue.enqueue("live_watch")
    barrier = threading.Barrier(2)

    def recordings():
        barrier.wait(timeout=3)
        return scout.select_for_today(db.get_settings())

    def streams():
        barrier.wait(timeout=3)
        return live.live_watch(host.Job(row, "concurrent-test"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(recordings), pool.submit(streams)]
        [future.result(timeout=5) for future in futures]
    attempts = [src for src in db.select("sources") if src["selected_day"]]
    assert len(attempts) == 1 and scout.discovery_attempts_remaining(db.get_settings()) == 0
    assert sum(job["kind"] in ("hunt_source", "live_capture") for job in queue.jobs()) == 1

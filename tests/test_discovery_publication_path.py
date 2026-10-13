"""Discovery keeps real reuse coverage useful without relaxing budgets, history, or final publishing gates."""
from __future__ import annotations

import time

import pytest


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db
    from clipfoundry.autopilot import host

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"trend_topics": "interview", "autopilot_sources_per_day": 3})
    db.save_account("youtube", tokens={"access_token": "fake"}, account_id="UCtest")
    host.WorkerHost(periodic=False)
    return tmp_path


def candidate(key: str, score: float = 99, *, covered: bool = False, url: str = "") -> dict:
    from clipfoundry import db

    now = time.time()
    platform = "commons" if covered else "url"
    address = url or (f"https://upload.wikimedia.org/{key}.webm" if covered else
                      f"https://public.example/{key}.mp4")
    return db.insert("trend_signals", {
        "provider": "library" if covered else "web_search", "platform": platform, "external_id": key,
        "title": f"Interview explanation {key}", "url": address, "kind": "video", "score": score,
        "score_mode": "momentum", "first_seen": now, "last_checked": now, "published_at": now - 3600,
        "metrics": {}, "raw": {"license": "cc-by-4.0", "license_name": "CC BY 4.0", "duration_s": 1800}
        if covered else {},
    })


def source(sig: dict, status: str, **fields) -> dict:
    from clipfoundry import db
    from clipfoundry.autopilot import scout

    return db.insert("sources", {**scout.source_from_signal(sig), "status": status,
                                 "source_score": sig["score"], "expected_clips": 2, **fields})


def scan() -> dict:
    from clipfoundry.autopilot import host, queue, scout

    row = queue.enqueue("source_scout")
    claimed = queue.claim("source_scout", "publication-path-test")
    assert claimed["id"] == row["id"]
    result = scout.source_scout(host.Job(claimed, "publication-path-test"))
    queue.complete(claimed, "publication-path-test", result)
    return result


def test_six_parked_rights_holds_do_not_starve_a_reusable_candidate(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, rights

    db.save_settings({"autopilot_public_videos": False})
    parked = [source(candidate(f"uncovered{i}"), "needs_rights", rights_status=rights.MANUAL) for i in range(6)]
    candidate("available", 90, covered=True)
    candidate("another-uncovered", 100)
    result = scan()
    available = db.select("sources", "external_id = 'available'")[0]
    assert result["picked"] == [available["id"]]
    assert available["rights_status"] == rights.CC and available["status"] == "queued"
    assert result["shortlist"]["backlog"] == result["shortlist"]["parked_backlog"] == 6
    assert result["shortlist"]["workable_backlog"] == 0
    assert not db.select("sources", "external_id = 'another-uncovered'")
    assert all(db.fetch("sources", row["id"])["status"] == "needs_rights" for row in parked)
    assert all(db.fetch("sources", row["id"])["rights_status"] == rights.MANUAL for row in parked)
    assert len(queue.jobs(worker="clip_hunter")) == 1


def test_six_missing_library_files_do_not_starve_an_accessible_candidate(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    parked = [source(candidate(f"missing{i}", covered=True, url=f"https://public.example/missing{i}.webm"),
                     "needs_file", rights_status=rights.CC) for i in range(6)]
    candidate("available", 90, covered=True)
    result = scan()
    assert len(result["picked"]) == 1
    assert db.fetch("sources", result["picked"][0])["external_id"] == "available"
    assert result["shortlist"]["parked_backlog"] == 6
    assert all(db.fetch("sources", row["id"])["status"] == "needs_file" for row in parked)
    assert all(db.fetch("sources", row["id"])["rights_status"] == rights.CC for row in parked)


def test_active_search_backlog_still_stops_new_reusable_admission(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    db.save_settings({"autopilot_sources_per_day": 30})
    for i in range(6):
        row = source(candidate(f"active{i}"), "queued")
        queue.enqueue("hunt_source", {"source_id": row["id"]}, ref=("source", row["id"]))
    candidate("available", covered=True)
    before = queue.jobs(worker="clip_hunter")
    result = scan()
    assert result["shortlist"]["backlog"] == 6
    assert not db.select("sources", "external_id = 'available'")
    assert queue.jobs(worker="clip_hunter") == before


def test_reusable_sources_win_the_daily_attempt_over_higher_local_only_scores(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scout

    db.save_settings({"autopilot_sources_per_day": 1})
    for i in range(3):
        candidate(f"popular{i}", 99 - i)
    candidate("available", 90, covered=True)
    result = scan()
    assert len(result["picked"]) == 1
    chosen = db.fetch("sources", result["picked"][0])
    assert chosen["external_id"] == "available" and chosen["rights_status"] == rights.CC
    assert len(db.select("sources")) == 1
    assert scout.discovery_attempts_remaining(db.get_settings()) == 0


def test_existing_eligible_local_only_rows_do_not_take_a_reusable_sources_turn(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    db.save_settings({"autopilot_sources_per_day": 1})
    local_only = source(candidate("popular", 99), "eligible", rights_status=rights.MANUAL)
    reusable = source(candidate("available", 90, covered=True), "eligible", rights_status=rights.CC)
    result = scan()
    assert result["picked"] == [reusable["id"]]
    assert db.fetch("sources", local_only["id"])["status"] == "eligible"
    assert db.fetch("sources", local_only["id"])["rights_status"] == rights.MANUAL
    assert not db.fetch("sources", local_only["id"])["selected_day"]


def test_reuse_coverage_does_not_lower_the_quality_floor(data):
    from clipfoundry import db

    db.save_settings({"autopilot_sources_per_day": 1, "discovery_min_source_score": 60})
    candidate("weak-covered", 1, covered=True)
    candidate("strong-local", 99)
    result = scan()
    assert len(result["picked"]) == 1
    assert db.fetch("sources", result["picked"][0])["external_id"] == "strong-local"
    assert not db.select("sources", "external_id = 'weak-covered'")
    assert result["shortlist"]["filtered"] == 1


def test_reusable_candidates_cannot_bypass_an_exhausted_daily_attempt_budget(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scout

    for i in range(3):
        source(candidate(f"processed{i}"), "weak", selected_day=scout.local_day(db.get_settings()),
               rights_status=rights.MANUAL)
    candidate("available", covered=True)
    result = scan()
    assert result["picked"] == [] and result["shortlist"]["daily_attempts_remaining"] == 0
    assert not db.select("sources", "external_id = 'available'")


def test_explicit_local_only_link_still_runs_before_automatic_reusable_sources(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scout

    db.save_settings({"autopilot_sources_per_day": 1, "autopilot_public_videos": False})
    manual = db.insert("sources", {"platform": "url", "external_id": "manual", "title": "My chosen video",
                                   "url": "https://public.example/manual.mp4", "user_added": 1,
                                   "status": "eligible", "source_score": 70, "expected_clips": 2,
                                   "rights_status": rights.MANUAL})
    candidate("available", covered=True)
    result = scan()
    assert result["picked"][0] == manual["id"] and len(result["picked"]) == 2
    assert db.fetch("sources", manual["id"])["rights_status"] == rights.MANUAL
    assert scout.discovery_attempts_remaining(db.get_settings()) == 0


def test_accessible_local_only_discovery_is_preserved_when_no_reusable_video_exists(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    candidate("popular", 99)
    result = scan()
    assert len(result["picked"]) == 1
    chosen = db.fetch("sources", result["picked"][0])
    assert chosen["external_id"] == "popular" and chosen["status"] == "queued"
    assert chosen["rights_status"] == rights.MANUAL
    assert rights.evaluate(chosen, db.get_settings())["auto_allowed"] is False


def test_disabling_automatic_license_use_retains_the_owners_rights_policy(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    db.save_settings({"autopilot_sources_per_day": 1, "rights_auto_creative_commons": False})
    candidate("popular", 99)
    candidate("licensed-but-disabled", 90, covered=True)
    result = scan()
    assert len(result["picked"]) == 1
    chosen = db.fetch("sources", result["picked"][0])
    assert chosen["external_id"] == "popular" and chosen["rights_status"] == rights.MANUAL
    assert not db.select("sources", "external_id = 'licensed-but-disabled'")
    assert db.get_settings()["rights_auto_creative_commons"] is False

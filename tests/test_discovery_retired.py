"""Automatic source discovery is retired (CF2-16): fresh and migrated profiles never search for videos, old discovery
work is parked with an explanation, nothing is deleted, and submitted inputs keep running."""
from __future__ import annotations

import json
import time

import pytest

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    return tmp_path


def _all_handlers():
    from clipfoundry.autopilot import handlers  # noqa: F401 - registers every job handler
    from clipfoundry.autopilot import host

    return host


def test_fresh_profile_never_schedules_a_search_even_with_autopilot_on(data):
    from clipfoundry import config, db
    from clipfoundry.autopilot import queue, scout, state

    host = _all_handlers()
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_live_monitoring": True})
    settings = db.get_settings()
    assert settings["autopilot_input_mode"] == "submitted" and not config.discovery_enabled(settings)
    started = []
    now = time.time()
    for hour in range(48):  # two idle days of periodic slots
        started += host.run_periodic(db.get_settings(), now + hour * 3600)
    assert not set(started) & set(config.DISCOVERY_JOB_KINDS)
    assert {"maintenance", "schedule_tick"} <= set(started)
    assert scout.refill({"id": "x"}) is None
    assert not [j for j in queue.jobs() if j["kind"] in config.DISCOVERY_JOB_KINDS]
    assert state.enabled(db.get_settings())


def test_old_clients_cannot_turn_discovery_back_on(data):
    from fastapi.testclient import TestClient

    from clipfoundry import config, db
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        r = client.put("/api/settings", headers=H, json={"autopilot_input_mode": "discovery"})
        assert r.status_code == 200
    assert db.get_settings()["autopilot_input_mode"] == "submitted"
    assert not config.discovery_enabled({"autopilot_input_mode": "discovery"})


def test_migrated_discovery_profile_parks_discovery_work_and_keeps_everything_else(data, monkeypatch):
    from clipfoundry import config, db
    from clipfoundry.autopilot import queue

    # --- an older profile, written while discovery still existed
    monkeypatch.setattr(config, "DISCOVERY_RETIRED", False)
    db.init()
    db.save_settings({"autopilot_input_mode": "discovery", "autopilot_enabled": True, "clip_count": 7})
    db.execute("DELETE FROM autopilot_state WHERE key = ?", (db.DISCOVERY_RETIRED_MIGRATION,))
    trend = queue.enqueue("trend_scan", {"periodic": True}, idem_key="trend:1")
    scoutjob = queue.enqueue("source_scout", {"reason": "replacement"}, idem_key="scout:1")
    finished = queue.enqueue("trend_scan", {"periodic": True}, idem_key="trend:0")
    db.execute("UPDATE worker_jobs SET status = 'completed' WHERE id = ?", (finished["id"],))
    picked = db.insert("sources", {"platform": "youtube", "external_id": "picked00001", "url": "https://x/1",
                                   "title": "Found by discovery", "status": "queued", "user_added": 0})
    mine = db.insert("sources", {"platform": "youtube", "external_id": "mine0000001", "url": "https://x/2",
                                 "title": "Added by me", "status": "queued", "user_added": 1})
    done = db.insert("sources", {"platform": "youtube", "external_id": "done0000001", "url": "https://x/3",
                                 "title": "Already clipped", "status": "analyzed", "user_added": 0})
    hunt_picked = queue.enqueue("hunt_source", {"source_id": picked["id"]}, idem_key="hunt:picked")
    hunt_mine = queue.enqueue("hunt_source", {"source_id": mine["id"]}, idem_key="hunt:mine")
    project = db.create_project("Earlier clips", status="ready", origin="autopilot", source_id=done["id"])
    # --- the upgrade starts the app on the same database
    monkeypatch.setattr(config, "DISCOVERY_RETIRED", True)
    db._ready.clear()  # noqa: SLF001 - a new process
    db.init()
    settings = db.get_settings()
    assert settings["autopilot_input_mode"] == "submitted" and settings["clip_count"] == 7
    for job in (trend, scoutjob, hunt_picked):
        row = queue.get(job["id"])
        assert row["status"] == "canceled" and "retired" in row["message"] and "nothing was deleted" in row["message"]
    assert queue.get(finished["id"])["status"] == "completed"  # history kept as it was
    assert queue.get(hunt_mine["id"])["status"] == "queued"  # a video you added keeps going
    assert db.fetch("sources", picked["id"])["status"] == "canceled"
    assert db.fetch("sources", mine["id"])["status"] == "queued"
    assert db.fetch("sources", done["id"])["status"] == "analyzed"
    assert db.get_project(project["id"])["status"] == "ready"
    event = db.select("autopilot_events", "kind = 'discovery_retired'")
    assert len(event) == 1
    record = json.loads(event[0]["data"]) if isinstance(event[0]["data"], str) else event[0]["data"]
    assert record["previous_mode"] == "discovery" and record["jobs_canceled"] == 3
    # once only: a later start changes nothing and adds no second audit entry
    db._ready.clear()  # noqa: SLF001
    db.init()
    assert len(db.select("autopilot_events", "kind = 'discovery_retired'")) == 1
    assert queue.get(hunt_mine["id"])["status"] == "queued"


def test_idle_worker_host_with_periodic_jobs_makes_no_source_search(data, monkeypatch):
    """The real host and its periodic dispatcher run idle on a migrated discovery profile: no discovery job and no
    call to any search provider."""
    from clipfoundry import config, db
    from clipfoundry.autopilot import providers, queue

    host = _all_handlers()
    monkeypatch.setattr(config, "DISCOVERY_RETIRED", False)
    db.init()
    db.save_settings({"autopilot_input_mode": "discovery", "autopilot_enabled": True,
                      "youtube_api_key": "would-search", "autopilot_live_monitoring": True})
    db.execute("DELETE FROM autopilot_state WHERE key = ?", (db.DISCOVERY_RETIRED_MIGRATION,))
    monkeypatch.setattr(config, "DISCOVERY_RETIRED", True)
    db._ready.clear()  # noqa: SLF001
    called = []
    monkeypatch.setattr(providers.httpx, "Client", lambda *a, **k: called.append(a) or (_ for _ in ()).throw(
        AssertionError("a search provider was called")))
    monkeypatch.setattr(host, "PERIODIC", [(kind, lambda _s: 30.0, active) for kind, _p, active in host.PERIODIC])
    worker = host.WorkerHost(poll=0.05)
    assert worker.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        worker.stop(timeout=30)
    kinds = {j["kind"] for j in queue.jobs()}
    assert not kinds & set(config.DISCOVERY_JOB_KINDS) and not kinds & {"hunt_source", "analyze_source"}
    assert not called

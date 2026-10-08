"""The office feed: robots move only on recorded job transitions; reports, decisions, controls and health."""
from __future__ import annotations

import time

import pytest

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def _until(fn, timeout: float = 10):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("condition not met")


def test_every_registry_role_has_a_department_and_manager():
    from clipfoundry import office

    assert len(office.ROLE_DEPARTMENT) == 25
    assert set(office.MANAGER.values()) <= set(office.ROLE_DEPARTMENT)
    assert set(office.KIND_ROLE.values()) <= set(office.ROLE_DEPARTMENT)
    from clipfoundry.autopilot import queue

    every_kind = {k for _, kinds in queue.WORKERS.values() for k in kinds}
    assert every_kind <= set(office.KIND_ROLE)  # no job runs without a responsible robot


def test_idle_office_is_truthful(data):
    from clipfoundry import office

    snap = office.snapshot()
    assert snap["run_state"] == "stopped" and snap["mission"]["title"] == "Stopped"
    assert {r["state"] for r in snap["robots"]} == {"lounge"}  # nobody pretends to work
    assert snap["next_upload"] is None and snap["health"]["state"] in ("Healthy", "Unknown", "Degraded", "Error")


def test_job_transitions_become_reports_reviews_and_decisions(data):
    from clipfoundry import db, office
    from clipfoundry.autopilot import host as host_mod
    from clipfoundry.autopilot import queue

    db.save_settings({"autopilot_enabled": True})
    h = host_mod.WorkerHost(workers=["maintenance"], poll=0.05, periodic=False)
    assert h.start()
    try:
        ok = queue.enqueue("selftest", {"result": {"x": 1}})
        bad = queue.enqueue("selftest", {"fail_times": 5, "retry_delay": 0.01}, max_attempts=1)
        h.wake()
        _until(lambda: queue.get(ok["id"])["status"] == "completed" and queue.get(bad["id"])["status"] == "failed")
        feed = _until(lambda: (lambda f: f if any(e["type"] == "office.boss_decision" for e in f["events"])
                               and sum(e["type"] == "office.manager_review" for e in f["events"]) >= 2
                               else None)(office.events(0)))
    finally:
        h.stop()
    by_job: dict = {}
    for e in feed["events"]:
        by_job.setdefault(e["job_id"], []).append(e)
    good = [e["type"] for e in by_job[ok["id"]]]
    assert good == ["office.task_started", "office.worker_report", "office.manager_review"]
    review = by_job[ok["id"]][-1]
    assert review["role"] == "switch" and review["data"]["review"] == "accepted" and review["data"]["rules"]
    failed = {e["type"]: e for e in by_job[bad["id"]]}
    assert failed["office.manager_review"]["data"]["review"] == "escalated"
    assert failed["office.boss_decision"]["role"] == "command"
    assert "Self-test failure" in failed["office.worker_report"]["message"]  # the real reason, not just "Failed"
    # cursor: nothing is returned twice
    again = office.events(feed["cursor"])
    assert all(e["id"] > feed["cursor"] for e in again["events"])


def test_feed_reports_a_gap_instead_of_replaying_a_backlog(data):
    from clipfoundry import office
    from clipfoundry.autopilot import state

    for i in range(30):
        state.event("office.task_started", f"x{i}", role="radar", job_id=str(i))
    out = office.events(0, limit=10)
    assert out["gap"] and len(out["events"]) == 10


def test_controls_follow_the_real_state(data):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        assert c.post("/api/office/control", json={"action": "start"}).status_code == 403  # page header needed
        assert c.post("/api/office/control", headers=H, json={"action": "start"}).json()["run_state"] == "running"
        assert c.post("/api/office/control", headers=H, json={"action": "start"}).json()["run_state"] == "running"
        assert c.post("/api/office/control", headers=H, json={"action": "pause"}).json()["run_state"] == "paused"
        assert c.post("/api/office/control", headers=H, json={"action": "resume"}).json()["run_state"] == "running"
        r = c.post("/api/office/control", headers=H, json={"action": "pause_publishing"}).json()
        assert r["publishing_paused"] and db.get_settings()["autopilot_publish_paused"]
        assert c.post("/api/office/control", headers=H, json={"action": "stop"}).json()["run_state"] == "stopped"
        assert c.post("/api/office/control", headers=H, json={"action": "resume"}).json()["run_state"] == "running"
        assert c.post("/api/office/control", headers=H, json={"action": "explode"}).status_code == 400
        snap = c.get("/api/office").json()
        assert snap["audience"] and len(snap["robots"]) == 25 and snap["cursor"] > 0
        h = c.get("/api/system/health").json()
        assert {x["id"] for x in h["checks"]} >= {"scheduler", "queue", "disk", "ffmpeg", "gpu"}
        assert next(x for x in h["checks"] if x["id"] == "network")["state"] == "Unknown"


def test_stale_heartbeat_is_an_error_not_green(data):
    from clipfoundry import db, health
    from clipfoundry.autopilot import state

    db.save_settings({"autopilot_enabled": True})
    state.put("host_heartbeat", {"at": time.time() - 3600})
    s = next(c for c in health.checks() if c["id"] == "scheduler")
    assert s["state"] == "Error" and "min ago" in s["reason"]

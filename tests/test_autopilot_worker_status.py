"""Worker progress describes the current live job rather than a previous completed result."""
import time

from clipfoundry import db
from clipfoundry.autopilot import host, queue, routes


def test_worker_status_exposes_current_kind_and_only_fresh_active_progress(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    worker = host.WorkerHost(periodic=False)
    row = queue.enqueue("live_capture", {"source_id": "example"})
    row = queue.claim("live_monitor", "test-worker")
    queue.progress(row["id"], 0.35, "Listening", "live")
    worker.set_state("live_monitor", "working", host.Job(row, "test-worker"))

    def current():
        return next(r for r in routes.workers()["workers"] if r["name"] == "live_monitor")

    assert current()["job_kind"] == "live_capture"
    assert current()["progress"] == 0.35
    db.execute("UPDATE worker_state SET heartbeat = ? WHERE name = ?", (time.time() - 120, "live_monitor"))
    assert current()["stale"] and current()["progress"] is None
    db.execute("UPDATE worker_state SET heartbeat = ? WHERE name = ?", (time.time(), "live_monitor"))
    queue.complete(row, "test-worker")
    assert current()["job_kind"] == "live_capture" and current()["progress"] is None
    assert current()["status"] == "idle"  # a fresh heartbeat cannot make a terminal job look busy


def test_completed_worker_retains_real_job_kind_until_idle(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    worker = host.WorkerHost(periodic=False)
    monkeypatch.setitem(host.HANDLERS, "live_watch", lambda job: {"message": "Checked for live videos"})
    queue.enqueue("live_watch")
    row = queue.claim("live_monitor", "test-worker")
    worker._run("live_monitor", row)
    result = next(r for r in routes.workers()["workers"] if r["name"] == "live_monitor")
    assert result["status"] == "completed" and result["job_kind"] == "live_watch"
    assert result["progress"] is None

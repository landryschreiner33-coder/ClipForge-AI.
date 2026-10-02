"""Autopilot foundation: persistent tables, the durable job queue, the worker host and the GPU resource manager."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path / "data"


def _until(cond, timeout: float = 10.0, step: float = 0.05):
    end = time.time() + timeout
    while time.time() < end:
        value = cond()
        if value:
            return value
        time.sleep(step)
    raise AssertionError("condition not reached")


# ------------------------------------------------------------------ persistence
def test_all_autopilot_tables_exist(data):
    from clipfoundry import db

    with db.connect() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table in ("trend_signals", "trend_history", "sources", "source_rights", "worker_jobs", "worker_state",
                  "clip_candidates", "clip_scores", "clip_analysis", "metadata_candidates", "scheduled_publications",
                  "platform_limits", "autopilot_state", "learning_metrics", "quota_usage", "action_items"):
        assert table in names, table


def test_deleting_a_video_removes_its_clip_records_but_keeps_post_history(data):
    """The Privacy Policy says what deleting a video removes: its clips, transcript windows, analysis and post text.
    What stays is the post history and each clip's fingerprint, which stops the same clip from being posted twice."""
    from clipfoundry import db

    project = db.create_project("Talk")
    clip = db.create_clip(project["id"], title="A moment", start=1.0, end=31.0)
    db.insert("clip_candidates", {"id": f"{project['id']}-1", "project_id": project["id"], "clip_id": clip["id"],
                                  "start": 1.0, "end": 31.0})
    db.insert("clip_analysis", {"clip_id": clip["id"], "project_id": project["id"]}, key="clip_id")
    db.insert("clip_scores", {"clip_id": clip["id"]}, key="clip_id")
    db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": "youtube", "title": "A moment"})
    db.insert("clip_fingerprints", {"clip_id": clip["id"]}, key="clip_id")
    db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "youtube", "status": "canceled"})
    db.delete_project(project["id"])
    for table in ("clips", "clip_candidates", "clip_analysis", "clip_scores", "metadata_candidates"):
        assert not db.scalar(f"SELECT COUNT(*) FROM {table}"), table
    assert db.scalar("SELECT COUNT(*) FROM clip_fingerprints") == 1
    assert db.scalar("SELECT COUNT(*) FROM scheduled_publications") == 1


def test_old_database_is_migrated(monkeypatch, tmp_path):
    folder = tmp_path / "old"
    folder.mkdir()
    conn = sqlite3.connect(folder / "clipfoundry.db")
    conn.executescript("CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL, "
                       "updated_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'created', source_path TEXT, "
                       "options TEXT DEFAULT '{}', info TEXT DEFAULT '{}');"
                       "INSERT INTO projects (id, name, created_at, updated_at) VALUES ('p1', 'old', 1, 1);")
    conn.close()
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(folder))
    from clipfoundry import db

    p = db.get_project("p1")
    assert p["origin"] == "manual" and p["source_id"] == ""  # added with defaults, existing row kept


def test_autopilot_settings_are_validated(data):
    from clipfoundry import db

    s = db.save_settings({"autopilot_daily_target": 500, "autopilot_timezone": "Mars/Base",
                          "autopilot_active_start": -3, "trend_region": "us", "youtube_api_key": "AIza-secret"})
    assert s["autopilot_daily_target"] == 100 and s["autopilot_timezone"] == "America/Chicago"
    assert s["autopilot_active_start"] == 0 and s["trend_region"] == "US" and s["youtube_api_key"] == "AIza-secret"
    with db.connect() as conn:
        raw = conn.execute("SELECT value FROM settings WHERE key = 'youtube_api_key'").fetchone()[0]
    assert "AIza-secret" not in raw  # sealed at rest


def test_every_secret_setting_is_sealed_at_rest_including_older_saves(data):
    import json

    from clipfoundry import config, db

    assert config.SEALED_KEYS == config.SECRET_KEYS
    db.save_settings({"openai_api_key": "sk-new", "anthropic_api_key": "sk-ant-new"})
    # a key saved by a version that did not seal it yet is sealed the next time the app opens the database
    with db.connect() as conn:
        conn.execute("UPDATE settings SET value = ? WHERE key = 'openai_api_key'", (json.dumps("sk-old"),))
    db._ready.clear()
    with db.connect() as conn:
        raw = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    assert "sk-old" not in raw["openai_api_key"] and "sk-ant-new" not in raw["anthropic_api_key"]
    s = db.get_settings()
    assert s["openai_api_key"] == "sk-old" and s["anthropic_api_key"] == "sk-ant-new"


def test_request_addresses_stay_out_of_the_log(capsys):
    # A YouTube Data API key travels in the request address (?key=); the worker's output is data/logs/workers.log.
    import logging

    import httpx

    from clipfoundry.__main__ import setup_logging

    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    root.handlers = []
    try:
        setup_logging()
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        with httpx.Client(transport=transport) as client:
            client.get("https://www.googleapis.com/youtube/v3/videos?id=x&key=AIza-secret")
    finally:
        root.handlers, root.level = handlers, level
        logging.getLogger("httpx").setLevel(logging.NOTSET)
    assert "AIza-secret" not in capsys.readouterr().err


# ------------------------------------------------------------------ queue
def test_idempotent_enqueue_and_priority(data):
    from clipfoundry.autopilot import queue

    a = queue.enqueue("selftest", {"n": 1}, idem_key="k1")
    assert queue.enqueue("selftest", {"n": 2}, idem_key="k1")["id"] == a["id"]
    b = queue.enqueue("selftest", priority=5)
    assert queue.claim("maintenance", "w1")["id"] == b["id"]  # higher priority first
    assert queue.claim("maintenance", "w1")["id"] == a["id"]
    assert queue.claim("maintenance", "w1") is None


def test_retry_backoff_then_give_up(data):
    from clipfoundry.autopilot import queue

    job = queue.enqueue("selftest", max_attempts=2)
    j = queue.claim("maintenance", "w")
    assert queue.retry_or_fail(j, "w", "network down", delay=0) == "retrying"
    assert queue.get(job["id"])["status"] == "retrying"
    j = queue.claim("maintenance", "w")
    assert j["attempts"] == 2
    assert queue.retry_or_fail(j, "w", "network down") == "failed"
    assert "gave up after 2 attempts" in queue.get(job["id"])["error"]
    events = [row["event"] for row in queue.logs(job["id"])]
    assert {"enqueued", "started", "retry", "failed"} <= set(events)  # structured log of every step


def test_waiting_jobs_resume_without_using_an_attempt(data):
    from clipfoundry.autopilot import queue

    queue.enqueue("selftest")
    j = queue.claim("maintenance", "w")
    queue.wait(j, "w", "gpu", 0.2, "Waiting for the GPU")
    assert queue.claim("maintenance", "w") is None
    time.sleep(0.25)
    j2 = queue.claim("maintenance", "w")
    assert j2["id"] == j["id"] and j2["attempts"] == 1


def test_recovery_after_a_crash(data):
    from clipfoundry.autopilot import queue

    job = queue.enqueue("selftest", max_attempts=2)
    queue.claim("maintenance", "dead-host", lease_s=0.01)  # the worker dies without finishing
    time.sleep(0.05)
    assert queue.recover()["retrying"] == 1
    assert "Interrupted" in queue.get(job["id"])["message"]
    j = queue.claim("maintenance", "new-host", lease_s=0.01)
    assert j["id"] == job["id"]
    time.sleep(0.05)
    assert queue.recover()["failed"] == 1  # max attempts reached: not retried forever
    assert queue.complete(j, "new-host") is False  # a stale owner cannot overwrite the outcome


def test_the_priority_floor_is_part_of_the_claim(data):
    from clipfoundry.autopilot import queue

    auto = queue.enqueue("selftest")  # older, but only a user-started job may run while Autopilot is off
    assert queue.claim("maintenance", "w", min_priority=100) is None
    manual = queue.enqueue("selftest", priority=100)
    assert queue.claim("maintenance", "w", min_priority=100)["id"] == manual["id"]
    assert queue.claim("maintenance", "w", min_priority=100) is None
    assert queue.claim("maintenance", "w")["id"] == auto["id"]


def test_a_recovered_job_cannot_be_finished_by_its_old_thread(data):
    from clipfoundry.autopilot import host as host_mod, queue

    h = host_mod.WorkerHost(workers=["maintenance"], periodic=False)  # not started: only its tokens are used
    job = queue.enqueue("selftest", max_attempts=3)
    first = h._claim("maintenance", 0)  # noqa: SLF001 - the thread that will hang
    time.sleep(0.01)
    queue.db.execute("UPDATE worker_jobs SET lease_until = 0 WHERE id = ?", (job["id"],))  # its lease ran out
    assert queue.recover()["retrying"] == 1
    second = h._claim("maintenance", 0)  # noqa: SLF001 - the same process claims it again
    assert second["id"] == job["id"] and first["lease_owner"] != second["lease_owner"]
    assert first["lease_owner"].startswith(h.owner) and second["lease_owner"].startswith(h.owner)
    assert queue.complete(first, first["lease_owner"], {"from": "old"}) is False
    assert queue.renew(job["id"], first["lease_owner"]) is None
    assert queue.complete(second, second["lease_owner"], {"from": "new"})
    assert queue.get(job["id"])["result"] == {"from": "new"}


def test_cancel_and_stop_all(data):
    from clipfoundry.autopilot import queue

    a = queue.enqueue("selftest")
    b = queue.enqueue("selftest")
    queue.cancel(a["id"])
    assert queue.get(a["id"])["status"] == "canceled"
    running = queue.claim("maintenance", "w")
    assert running["id"] == b["id"]
    c = queue.enqueue("trend_scan")
    out = queue.cancel_all()
    assert out == {"canceled": 1, "stopping": 1}
    assert queue.get(c["id"])["status"] == "canceled" and queue.get(b["id"])["cancel_requested"] == 1


def test_work_held_by_stop_all_continues_after_resume_but_a_cancel_by_you_stays(data):
    """Stop all jobs is an emergency hold: after Resume jobs, Autopilot queues the same work again when it asks for
    it (a clip's check, a due post). A job you canceled yourself stays canceled."""
    from clipfoundry.autopilot import queue

    running = queue.enqueue("selftest", idem_key="check:running")
    row = queue.claim("maintenance", "w")
    assert row["id"] == running["id"]
    waiting = queue.enqueue("selftest", idem_key="check:waiting")
    mine = queue.enqueue("selftest", idem_key="check:mine")
    queue.cancel(mine["id"])
    queue.cancel_all()
    assert queue.mark_canceled(row, "w")  # the running job reached its next check
    for job in (running, waiting, mine):
        assert queue.get(job["id"])["status"] == "canceled"

    for job in (running, waiting):  # resumed: asked for again, the same job runs again
        again = queue.enqueue("selftest", idem_key=job["idem_key"])
        assert again["id"] == job["id"] and again["status"] == "queued" and again["wait_reason"] == ""
    assert queue.enqueue("selftest", idem_key="check:mine")["status"] == "canceled"
    assert queue.enqueue("selftest", idem_key="check:mine", revive_canceled=True)["status"] == "queued"


# ------------------------------------------------------------------ host
@pytest.fixture()
def host(data):
    from clipfoundry.autopilot import host as host_mod

    h = host_mod.WorkerHost(workers=["maintenance"], poll=0.05, periodic=False)
    assert h.start()
    yield h
    h.stop()


def test_host_runs_retries_and_waits(host):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    db.save_settings({"autopilot_enabled": True})
    ok = queue.enqueue("selftest", {"result": {"x": 1}})
    flaky = queue.enqueue("selftest", {"fail_times": 1, "retry_delay": 0.05}, max_attempts=3)
    waits = queue.enqueue("selftest", {"wait_once": 0.1})
    host.wake()
    for job in (ok, flaky, waits):
        _until(lambda j=job: queue.get(j["id"])["status"] == "completed")
    assert queue.get(ok["id"])["result"]["x"] == 1 and queue.get(flaky["id"])["attempts"] == 2
    # the worker records "completed" right after the job's own status: wait for it instead of racing it
    st = _until(lambda: (lambda r: r if r and r["status"] in ("completed", "idle") else None)(
        db.fetch("worker_state", "maintenance", "name")))
    assert st["pid"] == os.getpid()


def test_running_job_is_canceled_cooperatively(host):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    db.save_settings({"autopilot_enabled": True})
    job = queue.enqueue("selftest", {"sleep": 30})
    host.wake()
    _until(lambda: queue.get(job["id"])["status"] == "running")
    queue.cancel(job["id"])
    host._heartbeat()  # noqa: SLF001 - the supervisor does this every few seconds
    _until(lambda: queue.get(job["id"])["status"] == "canceled", 5)


def test_timeout_stops_a_job(host):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    db.save_settings({"autopilot_enabled": True})
    job = queue.enqueue("selftest", {"sleep": 30}, timeout_s=0.2)
    host.wake()
    _until(lambda: queue.get(job["id"])["status"] == "running")
    time.sleep(0.3)
    queue.expire_timeouts()
    host._heartbeat()  # noqa: SLF001
    _until(lambda: queue.get(job["id"])["status"] == "failed", 5)
    assert "time limit" in queue.get(job["id"])["error"]


def test_autopilot_off_only_runs_manual_jobs_and_stop_all_blocks_everything(host):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, state

    db.save_settings({"autopilot_enabled": False})
    auto = queue.enqueue("selftest")
    manual = queue.enqueue("selftest", priority=100)
    host.wake()
    _until(lambda: queue.get(manual["id"])["status"] == "completed")
    time.sleep(0.2)
    assert queue.get(auto["id"])["status"] == "queued"  # waits for Autopilot to be turned on
    state.put("emergency_stop", True)
    blocked = queue.enqueue("selftest", priority=100)
    host.wake()
    time.sleep(0.3)
    assert queue.get(blocked["id"])["status"] == "queued"
    state.put("emergency_stop", False)
    db.save_settings({"autopilot_enabled": True})
    host.wake()
    _until(lambda: queue.get(auto["id"])["status"] == "completed")


def test_restarted_host_resumes_interrupted_work(data):
    from clipfoundry import db
    from clipfoundry.autopilot import host as host_mod, queue

    db.save_settings({"autopilot_enabled": True})
    job = queue.enqueue("selftest")
    queue.claim("maintenance", "crashed-process", lease_s=0.01)  # the previous run died mid-job
    time.sleep(0.05)
    h = host_mod.WorkerHost(workers=["maintenance"], poll=0.05, periodic=False)
    assert h.start()  # startup recovery puts the job back in the queue
    try:
        _until(lambda: queue.get(job["id"])["status"] == "completed")
        assert queue.get(job["id"])["attempts"] == 2
    finally:
        h.stop()


def test_only_one_host_at_a_time(host):
    from clipfoundry.autopilot import host as host_mod

    second = host_mod.WorkerHost(workers=["maintenance"], poll=0.05, periodic=False)
    assert second.start() is False


def test_a_stopping_host_keeps_exclusivity_until_its_threads_are_done(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host as host_mod, queue

    db.save_settings({"autopilot_enabled": True})
    release = threading.Event()

    def stubborn(job):  # a job between two safe points (e.g. mid-chunk of an upload): cannot stop at once
        release.wait(5)
        return {"message": "finished"}

    h = host_mod.WorkerHost(workers=["maintenance"], poll=0.05, periodic=False)
    monkeypatch.setitem(host_mod.HANDLERS, "selftest", stubborn)
    assert h.start()
    job = queue.enqueue("selftest")
    h.wake()
    _until(lambda: queue.get(job["id"])["status"] == "running")
    h.stop(timeout=0.2)
    second = host_mod.WorkerHost(workers=["maintenance"], poll=0.05, periodic=False)
    assert second.start() is False  # the old thread may still act: no second host yet
    release.set()
    _until(lambda: second.start(), 5)
    second.stop()


def test_periodic_jobs_are_enqueued_once_per_slot(data):
    from clipfoundry import db
    from clipfoundry.autopilot import host as host_mod, queue

    settings = {**db.get_settings(), "autopilot_enabled": False}
    host_mod.WorkerHost(periodic=False)  # registers handlers
    assert host_mod.run_periodic(settings, now=1000.0) == ["maintenance"]  # the only job that runs while off
    assert host_mod.run_periodic(settings, now=1001.0) == []
    assert len(queue.jobs(worker="maintenance")) == 1


# ------------------------------------------------------------------ GPU manager
def test_gpu_lock_serializes_heavy_work(data):
    from clipfoundry import gpu

    order: list[str] = []

    def work(name: str) -> None:
        with gpu.manager.heavy("transcription", name):
            order.append(f"{name}+")
            time.sleep(0.2)
            order.append(f"{name}-")

    threads = [threading.Thread(target=work, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert order in (["a+", "a-", "b+", "b-"], ["b+", "b-", "a+", "a-"])


def test_gpu_lock_is_shared_with_other_processes(data):
    from clipfoundry import gpu

    # The other process holds the GPU until we close its stdin, so a slow first status() call cannot race it.
    code = ("import sys;from clipfoundry import gpu\n"
            "with gpu.manager.heavy('transcription','other process'):\n"
            "    print('held', flush=True); sys.stdin.readline()\n")
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True, env={**os.environ, "CLIPFOUNDRY_DATA": str(data)})
    assert proc.stdout.readline().strip() == "held"
    st = gpu.manager.status({"gpu_min_free_vram_mb": 1200})
    assert st["busy"] and st["holder"]["label"] == "other process"
    waited: list[str] = []
    release = threading.Timer(1.0, proc.stdin.close)
    release.start()
    t0 = time.monotonic()
    with gpu.manager.heavy("transcription", "me", on_wait=waited.append):
        took = time.monotonic() - t0
    release.join()
    proc.wait(10)
    assert took > 0.5 and waited and "other process" in waited[0]
    assert not gpu.manager.status({})["busy"]


def test_gpu_waits_for_free_memory_then_gives_up(data, monkeypatch):
    from clipfoundry import gpu

    monkeypatch.setattr(gpu.manager, "memory", lambda max_age=3.0: {"free_mb": 500, "used_mb": 3500,
                                                                       "total_mb": 4000, "utilization": 90})
    msgs: list[str] = []
    with pytest.raises(gpu.GpuBusy, match="500 MB"):
        with gpu.manager.heavy("transcription", "x", need_free_mb=1200, max_wait_s=0.2, on_wait=msgs.append):
            pass
    assert "Waiting for GPU memory" in msgs[0]
    assert not gpu.manager.status({})["busy"]  # released after giving up


def test_cpu_fallback_is_never_silent(data):
    from clipfoundry import gpu
    from clipfoundry.autopilot import state

    gpu.manager.record_transcription({"requested_device": "cuda", "device": "cpu", "warning": "GPU failed",
                                      "fix": "run gpu-check.bat"}, "talk")
    items = state.open_actions()
    assert items and items[0]["key"] == "gpu:fallback" and "GPU failed" in items[0]["detail"]
    gpu.manager.record_transcription({"requested_device": "cuda", "device": "cuda"}, "talk")
    assert not state.open_actions()


def test_dismissed_questions_stay_dismissed_but_problems_do_not(data):
    from clipfoundry.autopilot import state

    state.action("rights:s1", "rights", "Confirm the rights", snooze_s=3600)
    state.dismiss("rights:s1")
    state.action("rights:s1", "rights", "Confirm the rights", snooze_s=3600)  # the next scout run asks again
    assert not state.open_actions()
    state.action("gpu:fallback", "gpu", "GPU transcription did not run as configured")
    state.dismiss("gpu:fallback")
    state.action("gpu:fallback", "gpu", "GPU transcription did not run as configured")  # happened again
    assert [a["key"] for a in state.open_actions()] == ["gpu:fallback"]
    state.resolve("rights:s2")  # resolving (not dismissing) an item does not snooze it
    state.action("rights:s2", "rights", "Confirm", snooze_s=3600)
    state.resolve("rights:s2")
    state.action("rights:s2", "rights", "Confirm", snooze_s=3600)
    assert {a["key"] for a in state.open_actions()} == {"gpu:fallback", "rights:s2"}


# ------------------------------------------------------------------ manual jobs survive a restart
def test_manual_work_resumes_after_restart(data, monkeypatch):
    from clipfoundry import db, jobs

    p = db.create_project("talk", status="processing", source_path=str(data / "missing.mp4"),
                          source_url="https://example.com/v.mp4")
    done = db.create_project("done", status="ready")
    clip = db.create_clip(done["id"], start=0, end=10, status="rendering")
    auto = db.create_project("auto", status="processing", origin="autopilot")
    pub = db.create_publication(clip["id"], "youtube", status="uploading")
    work = db.interrupted_work()
    assert [x["id"] for x in work["projects"]] == [p["id"]] and work["clips"] == [clip["id"]]
    assert auto["id"] not in [x["id"] for x in work["projects"]]  # resumed by its autopilot job instead
    assert db.get_publication(pub["id"])["status"] == "failed"
    calls: list = []
    w = jobs.Worker()
    monkeypatch.setattr(w, "submit_project", lambda pid, url=None: calls.append(("p", pid, url)))
    monkeypatch.setattr(w, "submit_render", lambda cid: calls.append(("c", cid)))
    w.resume(work)
    assert ("p", p["id"], "https://example.com/v.mp4") in calls and ("c", clip["id"]) in calls
    w.resume(db.interrupted_work())
    w.resume(db.interrupted_work())  # interrupted a third time: stop resuming automatically
    assert db.get_project(p["id"])["status"] == "error"


# ------------------------------------------------------------------ separate worker process
def test_worker_process_runs_jobs_and_exits_with_the_app(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, state

    db.save_settings({"autopilot_enabled": True})
    state.put("app_heartbeat", {"at": time.time()})
    job = queue.enqueue("selftest", {"result": {"from": "worker process"}})
    proc = subprocess.Popen([sys.executable, "-m", "clipfoundry", "workers", "--managed"], cwd=ROOT,
                            env={**os.environ, "CLIPFOUNDRY_DATA": str(data)}, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        _until(lambda: queue.get(job["id"])["status"] == "completed", 60)
        hb = _until(lambda: state.get("host_heartbeat"), 20)
        assert hb["pid"] == proc.pid and hb["managed"]
    finally:
        state.put("app_heartbeat", {"at": 0})  # the app "stops": the worker process notices and exits
        try:
            proc.wait(timeout=90)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
    assert proc.returncode == 0

"""A temporary host/state failure must not leave unexecuted work alive or permit duplicate workers."""
from __future__ import annotations

import threading
import time

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    db.save_settings({"autopilot_enabled": True})


def _until(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


@pytest.mark.parametrize("failure", ["database", "lease_recovery", "render_recovery"])
def test_failed_initialization_can_retry_and_execute_work(data, monkeypatch, failure):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, queue

    worker_host = host.WorkerHost(workers=["maintenance"], periodic=False, poll=0.01)
    queued = queue.enqueue("selftest")
    target, name = {
        "database": (db, "init"),
        "lease_recovery": (queue, "recover"),
        "render_recovery": (gate, "recover_regenerations"),
    }[failure]

    def unavailable():
        raise OSError("temporarily unavailable during startup")

    with monkeypatch.context() as failing:
        failing.setattr(target, name, unavailable)
        with pytest.raises(OSError, match="temporarily unavailable"):
            worker_host.start()
    assert not worker_host.started
    assert worker_host.host_lock._fd is None
    assert not worker_host.running()
    assert not any(thread.is_alive() for thread in worker_host._threads)

    second = host.WorkerHost(workers=["maintenance"], periodic=False, poll=0.01)
    try:
        assert worker_host.start()
        assert not second.start()  # the recovered host still owns one exclusive worker fleet
        _until(lambda: queue.get(queued["id"])["status"] == "completed")
        assert queue.get(queued["id"])["attempts"] == 1
    finally:
        worker_host.stop()
        second.stop()


@pytest.mark.parametrize("failure", ["worker_state", "thread_start"])
def test_partial_start_keeps_exclusivity_until_its_handler_stops(data, monkeypatch, failure):
    from clipfoundry.autopilot import host, queue

    entered, release = threading.Event(), threading.Event()
    calls = []
    worker_host = host.WorkerHost(workers=["maintenance", "packager"], periodic=False, poll=0.01)
    second = host.WorkerHost(workers=["maintenance"], periodic=False, poll=0.01)
    queued = queue.enqueue("selftest")
    set_state = worker_host.set_state
    start_thread = threading.Thread.start

    def between_safe_points(job):
        calls.append(job.id)
        entered.set()
        assert release.wait(5)
        return {"message": "Finished the safe point"}

    def fail_after_first_worker(name, *args, **kwargs):
        if failure == "worker_state" and name == "packager":
            assert entered.wait(5)
            raise OSError("worker initialization temporarily unavailable")
        return set_state(name, *args, **kwargs)

    def fail_second_thread(thread):
        if failure == "thread_start" and thread.name == "cf-worker-packager":
            assert entered.wait(5)
            raise OSError("worker initialization temporarily unavailable")
        return start_thread(thread)

    try:
        with monkeypatch.context() as failing:
            failing.setitem(host.HANDLERS, "selftest", between_safe_points)
            failing.setattr(worker_host, "set_state", fail_after_first_worker)
            failing.setattr(threading.Thread, "start", fail_second_thread)
            with pytest.raises(OSError, match="initialization temporarily unavailable"):
                worker_host.start()
            assert not worker_host.started
            assert worker_host._stop.is_set()
            assert worker_host.running()[queued["id"]].cancelled()
            assert not second.start()
            assert not worker_host.start()
            assert calls == [queued["id"]]
            release.set()
            _until(lambda: worker_host.host_lock._fd is None)
            assert not worker_host.running()

        saved = queue.get(queued["id"])
        assert saved["status"] == "waiting" and saved["wait_reason"] == "restart"
        queue.wake(queued["id"])
        assert worker_host.start()  # the same object clears its old stop flag only after acquiring the lock
        assert not second.start()
        _until(lambda: queue.get(queued["id"])["status"] == "completed")
        assert queue.get(queued["id"])["attempts"] == 1
        assert calls == [queued["id"]]
    finally:
        release.set()
        _until(lambda: not worker_host._stop.is_set() or worker_host.host_lock._fd is None)
        worker_host.stop()
        second.stop()


@pytest.mark.parametrize("persistent", [False, True])
def test_initial_state_failure_never_renews_an_unexecuted_job(data, monkeypatch, persistent):
    from clipfoundry.autopilot import host, queue

    worker_host = host.WorkerHost(workers=["maintenance"], periodic=False)
    queued = queue.enqueue("selftest")
    claimed = queue.claim("maintenance", "first-owner")
    calls = []
    set_state = worker_host.set_state

    def record(job):
        calls.append(job.owner)
        return {"message": "Actually executed"}

    def unavailable(name, status, *args, **kwargs):
        if persistent or status == "working":
            raise OSError("worker state write unavailable")
        return set_state(name, status, *args, **kwargs)

    monkeypatch.setitem(host.HANDLERS, "selftest", record)
    with monkeypatch.context() as failing:
        failing.setattr(worker_host, "set_state", unavailable)
        if persistent:
            with pytest.raises(OSError, match="state write unavailable"):
                worker_host._run("maintenance", claimed)
        else:
            worker_host._run("maintenance", claimed)
    assert not calls
    assert not worker_host.running()
    saved = queue.get(queued["id"])
    assert saved["status"] == "retrying"
    assert saved["lease_owner"] == "" and saved["lease_until"] == 0
    worker_host._heartbeat()
    assert queue.get(queued["id"]) == saved

    queue.wake(queued["id"])
    replacement = queue.claim("maintenance", "replacement-owner")
    worker_host._run("maintenance", replacement)
    assert calls == ["replacement-owner"]
    assert queue.get(queued["id"])["status"] == "completed"
    assert not worker_host.running()


def test_exhausted_thread_creation_still_releases_after_partial_start(data, monkeypatch):
    from clipfoundry.autopilot import host, queue

    entered, release = threading.Event(), threading.Event()
    worker_host = host.WorkerHost(workers=["maintenance", "packager"], periodic=False, poll=0.01)
    queued = queue.enqueue("selftest")
    start_thread = threading.Thread.start

    def between_safe_points(job):
        entered.set()
        assert release.wait(5)
        return {}

    def exhausted(thread):
        if thread.name == "cf-worker-packager":
            assert entered.wait(5)
            raise RuntimeError("cannot start second worker thread")
        if thread.name == "cf-worker-release":
            release.set()  # the existing worker reaches its safe point, without needing another new thread
            raise RuntimeError("cannot start cleanup thread either")
        return start_thread(thread)

    try:
        with monkeypatch.context() as failing:
            failing.setitem(host.HANDLERS, "selftest", between_safe_points)
            failing.setattr(threading.Thread, "start", exhausted)
            with pytest.raises(RuntimeError, match="cannot start second worker thread"):
                worker_host.start()
            assert not worker_host.started
            assert not worker_host.running()
            assert worker_host.host_lock._fd is None
            assert not any(thread.is_alive() for thread in worker_host._threads)
        queue.wake(queued["id"])
        assert worker_host.start()
        _until(lambda: queue.get(queued["id"])["status"] == "completed")
    finally:
        release.set()
        worker_host.stop()

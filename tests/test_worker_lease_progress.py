"""Late progress from a recovered worker must not overwrite its replacement or animate an invented handoff."""
from types import SimpleNamespace
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()


def test_recovered_handler_cannot_report_progress_or_a_handoff(data):
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue
    from clipfoundry.office import feed

    calls = []
    worker_host = SimpleNamespace(set_state=lambda *args, **kwargs: calls.append((args, kwargs)))
    queued = queue.enqueue("package_clip", ref=("clip", "c1"))
    first = queue.claim("packager", "first")
    old_handler = host.Job(first, "first", worker_host)
    old_handler.progress(0.1, "Rendering", "render")
    assert len(calls) == 1

    db.execute("UPDATE worker_jobs SET lease_until = 0 WHERE id = ?", (queued["id"],))
    assert queue.recover()["retrying"] == 1
    second = queue.claim("packager", "replacement")
    replacement = host.Job(second, "replacement", worker_host)
    replacement.progress(0.4, "Writing captions", "captions")
    saved, cursor = queue.get(queued["id"]), feed.cursor()
    calls_before = len(calls)

    old_handler.progress(0.9, "Old render is done", "metadata", force=True)
    assert queue.get(queued["id"]) == saved
    assert feed.cursor() == cursor
    assert len(calls) == calls_before

    assert queue.complete(second, "replacement")
    saved, cursor = queue.get(queued["id"]), feed.cursor()
    replacement.progress(0.5, "Late callback", "captions", force=True)
    assert queue.get(queued["id"]) == saved
    assert feed.cursor() == cursor
    assert len(calls) == calls_before


def test_progress_requires_running_work_and_keeps_manual_event_identity(data):
    from clipfoundry.autopilot import queue
    from clipfoundry.office import feed

    queued = queue.enqueue("selftest", {"manual": True})
    cursor = feed.cursor()
    assert not queue.progress(queued["id"], 0.1, "Not started", "render")
    assert feed.cursor() == cursor
    claimed = queue.claim("maintenance", "owner")
    assert not queue.progress(claimed["id"], 0.2, "Wrong owner", "render", owner="stale")
    assert feed.cursor() == cursor + 1  # only the real claim was emitted
    assert queue.progress(claimed["id"], 0.3, "Real stage", "render", owner="owner")
    event = feed.events_after(cursor)["events"][-1]
    assert event["type"] == "job_stage" and event["data"]["routine"] is False
    assert queue.progress(claimed["id"], 0.4)  # the existing direct helper remains available for running work
    assert queue.get(claimed["id"])["progress"] == 0.4


def test_recovery_lease_decision_cannot_race_a_heartbeat(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    queued = queue.enqueue("selftest")
    claimed = queue.claim("maintenance", "owner")
    db.execute("UPDATE worker_jobs SET lease_until = 0 WHERE id = ?", (queued["id"],))
    selected, release, renewed, attempting = (threading.Event() for _ in range(4))
    connect = db.connect

    class Selection:
        def __init__(self, cursor):
            self.cursor = cursor

        def fetchall(self):
            rows = self.cursor.fetchall()
            selected.set()
            assert release.wait(5)
            return rows

    class Connection:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *args):
            cursor = self.conn.execute(sql, *args)
            return Selection(cursor) if sql.startswith("SELECT id, worker, attempts,") else cursor

    @contextmanager
    def pause_after_selection():
        with connect() as conn:
            yield Connection(conn)

    monkeypatch.setattr(db, "connect", pause_after_selection)

    def heartbeat():
        attempting.set()
        result = queue.renew(claimed["id"], "owner")
        renewed.set()
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        recovery = pool.submit(queue.recover)
        assert selected.wait(5)
        beat = pool.submit(heartbeat)
        try:
            assert attempting.wait(5)
            assert not renewed.wait(0.15)  # the selected lease cannot change before its outcome commits
        finally:
            release.set()
        assert recovery.result(timeout=5) == {"retrying": 1, "failed": 0, "canceled": 0}
        assert beat.result(timeout=5) is None  # recovery won the transaction, so the expired owner is gone
    assert queue.get(queued["id"])["status"] == "retrying"


def test_recovery_preserves_a_lease_renewed_before_its_transaction(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    queued = queue.enqueue("selftest")
    queue.claim("maintenance", "owner")
    db.execute("UPDATE worker_jobs SET lease_until = 0 WHERE id = ?", (queued["id"],))
    assert queue.renew(queued["id"], "owner")
    assert queue.recover() == {"retrying": 0, "failed": 0, "canceled": 0}
    assert queue.get(queued["id"])["status"] == "running"
    assert not any(row["event"] == "recovered" for row in queue.logs(queued["id"]))

"""Durable studio work (full-video builds and renders) with leases and idempotent completion.

A job is one row in studio_jobs, keyed by an idempotency key (kind, target, plan revision): asking twice returns the
same job, and a finished job is not run again. A worker must claim a lease before running and holds it with
heartbeats; only the lease holder can complete the job, so a worker whose lease expired cannot commit a second
result. Jobs run in the app's single heavy-work thread (jobs.worker), so the server does one heavy thing at a time.
After a restart, queued jobs and jobs whose lease expired are picked up again; canceled jobs stay canceled.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

from .. import db

LEASE_S = 90.0
MAX_ATTEMPTS = 3
log = logging.getLogger(__name__)
HANDLERS: dict[str, Callable[[dict, "Lease"], dict]] = {}
STOP_HOOKS: dict[str, Callable[[dict, str], None]] = {}


class Canceled(Exception):
    pass


def handler(kind: str):
    def wrap(fn):
        HANDLERS[kind] = fn
        return fn
    return wrap


def on_stop(kind: str):
    """`fn(job, how)` runs when a job of this kind is canceled or given up (`how` is "canceled" or "failed"), so what
    it was making can say so: its handler may never run again to do that itself."""
    def wrap(fn):
        STOP_HOOKS[kind] = fn
        return fn
    return wrap


def _stopped(job_id: str, how: str) -> None:
    job = db.fetch("studio_jobs", job_id) or {}
    fn = STOP_HOOKS.get(job.get("kind", ""))
    if fn is not None:
        try:
            fn(job, how)
        except Exception:  # noqa: BLE001 - stopping a job never fails because of what it was making
            log.exception("after stopping studio job %s", job_id)


def enqueue(workspace_id: str, kind: str, target_id: str, revision: int = 0, *, submit: bool = True) -> dict:
    key = f"{kind}:{target_id}:{revision}"
    rows = db.select("studio_jobs", "idempotency_key = ?", (key,))
    if rows:
        job = rows[0]
        if job["status"] in ("failed", "canceled"):  # asked again on purpose: run it again
            db.update("studio_jobs", job["id"], status="queued", error="", progress=0, message="Waiting",
                      lease_token="", lease_until=0, attempts=0)
            job = db.fetch("studio_jobs", job["id"])
        elif job["status"] != "queued":
            return job  # running or done: never a second copy of the same work
    else:
        job = db.insert("studio_jobs", {"id": "job-" + os.urandom(6).hex(), "workspace_id": workspace_id,
                                        "kind": kind, "target_id": target_id, "revision": revision,
                                        "idempotency_key": key, "message": "Waiting for a worker"})
    if submit:
        from ..jobs import worker

        worker.submit_studio(job["id"])
    return job  # type: ignore[return-value]


class Lease:
    def __init__(self, job_id: str, token: str):
        self.job_id, self.token = job_id, token
        self._last = 0.0

    def alive(self) -> bool:
        row = db.fetch("studio_jobs", self.job_id) or {}
        return row.get("lease_token") == self.token and row.get("status") == "running"

    def canceled(self) -> bool:
        row = db.fetch("studio_jobs", self.job_id) or {}
        return row.get("status") == "canceled" or row.get("lease_token") != self.token

    def progress(self, frac: float, message: str = "") -> None:
        """Measured progress only; every report also renews the lease."""
        now = time.time()
        if now - self._last < 0.5 and frac < 1.0:
            return
        self._last = now
        changed = db.execute("UPDATE studio_jobs SET progress = ?, message = ?, lease_until = ?, updated_at = ? "
                             "WHERE id = ? AND lease_token = ? AND status = 'running'",
                             (round(min(max(frac, 0.0), 1.0), 4), message[:200], now + LEASE_S, now,
                              self.job_id, self.token))
        if not changed:
            raise Canceled()


def claim(job_id: str, now: float | None = None) -> Lease | None:
    now = now or time.time()
    token = os.urandom(8).hex()
    changed = db.execute("UPDATE studio_jobs SET status = 'running', lease_token = ?, lease_until = ?, "
                         "attempts = attempts + 1, updated_at = ? WHERE id = ? AND attempts < ? AND "
                         "(status = 'queued' OR (status = 'running' AND lease_until < ?))",
                         (token, now + LEASE_S, now, job_id, MAX_ATTEMPTS, now))
    return Lease(job_id, token) if changed else None


def finish(lease: Lease, result: dict) -> bool:
    """Commit the result if this worker still holds the lease (exactly one completion per job)."""
    return bool(db.execute("UPDATE studio_jobs SET status = 'done', progress = 1, message = 'Done', result = ?, "
                           "lease_token = '', updated_at = ? WHERE id = ? AND lease_token = ? AND status = 'running'",
                           (db._encode("studio_jobs", {"result": result})["result"], time.time(),  # noqa: SLF001
                            lease.job_id, lease.token)))


def fail(lease: Lease, error: str) -> None:
    db.execute("UPDATE studio_jobs SET status = 'failed', error = ?, message = 'Failed', lease_token = '', "
               "updated_at = ? WHERE id = ? AND lease_token = ?", (error[:1000], time.time(), lease.job_id,
                                                                    lease.token))


def cancel(job_id: str) -> bool:
    done = bool(db.execute("UPDATE studio_jobs SET status = 'canceled', message = 'Canceled', updated_at = ? "
                           "WHERE id = ? AND status IN ('queued', 'running')", (time.time(), job_id)))
    if done:
        _stopped(job_id, "canceled")
    return done


def run(job_id: str) -> None:
    """Run one job in the heavy-work thread."""
    lease = claim(job_id)
    if lease is None:
        row = db.fetch("studio_jobs", job_id) or {}
        if row.get("status") == "running" and row.get("lease_until", 0) > time.time():
            # another worker holds it (or a previous process did); look again when that lease runs out
            wait = row["lease_until"] - time.time() + 1
            threading.Timer(wait, lambda: _resubmit(job_id)).start()
        elif row.get("status") in ("queued", "running") and row.get("attempts", 0) >= MAX_ATTEMPTS:
            # interrupted too often (queued, or running with a lease nobody renews any more): give up, and say so
            now = time.time()
            if db.execute("UPDATE studio_jobs SET status = 'failed', message = 'Failed', error = ?, lease_token = '', "
                          "updated_at = ? WHERE id = ? AND attempts >= ? AND (status = 'queued' OR "
                          "(status = 'running' AND lease_until < ?))",
                          ("Stopped after repeated interruptions. Press Retry to try once more.", now, job_id,
                           MAX_ATTEMPTS, now)):
                _stopped(job_id, "failed")
        return
    job = db.fetch("studio_jobs", job_id) or {}
    fn = HANDLERS.get(job.get("kind", ""))
    if fn is None:
        fail(lease, f"Unknown job kind {job.get('kind')}")
        return
    from ..pipeline.common import Cancelled as MediaCancelled

    try:
        result = fn(job, lease)
    except (Canceled, MediaCancelled):  # the owner canceled: stop quietly, keep the job canceled
        db.execute("UPDATE studio_jobs SET lease_token = '' WHERE id = ? AND lease_token = ?", (job_id, lease.token))
        return
    except Exception as exc:  # noqa: BLE001 - the reason is shown to the owner
        log.exception("studio job %s failed", job_id)
        fail(lease, str(exc))
        return
    if not finish(lease, result or {}):
        log.warning("studio job %s finished after losing its lease; its result was not committed", job_id)


def _resubmit(job_id: str) -> None:
    from ..jobs import worker

    worker.submit_studio(job_id)


def recover() -> int:
    """After a restart: queue every unfinished job again (canceled and finished jobs stay as they are)."""
    n = 0
    for row in db.select("studio_jobs", "status IN ('queued', 'running')"):
        _resubmit(row["id"])
        n += 1
    return n

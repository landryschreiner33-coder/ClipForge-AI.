"""Every job handler, registered with the worker host by importing this module."""
from __future__ import annotations

import time

from .. import db
from . import queue, state
from .host import Job, handler

KEEP_JOB_DAYS = 30
KEEP_EVENT_DAYS = 90


@handler("maintenance")
def maintenance(job: Job) -> dict:
    """Recover abandoned jobs, trim old logs, and enforce data-retention rules."""
    now = time.time()
    recovered = queue.recover(now)
    cutoff = now - KEEP_JOB_DAYS * 86400
    removed_jobs = db.execute("DELETE FROM worker_jobs WHERE status IN ('completed', 'canceled') AND "
                              "COALESCE(finished_at, updated_at) < ?", (cutoff,))
    db.execute("DELETE FROM job_logs WHERE at < ?", (cutoff,))
    db.execute("DELETE FROM autopilot_events WHERE at < ?", (now - KEEP_EVENT_DAYS * 86400,))
    db.execute("DELETE FROM action_items WHERE resolved_at IS NOT NULL AND resolved_at < ?", (cutoff,))
    db.execute("DELETE FROM api_cache WHERE expires_at < ?", (now,))
    result = {"recovered": recovered, "removed_jobs": removed_jobs}
    for step in MAINTENANCE_STEPS:
        job.check()
        result.update(step(job) or {})
    return {**result, "message": "Maintenance done"}


MAINTENANCE_STEPS: list = []  # later modules add retention steps (e.g. the 30-day YouTube data rule)


@handler("selftest")
def selftest(job: Job) -> dict:
    """A job that exercises the queue (used by the tests and the "Check workers" button)."""
    p = job.payload
    if p.get("wait_once") and not state.get(f"selftest:{job.id}"):
        state.put(f"selftest:{job.id}", True)
        job.wait("test", float(p["wait_once"]), "Waiting (self-test)")
    if p.get("fail_times", 0) >= job.row["attempts"]:
        raise queue.Retry("Self-test failure", delay=float(p.get("retry_delay", 0.1)))
    if p.get("permanent"):
        raise queue.Fail("Self-test permanent failure", "Nothing to do")
    end = time.monotonic() + float(p.get("sleep", 0))
    while time.monotonic() < end:
        job.check()
        job.progress(1 - (end - time.monotonic()) / max(0.001, float(p.get("sleep", 1))), "Self-test running")
        time.sleep(0.05)
    return {"ok": True, "message": "Self-test passed", **(p.get("result") or {})}


# Worker modules register their handlers (and maintenance steps) on import.
from . import hunter, scout  # noqa: E402,F401

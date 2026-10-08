"""Durable job queue on SQLite.

Every job is a row in `worker_jobs`; nothing important lives only in memory, so a crash or restart loses no work:

* queued -> running -> completed | failed | canceled
* running -> retrying (transient error, with backoff) -> running ...
* running -> waiting (for the GPU, quota, a scheduled time or the user) -> running ...

A worker claims a job atomically and holds a lease that it renews while it works. A job whose lease runs out (the
process died or hung) is recovered: retried while attempts remain, failed otherwise. Idempotency keys make
enqueueing the same work twice a no-op. Cancellation is cooperative: running jobs see the request at their next
check. Every step is written to `job_logs` as a structured log line.
"""
from __future__ import annotations

import json
import os
import random
import socket
import sqlite3
import time
from typing import Any

from .. import db
from ..office import feed
from ..pipeline.common import Cancelled, log

ACTIVE = ("queued", "running", "waiting", "retrying")
TERMINAL = ("completed", "failed", "canceled")
LEASE_SECONDS = 90.0
STOP_ALL = "stop_all"  # wait_reason of a job canceled by Stop all jobs: a hold, so asking again after Resume revives it

# worker name -> (label, job kinds it runs)
WORKERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "trend_scout": ("Trend Scout", ("trend_scan",)),
    "source_scout": ("Source Scout", ("source_scout", "feed_scan", "identify_link")),
    "rights_gate": ("Rights Gate", ("rights_check",)),
    "live_monitor": ("Live Monitor", ("live_watch", "live_capture", "post_live")),
    "clip_hunter": ("Clip Hunter", ("hunt_source",)),
    "analyzer": ("Deep Clip Analyzer", ("analyze_source", "regenerate_clip")),
    "packager": ("Packaging AI", ("package_clip",)),
    "quality_gate": ("Final Quality Gate", ("quality_check",)),
    "scheduler": ("Smart Scheduler", ("schedule_tick",)),
    "publisher": ("Publisher", ("publish",)),
    "learner": ("Learning Worker", ("learn",)),
    "maintenance": ("Maintenance", ("maintenance", "selftest")),
}
KIND_WORKER = {kind: name for name, (_, kinds) in WORKERS.items() for kind in kinds}


def source_priority(source: dict | str, base: int = 0) -> int:
    """Keep a user's latest move-to-top order across stage handoffs, including already running jobs."""
    row = db.fetch("sources", source if isinstance(source, str) else source["id"]) or {}
    if row.get("user_added") and base < 100:
        return max(10, int((row.get("intake") or {}).get("priority") or 80))
    return max(10, base)


def has_higher_priority_work(current: dict, priority: int, now: float | None = None) -> bool:
    """Yield only to actionable heavy work. A future stream, a sign-in wait, and a recorder listening for moments
    must not hold ordinary rendering indefinitely. The current encode/transcription always finishes first."""
    now = _now() if now is None else now
    kinds = ("hunt_source", "analyze_source", "regenerate_clip", "post_live")
    marks = ",".join("?" * len(kinds))
    for row in db.select("worker_jobs", f"id != ? AND kind IN ({marks}) AND cancel_requested = 0 AND "
                         "(status = 'running' OR (status IN ('queued', 'retrying') AND run_after <= ?))",
                         (current["id"], *kinds, now)):
        source_id = (row.get("payload") or {}).get("source_id")
        if not source_id and row.get("ref_type") == "source":
            source_id = row.get("ref_id")
        if not source_id and row.get("ref_type") == "clip":
            clip = db.get_clip(row.get("ref_id") or "") or {}
            source_id = (db.get_project(clip.get("project_id") or "") or {}).get("source_id")
        effective = source_priority(source_id, row["priority"]) if source_id else row["priority"]
        if effective > priority:
            return True
    if priority >= 100:
        return False
    # Manual work uses the original app worker, not worker_jobs. Its durable visible state crosses processes.
    project_id = (current.get("payload") or {}).get("project_id") or ""
    if any((clip.get("render_info") or {}).get("manual_render_pending")
           for clip in db.select("clips", "status IN ('queued', 'rendering')")):
        return True
    return bool(db.scalar("SELECT COUNT(*) FROM clip_versions WHERE status IN ('queued', 'rendering')") or
                db.scalar("SELECT COUNT(*) FROM projects WHERE origin = 'manual' AND id != ? "
                          "AND status IN ('queued', 'processing')", (project_id,)) or
                db.scalar("SELECT COUNT(*) FROM clips c JOIN projects p ON p.id = c.project_id "
                          "WHERE p.origin = 'manual' AND c.status IN ('queued', 'rendering')"))


class JobError(Exception):
    """A job failure with a plain-language message and, when possible, what to do about it."""

    def __init__(self, message: str, fix: str = "", delay: float | None = None):
        super().__init__(message)
        self.fix = fix
        self.delay = delay


class Retry(JobError):
    """Transient problem (network, rate limit, busy resource): try again later."""


class Fail(JobError):
    """Permanent problem: retrying would not help."""


class Wait(Exception):
    """Not an error: the job must wait (for a time, the GPU, quota or the user) and continue later."""

    def __init__(self, reason: str, seconds: float, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason
        self.seconds = max(1.0, seconds)
        self.message = message or reason


Canceled = Cancelled  # one cancellation exception for the pipeline and the queue


def host_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _now() -> float:
    return time.time()


# ------------------------------------------------------------------ enqueue
def enqueue(kind: str, payload: dict | None = None, *, priority: int = 0, idem_key: str | None = None,
            delay: float = 0.0, max_attempts: int = 3, timeout_s: float = 3600.0, ref: tuple[str, str] = ("", ""),
            parent_id: str = "", message: str = "Waiting in queue", revive: bool = True,
            revive_canceled: bool = False) -> dict:
    """Add a job. With an idempotency key, an existing job with that key is returned instead of adding another
    (a failed one is queued again when `revive` is set). Cancellation is durable: only an explicit user retry
    (`revive_canceled`) may reset a canceled row. Stop all jobs is a hold, not a cancel of each item: after Resume
    jobs, work it canceled is queued again when Autopilot asks for it."""
    worker = KIND_WORKER[kind]
    now = _now()
    if idem_key:
        existing = db.fetch("worker_jobs", idem_key, "idem_key")
        if existing:
            canceled = existing["status"] == "canceled" and (revive_canceled or existing["wait_reason"] == STOP_ALL)
            if revive and (existing["status"] == "failed" or canceled):
                db.update("worker_jobs", existing["id"], status="queued", attempts=0, run_after=now + delay, error="",
                          fix="", cancel_requested=0, message="Queued again", payload=payload or existing["payload"],
                          finished_at=None, wait_reason="")
                log_line(existing["id"], worker, "info", "requeued", "Queued again")
                return db.fetch("worker_jobs", existing["id"]) or existing
            return existing
    row = {"id": db.new_id(), "kind": kind, "worker": worker, "status": "queued", "priority": priority,
           "payload": payload or {}, "idem_key": idem_key, "max_attempts": max_attempts, "run_after": now + delay,
           "timeout_s": timeout_s, "ref_type": ref[0], "ref_id": ref[1], "parent_id": parent_id, "message": message}
    try:
        job = db.insert("worker_jobs", row)
    except sqlite3.IntegrityError:  # another process enqueued the same idempotency key a moment ago
        return db.fetch("worker_jobs", idem_key, "idem_key") or row
    log_line(job["id"], worker, "info", "enqueued", f"{kind} queued", ref_type=ref[0], ref_id=ref[1])
    return job


# ------------------------------------------------------------------ claim / lease
def claim(worker: str, owner: str, lease_s: float = LEASE_SECONDS, now: float | None = None,
          min_priority: int | None = None, *, manual_priority: int | None = None) -> dict | None:
    """Atomically take the next due job for `worker` (highest priority, then oldest). `min_priority` (e.g. only
    jobs a user started while Autopilot is off) is part of the same transaction, so no other claim can slip in
    between the check and the take. `owner` becomes the job's lease token: only it can renew or finish the job."""
    now = now or _now()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        floor = -(2 ** 62) if min_priority is None else min_priority
        if manual_priority is not None:
            # A Pause/Stop may have committed after the host's preliminary gate read. Re-read controls inside
            # the claim transaction so newly queued work cannot slip through that stale observation.
            stopped = conn.execute("SELECT value FROM autopilot_state WHERE key = 'emergency_stop'").fetchone()
            if stopped and json.loads(stopped["value"]):
                conn.execute("COMMIT")
                return None
            enabled = conn.execute("SELECT value FROM settings WHERE key = 'autopilot_enabled'").fetchone()
            if not enabled or not json.loads(enabled["value"]):
                floor = max(floor, manual_priority)
        row = conn.execute(
            "SELECT id, status FROM worker_jobs WHERE worker = ? AND status IN ('queued', 'retrying', 'waiting') "
            "AND run_after <= ? AND cancel_requested = 0 AND priority >= ? "
            "ORDER BY priority DESC, run_after ASC, created_at ASC LIMIT 1",
            (worker, now, floor)).fetchone()
        if not row:
            conn.execute("COMMIT")
            return None
        bump = 0 if row["status"] == "waiting" else 1  # resuming after a wait is not a new attempt
        # the time limit counts from this run: a job that waited hours (a platform's Retry-After, the quota, the
        # GPU) or was revived gets its full time again instead of being stopped as soon as it resumes
        conn.execute("UPDATE worker_jobs SET status = 'running', lease_owner = ?, lease_until = ?, "
                     "attempts = attempts + ?, started_at = ?, wait_reason = '', updated_at = ? "
                     "WHERE id = ?", (owner, now + lease_s, bump, now, now, row["id"]))
        conn.execute("COMMIT")
    job = db.fetch("worker_jobs", row["id"])
    if job:
        log_line(job["id"], worker, "info", "started", f"attempt {job['attempts']} of {job['max_attempts']}",
                 owner=owner)
        feed.job_event(job, "job_started", job.get("message") or "", attempt=job["attempts"])
    return job


def renew(job_id: str, owner: str, lease_s: float = LEASE_SECONDS) -> dict | None:
    """Extend the lease. Returns the job's flags, or None if this worker no longer owns it."""
    now = _now()
    with db.connect() as conn:
        n = conn.execute("UPDATE worker_jobs SET lease_until = ? WHERE id = ? AND lease_owner = ? AND "
                         "status = 'running'", (now + lease_s, job_id, owner)).rowcount
        if not n:
            return None
        row = conn.execute("SELECT cancel_requested, started_at, timeout_s FROM worker_jobs WHERE id = ?",
                           (job_id,)).fetchone()
    return dict(row) if row else None


def _finish(job: dict, owner: str, **fields: Any) -> bool:
    """Write the outcome only if this worker still owns the job (a recovered job may belong to another)."""
    now = _now()
    fields = {**fields, "lease_owner": "", "lease_until": 0, "updated_at": now}
    for k in ("payload", "result"):
        if k in fields:
            fields[k] = json.dumps(fields[k], default=str)
    cols = ", ".join(f"{k} = ?" for k in fields)
    with db.connect() as conn:
        n = conn.execute(f"UPDATE worker_jobs SET {cols} WHERE id = ? AND lease_owner = ? AND status = 'running'",
                         [*fields.values(), job["id"], owner]).rowcount
    return bool(n)


def complete(job: dict, owner: str, result: dict | None = None, message: str = "Done") -> bool:
    ok = _finish(job, owner, status="completed", result=result or {}, progress=1.0, message=message, error="",
                 fix="", finished_at=_now())
    if ok:
        log_line(job["id"], job["worker"], "info", "completed", message)
        latest = db.fetch("worker_jobs", job["id"]) or job
        feed.job_event(latest, "job_done", message)
        feed.report(latest, "done", result or {})
    return ok


def backoff(attempts: int, base: float = 30.0, cap: float = 3600.0) -> float:
    return min(cap, base * 2 ** max(0, attempts - 1)) * random.uniform(0.85, 1.15)


def retry_or_fail(job: dict, owner: str, error: str, fix: str = "", delay: float | None = None) -> str:
    """A transient failure: retry with backoff while attempts remain. Returns the new status."""
    if job["attempts"] >= job["max_attempts"]:
        fail(job, owner, f"{error} (gave up after {job['attempts']} attempts)", fix)
        return "failed"
    wait_s = backoff(job["attempts"]) if delay is None else delay
    if _finish(job, owner, status="retrying", error=error[:2000], fix=fix, run_after=_now() + wait_s,
               message=f"Retrying in {int(wait_s // 60)} min {int(wait_s % 60)} s"):
        log_line(job["id"], job["worker"], "warning", "retry", error, fix=fix, delay=round(wait_s, 1))
        feed.job_event(db.fetch("worker_jobs", job["id"]) or job, "job_retry", error[:300], delay=round(wait_s, 1))
    return "retrying"


def fail(job: dict, owner: str, error: str, fix: str = "") -> bool:
    ok = _finish(job, owner, status="failed", error=error[:2000], fix=fix, message="Failed", finished_at=_now())
    if ok:
        log_line(job["id"], job["worker"], "error", "failed", error, fix=fix)
        latest = db.fetch("worker_jobs", job["id"]) or job
        feed.job_event(latest, "job_failed", error[:300], fix=fix[:300])
        feed.report(latest, "failed", {}, error=error, fix=fix)
    return ok


def wait(job: dict, owner: str, reason: str, seconds: float, message: str = "") -> bool:
    ok = _finish(job, owner, status="waiting", wait_reason=reason, run_after=_now() + seconds,
                 message=message or reason)
    if ok:
        log_line(job["id"], job["worker"], "info", "waiting", message or reason, reason=reason,
                 seconds=round(seconds, 1))
        feed.job_event(db.fetch("worker_jobs", job["id"]) or job, "job_waiting", (message or reason)[:300],
                       reason=reason, seconds=round(seconds, 1))
    return ok


def mark_canceled(job: dict, owner: str, message: str = "Canceled") -> bool:
    ok = _finish(job, owner, status="canceled", message=message, finished_at=_now())
    if ok:
        log_line(job["id"], job["worker"], "info", "canceled", message)
        feed.job_event(job, "job_canceled", message)
    return ok


def progress(job_id: str, fraction: float | None = None, message: str | None = None, stage: str | None = None) -> None:
    fields: dict[str, Any] = {}
    if fraction is not None:
        fields["progress"] = round(max(0.0, min(1.0, fraction)), 4)
    if message is not None:
        fields["message"] = message[:500]
    if stage is not None:
        fields["stage"] = stage
    if fields:
        before = db.fetch("worker_jobs", job_id) if stage is not None else None
        db.update("worker_jobs", job_id, **fields)
        if before and before.get("stage") != stage:  # a new stage can mean another role takes over
            feed.job_event({**before, **fields}, "job_stage", message or "", stage=stage)


# ------------------------------------------------------------------ control
def cancel(job_id: str, message: str = "Canceled by you") -> dict | None:
    """Cancel a job: at once if it is not running, at its next check if it is."""
    now = _now()
    with db.connect() as conn:
        conn.execute("UPDATE worker_jobs SET status = 'canceled', message = ?, finished_at = ?, updated_at = ?, "
                     "wait_reason = '' WHERE id = ? AND status IN ('queued', 'retrying', 'waiting')",
                     (message, now, now, job_id))
        conn.execute("UPDATE worker_jobs SET cancel_requested = 1, message = 'Stopping...', updated_at = ?, "
                     "wait_reason = '' WHERE id = ? AND status = 'running'", (now, job_id))
    log_line(job_id, "", "info", "cancel_requested", message)
    return db.fetch("worker_jobs", job_id)


def cancel_all(message: str = "Stopped with Stop all jobs", workers: tuple[str, ...] | None = None) -> dict:
    now = _now()
    scope, args = "", []
    if workers:
        scope = f" AND worker IN ({', '.join('?' for _ in workers)})"
        args = list(workers)
    with db.connect() as conn:
        pending = conn.execute("UPDATE worker_jobs SET status = 'canceled', message = ?, finished_at = ?, "
                               "updated_at = ?, wait_reason = ? WHERE status IN ('queued', 'retrying', 'waiting')"
                               + scope, [message, now, now, STOP_ALL, *args]).rowcount
        # The marker survives the running job's own cancel (mark_canceled keeps wait_reason)
        running = conn.execute("UPDATE worker_jobs SET cancel_requested = 1, message = 'Stopping...', updated_at = ?, "
                               "wait_reason = ? WHERE status = 'running'" + scope, [now, STOP_ALL, *args]).rowcount
    log_line("", "", "warning", "cancel_all", message, pending=pending, running=running)
    return {"canceled": pending, "stopping": running}


def wake(job_id: str) -> None:
    """Let a waiting job run now (its condition changed, e.g. the user approved something)."""
    db.execute("UPDATE worker_jobs SET run_after = ? WHERE id = ? AND status IN ('waiting', 'retrying', 'queued')",
               (_now(), job_id))


def recover(now: float | None = None) -> dict:
    """Jobs whose worker vanished (crash, restart, hang past the lease): retry them, or fail after max attempts."""
    now = now or _now()
    counts = {"retrying": 0, "failed": 0, "canceled": 0}
    with db.connect() as conn:
        rows = conn.execute("SELECT id, worker, attempts, max_attempts, cancel_requested FROM worker_jobs "
                            "WHERE status = 'running' AND lease_until < ?", (now,)).fetchall()
        for r in rows:
            if r["cancel_requested"]:
                status, msg = "canceled", "Canceled"
            elif r["attempts"] < r["max_attempts"]:
                status, msg = "retrying", "Interrupted (the app or worker stopped); resuming"
            else:
                status, msg = "failed", f"Interrupted {r['attempts']} times; not retrying"
            conn.execute("UPDATE worker_jobs SET status = ?, lease_owner = '', lease_until = 0, run_after = ?, "
                         "message = ?, error = CASE WHEN ? = 'failed' THEN ? ELSE error END, updated_at = ?, "
                         "finished_at = CASE WHEN ? IN ('failed', 'canceled') THEN ? ELSE finished_at END "
                         "WHERE id = ? AND status = 'running'",
                         (status, now, msg, status, msg, now, status, now, r["id"]))
            counts[status] += 1
    for r in rows:
        log_line(r["id"], r["worker"], "warning", "recovered", "lease expired; job recovered")
    return counts


def expire_timeouts(now: float | None = None) -> int:
    """Ask running jobs that exceeded their time limit to stop."""
    now = now or _now()
    return db.execute("UPDATE worker_jobs SET cancel_requested = 2, message = 'Time limit reached; stopping', "
                      "updated_at = ? WHERE status = 'running' AND cancel_requested = 0 AND started_at IS NOT NULL "
                      "AND started_at + timeout_s < ?", (now, now))


# ------------------------------------------------------------------ queries
def get(job_id: str) -> dict | None:
    return db.fetch("worker_jobs", job_id)


def jobs(status: tuple[str, ...] | None = None, worker: str = "", limit: int = 100, ref: tuple[str, str] | None = None
         ) -> list[dict]:
    where, args = [], []
    if status:
        where.append(f"status IN ({', '.join('?' for _ in status)})")
        args += list(status)
    if worker:
        where.append("worker = ?")
        args.append(worker)
    if ref:
        where += ["ref_type = ?", "ref_id = ?"]
        args += list(ref)
    return db.select("worker_jobs", " AND ".join(where), args, "created_at DESC", limit)


def counts() -> dict[str, dict[str, int]]:
    with db.connect() as conn:
        rows = conn.execute("SELECT worker, status, COUNT(*) AS n FROM worker_jobs GROUP BY worker, status").fetchall()
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["worker"], {})[r["status"]] = r["n"]
    return out


# ------------------------------------------------------------------ structured logs
def log_line(job_id: str, worker: str, level: str, event: str, message: str = "", **data: Any) -> None:
    getattr(log, "warning" if level in ("warning", "error") else "debug")("[job %s] %s %s %s", job_id, worker, event,
                                                                          message)
    try:
        db.execute("INSERT INTO job_logs (job_id, worker, at, level, event, message, data) VALUES (?,?,?,?,?,?,?)",
                   (job_id, worker, _now(), level, event, str(message)[:2000], json.dumps(data, default=str)))
    except sqlite3.Error as exc:  # logging must never break a job
        log.warning("could not write job log: %s", exc)


def logs(job_id: str = "", limit: int = 200) -> list[dict]:
    if job_id:
        return db.select("job_logs", "job_id = ?", (job_id,), "id DESC", limit)
    return db.select("job_logs", "", (), "id DESC", limit)

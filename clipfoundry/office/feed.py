"""The office feed: real transitions of the job system as small events, plus the managers' reports and the
Director's decisions.

Every event has a unique increasing id (the client's resume cursor), the job and role it belongs to, a type, a time
and a small payload. A client loads `snapshot()` (the current state plus the cursor), then asks for `events_after()`
that cursor; after a reconnect it does the same again, so missed events are never needed to be correct. Nothing here
starts, approves or finishes work: the robots only show what the job system already did.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from .. import db
from ..pipeline.common import log
from . import roles

KEEP_EVENTS = 20_000          # newest events kept (older ones are only history)
KEEP_DAYS = 14
RULES = "rules-v1"             # version of the deterministic checkpoint rules (recorded with each decision)
# jobs that run every minute or so: their routine runs are not shown as walks, only their real results
ROUTINE = {"schedule_tick", "feed_scan", "live_watch", "maintenance", "selftest"}


def emit(type_: str, role: str = "", *, job_id: str = "", kind: str = "", ref: tuple[str, str] = ("", ""),
         message: str = "", **data: Any) -> int:
    """Append one event; never raises (the feed must not break the work it describes)."""
    try:
        with db.connect() as conn:
            cur = conn.execute("INSERT INTO office_events (at, type, role, job_id, kind, ref_type, ref_id, message, "
                               "data) VALUES (?,?,?,?,?,?,?,?,?)",
                               (time.time(), type_, role, job_id, kind, ref[0] or "", ref[1] or "",
                                str(message)[:300], json.dumps(data, default=str)[:4000]))
            return int(cur.lastrowid or 0)
    except Exception as exc:  # noqa: BLE001 - a database or encoding problem here must not stop the job
        log.warning("office event not written: %s", exc)
        return 0


def _ref(job: dict) -> tuple[str, str]:
    return job.get("ref_type") or "", job.get("ref_id") or ""


def job_event(job: dict, type_: str, message: str = "", stage: str = "", **data: Any) -> None:
    """A transition of a durable job (called by autopilot/queue.py)."""
    kind = job.get("kind") or ""
    role = roles.role_for(kind, stage or job.get("stage") or "")
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    emit(type_, role, job_id=job.get("id") or "", kind=kind, ref=_ref(job), message=message,
         stage=stage or job.get("stage") or "",
         routine=kind in ROUTINE and not payload.get("manual"), worker=job.get("worker") or "", **data)


# ------------------------------------------------------------------ manager reports
def _recommend(state: str, result: dict, error: str) -> str:
    if state == "failed":
        return "needs_owner" if result.get("fix") else "stop"
    if state == "waiting":
        return "retry_later"
    if state == "retrying":
        return "retry_later"
    if result.get("skipped"):
        return "stop"
    return "continue"


def report(job: dict, state: str, result: dict | None = None, error: str = "", fix: str = "") -> dict | None:
    """The department manager's automatic review of a finished job: what was done, warnings, a recommendation.
    Routine periodic runs that did nothing are not reported (their result is already in the job list). Never raises:
    a report that cannot be written must not fail the job it describes."""
    try:
        return _report(job, state, result if isinstance(result, dict) else {}, error, fix)
    except Exception as exc:  # noqa: BLE001
        log.warning("office report not written for %s: %s", job.get("id"), exc)
        return None


def _report(job: dict, state: str, result: dict, error: str, fix: str) -> dict | None:
    kind = job.get("kind") or ""
    if kind in ROUTINE and state == "done" and not _meaningful(result):
        return None
    worker = roles.role_for(kind, job.get("stage") or "")
    dept = roles.department_of(worker)
    manager = roles.DEPARTMENTS.get(dept, {}).get("manager") or "command"
    started = float(job.get("started_at") or 0)
    found = result.get("warnings")  # a list of notes; some handlers report only a count
    warnings = [str(w)[:200] for w in found][:5] if isinstance(found, (list, tuple)) else []
    if error:
        warnings.insert(0, error[:300])
    row = {"job_id": job.get("id") or "", "kind": kind, "department": dept, "manager": manager, "worker": worker,
           "ref_type": job.get("ref_type") or "", "ref_id": job.get("ref_id") or "", "state": state,
           "summary": str(result.get("message") or error or state)[:300], "warnings": warnings,
           "recommendation": _recommend(state, {**result, "fix": fix}, error),
           "confidence": result.get("confidence") if isinstance(result.get("confidence"), (int, float)) else None,
           "resources": {"elapsed_s": round(time.time() - started, 1) if started else None,
                         "attempts": job.get("attempts"), "worker": job.get("worker")}}
    try:
        saved = db.insert("office_reports", row, replace=True)
    except sqlite3.Error as exc:
        log.warning("office report not written: %s", exc)
        return None
    emit("report", manager, job_id=row["job_id"], kind=kind, ref=(row["ref_type"], row["ref_id"]),
         message=row["summary"], worker=worker, state=state, recommendation=row["recommendation"],
         report_id=saved.get("id"))
    return saved


def _meaningful(result: dict) -> bool:
    for k, v in result.items():
        if k in ("message", "periodic", "skipped"):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            return True
        if isinstance(v, (list, dict)) and v:
            return True
    return False


# ------------------------------------------------------------------ the Director's decisions
POINTS = ("source", "clip", "qc", "upload")
ACTIONS = ("approved", "rework", "rejected", "held")


def decide(point: str, action: str, subject: tuple[str, str], reason: str, *, job_id: str = "",
           reported_by: str = "", once: bool = False, **evidence: Any) -> dict | None:
    """Record a checkpoint decision made by the deterministic rules (the Director's stamp). The decision is the
    record of what the code decided; it is never created by the office view. With `once`, a repeat of the same
    decision for the same subject (a job resumed after a wait) is not recorded again."""
    assert point in POINTS and action in ACTIONS, (point, action)
    if once:
        last = db.select("office_decisions", "point = ? AND subject_type = ? AND subject_id = ?",
                         (point, subject[0], subject[1]), "created_at DESC", 1)
        if last and last[0]["action"] == action:
            return last[0]
    row = {"point": point, "action": action, "subject_type": subject[0], "subject_id": subject[1], "job_id": job_id,
           "decided_by": "command", "reported_by": reported_by, "reason": reason[:500], "evidence": evidence,
           "rule_version": RULES}
    try:
        saved = db.insert("office_decisions", row)
    except sqlite3.Error as exc:
        log.warning("office decision not written: %s", exc)
        return None
    emit("decision", "command", job_id=job_id, ref=subject, message=reason[:300], point=point, action=action,
         reported_by=reported_by, decision_id=saved.get("id"))
    return saved


def decisions_for(subject_type: str, subject_id: str) -> list[dict]:
    return db.select("office_decisions", "subject_type = ? AND subject_id = ?", (subject_type, subject_id),
                     "created_at DESC", 50)


# ------------------------------------------------------------------ reading the feed
def cursor() -> int:
    return int(db.scalar("SELECT COALESCE(MAX(id), 0) FROM office_events") or 0)


def events_after(after: int, limit: int = 200) -> dict:
    """Events newer than the cursor, oldest first. `reset` tells a client its cursor is from before the kept
    history (or from another database): reload the snapshot instead of replaying."""
    limit = max(1, min(500, int(limit)))
    oldest = int(db.scalar("SELECT COALESCE(MIN(id), 0) FROM office_events") or 0)
    latest = cursor()
    reset = after > latest or (after and oldest and after < oldest - 1)
    rows = [] if reset else db.select("office_events", "id > ?", (after,), "id ASC", limit)
    return {"events": rows, "cursor": rows[-1]["id"] if rows else (latest if reset else after), "latest": latest,
            "more": bool(rows) and rows[-1]["id"] < latest, "reset": bool(reset), "server_time": time.time()}


def prune(now: float | None = None) -> int:
    now = now or time.time()
    n = db.execute("DELETE FROM office_events WHERE at < ? OR id <= (SELECT COALESCE(MAX(id), 0) FROM office_events)"
                   " - ?", (now - KEEP_DAYS * 86400, KEEP_EVENTS))
    db.execute("DELETE FROM office_reports WHERE created_at < ?", (now - 90 * 86400,))
    return int(n or 0)

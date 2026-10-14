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
NEXT_JOBS = {"rights_check": ("hunt_source",), "hunt_source": ("analyze_source",),
             "package_clip": ("quality_check",), "regenerate_clip": ("package_clip",),
             "live_capture": ("post_live",)}
JOB_CHECKPOINTS = {"hunt_source": "source", "analyze_source": "source", "package_clip": "clip",
                   "schedule_tick": "qc", "publish": "upload"}


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
    if type_ in ("job_started", "job_stage"):
        try:
            data = {**_job_handoff(job, role, type_), **data}
        except Exception as exc:  # noqa: BLE001 - display metadata must not interrupt a leased job
            log.warning("office handoff not read for %s: %s", job.get("id"), exc)
    emit(type_, role, job_id=job.get("id") or "", kind=kind, ref=_ref(job), message=message,
         stage=stage or job.get("stage") or "",
         routine=kind in ROUTINE and not payload.get("manual"), worker=job.get("worker") or "", **data)


def _job_handoff(job: dict, role: str, type_: str) -> dict:
    """Route only an observed job assignment or stage change, using its recorded checkpoint when present.

    A decision cannot dispatch work by itself. The actual job transition must follow it within the live feed
    window. Older reports and unrelated sources are history, rather than evidence for a new document pass.
    """
    now = time.time()
    previous = db.select("office_events", "job_id = ? AND type IN ('job_started', 'job_stage')",
                         (job.get("id") or "",), "id DESC", 1)
    before = previous[0] if previous else None
    ref_type, ref_id = _ref(job)
    if type_ == "job_stage":
        decisions = db.select("office_decisions", "job_id = ? AND created_at > ?",
                              (job.get("id") or "", now - 30), "created_at DESC", 1)
    elif ref_type and ref_id and job.get("kind") in JOB_CHECKPOINTS:
        decisions = db.select("office_decisions", "subject_type = ? AND subject_id = ? AND created_at > ?",
                              (ref_type, ref_id, now - 30), "created_at DESC", 1)
    else:
        decisions = []
    if (decisions and decisions[0]["action"] == "approved"
            and (type_ == "job_stage" or decisions[0]["point"] == JOB_CHECKPOINTS.get(job.get("kind")))
            and (not before or float(decisions[0]["created_at"]) > float(before["at"]))):
        path = roles.handoff_path("command", roles.manager_of(role), role)
        return {"handoff_path": path, "handoff_kind": "stage", "decision_id": decisions[0]["id"]}
    if type_ == "job_started" and ref_type and ref_id:
        reports = db.select("office_reports", "ref_type = ? AND ref_id = ? AND created_at > ? "
                            "AND job_id != ?", (ref_type, ref_id, now - 30, job.get("id") or ""),
                            "created_at DESC", 1)
        if (reports and reports[0]["state"] == "done" and reports[0]["recommendation"] == "continue"
                and job.get("kind") in NEXT_JOBS.get(reports[0]["kind"], ())):
            return {"handoff_path": roles.handoff_path("command", roles.manager_of(role), role),
                    "handoff_kind": "stage", "report_id": reports[0]["id"]}
    if (type_ == "job_stage" and before and now - float(before["at"]) <= 30
            and before.get("kind") == job.get("kind") and _ref(before) == _ref(job)
            and before.get("role") != role):
        prior = before["role"]
        return {"handoff_path": roles.handoff_path(prior, roles.manager_of(prior), roles.manager_of(role), role),
                "handoff_kind": "stage"}
    # An empty explicit path prevents the browser from guessing a cross-department transfer without evidence.
    return {"handoff_path": [], "handoff_kind": "stage"}


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
         report_id=saved.get("id"), handoff_path=roles.reporting_path(worker), handoff_kind="report")
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
    try:
        path = _decision_handoff(reported_by, action, subject, evidence)
    except Exception as exc:  # noqa: BLE001 - a missing display route must not alter the recorded decision
        log.warning("office decision handoff not read: %s", exc)
        path = roles.reporting_path(reported_by)
    emit("decision", "command", job_id=job_id, ref=subject, message=reason[:300], point=point, action=action,
         reported_by=reported_by, decision_id=saved.get("id"),
         handoff_path=path, handoff_kind="decision")
    return saved


def _decision_handoff(reported_by: str, action: str, subject: tuple[str, str], evidence: dict) -> list[str]:
    path = roles.reporting_path(reported_by)
    repair_id, target = evidence.get("repair_job_id"), evidence.get("next_role")
    if action != "rework" or not repair_id or target not in roles.BY_ID:
        return path
    repair = db.fetch("worker_jobs", str(repair_id))
    # A rejection may suggest a role without assigning a job. Only an actual queued repair is handed back.
    if (not repair or repair.get("status") not in ("queued", "running", "waiting", "retrying")
            or _ref(repair) != subject):
        return path
    assigned = (repair.get("payload") or {}).get("handoff") or {}
    recipient = assigned.get("to_role") or roles.role_for(repair["kind"], repair.get("stage") or "")
    if recipient != target:
        return path
    return roles.handoff_path(*path, "command", roles.manager_of(target), target)


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

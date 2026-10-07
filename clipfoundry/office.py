"""The robot office's truth: which role is doing what, recorded reports and decisions, and the event feed.

Robots move only on events recorded here from real job transitions (autopilot/host.py). Nothing in this module
invents activity: a role with no job is idle (or in the Lounge while Autopilot is paused), unknown values stay
unknown, and the frontend's animation never decides anything.

Roles are responsibilities over the one durable job queue (section 9 of the owner's brief), not separate processes
or AI sessions. Manager reviews and Boss decisions are deterministic rules over a job's recorded outcome; each says
which rule (``RULES``) produced it, so a report can be inspected and explained.

Feed: ``snapshot()`` is authoritative; ``events(after=cursor)`` returns what happened since (autopilot_events ids are
the cursor, so duplicates and gaps are detectable and a reconnect simply reloads the snapshot).
"""
from __future__ import annotations

import time

from . import audience, db

RULES = "office-rules.v1"

# role id (frontend/src/robots/registry.ts) -> department
ROLE_DEPARTMENT = {
    "command": "boss_hub", "tracker": "discover", "vector": "analyze", "frame": "clip_studio", "script": "caption",
    "clock": "schedule", "harbor": "upload_dock", "switch": "system", "curator": "brain",
    "radar": "discover", "archive": "discover", "pulse": "analyze", "gavel": "analyze", "boost": "analyze",
    "spark": "clip_studio", "story": "clip_studio", "splice": "clip_studio", "glyph": "caption", "quill": "caption",
    "check": "system", "patch": "system", "lock": "upload_dock", "dock": "upload_dock", "metric": "brain",
    "synapse": "brain",
}
MANAGER = {"boss_hub": "command", "discover": "tracker", "analyze": "vector", "clip_studio": "frame",
           "caption": "script", "schedule": "clock", "upload_dock": "harbor", "system": "switch", "brain": "curator"}
DEPARTMENT_LABEL = {"boss_hub": "Boss Hub", "discover": "Discover", "analyze": "Analyze", "clip_studio": "Clip Studio",
                    "caption": "Captions", "schedule": "Schedule", "upload_dock": "Upload Dock", "system": "System",
                    "brain": "Brain Room"}

# job kind -> the role responsible for it (one owner per kind; deterministic)
KIND_ROLE = {
    "trend_scan": "pulse", "source_scout": "radar", "feed_scan": "radar", "identify_link": "archive",
    "live_watch": "radar", "live_capture": "radar", "post_live": "archive", "rights_check": "gavel",
    "hunt_source": "spark", "analyze_source": "story", "regenerate_clip": "splice", "package_clip": "quill",
    "quality_check": "check", "schedule_tick": "clock", "publish": "dock", "learn": "synapse",
    "maintenance": "patch", "selftest": "patch",
}
STAGE_LABEL = {
    "trend_scan": "Measuring trend momentum", "source_scout": "Searching for sources", "feed_scan": "Checking feeds",
    "identify_link": "Researching a link", "live_watch": "Watching a live stream", "live_capture": "Recording live",
    "post_live": "Finishing a live recording", "rights_check": "Judging a source", "hunt_source": "Finding moments",
    "analyze_source": "Checking context and payoff", "regenerate_clip": "Rendering a clip",
    "package_clip": "Writing titles and captions", "quality_check": "Quality check", "schedule_tick": "Scheduling",
    "publish": "Uploading", "learn": "Learning from results", "maintenance": "System check",
    "selftest": "Self-test",
}


# frequent bookkeeping jobs: their live state shows on the robot, but only a problem becomes a feed event, so the
# feed is not flooded with "checked the schedule" every minute
ROUTINE = {"schedule_tick", "maintenance", "feed_scan"}


def role_for(kind: str) -> str:
    return KIND_ROLE.get(kind, "patch")


def _event(kind: str, message: str, level: str = "info", ref_type: str = "", ref_id: str = "", **data) -> None:
    from .autopilot import state

    state.event(kind, message, level, ref_type, ref_id, rules=RULES, **data)


# ------------------------------------------------------------------ recording (called by autopilot/host.py)
def job_started(row: dict) -> None:
    if row["kind"] in ROUTINE:
        return
    role = role_for(row["kind"])
    _event("office.task_started", f"{role.upper()}: {STAGE_LABEL.get(row['kind'], row['kind'])}",
           ref_type=row.get("ref_type") or "", ref_id=row.get("ref_id") or "", role=role, job_id=row["id"],
           department=ROLE_DEPARTMENT[role], stage=row["kind"], attempt=int(row.get("attempts") or 0))


def job_finished(row: dict, outcome: dict, started_at: float) -> None:
    """A worker report, its manager's review and, when the outcome needs one, a Boss decision. All three are derived
    from the recorded job outcome; nothing here changes the job or approves any publishing."""
    role = role_for(row["kind"])
    dept = ROLE_DEPARTMENT[role]
    manager = MANAGER[dept]
    status = outcome.get("status") or "unknown"
    if row["kind"] in ROUTINE and status in ("completed", "waiting", "canceled"):
        return
    elapsed = round(time.time() - started_at, 1)
    ref = {"ref_type": row.get("ref_type") or "", "ref_id": row.get("ref_id") or ""}
    common = {"job_id": row["id"], "department": dept, "stage": row["kind"], "elapsed_s": elapsed,
              "attempts": int(outcome.get("attempts") or row.get("attempts") or 0)}
    message = ((outcome.get("error") if status == "failed" else "") or outcome.get("message") or "")[:300]
    result = outcome.get("result") or {}
    warnings = [str(w)[:200] for w in (result.get("warnings") or [])][:5] if isinstance(result, dict) else []
    _event("office.worker_report", f"{role.upper()} reported: {message or status}",
           "error" if status == "failed" else "info", **ref, role=role, state=status, warnings=warnings, **common)
    if status == "completed":
        review, rec, conf = "accepted", "Send the result on to the next stage", "high"
    elif status in ("retrying", "queued"):
        review, rec, conf = "rework", "Try again after a pause (bounded retries)", "medium"
    elif status == "waiting":
        review, rec, conf = "on_hold", "Wait for the resource or time it asked for, then continue", "high"
    elif status == "failed":
        review, rec, conf = "escalated", "Stop retrying this task and report it", "high"
    elif status == "canceled":
        review, rec, conf = "stopped", "Canceled; nothing more to do", "high"
    else:
        review, rec, conf = "unknown", "Outcome not recorded yet", "low"
    _event("office.manager_review", f"{manager.upper()} {review} {role.upper()}'s {STAGE_LABEL.get(row['kind'], '')}"
           .strip(), "warning" if review in ("rework", "escalated") else "info", **ref, role=manager,
           worker=role, review=review, recommendation=rec, confidence=conf, **common)
    if review == "escalated":
        _event("office.boss_decision", f"COMMAND: {STAGE_LABEL.get(row['kind'], row['kind'])} failed after "
               f"{common['attempts']} attempt(s); other work continues. {message}"[:500], "warning", **ref,
               role="command", decision="isolate_failure", reason=message, **common)


def record_safely(fn, *args) -> None:
    """Office records are observability: their failure must never fail or delay the job itself."""
    try:
        fn(*args)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("office record failed")


# ------------------------------------------------------------------ the feed
FEED_KINDS = ("office.%", "strategy_%", "brain_%", "emergency_stop", "resumed", "autopilot_on", "autopilot_off",
              "published", "publish_failed", "learned", "publishing_paused", "publishing_resumed")


def events(after: int = 0, limit: int = 200) -> dict:
    """Events after a cursor, oldest first. `gap` is set when more happened than fit (the client reloads the
    snapshot instead of replaying a stale backlog)."""
    clause = " OR ".join("kind LIKE ?" for _ in FEED_KINDS)
    rows = db.select("autopilot_events", f"id > ? AND ({clause})", (int(after), *FEED_KINDS), "id", limit + 1)
    gap = len(rows) > limit
    rows = rows[:limit]
    latest = int(db.scalar("SELECT COALESCE(MAX(id), 0) FROM autopilot_events") or 0)
    return {"events": [_shape(r) for r in rows], "cursor": rows[-1]["id"] if rows else max(int(after), 0),
            "latest": latest, "gap": gap, "server_time": time.time()}


def _shape(r: dict) -> dict:
    data = r.get("data") or {}
    return {"id": r["id"], "at": r["at"], "type": r["kind"], "level": r["level"], "message": r["message"],
            "role": data.get("role") or "", "job_id": data.get("job_id") or "",
            "department": data.get("department") or "", "ref_type": r["ref_type"], "ref_id": r["ref_id"],
            "data": {k: v for k, v in data.items() if k not in ("role", "job_id", "department")}}


def run_state(settings: dict) -> str:
    """running / paused / stopped: what the control bar shows (Start, Pause+Stop, or Resume+Stop)."""
    from .autopilot import home, state

    if state.paused():
        return "stopped"
    if settings.get("autopilot_enabled"):
        return "running"
    return "paused" if home.started_before() else "stopped"


def robots(settings: dict, run: str) -> list[dict]:
    """Every role's current, truthful state: working on a real job, waiting, blocked, or idle."""
    from .autopilot import queue

    active = queue.jobs(("running", "retrying", "waiting"), limit=200)
    latest_report = {}
    for e in db.select("autopilot_events", "kind IN ('office.worker_report', 'office.manager_review')", (), "id DESC",
                       200):
        role = (e.get("data") or {}).get("role")
        if role and role not in latest_report:
            latest_report[role] = {"at": e["at"], "message": e["message"], "level": e["level"]}
    out = []
    for role, dept in ROLE_DEPARTMENT.items():
        jobs = [j for j in active if role_for(j["kind"]) == role]
        running = [j for j in jobs if j["status"] == "running"]
        if running:
            j = running[0]
            st, task = "working", {"job_id": j["id"], "stage": j["kind"], "label": STAGE_LABEL.get(j["kind"], ""),
                                   "progress": j.get("progress"), "message": j.get("message") or "",
                                   "ref_type": j.get("ref_type") or "", "ref_id": j.get("ref_id") or ""}
        elif jobs:
            j = jobs[0]
            st = "error" if j["status"] == "retrying" else "waiting"
            task = {"job_id": j["id"], "stage": j["kind"], "label": STAGE_LABEL.get(j["kind"], ""), "progress": None,
                    "message": j.get("message") or j.get("error") or "", "ref_type": j.get("ref_type") or "",
                    "ref_id": j.get("ref_id") or ""}
        else:
            st, task = ("idle" if run == "running" else "lounge"), None
        if role in MANAGER.values() and st in ("idle", "lounge"):
            reviewing = any(role_for(j["kind"]) in _team(role) and j["status"] == "running" for j in active)
            if reviewing:
                st = "monitoring"  # a manager watches its team's running work; it does not invent a review
        out.append({"role": role, "department": dept, "manager": MANAGER[dept] if MANAGER[dept] != role else
                    "command", "state": st, "task": task, "queued": len(jobs), "last": latest_report.get(role)})
    return out


def _team(manager: str) -> set[str]:
    dept = next(d for d, m in MANAGER.items() if m == manager)
    return {r for r, d in ROLE_DEPARTMENT.items() if d == dept}


def snapshot(settings: dict | None = None) -> dict:
    """Everything the Office screen shows, from stored state only (safe to call often; no network calls)."""
    from . import brain, health
    from .autopilot import state

    settings = settings if settings is not None else db.get_settings()
    run = run_state(settings)
    now = time.time()
    day_start = now - (now % 86400)
    nxt = db.select("scheduled_publications", "status IN ('approved', 'awaiting_approval') AND planned_at >= ?",
                    (now - 600,), "planned_at", 1)
    made_today = int(db.scalar("SELECT COUNT(*) FROM clips WHERE status = 'ready' AND created_at >= ?",
                               (day_start,)) or 0)
    manual = db.select("scheduled_publications", "status = 'manual_handoff'")
    cursor = int(db.scalar("SELECT COALESCE(MAX(id), 0) FROM autopilot_events") or 0)
    brain_view = brain.view(settings)
    return {
        "cursor": cursor, "server_time": now, "run_state": run,
        "publishing_paused": bool(settings.get("autopilot_publish_paused")),
        "mission": _mission(run),
        "robots": robots(settings, run),
        "health": health.summary(settings),
        "today": {"clips_made": made_today,
                  "uploads": int(db.scalar("SELECT COUNT(*) FROM publications WHERE status = 'done' AND "
                                           "created_at >= ?", (day_start,)) or 0)},
        "next_upload": ({"id": nxt[0]["id"], "platform": nxt[0]["platform"], "planned_at": nxt[0]["planned_at"],
                         "title": nxt[0].get("title") or "", "status": nxt[0]["status"]} if nxt else None),
        "needs_you": [{"key": a["key"], "title": a["title"], "fix": a.get("fix") or "", "level": a["level"]}
                      for a in state.open_actions()][:8],
        "manual_handoffs": len(manual),
        "audience": audience.summary(settings),
        "brain": {"state": brain_view["state"], "observations": brain_view["observations"],
                  "strategy": brain_view["ranking"], "cohorts": brain_view["cohorts"]},
        "recent": events(max(0, cursor - 60), 60)["events"][-30:],
    }


def _mission(run: str) -> dict:
    from .autopilot import queue

    running = queue.jobs(("running",), limit=20)
    if run == "stopped":
        return {"title": "Stopped", "detail": "Nothing new starts until you press Start."}
    if run == "paused":
        return {"title": "Paused", "detail": "No new work is admitted; anything already finishing is shown below."
                + (f" {len(running)} still finishing." if running else "")}
    if not running:
        return {"title": "Waiting for the next task", "detail": "Autopilot is on; the next scan or step is queued."}
    j = running[0]
    return {"title": STAGE_LABEL.get(j["kind"], j["kind"]), "detail": j.get("message") or "",
            "job_id": j["id"], "role": role_for(j["kind"])}

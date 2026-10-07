"""What the office shows: one authoritative snapshot of the real state (run state, each role's current task, the
latest reports and decisions, health, audience), and the live details of one room.

Role states come only from the job system: a robot works while a job of its kind runs, waits while that job waits,
shows an error after a failure, and is paused when Autopilot is paused or stopped. Nothing here is animated or
estimated; the frontend decides how to draw it.
"""
from __future__ import annotations

import time

from .. import db
from ..autopilot import state as ap_state
from ..publish import audience
from . import feed, health, roles

REACT_SECONDS = 8.0      # how long a manager shows "reviewing" after a real report (or COMMAND after a decision)
ERROR_SECONDS = 30 * 60  # a failure is shown on its robot this long, unless newer work started


def run_state(settings: dict) -> dict:
    """Start when stopped, Pause/Stop when running, Resume/Stop when paused (never a conflicting pair)."""
    from ..autopilot import home

    on = bool(settings.get("autopilot_enabled"))
    if ap_state.paused():                # Stop all: queued work canceled and held until started again
        st = "stopped"
    elif on:
        st = "running"
    else:                                # turned off after a start is a pause; never started is stopped
        st = "paused" if home.started_before() else "stopped"
    actions = {"running": ["pause", "stop"], "paused": ["resume", "stop"], "stopped": ["start"]}[st]
    return {"state": st, "actions": actions, "publishing_paused": bool(settings.get("autopilot_publishing_paused")),
            "label": {"running": "Running", "paused": "Paused", "stopped": "Stopped"}[st]}


def _active_jobs() -> list[dict]:
    return db.select("worker_jobs", "status IN ('running', 'waiting', 'retrying', 'queued')", (), "updated_at DESC",
                     400)


def _recent_failures(now: float) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for j in db.select("worker_jobs", "status = 'failed' AND finished_at > ?", (now - ERROR_SECONDS,),
                       "finished_at DESC", 50):
        out.setdefault(roles.role_for(j["kind"], j.get("stage") or ""), j)
    return out


def _task(j: dict) -> dict:
    measured = j["status"] == "running" and float(j.get("progress") or 0) > 0
    return {"job_id": j["id"], "kind": j["kind"], "stage": j.get("stage") or "", "status": j["status"],
            "message": (j.get("message") or "")[:200], "progress": round(float(j["progress"]), 3) if measured else None,
            "ref_type": j.get("ref_type") or "", "ref_id": j.get("ref_id") or "", "updated_at": j.get("updated_at")}


def role_states(settings: dict, now: float | None = None) -> list[dict]:
    now = now or time.time()
    run = run_state(settings)
    jobs = _active_jobs()
    failures = _recent_failures(now)
    by_role: dict[str, list[dict]] = {}
    for j in jobs:
        by_role.setdefault(roles.role_for(j["kind"], j.get("stage") or ""), []).append(j)
    reports = db.select("office_reports", "created_at > ?", (now - REACT_SECONDS,), "created_at DESC", 20)
    decisions = db.select("office_decisions", "created_at > ?", (now - REACT_SECONDS,), "created_at DESC", 5)
    from ..autopilot.scheduler import uploadable_platforms

    can_upload = bool(uploadable_platforms(settings))
    out = []
    for r in roles.ROLES:
        mine = by_role.get(r["id"], [])
        running = [j for j in mine if j["status"] == "running"]
        waiting = [j for j in mine if j["status"] in ("waiting", "retrying")]
        queued = [j for j in mine if j["status"] == "queued"]
        failed = failures.get(r["id"])
        dept_jobs = [j for rid, js in by_role.items() if roles.department_of(rid) == r["department"] for j in js
                     if j["status"] == "running"]
        st, task = "idle", None
        if running:
            st, task = "working", _task(running[0])
        elif waiting:
            st, task = ("retrying" if waiting[0]["status"] == "retrying" else "waiting"), _task(waiting[0])
        elif failed and float(failed.get("finished_at") or 0) > max((float(j.get("updated_at") or 0) for j in mine),
                                                                     default=0):
            st, task = "error", _task(failed)
        if r["rank"] == "manager":
            if any(rep["manager"] == r["id"] for rep in reports):
                st = "reviewing"
            elif st == "idle" and dept_jobs:
                st = "working"  # watching its department's running work
        if r["id"] == "command":
            if decisions:
                st = "reviewing"
            elif st == "idle" and any(j["status"] == "running" for j in jobs):
                st = "working"
        if r["id"] in ("dock", "lock", "harbor") and not can_upload and st == "idle":
            st = "unavailable"
        if run["state"] != "running" and st in ("idle", "working") and not running:
            st = "paused"
        last = db.select("office_reports", "worker = ? OR manager = ?", (r["id"], r["id"]), "created_at DESC", 1)
        out.append({"id": r["id"], "state": st, "task": task, "tasks": len(mine), "queued": len(queued),
                    "error": ((failed or {}).get("error") or "")[:300] if st == "error" else "",
                    "last": ({"summary": last[0]["summary"], "state": last[0]["state"], "at": last[0]["created_at"]}
                             if last else None)})
    return out


def snapshot() -> dict:
    """The office's authoritative state plus the event cursor to continue from."""
    settings = db.get_settings()
    cur = feed.cursor()  # taken first: an event written meanwhile is delivered again, never lost
    now = time.time()
    from ..autopilot.scheduler import uploadable_platforms

    nxt = db.select("scheduled_publications", "status IN ('approved', 'publishing') AND planned_at >= ?",
                    (now - 600,), "planned_at", 1)
    dests = {p: audience.destination(p, settings) for p in ("youtube", "tiktok")}
    footer = "Selected audience: " + " · ".join(
        f"{'YouTube' if p == 'youtube' else 'TikTok'} {d['label'][:1].lower() + d['label'][1:]}"
        for p, d in dests.items())
    return {
        "cursor": cur, "server_time": now, "run": run_state(settings),
        "roles": role_states(settings, now),
        "reports": db.select("office_reports", "", (), "created_at DESC", 12),
        "decisions": db.select("office_decisions", "", (), "created_at DESC", 12),
        "health": health.check(settings),
        "audience": {"footer": footer, "destinations": dests, "uploadable": uploadable_platforms(settings),
                     "halted": {p: audience.halted(p) for p in ("youtube", "tiktok")}},
        "next_upload": ({"id": nxt[0]["id"], "platform": nxt[0]["platform"], "title": nxt[0].get("title") or "",
                         "planned_at": nxt[0]["planned_at"]} if nxt else None),
        "today": _today(settings, now),
        "needs_you": [{k: a.get(k) for k in ("key", "kind", "level", "title", "detail", "fix")}
                      for a in ap_state.open_actions()[:5]],
        "brain": _brain_summary(),
    }


def _today(settings: dict, now: float) -> dict:
    from ..autopilot.scout import day_bounds

    start, _ = day_bounds(settings, now)
    clips = int(db.scalar("SELECT COUNT(*) FROM clips WHERE status = 'ready' AND updated_at >= ?", (start,)) or 0)
    uploads = int(db.scalar("SELECT COUNT(*) FROM publications WHERE status = 'done' AND created_at >= ?", (start,))
                  or 0)
    ready = int(db.scalar("SELECT COUNT(*) FROM quality_reports WHERE status = 'passed' AND created_at >= ?",
                          (start,)) or 0)
    return {"clips": clips, "passed_check": ready, "uploads": uploads}


def _brain_summary() -> dict:
    try:
        from ..autopilot import brain

        return brain.summary()
    except ImportError:
        return {}


# ------------------------------------------------------------------ one room's live details
def room(room_id: str) -> dict:
    """Full readable details for the room panel (only what is recorded; unknown values stay unknown)."""
    if room_id not in roles.ROOMS:
        raise KeyError(room_id)
    settings = db.get_settings()
    cast = [r["id"] for r in roles.ROLES if r["room"] == room_id]
    out: dict = {"id": room_id, "name": roles.ROOMS[room_id], "roles": cast,
                 "events": db.select("office_events", "role IN (%s)" % ",".join("?" * len(cast)) if cast else "0",
                                     cast, "id DESC", 15) if cast else []}
    if room_id == "boss":
        out["decisions"] = db.select("office_decisions", "", (), "created_at DESC", 20)
        out["reports"] = db.select("office_reports", "", (), "created_at DESC", 20)
        out["queue"] = {r["status"]: r["n"] for r in _count("worker_jobs", "status", "status IN ('queued', 'running', "
                                                                                          "'waiting', 'retrying')")}
        out["needs_you"] = ap_state.open_actions()[:10]
    elif room_id == "discover":
        from ..autopilot import home

        out["discovery"] = home.discovery_status()
        out["found"] = db.select("sources", "", (), "created_at DESC", 10)
    elif room_id == "analyze":
        out["decisions"] = db.select("office_decisions", "point = 'source'", (), "created_at DESC", 10)
        out["trends"] = db.select("trend_signals", "status = 'active'", (), "score DESC", 6)
    elif room_id in ("studio", "caption"):
        out["decisions"] = db.select("office_decisions", "point IN ('clip', 'qc')", (), "created_at DESC", 10)
        out["clips"] = [{k: c.get(k) for k in ("id", "title", "status", "duration", "score", "start", "end",
                                                "caption_text", "hook", "progress", "error")}
                        for c in db.select("clips", "", (), "created_at DESC", 8)]
    elif room_id == "schedule":
        out["upcoming"] = db.select("scheduled_publications", "status IN ('awaiting_approval', 'approved', "
                                    "'publishing') AND planned_at IS NOT NULL", (), "planned_at", 12)
        out["timezone"] = settings.get("autopilot_timezone")
        out["publishing_paused"] = bool(settings.get("autopilot_publishing_paused"))
    elif room_id == "dock":
        out["audience"] = audience.view(settings)
        out["halted"] = {p: audience.halted(p) for p in ("youtube", "tiktok")}
        out["recent"] = [{**{k: i.get(k) for k in ("id", "platform", "title", "status", "status_note")},
                          "delivery_state": audience.delivery_state(i),
                          "delivery_label": audience.DELIVERY_LABELS.get(audience.delivery_state(i), ""),
                          "delivery": i.get("delivery") or {}}
                         for i in db.select("scheduled_publications", "status IN ('publishing', 'published', "
                                            "'action_needed', 'blocked', 'reconciling')", (), "updated_at DESC", 10)]
        out["decisions"] = db.select("office_decisions", "point = 'upload'", (), "created_at DESC", 10)
    elif room_id == "system":
        out["health"] = health.check(settings)
        out["devlog"] = devlog(20)
    elif room_id == "brain":
        out["brain"] = _brain_summary()
    elif room_id in ("lounge", "workspace"):
        out["reports"] = db.select("office_reports", "", (), "created_at DESC", 10)
    return out


def _count(table: str, column: str, where: str) -> list[dict]:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(f"SELECT {column}, COUNT(*) AS n FROM {table} WHERE {where} "
                                              f"GROUP BY {column}").fetchall()]


def devlog(limit: int = 50) -> list[dict]:
    """The development history (.clipfoundry/ai-change-log.jsonl), read-only. Missing file: an empty list."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / ".clipfoundry" / "ai-change-log.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(rows))[:limit]

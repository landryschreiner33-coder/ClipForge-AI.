"""What the office shows: one authoritative snapshot of the real state (run state, each role's current task, the
latest reports and decisions, health, audience), and the live details of one room.

Role states come only from recorded work: Autopilot's queue and the work you started yourself (office/work.py: Make
clips projects, clip renders, the studio's durable jobs and editor requests). A robot works while a job of its kind
runs, waits while it is queued or waiting, shows an error after a failure, and is idle otherwise. Robots show "paused"
only when you paused or stopped Autopilot and they have none of your own work; Autopilot that was never started does
not make the office look paused. Nothing here is animated or estimated; the frontend decides how to draw it.
"""
from __future__ import annotations

import time
from pathlib import Path

from .. import db
from ..autopilot import state as ap_state
from ..publish import audience
from . import feed, health, roles, work

REACT_SECONDS = 8.0      # how long a manager shows "reviewing" after a real report (or COMMAND after a decision)
ERROR_SECONDS = 30 * 60  # a failure is shown on its robot this long, unless newer work started
QUEUED_TEXT = "Waiting in queue"  # queue.enqueue's first message, still there until the handler reports a step


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


def _active_jobs(now: float | None = None) -> list[dict]:
    """Autopilot's queue plus your own work, running first (each item once, with its stable id)."""
    rows = db.select("worker_jobs", "status IN ('running', 'waiting', 'retrying', 'queued')", (),
                     "CASE WHEN status = 'running' THEN 0 ELSE 1 END, updated_at DESC", 400)
    mine = work.active(now)
    return sorted(rows + mine, key=lambda j: (j["status"] != "running", -float(j.get("updated_at") or 0)))


def _recent_failures(now: float) -> dict[str, dict]:
    out: dict[str, dict] = {}
    rows = db.select("worker_jobs", "status = 'failed' AND finished_at > ?", (now - ERROR_SECONDS,),
                     "finished_at DESC", 50) + work.failures(now)
    for j in sorted(rows, key=lambda j: -float(j.get("finished_at") or 0)):
        out.setdefault(roles.role_for(j["kind"], j.get("stage") or ""), j)
    return out


def _task(j: dict) -> dict:
    measured = j["status"] == "running" and float(j.get("progress") or 0) > 0
    message = j.get("message") or ""
    if j["status"] == "running" and message == QUEUED_TEXT:  # claimed, but its handler has not said anything yet
        message = "Started"
    payload = j.get("payload") or {}
    handoff = payload.get("handoff") or {}
    clip_id = payload.get("clip_id") or (j.get("ref_id") if j.get("ref_type") == "clip" else "") or ""
    clip = db.get_clip(clip_id) or {}
    project_id = payload.get("project_id") or clip.get("project_id") or ""
    source_id = payload.get("source_id") or (j.get("ref_id") if j.get("ref_type") == "source" else "") or ""
    source = db.fetch("sources", source_id) or {}
    project_id = project_id or source.get("project_id") or ""
    project = db.get_project(project_id) or {}
    source_id = source_id or project.get("source_id") or ""
    dependencies = []
    if Path(project.get("source_path") or "").is_file():
        dependencies.append("Source recording saved")
    if project_id:
        from .. import config

        if (config.projects_dir() / project_id / "transcript.json").is_file():
            dependencies.append("Transcript saved")
    if Path(clip.get("output_path") or "").is_file():
        dependencies.append("Rendered clip saved")
    if handoff.get("report_id"):
        dependencies.append("Final check returned this work with a specific reason")
    next_role = {"hunt_source": "boost", "analyze_source": "quill", "post_live": "quill",
                 "regenerate_clip": "quill", "package_clip": "check", "quality_check": "harbor",
                 "schedule_tick": "lock", "publish": "metric", "live_capture": "spark",
                 "link_import": "archive", "video_build": "splice", "video_render": "harbor"}.get(j["kind"], "")
    blocked = (j.get("error") or message) if j["status"] in ("waiting", "retrying", "failed") else \
        (("Queued behind earlier work" if j.get("origin") == "owner" else "Waiting for background work to start")
         if j["status"] == "queued" else "")
    return {"job_id": j["id"], "kind": j["kind"], "stage": j.get("stage") or handoff.get("stage") or "",
            "status": j["status"],
            "message": message[:200], "progress": round(float(j["progress"]), 3) if measured else None,
            "ref_type": j.get("ref_type") or "", "ref_id": j.get("ref_id") or "", "updated_at": j.get("updated_at"),
            "blocked_reason": blocked[:400], "next_role": next_role, "dependencies": dependencies,
            "shared": {"source_id": source_id, "project_id": project_id, "clip_id": clip_id,
                       "video_id": payload.get("video_id") or ""},
            "origin": j.get("origin") or "autopilot", "title": str(payload.get("title") or "")[:120],
            "handoff": handoff or None}


def _job_role(j: dict) -> str:
    handoff = (j.get("payload") or {}).get("handoff") or {}
    if j["status"] == "queued" and handoff.get("to_role") in roles.BY_ID:
        return handoff["to_role"]
    return roles.role_for(j["kind"], j.get("stage") or "")


def _quality_blocked(jobs: list[dict], now: float) -> dict | None:
    """A completed check can reject a clip without failing the worker itself. Keep that blocker visible."""
    from ..autopilot import gate

    active_clips = {(j.get("payload") or {}).get("clip_id") for j in jobs}
    for rep in db.select("quality_reports", "updated_at > ?", (now - ERROR_SECONDS,), "updated_at DESC", 30):
        if rep["clip_id"] in active_clips:
            continue
        clip = db.get_clip(rep["clip_id"])
        if not clip or clip.get("status") != "ready" or (gate.report_for(clip) or {}).get("id") != rep["id"]:
            continue
        bad_text = [p for p, m in (rep.get("metadata") or {}).items() if m.get("status") != "passed"]
        if rep["status"] == "passed" and not bad_text:
            continue
        rows = db.select("worker_jobs", "kind = 'quality_check' AND ref_id = ?", (clip["id"],),
                         "created_at DESC", 1)
        if not rows:
            continue
        task = _task(rows[0])
        reason = "; ".join(rep.get("blockers") or ["Post text did not pass for " + ", ".join(bad_text)])
        task.update(status="blocked", progress=None, message=reason[:200], blocked_reason=reason[:400],
                    next_role=gate.rework_target(rep)[1] if rep["status"] != "passed" else "quill")
        return task
    return None


def _consultation_task(activity: dict) -> dict:
    """A measured knowledge consultation is real work, but it is not a made-up queue job or progress bar."""
    return {"job_id": "", "kind": "brain_consultation", "stage": "knowledge", "status": "running",
            "consultation_id": activity.get("consultation_id") or "",
            "message": str(activity.get("message") or "Consulting saved Brain guidance")[:200], "progress": None,
            "ref_type": activity.get("ref_type") or "", "ref_id": activity.get("ref_id") or "",
            "updated_at": activity.get("at"), "blocked_reason": "", "next_role": "curator",
            "dependencies": [], "shared": {}, "handoff": None}


def _idle_reason(role: dict, state: str, task: dict | None, brain: dict) -> str:
    if state in ("working", "reviewing"):
        return ""
    if state == "paused":
        return "Autopilot is paused or stopped, so it assigns no background work. Your own projects still run."
    if task and task.get("blocked_reason"):
        return task["blocked_reason"]
    if state == "unavailable":
        return "Publishing is unavailable. Check Settings → Integrations and Who watches."
    if role["department"] == "brain":
        if brain.get("state") == "paused":
            return "Brain guidance and strategy changes are paused; result collection can still run."
        return "Waiting for the next saved-guidance consultation or result collection. " + \
            "Strategy changes need enough mature, comparable results."
    if role["id"] == "dock":
        return "Waiting for an approved post to reach its posting time."
    return {
        "control": "Waiting for a department report or a video, clip, final-check or upload decision.",
        "intake": "Waiting for a file or link you add.",
        "research": "Waiting for a Find media search or a file you pick to download.",
        "story": "Waiting for a video to transcribe, or moments and stories to find.",
        "editing": "Waiting for a rough cut, a change you ask for or a preview to render.",
        "sound": "Waiting for clips that need captions or a sound check.",
        "quality": "Waiting for a final render, a finished-file check or the next maintenance pass.",
        "publishing": "Waiting for posts to review, schedule or upload.",
    }.get(role["department"], "No work is currently assigned.")


def role_states(settings: dict, now: float | None = None, *, brain: dict | None = None) -> list[dict]:
    now = now or time.time()
    run = run_state(settings)
    # Autopilot held by you (paused after a start, or Stop all). Never started is not a pause.
    autopilot_held = run["state"] == "paused" or ap_state.paused()
    jobs = _active_jobs(now)
    failures = _recent_failures(now)
    by_role: dict[str, list[dict]] = {}
    for j in jobs:
        by_role.setdefault(_job_role(j), []).append(j)
    # roles with your own work, their managers and the Director keep showing it while Autopilot is held
    owner_roles = {rid for rid, js in by_role.items() if any(j.get("origin") == "owner" for j in js)}
    owner_roles |= {roles.manager_of(rid) for rid in owner_roles} | ({"command"} if owner_roles else set())
    quality_blocked = _quality_blocked(jobs, now)
    reports = db.select("office_reports", "created_at > ?", (now - REACT_SECONDS,), "created_at DESC", 20)
    decisions = db.select("office_decisions", "created_at > ?", (now - REACT_SECONDS,), "created_at DESC", 5)
    brain = _brain_summary(settings) if brain is None else brain
    activity = brain.get("activity") or {}
    consultation = (run["state"] == "running" and not settings.get("brain_paused")
                    and activity.get("state") == "working" and activity.get("consultation_id")
                    and now - 120 <= float(activity.get("at") or 0) <= now + 5)
    brain_last = activity.get("last") or {}
    brain_review = (run["state"] == "running" and not settings.get("brain_paused")
                    and brain_last.get("state") == "done"
                    and now - REACT_SECONDS <= float(brain_last.get("at") or 0) <= now + 5)
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
        elif queued:  # assigned, not started yet (distinct from work that started and is now waiting)
            st, task = "queued", _task(queued[0])
        elif r["id"] == "check" and quality_blocked:
            st, task = "error", quality_blocked
        if r["id"] == "synapse" and consultation and not running:
            st, task = "working", _consultation_task(activity)
        if r["rank"] == "manager" and st == "idle":
            if any(rep["manager"] == r["id"] for rep in reports):
                st = "reviewing"
            elif r["id"] == "curator" and brain_review:
                st = "reviewing"
            elif dept_jobs or (r["id"] == "curator" and consultation):
                st = "working"  # watching its department's running work
        if r["id"] == "command" and st == "idle":
            if decisions or reports or brain_review:
                st = "reviewing"
            elif any(j["status"] == "running" for j in jobs) or consultation:
                st = "working"
        if r["id"] in ("dock", "lock", "harbor") and not can_upload and st == "idle":
            st = "unavailable"
        if autopilot_held and st in ("idle", "working") and not running and r["id"] not in owner_roles:
            st = "paused"
        last = (db.select("office_reports", "", (), "created_at DESC", 1) if r["id"] == "command" else
                db.select("office_reports", "worker = ? OR manager = ?", (r["id"], r["id"]), "created_at DESC", 1))
        out.append({"id": r["id"], "state": st, "task": task, "tasks": len(mine), "queued": len(queued),
                    "owner_tasks": sum(1 for j in mine if j.get("origin") == "owner"),
                    "error": ((task or {}).get("blocked_reason") or (failed or {}).get("error") or "")[:300]
                    if st == "error" else "",
                    "last": ({"summary": last[0]["summary"], "state": last[0]["state"], "at": last[0]["created_at"]}
                             if last else None), "idle_reason": _idle_reason(r, st, task, brain)})
    return out


def snapshot() -> dict:
    """The office's authoritative state plus the event cursor to continue from."""
    settings = db.get_settings()
    cur = feed.cursor()  # taken first: an event written meanwhile is delivered again, never lost
    now = time.time()
    brain = _brain_summary(settings)
    from ..autopilot.scheduler import uploadable_platforms

    nxt = db.select("scheduled_publications", "status IN ('approved', 'publishing') AND planned_at >= ?",
                    (now - 600,), "planned_at", 1)
    dests = {p: audience.destination(p, settings) for p in ("youtube", "tiktok")}
    footer = "Who watches: " + " · ".join(
        f"{'YouTube' if p == 'youtube' else 'TikTok'} {d['label'][:1].lower() + d['label'][1:]}"
        for p, d in dests.items())
    return {
        "cursor": cur, "server_time": now, "run": run_state(settings),
        "roles": role_states(settings, now, brain=brain),
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
        "brain": brain,
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


def _brain_summary(settings: dict | None = None) -> dict:
    try:
        from ..autopilot import brain

        return brain.summary(settings)
    except ImportError:
        return {}


# ------------------------------------------------------------------ one room's live details
def room(room_id: str) -> dict:
    """Full readable details for the room panel (only what is recorded; unknown values stay unknown). A room id from
    before the rooms followed the workflow still opens the room that took its place."""
    room_id = roles.OLD_ROOMS.get(room_id, room_id)
    if room_id not in roles.ROOMS:
        raise KeyError(room_id)
    settings = db.get_settings()
    cast = [r["id"] for r in roles.ROLES if r["room"] == room_id]
    out: dict = {"id": room_id, "name": roles.ROOMS[room_id], "roles": cast,
                 "does": (roles.DEPARTMENTS.get(room_id) or {}).get("does", ""),
                 "events": db.select("office_events", "role IN (%s)" % ",".join("?" * len(cast)) if cast else "0",
                                     cast, "id DESC", 15) if cast else []}
    ws = work.workspace()
    mine, args = (" AND workspace_id = ?", (ws,)) if ws else ("", ())
    if room_id == "control":
        out["decisions"] = db.select("office_decisions", "", (), "created_at DESC", 20)
        out["reports"] = db.select("office_reports", "", (), "created_at DESC", 20)
        out["queue"] = {r["status"]: r["n"] for r in _count("worker_jobs", "status", "status IN ('queued', 'running', "
                                                                                          "'waiting', 'retrying')")}
        yours = work.active()
        out["yours"] = {k: sum(1 for j in yours if j["status"] == k) for k in ("running", "queued")}
        out["needs_you"] = ap_state.open_actions()[:10]
    elif room_id == "intake":
        out["projects"] = [{k: p.get(k) for k in ("id", "name", "status", "stage", "message", "origin", "updated_at")}
                           for p in db.select("projects", "1 = 1" + mine, args, "updated_at DESC", 8)]
        out["videos"] = [{k: v.get(k) for k in ("id", "name", "status", "message", "updated_at")}
                         for v in db.select("studio_projects", "1 = 1" + mine, args, "updated_at DESC", 6)]
        out["decisions"] = db.select("office_decisions", "point = 'source'", (), "created_at DESC", 8)
    elif room_id == "research":
        out["media"] = [{k: m.get(k) for k in ("id", "title", "provider", "kind", "creator", "license", "license_name",
                                               "user_basis", "created_at")}
                        for m in db.select("asset_sources", "1 = 1" + mine, args, "created_at DESC", 10)]
        out["imports"] = [{k: m.get(k) for k in ("id", "title", "provider", "kind", "status", "message", "error",
                                                 "updated_at")}
                          for m in db.select("media_imports", "1 = 1" + mine, args, "updated_at DESC", 8)]
    elif room_id == "story":
        out["examples"] = [{k: r.get(k) for k in ("id", "title", "status", "message", "avoid", "updated_at")}
                           for r in db.select("reference_videos", "1 = 1" + mine, args, "updated_at DESC", 6)]
        out["decisions"] = db.select("office_decisions", "point = 'source'", (), "created_at DESC", 8)
    elif room_id in ("editing", "sound"):
        out["decisions"] = db.select("office_decisions", "point IN ('clip', 'qc')", (), "created_at DESC", 10)
        out["clips"] = [{k: c.get(k) for k in ("id", "title", "status", "duration", "score", "start", "end",
                                                "caption_text", "hook", "progress", "error")}
                        for c in db.select("clips", "", (), "created_at DESC", 8)]
        if room_id == "editing":
            out["videos"] = [{k: v.get(k) for k in ("id", "name", "status", "message", "plan_revision",
                                                    "rendered_revision", "updated_at")}
                             for v in db.select("studio_projects", "1 = 1" + mine, args, "updated_at DESC", 6)]
    elif room_id == "quality":
        out["health"] = health.check(settings)
        out["devlog"] = devlog(20)
    elif room_id == "publishing":
        out["upcoming"] = db.select("scheduled_publications", "status IN ('awaiting_approval', 'approved', "
                                    "'publishing') AND planned_at IS NOT NULL", (), "planned_at", 12)
        out["timezone"] = settings.get("autopilot_timezone")
        out["publishing_paused"] = bool(settings.get("autopilot_publishing_paused"))
        out["audience"] = audience.view(settings)
        out["halted"] = {p: audience.halted(p) for p in ("youtube", "tiktok")}
        out["recent"] = [{**{k: i.get(k) for k in ("id", "platform", "title", "status", "status_note")},
                          "delivery_state": audience.delivery_state(i),
                          "delivery_label": audience.DELIVERY_LABELS.get(audience.delivery_state(i), ""),
                          "delivery": i.get("delivery") or {}}
                         for i in db.select("scheduled_publications", "status IN ('publishing', 'published', "
                                            "'action_needed', 'blocked', 'reconciling')", (), "updated_at DESC", 10)]
        out["decisions"] = db.select("office_decisions", "point = 'upload'", (), "created_at DESC", 10)
    elif room_id == "brain":
        out["brain"] = _brain_summary(settings)
    elif room_id == "lounge":
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

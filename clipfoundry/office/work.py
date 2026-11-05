"""Work you started yourself, as the office sees it.

The office used to read only Autopilot's queue, so a Make clips project, a full video's rough cut or render, a Find
media download or an example-video analysis left every robot idle. This module reads that work from where it is
recorded (the projects, clips and clip_versions tables, the studio's durable jobs and editor requests) and returns it in
the same shape as an Autopilot queue row, with a stable id per item, so the same rules decide who works on it.

Nothing is estimated: a status, stage, message and progress are shown only as recorded. Autopilot's own projects
are left out here because its queue already shows them (no work is counted twice).
"""
from __future__ import annotations

import time

from .. import db

ERROR_SECONDS = 30 * 60
STUDIO_KINDS = {"link_import": "Fetching the video from your link", "video_build": "Building the rough cut",
                "video_media": "Reading files added to a video", "video_preview": "Rendering a preview",
                "video_render": "Rendering the final video", "media_import": "Downloading media you picked",
                "media_suggest": "Searching for supporting media", "reference_analysis": "Measuring an example video"}
# what a Make clips project's pipeline stage means, in words, when the pipeline left no message
STAGE_WORDS = {"queued": "Waiting to start", "download": "Getting the video", "probe": "Reading the video",
               "audio": "Extracting the sound", "transcribe": "Transcribing", "candidates": "Finding moments",
               "scoring": "Scoring moments", "render": "Rendering clips"}


def workspace() -> str | None:
    try:
        from ..cloud import principal

        return principal.workspace_id()
    except Exception:  # noqa: BLE001 - outside a request (a test, the worker): every workspace on this machine
        return None


def _row(**kw) -> dict:
    base = {"payload": {}, "ref_type": "", "ref_id": "", "stage": "", "progress": 0.0, "message": "", "error": "",
            "status": "running", "updated_at": time.time(), "finished_at": None, "origin": "owner"}
    return {**base, **kw}


def _mine(ws: str | None, column: str = "workspace_id") -> tuple[str, tuple]:
    return (f" AND {column} = ?", (ws,)) if ws else ("", ())


def target(j: dict) -> tuple[str, str, dict]:
    """What a studio job works on, as (ref_type, ref_id, payload): the Make clips project behind a link download, the
    video a media download is for, the example video being measured, or the video itself."""
    kind, tid = j["kind"], j["target_id"]
    if kind == "link_import":
        link = db.fetch("link_imports", tid) or {}
        project = db.get_project(link.get("project_id") or "") or {}
        return ("project", project["id"], {"project_id": project["id"], "title": project.get("name") or ""}) \
            if project else ("", "", {})
    if kind == "media_import":
        row = db.fetch("media_imports", tid) or {}
        video = db.fetch("studio_projects", row.get("project_id") or "") or {}
        return ("video" if video else "", video.get("id", ""),
                {"video_id": video.get("id", ""), "title": row.get("title") or video.get("name") or ""})
    if kind == "reference_analysis":
        ref = db.fetch("reference_videos", tid) or {}
        return ("example", ref.get("id", ""), {"example_id": ref.get("id", ""), "title": ref.get("title") or ""})
    video = db.fetch("studio_projects", tid) or {}
    return ("video" if video else "", video.get("id", ""), {"video_id": video.get("id", ""),
                                                             "title": video.get("name") or ""})


def active(now: float | None = None) -> list[dict]:
    """Owner work that is queued, running or waiting for you right now (newest first within each kind)."""
    now = now or time.time()
    ws = workspace()
    out: list[dict] = []
    where, args = _mine(ws)
    for j in db.select("studio_jobs", "status IN ('queued', 'running')" + where, args, "updated_at DESC", 100):
        ref_type, ref_id, payload = target(j)
        out.append(_row(id=j["id"], kind=j["kind"], status=j["status"], progress=float(j.get("progress") or 0),
                        message=j.get("message") or STUDIO_KINDS.get(j["kind"], ""), updated_at=j["updated_at"],
                        ref_type=ref_type, ref_id=ref_id, payload=payload))
    pwhere, pargs = _mine(ws)
    with db.connect() as conn:
        projects = [dict(r) for r in conn.execute(
            "SELECT id, name, status, stage, progress, message, updated_at FROM projects WHERE status IN "
            "('queued', 'processing') AND COALESCE(origin, 'manual') NOT IN ('autopilot', 'live')" + pwhere +
            " ORDER BY updated_at DESC LIMIT 100", pargs)]
        clips = [dict(r) for r in conn.execute(
            "SELECT c.id, c.title, c.status, c.progress, c.updated_at, c.project_id FROM clips c JOIN projects p ON "
            "p.id = c.project_id WHERE c.status IN ('queued', 'rendering') AND COALESCE(p.origin, 'manual') NOT IN "
            "('autopilot', 'live')" + pwhere.replace("workspace_id", "p.workspace_id") +
            " ORDER BY c.updated_at DESC LIMIT 100", pargs)]
        versions = [dict(r) for r in conn.execute(
            "SELECT v.id, v.clip_id, v.label, v.status, v.progress, v.updated_at, c.project_id, c.title FROM "
            "clip_versions v JOIN clips c ON c.id = v.clip_id JOIN projects p ON p.id = c.project_id WHERE v.status IN "
            "('queued', 'rendering') AND COALESCE(p.origin, 'manual') NOT IN ('autopilot', 'live')" +
            pwhere.replace("workspace_id", "p.workspace_id") + " ORDER BY v.updated_at DESC LIMIT 50", pargs)]
    for p in projects:
        stage = p.get("stage") or "queued"
        out.append(_row(id=f"project:{p['id']}", kind="project", stage=stage,
                        status="queued" if p["status"] == "queued" else "running",
                        progress=float(p.get("progress") or 0), updated_at=p["updated_at"],
                        message=p.get("message") or STAGE_WORDS.get(stage, ""), ref_type="project", ref_id=p["id"],
                        payload={"project_id": p["id"], "title": p.get("name") or ""}))
    for c in clips:
        out.append(_row(id=f"clip:{c['id']}", kind="clip_render", status="queued" if c["status"] == "queued" else
                        "running", progress=float(c.get("progress") or 0), updated_at=c["updated_at"],
                        message="Waiting to render" if c["status"] == "queued" else "Rendering a clip",
                        ref_type="clip", ref_id=c["id"],
                        payload={"clip_id": c["id"], "project_id": c["project_id"], "title": c.get("title") or ""}))
    for v in versions:
        out.append(_row(id=f"version:{v['id']}", kind="version_render", status="queued" if v["status"] == "queued"
                        else "running", progress=float(v.get("progress") or 0), updated_at=v["updated_at"],
                        message="Waiting to render a version" if v["status"] == "queued" else "Rendering a version",
                        ref_type="clip", ref_id=v["clip_id"],
                        payload={"clip_id": v["clip_id"], "project_id": v["project_id"],
                                 "title": v.get("label") or v.get("title") or ""}))
    rwhere, rargs = _mine(ws)
    for r in db.select("edit_requests", "status = 'thinking'" + rwhere, rargs, "created_at DESC", 20):
        out.append(_row(id=f"request:{r['id']}", kind="edit_request", status="running", updated_at=r["updated_at"],
                        message=f"Asking {r.get('provider') or 'the AI service'} about “{r['text'][:60]}”",
                        ref_type="video", ref_id=r["project_id"], payload={"video_id": r["project_id"]}))
    # an editor request that waits for you: a question to answer, or proposed changes to check and apply. Only while
    # it was made for the edit as it is now; after any other edit the editor marks it out of date and nothing waits.
    for r in db.select("edit_requests", "status IN ('question', 'ready')" + rwhere, rargs, "created_at DESC", 20):
        video = db.fetch("studio_projects", r["project_id"]) or {}
        if not video or int(r.get("base_revision") or 0) != int(video.get("plan_revision") or 0):
            continue
        message = (f"Waiting for your answer: {r.get('message') or ''}" if r["status"] == "question"
                   else "Waiting for you to check the proposed changes and apply them")
        out.append(_row(id=f"request:{r['id']}", kind="edit_request", status="waiting", updated_at=r["updated_at"],
                        message=message[:200], ref_type="video", ref_id=r["project_id"],
                        payload={"video_id": r["project_id"], "title": video.get("name") or "", "waiting_on": "you"}))
    return out


def failures(now: float | None = None) -> list[dict]:
    """Owner work that failed in the last half hour (so its robot shows the error until newer work starts)."""
    now = now or time.time()
    ws = workspace()
    where, args = _mine(ws)
    out = []
    for j in db.select("studio_jobs", "status = 'failed' AND updated_at > ?" + where, (now - ERROR_SECONDS, *args),
                       "updated_at DESC", 30):
        ref_type, ref_id, payload = target(j)
        out.append(_row(id=j["id"], kind=j["kind"], status="failed", error=j.get("error") or "It stopped.",
                        message=STUDIO_KINDS.get(j["kind"], ""), updated_at=j["updated_at"], finished_at=j["updated_at"],
                        ref_type=ref_type, ref_id=ref_id, payload=payload))
    pwhere, pargs = _mine(ws)
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, stage, error, updated_at FROM projects WHERE status = 'error' AND updated_at > ? AND "
            "COALESCE(origin, 'manual') NOT IN ('autopilot', 'live')" + pwhere + " ORDER BY updated_at DESC LIMIT 30",
            (now - ERROR_SECONDS, *pargs))]
    for p in rows:
        out.append(_row(id=f"project:{p['id']}", kind="project", stage=p.get("stage") or "", status="failed",
                        message=STAGE_WORDS.get(p.get("stage") or "", ""), payload={"project_id": p["id"],
                                                                                    "title": p.get("name") or ""},
                        error=p.get("error") or "It stopped.", updated_at=p["updated_at"],
                        finished_at=p["updated_at"], ref_type="project", ref_id=p["id"]))
    return out


HISTORY_SECONDS = 24 * 3600
_ENDED = {"done": "job_done", "failed": "job_failed", "canceled": "job_canceled"}


def history(role_id: str, now: float | None = None, limit: int = 8) -> list[dict]:
    """One robot's log of your own work that ended in the last day, newest first: what it was for, how it ended and
    when, from the recorded rows (the shared office feed has no workspace, so your work is read from its own rows)."""
    from .roles import role_for

    now = now or time.time()
    ws = workspace()
    where, args = _mine(ws)
    since = now - HISTORY_SECONDS
    out: list[dict] = []
    for j in db.select("studio_jobs", "status IN ('done', 'failed', 'canceled') AND updated_at > ?" + where,
                       (since, *args), "updated_at DESC", 200):
        if role_for(j["kind"], "") != role_id:
            continue
        ref_type, ref_id, payload = target(j)
        label = STUDIO_KINDS.get(j["kind"], j["kind"])
        detail = f" ({j.get('error')})" if j["status"] == "failed" and j.get("error") else ""
        out.append({"at": j["updated_at"], "type": _ENDED[j["status"]], "role": role_id, "kind": j["kind"],
                    "ref_type": ref_type, "ref_id": ref_id,
                    "message": f"{label}{': ' + payload['title'] if payload.get('title') else ''}{detail}"[:300]})
    with db.connect() as conn:
        projects = [dict(r) for r in conn.execute(
            "SELECT id, name, status, stage, error, updated_at FROM projects WHERE status IN ('ready', 'error') AND "
            "updated_at > ? AND COALESCE(origin, 'manual') NOT IN ('autopilot', 'live')" + where +
            " ORDER BY updated_at DESC LIMIT 100", (since, *args))]
    for p in projects:
        ready = p["status"] == "ready"
        # a finished project's last step was the clip render; a stopped one names the step it stopped at
        if role_for("project", "render" if ready else (p.get("stage") or "queued")) != role_id:
            continue
        what = "Clips rendered" if ready else (STAGE_WORDS.get(p.get("stage") or "", "") or "Stopped")
        detail = f" ({p.get('error')})" if not ready and p.get("error") else ""
        out.append({"at": p["updated_at"], "type": "job_done" if ready else "job_failed", "role": role_id,
                    "kind": "project", "ref_type": "project", "ref_id": p["id"],
                    "message": f"{what}: {p.get('name') or ''}{detail}"[:300]})
    if role_id == "story":
        for r in db.select("edit_requests", "status IN ('applied', 'failed') AND updated_at > ?" + where,
                           (since, *args), "updated_at DESC", 50):
            applied = r["status"] == "applied"
            out.append({"at": r["updated_at"], "type": "job_done" if applied else "job_failed", "role": role_id,
                        "kind": "edit_request", "ref_type": "video", "ref_id": r["project_id"],
                        "message": (f"Changes applied: “{r['text'][:80]}”" if applied
                                    else f"Request stopped: “{r['text'][:80]}” ({r.get('message') or ''})")[:300]})
    out.sort(key=lambda e: e["at"], reverse=True)
    return out[:limit]

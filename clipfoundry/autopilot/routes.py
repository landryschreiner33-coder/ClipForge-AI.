"""REST endpoints for Autopilot. State-changing calls only work from ClipFoundry's own page on this computer."""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, db, gpu
from ..publish.common import app_request, local_only
from . import gate, providers, queue, quota, rights, scout, state
from .host import MANUAL_PRIORITY, supervisor

router = APIRouter(prefix="/api/autopilot")
READ = [Depends(local_only)]
WRITE = [Depends(app_request)]


def _manual(kind: str, payload: dict | None = None, ref: tuple[str, str] = ("", "")) -> dict:
    """A job the user started: runs even while Autopilot is off (but never during STOP ALL JOBS)."""
    return queue.enqueue(kind, payload or {}, priority=MANUAL_PRIORITY, ref=ref, message="Started by you",
                         idem_key=f"manual:{kind}:{ref[1]}:{int(time.time())}")


# ------------------------------------------------------------------ trends and sources
@router.get("/trends", dependencies=READ)
def trends_list(status: str = "active", limit: int = 100) -> dict:
    rows = db.select("trend_signals", "status = ?", (status,), "score DESC, last_checked DESC", min(500, limit))
    return {"signals": rows, "providers": state.get("providers", {}) or {},
            "last_scan": state.get("trend:last_scan"),
            "derived_metrics_approved": bool(db.get_settings().get("youtube_derived_metrics_approved"))}


@router.get("/trends/{signal_id}/history", dependencies=READ)
def trend_history(signal_id: str) -> list[dict]:
    return db.select("trend_history", "signal_id = ?", (signal_id,), "at")


@router.post("/scan", dependencies=WRITE)
def scan_now() -> dict:
    return _manual("trend_scan")


def _public_source(s: dict) -> dict:
    status = s.get("rights_status") or rights.MANUAL
    return {**s, "rights_label": rights.LABELS.get(status, status), "rights_explain": rights.EXPLAIN.get(status, "")}


@router.get("/sources", dependencies=READ)
def sources_list(status: str = "", limit: int = 200) -> list[dict]:
    where, args = ("status = ?", (status,)) if status else ("", ())
    return [_public_source(s) for s in db.select("sources", where, args, "source_score DESC, updated_at DESC",
                                                   min(1000, limit))]


def _source_or_404(source_id: str) -> dict:
    s = db.fetch("sources", source_id)
    if not s:
        raise HTTPException(404, "Source not found")
    return s


class SourceIn(BaseModel):
    url: str = ""
    path: str = ""
    title: str = ""
    rights_status: str = ""
    basis: str = ""


@router.post("/sources", dependencies=WRITE)
def add_source(body: SourceIn) -> dict:
    """Add one source by hand (a local file or a URL you may use)."""
    import hashlib

    if body.path:
        p = Path(body.path).expanduser()
        if not p.is_file() or p.suffix.lower() not in config.VIDEO_EXTENSIONS:
            raise HTTPException(400, "That is not a video file on this computer (MP4, MOV, MKV, WEBM or M4V)")
        src = {"platform": "local", "external_id": hashlib.sha1(str(p.resolve()).lower().encode()).hexdigest()[:16],
               "local_path": str(p.resolve()), "url": p.resolve().as_uri(), "title": body.title or p.stem,
               "kind": "recorded", "published_at": p.stat().st_mtime}
    elif body.url.lower().startswith(("http://", "https://", "rtmp://", "rtmps://", "srt://")):
        src = {"platform": "url", "external_id": hashlib.sha1(body.url.strip().encode()).hexdigest()[:16],
               "url": body.url.strip(), "title": body.title or body.url.strip()[:120], "kind": "recorded"}
    else:
        raise HTTPException(400, "Enter a video file path or an http(s)/rtmp/srt URL")
    existing = db.select("sources", "platform = ? AND external_id = ?", (src["platform"], src["external_id"]))
    row = existing[0] if existing else db.insert("sources", {**src, "status": "discovered"})
    if body.rights_status:
        try:
            row = rights.confirm(row["id"], body.rights_status, body.basis)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    else:
        row = rights.apply(row)
    _manual("source_scout")
    return _public_source(db.fetch("sources", row["id"]) or row)


class RightsIn(BaseModel):
    status: str
    basis: str = ""


@router.post("/sources/{source_id}/rights", dependencies=WRITE)
def confirm_rights(source_id: str, body: RightsIn) -> dict:
    _source_or_404(source_id)
    try:
        row = rights.confirm(source_id, body.status, body.basis)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _manual("source_scout")
    return _public_source(row)


class FileIn(BaseModel):
    path: str


@router.post("/sources/{source_id}/file", dependencies=WRITE)
def attach_file(source_id: str, body: FileIn) -> dict:
    """Give a platform source its original file (e.g. downloaded from YouTube Studio for your own video)."""
    src = _source_or_404(source_id)
    p = Path(body.path).expanduser()
    if not p.is_file() or p.suffix.lower() not in config.VIDEO_EXTENSIONS:
        raise HTTPException(400, "That is not a video file on this computer (MP4, MOV, MKV, WEBM or M4V)")
    db.update("sources", source_id, local_path=str(p.resolve()),
              status="eligible" if src["status"] == "needs_file" else src["status"], status_note="File added")
    state.resolve(f"file:{source_id}")
    row = rights.apply(db.fetch("sources", source_id) or src)
    _manual("source_scout")
    return _public_source(row)


@router.post("/sources/{source_id}/skip", dependencies=WRITE)
def skip_source(source_id: str) -> dict:
    src = _source_or_404(source_id)
    if src["status"] in ("ingesting", "analyzing"):
        raise HTTPException(409, "The Clip Hunter is working on it; cancel its job first")
    db.update("sources", source_id, status="skipped", status_note="Skipped by you")
    state.resolve(f"rights:{source_id}")
    state.resolve(f"file:{source_id}")
    return _public_source(db.fetch("sources", source_id) or src)


@router.post("/sources/{source_id}/hunt", dependencies=WRITE)
def hunt_now(source_id: str) -> dict:
    src = _source_or_404(source_id)
    try:
        rights.gate(src, "ingest")
    except rights.RightsBlocked as exc:
        raise HTTPException(409, str(exc)) from exc
    db.update("sources", source_id, status="queued", status_note="Started by you")
    return queue.enqueue("hunt_source", {"source_id": source_id}, priority=MANUAL_PRIORITY,
                         idem_key=f"hunt:{source_id}", ref=("source", source_id), timeout_s=6 * 3600)


# ------------------------------------------------------------------ rights rules
@router.get("/rights", dependencies=READ)
def rights_rules() -> dict:
    s = db.get_settings()
    return {"rules": rights.rules(), "statuses": [{"id": k, "label": rights.LABELS[k], "explain": rights.EXPLAIN[k],
                                                   "auto": rights.auto_allowed(k, s)} for k in rights.STATUSES]}


class RuleIn(BaseModel):
    scope: str
    value: str
    status: str
    basis: str = ""
    label: str = ""
    platform: str = ""
    evidence_url: str = ""


@router.post("/rights", dependencies=WRITE)
def add_rights_rule(body: RuleIn) -> dict:
    try:
        rule = rights.add_rule(body.scope, body.value, body.status, body.basis, body.platform, body.label,
                               body.evidence_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _manual("rights_check")
    return rule


@router.delete("/rights/{rule_id}", dependencies=WRITE)
def delete_rights_rule(rule_id: str) -> dict:
    rights.remove_rule(rule_id)
    _manual("rights_check")
    return {"ok": True}


# ------------------------------------------------------------------ feeds (watch folders, channels, streams)
class FeedIn(BaseModel):
    kind: str
    name: str = ""
    config: dict = {}
    rights_status: str = ""
    rights_basis: str = ""


RULE_SCOPE = {"watch_folder": ("folder", "path"), "stream_url": ("url_prefix", "url"),
              "youtube_channel": ("channel", "channel_id")}


@router.get("/feeds", dependencies=READ)
def feeds_list() -> list[dict]:
    return providers.feeds(enabled_only=False)


@router.post("/feeds", dependencies=WRITE)
def add_feed(body: FeedIn) -> dict:
    try:
        feed = providers.add_feed(body.kind, body.name or body.kind.replace("_", " ").title(), body.config,
                                  body.rights_status, body.rights_basis)
        if body.rights_status and body.kind in RULE_SCOPE:
            scope, key = RULE_SCOPE[body.kind]
            rights.add_rule(scope, str(body.config.get(key) or ""), body.rights_status, body.rights_basis,
                            platform="youtube" if body.kind == "youtube_channel" else "", label=feed["name"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _manual("feed_scan" if body.kind != "youtube_channel" else "trend_scan")
    return feed


class FeedPatch(BaseModel):
    enabled: bool


@router.patch("/feeds/{feed_id}", dependencies=WRITE)
def patch_feed(feed_id: str, body: FeedPatch) -> dict:
    if not db.fetch("source_feeds", feed_id):
        raise HTTPException(404, "Feed not found")
    db.update("source_feeds", feed_id, enabled=int(body.enabled))
    return db.fetch("source_feeds", feed_id) or {}


@router.delete("/feeds/{feed_id}", dependencies=WRITE)
def delete_feed(feed_id: str) -> dict:
    db.execute("DELETE FROM source_feeds WHERE id = ?", (feed_id,))
    return {"ok": True}


# ------------------------------------------------------------------ quota, GPU, workers, jobs
@router.get("/quota", dependencies=READ)
def quota_status() -> dict:
    return quota.status(db.get_settings())


@router.get("/gpu", dependencies=READ)
def gpu_status() -> dict:
    return gpu.manager.status(db.get_settings())


@router.get("/workers", dependencies=READ)
def workers() -> dict:
    rows = {r["name"]: r for r in db.select("worker_state")}
    counts = queue.counts()
    out = []
    for name, (label, kinds) in queue.WORKERS.items():
        row = rows.get(name) or {"status": "idle", "message": "Not started"}
        stale = time.time() - float(row.get("heartbeat") or 0) > 90
        out.append({"name": name, "label": label, "kinds": list(kinds), **row,
                    "status": "idle" if stale and row.get("status") == "working" else row.get("status", "idle"),
                    "stale": stale, "queue": counts.get(name, {})})
    return {"workers": out, "host": supervisor.status(), "paused": state.paused()}


@router.get("/jobs", dependencies=READ)
def jobs_list(status: str = "", worker: str = "", limit: int = 100) -> list[dict]:
    statuses = tuple(s for s in status.split(",") if s) or None
    return queue.jobs(statuses, worker, min(500, limit))


@router.get("/jobs/{job_id}/logs", dependencies=READ)
def job_logs(job_id: str) -> list[dict]:
    return queue.logs(job_id)


@router.post("/jobs/{job_id}/cancel", dependencies=WRITE)
def cancel_job(job_id: str) -> dict:
    job = queue.cancel(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/jobs/{job_id}/retry", dependencies=WRITE)
def retry_job(job_id: str) -> dict:
    job = queue.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] not in ("failed", "canceled"):
        raise HTTPException(409, "Only failed or canceled jobs can be retried")
    db.update("worker_jobs", job_id, status="queued", attempts=0, run_after=time.time(), error="", fix="",
              cancel_requested=0, message="Retry requested by you", priority=max(job["priority"], MANUAL_PRIORITY))
    queue.log_line(job_id, job["worker"], "info", "retry_requested", "Retry requested by you")
    return queue.get(job_id) or job


@router.get("/events", dependencies=READ)
def events(limit: int = 100, ref_type: str = "", ref_id: str = "") -> list[dict]:
    return state.events(min(500, limit), ref_type, ref_id)


@router.get("/actions", dependencies=READ)
def actions() -> list[dict]:
    return state.open_actions()


@router.post("/actions/{key}/dismiss", dependencies=WRITE)
def dismiss_action(key: str) -> dict:
    state.dismiss(key)
    return {"ok": True}


@router.post("/stop-all", dependencies=WRITE)
def stop_all() -> dict:
    """STOP ALL JOBS: cancel queued work, stop running jobs at their next check, and hold everything until resumed.
    Covers the autopilot workers and the app's own render and upload queues."""
    from ..jobs import worker as render_worker
    from ..publish.jobs import worker as upload_worker

    state.put("emergency_stop", True)
    out = queue.cancel_all()
    manual = render_worker.cancel_all() + upload_worker.cancel_all()
    state.event("emergency_stop", f"STOP ALL JOBS: {out['canceled']} queued job(s) canceled, {out['stopping']} "
                                  f"running job(s) stopping, {manual} render/upload job(s) stopped", "warning")
    return {**out, "manual": manual, "paused": True}


@router.post("/resume", dependencies=WRITE)
def resume() -> dict:
    state.put("emergency_stop", False)
    state.event("resumed", "Jobs allowed again after STOP ALL JOBS")
    return {"paused": False}


# ------------------------------------------------------------------ Autopilot on/off and the overview
class EnableBody(BaseModel):
    enabled: bool


@router.post("/enable", dependencies=WRITE)
def enable(body: EnableBody) -> dict:
    db.save_settings({"autopilot_enabled": body.enabled})
    state.event("autopilot_on" if body.enabled else "autopilot_off",
                "Autopilot turned on" if body.enabled else "Autopilot turned off (queued work waits)")
    if body.enabled:
        for kind in ("feed_scan", "trend_scan", "schedule_tick"):
            _manual(kind)
    return status()


def _local_time(ts: float | None, settings: dict) -> str:
    if not ts:
        return ""
    return dt.datetime.fromtimestamp(ts, scout.tz(settings)).strftime("%a %b %d, %H:%M")


@router.get("/status", dependencies=READ)
def status() -> dict:
    """Everything the Autopilot dashboard shows."""
    from ..publish.routes import _tiktok_state, _youtube_state
    from .scout import local_day, today_counts, tz

    settings = db.get_settings()
    now = time.time()
    day = local_day(settings, now)
    zone = tz(settings)
    start = dt.datetime.combine(dt.datetime.now(zone).date(), dt.time(0, 0), zone).timestamp()
    end = start + 86400
    rows = db.select("scheduled_publications", "planned_at >= ? AND planned_at < ?", (start, end))
    published = {r["clip_id"] for r in rows if r["status"] == "published"}
    scheduled = {r["clip_id"] for r in rows if r["status"] in ("awaiting_approval", "approved", "publishing")}
    processed = int(db.scalar("SELECT COUNT(*) FROM clips WHERE status = 'ready' AND created_at >= ? AND project_id IN "
                              "(SELECT id FROM projects WHERE origin IN ('autopilot', 'live'))", (start,)) or 0)
    nxt = db.select("scheduled_publications", "status IN ('approved', 'awaiting_approval', 'publishing') AND "
                                              "planned_at >= ?", (now - 600,), "planned_at", 1)
    rights_counts = {r["rights_status"]: r["n"] for r in _count("sources", "rights_status", "status != 'skipped'")}
    q = quota.status(settings)
    return {
        "enabled": bool(settings.get("autopilot_enabled")), "paused": state.paused(), "day": day,
        "timezone": settings.get("autopilot_timezone"),
        "target": {"daily": int(settings.get("autopilot_daily_target") or 15), "published": len(published),
                   "scheduled": len(scheduled - published), "processed": processed,
                   "note": "A target, not a quota: quality, rights and platform limits come first."},
        "sources_today": today_counts(settings, now), "sources_per_day": settings.get("autopilot_sources_per_day"),
        "next": ({**nxt[0], "local": _local_time(nxt[0]["planned_at"], settings)} if nxt else None),
        "queue": {"size": int(db.scalar("SELECT COUNT(*) FROM worker_jobs WHERE status IN ('queued', 'retrying', "
                                        "'waiting', 'running')") or 0), "by_worker": queue.counts()},
        "workers": workers(), "gpu": gpu.manager.status(settings),
        "platforms": {"youtube": _youtube_state(settings), "tiktok": _tiktok_state(settings, None)},
        "rights": rights_counts, "quota": {"warnings": q["warnings"], "buckets": {k: {kk: v[kk] for kk in (
            "label", "used", "budget", "remaining", "projected", "exhausted")} for k, v in q["buckets"].items()},
            "resets_at": q["resets_at"], "discovery_paused": q["discovery_paused"]},
        "actions": state.open_actions(), "events": state.events(25),
        "trends": db.select("trend_signals", "status = 'active'", (), "score DESC", 8),
        "providers": state.get("providers", {}) or {},
        "settings": {k: settings.get(k) for k in settings if k.startswith("autopilot_")},
    }


def _count(table: str, column: str, where: str = "") -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(f"SELECT {column}, COUNT(*) AS n FROM {table}" + (f" WHERE {where}" if where else "")
                            + f" GROUP BY {column}").fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ Publish Center
VIEWS = {"upcoming": "status IN ('awaiting_approval', 'approved', 'publishing', 'action_needed')",
         "published": "status = 'published'",
         "problems": "status IN ('failed', 'blocked', 'action_needed')",
         "history": "status IN ('published', 'canceled', 'replaced', 'failed', 'blocked')",
         "all": ""}


def _public_item(item: dict, settings: dict) -> dict:
    clip = db.get_clip(item["clip_id"]) or {}
    project = db.get_project(clip.get("project_id") or "") or {}
    source = db.fetch("sources", item.get("source_id") or project.get("source_id") or "") if (
        item.get("source_id") or project.get("source_id")) else None
    signal = db.fetch("trend_signals", source["signal_id"]) if source and source.get("signal_id") else None
    pub = db.get_publication(item["publication_id"]) if item.get("publication_id") else None
    version = clip.get("active_version") or ""
    from .scheduler import approval_valid

    return {**item, "local_time": _local_time(item.get("planned_at"), settings),
            "approval_valid": approval_valid(item),
            "clip": {"id": clip.get("id"), "title": clip.get("title"), "duration": clip.get("duration"),
                     "score": clip.get("score"), "category": clip.get("category"), "status": clip.get("status"),
                     "has_thumbnail": bool(clip.get("thumb_path")), "version_id": version,
                     "video_url": f"/api/versions/{version}/video" if version else f"/api/clips/{clip.get('id')}/video",
                     "thumbnail_url": f"/api/clips/{clip.get('id')}/thumbnail", "caption_text": clip.get("caption_text")},
            "source": ({"id": source["id"], "title": source.get("title"), "url": source.get("url"),
                        "platform": source.get("platform"), "channel": source.get("channel_title"),
                        "rights_status": source.get("rights_status"),
                        "rights_label": rights.LABELS.get(source.get("rights_status") or "", "")} if source else
                       {"title": project.get("name"), "rights_status": "OWNED", "rights_label": "Manual project"}),
            "trend": ({"topic": signal.get("topic"), "score": signal.get("score"), "mode": signal.get("score_mode")}
                      if signal else None),
            "clip_scores": db.fetch("clip_scores", item["clip_id"], "clip_id"),
            "quality": gate.summary(gate.report_for(clip), item["platform"]) if clip else None,
            "metadata_options": db.select("metadata_candidates", "clip_id = ? AND platform = ?",
                                          (item["clip_id"], item["platform"]), "score DESC"),
            "publication": ({k: pub.get(k) for k in ("id", "status", "url", "privacy", "requested_privacy",
                                                     "message", "error", "fix", "info", "remote_id")} if pub else None)}


@router.get("/scheduled", dependencies=READ)
def scheduled_list(view: str = "upcoming", limit: int = 200) -> dict:
    settings = db.get_settings()
    where = VIEWS.get(view, VIEWS["upcoming"])
    order = "planned_at IS NULL, planned_at ASC" if view == "upcoming" else "updated_at DESC"
    items = [_public_item(i, settings) for i in db.select("scheduled_publications", where, (), order, min(500, limit))]
    return {"items": items, "view": view, "timezone": settings.get("autopilot_timezone"),
            "auto_publish": bool(settings.get("autopilot_auto_publish")),
            "counts": {r["status"]: r["n"] for r in _count("scheduled_publications", "status")}}


def _item_or_404(item_id: str) -> dict:
    item = db.fetch("scheduled_publications", item_id)
    if not item:
        raise HTTPException(404, "Scheduled post not found")
    return item


class ApproveBody(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    privacy: str | None = None
    made_for_kids: bool | None = None
    mode: str | None = None
    allow_comment: bool = False
    allow_duet: bool = False
    allow_stitch: bool = False
    disclose: bool = False
    brand_organic: bool = False
    brand_content: bool = False
    confirm: bool = False


def _fields(item: dict, body: ApproveBody) -> dict:
    fields: dict = {k: getattr(body, k) for k in ("title", "description", "tags", "privacy")
                    if getattr(body, k) is not None}
    opts = dict(item.get("options") or {})
    if item["platform"] == "youtube":
        if body.made_for_kids is not None:
            opts["made_for_kids"] = body.made_for_kids
    else:
        opts.update({k: getattr(body, k) for k in ("allow_comment", "allow_duet", "allow_stitch", "disclose",
                                                   "brand_organic", "brand_content")})
        if not body.disclose:
            opts["brand_organic"] = opts["brand_content"] = False
        if body.mode in ("direct", "inbox"):
            opts["mode"] = body.mode
    fields["options"] = opts
    return fields


@router.post("/scheduled/{item_id}/approve", dependencies=WRITE)
def approve_item(item_id: str, body: ApproveBody) -> dict:
    """Your explicit approval of this post, exactly as shown (required by YouTube and TikTok)."""
    from ..publish import tiktok
    from ..publish.common import PublishError
    from . import packaging, scheduler

    if not body.confirm:
        raise PublishError("Approving needs your explicit confirmation.", "Review the post and press Approve.")
    item = _item_or_404(item_id)
    fields = _fields(item, body)
    creator = None
    if item["platform"] == "tiktok" and (fields["options"].get("mode") or "direct") == "direct":
        creator = tiktok.creator_info(tiktok.Token(db.get_settings()))  # read fresh before every approval
    try:
        out = scheduler.approve(item_id, fields, creator)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    clip = db.get_clip(item["clip_id"])
    heard = " ".join(packaging.clip_sentences(clip)[0]) if clip else ""  # what is said in the file to be published
    warnings = packaging.validate({"title": out["title"], "caption": out["description"]}, heard)
    return {**_public_item(out, db.get_settings()), "warnings": warnings}


class EditBody(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    privacy: str | None = None
    metadata_id: str | None = None


@router.patch("/scheduled/{item_id}", dependencies=WRITE)
def edit_item(item_id: str, body: EditBody) -> dict:
    from . import packaging, scheduler

    item = _item_or_404(item_id)
    fields = {k: getattr(body, k) for k in ("title", "description", "tags", "privacy") if getattr(body, k) is not None}
    if body.metadata_id:  # use another packaging candidate
        meta = db.fetch("metadata_candidates", body.metadata_id)
        if not meta or meta["clip_id"] != item["clip_id"] or meta["platform"] != item["platform"]:
            raise HTTPException(400, "That text option belongs to another clip or platform")
        fields.update(title=meta["title"], description=meta["description"] if item["platform"] == "youtube" else
                      meta["caption"], tags=meta["tags"] if item["platform"] == "youtube" else meta["hashtags"])
        db.update("scheduled_publications", item_id, metadata_id=meta["id"])
    try:
        out = scheduler.edit(item_id, fields)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    clip = db.get_clip(item["clip_id"]) or {}
    return {**_public_item(out, db.get_settings()),
            "warnings": packaging.validate({"title": out["title"], "caption": out["description"]},
                                           clip.get("caption_text") or "")}


class RescheduleBody(BaseModel):
    planned_at: float


@router.post("/scheduled/{item_id}/reschedule", dependencies=WRITE)
def reschedule_item(item_id: str, body: RescheduleBody) -> dict:
    from . import scheduler

    _item_or_404(item_id)
    if body.planned_at < time.time() + 60:
        raise HTTPException(400, "Choose a time in the future")
    try:
        return _public_item(scheduler.reschedule(item_id, body.planned_at), db.get_settings())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/scheduled/{item_id}/cancel", dependencies=WRITE)
def cancel_item(item_id: str) -> dict:
    from . import scheduler

    _item_or_404(item_id)
    try:
        return _public_item(scheduler.cancel(item_id), db.get_settings())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/scheduled/{item_id}/retry", dependencies=WRITE)
def retry_item(item_id: str) -> dict:
    """Try a failed or blocked post again (with a new time). It needs a valid approval to go out."""
    from .scheduler import _audit, approval_valid

    item = _item_or_404(item_id)
    if item["status"] not in ("failed", "blocked", "action_needed", "canceled"):
        raise HTTPException(409, "Only failed, blocked or canceled posts can be retried")
    valid = approval_valid({**item, "status": "approved"})
    db.update("scheduled_publications", item_id, status="approved" if valid else "awaiting_approval",
              planned_at=None, last_error="", fix="", publication_id="",
              status_note="Retrying: a new time will be chosen" if valid else "Approve it again to publish it",
              audit=_audit(item, "retry", "Retry requested by you"))
    state.resolve(f"review:{item_id}")
    _manual("schedule_tick")
    return _public_item(_item_or_404(item_id), db.get_settings())


@router.post("/scheduled/{item_id}/publish-now", dependencies=WRITE)
def publish_now(item_id: str) -> dict:
    from .scheduler import _audit, approval_valid

    item = _item_or_404(item_id)
    if not approval_valid({**item, "status": "approved"}) or item["status"] not in ("approved",):
        raise HTTPException(409, "Approve the post first")
    db.update("scheduled_publications", item_id, planned_at=time.time() + 30, status="publishing",
              status_note="Publishing now (started by you)", audit=_audit(item, "publish_now", "Publish now: by you"))
    queue.enqueue("publish", {"scheduled_id": item_id}, idem_key=f"publish:{item_id}", priority=MANUAL_PRIORITY,
                  ref=("scheduled", item_id), max_attempts=5, timeout_s=3 * 3600)
    state.resolve(f"publish:{item_id}")
    return _public_item(_item_or_404(item_id), db.get_settings())


class UrlBody(BaseModel):
    url: str


@router.post("/scheduled/{item_id}/link", dependencies=WRITE)
def link_inbox_post(item_id: str, body: UrlBody) -> dict:
    """After finishing a TikTok inbox draft in the app: link the post (its URL) to read its real statistics."""
    from ..publish.routes import LinkBody, link_tiktok_post
    from .scheduler import _audit

    item = _item_or_404(item_id)
    if not item.get("publication_id"):
        raise HTTPException(400, "Nothing was uploaded for this post yet")
    link_tiktok_post(item["publication_id"], LinkBody(url=body.url))
    db.update("scheduled_publications", item_id, status="published", status_note="Posted from the TikTok app",
              audit=_audit(item, "linked", "Linked to the post made in the TikTok app"))
    state.resolve(f"inbox:{item_id}")
    return _public_item(_item_or_404(item_id), db.get_settings())


# ------------------------------------------------------------------ learning
@router.get("/learning", dependencies=READ)
def learning_status() -> dict:
    from . import learner

    rows = db.select("learning_metrics", "dimension NOT IN ('weight', 'calibration')", (), "dimension, platform, lift DESC")
    return {"status": state.get("learning:status") or {"samples": 0, "needed": learner.MIN_SAMPLES,
                                                       "message": "Nothing learned yet."},
            "metrics": [r for r in rows if (r.get("data") or {}).get("reliable")],
            "weights": db.select("learning_metrics", "dimension = 'weight'"),
            "labels": learner.DIMENSION_LABELS, "min_samples": learner.MIN_SAMPLES}


@router.post("/learn", dependencies=WRITE)
def learn_now() -> dict:
    return _manual("learn")

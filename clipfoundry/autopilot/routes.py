"""REST endpoints for Autopilot. State-changing calls only work from ClipFoundry's own page on this computer."""
from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, db, gpu
from ..publish.common import app_request, local_only
from . import autopublish, gate, home, intake, myvideos, providers, queue, quota, rights, scout, state, verify
from .host import MANUAL_PRIORITY, supervisor

router = APIRouter(prefix="/api/autopilot")
READ = [Depends(local_only)]
WRITE = [Depends(app_request)]


def _manual(kind: str, payload: dict | None = None, ref: tuple[str, str] = ("", "")) -> dict:
    """A job the user started: runs even while Autopilot is off (but never during STOP ALL JOBS)."""
    return queue.enqueue(kind, payload or {}, priority=MANUAL_PRIORITY, ref=ref, message="Started by you",
                         idem_key=f"manual:{kind}:{ref[1]}:{int(time.time())}")


class LinkIn(BaseModel):
    url: str


@router.get("/links", dependencies=READ)
def links_list() -> list[dict]:
    return intake.links()


@router.post("/links", dependencies=WRITE)
def add_link(body: LinkIn) -> dict:
    try:
        return intake.add(body.url)
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/links/{source_id}/{operation}", dependencies=WRITE)
def link_action(source_id: str, operation: str) -> dict:
    try:
        return intake.action(source_id, operation)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


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
    if row.get("source_score") is None:  # no trend signal scores it: without a score it would never be picked
        sc = scout.score_source(row, None, db.get_settings(), time.time())
        db.update("sources", row["id"], source_score=sc["score"], expected_clips=sc["expected"],
                  components=sc["components"])
        row = db.fetch("sources", row["id"]) or row
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


class PermissionIn(BaseModel):
    allowed: bool


@router.post("/sources/{source_id}/permission", dependencies=WRITE)
def answer_permission(source_id: str, body: PermissionIn) -> dict:
    """The one-click answer to "Can you use this content?" on the Autopilot page."""
    _source_or_404(source_id)
    row = home.answer_rights(source_id, body.allowed)
    _manual("source_scout")
    return _public_source(row)


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
    verify.ensure([src])  # a channel the feed named is confirmed with the platform first
    try:
        rights.gate(db.fetch("sources", source_id) or src, "ingest")
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


# ------------------------------------------------------------------ creator agreements
class AgreementIn(BaseModel):
    creator: str
    channels: list[str] = []
    evidence: str = ""
    evidence_url: str = ""
    attribution: str = ""
    commercial: bool = True
    platforms: list[str] = []
    third_party: bool = False
    expires: str = ""                 # YYYY-MM-DD (the agreement ends at the end of that day), or empty
    media_folder: str = ""
    media_url_prefix: str = ""


@router.get("/agreements", dependencies=READ)
def agreements_list() -> list[dict]:
    return rights.agreements()


@router.post("/agreements", dependencies=WRITE)
def add_agreement(body: AgreementIn) -> dict:
    """Record an agreement with a creator once; every video it covers is used without asking again."""
    expires = None
    if body.expires.strip():
        try:
            day = dt.date.fromisoformat(body.expires.strip())
        except ValueError as exc:
            raise HTTPException(400, "The end date must look like 2026-12-31") from exc
        zone = scout.tz(db.get_settings())
        expires = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0, 0), zone).timestamp()
    folder = body.media_folder.strip()
    if folder and not Path(folder).expanduser().is_dir():
        raise HTTPException(400, "That folder does not exist on this computer")
    try:
        made = rights.add_agreement(body.creator, body.channels, body.evidence, body.evidence_url,
                                    attribution=body.attribution, commercial=body.commercial,
                                    platforms=body.platforms, third_party=body.third_party, expires_at=expires,
                                    media_folder=folder, media_url_prefix=body.media_url_prefix)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if folder:  # files the creator drops into the shared folder are found by themselves
        providers.add_feed("watch_folder", f"Files from {body.creator.strip()[:80]}", {"path": folder},
                           rights.ALLOWLISTED, made[0]["basis"])
    _manual("rights_check")
    return next(a for a in rights.agreements() if a["id"] == (made[0]["conditions"] or {}).get("agreement_id"))


@router.delete("/agreements/{agreement_id}", dependencies=WRITE)
def remove_agreement(agreement_id: str) -> dict:
    if not rights.remove_agreement(agreement_id):
        raise HTTPException(404, "Agreement not found")
    _manual("rights_check")
    return {"ok": True}


# ------------------------------------------------------------------ the activity log and automatic publishing
@router.get("/activity", dependencies=READ)
def activity(limit: int = 60) -> dict:
    """What Autopilot did with the videos it found, and why it skipped the ones it skipped."""
    return {"items": home.activity(max(1, min(200, limit))),
            "events": [e for e in state.events(40) if e["kind"] in (
                "source_selected", "source_analyzed", "source_failed", "scheduled", "auto_approved", "published",
                "quality_failed", "agreement", "auto_publish_on", "auto_publish_off", "replaced")]}


class AutoPublishIn(BaseModel):
    platform: str = "youtube"
    visibility: str = ""
    made_for_kids: bool | None = None
    daily_limit: int = 3
    start_hour: int = 9
    end_hour: int = 21
    agreed: bool = False


@router.get("/auto-publish", dependencies=READ)
def auto_publish_view() -> dict:
    settings = db.get_settings()
    from ..publish.routes import _youtube_state

    yt = _youtube_state(settings)
    return {**autopublish.view(settings), "channel": yt.get("name") or yt.get("account_id") or "",
            "timezone": settings.get("autopilot_timezone"),
            "defaults": {"daily_limit": min(3, int(settings.get("autopilot_youtube_daily_limit") or 3)),
                         "start_hour": 9, "end_hour": 21},
            "preview": autopublish.text_for("youtube", {"visibility": "VISIBILITY", "made_for_kids": False,
                                                        "daily_limit": 3, "start_hour": 9, "end_hour": 21,
                                                        "timezone": settings.get("autopilot_timezone")})}


@router.post("/auto-publish", dependencies=WRITE)
def auto_publish_on(body: AutoPublishIn) -> dict:
    """Turn on automatic publishing for a platform whose rules allow it, with exactly these settings."""
    from ..publish.routes import _youtube_state

    settings = db.get_settings()
    yt = _youtube_state(settings)
    try:
        autopublish.enable(body.platform, body.visibility, body.made_for_kids, body.daily_limit, body.start_hour,
                           body.end_hour, body.agreed, yt.get("name") or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _manual("schedule_tick")
    return auto_publish_view()


@router.delete("/auto-publish/{platform}", dependencies=WRITE)
def auto_publish_off(platform: str) -> dict:
    back = autopublish.disable(platform)
    return {**auto_publish_view(), "returned_to_review": back}


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
        job = queue.get(row.get("job_id") or "") if row.get("job_id") else None
        matching = bool(job and job["worker"] == name)
        active = bool(matching and job["status"] in queue.ACTIVE)
        progress = job.get("progress") if active and not stale else None
        out.append({"name": name, "label": label, "kinds": list(kinds), **row,
                    "status": "idle" if row.get("status") == "working" and (stale or not active) else
                    row.get("status", "idle"),
                    "stale": stale, "queue": counts.get(name, {}),
                    "job_kind": job["kind"] if matching else "", "progress": progress})
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
    state.event("emergency_stop", f"Stop all jobs: {out['canceled']} queued job(s) canceled, {out['stopping']} "
                                  f"running job(s) stopping, {manual} render/upload job(s) stopped", "warning")
    return {**out, "manual": manual, "paused": True}


@router.post("/resume", dependencies=WRITE)
def resume() -> dict:
    state.put("emergency_stop", False)
    state.event("resumed", "Jobs allowed again after Stop all jobs")
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
        myvideos.ensure()
        for kind in ("feed_scan", "trend_scan", "schedule_tick"):
            _manual(kind)
    return status()


@router.get("/my-videos", dependencies=READ)
def my_videos() -> dict:
    """Your videos folder: where it is, whether Autopilot watches it, and how many videos are in it."""
    return myvideos.view()


@router.post("/my-videos/open", dependencies=WRITE)
def my_videos_open() -> dict:
    """OPEN MY VIDEOS FOLDER: create the folder if needed, watch it, show it in File Explorer and look at it now."""
    out = myvideos.open_in_explorer()
    _manual("feed_scan")
    return out


class StartBody(BaseModel):
    topics: str | None = None


@router.post("/start", dependencies=WRITE)
def start(body: StartBody | None = None) -> dict:
    """START AUTOPILOT: turn it on with the connected accounts and the topics you chose, and start finding
    opportunities right away."""
    from ..publish.routes import _tiktok_state, _youtube_state

    settings = db.get_settings()
    home.start({"youtube": _youtube_state(settings), "tiktok": _tiktok_state(settings, None)},
               (body.topics if body else None))
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
    from .scout import day_bounds, local_day, today_counts

    settings = db.get_settings()
    now = time.time()
    day = local_day(settings, now)
    start, end = day_bounds(settings, now)  # 23 or 25 hours on daylight-saving days
    counts = today_posts(db.select("scheduled_publications", "planned_at >= ? AND planned_at < ?", (start, end)), now)
    processed = int(db.scalar("SELECT COUNT(*) FROM clips WHERE status = 'ready' AND created_at >= ? AND project_id IN "
                              "(SELECT id FROM projects WHERE origin IN ('autopilot', 'live'))", (start,)) or 0)
    nxt = db.select("scheduled_publications", "status IN ('approved', 'awaiting_approval', 'publishing') AND "
                                              "planned_at >= ?", (now - 600,), "planned_at", 1)
    rights_counts = {r["rights_status"]: r["n"] for r in _count("sources", "rights_status", "status != 'skipped'")}
    q = quota.status(settings)
    platforms = {"youtube": _youtube_state(settings), "tiktok": _tiktok_state(settings, None)}
    workers_now = workers()
    return {
        "enabled": bool(settings.get("autopilot_enabled")), "paused": state.paused(), "day": day,
        "timezone": settings.get("autopilot_timezone"),
        "target": {"daily": int(settings.get("autopilot_daily_target") or 15), **counts, "processed": processed,
                   "note": "A target, not a quota: quality, rights and platform limits come first. It counts unique "
                           "clips; one clip on YouTube and TikTok is two platform posts."},
        "sources_today": today_counts(settings, now), "sources_per_day": settings.get("autopilot_sources_per_day"),
        "next": ({**nxt[0], "local": _local_time(nxt[0]["planned_at"], settings)} if nxt else None),
        "queue": {"size": int(db.scalar("SELECT COUNT(*) FROM worker_jobs WHERE status IN ('queued', 'retrying', "
                                        "'waiting', 'running')") or 0), "by_worker": queue.counts()},
        "workers": workers_now, "gpu": gpu.manager.status(settings), "platforms": platforms,
        "rights": rights_counts, "quota": {"warnings": q["warnings"], "buckets": {k: {kk: v[kk] for kk in (
            "label", "used", "budget", "remaining", "projected", "exhausted")} for k, v in q["buckets"].items()},
            "resets_at": q["resets_at"], "discovery_paused": q["discovery_paused"]},
        "actions": state.open_actions(), "events": state.events(25),
        "trends": db.select("trend_signals", "status = 'active'", (), "score DESC", 8),
        "providers": state.get("providers", {}) or {}, "web_search": providers.web_usage(settings),
        "settings": {k: settings.get(k) for k in settings if k.startswith("autopilot_")},
        "home": home.view(settings, platforms, workers_now["host"]["alive"]),
    }


def today_posts(rows: list[dict], now: float) -> dict:
    """Today's unique clips and platform posts, published and scheduled. One clip posted to YouTube and TikTok is one
    clip and two posts. A post counts as published once it is live: a YouTube post uploaded early that goes live
    later counts as scheduled. A clip counts once, as published if any of its posts is live."""
    live = [r for r in rows if r["status"] == "published" and (r.get("planned_at") or 0) <= now]
    waiting = [r for r in rows if r["status"] in ("awaiting_approval", "approved", "publishing", "reconciling") or
               (r["status"] == "published" and (r.get("planned_at") or 0) > now)]
    published = {r["clip_id"] for r in live}
    return {"published": len(published), "scheduled": len({r["clip_id"] for r in waiting} - published),
            "published_posts": len(live), "scheduled_posts": len(waiting),
            "posts_by_platform": {p: {"published": sum(r["platform"] == p for r in live),
                                      "scheduled": sum(r["platform"] == p for r in waiting)}
                                  for p in ("youtube", "tiktok")}}


def _count(table: str, column: str, where: str = "") -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(f"SELECT {column}, COUNT(*) AS n FROM {table}" + (f" WHERE {where}" if where else "")
                            + f" GROUP BY {column}").fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ Publish Center
VIEWS = {"upcoming": "status IN ('awaiting_approval', 'approved', 'publishing', 'reconciling', 'action_needed')",
         "published": "status = 'published'",
         "yours": "(status = 'action_needed' AND json_extract(delivery, '$.audience_setup') = 'manual_pending') OR "
                  "(status = 'published' AND json_extract(delivery, '$.audience_setup') = 'awaiting_invitations')",
         "held": "status = 'blocked' AND json_extract(audience, '$.intent') = 'LEGACY_PUBLIC'",
         "problems": "status IN ('failed', 'blocked', 'action_needed', 'reconciling')",
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
    from ..publish import audience
    from .scheduler import approval_valid

    delivery_state = audience.delivery_state(item, pub)
    analytics = audience.analytics_state(item, settings)
    return {**item, "local_time": _local_time(item.get("planned_at"), settings),
            "delivery_state": delivery_state, "delivery_label": audience.DELIVERY_LABELS.get(delivery_state, ""),
            "analytics_state": analytics, "analytics_label": audience.ANALYTICS_LABELS.get(analytics, ""),
            "audience_label": _audience_label(item, settings),
            "approval_valid": approval_valid(item, quick=True),  # display only; decisions hash the file
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
                                                     "message", "error", "fix", "info", "remote_id", "delivery")}
                            if pub else None)}


def _audience_label(item: dict, settings: dict) -> str:
    """Who this post is for, in the owner's words (the footer and the post page show it)."""
    from ..publish import audience

    want = (item.get("audience") or {}).get("intent") or ""
    if want == audience.LEGACY_PUBLIC:
        return "Planned as public before this version (held)"
    if want == audience.OWNER_ONLY:
        return "Only you (staging)"
    if want == audience.LOCAL_ONLY:
        return "Kept on this PC"
    return audience.destination(item["platform"], settings)["label"]


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


@router.get("/scheduled/{item_id}", dependencies=READ)
def scheduled_item(item_id: str) -> dict:
    """One post, as the list shows it (the post page: also an old post beyond the newest the lists return)."""
    settings = db.get_settings()
    return {"item": _public_item(_item_or_404(item_id), settings), "timezone": settings.get("autopilot_timezone"),
            "auto_publish": bool(settings.get("autopilot_auto_publish"))}


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
        if body.mode in ("direct", "inbox", "manual"):
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
    if db.get_settings().get("autopilot_publishing_paused"):
        raise HTTPException(409, "Publishing is paused. Resume publishing first (Office → bottom bar).")
    db.update("scheduled_publications", item_id, planned_at=time.time() + 30, status="publishing",
              status_note="Publishing now (started by you)", audit=_audit(item, "publish_now", "Publish now: by you"))
    queue.enqueue("publish", {"scheduled_id": item_id}, idem_key=f"publish:{item_id}", priority=MANUAL_PRIORITY,
                  ref=("scheduled", item_id), max_attempts=5, timeout_s=3 * 3600, revive_canceled=True)
    state.resolve(f"publish:{item_id}")
    return _public_item(_item_or_404(item_id), db.get_settings())


class UrlBody(BaseModel):
    url: str


@router.post("/scheduled/{item_id}/link", dependencies=WRITE)
def link_inbox_post(item_id: str, body: UrlBody) -> dict:
    """After posting in the TikTok app (an inbox draft, or a ready-to-post package you posted yourself): link the
    post (its URL) so its real statistics can be read. Your link is the record that you posted it."""
    from ..publish.routes import LinkBody, link_tiktok_post
    from . import publisher
    from .scheduler import _audit, active_version_path

    item = _item_or_404(item_id)
    pub_id = item.get("publication_id") or ""
    if not pub_id:
        if item["platform"] != "tiktok" or (item.get("delivery") or {}).get("audience_setup") != "manual_pending":
            raise HTTPException(400, "Nothing was uploaded for this post yet")
        clip = db.get_clip(item["clip_id"]) or {}
        video, version = active_version_path(clip) if clip else ("", "")
        pub = db.create_publication(item["clip_id"], "tiktok", project_id=clip.get("project_id") or "", mode="manual",
                                    status="done", progress=1.0, message="Posted by you from the TikTok app",
                                    title=item["title"], description=item["description"], tags=item.get("tags") or [],
                                    requested_privacy=(item.get("audience") or {}).get("visibility") or "",
                                    video_path=video, version_id=version, options=item.get("options") or {},
                                    scheduled_id=item_id, audience=item.get("audience") or {},
                                    delivery=item.get("delivery") or {})
        pub_id = pub["id"]
        db.update("scheduled_publications", item_id, publication_id=pub_id)
    link_tiktok_post(pub_id, LinkBody(url=body.url))
    pub = db.get_publication(pub_id) or {}
    db.update("scheduled_publications", item_id, status="published", status_note="Posted from the TikTok app",
              delivery=pub.get("delivery") or item.get("delivery") or {},
              audit=_audit(item, "linked", "Linked to the post made in the TikTok app"))
    state.resolve(f"inbox:{item_id}")
    publisher.remind_audience_setup()
    return _public_item(_item_or_404(item_id), db.get_settings())


@router.post("/scheduled/{item_id}/audience-confirmed", dependencies=WRITE)
def confirm_audience(item_id: str) -> dict:
    """You shared this Private YouTube video with your selected viewers in YouTube Studio. Recorded as your word:
    YouTube's API does not report private-sharing invitations."""
    from . import publisher
    from .scheduler import _audit

    item = _item_or_404(item_id)
    if item["status"] != "published" or (item.get("delivery") or {}).get("audience_setup") != "awaiting_invitations":
        raise HTTPException(409, "Only an uploaded video waiting for your invitations can be confirmed")
    delivery = {**(item.get("delivery") or {}), "audience_setup": "user_confirmed", "audience_evidence": "user",
                "confirmed_at": time.time()}
    db.update("scheduled_publications", item_id, delivery=delivery,
              audit=_audit(item, "audience_confirmed", "You shared it privately in YouTube Studio"))
    if item.get("publication_id") and db.get_publication(item["publication_id"]):
        pub = db.get_publication(item["publication_id"]) or {}
        db.update_publication(item["publication_id"], delivery={**(pub.get("delivery") or {}), **delivery})
    publisher.remind_audience_setup()
    return _public_item(_item_or_404(item_id), db.get_settings())


class RetargetBody(BaseModel):
    ids: list[str] = []


@router.post("/scheduled/retarget", dependencies=WRITE)
def retarget_held(body: RetargetBody) -> dict:
    """Plan posts held as public (planned before this version) for your selected viewers instead. Each one needs a
    new approval; nothing goes out on its own. With no ids: every held post."""
    from ..publish import audience
    from . import scheduler

    settings = db.get_settings()
    held = db.select("scheduled_publications", VIEWS["held"], ())
    if body.ids:
        held = [i for i in held if i["id"] in set(body.ids)]
    done = 0
    for item in held:
        dest = audience.destination(item["platform"], settings)
        text = {"title": item["title"], "caption": item["description"], "description": item["description"],
                "hashtags": item.get("tags") or [], "tags": item.get("tags") or []}
        meta = scheduler._meta_fields({"platform": item["platform"], "meta": text}, settings)  # noqa: SLF001
        db.update("scheduled_publications", item["id"], status="awaiting_approval", approval={}, planned_at=None,
                  privacy=meta["privacy"], options={**(item.get("options") or {}), **meta["options"]},
                  audience=meta["audience"], last_error="", fix="",
                  status_note=f"Planned for {dest['label']} instead of public: approve it to upload it",
                  audit=scheduler._audit(item, "retarget", "Planned for your selected viewers instead of public"))  # noqa: SLF001
        done += 1
    if done:
        state.event("audience_retarget", f"{done} held post{'s' if done != 1 else ''} planned for your selected "
                                         "viewers (each needs your approval)")
    return {"retargeted": done}


class ResolveBody(BaseModel):
    published: bool
    url: str = ""


@router.post("/scheduled/{item_id}/resolve", dependencies=WRITE)
def resolve_uncertain(item_id: str, body: ResolveBody) -> dict:
    """Your answer for an upload whose outcome the platform could not confirm: it is live (with its link, so its
    statistics can be read), or it is not (it gets a new time and is uploaded again)."""
    from ..publish import youtube
    from .scheduler import _audit, approval_valid

    item = _item_or_404(item_id)
    if item["status"] != "reconciling":
        raise HTTPException(409, "Only a post whose upload could not be confirmed can be resolved this way")
    if body.published:
        m = re.search(r"(?:shorts/|watch\?v=|youtu\.be/)([\w-]{6,})", body.url or "")
        if item["platform"] == "youtube" and not m:
            raise HTTPException(400, "Paste the video's YouTube link (…/shorts/ID or …watch?v=ID)")
        if item.get("publication_id"):
            db.update_publication(item["publication_id"], status="done", remote_id=m.group(1) if m else "",
                                  url=youtube.video_url(m.group(1)) if m else body.url.strip(),
                                  message="Confirmed by you after checking")
        db.update("scheduled_publications", item_id, status="published", last_error="", fix="",
                  status_note="Published (confirmed by you)",
                  audit=_audit(item, "resolved", "You confirmed the upload is live", url=body.url.strip()))
    else:
        valid = approval_valid({**item, "status": "approved"})
        db.update("scheduled_publications", item_id, status="approved" if valid else "awaiting_approval",
                  planned_at=None, publication_id="", last_error="", fix="",
                  status_note="Not on the platform: it will be uploaded again at a new time" if valid else
                  "Not on the platform: approve it again to upload it",
                  audit=_audit(item, "resolved", "You confirmed the upload is not on the platform"))
        _manual("schedule_tick")
    state.resolve(f"review:{item_id}")
    return _public_item(_item_or_404(item_id), db.get_settings())


# ------------------------------------------------------------------ learning
@router.get("/learning", dependencies=READ)
def learning_status() -> dict:
    from . import learner

    rows = db.select("learning_metrics", "dimension NOT IN ('weight', 'calibration')", (), "dimension, platform, lift DESC")
    need = learner.minimum(db.get_settings())
    return {"status": state.get("learning:status") or {"samples": 0, "needed": need,
                                                       "message": "Nothing learned yet."},
            "metrics": [r for r in rows if (r.get("data") or {}).get("reliable")],
            "weights": db.select("learning_metrics", "dimension = 'weight'"),
            "labels": learner.DIMENSION_LABELS, "min_samples": need}


@router.post("/learn", dependencies=WRITE)
def learn_now() -> dict:
    return _manual("learn")

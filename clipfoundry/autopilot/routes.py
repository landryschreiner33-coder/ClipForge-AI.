"""REST endpoints for Autopilot. State-changing calls only work from ClipFoundry's own page on this computer."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, db, gpu
from ..publish.common import app_request, local_only
from . import providers, queue, quota, rights, state
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
    state.resolve(key)
    return {"ok": True}


@router.post("/stop-all", dependencies=WRITE)
def stop_all() -> dict:
    """STOP ALL JOBS: cancel queued work, stop running jobs at their next check, and hold everything until resumed."""
    state.put("emergency_stop", True)
    out = queue.cancel_all()
    state.event("emergency_stop", f"STOP ALL JOBS: {out['canceled']} queued job(s) canceled, {out['stopping']} "
                                  "running job(s) stopping", "warning")
    return {**out, "paused": True}


@router.post("/resume", dependencies=WRITE)
def resume() -> dict:
    state.put("emergency_stop", False)
    state.event("resumed", "Jobs allowed again after STOP ALL JOBS")
    return {"paused": False}

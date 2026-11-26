"""Settings → Processing: where Make clips projects run (Local, Hybrid or Full Cloud), the worker's address and key,
worker time and its limit, and the private test job (fullcloud/__init__.py).

The worker's address and key are set only here, from ClipForge's own page on this computer (like the cloud
computer's): no other page can point the key somewhere else.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import config, db
from ..cloud import principal
from ..publish.common import app_request, local_only
from . import client, runner, testjob, usage
from .worker_api import STAGES

router = APIRouter()

MODES = (
    {"id": "local", "name": "Local", "about": "Everything runs on this computer."},
    {"id": "hybrid", "name": "Hybrid", "about": "Clips are made on this computer; pictures and video for shorts are "
                                                "made on your cloud computer (Settings → Cloud computer)."},
    {"id": "full_cloud", "name": "Full Cloud", "about": "Make clips runs on your ClipForge worker: getting the video, "
                                                        "transcription, finding the moments, framing, captions and "
                                                        "rendering. The clips come back here. With a cloud computer "
                                                        "set up, pictures and video for shorts are made there too."},
)


def _check(settings: dict) -> dict | None:
    cfg = client.configured(settings)
    if not cfg:
        return None
    try:
        facts = client.Client(cfg["url"], cfg["key"]).info()
        return {"ok": True, "version": facts.get("version"), "whisper": facts.get("whisper") or {},
                "ai": facts.get("ai") or "", "busy": facts.get("busy"), "jobs": facts.get("jobs") or {},
                "keep_hours": facts.get("keep_hours"), "max_upload_gb": facts.get("max_upload_gb")}
    except client.WorkerError as exc:
        return {"ok": False, "why": str(exc)}


def view(check: bool = False) -> dict:
    settings = db.get_settings()
    cfg = client.configured(settings)
    ws = principal.workspace_id()
    cloud_computer = bool(settings.get("engines_remote_url"))
    ready = {"local": True, "hybrid": cloud_computer, "full_cloud": bool(cfg)}
    why = {"hybrid": "" if cloud_computer else "Set up a cloud computer first (Settings → Cloud computer).",
           "full_cloud": "" if cfg else "Add your worker's address and key below first."}
    return {
        "mode": settings.get("processing_mode") or "local",
        "modes": [{**m, "ready": ready[m["id"]], "why": why.get(m["id"], "")} for m in MODES],
        "pictures_on": "cloud computer" if settings.get("engines_comfyui") == "remote" else "this computer",
        "worker": {"url": cfg["url"] if cfg else "", "host": cfg["host"] if cfg else "",
                   "key_set": bool(settings.get("worker_key")) or db.setting_kept("worker_key"),
                   "check": _check(settings) if check else None},
        "price_per_hour": float(settings.get("worker_price_per_hour") or 0) or None,
        "month_hours": float(settings.get("worker_month_hours") or 0),
        "usage": usage.view(settings, ws),
        "stages": list(STAGES),
        "unsupported": list(runner.UNSUPPORTED),
        "test": testjob.last(ws),
    }


@router.get("/api/processing", dependencies=[Depends(local_only)])
def processing(check: bool = False) -> dict:
    return view(check)


@router.put("/api/processing", dependencies=[Depends(app_request)])
def set_processing(body: dict[str, Any]) -> dict:
    settings = db.get_settings()
    patch: dict[str, Any] = {}
    note = ""
    mode = body.get("mode")
    if mode is not None:
        if mode not in config.PROCESSING_MODES:
            raise HTTPException(422, "Choose Local, Hybrid or Full Cloud.")
        if mode == "full_cloud" and not client.configured(settings):
            raise HTTPException(409, "Add your worker's address and key first, then choose Full Cloud.")
        if mode == "full_cloud" and settings.get("engines_remote_url") and settings.get("engines_comfyui") != "remote":
            # Full Cloud is everything in the cloud: the heavy pictures and video go to the cloud computer as well
            patch["engines_comfyui"] = "remote"
            note = "Clips are made on your worker, and pictures and video on your cloud computer."
        if mode == "hybrid":
            if not settings.get("engines_remote_url"):
                raise HTTPException(409, "Set up a cloud computer first (Settings → Cloud computer), then choose "
                                         "Hybrid.")
            if settings.get("engines_comfyui") != "remote":
                patch["engines_comfyui"] = "remote"
                note = "Pictures and video are now made on your cloud computer."
        if mode == "local" and settings.get("engines_comfyui") == "remote":
            patch["engines_comfyui"] = "clipforge"
            note = "Pictures and video are now made on this computer (ClipForge's own ComfyUI)."
        patch["processing_mode"] = mode
    for k, key in (("price_per_hour", "worker_price_per_hour"), ("month_hours", "worker_month_hours")):
        if k in body:  # sent but empty or not a number (a page's NaN arrives as null): said, never skipped
            try:
                value = float(str(body[k]).replace(",", "."))
            except (TypeError, ValueError) as exc:
                raise HTTPException(422, "Enter a number, like 0.44.") from exc
            if value != value or value < 0 or value == float("inf"):
                raise HTTPException(422, "Enter a number of 0 or more, like 0.44.")
            patch[key] = value
    if patch:
        db.save_settings(patch)
        if "engines_comfyui" in patch:
            from ..engines import makers

            makers.forget_found()
    out = view()
    if note:
        out["note"] = note
    return out


@router.post("/api/processing/worker", dependencies=[Depends(app_request)])
def set_worker(body: dict[str, Any]) -> dict:
    """Keep the worker's address (and key, when one is given: "" removes it) and check it now."""
    url = str(body.get("url") or "").strip().rstrip("/")
    if url and not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    patch: dict[str, Any] = {"worker_url": url}
    before = db.get_settings()
    if body.get("key") is not None:
        patch["worker_key"] = str(body["key"]).strip()
    elif client.host(before.get("worker_url") or "") != client.host(url):
        patch["worker_key"] = ""  # a key only ever goes to the worker it was typed for
    if set(config.validate_settings(patch)) != set(patch):
        raise HTTPException(422, "ClipForge cannot keep that address or key: the address must start with https:// "
                                 "(http:// only for this computer), and the key is letters, digits and symbols.")
    if not url:
        patch["processing_mode"] = "local" if before.get("processing_mode") == "full_cloud" else \
            before.get("processing_mode") or "local"
    db.save_settings(patch)
    return view(check=bool(url))


@router.post("/api/processing/test", dependencies=[Depends(app_request)])
def run_test() -> dict:
    try:
        return {"test": testjob.start(principal.workspace_id())}
    except testjob.TestError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/api/processing/test/stop", dependencies=[Depends(app_request)])
def stop_test() -> dict:
    return {"test": testjob.stop(principal.workspace_id())}

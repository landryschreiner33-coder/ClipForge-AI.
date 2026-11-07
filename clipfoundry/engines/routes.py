"""Settings → Pictures, video, voice: what is set up, setting it up, removing it, and a quick try of each maker.

Set-up, removal and tries change this computer (downloads, a program started), so they only come from ClipForge's
own page on this computer (publish.common.app_request). The online studio does not offer local makers.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import config
from ..cloud import settings as cloud_settings
from ..publish.common import app_request, local_only
from . import EngineError

router = APIRouter()

TYPES = {".png": "image/png", ".mp4": "video/mp4", ".wav": "audio/wav", ".webm": "video/webm", ".json":
         "application/json"}


def _desktop() -> None:
    if cloud_settings.enabled():
        raise HTTPException(404, "Pictures, video and voice are made by the desktop app.")


def _fail(exc: EngineError) -> HTTPException:
    return HTTPException(409, str(exc))


@router.get("/api/engines")
def engines_view() -> dict:
    _desktop()
    from . import overview

    return {**overview(), "trial": trial_view()}


@router.post("/api/engines/setup", dependencies=[Depends(app_request)])
def engines_setup(body: dict[str, Any]) -> dict:
    _desktop()
    from . import setup

    try:
        return setup(str(body.get("what") or ""), str(body.get("model") or ""))
    except EngineError as exc:
        raise _fail(exc) from exc


@router.post("/api/engines/cancel", dependencies=[Depends(app_request)])
def engines_cancel() -> dict:
    _desktop()
    from . import cancel

    return cancel()


@router.post("/api/engines/remove", dependencies=[Depends(app_request)])
def engines_remove(body: dict[str, Any]) -> dict:
    _desktop()
    from . import remove

    try:
        return remove(str(body.get("what") or ""), str(body.get("model") or ""))
    except EngineError as exc:
        raise _fail(exc) from exc


# ------------------------------------------------------------------ a quick try (one at a time)
_trial_lock = threading.Lock()
_trial_cancel = threading.Event()
_trial: dict = {"state": "idle", "role": "", "progress": 0.0, "message": "", "file": "", "error": "", "seconds": 0.0,
                "started_at": 0.0}


def trial_view() -> dict:
    with _trial_lock:
        return dict(_trial)


def _trial_set(**fields) -> None:
    with _trial_lock:
        _trial.update(fields)


@router.post("/api/engines/try", dependencies=[Depends(app_request)])
def engines_try(body: dict[str, Any]) -> dict:
    """Make one small picture, clip or sentence with what is set up, to hear or see that it works."""
    _desktop()
    from . import make_image, make_video, speak, status

    role = str(body.get("role") or "")
    if role not in ("image", "video", "voice"):
        raise HTTPException(400, "Choose picture, video or voice.")
    words = " ".join(str(body.get("text") or "").split())[:500]
    if not words:
        words = {"image": "A cosy reading nook by a rainy window, warm lamp light, film photo",
                 "video": "Slow push-in on a steaming cup of coffee on a wooden table, morning light",
                 "voice": "Here's the thing nobody tells you about starting out: the first step is the hardest, "
                          "and it's also the one that matters most."}[role]
    st = status(role)
    if not st.get("ready"):
        raise HTTPException(409, st.get("why") or "It is not set up yet.")
    with _trial_lock:
        if _trial["state"] == "running":
            raise HTTPException(409, "A try is already running; wait for it or stop it.")
        _trial_cancel.clear()
        _trial.update(state="running", role=role, progress=0.0, message="Starting", file="", error="", seconds=0.0,
                      started_at=time.time())

    def progress(fraction: float, message: str) -> None:
        _trial_set(progress=round(max(0.0, min(1.0, float(fraction))), 3), message=message[:160])

    def run() -> None:
        started = time.time()
        try:
            if role == "image":
                path = make_image(words, width=int(body.get("width") or 768), height=int(body.get("height") or 1344),
                                  progress=progress, cancel=_trial_cancel.is_set)
            elif role == "video":
                path = make_video(words, seconds=float(body.get("seconds") or 2.0), width=480, height=832,
                                  progress=progress, cancel=_trial_cancel.is_set)
            else:
                path = speak(words, voice=str(body.get("voice") or "default"), progress=progress,
                             cancel=_trial_cancel.is_set)["path"]
            _trial_set(state="done", progress=1.0, message="Done", file=_made_url(Path(path)),
                       seconds=round(time.time() - started, 1))
        except EngineError as exc:
            stopped = _trial_cancel.is_set()
            _trial_set(state="canceled" if stopped else "failed", message="Stopped" if stopped else "Failed",
                       error="" if stopped else str(exc)[:400], seconds=round(time.time() - started, 1))
        except Exception as exc:  # noqa: BLE001 - shown to the person
            _trial_set(state="failed", message="Failed", error=f"{exc.__class__.__name__}: {str(exc)[:300]}",
                       seconds=round(time.time() - started, 1))

    threading.Thread(target=run, daemon=True, name="engines-try").start()
    return trial_view()


@router.post("/api/engines/try/cancel", dependencies=[Depends(app_request)])
def engines_try_cancel() -> dict:
    _trial_cancel.set()
    return trial_view()


def made_root() -> Path:
    return (config.data_dir() / "engines" / "made").resolve()


def _made_url(path: Path) -> str:
    rel = path.resolve().relative_to(made_root())
    return "/api/engines/made/" + rel.as_posix()


@router.get("/api/engines/made/{path:path}", dependencies=[Depends(local_only)])
def engines_made(path: str) -> FileResponse:
    """A picture, clip or voice-over the makers made (only files under <data>/engines/made)."""
    _desktop()
    base = made_root()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file() or target.suffix.lower() not in TYPES:
        raise HTTPException(404)
    return FileResponse(target, media_type=TYPES[target.suffix.lower()],
                        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

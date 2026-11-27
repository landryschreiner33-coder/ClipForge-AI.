"""The viral predictor's routes: a clip's prediction, Check a video, and how well it matched your results."""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import db
from ..cloud import principal

router = APIRouter()
_one_at_a_time = threading.Lock()  # an on-demand prediction measures a file: one at a time


def _clip(clip_id: str) -> dict:
    clip = db.get_clip(clip_id)  # as the other clip routes (api._clip_or_404)
    if not clip:
        raise HTTPException(404, "Clip not found.")
    return clip


@router.get("/api/clips/{clip_id}/prediction")
def clip_prediction(clip_id: str, version_id: str | None = None) -> dict:
    """The prediction of what would be posted for this clip (or of one version), when there is one."""
    from . import enabled, stored

    clip = _clip(clip_id)
    return {"enabled": enabled(), "prediction": stored(clip, version_id),
            "rendered": bool(clip.get("output_path")) and clip.get("status") == "ready"}


class PredictBody(BaseModel):
    version_id: str = Field(default="", max_length=40)


@router.post("/api/clips/{clip_id}/prediction")
async def predict_clip(clip_id: str, body: PredictBody) -> dict:
    """Predict a rendered clip now (clips rendered before the predictor existed, or to ask again)."""
    from . import predict_clip as run, signals

    clip = _clip(clip_id)
    version_id = body.version_id or ""

    def work() -> dict:
        if not _one_at_a_time.acquire(timeout=120):
            raise HTTPException(409, "Another prediction is still running. Try again in a moment.")
        try:
            return run(clip["id"], version_id)
        finally:
            _one_at_a_time.release()

    try:
        return {"prediction": await run_in_threadpool(work)}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(409, str(exc)) from exc
    except signals.MeasureError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/predictor/accuracy")
def accuracy() -> dict:
    """How well the predictions matched your real results (Brain → Performance)."""
    from . import learn

    return learn.view()


# ------------------------------------------------------------------ Check a video
def _check_error(exc: Exception) -> HTTPException:
    return HTTPException(getattr(exc, "status", 422), str(exc))


class CheckCreate(BaseModel):
    asset_id: str = Field(max_length=80)
    title: str = Field(default="", max_length=120)
    upload_ids: list[str] = []  # the page's uploads of the file (studio/uploads.taken)


@router.get("/api/predictor/checks")
def list_checks() -> list[dict]:
    from . import checks

    return checks.list_for(principal.workspace_id())


@router.post("/api/predictor/checks")
def add_check(body: CheckCreate) -> dict:
    from . import checks

    try:
        return checks.create(principal.workspace_id(), body.asset_id, body.title, body.upload_ids[:20])
    except checks.CheckError as exc:
        raise _check_error(exc) from exc


@router.get("/api/predictor/checks/{check_id}")
def get_check(check_id: str) -> dict:
    from . import checks

    try:
        return checks.view(checks.get(check_id, principal.workspace_id()))
    except checks.CheckError as exc:
        raise _check_error(exc) from exc


@router.post("/api/predictor/checks/{check_id}/again")
def check_again(check_id: str) -> dict:
    from . import checks

    try:
        return checks.again(check_id, principal.workspace_id())
    except checks.CheckError as exc:
        raise _check_error(exc) from exc


@router.post("/api/predictor/checks/{check_id}/cancel")
def cancel_check(check_id: str) -> dict:
    from . import checks

    try:
        return checks.cancel(check_id, principal.workspace_id())
    except checks.CheckError as exc:
        raise _check_error(exc) from exc


@router.delete("/api/predictor/checks/{check_id}")
def delete_check(check_id: str) -> dict:
    from . import checks

    try:
        return checks.delete(check_id, principal.workspace_id())
    except checks.CheckError as exc:
        raise _check_error(exc) from exc

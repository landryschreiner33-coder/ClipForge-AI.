"""The animated-shorts API (docs/clipforge/ANIMATED_SHORTS.md): make a short, change its scenes and its options.

Every change answers with the whole video (as GET /api/studio/videos/<id>), so the page shows it at once; the work
itself happens in the short's build job.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from .. import db
from ..cloud import principal
from ..studio import video_flow
from . import shorts

router = APIRouter()


def _short(video_id: str) -> dict:
    v = db.fetch("studio_projects", video_id)
    if not shorts.is_short(v) or v["workspace_id"] != principal.workspace_id():  # type: ignore[index]
        raise HTTPException(404, "Short not found")
    return v  # type: ignore[return-value]


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(409 if isinstance(exc, video_flow.Conflict) else 422, str(exc))


def _answer(video_id: str) -> dict:
    return video_flow.view(_short(video_id))


class ShortRequest(BaseModel):
    name: str = ""
    mode: str = "paste"
    script: str = ""
    topic: str = ""
    tone: str | None = None
    length: str | None = None
    audience: str | None = None
    look: str | None = None
    voice: str | None = None
    speed: float | None = None
    music: str | None = None
    captions: str | None = None
    motion: str | None = None
    review: bool | None = None


@router.get("/api/studio/shorts/options")
def short_options() -> dict:
    return shorts.options()


@router.post("/api/studio/shorts")
def make_short(body: ShortRequest) -> dict:
    p = principal.current()
    data = body.model_dump()
    try:
        v = shorts.create(p.workspace_id, p.user_id, name=data.pop("name"), options=data)
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return video_flow.view(v)


class SampleRequest(BaseModel):
    voice: str = "auto"
    speed: float = 1.0


@router.post("/api/studio/shorts/voice-sample")
def voice_sample(body: SampleRequest) -> FileResponse:
    try:
        path, note = shorts.voice_sample(body.voice, body.speed)
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    if not note:
        return FileResponse(path, media_type="audio/wav")
    # another voice stood in: this sample is sent once and not kept, and the page says what happened
    return FileResponse(path, media_type="audio/wav", headers={"X-ClipForge-Note": quote(note[:300])},
                        background=BackgroundTask(path.unlink, missing_ok=True))


class SceneChange(BaseModel):
    narration: str | None = None
    picture_prompt: str | None = None
    move: str | None = None
    picture_asset_id: str | None = None
    upload_ids: list[str] | None = None  # the page's uploads of that picture (studio/uploads.taken)
    new_picture: bool | None = None
    again: bool | None = None


@router.patch("/api/studio/shorts/{video_id}/scenes/{scene_id}")
def change_scene(video_id: str, scene_id: str, body: SceneChange) -> dict:
    try:
        shorts.update_scene(_short(video_id), scene_id, body.model_dump(exclude_none=True))
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)


class SceneAdd(BaseModel):
    after: str | None = None
    narration: str = ""
    picture_prompt: str = ""


@router.post("/api/studio/shorts/{video_id}/scenes")
def add_scene(video_id: str, body: SceneAdd) -> dict:
    try:
        shorts.add_scene(_short(video_id), body.after, body.narration, body.picture_prompt)
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)


@router.delete("/api/studio/shorts/{video_id}/scenes/{scene_id}")
def delete_scene(video_id: str, scene_id: str) -> dict:
    try:
        shorts.delete_scene(_short(video_id), scene_id)
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)


@router.post("/api/studio/shorts/{video_id}/make")
def make(video_id: str) -> dict:
    try:
        shorts.make(_short(video_id))
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)


class OptionsChange(BaseModel):
    voice: str | None = None
    speed: float | None = None
    look: str | None = None
    music: str | None = None
    captions: str | None = None
    motion: str | None = None


@router.put("/api/studio/shorts/{video_id}/options")
def change_options(video_id: str, body: OptionsChange) -> dict:
    try:
        shorts.set_options(_short(video_id), body.model_dump(exclude_none=True))
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)

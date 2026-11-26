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
from . import cast, look_examples, shorts

router = APIRouter()


def _short(video_id: str) -> dict:
    v = db.fetch("studio_projects", video_id)
    if not shorts.is_short(v) or v["workspace_id"] != principal.workspace_id():  # type: ignore[index]
        raise HTTPException(404, "Short not found")
    return v  # type: ignore[return-value]


def _bad(exc: Exception) -> HTTPException:
    status = getattr(exc, "status", None)
    return HTTPException(status if isinstance(status, int) else 409 if isinstance(exc, video_flow.Conflict) else 422,
                         str(exc))


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


@router.get("/api/studio/shorts/look-examples")
def look_examples_view() -> dict:
    return look_examples.view()


@router.post("/api/studio/shorts/look-examples")
def look_examples_make() -> dict:
    try:
        return look_examples.start(principal.workspace_id())
    except look_examples.ExampleError as exc:
        raise _bad(exc) from exc


@router.post("/api/studio/shorts/look-examples/stop")
def look_examples_stop() -> dict:
    return look_examples.stop()


@router.get("/api/studio/shorts/look-examples/{look_id}")
def look_example_file(look_id: str) -> FileResponse:
    path = look_examples.file(look_id)
    if path is None:
        raise HTTPException(404, "No example of this look yet")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


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
    hold_ms: int | None = None
    cast: list[str] | None = None     # who is in the shot; [] for nobody (to show everyone again: all_cast)
    all_cast: bool | None = None
    drift_ok: bool | None = None


@router.patch("/api/studio/shorts/{video_id}/scenes/{scene_id}")
def change_scene(video_id: str, scene_id: str, body: SceneChange) -> dict:
    data = body.model_dump(exclude_none=True)
    if data.pop("all_cast", False):
        data["cast"] = None
    try:
        shorts.update_scene(_short(video_id), scene_id, data)
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
    transition: str | None = None


@router.put("/api/studio/shorts/{video_id}/options")
def change_options(video_id: str, body: OptionsChange) -> dict:
    try:
        shorts.set_options(_short(video_id), body.model_dump(exclude_none=True))
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)


# ------------------------------------------------------------------ characters and places (makers/cast.py)
class CastFields(BaseModel):
    kind: str | None = None
    name: str | None = None
    appearance: str | None = None
    clothing: str | None = None
    colors: str | None = None
    props: str | None = None
    locked: list[str] | None = None
    refs: list[str] | None = None


def _cast_bad(exc: cast.CastError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.get("/api/studio/cast")
def cast_library() -> dict:
    return {"library": cast.library(principal.workspace_id())}


@router.post("/api/studio/cast")
def cast_library_add(body: CastFields) -> dict:
    try:
        return cast.library_add(principal.workspace_id(), body.model_dump(exclude_none=True))
    except cast.CastError as exc:
        raise _cast_bad(exc) from exc


@router.patch("/api/studio/cast/{library_id}")
def cast_library_change(library_id: str, body: CastFields) -> dict:
    try:
        return cast.library_change(principal.workspace_id(), library_id, body.model_dump(exclude_none=True))
    except cast.CastError as exc:
        raise _cast_bad(exc) from exc


@router.delete("/api/studio/cast/{library_id}")
def cast_library_delete(library_id: str) -> dict:
    try:
        cast.library_delete(principal.workspace_id(), library_id)
    except cast.CastError as exc:
        raise _cast_bad(exc) from exc
    return {"deleted": True}


class CastAdd(CastFields):
    library_id: str | None = None
    save: bool = True  # also keep a new character in the library


@router.post("/api/studio/shorts/{video_id}/cast")
def short_cast_add(video_id: str, body: CastAdd) -> dict:
    try:
        shorts.cast_add(_short(video_id), body.model_dump(exclude_none=True))
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)


@router.patch("/api/studio/shorts/{video_id}/cast/{member_id}")
def short_cast_change(video_id: str, member_id: str, body: CastFields) -> dict:
    try:
        shorts.cast_change(_short(video_id), member_id, body.model_dump(exclude_none=True))
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)


@router.delete("/api/studio/shorts/{video_id}/cast/{member_id}")
def short_cast_remove(video_id: str, member_id: str) -> dict:
    try:
        shorts.cast_remove(_short(video_id), member_id)
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)


@router.post("/api/studio/shorts/{video_id}/cast/{member_id}/library")
def short_cast_to_library(video_id: str, member_id: str) -> dict:
    try:
        shorts.cast_to_library(_short(video_id), member_id)
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)


class CastReference(BaseModel):
    asset_id: str | None = None
    upload_ids: list[str] | None = None
    scene_id: str | None = None


@router.post("/api/studio/shorts/{video_id}/cast/{member_id}/reference")
def short_cast_reference(video_id: str, member_id: str, body: CastReference) -> dict:
    try:
        shorts.cast_reference(_short(video_id), member_id, body.model_dump(exclude_none=True))
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)


class CastWords(BaseModel):
    words: str = ""
    scene_id: str | None = None


@router.post("/api/studio/shorts/{video_id}/cast/{member_id}/propose")
def short_cast_propose(video_id: str, member_id: str, body: CastWords) -> dict:
    try:
        return shorts.cast_propose(_short(video_id), member_id, body.words, body.scene_id)
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc


class CastApply(BaseModel):
    changes: dict[str, str]
    scene_id: str | None = None  # one shot; none: every shot


@router.post("/api/studio/shorts/{video_id}/cast/{member_id}/apply")
def short_cast_apply(video_id: str, member_id: str, body: CastApply) -> dict:
    try:
        done = shorts.cast_apply(_short(video_id), member_id, body.changes, body.scene_id)
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return {**_answer(video_id), "applied": done}


@router.delete("/api/studio/shorts/{video_id}/scenes/{scene_id}/overrides/{member_id}")
def short_clear_override(video_id: str, scene_id: str, member_id: str) -> dict:
    try:
        shorts.cast_clear_override(_short(video_id), scene_id, member_id)
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return _answer(video_id)

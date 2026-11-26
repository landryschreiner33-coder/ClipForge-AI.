"""The Text Stories API (makers/textstory.py) and the voice previews and favourites every maker uses
(makers/voice_styles.py). Every change answers with the whole story, so the page shows it at once."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from .. import config
from ..cloud import principal
from . import textstory, voice_styles

router = APIRouter()
BASE = "/api/studio/text-stories"


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(getattr(exc, "status", 422), str(exc))


def _story(text_story_id: str) -> dict:
    try:
        return textstory.get(text_story_id, principal.workspace_id())
    except textstory.StoryError as exc:
        raise _bad(exc) from exc


@router.get(f"{BASE}/options")
def story_options() -> dict:
    return textstory.options(principal.workspace_id())


@router.get(BASE)
def stories() -> dict:
    return {"stories": textstory.list_stories(principal.workspace_id())}


class NewStory(BaseModel):
    name: str = ""
    title: str = ""
    script: str = ""


@router.post(BASE)
def new_story(body: NewStory) -> dict:
    try:
        return textstory.view(textstory.create(principal.workspace_id(), name=body.name, title=body.title,
                                               script=body.script))
    except textstory.StoryError as exc:
        raise _bad(exc) from exc


@router.get(f"{BASE}/backgrounds")
def background_choices(text_story_id: str = "") -> dict:
    ws = principal.workspace_id()
    need = textstory.estimate_seconds(_story(text_story_id)) if text_story_id else 0.0
    return {"videos": textstory.usable_backgrounds(ws, need)}


@router.get(BASE + "/{text_story_id}")
def one_story(text_story_id: str) -> dict:
    return textstory.view(_story(text_story_id))


class StoryChange(BaseModel):
    name: str | None = None
    title: str | None = None
    script: str | None = None
    voice: dict | None = None
    pronunciations: list | None = None
    captions: dict | None = None
    backgrounds: list | None = None


@router.patch(BASE + "/{text_story_id}")
def change_story(text_story_id: str, body: StoryChange) -> dict:
    try:
        return textstory.view(textstory.update(_story(text_story_id), body.model_dump(exclude_none=True)))
    except textstory.StoryError as exc:
        raise _bad(exc) from exc


@router.delete(BASE + "/{text_story_id}")
def delete_story(text_story_id: str) -> dict:
    textstory.delete(_story(text_story_id))
    return {"deleted": True}


@router.post(BASE + "/{text_story_id}/backgrounds/auto")
def pick_backgrounds(text_story_id: str) -> dict:
    try:
        return textstory.view(textstory.auto_backgrounds(_story(text_story_id)))
    except textstory.StoryError as exc:
        raise _bad(exc) from exc


class WriteAsk(BaseModel):
    topic: str = ""
    tone: str = "drama"
    length: str = "standard"
    change: str = ""


@router.post(BASE + "/{text_story_id}/write")
def write_story(text_story_id: str, body: WriteAsk) -> dict:
    try:
        return textstory.view(textstory.start(_story(text_story_id), "write", body.model_dump()))
    except textstory.StoryError as exc:
        raise _bad(exc) from exc


@router.post(BASE + "/{text_story_id}/preview")
def preview(text_story_id: str) -> dict:
    try:
        return textstory.view(textstory.start(_story(text_story_id), "preview"))
    except textstory.StoryError as exc:
        raise _bad(exc) from exc


@router.post(BASE + "/{text_story_id}/export")
def export(text_story_id: str) -> dict:
    try:
        return textstory.view(textstory.start(_story(text_story_id), "export"))
    except textstory.StoryError as exc:
        raise _bad(exc) from exc


@router.post(BASE + "/{text_story_id}/stop")
def stop(text_story_id: str) -> dict:
    return textstory.view(textstory.stop(_story(text_story_id)))


@router.get(BASE + "/{text_story_id}/file/{what}")
def story_file(text_story_id: str, what: str, download: bool = False) -> FileResponse:
    story = _story(text_story_id)
    try:
        path = textstory.file_for(story, what)
    except textstory.StoryError as exc:
        raise _bad(exc) from exc
    name = "".join(ch for ch in textstory.display_name(story) if ch.isalnum() or ch in " -_")[:60].strip() or "story"
    return FileResponse(path, media_type="video/mp4",
                        filename=f"{name} ({what}).mp4" if download else None,
                        headers={"Cache-Control": "private, max-age=3600"})


@router.post(BASE + "/{text_story_id}/open-in-editor")
def open_in_editor(text_story_id: str) -> dict:
    from ..studio import video_flow

    p = principal.current()
    try:
        project = textstory.open_in_editor(_story(text_story_id), p.user_id)
    except textstory.StoryError as exc:
        raise _bad(exc) from exc
    except video_flow.VideoError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"video_id": project["id"]}


# ------------------------------------------------------------------ voices: previews and favourites
class VoicePreview(BaseModel):
    voice: str = "auto"
    speed: float = 1.0
    tone: float = 0.0
    text: str = ""


PREVIEW_TEXT = "So this happened last week, and I still can't believe it. Here's how the story goes."


@router.post("/api/studio/voices/preview")
def voice_preview(body: VoicePreview) -> FileResponse:
    """A few seconds of a voice at this speed and tone (with the page's own words when it sends some, at most a
    sentence or two). The usual sample sentence is kept by voice, speed and tone, so playing it again is instant; a
    sample of the page's own words (a story's first sentences) is sent once and deleted, so none of a story's text
    stays behind in voices/previews."""
    from . import voice

    own = " ".join(body.text.split())[:220]
    try:
        path, note, kept = textstory_preview(body.voice, body.speed, body.tone, own or PREVIEW_TEXT, keep=not own)
    except (voice.VoiceError, voice_styles.VoiceStyleError) as exc:
        raise HTTPException(422, str(exc)) from exc
    headers = {"X-ClipForge-Note": quote(note[:300])} if note else None
    if kept:
        return FileResponse(path, media_type="audio/wav", headers=headers)
    return FileResponse(path, media_type="audio/wav", headers=headers,
                        background=BackgroundTask(path.unlink, missing_ok=True))


def textstory_preview(voice_id: str, speed: float, tone: float, words: str, *,
                      keep: bool = True) -> tuple[Path, str, bool]:
    """(the sample, a note when another voice read it, whether the file is kept). A sample is kept only when `keep`
    and the asked voice read it; otherwise the caller sends it once and deletes it."""
    from . import local_engines, voice

    v = voice_styles.clean_voice({"voice": voice_id or "auto", "speed": speed, "tone": tone})
    chosen = v["voice"]
    if chosen == "auto":
        chosen = voice.default_voice() or "auto"
    folder = config.data_dir() / "voices" / "previews"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{textstory._hash('preview', chosen, v['speed'], v['tone'], words)}.wav"  # noqa: SLF001
    if keep and out.is_file():
        return out, "", True
    fd, name = tempfile.mkstemp(dir=folder, suffix=".part.wav")
    os.close(fd)
    tmp = Path(name)
    try:
        got = voice.speak(words, tmp, voice=chosen, speed=v["speed"])
        local_engines.discard_made(got.get("original"))  # the voice engine's own copy of the words goes
        voice_styles.shape(tmp, tmp, v["tone"])
        if got.get("fallback") or (chosen != "auto" and got.get("voice_id") and got["voice_id"] != chosen):
            return tmp, str(got.get("fallback") or "Another voice read this preview."), False
        if not keep:
            return tmp, "", False
        tmp.replace(out)
        return out, "", True
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


@router.get("/api/studio/voices/favourites")
def favourites() -> dict:
    return {"favourites": voice_styles.favourites(principal.workspace_id())}


class Favourite(BaseModel):
    scope: str
    voice: dict | None = None


@router.put("/api/studio/voices/favourites")
def set_favourite(body: Favourite) -> dict:
    ws = principal.workspace_id()
    scope = body.scope
    if scope.startswith("project:"):
        _story(scope.split(":", 1)[1])  # a project's favourite is for one of your own stories
    try:
        return {"favourites": voice_styles.set_favourite(ws, scope, body.voice)}
    except voice_styles.VoiceStyleError as exc:
        raise HTTPException(422, str(exc)) from exc

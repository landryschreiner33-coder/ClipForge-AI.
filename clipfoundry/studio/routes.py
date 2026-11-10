"""Studio REST endpoints. Every object is looked up inside the requesting workspace; ownership of IDs in the
address is also checked app-wide (cloud/ownership.py)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..cloud import principal
from . import uploads

router = APIRouter()


def _err(exc: uploads.UploadError) -> JSONResponse:
    return JSONResponse({"detail": str(exc), **exc.extra}, status_code=exc.status)


# ------------------------------------------------------------------ uploads
class UploadStart(BaseModel):
    filename: str = Field(max_length=300)
    size: int
    sha256: str = ""
    fingerprint: str = Field(default="", max_length=300)


@router.post("/api/uploads")
def start_upload(body: UploadStart):
    try:
        return uploads.start(principal.workspace_id(), body.filename, body.size, body.sha256, body.fingerprint)
    except uploads.UploadError as exc:
        return _err(exc)


def _mine(upload_id: str) -> dict:
    row = uploads.get(upload_id)
    if row["workspace_id"] != principal.workspace_id():
        raise uploads.UploadError("Upload not found.", 404)
    return row


@router.get("/api/uploads/{upload_id}")
def upload_status(upload_id: str):
    try:
        return uploads.view(_mine(upload_id))
    except uploads.UploadError as exc:
        return _err(exc)


@router.put("/api/uploads/{upload_id}")
async def upload_chunk(upload_id: str, request: Request, offset: int = 0):
    declared = int(request.headers.get("content-length") or 0)
    if declared > uploads.CHUNK_MAX:  # refuse before reading an oversized body into memory
        return JSONResponse({"detail": f"Send chunks of at most {uploads.CHUNK_MAX >> 20} MB."}, status_code=413)
    try:
        await run_in_threadpool(_mine, upload_id)
        data = bytearray()
        async for part in request.stream():
            data += part
            if len(data) > uploads.CHUNK_MAX:
                return JSONResponse({"detail": "Chunk too large."}, status_code=413)
        return await run_in_threadpool(uploads.put_chunk, upload_id, offset, bytes(data))
    except uploads.UploadError as exc:
        return _err(exc)


@router.post("/api/uploads/{upload_id}/complete")
def complete_upload(upload_id: str):
    try:
        _mine(upload_id)
        return uploads.complete(upload_id)
    except uploads.UploadError as exc:
        return _err(exc)


@router.delete("/api/uploads/{upload_id}")
def cancel_upload(upload_id: str):
    try:
        _mine(upload_id)
        uploads.cancel(upload_id)
        return {"canceled": True}
    except uploads.UploadError as exc:
        return _err(exc)


# ------------------------------------------------------------------ assets (private media)
def _asset(asset_id: str) -> dict:
    try:
        return uploads.asset(asset_id, principal.workspace_id())
    except uploads.UploadError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/api/assets/{asset_id}")
def get_asset(asset_id: str) -> dict:
    return uploads.asset_view(_asset(asset_id))


@router.get("/api/assets/{asset_id}/media")
def asset_media(asset_id: str, download: int = 0) -> FileResponse:
    a = _asset(asset_id)
    return FileResponse(a["path"], filename=a["filename"] if download else None)


@router.get("/api/assets/{asset_id}/thumbnail")
def asset_thumbnail(asset_id: str) -> FileResponse:
    a = _asset(asset_id)
    if not a.get("thumb_path") or not Path(a["thumb_path"]).is_file():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(a["thumb_path"], media_type="image/jpeg")


@router.get("/api/studio/storage")
def storage() -> dict:
    ws = principal.workspace_id()
    return {"used_bytes": uploads.storage_used(ws), "limit_bytes": uploads.storage_limit_bytes(),
            "max_upload_bytes": uploads.max_upload_bytes()}


# ------------------------------------------------------------------ capabilities and guidance
from fastapi import File, Form, UploadFile  # noqa: E402

from .. import db  # noqa: E402
from ..jobs import worker  # noqa: E402
from . import capabilities, clips_flow, guidance, prefs, reference, skills, story_review, styles  # noqa: E402


def _bad(exc: Exception, status: int = 422) -> HTTPException:
    return HTTPException(status, str(exc))


@router.get("/api/studio/capabilities")
def get_capabilities() -> dict:
    return {"modes": list(capabilities.MODES), "fields": capabilities.registry()}


class GuidanceRequest(BaseModel):
    mode: str
    style_id: str = "saved"
    choices: dict = {}
    skills_on: list[str] = []
    skills_off: list[str] = []
    title: str = ""
    reference_id: str = ""


def _snapshot(body: GuidanceRequest) -> dict:
    ws = principal.workspace_id()
    try:
        style = clips_flow._style(ws, body.style_id)  # noqa: SLF001
        enabled = skills.enabled_skills(ws)
        on = [s for s in (db.fetch("skills", i) for i in body.skills_on) if s and s["workspace_id"] == ws]
        mode = clips_flow.guidance_mode(body.mode)
        examples = reference.guidance_inputs(ws, mode, body.reference_id)
        return guidance.resolve(mode, project_choices=body.choices, style=style, project_skills=on,
                                global_skills=[s for s in enabled if s["id"] not in set(body.skills_off) and
                                               s not in on], context={"title": body.title, "caption_text": ""},
                                **examples)
    except (ValueError, styles.StyleError) as exc:
        raise _bad(exc) from exc


@router.post("/api/studio/guidance/preview")
def guidance_preview(body: GuidanceRequest) -> dict:
    """What a new project would use, before it is made ("Used from your Brain")."""
    return _snapshot(body)


@router.get("/api/studio/guidance/preview")
def guidance_preview_read(mode: str, style_id: str = "saved", choices: str = "{}", skills_on: str = "",
                          skills_off: str = "", title: str = "", reference_id: str = "") -> dict:
    """The same preview as a plain read: opening Make clips must not send a request that could change anything
    (the read-only browser checks against the owner's real app block every non-GET)."""
    import json

    try:
        parsed = json.loads(choices or "{}")
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        raise HTTPException(422, "The choices must be a JSON object.")
    ids = lambda v: [x for x in v.split(",") if x][:50]  # noqa: E731
    return _snapshot(GuidanceRequest(mode=mode, style_id=style_id, choices=parsed, skills_on=ids(skills_on),
                                     skills_off=ids(skills_off), title=title[:300],
                                     reference_id=reference_id[:40]))


# ------------------------------------------------------------------ Make clips
class ClipsRequest(BaseModel):
    asset_id: str = ""
    url: str = Field(default="", max_length=4096)  # Video link: the same flow, downloaded first
    request_id: str = Field(default="", max_length=64)
    mode: str = "highlights"
    style_id: str = "saved"
    choices: dict = {}
    skills_on: list[str] = []
    skills_off: list[str] = []
    upload: dict = {}
    reference_id: str = ""


@router.post("/api/studio/clips")
def make_clips(body: ClipsRequest) -> dict:
    """Make clips from an uploaded file (asset_id) or a supplied video link (url): one request, one flow."""
    from . import link_import

    p = principal.current()
    if bool(body.asset_id) == bool(body.url.strip()):
        raise HTTPException(422, "Choose either a video file or a video link.")
    try:
        if body.url.strip():
            project = link_import.start(p.workspace_id, p.user_id, url=body.url, request_id=body.request_id,
                                        mode=body.mode, style_id=body.style_id, choices=body.choices,
                                        skills_on=body.skills_on, skills_off=body.skills_off, upload=body.upload,
                                        reference_id=body.reference_id)
        else:
            project = clips_flow.create(p.workspace_id, p.user_id, asset_id=body.asset_id, mode=body.mode,
                                        style_id=body.style_id, choices=body.choices, skills_on=body.skills_on,
                                        skills_off=body.skills_off, upload=body.upload,
                                        reference_id=body.reference_id)
    except link_import.LinkError as exc:
        return JSONResponse({"detail": f"{exc.why} {exc.fix}", "problem": exc.view()}, status_code=422)
    except clips_flow.FlowError as exc:
        raise _bad(exc) from exc
    return {k: v for k, v in project.items() if k != "source_path"}


@router.get("/api/studio/link-check")
def link_check(url: str = "") -> dict:
    """Is this a usable video link? Answered without any network access (nothing is fetched or searched)."""
    from . import link_import

    try:
        return {"ok": True, **link_import.normalize(url[:4096])}
    except link_import.LinkError as exc:
        return {"ok": False, "problem": exc.view()}


@router.get("/api/projects/{project_id}/guidance")
def project_guidance(project_id: str) -> dict:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    snap = project.get("guidance") or {}
    return {"snapshot": snap, "frozen": bool(snap.get("schema")),
            "note": "Saved when this project was made; later changes to styles, skills or notes affect new projects."}


# ------------------------------------------------------------------ Full stories review
@router.get("/api/projects/{project_id}/stories")
def project_stories(project_id: str) -> dict:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return {"mode": project.get("clip_mode"), "split": story_review.split_of(project),
            "stories": story_review.list_for(project_id),
            "summary": (project.get("info") or {}).get("stories") or {}}


class StoryPatch(BaseModel):
    start: float | None = None
    end: float | None = None
    included: bool | None = None
    title: str | None = Field(default=None, max_length=200)
    confirm: bool = False


@router.patch("/api/stories/{story_id}")
def patch_story(story_id: str, body: StoryPatch) -> dict:
    try:
        row = story_review.patch(story_id, start_ms=None if body.start is None else round(body.start * 1000),
                                 end_ms=None if body.end is None else round(body.end * 1000), included=body.included,
                                 title=body.title, confirm=body.confirm)
    except story_review.StoryError as exc:
        raise _bad(exc) from exc
    return story_review.view(row, db.get_project(row["project_id"]) or {})


class StorySplit(BaseModel):
    story_id: str
    at: float


class StoryIds(BaseModel):
    ids: list[str] | None = None


def _own_stories(project_id: str, ids: list[str]) -> None:
    for sid in ids:
        row = db.fetch("story_proposals", sid)
        if not row or row["project_id"] != project_id:
            raise HTTPException(404, "Story not found")


@router.post("/api/projects/{project_id}/stories/split")
def split_story(project_id: str, body: StorySplit) -> dict:
    _own_stories(project_id, [body.story_id])
    try:
        story_review.split(body.story_id, round(body.at * 1000))
    except story_review.StoryError as exc:
        raise _bad(exc) from exc
    return project_stories(project_id)


@router.post("/api/projects/{project_id}/stories/merge")
def merge_stories(project_id: str, body: StoryIds) -> dict:
    _own_stories(project_id, body.ids or [])
    try:
        story_review.merge(body.ids or [])
    except story_review.StoryError as exc:
        raise _bad(exc) from exc
    return project_stories(project_id)


@router.post("/api/projects/{project_id}/stories/order")
def order_stories(project_id: str, body: StoryIds) -> dict:
    _own_stories(project_id, body.ids or [])
    try:
        story_review.reorder(project_id, body.ids or [])
    except story_review.StoryError as exc:
        raise _bad(exc) from exc
    return project_stories(project_id)


@router.post("/api/projects/{project_id}/stories/create")
def create_story_clips(project_id: str, body: StoryIds) -> dict:
    """One batch action: a clip per chosen story (all included complete stories when none are named)."""
    _own_stories(project_id, body.ids or [])
    try:
        made = story_review.create_selected(project_id, body.ids)
    except story_review.StoryError as exc:
        raise _bad(exc) from exc
    for clip in made:
        worker.submit_render(clip["id"])
    return {"created": [c["id"] for c in made], **project_stories(project_id)}


# ------------------------------------------------------------------ styles
class StyleBody(BaseModel):
    name: str = Field(max_length=200)
    values: dict = {}
    modes: list[str] = []
    make_default: bool = False


class StylePatch(BaseModel):
    revision: int
    name: str | None = Field(default=None, max_length=200)
    values: dict | None = None


@router.get("/api/studio/brain/map")
def brain_map_view() -> dict:
    """Every style, skill and example video in this workspace, and the projects whose guidance used them."""
    from . import brain_map

    return brain_map.build(principal.workspace_id())


@router.get("/api/studio/styles")
def list_styles() -> list[dict]:
    return [styles.view(r) for r in db.select("styles", "workspace_id = ?", (principal.workspace_id(),),
                                              "is_default DESC, name")]


@router.post("/api/studio/styles")
def create_style(body: StyleBody) -> dict:
    try:
        return styles.create(principal.workspace_id(), body.name, body.values, body.modes,
                             make_default=body.make_default)
    except styles.StyleError as exc:
        raise _bad(exc) from exc


@router.patch("/api/studio/styles/{style_id}")
def update_style(style_id: str, body: StylePatch) -> dict:
    try:
        return styles.update(style_id, principal.workspace_id(), expected_revision=body.revision, name=body.name,
                             values=body.values)
    except styles.Conflict as exc:
        raise _bad(exc, 409) from exc
    except styles.StyleError as exc:
        raise _bad(exc, 404 if "not found" in str(exc) else 422) from exc


@router.post("/api/studio/styles/{style_id}/default")
def default_style(style_id: str) -> dict:
    try:
        styles.get(style_id, principal.workspace_id())
    except styles.StyleError as exc:
        raise _bad(exc, 404) from exc
    styles.set_default(style_id)
    return styles.view(db.fetch("styles", style_id))  # type: ignore[arg-type]


@router.delete("/api/studio/styles/{style_id}")
def delete_style(style_id: str) -> dict:
    try:
        styles.delete(style_id, principal.workspace_id())
    except styles.StyleError as exc:
        raise _bad(exc, 404) from exc
    return {"deleted": style_id}


# ------------------------------------------------------------------ skills
def _skill(skill_id: str) -> dict:
    row = db.fetch("skills", skill_id)
    if not row or row["workspace_id"] != principal.workspace_id():
        raise HTTPException(404, "Skill not found")
    return row


@router.get("/api/studio/skills")
def list_skills() -> list[dict]:
    return [skills.view(r) for r in db.select("skills", "workspace_id = ?", (principal.workspace_id(),), "name")]


@router.get("/api/studio/skills/example")
def example_skill() -> dict:
    return {"filename": skills.EXAMPLE.name, "text": skills.EXAMPLE.read_text(encoding="utf-8")}


@router.post("/api/studio/skills/preview")
async def preview_skill(file: UploadFile = File(...)) -> dict:
    data = await file.read(skills.MAX_BYTES + 1)
    try:
        return skills.parse(file.filename or "", data)
    except skills.SkillError as exc:
        raise _bad(exc) from exc


@router.post("/api/studio/skills")
async def import_skill(file: UploadFile = File(...)) -> dict:
    """Import (switched off). The preview shows what it would change; Enable is a separate explicit step."""
    data = await file.read(skills.MAX_BYTES + 1)
    try:
        return await run_in_threadpool(skills.save, principal.workspace_id(), file.filename or "", data)
    except skills.SkillError as exc:
        raise _bad(exc) from exc


class SkillPatch(BaseModel):
    enabled: bool | None = None
    text: str | None = Field(default=None, max_length=skills.MAX_BYTES)


@router.patch("/api/studio/skills/{skill_id}")
def patch_skill(skill_id: str, body: SkillPatch) -> dict:
    row = _skill(skill_id)
    try:
        if body.text is not None:
            row = db.fetch("skills", skills.edit(skill_id, body.text)["id"])  # type: ignore[assignment]
    except skills.SkillError as exc:
        raise _bad(exc) from exc
    if body.enabled is not None:
        db.update("skills", skill_id, enabled=int(body.enabled))
    return skills.view(db.fetch("skills", skill_id) or row)


@router.get("/api/studio/skills/{skill_id}/export")
def export_skill(skill_id: str) -> JSONResponse:
    row = _skill(skill_id)
    return JSONResponse(skills.export(row), headers={
        "Content-Disposition": f'attachment; filename="{row["skill_key"]}.skill.json"'})


@router.delete("/api/studio/skills/{skill_id}")
def delete_skill(skill_id: str) -> dict:
    _skill(skill_id)
    db.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
    return {"deleted": skill_id}


# ------------------------------------------------------------------ preferences and robot names
class PrefBody(BaseModel):
    value: dict
    revision: int | None = None


def _pref_call(fn, *args):
    try:
        return fn(*args)
    except prefs.Conflict as exc:
        raise _bad(exc, 409) from exc
    except prefs.PrefError as exc:
        raise _bad(exc) from exc


@router.get("/api/preferences/appearance")
def get_appearance() -> dict:
    p = principal.current()
    return prefs.get_appearance(p.workspace_id, p.user_id)


@router.put("/api/preferences/appearance")
def put_appearance(body: PrefBody) -> dict:
    p = principal.current()
    return _pref_call(prefs.set_appearance, p.workspace_id, p.user_id, body.value, body.revision)


@router.get("/api/preferences/layout/{device}")
def get_layout(device: str) -> dict:
    p = principal.current()
    return _pref_call(prefs.get_layout, p.workspace_id, p.user_id, device)


@router.put("/api/preferences/layout/{device}")
def put_layout(device: str, body: PrefBody) -> dict:
    p = principal.current()
    return _pref_call(prefs.set_layout, p.workspace_id, p.user_id, device, body.value, body.revision)


@router.delete("/api/preferences/layout/{device}")
def reset_layout(device: str) -> dict:
    p = principal.current()
    return _pref_call(prefs.reset_layout, p.workspace_id, p.user_id, device)


@router.get("/api/robots/names")
def robot_names() -> dict:
    return prefs.robot_names(principal.workspace_id())


class RobotName(BaseModel):
    name: str = Field(max_length=400)


@router.put("/api/robots/names/{role_id}")
def rename_robot(role_id: str, body: RobotName) -> dict:
    return _pref_call(prefs.rename_robot, principal.workspace_id(), role_id, body.name)


@router.delete("/api/robots/names/{role_id}")
def reset_robot(role_id: str) -> dict:
    return _pref_call(prefs.reset_robot, principal.workspace_id(), role_id)


class ResetAll(BaseModel):
    confirm: bool = False


@router.post("/api/robots/names/reset")
def reset_all_robots(body: ResetAll) -> dict:
    """Every name back to the original. The screen asks first; the request must say it was confirmed."""
    if not body.confirm:
        raise HTTPException(422, "Confirm resetting every robot's name.")
    return prefs.reset_all_robots(principal.workspace_id())


# ------------------------------------------------------------------ one library
@router.get("/api/studio/projects")
def library(kind: str = "", q: str = "") -> list[dict]:
    """Clips projects (Highlights and Full stories), full videos and animated shorts in one list, newest first.
    `kind`: "clips", "full_video" (filmed videos) or "short" (animated shorts); empty for all."""
    ws = principal.workspace_id()
    out = []
    if kind in ("", "clips"):
        for p in db.list_projects():
            if (p.get("workspace_id") or "local") != ws:
                continue
            out.append({"id": p["id"], "kind": "clips", "mode": p.get("clip_mode") or "highlights",
                        "story_split": (p.get("options") or {}).get("story_split", "") if isinstance(
                            p.get("options"), dict) else "",
                        "name": p["name"], "status": p["status"], "stage": p.get("stage"),
                        "progress": p.get("progress"), "message": p.get("message"), "error": p.get("error"),
                        "clip_count": p.get("clip_count") or 0, "updated_at": p["updated_at"],
                        "thumbnail": f"/api/projects/{p['id']}/thumbnail" if p.get("source_path") else "",
                        "href": f"#/project/{p['id']}"})
    if kind in ("", "full_video", "short"):
        from ..makers import shorts

        for v in db.select("studio_projects", "workspace_id = ?", (ws,), "updated_at DESC"):
            short = shorts.is_short(v)
            if kind and (kind == "short") != short:
                continue  # "full_video" lists filmed videos, "short" animated shorts
            first = shorts.cover_asset(v["id"], v) if short else (v.get("asset_ids") or [""])[0]
            # only a picture that exists: a first file with no frame (audio, or not read yet) shows the plain frame
            asset = db.fetch("assets", first) if first else None
            pictured = bool(asset and asset.get("thumb_path") and Path(asset["thumb_path"]).is_file())
            draft = video_setup.is_draft(v)  # still being planned with ClipForge AI: it opens on the setup page
            out.append({"id": v["id"], "kind": "full_video", "mode": shorts.WORKFLOW if short else "full_video",
                        "name": v["name"],
                        "status": v["status"], "message": v.get("message"), "updated_at": v["updated_at"],
                        "thumbnail": f"/api/assets/{first}/thumbnail" if pictured else "",
                        "href": f"#/create/video/{v['id']}" if draft else f"#/video/{v['id']}"})
    if q:
        out = [x for x in out if q.lower() in x["name"].lower()]
    return sorted(out, key=lambda x: -x["updated_at"])


# ------------------------------------------------------------------ Make a YouTube video
from . import video_flow  # noqa: E402
from .jobs import cancel as cancel_job, enqueue  # noqa: E402


class VideoRequest(BaseModel):
    name: str = Field(default="My video", max_length=120)
    asset_ids: list[str]
    brief: dict = {}
    style_id: str = "saved"
    remember: dict = {}
    reference_id: str = ""
    script: dict | None = None  # the script the video follows (what /api/studio/scripts/parse returned)


def _video(video_id: str) -> dict:
    v = db.fetch("studio_projects", video_id)
    if not v or v["workspace_id"] != principal.workspace_id():
        raise HTTPException(404, "Video not found")
    return v


@router.post("/api/studio/videos")
def make_video(body: VideoRequest) -> dict:
    p = principal.current()
    try:
        v = video_flow.create(p.workspace_id, p.user_id, name=body.name, asset_ids=body.asset_ids, brief=body.brief,
                              style_id=body.style_id, remember=body.remember, reference_id=body.reference_id,
                              script=body.script)
    except (video_flow.VideoError, styles.StyleError) as exc:
        raise _bad(exc) from exc
    return video_flow.view(v)


@router.get("/api/studio/videos/{video_id}")
def get_video(video_id: str) -> dict:
    return video_flow.view(_video(video_id))


# ------------------------------------------------------------------ plan a YouTube video with ClipForge AI
from . import video_setup  # noqa: E402


def _setup_bad(exc: video_setup.SetupError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


class SetupStart(BaseModel):
    asset_ids: list[str]
    idea: str = Field(default="", max_length=8000)
    mode: str = ""                       # ask (questions when needed) | auto (just do it); "" = as last time
    name: str = Field(default="", max_length=120)
    style_id: str = "saved"
    reference_id: str = ""
    script: dict | None = None
    remember: dict = {}


@router.post("/api/studio/videos/setup")
def start_video_setup(body: SetupStart) -> dict:
    """A new draft video from your files and your idea: ClipForge AI answers with a plan (and maybe questions), or
    with "Just do it" the video is built at once."""
    p = principal.current()
    try:
        return video_setup.start(p.workspace_id, p.user_id, asset_ids=body.asset_ids, idea=body.idea, mode=body.mode,
                                 name=body.name, style_id=body.style_id, reference_id=body.reference_id,
                                 script=body.script, remember=body.remember)
    except video_setup.SetupError as exc:
        raise _setup_bad(exc) from exc


@router.get("/api/studio/video-setup/model")
def video_setup_model() -> dict:
    """Whether ClipForge AI has a model to plan a video with (the start page says so before anything is sent)."""
    principal.workspace_id()
    return video_setup.model_view()


@router.get("/api/studio/videos/{video_id}/setup")
def get_video_setup(video_id: str) -> dict:
    try:
        return video_setup.view(principal.workspace_id(), video_id)
    except video_setup.SetupError as exc:
        raise _setup_bad(exc) from exc


class SetupSay(BaseModel):
    text: str = Field(max_length=8000)
    question_id: str = Field(default="", max_length=40)  # the question a quick answer belongs to


@router.post("/api/studio/videos/{video_id}/setup/say")
def say_to_video_setup(video_id: str, body: SetupSay) -> dict:
    ws = principal.workspace_id()
    try:
        out = video_setup.say(ws, video_id, body.text, body.question_id)
        return {**out, "setup": video_setup.view(ws, video_id)}
    except video_setup.SetupError as exc:
        raise _setup_bad(exc) from exc


@router.patch("/api/studio/videos/{video_id}/setup")
def change_video_setup(video_id: str, body: dict) -> dict:
    """Change a draft by hand: mode, plan fields, name, style, example, remember, the files' order, the script."""
    p = principal.current()
    try:
        return video_setup.patch(p.workspace_id, p.user_id, video_id, body)
    except video_setup.SetupError as exc:
        raise _setup_bad(exc) from exc


@router.post("/api/studio/videos/{video_id}/setup/stop")
def stop_video_setup(video_id: str) -> dict:
    ws = principal.workspace_id()
    try:
        video_setup.stop(ws, video_id)
        return video_setup.view(ws, video_id)
    except video_setup.SetupError as exc:
        raise _setup_bad(exc) from exc


class SetupBuild(BaseModel):
    mode: str = ""


@router.post("/api/studio/videos/{video_id}/setup/build")
def build_video_setup(video_id: str, body: SetupBuild) -> dict:
    """Build my video: the plan drives the edit (ClipForge AI plans first when it had not yet)."""
    p = principal.current()
    try:
        out = video_setup.build(p.workspace_id, p.user_id, video_id, body.mode)
    except video_setup.SetupError as exc:
        raise _setup_bad(exc) from exc
    return {**out, **video_flow.view(_video(video_id))}


class PlanBody(BaseModel):
    base_revision: int
    plan: dict


@router.put("/api/studio/videos/{video_id}/plan")
def change_video_plan(video_id: str, body: PlanBody) -> dict:
    """After the build: change the plan and edit the video again with it, as a new version Undo takes back."""
    p = principal.current()
    try:
        out = video_setup.change_plan(p.workspace_id, p.user_id, video_id, body.base_revision, body.plan)
    except video_setup.SetupError as exc:
        raise _setup_bad(exc) from exc
    return {**out, **video_flow.view(_video(video_id))}


class VideoEdit(BaseModel):
    base_revision: int
    edit: dict


@router.post("/api/studio/videos/{video_id}/edits")
def edit_video(video_id: str, body: VideoEdit) -> dict:
    _video(video_id)
    try:
        out = video_flow.edit(video_id, body.base_revision, body.edit)
    except video_flow.Conflict as exc:
        raise _bad(exc, 409) from exc
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return {**out, **video_flow.view(_video(video_id))}


class SmartBody(BaseModel):
    base_revision: int
    choices: dict = Field(default_factory=dict)


@router.post("/api/studio/videos/{video_id}/smart")
def smart_edit_video(video_id: str, body: SmartBody) -> dict:
    """Edit it for me (again): the smart edit with these choices, as a new version made in the background."""
    _video(video_id)
    try:
        out = video_flow.smart_again(video_id, body.base_revision, body.choices)
    except video_flow.Conflict as exc:
        raise _bad(exc, 409) from exc
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return {**out, **video_flow.view(_video(video_id))}


class ScriptBody(BaseModel):
    base_revision: int
    script: dict | None = None  # None takes the script away; the cut then follows the brief again


@router.put("/api/studio/videos/{video_id}/script")
def set_video_script(video_id: str, body: ScriptBody) -> dict:
    """Give the video a script (or take it away) and cut it again to follow it, as a new version made in the
    background."""
    _video(video_id)
    try:
        out = video_flow.set_script(video_id, body.base_revision, body.script)
    except video_flow.Conflict as exc:
        raise _bad(exc, 409) from exc
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return {**out, **video_flow.view(_video(video_id))}


@router.post("/api/studio/scripts/parse")
async def parse_script(file: UploadFile | None = File(default=None), text: str = Form(default=""),
                       filename: str = Form(default="")) -> dict:
    """Read a script file (.txt, .md, .docx, .pdf, .fdx) or pasted text into numbered lines, for the Script panel
    to show and for a new video or `PUT .../script` to follow. Nothing is stored here."""
    from . import script as script_mod

    if file is not None and file.filename:
        data: bytes | str = await file.read(script_mod.MAX_BYTES + 1)
        name = file.filename
    elif text.strip():
        data, name = text, (filename.strip() or "script.txt")
    else:
        raise HTTPException(422, "Give a script file, or paste the script's text.")
    try:
        return await run_in_threadpool(script_mod.parse, name, data)
    except script_mod.ScriptError as exc:
        raise _bad(exc) from exc


@router.get("/api/studio/sound-library")
def sound_library() -> dict:
    """ClipForge's own free music and sound effects (made on this computer, free to use)."""
    from . import library

    return library.catalog()


class RevisionBody(BaseModel):
    revision: int


@router.post("/api/studio/videos/{video_id}/restore")
def restore_revision(video_id: str, body: RevisionBody) -> dict:
    """Reopen an earlier version exactly, as a new revision (nothing in between is lost)."""
    _video(video_id)
    try:
        video_flow.restore(video_id, body.revision)
    except video_flow.Conflict as exc:
        raise _bad(exc, 409) from exc
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return video_flow.view(_video(video_id))


class BaseBody(BaseModel):
    base_revision: int


@router.post("/api/studio/videos/{video_id}/undo")
def undo_edit(video_id: str, body: BaseBody) -> dict:
    """Undo the last change (saved as a new version, so a stale tab cannot overwrite it)."""
    _video(video_id)
    try:
        out = video_flow.undo(video_id, body.base_revision)
    except video_flow.Conflict as exc:
        raise _bad(exc, 409) from exc
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return {**out, **video_flow.view(_video(video_id))}


@router.post("/api/studio/videos/{video_id}/redo")
def redo_edit(video_id: str, body: BaseBody) -> dict:
    _video(video_id)
    try:
        out = video_flow.redo(video_id, body.base_revision)
    except video_flow.Conflict as exc:
        raise _bad(exc, 409) from exc
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return {**out, **video_flow.view(_video(video_id))}


class NameBody(BaseModel):
    name: str = Field(default="", max_length=60)


@router.put("/api/studio/videos/{video_id}/revisions/{revision}/name")
def name_revision(video_id: str, revision: int, body: NameBody) -> dict:
    _video(video_id)
    try:
        video_flow.name_revision(video_id, revision, body.name)
    except video_flow.VideoError as exc:
        raise _bad(exc, 404) from exc
    return video_flow.view(_video(video_id))


class MediaBody(BaseModel):
    asset_ids: list[str]


@router.post("/api/studio/videos/{video_id}/media")
def add_video_media(video_id: str, body: MediaBody) -> dict:
    """Add files to the project's media bin (also after the rough cut); place them with an insert or audio edit."""
    _video(video_id)
    try:
        out = video_flow.add_media(video_id, body.asset_ids, yours=True)
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    return {**out, **video_flow.view(_video(video_id))}


@router.post("/api/studio/videos/{video_id}/render")
def render_video(video_id: str, body: RevisionBody) -> dict:
    v = _video(video_id)
    try:
        video_flow.plan_at(video_id, body.revision)
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    job = enqueue(v["workspace_id"], "video_render", video_id, body.revision)
    return {"job": job["id"], **video_flow.view(_video(video_id))}


@router.post("/api/studio/videos/{video_id}/cancel")
def cancel_video(video_id: str) -> dict:
    v = _video(video_id)
    n = sum(cancel_job(j["id"]) for j in db.select("studio_jobs", "target_id = ? AND status IN ('queued','running')",
                                                     (video_id,)))
    if n and v["status"] == "rendering":
        db.update("studio_projects", video_id, status="ready", message="Render canceled; the plan is unchanged")
    elif v.get("workflow") == "animated_short":
        from ..makers import shorts

        # a canceled build says so itself (studio_jobs.on_stop); this also frees a short whose build was lost, so
        # the page offers Make the short again. Nothing changes when nothing is being made.
        shorts.stopped(video_id)
    return {"canceled": n, **video_flow.view(_video(video_id))}


@router.get("/api/studio/videos/{video_id}/media")
def video_media(video_id: str, kind: str = "preview", revision: int = 0, download: int = 0) -> FileResponse:
    v = _video(video_id)
    rows = db.select("studio_artifacts", "project_id = ? AND kind = ?" + (" AND revision = ?" if revision else ""),
                     (video_id, kind, revision) if revision else (video_id, kind), "revision DESC", 1)
    if not rows:
        raise HTTPException(404, "Not rendered yet")
    name = f"{v['name'][:60]} v{rows[0]['revision']}.mp4" if download else None
    return FileResponse(rows[0]["path"], media_type="video/mp4", filename=name)


@router.get("/api/studio/videos/{video_id}/export")
def video_export(video_id: str, revision: int = 0) -> JSONResponse:
    """The edit plan of one version (ClipForge's own interchange format) with its time map."""
    v = _video(video_id)
    rev = revision or v["plan_revision"]
    try:
        plan = video_flow.plan_at(video_id, rev)
    except video_flow.VideoError as exc:
        raise _bad(exc, 404) from exc
    from . import engine as engine_mod

    return JSONResponse({"format": f"clipforge.edit-plan/v{engine_mod.SCHEMA}", "revision": rev, "plan": plan,
                         "timeline": engine_mod.timeline(plan)}, headers={
        "Content-Disposition": f'attachment; filename="{video_id}-v{rev}.plan.json"'})


# ------------------------------------------------------------------ finishing in another editor (FilmCraft)
@router.get("/api/studio/filmcraft")
def filmcraft_status() -> dict:
    """Whether FilmCraft is installed on this computer (never in the online studio)."""
    from . import filmcraft

    return filmcraft.status()


class HandoffBody(BaseModel):
    revision: int = 0
    reveal: bool = False


@router.post("/api/studio/videos/{video_id}/filmcraft")
def open_in_filmcraft(video_id: str, body: HandoffBody) -> dict:
    """Write this version as a timeline with captions next to the video, then open it in FilmCraft (or, with
    `reveal`, show the folder). Nothing is uploaded; FilmCraft reads the original files where they are."""
    import shutil

    from ..cloud import settings as cloud_settings
    from . import filmcraft, interchange

    v = _video(video_id)
    if cloud_settings.enabled():
        raise HTTPException(409, filmcraft.status()["message"])
    rev = body.revision or v["plan_revision"]
    if not rev:
        raise HTTPException(409, "The rough cut is not ready yet.")
    folder = interchange.local_folder(v, rev)
    try:
        shutil.rmtree(folder, ignore_errors=True)  # a fresh copy of exactly this version
        pkg = interchange.for_video(v, rev, folder, portable=False)
        if body.reveal:
            result = {"revealed": filmcraft.reveal(folder), "opened": False, "how": "", "warnings": []}
        else:
            result = filmcraft.open_package(pkg)
    except video_flow.VideoError as exc:
        raise _bad(exc, 404) from exc
    except (interchange.HandoffError, filmcraft.FilmCraftError) as exc:
        raise _bad(exc) from exc
    return {**result, "revision": rev, "folder": str(folder), "timeline": pkg.timeline.name,
            "captions": pkg.captions.name if pkg.captions else "", "counts": pkg.built.counts,
            "not_carried": interchange.not_carried_text(pkg.built), "page": filmcraft.PAGE}


@router.get("/api/studio/videos/{video_id}/timeline.zip")
def timeline_zip(video_id: str, revision: int = 0, media: int = 1) -> FileResponse:
    """This version as a portable package for FilmCraft or another editor: the .otio timeline, .srt captions, a
    README and (unless media=0) every file it uses under media/. Built in a scratch folder removed after sending."""
    import os
    import shutil

    from starlette.background import BackgroundTask

    from . import interchange

    v = _video(video_id)
    rev = revision or v["plan_revision"]
    if not rev:
        raise HTTPException(409, "The rough cut is not ready yet.")
    work = video_flow.video_dir(video_id) / f"handoff-{os.urandom(4).hex()}"
    try:
        pkg = interchange.for_video(v, rev, work / "package", portable=True)
        if not media:
            pkg.media = {}
        out = interchange.zip_package(pkg, work / "timeline.zip")
    except video_flow.VideoError as exc:
        shutil.rmtree(work, ignore_errors=True)
        raise _bad(exc, 404) from exc
    except interchange.HandoffError as exc:
        shutil.rmtree(work, ignore_errors=True)
        raise _bad(exc) from exc
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    name = f"{interchange.safe_name(v['name'])} v{rev} timeline.zip"
    return FileResponse(out, media_type="application/zip", filename=name,
                        background=BackgroundTask(shutil.rmtree, work, True))


# ------------------------------------------------------------------ example videos (Brain)
class ReferenceCreate(BaseModel):
    asset_id: str
    title: str = Field(default="", max_length=120)
    likes: list[str] = []
    note: str = Field(default="", max_length=2000)
    ranges: list[dict] = []
    avoid: bool = False
    scope: str = "chosen"
    modes: list[str] = []
    project_only: bool = False


class ReferencePatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    likes: list[str] | None = None
    note: str | None = Field(default=None, max_length=2000)
    avoid: bool | None = None
    scope: str | None = None
    modes: list[str] | None = None
    project_only: bool | None = None
    enabled: bool | None = None


class ReferenceAgain(BaseModel):
    ranges: list[dict] | None = None


class ReferenceStyle(BaseModel):
    values: dict
    analysis_revision: int
    name: str = Field(default="", max_length=60)
    style_revision: int | None = None


def _ref_error(exc: reference.ReferenceError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.get("/api/studio/references")
def list_references(all: int = 0) -> list[dict]:  # noqa: A002 - the query parameter's name
    return reference.list_for(principal.workspace_id(), include_project_only=bool(all))


@router.post("/api/studio/references")
def add_reference(body: ReferenceCreate) -> dict:
    data = body.model_dump(exclude={"asset_id", "ranges"})
    if not data.get("title"):
        data.pop("title")
    try:
        return reference.create(principal.workspace_id(), body.asset_id, data, body.ranges or None)
    except (reference.ReferenceError, ValueError) as exc:
        raise HTTPException(getattr(exc, "status", 422), str(exc)) from exc


@router.get("/api/studio/references/{reference_id}")
def get_reference(reference_id: str) -> dict:
    try:
        return reference.view(reference.get(reference_id, principal.workspace_id()))
    except reference.ReferenceError as exc:
        raise _ref_error(exc) from exc


@router.patch("/api/studio/references/{reference_id}")
def patch_reference(reference_id: str, body: ReferencePatch) -> dict:
    try:
        return reference.update(reference_id, principal.workspace_id(),
                                {k: v for k, v in body.model_dump().items() if v is not None})
    except reference.ReferenceError as exc:
        raise _ref_error(exc) from exc


@router.post("/api/studio/references/{reference_id}/analyze")
def reanalyze_reference(reference_id: str, body: ReferenceAgain) -> dict:
    try:
        return reference.reanalyze(reference_id, principal.workspace_id(), body.ranges)
    except (reference.ReferenceError, ValueError) as exc:
        raise HTTPException(getattr(exc, "status", 422), str(exc)) from exc


@router.post("/api/studio/references/{reference_id}/cancel")
def cancel_reference(reference_id: str) -> dict:
    try:
        return reference.cancel(reference_id, principal.workspace_id())
    except reference.ReferenceError as exc:
        raise _ref_error(exc) from exc


@router.put("/api/studio/references/{reference_id}/style")
def save_reference_style(reference_id: str, body: ReferenceStyle) -> dict:
    try:
        return reference.save_style(reference_id, principal.workspace_id(), values=body.values,
                                    analysis_revision=body.analysis_revision, name=body.name,
                                    style_revision=body.style_revision)
    except reference.ReferenceError as exc:
        raise _ref_error(exc) from exc


@router.delete("/api/studio/references/{reference_id}")
def delete_reference(reference_id: str, keep_style: int = 1, delete_file: int = 0) -> dict:
    try:
        return reference.delete(reference_id, principal.workspace_id(), keep_style=bool(keep_style),
                                delete_file=bool(delete_file))
    except reference.ReferenceError as exc:
        raise _ref_error(exc) from exc


# ------------------------------------------------------------------ Find media (Media sources)
from fastapi.responses import PlainTextResponse, StreamingResponse

from . import media_sources


def _media_error(exc: media_sources.MediaError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


class MediaSearch(BaseModel):
    kind: str
    query: str = Field(max_length=200)
    providers: list[str] = []
    filters: dict = {}
    page: int = 1
    project_id: str = ""


class MediaImport(BaseModel):
    result_id: str = Field(max_length=200)
    project_id: str = ""
    basis: str = Field(default="", max_length=500)


class MediaProviderPatch(BaseModel):
    enabled: bool | None = None
    key: str | None = Field(default=None, max_length=4096)


class MediaRules(BaseModel):
    mode: str | None = None
    commercial: bool | None = None
    share_alike: bool | None = None


class CreditEdit(BaseModel):
    key: str = Field(max_length=300)
    text: str = Field(default="", max_length=600)


@router.get("/api/studio/media/providers")
def media_providers() -> list[dict]:
    return media_sources.providers_view()


@router.put("/api/studio/media/providers/{provider_id}")
def set_media_provider(provider_id: str, body: MediaProviderPatch) -> list[dict]:
    p = media_sources.PROVIDERS.get(provider_id)
    if not p:
        raise HTTPException(404, "Unknown media source.")
    patch: dict = {}
    if body.enabled is not None:
        patch[p.enabled_setting] = body.enabled
    if body.key is not None:
        if not p.key_setting:
            raise HTTPException(422, f"{p.name} does not use a key.")
        key = body.key.strip()
        if len(key) > 512 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key):
            raise HTTPException(422, "Paste only the API key, without spaces, headers or extra lines.")
        patch[p.key_setting] = key  # sealed at rest by db.save_settings; never sent back to the page
    if patch:
        db.save_settings(patch)
    return media_sources.providers_view()


@router.post("/api/studio/media/providers/{provider_id}/test")
def test_media_provider(provider_id: str) -> dict:
    try:
        return media_sources.check_provider(provider_id)
    except media_sources.MediaError as exc:
        raise _media_error(exc) from exc


@router.post("/api/studio/media/search")
def search_media(body: MediaSearch) -> dict:
    ws = principal.workspace_id()
    rules = None
    if body.project_id:
        rules = media_sources.rules_for(_video(body.project_id))
    try:
        return media_sources.search(ws, body.kind, body.query, providers=body.providers or None,
                                    filters=body.filters, page=body.page, rules=rules)
    except media_sources.MediaError as exc:
        raise _media_error(exc) from exc


@router.get("/api/studio/media/preview/{token}")
def media_preview(token: str) -> StreamingResponse:
    try:
        body, ctype = media_sources.open_preview(token, principal.workspace_id())
    except media_sources.MediaError as exc:
        raise _media_error(exc) from exc
    return StreamingResponse(body, media_type=ctype, headers={
        "Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox"})


@router.post("/api/studio/media/imports")
def import_media(body: MediaImport) -> dict:
    if body.project_id:
        _video(body.project_id)
    try:
        return media_sources.start_import(principal.workspace_id(), body.result_id, project_id=body.project_id,
                                          basis=body.basis)
    except media_sources.MediaError as exc:
        raise _media_error(exc) from exc


@router.get("/api/studio/media/imports/{import_id}")
def media_import_status(import_id: str) -> dict:
    try:
        return media_sources.get_import(import_id, principal.workspace_id())
    except media_sources.MediaError as exc:
        raise _media_error(exc) from exc


@router.post("/api/studio/media/imports/{import_id}/cancel")
def cancel_media_import(import_id: str) -> dict:
    try:
        return media_sources.cancel_import(import_id, principal.workspace_id())
    except media_sources.MediaError as exc:
        raise _media_error(exc) from exc


@router.get("/api/assets/{asset_id}/source")
def asset_source(asset_id: str) -> list[dict]:
    """Where a file came from and on what terms (empty for your own uploads)."""
    uploads.asset(asset_id, principal.workspace_id())
    rows = media_sources.provenance([asset_id], principal.workspace_id()).get(asset_id) or []
    return [media_sources.source_view(r) for r in rows]


@router.put("/api/studio/videos/{video_id}/media-rules")
def set_media_rules(video_id: str, body: MediaRules) -> dict:
    _video(video_id)
    try:
        media_sources.set_rules(video_id, body.model_dump(exclude_none=True))
    except media_sources.MediaError as exc:
        raise _media_error(exc) from exc
    return video_flow.view(_video(video_id))


@router.post("/api/studio/videos/{video_id}/supporting-media")
def find_supporting_media(video_id: str) -> dict:
    v = _video(video_id)
    try:
        return media_sources.find_for_project(video_id, v["workspace_id"])
    except media_sources.MediaError as exc:
        raise _media_error(exc) from exc


@router.get("/api/studio/videos/{video_id}/supporting-media")
def supporting_media(video_id: str) -> dict:
    _video(video_id)
    return media_sources.suggestions_view(video_id)


@router.put("/api/studio/videos/{video_id}/credits")
def edit_video_credit(video_id: str, body: CreditEdit) -> dict:
    _video(video_id)
    try:
        media_sources.edit_credit(video_id, body.key, body.text)
    except media_sources.MediaError as exc:
        raise _media_error(exc) from exc
    return video_flow.view(_video(video_id))


@router.get("/api/studio/videos/{video_id}/credits.txt")
def video_credits(video_id: str, revision: int = 0) -> PlainTextResponse:
    v = _video(video_id)
    rev = revision or v["plan_revision"]
    try:
        plan = video_flow.plan_at(video_id, rev) if rev else None
    except video_flow.VideoError as exc:
        raise HTTPException(404, str(exc)) from exc
    body = media_sources.credits_text(v, plan) or "This version uses no media from Media sources.\n"
    return PlainTextResponse(body, headers={
        "Content-Disposition": f'attachment; filename="{video_id}-v{rev}-credits.txt"'})


# ------------------------------------------------------------------ "Tell the editor what to change" (section 9)
from . import edit_requests


class ChangeRequest(BaseModel):
    text: str
    base_revision: int | None = None


def _request_error(exc: edit_requests.RequestError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.post("/api/studio/videos/{video_id}/requests")
def ask_for_change(video_id: str, body: ChangeRequest) -> dict:
    v = _video(video_id)
    try:
        return edit_requests.ask(video_id, v["workspace_id"], body.text, body.base_revision)
    except edit_requests.RequestError as exc:
        raise _request_error(exc) from exc


@router.get("/api/studio/videos/{video_id}/requests")
def change_requests(video_id: str) -> list[dict]:
    _video(video_id)
    return edit_requests.recent(video_id)


@router.get("/api/studio/requests/{request_id}")
def change_request(request_id: str) -> dict:
    try:
        return edit_requests.view(request_id, principal.workspace_id())
    except edit_requests.RequestError as exc:
        raise _request_error(exc) from exc


@router.post("/api/studio/requests/{request_id}/apply")
def apply_change_request(request_id: str) -> dict:
    try:
        return edit_requests.apply(request_id, principal.workspace_id())
    except edit_requests.RequestError as exc:
        raise _request_error(exc) from exc


@router.post("/api/studio/requests/{request_id}/cancel")
def cancel_change_request(request_id: str) -> dict:
    try:
        return edit_requests.cancel(request_id, principal.workspace_id())
    except edit_requests.RequestError as exc:
        raise _request_error(exc) from exc

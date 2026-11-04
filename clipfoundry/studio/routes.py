"""Studio REST endpoints. Every object is looked up inside the requesting workspace; ownership of IDs in the
address is also checked app-wide (cloud/ownership.py)."""
from __future__ import annotations

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
    if not a.get("thumb_path"):
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
from . import capabilities, clips_flow, guidance, prefs, skills, story_review, styles  # noqa: E402


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


def _snapshot(body: GuidanceRequest) -> dict:
    ws = principal.workspace_id()
    try:
        style = clips_flow._style(ws, body.style_id)  # noqa: SLF001
        enabled = skills.enabled_skills(ws)
        on = [s for s in (db.fetch("skills", i) for i in body.skills_on) if s and s["workspace_id"] == ws]
        return guidance.resolve(body.mode, project_choices=body.choices, style=style, project_skills=on,
                                global_skills=[s for s in enabled if s["id"] not in set(body.skills_off) and
                                               s not in on], context={"title": body.title, "caption_text": ""})
    except (ValueError, styles.StyleError) as exc:
        raise _bad(exc) from exc


@router.post("/api/studio/guidance/preview")
def guidance_preview(body: GuidanceRequest) -> dict:
    """What a new project would use, before it is made ("Used from your Brain")."""
    return _snapshot(body)


# ------------------------------------------------------------------ Make clips
class ClipsRequest(BaseModel):
    asset_id: str
    mode: str = "highlights"
    style_id: str = "saved"
    choices: dict = {}
    skills_on: list[str] = []
    skills_off: list[str] = []
    upload: dict = {}


@router.post("/api/studio/clips")
def make_clips(body: ClipsRequest) -> dict:
    p = principal.current()
    try:
        project = clips_flow.create(p.workspace_id, p.user_id, asset_id=body.asset_id, mode=body.mode,
                                    style_id=body.style_id, choices=body.choices, skills_on=body.skills_on,
                                    skills_off=body.skills_off, upload=body.upload)
    except clips_flow.FlowError as exc:
        raise _bad(exc) from exc
    return {k: v for k, v in project.items() if k != "source_path"}


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
    return {"mode": project.get("clip_mode"), "stories": story_review.list_for(project_id),
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


# ------------------------------------------------------------------ one library
@router.get("/api/studio/projects")
def library(kind: str = "", q: str = "") -> list[dict]:
    """Clips projects (Highlights and Full stories) and full videos in one list, newest first."""
    ws = principal.workspace_id()
    out = []
    if kind in ("", "clips"):
        for p in db.list_projects():
            if (p.get("workspace_id") or "local") != ws:
                continue
            out.append({"id": p["id"], "kind": "clips", "mode": p.get("clip_mode") or "highlights",
                        "name": p["name"], "status": p["status"], "stage": p.get("stage"),
                        "progress": p.get("progress"), "message": p.get("message"), "error": p.get("error"),
                        "clip_count": p.get("clip_count") or 0, "updated_at": p["updated_at"],
                        "thumbnail": f"/api/projects/{p['id']}/thumbnail", "href": f"#/project/{p['id']}"})
    if kind in ("", "full_video"):
        for v in db.select("studio_projects", "workspace_id = ?", (ws,), "updated_at DESC"):
            first = (v.get("asset_ids") or [""])[0]
            out.append({"id": v["id"], "kind": "full_video", "mode": "full_video", "name": v["name"],
                        "status": v["status"], "message": v.get("message"), "updated_at": v["updated_at"],
                        "thumbnail": f"/api/assets/{first}/thumbnail" if first else "", "href": f"#/video/{v['id']}"})
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
                              style_id=body.style_id, remember=body.remember)
    except (video_flow.VideoError, styles.StyleError) as exc:
        raise _bad(exc) from exc
    return video_flow.view(v)


@router.get("/api/studio/videos/{video_id}")
def get_video(video_id: str) -> dict:
    return video_flow.view(_video(video_id))


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


class RevisionBody(BaseModel):
    revision: int


@router.post("/api/studio/videos/{video_id}/restore")
def restore_revision(video_id: str, body: RevisionBody) -> dict:
    """Reopen an earlier version exactly, as a new revision (nothing in between is lost)."""
    v = _video(video_id)
    try:
        plan = video_flow.plan_at(video_id, body.revision)
        rev = video_flow.save_revision(video_id, plan, f"Back to version {body.revision}", v["plan_revision"])
    except video_flow.VideoError as exc:
        raise _bad(exc) from exc
    enqueue(v["workspace_id"], "video_preview", video_id, rev)
    return video_flow.view(_video(video_id))


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

    return JSONResponse({"format": "clipforge.edit-plan/v1", "revision": rev, "plan": plan,
                         "timeline": engine_mod.timeline(plan)}, headers={
        "Content-Disposition": f'attachment; filename="{video_id}-v{rev}.plan.json"'})

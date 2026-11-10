"""FastAPI application: REST API + the built React UI."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, config, db, embedder, phone, taste
from .asyncio_windows import disconnect_cleanup
from .jobs import worker
from .pipeline import cleanup, cuda, export, llm, postpack, render, transcribe, versions
from .pipeline.common import read_json
from .pipeline.ffmpeg_utils import FFmpegError, find_binary, nvenc_available, videotoolbox_available
from .pipeline.process import load_words, project_dir, version_dir
from .publish import jobs as publish_jobs
from .publish import connection_routes
from .studio import local_routes, project_delete, routes as studio_routes
from .craft import routes as craft_routes
from .engines import routes as engine_routes
from .makers import routes as maker_routes
from .publish import routes as publish_routes
from .publish.common import PublishError
from .autopilot import host as autopilot_host
from .autopilot import brain_routes, knowledge_routes
from .brain import routes as memory_routes
from .autopilot import routes as autopilot_routes
from .office import integrations as integration_routes
from .office import routes as office_routes
from .cloud import auth_routes, ownership, principal
from .cloud import settings as cloud_settings
from .cloud.middleware import CloudGuard


def _cloud_startup() -> None:
    """Cloud mode refuses to start while any protection is missing: no unauthenticated or unencrypted fallback."""
    if not cloud_settings.enabled():
        return
    cloud_settings.reset()
    problems = cloud_settings.problems()
    if problems:
        raise RuntimeError("ClipForge cloud mode cannot start safely:\n- " + "\n- ".join(problems))

@asynccontextmanager
async def lifespan(_: FastAPI):
    with disconnect_cleanup():
        _cloud_startup()
        db.init()
        if cloud_settings.enabled():
            from .cloud import identity

            identity.ensure_primary_workspace()
        _youtube_retention()
        worker.resume(db.interrupted_work())
        worker.start()
        from .studio import edit_requests, jobs as studio_jobs, link_import, media_sources, reference, video_flow  # noqa: F401
        from .makers import shorts  # noqa: F401 - the short_build job handler
        from .brain import chat as brain_chat

        studio_jobs.recover()  # builds, renders and link downloads that were waiting or running continue
        edit_requests.recover()  # an AI request cut off by the restart is reported, never sent again silently
        brain_chat.recover()  # a chat answer cut off by the restart is reported the same way
        link_import.clean_abandoned()  # partial downloads of canceled or failed links
        project_delete.finish_later()  # files of deleted projects that were open in another program last time
        publish_jobs.worker.start()
        publish_jobs.worker.resume_waiting()  # uploads waiting for the time a platform asked for
        autopilot_host.supervisor.start()  # durable autopilot workers (own process by default)
        if not cloud_settings.enabled():  # the phone listener is a desktop feature; cloud has its own sign-in
            phone.manager.restore()
        if not cloud_settings.enabled() and os.environ.get("CLIPFOUNDRY_WORKERS", "").lower() != "off":
            from .craft import apps as craft_apps

            craft_apps.auto_install()  # FilmCraft and EffectCraft, fetched once in the background (Settings: off)
        try:
            yield
        finally:
            phone.manager.stop()
            autopilot_host.supervisor.stop()
            from . import builtin_ai
            from .craft import runner as craft_runner

            craft_runner.stop_all(closing=False)  # FilmCraft/EffectCraft renders stop with the server
            builtin_ai.shutdown()  # the engine's memory goes back to the computer
            from . import engines

            engines.shutdown()  # ClipForge's ComfyUI stops; the voice's memory is freed


def _youtube_retention() -> None:
    """YouTube's 30-day storage rule applies whether or not Autopilot runs: its hourly maintenance only runs while
    Autopilot is on, so the same clean-up also runs at every start."""
    from .autopilot import scout

    try:
        scout.youtube_retention()
    except Exception:  # noqa: BLE001 - a failed clean-up must not stop the app; maintenance tries again
        logging.getLogger(__name__).exception("YouTube data clean-up at start failed")


# Every route checks that the objects named in its address belong to the requesting workspace (cloud/ownership.py).
app = FastAPI(title=config.APP_NAME, version=__version__, lifespan=lifespan,
              dependencies=[Depends(ownership.check)])
app.add_middleware(CloudGuard)  # cloud mode only: host check, sign-in, CSRF, rate limits, security headers
app.include_router(auth_routes.router)
app.include_router(publish_routes.router)  # before the UI catch-all route below
app.include_router(connection_routes.router)
app.include_router(studio_routes.router)
app.include_router(local_routes.router)  # desktop: files used where they are, and background preparation
app.include_router(project_delete.router)  # what deleting a project does, and deleting a full video
app.include_router(craft_routes.router)  # editing apps (before the UI catch-all route)
app.include_router(engine_routes.router)  # local makers: pictures, video, voice (before the UI catch-all)
app.include_router(maker_routes.router)  # Make → Animated short
app.include_router(autopilot_routes.router)
app.include_router(office_routes.router)
app.include_router(brain_routes.router)
app.include_router(knowledge_routes.router)
app.include_router(memory_routes.router)  # ClipForge AI's memories
app.include_router(memory_routes.chats)  # ClipForge AI's chat
app.include_router(integration_routes.router)
app.include_router(phone.router)


# ------------------------------------------------------------------ helpers
def _project_or_404(project_id: str) -> dict:
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def _clip_or_404(clip_id: str) -> dict:
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(404, "Clip not found")
    return c


def _public_project(p: dict) -> dict:
    out = {k: v for k, v in p.items() if k not in {"source_path"}}
    out["has_thumbnail"] = (Path(p["source_path"]).parent / "thumb.jpg").exists() if p.get("source_path") else False
    if (p.get("info") or {}).get("link"):  # made from a supplied video link
        from .studio import link_import

        out["link_import"] = link_import.view(p)
    return out


def _public_clip(c: dict) -> dict:
    out = {k: v for k, v in c.items() if k not in {"output_path", "thumb_path"}}
    out["has_video"] = bool(c.get("output_path")) and Path(c["output_path"]).exists()
    out["has_thumbnail"] = bool(c.get("thumb_path")) and Path(c["thumb_path"]).exists()
    out["version"] = int(c.get("updated_at", 0))
    return out


def _clean_options(raw: dict) -> dict:
    allowed = {"clip_count", "min_duration", "max_duration", "target_duration", "caption_style", "tracking",
               "layout", "silence", "auto_zoom", "hook_overlay", "caption_position", "highlight_words",
               "remove_fillers", "caption_emphasis"}
    clean = config.validate_settings({k: v for k, v in raw.items() if k in allowed})
    return clean


# ------------------------------------------------------------------ system
@app.get("/api/desktop-status")
def desktop_status() -> dict:
    """Cheap native-window readiness probe; the launch nonce is not an API credential."""
    return {"version": __version__, "session": os.environ.get("CLIPFOUNDRY_DESKTOP_SESSION", "")}


@app.get("/api/health")
def health() -> dict:
    settings = db.get_settings()
    ffmpeg = find_binary("ffmpeg", settings.get("ffmpeg_path", ""))
    ffprobe = find_binary("ffprobe", settings.get("ffmpeg_path", ""))
    status = cuda.probe()
    plan = transcribe.whisper_plan(settings, status)
    return {
        "version": __version__,
        "platform": sys.platform,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "nvenc": nvenc_available() if ffmpeg else False,
        "videotoolbox": videotoolbox_available() if ffmpeg else False,
        "cuda": status["devices"] > 0,
        "gpu": {"name": plan["gpu"], "vram_mb": plan["vram_mb"], "libs_ok": status["libs_ok"],
                "libraries": status["libraries"]},
        "whisper_installed": transcribe.whisper_installed(),
        "whisper": {"model": plan["model"], "device": plan["device"], "compute_type": plan["compute_type"],
                    "cached": transcribe.model_cached(plan["model"]), "mode": plan["mode"], "reason": plan["reason"],
                    "problem": plan["problem"], "fix": plan["fix"], "last_run": transcribe.last_run or None},
        "ai_provider": llm.provider_label(settings),
        "data_dir": str(config.data_dir()),
        "busy": worker.current is not None,
        "queue": worker.q.qsize(),
    }


@app.get("/api/settings")
def get_settings() -> dict:
    s = db.get_settings()
    for k in config.SECRET_KEYS:
        s[k] = "********" if s.get(k) else ""
    return s


@app.put("/api/settings")
def put_settings(patch: dict[str, Any]) -> dict:
    patch = {k: v for k, v in patch.items() if not (k in config.SECRET_KEYS and v == "********")
             and k not in config.ACTION_ONLY_KEYS}
    for key in config.SEARCH_API_KEYS & patch.keys():
        value = patch[key]
        if not isinstance(value, str):
            raise HTTPException(422, "A search API key must be text copied from its provider dashboard.")
        value = value.strip()
        if len(value) > 4096 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise HTTPException(422, "Paste only the search API key, without spaces, headers or extra lines.")
        patch[key] = value
    db.save_settings(patch)
    return get_settings()


@app.post("/api/ai/check")
def ai_check() -> dict:
    return llm.check_provider(db.get_settings())


@app.get("/api/ai/setup")
def ai_setup_view() -> dict:
    """ClipForge AI's ready-made model choices, Ollama's state on this computer and any download or import running."""
    from . import ai_setup

    s = db.get_settings()
    try:
        gpus = cuda.probe().get("gpus") or []
        vram = int((gpus[0] if gpus else {}).get("vram_mb") or 0)
    except Exception:  # noqa: BLE001 - only a hint for the recommended model
        vram = 0
    from . import builtin_ai

    return {**ai_setup.presets(), "ollama": ai_setup.ollama_status(s.get("ollama_url") or ""),
            "task": ai_setup.task(), "provider": s.get("ai_provider", "heuristic"),
            "label": llm.provider_label(s), "recommended": ai_setup.recommended_model(vram, sys.platform == "darwin"),
            "builtin": builtin_ai.status(s)}


def _builtin_ready(level: str) -> None:
    """When the built-in model finishes downloading, it becomes ClipForge AI's model unless you already chose another one."""
    s = db.get_settings()
    patch: dict[str, Any] = {"builtin_ai_level": level}
    if s.get("ai_provider", "heuristic") in ("heuristic", "builtin"):
        patch["ai_provider"] = "builtin"
    db.save_settings(patch)


@app.get("/api/ai/meaning")
def ai_meaning_view() -> dict:
    """The meaning model (embedder.py): ready, on, downloading, or why not."""
    return embedder.status(db.get_settings())


@app.post("/api/ai/meaning/install")
def ai_meaning_install() -> dict:
    try:
        embedder.install()
    except embedder.MeaningError as exc:
        raise HTTPException(403, str(exc)) from exc
    return embedder.status(db.get_settings())


@app.post("/api/ai/meaning/cancel")
def ai_meaning_cancel() -> dict:
    embedder.cancel()
    return embedder.status(db.get_settings())


@app.post("/api/ai/meaning/remove")
def ai_meaning_remove() -> dict:
    embedder.remove()
    return embedder.status(db.get_settings())


@app.get("/api/taste")
def taste_view() -> dict:
    """What ClipForge AI learned from your choices (taste.py)."""
    return taste.status(taste.default_workspace())


@app.delete("/api/taste")
def taste_forget() -> dict:
    taste.forget(taste.default_workspace())
    return taste.status(taste.default_workspace())


@app.get("/api/ai/builtin")
def ai_builtin_view() -> dict:
    from . import builtin_ai

    return builtin_ai.status(db.get_settings())


@app.post("/api/ai/builtin/install")
def ai_builtin_install(body: dict[str, Any]) -> dict:
    from . import builtin_ai

    try:
        return builtin_ai.install(str(body.get("level") or ""), on_done=_builtin_ready)
    except builtin_ai.BuiltinError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@app.post("/api/ai/builtin/cancel")
def ai_builtin_cancel() -> dict:
    from . import builtin_ai

    return builtin_ai.cancel()


@app.post("/api/ai/builtin/use")
def ai_builtin_use(body: dict[str, Any]) -> dict:
    """Use the built-in model at an installed level (or the best installed one)."""
    from . import builtin_ai

    level = str(body.get("level") or "auto")
    if level != "auto" and level not in builtin_ai.installed_levels():
        raise HTTPException(409, "Download that level first.")
    if not builtin_ai.installed_levels():
        raise HTTPException(409, "Set up the built-in model first.")
    db.save_settings({"ai_provider": "builtin", "builtin_ai_level": level})
    return builtin_ai.status(db.get_settings())


@app.post("/api/ai/builtin/remove")
def ai_builtin_remove(body: dict[str, Any]) -> dict:
    """Delete a downloaded level to free disk space (download it again any time)."""
    from . import builtin_ai

    try:
        builtin_ai.remove(str(body.get("level") or ""))
    except builtin_ai.BuiltinError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    s = db.get_settings()
    if s.get("ai_provider") == "builtin" and not builtin_ai.installed_levels():
        db.save_settings({"ai_provider": "heuristic"})
    return builtin_ai.status(db.get_settings())


@app.post("/api/ai/ollama/pull")
def ai_ollama_pull(body: dict[str, Any]) -> dict:
    from . import ai_setup

    try:
        return ai_setup.pull(db.get_settings().get("ollama_url") or "", str(body.get("model") or ""))
    except ai_setup.SetupError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@app.post("/api/ai/ollama/import")
def ai_ollama_import(body: dict[str, Any]) -> dict:
    from . import ai_setup

    try:
        return ai_setup.import_gguf(db.get_settings().get("ollama_url") or "", str(body.get("path") or ""),
                                    str(body.get("name") or ""))
    except ai_setup.SetupError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def _my_projects() -> list[dict]:
    """The requesting workspace's projects (all of them on the desktop, which has one workspace)."""
    mine = principal.workspace_id()
    return [p for p in db.list_projects() if (p.get("workspace_id") or "local") == mine]


@app.get("/api/stats")
def stats() -> dict:
    projects = _my_projects()
    clips = sum(p.get("clip_count") or 0 for p in projects)
    return {"projects": len(projects), "clips": clips,
            "processing": sum(1 for p in projects if p["status"] in {"queued", "processing"}),
            "recent": [_public_project(p) for p in projects[:6]]}


# ------------------------------------------------------------------ projects
@app.get("/api/projects")
def list_projects() -> list[dict]:
    return [_public_project(p) for p in _my_projects()]


@app.post("/api/projects")
async def create_project(file: UploadFile = File(...), options: str = Form("{}"),
                         transcript: UploadFile | None = File(None)) -> dict:
    filename = Path(file.filename or "video.mp4").name
    ext = Path(filename).suffix.lower()
    if ext not in config.VIDEO_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use MP4, MOV, MKV, WEBM or M4V.")
    try:
        opts = _clean_options(json.loads(options or "{}"))
    except ValueError as exc:
        raise HTTPException(400, "Invalid options JSON") from exc
    name = Path(filename).stem[:120]
    project = db.create_project(name, source_filename=filename, options=opts, status="uploading",
                                workspace_id=principal.workspace_id())
    pdir = config.projects_dir() / project["id"]
    pdir.mkdir(parents=True, exist_ok=True)
    dest = pdir / f"source{ext}"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out, length=4 * 1024 * 1024)
    if transcript is not None and transcript.filename:
        t_ext = Path(transcript.filename).suffix.lower()
        if t_ext not in config.TRANSCRIPT_EXTENSIONS:
            raise HTTPException(400, "Transcript must be .srt, .vtt or .json")
        tpath = pdir / f"imported_transcript{t_ext}"
        with open(tpath, "wb") as out:
            shutil.copyfileobj(transcript.file, out)
        opts["transcript_file"] = str(tpath)
    db.update_project(project["id"], source_path=str(dest), options=opts)
    worker.submit_project(project["id"])
    return _public_project(db.get_project(project["id"]))  # type: ignore[arg-type]


class UrlImport(BaseModel):
    url: str
    options: dict = {}


@app.post("/api/projects/url")
def create_from_url(body: UrlImport) -> dict:
    url = body.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "Enter a http(s) URL")
    try:
        import yt_dlp  # noqa: F401
    except ImportError as exc:
        raise HTTPException(400, "URL import requires yt-dlp (pip install yt-dlp)") from exc
    if cloud_settings.enabled():
        from . import netguard

        try:  # a server must not fetch its own network or cloud metadata for anyone, owner included
            netguard.check(url, allow_private=False)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    project = db.create_project(url[:120], source_url=url, options=_clean_options(body.options), status="queued",
                                workspace_id=principal.workspace_id())
    pdir = config.projects_dir() / project["id"]
    pdir.mkdir(parents=True, exist_ok=True)
    db.update_project(project["id"], source_path=str(pdir / "source.mp4"))
    worker.submit_project(project["id"], url=url)
    return _public_project(db.get_project(project["id"]))  # type: ignore[arg-type]


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    p = _project_or_404(project_id)
    return {**_public_project(p), "clips": [_public_clip(c) for c in db.list_clips(project_id)]}


class ProjectPatch(BaseModel):
    name: str | None = None


@app.patch("/api/projects/{project_id}")
def patch_project(project_id: str, body: ProjectPatch) -> dict:
    _project_or_404(project_id)
    if body.name:
        db.update_project(project_id, name=body.name.strip()[:120])
    return get_project(project_id)


class ProcessBody(BaseModel):
    options: dict = {}


@app.post("/api/projects/{project_id}/process")
def reprocess(project_id: str, body: ProcessBody) -> dict:
    p = _project_or_404(project_id)
    if p["status"] in {"queued", "processing", "importing"}:
        raise HTTPException(409, "Project is already processing")
    if (p.get("info") or {}).get("link") and not p.get("asset_id"):  # the supplied link was never downloaded: try it again
        from .studio import link_import

        link_import.retry(project_id)
        return get_project(project_id)
    opts = {**(p.get("options") or {}), **_clean_options(body.options)}
    db.update_project(project_id, options=opts)
    worker.submit_project(project_id, url=p.get("source_url") if not Path(p["source_path"]).exists() else None)
    return get_project(project_id)


@app.post("/api/projects/{project_id}/cancel")
def cancel(project_id: str) -> dict:
    p = _project_or_404(project_id)
    if p["status"] == "importing":
        from .studio import link_import

        link_import.cancel(project_id)
        return {"ok": True}
    worker.cancel(project_id)
    return {"ok": True}


@app.delete("/api/projects/{project_id}", dependencies=[Depends(project_delete.from_this_computer)])
def delete_project(project_id: str, as_of: float | None = None):
    """The clips project and what only it uses; running work on it is stopped first (studio/project_delete.py).
    `as_of` is the delete plan's moment, which the page sends back."""
    return project_delete.answer_delete(project_id, "clips", as_of)


@app.get("/api/projects/{project_id}/thumbnail")
def project_thumbnail(project_id: str) -> FileResponse:
    p = _project_or_404(project_id)
    # a project made from a link has no source file until its download finishes
    thumb = project_dir(p) / "thumb.jpg" if p.get("source_path") else None
    if thumb is None or not thumb.exists():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(thumb, media_type="image/jpeg")


@app.get("/api/projects/{project_id}/source")
def project_source(project_id: str) -> FileResponse:
    p = _project_or_404(project_id)
    src = Path(p["source_path"]) if p.get("source_path") else None
    if src is None or not src.exists():
        raise HTTPException(404, "Source video missing")
    return FileResponse(src)


@app.get("/api/projects/{project_id}/transcript")
def project_transcript(project_id: str) -> dict:
    p = _project_or_404(project_id)
    return read_json(project_dir(p) / "transcript.json", {"segments": []})


class ExportBody(BaseModel):
    clip_ids: list[str] | None = None


@app.post("/api/projects/{project_id}/export")
def export_zip(project_id: str, body: ExportBody) -> FileResponse:
    p = _project_or_404(project_id)
    clips = [c for c in db.list_clips(project_id) if c["status"] == "ready"]
    if body.clip_ids is not None:
        wanted = set(body.clip_ids)
        clips = [c for c in clips if c["id"] in wanted]
    if not clips:
        raise HTTPException(400, "No rendered clips selected")
    zpath = export.build_zip(p, [with_active_version(c) for c in clips], project_dir(p) / "exports")
    for c in clips:
        taste.record(c, "exported", str(p.get("workspace_id") or "local"))
    return FileResponse(zpath, media_type="application/zip", filename=zpath.name)


def with_active_version(clip: dict) -> dict:
    """The clip as exported/published: the chosen version's video when one is chosen and rendered."""
    v = db.get_version(clip.get("active_version") or "") if clip.get("active_version") else None
    if v and v["status"] == "ready" and Path(v.get("output_path") or "").exists():
        return {**clip, "output_path": v["output_path"], "duration": v["duration"], "version_label": v["label"],
                "version_id": v["id"]}
    return clip


# ------------------------------------------------------------------ clips
@app.get("/api/clips/{clip_id}")
def get_clip(clip_id: str) -> dict:
    return _public_clip(_clip_or_404(clip_id))


class ClipPatch(BaseModel):
    title: str | None = None
    hook: str | None = None
    hashtags: list[str] | None = None
    caption_text: str | None = None
    selected: bool | None = None
    edit: dict | None = None
    post: dict | None = None


EDIT_KEYS = {"start", "end", "tracking", "layout", "crop_x", "zoom", "caption_style", "caption_position",
             "caption_size", "highlight_color", "highlight_words", "captions_enabled", "caption_words", "hook",
             "hook_overlay", "hook_seconds", "silence", "auto_zoom", "gain_db", "normalize_audio", "speed",
             "remove_fillers", "caption_emphasis", "clean_sound"}


@app.patch("/api/clips/{clip_id}")
def patch_clip(clip_id: str, body: ClipPatch) -> dict:
    clip = _clip_or_404(clip_id)
    fields: dict[str, Any] = {}
    post = dict(clip.get("post") or {})
    if body.title is not None:
        fields["title"] = body.title.strip()[:postpack.TITLE_MAX]
    if body.hook is not None:
        fields["hook"] = body.hook.strip()[:160]
    if body.hashtags is not None:
        fields["hashtags"] = [("#" + t.lstrip("#")).strip() for t in body.hashtags if t.strip("# ")][:10]
    if post and (body.title is not None or body.hashtags is not None):  # keep the post package in step
        fields["post"] = post = postpack.apply_edit(post, {k: fields[k] for k in ("title", "hashtags") if k in fields})
    if body.post is not None:
        post = postpack.apply_edit(post, body.post)
        fields["post"] = post
        if "title" in body.post:
            fields["title"] = post["title"]
        if "hashtags" in body.post:
            fields["hashtags"] = post["hashtags"]
    if body.caption_text is not None:
        fields["caption_text"] = body.caption_text
    if body.selected is not None:
        fields["selected"] = 1 if body.selected else 0
        if bool(clip.get("selected", 1)) != bool(body.selected):  # a lesson for ClipForge AI's taste (taste.py)
            taste.record(clip, "reselected" if body.selected else "deselected")
    if body.edit is not None:
        edit = dict(clip.get("edit") or {})
        for k in ("start", "end"):  # a trim is a time in seconds: never "NaN" or infinity (it would render it all)
            if body.edit.get(k) is not None:
                try:
                    finite = math.isfinite(float(body.edit[k]))
                except (TypeError, ValueError):
                    finite = False
                if not finite:
                    raise HTTPException(400, f"The clip's {k} must be a time in seconds.")
        for k, v in body.edit.items():
            if k not in EDIT_KEYS or (k == "clean_sound" and v is not None and v not in config.CLEAN_SOUND_MODES):
                continue
            if v is None:
                edit.pop(k, None)
            else:
                edit[k] = v
        if clip.get("category") == "story" and ("start" in body.edit or "end" in body.edit):
            # no story clip is longer than five minutes (studio/story_review.py); other changes stay possible on
            # a longer clip made before the limit
            from .pipeline.story_parts import MAX_CLIP_S

            try:
                length = float(edit.get("end", clip["end"])) - float(edit.get("start", clip["start"]))
            except (TypeError, ValueError):
                length = 0.0
            if length > MAX_CLIP_S + 0.001:
                raise HTTPException(400, f"A story clip can be at most 5 minutes long; this trim would make it "
                                         f"{int(length) // 60}:{int(length) % 60:02d}. Split the story into parts "
                                         "under Stories instead.")
            was = dict(clip.get("edit") or {})
            try:
                before = float(was.get("end", clip["end"])) - float(was.get("start", clip["start"]))
                whole = bool(was.get("hook_overlay")) and float(was.get("hook_seconds") or 0) >= before
            except (TypeError, ValueError):
                whole = False
            if whole and "hook_seconds" not in body.edit and length > 0:
                edit["hook_seconds"] = math.ceil(length) + 1  # "Part N" showed for the whole part: it still does
        fields["edit"] = edit
    db.update_clip(clip_id, **fields)
    return get_clip(clip_id)


class PostPackageBody(BaseModel):
    use_ai: bool = True


@app.post("/api/clips/{clip_id}/post-package")
def regenerate_post_package(clip_id: str, body: PostPackageBody) -> dict:
    """(Re)write the clip's post package from its current transcript range. Replaces any edits."""
    clip = _clip_or_404(clip_id)
    project = db.get_project(clip["project_id"])
    assert project
    post = postpack.for_clip(clip, load_words(project), db.get_settings(), use_ai=body.use_ai)
    db.update_clip(clip_id, post=post, title=post["title"] or clip["title"], hashtags=post["hashtags"])
    return get_clip(clip_id)


class SoundCheckBody(BaseModel):
    mode: str = "auto"


def _sound_check_dir() -> Path:
    return cleanup.cache_dir() / "compare"


def _sound_check_name(clip_id: str) -> str:
    return hashlib.sha256(clip_id.encode()).hexdigest()[:24]


@app.post("/api/clips/{clip_id}/sound-check")
def sound_check(clip_id: str, body: SoundCheckBody) -> dict:
    """Before/after for the clip editor: the clip's original sound and its cleaned-up sound at this level, matched in
    loudness. Uses the render's own cache, so the next render reuses the cleaning."""
    if body.mode not in config.CLEAN_SOUND_MODES or body.mode == "off":
        raise HTTPException(400, "Choose Auto, Gentle or Strong to compare.")
    clip = _clip_or_404(clip_id)
    project = db.get_project(clip["project_id"])
    if not project or not project.get("source_path") or not Path(project["source_path"]).exists():
        raise HTTPException(404, "The original video is no longer on this computer.")
    if not (project.get("info") or {}).get("has_audio", True):
        raise HTTPException(400, "This video has no sound.")
    edit = clip.get("edit") or {}
    start, end = float(edit.get("start", clip["start"])), float(edit.get("end", clip["end"]))
    try:
        out = cleanup.compare(project["source_path"], start, end + 0.2, load_words(project), body.mode,
                              _sound_check_dir(), _sound_check_name(clip["id"]))
    except cleanup.CleanupError as exc:
        raise HTTPException(409, str(exc)) from exc
    stamp = str(int(time.time() * 1000))
    url = lambda which: f"/api/clips/{clip_id}/sound-check/{which}?v={stamp}"  # noqa: E731
    report = out["report"]
    return {"mode": body.mode, "applied": report.get("applied"), "summary": report.get("summary", ""),
            "before": url("before"), "after": url("after") if out["after"] else None}


@app.get("/api/clips/{clip_id}/sound-check/{which}")
def sound_check_file(clip_id: str, which: str) -> FileResponse:
    if which not in ("before", "after"):
        raise HTTPException(404, "Not found")
    path = _sound_check_dir() / f"{_sound_check_name(_clip_or_404(clip_id)['id'])}-{which}.wav"
    if not path.exists():
        raise HTTPException(404, "Compare again to hear it.")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/api/clips/{clip_id}/render")
def rerender(clip_id: str) -> dict:
    clip = _clip_or_404(clip_id)
    if clip["status"] in {"queued", "rendering"}:
        raise HTTPException(409, "Clip is already rendering")
    worker.submit_render(clip_id)
    return get_clip(clip_id)


@app.get("/api/clips/{clip_id}/video")
def clip_video(clip_id: str, download: int = 0) -> FileResponse:
    clip = _clip_or_404(clip_id)
    path = Path(clip.get("output_path") or "")
    if not path.exists():
        raise HTTPException(404, "Clip not rendered yet")
    name = f"{export.safe_name(clip.get('title', ''), clip_id)}.mp4"
    if download:
        return FileResponse(path, media_type="video/mp4", filename=name)
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/clips/{clip_id}/thumbnail")
def clip_thumbnail(clip_id: str) -> FileResponse:
    clip = _clip_or_404(clip_id)
    path = Path(clip.get("thumb_path") or "")
    if not path.exists():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/clips/{clip_id}/words")
def clip_words(clip_id: str, pad: float = 20.0) -> dict:
    """Transcript words around the clip, for trimming and caption editing."""
    clip = _clip_or_404(clip_id)
    project = db.get_project(clip["project_id"])
    assert project
    edit = clip.get("edit") or {}
    start = float(edit.get("start", clip["start"]))
    end = float(edit.get("end", clip["end"]))
    words = load_words(project)
    around = [w for w in words if start - pad <= w["start"] <= end + pad]
    return {"start": start, "end": end, "original_start": clip["start"], "original_end": clip["end"],
            "duration": project.get("duration", 0), "words": around, "caption_words": edit.get("caption_words")}


# ------------------------------------------------------------------ versions
ORIGINAL_DESCRIPTION = "The clip as edited."


def _public_version(v: dict, clip: dict) -> dict:
    merged = {**(clip.get("edit") or {}), **(v.get("edit") or {})}
    out = {k: val for k, val in v.items() if k not in {"output_path", "thumb_path"}}
    out["has_video"] = bool(v.get("output_path")) and Path(v["output_path"]).exists()
    out["has_thumbnail"] = bool(v.get("thumb_path")) and Path(v["thumb_path"]).exists()
    out["version"] = int(v.get("updated_at", 0))
    rendered = (v.get("render_info") or {}).get("edit_hash")
    out["stale"] = bool(rendered) and rendered != render.edit_hash(merged)
    return out


def _versions_payload(clip: dict) -> dict:
    original = {"id": "", "clip_id": clip["id"], "kind": "original", "label": "Original",
                "description": ORIGINAL_DESCRIPTION, "status": clip["status"], "progress": clip.get("progress", 0),
                "error": clip.get("error", ""), "duration": clip.get("duration", 0),
                "render_info": clip.get("render_info") or {}, "stale": False, **{k: _public_clip(clip)[k] for k in
                                                                                  ("has_video", "has_thumbnail",
                                                                                   "version")}}
    return {"active": clip.get("active_version") or "",
            "versions": [original, *(_public_version(v, clip) for v in db.list_versions(clip["id"]))]}


@app.get("/api/clips/{clip_id}/versions")
def clip_versions(clip_id: str) -> dict:
    return _versions_payload(_clip_or_404(clip_id))


class VersionsBody(BaseModel):
    kinds: list[str] | None = None


@app.post("/api/clips/{clip_id}/versions")
def create_versions(clip_id: str, body: VersionsBody) -> dict:
    """Create (or rebuild) the requested alternative versions and queue their renders."""
    clip = _clip_or_404(clip_id)
    if clip["status"] != "ready":
        raise HTTPException(409, "Render the clip before creating versions")
    project = db.get_project(clip["project_id"])
    assert project
    kinds = [k for k in (body.kinds or list(versions.KINDS)) if k in versions.KINDS]
    words = load_words(project)
    existing = {v["kind"]: v for v in db.list_versions(clip_id)}
    for kind in kinds:
        edit, description = versions.build(kind, clip, project, db.get_settings(), words)
        old = existing.get(kind)
        if old and old["status"] in {"queued", "rendering"}:
            continue
        if old:
            db.update_version(old["id"], edit=edit, description=description)
            vid = old["id"]
        else:
            vid = db.create_version(clip_id, kind, label=versions.KINDS[kind], description=description, edit=edit,
                                    status="queued")["id"]
        worker.submit_version(vid)
    return _versions_payload(db.get_clip(clip_id) or clip)


def _version_or_404(version_id: str) -> dict:
    v = db.get_version(version_id)
    if not v:
        raise HTTPException(404, "Version not found")
    return v


@app.delete("/api/versions/{version_id}")
def delete_version(version_id: str) -> dict:
    v = _version_or_404(version_id)
    if v["status"] in {"queued", "rendering"}:
        raise HTTPException(409, "Wait for the render to finish")
    clip = db.get_clip(v["clip_id"])
    project = db.get_project(clip["project_id"]) if clip else None
    db.delete_version(version_id)
    if project:
        folder = version_dir(project, v)
        if config.projects_dir().resolve() in folder.resolve().parents:
            shutil.rmtree(folder, ignore_errors=True)
    return _versions_payload(db.get_clip(v["clip_id"])) if clip else {"active": "", "versions": []}


class ActiveVersionBody(BaseModel):
    version_id: str = ""


@app.post("/api/clips/{clip_id}/active-version")
def set_active_version(clip_id: str, body: ActiveVersionBody) -> dict:
    """Choose which version is published and exported ("" = the original)."""
    _clip_or_404(clip_id)
    if body.version_id:
        v = _version_or_404(body.version_id)
        if v["clip_id"] != clip_id:
            raise HTTPException(400, "That version belongs to another clip")
        if v["status"] != "ready":
            raise HTTPException(409, "That version is not rendered yet")
    db.update_clip(clip_id, active_version=body.version_id)
    return _versions_payload(db.get_clip(clip_id))  # type: ignore[arg-type]


@app.get("/api/versions/{version_id}/video")
def version_video(version_id: str, download: int = 0) -> FileResponse:
    v = _version_or_404(version_id)
    path = Path(v.get("output_path") or "")
    if not path.exists():
        raise HTTPException(404, "Version not rendered yet")
    clip = db.get_clip(v["clip_id"]) or {}
    name = f"{export.safe_name(clip.get('title', ''), v['clip_id'])} - {v['label']}.mp4"
    return FileResponse(path, media_type="video/mp4", filename=name if download else None)


@app.get("/api/versions/{version_id}/thumbnail")
def version_thumbnail(version_id: str) -> FileResponse:
    path = Path(_version_or_404(version_id).get("thumb_path") or "")
    if not path.exists():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(path, media_type="image/jpeg")


# ------------------------------------------------------------------ errors
@app.exception_handler(FFmpegError)
def _ffmpeg_error(_, exc: FFmpegError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=500)


@app.exception_handler(PublishError)
def _publish_error(_, exc: PublishError) -> JSONResponse:
    return JSONResponse({"detail": str(exc), "fix": exc.fix, "code": exc.code}, status_code=400)


# ------------------------------------------------------------------ legal pages
LEGAL_DIR = config.ROOT_DIR / "docs" / "legal"  # the same files are the public website (GitHub Pages)
LEGAL_PAGES = {"": "index.html", "terms": "terms.html", "privacy": "privacy.html", "site.css": "site.css",
               "app-icon.png": "app-icon.png", "favicon.ico": "favicon.ico"}


@app.get("/legal", include_in_schema=False)
def legal_root() -> RedirectResponse:
    return RedirectResponse("/legal/")  # the pages link to each other relatively


@app.get("/legal/", include_in_schema=False)
@app.get("/legal/{page}", include_in_schema=False)
def legal(page: str = "") -> FileResponse:
    name = LEGAL_PAGES.get(page.removesuffix(".html").replace("index", ""))
    if not name or not (LEGAL_DIR / name).is_file():
        raise HTTPException(404)
    media_type = {".css": "text/css", ".png": "image/png", ".ico": "image/x-icon"}.get(Path(name).suffix,
                                                                                       "text/html")
    return FileResponse(LEGAL_DIR / name, media_type=media_type)


# ------------------------------------------------------------------ UI
if (config.FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404)
    candidate = (config.FRONTEND_DIST / full_path).resolve()
    if full_path and candidate.is_file() and config.FRONTEND_DIST.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = config.FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"message": "ClipForge API is running. Build the UI with `npm run build` in frontend/."})

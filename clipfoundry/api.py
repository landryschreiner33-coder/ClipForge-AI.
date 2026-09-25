"""FastAPI application: REST API + the built React UI."""
from __future__ import annotations

import json
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, config, db
from .jobs import worker
from .pipeline import export, llm, transcribe
from .pipeline.common import read_json
from .pipeline.ffmpeg_utils import FFmpegError, find_binary, nvenc_available
from .pipeline.process import load_words, project_dir

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    db.mark_interrupted()
    worker.start()
    yield


app = FastAPI(title="ClipFoundry", version=__version__, lifespan=lifespan)


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
    return out


def _public_clip(c: dict) -> dict:
    out = {k: v for k, v in c.items() if k not in {"output_path", "thumb_path"}}
    out["has_video"] = bool(c.get("output_path")) and Path(c["output_path"]).exists()
    out["has_thumbnail"] = bool(c.get("thumb_path")) and Path(c["thumb_path"]).exists()
    out["version"] = int(c.get("updated_at", 0))
    return out


def _clean_options(raw: dict) -> dict:
    allowed = {"clip_count", "min_duration", "max_duration", "target_duration", "caption_style", "tracking",
               "layout", "silence", "auto_zoom", "hook_overlay", "caption_position", "highlight_words"}
    clean = config.validate_settings({k: v for k, v in raw.items() if k in allowed})
    return clean


# ------------------------------------------------------------------ system
@app.get("/api/health")
def health() -> dict:
    settings = db.get_settings()
    ffmpeg = find_binary("ffmpeg", settings.get("ffmpeg_path", ""))
    ffprobe = find_binary("ffprobe", settings.get("ffmpeg_path", ""))
    model, device, compute = transcribe.resolve_whisper(settings)
    return {
        "version": __version__,
        "platform": sys.platform,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "nvenc": nvenc_available() if ffmpeg else False,
        "cuda": transcribe.cuda_available(),
        "whisper_installed": transcribe.whisper_installed(),
        "whisper": {"model": model, "device": device, "compute_type": compute,
                    "cached": transcribe.model_cached(model)},
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
    patch = {k: v for k, v in patch.items() if not (k in config.SECRET_KEYS and v == "********")}
    db.save_settings(patch)
    return get_settings()


@app.post("/api/ai/check")
def ai_check() -> dict:
    return llm.check_provider(db.get_settings())


@app.get("/api/stats")
def stats() -> dict:
    projects = db.list_projects()
    clips = sum(p.get("clip_count") or 0 for p in projects)
    return {"projects": len(projects), "clips": clips,
            "processing": sum(1 for p in projects if p["status"] in {"queued", "processing"}),
            "recent": [_public_project(p) for p in projects[:6]]}


# ------------------------------------------------------------------ projects
@app.get("/api/projects")
def list_projects() -> list[dict]:
    return [_public_project(p) for p in db.list_projects()]


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
    project = db.create_project(name, source_filename=filename, options=opts, status="uploading")
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
    project = db.create_project(url[:120], source_url=url, options=_clean_options(body.options), status="queued")
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
    if p["status"] in {"queued", "processing"}:
        raise HTTPException(409, "Project is already processing")
    opts = {**(p.get("options") or {}), **_clean_options(body.options)}
    db.update_project(project_id, options=opts)
    worker.submit_project(project_id, url=p.get("source_url") if not Path(p["source_path"]).exists() else None)
    return get_project(project_id)


@app.post("/api/projects/{project_id}/cancel")
def cancel(project_id: str) -> dict:
    _project_or_404(project_id)
    worker.cancel(project_id)
    return {"ok": True}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    p = _project_or_404(project_id)
    if worker.current == project_id:
        raise HTTPException(409, "Cancel processing before deleting")
    worker.cancel(project_id)
    pdir = config.projects_dir() / project_id
    db.delete_project(project_id)
    root = config.projects_dir().resolve()
    if pdir.resolve().parent == root and pdir.exists():
        shutil.rmtree(pdir, ignore_errors=True)
    return {"ok": True, "deleted": p["id"]}


@app.get("/api/projects/{project_id}/thumbnail")
def project_thumbnail(project_id: str) -> FileResponse:
    p = _project_or_404(project_id)
    thumb = project_dir(p) / "thumb.jpg"
    if not thumb.exists():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(thumb, media_type="image/jpeg")


@app.get("/api/projects/{project_id}/source")
def project_source(project_id: str) -> FileResponse:
    p = _project_or_404(project_id)
    src = Path(p["source_path"])
    if not src.exists():
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
    zpath = export.build_zip(p, clips, project_dir(p) / "exports")
    return FileResponse(zpath, media_type="application/zip", filename=zpath.name)


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


EDIT_KEYS = {"start", "end", "tracking", "layout", "crop_x", "zoom", "caption_style", "caption_position",
             "caption_size", "highlight_color", "highlight_words", "captions_enabled", "caption_words", "hook",
             "hook_overlay", "hook_seconds", "silence", "auto_zoom", "gain_db", "normalize_audio"}


@app.patch("/api/clips/{clip_id}")
def patch_clip(clip_id: str, body: ClipPatch) -> dict:
    clip = _clip_or_404(clip_id)
    fields: dict[str, Any] = {}
    if body.title is not None:
        fields["title"] = body.title.strip()[:120]
    if body.hook is not None:
        fields["hook"] = body.hook.strip()[:160]
    if body.hashtags is not None:
        fields["hashtags"] = [("#" + t.lstrip("#")).strip() for t in body.hashtags if t.strip("# ")][:10]
    if body.caption_text is not None:
        fields["caption_text"] = body.caption_text
    if body.selected is not None:
        fields["selected"] = 1 if body.selected else 0
    if body.edit is not None:
        edit = dict(clip.get("edit") or {})
        for k, v in body.edit.items():
            if k not in EDIT_KEYS:
                continue
            if v is None:
                edit.pop(k, None)
            else:
                edit[k] = v
        fields["edit"] = edit
    db.update_clip(clip_id, **fields)
    return get_clip(clip_id)


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


# ------------------------------------------------------------------ errors
@app.exception_handler(FFmpegError)
def _ffmpeg_error(_, exc: FFmpegError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=500)


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
    return JSONResponse({"message": "ClipFoundry API is running. Build the UI with `npm run build` in frontend/."})

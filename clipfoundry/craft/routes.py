"""The editing apps in ClipForge: setting them up, FilmCraft's editor on the editor page, and its saves coming back.

FilmCraft's editor (its web build) runs only in the desktop app: it is served from this computer at /craft/filmcraft/
and reads this computer's files through the addresses below. The online studio does not offer it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .. import db
from ..cloud import principal
from ..cloud import settings as cloud_settings
from ..pathguard import plain_parts
from . import apps
from .runner import CraftError

router = APIRouter()

TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript",
         ".wasm": "application/wasm", ".css": "text/css", ".json": "application/json", ".png": "image/png",
         ".svg": "image/svg+xml", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8", ".woff2": "font/woff2",
         ".ttf": "font/ttf", ".otf": "font/otf"}


def _desktop() -> None:
    if cloud_settings.enabled():
        raise HTTPException(404, "FilmCraft's editor is part of the desktop app.")


@router.get("/api/craft")
def craft_status() -> dict:
    """What is set up (FilmCraft and EffectCraft), what a set-up would download, and how final videos are made."""
    from . import ai

    settings = db.get_settings()
    st = apps.status()
    return {**st, "engine": settings.get("edit_engine", "auto"), "ai_finish": bool(settings.get("craft_ai_finish",
                                                                                                  True)),
            "auto_install": bool(settings.get("craft_auto_install", True)), "ai_disclosure": ai.disclosure(settings),
            "editor": bool(apps.web_root("filmcraft")) and not st["online"]}


class InstallBody(BaseModel):
    parts: list[str] = ["cli", "web"]


@router.post("/api/craft/install")
def craft_install(body: InstallBody) -> dict:
    parts = tuple(p for p in body.parts if p in ("cli", "web")) or ("cli", "web")
    try:
        return apps.install(parts)
    except apps.CraftUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/craft/filmcraft/{path:path}", include_in_schema=False)
def filmcraft_web(path: str) -> FileResponse:
    """FilmCraft's web build, from this computer (same address as the page, so the page can hand it files)."""
    _desktop()
    parts = plain_parts(path or "index.html")  # before anything looks at the file system (pathguard.py)
    if parts is None:
        raise HTTPException(404)
    root = apps.web_root("filmcraft")
    if not root:
        raise HTTPException(404, "FilmCraft's editor is not set up yet.")
    base = root.resolve()
    target = base.joinpath(*parts).resolve()
    if target.is_dir():
        target = target / "index.html"
    if base not in target.parents or not target.is_file():
        raise HTTPException(404)
    cache = "no-cache" if target.suffix == ".html" else "public, max-age=3600"
    return FileResponse(target, media_type=TYPES.get(target.suffix.lower(), "application/octet-stream"),
                        headers={"Cache-Control": cache, "X-Content-Type-Options": "nosniff"})


# ------------------------------------------------------------------ FilmCraft's editor on one video
def _video(video_id: str) -> dict:
    v = db.fetch("studio_projects", video_id)
    if not v or v["workspace_id"] != principal.workspace_id():
        raise HTTPException(404, "Video not found")
    return v


def _rev(v: dict, revision: int) -> int:
    rev = revision or v["plan_revision"]
    if not rev:
        raise HTTPException(409, "The rough cut is not ready yet.")
    return rev


def _paths(video_id: str, rev: int) -> tuple[Path, Path]:
    from ..studio import video_flow

    base = video_flow.video_dir(video_id) / "filmcraft"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"web-r{rev}.json", base / "added"


def _source(v: dict, rev: int) -> tuple[Path | None, dict]:
    """The project FilmCraft's editor opens for one version: the person's own save of it, or the AI's edit."""
    from ..studio import video_flow
    from . import finish

    try:
        plan = video_flow.plan_at(v["id"], rev)
    except video_flow.VideoError as exc:
        raise HTTPException(404, str(exc)) from exc
    hand = plan.get("filmcraft") or {}
    if hand:
        saved = video_flow.filmcraft_saves(v["id"]) / f"{hand.get('project', '')}.fcproj"
        return (saved if saved.is_file() else None), {"hand": True, "saved_at": hand.get("saved_at"),
                                                      "opened_on": hand.get("opened_on")}
    folder = video_flow.video_dir(v["id"]) / f"r{rev}" / "filmcraft"
    try:
        done = json.loads((folder / "report.json").read_text())
    except (OSError, ValueError):
        done = {}
    ok = done.get("key") == finish.edit_key(plan, db.get_settings()) and (folder / "edit.fcproj").is_file()
    about = {"hand": False, "ai": done.get("ai") or {}, "steps": len(done.get("steps_run") or []),
             "failed": [s.get("id") for s in done.get("steps_run") or [] if not s.get("ok")][:20],
             "shots": [{"what": s.get("what"), "app": s.get("app"), "use": s.get("use")} for s in
                       done.get("shots") or []], "notes": done.get("notes") or []} if ok else {"hand": False}
    return (folder / "edit.fcproj" if ok else None), about


def _job(video_id: str, rev: int) -> dict | None:
    rows = db.select("studio_jobs", "target_id = ? AND kind = 'filmcraft_edit' AND revision = ?", (video_id, rev),
                     "created_at DESC", 1)
    if not rows:
        return None
    j = rows[0]
    return {k: j.get(k) for k in ("id", "status", "progress", "message", "error")}


@router.get("/api/studio/videos/{video_id}/filmcraft/editor")
def editor_session(video_id: str, revision: int = 0) -> dict:
    """What the editor page needs to open FilmCraft's editor on one version (or why it cannot yet)."""
    _desktop()
    v = _video(video_id)
    rev = _rev(v, revision)
    src, about = _source(v, rev)
    out = {"revision": rev, "editor": "/craft/filmcraft/index.html?host=parent",
           "editor_ready": bool(apps.web_root("filmcraft")), "cli_ready": bool(apps.find_cli("filmcraft")),
           "ready": bool(src), "job": _job(video_id, rev), **about}
    if src and out["editor_ready"]:
        from . import web

        manifest, _added = _paths(video_id, rev)
        base = f"/api/studio/videos/{video_id}/filmcraft/files"
        try:
            got = web.session(src, manifest, base)
        except CraftError as exc:
            raise HTTPException(409, str(exc)) from exc
        out.update(got, media_query=f"?revision={rev}",
                   project=f"/api/studio/videos/{video_id}/filmcraft/project?revision={rev}",
                   project_name=f"Version {rev}.fcproj")
    return out


class PrepareBody(BaseModel):
    revision: int = 0


@router.post("/api/studio/videos/{video_id}/filmcraft/prepare")
def editor_prepare(video_id: str, body: PrepareBody) -> dict:
    """Have FilmCraft (and the AI, when one is set up) make the edit of this version for the editor."""
    from ..studio.jobs import enqueue

    _desktop()
    v = _video(video_id)
    rev = _rev(v, body.revision)
    if not apps.find_cli("filmcraft"):
        raise HTTPException(409, "FilmCraft is not set up yet: set it up in Settings, Editing apps.")
    src, _about = _source(v, rev)
    if src is None:  # an edit made before (other settings or app versions) no longer fits: make it again
        for old in db.select("studio_jobs", "idempotency_key = ? AND status = 'done'",
                             (f"filmcraft_edit:{video_id}:{rev}",)):
            db.update("studio_jobs", old["id"], status="failed", error="Made again")
    job = enqueue(v["workspace_id"], "filmcraft_edit", video_id, rev)
    return editor_session(video_id, rev) | {"job": _job(video_id, rev) or {"id": job["id"], "status": "queued"}}


@router.get("/api/studio/videos/{video_id}/filmcraft/project")
def editor_project(video_id: str, revision: int = 0) -> Response:
    _desktop()
    v = _video(video_id)
    manifest, _added = _paths(video_id, _rev(v, revision))
    project = manifest.with_suffix(".fcproj")
    if not project.is_file():
        raise HTTPException(404, "Open the editor again.")
    return Response(project.read_bytes(), media_type="application/octet-stream",
                    headers={"Cache-Control": "no-store"})


@router.get("/api/studio/videos/{video_id}/filmcraft/files/{name}")
def editor_file(video_id: str, name: str, revision: int = 0) -> FileResponse:
    """A file the open project uses, only from the list ClipForge wrote for it."""
    from . import web

    _desktop()
    v = _video(video_id)
    manifest, _added = _paths(video_id, _rev(v, revision))
    path = web.media_file(manifest, name)
    if not path:
        raise HTTPException(404, "Not one of this video's files")
    return FileResponse(path, headers={"Cache-Control": "no-store"})


@router.post("/api/studio/videos/{video_id}/filmcraft/files/{name}")
async def editor_add_file(video_id: str, name: str, request: Request, revision: int = 0) -> dict:
    """A file the person added in FilmCraft's editor (the page sends it when a save uses it)."""
    from . import web

    _desktop()
    v = _video(video_id)
    manifest, added = _paths(video_id, _rev(v, revision))
    try:
        web.clean_name(name)
    except CraftError as exc:
        raise HTTPException(400, str(exc)) from exc
    added.mkdir(parents=True, exist_ok=True)
    tmp = added / f".upload-{os.urandom(6).hex()}.part"
    size = 0
    try:
        with tmp.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > web.MAX_FILE:
                    raise HTTPException(413, "A file over 512 MB cannot be added this way.")
                f.write(chunk)
        return web.add_file(manifest, added, name, tmp)
    except CraftError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/api/studio/videos/{video_id}/filmcraft/save")
async def editor_save(video_id: str, request: Request, revision: int = 0) -> Response:
    """A project saved in FilmCraft's editor: it becomes the next version of the video (rendered by FilmCraft).
    Answers 409 with `need` when the project uses files the person added in the editor that the page has not sent."""
    from ..studio import video_flow
    from . import web

    _desktop()
    v = _video(video_id)
    rev = _rev(v, revision)
    if int(request.headers.get("content-length") or 0) > web.MAX_PROJECT:
        raise HTTPException(413, "The project is larger than FilmCraft opens (256 MB).")
    data = await request.body()
    manifest, _added = _paths(video_id, rev)
    try:
        clean, need = web.accept(data, manifest)
    except CraftError as exc:
        raise HTTPException(400, str(exc)) from exc
    if clean is None:
        return Response(json.dumps({"need": need}), status_code=409, media_type="application/json")
    digest, _path = web.store_save(video_flow.filmcraft_saves(video_id), clean)
    raw_base = request.query_params.get("base") or str(v["plan_revision"])
    if not raw_base.isdigit():
        raise HTTPException(400, "Unknown version.")
    try:
        made = video_flow.save_filmcraft(video_id, rev, digest, int(raw_base))
    except video_flow.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except video_flow.VideoError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(json.dumps({**made, "view": video_flow.view(_video(video_id))}, default=str),
                    media_type="application/json")

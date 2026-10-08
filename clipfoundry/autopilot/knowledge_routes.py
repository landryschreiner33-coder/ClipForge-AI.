"""Local Brain workspace: references, approved teaching preferences, examples, and decision provenance."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .. import config, db
from ..publish.common import app_request, local_only
from . import brain, knowledge

router = APIRouter(prefix="/api/brain/knowledge")
READ = [Depends(local_only)]
WRITE = [Depends(app_request)]


def invalid(exc: knowledge.Invalid, status: int = 422) -> HTTPException:
    return HTTPException(status, str(exc))


@router.get("", dependencies=READ)
def list_knowledge(q: str = "", kind: str = "") -> list[dict]:
    try:
        return knowledge.search(q, kind)
    except knowledge.Invalid as exc:
        raise invalid(exc) from None


@router.get("/workspace", dependencies=READ)
def workspace() -> dict:
    rows = knowledge.search()
    observations = brain.observations(limit=80)
    for row in observations:
        row["clip_title"] = (db.get_clip(row["clip_id"]) or {}).get("title") or "Deleted clip"
    return {"counts": {"total": len(rows), "approved": sum(r["state"] == "approved" for r in rows),
                        "examples": sum(r["kind"] == "example" for r in rows)},
            "brain": brain.summary(), "history": brain.history(30), "observations": observations,
            "influences": knowledge.influences(), "formats": {"documents": knowledge.DOCUMENTS,
            "examples": knowledge.VIDEOS, "document_limit_mb": 2, "example_limit_mb": 64},
            "preferences": knowledge.PREFERENCES}


@router.get("/export", dependencies=READ)
def export() -> JSONResponse:
    return JSONResponse(knowledge.export(), headers={"Content-Disposition": 'attachment; filename="brain-knowledge.json"',
                                                     "X-Content-Type-Options": "nosniff"})


@router.post("", dependencies=WRITE)
def create(body: dict) -> dict:
    try:
        return knowledge.create(body)
    except knowledge.Invalid as exc:
        raise invalid(exc) from None


@router.post("/upload", dependencies=WRITE)
async def upload(file: UploadFile = File(...), metadata: str = Form(...)) -> dict:
    directory = None
    try:
        try:
            data = knowledge.clean(json.loads(metadata))
        except (ValueError, TypeError, AttributeError):
            raise knowledge.Invalid("Upload metadata must contain valid knowledge fields") from None
        filename = (file.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1][:180]
        extension = Path(filename).suffix.lower()
        example = data["kind"] == "example"
        allowed = knowledge.VIDEOS if example else knowledge.DOCUMENTS
        if extension not in allowed:
            raise knowledge.Invalid("Upload MP4, MOV, or WebM for an example; TXT, MD, CSV, JSON, or DOCX for a document")
        limit = knowledge.MAX_VIDEO if example else knowledge.MAX_DOCUMENT
        knowledge_id = db.new_id()
        directory = config.data_dir() / "brain" / "knowledge" / knowledge_id
        directory.mkdir(parents=True)
        path = directory / ("original" + extension)
        size, digest = 0, hashlib.sha256()
        with path.open("wb") as target:
            while chunk := await file.read(256 * 1024):
                size += len(chunk)
                if size > limit:
                    raise knowledge.Invalid(f"This upload exceeds the {limit // (1024 * 1024)} MB limit")
                digest.update(chunk)
                target.write(chunk)
        if not size:
            raise knowledge.Invalid("Choose a nonempty file")
        media = knowledge.probe_example(path) if example else {}
        if not example:
            extracted = knowledge.document_text(filename, path.read_bytes())
            data["content"] = (data["content"] + "\n\n" + extracted).strip()
        # clean() expects booleans, not the SQLite integer representation.
        data["enabled"] = bool(data["enabled"])
        row = knowledge.create(data, id=knowledge_id, filename=filename, asset_path=str(path),
                               asset_sha256=digest.hexdigest(), media=media)
        directory = None  # successful persistence retains the original file
        return row
    except knowledge.Invalid as exc:
        raise invalid(exc) from None
    finally:
        await file.close()
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)


@router.get("/influences/{clip_id}", dependencies=READ)
def influences(clip_id: str) -> list[dict]:
    return knowledge.influences(clip_id)


class Preview(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


@router.post("/preview", dependencies=WRITE)
def preview(body: Preview) -> dict:
    settings = db.get_settings()
    before = {"caption_style": settings["caption_style"], "caption_position": settings["caption_position"],
              "caption_emphasis": settings["caption_emphasis"], "pacing": "safe_cuts"}
    after, used = knowledge.choose({"caption_text": body.text}, before, settings)
    return {"before": before, "after": after, "influences": used,
            "note": "This previews the same deterministic preference lookup used for new Autopilot blueprints. "
                    "No clip or performance result is created."}


@router.patch("/{knowledge_id}", dependencies=WRITE)
def edit(knowledge_id: str, body: dict) -> dict:
    try:
        return knowledge.edit(knowledge_id, body)
    except knowledge.Invalid as exc:
        raise invalid(exc) from None


class Approval(BaseModel):
    revision: int = Field(ge=1)


@router.post("/{knowledge_id}/approve", dependencies=WRITE)
def approve(knowledge_id: str, body: Approval) -> dict:
    try:
        return knowledge.approve(knowledge_id, body.revision)
    except knowledge.Invalid as exc:
        raise invalid(exc, 409) from None


@router.delete("/{knowledge_id}", dependencies=WRITE)
def delete(knowledge_id: str) -> dict:
    try:
        knowledge.delete(knowledge_id)
        return {"deleted": True}
    except knowledge.Invalid as exc:
        raise invalid(exc, 404) from None


@router.get("/{knowledge_id}/asset", dependencies=READ)
def asset(knowledge_id: str, download: bool = False) -> FileResponse:
    try:
        path, row = knowledge.asset_file(knowledge_id)
    except knowledge.Invalid as exc:
        raise invalid(exc, 404) from None
    video = row["kind"] == "example" and path.suffix in knowledge.VIDEOS
    mime = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}.get(path.suffix)
    return FileResponse(path, media_type=mime if video else "application/octet-stream",
                        filename=row["filename"] if download or not video else None,
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'"})

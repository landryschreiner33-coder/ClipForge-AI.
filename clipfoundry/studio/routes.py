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

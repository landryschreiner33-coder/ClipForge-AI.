"""Desktop routes for big footage: browse this computer's folders, use files where they are (no copy, no upload)
and prepare a file in the background (its sound, transcript and preview proxy). Every object is looked up inside
the requesting workspace, as in studio/routes.py."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..cloud import principal
from . import local_files, proxies, uploads

router = APIRouter()
MAX_LINKS = 200  # files linked in one request


@router.get("/api/local/browse")
def browse(path: str = ""):
    try:
        return local_files.browse(path)
    except local_files.LocalError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)


class LinkRequest(BaseModel):
    paths: list[str] = Field(max_length=MAX_LINKS)


def _link_all(workspace_id: str, paths: list[str]) -> dict:
    """Each file on its own: one that cannot be linked is reported under "problems", the others are added."""
    assets, problems = [], []
    for path in paths:
        try:
            assets.append(uploads.asset_view(uploads.link_local(workspace_id, path)))
        except uploads.UploadError as exc:
            problems.append({"path": path, "detail": str(exc)})
    return {"assets": assets, "problems": problems}


@router.post("/api/uploads/link")
async def link_files(body: LinkRequest) -> dict:
    return await run_in_threadpool(_link_all, principal.workspace_id(), body.paths)


def _asset(asset_id: str) -> dict:
    try:
        return uploads.asset(asset_id, principal.workspace_id())
    except uploads.UploadError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/api/assets/{asset_id}/prepare")
def prepare_asset(asset_id: str) -> dict:
    a = _asset(asset_id)
    return proxies.prepare(a["workspace_id"], a["id"])


@router.get("/api/assets/{asset_id}/prepare")
def prepare_status(asset_id: str) -> dict:
    return proxies.status(_asset(asset_id))

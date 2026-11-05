"""Route-level ownership: every object named in an address must belong to the requesting workspace.

Installed as an app-wide FastAPI dependency (api.py), so it runs for every route, including routers added later.
An object of another workspace answers exactly like a missing one (404), so IDs reveal nothing. Desktop mode has a
single workspace and skips the lookups.
"""
from __future__ import annotations

from typing import Callable

from fastapi import HTTPException, Request

from .. import db
from . import principal
from . import settings as cloud_settings


def _one(sql: str, value: str) -> str | None:
    v = db.scalar(sql, (value,))
    return str(v) if v is not None else None


def project_workspace(project_id: str) -> str | None:
    return _one("SELECT workspace_id FROM projects WHERE id = ?", project_id)


def clip_workspace(clip_id: str) -> str | None:
    return _one("SELECT p.workspace_id FROM clips c JOIN projects p ON p.id = c.project_id WHERE c.id = ?", clip_id)


def version_workspace(version_id: str) -> str | None:
    return _one("SELECT p.workspace_id FROM clip_versions v JOIN clips c ON c.id = v.clip_id "
                "JOIN projects p ON p.id = c.project_id WHERE v.id = ?", version_id)


def publication_workspace(pub_id: str) -> str | None:
    return _one("SELECT p.workspace_id FROM publications u JOIN clips c ON c.id = u.clip_id "
                "JOIN projects p ON p.id = c.project_id WHERE u.id = ?", pub_id)


RESOLVERS: dict[str, Callable[[str], str | None]] = {
    "project_id": project_workspace,
    "clip_id": clip_workspace,
    "version_id": version_workspace,
    "pub_id": publication_workspace,
    "asset_id": lambda v: _one("SELECT workspace_id FROM assets WHERE id = ?", v),
    "upload_id": lambda v: _one("SELECT workspace_id FROM uploads WHERE id = ?", v),
    "video_id": lambda v: _one("SELECT workspace_id FROM studio_projects WHERE id = ?", v),
    "story_id": lambda v: _one("SELECT workspace_id FROM story_proposals WHERE id = ?", v),
    "connection_id": lambda v: _one("SELECT workspace_id FROM social_connections WHERE id = ?", v),
    "style_id": lambda v: _one("SELECT workspace_id FROM styles WHERE id = ?", v),
    "skill_id": lambda v: _one("SELECT workspace_id FROM skills WHERE id = ?", v),
    "reference_id": lambda v: _one("SELECT workspace_id FROM reference_videos WHERE id = ?", v),
    "import_id": lambda v: _one("SELECT workspace_id FROM media_imports WHERE id = ?", v),
    "request_id": lambda v: _one("SELECT workspace_id FROM edit_requests WHERE id = ?", v),
}
NOT_FOUND = {"project_id": "Project not found", "clip_id": "Clip not found", "version_id": "Version not found",
             "pub_id": "Publication not found"}


def check(request: Request) -> None:
    if not cloud_settings.enabled():
        return
    named = [name for name in request.path_params if name in RESOLVERS]
    try:
        mine = principal.workspace_id()
    except principal.NotSignedIn:
        if named:  # cannot happen behind the request guard; refuse rather than skip the check
            raise HTTPException(401, "Sign in to ClipForge.") from None
        return  # the public sign-in routes name no object
    for name, value in request.path_params.items():
        resolve = RESOLVERS.get(name)
        if resolve is None:
            continue
        owner = resolve(str(value))
        # Missing objects pass through, so each route keeps its own not-found answer; foreign ones look the same.
        if owner is not None and owner != mine:
            raise HTTPException(404, NOT_FOUND.get(name, "Not found"))


def workspace() -> str:
    """The workspace new objects of this request belong to ('local' on the desktop)."""
    return principal.workspace_id()

"""Multiple publishing connections: list, add, reconnect, rename, make default and disconnect.

Adding an account never disconnects or replaces another, and never changes the default or any queued, approved or
started post. Reconnect is bound to one connection: signing in to a different account during Reconnect is refused.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, secure
from ..cloud import principal
from . import jobs, tiktok, youtube
from .common import PublishError, app_request, challenge_hex, challenge_s256, local_only, redirect_uri, start_login

router = APIRouter()
LABELS = {"youtube": "YouTube", "tiktok": "TikTok"}


def health(acc: dict) -> dict:
    """What the owner needs to know about one connection, in words."""
    info = acc.get("info") or {}
    if acc["status"] == "disconnected" or not acc.get("has_tokens"):
        return {"state": "disconnected", "text": "Disconnected. Uploads to this account are paused.",
                "action": "reconnect"}
    if acc["status"] == "needs_reconnect" or info.get("needs_reconnect"):
        return {"state": "needs_reconnect", "text": "Sign-in expired or was revoked. Reconnect this account; "
                                                    "other accounts keep working.", "action": "reconnect"}
    return {"state": "ok", "text": "Connected", "action": ""}


def view(acc: dict) -> dict:
    pubs = [p for p in db.select("publications", "connection_id = ?", (acc["id"],)) if p["status"] in jobs.ACTIVE]
    return {"id": acc["id"], "platform": acc["platform"], "label": LABELS.get(acc["platform"], acc["platform"]),
            "account_id": acc["external_id"], "display_name": acc.get("display_name") or "",
            "nickname": acc.get("nickname") or "", "avatar": acc.get("avatar_url") or "",
            "scopes": acc.get("scopes") or [], "is_default": acc["is_default"], "status": acc["status"],
            "health": health(acc), "connected_at": acc.get("connected_at"), "active_uploads": len(pubs)}


def _mine(connection_id: str) -> dict:
    acc = db.get_connection(connection_id)
    if not acc or acc["workspace_id"] != principal.workspace_id():
        raise HTTPException(404, "Connection not found")
    return acc


@router.get("/api/connections", dependencies=[Depends(local_only)])
def list_connections(platform: str = "") -> dict:
    rows = db.list_connections(principal.workspace_id(), platform or None)
    return {"connections": [view(a) for a in rows], "protection": secure.protection()}


def _start(request: Request, platform: str, operation: str, connection_id: str = "") -> dict:
    settings = db.get_settings()
    if platform == "youtube":
        if not youtube.configured(settings):
            raise PublishError("YouTube is not set up yet.", youtube.SETUP_FIX, "setup")
        uri = redirect_uri(request, "youtube")
        state, verifier = start_login("youtube", uri, operation, connection_id)
        return {"auth_url": youtube.auth_url(settings, uri, state, challenge_s256(verifier))}
    if platform == "tiktok":
        if not tiktok.configured(settings):
            raise PublishError("TikTok is not set up yet.", tiktok.SETUP_FIX, "setup")
        uri = redirect_uri(request, "tiktok")
        state, verifier = start_login("tiktok", uri, operation, connection_id)
        return {"auth_url": tiktok.auth_url(settings, uri, state, challenge_hex(verifier))}
    raise HTTPException(404, "Unknown platform")


@router.post("/api/connections/{platform}/add", dependencies=[Depends(app_request)])
def add(platform: str, request: Request) -> dict:
    """Start signing in to another account. Existing connections are not touched."""
    return _start(request, platform, "add")


@router.post("/api/connections/{connection_id}/reconnect", dependencies=[Depends(app_request)])
def reconnect(connection_id: str, request: Request) -> dict:
    acc = _mine(connection_id)
    return _start(request, acc["platform"], "reconnect", acc["id"])


class ConnectionPatch(BaseModel):
    nickname: str | None = Field(default=None, max_length=60)
    make_default: bool | None = None


@router.patch("/api/connections/{connection_id}", dependencies=[Depends(app_request)])
def patch(connection_id: str, body: ConnectionPatch) -> dict:
    acc = _mine(connection_id)
    if body.nickname is not None:
        nickname = " ".join(body.nickname.split())
        if any(ord(c) < 32 for c in nickname):
            raise HTTPException(422, "Use a plain one-line name.")
        db.update_connection(acc["id"], nickname=nickname)
    if body.make_default:
        if acc["status"] != "connected":
            raise HTTPException(409, "Reconnect this account before making it the default.")
        db.set_default_connection(acc["id"])
    return view(db.get_connection(acc["id"]))  # type: ignore[arg-type]


@router.post("/api/connections/{connection_id}/disconnect", dependencies=[Depends(app_request)])
def disconnect(connection_id: str) -> dict:
    """Disconnect one account. An upload already transferring to it is refused rather than broken halfway:
    its session would be lost. Other accounts, and their queued posts, are not affected."""
    acc = _mine(connection_id)
    busy = [p for p in db.select("publications", "connection_id = ?", (acc["id"],))
            if p["status"] in ("uploading",) or jobs.unknown_outcome(p)]
    if busy:
        raise HTTPException(409, f"An upload to “{acc.get('display_name')}” is under way or its outcome is not "
                                 "confirmed yet. Let it finish (or resolve it on its post page) before disconnecting.")
    settings = db.get_settings()
    if acc["platform"] == "youtube":
        youtube.disconnect(settings, acc["id"])
    else:
        tiktok.disconnect(settings, acc["id"])
    return view(db.get_connection(acc["id"]))  # type: ignore[arg-type]


def require_connection(platform: str, connection_id: str) -> dict:
    """The connection a new publication goes to: the named one (it must be this workspace's, on this platform and
    connected), or the platform default when none is named. Used by the publish endpoints."""
    if not connection_id:
        connection_id = db.default_connection_id(platform, principal.workspace_id())
    acc = db.get_connection(connection_id) if connection_id else None
    if not acc or acc["workspace_id"] != principal.workspace_id() or acc["platform"] != platform:
        raise PublishError(f"Choose a connected {LABELS.get(platform, platform)} account.",
                           "Add one in Accounts.", "not_connected")
    if acc["status"] != "connected" or not acc.get("has_tokens"):
        name = acc.get("nickname") or acc.get("display_name") or "This account"
        raise PublishError(f"{name} is not connected.", "Reconnect it in Accounts.", "not_connected")
    return acc


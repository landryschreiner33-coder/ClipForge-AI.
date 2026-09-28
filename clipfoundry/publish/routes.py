"""REST endpoints for accounts and publishing. Every publish needs an explicit confirmation from the publish screen."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .. import db, secure
from . import jobs, youtube
from .common import (PublishError, app_request, callback_page, challenge_s256, finish_login, local_only,
                     redirect_uri, start_login)

router = APIRouter()
PLATFORMS = ("youtube",)


def _youtube_state(settings: dict) -> dict:
    acc = db.get_account("youtube") or {}
    info = acc.get("info") or {}
    return {
        "configured": youtube.configured(settings), "connected": bool(acc.get("has_tokens")),
        "needs_reconnect": bool(info.get("needs_reconnect")), "name": acc.get("display_name", ""),
        "account_id": acc.get("account_id", ""), "avatar": acc.get("avatar_url", ""),
        "scopes": acc.get("scopes") or [], "connected_at": acc.get("connected_at"),
        "analytics": youtube.SCOPES[2] in (acc.get("scopes") or []),
        "verified": bool(settings.get("youtube_project_verified")),
        "restriction": "" if settings.get("youtube_project_verified") else youtube.UNVERIFIED_NOTE,
        "setup": youtube.SETUP_FIX, "testing_note": youtube.TESTING_NOTE,
    }


@router.get("/api/publish/accounts", dependencies=[Depends(local_only)])
def accounts() -> dict:
    settings = db.get_settings()
    return {"youtube": _youtube_state(settings), "protection": secure.protection()}


# ------------------------------------------------------------------ YouTube sign-in
@router.post("/api/publish/youtube/connect", dependencies=[Depends(app_request)])
def youtube_connect(request: Request) -> dict:
    settings = db.get_settings()
    if not youtube.configured(settings):
        raise PublishError("YouTube is not set up yet.", youtube.SETUP_FIX, "setup")
    uri = redirect_uri(request, "youtube")
    state, verifier = start_login("youtube", uri)
    return {"auth_url": youtube.auth_url(settings, uri, state, challenge_s256(verifier))}


@router.get("/api/oauth/youtube/callback", dependencies=[Depends(local_only)], response_class=HTMLResponse)
def youtube_callback(state: str = "", code: str = "", error: str = "") -> str:
    if error:
        why = "you declined access" if error == "access_denied" else f"Google reported “{error}”"
        return callback_page(False, "YouTube was not connected", f"Sign-in stopped because {why}.",
                             "Click Connect YouTube again and allow access.")
    try:
        login = finish_login("youtube", state)
        acc = youtube.exchange_code(db.get_settings(), code, login.verifier, login.redirect_uri)
    except PublishError as exc:
        return callback_page(False, "YouTube was not connected", str(exc), exc.fix)
    return callback_page(True, "YouTube connected", f"ClipFoundry can now upload to the channel "
                                                    f"“{acc.get('display_name', '')}”. Your password was never "
                                                    "shared with ClipFoundry.")


@router.post("/api/publish/youtube/disconnect", dependencies=[Depends(app_request)])
def youtube_disconnect() -> dict:
    youtube.disconnect(db.get_settings())
    return accounts()


# ------------------------------------------------------------------ publishing
class PublishBody(BaseModel):
    title: str = ""
    description: str = ""
    tags: list[str] = []
    privacy: str = ""
    made_for_kids: bool | None = None
    confirm: bool = False


def _video_for(clip: dict) -> tuple[str, dict | None]:
    path = clip.get("output_path") or ""
    if clip.get("status") != "ready" or not path or not Path(path).exists():
        raise PublishError("This clip is not rendered yet.", "Wait for the render to finish, or re-render the clip.")
    return path, None


@router.post("/api/clips/{clip_id}/publish/{platform}", dependencies=[Depends(app_request)])
def publish(clip_id: str, platform: str, body: PublishBody) -> dict:
    if platform not in PLATFORMS:
        raise HTTPException(404, "Unknown platform")
    if not body.confirm:
        raise PublishError("Publishing needs your explicit confirmation.", "Press the Publish button and confirm.")
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(404, "Clip not found")
    video_path, version = _video_for(clip)
    if any(p["status"] in jobs.ACTIVE for p in db.list_publications(clip_id, platform)):
        raise HTTPException(409, "This clip is already being uploaded to this platform.")
    settings = db.get_settings()
    options: dict = {}
    if platform == "youtube":
        if not (db.get_account("youtube") or {}).get("has_tokens"):
            raise PublishError("YouTube is not connected.", "Click Connect YouTube first.", "not_connected")
        if body.made_for_kids is None:
            raise PublishError("Say whether this video is made for kids.",
                               "YouTube requires this answer (COPPA). Choose Yes or No on the publish screen.")
        youtube.video_body(body.title, body.description, body.tags, body.privacy, body.made_for_kids,
                           settings.get("youtube_category_id") or "22")  # validate before queueing
        options["made_for_kids"] = body.made_for_kids
    pub = db.create_publication(
        clip_id, platform, project_id=clip["project_id"], status="queued", message="Waiting to upload",
        title=body.title.strip(), description=body.description.strip(), tags=body.tags,
        requested_privacy=body.privacy, video_path=video_path, version_id=(version or {}).get("id", ""),
        options=options, features=jobs.feature_snapshot(clip, version))
    jobs.worker.submit(pub["id"])
    return pub


@router.get("/api/clips/{clip_id}/publications", dependencies=[Depends(local_only)])
def clip_publications(clip_id: str) -> list[dict]:
    return db.list_publications(clip_id)


def _pub_or_404(pub_id: str) -> dict:
    pub = db.get_publication(pub_id)
    if not pub:
        raise HTTPException(404, "Publication not found")
    return pub


@router.get("/api/publications/{pub_id}", dependencies=[Depends(local_only)])
def get_publication(pub_id: str) -> dict:
    return _pub_or_404(pub_id)


@router.post("/api/publications/{pub_id}/cancel", dependencies=[Depends(app_request)])
def cancel_publication(pub_id: str) -> dict:
    pub = _pub_or_404(pub_id)
    if pub["status"] in ("queued", "uploading"):
        jobs.worker.cancel(pub_id)
    return db.get_publication(pub_id) or pub


@router.post("/api/publications/{pub_id}/refresh", dependencies=[Depends(app_request)])
def refresh_publication(pub_id: str) -> dict:
    return jobs.refresh(_pub_or_404(pub_id))

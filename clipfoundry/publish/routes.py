"""REST endpoints for accounts and publishing. Every publish needs an explicit confirmation from the publish screen."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from .. import audience, db, learning, secure
from . import jobs, stats, tiktok, youtube
from .common import (PublishError, app_request, callback_page, challenge_hex, challenge_s256, finish_login,
                     local_only, redirect_uri, start_login)

router = APIRouter()
PLATFORMS = ("youtube", "tiktok")


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


def _tiktok_state(settings: dict, request: Request | None) -> dict:
    acc = db.get_account("tiktok") or {}
    granted = acc.get("scopes") or []
    audited = bool(settings.get("tiktok_app_audited"))
    return {
        "configured": tiktok.configured(settings), "connected": bool(acc.get("has_tokens")),
        "needs_reconnect": bool((acc.get("info") or {}).get("needs_reconnect")), "name": acc.get("display_name", ""),
        "account_id": acc.get("account_id", ""), "avatar": acc.get("avatar_url", ""), "scopes": granted,
        "connected_at": acc.get("connected_at"), "audited": audited,
        "can_direct_post": "video.publish" in granted, "can_inbox": "video.upload" in granted,
        "can_read_stats": "video.list" in granted,
        "restriction": "" if audited else tiktok.UNAUDITED_NOTE, "setup": tiktok.SETUP_FIX,
        "redirect_uri": redirect_uri(request, "tiktok") if request else "",
        "requested_scopes": tiktok.scopes(settings),
    }


@router.get("/api/publish/accounts", dependencies=[Depends(local_only)])
def accounts(request: Request) -> dict:
    settings = db.get_settings()
    return {"youtube": _youtube_state(settings), "tiktok": _tiktok_state(settings, request),
            "protection": secure.protection()}


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
def youtube_disconnect(request: Request) -> dict:
    youtube.disconnect(db.get_settings())
    return accounts(request)


# ------------------------------------------------------------------ TikTok sign-in
@router.post("/api/publish/tiktok/connect", dependencies=[Depends(app_request)])
def tiktok_connect(request: Request) -> dict:
    settings = db.get_settings()
    if not tiktok.configured(settings):
        raise PublishError("TikTok is not set up yet.", tiktok.SETUP_FIX, "setup")
    uri = redirect_uri(request, "tiktok")
    state, verifier = start_login("tiktok", uri)
    return {"auth_url": tiktok.auth_url(settings, uri, state, challenge_hex(verifier))}


@router.get("/api/oauth/tiktok/callback", dependencies=[Depends(local_only)], response_class=HTMLResponse)
def tiktok_callback(state: str = "", code: str = "", error: str = "", error_description: str = "") -> str:
    if error:
        why = "you declined access" if error == "access_denied" else f"TikTok reported “{error_description or error}”"
        return callback_page(False, "TikTok was not connected", f"Sign-in stopped because {why}.",
                             "Click Connect TikTok again. If TikTok mentions the redirect URI or scopes, check "
                             "them in your TikTok developer app against Settings → Publishing → TikTok.")
    try:
        login = finish_login("tiktok", state)
        acc = tiktok.exchange_code(db.get_settings(), code, login.verifier, login.redirect_uri)
    except PublishError as exc:
        return callback_page(False, "TikTok was not connected", str(exc), exc.fix)
    return callback_page(True, "TikTok connected", f"ClipFoundry can now upload to “{acc.get('display_name', '')}”. "
                                                   "Your password was never shared with ClipFoundry.")


@router.post("/api/publish/tiktok/disconnect", dependencies=[Depends(app_request)])
def tiktok_disconnect(request: Request) -> dict:
    tiktok.disconnect(db.get_settings())
    return accounts(request)


@router.get("/api/publish/tiktok/creator", dependencies=[Depends(local_only)])
def tiktok_creator() -> dict:
    """Nickname, privacy options and interaction settings for the publish screen (read fresh every time)."""
    return tiktok.creator_info(tiktok.Token(db.get_settings()))


# ------------------------------------------------------------------ publishing
class PublishBody(BaseModel):
    title: str = ""
    description: str = ""          # YouTube description, or the TikTok caption
    tags: list[str] = []
    privacy: str = ""              # YouTube: public/unlisted/private. TikTok: one of creator_info's options
    made_for_kids: bool | None = None
    mode: str = "direct"           # TikTok: direct (Direct Post) or inbox (draft in the TikTok app)
    allow_comment: bool = False
    allow_duet: bool = False
    allow_stitch: bool = False
    disclose: bool = False         # commercial content disclosure
    brand_organic: bool = False    # "Your brand"
    brand_content: bool = False    # "Branded content" (paid partnership)
    confirm: bool = False


def _video_for(clip: dict) -> tuple[str, dict | None]:
    """The file to upload: the version chosen on the publish screen, or the original clip."""
    if clip.get("active_version"):
        v = db.get_version(clip["active_version"])
        if not v or v["status"] != "ready" or not Path(v.get("output_path") or "").exists():
            raise PublishError("The chosen version is not rendered.", "Render it again or choose another version.")
        return v["output_path"], v
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
    # the audience policy applies to manual uploads exactly as to Autopilot (audience.py); TikTok's own rules are
    # checked first so their wording stays, then the policy (below)
    if platform == "youtube":
        audience.check(platform, body.privacy, settings)
    elif audience.intent(platform, settings) == audience.LOCAL_ONLY:
        audience.check(platform, body.privacy, settings, mode=body.mode)
    if platform == "youtube":
        if not (db.get_account("youtube") or {}).get("has_tokens"):
            raise PublishError("YouTube is not connected.", "Click Connect YouTube first.", "not_connected")
        if body.made_for_kids is None:
            raise PublishError("Say whether this video is made for kids.",
                               "YouTube requires this answer (COPPA). Choose Yes or No on the publish screen.")
        youtube.video_body(body.title, body.description, body.tags, body.privacy, body.made_for_kids,
                           settings.get("youtube_category_id") or "22")  # validate before queueing
        options["made_for_kids"] = body.made_for_kids
    mode = "direct"
    if platform == "tiktok":
        acc = db.get_account("tiktok") or {}
        if not acc.get("has_tokens"):
            raise PublishError("TikTok is not connected.", "Click Connect TikTok first.", "not_connected")
        mode = body.mode if body.mode in ("direct", "inbox") else "direct"
        needed = "video.publish" if mode == "direct" else "video.upload"
        if needed not in (acc.get("scopes") or []):
            raise PublishError(f"ClipFoundry does not have TikTok's {needed} permission.",
                               "Use the other posting option, or add the Content Posting API to your TikTok app and "
                               "connect again.", "scope")
        options = {k: getattr(body, k) for k in ("allow_comment", "allow_duet", "allow_stitch", "disclose",
                                                 "brand_organic", "brand_content")}
        options["duration"] = float((version or clip).get("duration") or 0)
        if not body.disclose:
            options["brand_organic"] = options["brand_content"] = False
        info = tiktok.creator_info(tiktok.Token(settings)) if mode == "direct" else None
        tiktok.validate(body.description, body.privacy, options, mode, settings, info, options["duration"])
        audience.check(platform, body.privacy, settings, mode=mode, creator=info)
    pub = db.create_publication(
        clip_id, platform, project_id=clip["project_id"], mode=mode, status="queued", message="Waiting to upload",
        title=body.title.strip(), description=body.description.strip(), tags=body.tags,
        requested_privacy=body.privacy, video_path=video_path, version_id=(version or {}).get("id", ""),
        options=options, features=jobs.feature_snapshot(clip, version))
    jobs.worker.submit(pub["id"])
    return pub


def _with_stats(pubs: list[dict]) -> list[dict]:
    latest = db.latest_performance()
    return [{**p, "stats": latest.get(p["id"])} for p in pubs]


@router.get("/api/clips/{clip_id}/publications", dependencies=[Depends(local_only)])
def clip_publications(clip_id: str) -> list[dict]:
    return _with_stats(db.list_publications(clip_id))


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
    return _with_stats([jobs.refresh(_pub_or_404(pub_id))])[0]


# ------------------------------------------------------------------ real performance (never estimated)
@router.post("/api/publications/{pub_id}/stats", dependencies=[Depends(app_request)])
def refresh_stats(pub_id: str) -> dict:
    stats.refresh(_pub_or_404(pub_id))
    return _with_stats([_pub_or_404(pub_id)])[0]


@router.get("/api/publications/{pub_id}/stats", dependencies=[Depends(local_only)])
def stats_history(pub_id: str) -> list[dict]:
    _pub_or_404(pub_id)
    return db.performance_history(pub_id)


class LinkBody(BaseModel):
    url: str


@router.post("/api/publications/{pub_id}/link", dependencies=[Depends(app_request)])
def link_tiktok_post(pub_id: str, body: LinkBody) -> dict:
    """After posting an inbox draft (or an 'Only me' post made public) in the TikTok app, link the actual post so
    its statistics can be read."""
    import re

    pub = _pub_or_404(pub_id)
    if pub["platform"] != "tiktok":
        raise HTTPException(400, "Only TikTok posts can be linked")
    m = re.search(r"/video/(\d{6,25})", body.url) or re.fullmatch(r"\s*(\d{6,25})\s*", body.url)
    if not m:
        raise PublishError("That does not look like a TikTok video link.",
                           "Copy the link from the TikTok app (Share → Copy link) or tiktok.com, e.g. "
                           "https://www.tiktok.com/@you/video/7300000000000000000.")
    post_id = m.group(1)
    username = (pub.get("info") or {}).get("username", "")
    url = body.url.strip() if body.url.strip().startswith("http") else tiktok.post_url(username, post_id)
    db.update_publication(pub_id, url=url, info={**(pub.get("info") or {}), "post_ids": [post_id], "linked": True})
    return refresh_stats(pub_id)


@router.post("/api/performance/refresh", dependencies=[Depends(app_request)])
def refresh_all_stats() -> dict:
    return stats.refresh_all()


@router.get("/api/performance", dependencies=[Depends(local_only)])
def performance_overview() -> dict:
    """Totals over the latest real snapshot of each publication (metrics a platform does not report are skipped,
    and the counts say how many publications each total covers)."""
    latest = db.latest_performance()
    pubs = [p for p in db.list_publications() if p["status"] in ("done", "action_needed")]
    settings = db.get_settings()
    counted = [p for p in pubs if p["platform"] != "youtube" or learning.youtube_allowed(settings)]
    totals = {}
    for key in ("views", "likes", "comments", "shares", "watch_time_minutes"):
        vals = [latest[p["id"]][key] for p in counted if p["id"] in latest and latest[p["id"]].get(key) is not None]
        totals[key] = {"total": round(sum(vals), 1) if vals else None, "publications": len(vals)}
    excluded = len(pubs) - len(counted)
    last = max((s["fetched_at"] for s in latest.values()), default=None)
    items = []
    for p in pubs[:50]:
        clip = db.get_clip(p["clip_id"]) or {}
        items.append({"id": p["id"], "clip_id": p["clip_id"], "platform": p["platform"], "title": p["title"] or
                      clip.get("title", ""), "privacy": p.get("privacy") or p["requested_privacy"], "url": p["url"],
                      "created_at": p["created_at"], "viral_potential": (p.get("features") or {}).get("viral_potential"),
                      "stats": latest.get(p["id"])})
    return {"published": len(pubs), "with_stats": sum(1 for p in pubs if p["id"] in latest), "totals": totals,
            "last_refreshed": last, "items": items, "check": learning.ranking_check(settings=settings),
            "totals_note": learning.YOUTUBE_NOTE if excluded else "", "excluded_from_totals": excluded}


@router.get("/api/performance/dataset", dependencies=[Depends(local_only)])
def performance_dataset(format: str = "csv") -> Response:  # noqa: A002 - query parameter name
    rows = learning.dataset()
    if format == "json":
        import json

        return Response(json.dumps(rows, indent=2), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="clipfoundry-performance.json"'})
    return Response("\ufeff" + learning.to_csv(rows), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="clipfoundry-performance.csv"'})


# ------------------------------------------------------------------ selected audience (audience.py)
class AudienceBody(BaseModel):
    youtube_intent: str | None = None
    tiktok_intent: str | None = None
    tiktok_group: str | None = None
    tiktok_private_confirmed: bool | None = None
    tiktok_followers_reviewed: bool | None = None
    youtube_viewers_label: str | None = None
    youtube_group_changed: bool = False
    tiktok_group_changed: bool = False
    publish_paused: bool | None = None


def audience_view() -> dict:
    settings = db.get_settings()
    return {"destinations": audience.summary(settings), "scope": audience.SCOPE_TEXT,
            "setup_labels": audience.SETUP_LABELS, "publish_paused": bool(settings.get("autopilot_publish_paused")),
            "tiktok_private_confirmed": bool(settings.get("audience_tiktok_private_confirmed")),
            "tiktok_followers_reviewed": bool(settings.get("audience_tiktok_followers_reviewed")),
            "youtube_viewers_label": settings.get("audience_youtube_viewers_label") or "",
            "migrated_from": settings.get("audience_migrated_from") or "",
            "youtube_share_steps": audience.YOUTUBE_SHARE_STEPS}


@router.get("/api/audience", dependencies=[Depends(local_only)])
def get_audience() -> dict:
    return audience_view()


@router.post("/api/audience", dependencies=[Depends(app_request)])
def save_audience(body: AudienceBody) -> dict:
    """The user's own audience choices. Nothing here invites anyone or changes an account; it only decides what
    ClipFoundry may request. Selected audience on TikTok needs the private-account confirmation first."""
    settings = db.get_settings()
    patch: dict = {}
    for name, key in (("youtube_intent", "audience_youtube_intent"), ("tiktok_intent", "audience_tiktok_intent"),
                      ("tiktok_group", "audience_tiktok_group"),
                      ("tiktok_private_confirmed", "audience_tiktok_private_confirmed"),
                      ("tiktok_followers_reviewed", "audience_tiktok_followers_reviewed"),
                      ("youtube_viewers_label", "audience_youtube_viewers_label"),
                      ("publish_paused", "autopilot_publish_paused")):
        value = getattr(body, name)
        if value is not None:
            patch[key] = value
    for key in ("audience_youtube_intent", "audience_tiktok_intent"):
        if key in patch and str(patch[key]).upper() not in audience.INTENTS:
            raise HTTPException(400, "Choose: keep on this PC, private staging, or selected audience")
    tiktok_selected = str(patch.get("audience_tiktok_intent", settings.get("audience_tiktok_intent"))).upper() \
        == audience.SELECTED_AUDIENCE
    if tiktok_selected and not patch.get("audience_tiktok_private_confirmed",
                                         settings.get("audience_tiktok_private_confirmed")):
        raise HTTPException(400, "Confirm that your TikTok account is private first. ClipFoundry never changes it.")
    if tiktok_selected and not patch.get("audience_tiktok_followers_reviewed",
                                         settings.get("audience_tiktok_followers_reviewed")):
        raise HTTPException(400, "Review your approved followers in the TikTok app first: Followers means all of them.")
    for p in audience.PLATFORMS:
        if getattr(body, f"{p}_group_changed"):
            patch[f"audience_{p}_group_version"] = int(settings.get(f"audience_{p}_group_version") or 1) + 1
    db.save_settings(patch)
    return audience_view()


@router.post("/api/publications/{pub_id}/viewers-invited", dependencies=[Depends(app_request)])
def viewers_invited(pub_id: str) -> dict:
    """The user says they shared this private YouTube video with their chosen viewers in Studio. Recorded as the
    user's confirmation, never as independent verification."""
    pub = _pub_or_404(pub_id)
    a = (pub.get("info") or {}).get("audience") or {}
    if pub["platform"] != "youtube" or pub["status"] != "done" or a.get("intent") != audience.SELECTED_AUDIENCE:
        raise HTTPException(400, "Only a private YouTube upload meant for your selected viewers can be marked shared.")
    info = {**(pub.get("info") or {}), "audience": {**a, "setup": audience.SETUP_USER_CONFIRMED,
                                                     "confirmed_at": time.time(), "evidence": "user"}}
    db.update_publication(pub_id, info=info, message="Viewers invited (confirmed by you).")
    from ..autopilot import state

    state.resolve(f"share:{pub_id}")
    return db.get_publication(pub_id) or pub


@router.post("/api/publications/{pub_id}/retarget", dependencies=[Depends(app_request)])
def retarget(pub_id: str) -> dict:
    """Explicitly turn one owner-only staged YouTube upload into a selected-audience video (the user then invites
    viewers in Studio). One clip at a time, never in bulk during a migration; nothing changes on YouTube."""
    pub = _pub_or_404(pub_id)
    a = (pub.get("info") or {}).get("audience") or {}
    settings = db.get_settings()
    if pub["platform"] != "youtube" or pub["status"] != "done" or (pub.get("privacy") or "") != "private":
        raise HTTPException(400, "Only a private YouTube upload can be retargeted.")
    if audience.intent("youtube", settings) != audience.SELECTED_AUDIENCE:
        raise HTTPException(400, "Set YouTube to Selected audience first (Settings → Integrations).")
    if a.get("intent") == audience.SELECTED_AUDIENCE:
        return pub
    d = audience.plan("youtube", settings)
    info = audience.record(pub.get("info") or {}, d, pub.get("privacy") or "", "user_retarget")
    db.update_publication(pub_id, info=info, message="Retargeted to your selected viewers: share it in YouTube Studio.")
    return db.get_publication(pub_id) or pub

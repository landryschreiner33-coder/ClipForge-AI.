"""TikTok through the official Content Posting API (and Login Kit for desktop).

Sign-in: TikTok's OAuth page with PKCE (TikTok's desktop flow hex-encodes the SHA-256 challenge) and a redirect to
http://127.0.0.1:<port>/api/oauth/tiktok/callback, which must be registered in your TikTok developer app. ClipFoundry
receives tokens, never your TikTok password.

Two official ways to post:
* Direct Post (scope video.publish): the video is posted to your profile with the privacy you choose. Until TikTok
  audits your app, it only accepts posts from private accounts, forces "Only me" (SELF_ONLY) and allows a few users
  per day.
* Upload to inbox (scope video.upload): the video lands in your TikTok inbox as a draft; you finish and post it in the
  TikTok app. This works without the audit and is ClipFoundry's fallback.

ClipFoundry follows TikTok's Content Sharing Guidelines: it shows the creator's nickname, reads the privacy options
before each post and never pre-selects one, leaves comments/duet/stitch off unless you turn them on (and greys them
out when your account disables them), offers the commercial content disclosure, and shows the Music Usage
Confirmation. No scraping and no unofficial automation.
"""
from __future__ import annotations

import os
import time
from typing import Callable
from urllib.parse import urlencode

import httpx

from .. import db
from .common import (SHORT_WAIT, Cancelled, PublishError, client, network_errors, retry_after, save_tokens,
                     sleep_exactly, with_retry_after)

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API_URL = "https://open.tiktokapis.com/v2"
OEMBED_URL = "https://www.tiktok.com/oembed"  # public embed API: a video's author, used to confirm channel claims
MIN_CHUNK = 5 * 1024 * 1024
CHUNK = 10 * 1024 * 1024  # between TikTok's 5 MB minimum and 64 MB maximum
POLL_SECONDS = 3.0
POLL_TIMEOUT = 10 * 60
CAPTION_MAX = 2200  # UTF-16 code units
PRIVACY_LABELS = {"PUBLIC_TO_EVERYONE": "Everyone", "MUTUAL_FOLLOW_FRIENDS": "Friends",
                  "FOLLOWER_OF_CREATOR": "Followers", "SELF_ONLY": "Only me"}
UPLOAD_PAGE = "https://www.tiktok.com/tiktokstudio/upload"
MUSIC_CONFIRMATION = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"
BRANDED_POLICY = "https://www.tiktok.com/legal/page/global/bc-policy/en"

UNAUDITED_NOTE = (
    "Until TikTok audits your developer app, Direct Post only works for private TikTok accounts, every post is "
    "limited to 'Only me', and only a few users can post per day. Use 'Send to TikTok inbox' instead: the video "
    "arrives as a draft in the TikTok app and you post it from there with any privacy. Or export the clip and upload "
    "it on tiktok.com/tiktokstudio/upload."
)
SETUP_FIX = ("Settings → Publishing → TikTok: create an app on developers.tiktok.com with Login Kit (Desktop) and the "
             "Content Posting API, register the redirect URI shown in Settings, and paste the client key and secret.")
RECONNECT_FIX = "Click Connect TikTok again (Settings → Publishing or the publish screen)."
PROCESSING_NOTE = "It may take a few minutes for the video to be processed and appear on your profile."


def configured(settings: dict) -> bool:
    return bool(settings.get("tiktok_client_key") and settings.get("tiktok_client_secret"))


def scopes(settings: dict) -> list[str]:
    s = ["user.info.basic", "video.upload"]
    if settings.get("tiktok_direct_post", True):
        s.append("video.publish")
    if settings.get("tiktok_read_stats", True):
        s.append("video.list")
    return s


def auth_url(settings: dict, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_key": settings["tiktok_client_key"], "scope": ",".join(scopes(settings)), "response_type": "code",
        "redirect_uri": redirect_uri, "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    })


def _json(r: httpx.Response) -> dict:
    try:
        data = r.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


@network_errors("TikTok")
def _token_request(settings: dict, data: dict) -> dict:
    with client(30) as c:
        r = c.post(f"{API_URL}/oauth/token/", data={"client_key": settings["tiktok_client_key"],
                                                   "client_secret": settings["tiktok_client_secret"], **data},
                   headers={"Content-Type": "application/x-www-form-urlencoded"})
    body = _json(r)
    if r.status_code != 200 or not body.get("access_token"):
        err = body.get("error") or ""
        if isinstance(err, dict):
            err = err.get("code", "")
        if err == "invalid_grant":
            raise PublishError("TikTok no longer accepts ClipFoundry's access to your account (it expired or was "
                               "revoked).", RECONNECT_FIX, "reconnect")
        if err in ("invalid_client", "unauthorized_client"):
            raise PublishError("TikTok rejected the client key or secret.", SETUP_FIX, "setup")
        raise PublishError(f"TikTok sign-in failed: {body.get('error_description') or err or r.status_code}.",
                           RECONNECT_FIX)
    return body


def exchange_code(settings: dict, code: str, verifier: str, redirect_uri: str) -> dict:
    tok = _token_request(settings, {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri,
                                    "code_verifier": verifier})
    granted = sorted(s for s in (tok.get("scope") or "").replace(" ", "").split(",") if s)
    if "video.upload" not in granted and "video.publish" not in granted:
        raise PublishError("The permission to upload videos was not granted.",
                           "Connect again and allow ClipFoundry to upload videos on TikTok's permission screen.")
    user = user_info(tok["access_token"])
    db.save_account("tiktok", tokens=save_tokens("tiktok", tok), account_id=tok.get("open_id", ""),
                    display_name=user.get("display_name", ""), avatar_url=user.get("avatar_url", ""),
                    scopes=granted, info={"needs_reconnect": False})
    return db.get_account("tiktok") or {}


class Token:
    def __init__(self, settings: dict):
        self.settings = settings

    def get(self, force: bool = False) -> str:
        tokens = db.account_tokens("tiktok")
        if not tokens:
            raise PublishError("TikTok is not connected.", RECONNECT_FIX, "not_connected")
        if not force and tokens["expires_at"] - 90 > time.time():
            return tokens["access_token"]
        if not tokens.get("refresh_token") or tokens.get("refresh_expires_at", time.time() + 1) < time.time():
            raise PublishError("The TikTok connection has expired.", RECONNECT_FIX, "reconnect")
        try:
            tok = _token_request(self.settings, {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]})
        except PublishError as exc:
            if exc.code == "reconnect":
                db.save_account("tiktok", info={"needs_reconnect": True})
            raise
        db.save_account("tiktok", tokens=save_tokens("tiktok", tok))
        return tok["access_token"]


@network_errors("TikTok")
def disconnect(settings: dict) -> None:
    tokens = db.account_tokens("tiktok") or {}
    if tokens.get("access_token") and configured(settings):
        try:
            with client(15) as c:
                c.post(f"{API_URL}/oauth/revoke/", data={"client_key": settings["tiktok_client_key"],
                                                        "client_secret": settings["tiktok_client_secret"],
                                                        "token": tokens["access_token"]})
        except httpx.HTTPError:
            pass
    db.delete_account("tiktok")


# ------------------------------------------------------------------ API errors
ERRORS = {
    "unaudited_client_can_only_post_to_private_accounts": (
        "TikTok only accepts Direct Posts from unaudited apps when your TikTok account is private.",
        "Use 'Send to TikTok inbox' (works without the audit), set your TikTok account to private for testing, or "
        "export the clip and upload it on tiktok.com/tiktokstudio/upload."),
    "reached_active_user_cap": (
        "Your TikTok app reached the daily limit of users who can post through an unaudited app.",
        "Try again tomorrow, use 'Send to TikTok inbox', or apply for TikTok's audit."),
    "spam_risk_too_many_posts": ("TikTok's daily posting limit for this account has been reached.",
                                 "Try again tomorrow."),
    "spam_risk_too_many_pending_share": ("There are too many unfinished drafts in your TikTok inbox.",
                                         "Post or delete the pending drafts in the TikTok app, then try again."),
    "spam_risk_user_banned_from_posting": ("TikTok currently does not allow this account to post.",
                                           "Check your account status in the TikTok app."),
    "privacy_level_option_mismatch": ("TikTok does not offer the chosen privacy option for this account.",
                                      "Pick one of the options shown on the publish screen."),
    "scope_not_authorized": ("ClipFoundry was not given this TikTok permission.",
                             "Make sure the Content Posting API is added to your TikTok app, then connect again."),
    "access_token_invalid": ("TikTok did not accept the access token.", RECONNECT_FIX),
    "rate_limit_exceeded": ("TikTok is rate limiting requests right now.", "Wait a minute and try again."),
    "file_format_check_failed": ("TikTok could not read the video file.", "Re-render the clip and try again."),
    "duration_check_failed": ("The video is too long for this account on TikTok.", "Trim the clip."),
    "frame_rate_check_failed": ("TikTok rejected the video's frame rate.", "Set Settings → Max frame rate to 30."),
    "picture_size_check_failed": ("TikTok rejected the video size.", "Re-render the clip."),
    "video_pull_failed": ("TikTok could not receive the video.", "Publish again."),
    "publish_cancelled": ("The post was cancelled on TikTok.", ""),
    "auth_removed": ("ClipFoundry's access was removed in TikTok.", RECONNECT_FIX),
    "user_banned_from_posting": ("TikTok currently does not allow this account to post.",
                                 "Check your account status in the TikTok app."),
    "internal": ("TikTok had an internal error.", "Try again in a few minutes."),
}


def api_error(code: str, message: str = "", status: int = 0) -> PublishError:
    if code in ERRORS:
        text, fix = ERRORS[code]
        return PublishError(text, fix, code)
    return PublishError(f"TikTok API error{f' {status}' if status else ''}: {message or code}.", code=code)


@network_errors("TikTok")
def _call(token: Token, path: str, body: dict | None = None, method: str = "POST", params: dict | None = None,
          *, cancelled: Callable[[], bool] = lambda: False) -> dict:
    with client(30) as c:
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {token.get(force=attempt > 0)}",
                       "Content-Type": "application/json; charset=UTF-8"}
            if cancelled():
                raise Cancelled()
            r = c.request(method, f"{API_URL}{path}", json=body if method == "POST" else None, params=params,
                          headers=headers)
            data = _json(r)
            code = (data.get("error") or {}).get("code", "ok" if r.status_code == 200 else "")
            if code == "access_token_invalid" and attempt == 0:
                continue
            break
    if r.status_code != 200 or code != "ok":
        raise with_retry_after(api_error(code or ("rate_limit_exceeded" if r.status_code == 429 else ""),
                                         (data.get("error") or {}).get("message", "") or r.text[:200], r.status_code),
                               r, "TikTok")
    return data.get("data") or {}


@network_errors("TikTok")
def user_info(access_token: str) -> dict:
    with client(30) as c:
        r = c.get(f"{API_URL}/user/info/", params={"fields": "open_id,avatar_url,display_name"},
                  headers={"Authorization": f"Bearer {access_token}"})
    data = _json(r)
    if r.status_code != 200 or (data.get("error") or {}).get("code", "ok") != "ok":
        err = data.get("error") or {}
        raise with_retry_after(api_error(err.get("code", ""), err.get("message", ""), r.status_code), r, "TikTok")
    return (data.get("data") or {}).get("user") or {}


def creator_info(token: Token) -> dict:
    """Current posting options for the connected creator (TikTok asks apps to fetch these before every post)."""
    d = _call(token, "/post/publish/creator_info/query/", {})
    return {"nickname": d.get("creator_nickname", ""), "username": d.get("creator_username", ""),
            "avatar": d.get("creator_avatar_url", ""), "privacy_options": d.get("privacy_level_options") or [],
            "comment_disabled": bool(d.get("comment_disabled")), "duet_disabled": bool(d.get("duet_disabled")),
            "stitch_disabled": bool(d.get("stitch_disabled")),
            "max_duration": int(d.get("max_video_post_duration_sec") or 0)}


# ------------------------------------------------------------------ posting
def caption_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def chunking(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) following TikTok's media transfer rules."""
    if size < MIN_CHUNK:
        return size, 1
    chunk = min(CHUNK, size)
    return chunk, max(1, size // chunk)  # the last chunk carries the remainder


def post_info(caption: str, privacy: str, opts: dict) -> dict:
    return {"title": caption, "privacy_level": privacy,
            "disable_comment": not opts.get("allow_comment", False),
            "disable_duet": not opts.get("allow_duet", False),
            "disable_stitch": not opts.get("allow_stitch", False),
            "brand_content_toggle": bool(opts.get("brand_content", False)),
            "brand_organic_toggle": bool(opts.get("brand_organic", False))}


def validate(caption: str, privacy: str, opts: dict, mode: str, settings: dict, info: dict | None,
             duration: float) -> None:
    """Everything TikTok (and its sharing guidelines) would reject, checked before uploading."""
    if caption_length(caption) > CAPTION_MAX:
        raise PublishError(f"TikTok captions can have at most {CAPTION_MAX} characters.", "Shorten the caption.")
    if mode != "direct":
        return
    if not privacy:
        raise PublishError("Choose who can see the video on TikTok.", "Pick a privacy option; there is no default.")
    if info is not None and privacy not in info["privacy_options"]:
        raise api_error("privacy_level_option_mismatch")
    if not settings.get("tiktok_app_audited") and privacy != "SELF_ONLY":
        raise PublishError("Your TikTok app is not marked as audited, so TikTok only allows 'Only me' for Direct Posts.",
                           "Choose 'Only me', use 'Send to TikTok inbox', or tick 'My app passed TikTok's audit' "
                           "in Settings once it did.", "unaudited")
    if opts.get("brand_content") and privacy == "SELF_ONLY":
        raise PublishError("Branded content cannot be posted as 'Only me'.",
                           "Choose another privacy option or turn off 'Branded content'.")
    if opts.get("disclose") and not (opts.get("brand_content") or opts.get("brand_organic")):
        raise PublishError("You turned on the commercial content disclosure but chose no option.",
                           "Select 'Your brand', 'Branded content' or both, or turn the disclosure off.")
    if info is not None and info["max_duration"] and duration > info["max_duration"]:
        raise PublishError(f"This account can post videos up to {info['max_duration']} seconds; the clip is "
                           f"{duration:.0f} seconds.", "Trim the clip.", "duration")
    for key, flag in (("allow_comment", "comment_disabled"), ("allow_duet", "duet_disabled"),
                      ("allow_stitch", "stitch_disabled")):
        if info is not None and opts.get(key) and info[flag]:
            raise PublishError(f"Your TikTok settings do not allow {key.split('_')[1]}s.",
                               "Change it in the TikTok app or leave it off.")


def init_upload(token: Token, mode: str, size: int, caption: str = "", privacy: str = "",
                opts: dict | None = None, *, cancelled: Callable[[], bool] = lambda: False) -> dict:
    chunk, total = chunking(size)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total}
    if mode == "direct":
        body = {"post_info": post_info(caption, privacy, opts or {}), "source_info": source}
        return _call(token, "/post/publish/video/init/", body, cancelled=cancelled)
    return _call(token, "/post/publish/inbox/video/init/", {"source_info": source}, cancelled=cancelled)


def _busy(r: httpx.Response) -> PublishError:
    """TikTok asked to wait (Retry-After) before the next chunk: a rate limit, or a busy server."""
    return with_retry_after(api_error("rate_limit_exceeded" if r.status_code == 429 else "internal"), r, "TikTok")


def upload_chunks(upload_url: str, path: str, progress: Callable[[float], None],
                  cancelled: Callable[[], bool], *, resume_offset: int = 0,
                  on_final_chunk: Callable[[], None] | None = None) -> None:
    """Upload or continue from a complete chunk confirmed by TikTok's status API. A short Retry-After is waited
    out exactly; a longer one ends the attempt so the durable job can continue this same upload later."""
    size = os.path.getsize(path)
    chunk, total = chunking(size)
    if isinstance(resume_offset, bool) or not isinstance(resume_offset, int) or resume_offset < 0 or \
            resume_offset >= size or resume_offset % chunk or resume_offset // chunk >= total:
        raise PublishError("TikTok reported an upload position that is not a complete chunk.",
                           "Check the post's status before uploading it again.", "outcome_unknown")
    with client(300) as c, open(path, "rb") as fh:
        for i in range(resume_offset // chunk, total):
            if cancelled():
                raise Cancelled()
            start = i * chunk
            end = size - 1 if i == total - 1 else start + chunk - 1
            fh.seek(start)
            data = fh.read(end - start + 1)
            if i == total - 1 and on_final_chunk:
                on_final_chunk()  # persist uncertainty before any final bytes can reach the platform
            for attempt in range(3):
                if cancelled():
                    raise Cancelled()
                try:
                    r = c.put(upload_url, content=data, headers={"Content-Type": "video/mp4",
                                                                  "Content-Range": f"bytes {start}-{end}/{size}"})
                except httpx.TransportError:
                    r = None
                if r is not None and r.status_code in (200, 201, 206):
                    break
                if r is not None and r.status_code < 500 and r.status_code != 429:
                    code = "upload_session_expired" if r.status_code in (403, 404, 410) else ""
                    raise PublishError(f"TikTok rejected the upload ({r.status_code}).", "Publish again.", code)
                asked = retry_after(r)
                if r is not None and ((asked is not None and asked > SHORT_WAIT) or attempt == 2 and
                                      (asked is not None or r.status_code == 429)):
                    raise _busy(r)  # a long wait (or the last try) goes back to the job queue with TikTok's time
                if attempt < 2:
                    sleep_exactly(asked if asked is not None else 2 ** attempt, cancelled)
            else:
                raise PublishError("The upload to TikTok kept failing.", "Check your connection and publish again.")
            progress((end + 1) / size)


def fetch_status(token: Token, publish_id: str) -> dict:
    return _call(token, "/post/publish/status/fetch/", {"publish_id": publish_id})


def post_url(username: str, post_id: str) -> str:
    return f"https://www.tiktok.com/@{username}/video/{post_id}" if username else ""


STATS_FIELDS = "id,view_count,like_count,comment_count,share_count"


def video_statistics(token: Token, video_ids: list[str]) -> dict[str, dict]:
    """video.query (scope video.list): statistics of your own public videos, by id."""
    data = _call(token, "/video/query/", {"filters": {"video_ids": [str(v) for v in video_ids][:20]}},
                 params={"fields": STATS_FIELDS})
    return {str(v.get("id")): v for v in data.get("videos") or []}

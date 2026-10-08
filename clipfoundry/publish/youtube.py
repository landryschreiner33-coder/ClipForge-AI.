"""YouTube Shorts through the official YouTube Data API v3.

Sign-in uses Google's OAuth 2.0 flow for desktop apps (loopback redirect to http://127.0.0.1 with PKCE), with your
own Google Cloud project's "Desktop app" client. ClipFoundry receives tokens, never your Google password.

Uploads use the resumable upload protocol (videos.insert, uploadType=resumable) in 8 MiB chunks, resuming after
network errors. YouTube classifies vertical videos of up to three minutes as Shorts automatically.

Google restricts API projects that have not passed YouTube's API compliance audit: every video they upload is locked
to private viewing, whatever privacy was requested. ClipFoundry says so before and after the upload, and private
uploads work for testing in the meantime.
"""
from __future__ import annotations

import os
import re
import time
from typing import Callable
from urllib.parse import urlencode

import httpx

from .. import db
from .common import (SHORT_WAIT, Cancelled, PublishError, client, network_errors, retry_after, save_tokens,
                     sleep_exactly, with_retry_after)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_URL = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",         # upload videos
    "https://www.googleapis.com/auth/youtube.readonly",       # channel name, your videos' status and statistics
    "https://www.googleapis.com/auth/yt-analytics.readonly",  # watch time / retention of your videos (optional)
]
CHUNK = 8 * 1024 * 1024  # must be a multiple of 256 KiB
PRIVACY = ("private", "public")
SHORTS_MAX_SECONDS = 180
AUDIT_URL = "https://support.google.com/youtube/contact/yt_api_form"

UNVERIFIED_NOTE = (
    "YouTube locks every video uploaded through an API project that has not passed its API compliance audit to "
    "Private, even when you choose Public or Unlisted. Private uploads work for testing. To publish publicly, get "
    f"your Google Cloud project audited ({AUDIT_URL}) and then tick 'My project passed the audit' in Settings, or "
    "upload the exported MP4 in YouTube Studio yourself."
)
SETUP_FIX = ("Settings → Publishing → YouTube: create a Google Cloud project, enable the YouTube Data API v3, set up "
             "the OAuth consent screen, create an OAuth client of type 'Desktop app' and paste its client ID and "
             "secret.")
RECONNECT_FIX = "Click Connect YouTube again (Settings → Publishing or the publish screen)."
TESTING_NOTE = ("If your OAuth consent screen is in 'Testing', Google ends the connection after 7 days; set it to "
                "'In production' to stay connected (for your own use you can continue past the 'unverified app' "
                "screen).")


def configured(settings: dict) -> bool:
    return bool(settings.get("youtube_client_id") and settings.get("youtube_client_secret"))


def auth_url(settings: dict, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": settings["youtube_client_id"], "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    })


@network_errors("YouTube")
def _token_request(data: dict) -> dict:
    with client(30) as c:
        r = c.post(TOKEN_URL, data=data)
    body = _json(r)
    if r.status_code != 200:
        err = body.get("error", "")
        if err == "invalid_grant":
            raise PublishError("Google no longer accepts ClipFoundry's access to your YouTube channel (it was revoked, "
                               "expired, or the password was changed).", f"{RECONNECT_FIX} {TESTING_NOTE}",
                               "reconnect")
        if err in ("invalid_client", "unauthorized_client"):
            raise PublishError("Google rejected the OAuth client ID or secret.", SETUP_FIX, "setup")
        raise PublishError(f"Google sign-in failed: {body.get('error_description') or err or r.status_code}.",
                           RECONNECT_FIX)
    return body


def exchange_code(settings: dict, code: str, verifier: str, redirect_uri: str) -> dict:
    """Finish the sign-in: store the tokens and the channel. Returns the account row."""
    tok = _token_request({"code": code, "client_id": settings["youtube_client_id"],
                          "client_secret": settings["youtube_client_secret"], "redirect_uri": redirect_uri,
                          "grant_type": "authorization_code", "code_verifier": verifier})
    granted = set((tok.get("scope") or "").split())
    if SCOPES[0] not in granted:
        raise PublishError("The permission to upload videos was not granted.",
                           "Connect again and tick 'Manage your YouTube videos' on Google's permission screen.")
    ch = channel(tok["access_token"])
    db.save_account("youtube", tokens=save_tokens("youtube", tok), account_id=ch["id"], display_name=ch["title"],
                    avatar_url=ch.get("thumbnail", ""), scopes=sorted(granted), info={"needs_reconnect": False})
    return db.get_account("youtube") or {}


class Token:
    """A valid access token for the connected channel, refreshed when it is about to expire."""

    def __init__(self, settings: dict):
        self.settings = settings

    def get(self, force: bool = False) -> str:
        tokens = db.account_tokens("youtube")
        if not tokens:
            raise PublishError("YouTube is not connected.", RECONNECT_FIX, "not_connected")
        if not force and tokens["expires_at"] - 90 > time.time():
            return tokens["access_token"]
        if not tokens.get("refresh_token"):
            raise PublishError("The YouTube connection has expired.", RECONNECT_FIX, "reconnect")
        try:
            tok = _token_request({"client_id": self.settings["youtube_client_id"],
                                  "client_secret": self.settings["youtube_client_secret"],
                                  "refresh_token": tokens["refresh_token"], "grant_type": "refresh_token"})
        except PublishError as exc:
            if exc.code == "reconnect":
                db.save_account("youtube", info={"needs_reconnect": True})
            raise
        db.save_account("youtube", tokens=save_tokens("youtube", tok))
        return tok["access_token"]


@network_errors("YouTube")
def disconnect(settings: dict) -> None:
    """Revoke ClipFoundry's access at Google (best effort) and forget the tokens."""
    tokens = db.account_tokens("youtube") or {}
    token = tokens.get("refresh_token") or tokens.get("access_token")
    if token:
        try:
            with client(15) as c:
                c.post(REVOKE_URL, data={"token": token})
        except httpx.HTTPError:
            pass  # the local tokens are deleted either way
    db.delete_account("youtube")


def _json(r: httpx.Response) -> dict:
    try:
        data = r.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _quota(method: str, purpose: str) -> None:
    """Count the call against the project's daily quota and refuse it when a budget would be exceeded."""
    from ..autopilot import quota

    try:
        quota.charge(method, purpose)
    except quota.QuotaDenied as exc:
        raise PublishError(str(exc), "The YouTube quota resets at midnight Pacific Time. The budgets are in Settings "
                                     "→ Autopilot → YouTube quota.", "quota_budget") from exc


def api_error(r: httpx.Response, method: str = "") -> PublishError:
    """Plain-language version of a YouTube API error response."""
    err = _json(r).get("error") or {}
    reason = ((err.get("errors") or [{}])[0] or {}).get("reason", "") if isinstance(err, dict) else ""
    message = err.get("message", "") if isinstance(err, dict) else str(err)
    if reason in ("quotaExceeded", "dailyLimitExceeded"):
        from ..autopilot import quota

        quota.mark_exhausted(method or "videos.list", message)
    known = {
        "quotaExceeded": ("Your Google Cloud project has used up today's YouTube API quota.",
                          "Try again after midnight Pacific Time, or request more quota in the Google Cloud console."),
        "uploadLimitExceeded": ("Your channel reached YouTube's upload limit for now.", "Try again in 24 hours."),
        "youtubeSignupRequired": ("This Google account has no YouTube channel yet.",
                                  "Create a channel on youtube.com, then connect again."),
        "insufficientPermissions": ("ClipFoundry is not allowed to do this on your channel.", RECONNECT_FIX),
        "forbidden": ("YouTube refused the request for this channel.", RECONNECT_FIX),
        "invalidTitle": ("YouTube rejected the title.", "Use 1-100 characters without < or >."),
        "invalidDescription": ("YouTube rejected the description.", "Use at most 5000 bytes without < or >."),
        "invalidTags": ("YouTube rejected the tags.", "Use fewer or shorter hashtags (500 characters in total)."),
        "accessNotConfigured": ("The YouTube Data API is not enabled in your Google Cloud project.",
                                "Google Cloud console → APIs & Services → Library → YouTube Data API v3 → Enable."),
        "rateLimitExceeded": ("YouTube is rate limiting requests right now.", "Wait a minute and try again."),
        "userRateLimitExceeded": ("YouTube is rate limiting requests right now.", "Wait a minute and try again."),
    }
    if reason in known:
        exc = PublishError(*known[reason], code=reason)
    elif r.status_code == 429:  # too many requests, whatever the body says
        exc = PublishError(*known["rateLimitExceeded"], code="rateLimitExceeded")
    elif r.status_code == 401:
        exc = PublishError("YouTube did not accept the access token.", RECONNECT_FIX, "reconnect")
    else:
        exc = PublishError(f"YouTube API error {r.status_code}: {message or r.text[:200]}", code=reason)
    return with_retry_after(exc, r, "YouTube")


@network_errors("YouTube")
def _get(token: Token, url: str, params: dict, method: str = "videos.list", purpose: str = "stats") -> dict:
    _quota(method, purpose)
    with client(30) as c:
        r = c.get(url, params=params, headers={"Authorization": f"Bearer {token.get()}"})
        if r.status_code == 401:
            r = c.get(url, params=params, headers={"Authorization": f"Bearer {token.get(force=True)}"})
    if r.status_code != 200:
        raise api_error(r, method)
    return _json(r)


@network_errors("YouTube")
def channel(access_token: str) -> dict:
    _quota("channels.list", "account")
    with client(30) as c:
        r = c.get(f"{API_URL}/channels", params={"part": "snippet", "mine": "true"},
                  headers={"Authorization": f"Bearer {access_token}"})
    if r.status_code != 200:
        raise api_error(r, "channels.list")
    items = _json(r).get("items") or []
    if not items:
        raise PublishError("This Google account has no YouTube channel yet.",
                           "Create a channel on youtube.com, then connect again.", "no_channel")
    sn = items[0].get("snippet") or {}
    return {"id": items[0]["id"], "title": sn.get("title", ""),
            "thumbnail": ((sn.get("thumbnails") or {}).get("default") or {}).get("url", "")}


# ------------------------------------------------------------------ metadata
def _clean(text: str) -> str:
    return re.sub(r"[<>]", "", text or "").strip()


def video_body(title: str, description: str, tags: list[str], privacy: str, made_for_kids: bool,
               category_id: str = "22", publish_at: float | None = None, *, audience_intent: str = "") -> dict:
    """snippet + status for videos.insert, validated against YouTube's limits.

    Public needs the explicit audience stamp validated by the caller; Private stays Private and unlisted is not
    supported. Scheduling is local: public uploads start at their planned time. `publish_at` from older callers is
    ignored, so an existing Private upload never becomes public later."""
    title = _clean(title)
    if not title:
        raise PublishError("A title is required for YouTube.", "Enter a title on the publish screen.")
    if len(title) > 100:
        raise PublishError("YouTube titles can have at most 100 characters.", "Shorten the title.")
    description = _clean(description)
    if len(description.encode("utf-8")) > 5000:
        raise PublishError("YouTube descriptions can have at most 5000 bytes.", "Shorten the description.")
    if privacy == "unlisted" or (privacy == "public" and audience_intent != "PUBLIC"):
        from .audience import PUBLIC_OFF_FIX, AudienceBlocked

        raise AudienceBlocked("Public and unlisted YouTube uploads are turned off unless a Public audience was "
                              "explicitly confirmed. Unlisted is not supported.", PUBLIC_OFF_FIX)
    if privacy not in PRIVACY:
        raise PublishError("Choose Private or Public after confirming who watches.")
    clean_tags, total = [], 0
    for t in tags:
        t = _clean(t).lstrip("#").replace(",", " ").strip()
        cost = len(t) + (2 if " " in t else 0) + (1 if clean_tags else 0)
        if t and t not in clean_tags and total + cost <= 480:
            clean_tags.append(t)
            total += cost
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids), "embeddable": True}
    return {"snippet": {"title": title, "description": description, "tags": clean_tags,
                        "categoryId": str(category_id or "22")}, "status": status}


# ------------------------------------------------------------------ upload
OUTCOME_UNKNOWN = "outcome_unknown"
OUTCOME_UNKNOWN_FIX = ("Open YouTube Studio → Content. If the video is there, mark the post as published (with its "
                       "link); if it is not, upload it again.")


def _outcome_unknown() -> PublishError:
    return PublishError("All of the video may already have reached YouTube, but YouTube no longer knows the upload "
                        "session, so ClipFoundry cannot tell whether the video was created. It is not uploaded again "
                        "automatically, to avoid a duplicate.", OUTCOME_UNKNOWN_FIX, OUTCOME_UNKNOWN)


def upload(path: str, body: dict, token: Token, progress: Callable[[float], None] | None = None,
           cancelled: Callable[[], bool] = lambda: False, sleep: Callable[[float], None] = time.sleep,
           on_session: Callable[[str], None] | None = None, resume_session: str = "",
           on_final_chunk: Callable[[], None] | None = None, may_be_complete: bool = False) -> dict:
    """Resumable upload. Returns the created video resource (id, snippet, status).

    `on_session` receives the upload session URL as soon as it exists (store it: an interrupted upload can then be
    resumed with `resume_session` instead of uploading the video a second time). `on_final_chunk` is called right
    before the last bytes are sent: from then on YouTube may create the video even if its answer is lost. When a
    session that may already be complete (`may_be_complete`, or the last bytes were sent in this call) has expired,
    the outcome cannot be known: PublishError with code OUTCOME_UNKNOWN, never a second upload."""
    size = os.path.getsize(path)
    report = progress or (lambda f: None)
    with client(120) as c:
        offset, failures = 0, 0
        session = ""
        final_sent = False
        if resume_session:
            offset, done = _resume_offset(c, resume_session, size, token, sleep, cancelled)
            if done is not None:
                report(1.0)
                return done
            if offset < 0 and may_be_complete:
                raise _outcome_unknown()
            session = resume_session if offset >= 0 else ""
            offset = max(0, offset)
        if not session:
            session = _start_session(c, body, size, token)
            if on_session:
                on_session(session)
        with open(path, "rb") as fh:
            while True:
                if cancelled():
                    raise Cancelled()
                fh.seek(offset)
                chunk = fh.read(CHUNK)
                if offset + len(chunk) >= size and not final_sent:
                    final_sent = True
                    if on_final_chunk:
                        on_final_chunk()
                headers = {"Authorization": f"Bearer {token.get()}", "Content-Type": "video/mp4",
                           "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{size}"}
                try:
                    r = c.put(session, content=chunk, headers=headers)
                except httpx.TransportError:
                    r = None
                if r is not None and r.status_code in (200, 201):
                    report(1.0)
                    return _json(r)
                if r is not None and r.status_code == 308:
                    offset, failures = _next_offset(r), 0
                    report(offset / size)
                    continue
                if r is not None and r.status_code == 401:
                    token.get(force=True)
                elif r is not None and r.status_code not in (408, 429, 500, 502, 503, 504):
                    raise api_error(r, "videos.insert")
                failures += 1
                asked = retry_after(r)
                if asked is not None and asked > SHORT_WAIT:
                    raise _wait_error(r)  # the attempt ends; the stored session continues after the wait
                if failures > 6:
                    raise PublishError("The upload to YouTube kept getting interrupted.",
                                       "Check your internet connection and publish again.")
                _pause(asked, min(60.0, 2.0 ** failures), sleep, cancelled)
                offset, done = _resume_offset(c, session, size, token, sleep, cancelled)
                if done is not None:
                    report(1.0)
                    return done
                if offset < 0:  # the upload session expired: start over, unless the video may already exist
                    if final_sent:
                        raise _outcome_unknown()
                    session, offset = _start_session(c, body, size, token), 0
                    if on_session:
                        on_session(session)


def _pause(asked: float | None, backoff: float, sleep: Callable[[float], None], cancelled: Callable[[], bool]) -> None:
    """Wait before the next try: exactly as long as YouTube's Retry-After asked (a short wait; a longer one ends the
    attempt, see _wait_error), else the backoff. Waits in short steps, so stopping the upload is not held up."""
    sleep_exactly(asked if asked is not None else backoff, cancelled, sleep)


def _wait_error(r: httpx.Response) -> PublishError:
    """YouTube asked for a longer wait than is worth sitting out mid-upload: the job runs again at that time and
    continues the same upload session (it stays valid for about a week)."""
    if r.status_code == 429:
        return api_error(r, "videos.insert")
    return with_retry_after(PublishError(f"YouTube is busy ({r.status_code}) and asked to wait.", code="busy"), r,
                            "YouTube")


@network_errors("YouTube")
def _start_session(c: httpx.Client, body: dict, size: int, token: Token) -> str:
    params = {"uploadType": "resumable", "part": "snippet,status"}
    _quota("videos.insert", "publish")
    for attempt in range(2):
        r = c.post(UPLOAD_URL, params=params, json=body,
                   headers={"Authorization": f"Bearer {token.get(force=attempt > 0)}",
                            "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
        if r.status_code == 200 and r.headers.get("Location"):
            return r.headers["Location"]
        if r.status_code != 401:
            break
    raise api_error(r, "videos.insert")


def _next_offset(r: httpx.Response) -> int:
    rng = r.headers.get("Range", "")
    m = re.search(r"(\d+)-(\d+)", rng)
    return int(m.group(2)) + 1 if m else 0


def _resume_offset(c: httpx.Client, session: str, size: int, token: Token, sleep: Callable[[float], None] = time.sleep,
                   cancelled: Callable[[], bool] = lambda: False) -> tuple[int, dict | None]:
    """Ask YouTube how much of the file it already has (offset, or the finished video, or -1 if expired). When it
    asks to wait before answering, a short wait is sat out and a longer one ends the attempt (_wait_error)."""
    for _ in range(3):
        try:
            r = c.put(session, headers={"Authorization": f"Bearer {token.get()}", "Content-Range": f"bytes */{size}",
                                        "Content-Length": "0"})
        except httpx.TransportError:
            return 0, None
        if r.status_code in (200, 201):
            return size, _json(r)
        if r.status_code == 308:
            return _next_offset(r), None
        if r.status_code in (404, 410):
            return -1, None
        asked = retry_after(r) if r.status_code == 429 or r.status_code >= 500 else None
        if asked is None:
            return 0, None
        if asked > SHORT_WAIT:
            raise _wait_error(r)
        _pause(asked, 0.0, sleep, cancelled)
    return 0, None


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/shorts/{video_id}"


def studio_url(video_id: str) -> str:
    return f"https://studio.youtube.com/video/{video_id}/edit"


def video_status(token: Token, video_id: str) -> dict:
    """Current privacy / processing status of an uploaded video (None fields if it was deleted)."""
    items = _get(token, f"{API_URL}/videos", {"part": "status,processingDetails", "id": video_id}).get("items") or []
    if not items:
        return {"exists": False}
    st = items[0].get("status") or {}
    return {"exists": True, "privacy": st.get("privacyStatus", ""), "upload_status": st.get("uploadStatus", ""),
            "rejection_reason": st.get("rejectionReason", ""), "failure_reason": st.get("failureReason", ""),
            "processing": ((items[0].get("processingDetails") or {}).get("processingStatus", ""))}


def video_statistics(token: Token, video_id: str) -> dict | None:
    """videos.list statistics (views, likes, comments) of your own video; None if it no longer exists."""
    items = _get(token, f"{API_URL}/videos", {"part": "statistics", "id": video_id}).get("items") or []
    return (items[0].get("statistics") or {}) if items else None


ANALYTICS_METRICS = "views,likes,comments,shares,estimatedMinutesWatched,averageViewDuration,averageViewPercentage"


def video_analytics(token: Token, video_id: str, start_date: str, end_date: str) -> dict | None:
    """YouTube Analytics totals for one video between two dates (YYYY-MM-DD); None when there is no data yet."""
    data = _get(token, ANALYTICS_URL, {"ids": "channel==MINE", "startDate": start_date, "endDate": end_date,
                                       "metrics": ANALYTICS_METRICS, "filters": f"video=={video_id}"},
                method="analytics.reports")
    rows = data.get("rows") or []
    if not rows:
        return None
    names = [h.get("name") for h in data.get("columnHeaders") or []]
    return dict(zip(names, rows[0]))

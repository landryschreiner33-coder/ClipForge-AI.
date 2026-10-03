"""Which channel a video belongs to, as the platform itself reports it.

A feed or list can name any channel for any video, so a channel named there is only a claim. Before a channel rule
(an agreement, an allowlisted creator) or ownership (your connected YouTube channel) is applied to a video, the
platform's own data has to confirm that this exact video belongs to that channel:

* YouTube   the YouTube Data API (videos.list) reports the video's channel. A video Autopilot found through the Data
            API already carries that answer; any other one is looked up (50 videos per call, 1 quota unit).
* TikTok    TikTok's oEmbed endpoint (its embed API) reports the video's author. The name inside a TikTok link is not
            trusted: TikTok finds a video by its number, whatever name the link shows.

The link ClipFoundry would get the file from must lead to that same video, so a list cannot pair a real video with
someone else's file. A confirmation only says who posted the video: the channel still has to match one of your
rules or agreements, or be your connected channel, before Autopilot uses it (rights.py). A video that cannot be
confirmed is skipped with the reason in the activity log and looked at again later; nobody is asked about it.

The outcome is stored on the source (`channel_check`) together with the exact claim it answers (platform, video,
channel and link), so it never carries over to a different claim.
"""
from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, urlparse

import httpx

from .. import db

VERIFIED, MISMATCH, NOT_FOUND, BAD_LINK, INVALID, UNAVAILABLE = (
    "verified", "mismatch", "not_found", "bad_link", "invalid", "unavailable")
FINAL = (VERIFIED, MISMATCH, BAD_LINK, INVALID)  # these answers do not change for the same claim
RECHECK = {UNAVAILABLE: 3600.0, NOT_FOUND: 86400.0}  # a video that may become visible, or a platform that was busy
PLATFORMS = {"youtube": "YouTube", "tiktok": "TikTok"}
YOUTUBE_ID = re.compile(r"[\w-]{2,64}")  # YouTube's IDs are 11 characters; never a comma or anything else
TIKTOK_ID = re.compile(r"\d{6,25}")
TIKTOK_HANDLE = re.compile(r"@?([\w.\-]{2,40})")
YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com")
TIKTOK_HOSTS = ("tiktok.com", "www.tiktok.com", "m.tiktok.com")
TIKTOK_PER_RUN = 20  # oEmbed lookups per run; the rest wait for the next one
YOUTUBE_DATA = "YouTube Data API"
TIKTOK_EMBED = "TikTok"


# ------------------------------------------------------------------ reading a stored answer
def _check(source: dict) -> dict:
    c = source.get("channel_check") or {}
    return c if isinstance(c, dict) else {}


def _same_channel(platform: str, a: str, b: str) -> bool:
    if not a or not b:
        return False
    if platform == "tiktok":  # TikTok user names are not case sensitive; "@" is only how they are written
        return a.lstrip("@").lower() == b.lstrip("@").lower()
    return a == b


def _answers(check: dict, source: dict) -> bool:
    """Does this stored answer belong to the source's current claim?"""
    return bool(check) and check.get("platform") == source.get("platform") and \
        check.get("video_id") == source.get("external_id") and check.get("claimed") == source.get("channel_id") and \
        check.get("url", "") == (source.get("url") or "")


def confirmed(source: dict) -> bool:
    """Has the platform confirmed that this exact video (and the link to it) belongs to the channel it names?"""
    c = _check(source)
    return c.get("state") == VERIFIED and _answers(c, source)


def unconfirmed_claim(source: dict) -> bool:
    """The source names a channel the platform has not confirmed."""
    return bool(source.get("channel_id")) and not confirmed(source)


def why_not(source: dict) -> str:
    """Why the channel of this video is not confirmed, in plain words (no final period)."""
    platform = source.get("platform") or ""
    name = PLATFORMS.get(platform)
    if not name:
        return "ClipFoundry can only confirm YouTube and TikTok channels"
    c = _check(source)
    if not _answers(c, source) or not c.get("state"):
        return f"{name} has not confirmed it yet"
    return c.get("detail") or f"{name} did not confirm it"


def due(source: dict, now: float | None = None) -> bool:
    """Is it worth asking the platform about this source now?"""
    if not source.get("channel_id") or source.get("platform") not in PLATFORMS:
        return False
    c = _check(source)
    if not _answers(c, source):
        return True
    state = c.get("state")
    if state in FINAL:
        return False
    now = time.time() if now is None else now
    return now >= max(float(c.get("at") or 0) + RECHECK.get(state, 3600.0), float(c.get("retry_at") or 0))


# ------------------------------------------------------------------ judging an answer
def link_video(platform: str, url: str) -> tuple[str, str] | None:
    """The video (and, for TikTok, the user name) a platform link points at; ("", "") for no link, None for a link
    that is not a plain link to one video on that platform."""
    if not url:
        return "", ""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme not in ("https", "http"):
        return None
    if platform == "youtube":
        if host == "youtu.be":
            vid = u.path.strip("/")
        elif host in YOUTUBE_HOSTS and u.path.rstrip("/") == "/watch":
            vid = (parse_qs(u.query).get("v") or [""])[0]
        elif host in YOUTUBE_HOSTS:
            m = re.fullmatch(r"/(?:shorts|live|embed)/([\w-]+)/?", u.path)
            vid = m.group(1) if m else ""
        else:
            return None
        return (vid, "") if YOUTUBE_ID.fullmatch(vid) else None
    if platform == "tiktok":
        m = re.fullmatch(r"/@([\w.\-]+)/video/(\d+)/?", u.path) if host in TIKTOK_HOSTS else None
        return (m.group(2), m.group(1)) if m else None
    return None


def _record(source: dict, state: str, detail: str = "", official: str = "", official_title: str = "",
            by: str = "", retry_at: float = 0.0, at: float | None = None) -> dict:
    return {"state": state, "platform": source.get("platform"), "video_id": source.get("external_id"),
            "claimed": source.get("channel_id"), "url": source.get("url") or "", "official": official,
            "official_title": official_title[:120], "by": by, "detail": detail[:300],
            "at": time.time() if at is None else at, "retry_at": retry_at}


def judge(source: dict, official: str, official_title: str, by: str, at: float | None = None) -> dict:
    """Compare what the platform reported about the video with what the source claims."""
    platform = source["platform"]
    name = PLATFORMS[platform]
    link = link_video(platform, source.get("url") or "")
    if link is None or (link[0] and link[0] != source.get("external_id")):
        return _record(source, BAD_LINK, "the link does not lead to this exact video", official, official_title, by,
                       at=at)
    if not official:
        return _record(source, NOT_FOUND, f"{name} has no public video with this ID", by=by, at=at)
    if not _same_channel(platform, source.get("channel_id") or "", official):
        shown = official_title or official
        return _record(source, MISMATCH, f"{name} says this video belongs to another channel ({shown}), not the "
                                         "one the list named", official, official_title, by, at=at)
    if link[1] and not _same_channel(platform, link[1], official):
        return _record(source, BAD_LINK, "the link names another TikTok account than the video's author", official,
                       official_title, by, at=at)
    return _record(source, VERIFIED, f"confirmed by {by}", official, official_title, by, at=at)


def _store(source: dict, record: dict) -> dict:
    db.update("sources", source["id"], channel_check=record)
    source["channel_check"] = record
    return record


# ------------------------------------------------------------------ asking the platform
def from_signal(source: dict, sig: dict | None) -> dict | None:
    """A video found through the YouTube Data API: its signal is YouTube's own answer about the video, so the channel
    is judged without another call."""
    raw = (sig or {}).get("raw") or {}
    if source.get("platform") != "youtube" or not source.get("channel_id") or confirmed(source) or not sig:
        return None
    if not str(sig.get("provider") or "").startswith("youtube_") or raw.get("reported_by") != YOUTUBE_DATA or \
            sig.get("external_id") != source.get("external_id") or not sig.get("channel_id"):
        return None
    return _store(source, judge(source, sig["channel_id"], sig.get("channel_title") or "", YOUTUBE_DATA,
                                at=raw.get("observed_at")))


def ensure(sources: list[dict], settings: dict | None = None, now: float | None = None) -> int:
    """Ask the platform about every source whose channel claim is not answered yet (or is due for another look).
    Each outcome is stored on its source. A platform problem never raises: the video stays unconfirmed (skipped)
    and is asked about again later. Returns how many sources were looked up."""
    now = time.time() if now is None else now
    todo = [s for s in sources if due(s, now)]
    if not todo:
        return 0
    settings = settings if settings is not None else db.get_settings()
    youtube = [s for s in todo if s["platform"] == "youtube"]
    tiktok = [s for s in todo if s["platform"] == "tiktok"][:TIKTOK_PER_RUN]
    if youtube:
        _youtube(youtube, settings)
    for s in tiktok:
        _tiktok(s)
    return len(youtube) + len(tiktok)


def _youtube(sources: list[dict], settings: dict) -> None:
    from ..publish.common import PublishError
    from . import providers, quota

    good = []
    for s in sources:
        if YOUTUBE_ID.fullmatch(s.get("external_id") or ""):
            good.append(s)
        else:
            _store(s, _record(s, INVALID, "the list does not give a YouTube video ID"))
    if not good:
        return
    retry_at = 0.0
    try:
        found = providers.YouTubeDiscovery(settings).videos([s["external_id"] for s in good])
    except providers.Unavailable:
        found, detail = None, "YouTube is not connected, so the channel could not be checked"
    except quota.QuotaDenied as exc:
        found, detail, retry_at = None, "today's YouTube quota for finding videos is used up", exc.retry_at
    except PublishError as exc:
        found, detail = None, f"YouTube could not be asked ({exc})"
        retry_at = time.time() + exc.retry_after if exc.retry_after is not None else 0.0
    for s in good:
        if found is None:
            _store(s, _record(s, UNAVAILABLE, f"{detail}; it is checked again later", retry_at=retry_at))
            continue
        sn = (found.get(s["external_id"]) or {}).get("snippet") or {}
        _store(s, judge(s, sn.get("channelId") or "", sn.get("channelTitle") or "", YOUTUBE_DATA))


def _tiktok(source: dict) -> None:
    from ..publish import tiktok
    from ..publish.common import client, retry_after

    vid = source.get("external_id") or ""
    handle = TIKTOK_HANDLE.fullmatch(source.get("channel_id") or "")
    if not TIKTOK_ID.fullmatch(vid) or not handle:
        _store(source, _record(source, INVALID, "the list does not give a TikTok video number and account"))
        return
    # the link is rebuilt from checked parts; TikTok answers with the video's real author, whatever name it shows
    url = f"https://www.tiktok.com/@{handle.group(1)}/video/{vid}"
    try:
        with client(20) as c:
            r = c.get(tiktok.OEMBED_URL, params={"url": url})
    except httpx.HTTPError as exc:
        _store(source, _record(source, UNAVAILABLE, f"TikTok could not be reached ({type(exc).__name__}); it is "
                                                    "checked again later"))
        return
    if r.status_code == 429 or r.status_code >= 500:
        asked = retry_after(r)
        _store(source, _record(source, UNAVAILABLE, f"TikTok was busy ({r.status_code}); it is checked again later",
                               retry_at=time.time() + asked if asked is not None else 0.0))
        return
    try:
        data = r.json() if r.status_code == 200 else {}
    except ValueError:
        data = {}
    author = str(data.get("author_unique_id") or "") if isinstance(data, dict) else ""
    if str((data or {}).get("embed_product_id") or "") != vid:
        author = ""  # the answer is not about this video
    _store(source, judge(source, f"@{author}" if author else "", str((data or {}).get("author_name") or ""),
                         TIKTOK_EMBED))

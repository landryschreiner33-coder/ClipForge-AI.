"""Where trend signals come from. Only legitimate, authorized sources; nothing is scraped.

* YouTube Data API v3 (official): the mostPopular chart for your region (since July 2025 it covers the Trending
  Music, Movies and Gaming charts), recent top videos for your topics (search.list, its own daily quota bucket),
  live streams with their concurrent viewers, and new uploads of channels you follow. Every call is counted by the
  quota manager, answers are cached, and repeated requests are served from the cache.
* Watch folders: new recordings you put in a folder (your own content, with the rights status you give the folder).
  A file that is still growing is treated as a live recording.
* Stream URLs you are allowed to use (your own HLS/RTMP/SRT stream, a licensed feed).
* Signal feeds: a JSON or CSV file (or URL) of signals from a provider you are authorized to use.

Not available, and shown as such: Google Trends (the official API is an application-gated alpha) and TikTok trends
(TikTok has no trend API for general developers; its Research API is for approved academic research).
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
import time
from pathlib import Path
from typing import Iterable

import httpx

from .. import config, db, netguard
from ..publish import youtube
from ..publish.common import PublishError, client
from . import quota, state, trends

UNAVAILABLE = {
    "google_trends": ("Google Trends", "The official Google Trends API is an application-gated alpha; ClipFoundry "
                                       "does not scrape Google Trends."),
    "tiktok_trends": ("TikTok trends", "TikTok offers no trend or discovery API to general developers (its Research "
                                       "API is limited to approved academic research); ClipFoundry does not scrape "
                                       "TikTok."),
}
VIDEO_PARTS = "snippet,statistics,contentDetails,liveStreamingDetails,status"
MIN_STABLE_SECONDS = 60


class Unavailable(Exception):
    def __init__(self, status: str, detail: str, fix: str = ""):
        super().__init__(detail)
        self.status = status
        self.fix = fix


def iso_duration(text: str | None) -> float | None:
    """ISO 8601 duration (PT1H2M3S, P1DT2H) to seconds."""
    if not text:
        return None
    mt = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?", text)
    if not mt:
        return None
    d, h, mi, s = (float(x) if x else 0.0 for x in mt.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def iso_time(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _int(v: object) -> int | None:
    try:
        return int(str(v)) if v is not None and str(v) != "" else None
    except ValueError:
        return None


# ------------------------------------------------------------------ YouTube (official Data API)
class YouTubeDiscovery:
    def __init__(self, settings: dict):
        self.settings = settings
        self.key = settings.get("youtube_api_key") or ""
        self.token: youtube.Token | None = None
        if not self.key:
            if not (db.get_account("youtube") or {}).get("has_tokens") or not youtube.configured(settings):
                raise Unavailable("not_configured", "YouTube discovery needs a YouTube Data API key or a connected "
                                                    "YouTube account.",
                                  "Settings → Autopilot → Discovery: paste an API key from your Google Cloud project, "
                                  "or connect YouTube in Settings → Publishing.")
            self.token = youtube.Token(settings)
        self.calls = 0
        self.cache_hits = 0
        self.denied: list[str] = []

    def _get(self, method: str, path: str, params: dict, ttl: float) -> dict:
        def fetch() -> dict:
            quota.check(method, "discovery", self.settings)
            query, headers = dict(params), {}
            if self.key:
                query["key"] = self.key
            else:
                headers["Authorization"] = f"Bearer {self.token.get()}"  # type: ignore[union-attr]
            try:
                with client(30) as c:
                    r = c.get(f"{youtube.API_URL}/{path}", params=query, headers=headers)
            except httpx.HTTPError as exc:
                raise PublishError(f"Could not reach YouTube ({type(exc).__name__}).",
                                   "Check the internet connection.", "network") from exc
            quota.record(method, "discovery")
            self.calls += 1
            if r.status_code != 200:
                raise youtube.api_error(r, method)
            return r.json()

        data, hit = quota.cached(["youtube", path, params], ttl, fetch, method)
        self.cache_hits += int(hit)
        return data

    def most_popular(self, region: str, max_results: int = 50) -> list[dict]:
        data = self._get("videos.list", "videos", {"part": VIDEO_PARTS, "chart": "mostPopular", "regionCode": region,
                                                   "maxResults": max_results}, ttl=1800)
        return data.get("items") or []

    def search(self, q: str, region: str, language: str, published_after: float | None, event_type: str = "",
               max_results: int = 25) -> list[str]:
        params = {"part": "snippet", "type": "video", "q": q, "regionCode": region, "relevanceLanguage": language,
                  "order": "viewCount", "maxResults": max_results}
        if event_type:
            params["eventType"] = event_type
        elif published_after:
            params["publishedAfter"] = dt.datetime.fromtimestamp(published_after, dt.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
        data = self._get("search.list", "search", params, ttl=1800)
        return [((i.get("id") or {}).get("videoId")) for i in data.get("items") or [] if (i.get("id") or {}).get("videoId")]

    def videos(self, ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for k in range(0, len(ids), 50):
            batch = ids[k:k + 50]
            data = self._get("videos.list", "videos", {"part": VIDEO_PARTS, "id": ",".join(batch)}, ttl=600)
            out.update({i["id"]: i for i in data.get("items") or []})
        return out

    def channel_uploads(self, channel_id: str, max_results: int = 10) -> list[str]:
        data = self._get("channels.list", "channels", {"part": "contentDetails", "id": channel_id}, ttl=7 * 86400)
        items = data.get("items") or []
        if not items:
            return []
        playlist = ((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
        if not playlist:
            return []
        data = self._get("playlistItems.list", "playlistItems", {"part": "contentDetails", "playlistId": playlist,
                                                                 "maxResults": max_results}, ttl=1800)
        return [(i.get("contentDetails") or {}).get("videoId") for i in data.get("items") or []
                if (i.get("contentDetails") or {}).get("videoId")]

    def discover(self, topics: list[str], channels: list[dict], include_live: bool, job=None) -> list[dict]:
        """One discovery pass. Stops using a bucket as soon as the quota manager refuses it."""
        region = self.settings.get("trend_region") or "US"
        lang = self.settings.get("trend_language") or "en"
        since = time.time() - 3600 * float(self.settings.get("trend_max_age_hours") or 72)
        ranked: dict[str, tuple[str, int, int, str]] = {}  # id -> (provider, rank, list size, query)

        def attempt(fn, *args, **kw):
            try:
                return fn(*args, **kw)
            except quota.QuotaDenied as exc:
                self.denied.append(str(exc))
                return None

        popular = attempt(self.most_popular, region)
        items: dict[str, dict] = {}
        for rank, item in enumerate(popular or [], 1):
            items[item["id"]] = item
            ranked[item["id"]] = ("youtube_popular", rank, len(popular or []), "mostPopular")
        for topic in topics:
            if job:
                job.check()
            ids = attempt(self.search, topic, region, lang, since)
            if ids is None:
                break  # the search bucket said no: no point trying the next topic
            for rank, vid in enumerate(ids, 1):
                ranked.setdefault(vid, ("youtube_search", rank, len(ids), topic))
        if include_live:
            ids = attempt(self.search, "live", region, lang, None, event_type="live")
            for rank, vid in enumerate(ids or [], 1):
                ranked[vid] = ("youtube_live", rank, len(ids or []), "live now")
        for ch in channels:
            ids = attempt(self.channel_uploads, ch["channel_id"])
            for rank, vid in enumerate(ids or [], 1):
                ranked.setdefault(vid, ("youtube_channel", rank, len(ids or []), ch.get("name") or ch["channel_id"]))
        missing = [v for v in ranked if v not in items]
        details = attempt(self.videos, missing) if missing else {}
        items.update(details or {})
        return [signal_from_video(items[v], *ranked[v], region=region, language=lang) for v in ranked if v in items]


def signal_from_video(item: dict, provider: str, rank: int, size: int, query: str, region: str = "",
                      language: str = "") -> dict:
    """A videos.list item as a trend signal, with each metric's provenance."""
    sn = item.get("snippet") or {}
    st = item.get("statistics") or {}
    cd = item.get("contentDetails") or {}
    live = item.get("liveStreamingDetails") or {}
    status = item.get("status") or {}
    now = time.time()
    is_live = sn.get("liveBroadcastContent") == "live"
    duration = iso_duration(cd.get("duration"))
    hidden = "hidden by the channel"
    metrics = {
        "views": trends.m(_int(st.get("viewCount")), note="" if "viewCount" in st else "not reported", at=now),
        "likes": trends.m(_int(st.get("likeCount")), note="" if "likeCount" in st else hidden, at=now),
        "comments": trends.m(_int(st.get("commentCount")), note="" if "commentCount" in st else "comments are off",
                             at=now),
        "live_viewers": trends.m(_int(live.get("concurrentViewers")) if is_live else None,
                                 note="" if is_live else "not live", at=now),
        "duration_s": trends.m(duration, note="" if duration else "live or unknown", at=now),
    }
    title = sn.get("title") or ""
    return {"provider": provider, "platform": "youtube", "external_id": item["id"], "kind": "live" if is_live else
            "video", "title": title, "url": f"https://www.youtube.com/watch?v={item['id']}",
            "channel_id": sn.get("channelId") or "", "channel_title": sn.get("channelTitle") or "",
            "category": trends.YOUTUBE_CATEGORIES.get(str(sn.get("categoryId") or ""), ""),
            "keywords": trends.keywords(title, sn.get("tags")), "query": query, "region": region,
            "language": language, "published_at": iso_time(sn.get("publishedAt")), "platform_rank": rank,
            "metrics": metrics,
            "raw": {"list_size": size, "license": status.get("license", ""), "made_for_kids":
                    bool(status.get("madeForKids")), "live_status": sn.get("liveBroadcastContent", ""),
                    "duration_s": duration, "privacy": status.get("privacyStatus", "")}}


# ------------------------------------------------------------------ local and user-provided feeds
def feeds(kind: str | None = None, enabled_only: bool = True) -> list[dict]:
    where, args = [], []
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if enabled_only:
        where.append("enabled = 1")
    return db.select("source_feeds", " AND ".join(where), args, "created_at")


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def scan_watch_folder(feed: dict, now: float | None = None) -> list[dict]:
    """Video files in the folder. A file must stop changing for a minute before it is used; a file that keeps
    growing is a recording in progress (a live source)."""
    now = now or time.time()
    cfg = feed.get("config") or {}
    folder = Path(cfg.get("path") or "")
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    seen = state.get(f"feed:{feed['id']}:sizes", {}) or {}
    sizes: dict[str, int] = {}
    out = []
    pattern = "**/*" if cfg.get("recursive", True) else "*"
    for f in sorted(folder.glob(pattern)):
        if not f.is_file() or f.suffix.lower() not in config.VIDEO_EXTENSIONS or f.name.startswith("."):
            continue
        st = f.stat()
        key = _key(str(f.resolve()).lower())
        sizes[key] = st.st_size
        growing = key in seen and seen[key] != st.st_size
        if not growing and now - st.st_mtime < MIN_STABLE_SECONDS:
            continue  # just appeared or still being written: look again next scan
        out.append({"provider": "watch_folder", "platform": "local", "external_id": key,
                    "kind": "live" if growing else "video", "title": f.stem.replace("_", " ")[:200],
                    "url": f.resolve().as_uri(), "channel_id": "", "channel_title": feed.get("name") or "Watch folder",
                    "category": cfg.get("category", ""), "keywords": trends.keywords(f.stem.replace("_", " ")),
                    "published_at": st.st_mtime, "platform_rank": None,
                    "metrics": {"file_size_mb": trends.m(round(st.st_size / 1e6, 1), at=now)},
                    "raw": {"path": str(f.resolve()), "feed_id": feed["id"], "growing": growing}})
    state.put(f"feed:{feed['id']}:sizes", sizes)
    return out


def stream_signal(feed: dict) -> list[dict]:
    cfg = feed.get("config") or {}
    url = (cfg.get("url") or "").strip()
    if not url:
        return []
    return [{"provider": "stream_url", "platform": "stream", "external_id": _key(url), "kind": "live",
             "title": feed.get("name") or url[:120], "url": url, "channel_id": "", "channel_title": feed.get("name", ""),
             "category": cfg.get("category", ""), "keywords": trends.keywords(feed.get("name") or ""),
             "published_at": None, "platform_rank": None, "metrics": {}, "raw": {"feed_id": feed["id"]}}]


def _rows(text: str) -> Iterable[dict]:
    text = text.strip()
    if text.startswith("[") or text.startswith("{"):
        data = json.loads(text)
        return data.get("signals", []) if isinstance(data, dict) else data
    return list(csv.DictReader(io.StringIO(text)))


def signal_feed(feed: dict) -> list[dict]:
    """Signals from a provider you are authorized to use, as JSON ([{...}] or {"signals": [...]}) or CSV with
    id, title, url, views, likes, comments, live_viewers, published_at, topic, platform."""
    cfg = feed.get("config") or {}
    where = (cfg.get("url") or cfg.get("path") or "").strip()
    if where.startswith(("http://", "https://")):
        with client(30) as c:  # you typed this address: it may be on your own network; redirects are checked
            text = netguard.get_text(c, where, allow_private=True)
    else:
        text = Path(where).read_text(encoding="utf-8-sig")
    now = time.time()
    out = []
    for rank, row in enumerate(_rows(text), 1):
        ext = str(row.get("id") or row.get("url") or "").strip()
        if not ext:
            continue
        published = row.get("published_at")
        published_at = float(published) if str(published or "").replace(".", "", 1).isdigit() else iso_time(
            str(published or "") or None)
        title = str(row.get("title") or ext)[:200]
        metrics = {k: trends.m(_int(row.get(k)), note=f"from {feed.get('name') or 'feed'}", at=now)
                   for k in ("views", "likes", "comments", "live_viewers")}
        out.append({"provider": "signal_feed", "platform": str(row.get("platform") or "feed"), "external_id": ext,
                    "kind": "live" if str(row.get("live") or "").lower() in ("1", "true", "yes") else "video",
                    "title": title, "url": str(row.get("url") or ""), "channel_id": str(row.get("channel_id") or ""),
                    "channel_title": str(row.get("channel") or ""), "category": str(row.get("category") or ""),
                    "keywords": trends.keywords(f"{title} {row.get('topic') or ''}"), "published_at": published_at,
                    "platform_rank": rank, "metrics": metrics, "raw": {"feed_id": feed["id"], "list_size": 0}})
    return out


FEED_SCANNERS = {"watch_folder": scan_watch_folder, "stream_url": stream_signal, "signal_feed": signal_feed}


def add_feed(kind: str, name: str, config_: dict, rights_status: str = "", rights_basis: str = "") -> dict:
    if kind not in (*FEED_SCANNERS, "youtube_channel"):
        raise ValueError(f"unknown feed kind {kind}")
    if kind == "watch_folder" and not Path(config_.get("path") or "").is_dir():
        raise ValueError("That folder does not exist on this computer")
    if kind == "youtube_channel" and not re.fullmatch(r"UC[\w-]{10,40}", str(config_.get("channel_id") or "")):
        raise ValueError("Enter the channel ID (starts with UC, from the channel's About page or URL)")
    return db.insert("source_feeds", {"kind": kind, "name": name[:120], "config": config_,
                                      "rights_status": rights_status, "rights_basis": rights_basis})

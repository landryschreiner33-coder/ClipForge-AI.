"""Where trend signals come from. Only legitimate, authorized sources; nothing is scraped.

* YouTube Data API v3 (official): the mostPopular chart for your region (since July 2025 it covers the Trending
  Music, Movies and Gaming charts), recent top videos for your topics (search.list, its own daily quota bucket),
  live streams with their concurrent viewers, and new uploads of channels you follow. Every call is counted by the
  quota manager, answers are cached, and repeated requests are served from the cache.
* Watch folders: new recordings you put in a folder (your own content, with the rights status you give the folder).
  A file that is still growing is treated as a live recording.
* Stream URLs you are allowed to use (your own HLS/RTMP/SRT stream, a licensed feed).
* Signal feeds: a JSON or CSV file (or URL) of signals from a provider you are authorized to use.
* Originals behind short clips: popular Shorts often link the long video they were cut from; those links are read
  from the videos.list answer (no extra search) and the originals are looked up by ID.
* Web search (optional, Tavily, your own key): public TikTok links for your topics, and the long YouTube videos that
  popular TikTok clips came from. Web search reports titles and links, not live statistics: TikTok numbers stay
  unknown. It counts against a monthly credit allowance and never spends money beyond your cost limit.
* Free-license library (Wikimedia Commons): videos their authors released under a free license, with the license,
  author and any extra restrictions in machine-readable form. Commons exists for reuse, so its files may be
  downloaded; which licenses are used automatically is decided by the rights gate (rights.py).

Every statistic keeps where it came from and when it was observed (trends.m). A number the provider does not report
stays unknown; it is never filled in with a guess.

Not available, and shown as such: Google Trends (the official API is an application-gated alpha) and a TikTok trend
API (TikTok has none for general developers; its Research API is for approved academic research).
"""
from __future__ import annotations

import csv
import datetime as dt
import email.utils
import hashlib
import html
import io
import json
import re
import time
from pathlib import Path
from typing import Iterable

import httpx

from .. import config, db, netguard
from ..publish import youtube
from ..publish.common import PublishError, client, retry_after, wait_text
from . import quota, state, trends

UNAVAILABLE = {
    "google_trends": ("Google Trends", "The official Google Trends API is an application-gated alpha; ClipFoundry "
                                       "does not scrape Google Trends."),
    "tiktok_trends": ("TikTok trends", "TikTok offers no trend or discovery API to general developers (its Research "
                                       "API is limited to approved academic research); ClipFoundry does not scrape "
                                       "TikTok. With a Tavily key, web search finds public TikTok links (without "
                                       "live statistics)."),
}
VIDEO_PARTS = "snippet,statistics,contentDetails,liveStreamingDetails,status"
MIN_STABLE_SECONDS = 60
YOUTUBE_DATA = "YouTube Data API"
SHORT_SECONDS = 180  # a video this short is a clip; the long video it links to is what can be clipped again
YOUTUBE_LINK = re.compile(r"(?:youtube\.com/(?:watch\?(?:[^\s#\"'<>]*&)?v=|live/|shorts/|embed/)|youtu\.be/)([\w-]{11})")


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
        self.errors: list[PublishError] = []

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
            try:
                data = r.json()
                if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
                    raise ValueError("invalid video list")
                return data
            except ValueError as exc:
                raise PublishError("YouTube returned an unreadable answer.", "It is tried again next scan.",
                                   "response") from exc

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
        failed_calls: set[str] = set()

        def attempt(fn, *args, **kw):
            if fn.__name__ in failed_calls or any(e.retry_after is not None or e.code in ("network", "setup", "reconnect")
                                                 for e in self.errors):
                return None
            try:
                return fn(*args, **kw)
            except quota.QuotaDenied as exc:
                self.denied.append(str(exc))
                return None
            except PublishError as exc:
                # Keep results already obtained. An exhausted search API must not erase the chart or prevent
                # a creator's upload list from being checked; a Retry-After or connection problem stops all calls.
                self.errors.append(exc)
                failed_calls.add(fn.__name__)
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
        found_from = self.originals(items, ranked, attempt)
        return [signal_from_video(items[v], *ranked[v], region=region, language=lang, found_from=found_from.get(v, ""))
                for v in ranked if v in items]

    def originals(self, items: dict[str, dict], ranked: dict, attempt) -> dict[str, str]:
        """Popular short clips often link the long video they were cut from. Those originals are added (one
        videos.list call for up to 50 of them). Returns {original id: the clip's URL}."""
        found: dict[str, str] = {}
        for vid in list(ranked):
            item = items.get(vid) or {}
            dur = iso_duration((item.get("contentDetails") or {}).get("duration"))
            if dur is None or dur > SHORT_SECONDS:
                continue
            for linked in linked_videos((item.get("snippet") or {}).get("description") or ""):
                if linked != vid and linked not in ranked and linked not in found:
                    found[linked] = vid
        if not found:
            return {}
        details = attempt(self.videos, list(found)) or {}
        out = {}
        for rank, (linked, short) in enumerate(found.items(), 1):
            if linked in details:
                items[linked] = details[linked]
                title = ((items.get(short) or {}).get("snippet") or {}).get("title") or short
                ranked[linked] = ("youtube_original", rank, len(found), f"original of “{title[:60]}”")
                out[linked] = f"https://www.youtube.com/watch?v={short}"
        return out


def linked_videos(text: str) -> list[str]:
    """YouTube video IDs linked in a description ("full video: youtu.be/..."), in order, without repeats. Only the
    IDs are read from the (untrusted) text."""
    out: list[str] = []
    for vid in YOUTUBE_LINK.findall(text or ""):
        if vid not in out:
            out.append(vid)
    return out[:5]


def signal_from_video(item: dict, provider: str, rank: int, size: int, query: str, region: str = "",
                      language: str = "", found_from: str = "") -> dict:
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
    src = YOUTUBE_DATA
    metrics = {
        "views": trends.m(_int(st.get("viewCount")), note="" if "viewCount" in st else "not reported", at=now,
                          source=src),
        "likes": trends.m(_int(st.get("likeCount")), note="" if "likeCount" in st else hidden, at=now, source=src),
        "comments": trends.m(_int(st.get("commentCount")), note="" if "commentCount" in st else "comments are off",
                             at=now, source=src),
        "live_viewers": trends.m(_int(live.get("concurrentViewers")) if is_live else None,
                                 note="" if is_live else "not live", at=now, source=src),
        "duration_s": trends.m(duration, note="" if duration else "live or unknown", at=now, source=src),
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
                    "duration_s": duration, "privacy": status.get("privacyStatus", ""), "found_from": found_from,
                    "observed_at": now, "reported_by": src}}


def any_time(text: str | None) -> float | None:
    """ISO 8601 or an e-mail style date ("Tue, 10 Sep 2026 14:00:00 GMT"), as web search results give them."""
    t = iso_time(text)
    if t is not None or not text:
        return t
    try:
        return email.utils.parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError, IndexError):
        return None


def plain(text: object, limit: int = 300) -> str:
    """Text without HTML markup (library metadata is HTML), shortened."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))).strip()[:limit]


# ------------------------------------------------------------------ web search (optional: Tavily, your own key)
TAVILY_URL = "https://api.tavily.com/search"
TAVILY_CREDIT_USD = 0.008   # pay-as-you-go price of one credit (tavily.com, 2026); a basic search costs 1 credit
TAVILY = "Tavily web search"
WEB_NOTE = "web search does not report TikTok statistics"
TIKTOK_VIDEO = re.compile(r"https?://(?:www\.|m\.)?tiktok\.com/@([\w.\-]+)/video/(\d+)")
WEB_TOPICS_PER_SCAN = 2     # searches per scan for TikTok links (1 credit each)
WEB_ORIGINALS_PER_SCAN = 2  # searches per scan for the long videos behind popular TikTok clips


def month_key(now: float | None = None) -> str:
    return time.strftime("%Y-%m", time.gmtime(now or time.time()))


def web_usage(settings: dict, now: float | None = None) -> dict:
    """This month's web search credits: used, allowed (free credits + what the cost limit buys) and the cost."""
    used = int(state.get(f"cost:tavily:{month_key(now)}", 0) or 0)
    free = int(settings.get("tavily_free_credits") or 0)
    budget = float(settings.get("discovery_monthly_budget_usd") or 0)
    allowed = free + int(budget / TAVILY_CREDIT_USD)
    return {"used": used, "free": free, "allowed": allowed, "budget_usd": budget,
            "cost_usd": round(max(0, used - free) * TAVILY_CREDIT_USD, 2), "month": month_key(now)}


class WebSearch:
    """Tavily's search API with your key. It finds public pages; it is not a TikTok API, so TikTok results carry no
    statistics. Never exceeds this month's allowance (free credits plus your cost limit)."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.key = settings.get("tavily_api_key") or ""
        if not self.key:
            raise Unavailable("not_configured", "Web search is off (no Tavily API key).",
                              "Optional: Settings → Advanced → Discovery and rights, paste a Tavily API key "
                              "(the free plan includes 1,000 searches a month).")
        self.calls = 0
        self.stopped = ""

    def search(self, query: str, domains: list[str], max_results: int = 10, time_range: str = "week") -> list[dict]:
        until = float(state.get("web:wait_until", 0) or 0)
        if until > time.time():  # Tavily asked to wait: nothing is sent before that time
            raise Unavailable("quota", "Tavily asked to wait before the next search.",
                              f"Web search starts again at {time.strftime('%H:%M', time.localtime(until))}.")
        use = web_usage(self.settings)
        if use["used"] + 1 > use["allowed"]:
            raise Unavailable("budget", f"Web search paused for this month: {use['used']} of {use['allowed']} "
                                        "credits used.",
                              "It starts again next month, or raise the Monthly cost limit in Settings → Advanced → "
                              "Discovery and rights.")
        body = {"query": query[:380], "search_depth": "basic", "topic": "general", "max_results": max_results,
                "include_domains": domains, "time_range": time_range}
        try:
            with client(30) as c:
                r = c.post(TAVILY_URL, json=body, headers={"Authorization": f"Bearer {self.key}"})
        except httpx.HTTPError as exc:
            raise Unavailable("error", f"Could not reach Tavily ({type(exc).__name__}).",
                              "Check the internet connection.") from exc
        if r.status_code in (401, 403):
            raise Unavailable("error", "Tavily did not accept the API key.",
                              "Check the key in Settings → Advanced → Discovery and rights.")
        if r.status_code == 429:
            asked = retry_after(r)
            if asked is not None:
                state.put("web:wait_until", time.time() + asked)
            raise Unavailable("quota", "Tavily is rate limiting requests right now.",
                              f"Tavily asked to wait {wait_text(asked)}; web search starts again then."
                              if asked is not None else "It is tried again next scan.")
        if r.status_code != 200:
            raise Unavailable("error", f"Tavily answered {r.status_code}.", "It is tried again next scan.")
        state.put(f"cost:tavily:{use['month']}", use["used"] + 1)
        self.calls += 1
        try:
            data = r.json()
            results = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results, list):
                raise ValueError("missing results list")
        except ValueError as exc:
            raise Unavailable("error", "Tavily returned an unreadable search result.",
                              "It is tried again next scan.") from exc
        return [x for x in results if isinstance(x, dict)]

    def discover(self, topics: list[str], youtube_: YouTubeDiscovery | None, job=None) -> list[dict]:
        """Public TikTok links for the topics, then the long YouTube videos behind the strongest of them. Stops
        quietly when the allowance runs out (what was found so far is kept)."""
        now = time.time()
        out: list[dict] = []
        tiktok: list[tuple[float, dict]] = []
        try:
            for topic in topics[:WEB_TOPICS_PER_SCAN]:
                if job:
                    job.check()
                if self.settings.get("autopilot_public_videos"):
                    results = self.search(f"{topic} interview podcast video", [], 5, "week")
                    for rank, result in enumerate(results, 1):
                        url = str(result.get("url") or "")
                        if not url.startswith(("https://", "http://")):
                            continue
                        title = plain(result.get("title"), 200) or "Public video"
                        from . import verify

                        platform, external_id = "url", hashlib.sha256(url.encode()).hexdigest()[:32]
                        yt_video, tk_video = verify.link_video("youtube", url), verify.link_video("tiktok", url)
                        if yt_video:
                            platform, external_id = "youtube", yt_video[0]
                            url = f"https://www.youtube.com/watch?v={external_id}"
                        elif tk_video:
                            platform, external_id = "tiktok", tk_video[0]
                            url = f"https://www.tiktok.com/@{tk_video[1].lower()}/video/{external_id}"
                        out.append({"provider": "web_search", "platform": platform, "external_id": external_id,
                                    "kind": "video", "title": title, "url": url, "channel_id": "",
                                    "channel_title": "", "keywords": trends.keywords(title), "query": topic,
                                    "published_at": any_time(result.get("published_date")), "platform_rank": rank,
                                    "metrics": {}, "raw": {"list_size": len(results), "reported_by": TAVILY,
                                                              "observed_at": now, "webpage": platform == "url"}})
                results = self.search(topic, ["tiktok.com"], 10, "week")
                sigs = [s for s in (tiktok_signal(x, topic, k, len(results), now) for k, x in enumerate(results, 1))
                        if s]
                out += sigs
                tiktok += [(float(s["raw"].get("search_score") or 0), s) for s in sigs]
            if youtube_ is not None:
                for _, sig in sorted(tiktok, key=lambda t: -t[0])[:WEB_ORIGINALS_PER_SCAN]:
                    if job:
                        job.check()
                    found = self.search(" ".join(sig["title"].split()[:12]), ["youtube.com"], 5, "month")
                    ids = [v for x in found for v in linked_videos(str(x.get("url") or ""))]
                    try:
                        items = youtube_.videos(list(dict.fromkeys(ids))[:5]) if ids else {}
                    except (quota.QuotaDenied, PublishError):
                        items = {}
                    for rank, (vid, item) in enumerate(items.items(), 1):
                        dur = iso_duration((item.get("contentDetails") or {}).get("duration"))
                        if dur is not None and dur > SHORT_SECONDS:
                            out.append(signal_from_video(item, "youtube_original", rank, len(items),
                                                         f"original of TikTok clip “{sig['title'][:60]}”",
                                                         found_from=sig["url"]))
        except Unavailable as exc:
            if not out:
                raise
            self.stopped = str(exc)
        return out


def tiktok_signal(result: dict, query: str, rank: int, size: int, now: float) -> dict | None:
    """A web search result that is a TikTok video page, as a signal. Titles and links only: TikTok's numbers are not
    in search results, so they stay unknown."""
    mt = TIKTOK_VIDEO.match(str(result.get("url") or ""))
    if not mt:
        return None
    handle, vid = mt.groups()
    title = re.sub(r"\s*[|\-]\s*TikTok\s*$", "", plain(result.get("title"), 200)).strip() or f"TikTok video by @{handle}"
    metrics = {k: trends.m(None, note=WEB_NOTE, at=now, source=TAVILY) for k in ("views", "likes", "comments")}
    return {"provider": "web_search", "platform": "tiktok", "external_id": vid, "kind": "video", "title": title,
            "url": f"https://www.tiktok.com/@{handle}/video/{vid}", "channel_id": f"@{handle}",
            "channel_title": f"@{handle}", "category": "", "keywords": trends.keywords(title), "query": query,
            "region": "", "language": "", "published_at": any_time(result.get("published_date")),
            "platform_rank": rank, "metrics": metrics,
            "raw": {"list_size": size, "search_score": result.get("score"), "reported_by": TAVILY,
                    "observed_at": now, "signal_only": True}}


# ------------------------------------------------------------------ free-license library (Wikimedia Commons)
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS = "Wikimedia Commons"
COMMONS_FILE_HOSTS = ("upload.wikimedia.org",)
# Wikimedia asks every API client for a descriptive User-Agent with a way to reach its author
USER_AGENT = "ClipFoundry/1.0 (local desktop clipping app; https://github.com/landryschreiner33-coder/ClipForge-AI)"
LIBRARY_TOPICS_PER_SCAN = 2
LICENSE_KEYS = ("provider", "license", "license_name", "license_url", "attribution_required", "artist", "credit",
                "restrictions", "page_url", "copyrighted", "reported_by", "observed_at")


class Library:
    """Wikimedia Commons search (MediaWiki API, no key). Every video comes with the license its author chose."""

    def __init__(self, settings: dict):
        if not settings.get("library_discovery", True):
            raise Unavailable("off", "The free-license library search is off.",
                              "Settings → Advanced → Discovery and rights → Free-license library.")
        self.settings = settings
        self.calls = 0

    def search(self, topic: str, limit: int = 10) -> list[dict]:
        params = {"action": "query", "format": "json", "formatversion": "2", "generator": "search",
                  "gsrsearch": f"{topic} filetype:video", "gsrnamespace": "6", "gsrlimit": str(limit),
                  "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata|metadata",
                  "iiextmetadatafilter": "License|LicenseShortName|LicenseUrl|AttributionRequired|Artist|Credit|"
                                         "Restrictions|DateTimeOriginal|ObjectName|Copyrighted"}
        try:
            with client(30) as c:
                r = c.get(COMMONS_API, params=params, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as exc:
            raise Unavailable("error", f"Could not reach Wikimedia Commons ({type(exc).__name__}).",
                              "Check the internet connection.") from exc
        if r.status_code != 200:
            raise Unavailable("error", f"Wikimedia Commons answered {r.status_code}.", "It is tried again next scan.")
        self.calls += 1
        try:
            data = r.json()
            if not isinstance(data, dict):
                raise ValueError("expected an object")
        except ValueError as exc:
            raise Unavailable("error", "Wikimedia Commons returned an unreadable search result.",
                              "It is tried again next scan.") from exc
        if data.get("error"):
            error = data["error"]
            code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
            raise Unavailable("error", f"Wikimedia Commons could not search ({str(code)[:80]}).",
                              "It is tried again next scan.")
        pages = (data.get("query") or {}).get("pages") or []
        if isinstance(pages, dict):  # formatversion 1
            pages = list(pages.values())
        now = time.time()
        pages = sorted((p for p in pages if isinstance(p, dict)), key=lambda p: p.get("index", 0))
        return [s for s in (library_signal(p, topic, k, len(pages), now) for k, p in enumerate(pages, 1)) if s]

    def discover(self, topics: list[str], job=None) -> list[dict]:
        out: list[dict] = []
        for topic in topics[:LIBRARY_TOPICS_PER_SCAN]:
            if job:
                job.check()
            out += self.search(topic)
        return out


def _library_duration(metadata: object) -> float | None:
    """Length in seconds from the file's metadata (the key depends on the container)."""
    stack = [metadata]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("name") in ("playtime_seconds", "length", "duration") and not isinstance(cur.get("value"),
                                                                                                 (list, dict)):
                try:
                    return float(cur["value"])
                except (TypeError, ValueError):
                    pass
            stack += [v for v in cur.values() if isinstance(v, (list, dict))]
        elif isinstance(cur, list):
            stack += cur
    return None


def library_signal(page: dict, query: str, rank: int, size: int, now: float) -> dict | None:
    info = (page.get("imageinfo") or [{}])[0] or {}
    if not str(info.get("mime") or "").startswith("video/") or not info.get("url"):
        return None
    ext = info.get("extmetadata") or {}

    def meta(key: str, limit: int = 300) -> str:
        return plain((ext.get(key) or {}).get("value"), limit)

    duration = _library_duration(info.get("metadata"))
    title = meta("ObjectName", 200) or re.sub(r"^File:|\.\w+$", "", str(page.get("title") or "")).strip()
    artist = meta("Artist", 120)
    return {"provider": "library", "platform": "commons", "external_id": str(page.get("pageid") or page.get("title")),
            "kind": "video", "title": title[:200], "url": str(info["url"]), "channel_id": "",
            "channel_title": artist or COMMONS, "category": "", "keywords": trends.keywords(title), "query": query,
            "region": "", "language": "", "published_at": any_time(meta("DateTimeOriginal")), "platform_rank": rank,
            "metrics": {"views": trends.m(None, note="Wikimedia Commons does not report views", at=now,
                                          source=COMMONS),
                        "duration_s": trends.m(duration, note="" if duration else "not reported", at=now,
                                               source=COMMONS)},
            "raw": {"list_size": size, "provider": "commons", "license": meta("License", 60).lower(),
                    "license_name": meta("LicenseShortName", 80), "license_url": meta("LicenseUrl", 200),
                    "attribution_required": meta("AttributionRequired", 10).lower() == "true", "artist": artist,
                    "credit": meta("Credit", 200), "restrictions": meta("Restrictions", 200),
                    "copyrighted": meta("Copyrighted", 10), "page_url": str(info.get("descriptionurl") or ""),
                    "mime": info.get("mime"), "size": info.get("size"), "duration_s": duration,
                    "reported_by": COMMONS, "observed_at": now}}


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
                    "metrics": {"file_size_mb": trends.m(round(st.st_size / 1e6, 1), at=now, source="this computer")},
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
        metrics = {k: trends.m(_int(row.get(k)), note=f"from {feed.get('name') or 'feed'}", at=now,
                               source=feed.get("name") or "your signal feed")
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

"""Find media: images, footage, music and sound effects from documented provider APIs, for one editing project.

Providers (endpoints and terms checked against each provider's own documentation on 2026-11-05):
* Openverse (https://api.openverse.org/v1/images/ and /v1/audio/): openly licensed images, music and sound effects
  indexed from Flickr, Freesound, Jamendo, Wikimedia and others. No key. Openverse does not verify licenses.
* Wikimedia Commons (MediaWiki Action API, https://commons.wikimedia.org/w/api.php): images, footage and sounds
  under the license each author chose. No key; requests carry a descriptive User-Agent as Wikimedia asks.
* Pexels (https://api.pexels.com/v1/search, /v1/videos/search): photos and footage under the Pexels License. A free
  key is required (by default 200 requests per hour and 20,000 per month).

Nothing searches in the background. A search runs when you search, or when you ask for supporting media for one
project (at most a few queries, never per frame or per render). Results are cached for a few minutes; a provider's
Retry-After is respected, a busy or failing provider is reported in words and the others still answer.

Importing a result looks the item up again at its provider (so the terms recorded are the ones retrieved at that
moment), downloads the file through netguard (public addresses only, every redirect checked, size bounded), checks
the declared type and then the decoded media, and stores it as an ordinary private asset. Its source, creator,
license, retrieval time, original file hash and credit line are kept as asset provenance (asset_sources), separate
from the Brain. A finished edit uses the local copy, so a provider that is later switched off or removes the item
changes nothing in existing projects.

A listing that says "free" is not proof of reuse rights. Unknown or incompatible terms are never added
automatically; adding such an item by hand needs the owner's own stated basis, which is recorded. Titles, creators
and descriptions from providers are untrusted text: they are shown, never interpreted as instructions.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import html
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .. import db, netguard
from ..publish.common import retry_after, wait_text
from . import uploads
from .jobs import Canceled, Lease, enqueue, handler
from .jobs import cancel as cancel_job

KINDS = ("image", "footage", "music", "effect")
KIND_WORDS = {"image": "Images", "footage": "Footage/B-roll", "music": "Music", "effect": "Sound effects"}
ASSET_KIND = {"image": "image", "footage": "video", "music": "audio", "effect": "audio"}
MAX_BYTES = {"image": 40 << 20, "footage": 1 << 30, "music": 200 << 20, "effect": 60 << 20}
PREVIEW_BYTES = {"image": 8 << 20, "audio": 30 << 20, "video": 30 << 20}
LONG_S = {"footage": 15.0, "music": 90.0, "effect": 10.0}  # the "short"/"long" duration filter
PER_PROVIDER = 12
CACHE_TTL = 15 * 60
CACHE_MAX = 128
PREVIEW_TTL = 6 * 3600
TIMEOUT = 20.0
RETRY_PAUSE = 0.5
USER_AGENT = "ClipForge/1.0 (local desktop video editor; https://github.com/landryschreiner33-coder/ClipForge-AI)"
DEFAULT_RULES = {"mode": "suggest", "commercial": True, "share_alike": False}
MODES = ("suggest", "auto")
OPENVERSE = "https://api.openverse.org/v1"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
PEXELS = "https://api.pexels.com/v1"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"
PEXELS_RESTRICTIONS = ("Identifiable people may not appear in a bad light or in an offensive way; do not sell "
                       "unaltered copies; do not imply that people or brands shown endorse you; do not redistribute "
                       "it on other stock or wallpaper platforms.")
# the types a decoded file may have, and the extension the stored asset gets (never taken from the URL)
TYPES = {
    "image": {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"},
    "footage": {"video/mp4": ".mp4", "video/webm": ".webm", "video/ogg": ".ogv", "application/ogg": ".ogv",
                "video/quicktime": ".mov"},
    "audio": {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/ogg": ".ogg", "application/ogg": ".ogg",
              "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/flac": ".flac",
              "audio/x-flac": ".flac", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".aac",
              "audio/opus": ".opus"},
}
PREVIEW_TYPES = {"image": ("image/jpeg", "image/png", "image/webp", "image/gif"),
                 "audio": tuple(TYPES["audio"]), "video": tuple(TYPES["footage"])}
URL_EXT = {"image": {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".webp": ".webp"},
           "footage": {".mp4": ".mp4", ".webm": ".webm", ".ogv": ".ogv", ".mov": ".mov"},
           "audio": {".mp3": ".mp3", ".ogg": ".ogg", ".oga": ".ogg", ".wav": ".wav", ".flac": ".flac",
                     ".m4a": ".m4a", ".opus": ".opus"}}

transport: httpx.BaseTransport | None = None  # tests replace the network with recorded provider answers


class MediaError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


class ProviderError(Exception):
    """A provider could not answer. `state` is one of off, missing_key, bad_key, quota, busy, unavailable, gone,
    error; the message says what happened and what to do."""

    def __init__(self, state: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.state = state
        self.retry_after = retry_after


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    kinds: tuple[str, ...]
    enabled_setting: str
    key_setting: str
    supplies: str
    key_help: str
    limits: str
    terms_url: str
    docs_url: str
    notice: str


PROVIDERS: dict[str, Provider] = {p.id: p for p in (
    Provider("openverse", "Openverse", ("image", "music", "effect"), "media_openverse", "",
             "Openly licensed images, music and sound effects gathered from Flickr, Freesound, Jamendo, Wikimedia "
             "and other collections.",
             "No key needed.",
             "Openverse limits how often anonymous apps may search; the exact limits are set by Openverse and can "
             "change. If it asks ClipForge to wait, searches resume after that time.",
             "https://docs.openverse.org/terms_of_service.html", "https://api.openverse.org/v1/",
             "Search results from Openverse. ClipForge is not endorsed or certified by Openverse."),
    Provider("commons", "Wikimedia Commons", ("image", "footage", "effect"), "media_commons", "",
             "Photos, illustrations, video footage and recorded sounds, each under the license its author chose.",
             "No key needed.",
             "Free to search; Wikimedia asks apps to send one request at a time with a descriptive name, which "
             "ClipForge does.",
             "https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia",
             "https://www.mediawiki.org/wiki/API:Main_page", "Media from Wikimedia Commons."),
    Provider("pexels", "Pexels", ("image", "footage"), "media_pexels", "pexels_api_key",
             "Photos and video footage under the Pexels License (free to use and edit; credit is appreciated, not "
             "required).",
             "Create a free account at pexels.com, then request an API key at https://www.pexels.com/api/ and "
             "paste it here.",
             "Free key. By default 200 requests per hour and 20,000 per month (Pexels' documentation, checked "
             "2026-11-05); Pexels may change this.",
             PEXELS_LICENSE_URL, "https://www.pexels.com/api/documentation/",
             "Photos and videos provided by Pexels (https://www.pexels.com)."),
)}

_lock = threading.Lock()
_cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
_previews: dict[str, dict] = {}
_waits: dict[str, float] = {}
_sem = {pid: threading.BoundedSemaphore(1) for pid in PROVIDERS}  # one request at a time per provider
_PREVIEW_SALT = secrets.token_hex(16)


# ------------------------------------------------------------------ plain text from untrusted metadata
def text(value: object, limit: int = 200) -> str:
    """Provider text as plain, bounded text: HTML tags and entities removed, control characters dropped."""
    s = html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))
    s = "".join(c if c.isprintable() else " " for c in s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def _http_url(value: object) -> str:
    s = str(value or "").strip()
    parts = urlsplit(s)
    return s if parts.scheme in ("http", "https") and parts.hostname and not parts.username else ""


# ------------------------------------------------------------------ licenses
def license_terms(code: str) -> dict:
    """What a license allows for an edited video. Unknown codes are unknown: never assumed to be free."""
    code = (code or "").lower()
    if code in ("cc0", "pdm"):
        return {"known": True, "commercial": True, "modify": True, "attribution": False, "share_alike": False}
    if code == "pexels":
        return {"known": True, "commercial": True, "modify": True, "attribution": False, "share_alike": False}
    if code == "sampling+":  # retired Creative Commons Sampling Plus: no advertising, whole-copy use non-commercial
        return {"known": True, "commercial": False, "modify": True, "attribution": True, "share_alike": False}
    if code == "nc-sampling+":
        return {"known": True, "commercial": False, "modify": True, "attribution": True, "share_alike": False}
    parts = code.split("-")
    if parts and parts[0] == "by" and set(parts[1:]) <= {"nc", "nd", "sa"}:
        return {"known": True, "commercial": "nc" not in parts, "modify": "nd" not in parts, "attribution": True,
                "share_alike": "sa" in parts}
    return {"known": False, "commercial": False, "modify": False, "attribution": True, "share_alike": False}


def license_name(code: str, version: str = "") -> str:
    code = (code or "").lower()
    if code == "cc0":
        return "CC0 " + (version or "1.0")
    if code == "pdm":
        return "Public Domain Mark " + (version or "1.0")
    if code == "pexels":
        return "Pexels License"
    if code in ("sampling+", "nc-sampling+"):
        return ("CC NC-Sampling+ " if code.startswith("nc") else "CC Sampling+ ") + (version or "1.0")
    if code.startswith("by"):
        return ("CC " + code.upper() + (" " + version if version else "")).strip()
    return "Unknown license"


def assess(terms: dict, rules: dict | None = None) -> dict:
    """Whether an item fits a project's rules (commercial use, share-alike), with the reasons in words."""
    rules = {**DEFAULT_RULES, **(rules or {})}
    reasons = []
    if not terms.get("known"):
        reasons.append("The license is not known. Choose another result, or state your own basis for using it.")
    else:
        if not terms.get("modify"):
            reasons.append("No-derivatives license: trimming, cropping or mixing it into your video is not allowed.")
        if rules["commercial"] and not terms.get("commercial"):
            reasons.append("Non-commercial license, and this project counts as commercial use.")
        if terms.get("share_alike") and not rules["share_alike"]:
            reasons.append("Share-alike license: your whole video would have to use the same license. Allow "
                           "share-alike for this project to use it.")
    return {"eligible": not reasons, "reasons": reasons, "credit_required": bool(terms.get("attribution"))}


def credit_line(r: dict) -> str:
    """The credit for one item, built from its retrieved terms (editable later per project)."""
    noun = {"image": "Photo", "footage": "Video", "music": "Music", "effect": "Sound"}[r["kind"]]
    if r["provider"] == "pexels":
        return f"{noun} by {r['creator'] or 'a Pexels contributor'} on Pexels ({r['page_url']})"
    bits = [f"“{r['title']}”" if r["title"] else noun]
    if r["creator"]:
        bits.append(f"by {r['creator']}")
    lic = r["license_name"] + (f" ({r['license_url']})" if r["license_url"] else "")
    where = r.get("origin") or PROVIDERS[r["provider"]].name
    via = f"{where} via Openverse" if r["provider"] == "openverse" and r.get("origin") else where
    return f"{' '.join(bits)}, {lic}, {via}" + (f": {r['page_url']}" if r["page_url"] else "")


def _result(provider: str, kind: str, external_id: str, *, title: str, creator: str = "", creator_url: str = "",
            page_url: str = "", origin: str = "", license_code: str = "unknown", license_version: str = "",
            license_url: str = "", license_label: str = "", restrictions: str = "", width=None, height=None,
            duration_s=None, filetype: str = "", filesize=None, file_url: str = "", preview_image: str = "",
            preview_audio: str = "", preview_video: str = "", mature: bool = False) -> dict:
    code = (license_code or "unknown").lower()
    terms = license_terms(code)
    r = {"id": f"{provider}:{kind}:{external_id}", "provider": provider, "provider_name": PROVIDERS[provider].name,
         "kind": kind, "external_id": str(external_id)[:120], "title": text(title, 160), "creator": text(creator, 120),
         "creator_url": _http_url(creator_url), "page_url": _http_url(page_url), "origin": text(origin, 60),
         "license": code if terms["known"] else "unknown", "license_version": text(license_version, 12),
         "license_name": text(license_label, 80) or license_name(code, license_version),
         "license_url": _http_url(license_url), "terms": terms, "restrictions": text(restrictions, 400),
         "width": int(width) if isinstance(width, (int, float)) and width else None,
         "height": int(height) if isinstance(height, (int, float)) and height else None,
         "duration_s": round(float(duration_s), 1) if isinstance(duration_s, (int, float)) and duration_s else None,
         "filetype": text(filetype, 20), "filesize": int(filesize) if isinstance(filesize, int) else None,
         "mature": bool(mature), "_file": _http_url(file_url), "_preview": {
             "image": _http_url(preview_image), "audio": _http_url(preview_audio), "video": _http_url(preview_video)}}
    r["credit"] = credit_line(r)
    return r


# ------------------------------------------------------------------ HTTP
def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(TIMEOUT, connect=10.0), follow_redirects=False,
                        headers={"User-Agent": USER_AGENT}, transport=transport)


def _get(p: Provider, url: str, params: dict, headers: dict | None = None) -> dict:
    left = _waits.get(p.id, 0.0) - time.time()
    if left > 0:
        raise ProviderError("busy", f"{p.name} asked ClipForge to wait; it is searched again in {wait_text(left)}.",
                            left)
    r = None
    with _sem[p.id]:
        for attempt in (0, 1):  # one retry for a dropped connection or a server error that named no wait
            try:
                with _client() as c:
                    r = c.get(url, params=params, headers=headers or {})
            except httpx.HTTPError as exc:
                if attempt == 0:
                    time.sleep(RETRY_PAUSE)
                    continue
                raise ProviderError("unavailable", f"Could not reach {p.name} ({type(exc).__name__}). Check the "
                                    "internet connection; your own files and projects keep working.") from exc
            if r.status_code >= 500 and attempt == 0 and retry_after(r) is None:
                time.sleep(RETRY_PAUSE)
                continue
            break
    assert r is not None
    if r.status_code == 200:
        try:
            data = r.json()
        except ValueError as exc:
            raise ProviderError("error", f"{p.name} sent an answer ClipForge could not read.") from exc
        if not isinstance(data, dict):
            raise ProviderError("error", f"{p.name} sent an answer ClipForge could not read.")
        return data
    asked = retry_after(r)
    if r.status_code == 429:
        wait = asked if asked is not None else 60.0
        _waits[p.id] = time.time() + wait
        limit = f" ({p.limits})" if p.id == "pexels" else ""
        raise ProviderError("quota", f"{p.name}'s request limit is reached{limit}. Try again in {wait_text(wait)}.",
                            wait)
    if r.status_code in (401, 403):
        if p.key_setting:
            raise ProviderError("bad_key", f"{p.name} did not accept the API key; it may be mistyped, expired or "
                                "revoked. Replace it in Settings → Media sources.")
        raise ProviderError("error", f"{p.name} refused the request ({r.status_code}).")
    if r.status_code in (404, 410):
        raise ProviderError("gone", f"This item is no longer available at {p.name}.")
    if asked is not None:
        _waits[p.id] = time.time() + asked
    if r.status_code >= 500:
        raise ProviderError("unavailable", f"{p.name} is not answering right now ({r.status_code}). Try again later; "
                            "your own files and projects keep working.", asked)
    raise ProviderError("error", f"{p.name} answered {r.status_code}.")


# ------------------------------------------------------------------ Openverse
def _ov(item: dict, kind: str) -> dict | None:
    if not isinstance(item, dict) or not item.get("id") or not item.get("url"):
        return None
    audio = kind in ("music", "effect")
    dur = item.get("duration")
    size = item.get("filesize")
    return _result(
        "openverse", kind, str(item["id"]), title=item.get("title") or "Untitled", creator=item.get("creator"),
        creator_url=item.get("creator_url"), page_url=item.get("foreign_landing_url"),
        origin=str(item.get("source") or item.get("provider") or "").replace("_", " ").title(),
        license_code=item.get("license"), license_version=item.get("license_version") or "",
        license_url=item.get("license_url"), width=item.get("width"), height=item.get("height"),
        duration_s=(dur / 1000) if isinstance(dur, (int, float)) and audio else None,
        filetype=item.get("filetype") or "", filesize=size if isinstance(size, int) else None, file_url=item["url"],
        preview_image=item.get("thumbnail") or ("" if audio else item["url"]),
        preview_audio=item["url"] if audio and (not isinstance(size, int) or size <= PREVIEW_BYTES["audio"]) else "",
        mature=bool(item.get("mature")))


def _ov_search(kind: str, query: str, filters: dict, page: int, settings: dict, rules: dict) -> list[dict]:
    p = PROVIDERS["openverse"]
    params = {"q": query, "page": page, "page_size": PER_PROVIDER, "mature": "false"}
    if filters.get("license") == "fits":
        params["license_type"] = "commercial,modification" if rules["commercial"] else "modification"
    if kind == "image":
        path = "/images/"
        ratio = {"landscape": "wide", "portrait": "tall", "square": "square"}.get(filters.get("orientation", ""))
        if ratio:
            params["aspect_ratio"] = ratio
    else:
        path = "/audio/"
        params["category"] = "music" if kind == "music" else "sound_effect"
        length = {"short": "shortest,short", "long": "medium,long"}.get(filters.get("duration", ""))
        if length:
            params["length"] = length
    data = _get(p, OPENVERSE + path, params)
    return [r for r in (_ov(i, kind) for i in data.get("results") or []) if r]


def _ov_lookup(kind: str, external_id: str, settings: dict) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", external_id):
        raise ProviderError("gone", "That Openverse item ID is not valid.")
    path = f"/images/{external_id}/" if kind == "image" else f"/audio/{external_id}/"
    r = _ov(_get(PROVIDERS["openverse"], OPENVERSE + path, {}), kind)
    if not r:
        raise ProviderError("gone", "Openverse no longer lists a file for this item.")
    return r


# ------------------------------------------------------------------ Wikimedia Commons
def _duration(metadata: object) -> float | None:
    stack = [metadata]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("name") in ("playtime_seconds", "length", "duration") and \
                    not isinstance(cur.get("value"), (list, dict)):
                try:
                    return float(cur["value"])
                except (TypeError, ValueError):
                    pass
            stack += [v for v in cur.values() if isinstance(v, (list, dict))]
        elif isinstance(cur, list):
            stack += cur
    return None


def commons_license(lic: str, short: str) -> tuple[str, str]:
    lic, short = (lic or "").lower().strip(), (short or "").lower()
    m = re.match(r"cc-(by(?:-nc)?(?:-nd|-sa)?)-(\d(?:\.\d)?)", lic)
    if m:
        return m.group(1), m.group(2)
    if lic in ("cc0", "cc-zero") or short.startswith("cc0"):
        return "cc0", "1.0"
    if lic in ("pd", "public domain") or lic.startswith("pd-") or short.startswith("public domain"):
        return "pdm", ""
    return "unknown", ""


def _commons(page: dict, kind: str, big: bool = False) -> dict | None:
    info = (page.get("imageinfo") or [{}])[0] or {}
    mime = str(info.get("mime") or "")
    want = {"image": "image/", "footage": "video/", "effect": "audio/"}[kind]
    if not info.get("url") or not (mime.startswith(want) or (kind == "footage" and mime == "application/ogg")):
        return None
    ext = info.get("extmetadata") or {}

    def meta(key: str, limit: int = 300) -> str:
        return text((ext.get(key) or {}).get("value"), limit)

    code, version = commons_license(meta("License", 60), meta("LicenseShortName", 80))
    size = info.get("size") if isinstance(info.get("size"), int) else None
    file_url = info["url"]
    if kind == "image" and (mime not in TYPES["image"] or (size or 0) > MAX_BYTES["image"]) and big:
        file_url = info.get("thumburl") or ""  # a rendered JPEG/PNG of a TIFF, SVG or very large original
    title = meta("ObjectName", 160) or re.sub(r"^File:|\.\w+$", "", str(page.get("title") or "")).strip()
    small = size is not None and size <= PREVIEW_BYTES["audio"]
    return _result("commons", kind, str(page.get("pageid") or ""), title=title, creator=meta("Artist", 120),
                   page_url=info.get("descriptionurl"), license_code=code, license_version=version,
                   license_url=meta("LicenseUrl", 200), license_label=meta("LicenseShortName", 80),
                   restrictions=meta("Restrictions", 300), width=info.get("width"), height=info.get("height"),
                   duration_s=_duration(info.get("metadata")) if kind != "image" else None,
                   filetype=mime.split("/")[-1], filesize=size, file_url=file_url,
                   preview_image=info.get("thumburl") or "",
                   preview_audio=info["url"] if kind == "effect" and small else "",
                   preview_video=info["url"] if kind == "footage" and small else "")


def _commons_params(width: int) -> dict:
    return {"action": "query", "format": "json", "formatversion": "2", "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata|metadata", "iiurlwidth": str(width),
            "iiextmetadatafilter": "License|LicenseShortName|LicenseUrl|AttributionRequired|Artist|Credit|"
                                   "Restrictions|ObjectName"}


def _commons_search(kind: str, query: str, filters: dict, page: int, settings: dict, rules: dict) -> list[dict]:
    ftype = {"image": "bitmap", "footage": "video", "effect": "audio"}[kind]
    params = {**_commons_params(480), "generator": "search", "gsrsearch": f"{query} filetype:{ftype}",
              "gsrnamespace": "6", "gsrlimit": str(PER_PROVIDER), "gsroffset": str((page - 1) * PER_PROVIDER)}
    data = _get(PROVIDERS["commons"], COMMONS_API, params)
    if data.get("error"):
        raise ProviderError("error", "Wikimedia Commons could not search (" +
                            text((data["error"] or {}).get("code") if isinstance(data["error"], dict) else "", 60) +
                            ").")
    pages = (data.get("query") or {}).get("pages") or []
    pages = sorted((p for p in pages if isinstance(p, dict)), key=lambda p: p.get("index", 0))
    return [r for r in (_commons(p, kind) for p in pages) if r]


def _commons_lookup(kind: str, external_id: str, settings: dict) -> dict:
    if not external_id.isdigit():
        raise ProviderError("gone", "That Wikimedia Commons item ID is not valid.")
    data = _get(PROVIDERS["commons"], COMMONS_API, {**_commons_params(1920), "pageids": external_id})
    pages = (data.get("query") or {}).get("pages") or []
    page = next((p for p in pages if isinstance(p, dict) and str(p.get("pageid")) == external_id), None)
    if not page or page.get("missing"):
        raise ProviderError("gone", "This file was removed from Wikimedia Commons.")
    r = _commons(page, kind, big=True)
    if not r:
        raise ProviderError("gone", "Wikimedia Commons no longer offers a usable file for this item.")
    return r


# ------------------------------------------------------------------ Pexels
def _pexels_key(settings: dict) -> str:
    key = str(settings.get("pexels_api_key") or "").strip()
    if not key:
        raise ProviderError("missing_key", "Pexels needs a free API key. Add it in Settings → Media sources.")
    return key


def _slug_title(url: str, fallback: str) -> str:
    m = re.search(r"/(?:video|photo)/([a-z0-9-]+?)-\d+/?$", url or "")
    return m.group(1).replace("-", " ").capitalize() if m else fallback


def _pexels_photo(p: dict) -> dict | None:
    src = p.get("src") or {}
    if not p.get("id") or not src.get("original"):
        return None
    return _result("pexels", "image", str(p["id"]), title=p.get("alt") or _slug_title(p.get("url", ""), "Photo"),
                   creator=p.get("photographer"), creator_url=p.get("photographer_url"), page_url=p.get("url"),
                   license_code="pexels", license_url=PEXELS_LICENSE_URL, restrictions=PEXELS_RESTRICTIONS,
                   width=p.get("width"), height=p.get("height"), filetype="jpeg", file_url=src["original"],
                   preview_image=src.get("medium") or src.get("small") or "")


def _pexels_video(v: dict) -> dict | None:
    files = [f for f in v.get("video_files") or [] if isinstance(f, dict) and f.get("link") and
             str(f.get("file_type") or "").lower() == "video/mp4" and isinstance(f.get("width"), int)]
    if not v.get("id") or not files:
        return None
    fit = [f for f in files if f["width"] <= 1920]
    best = max(fit, key=lambda f: f["width"]) if fit else min(files, key=lambda f: f["width"])
    small = min(files, key=lambda f: f["width"])
    user = v.get("user") or {}
    return _result("pexels", "footage", str(v["id"]), title=_slug_title(v.get("url", ""), "Video"),
                   creator=user.get("name"), creator_url=user.get("url"), page_url=v.get("url"),
                   license_code="pexels", license_url=PEXELS_LICENSE_URL, restrictions=PEXELS_RESTRICTIONS,
                   width=v.get("width"), height=v.get("height"), duration_s=v.get("duration"), filetype="mp4",
                   file_url=best["link"], preview_image=v.get("image") or "", preview_video=small["link"])


def _pexels_search(kind: str, query: str, filters: dict, page: int, settings: dict, rules: dict) -> list[dict]:
    key = _pexels_key(settings)
    params = {"query": query, "page": page, "per_page": PER_PROVIDER}
    if filters.get("orientation") in ("landscape", "portrait", "square"):
        params["orientation"] = filters["orientation"]
    if kind == "image":
        data = _get(PROVIDERS["pexels"], PEXELS + "/search", params, {"Authorization": key})
        return [r for r in (_pexels_photo(p) for p in data.get("photos") or [] if isinstance(p, dict)) if r]
    data = _get(PROVIDERS["pexels"], PEXELS + "/videos/search", params, {"Authorization": key})
    return [r for r in (_pexels_video(v) for v in data.get("videos") or [] if isinstance(v, dict)) if r]


def _pexels_lookup(kind: str, external_id: str, settings: dict) -> dict:
    if not external_id.isdigit():
        raise ProviderError("gone", "That Pexels item ID is not valid.")
    key = _pexels_key(settings)
    if kind == "image":
        r = _pexels_photo(_get(PROVIDERS["pexels"], f"{PEXELS}/photos/{external_id}", {}, {"Authorization": key}))
    else:
        r = _pexels_video(_get(PROVIDERS["pexels"], f"{PEXELS}/videos/videos/{external_id}", {},
                               {"Authorization": key}))
    if not r:
        raise ProviderError("gone", "Pexels no longer offers a file for this item.")
    return r


SEARCH = {"openverse": _ov_search, "commons": _commons_search, "pexels": _pexels_search}
LOOKUP = {"openverse": _ov_lookup, "commons": _commons_lookup, "pexels": _pexels_lookup}


# ------------------------------------------------------------------ provider status
def provider_state(p: Provider, settings: dict) -> ProviderError | None:
    if not settings.get(p.enabled_setting, True):
        return ProviderError("off", f"{p.name} is switched off in Settings → Media sources.")
    if p.key_setting and not str(settings.get(p.key_setting) or "").strip():
        return ProviderError("missing_key", f"{p.name} needs a free API key. Add it in Settings → Media sources.")
    return None


def providers_view(settings: dict | None = None) -> list[dict]:
    settings = settings if settings is not None else db.get_settings()
    out = []
    for p in PROVIDERS.values():
        st = provider_state(p, settings)
        left = _waits.get(p.id, 0.0) - time.time()
        out.append({"id": p.id, "name": p.name, "kinds": list(p.kinds), "supplies": p.supplies,
                    "key_required": bool(p.key_setting), "key_saved": bool(p.key_setting and
                                                                            settings.get(p.key_setting)),
                    "key_help": p.key_help, "limits": p.limits, "terms_url": p.terms_url, "docs_url": p.docs_url,
                    "notice": p.notice, "enabled": bool(settings.get(p.enabled_setting, True)),
                    "state": st.state if st else ("busy" if left > 0 else "ready"),
                    "message": str(st) if st else (f"Waiting {wait_text(left)} as {p.name} asked." if left > 0
                                                   else "")})
    return out


def check_provider(provider_id: str) -> dict:
    """One small real search, so a key and the connection can be checked without showing the key."""
    p = PROVIDERS.get(provider_id)
    if not p:
        raise MediaError("Unknown media source.", 404)
    settings = {**db.get_settings(), p.enabled_setting: True}
    st = provider_state(p, settings)
    if st:
        return {"ok": False, "state": st.state, "message": str(st)}
    try:
        rows = SEARCH[p.id](p.kinds[0], "mountain", {}, 1, settings, dict(DEFAULT_RULES))
    except ProviderError as exc:
        return {"ok": False, "state": exc.state, "message": str(exc)}
    return {"ok": True, "state": "ready", "message": f"Connected: {p.name} answered with {len(rows)} "
                                                      f"result{'' if len(rows) == 1 else 's'}."}


# ------------------------------------------------------------------ search
def _query(q: str) -> str:
    q = text(q, 100)
    if len(q) < 2:
        raise MediaError("Type at least two letters to search.")
    return q


def _cache_get(key: str) -> list[dict] | None:
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > time.time():
            _cache.move_to_end(key)
            return hit[1]
        _cache.pop(key, None)
    return None


def _cache_put(key: str, rows: list[dict]) -> None:
    with _lock:
        _cache[key] = (time.time() + CACHE_TTL, rows)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)


def _preview_token(ws: str, url: str, media: str) -> str:
    token = hashlib.sha256(f"{_PREVIEW_SALT}|{ws}|{media}|{url}".encode()).hexdigest()[:32]
    with _lock:
        _previews[token] = {"url": url, "media": media, "ws": ws, "until": time.time() + PREVIEW_TTL}
        if len(_previews) > 4000:
            now = time.time()
            for k in [k for k, v in _previews.items() if v["until"] < now][:2000] or list(_previews)[:1000]:
                _previews.pop(k, None)
    return token


def _orientation(r: dict) -> str:
    w, h = r.get("width") or 0, r.get("height") or 0
    if not w or not h:
        return ""
    return "square" if abs(w - h) / max(w, h) < 0.05 else ("landscape" if w > h else "portrait")


def _passes(r: dict, kind: str, filters: dict, verdict: dict) -> bool:
    if r.get("mature"):
        return False
    if filters.get("license") == "fits" and not verdict["eligible"]:
        return False
    if filters.get("license") == "no_credit" and (not verdict["eligible"] or verdict["credit_required"]):
        return False
    o = filters.get("orientation")
    if o in ("landscape", "portrait", "square") and _orientation(r) and _orientation(r) != o:
        return False
    d, dur = filters.get("duration"), r.get("duration_s")
    return not (d in ("short", "long") and kind in LONG_S and dur and (d == "short") != (dur <= LONG_S[kind]))


def public(r: dict, ws: str, verdict: dict | None = None) -> dict:
    """A result as the browser sees it: no file URLs, previews through ClipForge (tokens bound to the workspace)."""
    out = {k: v for k, v in r.items() if not k.startswith("_")}
    out["preview"] = {m: f"/api/studio/media/preview/{_preview_token(ws, u, m)}"
                      for m, u in (r.get("_preview") or {}).items() if u}
    if verdict is not None:
        out["fits"] = verdict
    return out


def search(ws: str, kind: str, query: str, *, providers: list[str] | None = None, filters: dict | None = None,
           page: int = 1, rules: dict | None = None) -> dict:
    if kind not in KINDS:
        raise MediaError("Choose images, footage, music or sound effects.")
    query = _query(query)
    page = max(1, min(int(page or 1), 20))
    filters = {k: str(v) for k, v in (filters or {}).items() if k in ("orientation", "duration", "license") and v}
    rules = {**DEFAULT_RULES, **(rules or {})}
    settings = db.get_settings()
    chosen = [p for p in PROVIDERS.values() if kind in p.kinds and (not providers or p.id in providers)]
    if not chosen:
        raise MediaError(f"No media source offers {KIND_WORDS[kind].lower()}.")

    def one(p: Provider):
        st = provider_state(p, settings)
        if st:
            return p, [], st, False
        key = json.dumps([p.id, kind, query.casefold(), page, sorted(filters.items()), rules["commercial"]])
        hit = _cache_get(key)
        if hit is not None:
            return p, hit, None, True
        try:
            rows = SEARCH[p.id](kind, query, filters, page, settings, rules)
        except ProviderError as exc:
            return p, [], exc, False
        _cache_put(key, rows)
        return p, rows, None, False

    with cf.ThreadPoolExecutor(max_workers=min(3, len(chosen))) as ex:
        answers = list(ex.map(one, chosen))
    statuses, lists = [], []
    for p, rows, err, cached in answers:
        statuses.append({"id": p.id, "name": p.name, "state": err.state if err else "ok",
                         "message": str(err) if err else "", "count": len(rows), "cached": cached,
                         "retry_after": getattr(err, "retry_after", None), "notice": p.notice})
        lists.append(rows)
    seen, results = set(), []
    for k in range(max((len(x) for x in lists), default=0)):  # interleave sources so none crowds out the others
        for rows in lists:
            if k < len(rows):
                r = rows[k]
                dedup = (r["id"], r["_file"])
                if r["id"] in seen or r["_file"] in seen:
                    continue
                seen.update(dedup)
                verdict = assess(r["terms"], rules)
                if _passes(r, kind, filters, verdict):
                    results.append(public(r, ws, verdict))
    return {"kind": kind, "query": query, "page": page, "filters": filters, "results": results,
            "providers": statuses}


# ------------------------------------------------------------------ previews (through ClipForge, bounded)
def preview_target(token: str, ws: str) -> dict:
    with _lock:
        hit = _previews.get(token)
    if not hit or hit["ws"] != ws or hit["until"] < time.time():
        raise MediaError("This preview has expired; search again.", 404)
    return hit


def open_preview(token: str, ws: str):
    """(byte iterator, content type) for a preview, checked like a download: public address, checked redirects,
    the expected type, and a size bound. The caller streams it."""
    target = preview_target(token, ws)
    media, limit = target["media"], PREVIEW_BYTES[target["media"]]
    c = _client()
    try:
        r = netguard.open_checked(c, target["url"])
    except (netguard.UnsafeUrl, httpx.HTTPError) as exc:
        c.close()
        raise MediaError(f"The preview could not be loaded ({str(exc)[:120]}).", 502) from exc
    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
    declared = int(r.headers.get("content-length") or 0)
    if r.status_code != 200 or ctype not in PREVIEW_TYPES[media] or declared > limit:
        r.close()
        c.close()
        why = f"answered {r.status_code}" if r.status_code != 200 else (
            f"is a {ctype or 'file of unknown type'}" if ctype not in PREVIEW_TYPES[media] else "is too large")
        raise MediaError(f"The preview {why}; it is not shown.", 502)

    def body():
        sent = 0
        try:
            for chunk in r.iter_bytes(1 << 16):
                sent += len(chunk)
                if sent > limit:
                    return
                yield chunk
        finally:
            r.close()
            c.close()

    return body(), ctype


# ------------------------------------------------------------------ project rules
def rules_for(project: dict | None) -> dict:
    media = (project or {}).get("media") or {}
    return {**DEFAULT_RULES, **{k: media[k] for k in DEFAULT_RULES if k in media}}


def set_rules(project_id: str, patch: dict) -> dict:
    project = db.fetch("studio_projects", project_id)
    if not project:
        raise MediaError("Project not found.", 404)
    media = dict(project.get("media") or {})
    if "mode" in patch:
        if patch["mode"] not in MODES:
            raise MediaError("Choose Suggest for review or Add eligible media automatically.")
        media["mode"] = patch["mode"]
    for k in ("commercial", "share_alike"):
        if k in patch:
            if type(patch[k]) is not bool:
                raise MediaError(f"{k.replace('_', ' ').capitalize()} must be yes or no.")
            media[k] = patch[k]
    db.update("studio_projects", project_id, media=media, updated_at=time.time())
    return rules_for({"media": media})


# ------------------------------------------------------------------ import
def _parse_id(result_id: str) -> tuple[str, str, str]:
    parts = str(result_id or "").split(":", 2)
    if len(parts) != 3 or parts[0] not in PROVIDERS or parts[1] not in KINDS or not parts[2]:
        raise MediaError("Choose a search result to add.")
    if parts[1] not in PROVIDERS[parts[0]].kinds:
        raise MediaError(f"{PROVIDERS[parts[0]].name} does not offer {KIND_WORDS[parts[1]].lower()}.")
    return parts[0], parts[1], parts[2][:120]


def existing(ws: str, provider: str, external_id: str) -> dict | None:
    rows = db.select("asset_sources", "workspace_id = ? AND provider = ? AND external_id = ?",
                     (ws, provider, external_id))
    if rows:
        a = db.fetch("assets", rows[0]["asset_id"])
        if a and a["workspace_id"] == ws and Path(a["path"]).is_file():
            return rows[0]
    return None


def start_import(ws: str, result_id: str, *, project_id: str = "", basis: str = "") -> dict:
    """Add a search result to your media (and to a project's media bin). The same item is downloaded once per
    workspace; an item whose terms do not fit needs your own stated basis."""
    provider, kind, external_id = _parse_id(result_id)
    basis = text(basis, 500)
    project = None
    if project_id:
        project = db.fetch("studio_projects", project_id)
        if not project or project["workspace_id"] != ws:
            raise MediaError("Project not found.", 404)
    have = existing(ws, provider, external_id)
    if have:
        if project:
            from . import video_flow

            video_flow.add_media(project_id, [have["asset_id"]])
        row = db.insert("media_imports", {"id": "mi-" + os.urandom(6).hex(), "workspace_id": ws,
                                          "project_id": project_id, "provider": provider, "kind": kind,
                                          "external_id": external_id, "title": have["title"], "user_basis": basis,
                                          "status": "ready", "asset_id": have["asset_id"],
                                          "message": "Already in your media"})
        return view_import(row)
    open_rows = db.select("media_imports", "workspace_id = ? AND provider = ? AND external_id = ? AND project_id = ? "
                          "AND status IN ('queued','importing')", (ws, provider, external_id, project_id))
    if open_rows:
        return view_import(open_rows[0])
    p = PROVIDERS[provider]
    st = provider_state(p, db.get_settings())
    if st:
        raise MediaError(str(st), 409)
    row = db.insert("media_imports", {"id": "mi-" + os.urandom(6).hex(), "workspace_id": ws,
                                      "project_id": project_id, "provider": provider, "kind": kind,
                                      "external_id": external_id, "title": "", "user_basis": basis,
                                      "status": "queued", "message": "Waiting to download"})
    enqueue(ws, "media_import", row["id"], 1)
    return view_import(row)


def _ext_for(kind: str, ctype: str, url: str) -> str | None:
    group = "audio" if kind in ("music", "effect") else kind
    if ctype in TYPES[group]:
        return TYPES[group][ctype]
    if ctype in ("application/octet-stream", "binary/octet-stream", ""):
        return URL_EXT[group].get(Path(urlsplit(url).path).suffix.lower())
    return None


def _decoded_ok(path: Path, kind: str) -> str:
    """Refuse a file whose decoded content is not the media it claims to be (an HTML page, an empty stream)."""
    from ..pipeline.ffmpeg_utils import FFmpegError, probe

    try:
        info = uploads.probe_audio(path) if kind in ("music", "effect") else probe(path)
    except (FFmpegError, OSError, ValueError) as exc:
        return f"The downloaded file is not readable media ({str(exc)[:100]})."
    if kind in ("music", "effect") and not float(info.get("duration") or 0) > 0.05:
        return "The downloaded sound has no length."
    if kind in ("image", "footage") and not (info.get("width") and info.get("height")):
        return "The downloaded file has no picture."
    if kind == "footage" and not float(info.get("duration") or 0) > 0.2:
        return "The downloaded video has no length."
    if kind in ("music", "effect") and not info.get("has_audio"):
        return "The downloaded file has no sound."
    return ""


def import_one(ws: str, provider: str, kind: str, external_id: str, *, rules: dict, basis: str = "",
               lease: Lease | None = None, label: str = "") -> tuple[dict, dict]:
    """(asset, provenance row). Raises ProviderError or MediaError; never leaves a partial file or asset."""
    have = existing(ws, provider, external_id)
    if have:
        return db.fetch("assets", have["asset_id"]), have
    settings = db.get_settings()
    p = PROVIDERS[provider]
    st = provider_state(p, settings)
    if st:
        raise st
    if lease:
        lease.progress(0.05, f"Checking the item at {p.name}")
    r = LOOKUP[provider](kind, external_id, settings)
    verdict = assess(r["terms"], rules)
    if not verdict["eligible"] and not basis:
        raise MediaError("Not added: " + " ".join(verdict["reasons"]))
    if r.get("mature"):
        raise MediaError("Not added: the source marks this item as mature content.")
    if not r["_file"]:
        raise ProviderError("gone", f"{p.name} lists no downloadable file for this item.")
    tmp = uploads.uploads_dir() / f"media-{os.urandom(8).hex()}.download"
    found = {"ctype": ""}

    def accept(resp: httpx.Response) -> None:
        if resp.status_code in (404, 410):
            raise ProviderError("gone", f"The file is no longer available at {r['origin'] or p.name}.")
        if resp.status_code != 200:
            raise MediaError(f"The file's host answered {resp.status_code}; nothing was added.", 502)
        found["ctype"] = resp.headers.get("content-type", "").split(";")[0].strip().lower()

    def progress(done: int, total: int) -> None:
        if lease and total:
            lease.progress(0.1 + 0.75 * min(1.0, done / total), f"Downloading {label or r['title']}")

    try:
        with _client() as c:
            netguard.download(c, r["_file"], tmp, max_bytes=MAX_BYTES[kind], accept=accept, progress=progress,
                              cancelled=lease.canceled if lease else None)
        ext = _ext_for(kind, found["ctype"], r["_file"])
        if not ext:
            raise MediaError(f"The file is a {found['ctype'] or 'file of unknown type'}, not a supported "
                             f"{'image (JPEG, PNG or WebP)' if kind == 'image' else ASSET_KIND[kind]} file; "
                             "nothing was added.")
        if lease:
            lease.progress(0.88, "Checking the file")
        problem = _decoded_ok(tmp, kind)
        if problem:
            raise MediaError(problem + " Nothing was added.")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", r["title"]).strip("-")[:50] or kind
        name = f"{slug}-{provider}-{re.sub(r'[^A-Za-z0-9]', '', external_id)[:16]}{ext}"
        try:
            asset = uploads.store_file(ws, tmp, name)
        except uploads.UploadError as exc:
            raise MediaError(str(exc), exc.status) from exc
    except netguard.UnsafeUrl as exc:
        raise MediaError(f"The file was not downloaded: {exc}.") from exc
    except httpx.HTTPError as exc:
        raise ProviderError("unavailable", f"The download from {r['origin'] or p.name} failed "
                            f"({type(exc).__name__}); nothing was added.") from exc
    finally:
        tmp.unlink(missing_ok=True)
        tmp.with_suffix(tmp.suffix + ".part").unlink(missing_ok=True)
    if asset["kind"] != ASSET_KIND[kind]:
        raise MediaError(f"The file turned out to be {asset['kind']}, not {ASSET_KIND[kind]}; it is in your media "
                         "but was not added as this result.")
    try:
        prov = _record_source(ws, asset, r, verdict, basis, label)
    except sqlite3.IntegrityError:  # the same item finished importing elsewhere at the same moment
        prov = existing(ws, provider, external_id) or {}
    return asset, prov


def _record_source(ws: str, asset: dict, r: dict, verdict: dict, basis: str, label: str) -> dict:
    return db.insert("asset_sources", {
        "id": "src-" + os.urandom(6).hex(), "workspace_id": ws, "asset_id": asset["id"], "provider": r["provider"],
        "kind": r["kind"], "external_id": r["external_id"], "title": r["title"], "creator": r["creator"],
        "creator_url": r["creator_url"], "page_url": r["page_url"], "file_url": r["_file"], "origin": r["origin"],
        "license": r["license"], "license_version": r["license_version"], "license_name": r["license_name"],
        "license_url": r["license_url"], "terms": r["terms"], "credit": r["credit"],
        "credit_required": int(verdict["credit_required"]), "restrictions": r["restrictions"],
        "user_basis": "" if verdict["eligible"] else basis, "query": label[:100], "retrieved_at": time.time(),
        "sha256": asset["sha256"], "size": asset["size"]})


@handler("media_import")
def import_job(job: dict, lease: Lease) -> dict:
    row = db.fetch("media_imports", job["target_id"])
    if not row or row["status"] not in ("queued", "importing"):
        return {"skipped": "not waiting"}
    db.update("media_imports", row["id"], status="importing", message="Downloading", error="")
    project = db.fetch("studio_projects", row["project_id"]) if row["project_id"] else None
    try:
        asset, prov = import_one(row["workspace_id"], row["provider"], row["kind"], row["external_id"],
                                 rules=rules_for(project), basis=row["user_basis"], lease=lease)
    except Canceled:
        db.update("media_imports", row["id"], status="canceled", message="Canceled")
        raise
    except (ProviderError, MediaError) as exc:
        db.update("media_imports", row["id"], status="failed", message="Not added", error=str(exc)[:500])
        raise
    except Exception as exc:
        from ..pipeline.common import Cancelled

        if isinstance(exc, Cancelled):
            db.update("media_imports", row["id"], status="canceled", message="Canceled")
            raise
        db.update("media_imports", row["id"], status="failed", message="Not added",
                  error=f"The item could not be added ({str(exc)[:300]}).")
        raise
    if project:
        from . import video_flow

        video_flow.add_media(project["id"], [asset["id"]])
    db.update("media_imports", row["id"], status="ready", asset_id=asset["id"], title=prov["title"],
              message="Added to your media" + (" and this project" if project else ""))
    return {"asset_id": asset["id"]}


def cancel_import(import_id: str, ws: str) -> dict:
    row = db.fetch("media_imports", import_id)
    if not row or row["workspace_id"] != ws:
        raise MediaError("Not found.", 404)
    for j in db.select("studio_jobs", "target_id = ? AND kind = 'media_import' AND status IN ('queued','running')",
                       (import_id,)):
        cancel_job(j["id"])
    if row["status"] in ("queued", "importing"):
        db.update("media_imports", import_id, status="canceled", message="Canceled")
    return view_import(db.fetch("media_imports", import_id))


def view_import(row: dict) -> dict:
    job = db.select("studio_jobs", "target_id = ? AND kind = 'media_import'", (row["id"],), "created_at DESC", 1)
    return {**{k: row.get(k) for k in ("id", "project_id", "provider", "kind", "external_id", "title", "status",
                                       "message", "error", "asset_id")},
            "result_id": f"{row['provider']}:{row['kind']}:{row['external_id']}",
            "progress": job[0]["progress"] if job else (1.0 if row["status"] == "ready" else 0.0),
            "job_message": job[0]["message"] if job else ""}


def get_import(import_id: str, ws: str) -> dict:
    row = db.fetch("media_imports", import_id)
    if not row or row["workspace_id"] != ws:
        raise MediaError("Not found.", 404)
    return view_import(row)


# ------------------------------------------------------------------ provenance and credits
def provenance(asset_ids: list[str], ws: str) -> dict[str, list[dict]]:
    if not asset_ids:
        return {}
    ids = list(dict.fromkeys(asset_ids))
    rows = db.select("asset_sources", f"workspace_id = ? AND asset_id IN ({','.join('?' * len(ids))})",
                     (ws, *ids), "created_at")
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["asset_id"], []).append(r)
    return out


def source_view(r: dict) -> dict:
    return {k: r.get(k) for k in ("provider", "kind", "external_id", "title", "creator", "creator_url", "page_url",
                                  "origin", "license", "license_version", "license_name", "license_url", "terms",
                                  "credit", "restrictions", "user_basis", "retrieved_at", "sha256")} | {
        "provider_name": PROVIDERS[r["provider"]].name if r["provider"] in PROVIDERS else r["provider"],
        "credit_required": bool(r.get("credit_required"))}


def used_assets(plan: dict | None) -> list[str]:
    if not plan:
        return []
    ids = [c["asset_id"] for c in plan.get("clips") or [] if c.get("include", True)]
    ids += [i["asset_id"] for i in plan.get("audio") or [] if not i.get("mute")]
    return list(dict.fromkeys(ids))


def _pname(provider_id: str) -> str:
    return PROVIDERS[provider_id].name if provider_id in PROVIDERS else provider_id


def credits(project: dict, plan: dict | None) -> list[dict]:
    """The credits for media from providers that the current plan uses, with the owner's edits applied."""
    edits = ((project.get("media") or {}).get("credits") or {})
    used = used_assets(plan)
    out = []
    for aid, rows in provenance(used, project["workspace_id"]).items():
        for r in rows:
            key = f"{aid}:{r['provider']}:{r['external_id']}"
            out.append({"key": key, "asset_id": aid, "provider_name": _pname(r["provider"]), "title": r["title"],
                        "creator": r["creator"], "required": bool(r.get("credit_required")),
                        "generated": r["credit"], "text": edits.get(key) or r["credit"], "edited": key in edits,
                        "license_name": r["license_name"], "license_url": r["license_url"],
                        "page_url": r["page_url"], "user_basis": r.get("user_basis") or ""})
    order = {aid: k for k, aid in enumerate(used)}
    return sorted(out, key=lambda c: (order.get(c["asset_id"], 1e9), c["key"]))


def credits_text(project: dict, plan: dict | None) -> str:
    rows = credits(project, plan)
    if not rows:
        return ""
    return "Credits:\n" + "\n".join(f"- {c['text']}" for c in rows)


def edit_credit(project_id: str, key: str, value: str | None) -> list[dict]:
    """Change one credit's wording (empty: back to the generated one). A credit the license requires must keep
    naming the creator and the license."""
    project = db.fetch("studio_projects", project_id)
    if not project:
        raise MediaError("Project not found.", 404)
    from . import video_flow

    plan = video_flow.plan_at(project_id, project["plan_revision"]) if project["plan_revision"] else None
    row = next((c for c in credits(project, plan) if c["key"] == key), None)
    if not row:
        raise MediaError("That credit is not part of this video.", 404)
    media = dict(project.get("media") or {})
    edits = dict(media.get("credits") or {})
    value = text(value, 600)
    if not value:
        edits.pop(key, None)
    else:
        low, missing = value.casefold(), []
        if row["required"]:
            if row["creator"] and row["creator"].casefold() not in low:
                missing.append(f"the creator ({row['creator']})")
            if row["license_name"].casefold() not in low and (not row["license_url"] or
                                                               row["license_url"].casefold() not in low):
                missing.append(f"the license ({row['license_name']})")
        if missing:
            raise MediaError("This credit is required by the license; keep " + " and ".join(missing) + " in it.")
        edits[key] = value
    media["credits"] = edits
    db.update("studio_projects", project_id, media=media, updated_at=time.time())
    return credits(db.fetch("studio_projects", project_id), plan)


def publishing_hold(asset_ids: list[str], ws: str) -> str:
    """Why automatic publishing must wait for the owner (empty when nothing holds it): media from a provider whose
    terms were unknown or did not fit, which was added on the owner's own stated basis."""
    for rows in provenance(asset_ids, ws).values():
        for r in rows:
            if r.get("user_basis") or not (r.get("terms") or {}).get("known"):
                return (f"“{r['title'] or 'A media item'}” from {_pname(r['provider'])} has terms that were unknown "
                        "or did not fit and was added on your own stated basis; automatic posting waits for your "
                        "review.")
    return ""


def required_credit_lines(asset_ids: list[str], ws: str) -> list[str]:
    return [r["credit"] for rows in provenance(asset_ids, ws).values() for r in rows if r.get("credit_required")]


# ------------------------------------------------------------------ supporting media for one project
STOP = set("""a about above after again against all also am an and any are around as at back be because been before
being below between both but by came can come could did do does doing done down during each even every few first for
from further get gets getting go goes going gone gonna good got great had has have having he her here hers herself
him himself his how i if in into is it its itself just know last let like little look lot made make many maybe me
more most much must my myself need never new next no nor not now of off oh ok okay on once one only or other our
ours ourselves out over own really right said same say see she should so some something still such sure take than
that thats the their theirs them themselves then there these they thing things think this those though through time
to today too two under until up us very want was way we well went were what when where which while who whom why will
with would yeah yes you your yours yourself yourselves""".split())  # noqa: SIM905


def topics(words: list[dict], limit: int = 3) -> list[dict]:
    """Distinctive words you say (no AI): longer words you say at least twice, most repeated first, each with when
    it is first said. A word said once is too weak a guess to search for."""
    counts: Counter = Counter()
    first: dict[str, float] = {}
    for w in words:
        t = re.sub(r"[^a-z]", "", str(w.get("w", "")).lower())
        if len(t) >= 4 and t not in STOP:
            counts[t] += 1
            first.setdefault(t, float(w.get("start") or 0))
    ranked = sorted((t for t in counts if counts[t] >= 2), key=lambda t: (-counts[t], first[t]))
    return [{"word": t, "count": counts[t], "first_s": round(first[t], 2)} for t in ranked[:limit]]


def find_for_project(project_id: str, ws: str) -> dict:
    project = db.fetch("studio_projects", project_id)
    if not project or project["workspace_id"] != ws:
        raise MediaError("Project not found.", 404)
    if not project["plan_revision"]:
        raise MediaError("The rough cut is not ready yet.")
    rnd = int(db.scalar("SELECT COALESCE(MAX(round), 0) FROM media_suggestions WHERE project_id = ?",
                        (project_id,)) or 0) + 1
    rules = rules_for(project)
    db.insert("media_suggestions", {"project_id": project_id, "round": rnd, "workspace_id": ws,
                                    "mode": rules["mode"], "status": "queued", "message": "Waiting"},
              key="project_id")
    enqueue(ws, "media_suggest", project_id, rnd)
    return suggestions_view(project_id)


def _place_after(plan: dict, words_by_asset: dict[str, list[dict]], word: str) -> int:
    """The sequence position right after the clip where `word` is first said (the end when it is not found)."""
    for k, c in enumerate(plan.get("clips") or []):
        if c.get("kind") != "video" or not c.get("include", True):
            continue
        for w in words_by_asset.get(c["asset_id"]) or []:
            t = float(w.get("start") or 0) * 1000
            if c["in_ms"] <= t < c["out_ms"] and re.sub(r"[^a-z]", "", str(w.get("w", "")).lower()) == word:
                return k + 1
    return len(plan.get("clips") or [])


@handler("media_suggest")
def suggest_job(job: dict, lease: Lease) -> dict:
    from . import engine, video_flow

    project_id, rnd = job["target_id"], job["revision"]
    rows = db.select("media_suggestions", "project_id = ? AND round = ?", (project_id, rnd))
    project = db.fetch("studio_projects", project_id)
    if not rows or not project:
        return {"skipped": "gone"}
    ws, rules = project["workspace_id"], rules_for(project)

    def save(**fields) -> None:
        db.execute("UPDATE media_suggestions SET " + ", ".join(f"{k} = ?" for k in fields) +
                   ", updated_at = ? WHERE project_id = ? AND round = ?",
                   (*[json.dumps(v) if isinstance(v, (list, dict)) else v for v in fields.values()], time.time(),
                    project_id, rnd))

    save(status="searching", message="Reading what is said")
    plan = video_flow.plan_at(project_id, project["plan_revision"])
    assets = video_flow._assets(project, plan)
    words = video_flow._words(assets)
    spoken = [w for aid in dict.fromkeys(c["asset_id"] for c in plan["clips"] if c.get("kind") == "video")
              for w in words.get(aid) or []]
    queries = [{"kind": "image", "query": t["word"],
                "why": f"You say “{t['word']}” {t['count']} time{'s' if t['count'] != 1 else ''} "
                       f"(first at {int(t['first_s'] // 60)}:{int(t['first_s'] % 60):02d})."}
               for t in topics(spoken)]
    if not queries and project.get("name"):
        queries = [{"kind": "image", "query": text(project["name"], 60), "why": "From the project's name."}]
    brief = project.get("brief") or {}
    if brief.get("music") == "find" and not any(i.get("role") == "music" for i in plan.get("audio") or []):
        feel = ((project.get("guidance") or {}).get("values") or {}).get("feel", "balanced")
        queries.append({"kind": "music", "query": {"calm": "calm ambient", "energetic": "upbeat energetic"}.get(
            feel, "acoustic background"), "why": f"You asked for music; the feel is {feel}."})
    out, problems = [], []
    aspect = (plan.get("output") or {}).get("aspect", "16:9")
    orient = "portrait" if aspect in ("9:16", "4:5") else ("square" if aspect == "1:1" else "landscape")
    for k, q in enumerate(queries):
        if lease.canceled():
            raise Canceled()
        lease.progress(0.1 + 0.4 * k / max(1, len(queries)), f"Searching for {q['query']}")
        try:
            found = search(ws, q["kind"], q["query"], filters={"license": "fits",
                                                               **({"orientation": orient} if q["kind"] == "image"
                                                                  else {})}, rules=rules)
        except MediaError as exc:
            problems.append(str(exc))
            continue
        problems += [s["message"] for s in found["providers"] if s["state"] not in ("ok", "off", "missing_key")]
        out.append({**q, "results": found["results"][:6]})
    save(queries=queries, items=out, message="Adding what fits" if rules["mode"] == "auto" else "Checking results")
    added = []
    if rules["mode"] == "auto":
        picks = []
        for k, o in enumerate(out):
            pick = next((r for r in o["results"] if r["fits"]["eligible"] and r["terms"]["known"]), None)
            if not pick:
                continue
            lease.progress(0.5 + 0.4 * k / max(1, len(out)), f"Adding {pick['title']}")
            provider, kind, external_id = _parse_id(pick["id"])
            try:
                asset, prov = import_one(ws, provider, kind, external_id, rules=rules, lease=None,
                                         label=o["query"])
            except (ProviderError, MediaError) as exc:
                problems.append(f"{pick['title']}: {exc}")
                continue
            picks.append((o, asset, prov))
        if picks:
            for _attempt in range(3):  # a concurrent edit makes a new base; never overwrite it
                project = db.fetch("studio_projects", project_id)
                base = project["plan_revision"]
                plan = video_flow.plan_at(project_id, base)
                video_flow.add_media(project_id, [a["id"] for _, a, _ in picks])
                project = db.fetch("studio_projects", project_id)
                assets = video_flow._assets(project, plan)
                new, notes, added = plan, [], []
                for o, asset, prov in picks:
                    if o["kind"] == "image":
                        at = _place_after(new, words, o["query"])
                        edit = {"op": "insert", "asset_id": asset["id"], "at": at, "duration_ms": 3000}
                    else:
                        values = (project.get("guidance") or {}).get("values") or {}
                        edit = {"op": "add_audio", "asset_id": asset["id"], "role": "music", "loop": True,
                                "gain_db": float(values.get("music_level_db", -18)),
                                "duck": bool(values.get("duck_music", True))}
                    new, _note = video_flow.apply_edit(new, edit, words, assets)
                    if o["kind"] == "image":
                        cid = new["clips"][edit["at"]]["id"]
                        for item in new.get("outline") or []:
                            if item["clip_id"] == cid:
                                item["summary"] = (f"Illustration from {prov['origin'] or _pname(prov['provider'])} "
                                                   f"({prov['license_name']}), not your own footage")
                    added.append({"asset_id": asset["id"], "kind": o["kind"], "title": prov["title"],
                                  "query": o["query"]})
                    notes.append(prov["title"] or o["query"])
                problems_ = engine.validate(new, assets)
                if problems_:
                    problems += problems_
                    added = []
                    break
                try:
                    rev = video_flow.save_revision(project_id, new, "Added supporting media automatically: " +
                                                   ", ".join(notes)[:200], base)
                except video_flow.Conflict:
                    continue
                enqueue(ws, "video_preview", project_id, rev)
                break
    if added:
        message = f"Added {len(added)} item{'s' if len(added) != 1 else ''} as a new version (Undo removes them)"
    elif any(o["results"] for o in out):
        message = "Suggestions ready for review"
    else:
        message = "Nothing that fits this project's license rules was found"
    save(status="ready", added=added, problems=list(dict.fromkeys(problems))[:6], message=message)
    return {"round": rnd, "added": len(added)}


def suggestions_view(project_id: str) -> dict:
    rows = db.select("media_suggestions", "project_id = ?", (project_id,), "round DESC", 1)
    project = db.fetch("studio_projects", project_id) or {}
    out = {"rules": rules_for(project), "latest": None}
    if rows:
        r = rows[0]
        job = db.select("studio_jobs", "target_id = ? AND kind = 'media_suggest' AND revision = ?",
                        (project_id, r["round"]), "created_at DESC", 1)
        out["latest"] = {k: r.get(k) for k in ("round", "mode", "status", "message", "queries", "items", "added",
                                                "problems", "created_at")}
        if job and job[0]["status"] == "failed":
            out["latest"]["status"] = "failed"
            out["latest"]["message"] = job[0]["error"] or "The search failed"
    return out

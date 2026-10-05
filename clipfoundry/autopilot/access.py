"""Getting a source's video file, decided separately from the right to reuse it (rights.py).

A license or an agreement says what you may do with a video; it does not say how you may obtain the file. A connected
YouTube account or a public link is not permission to download. ClipFoundry gets a file automatically only in these
ways:

* local           a file on this computer (your recordings, a watch folder, a file you added)
* creator_folder  a folder the creator shares with you (for example a synced Dropbox or Google Drive folder), named in
                  your agreement: the video's file is found by its YouTube ID in the file name, or by its title
* creator_link    a direct file link under the address the creator gave you in the agreement
* library         a free-license library that exists for reuse and serves its files for download (Wikimedia Commons)
* feed_link       a direct media or stream link from a feed you configured, or a link you added yourself
* platform        a platform-hosted video, only with "Download authorized platform sources" turned on in Advanced
                  after you checked the platform's terms (off by default), or a recorded public video in the
                  explicitly enabled Local test mode, which keeps all uploads off

Anything else is skipped (listed in the activity log with the reason) and Source Scout moves on to the next video.
Adding the file yourself stays possible.
"""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

from .. import config
from ..pipeline import fingerprint
from . import rights

LIBRARY_HOSTS = {"commons": ("upload.wikimedia.org",)}
LIBRARY_SCHEMES = ("https",)
PLATFORM_NAMES = {"youtube": "YouTube", "tiktok": "TikTok"}
SAME_TITLE = 0.8          # word overlap of a file name with the video's title
STABLE_SECONDS = 60       # a file still being synced or written is not used yet
METHOD_LABELS = {"local": "File on this computer", "creator_folder": "Creator's shared folder",
                 "creator_link": "Link from the creator", "library": "Free-license library download",
                 "feed_link": "Direct link", "platform": "Platform download you allowed"}


def _ok(method: str, detail: str, **where: str) -> dict:
    return {"ok": True, "method": method, "label": METHOD_LABELS[method], "detail": detail, **where}


def _no(detail: str) -> dict:
    return {"ok": False, "method": "", "label": "No allowed way to get the file", "detail": detail}


def _host_in(url: str, hosts: tuple[str, ...]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return urlparse(url).scheme in LIBRARY_SCHEMES and any(host == h or host.endswith("." + h) for h in hosts)


def find_in_folder(folder: str, source: dict, now: float | None = None) -> Path | None:
    """The creator's file for this video in their shared folder: the YouTube ID in the file name, or the same title.
    A file changed in the last minute (still syncing) is left for the next look."""
    root = Path(folder)
    if not folder or not root.is_dir():
        return None
    now = now or time.time()
    ext_id = (source.get("external_id") or "") if source.get("platform") == "youtube" else ""
    title = source.get("title") or ""
    best: tuple[float, Path] | None = None
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in config.VIDEO_EXTENSIONS or f.name.startswith("."):
            continue
        if now - f.stat().st_mtime < STABLE_SECONDS:
            continue
        if ext_id and ext_id in f.stem:
            return f
        sim = fingerprint.title_similarity(f.stem.replace("_", " "), title) if title else 0.0
        if sim >= SAME_TITLE and (best is None or sim > best[0]):
            best = (sim, f)
    return best[1] if best else None


def resolve(source: dict, settings: dict) -> dict:
    """How this source's file may be obtained: {"ok", "method", "label", "detail", "local_path" | "url"}."""
    local = source.get("local_path") or ""
    if local:
        if Path(local).exists():
            return _ok("local", "Local file", local_path=local)
        return _no("The local file no longer exists")
    conds = rights.evaluate(source, settings).get("conditions") or {}
    if conds.get("media_folder"):
        found = find_in_folder(conds["media_folder"], source)
        if found:
            return _ok("creator_folder", f"Found in the folder {conds.get('creator') or 'the creator'} shares with you",
                       local_path=str(found))
    url = source.get("url") or ""
    if not url:
        return _no("No file or link")
    prefix = conds.get("media_url_prefix") or ""
    if prefix and url.lower().startswith(prefix.lower()):
        return _ok("creator_link", f"A file link {conds.get('creator') or 'the creator'} gave you", url=url)
    hosts = LIBRARY_HOSTS.get(source.get("platform") or "")
    if hosts:
        if _host_in(url, hosts):
            return _ok("library", "Wikimedia Commons serves its files for reuse", url=url)
        return _no("The link is not one of the library's own files")
    if rights.is_platform_url(url) and source.get("platform") != "stream":
        if (settings.get("autopilot_local_test_mode") and source.get("kind", "recorded") == "recorded"
                and rights.local_allowed(source, settings=settings)):
            return {**_ok("platform", "Public video for Local test mode; uploads are off", url=url),
                    "label": "Public video for local testing"}
        if settings.get("rights_allow_remote_download"):
            return _ok("platform", "Download allowed in Settings for authorized sources", url=url)
        where = PLATFORM_NAMES.get(source.get("platform") or "", "The platform")
        waiting = f" (not in {conds['creator']}'s shared folder yet)" if conds.get("media_folder") else ""
        return _no(f"{where} does not allow downloading its videos without its permission{waiting}. Add the original "
                   "file if you have it (for your own videos: YouTube Studio → Download).")
    return _ok("feed_link", "Direct media or stream URL", url=url)


def record(source: dict, found: dict) -> dict:
    """What is stored with the source: how the file was (or could not be) obtained, and when."""
    return {"ok": found["ok"], "method": found["method"], "label": found["label"], "detail": found["detail"],
            "at": time.time()}

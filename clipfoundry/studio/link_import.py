"""Make clips from a video link: the same project flow as an uploaded file.

A supplied link is normalized without any network access (one recording; playlist, timestamp and tracking
parameters dropped) and the whole Make clips request (mode, style, choices, skill overrides, destinations and the
reuse statement) is validated and frozen into the project before anything is downloaded, exactly as for a file.
A durable studio job then downloads that one recording with the bounded public extractor (no cookies, sign-ins,
protected formats or search keys), stores it as a private asset like an upload (the same bytes are one asset),
and hands the project to the normal clip pipeline.

Progress, cancel and retry survive a page refresh and an app restart (the job, its lease and yt-dlp's partial file
stay in place); asking again with the same request ID returns the same project instead of a second download.
Partial files of a canceled or failed import are removed. Downloading the recording the owner chose is not source
discovery: nothing here searches for videos.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .. import config, db
from . import clips_flow, uploads
from .jobs import Canceled, Lease, cancel as cancel_job, enqueue, handler

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com",
                 "www.youtube-nocookie.com"}
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
TRACKING = re.compile(r"^(utm_.+|fbclid|gclid|dclid|msclkid|igshid|mc_cid|mc_eid|si|feature|ref|ref_src|pp|ab_channel)$",
                      re.I)
ACTIVE = ("queued", "running")

# code: (short label, why, what to do instead), in the studio's words. Nothing is ever worked around.
MESSAGES = {
    "invalid": ("Not a video link", "That is not a web address ClipForge can use.",
                "Paste a link that starts with https://, or use Video file."),
    "playlist": ("Not one video", "The link leads to a playlist, not to one video.",
                 "Open the video you want and copy its own link, or use Video file."),
    "channel": ("Not one video", "The link leads to a channel or profile, not to one video.",
                "Open the video you want and copy its own link."),
    "not_one_video": ("Not one video", "This YouTube address does not point to one video.",
                      "Use a watch, Shorts or youtu.be link to one video."),
    "live_only": ("Live stream", "This is a live or upcoming stream, or its recording is still being processed.",
                  "Add the link again once the finished recording is available, or upload your own copy."),
    "login_required": ("Sign-in required", "The website only shares this video with signed-in viewers or members. "
                       "ClipForge never signs in or uses your browser's cookies.",
                       "If it is your video, download your own copy and use Video file."),
    "private": ("Private video", "This video is private.", "If it is your video, use Video file with your copy."),
    "access_denied": ("Access denied", "The website refused to share this video's file.",
                      "Use Video file with your own copy."),
    "geo_blocked": ("Restricted", "The website does not show this video in this country.",
                    "Use Video file with your own copy."),
    "protected": ("Copy-protected", "This video is copy-protected (DRM). ClipForge never gets around a protection.",
                  "Use Video file with a copy you are allowed to edit."),
    "not_found": ("Unavailable", "This video was removed, made unavailable, or the link is wrong.",
                  "Check the link in a browser, or use Video file."),
    "unsupported_site": ("Unsupported website", "ClipForge has no supported way to get videos from this website.",
                         "Use a direct link to the video file, or Video file."),
    "rate_limited": ("Asked to slow down", "The website asked ClipForge to slow down.",
                     "Press Retry in a few minutes."),
    "network": ("Network problem", "The website did not answer properly.",
                "Check this computer's internet connection and press Retry."),
    "too_large": ("Over the limits", "The video is larger than the upload limit.",
                  "Use a shorter video, or trim your own copy and use Video file."),
    "disk_space": ("Disk almost full", "There is not enough free disk space for this download.",
                   "Free up space on the drive of the data folder and press Retry."),
    "extraction_failed": ("No video found", "No downloadable video was found at this link.",
                          "Use a direct link to the video, or Video file."),
    "unsafe": ("Address not allowed", "ClipForge does not fetch this address (a private network or unsafe link).",
               "Use a public link, or Video file."),
    "no_downloader": ("Link import not installed", "This installation has no video downloader (yt-dlp).",
                      "Use Video file, or reinstall ClipForge."),
    "tools_missing": ("Video tools missing", "ClipForge could not find its video tools (FFmpeg), which join the "
                      "video's picture and sound after the download.",
                      "Reinstall ClipForge, or set the FFmpeg folder in Settings, then press Retry."),
}
TEMPORARY = {"rate_limited", "network", "disk_space"}


class LinkError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code if code in MESSAGES else "extraction_failed"
        label, why, fix = MESSAGES[self.code]
        super().__init__(detail or why)
        self.label, self.why, self.fix = label, (detail or why), fix

    def view(self) -> dict:
        return {"code": self.code, "label": self.label, "why": self.why, "fix": self.fix,
                "temporary": self.code in TEMPORARY}


# ------------------------------------------------------------------ normalizing a supplied link
def normalize(raw: str) -> dict:
    """{"url": canonical link, "platform": "youtube" | "link", "video_id", "title"}; LinkError without network.

    A YouTube watch, Shorts, live, embed or youtu.be link becomes https://www.youtube.com/watch?v=ID, so a link
    that also names a playlist imports only its own video and the same video always has the same address."""
    value = (raw or "").strip()
    if not value or len(value) > 4096 or any(ord(c) < 32 for c in value) or " " in value:
        raise LinkError("invalid")
    if "://" not in value and re.match(r"^(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", value, re.I):
        value = "https://" + value
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 - raises for a malformed port
    except ValueError as exc:
        raise LinkError("invalid") from exc
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise LinkError("invalid")
    if parts.username or parts.password:
        raise LinkError("invalid", "Use a public link without a user name or password.")
    host = parts.hostname.lower().rstrip(".")
    if host == "youtu.be" or host in YOUTUBE_HOSTS:
        video_id = ""
        path = parts.path.rstrip("/")
        if host == "youtu.be":
            video_id = path.strip("/").split("/")[0] if path else ""
        elif path == "/watch":
            video_id = dict(parse_qsl(parts.query)).get("v", "")
        else:
            m = re.fullmatch(r"/(?:shorts|live|embed|v|e)/([^/]+)", path)
            if m:
                video_id = m.group(1)
            elif path == "/playlist" or (path == "/watch_videos"):
                raise LinkError("playlist")
            elif re.match(r"^/(@|channel/|c/|user/)", path):
                raise LinkError("channel")
        if not VIDEO_ID.fullmatch(video_id or ""):
            if dict(parse_qsl(parts.query)).get("list"):
                raise LinkError("playlist")
            raise LinkError("not_one_video")
        return {"url": f"https://www.youtube.com/watch?v={video_id}", "platform": "youtube", "video_id": video_id,
                "title": f"YouTube video {video_id}"}
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING.match(k)])
    clean = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", query, ""))
    name = Path(parts.path).name[:100]
    return {"url": clean, "platform": "link", "video_id": "", "title": name or host}


# ------------------------------------------------------------------ starting, canceling, retrying
def imports_dir() -> Path:
    d = config.data_dir() / "link-imports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _staging(import_id: str) -> Path:
    safe = "".join(c for c in import_id if c.isalnum() or c in "-_")
    return imports_dir() / safe


def for_project(project_id: str) -> dict | None:
    rows = db.select("link_imports", "project_id = ?", (project_id,), "created_at DESC", 1)
    return rows[0] if rows else None


def _job(row: dict) -> dict | None:
    jobs = db.select("studio_jobs", "kind = 'link_import' AND target_id = ?", (row["id"],), "created_at DESC", 1)
    return jobs[0] if jobs else None


def start(workspace_id: str, user_id: str, *, url: str, request_id: str = "", mode: str, style_id: str = "saved",
          choices: dict | None = None, skills_on: list[str] | None = None, skills_off: list[str] | None = None,
          upload: dict | None = None, reference_id: str = "") -> dict:
    """Validate everything, create the project (status "importing") and queue the download; returns the project.
    The same request ID, or the same link and mode while its first import is still running, returns that project."""
    link = normalize(url)
    request_id = re.sub(r"[^A-Za-z0-9_-]", "", request_id or "")[:64]
    if request_id:
        same = db.select("link_imports", "workspace_id = ? AND request_id = ?", (workspace_id, request_id))
        if same and db.get_project(same[0]["project_id"]):
            return {**db.get_project(same[0]["project_id"]), "already_started": True}  # type: ignore[dict-item]
    for row in db.select("link_imports", "workspace_id = ? AND url = ? AND mode = ? AND status IN ('queued', "
                         "'running')", (workspace_id, link["url"], mode)):
        project = db.get_project(row["project_id"])
        if project and project["status"] == "importing":
            return {**project, "already_started": True}
    ready = clips_flow.prepare(workspace_id, mode=mode, style_id=style_id, choices=choices, skills_on=skills_on,
                               skills_off=skills_off, upload=upload, title=link["title"],
                               reference_id=reference_id)
    project = db.create_project(link["title"][:120], source_url=link["url"], status="importing", stage="download",
                                message="Waiting to download the video", workspace_id=workspace_id, clip_mode=mode,
                                guidance=ready["guidance"], destinations=ready["destinations"],
                                options=ready["options"],
                                info={"link": {"url": link["url"], "original": url.strip()[:600],
                                               "platform": link["platform"], "video_id": link["video_id"]}})
    pdir = config.projects_dir() / project["id"]
    pdir.mkdir(parents=True, exist_ok=True)
    row = db.insert("link_imports", {"id": "imp-" + os.urandom(6).hex(), "workspace_id": workspace_id,
                                     "request_id": request_id or os.urandom(8).hex(), "url": link["url"],
                                     "original_url": url.strip()[:600], "mode": mode, "project_id": project["id"],
                                     "status": "queued"})
    clips_flow.remember_mode(workspace_id, user_id, mode)
    enqueue(workspace_id, "link_import", row["id"], 0)
    return db.get_project(project["id"])  # type: ignore[return-value]


def cancel(project_id: str) -> bool:
    row = for_project(project_id)
    if not row or row["status"] not in ACTIVE:
        return False
    job = _job(row)
    if job:
        cancel_job(job["id"])
    db.update("link_imports", row["id"], status="canceled")
    db.update_project(project_id, status="cancelled", message="Canceled; nothing was downloaded into your library")
    shutil.rmtree(_staging(row["id"]), ignore_errors=True)
    return True


def retry(project_id: str) -> dict:
    """Try the same link again with the same frozen request (a new download job; the old one stays in history)."""
    row = for_project(project_id)
    project = db.get_project(project_id)
    if not row or not project:
        raise clips_flow.FlowError("This project was not made from a link.")
    if row["status"] in ACTIVE:
        return project
    attempt = int(row.get("round") or 0) + 1  # a new job: the failed one stays in the history
    db.update("link_imports", row["id"], status="queued", error="", error_code="", round=attempt)
    db.update_project(project_id, status="importing", stage="download", progress=0, error="",
                      message="Waiting to download the video")
    enqueue(project["workspace_id"], "link_import", row["id"], attempt)
    return db.get_project(project_id)  # type: ignore[return-value]


def clean_abandoned() -> int:
    """Remove partial downloads whose import is no longer running (canceled, failed, finished or forgotten)."""
    n = 0
    root = imports_dir()
    for folder in root.iterdir():
        row = db.fetch("link_imports", folder.name)
        if row and row["status"] in ACTIVE:
            continue
        shutil.rmtree(folder, ignore_errors=True)
        n += 1
    return n


# ------------------------------------------------------------------ the download job
def _fail(row: dict, project_id: str, err: LinkError) -> None:
    db.update("link_imports", row["id"], status="failed", error=str(err)[:500], error_code=err.code)
    project = db.get_project(project_id) or {}
    info = {**(project.get("info") or {}), "link_error": err.view()}
    db.update_project(project_id, status="error", stage="download", message=err.label,
                      error=f"{err.why} {err.fix}"[:1000], info=info)
    shutil.rmtree(_staging(row["id"]), ignore_errors=True)


def _classify(exc: BaseException) -> LinkError:
    from .. import netguard
    from ..jobs import DownloadRefused
    from ..media_import import MediaUnavailable

    if isinstance(exc, LinkError):
        return exc
    if isinstance(exc, DownloadRefused):
        return LinkError(exc.code if exc.code in MESSAGES else "too_large", str(exc))
    if isinstance(exc, MediaUnavailable):
        return LinkError(exc.code)
    if isinstance(exc, netguard.UnsafeUrl):
        return LinkError("unsafe")
    if isinstance(exc, ImportError):
        return LinkError("no_downloader")
    return LinkError("extraction_failed", str(exc)[:300] or None)


def fetch(url: str, staging: Path, progress, cancelled) -> tuple[Path, dict]:
    """Download the one recording (replaced in tests by a local fixture)."""
    from .. import netguard
    from ..jobs import fetch_public_video

    try:
        import yt_dlp  # noqa: F401
    except ImportError as exc:
        raise LinkError("no_downloader") from exc
    from ..cloud import settings as cloud_settings

    if cloud_settings.enabled():
        netguard.check(url, allow_private=False)  # a server never fetches its own network for anyone
    return fetch_public_video(url, staging, progress=progress, cancelled=cancelled,
                              max_bytes=uploads.max_upload_bytes(), free_space_dir=config.data_dir(),
                              refuse_live=True)


@handler("link_import")
def run(job: dict, lease: Lease) -> dict:
    row = db.fetch("link_imports", job["target_id"])
    if not row:
        raise ValueError("This link import no longer exists.")
    project = db.get_project(row["project_id"])
    if not project or project["status"] == "cancelled" or row["status"] == "canceled":
        raise Canceled()
    if row.get("asset_id"):  # the download finished before an interruption: never download it twice
        clips_flow.attach_source(project["id"], db.fetch("assets", row["asset_id"]) or {})
        return {"asset_id": row["asset_id"]}
    db.update("link_imports", row["id"], status="running", attempts=int(row.get("attempts") or 0) + 1)
    db.update_project(project["id"], status="importing", stage="download", message="Downloading the video")
    last = [0.0]

    def progress(done: int, total: int, text: str) -> None:
        frac = min(1.0, done / total) if total else 0.0
        lease.progress(0.9 * frac, f"Downloading {text}".strip())
        now = time.time()
        if now - last[0] > 0.5:
            last[0] = now
            db.update_project(project["id"], progress=round(frac, 4), message=f"Downloading {text}".strip())

    staging = _staging(row["id"])
    try:
        path, meta = fetch(row["url"], staging, progress, lease.canceled)
    except Canceled:
        raise
    except BaseException as exc:  # noqa: BLE001 - every reason is shown in plain words
        from ..pipeline.common import Cancelled

        if isinstance(exc, Cancelled) or lease.canceled():
            raise Canceled() from None
        if not isinstance(exc, Exception):
            raise
        _fail(row, project["id"], _classify(exc))
        return {"failed": True}
    if lease.canceled():
        raise Canceled()
    lease.progress(0.92, "Checking the downloaded file")
    title = " ".join(str((meta or {}).get("title") or project["name"]).split())[:120]  # a caption's lines: one line
    safe = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", title).strip(" .") or "video"
    try:
        asset = uploads.store_file(project["workspace_id"], path, f"{safe[:100]}{path.suffix.lower()}")
    except uploads.UploadError as exc:
        _fail(row, project["id"], LinkError("extraction_failed", f"The downloaded file is not usable: {exc}"))
        return {"failed": True}
    shutil.rmtree(staging, ignore_errors=True)
    if asset["kind"] != "video":
        _fail(row, project["id"], LinkError("extraction_failed", "The link did not lead to a video."))
        return {"failed": True}
    db.update("link_imports", row["id"], status="done", asset_id=asset["id"], title=title)
    info = {**(project.get("info") or {}), "link": {**((project.get("info") or {}).get("link") or {}),
                                                     "title": title,
                                                     "uploader": str((meta or {}).get("uploader") or "")[:120],
                                                     "duration": (meta or {}).get("duration")}}
    info.pop("link_error", None)
    db.update_project(project["id"], name=title, source_filename=Path(asset["path"]).name, info=info,
                      status="queued", stage="queued", progress=0, message="Downloaded; waiting to process")
    clips_flow.attach_source(project["id"], asset)
    return {"asset_id": asset["id"]}


def view(project: dict) -> dict | None:
    row = for_project(project["id"])
    if not row:
        return None
    job = _job(row)
    return {"id": row["id"], "url": row["url"], "status": row["status"], "error_code": row.get("error_code") or "",
            "asset_id": row.get("asset_id") or "", "attempts": row.get("attempts") or 0,
            "job": {k: job[k] for k in ("id", "status", "progress", "message")} if job else None,
            "problem": ((project.get("info") or {}).get("link_error")) if row["status"] == "failed" else None}

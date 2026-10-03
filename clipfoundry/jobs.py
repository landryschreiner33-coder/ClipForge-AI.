"""Single background worker: one heavy job at a time keeps a laptop responsive."""
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from . import db
from .pipeline import process
from .pipeline.common import Cancelled, JobContext, log


class Worker:
    def __init__(self) -> None:
        self.q: queue.Queue = queue.Queue()
        self.cancelled: set[str] = set()
        self.current: str | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, daemon=True, name="clipfoundry-worker")
            self._thread.start()

    # ------------------------------------------------------------- submit
    def submit_project(self, project_id: str, url: str | None = None) -> None:
        self.cancelled.discard(project_id)
        db.update_project(project_id, status="queued", progress=0, stage="queued", error="",
                          message="Waiting in queue")
        self.q.put(("project", project_id, url))
        self.start()

    def submit_render(self, clip_id: str) -> None:
        self.cancelled.discard(clip_id)
        clip = db.get_clip(clip_id) or {}
        info = {**(clip.get("render_info") or {}), "manual_render_pending": True}
        db.update_clip(clip_id, status="queued", progress=0, error="", render_info=info)
        self.q.put(("render", clip_id, None))
        self.start()

    def submit_version(self, version_id: str) -> None:
        self.cancelled.discard(version_id)
        db.update_version(version_id, status="queued", progress=0, error="")
        self.q.put(("version", version_id, None))
        self.start()

    def cancel(self, key: str) -> None:
        self.cancelled.add(key)

    def cancel_all(self) -> int:
        """STOP ALL JOBS: cancel everything queued and the running job (at its next check)."""
        keys = []
        while True:
            try:
                kind, key, extra = self.q.get_nowait()
            except queue.Empty:
                break
            keys.append(key)
            self._mark_cancelled(kind, key)
            self.q.task_done()
        if self.current:
            self.cancelled.add(self.current)
            keys.append(self.current)
        return len(keys)

    def resume(self, work: dict) -> dict:
        """Continue what was queued or running when the app stopped (cached audio and transcripts are reused).

        A project interrupted twice in a row is not resumed again automatically: it may be what stops the app.
        """
        resumed = {"projects": 0, "clips": 0, "versions": 0, "not_resumed": 0}
        for p in work.get("projects", []):
            try:
                info = json.loads(p.get("info") or "{}")
            except ValueError:
                info = {}
            count = int(info.get("resume_count", 0)) + 1
            if count > 2:
                db.update_project(p["id"], status="error", message="Failed",
                                  error="Interrupted again while processing (the app was closed or stopped twice). "
                                        "Click Retry to try once more.")
                resumed["not_resumed"] += 1
                continue
            db.update_project(p["id"], info={**info, "resume_count": count})
            source_missing = not p.get("source_path") or not Path(p["source_path"]).exists()
            self.submit_project(p["id"], url=p.get("source_url") if source_missing and p.get("source_url") else None)
            resumed["projects"] += 1
        for clip_id in work.get("clips", []):
            self.submit_render(clip_id)
            resumed["clips"] += 1
        for version_id in work.get("versions", []):
            self.submit_version(version_id)
            resumed["versions"] += 1
        if any(resumed.values()):
            log.info("Resumed after restart: %s", resumed)
        return resumed

    # ------------------------------------------------------------- loop
    def _loop(self) -> None:
        while True:
            kind, key, extra = self.q.get()
            self.current = key
            try:
                if key in self.cancelled:
                    self._mark_cancelled(kind, key)
                elif kind == "project":
                    self._run_project(key, extra)
                elif kind == "render":
                    self._run_render(key)
                elif kind == "version":
                    self._run_version(key)
            except Exception:  # noqa: BLE001 - never let the worker die
                log.exception("job crashed")
            finally:
                self.current = None
                self.q.task_done()

    def _mark_cancelled(self, kind: str, key: str) -> None:
        if kind == "project":
            db.update_project(key, status="cancelled", message="Cancelled")
        elif kind == "version":
            db.update_version(key, status="error", error="Cancelled")
        else:
            db.update_clip(key, status="error", error="Cancelled")

    def _run_project(self, project_id: str, url: str | None) -> None:
        last = [0.0]

        def report(frac: float, msg: str) -> None:
            now = time.time()
            if now - last[0] > 0.4 or frac >= 1.0:
                last[0] = now
                db.update_project(project_id, progress=round(frac, 4), message=msg)

        ctx = JobContext(report, lambda: project_id in self.cancelled)
        db.update_project(project_id, status="processing", message="Starting")
        try:
            if url:
                self._download(project_id, url, ctx)
            process.run_project(project_id, ctx)
            clips = db.list_clips(project_id)
            ready = sum(1 for c in clips if c["status"] == "ready")
            msg = f"{ready} clip{'s' if ready != 1 else ''} ready" if clips else "No strong moments found"
            info = (db.get_project(project_id) or {}).get("info") or {}
            info.pop("resume_count", None)
            db.update_project(project_id, status="ready", progress=1.0, stage="done", message=msg, info=info)
        except Cancelled:
            db.update_project(project_id, status="cancelled", message="Cancelled")
        except Exception as exc:  # noqa: BLE001
            log.exception("project %s failed", project_id)
            db.update_project(project_id, status="error", error=str(exc)[:1000], message="Failed")
        finally:
            self.cancelled.discard(project_id)

    def _run_render(self, clip_id: str) -> None:
        ctx = JobContext(None, lambda: clip_id in self.cancelled)
        try:
            process.render_single(clip_id, ctx)
        except Cancelled:
            pass
        finally:
            clip = db.get_clip(clip_id) or {}
            info = dict(clip.get("render_info") or {})
            if info.pop("manual_render_pending", False):
                db.update_clip(clip_id, render_info=info)
            self.cancelled.discard(clip_id)

    def _run_version(self, version_id: str) -> None:
        ctx = JobContext(None, lambda: version_id in self.cancelled)
        try:
            process.render_version(version_id, ctx)
        except Cancelled:
            pass
        finally:
            self.cancelled.discard(version_id)

    def _download(self, project_id: str, url: str, ctx: JobContext) -> None:
        download_url(project_id, url, ctx)


class DownloadRefused(RuntimeError):
    """The video is over the size or length limit it was downloaded with; nothing was downloaded."""


def download_url(project_id: str, url: str, ctx: JobContext, max_bytes: int | None = None,
                 max_seconds: float | None = None) -> None:
    """Optional URL import via yt-dlp. Public media only: no cookies, logins or DRM circumvention.
    Autopilot passes size and length limits; a video over them is not downloaded (DownloadRefused)."""
    from . import config
    from .media_import import MediaUnavailable, public_extractor
    import os
    import shutil
    project = db.get_project(project_id)
    assert project
    pdir = Path(project["source_path"]).parent
    staging = pdir / "download"
    staging.mkdir(parents=True, exist_ok=True)
    db.update_project(project_id, stage="download", message="Downloading video")

    def hook(d: dict) -> None:
        if ctx.cancelled():
            raise Cancelled()
        if shutil.disk_usage(pdir).free < 2_000_000_000:
            raise DownloadRefused("The download stopped to keep 2 GB of free disk space")
        if d.get("status") == "downloading" and d.get("total_bytes"):
            db.update_project(project_id, progress=round(0.02 * d["downloaded_bytes"] / d["total_bytes"], 4),
                              message=f"Downloading {d.get('_percent_str', '').strip()}")

    ydl_opts = {
        "outtmpl": str(staging / "source.%(ext)s"),
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "allow_unplayable_formats": False,  # never touch DRM-protected formats
    }
    if max_bytes:
        ydl_opts["max_filesize"] = int(max_bytes)

    def one_video(info, *, incomplete=False):
        if info.get("_type") in ("playlist", "multi_video"):
            raise DownloadRefused("Use a link to one video, rather than a playlist or channel")
        if max_seconds and (info.get("duration") or 0) > max_seconds:
            raise DownloadRefused("The video exceeds the configured duration limit")
        return None

    ydl_opts["match_filter"] = one_video
    with public_extractor(ydl_opts, max_bytes=max_bytes or 8_000_000_000, cancelled=ctx.cancelled) as ydl:
        try:
            meta = ydl.extract_info(url, download=False)
            if not isinstance(meta, dict):
                raise DownloadRefused("No accessible video was found")
            one_video(meta)
            expected = sum(float(f.get("filesize") or f.get("filesize_approx") or 0)
                           for f in meta.get("requested_formats") or [meta])
            if max_bytes and expected > max_bytes:
                raise DownloadRefused("The video exceeds the configured size limit")
            if shutil.disk_usage(pdir).free < max(expected * 2, 0) + 2_000_000_000:
                raise DownloadRefused("Not enough free disk space to download and merge this video")
            meta = ydl.process_ie_result(meta, download=True)
            path = Path(ydl.prepare_filename(meta))
        except (Cancelled, DownloadRefused, MediaUnavailable):
            raise
        except Exception as exc:
            from . import netguard
            from .autopilot import queue

            if isinstance(exc, (netguard.UnsafeUrl, queue.Wait)):
                raise
            raise MediaUnavailable("This video could not be downloaded. The site may require a login, "
                                   "restrict downloads, or use an unsupported player.") from None
    if not path.exists():
        candidates = sorted(p for p in staging.glob("source.*") if p.suffix.lower() in config.VIDEO_EXTENSIONS
                            and p.name.count(".") == 1)
        if not candidates:
            if max_bytes or max_seconds:
                raise DownloadRefused(
                    f"Not downloaded: the video is larger than {(max_bytes or 0) / 1e9:.1f} GB or longer than "
                    f"{(max_seconds or 0) / 60:.0f} min (Autopilot limits)")
            raise RuntimeError("Download finished but no video file was found")
        path = candidates[0]
    destination = pdir / f"source{path.suffix.lower()}"
    os.replace(path, destination)
    path = destination
    name = (meta or {}).get("title") or project["name"]
    db.update_project(project_id, source_path=str(path), source_filename=path.name, name=name[:120])


worker = Worker()

"""Preview proxies, and the background preparation of a media file (studio job kind `asset_prepare`).

A proxy is a 640-pixel-wide H.264 copy of a big video (wider than 1280 pixels or longer than ten minutes), made
once into the asset's work folder (uploads.work_dir) and recorded in `assets.proxy_path`. Preview renders read it
instead of decoding the full original for every piece (engine.render); a final render always reads the original.
The setting `preview_proxies` (on by default) turns proxies off.

Preparing a file makes, in the background as soon as the file is added, what "Build my video" would otherwise do
first: the 16 kHz sound, the transcript (video_flow.transcript_words, cached in the work folder) and the proxy. The
build job still does whatever was not prepared. There is one prepare job per asset: asking again returns it.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from .. import db
from ..pipeline.common import Cancelled
from ..pipeline.ffmpeg_utils import extract_audio, run
from . import uploads
from .jobs import Canceled, Lease, enqueue, handler

log = logging.getLogger(__name__)
PROXY_WIDTH = 640
PROXY_FROM_WIDTH = 1280     # a video wider than this gets a proxy...
PROXY_FROM_SECONDS = 600.0  # ...and so does one longer than this
PROXY_NAME = "proxy.mp4"


def proxy_file(asset: dict) -> Path | None:
    """The asset's proxy, when it was made and is still on disk."""
    p = asset.get("proxy_path") or ""
    return Path(p) if p and Path(p).is_file() else None


def wants_proxy(asset: dict, settings: dict) -> bool:
    """Whether previews of this asset would read a proxy: a big video, proxies not switched off, none made yet."""
    if asset.get("kind") != "video" or not (settings or {}).get("preview_proxies", True):
        return False
    if proxy_file(asset) is not None:
        return False
    p = asset.get("probe") or {}
    return int(p.get("width") or 0) > PROXY_FROM_WIDTH or float(p.get("duration") or 0) > PROXY_FROM_SECONDS


def make_proxy(asset: dict, progress: Callable[[float], None] | None = None,
               cancel: Callable[[], bool] | None = None) -> Path:
    """Make the proxy (one full decode of the original) and record it on the asset; the one already there when it
    exists. 640 pixels wide with even dimensions, the source's frame rate, a keyframe every half second and no
    B-frames (so a preview piece can start anywhere), stereo AAC sound at 96 kb/s, or no sound when the source has
    none. Written to a temporary name first, so a half-made proxy is never used."""
    out = uploads.work_dir(asset) / PROXY_NAME
    if not (out.is_file() and out.stat().st_size > 0):
        p = asset.get("probe") or {}
        fps = float(p.get("fps") or 30)
        tmp = out.with_name("proxy.tmp.mp4")
        sound = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "96k", "-ac", "2"] if p.get("has_audio") else ["-an"]
        run(["-i", asset["path"], "-map", "0:v:0", *sound, "-vf", f"scale={PROXY_WIDTH}:-2", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-g", str(max(1, round(fps / 2))),
             "-bf", "0", "-movflags", "+faststart", str(tmp)],
            duration=float(p.get("duration") or 0), progress=progress, cancel=cancel)
        tmp.replace(out)
    if asset.get("proxy_path") != str(out):
        db.update("assets", asset["id"], proxy_path=str(out))
        asset["proxy_path"] = str(out)
    return out


@handler("asset_prepare")
def prepare_job(job: dict, lease: Lease) -> dict:
    """The sound, transcript and proxy of one asset, each skipped when it is already there. A proxy that cannot be
    made is reported in the result and never fails the job: previews then read the original."""
    asset = db.fetch("assets", job["target_id"])
    if not asset:
        raise ValueError("That file is no longer in your media.")
    if not Path(asset["path"]).is_file():
        raise ValueError(f"The original file {asset['filename']} is missing ({asset['path']}). Put it back where it "
                         "was, or add it again.")
    settings = db.get_settings()
    p = asset.get("probe") or {}
    name = asset.get("filename") or "the file"
    work = uploads.work_dir(asset)
    result: dict = {"transcript": False, "proxy": False}
    if asset["kind"] == "video" and p.get("has_audio"):
        wav = work / "audio.wav"
        if not wav.is_file():
            lease.progress(0.02, f"Reading the sound of {name}")
            extract_audio(Path(asset["path"]), wav, float(p.get("duration") or 0),
                          progress=lambda f: lease.progress(0.02 + 0.08 * f, f"Reading the sound of {name}"),
                          cancel=lease.canceled)
        lease.progress(0.1, f"Listening to {name}")
        from . import video_flow  # the whole editor; only this step needs it

        video_flow.transcript_words(asset, settings, lease)
        result["transcript"] = (work / "transcript.json").is_file()
    if wants_proxy(asset, settings):
        message = f"Making a small preview copy of {name}"
        lease.progress(0.6, message)
        try:
            make_proxy(asset, progress=lambda f: lease.progress(0.6 + 0.39 * f, message), cancel=lease.canceled)
        except (Canceled, Cancelled):
            raise
        except Exception as exc:  # noqa: BLE001 - previews read the original instead; the reason is kept
            log.warning("proxy of asset %s not made: %s", asset["id"], exc)
            result["proxy_error"] = (f"The small preview copy of {name} could not be made ({str(exc)[:200]}); "
                                     "previews read the original file.")
    result["proxy"] = proxy_file(asset) is not None
    lease.progress(1.0, "Ready")
    return result


def _job_fields(job: dict) -> dict:
    return {"status": job["status"], "progress": float(job.get("progress") or 0), "message": job.get("message") or "",
            "error": job.get("error") or ""}


def prepare(workspace_id: str, asset_id: str) -> dict:
    """Queue the preparation of an asset and return its job: {"job": id, "status", "progress", "message", "error"}.
    Asking again returns the same job (a prepared asset is not prepared twice; a failed one runs again)."""
    job = enqueue(workspace_id, "asset_prepare", asset_id, 0)
    return {"job": job["id"], **_job_fields(job)}


def status(asset: dict) -> dict:
    """What is prepared for an asset, and its newest prepare job (None when none was asked for):
    {"transcript": bool, "proxy": bool, "job": {"id", "status", "progress", "message", "error"} | None}."""
    rows = db.select("studio_jobs", "kind = 'asset_prepare' AND target_id = ?", (asset["id"],), "created_at DESC", 1)
    return {"transcript": (uploads.work_dir(asset) / "transcript.json").is_file(),
            "proxy": proxy_file(asset) is not None,
            "job": {"id": rows[0]["id"], **_job_fields(rows[0])} if rows else None}

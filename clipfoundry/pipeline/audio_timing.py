"""Check AAC's stored packet clock without FFmpeg silently reconstructing it from decoded samples."""
from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Callable

from .ffmpeg_utils import FFmpegError, ffprobe_bin, run_process


def inspect(path: str | Path, cancelled: Callable[[], bool] | None = None) -> dict:
    # Default ffprobe parsing repairs AAC timestamps. That hid a damaged MP4 stts table whose first
    # three seconds were squeezed into <1 s, followed by a long gap in the platform's transcode.
    result = run_process([ffprobe_bin(), "-v", "error", "-fflags", "+nofillin", "-select_streams", "a:0",
                          "-show_packets", "-show_streams", "-show_entries",
                          "stream=codec_name,profile,sample_rate,time_base:packet=pts,dts,duration",
                          "-of", "json", str(path)], timeout=60, cancel=cancelled)
    if result.returncode:
        raise FFmpegError("Could not read the stored audio timing. Render the clip again before uploading.")
    try:
        data = json.loads(result.stdout)
        streams = data["streams"]
        if not streams:
            return {"applicable": False, "reason": "No audio track"}
        stream = streams[0]
        if stream["codec_name"] != "aac" or stream.get("profile") != "LC":
            return {"applicable": False, "reason": "This check applies to AAC-LC renders"}
        rate = int(stream["sample_rate"])
        tick = float(Fraction(stream["time_base"]))
        if rate <= 0 or not math.isfinite(tick) or tick <= 0:
            raise ValueError("invalid audio clock")
        packets = data["packets"]
        if not packets or len(packets) >= 100000:
            raise ValueError("missing or excessive packet table")
        # ClipFoundry's AAC-LC encoder emits 1024 samples per packet. Only its final packet may be shorter.
        period, tolerance = 1024 / rate, max(tick, 1 / rate) * 1.1
        problems = 0
        first_bad = None
        previous = None
        largest_error = 0.0
        for i, packet in enumerate(packets):
            pts, dts, duration = (int(packet[key]) * tick for key in ("pts", "dts", "duration"))
            if not all(math.isfinite(v) for v in (pts, dts, duration)):
                raise ValueError("invalid packet timing")
            errors = [abs(pts - dts)]
            if previous is not None:
                errors.append(abs(pts - previous - period))
            if i < len(packets) - 1 or duration > period:
                errors.append(abs(duration - period))
            if duration <= 0:
                errors.append(period)
            error = max(errors)
            if error > tolerance:
                problems += 1
                if first_bad is None:
                    first_bad = i
                largest_error = max(largest_error, error)
            previous = pts
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise FFmpegError("Audio timing could not be verified. Render the clip again before uploading.") from exc
    return {"applicable": True, "valid": problems == 0, "packets": len(packets), "sample_rate": rate,
            "invalid_packets": problems, "first_invalid_packet": first_bad,
            "largest_clock_error_s": round(largest_error, 6)}


def require_valid(path: str | Path, cancelled: Callable[[], bool] | None = None) -> dict:
    result = inspect(path, cancelled)
    if not result.get("applicable") or not result.get("valid"):
        raise FFmpegError("The rendered audio timing is invalid and could cause glitches or silence after upload. "
                          "Render the clip again before uploading.")
    return result

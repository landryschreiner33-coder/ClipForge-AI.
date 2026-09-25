"""Thin wrappers around the ffmpeg / ffprobe executables."""
from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Sequence

from .. import config
from .common import Cancelled

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
EXE = ".exe" if sys.platform == "win32" else ""


class FFmpegError(RuntimeError):
    pass


def _candidate_dirs(explicit: str) -> list[Path]:
    dirs: list[Path] = []
    if explicit:
        p = Path(explicit)
        dirs.append(p.parent if p.is_file() else p)
        dirs.append(p / "bin")
    env = os.environ.get("CLIPFOUNDRY_FFMPEG")
    if env:
        p = Path(env)
        dirs.append(p.parent if p.is_file() else p)
    for rel in ("tools/ffmpeg/bin", "tools/ffmpeg", "ffmpeg/bin", "ffmpeg"):
        dirs.append(config.ROOT_DIR / rel)
    return dirs


def find_binary(name: str, explicit: str = "") -> str | None:
    for d in _candidate_dirs(explicit):
        exe = d / f"{name}{EXE}"
        if exe.is_file():
            return str(exe)
    return shutil.which(name)


def ffmpeg_bin() -> str:
    from .. import db

    exe = find_binary("ffmpeg", db.get_settings().get("ffmpeg_path", ""))
    if not exe:
        raise FFmpegError(
            "FFmpeg was not found. Install it (e.g. `winget install Gyan.FFmpeg`) or put ffmpeg.exe in tools/ffmpeg/bin."
        )
    return exe


def ffprobe_bin() -> str:
    from .. import db

    exe = find_binary("ffprobe", db.get_settings().get("ffmpeg_path", ""))
    if not exe:
        raise FFmpegError("ffprobe was not found next to ffmpeg. Install the full FFmpeg build.")
    return exe


def _drain(stream, sink: deque) -> None:
    for raw in iter(stream.readline, b""):
        sink.append(raw.decode("utf-8", "replace").rstrip())
    stream.close()


def run(
    args: Sequence[str],
    *,
    duration: float = 0.0,
    progress: Callable[[float], None] | None = None,
    cancel: Callable[[], bool] | None = None,
    cwd: str | Path | None = None,
) -> None:
    """Run ffmpeg with `-progress` parsing. `args` excludes the executable."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, creationflags=NO_WINDOW
    )
    tail: deque = deque(maxlen=40)
    t = threading.Thread(target=_drain, args=(proc.stderr, tail), daemon=True)
    t.start()
    assert proc.stdout is not None
    try:
        for raw in iter(proc.stdout.readline, b""):
            if cancel and cancel():
                proc.kill()
                raise Cancelled()
            line = raw.decode("ascii", "replace").strip()
            if progress and duration > 0 and line.startswith("out_time_us="):
                try:
                    progress(min(1.0, int(line.split("=", 1)[1]) / 1e6 / duration))
                except ValueError:
                    pass
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
        t.join(timeout=2)
    if proc.returncode != 0:
        raise FFmpegError("ffmpeg failed:\n" + "\n".join(list(tail)[-12:]))


def _parse_rate(rate: str | None) -> float:
    if not rate or rate in {"0/0", "N/A"}:
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            return float(num) / float(den) if float(den) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def probe(path: str | Path) -> dict:
    out = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        creationflags=NO_WINDOW,
    )
    if out.returncode != 0:
        raise FFmpegError(f"Could not read video file: {out.stderr.strip()[-400:]}")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams", [])
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise FFmpegError("The file has no video stream.")
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or video.get("duration") or 0.0)
    w, h = int(video.get("width") or 0), int(video.get("height") or 0)
    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(float(sd["rotation"]))
    if not rotation and video.get("tags", {}).get("rotate"):
        rotation = int(float(video["tags"]["rotate"]))
    if abs(rotation) % 180 == 90:
        w, h = h, w
    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate")) or 30.0
    if fps > 240 or fps < 1:
        fps = 30.0
    return {
        "duration": duration,
        "width": w,
        "height": h,
        "fps": round(fps, 3),
        "video_codec": video.get("codec_name", ""),
        "has_audio": audio is not None,
        "audio_codec": (audio or {}).get("codec_name", ""),
        "size_bytes": int(fmt.get("size") or 0),
    }


def extract_audio(src: Path, dst: Path, duration: float, progress=None, cancel=None) -> None:
    tmp = dst.with_suffix(".tmp.wav")
    run(
        ["-i", str(src), "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp)],
        duration=duration,
        progress=progress,
        cancel=cancel,
    )
    os.replace(tmp, dst)


def make_silent_wav(dst: Path, duration: float) -> None:
    run(["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", f"{max(duration, 0.1):.3f}",
         "-c:a", "pcm_s16le", str(dst)])


def thumbnail(src: Path, t: float, dst: Path, width: int = 480) -> None:
    run(["-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1",
         "-vf", f"scale={width}:-2", "-q:v", "3", str(dst)])


@functools.lru_cache(maxsize=4)
def _nvenc_works(exe: str) -> bool:
    try:
        r = subprocess.run(
            [exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=30, creationflags=NO_WINDOW,
        )
        return r.returncode == 0
    except Exception:
        return False


def nvenc_available() -> bool:
    try:
        return _nvenc_works(ffmpeg_bin())
    except FFmpegError:
        return False


def video_encoder_args(settings: dict) -> tuple[list[str], str]:
    choice = settings.get("encoder", "auto")
    crf = int(settings.get("crf", 20))
    if choice in {"auto", "nvenc"} and nvenc_available():
        return (["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(crf + 1), "-b:v", "0",
                 "-profile:v", "high", "-pix_fmt", "yuv420p"], "h264_nvenc")
    preset = settings.get("x264_preset", "veryfast")
    return (["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-profile:v", "high",
             "-pix_fmt", "yuv420p"], "libx264")


def filter_path(path: Path, cwd: Path) -> str:
    """Path usable inside a filtergraph option (ass=..., fontsdir=...).

    Prefers a path relative to `cwd` (no drive-letter colon to escape on Windows).
    """
    try:
        rel = os.path.relpath(path, cwd)
        p = rel.replace("\\", "/")
    except ValueError:  # different drive on Windows
        p = str(path).replace("\\", "/").replace(":", "\\:")
    return "'" + p.replace("'", "'\\''") + "'"

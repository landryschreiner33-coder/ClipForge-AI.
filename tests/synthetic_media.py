"""Small synthetic videos made with ffmpeg's generators (a second or two each), for fast tests of real renders and of
the final quality gate. A moving test pattern with a tone, optionally with black, silent or frozen stretches."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg and ffprobe are needed")


def make_video(path: Path, seconds: float = 8.0, size: str = "640x360", fps: int = 25,
               black: tuple[float, float] | None = None, silent: tuple[float, float] | None = None,
               frozen: bool = False, audio: bool = True, codec: str = "libx264") -> Path:
    """`black`/`silent`: (start, end) seconds painted black / muted. `frozen`: one still frame for the whole video."""
    src = f"color=c=gray:s={size}:r={fps}:d={seconds}" if frozen else f"testsrc2=s={size}:r={fps}:d={seconds}"
    vf = []
    if black:
        vf.append(f"drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='between(t,{black[0]},{black[1]})'")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", src]
    if audio:
        af = f"volume=enable='between(t,{silent[0]},{silent[1]})':volume=0" if silent else "anull"
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=330:sample_rate=48000:duration={seconds}", "-af", af]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-c:v", codec, "-pix_fmt", "yuv420p"]
    if codec == "libx264":
        cmd += ["-preset", "ultrafast"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "96k"]
    cmd += ["-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return path


def words_every(seconds: float, start: float = 0.2, step: float = 0.5, text: str = "this is a test clip") -> list[dict]:
    """Timed words (0.35 s each) repeating `text`, as the transcript of a synthetic video; sentences end every five
    words so sentence boundaries exist."""
    out, t, i = [], start, 0
    toks = text.split()
    while t + 0.35 < seconds:
        w = toks[i % len(toks)] + ("." if i % len(toks) == len(toks) - 1 else "")
        out.append({"w": w, "start": round(t, 3), "end": round(t + 0.35, 3)})
        t += step
        i += 1
    return out

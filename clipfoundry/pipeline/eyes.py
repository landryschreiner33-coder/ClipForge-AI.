"""ClipForge AI looks at the picture (docs/clipforge/SMARTER_AI.md).

The built-in model has a vision part that was downloaded with it and, until now, never used. For the strongest
finalists this module takes three small frames (a quarter, half and three quarters of the way through the clip), shows
them to the model in one request with the clip's first words, and asks what is on screen: the kind of footage
(talking head, screen recording, gameplay, slides...), how many people, any text on screen, which frame would make the
best thumbnail, a one-line description, and how much the picture would hold a viewer (1-10). The answer moves the
Clip Score by at most ±4 points, is shown with the clip ("ClipForge AI saw: ..."), and the chosen frame becomes the
clip's thumbnail. Everything stays on the computer. Without the built-in model (another provider, the setting off, a
video without a picture) nothing happens and the measured picture signals (faces, sharpness, motion) stand alone.
"""
from __future__ import annotations

import base64
import concurrent.futures
import json
import logging
import re
import subprocess
import time
from typing import Callable

from . import llm
from .common import JobContext
from .ffmpeg_utils import NO_WINDOW, ffmpeg_bin

log = logging.getLogger("clipfoundry.pipeline.eyes")

FRAME_W = 384
FRAMES = 3
WEIGHT = 4.0                 # the most the picture verdict can move a Clip Score
KINDS = ("talking_head", "interview", "vlog", "screen_recording", "gameplay", "slides", "b_roll", "other")
SYSTEM = ("You look at frames from a video clip and describe what is on screen for a video editor. Describe only what "
          "you can see; never guess what is said. Reply with one JSON object and nothing else.")
SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "people": {"type": "integer", "minimum": 0, "maximum": 20},
        "text_on_screen": {"type": "string", "maxLength": 120},
        "best_frame": {"type": "integer", "minimum": 1, "maximum": FRAMES},
        "appeal": {"type": "integer", "minimum": 1, "maximum": 10},
        "description": {"type": "string", "maxLength": 160},
        "problem": {"type": "string", "maxLength": 100}},
    "required": ["kind", "people", "text_on_screen", "best_frame", "appeal", "description", "problem"]}
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="eyes-ai")


def configured(opts: dict, meta: dict | None = None) -> bool:
    """The built-in model (the only provider with a vision part here) is in use, the eyes are on, and the source has a
    picture."""
    if opts.get("ai_provider") != "builtin" or not opts.get("ai_eyes", True):
        return False
    if meta is not None and (not meta.get("width") or not meta.get("has_video", True)):
        return False
    return True


def budget_s(opts: dict) -> float:
    return min(300.0, max(40.0, float(opts.get("ai_edit_timeout_s", 60)) * 5))


def frame(video: str, t: float, width: int = FRAME_W, timeout: float = 30.0) -> str | None:
    """One JPEG frame at `t` seconds as a base64 data URL (None when it cannot be read)."""
    cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}", "-i", video,
           "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "5", "pipe:1"]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("frame at %.1f s failed: %s", t, exc)
        return None
    if r.returncode != 0 or len(r.stdout) < 200:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(r.stdout).decode("ascii")


def frame_times(start: float, end: float, n: int = FRAMES) -> list[float]:
    dur = max(0.2, end - start)
    return [round(start + dur * (k + 1) / (n + 1), 3) for k in range(n)]


def prompt(first_words: str, n: int) -> str:
    return (f"These are {n} frames from one short clip, in time order"
            + (f'. The clip begins: "{first_words[:200]}"' if first_words else "")
            + ". Say what kind of footage this is (talking_head, interview, vlog, screen_recording, gameplay, slides, "
              "b_roll, other), how many people are visible, any readable text on screen (or \"\"), which frame (1-"
              f"{n}) would make the best thumbnail (a clear face or the most striking image), a one-line description "
              "of what is shown, how much the picture alone would hold a viewer scrolling past (appeal 1-10: 3 is a "
              "dull static shot, 7 a sharp close talking head, 9 striking), and any problem (dark, blurry, tiny face, "
              "nothing happening; or \"\").\n"
            'Answer: {"kind": "...", "people": 1, "text_on_screen": "...", "best_frame": 2, "appeal": 7, '
            '"description": "...", "problem": "..."}')


def _clean(text: object, limit: int) -> str:
    return " ".join(str(text or "").split()).strip("\"'“”. ")[:limit]


def look(video: str, start: float, end: float, first_words: str, opts: dict, ctx: JobContext | None, *,
         deadline: float | None = None, beat: Callable[[str], None] | None = None,
         complete: Callable[..., str] | None = None) -> dict | None:
    """What the model sees in the clip, or None (no frames, no answer in time, an unreadable answer)."""
    times = frame_times(start, end)
    urls = [u for u in (frame(video, t) for t in times) if u]
    if not urls:
        return None
    fn = complete or llm.complete
    timeout = min(120.0, max(20.0, float(opts.get("ai_edit_timeout_s", 60)) * 2))
    if deadline is not None:
        timeout = min(timeout, max(5.0, deadline - time.monotonic()))
    call = _pool.submit(fn, opts, prompt(first_words, len(urls)), task="eyes", system=SYSTEM, json_object=True,
                        json_schema=SCHEMA, timeout=timeout, max_tokens=300, images=urls)
    stop = time.monotonic() + timeout
    while True:
        try:
            raw = call.result(timeout=1.0)
            break
        except concurrent.futures.TimeoutError:
            if ctx:
                ctx.check()
            if beat:
                beat("ClipForge AI is looking at the picture")
            if time.monotonic() > stop:
                return None
        except llm.ProviderError as exc:
            log.warning("eyes: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001 - a bonus, never a blocker
            log.warning("eyes: %s", exc)
            return None
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return None
    try:
        appeal = max(1, min(10, int(data.get("appeal") or 5)))
        best = max(1, min(len(urls), int(data.get("best_frame") or 1)))
        people = max(0, min(20, int(data.get("people") or 0)))
    except (TypeError, ValueError):
        return None
    kind = data.get("kind") if data.get("kind") in KINDS else "other"
    return {"kind": kind, "people": people, "text_on_screen": _clean(data.get("text_on_screen"), 120),
            "description": _clean(data.get("description"), 160), "problem": _clean(data.get("problem"), 100),
            "appeal": appeal, "thumbnail_t": times[best - 1], "frames": len(urls),
            "adjust": round(max(-WEIGHT, min(WEIGHT, (appeal - 5) * 0.8)), 1), "provider": llm.provider_label(opts)}

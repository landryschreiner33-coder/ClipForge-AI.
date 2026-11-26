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
from pathlib import Path
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


def prompt(first_words: str, n: int, heard: str = "") -> str:
    return (f"These are {n} frames from one short clip, in time order"
            + (f'. The clip begins: "{first_words[:200]}"' if first_words else "")
            + (f". Heard during the clip: {heard[:200]}" if heard else "")
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
         complete: Callable[..., str] | None = None, times: list[float] | None = None,
         heard: str = "") -> dict | None:
    """What the model sees in the clip, or None (no frames, no answer in time, an unreadable answer). `times`: the
    frames to show (by default a quarter, half and three quarters of the way; the frame-by-frame watch passes the
    frames that differ most); `heard`: what was heard in the clip (laughter, applause...), as context."""
    times = sorted(times)[:FRAMES] if times else frame_times(start, end)
    urls = [u for u in (frame(video, t) for t in times) if u]
    if not urls:
        return None
    fn = complete or llm.complete
    timeout = min(120.0, max(20.0, float(opts.get("ai_edit_timeout_s", 60)) * 2))
    if deadline is not None:
        timeout = min(timeout, max(5.0, deadline - time.monotonic()))
    call = _pool.submit(fn, opts, prompt(first_words, len(urls), heard), task="eyes", system=SYSTEM, json_object=True,
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


# ------------------------------------------------------------------ watching the whole video (WATCH_AND_LISTEN.md)
DESCRIBE_VERSION = 1
DESCRIBE_FRAMES = 4
DESCRIBE_W = 320
TAGS = ("talking to camera", "conversation", "crowd", "close-up face", "laughing", "shocked or surprised", "crying",
        "angry or shouting", "fight", "fall or crash", "explosion or fire", "sports play", "celebration", "dancing",
        "game footage", "screen or slides", "text on screen", "animal", "food", "vehicle", "weapon", "outdoors",
        "dark", "nothing happens")
EXCITING_TAGS = ("laughing", "shocked or surprised", "angry or shouting", "fight", "fall or crash",
                 "explosion or fire", "sports play", "celebration", "dancing", "crying")
DESCRIBE_SYSTEM = ("You watch short stretches of a video for a video editor and say what happens in them. Describe "
                   "only what you can see in the frames; the words and sounds you are given are context, not "
                   "something to describe. Reply with one JSON object and nothing else.")
DESCRIBE_SCHEMA = {
    "type": "object",
    "properties": {
        "what": {"type": "string", "maxLength": 140},
        "tags": {"type": "array", "maxItems": 5, "items": {"type": "string", "enum": list(TAGS)}},
        "people": {"type": "integer", "minimum": 0, "maximum": 20},
        "action": {"type": "integer", "minimum": 0, "maximum": 10},
        "text_on_screen": {"type": "string", "maxLength": 80}},
    "required": ["what", "tags", "people", "action", "text_on_screen"]}


def describe_configured(opts: dict, meta: dict | None = None) -> bool:
    """The built-in model looks at the whole video: the same switch as the finalists' look (ai_eyes) plus the
    frame-by-frame watch (ai_watch)."""
    return configured(opts, meta) and bool(opts.get("ai_watch", True))


def describe_budget_s(opts: dict, duration: float) -> float:
    """How long the model may spend watching: 40% of the video's length, between 90 seconds and 10 minutes
    (Settings: ai_watch_budget_s, 0 = this rule). Parts already described are kept, so a second run adds to them."""
    own = float(opts.get("ai_watch_budget_s") or 0)
    return own if own > 0 else min(600.0, max(90.0, 0.4 * duration))


def _stamp(t: float) -> str:
    t = int(max(0.0, t))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def describe_prompt(start: float, end: float, n: int, said: str, heard: str) -> str:
    return (f"These are {n} frames from {_stamp(start)} to {_stamp(end)} of a video, in time order."
            + (f' Said here: "{said[:300]}".' if said else "")
            + (f" Heard here: {heard}." if heard else "")
            + " In one short sentence say what happens or what is shown (who does what, where). Then pick up to 5 "
              "tags from the list, count the people you can see, rate how much happens (action: 0 nothing moves, "
              "3 someone talking, 6 people moving or a lively scene, 9 something dramatic or funny happens), and "
              "copy any readable text on screen (or \"\").\n"
            'Answer: {"what": "...", "tags": ["..."], "people": 1, "action": 3, "text_on_screen": ""}')


def _read_answer(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    if not isinstance(data, dict) or not _clean(data.get("what"), 140):
        return None
    try:
        people = max(0, min(20, int(data.get("people") or 0)))
        action = max(0, min(10, int(data.get("action") or 0)))
    except (TypeError, ValueError):
        return None
    tags = [t for t in (data.get("tags") or []) if t in TAGS][:5] if isinstance(data.get("tags"), list) else []
    return {"what": _clean(data.get("what"), 140), "tags": tags, "people": people, "action": action,
            "text": _clean(data.get("text_on_screen"), 80)}


def describe_video(video: str, watched, opts: dict, ctx: JobContext | None, *, cache: Path | None = None,
                   said: Callable[[float, float], str] | None = None, heard: Callable[[float, float], str] | None = None,
                   priority: Callable[[float, float], float] | None = None, lo: float = 0.0, hi: float = 0.0,
                   complete: Callable[..., str] | None = None, budget: float | None = None) -> dict:
    """Show the built-in model every part of the video (watch.Watched.segments) and keep what it says happens in
    each, most promising parts first (`priority`), until the time budget is spent. A part that looks the same as
    the one before it (the same still talking head) takes that part's words instead of a new question. Returns
    {"parts": [{start, end, what, tags, people, action, text, same?}], "asked", "answered", "coverage",
    "problems", "provider"}; the parts are kept in `cache`, so the next run only asks about the rest."""
    from .common import read_json, write_json

    label = llm.provider_label(opts)
    segs = watched.segments() if watched is not None else []
    key = {"version": DESCRIBE_VERSION, "model": label, "segments": len(segs),
           "video": str(Path(video).stat().st_size) if video and Path(video).is_file() else ""}
    saved = read_json(cache, {}) if cache is not None else {}
    done: dict[str, dict] = {}
    if isinstance(saved, dict) and saved.get("key") == key:
        done = {p["id"]: p for p in saved.get("parts") or [] if isinstance(p, dict) and p.get("id")}
    notes = {"asked": 0, "answered": 0, "segments": len(segs), "problems": [], "provider": label, "coverage": 0.0,
             "kept": len(done)}
    if not segs:
        return {**notes, "parts": []}
    ids = [f"{s['start']:.2f}-{s['end']:.2f}" for s in segs]
    order = sorted(range(len(segs)), key=lambda i: -(priority(segs[i]["start"], segs[i]["end"]) if priority else 0.0)
                   - segs[i]["action"] * 0.5)
    fn = complete or llm.complete
    budget = describe_budget_s(opts, watched.duration) if budget is None else budget
    deadline = time.monotonic() + budget
    timeout = min(90.0, max(20.0, float(opts.get("ai_edit_timeout_s", 60)) * 1.5))

    def copy_before(i: int) -> bool:
        if i > 0 and segs[i]["same_as_before"] and ids[i - 1] in done and not done[ids[i - 1]].get("problem"):
            done[ids[i]] = {**done[ids[i - 1]], "id": ids[i], "start": segs[i]["start"], "end": segs[i]["end"],
                            "same": True}
            return True
        return False

    for step, i in enumerate(order):
        if ctx:
            ctx.check()
        if ids[i] in done or copy_before(i):
            continue
        if time.monotonic() > deadline:
            notes["problems"].append(f"Out of time after {notes['answered']} parts; the rest is measured only.")
            break
        s, e = segs[i]["start"], segs[i]["end"]
        times = watched.keyframes(s, e, DESCRIBE_FRAMES)
        urls = [u for u in (frame(video, t, DESCRIBE_W) for t in times) if u]
        if not urls:
            continue
        if ctx:
            ctx.progress(lo + (hi - lo) * min(1.0, step / max(1, len(order))),
                         f"ClipForge AI is watching part {step + 1} of {len(order)}")
        notes["asked"] += 1
        wait = max(5.0, min(timeout, deadline - time.monotonic() + 15.0))  # the last question may end a little late
        call = _pool.submit(fn, opts, describe_prompt(s, e, len(urls), said(s, e) if said else "",
                                                      heard(s, e) if heard else ""),
                            task="eyes", system=DESCRIBE_SYSTEM, json_object=True, json_schema=DESCRIBE_SCHEMA,
                            timeout=wait, max_tokens=160, images=urls)
        raw = None
        stop = time.monotonic() + wait
        while True:
            try:
                raw = call.result(timeout=1.0)
                break
            except concurrent.futures.TimeoutError:
                if ctx:
                    ctx.check()
                if time.monotonic() > stop:
                    notes["problems"].append(f"{_stamp(s)}: no answer within {wait:.0f} s.")
                    break
            except Exception as exc:  # noqa: BLE001 - a part left undescribed, never a failed job
                notes["problems"].append(f"{_stamp(s)}: {str(exc)[:160] or exc.__class__.__name__}")
                break
        got = _read_answer(raw or "") if raw else None
        if got is None:
            if raw is not None:
                notes["problems"].append(f"{_stamp(s)}: the answer was not readable.")
            if len(notes["problems"]) >= 6 and notes["answered"] == 0:
                notes["problems"].append("Stopped: the model did not describe the first parts.")
                break
            continue
        notes["answered"] += 1
        done[ids[i]] = {"id": ids[i], "start": s, "end": e, **got, "frames": len(urls)}
    for i in range(len(segs)):  # parts that look like the one before take its words (in time order)
        if ids[i] not in done:
            copy_before(i)
    parts = sorted(done.values(), key=lambda p: p["start"])
    notes["coverage"] = round(sum(p["end"] - p["start"] for p in parts) / max(0.1, watched.duration), 3)
    if cache is not None:
        try:
            write_json(cache, {"key": key, "parts": parts})
        except OSError as exc:
            log.warning("eyes: could not keep what was seen: %s", exc)
    return {**notes, "parts": parts}


def answer_about(video: str, times: list[float], question: str, opts: dict, *, context: str = "",
                 complete: Callable[..., str] | None = None, timeout: float = 60.0) -> str | None:
    """The built-in model looks at frames at `times` and answers a question about them in a few sentences (the chat's
    `watch` tool). None without the model or frames."""
    if opts.get("ai_provider") != "builtin":
        return None
    urls = [u for u in (frame(video, t, FRAME_W) for t in times[:6]) if u]
    if not urls:
        return None
    prompt_text = (f"These are {len(urls)} frames from a video, in time order ("
                   + ", ".join(_stamp(t) for t in times[:len(urls)]) + ")."
                   + (f" {context[:600]}" if context else "")
                   + f"\nQuestion: {question[:400]}\nAnswer in at most three short sentences, only from what you can "
                     "see (say so when the frames do not show it).")
    try:
        raw = (complete or llm.complete)(opts, prompt_text, task="eyes", system=(
            "You look at frames from a video and answer questions about what is on screen. Describe only what you "
            "can see."), timeout=timeout, max_tokens=200, images=urls)
    except Exception as exc:  # noqa: BLE001
        log.warning("eyes: %s", exc)
        return None
    text = " ".join(str(raw or "").split()).strip()
    return text[:700] or None

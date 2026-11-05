"""The full-video engine adapter, version ffmpeg-v2 (docs/clipforge/EDITOR_INTEGRATION.md).

An edit plan is engine-independent JSON with integer-millisecond times (timebase 1000). This adapter declares what it
supports, validates a plan against it (anything else is reported before rendering, never silently dropped), builds
the exact output time map, and renders from the full originals on the server. A preview is the same plan at a small
size and a fast preset, so preview and export follow one code path.

Scale: a render never opens every file at once. The sequence is cut into pieces (the body of each element and the
short join between two neighbours), each made by its own FFmpeg process with at most two inputs, encoded once and
cached by content, then joined by stream copy. Audio is rendered per element and per track item to raw samples and
mixed block by block (bounded memory) into three buses: speech (sound from your videos and voiceovers), music and
effects that duck under speech, and music and effects that do not. The number of files, sequence items and audio
items is not capped; free disk space is checked before work starts and the real limit is explained.

Every element's length is counted in whole output frames against the ideal timeline (no drift accumulates), and the
audio of each element has exactly that many frames' worth of samples, so picture and sound stay in sync however many
pieces a video has.

Audio follows the clip renderer's rules: each input clock is rebuilt first (aresample async, first_pts=0), the whole
edited mix is measured once for one constant normalization gain (no startup pumping), a peak limiter without
auto-level runs last, and the final sample clock is rebuilt from the actual output samples (asetpts=N/SR/TB).

Ducking is measured, not guessed: the speech bus is read in 10 ms frames, speech is wherever a frame is within 20 dB
of the speech's own typical level (so a quiet recording ducks as much as a loud one), and the music and effects that
duck are lowered by the plan's depth (default 12 dB) with a short attack, a hold between words and a slow release.
Speech itself is never compressed. (Before 2026-11-05 a fixed sidechain compressor did this; it dipped music by about
6 dB under loud speech and not at all under speech at a normal recording level.)

Smart editing (studio/smart_edit.py) adds three plan features:
* a clip's `join: "cut"` makes the join into it a straight cut whatever the plan's transition, so the jump cuts inside
  one recording stay cuts while the joins between recordings dissolve;
* a clip's `zoom` (1.0 to 1.5) punches in on the centre of the picture, which hides a jump cut;
* `overlays`: images (or muted footage) shown over a clip while its sound keeps playing (B-roll). Each overlay is
  attached to a clip at an offset, stays inside that clip's own part of the picture (never over a transition), can
  push in slowly ("zoom") and fades in and out. A render cuts the clip's body at the overlay's edges, so an overlay is
  always exactly one cached piece with one extra input.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
from pathlib import Path
from typing import Callable

from .. import config
from ..pipeline import audio_timing
from ..pipeline.captions import STYLE_PRESETS, chunk_words, hex_to_ass
from ..pipeline.common import Cancelled
from ..pipeline.ffmpeg_utils import FFmpegError, ffmpeg_bin, filter_path, probe, run, run_process

ENGINE = "ffmpeg-v2"
SCHEMA = 2
ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}
FPS = (24, 25, 30, 50, 60)  # each divides 48000, so a frame always holds a whole number of samples
SR = 48000
PREVIEW_HEIGHT = 360
TRANSITIONS = {"cut": None, "dissolve": "fade", "fade": "fadeblack"}
LAYOUTS = ("fit", "fill")
ROLES = ("voiceover", "music", "effect")
TRACKS = {"source": "Sound from your videos", "voiceover": "Voiceover", "music": "Music", "effects": "Sound effects"}
ROLE_TRACK = {"voiceover": "voiceover", "music": "music", "effect": "effects"}
CAPTION_SIZES = {"small": 0.8, "medium": 1.0, "large": 1.25}
# (ASS alignment, bottom/top margin as a share of the height); "raised" clears a player's bottom controls
CAPTION_POSITIONS = {"bottom": (2, 0.08), "raised": (2, 0.2), "middle": (5, 0.0), "top": (8, 0.08)}
GAIN_RANGE = (-36.0, 12.0)
DUCK_DEPTH_DB = 12.0          # how far ducking music/effects dip under speech
DUCK_RANGE = (0.0, 30.0)
DUCK_FRAME = 480              # 10 ms analysis frames
DUCK_ATTACK_S, DUCK_HOLD_S, DUCK_RELEASE_S = 0.06, 0.25, 0.45
SUPPORTED = {"clips", "trim", "reorder", "include", "image", "transition", "title", "captions", "audio_tracks",
             "voiceover", "music", "effects", "gain", "mute", "fades", "ducking", "aspect", "layout", "insert",
             "replace", "split", "word_fixes", "joins", "zoom", "overlays"}
ZOOM_RANGE = (1.0, 1.5)       # a clip's punch-in
OVERLAY_KINDS = ("image", "video")
OVERLAY_MOTIONS = ("still", "zoom")
OVERLAY_FITS = ("fill", "fit")
OVERLAY_MIN_MS = 500
OVERLAY_PUSH = 0.08           # how far a "zoom" overlay pushes in over its whole length
OVERLAY_FADE_S = 0.2
UNSUPPORTED = {"color_grade": "colour grading", "keyframes": "keyframed motion", "pip": "picture in picture",
               "speed": "speed changes", "effects_plugins": "effects plugins", "multicam": "multicam"}
MIX_BLOCK = SR * 10  # samples per mixing block (bounded memory whatever the length)


class RenderSpaceError(ValueError):
    """Not enough free disk space to render; nothing was started."""


def capabilities() -> dict:
    return {"engine": ENGINE, "schema": SCHEMA, "supported": sorted(SUPPORTED), "aspects": list(ASPECTS),
            "fps": list(FPS), "transitions": list(TRANSITIONS), "layouts": list(LAYOUTS), "roles": list(ROLES),
            "tracks": TRACKS, "caption_sizes": list(CAPTION_SIZES), "caption_positions": list(CAPTION_POSITIONS),
            "gain_range_db": list(GAIN_RANGE), "duck_depth_db": {"default": DUCK_DEPTH_DB, "range": list(DUCK_RANGE)},
            "zoom_range": list(ZOOM_RANGE), "overlays": {"kinds": list(OVERLAY_KINDS), "motions": list(OVERLAY_MOTIONS),
                                                         "min_ms": OVERLAY_MIN_MS},
            "unsupported": UNSUPPORTED,
            "limits": "No fixed number of files, clips or audio items. Free disk space is checked before a "
                      "render; each step opens at most two media files.",
            "notes": "Renders from the full original files on the server; previews use the same plan at 360p."}


def default_tracks() -> dict:
    return {t: {"gain_db": 0.0, "mute": False} for t in TRACKS}


def upgrade(plan: dict | None) -> dict | None:
    """A saved plan in the current schema. Schema-1 plans (one optional music bed) become a music item on the music
    track with the same level and looping that ducks under speech (with the measured ducking described above)."""
    if not plan or plan.get("schema") != 1:
        return plan
    p = copy.deepcopy(plan)
    music = p.pop("music", None) or {}
    p["audio"] = []
    if music.get("asset_id"):
        p["audio"].append({"id": "a1", "asset_id": music["asset_id"], "role": "music", "label": "Music",
                           "start_ms": 0, "in_ms": 0, "out_ms": None, "length_ms": None,
                           "gain_db": float(music.get("level_db", -18)), "mute": False, "fade_in_ms": 0,
                           "fade_out_ms": 0, "duck": True, "loop": True, "anchor": None})
    p["tracks"] = default_tracks()
    p.setdefault("word_fixes", {})
    p.setdefault("ducking", {"depth_db": DUCK_DEPTH_DB})
    p["schema"], p["engine"] = SCHEMA, ENGINE
    return p


def _dur(c: dict) -> int:
    return int(c["out_ms"]) - int(c["in_ms"])


def _length(a: dict) -> int:
    return int(float((a.get("probe") or {}).get("duration") or 0) * 1000)


def _gain_ok(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and GAIN_RANGE[0] <= v <= GAIN_RANGE[1]


def item_length(item: dict) -> int | None:
    """How long an audio item plays (ms); None for a loop that runs to the end of the video."""
    if item.get("loop"):
        return None if item.get("length_ms") is None else int(item["length_ms"])
    return int(item["out_ms"]) - int(item.get("in_ms") or 0) if item.get("out_ms") is not None else None


def _validate_audio(plan: dict, assets: dict[str, dict]) -> list[str]:
    out = []
    depth = (plan.get("ducking") or {}).get("depth_db", DUCK_DEPTH_DB)
    if isinstance(depth, bool) or not isinstance(depth, (int, float)) or not DUCK_RANGE[0] <= depth <= DUCK_RANGE[1]:
        out.append(f"Ducking must be between {DUCK_RANGE[0]:g} and {DUCK_RANGE[1]:g} dB.")
    tracks = plan.get("tracks") or {}
    for name, track in tracks.items():
        if name not in TRACKS:
            out.append(f"Unknown audio track “{name}”.")
        elif not _gain_ok(float(track.get("gain_db") or 0)):
            out.append(f"The {TRACKS[name].lower()} track volume is out of range.")
    clip_ids = {c.get("id") for c in plan.get("clips") or []}
    seen: set = set()
    for item in plan.get("audio") or []:
        name = item.get("label") or "An audio item"
        if item.get("id") in seen:
            out.append("Two audio items share one ID.")
        seen.add(item.get("id"))
        a = assets.get(item.get("asset_id"))
        if not a:
            out.append(f"“{name}” refers to a file that is missing.")
            continue
        if a["kind"] != "audio":
            out.append(f"“{a['filename']}” is not an audio file.")
        elif not Path(a["path"]).is_file():
            out.append(f"The original file “{a['filename']}” is missing on the server. Upload it again.")
        if item.get("role") not in ROLES:
            out.append(f"“{name}” needs a track: voiceover, music or effect.")
        if not _gain_ok(float(item.get("gain_db") or 0)):
            out.append(f"The volume of “{name}” is out of range.")
        anchor = item.get("anchor")
        if anchor and anchor.get("clip_id") not in clip_ids:
            out.append(f"“{name}” is attached to a clip that is not in this video.")
        if not anchor and int(item.get("start_ms") or 0) < 0:
            out.append(f"“{name}” starts before the video.")
        if item.get("loop"):
            if item.get("length_ms") is not None and int(item["length_ms"]) < 100:
                out.append(f"“{name}” is shorter than 0.1 s.")
        else:
            a_in, a_out = int(item.get("in_ms") or 0), item.get("out_ms")
            if a_out is None or a_in < 0 or int(a_out) - a_in < 100 or (_length(a) and int(a_out) > _length(a) + 50):
                out.append(f"“{name}” is trimmed outside its file.")
        length = item_length(item) if item.get("loop") or item.get("out_ms") is not None else None
        fades = int(item.get("fade_in_ms") or 0), int(item.get("fade_out_ms") or 0)
        if min(fades) < 0 or (length is not None and sum(fades) > length):
            out.append(f"The fades of “{name}” are longer than the sound.")
    return out


def validate(plan: dict, assets: dict[str, dict]) -> list[str]:
    """Problems that stop a render (unsupported operations are listed, never dropped)."""
    plan = upgrade(plan) or {}
    out = []
    if plan.get("schema") != SCHEMA or plan.get("timebase") != 1000:
        out.append("This plan was made for another editor version.")
    for key, label in UNSUPPORTED.items():
        if plan.get(key):
            out.append(f"{label.capitalize()} is not supported by this editor yet.")
    if (plan.get("output") or {}).get("aspect") not in ASPECTS:
        out.append("Choose 16:9, 9:16, 1:1 or 4:5.")
    if int((plan.get("output") or {}).get("fps") or 30) not in FPS:
        out.append("Choose 24, 25, 30, 50 or 60 frames per second.")
    if plan.get("layout", "fit") not in LAYOUTS:
        out.append("Unknown framing.")
    clips = [c for c in plan.get("clips") or [] if c.get("include", True)]
    if not clips:
        out.append("Every clip is removed; keep at least one.")
    ids = [c.get("id") for c in plan.get("clips") or []]
    if len(set(ids)) != len(ids):
        out.append("Two clips share one ID.")
    for c in clips:
        name = c.get("label", "?")
        a = assets.get(c.get("asset_id"))
        if not a:
            out.append(f"Clip “{name}” refers to a file that is missing.")
            continue
        if a["kind"] not in ("video", "image"):
            out.append(f"“{a['filename']}” is not a video or image.")
        if not Path(a["path"]).is_file():
            out.append(f"The original file “{a['filename']}” is missing on the server. Upload it again.")
        if _dur(c) < 200:
            out.append(f"Clip “{name}” is shorter than 0.2 s.")
        if a["kind"] == "video":
            length = _length(a)
            if c["in_ms"] < 0 or (length and c["out_ms"] > length + 50):
                out.append(f"Clip “{name}” is trimmed outside its file.")
        if c.get("layout") not in (None, *LAYOUTS):
            out.append(f"Clip “{name}” has an unknown framing.")
        fades = int(c.get("fade_in_ms") or 0), int(c.get("fade_out_ms") or 0)
        if min(fades) < 0 or sum(fades) > _dur(c):
            out.append(f"The sound fades of “{name}” are longer than the clip.")
        if not _gain_ok(float(c.get("gain_db") or 0)):
            out.append(f"The volume of “{name}” is outside {GAIN_RANGE[0]:.0f} to +{GAIN_RANGE[1]:.0f} dB.")
        zoom = c.get("zoom", 1.0)
        if isinstance(zoom, bool) or not isinstance(zoom, (int, float)) or not ZOOM_RANGE[0] <= zoom <= ZOOM_RANGE[1]:
            out.append(f"The zoom of “{name}” must be between {ZOOM_RANGE[0]:g} and {ZOOM_RANGE[1]:g}.")
        if c.get("join") not in (None, "cut"):
            out.append(f"Clip “{name}” has an unknown join.")
    t = (plan.get("transition") or {})
    if t.get("type", "cut") not in TRANSITIONS:
        out.append("Unknown transition.")
    elif t.get("type", "cut") != "cut" and clips:
        joins = _joins(plan)
        sides = [c for c in clips if any(joins[c["id"]])]  # clips that take part in a transition
        too_long = bool(sides) and int(t.get("ms") or 0) * 2 >= min(_dur(c) for c in sides)
        if not too_long and int((plan.get("output") or {}).get("fps") or 30) in FPS:
            els, _overlap = frame_map(plan, int((plan.get("output") or {}).get("fps") or 30))
            too_long = any(e["frames"] < e["ov_in"] + (els[k + 1]["ov_in"] if k + 1 < len(els) else 0)
                           for k, e in enumerate(els))
        if too_long:
            out.append("A transition is longer than half of the shortest clip; shorten it.")
    captions = plan.get("captions") or {}
    if captions.get("size", "medium") not in CAPTION_SIZES:
        out.append("Unknown caption size.")
    if captions.get("position", "bottom") not in CAPTION_POSITIONS:
        out.append("Unknown caption position.")
    return out + _validate_audio(plan, assets) + _validate_overlays(plan, assets)


def _validate_overlays(plan: dict, assets: dict[str, dict]) -> list[str]:
    out = []
    clip_ids = {c.get("id") for c in plan.get("clips") or []}
    seen: set = set()
    for o in plan.get("overlays") or []:
        name = o.get("label") or "A picture over the video"
        if o.get("id") in seen:
            out.append("Two pictures over the video share one ID.")
        seen.add(o.get("id"))
        a = assets.get(o.get("asset_id"))
        if not a:
            out.append(f"“{name}” refers to a file that is missing.")
            continue
        if a["kind"] not in OVERLAY_KINDS:
            out.append(f"“{a['filename']}” is not an image or video, so it cannot be shown over the video.")
        elif not Path(a["path"]).is_file():
            out.append(f"The original file “{a['filename']}” is missing on the server. Upload it again.")
        if o.get("clip_id") not in clip_ids:
            out.append(f"“{name}” is attached to a clip that is not in this video.")
        offset, length = o.get("offset_ms"), o.get("length_ms")
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or offset < 0:
            out.append(f"“{name}” starts before its clip.")
        if isinstance(length, bool) or not isinstance(length, (int, float)) or length < OVERLAY_MIN_MS:
            out.append(f"“{name}” must be shown for at least {OVERLAY_MIN_MS / 1000:g} s.")
        if o.get("motion", "still") not in OVERLAY_MOTIONS:
            out.append(f"“{name}” has an unknown motion.")
        if o.get("fit") not in (None, *OVERLAY_FITS):
            out.append(f"“{name}” has an unknown framing.")
        if a["kind"] == "video":
            src_in = int(o.get("in_ms") or 0)
            if src_in < 0 or (_length(a) and src_in + int(length or 0) > _length(a) + 50):
                out.append(f"“{name}” is trimmed outside its file.")
    return out


def _joins(plan: dict) -> dict[str, tuple[int, int]]:
    """For each included clip, how many ms it shares with the element before and after it (a transition overlap;
    0 at a straight cut, at a clip whose join is "cut", and at the ends of the video)."""
    t = plan.get("transition") or {}
    overlap = int(t.get("ms") or 0) if t.get("type", "cut") != "cut" else 0
    inc = [c for c in plan.get("clips") or [] if c.get("include", True)]
    title = _has_title(plan)
    out = {}
    for k, c in enumerate(inc):
        ov_in = 0 if (k == 0 and not title) or c.get("join") == "cut" else overlap
        nxt = inc[k + 1] if k + 1 < len(inc) else None
        ov_out = 0 if nxt is None or nxt.get("join") == "cut" else overlap
        out[c["id"]] = (ov_in, ov_out)
    return out


def _has_title(plan: dict) -> bool:
    title = plan.get("title") or {}
    return bool(title.get("enabled") and title.get("text"))


def timeline(plan: dict) -> list[dict]:
    """The output time map: every included clip's source range and where it plays, in integer milliseconds.
    A transition overlaps each pair of neighbours (the title card counts as the first element), so every later
    element starts earlier by the transition length, exactly as the pieces are joined."""
    joins = _joins(plan)
    pos = int((plan.get("title") or {}).get("ms") or 0) if _has_title(plan) else 0
    out = []
    for c in (c for c in plan.get("clips") or [] if c.get("include", True)):
        start = pos - joins[c["id"]][0]
        out.append({"clip_id": c["id"], "asset_id": c["asset_id"], "kind": c.get("kind", "video"),
                    "src_in_ms": int(c["in_ms"]), "src_out_ms": int(c["out_ms"]), "out_start_ms": start,
                    "out_end_ms": start + _dur(c)})
        pos = start + _dur(c)
    return out


def duration_ms(plan: dict) -> int:
    tl = timeline(plan)
    return tl[-1]["out_end_ms"] if tl else 0


def frame_map(plan: dict, fps: int) -> tuple[list[dict], int]:
    """(elements in output order with whole-frame positions, transition overlap in frames). Each element ends on the
    frame nearest its ideal end, so rounding never accumulates; the next one starts `overlap` frames earlier."""
    t = plan.get("transition") or {}
    overlap_ms = int(t.get("ms") or 0) if t.get("type", "cut") != "cut" else 0
    overlap = round(overlap_ms * fps / 1000)
    els: list[dict] = []
    if _has_title(plan):
        els.append({"kind": "title", "clip_id": "", "asset_id": "", "src_in_ms": 0,
                    "ideal_end_ms": int(plan["title"]["ms"])})
    clips = {c["id"]: c for c in plan.get("clips") or []}
    for seg in timeline(plan):
        els.append({**seg, "clip": clips[seg["clip_id"]], "ideal_end_ms": seg["out_end_ms"]})
    end = 0
    for k, e in enumerate(els):
        ov = 0 if k == 0 or (e.get("clip") or {}).get("join") == "cut" else overlap
        start = 0 if k == 0 else end - ov
        end = max(start + 1, round(e["ideal_end_ms"] * fps / 1000))
        e.update(start_f=start, end_f=end, frames=end - start, ov_in=ov)
    return els, (overlap if len(els) > 1 else 0)


def render_timeline(plan: dict, fps: int) -> list[dict]:
    """The time map of the rendered file: like timeline(), on whole output frames."""
    els, _ = frame_map(plan, fps)
    return [{"clip_id": e["clip_id"], "asset_id": e["asset_id"], "kind": e["kind"], "src_in_ms": e["src_in_ms"],
             "src_out_ms": e["src_in_ms"] + round(e["frames"] * 1000 / fps),
             "out_start_ms": round(e["start_f"] * 1000 / fps), "out_end_ms": round(e["end_f"] * 1000 / fps)}
            for e in els if e["kind"] != "title"]


def audio_timeline(plan: dict, segs: list[dict] | None = None, total_ms: int | None = None) -> list[dict]:
    """Where each audio item plays in the output (ms). An item attached to a clip follows that clip; an item whose
    clip is removed is silent; anything past the end of the video is cut (and reported in `cut_ms`)."""
    segs = timeline(plan) if segs is None else segs
    total = duration_ms(plan) if total_ms is None else total_ms
    starts = {s["clip_id"]: s["out_start_ms"] for s in segs}
    out = []
    for item in plan.get("audio") or []:
        if item.get("mute"):
            continue
        anchor = item.get("anchor")
        if anchor:
            if anchor.get("clip_id") not in starts:
                continue
            start = starts[anchor["clip_id"]] + int(anchor.get("offset_ms") or 0)
        else:
            start = int(item.get("start_ms") or 0)
        start = max(0, start)
        length = item_length(item)
        length = total - start if length is None else length
        end = min(total, start + length)
        if end - start < 20:
            continue
        out.append({"audio_id": item["id"], "asset_id": item["asset_id"], "role": item["role"],
                    "track": ROLE_TRACK[item["role"]], "out_start_ms": start, "out_end_ms": end,
                    "src_in_ms": 0 if item.get("loop") else int(item.get("in_ms") or 0),
                    "loop": bool(item.get("loop")), "cut_ms": start + length - end})
    return out


def overlay_timeline(plan: dict, segs: list[dict] | None = None) -> list[dict]:
    """Where each picture over the video shows (ms): inside its clip's own part of the picture (never over a
    transition), a later overlay on the same clip starting after the earlier one ends. A removed clip hides its
    overlays."""
    segs = timeline(plan) if segs is None else segs
    by = {s["clip_id"]: s for s in segs}
    joins = _joins(plan)
    out: list[dict] = []
    last_end: dict[str, int] = {}
    items = sorted((o for o in plan.get("overlays") or [] if o.get("clip_id") in by and not o.get("hide")),
                   key=lambda o: (o["clip_id"], int(o.get("offset_ms") or 0)))
    for o in items:
        s = by[o["clip_id"]]
        ov_in, ov_out = joins.get(o["clip_id"], (0, 0))
        lo, hi = s["out_start_ms"] + ov_in, s["out_end_ms"] - ov_out
        start = max(lo, s["out_start_ms"] + int(o.get("offset_ms") or 0), last_end.get(o["clip_id"], lo))
        end = min(hi, start + int(o.get("length_ms") or 0))
        if end - start < 300:
            continue
        last_end[o["clip_id"]] = end
        out.append({"overlay_id": o["id"], "asset_id": o["asset_id"], "clip_id": o["clip_id"], "out_start_ms": start,
                    "out_end_ms": end})
    return sorted(out, key=lambda x: x["out_start_ms"])


def _overlay_frames(plan: dict, els: list[dict], fps: int, assets: dict[str, dict]) -> dict[int, list[dict]]:
    """The overlays of each element in whole output frames, inside the element's body (as overlay_timeline)."""
    index = {e["clip_id"]: k for k, e in enumerate(els) if e["kind"] != "title"}
    out: dict[int, list[dict]] = {}
    last_end: dict[int, int] = {}
    items = sorted((o for o in plan.get("overlays") or [] if o.get("clip_id") in index and not o.get("hide")),
                   key=lambda o: (index[o["clip_id"]], int(o.get("offset_ms") or 0)))
    for o in items:
        k = index[o["clip_id"]]
        e = els[k]
        b0 = e["start_f"] + e["ov_in"]
        b1 = e["end_f"] - (els[k + 1]["ov_in"] if k + 1 < len(els) else 0)
        start = max(b0, e["start_f"] + round(int(o.get("offset_ms") or 0) * fps / 1000), last_end.get(k, b0))
        end = min(b1, start + round(int(o.get("length_ms") or 0) * fps / 1000))
        if end - start < max(1, round(0.3 * fps)):
            continue
        last_end[k] = end
        a = assets[o["asset_id"]]
        probe_ = a.get("probe") or {}
        fit = o.get("fit")
        if fit not in OVERLAY_FITS:  # automatic: fill unless the picture's shape is far from the frame's
            w, h = probe_.get("width") or 0, probe_.get("height") or 0
            fit = "fill"
            if w and h:
                ow, oh = ASPECTS[plan["output"]["aspect"]]
                fit = "fit" if abs(math.log((w / h) / (ow / oh))) > 0.35 else "fill"
        out.setdefault(k, []).append({"id": o["id"], "kind": a["kind"], "path": a["path"], "sha": a.get("sha256", ""),
                                      "start_f": start, "end_f": end, "fit": fit,
                                      "motion": o.get("motion", "still") if a["kind"] == "image" else "still",
                                      "src_in_ms": int(o.get("in_ms") or 0)})
    return out


def output_words(plan: dict, words_by_asset: dict[str, list[dict]], segs: list[dict] | None = None) -> list[dict]:
    """The words heard in the output, on the output timeline (seconds), through the time map. A word you corrected
    (plan `word_fixes`) shows your text; its timing stays the measured one.

    A word counts for a clip when it starts inside it and most of its measured time is inside: speech models often
    let a word's end run on into the silence after it, and a cut made in that silence must not drop the word from
    the captions (its shown end is then the clip's end)."""
    fixes = plan.get("word_fixes") or {}
    out = []
    for seg in timeline(plan) if segs is None else segs:
        a, b = seg["src_in_ms"] / 1000, seg["src_out_ms"] / 1000
        shift = seg["out_start_ms"] / 1000 - a
        mine = fixes.get(seg["asset_id"]) or {}
        for w in words_by_asset.get(seg["asset_id"]) or []:
            if not (a - 0.01 <= w["start"] < b):
                continue
            end = w["end"]
            if end > b + 0.01:
                if b - w["start"] < 0.5 * (end - w["start"]):
                    continue  # mostly cut away
                end = b
            text = mine.get(str(int(round(w["start"] * 1000))), w["w"])
            if not text.strip():
                continue  # a word you deleted from the captions
            out.append({"w": text, "start": round(w["start"] + shift, 3), "end": round(end + shift, 3),
                        "clip_id": seg["clip_id"], "src_start": w["start"], "src_end": w["end"]})
    return out


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_header(captions: dict, width: int, height: int) -> str:
    style = captions.get("style") or "clean"
    p = STYLE_PRESETS.get(style, STYLE_PRESETS["clean"])
    scale = min(width, height) / 1080
    size = max(14, int(p["size"] * scale * (0.72 if width > height else 1.0)
                       * CAPTION_SIZES.get(captions.get("size") or "medium", 1.0)))
    align, share = CAPTION_POSITIONS.get(captions.get("position") or "bottom", CAPTION_POSITIONS["bottom"])
    margin = int(height * share)
    bold = -1 if style in ("bold", "high_energy") else 0
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{p['font']},{size},{hex_to_ass('#FFFFFF')},{hex_to_ass('#FFFFFF')},&H00000000,&H64000000,"
        f"{bold},0,0,0,100,100,0,0,1,{max(2, int(4 * scale))},1,{align},60,60,{margin},1", "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]) + "\n"


def caption_events(words: list[dict], captions: dict) -> list[tuple[float, float, str]]:
    style = captions.get("style") or "clean"
    p = STYLE_PRESETS.get(style, STYLE_PRESETS["clean"])
    out = []
    for chunk in chunk_words(words, style):
        text = " ".join(w["w"].strip() for w in chunk).replace("{", "(").replace("}", ")").replace("\\", "/")
        out.append((chunk[0]["start"], chunk[-1]["end"] + 0.15, text.upper() if p.get("upper") else text))
    return out


def captions_ass(words: list[dict], captions: dict, width: int, height: int,
                 window: tuple[float, float] | None = None, events: list | None = None) -> str:
    """Captions sized and placed for this output frame (the clip captions assume 1080x1920). With `window`
    (start, end in seconds), only that stretch, shifted to start at 0 (one render piece)."""
    lines = [_ass_header(captions, width, height)]
    for a, b, text in caption_events(words, captions) if events is None else events:
        if window:
            if b <= window[0] or a >= window[1]:
                continue
            a, b = a - window[0], b - window[0]
        lines.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Cap,,0,0,0,,{text}\n")
    return "".join(lines)


def _font() -> Path:
    return config.FONTS_DIR / "Poppins-SemiBold.ttf"


# ------------------------------------------------------------------ rendering
def _check(cancelled: Callable[[], bool] | None) -> None:
    if cancelled and cancelled():
        raise Cancelled()


def _video_input(e: dict, rel_frame: int, frames: int, fps: int, width: int, height: int, idx: int, label: str,
                 layout: str, cwd: Path) -> tuple[list[str], list[str]]:
    """(input arguments, filter lines) producing normalised frames of element `e` from `rel_frame` on (the last
    frame repeats if a file ends early, so a piece always has its exact frame count)."""
    secs = frames / fps + 0.5
    if e["kind"] == "title":
        (cwd / "title.txt").write_text(e["title"][:120], encoding="utf-8")
        font = filter_path(_font(), cwd)
        return (["-f", "lavfi", "-i", f"color=c=0x0B0D14:s={width}x{height}:r={fps}:d={secs:.3f}"],
                [f"[{idx}:v]drawtext=fontfile={font}:textfile=title.txt:fontcolor=white:fontsize={int(height * 0.07)}:"
                 f"x=(w-text_w)/2:y=(h-text_h)/2,format=yuv420p,setsar=1,fps={fps},settb=AVTB,setpts=PTS-STARTPTS,"
                 f"tpad=stop=-1:stop_mode=clone{label}"])
    path = e["path"]
    if e["kind"] == "image":
        args = ["-loop", "1", "-framerate", str(fps), "-t", f"{secs:.3f}", "-i", path]
    else:
        start = e["src_in_ms"] / 1000 + rel_frame / fps
        args = ["-ss", f"{start:.6f}", "-t", f"{secs:.3f}", "-i", path]
    layout = (e.get("clip") or {}).get("layout") or layout
    lines = []
    src = f"[{idx}:v]"
    zoom = float((e.get("clip") or {}).get("zoom") or 1.0)
    if zoom > 1.001:  # punch in on the centre (hides a jump cut)
        lines.append(f"{src}crop=trunc(iw/{zoom:.4f}/2)*2:trunc(ih/{zoom:.4f}/2)*2[zm{idx}]")
        src = f"[zm{idx}]"
    if layout == "fill":
        chain = f"{src}scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    else:
        lines.append(f"{src}split[bgs{idx}][fgs{idx}]")
        lines.append(f"[bgs{idx}]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
                     f"boxblur=20:2[bg{idx}]")
        lines.append(f"[fgs{idx}]scale={width}:{height}:force_original_aspect_ratio=decrease[fg{idx}]")
        chain = f"[bg{idx}][fg{idx}]overlay=(W-w)/2:(H-h)/2"
    lines.append(f"{chain},fps={fps},format=yuv420p,setsar=1,settb=AVTB,setpts=PTS-STARTPTS,"
                 f"tpad=stop=-1:stop_mode=clone{label}")
    return args, lines


def _overlay_input(ov: dict, frames: int, fps: int, width: int, height: int, idx: int,
                   label: str) -> tuple[list[str], list[str]]:
    """(input arguments, filter lines) for one picture over the video, exactly `frames` long, fading in and out."""
    secs = frames / fps + 0.5
    if ov["kind"] == "image":
        args = ["-loop", "1", "-framerate", str(fps), "-t", f"{secs:.3f}", "-i", ov["path"]]
    else:
        args = ["-ss", f"{ov['src_in_ms'] / 1000:.6f}", "-t", f"{secs:.3f}", "-an", "-i", ov["path"]]
    push = ov["motion"] == "zoom"
    # a slow push-in is cropped from a larger frame, so it moves smoothly and never upscales the output
    w, h = (int(width * 1.5) // 2 * 2, int(height * 1.5) // 2 * 2) if push else (width, height)
    lines = []
    src = f"[{idx}:v]"
    if ov["fit"] == "fit":
        lines.append(f"{src}split[obs{idx}][ofs{idx}]")
        lines.append(f"[obs{idx}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:2[obg{idx}]")
        lines.append(f"[ofs{idx}]scale={w}:{h}:force_original_aspect_ratio=decrease[ofg{idx}]")
        chain = f"[obg{idx}][ofg{idx}]overlay=(W-w)/2:(H-h)/2"
    else:
        chain = f"{src}scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    if push:
        chain += (f",zoompan=z='1+{OVERLAY_PUSH}*on/{max(1, frames)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                  f":d=1:s={width}x{height}:fps={fps}")
    chain += f",fps={fps},setsar=1,settb=AVTB,setpts=PTS-STARTPTS,tpad=stop=-1:stop_mode=clone"
    fade = min(round(OVERLAY_FADE_S * fps), frames // 4)
    if fade > 0:
        chain += (f",format=yuva420p,fade=t=in:start_frame=0:nb_frames={fade}:alpha=1,"
                  f"fade=t=out:start_frame={frames - fade}:nb_frames={fade}:alpha=1")
    else:
        chain += ",format=yuv420p"
    lines.append(chain + label)
    return args, lines


def _encode_args(preview: bool, settings: dict | None) -> list[str]:
    # no B-frames: every piece is a closed, self-contained stream that joins by plain concatenation
    return ["-c:v", "libx264", "-preset", "ultrafast" if preview else (settings or {}).get("video_preset")
            or "veryfast", "-crf", "30" if preview else "20", "-bf", "0", "-pix_fmt", "yuv420p"]


def _piece(spec: dict, els: list[dict], fps: int, width: int, height: int, layout: str, kind: str | None,
           encode: list[str], ass: str, cache: Path, tmp: Path, cancelled) -> Path:
    """One piece of the picture, cached by everything that changes its pixels."""
    key_src = {"engine": ENGINE, "rel": spec["rel"], "frames": spec["frames"], "w": width, "h": height, "fps": fps,
               "layout": layout, "kind": kind if len(spec["els"]) == 2 else None, "enc": encode, "ass": ass,
               "inputs": [{"kind": els[k]["kind"], "sha": els[k].get("sha256", ""), "in": els[k]["src_in_ms"],
                           "title": els[k].get("title", ""),
                           "layout": (els[k].get("clip") or {}).get("layout"),
                           **({"zoom": (els[k].get("clip") or {}).get("zoom")}
                              if float((els[k].get("clip") or {}).get("zoom") or 1.0) > 1.001 else {})}
                          for k in spec["els"]]}
    if spec.get("ov"):
        ov = spec["ov"]
        key_src["overlay"] = {k: ov[k] for k in ("kind", "sha", "fit", "motion", "src_in_ms")}
    key = hashlib.sha256(json.dumps(key_src, sort_keys=True).encode()).hexdigest()[:32]
    out = cache / f"{key}.h264"
    if out.is_file() and out.stat().st_size > 0:
        return out
    inputs, lines = [], []
    for n, (k, rel) in enumerate(zip(spec["els"], spec["rel"])):
        args, chain = _video_input(els[k], rel, spec["frames"], fps, width, height, n, f"[s{n}]", layout, tmp)
        inputs += args
        lines += chain
    if len(spec["els"]) == 2:
        lines.append(f"[s0][s1]xfade=transition={kind}:duration={spec['frames'] / fps:.6f}:offset=0,fps={fps}[j]")
        last = "[j]"
    else:
        last = "[s0]"
    if spec.get("ov"):
        n = len(spec["els"])
        args, chain = _overlay_input(spec["ov"], spec["frames"], fps, width, height, n, f"[o{n}]")
        inputs += args
        lines += chain
        lines.append(f"{last}[o{n}]overlay=0:0:format=auto,format=yuv420p[ov]")
        last = "[ov]"
    if ass:
        (tmp / "piece.ass").write_text(ass, encoding="utf-8")
        lines.append(f"{last}ass=piece.ass:fontsdir={filter_path(config.FONTS_DIR, tmp)},format=yuv420p[vout]")
    else:
        lines.append(f"{last}format=yuv420p[vout]")
    part = cache / f"{key}.part"
    run([*inputs, "-filter_complex", ";".join(lines), "-map", "[vout]", "-frames:v", str(spec["frames"]), *encode,
         "-an", "-f", "h264", str(part)], duration=spec["frames"] / fps, cancel=cancelled, cwd=tmp)
    part.replace(out)
    return out


def _raw_audio(args: list[str], chain: str, samples: int, out: Path, cancelled) -> Path:
    """Decode to raw float stereo samples, exactly `samples` long (padded with silence or cut)."""
    run([*args, "-vn", "-af", f"{chain},apad=whole_len={samples},atrim=end_sample={samples}", "-f", "f32le", "-ac",
         "2", "-ar", str(SR), str(out)], duration=samples / SR, cancel=cancelled, cwd=out.parent)
    want = samples * 8
    have = out.stat().st_size
    if have != want:  # never trust a decoder's padding: make the length exact
        with open(out, "r+b") as fh:
            if have > want:
                fh.truncate(want)
            else:
                fh.seek(0, os.SEEK_END)
                fh.write(b"\0" * (want - have))
    return out


def _fades(fade_in_ms: int, fade_out_ms: int, length_s: float) -> str:
    out = ""
    if fade_in_ms > 0:
        out += f",afade=t=in:st=0:d={fade_in_ms / 1000:.3f}"
    if fade_out_ms > 0:
        out += f",afade=t=out:st={max(0.0, length_s - fade_out_ms / 1000):.6f}:d={fade_out_ms / 1000:.3f}"
    return out


NORMALISE = "aresample=48000:async=1:first_pts=0,aformat=sample_fmts=flt:sample_rates=48000:channel_layouts=stereo"


def mix(total: int, parts: list[dict], out: Path, cancelled=None) -> None:
    """Sum raw stereo parts into one bus of `total` samples, block by block (each part: start, n, path and optional
    linear ramp lengths at its edges, which make an exact crossfade with a neighbour's opposite ramp)."""
    import numpy as np

    maps = [(p, np.memmap(p["path"], dtype=np.float32, mode="r", shape=(p["n"], 2))) for p in parts]
    try:
        with open(out, "wb") as fh:
            for b0 in range(0, total, MIX_BLOCK):
                _check(cancelled)
                b1 = min(total, b0 + MIX_BLOCK)
                buf = np.zeros((b1 - b0, 2), dtype=np.float32)
                for p, mm in maps:
                    s, e = p["start"], p["start"] + p["n"]
                    if e <= b0 or s >= b1:
                        continue
                    lo, hi = max(s, b0), min(e, b1)
                    chunk = np.asarray(mm[lo - s:hi - s], dtype=np.float32)
                    if p.get("ramp_in") or p.get("ramp_out"):
                        pos = np.arange(lo - s, hi - s, dtype=np.float64)
                        g = np.ones(hi - lo, dtype=np.float64)
                        if p.get("ramp_in"):
                            g = np.minimum(g, pos / p["ramp_in"])
                        if p.get("ramp_out"):
                            g = np.minimum(g, (p["n"] - pos) / p["ramp_out"])
                        chunk = chunk * g.astype(np.float32)[:, None]
                    buf[lo - b0:hi - b0] += chunk
                fh.write(buf.tobytes())
    finally:
        for _, mm in maps:
            mm._mmap.close()  # noqa: SLF001 - release the file now (Windows cannot delete an open map)
        del maps


def duck_gains(speech: Path, total: int, depth_db: float, cancelled=None) -> tuple["np.ndarray", dict]:
    """Gain (linear) per 10 ms frame for the music and effects that duck, from the speech bus itself."""
    import numpy as np

    frames = (total + DUCK_FRAME - 1) // DUCK_FRAME
    rms = np.zeros(frames, dtype=np.float64)
    mm = np.memmap(speech, dtype=np.float32, mode="r", shape=(total, 2))
    try:
        step = (MIX_BLOCK // DUCK_FRAME) * DUCK_FRAME
        for b0 in range(0, total, step):
            _check(cancelled)
            block = np.asarray(mm[b0:min(total, b0 + step)], dtype=np.float64).mean(axis=1)
            pad = (-len(block)) % DUCK_FRAME
            block = np.concatenate([block, np.zeros(pad)]) if pad else block
            f0 = b0 // DUCK_FRAME
            rms[f0:f0 + len(block) // DUCK_FRAME] = np.sqrt((block.reshape(-1, DUCK_FRAME) ** 2).mean(axis=1))
    finally:
        mm._mmap.close()  # noqa: SLF001
    level = 20 * np.log10(np.maximum(rms, 1e-9))
    voiced = level[level > -60]
    if not len(voiced) or depth_db <= 0:
        return np.ones(frames), {"depth_db": depth_db, "speech_share": 0.0, "threshold_db": None}
    threshold = max(-50.0, float(np.percentile(voiced, 90)) - 20.0)
    speaking = level > threshold
    hold = int(DUCK_HOLD_S * SR / DUCK_FRAME)
    if hold and speaking.any():  # stay down through the short gaps between words
        idx = np.flatnonzero(speaking)
        held = np.zeros(frames + hold + 1, dtype=np.int64)
        np.add.at(held, idx, 1)
        np.add.at(held, idx + hold + 1, -1)
        speaking = np.cumsum(held)[:frames] > 0
    target = np.where(speaking, -float(depth_db), 0.0)
    down = 1 - math.exp(-DUCK_FRAME / (DUCK_ATTACK_S * SR))
    up = 1 - math.exp(-DUCK_FRAME / (DUCK_RELEASE_S * SR))
    gain_db = np.empty(frames)
    g = 0.0
    for k in range(frames):  # one-pole smoothing: quick to dip, slow to come back
        t = target[k]
        g += (t - g) * (down if t < g else up)
        gain_db[k] = g
    return 10 ** (gain_db / 20), {"depth_db": depth_db, "speech_share": round(float(speaking.mean()), 4),
                                  "threshold_db": round(threshold, 1)}


def combine(total: int, speech: Path, ducked: Path | None, free: Path | None, gains, out: Path, cancelled=None) -> None:
    """The final mix: speech, plus the ducking bus at the per-frame gains, plus the bus that never ducks."""
    import numpy as np

    maps = {k: np.memmap(p, dtype=np.float32, mode="r", shape=(total, 2))
            for k, p in (("speech", speech), ("ducked", ducked), ("free", free)) if p}
    centers = (np.arange(len(gains)) + 0.5) * DUCK_FRAME
    try:
        with open(out, "wb") as fh:
            for b0 in range(0, total, MIX_BLOCK):
                _check(cancelled)
                b1 = min(total, b0 + MIX_BLOCK)
                buf = np.array(maps["speech"][b0:b1], dtype=np.float32)
                if "ducked" in maps:
                    g = np.interp(np.arange(b0, b1), centers, gains).astype(np.float32)
                    buf += np.asarray(maps["ducked"][b0:b1], dtype=np.float32) * g[:, None]
                if "free" in maps:
                    buf += np.asarray(maps["free"][b0:b1], dtype=np.float32)
                fh.write(buf.tobytes())
    finally:
        for mm in maps.values():
            mm._mmap.close()  # noqa: SLF001
        del maps


def _post(gain_db: float | None, measure: bool) -> str:
    post = ["aformat=sample_fmts=dbl:sample_rates=48000:channel_layouts=stereo"]
    if measure:
        post.append("loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json")
    else:
        if gain_db is not None:
            post.append(f"volume={gain_db:.6f}dB:precision=double")
        post += ["aresample=48000", "alimiter=limit=0.841395:attack=5:release=50:level=disabled:latency=1",
                 "asettb=1/48000", "asetpts=N/SR/TB"]
    return ",".join(post)


def _raw_input(path: Path) -> list[str]:
    return ["-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(path)]


def _measure(mixed: Path, total_s: float, work: Path, cancelled) -> float:
    result = run_process([ffmpeg_bin(), "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info",
                          *_raw_input(mixed), "-filter_complex", f"[0:a]{_post(None, True)}[aout]",
                          "-map", "[aout]", "-f", "null", "-"],
                         timeout=max(120.0, total_s * 6), cancel=cancelled, cwd=str(work))
    if result.returncode:
        raise FFmpegError("Could not measure the video's audio: " +
                          result.stderr.decode("utf-8", "replace")[-400:])
    blocks = re.findall(r'\{\s*"input_i"\s*:.*?\}', result.stderr.decode("utf-8", "replace"), re.S)
    if not blocks:
        return 0.0
    measured = json.loads(blocks[-1])
    integrated, peak = float(measured["input_i"]), float(measured["input_tp"])
    if not math.isfinite(integrated):
        return 0.0  # silence: never amplify background noise blindly
    return max(-24.0, min(-14.0 - integrated, -1.5 - peak, 24.0))


def _size(plan: dict, preview: bool) -> tuple[int, int]:
    width, height = ASPECTS[plan["output"]["aspect"]]
    if preview:
        scale = PREVIEW_HEIGHT / min(width, height)
        width, height = int(width * scale) // 2 * 2, int(height * scale) // 2 * 2
    return width, height


def space_needed(plan: dict, preview: bool) -> int:
    """Bytes a render may need at its peak: picture pieces plus the joined copy and the output, the raw audio of
    the elements and items, and the mixed buses."""
    plan = upgrade(plan)
    width, height = _size(plan, preview)
    secs = duration_ms(plan) / 1000
    fps = int((plan.get("output") or {}).get("fps") or 30)
    picture = width * height * fps * (0.004 if preview else 0.0165) * secs
    sound = SR * 8 * secs * (2 + min(3, len(plan.get("audio") or [])))
    return int(picture * 3 + sound + 200e6)


def check_space(plan: dict, folder: Path, preview: bool) -> None:
    """Explain the real limit before any work starts (nothing is cut short half-way)."""
    folder.mkdir(parents=True, exist_ok=True)
    need, free = space_needed(plan, preview), shutil.disk_usage(folder).free
    if free < need:
        raise RenderSpaceError(f"This render needs about {need / 1e9:.1f} GB of free disk space and "
                               f"{free / 1e9:.1f} GB is free. Free some space, then render again; nothing was "
                               "changed.")


def render(plan: dict, assets: dict[str, dict], words_by_asset: dict[str, list[dict]], out_path: Path, *,
           preview: bool = False, settings: dict | None = None, progress: Callable[[float], None] | None = None,
           cancelled: Callable[[], bool] | None = None, cache_dir: Path | None = None) -> dict:
    """Render the plan to `out_path`; returns the probe, time map, final transcript and audio checks of the file."""
    plan = upgrade(plan)
    problems = validate(plan, assets)
    if problems:
        raise ValueError("; ".join(problems))
    report = progress or (lambda _f: None)
    work = out_path.parent
    check_space(plan, work, preview)
    cache = cache_dir or (work / "pieces")
    tmp = work / ("preview.work" if preview else "final.work")
    shutil.rmtree(tmp, ignore_errors=True)  # leftovers of an interrupted attempt
    for d in (cache, tmp):
        d.mkdir(parents=True, exist_ok=True)
    width, height = _size(plan, preview)
    fps = int((plan.get("output") or {}).get("fps") or 30)
    els, _overlap = frame_map(plan, fps)
    for e in els:
        if e["kind"] == "title":
            e["title"] = plan["title"]["text"]
        else:
            a = assets[e["asset_id"]]
            e.update(path=a["path"], sha256=a.get("sha256", ""))
    overlays = _overlay_frames(plan, els, fps, assets)
    total_f = els[-1]["end_f"]
    total_s = total_f / fps
    segs = render_timeline(plan, fps)
    words = output_words(plan, words_by_asset, segs)
    captions = plan.get("captions") or {}
    events = caption_events(words, captions) if captions.get("enabled") and words else []
    trans = TRANSITIONS.get((plan.get("transition") or {}).get("type", "cut"))
    layout = plan.get("layout") or "fit"
    encode = _encode_args(preview, settings)
    try:
        # ---- picture: bodies and joins, each a separate small FFmpeg run, cached by content
        specs = []
        for k, e in enumerate(els):
            head = e["ov_in"]
            tail = els[k + 1]["ov_in"] if k + 1 < len(els) else 0
            b0, b1 = e["start_f"] + head, e["end_f"] - tail
            if b1 > b0:  # the body, cut at the edges of its overlays (each overlay is exactly one piece)
                mine = overlays.get(k) or []
                cuts = sorted({b0, b1, *(x for o in mine for x in (o["start_f"], o["end_f"]) if b0 < x < b1)})
                for a, b in zip(cuts, cuts[1:]):
                    ov = next((o for o in mine if o["start_f"] <= a and b <= o["end_f"]), None)
                    specs.append({"els": [k], "rel": [a - e["start_f"]], "frames": b - a, "at": a, "ov": ov})
            if tail:
                specs.append({"els": [k, k + 1], "rel": [e["frames"] - tail, 0], "frames": tail,
                              "at": e["end_f"] - tail})
        used, done = [], 0
        for spec in specs:
            _check(cancelled)
            window = (spec["at"] / fps, (spec["at"] + spec["frames"]) / fps)
            mine = [ev for ev in events if ev[1] > window[0] and ev[0] < window[1]]
            ass = captions_ass([], captions, width, height, window, mine) if mine else ""
            used.append(_piece(spec, els, fps, width, height, layout, trans, encode, ass, cache, tmp, cancelled))
            done += spec["frames"]
            report(0.75 * done / total_f)
        joined = tmp / "picture.h264"
        with open(joined, "wb") as fh:
            for piece in used:
                with open(piece, "rb") as src:
                    shutil.copyfileobj(src, fh, 1 << 20)

        # ---- sound: each element and audio item to exact raw samples, then three buses mixed block by block
        tracks = {**default_tracks(), **(plan.get("tracks") or {})}
        spf = SR // fps
        total_n = total_f * spf
        speech, ducked, free = [], [], []
        src_track = tracks["source"]
        for k, e in enumerate(els):
            clip = e.get("clip") or {}
            a = assets.get(e["asset_id"]) if e["kind"] == "video" else None
            if not a or not (a.get("probe") or {}).get("has_audio") or clip.get("mute") or src_track.get("mute"):
                continue
            _check(cancelled)
            n = e["frames"] * spf
            gain = float(clip.get("gain_db") or 0) + float(src_track.get("gain_db") or 0)
            raw = _raw_audio(["-ss", f"{e['src_in_ms'] / 1000:.6f}", "-t", f"{n / SR + 0.5:.6f}", "-i", e["path"]],
                             f"{NORMALISE},volume={gain:.2f}dB" + _fades(int(clip.get("fade_in_ms") or 0),
                                                                        int(clip.get("fade_out_ms") or 0), n / SR),
                             n, tmp / f"el{k}.raw", cancelled)
            speech.append({"start": e["start_f"] * spf, "n": n, "path": raw,
                           "ramp_in": e["ov_in"] * spf,
                           "ramp_out": (els[k + 1]["ov_in"] if k + 1 < len(els) else 0) * spf})
        items = {i["id"]: i for i in plan.get("audio") or []}
        placed = audio_timeline(plan, segs, round(total_s * 1000))
        for k, place in enumerate(placed):
            item = items[place["audio_id"]]
            track = tracks[place["track"]]
            if track.get("mute"):
                continue
            _check(cancelled)
            start = min(total_n, round(place["out_start_ms"] * SR / 1000))
            n = min(total_n - start, round((place["out_end_ms"] - place["out_start_ms"]) * SR / 1000))
            if n <= 0:
                continue
            gain = float(item.get("gain_db") or 0) + float(track.get("gain_db") or 0)
            path = assets[item["asset_id"]]["path"]
            args = ["-stream_loop", "-1", "-i", path] if place["loop"] else \
                ["-ss", f"{place['src_in_ms'] / 1000:.6f}", "-t", f"{n / SR + 0.5:.6f}", "-i", path]
            raw = _raw_audio(args, f"{NORMALISE},volume={gain:.2f}dB" + _fades(
                int(item.get("fade_in_ms") or 0), int(item.get("fade_out_ms") or 0), n / SR), n,
                tmp / f"item{k}.raw", cancelled)
            part = {"start": start, "n": n, "path": raw}
            if item["role"] == "voiceover":
                speech.append(part)
            elif item.get("duck"):
                ducked.append(part)
            else:
                free.append(part)
        report(0.82)
        buses: dict[str, Path] = {}
        for name, parts in (("speech", speech), ("ducked", ducked), ("free", free)):
            if parts or name == "speech":  # the speech bus always exists (silence when nobody speaks)
                buses[name] = tmp / f"bus-{name}.raw"
                mix(total_n, parts, buses[name], cancelled)
        for part in speech + ducked + free:
            Path(part["path"]).unlink(missing_ok=True)
        depth = float((plan.get("ducking") or {}).get("depth_db", DUCK_DEPTH_DB))
        import numpy as np

        gains, ducking = (duck_gains(buses["speech"], total_n, depth, cancelled) if "ducked" in buses else
                          (np.ones(1), {"depth_db": depth, "speech_share": None, "threshold_db": None}))
        mixed = tmp / "mix.raw"
        combine(total_n, buses["speech"], buses.get("ducked"), buses.get("free"), gains, mixed, cancelled)
        for bus in buses.values():
            bus.unlink(missing_ok=True)
        gain = _measure(mixed, total_s, tmp, cancelled)
        report(0.88)

        # ---- the file: joined picture (stream copy) and the mixed, normalised sound
        tmp_out = out_path.with_suffix(".tmp.mp4")
        run(["-f", "h264", "-framerate", str(fps), "-i", str(joined), *_raw_input(mixed), "-filter_complex",
             f"[1:a]{_post(gain, False)}[aout]", "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac",
             "-profile:a", "aac_low", "-b:a", "128k" if preview else "192k", "-ac", "2", "-ar", "48000",
             "-movflags", "+faststart", "-t", f"{total_s:.6f}", str(tmp_out)],
            duration=total_s, progress=lambda f: report(0.88 + 0.12 * f), cancel=cancelled, cwd=work)
        tmp_out.replace(out_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # raw audio and joined copies never outlive the render
    keep = {p.name for p in used}
    for old in cache.glob("*.h264"):  # pieces no later render of this kind can reuse are removed
        if old.name not in keep:
            old.unlink(missing_ok=True)
    info = probe(out_path)
    timing = audio_timing.require_valid(out_path)
    return {"engine": ENGINE, "preview": preview, "width": info["width"], "height": info["height"],
            "duration": info["duration"], "expected_duration": round(total_s, 3), "fps": info["fps"],
            "has_audio": info["has_audio"], "audio_timing": timing, "normalization_gain_db": round(gain, 3),
            "timeline": segs, "audio_timeline": placed, "ducking": ducking, "words": words,
            "overlays": [{"overlay_id": o["id"], "start_f": o["start_f"], "end_f": o["end_f"]}
                         for k in sorted(overlays) for o in overlays[k]],
            "captions": bool(events),
            "pieces": len(used), "frames": total_f}

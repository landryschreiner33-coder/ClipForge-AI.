"""The full-video engine adapter, version ffmpeg-v2 (docs/clipforge/EDITOR_INTEGRATION.md).

An edit plan is engine-independent JSON with integer-millisecond times (timebase 1000). This adapter declares what it
supports, validates a plan against it (anything else is reported before rendering, never silently dropped), builds
the exact output time map, and renders from the full originals on the server. A preview is the same plan at a small
size and a fast preset, so preview and export follow one code path; a preview's picture may come from a small proxy
copy of a big video when one has been made (studio/proxies.py), its sound still comes from the original, and a final
render never reads a proxy.

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

Colour (pipeline/grade.py, plan key `color`): every video recording is read with its own colour matrix and range and
leaves as BT.709 limited range. Phone HDR (HLG/PQ) is always tone-mapped to normal video. With `color.auto` each
recording's white balance, exposure and contrast are corrected once (measured over the parts the plan uses, cached
next to the pieces), with `color.match` the recordings are nudged toward the one that plays longest, and
`color.look`/`strength` add a style. All of that is one 3D colour table per recording, applied to the body of each
piece after framing. A plan made before colour existed has no `color` and only gets the HDR conversion.

Speed and motion (studio/retime.py): a clip may play at `speed` (0.25 to 4, pitch kept) or follow a `speed_ramp`, a
freeze clip (kind "freeze") holds one frame of a video, and `motion` moves the framing slowly over a clip, photo or
freeze. Every place that turns file time into video time goes through retime's one map (picture, sound, captions,
overlays, attached sounds, chapters), so at speed 1 nothing changes. An overlay's or attached sound's `offset_ms`
counts in its clip's file time from the in point (on a freeze frame: in video time), so it stays on the moment it was
attached to whatever the speed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
from pathlib import Path
from typing import Callable

from .. import config
from ..pipeline import audio_timing, cleanup, grade, loudness, steady
from . import multicam, retime, sound_joins
from ..pipeline.captions import STYLE_PRESETS, chunk_words, hex_to_ass
from ..pipeline.common import Cancelled
from ..pipeline.ffmpeg_utils import FFmpegError, ffmpeg_bin, filter_path, probe, run, run_process

ENGINE = "ffmpeg-v2"
SCHEMA = 2
ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}
MIRROR = {"top_left": "top_right", "top_right": "top_left", "bottom_left": "bottom_right",
          "bottom_right": "bottom_left"}
FPS = (24, 25, 30, 50, 60)  # each divides 48000, so a frame always holds a whole number of samples
SR = 48000
PREVIEW_HEIGHT = 360
RETIME_PRE_MS = 100   # a sped-up or slowed piece is read from this far before its first moment (one frame or more)
FREEZE_PRE_S = 0.2    # a freeze frame is found among the frames this far before its moment
STEADY_MARGIN_S = 1.0  # camera shake is measured this far either side of a clip (its smoothed path runs on)
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
             "replace", "split", "word_fixes", "joins", "zoom", "overlays", "clean_sound", "color", "speed",
             "speed_ramp", "freeze", "motion", "multicam", "pip", "steady"}
ZOOM_RANGE = (1.0, 1.5)       # a clip's punch-in
LEAD_MAX_MS = 10000           # how far a sound may start before (or after) the moment it is attached to
OVERLAY_KINDS = ("image", "video")
OVERLAY_MOTIONS = ("still", "zoom")
OVERLAY_FITS = ("fill", "fit")
OVERLAY_MIN_MS = 500
OVERLAY_PUSH = 0.08           # how far a "zoom" overlay pushes in over its whole length
OVERLAY_FADE_S = 0.2
UNSUPPORTED = {"effects_plugins": "effects plugins"}
MIX_BLOCK = SR * 10  # samples per mixing block (bounded memory whatever the length)


class RenderSpaceError(ValueError):
    """Not enough free disk space to render; nothing was started."""


def capabilities() -> dict:
    return {"engine": ENGINE, "schema": SCHEMA, "supported": sorted(SUPPORTED), "aspects": list(ASPECTS),
            "fps": list(FPS), "transitions": list(TRANSITIONS), "layouts": list(LAYOUTS), "roles": list(ROLES),
            "tracks": TRACKS, "caption_sizes": list(CAPTION_SIZES), "caption_positions": list(CAPTION_POSITIONS),
            "gain_range_db": list(GAIN_RANGE), "duck_depth_db": {"default": DUCK_DEPTH_DB, "range": list(DUCK_RANGE)},
            "zoom_range": list(ZOOM_RANGE), "overlays": {"kinds": list(OVERLAY_KINDS), "motions": list(OVERLAY_MOTIONS),
                                                         "min_ms": OVERLAY_MIN_MS, "places": list(multicam.PLACES),
                                                         "corner_size": list(multicam.CORNER_SIZE)},
            "multicam": {"max_cams": multicam.MAX_CAMS, "shots": list(multicam.SHOTS),
                         "switching": list(multicam.SWITCHING), "corners": list(multicam.CORNERS),
                         "corner_size": list(multicam.CORNER_SIZE), "min_hold_ms": multicam.MIN_HOLD_MS},
            "clean_sound": list(config.CLEAN_SOUND_MODES), "unsupported": UNSUPPORTED,
            "speed_range": list(retime.SPEED_RANGE),
            "speed_ramps": {k: v[0] for k, v in retime.RAMPS.items()},
            "motions": {k: v[0] for k, v in retime.MOTIONS.items()}, "motion_zoom": list(retime.MOTION_ZOOM),
            "freeze": {"min_ms": retime.FREEZE_MIN_MS, "default_ms": retime.FREEZE_DEFAULT_MS},
            "color": {"looks": {k: grade.LOOKS[k] for k in config.LOOKS}, "strength": [0, 100],
                      "auto": "white balance, exposure and contrast once per recording; phone HDR always converted",
                      "match": "recordings matched to the one that plays longest",
                      "steady": "shaky camera footage steadied (never a tripod shot, a game or a screen); "
                                "a clip's \"steady\": false keeps it as shot"},
            "limits": "No fixed number of files, clips or audio items. Free disk space is checked before a "
                      "render; each step opens at most two media files.",
            "notes": "Renders from the full original files on the server; previews use the same plan at 360p and "
                     "read a small proxy copy of a big video when one has been made (never a final render)."}


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
    """How long a clip plays in the video (ms): its file range at its speed, or a freeze frame's hold."""
    return retime.out_len_ms(c)


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
        lead = (anchor or {}).get("lead_ms")
        if lead is not None and (isinstance(lead, bool) or not isinstance(lead, (int, float))
                                 or abs(lead) > LEAD_MAX_MS):
            out.append(f"“{name}” starts more than {LEAD_MAX_MS // 1000} s away from the moment it is attached to.")
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
    if plan.get("clean_sound") not in (None, *config.CLEAN_SOUND_MODES):
        out.append("Unknown sound cleanup choice.")
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
        timing = retime.problems(c, a, 1000 / float((a.get("probe") or {}).get("fps") or 30))
        out += timing
        if timing:
            continue
        if not retime.is_freeze(c) and _dur(c) < 200:
            out.append(f"Clip “{name}” is shorter than 0.2 s.")
        if a["kind"] == "video" and not retime.is_freeze(c):
            length = _length(a)
            if c["in_ms"] < 0 or (length and c["out_ms"] > length + 50):
                out.append(f"Clip “{name}” is trimmed outside its file.")
        if c.get("layout") not in (None, *LAYOUTS):
            out.append(f"Clip “{name}” has an unknown framing.")
        fades = int(c.get("fade_in_ms") or 0), int(c.get("fade_out_ms") or 0)
        if min(fades) < 0 or sum(fades) > _dur(c):  # fades are in video time (they shape the output samples)
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
    elif transition_too_long(plan):
        out.append("A transition is longer than half of the shortest clip; shorten it.")
    captions = plan.get("captions") or {}
    if captions.get("size", "medium") not in CAPTION_SIZES:
        out.append("Unknown caption size.")
    if captions.get("position", "bottom") not in CAPTION_POSITIONS:
        out.append("Unknown caption position.")
    if captions.get("highlight", False) not in (True, False):
        out.append("Highlighting the spoken word is either on or off.")
    color = plan.get("color")
    if color is not None:
        if not isinstance(color, dict):
            out.append("Unknown colour choice.")
        else:
            if color.get("look", "natural") not in config.LOOKS:
                out.append("Unknown look.")
            strength = color.get("strength", 100)
            if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not 0 <= strength <= 100:
                out.append("The look's strength must be between 0 and 100.")
            for key in ("auto", "match", "clean", "steady"):
                if color.get(key, True) not in (True, False):
                    out.append("Automatic colour, matching, noise cleanup and steadying are each either on or off.")
                    break
    return out + _validate_audio(plan, assets) + _validate_overlays(plan, assets) + multicam.problems(plan, assets)


def default_color(values: dict | None = None) -> dict:
    """A new plan's colour choices from resolved guidance values (or Settings)."""
    v = values or {}
    look = v.get("look") if v.get("look") in config.LOOKS else "natural"
    try:
        strength = max(0, min(100, int(float(v.get("look_strength", 100)))))
    except (TypeError, ValueError):
        strength = 100
    return {"auto": v.get("auto_color", True) is not False, "match": True, "look": look, "strength": strength,
            "clean": v.get("clean_picture", True) is not False, "steady": v.get("stabilize", True) is not False}


def steady_on(plan: dict) -> bool:
    """Whether shaky camera footage is steadied (plan "color" "steady"). A plan made before steadying existed has no
    such choice and renders as it always did."""
    c = plan.get("color")
    return isinstance(c, dict) and c.get("steady") is True


def steady_plans(plan: dict, els: list[dict], assets: dict[str, dict], fps: int, cache: Path,
                 cancelled=None) -> dict[int, "steady.Plan"]:
    """The steadying of each video element that shakes (pipeline/steady.py), measured over its clip's part of the
    recording (and STEADY_MARGIN_S either side) on the file's own frames (its own frame rate, whatever the video's:
    the sendcmd file gives each file frame its own correction before any change of frame rate, so a 60 fps file in
    a 30 fps video, or a 24 fps one whose frames the video repeats, is steadied frame by frame); only the clip's own
    part decides. A clip set to "steady": false, a freeze frame and a photo are left as they are."""
    out: dict[int, steady.Plan] = {}
    if not steady_on(plan):
        return out
    folder = cache.parent / "steady"  # shared by previews and finals (their pieces are kept apart)
    done: dict[tuple, steady.Plan | None] = {}
    for k, e in enumerate(els):
        clip = e.get("clip") or {}
        if e["kind"] != "video" or clip.get("steady") is False or retime.is_freeze(clip):
            continue
        a = assets[e["asset_id"]]
        info = a.get("probe") or {}
        size = (int(info.get("width") or 0), int(info.get("height") or 0))
        if min(size) <= 0:
            continue
        rate = float(info.get("fps") or fps)  # the file's own frames
        t0 = max(0.0, int(clip["in_ms"]) / 1000 - STEADY_MARGIN_S)
        t0 = round(t0 * rate) / rate
        length = int(clip["out_ms"]) / 1000 + STEADY_MARGIN_S - t0
        span = (int(clip["in_ms"]) / 1000, int(clip["out_ms"]) / 1000)
        key = (a["path"], t0, round(length, 3), span)
        if key not in done:
            _check(cancelled)
            done[key] = steady.for_stretch(a["path"], t0, length, rate, size, cache=folder, cancelled=cancelled,
                                           span=span, exact=True)
        if done[key] is not None:
            out[k] = done[key]
    return out


def _clip_seconds(clip: dict):
    """A file second of this clip to its own output seconds (its speed changes included)."""
    return lambda t: retime.out_at(clip, t * 1000 - int(clip.get("in_ms") or 0)) / 1000


def color_options(plan: dict) -> dict:
    """The plan's colour choices as grade options. A plan made before colour existed has none: only phone HDR is
    converted (its picture would be grey otherwise), nothing else changes."""
    c = plan.get("color")
    if not isinstance(c, dict):
        return {"auto_color": False, "look": "natural", "look_strength": 100, "clean_picture": False,
                "match": False}
    return {"auto_color": c.get("auto", True) is not False, "look": c.get("look", "natural"),
            "look_strength": c.get("strength", 100), "clean_picture": c.get("clean", True) is not False,
            "match": c.get("match", True) is not False}


def grades(plan: dict, assets: dict[str, dict], cache: Path, cancelled=None) -> dict[str, dict]:
    """Each video recording's grade (asset id -> {"grade", "denoise", "stats"}), measured over the parts the plan
    plays (clips and video overlays) and matched to the recording that plays longest."""
    opts = color_options(plan)
    ranges: dict[str, list[tuple[float, float]]] = {}
    shown: dict[str, float] = {}  # seconds each recording is on screen (a slowed clip and a freeze count longer)
    for c in plan.get("clips") or []:
        a = assets.get(c.get("asset_id"))
        if c.get("include", True) and a and a.get("kind") == "video":
            at = int(c["in_ms"]) / 1000
            # a freeze frame is measured on a short stretch from its frame on (the colour of that moment)
            end = at + 0.2 if retime.is_freeze(c) else int(c["out_ms"]) / 1000
            ranges.setdefault(c["asset_id"], []).append((at, end))
            shown[c["asset_id"]] = shown.get(c["asset_id"], 0.0) + _dur(c) / 1000
    for o in plan.get("overlays") or []:
        a = assets.get(o.get("asset_id"))
        if a and a.get("kind") == "video" and not o.get("hide"):
            at = int(o.get("in_ms") or 0)
            ranges.setdefault(o["asset_id"], []).append((at / 1000, (at + int(o.get("length_ms") or 0)) / 1000))
            shown[o["asset_id"]] = shown.get(o["asset_id"], 0.0) + int(o.get("length_ms") or 0) / 1000
    for aid, s0, s1, secs in _camera_parts(plan, assets):  # the other cameras of a recording, full or in a corner
        ranges.setdefault(aid, []).append((s0, s1))
        shown[aid] = shown.get(aid, 0.0) + secs
    out: dict[str, dict] = {}
    for aid, spans in ranges.items():
        _check(cancelled)
        g, stats = grade.for_footage(assets[aid]["path"], spans, opts, cache=cache / f"grade-{aid}.json",
                                     cancelled=cancelled)
        out[aid] = {"grade": g, "stats": stats, "denoise": grade.denoise_for(stats, opts),
                    "seconds": shown.get(aid, 0.0)}
    people = {aid: r for aid, r in out.items() if (r["stats"] or {}).get("skin", 0) >= grade.MATCH_SKIN}
    if opts["match"] and opts["auto_color"] and len(people) > 1:
        # only recordings of people are matched to each other: a screen recording keeps its own colours
        ref = max(people, key=lambda aid: people[aid]["seconds"])
        target = grade.corrected_stats(people[ref]["stats"], people[ref]["grade"])
        for aid, r in people.items():
            mine = grade.corrected_stats(r["stats"], r["grade"]) if aid != ref else None
            if target and mine:
                grade.match(r["grade"], mine, target)
    return out


def _cam_lengths(group: dict, assets: dict[str, dict]) -> dict[str, int]:
    """Each other camera's file length (ms), by camera id."""
    return {c["id"]: _length(assets[c["asset_id"]]) for c in group.get("cams") or []
            if c.get("id") and c.get("asset_id") in assets}


def _camera_parts(plan: dict, assets: dict[str, dict]) -> list[tuple[str, float, float, float]]:
    """(asset id, from, to (s of its own file), seconds shown) for every stretch another camera of a recording is on
    screen, full or in the corner (what colour measuring and matching read)."""
    out = []
    for c in plan.get("clips") or []:
        g = multicam.group_of(plan, c.get("asset_id"))
        if not g or not c.get("include", True) or c.get("kind", "video") not in ("video", "freeze"):
            continue
        a = int(c["in_ms"])
        b = a + 200 if retime.is_freeze(c) else int(c["out_ms"])
        for t0, t1, cam, side in multicam.spans(g, a, b, _cam_lengths(g, assets)):
            for which in (cam, side):
                entry = multicam.cam_entry(g, which) if which and which != multicam.MAIN else None
                if entry and entry.get("asset_id") in assets:
                    out.append((entry["asset_id"], multicam.to_cam_ms(entry, t0) / 1000,
                                multicam.to_cam_ms(entry, t1) / 1000, (t1 - t0) / 1000))
    return out


def camera_timeline(plan: dict, assets: dict[str, dict], segs: list[dict] | None = None) -> list[dict]:
    """Which camera is on screen when, and which one is in the corner, in ms of the video (the editor's timeline):
    [{"clip_id", "asset_id", "cam", "label", "corner", "out_start_ms", "out_end_ms"}], only for recordings with other
    cameras."""
    segs = timeline(plan) if segs is None else segs
    clips = {c.get("id"): c for c in plan.get("clips") or []}
    joins = _joins(plan)
    out: list[dict] = []
    for seg in segs:
        g = multicam.group_of(plan, seg["asset_id"])
        clip = clips.get(seg["clip_id"]) or {}
        if not g or seg["kind"] not in ("video", "freeze"):
            continue
        a = seg["src_in_ms"]
        freeze = retime.is_freeze(clip)
        mine = []
        for t0, t1, cam, side in multicam.spans(g, a, a + 1 if freeze else seg["src_out_ms"], _cam_lengths(g, assets)):
            o0 = seg["out_start_ms"] if freeze else seg["out_start_ms"] + round(retime.out_at(clip, t0 - a))
            o1 = seg["out_end_ms"] if freeze else seg["out_start_ms"] + round(retime.out_at(clip, t1 - a))
            if o1 > o0:
                mine.append({"clip_id": seg["clip_id"], "asset_id": seg["asset_id"], "cam": cam,
                             "label": multicam.label_of(g, cam), "corner": side, "out_start_ms": o0, "out_end_ms": o1})
        head, tail = joins.get(seg["clip_id"], (0, 0))
        for row in _settle_rows(mine, seg["out_start_ms"], seg["out_end_ms"], head, tail, "out_start_ms",
                                "out_end_ms"):
            o0, o1 = row["out_start_ms"], row["out_end_ms"]
            last = out[-1] if out else None
            if last and all(last[k] == row[k] for k in ("clip_id", "cam", "corner")) and last["out_end_ms"] == o0:
                last["out_end_ms"] = o1
            else:
                out.append(row)
    return out


def _settle_rows(rows: list[dict], start: float, end: float, head: float, tail: float, a: str, b: str) -> list[dict]:
    """An element's camera stretches with every camera change inside a transition overlap moved to its edge, as the
    joins are rendered (one camera per side for a whole dissolve or fade): a change while the element comes in
    happens as the transition ends; a change while it goes out does not happen."""
    out: list[dict] = []
    for r in rows:
        x = r[a]
        if out:
            if start < x < start + head:
                x = start + head
            if end - tail < x < end:
                x = end
            x = max(x, out[-1][a])
        out.append({**r, a: x})
    for i, r in enumerate(out):
        r[b] = out[i + 1][a] if i + 1 < len(out) else end
    if out:
        out[0][a] = start
    return [r for r in out if r[b] > r[a]]


def cameras_in_use(plan: dict) -> bool:
    """Whether the video shows another camera of a recording, or a picture in a corner (FilmCraft's timeline has
    neither, so with the editing app on "auto" such a final is rendered by the built-in engine)."""
    return multicam.in_use(plan)


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


def transition_too_long(plan: dict) -> bool:
    """Whether the plan's dissolve or fade is longer than half of a clip it joins: in milliseconds, or on the whole
    output frames the render uses (frame_map), where a clip a little over twice the transition can still be a frame
    short. The makers fit their transitions with this same check (makers/shorts.py)."""
    t = plan.get("transition") or {}
    clips = [c for c in plan.get("clips") or [] if c.get("include", True)]
    if t.get("type", "cut") == "cut" or t.get("type") not in TRANSITIONS or not clips:
        return False
    joins = _joins(plan)
    sides = [c for c in clips if any(joins[c["id"]])]  # clips that take part in a transition
    if sides and int(t.get("ms") or 0) * 2 >= min(_dur(c) for c in sides):
        return True
    fps = int((plan.get("output") or {}).get("fps") or 30)
    if fps not in FPS:
        return False
    els, _overlap = frame_map(plan, fps)
    return any(e["frames"] < e["ov_in"] + (els[k + 1]["ov_in"] if k + 1 < len(els) else 0) for k, e in enumerate(els))


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
                    "out_end_ms": start + _dur(c), **_timing(c)})
        pos = start + _dur(c)
    return out


def _timing(c: dict) -> dict:
    """What a time-map entry says about a clip that does not play at normal speed (nothing when it does): its
    speed (a ramp's average), whether it ramps, a freeze frame's hold. Readers of an EDL must not assume 1:1."""
    if not retime.retimed(c):
        return {}
    if retime.is_freeze(c):
        return {"freeze": True, "hold_ms": _dur(c)}
    span = int(c["out_ms"]) - int(c["in_ms"])
    out = {"speed": round(span / max(1e-9, retime.out_exact_ms(c)), 4)}
    if retime.ramp_points(c):
        out["ramp"] = True
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
             "src_out_ms": e["src_in_ms"] + round(retime.src_at(e["clip"], e["frames"] * 1000 / fps)),
             "out_start_ms": round(e["start_f"] * 1000 / fps), "out_end_ms": round(e["end_f"] * 1000 / fps),
             **_timing(e["clip"])}
            for e in els if e["kind"] != "title"]


def offset_out_ms(clip: dict, offset_ms) -> int:
    """Where something attached to a clip at `offset_ms` (an overlay, a sound, a chapter: file time from the in
    point, video time on a freeze frame) plays, in ms from the clip's start in the video. A lead before the clip
    (a negative offset: a whoosh into a cut) is video time, whatever the clip's speed."""
    off = float(offset_ms or 0)
    return round(retime.out_at(clip, max(0.0, off)) + min(0.0, off))


def offset_from_out_ms(clip: dict, out_ms) -> int:
    """The anchor offset for a moment `out_ms` after the clip starts in the video (the inverse of offset_out_ms):
    file time inside a clip, video time before it or on a freeze frame."""
    o = float(out_ms or 0)
    if o < 0 or retime.is_freeze(clip):
        return round(o)
    return round(retime.src_at(clip, o))


def anchor_lead_ms(anchor: dict | None) -> int:
    """How long (video ms) a sound starts before the moment it is attached to: a swish before a picture appears
    stays 270 ms ahead of it at any speed of the clip. 0 when missing or unreadable (validate reports that)."""
    v = (anchor or {}).get("lead_ms")
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) <= LEAD_MAX_MS else 0


def anchor_out_ms(clip: dict, anchor: dict) -> int:
    """Where a sound attached to `clip` starts, in ms from the clip's start in the video."""
    return offset_out_ms(clip, anchor.get("offset_ms")) - anchor_lead_ms(anchor)


def anchor_times(plan: dict) -> dict[str, int]:
    """{audio id: anchor_out_ms} for every sound attached to a clip of the plan, heard or not."""
    clips = {c.get("id"): c for c in plan.get("clips") or []}
    return {i["id"]: anchor_out_ms(clips[i["anchor"]["clip_id"]], i["anchor"]) for i in plan.get("audio") or []
            if isinstance(i.get("anchor"), dict) and i["anchor"].get("clip_id") in clips}


def audio_timeline(plan: dict, segs: list[dict] | None = None, total_ms: int | None = None) -> list[dict]:
    """Where each audio item plays in the output (ms). An item attached to a clip follows that clip; an item whose
    clip is removed is silent; anything past the end of the video is cut (and reported in `cut_ms`)."""
    segs = timeline(plan) if segs is None else segs
    total = duration_ms(plan) if total_ms is None else total_ms
    starts = {s["clip_id"]: s["out_start_ms"] for s in segs}
    clips = {c.get("id"): c for c in plan.get("clips") or []}
    out = []
    for item in plan.get("audio") or []:
        if item.get("mute"):
            continue
        anchor = item.get("anchor")
        if anchor:
            if anchor.get("clip_id") not in starts:
                continue
            clip_ms = anchor_out_ms(clips[anchor["clip_id"]], anchor)
            start = starts[anchor["clip_id"]] + clip_ms
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
                    "loop": bool(item.get("loop")), "cut_ms": start + length - end,
                    # an attached sound: where it starts from its clip's start, in the video's own time
                    **({"clip_ms": clip_ms} if anchor else {})})
    return out


def overlay_timeline(plan: dict, segs: list[dict] | None = None) -> list[dict]:
    """Where each picture over the video shows (ms): inside its clip's own part of the picture (never over a
    transition), a later overlay on the same clip starting after the earlier one ends. A removed clip hides its
    overlays."""
    segs = timeline(plan) if segs is None else segs
    by = {s["clip_id"]: s for s in segs}
    clips = {c.get("id"): c for c in plan.get("clips") or []}
    joins = _joins(plan)
    out: list[dict] = []
    last_end: dict[str, int] = {}
    items = sorted((o for o in plan.get("overlays") or [] if o.get("clip_id") in by and not o.get("hide")),
                   key=lambda o: (o["clip_id"], int(o.get("offset_ms") or 0)))
    for o in items:
        s = by[o["clip_id"]]
        ov_in, ov_out = joins.get(o["clip_id"], (0, 0))
        lo, hi = s["out_start_ms"] + ov_in, s["out_end_ms"] - ov_out
        start = max(lo, s["out_start_ms"] + offset_out_ms(clips[o["clip_id"]], o.get("offset_ms")),
                    last_end.get(o["clip_id"], lo))
        end = min(hi, start + int(o.get("length_ms") or 0))
        if end - start < 300:
            continue
        last_end[o["clip_id"]] = end
        out.append({"overlay_id": o["id"], "asset_id": o["asset_id"], "clip_id": o["clip_id"], "out_start_ms": start,
                    "out_end_ms": end})
    return sorted(out, key=lambda x: x["out_start_ms"])


def _picture_source(a: dict, use_proxies: bool) -> str:
    """The file an element's picture is read from: the asset's proxy for a preview when one exists, else the
    original. A final render never reads a proxy."""
    proxy = a.get("proxy_path") or ""
    if use_proxies and a.get("kind") == "video" and proxy and Path(proxy).is_file():
        return proxy
    return a["path"]


def _overlay_frames(plan: dict, els: list[dict], fps: int, assets: dict[str, dict],
                    use_proxies: bool = False) -> dict[int, list[dict]]:
    """The overlays of each element in whole output frames, inside the element's body (as overlay_timeline). With
    `use_proxies` (previews) a video overlay's picture comes from its proxy when one exists (`src` says which)."""
    index = {e["clip_id"]: k for k, e in enumerate(els) if e["kind"] != "title"}
    out: dict[int, list[dict]] = {}
    last_end: dict[int, int] = {}
    shape = multicam.aspect_key(*ASPECTS.get((plan.get("output") or {}).get("aspect"), (16, 9)))
    camera_corner = {aid: (g.get("corner") or {}).get("place") or multicam.CORNER_DEFAULT[shape][0]
                     for aid, g in multicam.groups(plan).items() if isinstance(g, dict) and (g.get("corner") or {})
                     .get("cam")}
    items = sorted((o for o in plan.get("overlays") or [] if o.get("clip_id") in index and not o.get("hide")),
                   key=lambda o: (index[o["clip_id"]], int(o.get("offset_ms") or 0)))
    for o in items:
        k = index[o["clip_id"]]
        e = els[k]
        b0 = e["start_f"] + e["ov_in"]
        b1 = e["end_f"] - (els[k + 1]["ov_in"] if k + 1 < len(els) else 0)
        start = max(b0, e["start_f"] + round(offset_out_ms(e["clip"], o.get("offset_ms")) * fps / 1000),
                    last_end.get(k, b0))
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
        picture = _picture_source(a, use_proxies)
        place = o.get("place") if o.get("place") in multicam.CORNERS else "full"
        if place != "full" and place == camera_corner.get(e.get("asset_id")):
            place = MIRROR[place]  # the camera in that corner would hide it: the free corner on the same side
        out.setdefault(k, []).append({"id": o["id"], "kind": a["kind"], "asset_id": o["asset_id"], "path": picture,
                                      "src": "proxy" if picture != a["path"] else "original",
                                      "sha": a.get("sha256", ""), "start_f": start, "end_f": end, "fit": fit,
                                      "motion": o.get("motion", "still") if a["kind"] == "image" else "still",
                                      "src_in_ms": int(o.get("in_ms") or 0), "place": place,
                                      # a picture in a corner: its share of the frame's width and its own shape
                                      **({"size": o.get("size"), "shape": _shape(a)} if place != "full" else {})})
    return out


def _shape(a: dict | None) -> float | None:
    p = (a or {}).get("probe") or {}
    w, h = p.get("width") or 0, p.get("height") or 0
    return w / h if w and h else None


def _overlay_box(ov: dict, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Where a picture over the video sits when it is in a corner (None: the whole frame)."""
    if ov.get("place", "full") == "full":
        return None
    return multicam.corner_box(ov["place"], ov.get("size"), width, height, ov.get("shape"))


def _cam_view(group: dict, cam: str | None, t0: float, assets: dict[str, dict], use_proxies: bool,
              look_of: Callable[[str], tuple[dict, dict | None]]) -> dict | None:
    """Where another camera's picture comes from for a stretch starting at the main recording's moment `t0`: its
    file (a preview may read its proxy), how far its time is from the main recording's, and its colour (None: the
    main camera)."""
    entry = multicam.cam_entry(group, cam) if cam and cam != multicam.MAIN else None
    if not entry or entry.get("asset_id") not in assets:
        return None
    a = assets[entry["asset_id"]]
    picture = _picture_source(a, use_proxies)
    colour, look = look_of(entry["asset_id"])
    return {"cam": cam, "asset_id": entry["asset_id"], "path": picture, "sha256": a.get("sha256", ""),
            "src": "proxy" if picture != a["path"] else "original", "colour": colour, "grade": look,
            "shift_ms": round(multicam.to_cam_ms(entry, t0) - t0, 1), "shape": _shape(a)}


def _camera_frames(plan: dict, els: list[dict], fps: int, assets: dict[str, dict], use_proxies: bool, width: int,
                   height: int, look_of: Callable[[str], tuple[dict, dict | None]]) -> dict[int, list[dict]]:
    """For each element of a recording with other cameras, its stretches in whole output frames: [{"f0", "f1", "cam",
    "view" (None: the recording's own picture), "corner" ({"view", "k", "box"} or None)}], covering the element."""
    out: dict[int, list[dict]] = {}
    for k, e in enumerate(els):
        g = multicam.group_of(plan, e.get("asset_id")) if e["kind"] in ("video", "freeze") else None
        if not g:
            continue
        clip = e["clip"]
        a = e["src_in_ms"]
        freeze = retime.is_freeze(clip)
        b = a + 1 if freeze else a + max(1.0, retime.src_at(clip, e["frames"] * 1000 / fps))
        corner = g.get("corner") or {}
        rows: list[dict] = []
        for t0, t1, cam, side in multicam.spans(g, a, b, _cam_lengths(g, assets)):
            f0 = e["start_f"] if freeze or t0 <= a else e["start_f"] + round(retime.out_at(clip, t0 - a) * fps / 1000)
            f1 = e["end_f"] if freeze or t1 >= b else e["start_f"] + round(retime.out_at(clip, t1 - a) * fps / 1000)
            f0, f1 = max(f0, rows[-1]["f1"] if rows else e["start_f"]), min(f1, e["end_f"])
            if f1 <= f0:
                continue
            side_view = _cam_view(g, side, t0, assets, use_proxies, look_of) if side else None
            if side == multicam.MAIN:  # the recording's own picture in the corner, while another camera is full
                colour, look = look_of(e["asset_id"])
                side_view = {"cam": multicam.MAIN, "asset_id": e["asset_id"], "path": e["path"],
                             "sha256": e.get("sha256", ""), "src": e.get("src", "original"), "colour": colour,
                             "grade": look, "shift_ms": 0.0, "shape": _shape(assets.get(e["asset_id"]))}
            rows.append({"f0": f0, "f1": f1, "cam": cam, "view": _cam_view(g, cam, t0, assets, use_proxies, look_of),
                         "corner": {"view": side_view, "k": k,
                                    "box": multicam.corner_box(corner.get("place"), corner.get("size"), width,
                                                               height, side_view.get("shape"))}
                         if side_view else None})
        if rows:
            rows[0]["f0"], rows[-1]["f1"] = e["start_f"], e["end_f"]
            for prev, row in zip(rows, rows[1:]):
                row["f0"] = prev["f1"]
            tail = els[k + 1]["ov_in"] if k + 1 < len(els) else 0
            out[k] = _settle_rows(rows, e["start_f"], e["end_f"], e["ov_in"], tail, "f0", "f1")
    return out


def _viewed(e: dict, view: dict | None) -> dict:
    """Element `e` as another camera sees it (unchanged for the recording's own picture)."""
    if not view:
        return e
    return {**e, "asset_id": view["asset_id"], "path": view["path"], "sha256": view["sha256"], "src": view["src"],
            "src_in_ms": e["src_in_ms"] + view["shift_ms"], "colour": view["colour"], "grade": view["grade"],
            "steady": None}  # another camera of the recording: its own picture, not steadied with this one's


def output_words(plan: dict, words_by_asset: dict[str, list[dict]], segs: list[dict] | None = None) -> list[dict]:
    """The words heard in the output, on the output timeline (seconds), through the time map. A word you corrected
    (plan `word_fixes`) shows your text; its timing stays the measured one.

    A word counts for a clip when it starts inside it and most of its measured time is inside: speech models often
    let a word's end run on into the silence after it, and a cut made in that silence must not drop the word from
    the captions (its shown end is then the clip's end)."""
    fixes = plan.get("word_fixes") or {}
    clips = {c.get("id"): c for c in plan.get("clips") or []}
    out = []
    for seg in timeline(plan) if segs is None else segs:
        clip = clips.get(seg["clip_id"]) or {}
        if retime.is_freeze(clip):
            continue  # a held frame says nothing
        a, b = seg["src_in_ms"] / 1000, seg["src_out_ms"] / 1000
        shift = seg["out_start_ms"] / 1000 - a
        # through the clip's speed: a word's time in the file -> its time in the video
        at = (lambda t, c=clip, a=a, o=seg["out_start_ms"] / 1000: o + retime.out_at(c, (t - a) * 1000) / 1000) \
            if retime.retimed(clip) else (lambda t, s=shift: t + s)
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
            out.append({"w": text, "start": round(at(w["start"]), 3), "end": round(at(end), 3),
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


def _escape_caption(text: str) -> str:
    return text.strip().replace("{", "(").replace("}", ")").replace("\\", "/")


def highlight_events(words: list[dict], captions: dict) -> list[tuple[float, float, str]]:
    """Caption events with the word being said in the style's highlight colour (plan `captions.highlight`, made for
    animated shorts): the same groups as `caption_events`, one event per word while the group is on screen, held
    through short gaps so it never flickers. The plain events stay what exports (FilmCraft, subtitles) read."""
    style = captions.get("style") or "clean"
    p = STYLE_PRESETS.get(style, STYLE_PRESETS["clean"])
    colour = hex_to_ass(p.get("highlight") or "#FFE500")
    grow = f"\\fscx{p['word_scale']}\\fscy{p['word_scale']}" if p.get("word_scale", 100) != 100 else ""
    chunks = chunk_words(words, style)
    out = []
    for ci, chunk in enumerate(chunks):
        texts = [_escape_caption(w["w"]) for w in chunk]
        texts = [t.upper() for t in texts] if p.get("upper") else texts
        start = chunk[0]["start"]
        following = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else None
        end = chunk[-1]["end"] + 0.15
        if following is not None and following - chunk[-1]["end"] < 0.35:
            end = following  # a short gap: keep the group up until the next one starts
        end = max(end, start + 0.2)
        for wi in range(len(chunk)):
            a = start if wi == 0 else chunk[wi]["start"]
            b = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else end
            if b - a < 0.02:
                continue
            text = " ".join(f"{{\\c{colour}{grow}}}{t}{{\\r}}" if k == wi else t for k, t in enumerate(texts))
            out.append((a, b, text))
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


# FFmpeg's overlay mixes up full-range pictures (phone or OBS video, JPEG photos): it hands on limited-range values
# still tagged as full range, so the blacks come out grey. Both halves of a "fit" picture are made limited range first
# (nothing happens to a picture that already is), into a format that cannot mean full range (the old "yuvj" ones
# do, whatever the tag says); 10-bit stays 10-bit for the colour step.
EVEN_RANGE = ("scale=out_range=tv,format=yuv420p|yuv422p|yuv444p|yuv420p10le|yuv422p10le|yuv444p10le|gbrp|rgb24|"
              "rgba|yuva420p")


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
    clip = e.get("clip") or {}
    lines = []
    src = f"[{idx}:v]"
    if e["kind"] == "image":
        args = ["-loop", "1", "-framerate", str(fps), "-t", f"{secs:.3f}", "-i", path]
    elif e["kind"] == "freeze":  # one frame, held (every piece of a freeze reads the same frame)
        # the frame on screen at the held moment: read a little before it and keep the last frame at or before it
        # (a seek to the moment itself drops that frame when it started earlier, and at a file's very end, where
        # the sound runs on past the picture, nothing would be left to hold)
        at = e["src_in_ms"] / 1000
        pre = min(at, FREEZE_PRE_S)
        args = ["-ss", f"{at - pre:.6f}", "-t", f"{pre + 0.1:.6f}", "-i", path]
        lines.append(f"{src}trim=end={pre + 0.0005:.6f},reverse,trim=end_frame=1,setpts=PTS-STARTPTS,fps={fps},"
                     f"tpad=stop=-1:stop_mode=clone[fr{idx}]")
        src = f"[fr{idx}]"
    else:
        # the source moment at this piece's first frame, and as much file as its frames show at this speed
        u0 = retime.src_at(clip, rel_frame * 1000 / fps)
        span = retime.src_at(clip, (rel_frame + frames) * 1000 / fps) - u0
        # read from a little before the piece's first moment when it is retimed: an accurate seek drops the frame
        # already on screen there, and at slow speeds one source frame lasts several output frames; the frames
        # before get negative times and the first output frame shows the source frame the time map says
        pre = min(e["src_in_ms"] + u0, RETIME_PRE_MS) if retime.retimed(clip) else 0
        seek, length = (e["src_in_ms"] + u0 - pre) / 1000, (span + pre) / 1000 + 0.5
        args = ["-ss", f"{seek:.6f}", "-t", f"{length:.3f}", "-i", path]
        if e.get("steady") is not None:  # shaky camera footage, steadied on the file's own times (before retiming)
            src = _steady_filters(e["steady"], seek, length, idx, src, lines, cwd)
        if retime.retimed(clip):
            lines.append(f"{src}{retime.setpts(clip, u0, u0 - pre)},fps={fps}:start_time=0:round=up[sp{idx}]")
            src = f"[sp{idx}]"
        elif retime.motion_keys(clip):  # the move is timed by frame count: count output frames, not the file's
            lines.append(f"{src}fps={fps}[fp{idx}]")
            src = f"[fp{idx}]"
    # (the whole element's length: a move runs over the clip, not over each piece of it)
    move = retime.motion_filter(clip, rel_frame, e.get("frames", rel_frame + frames), width, height)
    if move:  # a slow camera move: the framing window, per frame and by fractions of a pixel
        lines.append(f"{src}{move}[mv{idx}]")
        src = f"[mv{idx}]"
    layout = clip.get("layout") or layout
    zoom = float(clip.get("zoom") or 1.0)
    if zoom > 1.001:  # punch in on the centre (hides a jump cut)
        lines.append(f"{src}crop=trunc(iw/{zoom:.4f}/2)*2:trunc(ih/{zoom:.4f}/2)*2[zm{idx}]")
        src = f"[zm{idx}]"
    if layout == "fill":
        chain = f"{src}scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    else:
        lines.append(f"{src}{EVEN_RANGE},split[bgs{idx}][fgs{idx}]")
        lines.append(f"[bgs{idx}]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
                     f"boxblur=20:2[bg{idx}]")
        lines.append(f"[fgs{idx}]scale={width}:{height}:force_original_aspect_ratio=decrease[fg{idx}]")
        chain = f"[bg{idx}][fg{idx}]overlay=(W-w)/2:(H-h)/2"
    if e["kind"] == "image":  # a photo's own colours (BT.601 JPEG, RGB PNG) into the output's BT.709
        colour = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
    else:
        look = e.get("grade") or {}
        colour = grade.yuv_filters(e.get("colour") or {}, look.get("grade") or grade.Grade(), look.get("denoise", ""),
                                   cwd, int((e.get("colour") or {}).get("height") or 0))
    lines.append(f"{chain},{colour},fps={fps},format=yuv420p,setsar=1,settb=AVTB,setpts=PTS-STARTPTS,"
                 f"tpad=stop=-1:stop_mode=clone{label}")
    return args, lines


def _steady_filters(sp: "steady.Plan", seek: float, length: float, idx: int, src: str, lines: list[str],
                    cwd: Path) -> str:
    """Steadying in the filter graph: a sendcmd file (written next to the piece) moves a crop window of the plan's
    largest zoom onto the smoothed camera path frame by frame, after a rotate filter takes out the roll (only when
    the footage rolls). Returns the steadied stream's label."""
    roll = sp.rolls()
    name = f"steady{idx}.cmd"
    (cwd / name).write_text(sp.commands(f"crop@sc{idx}", seek, length, f"rotate@sr{idx}" if roll else None),
                            encoding="utf-8")
    z = sp.crop_zoom()
    chain = f"{src}sendcmd=f={name},"
    if roll:
        chain += f"rotate@sr{idx}=angle=0:ow=iw:oh=ih:c=black,"
    lines.append(f"{chain}crop@sc{idx}=w=trunc(iw/{z:.4f}/2)*2:h=trunc(ih/{z:.4f}/2)*2:exact=1[sd{idx}]")
    return f"[sd{idx}]"


def _overlay_input(ov: dict, frames: int, fps: int, width: int, height: int, idx: int,
                   label: str, cwd: Path | None = None, rel: int = 0, total: int | None = None,
                   box: tuple[int, int, int, int] | None = None) -> tuple[list[str], list[str]]:
    """(input arguments, filter lines) for one picture over the video, exactly `frames` long, fading in and out.
    `rel`/`total`: this piece starts `rel` frames into an overlay `total` frames long (an overlay cut where the
    camera under it changes), so the picture, the push-in and the fades go on where the piece before left them.
    `box`: a picture in a corner (x, y, w, h), cropped to the box and framed by a thin light border."""
    total = total or frames
    secs = frames / fps + 0.5
    if ov["kind"] == "image":
        args = ["-loop", "1", "-framerate", str(fps), "-t", f"{secs:.3f}", "-i", ov["path"]]
    else:
        args = ["-ss", f"{(ov['src_in_ms'] + rel * 1000 / fps) / 1000:.6f}", "-t", f"{secs:.3f}", "-an", "-i",
                ov["path"]]
    push = ov["motion"] == "zoom"
    tw, th = (box[2], box[3]) if box else (width, height)
    # a slow push-in is cropped from a larger frame, so it moves smoothly and never upscales the output
    w, h = (int(tw * 1.5) // 2 * 2, int(th * 1.5) // 2 * 2) if push else (tw, th)
    lines = []
    src = f"[{idx}:v]"
    if ov["fit"] == "fit" and not box:
        lines.append(f"{src}{EVEN_RANGE},split[obs{idx}][ofs{idx}]")
        lines.append(f"[obs{idx}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:2[obg{idx}]")
        lines.append(f"[ofs{idx}]scale={w}:{h}:force_original_aspect_ratio=decrease[ofg{idx}]")
        chain = f"[obg{idx}][ofg{idx}]overlay=(W-w)/2:(H-h)/2"
    else:
        chain = f"{src}scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    if push:
        chain += (f",zoompan=z='1+{OVERLAY_PUSH}*(on+{rel})/{max(1, total)}':x='iw/2-(iw/zoom/2)':"
                  f"y='ih/2-(ih/zoom/2)':d=1:s={tw}x{th}:fps={fps}")
    if ov["kind"] == "video" and cwd is not None:
        look = ov.get("grade") or {}
        chain += "," + grade.yuv_filters(ov.get("colour") or {}, look.get("grade") or grade.Grade(),
                                         look.get("denoise", ""), cwd, int((ov.get("colour") or {}).get("height") or 0))
    elif ov["kind"] == "image":
        chain += ",scale=out_color_matrix=bt709:out_range=tv"
    chain += f",fps={fps},setsar=1,settb=AVTB,setpts=PTS-STARTPTS,tpad=stop=-1:stop_mode=clone"
    if box:
        bd = multicam.border_px(width, height)
        chain += f",pad=w={tw + 2 * bd}:h={th + 2 * bd}:x={bd}:y={bd}:color={multicam.CORNER_COLOUR}"
    fade = min(round(OVERLAY_FADE_S * fps), total // 4)
    if fade > 0:
        # counted on the whole overlay's frames: the frames before this piece are stood in for, then dropped
        chain += (f"{f',tpad=start={rel}:start_mode=clone' if rel else ''},format=yuva420p,"
                  f"fade=t=in:start_frame=0:nb_frames={fade}:alpha=1,"
                  f"fade=t=out:start_frame={total - fade}:nb_frames={fade}:alpha=1"
                  f"{f',trim=start_frame={rel},setpts=PTS-STARTPTS' if rel else ''}")
    else:
        chain += ",format=yuv420p"
    lines.append(chain + label)
    return args, lines


def _encode_args(preview: bool, settings: dict | None, fps: int = 30) -> list[str]:
    # no B-frames: every piece is a closed, self-contained stream that joins by plain concatenation; a keyframe
    # every half second is what the platforms ask of an upload
    return ["-c:v", "libx264", "-preset", "ultrafast" if preview else (settings or {}).get("video_preset")
            or "veryfast", "-crf", "30" if preview else "20", "-bf", "0", "-g", str(max(1, round(fps / 2))),
            "-pix_fmt", "yuv420p"]


def _shown_at(look: dict | None, colour: dict, width: int, height: int) -> dict | None:
    """A recording's grade with its grain cleanup set for the size it is shown at: grain measured at full size
    mostly averages away when the picture is made smaller (a 360p preview, a 4K recording), so it is cleaned less."""
    if not look or not look.get("denoise"):
        return look
    big = max(int(colour.get("width") or 0), int(colour.get("height") or 0))
    scale = min(1.0, max(width, height) / big) if big else 1.0
    return {**look, "denoise": grade.denoise_for(look.get("stats"), {}, scale)}


def steadying_in_use(plan: dict, assets: dict[str, dict], cache: Path, cancelled=None) -> bool:
    """Whether the render steadies a clip (measured, cached with the pieces). FilmCraft cannot, so with the editing
    app on "auto" such a final is rendered by the built-in engine, like the preview."""
    if not steady_on(plan):
        return False
    fps = int((plan.get("output") or {}).get("fps") or 30)
    els, _overlap = frame_map(plan, fps)
    return bool(steady_plans(plan, els, assets, fps, cache, cancelled))


def retiming_in_use(plan: dict) -> bool:
    """Whether a clip of the video plays at another speed, ramps, is a freeze frame or has a camera move. FilmCraft's
    timeline carries a speed only as a constant time effect (no ramps, no room sound under a freeze, no camera
    move), so with the editing app on "auto" such a final is rendered by the built-in engine, like the preview."""
    return any(retime.retimed(c) or retime.motion_keys(c) for c in plan.get("clips") or [] if c.get("include", True))


def colour_in_use(plan: dict, assets: dict[str, dict], cache: Path | None = None, cancelled=None) -> bool:
    """Whether the plan's colour step changes the picture: a look, a phone HDR recording (always converted), or a
    correction or cleanup that the recordings really need. With `cache` (the render's pieces folder) the recordings
    are measured as the render would (a few frames each, kept), so a well-shot video with automatic colour on
    counts as unchanged; without it, automatic colour and cleanup count as in use."""
    o = color_options(plan)
    try:
        if o["look"] != "natural" and float(o["look_strength"] or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    used = {c.get("asset_id") for c in plan.get("clips") or [] if c.get("include", True)}
    used |= {ov.get("asset_id") for ov in plan.get("overlays") or []}
    used |= {aid for aid, *_ in _camera_parts(plan, assets)}
    if any(grade.hdr_kind(grade.source_colour(a["path"])) for aid, a in assets.items()
           if aid in used and a.get("kind") == "video" and a.get("path")):
        return True
    if not (o["auto_color"] or o["clean_picture"]):
        return False
    if cache is None:
        return True
    cache.mkdir(parents=True, exist_ok=True)
    return any(r["grade"].active() or r["denoise"] for r in grades(plan, assets, cache, cancelled).values())


def _grade_key(item: dict) -> dict:
    """What of a picture's colour changes its pixels (for the piece cache)."""
    look = item.get("grade") or {}
    g = look.get("grade")
    out = {}
    if g is not None and g.active():
        out["grade"] = g.key()
    if look.get("denoise"):
        out["denoise"] = look["denoise"]
    colour = item.get("colour") or {}
    if colour:
        out["matrix"] = (grade.input_matrix(colour), grade.input_range(colour))
    return out


def _timing_key(e: dict) -> dict:
    """What of an element's speed, freeze and camera move changes a piece's pixels (nothing at normal speed and
    without a move, so old cached pieces stay valid)."""
    clip = e.get("clip") or {}
    out = {}
    if retime.retimed(clip):
        ramp = retime.ramp_points(clip)  # a ramp's points are shares of the whole range: its end matters too
        out["time"] = {"speed": retime.speed(clip), "ramp": ramp, "out": int(clip["out_ms"]) if ramp else None,
                       "freeze": retime.is_freeze(clip)}
    if retime.motion_keys(clip):
        out["motion"] = {"keys": retime.motion_keys(clip), "ease": (clip.get("motion") or {}).get("ease"),
                         "frames": e.get("frames")}
    return out


def _piece(spec: dict, els: list[dict], fps: int, width: int, height: int, layout: str, kind: str | None,
           encode: list[str], ass: str, cache: Path, tmp: Path, cancelled) -> Path:
    """One piece of the picture, cached by everything that changes its pixels. `spec` may say which camera of a
    recording each element is seen from ("views"), what is in the corner ("corner") and where in its overlay the
    piece starts ("ov_rel")."""
    use = [_viewed(els[k], v) for k, v in zip(spec["els"], spec.get("views") or [None] * len(spec["els"]))]
    key_src = {"engine": ENGINE, "colour": f"bt709-v{grade.VERSION}", "rel": spec["rel"], "frames": spec["frames"],
               "w": width, "h": height, "fps": fps,
               "layout": layout, "kind": kind if len(spec["els"]) == 2 else None, "enc": encode, "ass": ass,
               "inputs": [{"kind": e["kind"], "sha": e.get("sha256", ""), "in": e["src_in_ms"],
                           "title": e.get("title", ""),
                           "layout": (e.get("clip") or {}).get("layout"),
                           **({"zoom": (e.get("clip") or {}).get("zoom")}
                              if float((e.get("clip") or {}).get("zoom") or 1.0) > 1.001 else {}),
                           **_timing_key(e),
                           **({"steady": e["steady"].key()} if e.get("steady") is not None else {}),
                           # a piece read from a proxy is never reused for the original, or the other way round
                           **({"src": "proxy"} if e.get("src") == "proxy" else {}),
                           **_grade_key(e)}
                          for e in use]}
    ov = spec.get("ov")
    box = _overlay_box(ov, width, height) if ov else None
    if ov:
        key_src["overlay"] = {**{k: ov[k] for k in ("kind", "sha", "fit", "motion", "src_in_ms")}, **_grade_key(ov)}
        if ov.get("src") == "proxy":
            key_src["overlay"]["src"] = "proxy"
        if box:
            key_src["overlay"]["box"] = list(box)
        total = ov["end_f"] - ov["start_f"]
        if spec.get("ov_rel") or spec["frames"] != total:  # a part of the overlay (old whole ones keep their key)
            key_src["overlay"].update(rel=int(spec.get("ov_rel") or 0), of=total)

    def corner_el(corner: dict) -> dict:
        base = els[corner["k"]]
        return {**_viewed(base, corner["view"]), "steady": None,
                "clip": {**(base.get("clip") or {}), "layout": "fill", "zoom": 1.0, "motion": None}}

    def corner_key(corner: dict, rel: int) -> dict:
        cel = corner_el(corner)
        return {"sha": cel.get("sha256", ""), "in": cel["src_in_ms"], "rel": rel, "box": list(corner["box"]),
                **_timing_key(cel), **({"src": "proxy"} if cel.get("src") == "proxy" else {}), **_grade_key(cel)}

    corner = spec.get("corner")
    if corner:
        key_src["corner"] = corner_key(corner, spec["rel"][spec["els"].index(corner["k"])])
    sides = spec.get("corners") or []  # a join: each side's own corner camera
    if any(sides):
        key_src["corners"] = [corner_key(c, rel) if c else None for c, rel in zip(sides, spec["rel"])]
    key = hashlib.sha256(json.dumps(key_src, sort_keys=True).encode()).hexdigest()[:32]
    out = cache / f"{key}.h264"
    if out.is_file() and out.stat().st_size > 0:
        return out
    inputs, lines = [], []
    bd = multicam.border_px(width, height)
    n = len(use)

    def put_corner(under: str, c: dict, rel: int, name: str) -> str:
        """Another camera small in a corner over `under`, on the same moment, through the clip's own speed."""
        nonlocal inputs, n
        x, y, w, h = c["box"]
        args, chain = _video_input(corner_el(c), rel, spec["frames"], fps, w, h, n, f"[c{n}]", "fill", tmp)
        inputs += args
        lines.extend(chain)
        lines.append(f"[c{n}]pad=w={w + 2 * bd}:h={h + 2 * bd}:x={bd}:y={bd}:color={multicam.CORNER_COLOUR}[cb{n}]")
        lines.append(f"{under}[cb{n}]overlay={x - bd}:{y - bd}:format=auto,format=yuv420p{name}")
        n += 1
        return name

    for k, (e, rel) in enumerate(zip(use, spec["rel"])):
        args, chain = _video_input(e, rel, spec["frames"], fps, width, height, k, f"[s{k}]", layout, tmp)
        inputs += args
        lines += chain
    side = ["[s0]", "[s1]"][:len(use)]
    for k, c in enumerate(sides):
        if c:
            side[k] = put_corner(side[k], c, spec["rel"][k], f"[sc{k}]")
    if len(use) == 2:
        lines.append(f"{side[0]}{side[1]}xfade=transition={kind}:duration={spec['frames'] / fps:.6f}:offset=0,"
                     f"fps={fps}[j]")
        last = "[j]"
    else:
        last = side[0]
    if corner:
        last = put_corner(last, corner, spec["rel"][spec["els"].index(corner["k"])], "[cr]")
    if ov:  # a picture over the video, above a camera in a corner
        args, chain = _overlay_input(ov, spec["frames"], fps, width, height, n, f"[o{n}]", tmp,
                                     rel=int(spec.get("ov_rel") or 0), total=ov["end_f"] - ov["start_f"], box=box)
        inputs += args
        lines += chain
        at = f"{box[0] - bd}:{box[1] - bd}" if box else "0:0"
        lines.append(f"{last}[o{n}]overlay={at}:format=auto,format=yuv420p[ov]")
        last = "[ov]"
        n += 1
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


def _write_tone(sample, n: int, out: Path, quiet: list[tuple[int, int]] = ()) -> Path:
    """`n` samples of room tone looped from `sample`, written block by block (sound_joins.loop_tone_blocks), so a
    long photo or silent video costs no more memory than a short one; silent over the `quiet` sample ranges (where a
    voiceover plays), with short fades around them (sound_joins.duck_gain)."""
    import numpy as np

    ramp = round(sound_joins.TONE_DUCK_MS * SR / 1000)
    at = 0
    with open(out, "wb") as fh:
        for block in sound_joins.loop_tone_blocks(sample, n, SR):
            gain = sound_joins.duck_gain(at, len(block), list(quiet), ramp) if quiet else None
            fh.write(np.asarray(block if gain is None else block * gain, dtype="<f4").tobytes())
            at += len(block)
    return out


def _one_pass(path: str, out: Path, cancelled) -> int:
    """One pass of a sound file decoded through the mix's chain to raw samples; returns how many. Looping music
    repeats exactly this: FFmpeg's own looping of an AAC or MP3 file drifts by the encoder's padding on every repeat
    until the resampler pads in about 0.1 s of silence every few repeats, which left gaps in long music and put a
    back-timed ending off the last frame."""
    run(["-i", str(path), "-vn", "-map", "0:a:0", "-af", NORMALISE, "-f", "f32le", "-ac", "2", "-ar", str(SR),
         str(out)], cancel=cancelled, cwd=out.parent)
    return out.stat().st_size // 8


def _retimed_sound(e: dict, rel0: int, n: int, sound: list[str], chain: str, out: Path, cancelled) -> Path:
    """`n` samples of a sped-up, slowed or ramped element's own sound from `rel0` output samples after its start
    (negative: a lead-in before it), on the same time map as its picture (retime): the file range those samples
    show is decoded at normal speed, then time-stretched with the pitch kept. Past either end of the clip its edge
    speed continues (crossfade margins). The clip's own fades are applied to the result, in video time."""
    import numpy as np

    clip = e["clip"]
    first = e["src_in_ms"] * SR / 1000

    def position(j):
        return first + retime.src_positions(clip, (np.asarray(j, dtype=np.float64) + rel0) * 1000 / SR) * SR / 1000
    lo, hi = position([0.0, float(n)])
    margin = retime.WSOLA_FRAME + retime.WSOLA_TOL + SR // 10
    a0 = max(0, int(math.floor(lo)) - margin)
    m = max(1, int(math.ceil(hi)) + margin - a0)
    src = _raw_audio(["-ss", f"{a0 / SR:.6f}", "-t", f"{m / SR + 0.5:.6f}", *sound], chain, m,
                     out.with_suffix(".src.raw"), cancelled)
    try:
        _check(cancelled)
        ms = SR / 1000
        retime.stretch(src, m, n, lambda j: position(j) - a0, out,
                       round(int(clip.get("fade_in_ms") or 0) * ms), round(int(clip.get("fade_out_ms") or 0) * ms))
    finally:
        src.unlink(missing_ok=True)
    return out


def _own_sound(els: list[dict], assets: dict[str, dict], src_track: dict) -> list[bool]:
    """Which picture elements bring their own sound (a video with sound, not muted, the source track on)."""
    out = []
    for e in els:
        clip = e.get("clip") or {}
        a = assets.get(e["asset_id"]) if e["kind"] == "video" else None
        out.append(bool(a and (a.get("probe") or {}).get("has_audio") and not clip.get("mute")
                        and not src_track.get("mute")))
    return out


def _back_timed(item: dict, place: dict, total_ms: int, assets: dict[str, dict]) -> bool:
    """A repeating music item that plays to the video's end and is set to end on its last frame (sound_joins)."""
    return (item["role"] == "music" and bool(place["loop"]) and place["out_end_ms"] >= total_ms - 1
            and sound_joins.back_times(item, (assets.get(item["asset_id"]) or {}).get("filename", "")))


def _voiceovers(placed: list[dict], items: dict[str, dict], tracks: dict) -> list[tuple[float, float]]:
    """Where a voiceover plays (ms): room tone steps aside there (the narration brings its own room; another one
    under it is only noise)."""
    return [(p["out_start_ms"], p["out_end_ms"]) for p in placed
            if items[p["audio_id"]]["role"] == "voiceover" and not items[p["audio_id"]].get("mute")
            and not (tracks.get(p["track"]) or {}).get("mute")]


def _narrated(els: list[dict], spans: list[tuple[float, float]], fps: int) -> set[int]:
    """Elements a voiceover covers from end to end (all but less than a frame): they get no room tone at all. One
    a voiceover only reaches into keeps its tone outside the voiceover (_write_tone's quiet ranges)."""
    return {k for k, e in enumerate(els)
            if sound_joins.uncovered_ms(e["start_f"] * 1000 / fps, e["end_f"] * 1000 / fps, spans) < 1000 / fps}


def sound_joins_in_use(plan: dict, assets: dict[str, dict], words_by_asset: dict[str, list[dict]],
                       report: dict | None = None) -> bool:
    """Whether the built-in engine's sound joins (sound_joins.py) shape this video's sound: a straight cut between
    two recordings with sound (always a crossfade, maybe a split edit), room tone under a title, photo or silent
    video, or a back-timed music bed. FilmCraft's timeline has none of them, so with the editing app on "auto" such
    a final is rendered by the built-in engine, like the preview (video_flow._craft_render). `report` is a render's
    own account of this plan (its info["sound_joins"], from the preview of the same version): whether room tone
    was found and the music moved is only known by measuring, so it decides those. Without one, any element that
    could get room tone or any bed that could be moved counts."""
    fps = int((plan.get("output") or {}).get("fps") or 30)
    els, _ = frame_map(plan, fps)
    tracks = {**default_tracks(), **(plan.get("tracks") or {})}
    own = _own_sound(els, assets, tracks["source"])
    if any(own[k - 1] and own[k] and not els[k]["ov_in"] and els[k - 1]["asset_id"] != els[k]["asset_id"]
           for k in range(1, len(els))):
        return True
    if report is not None:
        return bool(report.get("room_tone_s") or report.get("split_edits")
                    or any((report.get("music_back_timed_s") or {}).values()))
    items = {i["id"]: i for i in plan.get("audio") or []}
    total_ms = round(duration_ms(plan))
    placed = audio_timeline(plan, None, total_ms)
    narrated = _narrated(els, _voiceovers(placed, items, tracks), fps)
    if any(own) and any(words_by_asset.get(els[i]["asset_id"]) is not None for i in range(len(els)) if own[i]) \
            and any(not own[k] and k not in narrated and not (e.get("clip") or {}).get("mute") and e["frames"] > 0
                    for k, e in enumerate(els)):
        return True
    return any(_back_timed(items[p["audio_id"]], p, total_ms, assets) for p in placed
               if not (tracks.get(p["track"]) or {}).get("mute"))


def _room_tones(els: list[dict], own: list[bool], assets: dict[str, dict], words_by_asset: dict[str, list[dict]],
                source_sound, tmp: Path, track_gain_db: float, narrated: set[int] | None = None,
                cancelled=None) -> dict[int, "np.ndarray"]:
    """{element index: room-tone sample} for each title card, photo or video without sound (not a muted clip: the
    owner asked for silence there; not under a voiceover), taken from the nearest recording that has its own sound
    (sound_joins.py), at the volume that recording plays at (its clip's and the source track's)."""
    import numpy as np

    samples: dict[str, "np.ndarray | None"] = {}

    def sample(k: int) -> "np.ndarray | None":
        e = els[k]
        aid = e["asset_id"]
        if aid in samples:
            return samples[aid]
        samples[aid] = None
        words = words_by_asset.get(aid)
        if words is None:
            return None
        best = None
        for j, (a, b) in enumerate(sound_joins.tone_candidates(words, _length(assets[aid]) / 1000)):
            _check(cancelled)
            n = int((b - a) * SR)
            path = _raw_audio(["-ss", f"{a:.6f}", "-t", f"{b - a + 0.5:.6f}", *source_sound(e, assets[aid])],
                              NORMALISE, n, tmp / f"tone-{aid}-{j}.raw", cancelled)
            x = np.fromfile(path, dtype="<f4").reshape(-1, 2)
            path.unlink(missing_ok=True)
            level = sound_joins.level_db(x)
            if sound_joins.usable_tone(level) and (best is None or level < best[0]):
                best = (level, x)
        samples[aid] = best[1] if best else None
        return samples[aid]
    out = {}
    for k, e in enumerate(els):
        if own[k] or (e.get("clip") or {}).get("mute") or e["frames"] <= 0 or k in (narrated or ()):
            continue
        near = sorted((i for i in range(len(els)) if own[i]), key=lambda i: (abs(i - k), i > k))
        for i in near[:2]:
            x = sample(i)
            if x is not None:  # the level was judged as recorded; it plays as loud as that recording does
                gain = float((els[i].get("clip") or {}).get("gain_db") or 0) + track_gain_db
                out[k] = x * np.float32(10 ** (gain / 20))
                break
    return out


def mix(total: int, parts: list[dict], out: Path, cancelled=None) -> None:
    """Sum raw stereo parts into one bus of `total` samples, block by block (each part: start, n, path and optional
    ramp lengths at its edges, which make an exact crossfade with a neighbour's opposite ramp: a straight line, or
    equal power with `power_in`/`power_out`). A part may start before 0 or end after `total`: only what falls
    inside is heard."""
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
                        for key, x in (("in", pos / p["ramp_in"] if p.get("ramp_in") else None),
                                       ("out", (p["n"] - pos) / p["ramp_out"] if p.get("ramp_out") else None)):
                            if x is not None:  # equal power for two unrelated sounds, else a straight line
                                x = np.clip(x, 0.0, 1.0)
                                g = np.minimum(g, np.sin(x * (np.pi / 2)) if p.get(f"power_{key}") else x)
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


def _post(gain_db: float | None, measure: bool, trim_db: float = 0.0,
          ceiling_dbfs: float = loudness.LIMIT_DBFS) -> str:
    """The mix's last steps: measured (ebur128), or its constant gain (plus `trim_db`, the check's correction)
    and the 4x-oversampled limiter at `ceiling_dbfs` (pipeline/loudness.py)."""
    post = ["aformat=sample_fmts=dbl:sample_rates=48000:channel_layouts=stereo"]
    if measure:
        post.append(loudness.FILTER)
    else:
        if gain_db is not None or trim_db:
            post.append(f"volume={(gain_db or 0.0) + trim_db:.6f}dB:precision=double")
        post += [*loudness.limiter(ceiling_dbfs), "asettb=1/48000", "asetpts=N/SR/TB"]
    return ",".join(post)


def _raw_input(path: Path) -> list[str]:
    return ["-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(path)]


def _measure(mixed: Path, total_s: float, work: Path, cancelled) -> dict:
    """The whole mix's loudness and true peak (ebur128) and the constant gain to -14 LUFS that keeps its true peak
    at -1.5 dBTP or under ({lufs, tp, lra, gain_db, held}: what held the gain short, see loudness.gain_for);
    silence gets no gain."""
    result = run_process([ffmpeg_bin(), "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info",
                          *_raw_input(mixed), "-filter_complex", f"[0:a]{_post(None, True)}[aout]",
                          "-map", "[aout]", "-f", "null", "-"],
                         timeout=max(120.0, total_s * 6), cancel=cancelled, cwd=str(work))
    if result.returncode:
        raise FFmpegError("Could not measure the video's audio: " +
                          result.stderr.decode("utf-8", "replace")[-400:])
    try:
        got = loudness.parse(result.stderr)
    except ValueError:
        got = {"lufs": None, "tp": None, "lra": 0.0}
    gain, held = loudness.gain_for(got["lufs"], got["tp"], min_db=-24.0)
    return {**got, "gain_db": gain, "held": held}


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
    use_proxies = preview and bool((settings or {}).get("preview_proxies", True))
    proxied: list[str] = []  # the assets whose proxy stood in for the original (previews only)
    for e in els:
        if e["kind"] == "title":
            e["title"] = plan["title"]["text"]
        else:
            a = assets[e["asset_id"]]
            picture = _picture_source(a, use_proxies)
            # the picture may come from the proxy; the sound always comes from the original
            e.update(path=picture, sound_path=a["path"], sha256=a.get("sha256", ""),
                     src="proxy" if picture != a["path"] else "original")
    overlays = _overlay_frames(plan, els, fps, assets, use_proxies)
    looks = grades(plan, assets, cache, cancelled)
    for item in [e for e in els if e["kind"] in ("video", "freeze")] + \
            [o for items in overlays.values() for o in items if o["kind"] == "video"]:
        # the original's colour tags: a proxy is a smaller copy of the same picture and keeps its matrix and
        # transfer (its range is limited whatever the original's: the filters read the range from each frame)
        item["colour"] = grade.source_colour(assets[item["asset_id"]]["path"])
        item["grade"] = _shown_at(looks.get(item["asset_id"]), item["colour"], width, height)
    steadied = steady_plans(plan, els, assets, fps, cache, cancelled)
    for k, sp in steadied.items():
        els[k]["steady"] = sp
    colours: dict[str, tuple[dict, dict | None]] = {}

    def look_of(aid: str) -> tuple[dict, dict | None]:
        """A recording's colour tags and its grade at the size it is shown (each probed once)."""
        if aid not in colours:
            colour = grade.source_colour(assets[aid]["path"])
            colours[aid] = (colour, _shown_at(looks.get(aid), colour, width, height))
        return colours[aid]
    cams = _camera_frames(plan, els, fps, assets, use_proxies, width, height, look_of)
    viewed = [v for rows in cams.values() for r in rows for v in (r["view"], (r["corner"] or {}).get("view")) if v]
    for aid in [e["asset_id"] for e in els if e.get("src") == "proxy"] + \
            [o["asset_id"] for items in overlays.values() for o in items if o["src"] == "proxy"] + \
            [v["asset_id"] for v in viewed if v["src"] == "proxy"]:
        if aid not in proxied:
            proxied.append(aid)
    total_f = els[-1]["end_f"]
    total_s = total_f / fps
    segs = render_timeline(plan, fps)
    words = output_words(plan, words_by_asset, segs)
    captions = plan.get("captions") or {}
    events = ((highlight_events if captions.get("highlight") else caption_events)(words, captions)
              if captions.get("enabled") and words else [])
    trans = TRANSITIONS.get((plan.get("transition") or {}).get("type", "cut"))
    layout = plan.get("layout") or "fit"
    encode = _encode_args(preview, settings, fps)
    try:
        # ---- picture: bodies and joins, each a separate small FFmpeg run, cached by content
        def seen(k: int, f: int) -> dict:
            """The camera stretch of element k at output frame f (empty: the recording's own picture)."""
            return next((r for r in cams.get(k) or [] if r["f0"] <= f < r["f1"]), {})
        specs = []
        for k, e in enumerate(els):
            head = e["ov_in"]
            tail = els[k + 1]["ov_in"] if k + 1 < len(els) else 0
            b0, b1 = e["start_f"] + head, e["end_f"] - tail
            if b1 > b0:  # the body, cut at the edges of its overlays and where the camera changes
                mine = overlays.get(k) or []
                cuts = sorted({b0, b1, *(x for o in mine for x in (o["start_f"], o["end_f"]) if b0 < x < b1),
                               *(r["f0"] for r in cams.get(k) or [] if b0 < r["f0"] < b1)})
                for a, b in zip(cuts, cuts[1:]):
                    ov = next((o for o in mine if o["start_f"] <= a and b <= o["end_f"]), None)
                    s = seen(k, a)
                    specs.append({"els": [k], "rel": [a - e["start_f"]], "frames": b - a, "at": a, "ov": ov,
                                  "ov_rel": a - ov["start_f"] if ov else 0, "views": [s.get("view")],
                                  "corner": s.get("corner")})
            if tail:
                s0, s1 = seen(k, e["end_f"] - tail), seen(k + 1, els[k + 1]["start_f"])
                specs.append({"els": [k, k + 1], "rel": [e["frames"] - tail, 0], "frames": tail,
                              "at": e["end_f"] - tail, "views": [s0.get("view"), s1.get("view")],
                              # each side's corner camera comes and goes with its own side of the dissolve or fade
                              **({"corners": [s0.get("corner"), s1.get("corner")]}
                                 if s0.get("corner") or s1.get("corner") else {})})
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
        clean_mode = plan.get("clean_sound") or (settings or {}).get("clean_sound") or "off"
        cleaned: dict[str, cleanup.Result] = {}

        def source_sound(e: dict, a: dict) -> list[str]:
            """Input options for an element's own sound, always from the original file (a preview's picture may
            come from a proxy): the asset's cleaned-up sound when there is one."""
            sound = e.get("sound_path") or e["path"]
            if clean_mode == "off" or clean_mode not in cleanup.MODES:
                return ["-i", sound]
            aid = e["asset_id"]
            if aid not in cleaned:  # the whole file once (cached), so every cut and preview reuses it
                cleaned[aid] = cleanup.clean_or_keep(sound, 0.0, _length(a) / 1000,
                                                     words_by_asset.get(aid) or [], clean_mode, cancelled=cancelled)
            r = cleaned[aid]
            return r.input_args() if r.path is not None else ["-i", sound]
        items = {i["id"]: i for i in plan.get("audio") or []}
        placed = audio_timeline(plan, segs, round(total_s * 1000))
        # which elements bring their own sound; the rest get the nearest recording's room tone (sound_joins.py),
        # except under a voiceover
        own = _own_sound(els, assets, src_track)
        lengths = {aid: _length(a) for aid, a in assets.items() if a.get("kind") == "video"}
        splits = sound_joins.split_edits(els, own, words_by_asset, lengths, fps)
        voiced = _voiceovers(placed, items, tracks)
        tones = _room_tones(els, own, assets, words_by_asset, source_sound, tmp, float(src_track.get("gain_db") or 0),
                            _narrated(els, voiced, fps), cancelled) if not src_track.get("mute") else {}
        heard = [own[k] or k in tones for k in range(len(els))]
        xf = round(sound_joins.SCENE_XFADE_MS * SR / 1000)

        def faded(k: int, edge: str) -> int:
            """Samples of element k's own sound fade at its start or end ("in"/"out"), 0 without one."""
            return round(int((els[k].get("clip") or {}).get(f"fade_{edge}_ms") or 0) * SR / 1000) if own[k] else 0
        # room tone next to a recording whose own sound fades there runs on under that fade and fades the other way
        # (no dip to silence and back): {element k: samples it starts early / ends late}
        tone_lead = {k: faded(k - 1, "out") for k in tones if k and not els[k]["ov_in"] and faded(k - 1, "out")}
        tone_tail = {k: faded(k + 1, "in") for k in tones
                     if k + 1 < len(els) and not els[k + 1]["ov_in"] and faded(k + 1, "in")}
        # each straight cut between two different sounds (recordings, or room tone) gets an equal-power crossfade
        # around its sound edit: (samples before it, samples after it, ramp length) for the cut into element k
        xfades: dict[int, tuple[int, int, int]] = {}
        straight: set[int] = set()  # joins crossfaded in a straight line (the same sound on both sides)
        for k in range(1, len(els)):
            p_c, q_c = els[k - 1].get("clip") or {}, els[k].get("clip") or {}
            if own[k - 1] and own[k] and els[k - 1]["asset_id"] == els[k]["asset_id"] and not els[k]["ov_in"] and \
                    int(p_c.get("out_ms", -1)) == int(q_c.get("in_ms", -2)) and \
                    (retime.retimed(p_c) or retime.retimed(q_c)):
                # one recording going on across a split, faster or slower on one side: a stretched sound ends up to
                # 8 ms off its map (retime.stretch), so the two sides meet with a short straight-line crossfade, each
                # reaching into the other's own sound (the same moments of the file, so no word is cut or doubled)
                xfades[k] = (xf // 2, xf - xf // 2, xf)
                straight.add(k)
                continue
            if els[k]["ov_in"] or not (heard[k - 1] and heard[k]) or \
                    (own[k - 1] and own[k] and els[k - 1]["asset_id"] == els[k]["asset_id"]) or \
                    k in tone_lead or k - 1 in tone_tail:
                continue
            lead, lag = splits.get(k, (0, 0))
            shift = (lag - lead) / fps
            p_e, q_e = els[k - 1], els[k]
            # a side may reach past its own edge only into room sound (never a cut-out word); a split edit is
            # clear of words by construction, room tone always. A sped-up or slowed side reaches its edge speed
            # times as far into its file.
            p_c, q_c = p_e.get("clip") or {}, q_e.get("clip") or {}
            p_end = p_e["src_in_ms"] + retime.src_at(p_c, p_e["frames"] * 1000 / fps)
            p_far, q_far = xf / SR * retime.edge_speeds(p_c)[1], xf / SR * retime.edge_speeds(q_c)[0]
            after = k in splits or not own[k - 1] or sound_joins.clear(
                words_by_asset.get(p_e["asset_id"]), p_end / 1000 + shift, p_far,
                lengths.get(p_e["asset_id"], 0) / 1000)
            before = k in splits or not own[k] or sound_joins.clear(
                words_by_asset.get(q_e["asset_id"]), q_e["src_in_ms"] / 1000 + shift - q_far, q_far,
                lengths.get(q_e["asset_id"], 0) / 1000)
            xfades[k] = (xf // 2, xf - xf // 2, xf) if before and after else (0, xf, xf) if after else \
                (xf, 0, xf) if before else (0, 0, xf // 2)  # neither: a quick dip, like a jump cut's
        for k, e in enumerate(els):
            if not heard[k]:
                continue
            _check(cancelled)
            lead, lag = splits.get(k, (0, 0))              # this element's start: J lead or L lag (frames)
            n_lead, n_lag = splits.get(k + 1, (0, 0))       # its end: the next one's J lead or L lag
            x_in, x_out = xfades.get(k), xfades.get(k + 1)
            start = (e["start_f"] - lead + lag) * spf - (x_in[0] if x_in else 0) - tone_lead.get(k, 0)
            end = (e["end_f"] - n_lead + n_lag) * spf + (x_out[1] if x_out else 0) + tone_tail.get(k, 0)
            n = end - start
            if own[k]:
                clip = e.get("clip") or {}
                a = assets[e["asset_id"]]
                gain = float(clip.get("gain_db") or 0) + float(src_track.get("gain_db") or 0)
                if retime.retimed(clip):  # faster or slower, the voice at its own pitch (retime.stretch)
                    raw = _retimed_sound(e, start - e["start_f"] * spf, n, source_sound(e, a),
                                         f"{NORMALISE},volume={gain:.2f}dB", tmp / f"el{k}.raw", cancelled)
                else:
                    src = e["src_in_ms"] * SR // 1000 + (start - e["start_f"] * spf)  # the source sample at `start`
                    skip = max(0, -src)  # before the file's start (a crossfade at its very first sample): silence
                    raw = _raw_audio(["-ss", f"{max(0, src) / SR:.6f}", "-t", f"{(n - skip) / SR + 0.5:.6f}",
                                      *source_sound(e, a)],
                                     f"{NORMALISE},volume={gain:.2f}dB" + (f",adelay={skip}S:all=1" if skip else "")
                                     + _fades(int(clip.get("fade_in_ms") or 0), int(clip.get("fade_out_ms") or 0),
                                              n / SR), n, tmp / f"el{k}.raw", cancelled)
                bus = speech
            else:  # silent where a voiceover plays
                quiet = [(round(a * SR / 1000) - start, round(b * SR / 1000) - start) for a, b in voiced
                         if round(b * SR / 1000) > start and round(a * SR / 1000) < end]
                raw = _write_tone(tones[k], n, tmp / f"tone{k}.raw", quiet)
                bus = free  # never counted as speech (it would hold the music down)
            bus.append({"start": start, "n": n, "path": raw,
                        "ramp_in": x_in[2] if x_in else tone_lead.get(k) or e["ov_in"] * spf,
                        "power_in": bool(x_in) and k not in straight,
                        "ramp_out": x_out[2] if x_out else tone_tail.get(k) or
                        (els[k + 1]["ov_in"] if k + 1 < len(els) else 0) * spf,
                        "power_out": bool(x_out) and k + 1 not in straight})
            if not own[k] and k == 0:
                bus[-1].update(ramp_in=xf, power_in=True)  # room tone under an opening title fades in
            if not own[k] and k == len(els) - 1:
                bus[-1].update(ramp_out=xf, power_out=True)
        joins_report = {"split_edits": [{"at_s": round(els[k]["start_f"] / fps, 3), "j_frames": ld, "l_frames": lg}
                                        for k, (ld, lg) in sorted(splits.items())],
                        "room_tone_s": round(sum(sound_joins.uncovered_ms(els[k]["start_f"] * 1000 / fps,
                                                                          els[k]["end_f"] * 1000 / fps, voiced)
                                                 for k in tones) / 1000, 2)}
        back_timed: dict[str, float] = {}
        passes: dict[str, tuple[Path, int]] = {}  # looping music: one decoded pass per file, repeated exactly
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
            skip = 0
            if place["loop"]:  # one decoded pass, repeated sample for sample (_one_pass)
                if path not in passes:
                    one = tmp / f"pass{len(passes)}.raw"
                    passes[path] = (one, _one_pass(path, one, cancelled))
                one, per = passes[path]
                if per <= 0:
                    continue
                args, chain = ["-stream_loop", "-1", *_raw_input(one)], "asetpts=N/SR/TB"
                if _back_timed(item, place, round(total_s * 1000), assets):
                    # back-timed: started so its own end (a bed's last whole bar, a song's ending) lands on the
                    # video's last frame (sound_joins.py)
                    skip = sound_joins.back_time_offset(n, per)
                    if skip:
                        back_timed[item["id"]] = round(skip / SR, 3)
            else:
                args, chain = ["-ss", f"{place['src_in_ms'] / 1000:.6f}", "-t", f"{n / SR + 0.5:.6f}", "-i", path], \
                    NORMALISE
            fade_in = int(item.get("fade_in_ms") or 0)
            if skip:  # it now starts inside the music: never on a hard edge
                fade_in = max(fade_in, sound_joins.BACK_TIME_FADE_IN_MS)
            raw = _raw_audio(args, chain + (f",atrim=start_sample={skip},asetpts=PTS-STARTPTS" if skip else "")
                             + f",volume={gain:.2f}dB" + _fades(fade_in, int(item.get("fade_out_ms") or 0), n / SR), n,
                             tmp / f"item{k}.raw", cancelled)
            part = {"start": start, "n": n, "path": raw}
            if item["role"] == "voiceover":
                speech.append(part)
            elif item.get("duck"):
                ducked.append(part)
            else:
                free.append(part)
        for one, _ in passes.values():
            one.unlink(missing_ok=True)
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
        level = _measure(mixed, total_s, tmp, cancelled)
        gain = level["gain_db"]
        report(0.88)

        # ---- the file: joined picture (stream copy) and the mixed, normalised sound
        tmp_out = out_path.with_suffix(".tmp.mp4")

        def mux(trim_db: float, ceiling: float, lo: float, hi: float) -> None:
            run(["-f", "h264", "-framerate", str(fps), "-i", str(joined), *_raw_input(mixed),
                 "-filter_complex", f"[1:a]{_post(gain, False, trim_db, ceiling)}[aout]", "-map", "0:v",
                 "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-profile:a", "aac_low",
                 "-b:a", "128k" if preview else "256k", "-ac", "2", "-ar", "48000", "-movflags", "+faststart",
                 "-t", f"{total_s:.6f}", str(tmp_out)],
                duration=total_s, progress=lambda f: report(lo + (hi - lo) * f), cancel=cancelled, cwd=work)
        mux(0.0, loudness.LIMIT_DBFS, 0.88, 0.95)
        # the finished file's sound is measured; a missed level or a peak the encoder pushed over -1 dBTP gets the
        # sound made once more (the picture is copied again, the mix is still on disk)
        expected = level["lufs"] + gain if level["lufs"] is not None else None
        out = loudness.measure(tmp_out, cancelled, max(60.0, total_s * 3))
        verdict = loudness.check(out, expected, normalized=True, held=level["held"])
        fixed, ceiling = verdict["fix_db"], verdict["ceiling_dbfs"]
        if fixed or verdict["lower_ceiling"]:
            mux(fixed, ceiling, 0.95, 0.99)
            out = loudness.measure(tmp_out, cancelled, max(60.0, total_s * 3))
            verdict = loudness.check(out, None if expected is None else expected + fixed, normalized=True,
                                     held=level["held"])
        sound = {"status": verdict["status"], "note": verdict["note"], **out, "expected_lufs": expected,
                 "fixed_db": fixed, "source_lufs": level["lufs"], "source_tp": level["tp"],
                 "peak_limited": level["held"] == "peaks", "boost_capped": level["held"] == "cap",
                 **({"ceiling_dbfs": ceiling} if ceiling != loudness.LIMIT_DBFS else {})}
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
            "qc": {"version": 1, "sound": sound},
            "timeline": segs, "audio_timeline": placed, "ducking": ducking, "words": words,
            "sound_joins": {**joins_report, "music_back_timed_s": back_timed},
            "overlays": [{"overlay_id": o["id"], "start_f": o["start_f"], "end_f": o["end_f"]}
                         for k in sorted(overlays) for o in overlays[k]],
            "captions": bool(events), "clean_sound": {aid: r.report for aid, r in cleaned.items()},
            "colour": {aid: {**r["grade"].summary(), "denoise": bool(r["denoise"])} for aid, r in looks.items()},
            "steady": {els[k]["clip_id"]: sp.summary(_clip_seconds(els[k].get("clip") or {}))
                       for k, sp in steadied.items()},
            "pieces": len(used), "frames": total_f, "proxied": proxied}

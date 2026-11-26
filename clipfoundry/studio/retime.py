"""Speed changes, speed ramps, freeze frames and slow camera moves for the full-video engine (editing upgrade batch
4, docs/clipforge/RANGE_EDITING.md).

A clip's own time map. Its source range [in_ms, out_ms] plays at `speed` (0.25 to 4, the voice keeps its pitch), or
follows `speed_ramp`: points {at: share of the source range from 0 to 1, speed}, eased smoothly from one to the next.
A freeze clip (kind "freeze") holds the frame at in_ms of a video for hold_ms; it has no sound of its own, so it gets
the room tone of the recording around it like a photo does.

The map is reckoned on the time each source millisecond takes on screen (1 / speed), eased with smoothstep between
points. That has a closed-form integral, so the picture (an FFmpeg setpts expression), the sound (a WSOLA
time-stretch driven by this same map, sample exact) and the captions follow one map, and a clip at speed 1 maps every
time to itself (old plans are untouched).

`motion` is a slow camera move over a clip, photo or freeze frame: keys {at: share of the clip's length, zoom 1 to
1.5, x and y: the centre of the framing as a share of the picture}, eased. It is drawn with FFmpeg's perspective
filter evaluated per frame, so it moves smoothly by fractions of a pixel (crop moves in whole pixels and its size is
fixed for a run; zoompan jitters).
"""
from __future__ import annotations

import math
from pathlib import Path

SPEED_RANGE = (0.25, 4.0)
RAMP_POINTS = (2, 8)
FREEZE_MIN_MS = 200
FREEZE_DEFAULT_MS = 2000
MOTION_ZOOM = (1.0, 1.5)
MOTION_KEYS = (2, 6)
EASES = ("smooth", "linear")

# speed ramp presets: (label, points as (share of the source range, speed))
RAMPS = {
    "slow_middle": ("Slow motion in the middle", ((0.0, 1.0), (0.3, 0.35), (0.7, 0.35), (1.0, 1.0))),
    "fast_slow_fast": ("Fast, slow, fast", ((0.0, 2.0), (0.4, 0.4), (0.6, 0.4), (1.0, 2.0))),
    "slow_down": ("Slow down to the end", ((0.0, 1.0), (1.0, 0.35))),
    "speed_up": ("Speed up to the end", ((0.0, 1.0), (1.0, 2.5))),
}
# slow camera move presets: (label, start key, end key) with keys (zoom, x, y)
MOTIONS = {
    "zoom_in": ("Slow zoom in", (1.0, 0.5, 0.5), (1.2, 0.5, 0.5)),
    "zoom_out": ("Slow zoom out", (1.2, 0.5, 0.5), (1.0, 0.5, 0.5)),
    # at 1.2 the framing is 83% of the picture: its centre can travel from 0.42 to 0.58 (edge to edge)
    "pan_left": ("Pan left", (1.2, 0.58, 0.5), (1.2, 0.42, 0.5)),
    "pan_right": ("Pan right", (1.2, 0.42, 0.5), (1.2, 0.58, 0.5)),
    "pan_up": ("Pan up", (1.2, 0.5, 0.58), (1.2, 0.5, 0.42)),
    "pan_down": ("Pan down", (1.2, 0.5, 0.42), (1.2, 0.5, 0.58)),
}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def ramp_value(name: str) -> dict:
    """A preset ramp as it is stored on a clip."""
    return {"preset": name, "points": [{"at": a, "speed": s} for a, s in RAMPS[name][1]]}


def motion_value(name: str, ease: str = "smooth") -> dict:
    """A preset camera move as it is stored on a clip."""
    _label, a, b = MOTIONS[name]
    return {"preset": name, "ease": ease, "keys": [{"at": 0.0, "zoom": a[0], "x": a[1], "y": a[2]},
                                                   {"at": 1.0, "zoom": b[0], "x": b[1], "y": b[2]}]}


def is_freeze(c: dict) -> bool:
    return c.get("kind") == "freeze"


def frame_ms_of(asset: dict | None) -> float:
    """How long one frame of a video file lasts (ms), from its probed frame rate (30 fps when unknown)."""
    fps = ((asset or {}).get("probe") or {}).get("fps")
    return 1000.0 / float(fps) if _num(fps) and fps > 0 else 1000.0 / 30


def last_frame_ms(asset: dict | None, frame_ms: float | None = None) -> float | None:
    """When a video's last frame starts (ms into the file), or None when its length is unknown. The picture
    stream's own length counts: a phone or camera file's sound often runs on a little past its last frame."""
    p = (asset or {}).get("probe") or {}
    length = p.get("video_duration") if _num(p.get("video_duration")) and p["video_duration"] > 0 else p.get("duration")
    if not _num(length) or length <= 0:
        return None
    return max(0.0, float(length) * 1000 - (frame_ms or frame_ms_of(asset)))


def frame_start_ms(asset: dict | None, at_ms: float) -> float:
    """The start of the frame on screen at `at_ms` in a video file (its frames start on a regular grid from 0), no
    later than the last frame."""
    fm = frame_ms_of(asset)
    start = math.floor(max(0.0, at_ms) / fm + 1e-6) * fm
    last = last_frame_ms(asset, fm)
    if last is not None:
        start = min(start, math.floor(last / fm + 1e-6) * fm)
    return start


def ramp_points(c: dict) -> list[tuple[float, float]] | None:
    r = c.get("speed_ramp")
    pts = r.get("points") if isinstance(r, dict) else None
    if not pts:
        return None
    try:
        return [(float(p["at"]), float(p["speed"])) for p in pts]
    except (KeyError, TypeError, ValueError):
        return None


def speed(c: dict) -> float:
    """The clip's constant speed (1 for a ramp, a freeze or no speed)."""
    s = c.get("speed", 1)
    return float(s) if _num(s) and s > 0 and not ramp_points(c) and not is_freeze(c) else 1.0


def retimed(c: dict) -> bool:
    """Whether the clip does not play at normal speed (a speed, a ramp or a freeze)."""
    return is_freeze(c) or bool(ramp_points(c)) or abs(speed(c) - 1.0) > 1e-9


def motion_keys(c: dict) -> list[dict] | None:
    m = c.get("motion")
    keys = m.get("keys") if isinstance(m, dict) else None
    return keys or None


def ramp_range(c: dict) -> tuple[float, float] | None:
    """The file range [in, out] (ms) a speed ramp is drawn over when it is not the clip's own: kept by a split, so
    each half plays its part of the same curve, and by a trim, so the curve stays where it was in the file."""
    r = c.get("speed_ramp")
    rng = r.get("range") if isinstance(r, dict) else None
    if isinstance(rng, (list, tuple)) and len(rng) == 2 and all(_num(v) for v in rng) and rng[1] > rng[0]:
        return float(rng[0]), float(rng[1])
    return None


def _seg_out(seg, u: float) -> float:
    a, b, r0, r1, o = seg
    if b <= a:
        return o
    v = (u - a) / (b - a)
    return o + (b - a) * (r0 * v + (r1 - r0) * (v ** 3 - v ** 4 / 2))


def _seg_rate(seg, u: float) -> float:
    a, b, r0, r1, _o = seg
    v = 0.0 if b <= a else min(1.0, max(0.0, (u - a) / (b - a)))
    return r0 + (r1 - r0) * v * v * (3 - 2 * v)


def _segments(c: dict) -> tuple[list[tuple[float, float, float, float, float]], float]:
    """([(source start, source end, rate at start, rate at end, output start)] in ms from the in point, output
    length in ms), where rate = 1 / speed. Only the segments the clip plays are listed; the first may start before
    the in point and the last end after the out point (a clip playing part of its ramp's range). Where the clip
    reaches past its ramp's range, the edge speed goes on."""
    length = float(int(c["out_ms"]) - int(c["in_ms"]))
    rng = ramp_range(c)
    off, span = (int(c["in_ms"]) - rng[0], rng[1] - rng[0]) if rng else (0.0, length)
    pts = ramp_points(c) or [(0.0, speed(c)), (1.0, speed(c))]
    knots = [(p * span - off, 1.0 / s) for p, s in pts]
    if knots[0][0] > 0:
        knots.insert(0, (0.0, knots[0][1]))
    if knots[-1][0] < length:
        knots.append((length, knots[-1][1]))
    full, o = [], 0.0
    for (a, r0), (b, r1) in zip(knots, knots[1:]):
        full.append((a, b, r0, r1, o))
        o += (b - a) * (r0 + r1) / 2
    at0 = next(s for s in full if s[1] >= 0 or s is full[-1])
    shift = _seg_out(at0, 0.0)  # the curve's output at the in point: the clip starts there
    segs = [(a, b, r0, r1, so - shift) for a, b, r0, r1, so in full if b > 0 and a < length and b > a]
    if not segs:  # a zero-length range (never valid): one flat piece so nothing divides by zero
        segs = [(0.0, max(length, 1e-6), 1.0, 1.0, 0.0)]
    return segs, _seg_out(segs[-1], length)


def _edge_rates(segs, length: float) -> tuple[float, float]:
    return _seg_rate(segs[0], 0.0), _seg_rate(segs[-1], length)


def out_exact_ms(c: dict) -> float:
    if is_freeze(c):
        return float(int(c.get("hold_ms") or 0))
    return _segments(c)[1]


def out_len_ms(c: dict) -> int:
    """How long the clip plays in the video (ms, whole)."""
    if is_freeze(c):
        return int(c.get("hold_ms") or 0)
    if not retimed(c):
        return int(c["out_ms"]) - int(c["in_ms"])
    return int(round(out_exact_ms(c)))


def edge_speeds(c: dict) -> tuple[float, float]:
    """The speed at the clip's first and last moment (0 for a freeze: no source time passes)."""
    if is_freeze(c):
        return 0.0, 0.0
    if not ramp_points(c):
        return speed(c), speed(c)
    segs, _total = _segments(c)
    r0, r1 = _edge_rates(segs, float(int(c["out_ms"]) - int(c["in_ms"])))
    return 1.0 / r0, 1.0 / r1


def out_at(c: dict, src_rel_ms: float) -> float:
    """Output ms from the clip's start for a time in its file, counted from its in point. Past either end the clip's
    edge speed continues. On a freeze frame the time is already output time (kept inside the hold)."""
    if is_freeze(c):
        return max(0.0, min(float(src_rel_ms), out_exact_ms(c)))
    if not retimed(c):
        return float(src_rel_ms)
    segs, total = _segments(c)
    length = float(int(c["out_ms"]) - int(c["in_ms"]))
    r0, r1 = _edge_rates(segs, length)
    if src_rel_ms <= 0:
        return src_rel_ms * r0
    if src_rel_ms >= length:
        return total + (src_rel_ms - length) * r1
    for seg in segs:
        if src_rel_ms <= seg[1]:
            return _seg_out(seg, src_rel_ms)
    return total


def src_at(c: dict, out_rel_ms: float) -> float:
    """The time in the file (ms from the in point) shown `out_rel_ms` after the clip starts (the inverse of
    out_at; 0 throughout a freeze)."""
    if is_freeze(c):
        return 0.0
    if not retimed(c):
        return float(out_rel_ms)
    segs, total = _segments(c)
    length = float(int(c["out_ms"]) - int(c["in_ms"]))
    r0, r1 = _edge_rates(segs, length)
    if out_rel_ms <= 0:
        return out_rel_ms / r0
    if out_rel_ms >= total:
        return length + (out_rel_ms - total) / r1
    for k, seg in enumerate(segs):
        end = segs[k + 1][4] if k + 1 < len(segs) else total
        if out_rel_ms <= end:
            lo, hi = max(seg[0], 0.0), min(seg[1], length)
            for _ in range(60):  # out is strictly increasing: bisection to well under a microsecond
                mid = (lo + hi) / 2
                if _seg_out(seg, mid) < out_rel_ms:
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) / 2
    return length


def src_positions(c: dict, out_rel_ms):
    """src_at for an array of output times (ms), vectorised for the sound (a dense table of the closed form)."""
    import numpy as np

    t = np.asarray(out_rel_ms, dtype=np.float64)
    if not retimed(c):
        return t.copy()
    segs, total = _segments(c)
    length = float(int(c["out_ms"]) - int(c["in_ms"]))
    r0, r1 = _edge_rates(segs, length)
    us, os_ = [], []
    for seg in segs:
        u = np.linspace(max(seg[0], 0.0), min(seg[1], length), 513)
        v = (u - seg[0]) / max(seg[1] - seg[0], 1e-9)
        us.append(u)
        os_.append(seg[4] + (seg[1] - seg[0]) * (seg[2] * v + (seg[3] - seg[2]) * (v ** 3 - v ** 4 / 2)))
    u, o = np.concatenate(us), np.concatenate(os_)
    out = np.interp(t, o, u)
    lo, hi = t < 0, t > total
    out[lo] = t[lo] / r0
    out[hi] = length + (t[hi] - total) / r1
    return out


def setpts(c: dict, u0_ms: float, seek_ms: float | None = None) -> str:
    """FFmpeg setpts for picture read from `seek_ms` into the clip's source range (the seek point, `u0_ms` when not
    given): each source frame goes to its output time from the moment `u0_ms` (the piece's first frame), so frames
    read before it get negative times. Empty at normal speed."""
    if not retimed(c) or is_freeze(c):
        return ""
    seek = u0_ms if seek_ms is None else seek_ms
    f0 = out_at(c, u0_ms) / 1000
    if not ramp_points(c):
        rate = 1.0 / speed(c)
        return f"setpts='({seek / 1000:.9f}+T)*{rate:.9f}/TB-{f0:.9f}/TB'"
    segs, total = _segments(c)
    length = float(int(c["out_ms"]) - int(c["in_ms"]))
    e0, e1 = _edge_rates(segs, length)
    u = "ld(0)"
    expr = f"{total / 1000:.9f}+({u}-{length / 1000:.9f})*{e1:.9f}"  # past the end: the edge speed goes on
    for k in range(len(segs) - 1, -1, -1):
        a, b, r0, r1, o = segs[k]
        ln = (b - a) / 1000
        v = f"(({u}-{a / 1000:.9f})/{ln:.9f})"
        piece = f"{o / 1000:.9f}+{ln:.9f}*({r0:.9f}*{v}+{r1 - r0:.9f}*(pow({v},3)-pow({v},4)/2))"
        expr = f"if(lt({u},{min(b, length) / 1000:.9f}),{piece},{expr})"
    expr = f"if(lt({u},0),{u}*{e0:.9f},{expr})"  # before the in point: the edge speed too
    return f"setpts='st(0,{seek / 1000:.9f}+T);({expr}-{f0:.9f})/TB'"


def _ease(w: str, ease: str) -> str:
    return w if ease == "linear" else f"{w}*{w}*(3-2*{w})"


def _key_expr(keys: list[dict], field: str, ease: str) -> str:
    """A key field (zoom, x or y) at the position in ld(0), eased between keys (st(3) holds the local share)."""
    expr = f"{float(keys[-1][field]):.6f}"
    for k0, k1 in reversed(list(zip(keys, keys[1:]))):
        a, b = float(k0["at"]), float(k1["at"])
        v0, v1 = float(k0[field]), float(k1[field])
        if b <= a:
            continue
        piece = f"st(3,(ld(0)-{a:.6f})/{b - a:.6f});{v0:.6f}+{v1 - v0:.6f}*{_ease('ld(3)', ease)}"
        expr = f"if(lt(ld(0),{b:.6f}),{piece},{expr})"
    first = float(keys[0]["at"])
    return f"if(lt(ld(0),{first:.6f}),{float(keys[0][field]):.6f},{expr})"


def motion_filter(c: dict, rel_frame: int, frames: int, width: int, height: int) -> str:
    """The camera move of an element `frames` long, for a piece starting `rel_frame` into it: the source is made
    no bigger than the output needs at the deepest zoom, then a perspective filter (per frame, sub-pixel) shows the
    moving framing window. Empty without a move."""
    keys = motion_keys(c)
    if not keys:
        return ""
    ease = (c.get("motion") or {}).get("ease", "smooth")
    deepest = max(float(k["zoom"]) for k in keys)
    tw, th = math.ceil(width * deepest), math.ceil(height * deepest)
    w0, w1 = motion_range(c)
    # where this frame is in the move: its share of the element, within the part of the move the clip plays
    pos = f"st(0,{w0:.6f}+{w1 - w0:.6f}*clip(({rel_frame}+in)/{max(1, frames - 1)},0,1));"
    zoom = f"st(1,{_key_expr(keys, 'zoom', ease)});"
    left = f"{pos}{zoom}st(2,{_key_expr(keys, 'x', ease)});clip(ld(2)*W-W/ld(1)/2,0,W-W/ld(1))"
    top = f"{pos}{zoom}st(2,{_key_expr(keys, 'y', ease)});clip(ld(2)*H-H/ld(1)/2,0,H-H/ld(1))"
    right, bottom = f"{left}+W/ld(1)", f"{top}+H/ld(1)"
    return (f"scale=w='trunc(min(iw,max({tw},{th}*iw/ih))/2)*2':h=-2,"
            f"perspective=x0='{left}':y0='{top}':x1='{right}':y1='{top}':x2='{left}':y2='{bottom}':"
            f"x3='{right}':y3='{bottom}':sense=source:eval=frame:interpolation=linear")


def speed_at(c: dict, share: float) -> float:
    """The clip's speed at a share (0 to 1) of its source range."""
    if not ramp_points(c):
        return speed(c)
    segs, _total = _segments(c)
    u = share * float(int(c["out_ms"]) - int(c["in_ms"]))
    seg = next((s for s in segs if u <= s[1]), segs[-1])
    return 1.0 / _seg_rate(seg, u)


def split_ramp(c: dict, _share: float = 0.0) -> tuple[dict, dict]:
    """A ramp for each half of a split clip: both keep the whole curve and the file range it is drawn over, so each
    half plays exactly its part of it (the two together play as the whole did)."""
    r = c.get("speed_ramp") or {}
    rng = ramp_range(c) or (float(int(c["in_ms"])), float(int(c["out_ms"])))
    half = {**r, "range": [round(rng[0], 3), round(rng[1], 3)]}
    return dict(half), dict(half)


def _range_ok(rng) -> bool:
    return isinstance(rng, (list, tuple)) and len(rng) == 2 and all(_num(v) for v in rng) and 0 <= rng[0] <= rng[1] <= 1


def motion_range(c: dict) -> tuple[float, float]:
    """The part of its camera move a clip plays (shares of the move, 0 to 1): all of it, or a split half's part
    (`motion.range`), or one moment for a freeze frame held from a moving clip (both ends equal)."""
    m = c.get("motion")
    rng = m.get("range") if isinstance(m, dict) else None
    return (float(rng[0]), float(rng[1])) if _range_ok(rng) else (0.0, 1.0)


def split_motion(c: dict, share: float) -> tuple[dict, dict]:
    """A camera move cut in two at a share of the clip's length in the video: each half keeps the whole move and
    plays its part of it, so the framing goes on smoothly across the cut."""
    m = c.get("motion") or {}
    w0, w1 = motion_range(c)
    mid = round(w0 + (w1 - w0) * min(1.0, max(0.0, share)), 6)
    return {**m, "range": [w0, mid]}, {**m, "range": [mid, w1]}


def held_motion(c: dict, share: float) -> dict | None:
    """The camera move for a freeze frame held from a moving clip at a share of its length: the framing of that
    moment, held still."""
    m = c.get("motion")
    if not motion_keys(c):
        return None
    w0, w1 = motion_range(c)
    at = round(w0 + (w1 - w0) * min(1.0, max(0.0, share)), 6)
    return {**m, "range": [at, at]}


def problems(c: dict, asset: dict | None, frame_ms: float = 1000 / 30) -> list[str]:
    """What is wrong with a clip's speed, ramp, freeze or move (empty when nothing is)."""
    name = c.get("label", "?")
    out = []
    kind = c.get("kind", "video")
    if kind not in ("video", "image", "freeze"):
        out.append(f"Clip “{name}” has an unknown kind.")
        return out
    if "speed" in c and c["speed"] is not None:
        s = c["speed"]
        if not _num(s) or not SPEED_RANGE[0] <= s <= SPEED_RANGE[1]:
            out.append(f"The speed of “{name}” must be between {SPEED_RANGE[0]:g}× and {SPEED_RANGE[1]:g}×.")
        elif kind != "video" and abs(s - 1) > 1e-9:
            out.append(f"Only a video clip can change speed (“{name}”).")
    ramp = c.get("speed_ramp")
    if ramp is not None:
        pts = ramp_points(c)
        if not isinstance(ramp, dict) or pts is None:
            out.append(f"The speed ramp of “{name}” is not readable.")
        elif kind != "video":
            out.append(f"Only a video clip can have a speed ramp (“{name}”).")
        elif ramp.get("range") is not None and ramp_range(c) is None:
            out.append(f"The speed ramp of “{name}” has a file range that is not readable.")
        elif not RAMP_POINTS[0] <= len(pts) <= RAMP_POINTS[1]:
            out.append(f"A speed ramp has {RAMP_POINTS[0]} to {RAMP_POINTS[1]} points (“{name}”).")
        elif pts[0][0] != 0 or pts[-1][0] != 1 or any(b[0] <= a[0] for a, b in zip(pts, pts[1:])):
            out.append(f"The speed ramp of “{name}” must run from the start of the clip to its end, in order.")
        elif any(not SPEED_RANGE[0] <= s <= SPEED_RANGE[1] for _a, s in pts):
            out.append(f"Every speed in the ramp of “{name}” must be between {SPEED_RANGE[0]:g}× and "
                       f"{SPEED_RANGE[1]:g}×.")
    if kind == "freeze":
        hold = c.get("hold_ms")
        if not _num(hold) or hold < FREEZE_MIN_MS:
            out.append(f"The freeze frame “{name}” must hold for at least {FREEZE_MIN_MS / 1000:g} s.")
        if asset is not None and asset.get("kind") != "video":
            out.append(f"A freeze frame holds a frame of a video (“{name}”).")
        last = last_frame_ms(asset, frame_ms)  # (a moment inside the last frame holds that frame)
        if int(c.get("in_ms") or 0) < 0 or (last is not None and int(c.get("in_ms") or 0) > last + frame_ms - 1):
            out.append(f"The freeze frame “{name}” is outside its file.")
    m = c.get("motion")
    if m is not None:
        keys = motion_keys(c)
        if not isinstance(m, dict) or not keys:
            out.append(f"The camera move of “{name}” is not readable.")
        elif m.get("ease", "smooth") not in EASES:
            out.append(f"The camera move of “{name}” has an unknown easing.")
        elif m.get("range") is not None and not _range_ok(m["range"]):
            out.append(f"The camera move of “{name}” has a part that is not readable.")
        elif not MOTION_KEYS[0] <= len(keys) <= MOTION_KEYS[1]:
            out.append(f"A camera move has {MOTION_KEYS[0]} to {MOTION_KEYS[1]} keys (“{name}”).")
        else:
            try:
                ats = [float(k["at"]) for k in keys]
                bad = any(not (_num(k["zoom"]) and MOTION_ZOOM[0] <= k["zoom"] <= MOTION_ZOOM[1]
                               and _num(k["x"]) and 0 <= k["x"] <= 1 and _num(k["y"]) and 0 <= k["y"] <= 1)
                          for k in keys)
            except (KeyError, TypeError, ValueError):
                ats, bad = [], True
            if bad or not ats or ats[0] < 0 or ats[-1] > 1 or any(b <= a for a, b in zip(ats, ats[1:])):
                out.append(f"The camera move of “{name}” needs keys in order, zoom {MOTION_ZOOM[0]:g} to "
                           f"{MOTION_ZOOM[1]:g} and a framing inside the picture.")
        if float(c.get("zoom") or 1.0) > 1.001:
            out.append(f"“{name}” has both a punch-in zoom and a camera move; keep one.")
    return out


def describe(c: dict) -> str:
    """A short note of a clip's timing for lists ("2×", "ramp", "freeze 2 s"); empty at normal speed."""
    if is_freeze(c):
        return f"freeze {int(c.get('hold_ms') or 0) / 1000:g} s"
    r = c.get("speed_ramp")
    if ramp_points(c):
        preset = r.get("preset") if isinstance(r, dict) else None
        return RAMPS[preset][0].lower() if preset in RAMPS else "speed ramp"
    s = speed(c)
    return "" if abs(s - 1) < 1e-9 else f"{s:g}×"


# ------------------------------------------------------------------ sound
WSOLA_FRAME = 1024      # 21 ms at 48 kHz
WSOLA_TOL = 384         # how far a frame may move to join smoothly (8 ms): also the worst sync error


def stretch(src: Path, src_n: int, n: int, position, out: Path, gain_in: int = 0, gain_out: int = 0) -> Path:
    """Write `n` samples of raw float stereo to `out`, output sample j taken from source sample position(j) of the
    raw file `src` (src_n samples; outside it is silence; `position` maps an array of output sample numbers to
    increasing source sample positions): a WSOLA time-stretch that keeps the pitch. Each overlapping 21 ms frame
    moves at most 8 ms from where the map puts it so it joins its neighbour smoothly (normalised correlation, so
    where the map runs at normal speed the sound comes out unchanged). Linear fades of `gain_in`/`gain_out` samples
    at the ends (like FFmpeg's afade). Memory stays bounded: both files are mapped, not read whole, and the map is
    asked only at each frame's centre."""

    import numpy as np

    big_n, hop, tol = WSOLA_FRAME, WSOLA_FRAME // 2, WSOLA_TOL
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(big_n) / big_n)).astype(np.float32)  # sums to 1 at this hop
    xs = np.memmap(src, dtype=np.float32, mode="r", shape=(src_n, 2)) if src_n else np.zeros((0, 2), np.float32)
    ys = np.memmap(out, dtype=np.float32, mode="w+", shape=(max(1, n), 2))
    try:
        ys[:] = 0

        def read(a: int, b: int):
            """Source samples [a, b), silence outside the file."""
            buf = np.zeros((b - a, 2), dtype=np.float32)
            lo, hi = max(a, 0), min(b, src_n)
            if hi > lo:
                buf[lo - a:hi - a] = xs[lo:hi]
            return buf
        frames = n // hop + 2
        ideal = np.asarray(position(np.arange(frames, dtype=np.float64) * hop), dtype=np.float64)
        prev = None
        for i in range(frames):
            want = int(round(ideal[i])) - big_n // 2
            if prev is None:
                best = want
            else:
                nat = prev + hop  # where the previous frame naturally goes on
                template = read(nat, nat + big_n).mean(axis=1)
                region = read(want - tol, want + tol + big_n).mean(axis=1)
                corr = np.correlate(region, template, "valid")
                sq = np.concatenate([[0.0], np.cumsum(region.astype(np.float64) ** 2)])
                score = corr / np.sqrt(np.maximum(sq[big_n:] - sq[:-big_n], 1e-12))
                k = int(np.argmax(score))
                best = want - tol + k if score[k] > 1e-6 else want  # silence: where the map says
            prev = best
            o = i * hop - big_n // 2
            lo, hi = max(0, o), min(n, o + big_n)
            if hi > lo:
                ys[lo:hi] += read(best + lo - o, best + hi - o) * win[lo - o:hi - o, None]
        if gain_in > 0:
            k = min(gain_in, n)
            ys[:k] *= (np.arange(k, dtype=np.float32) / gain_in)[:, None]
        if gain_out > 0:
            k = min(gain_out, n)
            ys[n - k:] *= (np.arange(k - 1, -1, -1, dtype=np.float32) / gain_out)[:, None]
        ys.flush()
    finally:
        del ys
        if src_n:
            xs._mmap.close()  # noqa: SLF001 - release the file now (Windows cannot delete an open map)
    if n == 0:
        out.write_bytes(b"")
    return out

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


def _segments(c: dict) -> tuple[list[tuple[float, float, float, float, float]], float]:
    """([(source start, source end, rate at start, rate at end, output start)] in ms from the in point, output
    length in ms), where rate = 1 / speed."""
    length = float(int(c["out_ms"]) - int(c["in_ms"]))
    pts = ramp_points(c) or [(0.0, speed(c)), (1.0, speed(c))]
    segs, o = [], 0.0
    for (p0, s0), (p1, s1) in zip(pts, pts[1:]):
        a, b, r0, r1 = p0 * length, p1 * length, 1.0 / s0, 1.0 / s1
        segs.append((a, b, r0, r1, o))
        o += (b - a) * (r0 + r1) / 2
    return segs, o


def _seg_out(seg, u: float) -> float:
    a, b, r0, r1, o = seg
    if b <= a:
        return o
    v = (u - a) / (b - a)
    return o + (b - a) * (r0 * v + (r1 - r0) * (v ** 3 - v ** 4 / 2))


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
    pts = ramp_points(c)
    return (pts[0][1], pts[-1][1]) if pts else (speed(c), speed(c))


def out_at(c: dict, src_rel_ms: float) -> float:
    """Output ms from the clip's start for a time in its file, counted from its in point. Past either end the clip's
    edge speed continues. On a freeze frame the time is already output time (kept inside the hold)."""
    if is_freeze(c):
        return max(0.0, min(float(src_rel_ms), out_exact_ms(c)))
    if not retimed(c):
        return float(src_rel_ms)
    segs, total = _segments(c)
    if src_rel_ms <= 0:
        return src_rel_ms * segs[0][2]
    if src_rel_ms >= segs[-1][1]:
        return total + (src_rel_ms - segs[-1][1]) * segs[-1][3]
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
    if out_rel_ms <= 0:
        return out_rel_ms / segs[0][2]
    if out_rel_ms >= total:
        return segs[-1][1] + (out_rel_ms - total) / segs[-1][3]
    for k, seg in enumerate(segs):
        end = segs[k + 1][4] if k + 1 < len(segs) else total
        if out_rel_ms <= end:
            lo, hi = seg[0], seg[1]
            for _ in range(60):  # out is strictly increasing: bisection to well under a microsecond
                mid = (lo + hi) / 2
                if _seg_out(seg, mid) < out_rel_ms:
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) / 2
    return segs[-1][1]


def src_positions(c: dict, out_rel_ms):
    """src_at for an array of output times (ms), vectorised for the sound (a dense table of the closed form)."""
    import numpy as np

    t = np.asarray(out_rel_ms, dtype=np.float64)
    if not retimed(c):
        return t.copy()
    segs, total = _segments(c)
    us, os_ = [], []
    for seg in segs:
        u = np.linspace(seg[0], seg[1], 513)
        v = (u - seg[0]) / max(seg[1] - seg[0], 1e-9)
        us.append(u)
        os_.append(seg[4] + (seg[1] - seg[0]) * (seg[2] * v + (seg[3] - seg[2]) * (v ** 3 - v ** 4 / 2)))
    u, o = np.concatenate(us), np.concatenate(os_)
    out = np.interp(t, o, u)
    lo, hi = t < 0, t > total
    out[lo] = t[lo] / segs[0][2]
    out[hi] = segs[-1][1] + (t[hi] - total) / segs[-1][3]
    return out


def setpts(c: dict, u0_ms: float) -> str:
    """FFmpeg setpts for picture read from `u0_ms` into the clip's source range (the seek point): each source frame
    goes to its output time from the piece's start. Empty at normal speed."""
    if not retimed(c) or is_freeze(c):
        return ""
    pts = ramp_points(c)
    if not pts:
        return f"setpts=PTS*{1.0 / speed(c):.9f}"
    segs, total = _segments(c)
    f0 = out_at(c, u0_ms) / 1000
    u = "ld(0)"
    expr = f"{total / 1000:.9f}+({u}-{segs[-1][1] / 1000:.9f})*{segs[-1][3]:.9f}"  # past the end: edge speed
    for a, b, r0, r1, o in reversed(segs):
        if b <= a:
            continue
        ln = (b - a) / 1000
        v = f"(({u}-{a / 1000:.9f})/{ln:.9f})"
        piece = f"{o / 1000:.9f}+{ln:.9f}*({r0:.9f}*{v}+{r1 - r0:.9f}*(pow({v},3)-pow({v},4)/2))"
        expr = f"if(lt({u},{b / 1000:.9f}),{piece},{expr})"
    return f"setpts='st(0,{u0_ms / 1000:.9f}+T);({expr}-{f0:.9f})/TB'"


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
    pos = f"st(0,clip(({rel_frame}+in)/{max(1, frames - 1)},0,1));"
    zoom = f"st(1,{_key_expr(keys, 'zoom', ease)});"
    left = f"{pos}{zoom}st(2,{_key_expr(keys, 'x', ease)});clip(ld(2)*W-W/ld(1)/2,0,W-W/ld(1))"
    top = f"{pos}{zoom}st(2,{_key_expr(keys, 'y', ease)});clip(ld(2)*H-H/ld(1)/2,0,H-H/ld(1))"
    right, bottom = f"{left}+W/ld(1)", f"{top}+H/ld(1)"
    return (f"scale=w='trunc(min(iw,max({tw},{th}*iw/ih))/2)*2':h=-2,"
            f"perspective=x0='{left}':y0='{top}':x1='{right}':y1='{top}':x2='{left}':y2='{bottom}':"
            f"x3='{right}':y3='{bottom}':sense=source:eval=frame:interpolation=linear")


def speed_at(c: dict, share: float) -> float:
    """The clip's speed at a share (0 to 1) of its source range."""
    pts = ramp_points(c)
    if not pts:
        return speed(c)
    for (a, s0), (b, s1) in zip(pts, pts[1:]):
        if share <= b:
            v = 0.0 if b <= a else min(1.0, max(0.0, (share - a) / (b - a)))
            r = 1 / s0 + (1 / s1 - 1 / s0) * v * v * (3 - 2 * v)
            return 1 / r
    return pts[-1][1]


def split_ramp(c: dict, share: float) -> tuple[dict, dict]:
    """A ramp cut in two at a share of the source range (a split clip): each half keeps its part of the curve, both
    meeting at the speed of that moment."""
    pts = ramp_points(c) or []
    mid = round(speed_at(c, share), 4)
    first = [(a / share, s) for a, s in pts if a < share] + [(1.0, mid)]
    second = [(0.0, mid)] + [((a - share) / (1 - share), s) for a, s in pts if a > share]
    return ({"points": [{"at": round(a, 6), "speed": s} for a, s in first]},
            {"points": [{"at": round(a, 6), "speed": s} for a, s in second]})


def split_motion(c: dict, share: float) -> tuple[dict, dict]:
    """A camera move cut in two at a share of the clip's length in the video: the first half ends on the framing
    of that moment and the second starts from it."""
    m = c.get("motion") or {}
    keys = motion_keys(c) or []
    ease = m.get("ease", "smooth")
    here = {"at": share}
    for k0, k1 in zip(keys, keys[1:]):
        if share <= float(k1["at"]):
            a, b = float(k0["at"]), float(k1["at"])
            v = 0.0 if b <= a else min(1.0, max(0.0, (share - a) / (b - a)))
            w = v if ease == "linear" else v * v * (3 - 2 * v)
            here = {f: round(float(k0[f]) + (float(k1[f]) - float(k0[f])) * w, 4) for f in ("zoom", "x", "y")}
            break
    else:
        here = {f: float(keys[-1][f]) for f in ("zoom", "x", "y")} if keys else {"zoom": 1.0, "x": 0.5, "y": 0.5}
    first = [{**k, "at": round(float(k["at"]) / share, 6)} for k in keys if float(k["at"]) < share]
    first.append({"at": 1.0, **here})
    second = [{"at": 0.0, **here}] + [{**k, "at": round((float(k["at"]) - share) / (1 - share), 6)} for k in keys
                                      if float(k["at"]) > share]
    if first[0]["at"] > 0:
        first.insert(0, {**first[0], "at": 0.0})
    if second[-1]["at"] < 1:
        second.append({**second[-1], "at": 1.0})
    return {"ease": ease, "keys": first[-MOTION_KEYS[1]:]}, {"ease": ease, "keys": second[:MOTION_KEYS[1]]}


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
        length = float((asset or {}).get("probe", {}).get("duration") or 0) * 1000
        if int(c.get("in_ms") or 0) < 0 or (length and int(c.get("in_ms") or 0) > length - frame_ms):
            out.append(f"The freeze frame “{name}” is outside its file.")
    m = c.get("motion")
    if m is not None:
        keys = motion_keys(c)
        if not isinstance(m, dict) or not keys:
            out.append(f"The camera move of “{name}” is not readable.")
        elif m.get("ease", "smooth") not in EASES:
            out.append(f"The camera move of “{name}” has an unknown easing.")
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

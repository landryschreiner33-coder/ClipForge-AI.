"""Several cameras of one recording (multicam) and pictures in a corner (picture in picture).

A plan's `multicam` holds, for each recording the clips are cut from (the main recording, keyed by its asset id),
the other cameras that filmed the same moments, lined up by the sound they all recorded:

    plan["multicam"][main_id] = {
        "main": {"label": "Camera 1", "shot": "wide"},
        "cams": [{"id": "c2", "asset_id": ..., "label": "Camera 2", "shot": "close",
                  "offset_ms": 1530.0, "drift_ppm": 0.0, "match": 0.83}],
        "cuts": [[0, "main"], [12340, "c2"], ...],
        "corner": {"cam": "c2", "place": "bottom_right", "size": 0.26},
        "switching": "speaker" | "angles" | "hand" | "off",
    }

* A camera's own time is the main recording's time plus `offset_ms`, plus `drift_ppm` millionths of the main time
  (two cameras' clocks run a little apart: 50 ppm is 0.18 s an hour, which the eye sees as bad lip sync).
* `cuts` say which camera is on screen from each moment of the MAIN recording's file time on (before the first cut:
  the main camera). Because they are in file time, they stay on their moments through trims, splits, reordering
  and speed changes, as in an editor's multicam clip. A camera is shown only where its file has picture; elsewhere
  the main camera stands in.
* The sound always comes from the main recording (the clips' own sound), and so do the captions.
* `corner`: one camera shown small in a corner over the whole recording (a face cam over a screen recording, the
  listener in a podcast), hidden while that camera is the full picture.
* `shot`: "wide" (the whole scene, everyone), "close" (one person) or "other" (a screen, a product, gameplay: only
  shown when chosen by hand or in the corner).

Automatic switching (`plan_cuts`), from the research (docs/clipforge/EDITING_CRAFT_RESEARCH.md): cut to whoever is
speaking in the gap between turns, hold each shot at least 2 s, use the wide shot at the start, the end, during long
silences and when people talk over each other, break up a long close-up with the wide, and change camera at every
jump cut (a jump cut inside one camera is what multicam hides). Who is speaking comes from each close camera's own
sound: the person a camera films is the loudest in that camera's microphone (`who_speaks`). With one person and
several angles ("angles"), the camera changes at pauses after a few seconds (a right-skewed spread around 6 s),
alternating shot sizes.

Overlays (pictures over the video) take a `place` too: "full" (the whole frame, as before) or a corner, with a
`size` (share of the frame's width): a picture or another video in a corner over a clip.
"""
from __future__ import annotations

import hashlib
import math
import os
import subprocess
from bisect import bisect_right
from pathlib import Path
from typing import Callable

import numpy as np

from .. import config
from ..pipeline.ffmpeg_utils import NO_WINDOW, ffmpeg_bin

MAIN = "main"
MAX_CAMS = 6                     # cameras of one recording, the main one included
SHOTS = ("wide", "close", "other")
SHOT_NAMES = {"wide": "Wide shot", "close": "One person", "other": "Screen or other"}
SWITCHING = ("speaker", "angles", "hand", "off")
CORNERS = ("top_left", "top_right", "bottom_left", "bottom_right")
PLACES = ("full", *CORNERS)
CORNER_NAMES = {"top_left": "top left", "top_right": "top right", "bottom_left": "bottom left",
                "bottom_right": "bottom right"}
CORNER_SIZE = (0.15, 0.5)        # a corner picture's width, as a share of the frame's width
# where a corner picture sits, by the frame's shape: (side, as a share of the width; top and bottom, as shares of the
# height). On 9:16 it stays inside every platform's safe box (x 120-888, y 288-1248 at 1080x1920), clear of the
# buttons and the caption area at the bottom.
CORNER_MARGINS = {"16:9": (0.03, 0.053, 0.053), "9:16": (0.111, 0.15, 0.35), "1:1": (0.04, 0.04, 0.12),
                  "4:5": (0.05, 0.05, 0.14)}
CORNER_DEFAULT = {"16:9": ("bottom_right", 0.26), "9:16": ("top_right", 0.42), "1:1": ("bottom_right", 0.32),
                  "4:5": ("top_right", 0.36)}
CORNER_BORDER = 4                # a light frame around a corner picture, in pixels at 1080
CORNER_COLOUR = "0xF0F0F0"
DRIFT_PIECE_MS = 60000           # a drifting camera is re-lined-up at least this often
OFFSET_MAX_MS = 24 * 3600 * 1000
DRIFT_MAX_PPM = 500.0
MAX_CUTS = 20000

# the sound profile: speech-band loudness in 10 ms frames
RATE = 100
_SR = 8000
_PROFILE_VERSION = 1
# lining cameras up
MATCH_MIN = 0.12                 # the best match must be at least this good ...
MATCH_APART = 1.25               # ... and this much better than the best one more than a second away
MIN_OVERLAP_S = 20.0             # a match over a shorter stretch counts for less
DRIFT_MIN_S = 480.0              # drift is measured on recordings overlapping at least this long
DRIFT_WINDOW_S = 60.0
# who is speaking
SEP_DB = 4.0                     # each camera must hear its own person this much louder (relative to the others)
UNSURE_DB = 1.0                  # a word this close to halfway between two people is unclear
SPEAKER_MIN_SHARE = 0.03         # a "speaker" heard for less than this share of the talk is folded into another
# switching rules (ms)
PHRASE_GAP_MS = 300              # words closer than this belong to one phrase
MIN_HOLD_MS = 2000               # no shot shorter than this (except at a jump cut)
OPEN_MS = 3000                   # the wide shot opens the video for at least this long
END_MS = 5000                    # ... and comes back in the last few seconds
SILENCE_MS = 2500                # a pause this long goes to the wide shot
MAX_CLOSE_MS = 14000             # a close-up this long is broken up with the wide shot ...
WIDE_BREAK_MS = 3000             # ... for at least this long
LEAD_MS = 150                    # the picture changes this long before the new speaker's first word, at most
ANGLE_HOLD_MS = (3500, 12000)    # one person, several angles: how long a shot holds (median about 6 s)
SWITCH_GAP_MS = 150              # an angle changes only in a pause at least this long


class MulticamError(ValueError):
    """A camera setup that cannot work (a recording that is not there, a sound that does not match)."""


# ------------------------------------------------------------------ the plan's cameras
def groups(plan: dict) -> dict[str, dict]:
    g = (plan or {}).get("multicam")
    return g if isinstance(g, dict) else {}


def group_of(plan: dict, asset_id: str | None) -> dict | None:
    g = groups(plan).get(asset_id or "")
    return g if isinstance(g, dict) else None


def cam_entry(group: dict, cam: str) -> dict | None:
    """The camera's record (None for the main camera or an unknown id)."""
    return next((c for c in group.get("cams") or [] if c.get("id") == cam), None)


def cam_ids(group: dict) -> list[str]:
    return [MAIN, *[c.get("id") for c in group.get("cams") or []]]


def shot_of(group: dict, cam: str) -> str:
    rec = (group.get("main") or {}) if cam == MAIN else (cam_entry(group, cam) or {})
    return rec.get("shot") if rec.get("shot") in SHOTS else ("wide" if cam == MAIN else "close")


def label_of(group: dict, cam: str) -> str:
    rec = (group.get("main") or {}) if cam == MAIN else (cam_entry(group, cam) or {})
    if rec.get("label"):
        return str(rec["label"])
    return "Camera 1" if cam == MAIN else f"Camera {cam_ids(group).index(cam) + 1}" if cam in cam_ids(group) else cam


def asset_of(group: dict, main_id: str, cam: str) -> str | None:
    return main_id if cam == MAIN else (cam_entry(group, cam) or {}).get("asset_id")


def camera_at(group: dict, t_ms: float) -> str:
    """The camera the cuts put on screen at the main recording's moment `t_ms`."""
    cuts = group.get("cuts") or []
    k = bisect_right([float(c[0]) for c in cuts], float(t_ms)) - 1
    return str(cuts[k][1]) if k >= 0 else MAIN


def to_cam_ms(cam: dict, main_ms: float) -> float:
    """The camera's own time at the main recording's `main_ms`."""
    return float(cam.get("offset_ms") or 0) + float(main_ms) * (1 + float(cam.get("drift_ppm") or 0) / 1e6)


def coverage(cam: dict, length_ms: int) -> tuple[float, float]:
    """The main recording's stretch (ms) this camera has picture for (a frame clear of its file's end)."""
    rate = 1 + float(cam.get("drift_ppm") or 0) / 1e6
    off = float(cam.get("offset_ms") or 0)
    return -off / rate, (max(0, length_ms - 100) - off) / rate


def spans(group: dict, a_ms: float, b_ms: float, lengths: dict[str, int]) -> list[tuple[float, float, str, str | None]]:
    """The main recording's stretch [a, b) as (start, end, camera on screen, camera in the corner or None) in main
    file time. A camera stands in only where its file has picture (`lengths`: the cameras' file lengths in ms, by
    camera id); the main camera fills the rest. A drifting camera's stretches are cut at least every minute, so a
    render re-lines it up as it goes."""
    if b_ms <= a_ms:
        return []
    covers = {c["id"]: coverage(c, int(lengths.get(c["id"]) or 0)) for c in group.get("cams") or [] if c.get("id")}
    points = {a_ms, b_ms}
    points |= {float(c[0]) for c in group.get("cuts") or [] if a_ms < float(c[0]) < b_ms}
    points |= {x for lo_hi in covers.values() for x in lo_hi if a_ms < x < b_ms}
    if any(float(c.get("drift_ppm") or 0) for c in group.get("cams") or []):
        t = (math.floor(a_ms / DRIFT_PIECE_MS) + 1) * DRIFT_PIECE_MS
        while t < b_ms:
            points.add(float(t))
            t += DRIFT_PIECE_MS
    corner = group.get("corner") or {}
    want_corner = corner.get("cam") if corner.get("cam") in cam_ids(group) else None

    def shows(cam: str | None, t0: float, t1: float) -> bool:
        if cam is None or cam == MAIN:
            return cam == MAIN
        lo, hi = covers.get(cam, (0.0, -1.0))
        return lo <= t0 and t1 <= hi + 0.5

    out: list[tuple[float, float, str, str | None]] = []
    edges = sorted(points)
    for t0, t1 in zip(edges, edges[1:]):
        cam = camera_at(group, t0)
        cam = cam if cam in cam_ids(group) and shows(cam, t0, t1) else MAIN
        side = want_corner if want_corner and want_corner != cam and shows(want_corner, t0, t1) else None
        if out and out[-1][2] == cam and out[-1][3] == side and not _drifting(group, cam, side):
            out[-1] = (out[-1][0], t1, cam, side)
        else:
            out.append((t0, t1, cam, side))
    return out


def _drifting(group: dict, *cams: str | None) -> bool:
    return any(float((cam_entry(group, c) or {}).get("drift_ppm") or 0) for c in cams if c and c != MAIN)


def in_use(plan: dict) -> bool:
    """Whether the plan shows another camera than the clips' own anywhere, or a picture in a corner."""
    clips = [c for c in plan.get("clips") or [] if c.get("include", True)]
    used = {c.get("asset_id") for c in clips}
    for aid, g in groups(plan).items():
        if aid in used and ((g.get("corner") or {}).get("cam") or any(c[1] != MAIN for c in g.get("cuts") or [])):
            return True
    return any((o.get("place") or "full") != "full" for o in plan.get("overlays") or [] if not o.get("hide"))


def shown_assets(plan: dict) -> list[str]:
    """The other cameras the video shows (in a cut or in the corner) of the recordings it plays."""
    used = {c.get("asset_id") for c in plan.get("clips") or [] if c.get("include", True)}
    out = []
    for aid, g in groups(plan).items():
        if aid not in used:
            continue
        seen = {c[1] for c in g.get("cuts") or []} | {(g.get("corner") or {}).get("cam")}
        out += [c.get("asset_id") for c in g.get("cams") or [] if c.get("id") in seen and c.get("asset_id")]
    return list(dict.fromkeys(out))


def used_assets(plan: dict) -> list[str]:
    """Every camera recording the plan's camera setup refers to."""
    out = []
    for aid, g in groups(plan).items():
        out.append(aid)
        out += [c.get("asset_id") for c in g.get("cams") or [] if c.get("asset_id")]
    return list(dict.fromkeys(a for a in out if a))


def problems(plan: dict, assets: dict[str, dict]) -> list[str]:
    """What stops a render in the plan's camera setup and corner pictures."""
    out: list[str] = []
    raw = plan.get("multicam")
    if raw is None:
        return out + _overlay_problems(plan)
    if not isinstance(raw, dict):
        return ["The camera setup cannot be read."]
    for main_id, g in raw.items():
        main = assets.get(main_id)
        if not isinstance(g, dict):
            out.append("The camera setup cannot be read.")
            continue
        if not main or main.get("kind") != "video":
            out.append("A camera setup refers to a recording that is missing.")
            continue
        cams = g.get("cams") or []
        if not isinstance(cams, list) or len(cams) + 1 > MAX_CAMS:
            out.append(f"A recording can have at most {MAX_CAMS} cameras.")
            continue
        ids = [MAIN]
        for c in cams:
            a = assets.get((c or {}).get("asset_id"))
            name = (c or {}).get("label") or "A camera"
            if not isinstance(c, dict) or not c.get("id") or c.get("id") in ids:
                out.append("Two cameras share one ID.")
                continue
            ids.append(c["id"])
            if not a or a.get("kind") != "video":
                out.append(f"“{name}” refers to a recording that is missing.")
            elif not Path(a["path"]).is_file():
                out.append(f"The original file “{a['filename']}” is missing on the server. Upload it again.")
            elif c["asset_id"] == main_id:
                out.append(f"“{name}” is the recording itself.")
            if not _number(c.get("offset_ms"), -OFFSET_MAX_MS, OFFSET_MAX_MS):
                out.append(f"“{name}” is lined up more than a day away.")
            if not _number(c.get("drift_ppm", 0), -DRIFT_MAX_PPM, DRIFT_MAX_PPM):
                out.append(f"“{name}” runs too far apart from the recording to line it up.")
            if c.get("shot", "close") not in SHOTS:
                out.append(f"“{name}” has an unknown kind of shot.")
        if (g.get("main") or {}).get("shot", "wide") not in SHOTS:
            out.append("The main camera has an unknown kind of shot.")
        cuts = g.get("cuts") or []
        if not isinstance(cuts, list) or len(cuts) > MAX_CUTS:
            out.append("A recording has too many camera changes.")
        else:
            last = -1.0
            for cut in cuts:
                if not isinstance(cut, (list, tuple)) or len(cut) != 2 or not _number(cut[0], 0, 1e10) \
                        or cut[1] not in ids or float(cut[0]) < last:
                    out.append("A camera change cannot be read.")
                    break
                last = float(cut[0])
        corner = g.get("corner")
        if corner:
            if not isinstance(corner, dict) or corner.get("cam") not in ids:
                out.append("The camera in the corner is not one of this recording's cameras.")
            else:
                out += _corner_problems(corner, "The corner camera")
        if g.get("switching", "hand") not in SWITCHING:
            out.append("Unknown camera switching.")
    return out + _overlay_problems(plan)


def _overlay_problems(plan: dict) -> list[str]:
    out = []
    for o in plan.get("overlays") or []:
        if (o.get("place") or "full") != "full":
            out += _corner_problems(o, f"“{o.get('label') or 'A picture over the video'}”")
    return out


def _corner_problems(item: dict, name: str) -> list[str]:
    place = item.get("place")
    if place is not None and place not in CORNERS:  # none: the frame's usual corner
        return [f"{name} has an unknown place."]
    size = item.get("size")
    if size is not None and not _number(size, *CORNER_SIZE):
        return [f"{name} must be {CORNER_SIZE[0]:.0%} to {CORNER_SIZE[1]:.0%} of the frame's width."]
    return []


def _number(v, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi


# ------------------------------------------------------------------ corner geometry
def aspect_key(width: int, height: int) -> str:
    r = width / max(1, height)
    return min(CORNER_MARGINS, key=lambda k: abs(math.log(r / _ratio(k))))


def _ratio(key: str) -> float:
    a, b = key.split(":")
    return float(a) / float(b)


def corner_defaults(width: int, height: int) -> tuple[str, float]:
    return CORNER_DEFAULT[aspect_key(width, height)]


def corner_box(place: str | None, size, width: int, height: int, shape: float | None) -> tuple[int, int, int, int]:
    """(x, y, w, h) of a corner picture inside a width x height frame, in even pixels. `shape` is the picture's own
    width over height (kept between 3:4 and 16:9: a very tall or wide picture is cropped to that)."""
    key = aspect_key(width, height)
    d_place, d_size = CORNER_DEFAULT[key]
    place = place if place in CORNERS else d_place
    size = float(size) if _number(size, *CORNER_SIZE) else d_size
    shape = min(16 / 9, max(3 / 4, float(shape or 16 / 9)))
    w = max(2, int(round(width * size)) // 2 * 2)
    h = max(2, int(round(w / shape)) // 2 * 2)
    if h > height * 0.45:
        h = int(height * 0.45) // 2 * 2
        w = max(2, int(round(h * shape)) // 2 * 2)
    side, top, bottom = CORNER_MARGINS[key]
    x = int(round(width * side)) if place.endswith("left") else width - int(round(width * side)) - w
    y = int(round(height * top)) if place.startswith("top") else height - int(round(height * bottom)) - h
    return x // 2 * 2, y // 2 * 2, w, h


def border_px(width: int, height: int) -> int:
    return max(2, int(round(CORNER_BORDER * min(width, height) / 1080)))


# ------------------------------------------------------------------ the sound of each recording
def _cache_dir() -> Path:
    d = config.data_dir() / "cache" / "multicam"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _profile_key(asset: dict) -> str:
    sha = asset.get("sha256") or ""
    if not sha:
        p = Path(asset["path"])
        st = p.stat()
        sha = hashlib.sha256(f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()
    return f"{sha[:40]}-v{_PROFILE_VERSION}"


def sound_profile(asset: dict, cancelled: Callable[[], bool] | None = None) -> np.ndarray:
    """The recording's loudness in the speech band (100 Hz to 3.8 kHz), in dB, RATE frames a second: read once and
    kept in ClipForge's cache (a few megabytes for hours of sound). Empty for a recording without sound."""
    f = _cache_dir() / f"{_profile_key(asset)}.npy"
    if f.is_file():
        try:
            return np.load(f).astype(np.float32)
        except (OSError, ValueError):
            f.unlink(missing_ok=True)
    levels = _decode_levels(asset["path"], cancelled)
    tmp = f.with_name(f"{f.stem}.{os.getpid()}.part.npy")
    np.save(tmp, levels.astype(np.float16 if levels.size > 4_000_000 else np.float32))
    os.replace(tmp, f)
    return levels


def _decode_levels(path: str, cancelled: Callable[[], bool] | None) -> np.ndarray:
    win = _SR // RATE
    cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:a:0", "-vn",
           "-af", "highpass=f=100,lowpass=f=3800", "-ac", "1", "-ar", str(_SR), "-f", "s16le", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    parts: list[np.ndarray] = []
    rest = np.zeros(0, np.float32)
    try:
        while True:
            if cancelled and cancelled():
                from ..pipeline.common import Cancelled
                raise Cancelled()
            buf = proc.stdout.read(_SR * 2 * 30)  # type: ignore[union-attr]
            if not buf:
                break
            x = np.concatenate([rest, np.frombuffer(buf[: len(buf) // 2 * 2], np.int16).astype(np.float32) / 32768])
            n = len(x) // win
            rest = x[n * win:]
            if n:
                parts.append(10 * np.log10(np.mean(x[: n * win].reshape(n, win) ** 2, axis=1) + 1e-10))
    finally:
        proc.kill()
        proc.wait()
    return np.concatenate(parts).astype(np.float32) if parts else np.zeros(0, np.float32)


def _onsets(levels: np.ndarray) -> np.ndarray:
    """How the loudness rises from frame to frame (words, claps, door slams), standardised; the noise floor's own
    flicker is left out."""
    x = np.maximum(levels.astype(np.float64), np.percentile(levels, 20) if levels.size else 0.0)
    rise = np.maximum(0.0, np.diff(x, prepend=x[:1]))
    return ((rise - rise.mean()) / (rise.std() + 1e-9)).astype(np.float64)


def line_up(main: np.ndarray, cam: np.ndarray) -> dict | None:
    """How a camera's sound lines up with the main recording's: {"offset_ms", "drift_ppm", "match"} so that camera
    time = main time + offset + main time x drift / 1e6; None when no single place matches clearly (no shared sound).
    Both are compared whole (the camera may start long before or after the main recording); the match is refined
    between frames, and on recordings overlapping eight minutes or more the drift between the two clocks is measured
    from several one-minute stretches."""
    if main.size < RATE * 3 or cam.size < RATE * 3:
        return None
    a, b = _onsets(main), _onsets(cam)
    m, n = len(a), len(b)
    size = 1 << int(math.ceil(math.log2(m + n)))
    full = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)
    shifts = np.arange(-(m - 1), n)
    corr = full[shifts % size]
    over = np.minimum(m, n - shifts) - np.maximum(0, -shifts)
    score = corr / np.maximum(over, 1) * np.minimum(1.0, over / (MIN_OVERLAP_S * RATE))
    score[over < RATE * 5] = -np.inf
    best = int(np.argmax(score))
    match = float(score[best])
    away = np.abs(shifts - shifts[best]) > RATE
    second = float(np.max(score[away])) if away.any() else 0.0
    if not math.isfinite(match) or match < MATCH_MIN or match < MATCH_APART * max(second, 1e-9):
        return None
    lag = float(shifts[best]) + _peak(score, best)
    out = {"offset_ms": round(lag * 1000 / RATE, 1), "drift_ppm": 0.0, "match": round(min(1.0, match), 3)}
    drift = _drift(a, b, int(shifts[best]))
    if drift:
        out.update(offset_ms=round(drift[0] * 1000 / RATE, 1), drift_ppm=round(drift[1] * 1e6, 2))
    return out


def _peak(y: np.ndarray, k: int) -> float:
    """Where between frames the peak at `k` really is (a parabola through it and its neighbours)."""
    if k <= 0 or k >= len(y) - 1 or not (math.isfinite(y[k - 1]) and math.isfinite(y[k + 1])):
        return 0.0
    den = y[k - 1] - 2 * y[k] + y[k + 1]
    return float(np.clip(0.5 * (y[k - 1] - y[k + 1]) / den, -0.5, 0.5)) if den < 0 else 0.0


def _drift(a: np.ndarray, b: np.ndarray, lag: int) -> tuple[float, float] | None:
    """(lag at main time 0, frames of lag per frame) fitted through one-minute stretches, or None when the
    recordings overlap too briefly or the stretches do not agree on a straight line."""
    lo, hi = max(0, -lag), min(len(a), len(b) - lag)
    if hi - lo < DRIFT_MIN_S * RATE:
        return None
    win, reach = int(DRIFT_WINDOW_S * RATE), RATE // 2
    centres = np.linspace(lo + win / 2 + reach, hi - win / 2 - reach, 7)
    pts = []
    for c in centres:
        w0 = int(c - win / 2)
        seg = a[w0: w0 + win]
        start = w0 + lag - reach
        if start < 0 or start + win + 2 * reach > len(b):
            continue
        local = np.correlate(b[start: start + win + 2 * reach], seg, "valid") / win
        k = int(np.argmax(local))
        if 0 < k < len(local) - 1 and local[k] >= MATCH_MIN:
            pts.append((w0 + win / 2, lag - reach + k + _peak(local, k)))
    if len(pts) < 3:
        return None
    t, s = np.array(pts).T
    slope, icpt = np.polyfit(t, s, 1)
    keep = np.abs(s - (icpt + slope * t)) <= 3.0
    if keep.sum() < 3:
        return None
    slope, icpt = np.polyfit(t[keep], s[keep], 1)
    rms = float(np.sqrt(np.mean((s[keep] - (icpt + slope * t[keep])) ** 2)))
    if rms > 0.8 or abs(slope) * 1e6 > DRIFT_MAX_PPM:
        return None
    if abs(slope) * (hi - lo) < 0.5:  # under 5 ms over the whole overlap: no drift worth correcting
        return None
    return float(icpt), float(slope)


def aligned(levels: np.ndarray, cam: dict | None, frames: int) -> np.ndarray:
    """A camera's loudness on the main recording's frames (NaN where the camera has no sound)."""
    out = np.full(frames, np.nan, np.float32)
    if levels.size == 0:
        return out
    if cam is None:
        k = min(frames, len(levels))
        out[:k] = levels[:k]
        return out
    t = np.arange(frames, dtype=np.float64) * (1000 / RATE)
    cam_ms = float(cam.get("offset_ms") or 0) + t * (1 + float(cam.get("drift_ppm") or 0) / 1e6)
    idx = np.rint(cam_ms / (1000 / RATE)).astype(np.int64)
    ok = (idx >= 0) & (idx < len(levels))
    out[ok] = levels[idx[ok]]
    return out


# ------------------------------------------------------------------ who is speaking
def _word_levels(words: list[dict], levels: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """(words x cameras loudness in dB, each word's length in s): the louder half of each word's frames."""
    cams = list(levels)
    out = np.full((len(words), len(cams)), np.nan)
    dur = np.zeros(len(words))
    for i, w in enumerate(words):
        a, b = int(math.floor(float(w["start"]) * RATE)), int(math.ceil(float(w["end"]) * RATE))
        if b - a < 3:
            mid = (a + b) // 2
            a, b = mid - 1, mid + 2
        dur[i] = max(0.0, float(w["end"]) - float(w["start"]))
        for j, c in enumerate(cams):
            seg = levels[c][max(0, a): max(0, b)]
            if seg.size and not np.isnan(seg).any():
                out[i, j] = float(np.mean(np.sort(seg)[len(seg) // 2:]))
    return out, dur


def _kmeans(x: np.ndarray, wt: np.ndarray, cent: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Weighted k-means from `cent`. A group left empty starts again at the word furthest from its own group's
    centre (one person heard equally loud by every camera must not swallow the other)."""
    cent = np.array(cent, dtype=np.float64)
    for _ in range(40):
        d = ((x[:, None, :] - cent[None]) ** 2).sum(axis=2)
        lab = np.argmin(d, axis=1)
        own = d[np.arange(len(x)), lab]
        new = cent.copy()
        for j in range(len(cent)):
            if (lab == j).any():
                new[j] = np.average(x[lab == j], axis=0, weights=wt[lab == j])
            elif own.max() > 0:
                k = int(np.argmax(own))
                new[j], own[k] = x[k], -1.0
        if np.allclose(new, cent, atol=1e-4):
            break
        cent = new
    return np.argmin(((x[:, None, :] - cent[None]) ** 2).sum(axis=2), axis=1), cent


def who_speaks(words: list[dict], levels: dict[str, np.ndarray]) -> tuple[list[str | None], dict]:
    """Which close camera's person says each word (None: unclear, or two at once), from each camera's own sound on
    the main recording's frames (`aligned`). A camera hears the person it films loudest, but every camera has its own
    level, so the words are grouped by how loud each camera hears them compared with the others (k-means, one group
    per person; fewer groups when fewer people talk) and a group belongs to the camera that hears it loudest compared
    with the other groups. The people must be told apart by at least SEP_DB. Returns (speaker per word, {"separable",
    "why", "seconds": {camera: seconds of talk}})."""
    cams = list(levels)
    info: dict = {"separable": False, "why": "", "seconds": {}}
    out: list[str | None] = [None] * len(words)
    if len(cams) < 2:
        info["why"] = "only one camera films a single person"
        return out, info
    v, dur = _word_levels(words, levels)
    ok = ~np.isnan(v).any(axis=1) & (dur > 0.03)
    if ok.sum() < 8:
        info["why"] = "too few words were heard by every camera"
        return out, info
    x = v[ok] - v[ok].mean(axis=1, keepdims=True)
    wt = dur[ok]
    lead = np.argmax(x, axis=1)
    cent = np.array([x[lead == j].mean(axis=0) if (lead == j).any() else np.eye(len(cams))[j] * 6
                     for j in range(len(cams))])
    best = None
    worst_gap = 0.0
    while len(cent) >= 2:
        lab, cent = _kmeans(x, wt, cent)
        mass = np.array([wt[lab == j].sum() for j in range(len(cent))])
        keep = mass >= SPEAKER_MIN_SHARE * wt.sum()
        if keep.sum() >= 2:
            c = cent[keep]
            owners = np.argmax(c - c.mean(axis=0), axis=1)  # the gains of the cameras cancel out
            if len(set(owners.tolist())) == len(c):
                gaps = [(c[p][owners[p]] - c[p][owners[q]]) - (c[q][owners[p]] - c[q][owners[q]])
                        for p in range(len(c)) for q in range(p + 1, len(c))]
                worst_gap = max(worst_gap, min(gaps))
                if min(gaps) >= SEP_DB:
                    best = (c, owners)
                    break
        # one person fewer: merge the two closest groups and try again
        far = ((cent[:, None, :] - cent[None]) ** 2).sum(axis=2) + np.eye(len(cent)) * 1e9
        p, q = np.unravel_index(int(np.argmin(far)), far.shape)
        merged = (cent[p] * mass[p] + cent[q] * mass[q]) / max(1e-9, mass[p] + mass[q])
        cent = np.array([merged, *[cent[j] for j in range(len(cent)) if j not in (p, q)]])
    if best is None:
        info["why"] = ("every camera hears the speakers about equally loud" if worst_gap < 1.5 else
                       f"the cameras hear the speakers only {worst_gap:.1f} dB apart") + \
            " (each camera needs its own microphone near the person it films)"
        return out, info
    c, owners = best
    rows = np.flatnonzero(ok)
    for r, i in enumerate(rows):
        near = np.argsort(((x[r][None] - c) ** 2).sum(axis=1))
        p, q = int(near[0]), int(near[1])
        op, oq = owners[p], owners[q]
        mid = ((c[p][op] - c[p][oq]) + (c[q][op] - c[q][oq])) / 2
        side = (x[r][op] - x[r][oq]) - mid
        if abs(side) >= UNSURE_DB:
            out[i] = cams[op] if side > 0 else cams[oq]
    seconds: dict[str, float] = {}
    for c_, w in zip(out, words):
        if c_:
            seconds[c_] = seconds.get(c_, 0.0) + max(0.0, float(w["end"]) - float(w["start"]))
    info.update(separable=True, seconds={c_: round(s_, 1) for c_, s_ in seconds.items()})
    return out, info


# ------------------------------------------------------------------ which camera when
def _phrases(words: list[dict], who: list[str | None] | None, a_ms: float, b_ms: float) -> list[dict]:
    """The phrases spoken inside [a, b) (ms): words closer than PHRASE_GAP_MS, with whoever says most of it."""
    out: list[dict] = []
    for i, w in enumerate(words):
        s, e = float(w["start"]) * 1000, float(w["end"]) * 1000
        if s < a_ms - 10 or s >= b_ms:
            continue
        s, e = max(s, a_ms), min(e, b_ms)
        if out and s - out[-1]["end"] < PHRASE_GAP_MS:
            out[-1]["end"] = max(out[-1]["end"], e)
        else:
            out.append({"start": s, "end": e, "talk": {}})
        if who and who[i]:
            out[-1]["talk"][who[i]] = out[-1]["talk"].get(who[i], 0.0) + (e - s)
    for p in out:
        total = sum(p["talk"].values())
        top = max(p["talk"], key=p["talk"].get) if total else None
        p["who"] = top if top and p["talk"][top] >= 0.6 * total else None
    return out


def _settle_turns(phr: list[dict]) -> None:
    """A turn shorter than MIN_HOLD_MS (a quick "yeah") between two turns of one person is theirs; between two
    different people or two short turns it counts as unclear (the wide shot). A short turn set apart by a pause
    (a question after a silence) is not a quick "yeah": it stays its speaker's."""
    turns: list[list[int]] = []
    for i, p in enumerate(phr):
        if turns and phr[turns[-1][-1]]["who"] == p["who"]:
            turns[-1].append(i)
        else:
            turns.append([i])
    length = [phr[t[-1]]["end"] - phr[t[0]]["start"] for t in turns]
    for k, t in enumerate(turns):
        if length[k] >= MIN_HOLD_MS or phr[t[0]]["who"] is None:
            continue
        gap_before = phr[t[0]]["start"] - phr[turns[k - 1][-1]]["end"] if k else math.inf
        gap_after = phr[turns[k + 1][0]]["start"] - phr[t[-1]]["end"] if k + 1 < len(turns) else math.inf
        if max(gap_before, gap_after) >= SILENCE_MS:
            continue
        before = phr[turns[k - 1][0]]["who"] if k else None
        after = phr[turns[k + 1][0]]["who"] if k + 1 < len(turns) else None
        mine = before if before is not None and before == after else None
        for i in t:
            phr[i]["who"] = mine


def _shape(u: float) -> int:
    """One person, several angles: a shot's length from a share u (0-1), right-skewed with a median about 6 s."""
    lo, hi = ANGLE_HOLD_MS
    return int(lo + (hi - lo) * u ** 1.8)


def _unit(seed: str, n: int) -> float:
    return int(hashlib.sha1(f"{seed}:{n}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def plan_cuts(ranges: list[tuple[float, float]], words: list[dict], who: list[str | None] | None,
              shots: dict[str, str], mode: str, avail: Callable[[str, float, float], bool],
              seed: str = "") -> list[list]:
    """Camera changes [[main ms, camera], ...] for the parts of the main recording the video plays (`ranges`, in the
    video's order), by the rules in this module's notes. `shots`: each camera's shot ("wide", "close", "other"),
    main first; `who`: each word's speaker as a close camera (speaker mode); `avail(cam, t0, t1)`: whether a camera
    has picture over that stretch; `seed` makes the angle lengths of one recording repeatable."""
    cams = [c for c in shots if shots[c] != "other"]
    if not cams or not ranges or mode not in ("speaker", "angles"):
        return []
    cuts: list[tuple[float, str]] = []
    st: dict = {"cur": None, "since": 0.0, "n": 0, "used": {}, "hold": ANGLE_HOLD_MS[0], "break": False}
    total = sum(b - a for a, b in ranges)

    def wide_at(t0: float, t1: float) -> str | None:
        return next((c for c in cams if shots[c] == "wide" and avail(c, t0, t1)), None)

    def put(t: float, cam: str, pos: float, brk: bool = False) -> None:
        cuts.append((t, cam))
        st.update(cur=cam, since=pos)
        st["used"][cam] = st["n"]
        st["n"] += 1
        st["hold"] = _shape(_unit(seed, st["n"]))
        st["break"] = brk

    def other(cur: str | None, t0: float, t1: float, speaker: str | None = None) -> str | None:
        """A different camera (a jump cut, an angle change): the speaker's, else another shot size, else the least
        recently used."""
        if speaker and speaker != cur and avail(speaker, t0, t1):
            return speaker
        pool = [c for c in cams if c != cur and avail(c, t0, t1)]
        size = shots.get(cur or "", "")
        pool.sort(key=lambda c: (shots[c] == size, st["used"].get(c, -1), cams.index(c)))
        return pool[0] if pool else None

    base, prev_b = 0.0, None
    for ri, (a, b) in enumerate(ranges):
        phr = _phrases(words, who if mode == "speaker" else None, a, b)
        if mode == "speaker":
            _settle_turns(phr)
        end0 = phr[0]["end"] if phr else b

        def at(t: float, a=a, base=base) -> float:  # where a moment plays, in the video (ignoring speed changes)
            return base + (t - a)

        first = phr[0]["who"] if mode == "speaker" and phr else None
        if st["cur"] is None:  # the video opens on the wide shot
            cam = wide_at(a, end0) or (first if first and avail(first, a, end0) else None) or \
                next((c for c in cams if avail(c, a, end0)), cams[0])
            put(a, cam, at(a))
        elif ri and prev_b is not None and abs(a - prev_b) > 1 or not avail(st["cur"], a, end0):
            # a jump cut (or the camera has no picture here): another camera hides it
            put(a, other(st["cur"], a, end0, first) or st["cur"], at(a))
        else:
            cuts.append((a, st["cur"]))
        last_end = a
        for i, p in enumerate(phr):
            g0, g1 = last_end, p["start"]
            last_end = p["end"]
            if i == 0:
                continue
            gap, cur = g1 - g0, st["cur"]
            wide = wide_at(g0, p["end"])
            if mode == "speaker" and wide and cur != wide and gap >= SILENCE_MS and at(g0 + 300) - st["since"] >= \
                    MIN_HOLD_MS:  # a long pause: the wide shot while nobody talks
                put(g0 + 300, wide, at(g0 + 300))
                cur = wide
            held = at(g1) - st["since"]
            if ri == 0 and at(g1) < OPEN_MS:
                continue  # the opening wide shot holds
            t = max(g0 + min(100.0, gap / 2), g1 - LEAD_MS)
            if ri == len(ranges) - 1 and total - at(g1) <= END_MS and wide and avail(wide, t, b):
                if cur != wide and held >= MIN_HOLD_MS and b - t >= MIN_HOLD_MS * 0.75:
                    put(t, wide, at(t))  # the video ends on the wide shot
                continue
            if mode == "speaker":
                brk = False
                want = p["who"] if p["who"] and avail(p["who"], g1, p["end"]) else (wide or cur)
                if want == cur and shots.get(cur) == "close" and wide and held >= MAX_CLOSE_MS:
                    want, brk = wide, True  # a long close-up: the wide shot for a moment
                if cur == wide and st["break"] and held < WIDE_BREAK_MS:
                    continue
                if want and want != cur and held >= MIN_HOLD_MS:
                    put(t, want, at(t), brk)
            elif gap >= SWITCH_GAP_MS and held >= st["hold"]:
                cam = other(cur, t, p["end"])
                if cam:
                    put(t, cam, at(t))
        if ri == len(ranges) - 1 and phr:  # the talk is over before the end: the video ends on the wide shot
            wide, t = wide_at(last_end, b), last_end + min(300.0, (b - last_end) / 2)
            if wide and st["cur"] != wide and b - t >= MIN_HOLD_MS * 0.75 and at(t) - st["since"] >= MIN_HOLD_MS:
                put(t, wide, at(t))
        while mode == "angles" and not phr:  # nothing said (music, a silent stretch): another angle every few seconds
            t = max(a, a + st["since"] + st["hold"] - base)
            cam = other(st["cur"], t, min(b, t + st["hold"])) if t <= b - MIN_HOLD_MS else None
            if not cam:
                break
            put(t, cam, at(t))
        base += b - a
        prev_b = b
    out: list[list] = []
    for t, cam in sorted(cuts, key=lambda x: x[0]):
        t = int(round(t))
        if out and out[-1][0] == t:
            out[-1][1] = cam
            if len(out) > 1 and out[-2][1] == cam:
                out.pop()
        elif not out or out[-1][1] != cam:
            out.append([t, cam])
    # before the first change the main camera is on screen anyway
    return out[1:] if out and out[0][1] == MAIN else out

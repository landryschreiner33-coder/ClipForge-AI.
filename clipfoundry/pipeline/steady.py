"""Steadying shaky camera footage (batch 4d of the editing-quality work; research in
docs/clipforge/EDITING_CRAFT_RESEARCH.md, what the owner sees in docs/clipforge/STEADY.md).

Only footage that shakes is touched, and only camera footage: a recording on a tripod, a game or a screen
recording is left exactly as it is. For footage that shakes:

1. **Measure** (`measure`): the picture is read small (MEASURE_W wide, grey) on the clip's own frame grid; corners are
   tracked from frame to frame (OpenCV: goodFeaturesToTrack, calcOpticalFlowPyrLK) and the camera's move between two
   frames is the similarity that most of them agree on (estimateAffinePartial2D with RANSAC): a shift and a roll. A
   frame where tracking fails or the picture jumps starts a new shot. A stretch longer than `FULL_S` is first
   sampled (`PROBE_S` every `PROBE_EVERY_S`): when every sample is calm, nothing more is read.
2. **Smooth** (`plan`): per shot, the camera's path is smoothed (a Gaussian of `SMOOTH_S`), so hand shake (2-12 Hz)
   goes while a pan, a tilt or a walk stays. What is left (the path minus its smoothed self) is the shake.
3. **Decide**: a shot is steadied when it shakes (`SHAKY_MIN` of the width, or `SHAKY_ROLL` degrees, as RMS), when
   most tracked points move together and all over the picture (the camera moved, not a person in a still shot:
   `MIN_TOGETHER`, `MIN_SPREAD`; when they reach fewer than `MIN_CORNERS` corners of the picture, a person filling a
   plain-walled shot looks the same, so the shake must also hold hand tremor, `HAND_HZ` and up: `HAND_SHARE`), and
   when no point keeps staying put where the camera's move says it should have moved (a game's HUD, a screen's
   toolbar or a logo, which steadying would make shake: `STILL_FRAMES`; footage without one has none). A shot whose
   picture never moved enough to look for such points is left alone. Only the frames the clip shows (`span`) count:
   the measured stretch runs on either side.
4. **Correct**: each frame is moved back onto the smoothed path and the shot is enlarged just enough (at most
   `MAX_ZOOM`) to hide the moving edges; a frame that would need more is corrected only as far as the edges allow.

The corrections are shares of the frame width (both directions) and radians, so they fit the picture at any size: the
clip renderer applies them with cv2.warpAffine on each decoded frame (`Plan.matrix`), the full-video engine with
FFmpeg's rotate and crop filters driven by a sendcmd file (`Plan.commands`).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import subprocess
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .common import Cancelled
from .ffmpeg_utils import NO_WINDOW, ffmpeg_bin

log = logging.getLogger("clipfoundry.pipeline.steady")

VERSION = 3
MEASURE_W = 480        # the width the picture is measured at
SMOOTH_S = 0.45        # the smoothed camera path (Gaussian sigma, seconds): shake goes, a pan or a walk stays
SHAKY_MIN = 0.0025     # RMS shake (share of the width) from which a shot counts as shaky (about 5 px at 1920)
SHAKY_ROLL = 0.25      # or RMS roll, degrees
MAX_ZOOM = 1.10        # the most a shot is enlarged to hide the moving edges
MIN_SHOT_S = 1.0       # shorter shots are left alone
MIN_TOGETHER = 0.5     # median share of tracked points that move with the camera's move
STILL_FRAMES = 1 / 3   # a point stays put while the picture moves in this share of frames: a HUD, a toolbar, a logo
MIN_SPREAD = 0.4       # median share of the picture the points moving with the camera span (convex hull)
CORNER = 0.2           # the corners of the picture (this share of its width and height) ...
MIN_CORNERS = 3        # ... of which this many hold points moving with the camera; when fewer do (plain sky, a plain
HAND_HZ = 4.0          # wall: a person filling the shot looks the same), the shake above this frequency ...
HAND_SHARE = 0.35      # ... is at least this share of it (hand tremor; a person's own sway and nods are slower)
STILL_MOVE = 1.0       # a point the camera's move shifts this far (pixels at MEASURE_W) shows whether it stayed put
MIN_STILL_FRAMES = 5   # fewer frames showing that: whether something stays put cannot be told (left alone)
OVERLAY_BOX = (0.35, 0.22)  # each corner box of the picture (share of its width, height) where overlays sit
OVERLAY_POINTS = 80     # more points looked for in each corner box, to tell whether something stays put there
EIG_FLOOR = 0.002       # corner-box points weaker than this share of the picture's strongest are not followed
MIN_POINTS = 12        # fewer tracked points: the frame cannot be measured (a new shot starts)
CUT_JUMP = 0.2         # a move over this share of the width between two frames is a cut or a whip pan
FULL_S = 120.0         # a stretch up to this long is measured whole
PROBE_S = 2.0          # a longer one is sampled first: this long ...
PROBE_EVERY_S = 6.0    # ... every this many seconds (a shaky shot of 7 s or more always holds a whole sample)
ROLL_MIN_DEG = 0.05    # the full-video engine adds a rotate filter only when some frame rolls more than this


@dataclass
class Track:
    """The camera's move between consecutive frames of a stretch, read on the grid `t0 + k / fps`."""
    t0: float
    fps: float
    size: tuple[int, int]           # the measured picture (width, height)
    dx: np.ndarray                  # shift since the previous frame, share of the width (both directions)
    dy: np.ndarray
    da: np.ndarray                  # roll since the previous frame, radians (clockwise on screen)
    together: np.ndarray            # share of tracked points that moved with the camera (nan: not measured)
    still: np.ndarray               # how many points stayed put where the camera's move shifted them (nan: it
    #                                 shifted too few points to tell)
    spread: np.ndarray              # share of the picture spanned by the points that moved with the camera
    cuts: list[int] = field(default_factory=lambda: [0])   # first frame of each shot
    corners: np.ndarray | None = None   # how many of the picture's 4 corners hold points moving with the camera

    def to_json(self) -> dict:
        def r(a):
            return [None if not math.isfinite(float(v)) else round(float(v), 6) for v in a]
        return {"v": VERSION, "t0": self.t0, "fps": self.fps, "size": list(self.size), "dx": r(self.dx),
                "dy": r(self.dy), "da": r(self.da), "together": r(self.together), "still": r(self.still),
                "spread": r(self.spread), "cuts": self.cuts,
                "corners": r(self.corners if self.corners is not None else np.full(len(self.dx), np.nan))}

    @classmethod
    def from_json(cls, d: dict) -> "Track":
        def a(v):
            return np.array([np.nan if x is None else x for x in v], float)
        return cls(float(d["t0"]), float(d["fps"]), tuple(d["size"]), a(d["dx"]), a(d["dy"]), a(d["da"]),
                   a(d["together"]), a(d["still"]), a(d["spread"]), [int(c) for c in d["cuts"]], a(d["corners"]))


@dataclass
class Plan:
    """Per frame of the grid `t0 + k / fps`: the correction (tx, ty: share of the width; ta: radians) and the zoom;
    `shots` says what was decided for each shot and why; `span` is the part of the file the clip shows."""
    t0: float
    fps: float
    aspect: float                   # height / width of the picture
    tx: np.ndarray
    ty: np.ndarray
    ta: np.ndarray
    zoom: np.ndarray
    shots: list[dict]
    span: tuple[float, float] | None = None

    @property
    def active(self) -> bool:
        return any(s.get("steadied") for s in self.shots)

    def moves(self, k: int) -> bool:
        """Whether frame k is corrected at all (a calm shot between shaky ones is not)."""
        k = max(0, min(len(self.tx) - 1, k))
        return bool(self.zoom[k] > 1.0 or self.tx[k] or self.ty[k] or self.ta[k])

    def index(self, t: float) -> int:
        return max(0, min(len(self.tx) - 1, int(round((t - self.t0) * self.fps))))

    def matrix(self, k: int, w: int, h: int) -> np.ndarray:
        """The 2x3 warp (source to output pixels) that steadies frame k of a w x h picture."""
        k = max(0, min(len(self.tx) - 1, k))
        a, z = float(self.ta[k]), float(self.zoom[k])
        rot = z * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        centre = np.array([w / 2.0, h / 2.0])
        shift = centre + z * np.array([self.tx[k] * w, self.ty[k] * w]) - rot @ centre
        return np.hstack([rot, shift[:, None]])

    def framed(self, k: int, cx: float, cy: float) -> tuple[float, float]:
        """Where a point found on frame k before steadying (cx, cy: shares of the width and height, such as the
        framing's centre) is on the steadied frame. Only the enlargement moves it: the shake taken out is the
        framing's own smoothing, so following it would bring the shake back."""
        z = float(self.zoom[max(0, min(len(self.zoom) - 1, k))])
        return 0.5 + z * (float(cx) - 0.5), 0.5 + z * (float(cy) - 0.5)

    def key(self) -> str:
        """Changes whenever any correction does (cache keys of rendered pieces)."""
        data = np.round(np.stack([self.tx, self.ty, self.ta, self.zoom - 1.0]) * 1e5).astype(np.int64)
        return hashlib.sha256(json.dumps([VERSION, self.t0, self.fps, data.tolist()]).encode()).hexdigest()[:20]

    def summary(self, to_out: Callable[[float], float] | None = None) -> dict:
        """What the render notes keep: seconds steadied, the largest zoom, the strongest shake (share of the width,
        in %) and each steadied shot, all inside the part the clip shows (`span`, file seconds). `to_out` maps a
        file second to the clip's output seconds (cuts and speed), so `seconds` is what plays."""
        s0, s1 = self.span or (self.t0, self.t0 + len(self.tx) / self.fps)
        out = to_out or (lambda t: t)
        done, seconds = [], 0.0
        for s in self.shots:
            a, b = max(s["start_s"], s0), min(s["end_s"], s1)
            if s.get("steadied") and b > a:
                done.append({**s, "start_s": round(a, 3), "end_s": round(b, 3)})
                seconds += max(0.0, out(b) - out(a))
        return {"seconds": round(seconds, 2),
                "zoom": round(max([s["zoom"] for s in done] or [1.0]), 3),
                "shake_pct": round(max([s["shake_pct"] for s in done] or [0.0]), 2),
                "shots": [{k: s[k] for k in ("start_s", "end_s", "zoom", "shake_pct")} for s in done]}

    def rolls(self) -> bool:
        return bool(np.any(np.abs(self.ta) > math.radians(ROLL_MIN_DEG)))

    def crop_zoom(self) -> float:
        return float(np.max(self.zoom)) if len(self.zoom) else 1.0

    def commands(self, target: str, seek: float, length: float, roll: str | None = None) -> str:
        """A sendcmd file for the frames read from `seek` (file seconds) for `length` seconds: for each frame of the
        grid, where the crop window (`target`, a crop filter of the plan's largest zoom) and the roll (`roll`, a
        rotate filter) put it. Times are relative to `seek` (the frames' own times after an input seek); each takes
        effect half a frame early, so a file frame takes the correction of the grid frame nearest it."""
        k0, k1 = self.index(seek - 1.0 / self.fps), self.index(seek + length + 1.0 / self.fps)
        lines = []
        for k in range(k0, k1 + 1):
            at = max(0.0, self.t0 + k / self.fps - seek - 0.5 / self.fps)
            # the window is the largest zoom's (a shot that needed less is corrected inside the larger margin)
            x = f"(in_w-out_w)/2-({self.tx[k]:.6f})*in_w"
            y = f"(in_h-out_h)/2-({self.ty[k]:.6f})*in_w"
            cmd = f"{target} x {x}, {target} y {y}"
            if roll:
                cmd += f", {roll} angle {float(self.ta[k]):.6f}"
            lines.append(f"{at:.4f} {cmd};")
        return "\n".join(lines) + "\n"


def _size(w: int, h: int) -> tuple[int, int]:
    aw = min(MEASURE_W, max(2, w - w % 2))
    return aw, max(2, int(round(aw * h / max(1, w) / 2)) * 2)


def _frames(path: str, t0: float, length: float, fps: float, size: tuple[int, int],
            cancelled: Callable[[], bool] | None, exact: bool = False):
    """The picture, small and grey, on the grid from `t0`. Not `exact`: read exactly as the clip renderer decodes
    (an input seek to `t0` in milliseconds, then `fps`), so frame k is the frame the renderer shows as its frame k.
    `exact`: frame k is the file's frame nearest `t0 + k / fps` (the full-video engine times its corrections by the
    file's own frame times): the seek starts a frame early and the grid is anchored at `t0` itself."""
    aw, ah = size
    if exact:
        seek = max(0.0, t0 - 1.0 / fps)
        timing = ["-ss", f"{seek:.6f}", "-i", str(path), "-t", f"{length + t0 - seek:.6f}"]
        rate = f"fps=fps={fps}:start_time={t0 - seek:.6f}"
    else:
        timing, rate = ["-ss", f"{t0:.3f}", "-i", str(path), "-t", f"{length:.3f}"], f"fps={fps}"
    cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", *timing, "-map", "0:v:0", "-an", "-sn",
           "-vf", f"{rate},scale={aw}:{ah}:flags=area,format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW,
                            bufsize=aw * ah)
    try:
        while True:
            if cancelled is not None and cancelled():
                raise Cancelled()
            buf = proc.stdout.read(aw * ah)  # type: ignore[union-attr]
            if len(buf) < aw * ah:
                return
            yield np.frombuffer(buf, np.uint8).reshape(ah, aw)
    finally:
        proc.kill()
        proc.wait()


def _move(prev: np.ndarray, cur: np.ndarray,
          dense: bool = False) -> tuple[float, float, float, float, float, float, int] | None:
    """The camera's move from `prev` to `cur` (dx, dy in pixels, roll in radians, both about the centre), the share
    of tracked points that agree with it, how many of the points it shifts by STILL_MOVE or more stayed put instead
    (nan when it shifts too few: a roll moves the edges, not the middle), the share of the picture the
    agreeing points span (their convex hull) and how many of the picture's corners hold agreeing points. None: it
    cannot be measured (too few points, or the picture changed completely). `dense` (to tell whether something
    stays put): three times as many points, closer together, more in each corner of the picture where a date stamp,
    a logo or a score sits (see _overlay_points), followed in smaller windows (a thin or faint letter is not pulled
    along by the picture moving around it)."""
    import cv2

    pts = cv2.goodFeaturesToTrack(prev, maxCorners=600 if dense else 200, qualityLevel=0.005 if dense else 0.01,
                                  minDistance=5 if dense else 10, blockSize=7)
    if pts is None or len(pts) < MIN_POINTS:
        return None
    if dense:
        pts = np.concatenate([pts.reshape(-1, 2), _overlay_points(prev)]).reshape(-1, 1, 2).astype(np.float32)
    win = (13, 13) if dense else (21, 21)
    nxt, status, _err = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None, winSize=win, maxLevel=3)
    if nxt is None:
        return None
    ok = status.ravel() == 1
    p0, p1 = pts[ok].reshape(-1, 2), nxt[ok].reshape(-1, 2)
    if len(p0) < MIN_POINTS:
        return None
    m, inliers = cv2.estimateAffinePartial2D(p0, p1, method=cv2.RANSAC, ransacReprojThreshold=1.5, maxIters=500,
                                             confidence=0.99, refineIters=10)
    if m is None or inliers is None:
        return None
    agree = inliers.ravel().astype(bool)
    together = float(agree.mean())
    h, w = prev.shape
    good = p0[agree]
    span = cv2.contourArea(cv2.convexHull(good.astype(np.float32))) / float(w * h) if len(good) >= 3 else 0.0
    left, top = good[:, 0] < CORNER * w, good[:, 1] < CORNER * h
    right, bottom = good[:, 0] > (1 - CORNER) * w, good[:, 1] > (1 - CORNER) * h
    corners = sum(int(np.count_nonzero(sx & sy) >= 2) for sx in (left, right) for sy in (top, bottom))
    centre = np.array([w / 2.0, h / 2.0])
    moved = m[:, :2] @ centre + m[:, 2] - centre
    roll = math.atan2(float(m[1, 0]), float(m[0, 0]))
    return float(moved[0]), float(moved[1]), roll, together, _still(m, p0, p1), float(span), corners


def _overlay_points(prev: np.ndarray) -> np.ndarray:
    """Up to OVERLAY_POINTS more points in each corner box of the picture (OVERLAY_BOX of its width and height),
    ranked within the box: a small date stamp or a faint logo is outranked by the busy picture elsewhere. Points
    weaker than EIG_FLOOR of the picture's strongest (a plain sky or wall) are not followed."""
    import cv2

    h, w = prev.shape
    eig = cv2.cornerMinEigenVal(prev, 7)
    floor = EIG_FLOOR * float(eig.max())
    bw, bh = int(OVERLAY_BOX[0] * w), int(OVERLAY_BOX[1] * h)
    found = [np.zeros((0, 2), np.float32)]
    for x0 in (0, w - bw):
        for y0 in (0, h - bh):
            mask = np.zeros_like(prev)
            mask[y0:y0 + bh, x0:x0 + bw] = 255
            q = cv2.goodFeaturesToTrack(prev, maxCorners=OVERLAY_POINTS, qualityLevel=0.01, minDistance=3,
                                        blockSize=7, mask=mask)
            if q is not None:
                q = q.reshape(-1, 2)
                found.append(q[eig[q[:, 1].astype(int), q[:, 0].astype(int)] >= floor])
    return np.concatenate(found)


def _still(m: np.ndarray, p0: np.ndarray, p1: np.ndarray) -> float:
    """Of the points the camera's move `m` shifts by STILL_MOVE or more, how many stayed put (a HUD, a toolbar, a
    logo: even a small one holds a point or two); nan when it shifts too few points to tell."""
    shift = np.linalg.norm(p0 @ m[:, :2].T + m[:, 2] - p0, axis=1)
    should = shift >= STILL_MOVE
    if np.count_nonzero(should) < MIN_POINTS:
        return math.nan
    return float(np.count_nonzero(np.linalg.norm(p1 - p0, axis=1)[should] < 0.3))


def measure(path: str, t0: float, length: float, fps: float, frame_size: tuple[int, int],
            cancelled: Callable[[], bool] | None = None, exact: bool = False) -> Track:
    """The camera's move over `length` seconds from `t0`, on the grid `t0 + k / fps` (`exact`: see _frames)."""
    size = _size(*frame_size)
    aw = size[0]
    # whether something stays put is looked at over about a tenth of a second (every `gap` frames, with more points):
    # from one frame to the next a followed subject or a slow move often shifts too little to tell, at 60 fps above all
    gap = max(2, int(round(fps / 10)))
    dx, dy, da, together, still, spread, corners, cuts = [], [], [], [], [], [], [], [0]
    recent: deque = deque(maxlen=gap + 1)
    for k, cur in enumerate(_frames(path, t0, length, fps, size, cancelled, exact)):
        prev = recent[-1] if recent else None
        got = _move(prev, cur) if prev is not None else None
        if prev is not None and (got is None or math.hypot(got[0], got[1]) > CUT_JUMP * aw or got[3] < 0.25):
            cuts.append(k)  # a cut, a whip pan or a picture that cannot be followed: a new shot from here
            got = None
            recent.clear()
        recent.append(cur)
        if got is None:
            for v in (dx, dy, da):
                v.append(0.0)
            for v in (together, still, spread, corners):
                v.append(math.nan)
            continue
        dx.append(got[0] / aw)
        dy.append(got[1] / aw)
        da.append(got[2])
        together.append(got[3])
        spread.append(got[5])
        corners.append(got[6])
        wide = _move(recent[0], cur, dense=True) if k % gap == 0 and len(recent) == gap + 1 else None
        still.append(wide[4] if wide is not None else math.nan)
    a = lambda v: np.array(v, float)  # noqa: E731
    return Track(t0, fps, size, a(dx), a(dy), a(da), a(together), a(still), a(spread), cuts, a(corners))


def _smooth(x: np.ndarray, sigma: float) -> np.ndarray:
    """A Gaussian of `sigma` frames; the ends are continued as their own trend (odd reflection), so a pan running
    into a cut keeps its speed instead of being pulled back."""
    if sigma < 0.5 or len(x) < 3:
        return x.copy()
    r = max(1, int(3 * sigma))
    kern = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    kern /= kern.sum()
    padded = np.pad(x, r, mode="reflect", reflect_type="odd")
    return np.convolve(padded, kern, mode="valid")


def _median(v: np.ndarray) -> float:
    """The median of the measured values (0 when none was measured)."""
    return float(np.nanmedian(v)) if np.any(np.isfinite(v)) else 0.0


def _shown(track: Track, n: int, span: tuple[float, float] | None) -> tuple[int, int]:
    """The frames [i0, i1) of the grid inside `span` (file seconds): the ones the clip shows."""
    if span is None:
        return 0, n
    i0 = int(math.ceil((span[0] - track.t0) * track.fps - 1e-6))
    i1 = int(math.floor((span[1] - track.t0) * track.fps + 1e-6)) + 1
    return max(0, min(n, i0)), max(0, min(n, i1))


def _inside(tx, ty, ta, z, aspect: float) -> np.ndarray:
    """Whether the output window, enlarged by z and corrected by (tx, ty, ta), stays inside the picture (width 1,
    height `aspect`, centred) at each frame."""
    c, s = np.cos(-ta), np.sin(-ta)
    ok = np.ones(np.shape(tx), bool)
    for qx in (-0.5, 0.5):
        for qy in (-aspect / 2, aspect / 2):
            ux, uy = qx / z - tx, qy / z - ty
            sx, sy = c * ux - s * uy, s * ux + c * uy
            ok &= (np.abs(sx) <= 0.5 + 1e-9) & (np.abs(sy) <= aspect / 2 + 1e-9)
    return ok


def _zoom_needed(tx, ty, ta, aspect: float) -> np.ndarray:
    lo, hi = np.ones(len(tx)), np.full(len(tx), 2.0)
    for _ in range(24):
        mid = (lo + hi) / 2
        ok = _inside(tx, ty, ta, mid, aspect)
        hi, lo = np.where(ok, mid, hi), np.where(ok, lo, mid)
    return hi


def _fit(tx, ty, ta, z: float, aspect: float) -> np.ndarray:
    """The share (0-1) of each frame's correction that fits inside the margin of zoom z."""
    lo, hi = np.zeros(len(tx)), np.ones(len(tx))
    whole = _inside(tx, ty, ta, z, aspect)
    for _ in range(20):
        mid = (lo + hi) / 2
        ok = _inside(mid * tx, mid * ty, mid * ta, z, aspect)
        lo, hi = np.where(ok, mid, lo), np.where(ok, hi, mid)
    return np.where(whole, 1.0, lo)


def plan(track: Track, max_zoom: float = MAX_ZOOM, span: tuple[float, float] | None = None) -> Plan:
    """The corrections for a measured stretch: only shots that shake, of camera footage, are steadied. `span` (file
    seconds): the part the clip shows; only its frames decide (the stretch runs on either side for the smoothing)."""
    n = len(track.dx)
    aspect = track.size[1] / max(1, track.size[0])
    tx, ty, ta, zoom = np.zeros(n), np.zeros(n), np.zeros(n), np.ones(n)
    corners = track.corners if track.corners is not None else np.full(n, 4.0)
    i0, i1 = _shown(track, n, span)
    shots = []
    edges = sorted({c for c in track.cuts if 0 <= c < n} | {0})
    for a, b in zip(edges, edges[1:] + [n]):
        shot = {"start_s": round(track.t0 + a / track.fps, 3), "end_s": round(track.t0 + b / track.fps, 3),
                "steadied": False, "zoom": 1.0, "shake_pct": 0.0}
        shots.append(shot)
        u0, u1 = max(a, i0), min(b, i1)
        if u1 - u0 < 2:
            shot["why"] = "not shown"
            continue
        if b - a < MIN_SHOT_S * track.fps:
            shot["why"] = "short"
            continue
        mx, my, ma = (np.nan_to_num(v[a:b].copy()) for v in (track.dx, track.dy, track.da))
        mx[0] = my[0] = ma[0] = 0.0  # the move into the shot's first frame belongs to the cut
        path = [np.cumsum(v) for v in (mx, my, ma)]
        smooth = [_smooth(v, SMOOTH_S * track.fps) for v in path]
        rx, ry, ra = (p - s for p, s in zip(path, smooth))
        seen = slice(u0 - a, u1 - a)  # the shot's frames the clip shows
        shake = float(np.sqrt(np.mean(rx[seen] ** 2 + ry[seen] ** 2)))
        roll = math.degrees(float(np.sqrt(np.mean(ra[seen] ** 2))))
        shot.update(shake_pct=round(100 * shake, 3), roll_deg=round(roll, 3))
        moves = slice(max(a + 1, u0), u1)  # (the shot's first frame has no move of its own)
        together, spread, corner = (_median(v[moves]) for v in (track.together, track.spread, corners))
        stills = track.still[moves][np.isfinite(track.still[moves])]
        if together < MIN_TOGETHER or spread < MIN_SPREAD:
            shot["why"] = "not the camera"  # a person moving in a still shot, or on a plain wall: the frame is still
            continue
        if shake < SHAKY_MIN and roll < SHAKY_ROLL:
            shot["why"] = "steady"
            continue
        if corner < MIN_CORNERS:
            # one thing moves on a plain background: a camera's shake holds hand tremor, a person's sway does not
            fine = [p - _smooth(p, 0.187 / HAND_HZ * track.fps) for p in path[:2]]  # (the Gaussian's half power)
            hand = float(np.sqrt(np.mean(fine[0][seen] ** 2 + fine[1][seen] ** 2))) / max(shake, 1e-9)
            shot["hand_share"] = round(hand, 2)
            if shake < SHAKY_MIN or hand < HAND_SHARE:
                shot["why"] = "not the camera"
                continue
        if len(stills) < MIN_STILL_FRAMES:
            shot["why"] = "cannot tell"     # too little moved to see whether a HUD or a logo stays put
            continue
        if float(np.mean(stills >= 1)) >= STILL_FRAMES:
            shot["why"] = "fixed overlay"   # a game's HUD, a screen's toolbar, a logo: steadying would make it shake
            continue
        cx, cy, ca = -rx, -ry, -ra
        need = _zoom_needed(cx[seen], cy[seen], ca[seen], aspect)
        z = min(max_zoom, float(np.quantile(need, 0.98)))
        z = max(1.0, math.ceil(z * 200 - 1e-6) / 200)
        k = _fit(cx, cy, ca, z, aspect)
        tx[a:b], ty[a:b], ta[a:b], zoom[a:b] = k * cx, k * cy, k * ca, z
        shot.update(steadied=True, zoom=round(z, 3))
    return Plan(track.t0, track.fps, aspect, tx, ty, ta, zoom, shots, span)


def _calm(path: str, t0: float, length: float, fps: float, frame_size: tuple[int, int],
          cancelled: Callable[[], bool] | None) -> bool:
    """A stretch over FULL_S is sampled first (PROBE_S every PROBE_EVERY_S): True when every sample is calm (nothing
    to steady, nothing more to read). A shorter one is always measured whole."""
    if length <= FULL_S:
        return False
    count = int(math.ceil(length / PROBE_EVERY_S))
    for i in range(count):
        at = t0 + min(length - PROBE_S, i * PROBE_EVERY_S + (PROBE_EVERY_S - PROBE_S) / 2)
        if plan(measure(path, at, PROBE_S, fps, frame_size, cancelled)).active:
            return False
    return True


def for_stretch(path: str, t0: float, length: float, fps: float, frame_size: tuple[int, int],
                cache: Path | None = None, cancelled: Callable[[], bool] | None = None,
                span: tuple[float, float] | None = None, exact: bool = False) -> Plan | None:
    """The steadying plan for `length` seconds of `path` from `t0` on the grid `t0 + k / fps`, or None when nothing
    in it needs steadying. `span`: the part the clip shows (file seconds; the whole stretch when None); `exact`: the
    grid of the file's own frame times (see _frames). The measurement is cached (`cache`: a folder) by the file, the
    stretch and the grid."""
    try:
        st = Path(path).stat()
        name = hashlib.sha256(json.dumps([VERSION, str(Path(path).resolve()), st.st_size, int(st.st_mtime),
                                          round(t0, 6), round(length, 3), fps, list(frame_size), exact]).encode())
        cached = cache / f"steady-{name.hexdigest()[:24]}.json" if cache is not None else None
        track = None
        if cached is not None and cached.is_file():
            try:
                saved = json.loads(cached.read_text(encoding="utf-8"))
                track = None if saved.get("calm") else Track.from_json(saved)
                if saved.get("calm"):
                    return None
            except (ValueError, KeyError, TypeError):
                track = None
        if track is None:
            if _calm(path, t0, length, fps, frame_size, cancelled):
                if cached is not None:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    cached.write_text(json.dumps({"v": VERSION, "calm": True}), encoding="utf-8")
                return None
            track = measure(path, t0, length, fps, frame_size, cancelled, exact)
            if cached is not None:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(track.to_json()), encoding="utf-8")
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - steadying is an extra: the clip renders as shot without it
        log.warning("could not measure camera shake in %s: %s", Path(path).name, exc)
        return None
    p = plan(track, span=span)
    return p if p.active else None

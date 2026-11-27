"""Steadying shaky camera footage (batch 4d of the editing-quality work; research in
docs/clipforge/EDITING_CRAFT_RESEARCH.md, what the owner sees in docs/clipforge/STEADY.md).

Only footage that shakes is touched, and only camera footage: a recording on a tripod, a game or a screen
recording is left exactly as it is. For footage that shakes:

1. **Measure** (`measure`): the picture is read small (MEASURE_W wide, grey) on the clip's own frame grid; corners are
   tracked from frame to frame (OpenCV: goodFeaturesToTrack, calcOpticalFlowPyrLK) and the camera's move between two
   frames is the similarity that most of them agree on (estimateAffinePartial2D with RANSAC): a shift and a roll. A
   frame where tracking fails or the picture jumps starts a new shot. A long stretch is first sampled (`PROBE_S`
   every `PROBE_EVERY_S`): when every sample is calm, nothing more is read.
2. **Smooth** (`plan`): per shot, the camera's path is smoothed (a Gaussian of `SMOOTH_S`), so hand shake (2-12 Hz)
   goes while a pan, a tilt or a walk stays. What is left (the path minus its smoothed self) is the shake.
3. **Decide**: a shot is steadied when it shakes (`SHAKY_MIN` of the width, or `SHAKY_ROLL` degrees, as RMS), when
   most tracked points move together and all over the picture (the camera moved, not a person in a still shot:
   `MIN_TOGETHER`, `MIN_SPREAD`), and when hardly any point stays put while the picture moves (a game's HUD, a
   screen's toolbar or a logo, which steadying would make shake: `MAX_STILL`).
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .common import Cancelled
from .ffmpeg_utils import NO_WINDOW, ffmpeg_bin

log = logging.getLogger("clipfoundry.pipeline.steady")

VERSION = 1
MEASURE_W = 480        # the width the picture is measured at
SMOOTH_S = 0.45        # the smoothed camera path (Gaussian sigma, seconds): shake goes, a pan or a walk stays
SHAKY_MIN = 0.0025     # RMS shake (share of the width) from which a shot counts as shaky (about 5 px at 1920)
SHAKY_ROLL = 0.25      # or RMS roll, degrees
MAX_ZOOM = 1.10        # the most a shot is enlarged to hide the moving edges
MIN_SHOT_S = 1.0       # shorter shots are left alone
MIN_TOGETHER = 0.5     # median share of tracked points that move with the camera's move
MAX_STILL = 0.03       # median share of points that stay put while the picture moves (a HUD, a toolbar, a logo)
MIN_SPREAD = 0.4       # median share of the picture the points moving with the camera span (convex hull)
MIN_POINTS = 12        # fewer tracked points: the frame cannot be measured (a new shot starts)
CUT_JUMP = 0.2         # a move over this share of the width between two frames is a cut or a whip pan
PROBE_S = 2.0          # a long stretch is sampled first: this long ...
PROBE_EVERY_S = 20.0   # ... every this many seconds (at least 3 samples)
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
    still: np.ndarray               # share of points that stayed put while the picture moved (nan: it did not)
    spread: np.ndarray              # share of the picture spanned by the points that moved with the camera
    cuts: list[int] = field(default_factory=lambda: [0])   # first frame of each shot

    def to_json(self) -> dict:
        def r(a):
            return [None if not math.isfinite(float(v)) else round(float(v), 6) for v in a]
        return {"v": VERSION, "t0": self.t0, "fps": self.fps, "size": list(self.size), "dx": r(self.dx),
                "dy": r(self.dy), "da": r(self.da), "together": r(self.together), "still": r(self.still),
                "spread": r(self.spread), "cuts": self.cuts}

    @classmethod
    def from_json(cls, d: dict) -> "Track":
        def a(v):
            return np.array([np.nan if x is None else x for x in v], float)
        return cls(float(d["t0"]), float(d["fps"]), tuple(d["size"]), a(d["dx"]), a(d["dy"]), a(d["da"]),
                   a(d["together"]), a(d["still"]), a(d["spread"]), [int(c) for c in d["cuts"]])


@dataclass
class Plan:
    """Per frame of the grid `t0 + k / fps`: the correction (tx, ty: share of the width; ta: radians) and the zoom;
    `shots` says what was decided for each shot and why."""
    t0: float
    fps: float
    aspect: float                   # height / width of the picture
    tx: np.ndarray
    ty: np.ndarray
    ta: np.ndarray
    zoom: np.ndarray
    shots: list[dict]

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

    def key(self) -> str:
        """Changes whenever any correction does (cache keys of rendered pieces)."""
        data = np.round(np.stack([self.tx, self.ty, self.ta, self.zoom - 1.0]) * 1e5).astype(np.int64)
        return hashlib.sha256(json.dumps([VERSION, self.t0, self.fps, data.tolist()]).encode()).hexdigest()[:20]

    def summary(self) -> dict:
        """What the render notes keep: seconds steadied, the largest zoom, the strongest shake (share of the width,
        in %) and each steadied shot."""
        done = [s for s in self.shots if s.get("steadied")]
        return {"seconds": round(sum(s["end_s"] - s["start_s"] for s in done), 2),
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
            cancelled: Callable[[], bool] | None):
    aw, ah = size
    cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{t0:.3f}", "-i", str(path),
           "-t", f"{length:.3f}", "-map", "0:v:0", "-an", "-sn",
           "-vf", f"fps={fps},scale={aw}:{ah}:flags=area,format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]
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


def _move(prev: np.ndarray, cur: np.ndarray) -> tuple[float, float, float, float, float, float] | None:
    """The camera's move from `prev` to `cur` (dx, dy in pixels, roll in radians, both about the centre), the share
    of tracked points that agree with it, the share that stayed put while the picture moved (nan when it did not
    move) and the share of the picture the agreeing points span (their convex hull). None: it cannot be measured
    (too few points, or the picture changed completely)."""
    import cv2

    pts = cv2.goodFeaturesToTrack(prev, maxCorners=200, qualityLevel=0.01, minDistance=10, blockSize=7)
    if pts is None or len(pts) < MIN_POINTS:
        return None
    nxt, status, _err = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None, winSize=(21, 21), maxLevel=3)
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
    span = cv2.contourArea(cv2.convexHull(p0[agree].astype(np.float32))) / float(w * h) if agree.sum() >= 3 else 0.0
    centre = np.array([w / 2.0, h / 2.0])
    moved = m[:, :2] @ centre + m[:, 2] - centre
    roll = math.atan2(float(m[1, 0]), float(m[0, 0]))
    flow = np.linalg.norm(p1 - p0, axis=1)
    still = float((flow < 0.3).mean()) if math.hypot(*moved) > 1.5 else math.nan
    return float(moved[0]), float(moved[1]), roll, together, still, float(span)


def measure(path: str, t0: float, length: float, fps: float, frame_size: tuple[int, int],
            cancelled: Callable[[], bool] | None = None) -> Track:
    """The camera's move over `length` seconds from `t0`, on the grid `t0 + k / fps` (the clip renderer's own)."""
    size = _size(*frame_size)
    aw = size[0]
    dx, dy, da, together, still, spread, cuts = [], [], [], [], [], [], [0]
    prev = None
    for k, cur in enumerate(_frames(path, t0, length, fps, size, cancelled)):
        got = _move(prev, cur) if prev is not None else None
        if prev is not None and (got is None or math.hypot(got[0], got[1]) > CUT_JUMP * aw or got[3] < 0.25):
            cuts.append(k)  # a cut, a whip pan or a picture that cannot be followed: a new shot from here
            got = None
        if got is None:
            dx.append(0.0)
            dy.append(0.0)
            da.append(0.0)
            together.append(math.nan)
            still.append(math.nan)
            spread.append(math.nan)
        else:
            dx.append(got[0] / aw)
            dy.append(got[1] / aw)
            da.append(got[2])
            together.append(got[3])
            still.append(got[4])
            spread.append(got[5])
        prev = cur
    a = lambda v: np.array(v, float)  # noqa: E731
    return Track(t0, fps, size, a(dx), a(dy), a(da), a(together), a(still), a(spread), cuts)


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
    return float(np.nanmedian(v)) if np.any(np.isfinite(v)) else 0.0


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


def plan(track: Track, max_zoom: float = MAX_ZOOM) -> Plan:
    """The corrections for a measured stretch: only shots that shake, of camera footage, are steadied."""
    n = len(track.dx)
    aspect = track.size[1] / max(1, track.size[0])
    tx, ty, ta, zoom = np.zeros(n), np.zeros(n), np.zeros(n), np.ones(n)
    shots = []
    edges = sorted({c for c in track.cuts if 0 <= c < n} | {0})
    for a, b in zip(edges, edges[1:] + [n]):
        shot = {"start_s": round(track.t0 + a / track.fps, 3), "end_s": round(track.t0 + b / track.fps, 3),
                "steadied": False, "zoom": 1.0, "shake_pct": 0.0}
        shots.append(shot)
        if b - a < MIN_SHOT_S * track.fps:
            shot["why"] = "short"
            continue
        mx, my, ma = (np.nan_to_num(v[a:b].copy()) for v in (track.dx, track.dy, track.da))
        mx[0] = my[0] = ma[0] = 0.0  # the move into the shot's first frame belongs to the cut
        path = [np.cumsum(v) for v in (mx, my, ma)]
        smooth = [_smooth(v, SMOOTH_S * track.fps) for v in path]
        rx, ry, ra = (p - s for p, s in zip(path, smooth))
        shake = float(np.sqrt(np.mean(rx ** 2 + ry ** 2)))
        roll = math.degrees(float(np.sqrt(np.mean(ra ** 2))))
        shot.update(shake_pct=round(100 * shake, 3), roll_deg=round(roll, 3))
        together, still, spread = (_median(v[a + 1:b]) for v in (track.together, track.still, track.spread))
        if together < MIN_TOGETHER or spread < MIN_SPREAD:
            shot["why"] = "not the camera"  # a person moving in a still shot (or nothing else to follow)
            continue
        if still > MAX_STILL:
            shot["why"] = "fixed overlay"   # a game's HUD, a screen's toolbar, a logo: steadying would make it shake
            continue
        if shake < SHAKY_MIN and roll < SHAKY_ROLL:
            shot["why"] = "steady"
            continue
        cx, cy, ca = -rx, -ry, -ra
        need = _zoom_needed(cx, cy, ca, aspect)
        z = min(max_zoom, float(np.quantile(need, 0.98)))
        z = max(1.0, math.ceil(z * 200 - 1e-6) / 200)
        k = _fit(cx, cy, ca, z, aspect)
        tx[a:b], ty[a:b], ta[a:b], zoom[a:b] = k * cx, k * cy, k * ca, z
        shot.update(steadied=True, zoom=round(z, 3))
    return Plan(track.t0, track.fps, aspect, tx, ty, ta, zoom, shots)


def _calm(path: str, t0: float, length: float, fps: float, frame_size: tuple[int, int],
          cancelled: Callable[[], bool] | None) -> bool:
    """A long stretch is sampled first: True when every sample is calm (nothing to steady, nothing more to read)."""
    count = max(3, int(length // PROBE_EVERY_S))
    if length < count * PROBE_S * 2:
        return False
    for i in range(count):
        at = t0 + (length - PROBE_S) * (i + 0.5) / count
        if plan(measure(path, at, PROBE_S, fps, frame_size, cancelled)).active:
            return False
    return True


def for_stretch(path: str, t0: float, length: float, fps: float, frame_size: tuple[int, int],
                cache: Path | None = None, cancelled: Callable[[], bool] | None = None) -> Plan | None:
    """The steadying plan for `length` seconds of `path` from `t0` on the grid `t0 + k / fps`, or None when nothing
    in it needs steadying. The measurement is cached (`cache`: a folder) by the file, the stretch and the grid."""
    try:
        st = Path(path).stat()
        name = hashlib.sha256(json.dumps([VERSION, str(Path(path).resolve()), st.st_size, int(st.st_mtime),
                                          round(t0, 3), round(length, 3), fps, list(frame_size)]).encode())
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
            track = measure(path, t0, length, fps, frame_size, cancelled)
            if cached is not None:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(track.to_json()), encoding="utf-8")
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - steadying is an extra: the clip renders as shot without it
        log.warning("could not measure camera shake in %s: %s", Path(path).name, exc)
        return None
    p = plan(track)
    return p if p.active else None

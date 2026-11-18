"""Smart 9:16 framing.

Samples the clip at a low frame rate, detects faces (OpenCV YuNet), estimates
who is talking from mouth-region motion, finds salient screen content from
motion/edge energy, detects hard cuts, and turns the per-sample targets into a
smooth "virtual camera" path (dead-zone + eased velocity + gaussian smoothing,
with instant re-framing on scene cuts).

Split view: a stream or screen recording often shows a small face cam laid over the game or screen. Following that
face parks the 9:16 crop on its corner and loses the action, so `find_cam` looks for a small face that stays in one
place, with the cam's own rectangle around it, and `plan` then answers with a "split" plan: the cam fills the top of
the frame and the middle of the rest of the picture fills the part below it.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

import numpy as np

from .. import config
from .common import JobContext, log
from .ffmpeg_utils import NO_WINDOW, MediaWatchdog, ffmpeg_bin

ANALYSIS_FPS = 8.0
ANALYSIS_W = 640
TARGET_AR = 9 / 16

# ---- split view (a face cam over a game or screen)
SPLIT_LAYOUTS = ("auto", "split")   # "auto": split view when a face cam is found; "split": whenever a face is found
CAM_MIN_FACE_H = 0.035      # the smallest face looked for in a cam (the detector's limit at the analysis size)
CAM_PRESENCE = 0.5          # the face is in at least half of the samples ...
CAM_MAX_FACE_H = 0.24       # ... is small (a taller face is the camera's own picture, not a cam laid over another)
CAM_MAX_SPREAD = 1.2        # ... and stays within about one face width of one spot
CAM_FORCED_PRESENCE = 0.25  # when the owner chose split view: a small face seen in a quarter of the samples
CAM_MAX_AREA = 0.36         # a cam covering more of the frame than this is the picture itself
CAM_SIDE = 0.45             # how steadily an edge must show along a whole side to be the cam's border (0-1)
CAM_SCORE = 0.6             # the four sides together
CAM_SIDE_ALONE = 0.6        # the same two when nothing around the cam moves, so its edges are all there is to go
CAM_SCORE_ALONE = 0.75      # by: a person in front of a poster or a window has edges around the face too
CAM_FRAME_EDGE = 0.55       # what a side lying on the edge of the frame counts for (there is no edge to measure)
CAM_MOVING = 0.08           # edges come and go in enough of the picture for movement to tell cam from game
CAM_STILL = 0.3             # share of still picture in a strip that makes it the cam's own background
CAM_FALL = 0.35             # ... and how much less of it there is just past the cam's side
CAM_RUNS_ON = 0.6           # a line that goes on this steadily past a corner is not that rectangle's own side
CAM_FRAME_WIDTH = 5         # a drawn frame around the cam is at most this wide, in analysis pixels
CAM_BORDERLESS_FACE_H = 0.2  # a cam without a border (cut out over the game) needs a smaller, steadier face ...
CAM_BORDERLESS_PRESENCE = 0.7
CAM_BORDERLESS_MOTION = 0.5  # ... off to one side of a picture that moves
SPLIT_TOP = (0.30, 0.42)    # the cam panel's share of the output height; the seam stays clear of the apps' buttons
SPLIT_SHIFT = 0.10          # how far the lower panel may move off-centre to leave the cam out of it
SPLIT_CLEAR = 0.012         # ... and how far past the cam it then starts, so the cam's drawn frame stays out too


@dataclass
class Plan:
    mode: str
    fps: float
    n: int
    cx: np.ndarray  # normalised crop centre per output frame (source timeline)
    cy: np.ndarray
    cuts: list[float] = field(default_factory=list)
    faces_found: int = 0
    info: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"mode": self.mode, "fps": self.fps, "n": self.n, "cx": np.round(self.cx, 5).tolist(),
                "cy": np.round(self.cy, 5).tolist(), "cuts": self.cuts, "faces_found": self.faces_found,
                "info": self.info}

    @staticmethod
    def from_json(d: dict) -> "Plan":
        return Plan(d["mode"], d["fps"], d["n"], np.asarray(d["cx"], dtype=np.float64),
                    np.asarray(d["cy"], dtype=np.float64), d.get("cuts", []), d.get("faces_found", 0),
                    d.get("info", {}))


def crop_fraction(src_w: int, src_h: int) -> tuple[float, float]:
    """Size of the largest 9:16 box inside the frame, as fractions of width/height."""
    if src_w / max(1, src_h) > TARGET_AR:
        return (src_h * TARGET_AR) / src_w, 1.0
    return 1.0, (src_w / TARGET_AR) / src_h


def static_plan(mode: str, fps: float, n: int, x: float = 0.5, y: float = 0.5) -> Plan:
    return Plan(mode, fps, n, np.full(n, x), np.full(n, y))


# --------------------------------------------------------------- sampling
def _sample_frames(src: str, start: float, dur: float, src_w: int, src_h: int, ctx: JobContext | None):
    aw = min(ANALYSIS_W, src_w) if src_w >= src_h else max(2, int(min(ANALYSIS_W, src_h) * src_w / src_h))
    aw -= aw % 2
    ah = int(round(src_h * aw / src_w / 2)) * 2
    cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", src,
           "-t", f"{dur:.3f}", "-map", "0:v:0", "-vf", f"fps={ANALYSIS_FPS},scale={aw}:{ah}", "-an",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    size = aw * ah * 3
    with MediaWatchdog(ctx.cancelled if ctx else None, max(600.0, dur * 20)) as watch:
        proc = watch.add(subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          creationflags=NO_WINDOW))
        k = 0
        while True:
            watch.check()
            buf = proc.stdout.read(size)  # type: ignore[union-attr]
            watch.check()
            if len(buf) < size:
                break
            yield k / ANALYSIS_FPS, np.frombuffer(buf, np.uint8).reshape(ah, aw, 3)
            k += 1


def _detector(w: int, h: int):
    import cv2

    if not config.YUNET_MODEL.exists() or not hasattr(cv2, "FaceDetectorYN"):
        return None
    try:
        return cv2.FaceDetectorYN.create(str(config.YUNET_MODEL), "", (w, h), 0.6, 0.3, 50)
    except Exception as exc:  # noqa: BLE001
        log.warning("Face detector unavailable: %s", exc)
        return None


@dataclass
class Track:
    tid: int
    boxes: dict = field(default_factory=dict)      # sample idx -> (x, y, w, h) normalised
    activity: dict = field(default_factory=dict)   # sample idx -> mouth motion
    last_roi: object = None
    last_idx: int = -10

    @property
    def presence(self) -> int:
        return len(self.boxes)

    def mean_area(self) -> float:
        return float(np.mean([b[2] * b[3] for b in self.boxes.values()])) if self.boxes else 0.0


def analyze(src: str, start: float, end: float, src_w: int, src_h: int, ctx: JobContext | None = None,
            layout: bool = False) -> dict:
    """With `layout`, also what `find_cam` reads: where edges stay put over the whole clip ("edge_map": the share
    of samples with an edge at each analysis pixel) and "cam_tracks", the faces down to CAM_MIN_FACE_H of the
    picture's height. "tracks" keeps its own, larger smallest face, so a clip without a cam is framed as before."""
    import cv2

    dur = max(0.1, end - start)
    edge_sum = None
    det = None
    tracks: list[Track] = []
    cam_tracks: list[Track] = []

    def follow(pool: list[Track], idx: int, box: tuple[float, float, float, float]) -> Track:
        """The track in `pool` this face continues, or a new one."""
        cxn, cyn = box[0] + box[2] / 2, box[1] + box[3] / 2
        best, best_d = None, 1e9
        for tr in pool:
            if idx - tr.last_idx > 16:
                continue
            bx, by, bw, bh = tr.boxes[tr.last_idx]
            d = np.hypot(bx + bw / 2 - cxn, by + bh / 2 - cyn)
            if d < max(bw, box[2]) * 1.2 and d < best_d:
                best, best_d = tr, d
        if best is None or idx in best.boxes:
            best = Track(len(pool))
            pool.append(best)
        best.boxes[idx] = box
        return best
    times: list[float] = []
    hists: list[np.ndarray] = []
    col_energy: list[np.ndarray] = []
    row_energy: list[np.ndarray] = []
    edge_density, saturation, motion_level = [], [], []
    prev_gray = None
    for idx, (t, frame) in enumerate(_sample_frames(src, start, dur, src_w, src_h, ctx)):
        h, w = frame.shape[:2]
        if det is None and idx == 0:
            det = _detector(w, h) or False
        times.append(t)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
        hists.append(cv2.normalize(hist, hist).flatten())
        saturation.append(float(hsv[..., 1].mean()))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (160, max(2, int(160 * h / w))), interpolation=cv2.INTER_AREA)
        edges = cv2.Canny(small, 80, 160)
        edge_density.append(float((edges > 0).mean()))
        if layout:
            fine = (cv2.Canny(gray, 60, 150) > 0).astype(np.float32)
            edge_sum = fine if edge_sum is None else edge_sum + fine
        if prev_gray is not None and prev_gray.shape == small.shape:
            diff = cv2.GaussianBlur(cv2.absdiff(small, prev_gray), (5, 5), 0).astype(np.float32)
            motion_level.append(float(diff.mean()))
            col = diff.sum(axis=0) + 0.35 * edges.sum(axis=0) / 255.0 * diff.mean()
            row = diff.sum(axis=1)
        else:
            col = edges.sum(axis=0).astype(np.float32) / 255.0 * 0.01
            row = edges.sum(axis=1).astype(np.float32) / 255.0 * 0.01
        col_energy.append(col)
        row_energy.append(row)
        prev_gray = small

        if det:
            _, faces = det.detect(frame)
            faces = faces if faces is not None else []
            for f in faces:
                x, y, fw, fh = (float(v) for v in f[:4])
                box = (x / w, y / h, fw / w, fh / h)
                if layout and fh >= CAM_MIN_FACE_H * h:
                    follow(cam_tracks, idx, box).last_idx = idx
                if fh < 0.06 * h:
                    continue
                best = follow(tracks, idx, box)
                # mouth region motion (lip activity proxy)
                rx, ry, lx, ly = f[10], f[11], f[12], f[13]
                mx0 = int(max(0, min(rx, lx) - 0.15 * fw))
                mx1 = int(min(w, max(rx, lx) + 0.15 * fw))
                my0 = int(max(0, min(ry, ly) - 0.12 * fh))
                my1 = int(min(h, max(ry, ly) + 0.22 * fh))
                act = 0.0
                if mx1 - mx0 > 3 and my1 - my0 > 3:
                    roi = cv2.resize(gray[my0:my1, mx0:mx1], (32, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
                    roi = (roi - roi.mean()) / (roi.std() + 8.0)
                    if best.last_roi is not None and idx - best.last_idx == 1:
                        act = float(np.abs(roi - best.last_roi).mean())
                    best.last_roi = roi
                best.activity[idx] = act
                best.last_idx = idx
    n = len(times)
    cuts = []
    for k in range(1, len(hists)):
        if cv2.compareHist(hists[k - 1], hists[k], cv2.HISTCMP_CORREL) < 0.55:
            cuts.append(round((times[k - 1] + times[k]) / 2, 3))
    out = {"times": times, "n": n, "tracks": tracks, "cuts": cuts, "col": col_energy, "row": row_energy,
           "edge": float(np.mean(edge_density)) if edge_density else 0.0,
           "sat": float(np.mean(saturation)) if saturation else 0.0,
           "motion": float(np.mean(motion_level)) if motion_level else 0.0}
    if layout and edge_sum is not None:
        out["edge_map"] = edge_sum / max(1, n)
        out["cam_tracks"] = cam_tracks
    return out


def precise_cuts(src: str, t0: float, t1: float) -> list[float]:
    """Frame-exact hard cuts in [t0, t1] via PySceneDetect (short windows only: cheap)."""
    try:
        import scenedetect
        from scenedetect import ContentDetector

        scenes = scenedetect.detect(src, ContentDetector(threshold=27.0, min_scene_len=3),
                                    start_time=max(0.0, t0), end_time=max(t0 + 0.2, t1))
    except Exception as exc:  # noqa: BLE001 - optional refinement
        log.debug("scenedetect unavailable: %s", exc)
        return []

    def secs(tc) -> float:
        v = getattr(tc, "seconds", None)
        return float(v) if isinstance(v, (int, float)) else float(tc.get_seconds())

    return [secs(s) for s, _ in scenes[1:]]


def refine_cuts(src: str, start: float, approx: list[float]) -> list[float]:
    out = []
    for c in approx:
        exact = precise_cuts(src, start + c - 0.35, start + c + 0.35)
        out.append(round(min(exact, key=lambda e: abs(e - start - c)) - start, 3) if exact else c)
    return out


# --------------------------------------------------------------- face cam
def _face_groups(a: dict) -> list[dict]:
    """Faces by the place they stay in, most seen first. A track breaks when detection drops out for a moment, so
    tracks around one spot count as one face: {"box": median (x, y, w, h), "presence": share of samples, "spread":
    how far its centre wanders, in face widths, "samples": the sample numbers}."""
    n = max(1, a["n"])
    groups: list[dict] = []
    for tr in sorted((t for t in a.get("cam_tracks", a["tracks"]) if t.presence >= 3), key=lambda t: -t.presence):
        box = np.median(np.asarray(list(tr.boxes.values()), dtype=np.float64), axis=0)
        cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
        home = next((g for g in groups if np.hypot(g["cx"] - cx, g["cy"] - cy) < 1.5 * max(g["w"], box[2])), None)
        if home is None:
            home = {"cx": cx, "cy": cy, "w": box[2], "boxes": {}}
            groups.append(home)
        for idx, b in tr.boxes.items():
            home["boxes"].setdefault(idx, b)
    out = []
    for g in groups:
        boxes = np.asarray(list(g["boxes"].values()), dtype=np.float64)
        box = np.median(boxes, axis=0)
        centres = boxes[:, :2] + boxes[:, 2:] / 2
        away = np.hypot(*(centres - (box[:2] + box[2:] / 2)).T)
        out.append({"box": tuple(float(v) for v in box), "presence": len(boxes) / n,
                    "spread": float(np.percentile(away, 90) / max(1e-6, box[2])), "samples": set(g["boxes"])})
    return sorted(out, key=lambda g: -g["presence"])


def _peaks(profile: np.ndarray, lo: int, hi: int, floor: float, keep: int = 4) -> list[int]:
    """Where profile[lo:hi] has its local maxima at or above `floor`: the strongest `keep`, and always the one
    nearest each end (a cam's border is the outermost steady line, whatever lines its own picture holds)."""
    lo, hi = max(0, lo), min(len(profile), hi)
    found: list[tuple[int, float]] = []
    for i in range(lo, hi):
        v = float(profile[i])
        if v >= floor and v >= float(profile[max(lo, i - 2):min(hi, i + 3)].max()) - 1e-9:
            if found and i - found[-1][0] <= 2:
                if v >= found[-1][1]:
                    found[-1] = (i, v)
                continue
            found.append((i, v))
    strongest = sorted(found, key=lambda item: -item[1])[:keep]
    return sorted({i for i, _ in [*strongest, *found[:1], *found[-1:]]})


def _falls(quiet: np.ndarray, lo: int, hi: int, outward: int, cell: int, keep: int = 3) -> list[int]:
    """Places in quiet[lo:hi] (how much of the picture is still, along a line leading away from the face) where
    still picture turns into moving picture going `outward` (+1 or -1): the cam's own background ends there and the
    game begins. The steepest `keep`, each the last still place before the fall."""
    n = len(quiet)
    found: list[tuple[float, int]] = []
    for i in range(max(cell, lo), min(n - cell, hi)):
        inside = quiet[i - outward * cell:i] if outward > 0 else quiet[i + 1:i + 1 + cell]
        beyond = quiet[i + 1:i + 1 + cell] if outward > 0 else quiet[i - cell:i]
        if len(inside) and len(beyond):
            drop = float(inside.mean() - beyond.mean())
            if drop >= CAM_FALL and float(inside.mean()) >= CAM_STILL:
                found.append((drop, i))
    out: list[int] = []
    for _, i in sorted(found, reverse=True):
        if all(abs(i - j) > cell for j in out):
            out.append(i)
        if len(out) >= keep:
            break
    return sorted(out)


def _cam_rectangle(edge_map: np.ndarray, face: tuple[float, float, float, float]) -> tuple[list[float], float] | None:
    """The cam's rectangle around `face`: ((x0, y0, x1, y1) normalised, score 0-1), or None.

    Two things mark a cam's border, and both are read from `edge_map` (how often each pixel is an edge over the
    clip). Its edge stays put for the whole clip while the game changes beside it; and the still picture of the
    cam's own background (edges that are always or never there) meets a picture that moves (edges that come and go).
    Brightness changes in the cam, such as a lamp or the camera's exposure, move no edges, so they do not count as
    movement. Places for each side are first looked for beside the face, then every combination is scored along
    its whole length. A line that only passes behind the face (a door frame in the cam's own picture) has still
    picture on both sides and is not as long as the border, so it loses; a border too faint to show as an edge is
    still found by the movement beyond it; and a cam that reaches the edge of the frame needs no edge there. When
    the picture around the cam does not move (a menu, a desktop) only the edges count, and among rectangles that
    score about the same the largest wins: lines inside the cam's picture make smaller ones. The answer is the
    inside of the border, so a drawn frame stays out of the picture."""
    import cv2

    H, W = edge_map.shape
    raw = edge_map.astype(np.float32)
    steady = cv2.dilate(raw, np.ones((3, 3), np.uint8))  # an edge may sit a pixel either way from frame to frame
    sums = {}
    for name, picture in (("steady", steady), ("raw", raw)):   # running sums: any line's average in one step
        down, across = np.zeros((H + 1, W)), np.zeros((H, W + 1))
        np.cumsum(picture, axis=0, out=down[1:])
        np.cumsum(picture, axis=1, out=across[:, 1:])
        sums[name] = (down, across)
    cell = 4
    # An edge that is there in half of the samples belongs to a picture that moves: 4p(1-p) is 1 there, and 0 for
    # an edge that is always or never there.
    busy = cv2.blur(4.0 * raw * (1.0 - raw), (2 * cell + 1, 2 * cell + 1))
    level = float(np.percentile(busy, 80))
    still = None  # 1 where the picture hardly changes, summed for fast box averages; None: nothing moves around it
    if level >= CAM_MOVING:
        calm = (busy < max(0.02, 0.3 * level)).astype(np.float64)
        still = np.zeros((H + 1, W + 1))
        np.cumsum(np.cumsum(calm, axis=0), axis=1, out=still[1:, 1:])

    def calm_share(x0: int, y0: int, x1: int, y1: int) -> float | None:
        """Share of still picture in the box (None when the box is outside the frame)."""
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if x1 <= x0 or y1 <= y0:
            return None
        return float(still[y1, x1] - still[y0, x1] - still[y1, x0] + still[y0, x0]) / ((x1 - x0) * (y1 - y0))

    fx0, fy0, fw, fh = face[0] * W, face[1] * H, face[2] * W, face[3] * H
    fx1, fy1 = fx0 + fw, fy0 + fh
    r0, r1 = int(max(0, fy0 - 0.2 * fh)), int(min(H, fy1 + 0.3 * fh))   # rows and columns the cam certainly covers
    c0, c1 = int(max(0, fx0 - 0.2 * fw)), int(min(W, fx1 + 0.2 * fw))
    if r1 - r0 < 4 or c1 - c0 < 4:
        return None
    cols, rows = steady[r0:r1].mean(axis=0), steady[:, c0:c1].mean(axis=1)
    # A face is a tenth to a half of its cam's width and a sixth to a half of its height (someone leaning back in a
    # wide picture, or close to the lens), and not always in the middle.
    spans = {"l": (int(fx0 - 6.5 * fw), int(fx0 - 0.2 * fw)), "r": (int(fx1 + 0.2 * fw) + 1, int(fx1 + 6.5 * fw) + 1),
             "t": (int(fy0 - 3.0 * fh), int(fy0 - 0.15 * fh)), "b": (int(fy1 + 0.4 * fh) + 1, int(fy1 + 4.5 * fh) + 1)}
    sides: dict[str, list[tuple[int, bool]]] = {}
    for key, (lo, hi) in spans.items():
        profile, last = (cols, W - 1) if key in "lr" else (rows, H - 1)
        places = set(_peaks(profile, lo, hi, CAM_SIDE * 0.8))
        if still is not None:
            # how still the picture is beside (or above and below) the face, a little wider than the face itself
            a0, a1 = (int(max(0, fy0 - 0.6 * fh)), int(min(H, fy1 + 0.8 * fh))) if key in "lr" else \
                (int(max(0, fx0 - 1.2 * fw)), int(min(W, fx1 + 1.2 * fw)))
            wide = np.asarray([calm_share(i, a0, i + 1, a1) if key in "lr" else calm_share(a0, i, a1, i + 1)
                               for i in range(last + 1)], dtype=np.float64)
            places.update(_falls(wide, lo, hi, -1 if key in "lt" else 1, cell))
        found = [(i, False) for i in sorted(places)]
        if key in "lt" and lo <= 0:
            found.append((0, True))      # the cam may reach the edge of the frame, where there is no edge to see
        if key in "rb" and hi > last:
            found.append((last, True))
        if not found:
            return None
        sides[key] = found

    def edge_at(key: str, at: int, box: tuple[int, int, int, int], picture: str = "steady") -> float:
        """How steadily an edge shows along one side of the box, were that side at `at`."""
        left, top, right, bottom = box
        down, across = sums[picture]
        if key in "lr":
            return float(down[bottom + 1, at] - down[top, at]) / (bottom - top + 1) if 0 <= at < W else 0.0
        return float(across[at, right + 1] - across[at, left]) / (right - left + 1) if 0 <= at < H else 0.0

    def reaches_corners(key: str, at: int, box: tuple[int, int, int, int], whole: float) -> bool:
        """Does the edge along this side run to both of its ends? A border does; a line that only happens to lie
        above or beside the cam (a menu's own line) leaves the last stretch to the corner without an edge."""
        left, top, right, bottom = box
        lo, hi = (top, bottom) if key in "lr" else (left, right)
        tip = max(3, (hi - lo + 1) // 12)
        for a, b in ((lo, lo + tip - 1), (hi - tip + 1, hi)):
            part = (left, a, right, b) if key in "lr" else (a, top, b, bottom)
            if max(edge_at(key, at + d, part) for d in (-1, 0, 1)) < 0.5 * whole:
                return False
        return True

    def band(key: str, at: int, box: tuple[int, int, int, int], inside: bool) -> float | None:
        """Share of still picture in a strip two motion cells wide just inside or just outside a side."""
        left, top, right, bottom = box
        depth, gap = 2 * cell, 2
        inward = 1 if key in "lt" else -1
        near = at + (inward if inside else -inward) * gap
        far = near + (inward if inside else -inward) * depth
        lo, hi = min(near, far), max(near, far)
        return calm_share(lo, top, hi, bottom + 1) if key in "lr" else calm_share(left, lo, right + 1, hi)

    def ends_at_corners(key: str, at: int, box: tuple[int, int, int, int]) -> int:
        """How many of this side's two ends stop at the corner (0-2). A cam's border stops there; a line of the
        picture around it (a menu's grid) or inside it (a door frame crossed by a shelf) runs on past the corner."""
        left, top, right, bottom = box
        lo, hi = (top, bottom) if key in "lr" else (left, right)
        tip, gap, limit = max(4, (hi - lo + 1) // 10), 3, (H if key in "lr" else W)
        ends = 0
        for a, b in ((lo - gap - tip, lo - gap - 1), (hi + gap + 1, hi + gap + tip)):
            a, b = max(0, a), min(limit - 1, b)
            if b - a < 2:
                ends += 1        # the edge of the frame: nothing can run on
                continue
            part = (left, a, right, b) if key in "lr" else (a, top, b, bottom)
            ends += max(edge_at(key, at + d, part) for d in (-1, 0, 1)) < CAM_RUNS_ON
        return ends

    best: list[tuple[float, int, float, tuple[int, int, int, int], tuple[bool, ...], list[tuple[float, int]]]] = []
    for left, left_edge in sides["l"]:
        for right, right_edge in sides["r"]:
            w = right - left
            if not 1.6 * fw <= w <= 10.0 * fw:
                continue
            for top, top_edge in sides["t"]:
                for bottom, bottom_edge in sides["b"]:
                    h = bottom - top
                    on_edge = (left_edge, top_edge, right_edge, bottom_edge)
                    if not (1.6 * fh <= h <= 6.5 * fh and 0.6 <= w / h <= 2.4) or w * h > CAM_MAX_AREA * W * H \
                            or sum(on_edge) > 2:
                        continue
                    box = (left, top, right, bottom)
                    marks: list[tuple[float, int]] = []   # per side: its score, and where its edge is strongest
                    total, corners = 0.0, 0
                    for key, at, flat in zip("ltrb", box, on_edge):
                        inner = band(key, at, box, True) if still is not None else None
                        if flat:
                            if still is not None and (inner or 0.0) < CAM_STILL / 2:
                                break            # game right up to the edge of the frame: the cam ends earlier
                            value, line = (0.5 if still is not None else CAM_FRAME_EDGE), at
                            corners += 2
                        else:
                            edge, line = max((edge_at(key, at + d, box), at + d) for d in (-3, -2, -1, 0, 1, 2, 3))
                            if still is None:
                                value = edge
                                if edge < CAM_SIDE_ALONE:
                                    break
                            else:
                                outer = band(key, at, box, False)
                                differ = (1.0 - outer) * min(1.0, (inner or 0.0) / CAM_STILL) if outer is not None else 0.0
                                value = 0.5 * edge + 0.5 * differ
                                if edge < CAM_SIDE and differ < 0.5:
                                    break
                                line = line if edge >= CAM_SIDE else at
                            if edge >= CAM_SIDE and not reaches_corners(key, line, box, edge):
                                break
                            corners += ends_at_corners(key, line, box) if edge >= CAM_SIDE else 2
                        marks.append((value, line))
                        total += value
                    if len(marks) == 4 and total / 4 >= (0.5 if still is not None else CAM_SCORE_ALONE):
                        best.append((total / 4, corners, float(w * h), box, on_edge, marks))
    if not best:
        return None
    # Among rectangles that score about the same: the one whose sides stop at its corners, then the largest (lines
    # inside the cam's own picture make smaller ones).
    top_score = max(item[0] for item in best)
    score, _, _, box, on_edge, marks = max((item for item in best if item[0] >= 0.92 * top_score),
                                           key=lambda item: (item[1], item[2]))
    out = list(box)
    outers: dict[int, int] = {}       # per side with a steady edge: its outermost line ...
    inside: dict[int, set[int]] = {}  # ... and how far in from it other steady lines lie
    for index, (key, flat) in enumerate(zip("ltrb", on_edge)):
        if flat:
            continue
        outward = -1 if key in "lt" else 1
        at = marks[index][1]
        seen = edge_at(key, at, box)
        if seen < CAM_SIDE:
            # Found by the movement beyond it, which is not to the pixel: the faint edge next to it when there is
            # one, otherwise a little inside.
            faint, where = max((edge_at(key, at + d, box, "raw"), at + d) for d in range(-cell, cell + 1))
            out[index] = where - outward if faint >= CAM_SIDE / 3 else box[index] - outward * cell
            continue
        outer = at
        for step in range(1, 7):
            if edge_at(key, at + outward * step, box) >= max(CAM_SIDE, 0.85 * seen):
                outer = at + outward * step
        outers[index] = outer
        # a line may sit on either of two pixels from frame to frame, so two neighbours count together
        inside[index] = {step for step in range(1, CAM_FRAME_WIDTH + 1)
                         if edge_at(key, outer - outward * step, box, "raw")
                         + edge_at(key, outer - outward * (step + 1), box, "raw") >= CAM_SIDE}
    # A drawn frame is as wide on every side, so its inner edge is a line the same distance in on all of them; a
    # line like that on one side only belongs to the cam's own picture, which then starts right at the outer line.
    width = next((d for d in range(CAM_FRAME_WIDTH, 0, -1)
                  if len(inside) >= 2 and all({d - 1, d, d + 1} & steps for steps in inside.values())), 0)
    for index, outer in outers.items():
        outward = -1 if "ltrb"[index] in "lt" else 1
        own = max((d for d in (width - 1, width, width + 1) if d in inside[index]), default=0) if width else 0
        out[index] = outer - outward * (own + 1)
    left, top, right, bottom = out
    if right - left < 1.2 * fw or bottom - top < 1.2 * fh:
        return None
    return [max(0, left) / W, max(0, top) / H, min(W, right + 1) / W, min(H, bottom + 1) / H], score


def _overlap(a: list[float], b: list[float]) -> float:
    """Shared area of two (x0, y0, x1, y1) boxes over the area of both together."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    both = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - w * h
    return w * h / max(1e-9, both)


def find_cam(a: dict, force: bool = False, hint: dict | None = None) -> dict | None:
    """The face cam laid over the picture, from an `analyze(..., layout=True)` result: {"box": (x0, y0, x1, y1) and
    "face": (centre x, centre y, w, h), normalised; "kind": "border" (its rectangle was found) or "face" (a box
    around the face: a cam cut out over the game has no rectangle); "score"; "presence"}. None when the picture is
    not a small face in one place over something else.

    `force` (the owner chose split view) takes any small face that stays in the picture, with or without a
    rectangle around it: a streamer cut out over the game has none. A face that fills the picture is still the
    camera's own picture, and splitting that would only show it twice. `hint` is the cam found earlier in the same
    video: a cam found in about the same place gets exactly that rectangle, so every clip of one stream is framed
    alike, and it also stands in when the face is hidden for this clip but the rectangle's edges are still there."""
    groups = _face_groups(a)
    edge_map = a.get("edge_map")
    known = [float(v) for v in hint["box"]] if hint and len(hint.get("box") or []) == 4 else None
    if not groups:
        if known and edge_map is not None and _still_there(edge_map, known):
            return {"box": known, "face": list(hint.get("face") or _middle(known)), "kind": hint.get("kind") or "border",
                    "score": float(hint.get("score") or CAM_SCORE), "presence": 0.0, "from": "earlier"}
        return None
    cam = next((g for g in groups if g["box"][3] <= CAM_MAX_FACE_H and
                (g["presence"] >= CAM_FORCED_PRESENCE if force else
                 g["presence"] >= CAM_PRESENCE and g["spread"] <= CAM_MAX_SPREAD)), None)
    if cam is None:
        return None
    x, y, w, h = cam["box"]
    face = [x + w / 2, y + h / 2, w, h]
    others = [g for g in groups if g is not cam and g["presence"] >= 0.3]
    if not force and any(g["box"][3] > CAM_MAX_FACE_H for g in others):
        return None  # someone fills the picture: the small face is a guest or an inset, and the big one is followed
    found = _cam_rectangle(edge_map, cam["box"]) if edge_map is not None else None
    if found:
        box, score = found
        if not force and any(g["box"][2] * g["box"][3] >= 0.5 * w * h and not _inside(g["box"], box) for g in others):
            return None  # several people in one picture (an interview, a panel): the speaker is followed instead
        if not force and box[0] < 0.5 < box[2] and box[1] < 0.5 < box[3]:
            # A cam is put where it hides little, never over the middle of the picture: this is a person in front
            # of a window, a poster or a shelf, in the camera's own picture.
            return None
        if known and _overlap(box, known) >= 0.75:
            box = known
        return {"box": box, "face": face, "kind": "border", "score": round(score, 3), "presence": cam["presence"]}
    if known and _inside(cam["box"], known) and (edge_map is None or _still_there(edge_map, known)):
        return {"box": known, "face": face, "kind": hint.get("kind") or "border",
                "score": float(hint.get("score") or CAM_SCORE), "presence": cam["presence"], "from": "earlier"}
    side = min(face[0], 1 - face[0]) < 0.32 or min(face[1], 1 - face[1]) < 0.3
    if force or (h <= CAM_BORDERLESS_FACE_H and cam["presence"] >= CAM_BORDERLESS_PRESENCE and side and not others
                 and a.get("motion", 0.0) >= CAM_BORDERLESS_MOTION):
        return {"box": _around(cam["box"]), "face": face, "kind": "face", "score": 0.0, "presence": cam["presence"]}
    return None


def _around(face: tuple[float, float, float, float]) -> list[float]:
    """Head and shoulders around a face box (x, y, w, h), kept inside the frame."""
    x, y, w, h = face
    cx = x + w / 2
    return [max(0.0, cx - 1.4 * w), max(0.0, y - 0.7 * h), min(1.0, cx + 1.4 * w), min(1.0, y + 1.9 * h)]


def _inside(face: tuple[float, float, float, float], box: list[float]) -> bool:
    cx, cy = face[0] + face[2] / 2, face[1] + face[3] / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def _middle(box: list[float]) -> list[float]:
    """A stand-in face for a cam whose face is not seen: its usual place, upper middle of the cam."""
    w, h = box[2] - box[0], box[3] - box[1]
    return [box[0] + w / 2, box[1] + 0.42 * h, 0.3 * w, 0.4 * h]


def _still_there(edge_map: np.ndarray, box: list[float]) -> bool:
    """Do the sides of a cam rectangle found earlier still show as steady edges?"""
    import cv2

    H, W = edge_map.shape
    steady = cv2.dilate(edge_map.astype(np.float32), np.ones((7, 7), np.uint8))  # the saved box is set in from the border
    left, top = int(round(box[0] * W)), int(round(box[1] * H))
    right, bottom = min(W - 1, int(round(box[2] * W)) - 1), min(H - 1, int(round(box[3] * H)) - 1)
    if right - left < 4 or bottom - top < 4:
        return False
    sides = [steady[top:bottom + 1, left].mean() if left > 3 else None,
             steady[top:bottom + 1, right].mean() if right < W - 4 else None,
             steady[top, left:right + 1].mean() if top > 3 else None,
             steady[bottom, left:right + 1].mean() if bottom < H - 4 else None]
    seen = [float(v) for v in sides if v is not None]
    return len(seen) >= 2 and min(seen) >= CAM_SIDE


def split_layout(cam: dict, src_w: int, src_h: int, content_x: float | None = None) -> dict:
    """Where the two panels of a split view come from. The cam fills the top panel, whose height follows the cam's
    own shape within SPLIT_TOP; the lower panel shows the middle of the picture at full height, moved a little to the
    side when that leaves the cam out of it. `content_x` (the owner's own crop position) places the lower panel.

    Returns {"top": the top panel's share of the output height, "cam": box, "focus": the face's centre, "content":
    (centre x, centre y, width, height) of the lower panel's crop}, all normalised to the source picture."""
    x0, y0, x1, y1 = cam["box"]
    cam_w, cam_h = max(1e-6, (x1 - x0) * src_w), max(1e-6, (y1 - y0) * src_h)
    top = min(SPLIT_TOP[1], max(SPLIT_TOP[0], cam_h / cam_w * TARGET_AR))
    aspect = TARGET_AR / (1 - top)                       # the lower panel's width over its height
    cw = min(1.0, src_h * aspect / src_w)
    ch = 1.0 if cw < 1.0 else min(1.0, src_w / aspect / src_h)
    lo, hi = cw / 2, 1 - cw / 2
    if content_x is not None:
        cx = content_x
    else:
        cx = 0.5
        if (x0 + x1) / 2 < 0.5:
            cx += min(SPLIT_SHIFT, max(0.0, x1 + SPLIT_CLEAR - (cx - cw / 2)))
        else:
            cx -= min(SPLIT_SHIFT, max(0.0, (cx + cw / 2) - (x0 - SPLIT_CLEAR)))
    return {"top": round(top, 5), "cam": [round(float(v), 5) for v in cam["box"]],
            "focus": [round(float(cam["face"][0]), 5), round(float(cam["face"][1]), 5)],
            "content": [round(min(hi, max(lo, cx)), 5), 0.5, round(cw, 5), round(ch, 5)]}


# --------------------------------------------------------------- targets
def _choose_mode(a: dict) -> str:
    n = max(1, a["n"])
    frames_with_face = set()
    for tr in a["tracks"]:
        frames_with_face.update(tr.boxes)
    face_presence = len(frames_with_face) / n
    together = sum(1 for i in range(n) if sum(1 for t in a["tracks"] if i in t.boxes) >= 2)
    if face_presence >= 0.3:
        return "speaker" if together >= 0.15 * n else "face"
    if a["edge"] > 0.07 and a["sat"] < 70 and a["motion"] < 6:
        return "screen"
    # A missed face must not lock a narrow crop in the middle of moving footage (games, sports, profiles).
    return "motion" if a["motion"] > 0.25 else "screen" if a["edge"] > 0.03 else "center"


def speech_mask(times: list[float], speech: list[tuple[float, float]] | None, pad: float = 0.25) -> np.ndarray:
    """True at the sample times where someone is talking (word timings, clip-relative). All True if unknown."""
    t = np.asarray(times, dtype=np.float64)
    if speech is None:
        return np.ones(len(t), dtype=bool)
    mask = np.zeros(len(t), dtype=bool)
    for a, b in speech:
        mask |= (t >= a - pad) & (t <= b + pad)
    return mask


def _face_targets(a: dict, crop_w: float, crop_h: float, speaker: bool) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """Per-sample framing targets from face tracks, plus times where the camera should cut (speaker switch).

    Mouth movement only counts while someone is speaking (a["speech"]), so nodding, chewing or reacting during a
    pause never pulls the camera to another person, and the camera holds its shot through pauses.
    """
    n = a["n"]
    speech = a.get("speech")
    if speech is None or len(speech) != n:
        speech = np.ones(n, dtype=bool)
    xs, ys = np.full(n, np.nan), np.full(n, np.nan)
    switches: list[float] = []
    tracks: list[Track] = a["tracks"]
    if not tracks:
        return xs, ys, switches
    hold = int(ANALYSIS_FPS * 0.75)  # ride through short detection dropouts
    primary = max(tracks, key=lambda t: t.presence * t.mean_area())
    # smoothed speaking activity per track (a dropout counts as "no evidence", not silence)
    smooth: dict[int, np.ndarray] = {}
    for tr in tracks:
        ema = np.zeros(n)
        val = 0.0
        for i in range(n):
            if not speech[i]:
                val *= 0.9  # silence: mouth motion is not speech
            elif i in tr.activity and (i - 1) in tr.boxes:
                val = 0.7 * val + 0.3 * tr.activity[i]
            elif i not in tr.boxes:
                val *= 0.97
            ema[i] = val
        smooth[tr.tid] = ema
    last: dict[int, tuple[int, tuple]] = {}
    current = primary.tid
    last_switch = -99
    pending, pending_count = None, 0
    prev_x = None
    for i in range(n):
        for tr in tracks:
            if i in tr.boxes:
                last[tr.tid] = (i, tr.boxes[i])
        visible = {tid: box for tid, (j, box) in last.items() if i - j <= hold}
        if not visible:
            continue
        lefts = [b[0] for b in visible.values()]
        rights = [b[0] + b[2] for b in visible.values()]
        if len(visible) > 1 and max(rights) - min(lefts) <= crop_w * 0.85:
            # everyone fits in frame: centre the group
            xs[i] = (max(rights) + min(lefts)) / 2
            ys[i] = min(b[1] for b in visible.values()) + crop_h * 0.35
            prev_x = xs[i]
            continue
        if speaker and len(visible) > 1:
            cand = max(visible, key=lambda tid: smooth[tid][i])
            cur_act = smooth[current][i] if current in visible else -1.0
            if not speech[i] and current in visible:
                pending, pending_count = None, 0  # nobody is talking: hold the shot
            elif cand != current and (current not in visible or smooth[cand][i] > 1.3 * cur_act + 0.02):
                pending_count = pending_count + 1 if pending == cand else 1
                pending = cand
                if current not in visible or (pending_count >= 3 and i - last_switch >= 12):
                    current, last_switch, pending, pending_count = cand, i, None, 0
            else:
                pending, pending_count = None, 0
            tid = current if current in visible else cand
        else:
            tid = primary.tid if primary.tid in visible else max(visible, key=lambda k: visible[k][2] * visible[k][3])
        bx, by, bw, bh = visible[tid]
        xs[i] = bx + bw / 2
        ys[i] = by + bh / 2 + crop_h * 0.12  # keep eyes in the upper third
        if prev_x is not None and abs(xs[i] - prev_x) > 0.5 * crop_w and i > 0:
            switches.append(round(a["times"][i] - 0.5 / ANALYSIS_FPS, 3))  # far jump: cut, don't pan
        prev_x = xs[i]
    return xs, ys, switches


def _screen_targets(a: dict, crop_w: float, crop_h: float) -> tuple[np.ndarray, np.ndarray]:
    n = a["n"]
    xs, ys = np.full(n, np.nan), np.full(n, np.nan)
    for i in range(n):
        col = np.asarray(a["col"][i], dtype=np.float64)
        row = np.asarray(a["row"][i], dtype=np.float64)
        if col.sum() < 1e-6:
            continue
        W = len(col)
        win = max(1, int(round(crop_w * W)))
        if win >= W:
            xs[i] = 0.5
        else:
            cs = np.concatenate([[0.0], np.cumsum(col)])
            sums = cs[win:] - cs[:-win]
            # Many crop windows contain the same moving object. The first maximum pins it to the edge of
            # the crop; choose the equally good window nearest its measured centre instead.
            candidates = np.flatnonzero(sums >= sums.max() * 0.98)
            centre = float(np.dot(np.arange(W) + 0.5, col) / col.sum())
            k = int(candidates[np.argmin(abs(candidates + win / 2 - centre))])
            if sums[k] > 0.25 * col.sum():
                xs[i] = (k + win / 2) / W
        H = len(row)
        winh = max(1, int(round(crop_h * H)))
        if winh < H and row.sum() > 1e-6:
            cs = np.concatenate([[0.0], np.cumsum(row)])
            sums = cs[winh:] - cs[:-winh]
            k = int(np.argmax(sums))
            ys[i] = (k + winh / 2) / H
    return xs, ys


# ------------------------------------------------------------ smoothing
def _fill(arr: np.ndarray, default: float) -> np.ndarray:
    out = arr.copy()
    valid = ~np.isnan(out)
    if not valid.any():
        return np.full_like(out, default)
    idx = np.where(valid, np.arange(len(out)), 0)
    np.maximum.accumulate(idx, out=idx)
    out = out[idx]
    first = int(np.argmax(valid))
    out[:first] = out[first]
    return out


def _median(arr: np.ndarray, k: int = 5) -> np.ndarray:
    if len(arr) < k:
        return arr
    pad = k // 2
    p = np.pad(arr, pad, mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(p, k), axis=1)


def _gauss(arr: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0.5 or len(arr) < 3:
        return arr
    r = int(3 * sigma)
    x = np.arange(-r, r + 1)
    k = np.exp(-(x ** 2) / (2 * sigma ** 2))
    k /= k.sum()
    p = np.pad(arr, r, mode="edge")
    return np.convolve(p, k, mode="valid")


def _camera(target: np.ndarray, fps: float, crop: float, dead: float, speed: float) -> np.ndarray:
    """Virtual camera: holds still inside a dead zone, then eases toward the subject."""
    pos = float(target[0])
    vel = 0.0
    dt = 1.0 / fps
    vmax = speed * crop
    out = np.empty_like(target)
    for i, tgt in enumerate(target):
        err = tgt - pos
        if abs(err) > dead * crop:
            desired = np.sign(err) * (abs(err) - 0.5 * dead * crop) * 4.0
        else:
            desired = err * 0.5  # drift gently back to centre while the subject is steady
        vel += (desired - vel) * min(1.0, dt * 6.0)
        vel = max(-vmax, min(vmax, vel))
        pos += vel * dt
        out[i] = pos
    return out


def build_path(sample_t: np.ndarray, target: np.ndarray, cuts: list[float], fps: float, n_out: int,
               crop: float, default: float, smooth: str = "normal") -> np.ndarray:
    lo, hi = crop / 2, 1 - crop / 2
    if hi <= lo:
        return np.full(n_out, 0.5)
    t_out = np.arange(n_out) / fps
    if len(sample_t) == 0:
        return np.full(n_out, min(hi, max(lo, default)))
    dead, speed, sigma = (0.10, 1.4, 0.20) if smooth == "normal" else (0.18, 0.7, 0.45)
    bounds = [0.0] + [c for c in cuts if 0 < c < t_out[-1] + 1] + [1e9]
    out = np.empty(n_out)
    for s, e in zip(bounds[:-1], bounds[1:]):
        m_s = (sample_t >= s) & (sample_t < e)
        m_o = (t_out >= s) & (t_out < e)
        if not m_o.any():
            continue
        seg_t = sample_t[m_s]
        seg = target[m_s]
        if len(seg) == 0 or np.isnan(seg).all():
            vals = np.full(m_o.sum(), np.nan)
        else:
            seg = _median(_fill(seg, default), 5)
            vals = np.interp(t_out[m_o], seg_t, seg)
        out[m_o] = vals
    out = _fill(out, default)
    out = np.clip(out, lo, hi)
    # camera dynamics per scene, so hard cuts re-frame instantly
    res = np.empty_like(out)
    for s, e in zip(bounds[:-1], bounds[1:]):
        m = (t_out >= s) & (t_out < e)
        if m.any():
            res[m] = _gauss(_camera(out[m], fps, crop, dead, speed), sigma * fps)
    return np.clip(res, lo, hi)


def plan(src: str, start: float, end: float, src_w: int, src_h: int, mode: str, fps: float,
         ctx: JobContext | None = None, manual_x: float = 0.5,
         speech: list[tuple[float, float]] | None = None, layout: str = "fill",
         cam_hint: dict | None = None) -> Plan:
    """`speech`: clip-relative (start, end) of spoken words; speaker switches only happen while someone talks.

    `layout` "auto" or "split" also looks for a face cam laid over the picture (`find_cam`; `cam_hint` is the one
    found earlier in the same video). When there is one the plan's mode is "split" and `info["split"]` says where
    the two panels come from; otherwise the plan is the same as for a filled frame, and `info["layout"]` says so."""
    n_out = max(1, int(round((end - start) * fps)))
    cw, ch = crop_fraction(src_w, src_h)
    look = layout in SPLIT_LAYOUTS
    if not look:
        if mode == "center" or (cw >= 0.999 and ch >= 0.999):
            return static_plan("center", fps, n_out)
        if mode == "manual":
            return static_plan("manual", fps, n_out, min(1 - cw / 2, max(cw / 2, manual_x)), 0.5)
    a = analyze(src, start, end, src_w, src_h, ctx, layout=look)
    if look:
        cam = find_cam(a, force=layout == "split", hint=cam_hint)
        if cam:
            split = split_layout(cam, src_w, src_h, manual_x if mode == "manual" else None)
            return Plan("split", fps, n_out, np.full(n_out, split["content"][0]), np.full(n_out, 0.5), a["cuts"],
                        len([t for t in a["tracks"] if t.presence >= 3]),
                        {"layout": "split", "split": split,
                         "cam": {"kind": cam["kind"], "score": round(float(cam["score"]), 3),
                                 "presence": round(float(cam["presence"]), 3)}
                         | ({"from": cam["from"]} if cam.get("from") else {}),
                         "edge": round(a["edge"], 3), "motion": round(a["motion"], 2), "samples": a["n"]})
        if mode == "center" or (cw >= 0.999 and ch >= 0.999):
            return Plan("center", fps, n_out, np.full(n_out, 0.5), np.full(n_out, 0.5), info={"layout": "fill"})
        if mode == "manual":
            return Plan("manual", fps, n_out, np.full(n_out, min(1 - cw / 2, max(cw / 2, manual_x))),
                        np.full(n_out, 0.5), info={"layout": "fill"})
    a["speech"] = speech_mask(a["times"], speech)
    used = _choose_mode(a) if mode == "auto" else mode
    faces_found = len([t for t in a["tracks"] if t.presence >= 3])
    if used in {"face", "speaker"} and not a["tracks"]:
        used = _choose_mode(a)
    sample_t = np.asarray(a["times"], dtype=np.float64)
    cuts = refine_cuts(src, start, list(a["cuts"])) if a["cuts"] else []
    resolved = {"layout": "fill"} if look else {}
    if used in {"face", "speaker"}:
        xs, ys, switches = _face_targets(a, cw, ch, speaker=(used == "speaker"))
        # Face tracks already hold through short dropouts. After that, follow measured visual activity rather
        # than keeping an obsolete face position for the rest of the scene.
        visual_x, visual_y = _screen_targets(a, cw, ch)
        xs = np.where(np.isnan(xs), visual_x, xs)
        ys = np.where(np.isnan(ys), visual_y, ys)
        cuts = sorted(set(cuts + switches))
        smooth = "normal"
    elif used in {"screen", "motion"}:
        xs, ys = _screen_targets(a, cw, ch)
        smooth = "slow" if used == "screen" else "normal"
    else:
        return Plan("center", fps, n_out, np.full(n_out, 0.5), np.full(n_out, 0.5), a["cuts"], faces_found, resolved)
    cx = build_path(sample_t, xs, cuts, fps, n_out, cw, 0.5, smooth)
    # vertical path also matters when zooming in, so plan it for a slightly smaller crop
    cy = build_path(sample_t, ys, cuts, fps, n_out, min(ch, 0.87), 0.5, smooth)
    return Plan(used, fps, n_out, cx, cy, a["cuts"], faces_found,
                {"edge": round(a["edge"], 3), "sat": round(a["sat"], 1), "motion": round(a["motion"], 2),
                 "samples": a["n"], "visual_target_samples": int(np.isfinite(xs).sum()), **resolved})

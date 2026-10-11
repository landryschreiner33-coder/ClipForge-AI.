"""Smart 9:16 framing.

Samples the clip at a low frame rate, detects faces (OpenCV YuNet), estimates
who is talking from mouth-region motion, finds salient screen content from
motion/edge energy, detects hard cuts, and turns the per-sample targets into a
smooth "virtual camera" path (dead-zone + eased velocity + gaussian smoothing,
with instant re-framing on scene cuts).
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


def analyze(src: str, start: float, end: float, src_w: int, src_h: int, ctx: JobContext | None = None) -> dict:
    import cv2

    dur = max(0.1, end - start)
    det = None
    tracks: list[Track] = []
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
                if fh < 0.06 * h:
                    continue
                cxn, cyn = (x + fw / 2) / w, (y + fh / 2) / h
                box = (x / w, y / h, fw / w, fh / h)
                # associate with an existing track
                best, best_d = None, 1e9
                for tr in tracks:
                    if idx - tr.last_idx > 16:
                        continue
                    bx, by, bw, bh = tr.boxes[tr.last_idx]
                    d = np.hypot(bx + bw / 2 - cxn, by + bh / 2 - cyn)
                    if d < max(bw, box[2]) * 1.2 and d < best_d:
                        best, best_d = tr, d
                if best is None or idx in best.boxes:
                    best = Track(len(tracks))
                    tracks.append(best)
                best.boxes[idx] = box
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
    return {"times": times, "n": n, "tracks": tracks, "cuts": cuts, "col": col_energy, "row": row_energy,
            "edge": float(np.mean(edge_density)) if edge_density else 0.0,
            "sat": float(np.mean(saturation)) if saturation else 0.0,
            "motion": float(np.mean(motion_level)) if motion_level else 0.0}


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
    return "center"


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
            k = int(np.argmax(sums))
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
         speech: list[tuple[float, float]] | None = None) -> Plan:
    """`speech`: clip-relative (start, end) of spoken words; speaker switches only happen while someone talks."""
    n_out = max(1, int(round((end - start) * fps)))
    cw, ch = crop_fraction(src_w, src_h)
    if mode == "center" or (cw >= 0.999 and ch >= 0.999):
        return static_plan("center", fps, n_out)
    if mode == "manual":
        return static_plan("manual", fps, n_out, min(1 - cw / 2, max(cw / 2, manual_x)), 0.5)
    a = analyze(src, start, end, src_w, src_h, ctx)
    a["speech"] = speech_mask(a["times"], speech)
    used = _choose_mode(a) if mode == "auto" else mode
    faces_found = len([t for t in a["tracks"] if t.presence >= 3])
    if used in {"face", "speaker"} and not a["tracks"]:
        used = "center" if mode == "auto" else "screen" if mode == "screen" else "center"
    sample_t = np.asarray(a["times"], dtype=np.float64)
    cuts = refine_cuts(src, start, list(a["cuts"])) if a["cuts"] else []
    if used in {"face", "speaker"}:
        xs, ys, switches = _face_targets(a, cw, ch, speaker=(used == "speaker"))
        cuts = sorted(set(cuts + switches))
        smooth = "normal"
    elif used == "screen":
        xs, ys = _screen_targets(a, cw, ch)
        smooth = "slow"
    else:
        return Plan("center", fps, n_out, np.full(n_out, 0.5), np.full(n_out, 0.5), a["cuts"], faces_found)
    cx = build_path(sample_t, xs, cuts, fps, n_out, cw, 0.5, smooth)
    # vertical path also matters when zooming in, so plan it for a slightly smaller crop
    cy = build_path(sample_t, ys, cuts, fps, n_out, min(ch, 0.87), 0.5, smooth)
    return Plan(used, fps, n_out, cx, cy, a["cuts"], faces_found,
                {"edge": round(a["edge"], 3), "sat": round(a["sat"], 1), "motion": round(a["motion"], 2),
                 "samples": a["n"]})

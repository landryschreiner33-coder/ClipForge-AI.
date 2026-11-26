"""ClipForge AI watches the whole video, frame by frame (docs/clipforge/WATCH_AND_LISTEN.md).

Before, the picture was looked at only for the six strongest finalists, after the clips were nearly chosen. Now one
pass decodes the whole video at 2 frames a second (1 for videos over 20 minutes, 0.5 over 90) at 320 pixels wide and
measures every frame with OpenCV, without any download:

* movement (how much the picture changes from the frame before) and hard cuts (the colours change at once);
* faces (YuNet, the face detector ClipForge already ships): how many, and how big the largest one is;
* how bright, how sharp and how colourful the picture is;
* an 8×8 thumbnail of each frame, so a picture that comes back (the same talking head) is recognised.

From these come the video's shots, the moments where the picture comes alive (a burst of movement or a run of quick
cuts), long stretches where nothing moves, and the frames worth showing to the built-in model (eyes.describe), which
then says in words what happens in each part of the video. Everything is cached next to the project (watch.json).
"""
from __future__ import annotations

import base64
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .common import JobContext, read_json, write_json
from .ffmpeg_utils import NO_WINDOW, MediaWatchdog, ffmpeg_bin

log = logging.getLogger("clipfoundry.pipeline.watch")

VERSION = 1
SETTING = "ai_watch"
WIDTH = 320
CUT_CORREL = 0.55          # colour histograms this different between two frames: a hard cut (as reframe.py)
FACE_MIN_H = 0.06          # a face at least this share of the picture's height counts
SEGMENT_MAX = 8.0          # a part of a shot shown to the model at once, at most this long
SEGMENT_MIN = 1.5          # shorter shots join their neighbour
STILL_MOTION = 0.6         # mean frame difference (0-255) below this: the picture stands still
STILL_RUN = 12.0           # ... for this long: a still stretch


def fps_for(duration: float) -> float:
    return 2.0 if duration <= 20 * 60 else (1.0 if duration <= 90 * 60 else 0.5)


def enabled(settings: dict | None = None) -> bool:
    return bool((settings or {}).get(SETTING, True))


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def _unb64(s: str, dtype, shape=None) -> np.ndarray:
    a = np.frombuffer(base64.b64decode(s.encode("ascii")), dtype=dtype)
    return a.reshape(shape) if shape is not None else a


@dataclass
class Watched:
    """What was measured in every sampled frame (frame k is at k / fps seconds)."""
    fps: float
    duration: float
    motion: np.ndarray        # mean change from the frame before (0-255 scale, after a light blur)
    bright: np.ndarray        # 0-1
    sharp: np.ndarray         # 0-1 (log of the Laplacian's variance, scaled)
    sat: np.ndarray           # 0-1
    faces: np.ndarray         # faces found (0-9)
    face_h: np.ndarray        # the largest face's height as a share of the picture (0-1)
    thumbs: np.ndarray        # [n, 64] 8×8 grey thumbnails (0-255)
    cuts: list[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.motion)

    def t(self, k: int) -> float:
        return k / self.fps

    def _range(self, t0: float, t1: float) -> tuple[int, int]:
        a = max(0, int(np.ceil(t0 * self.fps - 1e-9)))
        b = min(self.n, int(np.floor(t1 * self.fps + 1e-9)) + 1)
        if b <= a:
            k = min(self.n - 1, max(0, int(round(t0 * self.fps))))
            return k, k + 1
        return a, b

    # -------------------------------------------------- shots and moments
    def shots(self, t0: float = 0.0, t1: float | None = None) -> list[tuple[float, float]]:
        """(start, end) of each shot in [t0, t1]."""
        t1 = self.duration if t1 is None else t1
        edges = [t0] + [c for c in self.cuts if t0 < c < t1] + [t1]
        return [(a, b) for a, b in zip(edges, edges[1:]) if b - a > 0.05]

    def _z(self) -> np.ndarray:
        m = self.motion.astype(np.float32)
        if len(m) < 4:
            return np.zeros(len(m), np.float32)
        med = float(np.median(m))
        mad = float(np.median(np.abs(m - med))) * 1.4826 + 0.5
        return (m - med) / mad

    def action(self) -> np.ndarray:
        """How alive the picture is around each frame, 0-1: movement against the video's own usual movement, and
        cuts in the two seconds around it."""
        if self.n == 0:
            return np.zeros(0, np.float32)
        z = np.clip(self._z(), 0.0, 6.0) / 6.0
        win = max(1, int(round(1.0 * self.fps)))
        z = np.convolve(z, np.ones(2 * win + 1) / (2 * win + 1), mode="same")
        cut = np.zeros(self.n, np.float32)
        for c in self.cuts:
            k = int(round(c * self.fps))
            cut[max(0, k - 2 * win):min(self.n, k + 2 * win + 1)] += 0.25
        return np.clip(0.75 * z + np.minimum(cut, 0.75), 0.0, 1.0).astype(np.float32)

    def moments(self, floor: float = 0.45, gap: float = 6.0, limit: int = 40) -> list[dict]:
        """The peaks where the picture comes alive (at least `gap` seconds apart), strongest first."""
        act = self.action()
        if not len(act):
            return []
        order = np.argsort(-act)
        out: list[dict] = []
        for k in order:
            if act[k] < floor or len(out) >= limit:
                break
            t = self.t(int(k))
            if all(abs(t - m["at"]) >= gap for m in out):
                out.append({"at": round(t, 2), "action": round(float(act[k]), 2)})
        return out

    def still_runs(self, t0: float, t1: float) -> list[tuple[float, float]]:
        """Stretches of at least STILL_RUN seconds without a cut where the picture barely moves."""
        a, b = self._range(t0, t1)
        still = self.motion[a:b] < STILL_MOTION
        cut_k = {int(round(c * self.fps)) for c in self.cuts}
        out, run = [], None
        for i, s in enumerate(list(still) + [False]):
            k = a + i
            if s and k not in cut_k and run is None:
                run = k
            elif (not s or k in cut_k) and run is not None:
                if (k - run) / self.fps >= STILL_RUN:
                    out.append((round(self.t(run), 2), round(self.t(k), 2)))
                run = k if s else None
        return out

    def features(self, t0: float, t1: float) -> dict:
        """The picture of a clip in numbers (small, stored with the clip)."""
        a, b = self._range(t0, t1)
        dur = max(0.1, t1 - t0)
        act = self.action()[a:b]
        faces = self.faces[a:b]
        n_cuts = sum(1 for c in self.cuts if t0 < c < t1)
        still = sum(e - s for s, e in self.still_runs(t0, t1))
        first = self._range(t0, min(t1, t0 + 3.0))
        return {"shots": n_cuts + 1, "cuts_per_10s": round(n_cuts / dur * 10, 2),
                "action": round(float(act.mean()) if len(act) else 0.0, 3),
                "action_peak": round(float(act.max()) if len(act) else 0.0, 3),
                "opening_action": round(float(self.action()[first[0]:first[1]].mean()), 3),
                "face_share": round(float((faces > 0).mean()) if len(faces) else 0.0, 3),
                "face_size": round(float(np.median(self.face_h[a:b][faces > 0])) if (faces > 0).any() else 0.0, 3),
                "people_max": int(faces.max()) if len(faces) else 0,
                "still_share": round(min(1.0, still / dur), 3),
                "dark_share": round(float((self.bright[a:b] < 0.12).mean()), 3),
                "sharpness": round(float(np.median(self.sharp[a:b])), 3),
                "frames": int(b - a), "fps": self.fps,
                "estimated": "measured in every sampled frame"}

    def keyframes(self, t0: float, t1: float, n: int = 4) -> list[float]:
        """Up to `n` frame times that show [t0, t1] best: the sharpest frame near the middle of each shot (the
        longest shots first), then evenly spread ones; in time order."""
        shots = sorted(self.shots(t0, t1), key=lambda s: -(s[1] - s[0]))
        picks: list[float] = []
        for s, e in shots[:n]:
            a, b = self._range(s + 0.15 * (e - s), e - 0.15 * (e - s))
            if b <= a:
                continue
            k = a + int(np.argmax(self.sharp[a:b] + 0.2 * (self.faces[a:b] > 0)))
            picks.append(round(self.t(k), 2))
        k = 1
        while len(picks) < n and k <= 2 * n:
            t = round(t0 + (t1 - t0) * k / (n + 1), 2)
            if all(abs(t - p) > 0.6 for p in picks):
                picks.append(t)
            k += 1
        return sorted(picks)[:n]

    def segments(self) -> list[dict]:
        """The video in parts the model is shown one at a time: each shot, cut into pieces of at most
        SEGMENT_MAX seconds; shots shorter than SEGMENT_MIN join the part before them. Each part says how alive
        its picture is and whether it looks like the part before it (the same still talking head)."""
        parts: list[list[float]] = []
        for s, e in self.shots():
            if parts and (e - s < SEGMENT_MIN or parts[-1][1] - parts[-1][0] < SEGMENT_MIN) \
                    and e - parts[-1][0] <= SEGMENT_MAX:
                parts[-1][1] = e
                continue
            pieces = max(1, int(np.ceil((e - s) / SEGMENT_MAX)))
            for i in range(pieces):
                parts.append([s + (e - s) * i / pieces, s + (e - s) * (i + 1) / pieces])
        act = self.action()
        out = []
        prev_thumb = None
        for s, e in parts:
            a, b = self._range(s, e)
            thumb = self.thumbs[a:b].astype(np.float32).mean(axis=0) if b > a else np.zeros(64, np.float32)
            same = bool(prev_thumb is not None and float(np.abs(thumb - prev_thumb).mean()) < 6.0
                        and float(self.motion[a:b].mean() if b > a else 0.0) < 2.0)
            prev_thumb = thumb
            out.append({"start": round(s, 2), "end": round(e, 2),
                        "action": round(float(act[a:b].mean()) if b > a else 0.0, 3), "same_as_before": same,
                        "faces": int(self.faces[a:b].max()) if b > a else 0})
        return out

    def to_json(self) -> dict:
        return {"version": VERSION, "fps": self.fps, "duration": round(self.duration, 3), "n": self.n,
                "motion": _b64(np.clip(np.round(self.motion * 4), 0, 65535).astype(np.uint16)),
                "bright": _b64(np.round(self.bright * 255).astype(np.uint8)),
                "sharp": _b64(np.round(self.sharp * 255).astype(np.uint8)),
                "sat": _b64(np.round(self.sat * 255).astype(np.uint8)),
                "faces": _b64(np.clip(self.faces, 0, 9).astype(np.uint8)),
                "face_h": _b64(np.round(self.face_h * 255).astype(np.uint8)),
                "thumbs": _b64(self.thumbs.astype(np.uint8)), "cuts": self.cuts}

    @staticmethod
    def from_json(d: dict) -> "Watched | None":
        try:
            n = int(d["n"])
            w = Watched(float(d["fps"]), float(d["duration"]),
                        _unb64(d["motion"], np.uint16).astype(np.float32) / 4.0,
                        _unb64(d["bright"], np.uint8).astype(np.float32) / 255.0,
                        _unb64(d["sharp"], np.uint8).astype(np.float32) / 255.0,
                        _unb64(d["sat"], np.uint8).astype(np.float32) / 255.0,
                        _unb64(d["faces"], np.uint8).astype(np.int32),
                        _unb64(d["face_h"], np.uint8).astype(np.float32) / 255.0,
                        _unb64(d["thumbs"], np.uint8, (n, 64)), [float(c) for c in d.get("cuts") or []])
            return w if all(len(getattr(w, k)) == n for k in ("bright", "sharp", "sat", "faces", "face_h")) else None
        except (KeyError, TypeError, ValueError):
            return None


# ------------------------------------------------------------------ the pass
def _detector(w: int, h: int):
    from .reframe import _detector as det  # the same YuNet face detector the framing uses

    return det(w, h)


def _frames(src: str, fps: float, w: int, h: int, duration: float, ctx: JobContext | None):
    cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error"]
    if sys.platform == "darwin":
        cmd += ["-hwaccel", "videotoolbox"]   # decodes on the Mac's media engine; ffmpeg falls back by itself
    cmd += ["-i", src, "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", f"fps={fps},scale={w}:{h}:flags=area",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    size = w * h * 3
    with MediaWatchdog(ctx.cancelled if ctx else None, max(900.0, duration * 3)) as watch:
        proc = watch.add(subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          creationflags=NO_WINDOW))
        k = 0
        try:
            while True:
                watch.check()
                buf = proc.stdout.read(size)  # type: ignore[union-attr]
                watch.check()
                if len(buf) < size:
                    break
                yield k, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
                k += 1
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def _key(src: Path) -> dict:
    st = src.stat()
    return {"version": VERSION, "size": st.st_size, "mtime": int(st.st_mtime)}


def scan(src: Path | str, meta: dict, ctx: JobContext | None = None, cache: Path | None = None,
         progress: Callable[[float], None] | None = None, settings: dict | None = None) -> Watched | None:
    """Watch the whole video. None when the setting is off or there is no picture (callers fall back to what they
    did before)."""
    import cv2

    src = Path(src)
    if not enabled(settings) or not src.is_file() or not meta.get("width") or not meta.get("has_video", True):
        return None
    key = _key(src)
    if cache is not None and cache.is_file():
        saved = read_json(cache, {}) or {}
        if saved.get("key") == key:
            got = Watched.from_json(saved.get("watched") or {})
            if got is not None:
                return got
    duration = float(meta.get("duration") or 0.0)
    if duration <= 0:
        return None
    fps = fps_for(duration)
    sw, sh = int(meta["width"]), int(meta["height"])
    w = WIDTH if sw >= sh else max(2, int(WIDTH * sw / sh) // 2 * 2)
    h = max(2, int(round(sh * w / sw / 2)) * 2)
    det = _detector(w, h)
    expect = max(1, int(duration * fps))
    motion, bright, sharp, sat, faces, face_h, thumbs, cuts = [], [], [], [], [], [], [], []
    prev_small = prev_hist = None
    try:
        for k, frame in _frames(str(src), fps, w, h, duration, ctx):
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.GaussianBlur(cv2.resize(gray, (160, max(2, int(160 * h / w))), interpolation=cv2.INTER_AREA),
                                     (5, 5), 0)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
            hist = cv2.normalize(hist, hist).flatten()
            motion.append(float(cv2.absdiff(small, prev_small).mean()) if prev_small is not None else 0.0)
            if prev_hist is not None and cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL) < CUT_CORREL:
                cuts.append(round((k - 0.5) / fps, 3))
            prev_small, prev_hist = small, hist
            bright.append(float(gray.mean()) / 255.0)
            lap = float(cv2.Laplacian(gray, cv2.CV_32F).var())
            sharp.append(min(1.0, np.log1p(lap) / 8.0))
            sat.append(float(hsv[..., 1].mean()) / 255.0)
            n_f, big = 0, 0.0
            if det:
                _, found = det.detect(frame)
                for f in (found if found is not None else []):
                    fh = float(f[3]) / h
                    if fh >= FACE_MIN_H:
                        n_f += 1
                        big = max(big, fh)
            faces.append(min(9, n_f))
            face_h.append(min(1.0, big))
            thumbs.append(cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA).flatten())
            if progress and k % 20 == 0:
                progress(min(1.0, (k + 1) / expect))
    except Exception as exc:  # noqa: BLE001 - cancellation passes; anything else leaves the picture unwatched
        from .common import Cancelled

        if isinstance(exc, Cancelled):
            raise
        log.warning("watch: %s", exc)
        return None
    if not motion:
        return None
    watched = Watched(fps, duration, np.array(motion, np.float32), np.array(bright, np.float32),
                      np.array(sharp, np.float32), np.array(sat, np.float32), np.array(faces, np.int32),
                      np.array(face_h, np.float32), np.array(thumbs, np.uint8), cuts)
    if cache is not None:
        try:
            write_json(cache, {"key": key, "watched": watched.to_json()})
        except OSError as exc:
            log.warning("watch: could not keep the result: %s", exc)
    return watched


def load(cache: Path) -> Watched | None:
    saved = read_json(cache, {}) or {}
    return Watched.from_json(saved.get("watched") or {}) if saved else None

"""The camera of a scene in an animated short (docs/clipforge/ANIMATED_SHORTS.md): where it looks at each moment.

A scene is one still picture, so the camera is what makes it a shot. Viral shorts never hold a picture still and
never move it at one dull speed: the camera eases (fast at first, then a slow creep), punches in on a phrase (a cut
to a closer framing of the same picture, so the eye gets a new shot every two seconds without a new picture), lands
on a cut with a small settle or arrives with a whip, and shakes for a moment when something hits. With a depth map of
the picture (depth.py) near things move more than far things, which reads as a real camera moving through a scene.

Everything here is arithmetic on a `direction` (director.py writes it; plain JSON, every key optional):

    {"move": "zoom_in",            # one of motion.MOVES (the owner's choice or the director's)
     "strength": 0.12,             # how far the move travels, as a share of the frame (0-0.3)
     "ease": "snap",               # "linear" | "inout" | "out" | "snap" (fast start, slow creep)
     "drift": [0.3, -0.2],         # a sideways drift on top of the move, in shares of `strength` (x, y)
     "rotate": 0.6,                # degrees the frame turns over the scene (a slow roll; 0 for none)
     "beats": [{"t": 1.9, "zoom": 1.18}],   # punch-ins: from `t` seconds on the framing is this much closer
     "focus": [0.5, 0.38],         # where a punch-in aims, as shares of the picture (None: found in the picture)
     "entry": {"kind": "whip_left", "frames": 6},   # "pop" | "zoom" | "whip_left" | "whip_right" | "flash" | "none"
     "shake": 6.0,                 # pixels a punch or an entry shakes the frame for a moment (0 for none)
     "parallax": 0.035}            # with a depth map: how far near and far things part, as a share of the width

`Camera.at(i)` gives the frame's `Shot` (scale, centre, turn, offset, what the depth adds); motion.py draws it.
The same direction, picture size and frame count always give the same shots.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EASES = ("linear", "inout", "out", "snap")
ENTRIES = ("none", "pop", "zoom", "whip_left", "whip_right", "flash")
MAX_STRENGTH = 0.3
MAX_ROTATE = 3.0             # degrees
MAX_PUNCH = 1.6              # the closest framing punches may add up to
PUNCH_S = 0.1                # a punch-in takes this long (three frames at 30 a second: a cut with a little travel)
POP = 0.045                  # a "pop" entry starts this much closer and settles
ZOOM_ENTRY = 0.32            # a "zoom" entry starts this much closer
WHIP = 0.55                  # a whip entry starts this share of the frame's width to the side
SHAKE_S = 0.28               # how long a shake takes to die away
PAN_TRAVEL = 1.5             # a pan travels this many times `strength` of the frame
FOCUS = (0.5, 0.4)           # where pictures made for a short keep their subject (above the captions)
FOCUS_BOX = ((0.28, 0.72), (0.22, 0.62))   # a found focus is kept inside this part of the picture


def ease(name: str, p: float) -> float:
    """Progress 0-1 through a move, shaped: "out" starts fast and lands softly, "inout" starts and lands softly,
    "snap" covers most of the way in the first sixth of the time and creeps for the rest."""
    p = min(1.0, max(0.0, float(p)))
    if name == "inout":
        return 0.5 - 0.5 * math.cos(math.pi * p)
    if name == "out":
        return 1.0 - (1.0 - p) ** 3
    if name == "snap":
        return 0.62 * (1.0 - (1.0 - min(1.0, p / 0.16)) ** 3) + 0.38 * p
    return p


def _num(value, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, v)) if math.isfinite(v) else default


@dataclass(frozen=True)
class Shot:
    """One frame's camera: the picture is drawn `scale` times its size, turned by `angle` degrees about the frame's
    centre, with the picture's point (cx, cy) at the frame's centre plus (dx, dy) pixels. `lateral` (-1 to 1, x and
    y) and `push` (0-1) say where the camera is on its path, for the depth's parallax; `flash` (0-1) brightens the
    frame; `blur` says the frame is in fast motion and should be drawn smeared."""
    scale: float
    cx: float
    cy: float
    angle: float
    dx: float
    dy: float
    lateral: tuple[float, float]
    push: float
    flash: float
    blur: bool


class Camera:
    def __init__(self, direction: dict | None, picture: tuple[int, int], size: tuple[int, int], frames: int,
                 fps: int, focus: tuple[float, float] | None = None, seed: int = 0):
        d = dict(direction or {})
        self.w, self.h = int(picture[0]), int(picture[1])
        self.w_out, self.h_out = int(size[0]), int(size[1])
        self.frames, self.fps = max(1, int(frames)), max(1, int(fps))
        self.move = str(d.get("move") or "zoom_in")
        self.strength = _num(d.get("strength"), 0.0, MAX_STRENGTH, 0.08)
        self.ease = d.get("ease") if d.get("ease") in EASES else "inout"
        drift = d.get("drift") if isinstance(d.get("drift"), (list, tuple)) and len(d["drift"]) == 2 else (0.0, 0.0)
        self.drift = (_num(drift[0], -1.0, 1.0, 0.0), _num(drift[1], -1.0, 1.0, 0.0))
        self.rotate = _num(d.get("rotate"), -MAX_ROTATE, MAX_ROTATE, 0.0)
        self.shake = _num(d.get("shake"), 0.0, 40.0, 0.0)
        self.parallax = _num(d.get("parallax"), 0.0, 0.08, 0.0)
        entry = d.get("entry") if isinstance(d.get("entry"), dict) else {}
        self.entry = entry.get("kind") if entry.get("kind") in ENTRIES else "none"
        self.entry_frames = int(_num(entry.get("frames"), 2, 20, 6)) if self.entry != "none" else 0
        self.beats = sorted(
            (_num(b.get("t"), 0.0, 3600.0, 0.0), _num(b.get("zoom"), 1.0 / MAX_PUNCH, MAX_PUNCH, 1.0))
            for b in d.get("beats") or [] if isinstance(b, dict))
        given = d.get("focus") if isinstance(d.get("focus"), (list, tuple)) and len(d["focus"]) == 2 else focus
        fx, fy = given if given else FOCUS
        self.focus = (_num(fx, 0.0, 1.0, FOCUS[0]), _num(fy, 0.0, 1.0, FOCUS[1]))
        self.cover = max(self.w_out / self.w, self.h_out / self.h)
        # the frame turned needs a little more picture under its corners
        turn = math.radians(abs(self.rotate))
        self.turn_room = math.cos(turn) + math.sin(turn) * max(self.w_out / self.h_out, self.h_out / self.w_out)
        self._phase = [((seed * 2654435761 + k * 40503) % 6283) / 1000.0 for k in range(4)]

    # ------------------------------------------------------------------ the parts of a shot
    def _punch(self, t: float) -> float:
        """How much closer the framing is at `t` seconds: each beat multiplies it, over PUNCH_S."""
        zoom = 1.0
        for at, by in self.beats:
            if t >= at:
                zoom *= 1.0 + (by - 1.0) * ease("out", (t - at) / PUNCH_S)
        return min(MAX_PUNCH, max(1.0 / MAX_PUNCH, zoom))

    def _hit(self, t: float) -> float:
        """0-1: how hard the frame still shakes from the last punch or entry."""
        last = max([at for at, by in self.beats if t >= at and by > 1.02] +
                   ([0.0] if self.entry in ("zoom", "whip_left", "whip_right") else []), default=None)
        if last is None:
            return 0.0
        since = t - last - (self.entry_frames / self.fps if last == 0.0 and self.entry != "none" else 0.0)
        return math.exp(-max(0.0, since) / (SHAKE_S / 3)) if since >= -1e-9 else 0.0

    def _base(self, p: float) -> tuple[float, float, float]:
        """(zoom over cover, pan x, pan y in output pixels) of the move alone at progress p."""
        s, e = self.strength, ease(self.ease, p)
        travel_x, travel_y = self.w_out * s * PAN_TRAVEL, self.h_out * s * PAN_TRAVEL
        zoom, x, y = 1.0 + s, 0.0, 0.0
        if self.move == "zoom_in":
            zoom = 1.0 + s * e
        elif self.move == "zoom_out":
            zoom = 1.0 + s * (1.0 - e)
        elif self.move == "still":
            zoom = 1.0
        elif self.move == "pan_right":
            x = travel_x * (e - 0.5)
        elif self.move == "pan_left":
            x = travel_x * (0.5 - e)
        elif self.move == "pan_down":
            y = travel_y * (e - 0.5)
        elif self.move == "pan_up":
            y = travel_y * (0.5 - e)
        if self.move != "still":  # the drift: a slow slide on top, so a push-in is never dead centre
            x += self.w_out * s * self.drift[0] * (e - 0.5)
            y += self.h_out * s * self.drift[1] * (e - 0.5)
            zoom += s * 0.5 * (abs(self.drift[0]) + abs(self.drift[1]))  # room for it
        return zoom, x, y

    def at(self, i: float) -> Shot:
        """The shot at frame `i` (a fraction is a moment between two frames, for motion blur)."""
        t = max(0.0, float(i)) / self.fps
        p = min(1.0, float(i) / (self.frames - 1)) if self.frames > 1 else 0.0
        zoom, pan_x, pan_y = self._base(p)
        punch = self._punch(t)
        closer = min(1.0, max(0.0, (punch - 1.0) / 0.25))   # 0: the whole picture; 1: fully on the focus
        entry_zoom, dx, flash, fast = 1.0, 0.0, 0.0, False
        if self.entry != "none" and i < self.entry_frames:
            left = 1.0 - ease("out", float(i) / self.entry_frames)   # 1 at the cut, 0 when it has landed
            fast = left > 0.08
            if self.entry == "pop":
                entry_zoom, fast = 1.0 + POP * left, False
            elif self.entry == "zoom":
                entry_zoom = 1.0 + ZOOM_ENTRY * left
            elif self.entry == "whip_left":      # the new picture arrives from the right
                dx = self.w_out * WHIP * left
            elif self.entry == "whip_right":
                dx = -self.w_out * WHIP * left
            elif self.entry == "flash":
                flash, fast = 0.7 * left, False
        angle = self.rotate * (ease("inout", p) - 0.5) if self.move != "still" else 0.0
        scale = self.cover * max(zoom, self.turn_room if angle else 1.0) * punch * entry_zoom
        # the picture point under the frame's centre: the middle, pulled towards the focus by a punch-in, moved by
        # the pan; kept where the frame stays inside the picture
        cx = self.w * (0.5 + (self.focus[0] - 0.5) * closer) + pan_x / scale
        cy = self.h * (0.5 + (self.focus[1] - 0.5) * closer) + pan_y / scale
        half_w = self.w_out / 2 / scale * (self.turn_room if angle else 1.0)
        half_h = self.h_out / 2 / scale * (self.turn_room if angle else 1.0)
        cx = min(max(cx, half_w), self.w - half_w) if half_w * 2 <= self.w else self.w / 2
        cy = min(max(cy, half_h), self.h - half_h) if half_h * 2 <= self.h else self.h / 2
        dy = 0.0
        hit = self._hit(t) if self.shake else 0.0
        if hit > 0.02:
            a = self.shake * hit
            dx += a * math.sin(t * 2 * math.pi * 17.0 + self._phase[0])
            dy += a * math.sin(t * 2 * math.pi * 23.0 + self._phase[1])
        if not fast:  # a punch-in travels for PUNCH_S: smear those frames too
            fast = any(0.0 <= t - at < PUNCH_S and abs(by - 1.0) > 0.03 for at, by in self.beats)
        e = ease(self.ease, p)
        lateral = ((e - 0.5) * 2 * (1 if self.move == "pan_right" else -1 if self.move == "pan_left" else
                                    self.drift[0]),
                   (e - 0.5) * 2 * (1 if self.move == "pan_down" else -1 if self.move == "pan_up" else
                                    self.drift[1]))
        push = e if self.move == "zoom_in" else (1.0 - e) if self.move == "zoom_out" else 0.0
        return Shot(scale, cx, cy, angle, dx, dy, lateral, push, flash, fast)

    def matrix(self, shot: Shot) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """The 2x3 matrix that draws the picture into the frame for this shot (picture pixels to frame pixels)."""
        a = math.radians(shot.angle)
        c, s = math.cos(a) * shot.scale, math.sin(a) * shot.scale
        ox, oy = self.w_out / 2 + shot.dx, self.h_out / 2 + shot.dy
        return ((c, -s, ox - c * shot.cx + s * shot.cy), (s, c, oy - s * shot.cx - c * shot.cy))


def find_focus(img) -> tuple[float, float]:
    """Where the eye goes in a picture, as shares of its width and height: the centre of what stands out from its
    surroundings (the spectral-residual saliency of Hou and Zhang, 2007, on a small copy), kept inside the part of
    the frame where a short's subject sits. A flat picture gives the usual place."""
    import cv2
    import numpy as np

    try:
        small = cv2.resize(img, (64, 64), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) if small.ndim == 3 else \
            small.astype(np.float32)
        spectrum = np.fft.fft2(gray)
        log_amp = np.log(np.abs(spectrum) + 1e-6)
        residual = log_amp - cv2.blur(log_amp, (3, 3))
        sal = np.abs(np.fft.ifft2(np.exp(residual + 1j * np.angle(spectrum)))) ** 2
        sal = cv2.GaussianBlur(sal.astype(np.float32), (0, 0), 3.0)
        sal -= sal.min()
        yy, xx = np.mgrid[0:64, 0:64].astype(np.float32)
        sal *= np.exp(-(((xx - 32) / 30) ** 2 + ((yy - 26) / 30) ** 2))   # the middle counts more than the edges
        total = float(sal.sum())
        if total <= 1e-6 or float(sal.max()) < 1e-6:
            return FOCUS
        fx, fy = float((sal * xx).sum() / total) / 63.0, float((sal * yy).sum() / total) / 63.0
    except Exception:  # noqa: BLE001 - the usual place is always a fine answer
        return FOCUS
    (x0, x1), (y0, y1) = FOCUS_BOX
    return min(x1, max(x0, fx)), min(y1, max(y0, fy))

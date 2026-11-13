"""What lies over and on a scene's picture in an animated short (docs/clipforge/ANIMATED_SHORTS.md): the air
between the camera and the picture, and the finish of the picture itself.

A still picture that only slides looks like a slide show. The shorts that feel animated have something alive in
every frame: dust in a beam of light, rain, snow, embers rising, fog drifting, a glint. `Atmosphere` draws those over
each frame, made here from a few numbers (nothing is downloaded, nobody else owns them), the same every time for the
same seed. `finish` gives the picture its grade once, before the camera moves it: a little contrast and colour, a
soft glow on the bright parts. `Frame` is what stays fixed to the screen: darker corners and, for film looks, grain.

All of it is quiet on purpose: the captions and the picture are the show.
"""
from __future__ import annotations

import math

KINDS = ("dust", "bokeh", "snow", "rain", "embers", "fog", "rays", "sparkle", "fireflies", "bubbles")
MAX_KINDS = 3
#          how many, sizes (pixels at 1080 wide), colour (B, G, R), brightness, speed (x, y pixels a second), sway
PARTICLES = {
    "dust": (70, (3, 5, 8), (205, 225, 255), (0.25, 0.6), ((-14, 14), (-22, -4)), 18.0),
    "bokeh": (11, (70, 110, 150), (220, 235, 255), (0.07, 0.15), ((-10, 10), (-12, 4)), 10.0),
    "snow": (150, (4, 7, 11), (255, 255, 255), (0.45, 0.9), ((-30, 10), (90, 190)), 26.0),
    "embers": (60, (3, 5, 7), (70, 150, 255), (0.5, 1.0), ((-26, 26), (-170, -70)), 30.0),
    "fireflies": (26, (5, 8, 12), (120, 255, 220), (0.35, 0.9), ((-16, 16), (-14, 14)), 34.0),
    "bubbles": (34, (8, 14, 22), (255, 240, 215), (0.2, 0.45), ((-10, 10), (-120, -50)), 22.0),
    "sparkle": (22, (16, 24, 34), (235, 250, 255), (0.5, 1.0), ((0, 0), (0, 0)), 0.0),
}


def clean_kinds(kinds) -> tuple[str, ...]:
    """The known kinds among `kinds`, each once, at most MAX_KINDS."""
    out: list[str] = []
    for k in kinds or ():
        if k in KINDS and k not in out:
            out.append(k)
    return tuple(out[:MAX_KINDS])


def _rng(seed: int, salt: str):
    import zlib

    import numpy as np

    return np.random.default_rng(zlib.crc32(f"{int(seed)}:{salt}".encode()))


def _blob(size: int, ring: bool = False, star: bool = False):
    """A soft round dot `size` pixels across (0-1); `ring`: a bubble's rim; `star`: a four-point glint."""
    import numpy as np

    n = max(3, int(size) | 1)
    c = (n - 1) / 2
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    r = np.hypot(xx - c, yy - c) / max(1.0, c)
    if star:
        ax, ay = np.abs(xx - c) / max(1.0, c), np.abs(yy - c) / max(1.0, c)
        arms = np.exp(-(ay * 9) ** 2) * np.clip(1 - ax, 0, 1) ** 2 + np.exp(-(ax * 9) ** 2) * np.clip(1 - ay, 0, 1) ** 2
        return np.clip(arms + np.exp(-(r * 3.2) ** 2), 0, 1).astype(np.float32)
    if ring:
        return np.clip(np.exp(-((r - 0.78) * 7) ** 2) + 0.18 * np.exp(-(r * 1.5) ** 2), 0, 1).astype(np.float32)
    return np.exp(-(r * 2.1) ** 2).astype(np.float32)


class Atmosphere:
    """The moving layers over a scene. `apply(frame, i)` draws frame i's layers into `frame` (BGR, uint8), in place."""

    def __init__(self, kinds, size: tuple[int, int], fps: int, seed: int = 0, amount: float = 1.0):
        import numpy as np

        self.kinds = clean_kinds(kinds)
        self.w, self.h = int(size[0]), int(size[1])
        self.fps = max(1, int(fps))
        self.k = self.w / 1080.0                       # everything is sized for a 1080-wide frame
        self.amount = min(2.0, max(0.0, float(amount)))
        self._parts: dict[str, dict] = {}
        self._layers: dict[str, object] = {}
        for kind in self.kinds:
            rng = _rng(seed, kind)
            if kind in PARTICLES:
                count, sizes, colour, bright, (vx, vy), sway = PARTICLES[kind]
                n = max(1, int(round(count * self.amount)))
                which = rng.integers(0, len(sizes), n)
                self._parts[kind] = {
                    "x": rng.uniform(0, self.w, n), "y": rng.uniform(0, self.h, n),
                    "vx": rng.uniform(vx[0], vx[1], n) * self.k, "vy": rng.uniform(vy[0], vy[1], n) * self.k,
                    "a": rng.uniform(bright[0], bright[1], n), "phase": rng.uniform(0, 2 * math.pi, n),
                    "rate": rng.uniform(0.5, 1.6, n), "sway": sway * self.k * rng.uniform(0.4, 1.0, n),
                    "which": which,
                    "sprites": [(_blob(max(3, round(s * self.k)), ring=kind == "bubbles", star=kind == "sparkle")
                                 [..., None] * np.array(colour, dtype=np.float32)) for s in sizes]}
            elif kind == "rain":
                n = max(1, int(round(230 * self.amount)))
                self._parts[kind] = {"x": rng.uniform(-0.2 * self.w, 1.2 * self.w, n), "y": rng.uniform(0, self.h, n),
                                     "v": rng.uniform(1500, 2300, n) * self.k, "len": rng.uniform(28, 62, n) * self.k,
                                     "a": rng.uniform(70, 160, n)}
            elif kind == "fog":
                self._layers[kind] = self._fog(rng)
            elif kind == "rays":
                self._layers[kind] = self._rays(rng)

    # ------------------------------------------------------------------ the layers made once
    def _fog(self, rng):
        """Two wide strips of soft cloud (uint8, three channels, already at their strength) that slide sideways;
        thickest in the lower half, where the ground is."""
        import cv2
        import numpy as np

        strips = []
        for octave in (5, 9):
            small = rng.random((octave * 2, octave * 4)).astype(np.float32)
            small[:, -1] = small[:, 0]  # the strip meets its own start, so it can slide for ever
            tex = cv2.resize(small, (self.w * 2, self.h), interpolation=cv2.INTER_CUBIC)
            yy = np.linspace(0.0, 1.0, self.h, dtype=np.float32)[:, None]
            where = 0.25 + 0.75 * np.clip((yy - 0.25) / 0.6, 0, 1)
            layer = (np.clip(tex, 0, 1) ** 1.6 * where * 62.0 * min(1.5, self.amount)).astype(np.uint8)
            layer = np.concatenate([layer, layer[:, :self.w]], axis=1)   # one frame more, to slide through the join
            strips.append(np.repeat(layer[..., None], 3, axis=2))
        return strips

    def _rays(self, rng):
        """Beams of light from an upper corner (uint8, three channels), warm."""
        import numpy as np

        left = bool(rng.integers(0, 2))
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        ox, oy = (-0.15 * self.w if left else 1.15 * self.w), -0.1 * self.h
        ang = np.arctan2(yy - oy, (xx - ox) if left else (ox - xx))
        dist = np.hypot(xx - ox, yy - oy) / math.hypot(self.w, self.h)
        beams = np.zeros_like(ang)
        for centre, width in zip(rng.uniform(0.75, 1.25, 4), rng.uniform(0.035, 0.09, 4)):
            beams += np.exp(-((ang - centre) / width) ** 2)
        light = np.clip(beams, 0, 1) * np.clip(1.15 - dist * 1.25, 0, 1) * 70.0 * min(1.5, self.amount)
        return (light[..., None] * np.array([0.72, 0.9, 1.0], dtype=np.float32)).astype(np.uint8)

    # ------------------------------------------------------------------ each frame
    def apply(self, frame, i: int) -> None:
        import cv2
        import numpy as np

        t = i / self.fps
        for kind in self.kinds:
            if kind == "fog":
                for n, strip in enumerate(self._layers[kind]):
                    off = int((t * (14 + 11 * n) * self.k) % (2 * self.w))
                    cv2.add(frame, strip[:, off:off + self.w], dst=frame)
            elif kind == "rays":
                breath = 0.8 + 0.2 * math.sin(t * 0.9)
                cv2.addWeighted(frame, 1.0, self._layers[kind], breath, 0.0, dst=frame)
            elif kind == "rain":
                p = self._parts[kind]
                layer = np.zeros((self.h, self.w), dtype=np.uint8)
                ys = (p["y"] + p["v"] * t) % (self.h + 80 * self.k) - 40 * self.k
                slant = 0.16
                for x, y, ln, a in zip(p["x"], ys, p["len"], p["a"]):
                    cv2.line(layer, (int(x - slant * (y + ln)), int(y + ln)), (int(x - slant * y), int(y)), int(a),
                             max(1, round(1.6 * self.k)), cv2.LINE_AA)
                cv2.add(frame, cv2.merge([layer, layer, layer]), dst=frame)
            else:
                self._particles(frame, kind, t)

    def _particles(self, frame, kind: str, t: float) -> None:
        import cv2
        import numpy as np

        p = self._parts[kind]
        pad = 80 * self.k
        xs = (p["x"] + p["vx"] * t + p["sway"] * np.sin(t * p["rate"] + p["phase"])) % (self.w + 2 * pad) - pad
        ys = (p["y"] + p["vy"] * t) % (self.h + 2 * pad) - pad
        if kind == "sparkle":      # a glint comes and goes where it is
            life = (t * p["rate"] * 0.9 + p["phase"]) % (2 * math.pi)
            alphas = p["a"] * np.clip(np.sin(life), 0, 1) ** 3
            xs, ys = p["x"], p["y"]
        elif kind in ("fireflies", "embers"):
            alphas = p["a"] * (0.55 + 0.45 * np.sin(t * p["rate"] * 5 + p["phase"]))
        else:
            alphas = p["a"] * (0.8 + 0.2 * np.sin(t * p["rate"] * 2 + p["phase"]))
        for x, y, a, which in zip(xs, ys, alphas, p["which"]):
            if a <= 0.02:
                continue
            sprite = p["sprites"][which]
            n = sprite.shape[0]
            x0, y0 = int(x) - n // 2, int(y) - n // 2
            if x0 >= self.w or y0 >= self.h or x0 + n <= 0 or y0 + n <= 0:
                continue
            sx0, sy0 = max(0, -x0), max(0, -y0)
            sx1, sy1 = min(n, self.w - x0), min(n, self.h - y0)
            roi = frame[y0 + sy0:y0 + sy1, x0 + sx0:x0 + sx1]
            cv2.add(roi, (sprite[sy0:sy1, sx0:sx1] * float(a)).astype(np.uint8), dst=roi)


# ------------------------------------------------------------------ the picture's finish (once, before it moves)
def finish(img, grade: dict | None):
    """The picture graded: {"contrast": 1.05, "saturation": 1.08, "warmth": 0.0 (-1 cool to 1 warm), "bloom": 0.15}.
    Small numbers: every scene of a short gets the same grade, so the pictures look like one film."""
    import cv2
    import numpy as np

    g = grade or {}

    def num(key: str, lo: float, hi: float, default: float) -> float:
        try:
            return min(hi, max(lo, float(g.get(key, default))))
        except (TypeError, ValueError):
            return default

    contrast, saturation = num("contrast", 0.8, 1.3, 1.0), num("saturation", 0.0, 1.6, 1.0)
    warmth, bloom = num("warmth", -1.0, 1.0, 0.0), num("bloom", 0.0, 0.6, 0.0)
    if contrast == 1.0 and saturation == 1.0 and warmth == 0.0 and bloom == 0.0:
        return img
    out = img.astype(np.float32)
    if bloom:
        small = cv2.resize(img, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA).astype(np.float32)
        bright = np.clip(small - 150.0, 0, None) * (255.0 / 105.0)
        glow = cv2.GaussianBlur(bright, (0, 0), max(2.0, small.shape[1] * 0.02))
        out += cv2.resize(glow, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR) * bloom
    if contrast != 1.0:
        out = (out - 127.5) * contrast + 127.5
    if saturation != 1.0:
        gray = out @ np.array([0.114, 0.587, 0.299], dtype=np.float32)
        out = gray[..., None] + (out - gray[..., None]) * saturation
    if warmth:
        out *= np.array([1.0 - 0.06 * warmth, 1.0, 1.0 + 0.06 * warmth], dtype=np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


class Frame:
    """What stays fixed to the screen: darker corners (`vignette` 0-0.6) and film grain (`grain` 0-12 levels)."""

    def __init__(self, size: tuple[int, int], vignette: float = 0.0, grain: float = 0.0, seed: int = 0):
        import numpy as np

        w, h = int(size[0]), int(size[1])
        self.vignette = None
        v = min(0.6, max(0.0, float(vignette or 0.0)))
        if v > 0.005:
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            r = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)) / math.sqrt(2)
            mask = 1.0 - v * np.clip((r - 0.45) / 0.55, 0, 1) ** 1.8
            self.vignette = np.repeat((mask * 255).astype(np.uint8)[..., None], 3, axis=2)
        self.grain = min(12.0, max(0.0, float(grain or 0.0)))
        self._noise = []
        if self.grain > 0.2:
            rng = _rng(seed, "grain")
            for _ in range(6):   # six grains in turn: enough that the eye sees no repeat
                tile = rng.normal(128.0, 42.0, (h // 2, w // 2)).clip(0, 255).astype(np.uint8)
                big = np.repeat(np.repeat(tile, 2, axis=0), 2, axis=1)
                big = np.pad(big, ((0, h - big.shape[0]), (0, w - big.shape[1])), mode="edge")
                self._noise.append(np.repeat(big[..., None], 3, axis=2))

    def apply(self, frame, i: int, flash: float = 0.0) -> None:
        import cv2

        if flash > 0.01:
            cv2.addWeighted(frame, 1.0 - 0.5 * flash, frame, 0.0, 255.0 * flash, dst=frame)
        if self.vignette is not None:
            cv2.multiply(frame, self.vignette, dst=frame, scale=1.0 / 255.0)
        if self._noise:
            a = self.grain / 42.0
            cv2.addWeighted(frame, 1.0, self._noise[i % len(self._noise)], a, -128.0 * a, dst=frame)

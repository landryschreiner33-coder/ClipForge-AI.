"""A designed picture for a scene of an animated short when no picture engine is set up
(docs/clipforge/ANIMATED_SHORTS.md).

A card is the look's colour gradient with soft shapes (placed differently in every scene, so the cuts still show a
change) and the scene's key words in big letters. The words sit between 18 and 42 percent of the height: clear of the
captions in the middle and of the buttons the phone apps put along the bottom and the right. A card is larger than the
video's frame (1242 x 2208 for 1080 x 1920) so the camera can push in on it and it stays sharp.

Cards are honest placeholders, not illustrations: the page says so and links to Settings → Pictures, video, voice.
"""
from __future__ import annotations

import logging
import math
import random
import zlib
from pathlib import Path

from .. import config
from . import scenes
from .looks import Look

SIZE = (1242, 2208)
BAND = (0.18, 0.42)          # where the key words sit, as shares of the height
TEXT_WIDTH = 0.84            # the words' widest line, as a share of the width
MAX_LINES = 3
FONT_SIZES = (230, 60)       # the largest and the smallest letters tried, at the card's own size
FALLBACK_FONT = "Poppins-Black.ttf"
SMALLEST = 12                # the letters of a word wider than the card at the smallest size shrink down to this
log = logging.getLogger(__name__)


class CardError(RuntimeError):
    """The card could not be drawn; the message says why."""


# ------------------------------------------------------------------ the words
def _word_score(word: str) -> float:
    low = word.lower()
    score = 1.0
    if any(c.isdigit() for c in low) or low in scenes._NUMBER_WORDS:
        score += 3.0
    if len(low) >= 7:
        score += 1.5
    elif len(low) >= 5:
        score += 1.0
    if word[:1].isupper() and not word.isupper():
        score += 1.0   # a name ("Cleopatra"), since sentence starts are lowercased
    return score


def key_words(narration: str, limit: int = 4) -> str:
    """The scene's key words for its card: the runs of words that carry the picture, the strongest first, at most
    `limit` words, in the order they are said ("octopuses three hearts")."""
    runs = [r for r in scenes.chunks(narration) if not (len(r) == 1 and r[0].lower() in scenes.GENERIC)]
    if not runs:
        words = [w.strip(".,!?;:\"'“”‘’()[]") for w in str(narration or "").split()]
        return " ".join(w for w in words if w)[:60]
    limit = max(1, int(limit))
    scored = []
    for k, run in enumerate(runs):
        if len(run) > limit:  # the strongest window of a long run
            best = max(range(len(run) - limit + 1), key=lambda i: sum(_word_score(w) for w in run[i:i + limit]))
            run = run[best:best + limit]
        scored.append((max(_word_score(w) for w in run) + 0.2 * len(run), k, run))
    chosen, used = [], 0
    for _, k, run in sorted(scored, key=lambda x: (-x[0], x[1])):
        if used + len(run) <= limit:
            chosen.append((k, run))
            used += len(run)
    return " ".join(" ".join(run) for _, run in sorted(chosen))


# ------------------------------------------------------------------ drawing
def _rgb(colour: str) -> tuple[int, int, int]:
    s = colour.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except (ValueError, IndexError):
        return 255, 255, 255


def _luma(rgb: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _font(look: Look, size: int):
    from PIL import ImageFont

    for name in (look.font, FALLBACK_FONT):
        path = Path(config.FONTS_DIR) / name
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # an old Pillow without sizes
        return ImageFont.load_default()


def _wrap(draw, words: list[str], font, width: int) -> list[str] | None:
    lines: list[str] = []
    for w in words:
        if lines and draw.textlength(f"{lines[-1]} {w}", font=font) <= width:
            lines[-1] = f"{lines[-1]} {w}"
        elif draw.textlength(w, font=font) <= width:
            lines.append(w)
        else:
            return None
    return lines if len(lines) <= MAX_LINES else None


def _fit(draw, text: str, look: Look, width: int, height: int):
    words = text.split()
    hi, lo = FONT_SIZES
    size = hi
    while size >= lo:
        font = _font(look, size)
        lines = _wrap(draw, words, font, width) if words else []
        if lines is not None:
            line_h = size * 1.08
            if line_h * len(lines) <= height:
                return font, lines, line_h
        size = int(size * 0.92)
    # too long even at the smallest size: a word wider than the card gets smaller letters, and lines past the last
    # are left out, so nothing is ever drawn past the edge
    size = lo
    font = _font(look, size)
    while size > SMALLEST and words and max(draw.textlength(w, font=font) for w in words) > width:
        size = max(SMALLEST, int(size * 0.9))
        font = _font(look, size)
    lines, line = [], ""
    for w in words:
        if draw.textlength(f"{line} {w}".strip(), font=font) <= width:
            line = f"{line} {w}".strip()
        else:
            lines.append(line)
            line = w
    lines.append(line)
    return font, [ln for ln in lines if ln][:MAX_LINES], size * 1.08


def _background(look: Look, size: tuple[int, int], rng: random.Random):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    w, h = size
    top, bottom, accent = (np.array(_rgb(c), dtype=np.float32) for c in (look.top, look.bottom, look.accent))
    t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    shift = rng.uniform(-0.12, 0.12)
    t = np.clip(t + shift * np.sin(np.linspace(0, math.pi, w, dtype=np.float32))[None, :, None], 0.0, 1.0)
    grad = top * (1 - t) + bottom * t
    # a soft light where the words are, so they read on any gradient
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w * rng.uniform(0.35, 0.65), h * (BAND[0] + BAND[1]) / 2
    glow = np.exp(-(((xx - cx) / (w * 0.55)) ** 2 + ((yy - cy) / (h * 0.22)) ** 2))[..., None]
    grad = grad * (1 - 0.18 * glow) + 255 * 0.18 * glow if _luma(_rgb(look.ink)) < 0.5 else grad * (1 + 0.12 * glow)
    img = Image.fromarray(np.clip(grad, 0, 255).astype("uint8"), "RGB")
    # soft shapes in the accent colour, placed by the scene's number
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ac = tuple(int(c) for c in accent)
    for _ in range(rng.randint(4, 6)):
        r = rng.uniform(0.12, 0.34) * w
        x, y = rng.uniform(-0.1, 1.1) * w, rng.choice((rng.uniform(0.0, 0.2), rng.uniform(0.45, 1.05))) * h
        d.ellipse((x - r, y - r, x + r, y + r), fill=(*ac, rng.randint(50, 110)))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=w * 0.035))
    crisp = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(crisp)
    for _ in range(rng.randint(5, 9)):
        r = rng.uniform(0.008, 0.03) * w
        x, y = rng.uniform(0.04, 0.96) * w, rng.uniform(0.05, 0.95) * h
        if BAND[0] * h - r < y < BAND[1] * h + r and 0.08 * w < x < 0.92 * w:
            continue  # nothing behind the words
        if rng.random() < 0.5:
            d.ellipse((x - r, y - r, x + r, y + r), fill=(*ac, 200))
        else:
            d.ellipse((x - r, y - r, x + r, y + r), outline=(*ac, 210), width=max(2, int(r * 0.35)))
    img = Image.alpha_composite(img.convert("RGBA"), layer)
    return Image.alpha_composite(img, crisp)


def make_card(text: str, look: Look, out: Path, *, index: int = 0, size: tuple[int, int] = SIZE,
              seed: int = 0) -> Path:
    """Draw a scene's card into `out` (PNG) and return its path: the same card for the same look, scene number and
    seed (New picture gives the scene a new seed, so its shapes move). Raises CardError."""
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError as exc:  # pillow is in requirements.txt
        raise CardError("ClipForge could not draw the scene's card: Pillow is missing. Reinstall ClipForge.") from exc
    w, h = int(size[0]), int(size[1])
    rng = random.Random(zlib.crc32(f"{look.id}:{int(index)}{f':{int(seed)}' if seed else ''}".encode()))
    try:
        img = _background(look, (w, h), rng)
        words = " ".join(str(text or "").split()).upper()
        draw = ImageDraw.Draw(img)
        band_top, band_h = BAND[0] * h, (BAND[1] - BAND[0]) * h
        font, lines, line_h = _fit(draw, words, look, int(w * TEXT_WIDTH), int(band_h * 0.9))
        ink = _rgb(look.ink)
        edge = (20, 20, 28) if _luma(ink) > 0.5 else (255, 255, 255)
        stroke = max(3, int(font.size * 0.06)) if hasattr(font, "size") else 3
        block_h = line_h * len(lines)
        y0 = band_top + (band_h - block_h) / 2
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        for k, line in enumerate(lines):
            x = (w - draw.textlength(line, font=font)) / 2
            sd.text((x + stroke, y0 + k * line_h + stroke * 1.6), line, font=font, fill=(0, 0, 0, 120),
                    stroke_width=stroke, stroke_fill=(0, 0, 0, 120))
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(radius=max(4, stroke * 1.4))))
        draw = ImageDraw.Draw(img)
        for k, line in enumerate(lines):
            x = (w - draw.textlength(line, font=font)) / 2
            draw.text((x, y0 + k * line_h), line, font=font, fill=(*ink, 255), stroke_width=stroke,
                      stroke_fill=(*edge, 255))
        if lines:
            bar_w = min(w * 0.32, max(draw.textlength(ln, font=font) for ln in lines) * 0.5)
            by = y0 + block_h + line_h * 0.12
            draw.rounded_rectangle(((w - bar_w) / 2, by, (w + bar_w) / 2, by + max(8, h * 0.006)),
                                   radius=int(max(4, h * 0.003)), fill=(*_rgb(look.accent), 255))
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(out, "PNG")
    except CardError:
        raise
    except (OSError, ValueError) as exc:
        log.warning("the card could not be drawn: %s", exc)
        raise CardError("ClipForge could not draw or save this scene's card. Check that the disk has free space, "
                        "then press Try again.") from exc
    return out

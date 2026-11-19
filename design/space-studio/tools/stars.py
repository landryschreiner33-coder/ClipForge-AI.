"""Crisp small stars for the sky, as two transparent tiles the page repeats at screen size (2026-11-19).

The sky picture is scaled to fit the window, which blurs one-pixel stars away; these tiles are never scaled on an
ordinary screen, so their stars stay sharp. Two tiles of different sizes overlap so the repeat is hard to spot."""
import numpy as np, cv2
from PIL import Image

COLOURS = np.array([[236, 240, 255], [178, 204, 255], [255, 228, 196], [214, 190, 255]], np.float32)


def tile(size, n_small, n_mid, n_glow, seed):
    rng = np.random.default_rng(seed)
    rgb = np.zeros((size, size, 3), np.float32); alpha = np.zeros((size, size), np.float32)

    def put(x, y, a, col):
        x %= size; y %= size  # wrap so the tile repeats without seams
        keep = a > alpha[y, x]
        alpha[y, x] = np.where(keep, a, alpha[y, x]); rgb[y, x] = np.where(keep, col, rgb[y, x])

    def colour():
        return COLOURS[rng.choice(4, p=[0.62, 0.22, 0.1, 0.06])]
    for _ in range(n_small):  # single pixels
        put(int(rng.integers(size)), int(rng.integers(size)), rng.uniform(0.35, 0.85), colour())
    for _ in range(n_mid):  # a bright pixel with a soft cross
        x, y, c, a = int(rng.integers(size)), int(rng.integers(size)), colour(), rng.uniform(0.75, 1.0)
        put(x, y, a, c)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            put(x + dx, y + dy, a * 0.38, c)
    for _ in range(n_glow):  # a few with a small halo
        x, y, c = int(rng.integers(size)), int(rng.integers(size)), colour()
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                d = (dx * dx + dy * dy) ** 0.5
                if d <= 3.2:
                    put(x + dx, y + dy, float(np.exp(-d * d / 1.6)) * 0.95, c)
    out = np.dstack([rgb, alpha * 255]).clip(0, 255).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')


if __name__ == '__main__':
    tile(512, 150, 26, 4, 3).save('out/stars-near.png', optimize=True)
    tile(797, 190, 18, 3, 8).save('out/stars-far.png', optimize=True)

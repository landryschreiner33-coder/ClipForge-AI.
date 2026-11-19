"""Deep-navy space sky: blue-violet nebula dust in a diagonal band, bright stars, sparkles and small galaxies.

Stars smaller than a pixel vanish once the page scales this picture to the window, so it carries the nebula and the
bigger stars; stars.py makes the crisp small stars, tiled at screen size (2026-11-19: the owner wants to see the stars)."""
import numpy as np, cv2
from PIL import Image
W, H = 2400, 1500
rng = np.random.default_rng(11)

def fbm(w, h, octaves=7, base=3, persistence=0.55, seed=0):
    r = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32); amp = 1.0; tot = 0
    for o in range(octaves):
        gw, gh = base * 2 ** o + 1, int(base * 2 ** o * h / w) + 2
        g = r.random((gh, gw)).astype(np.float32)
        out += cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC) * amp
        tot += amp; amp *= persistence
    return out / tot

yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
u, v = xx / W, yy / H
# base: deep navy with a slight lift toward the lower left
base = np.dstack([np.full((H, W), 6.0), np.full((H, W), 10.0), np.full((H, W), 26.0)])
base += np.dstack([0 * u, 2 * (1 - u) * v, 6 * (1 - u) * v])
# diagonal band from lower left to upper right, plus a softer wisp down the left edge
d1 = (v - (0.95 - 0.75 * u))  # distance-ish to the band's centre line
warp = (fbm(W, H, seed=9, base=3, octaves=4) - 0.5) * 0.22
band = np.exp(-((d1 + warp) / 0.13) ** 2)
left = np.exp(-((u - 0.02 + warp * 0.3) / 0.06) ** 2) * (0.25 + 0.75 * v)
n1 = fbm(W, H, seed=1); n2 = fbm(W, H, seed=2, base=5); n3 = fbm(W, H, seed=3, base=9, octaves=6)
dust = np.clip((n1 - 0.42) * 2.4, 0, 1) ** 1.6
fil = np.clip((n2 - 0.5) * 3.0, 0, 1) ** 2
n4 = fbm(W, H, seed=5, base=24, octaves=5, persistence=0.6)
streak = np.clip((n4 - 0.52) * 5.0, 0, 1) ** 1.5
mask = np.clip(band * 0.85 + left * 0.75, 0, 1)
blue = np.array([34, 62, 160], np.float32); violet = np.array([104, 52, 172], np.float32); ice = np.array([96, 150, 240], np.float32)
magenta = np.array([150, 60, 160], np.float32)
mix = np.clip(n3 * 1.6 - 0.3, 0, 1)[..., None]
neb_col = blue * (1 - mix) + violet * mix
pink = np.clip((fbm(W, H, seed=7, base=4, octaves=5) - 0.58) * 4, 0, 1)[..., None]
neb_col = neb_col * (1 - 0.6 * pink) + magenta * (0.6 * pink)
neb = neb_col * (dust * mask)[..., None] * 0.95 + ice * (fil * mask * 0.35)[..., None]
neb += np.array([60, 105, 225], np.float32) * (streak * dust * mask * 0.85)[..., None]
img = base + neb * 1.05
# dark lanes inside the band
lanes = np.clip((fbm(W, H, seed=4, base=6) - 0.55) * 4, 0, 1)
img *= (1 - 0.45 * lanes * mask)[..., None]
# stars: many faint, denser in the band
def stars(n, lo, hi, size):
    global img
    xs = rng.integers(0, W, n); ys = rng.integers(0, H, n)
    keep = rng.random(n) < (0.25 + 0.75 * mask[ys, xs])
    xs, ys = xs[keep], ys[keep]
    b = rng.uniform(lo, hi, len(xs))
    tint = rng.choice([0, 1, 2], len(xs), p=[0.7, 0.2, 0.1])
    cols = np.array([[235, 238, 255], [180, 205, 255], [255, 226, 190]], np.float32)[tint]
    layer = np.zeros_like(img)
    layer[ys, xs] = cols * b[:, None]
    if size > 0:
        layer = cv2.GaussianBlur(layer, (0, 0), size) * (2 * np.pi * size * size) * 0.6
    img += layer
stars(20000, 0.10, 0.45, 0)
stars(5200, 0.45, 1.0, 0.7)
stars(900, 0.75, 1.0, 1.1)
stars(120, 0.9, 1.0, 1.8)
# a few four-point sparkles
for _ in range(34):
    x, y = int(rng.integers(40, W - 40)), int(rng.integers(40, H - 40))
    L = int(rng.integers(10, 30)); c = np.array([255, 245, 235], np.float32) * rng.uniform(0.75, 1.0)
    spark = np.zeros((2 * L + 1, 2 * L + 1), np.float32)
    k = np.arange(-L, L + 1); f = np.exp(-np.abs(k) / (L / 4.0))
    spark[L, :] = f; spark[:, L] = np.maximum(spark[:, L], f)
    spark = cv2.GaussianBlur(spark, (0, 0), 0.8) * 1.9
    halo = np.zeros_like(spark); cv2.circle(halo, (L, L), 2, 1.0, -1)
    spark += cv2.GaussianBlur(halo, (0, 0), L / 5.0) * 1.4
    img[y - L:y + L + 1, x - L:x + L + 1] += spark[..., None] * c
# small distant galaxies: a warm core and two faint arms, tilted
for gx, gy, ang, size in [(int(W * 0.07), int(H * 0.47), 25, 0.9), (int(W * 0.74), int(H * 0.66), -30, 1.1),
                          (int(W * 0.96), int(H * 0.30), 15, 0.7)]:
    S = int(130 * size); c0 = S // 2
    g = np.zeros((S, S, 3), np.float32)
    t = np.linspace(0, 3.2 * np.pi, 900)
    for arm in (0, np.pi):
        r = 3 + t * S * 0.045
        px = c0 + r * np.cos(t + arm); py = c0 + r * np.sin(t + arm)
        for k in range(len(t)):
            xi, yi = int(px[k]), int(py[k])
            if 0 <= xi < S and 0 <= yi < S:
                g[yi, xi] += np.array([150, 170, 255], np.float32) * (1 - k / len(t)) * 0.9
    g = cv2.GaussianBlur(g, (0, 0), 3.4 * size) * 3.4
    disk = np.zeros((S, S), np.float32); cv2.circle(disk, (c0, c0), int(S * 0.26), 1.0, -1)
    g += cv2.GaussianBlur(disk, (0, 0), S * 0.07)[..., None] * np.array([120, 130, 220], np.float32) * 0.35
    core = np.zeros((S, S), np.float32); cv2.circle(core, (c0, c0), max(2, int(5 * size)), 1.0, -1)
    g += cv2.GaussianBlur(core, (0, 0), 4 * size)[..., None] * np.array([255, 214, 160], np.float32) * 2.6
    M = cv2.getRotationMatrix2D((c0, c0), ang, 1.0)  # turn, then squash so it looks inclined
    g = cv2.warpAffine(g, M, (S, S))
    g = cv2.resize(g, (S, int(S * 0.42)))
    h2 = g.shape[0]
    y0, x0 = gy - h2 // 2, gx - S // 2
    img[y0:y0 + h2, x0:x0 + S] += g * 0.45
img = np.clip(img, 0, 255).astype(np.uint8)
Image.fromarray(img).save('out/sky.jpg', quality=90, subsampling=0, optimize=True, progressive=True)
Image.fromarray(img).resize((1200, 750), Image.LANCZOS).save('out/sky_small.png')

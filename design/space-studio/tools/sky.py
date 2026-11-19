"""Deep-navy space sky: fine stars, a few sparkles and blue-violet nebula dust in a diagonal band."""
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
blue = np.array([28, 54, 140], np.float32); violet = np.array([86, 46, 150], np.float32); ice = np.array([90, 140, 230], np.float32)
mix = np.clip(n3 * 1.6 - 0.3, 0, 1)[..., None]
neb_col = blue * (1 - mix) + violet * mix
neb = neb_col * (dust * mask)[..., None] * 0.95 + ice * (fil * mask * 0.35)[..., None]
neb += np.array([60, 105, 225], np.float32) * (streak * dust * mask * 0.85)[..., None]
img = base + neb * 0.72
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
stars(26000, 0.10, 0.45, 0)
stars(30000, 0.10, 0.50, 0)
stars(2600, 0.35, 0.9, 0.6)
stars(260, 0.7, 1.0, 1.1)
# a few four-point sparkles
for _ in range(16):
    x, y = int(rng.integers(40, W - 40)), int(rng.integers(40, H - 40))
    L = int(rng.integers(8, 20)); c = np.array([255, 245, 235], np.float32) * rng.uniform(0.55, 0.9)
    spark = np.zeros((2 * L + 1, 2 * L + 1), np.float32)
    k = np.arange(-L, L + 1); f = np.exp(-np.abs(k) / (L / 4.0))
    spark[L, :] = f; spark[:, L] = np.maximum(spark[:, L], f)
    spark = cv2.GaussianBlur(spark, (0, 0), 0.7) * 1.6
    img[y - L:y + L + 1, x - L:x + L + 1] += spark[..., None] * c
# two tiny distant galaxies
for gx, gy, ang in [(int(W * 0.18), int(H * 0.30), 25), (int(W * 0.72), int(H * 0.64), -30)]:
    g = np.zeros((90, 90), np.float32)
    cv2.ellipse(g, (45, 45), (26, 7), ang, 0, 360, 1.0, -1)
    g = cv2.GaussianBlur(g, (0, 0), 4) * 0.55
    core = np.zeros((90, 90), np.float32); cv2.circle(core, (45, 45), 2, 1.0, -1); core = cv2.GaussianBlur(core, (0, 0), 1.5) * 2
    col = np.array([255, 200, 150], np.float32)
    img[gy - 45:gy + 45, gx - 45:gx + 45] += (g + core)[..., None] * col * 0.5
img = np.clip(img, 0, 255).astype(np.uint8)
Image.fromarray(img).save('out/sky.jpg', quality=84, optimize=True, progressive=True)
Image.fromarray(img).resize((1200, 750), Image.LANCZOS).save('out/sky_small.png')

import numpy as np, cv2
from PIL import Image
OUT = 'out/'
def grabcut(img, rect, iters=6, sure_fg=(), sure_bg=(), max_hole=10 ** 9):
    mask = np.zeros(img.shape[:2], np.uint8)
    bgd = np.zeros((1, 65)); fgd = np.zeros((1, 65))
    cv2.grabCut(img, mask, rect, bgd, fgd, iters, cv2.GC_INIT_WITH_RECT)
    if sure_fg or sure_bg:
        for x0, y0, x1, y1 in sure_fg: mask[y0:y1, x0:x1] = cv2.GC_FGD
        for x0, y0, x1, y1 in sure_bg: mask[y0:y1, x0:x1] = cv2.GC_BGD
        cv2.grabCut(img, mask, None, bgd, fgd, 3, cv2.GC_INIT_WITH_MASK)
    m = np.where((mask == 1) | (mask == 3), 255, 0).astype(np.uint8)
    # fill holes and keep the biggest piece
    inv = (m == 0).astype(np.uint8)
    n, lab = cv2.connectedComponents(inv, 4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
    for l in range(1, n):
        if l not in border and (lab == l).sum() <= max_hole: m[lab == l] = 255
    n2, lab2, st, _ = cv2.connectedComponentsWithStats((m > 0).astype(np.uint8), 8)
    big = 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])
    return np.where(lab2 == big, 255, 0).astype(np.uint8)

def soft(m, r=1.2):
    return cv2.GaussianBlur(m.astype(np.float32), (0, 0), r)

# --- black hole: keep the pixels, feather an ellipse so the sky blends into ours
def black_hole():
    bh = cv2.imread(OUT + 'bh_crop.png')[:246]
    h, w = bh.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = 355, 128
    d = ((xx - cx) / 352.0) ** 2 + ((yy - cy) / 150.0) ** 2
    a = np.clip((1.0 - d) / 0.35, 0, 1) ** 1.4
    # luminance keeps the faint outer disk while the empty sky fades out
    lum = bh.astype(np.float32).max(axis=2) / 255.0
    a = np.maximum(a * np.clip(lum * 3.0, 0.0, 1.0), np.where(((xx - cx) / 92.0) ** 2 + ((yy - 127) / 92.0) ** 2 < 1, 1.0, 0.0) * a)
    # the reference crop ends at the arc above and the lower ring below: fade both edges so no straight line shows
    a *= np.clip(yy / 18.0, 0, 1) ** 1.2 * np.clip((h - 1 - yy) / 14.0, 0, 1) ** 1.2
    rgba = np.dstack([bh[..., ::-1], (a * 255).astype(np.uint8)])
    Image.fromarray(rgba, 'RGBA').save(OUT + 'blackhole.png')
    # where the disk is bright: the mask for the light that travels along it (space.css .black-hole .glint)
    glow = np.clip((lum - 0.32) / 0.5, 0, 1) * a
    white = np.full((h, w, 3), 255, np.uint8)
    Image.fromarray(np.dstack([white, (glow * 255).astype(np.uint8)]), 'RGBA').save(OUT + 'blackhole-glow.png')


def scenes():
    # --- satellite: cut it out, and paint it out of the orbit background
    sat = cv2.imread(OUT + 'sat_crop.png')[:426, :694]
    m = grabcut(sat, (150, 85, 425, 185), sure_fg=[(170, 128, 290, 185), (378, 96, 390, 150), (300, 150, 420, 240),
                (425, 200, 560, 262)])
    ys, xs = np.where(m > 0)
    print('sat bbox', xs.min(), ys.min(), xs.max(), ys.max())
    sat_rgba = np.dstack([sat[..., ::-1], soft(m).clip(0, 255).astype(np.uint8)])
    Image.fromarray(sat_rgba[ys.min() - 2:ys.max() + 3, xs.min() - 2:xs.max() + 3], 'RGBA').save(OUT + 'satellite.png')
    open(OUT + 'satellite_pos.txt', 'w').write(f'{xs.min() - 2} {ys.min() - 2}')
    dil = cv2.dilate(m, np.ones((9, 9), np.uint8))
    bgimg = cv2.inpaint(sat, dil, 6, cv2.INPAINT_TELEA)
    # feather the left edge so the orbit art melts into the card
    h, w = bgimg.shape[:2]
    fade = np.clip(np.arange(w) / 260.0, 0, 1) ** 1.6
    alpha = np.tile(fade, (h, 1))
    Image.fromarray(np.dstack([bgimg[..., ::-1], (alpha * 255).astype(np.uint8)]), 'RGBA').save(OUT + 'orbit.png')

    # --- Dock on its platform
    dk = cv2.imread(OUT + 'dock_crop.png')
    m = grabcut(dk, (30, 10, 610, 330), sure_fg=[(190, 90, 340, 270), (380, 20, 520, 270), (60, 205, 180, 280)],
                sure_bg=[(0, 0, 640, 8), (0, 0, 25, 360), (296, 20, 372, 76), (520, 160, 640, 200)], max_hole=400)
    ys, xs = np.where(m > 0)
    print('dock bbox', xs.min(), ys.min(), xs.max(), ys.max())
    dk_rgba = np.dstack([dk[..., ::-1], soft(m).clip(0, 255).astype(np.uint8)])
    Image.fromarray(dk_rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1], 'RGBA').save(OUT + 'dock_scene.png')
    open(OUT + 'dock_pos.txt', 'w').write(f'{xs.min()} {ys.min()}')


if __name__ == '__main__':
    black_hole()
    scenes()

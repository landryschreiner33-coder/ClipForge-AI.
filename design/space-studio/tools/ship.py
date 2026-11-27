"""Build the Studio ship layers at native pixel size (768 x 384) from the cutaway artwork."""
import sys, numpy as np, cv2
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from robots_bbox import BAKED
SRC = '/mnt/project-files/space-studio/references/2-ship-cutaway.png'
W, H = 768, 384
K = W / 1774.0

def native_hull(mask_path):
    img = cv2.imread(SRC).astype(np.float32)
    mask = cv2.imread(mask_path, 0).astype(np.float32) / 255.0
    sp = cv2.resize(img * mask[..., None], (W, H), interpolation=cv2.INTER_AREA)
    sa = cv2.resize(mask, (W, H), interpolation=cv2.INTER_AREA)
    col = sp / np.maximum(sa[..., None], 1e-6)
    return col, sa >= 0.5

def floor_mask(col, alpha):
    lab = cv2.cvtColor(np.clip(col, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
    boxes = [(300, 165, 420, 188), (200, 218, 214, 230), (472, 268, 492, 280), (630, 120, 650, 135)]
    sample = np.concatenate([lab[y0:y1, x0:x1].reshape(-1, 3) for x0, y0, x1, y1 in boxes])
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, _, centers = cv2.kmeans(sample, 8, None, crit, 4, cv2.KMEANS_PP_CENTERS)
    d = np.min(((lab[:, :, None, :] - centers[None, None]) ** 2).sum(-1), axis=2)
    m = (d < 9 ** 2) & alpha
    # floor is a broad surface: drop specks that are only floor-coloured by accident
    m8 = m.astype(np.uint8)
    n, lab_, st, _ = cv2.connectedComponentsWithStats(m8, 4)
    keep = np.zeros_like(m)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= 60:
            keep[lab_ == i] = True
    return keep

def station_rects():
    out = []
    for n, x0, y0, x1, y1 in BAKED:
        if n == 'a-green':  # stands at the conveyor's end, no desk
            r = (x0 - 2, y0 - 3, x1 + 4, y1 + 2)
        elif n.startswith('b-'):
            r = (x0 - 22, y0 - 8, x1 + 22, y1 + 14)
        elif n.startswith(('a-', 'c-', 'd-', 'e-', 'f-', 'g-', 'core-')):
            r = (x0 - 22, y0 - 3, x1 + 22, y1 + 14)
        elif n == 'bridge':
            continue
        else:
            r = (x0 - 3, y0 - 3, x1 + 3, y1 + 3)
        out.append((n, int(r[0] * K), int(r[1] * K), int(np.ceil(r[2] * K)), int(np.ceil(r[3] * K))))
    return out

def repaint_floor(col, alpha, floor, forced, tile=6):
    f = floor.copy()
    for _, x0, y0, x1, y1 in forced:
        f[y0:y1, x0:x1] = alpha[y0:y1, x0:x1]
    known = floor.copy()
    for _, x0, y0, x1, y1 in forced:
        known[y0:y1, x0:x1] = False
    kf = known.astype(np.float32)
    # lighting: normalised blur of the known floor colour, so lamp pools and wall shading survive
    blur = lambda a, s: cv2.GaussianBlur(a, (0, 0), s)
    num = blur(col * kf[..., None], 3.0); den = blur(kf, 3.0)
    light = num / np.maximum(den[..., None], 1e-4)
    num2 = blur(col * kf[..., None], 9.0); den2 = blur(kf, 9.0)
    light2 = num2 / np.maximum(den2[..., None], 1e-4)
    light = np.where(den[..., None] > 0.25, light, light2)
    yy, xx = np.mgrid[0:H, 0:W]
    line = (xx % tile == 0) | (yy % tile == 0)
    hi = ((xx % tile == 1) & (yy % tile != 0)) | ((yy % tile == 1) & (xx % tile != 0))
    rng = np.random.default_rng(7)
    noise = 1 + (rng.random((H, W)) - 0.5) * 0.05
    fac = np.where(line, 0.82, np.where(hi, 1.06, 1.0)) * noise
    newc = light * fac[..., None]
    out = col.copy()
    out[f] = newc[f]
    return out, f

INPAINT = [(503, 66, 538, 101), (656, 101, 681, 131)]  # CORE's painted brain + beam; COMMAND on the bridge

def inpaint(col):
    img = np.clip(col, 0, 255).astype(np.uint8)
    m = np.zeros(img.shape[:2], np.uint8)
    for x0, y0, x1, y1 in INPAINT:
        m[y0:y1, x0:x1] = 255
    return cv2.inpaint(img, m, 4, cv2.INPAINT_TELEA).astype(np.float32)

def quantize(col, alpha, k=96):
    pts = col[alpha].reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.5)
    _, lab, centers = cv2.kmeans(pts, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    q = np.zeros((H, W, 3), np.uint8)
    q[alpha] = centers[lab.ravel()].clip(0, 255).astype(np.uint8)
    return q

if __name__ == '__main__':
    from PIL import Image
    col, alpha = native_hull(sys.argv[1])
    fl = floor_mask(col, alpha)
    cv2.imwrite('out/floor_mask_native.png', (fl * 255).astype(np.uint8))
    col2, f = repaint_floor(col, alpha, fl, station_rects())
    col2 = inpaint(col2)
    q = quantize(col2, alpha)
    np.save('out/floor_final.npy', f)
    rgba = np.dstack([q[..., ::-1], (alpha * 255).astype(np.uint8)])
    Image.fromarray(rgba, 'RGBA').save(sys.argv[2])

import sys, numpy as np, cv2
from PIL import Image
from cells import CELLS

def fg_mask(rgb):
    h, w, _ = rgb.shape
    border = np.concatenate([rgb[:4].reshape(-1, 3), rgb[-4:].reshape(-1, 3), rgb[:, :4].reshape(-1, 3), rgb[:, -4:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    dist = np.abs(rgb.astype(int) - bg.astype(int)).max(axis=2)
    m = (dist > 22).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # components: drop small ones and the label text (anything whose top is in the bottom 12%)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = areas.max() if len(areas) else 0
    for i in range(1, n):
        x, y, ww, hh, a = stats[i]
        if a < max(40, big * 0.004):
            continue
        if y > h * 0.88:
            continue
        keep[lab == i] = 1
    # include the dark outline: dilate a little, then fill holes
    keep = cv2.dilate(keep, np.ones((7, 7), np.uint8))
    ff = keep.copy() * 255
    pad = np.zeros((h + 2, w + 2), np.uint8)
    inv = (255 - ff).astype(np.uint8)
    cv2.floodFill(inv, pad, (0, 0), 0)
    holes = inv > 0
    keep[holes] = 1
    keep = cv2.erode(keep, np.ones((3, 3), np.uint8))
    return keep, bg

def downsample(rgb, mask, H):
    ys, xs = np.where(mask > 0)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    rgb = rgb[y0:y1, x0:x1].astype(np.float32); mask = mask[y0:y1, x0:x1].astype(np.float32)
    h, w = mask.shape
    W = max(1, round(w * H / h))
    # area-average premultiplied colour
    pre = rgb * mask[..., None]
    small_pre = cv2.resize(pre, (W, H), interpolation=cv2.INTER_AREA)
    small_a = cv2.resize(mask, (W, H), interpolation=cv2.INTER_AREA)
    col = small_pre / np.maximum(small_a[..., None], 1e-6)
    return col, small_a

def quantize(col, alpha, k):
    pts = col[alpha >= 0.5].reshape(-1, 3).astype(np.float32)
    k = min(k, len(pts))
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
    _, labels, centers = cv2.kmeans(pts, k, None, crit, 6, cv2.KMEANS_PP_CENTERS)
    out = np.zeros(col.shape[:2] + (4,), np.uint8)
    flat = col.reshape(-1, 3)
    d = ((flat[:, None, :] - centers[None]) ** 2).sum(-1)
    idx = d.argmin(1).reshape(col.shape[:2])
    q = centers[idx].clip(0, 255).astype(np.uint8)
    out[..., :3] = q
    out[..., 3] = np.where(alpha >= 0.5, 255, 0)
    return out

def outline(rgba, color=(11, 10, 22)):
    a = rgba[..., 3] > 0
    ap = np.pad(a, 1)
    near = np.zeros_like(ap)
    near[1:, :] |= ap[:-1, :]; near[:-1, :] |= ap[1:, :]
    near[:, 1:] |= ap[:, :-1]; near[:, :-1] |= ap[:, 1:]
    ring = near & ~ap
    out = np.pad(rgba, ((1, 1), (1, 1), (0, 0)))
    out[ring] = (*color, 255)
    return out

def run(H, k, name_filter=None):
    sheets = {}
    res = {}
    for n, s, x0, y0, x1, y1 in CELLS:
        if name_filter and n not in name_filter: continue
        im = sheets.setdefault(s, np.array(Image.open(s).convert('RGB')))
        crop = im[y0:y1, x0:x1]
        m, bg = fg_mask(crop)
        col, a = downsample(crop, m, H)
        q = quantize(col, a, k)
        res[n] = outline(q)
    return res

if __name__ == '__main__':
    H = int(sys.argv[1]); k = int(sys.argv[2]); scale = int(sys.argv[3]); out = sys.argv[4]
    res = run(H, k)
    cols = 9
    cw = max(v.shape[1] for v in res.values()); ch = max(v.shape[0] for v in res.values())
    sheet = Image.new('RGBA', (cols * (cw + 2) * scale, ((len(res) + cols - 1) // cols) * (ch + 2) * scale), (40, 44, 70, 255))
    for i, (n, v) in enumerate(res.items()):
        im = Image.fromarray(v, 'RGBA').resize((v.shape[1] * scale, v.shape[0] * scale), Image.NEAREST)
        sheet.alpha_composite(im, ((i % cols) * (cw + 2) * scale, (i // cols) * (ch + 2) * scale))
    sheet.save(out)
    print({n: v.shape[:2] for n, v in res.items()})

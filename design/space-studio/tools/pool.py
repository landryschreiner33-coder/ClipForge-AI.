import numpy as np, colorsys
from PIL import Image
from extract import run, outline

OUT = (11, 10, 22)

def strip_outline(rgba):
    a = rgba[..., 3] > 0
    is_out = a & (np.abs(rgba[..., :3].astype(int) - OUT).sum(-1) < 6)
    r = rgba.copy(); r[is_out] = 0
    # crop the 1px border added by outline()
    return r[1:-1, 1:-1]

def emissive(c):
    r, g, b = [x / 255 for x in c]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return s > 0.45 and v > 0.55

def pool2(rgba):
    h, w = rgba.shape[:2]
    H, W = (h + 1) // 2, (w + 1) // 2
    pad = np.zeros((H * 2, W * 2, 4), np.uint8); pad[:h, :w] = rgba
    out = np.zeros((H, W, 4), np.uint8)
    for y in range(H):
        for x in range(W):
            blk = pad[y*2:y*2+2, x*2:x*2+2].reshape(-1, 4)
            op = [tuple(p[:3]) for p in blk if p[3] > 0]
            if len(op) < 2:
                continue
            score = {}
            for c in op:
                score[c] = score.get(c, 0) + 1 + (1.6 if emissive(c) else 0)
            best = max(score.items(), key=lambda kv: (kv[1], -sum(kv[0])))[0]
            out[y, x] = (*best, 255)
    return out

if __name__ == '__main__':
    import sys
    res = run(40, 14)
    small = {n: outline(pool2(strip_outline(v))) for n, v in res.items()}
    scale = 8; cols = 9
    cw = max(v.shape[1] for v in small.values()); ch = max(v.shape[0] for v in small.values())
    sheet = Image.new('RGBA', (cols*(cw+2)*scale, 3*(ch+2)*scale), (40, 44, 70, 255))
    for i, (n, v) in enumerate(small.items()):
        im = Image.fromarray(v, 'RGBA').resize((v.shape[1]*scale, v.shape[0]*scale), Image.NEAREST)
        sheet.alpha_composite(im, ((i % cols)*(cw+2)*scale, (i//cols)*(ch+2)*scale))
    sheet.save(sys.argv[1])
    print({n: v.shape[:2] for n, v in small.items()})

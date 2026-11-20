"""Crew animation frames from the portrait sprites: idle (front, blink, look left/right), signature work gesture
(4 frames, with glow points) and two walking steps. Regions are detected by colour, then each robot's gesture is
chosen from its crew sheet description."""
import colorsys, json, numpy as np
from PIL import Image

OUT = (11, 10, 22)

def hsv(px):
    r, g, b = [c / 255 for c in px[:3]]
    return colorsys.rgb_to_hsv(r, g, b)

def opaque(s):
    return s[..., 3] > 0

def is_outline(p):
    return p[3] > 0 and abs(int(p[0]) - OUT[0]) + abs(int(p[1]) - OUT[1]) + abs(int(p[2]) - OUT[2]) < 8

def regions(s, name):
    h, w = s.shape[:2]
    op = opaque(s)
    rowcount = op.sum(1)
    lo, hi = int(h * 0.36), int(h * 0.58)
    # the neck: the narrowest row between head and body (ties: the lower one)
    neck = lo + int(np.argmin(rowcount[lo:hi][::-1] * 1.0)) if name != 'core' else int(h * 0.62)
    neck = hi - 1 - int(np.argmin(rowcount[lo:hi][::-1])) if name != 'core' else int(h * 0.62)
    V = np.zeros((h, w)); S = np.zeros((h, w))
    for y in range(h):
        for x in range(w):
            if op[y, x] and not is_outline(s[y, x]):
                _, S[y, x], V[y, x] = hsv(s[y, x])
    import cv2
    nod = np.zeros((h, w), np.uint8)
    for y in range(0, neck + 1):
        for x in range(w):
            if op[y, x] and not is_outline(s[y, x]) and V[y, x] < 0.3:
                nod[y, x] = 1
    n, lab, st, _ = cv2.connectedComponentsWithStats(nod, connectivity=4)
    eyes = []
    if n > 1:
        k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        vx, vy, vw, vh = st[k, :4]
        if st[k, cv2.CC_STAT_AREA] >= 6:
            for y in range(vy, vy + vh):
                for x in range(vx, vx + vw):
                    if op[y, x] and not is_outline(s[y, x]) and S[y, x] > 0.3 and V[y, x] > 0.42:
                        eyes.append((x, y))
    cols = np.where(op.any(0))[0]
    cx0, cx1 = cols.min(), cols.max()
    width = cx1 - cx0 + 1
    mid0, mid1 = cx0 + int(width * 0.25), cx1 - int(width * 0.25)
    body1 = min(h - 1, neck + int(h * 0.38))
    emb = [(x, y) for y in range(neck + 1, body1) for x in range(mid0, mid1 + 1) if S[y, x] > 0.35 and V[y, x] > 0.32]
    if not emb:
        emb = [(x, y) for y in range(neck + 1, body1) for x in range(mid0, mid1 + 1) if S[y, x] > 0.12 and V[y, x] > 0.35]
    if not emb:
        emb = [(x, y) for y in range(neck + 1, body1) for x in range(mid0, mid1 + 1) if op[y, x] and not is_outline(s[y, x])]
    left = [(x, y) for y in range(neck + 1, min(h, body1 + 3)) for x in range(cx0, mid0) if S[y, x] > 0.3 and V[y, x] > 0.3]
    right = [(x, y) for y in range(neck + 1, min(h, body1 + 3)) for x in range(mid1 + 1, cx1 + 1) if S[y, x] > 0.3 and V[y, x] > 0.3]
    top = [(x, y) for y in range(0, max(1, neck // 2)) for x in range(w) if S[y, x] > 0.35 and V[y, x] > 0.45]
    bb = lambda pts: [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)] if pts else None
    feet = int(np.where(op.any(1))[0].max())
    return dict(neck=neck, eyes=eyes, eyes_bb=bb(eyes), emb=emb, emb_bb=bb(emb), left=left, left_bb=bb(left),
                right=right, right_bb=bb(right), top=top, top_bb=bb(top), w=w, h=h, feet=feet, cx=(cx0 + cx1) / 2)

def shift_region(s, rect, dx, dy, fill=None):
    x0, y0, x1, y1 = rect
    out = s.copy()
    part = s[y0:y1 + 1, x0:x1 + 1].copy()
    if fill is None:
        out[y0:y1 + 1, x0:x1 + 1] = 0
    else:
        out[y0:y1 + 1, x0:x1 + 1] = fill
    H, W = s.shape[:2]
    for yy in range(part.shape[0]):
        for xx in range(part.shape[1]):
            ty, tx = y0 + yy + dy, x0 + xx + dx
            if 0 <= ty < H and 0 <= tx < W and part[yy, xx, 3] > 0:
                out[ty, tx] = part[yy, xx]
    return out

def recolor(s, pts, color):
    out = s.copy()
    for x, y in pts:
        out[y, x, :3] = color
    return out

def lighten(s, pts, k):
    out = s.copy()
    for x, y in pts:
        c = out[y, x, :3].astype(float)
        out[y, x, :3] = np.clip(c + (255 - c) * k, 0, 255).astype(np.uint8)
    return out

def darken(s, pts, k):
    out = s.copy()
    for x, y in pts:
        out[y, x, :3] = (out[y, x, :3].astype(float) * (1 - k)).astype(np.uint8)
    return out

def visor_color(s, R):
    if not R['eyes']: return (16, 20, 36)
    x, y = R['eyes'][0]
    for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        p = s[y + dy, x + dx]
        if p[3] and hsv(p)[2] < 0.26: return tuple(int(c) for c in p[:3])
    return (16, 20, 36)

def look(s, R, dx):
    if not R['eyes']: return s
    vc = visor_color(s, R)
    out = s.copy()
    for x, y in R['eyes']: out[y, x, :3] = vc
    for x, y in R['eyes']:
        nx = x + dx
        if s[y, nx, 3] and hsv(s[y, nx])[2] < 0.26 or (nx, y) in R['eyes']:
            out[y, nx] = s[y, x]
        else:
            out[y, x] = s[y, x]
    return out

def blink(s, R):
    if not R['eyes']: return s
    vc = visor_color(s, R)
    out = s.copy()
    ys = sorted(set(y for _, y in R['eyes']))
    keep = ys[-1]
    for x, y in R['eyes']:
        out[y, x, :3] = vc if y != keep else (np.array(s[y, x, :3], float) * 0.55).astype(np.uint8)
    return out

def step(s, R, side):
    # lift one foot by a pixel: the lowest rows split at the centre column
    out = s.copy()
    h, w = s.shape[:2]
    feet = R['feet']; cx = int(R['cx'])
    rows = range(feet - 4, feet + 1)
    xs = range(0, cx) if side < 0 else range(cx + 1, w)
    for y in rows:
        for x in xs:
            out[y - 1, x] = s[y, x] if s[y, x, 3] else out[y - 1, x]
    for x in xs:
        if s[feet, x, 3]: out[feet, x] = 0
    return out

def ring(points, n):
    return points[n % len(points)] if points else None

def gesture(name, s, R):
    """Four work frames and their glow points [(x, y, radius, '#rrggbb')]."""
    F, G = [], []
    emb, eb = R['emb'], R['emb_bb']
    L, LB, Rt, RB = R['left'], R['left_bb'], R['right'], R['right_bb']
    eyes = R['eyes']
    def add(fr, glow=()): F.append(fr); G.append(list(glow))
    def center(bb): return ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
    if name == 'command':  # inclines its gold-crested head
        head = (0, 0, R['w'] - 1, R['neck'])
        add(s); add(shift_region(s, head, 0, 1)); add(shift_region(s, head, 1, 1)); add(shift_region(s, head, 0, 1))
    elif name == 'tracker':  # ticks its clipboard
        rows = sorted(set(y for _, y in emb))
        for k in range(4):
            fr = s
            for r in rows[: (k * len(rows)) // 3 + 1]:
                fr = recolor(fr, [p for p in emb if p[1] == r and hsv(s[r, p[0]])[0] < 0.4], (126, 255, 92))
            add(fr, [(*center(eb), 3, '#9cff5a')] if k == 3 else [])
    elif name == 'radar':  # sweeps its lime reticle
        cx, cy = center(R['eyes_bb'] or eb)
        for k in range(4):
            ang = k * np.pi / 2
            pts = [(int(round(cx + np.cos(ang) * r)), int(round(cy + np.sin(ang) * r))) for r in (1, 2, 3)]
            pts = [p for p in pts if s[p[1], p[0], 3]]
            add(recolor(s, pts, (196, 255, 70)), [(cx, cy, 4, '#b8ff4a')])
    elif name == 'gavel':  # flashes its amber visor when a decision lands
        add(s); add(recolor(lighten(s, eyes, 0.3), eyes, (255, 196, 64)), [(*center(R['eyes_bb']), 6, '#ffb52e')])
        add(recolor(s, eyes, (255, 226, 140)), [(*center(R['eyes_bb']), 8, '#ffc84a')]); add(s)
    elif name == 'clock':  # advances its dial
        bb = eb; cx, cy = center(bb); r = max(1, min(bb[2] - bb[0], bb[3] - bb[1]) // 2 - 1)
        for k in range(4):
            ang = -np.pi / 2 + k * np.pi / 2
            pts = [(int(round(cx + np.cos(ang) * t)), int(round(cy + np.sin(ang) * t))) for t in range(0, r + 1)]
            add(recolor(s, pts, (255, 236, 170)), [(cx, cy, 3, '#ffab45')] if k % 2 else [])
    elif name == 'pulse':  # steps its blue meter
        bb = LB or eb; cols = list(range(bb[0], bb[2] + 1))
        for k in range(4):
            pts = [(x, y) for x, y in (L or emb) if y >= bb[3] - (k + 1) * max(1, (bb[3] - bb[1] + 1) // 4) + 1]
            add(recolor(s, pts, (120, 200, 255)), [(*center(bb), 3, '#5aa8ff')])
    elif name == 'vector':  # lights a branching path
        rows = sorted(set(y for _, y in emb), reverse=True)
        for k in range(4):
            lit = [p for p in emb if p[1] in rows[: max(1, (k + 1) * len(rows) // 4)]]
            add(recolor(s, lit, (150, 230, 255)), [(*center(eb), 3, '#7fd8ff')] if k == 3 else [])
    elif name == 'archive':  # slots a cartridge
        bb = RB or LB
        add(s); add(shift_region(s, bb, -1, 0)); add(shift_region(s, bb, -2, 0), [(bb[0] - 2, center(bb)[1], 2, '#ff9a3c')]); add(shift_region(s, bb, -1, 0))
    elif name == 'spark':  # warms its golden lens
        pts = eyes or emb
        for k, t in enumerate((0.0, 0.25, 0.55, 0.25)):
            add(lighten(s, pts, t), [(*center(R['eyes_bb'] or eb), 3 + 2 * k % 5, '#ffd84a')] if k else [])
    elif name == 'boost':  # lights its teal cells in sequence
        x0, x1 = eb[0], eb[2]; seg = max(1, (x1 - x0 + 1) // 3)
        for k in range(4):
            fr = darken(s, emb, 0.45)
            if k < 3:
                fr = recolor(fr, [p for p in emb if x0 + k * seg <= p[0] < x0 + (k + 1) * seg + (1 if k == 2 else 0)], (120, 255, 236))
                add(fr, [(x0 + k * seg + seg / 2, center(eb)[1], 2, '#3fffe0')])
            else:
                add(recolor(s, emb, (120, 255, 236)), [(*center(eb), 4, '#3fffe0')])
    elif name == 'frame':  # focuses its camera lens
        cx, cy = center(eb)
        core = [p for p in emb if abs(p[0] - cx) <= 1 and abs(p[1] - cy) <= 1]
        for k in range(4):
            add(recolor(s, core, (255, 120, 220) if k % 2 else (255, 220, 245)), [(cx, cy, 2 + k, '#ff3dad')])
    elif name == 'story':  # flips a storyboard panel
        x0, y0, x1, y1 = eb
        flipped = s.copy(); flipped[y0:y1 + 1, x0:x1 + 1] = s[y0:y1 + 1, x0:x1 + 1][:, ::-1]
        mid = s.copy(); mid[y0:y1 + 1, x0:x1 + 1] = s[y0:y1 + 1, x0:x1 + 1]
        add(s); add(lighten(s, emb, 0.35)); add(flipped); add(lighten(flipped, emb, 0.2))
    elif name == 'splice':  # brings two clip tiles together
        bb = LB or RB
        add(s); add(shift_region(s, bb, 1, 0)); add(shift_region(s, bb, 2, 0), [(bb[2] + 2, center(bb)[1], 3, '#ff4fc0')]); add(shift_region(s, bb, 1, 0))
    elif name == 'script':  # traces a waveform
        x0, x1 = eb[0], eb[2]
        for k in range(4):
            col = x0 + (k * (x1 - x0)) // 3
            add(recolor(s, [p for p in emb if abs(p[0] - col) <= 0], (240, 220, 255)), [(col, center(eb)[1], 2, '#b48cff')])
    elif name == 'glyph':  # highlights a caption line
        rows = sorted(set(y for _, y in emb))
        groups = [rows[: len(rows) // 2], rows[len(rows) // 2:]] if len(rows) > 1 else [rows, rows]
        for k in range(4):
            g = groups[k % 2]
            add(recolor(s, [p for p in emb if p[1] in g], (232, 214, 255)), [(center(eb)[0], np.mean(g), 3, '#a77bff')])
    elif name == 'curator':  # files an item into its chest tray
        cx = int(center(eb)[0]); y_end = eb[1]
        for k in range(4):
            y = y_end - 3 + k
            fr = s.copy()
            if k < 3 and 0 <= y < s.shape[0]:
                fr[y, cx] = (255, 236, 170, 255); fr[y, cx + 1] = (255, 236, 170, 255)
                add(fr)
            else:
                add(lighten(s, emb, 0.35), [(*center(eb), 3, '#c4a8ff')])
    elif name == 'metric':  # tilts its chart tablet
        bb = LB or RB
        add(s); add(shift_region(s, bb, 0, -1)); add(lighten(shift_region(s, bb, 1, -1), L or Rt, 0.3), [(*center(bb), 3, '#3fe0f0')]); add(shift_region(s, bb, 0, -1))
    elif name == 'synapse':  # passes a light between linked nodes
        pts = sorted(emb, key=lambda p: (p[0], p[1]))
        bright = [p for p in emb if hsv(s[p[1], p[0]])[2] > 0.75] or pts
        bright.sort(key=lambda p: p[0])
        chunks = [bright[i::3] for i in range(3)]
        for k in range(4):
            c = chunks[k % 3]
            add(recolor(s, c, (250, 236, 255)), [(np.mean([p[0] for p in c]), np.mean([p[1] for p in c]), 2, '#d3a8ff')] if c else [])
    elif name == 'switch':  # flips a chest lever: each lever lights in turn, then all settle
        x0, x1 = eb[0], eb[2]; seg = max(1, (x1 - x0 + 1) // 3)
        for k in range(4):
            if k < 3:
                lv = [p for p in emb if x0 + k * seg <= p[0] < x0 + (k + 1) * seg]
                add(lighten(s, lv, 0.55), [(x0 + k * seg + seg / 2, center(eb)[1], 3, '#ffc23d')])
            else:
                add(lighten(s, emb, 0.25), [(*center(eb), 4, '#ffc23d')])
    elif name == 'check':  # raises its green check display
        bb = RB or LB
        add(s); add(shift_region(s, bb, 0, -1)); add(lighten(shift_region(s, bb, 0, -2), [(x, y - 2) for x, y in (Rt or L)], 0.35), [(*center(bb), 4, '#57eea0')]); add(shift_region(s, bb, 0, -1))
    elif name == 'patch':  # unfolds its articulated arm (the claw arm on its right side)
        bb = (int(R['w'] * 0.68), 3, R['w'] - 1, R['neck'] + 6)
        add(s); add(shift_region(s, bb, 0, -1)); add(shift_region(s, bb, 1, -2), [(bb[2], bb[1], 2.5, '#ff8a2a')]); add(shift_region(s, bb, 0, -1))
    elif name == 'harbor':  # scans its manifest
        bb = LB or RB
        for k in range(4):
            y = bb[1] + (k * (bb[3] - bb[1])) // 3
            add(recolor(s, [(x, y) for x in range(bb[0], bb[2] + 1) if s[y, x, 3] and not is_outline(s[y, x])], (180, 255, 210)), [(center(bb)[0], y, 2, '#57eea0')])
    elif name == 'quill':  # writes a short pen stroke
        bb = RB or eb
        for k in range(4):
            fr = shift_region(s, bb, [0, 1, 2, 1][k], [0, 0, 1, 0][k])
            add(fr, [(bb[0] + [0, 1, 2, 1][k], bb[3], 1.5, '#ff7fae')] if k == 2 else [])
    elif name == 'lock':  # brings its shield forward
        add(s); add(lighten(s, emb, 0.2)); add(lighten(s, emb, 0.45), [(*center(eb), 5, '#9fc6ff')]); add(lighten(s, emb, 0.2))
    elif name == 'dock':  # acknowledges with its amber beacon
        tb = R['top_bb'] or R['eyes_bb']
        add(s); add(recolor(s, R['top'], (255, 200, 90)), [(*center(tb), 5, '#ffab3d')]); add(s); add(recolor(s, R['top'], (255, 230, 150)), [(*center(tb), 7, '#ffc65a')])
    elif name == 'core':
        for k in range(4): add(lighten(s, [(x, y) for y in range(s.shape[0]) for x in range(s.shape[1]) if s[y, x, 3] and hsv(s[y, x])[0] > 0.7], 0.08 * (k % 2)))
    else:
        for k in range(4): add(s)
    return F, G

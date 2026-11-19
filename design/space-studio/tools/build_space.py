"""Builds the space studio assets for frontend/public/space/ from the cleaned art in out/.
Run from the art folder: python3 tools/build_space.py"""
import colorsys, json, os, shutil, sys
import numpy as np, cv2
from PIL import Image
sys.path.insert(0, 'tools')
from frames import regions, gesture, look, blink, step, lighten
from extract import run

OUT = 'out/space'
CREW = ['command', 'tracker', 'radar', 'gavel', 'clock', 'pulse', 'vector', 'archive', 'spark', 'boost', 'frame', 'story',
        'splice', 'script', 'glyph', 'curator', 'metric', 'synapse', 'switch', 'check', 'patch', 'harbor', 'quill', 'lock', 'dock']
FRAMES = ['idle', 'blink', 'look_left', 'look_right', 'walk_left_a', 'walk_left_b', 'walk_right_a', 'walk_right_b',
          'work_0', 'work_1', 'work_2', 'work_3']
CW, CH = 48, 44

def r1(v): return round(float(v), 1)

def crew_atlas():
    z = np.load('out/crew_arrays.npz')
    atlas = np.zeros((CH * len(CREW), CW * len(FRAMES), 4), np.uint8)
    meta = {}
    for row, n in enumerate(CREW):
        s = z['big_' + n]
        R = regions(s, n)
        work, glows = gesture(n, s, R)
        frames = [s, blink(s, R), look(s, R, -1), look(s, R, 1),
                  look(step(s, R, -1), R, -1), look(step(s, R, 1), R, -1),
                  look(step(s, R, -1), R, 1), look(step(s, R, 1), R, 1)] + work
        h, w = s.shape[:2]
        assert w <= CW and h <= CH, (n, w, h)
        for col, f in enumerate(frames):
            atlas[row * CH:row * CH + h, col * CW:col * CW + w] = f
        op = s[..., 3] > 0
        xs = np.where(op.any(0))[0]
        meta[n] = {'row': row, 'w': int(w), 'h': int(h), 'foot': int(np.where(op.any(1))[0].max()),
                   'cx': r1((xs.min() + xs.max() + 1) / 2),
                   'glows': [[[r1(g[0]), r1(g[1]), r1(g[2]), g[3]] for g in gl] for gl in glows]}
    Image.fromarray(atlas, 'RGBA').save(f'{OUT}/crew.png', optimize=True)
    return {'cell': [CW, CH], 'frames': FRAMES, 'robots': meta}

def core_sprite():
    big = run(84, 18, ['core'])['core']
    h, w = big.shape[:2]
    op = big[..., 3] > 0
    # the brain is the top block; the base is the bottom block. Find the widest violet rows to split.
    Image.fromarray(big, 'RGBA').save(f'{OUT}/core.png', optimize=True)
    return {'w': int(w), 'h': int(h)}

ACCENTS = {'intake': (156, 230, 70), 'research': (60, 214, 230), 'story': (90, 150, 255), 'editing': (255, 80, 196),
           'sound': (178, 120, 255), 'quality': (255, 176, 60), 'publishing': (255, 150, 60), 'brain': (190, 110, 255)}
CONSOLE_FRAMES = ['off', 'idle', 'work_0', 'work_1', 'work_2', 'work_3']

def console_sheet():
    W, H = 16, 22
    OUTL = (11, 10, 22, 255); BEZ = (58, 66, 88, 255); BEZ_HI = (92, 102, 128, 255); BEZ_LO = (38, 44, 62, 255)
    SCR_OFF = (16, 22, 42, 255); STAND = (46, 52, 72, 255); BASE = (70, 78, 102, 255)
    sheet = np.zeros((H * len(ACCENTS), W * len(CONSOLE_FRAMES), 4), np.uint8)
    for r, (room, acc) in enumerate(ACCENTS.items()):
        for c, fr in enumerate(CONSOLE_FRAMES):
            im = np.zeros((H, W, 4), np.uint8)
            # monitor 16x12 (rows 0-11): outline, bezel, screen 12x7 at (2,2)
            im[0:12, 0:16] = OUTL
            im[1:11, 1:15] = BEZ
            im[1, 1:15] = BEZ_HI
            im[10, 1:15] = BEZ_LO
            sc = np.zeros((7, 12, 4), np.uint8); sc[:] = SCR_OFF
            if fr == 'off':
                sc[1, 1] = (34, 44, 70, 255); sc[2, 2] = (28, 36, 60, 255)
            elif fr == 'idle':
                dim = tuple(int(v * 0.35 + 16 * 0.65) for v in acc) + (255,)
                sc[:] = (20, 28, 50, 255)
                sc[5, 1:4] = dim; sc[3, 9] = tuple(int(v * 0.7) for v in acc) + (255,)
            else:
                k = int(fr[-1])
                base = tuple(int(v * 0.30 + 18 * 0.7) for v in acc) + (255,)
                sc[:] = base
                lit = tuple(min(255, int(v * 1.0)) for v in acc) + (255,)
                hi = tuple(min(255, int(v + (255 - v) * 0.55)) for v in acc) + (255,)
                for line in range(3):
                    y = 1 + line * 2
                    ln = [7, 9, 5, 8][(line + k) % 4]
                    sc[y, 1:1 + ln] = lit
                sc[1 + ((k + 1) % 3) * 2, 1 + [6, 8, 4, 7][k]] = hi
                sc[6, 11 - k] = hi
            im[2:9, 2:14] = sc
            # stand and base
            im[12:18, 6:10] = OUTL; im[12:17, 7:9] = STAND
            im[17:22, 2:14] = OUTL; im[18:21, 3:13] = BASE; im[18, 3:13] = BEZ_HI
            if fr != 'off':
                im[19, 11] = (120, 255, 150, 255) if fr != 'idle' else (90, 120, 110, 255)
            sheet[r * H:(r + 1) * H, c * W:(c + 1) * W] = im
    Image.fromarray(sheet, 'RGBA').save(f'{OUT}/consoles.png', optimize=True)
    return {'cell': [W, H], 'frames': CONSOLE_FRAMES, 'rows': list(ACCENTS)}

def exhaust_sheet():
    # 6 frames of a cyan engine flame pointing left, 72x28 world px, drawn additively
    W, H = 150, 48
    frames = []
    rng = np.random.default_rng(3)
    for k in range(6):
        im = np.zeros((H, W, 4), np.float32)
        L = 104 + [0, 10, 20, 14, 5, 17][k]
        cy = H / 2 - 0.5
        for x in range(W):
            d = (W - 1 - x)  # distance from the nozzle (nozzle at the right edge)
            if d > L: continue
            t = d / L
            half = (17 * (1 - t ** 1.5)) + 0.8
            wob = np.sin(k * 1.7 + d * 0.18) * 1.2 * t
            for y in range(H):
                dy = abs(y - cy - wob)
                if dy > half: continue
                e = dy / max(half, 0.1)
                core = (1 - t) ** 0.8 * (1 - e ** 2)
                glow = (1 - t) ** 1.4 * (1 - e)
                r = 40 + 215 * core ** 1.6
                g = 150 + 105 * core
                b = 255
                a = min(1.0, glow * 1.25)
                im[y, x] = (r, g, b, a * 255)
        # quantize to pixel art steps
        im[..., 3] = np.round(im[..., 3] / 51) * 51
        frames.append(im.clip(0, 255).astype(np.uint8))
    sheet = np.concatenate(frames, axis=0)
    Image.fromarray(sheet, 'RGBA').save(f'{OUT}/exhaust.png', optimize=True)
    return {'cell': [W, H], 'count': 6}

def lights_layer():
    hull = np.array(Image.open('out/ship_clean.png').convert('RGBA'))
    rgb = hull[..., :3].astype(np.float32) / 255
    hsv = cv2.cvtColor((rgb * 255).astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    S, V = hsv[..., 1] / 255, hsv[..., 2] / 255
    em = (hull[..., 3] > 0) & (((S > 0.42) & (V > 0.62)) | (V > 0.93))
    out = np.zeros_like(hull)
    out[em] = hull[em]
    Image.fromarray(out, 'RGBA').save(f'{OUT}/ship-lights.png', optimize=True)
    return int(em.sum())

def engines():
    hull = np.array(Image.open('out/ship_clean.png').convert('RGBA'))
    a = hull[..., 3] > 0
    res = []
    for y in range(hull.shape[0]):
        xs = np.where(a[y])[0]
        res.append(xs.min() if len(xs) else 9999)
    return res

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    meta = {'crew': crew_atlas(), 'core': core_sprite(), 'consoles': console_sheet(), 'exhaust': exhaust_sheet()}
    print('lights', lights_layer())
    left = engines()
    print('leftmost hull x for rows 90..270:', [(y, left[y]) for y in range(90, 280, 6)])
    shutil.copy('out/ship_clean.png', f'{OUT}/ship.png')
    # the black hole is painted in code (frontend/src/components/blackHoleArt.ts); stars.py makes the star tiles
    for f in ['sky.jpg', 'stars-near.png', 'stars-far.png', 'satellite.png', 'orbit.png', 'dock_scene.png']:
        shutil.copy(f'out/{f}', f'{OUT}/{f.replace("_", "-")}')
    json.dump(meta, open(f'{OUT}/sprites.json', 'w'), separators=(',', ':'))
    for f in sorted(os.listdir(OUT)):
        print(f, os.path.getsize(f'{OUT}/{f}'))

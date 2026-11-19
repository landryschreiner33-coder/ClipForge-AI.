import json, sys, numpy as np
from PIL import Image, ImageDraw, ImageFilter
W = json.load(open('/home/claude/ClipForge-AI./frontend/src/space/ship-world.json'))
S = json.load(open('out/space/sprites.json'))
crew = Image.open('out/space/crew.png'); cons = Image.open('out/space/consoles.png'); exh = Image.open('out/space/exhaust.png')
core = Image.open('out/space/core.png'); ship = Image.open('out/space/ship.png'); lights = Image.open('out/space/ship-lights.png')
sky = Image.open('out/space/sky.jpg').convert('RGBA')
ROOM_OF = {'command': 'control', 'tracker': 'intake', 'radar': 'intake', 'gavel': 'intake', 'clock': 'research', 'pulse': 'research',
           'archive': 'story', 'spark': 'story', 'boost': 'story', 'vector': 'story', 'frame': 'editing', 'story': 'editing', 'splice': 'editing',
           'glyph': 'sound', 'script': 'sound', 'switch': 'quality', 'check': 'quality', 'patch': 'quality', 'quill': 'publishing',
           'lock': 'publishing', 'harbor': 'publishing', 'dock': 'publishing', 'metric': 'brain', 'synapse': 'brain', 'curator': 'brain'}
working = set(sys.argv[1].split(',')) if len(sys.argv) > 1 and sys.argv[1] else set()
at_station = set(sys.argv[2].split(',')) if len(sys.argv) > 2 and sys.argv[2] else set(ROOM_OF)
frame_k = int(sys.argv[3]) if len(sys.argv) > 3 else 1
out = sys.argv[4] if len(sys.argv) > 4 else 'out/preview.png'
WW, WH = W['world']['w'], W['world']['h']
VX = W['view']['x']; VW = W['view']['w']
img = sky.resize((2400, 1500)).crop((300, 300, 300 + VW, 300 + WH))
img.alpha_composite(ship.resize((WW, WH), Image.NEAREST), (-VX, 0))
glow = Image.new('RGBA', (VW, WH), (0, 0, 0, 0))
L2 = lights.resize((WW, WH), Image.NEAREST)
busy_rooms = {ROOM_OF[r] for r in working}
for rid, r in W['rooms'].items():
    if rid in busy_rooms:
        box = (r['x'], r['y'], r['x'] + r['w'], r['y'] + r['h'])
        glow.alpha_composite(L2.crop(box), (box[0] - VX, box[1]))
def add(base, layer, alpha=1.0):
    a = np.array(base).astype(np.float32); b = np.array(layer).astype(np.float32)
    ba = b[..., 3:4] / 255 * alpha
    a[..., :3] = np.clip(a[..., :3] + b[..., :3] * ba, 0, 255)
    return Image.fromarray(a.astype(np.uint8), 'RGBA')
img = add(img, glow, 0.55)
# exhaust
ew, eh = S['exhaust']['cell']
for i, (x, y) in enumerate(W['engines']):
    fr = exh.crop((0, eh * ((frame_k + i * 2) % 6), ew, eh * ((frame_k + i * 2) % 6 + 1)))
    lay = Image.new('RGBA', (VW, WH)); lay.alpha_composite(fr, (x - ew - VX, y - eh // 2))
    img = add(img, lay, 1.0)
# core
cx, cy = W['core']['x'], W['core']['y']
img.alpha_composite(core, (cx - core.width // 2 - VX, cy - core.height // 2))
CW, CH = S['crew']['cell']; KW, KH = S['consoles']['cell']; rows = S['consoles']['rows']
items = []
for rid, st in W['stations'].items():
    room = ROOM_OF[rid]
    if st['console']:
        fx, fy = st['console']
        col = (2 + frame_k % 4) if rid in working else (1 if rid in at_station else 0)
        spr = cons.crop((col * KW, rows.index(room) * KH, (col + 1) * KW, (rows.index(room) + 1) * KH))
        items.append((fy, fx - KW // 2, fy - KH + 1, spr))
spots = iter(W['lounge'])
for rid, m in S['crew']['robots'].items():
    if rid in at_station:
        st = W['stations'][rid]; fx, fy = st['x'], st['y']
    else:
        sp = next(spots); fx, fy = sp['x'], sp['y']
    col = (8 + frame_k % 4) if rid in working else 0
    spr = crew.crop((col * CW, m['row'] * CH, col * CW + m['w'], m['row'] * CH + m['h']))
    items.append((fy + 0.5, int(fx - m['cx']), int(fy - m['foot']), spr))
items.sort(key=lambda t: t[0])
for _, x, y, spr in items:
    img.alpha_composite(spr, (x - VX, y))
img.convert('RGB').save(out)
img.resize((1000, round(1000 * WH / VW)), Image.LANCZOS).convert('RGB').save(out.replace('.png', '_1000.png'))
print('ok')

"""Crew sprites: portraits (40 px + outline) and in-ship sprites (2x2 saliency pooled + outline)."""
import sys, json, numpy as np
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from extract import run, outline
from pool import pool2, strip_outline
from PIL import Image, ImageDraw

def build():
    big = run(40, 14)
    small = {n: outline(pool2(strip_outline(v))) for n, v in big.items()}
    return big, small

def annotated(sprites, scale, path, cols=7):
    names = list(sprites)
    cw = max(v.shape[1] for v in sprites.values()); ch = max(v.shape[0] for v in sprites.values())
    tw, th = (cw + 2) * scale, (ch + 3) * scale
    sheet = Image.new('RGBA', (cols * tw, ((len(names) + cols - 1) // cols) * th), (34, 38, 60, 255))
    d = ImageDraw.Draw(sheet)
    for i, n in enumerate(names):
        v = sprites[n]
        ox, oy = (i % cols) * tw, (i // cols) * th + scale
        im = Image.fromarray(v, 'RGBA').resize((v.shape[1] * scale, v.shape[0] * scale), Image.NEAREST)
        sheet.alpha_composite(im, (ox, oy))
        for x in range(v.shape[1] + 1):
            d.line([(ox + x * scale, oy), (ox + x * scale, oy + v.shape[0] * scale)], fill=(255, 255, 255, 40 if x % 5 else 110))
        for y in range(v.shape[0] + 1):
            d.line([(ox, oy + y * scale), (ox + v.shape[1] * scale, oy + y * scale)], fill=(255, 255, 255, 40 if y % 5 else 110))
        d.text((ox + 2, oy - scale + 1), f'{n} {v.shape[1]}x{v.shape[0]}', fill=(255, 255, 0, 255))
    sheet.save(path)

if __name__ == '__main__':
    big, small = build()
    np.savez_compressed('out/crew_arrays.npz', **{f'big_{k}': v for k, v in big.items()}, **{f'small_{k}': v for k, v in small.items()})
    annotated({k: v for k, v in list(small.items())[:13]}, 12, 'out/small_grid_a.png')
    annotated({k: v for k, v in list(small.items())[13:]}, 12, 'out/small_grid_b.png')

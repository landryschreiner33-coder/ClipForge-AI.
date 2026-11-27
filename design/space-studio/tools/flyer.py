"""Cuts Landry's little ship (the one flying in front of the Studio's black hole) out of its picture and writes the two
copies the app draws: frontend/public/space/flyer-384.png and flyer-192.png (half size, for small or 1x screens).

The picture (2026-11-27, 2172 × 724) came with a see-through background, but the ship itself was only partly solid
(about 75-99 %) and faint specks were scattered round it. This keeps the one solid shape, fills it in completely,
keeps its edge soft for a pixel or two, crops it, and scales it down on premultiplied colour (no light or dark fringe).

    python3 design/space-studio/tools/flyer.py <the picture> [frontend/public/space]

The engines start at 22 % of the width from the left (FLAME in frontend/src/components/shipArt.ts): everything left
of that is the exhaust flame, which the app stretches and flickers on its own.
"""
import sys

import cv2
import numpy as np
from PIL import Image


def cut_out(path: str) -> Image.Image:
    src = np.array(Image.open(path).convert("RGBA")).astype(np.float32)
    a = src[..., 3]
    solid = (a > 128).astype(np.uint8)
    # the ship is the biggest solid piece; anything else is a speck
    n, labels, stats, _ = cv2.connectedComponentsWithStats(solid, 8)
    ship = (labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    # fill any hole inside it: everything the outside cannot reach is ship
    _, outside = cv2.connectedComponents(1 - ship, connectivity=4)
    ship = (outside != outside[0, 0]).astype(np.uint8)
    # fully solid inside, a soft edge of a pixel or two from the picture's own edge, nothing further out
    near = cv2.dilate(ship, np.ones((5, 5), np.uint8))
    alpha = np.clip((a - 40) / 110, 0, 1) * near
    alpha[(ship == 1) & (a > 150)] = 1
    alpha[cv2.erode(ship, np.ones((5, 5), np.uint8)) == 1] = 1
    out = src.copy()
    out[..., 3] = alpha * 255
    ys, xs = np.where(alpha > 0)
    pad = 4
    crop = out[max(0, ys.min() - pad):ys.max() + pad + 1, max(0, xs.min() - pad):xs.max() + pad + 1]
    return Image.fromarray(np.clip(crop, 0, 255).astype(np.uint8), "RGBA")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    folder = sys.argv[2] if len(sys.argv) > 2 else "frontend/public/space"
    ship = cut_out(sys.argv[1])
    for w in (384, 192):
        h = round(ship.height * w / ship.width)
        small = ship.convert("RGBa").resize((w, h), Image.LANCZOS).convert("RGBA")
        small.save(f"{folder}/flyer-{w}.png", optimize=True)
        print(f"{folder}/flyer-{w}.png", small.size)


if __name__ == "__main__":
    main()

"""Make every ClipForge app icon from the one approved picture (design/brand/clipforge-icon-gold-source.png).

The owner approved the gold command robot on 2026-11-25. This script is the only way the icon files are made, so the
app, the website, the browser tab, the TikTok form, the Mac app and the Windows shortcut always show the same robot:

    python scripts/make_icons.py            # write every file below
    python scripts/make_icons.py --check    # exit 1 when a committed file differs from what the script makes

Files it writes (all from the same source, with Pillow only, so it runs the same on Linux, Mac and Windows):
  design/tiktok/app-icon-dark.png, app-icon-light.png   1024 x 1024 PNG (TikTok Basic information, served in-app)
  frontend/public/app-icon.png, docs/legal/app-icon.png  the same bytes (app, website and tab icon)
  frontend/public/app-icon-128.png                       the sidebar logo, pre-scaled so it is not drawn pixelated
  frontend/public/favicon.ico, docs/legal/favicon.ico    Windows and browser icon, 16 to 256 px
  macos/desktop/AppIcon.iconset/*.png                    the ten Mac sizes, on Apple's icon grid
  design/brand/icon-small-sizes.png                      a sheet of the small sizes on dark and light, for review

Small sizes: at 16-24 px the robot's eyes vanish when the whole tile is shrunk, so those sizes use a closer crop
of the same art (more robot, less black frame). Nothing is redrawn by hand.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "design/brand/clipforge-icon-gold-source.png"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SMALL = 32          # at this size and below, use the close crop
MAC_BODY = 824      # Apple's macOS icon grid: an 824 px body centred on a 1024 px canvas
MAC_SIZES = (16, 32, 128, 256, 512)


def _source() -> Image.Image:
    im = Image.open(SOURCE).convert("RGBA")
    box = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if not box:
        raise SystemExit(f"{SOURCE} is empty")
    return im.crop(box)  # the rounded tile without the transparent margin around it


def _square(im: Image.Image) -> Image.Image:
    side = max(im.size)
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    return out


def _rounded(size: int, radius: float) -> Image.Image:
    scale = 4  # draw large, then shrink, for a smooth edge
    mask = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size * scale - 1, size * scale - 1), radius=radius * scale,
                                           fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def tile(size: int) -> Image.Image:
    """The approved tile at `size`, filling the canvas."""
    return _square(_source()).resize((size, size), Image.LANCZOS)


def small(size: int) -> Image.Image:
    """A close crop for tiny sizes: the robot fills most of the tile so the visor and eyes stay readable."""
    src = _source()
    rgb = src.convert("RGB")
    gold = rgb.point(lambda v: 255 if v > 120 else 0).convert("L").getbbox()  # the bright robot
    if not gold:
        return tile(size)
    x0, y0, x1, y1 = gold
    pad = int(0.07 * max(x1 - x0, y1 - y0))
    side = max(x1 - x0, y1 - y0) + 2 * pad
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    crop = src.crop((cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side))
    crop = Image.alpha_composite(Image.new("RGBA", crop.size, (12, 11, 13, 255)), crop)
    out = crop.resize((size, size), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=0.6, percent=60))
    out.putalpha(_rounded(size, size * 0.2))
    return out


def for_size(size: int) -> Image.Image:
    return small(size) if size <= SMALL else tile(size)


def mac_icon(size: int) -> Image.Image:
    """One Mac size: the tile on Apple's grid (body 824/1024), so the Dock shows it as big as other apps."""
    body = max(1, round(size * MAC_BODY / 1024))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    art = for_size(body)
    canvas.paste(art, ((size - body) // 2, (size - body) // 2), art)
    return canvas


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _ico() -> bytes:
    """A Windows .ico with every size made separately (Pillow would otherwise shrink one picture for all)."""
    images = [for_size(s) for s in ICO_SIZES]
    buf = io.BytesIO()
    images[-1].save(buf, "ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    return buf.getvalue()


def _sheet() -> bytes:
    sizes = (16, 20, 24, 32, 48, 64)
    width = sum(sizes) + 12 * (len(sizes) + 1)
    sheet = Image.new("RGBA", (width * 2, 64 + 24), (0, 0, 0, 0))
    for half, bg in enumerate(((30, 30, 34, 255), (236, 236, 240, 255))):
        sheet.paste(Image.new("RGBA", (width, 88), bg), (half * width, 0))
        x = half * width + 12
        for s in sizes:
            im = for_size(s)
            sheet.paste(im, (x, 12 + (64 - s)), im)
            x += s + 12
    return _png(sheet)


def outputs() -> dict[Path, bytes]:
    big = _png(tile(1024))
    ico = _ico()
    files = {
        ROOT / "design/tiktok/app-icon-dark.png": big,
        ROOT / "design/tiktok/app-icon-light.png": big,
        ROOT / "frontend/public/app-icon.png": big,
        ROOT / "docs/legal/app-icon.png": big,
        ROOT / "frontend/public/app-icon-128.png": _png(tile(128)),
        ROOT / "frontend/public/favicon.ico": ico,
        ROOT / "docs/legal/favicon.ico": ico,
        ROOT / "design/brand/icon-small-sizes.png": _sheet(),
    }
    iconset = ROOT / "macos/desktop/AppIcon.iconset"
    for size in MAC_SIZES:
        files[iconset / f"icon_{size}x{size}.png"] = _png(mac_icon(size))
        files[iconset / f"icon_{size}x{size}@2x.png"] = _png(mac_icon(size * 2))
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="only compare; exit 1 on a difference")
    args = parser.parse_args(argv)
    stale = []
    for path, data in outputs().items():
        if path.exists() and path.read_bytes() == data:
            continue
        if args.check:
            stale.append(path.relative_to(ROOT).as_posix())
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print("wrote", path.relative_to(ROOT).as_posix())
    if stale:
        print("Out of date (run python scripts/make_icons.py):", *stale, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

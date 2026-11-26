"""The animated-short looks and the caption preview use the owner's pictures (made with ChatGPT, 2026-11-26) instead
of shapes drawn in code; a drawing still shows if a picture can't load."""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

from clipfoundry.makers import looks

FRONT = Path(__file__).resolve().parents[1] / "frontend"


def test_every_look_has_its_picture_at_9_by_16():
    src = (FRONT / "src" / "components" / "lookArt.tsx").read_text(encoding="utf-8")
    listed = dict(re.findall(r'(\w+): "(/looks/\w+\.jpg)"', src))
    assert set(listed) == {look.id for look in looks.LOOKS}
    for look_id, url in listed.items():
        with Image.open(FRONT / "public" / url.lstrip("/")) as im:
            assert im.format == "JPEG" and im.size == (720, 1280), look_id


def test_a_picture_that_cannot_load_falls_back_to_the_drawing():
    src = (FRONT / "src" / "components" / "lookArt.tsx").read_text(encoding="utf-8")
    assert "onError={() => setBroken(true)}" in src
    assert "if (picture && !broken)" in src and "const Art = ART[look];" in src
    # the picture maker's own example still wins over the bundled picture
    assert src.index("if (made)") < src.index("if (picture && !broken)")
    page = (FRONT / "src" / "pages" / "MakeShort.tsx").read_text(encoding="utf-8")
    assert "Drawn by ClipForge" not in page


def test_the_caption_preview_has_a_tall_and_a_wide_picture():
    src = (FRONT / "src" / "components" / "StyleStudio.tsx").read_text(encoding="utf-8")
    assert 'tall: "/brain/style-preview-tall.jpg", wide: "/brain/style-preview-wide.jpg"' in src
    assert 'SCENE_PICTURE[clip ? "tall" : "wide"]' in src
    for name, size in (("style-preview-tall.jpg", (720, 1280)), ("style-preview-wide.jpg", (1280, 720))):
        with Image.open(FRONT / "public" / "brain" / name) as im:
            assert im.format == "JPEG" and im.size == size, name

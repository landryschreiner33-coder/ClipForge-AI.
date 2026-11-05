"""ClipForge is dark only, and every palette and accent offered in Customize studio stays readable (handoff section 3).

The colours are read from frontend/src/theme.css itself, so a new palette or accent cannot be added without passing
these checks: WCAG 2.1 contrast of 4.5:1 for text (accent links, status words, secondary text) and 3:1 for focus
rings and control borders, on each palette's surfaces.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "theme.css").read_text(encoding="utf-8")


def _tokens(block: str) -> dict[str, str]:
    return {k: v.upper() for k, v in re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", block)}


def _rule(selector: str) -> dict[str, str]:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, selector
    return _tokens(m.group(1))


BASE = _rule(':root, :root[data-palette="studio"]')
PALETTES = {"studio": BASE, **{name: {**BASE, **_rule(f':root[data-palette="{name}"]')}
                               for name in re.findall(r':root\[data-palette="(\w+)"\]', CSS) if name != "studio"}}
ACCENTS = {name: _rule(sel) for sel, name in
           [(m.group(0), m.group(1)) for m in re.finditer(r':root(?:, :root)?\[data-accent="(\w+)"\]', CSS)]}


def _lum(hex_: str) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_there_is_no_light_theme_left():
    assert "data-theme" not in CSS and "light" not in re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL).lower()
    assert set(PALETTES) == {"studio", "midnight", "graphite", "plum"}
    assert set(ACCENTS) == {"violet", "teal", "blue", "coral", "green", "pink"}
    for p in PALETTES.values():  # every palette is dark: the canvas is darker than the text by far
        assert _lum(p["canvas"]) < 0.02 and _lum(p["surface"]) < 0.03


@pytest.mark.parametrize("palette", ["studio", "midnight", "graphite", "plum"])
def test_text_status_focus_and_controls_are_readable_on_every_palette(palette):
    p = PALETTES[palette]
    for bg in ("canvas", "surface", "raised", "hover"):
        for fg in ("text", "text-2", "text-3"):
            assert ratio(p[fg], p[bg]) >= 4.5, (palette, fg, bg, round(ratio(p[fg], p[bg]), 2))
    for bg in ("canvas", "surface", "raised"):
        for fg in ("good", "warn", "bad", "info"):
            assert ratio(p[fg], p[bg]) >= 4.5, (palette, fg, bg)
        assert ratio(p["focus"], p[bg]) >= 3 and ratio(p["control-border"], p[bg]) >= 3, (palette, bg)


@pytest.mark.parametrize("accent", ["violet", "teal", "blue", "coral", "green", "pink"])
def test_every_accent_is_readable_on_every_palette_and_under_button_text(accent):
    a = ACCENTS[accent]
    for name, p in PALETTES.items():
        for bg in ("canvas", "surface", "raised"):
            assert ratio(a["primary"], p[bg]) >= 4.5, (accent, name, bg, round(ratio(a["primary"], p[bg]), 2))
        assert ratio(a["primary"], a["primary-tint"]) >= 4.5, (accent, "on its own tint")
        for fill in ("primary", "primary-hover"):
            assert ratio(p["on-primary"], a[fill]) >= 4.5, (accent, name, fill)

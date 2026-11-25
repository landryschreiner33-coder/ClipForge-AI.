"""The gold command robot icon: every copy is made by scripts/make_icons.py from the one approved picture, and the
Mac build shows the name ClipForge while keeping the ClipFoundry.app folder (so updates replace it in place)."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import plistlib
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
APPROVED_SHA = "f99cf07c21059134c80a28ad4c6af8e7e62e5cf004abc2ec1e673a0d05bb452e"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


icons = _load("make_icons", ROOT / "scripts/make_icons.py")


def test_the_source_is_the_owners_approved_picture():
    assert hashlib.sha256(icons.SOURCE.read_bytes()).hexdigest() == APPROVED_SHA


def test_every_committed_icon_is_exactly_what_the_generator_makes():
    assert icons.main(["--check"]) == 0, "run python scripts/make_icons.py and commit the files"


def test_the_big_icon_is_a_1024_png_with_transparent_corners_and_all_copies_match():
    big = (ROOT / "design/tiktok/app-icon-dark.png").read_bytes()
    im = Image.open(io.BytesIO(big))
    assert im.size == (1024, 1024) and im.mode == "RGBA"
    assert im.getpixel((0, 0))[3] == 0  # rounded tile: the corner is see-through
    assert im.getpixel((512, 512))[3] >= 250  # the approved art is very slightly translucent (254)
    for copy in ("frontend/public/app-icon.png", "docs/legal/app-icon.png", "design/tiktok/app-icon-light.png"):
        assert (ROOT / copy).read_bytes() == big, copy
    assert len(big) < 5 * 1024 * 1024  # TikTok's form takes at most 5 MB


def test_the_windows_icon_has_every_size_the_taskbar_and_start_menu_use():
    data = (ROOT / "frontend/public/favicon.ico").read_bytes()
    assert data[:4] == b"\x00\x00\x01\x00"
    assert (ROOT / "docs/legal/favicon.ico").read_bytes() == data
    sizes = Image.open(io.BytesIO(data)).info["sizes"]
    assert {(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)} <= set(sizes)


def test_small_sizes_keep_the_robots_eyes():
    """At 16 px the whole tile would shrink the visor to a smear; the close crop keeps bright eyes inside a dark
    visor. Check that the middle row of a 16 px icon has both gold and dark pixels."""
    im = icons.for_size(16).convert("RGB")
    row = [im.getpixel((x, 8)) for x in range(16)] + [im.getpixel((x, 9)) for x in range(16)]
    bright = [p for p in row if p[0] > 170 and p[1] > 120]
    dark = [p for p in row if sum(p) < 120]
    assert len(bright) >= 4 and len(dark) >= 4


def test_mac_iconset_has_apples_ten_sizes_on_the_icon_grid():
    folder = ROOT / "macos/desktop/AppIcon.iconset"
    names = sorted(p.name for p in folder.glob("*.png"))
    assert len(names) == 10
    for size in (16, 32, 128, 256, 512):
        for scale, suffix in ((1, ""), (2, "@2x")):
            im = Image.open(folder / f"icon_{size}x{size}{suffix}.png")
            assert im.size == (size * scale, size * scale)
    big = Image.open(folder / "icon_512x512@2x.png")
    assert big.getpixel((60, 512))[3] == 0  # Apple's grid leaves a margin around the 824 px body
    assert big.getpixel((512, 512))[3] >= 250


def test_mac_app_shows_clipforge_but_keeps_the_folder_id_and_data_names():
    build = _load("build_desktop", ROOT / "macos/build_desktop.py")
    info = build.info_plist("abc123", "2026.11.25")
    assert info["CFBundleIdentifier"] == "com.clipfoundry.studio"  # Keychain, WebKit storage and defaults key on it
    assert info["CFBundleExecutable"] == "ClipFoundry"
    assert info["CFBundleDisplayName"] == build.FOLDER_NAME == "ClipFoundry"  # must equal the folder name
    assert info["LSHasLocalizedDisplayName"] is True and info["CFBundleName"] == "ClipForge"
    assert info["CFBundleShortVersionString"] == "2026.11.25"


def test_mac_localized_name_file_says_clipforge(tmp_path):
    build = _load("build_desktop", ROOT / "macos/build_desktop.py")
    path = build.write_localization(tmp_path)
    assert path == tmp_path / "Resources/en.lproj/InfoPlist.strings"
    assert plistlib.loads(path.read_bytes()) == {"CFBundleDisplayName": "ClipForge", "CFBundleName": "ClipForge"}


def test_release_version_accepts_only_a_date_version(monkeypatch):
    build = _load("build_desktop", ROOT / "macos/build_desktop.py")
    for good in ("2026.11.25", "2026.11.25.2"):
        monkeypatch.setenv("CLIPFORGE_VERSION", good)
        assert build.release_version() == good
    for bad in ("", "1.0", "2026.11.25; rm -rf /", "v2026.11.25"):
        monkeypatch.setenv("CLIPFORGE_VERSION", bad)
        assert build.release_version() == ""


def test_user_visible_launch_files_say_clipforge():
    for name in ("run-unattended.bat", "gpu-check.bat", "test-isolated.bat"):
        text = (ROOT / name).read_text()
        assert "ClipFoundry" not in text, name
    phone = (ROOT / "frontend/public/phone/index.html").read_text()
    assert "Foundry" not in phone and 'href="/icon.png"' in phone
    for page in ("index.html", "privacy.html", "terms.html"):
        html = (ROOT / "docs/legal" / page).read_text()
        assert '<a class="brand" href="index.html"' in html and ">ClipForge</a>" in html, page

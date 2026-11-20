"""File addresses from requests (clipfoundry/pathguard.py): only plain folder and file names reach the file system.

Windows path rules are checked with PureWindowsPath, so this runs on every computer: on Windows, merely looking at
\\\\server\\share\\x connects to that server and signs in as the person.
"""
from __future__ import annotations

from pathlib import PureWindowsPath

import pytest

from clipfoundry.pathguard import plain_parts

TRICKY = ["//evil/share/x.js", "\\\\evil\\share\\x.js", "\\\\?\\UNC\\evil\\share\\x", "\\\\.\\pipe\\x", "/etc/passwd",
          "\\Windows\\win.ini", "C:/Windows/win.ini", "C:evil.js", "c:\\evil", "D:", "a/D:evil", "index.html:evil",
          "index.html::$DATA", "../secret", "a/../../secret", "a/..", "..", ".", "a\\..\\..\\secret", "a/\0b", "",
          "a//b", "a/./b", "./a", "a/", "assets/app.js", "index.html", "dir with space/file name.png", "名前/画像.png"]


@pytest.mark.parametrize("path", ["index.html", "assets/app.js", "a/", "a//b", "a/./b", "./a",
                                  "dir with space/file name.png", "名前/画像.png"])
def test_plain_names_are_kept(path):
    parts = plain_parts(path)
    assert parts and all(p not in ("", ".", "..") for p in parts)


@pytest.mark.parametrize("path", ["", "/etc/passwd", "//evil/share/x.js", "\\\\evil\\share\\x.js",
                                  "\\\\?\\UNC\\evil\\share\\x", "\\\\.\\pipe\\x", "\\Windows\\win.ini",
                                  "C:/Windows/win.ini", "C:evil.js", "c:\\evil", "D:", "a/D:evil", "index.html:evil",
                                  "index.html::$DATA", "..", "../secret", "a/../../secret", "a/..",
                                  "a\\..\\..\\secret", "a/\0b"])
def test_anything_else_is_refused(path):
    assert plain_parts(path) is None


@pytest.mark.parametrize("path", TRICKY)
def test_what_is_kept_stays_in_the_folder_on_windows(path):
    """Whatever is kept, joined to a Windows folder, is still on that drive, inside that folder, and not a share."""
    parts = plain_parts(path)
    if parts is None:
        return
    base = PureWindowsPath("C:/Users/Ana/ClipForge/web")
    joined = base.joinpath(*parts)
    assert joined.drive == "C:" and base in joined.parents and ".." not in joined.parts

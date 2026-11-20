"""File addresses that came from a request, checked before anything looks at the file system.

On Windows, merely looking at a path such as \\\\server\\share\\x or //server/share/x (resolving it, asking whether
it exists, opening it) connects to that server and signs in as the person, handing it their password hash. Any web
page the person visits can make the browser ask ClipForge for an address (an image or script tag needs no
permission), so a file address from a request is reduced to plain folder and file names first, and anything else is
refused before a single file is looked at. Other drives ("D:x"), absolute paths, alternate data streams ("a.js:x")
and ".." are refused for the same reason: none of them stays inside the folder a route serves.

The containment check after resolving (symbolic links) is still each route's job; this only decides what may reach
the file system at all.
"""
from __future__ import annotations

from pathlib import PurePosixPath


def plain_parts(path: str) -> tuple[str, ...] | None:
    """`path` (forward slashes, as in a URL) as plain folder and file names, or None when it is anything else."""
    if not path or path.startswith("/") or any(c in path for c in "\\:\0"):
        return None
    parts = PurePosixPath(path).parts
    if not parts or any(p in (".", "..") for p in parts):
        return None
    return parts

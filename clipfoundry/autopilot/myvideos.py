"""Your videos folder: the one place to put videos for Autopilot.

Videos from other channels are never used without an agreement or a license, so a fresh Autopilot with only a
connected account often finds nothing it may clip. This folder gives it something to work on without any setup: it
lives in your Videos folder (outside the ClipFoundry folder, so updating ClipFoundry never deletes it), it is watched
like any folder you add, and what you put there counts as your own content (Owned), as a video uploaded on the Create
page does. The page says so: only put videos there that you made or may use.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .. import config, db
from . import providers, rights, state

NAME = "Your videos folder"
BASIS = "Your ClipFoundry videos folder: videos you put there are your own, or ones you may use"
FEED_KEY = "my_videos:feed"


def default_folder() -> Path:
    """Videos\\ClipFoundry in your user folder (CLIPFOUNDRY_VIDEOS overrides it: tests, the sandbox)."""
    env = os.environ.get("CLIPFOUNDRY_VIDEOS")
    if env:
        return Path(env)
    videos = Path.home() / "Videos"
    return (videos / "ClipFoundry") if videos.is_dir() else (Path.home() / "ClipFoundry videos")


def feed() -> dict | None:
    """The watch-folder entry of your videos folder, if it exists."""
    fid = state.get(FEED_KEY)
    return (db.fetch("source_feeds", fid) if fid else None) or None


def folder() -> Path:
    f = feed()
    return Path((f.get("config") or {}).get("path") or "") if f else default_folder()


def ensure(explicit: bool = False) -> dict | None:
    """Create the folder and watch it. Idempotent. If you removed it under Advanced, it only comes back when you
    ask for it (`explicit`: OPEN MY VIDEOS FOLDER); if you turned it off there, it stays off."""
    f = feed()
    if f is None and state.get(FEED_KEY) and not explicit:
        return None  # removed under Advanced: respected until you open the folder again
    path = Path((f.get("config") or {}).get("path")) if f else default_folder()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        state.event("my_videos", f"Could not create your videos folder {path}: {exc}", level="warning")
        return f
    if f is None:
        # The resolved path, so the rule also covers files whose resolved path runs through a redirected folder
        where = str(path.resolve())
        f = providers.add_feed("watch_folder", NAME, {"path": where, "my_videos": True}, rights.OWNED, BASIS)
        if not any(r["scope"] == "folder" and r["value"] == rights.normalize_path(where) and r["status"] == rights.OWNED
                   for r in rights.rules()):
            rights.add_rule("folder", where, rights.OWNED, BASIS, label=NAME)
        state.put(FEED_KEY, f["id"])
        state.event("my_videos", f"Watching your videos folder: {where}")
    return f


def videos(limit: int = 1000) -> int:
    """How many video files are in the folder now."""
    root = folder()
    if not root.is_dir():
        return 0
    n = 0
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in config.VIDEO_EXTENSIONS and not p.name.startswith("."):
            n += 1
            if n >= limit:
                break
    return n


def unseen() -> int:
    """Videos in the folder Autopilot has not picked up yet (just added, or still being copied)."""
    root = folder()
    if not root.is_dir():
        return 0
    known = {r["local_path"] for r in db.select("sources", "platform = 'local' AND local_path != ''")}
    return sum(1 for p in root.rglob("*") if p.is_file() and p.suffix.lower() in config.VIDEO_EXTENSIONS
               and not p.name.startswith(".") and str(p.resolve()) not in known)


def view() -> dict:
    f = feed()
    return {"path": str(folder()), "watching": bool(f and f.get("enabled")), "videos": videos()}


def open_in_explorer() -> dict:
    """Show the folder in File Explorer (Finder, or the file manager), creating it first if needed. If no file
    manager can be started, the page shows the folder's path instead."""
    ensure(explicit=True)
    path = str(folder())
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - a folder this app created, opened for the user
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path],  # noqa: S603, S607
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        opened = True
    except OSError:
        opened = False
    return {**view(), "opened": opened}

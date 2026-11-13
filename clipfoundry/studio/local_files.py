"""The folders of this computer a file can be used from where it is (desktop only; uploads.link_local).

ClipForge looks only inside the owner's own places: the home folder with its Desktop, Documents, Downloads and
Movies (macOS) or Videos folder, and external drives (macOS: /Volumes except the boot volume; Windows: the drive
letters other than the system drive; Linux: /media/<user>, /run/media/<user> and /mnt). Nothing else on the
computer can be listed or linked, and every path is resolved before it is checked, so a link that points somewhere
else does not get around the list. `CLIPFOUNDRY_LOCAL_ROOTS` (folders separated by ":" on macOS and Linux and ";"
on Windows) replaces the list, for an owner who keeps footage elsewhere and for the tests. Cloud mode never browses
the server.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path, PureWindowsPath

from ..cloud import settings as cloud_settings

ENV_ROOTS = "CLIPFOUNDRY_LOCAL_ROOTS"
MAX_ENTRIES = 500  # folders and files listed per folder before the answer says it was cut short
HIDDEN = {"$RECYCLE.BIN", "System Volume Information"}  # a Windows-formatted drive's own folders


class LocalError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _inside(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def _drives() -> list[tuple[str, Path]]:
    """External drives, labelled by their folder name (Windows: the drive letter)."""
    out: list[tuple[str, Path]] = []
    if sys.platform == "darwin":
        volumes = Path("/Volumes")
        for p in sorted(volumes.iterdir()) if volumes.is_dir() else []:
            try:
                if p.is_dir() and not os.path.samefile(p, "/"):  # the boot volume is the home folder's own disk
                    out.append((p.name, p))
            except OSError:
                continue
        return out
    if os.name == "nt":
        listdrives = getattr(os, "listdrives", None)  # Python 3.12 and later
        drives = list(listdrives()) if listdrives else [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
        system = (os.environ.get("SystemDrive") or "C:").upper()
        for d in drives:
            p = Path(d)
            try:
                if p.drive.upper() != system and p.is_dir():
                    out.append((p.drive, p))
            except OSError:
                continue
        return out
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - no account name to be found: only /mnt is left
        user = ""
    bases = [Path("/mnt")] + ([Path("/media") / user, Path("/run/media") / user] if user else [])
    for base in bases:
        try:
            entries = sorted(base.iterdir()) if base.is_dir() else []
            out += [(p.name, p) for p in entries if p.is_dir()]
        except OSError:
            continue
    return out


def roots() -> list[dict]:
    """The top folders the owner can pick from, in the order they are shown: [{"label", "path"}], only folders
    that exist, each once (the path is the real one, links followed)."""
    override = os.environ.get(ENV_ROOTS, "")
    if override.strip():
        wanted = [(Path(raw.strip()).expanduser().name or raw.strip(), Path(raw.strip()).expanduser())
                  for raw in override.split(os.pathsep) if raw.strip()]
    else:
        home = Path.home()
        movies = "Movies" if sys.platform == "darwin" else "Videos"
        wanted = [("Home", home), ("Desktop", home / "Desktop"), ("Documents", home / "Documents"),
                  ("Downloads", home / "Downloads"), (movies, home / movies), *_drives()]
    out: list[dict] = []
    seen: set[str] = set()
    for label, path in wanted:
        try:
            if not path.is_dir():
                continue
            real = str(path.resolve())
        except OSError:
            continue
        if real not in seen:
            seen.add(real)
            out.append({"label": label, "path": real})
    return out


def other_computer(path: str, tops: list[dict]) -> bool:
    """Whether `path` names another computer (\\\\server\\share, //server/share or any mix of the two slashes) or a
    Windows device path (\\\\?\\..., \\\\.\\...) rather than a folder of this computer, other than a network share the
    owner listed as one of the roots. Decided from the text alone, before anything looks at it: on Windows, merely
    looking at such a path connects to that server and signs in as the person, and any web page can ask for one."""
    text = str(path or "").strip().replace("/", "\\")
    if not text.startswith("\\\\"):
        return False
    shares = {PureWindowsPath(r["path"].replace("/", "\\")).drive.lower() for r in tops
              if r["path"].replace("/", "\\").startswith("\\\\")}
    return PureWindowsPath(text).drive.lower() not in shares


ELSEWHERE = "ClipForge only looks at the folders of this computer and its drives, not at other computers."


def allowed(path: Path) -> bool:
    """Whether a path (links followed) lies inside one of the roots."""
    try:
        target = Path(path).resolve()
    except (OSError, RuntimeError):
        return False
    return any(_inside(target, Path(r["path"])) for r in roots())


def browse(path: str = "") -> dict:
    """What a folder holds, for the "Add from this computer" picker. An empty path lists the roots as the folders.
    Only media files are listed (uploads.kind_of), hidden entries and entries that cannot be read are left out,
    names sort without regard to case, and at most 500 folders and 500 files are shown ("truncated" says when
    more were there). `parent` is "" at a root."""
    from . import uploads  # uploads imports this module for link_local, so the import is made here

    if cloud_settings.enabled():
        raise LocalError("Browsing the server's folders is not available in the cloud; upload the file instead.",
                         403)
    tops = roots()
    if not (path or "").strip():
        return {"path": "", "parent": "", "roots": tops,
                "folders": [{"name": r["label"], "path": r["path"]} for r in tops], "files": [], "truncated": False}
    if other_computer(path, tops):
        raise LocalError(ELSEWHERE, 403)
    raw = Path(path.strip())
    if not raw.is_absolute():
        raise LocalError("Give the full path of a folder, starting at the root folder or the drive.", 400)
    folder = raw.resolve()
    if not allowed(folder):
        raise LocalError(f"ClipForge may only look inside your own folders and external drives, not {raw}.", 403)
    if not folder.is_dir():
        raise LocalError(f"There is no folder at {raw}.", 404)
    try:
        with os.scandir(folder) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except OSError as exc:
        raise LocalError(f"ClipForge is not allowed to read {raw}.", 403) from exc
    folders: list[dict] = []
    files: list[dict] = []
    truncated = False
    for entry in entries:
        name = entry.name
        if name.startswith(".") or name in HIDDEN:
            continue
        try:
            if entry.is_dir():
                if len(folders) >= MAX_ENTRIES:
                    truncated = True
                    continue
                folders.append({"name": name, "path": os.path.join(folder, name)})
            elif entry.is_file():
                kind = uploads.kind_of(name)
                if kind is None:
                    continue
                if len(files) >= MAX_ENTRIES:
                    truncated = True
                    continue
                st = entry.stat()
                files.append({"name": name, "path": os.path.join(folder, name), "size": st.st_size, "kind": kind,
                              "modified": st.st_mtime})
        except OSError:
            continue  # an entry that cannot be read is left out
    parent = "" if any(str(folder) == r["path"] for r in tops) else str(folder.parent)
    return {"path": str(folder), "parent": parent, "roots": tops, "folders": folders, "files": files,
            "truncated": truncated}

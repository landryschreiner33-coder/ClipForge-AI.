"""Pinned downloads for the local makers: every file ClipForge fetches for them has a fixed address, size and
SHA-256 written in catalog.py, is streamed into a `.part` file (a stopped download resumes where it stopped), is never
allowed to grow past its size, and is checked before it is used. A file that does not match is deleted.

Archives (ComfyUI's source, uv) are unpacked with the same checks as the editing apps: nothing outside the target
folder, no links out of it, no devices.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tarfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from . import EngineError

MARKER = "clipforge-verified.json"
CHUNK = 1 << 20


@dataclass(frozen=True)
class Pinned:
    """One file: where it comes from, how big it is and its SHA-256 (lower-case hex)."""
    name: str
    url: str
    size: int
    sha256: str


def sha256_file(path: Path, progress: Callable[[int], None] | None = None,
                cancelled: Callable[[], bool] = lambda: False) -> str:
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(8 * CHUNK), b""):
            if cancelled():
                raise EngineError("Stopped.")
            h.update(block)
            done += len(block)
            if progress:
                progress(done)
    return h.hexdigest()


def fetch(pin: Pinned, dest: Path, progress: Callable[[int], None] | None = None,
          cancelled: Callable[[], bool] = lambda: False, check: Callable[[int], None] | None = None) -> Path:
    """Download `pin` to `dest` (resuming a partial download) and check its size and SHA-256. A finished file that
    already matches its size is only re-checked, and so is a `.part` file that has every byte. Returns `dest`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size == pin.size:
        if sha256_file(dest, check, cancelled) == pin.sha256:
            return dest
        dest.unlink(missing_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if have > pin.size:
        part.unlink()
        have = 0
    if have and have == pin.size:  # every byte came, but it was not checked and finished (the computer stopped)
        if sha256_file(part, check, cancelled) == pin.sha256:
            _finish(part, dest)
            return dest
        part.unlink()
        have = 0
    digest = hashlib.sha256()
    if have:
        with open(part, "rb") as fh:  # the hash of what is already there, so the finished file is hashed once
            for block in iter(lambda: fh.read(8 * CHUNK), b""):
                digest.update(block)
    try:
        for again in (False, True):
            headers = {"Range": f"bytes={have}-"} if have else {}
            with httpx.stream("GET", pin.url, headers=headers, follow_redirects=True,
                              timeout=httpx.Timeout(30.0, read=120.0)) as r:
                if r.status_code == 416 and have and not again:  # it cannot go on from there: start over, once
                    part.unlink(missing_ok=True)
                    have, digest = 0, hashlib.sha256()
                    continue
                if r.status_code == 200 and have:  # the server ignored the range: start over
                    have, digest = 0, hashlib.sha256()
                elif r.status_code not in (200, 206):
                    raise EngineError(f"The download of {pin.name} answered HTTP {r.status_code}.")
                with open(part, "ab" if have else "wb") as fh:
                    for block in r.iter_bytes(CHUNK):
                        if cancelled():
                            raise EngineError("Stopped. The download resumes where it stopped next time.")
                        have += len(block)
                        if have > pin.size:
                            raise EngineError(f"{pin.name} is larger than expected; it was not used.")
                        digest.update(block)
                        fh.write(block)
                        if progress:
                            progress(have)
            break
    except httpx.ConnectError as exc:
        raise EngineError("Could not connect to download it. Check the internet connection and try again (the "
                          "download resumes).") from exc
    except httpx.TimeoutException as exc:
        raise EngineError("The download stalled. Try again; it resumes where it stopped.") from exc
    except httpx.HTTPError as exc:
        raise EngineError(f"The download of {pin.name} failed ({exc.__class__.__name__}). Try again.") from exc
    if have != pin.size or digest.hexdigest() != pin.sha256:
        part.unlink(missing_ok=True)
        raise EngineError(f"{pin.name} did not match its published checksum, so it was deleted. Try again.")
    _finish(part, dest)
    return dest


def _finish(part: Path, dest: Path, tries: int = 6) -> None:
    """Give the checked `.part` file its name. On Windows a virus scanner or the search indexer may still hold the
    new file for a moment, so this tries again for a few seconds (the checked file is kept if it never lets go)."""
    for n in range(tries):
        try:
            part.replace(dest)
            return
        except PermissionError as exc:
            if n == tries - 1:
                raise EngineError(f"Could not finish {dest.name}: another program is holding it. Try again in a "
                                  "moment; nothing has to be downloaded again.") from exc
            time.sleep(0.25 * (n + 1))


def read_marker(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_marker(folder: Path, data: dict) -> None:
    tmp = folder / (MARKER + ".tmp")
    tmp.write_text(json.dumps({**data, "verified_at": time.time()}, indent=1), encoding="utf-8")
    tmp.replace(folder / MARKER)


def free_bytes(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free


def need_space(path: Path, needed: int, what: str) -> None:
    """Refuse to start a download that cannot fit (with 2 GB to spare for the computer)."""
    if needed <= 0:
        return
    free = free_bytes(path)
    if free < needed + (2 << 30):
        raise EngineError(f"Not enough free disk space for {what}: it needs about {(needed + (2 << 30)) / 1e9:.1f} GB "
                          f"and {free / 1e9:.1f} GB is free.")


def _inside(base: Path, name: str) -> Path:
    target = (base / name).resolve()
    if target != base and base not in target.parents:
        raise EngineError(f"The archive has a file outside its folder ({name!r}); it was not used.")
    return target


def extract(archive: Path, dest: Path) -> None:
    """Unpack a .zip or .tar.gz into `dest`: no path outside it, links only to files inside it, no devices."""
    dest.mkdir(parents=True, exist_ok=True)
    base = dest.resolve()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                mode = info.external_attr >> 16
                if (mode & 0o170000) == 0o120000:
                    raise EngineError("The archive has a link in it; it was not used.")
                target = _inside(base, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, CHUNK)
                if mode & 0o111:
                    target.chmod(0o755)
        return
    with tarfile.open(archive, "r:*") as t:
        members = t.getmembers()
        for m in members:
            target = _inside(base, m.name)
            if m.issym() or m.islnk():
                link = (target.parent / m.linkname).resolve() if m.issym() else (base / m.linkname).resolve()
                if link != base and base not in link.parents:
                    raise EngineError(f"The archive has a link out of its folder ({m.name}); it was not used.")
            elif not (m.isfile() or m.isdir()):
                raise EngineError(f"The archive has a special file in it ({m.name}); it was not used.")
        try:
            t.extractall(base, members=members, filter="data")
        except TypeError:  # Python without extraction filters: every member was checked above
            t.extractall(base, members=members)  # noqa: S202


def long_path(path: str) -> str:
    """An absolute Windows path written the way that lets it pass 260 letters (\\\\?\\C:\\..., \\\\?\\UNC\\server\\...)."""
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def remove_tree(path: Path) -> bool:
    """Delete a folder ClipForge made: read-only files too, which Windows refuses to delete otherwise, and files
    deeper than Windows' 260 letters (PyTorch's are, when ClipForge's folder is deep). True when it is gone."""
    def unlock(func, p, _exc):  # noqa: ANN001
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass

    target = long_path(os.path.abspath(path)) if sys.platform == "win32" else str(path)
    if os.path.exists(target):
        try:
            shutil.rmtree(target, onexc=unlock)  # type: ignore[call-arg]
        except TypeError:  # Python < 3.12
            shutil.rmtree(target, onerror=unlock)
    return not os.path.exists(target)

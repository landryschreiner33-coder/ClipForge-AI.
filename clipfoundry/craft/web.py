"""FilmCraft's editor inside ClipForge's editor page, and the person's saves coming back.

FilmCraft's web build (the same engine and editor as the desktop app, compiled to WebAssembly) is served by ClipForge
itself at /craft/filmcraft/ and framed by the editor page on the same address (`?host=parent`). The page hands it
the media first (`filmcraft.importUrl`: each file becomes `/files/<name>` in the editor's own file table, read in
pieces as it plays, never copied whole) and then the project (`filmcraft.openProject`). A save comes back to the page
as the project file (`filmcraft:save`), which the page sends here.

* `session`: the project for one version in the editor's file names: every file the project names becomes
  `/files/<name>`, served only from the list kept in `web.json` (never a path the browser sends).
* `accept`: a saved project back in ClipForge's file names. Every `/files/<name>` must be one of this video's files
  or a file the person added in the editor and the page sent here (`add_file`); any other file path or address is
  refused, so a saved project can only ever read this video's files when ClipForge renders it.

A version finished by hand is saved as `<video>/filmcraft/saves/<sha256>.fcproj` and becomes a new version of the
video whose plan names it (`plan["filmcraft"]`); its preview and final video are rendered by FilmCraft from that file.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from .runner import CraftError

MAX_PROJECT = 256 << 20    # FilmCraft's own limit for a project it opens
MAX_FILE = 512 << 20       # ...and for a file the page hands it
FILES = "/files/"
_PATHISH = re.compile(r"^(?:/|~|\\|[A-Za-z]:[\\/]|file:)", re.I)  # a leading \ too: \\server\share, \/server/share
_CLIMB = re.compile(r"(?:^|[\\/])\.\.[\\/]|[\\/]\.\.$")  # ..\x, a/../b, a/.. (not ".." said on its own)
_VIRTUAL = ("/projects/", "/exports/")  # the editor's own folders for projects and exports: nothing is read there
_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")
_PLAIN = re.compile(r"[^A-Za-z0-9._-]+")  # the names ClipForge gives files in the editor (FilmCraft keeps them)


def _load(data: bytes) -> object:
    if len(data) > MAX_PROJECT:
        raise CraftError("The project is larger than FilmCraft opens (256 MB).")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CraftError("This is not a FilmCraft project ClipForge can read.") from exc


def _strings(node, visit, key: str = ""):
    """Every string in the document, replaced by visit(key, value) (which returns the new value)."""
    if isinstance(node, dict):
        return {k: _strings(v, visit, k) for k, v in node.items()}
    if isinstance(node, list):
        return [_strings(v, visit, key) for v in node]
    if isinstance(node, str):
        return visit(key, node)
    return node


def file_name(n: int, path: Path) -> str:
    """The name a file has in the editor: numbered (two files may share a name), plain letters only."""
    stem = _PLAIN.sub("-", path.stem).strip(".-")[:40] or "media"
    ext = _PLAIN.sub("", path.suffix)[:10]
    return f"{n:02d}-{stem}{ext}"


def _elsewhere(value: str) -> bool:
    """Another computer (\\\\server\\share, //server/share or any mix of the two slashes) or a Windows device path.
    Never looked up: on Windows, looking at one connects to that server and signs in as the person, and every text in a
    project (an AI's title, a project saved from the editor) is looked up as a possible file."""
    return value.strip().replace("\\", "/").startswith("//")


def _resolve(value: str, base: Path) -> Path | None:
    if not value or value.startswith(FILES) or value.startswith(_VIRTUAL):
        return None
    raw = value[7:] if value.startswith("file://") else value
    if _elsewhere(raw):
        return None
    p = Path(raw)
    p = p if p.is_absolute() else base / p
    try:
        return p.resolve() if p.is_file() else None
    except OSError:
        return None


def session(project: Path, manifest: Path, url: str) -> dict:
    """Write the editor's copy of `project` and `manifest` (name -> file); returns what the page loads.
    `url` is the address the media is served under (`<url>/<name>`)."""
    doc = _load(project.read_bytes())
    names: dict[str, str] = {}
    by_path: dict[str, str] = {}

    def visit(_key: str, value: str) -> str:
        real = _resolve(value, project.parent)
        if real is None:
            return value
        name = by_path.get(str(real))
        if name is None:
            name = file_name(len(names) + 1, real)
            names[name] = str(real)
            by_path[str(real)] = name
        return FILES + name

    web = _strings(doc, visit)
    old = json.loads(manifest.read_text()) if manifest.is_file() else {}
    added = {k: v for k, v in (old.get("added") or {}).items() if Path(v).is_file()}
    manifest.write_text(json.dumps({"made": time.time(), "project": str(project), "media": names, "added": added},
                                   indent=1))
    body = json.dumps(web).encode("utf-8")
    manifest.with_suffix(".fcproj").write_bytes(body)
    from urllib.parse import quote

    return {"media": [{"name": n, "url": f"{url}/{quote(n)}", "bytes": Path(p).stat().st_size}
                      for n, p in names.items()],
            "project_bytes": len(body)}


def media_file(manifest: Path, name: str) -> Path | None:
    """The file behind an editor name, from the list ClipForge wrote (None when it is not on it)."""
    if not manifest.is_file():
        return None
    m = json.loads(manifest.read_text())
    path = (m.get("media") or {}).get(name) or (m.get("added") or {}).get(name)
    return Path(path) if path and Path(path).is_file() else None


def clean_name(name: str) -> str:
    """A name the editor gave a file the person added (`/files/<name>`), refused when it could leave the folder."""
    name = str(name or "")
    if not name or len(name) > 200 or "/" in name or "\\" in name or name.startswith(".") or "\x00" in name:
        raise CraftError("That file name cannot be used.")
    return name


def add_file(manifest: Path, store: Path, name: str, received: Path) -> dict:
    """Keep a file the person added in the editor (`received`: what the page sent, already on disk; it is moved);
    returns {name, bytes}."""
    name = clean_name(name)
    size = received.stat().st_size
    if not size or size > MAX_FILE:
        received.unlink(missing_ok=True)
        raise CraftError("The file was empty." if not size else "A file over 512 MB cannot be added this way.")
    h = hashlib.sha256()
    with received.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    store.mkdir(parents=True, exist_ok=True)
    out = store / f"{h.hexdigest()[:16]}-{_SAFE.sub('-', name)[:80]}"
    received.replace(out)
    m = json.loads(manifest.read_text()) if manifest.is_file() else {"media": {}, "added": {}}
    m.setdefault("added", {})[name] = str(out)
    manifest.write_text(json.dumps(m, indent=1))
    return {"name": name, "bytes": size}


def accept(data: bytes, manifest: Path) -> tuple[bytes | None, list[str]]:
    """A saved project in ClipForge's file names, or (None, the editor files the page must send first).
    Raises CraftError when the project names a file or address that is not one of this video's files."""
    doc = _load(data)
    m = json.loads(manifest.read_text()) if manifest.is_file() else {}
    known = {**(m.get("media") or {}), **(m.get("added") or {})}
    need: list[str] = []
    bad: list[str] = []

    def visit(_key: str, value: str) -> str:
        v = value.strip()
        if v.startswith(FILES):
            name = v[len(FILES):]
            if name in known and Path(known[name]).is_file():
                return known[name]
            if name not in need:
                need.append(name)
            return value
        if v.startswith(_VIRTUAL) and ".." not in v:
            return value
        if _PATHISH.match(v) or _CLIMB.search(v) or re.match(r"^[a-z][a-z0-9+.-]*://", v, re.I):
            bad.append(v[:80])
        return value

    out = _strings(doc, visit)
    if bad:
        raise CraftError("The saved project names a file outside this video's files (" + bad[0] + "); it was not "
                         "saved. Add files to it from FilmCraft's own Import instead.")
    if need:
        for n in need:
            clean_name(n)
        return None, need
    return json.dumps(out).encode("utf-8"), []


def store_save(folder: Path, data: bytes) -> tuple[str, Path]:
    """Keep a saved project under its content hash (a version's file never changes)."""
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    path = folder / f"{digest}.fcproj"
    if not path.is_file():
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return digest, path

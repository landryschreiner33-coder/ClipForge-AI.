"""Which Crafting Apps ClipForge runs, where they live and how they get there.

ClipForge fetches FilmCraft and EffectCraft itself, from the ArtCraft team's official GitHub releases, pinned by
version and SHA-256 below (copied from each release's SHA256SUMS.txt). Nothing comes from a request: the address,
file name, size and hash of every download are fixed here. A file that does not match is deleted and never opened.

They are unpacked into ClipForge's own data folder (`tools/craft/<app>-<version>-<part>/`), not installed system-wide.
Each app has two parts: its command-line tool for this computer (`cli`), which the editor drives and which renders,
and its web editor (`web`), which ClipForge serves inside the editor page.

`CLIPFOUNDRY_FILMCRAFT_CLI` / `CLIPFOUNDRY_EFFECTCRAFT_CLI` point at another copy of a command-line tool (tests, a
server provisioned by hand); a FilmCraft the person installed themselves is used when ClipForge has none of its own.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import sys
import tarfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import config
from ..cloud import settings as cloud_settings

GITHUB = "https://github.com"
MAX_DOWNLOAD = 400 << 20


class CraftUnavailable(RuntimeError):
    """A Crafting App is not here and cannot be fetched now (the reason is written for the person)."""


@dataclass(frozen=True)
class App:
    key: str
    label: str
    what: str
    repo: str
    version: str
    cli: str
    files: dict  # part -> (file name, sha256, bytes)
    page: str

    def url(self, name: str) -> str:
        return f"{GITHUB}/{self.repo}/releases/download/v{self.version}/{name}"


APPS: dict[str, App] = {
    "filmcraft": App(
        key="filmcraft", label="FilmCraft", what="video editor", repo="storytold/filmcraft", version="0.17.1",
        cli="filmcraft-cli", page="https://getartcraft.com/apps/filmcraft",
        files={
            "macos": ("filmcraft-cli-0.17.1-macos-universal.zip",
                      "ca0749fecd44c51caee419d90938d24ce322340d7af1d1660605166f1ecd2755", 95187152),
            "linux-x86_64": ("filmcraft-0.17.1-linux-x86_64.tar.gz",
                             "397ae9fece559b37863b4b076af46a63b6e4387c35f781709e4efad14fe71ebe", 107780902),
            "linux-aarch64": ("filmcraft-0.17.1-linux-aarch64.tar.gz",
                              "225d6d815fad8cdfb720b5ce382196b60edd6ee10a9216660bcdabb28beaaa95", 104458899),
            "windows-x64": ("filmcraft-0.17.1-windows-x64-portable.zip",
                            "6a87da6b1bbf3251a6995626f8de42388c6255e10f434a893034774b4a5a6766", 109020901),
            "windows-arm64": ("filmcraft-0.17.1-windows-arm64-portable.zip",
                              "2c56464ca0cf144d3fdfe75eee1c4bee435aed929c26f8b9ee80a5de7de5bea5", 105212221),
            "web": ("filmcraft-web-0.17.1.zip",
                    "4449a9823adfd5b8996348c74abbb84e856c46480f9d06f85e07b277150a4e4f", 15199912),
        }),
    "effectcraft": App(
        key="effectcraft", label="EffectCraft", what="motion graphics and effects", repo="storytold/effectcraft",
        version="0.9.2", cli="effectcraft-cli", page="https://getartcraft.com/apps/effectcraft",
        files={
            "macos": ("effectcraft-cli-0.9.2-macos-universal.zip",
                      "957c39106f18d6bf4fc0a8b2ab8a084e334b183992390347a09dc04869dfd505", 59035495),
            "linux-x86_64": ("effectcraft-0.9.2-linux-x86_64.tar.gz",
                             "916d35d7dc0fd5650b57f576e6556256d05dedf93e83a9740c1892319bb4ac1c", 62661586),
            "linux-aarch64": ("effectcraft-0.9.2-linux-aarch64.tar.gz",
                              "3efab284d4f06380a0f36d9e8d21cafc9a05e505607cdacb8beb6d37b932d160", 58478914),
            "windows-x64": ("effectcraft-0.9.2-windows-x64-portable.zip",
                            "1f6fbb3a348f1b12b15faa3bc2c78a079414f07454cc1402208793486e79bee4", 65738563),
            "windows-arm64": ("effectcraft-0.9.2-windows-arm64-portable.zip",
                              "2dede4e9aac41d989544e0f1e61c9c61c29dd65d15282ae18d5de5b56da5486c", 60874629),
            "web": ("effectcraft-web-0.9.2.zip",
                    "09e4a278652fb389725f991c12ea4fb667599c19d0b2b3d2fded31d662bc1ad9", 18801063),
        }),
}
WEB_APPS = ("filmcraft",)  # whose web editor ClipForge serves (EffectCraft's is not shown yet)


def platform_key() -> str | None:
    """This computer's release files: macos (universal), linux-x86_64/-aarch64, windows-x64/-arm64; None otherwise."""
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64", "armv8l")
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux") and machine in ("x86_64", "amd64", "arm64", "aarch64"):
        return "linux-aarch64" if arm else "linux-x86_64"
    if sys.platform == "win32" and machine in ("amd64", "x86_64", "arm64"):
        return "windows-arm64" if arm else "windows-x64"
    return None


def tools_root() -> Path:
    return config.data_dir() / "tools" / "craft"


def part_dir(app: App, part: str) -> Path:
    return tools_root() / f"{app.key}-{app.version}-{part}"


def _marker(folder: Path) -> dict | None:
    try:
        m = json.loads((folder / "clipforge-install.json").read_text())
    except (OSError, ValueError):
        return None
    return m if isinstance(m, dict) else None


def _installed(app: App, part: str) -> dict | None:
    folder = part_dir(app, part)
    m = _marker(folder)
    if not m or m.get("version") != app.version or m.get("sha256") != app.files[part][1]:
        return None
    target = folder / m.get("path", "")
    if not target.exists() or folder.resolve() not in target.resolve().parents:
        return None
    return {**m, "abs": str(target.resolve())}


# ------------------------------------------------------------------ finding a tool
def find_cli(key: str) -> dict | None:
    """The command-line tool of `key` this ClipForge uses: {path, version, source}, or None."""
    app = APPS[key]
    env = os.environ.get(f"CLIPFOUNDRY_{key.upper()}_CLI", "").strip()
    if env:
        p = Path(env).expanduser()
        return {"path": str(p), "version": "", "source": "env"} if p.is_file() else None
    plat = platform_key()
    if plat:
        got = _installed(app, plat)
        if got:
            return {"path": got["abs"], "version": app.version, "source": "clipforge"}
    if key == "filmcraft" and not cloud_settings.enabled():
        from ..studio import filmcraft as desktop

        found = desktop.find()
        if found.get("cli"):
            return {"path": found["cli"], "version": found.get("version") or "", "source": "installed"}
    return None


def web_root(key: str) -> Path | None:
    """The folder with `key`'s web editor (index.html, the .wasm and its glue), when ClipForge has it."""
    got = _installed(APPS[key], "web")
    return Path(got["abs"]) if got else None


# ------------------------------------------------------------------ fetching
def _download(url: str, dest: Path, sha256: str, size: int, progress: Callable[[int], None],
              cancelled: Callable[[], bool]) -> None:
    import httpx

    h = hashlib.sha256()
    got = 0
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0)) as r:
            if r.status_code != 200:
                raise CraftUnavailable(f"The download answered HTTP {r.status_code}.")
            announced = int(r.headers.get("content-length") or 0)
            if announced and announced != size:
                raise CraftUnavailable(f"The file is {announced} bytes instead of {size}; it was not used.")
            with open(dest, "wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    if cancelled():
                        raise CraftUnavailable("Stopped.")
                    got += len(chunk)
                    if got > min(size, MAX_DOWNLOAD):
                        raise CraftUnavailable("The file is larger than expected; it was not used.")
                    h.update(chunk)
                    fh.write(chunk)
                    progress(got)
    except httpx.HTTPError as exc:
        raise CraftUnavailable(f"Could not download it ({exc.__class__.__name__}). Check the internet connection "
                               "and try again.") from exc
    if got != size or h.hexdigest() != sha256:
        dest.unlink(missing_ok=True)
        raise CraftUnavailable("The downloaded file does not match the release's checksum; it was deleted.")


def _inside(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    if target != root and root not in target.parents:
        raise CraftUnavailable(f"The archive has a file outside its folder ({name!r}); it was not used.")
    return target


def _unpack(archive: Path, into: Path) -> None:
    root = into.resolve()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise CraftUnavailable("The archive has a link in it; it was not used.")
                target = _inside(root, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                if mode & 0o111:
                    target.chmod(0o755)
        return
    with tarfile.open(archive, "r:gz") as t:
        members = t.getmembers()
        for m in members:
            _inside(root, m.name)
            if m.issym() or m.islnk() or m.isdev():
                if m.issym() and not Path(m.linkname).is_absolute() and ".." not in Path(m.linkname).parts:
                    continue  # a link to a sibling inside the archive (shared libraries); the data filter checks it
                raise CraftUnavailable("The archive has a link or device in it; it was not used.")
        try:
            t.extractall(root, members=members, filter="data")
        except TypeError:  # Python without extraction filters: the checks above already ran
            t.extractall(root, members=members)  # noqa: S202 - every member was checked above


def _locate(folder: Path, app: App, part: str) -> Path:
    if part == "web":
        hits = sorted(p.parent for p in folder.rglob("index.html") if any(p.parent.glob("*_bg.wasm")))
        if not hits:
            raise CraftUnavailable(f"{app.label}'s web editor was not in the download.")
        return hits[0]
    names = {app.cli, app.cli + ".exe"}
    hits = sorted((p for p in folder.rglob("*") if p.name in names and p.is_file()),
                  key=lambda p: (p.parent.name != "bin", len(p.parts)))
    if not hits:
        raise CraftUnavailable(f"{app.label}'s command-line tool was not in the download.")
    exe = hits[0]
    exe.chmod(exe.stat().st_mode | 0o755)
    return exe


def install_part(key: str, part: str, progress: Callable[[int], None] = lambda _n: None,
                 cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Fetch, check and unpack one part (a platform key or "web") of an app; nothing changes until it all worked."""
    app = APPS[key]
    if part not in app.files:
        raise CraftUnavailable(f"{app.label} has no release for this computer.")
    got = _installed(app, part)
    if got:
        return got
    name, sha256, size = app.files[part]
    root = tools_root()
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < size * 4:
        raise CraftUnavailable(f"Not enough free disk space for {app.label} ({size * 4 / 1e9:.1f} GB needed).")
    final = part_dir(app, part)
    work = root / f".{final.name}.part"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        archive = work / name
        _download(app.url(name), archive, sha256, size, progress, cancelled)
        unpacked = work / "files"
        unpacked.mkdir()
        _unpack(archive, unpacked)
        archive.unlink()
        target = _locate(unpacked, app, part)
        marker = {"app": key, "version": app.version, "part": part, "file": name, "sha256": sha256,
                  "path": str(target.relative_to(work)), "installed_at": time.time()}
        (work / "clipforge-install.json").write_text(json.dumps(marker, indent=1))
        shutil.rmtree(final, ignore_errors=True)
        work.replace(final)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    for old in root.glob(f"{key}-*-{part}"):  # earlier versions of this part
        if old != final:
            shutil.rmtree(old, ignore_errors=True)
    return _installed(app, part) or {}


# ------------------------------------------------------------------ the background task the app and Settings use
_lock = threading.Lock()
_task: dict = {"state": "idle", "app": "", "part": "", "done": 0, "total": 0, "error": "", "finished_at": 0.0}


def _wanted(parts: tuple[str, ...]) -> list[tuple[str, str]]:
    plat = platform_key()
    out = []
    for key, app in APPS.items():
        for part in parts:
            p = plat if part == "cli" else part
            if p and p in app.files and (part != "web" or key in WEB_APPS) and not _installed(app, p):
                out.append((key, p))
    return out


def status() -> dict:
    plat = platform_key()
    apps = []
    for key, app in APPS.items():
        cli = find_cli(key)
        web = web_root(key) if key in WEB_APPS else None
        apps.append({"key": key, "label": app.label, "what": app.what, "version": app.version, "page": app.page,
                     "cli": {"ready": bool(cli), "source": (cli or {}).get("source", ""),
                             "version": (cli or {}).get("version", ""),
                             "bytes": app.files[plat][2] if plat in app.files else 0},
                     "web": {"ready": bool(web), "bytes": app.files["web"][2]} if key in WEB_APPS else None})
    missing = _wanted(("cli", "web"))
    return {"platform": plat or "", "supported": bool(plat), "online": cloud_settings.enabled(),
            "can_install": bool(plat) and not cloud_settings.enabled(), "apps": apps,
            "ready": all(a["cli"]["ready"] for a in apps),
            "missing_bytes": sum(APPS[k].files[p][2] for k, p in missing), "task": dict(_task)}


def install(parts: tuple[str, ...] = ("cli", "web"), wait: bool = False) -> dict:
    """Fetch every missing part in the background (one task at a time); `wait` blocks until it is done."""
    if cloud_settings.enabled():
        raise CraftUnavailable("The online studio's server is set up by its operator; it does not fetch programs.")
    if not platform_key():
        raise CraftUnavailable("FilmCraft and EffectCraft have no release for this kind of computer.")
    todo = _wanted(parts)
    with _lock:
        if _task["state"] == "running":
            thread = None
        else:
            total = sum(APPS[k].files[p][2] for k, p in todo)
            _task.update(state="running" if todo else "done", app="", part="", done=0, total=total, error="",
                         finished_at=0.0 if todo else time.time())
            thread = threading.Thread(target=_run, args=(todo,), name="craft-install", daemon=True) if todo else None
    if thread:
        thread.start()
        if wait:
            thread.join()
    return status()


def _run(todo: list[tuple[str, str]]) -> None:
    base = 0
    try:
        for key, part in todo:
            _task.update(app=key, part=part)
            install_part(key, part, progress=lambda n, b=base: _task.update(done=b + n))
            base += APPS[key].files[part][2]
            _task.update(done=base)
        _task.update(state="done", error="", finished_at=time.time())
    except Exception as exc:  # noqa: BLE001 - reported to the person; the next try starts over
        _task.update(state="failed", error=str(exc)[:300], finished_at=time.time())


def auto_install(delay_s: float = 20.0) -> None:
    """The desktop app fetches the Crafting Apps once, in the background, soon after it starts (Settings can turn it
    off). Never in the online studio, and never while the computer is busy starting up."""
    if cloud_settings.enabled() or not platform_key():
        return

    def later():
        time.sleep(delay_s)
        try:
            from .. import db

            if not db.get_settings().get("craft_auto_install", True):
                return
            install()
        except Exception:  # noqa: BLE001 - offline or no disk: Settings shows it and can try again
            pass

    threading.Thread(target=later, name="craft-auto-install", daemon=True).start()

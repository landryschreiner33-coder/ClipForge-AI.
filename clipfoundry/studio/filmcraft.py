"""Open a ClipForge cut in FilmCraft, the free open-source video editor from the ArtCraft team (MIT OR Apache-2.0).

ClipForge never ships, downloads or builds FilmCraft: it looks for a copy the person installed from
https://getartcraft.com/apps/filmcraft (or GitHub releases) and hands it the cut as files.

* The cut is written as an OpenTimelineIO timeline with SRT captions (studio/interchange.py) in the video's folder.
* With FilmCraft's command-line tool (`filmcraft-cli`, inside the Windows and Linux installs, a separate download on
  a Mac) the timeline and captions are first imported into a FilmCraft project (`.fcproj`), which the app opens.
* Without it, the app is started with the timeline and captions as files to import (FilmCraft's own launch
  arguments: `filmcraft [project.fcproj | media files...]`; a timeline among the files is imported as a sequence).

Nothing is ever sent anywhere. Only the computer ClipForge runs on can open FilmCraft, so the online (cloud) studio
offers the timeline as a download instead. Paths to the app come from fixed install locations or the
CLIPFOUNDRY_FILMCRAFT / CLIPFOUNDRY_FILMCRAFT_CLI environment variables, never from a request.
"""
from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from ..cloud import settings as cloud_settings

PAGE = "https://getartcraft.com/apps/filmcraft"
RELEASES = "https://github.com/storytold/filmcraft/releases/latest"
APP_ENV = "CLIPFOUNDRY_FILMCRAFT"
CLI_ENV = "CLIPFOUNDRY_FILMCRAFT_CLI"
IMPORT_TIMEOUT_S = 300
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class FilmCraftError(RuntimeError):
    """FilmCraft could not be used (the reason is written for the person)."""


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _executable(p: Path) -> bool:
    return p.is_file() and (sys.platform == "win32" or os.access(p, os.X_OK))


def _mac_app_exe(app: Path) -> Path | None:
    exe = app / "Contents" / "MacOS" / "FilmCraft"
    if _executable(exe):
        return exe
    try:  # a renamed executable: the bundle says which
        info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
        exe = app / "Contents" / "MacOS" / str(info.get("CFBundleExecutable") or "")
        return exe if info.get("CFBundleExecutable") and _executable(exe) else None
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


def _mac_version(app: Path) -> str:
    try:
        info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
        return str(info.get("CFBundleShortVersionString") or "")
    except (OSError, plistlib.InvalidFileException, ValueError):
        return ""


def _windows_dirs() -> list[Path]:
    dirs = []
    try:  # the installer records where it put FilmCraft (per user or per machine)
        import winreg  # type: ignore[import-not-found]

        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, r"Software\FilmCraft") as key:
                    dirs.append(Path(winreg.QueryValueEx(key, "InstallDir")[0]))
            except OSError:
                pass
    except ImportError:
        pass
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        if os.environ.get(var):
            dirs.append(Path(os.environ[var]) / "FilmCraft")
    if os.environ.get("LOCALAPPDATA"):
        dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "FilmCraft")
    return dirs


def _bin_dirs() -> list[Path]:
    """Where a command-line tool usually lives. An app started from the Dock or Finder has a short PATH, so the
    usual folders are checked as well as PATH."""
    dirs = [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    dirs += [_home() / ".local" / "bin", _home() / "bin", Path("/usr/local/bin"), Path("/opt/homebrew/bin"),
             Path("/usr/bin")]
    return list(dict.fromkeys(dirs))


def find() -> dict:
    """Where FilmCraft is installed: {"app": path or "", "exe": path or "", "cli": path or "", "version": str}.
    `app` is what gets opened (an .app bundle on a Mac, the executable elsewhere)."""
    app = exe = cli = ""
    version = ""
    override = os.environ.get(APP_ENV, "").strip()
    if override:
        p = Path(override).expanduser()
        if p.suffix == ".app" and p.is_dir():
            found = _mac_app_exe(p)
            if found:
                app, exe, version = str(p), str(found), _mac_version(p)
        elif _executable(p):
            app = exe = str(p)
    elif sys.platform == "darwin":
        for folder in (Path("/Applications"), _home() / "Applications"):
            bundle = folder / "FilmCraft.app"
            found = _mac_app_exe(bundle) if bundle.is_dir() else None
            if found:
                app, exe, version = str(bundle), str(found), _mac_version(bundle)
                break
    elif sys.platform == "win32":
        for folder in _windows_dirs():
            if _executable(folder / "filmcraft.exe"):
                app = exe = str(folder / "filmcraft.exe")
                if _executable(folder / "filmcraft-cli.exe"):
                    cli = str(folder / "filmcraft-cli.exe")
                break
    else:
        for folder in _bin_dirs():
            if _executable(folder / "filmcraft"):
                app = exe = str(folder / "filmcraft")
                break
    cli_override = os.environ.get(CLI_ENV, "").strip()
    if cli_override:
        p = Path(cli_override).expanduser()
        cli = str(p) if _executable(p) else ""
    elif not cli:
        name = "filmcraft-cli.exe" if sys.platform == "win32" else "filmcraft-cli"
        near = [Path(exe).parent] if exe and sys.platform != "darwin" else []
        cli = next((str(d / name) for d in near + _bin_dirs() if _executable(d / name)), "")
    return {"app": app, "exe": exe, "cli": cli, "version": version}


def status() -> dict:
    """What the editor page shows next to "Open in FilmCraft"."""
    if cloud_settings.enabled():
        return {"available": False, "installed": False, "reason": "online", "page": PAGE,
                "message": "FilmCraft opens on the computer ClipForge runs on. In the online studio, download the "
                           "timeline and open it in FilmCraft on your own computer."}
    f = find()
    return {"available": True, "installed": bool(f["app"] or f["cli"]), "app": bool(f["app"]), "cli": bool(f["cli"]),
            "version": f["version"], "page": PAGE, "releases": RELEASES}


def import_project(cli: str, files: list[Path], project: Path) -> dict:
    """Import the timeline (then the captions) into a new FilmCraft project with FilmCraft's own command-line tool.
    Returns FilmCraft's import report; raises FilmCraftError when nothing usable was made."""
    project.unlink(missing_ok=True)
    cmd = [cli, "--compact", "import", *[str(f) for f in files], "--save-as", str(project)]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=IMPORT_TIMEOUT_S,  # noqa: S603 - fixed argv
                              cwd=str(project.parent), creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise FilmCraftError("FilmCraft took too long to import the timeline.") from exc
    except OSError as exc:
        raise FilmCraftError(f"FilmCraft's command-line tool could not be started: {exc}") from exc
    text = done.stdout.decode("utf-8", "replace").strip()
    report: dict = {}
    for line in reversed(text.splitlines()):  # the result is one JSON line
        try:
            report = json.loads(line)
            break
        except ValueError:
            continue
    if done.returncode != 0 or not project.is_file():
        why = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no project was written"]
        raise FilmCraftError(f"FilmCraft could not import the timeline: {why[0][:300]}")
    return report if isinstance(report, dict) else {}


def _launch(found: dict, files: list[Path]) -> None:
    """Start FilmCraft with these files (a project, or a timeline and captions to import)."""
    args = [str(f) for f in files]
    app = found["app"]
    try:
        if sys.platform == "darwin" and app.endswith(".app"):
            if len(files) == 1 and files[0].suffix == ".fcproj":
                cmd = ["open", "-a", app, *args]  # a FilmCraft project: also opens in a FilmCraft already running
            else:  # files to import are launch arguments, so they need a new instance
                cmd = ["open", "-n", "-a", app, "--args", *args]
            done = subprocess.run(cmd, capture_output=True, timeout=30)  # noqa: S603, S607 - macOS open
            if done.returncode != 0:
                why = done.stderr.decode("utf-8", "replace").strip()
                raise FilmCraftError(f"macOS could not open FilmCraft: {why[:300] or 'unknown error'}")
        elif sys.platform == "win32":
            flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen([found["exe"], *args], creationflags=flags, close_fds=True,  # noqa: S603
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        else:
            subprocess.Popen([found["exe"], *args], start_new_session=True, close_fds=True,  # noqa: S603
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise FilmCraftError("FilmCraft did not start in time.") from exc
    except OSError as exc:
        raise FilmCraftError(f"FilmCraft could not be started: {exc}") from exc


def open_package(pkg, found: dict | None = None) -> dict:
    """Open a written handoff package (interchange.Package) in FilmCraft. Returns what happened."""
    found = found or find()
    files = [pkg.timeline] + ([pkg.captions] if pkg.captions else [])
    out = {"installed": bool(found["app"] or found["cli"]), "opened": False, "how": "", "project": "",
           "warnings": []}
    if not out["installed"]:
        return out
    project = None
    if found["cli"]:
        project = pkg.timeline.with_suffix(".fcproj")
        try:
            report = import_project(found["cli"], files, project)
            out["project"] = str(project)
            out["warnings"] = [str(e) for e in report.get("errors") or []][:10]
            for doc in report.get("documents") or []:
                if not isinstance(doc, dict):
                    continue
                offline = doc.get("offlineMedia") or []
                if offline:
                    out["warnings"].append(f"{len(offline)} file(s) could not be found and show as offline.")
                notes = doc.get("report") if isinstance(doc.get("report"), list) else []
                out["warnings"] += [str(w) for w in notes][:10]
        except FilmCraftError as exc:
            if not found["app"]:
                raise
            out["warnings"].append(f"{exc} Opening the timeline in the app instead.")
            project = None
    if not found["app"]:
        out["how"] = "project"  # only the command-line tool: the project is ready to open by hand
        return out
    _launch(found, [project] if project else files)
    out.update(opened=True, how="project" if project else "timeline")
    return out


def reveal(folder: Path) -> bool:
    """Show the folder in Finder / File Explorer / the file manager."""
    try:
        if sys.platform == "win32":
            os.startfile(str(folder))  # noqa: S606 - a folder ClipForge made
        else:
            opener = "open" if sys.platform == "darwin" else shutil.which("xdg-open")
            if not opener:
                return False
            subprocess.Popen([opener, str(folder)], stdout=subprocess.DEVNULL,  # noqa: S603
                             stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False

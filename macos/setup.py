"""Readable, per-user Mac setup. No administrator access or global Python changes."""
from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
import webbrowser
import zipfile

BASE = Path.home() / "Library/Application Support/ClipFoundry"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract_app(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (path.is_absolute() or ".." in path.parts or "\\" in item.filename
                    or mode & 0o170000 == 0o120000):
                raise ValueError("Unsafe path in app package")
        z.extractall(destination)


def fetch(url: str, sha256: str, destination: Path) -> None:
    if destination.is_file() and digest(destination) == sha256:
        return
    if not url.startswith("https://github.com/eugeneware/ffmpeg-static/releases/download/"):
        raise ValueError("Unexpected video-tool download address")
    partial = destination.with_suffix(".partial")
    try:
        with urllib.request.urlopen(url, timeout=90) as response, partial.open("wb") as out:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 100 * 1024 * 1024:
                    raise ValueError("Video-tool download exceeded its size limit")
                out.write(chunk)
        if digest(partial) != sha256:
            raise ValueError("Video-tool checksum does not match. Reopen setup to retry.")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def install_release(bundle: Path, base: Path, manifest: dict) -> Path:
    revision = manifest["source_commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid app release identity")
    archive = bundle / "app.zip"
    if digest(archive) != manifest["app_sha256"]:
        raise ValueError("App checksum does not match. Download a fresh copy.")
    releases = base / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    target = releases / revision
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix=".unpack-", dir=releases) as scratch:
            stage = Path(scratch) / "app"
            stage.mkdir()
            extract_app(archive, stage)
            stage.rename(target)
    return target


def check_port(port: int = 8765) -> None:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(
                "Port 8765 is already in use. Close the other ClipForge window before reopening this setup. "
                "No process was stopped."
            ) from exc


def main(*, launch: bool = True) -> int:
    if sys.platform != "darwin" or platform.machine() != "arm64" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("Use the bundled Open-ClipFoundry.command on an Apple-silicon Mac.")
    os.umask(0o077)
    bundle = Path(__file__).resolve().parent
    manifest = json.loads((bundle / "manifest.json").read_text())
    BASE.mkdir(parents=True, exist_ok=True)
    # Hold the lock until the app exits. No stale PID deletion or killing another installation.
    with (BASE / "launcher.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("ClipForge is already running or setting up. Use its existing Terminal window.")
            webbrowser.open("http://127.0.0.1:8765")
            return 0
        check_port()
        app = install_release(bundle, BASE, manifest)
        python = app / ".venv/bin/python"
        if not python.exists():
            print("Creating ClipForge's private Python environment…", flush=True)
            subprocess.run([sys.executable, "-m", "venv", str(app / ".venv")], check=True)
        ready = app / ".setup-complete"
        if not ready.exists():
            print("Installing Mac dependencies. This first run needs an internet connection…", flush=True)
            subprocess.run([str(python), "-m", "pip", "install", "--only-binary=:all:",
                            "-r", str(app / "requirements-macos.txt")], cwd=app, check=True)
            subprocess.run([str(python), "-m", "pip", "check"], cwd=app, check=True)
        tools_dir = app / "tools/ffmpeg/bin"
        tools_dir.mkdir(parents=True, exist_ok=True)
        cache = BASE / "downloads"
        cache.mkdir(exist_ok=True)
        for name in ("ffmpeg", "ffprobe"):
            source = manifest["video_tools"][name]
            compressed = cache / (source["sha256"] + ".gz")
            binary = tools_dir / name
            if not binary.exists() or digest(binary) != source["binary_sha256"]:
                print(f"Downloading verified {name} from its upstream distributor…", flush=True)
                fetch(source["url"], source["sha256"], compressed)
                partial = binary.with_suffix(".partial")
                try:
                    with gzip.open(compressed, "rb") as src, partial.open("wb") as out:
                        shutil.copyfileobj(src, out)
                    if digest(partial) != source["binary_sha256"]:
                        raise ValueError("Extracted video tool did not match its checksum")
                    partial.chmod(0o700)
                    partial.replace(binary)
                finally:
                    partial.unlink(missing_ok=True)
        env = dict(os.environ, CLIPFOUNDRY_DATA=str(BASE / "data"), CLIPFOUNDRY_FFMPEG=str(tools_dir),
                   PYTHONNOUSERSITE="1", PYTHONUNBUFFERED="1")
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        # Diagnostics use an isolated temporary profile and synthetic media, never saved accounts or projects.
        if not ready.exists():
            subprocess.run([str(python), "macos/diagnose.py"], cwd=app, env=env, check=True)
            ready.write_text(manifest["source_commit"] + "\n")
        if not launch:
            print("Setup and native diagnostics finished.", flush=True)
            return 0
        print("Opening ClipForge. Your data lives in ~/Library/Application Support/ClipFoundry/data.", flush=True)
        print("Keep this window open. Press Control+C here to stop the app before updating.", flush=True)
        return subprocess.call([str(python), "-m", "clipfoundry", "--unattended", "--open"], cwd=app, env=env)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nClipForge stopped.")
    except Exception as exc:
        print(f"\nSetup could not finish: {exc}\nReopen the launcher to retry. Saved data is preserved.")
        raise SystemExit(1)

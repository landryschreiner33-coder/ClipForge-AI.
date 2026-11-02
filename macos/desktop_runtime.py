"""Owned local backend for the native Mac app; never installs or alters the bundle."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import sys
import threading
import time
import urllib.request

PREFIX = "CLIPFOUNDRY_DESKTOP "


def report(state: str, message: str = "") -> None:
    print(PREFIX + json.dumps({"state": state, "message": message}), flush=True)


def port_available(port: int) -> bool:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def observe(parent: int, port: int, session: str, done: threading.Event, *, timeout: float = 120) -> None:
    """No orphaned app after Force Quit. Readiness must belong to this launch."""
    ready = False
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while not done.wait(0.4):
        if os.getppid() != parent:
            os.kill(os.getpid(), signal.SIGTERM)
            return
        if not ready:
            try:
                with opener.open(f"http://127.0.0.1:{port}/api/desktop-status", timeout=1) as response:
                    payload = json.loads(response.read(4096))
                if payload.get("session") == session:
                    ready = True
                    report("ready")
            except (OSError, ValueError):
                pass
            if not ready and time.monotonic() > deadline:
                report("error", "The studio took too long to start. Quit and reopen ClipFoundry, or view its local logs.")
                os.kill(os.getpid(), signal.SIGTERM)
                return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", type=int, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--base", type=Path, default=Path.home() / "Library/Application Support/ClipFoundry")
    args = parser.parse_args()
    os.umask(0o077)
    if args.parent != os.getppid() or not args.session or not 1024 <= args.port <= 65535:
        report("error", "The desktop launch identity is invalid. Reopen ClipFoundry from Applications.")
        return 2
    resources = Path(__file__).resolve().parent
    app = resources / "app"
    args.base.mkdir(parents=True, exist_ok=True)
    with (args.base / "launcher.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            report("error", "Another ClipFoundry app or setup is running. Quit it first, then click Try again. Your data is safe.")
            return 2
        if not port_available(args.port):
            report("error", "Another app is using ClipFoundry’s local port. Close the old ClipFoundry window first, then click Try again. No other process was stopped.")
            return 2
        os.environ.update(CLIPFOUNDRY_DATA=str(args.base / "data"), CLIPFOUNDRY_DESKTOP_SESSION=args.session,
                          CLIPFOUNDRY_FFMPEG=str(resources.parent / "Helpers"), PYTHONDONTWRITEBYTECODE="1",
                          PYTHONNOUSERSITE="1", PYTHONUNBUFFERED="1",
                          FONTCONFIG_FILE=str(resources / "media/fonts.conf"))
        os.environ.pop("PYTHONHOME", None)
        os.environ.pop("PYTHONPATH", None)
        sys.path.insert(0, str(app))
        os.chdir(app)
        report("starting", "Opening your Brain, clips and workspace…")
        from clipfoundry import unattended

        done = threading.Event()
        watcher = threading.Thread(target=observe, args=(args.parent, args.port, args.session, done), daemon=True)
        # run() installs signal handlers before starting its first child. A tiny launch
        # interval is harmless: default SIGTERM exits before a child has been started.
        watcher.start()
        try:
            return unattended.run("127.0.0.1", args.port)
        finally:
            done.set()
            watcher.join(timeout=2)
            report("stopped")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Exception details can contain local paths or account data. Existing owned
        # backend logs remain local; do not send their contents through UI messages.
        report("error", "ClipFoundry could not start. View the local logs for details, then try again.")
        raise SystemExit(1)

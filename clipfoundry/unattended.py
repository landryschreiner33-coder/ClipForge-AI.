"""Opt-in app watchdog; restarting the UI process never grants publishing permission."""
from __future__ import annotations

import codecs
import ctypes
import hashlib
import logging
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from . import config, locks

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 2
MIN_RESTART_SECONDS = 2.0
MAX_RESTART_SECONDS = 60.0
STABLE_SECONDS = 300.0


class _PortLock(locks.FileLock):
    @property
    def path(self) -> Path:
        # Separate profiles must not repeatedly race for the same listening port.
        folder = Path(tempfile.gettempdir()) / "clipfoundry-unattended-ports"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{self.name}.lock"


def _port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as listener:
            if sys.platform == "win32":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                # Match uvicorn's POSIX reuse of TIME_WAIT sockets without sharing an active listener.
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((host, port))
        return True
    except OSError:
        return False


class _WindowsJob:
    """The OS kills the app and all its descendants if the watchdog exits, including a forced console close."""

    def __init__(self) -> None:
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("user_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", wintypes.DWORD),
                        ("minimum", ctypes.c_size_t), ("maximum", ctypes.c_size_t), ("active", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                        ("peak_job", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; descendants cannot break away.
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def assign(self, proc: subprocess.Popen) -> None:
        if not self.kernel.AssignProcessToJobObject(self.handle, int(proc._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def child_gate() -> bool:
    """Start no app/worker until the parent has established ownership of the complete process tree."""
    if sys.stdin.readline() != "start\n":
        return False
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    return True


class AppChild:
    def __init__(self, command: list[str], env: dict[str, str], logger: logging.Logger):
        self.job: _WindowsJob | None = None
        self.proc: subprocess.Popen | None = None
        self.reader: threading.Thread | None = None
        try:
            if sys.platform == "win32":
                self.job = _WindowsJob()
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            self.proc = subprocess.Popen(command, cwd=str(config.ROOT_DIR), env=env, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags,
                                         start_new_session=sys.platform != "win32", bufsize=0)
            if self.job:
                self.job.assign(self.proc)
            self.reader = threading.Thread(target=self._read, args=(logger,), daemon=True, name="cf-app-output")
            self.reader.start()
            self.proc.stdin.write(b"start\n")
            self.proc.stdin.close()
        except BaseException:
            self.stop(graceful=False)
            raise

    def _read(self, logger: logging.Logger) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while chunk := os.read(self.proc.stdout.fileno(), 2048):
                logger.info("%s", decoder.decode(chunk).rstrip("\r\n"))
            tail = decoder.decode(b"", final=True)
            if tail:
                logger.info("%s", tail)
        except (OSError, ValueError):
            pass

    def poll(self) -> int | None:
        return self.proc.poll()

    def stop(self, graceful: bool = True) -> None:
        proc = self.proc
        if proc is None:
            if self.job:
                self.job.close()
            return
        if graceful and proc.poll() is None:
            try:
                if sys.platform == "win32":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if self.job:
            self.job.close()
        elif sys.platform != "win32":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        if self.reader:
            self.reader.join(timeout=5)
        if proc.stdout:
            proc.stdout.close()
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()


def _logger(folder: Path) -> tuple[logging.Logger, logging.Handler]:
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.Logger("clipfoundry.unattended", level=logging.INFO)
    handler = RotatingFileHandler(folder / "unattended.log", maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    return logger, handler


def _supervise(command: list[str], env: dict[str, str], logger: logging.Logger, stop: threading.Event,
               host: str, port: int, *, spawn: Callable = AppChild, clock: Callable = time.monotonic) -> int:
    delay = MIN_RESTART_SECONDS
    while not stop.is_set():
        if not _port_available(host, port):
            logger.error("Port %s is already in use; stopped without starting another app.", port)
            print(f"Port {port} is already in use. Stop the other app before starting unattended mode.", flush=True)
            return 2
        started = clock()
        child = None
        try:
            child = spawn(command, env, logger)
            logger.info("Started app process.")
            while child.poll() is None and not stop.wait(0.25):
                pass
            if stop.is_set():
                return 0
            result = child.poll()
        except OSError as exc:
            # Paths/accounts/URLs from arbitrary exception strings do not enter the status log.
            logger.error("App could not start (%s).", type(exc).__name__)
            result = "startup error"
        finally:
            if child:
                child.stop(graceful=stop.is_set())
        if stop.is_set():
            return 0
        if clock() - started >= STABLE_SECONDS:
            delay = MIN_RESTART_SECONDS
        logger.warning("App exited (%s); restarting in %.0f seconds.", result, delay)
        print(f"App exited; restarting in {delay:.0f} seconds. Ctrl+C stops unattended mode.", flush=True)
        if stop.wait(delay):
            return 0
        delay = min(MAX_RESTART_SECONDS, delay * 2)
    return 0


def run(host: str, port: int, open_browser: bool = False) -> int:
    if not 1 <= port <= 65535:
        print("Choose a port between 1 and 65535.")
        return 2
    profile = config.data_dir().resolve()
    profile_lock = locks.named("unattended-app")
    port_lock = _PortLock(hashlib.sha256(f"port:{port}".encode()).hexdigest()[:20])
    acquired: list[locks.FileLock] = []
    handler = None
    browser_timer = None
    old_signals = {}
    stop = threading.Event()
    try:
        for lock in (profile_lock, port_lock):
            if not lock.acquire(timeout=0, poll=0.01):
                print("Unattended mode is already running for this data folder or port.")
                return 2
            acquired.append(lock)
        logger, handler = _logger(profile / "logs")
        for signum in (signal.SIGINT, signal.SIGTERM):
            old_signals[signum] = signal.signal(signum, lambda *_: stop.set())
        env = {**os.environ, "CLIPFOUNDRY_DATA": str(profile), "CLIPFOUNDRY_PORT": str(port), "PYTHONUNBUFFERED": "1"}
        command = [sys.executable, "-m", "clipfoundry", "--host", host, "--port", str(port), "--unattended-child"]
        print(f"ClipFoundry unattended mode; logs: {profile / 'logs' / 'unattended.log'}\n"
              "Leave this window open. Ctrl+C stops the app and its workers.", flush=True)
        if open_browser:
            import webbrowser

            browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else (f"[{host}]" if ":" in host else host)
            browser_timer = threading.Timer(1.5, lambda: webbrowser.open(f"http://{browser_host}:{port}"))
            browser_timer.daemon = True
            browser_timer.start()
        return _supervise(command, env, logger, stop, host, port)
    except OSError as exc:
        print(f"Unattended mode could not start ({type(exc).__name__}). Check folder permissions and setup.")
        return 2
    finally:
        stop.set()
        if browser_timer:
            browser_timer.cancel()
        for signum, previous in old_signals.items():
            signal.signal(signum, previous)
        if handler:
            handler.close()
        for lock in reversed(acquired):
            lock.release()

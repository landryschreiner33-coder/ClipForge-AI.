"""Cross-process locks on files in the data folder.

The app and the autopilot worker process share the GPU, the platform tokens and the worker host role. A lock file
held with an OS-level lock (msvcrt on Windows, flock elsewhere) is released automatically when its process exits,
even after a crash, so a stuck lock never outlives its owner.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from . import config

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


def lock_dir() -> Path:
    d = config.data_dir() / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


class FileLock:
    """An exclusive lock shared by all threads and processes that use the same name (not re-entrant)."""

    def __init__(self, name: str):
        self.name = name
        self._thread_lock = threading.Lock()
        self._fd: int | None = None

    @property
    def path(self) -> Path:
        return lock_dir() / f"{self.name}.lock"

    def acquire(self, timeout: float | None = None, poll: float = 0.25,
                cancelled: Callable[[], bool] | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._thread_lock.acquire(timeout=poll):
            if (cancelled and cancelled()) or (deadline is not None and time.monotonic() >= deadline):
                return False
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")  # msvcrt locks a byte range, so the file needs one byte
            while not _try_lock(fd):
                if (cancelled and cancelled()) or (deadline is not None and time.monotonic() >= deadline):
                    raise TimeoutError
                time.sleep(poll)
        except TimeoutError:
            os.close(fd)
            self._thread_lock.release()
            return False
        except BaseException:
            os.close(fd)
            self._thread_lock.release()
            raise
        self._fd = fd
        return True

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            _unlock(fd)
            os.close(fd)
            self._thread_lock.release()

    def held_elsewhere(self) -> bool:
        """True when another thread or process holds the lock right now (a quick, non-blocking probe)."""
        if not self.acquire(timeout=0, poll=0.01):
            return True
        self.release()
        return False

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


_named: dict[tuple[str, str], FileLock] = {}
_named_lock = threading.Lock()


def named(name: str) -> FileLock:
    """One FileLock object per name and data folder in this process (so threads share its thread lock)."""
    key = (str(config.data_dir()), name)
    with _named_lock:
        if key not in _named:
            _named[key] = FileLock(name)
        return _named[key]

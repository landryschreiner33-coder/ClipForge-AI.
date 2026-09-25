"""Shared helpers for the processing pipeline."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("clipfoundry")


class Cancelled(Exception):
    """Raised inside a job when the user cancels it."""


class JobContext:
    """Progress + cancellation plumbing handed to every pipeline stage."""

    def __init__(
        self,
        report: Callable[[float, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ):
        self._report = report or (lambda p, m: None)
        self._is_cancelled = is_cancelled or (lambda: False)

    def cancelled(self) -> bool:
        return self._is_cancelled()

    def check(self) -> None:
        if self._is_cancelled():
            raise Cancelled()

    def progress(self, fraction: float, message: str = "") -> None:
        self._report(max(0.0, min(1.0, fraction)), message)

    def sub(self, lo: float, hi: float, message: str = "") -> Callable[[float], None]:
        """Callback mapping a 0..1 sub-task onto [lo, hi] of the overall job."""

        def cb(frac: float) -> None:
            self.progress(lo + (hi - lo) * max(0.0, min(1.0, frac)), message)

        return cb


def write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def fmt_ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

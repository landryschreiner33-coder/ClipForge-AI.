"""Keeping the PC awake while Autopilot works.

Windows puts an idle PC to sleep after a while (often 15 to 30 minutes), and a sleeping PC finds, clips and posts
nothing, so a night of Autopilot used to end soon after the user walked away. While Autopilot is on, ClipFoundry asks
Windows to keep the system running (the screen may still turn off). It is the documented SetThreadExecutionState
request: it lasts only while ClipFoundry runs and ends by itself when ClipFoundry closes or crashes. It cannot stop a
laptop from sleeping when its lid is closed, or the PC from sleeping when someone chooses Sleep.

Elsewhere (macOS, Linux) nothing is changed: the request is Windows only.
"""
from __future__ import annotations

import sys
import threading
import time

from .pipeline.common import log

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class KeepAwake:
    """The request is per thread, so one thread owns it: call hold() from the same long-lived thread every time.

    `holding` is only true once Windows accepted the request. When Windows refuses it, `error` says so, the page
    shows it with what to do instead, and the request is tried again after `retry_seconds` (not on every check)."""

    retry_seconds = 60.0

    def __init__(self) -> None:
        self.holding = False
        self.supported = sys.platform == "win32"
        self.error = ""  # why the last request to keep the PC awake failed; "" once one succeeds or it is not wanted
        self.clock = time.monotonic
        self._retry_at = 0.0
        self._owner: int | None = None

    def hold(self, on: bool) -> bool:
        """Ask for (or give up) keeping the PC awake. Returns whether it is kept awake now."""
        if not self.supported:
            return False
        if on == self.holding:
            if not on:  # not wanted any more: an earlier refusal no longer matters
                self.error, self._retry_at = "", 0.0
            return self.holding
        me = threading.get_ident()
        if self._owner not in (None, me):
            log.warning("keep-awake: hold() called from a different thread; ignoring")
            return self.holding
        if self.clock() < self._retry_at:
            return self.holding  # refused a moment ago: try again later, not every few seconds
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
        try:
            import ctypes

            ok = ctypes.windll.kernel32.SetThreadExecutionState(flags)  # type: ignore[attr-defined]
            why = "" if ok else "Windows did not accept the request"
        except (AttributeError, OSError) as exc:
            ok, why = 0, f"Windows could not be asked ({exc})"
        if not ok:
            if on and not self.error:
                log.warning("keep-awake: %s", why)
            if on:
                self.error = why
            self._retry_at = self.clock() + self.retry_seconds
            return self.holding
        self.holding, self._owner, self.error, self._retry_at = on, (me if on else None), "", 0.0
        return self.holding

    def status(self, wanted: bool) -> str:
        """What the page says: "unsupported" (not Windows), "off" (Autopilot or the setting is off), "on" (Windows
        accepted), "failed" (Windows refused; tried again every minute) or "pending" (not asked yet: the app checks
        every few seconds)."""
        if not self.supported:
            return "unsupported"
        if not wanted:
            return "off"
        if self.holding:
            return "on"
        return "failed" if self.error else "pending"


keeper = KeepAwake()

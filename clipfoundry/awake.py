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

from .pipeline.common import log

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


class KeepAwake:
    """The request is per thread, so one thread owns it: call hold() from the same long-lived thread every time."""

    def __init__(self) -> None:
        self.holding = False
        self.supported = sys.platform == "win32"
        self._owner: int | None = None

    def hold(self, on: bool) -> bool:
        """Ask for (or give up) keeping the PC awake. Returns whether it is kept awake now."""
        if not self.supported:
            return False
        if on == self.holding:
            return self.holding
        me = threading.get_ident()
        if self._owner not in (None, me):
            log.warning("keep-awake: hold() called from a different thread; ignoring")
            return self.holding
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
        try:
            import ctypes

            ok = ctypes.windll.kernel32.SetThreadExecutionState(flags)  # type: ignore[attr-defined]
        except (AttributeError, OSError) as exc:
            log.warning("keep-awake: Windows did not accept the request (%s)", exc)
            self.supported = False
            return False
        if not ok:
            log.warning("keep-awake: Windows did not accept the request")
            return self.holding
        self.holding, self._owner = on, (me if on else None)
        return self.holding


keeper = KeepAwake()

"""The one background job that sets up the local makers (downloads, ClipForge's own ComfyUI), so Settings can show
its progress, the person can keep working, and Cancel stops it at the next block of bytes.

A job is a list of steps; each step is a function `step(report, cancelled)` where `report(status, done, total)` tells
how far it is and `cancelled()` says whether to stop. One job runs at a time.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from . import EngineError

log = logging.getLogger(__name__)

Report = Callable[[str, int, int], None]
Step = Callable[[Report, Callable[[], bool]], None]

_lock = threading.Lock()
_cancel = threading.Event()
_state: dict = {"state": "idle", "what": "", "status": "", "done": 0, "total": 0, "error": "", "step": 0, "steps": 0,
                "started_at": 0.0, "updated_at": 0.0}


def view() -> dict:
    with _lock:
        return dict(_state)


def running() -> bool:
    with _lock:
        return _state["state"] == "running"


def _set(**fields) -> None:
    with _lock:
        _state.update(fields, updated_at=time.time())


def cancel() -> dict:
    _cancel.set()
    return view()


def stop(timeout_s: float = 15.0) -> None:
    """ClipForge is closing: stop a set-up under way and give it a moment to stop what it started (a download, or
    uv installing), so nothing keeps working on with nothing in ClipForge showing it."""
    if not running():
        return
    _cancel.set()
    deadline = time.monotonic() + timeout_s
    while running() and time.monotonic() < deadline:
        time.sleep(0.1)


def start(what: str, steps: list[Step], on_done: Callable[[], None] | None = None, wait: bool = False) -> dict:
    """Run `steps` in a background thread (`wait`: in this thread, for checks and tests)."""
    with _lock:
        if _state["state"] == "running":
            raise EngineError(f"{_state['what'] or 'A set-up'} is already running; wait for it to finish or cancel it.")
        _cancel.clear()
        _state.update(state="running", what=what, status="Starting", done=0, total=0, error="", step=0,
                      steps=len(steps), started_at=time.time(), updated_at=time.time())

    def report(status: str, done: int, total: int) -> None:
        _set(status=status, done=int(done), total=int(total))

    def run() -> None:
        try:
            for i, step in enumerate(steps, 1):
                _set(step=i)
                if _cancel.is_set():
                    raise EngineError("Stopped.")
                step(report, _cancel.is_set)
            if on_done:
                try:
                    on_done()
                except Exception:  # noqa: BLE001 - the set-up worked; choosing it can be done by hand
                    log.exception("after setting up %s", what)
            _set(state="done", status="Ready", done=0, total=0)
        except Exception as exc:  # noqa: BLE001 - every failure is shown to the person in plain words
            stopped = _cancel.is_set()
            message = str(exc)[:400] if isinstance(exc, EngineError) else f"{exc.__class__.__name__}: {str(exc)[:300]}"
            _set(state="canceled" if stopped else "failed", status="Stopped" if stopped else "Failed",
                 error="" if stopped else message)
            if not stopped:
                log.warning("setting up %s stopped: %s", what, exc, exc_info=not isinstance(exc, EngineError))

    if wait:
        run()
    else:
        threading.Thread(target=run, daemon=True, name="engines-setup").start()
    return view()


def reset_for_tests() -> None:
    _cancel.clear()
    with _lock:
        _state.update(state="idle", what="", status="", done=0, total=0, error="", step=0, steps=0)

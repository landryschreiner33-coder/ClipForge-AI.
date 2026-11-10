"""The day's allowance of requests to an online AI ("AI requests a day" in Settings → Advanced,
`ai_edit_requests_per_day`; 0 means never send one). Every request ClipForge AI, its helper agents and the editor's
change requests send to an online model counts, one by one: one answer can be several requests (its rounds, and the
rounds of the helpers it asks), and the new-video planner's requests (studio/video_setup.py) and its notes from helper
agents count too. A model on this computer is never counted or limited (the editor keeps its own limit of its
requests to it, as always).

Each request ClipForge AI, a helper or the planner sends is one row of `ai_usage` with provider
"clipforge_ai:<workspace>" (the local day it counts against, its task: chat, helper, helper_note or video_plan, the
model and the chat message or video it was for); a change request the editor sends is its own `edit_requests` row
(source ai), as before.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

from .. import db

T = TypeVar("T")

PROVIDER = "clipforge_ai"
SENT_ONLINE = "Sent over the internet"  # how an editor's request to an online AI starts its `sent` line
_lock = threading.Lock()


class Reached(Exception):
    """Today's allowance is used up: nothing more is sent. The message says so in plain words."""


def _day() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _day_start() -> float:
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def online(settings: dict) -> bool:
    """True when the model answering is an online service (counted); False for one on this computer."""
    from ..pipeline import llm

    return not llm.is_local(settings)


def limit(settings: dict) -> int:
    return max(0, int(settings.get("ai_edit_requests_per_day", 40) or 0))


def used(ws: str) -> int:
    """Requests sent to an online AI today in this workspace: ClipForge AI's, its helpers' and the editor's (an
    editor request to a model on this computer is not one of them)."""
    mine = int(db.scalar("SELECT COUNT(*) FROM ai_usage WHERE provider = ? AND day = ?",
                         (f"{PROVIDER}:{ws}", _day())) or 0)
    edits = int(db.scalar("SELECT COUNT(*) FROM edit_requests WHERE workspace_id = ? AND source = 'ai' AND "
                          "created_at >= ? AND sent LIKE ?", (ws, _day_start(), SENT_ONLINE + "%")) or 0)
    return mine + edits


def message(settings: dict) -> str:
    return (f"Today's limit of {limit(settings)} requests to your online AI is reached (Settings → Advanced, "
            "“AI requests a day”).")


def reached(ws: str, settings: dict) -> bool:
    """True when nothing more may be sent to the online AI today (always False for a model on this computer)."""
    return online(settings) and used(ws) >= limit(settings)


def counted(ws: str, settings: dict, write: Callable[[], T]) -> T:
    """Check today's allowance and run `write()`, which writes the row that counts one request to the online AI (the
    editor's change request), as one step: raises Reached, writing nothing, when the allowance is used up. Every part
    counts under the same lock, so two parts asking at the same moment never send one more than the limit."""
    with _lock:
        if used(ws) >= limit(settings):
            raise Reached(message(settings))
        return write()


def take(ws: str, settings: dict, task: str, ref: str = "") -> None:
    """Count one request that is about to be sent to the online AI, or raise Reached (and send nothing) when today's
    allowance is used up. A model on this computer is free: nothing is counted."""
    if not online(settings):
        return
    from ..pipeline import llm

    counted(ws, settings, lambda: db.insert("ai_usage", {
        "provider": f"{PROVIDER}:{ws}", "day": _day(), "job_id": str(ref or ""), "task": task,
        "model": llm.provider_label(settings), "status": "done"}))

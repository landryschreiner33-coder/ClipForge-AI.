"""REST endpoints for the office: the cast, one snapshot, the event feed after a cursor, reports, decisions, health,
one room's details, and the bottom-bar controls. Reads are local-only; controls only work from ClipFoundry's page."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..publish.common import app_request, local_only
from . import feed, health, roles, view

router = APIRouter(prefix="/api/office")
READ = [Depends(local_only)]
WRITE = [Depends(app_request)]


@router.get("/roles", dependencies=READ)
def cast() -> dict:
    """The fixed cast: Director COMMAND, 8 managers and 16 workers (plus CORE, the Brain room's core)."""
    return {"roles": roles.public(), "core": roles.CORE, "rooms": roles.ROOMS, "departments": roles.DEPARTMENTS,
            "problems": roles.validate()}


@router.get("/snapshot", dependencies=READ)
def snapshot() -> dict:
    return view.snapshot()


@router.get("/events", dependencies=READ)
def events(after: int = 0, limit: int = 200) -> dict:
    return feed.events_after(after, limit)


@router.get("/decisions", dependencies=READ)
def decisions(point: str = "", subject_type: str = "", subject_id: str = "", limit: int = 50) -> list[dict]:
    where, args = [], []
    for col, val in (("point", point), ("subject_type", subject_type), ("subject_id", subject_id)):
        if val:
            where.append(f"{col} = ?")
            args.append(val)
    return db.select("office_decisions", " AND ".join(where), args, "created_at DESC", max(1, min(200, limit)))


@router.get("/reports", dependencies=READ)
def reports(manager: str = "", limit: int = 50) -> list[dict]:
    return db.select("office_reports", "manager = ?" if manager else "", (manager,) if manager else (),
                     "created_at DESC", max(1, min(200, limit)))


@router.get("/health", dependencies=READ)
def health_check() -> dict:
    return health.check()


@router.get("/rooms/{room_id}", dependencies=READ)
def room(room_id: str) -> dict:
    try:
        return view.room(room_id)
    except KeyError:
        raise HTTPException(404, "There is no such room.") from None


@router.get("/devlog", dependencies=READ)
def devlog(limit: int = 50) -> list[dict]:
    return view.devlog(max(1, min(500, limit)))


class ControlBody(BaseModel):
    action: Literal["start", "pause", "resume", "stop", "pause_publishing", "resume_publishing"]


CONTROL_TEXT = {
    "start": "Autopilot started", "pause": "Autopilot paused: running steps finish, nothing new starts",
    "resume": "Autopilot resumed", "stop": "Stop all: queued work canceled and held until you start again",
    "pause_publishing": "Publishing paused: clips are still made and checked, nothing new is uploaded",
    "resume_publishing": "Publishing resumed: due posts go out at their next check",
}


@router.post("/control", dependencies=WRITE)
def control(body: ControlBody) -> dict:
    """The bottom bar. Only the actions that fit the current state are accepted (no Pause while stopped), and each
    one uses the same code as the existing Autopilot buttons, so nothing here skips a check."""
    from ..autopilot import home, state
    from ..autopilot import routes as ap

    a = body.action
    settings = db.get_settings()
    if a in ("pause_publishing", "resume_publishing"):
        paused = a == "pause_publishing"
        db.save_settings({"autopilot_publishing_paused": paused})
        if not paused:
            ap._manual("schedule_tick")  # due posts are dispatched now, not at the next minute
    else:
        run = view.run_state(settings)
        if a not in run["actions"]:
            raise HTTPException(409, f"Autopilot is {run['label'].lower()}, so {a} does not apply. "
                                     f"Use: {', '.join(run['actions'])}.")
        if a == "stop":
            ap.stop_all()
        elif a == "pause":
            ap.enable(ap.EnableBody(enabled=False))
        else:  # start, resume
            if state.paused():
                ap.resume()
            if home.started_before():
                ap.enable(ap.EnableBody(enabled=True))
            else:
                ap.start()
    state.event(f"office_{a}", CONTROL_TEXT[a])
    feed.emit("control", "command", message=CONTROL_TEXT[a], action=a)
    return view.snapshot()

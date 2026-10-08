"""REST API for the Office screen: snapshot + event cursor, controls, health, and the read-only Dev Log."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db, health, office
from .publish.common import app_request, local_only

router = APIRouter()
READ = [Depends(local_only)]
WRITE = [Depends(app_request)]
REPO = Path(__file__).resolve().parents[1]


@router.get("/api/office", dependencies=READ)
def office_snapshot() -> dict:
    return office.snapshot()


@router.get("/api/office/events", dependencies=READ)
def office_events(after: int = 0, limit: int = 200) -> dict:
    return office.events(after, max(1, min(500, limit)))


@router.get("/api/system/health", dependencies=READ)
def system_health() -> dict:
    return health.summary()


class ControlBody(BaseModel):
    action: str  # start pause resume stop pause_publishing resume_publishing


@router.post("/api/office/control", dependencies=WRITE)
def control(body: ControlBody) -> dict:
    """The bottom control bar. Each action is the existing durable control, so repeated clicks reuse the current
    run and never reset budgets or skip a check."""
    from .autopilot import routes as ap
    from .autopilot import state

    a = body.action
    if a == "start":
        if state.paused():
            ap.resume()
        ap.start(None)
    elif a == "pause":
        ap.enable(ap.EnableBody(enabled=False))
    elif a == "resume":
        if state.paused():
            ap.resume()
        ap.enable(ap.EnableBody(enabled=True))
    elif a == "stop":
        ap.stop_all()
        db.save_settings({"autopilot_enabled": False})
    elif a in ("pause_publishing", "resume_publishing"):
        db.save_settings({"autopilot_publish_paused": a == "pause_publishing"})
        state.event("publishing_paused" if a == "pause_publishing" else "publishing_resumed",
                    "Publishing paused: local clips keep being made" if a == "pause_publishing"
                    else "Publishing resumed")
    else:
        raise HTTPException(400, f"Unknown action {a!r}")
    settings = db.get_settings()
    return {"run_state": office.run_state(settings), "publishing_paused": bool(settings["autopilot_publish_paused"])}


@router.get("/api/devlog", dependencies=READ)
def devlog(limit: int = 100) -> dict:
    """Read-only development history (AI_CHANGELOG.md and the machine-readable log), when installed from source."""
    entries = []
    log = REPO / ".clipfoundry" / "ai-change-log.jsonl"
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines()[-max(1, min(500, limit)):]:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    md = REPO / "AI_CHANGELOG.md"
    return {"entries": list(reversed(entries)), "changelog": md.read_text(encoding="utf-8")[:200_000]
            if md.is_file() else "", "available": log.is_file() or md.is_file()}

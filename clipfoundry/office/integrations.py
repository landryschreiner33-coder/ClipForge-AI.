"""REST endpoints for Settings → Integrations: the cards, the capability registry, and the optional NVIDIA AI
(explicit opt-in, a check that generates nothing, an explicit small test, and disconnect)."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..pipeline import nvidia
from ..publish.common import app_request, local_only
from . import capabilities

router = APIRouter(prefix="/api/integrations")
READ = [Depends(local_only)]
WRITE = [Depends(app_request)]


@router.get("", dependencies=READ)
def cards() -> dict:
    return {"cards": capabilities.cards(), "registry": capabilities.matrix()}


@router.get("/nvidia", dependencies=READ)
def nvidia_view() -> dict:
    return nvidia.view(db.get_settings())


class OptIn(BaseModel):
    agree: bool


@router.post("/nvidia/opt-in", dependencies=WRITE)
def nvidia_opt_in(body: OptIn) -> dict:
    """The explicit agreement that approved excerpts leave this PC (withdrawn with agree=false)."""
    db.save_settings({"nvidia_opt_in_at": time.time() if body.agree else 0.0})
    return nvidia.view(db.get_settings())


@router.post("/nvidia/check", dependencies=WRITE)
def nvidia_check() -> dict:
    return nvidia.check(db.get_settings())


@router.post("/nvidia/test", dependencies=WRITE)
def nvidia_test() -> dict:
    settings = db.get_settings()
    if settings.get("ai_provider") != "nvidia":
        raise HTTPException(409, "Choose NVIDIA AI as the AI provider first.")
    return nvidia.small_test(settings)


@router.post("/nvidia/disconnect", dependencies=WRITE)
def nvidia_disconnect() -> dict:
    return nvidia.disconnect()

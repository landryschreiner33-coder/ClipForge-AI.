"""REST endpoints for Settings → Integrations: the cards, the capability registry, Test connection for YouTube and
TikTok (one read, nothing uploaded or changed), and the optional NVIDIA AI (explicit opt-in, a check that generates
nothing, an explicit small test, and disconnect)."""
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


def _test(platform: str) -> dict:
    """Test connection (only from ClipFoundry's page on this PC): one read on the platform with the connected
    account. It never uploads, posts or changes anything there, and it costs no money."""
    if not (db.get_account(platform) or {}).get("has_tokens"):
        raise HTTPException(409, f"Connect {'YouTube' if platform == 'youtube' else 'TikTok'} first.")
    return capabilities.test_connection(platform)


@router.post("/youtube/test", dependencies=WRITE)
def youtube_test() -> dict:
    return _test("youtube")


@router.post("/tiktok/test", dependencies=WRITE)
def tiktok_test() -> dict:
    return _test("tiktok")


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

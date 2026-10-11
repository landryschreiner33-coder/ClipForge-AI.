"""REST endpoints for the Brain: its state, test feedback (form and CSV import), strategies and rollback."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..publish.common import app_request, local_only
from . import brain

router = APIRouter(prefix="/api/brain")
READ = [Depends(local_only)]
WRITE = [Depends(app_request)]


@router.get("", dependencies=READ)
def status() -> dict:
    return {**brain.summary(), "history": brain.history(20), "fields": {
        "metrics": {k: {"label": v[0], "unit": v[1]} for k, v in brain.METRICS.items()},
        "ratings": brain.RATINGS, "provenance": brain.PROVENANCE_LABELS, "cohorts": brain.COHORT_LABELS}}


@router.get("/feedback-clips", dependencies=READ)
def feedback_clips() -> list[dict]:
    return brain.feedback_clips()


@router.get("/clips/{clip_id}", dependencies=READ)
def clip(clip_id: str) -> dict:
    if not db.get_clip(clip_id):
        raise HTTPException(404, "That clip does not exist")
    return brain.clip_results(clip_id)


class ObservationIn(BaseModel):
    clip_id: str
    platform: str = ""
    provenance: Literal["owner_import", "tester_feedback"]  # platform_api readings come only from the API
    values: dict
    observed_at: float | None = None
    tester: str = ""
    note: str = ""


@router.post("/observations", dependencies=WRITE)
def add(body: ObservationIn) -> dict:
    try:
        return brain.add(body.clip_id, body.platform, body.provenance, body.values, observed_at=body.observed_at,
                         tester=body.tester, note=body.note, origin="form")
    except brain.Invalid as exc:
        raise HTTPException(422, str(exc)) from None


class ImportIn(BaseModel):
    text: str
    provenance: Literal["owner_import", "tester_feedback"] = "owner_import"
    platform: str = ""
    observed_at: float | None = None
    filename: str = "import.csv"


@router.post("/import/preview", dependencies=WRITE)
def import_preview(body: ImportIn) -> dict:
    try:
        return brain.preview(body.text, body.provenance, body.platform, body.observed_at)
    except brain.Invalid as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/import", dependencies=WRITE)
def import_file(body: ImportIn) -> dict:
    try:
        return brain.import_csv(body.text, body.provenance, body.platform, body.observed_at, body.filename)
    except brain.Invalid as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/strategies/{strategy_id}/rollback", dependencies=WRITE)
def rollback(strategy_id: str) -> dict:
    try:
        return brain.rollback(strategy_id)
    except brain.Invalid as exc:
        raise HTTPException(409, str(exc)) from None


class ResetIn(BaseModel):
    platform: str = ""


@router.post("/reset", dependencies=WRITE)
def reset(body: ResetIn) -> dict:
    return brain.reset(body.platform)


class PauseIn(BaseModel):
    paused: bool


@router.post("/pause", dependencies=WRITE)
def pause(body: PauseIn) -> dict:
    db.save_settings({"brain_paused": body.paused})
    return brain.summary()

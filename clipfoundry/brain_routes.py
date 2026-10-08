"""REST API for the Brain: test feedback (manual form and CSV import), its state, and strategy rollback."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import brain, db
from .publish.common import app_request, local_only

router = APIRouter(prefix="/api/brain")
READ = [Depends(local_only)]  # viewer evidence stays on this PC
WRITE = [Depends(app_request)]


class FeedbackBody(BaseModel):
    clip_id: str
    platform: str
    provenance: str = "owner_import"          # owner_import (numbers from a platform screen) or tester_feedback
    metrics: dict[str, float | None] = {}     # owner_import: views, avg_view_percentage, ...
    ratings: dict[str, float | None] = {}     # tester_feedback: hook, context, payoff, captions, overall (1-5)
    tester_id: str = ""
    comment: str = ""
    stopped_at_s: float | None = None
    observed_at: float | None = None
    sample_size: int | None = None


class CsvBody(BaseModel):
    text: str
    filename: str = ""


def _problem(exc: Exception) -> HTTPException:
    return HTTPException(400, str(exc))


@router.get("", dependencies=READ)
def brain_view() -> dict:
    return brain.view(db.get_settings())


@router.get("/clips/{clip_id}", dependencies=READ)
def clip_feedback(clip_id: str) -> dict:
    if not db.get_clip(clip_id):
        raise HTTPException(404, "Clip not found")
    return {**brain.clip_status(clip_id), "items": brain.current("clip_id = ?", (clip_id,)),
            "labels": brain.PROVENANCE_LABELS}


@router.post("/feedback", dependencies=WRITE)
def add_feedback(body: FeedbackBody) -> dict:
    settings = db.get_settings()
    try:
        if body.provenance == "tester_feedback":
            rows = brain.record_tester(body.clip_id, body.platform, body.ratings, settings, body.tester_id,
                                       body.comment, body.stopped_at_s)
        elif body.provenance == "owner_import":
            if not any(v is not None for v in body.metrics.values()):
                raise brain.ImportProblem("Enter at least one number you read on the platform")
            rows = [brain.record(body.clip_id, body.platform, "owner_import", m, v, settings=settings,
                                 observed_at=body.observed_at, sample_size=body.sample_size, note=body.comment)
                    for m, v in body.metrics.items() if v is not None]
        else:  # platform_api evidence only ever comes from the platform itself
            raise brain.ImportProblem("Only your imported numbers or tester feedback can be entered by hand")
    except brain.ImportProblem as exc:
        raise _problem(exc) from exc
    return {"stored": sum(not r.get("duplicate") for r in rows), "duplicates": sum(bool(r.get("duplicate"))
                                                                                    for r in rows)}


@router.post("/import/preview", dependencies=WRITE)
def import_preview(body: CsvBody) -> dict:
    try:
        out = brain.preview_csv(body.text, db.get_settings())
    except brain.ImportProblem as exc:
        raise _problem(exc) from exc
    return {**out, "rows": out["rows"][:200]}


@router.post("/import/commit", dependencies=WRITE)
def import_commit(body: CsvBody) -> dict:
    try:
        return brain.commit_csv(body.text, db.get_settings(), body.filename)
    except brain.ImportProblem as exc:
        raise _problem(exc) from exc


@router.post("/evaluate", dependencies=WRITE)
def evaluate() -> dict:
    return {"results": brain.evaluate_all(db.get_settings())}


@router.post("/strategy/{version_id}/rollback", dependencies=WRITE)
def rollback(version_id: str) -> dict:
    try:
        return brain.rollback(version_id)
    except ValueError as exc:
        raise _problem(exc) from exc

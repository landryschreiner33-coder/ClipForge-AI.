"""Check a video: the viral predictor on any short video the owner uploads (a draft, an edit made in another app, a
video they want to compare with). A durable, cancelable studio job transcribes it on this computer (the same speech
model as everything else, reused per file), measures its picture and sound, and keeps the prediction with the check.
The video stays private and is never sent anywhere; deleting a check keeps the file in the owner's media.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from .. import db
from ..studio import uploads
from ..studio.jobs import Canceled, Lease, cancel as cancel_job, enqueue, handler, on_stop

log = logging.getLogger(__name__)
KIND = "viral_check"
MAX_SECONDS = 10 * 60  # the predictor is made for short videos: a longer one is better made into clips first
MAX_TITLE = 120


class CheckError(ValueError):
    status = 422


class NotFound(CheckError):
    status = 404


def get(check_id: str, workspace_id: str) -> dict:
    row = db.fetch("viral_checks", check_id)
    if not row or row["workspace_id"] != workspace_id:
        raise NotFound("Check not found.")
    return row


def view(row: dict, full: bool = True) -> dict:
    from . import summary

    result = row.get("result") or None
    out = {k: row[k] for k in ("id", "title", "status", "message", "error", "created_at", "updated_at")}
    out["media_url"] = f"/api/assets/{row['asset_id']}/media"
    out["summary"] = summary(result) if result else None
    if full:
        out["result"] = result
    return out


def list_for(workspace_id: str) -> list[dict]:
    rows = db.select("viral_checks", "workspace_id = ?", (workspace_id,), "updated_at DESC", limit=100)
    return [view(r, full=False) for r in rows]


def create(workspace_id: str, asset_id: str, title: str = "", upload_ids=None) -> dict:
    try:
        asset = uploads.asset(asset_id, workspace_id)
    except uploads.UploadError as exc:
        raise NotFound(str(exc)) from exc
    if asset["kind"] != "video":
        raise CheckError("Choose a video file to check.")
    duration = float((asset.get("probe") or {}).get("duration") or 0)
    if duration > MAX_SECONDS:
        raise CheckError(f"This video is {duration / 60:.0f} minutes long. The predictor is made for short videos "
                         f"(up to {MAX_SECONDS // 60} minutes): make clips from it, and each clip is predicted.")
    name = " ".join((title or Path(asset["filename"]).stem or "Video").split())[:MAX_TITLE]
    row = db.insert("viral_checks", {"id": "vc-" + os.urandom(6).hex(), "workspace_id": workspace_id,
                                     "asset_id": asset_id, "title": name, "status": "queued",
                                     "message": "Waiting to be checked", "round": 1})
    uploads.taken(workspace_id, upload_ids, row["id"], [asset_id])
    enqueue(workspace_id, KIND, row["id"], 1)
    return view(row)


def again(check_id: str, workspace_id: str) -> dict:
    row = get(check_id, workspace_id)
    nxt = int(row.get("round") or 1) + 1
    db.update("viral_checks", check_id, round=nxt, status="queued", message="Waiting to be checked", error="")
    enqueue(workspace_id, KIND, check_id, nxt)
    return view(get(check_id, workspace_id))


def _job(row: dict) -> dict | None:
    rows = db.select("studio_jobs", "idempotency_key = ?", (f"{KIND}:{row['id']}:{row['round']}",))
    return rows[0] if rows else None


def cancel(check_id: str, workspace_id: str) -> dict:
    row = get(check_id, workspace_id)
    job = _job(row)
    if job and job["status"] in ("queued", "running"):
        cancel_job(job["id"])
    if row["status"] in ("queued", "checking"):
        db.update("viral_checks", check_id, status="canceled", message="Canceled")
    return view(get(check_id, workspace_id))


def delete(check_id: str, workspace_id: str) -> dict:
    row = get(check_id, workspace_id)
    job = _job(row)
    if job and job["status"] in ("queued", "running"):
        cancel_job(job["id"])
    db.execute("DELETE FROM viral_checks WHERE id = ?", (check_id,))
    return {"deleted": check_id, "notes": ["The video file stays in your media."]}


def _words(asset: dict, settings: dict, lease: Lease) -> tuple[list[dict] | None, str]:
    """The words heard in the video (None: speech is estimated from the sound), and how they were found."""
    from ..pipeline.common import Cancelled as MediaCancelled
    from ..studio import video_flow

    if not (asset.get("probe") or {}).get("has_audio"):
        return None, "This video has no sound."
    try:
        words = video_flow.transcript_words(asset, settings, lease, lo=0.05, hi=0.5)
    except (Canceled, MediaCancelled):
        raise
    except Exception as exc:  # noqa: BLE001 - without a speech model the picture and sound are still measured
        log.info("check transcript unavailable: %s", exc)
        return None, "Transcription was not available, so speech was estimated from the sound."
    if not words:
        return None, "No words were recognized, so it is judged on its picture and sound."
    return words, "Words from the transcript made on this computer."


@on_stop(KIND)
def _stopped(job: dict, how: str) -> None:
    """A check whose job was canceled or given up says so (its handler may never run again)."""
    row = db.fetch("viral_checks", job.get("target_id") or "")
    if row and int(row.get("round") or 1) == int(job.get("revision") or 0) and row["status"] in ("queued", "checking"):
        db.update("viral_checks", row["id"], status="canceled" if how == "canceled" else "failed",
                  message="Canceled" if how == "canceled" else "Failed",
                  error="" if how == "canceled" else "Stopped after repeated interruptions. Press Check again.")


@handler(KIND)
def check_job(job: dict, lease: Lease) -> dict:
    from . import run, signals

    row = db.fetch("viral_checks", job["target_id"])
    if not row or int(row.get("round") or 1) != int(job["revision"]):
        return {"skipped": "superseded"}
    asset = db.fetch("assets", row["asset_id"])
    if not asset or asset["workspace_id"] != row["workspace_id"] or not Path(asset["path"]).is_file():
        db.update("viral_checks", row["id"], status="failed", message="Failed",
                  error="The video file is missing. Upload it again.")
        raise CheckError("The video file is missing.")
    db.update("viral_checks", row["id"], status="checking", message="Listening to the words", error="")
    settings = db.get_settings()
    try:
        lease.progress(0.02, "Listening to the words")
        words, note = _words(asset, settings, lease)
        db.update("viral_checks", row["id"], message="Watching the picture and sound")
        result = run(asset["path"], words, settings, cancelled=lease.canceled,
                     progress=lambda f, m: lease.progress(0.5 + 0.48 * f, m or "Watching the picture and sound"))
    except signals.ra.Canceled:
        raise Canceled() from None
    except Canceled:
        raise
    except signals.MeasureError as exc:
        db.update("viral_checks", row["id"], status="failed", message="Failed", error=str(exc))
        raise
    except Exception as exc:
        from ..pipeline.common import Cancelled as MediaCancelled

        if isinstance(exc, MediaCancelled):
            raise
        db.update("viral_checks", row["id"], status="failed", message="Failed",
                  error="The video could not be checked: " + str(exc)[:300])
        raise
    result["words_note"] = note
    current = db.fetch("viral_checks", row["id"])
    if not current or current["round"] != row["round"]:
        return {"skipped": "superseded"}
    db.update("viral_checks", row["id"], status="ready", result=result, error="",
              message=f"Viral score {result['score']} ({result['band']})")
    return {"score": result["score"]}

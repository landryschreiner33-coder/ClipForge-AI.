"""Example videos the Brain measures, and the Example styles learned from them.

An example is a private asset (uploaded through the resumable upload system) plus what the owner likes about it.
A durable, cancelable studio job measures it (reference_analysis.py) and caches the result by the file's content
hash, the analyzed ranges, the analyzer version and whether a transcript was available. The owner then saves the
supported choices they want as an Example style: an ordinary style with revisions that also records the example,
the analysis revision, the method and the owner's corrections. The example's own frames and sound never enter a
project; only the saved choices do.

Where an Example style applies (guidance.py):
- an example chosen for one project ("Use an example") ranks right after the project's own choices;
- examples the owner set to apply to every project, or to some project types, rank with the Brain, after skills;
- an example to avoid is never applied, and an example added for one project stays with that project until the
  owner chooses to remember it.
A project keeps the guidance snapshot it was made with, so reanalysis or a later edit never changes queued work.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path

from .. import db
from . import capabilities, reference_analysis as ra, styles, uploads
from .jobs import Canceled, Lease, cancel as cancel_job, enqueue, handler

log = logging.getLogger(__name__)
SCOPES = ("chosen", "all", "modes")
MAX_NOTE = 2000


class ReferenceError(ValueError):
    status = 422


class NotFound(ReferenceError):
    status = 404


class Conflict(ReferenceError):
    status = 409


# ------------------------------------------------------------------ records
def get(ref_id: str, workspace_id: str) -> dict:
    row = db.fetch("reference_videos", ref_id)
    if not row or row["workspace_id"] != workspace_id:
        raise NotFound("Example not found.")
    return row


def _meta(data: dict, current: dict | None = None) -> dict:
    """The owner's answers about an example, validated. Unknown fields are refused, never stored."""
    allowed = {"title", "likes", "note", "avoid", "scope", "modes", "project_only", "enabled"}
    unknown = set(data) - allowed
    if unknown:
        raise ReferenceError("Unknown fields: " + ", ".join(sorted(unknown)))
    out: dict = {}
    if "title" in data:
        title = " ".join(str(data["title"] or "").split())[:120]
        if not title:
            raise ReferenceError("Give the example a name.")
        out["title"] = title
    if "likes" in data:
        likes = data["likes"]
        if not isinstance(likes, list) or any(x not in ra.ASPECTS for x in likes):
            raise ReferenceError("Choose what you like from: " + ", ".join(ra.ASPECTS) + ".")
        out["likes"] = list(dict.fromkeys(likes))
    if "note" in data:
        note = data["note"] if isinstance(data["note"], str) else None
        if note is None or len(note) > MAX_NOTE or "\x00" in note:
            raise ReferenceError(f"Keep the note under {MAX_NOTE} characters.")
        out["note"] = note.strip()
    for flag in ("avoid", "project_only", "enabled"):
        if flag in data:
            if type(data[flag]) is not bool:
                raise ReferenceError(f"{flag.replace('_', ' ').capitalize()} must be true or false.")
            out[flag] = int(data[flag])
    if current and not current.get("project_only") and out.get("project_only") == 1:
        raise ReferenceError("An example you remembered stays in your Brain; disable it instead.")
    if "scope" in data:
        if data["scope"] not in SCOPES:
            raise ReferenceError("Use this example when chosen, for every project, or for some project types.")
        out["scope"] = data["scope"]
    if "modes" in data:
        modes = data["modes"]
        if not isinstance(modes, list) or any(m not in capabilities.MODES for m in modes):
            raise ReferenceError("Choose project types from: " + ", ".join(capabilities.MODES) + ".")
        out["modes"] = list(dict.fromkeys(modes))
    scope = out.get("scope", (current or {}).get("scope", "chosen"))
    modes = out.get("modes", (current or {}).get("modes") or [])
    if scope == "modes" and not modes:
        raise ReferenceError("Choose at least one project type for this example.")
    return out


def create(workspace_id: str, asset_id: str, data: dict, ranges: list | None = None, upload_ids=None) -> dict:
    """A new example of the owner's video file. `upload_ids`: the uploads the Examples page made of the file, which
    become the example's own (uploads.taken), so deleting it with its file tells them from another page's."""
    try:
        asset = uploads.asset(asset_id, workspace_id)
    except uploads.UploadError as exc:
        raise NotFound(str(exc)) from exc
    if asset["kind"] != "video":
        raise ReferenceError("An example must be a video file.")
    meta = _meta({"title": Path(asset["filename"]).stem or "Example", **data})
    clean = ra.clean_ranges(ranges, float((asset.get("probe") or {}).get("duration") or 0))
    row = db.insert("reference_videos", {
        "id": "ref-" + os.urandom(6).hex(), "workspace_id": workspace_id, "asset_id": asset_id,
        "ranges": [] if not ranges else [{"start_ms": int(a * 1000), "end_ms": int(b * 1000)} for a, b in clean],
        "status": "queued", "message": "Waiting to be analyzed", "round": 1, **meta})
    uploads.taken(workspace_id, upload_ids, row["id"], [asset_id])
    enqueue(workspace_id, "reference_analysis", row["id"], 1)
    return view(row)


def update(ref_id: str, workspace_id: str, data: dict) -> dict:
    row = get(ref_id, workspace_id)
    meta = _meta(data, row)
    if meta:
        db.update("reference_videos", ref_id, **meta)
    return view(get(ref_id, workspace_id))


def reanalyze(ref_id: str, workspace_id: str, ranges: list | None = None) -> dict:
    """A new analysis round (a new revision when it finishes). Saved styles keep the revision they were made from
    until the owner saves again, and projects keep their own snapshot."""
    row = get(ref_id, workspace_id)
    asset = uploads.asset(row["asset_id"], workspace_id)
    fields: dict = {"round": row["round"] + 1, "status": "queued", "message": "Waiting to be analyzed", "error": ""}
    if ranges is not None:
        clean = ra.clean_ranges(ranges, float((asset.get("probe") or {}).get("duration") or 0))
        fields["ranges"] = [] if not ranges else [{"start_ms": int(a * 1000), "end_ms": int(b * 1000)}
                                                  for a, b in clean]
    db.update("reference_videos", ref_id, **fields)
    enqueue(workspace_id, "reference_analysis", ref_id, fields["round"])
    return view(get(ref_id, workspace_id))


def cancel(ref_id: str, workspace_id: str) -> dict:
    row = get(ref_id, workspace_id)
    job = _job(row)
    if job and job["status"] in ("queued", "running"):
        cancel_job(job["id"])
    if row["status"] in ("queued", "analyzing"):
        db.update("reference_videos", ref_id, status="canceled",
                  message="Canceled. Press Analyze again to start over." if not row["analysis_revision"] else
                  "Canceled. The previous analysis is still shown.")
    return view(get(ref_id, workspace_id))


def delete(ref_id: str, workspace_id: str, *, keep_style: bool = True, delete_file: bool = False) -> dict:
    """Delete an example and its analyses. Projects already made keep their guidance snapshot (the values and the
    style revision they used), so they still explain and reproduce their plan. The learned style is kept as a
    normal style unless the owner deletes it too; the uploaded file is removed only when asked and nothing else
    uses it."""
    row = get(ref_id, workspace_id)
    job = _job(row)
    if job and job["status"] in ("queued", "running"):
        cancel_job(job["id"])
    style_note = ""
    style = db.fetch("styles", row["style_id"]) if row["style_id"] else None
    if style and style["workspace_id"] == workspace_id:
        if keep_style:
            prov = {**(style.get("provenance") or {}), "reference_deleted_at": time.time()}
            db.update("styles", style["id"], provenance=prov)
            style_note = f"The style “{style['name']}” stays; it no longer links to a playable example."
        else:
            styles.delete(style["id"], workspace_id)
            style_note = f"The style “{style['name']}” was deleted too."
    db.execute("DELETE FROM reference_analyses WHERE reference_id = ?", (ref_id,))
    db.execute("DELETE FROM reference_videos WHERE id = ?", (ref_id,))
    file_note = "The video file stays in your media."
    if delete_file:
        file_note = _drop_file(row["asset_id"], workspace_id, float(row.get("created_at") or 0))
    return {"deleted": ref_id, "notes": [n for n in (style_note, file_note,
                                                       "Projects already made keep the choices they used.") if n]}


def _drop_file(asset_id: str, workspace_id: str, made: float = 0.0) -> str:
    """Delete the example's video file when nothing else needs it. It stays when anything else names it (a project,
    any saved version of a video, an animated short, a media import, another example: project_delete's own check),
    or when, in the last day, the owner added the same file on a page whose upload no project or example took (also
    before the example was made; Add from this computer leaves such an upload too) or ClipForge handed it out again
    since the example was made: that page may be about to use it. The Examples page's own uploads are the
    example's (create), so they do not count. The check and the delete are one step, so a hand-out waits for it
    (uploads._reuse). What ClipForge made for a linked file goes; the owner's file never does."""
    from . import project_delete

    asset = db.fetch("assets", asset_id)
    if not asset or asset["workspace_id"] != workspace_id:
        return "The video file was deleted."
    with uploads._content_lock(workspace_id, asset["sha256"]), db.connect() as conn:  # noqa: SLF001
        conn.execute("BEGIN IMMEDIATE")
        if asset_id in project_delete._used_elsewhere(workspace_id, "example", ""):  # noqa: SLF001
            return "The video file stays because a project or another example uses it."
        now = conn.execute("SELECT reused_at FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if now is None:
            return "The video file was deleted."
        day = time.time() - project_delete.AGAIN_S
        if float(now[0] or 0) > max(made, day) or conn.execute(
                "SELECT 1 FROM uploads WHERE asset_id = ? AND status = 'complete' AND taken = '' AND updated_at > ? "
                "LIMIT 1", (asset_id, day)).fetchone():
            return "The video file stays because you added it again in the last day, and a page may be about to use it."
        for table, column in (("asset_sources", "asset_id"), ("uploads", "asset_id"), ("assets", "id")):
            conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (asset_id,))
        conn.commit()
    project_delete.remove_asset_files(asset)
    if uploads.is_linked(asset):
        return "What ClipForge made for the file was deleted; the file itself stays where it is on this computer."
    return "The video file was deleted."


# ------------------------------------------------------------------ the analysis job
def _job(row: dict) -> dict | None:
    rows = db.select("studio_jobs", "idempotency_key = ?", (f"reference_analysis:{row['id']}:{row['round']}",))
    return rows[0] if rows else None


def cache_key(sha256: str, ranges: list[tuple[float, float]], speech: str) -> str:
    raw = json.dumps({"sha": sha256, "ranges": [[round(a, 3), round(b, 3)] for a, b in ranges],
                      "analyzer": ra.ANALYZER, "speech": speech}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def model_note(settings: dict) -> str:
    """What the configured AI could have done with this video, in words. ClipForge only sends text to AI services,
    so none of them watched or heard an example."""
    from ..pipeline import llm

    if settings.get("ai_provider", "heuristic") in ("", "heuristic"):
        return "No AI service is set up, so this is measured only."
    return (f"The AI service in Settings ({llm.provider_label(settings)}) is only sent text by ClipForge, so it did "
            "not watch or hear this example.")


def _words(asset: dict, settings: dict, lease: Lease) -> tuple[list[dict] | None, str]:
    from . import video_flow

    if not (asset.get("probe") or {}).get("has_audio"):
        return None, "This example has no sound."
    try:
        words = video_flow.transcript_words(asset, settings, lease)
    except Canceled:
        raise
    except Exception as exc:  # noqa: BLE001 - a missing speech model must not stop the rest of the analysis
        from ..pipeline.common import Cancelled as MediaCancelled

        if isinstance(exc, MediaCancelled):
            raise
        log.info("example transcript unavailable: %s", exc)
        why = " ".join(str(exc).split())
        if len(why) > 140:
            why = why[:140].rsplit(" ", 1)[0] + "…"
        return None, f"Transcription was not available ({why}), so speech was estimated from the sound."
    if not words:
        return None, "No words were recognized, so speech was estimated from the sound."
    return words, "Speech timing from the transcript."


@handler("reference_analysis")
def analyze_job(job: dict, lease: Lease) -> dict:
    row = db.fetch("reference_videos", job["target_id"])
    if not row or row["round"] != job["revision"]:
        return {"skipped": "superseded"}
    asset = db.fetch("assets", row["asset_id"])
    if not asset or asset["workspace_id"] != row["workspace_id"] or not Path(asset["path"]).is_file():
        db.update("reference_videos", row["id"], status="failed", error="The example's video file is missing.",
                  message="Failed")
        raise ReferenceError("The example's video file is missing.")
    db.update("reference_videos", row["id"], status="analyzing", message="Reading the example", error="")
    settings = db.get_settings()
    probe = asset.get("probe") or {}
    try:
        ranges = ra.clean_ranges(row["ranges"] or None, float(probe.get("duration") or 0))
        lease.progress(0.02, "Reading the example's speech")
        words, speech_note = _words(asset, settings, lease)
        key = cache_key(asset["sha256"], ranges, "transcript" if words else "estimate")
        hit = db.scalar("SELECT a.reference_id || ':' || a.revision FROM reference_analyses a JOIN reference_videos r "
                        "ON r.id = a.reference_id WHERE a.cache_key = ? AND r.workspace_id = ? "
                        "ORDER BY a.created_at DESC LIMIT 1", (key, row["workspace_id"]))
        if hit:
            src_id, src_rev = hit.rsplit(":", 1)
            prev = db.select("reference_analyses", "reference_id = ? AND revision = ?", (src_id, int(src_rev)))[0]
            result = {k: prev[k] for k in ("analyzer", "method", "coverage", "measured", "observations")}
            reused = hit
        else:
            result = ra.analyze(Path(asset["path"]), probe, ranges, words, transcript_note=speech_note,
                                cancelled=lease.canceled, progress=lease.progress)
            reused = ""
    except ra.Canceled:
        raise Canceled() from None
    except ra.AnalysisError as exc:
        db.update("reference_videos", row["id"], status="failed", error=str(exc), message="Failed")
        raise
    except Canceled:
        raise
    except Exception as exc:
        db.update("reference_videos", row["id"], status="failed", message="Failed",
                  error="The example could not be analyzed: " + str(exc)[:300])
        raise
    applicable, unsupported = ra.applicable(result["measured"], row["likes"] or [])
    current = db.fetch("reference_videos", row["id"])
    if not current or current["round"] != row["round"]:
        return {"skipped": "superseded"}
    rev = current["analysis_revision"] + 1
    db.insert("reference_analyses", {"reference_id": row["id"], "revision": rev, "cache_key": key,
                                     "analyzer": result["analyzer"], "method": result["method"],
                                     "model": "", "coverage": result["coverage"], "measured": result["measured"],
                                     "observations": result["observations"], "applicable": applicable,
                                     "unsupported": unsupported, "reused_from": reused}, key="reference_id")
    db.update("reference_videos", row["id"], status="ready", analysis_revision=rev, error="",
              message=f"Analyzed ({len(result['observations'])} things noticed)")
    return {"revision": rev, "reused_from": reused}


# ------------------------------------------------------------------ views
def analysis(ref_id: str, revision: int) -> dict | None:
    rows = db.select("reference_analyses", "reference_id = ? AND revision = ?", (ref_id, revision))
    return rows[0] if rows else None


def view(row: dict, settings: dict | None = None) -> dict:
    a = analysis(row["id"], row["analysis_revision"]) if row["analysis_revision"] else None
    job = _job(row)
    style = db.fetch("styles", row["style_id"]) if row["style_id"] else None
    likes = row.get("likes") or []
    every = not likes or "overall" in likes
    out = {k: row[k] for k in ("id", "asset_id", "title", "likes", "note", "ranges", "scope", "modes", "status",
                               "message", "error", "analysis_revision", "created_at", "updated_at")}
    out.update(avoid=bool(row["avoid"]), project_only=bool(row["project_only"]), enabled=bool(row["enabled"]),
               media_url=f"/api/assets/{row['asset_id']}/media",
               progress=(job or {}).get("progress", 0) if row["status"] in ("queued", "analyzing") else None,
               style=styles.view(style) if style else None)
    asset = db.fetch("assets", row["asset_id"])
    out["duration_ms"] = int(float(((asset or {}).get("probe") or {}).get("duration") or 0) * 1000)
    if a:
        fields = capabilities.FIELDS
        out["analysis"] = {
            "revision": a["revision"], "analyzer": a["analyzer"], "method": a["method"],
            "model_note": model_note(settings if settings is not None else db.get_settings()),
            "coverage": a["coverage"], "observations": a["observations"], "unsupported": a["unsupported"],
            "speech_note": (a["measured"].get("speech") or {}).get("note", ""), "reused_from": a["reused_from"],
            "created_at": a["created_at"],
            "applicable": [{**x, "label": fields[x["field"]].label, "text": fields[x["field"]].describe(x["value"]),
                            "selected": False if row["avoid"] else (every or x["aspect"] in likes)}
                           for x in a["applicable"] if x["field"] in fields]}
    return out


def list_for(workspace_id: str, include_project_only: bool = False) -> list[dict]:
    where = "workspace_id = ?" + ("" if include_project_only else " AND project_only = 0")
    settings = db.get_settings()
    return [view(r, settings) for r in db.select("reference_videos", where, (workspace_id,), "updated_at DESC", 500)]


# ------------------------------------------------------------------ the Example style
def save_style(ref_id: str, workspace_id: str, *, values: dict, analysis_revision: int, name: str = "",
               style_revision: int | None = None) -> dict:
    """Save the chosen supported values as this example's style (one action, no per-project reapproval). A value
    that differs from what was measured is recorded as the owner's correction."""
    row = get(ref_id, workspace_id)
    if row["avoid"]:
        raise ReferenceError("This is an example to avoid; its choices are never applied.")
    if analysis_revision != row["analysis_revision"] or not row["analysis_revision"]:
        raise Conflict("This example was analyzed again. Review the newest analysis before saving.")
    a = analysis(ref_id, row["analysis_revision"])
    if not isinstance(values, dict) or not values:
        raise ReferenceError("Choose at least one thing to apply.")
    clean, problems = capabilities.clean(values)
    if problems:
        raise ReferenceError("; ".join(problems))
    measured = {x["field"]: x["value"] for x in a["applicable"]}
    corrections = [{"field": k, "measured": measured.get(k), "chosen": v} for k, v in clean.items()
                   if k not in measured or measured[k] != v]
    provenance = {"reference_id": ref_id, "title": row["title"], "analysis_revision": a["revision"],
                  "analyzer": a["analyzer"], "method": a["method"], "model": a["model"],
                  "ranges": row["ranges"] or [{"start_ms": 0, "end_ms": None}], "corrections": corrections,
                  "saved_at": time.time()}
    style = db.fetch("styles", row["style_id"]) if row["style_id"] else None
    try:
        if style and style["workspace_id"] == workspace_id:
            saved = styles.update(style["id"], workspace_id, expected_revision=style["revision"] if style_revision is None else style_revision,
                                  name=name or None, values=clean, provenance=provenance)
        else:
            saved = styles.create(workspace_id, name or f"{row['title'][:54]} style", clean,
                                  list(capabilities.MODES), source="example", reference_id=ref_id,
                                  provenance=provenance)
            db.update("reference_videos", ref_id, style_id=saved["id"])
    except styles.Conflict as exc:
        raise Conflict(str(exc)) from exc
    except styles.StyleError as exc:
        raise ReferenceError(str(exc)) from exc
    return view(get(ref_id, workspace_id))


def _usable(row: dict) -> dict | None:
    if row["avoid"] or not row["enabled"] or not row["style_id"]:
        return None
    style = db.fetch("styles", row["style_id"])
    if not style or style["workspace_id"] != row["workspace_id"]:
        return None
    return {**style, "reference_title": row["title"], "reference_id": row["id"]}


def chosen(workspace_id: str, ref_id: str) -> dict | None:
    """The Example style of an example chosen for one project ('' = none)."""
    if not ref_id:
        return None
    row = get(ref_id, workspace_id)
    if row["avoid"]:
        raise ReferenceError("That is an example to avoid; choose another one.")
    if not row["enabled"]:
        raise ReferenceError("That example is disabled. Enable it in Brain or choose another one.")
    style = _usable(row)
    if style is None:
        raise ReferenceError("Save what you want to use from that example first (Brain → Example videos).")
    return style


def guidance_inputs(workspace_id: str, mode: str, reference_id: str = "") -> dict:
    """The Example styles for guidance.resolve: the one chosen for this project and the ones that always apply."""
    return {"reference": chosen(workspace_id, reference_id),
            "examples": applying(workspace_id, mode, exclude=reference_id)}


def applying(workspace_id: str, mode: str, exclude: str = "") -> list[dict]:
    """Example styles that apply to every project, or to this project type, without being chosen."""
    out = []
    for row in db.select("reference_videos", "workspace_id = ? AND project_only = 0 AND enabled = 1 AND avoid = 0 "
                         "AND scope != 'chosen'", (workspace_id,), "updated_at DESC", 50):
        if row["id"] == exclude or (row["scope"] == "modes" and mode not in (row["modes"] or [])):
            continue
        style = _usable(row)
        if style:
            out.append(style)
    return out

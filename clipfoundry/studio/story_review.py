"""Full stories inside Clips: proposals, owner adjustments and one clip per story.

Confident, complete stories become clips automatically (no new per-clip ceremony). Uncertain or cut-off ones are
held as proposals until the owner adjusts or confirms them. Every manual change increments the story's boundary
revision, keeps times in integer milliseconds and never changes a clip that is already rendered: a changed boundary
makes a new clip, and the old one stays until it is removed.
"""
from __future__ import annotations

from .. import db
from ..pipeline import postpack, scoring, stories
from . import eligibility

# A whole story is one continuous source interval: no silence removal, no filler cuts, no teaser hook overlay.
STORY_EDIT = {"silence": "off", "remove_fillers": False, "hook_overlay": False}
MIN_MS = 3000


class StoryError(ValueError):
    pass


def _destinations(project: dict) -> list[dict]:
    out = []
    for cid in (project.get("destinations") or {}).get("connections", []) if isinstance(
            project.get("destinations"), dict) else []:
        acc = db.get_connection(cid)
        if acc:
            out.append(acc)
    return out


def view(row: dict, project: dict) -> dict:
    duration = (row["end_ms"] - row["start_ms"]) / 1000
    clip = db.get_clip(row["clip_id"]) if row["clip_id"] else None
    return {**{k: row[k] for k in ("id", "position", "kind", "title", "opening", "closing", "completeness", "reason",
                                   "method", "boundary_revision", "clip_id")},
            "start": row["start_ms"] / 1000, "end": row["end_ms"] / 1000, "duration": round(duration, 3),
            "confidence": row["confidence"], "included": bool(row["included"]),
            "clip_status": (clip or {}).get("status", ""),
            "eligibility": eligibility.for_output(duration, 1080, 1920, _destinations(project))
            if row["kind"] == "story" else []}


def list_for(project_id: str) -> list[dict]:
    project = db.get_project(project_id) or {}
    return [view(r, project) for r in db.select("story_proposals", "project_id = ?", (project_id,), "position, start_ms")]


def save(project: dict, result: dict) -> list[dict]:
    """Store a new analysis. Proposals the owner already changed are kept as they are."""
    manual = db.select("story_proposals", "project_id = ? AND boundary_revision > 0", (project["id"],))
    if manual:
        return manual
    db.execute("DELETE FROM story_proposals WHERE project_id = ? AND clip_id = ''", (project["id"],))
    rows = []
    for pos, item in enumerate(result["items"]):
        rows.append(db.insert("story_proposals", {
            "id": db.new_id(), "project_id": project["id"], "workspace_id": project.get("workspace_id") or "local",
            "position": pos, "start_ms": int(round(item["start"] * 1000)), "end_ms": int(round(item["end"] * 1000)),
            "kind": item["kind"], "title": item["title"] if item["kind"] == "story" else (item["label"] or "Other"),
            "opening": item["opening"][:500], "closing": item["closing"][:500],
            "completeness": item["completeness"], "confidence": item["confidence"], "reason": item["reason"][:500],
            "included": 1 if item["kind"] == "story" else 0, "method": result["method"]}))
    return rows


def _story_text(words: list[dict], start: float, end: float) -> list[str]:
    from ..pipeline.text_utils import build_sentences

    inside = [w for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]
    return [s["text"] for s in build_sentences(inside)]


def create_clip(project: dict, row: dict, words: list[dict], settings: dict, from_pipeline: bool = False) -> dict:
    """One clip for one story: its whole interval, captions from its own words, a grounded post package."""
    start, end = row["start_ms"] / 1000, row["end_ms"] / 1000
    sents = _story_text(words, start, end)
    df = scoring.document_frequencies([{"text": s} for s in sents]) if sents else {}
    post = postpack.generate(sents, "", [], "story", {**settings, **(project.get("options") or {})}, df,
                             max(1, len(sents))) if sents else {"title": row["title"], "hashtags": []}
    clip = db.create_clip(project["id"], rank=row["position"], start=start, end=end,
                          title=(post.get("title") or row["title"])[:100], hook="", hooks_alt=[],
                          caption_text=" ".join(sents)[:4000], hashtags=post.get("hashtags") or [], category="story",
                          score=0.0, scores={}, score_source="story", reason=row["reason"],
                          analysis={"story": {"id": row["id"], "boundary_revision": row["boundary_revision"],
                                              "completeness": row["completeness"], "confidence": row["confidence"],
                                              "method": row["method"], "opening": row["opening"],
                                              "closing": row["closing"]},
                                    # owner-made story clips of an upload request upload after their first render
                                    **({"autopublish_first_render": True} if project.get("destinations") and
                                       not from_pipeline else {})},
                          post=post, edit=dict(STORY_EDIT), status="queued", duration=round(end - start, 2))
    db.update("story_proposals", row["id"], clip_id=clip["id"])
    return clip


def auto_clips(project: dict, words: list[dict], settings: dict) -> list[dict]:
    """Clips for every included, complete story that has none yet (uncertain ones wait for the owner)."""
    rows = db.select("story_proposals", "project_id = ? AND kind = 'story' AND included = 1 AND clip_id = '' "
                                        "AND completeness = 'complete'", (project["id"],), "position")
    return [create_clip(project, r, words, settings, from_pipeline=True) for r in rows]


def analyze(p, ctx) -> list[dict]:
    """The Full stories stage of the pipeline: propose, store and create the confident clips."""
    p.stage("stories", 0.46, "Finding complete stories")
    result = stories.propose(p.words, p.sentences, float(p.meta["duration"] or 0))
    rows = save(p.project, result)
    p.info["stories"] = {"method": result["method"], "chunks": len(result.get("chunks") or []),
                         "stories": sum(1 for r in rows if r["kind"] == "story"),
                         "held": sum(1 for r in rows if r["kind"] == "story" and r["completeness"] != "complete"),
                         "gaps": sum(1 for r in rows if r["kind"] == "gap"), "note": result.get("note", "")}
    p.save_info()
    ctx.check()
    return auto_clips(db.get_project(p.id) or p.project, p.words, p.settings)


# ------------------------------------------------------------------ owner adjustments
def _get(story_id: str) -> dict:
    row = db.fetch("story_proposals", story_id)
    if not row:
        raise StoryError("Story not found.")
    return row


def _project_duration_ms(project_id: str) -> int:
    return int(round(float((db.get_project(project_id) or {}).get("duration") or 0) * 1000))


def _bump(row: dict, **fields) -> dict:
    """A manual change: new boundary revision; a changed interval detaches the old clip (kept, never rewritten)."""
    if ("start_ms" in fields or "end_ms" in fields) and row["clip_id"]:
        fields["clip_id"] = ""
    db.update("story_proposals", row["id"], boundary_revision=row["boundary_revision"] + 1, method="manual",
              **fields)
    return _get(row["id"])


def patch(story_id: str, *, start_ms: int | None = None, end_ms: int | None = None, included: bool | None = None,
          title: str | None = None, confirm: bool = False) -> dict:
    row = _get(story_id)
    fields: dict = {}
    s = row["start_ms"] if start_ms is None else int(start_ms)
    e = row["end_ms"] if end_ms is None else int(end_ms)
    limit = _project_duration_ms(row["project_id"])
    if s < 0 or (limit and e > limit) or e - s < MIN_MS:
        raise StoryError("A story must be at least 3 seconds long and inside the recording.")
    if (s, e) != (row["start_ms"], row["end_ms"]):
        fields.update(start_ms=s, end_ms=e, completeness="complete",
                      reason="Boundaries set by you.", confidence=1.0)
    if included is not None:
        fields["included"] = int(included)
    if title is not None:
        text = " ".join(title.split())[:100]
        if not text:
            raise StoryError("Give the story a title.")
        fields["title"] = text
    if confirm and row["completeness"] != "complete":
        fields.update(completeness="complete", reason=row["reason"] + " Confirmed by you.")
    return _bump(row, **fields) if fields else row


def split(story_id: str, at_ms: int) -> list[dict]:
    row = _get(story_id)
    if not row["start_ms"] + MIN_MS <= at_ms <= row["end_ms"] - MIN_MS:
        raise StoryError("Split at least 3 seconds inside the story.")
    db.execute("UPDATE story_proposals SET position = position + 1 WHERE project_id = ? AND position > ?",
               (row["project_id"], row["position"]))
    first = _bump(row, end_ms=int(at_ms), completeness="uncertain", reason="Split by you; check both parts.")
    second = db.insert("story_proposals", {**{k: row[k] for k in ("project_id", "workspace_id", "kind", "closing",
                                                                   "method", "included")},
                                           "id": db.new_id(), "position": row["position"] + 1, "start_ms": int(at_ms),
                                           "end_ms": row["end_ms"], "title": row["title"] + " (part 2)",
                                           "opening": "", "completeness": "uncertain", "confidence": 1.0,
                                           "reason": "Split by you; check both parts.", "boundary_revision": 1,
                                           "method": "manual"})
    return [first, second]


def merge(ids: list[str]) -> dict:
    rows = sorted((_get(i) for i in ids), key=lambda r: r["position"])
    if len(rows) < 2 or len({r["project_id"] for r in rows}) != 1:
        raise StoryError("Choose two or more stories of the same project.")
    positions = [r["position"] for r in rows]
    if positions != list(range(positions[0], positions[0] + len(rows))):
        raise StoryError("Only neighbouring parts can be merged.")
    first = rows[0]
    merged = _bump(first, end_ms=rows[-1]["end_ms"], closing=rows[-1]["closing"], kind="story", included=1,
                   completeness="complete", reason="Merged by you.", confidence=1.0)
    for r in rows[1:]:
        db.execute("DELETE FROM story_proposals WHERE id = ?", (r["id"],))
    db.execute("UPDATE story_proposals SET position = position - ? WHERE project_id = ? AND position > ?",
               (len(rows) - 1, first["project_id"], rows[-1]["position"]))
    return merged


def reorder(project_id: str, ids: list[str]) -> list[dict]:
    rows = db.select("story_proposals", "project_id = ?", (project_id,))
    if sorted(ids) != sorted(r["id"] for r in rows):
        raise StoryError("List every story of the project once.")
    for pos, sid in enumerate(ids):
        db.update("story_proposals", sid, position=pos)
    return list_for(project_id)


def create_selected(project_id: str, ids: list[str] | None = None) -> list[dict]:
    """Batch create: clips for the chosen (or all included) stories. Uncertain stories need the owner's confirm,
    which listing them here is."""
    from ..pipeline.process import load_words

    project = db.get_project(project_id)
    if not project:
        raise StoryError("Project not found.")
    where = "project_id = ? AND kind = 'story' AND clip_id = ''"
    rows = db.select("story_proposals", where, (project_id,), "position")
    if ids is not None:
        rows = [r for r in rows if r["id"] in ids]
    else:
        rows = [r for r in rows if r["included"] and r["completeness"] == "complete"]
    words = load_words(project)
    settings = db.get_settings()
    made = []
    for r in rows:
        if r["completeness"] != "complete":
            r = patch(r["id"], confirm=True)
        made.append(create_clip(project, r, words, settings))
    return made


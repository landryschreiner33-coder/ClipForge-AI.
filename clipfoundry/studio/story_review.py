"""Full stories inside Clips: proposals, owner adjustments and one clip per story (or per part of a story).

Two settings: **Full story** makes one clip per story, from where it starts to where the next one starts, and never
cuts a story except when it is longer than five minutes; **Story parts** cuts every story that is long enough at its
best places into Part 1, Part 2... (pipeline/story_parts.py). No story clip is ever longer than five minutes, in
either setting, whatever the owner does afterwards: a longer story is split at its best point.

Every story becomes a clip as soon as it is found; nothing waits for the owner. How sure ClipForge is about a
story's boundaries (complete, uncertain, cut off) is shown on its card so the owner can check it afterwards, and
never holds a clip back. Every manual change increments the story's boundary revision, keeps times in integer
milliseconds and never changes a clip that is already rendered: a changed boundary makes a new clip, and the old one
stays until it is removed.

A story clip keeps the picture still: the whole frame, centred, never cropped to follow a face or the action and
never zoomed, with the captions above the picture so none of the gameplay is covered. Only a choice the owner made
for this project (Make clips, Customize) or in the clip editor changes that.
"""
from __future__ import annotations

import math
import re

from .. import db
from ..pipeline import postpack, scoring, stories, story_parts
from . import ai_editor, eligibility, guidance

# A whole story is one continuous source interval: no silence removal, no filler cuts, no teaser hook overlay.
STORY_EDIT = {"silence": "off", "remove_fillers": False, "hook_overlay": False}
# The picture of a story clip stays still: never zoomed or pushed in, and the whole frame, centred, unless this
# project chose a framing (guidance.story_framing; guidance.py shows the same rule in "Used from your Brain").
STILL = {"zoom": 1.0, "auto_zoom": False}
MIN_MS = 3000
MAX_MS = int(story_parts.MAX_CLIP_S * 1000)
SPLITS = ("whole", "parts")              # Full story | Story parts
_PART = re.compile(r"\s*\((?:part|Part) \d+(?: of \d+)?\)$")
PLAIN_CUT = "after a finished sentence, near the planned length"  # a cut with nothing more to say about it


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


def split_of(project: dict) -> str:
    """"whole" (Full story) or "parts" (Story parts): chosen in Make clips, kept in the project's options."""
    value = (project.get("options") or {}).get("story_split")
    return value if value in SPLITS else "whole"


def view(row: dict, project: dict) -> dict:
    duration = (row["end_ms"] - row["start_ms"]) / 1000
    clip = db.get_clip(row["clip_id"]) if row["clip_id"] else None
    return {**{k: row[k] for k in ("id", "position", "kind", "title", "opening", "closing", "completeness", "reason",
                                   "method", "boundary_revision", "clip_id")},
            "part": int(row.get("part") or 0), "parts": int(row.get("parts") or 0),
            "story_key": row.get("story_key") or "",
            "start": row["start_ms"] / 1000, "end": row["end_ms"] / 1000, "duration": round(duration, 3),
            "confidence": row["confidence"], "included": bool(row["included"]),
            "clip_status": (clip or {}).get("status", ""),
            "eligibility": eligibility.for_output(duration, 1080, 1920, _destinations(project))
            if row["kind"] == "story" else []}


def list_for(project_id: str) -> list[dict]:
    project = db.get_project(project_id) or {}
    return [view(r, project) for r in db.select("story_proposals", "project_id = ?", (project_id,), "position, start_ms")]


def _base_title(title: str) -> str:
    return _PART.sub("", title or "").strip()


def _part_title(title: str, part: int, parts: int) -> str:
    base = _base_title(title)
    if parts <= 1:
        return base[:100]
    suffix = f" (Part {part})"
    return base[:100 - len(suffix)].rstrip() + suffix


def plan_parts(items: list[dict], sents: list[dict], words: list[dict], split: str,
               chooser=None) -> list[dict]:
    """The stories cut into the clips they become: with Full story ("whole") one clip per story, and a story longer
    than five minutes in the fewest parts that fit; with Story parts ("parts") every story long enough at its best
    places. Each part keeps its story's title with "(Part N)", the story's index ("story") and why it starts where
    it does. `chooser` (optional) is ClipForge AI's pick among the best places (story_parts.split)."""
    rh = story_parts.rhythm(sents)
    out: list[dict] = []
    for index, item in enumerate(items):
        if item["kind"] != "story":
            out.append(item)
            continue
        pieces = story_parts.split(sents, words, item["start"], item["end"], split, rh, chooser)
        n = len(pieces)
        if n == 1:
            out.append({**item, "story": index})
            continue
        why_split = ("This story is longer than five minutes, so it is split at its best point" if split != "parts"
                     else "Story parts: the story is split at its best moments")
        for k, piece in enumerate(pieces, 1):
            inside = [x for x in sents if x["start"] >= piece["start"] - 0.05 and x["end"] <= piece["end"] + 0.05]
            reason = (item["reason"] + f"; part 1 of {n}. {why_split}." if k == 1 else
                      f"Part {k} of {n}: starts " + (", ".join(piece["why"]) or PLAIN_CUT) + ".")
            out.append({**item, "story": index, "part": k, "parts": n, "start": piece["start"], "end": piece["end"],
                        "opening": item["opening"] if k == 1 or not inside else inside[0]["text"],
                        "closing": item["closing"] if k == n or not inside else inside[-1]["text"],
                        "title": _part_title(item["title"], k, n), "reason": reason,
                        **({"completeness": "complete"} if 1 < k < n else {})})
    return out


def save(project: dict, result: dict) -> list[dict]:
    """Store a new analysis. Proposals the owner already changed are kept as they are."""
    manual = db.select("story_proposals", "project_id = ? AND boundary_revision > 0", (project["id"],))
    if manual:
        return manual
    db.execute("DELETE FROM story_proposals WHERE project_id = ? AND clip_id = ''", (project["id"],))
    rows = []
    keys: dict[int, str] = {}
    for pos, item in enumerate(result["items"]):
        story = item.get("story")
        key = keys.setdefault(story, db.new_id()) if story is not None and item.get("parts", 0) > 1 else ""
        rows.append(db.insert("story_proposals", {
            "id": db.new_id(), "project_id": project["id"], "workspace_id": project.get("workspace_id") or "local",
            "position": pos, "start_ms": int(round(item["start"] * 1000)), "end_ms": int(round(item["end"] * 1000)),
            "kind": item["kind"], "title": item["title"] if item["kind"] == "story" else (item["label"] or "Other"),
            "opening": item["opening"][:500], "closing": item["closing"][:500],
            "completeness": item["completeness"], "confidence": item["confidence"], "reason": item["reason"][:500],
            "included": 1 if item["kind"] == "story" else 0, "method": result["method"],
            "part": int(item.get("part") or 0), "parts": int(item.get("parts") or 0), "story_key": key}))
    return rows


def _story_text(words: list[dict], start: float, end: float) -> list[str]:
    from ..pipeline.text_utils import build_sentences

    inside = [w for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]
    return [s["text"] for s in build_sentences(inside)]


def _owner_levels(project: dict) -> dict[str, str]:
    """Which guidance level decided each field of this project (project, reference, style, skill, example, brain,
    settings)."""
    return {d["field"]: (d.get("from") or {}).get("level", "") for d in
            (project.get("guidance") or {}).get("decisions") or [] if isinstance(d, dict) and d.get("field")}


def story_edit(project: dict, row: dict) -> dict:
    """The edit a story clip starts with: one continuous interval, the picture still and centred (the whole frame,
    never cropped to follow anything or zoomed) unless the owner chose a framing for this project, captions above
    the picture unless a caption position was chosen anywhere (project, example, style, skill, Brain note), and
    "Part N" at the top for the whole clip when the story is in parts."""
    levels = _owner_levels(project)
    edit = {**STORY_EDIT, **STILL,
            **guidance.story_framing((project.get("guidance") or {}).get("decisions") or [])}
    if levels.get("caption_position") in (None, "", "settings", "story"):  # nobody chose one: above the picture
        edit["caption_position"] = guidance.STORY_CAPTIONS
    if int(row.get("parts") or 0) > 1:
        # whole seconds, so the clip editor's field (half-second steps) shows a valid number
        edit.update(hook_overlay=True, hook_seconds=math.ceil((row["end_ms"] - row["start_ms"]) / 1000) + 1)
    return edit


def create_clip(project: dict, row: dict, words: list[dict], settings: dict, from_pipeline: bool = False) -> dict:
    """One clip for one story (or one part of it): its whole interval, captions from its own words, a grounded post
    package. A story part keeps its story's title with "(Part N)" and shows "Part N" at the top."""
    start, end = row["start_ms"] / 1000, row["end_ms"] / 1000
    sents = _story_text(words, start, end)
    df = scoring.document_frequencies([{"text": s} for s in sents]) if sents else {}
    post = postpack.generate(sents, "", [], "story", {**settings, **(project.get("options") or {})}, df,
                             max(1, len(sents))) if sents else {"title": row["title"], "hashtags": []}
    parts, part = int(row.get("parts") or 0), int(row.get("part") or 0)
    if parts > 1:  # the series keeps one name: the story's title and the part's number
        post = {**post, "title": _part_title(row["title"], part, parts)}
    clip = db.create_clip(project["id"], rank=row["position"], start=start, end=end,
                          title=(post.get("title") or row["title"])[:100],
                          hook=f"Part {part}" if parts > 1 else "", hooks_alt=[],
                          caption_text=" ".join(sents)[:4000], hashtags=post.get("hashtags") or [], category="story",
                          score=0.0, scores={}, score_source="story", reason=row["reason"],
                          analysis={"story": {"id": row["id"], "boundary_revision": row["boundary_revision"],
                                              "completeness": row["completeness"], "confidence": row["confidence"],
                                              "method": row["method"], "opening": row["opening"],
                                              "closing": row["closing"], "part": part, "parts": parts},
                                    # owner-made story clips of an upload request upload after their first render
                                    **({"autopublish_first_render": True} if project.get("destinations") and
                                       not from_pipeline else {})},
                          post=post, edit=story_edit(project, row), status="queued", duration=round(end - start, 2))
    db.update("story_proposals", row["id"], clip_id=clip["id"])
    return clip


def capped(project: dict, row: dict, words: list[dict]) -> list[dict]:
    """The row, or its parts when it is longer than five minutes (a story stored before the limit, or one whose
    boundaries were set by hand): split at the best point, never cut at the limit in the middle of a sentence."""
    if row["end_ms"] - row["start_ms"] <= MAX_MS or row["kind"] != "story":
        return [row]
    from ..pipeline.text_utils import build_sentences

    start, end = row["start_ms"] / 1000, row["end_ms"] / 1000
    inside = [w for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]
    pieces = story_parts.split(build_sentences(inside), inside, start, end, "whole")
    key = row.get("story_key") or row["id"]
    n = len(pieces)
    db.execute("UPDATE story_proposals SET position = position + ? WHERE project_id = ? AND position > ?",
               (n - 1, row["project_id"], row["position"]))
    db.update("story_proposals", row["id"], end_ms=int(round(pieces[0]["end"] * 1000)), story_key=key,
              reason=(row["reason"] + " Longer than five minutes, so it is split at its best point.")[:500])
    ids = [row["id"]]
    for k, piece in enumerate(pieces[1:], 2):
        ids.append(db.insert("story_proposals", {
            **{c: row[c] for c in ("project_id", "workspace_id", "kind", "completeness", "confidence", "included",
                                   "method", "boundary_revision", "title")},
            "id": db.new_id(), "position": row["position"] + k - 1, "start_ms": int(round(piece["start"] * 1000)),
            "end_ms": int(round(piece["end"] * 1000)) if k < n else row["end_ms"],
            "opening": "", "closing": row["closing"] if k == n else "",
            "reason": (f"Part {k} of {n}: starts " + (", ".join(piece["why"]) or PLAIN_CUT) + ".")[:500],
            "story_key": key})["id"])
    _renumber(row["project_id"], key)  # Part 1, 2... over the whole story, also when it was in parts already
    return [db.fetch("story_proposals", i) for i in ids]


def auto_clips(project: dict, words: list[dict], settings: dict) -> list[dict]:
    """Clips for every included story that has none yet, however sure ClipForge is about its boundaries."""
    rows = db.select("story_proposals", "project_id = ? AND kind = 'story' AND included = 1 AND clip_id = ''",
                     (project["id"],), "position")
    # each row read again: splitting a longer story moves the positions of the stories after it
    return [create_clip(project, part, words, settings, from_pipeline=True)
            for r in rows for part in capped(project, db.fetch("story_proposals", r["id"]) or r, words)]


def analyze(p, ctx) -> list[dict]:
    """The Full stories stage of the pipeline: find the stories, store them and make every clip. With a model set
    up, ClipForge AI checks the boundaries the rules are least sure of and names the stories, inside a time budget;
    without one, or when it does not answer, the rules decide."""
    p.stage("stories", 0.46, "Finding the stories")
    judge = None
    if ai_editor.configured(p.settings):
        budget = min(600.0, max(60.0, float(p.settings.get("ai_edit_timeout_s", 60)) * 5))
        judge = stories.Judge(p.settings, p.sentences, budget_s=budget, canceled=ctx.cancelled,
                              heartbeat=lambda m: p.stage("stories", 0.47, m))
    result = stories.propose(p.words, p.sentences, float(p.meta["duration"] or 0), judge=judge, opts=p.settings)
    if judge is not None and not ctx.cancelled():
        for k, title in judge.titles(result["items"]).items():
            result["items"][k]["title"] = title
    split = split_of(p.project)
    p.stage("stories", 0.48, "Cutting the stories into parts" if split == "parts" else "Checking the story lengths")
    chooser = judge.choose_cut if judge is not None and not ctx.cancelled() else None
    whole = sum(1 for i in result["items"] if i["kind"] == "story")
    result = {**result, "items": plan_parts(result["items"], p.sentences, p.words, split, chooser)}
    rows = save(p.project, result)
    stories_rows = [r for r in rows if r["kind"] == "story"]
    p.info["stories"] = {"method": result["method"], "chunks": len(result.get("chunks") or []),
                         "stories": whole, "clips": len(stories_rows), "split": split,
                         "in_parts": len({r["story_key"] for r in stories_rows if r.get("story_key")}),
                         "unsure": sum(1 for r in stories_rows if r["completeness"] != "complete"),
                         "gaps": sum(1 for r in rows if r["kind"] == "gap"), "note": result.get("note", ""),
                         "separators": result.get("separators") or [], "ai": result.get("ai") or {}}
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
    if e - s > MAX_MS and (s, e) != (row["start_ms"], row["end_ms"]):
        raise StoryError(f"A story clip can be at most 5 minutes long; this would make it {_clock(e - s)}. "
                         "Split the story into parts instead.")
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


def _clock(ms: int) -> str:
    secs = int(round(ms / 1000))
    return f"{secs // 60}:{secs % 60:02d}"


def _renumber(project_id: str, key: str) -> None:
    """Number the parts of one story again (Part 1, 2...) after a split or a merge; a story left in one piece loses
    its part number. Clips already made keep the name they were made with."""
    if not key:
        return
    rows = db.select("story_proposals", "project_id = ? AND story_key = ?", (project_id, key), "position")
    n = len(rows)
    for k, r in enumerate(rows, 1):
        db.update("story_proposals", r["id"], part=k if n > 1 else 0, parts=n if n > 1 else 0,
                  story_key=key if n > 1 else "", title=_part_title(r["title"], k, n))


def split(story_id: str, at_ms: int) -> list[dict]:
    row = _get(story_id)
    if not row["start_ms"] + MIN_MS <= at_ms <= row["end_ms"] - MIN_MS:
        raise StoryError("Split at least 3 seconds inside the story.")
    key = row.get("story_key") or row["id"]
    db.execute("UPDATE story_proposals SET position = position + 1 WHERE project_id = ? AND position > ?",
               (row["project_id"], row["position"]))
    first = _bump(row, end_ms=int(at_ms), completeness="uncertain", reason="Split by you; check both parts.",
                  story_key=key)
    second = db.insert("story_proposals", {**{k: row[k] for k in ("project_id", "workspace_id", "kind", "closing",
                                                                   "method", "included")},
                                           "id": db.new_id(), "position": row["position"] + 1, "start_ms": int(at_ms),
                                           "end_ms": row["end_ms"], "title": row["title"],
                                           "opening": "", "completeness": "uncertain", "confidence": 1.0,
                                           "reason": "Split by you; check both parts.", "boundary_revision": 1,
                                           "method": "manual", "story_key": key})
    _renumber(row["project_id"], key)
    return [_get(first["id"]), _get(second["id"])]


def merge(ids: list[str]) -> dict:
    rows = sorted((_get(i) for i in ids), key=lambda r: r["position"])
    if len(rows) < 2 or len({r["project_id"] for r in rows}) != 1:
        raise StoryError("Choose two or more stories of the same project.")
    positions = [r["position"] for r in rows]
    if positions != list(range(positions[0], positions[0] + len(rows))):
        raise StoryError("Only neighbouring parts can be merged.")
    length = rows[-1]["end_ms"] - rows[0]["start_ms"]
    if length > MAX_MS:
        raise StoryError(f"Together these would be {_clock(length)} long, and a story clip can be at most 5 minutes. "
                         "Keep them as parts.")
    first = rows[0]
    keys = {r.get("story_key") or "" for r in rows}
    key = first.get("story_key") or ""
    merged = _bump(first, end_ms=rows[-1]["end_ms"], closing=rows[-1]["closing"], kind="story", included=1,
                   completeness="complete", reason="Merged by you.", confidence=1.0)
    for r in rows[1:]:
        db.execute("DELETE FROM story_proposals WHERE id = ?", (r["id"],))
    db.execute("UPDATE story_proposals SET position = position - ? WHERE project_id = ? AND position > ?",
               (len(rows) - 1, first["project_id"], rows[-1]["position"]))
    if len(keys) == 1 and key:  # parts of one story: the rest of that story is numbered again
        _renumber(first["project_id"], key)
    elif key or any(keys):  # parts of different stories joined: the result is a story of its own
        db.update("story_proposals", first["id"], part=0, parts=0, story_key="",
                  title=_base_title(first["title"])[:100])
        for k in keys - {""}:
            _renumber(first["project_id"], k)
    return _get(merged["id"])


def reorder(project_id: str, ids: list[str]) -> list[dict]:
    rows = db.select("story_proposals", "project_id = ?", (project_id,))
    if sorted(ids) != sorted(r["id"] for r in rows):
        raise StoryError("List every story of the project once.")
    for pos, sid in enumerate(ids):
        db.update("story_proposals", sid, position=pos)
    return list_for(project_id)


def create_selected(project_id: str, ids: list[str] | None = None) -> list[dict]:
    """Batch create: clips for the chosen stories, or for every included story without one. A story the owner
    names is confirmed by that; the others keep their label."""
    from ..pipeline.process import load_words

    project = db.get_project(project_id)
    if not project:
        raise StoryError("Project not found.")
    where = "project_id = ? AND kind = 'story' AND clip_id = ''"
    rows = db.select("story_proposals", where, (project_id,), "position")
    if ids is not None:
        rows = [r for r in rows if r["id"] in ids]
    else:
        rows = [r for r in rows if r["included"]]
    words = load_words(project)
    settings = db.get_settings()
    made = []
    for r in rows:
        r = db.fetch("story_proposals", r["id"]) or r  # positions move when a longer story before it is split
        if ids is not None and r["completeness"] != "complete":
            r = patch(r["id"], confirm=True)
        made += [create_clip(project, part, words, settings) for part in capped(project, r, words)]
    return made


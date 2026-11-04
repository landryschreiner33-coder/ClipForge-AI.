"""Make a YouTube video: media bin + four-question brief → outline → rough cut → preview → validated edits → render.

Plans are saved as immutable revisions (edit_plans); an edit is a validated operation that produces the next
revision, and an unsupported request is explained while the current revision stays as it is. Renders are durable
jobs bound to one revision; a finished render is an immutable artifact with its exact hash, probe, time map, final
transcript and audio checks. The previous finished artifact stays available until a new render passes its checks.
Nothing is invented: no narration, statements or endings are generated; a length target the footage cannot meet is
explained, not filled.
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
from pathlib import Path

from .. import config, db
from ..pipeline import artifact
from ..pipeline.ffmpeg_utils import extract_audio
from . import engine, guidance, prefs, styles, uploads
from .jobs import Lease, enqueue, handler

FEEL_TRANSITIONS = {"calm": ("dissolve", 800), "balanced": ("dissolve", 400), "energetic": ("cut", 0)}
IMAGE_MS = 4000
BRIEF_FIELDS = {"video_type", "audience", "goal", "target_duration_s", "aspect_ratio", "feel", "captions", "music",
                "music_asset_id", "must_keep", "avoid", "caption_style", "caption_position", "transition",
                "title_card", "music_level_db", "layout"}


class VideoError(ValueError):
    pass


class Conflict(VideoError):
    pass


def video_dir(project_id: str) -> Path:
    d = config.data_dir() / "videos" / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ transcripts (cached per asset content)
def transcript_words(asset: dict, settings: dict, lease: Lease | None = None, cached_only: bool = False) -> list[dict]:
    """Timed words of a video asset, transcribed once per file content and reused by every project.
    `cached_only`: never transcribe (request handlers read what the build job already made)."""
    from ..pipeline import transcribe
    from ..pipeline.common import JobContext, read_json, write_json

    if asset["kind"] != "video" or not (asset.get("probe") or {}).get("has_audio"):
        return []
    folder = Path(asset["path"]).parent
    cache = folder / "transcript.json"
    data = read_json(cache, None)
    if data is None and cached_only:
        return []
    if data is None:
        wav = folder / "audio.wav"
        duration = float(asset["probe"].get("duration") or 0)
        if not wav.exists():
            extract_audio(Path(asset["path"]), wav, duration)
        ctx = JobContext((lambda f, m: lease.progress(0.05 + 0.4 * f, m)) if lease else None,
                         (lambda: lease.canceled()) if lease else None)
        data = transcribe.transcribe(wav, duration, settings, ctx)
        write_json(cache, data)
    return transcribe.flatten_words(data)


# ------------------------------------------------------------------ creating a project
def create(workspace_id: str, user_id: str, *, name: str, asset_ids: list[str], brief: dict, style_id: str = "saved",
           remember: dict | None = None) -> dict:
    if not asset_ids:
        raise VideoError("Add at least one video or image.")
    unknown = set(brief) - BRIEF_FIELDS
    if unknown:
        raise VideoError("Unknown brief fields: " + ", ".join(sorted(unknown)))
    assets = []
    for aid in asset_ids:
        try:
            a = uploads.asset(aid, workspace_id)
        except uploads.UploadError as exc:
            raise VideoError(str(exc)) from exc
        if a["kind"] not in ("video", "image"):
            raise VideoError(f"“{a['filename']}” is not a video or image; add music under the brief's third question.")
        assets.append(a)
    if not any(a["kind"] == "video" for a in assets):
        raise VideoError("Add at least one video; images are inserted between videos.")
    if brief.get("music") == "supplied":
        try:
            m = uploads.asset(str(brief.get("music_asset_id") or ""), workspace_id)
        except uploads.UploadError as exc:
            raise VideoError("Upload the music file you want to use.") from exc
        if m["kind"] != "audio":
            raise VideoError("The music must be an audio file.")
    style = styles.default(workspace_id) if style_id == "saved" else (
        styles.get(style_id, workspace_id) if style_id not in ("", "settings") else None)
    choices = {k: v for k, v in brief.items() if k in {"aspect_ratio", "feel", "captions", "music", "caption_style",
                                                       "caption_position", "transition", "title_card",
                                                       "music_level_db", "layout", "target_duration_s",
                                                       "video_type", "audience"} and v not in (None, "")}
    from . import skills

    snapshot = guidance.resolve("full_video", project_choices=choices, style=style,
                                global_skills=skills.enabled_skills(workspace_id),
                                context={"title": name, "caption_text": brief.get("goal") or ""})
    if snapshot["problems"]:
        raise VideoError("; ".join(snapshot["problems"]))
    project = db.insert("studio_projects", {
        "id": "vid-" + os.urandom(6).hex(), "workspace_id": workspace_id, "name": (name or "My video")[:120],
        "status": "building", "message": "Reading your files", "asset_ids": asset_ids,
        "brief": {k: v for k, v in brief.items() if k in BRIEF_FIELDS}, "style_id": (style or {}).get("id", ""),
        "guidance": snapshot})
    remember = remember or {}
    pref = prefs.get_appearance(workspace_id, user_id)["value"]
    if remember.get("enabled", pref.get("remember_style", True)):
        styles.remember_from_brief(workspace_id, (remember.get("name") or f"{name} style")[:60], choices,
                                   "full_video")
    if "enabled" in remember:  # the owner's explicit choice is the next brief's default
        prefs.set_appearance(workspace_id, user_id, {"remember_style": bool(remember["enabled"])}, None)
    enqueue(workspace_id, "video_build", project["id"], 0)
    return project


# ------------------------------------------------------------------ the rough cut
def _sentences(words: list[dict]) -> list[dict]:
    from ..pipeline.text_utils import build_sentences

    return build_sentences(words)


def _phrases(text: str) -> list[str]:
    return [p.strip().lower() for p in re.split(r"[,;\n]|\band\b", text or "") if len(p.strip()) >= 3]


def rough_cut(project: dict, assets: dict[str, dict], words: dict[str, list[dict]]) -> dict:
    """Revision 1: the files in the order of the media bin, each trimmed to its speech (measured silence kept short),
    avoid-requests cut out at sentence boundaries, and the brief/style choices applied."""
    values = (project.get("guidance") or {}).get("values") or {}
    brief = project.get("brief") or {}
    feel = values.get("feel", "balanced")
    t_type, t_ms = FEEL_TRANSITIONS.get(feel, FEEL_TRANSITIONS["balanced"])
    if values.get("transition"):
        t_type = values["transition"]
        t_ms = 0 if t_type == "cut" else (t_ms or 400)
    avoid, keep = _phrases(brief.get("avoid", "")), _phrases(brief.get("must_keep", ""))
    clips, outline, notes = [], [], []
    for n, aid in enumerate(project["asset_ids"], 1):
        a = assets[aid]
        if a["kind"] == "image":
            clips.append({"id": f"c{n}", "asset_id": aid, "kind": "image", "in_ms": 0, "out_ms": IMAGE_MS,
                          "label": a["filename"], "gain_db": 0.0, "include": True})
            outline.append({"clip_id": f"c{n}", "label": a["filename"], "summary": "Your image (B-roll)",
                            "duration": IMAGE_MS / 1000})
            continue
        length = int(float(a["probe"].get("duration") or 0) * 1000)
        ws = words.get(aid) or []
        sents = _sentences(ws)
        start = max(0, int((ws[0]["start"] - 0.4) * 1000)) if ws else 0
        end = min(length, int((ws[-1]["end"] + 0.6) * 1000)) if ws else length
        ranges = [(start, end)]
        for s in sents:
            text = s["text"].lower()
            hit = next((p for p in avoid if p in text), None)
            if hit and not any(k in text for k in keep):
                a_ms, b_ms = int((s["start"] - 0.15) * 1000), int((s["end"] + 0.15) * 1000)
                ranges = [r for x in ranges for r in ((x[0], min(x[1], a_ms)), (max(x[0], b_ms), x[1])) if
                          r[1] - r[0] >= 500]
                notes.append(f"Removed “{s['text'][:80]}” from {a['filename']} because you asked to avoid “{hit}”.")
        for k, (a_ms, b_ms) in enumerate(ranges):
            cid = f"c{n}" + (chr(ord("a") + k) if len(ranges) > 1 else "")
            inside = [s for s in sents if s["start"] * 1000 >= a_ms - 50 and s["end"] * 1000 <= b_ms + 50]
            kept = [p for p in keep if any(p in s["text"].lower() for s in inside)]
            clips.append({"id": cid, "asset_id": aid, "kind": "video", "in_ms": a_ms, "out_ms": b_ms,
                          "label": a["filename"], "gain_db": 0.0, "include": True, "must_keep": kept})
            outline.append({"clip_id": cid, "label": a["filename"], "duration": round((b_ms - a_ms) / 1000, 1),
                            "summary": inside[0]["text"][:140] if inside else "No speech",
                            "keeps": kept})
        if ws and (start > 500 or length - end > 500):
            notes.append(f"Trimmed silence at the start/end of {a['filename']}.")
    music = None
    if values.get("music") == "supplied" and brief.get("music_asset_id"):
        music = {"asset_id": brief["music_asset_id"], "level_db": float(values.get("music_level_db", -18))}
    plan = {"schema": engine.SCHEMA, "timebase": 1000, "engine": engine.ENGINE,
            "output": {"aspect": values.get("aspect_ratio", "16:9"), "fps": 30},
            "layout": values.get("layout", "fit"), "clips": clips,
            "transition": {"type": t_type, "ms": t_ms},
            "title": {"enabled": bool(values.get("title_card")), "text": project["name"], "ms": 2500},
            "captions": {"enabled": values.get("captions", True), "style": values.get("caption_style", "clean"),
                         "position": values.get("caption_position", "bottom")},
            "music": music, "outline": outline, "notes": notes}
    total = engine.duration_ms(plan) / 1000
    target = float(values.get("target_duration_s") or 0)
    if target and total > target * 1.1:
        plan["notes"].append(f"The rough cut is {total / 60:.1f} min; you asked for about {target / 60:.1f} min. "
                             "Shorten the introduction or remove clips below; nothing is cut without you.")
    elif target and total < target * 0.9:
        plan["notes"].append(f"Your footage adds up to {total / 60:.1f} min, shorter than the {target / 60:.1f} min "
                             "you asked for. Nothing is invented to fill the difference.")
    return plan


def _assets(project: dict) -> dict[str, dict]:
    ids = list(project["asset_ids"]) + ([(project.get("brief") or {}).get("music_asset_id")]
                                        if (project.get("brief") or {}).get("music_asset_id") else [])
    out = {}
    for aid in ids:
        a = db.fetch("assets", aid)
        if a and a["workspace_id"] == project["workspace_id"]:
            out[aid] = a
    return out


def save_revision(project_id: str, plan: dict, note: str, base: int | None) -> int:
    row = db.fetch("studio_projects", project_id)
    if base is not None and base != row["plan_revision"]:
        raise Conflict(f"This video was changed elsewhere (now revision {row['plan_revision']}). Reload it to see "
                       "the newer edit; nothing was overwritten.")
    rev = row["plan_revision"] + 1
    db.execute("INSERT INTO edit_plans (project_id, revision, plan, note, created_at) VALUES (?, ?, ?, ?, ?)",
               (project_id, rev, json.dumps(plan), note[:300], time.time()))
    changed = db.execute("UPDATE studio_projects SET plan_revision = ?, updated_at = ? WHERE id = ? AND "
                         "plan_revision = ?", (rev, time.time(), project_id, row["plan_revision"]))
    if not changed:
        db.execute("DELETE FROM edit_plans WHERE project_id = ? AND revision = ?", (project_id, rev))
        raise Conflict("This video was changed elsewhere at the same moment. Reload it and try again.")
    return rev


def plan_at(project_id: str, revision: int) -> dict:
    rows = db.select("edit_plans", "project_id = ? AND revision = ?", (project_id, revision))
    if not rows:
        raise VideoError("That version of the plan does not exist.")
    return rows[0]["plan"]


@handler("video_build")
def build(job: dict, lease: Lease) -> dict:
    project = db.fetch("studio_projects", job["target_id"])
    if not project:
        raise VideoError("The project was deleted.")
    settings = db.get_settings()
    assets = _assets(project)
    missing = [aid for aid in project["asset_ids"] if aid not in assets]
    if missing:
        raise VideoError("A file of this project is missing; upload it again.")
    words = {}
    for k, aid in enumerate(project["asset_ids"]):
        lease.progress(0.05 + 0.6 * k / len(project["asset_ids"]), f"Listening to {assets[aid]['filename']}")
        words[aid] = transcript_words(assets[aid], settings, lease)
    lease.progress(0.7, "Building the rough cut")
    plan = rough_cut(project, assets, words)
    rev = save_revision(project["id"], plan, "Rough cut from your brief", None) if project["plan_revision"] == 0 \
        else project["plan_revision"]
    db.update("studio_projects", project["id"], status="ready", message="Rough cut ready; making a preview")
    enqueue(project["workspace_id"], "video_preview", project["id"], rev)
    return {"revision": rev}


# ------------------------------------------------------------------ edits
def _find(plan: dict, clip_id: str) -> dict:
    for c in plan["clips"]:
        if c["id"] == clip_id:
            return c
    raise VideoError("That clip is not in this video.")


def parse_request(text: str) -> dict:
    """A few plain requests turned into validated operations; anything else is explained, not guessed."""
    t = (text or "").lower().strip()
    m = re.search(r"shorten (the )?(intro|introduction|opening|start)( by (\d+(\.\d+)?) ?(s|sec|seconds?))?", t)
    if m:
        return {"op": "shorten_intro", "seconds": float(m.group(4) or 5)}
    m = re.search(r"remove (clip )?(\d+)", t)
    if m:
        return {"op": "remove_index", "index": int(m.group(2))}
    m = re.search(r"\b(no|turn off|remove the|without) captions\b", t)
    if m:
        return {"op": "set", "field": "captions", "value": False}
    if re.search(r"\b(add|turn on) captions\b", t):
        return {"op": "set", "field": "captions", "value": True}
    raise VideoError("ClipForge cannot do that as a request yet. Use the controls: trim, move, keep or remove a "
                     "clip, shorten the introduction, transitions, captions and music level.")


def apply_edit(plan: dict, edit: dict, words: dict[str, list[dict]]) -> tuple[dict, str]:
    """(next plan, what changed). Raises VideoError for anything the plan or the engine does not support."""
    p = copy.deepcopy(plan)
    op = edit.get("op")
    if op == "request":
        return apply_edit(plan, parse_request(edit.get("text", "")), words)
    if op == "remove_index":
        included = [c for c in p["clips"] if c.get("include", True)]
        idx = int(edit.get("index") or 0)
        if not 1 <= idx <= len(included):
            raise VideoError(f"There is no clip {idx}.")
        edit = {"op": "remove", "clip_id": included[idx - 1]["id"]}
        op = "remove"
    if op == "remove":
        c = _find(p, edit["clip_id"])
        if c.get("must_keep"):
            raise VideoError(f"You asked to keep “{c['must_keep'][0]}”, which is in this clip. Change the brief first.")
        c["include"] = False
        return p, f"Removed {c['label']}"
    if op == "include":
        c = _find(p, edit["clip_id"])
        c["include"] = True
        return p, f"Put back {c['label']}"
    if op == "trim":
        c = _find(p, edit["clip_id"])
        a, b = int(edit["in_ms"]), int(edit["out_ms"])
        if b - a < 500:
            raise VideoError("A clip must stay at least half a second long.")
        c["in_ms"], c["out_ms"] = a, b
        return p, f"Trimmed {c['label']}"
    if op == "keep":  # keep only this section of a clip
        c = _find(p, edit["clip_id"])
        a, b = int(edit["in_ms"]), int(edit["out_ms"])
        if not (c["in_ms"] <= a < b <= c["out_ms"]) or b - a < 500:
            raise VideoError("Choose a section inside the clip.")
        c["in_ms"], c["out_ms"] = a, b
        return p, f"Kept only part of {c['label']}"
    if op == "move":
        c = _find(p, edit["clip_id"])
        p["clips"].remove(c)
        to = max(0, min(int(edit.get("to", 0)), len(p["clips"])))
        p["clips"].insert(to, c)
        return p, f"Moved {c['label']}"
    if op == "split":
        c = _find(p, edit["clip_id"])
        at = int(edit["at_ms"])
        if not c["in_ms"] + 500 <= at <= c["out_ms"] - 500:
            raise VideoError("Split at least half a second inside the clip.")
        second = {**copy.deepcopy(c), "id": c["id"] + "s", "in_ms": at}
        c["out_ms"] = at
        p["clips"].insert(p["clips"].index(c) + 1, second)
        return p, f"Split {c['label']}"
    if op == "shorten_intro":
        first = next((c for c in p["clips"] if c.get("include", True) and c.get("kind") == "video"), None)
        if first is None:
            raise VideoError("There is no video clip to shorten.")
        if first.get("must_keep"):
            raise VideoError("The introduction holds something you asked to keep.")
        want = int(float(edit.get("seconds") or 5) * 1000)
        # cut at a sentence start, never inside a word
        starts = [int(s["start"] * 1000) - 150 for s in _sentences(words.get(first["asset_id"]) or [])
                  if first["in_ms"] + 300 < s["start"] * 1000 < first["out_ms"] - 1000]
        candidates = [s for s in starts if s - first["in_ms"] <= want + 1500]
        if not candidates:
            raise VideoError("The introduction has no sentence boundary to cut at within that length.")
        new_in = max(candidates)
        removed = (new_in - first["in_ms"]) / 1000
        first["in_ms"] = new_in
        return p, f"Shortened the introduction by {removed:.1f} s (at a sentence start)"
    if op == "set":
        field, value = edit.get("field"), edit.get("value")
        if field == "captions" and type(value) is bool:
            p["captions"]["enabled"] = value
        elif field == "caption_position" and value in ("bottom", "middle", "top"):
            p["captions"]["position"] = value
        elif field == "transition" and value in engine.TRANSITIONS:
            p["transition"] = {"type": value, "ms": 0 if value == "cut" else 400}
        elif field == "music_level_db" and isinstance(value, (int, float)) and -36 <= value <= -6 and p.get("music"):
            p["music"]["level_db"] = float(value)
        elif field == "gain_db" and isinstance(value, (int, float)) and -12 <= value <= 12:
            _find(p, edit["clip_id"])["gain_db"] = float(value)
        elif field == "aspect" and value in engine.ASPECTS:
            p["output"]["aspect"] = value
        else:
            raise VideoError(f"“{field}” cannot be set to that.")
        return p, f"Changed {field}"
    if op in engine.UNSUPPORTED:
        raise VideoError(f"{engine.UNSUPPORTED[op].capitalize()} is not supported by this editor yet.")
    raise VideoError("Unknown edit.")


def edit(project_id: str, base_revision: int, change: dict) -> dict:
    project = db.fetch("studio_projects", project_id)
    if not project or not project["plan_revision"]:
        raise VideoError("The rough cut is not ready yet.")
    plan = plan_at(project_id, project["plan_revision"])
    assets = _assets(project)
    words = {aid: transcript_words(a, db.get_settings(), cached_only=True) for aid, a in assets.items()
             if a["kind"] == "video"}
    new, note = apply_edit(plan, change, words)
    problems = engine.validate(new, assets)
    if problems:
        raise VideoError("; ".join(problems))
    rev = save_revision(project_id, new, note, base_revision)
    enqueue(project["workspace_id"], "video_preview", project_id, rev)
    return {"revision": rev, "note": note}


# ------------------------------------------------------------------ renders
def _render(job: dict, lease: Lease, preview: bool) -> dict:
    project = db.fetch("studio_projects", job["target_id"])
    if not project:
        raise VideoError("The project was deleted.")
    kind = "preview" if preview else "final"
    existing = db.select("studio_artifacts", "project_id = ? AND revision = ? AND kind = ?",
                         (project["id"], job["revision"], kind))
    if existing:
        return {"artifact": existing[0]["id"]}  # already rendered: idempotent
    plan = plan_at(project["id"], job["revision"])
    assets = _assets(project)
    settings = db.get_settings()
    words = {aid: transcript_words(a, settings) for aid, a in assets.items() if a["kind"] == "video"}
    folder = video_dir(project["id"]) / f"r{job['revision']}"
    out = folder / f"{kind}.mp4"
    if not preview:
        db.update("studio_projects", project["id"], status="rendering", message="Rendering the final video")
    try:
        info = engine.render(plan, assets, words, out, preview=preview, settings=settings,
                             progress=lambda f: lease.progress(f * 0.95, "Rendering preview" if preview else
                                                               "Rendering"),
                             cancelled=lease.canceled)
    except BaseException as exc:
        if not preview:  # the plan and any earlier finished version stay as they were
            canceled = lease.canceled()
            db.update("studio_projects", project["id"], status="ready",
                      message="Render canceled; nothing changed" if canceled else f"Render failed: {str(exc)[:200]}")
        out.unlink(missing_ok=True)
        raise
    if abs(info["duration"] - info["expected_duration"]) > 0.2:
        raise VideoError(f"The render is {info['duration']:.2f} s instead of {info['expected_duration']:.2f} s.")
    sha = artifact.sha256_file(out)
    (folder / f"{kind}.timeline.json").write_text(json.dumps({"timeline": info["timeline"], "words": info["words"]}))
    if not lease.alive():
        raise VideoError("This render lost its lease; another worker owns it.")
    db.execute("INSERT OR IGNORE INTO studio_artifacts (id, project_id, revision, kind, path, sha256, info, "
               "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
               ("art-" + os.urandom(6).hex(), project["id"], job["revision"], kind, str(out), sha,
                json.dumps({k: v for k, v in info.items() if k != "words"}), time.time()))
    if not preview:
        db.update("studio_projects", project["id"], status="ready", rendered_revision=job["revision"],
                  message=f"Version {job['revision']} rendered and checked")
    return {"sha256": sha, "duration": info["duration"]}


@handler("video_preview")
def preview_job(job: dict, lease: Lease) -> dict:
    return _render(job, lease, True)


@handler("video_render")
def render_job(job: dict, lease: Lease) -> dict:
    return _render(job, lease, False)


def view(project: dict) -> dict:
    rev = project["plan_revision"]
    plan = plan_at(project["id"], rev) if rev else None
    arts = db.select("studio_artifacts", "project_id = ?", (project["id"],), "revision DESC")
    jobs = db.select("studio_jobs", "target_id = ?", (project["id"],), "created_at DESC", 10)
    revisions = [{"revision": r["revision"], "note": r["note"], "created_at": r["created_at"]}
                 for r in db.select("edit_plans", "project_id = ?", (project["id"],), "revision DESC")]
    assets = _assets(project)
    return {**{k: project[k] for k in ("id", "name", "status", "message", "asset_ids", "brief", "plan_revision",
                                       "rendered_revision", "created_at", "updated_at")},
            "guidance": project.get("guidance") or {}, "plan": plan,
            "duration": engine.duration_ms(plan) / 1000 if plan else 0,
            "assets": [uploads.asset_view(a) for a in assets.values()],
            "artifacts": [{"id": a["id"], "revision": a["revision"], "kind": a["kind"], "sha256": a["sha256"],
                           "duration": (a.get("info") or {}).get("duration"),
                           "audio_ok": ((a.get("info") or {}).get("audio_timing") or {}).get("valid")}
                          for a in arts],
            "jobs": [{k: j[k] for k in ("id", "kind", "revision", "status", "progress", "message", "error")}
                     for j in jobs],
            "revisions": revisions, "capabilities": engine.capabilities()}

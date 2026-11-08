"""Make a YouTube video: media bin + four-question brief → outline → rough cut → preview → validated edits → render.

Plans are saved as immutable revisions (edit_plans); an edit is a validated operation that produces the next
revision, and an unsupported request is explained while the current revision stays as it is. Undo, redo and going
back to an older version also save a new revision, so nothing in between is lost and the revision number only ever
grows (a stale tab can never overwrite newer work). Renders are durable jobs bound to one revision; a finished render
is an immutable artifact with its exact hash, probe, time map, final transcript and audio checks. The previous
finished artifact stays available until a new render passes its checks.

The project's media bin holds every file you added (videos, images and audio), before or after the rough cut; the
plan references files from it. Audio is not one optional music field: voiceovers, music and effects are items on
their own tracks, with gain, mute, fades, ducking and loops (engine.py renders them).

Nothing is invented: no narration, statements or endings are generated; a length target the footage cannot meet is
explained, not filled.

With smart editing on (the brief's "How much should ClipForge edit?"), the rough cut is made by smart_edit.py: it
cuts dead air and repeated takes, fits the length, shows your images over the video, and adds music and soft sound
effects (your own, or free ones ClipForge makes on this computer, library.py), optionally helped by ClipForge AI
from Settings (ai_editor.py). "Edit it for me" on the editor page runs the same edit again on any project, as a new
version that Undo reverts. With a script (`script`, read by script.py), script_cut.py makes the cut instead: one
clip per script line in script order, the best take of each, the other takes behind it to swap in (`use_take`).

Every video is listened to once per file content (`listen`): its 16 kHz sound and transcript live in the asset's
work folder (uploads.work_dir), a long file is transcribed in pieces that survive a restart, and the speech model
is released when the batch is done so the local AI model has the memory.
"""
from __future__ import annotations

import logging

import copy
import hashlib
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
                "title_card", "music_level_db", "layout", "caption_size", "frame_rate", "duck_music",
                "voiceover_asset_ids", "duck_depth_db", "shot_length_s", "find_media", "smart_edit", "cut_pauses",
                "cut_retakes", "fit_length", "punch_in", "sound_effects", "broll_images", "ai_edit", "cold_open",
                "open_with", "plan"}
OPEN_WITH_CHARS = 200    # the brief's `open_with`: how the owner wants the video to open (their words)
PLAN_WORDS = {"summary": 300, "opening": 200}       # the brief's `plan`: the owner's plan made with ClipForge AI
PLAN_LISTS = {"story": (8, 160), "notes": (6, 200)}  # (video_setup.py), read by ClipForge AI's edit
SMART_OPTIONS = {"smart_edit": ("off", "smart", "tight"), "music": ("none", "supplied", "find", "auto", "library"),
                 "cut_pauses": (True, False), "cut_retakes": (True, False), "fit_length": (True, False),
                 "punch_in": (True, False), "sound_effects": (True, False), "broll_images": (True, False),
                 "ai_edit": (True, False), "cold_open": (True, False)}
SCRIPT_KINDS = ("line", "heading", "direction")
STYLE_CHOICES = {"aspect_ratio", "feel", "captions", "music", "caption_style", "caption_position", "transition",
                 "title_card", "music_level_db", "layout", "target_duration_s", "video_type", "audience",
                 "caption_size", "frame_rate", "duck_music", "duck_depth_db", "shot_length_s", "smart_edit",
                 "punch_in", "sound_effects", "broll_images"}
AUDIO_DEFAULTS = {"voiceover": {"gain_db": 0.0, "duck": False, "loop": False},
                  "music": {"gain_db": -18.0, "duck": True, "loop": True},
                  "effect": {"gain_db": 0.0, "duck": False, "loop": False}}


class VideoError(ValueError):
    pass


class Conflict(VideoError):
    pass


HAND_KEEPS = ("filmcraft", "undo", "redo", "restore")


def filmcraft_saves(project_id: str) -> Path:
    """Where the projects saved in FilmCraft's editor are kept (by content hash; one never changes)."""
    return video_dir(project_id) / "filmcraft" / "saves"


def video_dir(project_id: str) -> Path:
    d = config.data_dir() / "videos" / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ transcripts (cached per asset content)
def transcript_words(asset: dict, settings: dict, lease: Lease | None = None, cached_only: bool = False,
                     lo: float = 0.05, hi: float = 0.45) -> list[dict]:
    """Timed words of a video asset, transcribed once per file content and reused by every project. The 16 kHz
    sound and the transcript live in the asset's work folder (uploads.work_dir: never beside a linked file); a
    long file is transcribed in pieces saved as they finish, so a crash or a closed app loses at most one piece.
    Progress goes to lo..hi of the lease. `cached_only`: never transcribe (request handlers read what the build job
    already made). The speech model stays loaded for the next file; `listen` releases it after a batch."""
    from ..pipeline import transcribe
    from ..pipeline.common import JobContext, read_json, write_json

    if asset["kind"] != "video" or not (asset.get("probe") or {}).get("has_audio"):
        return []
    folder = uploads.work_dir(asset)
    cache = folder / "transcript.json"
    data = read_json(cache, None)
    if data is None and cached_only:
        return []
    if data is None:
        wav = folder / "audio.wav"
        duration = float(asset["probe"].get("duration") or 0)
        name = asset.get("filename") or "the file"
        if not wav.exists():
            extract_audio(Path(asset["path"]), wav, duration,
                          progress=(lambda f: lease.progress(lo + (hi - lo) * 0.1 * f, f"Reading the sound of {name}"))
                          if lease else None, cancel=lease.canceled if lease else None)
        ctx = JobContext((lambda f, m: lease.progress(f, m)) if lease else None,
                         (lambda: lease.canceled()) if lease else None)
        data = transcribe.transcribe_long(wav, duration, settings, ctx, parts_dir=folder / "transcript.parts",
                                          lo=lo + (hi - lo) * 0.1, hi=hi, label=f"Listening to {name}")
        write_json(cache, data)
    return transcribe.flatten_words(data)


def listen(assets: dict[str, dict], ids, settings: dict, lease: Lease | None = None, lo: float = 0.05,
           hi: float = 0.65) -> dict[str, list[dict]]:
    """The words of these assets ({asset id: words}; [] for anything that is not a video with sound), each
    transcribed once and cached; progress for the batch goes to lo..hi of the lease, file by file. The speech
    model is held across the files and released when the batch is done, whatever happened."""
    from ..pipeline import transcribe

    ids = [aid for aid in dict.fromkeys(ids) if aid in assets]
    videos = [aid for aid in ids if assets[aid]["kind"] == "video"]
    words: dict[str, list[dict]] = {aid: [] for aid in ids}
    try:
        span = (hi - lo) / max(1, len(videos))
        for k, aid in enumerate(videos):
            if lease:
                lease.progress(lo + span * k, f"Listening to {assets[aid]['filename']}")
            words[aid] = transcript_words(assets[aid], settings, lease, lo=lo + span * k, hi=lo + span * (k + 1))
    finally:
        transcribe.release_model()
    return words


# ------------------------------------------------------------------ creating a project
def _owned(workspace_id: str, aid: str) -> dict:
    try:
        return uploads.asset(aid, workspace_id)
    except uploads.UploadError as exc:
        raise VideoError(str(exc)) from exc


def script_payload(script) -> dict:
    """The script a project follows, checked: script.parse's result from the Script panel ({"filename", "format",
    "text", "lines", "counts"}) or just {"text": ...} (read here), trimmed to what the cut needs and numbered
    again; the words each line is matched on are always worked out here. {} for no script."""
    from . import script as script_mod

    if script in (None, "", {}):
        return {}
    if not isinstance(script, dict):
        raise VideoError("The script must be a script file as ClipForge read it, or its text.")
    lines = script.get("lines")
    if not lines and isinstance(script.get("text"), str) and script["text"].strip():
        try:
            lines = script_mod.parse(str(script.get("filename") or "script.txt"), script["text"])["lines"]
        except script_mod.ScriptError as exc:
            raise VideoError(str(exc)) from exc
    if not isinstance(lines, list) or not lines:
        raise VideoError("The script has no lines.")
    if len(lines) > script_mod.MAX_LINES:
        raise VideoError(f"The script has more than {script_mod.MAX_LINES:,} lines; give only the part this video "
                         "follows.")
    out: list[dict] = []
    for ln in lines:
        if not isinstance(ln, dict) or not isinstance(ln.get("text"), str):
            raise VideoError("Each script line needs its text.")
        text = " ".join(ln["text"].split())[:2000]
        if not text:
            continue
        kind = ln.get("kind") if ln.get("kind") in SCRIPT_KINDS else "line"
        out.append({"n": len(out) + 1, "text": text, "kind": kind, "speaker": str(ln.get("speaker") or "")[:60],
                    "section": str(ln.get("section") or "")[:200], "tokens": script_mod.normalize(text)})
    if not out:
        raise VideoError("The script has no text.")
    text = str(script.get("text") or "")[:script_mod.MAX_CHARS] or "\n".join(ln["text"] for ln in out)
    return {"filename": str(script.get("filename") or "script.txt")[:200],
            "format": str(script.get("format") or "txt")[:10], "text": text, "lines": out,
            "counts": {"lines": sum(1 for ln in out if ln["kind"] == "line"),
                       "headings": sum(1 for ln in out if ln["kind"] == "heading"),
                       "directions": sum(1 for ln in out if ln["kind"] == "direction"),
                       "words": sum(len(ln["text"].split()) for ln in out if ln["kind"] == "line")}}


def plan_words(value) -> dict:
    """The owner's plan words a brief carries for ClipForge AI's edit (`brief.plan`, made on the setup page by
    video_setup.py): what the video is, how it opens, the story in order and notes, each bounded. {} for none."""
    if value in (None, "", {}):
        return {}
    if not isinstance(value, dict):
        raise VideoError("The plan must be a JSON object.")
    out: dict = {}
    for key, limit in PLAN_WORDS.items():
        if isinstance(value.get(key), str) and value[key].strip():
            out[key] = " ".join(value[key].split())[:limit]
    for key, (count, size) in PLAN_LISTS.items():
        items = value.get(key)
        if items in (None, ""):
            continue
        if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
            raise VideoError(f"The plan's {key} must be a list of short texts.")
        kept = [" ".join(x.split())[:size] for x in items if x.strip()][:count]
        if kept:
            out[key] = kept
    return out


def check_brief(workspace_id: str, brief: dict) -> dict:
    """The brief, checked (unknown fields, music, supporting media, the smart-editing choices, voiceovers, the
    opening and the plan words) and returned with its plan words bounded. Raises VideoError."""
    if not isinstance(brief, dict):
        raise VideoError("The brief must be a JSON object.")
    unknown = set(brief) - BRIEF_FIELDS
    if unknown:
        raise VideoError("Unknown brief fields: " + ", ".join(sorted(unknown)))
    if brief.get("music") == "supplied":
        try:
            m = uploads.asset(str(brief.get("music_asset_id") or ""), workspace_id)
        except uploads.UploadError as exc:
            raise VideoError("Upload the music file you want to use.") from exc
        if m["kind"] != "audio":
            raise VideoError("The music must be an audio file.")
    if brief.get("find_media") not in (None, "", "off", "suggest", "auto"):
        raise VideoError("Supporting media: choose off, suggest for review, or add eligible media automatically.")
    if brief.get("music") not in (None, "", "none", "supplied", "find", "auto", "library"):
        raise VideoError("Music: choose none, your own file, free music made by ClipForge, pick for me, or find "
                         "music for me.")
    for key, allowed in SMART_OPTIONS.items():
        if key != "music" and brief.get(key) not in (None, "", *allowed):
            raise VideoError(f"“{key}” must be one of: {', '.join(map(str, allowed))}.")
    voiceovers = brief.get("voiceover_asset_ids") or []
    if not isinstance(voiceovers, list):
        raise VideoError("Voiceovers must be a list of audio files.")
    for aid in voiceovers:
        if _owned(workspace_id, str(aid))["kind"] != "audio":
            raise VideoError("A voiceover must be an audio file.")
    opening = brief.get("open_with")
    if opening not in (None, "") and (not isinstance(opening, str) or len(opening) > OPEN_WITH_CHARS):
        raise VideoError(f"How the video opens must be text of at most {OPEN_WITH_CHARS} characters.")
    out = dict(brief)
    if "plan" in out:
        out["plan"] = plan_words(out["plan"])
        if not out["plan"]:
            out.pop("plan")
    return out


def guidance_for(workspace_id: str, name: str, brief: dict, style_id: str = "saved",
                 reference_id: str = "") -> tuple[dict | None, dict, dict]:
    """(the style, the guidance snapshot, the brief's style choices) for a project with this brief: the brief's
    own answers win over the style and the example video."""
    style = styles.default(workspace_id) if style_id == "saved" else (
        styles.get(style_id, workspace_id) if style_id not in ("", "settings") else None)
    choices = {k: v for k, v in brief.items() if k in STYLE_CHOICES and v not in (None, "")}
    from . import reference, skills

    try:
        examples = reference.guidance_inputs(workspace_id, "full_video", reference_id)
    except reference.ReferenceError as exc:
        raise VideoError(str(exc)) from exc
    snapshot = guidance.resolve("full_video", project_choices=choices, style=style,
                                global_skills=skills.enabled_skills(workspace_id),
                                context={"title": name, "caption_text": brief.get("goal") or ""}, **examples)
    if snapshot["problems"]:
        raise VideoError("; ".join(snapshot["problems"]))
    return style, snapshot, choices


def remember_style(workspace_id: str, user_id: str, name: str, choices: dict, remember: dict | None) -> None:
    """Save the brief's look as a style when the owner wants that (their last choice is the next default)."""
    remember = remember or {}
    pref = prefs.get_appearance(workspace_id, user_id)["value"]
    if remember.get("enabled", pref.get("remember_style", True)):
        styles.remember_from_brief(workspace_id, (remember.get("name") or f"{name} style")[:60], choices,
                                   "full_video")
    if "enabled" in remember:  # the owner's explicit choice is the next brief's default
        prefs.set_appearance(workspace_id, user_id, {"remember_style": bool(remember["enabled"])}, None)


def create(workspace_id: str, user_id: str, *, name: str, asset_ids: list[str], brief: dict, style_id: str = "saved",
           remember: dict | None = None, reference_id: str = "", script=None) -> dict:
    """A new project. `asset_ids` is the media bin in order (any number of videos, images and audio files; the rough
    cut uses the videos and images, audio stays in the bin until you place it, apart from the music and voiceovers
    the brief names). `script`: the script the video follows (script_payload), when there is one."""
    if not asset_ids:
        raise VideoError("Add at least one video or image.")
    script = script_payload(script)
    brief = check_brief(workspace_id, brief)
    asset_ids = list(dict.fromkeys(asset_ids))  # the same file twice is one bin entry
    assets = [_owned(workspace_id, aid) for aid in asset_ids]
    if not any(a["kind"] == "video" for a in assets):
        raise VideoError("Add at least one video; images are inserted between videos.")
    style, snapshot, choices = guidance_for(workspace_id, name, brief, style_id, reference_id)
    project = db.insert("studio_projects", {
        "id": "vid-" + os.urandom(6).hex(), "workspace_id": workspace_id, "name": (name or "My video")[:120],
        "status": "building", "message": "Reading your files", "asset_ids": asset_ids,
        "brief": {k: v for k, v in brief.items() if k in BRIEF_FIELDS}, "style_id": (style or {}).get("id", ""),
        "guidance": snapshot, "script": script,
        "media": {"mode": "auto" if brief.get("find_media") == "auto" else "suggest",
                  "commercial": bool(db.get_settings().get("autopilot_commercial_use", True))}})
    remember_style(workspace_id, user_id, name, choices, remember)
    enqueue(workspace_id, "video_build", project["id"], 0)
    return project


# ------------------------------------------------------------------ the rough cut
def _sentences(words: list[dict]) -> list[dict]:
    from ..pipeline.text_utils import build_sentences

    return build_sentences(words)


def _phrases(text: str) -> list[str]:
    return [p.strip().lower() for p in re.split(r"[,;\n]|\band\b", text or "") if len(p.strip()) >= 3]


def _speech_range(asset: dict, words: list[dict]) -> tuple[int, int]:
    """The part of a file with speech (measured silence at either end kept short), or the whole file."""
    length = engine._length(asset)  # noqa: SLF001 - the engine's own reading of a probe
    if not words:
        return 0, length
    return max(0, int((words[0]["start"] - 0.4) * 1000)), min(length, int((words[-1]["end"] + 0.6) * 1000))


def _shots(span: tuple[int, int], sents: list[dict], target_s: float) -> list[tuple[int, int]]:
    """Split one kept range into shots of about `target_s` at sentence ends (a sentence is never cut), each shot
    trimmed to its speech so the pauses between shots are left out. Without sentences the range stays whole."""
    a_ms, b_ms = span
    inside = [x for x in sents if x["start"] * 1000 >= a_ms - 50 and x["end"] * 1000 <= b_ms + 50]
    if not inside:
        return [span]
    groups: list[list[dict]] = [[inside[0]]]
    for x in inside[1:]:
        if x["end"] - groups[-1][0]["start"] > target_s:
            groups.append([x])
        else:
            groups[-1].append(x)
    out = []
    for g in groups:
        s0 = max(a_ms, int((g[0]["start"] - 0.12) * 1000))
        s1 = min(b_ms, int((g[-1]["end"] + 0.12) * 1000))
        if s1 - s0 >= 300:
            out.append((s0, s1))
    return out or [span]


def _audio_item(item_id: str, asset: dict, role: str, **over) -> dict:
    d = AUDIO_DEFAULTS[role]
    loop = over.get("loop", d["loop"])
    item = {"id": item_id, "asset_id": asset["id"], "role": role, "label": asset["filename"], "start_ms": 0,
            "in_ms": 0, "out_ms": None if loop else engine._length(asset),  # noqa: SLF001
            "length_ms": None, "gain_db": d["gain_db"], "mute": False, "fade_in_ms": 0, "fade_out_ms": 0,
            "duck": d["duck"], "loop": loop, "anchor": None}
    item.update({k: v for k, v in over.items() if k in item})
    return item


def rough_cut(project: dict, assets: dict[str, dict], words: dict[str, list[dict]], smart: dict | None = None) -> dict:
    """Revision 1: the videos and images in the order of the media bin, each trimmed to its speech (measured silence
    kept short), avoid-requests cut out at sentence boundaries, the brief's music and voiceovers on their tracks,
    and the brief/style choices applied. With smart editing on, smart_edit.build makes it instead (`smart`: what
    prepare_smart got ready: ClipForge AI's advice and the music and effects to use)."""
    values = (project.get("guidance") or {}).get("values") or {}
    brief = project.get("brief") or {}
    from . import smart_edit

    if (project.get("script") or {}).get("lines"):
        from . import script_cut

        return script_cut.assemble(project, assets, words, values, project["script"], ctx=smart)
    if smart_edit.options(values, brief)["level"] != "off":
        return smart_edit.build(project, assets, words, values, ctx=smart)
    feel = values.get("feel", "balanced")
    t_type, t_ms = FEEL_TRANSITIONS.get(feel, FEEL_TRANSITIONS["balanced"])
    if values.get("transition"):
        t_type = values["transition"]
        t_ms = 0 if t_type == "cut" else (t_ms or 400)
    avoid, keep = _phrases(brief.get("avoid", "")), _phrases(brief.get("must_keep", ""))
    clips, outline, notes = [], [], []
    for n, aid in enumerate(project["asset_ids"], 1):
        a = assets[aid]
        if a["kind"] == "audio":
            continue  # audio waits in the media bin until it is placed on a track
        if a["kind"] == "image":
            clips.append({"id": f"c{n}", "asset_id": aid, "kind": "image", "in_ms": 0, "out_ms": IMAGE_MS,
                          "label": a["filename"], "gain_db": 0.0, "include": True})
            outline.append({"clip_id": f"c{n}", "label": a["filename"], "summary": "Your image (B-roll)",
                            "duration": IMAGE_MS / 1000})
            continue
        length = engine._length(a)  # noqa: SLF001
        ws = words.get(aid) or []
        sents = _sentences(ws)
        start, end = _speech_range(a, ws)
        ranges = [(start, end)]
        for s in sents:
            text = s["text"].lower()
            hit = next((p for p in avoid if p in text), None)
            if hit and not any(k in text for k in keep):
                a_ms, b_ms = int((s["start"] - 0.15) * 1000), int((s["end"] + 0.15) * 1000)
                ranges = [r for x in ranges for r in ((x[0], min(x[1], a_ms)), (max(x[0], b_ms), x[1])) if
                          r[1] - r[0] >= 500]
                notes.append(f"Removed “{s['text'][:80]}” from {a['filename']} because you asked to avoid “{hit}”.")
        shot_s = float(values.get("shot_length_s") or 0)
        if shot_s and sents:
            before = len(ranges)
            ranges = [r for x in ranges for r in _shots(x, sents, shot_s)]
            if len(ranges) > before:
                notes.append(f"Cut {a['filename']} into {len(ranges)} shots of about {shot_s:g} s at sentence ends, "
                             "leaving out the pauses between them.")
        for k, (a_ms, b_ms) in enumerate(ranges):
            cid = f"c{n}" + ((chr(ord("a") + k) if len(ranges) <= 26 else f"-{k + 1}") if len(ranges) > 1 else "")
            inside = [s for s in sents if s["start"] * 1000 >= a_ms - 50 and s["end"] * 1000 <= b_ms + 50]
            kept = [p for p in keep if any(p in s["text"].lower() for s in inside)]
            clips.append({"id": cid, "asset_id": aid, "kind": "video", "in_ms": a_ms, "out_ms": b_ms,
                          "label": a["filename"], "gain_db": 0.0, "include": True, "must_keep": kept})
            outline.append({"clip_id": cid, "label": a["filename"], "duration": round((b_ms - a_ms) / 1000, 1),
                            "summary": inside[0]["text"][:140] if inside else "No speech",
                            "keeps": kept})
        if ws and (start > 500 or length - end > 500):
            notes.append(f"Trimmed silence at the start/end of {a['filename']}.")
    audio = []
    if values.get("music") == "supplied" and brief.get("music_asset_id") in assets:
        audio.append(_audio_item("a1", assets[brief["music_asset_id"]], "music",
                                 gain_db=float(values.get("music_level_db", -18)),
                                 duck=bool(values.get("duck_music", True))))
    at = 0
    for aid in brief.get("voiceover_asset_ids") or []:  # one after another from the start, as you listed them
        if aid in assets:
            item = _audio_item(f"a{len(audio) + 1}", assets[aid], "voiceover", start_ms=at)
            audio.append(item)
            at += engine.item_length(item) or 0
    plan = {"schema": engine.SCHEMA, "timebase": 1000, "engine": engine.ENGINE,
            "output": {"aspect": values.get("aspect_ratio", "16:9"), "fps": int(values.get("frame_rate") or 30)},
            "layout": values.get("layout", "fit"), "clips": clips,
            "transition": {"type": t_type, "ms": t_ms},
            "title": {"enabled": bool(values.get("title_card")), "text": project["name"], "ms": 2500},
            "captions": {"enabled": values.get("captions", True), "style": values.get("caption_style", "clean"),
                         "position": values.get("caption_position", "bottom"),
                         "size": values.get("caption_size", "medium")},
            "audio": audio, "tracks": engine.default_tracks(), "word_fixes": {},
            "ducking": {"depth_db": float(values.get("duck_depth_db", engine.DUCK_DEPTH_DB))},
            "outline": outline, "notes": notes}
    total = engine.duration_ms(plan) / 1000
    target = float(values.get("target_duration_s") or 0)
    if target and total > target * 1.1:
        plan["notes"].append(f"The rough cut is {total / 60:.1f} min; you asked for about {target / 60:.1f} min. "
                             "Shorten the introduction or remove clips below; nothing is cut without you.")
    elif target and total < target * 0.9:
        plan["notes"].append(f"Your footage adds up to {total / 60:.1f} min, shorter than the {target / 60:.1f} min "
                             "you asked for. Nothing is invented to fill the difference.")
    music = (smart or {}).get("music") or {}
    if not any(i["role"] == "music" for i in audio) and music.get("asset_id") in assets:
        m = assets[music["asset_id"]]
        audio.append({**_audio_item(f"a{len(audio) + 1}", m, "music",
                                    gain_db=float(values.get("music_level_db", -20 if music.get("how") == "library"
                                                             else -18)),
                                    duck=bool(values.get("duck_music", True)), fade_in_ms=1500, fade_out_ms=2500),
                      "auto": True})
        plan["notes"].append(f"Added {'free background music' if music.get('how') == 'library' else 'your music file'} "
                             f"“{m['filename']}” under the whole video; it dips while people speak.")
    vo_end = max((i["start_ms"] + (engine.item_length(i) or 0) for i in audio if i["role"] == "voiceover"),
                 default=0)
    if vo_end > total * 1000 + 100:
        plan["notes"].append(f"Your voiceovers last {vo_end / 1000:.1f} s and the pictures {total:.1f} s; the "
                             "video ends with the pictures. Add footage or move a voiceover.")
    return plan


def _assets(project: dict, plan: dict | None = None) -> dict[str, dict]:
    """The project's files: its media bin, the brief's music and voiceovers, and anything a plan references."""
    brief = project.get("brief") or {}
    ids = list(project["asset_ids"]) + ([brief["music_asset_id"]] if brief.get("music_asset_id") else []) + \
        list(brief.get("voiceover_asset_ids") or [])
    if plan:
        ids += [c["asset_id"] for c in plan.get("clips") or []] + [i["asset_id"] for i in plan.get("audio") or []]
        ids += [o["asset_id"] for o in plan.get("overlays") or []]
        if plan.get("music"):
            ids.append(plan["music"].get("asset_id"))
    out = {}
    for aid in dict.fromkeys(i for i in ids if i):
        a = db.fetch("assets", aid)
        if a and a["workspace_id"] == project["workspace_id"]:
            out[aid] = a
    return out


def _revision_row(project_id: str, revision: int) -> dict:
    rows = db.select("edit_plans", "project_id = ? AND revision = ?", (project_id, revision))
    if not rows:
        raise VideoError("That version of the plan does not exist.")
    return rows[0]


def _meta(row: dict) -> dict:
    """How a revision was made. Revisions saved before undo existed lead back to the one before them."""
    meta = row.get("meta") or {}
    if not meta:
        meta = {"action": "edit", "prev": row["revision"] - 1 if row["revision"] > 1 else None, "redo": None}
    return meta


def save_revision(project_id: str, plan: dict, note: str, base: int | None, meta: dict | None = None) -> int:
    """Save `plan` as the next version. A version finished by hand in FilmCraft (`plan["filmcraft"]`) stays so only
    when it is saved from FilmCraft or reopened as it was (undo, redo, going back); any other edit starts again from
    ClipForge's own cut, and the FilmCraft version stays in the history."""
    if (meta or {}).get("action") not in HAND_KEEPS and "filmcraft" in plan:
        plan = {k: v for k, v in plan.items() if k != "filmcraft"}
    row = db.fetch("studio_projects", project_id)
    if base is not None and base != row["plan_revision"]:
        raise Conflict(f"This video was changed elsewhere (now revision {row['plan_revision']}). Reload it to see "
                       "the newer edit; nothing was overwritten.")
    rev = row["plan_revision"] + 1
    meta = meta if meta is not None else {"action": "edit", "prev": row["plan_revision"] or None, "redo": None}
    db.execute("INSERT INTO edit_plans (project_id, revision, plan, note, created_at, meta) VALUES (?, ?, ?, ?, ?, ?)",
               (project_id, rev, json.dumps(plan), note[:300], time.time(), json.dumps(meta)))
    changed = db.execute("UPDATE studio_projects SET plan_revision = ?, updated_at = ? WHERE id = ? AND "
                         "plan_revision = ?", (rev, time.time(), project_id, row["plan_revision"]))
    if not changed:
        db.execute("DELETE FROM edit_plans WHERE project_id = ? AND revision = ?", (project_id, rev))
        raise Conflict("This video was changed elsewhere at the same moment. Reload it and try again.")
    return rev


def plan_at(project_id: str, revision: int) -> dict:
    """The plan of one revision, in the current schema (older revisions are upgraded when read, never rewritten)."""
    return engine.upgrade(_revision_row(project_id, revision)["plan"])


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
    words = listen(assets, project["asset_ids"], settings, lease, 0.05, 0.65)
    if (project.get("setup") or {}).get("pending"):
        # "Just do it" before ClipForge AI had planned: it plans now, having heard every file (video_setup.py)
        from . import video_setup

        project = video_setup.plan_in_build(project, assets, words, settings, lease)
        assets = _assets(project)
    lease.progress(0.7, "Building the rough cut")
    smart = prepare_smart(project, assets, words, settings, lease)
    plan = rough_cut(db.fetch("studio_projects", project["id"]), assets, words, smart)
    rev = save_revision(project["id"], plan, "Rough cut from your brief", None,
                        {"action": "build", "prev": None, "redo": None}) if project["plan_revision"] == 0 \
        else project["plan_revision"]
    db.update("studio_projects", project["id"], status="ready", message="Rough cut ready; making a preview")
    enqueue(project["workspace_id"], "video_preview", project["id"], rev)
    if (project.get("brief") or {}).get("find_media") in ("suggest", "auto") and \
            not db.scalar("SELECT 1 FROM media_suggestions WHERE project_id = ?", (project["id"],)):
        # the one supporting-media step you asked for; never repeated per render
        from . import media_sources
        media_sources.find_for_project(project["id"], project["workspace_id"])
    return {"revision": rev}


SMART_KNOWHOW_CHARS = 700  # built-in know-how (brain/knowhow.py) read by smart-edit advice, per window


def _smart_knowhow(brief: dict) -> str:
    """The built-in playbooks that fit this video's brief (talking heads, endings, pacing by default). Never fails
    the edit."""
    from ..brain import knowhow

    try:
        asked = " ".join(str(brief.get(k) or "") for k in ("video_type", "goal", "audience", "avoid")).strip()
        return knowhow.select(asked, "smart_edit", limit=2, budget_chars=SMART_KNOWHOW_CHARS).prompt()
    except Exception:  # noqa: BLE001
        logging.getLogger("clipfoundry.studio.video_flow").exception("know-how failed")
        return ""


def _smart_memories(project: dict, brief: dict) -> str:
    """What the owner told ClipForge AI that applies to editing this video: rules and facts, briefly
    (docs/clipforge/CLIPFORGE_AI.md). Never fails the edit."""
    from .. import brain as ai_brain

    try:
        asked = " ".join(str(brief.get(k) or "") for k in ("video_type", "goal", "audience", "avoid")).strip()
        rec = ai_brain.recall(asked or "editing this video", project["workspace_id"], project_id=project["id"],
                              mode="video", kinds=("rule", "fact"), limit=4, budget_chars=500)
        if rec.ids:
            ai_brain.record_use(project["workspace_id"], rec.ids, "smart_edit", project["id"])
        return rec.prompt()
    except Exception:  # noqa: BLE001
        logging.getLogger("clipfoundry.studio.video_flow").exception("recall failed")
        return ""


def prepare_smart(project: dict, assets: dict[str, dict], words: dict[str, list[dict]], settings: dict,
                  lease: Lease | None = None) -> dict:
    """What a smart edit needs besides the transcripts: ClipForge AI's advice (when one is set up and allowed), and
    the music and sound effects it will use, stored as assets and added to the project's media (`assets` is
    updated in place). Empty when smart editing is off."""
    from . import ai_editor, library, smart_edit

    values = (project.get("guidance") or {}).get("values") or {}
    brief = project.get("brief") or {}
    opts = smart_edit.options(values, brief)
    off = opts["level"] == "off"
    if off and (brief.get("music") or values.get("music")) not in ("auto", "library"):
        return {}  # clips kept as they are get music only when it was asked for
    ctx: dict = {}
    if off or (project.get("script") or {}).get("lines"):  # clips as they are, or the script decides: no advice
        pass
    elif opts["ai"] and ai_editor.configured(settings):
        table = smart_edit.sentence_table(project, assets, words)
        keep = [p.strip().lower() for p in re.split(r"[,;\n]|\band\b", brief.get("must_keep") or "")
                if len(p.strip()) >= 3]
        if table:
            if lease:
                lease.progress(0.72, "ClipForge AI is reading what is said")
            # what the rules already leave out (retakes, warm-ups, chatter) is not sent
            skip = smart_edit.dropped_by_rules(smart_edit.judge_sentences(project, assets, words, values), table)
            try:
                ctx["ai"] = ai_editor.advise(
                    table, {**brief, **{k: values[k] for k in ("video_type", "audience", "target_duration_s")
                                        if k in values and not brief.get(k)}}, settings,
                    protected={s["i"] for s in table if any(p in s["text"].lower() for p in keep)},
                    heartbeat=(lambda m: lease.progress(0.74, m)) if lease else None,
                    canceled=lease.canceled if lease else None, memories=_smart_memories(project, brief),
                    knowhow=_smart_knowhow(brief), skip=skip)
            except ai_editor.AdviceError as exc:
                ctx["ai_problem"] = str(exc)[:200]
    elif opts["ai"]:
        ctx["ai_problem"] = "no model is set up; Settings → ClipForge AI has free choices"
    music = smart_edit.choose_music(project, assets, values, (ctx.get("ai") or {}).get("music", ""))
    added: list[dict] = []
    lib: dict[str, dict] = {}
    try:
        if music.get("how") == "library":
            if lease:
                lease.progress(0.78, "Making the background music")
            a = library.asset(project["workspace_id"], music["key"])
            music["asset_id"] = a["id"]
            added.append(a)
        if opts["sound_effects"] and not off:
            for key in ("whoosh", "swish"):
                lib[key] = library.asset(project["workspace_id"], key)
                added.append(lib[key])
    except (OSError, ValueError, RuntimeError) as exc:  # the edit goes on without them, and says so
        ctx["library_problem"] = str(exc)[:200]
        music = {"how": ""} if music.get("how") == "library" and not music.get("asset_id") else music
    for a in added:
        assets[a["id"]] = a
    fresh = [a["id"] for a in added if a["id"] not in project["asset_ids"]]
    if fresh:
        current = db.fetch("studio_projects", project["id"])
        db.update("studio_projects", project["id"], asset_ids=list(dict.fromkeys(current["asset_ids"] + fresh)),
                  updated_at=time.time())
    ctx.update(music=music if music.get("how") in ("bin", "library") else {}, library=lib)
    return ctx


SMART_KEEP = ("output", "layout", "captions", "title", "word_fixes", "ducking", "tracks", "clean_sound")


def smart_again(project_id: str, base_revision: int, choices: dict) -> dict:
    """Run the smart edit again on this project with these choices, as a background job that saves a new version
    (Undo returns to the current one). Your look, captions, word fixes and the sounds and pictures you placed
    yourself are kept."""
    project = db.fetch("studio_projects", project_id)
    if not project or not project["plan_revision"]:
        raise VideoError("The rough cut is not ready yet.")
    if base_revision != project["plan_revision"]:
        raise Conflict(f"This video was changed elsewhere (now version {project['plan_revision']}). Reload it first.")
    unknown = set(choices) - set(SMART_OPTIONS) - {"target_duration_s"}
    if unknown:
        raise VideoError("Unknown choices: " + ", ".join(sorted(unknown)))
    for key, value in choices.items():
        if key == "target_duration_s":
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or
                                      not 0 <= value <= 4 * 3600):
                raise VideoError("The length must be between 0 and 4 hours.")
        elif value not in SMART_OPTIONS[key]:
            raise VideoError(f"“{key}” must be one of: {', '.join(map(str, SMART_OPTIONS[key]))}.")
    if choices.get("music") == "supplied" and not (project.get("brief") or {}).get("music_asset_id"):
        raise VideoError("Add your music file to this video first, or choose another music option.")
    brief = {**(project.get("brief") or {}), **choices}
    db.update("studio_projects", project_id, brief=brief, updated_at=time.time())
    job = enqueue(project["workspace_id"], "video_smart", project_id, base_revision)
    return {"job": job["id"]}


def set_script(project_id: str, base_revision: int, script) -> dict:
    """Give the project a script (or take it away with None) and cut the video again to follow it, as a
    background job that saves a new version (Undo returns to the current one)."""
    project = db.fetch("studio_projects", project_id)
    if not project or not project["plan_revision"]:
        raise VideoError("The rough cut is not ready yet.")
    if base_revision != project["plan_revision"]:
        raise Conflict(f"This video was changed elsewhere (now version {project['plan_revision']}). Reload it first.")
    payload = script_payload(script)
    db.update("studio_projects", project_id, script=payload, updated_at=time.time())
    job = enqueue(project["workspace_id"], "video_smart", project_id, base_revision)
    return {"job": job["id"], "script": bool(payload)}


@handler("video_smart")
def smart_job(job: dict, lease: Lease) -> dict:
    project = db.fetch("studio_projects", job["target_id"])
    if not project:
        raise VideoError("The project was deleted.")
    base = job["revision"]
    if project["plan_revision"] != base:
        raise VideoError("The video changed before this edit started; nothing was changed. Press Edit it for me "
                         "again.")
    settings = db.get_settings()
    current = plan_at(project["id"], base)
    assets = _assets(project, current)
    words = listen(assets, project["asset_ids"], settings, lease, 0.05, 0.55)
    lease.progress(0.6, "Editing")
    ctx = prepare_smart(project, assets, words, settings, lease)
    project = db.fetch("studio_projects", project["id"])
    new = rough_cut(project, assets, words, ctx)
    for key in SMART_KEEP:  # the look and the fixes you made stay as they are
        if key in current:
            new[key] = copy.deepcopy(current[key])
    look = (project.get("setup") or {}).get("look") or {}
    if look:  # ...apart from the shape and captions you changed in the plan ("Edit it again with this plan")
        if look.get("aspect") in engine.ASPECTS and isinstance(new.get("output"), dict):
            new["output"]["aspect"] = look["aspect"]
        if isinstance(look.get("captions"), bool) and isinstance(new.get("captions"), dict):
            new["captions"]["enabled"] = look["captions"]
    clip_ids = {c["id"] for c in new["clips"]}
    mine = [i for i in current.get("audio") or [] if not i.get("auto") and
            (not i.get("anchor") or i["anchor"].get("clip_id") in clip_ids)]
    lost = [i["label"] for i in current.get("audio") or [] if not i.get("auto") and i not in mine]
    auto = [i for i in new.get("audio") or [] if i.get("auto") or i["role"] != "voiceover"]
    if any(i["role"] == "music" for i in mine):
        auto = [i for i in auto if i["role"] != "music"]
    auto = [i for i in auto if not any(m["asset_id"] == i["asset_id"] and m["role"] == i["role"] for m in mine)]
    new["audio"] = []
    for n, item in enumerate(mine + auto, 1):
        new["audio"].append({**item, "id": f"a{n}"})
    keep_ov = [o for o in current.get("overlays") or [] if not o.get("auto") and o.get("clip_id") in clip_ids]
    lost += [o.get("label", "") for o in current.get("overlays") or [] if not o.get("auto") and o not in keep_ov]
    new["overlays"] = [{**o, "id": f"o{n}"} for n, o in enumerate(keep_ov + (new.get("overlays") or []), 1)]
    if lost:
        new["notes"].append("These were attached to parts that are no longer in the video and were left out: " +
                            ", ".join(x for x in lost if x)[:300] + ". Add them again from Your media.")
    problems = engine.validate(new, _assets(db.fetch("studio_projects", project["id"]), new))
    if problems:
        raise VideoError("; ".join(problems))
    level = (new.get("smart") or {}).get("level", "off")
    note = {"smart": "Edited for you", "tight": "Edited for you (fast-paced)"}.get(level, "Rebuilt the rough cut")
    if new.get("script"):
        note = "Followed your script"
    try:
        rev = save_revision(project["id"], new, note, base)
    except Conflict as exc:
        raise VideoError("The video changed while it was being edited; nothing was overwritten. Press Edit it for "
                         "me again.") from exc
    if look:
        from . import video_setup

        video_setup.look_used(project["id"])
    enqueue(project["workspace_id"], "video_preview", project["id"], rev)
    return {"revision": rev}


# ------------------------------------------------------------------ the media bin
def add_media(project_id: str, asset_ids: list[str]) -> dict:
    """Add files to the media bin (before or after the rough cut). Nothing in the plan changes until you place
    them; new videos are listened to in the background so trims and captions can use their words."""
    project = db.fetch("studio_projects", project_id)
    if not asset_ids:
        raise VideoError("Choose at least one file.")
    added = []
    for aid in dict.fromkeys(asset_ids):
        _owned(project["workspace_id"], aid)  # only your own files
        if aid not in project["asset_ids"]:
            added.append(aid)
    if added:
        bin_ids = list(project["asset_ids"]) + added
        db.update("studio_projects", project_id, asset_ids=bin_ids, updated_at=time.time())
        enqueue(project["workspace_id"], "video_media", project_id, len(bin_ids))
    return {"added": added}


@handler("video_media")
def prepare_media(job: dict, lease: Lease) -> dict:
    """Transcribe the bin's videos that have no transcript yet (each file content is transcribed once)."""
    project = db.fetch("studio_projects", job["target_id"])
    if not project:
        raise VideoError("The project was deleted.")
    settings = db.get_settings()
    assets = _assets(project)
    videos = [aid for aid, a in assets.items() if a["kind"] == "video"]
    listen(assets, videos, settings, lease, 0.0, 1.0)
    return {"videos": len(videos)}


# ------------------------------------------------------------------ edits
def _find(plan: dict, clip_id: str) -> dict:
    for c in plan["clips"]:
        if c["id"] == clip_id:
            return c
    raise VideoError("That clip is not in this video.")


def _find_audio(plan: dict, audio_id: str) -> dict:
    for i in plan.get("audio") or []:
        if i["id"] == audio_id:
            return i
    raise VideoError("That sound is not in this video.")


def _new_id(prefix: str, taken) -> str:
    taken = set(taken)
    n = len(taken) + 1
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"


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


def _number(value, low: float, high: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise VideoError(f"{what} must be between {low:g} and {high:g}.")
    return float(value)


def _ms(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise VideoError(f"{what} must be a time of 0 or more milliseconds.")
    return int(value)


def _place_clip(a: dict, words: dict[str, list[dict]], edit: dict, clip_id: str) -> dict:
    if a["kind"] == "audio":
        raise VideoError(f"“{a['filename']}” is a sound; add it to an audio track instead.")
    if a["kind"] == "image":
        span = (0, _ms(edit.get("duration_ms", IMAGE_MS), "The duration"))
    elif "in_ms" in edit or "out_ms" in edit:
        span = (_ms(edit.get("in_ms", 0), "The start"), _ms(edit.get("out_ms", engine._length(a)), "The end"))  # noqa: SLF001
    else:
        span = _speech_range(a, words.get(a["id"]) or [])
    if span[1] - span[0] < 500:
        raise VideoError("A clip must be at least half a second long.")
    return {"id": clip_id, "asset_id": a["id"], "kind": a["kind"], "in_ms": span[0], "out_ms": span[1],
            "label": a["filename"], "gain_db": 0.0, "include": True}


def _bin_asset(assets: dict[str, dict], aid) -> dict:
    a = assets.get(aid)
    if not a:
        raise VideoError("Add that file to this project's media first.")
    return a


def _clip_set(p: dict, edit: dict, field: str, value) -> str:
    c = _find(p, edit.get("clip_id"))
    if field == "gain_db":
        c["gain_db"] = _number(value, -12, 12, "A clip's volume")
    elif field == "mute" and type(value) is bool:
        c["mute"] = value
    elif field in ("fade_in_ms", "fade_out_ms"):
        c[field] = _ms(value, "A fade")
    elif field == "layout" and value in (None, *engine.LAYOUTS):
        c["layout"] = value
    elif field == "zoom":
        c["zoom"] = _number(value, *engine.ZOOM_RANGE, "A clip's zoom")
    elif field == "join" and value in (None, "cut"):
        if value is None:
            c.pop("join", None)
        else:
            c["join"] = "cut"
    else:
        raise VideoError(f"“{field}” cannot be set to that.")
    return f"Changed {field.replace('_', ' ')} of {c['label']}"


def _overlay_edit(p: dict, edit: dict, assets: dict[str, dict]) -> str:
    """Pictures over the video: add one to a clip, move or resize it, change its motion, or remove it."""
    op = edit["op"]
    p.setdefault("overlays", [])
    if op == "overlay_add":
        a = _bin_asset(assets, edit.get("asset_id"))
        if a["kind"] not in engine.OVERLAY_KINDS:
            raise VideoError(f"“{a['filename']}” is a sound; add it to an audio track instead.")
        c = _find(p, edit.get("clip_id"))
        length = _ms(edit.get("length_ms", 3500), "The length")
        if length < engine.OVERLAY_MIN_MS:
            raise VideoError("Show a picture for at least half a second.")
        item = {"id": _new_id("o", (o["id"] for o in p["overlays"])), "asset_id": a["id"], "clip_id": c["id"],
                "offset_ms": _ms(edit.get("offset_ms", 0), "The start"), "length_ms": length,
                "motion": edit.get("motion", "zoom" if a["kind"] == "image" else "still"), "label": a["filename"]}
        if item["motion"] not in engine.OVERLAY_MOTIONS:
            raise VideoError("Choose still or a slow zoom.")
        if a["kind"] == "video":
            item["in_ms"] = _ms(edit.get("in_ms", 0), "The start in the file")
        p["overlays"].append(item)
        return f"Showed {a['filename']} over {c['label']}"
    o = next((x for x in p["overlays"] if x["id"] == edit.get("overlay_id")), None)
    if o is None:
        raise VideoError("That picture is not over this video.")
    if op == "overlay_remove":
        p["overlays"].remove(o)
        return f"Removed {o['label']} from over the video (the file stays in your media)"
    if op == "overlay_set":
        field, value = edit.get("field"), edit.get("value")
        if field in ("offset_ms", "length_ms"):
            o[field] = _ms(value, "A time")
            if field == "length_ms" and o[field] < engine.OVERLAY_MIN_MS:
                raise VideoError("Show a picture for at least half a second.")
        elif field == "motion" and value in engine.OVERLAY_MOTIONS:
            o["motion"] = value
        elif field == "fit" and value in (None, *engine.OVERLAY_FITS):
            o["fit"] = value
        elif field == "clip_id":
            o["clip_id"] = _find(p, value)["id"]
        else:
            raise VideoError(f"“{field}” cannot be set to that.")
        o.pop("auto", None)  # you changed it: a later "Edit it for me" keeps it
        return f"Changed {str(field).replace('_', ' ')} of {o['label']}"
    raise VideoError("Unknown edit.")


def _audio_edit(p: dict, edit: dict, assets: dict[str, dict]) -> str:
    op = edit["op"]
    p.setdefault("audio", [])
    if op == "add_audio":
        a = _bin_asset(assets, edit.get("asset_id"))
        if a["kind"] != "audio":
            raise VideoError(f"“{a['filename']}” is not an audio file.")
        role = edit.get("role", "effect")
        if role not in engine.ROLES:
            raise VideoError("Choose the voiceover, music or effects track.")
        over = {k: edit[k] for k in ("gain_db", "duck", "loop", "fade_in_ms", "fade_out_ms") if k in edit}
        item = _audio_item(_new_id("a", (i["id"] for i in p["audio"])), a, role, **over)
        if edit.get("clip_id"):  # attached to a clip: it moves with that clip
            _find(p, edit["clip_id"])
            item["anchor"] = {"clip_id": edit["clip_id"], "offset_ms": int(edit.get("offset_ms") or 0)}
        else:
            item["start_ms"] = _ms(edit.get("start_ms", 0), "The start")
        if not item["loop"] and ("in_ms" in edit or "out_ms" in edit):
            item["in_ms"] = _ms(edit.get("in_ms", 0), "The start")
            item["out_ms"] = _ms(edit.get("out_ms", engine._length(a)), "The end")  # noqa: SLF001
        p["audio"].append(item)
        return f"Added {a['filename']} to the {engine.TRACKS[engine.ROLE_TRACK[role]].lower()} track"
    item = _find_audio(p, edit.get("audio_id"))
    if op == "audio_remove":
        p["audio"].remove(item)
        return f"Removed {item['label']} from its track (the file stays in your media)"
    if op == "audio_move":
        if edit.get("clip_id"):
            _find(p, edit["clip_id"])
            item["anchor"] = {"clip_id": edit["clip_id"], "offset_ms": int(edit.get("offset_ms") or 0)}
        else:
            item["anchor"] = None
            item["start_ms"] = _ms(edit.get("start_ms"), "The start")
        return f"Moved {item['label']}"
    if op == "audio_trim":
        if item.get("loop"):
            length = edit.get("length_ms")
            item["length_ms"] = None if length is None else _ms(length, "The length")
        else:
            a, b = _ms(edit.get("in_ms"), "The start"), _ms(edit.get("out_ms"), "The end")
            if b - a < 100:
                raise VideoError("A sound must stay at least 0.1 s long.")
            item["in_ms"], item["out_ms"] = a, b
        return f"Trimmed {item['label']}"
    if op == "audio_set":
        field, value = edit.get("field"), edit.get("value")
        if field == "gain_db":
            item["gain_db"] = _number(value, *engine.GAIN_RANGE, "A sound's volume")
        elif field in ("mute", "duck") and type(value) is bool:
            if field == "duck" and item["role"] == "voiceover":
                raise VideoError("A voiceover is speech: music and effects duck under it, it never ducks itself.")
            item[field] = value
        elif field in ("fade_in_ms", "fade_out_ms"):
            item[field] = _ms(value, "A fade")
        elif field == "loop" and type(value) is bool:
            if value and not item["loop"]:
                item.update(loop=True, in_ms=0, out_ms=None, length_ms=None)
            elif not value and item["loop"]:
                a = _bin_asset(assets, item["asset_id"])
                item.update(loop=False, in_ms=0, out_ms=engine._length(a), length_ms=None)  # noqa: SLF001
        elif field == "role" and value in engine.ROLES:
            item["role"] = value
            if value == "voiceover":
                item["duck"] = False
        else:
            raise VideoError(f"“{field}” cannot be set to that.")
        return f"Changed {str(field).replace('_', ' ')} of {item['label']}"
    raise VideoError("Unknown edit.")


def apply_edit(plan: dict, edit: dict, words: dict[str, list[dict]],
               assets: dict[str, dict] | None = None) -> tuple[dict, str]:
    """(next plan, what changed). Raises VideoError for anything the plan or the engine does not support."""
    p = copy.deepcopy(engine.upgrade(plan))
    assets = assets or {}
    op = edit.get("op")
    if op == "request":
        return apply_edit(plan, parse_request(edit.get("text", "")), words, assets)
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
        taken = {x["id"] for x in p["clips"]}
        sid = c["id"] + "s"
        while sid in taken:
            sid += "s"
        second = {**copy.deepcopy(c), "id": sid, "in_ms": at}
        c["out_ms"] = at
        p["clips"].insert(p["clips"].index(c) + 1, second)
        return p, f"Split {c['label']}"
    if op == "insert":  # a file from the media bin, placed at a position of the sequence
        a = _bin_asset(assets, edit.get("asset_id"))
        clip = _place_clip(a, words, edit, _new_id("c", (x["id"] for x in p["clips"])))
        at = edit.get("at", len(p["clips"]))
        if isinstance(at, bool) or not isinstance(at, int) or not 0 <= at <= len(p["clips"]):
            raise VideoError("Choose a position in the sequence.")
        p["clips"].insert(at, clip)
        p.setdefault("outline", []).append({"clip_id": clip["id"], "label": a["filename"],
                                            "duration": round((clip["out_ms"] - clip["in_ms"]) / 1000, 1),
                                            "summary": "Added by you" if a["kind"] == "video" else "Your image"})
        return p, f"Inserted {a['filename']} at position {at + 1}"
    if op == "replace":  # another file in the same place and (where it can) for the same length
        c = _find(p, edit["clip_id"])
        a = _bin_asset(assets, edit.get("asset_id"))
        new = _place_clip(a, words, {"duration_ms": max(500, c["out_ms"] - c["in_ms"])} if a["kind"] == "image"
                          else {k: edit[k] for k in ("in_ms", "out_ms") if k in edit} or
                          {"in_ms": 0, "out_ms": min(engine._length(a), c["out_ms"] - c["in_ms"])},  # noqa: SLF001
                          c["id"])
        old = c["label"]
        keep = {k: c[k] for k in ("include", "gain_db", "mute", "fade_in_ms", "fade_out_ms", "layout") if k in c}
        c.clear()
        c.update({**new, **keep})
        return p, f"Replaced {old} with {a['filename']}"
    if op in ("add_audio", "audio_remove", "audio_move", "audio_trim", "audio_set"):
        return p, _audio_edit(p, edit, assets)
    if op in ("overlay_add", "overlay_remove", "overlay_set"):
        return p, _overlay_edit(p, edit, assets)
    if op == "track_set":
        track = edit.get("track")
        if track not in engine.TRACKS:
            raise VideoError("Unknown audio track.")
        tracks = p.setdefault("tracks", engine.default_tracks())
        tracks.setdefault(track, {"gain_db": 0.0, "mute": False})
        field, value = edit.get("field"), edit.get("value")
        if field == "gain_db":
            tracks[track]["gain_db"] = _number(value, *engine.GAIN_RANGE, "A track's volume")
        elif field == "mute" and type(value) is bool:
            tracks[track]["mute"] = value
        else:
            raise VideoError(f"“{field}” cannot be set to that.")
        return p, f"Changed the {engine.TRACKS[track].lower()} track"
    if op == "fix_word":  # correct (or delete, with empty text) one caption word; its timing stays measured
        aid, start = edit.get("asset_id"), edit.get("start_ms")
        text = edit.get("text")
        if not isinstance(text, str) or len(text) > 60 or "\n" in text:
            raise VideoError("Type the corrected word (at most 60 characters).")
        heard = [w for w in words.get(aid) or [] if int(round(w["start"] * 1000)) == start]
        if not heard:
            raise VideoError("That word is not in this file's transcript.")
        p.setdefault("word_fixes", {}).setdefault(aid, {})[str(start)] = text.strip()
        return p, f"Changed the caption “{heard[0]['w'].strip()}” to “{text.strip()}”" if text.strip() else \
            f"Removed “{heard[0]['w'].strip()}” from the captions"
    if op == "use_take":  # another take of a script line plays instead of the one that does now
        return _use_take(p, edit)
    if op == "shorten_intro":
        first = next((c for c in p["clips"] if c.get("include", True) and c.get("kind") == "video"
                      and not c.get("hook")), None)
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
        if edit.get("clip_id"):
            return p, _clip_set(p, edit, field, value)
        if field == "captions" and type(value) is bool:
            p["captions"]["enabled"] = value
        elif field == "caption_position" and value in engine.CAPTION_POSITIONS:
            p["captions"]["position"] = value
        elif field == "caption_size" and value in engine.CAPTION_SIZES:
            p["captions"]["size"] = value
        elif field == "transition" and value in engine.TRANSITIONS:
            p["transition"] = {"type": value, "ms": 0 if value == "cut" else 400}
        elif field == "music_level_db" and isinstance(value, (int, float)) and -36 <= value <= -6 and \
                any(i["role"] == "music" for i in p.get("audio") or []):
            for i in p["audio"]:
                if i["role"] == "music":
                    i["gain_db"] = float(value)
        elif field == "aspect" and value in engine.ASPECTS:
            p["output"]["aspect"] = value
        elif field == "duck_depth_db":
            p["ducking"] = {"depth_db": _number(value, *engine.DUCK_RANGE, "Ducking")}
        elif field == "fps" and value in engine.FPS:
            p["output"]["fps"] = int(value)
        elif field == "layout" and value in engine.LAYOUTS:
            p["layout"] = value
        elif field == "clean_sound" and value in config.CLEAN_SOUND_MODES:
            p["clean_sound"] = value
        elif field == "title" and isinstance(value, str) and len(value) <= 120:
            p["title"].update(text=value.strip() or p["title"]["text"], enabled=bool(value.strip()))
        elif field == "title_card" and type(value) is bool:
            p["title"]["enabled"] = value
        else:
            raise VideoError(f"“{field}” cannot be set to that.")
        return p, f"Changed {str(field).replace('_', ' ')}"
    if op in engine.UNSUPPORTED or op in ("color_grade", "effects"):
        label = engine.UNSUPPORTED.get(op, "effects")
        raise VideoError(f"{label.capitalize()} is not supported by this editor yet.")
    raise VideoError("Unknown edit.")


def _use_take(p: dict, edit: dict) -> tuple[dict, str]:
    """Swap the take of a script line: the chosen (switched-off) take plays where the line plays now, and the take
    that played is kept behind it, switched off, so the swap can be undone or made again. The clip that held the
    line is split around it when it holds other lines too; every piece keeps its lines (`take_of`)."""
    from .smart_edit import FADE_MS

    alt = _find(p, edit.get("clip_id", ""))
    info = alt.get("take_of") or {}
    n = info.get("line")
    if not isinstance(n, int):
        raise VideoError("Choose another take of a script line (one listed under the line).")
    if alt.get("include", True):
        raise VideoError("That take plays already.")
    outline = p.setdefault("outline", [])
    chain = next((c for c in p["clips"] if c.get("include", True) and c is not alt and
                  str(n) in ((c.get("take_of") or {}).get("takes") or {})), None)
    playing_take = {"in_ms": alt["in_ms"], "out_ms": alt["out_ms"], "coverage": info.get("coverage"),
                    "quality": info.get("quality")}
    if chain is None:  # no take of this line plays yet: this one plays where it is
        alt["include"] = True
        alt["take_of"] = {"lines": [n], "takes": {str(n): playing_take}}
        for o in outline:
            if o.get("clip_id") == alt["id"]:
                o["summary"] = f"Line {n}: {o['summary'].split(': ', 1)[-1]}"
        return p, f"Line {n} now plays from {alt['label']}"
    takes, lines = chain["take_of"]["takes"], list(chain["take_of"]["lines"])
    old = takes[str(n)]
    before, after = [m for m in lines if m < n], [m for m in lines if m > n]
    pos = p["clips"].index(chain)
    p["clips"].remove(chain)
    at = p["clips"].index(alt)
    p["clips"].remove(alt)
    if at < pos:
        pos -= 1
    taken = {c["id"] for c in p["clips"]}
    base = {k: v for k, v in chain.items() if k not in ("id", "in_ms", "out_ms", "take_of", "zoom", "join",
                                                          "fade_in_ms", "fade_out_ms", "asset_id", "label")}
    label_of = {o["clip_id"]: o for o in outline if o.get("clip_id") in (chain["id"], alt["id"])}

    def fresh() -> str:
        cid = _new_id("c", taken)
        taken.add(cid)
        return cid

    pieces: list[dict] = []
    if before:
        pieces.append({**base, "id": chain["id"], "asset_id": chain["asset_id"], "label": chain["label"],
                       "in_ms": chain["in_ms"], "out_ms": takes[str(before[-1])]["out_ms"],
                       "take_of": {"lines": before, "takes": {str(m): takes[str(m)] for m in before}},
                       **({"join": "cut", "fade_in_ms": FADE_MS} if chain.get("join") == "cut" else {})})
    playing = {**base, "id": chain["id"] if not before else fresh(), "asset_id": alt["asset_id"],
               "label": alt["label"], "in_ms": alt["in_ms"], "out_ms": alt["out_ms"], "include": True,
               "take_of": {"lines": [n], "takes": {str(n): playing_take}}}
    pieces.append(playing)
    if after:
        pieces.append({**base, "id": fresh(), "asset_id": chain["asset_id"], "label": chain["label"],
                       "in_ms": takes[str(after[0])]["in_ms"], "out_ms": chain["out_ms"],
                       "take_of": {"lines": after, "takes": {str(m): takes[str(m)] for m in after}}})
    retired = {**base, "id": alt["id"] if alt["id"] not in taken else fresh(), "asset_id": chain["asset_id"],
               "label": chain["label"], "in_ms": old["in_ms"], "out_ms": old["out_ms"], "include": False,
               "take_of": {"line": n, "coverage": old.get("coverage"), "quality": old.get("quality")}}
    prev = next((c for c in reversed(p["clips"][:pos]) if c.get("include", True)), None)
    for piece in pieces:  # inside one recording a join is a straight cut with a tiny fade; between two, a transition
        if prev is not None and prev["asset_id"] == piece["asset_id"] and prev.get("kind") == "video":
            piece.update(join="cut", fade_in_ms=FADE_MS)
            prev["fade_out_ms"] = FADE_MS
        else:
            piece.pop("join", None)
            piece.pop("fade_in_ms", None)
        prev = piece
    p["clips"][pos:pos] = pieces + [retired]
    following = next((c for c in p["clips"][pos + len(pieces) + 1:] if c.get("include", True)), None)
    if following is not None and following.get("kind") == "video":
        if following["asset_id"] == pieces[-1]["asset_id"]:
            following.update(join="cut", fade_in_ms=FADE_MS)
            pieces[-1]["fade_out_ms"] = FADE_MS
        else:
            following.pop("join", None)
            following.pop("fade_in_ms", None)
    rows = [o for o in outline if o.get("clip_id") not in (chain["id"], alt["id"])]
    where = next((i for i, o in enumerate(outline) if o.get("clip_id") == chain["id"]), len(rows))
    chain_words = (label_of.get(chain["id"]) or {}).get("summary", "")
    alt_words = (label_of.get(alt["id"]) or {}).get("summary", "")
    fresh_rows = []
    for piece in pieces:
        ls = piece["take_of"]["lines"]
        which = f"Line {ls[0]}" if len(ls) == 1 else f"Lines {ls[0]} to {ls[-1]}"
        said = alt_words.split("): ", 1)[-1] if piece is playing else chain_words.split(": ", 1)[-1]
        fresh_rows.append({"clip_id": piece["id"], "label": piece["label"],
                           "duration": round((piece["out_ms"] - piece["in_ms"]) / 1000, 1),
                           "summary": f"{which}: {said[:140]}"})
    fresh_rows.append({"clip_id": retired["id"], "label": retired["label"],
                       "duration": round((old["out_ms"] - old["in_ms"]) / 1000, 1),
                       "summary": f"Another take of line {n} (the one that played before): "
                                  f"{chain_words.split(': ', 1)[-1][:120]}"})
    rows[where:where] = fresh_rows
    p["outline"] = rows
    if p.get("script"):
        for row in p["script"].get("lines") or []:
            if row.get("n") == n:
                row["clip_id"] = playing["id"]
                row["takes"] = [{**t, "clip_id": retired["id"]} if t.get("clip_id") == alt["id"] else t
                                for t in row.get("takes") or []]
                for t in row["takes"]:
                    if t.get("clip_id") == retired["id"]:
                        t.update(coverage=old.get("coverage"), quality=old.get("quality"))
            elif row.get("clip_id") == chain["id"] and row.get("n") in after:
                row["clip_id"] = pieces[-1]["id"]
    for ch in p.get("chapters") or []:
        if ch.get("clip_id") == chain["id"]:
            for piece in pieces:
                t = (piece["take_of"]["takes"] or {})
                inside = [v for v in t.values() if v["in_ms"] - piece["in_ms"] <= int(ch.get("offset_ms") or 0)]
                if piece is pieces[0] or inside:
                    ch["clip_id"] = piece["id"]
                    ch["offset_ms"] = max(0, min(int(ch.get("offset_ms") or 0), piece["out_ms"] - piece["in_ms"] - 1))
    return p, f"Line {n} now plays from {alt['label']} (the take that played is kept behind it, switched off)"


def _words(assets: dict[str, dict]) -> dict[str, list[dict]]:
    return {aid: transcript_words(a, db.get_settings(), cached_only=True) for aid, a in assets.items()
            if a["kind"] == "video"}


def edit(project_id: str, base_revision: int, change: dict) -> dict:
    project = db.fetch("studio_projects", project_id)
    if not project or not project["plan_revision"]:
        raise VideoError("The rough cut is not ready yet.")
    plan = plan_at(project_id, project["plan_revision"])
    assets = _assets(project, plan)
    new, note = apply_edit(plan, change, _words(assets), assets)
    problems = engine.validate(new, assets)
    if problems:
        raise VideoError("; ".join(problems))
    rev = save_revision(project_id, new, note, base_revision)
    enqueue(project["workspace_id"], "video_preview", project_id, rev)
    return {"revision": rev, "note": note}


def _jump(project_id: str, base_revision: int, target: int, note: str, meta: dict) -> dict:
    project = db.fetch("studio_projects", project_id)
    plan = plan_at(project_id, target)
    problems = engine.validate(plan, _assets(project, plan))
    if problems:
        raise VideoError("; ".join(problems))
    rev = save_revision(project_id, plan, note, base_revision, {**meta, "same_as": target})
    enqueue(project["workspace_id"], "video_preview", project_id, rev)
    return {"revision": rev, "note": note}


def undo(project_id: str, base_revision: int) -> dict:
    """Go back one step, as a new revision (redo stays possible until the next edit)."""
    project = db.fetch("studio_projects", project_id)
    if not project or not project["plan_revision"]:
        raise VideoError("The rough cut is not ready yet.")
    cur = _revision_row(project_id, project["plan_revision"])
    prev = _meta(cur).get("prev")
    if not prev:
        raise VideoError("There is nothing to undo.")
    target = _revision_row(project_id, prev)
    return _jump(project_id, base_revision, prev, f"Undid: {cur['note']}"[:300],
                 {"action": "undo", "prev": _meta(target).get("prev"), "redo": cur["revision"]})


def redo(project_id: str, base_revision: int) -> dict:
    project = db.fetch("studio_projects", project_id)
    if not project or not project["plan_revision"]:
        raise VideoError("The rough cut is not ready yet.")
    cur = _revision_row(project_id, project["plan_revision"])
    nxt = _meta(cur).get("redo")
    if not nxt:
        raise VideoError("There is nothing to redo.")
    target = _revision_row(project_id, nxt)
    tm = _meta(target)
    return _jump(project_id, base_revision, nxt, f"Redid: {target['note']}"[:300],
                 {"action": "redo", "prev": tm.get("prev"), "redo": tm.get("redo")})


def restore(project_id: str, revision: int, base_revision: int | None = None) -> dict:
    """Reopen an earlier version exactly, as a new revision (nothing in between is lost; undo returns here)."""
    project = db.fetch("studio_projects", project_id)
    row = _revision_row(project_id, revision)
    name = f" “{row['name']}”" if row.get("name") else ""
    return _jump(project_id, project["plan_revision"] if base_revision is None else base_revision, revision,
                 f"Back to version {revision}{name}", {"action": "restore", "prev": project["plan_revision"],
                                                       "redo": None})


def name_revision(project_id: str, revision: int, name: str) -> None:
    """Name a version (the plan itself never changes; an empty name removes the name)."""
    _revision_row(project_id, revision)
    clean = " ".join(str(name or "").split())[:60]
    db.execute("UPDATE edit_plans SET name = ? WHERE project_id = ? AND revision = ?", (clean, project_id, revision))


def save_filmcraft(project_id: str, opened_on: int, digest: str, base_revision: int) -> dict:
    """A project saved in FilmCraft's editor becomes the next version: the plan of the version it was opened on,
    naming the saved project (its preview and final video are rendered by FilmCraft from that file).
    `base_revision` is the video's version when the editor was opened (a newer one means a conflict)."""
    project = db.fetch("studio_projects", project_id)
    if not project or not project["plan_revision"]:
        raise VideoError("The rough cut is not ready yet.")
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or not (filmcraft_saves(project_id) / f"{digest}.fcproj").is_file():
        raise VideoError("The saved FilmCraft project is missing.")
    plan = copy.deepcopy(plan_at(project_id, opened_on))
    if (plan.get("filmcraft") or {}).get("project") == digest and opened_on == project["plan_revision"]:
        return {"revision": opened_on, "note": "Nothing changed in FilmCraft", "unchanged": True}
    plan["filmcraft"] = {"project": digest, "saved_at": round(time.time(), 3), "opened_on": opened_on}
    note = "Finished by hand in FilmCraft's editor"
    rev = save_revision(project_id, plan, note, base_revision,
                        {"action": "filmcraft", "prev": base_revision, "redo": None})
    enqueue(project["workspace_id"], "video_preview", project_id, rev)
    return {"revision": rev, "note": note}


@handler("filmcraft_edit")
def filmcraft_edit_job(job: dict, lease: Lease) -> dict:
    """The AI's FilmCraft edit of one version, made for FilmCraft's editor on the editor page (the final render
    uses the same edit when the plan has not changed since)."""
    from ..craft import finish

    project = db.fetch("studio_projects", job["target_id"])
    if not project:
        raise VideoError("The project was deleted.")
    plan = plan_at(project["id"], job["revision"])
    if plan.get("filmcraft"):
        return {"ready": True, "hand": True}
    assets = _assets(project, plan)
    settings = db.get_settings()
    used = {c["asset_id"] for c in plan["clips"] if c.get("include", True)}
    words = listen(assets, [aid for aid, a in assets.items() if a["kind"] == "video" and aid in used], settings)
    folder = video_dir(project["id"]) / f"r{job['revision']}" / "filmcraft"
    name = project.get("name") or "Video"
    key = finish.edit_key(plan, settings)
    if finish.reuse_edit(folder, key, plan, assets, words, name=name, revision=job["revision"]):
        return {"ready": True}
    state = {"t": time.monotonic(), "f": 0.0, "m": "Editing in FilmCraft"}

    def report(frac: float, message: str) -> None:
        state.update(f=frac, m=message or state["m"], t=time.monotonic())
        lease.progress(frac, state["m"])

    def stop() -> bool:
        if time.monotonic() - state["t"] > 15:
            state["t"] = time.monotonic()
            lease.progress(state["f"], state["m"])
        return lease.canceled()

    edit = finish.build_edit(plan, assets, words, folder, name=name, revision=job["revision"], settings=settings,
                             progress=report, cancelled=stop)
    return {"ready": True, "steps": len(edit.steps), "failed": len(edit.failed()), "shots": len(edit.shots)}


# ------------------------------------------------------------------ renders
def plan_hash(plan: dict) -> str:
    """What decides a render's pixels and sound: the plan without its notes, outline, chapters and edit report."""
    core = {k: v for k, v in engine.upgrade(plan).items() if k not in ("notes", "outline", "chapters", "smart")}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def _reuse(project: dict, revision: int, kind: str, digest: str, folder: Path) -> dict | None:
    """A finished artifact of another revision with exactly this plan (after undo, redo or going back)."""
    for art in db.select("studio_artifacts", "project_id = ? AND kind = ?", (project["id"], kind), "revision DESC"):
        info = art.get("info") or {}
        if info.get("plan_sha256") != digest or not Path(art["path"]).is_file():
            continue
        out = folder / f"{kind}.mp4"
        folder.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        try:
            os.link(art["path"], out)
        except OSError:
            import shutil

            shutil.copyfile(art["path"], out)
        if artifact.sha256_file(out) != art["sha256"]:
            out.unlink(missing_ok=True)
            continue
        timeline_file = Path(art["path"]).with_name(f"{kind}.timeline.json")
        if timeline_file.is_file():
            (folder / f"{kind}.timeline.json").write_text(timeline_file.read_text())
        return {"path": out, "sha256": art["sha256"], "info": {**info, "reused_from": art["revision"]}}
    return None


def _craft_render(project: dict, job: dict, plan: dict, assets: dict, words: dict, out: Path, settings: dict,
                  lease: Lease, preview: bool) -> tuple[dict | None, str]:
    """The final video edited and rendered in FilmCraft (craft/finish.py: ClipForge's look and sound with
    FilmCraft's tools, EffectCraft's animated title and, with an AI service set up, the AI's own finishing) when
    FilmCraft is set up and chosen (setting `edit_engine`). Returns (None, why) when the built-in engine renders it
    instead: FilmCraft is not set up or not chosen, or (with "auto") FilmCraft's render failed; `why` is kept with
    the video. With "filmcraft" a failure fails the render. Previews stay with the built-in engine (quick), except
    a version finished by hand in FilmCraft's editor: only FilmCraft can render that, so both come from FilmCraft
    and a failure is reported instead of rendering something else."""
    from ..craft import apps, finish

    hand = plan.get("filmcraft") or {}
    choice = settings.get("edit_engine", "auto")
    if not hand and (preview or choice == "ffmpeg"):
        return None, ""
    if not apps.find_cli("filmcraft"):
        if hand:
            raise VideoError("This version was finished in FilmCraft's editor, and FilmCraft is not set up here to "
                             "render it. Set it up in Settings, Editing apps, or go back to the version before.")
        if choice == "filmcraft":
            raise VideoError("FilmCraft is chosen for final videos but is not set up yet: set it up in Settings, "
                             "Editing apps, or choose the built-in editor there.")
        return None, ""
    state = {"f": 0.0, "m": "Editing in FilmCraft", "t": time.monotonic()}

    def report(frac: float, message: str) -> None:
        state.update(f=frac * 0.95, m=message or state["m"], t=time.monotonic())
        lease.progress(state["f"], state["m"])

    def stop() -> bool:  # asked once a second while FilmCraft or EffectCraft runs; keeps the lease alive meanwhile
        if time.monotonic() - state["t"] > 15:
            state["t"] = time.monotonic()
            lease.progress(state["f"], state["m"])
        return lease.canceled()

    if hand:
        saved = filmcraft_saves(project["id"]) / f"{hand.get('project', '')}.fcproj"
        if not re.fullmatch(r"[0-9a-f]{64}", str(hand.get("project", ""))) or not saved.is_file():
            raise VideoError("The FilmCraft edit of this version is missing; go back to the version before.")
        return finish.render_saved(saved, plan, words, out, preview=preview, cancelled=stop, progress=report), ""
    try:
        return finish.render(plan, assets, words, out, name=project.get("name") or "Video", revision=job["revision"],
                             settings=settings, cancelled=stop, progress=report,
                             context={"workspace_id": project["workspace_id"], "project_id": project["id"]}), ""
    except Exception as exc:
        if choice == "filmcraft" or lease.canceled():
            raise
        why = f"FilmCraft could not make this version ({str(exc)[:240]}); the built-in editor rendered it."
        lease.progress(0.0, "FilmCraft could not render it; rendering with the built-in editor")
        return None, why


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
    assets = _assets(project, plan)
    settings = db.get_settings()
    used = {c["asset_id"] for c in plan["clips"] if c.get("include", True)}
    words = listen(assets, [aid for aid, a in assets.items() if a["kind"] == "video" and aid in used], settings)
    folder = video_dir(project["id"]) / f"r{job['revision']}"
    out = folder / f"{kind}.mp4"
    digest = plan_hash(plan)
    if not preview:
        db.update("studio_projects", project["id"], status="rendering", message="Rendering the final video")
    reused = _reuse(project, job["revision"], kind, digest, folder)
    if reused:
        sha, info = reused["sha256"], reused["info"]
    else:
        try:
            info, fallback = _craft_render(project, job, plan, assets, words, out, settings, lease, preview)
            if info is None:
                info = engine.render(plan, assets, words, out, preview=preview, settings=settings,
                                     progress=lambda f: lease.progress(f * 0.95, "Rendering preview" if preview else
                                                                       "Rendering"),
                                     cancelled=lease.canceled, cache_dir=video_dir(project["id"]) / f"pieces-{kind}")
            if fallback:
                info["filmcraft_fallback"] = fallback
        except BaseException as exc:
            if not preview:  # the plan and any earlier finished version stay as they were
                canceled = lease.canceled()
                db.update("studio_projects", project["id"], status="ready",
                          message="Render canceled; nothing changed" if canceled else
                          f"Render failed: {str(exc)[:200]}")
            out.unlink(missing_ok=True)
            raise
        if abs(info["duration"] - info["expected_duration"]) > 0.2:
            raise VideoError(f"The render is {info['duration']:.2f} s instead of {info['expected_duration']:.2f} s.")
        info["plan_sha256"] = digest
        sha = artifact.sha256_file(out)
        (folder / f"{kind}.timeline.json").write_text(json.dumps({"timeline": info["timeline"],
                                                                   "words": info["words"]}))
    from . import media_sources

    info = {**info, "credits": media_sources.credits_text(project, plan)}  # media from providers, as edited
    if info["credits"] and not preview:
        (folder / "credits.txt").write_text(info["credits"] + "\n", encoding="utf-8")
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


def _made_with(info: dict) -> dict:
    """Which editor made a rendered version, and what FilmCraft, EffectCraft and the AI did in it (for the page)."""
    fc = info.get("filmcraft") or {}
    out = {"engine": info.get("engine") or "ffmpeg"}
    if info.get("filmcraft_fallback"):
        out["fallback"] = info["filmcraft_fallback"]
    if fc:
        ai = fc.get("ai") or {}
        out["filmcraft"] = {"hand_edited": bool(fc.get("hand_edited")), "steps": fc.get("steps", 0),
                            "failed": len(fc.get("failed") or []),
                            "shots": [{"what": s.get("what", ""), "app": s.get("app", ""), "use": s.get("use", "")}
                                      for s in fc.get("shots") or []],
                            "ai": {"used": bool(ai.get("used")), "summary": ai.get("summary", ""),
                                   "provider": ai.get("provider", ""), "steps": ai.get("steps", 0),
                                   "refused": len(ai.get("refused") or [])} if ai else None,
                            "notes": (fc.get("notes") or [])[:5]}
    return out


def view(project: dict) -> dict:
    rev = project["plan_revision"]
    plan = plan_at(project["id"], rev) if rev else None
    arts = db.select("studio_artifacts", "project_id = ?", (project["id"],), "revision DESC")
    jobs = db.select("studio_jobs", "target_id = ?", (project["id"],), "created_at DESC", 10)
    rows = db.select("edit_plans", "project_id = ?", (project["id"],), "revision DESC")
    revisions = [{"revision": r["revision"], "note": r["note"], "name": r.get("name") or "",
                  "action": _meta(r).get("action", "edit"), "created_at": r["created_at"]} for r in rows]
    current = next((r for r in rows if r["revision"] == rev), None)
    meta = _meta(current) if current else {}
    assets = _assets(project, plan)
    previews = [a for a in arts if a["kind"] == "preview"]
    shown = next((a for a in previews if a["revision"] == rev), previews[0] if previews else None)
    digest = plan_hash(plan) if plan else ""
    stale = bool(shown and shown["revision"] != rev and (shown.get("info") or {}).get("plan_sha256") != digest)
    return {**{k: project[k] for k in ("id", "name", "status", "message", "asset_ids", "brief", "plan_revision",
                                       "rendered_revision", "created_at", "updated_at")},
            "guidance": project.get("guidance") or {}, "plan": plan,
            "duration": engine.duration_ms(plan) / 1000 if plan else 0,
            "timeline": engine.timeline(plan) if plan else [],
            "audio_timeline": engine.audio_timeline(plan) if plan else [],
            "assets": [uploads.asset_view(a) for a in assets.values()],
            "bin": [aid for aid in project["asset_ids"] if aid in assets],
            "artifacts": [{"id": a["id"], "revision": a["revision"], "kind": a["kind"], "sha256": a["sha256"],
                           "duration": (a.get("info") or {}).get("duration"),
                           "audio_ok": ((a.get("info") or {}).get("audio_timing") or {}).get("valid"),
                           **_made_with(a.get("info") or {})}
                          for a in arts],
            "preview": {"revision": shown["revision"], "stale": stale} if shown else None,
            "jobs": [{k: j[k] for k in ("id", "kind", "revision", "status", "progress", "message", "error")}
                     for j in jobs],
            "revisions": revisions, "can_undo": bool(meta.get("prev")), "can_redo": bool(meta.get("redo")),
            "script": script_view(project.get("script") or {}), "setup": _setup_view(project),
            "capabilities": engine.capabilities(), **_media_view(project, plan, assets), **_smart_view(plan)}


def _setup_view(project: dict) -> dict | None:
    """The plan made with ClipForge AI before the build (video_setup.py), or None for a video made without one."""
    from . import video_setup

    return video_setup.summary(project)


def script_view(script: dict) -> dict | None:
    """The project's script for the Script panel: its lines with their text (the matching lives in the plan's
    `script`, by line number), or None when the project has none."""
    if not script or not script.get("lines"):
        return None
    return {"filename": script.get("filename") or "", "format": script.get("format") or "", "counts": script.get("counts") or {},
            "lines": [{k: ln.get(k, "") for k in ("n", "text", "kind", "speaker", "section")} for ln in script["lines"]]}


def _smart_view(plan: dict | None) -> dict:
    from ..pipeline import llm
    from . import ai_editor, smart_edit

    settings = db.get_settings()
    provider = ai_editor.configured(settings)
    return {"overlay_timeline": engine.overlay_timeline(plan) if plan else [],
            "chapters": smart_edit.chapter_times(plan) if plan else [],
            "smart": (plan or {}).get("smart"),
            "ai_helper": {"configured": bool(provider), "label": llm.provider_label(settings) if provider else "",
                          "local": ai_editor.is_local(settings, provider) if provider else False}}


def _media_view(project: dict, plan: dict | None, assets: dict[str, dict]) -> dict:
    from . import media_sources

    sources = media_sources.provenance(list(assets), project["workspace_id"])
    return {"sources": {aid: [media_sources.source_view(r) for r in rows] for aid, rows in sources.items()},
            "credits": media_sources.credits(project, plan), "media_rules": media_sources.rules_for(project)}

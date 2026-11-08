"""Make → Animated short: a voice-over short of moving pictures, from a pasted script or one ClipForge AI writes
(docs/clipforge/ANIMATED_SHORTS.md).

A short is a studio project (`workflow = "animated_short"`) whose options live in its `short` column and whose
scenes are rows of `short_scenes`. The `short_build` job writes the script when asked, stops for the owner to check
it when asked, then makes every scene that needs it: the voice (voice.py), the picture (pictures.py, the owner's own
picture, or an earlier one) and the moving clip (motion.py). Each scene clip is stored as an ordinary private video
asset whose transcript is the script's own words with their times, so the editor, its captions, previews, renders
and FilmCraft treat it like any other footage. A scene keeps keys of what its voice, picture and clip were made from;
a build makes again only what changed, and a scene that fails never stops the others.

The plan (`assemble`) has one clip per ready scene (clip id = scene id), centred captions with the spoken word
highlighted, a music bed under the voice and a whoosh on every other cut. A later build keeps what the owner changed
in the editor: the order, trims and splits of unchanged scenes, removed and replaced clips, inserted files, captions,
levels, tracks, pictures over the video and the word fixes of unchanged scenes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Callable

from .. import config, db
from ..pipeline.common import Cancelled, write_json
from ..studio import engine, guidance, library, uploads, video_flow
from ..studio.jobs import Canceled, Lease, enqueue, handler
from . import local_engines, looks

log = logging.getLogger(__name__)

WORKFLOW = "animated_short"
MODES = ("paste", "write")
MOTIONS = ("camera", "animate")
CAPTIONS = {"bold": "Bold", "high_energy": "High energy", "clean": "Clean", "off": "No captions"}
MUSIC = {"calm": "Calm", "balanced": "Balanced", "energetic": "Energetic", "none": "No music"}
SPEEDS = ((0.95, "Calm"), (1.05, "Lively"), (1.15, "Fast"))
SPEED_RANGE = (0.7, 1.4)
OPTION_FIELDS = ("mode", "tone", "length", "audience", "look", "voice", "speed", "music", "captions", "motion",
                 "review")
DEFAULTS = {"mode": "paste", "tone": "curious", "length": "standard", "audience": "", "look": looks.DEFAULT,
            "voice": "auto", "speed": 1.05, "music": "balanced", "captions": "", "motion": "camera", "review": False}
FPS = 30
SIZE = (1080, 1920)
TAIL_MS = 250          # the pause after a scene's words before the cut
END_MS = 700           # every scene clip runs on this long after its words; the last one in the video plays it all
MUSIC_DB = -20.0
WHOOSH_DB = -14.0
WHOOSH_LEAD_MS = 540   # the library whoosh swells for about this long, so it lands on the cut
MAX_EARLIER = 8        # earlier pictures kept per scene
MAX_NARRATION = 400    # characters of one scene's words
MAX_PICTURE = 400
MAX_SCRIPT = 20_000
MAX_TOPIC = 300
MAX_VOICES = 120       # recorded scene voices kept per short (going back to earlier words reuses them)
VIDEO_MAX_S = 5.0      # what the video engine is asked for at most per scene
CLIP_RECIPE = 1        # part of every clip key: a changed recipe makes the clips again
STATUS_TTL = 5.0       # seconds an engine's status is reused (the editor page asks every few seconds)
WORKING = ("voice", "picture", "motion")
SAMPLE_TEXT = "Here is how this voice sounds in your short. Did you know octopuses have three hearts?"
_status_cache: dict[str, tuple[float, dict]] = {}


class ShortError(video_flow.VideoError):
    """Something the owner can fix; the message says what."""


class _Stale(Exception):
    """The scene changed while it was being made; the next build makes it from the new words."""


# ------------------------------------------------------------------ small helpers
def _norm(text: object) -> str:
    return " ".join(str(text or "").split())


def _hash(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def _seed() -> int:
    return int.from_bytes(os.urandom(4), "big") % 2_000_000_000 + 1


def _first_words(text: str, n: int = 6) -> str:
    words = _norm(text).split()
    out = " ".join(words[:n]).rstrip(",;:—-")
    return out + ("…" if len(words) > n else "")


def engine_status(role: str) -> dict:
    """local_engines.status, reused for a few seconds."""
    now = time.monotonic()
    hit = _status_cache.get(role)
    if hit and now - hit[0] < STATUS_TTL:
        return hit[1]
    got = local_engines.status(role)
    _status_cache[role] = (now, got)
    return got


def short_dir(project_id: str) -> Path:
    d = video_flow.video_dir(project_id) / "short"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_short(project: dict | None) -> bool:
    return bool(project) and project.get("workflow") == WORKFLOW


def _project(project_id: str) -> dict:
    p = db.fetch("studio_projects", project_id)
    if not is_short(p):
        raise ShortError("The short was deleted.")
    return p  # type: ignore[return-value]


def scene_rows(project_id: str) -> list[dict]:
    return db.select("short_scenes", "project_id = ?", (project_id,), "position, created_at")


def _patch_short(project_id: str, changes: dict | None = None, *, bump: bool = False, apply: tuple = ()) -> dict:
    """Change some of the short's options in one step (the build job and the page both write them); returns them.
    `bump` asks for a new build; `apply` names plan parts ("music", "captions") that build sets again from the
    options, over what the owner changed in the editor."""
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT short FROM studio_projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise ShortError("The short was deleted.")
        data = json.loads(row["short"] or "{}")
        for key, value in (changes or {}).items():
            data[key] = value
        if bump:
            data["build"] = int(data.get("build") or 0) + 1
        for part in apply:
            data.setdefault("apply", {})[part] = int(data.get("build") or 0)
        conn.execute("UPDATE studio_projects SET short = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(data, ensure_ascii=False), time.time(), project_id))
    return data


def _change_scene(scene_id: str, change: Callable[[dict], dict | None]) -> dict | None:
    """Change one scene in one step (the build job and the page both write scenes): `change(row)` answers the fields
    to write, or nothing to leave it as it is. Returns the scene as it is now (None when it was deleted)."""
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        raw = conn.execute("SELECT * FROM short_scenes WHERE id = ?", (scene_id,)).fetchone()
        if raw is None:
            return None
        row = db._decode("short_scenes", raw)  # noqa: SLF001 - the same decoding as db.fetch, inside this step
        fields = change(row)  # type: ignore[arg-type]
        if not fields:
            return row
        fields = {**fields, "updated_at": time.time()}
        enc = db._encode("short_scenes", fields)  # noqa: SLF001
        conn.execute(f"UPDATE short_scenes SET {', '.join(f'{k} = ?' for k in enc)} WHERE id = ?",
                     [*enc.values(), scene_id])
    return {**row, **fields}  # type: ignore[dict-item]


def _info(scene: dict) -> dict:
    return scene.get("info") or {}


def _tone_ids() -> list[str]:
    from . import writer

    return list(writer.TONES)


def _tone_label(tone: str) -> str:
    from . import writer

    labels = getattr(writer, "TONE_LABELS", None) or {}
    if tone in labels:
        return str(labels[tone])
    value = writer.TONES.get(tone)
    if isinstance(value, dict) and value.get("label"):
        return str(value["label"])
    return tone.replace("_", " ").capitalize()


# ------------------------------------------------------------------ options
def clean_options(raw: dict, base: dict | None = None) -> dict:
    """The short's options from what the page sent, on top of `base` (the defaults for a new short). Raises
    ShortError for a choice that does not exist."""
    from . import scenes

    out = dict(base if base is not None else DEFAULTS)
    for key in OPTION_FIELDS:
        if key not in raw or raw[key] is None:
            continue
        value = raw[key]
        if key == "mode" and value not in MODES:
            raise ShortError("Choose Paste my script or Write it for me.")
        if key == "tone" and value not in _tone_ids():
            raise ShortError("Choose one of the tones on the page.")
        if key == "length" and value not in scenes.LENGTHS:
            raise ShortError("Choose one of the lengths on the page.")
        if key == "look" and value not in looks.BY_ID:
            raise ShortError("Choose one of the looks on the page.")
        if key == "music" and value not in MUSIC:
            raise ShortError("Choose calm, balanced or energetic music, or no music.")
        if key == "captions" and value not in ("", *CAPTIONS):
            raise ShortError("Choose a caption style, or no captions.")
        if key == "motion" and value not in MOTIONS:
            raise ShortError("Choose gentle camera moves or animated pictures.")
        if key == "review" and type(value) is not bool:
            raise ShortError("Checking the script first is either on or off.")
        if key == "speed":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or \
                    not SPEED_RANGE[0] <= float(value) <= SPEED_RANGE[1]:
                raise ShortError(f"The voice speed must be between {SPEED_RANGE[0]:g} and {SPEED_RANGE[1]:g}.")
            value = round(float(value), 2)
        if key == "voice":
            value = _norm(value)[:200] or "auto"
            if value != "auto" and not re.fullmatch(r"(engine|system|espeak):.{1,190}", value):
                raise ShortError("Choose one of the voices on the page.")
        if key in ("audience", "tone", "length", "look", "music", "captions", "mode", "motion") and \
                not isinstance(value, str):
            raise ShortError("Choose one of the options on the page.")
        if key == "audience":
            value = _norm(value)[:200]
        out[key] = value
    return out


def can_listen(settings: dict) -> bool:
    """Whether word times can come from listening to the voice: the speech model is installed and downloaded."""
    from ..pipeline import transcribe

    try:
        return transcribe.whisper_installed() and transcribe.model_cached(transcribe.whisper_plan(settings)["model"])
    except Exception:  # noqa: BLE001 - then the times are estimated from the sound
        return False


def _engines() -> dict:
    return {"available": local_engines.available(), **{role: engine_status(role) for role in local_engines.ROLES}}


def _writer_state(settings: dict) -> dict:
    from . import writer

    try:
        state = writer.ready(settings) or {}
    except Exception:  # noqa: BLE001 - a broken AI setting must not hide the page
        log.exception("checking ClipForge AI failed")
        state = {}
    return {"configured": bool(state.get("configured")), "label": str(state.get("label") or ""),
            "local": bool(state.get("local"))}


def options() -> dict:
    """Everything the Make page offers (GET /api/studio/shorts/options)."""
    from . import scenes, voice

    settings = db.get_settings()
    try:
        voices = voice.voices()
        default = voice.default_voice()
    except Exception:  # noqa: BLE001 - the page still opens; making a short explains a voice problem
        log.exception("listing voices failed")
        voices, default = [{"id": "auto", "name": "The best voice on this computer", "lang": "", "gender": "",
                            "about": "", "engine": ""}], "auto"
    return {"looks": looks.view(), "voices": voices, "default_voice": default,
            "tones": [{"id": t, "label": _tone_label(t)} for t in _tone_ids()],
            "lengths": [{"id": k, "label": f"{lo}–{hi} s", "min": lo, "max": hi, "target": target}
                        for k, (lo, hi, target) in scenes.LENGTHS.items()],
            "captions": [{"id": "", "label": "Fits the look"}, *({"id": k, "label": v} for k, v in CAPTIONS.items())],
            "music": [{"id": k, "label": v} for k, v in MUSIC.items()],
            "speeds": [{"value": v, "label": label} for v, label in SPEEDS],
            "engines": _engines(), "writer": _writer_state(settings),
            "timing": "listened" if can_listen(settings) else "estimated",
            "limits": {"max_words": scenes.MAX_WORDS, "max_scenes": scenes.MAX_SCENES, "wpm": scenes.WPM},
            "links": {"makers": "#/settings/makers", "ai": "#/settings/ai"}}


# ------------------------------------------------------------------ making a short
def create(workspace_id: str, user_id: str, *, name: str, options: dict) -> dict:
    """A new short (`user_id` keeps the call shape of video_flow.create). A pasted script is split into scenes at
    once, so a script the owner must fix is refused before anything is saved; a topic is written into scenes by the
    build job."""
    from . import scenes

    opts = clean_options(options)
    settings = db.get_settings()
    rows: list[dict] = []
    script = options.get("script") if isinstance(options.get("script"), str) else ""
    topic = _norm(options.get("topic") if isinstance(options.get("topic"), str) else "")
    if opts["mode"] == "paste":
        if len(script) > MAX_SCRIPT:
            raise ShortError(f"The script is longer than a short can be; keep it under about {scenes.MAX_WORDS} "
                             "words.")
        try:
            rows = scenes.split(script)
        except scenes.SceneError as exc:
            raise ShortError(str(exc)) from exc
        topic = ""
    else:
        if not topic:
            raise ShortError("Say what the short is about.")
        if len(topic) > MAX_TOPIC:
            raise ShortError(f"Keep the topic to a sentence or two ({MAX_TOPIC} characters).")
        if not _writer_state(settings)["configured"]:
            raise ShortError("Writing a script needs ClipForge AI. Set it up in Settings → ClipForge AI, or paste "
                             "your own script.")
        script = ""
    named = _norm(name)[:120]
    title = named or (_first_words(rows[0]["narration"]) if rows else _first_words(topic, 8)) or "My short"
    writing = opts["mode"] == "write"
    message = "ClipForge AI is writing the script" if writing else "Making the scenes"
    short = {**opts, "topic": topic, "script": script, "build": 1, "stage": "writing" if writing else "making",
             "message": message, "seed": _seed(), "title": named, "character": "", "subject": "",
             "named": bool(named), "writer": None, "notes": [], "reviewed": False, "pictured": writing, "apply": {},
             "next_seq": len(rows), "voice_used": ""}
    project_id = "vid-" + os.urandom(6).hex()
    db.insert("studio_projects", {
        "id": project_id, "workspace_id": workspace_id, "name": title, "workflow": WORKFLOW, "status": "building",
        "message": message, "asset_ids": [], "brief": {}, "style_id": "", "guidance": _guidance(short),
        "script": {}, "short": short,
        "media": {"mode": "suggest", "commercial": bool(settings.get("autopilot_commercial_use", True))}})
    _insert_scenes(project_id, workspace_id, rows, short["seed"], 0)
    enqueue(workspace_id, "short_build", project_id, 1)
    del user_id
    return db.fetch("studio_projects", project_id)  # type: ignore[return-value]


def _guidance(short: dict) -> dict:
    """What decided this short, for the editor's guidance list: the owner's own choices on the Make page."""
    look = looks.get(short.get("look"))
    here = {"level": "project", "id": "", "revision": 0, "name": "This short's choices"}
    voice_id = short.get("voice") or "auto"
    style = short.get("captions") or look.caption_style
    rows = [("look", look.id, f"Look: {look.name}"),
            ("voice", voice_id, "Voice: " + ("the best voice on this computer" if voice_id == "auto"
                                             else voice_id.split(":", 1)[-1])),
            ("music", short.get("music"), f"Music: {MUSIC.get(short.get('music') or '', 'none').lower()}"),
            ("captions", style, f"Captions: {CAPTIONS.get(style, 'bold').lower()}")]
    return {"schema": guidance.SCHEMA, "mode": WORKFLOW, "created_at": time.time(),
            "values": {k: v for k, v, _ in rows}, "conflicts": [], "problems": [], "used": [], "entries": [here],
            "decisions": [{"field": k, "value": v, "text": text, "from": here, "also": [], "overridden": []}
                          for k, v, text in rows]}


_UNSET = object()


def _insert_scenes(project_id: str, workspace_id: str, rows: list[dict], base_seed: int, first_seq: int,
                   start: float = 1.0, after=_UNSET) -> list[str]:
    """Save scenes in order from position `start`. `after` (a scene id, or None for the very start) places scenes
    added later in the short's order until the plan has them; a new short's scenes leave it out."""
    ids: list[str] = []
    for k, r in enumerate(rows):
        sid = "sc-" + os.urandom(6).hex()
        seq = first_seq + k
        info: dict = {"seq": seq}
        if after is not _UNSET:
            info["after"] = after if k == 0 else ids[-1]
        picture = _norm(r.get("picture"))[:MAX_PICTURE]
        db.insert("short_scenes", {
            "id": sid, "project_id": project_id, "workspace_id": workspace_id, "position": start + k,
            "narration": _norm(r.get("narration"))[:MAX_NARRATION], "picture_prompt": picture,
            "picture_from": r.get("picture_from") or ("script" if picture else ""),
            "seed": (int(base_seed) + 7919 * seq) % 2_000_000_000 + 1, "status": "waiting", "message": "Waiting",
            "pictures": [], "info": info})
        ids.append(sid)
    return ids


def _rebuild(project: dict, changes: dict | None = None, apply: tuple = (),
             waiting: str = "Waiting to make the changes") -> int:
    """Ask for a new build after a change: the job makes what changed and saves the next version of the plan. Until
    it starts, the short says it is waiting to make the change (not "Ready"), unless it waits for the owner to check
    the script or ClipForge AI is still writing it."""
    now = {**(project.get("short") or {}), **(changes or {})}
    if not (now.get("review") and not now.get("reviewed")) and now.get("stage") != "writing":
        changes = {**(changes or {}), "stage": "making", "message": waiting}
    short = _patch_short(project["id"], changes, bump=True, apply=apply)
    build = int(short["build"])
    db.update("studio_projects", project["id"], status="building", message=waiting)
    enqueue(project["workspace_id"], "short_build", project["id"], build)
    return build


def stopped(project_id: str) -> None:
    """After the owner pressed Stop: the scenes being made wait, and the short says how to go on."""
    project = db.fetch("studio_projects", project_id)
    if not is_short(project):
        return
    for s in scene_rows(project_id):
        if s["status"] in WORKING:
            db.update("short_scenes", s["id"], status="waiting", message="Stopped")
    message = "Stopped. Press Make the short to go on."
    _patch_short(project_id, {"stage": "stopped", "message": message})
    db.update("studio_projects", project_id, status="ready" if project["plan_revision"] else "draft",  # type: ignore[index]
              message=message)


# ------------------------------------------------------------------ the order of the scenes
def ordered(rows: list[dict], plan: dict | None) -> list[dict]:
    """The scenes in the short's order: the plan's order for scenes in it (the owner may have moved them in the
    editor), a scene added later right after the scene it was added after, the rest by position."""
    by_id = {s["id"]: s for s in rows}
    seen = dict.fromkeys(c.get("scene_id") for c in (plan or {}).get("clips") or [])
    out = [by_id[i] for i in seen if i in by_id]
    placed = {s["id"] for s in out}
    for s in sorted((s for s in rows if s["id"] not in placed), key=lambda s: (s["position"], s["created_at"])):
        info = _info(s)
        ids = [x["id"] for x in out]
        if "after" in info and info["after"] is None:
            out.insert(0, s)
        elif info.get("after") in ids:
            out.insert(ids.index(info["after"]) + 1, s)
        else:
            k = len(out)
            while k > 0 and out[k - 1]["position"] > s["position"]:
                k -= 1
            out.insert(k, s)
    return out


# ------------------------------------------------------------------ what a scene needs
def voice_for(project_id: str, short: dict) -> str:
    """The voice a build speaks with: the chosen one, or for "auto" the best voice when the short was first made
    (kept, so changing one scene never changes the voice of the others)."""
    chosen = short.get("voice") or "auto"
    if chosen != "auto":
        return chosen
    if short.get("voice_used"):
        return str(short["voice_used"])
    from . import voice

    try:
        found = voice.default_voice()
    except Exception:  # noqa: BLE001 - speak() explains a missing voice
        log.exception("finding the default voice failed")
        found = "auto"
    if found and found != "auto":
        _patch_short(project_id, {"voice_used": found})
        short["voice_used"] = found
    return found or "auto"


def voice_key(scene: dict, short: dict, voice_id: str) -> str:
    return _hash("voice", _norm(scene["narration"]), voice_id, round(float(short.get("speed") or 1.0), 2))


def picture_keys(scene: dict, short: dict) -> tuple[str, str]:
    """(the key of a picture the picture engine makes, the key of a designed card) for this scene as it is now."""
    from . import cards

    base = ("picture", _norm(scene["picture_prompt"]), looks.get(short.get("look")).id, int(scene["seed"]),
            _norm(short.get("character")))
    return _hash(*base, "engine"), _hash(*base, "card", cards.key_words(scene["narration"]), _info(scene).get("seq", 0))


def _fine_pictures(scene: dict, short: dict) -> tuple[str, ...]:
    """The picture keys that need no new picture: with a picture engine ready a card is replaced by a real picture
    (unless the engine already failed on this picture), without one a card or an earlier engine picture stays."""
    engine_key, card_key = picture_keys(scene, short)
    failed = (_info(scene).get("picture") or {}).get("failed") == engine_key
    return (engine_key,) if engine_status("image")["ready"] and not failed else (engine_key, card_key)


def _move(scene: dict) -> str:
    from . import motion

    move = scene.get("move") or "auto"
    return motion.pick_move(int(_info(scene).get("seq") or 0)) if move == "auto" else move


def _motion_mode(short: dict) -> str:
    return "animate" if short.get("motion") == "animate" and engine_status("video")["ready"] else "camera"


def clip_key(scene: dict, short: dict, vkey: str) -> str:
    return _hash("clip", CLIP_RECIPE, vkey, scene["picture_asset_id"], _move(scene), _motion_mode(short), FPS,
                 list(SIZE), END_MS)


def _voice_files(project_id: str, vkey: str) -> tuple[Path, Path]:
    folder = short_dir(project_id) / "voice"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{vkey}.wav", folder / f"{vkey}.json"


def _asset_ok(asset_id: str, workspace_id: str, kind: str) -> dict | None:
    a = db.fetch("assets", asset_id) if asset_id else None
    if a and a["workspace_id"] == workspace_id and a["kind"] == kind and Path(a["path"]).is_file():
        return a
    return None


def needs(scene: dict, short: dict, project: dict, voice_id: str) -> list[str]:
    """What this scene still needs made: any of "voice", "picture", "clip" (in that order)."""
    vkey = voice_key(scene, short, voice_id)
    wav, meta = _voice_files(project["id"], vkey)
    ws = project["workspace_id"]
    out = []
    if not (wav.is_file() and meta.is_file()):
        out.append("voice")
    if scene["picture_source"] != "upload" and (scene["picture_key"] not in _fine_pictures(scene, short) or
                                                not _asset_ok(scene["picture_asset_id"], ws, "image")):
        out.append("picture")
    if out or scene["clip_key"] != clip_key(scene, short, vkey) or not _asset_ok(scene["clip_asset_id"], ws, "video"):
        out.append("clip")
    return out


# ------------------------------------------------------------------ the build job
def _job_canceled(job_id: str) -> bool:
    return (db.fetch("studio_jobs", job_id) or {}).get("status") == "canceled"


@handler("short_build")
def build_job(job: dict, lease: Lease) -> dict:
    from . import voice

    project_id = job["target_id"]
    project = _project(project_id)
    if int(project["short"].get("build") or 0) > int(job["revision"]):
        return {"skipped": "A newer change is being made."}
    settings = db.get_settings()
    state = {"listened": False}
    try:
        short = project["short"]
        if short.get("mode") == "write" and not scene_rows(project_id):
            _write_script(project, settings, lease)
            project = _project(project_id)
            short = project["short"]
        if short.get("review") and not short.get("reviewed"):
            message = "Check the script, then press Make the short."
            _patch_short(project_id, {"stage": "review", "message": message})
            db.update("studio_projects", project_id, status="needs_input", message=message)
            return {"review": True}
        if not short.get("pictured"):
            _plan_pictures(project, settings, lease)
            project = _project(project_id)
        made = _make_scenes(project, settings, lease, state)
        rev = save_plan(project_id)
    except (Canceled, Cancelled):
        if _job_canceled(job["id"]):
            stopped(project_id)
        raise
    except Exception as exc:
        if lease.canceled():
            if _job_canceled(job["id"]):
                stopped(project_id)
            raise Canceled() from exc
        message = str(exc) if isinstance(exc, video_flow.VideoError) and str(exc) else \
            f"The short could not be made ({exc.__class__.__name__}). Press Make the short to try again."
        if db.fetch("studio_projects", project_id):
            _patch_short(project_id, {"stage": "failed", "message": message})
            db.update("studio_projects", project_id, status="failed", message=message[:200])
        raise
    finally:
        if state["listened"]:
            try:
                voice.release()
            except Exception:  # noqa: BLE001 - freeing memory never fails a build
                log.exception("releasing the speech model failed")
    project = _project(project_id)
    _tidy_voices(project_id, project["short"])
    if int(project["short"].get("build") or 0) > int(job["revision"]):
        return {"revision": rev, "made": made, "newer": True}  # the next build is waiting; it says when it is done
    failed = [s for s in scene_rows(project_id) if s["status"] == "failed"]
    message = (f"{len(failed)} scene{'s' if len(failed) != 1 else ''} could not be made; see the scenes" if failed
               else "The short is ready; making a preview")
    _patch_short(project_id, {"stage": "ready", "message": message})
    db.update("studio_projects", project_id, status="ready", message=message)
    return {"revision": rev, "made": made, "failed": len(failed)}


def _write_script(project: dict, settings: dict, lease: Lease) -> None:
    from ..brain import knowhow
    from . import scenes, writer

    pid, short = project["id"], project["short"]
    message = "ClipForge AI is writing the script"
    _patch_short(pid, {"stage": "writing", "message": message})
    db.update("studio_projects", pid, status="building", message=message)
    lease.progress(0.02, message)
    try:
        got = writer.write(short.get("topic") or "", tone=short.get("tone") or "curious",
                           length=short.get("length") or "standard", audience=short.get("audience") or "",
                           look=looks.get(short.get("look")), settings=settings,
                           workspace_id=project["workspace_id"], project_id=pid, cancel=lease.canceled,
                           beat=lambda m="", *_: lease.progress(0.05, str(m or message)))
    except writer.WriterError as exc:
        if lease.canceled():
            raise Canceled() from exc
        raise ShortError(str(exc)) from exc
    rows = [{"narration": _norm(s.get("narration")), "picture": _norm(s.get("picture"))}
            for s in got.get("scenes") or [] if isinstance(s, dict) and _norm(s.get("narration"))][:scenes.MAX_SCENES]
    if not rows:
        raise ShortError("ClipForge AI wrote no usable scenes. Try another topic, or paste your own script.")
    subject = scenes.subject_of([r["narration"] for r in rows], title=_norm(got.get("title")))
    for r in rows:  # a scene the model gave no picture (a long scene it split) follows its own words
        r["picture_from"] = "ai" if r["picture"] else "words"
        r["picture"] = r["picture"] or scenes.picture_words(r["narration"], subject)
    if scene_rows(pid):
        return  # written meanwhile (a build that was cut off and run again)
    _insert_scenes(pid, project["workspace_id"], rows, int(short["seed"]), 0)
    used = {"model": str(got.get("model") or ""), "local": bool(got.get("local")),
            "memories": len(got.get("memories") or []),
            "knowhow": [knowhow.BY_ID[k].title for k in got.get("knowhow") or [] if k in knowhow.BY_ID]}
    title = _norm(got.get("title"))[:120]
    _patch_short(pid, {"title": title, "character": _norm(got.get("character"))[:300], "writer": used,
                       "notes": [str(n) for n in got.get("notes") or []][:6], "next_seq": len(rows), "pictured": True,
                       "subject": scenes.subject_of([r["narration"] for r in rows], title=title)})
    if not short.get("named") and title:
        db.update("studio_projects", pid, name=title)


def _plan_pictures(project: dict, settings: dict, lease: Lease) -> None:
    """Picture ideas for a pasted script's scenes that have none from the script: from ClipForge AI when it is set
    up, else from each scene's own words."""
    from . import scenes, writer

    pid, short = project["id"], project["short"]
    rows = ordered(scene_rows(pid), None)
    subject = scenes.subject_of([s["narration"] for s in rows], title=project["name"] if short.get("named") else "")
    character = short.get("character") or ""
    lacking = {s["id"] for s in rows if s["picture_from"] not in ("script", "owner", "ai") or not s["picture_prompt"]}
    notes = list(short.get("notes") or [])
    writer_used = short.get("writer")
    if lacking and _writer_state(settings)["configured"]:
        message = "ClipForge AI is picturing the scenes"
        lease.progress(0.04, message)
        try:
            got = writer.picture_ideas([s["narration"] for s in rows], title=project["name"],
                                       look=looks.get(short.get("look")), settings=settings,
                                       workspace_id=project["workspace_id"], project_id=pid, cancel=lease.canceled,
                                       beat=lambda m="", *_: lease.progress(0.05, str(m or message)))
            character = _norm(got.get("character"))[:300] or character
            for s, idea in zip(rows, got.get("pictures") or []):
                if s["id"] in lacking and _norm(idea):
                    db.update("short_scenes", s["id"], picture_prompt=_norm(idea)[:MAX_PICTURE], picture_from="ai")
                    lacking.discard(s["id"])
            from ..brain import knowhow

            writer_used = {"model": str(got.get("model") or ""), "local": bool(got.get("local")),
                           "memories": len(got.get("memories") or []),
                           "knowhow": [knowhow.BY_ID[k].title for k in got.get("knowhow") or []
                                       if k in knowhow.BY_ID]}
        except writer.WriterError as exc:
            if lease.canceled():
                raise Canceled() from exc
            notes.append(f"ClipForge AI could not describe the pictures ({str(exc)[:120]}), so each picture follows "
                         "its scene's own words.")
    for s in rows:
        if s["id"] in lacking:
            db.update("short_scenes", s["id"], picture_prompt=scenes.picture_words(s["narration"], subject)[:MAX_PICTURE],
                      picture_from="words")
    _patch_short(pid, {"pictured": True, "character": character, "subject": subject, "notes": notes[-6:],
                       "writer": writer_used})


def _make_scenes(project: dict, settings: dict, lease: Lease, state: dict) -> int:
    pid = project["id"]
    short = project["short"]
    voice_id = voice_for(pid, short)
    base = video_flow.plan_at(pid, project["plan_revision"]) if project["plan_revision"] else None
    rows = ordered(scene_rows(pid), base)
    todo = [s for s in rows if needs(s, short, project, voice_id)]
    for s in rows:
        if s not in todo and s["status"] != "ready":
            db.update("short_scenes", s["id"], status="ready", message="", error="")
    message = f"Making {len(todo)} scene{'s' if len(todo) != 1 else ''}" if todo else "Putting the short together"
    _patch_short(pid, {"stage": "making", "message": message})
    db.update("studio_projects", pid, status="building", message=message)
    made = 0
    for k, s in enumerate(todo):
        fresh = db.fetch("short_scenes", s["id"])
        if not fresh:
            continue  # deleted meanwhile
        n = rows.index(s) + 1
        lo, hi = 0.08 + 0.84 * k / len(todo), 0.08 + 0.84 * (k + 1) / len(todo)
        lease.progress(lo, f"Making scene {n} of {len(rows)}")
        try:
            _make_scene(project, fresh, short, voice_id, n, settings, lease, (lo, hi), state)
            made += 1
        except _Stale:
            db.update("short_scenes", s["id"], status="waiting", message="Waiting", error="")
        except (Canceled, Cancelled):
            db.update("short_scenes", s["id"], status="waiting", message="Stopped")
            raise
        except Exception as exc:  # noqa: BLE001 - one scene never stops the others
            if lease.canceled():
                db.update("short_scenes", s["id"], status="waiting", message="Stopped")
                raise Canceled() from exc
            known = isinstance(exc, (video_flow.VideoError, uploads.UploadError, OSError)) or \
                exc.__class__.__name__ in ("VoiceError", "MotionError", "FFmpegError", "CardError")
            if not known:
                log.exception("scene %s failed", s["id"])
            why = str(exc) if known and str(exc) else f"Something went wrong ({exc.__class__.__name__})."
            db.update("short_scenes", s["id"], status="failed", message="", error=why[:300])
    return made


def _same(row: dict, scene: dict, picture_id: str | None = None) -> bool:
    """Whether a scene still says and shows what it did when this build started making it."""
    keys = ("narration", "picture_prompt", "picture_source", "seed", "move")
    return all(row[k] == scene[k] for k in keys) and (picture_id is None or row["picture_asset_id"] == picture_id)


def _make_scene(project: dict, scene: dict, short: dict, voice_id: str, n: int, settings: dict, lease: Lease,
                span: tuple[float, float], state: dict) -> None:
    from . import motion, pictures, voice

    pid, ws, sid = project["id"], project["workspace_id"], scene["id"]
    lo, hi = span

    def step(frac: float, message: str) -> None:
        lease.progress(lo + (hi - lo) * min(max(float(frac), 0.0), 1.0), message)

    look = looks.get(short.get("look"))
    seq = int(_info(scene).get("seq") or 0)
    # ---- the voice
    vkey = voice_key(scene, short, voice_id)
    wav, meta_path = _voice_files(pid, vkey)
    if not (wav.is_file() and meta_path.is_file()):
        db.update("short_scenes", sid, status="voice", message="Recording the voice", error="")
        step(0.02, f"Recording the voice of scene {n}")
        tmp = wav.with_name(f"{vkey}.part.wav")
        try:
            got = voice.speak(scene["narration"], tmp, voice=voice_id, speed=float(short.get("speed") or 1.0),
                              cancel=lease.canceled)
            step(0.1, f"Timing the words of scene {n}")
            words, how = voice.time_words(tmp, scene["narration"], engine_words=got.get("words"), settings=settings,
                                          listen=True)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        state["listened"] = state["listened"] or how == "listened"
        write_json(meta_path, {"duration_s": float(got["duration_s"]), "words": words, "timing": how,
                               "engine": got.get("engine", ""), "voice": got.get("voice", ""),
                               "fallback": got.get("fallback", ""), "rule": str(got.get("rule") or "")})
        tmp.replace(wav)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    step(0.15, f"Scene {n}: the voice is ready")
    # ---- the picture
    if scene["picture_source"] == "upload":
        picture = _asset_ok(scene["picture_asset_id"], ws, "image")
        if picture is None:
            raise ShortError("The picture you chose for this scene is missing. Choose it again, or press New picture.")
    else:
        picture = _asset_ok(scene["picture_asset_id"], ws, "image") \
            if scene["picture_key"] in _fine_pictures(scene, short) else None
        if picture is None:
            db.update("short_scenes", sid, status="picture", message="Making the picture")
            step(0.2, f"Making the picture of scene {n}")
            with tempfile.TemporaryDirectory(dir=short_dir(pid)) as tmpdir:
                got = pictures.make(scene["narration"], scene["picture_prompt"], look, Path(tmpdir),
                                    character=short.get("character") or "", seed=int(scene["seed"]), index=seq,
                                    cancel=lease.canceled,
                                    progress=lambda f=0.0, m="", *_: step(0.2 + 0.45 * float(f or 0),
                                                                          str(m or f"Making the picture of scene {n}")))
                made_path = Path(got["path"])
                stored = uploads.store_file(ws, made_path, f"Scene {n} picture{made_path.suffix}")
            engine_key, card_key = picture_keys(scene, short)
            made_key = engine_key if got["source"] == "engine" else card_key
            pic_info = {"source": got["source"], "engine": got.get("engine") or "", "why": got.get("why") or "",
                        "failed": engine_key if got["source"] != "engine" and got.get("tried") else ""}
            entry = {"asset_id": stored["id"], "prompt": scene["picture_prompt"], "seed": int(scene["seed"]),
                     "key": made_key, "at": time.time(), **{k: pic_info[k] for k in ("source", "engine", "why")}}

            def put_picture(row: dict) -> dict:
                history = [e for e in row.get("pictures") or [] if e.get("asset_id") != stored["id"]] + [entry]
                out: dict = {"pictures": history[-(MAX_EARLIER + 1):]}
                if _same(row, scene):
                    out.update(picture_asset_id=stored["id"], picture_key=made_key,
                               info={**_info(row), "picture": pic_info})
                return out

            row = _change_scene(sid, put_picture)
            if row is None:
                return  # deleted meanwhile
            if row["picture_asset_id"] != stored["id"] or not _same(row, scene):
                raise _Stale()
            scene, picture = row, stored
    # ---- the moving clip with the voice
    ckey = clip_key({**scene, "picture_asset_id": picture["id"]}, short, vkey)
    if scene["clip_key"] == ckey and _asset_ok(scene["clip_asset_id"], ws, "video"):
        _change_scene(sid, lambda r: {"status": "ready", "message": "", "error": ""}
                      if _same(r, scene, picture["id"]) else None)
        return
    db.update("short_scenes", sid, status="motion", message="Moving the picture")
    step(0.7, f"Moving the picture of scene {n}")
    duration_s = float(meta["duration_s"]) + END_MS / 1000
    how, why = "camera", ""
    with tempfile.TemporaryDirectory(dir=short_dir(pid)) as tmpdir:
        out = Path(tmpdir) / f"scene-{n}.mp4"
        result = None
        if _motion_mode(short) == "animate":
            result, why = _animate(scene, short, look, picture, wav, out, duration_s, step, lease, n)
            how = "engine" if result else "camera"
        if result is None:
            result = motion.still_clip(Path(picture["path"]), wav, out, duration_s=duration_s, move=_move(scene),
                                       fps=FPS, size=SIZE, cancel=lease.canceled,
                                       progress=lambda f=0.0, *_: step(0.7 + 0.25 * float(f or 0),
                                                                       f"Moving the picture of scene {n}"))
        clip = uploads.store_file(ws, Path(result["path"]), f"Scene {n}.mp4")
    duration_ms = int(round(float(result["duration_s"]) * 1000))
    _write_transcript(clip, scene["narration"], meta["words"], duration_ms / 1000)
    voice_info = {"engine": meta.get("engine", ""), "voice": meta.get("voice", ""), "timing": meta.get("timing", ""),
                  "fallback": meta.get("fallback", ""), "rule": meta.get("rule", ""),
                  "duration_ms": int(round(float(meta["duration_s"]) * 1000))}

    def put_clip(row: dict) -> dict | None:
        if not _same(row, scene, picture["id"]):
            return None
        return {"clip_asset_id": clip["id"], "clip_key": ckey, "duration_ms": duration_ms, "status": "ready",
                "message": "", "error": "",
                "info": {**_info(row), "voice": voice_info, "motion": {"how": how, "why": why}}}

    row = _change_scene(sid, put_clip)
    if row is not None and row["clip_asset_id"] != clip["id"]:
        raise _Stale()
    step(1.0, f"Scene {n} is ready")


def _animate(scene: dict, short: dict, look, picture: dict, wav: Path, out: Path, duration_s: float,
             step: Callable[[float, str], None], lease: Lease, n: int) -> tuple[dict | None, str]:
    """The video engine's motion for this scene, with the voice: (the clip, "") or (None, why the camera moves
    instead)."""
    from . import motion

    eng = local_engines.module()
    if eng is None:
        return None, "This version of ClipForge does not have the local makers yet, so the camera moves instead."
    prompt, _negative = looks.prompt_for(look, scene["picture_prompt"], short.get("character") or "")
    try:
        video = eng.make_video(prompt, image=Path(picture["path"]), seconds=min(VIDEO_MAX_S, duration_s), width=720,
                               height=1280, seed=int(scene["seed"]),
                               progress=lambda f=0.0, m="", *_: step(0.7 + 0.2 * float(f or 0),
                                                                     str(m or f"Animating scene {n}")),
                               cancel=lease.canceled)
        return motion.video_clip(Path(video), wav, out, duration_s=duration_s, fps=FPS, size=SIZE,
                                 cancel=lease.canceled), ""
    except (Canceled, Cancelled):
        raise
    except local_engines.errors() as exc:
        return None, f"The video maker could not animate this scene ({str(exc)[:140]}); the camera moves instead."
    except Exception as exc:  # noqa: BLE001 - the camera move stands in
        if lease.canceled():
            raise Canceled() from exc
        log.exception("animating scene %s failed", scene["id"])
        return None, f"The video maker stopped with an error ({exc.__class__.__name__}); the camera moves instead."


def _write_transcript(clip: dict, narration: str, words: list[dict], duration_s: float) -> None:
    """The scene clip's transcript is the script's own words with their times: the editor's captions, word fixes
    and exports read it like the transcript of any video (video_flow.transcript_words)."""
    ws = [{"w": str(w["w"]), "start": round(max(0.0, float(w["start"])), 3),
           "end": round(min(duration_s, max(float(w["start"]), float(w["end"]))), 3)}
          for w in words if str(w.get("w") or "").strip()]
    data = {"language": "en", "duration": duration_s, "source": "animated_short",
            "segments": [{"start": ws[0]["start"] if ws else 0.0, "end": ws[-1]["end"] if ws else 0.0,
                          "text": narration, "words": ws}]}
    write_json(uploads.work_dir(clip) / "transcript.json", data)


def _tidy_voices(project_id: str, short: dict) -> None:
    """Keep the newest recorded voices (going back to earlier words reuses them); the oldest unused ones go."""
    folder = short_dir(project_id) / "voice"
    wavs = sorted(folder.glob("*.wav"), key=lambda f: f.stat().st_mtime)
    if len(wavs) <= MAX_VOICES:
        return
    voice_id = short.get("voice_used") or short.get("voice") or "auto"
    keep = {voice_key(s, short, voice_id) for s in scene_rows(project_id)}
    for f in wavs[:len(wavs) - MAX_VOICES]:
        if f.stem not in keep and not f.stem.endswith(".part"):
            f.unlink(missing_ok=True)
            f.with_suffix(".json").unlink(missing_ok=True)


# ------------------------------------------------------------------ the plan
def _label(scene: dict) -> str:
    return _first_words(scene["narration"], 6) or "Scene"


def _captions(short: dict, look, old: dict | None) -> dict:
    style = short.get("captions") or look.caption_style
    out = {"position": "middle", "size": "medium", "highlight": True, **(old or {})}
    out.update(enabled=style != "off", style=style if style in ("bold", "high_energy", "clean") else
               (out.get("style") or look.caption_style))
    return out


def _voice_ms(scene: dict) -> int:
    voiced = int((_info(scene).get("voice") or {}).get("duration_ms") or 0)
    return voiced or max(200, int(scene["duration_ms"]) - END_MS)


def _auto_out(scene: dict, last: bool) -> int:
    whole = int(scene["duration_ms"])
    return whole if last else min(whole, _voice_ms(scene) + TAIL_MS)


def _scene_clip(scene: dict, keep: dict, taken: set[str]) -> dict:
    cid = scene["id"]
    k = 2
    while cid in taken:
        cid, k = f"{scene['id']}-{k}", k + 1
    taken.add(cid)
    out = min(int(scene["duration_ms"]), _voice_ms(scene) + TAIL_MS)
    c = {"id": cid, "asset_id": scene["clip_asset_id"], "kind": "video", "in_ms": 0, "out_ms": out,
         "label": _label(scene), "gain_db": 0.0, "include": True, "scene_id": scene["id"], "auto_ms": [0, out]}
    c.update(keep)
    if int(c.get("fade_in_ms") or 0) + int(c.get("fade_out_ms") or 0) > out:
        c.update(fade_in_ms=0, fade_out_ms=0)
    return c


def _fresh_plan(project: dict, short: dict, look) -> dict:
    return {"schema": engine.SCHEMA, "timebase": 1000, "engine": engine.ENGINE,
            "output": {"aspect": "9:16", "fps": FPS}, "layout": "fill", "clips": [],
            "transition": {"type": "cut", "ms": 0}, "title": {"enabled": False, "text": project["name"], "ms": 2500},
            "captions": _captions(short, look, None), "audio": [], "tracks": engine.default_tracks(),
            "word_fixes": {}, "ducking": {"depth_db": engine.DUCK_DEPTH_DB}, "clean_sound": "off", "outline": [],
            "notes": []}


def _slot(clips: list[dict], order: list[dict], scene: dict) -> int:
    """Where a new scene's clip goes: after the clips of the scene before it, else before the first scene clip."""
    k = order.index(scene)
    for prev in reversed(order[:k]):
        at = [i for i, c in enumerate(clips) if c.get("scene_id") == prev["id"]]
        if at:
            return at[-1] + 1
    at = [i for i, c in enumerate(clips) if c.get("scene_id")]
    return at[0] if at else len(clips)


def assemble(project: dict, rows: list[dict], base: dict | None) -> dict | None:
    """The plan for these scenes on top of the current plan `base`, so the owner's edits stay. None while no scene
    has been made."""
    short = project["short"]
    look = looks.get(short.get("look"))
    by_id = {s["id"]: s for s in rows}
    ready = {s["id"] for s in rows if s["status"] == "ready" and s["clip_asset_id"] and int(s["duration_ms"] or 0) > 0}
    plan = copy.deepcopy(engine.upgrade(base)) if base else _fresh_plan(project, short, look)
    before = (base or {}).get("short") or {}
    placed_before = set(before.get("scenes") or [])
    fixes = dict(plan.get("word_fixes") or {})
    taken = {c["id"] for c in plan.get("clips") or []}
    moved: dict[str, str | None] = {}  # a clip that went → the clip that takes its attachments (None: they go)
    clips: list[dict] = []
    for c in plan.get("clips") or []:
        sid = c.get("scene_id")
        s = by_id.get(sid or "")
        if not sid:
            clips.append(c)  # the owner's own clip: inserted, or a scene clip they replaced in the editor
        elif s is None:
            moved[c["id"]] = None  # its scene was deleted
        elif sid not in ready or c["asset_id"] == s["clip_asset_id"]:
            clips.append(c)  # unchanged, or not made yet (the earlier version stays meanwhile)
        elif any(x.get("scene_id") == sid for x in clips):
            moved[c["id"]] = next(x["id"] for x in clips if x.get("scene_id") == sid)  # another part of it
        else:
            fixes.pop(c["asset_id"], None)  # corrections of the old voice's words
            keep = {k: c[k] for k in ("include", "gain_db", "mute", "fade_in_ms", "fade_out_ms", "layout", "zoom")
                    if k in c}
            taken.discard(c["id"])
            fresh = _scene_clip(s, keep, taken)
            if fresh["id"] != c["id"]:
                moved[c["id"]] = fresh["id"]
            clips.append(fresh)
    order = ordered(rows, {"clips": clips})
    present = {c["scene_id"] for c in clips if c.get("scene_id")}
    for s in order:
        if s["id"] in present or s["id"] not in ready:
            continue
        if s["id"] in placed_before and not _info(s).get("readd"):
            continue  # the owner replaced its clip in the editor; it comes back when the scene is changed
        clips.insert(_slot(clips, order, s), _scene_clip(s, {}, taken))
        present.add(s["id"])
    if not clips:
        return None
    shown = [c for c in clips if c.get("include", True)]
    last = next((c.get("scene_id") for c in reversed(shown) if c.get("scene_id")), None)
    for c in clips:
        s = by_id.get(c.get("scene_id") or "")
        if s is None or c["asset_id"] != s["clip_asset_id"] or not int(s["duration_ms"] or 0):
            continue
        auto = _auto_out(s, c["scene_id"] == last)
        if c.get("auto_ms") == [c["in_ms"], c["out_ms"]]:
            c.update(in_ms=0, out_ms=auto, auto_ms=[0, auto])  # not trimmed by the owner: follows its place
        c["out_ms"] = min(int(c["out_ms"]), int(s["duration_ms"]))
        if c["out_ms"] - int(c["in_ms"]) < 200:
            c.update(in_ms=0, out_ms=auto, auto_ms=[0, auto])
        c["label"] = _label(s)
    ids = {c["id"] for c in clips}
    plan["clips"] = clips
    plan["word_fixes"] = {k: v for k, v in fixes.items() if any(c["asset_id"] == k for c in clips)}
    applied = dict(before.get("applied") or {})
    want = short.get("apply") or {}
    if base is not None and int(want.get("captions") or 0) > int(applied.get("captions") or 0):
        plan["captions"] = _captions(short, look, plan.get("captions"))

    def follow(anchor_id: str) -> str | None:
        while anchor_id in moved and anchor_id not in ids:
            anchor_id = moved[anchor_id]  # type: ignore[assignment]
            if anchor_id is None:
                return None
        return anchor_id if anchor_id in ids else None

    audio = []
    for a in plan.get("audio") or []:
        if a.get("auto") and a.get("role") == "effect":
            continue  # ClipForge's own whooshes are placed again below
        anchor = a.get("anchor")
        if anchor:
            to = follow(anchor.get("clip_id"))
            if to is None:
                continue
            a = {**a, "anchor": {**anchor, "clip_id": to}}
        audio.append(a)
    overlays = []
    for o in plan.get("overlays") or []:
        to = follow(o.get("clip_id"))
        if to is not None:
            overlays.append({**o, "clip_id": to})
    if plan.get("overlays") is not None or overlays:
        plan["overlays"] = overlays
    audio_ids = {a["id"] for a in audio}
    if base is None or int(want.get("music") or 0) > int(applied.get("music") or 0):
        audio = [a for a in audio if not (a.get("auto") and a.get("role") == "music")]
        music = _music_item(project, short, audio_ids)
        if music:
            audio.insert(0, music)
    plan["audio"] = audio + _whooshes(project, clips, audio_ids | {a["id"] for a in audio})
    plan["maker"] = WORKFLOW
    placed = (placed_before & set(by_id)) | present
    # which scenes the plan placed (a placed scene missing from it was replaced by the owner) and which option
    # changes it has taken in; nothing that changes from build to build, so an unchanged short saves no new version
    plan["short"] = {"scenes": sorted(placed),
                     "applied": {k: max(int(want.get(k) or 0), int(applied.get(k) or 0)) for k in ("captions", "music")}}
    old_outline = {o.get("clip_id"): o for o in plan.get("outline") or []}
    outline = []
    for c in clips:
        s = by_id.get(c.get("scene_id") or "")
        if s is not None:
            outline.append({"clip_id": c["id"], "label": c["label"], "summary": _norm(s["narration"])[:140],
                            "duration": round((c["out_ms"] - c["in_ms"]) / 1000, 1)})
        elif c["id"] in old_outline:
            outline.append(old_outline[c["id"]])
    plan["outline"] = outline
    plan["notes"] = _notes(ordered(rows, plan), short, plan)
    return plan


def _new_audio_id(taken: set[str]) -> str:
    n = 1
    while f"a{n}" in taken:
        n += 1
    taken.add(f"a{n}")
    return f"a{n}"


def _music_item(project: dict, short: dict, taken: set[str]) -> dict | None:
    mood = short.get("music") or "balanced"
    if mood == "none":
        return None
    key = library.music_key(mood, project["id"])
    asset = library.asset(project["workspace_id"], key)
    item = video_flow._audio_item(_new_audio_id(taken), asset, "music", gain_db=MUSIC_DB,  # noqa: SLF001
                                  duck=True, fade_in_ms=800, fade_out_ms=1500)
    item.update(auto=True, label=f"{library.MUSIC[key]['title']} (ClipForge)")
    return item


def _whooshes(project: dict, clips: list[dict], taken: set[str]) -> list[dict]:
    """A soft whoosh on every other cut, attached to the clip after the cut so it moves with it."""
    shown = [c for c in clips if c.get("include", True)]
    if len(shown) < 2:
        return []
    asset = library.asset(project["workspace_id"], "whoosh")
    out = []
    for k, c in enumerate(shown):
        if k % 2 == 1:
            item = video_flow._audio_item(_new_audio_id(taken), asset, "effect", gain_db=WHOOSH_DB)  # noqa: SLF001
            item.update(anchor={"clip_id": c["id"], "offset_ms": -WHOOSH_LEAD_MS}, auto=True,
                        label="Whoosh (ClipForge)")
            out.append(item)
    return out


def _notes(rows: list[dict], short: dict, plan: dict | None) -> list[str]:
    """What the owner should know about how the short was made, in plain words."""
    notes = []
    in_plan = {c.get("scene_id") for c in (plan or {}).get("clips") or [] if c.get("scene_id")}
    auto = [s for s in rows if s["picture_source"] != "upload" and s["picture_asset_id"]]
    cards = [s for s in auto if (_info(s).get("picture") or {}).get("source") == "card"]
    failed_engine = [s for s in cards if (_info(s).get("picture") or {}).get("failed")]
    if failed_engine:
        notes.append(f"The picture maker could not make {len(failed_engine)} picture"
                     f"{'s' if len(failed_engine) != 1 else ''}, so {'they are' if len(failed_engine) != 1 else 'it is'}"
                     " a designed card with the scene's key words. Press New picture on a scene to try again.")
    elif cards:
        notes.append(f"{len(cards)} of {len(rows)} pictures are designed cards with each scene's key words, because "
                     "no picture maker is set up. Set one up in Settings → Pictures, video, voice, then press Make the short "
                     "to swap them for real pictures.")
    for n, s in enumerate(rows, 1):
        if s["status"] == "failed":
            notes.append(f"Scene {n} {'still shows its earlier version' if s['id'] in in_plan else 'is not in the video yet'}"
                         f": {s['error'] or 'it could not be made.'}")
    fallback = next(((_info(s).get("voice") or {}) for s in rows if (_info(s).get("voice") or {}).get("fallback")), None)
    if fallback:
        notes.append(str(fallback["fallback"]))
    for rule in dict.fromkeys((_info(s).get("voice") or {}).get("rule") or "" for s in rows):
        if rule:  # what the voice's licence asks of what it makes (Settings → Pictures, video, voice); also at Download
            notes.append(f"About the voice: {rule}")
    animated = [s for s in rows if (_info(s).get("motion") or {}).get("why")]
    if animated:
        notes.append(f"{len(animated)} scene{'s use' if len(animated) != 1 else ' uses'} gentle camera moves because the "
                     "video maker could not animate "
                     f"{'them' if len(animated) != 1 else 'it'}.")
    if any((_info(s).get("voice") or {}).get("timing") == "estimated" for s in rows):
        notes.append("The captions follow the voice by its sound, so a word may show a moment early or late.")
    notes.extend(str(x) for x in (short.get("notes") or [])[:4])
    return notes


def _clear_readd(plan: dict) -> None:
    for sid in {c.get("scene_id") for c in plan.get("clips") or [] if c.get("scene_id")}:
        _change_scene(sid, lambda r: {"info": {k: v for k, v in _info(r).items() if k != "readd"}}
                      if _info(r).get("readd") else None)


def save_plan(project_id: str) -> int | None:
    """Save the scenes as the next version of the plan (unless nothing changed) and queue its preview."""
    for attempt in range(3):
        project = _project(project_id)
        rev = project["plan_revision"]
        base = video_flow.plan_at(project_id, rev) if rev else None
        rows = scene_rows(project_id)
        plan = assemble(project, ordered(rows, base), base)
        if plan is None:
            failed = [s for s in rows if s["status"] == "failed"]
            if failed:
                raise ShortError(f"No scene could be made. {failed[0]['error']}".strip())
            return rev or None
        if base is not None and video_flow.plan_hash(plan) == video_flow.plan_hash(base):
            _clear_readd(plan)
            return rev
        problems = engine.validate(plan, video_flow._assets(project, plan))  # noqa: SLF001
        if problems:
            raise ShortError("The short could not be put together: " + "; ".join(problems[:3]))
        count = len({c["scene_id"] for c in plan["clips"] if c.get("scene_id")})
        note = (f"Animated short: {count} scene{'s' if count != 1 else ''}" if base is None else
                f"Scenes updated ({count} in the short)")
        try:
            new = video_flow.save_revision(project_id, plan, note, rev if base is not None else None,
                                           {"action": "build", "prev": None, "redo": None} if base is None else None)
        except video_flow.Conflict:
            if attempt == 2:
                raise
            continue  # the owner edited it meanwhile: build on their edit
        _clear_readd(plan)
        enqueue(project["workspace_id"], "video_preview", project_id, new)
        return new
    return None


# ------------------------------------------------------------------ changes from the page
def _scene(project: dict, scene_id: str) -> dict:
    s = db.fetch("short_scenes", scene_id)
    if not s or s["project_id"] != project["id"]:
        raise ShortError("That scene does not exist any more.")
    return s


def _narration(text: object) -> str:
    out = _norm(text if isinstance(text, str) else "")
    if not out:
        raise ShortError("A scene needs words to say. Delete the scene instead if it should go.")
    if len(out) > MAX_NARRATION:
        raise ShortError(f"Keep a scene to a sentence or two ({MAX_NARRATION} characters); add another scene for "
                         "the rest.")
    return out


def update_scene(project: dict, scene_id: str, body: dict) -> None:
    """Change a scene's words, picture idea, camera move or picture, or make it again."""
    from . import motion, scenes

    allowed = {"narration", "picture_prompt", "move", "picture_asset_id", "new_picture", "again"}
    unknown = set(body) - allowed
    if unknown:
        raise ShortError("Unknown change: " + ", ".join(sorted(unknown)))
    s = _scene(project, scene_id)
    short = project["short"]
    subject = short.get("subject") or ""
    changes: dict = {}
    picture_info: dict | None = None   # replaces the scene's picture facts (a chosen picture)
    retry = False                      # forget that the picture maker failed on this picture
    chosen: dict | None = None         # the owner's own picture, added to the scene's pictures
    if body.get("narration") is not None:
        text = _narration(body["narration"])
        if text != s["narration"]:
            changes["narration"] = text
            if s["picture_from"] == "words":
                changes["picture_prompt"] = scenes.picture_words(text, subject)[:MAX_PICTURE]
    if body.get("picture_prompt") is not None:
        if not isinstance(body["picture_prompt"], str):
            raise ShortError("Describe the picture in words.")
        idea = _norm(body["picture_prompt"])[:MAX_PICTURE]
        if idea != s["picture_prompt"] or s["picture_source"] == "upload":
            if idea:
                changes.update(picture_prompt=idea, picture_from="owner", picture_source="auto")
            else:
                changes.update(picture_prompt=scenes.picture_words(changes.get("narration") or s["narration"],
                                                                   subject)[:MAX_PICTURE],
                               picture_from="words", picture_source="auto")
    if body.get("move") is not None:
        if body["move"] != "auto" and body["move"] not in motion.MOVES:
            raise ShortError("Choose one of the camera moves.")
        if body["move"] != s["move"]:
            changes["move"] = body["move"]
    if body.get("picture_asset_id"):
        aid = str(body["picture_asset_id"])
        if _asset_ok(aid, project["workspace_id"], "image") is None:
            raise ShortError("Choose a picture file (PNG, JPEG or WebP) for the scene.")
        earlier = next((e for e in s.get("pictures") or [] if e.get("asset_id") == aid), None)
        # the owner chose this exact picture: it stays until they ask for another
        changes.update(picture_asset_id=aid, picture_source="upload")
        picture_info = {"source": (earlier or {}).get("source") or "upload", "engine": (earlier or {}).get("engine")
                        or "", "why": "", "failed": ""}
        if earlier is not None and earlier.get("source") != "upload":
            changes.update(picture_prompt=earlier.get("prompt") or s["picture_prompt"],
                           seed=int(earlier.get("seed") or s["seed"]))
        if earlier is None:
            chosen = {"asset_id": aid, "prompt": "", "seed": 0, "key": "", "source": "upload", "engine": "", "why": "",
                      "at": time.time()}
    if body.get("new_picture"):
        changes.update(seed=_seed(), picture_source="auto")
        retry = True
    if body.get("again"):
        changes["clip_key"] = ""
        retry = True
    if not changes:
        return

    def put(row: dict) -> dict:
        info = {**_info(row), "readd": True}
        if picture_info is not None:
            info["picture"] = picture_info
        if retry:
            info["picture"] = {**(info.get("picture") or {}), "failed": ""}
        out = {**changes, "status": "waiting", "message": "Waiting", "error": "", "info": info}
        if chosen is not None:
            out["pictures"] = (list(row.get("pictures") or []) + [chosen])[-(MAX_EARLIER + 1):]
        return out

    _change_scene(scene_id, put)
    _rebuild(project)


def add_scene(project: dict, after: str | None, narration: object, picture_prompt: object = "") -> str:
    from . import scenes

    rows = scene_rows(project["id"])
    if len(rows) >= scenes.MAX_SCENES:
        raise ShortError(f"A short has at most {scenes.MAX_SCENES} scenes.")
    text = _narration(narration)
    short = project["short"]
    idea = _norm(picture_prompt if isinstance(picture_prompt, str) else "")[:MAX_PICTURE]
    if after:
        start = float(_scene(project, after)["position"]) + 0.001
    else:
        start = min((float(s["position"]) for s in rows), default=1.0) - 1.0
    seq = max(int(short.get("next_seq") or 0), len(rows))
    row = {"narration": text, "picture": idea or scenes.picture_words(text, short.get("subject") or ""),
           "picture_from": "owner" if idea else "words"}
    sid = _insert_scenes(project["id"], project["workspace_id"], [row], int(short.get("seed") or 1), seq, start,
                         after or None)[0]
    _rebuild(project, {"next_seq": seq + 1})
    return sid


def delete_scene(project: dict, scene_id: str) -> None:
    _scene(project, scene_id)
    if len(scene_rows(project["id"])) <= 1:
        raise ShortError("A short needs at least one scene.")
    db.execute("DELETE FROM short_scenes WHERE id = ? AND project_id = ?", (scene_id, project["id"]))
    _rebuild(project)


def make(project: dict) -> None:
    """Go on after the owner checked the script (or after a stop), or make every scene that still needs it."""
    if project["short"].get("mode") == "write" and not scene_rows(project["id"]) and \
            project["status"] == "building":
        raise ShortError("ClipForge AI is still writing the script.")
    _rebuild(project, {"reviewed": True}, waiting="Waiting to start")


def set_options(project: dict, body: dict) -> None:
    """Change the voice, speed, look, music, captions or motion of the whole short; the scenes that change are made
    again (the owner's own pictures stay)."""
    allowed = {"voice", "speed", "look", "music", "captions", "motion"}
    unknown = set(body) - allowed
    if unknown:
        raise ShortError("Unknown option: " + ", ".join(sorted(unknown)))
    short = project["short"]
    new = clean_options({k: v for k, v in body.items() if v is not None}, short)
    changes = {k: new[k] for k in allowed if new.get(k) != short.get(k)}
    if not changes:
        return
    apply = (("music",) if "music" in changes else ()) + \
        (("captions",) if "captions" in changes or ("look" in changes and not new.get("captions")) else ())
    if "voice" in changes:
        changes["voice_used"] = ""
    _rebuild(project, changes, apply)
    db.update("studio_projects", project["id"], guidance=_guidance({**short, **changes}))


def voice_sample(voice_id: str, speed: float) -> Path:
    """A few seconds of a voice, kept by voice and speed (POST /api/studio/shorts/voice-sample)."""
    from . import voice

    opts = clean_options({"voice": voice_id, "speed": speed})
    chosen = opts["voice"]
    if chosen == "auto":
        try:
            chosen = voice.default_voice()
        except Exception:  # noqa: BLE001 - speak() explains it
            chosen = "auto"
    folder = config.data_dir() / "shorts" / "samples"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{_hash('sample', chosen, opts['speed'], SAMPLE_TEXT)}.wav"
    if not out.is_file():
        tmp = out.with_name(out.stem + ".part.wav")
        try:
            voice.speak(SAMPLE_TEXT, tmp, voice=chosen, speed=float(opts["speed"]))
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise ShortError(str(exc) or "That voice could not speak on this computer.") from exc
        tmp.replace(out)
    return out


# ------------------------------------------------------------------ the editor page
def _scene_view(s: dict, n: int, plan: dict | None) -> dict:
    info = _info(s)
    pic = info.get("picture") or {}
    if s["picture_source"] == "upload":
        source = pic.get("source") or "upload"
    else:
        source = pic.get("source") or ""
    earlier = [{"asset_id": e["asset_id"], "prompt": e.get("prompt") or "", "source": e.get("source") or ""}
               for e in reversed(s.get("pictures") or []) if e.get("asset_id") != s["picture_asset_id"]][:MAX_EARLIER]
    v = info.get("voice") or {}
    parts = [c for c in (plan or {}).get("clips") or [] if c.get("scene_id") == s["id"]]
    placed = s["id"] in set(((plan or {}).get("short") or {}).get("scenes") or [])
    return {"id": s["id"], "n": n, "narration": s["narration"], "picture_prompt": s["picture_prompt"],
            "picture_from": s["picture_from"], "picture_source": s["picture_source"],
            "picture_asset_id": s["picture_asset_id"], "clip_asset_id": s["clip_asset_id"], "move": s["move"] or "auto",
            "status": s["status"], "message": s["message"] or "", "error": s["error"] or "",
            "duration": round(int(s["duration_ms"] or 0) / 1000, 2),
            "picture": {"source": source, "engine": pic.get("engine") or "", "why": pic.get("why") or ""},
            "voice": {"engine": v.get("engine") or "", "voice": v.get("voice") or "", "timing": v.get("timing") or ""},
            "motion": info.get("motion") or {}, "earlier": earlier,
            "in_plan": any(c["asset_id"] == s["clip_asset_id"] for c in parts),
            "included": any(c.get("include", True) for c in parts),
            "replaced": placed and not parts}


def view(project: dict, plan: dict | None = None) -> dict:
    """The short's part of the editor page (GET /api/studio/videos/<id> → `short`)."""
    from . import scenes

    short = project.get("short") or {}
    if plan is None and project.get("plan_revision"):
        plan = video_flow.plan_at(project["id"], project["plan_revision"])
    rows = ordered(scene_rows(project["id"]), plan)
    shown = [_scene_view(s, n, plan) for n, s in enumerate(rows, 1)]
    speed = float(short.get("speed") or 1.0)
    seconds = sum(x["duration"] or scenes.seconds(x["narration"], speed) for x in shown)
    state = _writer_state(db.get_settings())
    return {**{k: short.get(k, DEFAULTS.get(k, "")) for k in OPTION_FIELDS},
            "topic": short.get("topic") or "", "title": short.get("title") or "",
            "character": short.get("character") or "", "stage": short.get("stage") or "making",
            "message": short.get("message") or "", "scenes": shown,
            "progress": {"done": sum(1 for x in shown if x["status"] == "ready"), "total": len(shown)},
            "seconds": round(seconds, 1), "engines": _engines(),
            "writer": {**state, "used": short.get("writer")},
            "voice_rule": voice_rule(rows),
            "notes": _notes(rows, short, plan)}


def voice_rule(rows: list[dict]) -> str:
    """What the licence of the voice that spoke these scenes asks of what it makes ("" for none): the editor page
    shows it next to Download, where the short leaves ClipForge."""
    return next((str(r) for r in ((_info(s).get("voice") or {}).get("rule") for s in rows) if r), "")


def cover_asset(project_id: str) -> str:
    """The first scene's picture, for the project lists ("" while there is none)."""
    project = db.fetch("studio_projects", project_id)
    plan = video_flow.plan_at(project_id, project["plan_revision"]) if project and project["plan_revision"] else None
    for s in ordered(scene_rows(project_id), plan):
        if s["picture_asset_id"]:
            return s["picture_asset_id"]
    return ""

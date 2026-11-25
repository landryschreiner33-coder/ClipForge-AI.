"""Text Stories (the final-release prompt, section 8): a story read aloud over background video, with big captions.

The steps are the page's: script (pasted or written by ClipForge AI, which can also revise it) → voice (a voice, a
style, speed, tone and pronunciations; makers/voice_styles.py) → background (your own uploaded clips, trimmed,
looped and moved within the frame, or ones ClipForge picks from your usable videos; when you have none, a moving
colour background ClipForge draws itself) → preview (a small, quick render) → export (1080 × 1920, 30 fps, H.264
and AAC: what TikTok, YouTube Shorts and Reels take).

The narrator reads the title first, while it shows on a card in the middle of the screen; then the captions show
the story's words, the one being said lit up (studio/engine.highlight_events). The background's own sound is left
out. Everything is made on this computer by FFmpeg and the voice engines; only ClipForge AI's writing can go online,
and only when the AI service chosen in Settings is an online one (the page says so).

The work runs as studio jobs (studio/jobs.py), so it shows progress, can be stopped and continues after a restart.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import time
from pathlib import Path

from .. import config, db
from ..pipeline import ffmpeg_utils
from ..pipeline.common import Cancelled
from ..studio import engine, uploads
from ..studio.jobs import Canceled, Lease, cancel as cancel_job, enqueue, handler, on_stop
from . import voice_styles

log = logging.getLogger(__name__)

SIZE = (1080, 1920)
PREVIEW_SIZE = (360, 640)
FPS = 30
TAIL_S = 0.6               # the background runs on this long after the last word
TITLE_HOLD_S = 0.35        # the title card stays this long after its last word
MAX_SCRIPT = 6000          # characters
MAX_WORDS = 650            # about 3.7 minutes at 175 words a minute
MAX_TITLE = 140
MAX_NAME = 120
MAX_BACKGROUNDS = 12
MAX_PIECES = 80            # background pieces in one render (a short clip looped over a long story)
MIN_PIECE_S = 1.0
RENDER_RECIPE = 2          # part of every render key: a changed recipe renders again
WPM = 175
CAPTION_STYLES = {"bold": "Bold", "clean": "Clean", "high_energy": "High energy"}
CAPTION_PLACES = {"middle": "Middle", "raised": "Lower", "top": "Top"}
CAPTION_SIZES = {"medium": "Medium", "large": "Large"}
DEFAULT_CAPTIONS = {"style": "bold", "position": "middle", "size": "large"}
# Moving colour backgrounds ClipForge draws itself (FFmpeg's gradients source): free of anyone's rights
BUILTINS = {
    "aurora": {"name": "Aurora", "colors": ("0x0b1d51", "0x3a0ca3", "0x4cc9f0", "0x7209b7"), "type": "linear"},
    "sunset": {"name": "Sunset", "colors": ("0x3d0c45", "0xd1495b", "0xedae49", "0x1b1b3a"), "type": "radial"},
    "ocean": {"name": "Deep sea", "colors": ("0x03045e", "0x0077b6", "0x00b4d8", "0x023e8a"), "type": "circular"},
}
# words in a video's name that say it was made to sit behind a story
HINTS = ("gameplay", "minecraft", "parkour", "satisfying", "subway", "surfer", "driving", "drive", "racing", "race",
         "slime", "asmr", "background", "broll", "b-roll", "loop", "game", "soap", "sand", "kinetic", "satisfy")
WORKING = ("writing", "voicing", "rendering")


class StoryError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ rows
def folder(story_id: str) -> Path:
    d = config.data_dir() / "text_stories" / story_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get(story_id: str, workspace_id: str) -> dict:
    s = db.fetch("text_stories", story_id)
    if not s or s["workspace_id"] != workspace_id:
        raise StoryError("Story not found.", 404)
    return s


def _patch(story_id: str, **fields) -> dict:
    db._update("text_stories", story_id, fields)  # noqa: SLF001 - db.update takes the id as its first value
    return db.fetch("text_stories", story_id) or {}


def _hash(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def words_of(story: dict) -> int:
    return len((story.get("title") or "").split()) + len((story.get("script") or "").split())


def spoken(story: dict) -> tuple[str, str]:
    """(what the narrator reads as written, the title part of it). The title is read first, as its own sentence."""
    title = " ".join((story.get("title") or "").split())
    script = " ".join((story.get("script") or "").split())
    if title and not re.search(r"[.!?…]$", title):
        title_read = title + "."
    else:
        title_read = title
    return (f"{title_read} {script}".strip(), title_read)


# ------------------------------------------------------------------ the page's choices
def options(workspace_id: str) -> dict:
    from . import voice, writer

    try:
        voices = voice.voices()
    except Exception:  # noqa: BLE001 - the page still opens; the voice step says why
        log.exception("the voice list failed")
        voices = []
    settings = db.get_settings()
    return {
        "voices": voices, "default_voice": voice.default_voice() if voices else "",
        "styles": voice_styles.styles(), "tone_range": list(voice_styles.TONE_RANGE),
        "speed_range": list(voice_styles.SPEED_RANGE),
        "captions": {"styles": [{"id": k, "label": v} for k, v in CAPTION_STYLES.items()],
                     "positions": [{"id": k, "label": v} for k, v in CAPTION_PLACES.items()],
                     "sizes": [{"id": k, "label": v} for k, v in CAPTION_SIZES.items()]},
        "builtins": [{"id": k, "name": v["name"], "colors": ["#" + c[2:] for c in v["colors"]]}
                     for k, v in BUILTINS.items()],
        "writer": writer.ready(settings),
        "tones": [{"id": k, "label": v} for k, v in writer.STORY_TONE_LABELS.items()],
        "lengths": [{"id": k, "label": v} for k, v in writer.STORY_LENGTH_LABELS.items()],
        "favourites": voice_styles.favourites(workspace_id),
        "limits": {"max_words": MAX_WORDS, "max_title": MAX_TITLE, "wpm": WPM, "max_backgrounds": MAX_BACKGROUNDS},
        "links": {"ai": "#/settings/ai", "makers": "#/settings/makers"},
    }


def _starting_voice(workspace_id: str) -> dict:
    fav = voice_styles.favourite_for(workspace_id, style=voice_styles.DEFAULT_STYLE)
    return voice_styles.clean_voice(fav) if fav else voice_styles.clean_voice({})


def create(workspace_id: str, *, name: str = "", title: str = "", script: str = "") -> dict:
    title, script = _clean_title(title), _clean_script(script)
    story = db.insert("text_stories", {
        "id": "tst-" + os.urandom(6).hex(), "workspace_id": workspace_id, "name": " ".join(name.split())[:MAX_NAME],
        "title": title, "script": script, "voice": _starting_voice(workspace_id), "pronunciations": [],
        "captions": dict(DEFAULT_CAPTIONS), "backgrounds": [], "narration": {}, "preview": {}, "export": {},
        "writer": {}, "status": "draft", "message": ""})
    return story


def list_stories(workspace_id: str) -> list[dict]:
    rows = db.select("text_stories", "workspace_id = ?", (workspace_id,), "updated_at DESC", 200)
    return [{"id": s["id"], "name": display_name(s), "status": s["status"], "words": words_of(s),
             "exported": _file_ok(s, "export"), "updated_at": s["updated_at"]} for s in rows]


def display_name(story: dict) -> str:
    if story.get("name"):
        return story["name"]
    words = (story.get("title") or story.get("script") or "").split()
    return " ".join(words[:7]) + ("…" if len(words) > 7 else "") if words else "New text story"


def _clean_title(value: object) -> str:
    if not isinstance(value, str):
        raise StoryError("The title must be text.")
    title = " ".join(value.split())
    if len(title) > MAX_TITLE:
        raise StoryError(f"Keep the title under {MAX_TITLE} characters.")
    return title


def _clean_script(value: object) -> str:
    if not isinstance(value, str):
        raise StoryError("The script must be text.")
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", value.replace("\r", ""))]
    script = "\n\n".join(p for p in paras if p)
    if len(script) > MAX_SCRIPT or len(script.split()) > MAX_WORDS:
        raise StoryError(f"The script is too long for one video; keep it under {MAX_WORDS} words.")
    return script


def _clean_captions(raw: object, base: dict) -> dict:
    if not isinstance(raw, dict):
        raise StoryError("Captions must be a set of choices.")
    out = {**DEFAULT_CAPTIONS, **base}
    for key, allowed in (("style", CAPTION_STYLES), ("position", CAPTION_PLACES), ("size", CAPTION_SIZES)):
        if key in raw:
            if raw[key] not in allowed:
                raise StoryError(f"Choose one of the caption {key}s.")
            out[key] = raw[key]
    return out


def _num(value, lo: float, hi: float, what: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise StoryError(f"The {what} must be a number.") from None
    if not math.isfinite(v):
        raise StoryError(f"The {what} must be a number.")
    return min(hi, max(lo, v))


def _clean_backgrounds(workspace_id: str, raw: object) -> list[dict]:
    """[{"id", "asset_id" | "builtin", "in_s", "out_s", "loop", "focus_x", "focus_y", "why"}]: your own videos must
    be yours; a trim is kept inside the video and at least a second long."""
    if not isinstance(raw, list):
        raise StoryError("Backgrounds must be a list.")
    if len(raw) > MAX_BACKGROUNDS:
        raise StoryError(f"Use at most {MAX_BACKGROUNDS} background clips.")
    out = []
    for n, b in enumerate(raw):
        if not isinstance(b, dict):
            raise StoryError("A background must be a set of choices.")
        item: dict = {"id": str(b.get("id") or f"bg{n}-{os.urandom(3).hex()}")[:40],
                      "loop": bool(b.get("loop")), "why": " ".join(str(b.get("why") or "").split())[:200],
                      "focus_x": _num(b.get("focus_x", 0.5), 0.0, 1.0, "position"),
                      "focus_y": _num(b.get("focus_y", 0.5), 0.0, 1.0, "position")}
        if b.get("builtin"):
            if b["builtin"] not in BUILTINS:
                raise StoryError("That background is not one of ClipForge's.")
            item["builtin"] = b["builtin"]
            item["in_s"] = 0.0
            item["out_s"] = _num(b.get("out_s", 20.0), MIN_PIECE_S, 600.0, "length")
        else:
            asset = db.fetch("assets", str(b.get("asset_id") or ""))
            if not asset or asset["workspace_id"] != workspace_id:
                raise StoryError("That background video was not found. Choose it again.", 404)
            probe = asset.get("probe") or {}
            if asset["kind"] != "video" or not probe.get("has_video", True):
                raise StoryError(f"“{asset['filename']}” is not a video, so it cannot be a background.")
            length = float(probe.get("duration") or 0.0)
            if length < MIN_PIECE_S:
                raise StoryError(f"“{asset['filename']}” is shorter than a second.")
            a = _num(b.get("in_s", 0.0), 0.0, max(0.0, length - MIN_PIECE_S), "start")
            z = _num(b.get("out_s", length), a + MIN_PIECE_S, length, "end")
            item.update(asset_id=asset["id"], in_s=round(a, 2), out_s=round(z, 2))
        out.append(item)
    return out


def update(story: dict, body: dict) -> dict:
    """Change the story. Nothing changes while ClipForge is working on it (stop the work first)."""
    if story["status"] in WORKING:
        raise StoryError("ClipForge is working on this story. Wait for it to finish, or press Stop.", 409)
    ws = story["workspace_id"]
    fields: dict = {}
    if "name" in body:
        fields["name"] = " ".join(str(body["name"] or "").split())[:MAX_NAME]
    if "title" in body:
        fields["title"] = _clean_title(body["title"])
    if "script" in body:
        fields["script"] = _clean_script(body["script"])
    if "voice" in body:
        try:
            fields["voice"] = voice_styles.clean_voice(body["voice"], story.get("voice") or None)
        except voice_styles.VoiceStyleError as exc:
            raise StoryError(str(exc)) from exc
    if "pronunciations" in body:
        try:
            fields["pronunciations"] = voice_styles.clean_rules(body["pronunciations"])
        except voice_styles.VoiceStyleError as exc:
            raise StoryError(str(exc)) from exc
    if "captions" in body:
        fields["captions"] = _clean_captions(body["captions"], story.get("captions") or {})
    if "backgrounds" in body:
        fields["backgrounds"] = _clean_backgrounds(ws, body["backgrounds"])
    if not fields:
        return story
    changed = {k for k, v in fields.items() if v != story.get(k)}
    if changed - {"name"}:
        # what was made from the old choices is out of date: the page says so, and Preview makes it again
        fields["status"] = "draft"
        fields["error"] = ""
        fields["message"] = ""
    return _patch(story["id"], **fields)


def delete(story: dict) -> None:
    if story.get("job_id"):
        cancel_job(story["job_id"])
    db.execute("DELETE FROM text_stories WHERE id = ?", (story["id"],))
    db.execute("DELETE FROM voice_favorites WHERE workspace_id = ? AND scope = ?",
               (story["workspace_id"], f"project:{story['id']}"))
    shutil.rmtree(config.data_dir() / "text_stories" / story["id"], ignore_errors=True)


# ------------------------------------------------------------------ backgrounds ClipForge picks
def usable_backgrounds(workspace_id: str, need_s: float = 0.0) -> list[dict]:
    """Your videos that can sit behind a story, best first: [{"asset_id", "filename", "duration", "score", "why"}].
    A video counts when it has pictures and runs at least 5 seconds; a name that says gameplay, satisfying, parkour
    and the like, a vertical picture and enough length for the story rank it higher. Never the exports of text
    stories themselves."""
    made = {str(s.get("export_asset_id") or "") for s in
            (r.get("export") or {} for r in db.select("text_stories", "workspace_id = ?", (workspace_id,)))}
    out = []
    for a in db.select("assets", "workspace_id = ? AND kind = 'video'", (workspace_id,), "created_at DESC", 400):
        p = a.get("probe") or {}
        d = float(p.get("duration") or 0.0)
        if a["id"] in made or not p.get("has_video", True) or d < 5.0:
            continue
        if not uploads.is_linked(a) and not Path(a["path"]).is_file():
            continue
        name = (a.get("filename") or "").lower()
        why, score = [], 0.0
        hint = next((h for h in HINTS if h in re.sub(r"[_.]", " ", name)), "")
        if hint:
            score += 3
            why.append(f"its name says “{hint}”")
        w, h = int(p.get("width") or 0), int(p.get("height") or 0)
        if h > w > 0:
            score += 1
            why.append("it is already vertical")
        if need_s and d >= need_s:
            score += 1
            why.append("it is long enough for the whole story")
        if not p.get("has_audio"):
            score += 0.5
            why.append("it has no sound of its own to hide")
        score += min(1.0, d / 300.0)  # longer videos repeat less
        out.append({"asset_id": a["id"], "filename": a.get("filename") or "", "duration": round(d, 1),
                    "width": w, "height": h, "score": round(score, 2),
                    "why": ("Picked because " + ", ".join(why) + ".") if why else "Picked from your videos."})
    out.sort(key=lambda c: (-c["score"], -c["duration"]))
    return out


def auto_backgrounds(story: dict) -> dict:
    """Let ClipForge choose: the best one or two of your usable videos (the last one loops until the story ends),
    or, when you have none, one of ClipForge's own moving colour backgrounds."""
    if story["status"] in WORKING:
        raise StoryError("ClipForge is working on this story. Wait for it to finish, or press Stop.", 409)
    need = estimate_seconds(story)
    found = usable_backgrounds(story["workspace_id"], need)
    picks: list[dict] = []
    total = 0.0
    for c in found[:2]:
        if picks and total >= need:
            break
        length = c["duration"]
        picks.append({"asset_id": c["asset_id"], "in_s": 0.0, "out_s": length, "loop": False, "focus_x": 0.5,
                      "focus_y": 0.5, "why": c["why"]})
        total += length
    if picks:
        picks[-1]["loop"] = True
    else:
        builtin = list(BUILTINS)[int(_hash(story["id"]), 16) % len(BUILTINS)]
        picks = [{"builtin": builtin, "out_s": 20.0, "loop": True, "focus_x": 0.5, "focus_y": 0.5,
                  "why": "You have no videos to use yet, so ClipForge draws a moving colour background."}]
    return update(story, {"backgrounds": picks})


def estimate_seconds(story: dict) -> float:
    narr = story.get("narration") or {}
    if narr.get("key") and narr.get("key") == narration_key(story):
        return float(narr.get("duration") or 0.0) + TAIL_S
    speed = float((story.get("voice") or {}).get("speed") or 1.0)
    return round(words_of(story) / (WPM * speed) * 60.0 + TAIL_S, 1)


# ------------------------------------------------------------------ the work
def narration_key(story: dict) -> str:
    v = story.get("voice") or {}
    return _hash("narration", spoken(story)[0], v.get("voice"), v.get("speed"), v.get("tone"),
                 story.get("pronunciations") or [])


def render_key(story: dict, mode: str) -> str:
    return _hash("render", RENDER_RECIPE, mode, narration_key(story), story.get("backgrounds") or [],
                 story.get("captions") or {}, story.get("title") or "")


def _file_ok(story: dict, what: str) -> bool:
    made = story.get(what) or {}
    return bool(made.get("file")) and (folder(story["id"]) / made["file"]).is_file()


def current(story: dict, what: str) -> bool:
    """Whether the preview or export on disk was made from the story as it is now."""
    made = story.get(what) or {}
    return _file_ok(story, what) and made.get("key") == render_key(story, what)


def start(story: dict, what: str, body: dict | None = None) -> dict:
    """Start writing ("write"), a preview ("preview") or the export ("export")."""
    from . import writer

    if story["status"] in WORKING:
        raise StoryError("ClipForge is already working on this story.", 409)
    if what == "write":
        body = body or {}
        settings = db.get_settings()
        if not writer.ready(settings)["configured"]:
            raise StoryError("Writing needs ClipForge AI. Set it up in Settings → ClipForge AI, or write the script "
                             "yourself.")
        change = " ".join(str(body.get("change") or "").split())[:400]
        topic = " ".join(str(body.get("topic") or "").split())[:300]
        if change and not (story.get("script") or "").strip():
            raise StoryError("There is no script to revise yet. Write one first.")
        if not change and not topic:
            raise StoryError("Say what the story is about.")
        ask = {"topic": topic, "change": change, "tone": body.get("tone") if body.get("tone") in writer.STORY_TONES
               else "drama", "length": body.get("length") if body.get("length") in writer.STORY_LENGTHS
               else "standard"}
        fields = {"writer": {**(story.get("writer") or {}), "ask": ask}, "status": "writing", "stage": "write",
                  "message": "ClipForge AI is revising the story" if change else "ClipForge AI is writing the story"}
        kind = "text_story_write"
    elif what in ("preview", "export"):
        if not words_of(story):
            raise StoryError("Write or paste the story first.")
        if not story.get("backgrounds"):
            raise StoryError("Choose a background first, or let ClipForge pick one.")
        if current(story, what):
            return story  # already made from the story as it is
        fields = {"status": "voicing", "stage": what, "message": "Recording the voice"}
        kind = "text_story_render"
    else:
        raise StoryError("Unknown step.")
    revision = int(story.get("revision") or 0) + 1
    fields.update(revision=revision, error="")
    story = _patch(story["id"], **fields)
    job = enqueue(story["workspace_id"], kind, story["id"], revision)
    return _patch(story["id"], job_id=job["id"])


def stop(story: dict) -> dict:
    if story["status"] not in WORKING or not story.get("job_id"):
        return story
    cancel_job(story["job_id"])
    return db.fetch("text_stories", story["id"]) or story


def _settle(story_id: str, how: str, error: str = "") -> None:
    s = db.fetch("text_stories", story_id)
    if not s or s["status"] not in WORKING:
        return
    _patch(story_id, status="failed" if how == "failed" else "draft", stage="",
           message="Stopped. Nothing new was kept." if how == "canceled" else "", error=error[:600] if error else
           ("Stopped after repeated interruptions. Press the button again to try once more." if how == "failed"
            else ""))


@on_stop("text_story_write")
def _write_stopped(job: dict, how: str) -> None:
    _settle(job["target_id"], how)


@on_stop("text_story_render")
def _render_stopped(job: dict, how: str) -> None:
    _settle(job["target_id"], how)


def _own_job(job: dict) -> dict | None:
    s = db.fetch("text_stories", job["target_id"])
    return s if s and s.get("job_id") == job["id"] else None


def _plain(exc: BaseException) -> str:
    from . import voice, writer

    if isinstance(exc, (voice.VoiceError, writer.WriterError, StoryError)):
        return str(exc)
    if isinstance(exc, ffmpeg_utils.FFmpegError):
        return "FFmpeg could not make the video. Try another background clip, or try again."
    if isinstance(exc, OSError):
        return "ClipForge could not save the video. Check that the disk has free space, then try again."
    return f"Something went wrong ({type(exc).__name__}). Try again."


@handler("text_story_write")
def write_job(job: dict, lease: Lease) -> dict:
    from . import writer

    story = _own_job(job)
    if story is None:
        return {"skipped": True}
    ask = (story.get("writer") or {}).get("ask") or {}
    try:
        got = writer.write_story(ask.get("topic") or "", tone=ask.get("tone") or "drama",
                                 length=ask.get("length") or "standard", settings=db.get_settings(),
                                 workspace_id=story["workspace_id"], project_id=story["id"],
                                 current={"title": story.get("title"), "script": story.get("script")}
                                 if ask.get("change") else None, change=ask.get("change") or "",
                                 cancel=lease.canceled, beat=lambda m: lease.progress(0.5, m))
    except (Canceled, Cancelled):
        raise
    except Exception as exc:
        _patch(story["id"], status="failed", stage="", message="", error=_plain(exc))
        raise
    if _own_job(job) is None or lease.canceled():
        raise Canceled()
    script = _clean_script(got["script"])
    _patch(story["id"], title=_clean_title(got["title"][:MAX_TITLE]), script=script, status="draft", stage="",
           error="", message=("ClipForge AI revised the story." if ask.get("change") else
                              "ClipForge AI wrote the story. Read it through and change anything you like."),
           writer={"ask": ask, "notes": got["notes"], "model": got["model"], "local": got["local"],
                   "at": time.time()})
    return {"words": len(script.split())}


@handler("text_story_render")
def render_job(job: dict, lease: Lease) -> dict:
    story = _own_job(job)
    if story is None:
        return {"skipped": True}
    what = story.get("stage") if story.get("stage") in ("preview", "export") else "preview"
    try:
        narration = make_narration(story, lease)
        story = _patch(story["id"], narration=narration, status="rendering",
                       message="Making the preview" if what == "preview" else "Making the video")
        made = render(story, what, lease)
    except (Canceled, Cancelled):
        raise
    except Exception as exc:
        log.exception("text story %s failed", story["id"])
        _patch(story["id"], status="failed", stage="", message="", error=_plain(exc))
        raise
    if _own_job(job) is None:
        raise Canceled()
    _patch(story["id"], **{what: made}, status="ready", stage="", error="",
           message="The preview is ready." if what == "preview" else "Your video is ready to download.")
    return {"file": made["file"], "duration": made["duration"]}


def make_narration(story: dict, lease: Lease | None = None) -> dict:
    """The narrator's recording of the title and script, with every written word's time (kept while nothing it
    depends on changes)."""
    from . import voice

    key = narration_key(story)
    old = story.get("narration") or {}
    d = folder(story["id"])
    if old.get("key") == key and (d / str(old.get("file") or "-")).is_file():
        return old
    written, title_read = spoken(story)
    if not written:
        raise StoryError("Write or paste the story first.")
    v = story.get("voice") or voice_styles.clean_voice({})
    said, counts = voice_styles.pronounce(written, story.get("pronunciations") or [])
    if lease:
        lease.progress(0.05, "Recording the voice")
    raw = d / f"voice-{key}.raw.wav"
    got = voice.speak(said, raw, voice=v.get("voice") or "auto", speed=float(v.get("speed") or 1.0),
                      cancel=lease.canceled if lease else None)
    out = d / f"voice-{key}.wav"
    if lease:
        lease.progress(0.25, "Timing the words")
    voice_styles.shape(raw, out, float(v.get("tone") or 0.0), cancel=lease.canceled if lease else None)
    raw.unlink(missing_ok=True)
    timed, how = voice.time_words(out, said, engine_words=got.get("words"), settings=db.get_settings(),
                                  cancel=lease.canceled if lease else None)
    if len(timed) != len(said.split()):
        timed, how = voice.estimate_words(out, said), "estimated"
    words = voice_styles.words_back(timed, written, counts)
    for old_file in d.glob("voice-*.wav"):
        if old_file.name != out.name:
            old_file.unlink(missing_ok=True)
    duration = float(got.get("duration_s") or 0.0) or (words[-1]["end"] if words else 0.0)
    return {"key": key, "file": out.name, "duration": round(duration, 3), "words": words,
            "title_words": len(title_read.split()), "timing": how, "engine": got.get("engine") or "",
            "voice": got.get("voice") or "", "voice_id": got.get("voice_id") or "",
            "fallback": got.get("fallback") or "", "rule": got.get("rule") or ""}


def pieces(backgrounds: list[dict], total_s: float) -> list[dict]:
    """The background clips in the order they play until `total_s`: a looping clip repeats until the end (clips
    after it are not reached); when none loops and they run out, the last picture holds."""
    out: list[dict] = []
    t = 0.0
    for b in backgrounds:
        length = max(MIN_PIECE_S, float(b["out_s"]) - float(b["in_s"]))
        while t < total_s - 0.01 and len(out) < MAX_PIECES:
            take = min(length, total_s - t)
            out.append({**b, "length": round(take, 3)})
            t += take
            if not b.get("loop"):
                break
        if t >= total_s - 0.01 or len(out) >= MAX_PIECES:
            break
    return out


def _title_style(width: int, height: int) -> str:
    scale = min(width, height) / 1080
    size = max(14, int(78 * scale))
    pad = max(8, int(34 * scale))
    margin = int(110 * scale)
    # BorderStyle 3: an opaque box behind the words (its colour is the outline colour), white with dark words
    return (f"Style: Title,Poppins ExtraBold,{size},&H00141414,&H00141414,&H00FFFFFF,&H64000000,-1,0,0,0,100,100,0,0,"
            f"3,{pad},0,5,{margin},{margin},0,1")


def story_ass(story: dict, narration: dict, width: int, height: int) -> str:
    """The title card and the captions for this frame size."""
    words = narration.get("words") or []
    n = int(narration.get("title_words") or 0)
    title_words, rest = words[:n], words[n:]
    captions = {**DEFAULT_CAPTIONS, **(story.get("captions") or {})}
    events = engine.highlight_events(rest, captions) if rest else []
    text = engine.captions_ass(rest, captions, width, height, events=events)
    head, sep, tail = text.partition("\n\n[Events]")
    head += "\n" + _title_style(width, height)
    title = " ".join((story.get("title") or "").split())
    if title and title_words:
        end = float(title_words[-1]["end"]) + TITLE_HOLD_S
        first = float(rest[0]["start"]) if rest else end
        end = max(0.8, min(end, first - 0.02) if rest else end)
        safe = title.replace("{", "(").replace("}", ")").replace("\\", "/")
        tail += f"Dialogue: 1,{engine._ass_time(0.0)},{engine._ass_time(end)},Title,,0,0,0,,{safe}\n"  # noqa: SLF001
    return head + sep + tail


def _source_args(piece: dict, size: tuple[int, int]) -> list[str]:
    w, h = size
    if piece.get("builtin"):
        b = BUILTINS[piece["builtin"]]
        colours = ":".join(f"c{i}={c}" for i, c in enumerate(b["colors"]))
        return ["-f", "lavfi", "-i", f"gradients=s={w}x{h}:r={FPS}:{colours}:n={len(b['colors'])}:speed=0.012:"
                                     f"type={b['type']}:seed=7:d={piece['length']:.3f}"]
    asset = db.fetch("assets", piece["asset_id"])
    if not asset:
        raise StoryError("A background video was deleted. Choose another background.")
    path = Path(asset["path"])
    if not path.is_file():
        raise StoryError(f"The background video “{asset.get('filename') or path.name}” is missing from this "
                         "computer. Choose another background.")
    return ["-ss", f"{float(piece['in_s']):.3f}", "-t", f"{piece['length']:.3f}", "-i", str(path)]


def render(story: dict, what: str, lease: Lease | None = None) -> dict:
    """Render the preview (360 × 640, quick) or the export (1080 × 1920): the background pieces filling the frame
    (cropped around where you placed them), the narration, the title card and the captions."""
    narration = story.get("narration") or {}
    d = folder(story["id"])
    voice_file = d / str(narration.get("file") or "-")
    if not voice_file.is_file():
        raise StoryError("The voice recording is missing. Press Preview again.")
    size = PREVIEW_SIZE if what == "preview" else SIZE
    w, h = size
    total = round(float(narration.get("duration") or 0.0) + TAIL_S, 3)
    plays = pieces(story.get("backgrounds") or [], total)
    if not plays:
        raise StoryError("Choose a background first, or let ClipForge pick one.")
    args: list[str] = []
    chains = []
    for i, p in enumerate(plays):
        args += _source_args(p, size)
        fx, fy = float(p.get("focus_x", 0.5)), float(p.get("focus_y", 0.5))
        chains.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                      f"crop={w}:{h}:(in_w-{w})*{fx:.3f}:(in_h-{h})*{fy:.3f},setsar=1,fps={FPS},format=yuv420p,"
                      f"trim=duration={p['length']:.3f},setpts=PTS-STARTPTS[v{i}]")
    args += ["-i", str(voice_file)]
    ass = d / f"{what}.ass"
    ass.write_text(story_ass(story, narration, w, h), encoding="utf-8")
    joined = "".join(f"[v{i}]" for i in range(len(plays)))
    chains.append(f"{joined}concat=n={len(plays)}:v=1:a=0,tpad=stop_mode=clone:stop_duration={total:.3f},"
                  f"trim=duration={total:.3f},setpts=PTS-STARTPTS,"
                  f"ass={ffmpeg_utils.filter_path(ass, d)}:fontsdir={ffmpeg_utils.filter_path(config.FONTS_DIR, d)},"
                  f"format=yuv420p[vout]")
    chains.append(f"[{len(plays)}:a]aresample=48000,apad[aout]")
    tmp = d / f"{what}.part.mp4"
    if what == "preview":
        video = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p"]
    else:
        video, _ = ffmpeg_utils.video_encoder_args(db.get_settings())
        video += ffmpeg_utils.delivery_args(FPS)
    out_args = [*args, "-filter_complex", ";".join(chains), "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.3f}",
                "-r", str(FPS), *video, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
                str(tmp)]

    def progress(frac: float) -> None:
        if lease:
            lease.progress(0.35 + 0.63 * frac, "Making the preview" if what == "preview" else "Making the video")

    ffmpeg_utils.run(out_args, duration=total, progress=progress, cancel=lease.canceled if lease else None, cwd=d)
    final = d / f"{what}.mp4"
    tmp.replace(final)
    ass.unlink(missing_ok=True)
    return {"key": render_key(story, what), "file": final.name, "duration": total, "width": w, "height": h,
            "at": time.time(), "size": final.stat().st_size}


# ------------------------------------------------------------------ what the page shows
def view(story: dict) -> dict:
    job = db.fetch("studio_jobs", story.get("job_id") or "") if story.get("job_id") else None
    working = story["status"] in WORKING
    backgrounds = []
    for b in story.get("backgrounds") or []:
        item = dict(b)
        if b.get("asset_id"):
            a = db.fetch("assets", b["asset_id"])
            p = (a or {}).get("probe") or {}
            item.update(filename=(a or {}).get("filename") or "A deleted video", missing=a is None,
                        duration=p.get("duration"), width=p.get("width"), height=p.get("height"),
                        has_thumbnail=bool((a or {}).get("thumb_path")))
        else:
            item.update(name=BUILTINS.get(b.get("builtin") or "", {}).get("name", ""))
        backgrounds.append(item)
    narr = story.get("narration") or {}
    fresh_voice = bool(narr.get("key")) and narr.get("key") == narration_key(story)
    made = {}
    for what in ("preview", "export"):
        m = story.get(what) or {}
        made[what] = {"ready": _file_ok(story, what), "current": current(story, what), "duration": m.get("duration"),
                      "at": m.get("at"), "size": m.get("size"),
                      "url": f"/api/studio/text-stories/{story['id']}/file/{what}?v={m.get('key', '')}"
                      if _file_ok(story, what) else ""}
    v = story.get("voice") or {}
    return {
        "id": story["id"], "name": display_name(story), "own_name": story.get("name") or "",
        "title": story.get("title") or "", "script": story.get("script") or "", "words": words_of(story),
        "seconds": estimate_seconds(story), "voice": v, "pronunciations": story.get("pronunciations") or [],
        "captions": {**DEFAULT_CAPTIONS, **(story.get("captions") or {})}, "backgrounds": backgrounds,
        "status": story["status"], "stage": story.get("stage") or "", "message": story.get("message") or "",
        "error": story.get("error") or "", "working": working,
        "job": {"progress": float(job.get("progress") or 0.0), "message": job.get("message") or ""}
        if job and working else None,
        "narration": {"ready": fresh_voice, "voice": narr.get("voice") or "", "fallback": narr.get("fallback") or "",
                      "timing": narr.get("timing") or "", "rule": narr.get("rule") or "",
                      "duration": narr.get("duration")} if narr else {"ready": False},
        "made": made, "writer": {k: (story.get("writer") or {}).get(k) for k in ("notes", "model", "local")},
        "project_id": story.get("project_id") or "", "updated_at": story["updated_at"],
        "steps": {"script": words_of(story) > 0, "voice": bool(v.get("voice")), "background": bool(backgrounds),
                  "preview": made["preview"]["current"], "export": made["export"]["current"]},
    }


def file_for(story: dict, what: str) -> Path:
    if what not in ("preview", "export"):
        raise StoryError("Not found.", 404)
    if not _file_ok(story, what):
        raise StoryError("That video has not been made yet.", 404)
    return folder(story["id"]) / story[what]["file"]


def open_in_editor(story: dict, user_id: str) -> dict:
    """The exported video as a new project in the editor (where it can be trimmed, captioned again and posted)."""
    from ..studio import video_flow

    if not current(story, "export"):
        raise StoryError("Export the story first; the editor opens the exported video.")
    src = file_for(story, "export")
    copy = folder(story["id"]) / "to-editor.mp4"
    shutil.copyfile(src, copy)
    name = display_name(story)
    try:
        asset = uploads.store_file(story["workspace_id"], copy, f"{name[:80]}.mp4")
    except uploads.UploadError as exc:
        copy.unlink(missing_ok=True)
        raise StoryError(str(exc), getattr(exc, "status", 422)) from exc
    project = video_flow.create(story["workspace_id"], user_id, name=name, asset_ids=[asset["id"]], brief={})
    export = {**(story.get("export") or {}), "export_asset_id": asset["id"]}
    _patch(story["id"], project_id=project["id"], export=export)
    return project

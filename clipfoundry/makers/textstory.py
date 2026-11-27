"""Text Stories (the final-release prompt, section 8): a story read aloud over background video, with big captions;
or, as a story of the "chat" kind, a text-message conversation that appears a bubble at a time over the background, each
message read aloud in its sender's voice (makers/chatstory.py, Landry 2026-11-26). Both kinds run up to ten minutes.

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
from ..pipeline import ffmpeg_utils, grade
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
MAX_SCRIPT = 16000         # characters
MAX_WORDS = 1750           # about ten minutes at 175 words a minute (Landry, 2026-11-26: "up to 10")
MAX_TITLE = 140
MAX_NAME = 120
MAX_BACKGROUNDS = 12
MAX_PIECES = 5000          # a guard only: a looping clip is one input however often it plays (render())
MIN_PIECE_S = 1.0
RENDER_RECIPE = 2          # part of every render key: a changed recipe renders again
KINDS = {"chat": "Text-message story", "narrated": "Narrated story"}
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
         "slime", "asmr", "background", "broll", "b-roll", "loop", "game", "soap", "sand", "kinetic", "satisfy",
         # the cooking and cutting clips text-message stories are told over
         "cooking", "cook", "cutting", "slicing", "chopping", "knife", "chef", "kitchen", "recipe", "food", "cake")
WORKING = ("writing", "voicing", "rendering")
STUCK = "ClipForge stopped before it finished, and nothing new was kept. Press the button again to try once more."


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
    return _unstick(s)


def _unstick(story: dict) -> dict:
    """A story that says ClipForge is working on it while its job has ended (or is gone) is settled, so the page never
    shows work that is not happening and Stop, the edits and the buttons work again. The handlers settle the story
    themselves; this catches what a crash between their steps could leave."""
    if story["status"] not in WORKING:
        return story
    job = db.fetch("studio_jobs", story.get("job_id") or "") if story.get("job_id") else None
    if job and job["status"] in ("queued", "running"):
        return story
    # a Stop marks its job canceled a moment before it settles the story: settled here as that Stop would
    stopped = bool(job and job["status"] == "canceled")
    _settle(story["id"], "canceled" if stopped else "failed", "" if stopped else STUCK, job_id=story.get("job_id"))
    return db.fetch("text_stories", story["id"]) or story


def _patch(story_id: str, **fields) -> dict:
    db._update("text_stories", story_id, fields)  # noqa: SLF001 - db.update takes the id as its first value
    return db.fetch("text_stories", story_id) or {}


def _hash(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def words_of(story: dict) -> int:
    if is_chat(story):
        from . import chatstory

        return chatstory.words_in(chatstory.parse(story.get("script") or ""))
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
    from . import chatstory, voice, writer

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
        "kinds": [{"id": k, "label": v} for k, v in KINDS.items()],
        "chat": {"themes": [{"id": k, "label": v["label"],
                             **{part: "#%02x%02x%02x" % rgb for part, rgb in v.items() if part != "label"}}
                            for k, v in chatstory.THEMES.items()],
                 "paces": [{"id": k, "label": v} for k, v in chatstory.PACE_LABELS.items()],
                 "tones": [{"id": k, "label": v} for k, v in writer.CHAT_TONE_LABELS.items()],
                 "lengths": [{"id": k, "label": v} for k, v in writer.CHAT_LENGTH_LABELS.items()],
                 "limits": {"max_messages": chatstory.MAX_MESSAGES, "max_words": chatstory.MAX_WORDS,
                            "max_message": chatstory.MAX_MESSAGE_CHARS, "max_seconds": chatstory.MAX_SECONDS,
                            "max_people": chatstory.MAX_PEOPLE},
                 "emoji_note": chatstory.platform_emoji_note()},
    }


def _starting_voice(workspace_id: str) -> dict:
    fav = voice_styles.favourite_for(workspace_id, style=voice_styles.DEFAULT_STYLE)
    return voice_styles.clean_voice(fav) if fav else voice_styles.clean_voice({})


def create(workspace_id: str, *, name: str = "", title: str = "", script: str = "", kind: str = "narrated") -> dict:
    from . import chatstory

    if kind not in KINDS:
        raise StoryError("Choose a text-message story or a narrated story.")
    chat: dict = {}
    if kind == "chat":
        title, script = "", _clean_chat_script(script)
        chat = chatstory.with_voices(script, dict(chatstory.DEFAULT_CHAT))
    else:
        title, script = _clean_title(title), _clean_script(script)
    story = db.insert("text_stories", {
        "id": "tst-" + os.urandom(6).hex(), "workspace_id": workspace_id, "name": " ".join(name.split())[:MAX_NAME],
        "kind": kind, "chat": chat,
        "title": title, "script": script, "voice": _starting_voice(workspace_id), "pronunciations": [],
        "captions": dict(DEFAULT_CAPTIONS), "backgrounds": [], "narration": {}, "preview": {}, "export": {},
        "writer": {}, "status": "draft", "message": ""})
    return story


def is_chat(story: dict) -> bool:
    return story.get("kind") == "chat"


def _clean_chat_script(value: object) -> str:
    from . import chatstory

    try:
        return chatstory.clean_script(value)
    except chatstory.ChatError as exc:
        raise StoryError(str(exc), exc.status) from exc


def list_stories(workspace_id: str) -> list[dict]:
    rows = db.select("text_stories", "workspace_id = ?", (workspace_id,), "updated_at DESC", 200)
    return [{"id": s["id"], "name": display_name(s), "status": s["status"], "words": words_of(s),
             "kind": s.get("kind") or "narrated", "messages": _messages(s) if is_chat(s) else 0,
             "exported": _file_ok(s, "export"), "updated_at": s["updated_at"]} for s in rows]


def _messages(story: dict) -> int:
    from . import chatstory

    return len(chatstory.parse(story.get("script") or ""))


def display_name(story: dict) -> str:
    if story.get("name"):
        return story["name"]
    if is_chat(story):
        from . import chatstory

        got = chatstory.resolve(story.get("script") or "", story.get("chat") or {})
        if not got["messages"]:
            return "New text-message story"
        words = got["messages"][0]["text"].split()
        return f"{got['contact']}: " + " ".join(words[:6]) + ("…" if len(words) > 6 else "")
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
    from . import chatstory

    ws = story["workspace_id"]
    fields: dict = {}
    kind = story.get("kind") or "narrated"
    if "kind" in body:
        if body["kind"] not in KINDS:
            raise StoryError("Choose a text-message story or a narrated story.")
        kind = fields["kind"] = body["kind"]
    if "name" in body:
        fields["name"] = " ".join(str(body["name"] or "").split())[:MAX_NAME]
    if "title" in body:
        fields["title"] = _clean_title(body["title"])
    if "script" in body or "kind" in body:
        raw = body.get("script", story.get("script") or "")
        if "script" not in body and kind != (story.get("kind") or "narrated"):
            # the same words in the other kind: a chat's messages become paragraphs, and paragraphs messages, so
            # switching back gives the same chat
            raw = str(raw or "")
            raw = ("\n".join(" ".join(p.split()) for p in re.split(r"\n\s*\n", raw) if p.strip()) if kind == "chat"
                   else "\n\n".join(line.strip() for line in raw.split("\n") if line.strip()))
        fields["script"] = _clean_chat_script(raw) if kind == "chat" else _clean_script(raw)
    if kind == "chat" and ("chat" in body or "script" in fields):
        try:
            chat = chatstory.clean_chat(body.get("chat") or {}, story.get("chat") or {})
        except chatstory.ChatError as exc:
            raise StoryError(str(exc), exc.status) from exc
        # everyone in the script has a voice; people who left it lose theirs
        fields["chat"] = chatstory.with_voices(fields.get("script", story.get("script") or ""), chat)
    if "voice" in body:
        raw = body["voice"]
        if isinstance(raw, dict) and "style" in raw and "voice" not in raw and \
                raw["style"] != (story.get("voice") or {}).get("style"):
            # a style picked on its own: the story's kept voice stays, else the style's favourite comes with it
            raw = {**voice_styles.for_style(ws, story["id"], str(raw["style"])), **raw}
        try:
            fields["voice"] = voice_styles.clean_voice(raw, story.get("voice") or None)
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
    """The story, its favourite voice, its folder (voice, preview, export) and what ClipForge AI remembered about it
    (Brain memories kept for this story). The fingerprints of its exports stay (text_story_exports), so a copy of one
    is never offered back as a background."""
    if story.get("job_id"):
        cancel_job(story["job_id"])
    ws, scope = story["workspace_id"], f"project:{story['id']}"
    with db.connect() as conn:
        conn.execute("DELETE FROM text_stories WHERE id = ?", (story["id"],))
        conn.execute("DELETE FROM voice_favorites WHERE workspace_id = ? AND scope = ?", (ws, scope))
    _forget(ws, story["id"])
    shutil.rmtree(config.data_dir() / "text_stories" / story["id"], ignore_errors=True)


def _forget(workspace_id: str, story_id: str) -> None:
    """What ClipForge AI remembered about this story: its Brain memories and the uses recorded for it. The scope says
    whom a memory is for (as when a video is deleted: studio/project_delete.py)."""
    scope = f"project:{story_id}"
    with db.connect() as conn:
        conn.execute("DELETE FROM brain_memory_uses WHERE memory_id IN (SELECT id FROM brain_memories WHERE "
                     "workspace_id = ? AND scope = ?)", (workspace_id, scope))
        conn.execute("DELETE FROM brain_memories WHERE workspace_id = ? AND scope = ?", (workspace_id, scope))


# ------------------------------------------------------------------ backgrounds ClipForge picks
def usable_backgrounds(workspace_id: str, need_s: float = 0.0) -> list[dict]:
    """Your videos that can sit behind a story, best first: [{"asset_id", "filename", "duration", "score", "why"}].
    A video counts when it has pictures and runs at least 5 seconds; a name that says gameplay, satisfying, parkour
    and the like, a vertical picture and enough length for the story rank it higher. Never the exports of text
    stories themselves."""
    made = {str(s.get("export_asset_id") or "") for s in
            (r.get("export") or {} for r in db.select("text_stories", "workspace_id = ?", (workspace_id,)))}
    # every story video ever sent to the editor, also after a new export or the story's deletion
    made_sha = {r["sha256"] for r in db.select("text_story_exports", "workspace_id = ?", (workspace_id,))}
    out = []
    for a in db.select("assets", "workspace_id = ? AND kind = 'video'", (workspace_id,), "created_at DESC", 400):
        p = a.get("probe") or {}
        d = float(p.get("duration") or 0.0)
        if a["id"] in made or a.get("sha256") in made_sha or not p.get("has_video", True) or d < 5.0:
            continue
        if not Path(a["path"]).is_file():  # stored or linked: a linked video can be moved or deleted too
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
        return total_seconds(story, narr)
    if is_chat(story):
        from . import chatstory

        return chatstory.estimate(story.get("script") or "", story.get("chat") or {})
    speed = float((story.get("voice") or {}).get("speed") or 1.0)
    return round(words_of(story) / (WPM * speed) * 60.0 + TAIL_S, 1)


def total_seconds(story: dict, narration: dict) -> float:
    """The video's length once its voice is recorded: a chat's own timing (its last bubble stays a moment), a
    narrated story's voice and TAIL_S."""
    if is_chat(story):
        return round(float(narration.get("total") or 0.0), 3)
    return round(float(narration.get("duration") or 0.0) + TAIL_S, 3)


# ------------------------------------------------------------------ the work
def narration_key(story: dict) -> str:
    if is_chat(story):
        from . import chatstory

        return chatstory.narration_key(story.get("script") or "", story.get("chat") or {},
                                       story.get("pronunciations") or [])
    v = story.get("voice") or {}
    return _hash("narration", spoken(story)[0], v.get("voice"), v.get("speed"), v.get("tone"),
                 story.get("pronunciations") or [])


def render_key(story: dict, mode: str) -> str:
    if is_chat(story):
        from . import chatstory

        chat = story.get("chat") or {}
        contact = chatstory.resolve(story.get("script") or "", chat)["contact"]
        return _hash("render-chat", RENDER_RECIPE, chatstory.RECIPE, mode, narration_key(story),
                     story.get("backgrounds") or [], chatstory.look_key(chat, contact))
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
        tones, lengths = ((writer.CHAT_TONES, writer.CHAT_LENGTHS) if is_chat(story) else
                          (writer.STORY_TONES, writer.STORY_LENGTHS))
        ask = {"topic": topic, "change": change, "tone": body.get("tone") if body.get("tone") in tones
               else "drama", "length": body.get("length") if body.get("length") in lengths
               else "standard"}
        fields = {"writer": {**(story.get("writer") or {}), "ask": ask}, "status": "writing", "stage": "write",
                  "message": "ClipForge AI is revising the story" if change else "ClipForge AI is writing the story"}
        kind = "text_story_write"
    elif what in ("preview", "export"):
        if not words_of(story):
            raise StoryError("Write or paste the chat first." if is_chat(story) else "Write or paste the story first.")
        if not story.get("backgrounds"):
            raise StoryError("Choose a background first, or let ClipForge pick one.")
        if current(story, what):
            return story  # already made from the story as it is
        fields = {"status": "voicing", "stage": what, "message": "Recording the voice"}
        kind = "text_story_render"
    else:
        raise StoryError("Unknown step.")
    revision = int(story.get("revision") or 0) + 1
    # the job is made first and handed to the worker only once the story names it: a worker that took the job before
    # the story named it would find it is not the story's job, skip it and leave the story working forever
    job = enqueue(story["workspace_id"], kind, story["id"], revision, submit=False)
    fields.update(revision=revision, error="", job_id=job["id"])
    story = _patch(story["id"], **fields)
    from ..jobs import worker

    worker.submit_studio(job["id"])
    return story


def stop(story: dict) -> dict:
    if story["status"] not in WORKING:
        return story
    if not story.get("job_id") or not cancel_job(story["job_id"]):
        # its job had already ended (or is gone): nothing else would settle it. Only while the story is still on that
        # job: a newer job started since (another tab, a quick second press) is not stopped by this older Stop
        _settle(story["id"], "canceled", job_id=story.get("job_id") or None)
    return db.fetch("text_stories", story["id"]) or story


def _settle(story_id: str, how: str, error: str = "", *, job_id: str | None = None) -> None:
    """A story whose work ended without a result (stopped, failed) goes back to editing, in one write that changes it
    only while it is still working (on `job_id`, when given): a result or a newer job that got there first stays."""
    fields = {"status": "failed" if how == "failed" else "draft", "stage": "",
              "message": "Stopped. Nothing new was kept." if how == "canceled" else "",
              "error": error[:600] if error else
              ("Stopped after repeated interruptions. Press the button again to try once more." if how == "failed"
               else ""), "updated_at": time.time()}
    enc = db._encode("text_stories", fields)  # noqa: SLF001
    cols = ", ".join(f"{k} = ?" for k in enc)
    marks = ", ".join("?" for _ in WORKING)
    mine = " AND job_id = ?" if job_id else ""
    db.execute(f"UPDATE text_stories SET {cols} WHERE id = ? AND status IN ({marks}){mine}",
               [*enc.values(), story_id, *WORKING, *([job_id] if job_id else [])])


@on_stop("text_story_write")
def _write_stopped(job: dict, how: str) -> None:
    _settle(job["target_id"], how, job_id=job["id"])


@on_stop("text_story_render")
def _render_stopped(job: dict, how: str) -> None:
    _settle(job["target_id"], how, job_id=job["id"])


def _own_job(job: dict) -> dict | None:
    s = db.fetch("text_stories", job["target_id"])
    return s if s and s.get("job_id") == job["id"] else None


def _patch_working(story_id: str, job_id: str, **fields) -> dict | None:
    """Change a story only while this job is still its work (not stopped, not replaced): one write, so a Stop that
    lands at the same moment is never written over. None when the story moved on."""
    fields["updated_at"] = time.time()
    enc = db._encode("text_stories", fields)  # noqa: SLF001
    cols = ", ".join(f"{k} = ?" for k in enc)
    marks = ", ".join("?" for _ in WORKING)
    changed = db.execute(f"UPDATE text_stories SET {cols} WHERE id = ? AND job_id = ? AND status IN ({marks})",
                         [*enc.values(), story_id, job_id, *WORKING])
    return db.fetch("text_stories", story_id) if changed else None


def _plain(exc: BaseException) -> str:
    from . import chatstory, voice, writer

    if isinstance(exc, (voice.VoiceError, writer.WriterError, StoryError, chatstory.ChatError)):
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
    chat_fields: dict = {}
    try:
        if is_chat(story):
            from . import chatstory

            chat = story.get("chat") or {}
            current = {"script": story.get("script"), "title": story.get("name"),
                       "me": chat.get("me") or chatstory.resolve(story.get("script") or "", chat)["me"],
                       "contact": chat.get("contact")}
            got = writer.write_chat(ask.get("topic") or "", tone=ask.get("tone") or "drama",
                                    length=ask.get("length") or "standard", settings=db.get_settings(),
                                    workspace_id=story["workspace_id"], project_id=story["id"],
                                    current=current if ask.get("change") else None, change=ask.get("change") or "",
                                    cancel=lease.canceled, beat=lambda m: lease.progress(0.5, m), remember=False)
            script = _clean_chat_script(got["script"])
            title = ""
            if not ask.get("change"):
                chat = {**chat, "contact": got.get("contact") or "", "me": "Me"}
            else:
                # "Automatic" (or a chosen person who has left the chat) picks the second person to write when nobody
                # is Me: a revision that changes who writes first must not hand the phone to the other person
                before = chatstory.resolve(story.get("script") or "", chat)["me"]
                after = chatstory.resolve(script, chat)
                if before and before != after["me"] and before in after["people"]:
                    chat = {**chat, "me": before}
            chat_fields = {"chat": chatstory.with_voices(script, chat)}
            if not story.get("name") and got.get("title"):
                chat_fields["name"] = " ".join(str(got["title"]).split())[:MAX_NAME]
        else:
            got = writer.write_story(ask.get("topic") or "", tone=ask.get("tone") or "drama",
                                     length=ask.get("length") or "standard", settings=db.get_settings(),
                                     workspace_id=story["workspace_id"], project_id=story["id"],
                                     current={"title": story.get("title"), "script": story.get("script")}
                                     if ask.get("change") else None, change=ask.get("change") or "",
                                     cancel=lease.canceled, beat=lambda m: lease.progress(0.5, m), remember=False)
            script = _clean_script(got["script"])
            title = _clean_title(got["title"][:MAX_TITLE])
    except (Canceled, Cancelled):
        raise
    except Exception as exc:
        _patch_working(story["id"], job["id"], status="failed", stage="", message="", error=_plain(exc))
        raise
    noun = "chat" if is_chat(story) else "story"
    if lease.canceled() or _patch_working(
            story["id"], job["id"], title=title, script=script, status="draft", stage="", error="", **chat_fields,
            message=(f"ClipForge AI revised the {noun}." if ask.get("change") else
                     f"ClipForge AI wrote the {noun}. Read it through and change anything you like."),
            writer={"ask": ask, "notes": got["notes"], "model": got["model"], "local": got["local"],
                    "at": time.time()}) is None:
        raise Canceled()
    # only now that the story kept the writing: a story stopped or deleted meanwhile gets no Brain note
    writer.remember_story(story["workspace_id"], story["id"], got)
    if db.fetch("text_stories", story["id"]) is None:
        _forget(story["workspace_id"], story["id"])  # deleted while the note was written: delete() may have run first
    return {"words": words_of({**story, "script": script})}


@handler("text_story_render")
def render_job(job: dict, lease: Lease) -> dict:
    story = _own_job(job)
    if story is None:
        return {"skipped": True}
    what = story.get("stage") if story.get("stage") in ("preview", "export") else "preview"
    try:
        if is_chat(story):
            from . import chatstory

            narration = chatstory.make_voices(story, folder(story["id"]), lease)
        else:
            narration = make_narration(story, lease)
        # a Stop pressed as the voice finished has settled the story already: never write it back to working
        moved_on = lease.canceled() or None
        story = None if moved_on else _patch_working(  # type: ignore[assignment]
            job["target_id"], job["id"], narration=narration, status="rendering",
            message="Making the preview" if what == "preview" else "Making the video")
        if story is None:
            raise Canceled()
        made = render(story, what, lease)
    except (Canceled, Cancelled):
        raise
    except Exception as exc:
        log.exception("text story %s failed", job["target_id"])
        _patch_working(job["target_id"], job["id"], status="failed", stage="", message="", error=_plain(exc))
        raise
    d = folder(job["target_id"])
    if _patch_working(job["target_id"], job["id"], **{what: made}, status="ready", stage="", error="",
                      message="The preview is ready." if what == "preview" else
                      "Your video is ready to download.") is None:
        (d / made["file"]).unlink(missing_ok=True)  # stopped as it finished: nothing new is kept
        raise Canceled()
    for old in [*d.glob(f"{what}.mp4"), *d.glob(f"{what}-*.mp4")]:
        if old.name != made["file"]:
            old.unlink(missing_ok=True)  # the one it replaces
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
    rules = story.get("pronunciations") or []
    # the title and the script are pronounced apart: a rule never spans the two, and the captions know exactly how
    # many of the written words are the title's (a rule for several words makes one caption word of them)
    said_title, title_counts = voice_styles.pronounce(title_read, rules)
    said_script, script_counts = voice_styles.pronounce(written[len(title_read):].strip(), rules)
    said, counts = f"{said_title} {said_script}".strip(), title_counts + script_counts
    if lease:
        lease.progress(0.05, "Recording the voice")
    raw = d / f"voice-{key}.raw.wav"
    got = voice.speak(said, raw, voice=v.get("voice") or "auto", speed=float(v.get("speed") or 1.0),
                      cancel=lease.canceled if lease else None)
    out = d / f"voice-{key}.wav"
    try:
        if lease:
            lease.progress(0.25, "Timing the words")
        voice_styles.shape(raw, out, float(v.get("tone") or 0.0), cancel=lease.canceled if lease else None)
        raw.unlink(missing_ok=True)
        timed, how = voice.time_words(out, said, engine_words=got.get("words"), settings=db.get_settings(),
                                      cancel=lease.canceled if lease else None)
        if len(timed) != len(said.split()):
            timed, how = voice.estimate_words(out, said), "estimated"
    except BaseException:
        from . import local_engines

        raw.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
        local_engines.discard_made(got.get("original"))  # the voice engine's own copy goes with it
        raise
    words = voice_styles.words_back(timed, written, counts)
    for old_file in d.glob("voice-*.wav"):
        if old_file.name != out.name:
            old_file.unlink(missing_ok=True)
    _keep_original(got.get("original"), d)
    duration = float(got.get("duration_s") or 0.0) or (words[-1]["end"] if words else 0.0)
    return {"key": key, "file": out.name, "duration": round(duration, 3), "words": words,
            "title_words": sum(1 for c in title_counts if c > 0), "timing": how, "engine": got.get("engine") or "",
            "voice": got.get("voice") or "", "voice_id": got.get("voice_id") or "",
            "fallback": got.get("fallback") or "", "rule": got.get("rule") or ""}


def _keep_original(original: object, d: Path) -> None:
    """The local voice engine keeps its own copy of what it read (engines/made, with a note holding the words): it
    is moved into the story's folder as voice-original.*, replacing the last one, so it goes when the story does.
    Nothing outside engines/made is taken; this never fails the work."""
    from . import local_engines

    if not original:
        return
    src = Path(str(original))
    try:
        if not local_engines.made_here(src):
            return
        for old in d.glob("voice-original.*"):
            old.unlink(missing_ok=True)
        for item, dest in ((src, d / f"voice-original{src.suffix.lower()}"), (src.with_suffix(".json"),
                                                                            d / "voice-original.json")):
            if item.is_file():
                shutil.move(str(item), str(dest))
    except OSError as exc:
        log.warning("the voice engine's copy could not be kept with the story: %s", exc)


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


def _runs(plays: list[dict]) -> list[dict]:
    """The pieces as inputs: the plays of one looping clip one after another are one run (`times` plays, `length`
    their total), so a short clip looped over a long story is one input, not one per play."""
    out: list[dict] = []
    for p in plays:
        last = out[-1] if out else None
        same = last is not None and p.get("loop") and last.get("loop") and all(
            last.get(k) == p.get(k) for k in ("id", "asset_id", "builtin", "in_s", "out_s"))
        if same:
            last["times"] += 1
            last["length"] = round(last["length"] + p["length"], 3)
        else:
            out.append({**p, "times": 1, "play": p["length"]})
    return out


def _video_path(piece: dict) -> Path:
    asset = db.fetch("assets", piece["asset_id"])
    if not asset:
        raise StoryError("A background video was deleted. Choose another background.")
    path = Path(asset["path"])
    if not path.is_file():
        raise StoryError(f"The background video “{asset.get('filename') or path.name}” is missing from this "
                         "computer. Choose another background.")
    return path


def _source_args(piece: dict, size: tuple[int, int], loop_file: Path | None = None) -> list[str]:
    w, h = size
    if piece.get("builtin"):
        b = BUILTINS[piece["builtin"]]
        colours = ":".join(f"c{i}={c}" for i, c in enumerate(b["colors"]))
        return ["-f", "lavfi", "-i", f"gradients=s={w}x{h}:r={FPS}:{colours}:n={len(b['colors'])}:speed=0.012:"
                                     f"type={b['type']}:seed=7:d={piece['length']:.3f}"]
    if loop_file is not None:  # the clip's trimmed part, made once, played over and over
        return ["-stream_loop", "-1", "-i", str(loop_file)]
    return ["-ss", f"{float(piece['in_s']):.3f}", "-t", f"{piece['length']:.3f}", "-i", str(_video_path(piece))]


def _read(path: Path) -> str:
    """The `scale` option that reads a background video's colours with its own matrix (grade.input_matrix: FFmpeg
    would read untagged HD video as BT.601)."""
    return f"in_color_matrix={grade.input_matrix(grade.source_colour(path))}"


# every picture is put together in RGB and turned into BT.709 limited range once, at the end: the chat card and the
# captions keep their exact colours, and the file's BT.709 tags are true (FFmpeg's default conversion is BT.601,
# which made reds up to 10 codes off and the card's blue 6)
TO_VIDEO = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
BT709_TAGS = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]


def _loop_part(piece: dict, size: tuple[int, int], dest: Path, cancel=None) -> Path:
    """The looping clip's trimmed part at the frame size (cropped where the owner placed it), without sound: FFmpeg
    can loop a whole file but not a part of one, so the part is made once and looped. It is made BT.709 and tagged
    so, whatever the clip was."""
    w, h = size
    fx, fy = float(piece.get("focus_x", 0.5)), float(piece.get("focus_y", 0.5))
    src = _video_path(piece)
    ffmpeg_utils.run(["-ss", f"{float(piece['in_s']):.3f}", "-t", f"{piece['play']:.3f}", "-i",
                      str(src), "-an", "-vf",
                      f"scale={w}:{h}:force_original_aspect_ratio=increase:{_read(src)},crop={w}:{h}:"
                      f"(in_w-{w})*{fx:.3f}:(in_h-{h})*{fy:.3f},setsar=1,fps={FPS},format=gbrp,{TO_VIDEO}",
                      "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p", *BT709_TAGS,
                      str(dest)], cancel=cancel)
    return dest


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
    chat = is_chat(story)
    total = total_seconds(story, narration)
    plays = _runs(pieces(story.get("backgrounds") or [], total))
    if not plays:
        raise StoryError("Choose a background first, or let ClipForge pick one.")
    key = render_key(story, what)
    ass = d / f"{what}.ass"
    cards = d / f"{what}-cards"
    tmp = d / f"{what}-{key}.part.mp4"
    made_parts: list[Path] = []

    def tidy() -> None:  # what this render made on the way (also when it stops or fails)
        for f in (ass, *made_parts):
            f.unlink(missing_ok=True)
        shutil.rmtree(cards, ignore_errors=True)

    try:
        args: list[str] = []
        chains = []
        for i, p in enumerate(plays):
            part = None
            if p["times"] > 1 and not p.get("builtin"):
                part = d / f"{what}-loop{i}.mp4"
                made_parts.append(part)
                _loop_part(p, size, part, cancel=lease.canceled if lease else None)
            args += _source_args(p, size, part)
            fx, fy = float(p.get("focus_x", 0.5)), float(p.get("focus_y", 0.5))
            read = "" if p.get("builtin") else ":" + _read(part if part is not None else _video_path(p))
            chains.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase{read},"
                          f"crop={w}:{h}:(in_w-{w})*{fx:.3f}:(in_h-{h})*{fy:.3f},setsar=1,fps={FPS},format=gbrp,"
                          f"trim=duration={p['length']:.3f},setpts=PTS-STARTPTS[v{i}]")
        args += ["-i", str(voice_file)]
        joined = "".join(f"[v{i}]" for i in range(len(plays)))
        background = (f"{joined}concat=n={len(plays)}:v=1:a=0,tpad=stop_mode=clone:stop_duration={total:.3f},"
                      f"trim=duration={total:.3f},setpts=PTS-STARTPTS")
        if chat:
            from . import chatstory

            # the chat card's pictures, each shown for as long as it stands, over the background
            listing = chatstory.make_cards(story, narration, size, cards, lease)
            args += ["-f", "concat", "-safe", "0", "-i", str(listing)]
            x, y = chatstory.card_box(size)
            chains.append(f"{background}[bg]")
            chains.append(f"[{len(plays) + 1}:v]fps={FPS},format=rgba[cards]")
            chains.append(f"[bg][cards]overlay=x={x}:y={y}:eof_action=repeat:format=gbrp,{TO_VIDEO}[vout]")
        else:
            ass.write_text(story_ass(story, narration, w, h), encoding="utf-8")
            chains.append(f"{background},ass={ffmpeg_utils.filter_path(ass, d)}:"
                          f"fontsdir={ffmpeg_utils.filter_path(config.FONTS_DIR, d)},{TO_VIDEO}[vout]")
        chains.append(f"[{len(plays)}:a]aresample=48000,apad[aout]")
        if what == "preview":
            video = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p", *BT709_TAGS]
        else:
            video, _ = ffmpeg_utils.video_encoder_args(db.get_settings())
            video += ffmpeg_utils.delivery_args(FPS)
        out_args = [*args, "-filter_complex", ";".join(chains), "-map", "[vout]", "-map", "[aout]", "-t",
                    f"{total:.3f}", "-r", str(FPS), *video, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-movflags", "+faststart", str(tmp)]

        start = 0.45 if chat else 0.35

        def progress(frac: float) -> None:
            if lease:
                lease.progress(start + (0.98 - start) * frac,
                               "Making the preview" if what == "preview" else "Making the video")

        ffmpeg_utils.run(out_args, duration=total, progress=progress, cancel=lease.canceled if lease else None,
                         cwd=d)
        # named by what it was made from, so a stopped job never replaces the file the story still names
        final = d / f"{what}-{key}.mp4"
        tmp.replace(final)
    except BaseException:
        tmp.unlink(missing_ok=True)  # Stop or a failure: the partial video goes too
        raise
    finally:
        tidy()
    return {"key": key, "file": final.name, "duration": total, "width": w, "height": h,
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
    chat = None
    if is_chat(story):
        from . import chatstory

        c = {**chatstory.DEFAULT_CHAT, **(story.get("chat") or {})}
        got = chatstory.resolve(story.get("script") or "", c)
        chat = {**c, "people": {n: (c.get("people") or {}).get(n) or {} for n in got["people"]},
                "names": got["people"], "whose_phone": got["me"], "shown_contact": got["contact"],
                "auto_phone": chatstory.whose_phone(got["people"]),
                "group": got["group"], "messages": [{"who": m["who"], "text": m["text"], "side": m["side"],
                                                     "label": m["label"]} for m in got["messages"]]}
    return {
        "id": story["id"], "name": display_name(story), "own_name": story.get("name") or "",
        "kind": story.get("kind") or "narrated", "chat": chat,
        "title": story.get("title") or "", "script": story.get("script") or "", "words": words_of(story),
        "seconds": estimate_seconds(story), "voice": v, "pronunciations": story.get("pronunciations") or [],
        "captions": {**DEFAULT_CAPTIONS, **(story.get("captions") or {})}, "backgrounds": backgrounds,
        "status": story["status"], "stage": story.get("stage") or "", "message": story.get("message") or "",
        "error": story.get("error") or "", "working": working,
        "job": {"progress": float(job.get("progress") or 0.0), "message": job.get("message") or ""}
        if job and working else None,
        "narration": {"ready": fresh_voice, "voice": narr.get("voice") or "", "fallback": narr.get("fallback") or "",
                      "messages": narr.get("messages"),
                      "timing": narr.get("timing") or "", "rule": narr.get("rule") or "",
                      "duration": narr.get("duration")} if narr else {"ready": False},
        "made": made, "writer": {k: (story.get("writer") or {}).get(k) for k in ("notes", "model", "local")},
        "project_id": editor_project(story), "updated_at": story["updated_at"],
        "steps": {"script": words_of(story) > 0,
                  "voice": bool(chat and chat["people"]) if chat is not None else bool(v.get("voice")),
                  "background": bool(backgrounds),
                  "preview": made["preview"]["current"], "export": made["export"]["current"]},
    }


def file_for(story: dict, what: str) -> Path:
    if what not in ("preview", "export"):
        raise StoryError("Not found.", 404)
    if not _file_ok(story, what):
        raise StoryError("That video has not been made yet.", 404)
    return folder(story["id"]) / story[what]["file"]


def editor_project(story: dict) -> str:
    """The editor video made from the export the story has now ("" when there is none: never made, made from an
    earlier export, or deleted since), so "Open in the editor" never leads to an old or deleted video."""
    pid = str((story.get("export") or {}).get("project_id") or "")
    if not pid:
        return ""
    project = db.fetch("studio_projects", pid)
    return pid if project and project.get("workspace_id") == story["workspace_id"] else ""


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
    # its fingerprint stays after a new export or the story's deletion: a copy of it is never a background
    db.execute("INSERT OR IGNORE INTO text_story_exports (workspace_id, sha256, created_at) VALUES (?, ?, ?)",
               (story["workspace_id"], asset["sha256"], time.time()))
    project = video_flow.create(story["workspace_id"], user_id, name=name, asset_ids=[asset["id"]], brief={})
    # kept with the export it was made from: a new export replaces both, so the page offers the button again
    export = {**(story.get("export") or {}), "export_asset_id": asset["id"], "project_id": project["id"]}
    _patch(story["id"], project_id=project["id"], export=export)
    return project

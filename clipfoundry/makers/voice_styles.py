"""Voice styles, tone, pronunciations and favourite voices (the final-release prompt, section 8: "voice presets such as
energetic storyteller, casual commentary, dramatic suspense, fast meme narration; speed, tone where supported,
pronunciation; favorite voice per project or style").

The voices themselves are makers/voice.py's: the local voice engine's (Supertonic 3, OpenRAIL-M: made for this use),
this computer's own (macOS `say`, the Windows voices) and espeak-ng. Only voices ClipForge is allowed to use are
offered; no voice is cloned or downloaded from a website here.

A style is a speed and a tone (pitch, in semitones). The tone is changed by FFmpeg after the voice reads (the sound
is resampled and stretched back to the same length), so it works with every voice and the word times stay the same.
Pronunciations replace a word with how it should be said ("GIF" read as "jif"); the captions keep the word as
written (`words_back`).
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path

from .. import db
from ..pipeline import ffmpeg_utils

STYLES: dict[str, dict] = {
    "energetic": {"name": "Energetic storyteller", "about": "Upbeat and a little quick, for stories with a twist.",
                  "speed": 1.12, "tone": 1.0},
    "casual": {"name": "Casual commentary", "about": "Relaxed, like telling a friend what happened.",
               "speed": 1.0, "tone": 0.0},
    "dramatic": {"name": "Dramatic suspense", "about": "Slower and lower, for cliffhangers and creepy stories.",
                 "speed": 0.9, "tone": -2.0},
    "meme": {"name": "Fast meme narration", "about": "Fast and bright, the classic meme-video read.",
             "speed": 1.3, "tone": 2.0},
}
DEFAULT_STYLE = "casual"
TONE_RANGE = (-4.0, 4.0)     # semitones; further than this sounds like a cartoon
SPEED_RANGE = (0.7, 1.4)     # voice.SPEEDS
MAX_RULES = 40
MAX_RULE_CHARS = 60
SCOPES = re.compile(r"^(style:(?:energetic|casual|dramatic|meme)|project:[A-Za-z0-9_-]{1,64})$")


class VoiceStyleError(ValueError):
    pass


def styles() -> list[dict]:
    return [{"id": k, **v} for k, v in STYLES.items()]


def clean_voice(raw: object, base: dict | None = None) -> dict:
    """{"voice", "style", "speed", "tone"}: a style fills in speed and tone that were not given."""
    raw = raw if isinstance(raw, dict) else {}
    out = dict(base or {"voice": "auto", "style": DEFAULT_STYLE, **{k: STYLES[DEFAULT_STYLE][k] for k in ("speed",
                                                                                                          "tone")}})
    if "style" in raw:
        style = raw.get("style")
        if style not in STYLES:
            raise VoiceStyleError("Choose one of the voice styles.")
        if style != out.get("style"):
            out.update(style=style, speed=STYLES[style]["speed"], tone=STYLES[style]["tone"])
    if "voice" in raw:
        voice = raw.get("voice")
        if not isinstance(voice, str) or not voice or len(voice) > 200:
            raise VoiceStyleError("Choose a voice.")
        out["voice"] = voice
    for key, (lo, hi) in (("speed", SPEED_RANGE), ("tone", TONE_RANGE)):
        if key in raw:
            try:
                value = float(raw[key])
            except (TypeError, ValueError):
                raise VoiceStyleError(f"The {key} must be a number.") from None
            if not math.isfinite(value):
                raise VoiceStyleError(f"The {key} must be a number.")
            out[key] = round(min(hi, max(lo, value)), 2)
    return out


def clean_rules(raw: object) -> list[dict]:
    """Pronunciations: [{"word", "say"}], at most 40; a rule without both parts is dropped."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise VoiceStyleError("Pronunciations must be a list.")
    out, seen = [], set()
    for r in raw[:MAX_RULES]:
        if not isinstance(r, dict):
            continue
        word = " ".join(str(r.get("word") or "").split())[:MAX_RULE_CHARS]
        say = " ".join(str(r.get("say") or "").split())[:MAX_RULE_CHARS]
        if not word or not say or word.lower() in seen:
            continue
        seen.add(word.lower())
        out.append({"word": word, "say": say})
    return out


_EDGE = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)


def _core(token: str) -> tuple[str, str, str]:
    """A written word without the punctuation around it: (before, word, after)."""
    m = _EDGE.match(token)
    return (m.group(1), m.group(2), m.group(3)) if m else ("", token, "")


def pronounce(text: str, rules: list[dict]) -> tuple[str, list[int]]:
    """The words as the voice should read them, and for each written word how many spoken words stand for it (so
    `words_back` can give the captions the written words). A rule matches whole words, any case, and may cover
    several written words ("New York"); the longest rule wins. Punctuation around the words stays (the voice pauses
    at it)."""
    tokens = text.split()
    ordered = sorted(({"words": r["word"].lower().split(), "say": r["say"].split()} for r in rules if r["say"].split()),
                     key=lambda r: -len(r["words"]))
    spoken: list[str] = []
    counts: list[int] = []
    i = 0
    while i < len(tokens):
        for r in ordered:
            n = len(r["words"])
            if i + n <= len(tokens) and [_core(t)[1].lower() for t in tokens[i:i + n]] == r["words"]:
                parts = list(r["say"])
                parts[0] = _core(tokens[i])[0] + parts[0]
                parts[-1] = parts[-1] + _core(tokens[i + n - 1])[2]
                spoken.extend(parts)
                counts.extend([len(parts)] + [0] * (n - 1))
                i += n
                break
        else:
            spoken.append(tokens[i])
            counts.append(1)
            i += 1
    return " ".join(spoken), counts


def words_back(timed: list[dict], written: str, counts: list[int]) -> list[dict]:
    """The written words with the times of the spoken words that stand for them ([{"w", "start", "end"}])."""
    tokens = written.split()
    out: list[dict] = []
    k = 0
    for token, n in zip(tokens, counts):
        if n <= 0:
            if out:
                out[-1]["w"] = f"{out[-1]['w']} {token}"  # read together with the word before it
            continue
        part = timed[k:k + n]
        k += n
        if not part:
            break
        out.append({"w": token, "start": float(part[0]["start"]), "end": float(part[-1]["end"])})
    return out


def shape(src: Path, dst: Path, tone: float, cancel=None) -> None:
    """The voice `tone` semitones higher (or lower), the same length: resampled, then stretched back (FFmpeg)."""
    tone = min(TONE_RANGE[1], max(TONE_RANGE[0], float(tone)))
    if abs(tone) < 0.05:
        if Path(src) != Path(dst):
            Path(dst).write_bytes(Path(src).read_bytes())
        return
    f = 2 ** (tone / 12.0)
    rate = 48000
    chain = f"asetrate={round(rate * f)},aresample={rate},atempo={1 / f:.6f}"
    tmp = Path(dst).with_suffix(".tone.wav")
    ffmpeg_utils.run(["-i", str(src), "-af", chain, "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", str(tmp)],
                     cancel=cancel)
    tmp.replace(dst)


# ------------------------------------------------------------------ favourite voices
def favourites(workspace_id: str) -> dict:
    """{scope: {"voice", "speed", "tone", "style"}} for this workspace: "style:<id>" and "project:<id>"."""
    rows = db.select("voice_favorites", "workspace_id = ?", (workspace_id,))
    return {r["scope"]: {"voice": r["voice"], "speed": r["speed"], "tone": r["tone"], "style": r["style"]}
            for r in rows}


def set_favourite(workspace_id: str, scope: str, voice: dict | None) -> dict:
    if not isinstance(scope, str) or not SCOPES.match(scope):
        raise VoiceStyleError("A favourite voice is for a style or for one project.")
    if voice is None:
        db.execute("DELETE FROM voice_favorites WHERE workspace_id = ? AND scope = ?", (workspace_id, scope))
        return favourites(workspace_id)
    v = clean_voice(voice)
    db.execute("INSERT INTO voice_favorites (workspace_id, scope, voice, speed, tone, style, updated_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (workspace_id, scope) DO UPDATE SET voice = excluded.voice, "
               "speed = excluded.speed, tone = excluded.tone, style = excluded.style, updated_at = excluded.updated_at",
               (workspace_id, scope, v["voice"], v["speed"], v["tone"], v["style"], time.time()))
    return favourites(workspace_id)


def favourite_for(workspace_id: str, project_id: str = "", style: str = "") -> dict | None:
    """The favourite that applies: this project's, else this style's."""
    fav = favourites(workspace_id)
    return fav.get(f"project:{project_id}") if project_id and f"project:{project_id}" in fav else \
        fav.get(f"style:{style}") if style else None

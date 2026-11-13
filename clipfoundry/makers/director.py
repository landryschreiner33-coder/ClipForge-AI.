"""The director of an animated short (docs/clipforge/ANIMATED_SHORTS.md): how each scene is filmed and cut.

The shorts people watch to the end change what the eye sees every second or two, land every change on a word, and
never hold a picture still. A scene of a short is one picture and five seconds of voice, so the director makes shots
out of it: how the camera moves and how fast, where in the sentence it punches in (a cut to a closer framing of the
same picture, on a phrase start), how the scene arrives on the cut (a small pop, a fast zoom, a whip from the side),
what drifts through the air over it (dust, rain, snow, embers: read from what the scene shows) and which words the
captions lift in colour. `direct()` writes that down as a plain `direction` (camera.py and fx.py say what each key
does; motion.still_clip films it).

Everything follows from the scene itself (its words and their times, its place in the short, its picture idea, the
look and the editing style), so the same scene is always filmed the same way and a changed one is filmed again. No
model is asked and nothing is random.

Editing styles (`STYLES`): "gentle" eases slowly and never punches in; "lively" lands each cut and punches in once in
a long scene; "punchy" is the short-video cut: a snap at the start of every scene, a punch-in about every two seconds,
whips and fast zooms between scenes.
"""
from __future__ import annotations

import re

from . import fx

RECIPE = 1                     # part of every clip key (shorts.clip_key): a changed director films the scenes again
STYLES = {"gentle": "Gentle", "lively": "Lively", "punchy": "Punchy"}
DEFAULT = "punchy"
#         ease, strength, turn (degrees), seconds between punch-ins (0: none), most punch-ins, shake (pixels)
_STYLE = {"gentle": ("inout", 0.08, 0.0, 0.0, 0, 0.0),
          "lively": ("out", 0.11, 0.35, 3.0, 1, 0.0),
          "punchy": ("snap", 0.13, 0.6, 1.9, 3, 6.0)}
# how a scene arrives on its cut, scene after scene (the first scene of a short is its cover: it never arrives blurred)
_ENTRIES = {"gentle": ("none",),
            "lively": ("pop", "pop", "zoom", "pop"),
            "punchy": ("zoom", "pop", "whip_left", "pop", "zoom", "whip_right", "pop", "flash")}
_PUNCHES = (1.16, 1.12, 1.1)   # each punch-in comes this much closer than the framing before it
CARD_PUNCH = 1.07              # a designed card holds words: it is never cropped far
MIN_SHOT_S = 1.2               # no punch-in sooner than this after the cut or the punch-in before it
TAIL_S = 0.7                   # ...or later than this before the scene's words end
HOOK_BEAT_S = (0.7, 1.6)       # the first scene punches in early: the first seconds decide who stays
MAX_AIR = 2                    # kinds of air over one scene

# What drifts over a scene, read from what it shows and says (the first kinds that match, in this order).
_AIR = (
    ("snow", r"snow|blizzard|winter|frozen|arctic|icy|glacier"),
    ("rain", r"rain|storm|thunder|drizzle|downpour|monsoon"),
    ("embers", r"fire|flame|burn|lava|volcano|ember|torch|blaze|explosion|dragon|forge|furnace"),
    ("bubbles", r"underwater|ocean floor|deep sea|beneath the waves|bubble|submarine|scuba|aquarium|coral"),
    ("fireflies", r"firefl|glowing bug|fairy|fairies|enchanted|magical forest"),
    ("sparkle", r"star|galaxy|cosmos|treasure|gold|diamond|crystal|jewel|magic|sparkl|glitter|trophy"),
    ("fog", r"fog|mist|haunted|graveyard|ghost|swamp|smoke|eerie|creepy|abandoned|cemetery|shadowy"),
    ("rays", r"sunrise|sunset|sunlight|sunbeam|morning|dawn|window|cathedral|temple|forest|jungle|heaven|spotlight"),
    ("bokeh", r"city|street|night|neon|party|concert|festival|lights"),
    ("dust", r"desert|attic|ancient|library|museum|ruin|cave|barn|workshop|old |dust"),
)
_AIR = tuple((kind, re.compile(rf"\b(?:{words})", re.I)) for kind, words in _AIR)

# Words a caption lifts in colour: the ones a narrator leans on.
_POWER = frozenset("""never always every only secret secrets nobody nothing everything everyone impossible instantly
suddenly forever first last best worst biggest smallest fastest oldest deadliest strangest huge tiny giant massive
million millions billion billions thousand thousands hundred hundreds zero free real truth true false wrong right
mistake mistakes warning danger dangerous deadly dead alive kill killed die died survive survived love hate fear
money rich poor win won lose lost stop wait why how what actually literally exactly finally still again
shocking insane crazy weird strange amazing incredible unbelievable terrifying brilliant genius perfect""".split())
_STOP = frozenset("""a an the and or but so if of to in on at by for with from as is are was were be been it its this
that these those i you he she we they my your his her our their me him them us not no yes do does did has have had
will would can could should may might just very really then than there here when where who whom which while into
over under up down out about after before because""".split())
_NUMBER = re.compile(r"\d")
_BREAK = (".", "!", "?", ",", ";", ":", "…", "—", "–")
EM_GAP = 3                     # at least this many words between two lifted words
EM_SHARE = 0.22                # at most this share of a scene's words is lifted


def clean_style(value) -> str:
    return value if value in STYLES else DEFAULT


def _bare(word: str) -> str:
    return re.sub(r"[^\w']+", "", str(word or "")).lower()


def emphasis(words: list[dict]) -> list[int]:
    """Which of a scene's words (by index) the captions lift in colour: numbers, the words a narrator leans on, a
    word shouted in capitals or ending a question or an exclamation; a few per scene, never two in a row."""
    scored = []
    for k, w in enumerate(words):
        raw = str(w.get("w") or "").strip()
        bare = _bare(raw)
        if not bare or bare in _STOP:
            continue
        score = 0
        if _NUMBER.search(raw):
            score += 3
        if bare in _POWER:
            score += 2
        if len(bare) >= 3 and raw.strip(".,!?;:\"'()").isupper():
            score += 2
        if raw.endswith(("!", "?")):
            score += 1
        if len(bare) >= 8:
            score += 1
        if score >= 2:
            scored.append((score, k))
    room = max(1, int(len(words) * EM_SHARE + 0.5))
    chosen: list[int] = []
    for _score, k in sorted(scored, key=lambda s: (-s[0], s[1])):
        if len(chosen) >= room:
            break
        if all(abs(k - c) >= EM_GAP for c in chosen):
            chosen.append(k)
    return sorted(chosen)


def phrase_starts(words: list[dict]) -> list[float]:
    """The moments in a scene's voice where a new phrase starts: after a comma or a full stop, or after a breath."""
    out = []
    for k in range(1, len(words)):
        before, here = words[k - 1], words[k]
        try:
            gap = float(here["start"]) - float(before["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if str(before.get("w") or "").strip().endswith(_BREAK) or gap >= 0.18:
            out.append(float(here["start"]))
    return out


def _beats(words: list[dict], voiced_s: float, every: float, most: int, first: bool) -> list[float]:
    """When a scene punches in: about every `every` seconds, each on the phrase start nearest to that moment (or the
    nearest word when the sentence has no break there), never right after the cut or right before the words end."""
    if not every or most <= 0 or voiced_s < MIN_SHOT_S + TAIL_S + 0.4:
        return []
    marks = phrase_starts(words)
    starts = [float(w["start"]) for w in words if isinstance(w.get("start"), (int, float))]
    out: list[float] = []
    at = 0.0
    target = sum(HOOK_BEAT_S) / 2 if first else every
    while len(out) < most:
        want = at + target
        if want > voiced_s - TAIL_S:
            break
        lo, hi = max(at + MIN_SHOT_S if out or not first else HOOK_BEAT_S[0], want - 0.6), \
            min(voiced_s - TAIL_S, want + 0.6)
        near = [t for t in marks if lo <= t <= hi] or [t for t in starts if lo <= t <= hi]
        t = min(near, key=lambda x: abs(x - want)) if near else want
        if t < lo - 1e-6 or t > hi + 1e-6:
            break
        out.append(round(t - 0.03, 3))   # a frame before the word: the eye is there when the ear hears it
        at, target = t, every
    return out


def air_for(text: str, look_air: tuple[str, ...] = ()) -> list[str]:
    """The kinds of air over a scene: what its words and picture idea name, then the look's own, at most MAX_AIR."""
    found = [kind for kind, pattern in _AIR if pattern.search(text or "")]
    return list(fx.clean_kinds([*found, *look_air])[:MAX_AIR])


def direct(*, seq: int, narration: str, picture: str, words: list[dict], voiced_s: float, move: str, look,
           style: str, effects: bool = True, seed: int = 0, card: bool = False) -> dict:
    """The direction of one scene (camera.py and fx.py read it; shorts keeps it with the scene). `seq`: the scene's
    place when the short was made (0 opens the short); `words`: the voice's timed words; `voiced_s`: how long the
    voice speaks; `move`: the camera move chosen for the scene; `look`: its looks.Look; `card`: the picture is a
    designed card with words on it (filmed more quietly, so the words stay whole)."""
    style = clean_style(style)
    ease, strength, turn, every, most, shake = _STYLE[style]
    first = int(seq) == 0
    entries = _ENTRIES[style]
    entry = "none" if first else entries[(int(seq) - 1) % len(entries)]
    if card and entry in ("whip_left", "whip_right", "flash"):
        entry = "pop"
    if first and style != "gentle":
        ease, strength = "snap", min(0.16, strength + 0.03)   # the opening push
    times = _beats(words, float(voiced_s), every, most, first)
    beats = [{"t": t, "zoom": CARD_PUNCH if card else _PUNCHES[min(k, len(_PUNCHES) - 1)]}
             for k, t in enumerate(times[:1] if card else times)]
    spin = (seed * 2654435761 + int(seq) * 97) % 1000 / 1000.0          # 0-1, the scene's own
    side = 1 if int(seq) % 2 == 0 else -1
    out: dict = {
        "v": RECIPE, "style": style, "move": move, "strength": strength, "ease": ease,
        "drift": [round((spin - 0.5) * 0.8, 3), round(-0.25 * side, 3)] if not card else [0.0, 0.0],
        "rotate": 0.0 if card else round(turn * side, 2),
        "beats": beats,
        "entry": {"kind": entry, "frames": 5 if entry == "pop" else 6} if entry != "none" else {"kind": "none"},
        "shake": 0.0 if card else shake,
        "parallax": 0.0 if card else 0.03,
        "seed": int(seed) % 100000,
        "grade": dict(getattr(look, "grade", None) or {}),
        "fx": air_for(f"{picture} {narration}", tuple(getattr(look, "air", ()) or ())) if effects and not card
        else [],
    }
    if card:
        out["focus"] = [0.5, 0.5]
    return out


def cues(direction: dict | None) -> dict:
    """What the sound follows in a scene's direction: {"entry": the way it arrives, "beats": [seconds]}."""
    d = direction if isinstance(direction, dict) else {}
    entry = (d.get("entry") or {}).get("kind") if isinstance(d.get("entry"), dict) else None
    beats = [float(b["t"]) for b in d.get("beats") or []
             if isinstance(b, dict) and isinstance(b.get("t"), (int, float)) and float(b.get("zoom") or 1) > 1.02]
    return {"entry": entry or "none", "beats": beats}

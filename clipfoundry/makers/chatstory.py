"""Text-message stories (Landry, 2026-11-26: "like the ones on TikTok", "several minutes long up to 10"): a phone chat
that appears one bubble at a time on a dark chat card over background video (cooking, cutting, gameplay: anything with
steady motion), each message read aloud in its sender's voice. A Text Story is either this kind ("chat") or the
narrated kind (makers/textstory.py); both share the story's backgrounds, preview, export, Stop and the job line.

**The script** is plain text, one message a line, each line starting with who sends it:

    Sienna: Be honest.
    Sienna: Does it embarrass you that my friend's boyfriend makes seven times your salary?
    Me: Good morning to you too.

A line without a name is one more message from the last person who wrote ("Sienna:" alone on a line starts her
messages). A name is a short label before a colon (at most four words, starting with a letter), so "10:30 works?"
and links stay messages; a line starting with a backslash is always a message ("\\Note: bring cake"). Whose phone it
is ("me": the blue bubbles on the right) is chosen on the page; by default it is the person called Me (or I, You,
Myself), else the second person to write. With more than two people it is a group chat: the header shows the group's
name and each of the others' turns shows their name over their bubble.

**The card** is drawn here with Pillow from the bundled Inter font (SIL Open Font License) and this computer's colour
emoji font (Apple Color Emoji, Segoe UI Emoji or Noto Color Emoji; without one, emoji are left out of the picture,
never drawn as boxes): a header with a back arrow and an unread count, the contact's round picture with their first
letter, their name and a video-call button; then the bubbles, grey on the left and coloured on the right, with a tail
on the last bubble of each turn. Nothing of anyone's app is copied: the picture is drawn from shapes and the bundled
font, and ClipForge adds no watermark. When the next bubble does not fit, the card starts a new page (without the
header) with that bubble at the top. Each card picture is made once and FFmpeg shows it for as long as it stands
(an ffconcat list); a new bubble rises into place over a tenth of a second.

**Timing.** A bubble appears with a soft sound (a pop when a message comes in, a quick swoosh when one is sent; both
made here from tones and noise, pipeline/moves.py) and its voice starts a moment later; the next bubble comes after a
short pause, longer when the other person answers. Without reading aloud, each message stays as long as it takes to
read it. Each line's voice is recorded once and kept (lines/) while its words, voice, speed, tone and pronunciations
stay the same, so changing one message records only that message again. Every line is brought to the same loudness,
so the two people sound equally loud.

A story is at most ten minutes long (MAX_SECONDS); YouTube counts vertical videos up to three minutes as Shorts and
posts longer ones as ordinary videos.
"""
from __future__ import annotations

import concurrent.futures
import functools
import hashlib
import json
import logging
import math
import os
import re
import shutil
import sys
import unicodedata
import wave
from pathlib import Path

import numpy as np

from .. import config
from ..pipeline import ffmpeg_utils

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ limits
MAX_MESSAGES = 400
MAX_MESSAGE_CHARS = 320
MAX_WORDS = 1800              # about ten minutes of texts read aloud with the pauses between them
MAX_SCRIPT = 30000            # characters, names included
MAX_NAME = 32
MAX_PEOPLE = 8
MAX_SECONDS = 600.0           # ten minutes (Landry's longest)
MAX_BADGE = 999
ME_NAMES = ("me", "i", "myself", "you")

THEMES = {
    # the card, the header, the line under it, their bubbles, their words, my bubbles, my words, names and icons
    "dark": {"label": "Dark", "card": (0, 0, 0), "head": (28, 28, 30), "rule": (56, 56, 58), "them": (38, 38, 41),
             "them_text": (255, 255, 255), "me": (10, 132, 255), "me_text": (255, 255, 255),
             "name": (255, 255, 255), "accent": (10, 132, 255), "muted": (142, 142, 147)},
    "light": {"label": "Light", "card": (255, 255, 255), "head": (246, 246, 248), "rule": (216, 216, 220),
              "them": (233, 233, 235), "them_text": (0, 0, 0), "me": (10, 132, 255), "me_text": (255, 255, 255),
              "name": (0, 0, 0), "accent": (10, 132, 255), "muted": (128, 128, 133)},
    "green": {"label": "Dark, green bubbles", "card": (0, 0, 0), "head": (28, 28, 30), "rule": (56, 56, 58),
              "them": (38, 38, 41), "them_text": (255, 255, 255), "me": (48, 199, 89), "me_text": (255, 255, 255),
              "name": (255, 255, 255), "accent": (10, 132, 255), "muted": (142, 142, 147)},
}
PACES = {"quick": 0.6, "normal": 1.0, "slow": 1.6}
PACE_LABELS = {"quick": "Quick", "normal": "Normal", "slow": "Slow"}
DEFAULT_CHAT = {"contact": "", "me": "", "people": {}, "theme": "dark", "badge": 99, "sounds": True,
                "read_aloud": True, "pace": "normal"}

# ------------------------------------------------------------------ the card, in pixels of a 1080-wide frame
CARD_X, CARD_W = 147, 786     # the card's left edge and width (a 1080 x 1920 frame)
CARD_TOP = 380                # its top edge: clear of the phone apps' buttons at the top
CARD_MAX_H = 1000             # a new page starts before the card would reach 1380 (the captions and buttons below)
CARD_RADIUS = 38
HEAD_H = 214
AVATAR, AVATAR_TOP = 112, 30
NAME_SIZE = 31
TEXT_SIZE, LINE_H = 35, 44
PAD_X, PAD_Y = 26, 16
BUBBLE_RADIUS = 38
SIDE = 22                     # from the card's edge to a bubble
MAX_BUBBLE = 0.74             # a bubble's widest, as a share of the card
GAP_SAME, GAP_TURN = 7, 20    # between bubbles of one turn, and when the other person writes
TOP_PAD, BOTTOM_PAD = 22, 24
SENDER_SIZE, SENDER_H = 24, 32
TAIL_ROOM = 14                # the tail reaches this far out of the bubble
EMOJI_SCALE = 1.18            # an emoji's height, as a share of the letters' size
RISE = (0.45, 0.8)            # the new bubble's opacity in the two frames before it lands...
RISE_PX = (12, 5)             # ...and how far below its place it is

# ------------------------------------------------------------------ timing
FPS = 30
FIRST_S = 0.0                 # the first bubble is there from the first frame (the hook, also in the thumbnail)
LEAD_S = 0.1                  # a bubble shows (with its sound) this long before its voice starts
PAUSE_SAME_S, PAUSE_TURN_S = 0.22, 0.4
END_S = 1.2                   # the last bubble stays this long after its voice ends
READ_S = (0.5, 0.32, 1.1, 6.0)  # without voices: base + per word, at least, at most (seconds)
LINE_DB = -20.0               # every line's speech is brought to this loudness (RMS of its voiced part, dBFS)
PEAK = 0.89                   # and its peaks kept under this (-1 dBFS)
POP_DB, SWOOSH_DB = -17.0, -21.0
SR = 48000
RECIPE = 1                    # part of every render key: a changed recipe renders again


class ChatError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ the script
_LABEL = re.compile(r"^(?P<name>[^:\n]{1,40}?)\s*:\s*(?P<text>.*)$")


def _name_ok(name: str) -> bool:
    words = name.split()
    if not words or len(words) > 4 or len(name) > MAX_NAME:
        return False
    first = name[0]
    if not (first.isalpha() or _is_emoji_start(name, 0)):
        return False   # "10:30 works?" is a message
    return not re.search(r"https?$|www\.|[<>{}\[\]/\\@#]", name, re.I)


def clean_script(value: object) -> str:
    """The script as kept: lines tidied (spaces inside a line, no blank runs), the limits checked."""
    if not isinstance(value, str):
        raise ChatError("The chat must be text.")
    lines = [" ".join(line.split()) for line in value.replace("\r", "").split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    text = "\n".join(out).strip()
    if len(text) > MAX_SCRIPT:
        raise ChatError(f"The chat is too long for one video; keep it under {MAX_SCRIPT:,} characters.")
    messages = parse(text)
    if len(messages) > MAX_MESSAGES:
        raise ChatError(f"The chat has {len(messages)} messages; one video holds at most {MAX_MESSAGES}.")
    long = next((m for m in messages if len(m["text"]) > MAX_MESSAGE_CHARS), None)
    if long:
        raise ChatError(f"One message is longer than {MAX_MESSAGE_CHARS} characters (“{long['text'][:40]}…”). "
                        "Split it into two lines.")
    if words_in(messages) > MAX_WORDS:
        raise ChatError(f"The chat is too long for one video; keep it under {MAX_WORDS} words (about ten minutes).")
    if len(people_in(messages)) > MAX_PEOPLE:
        raise ChatError(f"A chat can have at most {MAX_PEOPLE} people.")
    return text


def parse(script: str) -> list[dict]:
    """[{"who", "text"}] in order: one message a line (see the module's notes)."""
    out: list[dict] = []
    who = ""
    for raw in (script or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("\\"):
            text = line[1:].strip()
        else:
            m = _LABEL.match(line)
            if m and _name_ok(m.group("name").strip()) and not m.group("text").startswith("//"):
                who = _canon(m.group("name").strip(), out)
                text = m.group("text").strip()
            else:
                text = line
        if text:
            out.append({"who": who or "Them", "text": text})
    return out


def write_line(who: str, text: str) -> str:
    """One message as a script line that reads back the same (parse): a message starting with // or \\ goes on a
    line of its own under its sender's name, after a \\."""
    if text.startswith(("//", "\\")):
        return f"{who}:\n\\{text}"
    return f"{who}: {text}"


def _canon(name: str, so_far: list[dict]) -> str:
    """A name as it was first written ("sienna" after "Sienna" is Sienna)."""
    low = name.casefold()
    return next((m["who"] for m in so_far if m["who"].casefold() == low), name)


def people_in(messages: list[dict]) -> list[str]:
    seen: list[str] = []
    for m in messages:
        if m["who"] not in seen:
            seen.append(m["who"])
    return seen


def words_in(messages: list[dict]) -> int:
    return sum(len(m["text"].split()) for m in messages)


def whose_phone(names: list[str], chosen: str = "") -> str:
    """The person whose phone it is: the one chosen when they are in the chat, else Me (I, You, Myself), else the
    second person to write; "" when one person writes alone."""
    if chosen and chosen in names:
        return chosen
    named = next((n for n in names if n.casefold() in ME_NAMES), "")
    if named:
        return named
    return names[1] if len(names) > 1 else ""


def resolve(script: str, chat: dict) -> dict:
    """Everything the card and the timing need: {"messages": [{"who", "text", "side", "label"}], "me", "people",
    "others", "group", "contact"}."""
    messages = parse(script)
    names = people_in(messages)
    me = whose_phone(names, str(chat.get("me") or ""))
    others = [n for n in names if n != me]
    group = len(others) > 1
    contact = " ".join(str(chat.get("contact") or "").split()) or (", ".join(others[:3]) if group else
                                                                  (others[0] if others else "Unknown"))
    out = []
    for i, m in enumerate(messages):
        side = "me" if m["who"] == me else "them"
        first = i == 0 or messages[i - 1]["who"] != m["who"]
        sender = m["who"] if group and side == "them" else ""
        out.append({**m, "side": side, "sender": sender, "label": sender if first else ""})
    return {"messages": out, "me": me, "people": names, "others": others, "group": group, "contact": contact}


# ------------------------------------------------------------------ the chat's choices
def clean_chat(raw: object, base: dict | None = None) -> dict:
    """The chat's choices: who the contact is, whose phone it is, each person's voice, the look and the sounds."""
    from . import voice_styles

    if not isinstance(raw, dict):
        raise ChatError("The chat's choices must be a set of choices.")
    out = {**DEFAULT_CHAT, **(base or {})}
    out["people"] = dict(out.get("people") or {})
    if "contact" in raw:
        out["contact"] = " ".join(str(raw["contact"] or "").split())[:40]
    if "me" in raw:
        out["me"] = " ".join(str(raw["me"] or "").split())[:MAX_NAME]
    if "theme" in raw:
        if raw["theme"] not in THEMES:
            raise ChatError("Choose one of the chat looks.")
        out["theme"] = raw["theme"]
    if "pace" in raw:
        if raw["pace"] not in PACES:
            raise ChatError("Choose quick, normal or slow.")
        out["pace"] = raw["pace"]
    if "badge" in raw:
        try:
            badge = int(raw["badge"] or 0)
        except (TypeError, ValueError):
            raise ChatError("The unread count must be a number.") from None
        out["badge"] = max(0, min(MAX_BADGE, badge))
    for key in ("sounds", "read_aloud"):
        if key in raw:
            out[key] = bool(raw[key])
    if "people" in raw:
        if not isinstance(raw["people"], dict) or len(raw["people"]) > MAX_PEOPLE * 2:
            raise ChatError("Each person's voice must be a set of choices.")
        for name, v in raw["people"].items():
            name = " ".join(str(name).split())[:MAX_NAME]
            if not name:
                continue
            if v is None:
                out["people"].pop(name, None)
                continue
            try:
                out["people"][name] = voice_styles.clean_voice(v, out["people"].get(name))
            except voice_styles.VoiceStyleError as exc:
                raise ChatError(f"{name}'s voice: {exc}") from exc
    return out


def with_voices(script: str, chat: dict, voices: list[dict] | None = None) -> dict:
    """The chat's choices with a voice for everyone in the script (people who left the script lose theirs). Whose
    phone it is gets the best voice; the others get other voices, of another kind first (a man's next to a woman's)
    so the two sides sound different; when this computer has fewer voices than people, a voice comes back a little
    higher or lower."""
    from . import voice, voice_styles

    names = people_in(parse(script))
    have = {n: v for n, v in (chat.get("people") or {}).items() if n in names}
    missing = [n for n in names if n not in have]
    if not missing:
        return {**chat, "people": have}
    if voices is None:
        try:
            voices = voice.voices()
        except Exception:  # noqa: BLE001 - a story still opens; "auto" reads
            log.exception("the voice list failed")
            voices = []
    me = whose_phone(names, str(chat.get("me") or ""))
    usable = [v for v in voices if v["id"] != "auto"]
    english = [v for v in usable if str(v.get("lang") or "").lower().startswith("en")] or usable
    best = None
    if english:
        default = voice.default_voice()
        best = next((v for v in english if v["id"] == default), english[0])
    used = [v["voice"] for v in have.values()]
    order = sorted(missing, key=lambda n: n != me)  # whose phone it is first
    for k, name in enumerate(order):
        pick, tone = "auto", 0.0
        if english:
            if name == me and best is not None and best["id"] not in used:
                choice = best
            else:
                taken = set(used)
                genders = {next((v.get("gender") for v in english if v["id"] == u), "") for u in used}
                fresh = [v for v in english if v["id"] not in taken and "@" not in v["id"]] or \
                        [v for v in english if v["id"] not in taken]
                other_kind = [v for v in fresh if v.get("gender") and v.get("gender") not in genders]
                same_engine = [v for v in other_kind if best is None or v["engine"] == best["engine"]]
                choice = (same_engine or other_kind or fresh or [None])[0]
                if choice is None:   # more people than voices: an earlier voice, a little higher or lower
                    choice = english[k % len(english)]
                    tone = (2.0, -2.0, 3.0, -3.0)[k % 4]
            pick = choice["id"]
        have[name] = voice_styles.clean_voice({"voice": pick, "tone": tone})
        used.append(pick)
    return {**chat, "people": {n: have[n] for n in names}}


# ------------------------------------------------------------------ text: letters, emoji and other scripts
_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2300, 0x23FF), (0x2B00, 0x2BFF), (0x1F1E6, 0x1F1FF),
                 (0x3030, 0x3030), (0x303D, 0x303D), (0x3297, 0x3299))
# what the bundled Inter files hold (scripts/subset of the Google Fonts Inter): anything else is drawn with a font of
# this computer that has it
_INTER = ((0x20, 0x24F), (0x370, 0x52F), (0x1E00, 0x1EFF), (0x2000, 0x206F), (0x20A0, 0x20C0), (0x2100, 0x21FF),
          (0x2212, 0x2212))


def _is_emoji_char(c: str) -> bool:
    o = ord(c)
    return any(a <= o <= b for a, b in _EMOJI_RANGES)


def _is_emoji_start(text: str, i: int) -> bool:
    c = text[i]
    nxt = text[i + 1] if i + 1 < len(text) else ""
    if _is_emoji_char(c):
        return True
    if nxt == "\ufe0f":
        return True        # ©️, ❤ written as text plus the emoji selector, 1️⃣
    return nxt == "\u20e3"


def runs(text: str) -> list[tuple[str, str]]:
    """The text cut into ("text" | "other" | "emoji", piece): an emoji with its joiners, skin tones and selectors is
    one piece; "other" is letters the bundled font does not have."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(text)
    while i < n:
        if _is_emoji_start(text, i):
            j = i + 1
            while j < n:
                c = text[j]
                o = ord(c)
                if c in ("\ufe0f", "\ufe0e", "\u20e3") or 0x1F3FB <= o <= 0x1F3FF or 0xE0020 <= o <= 0xE007F:
                    j += 1
                elif c == "\u200d" and j + 1 < n:
                    j += 2
                elif 0x1F1E6 <= ord(text[i]) <= 0x1F1FF and 0x1F1E6 <= o <= 0x1F1FF and j == i + 1:
                    j += 1     # a flag is two regional letters
                else:
                    break
            out.append(("emoji", text[i:j]))
            i = j
            continue
        c = text[i]
        o = ord(c)
        if c in ("\ufe0f", "\u200d"):
            i += 1
            continue
        kind = "text" if any(a <= o <= b for a, b in _INTER) or unicodedata.category(c).startswith("Z") else "other"
        if out and out[-1][0] == kind:
            out[-1] = (kind, out[-1][1] + c)
        else:
            out.append((kind, c))
        i += 1
    return out


def plain(text: str) -> str:
    """The words without emoji (for a voice, and for the names in a file)."""
    return " ".join("".join(piece for kind, piece in runs(text) if kind != "emoji").split())


_WIN_FONTS = (os.environ.get("WINDIR") or "C:/Windows").replace("\\", "/").rstrip("/") + "/Fonts/"
EMOJI_FONTS = ("/System/Library/Fonts/Apple Color Emoji.ttc", _WIN_FONTS + "seguiemj.ttf",
               "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", "/usr/share/fonts/noto/NotoColorEmoji.ttf",
               "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf")
# this computer's fonts for letters and symbols the bundled Inter lacks: each character is drawn with the first that
# has it (Chinese, Japanese, Korean, Thai, Hindi, Hebrew, Arabic, ★ ✓ ♪ ...)
OTHER_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Hiragino Sans GB.ttc", "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Apple Symbols.ttf",
    _WIN_FONTS + "arial.ttf", _WIN_FONTS + "segoeui.ttf", _WIN_FONTS + "msyh.ttc", _WIN_FONTS + "YuGothM.ttc",
    _WIN_FONTS + "malgun.ttf", _WIN_FONTS + "Nirmala.ttc", _WIN_FONTS + "Nirmala.ttf", _WIN_FONTS + "LeelawUI.ttf",
    _WIN_FONTS + "ebrima.ttf", _WIN_FONTS + "seguisym.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf")
EMOJI_SIZES = (160, 137, 136, 128, 109, 96, 72, 64, 48)   # colour emoji fonts are pictures at fixed sizes
_JOINERS = ("\ufe0f", "\ufe0e", "\u200d", "\u20e3")


def _truetype(path: str, size: float):
    from PIL import ImageFont

    try:
        return ImageFont.truetype(path, size)   # a size in between (a third of 35 for the preview)
    except TypeError:                           # Pillow before 10.1 takes whole sizes only
        return ImageFont.truetype(path, max(1, int(round(size))))


@functools.lru_cache(maxsize=1)
def _emoji_font():
    from PIL import ImageFont

    for path in [os.environ.get("CLIPFOUNDRY_EMOJI_FONT", ""), *EMOJI_FONTS]:
        if not path or not Path(path).is_file():
            continue
        for size in EMOJI_SIZES:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return None


@functools.lru_cache(maxsize=32)
def _font(name: str, size: float):
    return _truetype(str(config.FONTS_DIR / name), size)


@functools.lru_cache(maxsize=64)
def _font_at(path: str, size: float):
    try:
        return _truetype(path, size)
    except OSError:
        return None


@functools.lru_cache(maxsize=1)
def _other_paths() -> tuple[str, ...]:
    return tuple(p for p in OTHER_FONTS if Path(p).is_file() and _font_at(p, 40) is not None)


def _shape(font, ch: str) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("L", (100, 100), 0)
    ImageDraw.Draw(img).text((20, 75), ch, font=font, fill=255, anchor="ls")
    return img.tobytes()


@functools.lru_cache(maxsize=64)
def _missing_shape(path: str) -> bytes:
    return _shape(_font_at(path, 40), "\uffff")   # no font has this: what it draws is its "missing" box


@functools.lru_cache(maxsize=8192)
def _has_glyph(path: str, ch: str) -> bool:
    """Whether the font draws this character (not its "missing" box, and not nothing)."""
    font = _font_at(path, 40)
    if font is None:
        return False
    try:
        got = _shape(font, ch)
        return any(got) and got != _missing_shape(path)
    except (OSError, ValueError):
        return False


@functools.lru_cache(maxsize=4096)
def _path_for(ch: str) -> str:
    """The first of this computer's fonts that has the character ("" for none)."""
    return next((path for path in _other_paths() if _has_glyph(path, ch)), "")


def _in_inter(ch: str) -> bool:
    o = ord(ch)
    return any(a <= o <= b for a, b in _INTER) or unicodedata.category(ch).startswith("Z")


def _segments(piece: str, size: float, emoji: bool = False) -> list[tuple[object, str]]:
    """The piece cut by the font that draws it: [(font, letters)]. An emoji with no colour picture is drawn as a
    letter when a font has it (★ ✓ ♪) and left out when none has; letters no font has show as the first font's box."""
    inter = _font("Inter-Regular.ttf", size)
    out: list[tuple[object, str]] = []
    for ch in piece:
        o = ord(ch)
        if ch in _JOINERS or 0x1F3FB <= o <= 0x1F3FF or 0xE0020 <= o <= 0xE007F:
            continue
        if out and unicodedata.category(ch).startswith("M"):
            out[-1] = (out[-1][0], out[-1][1] + ch)   # a mark stays with its letter
            continue
        if _in_inter(ch):
            font = inter
        else:
            path = _path_for(ch)
            if path:
                font = _font_at(path, size)
            elif emoji:
                continue
            else:
                first = _other_paths()
                font = (_font_at(first[0], size) if first else None) or inter
        if out and out[-1][0] is font:
            out[-1] = (font, out[-1][1] + ch)
        else:
            out.append((font, ch))
    return out


def _letter_font(ch: str, size: float):
    """A font that has this letter (the round picture's first letter)."""
    if _in_inter(ch):
        return _font("Inter-Regular.ttf", size)
    path = _path_for(ch)
    return (_font_at(path, size) if path else None) or _font("Inter-Regular.ttf", size)


@functools.lru_cache(maxsize=1)
def _emoji_missing() -> bytes:
    font = _emoji_font()
    return _emoji_shape(font, "\uffff") if font is not None else b""


def _emoji_shape(font, piece: str) -> bytes:
    from PIL import Image, ImageDraw

    canvas = Image.new("RGBA", (font.size * 2, int(font.size * 1.4)), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((0, 0), piece, font=font, embedded_color=True)
    return canvas.tobytes()


@functools.lru_cache(maxsize=512)
def _emoji(piece: str, height: int):
    """The emoji as a colour picture `height` pixels tall (None when this computer has no colour emoji font)."""
    from PIL import Image, ImageDraw

    font = _emoji_font()
    if font is None or height < 2:
        return None
    try:
        if _emoji_shape(font, piece[0]) == _emoji_missing():
            return None   # the colour font does not have it (★ ✓ ♪): it is drawn as a letter instead
        right = int(font.getbbox(piece)[2])
        width = max(1, int(round(font.getlength(piece))))
        size = font.size
        canvas = Image.new("RGBA", (max(width, right), int(size * 1.3)), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((0, 0), piece, font=font, embedded_color=True)
        box = canvas.getbbox()
        if not box:
            return None
        # the emoji's square (its advance wide, the font's size tall) so emoji line up with each other
        pic = canvas.crop((0, max(0, box[1] - 2), max(width, box[2]), min(canvas.height, box[3] + 2)))
    except (OSError, ValueError):
        return None
    w = max(1, round(pic.width * height / pic.height))
    return pic.resize((w, height), Image.LANCZOS)


def _measure(text: str, size: float) -> float:
    font = _font("Inter-Regular.ttf", size)
    width = 0.0
    for kind, piece in runs(text):
        if kind == "text":
            width += font.getlength(piece)
            continue
        pic = _emoji(piece, round(size * EMOJI_SCALE)) if kind == "emoji" else None
        if pic is not None:
            width += pic.width + size * 0.08
        else:
            width += sum(f.getlength(part) for f, part in _segments(piece, size, kind == "emoji"))
    return width


def wrap(text: str, size: float, width: float) -> list[str]:
    """The message's lines at this letter size: whole words where they fit, a word longer than a line cut."""
    lines: list[str] = []
    line = ""
    for word in text.split(" "):
        if not word:
            continue
        trial = f"{line} {word}" if line else word
        if _measure(trial, size) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        if _measure(word, size) <= width:
            line = word
            continue
        piece = ""
        for kind, part in runs(word):
            for ch in ([part] if kind == "emoji" else list(part)):
                if piece and _measure(piece + ch, size) > width:
                    lines.append(piece)
                    piece = ""
                piece += ch
        line = piece
    if line:
        lines.append(line)
    return lines or [""]


def _draw_text(img, xy: tuple[float, float], text: str, size: float, fill) -> None:
    """One line at (x, baseline): letters, other scripts and colour emoji."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    x, base = xy
    font = _font("Inter-Regular.ttf", size)
    for kind, piece in runs(text):
        if kind == "text":
            draw.text((x, base), piece, font=font, fill=fill, anchor="ls")
            x += font.getlength(piece)
            continue
        pic = _emoji(piece, round(size * EMOJI_SCALE)) if kind == "emoji" else None
        if pic is not None:
            img.alpha_composite(pic, (int(round(x + size * 0.04)), int(round(base - pic.height * 0.86))))
            x += pic.width + size * 0.08
            continue
        for f, part in _segments(piece, size, kind == "emoji"):
            draw.text((x, base), part, font=f, fill=fill, anchor="ls")
            x += f.getlength(part)


# ------------------------------------------------------------------ drawing
def _bezier(p0, p1, p2, p3, n: int = 16) -> list[tuple[float, float]]:
    pts = []
    for k in range(n + 1):
        t = k / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


def _tail(w: float, h: float, side: str, s: float) -> list[tuple[float, float]]:
    """The bubble's tail at its bottom corner: a hook curving out and down (left for them, right for me), as a
    polygon in the bubble's own pixels (x from the bubble's left edge, y from its top)."""
    # offsets from the bottom-left corner, in pixels of a 1080-wide frame
    outer = _bezier((4, -24), (4, -6), (-1, -1), (-9, 1))
    inner = _bezier((-9, 1), (1, 2), (10, -1), (18, -6))
    pts = [(dx * s, h + dy * s) for dx, dy in [*outer, *inner[1:], (18, -24)]]
    if side == "me":
        pts = [(w - x, y) for x, y in pts]
    return pts


BUBBLE_TEXT_W = CARD_W * MAX_BUBBLE - 2 * PAD_X
# the most lines a bubble shows: it always fits a page without the header, its sender's name above it included
MAX_LINES = int((CARD_MAX_H - TOP_PAD - BOTTOM_PAD - SENDER_H - 2 * PAD_Y) // LINE_H)


def first_lines(label: bool) -> int:
    """The most lines the first bubble shows: it stays under the header, so the video opens on whose chat it is."""
    return int((CARD_MAX_H - HEAD_H - TOP_PAD - BOTTOM_PAD - (SENDER_H if label else 0) - 2 * PAD_Y) // LINE_H)


@functools.lru_cache(maxsize=4096)
def bubble_lines(text: str, most: int = MAX_LINES) -> tuple[tuple[str, ...], float]:
    """A message's lines in its bubble and the widest one's width, in pixels of a 1080-wide frame. Worked out once
    for every size, so the preview and the video break lines and start pages at the same messages. A message longer
    than its page holds (`most` lines) ends with "…" on the card (its voice still reads all of it)."""
    lines = wrap(text, TEXT_SIZE, BUBBLE_TEXT_W)
    if len(lines) > most:
        lines = lines[:most]
        last = lines[-1]
        while last and _measure(last + "…", TEXT_SIZE) > BUBBLE_TEXT_W:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return tuple(lines), max(_measure(line, TEXT_SIZE) for line in lines)


class Card:
    """The chat card's pictures for one frame size (scale `s` of a 1080-wide frame) and one look. Where the lines
    break and where each bubble goes are worked out at 1080 and scaled, so every size shows the same pages."""

    def __init__(self, scale: float, theme: str, contact: str, badge: int):
        self.s = scale
        self.theme = THEMES.get(theme, THEMES["dark"])
        self.contact = contact
        self.badge = badge
        self.w = int(round(CARD_W * scale))
        self.max_h = int(round(CARD_MAX_H * scale))
        self.text = TEXT_SIZE * scale
        self.line = LINE_H * scale
        self._bubbles: dict = {}
        self._corner = self._corner_mask(int(round(CARD_RADIUS * scale)))
        self._head = None

    # -- the parts
    @staticmethod
    def _corner_mask(r: int):
        """A rounded corner's alpha (top left), drawn four times larger and shrunk, so its edge is smooth."""
        from PIL import Image, ImageDraw

        r = max(1, r)
        big = Image.new("L", (r * 4, r * 4), 0)
        ImageDraw.Draw(big).pieslice([0, 0, r * 8, r * 8], 180, 270, fill=255)
        return big.resize((r, r), Image.LANCZOS)

    def bubble(self, text: str, side: str, tail: bool, most: int = MAX_LINES):
        """(picture, its width and height without the tail room): the bubble with its words."""
        from PIL import Image, ImageDraw

        key = (text, side, tail, most)
        if key in self._bubbles:
            return self._bubbles[key]
        s = self.s
        lines, width = bubble_lines(text, most)
        # the lines and the height come from 1080; the width also fits the words as drawn at this size (without
        # Pillow's raqm, letters are placed on whole pixels and a small size comes out a little wider)
        bw = int(math.ceil(max((width + 2 * PAD_X) * s,
                               max(_measure(line, self.text) for line in lines) + 2 * PAD_X * s)))
        bh = int(math.ceil((len(lines) * LINE_H + 2 * PAD_Y) * s))
        room = int(math.ceil(TAIL_ROOM * s))
        k = 4  # the shape is drawn four times larger and shrunk: smooth edges
        mask = Image.new("L", ((bw + 2 * room) * k, (bh + room) * k), 0)
        d = ImageDraw.Draw(mask)
        d.rounded_rectangle([room * k, 0, (room + bw) * k - 1, bh * k - 1], radius=int(BUBBLE_RADIUS * s * k),
                            fill=255)
        if tail:
            d.polygon([((room + x) * k, y * k) for x, y in _tail(bw, bh, side, s)], fill=255)
        mask = mask.resize((bw + 2 * room, bh + room), Image.LANCZOS)
        colour = self.theme["me" if side == "me" else "them"]
        pic = Image.new("RGBA", mask.size, (*colour, 0))
        pic.putalpha(mask)
        ink = self.theme["me_text" if side == "me" else "them_text"]
        base0 = PAD_Y * s + self.line * 0.5 + self.text * 0.36
        for n, line in enumerate(lines):
            _draw_text(pic, (room + PAD_X * s, base0 + n * self.line), line, self.text, ink)
        got = (pic, bw, bh, room)
        self._bubbles[key] = got
        return got

    def header(self):
        """The top of the card: back arrow and unread count, the round picture with the contact's first letter,
        their name, and the video-call button. Drawn three times larger and shrunk."""
        from PIL import Image, ImageDraw

        if self._head is not None:
            return self._head
        k = 3
        s = self.s * k
        t = self.theme
        w, h = int(round(CARD_W * s)), int(round(HEAD_H * s))
        img = Image.new("RGBA", (w, h), (*t["head"], 255))
        d = ImageDraw.Draw(img)
        d.rectangle([0, h - max(1, round(2 * self.s)) * k, w, h], fill=(*t["rule"], 255))
        cy = 96 * s
        # back arrow
        line = max(2, round(5.5 * s))
        d.line([(44 * s, cy - 17 * s), (28 * s, cy), (44 * s, cy + 17 * s)], fill=(*t["accent"], 255), width=line,
               joint="curve")
        for end in ((44 * s, cy - 17 * s), (28 * s, cy), (44 * s, cy + 17 * s)):
            d.ellipse([end[0] - line / 2, end[1] - line / 2, end[0] + line / 2, end[1] + line / 2],
                      fill=(*t["accent"], 255))
        if self.badge:
            bold = _font("Inter-SemiBold.ttf", max(6, round(27 * s)))
            label = str(self.badge)
            tw = bold.getlength(label)
            bx, bhh = 56 * s, 44 * s
            bwid = max(bhh, tw + 26 * s)
            d.rounded_rectangle([bx, cy - bhh / 2, bx + bwid, cy + bhh / 2], radius=bhh / 2, fill=(*t["accent"], 255))
            d.text((bx + bwid / 2, cy), label, font=bold, fill=(255, 255, 255, 255), anchor="mm")
        # video call button
        vx, vw, vh = w - 92 * s, 46 * s, 33 * s
        d.rounded_rectangle([vx, cy - vh / 2, vx + vw, cy + vh / 2], radius=6 * s, outline=(*t["accent"], 255),
                            width=max(2, round(4.5 * s)))
        d.polygon([(vx + vw + 4 * s, cy), (vx + vw + 22 * s, cy - 13 * s), (vx + vw + 22 * s, cy + 13 * s)],
                  outline=(*t["accent"], 255), width=max(2, round(4.5 * s)))
        # the round picture: a soft grey with the first letter
        a = AVATAR * s
        ax, ay = (w - a) / 2, AVATAR_TOP * s
        top, bottom = np.array((168, 168, 176)), np.array((116, 116, 124))
        grad = np.linspace(0, 1, int(a))[:, None, None] * (bottom - top) + top
        rgb = np.broadcast_to(grad, (int(a), int(a), 3)).astype(np.uint8)
        disc = Image.fromarray(np.dstack([rgb, np.full((int(a), int(a)), 255, np.uint8)]), "RGBA")
        circle = Image.new("L", disc.size, 0)
        ImageDraw.Draw(circle).ellipse([0, 0, disc.width - 1, disc.height - 1], fill=255)
        disc.putalpha(circle)
        first = next((ch for ch in plain(self.contact) if ch.isalnum()), "")
        if first:
            ImageDraw.Draw(disc).text((disc.width / 2, disc.height / 2 + 2 * s), first.upper(),
                                      font=_letter_font(first, max(6, round(56 * s))),
                                      fill=(255, 255, 255, 255), anchor="mm")
        img.alpha_composite(disc, (int(ax), int(ay)))
        # the name, and a small arrow after it
        size = max(6, round(NAME_SIZE * s))
        name = self.contact[:40]
        width = _measure(name, size)
        while width > w - 220 * s and len(name) > 3:
            name = name[:-2].rstrip() + "…"
            width = _measure(name, size)
        chev = 18 * s
        nx = (w - width - chev) / 2
        base = (AVATAR_TOP + AVATAR + 44) * s
        _draw_text(img, (nx, base), name, size, (*t["name"], 255))
        cx = nx + width + 10 * s
        d.line([(cx, base - 21 * s), (cx + 7 * s, base - 14 * s), (cx, base - 7 * s)], fill=(*t["muted"], 255),
               width=max(1, round(2.5 * s)))
        self._head = img.resize((self.w, int(round(HEAD_H * self.s))), Image.LANCZOS)
        return self._head

    # -- the pages
    def layout(self, messages: list[dict]) -> list[dict]:
        """Where each bubble goes: [{"page", "top", "x", "w", "h", "room", "label_y", "label"}], a new page (without
        the header) when the next bubble would not fit. Worked out in pixels of a 1080-wide frame, then scaled."""
        s = self.s
        out: list[dict] = []
        page, y = 0, float(HEAD_H + TOP_PAD)
        first_on_page = True
        for i, m in enumerate(messages):
            most = first_lines(bool(m.get("label") or m.get("sender"))) if i == 0 else MAX_LINES
            lines, _ = bubble_lines(m["text"], most)
            bh = len(lines) * LINE_H + 2 * PAD_Y
            prev = messages[i - 1] if i else None
            same = prev is not None and prev["who"] == m["who"]
            for attempt in range(2):
                gap = 0.0 if first_on_page else float(GAP_SAME if same else GAP_TURN)
                label = m.get("label") or (m.get("sender") if first_on_page else "") or ""
                label_h = float(SENDER_H) if label else 0.0
                bottom = y + gap + label_h + bh + BOTTOM_PAD
                # first on its page, a bubble always fits (bubble_lines keeps it to `most` lines)
                if bottom <= CARD_MAX_H or first_on_page or attempt:
                    break
                page, y, first_on_page = page + 1, float(TOP_PAD), True
            top = y + gap + label_h
            pic, bw, bh_px, room = self.bubble(m["text"], m["side"], False, most)
            x = SIDE * s if m["side"] == "them" else self.w - SIDE * s - bw
            out.append({"page": page, "top": top * s, "x": x, "w": bw, "h": bh_px, "room": room,
                        "label_y": (y + gap) * s if label_h else None, "label": label, "most": most})
            y = top + bh
            first_on_page = False
        return out

    def state(self, messages: list[dict], places: list[dict], upto: int, rise: int = -1):
        """The card showing the page of message `upto`, from its first bubble to `upto` (the picture is the card's
        widest and tallest, transparent below the card). `rise` 0 or 1: the new bubble on its way in."""
        from PIL import Image

        s, t = self.s, self.theme
        img = Image.new("RGBA", (self.w, self.max_h), (0, 0, 0, 0))
        if upto < 0:
            h = int(round((HEAD_H + TOP_PAD + BOTTOM_PAD) * s))
            page = 0
            shown: list[int] = []
        else:
            page = places[upto]["page"]
            shown = [i for i in range(upto + 1) if places[i]["page"] == page]
            h = int(math.ceil(places[upto]["top"] + places[upto]["h"] + BOTTOM_PAD * s))
        h = min(self.max_h, h)
        body = Image.new("RGBA", (self.w, h), (*t["card"], 255))
        if page == 0:
            body.alpha_composite(self.header(), (0, 0))
        for i in shown:
            p = places[i]
            m = messages[i]
            nxt = i + 1 if i + 1 in shown else None
            tail = nxt is None or messages[nxt]["who"] != m["who"]
            pic, bw, bh, room = self.bubble(m["text"], m["side"], tail, p.get("most", MAX_LINES))
            dy, alpha = 0.0, 1.0
            if i == upto and rise in (0, 1):
                dy, alpha = RISE_PX[rise] * s, RISE[rise]
            if alpha < 1.0:
                pic = pic.copy()
                pic.putalpha(pic.getchannel("A").point(lambda a, f=alpha: int(a * f)))
            if p["label"] and p["label_y"] is not None:
                _draw_text(body, ((SIDE + 14) * s, p["label_y"] + SENDER_H * s * 0.72), p["label"], SENDER_SIZE * s,
                           (*t["muted"], 255))
            body.alpha_composite(pic, (int(round(p["x"] - room)), int(round(p["top"] + dy))))
        # the rounded corners
        alpha = body.getchannel("A")
        r = self._corner.width
        for corner, box in ((self._corner, (0, 0)),
                            (self._corner.transpose(Image.FLIP_LEFT_RIGHT), (self.w - r, 0)),
                            (self._corner.transpose(Image.FLIP_TOP_BOTTOM), (0, h - r)),
                            (self._corner.transpose(Image.ROTATE_180), (self.w - r, h - r))):
            alpha.paste(corner, box)
        body.putalpha(alpha)
        img.paste(body, (0, 0))
        return img


# ------------------------------------------------------------------ the voices and the timing
def line_key(said: str, v: dict) -> str:
    return hashlib.sha256(json.dumps(["line", said, v.get("voice"), v.get("speed"), v.get("tone")],
                                     sort_keys=True).encode()).hexdigest()[:20]


def said_lines(resolved: dict, chat: dict, rules: list[dict]) -> list[dict]:
    """What each message's voice says ({"said", "voice"}): emoji left out, pronunciations used."""
    from . import voice_styles

    out = []
    people = chat.get("people") or {}
    for m in resolved["messages"]:
        said = voice_styles.pronounce(plain(m["text"]), rules)[0] if rules else plain(m["text"])
        out.append({"said": said, "voice": people.get(m["who"]) or voice_styles.clean_voice({})})
    return out


def narration_key(script: str, chat: dict, rules: list[dict]) -> str:
    resolved = resolve(script, chat)
    lines = said_lines(resolved, chat, rules)
    # the texts as shown too: an emoji changed is a changed bubble (and, unread, a changed reading time)
    return hashlib.sha256(json.dumps(
        ["chat-narration", RECIPE, [m["who"] for m in resolved["messages"]], [m["side"] for m in resolved["messages"]],
         [m["text"] for m in resolved["messages"]],
         [line_key(x["said"], x["voice"]) for x in lines], bool(chat.get("read_aloud", True)),
         bool(chat.get("sounds", True)), chat.get("pace") or "normal"], sort_keys=True).encode()).hexdigest()[:16]


def reading_seconds(text: str) -> float:
    base, per_word, lo, hi = READ_S
    return round(min(hi, max(lo, base + per_word * len(text.split()))), 3)


def estimate(script: str, chat: dict) -> float:
    """About how long the video runs (before the voices are recorded): 175 words a minute at each person's speed."""
    resolved = resolve(script, chat)
    people = chat.get("people") or {}
    pace = PACES.get(chat.get("pace") or "normal", 1.0)
    t = FIRST_S
    msgs = resolved["messages"]
    for i, m in enumerate(msgs):
        if chat.get("read_aloud", True):
            speed = float((people.get(m["who"]) or {}).get("speed") or 1.0)
            words = max(1, len(plain(m["text"]).split()))
            d = words / (175.0 * speed) * 60.0 + 0.25
        else:
            d = reading_seconds(m["text"])
        t += LEAD_S + d
        if i + 1 < len(msgs):
            t += (PAUSE_SAME_S if msgs[i + 1]["who"] == m["who"] else PAUSE_TURN_S) * pace
    return round(t + END_S, 1) if msgs else 0.0


def timeline(messages: list[dict], durations: list[float], pace: str = "normal") -> tuple[list[dict], float]:
    """([{"show", "at", "end"}] per message, the video's length): when each bubble appears, when its voice starts and
    when it ends."""
    p = PACES.get(pace, 1.0)
    out = []
    t = FIRST_S
    for i, (m, d) in enumerate(zip(messages, durations)):
        show = t
        at = show + LEAD_S
        end = at + d
        out.append({"show": round(show, 3), "at": round(at, 3), "end": round(end, 3)})
        if i + 1 < len(messages):
            t = end + (PAUSE_SAME_S if messages[i + 1]["who"] == m["who"] else PAUSE_TURN_S) * p
    total = (out[-1]["end"] if out else FIRST_S) + END_S
    return out, round(total, 3)


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        channels = w.getnchannels()
        rate = w.getframerate()
    x = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    if rate != SR:   # every voice file is 48 kHz (voice.speak); this is a guard only
        n = int(round(len(x) * SR / rate))
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x) if len(x) else x
    return x


def level(x: np.ndarray) -> np.ndarray:
    """The line brought to LINE_DB (the loudness of its voiced 10 ms frames), its peaks under PEAK."""
    if not len(x):
        return x
    frame = SR // 100
    n = len(x) // frame
    if n:
        rms = np.sqrt((x[: n * frame].reshape(n, frame) ** 2).mean(axis=1))
        voiced = rms[rms > max(1e-4, rms.max() * 0.1)]
        loud = float(np.sqrt((voiced ** 2).mean())) if len(voiced) else 0.0
    else:
        loud = float(np.sqrt((x ** 2).mean()))
    if loud < 1e-5:
        return x
    gain = min(8.0, max(0.125, 10 ** (LINE_DB / 20) / loud))
    peak = float(np.abs(x).max()) * gain
    if peak > PEAK:
        gain *= PEAK / peak
    return x * gain


def mix(lines: list[np.ndarray | None], times: list[dict], sides: list[str], total: float, sounds: bool) -> np.ndarray:
    """The whole sound: each line at its time and, with sounds on, a pop as their message comes in and a swoosh as
    mine is sent. Stereo, float, 48 kHz."""
    from ..pipeline import moves

    track = np.zeros((int(math.ceil(total * SR)) + 1, 2))

    def put(sound: np.ndarray, at: float) -> None:
        k = int(round(at * SR))
        a, b = max(0, k), min(len(track), k + len(sound))
        if b > a:
            track[a:b] += sound[a - k:b - k]

    for i, (x, t) in enumerate(zip(lines, times)):
        if sounds:
            if sides[i] == "me":
                put(moves.whoosh(i, length=0.26, land=0.35) * 10 ** (SWOOSH_DB / 20), max(0.0, t["show"] - 0.05))
            else:
                put(moves.pop(i) * 10 ** (POP_DB / 20), t["show"])
        if x is not None and len(x):
            put(np.stack([x, x], axis=1), t["at"])
    peak = float(np.abs(track).max()) if len(track) else 0.0
    if peak > 0.98:
        track *= 0.98 / peak
    return track


def write_wav(track: np.ndarray, path: Path) -> Path:
    from ..pipeline import moves

    return moves.write_wav(track, path)


def make_voices(story: dict, folder: Path, lease=None) -> dict:
    """Each message's voice (recorded once, see the module's notes), the timing and the whole sound: the story's
    "narration" for a chat ({"key", "file", "duration", "times", "voices", "fallback", "rule", "timing": "chat"})."""
    from . import local_engines, voice, voice_styles

    script, chat = story.get("script") or "", story.get("chat") or {}
    rules = story.get("pronunciations") or []
    key = narration_key(script, chat, rules)
    old = story.get("narration") or {}
    if old.get("key") == key and (folder / str(old.get("file") or "-")).is_file():
        return old
    resolved = resolve(script, chat)
    msgs = resolved["messages"]
    if not msgs:
        raise ChatError("Write or paste the chat first.")
    lines_dir = folder / "lines"
    lines_dir.mkdir(parents=True, exist_ok=True)
    said = said_lines(resolved, chat, rules)
    aloud = bool(chat.get("read_aloud", True))
    sounds: list[np.ndarray | None] = []
    durations: list[float] = []
    notes: list[str] = []
    licences: dict[str, str] = {}   # whose voice: what its licence asks of what it makes
    keep: set[str] = set()
    cancel = lease.canceled if lease else None
    for i, (m, x) in enumerate(zip(msgs, said)):
        if lease:
            lease.progress(0.03 + 0.3 * i / max(1, len(msgs)),
                           f"Recording the voices ({i + 1} of {len(msgs)})" if aloud else "Timing the messages")
        # a message of emoji or dots alone ("...", "??", "😭") is not read: it stays up as long as it takes to see
        if not aloud or not any(ch.isalnum() for ch in voice._speakable(x["said"])):  # noqa: SLF001
            sounds.append(None)
            durations.append(reading_seconds(m["text"]))
            continue
        v = x["voice"]
        lk = line_key(x["said"], v)
        path = lines_dir / f"{lk}.wav"
        about = lines_dir / f"{lk}.json"   # the line's voice and what its licence asks
        once = False
        if path.is_file():
            keep.add(lk)
            info = _read_about(about)
        else:
            raw, made = lines_dir / f"{lk}.raw.wav", lines_dir / f"{lk}.new.wav"
            try:
                got = voice.speak(x["said"], raw, voice=v.get("voice") or "auto", speed=float(v.get("speed") or 1.0),
                                  cancel=cancel)
                local_engines.discard_made(got.get("original"))   # the line is kept here, not in engines/made
                voice_styles.shape(raw, made, float(v.get("tone") or 0.0), cancel=cancel)
            except BaseException:
                raw.unlink(missing_ok=True)
                made.unlink(missing_ok=True)
                raise
            raw.unlink(missing_ok=True)
            info = {"voice_id": str(got.get("voice_id") or ""), "rule": str(got.get("rule") or ""),
                    "fallback": str(got.get("fallback") or "")}
            if info["fallback"]:
                # read by another voice this time (the chosen one failed): used for this mix only, so the next
                # recording asks for the chosen voice again
                path, once = lines_dir / f"{lk}.once.wav", True
            else:
                about.write_text(json.dumps(info), encoding="utf-8")
                keep.add(lk)
            made.replace(path)
        if info.get("fallback"):
            note = f"{plain(m['who']) or m['who']}: {info['fallback']}"
            if note not in notes:
                notes.append(note)
        if info.get("rule"):
            licences.setdefault(m["who"], str(info["rule"]))
        x_arr = level(_read_wav(path))
        if once:
            path.unlink(missing_ok=True)
        sounds.append(x_arr)
        durations.append(round(len(x_arr) / SR, 3))
    times, total = timeline(msgs, durations, chat.get("pace") or "normal")
    if total > MAX_SECONDS + END_S:
        raise ChatError(f"The chat runs {int(total // 60)}:{int(total % 60):02d} read aloud, longer than ten "
                        "minutes. Take some messages out, pick a quicker pace or faster voices.")
    if lease:
        lease.progress(0.34, "Mixing the voices")
    track = mix(sounds, times, [m["side"] for m in msgs], total, bool(chat.get("sounds", True)))
    out = folder / f"voice-{key}.wav"
    write_wav(track, out)
    for f in folder.glob("voice-*.wav"):
        if f.name != out.name:
            f.unlink(missing_ok=True)
    if aloud:   # (read without voices, the recorded lines stay for when the voices are back on)
        for f in lines_dir.iterdir():
            if f.name.split(".")[0] not in keep:
                f.unlink(missing_ok=True)   # a message that changed or left: its old voice goes
    return {"key": key, "file": out.name, "duration": round(total - END_S, 3), "total": total, "times": times,
            "timing": "chat", "voices": {n: (chat.get("people") or {}).get(n, {}).get("voice", "auto")
                                         for n in resolved["people"]},
            "fallback": " ".join(notes)[:600], "rule": _licence_text(licences), "messages": len(msgs)}


def _read_about(path: Path) -> dict:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _licence_text(licences: dict[str, str]) -> str:
    """What the voices' licences ask: one rule as it is; different rules each with whose voices they are for."""
    by_rule: dict[str, list[str]] = {}
    for who, rule in licences.items():
        by_rule.setdefault(" ".join(rule.split()), []).append(plain(who) or who)
    if len(by_rule) <= 1:
        return next(iter(by_rule), "")[:600]
    return " ".join(f"{', '.join(names)}: {rule}" for rule, names in by_rule.items())[:600]


# ------------------------------------------------------------------ the card's pictures for FFmpeg
def look_key(chat: dict, contact: str) -> list:
    return [chat.get("theme") or "dark", contact, int(chat.get("badge") or 0)]


def make_cards(story: dict, narration: dict, size: tuple[int, int], dest: Path, lease=None) -> Path:
    """The card's pictures and the ffconcat list that shows each for as long as it stands; returns the list."""
    script, chat = story.get("script") or "", story.get("chat") or {}
    resolved = resolve(script, chat)
    msgs = resolved["messages"]
    times = narration.get("times") or []
    if len(times) != len(msgs):
        raise ChatError("The voices are out of date. Press Preview again.")
    total = float(narration.get("total") or 0.0)
    scale = size[0] / 1080
    card = Card(scale, chat.get("theme") or "dark", resolved["contact"], int(chat.get("badge") or 0))
    places = card.layout(msgs)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    plan: list[tuple[str, int, int, int]] = []   # (file, upto, rise, from which frame)

    def on_frame(t: float) -> int:
        return int(round(t * FPS))

    first_show = on_frame(times[0]["show"]) if times else on_frame(total)
    if first_show > 0:
        plan.append(("c-empty.png", -1, -1, 0))   # the header alone until the first bubble
    for i, t in enumerate(times):
        show = on_frame(t["show"])
        if i or first_show > 0:   # the first bubble is simply there at the start: it rises in otherwise
            plan.append((f"c{i:04d}-0.png", i, 0, show))
            plan.append((f"c{i:04d}-1.png", i, 1, show + 1))
            plan.append((f"c{i:04d}.png", i, -1, show + 2))
        else:
            plan.append((f"c{i:04d}.png", i, -1, show))
    cancel = lease.canceled if lease else None

    # the pictures are composed here, in order (the fonts are not shared between threads), and saved on a few
    # threads (compressing a PNG lets go of Python)
    from ..pipeline.common import Cancelled

    workers = max(1, min(4, (os.cpu_count() or 2) - 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        waiting: list[concurrent.futures.Future] = []
        for n, (name, upto, rise, _) in enumerate(plan):
            if cancel and cancel():
                for g in waiting:
                    g.cancel()
                raise Cancelled("Stopped.")
            pic = card.state(msgs, places, upto, rise)
            waiting.append(pool.submit(pic.save, dest / name, compress_level=1))
            if len(waiting) >= workers * 3:
                waiting.pop(0).result()
            if lease and n % 20 == 0:
                lease.progress(0.36 + 0.08 * n / max(1, len(plan)), "Drawing the chat")
        for g in waiting:
            g.result()
    # each picture's start in whole microseconds (what the list reader adds up), on its frame
    exact = _concat_takes_options()
    option = [f"option framerate {FPS}"] if exact else []
    lines = ["ffconcat version 1.0"]
    for n, (name, _, _, start) in enumerate(plan):
        a = round(start * 1_000_000 / FPS)
        z = round(plan[n + 1][3] * 1_000_000 / FPS) if n + 1 < len(plan) else round(total * 1_000_000)
        lines += [f"file '{name}'", *option, f"duration {max(1, z - a) / 1_000_000:.6f}"]
    # the last picture once more: the concat reader drops its duration otherwise
    lines += [f"file '{plan[-1][0]}'", *option]
    listing = dest / "cards.ffconcat"
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listing


@functools.lru_cache(maxsize=4)
def _concat_options_work(exe: str) -> bool:
    import subprocess
    import tempfile

    from PIL import Image

    with tempfile.TemporaryDirectory(prefix="clipforge-concat-") as d:
        Image.new("RGBA", (2, 2)).save(Path(d) / "a.png")
        (Path(d) / "a.ffconcat").write_text(f"ffconcat version 1.0\nfile 'a.png'\noption framerate {FPS}\n"
                                            "duration 0.1\n", encoding="utf-8")
        try:
            got = ffmpeg_utils.run_process([exe, "-v", "error", "-nostdin", "-f", "concat", "-safe", "0", "-i",
                                            str(Path(d) / "a.ffconcat"), "-frames:v", "1", "-f", "null", "-"],
                                           timeout=30)
        except (OSError, subprocess.SubprocessError):
            return False
        return got.returncode == 0


def _concat_takes_options() -> bool:
    """Whether this FFmpeg's list reader takes "option" lines (FFmpeg 5 and later). Each card picture then starts on
    its own 1/30 s frame; without, the picture reader's 1/25 s steps can swallow one of a bubble's rise frames."""
    try:
        return _concat_options_work(ffmpeg_utils.ffmpeg_bin())
    except Exception:   # noqa: BLE001 - no FFmpeg yet: the render says so itself
        return False


def card_box(size: tuple[int, int]) -> tuple[int, int]:
    """Where the card's pictures go in the frame (x, y)."""
    return int(round(CARD_X * size[0] / 1080)), int(round(CARD_TOP * size[1] / 1920))


def platform_emoji_note() -> str:
    """What the page says when this computer has no colour emoji font ("" when it has one)."""
    if _emoji_font() is not None:
        return ""
    where = {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, "this computer")
    return f"No colour emoji font was found on {where}, so emoji are left out of the chat's pictures."

"""The voice of an animated short: a scene's words read aloud, and when each word is said
(docs/clipforge/ANIMATED_SHORTS.md).

Voices, best first: the local voice engine when it is set up (Settings → Pictures, video, voice), then this
computer's own: macOS `say`, the Windows voices (SAPI, through Windows PowerShell) and espeak-ng (or espeak) wherever
it is installed. "auto" is the best voice found. Whichever voice reads, the result is the same kind of file: a WAV
(mono, 48 kHz, 16-bit) with the silence at both ends trimmed to 40 ms, so the scenes join evenly.

Speed: the engine and espeak-ng read at the speed asked. macOS and Windows voices read at their usual pace and FFmpeg
then makes the sound faster or slower without changing its pitch (`atempo`), because their own rate settings do not
scale evenly. Measured on GitHub's Mac and Windows machines (scripts/shorts_check.py): `say -r` at 1.3 times the
words a minute read 1.7 times as fast, and the Windows rate for 1.3 (3 of 10) read 1.44 times as fast; the Windows
rate also only has whole steps, so the shorts' Calm (0.95) and Lively (1.05) were both read at the usual pace.

The words reach a voice program in a temporary file, never on its command line and never through a shell; a voice
name is only ever one that `voices()` listed; a cancel stops the program at once.

When each word is said, best first: the engine's own times; the speech model's, when it is installed and already
downloaded (nothing is downloaded here), matched to the script's words; else an estimate from the sound alone: the
voiced stretch, its pauses matched to the script's punctuation, and each phrase shared out by syllables. The words
are always the script's own words with their punctuation, so the captions show what was written. A token that is
only punctuation or a symbol nobody says (a lone dash, an emoji) is not a word.
"""
from __future__ import annotations

import bisect
import difflib
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from ..pipeline import ffmpeg_utils
from ..pipeline.common import Cancelled, JobContext
from . import local_engines

log = logging.getLogger(__name__)

RATE = 48000               # the voice file: mono, 48 kHz, 16-bit
EDGE_S = 0.04              # the silence kept at both ends
FADE_S = 0.005             # the very first and last moments fade, so a cut there never clicks
WPM = 175                  # words a minute at speed 1.0 (say -r, espeak -s)
TEMPO_KINDS = ("say", "sapi")  # voices made faster or slower by FFmpeg after they read (see the module's notes)
SPEEDS = (0.7, 1.4)
CACHE_S = 600.0            # the voice list is looked up again after ten minutes...
RETRY_S = 30.0             # ...or after half a minute when listing this computer's voices failed
FRAME_S = 0.01             # loudness is measured every 10 ms
PAUSE_S = 0.12             # a quiet run this long inside the speech is a pause...
SHORT_PAUSE_S = 0.06       # ...but fast speech pauses less at a comma, so a shorter run is a weaker candidate
MATCH_MIN = 0.5            # heard words must match this share of the script's words, else they are not used
WORD_S = 60.0 / WPM        # one word's time when nothing better is known
FINAL_WEIGHT = 3           # the last word of a phrase is drawn out (phrase-final lengthening)
MIN_WORD_S = 0.01
AUTO_NAME = "Best voice on this computer"
SETUP = "download the voice in ClipForge's Settings → Pictures, video, voice"

# macOS voices made for fun rather than narration (System Settings lists them under "Novelty")
NOVELTY = frozenset({"albert", "bad news", "bahh", "bells", "boing", "bubbles", "cellos", "deranged", "good news",
                     "hysterical", "jester", "organ", "pipe organ", "superstar", "trinoids", "whisper", "wobble",
                     "zarvox"})
MAC_FAVOURITES = ("Samantha", "Daniel", "Karen", "Alex")
WINDOWS_FAVOURITES = ("zira", "aria", "david")
# `say -v ?` does not say who speaks: the English macOS voices people know
MAC_GENDERS = {**dict.fromkeys(("samantha", "karen", "moira", "tessa", "fiona", "veena", "victoria", "allison", "ava",
                                "susan", "zoe", "kate", "serena", "kathy", "vicki", "agnes", "princess", "flo",
                                "grandma", "sandy", "shelley", "isha", "sangeeta", "nicky", "joelle", "noelle",
                                "matilda", "catherine", "martha"), "female"),
               **dict.fromkeys(("alex", "daniel", "fred", "tom", "oliver", "lee", "rishi", "evan", "nathan", "aaron",
                                "arthur", "gordon", "bruce", "ralph", "junior", "eddy", "grandpa", "reed", "rocko",
                                "jamie"), "male")}
ESPEAK_VOICES = (("en-us", "American man (simple voice)", "en-US", "male"),
                 ("en-us+f3", "American woman (simple voice)", "en-US", "female"),
                 ("en-gb", "British man (simple voice)", "en-GB", "male"),
                 ("en-gb+f3", "British woman (simple voice)", "en-GB", "female"))
ESPEAK_ABOUT = "A simple voice from espeak-ng: clear, but it sounds like a robot."

# Windows PowerShell scripts: fixed text with single quotes only. The words, the voice and the paths arrive in
# environment variables and a file, never on the command line.
SAPI_LIST = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Add-Type -AssemblyName System.Speech; "
             "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
             "foreach ($v in $s.GetInstalledVoices()) { if ($v.Enabled) { $i = $v.VoiceInfo; "
             "[Console]::Out.WriteLine($i.Name + '|' + $i.Culture.Name + '|' + $i.Gender) } }; $s.Dispose()")
SAPI_SPEAK = ("$ErrorActionPreference = 'Stop'; Add-Type -AssemblyName System.Speech; "
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "try { $s.SelectVoice($env:CLIPFORGE_VOICE_NAME); "
              "$s.SetOutputToWaveFile($env:CLIPFORGE_VOICE_OUT); "
              "$s.Speak([System.IO.File]::ReadAllText($env:CLIPFORGE_VOICE_TEXT, [System.Text.Encoding]::UTF8)) } "
              "finally { $s.Dispose() }")


class VoiceError(RuntimeError):
    """No voice could read the words. The message says what happened and what to do."""


class _Failed(Exception):
    """One voice did not work. `why` is "silent", "slow" or ""; `reason` is the half sentence the owner reads
    ("“Daniel” did not work on this computer") and `detail` an optional sentence after it."""

    def __init__(self, log_text: str, *, why: str = "", reason: str = "", detail: str = ""):
        super().__init__(log_text)
        self.why, self.reason, self.detail = why, reason, detail


# ------------------------------------------------------------------ the voices
_cache: dict = {"at": 0.0, "key": None, "voices": []}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    """Forget the voice list, so the next `voices()` looks again (after a voice was installed, and in tests)."""
    with _cache_lock:
        _cache.update(at=0.0, key=None, voices=[])


def voices() -> list[dict]:
    """Every voice that can read here, for the page's picker: [{"id", "name", "lang", "gender", "about", "engine"}].

    "auto" comes first, then the local engine's voices ("engine:<id>"), this computer's own ("system:<name>": macOS
    `say` or the Windows voices) and espeak-ng's ("espeak:<voice>"), English voices first within each. Novelty voices
    are left out. The list is kept for ten minutes (and looked up again at once when the engine is set up or stops);
    it never raises."""
    status = local_engines.status("voice")
    key = (bool(status["ready"]), status["engine"])
    with _cache_lock:
        if _cache["key"] == key and time.monotonic() - _cache["at"] < CACHE_S:
            return [dict(v) for v in _cache["voices"]]
        trouble: list[str] = []
        found = _engine_voices(status, trouble) + _system_voices(trouble) + _espeak_voices()
        listing = [_auto_entry(found)] + found
        # a listing that failed (a slow first start of PowerShell, a busy computer) is looked up again soon
        _cache.update(at=time.monotonic() - (CACHE_S - RETRY_S if trouble else 0.0), key=key, voices=listing)
        return [dict(v) for v in listing]


def default_voice() -> str:
    """The voice "auto" reads with: the local engine's when it is set up, else this computer's best (macOS: a
    Premium, then an Enhanced voice, then Samantha, Daniel, Karen or Alex; Windows: Zira, Aria or David; espeak-ng:
    American English). "" when this computer has no voice at all."""
    order = _auto_order(voices(), "en")
    return order[0]["id"] if order else ""


def _entry(vid: str, name: str, lang: str, gender: str, about: str, engine: str) -> dict:
    return {"id": vid, "name": name, "lang": lang, "gender": gender, "about": about, "engine": engine}


def _lang_base(lang: str) -> str:
    return re.split(r"[-_]", str(lang or "").strip().lower())[0]


def _speaks(v: dict, want: str) -> bool:
    """Whether a voice reads the language `want` ("en"): a voice that reads every language says "multilingual" or
    "mul", or nothing."""
    base = _lang_base(v["lang"])
    return base == want or base in ("multilingual", "mul", "")


def _english_first(found: list[dict]) -> list[dict]:
    return sorted(found, key=lambda v: _lang_base(v["lang"]) != "en")


def _auto_entry(found: list[dict]) -> dict:
    order = _auto_order(found, "en")
    if not order:
        return _entry("auto", AUTO_NAME, "en", "", f"No voice was found on this computer yet. {_how_to_add()}", "")
    best = order[0]
    return _entry("auto", AUTO_NAME, best["lang"], best["gender"],
                  f"ClipForge picks the best voice it finds. Right now that is {best['name']}.", best["engine"])


def _auto_order(listing: list[dict], lang: str = "en") -> list[dict]:
    """The best voice of each kind, best first: the engine's, this computer's own, espeak-ng's. A kind with a voice
    in `lang` comes before one without."""
    want = _lang_base(lang) or "en"
    picks = []
    for rank, kinds in enumerate((("engine",), ("say", "sapi"), ("espeak",))):
        group = [v for v in listing if v["engine"] in kinds and v["id"] != "auto"]
        if not group:
            continue
        same = [v for v in group if _speaks(v, want)]
        english = [v for v in group if _speaks(v, "en")]
        picks.append((0 if same else 1, rank, _best(same or english or group)))
    return [pick for *_, pick in sorted(picks, key=lambda p: p[:2])]


def _best(group: list[dict]) -> dict:
    kind = group[0]["engine"]
    if kind == "say":
        def rank(v: dict) -> tuple:
            name = v["name"]
            tier = (0 if "(Premium)" in name else 1 if "(Enhanced)" in name
                    else 2 + MAC_FAVOURITES.index(name) if name in MAC_FAVOURITES else 9)
            return tier, v["lang"].lower() != "en-us"
        return min(group, key=rank)
    if kind == "sapi":
        for favourite in WINDOWS_FAVOURITES:
            for v in group:
                if favourite in v["name"].lower().split():
                    return v
    if kind == "espeak":
        return next((v for v in group if v["id"] == "espeak:en-us"), group[0])
    return group[0]


def _engine_voices(status: dict, trouble: list[str]) -> list[dict]:
    mod = local_engines.module()
    if not status["ready"] or mod is None:
        return []
    try:
        listed = list(mod.voices() or [])
    except Exception:  # noqa: BLE001 - a broken engine leaves this computer's own voices
        log.exception("The voice engine could not list its voices")
        trouble.append("engine")
        return []
    found = {}
    for v in listed:
        vid = str(v.get("id") or "").strip() if isinstance(v, dict) else ""
        if vid:
            about = str(v.get("about") or "A voice from the local voice engine.")
            found[vid] = _entry(f"engine:{vid}", str(v.get("name") or vid), str(v.get("lang") or ""),
                                str(v.get("gender") or ""), about, "engine")
    return _english_first(list(found.values()))


def _system_voices(trouble: list[str]) -> list[dict]:
    try:
        if sys.platform == "darwin":
            return _say_voices()
        if sys.platform == "win32":
            return _sapi_voices()
    except (OSError, ValueError, subprocess.SubprocessError, ffmpeg_utils.FFmpegError) as exc:
        log.warning("This computer's voices could not be listed: %s", exc)
        trouble.append("system")
    return []


def _say_voices() -> list[dict]:
    say = _find("say")
    if not say:
        return []
    got = _run([say, "-v", "?"], timeout=30.0)
    if got.returncode != 0:
        raise OSError(f"say -v ? answered {got.returncode}: {_tail(got.stderr)}")
    return _parse_say(got.stdout.decode("utf-8", "replace"))


_SAY_LINE = re.compile(r"^(?P<name>\S.*?)\s+(?P<lang>[A-Za-z]{2,3}(?:[_-][A-Za-z0-9]+)*)\s+#")


def _parse_say(listing: str) -> list[dict]:
    """The voices in `say -v ?` lines like "Samantha            en_US    # Hello! My name is Samantha." or
    "Eddy (English (US)) en_US    # ...", without the novelty voices."""
    found = {}
    for line in listing.splitlines():
        m = _SAY_LINE.match(line.strip())
        if not m:
            continue
        name = m["name"].strip()
        base = name.split(" (")[0].strip()
        if base.lower() in NOVELTY:
            continue
        better = "(Premium)" in name or "(Enhanced)" in name
        found[name] = _entry(f"system:{name}", name, m["lang"].replace("_", "-"), MAC_GENDERS.get(base.lower(), ""),
                             "Comes with macOS, in its higher quality." if better else "Comes with macOS.", "say")
    return _english_first(list(found.values()))


def _sapi_voices() -> list[dict]:
    powershell = _find("powershell")
    if not powershell:
        return []
    got = _run([powershell, "-NoProfile", "-NonInteractive", "-Command", SAPI_LIST], timeout=30.0)
    if got.returncode != 0:
        raise OSError(f"the Windows voices could not be listed ({got.returncode}): {_tail(got.stderr)}")
    return _parse_sapi(got.stdout.decode("utf-8", "replace"))


def _parse_sapi(listing: str) -> list[dict]:
    """The voices in "name|culture|gender" lines (Windows PowerShell, System.Speech)."""
    found = {}
    for line in listing.lstrip("\ufeff").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0]:
            continue
        gender = parts[2].lower() if len(parts) > 2 else ""
        gender = gender if gender in ("female", "male", "neutral") else ""
        found[parts[0]] = _entry(f"system:{parts[0]}", parts[0], parts[1], gender, "Comes with Windows.", "sapi")
    return _english_first(list(found.values()))


def _espeak_voices() -> list[dict]:
    exe = _espeak()
    if not exe:
        return []
    have = _espeak_languages(exe)
    return [_entry(f"espeak:{vid}", name, lang, gender, ESPEAK_ABOUT, "espeak")
            for vid, name, lang, gender in ESPEAK_VOICES if have is None or vid.split("+")[0] in have]


def _espeak_languages(exe: str) -> set[str] | None:
    """The languages espeak lists (`--voices`), or None when it could not say (then the usual ones are offered)."""
    try:
        got = _run([exe, "--voices"], timeout=15.0)
    except (OSError, subprocess.SubprocessError, ffmpeg_utils.FFmpegError):
        return None
    if got.returncode != 0:
        return None
    rows = [line.split() for line in got.stdout.decode("utf-8", "replace").splitlines()[1:]]
    return {row[1].lower() for row in rows if len(row) > 1} or None


def _find(program: str) -> str | None:
    """Where a voice program is, or None. Windows PowerShell is also looked for where Windows keeps it."""
    found = shutil.which(program)
    if found or program != "powershell" or sys.platform != "win32":
        return found
    path = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return str(path) if path.is_file() else None


def _espeak() -> str | None:
    return _find("espeak-ng") or _find("espeak")


# ------------------------------------------------------------------ reading aloud
def speak(text: str, out: Path, *, voice: str = "auto", speed: float = 1.0, lang: str = "en",
          cancel: Callable[[], bool] | None = None) -> dict:
    """Read `text` aloud into `out`: a WAV (mono, 48 kHz, 16-bit) with the silence at both ends trimmed to 40 ms.

    `voice` is an id from `voices()` ("auto" is the best one); an id that is not there reads with the best voice,
    and so does a voice that does not work. `speed` is kept within 0.7 to 1.4 (1.0 is the voice's usual pace, about
    175 words a minute); macOS and Windows voices get it from FFmpeg after they read (see the module's notes).
    `cancel()` is checked before and after, and stops a voice program while it runs (raising Cancelled).

    Returns {"path", "duration_s", "words": the engine's timed words (on this file's time) or None, "engine":
    "engine" | "say" | "sapi" | "espeak", "voice": its name, "fallback": why the asked voice was not used ("" when it
    was), "voice_id", "rule": what the voice's licence asks of what it makes ("" for none), "original": the local
    voice engine's own file in engines/made, with its note next to it ("" for the other voices; the caller keeps it
    with what it made from it, or leaves it there)}. Raises VoiceError when no voice can read the words."""
    said = _speakable(text)
    if not said:
        raise VoiceError("There are no words to read. Write what the voice should say, then try again.")
    speed = _speed(speed)
    _check(cancel)
    try:
        ffmpeg_utils.ffmpeg_bin()
    except ffmpeg_utils.FFmpegError as exc:
        raise VoiceError("ClipForge needs FFmpeg to save a voice, and FFmpeg was not found. Install it (the ClipForge "
                         "setup does this), then try again.") from exc
    out = Path(out)
    plan, reason = _plan(voice, lang)
    if not plan:
        raise VoiceError(f"{_no_voice()} {_how_to_add()}")
    detail, failures = "", []
    try:
        with tempfile.TemporaryDirectory(prefix="clipforge-voice-", ignore_cleanup_errors=True) as tmp:
            for k, choice in enumerate(plan):
                try:
                    made = _read_with(choice, said, out, speed, lang, Path(tmp) / str(k), cancel)
                except _Failed as exc:
                    log.warning("The voice %s did not work: %s", choice["id"], exc)
                    failures.append(exc.reason)
                    if not reason:
                        reason, detail = exc.reason, exc.detail
                    continue
                note = f"{reason}, so ClipForge used “{choice['name']}” instead." if reason else ""
                return {"path": str(out), "duration_s": made["duration_s"], "words": made["words"],
                        "engine": choice["engine"], "voice": choice["name"],
                        "fallback": f"{note} {detail}".strip(), "voice_id": choice["id"], "rule": made.get("rule", ""),
                        "original": made.get("original", "")}
    except OSError as exc:
        raise VoiceError("ClipForge could not save the voice. Check that the disk has free space, then try "
                         "again.") from exc
    raise VoiceError(f"{_no_voice()[:-1]} that could read these words. {failures[0]}. Try again{_or_setup()}.")


def _speed(speed) -> float:
    try:
        value = float(speed)
    except (TypeError, ValueError):
        return 1.0
    return min(SPEEDS[1], max(SPEEDS[0], value)) if math.isfinite(value) else 1.0


def _wpm(speed: float) -> int:
    return round(WPM * speed)


def _check(cancel: Callable[[], bool] | None) -> None:
    if cancel is not None and cancel():
        raise Cancelled()


def _no_voice() -> str:
    return "No voice is available on this computer."


def _or_setup() -> str:
    """", or download the voice in ClipForge's Settings" when this ClipForge has the local makers (the Settings page
    shows that section only then), else ""."""
    return f", or {SETUP}" if local_engines.available() else ""


def _how_to_add() -> str:
    if sys.platform == "darwin":
        return f"Add a voice in System Settings → Accessibility → Spoken Content{_or_setup()}."
    if sys.platform == "win32":
        return f"Add a voice in Windows Settings → Time & language → Speech{_or_setup()}."
    return f"Install espeak-ng (for example: sudo apt install espeak-ng){_or_setup()}."


def _no_commands(text: str) -> str:
    """say acts on [[...]] commands inside the words, and espeak-ng reads [[...]] as phoneme codes: every pair of
    brackets is broken up ("[[[slnc 3000]]]" → "[ [ [slnc 3000] ] ]"), so the script is only ever read aloud."""
    return re.sub(r"\](?=\])", "] ", re.sub(r"\[(?=\[)", "[ ", text))


def _speakable(text: str) -> str:
    """The words as a voice should get them: on one line, without emoji and other symbols nobody says aloud."""
    kept = []
    for ch in unicodedata.normalize("NFC", str(text or "")):
        cat = unicodedata.category(ch)
        if ch in _SYMBOL_SYL:
            kept.append(ch)
        elif cat == "Cf" or ch in "\ufe0e\ufe0f":
            continue  # joiners and variation selectors inside emoji, soft hyphens inside words
        elif cat in ("So", "Sk", "Cs", "Co", "Cn", "Cc"):
            kept.append(" ")
        else:
            kept.append(ch)
    return " ".join("".join(kept).split())


def _plan(asked, lang: str) -> tuple[list[dict], str]:
    """The voices to try in order (the asked one, then the best of each kind) and, when the asked voice cannot be
    used at all, why (the first half of the owner's sentence)."""
    listing = voices()
    order = _auto_order(listing, lang)
    asked = str(asked or "").strip() or "auto"
    if asked == "auto":
        return order, ""
    known = next((v for v in listing if v["id"] == asked), None)
    if known is not None:
        return [known] + [v for v in order if v["id"] != asked], ""
    if asked.startswith("engine:"):
        ready = any(v["engine"] == "engine" for v in listing)
        return order, ("The local voice engine does not have that voice any more" if ready
                       else "The local voice engine is not ready")
    return order, "The voice you picked is not on this computer"


def _read_with(choice: dict, text: str, out: Path, speed: float, lang: str, work: Path, cancel) -> dict:
    kind, name = choice["engine"], choice["name"]
    voice_id = choice["id"].split(":", 1)[1]
    work.mkdir(parents=True, exist_ok=True)
    words, rule, original = None, "", ""
    try:
        if kind == "engine":
            raw, words, rule = _engine_read(voice_id, text, speed, lang, cancel)
            original = str(raw)
        elif kind == "say":
            raw = _say_read(voice_id, _no_commands(text), work, cancel)
        elif kind == "sapi":
            raw = _sapi_read(voice_id, text, work, cancel)
        else:
            raw = _espeak_read(voice_id, _no_commands(text), work, speed, cancel)
        try:
            length, shift = _save(raw, out, work, cancel, tempo=speed if kind in TEMPO_KINDS else 1.0)
        except BaseException:
            local_engines.discard_made(original)  # the engine's file that could not be used (or Stop) goes
            raise
    except _Failed as exc:
        if not exc.reason:
            who = "The local voice engine" if kind == "engine" else f"“{name}”"
            exc.reason = {"silent": f"{who} made no sound for these words", "slow": f"{who} took too long"}.get(
                exc.why, "The local voice engine could not read this" if kind == "engine"
                else f"{who} did not work on this computer")
        raise
    return {"duration_s": round(length, 3), "words": _shifted(words, shift, length) if words else None, "rule": rule,
            "original": original}


def _engine_read(engine_id: str, text: str, speed: float, lang: str, cancel) -> tuple[Path, object, str]:
    """The local engine reads the words: its sound file, its timed words (None when it only estimated them: then the
    speech model or the estimate from the sound times them) and its licence's rule for what it makes ("" for none:
    a voice whose licence asks for a label carries that sentence, shown with the short)."""
    mod = local_engines.module()
    if mod is None or not local_engines.status("voice")["ready"]:
        raise _Failed("the voice engine is not ready", reason="The local voice engine is not ready")
    try:
        got = mod.speak(text, voice=engine_id, speed=speed, lang=lang, progress=_no_progress,
                        cancel=lambda: bool(cancel is not None and cancel()))
    except Cancelled:
        raise
    except local_engines.errors() as exc:
        _check(cancel)
        said = "" if isinstance(exc, OSError) else _sentence(str(exc))  # an OSError's words are for the log
        raise _Failed(repr(exc), reason="The local voice engine could not read this",
                      detail=f"The engine said: {said}" if said else "") from exc
    except Exception as exc:  # noqa: BLE001 - a fault inside the engine: logged, and this computer's voice reads
        _check(cancel)
        log.exception("The voice engine failed")
        raise _Failed(repr(exc), reason="The local voice engine could not read this") from exc
    made = got.get("path") if isinstance(got, dict) else None
    path = Path(str(made)) if made else None
    try:
        _check(cancel)
    except BaseException:
        local_engines.discard_made(path)  # stopped as it finished: what it made goes
        raise
    if path is None or not path.is_file():
        raise _Failed(f"the voice engine answered {got!r}", reason="The local voice engine did not make a sound file")
    words = None if str(got.get("word_timing") or "").lower() == "estimated" else got.get("words")
    return path, words, " ".join(str(got.get("rule") or "").split())[:400]


def _no_progress(fraction: float = 0.0, message: str = "") -> None:
    return None


def _sentence(text: str) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _say_read(name: str, text: str, work: Path, cancel) -> Path:
    """macOS reads at its usual pace (speed 1.0); FFmpeg sets the speed afterwards."""
    say = _find("say")
    if not say:
        raise _Failed("say is missing")
    words, made = _words_file(work, text), work / "voice.aiff"
    _program([say, "-v", name, "-r", str(WPM), "-f", str(words), "-o", str(made)], made, text, cancel)
    return made


def _sapi_read(name: str, text: str, work: Path, cancel) -> Path:
    """Windows reads at its usual pace (rate 0); FFmpeg sets the speed afterwards."""
    powershell = _find("powershell")
    if not powershell:
        raise _Failed("Windows PowerShell is missing")
    words, made = _words_file(work, text), work / "voice.wav"
    env = dict(os.environ, CLIPFORGE_VOICE_TEXT=str(words), CLIPFORGE_VOICE_NAME=name, CLIPFORGE_VOICE_OUT=str(made))
    _program([powershell, "-NoProfile", "-NonInteractive", "-Command", SAPI_SPEAK], made, text, cancel, env=env)
    return made


def _espeak_read(name: str, text: str, work: Path, speed: float, cancel) -> Path:
    exe = _espeak()
    if not exe:
        raise _Failed("espeak-ng is missing")
    words, made = _words_file(work, text), work / "voice.wav"
    _program([exe, "-b", "1", "-v", name, "-s", str(_wpm(speed)), "-f", str(words), "-w", str(made)], made, text,
             cancel)
    return made


def _words_file(work: Path, text: str) -> Path:
    path = work / "words.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _program(args: list[str], made: Path, text: str, cancel, env: dict | None = None) -> None:
    """Run one voice program; it must leave its sound file at `made`."""
    try:
        got = _run(args, timeout=min(1800.0, 60.0 + 0.5 * len(text.split())), cancel=cancel, env=env)
    except ffmpeg_utils.FFmpegError as exc:  # the time limit
        raise _Failed(f"{Path(args[0]).name}: {exc}", why="slow") from exc
    except OSError as exc:
        raise _Failed(f"{Path(args[0]).name} could not start: {exc}") from exc
    if got.returncode != 0 or not made.is_file() or made.stat().st_size == 0:
        raise _Failed(f"{Path(args[0]).name} answered {got.returncode}: {_tail(got.stderr)}")


def _run(args: list[str], *, timeout: float, cancel: Callable[[], bool] | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a program from an argument list (no shell) and wait for it. A cancel or the time limit stops it at once
    (Cancelled, or FFmpegError for the time limit)."""
    with ffmpeg_utils.MediaWatchdog(cancel, timeout) as watch:
        proc = watch.add(subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, env=env, creationflags=ffmpeg_utils.NO_WINDOW))
        stdout, stderr = proc.communicate()
        watch.check()
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


def _tail(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", "replace").strip()[-400:]


def _convert(src: Path, dst: Path, rate: int, cancel=None, tempo: float = 1.0) -> None:
    """Any sound file as a mono 16-bit WAV at `rate`, by FFmpeg; `tempo` other than 1 makes it that much faster or
    slower without changing its pitch."""
    tempo = _speed(tempo)
    shape = ["-af", f"atempo={tempo:.4f}"] if abs(tempo - 1.0) > 1e-4 else []
    args = [ffmpeg_utils.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(src),
            "-map", "0:a:0", *shape, "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", "-f", "wav", str(dst)]
    try:
        got = ffmpeg_utils.run_process(args, timeout=300.0, cancel=cancel)
    except ffmpeg_utils.FFmpegError as exc:
        raise _Failed(f"converting the voice: {exc}", why="slow") from exc
    if got.returncode != 0 or not dst.is_file():
        raise _Failed(f"FFmpeg could not read the voice's sound: {_tail(got.stderr)}")


def _save(raw: Path, out: Path, work: Path, cancel, tempo: float = 1.0) -> tuple[float, float]:
    """The voice program's sound as the voice file `out` (`tempo` times as fast): (its length, and how far its times
    moved, in seconds). Engine words are only ever given with tempo 1."""
    pcm = work / "voice-48k.wav"
    _convert(raw, pcm, RATE, cancel, tempo)
    _check(cancel)
    return _trim(pcm, out)


def _trim(pcm: Path, out: Path) -> tuple[float, float]:
    """Copy the 48 kHz mono `pcm` to `out` with EDGE_S of silence before the first sound and after the last (cut
    or padded to that), the outermost 5 ms faded. Written beside `out` first and then moved, so a reader never sees
    half a file. Returns (length, shift): a time in `pcm` is time + shift in `out`."""
    with wave.open(str(pcm), "rb") as src:
        levels = _levels(src)
        frames, rate = src.getnframes(), src.getframerate()
    span = _span(_voiced(levels, rel=45.0, floor=-70.0))
    if span is None:
        raise _Failed("the voice is silent", why="silent")
    hop, edge = _hop(rate), int(round(rate * EDGE_S))
    first, last = span[0] * hop, min(frames, (span[1] + 1) * hop)
    start, end = max(0, first - edge), min(frames, last + edge)
    before, after = edge - (first - start), edge - (end - last)
    out.parent.mkdir(parents=True, exist_ok=True)
    handle, part = tempfile.mkstemp(prefix=".voice-", suffix=".wav", dir=out.parent)
    os.close(handle)
    try:
        with wave.open(str(pcm), "rb") as src, wave.open(part, "wb") as dst:
            dst.setnchannels(1)
            dst.setsampwidth(2)
            dst.setframerate(rate)
            dst.writeframes(bytes(2 * before))
            copied = _copy(src, dst, start, end - start, int(rate * FADE_S))
            dst.writeframes(bytes(2 * after))
        os.replace(part, out)
    except BaseException:
        Path(part).unlink(missing_ok=True)
        raise
    return (before + copied + after) / rate, (before - start) / rate


def _copy(src: wave.Wave_read, dst: wave.Wave_write, start: int, count: int, fade: int) -> int:
    """Copy `count` mono 16-bit frames from `start`, a second at a time, fading the first and last `fade` frames."""
    fade = max(1, min(fade, count // 2))
    src.setpos(start)
    done = 0
    while done < count:
        x = np.frombuffer(src.readframes(min(count - done, src.getframerate())), dtype="<i2").astype(np.float32)
        if not len(x):
            break
        at = np.arange(done, done + len(x))
        x *= np.clip(np.minimum(at + 1, count - at) / fade, 0.0, 1.0)
        dst.writeframes(np.clip(np.round(x), -32768, 32767).astype("<i2").tobytes())
        done += len(x)
    return done


def _shifted(words, shift: float, length: float) -> list[dict] | None:
    heard = _clean_heard(words)
    if not heard:
        return None
    return _tidy([{"w": h["w"], "start": h["start"] + shift, "end": h["end"] + shift} for h in heard], length)


# ------------------------------------------------------------------ the sound's loudness
def _hop(rate: int) -> int:
    return max(1, int(round(rate * FRAME_S)))


def _samples(raw: bytes, width: int, channels: int) -> np.ndarray:
    """PCM bytes as float samples in -1..1, mixed to mono."""
    if width == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw[: len(raw) // 3 * 3], np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = np.where(v >= 1 << 23, v - (1 << 24), v).astype(np.float32) / float(1 << 23)
    elif width == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / float(1 << 31)
    else:
        raise ValueError(f"{width * 8}-bit sound is not supported here")
    if channels > 1:
        x = x[: len(x) // channels * channels].reshape(-1, channels).mean(axis=1)
    return x


def _levels(wf: wave.Wave_read) -> np.ndarray:
    """The loudness of every 10 ms of an open WAV file, in dBFS (silence is -120), read a second at a time."""
    hop = _hop(wf.getframerate())
    width, channels = wf.getsampwidth(), wf.getnchannels()
    chunks: list[np.ndarray] = []
    rest = np.zeros(0, np.float32)
    while True:
        raw = wf.readframes(hop * 100)
        if not raw:
            break
        x = np.concatenate([rest, _samples(raw, width, channels)])
        n = len(x) // hop
        if n:
            chunks.append(np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1)))
        rest = x[n * hop:]
    if len(rest):
        chunks.append(np.array([np.sqrt(np.mean(rest ** 2))]))  # the last part of a frame counts too
    rms = np.concatenate(chunks) if chunks else np.zeros(0)
    return 20.0 * np.log10(rms + 1e-6)


def _sound_levels(path: Path) -> tuple[np.ndarray, float, float]:
    """(loudness every 10 ms, seconds per value, the file's length in seconds); (empty, FRAME_S, 0) when the file
    cannot be read. A WAV is read directly; anything else (or an unusual WAV) through FFmpeg."""
    try:
        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate()
            return _levels(wf), _hop(rate) / rate, wf.getnframes() / rate
    except (wave.Error, EOFError, OSError, ValueError):
        pass
    try:
        with tempfile.TemporaryDirectory(prefix="clipforge-voice-", ignore_cleanup_errors=True) as tmp:
            pcm = Path(tmp) / "sound.wav"
            _convert(path, pcm, 16000)
            with wave.open(str(pcm), "rb") as wf:
                return _levels(wf), _hop(16000) / 16000, wf.getnframes() / 16000
    except (_Failed, ffmpeg_utils.FFmpegError, wave.Error, EOFError, OSError, ValueError) as exc:
        log.info("The sound of %s could not be read (%s)", path.name, exc)
    return np.zeros(0), FRAME_S, 0.0


def _length(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except (wave.Error, EOFError, OSError, ValueError, ZeroDivisionError):
        return None


def _voiced(levels: np.ndarray, *, rel: float, floor: float) -> np.ndarray:
    """Which 10 ms frames have sound: louder than `rel` dB below the loud frames (and than `floor` dBFS). A lone
    frame in the quiet is a click, not sound."""
    if not len(levels):
        return np.zeros(0, dtype=bool)
    heard = levels[levels > -100.0]
    ref = float(np.percentile(heard, 95)) if len(heard) >= 10 else float(levels.max())
    mask = levels > max(ref - rel, floor)
    if len(mask) > 2:
        lone = mask[1:-1] & ~mask[:-2] & ~mask[2:]
        mask[1:-1][lone] = False
    return mask


def _span(mask: np.ndarray) -> tuple[int, int] | None:
    """The first and last frame with sound, or None."""
    found = np.flatnonzero(mask)
    return (int(found[0]), int(found[-1])) if len(found) else None


def _pauses(mask: np.ndarray, span: tuple[int, int], step: float) -> list[tuple[float, float]]:
    """The quiet runs of at least SHORT_PAUSE_S between the first and the last sound, as (start, end) seconds."""
    first, last = span
    quiet = (~mask[first:last + 1]).astype(np.int8)
    edges = np.flatnonzero(np.diff(np.concatenate([[0], quiet, [0]])))
    return [((first + a) * step, (first + b) * step) for a, b in zip(edges[::2], edges[1::2])
            if (b - a) * step >= SHORT_PAUSE_S - 1e-9]


# ------------------------------------------------------------------ the script's words
_CLOSERS = "\"'”’»)]}"
_OPENERS = "\"'“‘«([{"
_ABBREVIATIONS = frozenset({"mr.", "mrs.", "ms.", "dr.", "st.", "jr.", "sr.", "prof.", "vs.", "e.g.", "i.e.", "mt.",
                            "approx."})
_INITIALS = re.compile(r"(?:[^\W\d_]\.)+")
_VOWELS = frozenset("aeiouyàáâãäåæèéêëìíîïòóôõöøùúûüýÿœаеёиоуыэюяαεηιουωάέήίόύώ")
_ONES_SYL = (2, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 3, 1, 2, 2, 2, 2, 3, 2, 2)   # zero .. nineteen
_TENS_SYL = (0, 0, 2, 2, 2, 2, 2, 3, 2, 2)                                # twenty .. ninety
_SYMBOL_SYL = {"%": 2, "$": 2, "€": 2, "£": 1, "¥": 1, "&": 1, "+": 1, "=": 2, "@": 1, "#": 2, "°": 2}
_SYMBOL_WORDS = {"%": "percent", "$": "dollars", "€": "euros", "£": "pounds", "&": "and", "+": "plus",
                 "=": "equals", "@": "at", "#": "number", "°": "degrees"}
_SUFFIXES = frozenset({"st", "nd", "rd", "th", "s"})   # 1st, 22nd, 1990s: said within the number
_PARTS = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+|[%$€£¥&+=@#°]")
_SKIP_COST = {"end": 3.0, "semi": 2.0, "dash": 2.0, "comma": 1.0}
_MAX_SKIP = 8              # phrase ends in a row without a pause


@dataclass
class _Phrase:
    words: list[str]
    weights: list[int]
    strength: str          # how the speech pauses after it: "end", "semi", "dash" or "comma"

    @property
    def weight(self) -> int:
        return sum(self.weights)


def _is_word(token: str) -> bool:
    return any(ch.isalnum() or ch in _SYMBOL_SYL for ch in token)


def _break_after(token: str) -> str:
    """How the speech pauses after this token: "end" (. ! ?), "semi" (; : …), "dash", "comma" or "" (it does not)."""
    t = token.rstrip(_CLOSERS)
    if not t:
        return ""
    if t.endswith(("...", "…")):
        return "semi"
    last = t[-1]
    if last in ".!?":
        core = t.lower().lstrip(_OPENERS)
        return "" if last == "." and (core in _ABBREVIATIONS or _INITIALS.fullmatch(core)) else "end"
    if last in ";:":
        return "semi"
    if last in "-—–":
        return "dash"
    return "comma" if last == "," else ""


def _phrases(text: str) -> list[_Phrase]:
    """The script cut into phrases at , . ; : ! ? and dashes; each word keeps its exact token and its weight."""
    phrases: list[_Phrase] = []
    words: list[str] = []
    for token in str(text or "").split():
        if _is_word(token):
            words.append(token)
        strength = _break_after(token)
        if strength and words:
            phrases.append(_phrase(words, strength))
            words = []
    if words:
        phrases.append(_phrase(words, "end"))
    return phrases


def _phrase(words: list[str], strength: str) -> _Phrase:
    weights = [_weight(w) for w in words]
    weights[-1] += FINAL_WEIGHT
    return _Phrase(words, weights, strength)


def _weight(token: str) -> int:
    """How long a word takes to say: its syllables (vowel groups; a number as it is read out) plus its letters,
    which stand for its sounds. Measured against espeak-ng's own word times, letters halve the error of syllables
    alone: "stopped" takes longer than "valley"."""
    letters = 0
    for part in _PARTS.findall(unicodedata.normalize("NFKC", token)):
        if part[0].isdigit():
            letters += 3 * _number_syllables(part)
        elif part in _SYMBOL_SYL:
            letters += 3 * _SYMBOL_SYL[part]
        else:
            letters += len(part)
    return _syllables(token) + max(1, letters)


def _syllables(token: str) -> int:
    """How long a word takes to say, in syllables: its vowel groups, a number as it is read out, at least 1."""
    total, after_number = 0, False
    for part in _PARTS.findall(unicodedata.normalize("NFKC", token)):
        if part[0].isdigit():
            total += _number_syllables(part)
            after_number = True
            continue
        if part in _SYMBOL_SYL:
            total += _SYMBOL_SYL[part]
        elif not (after_number and part.lower() in _SUFFIXES):
            total += _letter_syllables(part)
        after_number = False
    return max(1, total)


def _letter_syllables(word: str) -> int:
    if any("\u3040" <= ch <= "\u30ff" or "\u3400" <= ch <= "\u9fff" or "\uac00" <= ch <= "\ud7af" for ch in word):
        return len(word)  # kana, Chinese characters, Hangul: about a syllable each
    if word.isupper() and (2 <= len(word) <= 3 or not any(ch in "AEIOU" for ch in word)):
        return sum(3 if ch == "W" else 1 for ch in word)  # said letter by letter: TV, FBI, HTML
    w = word.lower()
    count, before = 0, False
    for ch in w:
        vowel = ch in _VOWELS
        count += vowel and not before
        before = vowel
    if count > 1 and ((w.endswith("e") and not w.endswith(("le", "ee")))
                      or (w.endswith("ed") and len(w) > 3 and w[-3] not in "td")
                      or (w.endswith("es") and len(w) > 3 and w[-3] not in "sxzcgh")):
        count -= 1  # a silent e: make, jumped, makes
    return count or max(1, len(word) // 3)


def _number_syllables(digits: str) -> int:
    """A number's syllables as it is read out: 1999 is nineteen ninety-nine, 3.5 three point five, 007 zero zero
    seven."""
    s = digits.strip(".,")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
        s = s.replace(",", "")  # 1,000,000
    whole, _, frac = s.replace(",", ".").partition(".")
    frac = frac.replace(".", "")
    said = (1 + sum(_ONES_SYL[int(d)] for d in frac)) if frac else 0  # "point" and each digit
    if (len(whole) > 1 and whole.startswith("0")) or len(whole) > 15:
        return said + sum(_ONES_SYL[int(d)] for d in whole)
    value = int(whole)
    if len(whole) == 4 and not frac and (1100 <= value <= 1999 or 2010 <= value <= 2099):
        high, low = divmod(value, 100)  # a year
        return said + _int_syllables(high) + (2 if low == 0 else _int_syllables(low) if low >= 10
                                              else 1 + _ONES_SYL[low])
    return said + _int_syllables(value)


def _int_syllables(n: int) -> int:
    if n < 20:
        return _ONES_SYL[n]
    if n < 100:
        return _TENS_SYL[n // 10] + (_ONES_SYL[n % 10] if n % 10 else 0)
    if n < 1000:
        return _ONES_SYL[n // 100] + 2 + (_int_syllables(n % 100) if n % 100 else 0)
    for size in (10 ** 12, 10 ** 9, 10 ** 6, 1000):
        if n >= size:
            return _int_syllables(n // size) + 2 + (_int_syllables(n % size) if n % size else 0)
    return 1


def _norm(token: str) -> str:
    """A word as it is compared: lower case, letters and digits only ("Hearts?" and "hearts" are the same word)."""
    t = unicodedata.normalize("NFKC", str(token)).lower()
    return "".join(ch for ch in t if ch.isalnum()) or "".join(_SYMBOL_WORDS.get(ch, "") for ch in t)


# ------------------------------------------------------------------ word times
def estimate_words(wav: Path, text: str) -> list[dict]:
    """When each of the script's words is said, from the sound alone: [{"w", "start", "end"}] in seconds.

    The voiced stretch is found from the loudness (10 ms frames; sound is within 30 dB of the loud frames), its
    pauses are the quiet runs inside it (about 120 ms or more; a little less for fast speech), the script is cut into
    phrases at , . ; : ! ? and dashes, the phrase ends are matched in order to the pauses that fit the phrases'
    lengths by syllables best, and each phrase is shared out over its own time by syllables. The words are the
    script's tokens with their punctuation, in order, never overlapping, inside the file. Always answers: a file
    without sound gets the words spread over its length, a file that cannot be read gets them at 175 words a
    minute."""
    phrases = _phrases(text)
    if not phrases:
        return []
    levels, step, length = _sound_levels(Path(wav))
    if length <= 2 * FRAME_S:
        whole = sum(len(p.words) for p in phrases) * WORD_S
        return _tidy(_spread_phrases(phrases, [(0, len(phrases), 0.0, whole)]))
    voiced = _voiced(levels, rel=30.0, floor=-60.0)
    span = _span(voiced)
    if span is None:
        return _tidy(_spread_phrases(phrases, [(0, len(phrases), 0.0, length)]), length)
    start, end = span[0] * step, min(length, (span[1] + 1) * step)
    groups = _fit(phrases, _pauses(voiced, span, step), start, end)
    return _tidy(_spread_phrases(phrases, groups), length)


def _fit(phrases: list[_Phrase], pauses: list[tuple[float, float]], start: float,
         end: float) -> list[tuple[int, int, float, float]]:
    """Which pause ends which phrase: [(first phrase, after the last phrase, start s, end s)] in order.

    A dynamic programme over (phrases said, pause reached): a run of phrases between two chosen pauses should last
    as long as its syllables at the voice's pace (the pace is measured, then measured again without the chosen
    pauses); a phrase end without a pause costs (most for a full stop), a long pause left unused costs, and a pause
    shorter than PAUSE_S is a weaker choice."""
    count = len(phrases)
    if count == 1 or not pauses:
        return [(0, count, start, end)]
    sums = [0]
    for p in phrases:
        sums.append(sums[-1] + p.weight)
    skips = [0.0]
    for p in phrases:
        skips.append(skips[-1] + _SKIP_COST.get(p.strength, 1.0))
    starts = [start] + [a for a, _ in pauses] + [end]
    ends = [start] + [b for _, b in pauses] + [end]
    lengths = [0.0] + [b - a for a, b in pauses] + [0.0]
    unused = [0.0]
    for d in lengths[1:-1]:
        unused.append(unused[-1] + min(3.0, max(0.0, d - 0.1) * 10.0))
    k = len(pauses)
    pace = max(0.1, end - start - sum(d for d in lengths if d >= PAUSE_S)) / sums[-1]
    reach = 3.0 + 0.15 * (end - start)  # how far from where its words put it a phrase end may be
    chosen: list[tuple[int, int]] = []
    for _ in range(2):
        best: dict[tuple[int, int], tuple[float, tuple[int, int] | None]] = {(0, 0): (0.0, None)}
        for i in range(1, count + 1):
            near = start + (end - start) * sums[i] / sums[-1]
            for j in (range(bisect.bisect_left(starts, near - reach, 1, k + 1),
                            bisect.bisect_right(starts, near + reach, 1, k + 1)) if i < count else (k + 1,)):
                top: tuple[float, tuple[int, int] | None] = (math.inf, None)
                for i0 in range(i - 1, max(-1, i - 1 - _MAX_SKIP), -1):
                    weight = sums[i] - sums[i0]
                    want = pace * weight
                    spread = 0.18 + 1.25 / math.sqrt(weight)  # a short run of words varies more
                    fixed = skips[i - 1] - skips[i0]  # phrase ends i0+1 .. i-1 had no pause
                    if j <= k:
                        short = min(1.0, max(0.0, (PAUSE_S - lengths[j]) / (PAUSE_S - SHORT_PAUSE_S)))
                        fixed += short * (1.2 if phrases[i - 1].strength == "end" else 0.8)
                    # the latest earlier pause that leaves the run long enough, then earlier ones until too long
                    latest = min(j - 1, bisect.bisect_right(ends, starts[j] - want / 3) - 1)
                    for j0 in ((0,) if i0 == 0 else range(latest, 0, -1)):
                        took = starts[j] - ends[j0]
                        if took > 3 * want + 0.5:
                            break
                        prev = best.get((i0, j0))
                        if prev is None or took < want / 3:
                            continue
                        cost = (prev[0] + fixed + unused[j - 1] - unused[j0]
                                + min(30.0, (math.log(max(took, 0.01) / want) / spread) ** 2))
                        if cost < top[0]:
                            top = (cost, (i0, j0))
                if top[1] is not None:
                    best[(i, j)] = top
        if (count, k + 1) not in best:
            return [(0, count, start, end)]
        chosen, node = [], (count, k + 1)
        while node is not None:
            chosen.append(node)
            node = best[node][1]
        chosen.reverse()
        said = [j for _, j in chosen if 0 < j <= k]
        pace = max(0.1, end - start - sum(lengths[j] for j in said)) / sums[-1]
    return [(i0, i, ends[j0], starts[j]) for (i0, j0), (i, j) in zip(chosen, chosen[1:])]


def _spread_phrases(phrases: list[_Phrase], groups: list[tuple[int, int, float, float]]) -> list[dict]:
    out: list[dict] = []
    for lo, hi, t0, t1 in groups:
        part = phrases[lo:hi]
        out += _spread([w for p in part for w in p.words], [x for p in part for x in p.weights], t0, t1)
    return out


def _spread(words: list[str], weights: list[float], t0: float, t1: float) -> list[dict]:
    """The words one after another over t0..t1, each taking its share by weight."""
    total = float(sum(weights)) or 1.0
    span = max(0.0, t1 - t0)
    out, done = [], 0.0
    for word, weight in zip(words, weights):
        first = t0 + span * done / total
        done += weight
        out.append({"w": word, "start": first, "end": t0 + span * done / total})
    return out


def _tidy(words: list[dict], length: float | None = None) -> list[dict]:
    """The words' times in order, rounded to the millisecond, never overlapping, at least 10 ms long and, when the
    file's length is known, inside it."""
    n = len(words)
    if not n:
        return []
    starts = [float(w["start"]) for w in words]
    ends = [float(w["end"]) for w in words]
    previous = 0.0
    for k in range(n):
        starts[k] = max(starts[k], previous)
        ends[k] = max(ends[k], starts[k] + MIN_WORD_S)
        previous = ends[k]
    if length is not None:
        cap = math.floor(max(0.0, length) * 1000.0) / 1000.0
        least = min(MIN_WORD_S, cap / n)
        for k in range(n - 1, -1, -1):
            ends[k] = min(ends[k], cap)
            starts[k] = max(0.0, min(starts[k], ends[k] - least))
            cap = starts[k]
    return [{"w": w["w"], "start": round(s, 3), "end": round(e, 3)} for w, s, e in zip(words, starts, ends)]


def _clean_heard(items) -> list[dict]:
    """Timed words from an engine or the speech model, made safe: a word, finite times, in order of start."""
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        word = str(item.get("w") or item.get("word") or item.get("text") or "").strip()
        try:
            first = float(item["start"] if item.get("start") is not None else item.get("start_s"))
            last = float(item["end"] if item.get("end") is not None else item.get("end_s"))
        except (TypeError, ValueError):
            continue
        if word and _norm(word) and math.isfinite(first) and math.isfinite(last):
            out.append({"w": word, "start": first, "end": max(first, last)})
    out.sort(key=lambda h: h["start"])
    return out


def align_words(text: str, heard: list[dict]) -> list[dict]:
    """The script's words with the times of the words a speech model (or an engine) heard: matched in order on
    their letters, so "hearts?" takes the time of "Hearts", and a word heard with another spelling ("harts") still
    matches; script words heard as something else entirely share the time of what was heard in their place; words
    not heard at all are spread between their matched neighbours; heard words that are not in the script are left
    out. [{"w", "start", "end"}], in order and never overlapping."""
    words, _ = _align(text, heard)
    return _tidy(words)


def _align(text: str, heard) -> tuple[list[dict], float]:
    """The aligned words (not yet tidied) and the share of the script's words that were heard."""
    script = [w for p in _phrases(text) for w in p.words]
    if not script:
        return [], 0.0
    weights = [_weight(w) for w in script]
    got = _clean_heard(heard)
    if not got:
        return _spread(script, weights, 0.0, len(script) * WORD_S), 0.0
    times: list[tuple[float, float] | None] = [None] * len(script)
    matched = 0
    mine, theirs = [_norm(w) for w in script], [_norm(h["w"]) for h in got]
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, mine, theirs, autojunk=False).get_opcodes():
        pairs = ([(d, d) for d in range(i2 - i1)] if tag == "equal"
                 else _similar_pairs(mine[i1:i2], theirs[j1:j2]) if tag == "replace" else [])
        for di, dj in pairs:
            times[i1 + di] = (got[j1 + dj]["start"], got[j1 + dj]["end"])
        matched += len(pairs)
        if tag == "replace" and not pairs:  # heard as something else entirely ("42" for "forty-two"): that time
            placed = _spread(script[i1:i2], weights[i1:i2], got[j1]["start"], got[j2 - 1]["end"])
            for d, w in enumerate(placed):
                times[i1 + d] = (w["start"], w["end"])
    _fill(times, weights)
    return [{"w": w, "start": t[0], "end": t[1]} for w, t in zip(script, times)], matched / len(script)


def _similar_pairs(mine: list[str], theirs: list[str]) -> list[tuple[int, int]]:
    """Inside a run of words that differ, the pairs spelt alike ("hearts" and "harts"), in order, most alike first."""
    if not mine or not theirs or len(mine) * len(theirs) > 2500:
        return []
    alike = [[_alike(a, b) for b in theirs] for a in mine]
    n, m = len(mine), len(theirs)
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            paired = alike[i][j] + best[i + 1][j + 1] if alike[i][j] else 0.0
            best[i][j] = max(best[i + 1][j], best[i][j + 1], paired)
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if alike[i][j] and best[i][j] == alike[i][j] + best[i + 1][j + 1]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            i += 1
        else:
            j += 1
    return pairs


def _alike(a: str, b: str) -> float:
    ratio = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0
    return ratio if ratio >= 0.6 else 0.0


def _fill(times: list, weights: list[int]) -> None:
    """Give the words that were not heard times between their neighbours (taking up to half of each neighbour
    when the gap is too short for them)."""
    n, k = len(times), 0
    while k < n:
        if times[k] is not None:
            k += 1
            continue
        m = k
        while m < n and times[m] is None:
            m += 1
        need = (m - k) * WORD_S
        left = times[k - 1][1] if k > 0 else None
        right = times[m][0] if m < n else None
        if left is None and right is None:
            left, right = 0.0, need
        elif left is None:
            left = max(0.0, right - need)
        elif right is None:
            right = left + need
        if right - left < 0.06 * (m - k):
            if k > 0:
                left = (times[k - 1][0] + left) / 2
                times[k - 1] = (times[k - 1][0], left)
            if m < n:
                right = (right + times[m][1]) / 2
                times[m] = (right, times[m][1])
        for d, w in enumerate(_spread(["."] * (m - k), weights[k:m], left, right)):
            times[k + d] = (w["start"], w["end"])
        k = m


def time_words(wav: Path, text: str, *, engine_words=None, settings: dict | None = None, listen: bool = True,
               cancel: Callable[[], bool] | None = None, used: dict | None = None) -> tuple[list[dict], str]:
    """The script's words with their times in `wav`, and how they were found:

    "engine" (the voice engine said when it spoke each word; matched to the script), "listened" (the speech model is
    installed and already downloaded: it listened, and what it heard is matched to the script; this never downloads
    anything), or "estimated" (from the sound, see `estimate_words`). Heard or engine words that match less than half
    of the script are not trusted. `cancel` stops the listening (raising Cancelled); any other problem while
    listening falls back to the estimate. `used["model"]` becomes True when the speech model was asked to listen
    (it may stay loaded even when its words were not used: `release()` gives the memory back)."""
    wav = Path(wav)
    length = _length(wav)
    if engine_words:
        words, share = _align(text, _clean_heard(engine_words))
        if words and share >= MATCH_MIN:
            return _tidy(words, length), "engine"
    if listen:
        heard = _listen(wav, settings, cancel, used)
        if heard:
            words, share = _align(text, heard)
            if words and share >= MATCH_MIN:
                return _tidy(words, length), "listened"
    return estimate_words(wav, text), "estimated"


def _listen(wav: Path, settings: dict | None, cancel, used: dict | None = None) -> list[dict] | None:
    """What the speech model hears in the voice, when it is installed and its files are already on this computer;
    None otherwise. A CPU fallback is allowed only when that model is downloaded too, so nothing is downloaded."""
    from ..pipeline import transcribe  # noqa: PLC0415 - heavy, and only needed when listening

    try:
        if not transcribe.whisper_installed():
            return None
        conf = settings if settings is not None else _app_settings()
        plan = transcribe.whisper_plan(conf)
        if not transcribe.model_cached(plan["model"]):
            return None
        auto = (conf.get("whisper_model") or "auto") == "auto"
        allow_cpu = plan["device"] != "cuda" or transcribe.model_cached(transcribe.CPU_MODEL if auto else plan["model"])
        with tempfile.TemporaryDirectory(prefix="clipforge-listen-", ignore_cleanup_errors=True) as tmp:
            pcm = Path(tmp) / "voice-16k.wav"
            _convert(wav, pcm, 16000, cancel)
            if used is not None:
                used["model"] = True  # loading it starts now
            result = transcribe.transcribe(pcm, _length(pcm) or 0.0, conf, JobContext(None, cancel), vad=False,
                                           allow_cpu_fallback=allow_cpu)
        return transcribe.flatten_words(result)
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - listening is a bonus: any problem leaves the estimate to do it
        log.info("Listening to the voice did not work (%s); its word times are estimated", exc)
        return None


def _app_settings() -> dict:
    try:
        from .. import db  # noqa: PLC0415

        return db.get_settings()
    except Exception:  # noqa: BLE001 - the speech model's defaults work without the saved settings
        log.exception("The settings could not be read")
        return {}


def release() -> None:
    """Give back the speech model's memory after a batch of scenes (the next listen loads it again)."""
    try:
        from ..pipeline import transcribe  # noqa: PLC0415

        transcribe.release_model()
    except Exception:  # noqa: BLE001 - releasing memory must never fail a build
        log.exception("The speech model could not be released")

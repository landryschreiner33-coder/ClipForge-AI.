"""ClipForge's own free sound library: background music and sound effects made on this computer.

Nothing is downloaded and nobody else owns these sounds: each one is synthesized here from a fixed recipe (chords,
a bass line, a soft pluck and, for the livelier moods, a light drum pattern; effects from shaped noise and tones), so
they are free to use in any video, including monetized ones, with no credit line. The same recipe always gives the
same sound, so a file is made once (in the data folder's `library` cache, about 1 to 2 MB each) and stored in a
workspace like any other asset the first time a project uses it.

Music beds are made to loop seamlessly (the release of the last chord is wrapped onto the start), so the editor's
loop plays them under a video of any length. Levels are moderate on purpose: the full mix is measured and normalized
when a video renders, and music dips under speech there.
"""
from __future__ import annotations

import math
import shutil
import tempfile
import threading
import wave
from pathlib import Path

from .. import config

SR = 48000
LIBRARY_VERSION = 1   # part of every file name: a changed recipe never reuses an older file

# semitone offsets from the key's root; "m" marks a minor chord
MUSIC = {
    "calm-1": {"title": "Morning Light", "mood": "calm", "bpm": 70, "root": 57, "prog": [(0, ""), (7, ""), (9, "m"), (5, "")],
               "bars_per_chord": 2, "drums": "none"},
    "calm-2": {"title": "Still Water", "mood": "calm", "bpm": 66, "root": 52, "prog": [(0, "m"), (8, ""), (3, ""), (10, "")],
               "bars_per_chord": 2, "drums": "none"},
    "balanced-1": {"title": "Easy Going", "mood": "balanced", "bpm": 92, "root": 55, "prog": [(0, ""), (9, "m"), (5, ""), (7, "")],
                   "bars_per_chord": 1, "drums": "soft"},
    "balanced-2": {"title": "Open Road", "mood": "balanced", "bpm": 98, "root": 50, "prog": [(0, ""), (7, ""), (5, ""), (5, "")],
                   "bars_per_chord": 1, "drums": "soft"},
    "energetic-1": {"title": "Bright Run", "mood": "energetic", "bpm": 120, "root": 52, "prog": [(0, "m"), (8, ""), (10, ""), (7, "")],
                    "bars_per_chord": 1, "drums": "full"},
    "energetic-2": {"title": "Lift Off", "mood": "energetic", "bpm": 126, "root": 57, "prog": [(0, ""), (5, ""), (9, "m"), (7, "")],
                    "bars_per_chord": 1, "drums": "full"},
}
EFFECTS = {
    "whoosh": {"title": "Whoosh", "use": "a change of scene"},
    "swish": {"title": "Soft swish", "use": "a picture appearing over the video"},
    "pop": {"title": "Pop", "use": "a quick accent"},
    "riser": {"title": "Riser", "use": "building into a title"},
    "hit": {"title": "Soft hit", "use": "landing on a title"},
}
MOODS = ("calm", "balanced", "energetic")
_lock = threading.Lock()


def _np():
    import numpy as np

    return np


def _midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def _tone(freq: float, n: int, harmonics: tuple[float, ...], phase: float = 0.0):
    np = _np()
    t = np.arange(n, dtype=np.float64) / SR
    out = np.zeros(n)
    for k, amp in enumerate(harmonics, 1):
        if amp and freq * k < SR / 2 - 1000:  # band-limited: nothing near Nyquist, so nothing aliases
            out += amp * np.sin(2 * math.pi * freq * k * t + phase * k)
    return out


def _adsr(n: int, attack: float, release: float):
    np = _np()
    env = np.ones(n)
    a, r = min(n, int(attack * SR)), min(n, int(release * SR))
    if a:
        env[:a] = np.linspace(0, 1, a) ** 1.5
    if r:
        env[n - r:] *= np.linspace(1, 0, r) ** 1.5
    return env


def _add(buf, start: int, sig, pan: float = 0.0, wrap: bool = True) -> None:
    """Mix a mono signal into a stereo buffer at `start`, equal-power panned; past the end it wraps (seamless loop)."""
    left, right = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
    total = len(buf)
    start %= total
    while len(sig):
        take = min(len(sig), total - start)
        buf[start:start + take, 0] += sig[:take] * left
        buf[start:start + take, 1] += sig[:take] * right
        if not wrap:
            return
        sig, start = sig[take:], 0


def _noise(n: int, rng):
    return rng.standard_normal(n)


def _onepole(x, coef: float):
    """A gentle one-pole low-pass (coef near 1: darker)."""
    np = _np()
    from itertools import accumulate

    y = list(accumulate(x, lambda prev, v: prev * coef + v * (1 - coef)))
    return np.asarray(y)


def _kick(rng):
    np = _np()
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    freq = 50 + 90 * np.exp(-t * 28)
    phase = 2 * math.pi * np.cumsum(freq) / SR
    return np.sin(phase) * np.exp(-t * 9) * 0.9


def _hat(rng, length: float = 0.05):
    np = _np()
    n = int(length * SR)
    x = _noise(n, rng)
    x = x - _onepole(x, 0.6)  # keep the hiss, lose the rumble
    return x * np.exp(-np.arange(n) / SR * 70) * 0.25


def _clap(rng):
    np = _np()
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    x = _noise(n, rng)
    x = x - _onepole(x, 0.85)
    env = np.exp(-t * 22) + 0.5 * np.exp(-np.maximum(0, t - 0.012) * 40) * (t > 0.012)
    return x * env * 0.35


def _music(recipe: dict):
    """A seamlessly looping stereo bed (float array of shape (n, 2))."""
    np = _np()
    rng = np.random.default_rng(sum(map(ord, recipe["title"])) * 7919)
    kick, clap, hat = _kick(rng), _clap(rng), _hat(rng)  # one of each per bed: the same hit every time
    beat = 60.0 / recipe["bpm"]
    bar = 4 * beat
    seg = bar * recipe["bars_per_chord"]
    prog = recipe["prog"]
    rounds = max(2, round(52 / (seg * len(prog))))  # about 50 s: long enough that a loop is not obvious
    chords = prog * rounds
    total = int(round(seg * len(chords) * SR))
    buf = np.zeros((total, 2))
    root = recipe["root"]
    half = len(chords) // 2
    for c, (offset, quality) in enumerate(chords):
        start = int(round(c * seg * SR))
        n_seg = int(round(seg * SR))
        third = 3 if quality == "m" else 4
        notes = [root + offset, root + offset + third, root + offset + 7, root + offset + 12]
        # pad: soft, slightly detuned left and right, overlapping the next chord by its release
        n_pad = n_seg + int(0.8 * SR)
        env = _adsr(n_pad, 0.6 if recipe["mood"] == "calm" else 0.25, 1.0)
        for k, note in enumerate(notes):
            for side, cents in ((-0.6, -4), (0.6, 4)):
                f = _midi(note) * 2 ** (cents / 1200)
                _add(buf, start, _tone(f, n_pad, (1, 0.35, 0.16, 0.07, 0.03), phase=k * 1.3) * env * 0.045, side)
        # bass: the root, one note per beat pair
        step = 2 * beat
        for b in range(int(seg / step + 0.5)):
            n_b = int(step * SR)
            t = np.arange(n_b) / SR
            sig = _tone(_midi(root + offset - 12), n_b, (1, 0.25, 0.08)) * np.exp(-t * 1.6) * _adsr(n_b, 0.01, 0.15)
            _add(buf, start + int(b * step * SR), np.tanh(sig * 1.6) * 0.14, 0.0)
        # pluck: eighth notes over the chord tones, in the second half (the loop alternates sparser and fuller)
        if c >= half or recipe["mood"] == "energetic":
            pattern = [0, 2, 1, 3, 2, 1, 3, 2]
            n_p = int(beat / 2 * SR)
            for e in range(int(seg / (beat / 2) + 0.5)):
                note = notes[pattern[e % len(pattern)]] + 12
                t = np.arange(n_p * 2) / SR
                sig = _tone(_midi(note), n_p * 2, (1, 0, 0.11, 0, 0.04)) * np.exp(-t * 7) * _adsr(n_p * 2, 0.004, 0.05)
                _add(buf, start + e * n_p, sig * (0.05 if recipe["mood"] == "calm" else 0.065), -0.35 if e % 2 else 0.35)
        # drums
        if recipe["drums"] != "none":
            soft = recipe["drums"] == "soft"
            for bt in range(int(seg / beat + 0.5)):
                at = start + int(bt * beat * SR)
                if bt % 4 in (0, 2) or (not soft and bt % 4 == 3 and c % 2):
                    _add(buf, at, kick * (0.35 if soft else 0.5), 0.0)
                if bt % 4 in (1, 3):
                    _add(buf, at, clap * (0.45 if soft else 0.7), 0.1)
                for half_beat in (0, 1):
                    _add(buf, at + int(half_beat * beat / 2 * SR), hat * (0.5 if soft else 0.8) *
                         (0.7 if half_beat else 1.0), 0.3)
    buf = np.tanh(buf * 1.2) / 1.2
    peak = float(np.max(np.abs(buf))) or 1.0
    return buf * (0.5 / peak)  # about -6 dBFS peak


def _effect(name: str):
    np = _np()
    rng = np.random.default_rng(sum(map(ord, name)) * 104729)
    if name in ("whoosh", "swish"):
        length = 0.9 if name == "whoosh" else 0.45
        n = int(length * SR)
        t = np.arange(n) / SR
        peak_at = length * 0.6
        env = np.where(t < peak_at, (t / peak_at) ** 2.2, np.exp(-(t - peak_at) * (9 if name == "whoosh" else 16)))
        x = _noise(n, rng)
        # a filter that opens towards the peak and closes after it: the "air moving past" sound
        bright = 0.55 + 0.4 * (1 - env)
        y = np.empty(n)
        prev = 0.0
        for k in range(n):
            prev = prev * bright[k] + x[k] * (1 - bright[k])
            y[k] = prev
        y = y - _onepole(y, 0.97)
        sig = y * env
        out = np.zeros((n, 2))
        pan = np.linspace(-0.7, 0.7, n)
        out[:, 0] = sig * np.cos((pan + 1) * math.pi / 4)
        out[:, 1] = sig * np.sin((pan + 1) * math.pi / 4)
    elif name == "pop":
        n = int(0.12 * SR)
        t = np.arange(n) / SR
        freq = 900 * np.exp(-t * 18) + 300
        sig = np.sin(2 * math.pi * np.cumsum(freq) / SR) * np.exp(-t * 38)
        out = np.stack([sig, sig], axis=1)
    elif name == "riser":
        n = int(1.6 * SR)
        t = np.arange(n) / SR
        freq = 180 * 2 ** (t / 1.6 * 2.5)
        tone = np.sin(2 * math.pi * np.cumsum(freq) / SR) * 0.3
        x = _noise(n, rng)
        noise = (x - _onepole(x, 0.9)) * 0.5
        env = (t / 1.6) ** 2 * np.minimum(1, (1.6 - t) / 0.03)
        sig = (tone + noise) * env
        out = np.stack([sig * 0.95, sig], axis=1)
    elif name == "hit":
        n = int(1.2 * SR)
        t = np.arange(n) / SR
        freq = 45 + 70 * np.exp(-t * 14)
        body = np.sin(2 * math.pi * np.cumsum(freq) / SR) * np.exp(-t * 3.5)
        x = _noise(n, rng)
        crack = (x - _onepole(x, 0.8)) * np.exp(-t * 45) * 0.5
        sig = np.tanh((body + crack) * 1.5)
        out = np.stack([sig, sig], axis=1)
    else:
        raise KeyError(name)
    peak = float(np.max(np.abs(out))) or 1.0
    return out * (0.7 / peak)


def _write_wav(path: Path, data) -> None:
    np = _np()
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def cache_dir() -> Path:
    d = config.data_dir() / "library"
    d.mkdir(parents=True, exist_ok=True)
    return d


def filename(key: str) -> str:
    if key in MUSIC:
        r = MUSIC[key]
        return f"ClipForge music - {r['title']} ({r['mood']}).m4a"
    return f"ClipForge effect - {EFFECTS[key]['title']}.m4a"


def make(key: str) -> Path:
    """The library file for `key`, made once and cached (the same recipe always gives the same sound)."""
    if key not in MUSIC and key not in EFFECTS:
        raise KeyError(f"Unknown library sound {key}")
    out = cache_dir() / f"v{LIBRARY_VERSION}-{key}.m4a"
    if out.is_file() and out.stat().st_size > 0:
        return out
    with _lock:
        if out.is_file() and out.stat().st_size > 0:
            return out
        from ..pipeline.ffmpeg_utils import run

        data = _music(MUSIC[key]) if key in MUSIC else _effect(key)
        with tempfile.TemporaryDirectory(dir=cache_dir()) as tmp:
            wav = Path(tmp) / "sound.wav"
            _write_wav(wav, data)
            enc = Path(tmp) / "sound.m4a"
            run(["-i", str(wav), "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2", "-movflags", "+faststart",
                 str(enc)], duration=len(data) / SR)
            enc.replace(out)
    return out


def asset(workspace_id: str, key: str, project_id: str = "") -> dict:
    """The library sound as an ordinary private asset of this workspace (stored once per content), for the project
    `project_id` (a sound stored already is handed out again to it: uploads.store_file)."""
    from . import uploads

    src = make(key)
    with tempfile.TemporaryDirectory(dir=cache_dir()) as tmp:
        copy = Path(tmp) / filename(key)
        shutil.copyfile(src, copy)
        return uploads.store_file(workspace_id, copy, filename(key), project_id=project_id)


def music_key(mood: str, seed: str = "") -> str:
    """One of the mood's beds, chosen by `seed` (a project id) so neighbouring projects do not all sound the same."""
    mood = mood if mood in MOODS else "balanced"
    keys = sorted(k for k, r in MUSIC.items() if r["mood"] == mood)
    return keys[sum(map(ord, seed)) % len(keys)] if seed else keys[0]


def catalog() -> dict:
    return {"music": [{"key": k, "title": r["title"], "mood": r["mood"], "bpm": r["bpm"]} for k, r in MUSIC.items()],
            "effects": [{"key": k, **v} for k, v in EFFECTS.items()],
            "license": "Made by ClipForge on this computer. Free to use in any video, including monetized ones; "
                       "no credit needed."}

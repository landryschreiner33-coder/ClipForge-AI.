"""ClipForge AI listens to the voice (docs/clipforge/SMARTER_AI.md).

Word lists hear what is said; this module hears how it is said, from the 16 kHz copy made for transcription and with
numpy alone (no model, no download): the pitch of the voice in every 20 ms, how much it moves (a flat voice loses
viewers; a voice that rises and falls holds them), the moments where pitch and loudness jump together (emphasis: the
word the speaker leans on), laughter-like bursts (loud stretches without words whose loudness pulses 3-8 times a
second), and the pauses before the last lines (comic timing).

Used by the deep clip analysis (a bounded, explained part of the Clip Score and the stored `prosody` of a clip) and
by the smart editor (punch-ins land on an emphasis instead of on every other cut). Every number is an estimate from
the sound alone and is labelled as such.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np

from .audio import read_samples

log = logging.getLogger("clipfoundry.pipeline.ears")

SR = 16000
FRAME = 640            # 40 ms
HOP = 320              # 20 ms
F_LO, F_HI = 70.0, 400.0
VOICED_MIN = 0.45      # autocorrelation peak a frame needs to count as a pitched (voiced) frame
EMPHASIS_ST = 3.0      # semitones above the speaker's usual pitch
EMPHASIS_Z = 0.8       # ... together with loudness this far above the speaker's usual level
BLOCK_S = 60.0
VERSION = 1


def _frames(x: np.ndarray) -> np.ndarray:
    n = 1 + max(0, (len(x) - FRAME) // HOP)
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    return x[idx]


def pitch_track(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(semitones relative to 100 Hz or NaN for unvoiced, loudness in dB, voicing strength) per 20 ms frame."""
    if len(x) < FRAME:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    fr = _frames(x.astype(np.float32))
    fr = fr - fr.mean(axis=1, keepdims=True)
    rms = np.sqrt((fr ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    win = np.hanning(FRAME).astype(np.float32)
    spec = np.fft.rfft(fr * win, n=2 * FRAME, axis=1)
    acf = np.fft.irfft(np.abs(spec) ** 2, axis=1)[:, :FRAME]
    acf = acf / (acf[:, :1] + 1e-9)
    lo, hi = int(SR / F_HI), int(SR / F_LO)
    seg = acf[:, lo:hi + 1]
    lag = seg.argmax(axis=1) + lo
    strength = seg.max(axis=1)
    f0 = SR / lag
    semis = 12 * np.log2(f0 / 100.0)
    semis = np.where(strength >= VOICED_MIN, semis, np.nan)
    return semis, db, strength


def analyze(x: np.ndarray, start: float = 0.0, words: list[dict] | None = None) -> dict:
    """Prosody of one stretch of sound (`start` is where it begins in the recording, for the times reported)."""
    semis, db, strength = pitch_track(x)
    n = len(db)
    if n < 10:
        return {"frames": n, "voiced_share": 0.0, "pitch_semitones_std": 0.0, "pitch_range_semitones": 0.0,
                "pitch_variation": 0.0, "emphasis_times": [], "emphasis_per_30s": 0.0, "laughter_like": 0,
                "laughter_seconds": 0.0, "pause_before_end_s": 0.0, "monotone": False, "score": 0.5,
                "estimated": ["everything here is estimated from the sound alone"]}
    t = start + (np.arange(n) * HOP + FRAME / 2) / SR
    speech = db > (np.percentile(db, 90) - 25.0)  # the speaker's own level decides what counts as sound
    if words:
        covered = np.zeros(n, dtype=bool)
        for w in words:
            a = int(max(0, (w["start"] - start) * SR - FRAME / 2) // HOP)
            b = int(max(0, (w["end"] - start) * SR) // HOP) + 1
            covered[a:min(n, b)] = True
    else:
        covered = speech
    voiced = ~np.isnan(semis) & speech & covered
    voiced_share = float(voiced.mean())
    pv = semis[voiced]
    if len(pv) >= 8:
        med = float(np.median(pv))
        mad = float(np.median(np.abs(pv - med))) * 1.4826
        std = float(min(mad, np.std(pv)))
        rng = float(np.percentile(pv, 90) - np.percentile(pv, 10))
    else:
        med, std, rng = 0.0, 0.0, 0.0
    # emphasis: pitch and loudness up together, grouped into moments at least a second apart
    loud_ref = db[speech] if speech.any() else db
    z = (db - float(np.median(loud_ref))) / (float(np.std(loud_ref)) + 1e-6)
    hits = voiced & (semis >= med + EMPHASIS_ST) & (z >= EMPHASIS_Z) if len(pv) >= 8 else np.zeros(n, dtype=bool)
    emphasis: list[float] = []
    for k in np.flatnonzero(hits):
        if not emphasis or t[k] - emphasis[-1] >= 1.0:
            emphasis.append(round(float(t[k]), 2))
    dur = n * HOP / SR
    # laughter-like: stretches without words that are loud on the whole and whose loudness pulses 3-8 times a
    # second (laughter is a train of bursts, so the stretch itself is not steadily loud)
    laughs, laugh_s = 0, 0.0
    if words:
        free = ~covered
        k = 0
        while k < n:
            if not free[k]:
                k += 1
                continue
            j = k
            while j < n and free[j]:
                j += 1
            length = (j - k) * HOP / SR
            level = 20 * np.log10(float(np.mean(10 ** (db[k:j] / 20))) + 1e-9)  # the stretch's level as a whole
            if length >= 0.4 and j - k >= 16 and level > float(np.median(loud_ref)) - 10.0:
                env = 10 ** (db[k:j] / 20)
                env = env - env.mean()
                spec = np.abs(np.fft.rfft(env * np.hanning(len(env))))
                freqs = np.fft.rfftfreq(len(env), HOP / SR)
                band = spec[(freqs >= 3.0) & (freqs <= 8.0)].sum()
                total = spec[freqs > 0.5].sum() + 1e-9
                if band / total >= 0.35:
                    laughs += 1
                    laugh_s += length
            k = j
    # the pause before the last lines (comic timing): the longest gap between words in the final third
    pause_end = 0.0
    if words:
        tail = [w for w in words if w["start"] >= start + 0.67 * dur]
        for a, b in zip(tail, tail[1:]):
            pause_end = max(pause_end, b["start"] - a["end"])
    pitch_var = max(0.0, min(1.0, std / 3.5))
    per30 = len(emphasis) / max(0.5, dur / 30.0)
    monotone = bool(len(pv) >= 8 and std < 1.2 and float(np.std(db[speech])) < 3.0) if speech.any() else False
    score = (0.45 * pitch_var + 0.25 * min(1.0, per30 / 2.0) + 0.20 * min(1.0, laughs / 1.0)
             + 0.10 * (0.0 if monotone else 1.0))
    return {"frames": n, "voiced_share": round(voiced_share, 3), "pitch_semitones_std": round(std, 2),
            "pitch_range_semitones": round(rng, 2), "pitch_variation": round(pitch_var, 3),
            "emphasis_times": emphasis[:60], "emphasis_per_30s": round(per30, 2), "laughter_like": laughs,
            "laughter_seconds": round(laugh_s, 1), "pause_before_end_s": round(pause_end, 2), "monotone": monotone,
            "score": round(score, 3), "estimated": ["everything here is estimated from the sound alone"]}


def clip_prosody(wav_path: Path | str | None, start: float, end: float, words: list[dict] | None) -> dict | None:
    """Prosody of a clip's range, read straight from the 16 kHz file (None when there is no file)."""
    if not wav_path or not Path(wav_path).is_file():
        return None
    try:
        x = read_samples(Path(wav_path), start, end)
    except (OSError, ValueError, EOFError) as exc:
        log.warning("prosody: %s", exc)
        return None
    inside = [w for w in (words or []) if w["end"] > start and w["start"] < end]
    return analyze(x, start, inside)


def emphasis_points(wav_path: Path | str | None, words: list[dict] | None, cache: Path | None = None) -> list[float]:
    """Every emphasis moment of a whole recording (seconds), computed in one-minute blocks and cached as JSON."""
    if not wav_path or not Path(wav_path).is_file():
        return []
    wav = Path(wav_path)
    key = {"version": VERSION, "size": wav.stat().st_size, "mtime": int(wav.stat().st_mtime)}
    if cache and cache.is_file():
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved.get("key") == key:
                return [float(t) for t in saved.get("emphasis", [])]
        except (OSError, ValueError):
            pass
    import wave
    try:
        with wave.open(str(wav), "rb") as wf:
            total = wf.getnframes() / wf.getframerate()
    except (OSError, wave.Error):
        return []
    out: list[float] = []
    t0 = 0.0
    while t0 < total:
        t1 = min(total, t0 + BLOCK_S)
        try:
            x = read_samples(wav, max(0.0, t0 - 0.5), t1)
        except (OSError, ValueError, EOFError):
            break
        inside = [w for w in (words or []) if w["end"] > t0 - 0.5 and w["start"] < t1]
        res = analyze(x, max(0.0, t0 - 0.5), inside)
        out += [t for t in res["emphasis_times"] if t >= t0 and (not out or t - out[-1] >= 1.0)]
        t0 = t1
    if cache:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"key": key, "emphasis": out}), encoding="utf-8")
        except OSError:
            pass
    return out


def semitones(f0: float) -> float:
    return 12 * math.log2(max(1.0, f0) / 100.0)

"""What the Viral Predictor measures: a clip's picture, sound and words, half a second at a time.

Two ways in:

* `measure_file` reads a finished video file (a rendered clip, an alternative version, or any video the owner drops on
  the Viral Predictor page): every frame at `reference_analysis.SCAN_FPS` for movement and cuts, one still per half
  second (at most MAX_STILLS) for faces and on-screen text, and the whole sound track for loudness, sudden sounds,
  speech, emphasis and laughter.
* `from_source` builds the same signals for a moment of a longer recording while clips are being picked, before
  anything is rendered: words and loudness only (the picture is not measured yet, and the prediction says so).

Everything is measured on this computer with FFmpeg, numpy and OpenCV. No model watches or hears the video here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from ..pipeline import ears
from ..pipeline.ffmpeg_utils import probe as probe_file
from ..studio import reference_analysis as ra

BIN = 0.5                 # seconds per measurement bin
MAX_STILLS = 180          # stills read for faces and on-screen text (one per bin up to 90 s, then spread out)
MAX_SECONDS = 15 * 60     # a longer file is measured over its first 15 minutes
SILENT_DB = -50.0         # a bin quieter than this has no sound worth hearing
REACTION_Z = 1.0          # loud without words: this many standard deviations above the speech level...
REACTION_MIN = 0.4        # ...for at least this long (laughter, a shout, a crowd)
REACTION_DB = 3.0         # ...and at least 3 dB louder than the median speech

Progress = Callable[[float, str], None]


class MeasureError(ValueError):
    """The file cannot be measured (no picture, unreadable)."""


@dataclass
class Signals:
    """Per-bin measurements of one clip, in the clip's own time (0 = its first frame)."""

    duration: float
    n: int
    speech: np.ndarray                     # share of each bin with someone speaking (0-1)
    words: list[dict] = field(default_factory=list)   # {"w", "start", "end"} in clip time
    motion: np.ndarray | None = None       # mean pixel change between frames (0-1 of full scale)
    cuts: np.ndarray | None = None         # cuts, dissolves and fades starting in each bin
    luma: np.ndarray | None = None         # brightness (0-1)
    face: np.ndarray | None = None         # height of the largest face, share of the frame height (nan: no still)
    text: np.ndarray | None = None         # 1 when a line of on-screen text was seen (nan: no still)
    level: np.ndarray | None = None        # sound level, dBFS (None: no sound track)
    onsets: np.ndarray | None = None       # sudden sounds starting in each bin
    emphasis: list[float] = field(default_factory=list)       # times the voice rises in pitch and loudness
    reactions: list[tuple[float, float]] = field(default_factory=list)  # loud stretches without words
    monotone: bool | None = None
    meta: dict = field(default_factory=dict)

    @property
    def has_picture(self) -> bool:
        return self.motion is not None

    @property
    def has_sound(self) -> bool:
        return self.level is not None

    def times(self) -> np.ndarray:
        return (np.arange(self.n) + 0.5) * BIN


def bins_for(duration: float) -> int:
    return max(1, int(math.ceil(max(0.0, duration) / BIN - 1e-9)))


def speech_share(words: list[dict], n: int, pad: float = 0.12) -> np.ndarray:
    """Share of each bin covered by words (a word's sound runs a little past its timestamps)."""
    out = np.zeros(n)
    for w in words:
        a, b = max(0.0, float(w["start"]) - pad), float(w["end"]) + pad
        k0, k1 = int(a // BIN), min(n - 1, int(b // BIN))
        for k in range(k0, k1 + 1):
            lo, hi = k * BIN, (k + 1) * BIN
            out[k] += max(0.0, min(b, hi) - max(a, lo)) / BIN
    return np.clip(out, 0.0, 1.0)


def _bin_mean(times: np.ndarray, values: np.ndarray, n: int) -> np.ndarray:
    out = np.full(n, np.nan)
    if not len(times):
        return out
    idx = np.clip((times // BIN).astype(int), 0, n - 1)
    sums, counts = np.zeros(n), np.zeros(n)
    np.add.at(sums, idx, values)
    np.add.at(counts, idx, 1)
    has = counts > 0
    out[has] = sums[has] / counts[has]
    return out


def _fill(arr: np.ndarray, default: float = 0.0) -> np.ndarray:
    """Bins without a sample take their nearest neighbour's value."""
    out = arr.copy()
    good = np.flatnonzero(~np.isnan(out))
    if not len(good):
        return np.full(len(out), default)
    for k in np.flatnonzero(np.isnan(out)):
        out[k] = out[good[np.argmin(np.abs(good - k))]]
    return out


def level_bins(db: np.ndarray, hop: float, n: int, offset: float = 0.0) -> np.ndarray:
    """Per-bin sound level (dBFS) from a level envelope with frames every `hop` seconds starting at `offset`: the
    mean energy of each bin, so a loud word is not averaged away in decibels."""
    t = offset + np.arange(len(db)) * hop
    energy = 10 ** (np.asarray(db, dtype=float) / 10)
    keep = (t >= 0) & (t < n * BIN)
    lv = _bin_mean(t[keep], energy[keep], n)
    lv = _fill(lv, 1e-9)
    return 10 * np.log10(np.maximum(lv, 1e-9))


def reactions_from(level_db: np.ndarray, hop: float, words: list[dict], speech_mask: np.ndarray | None = None
                   ) -> list[tuple[float, float]]:
    """Loud stretches without words (laughter, a shout, a crowd): louder than the speech by REACTION_Z standard
    deviations and REACTION_DB decibels, for at least REACTION_MIN seconds. An estimate from loudness alone."""
    db = np.asarray(level_db, dtype=float)
    if len(db) < 4:
        return []
    t = np.arange(len(db)) * hop
    covered = np.zeros(len(db), dtype=bool)
    for w in words:
        covered |= (t >= float(w["start"]) - 0.05) & (t < float(w["end"]) + 0.05)
    if speech_mask is not None and len(speech_mask) == len(db):
        covered |= speech_mask
    ref = db[covered] if covered.sum() >= 20 else db[db > SILENT_DB]
    if len(ref) < 10:
        return []
    above = db - float(np.median(ref))
    z = above / (float(np.std(ref)) or 1.0)
    hot = (z > REACTION_Z) & (above >= REACTION_DB) & ~covered
    out, run = [], None
    for k, h in enumerate(list(hot) + [False]):
        if h and run is None:
            run = k
        elif not h and run is not None:
            if (k - run) * hop >= REACTION_MIN:
                out.append((round(run * hop, 2), round(k * hop, 2)))
            run = None
    return out


# ------------------------------------------------------------------ a finished file
def _faces_and_text(path: Path, probe: dict, dur: float, n: int, cancelled) -> tuple[np.ndarray, np.ndarray, int]:
    """Largest face height and on-screen text per bin, from one still per bin (spread out past MAX_STILLS)."""
    from ..pipeline import reframe

    face = np.full(n, np.nan)
    text = np.full(n, np.nan)
    centres = [(k + 0.5) * BIN for k in range(n) if (k + 0.5) * BIN < dur - 0.05]
    if len(centres) > MAX_STILLS:
        idx = np.linspace(0, len(centres) - 1, MAX_STILLS).round().astype(int)
        centres = [centres[i] for i in sorted(set(idx.tolist()))]
    stills = ra.read_stills(path, probe, [(0.0, dur)], centres, cancelled)
    det = None
    for t, img in stills:
        k = min(n - 1, int(t // BIN))
        h, w = img.shape[:2]
        if det is None:
            det = reframe._detector(w, h) or False  # noqa: SLF001 - the app's one face detector (YuNet)
        biggest = 0.0
        if det:
            try:
                _, found = det.detect(np.repeat(img[:, :, None], 3, axis=2))
            except Exception:  # noqa: BLE001 - a still the detector cannot read counts as no face
                found = None
            for f in found if found is not None else []:
                biggest = max(biggest, float(f[3]) / h)
        face[k] = biggest if det else np.nan
        text[k] = 1.0 if ra.text_band(img) else 0.0
    return face, text, len(stills)


def measure_file(path: str | Path, words: list[dict] | None = None, *, cancelled: Callable[[], bool] | None = None,
                 progress: Progress | None = None, probe: dict | None = None) -> Signals:
    """Measure a finished video file. `words` are the words heard in it, in its own time (None: speech is estimated
    from the sound)."""
    path = Path(path)
    step = progress or (lambda f, m: None)
    probe = probe or probe_file(path)
    if not probe.get("width"):
        raise MeasureError("This file has no picture to measure.")
    dur = float(probe.get("video_duration") or probe.get("duration") or 0.0)
    if dur < 1.0:
        raise MeasureError("This video is shorter than a second.")
    measured = min(dur, MAX_SECONDS)
    n = bins_for(measured)
    words = sorted((dict(w) for w in words or [] if float(w["start"]) < measured), key=lambda w: float(w["start"]))
    step(0.05, "Watching the picture frame by frame")
    scan = ra.scan_pictures(path, probe, [(0.0, measured)], cancelled,
                            lambda f, m: step(0.05 + 0.45 * f, "Watching the picture frame by frame"))
    r0 = scan["ranges"][0]
    times = r0["times"]
    joins = ra.find_joins(r0)
    cut_t = np.array([j["t"] for j in joins])
    cut_frames = {int(round((j["t"] - 0.0) * ra.SCAN_FPS)) for j in joins}
    keep = np.array([int(round(t * ra.SCAN_FPS)) not in cut_frames for t in times], dtype=bool) if len(times) \
        else np.zeros(0, dtype=bool)
    motion = _fill(_bin_mean(times[keep], r0["dpix"][keep], n)) if len(times) else np.zeros(n)
    luma = _fill(_bin_mean(times, r0["luma"], n), 0.5) if len(times) else np.full(n, 0.5)
    cuts = np.zeros(n)
    for t in cut_t:
        cuts[min(n - 1, int(t // BIN))] += 1
    step(0.52, "Looking for faces and on-screen text")
    face, text, stills = _faces_and_text(path, probe, measured, n, cancelled)
    sig = Signals(duration=round(measured, 3), n=n, speech=np.zeros(n), words=words, motion=motion, cuts=cuts,
                  luma=luma, face=face, text=text)
    sig.meta = {"source": "file", "width": int(probe.get("width") or 0), "height": int(probe.get("height") or 0),
                "fps": probe.get("fps"), "has_audio": bool(probe.get("has_audio")), "frames": int(len(times)),
                "stills": stills, "file_seconds": round(dur, 2), "measured_seconds": round(measured, 2),
                "speech_source": "transcript" if words else "none"}
    if probe.get("has_audio"):
        step(0.75, "Listening to the sound")
        x = ra.read_audio(path, [(0.0, measured)], cancelled)[0]
        bands = ra._bands(x)  # noqa: SLF001 - the example analyzer's 50 ms level and voice-band split
        hop = ra.HOP / ra.SR
        level = np.asarray(bands["level"], dtype=float)
        if len(level):
            sig.level = level_bins(level, hop, n)
            if words:
                sig.speech = speech_share(words, n)
                spans = None
            else:
                spans = ra.estimate_speech(bands)
                share = np.zeros(n)
                for a, b in spans:
                    share += speech_share([{"start": a, "end": b}], n, pad=0.0)
                sig.speech = np.clip(share, 0.0, 1.0)
                sig.meta["speech_source"] = "estimate" if spans else "none"
            snd = ra.sound(x, [(float(w["start"]), float(w["end"])) for w in words] if words else spans or [], 0.0)
            onsets = np.zeros(n)
            for t in snd.get("onsets") or []:
                if t < measured:
                    onsets[min(n - 1, int(t // BIN))] += 1
            sig.onsets = onsets
            mask = None
            if not words and spans:
                tt = np.arange(len(level)) * hop
                mask = np.zeros(len(level), dtype=bool)
                for a, b in spans:
                    mask |= (tt >= a) & (tt < b)
            sig.reactions = reactions_from(level, hop, words, mask)
            pros = ears.analyze(x, 0.0, words or None)
            sig.emphasis = [float(t) for t in pros.get("emphasis_times") or [] if t < measured]
            sig.monotone = bool(pros.get("monotone")) if pros.get("frames", 0) >= 10 and (words or spans) else None
    step(0.95, "Measured")
    return sig


# ------------------------------------------------------------------ a moment of a longer recording (not rendered)
def from_source(start: float, end: float, words_all: list[dict], loud, emphasis: list[float] | None = None
                ) -> Signals:
    """The same signals for the moment [start, end) of a recording while clips are picked: its words and its
    loudness (`audio.Loudness`). The picture is not measured here."""
    dur = max(0.5, float(end) - float(start))
    n = bins_for(dur)
    words = [{"w": w["w"], "start": max(0.0, float(w["start"]) - start), "end": min(dur, float(w["end"]) - start),
              **({"p": w["p"]} if w.get("p") is not None else {})}
             for w in words_all if float(w["end"]) > start and float(w["start"]) < end]
    sig = Signals(duration=round(dur, 3), n=n, speech=speech_share(words, n), words=words)
    hop = float(loud.hop)
    a, b = loud._idx(start), loud._idx(end)  # noqa: SLF001
    db = np.asarray(loud.db[a:b], dtype=float)
    if len(db) >= 2:
        sig.level = level_bins(db, hop, n, offset=a * hop - start)
        # sudden sounds: a jump of 6 dB or more from one 0.1 s frame to the next, at least 0.3 s apart
        onsets = np.zeros(n)
        last = -1e9
        for k in range(1, len(db)):
            t = k * hop + a * hop - start
            if db[k] - db[k - 1] >= 6.0 and db[k] > SILENT_DB and t - last >= 0.3 and 0 <= t < dur:
                onsets[min(n - 1, int(t // BIN))] += 1
                last = t
        sig.onsets = onsets
        sig.reactions = [(round(x + a * hop - start, 2), round(y + a * hop - start, 2))
                         for x, y in reactions_from(db, hop, [{"start": w["start"] - (a * hop - start),
                                                              "end": w["end"] - (a * hop - start)} for w in words])]
    sig.emphasis = [float(t) - start for t in emphasis or [] if start <= float(t) < end]
    sig.meta = {"source": "recording", "has_audio": sig.level is not None,
                "speech_source": "transcript" if words else "none"}
    return sig

"""Measure an example video: its cuts and joins, framing, on-screen captions, speech, pauses and sound levels.

Everything here is measured on this computer from decoded frames and audio samples (FFmpeg and numpy). Nothing is
sent anywhere, and nothing here claims that a model watched or heard the video. Readings that rest on a heuristic
(captions found from on-screen text edges, speech found from sound when there is no transcript, music level under
speech in a finished mix) are labelled estimates with a confidence, separately from direct measurements.

Coverage is honest about sampling: every frame at SCAN_FPS frames per second of each selected range is compared to
find cuts, dissolves and fades; framing and captions are read from a bounded set of stills (one in the middle of
each shot plus one every COVER_EVERY_S seconds of long shots); the sound of the whole selected range is read.
"""
from __future__ import annotations

import math
import statistics
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

from ..pipeline.ffmpeg_utils import NO_WINDOW, ffmpeg_bin

ANALYZER = "measure-1"           # bump when a measurement changes: cached analyses are keyed by it
SCAN_FPS = 10
SCAN_W = 48
STILL_W = 320
MAX_STILLS = 160
COVER_EVERY_S = 8.0
MAX_ANALYZE_S = 30 * 60          # the selected ranges together
MAX_RANGES = 8
MIN_RANGE_S = 1.0
SR = 16000
HOP = SR // 20                   # 50 ms audio frames
SILENCE_DB = -48.0
ASPECTS = ("overall", "pacing", "captions", "framing", "sound")
RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5}
METHOD = ("Measured on this computer from the video's frames and sound (FFmpeg). No AI model watched or heard this "
          "video.")


class Canceled(Exception):
    pass


class AnalysisError(ValueError):
    pass


Progress = Callable[[float, str], None]
Cancelled = Callable[[], bool]


def _check(cancelled: Cancelled | None) -> None:
    if cancelled and cancelled():
        raise Canceled()


def clean_ranges(ranges: list | None, duration_s: float) -> list[tuple[float, float]]:
    """The time ranges to analyze, in seconds of the example's own timeline; none means the whole video."""
    if duration_s <= 0:
        raise AnalysisError("This video has no readable length.")
    if not ranges:
        if duration_s > MAX_ANALYZE_S:
            raise AnalysisError(f"This example is {duration_s / 60:.0f} min long. Choose up to "
                                f"{MAX_ANALYZE_S // 60} min of it to analyze.")
        return [(0.0, duration_s)]
    if not isinstance(ranges, list) or len(ranges) > MAX_RANGES:
        raise AnalysisError(f"Choose at most {MAX_RANGES} parts of the example.")
    out = []
    for r in ranges:
        try:
            a, b = float(r["start_ms"]) / 1000, float(r["end_ms"]) / 1000
        except (KeyError, TypeError, ValueError):
            raise AnalysisError("Each part needs a start and an end.") from None
        if not (math.isfinite(a) and math.isfinite(b)) or a < 0 or b > duration_s + 0.05 or b - a < MIN_RANGE_S:
            raise AnalysisError(f"Each part must be at least {MIN_RANGE_S:g} s long and inside the video "
                                f"(0 to {duration_s:.1f} s).")
        out.append((round(a, 3), round(min(b, duration_s), 3)))
    out.sort()
    if any(out[i][0] < out[i - 1][1] for i in range(1, len(out))):
        raise AnalysisError("The parts overlap. Choose separate parts.")
    if sum(b - a for a, b in out) > MAX_ANALYZE_S:
        raise AnalysisError(f"Choose at most {MAX_ANALYZE_S // 60} min of the example in total.")
    return out


# ------------------------------------------------------------------ pictures: cuts, dissolves, fades
def _frames(path: Path, start: float, length: float, vf: str, frame_bytes: int, cancelled: Cancelled | None):
    """Decoded raw frames of one range, streamed (never the whole video in memory). Frames pass through as the
    filters produce them (no duplicates to keep a constant rate)."""
    cmd = [ffmpeg_bin(), "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path),
           "-map", "0:v:0", "-an", "-sn", "-vf", vf, "-fps_mode", "passthrough", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    try:
        n = 0
        while True:
            buf = proc.stdout.read(frame_bytes)  # type: ignore[union-attr]
            if len(buf) < frame_bytes:
                break
            yield buf
            n += 1
            if n % 40 == 0:
                _check(cancelled)
    finally:
        proc.kill()
        proc.wait()


def _size(probe: dict, width: int) -> tuple[int, int]:
    w, h = int(probe.get("width") or 0), int(probe.get("height") or 0)
    rot = abs(int(float(probe.get("rotation") or 0))) % 180 == 90
    if rot:
        w, h = h, w
    if w <= 0 or h <= 0:
        raise AnalysisError("This file has no readable picture.")
    return width, max(2, int(round(h * width / w / 2)) * 2)


def scan_pictures(path: Path, probe: dict, ranges: list[tuple[float, float]], cancelled: Cancelled | None = None,
                  progress: Progress | None = None) -> dict:
    """Compare every frame (at SCAN_FPS) with the one before: per-frame times (source timeline), brightness, and
    picture/colour change. Returns arrays per range."""
    w, h = _size(probe, SCAN_W)
    total = sum(b - a for a, b in ranges)
    done = 0.0
    out = []
    for a, b in ranges:
        times, luma, dpix, dhist, hists = [], [], [], [], []
        prev = None
        prev_hist = None
        vf = f"fps={SCAN_FPS},scale={w}:{h}:flags=area,format=rgb24"
        for k, buf in enumerate(_frames(path, a, b - a, vf, w * h * 3, cancelled)):
            f = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3).astype(np.float32)
            hist = np.concatenate([np.histogram(f[..., c], bins=16, range=(0, 256))[0] for c in range(3)])
            hist = hist / max(1.0, float(hist.sum()))
            times.append(a + k / SCAN_FPS)
            luma.append(float((0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]).mean()) / 255)
            dpix.append(0.0 if prev is None else float(np.abs(f - prev).mean()) / 255)
            dhist.append(0.0 if prev_hist is None else float(np.abs(hist - prev_hist).sum()) / 2)
            hists.append(hist.astype(np.float32))
            prev, prev_hist = f, hist
            if progress and k % 50 == 0:
                progress(min(1.0, (done + k / SCAN_FPS) / total), "Comparing frames to find cuts")
        done += b - a
        out.append({"range": (a, b), "times": np.array(times), "luma": np.array(luma), "dpix": np.array(dpix),
                    "dhist": np.array(dhist), "hists": np.array(hists) if hists else np.zeros((0, 48))})
    return {"ranges": out, "size": (w, h)}


def _mad(x: np.ndarray) -> tuple[float, float]:
    if not len(x):
        return 0.0, 0.0
    med = float(np.median(x))
    return med, float(np.median(np.abs(x - med)))


def find_joins(scan: dict) -> list[dict]:
    """Cuts (one big change), dissolves (several gradual changes adding up to a big one) and fades (through black)
    found in the per-frame changes of one range."""
    times, luma, dpix, dhist, hists = (scan[k] for k in ("times", "luma", "dpix", "dhist", "hists"))
    n = len(times)
    if n < 3:
        return []
    med, mad = _mad(dpix[1:])
    cut_t = max(0.09, med + 8 * mad)
    joins: list[dict] = []
    dark = luma < 0.06
    used = np.zeros(n, dtype=bool)
    # fades: a dark run with brighter pictures on both sides
    i = 0
    while i < n:
        if dark[i]:
            j = i
            while j + 1 < n and dark[j + 1]:
                j += 1
            if i > 0 and j < n - 1:
                joins.append({"t": float((times[i] + times[j]) / 2), "kind": "fade", "start": float(times[i - 1]),
                              "end": float(times[j + 1])})
                used[max(0, i - 3):min(n, j + 4)] = True
            i = j + 1
        else:
            i += 1
    for i in range(1, n):
        if used[i]:
            continue
        if dpix[i] >= cut_t and dhist[i] >= 0.12 and dpix[i] >= 2.0 * max(dpix[i - 1], dpix[i + 1] if i + 1 < n
                                                                          else 0.0):
            joins.append({"t": float((times[i - 1] + times[i]) / 2), "kind": "cut", "start": float(times[i - 1]),
                          "end": float(times[i])})
            used[i] = True
    # dissolves: runs of >= 3 moderate changes whose start and end pictures differ like a cut
    soft = max(0.02, med + 3 * mad)
    i = 1
    while i < n:
        if not used[i] and soft <= dpix[i] < cut_t:
            j = i
            while j + 1 < n and not used[j + 1] and soft <= dpix[j + 1] < cut_t:
                j += 1
            if j - i + 1 >= 3:
                before, after = hists[i - 1], hists[min(n - 1, j)]
                if float(np.abs(before - after).sum()) / 2 >= 0.3 and dpix[i:j + 1].max() < 0.6 * dpix[i:j + 1].sum():
                    joins.append({"t": float((times[i - 1] + times[j]) / 2), "kind": "dissolve",
                                  "start": float(times[i - 1]), "end": float(times[j])})
                    used[i:j + 1] = True
            i = j + 1
        else:
            i += 1
    joins.sort(key=lambda j: j["t"])
    merged: list[dict] = []
    for j in joins:  # one join per 0.3 s at most (a cut inside a fade is the same join)
        if merged and j["t"] - merged[-1]["t"] < 0.3:
            continue
        merged.append(j)
    return merged


def shots(joins: list[dict], ranges: list[tuple[float, float]]) -> list[dict]:
    out = []
    for a, b in ranges:
        cuts = [j["t"] for j in joins if a < j["t"] < b]
        edges = [a, *cuts, b]
        for k in range(len(edges) - 1):
            out.append({"start": edges[k], "end": edges[k + 1], "partial": k == 0 or k == len(edges) - 2})
    return out


def pick_stills(shot_list: list[dict]) -> list[float]:
    """One still in the middle of each shot, plus one every COVER_EVERY_S seconds of long shots (bounded)."""
    times = []
    for s in shot_list:
        length = s["end"] - s["start"]
        if length < 0.2:
            continue
        if length <= COVER_EVERY_S:
            times.append(s["start"] + length / 2)
        else:
            k = int(length // COVER_EVERY_S) + 1
            times += [s["start"] + length * (i + 0.5) / k for i in range(k)]
    if len(times) > MAX_STILLS:
        idx = np.linspace(0, len(times) - 1, MAX_STILLS).round().astype(int)
        times = [times[i] for i in sorted(set(idx))]
    return times


def read_stills(path: Path, probe: dict, ranges: list[tuple[float, float]], times: list[float],
                cancelled: Cancelled | None = None) -> list[tuple[float, np.ndarray]]:
    """Grey stills at the chosen times: one decode of each range, keeping only the chosen frames."""
    w, h = _size(probe, STILL_W)
    out = []
    for a, b in ranges:
        wanted = sorted({int(round((t - a) * SCAN_FPS)) for t in times if a <= t < b})
        if not wanted:
            continue
        expr = "+".join(f"eq(n\\,{i})" for i in wanted)
        vf = f"fps={SCAN_FPS},select='{expr}',scale={w}:{h}:flags=area,format=gray"
        for k, buf in enumerate(_frames(path, a, b - a, vf, w * h, cancelled)):
            if k >= len(wanted):
                break
            out.append((a + wanted[k] / SCAN_FPS, np.frombuffer(buf, dtype=np.uint8).reshape(h, w)))
    return out


# ------------------------------------------------------------------ stills: framing and on-screen text
def bars(img: np.ndarray) -> dict:
    """Black bars: the share of rows (top/bottom) and columns (left/right) that are flat and near black."""
    f = img.astype(np.float32)

    def run(lines: np.ndarray) -> int:
        k = 0
        for row in lines:
            if row.mean() < 20 and row.std() < 8:
                k += 1
            else:
                break
        return k

    h, w = f.shape
    return {"top": run(f) / h, "bottom": run(f[::-1]) / h, "left": run(f.T) / w, "right": run(f.T[::-1]) / w}


def blurred_margins(img: np.ndarray) -> bool:
    """A sharp picture in the middle with soft (blurred) bands above and below: "fit with blurred background"."""
    f = img.astype(np.float32)
    energy = np.abs(np.diff(f, axis=1)).mean(axis=1)[:-1] + np.abs(np.diff(f, axis=0)).mean(axis=1)
    h = len(energy)
    top, mid, bottom = energy[:h // 4], energy[h // 3:2 * h // 3], energy[3 * h // 4:]
    m = float(np.median(mid))
    if m < 2.0:
        return False
    return float(np.median(top)) < 0.35 * m and float(np.median(bottom)) < 0.35 * m and \
        float(np.median(img[:h // 4])) > 24


def text_band(img: np.ndarray) -> dict | None:
    """The row band that looks most like a line of text (many strong left-right light/dark changes), or None."""
    f = img.astype(np.int16)
    strong = (np.abs(np.diff(f, axis=1)) >= 80).mean(axis=1)
    h = len(strong)
    floor = float(np.median(strong))
    rows = strong >= max(0.08, 4 * floor)
    bands, i = [], 0
    while i < h:
        if rows[i]:
            j = i
            while j + 1 < h and (rows[j + 1] or (j + 2 < h and rows[j + 2])):
                j += 1
            bands.append((i, j))
            i = j + 1
        else:
            i += 1
    best = None
    for a, b in bands:
        score = float(strong[a:b + 1].mean())
        # widen the core (letter bodies) to the ascenders, descenders and outline around it
        edge = max(0.025, 0.2 * score)
        while a > 0 and strong[a - 1] >= edge:
            a -= 1
        while b + 1 < h and strong[b + 1] >= edge:
            b += 1
        height = (b - a + 1) / h
        if not 0.008 <= height <= 0.22:
            continue
        if best is None or score > best["score"]:
            best = {"top": a / h, "bottom": (b + 1) / h, "center": (a + b + 1) / 2 / h, "height": height,
                    "px": b - a + 1, "score": score, "rows": (a, b + 1)}
    return best


def framing(stills: list[tuple[float, np.ndarray]], probe: dict) -> dict:
    w, h = _size(probe, 1000)
    ratio = w / h
    near = min(RATIOS, key=lambda k: abs(math.log(RATIOS[k] / ratio)))
    letterbox = pillarbox = blur = 0
    evidence = []
    for t, img in stills:
        b = bars(img)
        lb, pb = b["top"] + b["bottom"] >= 0.08, b["left"] + b["right"] >= 0.08
        bl = not lb and not pb and blurred_margins(img)
        letterbox += lb
        pillarbox += pb
        blur += bl
        if (lb or pb or bl) and len(evidence) < 5:
            evidence.append(t)
    n = max(1, len(stills))
    return {"width": int(probe.get("width") or 0), "height": int(probe.get("height") or 0), "ratio": round(ratio, 4),
            "aspect": near if abs(math.log(RATIOS[near] / ratio)) < 0.03 else "", "stills": len(stills),
            "letterbox": letterbox / n, "pillarbox": pillarbox / n, "blurred": blur / n,
            "fit_share": (letterbox + pillarbox + blur) / n, "evidence": evidence}


def captions(stills: list[tuple[float, np.ndarray]], speech: list[tuple[float, float]], probe: dict) -> dict:
    """Where a changing line of on-screen text sits (captions), how tall it is and how often it is there."""
    width, frame_h = _size(probe, 1000)
    found = []
    for t, img in stills:
        band = text_band(img)
        if band:
            found.append((t, img, band))
    n = len(stills)
    if not found:
        return {"stills": n, "found": 0, "share": 0.0, "changing": False}
    centers = [b["center"] for _, _, b in found]
    pos = ["top" if c < 0.38 else "middle" if c <= 0.62 else "bottom" for c in centers]
    position = max(set(pos), key=pos.count)
    same = [(t, img, b) for (t, img, b), p in zip(found, pos) if p == position]
    heights = [b["height"] for _, _, b in same]
    changed = 0
    for (_, img1, b1), (_, img2, b2) in zip(same, same[1:]):
        a, z = min(b1["rows"][0], b2["rows"][0]), max(b1["rows"][1], b2["rows"][1])
        if float(np.abs(img1[a:z].astype(np.int16) - img2[a:z].astype(np.int16)).mean()) > 6:
            changed += 1
    in_speech = [t for t, _, _ in found if any(a <= t <= b for a, b in speech)]
    speech_stills = [t for t, _ in stills if any(a <= t <= b for a, b in speech)]
    return {"stills": n, "found": len(found), "share": len(found) / max(1, n), "position": position,
            "position_share": len(same) / len(found), "center": float(np.median([b["center"] for _, _, b in same])),
            "height": float(np.median(heights)), "scale": round(caption_scale(float(np.median(heights)),
                                                                                 width, frame_h), 4), "changing": len(same) < 2 or changed >= 0.5 * (len(same) - 1),
            "speech_share": (len(in_speech) / len(speech_stills)) if speech_stills else None,
            "evidence": [t for t, _, _ in same[:5]]}


def caption_scale(height: float, width: int, frame_h: int) -> float:
    """A caption line's measured height relative to the frame's short side, the way the editor sizes captions
    (landscape frames use 0.72 of that size)."""
    if width <= 0 or frame_h <= 0:
        return 0.0
    return height * frame_h / (min(width, frame_h) * (0.72 if width > frame_h else 1.0))


def caption_size(scale: float) -> str:
    """The measured line scale to the editor's sizes (calibrated on the editor's own clean captions: small 0.025,
    medium 0.028, large 0.037 of the short side)."""
    return "small" if scale < 0.0265 else "medium" if scale < 0.0325 else "large"


# ------------------------------------------------------------------ sound
def read_audio(path: Path, ranges: list[tuple[float, float]], cancelled: Cancelled | None = None) -> list[np.ndarray]:
    out = []
    for a, b in ranges:
        _check(cancelled)
        cmd = [ffmpeg_bin(), "-v", "error", "-nostdin", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(path),
               "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
        try:
            raw = subprocess.run(cmd, capture_output=True, timeout=max(60, (b - a) * 2),
                                 creationflags=NO_WINDOW).stdout
        except subprocess.TimeoutExpired:
            raise AnalysisError("Reading the example's sound took too long.") from None
        out.append(np.frombuffer(raw, dtype=np.float32).copy())
    return out


def _db(x: np.ndarray) -> np.ndarray:
    return 10 * np.log10(np.maximum(x, 1e-12))


def _bands(x: np.ndarray) -> dict[str, np.ndarray]:
    """Per 50 ms frame: overall level and the energy below, inside and above the voice band (dB)."""
    n = len(x) // HOP
    if n < 2:
        return {k: np.zeros(0) for k in ("level", "low", "voice", "high")}
    frames = x[:n * HOP].reshape(n, HOP)
    level = _db((frames ** 2).mean(axis=1))
    win = np.hanning(1024).astype(np.float32)
    pad = np.concatenate([x, np.zeros(1024, dtype=np.float32)])
    idx = (np.arange(n) * HOP)[:, None] + np.arange(1024)[None, :]
    spec = np.abs(np.fft.rfft(pad[idx] * win, axis=1)) ** 2
    freqs = np.fft.rfftfreq(1024, 1 / SR)

    def band(lo, hi):
        return _db(spec[:, (freqs >= lo) & (freqs < hi)].sum(axis=1) / (win ** 2).sum())

    return {"level": level, "low": band(30, 80), "voice": band(300, 3400), "high": band(5000, 7800), "spec": spec}


def estimate_speech(b: dict) -> list[tuple[float, float]]:
    """Speech found from sound alone (no transcript): loud frames where most energy is in the voice band, held
    over short gaps. An estimate: singing or a voice-like instrument also counts."""
    level, voice = b["level"], b["voice"]
    if not len(level):
        return []
    total = _db(b["spec"].sum(axis=1) / (np.hanning(1024) ** 2).sum())
    share = voice - total  # dB: 0 means all energy in the voice band
    active = (level > max(-40.0, float(np.percentile(level, 30)))) & (share > -3.0)
    return _runs(active, hold=6, minimum=6)


def _runs(mask: np.ndarray, hold: int = 0, minimum: int = 1) -> list[tuple[float, float]]:
    """(start, end) seconds of True runs in a per-50 ms mask, bridging gaps of up to `hold` frames."""
    out: list[list[int]] = []
    for i, on in enumerate(mask):
        if not on:
            continue
        if out and i - out[-1][1] <= hold + 1:
            out[-1][1] = i + 1
        else:
            out.append([i, i + 1])
    return [(a * HOP / SR, b * HOP / SR) for a, b in out if b - a >= minimum]


def sound(x: np.ndarray, speech: list[tuple[float, float]], offset: float) -> dict:
    """Levels, silences, the background level under speech versus between sentences, and sudden sounds."""
    b = _bands(x)
    level = b["level"]
    n = len(level)
    if n < 4:
        return {"seconds": len(x) / SR, "frames": n}
    t = np.arange(n) * HOP / SR
    in_speech = np.zeros(n, dtype=bool)
    near = np.zeros(n, dtype=bool)
    for a, z in speech:
        a, z = a - offset, z - offset
        in_speech |= (t >= a) & (t < z)
        near |= (t >= a - 0.35) & (t < z + 0.35)
    silent = level < SILENCE_DB
    silences = [(a + offset, z + offset) for a, z in _runs(silent, minimum=8)]
    core = in_speech & ~(~np.roll(in_speech, 6) | ~np.roll(in_speech, -6))  # 0.3 s inside speech
    gaps = ~near & ~silent
    under = {}
    for name in ("low", "high"):
        if core.sum() >= 10 and gaps.sum() >= 10:
            g, s = float(np.median(b[name][gaps])), float(np.median(b[name][core]))
            under[name] = {"gap_db": round(g, 1), "speech_db": round(s, 1), "drop_db": round(g - s, 1)}
    # sudden sounds: spectral flux peaks well above the usual change, at least 0.3 s apart
    spec = b["spec"]
    flux = np.maximum(np.sqrt(spec[1:]) - np.sqrt(spec[:-1]), 0).sum(axis=1)
    med, mad = _mad(flux)
    peaks = []
    for i in range(1, len(flux) - 1):
        if flux[i] > med + 10 * max(mad, 1e-9) and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1] and \
                level[i + 1] > SILENCE_DB and (not peaks or (i + 1) * HOP / SR - peaks[-1] >= 0.3):
            peaks.append((i + 1) * HOP / SR)
    loud = level[~silent]
    return {"seconds": round(len(x) / SR, 2), "frames": n,
            "level_db": round(float(np.median(loud)), 1) if len(loud) else None,
            "peak_db": round(float(level.max()), 1), "silences": silences,
            "speech_frames": int(in_speech.sum()), "gap_frames": int(gaps.sum()),
            "background_gap_db": round(float(np.median(level[gaps])), 1) if gaps.sum() >= 10 else None,
            "under_speech": under, "onsets": [p + offset for p in peaks]}


# ------------------------------------------------------------------ the whole analysis
def speech_from_words(words: list[dict], ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    segs: list[list[float]] = []
    for w in words:
        a, b = float(w["start"]), float(w["end"])
        if not any(r0 <= a < r1 for r0, r1 in ranges):
            continue
        if segs and a - segs[-1][1] < 0.35:
            segs[-1][1] = max(segs[-1][1], b)
        else:
            segs.append([a, b])
    return [(a, b) for a, b in segs]


def analyze(path: Path, probe: dict, ranges: list[tuple[float, float]], words: list[dict] | None = None, *,
            transcript_note: str = "", cancelled: Cancelled | None = None,
            progress: Progress | None = None) -> dict:
    """Measure the example over `ranges`. Returns the measurements, the observations ("What I noticed") with
    timestamped evidence, and the coverage."""
    step = progress or (lambda f, m: None)
    scan = scan_pictures(path, probe, ranges, cancelled, lambda f, m: step(0.05 + 0.5 * f, m))
    joins = [j for r in scan["ranges"] for j in find_joins(r)]
    shot_list = shots(joins, ranges)
    step(0.58, "Looking at stills for framing and captions")
    still_times = pick_stills(shot_list)
    stills = read_stills(path, probe, ranges, still_times, cancelled)
    step(0.75, "Listening to the sound")
    has_audio = bool(probe.get("has_audio"))
    speech_source = "none"
    speech: list[tuple[float, float]] = []
    audio_parts = read_audio(path, ranges, cancelled) if has_audio else []
    if words:
        speech = speech_from_words(words, ranges)
        speech_source = "transcript"
    elif has_audio:
        for (a, _), x in zip(ranges, audio_parts):
            speech += [(s + a, e + a) for s, e in estimate_speech(_bands(x))]
        speech_source = "estimate"
    sounds = [sound(x, speech, a) for (a, _), x in zip(ranges, audio_parts)]
    step(0.92, "Writing down what I noticed")
    lengths = [s["end"] - s["start"] for s in shot_list]
    full = [s["end"] - s["start"] for s in shot_list if not s["partial"]] if len(shot_list) >= 4 else lengths
    kinds = [j["kind"] for j in joins]
    words_in = [w for w in (words or []) if any(a <= float(w["start"]) < b for a, b in ranges)]
    speech_s = sum(b - a for a, b in speech)
    pauses = [speech[i + 1][0] - speech[i][1] for i in range(len(speech) - 1)
              if any(a <= speech[i][1] and speech[i + 1][0] <= b for a, b in ranges)]
    measured = {
        "ranges": [{"start_ms": int(a * 1000), "end_ms": int(b * 1000)} for a, b in ranges],
        "seconds": round(sum(b - a for a, b in ranges), 2),
        "shots": {"count": len(shot_list), "median_s": round(statistics.median(full), 2) if full else None,
                  "shortest_s": round(min(lengths), 2) if lengths else None,
                  "longest_s": round(max(lengths), 2) if lengths else None,
                  "first_s": round(lengths[0], 2) if lengths else None},
        "joins": {"count": len(joins), "cut": kinds.count("cut"), "dissolve": kinds.count("dissolve"),
                  "fade": kinds.count("fade"), "times": [round(j["t"], 2) for j in joins[:400]]},
        "starts_black": bool(scan["ranges"] and len(scan["ranges"][0]["luma"]) and
                             scan["ranges"][0]["luma"][0] < 0.06),
        "framing": framing(stills, probe),
        "captions": captions(stills, speech, probe),
        "speech": {"source": speech_source, "segments": len(speech), "seconds": round(speech_s, 1),
                   "first_s": round(speech[0][0], 2) if speech else None,
                   "words_per_minute": round(len(words_in) / speech_s * 60) if words_in and speech_s > 5 else None,
                   "median_pause_s": round(statistics.median(pauses), 2) if pauses else None,
                   "pauses": len(pauses), "note": transcript_note,
                   "spans": [(round(a, 2), round(b, 2)) for a, b in speech[:50]]},
        "sound": _merge_sound(sounds) if has_audio else None,
        "brightness": round(float(np.mean([float(r["luma"].mean()) for r in scan["ranges"] if len(r["luma"])]))
                            if scan["ranges"] else 0.0, 3),
    }
    coverage = {"ranges": measured["ranges"], "seconds": measured["seconds"],
                "frames_compared": int(sum(len(r["times"]) for r in scan["ranges"])), "scan_fps": SCAN_FPS,
                "stills": len(stills), "still_method": f"one still in the middle of each shot, plus one every "
                                                       f"{COVER_EVERY_S:g} s of longer shots (at most {MAX_STILLS})",
                "audio_seconds": round(sum(len(x) for x in audio_parts) / SR, 1) if audio_parts else 0,
                "speech": speech_source}
    return {"analyzer": ANALYZER, "method": METHOD, "measured": measured, "coverage": coverage,
            "observations": observations(measured, joins, shot_list)}


def _merge_sound(parts: list[dict]) -> dict:
    parts = [p for p in parts if p.get("frames", 0) >= 4]
    if not parts:
        return {"seconds": 0}
    under: dict[str, dict] = {}
    for name in ("low", "high"):
        vals = [p["under_speech"][name] for p in parts if name in p.get("under_speech", {})]
        if vals:
            under[name] = {k: round(float(np.median([v[k] for v in vals])), 1)
                           for k in ("gap_db", "speech_db", "drop_db")}
    levels = [p["level_db"] for p in parts if p.get("level_db") is not None]
    gaps = [p["background_gap_db"] for p in parts if p.get("background_gap_db") is not None]
    return {"seconds": round(sum(p["seconds"] for p in parts), 1),
            "level_db": round(float(np.median(levels)), 1) if levels else None,
            "peak_db": max(p["peak_db"] for p in parts), "silences": [s for p in parts for s in p["silences"]],
            "background_gap_db": round(float(np.median(gaps)), 1) if gaps else None,
            "gap_frames": sum(p["gap_frames"] for p in parts), "under_speech": under,
            "onsets": [o for p in parts for o in p["onsets"]]}


def _ev(times: list[float], span: float = 1.0, label: str = "") -> list[dict]:
    return [{"start_ms": int(max(0.0, t - span / 2) * 1000), "end_ms": int((t + span / 2) * 1000),
             **({"label": label} if label else {})} for t in times[:5]]


def music_drop(sound_m: dict | None) -> float | None:
    """How far the background (outside the voice band) drops while someone speaks, in dB, or None when there is no
    background between sentences to compare with."""
    if not sound_m or sound_m.get("background_gap_db") is None or sound_m["background_gap_db"] < -55:
        return None
    under = sound_m.get("under_speech") or {}
    drops = [v["drop_db"] for v in under.values() if v["gap_db"] > -75]
    return max(drops) if drops else None


def observations(m: dict, joins: list[dict], shot_list: list[dict]) -> list[dict]:
    """What I noticed: plain sentences, each measured or estimated, with timestamped evidence to play."""
    out: list[dict] = []

    def add(oid, aspect, kind, text, evidence, confidence=None):
        out.append({"id": oid, "aspect": aspect, "kind": kind, "text": text, "evidence": evidence,
                    **({"confidence": round(confidence, 2)} if confidence is not None else {})})

    s = m["shots"]
    if s["count"] >= 2 and s["median_s"] is not None:
        cut_times = [j["t"] for j in joins]
        add("shots", "pacing", "measured", f"{s['count']} shots; a typical shot lasts {s['median_s']:g} s "
            f"(shortest {s['shortest_s']:g} s, longest {s['longest_s']:g} s).", _ev(cut_times, 1.0, "cut"))
    else:
        add("shots", "pacing", "measured", "One continuous shot: no cuts found in the selected part.", [])
    j = m["joins"]
    if j["count"]:
        parts = [f"{j[k]} {name}" for k, name in (("cut", "hard cuts"), ("dissolve", "dissolves"),
                                                    ("fade", "fades through black")) if j[k]]
        soft = [x["t"] for x in joins if x["kind"] != "cut"] or [x["t"] for x in joins]
        add("joins", "pacing", "measured", "Joins between shots: " + ", ".join(parts) + ".",
            _ev(soft, 1.2, "join"))
    sp = m["speech"]
    if sp["segments"]:
        how = "from the transcript" if sp["source"] == "transcript" else "estimated from the sound"
        text = f"Someone speaks for {sp['seconds']:g} s ({how})"
        if sp["first_s"] is not None:
            text += f", starting at {sp['first_s']:g} s"
        if sp["median_pause_s"] is not None:
            text += f"; pauses between sentences are about {sp['median_pause_s']:g} s"
        add("speech", "pacing", "measured" if sp["source"] == "transcript" else "estimate", text + ".",
            _ev([sp["first_s"]] if sp["first_s"] is not None else [], 2.0, "speech starts"),
            None if sp["source"] == "transcript" else 0.6)
        if sp["words_per_minute"]:
            add("pace", "pacing", "measured", f"Speaking pace about {sp['words_per_minute']} words per minute.", [])
    f = m["framing"]
    if f["width"]:
        shape = f["aspect"] or f"{f['width']}×{f['height']}"
        how = ("sits inside the frame with black bars or a blurred background in "
               f"{f['fit_share']:.0%} of stills" if f["fit_share"] >= 0.5 else "fills the frame")
        add("framing", "framing", "measured", f"Shape {shape} ({f['width']}×{f['height']}); the picture {how}.",
            _ev(f["evidence"], 0.5, "still"))
    c = m["captions"]
    if c["found"] and c.get("changing"):
        where = {"bottom": "in the lower third", "middle": "in the centre", "top": "near the top"}[c["position"]]
        add("captions", "captions", "estimate",
            f"A changing line of on-screen text, most likely captions, sits {where} in {c['share']:.0%} of the "
            f"{c['stills']} stills; its line is about {c['height']:.1%} of the frame height "
            f"({caption_size(c['scale'])} in this editor). Found from text-like edges; no model read it.",
            _ev(c["evidence"], 0.5, "caption"), min(0.9, 0.4 + c["share"] * c["position_share"] / 2))
    elif c["found"]:
        add("captions", "captions", "estimate", f"Text that does not change (a logo or a title?) sits in the same "
            f"place in {c['found']} stills. It is not treated as captions.", _ev(c["evidence"], 0.5, "text"), 0.5)
    elif c["stills"] >= 5:
        add("captions", "captions", "estimate", f"No on-screen captions found in {c['stills']} stills.", [], 0.6)
    snd = m["sound"]
    if snd and snd.get("seconds"):
        drop = music_drop(snd)
        if drop is not None and sp["segments"]:
            if drop >= 4:
                text = (f"Background sound (music?) is about {drop:.0f} dB quieter while someone speaks than between "
                        "sentences.")
            else:
                text = "Background sound stays at about the same level while someone speaks."
            add("music", "sound", "estimate", text + " Measured outside the voice band of the mix; a finished mix "
                "cannot be separated exactly.", [{"start_ms": int(max(0.0, a - 1.5) * 1000),
                                                  "end_ms": int((a + 1.5) * 1000), "label": "speech begins"}
                                                 for a, _ in sp.get("spans", [])[:3]], 0.6)
        elif sp["segments"]:
            add("music", "sound", "measured", "Between sentences it is quiet: no background music to compare.", [])
        if snd.get("level_db") is not None:
            add("levels", "sound", "measured", f"Typical level {snd['level_db']:g} dBFS, peaks {snd['peak_db']:g} "
                "dBFS (50 ms readings, not a loudness standard).", [])
        if snd["silences"]:
            add("silences", "sound", "measured", f"{len(snd['silences'])} silent stretches of 0.4 s or more.",
                _ev([(a + b) / 2 for a, b in snd["silences"]], 1.0, "silence"))
        if snd["onsets"]:
            add("effects", "sound", "estimate", f"{len(snd['onsets'])} sudden sounds (sound effects or hits?).",
                _ev(snd["onsets"], 1.0, "sudden sound"), 0.5)
    if m.get("starts_black"):
        add("opening", "pacing", "measured", "The video opens from black.", _ev([m["ranges"][0]["start_ms"] / 1000],
                                                                                 1.0, "opening"))
    return out


# ------------------------------------------------------------------ what the editor can apply
def applicable(m: dict, likes: list[str]) -> tuple[list[dict], list[dict]]:
    """Supported editing choices the measurements justify (each with the observation behind it), and what was
    noticed but cannot be reproduced. `selected` follows what the owner said they like."""
    every = not likes or "overall" in likes

    def pick(aspect):
        return every or aspect in likes

    out: list[dict] = []

    def add(field, value, aspect, why, modes):
        out.append({"field": field, "value": value, "aspect": aspect, "why": why, "selected": pick(aspect),
                    "modes": modes})

    s, j = m["shots"], m["joins"]
    if s["count"] >= 4 and s["median_s"]:
        add("shot_length_s", float(min(30.0, max(1.5, round(s["median_s"] * 2) / 2))), "pacing", "shots",
            ["full_video"])
    if s["count"] >= 2 and s["median_s"]:
        tight = s["median_s"] <= 4 or ((m["speech"]["median_pause_s"] or 1) <= 0.3 and m["speech"]["pauses"] >= 3)
        add("pacing", "safe_cuts" if tight else "continuous", "pacing", "shots", ["highlights"])
    if j["count"] >= 3:
        kind, n = max(((k, j[k]) for k in ("cut", "dissolve", "fade")), key=lambda kv: kv[1])
        if n / j["count"] >= 0.6:
            add("transition", kind, "pacing", "joins", ["full_video"])
    c = m["captions"]
    if c["found"] and c.get("changing") and c["share"] >= 0.3:
        add("captions", True, "captions", "captions", ["full_video"])
        add("caption_position", c["position"], "captions", "captions", ["highlights", "full_stories", "full_video"])
        add("caption_size", caption_size(c["scale"]), "captions", "captions", ["full_video"])
    elif c["stills"] >= 10 and not c["found"]:
        add("captions", False, "captions", "captions", ["full_video"])
    f = m["framing"]
    if f["aspect"]:
        add("aspect_ratio", f["aspect"], "framing", "framing", ["full_video"])
    if f["stills"] >= 3:
        add("layout", "fit" if f["fit_share"] >= 0.5 else "fill", "framing", "framing",
            ["highlights", "full_stories", "full_video"])
    drop = music_drop(m.get("sound"))
    if drop is not None and m["speech"]["segments"]:
        if drop >= 4:
            add("duck_music", True, "sound", "music", ["full_video"])
            add("duck_depth_db", float(min(30, max(3, round(drop)))), "sound", "music", ["full_video"])
        elif drop < 2:
            add("duck_music", False, "sound", "music", ["full_video"])
    unsupported = [{"aspect": "captions", "text": "Caption font and colours: ClipForge cannot read a font from video. "
                    "Pick a caption style yourself."}]
    snd = m.get("sound") or {}
    if snd.get("onsets"):
        unsupported.append({"aspect": "sound", "text": "Sound-effect timing: place effects yourself on the Effects "
                            "track; they are not copied from the example."})
    if drop is not None:
        unsupported.append({"aspect": "sound", "text": "The example's music itself is never copied. Add your own "
                            "music to a project to hear the same treatment."})
    if m["speech"].get("words_per_minute"):
        unsupported.append({"aspect": "pacing", "text": "Speaking pace: ClipForge does not speed up or slow down "
                            "speech."})
    unsupported.append({"aspect": "overall", "text": "Colour, brightness, zooms and motion graphics are not "
                        "measured or reproduced by this editor."})
    return out, unsupported

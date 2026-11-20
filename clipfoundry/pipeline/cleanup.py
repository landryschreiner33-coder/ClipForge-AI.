"""Clean up the sound of speech: rumble and mains hum, background noise, breaths between sentences, uneven levels
between quiet and loud parts, harsh "s" sounds and a little presence.

A range of a source file is cleaned once into a cached 48 kHz mono float file; renders then read that file instead of
the source's own sound, so the picture and every cut stay exactly where they were. Background noise is removed by
DeepFilterNet 3 (MIT or Apache-2.0), a small speech model that runs on the CPU through ONNX Runtime. Its 13 MB model
is downloaded once and checked against pinned SHA-256 hashes; without it (or without ONNX Runtime) a simpler spectral
noise gate, measured on the pauses between words, does that step instead.

Modes: ``off``; ``auto`` (leaves music and ranges that are mostly not speech alone, otherwise ``gentle``);
``gentle``; ``strong``.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx
import numpy as np

from .. import config
from .common import Cancelled, log
from .ffmpeg_utils import NO_WINDOW, MediaWatchdog, ffmpeg_bin, run_process

VERSION = 1
MODES = tuple(config.CLEAN_SOUND_MODES)
SR = 48000
FRAME = 512                 # DeepFilterNet works on 512-sample frames (10.7 ms)
DELAY = 1536                # ...and its output lags its input by this many samples
PRE = SR                    # each block starts 1 s early so the model has settled before the part that is kept
BLOCK = 30 * SR
XFADE = 480                 # 10 ms crossfade where two blocks meet
ASR = 16000                 # analysis rate
AWIN = ASR // 20            # 50 ms analysis frames
TICK = SR // 100            # 10 ms gain steps
TARGET_DB = -20.0           # speech level going into the voice polish (the renderer sets the final loudness)
MAX_RANGE_S = 5 * 3600.0
CACHE_CAP = 4 << 30
RETRY_S = 3600.0            # after a failed model download, use the fallback for this long before trying again

MODEL_NAME = "dfn3-512-v1"
MODEL_URL = "https://github.com/wuxuedaifu/deepfilter-stream/releases/download/model-dfn3-512-v1/{file}"
MODEL_FILES = {  # name: (bytes, sha256)
    "denoiser_model.onnx": (12911035, "b758c49d6708a5b7979e3de185705a8a4915076c862fb17b1b304d9a72b75cdc"),
    "initial_states.npz": (187714, "1165503707b8859a6b650b6bb0dc5b6c55d30c2779d87502f97a77102b5d3872"),
    "meta.json": (1112, "f069011a01849629ad23fbb1d00f4417cf106d5e316e3f7fbcba65cce3440818"),
}
MODEL_LICENSE = (
    "DeepFilterNet 3, https://github.com/Rikorose/DeepFilterNet (Hendrik Schroter), MIT OR Apache-2.0.\n"
    "Streaming ONNX export (torchDF), as published at https://github.com/wuxuedaifu/deepfilter-stream release\n"
    "model-dfn3-512-v1.\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this\n"
    "software and associated documentation files (the \"Software\"), to deal in the Software without restriction,\n"
    "including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or\n"
    "sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the\n"
    "following conditions: The above copyright notice and this permission notice shall be included in all copies or\n"
    "substantial portions of the Software. THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND.\n")
MARKER = "clipforge-verified.json"

# How hard each mode works. "atten_db" limits how far the denoiser may lower anything (a gentle limit keeps the
# room's natural air); "level_share" is how much of the difference between quiet and loud passages is evened out.
# The voice chain a dialogue editor uses: high-pass 80-100 Hz, 3-4 dB out of the mud at 200-400 Hz, 2-3 dB of
# presence at 2.5-5 kHz, a 2.5:1 to 3.5:1 compressor with a 15-30 ms attack and a 50-100 ms release.
PROFILES = {
    "gentle": {"highpass": 80, "atten_db": 12.0, "breath_db": 6.0, "level_share": 0.5, "level_range": (-4.0, 6.0),
               "deess": 0.25, "ratio": 2.5, "presence_db": 2.0, "mud_db": -2.0, "gate": 2.0},
    "strong": {"highpass": 100, "atten_db": 30.0, "breath_db": 12.0, "level_share": 0.8, "level_range": (-6.0, 9.0),
               "deess": 0.45, "ratio": 3.5, "presence_db": 3.0, "mud_db": -3.5, "gate": 3.0},
}
PRESENCE_HZ = 3500
MUD_HZ = 300
COMP_ATTACK_MS, COMP_RELEASE_MS = 20, 90


class CleanupError(RuntimeError):
    """The sound could not be cleaned; the caller keeps the original sound."""


@dataclass
class Result:
    path: Path | None       # None: the sound is left as it is (see report["why"])
    report: dict

    def input_args(self) -> list[str]:
        """FFmpeg input options for the cleaned sound (raw mono float at 48 kHz, starting at the range's start)."""
        assert self.path is not None
        return ["-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(self.path)]


# ------------------------------------------------------------------ the voice model (downloaded on first use)
_lock = threading.Lock()
_denoiser = None
_failed_at = 0.0


def model_dir() -> Path:
    return config.models_dir() / "clean-sound" / MODEL_NAME


def _expected() -> dict:
    return {name: sha for name, (_size, sha) in MODEL_FILES.items()}


def model_ready() -> bool:
    folder = model_dir()
    try:
        marker = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if marker.get("files") != _expected():
        return False
    return all((folder / n).is_file() and (folder / n).stat().st_size == size for n, (size, _) in MODEL_FILES.items())


def _fetch(name: str, size: int, sha: str, folder: Path) -> None:
    part = folder / f"{name}.{uuid.uuid4().hex[:8]}.part"
    digest, have = hashlib.sha256(), 0
    try:
        with httpx.stream("GET", MODEL_URL.format(file=name), follow_redirects=True,
                          timeout=httpx.Timeout(20.0, read=60.0)) as r:
            if r.status_code != 200:
                raise CleanupError(f"The voice cleanup model download answered {r.status_code}.")
            with open(part, "wb") as fh:
                for block in r.iter_bytes(1 << 16):
                    have += len(block)
                    if have > size:
                        raise CleanupError("The voice cleanup model download was larger than expected.")
                    digest.update(block)
                    fh.write(block)
        if have != size or digest.hexdigest() != sha:
            raise CleanupError("The downloaded voice cleanup model did not match its published checksum.")
        part.replace(folder / name)
    finally:
        part.unlink(missing_ok=True)


def ensure_model() -> Path:
    """The verified model folder, downloading it if needed (raises CleanupError when it cannot be had)."""
    global _failed_at
    folder = model_dir()
    if model_ready():
        return folder
    if time.monotonic() - _failed_at < RETRY_S and _failed_at:
        raise CleanupError("The voice cleanup model could not be downloaded a moment ago.")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name, (size, sha) in MODEL_FILES.items():
            _fetch(name, size, sha, folder)
        (folder / "LICENSE.txt").write_text(MODEL_LICENSE, encoding="utf-8")
        (folder / MARKER).write_text(json.dumps({"files": _expected(), "source": MODEL_URL}), encoding="utf-8")
    except (httpx.HTTPError, OSError, CleanupError) as exc:
        _failed_at = time.monotonic()
        if isinstance(exc, CleanupError):
            raise
        raise CleanupError("The voice cleanup model could not be downloaded.") from exc
    return folder


@dataclass
class _Model:
    session: object
    states: list[str]
    outputs: list[str]
    order: list[int]
    initial: dict


def _model() -> _Model:
    global _denoiser
    with _lock:
        if _denoiser is not None:
            return _denoiser
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise CleanupError("ONNX Runtime is not installed.") from exc
        folder = ensure_model()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1  # blocks run side by side instead
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3
        try:
            session = ort.InferenceSession(str(folder / "denoiser_model.onnx"), sess_options=opts,
                                           providers=["CPUExecutionProvider"])
            names = [i.name for i in session.get_inputs()]
            outputs = [o.name for o in session.get_outputs()]
            if names[0] != "input_frame":
                raise ValueError("unexpected inputs")
            with np.load(folder / "initial_states.npz", allow_pickle=False) as z:
                initial = {n: np.asarray(z[n], np.float32) for n in names[1:]}
            order = [outputs.index("new_" + n) for n in names[1:]]
        except Exception as exc:  # noqa: BLE001 - any loading problem means "use the fallback"
            raise CleanupError("The voice cleanup model could not be loaded.") from exc
        _denoiser = _Model(session, names[1:], outputs, order, initial)
        return _denoiser


def denoiser_kind() -> str:
    """"deepfilternet" when the voice model can be used (downloading it if needed), otherwise "gate"."""
    try:
        _model()
        return "deepfilternet"
    except CleanupError:
        return "gate"


def _denoise(m: _Model, x: np.ndarray, keep: float, cancelled: Callable[[], bool] | None) -> np.ndarray:
    """Run the voice model over `x` (mono float, from a fresh state) and return the time-aligned result, with
    `keep` of the original mixed back in (the attenuation limit)."""
    n = x.size
    total = -(-(n + DELAY) // FRAME) * FRAME
    buf = np.zeros(total, np.float32)
    buf[:n] = x
    out = np.empty(total, np.float32)
    states = dict(m.initial)
    run = m.session.run  # type: ignore[attr-defined]
    for i in range(0, total, FRAME):
        if cancelled and i % (FRAME * 256) == 0 and cancelled():
            raise Cancelled()
        feeds = {"input_frame": buf[i:i + FRAME]}
        feeds.update(states)
        r = run(m.outputs, feeds)
        out[i:i + FRAME] = np.asarray(r[0], np.float32).reshape(-1)
        states = {name: r[j] for name, j in zip(m.states, m.order)}
    y = out[DELAY:DELAY + n]
    return (1.0 - keep) * y + keep * x if keep > 0 else y


GATE_N, GATE_H = 1024, 256
_GATE_WIN = np.sqrt(0.5 - 0.5 * np.cos(2 * np.pi * np.arange(GATE_N) / GATE_N)).astype(np.float32)  # sqrt periodic Hann


def _spectra(x: np.ndarray) -> np.ndarray:
    pad = np.pad(np.asarray(x, np.float32), (GATE_N, GATE_N + GATE_H))
    frames = np.lib.stride_tricks.sliding_window_view(pad, GATE_N)[::GATE_H]
    return np.fft.rfft(frames * _GATE_WIN, axis=1).astype(np.complex64)


def noise_profile(x: np.ndarray, words_rel: list[tuple[float, float]]) -> np.ndarray:
    """Average power spectrum of the quieter frames in the pauses (or of the quietest frames overall)."""
    n = x.shape[0]
    count = n // GATE_N
    if not count:
        return np.full(GATE_N // 2 + 1, 1e-10)
    pauses = ~_mask(words_rel, count, GATE_N / SR, 0.1, 0.15)
    power = _frames_power(x, GATE_N)[:count]
    pick = np.flatnonzero(pauses & (power > 1e-11))
    if pick.size < 20:
        pick = np.flatnonzero(power > 1e-11)
    if not pick.size:
        return np.full(GATE_N // 2 + 1, 1e-10)
    pick = pick[power[pick] <= np.percentile(power[pick], 50 if words_rel else 15)]
    if pick.size > 2000:
        pick = pick[np.linspace(0, pick.size - 1, 2000).astype(int)]
    acc = np.zeros(GATE_N // 2 + 1)
    for i in pick:
        seg = np.asarray(x[i * GATE_N:(i + 1) * GATE_N], np.float32)
        acc += np.abs(np.fft.rfft(seg * _GATE_WIN)) ** 2
    return np.maximum(acc / pick.size, 1e-12)


def _gate(x: np.ndarray, noise: np.ndarray, keep: float, strength: float) -> np.ndarray:
    """Spectral noise gate (over-subtraction with a floor, smoothed over time and frequency). Overlap-add with
    matching analysis/synthesis windows, so the output lines up with the input sample for sample."""
    n = x.size
    spec = _spectra(x)
    power = np.abs(spec) ** 2
    kernel = np.ones(3, np.float32) / 3
    smooth = np.apply_along_axis(lambda c: np.convolve(c, kernel, "same"), 0, power)
    gain = np.sqrt(np.clip(1.0 - strength * noise[None, :] / np.maximum(smooth, 1e-20), 0.0, 1.0))
    gain = np.maximum(gain, keep)
    gain = (gain + np.roll(gain, 1, 1) + np.roll(gain, -1, 1)) / 3
    frames = np.fft.irfft(spec * gain.astype(np.float32), n=GATE_N, axis=1).astype(np.float32) * _GATE_WIN
    count = frames.shape[0]
    quarters = frames.reshape(count, GATE_N // GATE_H, GATE_H)
    acc = np.zeros((count + GATE_N // GATE_H, GATE_H), np.float32)
    for j in range(GATE_N // GATE_H):
        acc[j:j + count] += quarters[:, j, :]
    out = acc.reshape(-1) / 2.0  # the product of the two windows sums to 2 at a quarter-window hop
    return out[GATE_N:GATE_N + n]


# ------------------------------------------------------------------ FFmpeg helpers
def _decode(src: str, t0: float, n: int, rate: int, channels: int, chain: str, out: Path,
            cancelled: Callable[[], bool] | None) -> np.memmap:
    """Decode exactly `n` samples per channel from `t0` into a raw float file and map it."""
    dur = n / rate
    args = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t0:.6f}",
            "-t", f"{dur + 0.5:.6f}", "-i", str(src), "-vn", "-sn", "-dn",
            "-af", f"aresample={rate}:async=1:first_pts=0,{chain},apad=whole_len={n},atrim=end_sample={n}",
            "-f", "f32le", "-ac", str(channels), "-ar", str(rate), str(out)]
    result = run_process(args, timeout=max(120.0, dur * 2), cancel=cancelled)
    if result.returncode or not out.exists():
        raise CleanupError("Could not read the sound of this video.")
    want = n * channels * 4
    have = out.stat().st_size
    if have != want:
        with open(out, "r+b") as fh:
            if have > want:
                fh.truncate(want)
            else:
                fh.seek(0, os.SEEK_END)
                fh.write(b"\0" * (want - have))
    return np.memmap(out, np.float32, "r", shape=(n, channels) if channels > 1 else (n,))


def _db(power, floor: float = 1e-12):
    return 10.0 * np.log10(np.maximum(power, floor))


def _frames_power(x: np.ndarray, win: int) -> np.ndarray:
    """Mean power of each `win`-sample frame of a mono memmap (the last partial frame included)."""
    n = x.shape[0]
    count = -(-n // win)
    out = np.empty(count)
    step = win * 4096
    for a in range(0, n, step):
        blk = np.asarray(x[a:a + step], np.float64)
        full = blk.size // win
        k = a // win
        if full:
            out[k:k + full] = (blk[:full * win].reshape(full, win) ** 2).mean(1)
        if blk.size % win:
            out[k + full] = (blk[full * win:] ** 2).mean()
    return out


def _mask(spans: list[tuple[float, float]], count: int, step_s: float, pad_before: float = 0.0,
          pad_after: float = 0.0) -> np.ndarray:
    m = np.zeros(count, bool)
    for a, b in spans:
        i = max(0, int(math.floor((a - pad_before) / step_s)))
        j = min(count, int(math.ceil((b + pad_after) / step_s)))
        if j > i:
            m[i:j] = True
    return m


def _moving_sum(x: np.ndarray, width: int) -> np.ndarray:
    c = np.concatenate([[0.0], np.cumsum(x, dtype=np.float64)])
    half = width // 2
    idx = np.arange(x.size)
    lo = np.clip(idx - half, 0, x.size)
    hi = np.clip(idx + half + 1, 0, x.size)
    return c[hi] - c[lo]


# ------------------------------------------------------------------ analysis
HUM_BASES = (50.0, 60.0)


def _hum(spectrum: np.ndarray, res: float) -> tuple[float | None, list[float]]:
    """Mains hum: narrow peaks at 50 or 60 Hz and their multiples, well above the spectrum around them."""
    best: tuple[float, float | None, list[float]] = (0.0, None, [])
    for base in HUM_BASES:
        found, score = [], 0.0
        for h in range(1, 9):
            f = base * h
            k = int(round(f / res))
            peak = spectrum[max(0, k - 2):k + 3].max()
            lo = spectrum[int((f - 15) / res):int((f - 5) / res)]
            hi = spectrum[int((f + 5) / res):int((f + 15) / res)]
            around = np.median(np.concatenate([lo, hi])) if lo.size + hi.size else peak
            ratio = float(_db(peak) - _db(around))
            if ratio >= 6.0:
                found.append(f)
                score += ratio
        strong = sum(1 for f in found if f <= base * 4)
        if (strong >= 2 or (found and found[0] <= base * 2 and score >= 18.0)) and score > best[0]:
            best = (score, base, found)
    return best[1], best[2]


def _tonal(window: np.ndarray, hum_base: float | None) -> float:
    """Share of the 150-4000 Hz energy in narrow spectral peaks: high for music, near zero for noise."""
    spec = np.abs(np.fft.rfft(window * np.hanning(window.size))) ** 2
    res = ASR / window.size
    lo, hi = int(150 / res), int(4000 / res)
    p = spec[lo:hi]
    logp = _db(p)
    padded = np.pad(logp, 7, mode="edge")
    smooth = np.median(np.lib.stride_tricks.sliding_window_view(padded, 15), axis=1)
    peaks = (logp - smooth > 10.0) & (logp >= np.roll(logp, 1)) & (logp >= np.roll(logp, -1))
    freqs = (np.arange(p.size) + lo) * res
    if hum_base:
        off = np.abs(freqs - np.round(freqs / hum_base) * hum_base)
        peaks &= off > 2.5 * res
    if not peaks.any():
        return 0.0
    near = peaks | np.roll(peaks, 1) | np.roll(peaks, -1)
    return float(p[near].sum() / max(p.sum(), 1e-20))


def analyse(x: np.ndarray, words_rel: list[tuple[float, float]]) -> dict:
    """What the range sounds like, from a 16 kHz stereo decode: speech share, noise floor, speech level, channel
    balance, mains hum and whether music plays between the words."""
    n = x.shape[0]
    count = -(-n // AWIN)
    left, right, mid, cross = (np.zeros(count) for _ in range(4))
    step = AWIN * 2048
    for a in range(0, n, step):
        blk = np.asarray(x[a:a + step], np.float64)
        full = -(-blk.shape[0] // AWIN)
        pad = full * AWIN - blk.shape[0]
        if pad:
            blk = np.concatenate([blk, np.zeros((pad, 2))])
        f = blk.reshape(full, AWIN, 2)
        k = a // AWIN
        left[k:k + full] = (f[..., 0] ** 2).mean(1)
        right[k:k + full] = (f[..., 1] ** 2).mean(1)
        mid[k:k + full] = (((f[..., 0] + f[..., 1]) * 0.5) ** 2).mean(1)
        cross[k:k + full] = (f[..., 0] * f[..., 1]).mean(1)
    step_s = AWIN / ASR
    speech = _mask(words_rel, count, step_s)
    gaps = ~_mask(words_rel, count, step_s, 0.15, 0.15)
    # channel balance first: everything after is measured on the sound that will actually be used
    heard = np.maximum(left, right) > 1e-11
    sel = speech & heard if (speech & heard).any() else heard
    l_db = float(_db(left[sel].mean())) if sel.any() else -120.0
    r_db = float(_db(right[sel].mean())) if sel.any() else -120.0
    denom = math.sqrt(max(left[sel].sum() * right[sel].sum(), 1e-30)) if sel.any() else 1.0
    corr = float(cross[sel].sum() / denom) if sel.any() else 1.0
    _pan, channel = channel_choice({"left_db": l_db, "right_db": r_db, "correlation": corr})
    use, col = {"left": (left, 0), "right": (right, 1)}.get(channel, (mid, None))
    use_db = _db(use)
    audible = use_db > -110.0
    silent = not audible.any()
    pool = use_db[gaps & audible] if (gaps & audible).sum() >= 10 else use_db[audible]
    floor = float(np.percentile(pool, 10)) if pool.size else -120.0
    loud = speech & (use_db > floor + 6.0)
    speech_db = float(np.median(use_db[loud])) if loud.any() else (
        float(np.percentile(use_db[audible], 90)) if audible.any() else -120.0)

    def mono(a: int, b: int) -> np.ndarray:
        blk = np.asarray(x[a:b], np.float64)
        return blk.mean(1) if col is None else blk[:, col]

    # stretches between the words, where hum and music are not masked by the voice
    pauses, run_start = [], None
    for i, g in enumerate(np.append(gaps, False)):
        if g and run_start is None:
            run_start = i
        elif not g and run_start is not None:
            pauses.append((run_start * AWIN, i * AWIN))
            run_start = None

    # mains hum: the average spectrum of the pauses (or of the whole range when there are too few)
    hw = 8192
    starts = [a for p0, p1 in pauses for a in range(p0, p1 - hw + 1, ASR // 4)]
    if len(starts) < 6:
        hw = 16384
        starts = list(range(0, max(0, n - hw), ASR))
    if len(starts) > 600:
        starts = [starts[int(i * len(starts) / 600)] for i in range(600)]
    hum_base, hum = None, []
    if starts:
        acc = np.zeros(hw // 2 + 1)
        win = np.hanning(hw)
        for a in starts:
            acc += np.abs(np.fft.rfft(mono(a, a + hw) * win)) ** 2
        hum_base, hum = _hum(acc / len(starts), ASR / hw)

    # music between the words: tonal windows in the pauses (mains hum and its multiples do not count)
    tw = 4096
    tonal, considered = 0, 0
    windows = [a for p0, p1 in pauses for a in range(p0, p1 - tw + 1, ASR // 2)]
    if len(windows) > 400:
        windows = [windows[int(i * len(windows) / 400)] for i in range(400)]
    for a in windows:
        w = mono(a, a + tw)
        level = float(_db((w ** 2).mean()))
        if level < -60.0 or level < speech_db - 45.0:
            continue
        considered += 1
        tonal += _tonal(w, hum_base) >= 0.25
    music = considered >= 4 and tonal / considered >= 0.4
    return {"speech_share": round(float(speech.mean()) if count else 0.0, 3), "floor_db": round(floor, 1),
            "speech_db": round(speech_db, 1), "left_db": round(l_db, 1), "right_db": round(r_db, 1),
            "correlation": round(corr, 3), "channel": channel, "hum_hz": hum_base, "hum": hum, "music": bool(music),
            "tonal_windows": [int(tonal), considered], "silent": silent}


def decide(mode: str, a: dict) -> tuple[str | None, str]:
    """Which profile to apply (None: leave the sound as it is) and why, in plain words."""
    if a["silent"]:
        return None, "there is no sound to clean up"
    if mode == "auto":
        if a["speech_share"] < 0.3:
            return None, "it is mostly not speech"
        if a["music"]:
            return None, "there is music in the background"
        return "gentle", "speech"
    return mode, ""


def channel_choice(a: dict) -> tuple[str, str]:
    """Mic balance: use one channel when the other is nearly silent or cancels it out, otherwise both."""
    l_db, r_db, corr = a["left_db"], a["right_db"], a["correlation"]
    if l_db - r_db > 15.0 or (corr < -0.3 and l_db >= r_db):
        return "pan=mono|c0=c0", "left"
    if r_db - l_db > 15.0 or corr < -0.3:
        return "pan=mono|c0=c1", "right"
    return "pan=mono|c0=0.5*c0+0.5*c1", "both"


# ------------------------------------------------------------------ the cache
def cache_dir() -> Path:
    d = config.data_dir() / "cache" / "clean-sound"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _trim_cache(keep: Path) -> None:
    files = sorted(cache_dir().glob("*.f32"), key=lambda p: p.stat().st_mtime if p.exists() else 0)
    total = sum(p.stat().st_size for p in files if p.exists())
    for p in files:
        if total <= CACHE_CAP:
            break
        if p == keep:
            continue
        try:
            size = p.stat().st_size
            p.unlink()
            p.with_suffix(".json").unlink(missing_ok=True)
            total -= size
        except OSError:
            pass  # in use by a render right now


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _key(src: str, t0: float, t1: float, words_rel: list[tuple[float, float]], mode: str) -> str:
    st = os.stat(src)
    data = [VERSION, str(Path(src).resolve()), st.st_size, st.st_mtime_ns, round(t0, 3), round(t1, 3), mode,
            [(round(a, 2), round(b, 2)) for a, b in words_rel]]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()[:32]


# ------------------------------------------------------------------ cleaning a range
def _words_in(words: list[dict], t0: float, t1: float) -> list[tuple[float, float]]:
    out = []
    for w in words or []:
        a, b = float(w.get("start", 0)), float(w.get("end", 0))
        if b > t0 and a < t1 and b > a:
            out.append((max(0.0, a - t0), min(t1, b) - t0))
    return sorted(out)


def clean(src: str | Path, t0: float, t1: float, words: list[dict], mode: str, *,
          cancelled: Callable[[], bool] | None = None,
          progress: Callable[[float, str], None] | None = None) -> Result:
    """The cleaned sound of src[t0, t1) (seconds), cached. `words` are transcript words in source time. The report
    says what was done, in numbers and in one plain sentence ("summary")."""
    result = _clean(str(src), t0, t1, words, mode, cancelled, progress)
    result.report["summary"] = summary(result.report)
    return result


def failed(mode: str, exc: Exception) -> Result:
    """What a caller keeps when cleaning failed: the original sound, and why."""
    why = str(exc) if isinstance(exc, CleanupError) else "it could not be cleaned up on this computer."
    report = {"mode": mode, "applied": None, "error": why}
    report["summary"] = summary(report)
    return Result(None, report)


def clean_or_keep(src: str | Path, t0: float, t1: float, words: list[dict], mode: str, *,
                  cancelled: Callable[[], bool] | None = None,
                  progress: Callable[[float, str], None] | None = None) -> Result:
    """`clean`, for renders: any failure (a missing model, a full disk, an unreadable stream) keeps the original
    sound and says why; only a cancel stops the render."""
    try:
        return clean(src, t0, t1, words, mode, cancelled=cancelled, progress=progress)
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - the original sound is always a safe fallback
        log.warning("sound cleanup skipped for %s: %s", Path(src).name, exc)
        return failed(mode, exc)


def _clean(src: str, t0: float, t1: float, words: list[dict], mode: str, cancelled: Callable[[], bool] | None,
           progress: Callable[[float, str], None] | None) -> Result:
    if mode not in MODES:
        raise CleanupError(f"Unknown sound cleanup mode {mode!r}.")
    if mode == "off":
        return Result(None, {"mode": "off", "applied": None, "why": "turned off"})
    t0, t1 = max(0.0, float(t0)), float(t1)
    if t1 - t0 <= 0.05:
        return Result(None, {"mode": mode, "applied": None, "why": "the range is too short"})
    if t1 - t0 > MAX_RANGE_S:
        raise CleanupError("This video is too long to clean up its sound in one piece.")
    report_ = progress or (lambda _f, _m: None)
    words_rel = _words_in(words, t0, t1)
    try:
        key0 = _key(src, t0, t1, words_rel, mode)
    except OSError as exc:
        raise CleanupError("The video file could not be read.") from exc
    folder = cache_dir()
    known = _read_json(folder / f"{key0}.json")
    work = folder / "work" / uuid.uuid4().hex
    started = time.monotonic()
    try:
        if known is None:
            report_(0.0, "Listening to the sound")
            n16 = int(round((t1 - t0) * ASR))
            work.mkdir(parents=True, exist_ok=True)
            x16 = _decode(src, t0, n16, ASR, 2, "aformat=sample_fmts=flt:channel_layouts=stereo",
                          work / "listen.f32", cancelled)
            analysis = analyse(x16, words_rel)
            del x16
            applied, why = decide(mode, analysis)
            known = {"analysis": analysis, "applied": applied, "why": why}
            _write_json(folder / f"{key0}.json", known)
        analysis, applied = known["analysis"], known["applied"]
        if applied is None:
            return Result(None, {"mode": mode, "applied": None, "why": known["why"], **_public(analysis)})
        kind = denoiser_kind()
        key = f"{key0}-{kind[:3]}"
        out = folder / f"{key}.f32"
        done = _read_json(folder / f"{key}.json")
        n = int(round((t1 - t0) * SR))
        if done and out.exists() and out.stat().st_size == n * 4:
            try:
                os.utime(out)
            except OSError:
                pass
            return Result(out, done)
        need = n * 4 * 3 + (512 << 20)
        if shutil.disk_usage(folder).free < need:
            raise CleanupError("There is not enough free disk space to clean up the sound.")
        work.mkdir(parents=True, exist_ok=True)
        report = _process(src, t0, n, words_rel, analysis, applied, kind, work, out, cancelled, report_)
        report.update(mode=mode, applied=applied, why=known["why"], seconds=round(time.monotonic() - started, 2))
        _write_json(folder / f"{key}.json", report)
        _trim_cache(out)
        return Result(out, report)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _public(a: dict) -> dict:
    return {"speech_share": a["speech_share"], "music": a["music"], "hum_hz": a["hum_hz"],
            "noise_below_voice_db_before": round(a["speech_db"] - a["floor_db"], 1)}


def _polish_chain(p: dict, n: int) -> str:
    parts = []
    parts.append(f"deesser=i={p['deess']:.2f}:m=0.5:f=0.5:s=o")
    # Only the syllables louder than the typical level are pressed down, so pauses do not come up relative to speech.
    parts.append(f"acompressor=threshold={TARGET_DB + 2:.0f}dB:ratio={p['ratio']:.1f}:attack={COMP_ATTACK_MS}:"
                 f"release={COMP_RELEASE_MS}:knee=6:makeup=1:detection=rms")
    if p["presence_db"]:
        parts.append(f"equalizer=f={PRESENCE_HZ}:t=q:w=0.8:g={p['presence_db']:.1f}")
    if p["mud_db"]:
        parts.append(f"equalizer=f={MUD_HZ}:t=q:w=1:g={p['mud_db']:.1f}")
    parts.append(f"apad=whole_len={n},atrim=end_sample={n}")
    return ",".join(parts)


def _process(src: str, t0: float, n: int, words_rel: list[tuple[float, float]], a: dict, applied: str, kind: str,
             work: Path, out: Path, cancelled, report_: Callable[[float, str], None]) -> dict:
    p = PROFILES[applied]
    pan, channel = channel_choice(a)
    chain = [f"aformat=sample_fmts=flt:channel_layouts=stereo,{pan}", f"highpass=f={p['highpass']}:p=2"]
    for f in a["hum"]:
        chain.append(f"bandreject=f={f:.1f}:width_type=h:w={max(2.0, f * 0.02):.1f}")
    report_(0.05, "Cleaning up the sound")
    pre = _decode(src, t0, n, SR, 1, ",".join(chain), work / "pre.f32", cancelled)

    # 1. background noise, block by block (blocks run side by side; each starts early to settle)
    keep = 10 ** (-p["atten_db"] / 20)
    if kind == "deepfilternet":
        model = _model()
        run_block = lambda x: _denoise(model, x, keep, cancelled)  # noqa: E731
    else:
        noise = noise_profile(pre, words_rel)
        run_block = lambda x: _gate(x, noise, keep, p["gate"])  # noqa: E731
    dn = np.memmap(work / "dn.f32", np.float32, "w+", shape=(n,))
    bounds = [(s, min(n, s + BLOCK)) for s in range(0, n, BLOCK)]

    def one(span: tuple[int, int]) -> np.ndarray:
        s, e = span
        lead = s - XFADE if s else 0
        a0 = max(0, lead - PRE)
        y = run_block(np.asarray(pre[a0:e], np.float32))
        return y[lead - a0:]

    workers = max(1, min(3, (os.cpu_count() or 2) // 2))
    ramp = np.linspace(0.0, 1.0, XFADE, dtype=np.float32)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cf-clean-sound") as pool:
        it = iter(bounds)
        pending: deque = deque((span, pool.submit(one, span)) for span in (next(it) for _ in range(
            min(len(bounds), workers * 2))))
        try:
            for k in range(len(bounds)):
                (s, e), fut = pending.popleft()
                y = fut.result()
                if s:
                    dn[s - XFADE:s] = dn[s - XFADE:s] * (1 - ramp) + y[:XFADE] * ramp
                    dn[s:e] = y[XFADE:]
                else:
                    dn[s:e] = y
                report_(0.05 + 0.75 * (k + 1) / len(bounds), "Cleaning up the sound")
                nxt = next(it, None)
                if nxt is not None:
                    pending.append((nxt, pool.submit(one, nxt)))
        finally:
            for _span, fut in pending:
                fut.cancel()
    dn.flush()
    del pre

    # 2. levels: even out quiet and loud passages (a slow gain that ignores pauses) and soften breaths
    ticks = _frames_power(dn, TICK)
    tick_db = _db(ticks)
    count = ticks.size
    step_s = TICK / SR
    near_words = _mask(words_rel, count, step_s, 0.04, 0.10)
    in_words = _mask(words_rel, count, step_s)
    gap_pool = tick_db[~near_words & (tick_db > -110)]
    floor = float(np.percentile(gap_pool, 10)) if gap_pool.size >= 20 else float(np.percentile(tick_db, 5))
    speech = in_words & (tick_db > floor + 6.0)
    ref = float(np.median(tick_db[speech])) if speech.any() else (
        float(np.percentile(tick_db, 90)) if count else TARGET_DB)
    offset = float(np.clip(TARGET_DB - ref, -12.0, 24.0))
    level = np.zeros(count)
    lo, hi = p["level_range"]
    if speech.sum() >= 50:
        energy = _moving_sum(np.where(speech, ticks, 0.0), 300)
        weight = _moving_sum(speech.astype(np.float64), 300)
        ok = weight >= 30
        env = np.full(count, np.nan)
        env[ok] = _db(energy[ok] / weight[ok])
        idx = np.arange(count)
        env = np.interp(idx, idx[ok], env[ok]) if ok.any() else np.full(count, ref)
        level = np.clip(p["level_share"] * (ref - env), lo, hi)
        level = _moving_sum(level, 50) / _moving_sum(np.ones(count), 50)
    duck = np.zeros(count)
    breaths = 0
    if words_rel:
        cand = ~near_words & (tick_db > floor + 6.0) & (tick_db > ref - 40.0) & (tick_db < ref - 12.0)
        i = 0
        while i < count:
            if not cand[i]:
                i += 1
                continue
            j = i
            while j < count and cand[j]:
                j += 1
            if 10 <= j - i <= 100:  # 0.1 to 1 s: a breath, not a sound that belongs to the scene
                duck[i:j] = p["breath_db"]
                breaths += 1
            i = j
        duck = _moving_sum(duck, 4) / _moving_sum(np.ones(count), 4)
    gain = 10 ** ((offset + level - duck) / 20)
    centres = (np.arange(count) + 0.5) * TICK

    # 3. voice polish (de-ess, gentle compression, presence) and the exact length, written to the cache
    part = out.with_name(f"{out.name}.{uuid.uuid4().hex[:8]}.part")
    args = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(SR),
            "-ac", "1", "-i", "pipe:0", "-af", _polish_chain(p, n), "-f", "f32le",
            "-ac", "1", "-ar", str(SR), str(part)]
    report_(0.85, "Polishing the voice")
    try:
        with tempfile.TemporaryFile() as err, MediaWatchdog(cancelled, max(300.0, n / SR * 2)) as watch:
            proc = watch.add(subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err,
                                              creationflags=NO_WINDOW))
            try:
                for s in range(0, n, SR * 4):
                    watch.check()
                    e = min(n, s + SR * 4)
                    g = np.interp(np.arange(s, e), centres, gain).astype(np.float32)
                    proc.stdin.write((np.asarray(dn[s:e], np.float32) * g).tobytes())  # type: ignore[union-attr]
                proc.stdin.close()  # type: ignore[union-attr]
                rc = proc.wait()
            except (BrokenPipeError, OSError) as exc:
                watch.check()
                raise CleanupError("The voice polish stopped unexpectedly.") from exc
        if rc or not part.exists():
            raise CleanupError("The voice polish failed.")
        size = part.stat().st_size
        if size != n * 4:
            with open(part, "r+b") as fh:
                if size > n * 4:
                    fh.truncate(n * 4)
                else:
                    fh.seek(0, os.SEEK_END)
                    fh.write(b"\0" * (n * 4 - size))
        os.replace(part, out)
    finally:
        part.unlink(missing_ok=True)
    del dn

    # what changed, measured the same way before and after (50 ms frames, pauses vs. words)
    done = np.memmap(out, np.float32, "r", shape=(n,))
    frames = _db(_frames_power(done, SR // 20))
    del done
    fc = frames.size
    gaps = ~_mask(words_rel, fc, 0.05, 0.15, 0.15) & (frames > -110)
    spk = _mask(words_rel, fc, 0.05)
    after_floor = float(np.percentile(frames[gaps], 10)) if gaps.sum() >= 10 else float(np.percentile(frames, 5))
    loud = spk & (frames > after_floor + 6.0)
    after_speech = float(np.median(frames[loud])) if loud.any() else float(np.percentile(frames, 90))
    return {**_public(a), "denoiser": kind, "channel": channel, "breaths_softened": breaths,
            "noise_below_voice_db_after": round(after_speech - after_floor, 1), "version": VERSION}


# ------------------------------------------------------------------ before / after
def _write_wav(path: Path, x: np.ndarray) -> None:
    import wave

    pcm = np.clip(np.asarray(x, np.float64) * 32767.0, -32768, 32767).astype("<i2")
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1 if pcm.ndim == 1 else pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def _speech_rms(x: np.ndarray, words_rel: list[tuple[float, float]]) -> float:
    mono = x if x.ndim == 1 else x.mean(1)
    frames = _frames_power(mono, SR // 20)
    mask = _mask(words_rel, frames.size, 0.05)
    pick = frames[mask] if mask.sum() >= 5 else frames
    return float(math.sqrt(max(float(pick.mean()) if pick.size else 0.0, 1e-12)))


def compare(src: str | Path, t0: float, t1: float, words: list[dict], mode: str, folder: Path, name: str, *,
            cancelled: Callable[[], bool] | None = None, max_s: float = 90.0) -> dict:
    """Two WAV files of the same stretch (at most `max_s` seconds from t0) for a before/after switch: the original
    sound and the cleaned sound, matched in loudness so the comparison is about clarity, not volume. The cleaning
    uses the same range and cache as the render, so rendering afterwards reuses it."""
    result = clean(src, t0, t1, words, mode, cancelled=cancelled)
    folder.mkdir(parents=True, exist_ok=True)
    n = int(round(min(t1 - t0, max_s) * SR))
    words_rel = _words_in(words, t0, t0 + n / SR)
    with tempfile.TemporaryDirectory(dir=cache_dir()) as tmp:
        before = np.array(_decode(str(src), t0, n, SR, 2, "aformat=sample_fmts=flt:channel_layouts=stereo",
                                  Path(tmp) / "before.f32", cancelled), np.float64)
    target = 10 ** (TARGET_DB / 20)
    out = {"before": None, "after": None, "report": result.report}
    pairs = [("before", before)]
    if result.path is not None:  # in both channels, like the source, so the two play at the same loudness
        after = np.array(np.memmap(result.path, np.float32, "r", shape=(n,)), np.float64)
        pairs.append(("after", np.stack([after, after], 1)))
    for which, x in pairs:
        y = x * (target / _speech_rms(x, words_rel))
        peak = float(np.abs(y).max()) if y.size else 0.0
        if peak > 0.98:
            y *= 0.98 / peak
        path = folder / f"{name}-{which}.wav"
        _write_wav(path, y)
        out[which] = path
    return out


# ------------------------------------------------------------------ in words
def summary(report: dict | None) -> str:
    """One or two plain sentences on what the cleanup did (shown under the clip's audio settings)."""
    if not report or report.get("mode") in (None, "off"):
        return ""
    if report.get("error"):
        return f"The sound was left as it is: {report['error']}"
    if not report.get("applied"):
        return f"The sound was left as it is: {report.get('why') or 'nothing to clean up'}."
    bits = []
    before, after = report.get("noise_below_voice_db_before"), report.get("noise_below_voice_db_after")
    if before is not None and after is not None and after > before + 1:
        bits.append(f"background noise went from {before:.0f} dB to {after:.0f} dB below the voice")
    if report.get("hum_hz"):
        bits.append(f"{report['hum_hz']:.0f} Hz hum removed")
    if report.get("breaths_softened"):
        n = report["breaths_softened"]
        bits.append(f"{n} breath{'s' if n != 1 else ''} softened")
    if report.get("channel") in ("left", "right"):
        bits.append(f"used the {report['channel']} microphone channel (the other was nearly silent or out of phase)")
    head = "Sound cleaned up (" + ("strong" if report.get("applied") == "strong" else "gentle") + ")"
    text = head + (": " + "; ".join(bits) + "." if bits else ": voice polished.")
    if report.get("denoiser") == "gate":
        text += " The voice model was not available, so a simpler noise filter was used."
    return text

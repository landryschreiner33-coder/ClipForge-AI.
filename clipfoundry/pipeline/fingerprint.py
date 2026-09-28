"""Clip fingerprints for duplicate protection.

* text: a MinHash signature of the transcript's word 4-grams (estimates word overlap between clips cheaply)
* video: a perceptual hash (dHash) of eight frames of the rendered clip; near-identical pictures give near-identical
  hashes even after re-encoding or small edits
* source key + time range, and the normalized title

They are compared against clips that were already published or scheduled, so the same moment is not posted twice.
"""
from __future__ import annotations

import hashlib
import re
import subprocess

import numpy as np

from .common import log
from .ffmpeg_utils import NO_WINDOW, ffmpeg_bin
from .text_utils import tokens

PERMUTATIONS = 64
SHINGLE = 4
_MASK = (1 << 61) - 1
_rng = np.random.default_rng(20260928)
_A = _rng.integers(1, _MASK, PERMUTATIONS, dtype=np.int64)
_B = _rng.integers(0, _MASK, PERMUTATIONS, dtype=np.int64)
FRAMES = 8


def _shingles(text: str) -> set[int]:
    toks = tokens(text)
    if len(toks) < SHINGLE:
        toks = toks + ["_"] * (SHINGLE - len(toks))
    return {int.from_bytes(hashlib.blake2b(" ".join(toks[k:k + SHINGLE]).encode(), digest_size=7).digest(), "big")
            for k in range(len(toks) - SHINGLE + 1)}


def text_signature(text: str) -> list[int]:
    sh = np.fromiter(_shingles(text), dtype=np.int64)
    if not len(sh):
        return [0] * PERMUTATIONS
    # (a*x + b) mod p, computed in Python ints for the modulo to stay exact
    sig = []
    for a, b in zip(_A.tolist(), _B.tolist()):
        sig.append(min(((a * int(x) + b) & _MASK) for x in sh.tolist()))
    return sig


def text_similarity(a: list[int], b: list[int]) -> float:
    """Estimated Jaccard similarity of the two transcripts' word 4-grams."""
    if not a or not b or not any(a) or not any(b):
        return 0.0
    return sum(1 for x, y in zip(a, b) if x == y) / min(len(a), len(b))


def norm_title(title: str) -> str:
    return " ".join(tokens(re.sub(r"#\w+", " ", title or "")))


def title_similarity(a: str, b: str) -> float:
    sa, sb = set(norm_title(a).split()), set(norm_title(b).split())
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def video_signature(path: str, duration: float) -> list[str]:
    """dHash (64 bits, hex) of FRAMES frames spread over the clip. Empty list if the video cannot be read."""
    hashes: list[str] = []
    for k in range(FRAMES):
        t = max(0.0, duration * (k + 0.5) / FRAMES)
        cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(path),
               "-frames:v", "1", "-vf", "scale=9:8,format=gray", "-f", "rawvideo", "pipe:1"]
        try:
            raw = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=NO_WINDOW).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("video fingerprint failed: %s", exc)
            return []
        if len(raw) < 72:
            continue
        px = np.frombuffer(raw[:72], np.uint8).reshape(8, 9).astype(np.int16)
        bits = (px[:, 1:] > px[:, :-1]).flatten()
        hashes.append(f"{int(''.join('1' if b else '0' for b in bits), 2):016x}")
    return hashes


def video_distance(a: list[str], b: list[str]) -> float | None:
    """Mean Hamming distance (0-64) between matching frames; None if either is missing."""
    if not a or not b:
        return None
    n = min(len(a), len(b))
    return sum(bin(int(x, 16) ^ int(y, 16)).count("1") for x, y in zip(a[:n], b[:n])) / n


def same_video(a: list[str], b: list[str], max_distance: float = 10.0) -> bool:
    d = video_distance(a, b)
    return d is not None and d <= max_distance

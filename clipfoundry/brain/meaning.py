"""The meaning of a memory as numbers, so "no zooms on faces" is found when you ask about "zooming in"
(docs/clipforge/CLIPFORGE_AI.md).

Phase A embeds with feature hashing (`hash-v1`): the content words, their stems and the word pairs of a text are
hashed into 256 numbers with a stable hash, so a vector made today still matches one made last year, nothing is
downloaded and nothing leaves the computer. The plan's embedding model (through the built-in engine) takes over
later: every memory records which embedder made its vector, the brain check reports the old ones and Rebuild
recomputes them.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter

import numpy as np

from ..pipeline.text_utils import content_tokens

MODEL = "hash-v1"
DIM = 256


def terms(text: str) -> list[str]:
    """Content words, stems ("zoom", "zooms" and "zooming" share "~zoom") and word pairs."""
    toks = content_tokens(text)
    stems = [f"~{t[:4]}" for t in toks if len(t) >= 4]
    return toks + stems + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]


def _slot(term: str) -> tuple[int, float]:
    n = int.from_bytes(hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest(), "little")
    return n % DIM, 1.0 if (n >> 60) & 1 else -1.0


def embed(text: str) -> np.ndarray:
    """A unit vector of DIM numbers; a text without content words gives zeros."""
    v = np.zeros(DIM, dtype=np.float32)
    for term, c in Counter(terms(text)).items():
        i, sign = _slot(term)
        v[i] += sign * (1.0 + math.log(c))
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 1e-9 else v


def pack(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype="<f4").tobytes()


def unpack(blob: bytes | None) -> np.ndarray | None:
    if not blob or len(blob) % 4:
        return None
    return np.frombuffer(blob, dtype="<f4").astype(np.float32)


def cosine(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None or a.shape != b.shape:
        return 0.0
    return float(np.clip(np.dot(a, b), -1.0, 1.0))

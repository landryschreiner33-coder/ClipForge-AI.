"""The meaning of a memory as numbers, so "no zooms on faces" is found when you ask about "zooming in"
(docs/clipforge/CLIPFORGE_AI.md, docs/clipforge/SMARTER_AI.md).

Two embedders. With the meaning model (clipfoundry/embedder.py, all-MiniLM-L6-v2 on the CPU) a question finds the
memory that means the same thing in other words. Without it, feature hashing (`hash-v1`): the content words, their
stems and the word pairs of a text are hashed into 256 numbers with a stable hash, so a vector made today still
matches one made last year, nothing is downloaded and nothing leaves the computer. Every memory records which
embedder made its vector; vectors from different embedders are never compared, the brain check reports the old ones
and Rebuild recomputes them with the current embedder.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter

import numpy as np

from .. import embedder
from ..pipeline.text_utils import content_tokens

HASH_MODEL = "hash-v1"
MODEL = HASH_MODEL              # the hash space's id; model() is the embedder in use right now
DIM = 256


def model(settings: dict | None = None) -> str:
    """The embedder that makes vectors right now: the meaning model when it is on and present, else hash-v1."""
    return embedder.MODEL if embedder.usable(settings) else HASH_MODEL


def min_similar(which: str | None = None) -> float:
    """The cosine from which two texts count as sharing meaning (unrelated texts score higher with the meaning
    model than with hashing)."""
    return 0.30 if (which or model()) == embedder.MODEL else 0.15


def terms(text: str) -> list[str]:
    """Content words, stems ("zoom", "zooms" and "zooming" share "~zoom") and word pairs."""
    toks = content_tokens(text)
    stems = [f"~{t[:4]}" for t in toks if len(t) >= 4]
    return toks + stems + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]


def _slot(term: str) -> tuple[int, float]:
    n = int.from_bytes(hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest(), "little")
    return n % DIM, 1.0 if (n >> 60) & 1 else -1.0


def make(text: str, settings: dict | None = None) -> tuple[bytes, str]:
    """(packed vector, embedder id) for a memory's text, with the embedder in use right now."""
    which = model(settings)
    if which == embedder.MODEL:
        v = embedder.embed_one(text, settings)
        if v is not None:
            return pack(v), embedder.MODEL
    return pack(hash_embed(text)), HASH_MODEL


def embed(text: str, which: str | None = None, settings: dict | None = None) -> np.ndarray:
    """A unit vector in the space of `which` (default: the embedder in use right now)."""
    which = which or model(settings)
    if which == embedder.MODEL:
        v = embedder.embed_one(text, settings)
        if v is not None:
            return v
    return hash_embed(text)


def hash_embed(text: str) -> np.ndarray:
    """A unit vector of DIM numbers (hash-v1); a text without content words gives zeros."""
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

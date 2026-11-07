"""Local sentence embeddings for semantic analysis.

Each sentence of a video becomes a dense vector. With the meaning model (clipfoundry/embedder.py, a small
sentence-embedding network run on the CPU) two sentences that say the same thing in different words are close
together. Without it (setting off, no download yet, no ONNX Runtime) the vectors are TF-IDF over the video's own
content words, word stems and word pairs (randomly projected to a fixed size), blended with a latent semantic
analysis of the same matrix (an SVD), so sentences about the same thing still end up close when they share words
that co-occur elsewhere in the video. Either way this is enough to see whether a clip stays on one topic, ties its
ending back to its opening, leans on what was said just before it, or repeats another clip.

The two spaces have different scales (two unrelated sentences score about 0.0 with words and about 0.1 with the
meaning model), so every vector set carries the video's own baseline similarity and `cos_cal` removes it: the
numbers downstream (features, diversity, story boundaries) mean the same thing whichever model made them.
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np

from .. import embedder
from .text_utils import content_tokens

MAX_VOCAB = 3000
DIM = 48
RAW_DIM = 256


def _terms(text: str) -> list[str]:
    toks = content_tokens(text)
    stems = [f"~{t[:4]}" for t in toks if len(t) >= 5]  # "runners"/"running" share "~runn"
    return toks + stems + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]


class Embeddings(np.ndarray):
    """Sentence vectors (rows are unit vectors or zeros) that remember which embedder made them (`model`:
    embedder.MODEL or "lexical") and the video's baseline similarity between unrelated sentences (`baseline`)."""
    model: str
    baseline: float

    def __new__(cls, arr, model: str = "lexical", baseline: float = 0.0):
        obj = np.asarray(arr, dtype=np.float32).view(cls)
        obj.model = model
        obj.baseline = float(baseline)
        return obj

    def __array_finalize__(self, obj):
        if obj is None:
            return
        self.model = getattr(obj, "model", "lexical")
        self.baseline = getattr(obj, "baseline", 0.0)


def _baseline(vecs: np.ndarray, fallback: float) -> float:
    """The typical cosine between two sentences that are far apart in the video (the model's own "unrelated" level),
    measured on the video itself when it has enough sentences."""
    n = len(vecs)
    if n < 12:
        return fallback
    rng = np.random.default_rng(n)
    pairs = rng.integers(0, n, (min(600, 4 * n), 2))
    sims = [float(vecs[i] @ vecs[j]) for i, j in pairs if abs(int(i) - int(j)) > 5
            and np.linalg.norm(vecs[i]) > 1e-9 and np.linalg.norm(vecs[j]) > 1e-9]
    if len(sims) < 20:
        return fallback
    return float(min(0.35, max(0.0, np.median(sims))))


MEANING_BASELINE = 0.10   # all-MiniLM-L6-v2: unrelated sentences score about this; measured per video when possible


def embed_texts(texts: list[str], dim: int = DIM, opts: dict | None = None) -> Embeddings:
    """Unit vectors (len(texts) x d): the meaning model's when it is on and available, otherwise the word-based
    ones. Texts without content words get a zero vector in the word-based space."""
    n = len(texts)
    if n == 0:
        return Embeddings(np.zeros((0, 1), dtype=np.float32))
    vecs = embedder.embed_or_none(texts, opts)
    if vecs is not None and len(vecs) == n:
        return Embeddings(vecs, embedder.MODEL, _baseline(vecs, MEANING_BASELINE))
    return Embeddings(_lexical(texts, dim), "lexical", 0.0)


def _lexical(texts: list[str], dim: int = DIM) -> np.ndarray:
    n = len(texts)
    docs = [Counter(_terms(t)) for t in texts]
    df: Counter = Counter()
    for d in docs:
        df.update(d.keys())
    vocab = [t for t, c in df.most_common(MAX_VOCAB) if c >= 2 or n < 80]
    if not vocab:
        return np.zeros((n, 1), dtype=np.float32)
    index = {t: k for k, t in enumerate(vocab)}
    m = np.zeros((n, len(vocab)), dtype=np.float32)
    for i, d in enumerate(docs):
        for t, c in d.items():
            k = index.get(t)
            if k is not None:
                m[i, k] = (1.0 + math.log(c)) * math.log((1 + n) / (1 + df[t]) + 1.0)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    m = np.divide(m, norms, out=np.zeros_like(m), where=norms > 0)
    k = max(2, min(dim, n // 4, len(vocab) - 1))  # few dimensions: related words get merged
    if n <= 2 or len(vocab) <= 2:
        emb = m
    elif n <= 400:
        # exact: eigen-decomposition of the small sentences x sentences Gram matrix
        vals, vecs = np.linalg.eigh((m @ m.T).astype(np.float64))
        order = np.argsort(vals)[::-1][:k]
        vals, vecs = np.clip(vals[order], 0, None), vecs[:, order]
        emb = (vecs * np.sqrt(vals)).astype(np.float32)
    else:
        # long videos: randomized SVD (two power iterations), a few hundred milliseconds for hours of speech
        rng = np.random.default_rng(0)
        q, _ = np.linalg.qr(m @ rng.standard_normal((len(vocab), k + 10)).astype(np.float32))
        for _ in range(2):
            q, _ = np.linalg.qr(m @ (m.T @ q))
        u, s, _ = np.linalg.svd(q.T @ m, full_matrices=False)
        emb = ((q @ u[:, :k]) * s[:k]).astype(np.float32)
    lsa = _unit(emb)
    # Blend with the words themselves (a random projection keeps the vectors small): cosine similarity becomes
    # 60% shared words + 40% latent topics, which stays sensible for short transcripts where LSA alone is noisy.
    proj = np.random.default_rng(7).standard_normal((len(vocab), RAW_DIM)).astype(np.float32) / np.sqrt(RAW_DIM)
    raw = _unit(m @ proj)
    return _unit(np.hstack([np.sqrt(0.6) * raw, np.sqrt(0.4) * lsa]))


def _unit(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    return np.divide(x, norms, out=np.zeros_like(x), where=norms > 1e-9)


def embed_sentences(sentences: list[dict], opts: dict | None = None) -> Embeddings:
    return embed_texts([s["text"] for s in sentences], opts=opts)


def cos_cal(emb: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    """Cosine of two vectors with the video's baseline removed: unrelated is about 0, the same thing is 1."""
    c = cos(a, b)
    base = float(getattr(emb, "baseline", 0.0) or 0.0)
    return c if base <= 0 else max(-1.0, min(1.0, (c - base) / (1.0 - base)))


def cos(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(a @ b / (na * nb)) if na > 1e-9 and nb > 1e-9 else 0.0


def window_vector(emb: np.ndarray, s0: int, s1: int) -> np.ndarray:
    v = emb[s0:s1 + 1].mean(axis=0) if s1 >= s0 >= 0 and len(emb) else np.zeros(emb.shape[1] if emb.ndim == 2 else 1)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def features(emb: np.ndarray, s0: int, s1: int) -> dict:
    """Semantic shape of the sentence range [s0, s1]: does it stay on one topic (coherence, min_adjacent), does
    the ending tie back to the opening (closure), does it lean on what was said just before (context_dependency),
    and is it about something the rest of the video is not (novelty: the share of same-length windows that sit
    closer to the video's centre)."""
    if s0 < 0 or not len(emb):
        return {"coherence": 0.5, "min_adjacent": 0.5, "closure": 0.0, "context_dependency": 0.0, "novelty": 0.5,
                "score": 0.5}
    vecs = emb[s0:s1 + 1]
    centroid = window_vector(emb, s0, s1)
    live = [v for v in vecs if np.linalg.norm(v) > 1e-9]
    coherence = float(np.mean([cos_cal(emb, v, centroid) for v in live])) if live else 0.5
    adj = [cos_cal(emb, vecs[k], vecs[k + 1]) for k in range(len(vecs) - 1)
           if np.linalg.norm(vecs[k]) > 1e-9 and np.linalg.norm(vecs[k + 1]) > 1e-9]
    min_adjacent = min(adj) if adj else 1.0
    closure = cos_cal(emb, vecs[0], vecs[-1]) if len(vecs) > 1 else 0.0
    before = emb[max(0, s0 - 3):s0]
    context_dependency = cos_cal(emb, vecs[0], before.mean(axis=0)) if len(before) else 0.0
    novelty = _novelty(emb, s0, s1)
    coherence01 = max(0.0, min(1.0, coherence))
    score = (0.4 * coherence01 + 0.2 * max(0.0, closure) + 0.2 * (1.0 - max(0.0, context_dependency))
             + 0.2 * max(0.0, min(1.0, novelty)))
    return {"coherence": round(coherence, 3), "min_adjacent": round(min_adjacent, 3), "closure": round(closure, 3),
            "context_dependency": round(context_dependency, 3), "novelty": round(novelty, 3),
            "score": round(score, 3)}


def _novelty(emb: np.ndarray, s0: int, s1: int) -> float:
    """How far the window sits from the video's centre, as the share of all windows of the same length that are
    closer to it (0: the most typical passage of the video, 1: the most distinct one). Scale-free, so it means the
    same thing in both vector spaces."""
    n = len(emb)
    width = s1 - s0 + 1
    if n <= width or width <= 0:
        return 0.5
    video = np.asarray(emb, dtype=np.float32).mean(axis=0)
    if np.linalg.norm(video) < 1e-9:
        return 0.5
    arr = np.asarray(emb, dtype=np.float32)
    sums = np.cumsum(np.vstack([np.zeros((1, arr.shape[1]), dtype=np.float32), arr]), axis=0)
    windows = (sums[width:] - sums[:-width])  # every window's summed vector
    norms = np.linalg.norm(windows, axis=1)
    central = np.divide(windows @ video, norms * float(np.linalg.norm(video)), out=np.zeros(len(windows)),
                        where=norms > 1e-9)
    mine = central[s0] if s0 < len(central) else float(np.mean(central))
    others = np.delete(central, s0) if s0 < len(central) else central
    return float(np.mean(others > mine)) if len(others) else 0.5

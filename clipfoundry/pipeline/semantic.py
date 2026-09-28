"""Local sentence embeddings for semantic analysis (no downloads, no network).

Each sentence of a video becomes a dense vector: TF-IDF over the video's own content words, word stems and word
pairs (randomly projected to a fixed size), blended with a latent semantic analysis of the same matrix (an SVD), so
sentences about the same thing end up close together even when they use different words that co-occur elsewhere in
the video. This is enough to see whether a clip stays on one topic, ties
its ending back to its opening, leans on what was said just before it, or repeats another clip.
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np

from .text_utils import content_tokens

MAX_VOCAB = 3000
DIM = 48
RAW_DIM = 256


def _terms(text: str) -> list[str]:
    toks = content_tokens(text)
    stems = [f"~{t[:4]}" for t in toks if len(t) >= 5]  # "runners"/"running" share "~runn"
    return toks + stems + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]


def embed_texts(texts: list[str], dim: int = DIM) -> np.ndarray:
    """Unit vectors (len(texts) x d). Texts without content words get a zero vector."""
    n = len(texts)
    if n == 0:
        return np.zeros((0, 1), dtype=np.float32)
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


def embed_sentences(sentences: list[dict]) -> np.ndarray:
    return embed_texts([s["text"] for s in sentences])


def cos(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(a @ b / (na * nb)) if na > 1e-9 and nb > 1e-9 else 0.0


def window_vector(emb: np.ndarray, s0: int, s1: int) -> np.ndarray:
    v = emb[s0:s1 + 1].mean(axis=0) if s1 >= s0 >= 0 and len(emb) else np.zeros(emb.shape[1] if emb.ndim == 2 else 1)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def features(emb: np.ndarray, s0: int, s1: int) -> dict:
    """Semantic shape of the sentence range [s0, s1]."""
    if s0 < 0 or not len(emb):
        return {"coherence": 0.5, "min_adjacent": 0.5, "closure": 0.0, "context_dependency": 0.0, "novelty": 0.5,
                "score": 0.5}
    vecs = emb[s0:s1 + 1]
    centroid = window_vector(emb, s0, s1)
    live = [v for v in vecs if np.linalg.norm(v) > 1e-9]
    coherence = float(np.mean([cos(v, centroid) for v in live])) if live else 0.5
    adj = [cos(vecs[k], vecs[k + 1]) for k in range(len(vecs) - 1)
           if np.linalg.norm(vecs[k]) > 1e-9 and np.linalg.norm(vecs[k + 1]) > 1e-9]
    min_adjacent = min(adj) if adj else 1.0
    closure = cos(vecs[0], vecs[-1]) if len(vecs) > 1 else 0.0
    before = emb[max(0, s0 - 3):s0]
    context_dependency = cos(vecs[0], before.mean(axis=0)) if len(before) else 0.0
    video = emb.mean(axis=0)
    novelty = 1.0 - max(0.0, cos(centroid, video))
    coherence01 = max(0.0, min(1.0, coherence))
    score = (0.4 * coherence01 + 0.2 * max(0.0, closure) + 0.2 * (1.0 - max(0.0, context_dependency))
             + 0.2 * max(0.0, min(1.0, novelty)))
    return {"coherence": round(coherence, 3), "min_adjacent": round(min_adjacent, 3), "closure": round(closure, 3),
            "context_dependency": round(context_dependency, 3), "novelty": round(novelty, 3),
            "score": round(score, 3)}

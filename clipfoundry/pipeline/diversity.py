"""Diversity selection: the final clips of a source must be meaningfully different.

Two candidates are compared on timestamp overlap, transcript similarity, semantic similarity (embeddings), topic
overlap (keywords), hook structure (how they open) and punchline similarity (how they end). Candidates are taken
best-first; one that is too close to a clip already chosen, or to a clip that was already published or scheduled,
is rejected with the reason. Every chosen clip gets a Diversity Score (100 = unlike anything else chosen).
"""
from __future__ import annotations

import numpy as np

from . import fingerprint, semantic
from .scoring import rejection
from .text_utils import SETUP_PHRASES, content_tokens, cosine, count_phrases, tf_vector

SIMILAR = 0.55            # combined similarity at which a clip counts as a variant of another
OVERLAP = 0.15            # share of the shorter clip that may overlap another clip
PRIOR_TEXT = 0.6          # MinHash similarity to a published/scheduled clip that makes it a repeat


def _opener_type(text: str) -> str:
    low = text.lower().strip()
    if low.rstrip().endswith("?"):
        return "question"
    if count_phrases(low[:40], ["here's", "here is", "the reason", "the truth", "the secret", "the problem"]):
        return "reveal"
    if count_phrases(low[:30], SETUP_PHRASES):
        return "setup"
    if low.startswith(("i ", "i'm", "my ", "when i")):
        return "story"
    return "statement"


def _first_last(r: dict, sentences: list[dict]) -> tuple[str, str]:
    if r.get("s0", -1) < 0:
        return "", ""
    return sentences[r["s0"]]["text"], sentences[r["s1"]]["text"]


def similarity(a: dict, b: dict, sentences: list[dict], emb: np.ndarray | None = None) -> dict:
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    overlap = max(0.0, inter) / max(0.1, min(a["end"] - a["start"], b["end"] - b["start"]))
    ta, tb = a.get("caption_text") or a.get("text") or "", b.get("caption_text") or b.get("text") or ""
    transcript = cosine(tf_vector(ta), tf_vector(tb))
    sem = 0.0
    if emb is not None and len(emb) and a.get("s0", -1) >= 0 and b.get("s0", -1) >= 0:
        sem = max(0.0, semantic.cos(semantic.window_vector(emb, a["s0"], a["s1"]),
                                    semantic.window_vector(emb, b["s0"], b["s1"])))
    ka, kb = set(content_tokens(ta)), set(content_tokens(tb))
    topic = len(ka & kb) / len(ka | kb) if ka and kb else 0.0
    fa, la = _first_last(a, sentences)
    fb, lb = _first_last(b, sentences)
    hook = 0.5 * (_opener_type(fa) == _opener_type(fb)) + 0.5 * cosine(tf_vector(fa), tf_vector(fb)) if fa and fb \
        else 0.0
    punch = cosine(tf_vector(la), tf_vector(lb)) if la and lb else 0.0
    combined = max(min(1.0, overlap), 0.35 * transcript + 0.30 * sem + 0.15 * topic + 0.10 * hook + 0.10 * punch)
    return {"overlap": round(overlap, 3), "transcript": round(transcript, 3), "semantic": round(sem, 3),
            "topic": round(topic, 3), "hook": round(hook, 3), "punchline": round(punch, 3),
            "combined": round(combined, 3)}


def prior_repeat(text: str, prior: list[dict]) -> dict | None:
    """The published/scheduled clip this text repeats, if any ({clip_id, similarity, title})."""
    sig = fingerprint.text_signature(text)
    best = None
    for p in prior:
        s = fingerprint.text_similarity(sig, p.get("text_sig") or [])
        if s >= PRIOR_TEXT and (best is None or s > best["similarity"]):
            best = {"clip_id": p["clip_id"], "similarity": round(s, 3), "title": p.get("title_norm", "")}
    return best


def select(results: list[dict], count: int, min_score: float, sentences: list[dict], emb: np.ndarray | None = None,
           min_quality: float = 0.0, prior: list[dict] | None = None, score_key: str = "clip_score"
           ) -> tuple[list[dict], list[dict]]:
    """(chosen, rejected with reasons). Best first; quality gate first, then diversity. Never fills up the count
    with near-duplicates or weak clips."""
    chosen: list[dict] = []
    rejected: list[dict] = []
    prior = prior or []
    for r in sorted(results, key=lambda r: r.get(score_key, r["score"]), reverse=True):
        reasons = rejection(r, min_score)
        if r.get(score_key, r["score"]) < min_quality:
            reasons.append(f"Clip Score {r.get(score_key, r['score']):.0f} is below the minimum of {min_quality:.0f}")
        if not reasons:
            sims = [(c, similarity(r, c, sentences, emb)) for c in chosen]
            close = max(sims, key=lambda x: x[1]["combined"], default=None)
            if close and close[1]["overlap"] > OVERLAP:
                reasons.append(f"Overlaps a better clip (“{close[0].get('title', '')[:60]}”)")
            elif close and close[1]["combined"] >= SIMILAR:
                reasons.append(f"Too similar to a better clip (“{close[0].get('title', '')[:60]}”, "
                               f"{close[1]['combined']:.0%} alike)")
            repeat = prior_repeat(r.get("caption_text") or "", prior)
            if repeat:
                reasons.append(f"Repeats a clip that was already published or scheduled ({repeat['similarity']:.0%} "
                               "alike)")
            if not reasons:
                if len(chosen) >= count:
                    rejected.append({**r, "reasons": ["Passed, but the clips-per-source limit was reached"]})
                    continue
                worst = close[1]["combined"] if close else 0.0
                r["diversity"] = {"score": round(100 * (1 - worst), 1),
                                  "closest": close[0].get("title", "") if close else "",
                                  "components": close[1] if close else {}}
                chosen.append(r)
                continue
        rejected.append({**r, "reasons": reasons})
    return chosen, rejected

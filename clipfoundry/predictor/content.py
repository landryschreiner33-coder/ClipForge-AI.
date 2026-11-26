"""What a clip says, judged on its own: the 11-factor Viral Potential (pipeline/virality.py) of the words heard in
the clip, read as one moment from its first word to its last. Clip picking measures a moment inside its recording;
this measures the clip as it is now (after trims, removed pauses and sped-up parts)."""
from __future__ import annotations

import numpy as np

from ..pipeline import candidates as cand_mod
from ..pipeline import virality
from ..pipeline.audio import Loudness
from ..pipeline.text_utils import build_sentences
from .signals import Signals

MIN_WORDS = 6


def loudness_of(sig: Signals) -> Loudness:
    """A loudness envelope (0.1 s frames) from the clip's own sound, for the factors that read loudness."""
    if sig.level is None:
        return Loudness({"hop": 0.1, "db": [-20.0] * max(10, int(sig.duration * 10))})
    db = np.repeat(np.asarray(sig.level, dtype=float), 5)  # 0.5 s bins -> 0.1 s frames
    return Loudness({"hop": 0.1, "db": np.round(db, 1).tolist()})


def analyze(sig: Signals, settings: dict | None = None) -> dict | None:
    """The 11-factor analysis of the clip's words (None when it says fewer than MIN_WORDS words)."""
    words = [{"w": w["w"], "start": float(w["start"]), "end": float(w["end"]),
              **({"p": w["p"]} if w.get("p") is not None else {})} for w in sig.words if str(w.get("w", "")).strip()]
    if len(words) < MIN_WORDS:
        return None
    sentences = build_sentences(words)
    if not sentences:
        return None
    settings = settings or {}
    feats = cand_mod.sentence_features(sentences, words)
    length = max(1.0, sig.duration)
    opts = {"min_duration": min(float(settings.get("min_duration") or 15.0), length),
            "max_duration": max(float(settings.get("max_duration") or 60.0), length),
            "target_duration": float(settings.get("target_duration") or 30.0)}
    r = virality.analyze(0, len(sentences) - 1, sentences, feats, words, loudness_of(sig), opts)
    r.pop("tf", None)
    return {"viral_potential": r["viral_potential"], "factors": r["factors"], "structure": r["structure"],
            "flags": r["flags"], "subscores": r["subscores"], "sentences": [
                {"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"]} for s in sentences]}

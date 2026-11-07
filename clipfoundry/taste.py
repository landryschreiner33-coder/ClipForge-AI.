"""ClipForge AI learns your taste (docs/clipforge/SMARTER_AI.md).

Every choice you make about a clip is a lesson: leaving a clip out (unticking it), putting it back, exporting it,
publishing it. Each lesson is stored with the clip's measured profile (the eleven virality factors, its length, how it
opens) and, once there are enough lessons on both sides (12 in all, at least 4 kept and 4 left out), a small model
is fitted to them: a regularised logistic regression on standardised features, a few hundred numbers, trained in
milliseconds on this computer. From then on every new finalist gets a taste adjustment of at most ±6 Clip Score
points, with the reason in words ("you tend to keep clips with a stronger hook and leave out long ones"), and the
same words go into the brief the model reads. The Brain → Memory page shows what was learned and can forget it.

Nothing here leaves the computer, nothing is guessed from a single click, and the local analysis still decides
what is a clip at all: taste only reorders the finalists a little.
"""
from __future__ import annotations

import json
import logging
import time

import numpy as np

from . import db
from .pipeline import virality

log = logging.getLogger("clipfoundry.taste")

FEATURES = [*virality.FACTORS, "viral_potential", "duration", "question_open", "story", "hook_words"]
WORDS = {"hook": "a stronger hook", "opening": "a stronger opening", "curiosity": "more curiosity",
         "emotion": "more emotion", "density": "denser information", "payoff": "a clearer payoff",
         "standalone": "clips that stand alone", "pacing": "faster pacing", "uniqueness": "more unusual moments",
         "clarity": "clearer wording", "retention": "a stronger retention shape", "viral_potential": "a higher score",
         "duration": "longer clips", "question_open": "clips that open on a question", "story": "stories",
         "hook_words": "hook words in the first line"}
LESS = {"hook": "a weaker hook", "opening": "a weaker opening", "curiosity": "less curiosity", "emotion": "less emotion",
        "density": "thinner information", "payoff": "a vaguer payoff", "standalone": "clips that need context",
        "pacing": "slower pacing", "uniqueness": "more ordinary moments", "clarity": "muddier wording",
        "retention": "a weaker retention shape", "viral_potential": "a lower score", "duration": "shorter clips",
        "question_open": "clips that do not open on a question", "story": "moments that are not stories",
        "hook_words": "no hook words in the first line"}
KINDS = {"exported": 1.0, "published": 1.0, "reselected": 0.6, "deselected": -1.0, "deleted": -0.8}
MIN_EVENTS = 12
MIN_EACH = 4
WEIGHT = 6.0            # the most your taste can move a Clip Score
L2 = 1.0
MAX_EVENTS = 2000
_models: dict[str, tuple[int, dict | None]] = {}


# ------------------------------------------------------------------ a clip as numbers
def features_from_summary(analysis: dict, duration: float) -> list[float] | None:
    """The stored analysis of a clip (virality.summary: factors 0-10) as the feature vector (all 0-1)."""
    factors = (analysis or {}).get("factors") or {}
    if not factors:
        return None
    x = [min(1.0, max(0.0, float(factors.get(k) or 0.0) / 10.0)) for k in virality.FACTORS]
    x.append(min(1.0, max(0.0, float(analysis.get("viral_potential") or 0.0) / 100.0)))
    x.append(min(1.0, max(0.0, float(duration or 0.0) / 90.0)))
    sig = analysis.get("signals") or {}
    x += [1.0 if sig.get("question_open") else 0.0, 1.0 if sig.get("story") else 0.0,
          min(1.0, float(sig.get("hook_words") or 0.0) / 3.0)]
    return x


def features_from_result(r: dict) -> list[float] | None:
    """A pipeline result (its `analysis` is the raw virality result) as the same feature vector."""
    a = r.get("analysis") or {}
    if not a.get("factors"):
        return None
    try:
        return features_from_summary(virality.summary(a), float(r["end"]) - float(r["start"]))
    except (KeyError, TypeError, ValueError):
        return None


def _workspace(clip: dict) -> str:
    project = db.get_project(str(clip.get("project_id") or "")) if clip.get("project_id") else None
    return str((project or {}).get("workspace_id") or "local")


def default_workspace() -> str:
    try:
        ws = db.scalar("SELECT workspace_id FROM projects GROUP BY workspace_id ORDER BY COUNT(*) DESC LIMIT 1")
    except Exception:  # noqa: BLE001
        ws = None
    return str(ws or "local")


# ------------------------------------------------------------------ lessons
def record(clip: dict, kind: str, workspace_id: str | None = None) -> dict | None:
    """One lesson from one choice about one clip; the latest choice of a kind replaces the earlier one, and
    unticking cancels an earlier re-ticking (and the other way round). Never fails the caller."""
    if kind not in KINDS or not clip or not clip.get("id"):
        return None
    try:
        duration = float(clip.get("duration") or (float(clip.get("end") or 0) - float(clip.get("start") or 0)))
        x = features_from_summary(clip.get("analysis") or {}, duration)
        if x is None:
            return None
        ws = workspace_id or _workspace(clip)
        db.execute("DELETE FROM taste_events WHERE clip_id = ? AND kind = ?", (clip["id"], kind))
        opposite = {"deselected": "reselected", "reselected": "deselected"}.get(kind)
        if opposite:
            db.execute("DELETE FROM taste_events WHERE clip_id = ? AND kind = ?", (clip["id"], opposite))
        row = {"id": db.new_id(), "workspace_id": ws, "project_id": str(clip.get("project_id") or ""),
               "clip_id": clip["id"], "kind": kind, "value": KINDS[kind], "features": json.dumps(x),
               "created_at": time.time()}
        db.insert("taste_events", row)
        _models.pop(ws, None)
        return row
    except Exception:  # noqa: BLE001 - a lesson is never worth failing the action that taught it
        log.exception("taste: recording failed")
        return None


def published(clip_id: str) -> None:
    try:
        clip = db.get_clip(clip_id)
    except Exception:  # noqa: BLE001
        clip = None
    if clip:
        record(clip, "published")


def events(ws: str) -> list[dict]:
    return db.select("taste_events", "workspace_id = ?", (ws,), "created_at DESC", limit=MAX_EVENTS)


# ------------------------------------------------------------------ the model
def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def train(ws: str) -> dict | None:
    """Fit the taste model on the workspace's lessons (None while there are too few on either side)."""
    rows = events(ws)
    if len(rows) < MIN_EVENTS:
        return None
    X, y, w = [], [], []
    for r in rows:
        try:
            x = json.loads(r["features"])
        except (TypeError, ValueError):
            continue
        if len(x) != len(FEATURES):
            continue
        X.append(x)
        y.append(1.0 if float(r["value"]) > 0 else 0.0)
        w.append(abs(float(r["value"])))
    if not X:
        return None
    Xa, ya, wa = np.asarray(X, dtype=np.float64), np.asarray(y), np.asarray(w)
    pos, neg = int(ya.sum()), int(len(ya) - ya.sum())
    if pos < MIN_EACH or neg < MIN_EACH:
        return None
    # both sides weigh the same in all, so a person who exports a lot does not teach "keep everything"
    wa = wa / np.where(ya > 0, wa[ya > 0].sum(), wa[ya == 0].sum()) * 0.5
    mu, sd = Xa.mean(axis=0), Xa.std(axis=0) + 1e-6
    Z = (Xa - mu) / sd
    th, b = np.zeros(Z.shape[1]), 0.0
    lr = 0.5
    for _ in range(400):
        p = _sigmoid(Z @ th + b)
        err = wa * (p - ya)
        th -= lr * (Z.T @ err + L2 * th / len(ya))
        b -= lr * float(err.sum())
    model = {"weights": [round(float(v), 5) for v in th], "bias": round(float(b), 5), "mu": [round(float(v), 5) for v in mu],
             "sd": [max(1e-4, round(float(v), 5)) for v in sd], "n": len(ya), "positives": pos, "negatives": neg,
             "features": list(FEATURES), "trained_at": time.time()}
    db.execute("INSERT OR REPLACE INTO taste_models (workspace_id, model, n, trained_at) VALUES (?, ?, ?, ?)",
               (ws, json.dumps(model), len(rows), model["trained_at"]))
    return model


def model(ws: str) -> dict | None:
    """The current model (trained when the lessons changed), or None while there are too few lessons."""
    try:
        n = int(db.scalar("SELECT COUNT(*) FROM taste_events WHERE workspace_id = ?", (ws,)) or 0)
    except Exception:  # noqa: BLE001
        return None
    cached = _models.get(ws)
    if cached and cached[0] == n:
        return cached[1]
    m = None
    if n >= MIN_EVENTS:
        try:
            row = db.fetch("taste_models", ws, key="workspace_id")
            if row and int(row.get("n") or -1) == n:
                m = json.loads(row["model"])
            else:
                m = train(ws)
        except Exception:  # noqa: BLE001
            log.exception("taste: model failed")
            m = None
    _models[ws] = (n, m)
    return m


def predict(m: dict, x: list[float]) -> dict:
    """{p, adjust, why} for one feature vector."""
    sd = np.maximum(np.asarray(m["sd"], dtype=np.float64), 1e-4)
    z = np.clip((np.asarray(x, dtype=np.float64) - np.asarray(m["mu"])) / sd, -4.0, 4.0)  # a feature that never
    contrib = z * np.asarray(m["weights"])                                                  # varied cannot explode
    p = float(_sigmoid(np.array([contrib.sum() + float(m["bias"])]))[0])
    adjust = max(-WEIGHT, min(WEIGHT, 2.0 * WEIGHT * (p - 0.5)))
    order = np.argsort(-np.abs(contrib))
    why = []
    for k in order[:2]:
        if abs(contrib[k]) < 0.15:
            continue
        name = m["features"][k]
        more = contrib[k] > 0
        why.append(_describe(name, more if float(m["weights"][k]) > 0 else not more, like=adjust >= 0))
    return {"p": round(p, 3), "adjust": round(adjust, 1), "why": why}


def _describe(name: str, more: bool, like: bool) -> str:
    """One feature's part in a verdict, in words: "a stronger hook" / "shorter clips"."""
    return (WORDS if more else LESS).get(name, name.replace("_", " "))


def preferences(m: dict) -> list[str]:
    """The strongest learned preferences in words, for the Memory page and the brief."""
    w = np.asarray(m["weights"])
    out = []
    for k in np.argsort(-np.abs(w))[:3]:
        if abs(w[k]) < 0.1:
            continue
        name = m["features"][k]
        out.append((WORDS if w[k] > 0 else LESS).get(name, name.replace("_", " ")))
    return out


def brief_line(ws: str) -> str:
    m = model(ws) if ws else None
    if not m:
        return ""
    prefs = preferences(m)
    return f"The owner's own choices so far ({m['n']} of them): they keep clips with " + ", ".join(prefs) + "." \
        if prefs else ""


def apply(results: list[dict], opts: dict) -> int:
    """Give every evaluated result a `taste` verdict ({p, adjust, why}); returns how many got one."""
    ws = str(opts.get("workspace_id") or "")
    m = model(ws) if ws else None
    if not m:
        return 0
    n = 0
    for r in results:
        x = features_from_result(r)
        if x is None:
            continue
        r["taste"] = predict(m, x)
        n += 1
    return n


# ------------------------------------------------------------------ the Memory page
def status(ws: str) -> dict:
    rows = events(ws)
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    pos = sum(1 for r in rows if float(r["value"]) > 0)
    neg = len(rows) - pos
    m = model(ws)
    return {"events": len(rows), "by_kind": by_kind, "kept": pos, "left_out": neg, "ready": bool(m),
            "needed": {"events": max(0, MIN_EVENTS - len(rows)), "kept": max(0, MIN_EACH - pos),
                       "left_out": max(0, MIN_EACH - neg)},
            "preferences": preferences(m) if m else [], "trained_at": (m or {}).get("trained_at"),
            "weight": WEIGHT, "features": list(FEATURES)}


def forget(ws: str) -> int:
    n = db.execute("DELETE FROM taste_events WHERE workspace_id = ?", (ws,))
    db.execute("DELETE FROM taste_models WHERE workspace_id = ?", (ws,))
    _models.pop(ws, None)
    return int(n or 0)

"""How well the viral predictor matched your real results, and what it learns from them.

Every post keeps what the predictor said when it went out (publish/jobs.feature_snapshot → "prediction"). Once the
results are in (the Learning Worker reads them 48 hours after a post was shown), this compares the two:

- Accuracy, per platform: does a higher predicted score go with more views (Spearman rank correlation with log
  views, from MIN_RANK posts), how often the predicted top third beat the platform's median, and the median views of
  each score band. With the average percentage viewed (YouTube, with Google's approval for derived metrics), how far
  the predicted average watched was from the real one.
- Calibration: the hold model's average watched against the real average percentage viewed, a straight line fitted
  from MIN_CAL posts and pulled toward "no change" while there are few (n / (n + SHRINK_K)).
- Weights: from MIN_WEIGHTS posts, how well each part of the score (what it says, hook, how much is watched, memory,
  look) ordered your results. A weight may move at most MAX_SHIFT (40%) from its designed value, and at most STEP
  (10%) per update, so one lucky post never becomes a rule.

Learning reads only the posts the Learning Worker itself may learn from (your current audience, enough views, and
YouTube only with the approval above). Pausing the Brain pauses this too: the designed values are used.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict

import numpy as np

from .. import learning
from . import STATE_ACCURACY, STATE_LEARNED, model

MIN_RANK = 10
MIN_CAL = 15
MIN_WEIGHTS = 30
MAX_SHIFT = 0.40
STEP = 0.10
SHRINK_K = 20.0
SLOPE_RANGE = (0.3, 2.0)


def _pred(r: dict) -> dict | None:
    p = r.get("prediction")
    return p if isinstance(p, dict) and p.get("model") == model.MODEL_VERSION and p.get("score") is not None else None


def accuracy(rs: list[dict]) -> dict:
    """How the predictions compare with the results, per platform."""
    out: dict = {"at": round(time.time(), 1), "posts": 0, "platforms": {}, "min_posts": MIN_RANK}
    by = defaultdict(list)
    for r in rs:
        p = _pred(r)
        if p and r.get("views") is not None:
            by[r["platform"]].append((p, r))
    for platform, group in sorted(by.items()):
        out["posts"] += len(group)
        views = np.array([float(r["views"]) for _, r in group])
        median = float(np.median(views)) if len(views) else 0.0
        item: dict = {"posts": len(group), "median_views": round(median, 1), "spearman": None, "top_third_hit": None,
                      "bands": [], "avg_view_error": None, "avg_view_posts": 0}
        if len(group) >= MIN_RANK:
            rho = learning.spearman([float(p["score"]) for p, _ in group], [math.log1p(v) for v in views])
            item["spearman"] = None if rho is None else round(rho, 3)
            order = sorted(group, key=lambda pr: -float(pr[0]["score"]))
            top = order[:max(1, len(order) // 3)]
            item["top_third_hit"] = round(sum(float(r["views"]) > median for _, r in top) / len(top), 3)
        for _, name in model.BANDS:
            vals = [float(r["views"]) for p, r in group if p.get("band") == name]
            if vals:
                item["bands"].append({"band": name, "posts": len(vals), "median_views": round(float(np.median(vals)), 1),
                                      "vs_median": round(float(np.median(vals)) / median, 2) if median > 0 else None})
        pairs = [(float(p["avg_view_calibrated"] if p.get("avg_view_calibrated") is not None else p["avg_view"]),
                  float(r["avg_view_percentage"])) for p, r in group
                 if p.get("avg_view") is not None and r.get("avg_view_percentage") is not None]
        if pairs:
            item["avg_view_posts"] = len(pairs)
            item["avg_view_error"] = round(float(np.mean([abs(a - b) for a, b in pairs])), 1)
        out["platforms"][platform] = item
    return out


def calibrate(rs: list[dict]) -> dict | None:
    """The hold model's average watched against the real average percentage viewed (both 0-1)."""
    pairs = [(float(p["avg_view"]) / 100.0, float(r["avg_view_percentage"]) / 100.0) for r in rs
             if (p := _pred(r)) and p.get("avg_view") is not None and r.get("avg_view_percentage") is not None]
    if len(pairs) < MIN_CAL:
        return None
    x, y = np.array([a for a, _ in pairs]), np.array([b for _, b in pairs])
    if float(x.std()) < 1e-3:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    slope = float(np.clip(slope, *SLOPE_RANGE))
    intercept = float(np.mean(y) - slope * np.mean(x))  # the line through the means with the bounded slope
    n = len(pairs)
    return {"slope": round(slope, 4), "intercept": round(intercept, 4), "n": n, "shrink": round(n / (n + SHRINK_K), 3)}


def _perf(rs: list[dict]) -> dict[str, float]:
    """Each post's result against its own platform: z-score of log views, extremes capped."""
    out = {}
    by = defaultdict(list)
    for r in rs:
        by[r["platform"]].append(r)
    for group in by.values():
        v = np.array([math.log1p(float(r["views"])) for r in group])
        lo, hi = np.percentile(v, [10, 90]) if len(v) >= 3 else (v.min(), v.max())
        w = np.clip(v, lo, hi)
        z = (w - w.mean()) / (w.std() or 1.0)
        for r, zz in zip(group, z):
            out[r["publication_id"]] = float(zz)
    return out


def weights(rs: list[dict], previous: dict[str, float] | None = None) -> dict | None:
    """Learned weights of the score's parts, bounded (None until MIN_WEIGHTS posts)."""
    usable = [(p, r) for r in rs if (p := _pred(r)) and r.get("views") is not None]
    if len(usable) < MIN_WEIGHTS:
        return None
    perf = _perf([r for _, r in usable])
    previous = previous or {}
    out, evidence = {}, {}
    for k, base in model.WEIGHTS.items():
        pairs = [(float(p["components"][k]), perf[r["publication_id"]]) for p, r in usable
                 if (p.get("components") or {}).get(k) is not None]
        start = float(previous.get(k, base))
        if len(pairs) < MIN_WEIGHTS:
            out[k] = start
            continue
        rho = learning.spearman([a for a, _ in pairs], [b for _, b in pairs])
        if rho is None:
            out[k] = start
            continue
        aim = base * (1 + max(-MAX_SHIFT, min(MAX_SHIFT, rho)))
        out[k] = round(max(start * (1 - STEP), min(start * (1 + STEP), aim)), 4)
        evidence[k] = {"rho": round(rho, 3), "posts": len(pairs), "aim": round(aim, 4)}
    return {"weights": out, "evidence": evidence, "n": len(usable)}


def learn(rs: list[dict]) -> dict:
    """Check and learn from the Learning Worker's rows (each with its "prediction" snapshot); keeps the results in
    the autopilot state. Returns a short summary."""
    from ..autopilot import state

    acc = accuracy(rs)
    prev = state.get(STATE_LEARNED) or {}
    if prev.get("model") != model.MODEL_VERSION:
        prev = {}
    cal = calibrate(rs)
    w = weights(rs, (prev.get("weights") or None))
    learned = {"model": model.MODEL_VERSION, "at": round(time.time(), 1)}
    if cal:
        learned["hold"] = cal
    if w:
        learned["weights"] = w["weights"]
        learned["evidence"] = w["evidence"]
        learned["n"] = w["n"]
    acc["calibration"] = cal
    acc["weights"] = (w or {}).get("weights")
    acc["evidence"] = (w or {}).get("evidence")
    state.put(STATE_ACCURACY, acc)
    if cal or w:
        state.put(STATE_LEARNED, learned)
    parts = [f"{acc['posts']} post{'s' if acc['posts'] != 1 else ''} with a prediction"]
    for platform, item in acc["platforms"].items():
        if item["spearman"] is not None:
            parts.append(f"{platform}: rank match {item['spearman']:+.2f}")
    if cal:
        parts.append(f"average watched calibrated on {cal['n']} posts")
    if w:
        parts.append(f"weights learned from {w['n']} posts")
    return {"message": "Viral predictor: " + "; ".join(parts) + ".", "accuracy": acc}


def view() -> dict:
    """The accuracy panel's data (Brain → Performance)."""
    from ..autopilot import state

    acc = state.get(STATE_ACCURACY) or {"posts": 0, "platforms": {}, "min_posts": MIN_RANK}
    lrn = state.get(STATE_LEARNED) or {}
    return {**acc, "min_posts": MIN_RANK, "min_calibration": MIN_CAL, "min_weights": MIN_WEIGHTS,
            "designed_weights": model.WEIGHTS, "learned": lrn if lrn.get("model") == model.MODEL_VERSION else None,
            "note": model.ESTIMATE_NOTE}

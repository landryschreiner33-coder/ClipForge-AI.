"""Groundwork for learning from real results.

Every publication stores a snapshot of the clip's scores at publish time (`features`), and every statistics refresh
stores the platform's real numbers (`performance`). `dataset()` joins the two, one row per published clip, ready for
a future step that tunes the Viral Potential weights to what actually worked for this creator.

Nothing here changes the ranking yet. `ranking_check()` only reports how well the existing estimate ordered the
clips, and only once enough real data exists: it never fills gaps or makes up numbers.
"""
from __future__ import annotations

import csv
import io
import math

import numpy as np

from . import db

MIN_SAMPLES = 10
OUTCOMES = db.METRICS
FEATURES = ["viral_potential", "hook", "retention", "context", "engagement", "duration"]


def dataset() -> list[dict]:
    latest = db.latest_performance()
    rows = []
    for pub in db.list_publications():
        perf = latest.get(pub["id"])
        if pub["status"] not in ("done", "action_needed") or not perf:
            continue
        f = pub.get("features") or {}
        sub = f.get("subscores") or {}
        row = {"publication_id": pub["id"], "clip_id": pub["clip_id"], "platform": pub["platform"],
               "privacy": pub.get("privacy") or pub.get("requested_privacy"), "published_at": pub["created_at"],
               "hours_since_publish": round((perf["fetched_at"] - pub["created_at"]) / 3600, 1),
               "fetched_at": perf["fetched_at"], "source": perf["source"],
               "viral_potential": f.get("viral_potential"), "hook": sub.get("hook"), "retention": sub.get("retention"),
               "context": sub.get("context"), "engagement": sub.get("engagement"), "duration": f.get("duration"),
               "category": f.get("category"), "structure": f.get("structure"), "version": f.get("version"),
               **{f"factor_{k}": v for k, v in (f.get("factors") or {}).items()},
               **{k: perf.get(k) for k in OUTCOMES}}
        rows.append(row)
    return rows


def _ranks(x: list[float]) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    ranks[order] = np.arange(len(x), dtype=float)
    xs = np.asarray(x, dtype=float)
    for v in set(xs.tolist()):  # ties share the average rank
        idx = xs == v
        ranks[idx] = ranks[idx].mean()
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def ranking_check(rows: list[dict] | None = None, metric: str = "views", platform: str | None = None) -> dict:
    """Rank correlation between the Viral Potential estimate and a real metric (None until enough samples)."""
    rows = dataset() if rows is None else rows
    pairs = [(r["viral_potential"], r[metric]) for r in rows
             if r.get("viral_potential") is not None and r.get(metric) is not None
             and (platform is None or r["platform"] == platform)]
    out = {"metric": metric, "platform": platform or "all", "samples": len(pairs), "min_samples": MIN_SAMPLES,
           "spearman": None}
    if len(pairs) >= MIN_SAMPLES:
        rho = spearman([p[0] for p in pairs], [math.log1p(p[1]) for p in pairs])
        out["spearman"] = None if rho is None else round(rho, 3)
    return out


def to_csv(rows: list[dict]) -> str:
    cols: list[str] = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
    return buf.getvalue()

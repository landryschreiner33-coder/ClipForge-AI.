"""Results compared by channel, niche, format or clip length: what your own posts did, read the same way for each.

Fair comparisons only:
- One platform and one audience at a time (learner.cohort): YouTube is never compared with TikTok, and posts your
  selected viewers saw are never mixed with public ones.
- Every post is read at the same age: the reading closest to 48 hours after your viewers could first watch it
  (learner._snapshot). A post younger than that is not counted yet.
- A group is compared with the rest of the same platform's posts, by their medians (one viral post moves a median
  little), and a difference counts as clear only when each side has at least MIN_POSTS posts and a permutation test
  on log views says a gap this size is unlikely by chance (p < CLEAR_P). Otherwise the answer is "too few posts" or
  "no clear difference yet", never a guess.
- Comparable periods: the last PERIOD_DAYS days against the PERIOD_DAYS before them, per platform.
- A number a platform does not report (TikTok's average % viewed, for example) is "not reported", never estimated.
  YouTube numbers are used only after you confirm Google's approval for derived metrics (learner.usable), as the
  YouTube Developer Policies require.

Every answer is what happened with your posts so far, not a promise of views. Each suggestion is a test you can run
next and check here 48 hours after the posts go out.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict

import numpy as np

from .. import db, learning
from . import learner

DIMENSIONS = {"channel": "Channel", "niche": "Niche", "format": "Format", "length": "Clip length"}
MIN_POSTS = 5          # posts on each side before a difference can count as clear
CLEAR_P = 0.1          # ... and how unlikely by chance it must be
PERIOD_DAYS = 28
PERMUTATIONS = 2000
FORMATS = {"split": "Gameplay + Facecam", "pip": "Picture-in-picture", "game": "Gameplay only", "fill": "Fill (crop)",
           "fit": "Fit (whole frame)"}
PLATFORM_NAMES = {"youtube": "YouTube", "tiktok": "TikTok"}
COHORT_NAMES = {"selected": "your selected viewers", "public": "the public", "public_requested": "public (requested)",
                "public_legacy": "public, posted before audiences", "unconfirmed": "an audience not confirmed yet",
                "owner_only": "only you"}
NOT_A_PROMISE = "What happened with your posts so far, read 48 hours after each went out. Not a promise of views."


def _format(clip: dict) -> str:
    if clip.get("category") == "story":
        return "Story clip"
    ri = clip.get("render_info") or {}
    return FORMATS.get(ri.get("layout") or "", "Not recorded")


def _channel(pub: dict, names: dict[str, str]) -> str:
    cid = pub.get("connection_id") or ""
    if cid not in names:
        conn = db.get_connection(cid) if cid else None
        names[cid] = (conn or {}).get("nickname") or (conn or {}).get("display_name") or \
            ("Removed account" if cid else "Unknown account")
    return names[cid]


def posts(settings: dict, now: float | None = None) -> list[dict]:
    """Every published post with a reading at about 48 hours: its platform, audience, channel, niche, format,
    length, when your viewers could first watch it, and its 48-hour views and average % viewed (None when the
    platform does not report it)."""
    now = now or time.time()
    out, names = [], {}
    for pub in db.list_publications():
        if pub["status"] not in ("done", "action_needed"):
            continue
        snap = learner._snapshot(pub)  # noqa: SLF001 - the shared "read at 48 hours" rule
        if not snap:
            continue
        clip = db.get_clip(pub["clip_id"]) or {}
        project = db.get_project(clip.get("project_id") or "") or {}
        source = db.fetch("sources", project.get("source_id") or "") if project.get("source_id") else None
        niche = ((source or {}).get("topic") or (source or {}).get("category") or clip.get("category") or "")
        length = (pub.get("features") or {}).get("duration") or clip.get("duration")
        out.append({"publication_id": pub["id"], "platform": pub["platform"], "cohort": learner.cohort(pub),
                    "channel": _channel(pub, names), "niche": niche.strip().lower() or "no niche recorded",
                    "format": _format(clip), "length": learner._duration_bucket(length),  # noqa: SLF001
                    "shown_at": learner.shown_at(pub), "views": float(snap["views"]),
                    "pct": None if snap.get("avg_view_percentage") is None else float(snap["avg_view_percentage"]),
                    "age_h": round((snap["fetched_at"] - learner.shown_at(pub)) / 3600, 1)})
    return out


def _median(xs: list[float]) -> float | None:
    return float(np.median(xs)) if xs else None


def _p_value(a: list[float], b: list[float], seed: int = 7) -> float:
    """How often shuffled posts give a gap in median log views at least this big (two-sided)."""
    la, lb = np.log1p(np.asarray(a, float)), np.log1p(np.asarray(b, float))
    seen = abs(np.median(la) - np.median(lb))
    both = np.concatenate([la, lb])
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(PERMUTATIONS):
        rng.shuffle(both)
        if abs(np.median(both[:len(la)]) - np.median(both[len(la):])) >= seen - 1e-12:
            hits += 1
    return (hits + 1) / (PERMUTATIONS + 1)


def _n(v: float) -> str:
    """A whole number with thousands separators, rounded half up like the app shows it."""
    return f"{math.floor(v + 0.5):,}"


def _tests(dim: str, name: str, where: str) -> dict[str, str]:
    """A test to run next for each verdict, worded for the dimension."""
    if dim == "channel":
        return {"more": f"Post {{n}} more on {name}", "fewer": f"Post {{n}} more on your other channels",
                "inconclusive": f"Post the same kind of clip on {name} and your other channels for the next 10, on the "
                                "same days and times, and compare again.",
                "higher": f"Put 6 of your next 10 posts on {name} and 4 on your other channels, to see whether it "
                          "holds.",
                "lower": f"Post the same kind of clip on {name} and a stronger channel for the next 10 to see whether "
                         "it is the channel or the clips."}
    what = {"format": f"{name} clips", "niche": f"clips about {name}", "length": f"clips of {name}"}[dim]
    return {"more": f"Post {{n}} more {what}{where}", "fewer": f"Post {{n}} more that are not {what}{where}",
            "inconclusive": f"Alternate {what} with your other posts for the next 10{where}, on the same days and "
                            "times, and compare again.",
            "higher": f"Make 6 of your next 10 posts {what}{where} and keep 4 as before, to see whether it holds.",
            "lower": f"Make your next 10 posts without {what}{where} and compare; then try a few again to check."}


def _verdict(name: str, dim: str, mine: list[dict], rest: list[dict], platform: str, channel_hint: str) -> dict:
    views, others = [r["views"] for r in mine], [r["views"] for r in rest]
    pcts = [r["pct"] for r in mine if r["pct"] is not None]
    out = {"group": name, "posts": len(mine), "others": len(rest), "median_views": _median(views),
           "median_pct": _median(pcts), "pct_reported": bool(pcts)}
    tests = _tests(dim, name, f" on {channel_hint}" if channel_hint and dim != "channel" else "")
    plat = PLATFORM_NAMES.get(platform, platform)
    if len(mine) < MIN_POSTS or len(rest) < MIN_POSTS:
        need_mine, need_rest = max(0, MIN_POSTS - len(mine)), max(0, MIN_POSTS - len(rest))
        out.update(verdict="too_few", ratio=None, p=None,
                   text=f"Too few posts to compare yet ({len(mine)} here, {len(rest)} others; at least {MIN_POSTS} "
                        f"each).",
                   test=(tests["more"].format(n=need_mine) if need_mine else tests["fewer"].format(n=need_rest))
                   + ", then look again 48 hours after the last one goes out.")
        return out
    mid, rest_mid = out["median_views"], _median(others)
    ratio = (mid + 1.0) / (rest_mid + 1.0)
    p = _p_value(views, others)
    out.update(ratio=round(ratio, 2), p=round(p, 3), test=tests["inconclusive" if p >= CLEAR_P else
                                                                "higher" if ratio > 1 else "lower"])
    if p >= CLEAR_P:
        out.update(verdict="inconclusive",
                   text=f"No clear difference yet: a median of {_n(mid)} views at 48 hours against {_n(rest_mid)} for "
                        "the others, and the posts overlap too much to tell.")
    elif ratio > 1:
        out.update(verdict="higher",
                   text=f"Higher so far: a median of {_n(mid)} views at 48 hours, about {ratio:.1f}× the "
                        f"{_n(rest_mid)} of your other {plat} posts.")
    else:
        out.update(verdict="lower",
                   text=f"Lower so far: a median of {_n(mid)} views at 48 hours against {_n(rest_mid)} for your "
                        f"other {plat} posts.")
    return out


def _periods(rows: list[dict], now: float) -> dict:
    span = PERIOD_DAYS * 86400
    recent = [r["views"] for r in rows if now - span <= r["shown_at"] < now]
    before = [r["views"] for r in rows if now - 2 * span <= r["shown_at"] < now - span]
    out = {"days": PERIOD_DAYS, "recent": {"posts": len(recent), "median_views": _median(recent)},
           "before": {"posts": len(before), "median_views": _median(before)}}
    if len(recent) < MIN_POSTS or len(before) < MIN_POSTS:
        out.update(verdict="too_few", text=f"Too few posts to compare the last {PERIOD_DAYS} days with the "
                                           f"{PERIOD_DAYS} before ({len(recent)} and {len(before)}; at least "
                                           f"{MIN_POSTS} each).")
        return out
    p = _p_value(recent, before)
    ratio = (_median(recent) + 1.0) / (_median(before) + 1.0)
    out.update(p=round(p, 3), ratio=round(ratio, 2))
    if p >= CLEAR_P:
        out.update(verdict="inconclusive", text=f"About the same as the {PERIOD_DAYS} days before: no clear "
                                                "difference.")
    else:
        out.update(verdict="higher" if ratio > 1 else "lower",
                   text=f"The last {PERIOD_DAYS} days: a median of {_n(_median(recent))} views at 48 hours against "
                        f"{_n(_median(before))} in the {PERIOD_DAYS} days before ({ratio:.1f}×).")
    return out


def compare(by: str = "format", settings: dict | None = None, now: float | None = None) -> dict:
    """Groups of your posts by `by` (DIMENSIONS), per platform and audience, each with its verdict and a test to
    run next. YouTube is "unavailable" until you confirm Google's approval for derived metrics."""
    if by not in DIMENSIONS:
        raise ValueError(f"Compare by one of: {', '.join(DIMENSIONS)}.")
    settings = settings if settings is not None else db.get_settings()
    now = now or time.time()
    rows = posts(settings, now)
    by_place: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if r["cohort"] != "owner_only":   # your own views are not your viewers'
            by_place[(r["platform"], r["cohort"])].append(r)
    places = []
    for platform in ("youtube", "tiktok"):
        for (plat, cohort), group in sorted(by_place.items()):
            if plat != platform:
                continue
            name = PLATFORM_NAMES[platform]
            place = {"platform": platform, "cohort": cohort, "audience": COHORT_NAMES.get(cohort, cohort),
                     "posts": len(group)}
            if not learner.usable(platform, settings):
                place.update(available=False, note=learning.YOUTUBE_NOTE, groups=[], periods=None)
                places.append(place)
                continue
            channels = {r["channel"] for r in group}
            hint = next(iter(channels)) if len(channels) == 1 else ""
            keys = defaultdict(list)
            for r in group:
                keys[r[by]].append(r)
            groups = [_verdict(key, by, mine, [r for r in group if r[by] != key], platform, hint)
                      for key, mine in sorted(keys.items(), key=lambda kv: -len(kv[1]))]
            if len(keys) == 1:
                for g in groups:
                    g.update(verdict="only_one", text=f"All {len(group)} {name} posts here share this "
                                                      f"{DIMENSIONS[by].lower()}: nothing to compare it with.",
                             test="Post a few with a different one to compare.")
            pct_reported = any(r["pct"] is not None for r in group)
            place.update(available=True, groups=groups, periods=_periods(group, now),
                         note="" if pct_reported else f"{name} did not report average % viewed for these posts.")
            places.append(place)
    return {"by": by, "label": DIMENSIONS[by], "dimensions": DIMENSIONS, "places": places, "counted": len(rows),
            "min_posts": MIN_POSTS, "note": NOT_A_PROMISE}


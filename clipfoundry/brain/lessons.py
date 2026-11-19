"""What the results of posted clips teach the Brain about picking moments.

autopilot/brain.py keeps the results (with where each number came from) and learns one thing from them: the clip
length. This module learns a second: which kinds of moment did better or worse. It reads the same evidence under
the same guards (a mature reading, enough views, one comparable audience, only numbers ClipForge may learn from)
and compares, per kind of moment, the clips that showed it with the clips that did not. A clear difference becomes
a memory ("From your results: look for a big reaction ..."). Clip picking reads it like any other memory
(brain/steer.py), the AI that reads the video is told (pipeline/scout.py), the chat can answer from it, and the
owner can switch it off or forget it in Brain → Memory. A lesson the owner forgot is not learned again while the
numbers say the same.

These are patterns in the owner's own numbers, not proof that a kind of moment causes more views, so what a lesson
can do to one clip stays inside steer.LIMIT, and every lesson says how many clips it stands on.
"""
from __future__ import annotations

import math
import re
import time
from collections import defaultdict

from .. import db
from ..pipeline.common import log
from ..pipeline.text_utils import PROMO_PHRASES, STORY_MARKERS, count_phrases
from . import memories, steer

TAG = "from results"
STARTS = steer.LESSON_STARTS
MIN_WITH = 6          # clips that showed the kind ...
MIN_WITHOUT = 6       # ... and clips that did not, in one comparable audience
MIN_SOURCES = 3       # ... each side from at least this many different videos, so one video is not a lesson
# How clear a difference must be: what two (and, for a strong lesson, three) standard errors mean on many clips.
# Each run tests every kind of moment at once and has only a few clips, so the bar is split over the kinds tested
# and read from Student's t with the few clips' degrees of freedom: noise alone rarely makes a lesson.
CLEAR = 2.0
STRONG = 3.0
MIN_EFFECT = {"watched": 3.0, "views": 0.1}  # points watched; log10 of views (about a quarter more or fewer)
VIEWS_AGE_SPREAD = 1.5  # view counts keep growing for weeks: compared only when read within 1.5 times the usual age
STATE = "brain:lessons"
PLATFORM_WORDS = {"youtube": "YouTube", "tiktok": "TikTok"}


def kinds_of(clip: dict) -> list[str]:
    """The kinds of moment a clip shows: kept with the clip since this version, read from its words before."""
    a = clip.get("analysis") or {}
    if isinstance(a.get("moment"), list):
        return [k for k in a["moment"] if k in steer.BY_ID]
    text = str(clip.get("caption_text") or "")
    if not text.strip():
        return []
    low = text.lower()
    f = a.get("factors") or {}
    lines = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    facts = {
        "emotion": float(f.get("emotion", 5)) / 10, "density": float(f.get("density", 5)) / 10,
        "hook": float(f.get("hook", 5)) / 10, "curiosity": float(f.get("curiosity", 5)) / 10,
        "question_early": "?" in text[:max(1, int(len(text) * 0.4))],
        "story": count_phrases(low, STORY_MARKERS), "complete": bool((a.get("structure") or {}).get("complete")),
        "promo": count_phrases(low, PROMO_PHRASES), "outro": bool((a.get("signals") or {}).get("outro")),
        "slow_open": any(fl.get("id") == "slow_opening" for fl in a.get("flags") or []),
        "numbers": len(re.findall(r"\d+", text)),
        "short_lines": sum(1 for s in lines if 2 <= len(s.split()) <= 8 and s.rstrip()[-1:] in "!?"),
    }
    return steer.shown_kinds(text, facts)


def _outcomes(settings: dict, now: float) -> dict[tuple, dict]:
    """Per comparable audience: what is compared ("watched": the share of the clip people watched, where most
    clips have it; otherwise "views") and each clip's value. Same guards as autopilot/brain.evidence."""
    from ..autopilot import brain as results
    from ..autopilot.learner import REFERENCE_AGE_H, destination_cohort, usable

    min_views = int(settings.get("brain_min_views") or 10)
    latest: dict[tuple, dict[str, dict]] = defaultdict(dict)
    # Views keep growing, so view counts are compared at one age: each clip's reading closest to 48 hours, as the
    # posting learner does (learner._snapshot), and only when it was read near the age most clips of that audience
    # were (within VIEWS_AGE_SPREAD of the middle age): clips read at day 2 and clips first read a month later are
    # never compared, and an owner who imports every count at day 5 still learns. The share watched settles early
    # and is read at its latest.
    at_age: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for o in db.select("brain_observations", "", (), "observed_at"):
        if o["provenance"] == "tester_feedback" or not o.get("platform") or not o.get("clip_id"):
            continue
        if o["provenance"] == "platform_api" and not usable(o["platform"], settings):
            continue  # YouTube API numbers are shown, but learning from them needs Google's approval
        if o.get("age_hours") is None or float(o["age_hours"]) < results.MATURE_HOURS:
            continue
        if (o.get("metrics") or {}).get("views") is None:
            continue
        key = (o["platform"], o["cohort"], int(o.get("group_version") or 0))
        held = at_age[key].get(o["clip_id"])
        if not held or abs(float(o["age_hours"]) - REFERENCE_AGE_H) < abs(float(held["age_hours"]) - REFERENCE_AGE_H):
            at_age[key][o["clip_id"]] = o
        if o["metrics"]["views"] >= min_views:
            latest[key][o["clip_id"]] = o
    for key, clips in at_age.items():  # the floor applies to the reading compared, never to an earlier one
        kept = {cid: o for cid, o in clips.items() if o["metrics"]["views"] >= min_views}
        ages = sorted(float(o["age_hours"]) for o in kept.values())
        near = sorted(ages, key=lambda a: abs(math.log(a / REFERENCE_AGE_H)))  # the band nearest 48 hours ...
        mid = next((a for a in near if sum(a / VIEWS_AGE_SPREAD <= x <= a * VIEWS_AGE_SPREAD for x in ages)
                    >= MIN_WITH + MIN_WITHOUT), ages[len(ages) // 2] if ages else 0.0)  # ... that holds enough
        at_age[key] = {cid: o for cid, o in kept.items()
                       if mid / VIEWS_AGE_SPREAD <= float(o["age_hours"]) <= mid * VIEWS_AGE_SPREAD}
    out: dict[tuple, dict] = {}
    for (platform, cohort, gv), clips in latest.items():
        if cohort not in results.STRATEGY_COHORTS or cohort != destination_cohort(platform, settings):
            continue
        if gv != results._group_version(platform, settings):  # noqa: SLF001 - the same audience rule
            continue
        watched = {cid: o for cid, o in clips.items() if o["metrics"].get("avg_view_percentage") is not None}
        if len(watched) >= 0.8 * len(clips):
            what, values = "watched", {cid: float(o["metrics"]["avg_view_percentage"]) for cid, o in watched.items()}
        else:
            clips = at_age.get((platform, cohort, gv)) or {}
            what, values = "views", {cid: math.log10(float(o["metrics"]["views"]) + 1) for cid, o in clips.items()}
        out[(platform, cohort, gv)] = {"what": what, "clips": {cid: {"value": v, "at": clips[cid]["observed_at"]}
                                                              for cid, v in values.items()}}
    return out


# ------------------------------------------------------------------ Student's t, without extra packages
def _beta_cf(a: float, b: float, x: float) -> float:
    """The continued fraction of the incomplete beta function (Lentz's method)."""
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        for num in (m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
                    -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))):
            d = 1.0 + num * d
            d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + num / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1.0) < 1e-12:
            break
    return h


def _beta_inc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_cf(a, b, x) / a
    return 1.0 - front * _beta_cf(b, a, 1.0 - x) / b


def t_two_sided(t: float, df: float) -> float:
    """The chance of a t statistic at least this far from zero, either way, when there is no difference."""
    return _beta_inc(df / 2.0, 0.5, df / (df + t * t))


def t_bar(p: float, df: float) -> float:
    """The t statistic whose two-sided chance is p."""
    lo, hi = 0.0, 1.0
    while t_two_sided(hi, df) > p and hi < 1e6:
        hi *= 2.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        lo, hi = (mid, hi) if t_two_sided(mid, df) > p else (lo, mid)
    return hi


def _value(p: dict, raw: bool) -> float:
    return float(p.get("raw", p["value"])) if raw else float(p["value"])


def _mean(pts: list[dict], raw: bool = False) -> float:
    return sum(p["weight"] * _value(p, raw) for p in pts) / sum(p["weight"] for p in pts)


def _jackknife(reps: list[float]) -> float:
    g = len(reps)
    mid = sum(reps) / g
    return (g - 1) / g * sum((r - mid) ** 2 for r in reps)


def _inside(have: dict[str, list[dict]], rest: dict[str, list[dict]], videos: list[str], raw: bool) -> float:
    """The gap inside videos: each video's own gap between its clips with and without the kind, weighted by how much
    it can say (W_with * W_without / (W_with + W_without))."""
    num = den = 0.0
    for v in videos:
        wa, wb = sum(p["weight"] for p in have[v]), sum(p["weight"] for p in rest[v])
        k = wa * wb / (wa + wb)
        num, den = num + k * (_mean(have[v], raw) - _mean(rest[v], raw)), den + k
    return num / den


def _gap(have: list[dict], rest: list[dict]) -> tuple[float, float, float, int, int]:
    """The gap between clips with the kind and the others, the square of its standard error, its degrees of freedom
    and the clips with and without it that it stands on.

    Clips of one video move together (a strong video lifts all of them). Where at least MIN_SOURCES videos hold
    clips on both sides (with enough clips), the gap is taken inside each of those videos, so their reach cancels
    out; otherwise the two sides' means are compared and one long video that carries a side counts with all its
    weight. Either way the error is the gap's own spread when each video in turn is left out (a jackknife over
    videos), read from the values before the outlier cap (a cap that flattens a few volatile videos must not make
    noise look certain), and the degrees of freedom are the videos less one, fewer when a few videos carry the gap
    (Satterthwaite's estimate), so one lucky video cannot pass for many."""
    have_v: dict[str, list[dict]] = defaultdict(list)
    rest_v: dict[str, list[dict]] = defaultdict(list)
    for p in have:
        have_v[p["source"]].append(p)
    for p in rest:
        rest_v[p["source"]].append(p)
    both = sorted(set(have_v) & set(rest_v))
    n_with, n_without = sum(len(have_v[v]) for v in both), sum(len(rest_v[v]) for v in both)
    if len(both) >= MIN_SOURCES and n_with >= MIN_WITH and n_without >= MIN_WITHOUT:
        gap = _inside(have_v, rest_v, both, raw=False)
        var = _jackknife([_inside(have_v, rest_v, [v for v in both if v != u], raw=True) for u in both])
        ks = []
        for v in both:
            wa, wb = sum(p["weight"] for p in have_v[v]), sum(p["weight"] for p in rest_v[v])
            ks.append(wa * wb / (wa + wb))
        df = sum(ks) ** 2 / sum(k * k for k in ks)   # each video's part of the error goes with its weight
        return gap, var, max(1.0, min(len(both) - 1.0, df)), n_with, n_without
    gap = _mean(have) - _mean(rest)
    videos = sorted(set(have_v) | set(rest_v))
    g = len(videos)
    # each side keeps clips when one video is left out: compare asks for MIN_SOURCES videos on both
    var = _jackknife([_mean([p for p in have if p["source"] != v], True)
                      - _mean([p for p in rest if p["source"] != v], True) for v in videos])
    clip_part: dict[str, float] = defaultdict(float)   # what each video's clips add to the gap's error ...
    video_part: dict[str, float] = defaultdict(float)  # ... and what the video's own level adds
    left: dict[str, list[float]] = defaultdict(list)
    for side, sign in ((have, 1.0), (rest, -1.0)):
        w, mean = sum(p["weight"] for p in side), _mean(side, True)
        for p in side:
            clip_part[p["source"]] += (p["weight"] / w) ** 2
            video_part[p["source"]] += sign * p["weight"] / w
            left[p["source"]].append(_value(p, True) - mean)
    n = sum(len(v) for v in left.values())
    within = sum(sum((x - sum(v) / len(v)) ** 2 for x in v) for v in left.values()) / max(1, n - g)
    between = sum(sum(v) ** 2 / len(v) for v in left.values()) / max(1, g - 1)
    video_var = max(0.0, (between - within) * g / n)  # how much videos differ beyond their clips (one-way ANOVA)
    parts = [max(within, 1e-12) * clip_part[v] + video_var * video_part[v] ** 2 for v in videos]
    df = sum(parts) ** 2 / max(1e-30, sum(x * x for x in parts))
    return gap, var, max(1.0, min(g - 1.0, df)), len(have), len(rest)


def compare(pts: list[dict], what: str) -> list[dict]:
    """The kinds of moment whose clips did clearly better or worse than the other clips of one audience.
    `pts`: autopilot/brain._points rows with their clip's `kinds`."""
    tested = []
    for kind in steer.KINDS:
        have = [p for p in pts if kind.id in p["kinds"]]
        rest = [p for p in pts if kind.id not in p["kinds"]]
        if len(have) < MIN_WITH or len(rest) < MIN_WITHOUT:
            continue
        if min(len({p["source"] for p in have}), len({p["source"] for p in rest})) < MIN_SOURCES:
            continue
        tested.append((kind, have, rest))
    found = []
    for kind, have, rest in tested:
        diff, var, df, n_with, n_without = _gap(have, rest)
        t = diff / max(1e-9, math.sqrt(var))
        clear = t_bar(math.erfc(CLEAR / math.sqrt(2)) / len(tested), df)
        if abs(t) < clear or abs(diff) < MIN_EFFECT[what]:
            continue
        if diff > 0 and kind.id in steer.UNWANTED:
            continue  # only the owner's own words can ask for small talk, ad reads or swearing
        strong = abs(t) >= t_bar(math.erfc(STRONG / math.sqrt(2)) / len(tested), df)
        found.append({"kind": kind.id, "sign": 1 if diff > 0 else -1, "strong": strong, "what": what,
                      "diff": round(diff, 3), "z": round(t, 2), "with": n_with, "without": n_without})
    return found


def text_of(lesson: dict, platform: str) -> str:
    label = steer.BY_ID[lesson["kind"]].label
    if lesson["what"] == "watched":
        how = f"were watched {abs(lesson['diff']):.0f} points {'further' if lesson['sign'] > 0 else 'less far'} than"
    else:
        times = 10 ** abs(lesson["diff"])
        how = (f"got about {times:.1f} times the views of" if lesson["sign"] > 0 else
               f"got about {100 * (1 - 1 / times):.0f}% fewer views than")
    return (f"{STARTS} {'look for' if lesson['sign'] > 0 else 'pass over'} {label}. Clips with it {how} your other "
            f"clips ({lesson['with']} clips against {lesson['without']}, on {PLATFORM_WORDS.get(platform, platform)})."
            " A pattern in your own numbers, not proof.")


def _mine(ws: str) -> dict[str, dict]:
    """The lesson memories of a workspace by kind of moment (switched on or off, the owner's rewrites too)."""
    out = {}
    for row in db.select("brain_memories", "workspace_id = ?", (ws,), "created_at"):
        lesson = (row.get("data") or {}).get("lesson") or {}
        if lesson.get("kind") and TAG in (row.get("tags") or []):
            out[lesson["kind"]] = row
    return out


def _forget(ws: str, memory_id: str) -> None:
    try:
        memories.forget(ws, memory_id)
    except memories.Invalid:
        pass  # the owner forgot it a moment ago: it is gone either way


def learn(settings: dict | None = None, now: float | None = None) -> dict:
    """Compare the results by kind of moment and keep the Brain's lessons in step with them. Safe to re-run:
    nothing changes when the numbers say the same. Returns what was added, changed and dropped."""
    from ..autopilot import brain as results
    from ..autopilot import state

    settings = settings or db.get_settings()
    now = now or time.time()
    report = {"added": [], "changed": [], "dropped": [], "lessons": 0}
    if settings.get("brain_paused"):
        return {**report, "paused": True}
    per_ws: dict[str, dict[str, tuple[dict, str]]] = defaultdict(dict)
    for (platform, _cohort, _gv), found in sorted(_outcomes(settings, now).items()):
        by_ws: dict[str, list[dict]] = defaultdict(list)
        for p in results._points(found["clips"], now):  # noqa: SLF001 - weights, outlier caps, source videos
            clip = db.get_clip(p["clip_id"]) or {}
            project = db.get_project(clip.get("project_id") or "") or {}
            by_ws[str(project.get("workspace_id") or "local")].append({**p, "kinds": kinds_of(clip)})
        for ws, pts in by_ws.items():
            for lesson in compare(pts, found["what"]):
                seen = per_ws[ws].get(lesson["kind"])
                if seen and seen[0]["sign"] != lesson["sign"]:
                    per_ws[ws][lesson["kind"]] = ({**lesson, "sign": 0}, platform)  # two audiences disagree
                elif not seen or abs(lesson["z"]) > abs(seen[0]["z"]):
                    per_ws[ws][lesson["kind"]] = (lesson, platform)
    known = state.get(STATE) or {}
    for ws in set(per_ws) | set(known):
        mine = _mine(ws)
        was = dict(known.get(ws) or {})
        now_holds = {k: v for k, v in per_ws.get(ws, {}).items() if v[0]["sign"]}
        for kind, (lesson, platform) in now_holds.items():
            text, old, before = text_of(lesson, platform), mine.get(kind), was.get(kind) or {}
            if before.get("id") and not old and before.get("sign") == lesson["sign"]:
                continue  # the owner forgot this lesson: the same numbers do not bring it back
            if old and (not old.get("enabled") or not steer.lesson_of(old)):
                was[kind] = {"id": old["id"], "sign": lesson["sign"]}
                continue  # switched off, or rewritten in the owner's words: theirs now
            if old and old["text"] == text:
                was[kind] = {"id": old["id"], "sign": lesson["sign"]}
                if steer.lesson_of(old).get("strong") != lesson["strong"]:   # same words, firmer or weaker
                    memories._write_over(old, {  # noqa: SLF001 - the memory's own guarded write
                        "data": {**(old.get("data") or {}), "lesson": lesson, "text": text},
                        "revision": int(old.get("revision") or 1) + 1})
                continue
            if old:
                # recorded as being replaced before it goes: a run that stops before the new one is written must
                # not read the gap as the owner's Forget
                was.pop(kind, None)
                state.put(STATE, {**known, ws: was})
                _forget(ws, old["id"])
            row = memories.remember(ws, text, kind="fact", source="did", tags=[TAG, "clip picking"],
                                    data={"lesson": lesson, "text": text})
            was[kind] = {"id": row["id"], "sign": lesson["sign"]}
            state.put(STATE, {**known, ws: was})
            report["changed" if old else "added"].append(text)
        for kind, old in mine.items():
            if kind in now_holds or not old.get("enabled") or not steer.lesson_of(old):
                continue
            _forget(ws, old["id"])  # the numbers no longer say it
            was.pop(kind, None)
            report["dropped"].append(old["text"])
        known[ws] = was
        state.put(STATE, known)  # at once, so a later failure cannot leave a lesson's id unrecorded
        report["lessons"] += len(_mine(ws))
    state.put(STATE, known)
    for text in report["added"] + report["changed"]:
        state.event("brain_lesson", text[:300])
    if report["added"] or report["changed"] or report["dropped"]:
        log.info("Brain lessons from results: %d added, %d changed, %d dropped", len(report["added"]),
                 len(report["changed"]), len(report["dropped"]))
    return report

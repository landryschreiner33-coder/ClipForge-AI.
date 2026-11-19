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
STARTS = "From your results:"
MIN_WITH = 6          # clips that showed the kind ...
MIN_WITHOUT = 6       # ... and clips that did not, in one comparable audience
MIN_SOURCES = 3       # ... from at least this many different videos, so one good video is not a lesson
CLEAR = 2.0           # the difference must be this many standard errors
STRONG = 3.0
MIN_EFFECT = {"watched": 3.0, "views": 0.1}  # points watched; log10 of views (about a quarter more or fewer)
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
    from ..autopilot.learner import destination_cohort, usable

    min_views = int(settings.get("brain_min_views") or 10)
    latest: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for o in db.select("brain_observations", "", (), "observed_at"):
        if o["provenance"] == "tester_feedback" or not o.get("platform") or not o.get("clip_id"):
            continue
        if o["provenance"] == "platform_api" and not usable(o["platform"], settings):
            continue  # YouTube API numbers are shown, but learning from them needs Google's approval
        if o.get("age_hours") is None or float(o["age_hours"]) < results.MATURE_HOURS:
            continue
        if (o.get("metrics") or {}).get("views") is None or o["metrics"]["views"] < min_views:
            continue
        latest[(o["platform"], o["cohort"], int(o.get("group_version") or 0))][o["clip_id"]] = o
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
            what, values = "views", {cid: math.log10(float(o["metrics"]["views"]) + 1) for cid, o in clips.items()}
        out[(platform, cohort, gv)] = {"what": what, "clips": {cid: {"value": v, "at": clips[cid]["observed_at"]}
                                                              for cid, v in values.items()}}
    return out


def compare(pts: list[dict], what: str) -> list[dict]:
    """The kinds of moment whose clips did clearly better or worse than the other clips of one audience.
    `pts`: autopilot/brain._points rows with their clip's `kinds`."""
    from ..autopilot import brain as results

    found = []
    for kind in steer.KINDS:
        have = [p for p in pts if kind.id in p["kinds"]]
        rest = [p for p in pts if kind.id not in p["kinds"]]
        if len(have) < MIN_WITH or len(rest) < MIN_WITHOUT or len({p["source"] for p in have}) < MIN_SOURCES:
            continue
        mean_a, se_a, _ = results._stats(have)  # noqa: SLF001 - the same weighted statistics
        mean_b, se_b, _ = results._stats(rest)  # noqa: SLF001
        diff = mean_a - mean_b
        z = diff / max(1e-9, math.sqrt(se_a ** 2 + se_b ** 2))
        if abs(z) < CLEAR or abs(diff) < MIN_EFFECT[what]:
            continue
        if diff > 0 and kind.id in steer.UNWANTED:
            continue  # only the owner's own words can ask for small talk, ad reads or swearing
        found.append({"kind": kind.id, "sign": 1 if diff > 0 else -1, "strong": abs(z) >= STRONG, "what": what,
                      "diff": round(diff, 3), "z": round(z, 2), "with": len(have), "without": len(rest)})
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
    """The lesson memories of a workspace by kind of moment (switched on or off)."""
    out = {}
    for row in db.select("brain_memories", "workspace_id = ?", (ws,), "created_at"):
        lesson = (row.get("data") or {}).get("lesson") or {}
        if lesson.get("kind") and TAG in (row.get("tags") or []):
            out[lesson["kind"]] = row
    return out


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
            if old and (not old.get("enabled") or not str(old["text"]).startswith(STARTS)):
                was[kind] = {"id": old["id"], "sign": lesson["sign"]}
                continue  # switched off, or rewritten in the owner's words: theirs now
            if old and old["text"] == text:
                continue
            if old:
                memories.forget(ws, old["id"])
            row = memories.remember(ws, text, kind="fact", source="did", tags=[TAG, "clip picking"],
                                    data={"lesson": lesson})
            was[kind] = {"id": row["id"], "sign": lesson["sign"]}
            report["changed" if old else "added"].append(text)
        for kind, old in mine.items():
            if kind in now_holds or not old.get("enabled") or not str(old["text"]).startswith(STARTS):
                continue
            memories.forget(ws, old["id"])  # the numbers no longer say it
            was.pop(kind, None)
            report["dropped"].append(old["text"])
        known[ws] = was
        report["lessons"] += len(_mine(ws))
    state.put(STATE, known)
    for text in report["added"] + report["changed"]:
        state.event("brain_lesson", text[:300])
    if report["added"] or report["changed"] or report["dropped"]:
        log.info("Brain lessons from results: %d added, %d changed, %d dropped", len(report["added"]),
                 len(report["changed"]), len(report["dropped"]))
    return report

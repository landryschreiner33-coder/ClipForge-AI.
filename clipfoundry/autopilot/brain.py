"""The Brain (CORE in the office): what ClipFoundry remembers about real results, and the one strategy it may change.

Evidence comes from three places and keeps its provenance apart:

* ``platform_api``: numbers the platform's official API returned for your post (publish/stats.py).
* ``owner_import``: numbers you copied or exported from YouTube Studio or TikTok (the form or a CSV file).
* ``tester_feedback``: ratings your testers gave (1-5) and where they stopped. Self-reported, never shown as watch
  time or retention.

A missing number stays missing (never 0). Readings of the same post are cumulative snapshots: only the latest mature
one counts, they are never added together. A correction replaces the values and keeps the earlier ones.

Results are only compared within one comparable audience: the platform, who could watch (your selected viewers,
only you, or the public before this version) and the version of that audience group. Only selected viewers' results
can change a strategy; "only you" staging and old public posts are kept but never mixed in.

The strategy this version adjusts is the clip length Autopilot aims for (``target_duration`` in the moment finder).
The guards (section 14 of the build brief, all in Settings → Advanced):

* nothing changes before ``brain_min_clips`` (30) distinct clips with mature results in one comparable audience,
  from at least 5 different source videos; a clip counts once it has ``brain_min_views`` views in a reading at
  least 48 hours after posting, or ratings from ``brain_min_testers`` different testers;
* clips from the same source video are weighted down (1/sqrt(n)) and older results count less (half weight after
  60 days); outcomes are capped at their 10th and 90th percentiles;
* a change needs both shorter and longer clips (10 each) and a difference larger than twice its standard error;
  otherwise the result is "not enough evidence" or "inconclusive" and the strategy stays;
* one accepted update moves the target by at most ``brain_max_step`` (10%), inside your min/max clip length;
* every version stores its evidence, the old and new value and the version it replaced; later results are checked
  and a clearly worse version is rolled back automatically; Reset returns to your own setting.

The Brain never changes code, secrets, privacy, who watches, spending limits or safety checks. These are correlations
in your own results, not proof that a length causes more views, and a small selected group is not the public.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import time
from collections import defaultdict
from typing import Any

from .. import db
from ..office import feed
from . import state

PROVENANCE = ("platform_api", "owner_import", "tester_feedback")
PROVENANCE_LABELS = {"platform_api": "Platform (API)", "owner_import": "Your import",
                     "tester_feedback": "Tester feedback (self-reported)"}
# metric -> (label, unit, low, high, whole number)
METRICS: dict[str, tuple[str, str, float, float, bool]] = {
    "views": ("Views", "count", 0, 1e12, True),
    "watch_time_minutes": ("Watch time", "minutes", 0, 1e12, False),
    "avg_view_duration_s": ("Average view duration", "seconds", 0, 86400, False),
    "avg_view_percentage": ("Average percentage viewed", "%", 0, 1000, False),  # rewatches can exceed 100
    "likes": ("Likes", "count", 0, 1e12, True),
    "comments": ("Comments", "count", 0, 1e12, True),
    "shares": ("Shares", "count", 0, 1e12, True),
    "impressions": ("Impressions", "count", 0, 1e12, True),
    "ctr": ("Impressions click-through rate", "%", 0, 100, False),
    "rewatches": ("Rewatches", "count", 0, 1e12, True),
    "audience_size": ("Audience size", "people", 0, 1e9, True),
}
RATINGS = {"hook": "The start made me want to watch", "context": "I understood what it was about",
           "payoff": "The ending paid off", "captions": "The captions were easy to read", "overall": "Overall"}
TESTER_FIELDS = (*RATINGS, "stopped_at_s")
MATURE_HOURS = 48.0
RECENCY_DAYS = 60.0
MIN_SOURCES = 5
MIN_SIDE = 10
STRATEGY = "clip_length"
STRATEGY_COHORTS = ("selected",)  # only your selected viewers' results may change a strategy
COHORT_LABELS = {"selected": "Selected viewers", "owner_only": "Only you (staging)",
                 "public_legacy": "Public (before this version)", "testers": "Shown to testers directly",
                 "unlinked": "Not linked to a post"}
STATE_LABELS = {"cold_start": "Cold start", "collecting": "Collecting data", "evaluating": "Evaluating",
                "updated": "Strategy updated", "paused": "Paused", "error": "Error"}


class Invalid(ValueError):
    """An observation or import row that cannot be stored as given (the message says what to change)."""


def _settings(settings: dict | None) -> dict:
    return settings if settings is not None else db.get_settings()


# ------------------------------------------------------------------ recording evidence
def _destination(clip_id: str, platform: str, publication_id: str = "") -> dict:
    """Which post (and so which audience) an observation belongs to."""
    from .learner import cohort

    pubs = [p for p in db.list_publications(clip_id=clip_id, platform=platform or None)
            if p["status"] in ("done", "action_needed") and (not publication_id or p["id"] == publication_id)]
    if pubs and platform:
        pub = max(pubs, key=lambda p: p["created_at"])
        stamp = pub.get("audience") or {}
        return {"publication_id": pub["id"], "cohort": cohort(pub), "group_version": int(stamp.get("group_version")
                                                                                         or 0),
                "posted_at": float(pub["created_at"])}
    # feedback on a clip shown to testers directly, or numbers for a post ClipFoundry does not know about: kept, but
    # never mixed with a platform audience
    return {"publication_id": "", "cohort": "unlinked" if platform else "testers", "group_version": 0,
            "posted_at": None}


def _number(key: str, raw: Any, limits: tuple[float, float], whole: bool) -> float | int | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None  # missing stays missing
    try:
        value = float(str(raw).replace(",", "").replace("%", "").strip())
    except ValueError:
        raise Invalid(f"{key}: “{raw}” is not a number") from None
    if math.isnan(value) or not limits[0] <= value <= limits[1]:
        raise Invalid(f"{key}: {raw} is outside {limits[0]:g}-{limits[1]:g}")
    return int(round(value)) if whole else round(value, 3)


def clean(provenance: str, values: dict, clip: dict | None = None) -> dict:
    """Only known fields, in their units; unknown fields are refused by name. Missing values are left out."""
    if provenance not in PROVENANCE:
        raise Invalid(f"Unknown evidence type: {provenance}")
    allowed = TESTER_FIELDS if provenance == "tester_feedback" else tuple(METRICS)
    unknown = sorted(k for k, v in values.items() if k not in allowed and v not in (None, ""))
    if unknown:
        raise Invalid(f"Not a field for {PROVENANCE_LABELS[provenance].lower()}: {', '.join(unknown)}")
    out: dict[str, Any] = {}
    for key in allowed:
        if key in RATINGS:
            v = _number(key, values.get(key), (1, 5), True)
        elif key == "stopped_at_s":
            longest = float((clip or {}).get("duration") or 3600) + 5
            v = _number(key, values.get(key), (0, longest), False)
        else:
            _label, _unit, lo, hi, whole = METRICS[key]
            v = _number(key, values.get(key), (lo, hi), whole)
        if v is not None:
            out[key] = v
    if not out:
        raise Invalid("Enter at least one result")
    return out


def _key(provenance: str, clip_id: str, platform: str, dest: dict, observed_at: float, tester: str,
         values: dict) -> str:
    if provenance == "platform_api":
        return f"api:{dest['publication_id'] or clip_id}:{int(observed_at)}"
    if provenance == "owner_import":
        return f"import:{clip_id}:{platform}:{int(observed_at // 60)}"  # the same reading, possibly corrected
    if tester:
        return f"tester:{clip_id}:{platform}:{tester.lower()}"  # one answer per tester; a new one corrects it
    digest = hashlib.sha256(json.dumps([observed_at, values], sort_keys=True).encode()).hexdigest()[:16]
    return f"tester:{clip_id}:{platform}:anonymous:{digest}"


def add(clip_id: str, platform: str, provenance: str, values: dict, *, observed_at: float | None = None,
        tester: str = "", note: str = "", origin: str = "form", publication_id: str = "",
        now: float | None = None) -> dict:
    """Store one observation. Returns {"status": "added" | "duplicate" | "corrected", "observation": row}."""
    now = now or time.time()
    clip = db.get_clip(clip_id)
    if not clip:
        raise Invalid("That clip does not exist (it may have been deleted)")
    platform = (platform or "").lower()
    if platform not in ("youtube", "tiktok", ""):
        raise Invalid("Platform must be YouTube, TikTok or empty (shown to testers directly)")
    if not platform and provenance != "tester_feedback":
        raise Invalid("Platform numbers need a platform (YouTube or TikTok)")
    tester = (tester or "").strip()[:40]
    if "@" in tester:
        raise Invalid("Use a nickname or a number for the tester, not an email address")
    observed_at = float(observed_at or now)
    if observed_at > now + 3600:
        raise Invalid("The observation date is in the future")
    if observed_at < float(clip["created_at"]) - 3600:
        raise Invalid("The observation date is before the clip was made")
    cleaned = clean(provenance, values, clip)
    dest = _destination(clip_id, platform, publication_id)
    age = round((observed_at - dest["posted_at"]) / 3600, 2) if dest["posted_at"] else None
    key = _key(provenance, clip_id, platform, dest, observed_at, tester, cleaned)
    old = db.select("brain_observations", "dedupe_key = ?", (key,))
    if old and old[0]["metrics"] == cleaned:
        return {"status": "duplicate", "observation": old[0]}
    if old:
        row = old[0]
        previous = (row.get("previous") or []) + [{"metrics": row["metrics"], "revision": row.get("revision") or 1,
                                                   "replaced_at": now, "origin": row.get("origin")}]
        db.update("brain_observations", row["id"], metrics=cleaned, previous=previous[-20:],
                  revision=int(row.get("revision") or 1) + 1, observed_at=observed_at, age_hours=age,
                  note=note[:500] or row.get("note") or "", origin=origin[:120])
        saved, status = db.fetch("brain_observations", row["id"]), "corrected"
    else:
        saved = db.insert("brain_observations", {
            "clip_id": clip_id, "publication_id": dest["publication_id"], "platform": platform,
            "cohort": dest["cohort"], "group_version": dest["group_version"], "provenance": provenance,
            "observed_at": observed_at, "age_hours": age, "metrics": cleaned, "tester": tester,
            "note": note[:500], "origin": origin[:120], "dedupe_key": key})
        status = "added"
    feed.emit("brain_observation", "metric", ref=("clip", clip_id), message=f"{PROVENANCE_LABELS[provenance]} "
              f"for a {platform or 'tester'} clip ({status})", provenance=provenance, status=status)
    return {"status": status, "observation": saved}


def ingest_platform(pub: dict) -> int:
    """Mirror a post's platform readings (publish/stats.py) as evidence; re-running adds nothing new."""
    added = 0
    fields = ("views", "likes", "comments", "shares", "watch_time_minutes", "avg_view_duration_s",
              "avg_view_percentage")
    for h in db.performance_history(pub["id"]):
        values = {k: h.get(k) for k in fields if h.get(k) is not None}
        if not values:
            continue
        try:
            out = add(pub["clip_id"], pub["platform"], "platform_api", values, observed_at=float(h["fetched_at"]),
                      origin=f"{pub['platform']} API", publication_id=pub["id"])
        except Invalid:
            continue
        added += out["status"] != "duplicate"
    return added


def observations(clip_id: str = "", limit: int = 200) -> list[dict]:
    return db.select("brain_observations", "clip_id = ?" if clip_id else "", (clip_id,) if clip_id else (),
                     "observed_at DESC", limit)


# ------------------------------------------------------------------ CSV import (preview, then import)
COLUMNS = {
    "clip_id": ("clip_id", "clip", "clip id"),
    "video_id": ("video_id", "video id", "content", "video"),
    "platform": ("platform",),
    "observed_at": ("observed_at", "observed", "date", "as of"),
    "tester": ("tester", "tester_id", "tester id"),
    "note": ("note", "comment", "notes"),
    "views": ("views",),
    "watch_time_minutes": ("watch_time_minutes", "watch time (minutes)"),
    "watch_time_hours": ("watch time (hours)",),
    "avg_view_duration_s": ("avg_view_duration_s", "average view duration"),
    "avg_view_percentage": ("avg_view_percentage", "average percentage viewed (%)", "average percentage viewed"),
    "likes": ("likes",),
    "comments": ("comments", "comments added"),
    "shares": ("shares",),
    "impressions": ("impressions",),
    "ctr": ("ctr", "impressions click-through rate (%)"),
    "rewatches": ("rewatches",),
    "audience_size": ("audience_size", "audience size"),
    **{k: (k,) for k in TESTER_FIELDS},
}
MAX_IMPORT_BYTES = 2_000_000
MAX_IMPORT_ROWS = 5000


def _date(raw: str) -> float:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(raw[:16] if "%H" in fmt else raw, fmt).timestamp()
        except ValueError:
            continue
    raise Invalid(f"date “{raw}” was not understood (use 2026-10-07 or 2026-10-07 18:30)")


def _duration(raw: str) -> str:
    """'0:00:41' or '1:05' → seconds; plain numbers pass through."""
    if ":" not in raw:
        return raw
    parts = [float(p) for p in raw.strip().split(":")]
    return str(sum(p * 60 ** k for k, p in enumerate(reversed(parts))))


def _rows(text: str, provenance: str, platform: str, observed_at: float | None, now: float) -> tuple[list, dict]:
    if len(text.encode("utf-8", "ignore")) > MAX_IMPORT_BYTES:
        raise Invalid("The file is larger than 2 MB")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    heads = {h: (h or "").strip().lower() for h in reader.fieldnames or []}
    found: dict[str, str] = {}
    for head, low in heads.items():
        for field, names in COLUMNS.items():
            if low in names and field not in found:
                found[field] = head
    ignored = [h for h in heads if h not in found.values()]
    if "clip_id" not in found and "video_id" not in found:
        raise Invalid("The file needs a clip_id column (from ClipFoundry) or a video ID column (Content)")
    pubs = {p.get("remote_id"): p for p in db.list_publications() if p.get("remote_id")}
    out = []
    for n, rec in enumerate(reader, start=2):
        if n - 1 > MAX_IMPORT_ROWS:
            raise Invalid(f"More than {MAX_IMPORT_ROWS} rows; split the file")
        get = lambda f: (rec.get(found[f]) or "").strip() if f in found else ""  # noqa: E731
        row: dict[str, Any] = {"line": n, "status": "new", "message": ""}
        try:
            if get("video_id").lower() == "total" or (not get("clip_id") and not get("video_id")):
                continue  # YouTube Studio's totals row, or an empty line
            pub = pubs.get(get("video_id")) if get("video_id") else None
            clip_id = get("clip_id") or (pub or {}).get("clip_id") or ""
            if not clip_id:
                raise Invalid(f"video {get('video_id')} is not one of your ClipFoundry posts")
            row_platform = (get("platform") or (pub or {}).get("platform") or platform).lower()
            if provenance != "tester_feedback" and row_platform not in ("youtube", "tiktok"):
                raise Invalid("no platform (add a platform column or choose YouTube or TikTok for the file)")
            when = _date(get("observed_at")) if get("observed_at") else observed_at
            if not when:
                raise Invalid("no observation date (add a date column or choose the date of the export)")
            if when > now + 3600:
                raise Invalid("the date is in the future")
            values = {f: get(f) for f in (TESTER_FIELDS if provenance == "tester_feedback" else METRICS) if get(f)}
            if provenance != "tester_feedback":
                if get("watch_time_hours") and "watch_time_minutes" not in values:
                    values["watch_time_minutes"] = str(float(get("watch_time_hours").replace(",", "")) * 60)
                if "avg_view_duration_s" in values:
                    values["avg_view_duration_s"] = _duration(values["avg_view_duration_s"])
            clip = db.get_clip(clip_id)
            if not clip:
                raise Invalid(f"clip {clip_id} does not exist")
            cleaned = clean(provenance, values, clip)
            dest = _destination(clip_id, row_platform, (pub or {}).get("id", ""))
            key = _key(provenance, clip_id, row_platform, dest, when, get("tester"), cleaned)
            old = db.select("brain_observations", "dedupe_key = ?", (key,))
            row.update(clip_id=clip_id, clip_title=clip.get("title") or "", platform=row_platform,
                       observed_at=when, tester=get("tester"), note=get("note"), values=cleaned,
                       publication_id=dest["publication_id"], cohort=dest["cohort"],
                       cohort_label=COHORT_LABELS.get(dest["cohort"], dest["cohort"]))
            if old:
                row["status"] = "duplicate" if old[0]["metrics"] == cleaned else "correction"
                row["message"] = "Already imported" if row["status"] == "duplicate" else "Replaces earlier values"
        except (Invalid, ValueError) as exc:
            row.update(status="error", message=str(exc))
        out.append(row)
    return out, {"recognized": sorted(found), "ignored": ignored}


def preview(text: str, provenance: str = "owner_import", platform: str = "", observed_at: float | None = None,
            now: float | None = None) -> dict:
    """What an import would do, row by row, without storing anything."""
    rows, columns = _rows(text, provenance, platform, observed_at, now or time.time())
    counts = defaultdict(int)
    for r in rows:
        counts[r["status"]] += 1
    return {"rows": rows, "columns": columns, "counts": dict(counts), "provenance": provenance}


def import_csv(text: str, provenance: str = "owner_import", platform: str = "", observed_at: float | None = None,
               filename: str = "import.csv") -> dict:
    """Import the new and corrected rows of a previewed file. Importing the same file again adds nothing."""
    result = preview(text, provenance, platform, observed_at)
    done = defaultdict(int)
    for r in result["rows"]:
        if r["status"] not in ("new", "correction"):
            done[r["status"]] += 1
            continue
        try:
            out = add(r["clip_id"], r["platform"], provenance, r["values"], observed_at=r["observed_at"],
                      tester=r.get("tester") or "", note=r.get("note") or "", origin=filename[:120],
                      publication_id=r.get("publication_id") or "")
            done[out["status"]] += 1
        except Invalid as exc:
            r.update(status="error", message=str(exc))
            done["error"] += 1
    state.event("brain_import", f"Imported results from {filename}: {done.get('added', 0)} new, "
                                f"{done.get('corrected', 0)} corrected, {done.get('duplicate', 0)} already there, "
                                f"{done.get('error', 0)} not usable")
    return {"counts": dict(done), "rows": result["rows"]}


# ------------------------------------------------------------------ evidence per clip
def _source_of(clip: dict) -> str:
    project = db.get_project(clip.get("project_id") or "") or {}
    return project.get("source_id") or clip.get("project_id") or clip["id"]


def evidence(settings: dict | None = None, now: float | None = None) -> dict[tuple, dict]:
    """Per comparable audience (platform, audience, group version): each clip's usable outcome, if it has one."""
    from .learner import usable

    settings = _settings(settings)
    now = now or time.time()
    min_views, min_testers = int(settings.get("brain_min_views") or 10), int(settings.get("brain_min_testers") or 3)
    per: dict[tuple, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"reading": None, "testers": {}}))
    for o in db.select("brain_observations", "", (), "observed_at"):
        group = (o["platform"], o["cohort"], int(o.get("group_version") or 0))
        slot = per[group][o["clip_id"]]
        if o["provenance"] == "tester_feedback":
            if o.get("tester"):  # anonymous answers are kept but cannot show different people watched
                slot["testers"][o["tester"].lower()] = o
            continue
        if o["provenance"] == "platform_api" and not usable(o["platform"], settings):
            continue  # YouTube API numbers are shown, but derived metrics need Google's approval
        if o.get("age_hours") is None or float(o["age_hours"]) < MATURE_HOURS:
            continue
        if slot["reading"] is None or o["observed_at"] > slot["reading"]["observed_at"]:
            slot["reading"] = o  # the latest mature cumulative reading; snapshots are never added together
    out: dict[tuple, dict] = {}
    for group, clips in per.items():
        measured, rated = {}, {}
        for clip_id, slot in clips.items():
            r = slot["reading"]
            if r and (r["metrics"].get("views") or 0) >= min_views and r["metrics"].get("avg_view_percentage") \
                    is not None:
                measured[clip_id] = {"value": float(r["metrics"]["avg_view_percentage"]), "at": r["observed_at"],
                                     "provenance": r["provenance"]}
            overall = [t["metrics"]["overall"] for t in slot["testers"].values() if "overall" in t["metrics"]]
            if len(overall) >= min_testers:
                rated[clip_id] = {"value": sum(overall) / len(overall), "at": max(
                    t["observed_at"] for t in slot["testers"].values()), "provenance": "tester_feedback",
                                  "testers": len(overall)}
        out[group] = {"clips": len(clips), "measured": measured, "rated": rated}
    return out


def _points(outcomes: dict[str, dict], now: float) -> list[dict]:
    pts = []
    by_source: dict[str, int] = defaultdict(int)
    clips = {}
    for clip_id in outcomes:
        clip = db.get_clip(clip_id)
        if clip and clip.get("duration"):
            clips[clip_id] = clip
            by_source[_source_of(clip)] += 1
    for clip_id, clip in clips.items():
        o = outcomes[clip_id]
        source = _source_of(clip)
        recency = 0.5 ** (max(0.0, now - float(o["at"])) / 86400 / RECENCY_DAYS)
        pts.append({"clip_id": clip_id, "source": source, "duration": float(clip["duration"]), "value": o["value"],
                    "weight": recency / math.sqrt(by_source[source]), "strategy": _strategy_of(clip)})
    if len(pts) >= 5:  # cap outliers at the 10th and 90th percentiles
        vals = sorted(p["value"] for p in pts)
        lo, hi = vals[int(0.1 * (len(vals) - 1))], vals[int(math.ceil(0.9 * (len(vals) - 1)))]
        for p in pts:
            p["value"] = min(hi, max(lo, p["value"]))
    return pts


def _stats(pts: list[dict]) -> tuple[float, float, float]:
    """Weighted mean, its standard error (Kish effective size), and the effective size."""
    w = sum(p["weight"] for p in pts)
    mean = sum(p["weight"] * p["value"] for p in pts) / w
    var = sum(p["weight"] * (p["value"] - mean) ** 2 for p in pts) / w
    n_eff = w * w / sum(p["weight"] ** 2 for p in pts)
    return mean, math.sqrt(var / max(1.0, n_eff - 1)), n_eff


def _weighted_median(pts: list[dict], key: str) -> float:
    pts = sorted(pts, key=lambda p: p[key])
    half, run = sum(p["weight"] for p in pts) / 2, 0.0
    for p in pts:
        run += p["weight"]
        if run >= half:
            return p[key]
    return pts[-1][key]


# ------------------------------------------------------------------ strategies
def active(platform: str, cohort: str = "selected", group_version: int | None = None,
           name: str = STRATEGY) -> dict | None:
    where, args = "name = ? AND platform = ? AND cohort = ? AND status = 'active'", [name, platform, cohort]
    rows = db.select("brain_strategies", where, args, "version DESC", 5)
    if group_version is not None:
        rows = [r for r in rows if int((r.get("params") or {}).get("group_version") or 0) == group_version]
    return rows[0] if rows else None


def _strategy_of(clip: dict) -> str:
    project = db.get_project(clip.get("project_id") or "") or {}
    return ((project.get("options") or {}).get("strategy") or {}).get(STRATEGY, {}).get("id", "") or "baseline"


def _baseline(settings: dict) -> float:
    return float(settings.get("target_duration") or 30.0)


def _group_version(platform: str, settings: dict) -> int:
    from ..publish import audience

    return int(audience.destination(platform, settings)["group_version"])


def clip_length(settings: dict | None = None) -> dict | None:
    """The clip length Autopilot aims for now, when a learned strategy applies (None: your own setting). Used when
    Autopilot starts work on a new video (autopilot/hunter.py), and recorded with it, so later results can be tied
    to the version that made them."""
    settings = _settings(settings)
    if settings.get("brain_paused"):
        return None
    found = []
    for platform in ("youtube", "tiktok"):
        if not settings.get(f"autopilot_{platform}"):
            continue
        s = active(platform, "selected", _group_version(platform, settings))
        if s:
            found.append(s)
    if not found:
        return None
    target = round(sum(float(s["params"]["target_duration"]) for s in found) / len(found), 1)
    lo, hi = float(settings.get("min_duration") or 15), float(settings.get("max_duration") or 60)
    used = [{"id": s["id"], "platform": s["platform"], "version": s["version"]} for s in found]
    feed.emit("brain_lookup", "core", message=f"Clip length {target:g} s from the learned strategy "
              + ", ".join(f"{u['platform']} v{u['version']}" for u in used), strategies=used)
    return {"target_duration": min(hi, max(lo, target)), "id": found[0]["id"] if len(found) == 1 else
            "+".join(u["id"] for u in used), "used": used}


def _save(platform: str, cohort: str, group_version: int, params: dict, evidence_: dict, reason: str,
          replaces: dict | None) -> dict:
    last = db.scalar("SELECT COALESCE(MAX(version), 0) FROM brain_strategies WHERE name = ? AND platform = ? AND "
                     "cohort = ?", (STRATEGY, platform, cohort)) or 0
    if replaces:
        db.update("brain_strategies", replaces["id"], status="superseded")
    return db.insert("brain_strategies", {
        "name": STRATEGY, "platform": platform, "cohort": cohort, "version": int(last) + 1,
        "params": {**params, "group_version": group_version, "rollback_to": (replaces or {}).get("id") or "baseline"},
        "evidence": evidence_, "status": "active", "reason": reason[:500]})


def rollback(strategy_id: str, reason: str = "Rolled back by you") -> dict:
    """Return to the version this one replaced (or to your own setting)."""
    row = db.fetch("brain_strategies", strategy_id)
    if not row or row["status"] != "active":
        raise Invalid("Only the strategy in use can be rolled back")
    db.update("brain_strategies", row["id"], status="rolled_back", reason=f"{row['reason']} | {reason}"[:500])
    back = (row.get("params") or {}).get("rollback_to") or "baseline"
    prev = db.fetch("brain_strategies", back) if back != "baseline" else None
    if prev:
        db.update("brain_strategies", prev["id"], status="active")
    msg = f"Clip length strategy for {row['platform']} v{row['version']} rolled back to " + (
        f"v{prev['version']}" if prev else "your own setting") + f": {reason}"
    state.event("strategy_rolled_back", msg)
    feed.emit("strategy_rolled_back", "curator", message=msg, strategy_id=row["id"])
    return {"rolled_back": row["id"], "active": prev["id"] if prev else "baseline", "message": msg}


def reset(platform: str = "") -> dict:
    """Back to your own clip length setting (every learned version stays in the history)."""
    n = 0
    for row in db.select("brain_strategies", "status = 'active'" + (" AND platform = ?" if platform else ""),
                         (platform,) if platform else ()):
        db.update("brain_strategies", row["id"], status="rolled_back", reason=f"{row['reason']} | Reset by you"[:500])
        n += 1
    state.event("strategy_reset", f"Learned clip length reset ({n} version(s)); Autopilot uses your own setting")
    feed.emit("strategy_rolled_back", "curator", message="Learned strategy reset to your own setting")
    return {"reset": n}


def _check_active(pts: list[dict], s: dict) -> str | None:
    """Later results under the version in use against those under the version it replaced: a clearly worse
    version is rolled back (returns the message)."""
    mine = [p for p in pts if p["strategy"] == s["id"]]
    before_id = (s.get("params") or {}).get("rollback_to") or "baseline"
    before = [p for p in pts if p["strategy"] == before_id]
    if len(mine) < MIN_SIDE or len(before) < MIN_SIDE:
        return None
    m_new, se_new, _ = _stats(mine)
    m_old, se_old, _ = _stats(before)
    se = math.sqrt(se_new ** 2 + se_old ** 2)
    if m_old - m_new > 2 * se and se > 0:
        return rollback(s["id"], f"later results were worse ({m_new:.1f} vs {m_old:.1f}, {len(mine)} and "
                                 f"{len(before)} clips)")["message"]
    return None


def evaluate_group(platform: str, cohort: str, gv: int, ev: dict, settings: dict, now: float) -> dict:
    """One comparable audience: not enough evidence, inconclusive, or a bounded change (with its evidence)."""
    min_clips = max(30, int(settings.get("brain_min_clips") or 30))
    step_cap = min(0.10, float(settings.get("brain_max_step") or 0.10))
    label = f"{'YouTube' if platform == 'youtube' else 'TikTok'} · {COHORT_LABELS.get(cohort, cohort)}"
    base = {"platform": platform, "cohort": cohort, "group_version": gv, "label": label, "needed": min_clips}
    if ev["measured"] and len(ev["measured"]) >= len(ev["rated"]):
        outcomes, metric = ev["measured"], "avg_view_percentage"
    else:
        outcomes, metric = ev["rated"], "tester_overall"
    pts = _points(outcomes, now)
    kinds = {outcomes[p["clip_id"]]["provenance"] for p in pts}
    where = " and ".join(w for k, w in (("platform_api", "platform API"), ("owner_import", "your imports"))
                         if k in kinds) or "no readings"
    metric_label = f"average percentage viewed ({where})" if metric == "avg_view_percentage" else \
        "testers' overall rating (self-reported)"
    sources = len({p["source"] for p in pts})
    base.update(eligible=len(pts), sources=sources, metric=metric, metric_label=metric_label)
    current = active(platform, cohort, gv)
    if current:
        rolled = _check_active(pts, current)
        if rolled:
            return {**base, "result": "rolled_back", "message": rolled}
        current = active(platform, cohort, gv)
    if len(pts) < min_clips or sources < MIN_SOURCES:
        return {**base, "result": "not_enough", "message": f"Not enough evidence yet: {len(pts)} of {min_clips} "
                f"clips with mature results from {sources} of {MIN_SOURCES} videos."}
    if current:  # the same evidence never moves the value twice: the next step waits for new results
        seen = set((current.get("evidence") or {}).get("clips") or [])
        fresh = sum(p["clip_id"] not in seen for p in pts)
        if fresh < MIN_SIDE:
            return {**base, "result": "waiting", "message": f"Waiting for new results since version "
                    f"{current['version']}: {fresh} of {MIN_SIDE} new clips."}
    target = float(current["params"]["target_duration"]) if current else _baseline(settings)
    short = [p for p in pts if p["duration"] < target]
    long = [p for p in pts if p["duration"] >= target]
    if len(short) < MIN_SIDE or len(long) < MIN_SIDE:
        return {**base, "result": "inconclusive", "message": f"Inconclusive: needs at least {MIN_SIDE} clips shorter "
                f"and {MIN_SIDE} longer than {target:g} s ({len(short)} and {len(long)} so far)."}
    m_s, se_s, n_s = _stats(short)
    m_l, se_l, n_l = _stats(long)
    se = math.sqrt(se_s ** 2 + se_l ** 2)
    diff = m_l - m_s
    found = {"metric": metric, "short": {"n": len(short), "mean": round(m_s, 2), "n_eff": round(n_s, 1)},
             "long": {"n": len(long), "mean": round(m_l, 2), "n_eff": round(n_l, 1)}, "diff": round(diff, 2),
             "standard_error": round(se, 2), "sources": sources, "clips": [p["clip_id"] for p in pts][:1000],
             "provenance": sorted({outcomes[p["clip_id"]]["provenance"] for p in pts}), "at": now}
    if se == 0 or abs(diff) <= 2 * se:
        return {**base, "result": "inconclusive", "evidence": found, "message": f"Inconclusive: shorter and longer "
                f"clips did about the same ({m_s:.1f} vs {m_l:.1f}, uncertainty ±{2 * se:.1f})."}
    better = long if diff > 0 else short
    aim = _weighted_median(better, "duration")
    step = min(step_cap, abs(aim - target) / target)
    lo, hi = float(settings.get("min_duration") or 15), float(settings.get("max_duration") or 60)
    new = round(min(hi, max(lo, target * (1 + step if diff > 0 else 1 - step))), 1)
    if abs(new - target) < 0.1:
        return {**base, "result": "inconclusive", "evidence": found,
                "message": "The better clips are already at the current length (or at your min/max)."}
    confidence = "moderate" if abs(diff) > 3 * se else "low"
    reason = (f"{'Longer' if diff > 0 else 'Shorter'} clips had a higher {metric_label} ({max(m_s, m_l):.1f} vs "
              f"{min(m_s, m_l):.1f}, ±{2 * se:.1f}) across {len(pts)} clips from {sources} videos; target moved "
              f"{target:g} → {new:g} s (at most {step_cap:.0%} per update; {confidence} confidence, a correlation)")
    saved = _save(platform, cohort, gv, {"target_duration": new, "previous_target": target},
                  {**found, "confidence": confidence}, reason, current)
    state.event("strategy_updated", f"{label}: {reason}")
    feed.emit("strategy_changed", "curator", message=reason[:300], strategy_id=saved["id"], version=saved["version"])
    return {**base, "result": "updated", "message": reason, "strategy": saved}


def evaluate(settings: dict | None = None, now: float | None = None) -> dict:
    """Compare results per comparable audience and apply at most one bounded change each. Safe to re-run."""
    settings = _settings(settings)
    now = now or time.time()
    if settings.get("brain_paused"):
        out = {"at": now, "state": "paused", "groups": [], "message": "Learning is paused: results are still "
                                                                      "collected, no strategy changes."}
        state.put("brain:last", out)
        return out
    state.put("brain:evaluating", now)
    feed.emit("brain_evaluation", "synapse", message="Comparing results by audience")
    groups = []
    try:
        for (platform, cohort, gv), ev in sorted(evidence(settings, now).items()):
            if cohort not in STRATEGY_COHORTS or not platform:
                continue
            if gv != _group_version(platform, settings):
                continue  # results from before the audience group changed are a different audience
            groups.append(evaluate_group(platform, cohort, gv, ev, settings, now))
    except Exception as exc:  # noqa: BLE001 - recorded as the Brain's Error state; the job reports it too
        state.put("brain:last", {"at": now, "state": "error", "groups": groups, "message": str(exc)[:300]})
        raise
    finally:
        state.delete("brain:evaluating")
    changed = [g for g in groups if g["result"] in ("updated", "rolled_back")]
    msg = "; ".join(g["message"] for g in changed) or (groups[0]["message"] if groups else
                                                       "Not enough evidence yet: no results from selected viewers.")
    out = {"at": now, "state": "updated" if changed else "collecting", "groups": groups, "message": msg}
    state.put("brain:last", out)
    feed.emit("brain_evaluated", "curator", message=msg[:300], changed=len(changed))
    return out


# ------------------------------------------------------------------ what the pages show
def summary(settings: dict | None = None) -> dict:
    settings = _settings(settings)
    counts = {p: int(db.scalar("SELECT COUNT(*) FROM brain_observations WHERE provenance = ?", (p,)) or 0)
              for p in PROVENANCE}
    last = state.get("brain:last") or {}
    strategies = db.select("brain_strategies", "status = 'active'", (), "platform, version DESC")
    if settings.get("brain_paused"):
        st = "paused"
    elif state.get("brain:evaluating"):
        st = "evaluating"
    elif last.get("state") == "error":
        st = "error"
    elif not any(counts.values()):
        st = "cold_start"
    elif strategies:
        st = "updated"
    else:
        st = "collecting"
    message = {"cold_start": "No results yet. Autopilot uses your own settings.",
               "paused": "Learning is paused: results are still collected, no strategy changes."}.get(st) or \
        last.get("message") or "Not enough evidence yet."
    return {"state": st, "label": STATE_LABELS[st], "message": message, "observations": counts,
            "groups": last.get("groups") or [], "last_evaluated": last.get("at"),
            "strategies": [{k: s.get(k) for k in ("id", "name", "platform", "cohort", "version", "params", "reason",
                                                  "created_at")} for s in strategies],
            "baseline_target": _baseline(settings), "min_clips": max(30, int(settings.get("brain_min_clips") or 30)),
            "max_step": min(0.10, float(settings.get("brain_max_step") or 0.10))}


def history(limit: int = 50) -> list[dict]:
    return db.select("brain_strategies", "", (), "created_at DESC", limit)


def clip_results(clip_id: str) -> dict:
    """A clip's evidence for the Test feedback page: per provenance, newest first, and what it means."""
    rows = observations(clip_id)
    testers = {r["tester"].lower() for r in rows if r["provenance"] == "tester_feedback" and r.get("tester")}
    return {"observations": rows, "testers": len(testers),
            "has": {p: any(r["provenance"] == p for r in rows) for p in PROVENANCE}}

"""Smart Scheduler: when each packaged clip goes out, per platform. Everything it decides is stored, so the plan
survives restarts.

* Time zone America/Chicago by default; posts only inside the active hours, with a minimum gap per platform.
* Posting times come from your own results (learning.py): until there is enough history, the day's posts are spread
  evenly over the active hours. No generic "best times" are assumed.
* Platform limits (configured, and learned from platform refusals) and the daily clip target are respected; the
  target is never reached by lowering the quality bar.
* Final Opportunity Score = an explained, weighted mix of the Clip, Packaging, Trend, Source, Diversity, Expected
  Retention and Publish Opportunity scores. Better items get better slots; a trending clip is posted sooner.
* Every post waits for your approval (YouTube and TikTok require users to control what is published). Approved posts
  are published at their time without another click.
* Dynamic replacement: a clearly stronger new opportunity takes the slot of the weakest future item that has not
  started. Nothing that is uploading or published is touched; an approved post is only swapped once you approve its
  replacement. Every replacement is written to the item's audit trail.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import time
from pathlib import Path

from .. import db
from ..pipeline import artifact, fingerprint
from . import gate, learner, queue, rights, state
from .host import Job, handler
from .scout import local_day, tz

PLATFORMS = ("youtube", "tiktok")
LOCK_MINUTES = 20          # this close to its time an item is never moved or replaced
HORIZON_DAYS = 2           # plan today and the next two days
MISSED_GRACE_HOURS = 48    # an unapproved item that missed its slot this long ago is retired
OVERDUE_MINUTES = 15       # an approved item this late (app was off) gets a new slot instead of posting late
ACTIVE = ("awaiting_approval", "approved", "publishing", "reconciling")  # reconciling: may already be live
DONE = ("published",)
FINAL_WEIGHTS = {"clip": 0.35, "packaging": 0.15, "trend": 0.15, "source": 0.10, "diversity": 0.10,
                 "retention": 0.10, "publish_opportunity": 0.05}
SCORE_LABELS = {"clip": "Clip Score", "packaging": "Packaging Score", "trend": "Trend Score", "source": "Source Score",
                "diversity": "Diversity Score", "retention": "Expected Retention", "publish_opportunity":
                "Publish Opportunity"}


def _now() -> float:
    return time.time()


def _audit(item: dict, event: str, detail: str, **data: object) -> list[dict]:
    return [*(item.get("audit") or []), {"at": _now(), "event": event, "detail": detail, **data}]


# ------------------------------------------------------------------ limits
def daily_limit(settings: dict, platform: str) -> int:
    """Posts per day on a platform: your setting, lowered by any limit the platform itself reported."""
    configured = int(settings.get(f"autopilot_{platform}_daily_limit") or 0)
    rows = db.select("platform_limits", "platform = ? AND key = 'daily_posts'", (platform,))
    if rows and rows[0]["value"] is not None:
        return min(configured, int(rows[0]["value"]))
    return configured


def blocked_until(platform: str, now: float | None = None) -> tuple[float, str]:
    rows = db.select("platform_limits", "platform = ? AND key = 'blocked_until'", (platform,))
    if rows and (rows[0]["value"] or 0) > (now or _now()):
        return float(rows[0]["value"]), rows[0]["note"] or ""
    return 0.0, ""


def block_platform(platform: str, until: float, note: str) -> None:
    """A platform refused posting for now (daily cap, spam limit): no more posts there until `until`."""
    db.insert("platform_limits", {"platform": platform, "key": "blocked_until", "value": until, "origin": "observed",
                                  "note": note[:300], "updated_at": _now()}, key="platform", replace=True)
    state.event("platform_limit", f"{platform}: {note}", "warning", until=until)


# ------------------------------------------------------------------ time slots
def _local(ts: float, settings: dict) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts, tz(settings))


def _label(ts: float, settings: dict) -> str:
    """How a time is shown to you (in the Autopilot time zone)."""
    return _local(ts, settings).strftime("%a %b %d, %H:%M")


def grid(settings: dict, day: dt.date, per_day: int) -> list[float]:
    """Evenly spaced candidate times over the active hours of a local day (never closer than the minimum gap)."""
    zone = tz(settings)
    start_h = int(settings.get("autopilot_active_start") or 9)
    end_h = int(settings.get("autopilot_active_end") or 23)
    if end_h <= start_h:
        end_h = start_h + 1
    minutes = (end_h - start_h) * 60
    gap = float(settings.get("autopilot_min_gap_minutes") or 45)
    step = max(gap, minutes / max(1, per_day), 15.0)
    base = dt.datetime.combine(day, dt.time(start_h, 0), zone)
    out, k = [], 0
    while True:
        m = k * step + step / 2 if per_day > 1 else minutes / 2
        if m >= minutes:
            break
        t = base + dt.timedelta(minutes=5 * round(m / 5))
        out.append(t.timestamp())
        k += 1
        if per_day <= 1:
            break
    return out


class Timing:
    """Your own results by hour and weekday (from learning.py). 1.0 = your average; no data = even spreading."""

    def __init__(self, platform: str, settings: dict):
        self.platform = platform
        self.hour: dict[int, float] = {}
        self.weekday: dict[int, float] = {}
        self.samples = 0
        if settings.get("autopilot_learning", True):
            for r in db.select("learning_metrics", "platform = ? AND dimension IN ('hour', 'weekday') AND "
                                                   "metric = 'performance'", (platform,)):
                if not (r.get("data") or {}).get("reliable"):
                    continue  # too few posts in this group to trust
                target = self.hour if r["dimension"] == "hour" else self.weekday
                try:
                    target[int(r["key"])] = float(r["lift"] if r["lift"] is not None else 1.0)
                except (TypeError, ValueError):
                    continue
                self.samples = max(self.samples, int(r["n"] or 0))

    def quality(self, local: dt.datetime) -> tuple[float, str]:
        h, d = self.hour.get(local.hour), self.weekday.get(local.weekday())
        if h is None and d is None:
            return 0.5, "no posting history yet: spread evenly over your active hours"
        lift = (h or 1.0) * (d or 1.0)
        return max(0.0, min(1.0, 0.5 * lift)), f"{lift:.2f}x your average at this hour/weekday (your results)"


def final_score(scores: dict, learned: dict[str, float] | None = None) -> tuple[float, list[str]]:
    """Weighted mix of the available scores (each 0-100); missing ones are left out and the weights renormalized.
    `learned` weights (from how well each score ordered your real results) replace the defaults they cover."""
    weights = {**FINAL_WEIGHTS, **{k: v for k, v in (learned or {}).items() if k in FINAL_WEIGHTS}}
    avail = {k: float(v) for k, v in scores.items() if k in weights and v is not None}
    if not avail:
        return 0.0, ["no scores"]
    total = sum(weights[k] for k in avail)
    value = sum(weights[k] * v for k, v in avail.items()) / total
    why = [f"{SCORE_LABELS[k]} {v:.0f} × {weights[k] / total:.0%}" for k, v in
           sorted(avail.items(), key=lambda kv: -weights[kv[0]])]
    if learned:
        why.append("weights adjusted from your own results: " + ", ".join(SCORE_LABELS[k] for k in learned
                                                                           if k in FINAL_WEIGHTS))
    missing = [SCORE_LABELS[k] for k in FINAL_WEIGHTS if k not in avail]
    if missing:
        why.append("not counted (not available): " + ", ".join(missing))
    return round(value, 1), why


# ------------------------------------------------------------------ what can be scheduled
def active_version_path(clip: dict) -> tuple[str, str]:
    """(video path, version id) that would be published for this clip."""
    path, version, _ = artifact.active(clip)
    return path, version


def _published_or_active(clip_id: str, platform: str) -> bool:
    if db.scalar("SELECT COUNT(*) FROM scheduled_publications WHERE clip_id = ? AND platform = ? AND status IN "
                 "('awaiting_approval', 'approved', 'publishing', 'reconciling', 'published')", (clip_id, platform)):
        return True
    return bool(db.scalar("SELECT COUNT(*) FROM publications WHERE clip_id = ? AND platform = ? AND status IN "
                          "('done', 'action_needed', 'uploading', 'processing', 'queued')", (clip_id, platform)))


def _repeat_of_published(clip: dict) -> str:
    """Title of an already published/scheduled clip that this one repeats ("" if none)."""
    mine = db.fetch("clip_fingerprints", clip["id"], "clip_id")
    if not mine:
        return ""
    others = db.select("clip_fingerprints", "clip_id != ? AND clip_id IN (SELECT clip_id FROM publications WHERE "
                                            "status IN ('done', 'action_needed', 'uploading', 'processing') UNION "
                                            "SELECT clip_id FROM scheduled_publications WHERE status IN "
                                            "('awaiting_approval', 'approved', 'publishing', 'reconciling', "
                                            "'published'))",
                       (clip["id"],))
    for o in others:
        if fingerprint.text_similarity(mine.get("text_sig") or [], o.get("text_sig") or []) >= 0.6 or \
                fingerprint.same_video(mine.get("phash") or [], o.get("phash") or []):
            return o.get("title_norm") or o["clip_id"]
    return ""


def candidates(settings: dict, now: float) -> list[dict]:
    """(clip, platform) pairs ready to be scheduled, with their scores."""
    out = []
    rows = db.select("clips", "status = 'ready' AND project_id IN (SELECT id FROM projects WHERE origin IN "
                              "('autopilot', 'live'))", (), "created_at")
    platforms = [p for p in PLATFORMS if settings.get(f"autopilot_{p}")]
    for clip in rows:
        project = db.get_project(clip["project_id"]) or {}
        source = db.fetch("sources", project.get("source_id") or "") if project.get("source_id") else None
        try:
            rights.gate(source, "schedule", settings)
        except rights.RightsBlocked:
            continue
        if not settings.get("autopilot_allow_republish"):
            repeat = _repeat_of_published(clip)
            if repeat:
                continue
        sc = db.fetch("clip_scores", clip["id"], "clip_id") or {}
        retention, _ = learner.expected_retention(sc.get("retention"))
        for platform in platforms:
            if not settings.get("autopilot_allow_republish") and _published_or_active(clip["id"], platform):
                continue
            meta = db.select("metadata_candidates", "clip_id = ? AND platform = ? AND selected = 1",
                             (clip["id"], platform))
            if not meta or not gate.schedulable(clip, platform, meta[0]["id"])[0]:
                continue  # not packaged, or the final quality gate has not passed this file and text
            signal = db.fetch("trend_signals", (source or {}).get("signal_id") or "") if source and \
                source.get("signal_id") else None
            urgency = (signal or {}).get("score") or 0.0
            out.append({"clip": clip, "platform": platform, "meta": meta[0], "source": source,
                        "scores": {"clip": sc.get("clip", clip.get("score")), "packaging": meta[0]["score"],
                                   "trend": sc.get("trend"), "source": sc.get("source"),
                                   "diversity": sc.get("diversity"), "retention": retention},
                        "urgency": max(0.0, min(1.0, urgency / 100))})
    return out


# ------------------------------------------------------------------ planning
class Plan:
    """Occupied slots and daily counts, built from the stored items."""

    def __init__(self, settings: dict, now: float):
        self.settings = settings
        self.now = now
        self.items = db.select("scheduled_publications", "status IN ('awaiting_approval', 'approved', 'publishing', "
                                                         "'reconciling', 'published') AND planned_at IS NOT NULL")
        self.gap = 60.0 * float(settings.get("autopilot_min_gap_minutes") or 45)

    def occupies(self, item: dict) -> bool:
        """A pending swap shares its slot with the item it would replace, so it takes no slot of its own."""
        return not (item.get("replaces") and any(o["id"] == item["replaces"] and o["status"] in ACTIVE
                                                 for o in self.items))

    def _counts(self, platform: str, day: str) -> tuple[int, set]:
        n, clips = 0, set()
        for it in self.items:
            if not self.occupies(it):
                continue
            if local_day(self.settings, it["planned_at"]) != day:
                continue
            clips.add(it["clip_id"])
            n += it["platform"] == platform
        return n, clips

    def free(self, platform: str, t: float, clip_id: str) -> bool:
        day = local_day(self.settings, t)
        count, clips = self._counts(platform, day)
        if count >= daily_limit(self.settings, platform):
            return False
        if clip_id not in clips and len(clips) >= int(self.settings.get("autopilot_daily_target") or 15):
            return False
        return all(abs(it["planned_at"] - t) >= self.gap for it in self.items if it["platform"] == platform
                   and self.occupies(it))

    def best_slot(self, platform: str, clip_id: str, urgency: float, timing: Timing) -> tuple[float, dict] | None:
        start = self.now + 60.0 * (LOCK_MINUTES + 5)
        blocked, _ = blocked_until(platform, self.now)
        start = max(start, blocked)
        per_day = max(1, min(daily_limit(self.settings, platform), int(self.settings.get("autopilot_daily_target")
                                                                         or 15)))
        best = None
        today = _local(self.now, self.settings).date()
        for d in range(HORIZON_DAYS + 1):
            for t in grid(self.settings, today + dt.timedelta(days=d), per_day):
                if t < start or not self.free(platform, t, clip_id):
                    continue
                q, note = timing.quality(_local(t, self.settings))
                days_out = (t - self.now) / 86400
                value = q - 0.25 * urgency * days_out - 0.05 * days_out  # trending clips go out sooner
                if best is None or value > best[0] + 1e-9:
                    best = (value, t, {"quality": round(q, 3), "note": note,
                                       "local": _local(t, self.settings).isoformat(timespec="minutes")})
        return (best[1], best[2]) if best else None

    def add(self, item: dict) -> None:
        self.items.append(item)


def _opportunity(slot: dict, urgency: float, planned_at: float, now: float) -> float:
    freshness = math.exp(-max(0.0, planned_at - now) / 3600 / 48) if urgency else 1.0
    return round(100 * (0.7 * slot["quality"] + 0.3 * freshness), 1)


def _meta_fields(c: dict, settings: dict) -> dict:
    meta, platform = c["meta"], c["platform"]
    if platform == "youtube":
        return {"title": meta["title"], "description": meta["description"], "tags": meta["tags"] or [],
                "privacy": settings.get("autopilot_youtube_privacy") or "public", "options": {"made_for_kids": None}}
    return {"title": meta["title"], "description": meta["caption"], "tags": meta["hashtags"] or [], "privacy": "",
            "options": {"mode": "direct", "allow_comment": False, "allow_duet": False, "allow_stitch": False,
                        "disclose": False}}


def create_item(c: dict, planned_at: float, slot: dict, settings: dict, now: float, replaces: str = "",
                audit: list | None = None) -> dict:
    opp = _opportunity(slot, c["urgency"], planned_at, now)
    scores = {**c["scores"], "publish_opportunity": opp}
    final, why = final_score(scores, learner.weights())
    item = db.insert("scheduled_publications", {
        "clip_id": c["clip"]["id"], "source_id": (c["source"] or {}).get("id", ""), "platform": c["platform"],
        "metadata_id": c["meta"]["id"], **_meta_fields(c, settings), "planned_at": planned_at,
        "timezone": settings.get("autopilot_timezone") or "America/Chicago", "slot": slot, "final_score": final,
        "scores": {**scores, "explanation": why}, "status": "awaiting_approval", "replaces": replaces,
        "status_note": "Waiting for your approval",
        "audit": audit or [{"at": now, "event": "scheduled", "detail": f"Planned for {_label(planned_at, settings)} "
                                                                        f"({slot['note']}); Final Opportunity Score "
                                                                        f"{final:.0f}"}]})
    state.event("scheduled", f"{c['platform']}: “{c['meta']['title'][:60]}” planned for "
                             f"{_label(planned_at, settings)}", ref_type="scheduled", ref_id=item["id"], final=final)
    return item


def weakest_replaceable(platform: str, now: float) -> dict | None:
    rows = db.select("scheduled_publications", "platform = ? AND status IN ('awaiting_approval', 'approved') AND "
                                               "planned_at > ? AND replaced_by = '' AND replaces = ''",
                     (platform, now + 60 * LOCK_MINUTES), "final_score ASC", 1)
    return rows[0] if rows else None


def try_replace(c: dict, settings: dict, now: float, plan: Plan) -> dict | None:
    """Dynamic replacement: a clearly stronger opportunity takes the weakest future slot."""
    if not settings.get("autopilot_dynamic_replacement"):
        return None
    weak = weakest_replaceable(c["platform"], now)
    if not weak:
        return None
    probe = final_score({**c["scores"], "publish_opportunity": (weak.get("scores") or {}).get("publish_opportunity")},
                        learner.weights())
    threshold = float(settings.get("autopilot_replacement_threshold") or 15)
    if probe[0] < (weak["final_score"] or 0) * (1 + threshold / 100):
        return None
    reason = (f"Final Opportunity Score {probe[0]:.0f} vs {weak['final_score']:.0f} (needs {threshold:.0f}% better)")
    slot = weak.get("slot") or {"quality": 0.5, "note": "", "local": _local(weak["planned_at"], settings).isoformat()}
    new = create_item(c, weak["planned_at"], slot, settings, now, replaces=weak["id"],
                      audit=[{"at": now, "event": "replacement", "detail": f"Takes the slot of “{weak['title'][:60]}”: "
                                                                            f"{reason}", "replaces": weak["id"]}])
    if weak["status"] == "approved":
        db.update("scheduled_publications", new["id"], status_note="Approve it to replace the weaker approved post in "
                                                                  "this slot; until then that post stays scheduled.")
        db.update("scheduled_publications", weak["id"], audit=_audit(weak, "replacement_proposed",
                                                                     f"A stronger clip was proposed for this slot: "
                                                                     f"{reason}", by=new["id"]))
    else:
        db.update("scheduled_publications", weak["id"], status="replaced", replaced_by=new["id"],
                  status_note=f"Replaced by a stronger opportunity: {reason}",
                  audit=_audit(weak, "replaced", f"Replaced by “{new['title'][:60]}”: {reason}", by=new["id"]))
        state.event("replaced", f"{c['platform']}: “{weak['title'][:60]}” replaced by “{new['title'][:60]}” ({reason})",
                    ref_type="scheduled", ref_id=weak["id"], by=new["id"])
    plan.add(new)
    return new


def plan_new(settings: dict, now: float) -> dict:
    plan = Plan(settings, now)
    timings = {p: Timing(p, settings) for p in PLATFORMS}
    created, replaced, no_slot = 0, 0, 0
    cands = candidates(settings, now)
    learned = learner.weights()
    for c in cands:
        c["rank"], _ = final_score({**c["scores"], "publish_opportunity": 50.0}, learned)
    for c in sorted(cands, key=lambda c: c["rank"], reverse=True):
        slot = plan.best_slot(c["platform"], c["clip"]["id"], c["urgency"], timings[c["platform"]])
        if slot:
            plan.add(create_item(c, slot[0], slot[1], settings, now))
            created += 1
        elif try_replace(c, settings, now, plan):
            replaced += 1
        else:
            no_slot += 1
    return {"created": created, "replaced": replaced, "waiting_for_slot": no_slot}


# ------------------------------------------------------------------ approvals
def approval_hash(item: dict) -> str:
    clip = db.get_clip(item["clip_id"]) or {}
    path, version = active_version_path(clip)
    try:
        st = Path(path).stat()
        video = f"{path}:{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        video = path
    data = {k: item.get(k) for k in ("platform", "title", "description", "tags", "privacy", "options")}
    data.update(video=video, version=version)
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def approval_valid(item: dict) -> bool:
    return item["status"] in ("approved", "publishing") and (item.get("approval") or {}).get("hash") == \
        approval_hash(item)


def check_platform(item: dict, creator: dict | None = None) -> None:
    """What the platform would refuse, checked before the approval is accepted (raises PublishError)."""
    from ..publish import tiktok, youtube
    from ..publish.common import PublishError

    settings = db.get_settings()
    opts = item.get("options") or {}
    if item["platform"] == "youtube":
        if opts.get("made_for_kids") is None:
            raise PublishError("Say whether this video is made for kids.", "YouTube requires this answer (COPPA).")
        youtube.video_body(item["title"], item["description"], item.get("tags") or [], item["privacy"],
                           bool(opts["made_for_kids"]), settings.get("youtube_category_id") or "22")
    else:
        clip = db.get_clip(item["clip_id"]) or {}
        mode = opts.get("mode") or "direct"
        tiktok.validate(item["description"], item.get("privacy") or "", opts, mode, settings, creator,
                        float(clip.get("duration") or 0))


def approve(item_id: str, fields: dict, creator: dict | None = None) -> dict:
    """The user's explicit approval of exactly this content, visibility and settings (validated first)."""
    item = db.fetch("scheduled_publications", item_id)
    if not item:
        raise ValueError("Scheduled post not found")
    if item["status"] not in ("awaiting_approval", "approved", "failed"):
        raise ValueError(f"This post is {item['status'].replace('_', ' ')}; it cannot be approved now")
    updated = {**item, **{k: v for k, v in fields.items() if k in ("title", "description", "tags", "privacy",
                                                                     "options")}}
    check_platform(updated, creator)
    rep = gate.report_for(db.get_clip(item["clip_id"]) or {})
    if rep and rep["status"] != "passed":  # not checked yet is fine: the publisher waits for the check
        raise ValueError("The clip's file did not pass the final quality check (" + "; ".join(rep["blockers"][:2])
                         + "). Fix the clip and render it again before approving it.")
    now = _now()
    approval = {"at": now, "by": "you", "hash": approval_hash(updated)}
    db.update("scheduled_publications", item_id, **{k: updated[k] for k in ("title", "description", "tags", "privacy",
                                                                             "options")},
              status="approved", approval=approval, last_error="", fix="",
              status_note="Approved: it will be published at its time" if item["planned_at"] > now else
              "Approved: publishing now",
              audit=_audit(item, "approved", "Approved by you", privacy=updated["privacy"]))
    if item.get("replaces"):
        weak = db.fetch("scheduled_publications", item["replaces"])
        if weak and weak["status"] in ("awaiting_approval", "approved") and \
                weak["planned_at"] > now + 60 * LOCK_MINUTES:
            db.update("scheduled_publications", weak["id"], status="replaced", replaced_by=item_id,
                      status_note="Replaced by a stronger opportunity you approved",
                      audit=_audit(weak, "replaced", "Replaced by an approved, stronger opportunity", by=item_id))
            state.event("replaced", f"“{weak['title'][:60]}” replaced by “{updated['title'][:60]}”",
                        ref_type="scheduled", ref_id=weak["id"], by=item_id)
        elif weak and weak["status"] in ACTIVE + DONE:
            db.update("scheduled_publications", item_id, replaces="", planned_at=None,
                      status_note="The post it would have replaced already started; a new time will be chosen")
    state.event("approved", f"{item['platform']}: “{updated['title'][:60]}” approved", ref_type="scheduled",
                ref_id=item_id)
    return db.fetch("scheduled_publications", item_id) or item


def edit(item_id: str, fields: dict) -> dict:
    """Change the text or settings. An approved post needs to be approved again afterwards."""
    item = db.fetch("scheduled_publications", item_id)
    if not item or item["status"] in ("publishing", "reconciling", "published"):
        raise ValueError("This post can no longer be edited")
    clean = {k: v for k, v in fields.items() if k in ("title", "description", "tags", "privacy", "options")}
    changes = {**clean}
    if item["status"] == "approved":
        changes.update(status="awaiting_approval", approval={}, status_note="Edited: approve it again")
    db.update("scheduled_publications", item_id, **changes, audit=_audit(item, "edited", "Edited by you",
                                                                          fields=sorted(clean)))
    return db.fetch("scheduled_publications", item_id) or item


def reschedule(item_id: str, planned_at: float) -> dict:
    item = db.fetch("scheduled_publications", item_id)
    if not item or item["status"] not in ("awaiting_approval", "approved", "failed"):
        raise ValueError("This post can no longer be moved")
    settings = db.get_settings()
    gap = 60.0 * float(settings.get("autopilot_min_gap_minutes") or 45)
    for other in db.select("scheduled_publications", "platform = ? AND id != ? AND status IN ('awaiting_approval', "
                                                     "'approved', 'publishing', 'reconciling', 'published')",
                           (item["platform"], item_id)):
        if other["planned_at"] and abs(other["planned_at"] - planned_at) < gap:
            raise ValueError(f"Less than {gap / 60:.0f} minutes from another {item['platform']} post "
                             f"(“{other['title'][:40]}”)")
    local = _local(planned_at, settings)
    slot = {**(item.get("slot") or {}), "local": local.isoformat(timespec="minutes"), "note": "chosen by you"}
    status = item["status"]
    if status == "failed":  # a retry at a new time: still approved only if nothing changed since the approval
        status = "approved" if approval_valid({**item, "status": "approved"}) else "awaiting_approval"
    db.update("scheduled_publications", item_id, planned_at=planned_at, slot=slot, status=status,
              audit=_audit(item, "rescheduled", f"Moved to {_label(planned_at, settings)} by you"))
    return db.fetch("scheduled_publications", item_id) or item


def cancel(item_id: str, reason: str = "Canceled by you") -> dict:
    item = db.fetch("scheduled_publications", item_id)
    if not item:
        raise ValueError("Scheduled post not found")
    if item["status"] in ("publishing", "reconciling", "published"):
        raise ValueError("This post is already being published (or may already be live): check it first")
    db.update("scheduled_publications", item_id, status="canceled", status_note=reason,
              audit=_audit(item, "canceled", reason))
    for j in queue.jobs(("queued", "retrying", "waiting"), ref=("scheduled", item_id)):
        queue.cancel(j["id"], reason)
    return db.fetch("scheduled_publications", item_id) or item


# ------------------------------------------------------------------ the tick
def lead_seconds(item: dict, settings: dict) -> float:
    """YouTube posts are uploaded early and published by YouTube at the planned time (publishAt)."""
    if item["platform"] == "youtube":
        return 60.0 * float(settings.get("autopilot_upload_lead_minutes") or 30)
    return 0.0


ORPHAN_AFTER = 120  # seconds a post may show "publishing" without a publish job before it is reconciled


def reconcile_orphans(now: float) -> int:
    """Posts left "publishing" without a publish job (STOP ALL canceled it while it waited, or the worker died):
    one that never started uploading gets a new time; one that did is checked with the platform ("reconciling"),
    never uploaded again blindly."""
    active = {j["ref_id"] for j in queue.jobs(("queued", "running", "waiting", "retrying"), worker="publisher",
                                              limit=1000)}
    n = 0
    for item in db.select("scheduled_publications", "status = 'publishing' AND updated_at < ?", (now - ORPHAN_AFTER,)):
        if item["id"] in active:
            continue
        if item.get("publication_id"):
            db.update("scheduled_publications", item["id"], status="reconciling",
                      status_note="Checking with the platform whether the upload finished",
                      audit=_audit(item, "reconciling", "The upload job stopped before it finished; checking with the "
                                                        "platform what happened"))
            queue.enqueue("publish", {"scheduled_id": item["id"]}, idem_key=f"publish:{item['id']}",
                          ref=("scheduled", item["id"]), max_attempts=5, timeout_s=3 * 3600,
                          message="Checking what happened to the upload")
        else:
            db.update("scheduled_publications", item["id"], status="approved", planned_at=None,
                      status_note="The upload never started; a new time will be chosen",
                      audit=_audit(item, "requeued", "The upload job stopped before the upload started"))
        n += 1
    return n


def process_due(settings: dict, now: float) -> dict:
    started, moved, retired = 0, 0, 0
    waiting = 0
    reconciled = reconcile_orphans(now)
    for item in db.select("scheduled_publications", "status IN ('approved', 'awaiting_approval') AND planned_at IS "
                                                    "NOT NULL", (), "planned_at"):
        if item["status"] == "approved":
            if item["planned_at"] - lead_seconds(item, settings) > now:
                continue
            if item["planned_at"] < now - 60 * OVERDUE_MINUTES:
                # e.g. the computer was off at its time: find a new slot instead of posting several at once
                db.update("scheduled_publications", item["id"], planned_at=None,
                          audit=_audit(item, "overdue", "Its time passed while ClipFoundry was not running; a new "
                                                        "time will be chosen (still approved)"))
                moved += 1
                continue
            if not approval_valid(item):
                db.update("scheduled_publications", item["id"], status="awaiting_approval", approval={},
                          status_note="The clip or its text changed after approval: approve it again",
                          audit=_audit(item, "approval_invalidated", "Content changed after approval"))
                continue
            if not settings.get("autopilot_auto_publish"):
                state.action(f"publish:{item['id']}", "publish", f"Publish “{item['title'][:60]}” now?",
                             "Automatic publishing is off, so approved posts wait for you at their time.",
                             "Publish Center → Publish now.", ref_type="scheduled", ref_id=item["id"])
                continue
            queue.enqueue("publish", {"scheduled_id": item["id"]}, idem_key=f"publish:{item['id']}",
                          ref=("scheduled", item["id"]), max_attempts=5, timeout_s=3 * 3600)
            db.update("scheduled_publications", item["id"], status="publishing", status_note="Queued for upload",
                      audit=_audit(item, "publish_queued", "Due: queued for upload"))
            started += 1
        elif item["planned_at"] < now:
            waiting += 1
            if now - item["planned_at"] > 3600 * MISSED_GRACE_HOURS:
                db.update("scheduled_publications", item["id"], status="canceled",
                          status_note="Not approved within 48 hours of its slot",
                          audit=_audit(item, "expired", "Missed its slot waiting for approval"))
                retired += 1
            elif item["planned_at"] < now - 60 * 10:
                db.update("scheduled_publications", item["id"], planned_at=None,
                          audit=_audit(item, "missed", "Missed its slot waiting for approval; a new time will be "
                                                       "chosen"))
                moved += 1
    # items without a time (missed slot, failed swap) get a new one
    plan = Plan(settings, now)
    for item in db.select("scheduled_publications", "status IN ('awaiting_approval', 'approved') AND planned_at IS "
                                                    "NULL"):
        timing = Timing(item["platform"], settings)
        slot = plan.best_slot(item["platform"], item["clip_id"], 0.0, timing)
        if slot:
            db.update("scheduled_publications", item["id"], planned_at=slot[0], slot=slot[1], replaces="",
                      audit=_audit(item, "rescheduled", f"New time {slot[1]['local']}"))
            plan.add({**item, "planned_at": slot[0], "replaces": ""})
    pending = int(db.scalar("SELECT COUNT(*) FROM scheduled_publications WHERE status = 'awaiting_approval'") or 0)
    if pending:
        state.action("approvals", "approve", f"{pending} post{'s' if pending != 1 else ''} waiting for your approval",
                     "YouTube and TikTok require that you approve what is published. Approved posts go out at "
                     "their time automatically.", "Open the Publish Center, review and approve.")
    else:
        state.resolve("approvals")
    return {"publishing": started, "missed": moved, "expired": retired, "overdue_unapproved": waiting,
            "awaiting_approval": pending, "reconciled": reconciled}


@handler("schedule_tick")
def schedule_tick(job: Job) -> dict:
    settings = db.get_settings()
    now = _now()
    due = process_due(settings, now)
    planned = plan_new(settings, now) if settings.get("autopilot_auto_schedule") else {"created": 0}
    return {**due, **planned, "message": f"{planned.get('created', 0)} scheduled, {planned.get('replaced', 0)} "
                                         f"replaced, {due['publishing']} publishing"}

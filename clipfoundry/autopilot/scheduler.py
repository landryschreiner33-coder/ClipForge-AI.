"""Smart Scheduler: when each packaged clip goes out, per platform. Everything it decides is stored, so the plan
survives restarts.

* Time zone America/Chicago by default; posts only inside the active hours, with a minimum gap per platform.
* Posting times come from your own results (learning.py): until there is enough history, the day's posts are spread
  evenly over the active hours. No generic "best times" are assumed.
* Platform limits (configured, and learned from platform refusals) and the daily clip target are respected; the
  target is never reached by lowering the quality bar.
* Final Opportunity Score = an explained, weighted mix of the Clip, Packaging, Trend, Source, Diversity, Expected
  Retention and Publish Opportunity scores. Better items get better slots; a trending clip is posted sooner.
* A post goes out only with an approval: yours, or the automatic-publishing permission you gave for a platform whose
  rules allow it (autopublish.py: YouTube; TikTok requires your OK on each post). A post approved under that
  permission is marked "approved automatically", never "approved by you", and only clips that passed every check
  qualify. Approved posts are published at their time without another click.
* The coverage's conditions are kept: a video an agreement allows only on some platforms is only planned there.
* Dynamic replacement: a clearly stronger new opportunity takes the slot of the weakest future item that has not
  started. Nothing that is uploading or published is touched; an approved post is only swapped once you approve its
  replacement. Every replacement is written to the item's audit trail.
"""
from __future__ import annotations

import datetime as dt
import math
import time
from pathlib import Path

from .. import db
from ..pipeline import artifact, fingerprint
from ..publish import audience
from . import autopublish, gate, learner, queue, rights, state
from .host import Job, handler
from .scout import local_day, tz

PLATFORMS = ("youtube", "tiktok")
LOCK_MINUTES = 20          # this close to its time an item is never moved or replaced
HORIZON_DAYS = 2           # plan today and the next two days
MISSED_GRACE_HOURS = 48    # an unapproved item that missed its slot this long ago is retired
OVERDUE_MINUTES = 15       # an approved item this late (app was off) gets a new slot instead of posting late
REPLACEMENT_COOLDOWN_HOURS = 24  # a slot takes part in at most one replacement a day (setting overrides it)
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


def uploadable_platforms(settings: dict) -> list[str]:
    """Platforms Autopilot plans posts for: turned on, and with a confirmed audience (publish/audience.py). Without
    one, clips stay ready on this PC and the overview says why."""
    return [p for p in PLATFORMS if settings.get(f"autopilot_{p}") and audience.destination(p, settings)["confirmed"]]


def audience_reminders(settings: dict) -> None:
    """One Needs you item per connected platform whose audience is not chosen yet (nothing uploads there until)."""
    for p in PLATFORMS:
        dest = audience.destination(p, settings)
        connected = bool((db.get_account(p) or {}).get("has_tokens"))
        if settings.get(f"autopilot_{p}") and connected and not dest["confirmed"] and dest["intent"] != \
                audience.LOCAL_ONLY:
            name = "YouTube" if p == "youtube" else "TikTok"
            state.action(f"audience_setup:{p}", "audience", f"Choose who watches your {name} clips",
                         f"Clips stay ready on this PC until you say who may watch them on {name}. ClipFoundry posts "
                         "only to viewers you pick, never publicly.",
                         f"Settings → Integrations → {name} → Who watches.")
        else:
            state.resolve(f"audience_setup:{p}")


def candidates(settings: dict, now: float) -> list[dict]:
    """(clip, platform) pairs ready to be scheduled, with their scores."""
    out = []
    rows = db.select("clips", "status = 'ready' AND project_id IN (SELECT id FROM projects WHERE origin IN "
                              "('autopilot', 'live'))", (), "created_at")
    platforms = uploadable_platforms(settings)
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
            if not rights.platform_allowed(source, platform, settings)[0]:
                continue  # e.g. an agreement that covers TikTok only
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
        self.held = 0  # replacements held back by the cooldown

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
    """The post's text and its audience. YouTube: always Private (the owner invites viewers in Studio). TikTok: no
    preset privacy (the owner picks it per post, among the audience's allowed options) and the route TikTok allows
    this app: Direct Post, an inbox draft, or a package the owner posts by hand."""
    meta, platform = c["meta"], c["platform"]
    want = audience.intent(platform, settings)
    dest = audience.destination(platform, settings)
    stamp = {"intent": want, "platform": platform, "policy_version": audience.POLICY_VERSION, "group": dest["group"],
             "group_version": dest["group_version"], "visibility": audience.visibility(platform, want, settings)}
    if platform == "youtube":
        return {"title": meta["title"], "description": meta["description"], "tags": meta["tags"] or [],
                "privacy": "private", "options": {"made_for_kids": None}, "audience": stamp}
    route = audience.tiktok_route(settings, db.get_account("tiktok"))
    return {"title": meta["title"], "description": meta["caption"], "tags": meta["hashtags"] or [], "privacy": "",
            "options": {"mode": route, "allow_comment": False, "allow_duet": False, "allow_stitch": False,
                        "disclose": False}, "audience": stamp}


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
    if auto_approve(item, settings, now):
        return db.fetch("scheduled_publications", item["id"]) or item
    return item


def replaceable(platform: str, now: float) -> list[dict]:
    """Future posts that dynamic replacement may swap out, weakest first (outside the freeze window, not a swap
    themselves, and without a stronger post already proposed for their slot)."""
    return db.select("scheduled_publications", "platform = ? AND status IN ('awaiting_approval', 'approved') AND "
                                                "planned_at > ? AND replaced_by = '' AND replaces = '' AND id NOT IN "
                                                "(SELECT replaces FROM scheduled_publications WHERE replaces != '' AND "
                                                "status IN ('awaiting_approval', 'approved', 'publishing', "
                                                "'reconciling'))",
                     (platform, now + 60 * LOCK_MINUTES), "final_score ASC")


def weakest_replaceable(platform: str, now: float) -> dict | None:
    rows = replaceable(platform, now)
    return rows[0] if rows else None


def cooldown_hours(settings: dict) -> float:
    return float(settings.get("autopilot_replacement_cooldown_hours", REPLACEMENT_COOLDOWN_HOURS) or 0)


def replacement_blocked(weak: dict, clip_id: str, settings: dict, now: float) -> str:
    """Why this post's slot is not replaced now ("" when it may be). The replacement history is stored
    (slot_replacements), so the cooldown holds across restarts: a slot, or a post that took part in a replacement,
    is not part of another one until the cooldown has passed, and a clip is proposed for the same post only once."""
    if db.scalar("SELECT COUNT(*) FROM slot_replacements WHERE replaced_id = ? AND clip_id = ?", (weak["id"], clip_id)):
        return "this clip was already proposed for this slot"
    hours = cooldown_hours(settings)
    last = db.scalar("SELECT MAX(created_at) FROM slot_replacements WHERE platform = ? AND (ABS(slot_at - ?) < 60 OR "
                     "replaced_id = ? OR replacement_id = ?)", (weak["platform"], weak["planned_at"], weak["id"],
                                                                weak["id"]))
    if hours and last and now - float(last) < hours * 3600:
        return f"its slot was part of a replacement less than {hours:g} hours ago"
    return ""


def try_replace(c: dict, settings: dict, now: float, plan: Plan) -> dict | None:
    """Dynamic replacement: a clearly stronger opportunity takes the weakest future slot that may be replaced."""
    if not settings.get("autopilot_dynamic_replacement"):
        return None
    threshold = float(settings.get("autopilot_replacement_threshold") or 15)
    for weak in replaceable(c["platform"], now):
        probe = final_score({**c["scores"], "publish_opportunity": (weak.get("scores") or {}).get(
            "publish_opportunity")}, learner.weights())
        if probe[0] < (weak["final_score"] or 0) * (1 + threshold / 100):
            return None  # weakest first: the stronger posts after it would not be beaten either
        if replacement_blocked(weak, c["clip"]["id"], settings, now):
            plan.held += 1
            continue
        return _replace(c, weak, probe[0], threshold, settings, now, plan)
    return None


def _replace(c: dict, weak: dict, score: float, threshold: float, settings: dict, now: float, plan: Plan) -> dict:
    reason = (f"Final Opportunity Score {score:.0f} vs {weak['final_score']:.0f} (needs {threshold:.0f}% better)")
    slot = weak.get("slot") or {"quality": 0.5, "note": "", "local": _local(weak["planned_at"], settings).isoformat()}
    new = create_item(c, weak["planned_at"], slot, settings, now, replaces=weak["id"],
                      audit=[{"at": now, "event": "replacement", "detail": f"Takes the slot of “{weak['title'][:60]}”: "
                                                                            f"{reason}", "replaces": weak["id"]}])
    weak = db.fetch("scheduled_publications", weak["id"]) or weak  # an automatic approval may have taken the slot
    db.insert("slot_replacements", {"replacement_id": new["id"], "platform": c["platform"],
                                    "slot_at": weak["planned_at"], "replaced_id": weak["id"],
                                    "clip_id": c["clip"]["id"], "created_at": now,
                                    "status": "proposed" if weak["status"] == "approved" else "replaced"},
              key="replacement_id")
    if weak["status"] == "replaced":
        pass  # approved automatically and swapped in already (_take_slot wrote the audit trail)
    elif weak["status"] == "approved":
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
    return {"created": created, "replaced": replaced, "waiting_for_slot": no_slot, "replacement_cooldown": plan.held}


# ------------------------------------------------------------------ approvals
# An approval is bound to the SHA-256 of the video's bytes, plus the post's text, visibility, platform options and
# the render version. Scheme 1 (older versions) used the file's size and modification time, which a re-render or
# an edit in place can keep; such approvals are never trusted, the post is approved again (YouTube automatically
# only under a permission still in force and a final check of these exact bytes; TikTok by you).
APPROVAL_SCHEME = 3  # 3: also bound to the audience (intent, policy and group versions; publish/audience.py)
_sha_memo: dict[str, tuple[tuple, str]] = {}  # path -> (stat key, SHA-256): only for the quick display check


def video_sha256(path: str, quick: bool = False) -> str:
    """SHA-256 of the file's bytes, "" when it is missing or unreadable. `quick` reuses the last hash while the file's
    size, times and identity are unchanged: for what the Publish Center shows every few seconds, never for a
    decision (an edit in place can keep all of them on Windows)."""
    try:
        st = Path(path).stat() if path else None
    except OSError:
        return ""
    if st is None or not Path(path).is_file():
        return ""
    key = (st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino, st.st_dev)
    if quick and _sha_memo.get(path, ((), ""))[0] == key:
        return _sha_memo[path][1]
    try:
        sha = artifact.sha256_file(path)
    except OSError:
        return ""
    _sha_memo[path] = (key, sha)
    return sha


def approval_basis(item: dict, quick: bool = False) -> dict | None:
    """What an approval covers, or None when the video that would be published is missing or unreadable."""
    clip = db.get_clip(item["clip_id"]) or {}
    path, version = active_version_path(clip)
    sha = video_sha256(path, quick)
    if not sha:
        return None
    data = {k: item.get(k) for k in ("platform", "title", "description", "tags", "privacy", "options")}
    stamp = item.get("audience") or {}
    data["audience"] = {k: stamp.get(k) for k in ("intent", "policy_version", "group", "group_version")}
    return {**data, "video_sha256": sha, "version": version, "scheme": APPROVAL_SCHEME}


def approval_hash(item: dict, quick: bool = False) -> str:
    basis = approval_basis(item, quick)
    return artifact.sha256_json(basis) if basis else ""


def approval_record(item: dict, **fields: object) -> dict | None:
    """The approval to store for exactly this content, or None when its video is missing or unreadable."""
    basis = approval_basis(item)
    if not basis:
        return None
    return {**fields, "hash": artifact.sha256_json(basis), "scheme": APPROVAL_SCHEME,
            "video_sha256": basis["video_sha256"]}


def approval_problem(item: dict, quick: bool = False) -> str:
    """Why the stored approval does not cover what would be published now ("" when it does)."""
    appr = item.get("approval") or {}
    if not appr.get("hash"):
        return "not approved"
    if appr.get("scheme") != APPROVAL_SCHEME:
        return ("approved before ClipFoundry checked who may watch it" if appr.get("scheme") == 2 else
                "approved before ClipFoundry checked the exact video file")
    stamp = item.get("audience") or {}
    if stamp.get("group_version"):
        dest = audience.destination(item["platform"], db.get_settings())
        if int(stamp["group_version"]) != dest["group_version"]:
            return "who watches changed after approval"
    current = approval_hash(item, quick)
    if not current:
        return "the video file is missing or cannot be read"
    return "" if appr["hash"] == current else "the clip or its text changed after approval"


def approval_valid(item: dict, quick: bool = False) -> bool:
    return item["status"] in ("approved", "publishing") and not approval_problem(item, quick)


def check_platform(item: dict, creator: dict | None = None) -> dict:
    """What the platform or the audience policy would refuse, checked before the approval is accepted (raises
    PublishError). Returns the audience stamp the post is approved for."""
    from ..publish import tiktok, youtube
    from ..publish.common import PublishError

    settings = db.get_settings()
    opts = item.get("options") or {}
    if item["platform"] == "youtube":
        if opts.get("made_for_kids") is None:
            raise PublishError("Say whether this video is made for kids.", "YouTube requires this answer (COPPA).")
        youtube.video_body(item["title"], item["description"], item.get("tags") or [], item["privacy"],
                           bool(opts["made_for_kids"]), settings.get("youtube_category_id") or "22")
        return audience.check("youtube", item["privacy"], settings, stamp=item.get("audience") or None)
    clip = db.get_clip(item["clip_id"]) or {}
    mode = opts.get("mode") or "direct"
    tiktok.validate(item["description"], item.get("privacy") or "", opts, mode if mode != "manual" else "inbox",
                    settings, creator, float(clip.get("duration") or 0))
    return audience.check("tiktok", item.get("privacy") or "", settings, mode=mode, creator=creator,
                          stamp=item.get("audience") or None)


def _note(item: dict, note: str) -> None:
    if item.get("status_note") != note:
        db.update("scheduled_publications", item["id"], status_note=note[:500])


def auto_approve(item: dict, settings: dict, now: float) -> bool:
    """Approve a post under your automatic-publishing permission, if the platform allows it and the clip qualifies.
    It is recorded as approved automatically (with the permission), never as approved by you."""
    from ..publish.common import PublishError

    consent = autopublish.active(item["platform"])
    if not consent or item["status"] != "awaiting_approval" or not item.get("planned_at"):
        return False
    if any(a.get("event") == "edited" for a in item.get("audit") or []):
        return False  # you changed this post yourself: you decide when it is ready
    cfg = consent.get("settings") or {}
    if cfg.get("visibility") != "private":  # a permission given for public videos covers nothing now
        return False
    clip = db.get_clip(item["clip_id"]) or {}
    report = gate.report_for(clip) if clip else None
    sha = video_sha256(active_version_path(clip)[0]) if clip else ""
    if not sha:
        _note(item, "Held for your review, not published automatically: the video file is missing or cannot be read")
        return False
    if report and report.get("artifact_sha256") != sha:  # same size and time, other bytes: check these ones
        gate.request(clip, sha=sha)
        report = None
    ok, why = autopublish.qualifies(report)
    if not ok:
        _note(item, f"Held for your review, not published automatically: {why}")
        return False
    project = db.get_project(clip.get("project_id") or "") or {}
    source = db.fetch("sources", project.get("source_id") or "") if project.get("source_id") else None
    try:
        rights.gate(source, "schedule", settings)
    except rights.RightsBlocked:
        return False
    day = local_day(settings, item["planned_at"])
    mine = [r for r in db.select("scheduled_publications", "platform = ? AND status IN ('approved', 'publishing', "
                                                           "'reconciling', 'published') AND planned_at IS NOT NULL",
                                 (item["platform"],))
            if (r.get("approval") or {}).get("by") == "automatic" and local_day(settings, r["planned_at"]) == day]
    if len(mine) >= int(cfg.get("daily_limit") or 0):
        _note(item, f"Held for your review: automatic publishing's limit of {cfg.get('daily_limit')} posts that day "
                    "is reached")
        return False
    updated = {**item, "privacy": "private",  # the only visibility the permission and the audience policy allow
               "options": {**(item.get("options") or {}), "made_for_kids": bool(cfg.get("made_for_kids"))}}
    try:
        stamp = check_platform(updated)
    except PublishError as exc:
        _note(item, f"Held for your review: {exc}")
        return False
    updated["audience"] = {**(item.get("audience") or {}), **stamp}
    when = autopublish.since(consent, settings)
    approval = approval_record(updated, at=now, by="automatic", consent_id=consent["id"])
    if not approval or approval["video_sha256"] != sha:  # the file changed while this was being decided
        _note(item, "Held for your review, not published automatically: the video file changed; it is checked again")
        return False
    db.update("scheduled_publications", item["id"], privacy=updated["privacy"], options=updated["options"],
              audience=updated["audience"], status="approved", approval=approval, last_error="", fix="",
              status_note=f"Approved automatically (automatic publishing, on since {when}). You can cancel it until it "
                          "goes out.",
              audit=_audit(item, "auto_approved", f"Approved automatically under the automatic-publishing permission "
                                                  f"you gave on {when} (not reviewed by you)", consent=consent["id"],
                           privacy=updated["privacy"]))
    state.event("auto_approved", f"{item['platform']}: “{item['title'][:60]}” approved automatically",
                ref_type="scheduled", ref_id=item["id"])
    if item.get("replaces"):
        _take_slot(item["id"], updated, now, "approved automatically")
    return True


def _take_slot(item_id: str, updated: dict, now: float, how: str) -> None:
    """An approved replacement takes the slot of the weaker post it was proposed for (if that one has not started)."""
    weak = db.fetch("scheduled_publications", updated["replaces"])
    if weak and weak["status"] in ("awaiting_approval", "approved") and weak["planned_at"] > now + 60 * LOCK_MINUTES:
        db.execute("UPDATE slot_replacements SET status = 'replaced', updated_at = ? WHERE replacement_id = ?",
                   (now, item_id))
        db.update("scheduled_publications", weak["id"], status="replaced", replaced_by=item_id,
                  status_note=f"Replaced by a stronger opportunity ({how})",
                  audit=_audit(weak, "replaced", f"Replaced by a stronger opportunity ({how})", by=item_id))
        state.event("replaced", f"“{weak['title'][:60]}” replaced by “{updated['title'][:60]}”",
                    ref_type="scheduled", ref_id=weak["id"], by=item_id)
    elif weak and weak["status"] in ACTIVE + DONE:
        db.update("scheduled_publications", item_id, replaces="", planned_at=None,
                  status_note="The post it would have replaced already started; a new time will be chosen")


def approve(item_id: str, fields: dict, creator: dict | None = None) -> dict:
    """The user's explicit approval of exactly this content, visibility and settings (validated first)."""
    item = db.fetch("scheduled_publications", item_id)
    if not item:
        raise ValueError("Scheduled post not found")
    if item["status"] not in ("awaiting_approval", "approved", "failed"):
        raise ValueError(f"This post is {item['status'].replace('_', ' ')}; it cannot be approved now")
    updated = {**item, **{k: v for k, v in fields.items() if k in ("title", "description", "tags", "privacy",
                                                                     "options")}}
    # approving is for the audience as it is now: the post keeps what it was meant for (only you, held as public),
    # and takes the current test group
    kept = (item.get("audience") or {}).get("intent")
    updated["audience"] = {"intent": kept} if kept else {}
    stamp = check_platform(updated, creator)
    updated["audience"] = {**(item.get("audience") or {}), **stamp}
    rep = gate.report_for(db.get_clip(item["clip_id"]) or {})
    if rep and rep["status"] != "passed":  # not checked yet is fine: the publisher waits for the check
        raise ValueError("The clip's file did not pass the final quality check (" + "; ".join(rep["blockers"][:2])
                         + "). Fix the clip and render it again before approving it.")
    now = _now()
    approval = approval_record(updated, at=now, by="you")
    if not approval:
        raise ValueError("The clip's video file is missing or cannot be read. Render the clip again before approving "
                         "it.")
    db.update("scheduled_publications", item_id, **{k: updated[k] for k in ("title", "description", "tags", "privacy",
                                                                             "options", "audience")},
              status="approved", approval=approval, last_error="", fix="",
              status_note="Approved: it will be published at its time" if item["planned_at"] > now else
              "Approved: publishing now",
              audit=_audit(item, "approved", "Approved by you", privacy=updated["privacy"]))
    if item.get("replaces"):
        _take_slot(item_id, updated, now, "you approved it")
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


def _awaiting_by_platform() -> dict[str, int]:
    with db.connect() as conn:
        rows = conn.execute("SELECT platform, COUNT(*) AS n FROM scheduled_publications WHERE status = "
                            "'awaiting_approval' GROUP BY platform").fetchall()
    return {r["platform"]: r["n"] for r in rows}


# ------------------------------------------------------------------ the tick
def lead_seconds(item: dict, settings: dict) -> float:
    """YouTube posts are uploaded a little early, as Private (no publishAt: nothing becomes public later)."""
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
            old = db.fetch("worker_jobs", f"publish:{item['id']}", "idem_key")
            if old and old["status"] == "canceled":
                # The post already has an upload record. Reconcile that same session after work resumes; this is
                # the narrowly scoped exception to cancellation, never permission to start a second upload.
                db.update("worker_jobs", old["id"], status="queued", cancel_requested=0, attempts=0, run_after=now,
                          lease_owner="", lease_until=0, finished_at=None, error="", fix="",
                          message="Checking what happened to the upload")
                queue.log_line(old["id"], old["worker"], "info", "reconcile", "Checking the existing upload")
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
            problem = approval_problem(item)
            if problem:
                db.update("scheduled_publications", item["id"], status="awaiting_approval", approval={},
                          status_note=f"Needs a new approval: {problem}",
                          audit=_audit(item, "approval_invalidated", problem[:1].upper() + problem[1:],
                                       approved_sha256=(item.get("approval") or {}).get("video_sha256", "")))
                continue
            if not autopublish.still_covers(item):
                db.update("scheduled_publications", item["id"], status="awaiting_approval", approval={},
                          status_note="Automatic publishing was turned off or changed: approve it yourself",
                          audit=_audit(item, "approval_invalidated", "The automatic-publishing permission that "
                                                                     "approved it is no longer in force"))
                continue
            if settings.get("autopilot_publishing_paused"):  # clips are still made; uploads wait for Resume
                _note(item, "Publishing is paused: it goes out after you resume publishing")
                continue
            if not settings.get("autopilot_auto_publish"):
                state.action(f"publish:{item['id']}", "publish", f"Publish “{item['title'][:60]}” now?",
                             "Automatic publishing is off, so approved posts wait for you at their time.",
                             "Posts → open the post → Publish now.", ref_type="scheduled", ref_id=item["id"])
                continue
            # The approved post decides, not an earlier upload job: one canceled before its upload started (the
            # post came back with a new time) runs again now. The publisher itself never uploads a video twice.
            queue.enqueue("publish", {"scheduled_id": item["id"]}, idem_key=f"publish:{item['id']}",
                          ref=("scheduled", item["id"]), max_attempts=5, timeout_s=3 * 3600, revive_canceled=True)
            db.update("scheduled_publications", item["id"], status="publishing", status_note="Queued for upload",
                      audit=_audit(item, "publish_queued", "Due: queued for upload"))
            started += 1
        elif item["planned_at"] > now and auto_approve(item, settings, now):
            continue
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
    pending = remind_approvals()
    return {"publishing": started, "missed": moved, "expired": retired, "overdue_unapproved": waiting,
            "awaiting_approval": pending, "reconciled": reconciled}


def remind_approvals() -> int:
    """The one "waiting for your OK" item on the Autopilot page, kept in step with the posts that wait for you."""
    by_platform = _awaiting_by_platform()
    # posts held back under automatic publishing are there for you to look at, not a problem that needs you
    need = {p: n for p, n in by_platform.items() if not autopublish.active(p)}
    if need:
        n = sum(need.values())
        only_tiktok = set(need) == {"tiktok"}
        state.action("approvals", "approve", f"{n} {'TikTok ' if only_tiktok else ''}post{'s' if n != 1 else ''} "
                                             "waiting for your OK",
                     ("TikTok's rules require your OK on each post. " if "tiktok" in need else "") +
                     ("Turn on automatic publishing for YouTube to skip this there. " if "youtube" in need else "") +
                     "Approved posts go out at their time automatically.", "Open Posts, review and approve.")
    else:
        state.resolve("approvals")
    return sum(by_platform.values())


@handler("schedule_tick")
def schedule_tick(job: Job) -> dict:
    settings = db.get_settings()
    now = _now()
    audience_reminders(settings)
    due = process_due(settings, now)
    planned = plan_new(settings, now) if settings.get("autopilot_auto_schedule") else {"created": 0}
    if planned.get("created"):
        due["awaiting_approval"] = remind_approvals()  # new posts that need your OK are listed right away
    return {**due, **planned, "message": f"{planned.get('created', 0)} scheduled, {planned.get('replaced', 0)} "
                                         f"replaced, {due['publishing']} publishing"}

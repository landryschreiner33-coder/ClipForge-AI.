"""Rights and content safety gate. Discovery is not authorization.

Every source gets exactly one rights status. Review mode may discover, clip and schedule accessible videos locally
without recorded reuse coverage. Uploading requires current recorded coverage or an exact per-post owner assertion:

* OWNED                          your own content (your connected YouTube channel, folders you marked as yours)
* LICENSED                       you have a license (you record the basis, e.g. the agreement)
* CREATIVE_COMMONS               the platform or library reports CC BY (the credit line is added)
* PUBLIC_DOMAIN                  the library reports public domain or CC0
* ALLOWLISTED                    the creator allows it (an agreement you recorded, or a clipping program you joined)
* MANUAL_CONFIRMATION_REQUIRED   nothing covers it ("Not covered"): needs owner review before uploading
* BLOCKED                        never used

Being public, trending or downloadable says nothing about whether a video may be reused, so the default for anything
unknown is MANUAL_CONFIRMATION_REQUIRED. Review mode and explicit public-local discovery may select it for local
clipping; neither supplies a publishing grant. With review mode off, automatic scheduling requires recorded reuse
coverage. Explicit blocks always prevent local processing. Owner assertions are stored separately and never
fabricate an ownership or license status for the source.

A channel named by a feed or list is only a claim. Channel rules (agreements, allowlisted creators) and ownership by
your connected channel apply only when the platform itself confirmed that this exact video, and the link to it,
belongs to that channel (verify.py); otherwise the video is skipped with the reason. A confirmed channel still needs
a rule: confirmation alone never makes a video usable. A block matches the claim whether or not it is confirmed.

Coverage keeps its conditions (a rule's `conditions`, a license's terms): the credit line, whether commercial use is
allowed, the platforms it covers, and whether it covers other people's material inside the video. An agreement with a
creator covers the creator's own material only: a video whose title suggests someone else's music or footage (a
music video, a reaction, broadcast sports footage, a trailer) is not used under it, and the final check rejects clips
with long stretches of sound without speech (gate.py). No status is ever derived from an AI judgement of fair use;
every automatic status comes from your own records or from a license the provider reports.

Getting the file is a separate question (access.py): a license or an agreement does not make a platform's video
downloadable.
"""
from __future__ import annotations

import os
import re
import time
from urllib.parse import urlparse

from .. import db
from . import state, verify

OWNED, LICENSED, CC, PD, ALLOWLISTED, MANUAL, BLOCKED = (
    "OWNED", "LICENSED", "CREATIVE_COMMONS", "PUBLIC_DOMAIN", "ALLOWLISTED", "MANUAL_CONFIRMATION_REQUIRED", "BLOCKED")
STATUSES = [OWNED, LICENSED, CC, PD, ALLOWLISTED, MANUAL, BLOCKED]
LABELS = {OWNED: "Owned", LICENSED: "Licensed", CC: "Creative Commons", PD: "Public domain",
          ALLOWLISTED: "Allowlisted", MANUAL: "Not covered", BLOCKED: "Blocked"}
EXPLAIN = {
    OWNED: "Your own content.",
    LICENSED: "You recorded a license that covers this content.",
    CC: "A Creative Commons Attribution (CC BY) license, as the platform or library reports it; the credit line is "
        "added to the description.",
    PD: "Public domain (or CC0), as the library reports it.",
    ALLOWLISTED: "The creator allows reuse (an agreement you recorded, or a clipping program you joined).",
    MANUAL: "No recorded reuse coverage. Review the source and confirm your basis before publishing, or record "
            "an agreement with the creator.",
    BLOCKED: "Blocked: never clipped or published.",
}
SCOPES = ("source", "channel", "folder", "url_prefix")
PLATFORM_HOSTS = ("youtube.com", "youtu.be", "tiktok.com", "twitch.tv", "instagram.com", "facebook.com", "x.com",
                  "twitter.com", "kick.com", "vimeo.com", "dailymotion.com", "rumble.com")


class RightsBlocked(Exception):
    def __init__(self, message: str, status: str):
        super().__init__(message)
        self.status = status


def auto_allowed(status: str, settings: dict) -> bool:
    return {OWNED: True, LICENSED: bool(settings.get("rights_auto_licensed", True)),
            ALLOWLISTED: bool(settings.get("rights_auto_allowlisted", True)),
            CC: bool(settings.get("rights_auto_creative_commons", True)),
            PD: bool(settings.get("rights_auto_public_domain", True))}.get(status, False)


def review_before_publish(settings: dict | None = None) -> bool:
    """Review mode prepares local posts; it never grants permission to upload them."""
    settings = settings if settings is not None else db.get_settings()
    return bool(settings.get("autopilot_review_before_publish", True))


def _stopped(source: dict | None) -> bool:
    intake = (source or {}).get("intake") or {}
    return bool((source or {}).get("status") in ("canceled", "removed") or
                intake.get("canceled") or intake.get("removed"))


def local_allowed(source: dict, evaluation: dict | None = None, settings: dict | None = None) -> bool:
    """A submitted video or an enabled public discovery pick may be clipped without a publishing grant.

    This never changes its reuse status. Review-mode scheduling is local; publishing needs a separate grant.
    Explicit blocks remain binding, and access.resolve separately decides whether media can be obtained.
    """
    intake = source.get("intake") or {}
    if intake.get("canceled") or intake.get("removed") or source.get("status") in ("canceled", "removed"):
        return False
    settings = settings if settings is not None else db.get_settings()
    r = evaluation if evaluation is not None else evaluate(source, settings)
    public_pick = bool((settings.get("autopilot_public_videos") or review_before_publish(settings)) and
                       source.get("signal_id") and
                       not source.get("local_path") and
                       str(source.get("url") or "").startswith(("http://", "https://")))
    return bool(r["auto_allowed"] or ((source.get("user_added") or public_pick) and r["status"] != BLOCKED))


def discovery_publishable(source: dict, settings: dict, all_rules: list[dict] | None = None,
                          platforms: set[str] | None = None) -> bool:
    """Admit review candidates, or require recorded coverage when automatic publishing is selected.

    This is a local admission check, not a publishing grant: file access, final checks, connected-account
    readiness and posting consent are checked separately. Explicit local imports keep their existing behavior.
    """
    if _stopped(source):
        return False
    evaluation = evaluate(source, settings, all_rules)
    if evaluation["status"] == BLOCKED or (not evaluation["auto_allowed"] and not review_before_publish(settings)):
        return False
    if platforms is None:
        connected = {p for p in ("youtube", "tiktok") if (db.get_account(p) or {}).get("has_tokens")}
        platforms = {p for p in (connected or {"youtube", "tiktok"}) if settings.get(f"autopilot_{p}")}
    allowed = set((evaluation.get("conditions") or {}).get("platforms") or [])
    return bool(platforms and (review_before_publish(settings) or not allowed or platforms & allowed))


# What a title says about material that is not the creator's own (music, broadcasts, films). A heuristic: it can
# miss things, so an agreement also never covers clips with long stretches of sound without speech (gate.py).
THIRD_PARTY = [
    (re.compile(r"\b(official (music )?video|official audio|music video|lyric video|lyrics|full album|remix|"
                r"\(audio\))\b"), "a music recording"),
    (re.compile(r"\b(reacts? to|reacting to|reaction to|reaction video)\b"), "a reaction to someone else's video"),
    (re.compile(r"\b(full (match|game|fight|race)|(match|game|fight|race|extended) highlights)\b"),
     "broadcast sports footage"),
    (re.compile(r"\b(official trailer|trailer|full movie|movie clip|full episode)\b"), "film or TV footage"),
    (re.compile(r"\bcompilation\b"), "a compilation of other clips"),
]


def third_party_risk(source: dict) -> str:
    """Why the video probably contains other people's material ("" if nothing suggests it)."""
    if (source.get("category") or "") == "Music":
        return "a music video (YouTube category Music)"
    title = (source.get("title") or "").lower()
    for pattern, what in THIRD_PARTY:
        if pattern.search(title):
            return f"the title suggests {what}"
    return ""


def license_status(source: dict) -> tuple[str, str, dict] | None:
    """What the license a platform or library reports means here: (status, basis, conditions), or None when no
    license is reported. Only licenses that allow editing and commercial reuse are used automatically."""
    lic = (source.get("license") or "").strip().lower()
    if not lic or lic == "youtube":  # the Standard YouTube License grants no reuse
        return None
    info = source.get("rights_info") or {}
    name = info.get("license_name") or lic
    where = "YouTube" if source.get("platform") == "youtube" else (info.get("reported_by") or "The provider")
    conds = {"kind": "license", "commercial": True, "third_party": False}
    if lic in ("creativecommon", "creative_commons", "cc-by"):  # YouTube offers one CC license: CC BY 3.0
        return CC, f"{where} reports a Creative Commons Attribution (CC BY) license", conds
    if info.get("restrictions"):
        return MANUAL, f"{name}, with other restrictions ({info['restrictions'][:120]}): not used automatically", {}
    if lic in ("pd", "cc0", "cc-zero", "public domain") or lic.startswith("pd-") or "public domain" in name.lower():
        shown = name if name != lic else {"cc0": "CC0 (a public domain dedication)"}.get(lic, "public domain")
        return PD, f"{where} reports {shown}", conds
    mt = re.fullmatch(r"cc-by(-[a-z-]+)?-(\d(?:\.\d)?)(?:-[a-z]+)?", lic)
    if mt and not mt.group(1):
        return CC, f"{where} reports {name}", conds
    if lic.startswith("cc-by"):
        why = [w for k, w in (("sa", "share-alike"), ("nc", "non-commercial"), ("nd", "no derivatives"))
               if f"-{k}" in lic]
        return MANUAL, f"{name} ({', '.join(why) or 'terms not recognized'}): not used automatically", {}
    return MANUAL, f"License “{name}” is not one Autopilot uses automatically", {}


# ------------------------------------------------------------------ rules
def rules(active_only: bool = True) -> list[dict]:
    return db.select("source_rights", "active = 1" if active_only else "", (), "created_at DESC")


def add_rule(scope: str, value: str, status: str, basis: str = "", platform: str = "", label: str = "",
             evidence_url: str = "", expires_at: float | None = None, created_by: str = "user",
             conditions: dict | None = None, evidence: str = "") -> dict:
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope}")
    if status not in (OWNED, LICENSED, CC, ALLOWLISTED, BLOCKED):
        raise ValueError("A rule sets Owned, Licensed, Creative Commons, Allowlisted or Blocked")
    value = value.strip()
    if scope == "folder":
        value = normalize_path(value)
    if not value:
        raise ValueError("A rule needs a value (a channel ID, folder, URL prefix or source)")
    if status in (LICENSED, ALLOWLISTED) and not basis.strip():
        raise ValueError("Say what the license or permission is (for example the agreement or program)")
    rule = db.insert("source_rights", {"scope": scope, "platform": platform, "value": value, "label": label[:200],
                                       "status": status, "basis": basis[:1000], "evidence_url": evidence_url[:500],
                                       "created_by": created_by, "expires_at": expires_at,
                                       "conditions": conditions or {}, "evidence": evidence[:2000]})
    state.event("rights_rule", f"{LABELS[status]} rule added for {scope} {label or value}", ref_type="rule",
                ref_id=rule["id"], basis=basis)
    return rule


def remove_rule(rule_id: str) -> None:
    db.update("source_rights", rule_id, active=0)
    state.event("rights_rule", "Rights rule removed", ref_type="rule", ref_id=rule_id)


def normalize_path(p: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(p))) if p else ""


def _under(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([normalize_path(path), folder]) == folder
    except ValueError:  # different drives on Windows
        return False


def _matches(rule: dict, source: dict) -> bool:
    if rule.get("expires_at") and rule["expires_at"] < time.time():
        return False
    v = rule["value"]
    if rule["scope"] == "source":
        return v in (source.get("id"), f"{source.get('platform')}:{source.get('external_id')}")
    if rule["scope"] == "channel":
        return bool(source.get("channel_id")) and v == source["channel_id"] and \
            rule.get("platform", "") in ("", source.get("platform"))
    if rule["scope"] == "folder":
        return bool(source.get("local_path")) and _under(source["local_path"], v)
    if rule["scope"] == "url_prefix":
        return bool(source.get("url")) and source["url"].lower().startswith(v.lower())
    return False


# ------------------------------------------------------------------ evaluation
def evaluate(source: dict, settings: dict | None = None, all_rules: list[dict] | None = None) -> dict:
    """The rights status of a source and why."""
    settings = settings if settings is not None else db.get_settings()
    all_rules = rules() if all_rules is None else all_rules
    matching = [r for r in all_rules if _matches(r, source)]

    def out(status: str, basis: str, rule_id: str = "", conditions: dict | None = None) -> dict:
        return {"status": status, "label": LABELS[status], "basis": basis, "rule_id": rule_id,
                "auto_allowed": auto_allowed(status, settings), "explain": EXPLAIN[status],
                "conditions": conditions or {}}

    def covered(status: str, basis: str, rule_id: str, conds: dict) -> dict:
        """Coverage by an agreement, a rule or a license, with its conditions checked against this video."""
        if status in (LICENSED, ALLOWLISTED, CC, PD):
            if conds.get("commercial") is False and settings.get("autopilot_commercial_use", True):
                return out(MANUAL, f"{basis}: commercial use is not allowed, and your posts count as commercial "
                                   "(Settings → Advanced → Discovery and rights)", rule_id, conds)
            risk = "" if conds.get("third_party") else third_party_risk(source)
            if risk:
                return out(MANUAL, f"Not used: {risk}, and {basis[:1].lower() + basis[1:]} covers only the "
                                   "creator's own material", rule_id, conds)
        return out(status, basis, rule_id, conds)

    blocked = next((r for r in matching if r["status"] == BLOCKED), None)
    if blocked:
        return out(BLOCKED, blocked["basis"] or f"Blocked by a {blocked['scope']} rule", blocked["id"])
    by_scope = {scope: next((r for r in matching if r["scope"] == scope), None) for scope in SCOPES}
    if by_scope["source"]:  # a decision about this very source wins (you judged this very video)
        r = by_scope["source"]
        return out(r["status"], r["basis"] or f"{LABELS[r['status']]} (your decision for this source)", r["id"],
                   r.get("conditions") or {})
    confirmed = verify.confirmed(source)  # the platform confirmed the channel this source names (never a network call)
    claim_only = False  # an unconfirmed channel claim is what would have covered it
    own = (db.get_account("youtube") or {}).get("account_id")
    if source.get("platform") == "youtube" and own and source.get("channel_id") == own:
        if confirmed:
            return out(OWNED, "Uploaded by your connected YouTube channel")
        claim_only = True
    for scope in ("channel", "folder", "url_prefix"):
        r = by_scope[scope]
        # a channel rule, or a link rule on a platform's own site (its links name the account), needs the confirmed
        # channel of this exact video
        if r and not confirmed and (scope == "channel" or (scope == "url_prefix" and is_platform_url(r["value"]))):
            claim_only = True
            continue
        if r:
            return covered(r["status"], r["basis"] or f"{LABELS[r['status']]} ({scope} rule)", r["id"],
                           r.get("conditions") or {})
    lic = license_status(source)
    if lic:
        return covered(*lic[:2], "", lic[2]) if lic[0] != MANUAL else out(MANUAL, lic[1])
    if claim_only:
        why = verify.why_not(source)
        return out(MANUAL, f"channel not confirmed. {why[:1].upper()}{why[1:]}")
    return out(MANUAL, "No agreement, license or ownership covers this video")


def apply(source: dict, settings: dict | None = None, all_rules: list[dict] | None = None) -> dict:
    """Evaluate and store the rights of a source; update its status and the user's action items."""
    settings = settings if settings is not None else db.get_settings()
    r = evaluate(source, settings, all_rules)
    fields: dict = {"rights_status": r["status"], "rights_basis": r["basis"], "rights_rule_id": r["rule_id"],
                    "rights_checked_at": time.time()}
    status = source.get("status") or "discovered"
    if r["status"] == BLOCKED and status not in ("analyzed", "weak", "exhausted"):
        fields["status"] = "blocked"
    elif local_allowed(source, r, settings) and status in ("discovered", "needs_rights", "blocked"):
        fields["status"] = "eligible"
    elif not local_allowed(source, r, settings) and status in ("discovered", "eligible", "blocked", "needs_file",
                                                             "queued"):
        fields["status"] = "needs_rights"  # a video waiting for its file or its turn that is no longer covered
    if r["status"] != source.get("rights_status"):
        state.event("rights_status", f"{source.get('title', '')[:80]}: {r['label']} ({r['basis']})",
                    ref_type="source", ref_id=source["id"], status=r["status"])
    if r["auto_allowed"] or r["status"] == BLOCKED:
        state.resolve(f"rights:{source['id']}")
    db.update("sources", source["id"], **fields)
    return {**source, **fields, "rights": r}


def recheck(source: dict, settings: dict | None = None) -> dict:
    """Right before work starts on a source: ask the platform about its channel if that never happened (a video
    queued before channels were confirmed, or one the platform could not be asked about), then evaluate and store
    its rights again. Returns the evaluation; the stored status says why when it may not be used."""
    settings = settings if settings is not None else db.get_settings()
    verify.ensure([source], settings)
    return apply(db.fetch("sources", source["id"]) or source, settings)["rights"]


def confirm(source_id: str, status: str, basis: str) -> dict:
    """The user's decision for one source (recorded as a source rule, with its basis)."""
    source = db.fetch("sources", source_id)
    if not source:
        raise ValueError("Source not found")
    for old in db.select("source_rights", "scope = 'source' AND value = ? AND active = 1", (source_id,)):
        db.update("source_rights", old["id"], active=0)
    add_rule("source", source_id, status, basis, platform=source["platform"], label=source.get("title", "")[:200])
    return apply(db.fetch("sources", source_id) or source)


ASK_AGAIN_AFTER = 7 * 86400  # a rights question you dismissed stays quiet this long


def request_confirmation(source: dict) -> None:
    """Only when you turned on "Ask me about strong videos nothing covers" (Advanced); by default such videos are
    skipped and listed in the activity log."""
    state.action(f"rights:{source['id']}", "rights", f"Confirm the rights for “{source.get('title', '')[:80]}”",
                 f"{source.get('channel_title') or source.get('platform')} · {EXPLAIN[MANUAL]}",
                 "Answer on the Autopilot page (Yes, I have permission / No), or set its rights under "
                 "Autopilot → Permissions & sources.",
                 level="action", ref_type="source", ref_id=source["id"], snooze_s=ASK_AGAIN_AFTER)


def platform_allowed(source: dict | None, platform: str, settings: dict | None = None, *,
                     stage: str = "publish") -> tuple[bool, str]:
    """Does the coverage allow posting on this platform? (an agreement may be limited to some platforms)"""
    if stage == "schedule":
        return scheduling_allowed(source, platform, settings)
    if source is None:
        return True, ""
    r = evaluate(source, settings)
    allowed = [p for p in (r.get("conditions") or {}).get("platforms") or [] if p]
    if allowed and platform not in allowed:
        return False, f"{r['basis']}: allowed only on {', '.join(a.title() for a in allowed)}"
    return True, ""


def scheduling_allowed(source: dict | None, platform: str, settings: dict | None = None) -> tuple[bool, str]:
    """Uncovered sources can enter local review without becoming owned, licensed or approved to upload."""
    settings = settings if settings is not None else db.get_settings()
    try:
        gate(source, "schedule", settings)
    except RightsBlocked as exc:
        return False, str(exc)
    if review_before_publish(settings):
        return True, ""
    return platform_allowed(source, platform, settings)


# ------------------------------------------------------------------ creator agreements
CHANNEL_ID = re.compile(r"UC[\w-]{10,40}|@[\w.\-]{2,40}")


def add_agreement(creator: str, channels: list[str], evidence: str, evidence_url: str = "", *,
                  attribution: str = "", commercial: bool = True, platforms: list[str] | None = None,
                  third_party: bool = False, expires_at: float | None = None, media_folder: str = "",
                  media_url_prefix: str = "") -> list[dict]:
    """Record an agreement you have with a creator: what shows it (evidence), what it covers (their YouTube channel
    IDs and TikTok handles, the folder or link where they share their files) and its conditions. Every video it
    covers is then used without asking again. Nothing here is inferred: without evidence it is refused."""
    creator = creator.strip()
    if not creator:
        raise ValueError("Name the creator")
    if not (evidence.strip() or evidence_url.strip()):
        raise ValueError("Add what shows the agreement: a link to it, or where and when the creator agreed")
    channels = [c.strip() for c in channels if c.strip()]
    bad = [c for c in channels if not CHANNEL_ID.fullmatch(c)]
    if bad:
        raise ValueError(f"Not a YouTube channel ID (UC...) or TikTok handle (@name): {', '.join(bad)}")
    if not (channels or media_folder.strip() or media_url_prefix.strip()):
        raise ValueError("Say what it covers: a channel ID, a TikTok handle, or the folder or link with their files")
    if media_url_prefix.strip() and not media_url_prefix.strip().lower().startswith(("https://", "http://")):
        raise ValueError("The file link must start with https://")
    platforms = [p for p in (platforms or []) if p in ("youtube", "tiktok")]
    conditions = {"kind": "agreement", "agreement_id": db.new_id(), "creator": creator[:120],
                  "attribution": attribution.strip()[:200], "commercial": bool(commercial), "platforms": platforms,
                  "third_party": bool(third_party), "media_folder": normalize_path(media_folder.strip()),
                  "media_url_prefix": media_url_prefix.strip()}
    basis = f"Agreement with {creator[:80]}: " + (evidence.strip()[:300] or evidence_url.strip())
    common = {"status": ALLOWLISTED, "basis": basis, "label": creator[:200], "evidence_url": evidence_url.strip(),
              "expires_at": expires_at, "conditions": conditions, "evidence": evidence.strip()}
    rules = [add_rule("channel", c, platform="tiktok" if c.startswith("@") else "youtube", **common) for c in channels]
    if media_folder.strip():
        rules.append(add_rule("folder", media_folder.strip(), **common))
    if media_url_prefix.strip():
        rules.append(add_rule("url_prefix", media_url_prefix.strip(), **common))
    state.event("agreement", f"Agreement with {creator[:80]} recorded ({len(rules)} rule(s))",
                agreement=conditions["agreement_id"])
    return rules


def agreements() -> list[dict]:
    """Your agreements, each with the rules it made."""
    out: dict[str, dict] = {}
    for r in rules():
        c = r.get("conditions") or {}
        if c.get("kind") != "agreement":
            continue
        a = out.setdefault(c["agreement_id"], {"id": c["agreement_id"], "creator": c.get("creator", ""),
                                               "evidence": r.get("evidence", ""), "evidence_url": r["evidence_url"],
                                               "expires_at": r.get("expires_at"), "created_at": r["created_at"],
                                               "conditions": c, "channels": [], "rules": []})
        a["rules"].append(r["id"])
        if r["scope"] == "channel":
            a["channels"].append(r["value"])
    return sorted(out.values(), key=lambda a: -a["created_at"])


def remove_agreement(agreement_id: str) -> int:
    n = 0
    for r in rules():
        if (r.get("conditions") or {}).get("agreement_id") == agreement_id:
            db.update("source_rights", r["id"], active=0)
            n += 1
    if n:
        state.event("agreement", "Agreement removed", agreement=agreement_id)
    return n


def gate(source: dict | None, stage: str, settings: dict | None = None) -> dict:
    """Raise RightsBlocked unless the source may be used automatically at this stage (ingest, schedule, publish).
    Re-evaluates the rules each time, so a rule added later (e.g. Blocked) takes effect immediately."""
    if source is None:
        return {"status": OWNED, "auto_allowed": True, "basis": "Manual project"}
    if source.get("id"):
        source = db.fetch("sources", source["id"]) or source
    intake = source.get("intake") or {}
    if source.get("status") in ("canceled", "removed") or intake.get("canceled") or intake.get("removed"):
        raise RightsBlocked("Canceled by you: no further automatic posts will be made from this video.", BLOCKED)
    settings = settings if settings is not None else db.get_settings()
    r = evaluate(source, settings)
    if not r["auto_allowed"] and not (stage == "schedule" and review_before_publish(settings) and
                                      r["status"] != BLOCKED):
        raise RightsBlocked(f"{r['label']}: not used automatically at the {stage} stage. {r['explain']}", r["status"])
    return r


def _post_source(item: dict) -> tuple[dict, dict | None]:
    clip = db.get_clip(item.get("clip_id") or "") or {}
    project = db.get_project(clip.get("project_id") or "") or {}
    source_id = project.get("source_id") or item.get("source_id") or ""
    source = db.fetch("sources", source_id) if source_id else None
    if source_id and not source:
        raise ValueError("This clip's source record is missing")
    return clip, source


def _confirmation_record(item: dict) -> dict:
    record = item.get("reuse_confirmation") or (item.get("options") or {}).get("reuse_confirmation") or {}
    return record if isinstance(record, dict) else {}


def _confirmation_binding(item: dict, settings: dict, sha: str | None = None) -> dict:
    """The same canonical payload in a local schedule and its eventual upload snapshot."""
    from ..pipeline import artifact

    clip, source = _post_source(item)
    if not clip:
        raise ValueError("The clip is missing")
    path, version, _ = artifact.active(clip)
    if clip.get("active_version") and version != clip["active_version"]:
        raise ValueError("The selected clip version is missing or not rendered")
    if not path:
        raise ValueError("The rendered clip file is missing")
    if sha is None:
        sha = artifact.sha256_file(path)
    if not sha:
        raise ValueError("The rendered clip file cannot be read")
    options = {k: v for k, v in (item.get("options") or {}).items() if k not in
               ("approved_account", "approved_video_sha256", "reuse_confirmation", "duration")}
    options["mode"] = options.get("mode") or item.get("mode") or "direct"
    audience_stamp = item.get("audience") or {}
    payload = {"title": item.get("title") or "", "description": item.get("description") or "",
               "tags": item.get("tags") or [], "privacy": item.get("privacy") or item.get("requested_privacy") or "",
               "options": options, "audience": {k: audience_stamp.get(k) for k in
                                                ("intent", "policy_version", "group", "group_version")}}
    evaluation = evaluate(source, settings) if source else None
    identity = {k: (source or {}).get(k) for k in
                ("id", "platform", "url", "local_path", "channel_id", "external_id", "video_id")}
    return {"scheduled_id": item.get("scheduled_id") or item.get("id") or "",
            "source_id": (source or {}).get("id") or "", "source_identity": artifact.sha256_json(identity),
            "clip_id": clip["id"], "project_id": clip["project_id"], "platform": item.get("platform") or "",
            "account_id": (db.get_account(item.get("platform") or "") or {}).get("account_id") or "",
            "version_id": version, "video_sha256": sha, "payload_sha256": artifact.sha256_json(payload),
            "terms_sha256": artifact.sha256_json({"evaluation": evaluation,
                                                   "attribution": current_attribution(source, settings)})}


def make_reuse_confirmation(item: dict, basis: str, settings: dict | None = None) -> dict:
    """Record the owner's per-post assertion separately from any verified source ownership or license."""
    settings = settings if settings is not None else db.get_settings()
    basis = str(basis).strip()
    if not basis or len(basis) > 4000:
        raise ValueError("Explain your reuse permission for this post (up to 4,000 characters)")
    _clip, source = _post_source(item)
    if _stopped(source) or (source and evaluate(source, settings)["status"] == BLOCKED):
        raise ValueError("This source is blocked or canceled; it cannot be approved for publication")
    return {"policy_version": 1, "owner_confirmed": True, "basis": basis, "confirmed_at": time.time(),
            "binding": _confirmation_binding(item, settings)}


def confirmation_problem(item: dict, settings: dict | None = None, sha: str | None = None) -> str:
    """An assertion is usable only for these exact current bytes, source, account, text and destination."""
    settings = settings if settings is not None else db.get_settings()
    record = _confirmation_record(item)
    if record.get("policy_version") != 1 or record.get("owner_confirmed") is not True or not str(
            record.get("basis") or "").strip():
        return "Review the source and confirm your reuse permission for this post"
    try:
        clip, source = _post_source(item)
        if not clip or _stopped(source) or (source and evaluate(source, settings)["status"] == BLOCKED):
            return "The source is missing, blocked or canceled"
        binding = _confirmation_binding(item, settings, sha)
    except (OSError, ValueError):
        return "The source or rendered clip file is missing or cannot be read"
    if record.get("binding") != binding:
        return "The source, reuse terms, account, video or post changed after your reuse review"
    return ""


def publication_allowed(source: dict | None, platform: str, settings: dict | None = None,
                        publication: dict | None = None) -> tuple[bool, str]:
    """Local review admission is never a grant: uploads need current coverage or an exact owner assertion."""
    settings = settings if settings is not None else db.get_settings()
    if publication is not None:
        if publication.get("platform") != platform:
            return False, "The post's platform does not match this publication request"
        try:
            _clip, source = _post_source(publication)
        except ValueError as exc:
            return False, str(exc)
    if source and source.get("id"):
        source = db.fetch("sources", source["id"]) or source
    if _stopped(source) or (source and evaluate(source, settings)["status"] == BLOCKED):
        return False, "This source is blocked or canceled; no further publication is allowed"
    try:
        gate(source, "publish", settings)
        allowed, why = platform_allowed(source, platform, settings)
        if allowed:
            return True, ""
    except RightsBlocked as exc:
        why = str(exc)
    if publication is not None and _confirmation_record(publication):
        problem = confirmation_problem(publication, settings)
        if not problem:
            return True, ""
        return False, problem
    return False, why


def review_info(item: dict, settings: dict | None = None) -> dict:
    """Show recorded coverage and an owner assertion as distinct evidence, including source-sound uncertainty."""
    settings = settings if settings is not None else db.get_settings()
    try:
        clip, source = _post_source(item)
    except ValueError as exc:
        return {"required": True, "confirmed": False, "basis": "", "explanation": str(exc), "status": MANUAL}
    evaluation = evaluate(source, settings) if source else {"status": OWNED, "auto_allowed": True,
                                                           "basis": "Manual project"}
    allowed, why = publication_allowed(source, item.get("platform") or "", settings)
    sound_review = False
    if clip:
        from . import gate as final_gate

        sound = final_gate.sound_rights_check(clip, settings)
        sound_review = bool(sound and (sound.get("values") or {}).get("owner_confirmation_required"))
    required = not allowed or sound_review
    record = _confirmation_record(item)
    confirmed = bool(record and not confirmation_problem(item, settings))
    explanation = ("Your reuse confirmation covers this exact post; it does not mark the source as owned or licensed."
                   if confirmed else ("Review any music or other material inside this clip before confirming reuse."
                                      if sound_review else why or evaluation.get("basis") or "Recorded reuse coverage"))
    return {"required": required, "confirmed": confirmed, "basis": str(record.get("basis") or ""),
            "explanation": explanation, "status": evaluation["status"]}


# ------------------------------------------------------------------ acquisition policy (see access.py)
def is_platform_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in PLATFORM_HOSTS)


def download_allowed(source: dict, settings: dict) -> tuple[bool, str]:
    """May the media be fetched automatically? (access.resolve, kept for older callers)"""
    from . import access

    a = access.resolve(source, settings)
    return a["ok"], a["detail"]


def url_typed_by_user(source: dict) -> bool:
    """Was this source's URL typed by you (added by hand, or a stream you configured)? Only then may it point into
    your own network; URLs that came from a feed's rows or from discovery must be public (netguard.py)."""
    if source.get("user_added"):
        return False  # public-link intake stays public on every redirect, including later pipeline steps
    if not source.get("signal_id"):
        return True
    signal = db.fetch("trend_signals", source["signal_id"]) or {}
    return signal.get("provider") == "stream_url"


def attribution(source: dict) -> str:
    """The credit line the coverage asks for: a CC license's attribution, a library's credit, or the credit line of
    your agreement with the creator (added to the description and caption, and allowed by the text check)."""
    status = source.get("rights_status")
    info = source.get("rights_info") or {}
    title = source.get("title", "")
    if info.get("provider") == "commons" and (status == CC or (status == PD and info.get("attribution_required"))):
        who = info.get("artist") or "its author"
        lic = f", {info['license_name']}" if info.get("license_name") and status == CC else ""
        page = info.get("page_url") or source.get("url", "")
        return f"Source: “{title}” by {who}{lic}, via Wikimedia Commons ({page})."
    if status == CC:
        who = source.get("channel_title") or "the original creator"
        return f"Source: “{title}” by {who} ({source.get('url', '')}), licensed under CC BY."
    if status in (LICENSED, ALLOWLISTED) and source.get("rights_rule_id"):
        rule = db.fetch("source_rights", source["rights_rule_id"]) or {}
        return str((rule.get("conditions") or {}).get("attribution") or "")
    return ""


def current_attribution(source: dict | None, settings: dict | None = None) -> str:
    """Use current recorded terms even before a background rights refresh updates the source's cached label."""
    if not source:
        return ""
    evaluation = evaluate(source, settings)
    # An owner assertion supplies a separate posting basis; it never silently waives an existing credit term.
    recorded_credit = str((evaluation.get("conditions") or {}).get("attribution") or "").strip()
    if recorded_credit:
        return recorded_credit
    return attribution({**source, "rights_status": evaluation["status"], "rights_rule_id": evaluation["rule_id"]})

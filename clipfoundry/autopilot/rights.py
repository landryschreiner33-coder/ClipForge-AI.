"""Rights and content safety gate. Discovery is not authorization.

Every source gets exactly one rights status. Discovery stays broad (any trending topic, creator or stream), but a
source is only clipped, scheduled or published automatically when its status passes the policy in Settings:

* OWNED                          your own content (your connected YouTube channel, folders you marked as yours)
* LICENSED                       you have a license (you record the basis, e.g. the agreement)
* CREATIVE_COMMONS               the platform reports a Creative Commons license (attribution is added)
* ALLOWLISTED                    the creator allows it (e.g. an official clipping program you joined)
* MANUAL_CONFIRMATION_REQUIRED   nothing known: waits for you, never used automatically
* BLOCKED                        never used

Being public, trending or downloadable says nothing about whether a video may be reused, so the default for anything
unknown is MANUAL_CONFIRMATION_REQUIRED.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import urlparse

from .. import db
from . import state

OWNED, LICENSED, CC, ALLOWLISTED, MANUAL, BLOCKED = (
    "OWNED", "LICENSED", "CREATIVE_COMMONS", "ALLOWLISTED", "MANUAL_CONFIRMATION_REQUIRED", "BLOCKED")
STATUSES = [OWNED, LICENSED, CC, ALLOWLISTED, MANUAL, BLOCKED]
LABELS = {OWNED: "Owned", LICENSED: "Licensed", CC: "Creative Commons", ALLOWLISTED: "Allowlisted",
          MANUAL: "Needs your confirmation", BLOCKED: "Blocked"}
EXPLAIN = {
    OWNED: "Your own content.",
    LICENSED: "You recorded a license that covers this content.",
    CC: "The platform reports a Creative Commons license; the source is credited in the description.",
    ALLOWLISTED: "The creator allows reuse (for example through a clipping program you joined).",
    MANUAL: "Nothing shows that you may reuse this content. Confirm the rights, or it will not be used.",
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
            CC: bool(settings.get("rights_auto_creative_commons", False))}.get(status, False)


# ------------------------------------------------------------------ rules
def rules(active_only: bool = True) -> list[dict]:
    return db.select("source_rights", "active = 1" if active_only else "", (), "created_at DESC")


def add_rule(scope: str, value: str, status: str, basis: str = "", platform: str = "", label: str = "",
             evidence_url: str = "", expires_at: float | None = None, created_by: str = "user") -> dict:
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
                                       "created_by": created_by, "expires_at": expires_at})
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

    def out(status: str, basis: str, rule_id: str = "") -> dict:
        return {"status": status, "label": LABELS[status], "basis": basis, "rule_id": rule_id,
                "auto_allowed": auto_allowed(status, settings), "explain": EXPLAIN[status]}

    blocked = next((r for r in matching if r["status"] == BLOCKED), None)
    if blocked:
        return out(BLOCKED, blocked["basis"] or f"Blocked by a {blocked['scope']} rule", blocked["id"])
    by_scope = {scope: next((r for r in matching if r["scope"] == scope), None) for scope in SCOPES}
    if by_scope["source"]:  # a decision about this very source wins
        r = by_scope["source"]
        return out(r["status"], r["basis"] or f"{LABELS[r['status']]} (your decision for this source)", r["id"])
    own = (db.get_account("youtube") or {}).get("account_id")
    if source.get("platform") == "youtube" and own and source.get("channel_id") == own:
        return out(OWNED, "Uploaded by your connected YouTube channel")
    for scope in ("channel", "folder", "url_prefix"):
        r = by_scope[scope]
        if r:
            return out(r["status"], r["basis"] or f"{LABELS[r['status']]} ({scope} rule)", r["id"])
    if (source.get("license") or "").lower() in ("creativecommon", "creative_commons", "cc-by"):
        return out(CC, "The platform reports a Creative Commons Attribution (CC BY) license")
    return out(MANUAL, "No rule, license or ownership information covers this source")


def apply(source: dict, settings: dict | None = None, all_rules: list[dict] | None = None) -> dict:
    """Evaluate and store the rights of a source; update its status and the user's action items."""
    settings = settings if settings is not None else db.get_settings()
    r = evaluate(source, settings, all_rules)
    fields: dict = {"rights_status": r["status"], "rights_basis": r["basis"], "rights_rule_id": r["rule_id"],
                    "rights_checked_at": time.time()}
    status = source.get("status") or "discovered"
    if r["status"] == BLOCKED and status not in ("analyzed", "weak", "exhausted"):
        fields["status"] = "blocked"
    elif r["auto_allowed"] and status in ("discovered", "needs_rights", "blocked"):
        fields["status"] = "eligible"
    elif not r["auto_allowed"] and status in ("discovered", "eligible", "blocked"):
        fields["status"] = "needs_rights"
    if r["status"] != source.get("rights_status"):
        state.event("rights_status", f"{source.get('title', '')[:80]}: {r['label']} ({r['basis']})",
                    ref_type="source", ref_id=source["id"], status=r["status"])
    if r["auto_allowed"] or r["status"] == BLOCKED:
        state.resolve(f"rights:{source['id']}")
    db.update("sources", source["id"], **fields)
    return {**source, **fields, "rights": r}


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
    state.action(f"rights:{source['id']}", "rights", f"Confirm the rights for “{source.get('title', '')[:80]}”",
                 f"{source.get('channel_title') or source.get('platform')} · {EXPLAIN[MANUAL]}",
                 "Answer on the Autopilot page (Yes, I have permission / No), or set its rights under "
                 "Autopilot → Advanced → Sources & rights.",
                 level="action", ref_type="source", ref_id=source["id"], snooze_s=ASK_AGAIN_AFTER)


def gate(source: dict | None, stage: str, settings: dict | None = None) -> dict:
    """Raise RightsBlocked unless the source may be used automatically at this stage (ingest, schedule, publish).
    Re-evaluates the rules each time, so a rule added later (e.g. Blocked) takes effect immediately."""
    if source is None:
        return {"status": OWNED, "auto_allowed": True, "basis": "Manual project"}
    settings = settings if settings is not None else db.get_settings()
    r = evaluate(source, settings)
    if not r["auto_allowed"]:
        raise RightsBlocked(f"{r['label']}: not used automatically at the {stage} stage. {r['explain']}", r["status"])
    return r


# ------------------------------------------------------------------ acquisition policy
def is_platform_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in PLATFORM_HOSTS)


def download_allowed(source: dict, settings: dict) -> tuple[bool, str]:
    """May the media be fetched automatically? Platform-hosted videos need the explicit setting (their terms only
    allow downloads they authorize, or with permission from the platform and the rights holders)."""
    if source.get("local_path"):
        return (Path(source["local_path"]).exists(), "Local file" if Path(source["local_path"]).exists() else
                "The local file no longer exists")
    url = source.get("url") or ""
    if not url:
        return False, "No file or URL"
    if is_platform_url(url) and source.get("platform") != "stream":
        if settings.get("rights_allow_remote_download"):
            return True, "Download allowed in Settings for authorized sources"
        return False, ("Platform-hosted video: add the original file (for your own videos, YouTube Studio → Download), "
                       "or allow downloads of authorized sources in Settings after checking the platform's terms.")
    return True, "Direct media or stream URL"


def url_typed_by_user(source: dict) -> bool:
    """Was this source's URL typed by you (added by hand, or a stream you configured)? Only then may it point into
    your own network; URLs that came from a feed's rows or from discovery must be public (netguard.py)."""
    if not source.get("signal_id"):
        return True
    signal = db.fetch("trend_signals", source["signal_id"]) or {}
    return signal.get("provider") == "stream_url"


def attribution(source: dict) -> str:
    """Credit line for Creative Commons sources (shown in the suggested description, which you approve)."""
    if source.get("rights_status") != CC:
        return ""
    who = source.get("channel_title") or "the original creator"
    return f"Source: “{source.get('title', '')}” by {who} ({source.get('url', '')}), licensed under CC BY."

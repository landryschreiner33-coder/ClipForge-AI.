"""Standing YouTube permission for one channel and visibility, recorded with its exact wording.

Public automation needs explicit Public audience setup and a connected channel. Existing v2 Private permission
stays Private. A new public permission never changes existing posts
or previously scheduled Private uploads. TikTok requires express consent on each post with preview, an unpreset
privacy choice and Music Usage Confirmation, so TikTok automation cannot substitute a standing permission.

Only exact files that passed the quality gate without specified warnings qualify. Content and reuse eligibility,
posting limits, cancellation and the emergency stop remain enforced. Platform approval may still restrict the
actual visibility; the returned result is reported separately from the visibility requested here.
"""
from __future__ import annotations

import datetime as dt
import time

from .. import config, db
from . import state

TEXT_VERSION = 3  # 3: explicit audience, visibility and connected-account permission
SUPPORTED = {
    "youtube": "YouTube uploads can run automatically under your permission for one channel and visibility. "
               "The upload result confirms who can watch; Private videos stay Private until you share them.",
}
NOT_SUPPORTED = {
    "tiktok": "TikTok's rules for apps require your OK on each post (with a preview and your own privacy choice), so "
              "TikTok posts wait for you in Posts. Approved posts then go out at their time by themselves."
}
# final-check warnings that hold a clip for your review instead of publishing it automatically ("frozen" is left
# out: a still picture over speech is normal for a podcast with a cover image)
HOLD_ON = ("content", "framing", "cuts", "captions", "silence", "black", "sound_rights")


def active(platform: str) -> dict | None:
    rows = db.select("publish_consents", "platform = ? AND revoked_at IS NULL", (platform,), "created_at DESC", 1)
    return rows[0] if rows else None


def account_id(platform: str) -> str:
    """The account posts would go to now ("" when none is connected)."""
    return str((db.get_account(platform) or {}).get("account_id") or "")


def same_account(consent: dict) -> bool:
    """Was the permission given for the account connected now? It names one channel, so it never carries over to
    another one connected later (no account connected: nothing can be uploaded anyway)."""
    given, now = (consent.get("settings") or {}).get("account_id") or "", account_id(consent["platform"])
    return bool(given and now and given == now)


def text_for(platform: str, cfg: dict, channel: str = "") -> str:
    """Exactly what you agree to (stored with the permission)."""
    where = f"my YouTube channel{f' “{channel}”' if channel else ''}"
    kids = "made for kids" if cfg["made_for_kids"] else "not made for kids"
    public = cfg.get("visibility") == "public"
    who = ("Public videos that anyone can watch" if public else "Private videos")
    meaning = ("Public posting is authorized only for new posts planned for the public. Existing posts and "
               "previously planned Private uploads keep their visibility. " if public else
               "Nobody else can watch them until I share them privately in YouTube Studio; ClipFoundry never makes "
               "them public or unlisted under this permission. ")
    return (f"Upload up to {cfg['daily_limit']} clip{'s' if cfg['daily_limit'] != 1 else ''} a day to {where} as "
            f"{who}, marked {kids}, between {cfg['start_hour']}:00 and {cfg['end_hour']}:00 "
            f"({cfg['timezone']}), without asking me about each one. {meaning}Only clips that passed "
            "every automatic check (file, sound, captions, framing, text), from videos I own or that an agreement or "
            "license covers. I can cancel any upcoming upload, and turn this off at any time.")


def view(settings: dict) -> dict:
    from ..publish import audience

    out = {}
    for platform in ("youtube", "tiktok"):
        c = active(platform)
        dest = audience.destination(platform, settings)
        visibility = audience.visibility(platform, dest["intent"], settings)
        blocker = ""
        if platform == "youtube":
            if not account_id(platform) or not (db.get_account(platform) or {}).get("has_tokens"):
                blocker = "Connect your YouTube channel first."
            elif not dest["confirmed"]:
                blocker = "Confirm who watches in Settings → Integrations first."
        can_enable = platform in SUPPORTED and not blocker
        enabled = bool(c) and same_account(c) and consent_visibility(c) == visibility and not blocker
        if visibility == "public" and c:
            enabled = enabled and (c.get("settings") or {}).get("group_version") == dest["group_version"]
        if c and not enabled and not blocker:
            blocker = "Renew automatic publishing for the connected channel and the audience selected now."
        out[platform] = {"supported": platform in SUPPORTED, "note": SUPPORTED.get(platform) or
                         NOT_SUPPORTED[platform], "enabled": enabled,
                         "visibility": visibility, "can_enable": can_enable,
                         "blocker": blocker,
                         "account_id": account_id(platform), "audience_version": dest["group_version"],
                         "consent": ({k: c[k] for k in ("id", "settings", "text", "created_at")} if c else None)}
    out["verified_project"] = bool(settings.get("youtube_project_verified"))
    return out


def enable(platform: str, visibility: str, made_for_kids: bool | None, daily_limit: int, start_hour: int,
           end_hour: int, agreed: bool, channel: str = "", *, expected_account_id: str = "",
           expected_audience_version: int | None = None) -> dict:
    if platform not in SUPPORTED:
        raise ValueError(NOT_SUPPORTED.get(platform, "Unknown platform"))
    if not agreed:
        raise ValueError("Read and confirm what automatic publishing will do")
    if visibility not in config.YOUTUBE_PRIVACY:
        raise ValueError("Choose Public or Private for automatic YouTube uploads")
    if made_for_kids is None:
        raise ValueError("Say whether your videos are made for kids (YouTube requires this answer)")
    if not 1 <= int(daily_limit) <= 15:
        raise ValueError("The daily limit is 1 to 15 posts")
    if not 0 <= int(start_hour) < int(end_hour) <= 24:
        raise ValueError("The posting window must start before it ends")
    settings = db.get_settings()
    from ..publish import audience

    dest = audience.destination(platform, settings)
    if not account_id(platform) or not (db.get_account(platform) or {}).get("has_tokens"):
        raise ValueError("Connect the YouTube channel this permission will authorize first")
    if expected_account_id and expected_account_id != account_id(platform):
        raise ValueError("Another YouTube channel is connected now. Review the channel and permission again")
    if expected_audience_version is not None and expected_audience_version != dest["group_version"]:
        raise ValueError("Who watches changed while this permission was open. Review it again")
    if visibility == "public":
        if dest["intent"] != audience.PUBLIC or not dest["confirmed"]:
            raise ValueError("Automatic uploads are Private only until you explicitly confirm Public audience "
                             "in Settings → Integrations")
    elif dest["intent"] == audience.PUBLIC:
        raise ValueError("The permission's visibility must match Who watches. Choose Public, or confirm a Private "
                         "audience in Settings → Integrations")
    cfg = {"visibility": visibility, "made_for_kids": bool(made_for_kids), "daily_limit": int(daily_limit),
           "start_hour": int(start_hour), "end_hour": int(end_hour),
           "timezone": settings.get("autopilot_timezone") or "America/Chicago",
           "min_quality": float(settings.get("autopilot_min_quality") or 0), "text_version": TEXT_VERSION,
           "account_id": account_id(platform)}
    if visibility == "public":
        cfg.update(audience_intent=audience.PUBLIC, group_version=dest["group_version"])
    now = time.time()
    for old in db.select("publish_consents", "platform = ? AND revoked_at IS NULL", (platform,)):
        db.update("publish_consents", old["id"], revoked_at=now)
    row = db.insert("publish_consents", {"platform": platform, "settings": cfg,
                                        "text": text_for(platform, cfg, channel)})
    state.resolve(f"consent_renew:{platform}")
    db.save_settings({"autopilot_auto_publish": True, f"autopilot_{platform}_daily_limit": int(daily_limit),
                      f"autopilot_{platform}_privacy": visibility, "autopilot_active_start": int(start_hour),
                      "autopilot_active_end": int(end_hour)})
    state.event("auto_publish_on", f"Automatic publishing turned on for {platform.title()}: {row['text']}",
                ref_type="consent", ref_id=row["id"])
    return row


def disable(platform: str) -> int:
    """Revoke the permission; posts it approved that have not started uploading wait for your approval again."""
    from .scheduler import _audit

    now = time.time()
    revoked = 0
    for c in db.select("publish_consents", "platform = ? AND revoked_at IS NULL", (platform,)):
        db.update("publish_consents", c["id"], revoked_at=now)
        revoked += 1
    back = 0
    for item in db.select("scheduled_publications", "platform = ? AND status = 'approved'", (platform,)):
        if (item.get("approval") or {}).get("by") != "automatic":
            continue
        db.update("scheduled_publications", item["id"], status="awaiting_approval", approval={},
                  status_note="Automatic publishing was turned off: approve it yourself to publish it",
                  audit=_audit(item, "auto_publish_off", "Automatic publishing was turned off"))
        back += 1
    if revoked:
        state.event("auto_publish_off", f"Automatic publishing turned off for {platform.title()} ({back} upcoming "
                                        f"post{'s' if back != 1 else ''} wait for your approval)")
    return back


def still_covers(item: dict) -> bool:
    """Is the permission that approved this post still in force?"""
    appr = item.get("approval") or {}
    if appr.get("by") != "automatic":
        return True
    c = active(item["platform"])
    if not c or c["id"] != appr.get("consent_id") or not same_account(c):
        return False
    visibility = consent_visibility(c)
    if not visibility or visibility != (item.get("privacy") or "private"):
        return False
    if visibility == "public":
        from ..publish import audience

        settings = db.get_settings()
        dest = audience.destination(item["platform"], settings)
        cfg = c.get("settings") or {}
        return ((item.get("audience") or {}).get("intent") == audience.PUBLIC and dest["intent"] == audience.PUBLIC
                and dest["confirmed"] and cfg.get("group_version") == dest["group_version"])
    return (item.get("audience") or {}).get("intent") != "PUBLIC"


def consent_visibility(consent: dict) -> str:
    """Old Private permissions remain Private; public requires the new explicit wording and account binding."""
    cfg = consent.get("settings") or {}
    visibility = cfg.get("visibility") or ""
    if visibility == "private" and int(cfg.get("text_version") or 0) >= 2:
        return visibility
    if (visibility == "public" and int(cfg.get("text_version") or 0) >= TEXT_VERSION and cfg.get("account_id")
            and cfg.get("audience_intent") == "PUBLIC"):
        return visibility
    return ""


def qualifies(report: dict | None) -> tuple[bool, str]:
    """May this clip go out without your review? Only with a passing final check and none of its warnings."""
    if not report:
        return False, "the final check has not run yet"
    if report["status"] != "passed":
        return False, "it did not pass the final check"
    held = [c for c in report.get("checks") or [] if c.get("status") == "warn" and c.get("name") in HOLD_ON]
    if held:
        return False, "the final check noted: " + "; ".join(f"{c['label']}: {c['detail']}" for c in held[:2])
    return True, ""


def since(consent: dict, settings: dict) -> str:
    from .scout import tz

    return dt.datetime.fromtimestamp(consent["created_at"], tz(settings)).strftime("%b %d")

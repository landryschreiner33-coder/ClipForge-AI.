"""Automatic publishing: your standing permission to upload without reviewing each post, where the platform's rules
allow it.

What the platforms' own documentation says (checked September 2026):

* YouTube (Data API videos.insert): an app may upload videos for the signed-in user. YouTube's Developer Policies
  require that users keep final control over what is published and know what the app does in their name. Here that is
  your explicit permission (which channel, what content, how many a day, when), stored with its exact wording, plus
  every upcoming post listed with Cancel until it goes out. Since the selected-audience version, uploads are always
  Private: nobody else can watch until you share a video privately in YouTube Studio (the API cannot invite viewers),
  and nothing is ever scheduled to turn public.
* TikTok (Content Posting API, Direct Post): TikTok's Content Sharing Guidelines require the user's express consent
  to each post, with a preview, a privacy choice with no preset value and the Music Usage Confirmation. So TikTok posts
  always wait for your OK in the Publish Center; once approved they go out at their time by themselves.

A post approved under this permission is marked "approved automatically" with the permission it came from; it is
never recorded as approved by you. Only clips that passed every check qualify: a clip whose final check noted a
possible problem (a warning) is held for you instead. Turning the permission off returns every post that has not
started uploading to "waiting for your approval". A permission given for public or unlisted videos (before this
version) ended when the app updated; it is asked again with the new wording.
"""
from __future__ import annotations

import datetime as dt
import time

from .. import config, db
from . import state

TEXT_VERSION = 2  # 2: Private uploads only, shared by you in YouTube Studio
SUPPORTED = {
    "youtube": "YouTube allows apps to upload videos for you. ClipFoundry uploads them as Private; you share each one "
               "with the people you picked in YouTube Studio.",
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
    return not given or not now or given == now


def text_for(platform: str, cfg: dict, channel: str = "") -> str:
    """Exactly what you agree to (stored with the permission)."""
    where = f"my YouTube channel{f' “{channel}”' if channel else ''}"
    kids = "made for kids" if cfg["made_for_kids"] else "not made for kids"
    return (f"Upload up to {cfg['daily_limit']} clip{'s' if cfg['daily_limit'] != 1 else ''} a day to {where} as "
            f"Private videos, marked {kids}, between {cfg['start_hour']}:00 and {cfg['end_hour']}:00 "
            f"({cfg['timezone']}), without asking me about each one. Nobody else can watch them until I share them "
            "privately in YouTube Studio; ClipFoundry never makes them public or unlisted. Only clips that passed "
            "every automatic check (file, sound, captions, framing, text), from videos I own or that an agreement or "
            "license covers. I can cancel any upcoming upload, and turn this off at any time.")


def view(settings: dict) -> dict:
    out = {}
    for platform in ("youtube", "tiktok"):
        c = active(platform)
        out[platform] = {"supported": platform in SUPPORTED, "note": SUPPORTED.get(platform) or
                         NOT_SUPPORTED[platform], "enabled": bool(c),
                         "consent": ({k: c[k] for k in ("id", "settings", "text", "created_at")} if c else None)}
    out["verified_project"] = bool(settings.get("youtube_project_verified"))
    return out


def enable(platform: str, visibility: str, made_for_kids: bool | None, daily_limit: int, start_hour: int,
           end_hour: int, agreed: bool, channel: str = "") -> dict:
    if platform not in SUPPORTED:
        raise ValueError(NOT_SUPPORTED.get(platform, "Unknown platform"))
    if not agreed:
        raise ValueError("Read and confirm what automatic publishing will do")
    if visibility not in config.YOUTUBE_PRIVACY:
        raise ValueError("Automatic uploads are Private only: you share them with your selected viewers in Studio")
    if made_for_kids is None:
        raise ValueError("Say whether your videos are made for kids (YouTube requires this answer)")
    if not 1 <= int(daily_limit) <= 15:
        raise ValueError("The daily limit is 1 to 15 posts")
    if not 0 <= int(start_hour) < int(end_hour) <= 24:
        raise ValueError("The posting window must start before it ends")
    settings = db.get_settings()
    cfg = {"visibility": visibility, "made_for_kids": bool(made_for_kids), "daily_limit": int(daily_limit),
           "start_hour": int(start_hour), "end_hour": int(end_hour),
           "timezone": settings.get("autopilot_timezone") or "America/Chicago",
           "min_quality": float(settings.get("autopilot_min_quality") or 0), "text_version": TEXT_VERSION,
           "account_id": account_id(platform)}
    now = time.time()
    for old in db.select("publish_consents", "platform = ? AND revoked_at IS NULL", (platform,)):
        db.update("publish_consents", old["id"], revoked_at=now)
    row = db.insert("publish_consents", {"platform": platform, "settings": cfg, "text": text_for(platform, cfg, channel)})
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
    return (bool(c) and c["id"] == appr.get("consent_id") and (c.get("settings") or {}).get("visibility") == "private"
            and same_account(c))


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

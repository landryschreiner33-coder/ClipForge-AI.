"""Who may watch an uploaded clip: one audience policy for every upload path.

This version posts only to a test audience the owner chooses, never to the general public:

* YouTube: the video is uploaded as **Private** (no `publishAt`, so YouTube never makes it public later). The owner
  then shares it privately in YouTube Studio with the people they pick. The Data API has no call that manages those
  invitations, so ClipFoundry records "awaiting viewer invitations" until the owner says they shared it; that is
  user-confirmed, not verified.
* TikTok: a post for the owner's approved **Followers** (or **Friends**, if the owner chose that narrower group) on a
  private account. TikTok only lets audited apps Direct Post to those groups; an unaudited app can only post "Only
  me", which is staging for the owner, never a delivery to viewers. Without an eligible route the clip becomes a
  ready-to-post package the owner posts in the TikTok app.

Three intents, independent of the platforms' own words:

* LOCAL_ONLY: kept on this PC, never uploaded.
* OWNER_ONLY: uploaded where only the owner sees it (YouTube Private without invitations, TikTok "Only me"). A
  disclosed staging state; it is never shown as delivered to test viewers.
* SELECTED_AUDIENCE: the owner's chosen viewers (YouTube invitations, TikTok approved followers or friends).

Public, unlisted (anyone with the link) and "Everyone" are blocked for every path: Autopilot, your own uploads,
retries, recovered jobs and posts planned before this version. Nothing here invites people, approves followers or
changes an account's privacy: the owner manages the audience in the platform's own app.

An upload needs a confirmed destination: the owner said, once per platform, how the audience works (Settings →
Integrations). Every stamp carries the policy version and the audience group's version; approvals are bound to the
stamp, so a change makes older approvals stale.
"""
from __future__ import annotations

import time

from .common import PublishError

LOCAL_ONLY = "LOCAL_ONLY"
OWNER_ONLY = "OWNER_ONLY"
SELECTED = "SELECTED_AUDIENCE"
LEGACY_PUBLIC = "LEGACY_PUBLIC"  # planned before this version as public/unlisted/everyone: kept, but blocked
INTENTS = (LOCAL_ONLY, OWNER_ONLY, SELECTED)
SETTING_INTENT = {"local_only": LOCAL_ONLY, "owner_only": OWNER_ONLY, "selected": SELECTED}
POLICY_VERSION = 1

BLOCKED_VISIBILITY = {"youtube": {"public", "unlisted"}, "tiktok": {"PUBLIC_TO_EVERYONE"}}
TIKTOK_GROUPS = {"followers": "FOLLOWER_OF_CREATOR", "friends": "MUTUAL_FOLLOW_FRIENDS"}
TIKTOK_GROUP_LABELS = {"followers": "your approved followers", "friends": "your friends (followers you follow back)"}
INTENT_LABELS = {LOCAL_ONLY: "Kept on this PC", OWNER_ONLY: "Only you (staging)", SELECTED: "Selected audience",
                 LEGACY_PUBLIC: "Public (planned before this version; blocked)"}

YOUTUBE_SHARE_STEPS = ("Open the video in YouTube Studio, choose Visibility → Private → Share privately, add the "
                       "email addresses of the people you picked, and save. Then press “I shared it” here.")
TIKTOK_PRIVATE_STEPS = ("In the TikTok app: Profile → Menu → Settings and privacy → Privacy → turn on Private "
                        "account, then check Followers so only the people you approved are there.")
PUBLIC_OFF_FIX = ("This version of ClipFoundry posts only to the viewers you choose. Use “Send to my selected "
                  "viewers” to plan it again for them, or cancel it.")


class AudienceBlocked(PublishError):
    """An upload this policy does not allow (wrong visibility, no confirmed destination, no eligible route)."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message, fix, "audience")


def _name(platform: str) -> str:
    return "YouTube" if platform == "youtube" else "TikTok"


def intent(platform: str, settings: dict) -> str:
    return SETTING_INTENT.get(str(settings.get(f"audience_{platform}") or "selected"), SELECTED)


def tiktok_group(settings: dict) -> str:
    group = str(settings.get("audience_tiktok_group") or "followers")
    return group if group in TIKTOK_GROUPS else "followers"


def destination(platform: str, settings: dict) -> dict:
    """The owner's audience choice for one platform, and whether it is confirmed (needed before any upload)."""
    want = intent(platform, settings)
    confirmed_at = float(settings.get(f"audience_{platform}_confirmed_at") or 0)
    group = "invited" if platform == "youtube" else tiktok_group(settings)
    if want == LOCAL_ONLY:
        label = "Kept on this PC"
        detail = f"Clips are not uploaded to {_name(platform)}."
    elif want == OWNER_ONLY:
        label = "Only you (staging)"
        detail = ("Uploaded as Private with nobody invited." if platform == "youtube" else
                  "Posted as “Only me”.") + " Nobody else can watch; this is not a test with viewers."
    elif platform == "youtube":
        label = "Invited viewers"
        detail = "Uploaded as Private. You invite the people you picked in YouTube Studio."
    else:
        label = "Approved friends" if group == "friends" else "Approved followers"
        detail = f"Posted for {TIKTOK_GROUP_LABELS[group]} on your private TikTok account."
    return {"platform": platform, "intent": want, "group": group, "label": label, "detail": detail,
            "confirmed": want != LOCAL_ONLY and confirmed_at > 0, "confirmed_at": confirmed_at or None,
            "group_version": int(settings.get(f"audience_{platform}_group_version") or 1)}


def visibility(platform: str, want: str, settings: dict) -> str:
    """The platform visibility that matches an intent ("" for a TikTok choice the owner makes per post)."""
    if platform == "youtube":
        return "private"
    if want == OWNER_ONLY:
        return "SELF_ONLY"
    return TIKTOK_GROUPS[tiktok_group(settings)]


def allowed(platform: str, settings: dict, offered: list[str] | None = None) -> list[str]:
    """The visibilities a publish screen may offer (TikTok: only among what TikTok returned, never preselected)."""
    want = intent(platform, settings)
    if want == LOCAL_ONLY:
        return []
    out = [visibility(platform, want, settings)]
    if offered is not None:
        out = [v for v in out if v in offered]
    return out


def classify(platform: str, privacy: str, settings: dict) -> str:
    """The intent a stored visibility amounts to (for posts planned before this version, and for checks)."""
    if privacy in BLOCKED_VISIBILITY.get(platform, set()):
        return LEGACY_PUBLIC
    if platform == "tiktok" and privacy == "SELF_ONLY":
        return OWNER_ONLY
    if platform == "tiktok" and privacy in TIKTOK_GROUPS.values():
        return SELECTED
    if platform == "youtube" and privacy == "private":
        return intent(platform, settings) if intent(platform, settings) != LOCAL_ONLY else OWNER_ONLY
    return SELECTED if platform == "tiktok" and not privacy else LEGACY_PUBLIC


def check(platform: str, privacy: str, settings: dict, *, mode: str = "direct", creator: dict | None = None,
          stamp: dict | None = None) -> dict:
    """Raise AudienceBlocked unless an upload with this visibility is allowed now; return the audience stamp.

    `stamp` is the post's stored audience (an older post keeps its own intent: a staged owner-only post is never
    turned into a delivery to viewers by a later setting). `creator` is TikTok's creator_info answer, when read."""
    name = _name(platform)
    if privacy in BLOCKED_VISIBILITY.get(platform, set()):
        raise AudienceBlocked(f"Public posting is turned off: this {name} post would be "
                              f"{'visible to anyone with the link' if privacy == 'unlisted' else 'public'}.",
                              PUBLIC_OFF_FIX)
    dest = destination(platform, settings)
    stop = halted(platform)
    if stop:
        raise AudienceBlocked(f"Uploads to {name} are stopped: {stop.get('detail', 'a video had the wrong audience')}",
                              f"Check the video in {name}, then press “I checked it” in Settings → Integrations.")
    want = (stamp or {}).get("intent") or dest["intent"]
    if want == LEGACY_PUBLIC:
        raise AudienceBlocked(f"This {name} post was planned as public before this version.", PUBLIC_OFF_FIX)
    if want == LOCAL_ONLY or dest["intent"] == LOCAL_ONLY:
        raise AudienceBlocked(f"{name} is set to keep clips on this PC.",
                              f"Settings → Integrations → {name}: choose who watches, or export the clip.")
    if not dest["confirmed"]:
        raise AudienceBlocked(f"Choose who watches your {name} clips first.",
                              f"Settings → Integrations → {name} → Who watches. Nothing is uploaded until you "
                              "confirm it.")
    if stamp and stamp.get("intent") == SELECTED and dest["intent"] != SELECTED:
        raise AudienceBlocked(f"This post was meant for your selected {name} viewers, but {name} is now set to "
                              f"“{dest['label']}”.", "Plan it again, or change Who watches back.")
    if stamp and stamp.get("group_version") and int(stamp["group_version"]) != dest["group_version"]:
        raise AudienceBlocked(f"Your {name} test group changed after this post was approved.",
                              "Approve it again for the current group.")
    route = "api"
    if platform == "youtube":
        if privacy != "private":
            raise AudienceBlocked("YouTube uploads must be Private (you invite the viewers in YouTube Studio).",
                                  "Choose Private.")
    elif mode == "direct":
        expected = visibility(platform, want, settings)
        if privacy != expected:
            label = "Only me" if expected == "SELF_ONLY" else TIKTOK_GROUP_LABELS[tiktok_group(settings)]
            raise AudienceBlocked(f"This TikTok post must be for {label}.",
                                  "Choose that option, or change Who watches in Settings → Integrations → TikTok.")
        if creator is not None and privacy not in (creator.get("privacy_options") or []):
            raise AudienceBlocked("TikTok does not offer that audience for this account right now.",
                                  "Make sure your TikTok account is private, or post it yourself from the "
                                  "ready-to-post package.")
        if want == SELECTED and not settings.get("tiktok_app_audited"):
            raise AudienceBlocked("TikTok only lets audited apps post for followers; this app can post “Only me”.",
                                  "Use the ready-to-post package (or a draft in your TikTok inbox) and choose "
                                  f"{'Friends' if tiktok_group(settings) == 'friends' else 'Followers'} in the app.")
    else:
        route = "manual"  # inbox draft or package: the owner picks the audience in the TikTok app
    return {"intent": want, "platform": platform, "policy_version": POLICY_VERSION, "group": dest["group"],
            "group_version": dest["group_version"], "visibility": privacy or visibility(platform, want, settings),
            "route": route, "at": time.time()}


def halted(platform: str) -> dict | None:
    """An open audience incident (a video reported wider than requested): uploads to that platform stop until the
    owner looked at it. Nothing is deleted or changed on the platform."""
    from ..autopilot import state

    return state.get(f"audience_halt:{platform}") or None


def incident(platform: str, detail: str, remote_id: str = "") -> None:
    from ..autopilot import state

    if halted(platform):
        return
    state.put(f"audience_halt:{platform}", {"at": time.time(), "detail": detail, "remote_id": remote_id})
    name = _name(platform)
    state.action(f"audience:{platform}", "publish", f"Check who can see a {name} video",
                 f"{detail} ClipFoundry stopped uploading to {name} until you check it. Changing the visibility now "
                 "cannot take back copies someone already saw.",
                 f"Open the video in {name} and set it back to the audience you chose, then press “I checked it” "
                 "in Settings → Integrations.", level="error")
    state.event("audience_incident", f"{name}: {detail}", "error", key=f"audience:{platform}")


def clear_incident(platform: str) -> None:
    from ..autopilot import state

    state.delete(f"audience_halt:{platform}")
    state.resolve(f"audience:{platform}")
    state.event("audience_checked", f"{_name(platform)}: you checked the video's audience; uploads may continue")


def tiktok_route(settings: dict, account: dict | None, creator: dict | None = None) -> str:
    """How a TikTok post for the selected audience can go out: "direct" (audited app, TikTok offers the group),
    "inbox" (a draft the owner finishes in the app) or "manual" (a package the owner posts by hand)."""
    scopes = (account or {}).get("scopes") or []
    want = intent("tiktok", settings)
    if (account or {}).get("has_tokens") and "video.publish" in scopes and (
            want == OWNER_ONLY or settings.get("tiktok_app_audited")):
        needed = visibility("tiktok", want, settings)
        if creator is None or needed in (creator.get("privacy_options") or []):
            return "direct"
    if (account or {}).get("has_tokens") and "video.upload" in scopes:
        return "inbox"
    return "manual"


# ------------------------------------------------------------------ delivery: what actually happened
DELIVERY_LABELS = {
    "local_ready": "Ready on this PC", "scheduled": "Scheduled", "audience_check": "Audience check",
    "requires_action": "Needs your action", "uploading": "Uploading", "remote_processing": "Processing on the platform",
    "uploaded_owner_only": "Uploaded, only you can see it", "awaiting_invitations": "Awaiting viewer invitations",
    "audience_user_confirmed": "Audience set up (you confirmed)",
    "restricted_api_verified": "Restricted audience (platform confirmed)",
    "restricted_requested": "Posted for your chosen group (as asked; TikTok does not report who can see it)",
    "manual_handoff": "Ready for you to post on TikTok", "awaiting_analytics": "Awaiting viewer results",
    "blocked": "Blocked", "failed": "Failed", "retrying": "Retrying", "uncertain": "Upload not confirmed",
    "canceled": "Canceled", "published": "Posted before this version",
}


def delivery_after_upload(platform: str, stamp: dict, returned_visibility: str, route: str) -> dict:
    """The delivery record once the platform accepted a file (never "watched", never "viewers can watch")."""
    now = time.time()
    want = (stamp or {}).get("intent") or SELECTED
    out = {"transfer": "done", "transfer_at": now, "route": route,
           "visibility": {"requested": (stamp or {}).get("visibility", ""), "returned": returned_visibility or None,
                          "evidence": "api" if returned_visibility and route == "api" else "unknown",
                          "checked_at": now if returned_visibility else None},
           "analytics": "awaiting_viewer_access"}
    if want == OWNER_ONLY:
        out["audience_setup"] = "owner_only"
    elif platform == "youtube":
        out["audience_setup"] = "awaiting_invitations"
    elif route == "manual":
        out["audience_setup"] = "manual_pending"
    else:
        out["audience_setup"] = "account_group"  # TikTok's own group (followers/friends) as the post requested
    return out


def delivery_state(item: dict, pub: dict | None = None) -> str:
    """One label for a planned post, from its separate fields (transfer, visibility, audience setup, analytics)."""
    status = item.get("status") or ""
    d = item.get("delivery") or {}
    setup = d.get("audience_setup") or ""
    if status == "canceled" or status == "replaced":
        return "canceled"
    if status == "blocked":
        return "blocked"
    if status == "failed":
        return "failed"
    if status == "reconciling":
        return "uncertain"
    if status == "action_needed":
        return "manual_handoff" if setup == "manual_pending" or (item.get("options") or {}).get("mode") in (
            "inbox", "manual") else "requires_action"
    if status == "publishing":
        if (pub or {}).get("status") == "processing":
            return "remote_processing"
        return "uploading" if pub else "audience_check"
    if status in ("awaiting_approval", "approved"):
        return "scheduled" if item.get("planned_at") else "local_ready"
    if status == "published":
        if setup == "owner_only":
            return "uploaded_owner_only"
        if setup == "awaiting_invitations":
            return "awaiting_invitations"
        if setup == "manual_pending":
            return "manual_handoff"
        if setup == "api_verified":
            return "restricted_api_verified"
        if setup == "account_group":
            return "restricted_requested"
        if setup in ("user_confirmed", "manual_confirmed"):
            return "audience_user_confirmed"
        # posted before this version: what it was is in its own record, nothing here is assumed
        return "uploaded_owner_only" if (item.get("audience") or {}).get("intent") == OWNER_ONLY else "published"
    return status or "local_ready"


ANALYTICS_LABELS = {
    "awaiting_viewer_access": "Awaiting viewer access", "awaiting_observations": "Awaiting observations",
    "api_available": "API data available", "manual_available": "Manual feedback available",
    "insufficient": "Insufficient evidence", "unavailable": "Analytics unavailable",
}


def analytics_state(item: dict, settings: dict | None = None) -> str:
    """The results side of a post, kept apart from its delivery (a waiting post never blocks the next clip): what
    evidence the Brain has for it (autopilot/brain.py), never a guess."""
    from .. import db

    if item.get("status") != "published":
        return "unavailable"
    setup = (item.get("delivery") or {}).get("audience_setup") or ""
    if setup == "owner_only" or (item.get("audience") or {}).get("intent") == OWNER_ONLY:
        return "unavailable"  # nobody else can watch it, so there is nothing to learn from viewers
    rows = db.select("brain_observations", "clip_id = ? AND platform = ?", (item.get("clip_id") or "",
                                                                           item.get("platform") or ""))
    if not rows:
        return "awaiting_viewer_access" if setup in ("awaiting_invitations", "manual_pending") else \
            "awaiting_observations"
    settings = settings if settings is not None else db.get_settings()
    views = max((r["metrics"].get("views") or 0 for r in rows if r["provenance"] != "tester_feedback"), default=0)
    testers = len({r["tester"].lower() for r in rows if r["provenance"] == "tester_feedback" and r.get("tester")})
    if views < int(settings.get("brain_min_views") or 10) and testers < int(settings.get("brain_min_testers") or 3):
        return "insufficient"
    return "api_available" if any(r["provenance"] == "platform_api" for r in rows) else "manual_available"


def view(settings: dict) -> dict:
    """What Settings → Integrations and the office show about who watches."""
    return {"policy_version": POLICY_VERSION, "youtube": destination("youtube", settings),
            "tiktok": destination("tiktok", settings),
            "summary": "Selected audience: YouTube invited viewers · TikTok approved followers",
            "youtube_steps": YOUTUBE_SHARE_STEPS, "tiktok_steps": TIKTOK_PRIVATE_STEPS,
            "limits": "Selected viewers are a small test group, not the public. Their results show how this group "
                      "reacts; they do not predict how the public would."}

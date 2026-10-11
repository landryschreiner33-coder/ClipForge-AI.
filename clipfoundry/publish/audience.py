"""Explicit audience policy shared by manual uploads, Autopilot, retries and recovery.

New posts may target Public, selected viewers, only the owner, or stay local. Public requires a confirmed choice;
YouTube public automation also needs new channel- and visibility-bound permission. TikTok always requires consent
for each post and audited Direct Post when requesting Everyone or followers. Unsupported routes hand the owner a
package or inbox draft, with no claim that it was automatically posted.

Existing posts keep their stored audience and visibility. Legacy public plans remain held; choosing Public never
reactivates them or widens previously scheduled Private uploads. YouTube Private never uses publishAt; invitation
sharing stays the owner's action. Audience stamps retain policy and group versions so approvals cover what the
owner chose. Delivery records distinguish requested visibility, the platform's answer, and user confirmation.
"""
from __future__ import annotations

import time

from .common import PublishError

LOCAL_ONLY = "LOCAL_ONLY"
OWNER_ONLY = "OWNER_ONLY"
SELECTED = "SELECTED_AUDIENCE"
PUBLIC = "PUBLIC"
LEGACY_PUBLIC = "LEGACY_PUBLIC"  # planned before this version as public/unlisted/everyone: kept, but blocked
INTENTS = (LOCAL_ONLY, OWNER_ONLY, SELECTED, PUBLIC)
SETTING_INTENT = {"local_only": LOCAL_ONLY, "owner_only": OWNER_ONLY, "selected": SELECTED, "public": PUBLIC}
POLICY_VERSION = 2

BLOCKED_VISIBILITY = {"youtube": {"unlisted"}, "tiktok": set()}
TIKTOK_GROUPS = {"followers": "FOLLOWER_OF_CREATOR", "friends": "MUTUAL_FOLLOW_FRIENDS"}
TIKTOK_GROUP_LABELS = {"followers": "your approved followers", "friends": "your friends (followers you follow back)"}
INTENT_LABELS = {LOCAL_ONLY: "Kept on this PC", OWNER_ONLY: "Only you (staging)", SELECTED: "Selected audience",
                 PUBLIC: "Public audience", LEGACY_PUBLIC: "Public (planned before this version; blocked)"}

YOUTUBE_SHARE_STEPS = ("Open the video in YouTube Studio, choose Visibility → Private → Share privately, add the "
                       "email addresses of the people you picked, and save. Then press “I shared it” here.")
TIKTOK_PRIVATE_STEPS = ("In the TikTok app: Profile → Menu → Settings and privacy → Privacy → turn on Private "
                        "account, then check Followers so only the people you approved are there.")
PUBLIC_OFF_FIX = ("Choose and confirm Public audience explicitly for new public posts. Existing posts keep their "
                  "visibility and need their own review; unlisted uploads are not supported.")


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
    elif want == PUBLIC:
        group, label = "public", "Public audience"
        detail = ("Requests Public visibility. The upload record shows who YouTube actually allows to watch."
                  if platform == "youtube" else
                  "Everyone, when TikTok offers it to your audited app. Each post still needs your OK; otherwise "
                  "you finish it in TikTok or post the package yourself.")
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
        return "public" if want == PUBLIC else "private"
    if want == PUBLIC:
        return "PUBLIC_TO_EVERYONE"
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
    if privacy == ("public" if platform == "youtube" else "PUBLIC_TO_EVERYONE"):
        return PUBLIC
    if platform == "tiktok" and privacy == "SELF_ONLY":
        return OWNER_ONLY
    if platform == "tiktok" and privacy in TIKTOK_GROUPS.values():
        return SELECTED
    if platform == "youtube" and privacy == "private":
        return SELECTED if intent(platform, settings) == SELECTED else OWNER_ONLY
    return SELECTED if platform == "tiktok" and not privacy else LEGACY_PUBLIC


def check(platform: str, privacy: str, settings: dict, *, mode: str = "direct", creator: dict | None = None,
          stamp: dict | None = None) -> dict:
    """Raise AudienceBlocked unless an upload with this visibility is allowed now; return the audience stamp.

    `stamp` is the post's stored audience (an older post keeps its own intent: a staged owner-only post is never
    turned into a delivery to viewers by a later setting). `creator` is TikTok's creator_info answer, when read."""
    name = _name(platform)
    if privacy in BLOCKED_VISIBILITY.get(platform, set()):
        raise AudienceBlocked(f"Unlisted uploads are not supported for {name}; choose Public or Private explicitly.",
                              PUBLIC_OFF_FIX)
    dest = destination(platform, settings)
    stop = halted(platform)
    if stop:
        raise AudienceBlocked(f"Uploads to {name} are stopped: {stop.get('detail', 'a video had the wrong audience')}",
                              f"Check the video in {name}, then press “I checked it” in Settings → Integrations.")
    want = (stamp or {}).get("intent") or dest["intent"]
    if not stamp and dest["intent"] == PUBLIC and privacy and privacy not in ("public", "PUBLIC_TO_EVERYONE"):
        want = classify(platform, privacy, settings)
    # Who watches is a default for new posts. A later Public choice cannot widen, retarget or silently replace
    # the selected/owner-only audience already stamped on an existing post.
    kept_private = bool(stamp and want in (SELECTED, OWNER_ONLY) and dest["intent"] == PUBLIC)
    if want == LEGACY_PUBLIC:
        raise AudienceBlocked(f"This {name} post was planned as public before this version.", PUBLIC_OFF_FIX)
    if want == LOCAL_ONLY or dest["intent"] == LOCAL_ONLY:
        raise AudienceBlocked(f"{name} is set to keep clips on this PC.",
                              f"Settings → Integrations → {name}: choose who watches, or export the clip.")
    if want == PUBLIC and dest["intent"] != PUBLIC:
        raise AudienceBlocked(f"Public posting is turned off for {name}: choose Public audience explicitly first.",
                              f"Settings → Integrations → {name} → Who watches → Public audience, then confirm it.")
    if privacy in ("public", "PUBLIC_TO_EVERYONE") and want != PUBLIC:
        raise AudienceBlocked("Public and unlisted YouTube uploads are turned off for this post's chosen audience."
                              if platform == "youtube" else "Public posting is turned off for this post's audience.",
                              "Choose and confirm Public audience for new posts. Existing posts keep their audience.")
    if not dest["confirmed"]:
        raise AudienceBlocked(f"Choose who watches your {name} clips first.",
                              f"Settings → Integrations → {name} → Who watches. Nothing is uploaded until you "
                              "confirm it.")
    if stamp and stamp.get("intent") == SELECTED and dest["intent"] != SELECTED and not kept_private:
        raise AudienceBlocked(f"This post was meant for your selected {name} viewers, but {name} is now set to "
                              f"“{dest['label']}”.", "Plan it again, or change Who watches back.")
    if stamp and stamp.get("group_version") and int(stamp["group_version"]) != dest["group_version"] and not \
            kept_private:
        raise AudienceBlocked(f"Your {name} test group changed after this post was approved.",
                              "Approve it again for the current group.")
    route = "api"
    if platform == "youtube":
        if want == PUBLIC and privacy != "public":
            raise AudienceBlocked("This YouTube post was planned for the public.", "Choose Public.")
        if want != PUBLIC and privacy != "private":
            raise AudienceBlocked("Choose Private (you invite the viewers in YouTube Studio).",
                                  "Choose Private.")
    elif mode == "direct":
        expected = visibility(platform, want, settings)
        if kept_private and want == SELECTED:
            expected = TIKTOK_GROUPS.get(stamp.get("group"), expected)
        if privacy != expected:
            label = "Everyone" if want == PUBLIC else "Only me" if expected == "SELF_ONLY" else \
                TIKTOK_GROUP_LABELS[tiktok_group(settings)]
            raise AudienceBlocked(f"This TikTok post must be for {label}.",
                                  "Choose that option, or change Who watches in Settings → Integrations → TikTok.")
        if creator is not None and privacy not in (creator.get("privacy_options") or []):
            raise AudienceBlocked("TikTok does not offer that audience for this account right now.",
                                  "Everyone requires a public TikTok account. Review its current privacy options, "
                                  "or post it yourself from the ready-to-post package." if want == PUBLIC else
                                  "Make sure your TikTok account is private, or post it yourself from the "
                                  "ready-to-post package.")
        if want in (SELECTED, PUBLIC) and not settings.get("tiktok_app_audited"):
            label = "Everyone" if want == PUBLIC else \
                "Friends" if tiktok_group(settings) == "friends" else "Followers"
            raise AudienceBlocked("TikTok only lets audited apps post for viewers; this app can post “Only me”.",
                                  "Use the ready-to-post package (or a draft in your TikTok inbox) and choose "
                                  f"{label} in the app.")
    else:
        route = "manual"  # inbox draft or package: the owner picks the audience in the TikTok app
    return {"intent": want, "platform": platform,
            "policy_version": int((stamp or {}).get("policy_version") or POLICY_VERSION),
            "group": stamp.get("group", dest["group"]) if kept_private else dest["group"],
            "group_version": (stamp.get("group_version", dest["group_version"]) if kept_private else
                              dest["group_version"]),
            "visibility": privacy or visibility(platform, want, settings),
            "route": route, "at": (stamp or {}).get("at") or time.time()}


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
    "public_api_verified": "Public (platform confirmed)",
    "public_requested": "Posted; Public requested (visibility not reported)",
    "public_restricted": "Uploaded, public visibility not confirmed",
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
    elif want == PUBLIC and route != "manual":
        out["audience_setup"] = ("public_api_verified" if returned_visibility == "public" else
                                 "public_requested" if platform == "tiktok" else "public_restricted")
        out["analytics"] = "awaiting_observations" if out["audience_setup"] != "public_restricted" else \
            "awaiting_viewer_access"
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
        if setup in ("public_api_verified", "public_requested", "public_restricted"):
            return setup
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
    destinations = {p: destination(p, settings) for p in ("youtube", "tiktok")}
    return {"policy_version": POLICY_VERSION, "youtube": destinations["youtube"],
            "tiktok": destination("tiktok", settings),
            "summary": " · ".join(f"{_name(p)}: {d['label']}" for p, d in destinations.items()),
            "youtube_steps": YOUTUBE_SHARE_STEPS, "tiktok_steps": TIKTOK_PRIVATE_STEPS,
            "limits": "Public publishing needs your explicit choice and the platform's approval. Changing this "
                      "setting never makes existing videos or previously planned private uploads public. "
                      "Results from public and selected viewers stay separate."}

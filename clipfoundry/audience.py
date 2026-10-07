"""Who may see a clip: the central audience policy for every upload path.

The owner's goal is a *selected audience*: a few chosen people watch real clips on YouTube and TikTok and their
genuine reactions inform later clips. That is neither "Only me" nor "everyone". Account privacy, a post's visibility
and who can actually watch are separate facts, so they are kept apart here.

Application intents (per destination, independent of the platforms' own words):

* ``LOCAL_ONLY``: clips stay on this PC (export, manual posting). Nothing is uploaded. The default until the user
  sets a destination up.
* ``OWNER_ONLY``: staging. YouTube private with no viewers invited, TikTok "Only me". Never shown as delivered to
  test viewers. (Older ``private`` YouTube settings migrate here.)
* ``SELECTED_AUDIENCE``: YouTube private + people the user invites in YouTube Studio; TikTok on a private account
  with Followers (that account's whole approved-follower group) or, when the user picks it, Friends.

Hard rules, whatever any setting, retry, recovered job, Brain update or model answer says:

* Public / everyone and unlisted / anyone-with-the-link are always blocked in this build.
* YouTube ``status.publishAt`` (a later public release) is never sent.
* "Only me" on TikTok is never a viewer-test delivery.
* Nothing here invites people, approves followers or changes an account's privacy: the user manages the audience.

Every upload entry point (Autopilot publisher, manual publish, bulk actions, retries, recovery) calls ``check`` right
before dispatch; approvals are bound to ``policy_version`` so a relevant change makes a stale approval invalid.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field

from .publish.common import PublishError

LOCAL_ONLY, OWNER_ONLY, SELECTED_AUDIENCE = "LOCAL_ONLY", "OWNER_ONLY", "SELECTED_AUDIENCE"
INTENTS = (LOCAL_ONLY, OWNER_ONLY, SELECTED_AUDIENCE)
PLATFORMS = ("youtube", "tiktok")
TIKTOK_GROUPS = {"FOLLOWERS": "FOLLOWER_OF_CREATOR", "FRIENDS": "MUTUAL_FOLLOW_FRIENDS"}
# provider visibility words that would widen the audience beyond the user's chosen people
WIDE = {"public", "unlisted", "PUBLIC_TO_EVERYONE"}
SCHEME = 1  # bump when the meaning of the policy fields changes

# Audience setup states of an upload (stored on the publication, separate from transfer and visibility)
SETUP_STAGING = "owner_only_staging"            # uploaded for the owner only; no test viewer can watch
SETUP_AWAITING_INVITES = "awaiting_invitations"  # YouTube private; the user still has to share it in Studio
SETUP_USER_CONFIRMED = "user_confirmed"          # the user says the viewers were invited / it was posted to followers
SETUP_API_REQUESTED = "api_requested"            # restricted visibility requested through the API; not yet confirmed
SETUP_API_VERIFIED = "api_verified"              # the platform's API reported/accepted the restricted visibility
SETUP_MANUAL_PENDING = "manual_handoff"          # ready for the user to post on TikTok themselves
SETUP_LABELS = {
    SETUP_STAGING: "Uploaded for you only (staging, not delivered to test viewers)",
    SETUP_AWAITING_INVITES: "Uploaded privately; awaiting viewer invitations",
    SETUP_USER_CONFIRMED: "Audience setup confirmed by you",
    SETUP_API_REQUESTED: "Restricted visibility requested; waiting for the platform",
    SETUP_API_VERIFIED: "Restricted visibility confirmed by the platform's API",
    SETUP_MANUAL_PENDING: "Ready for manual TikTok posting",
}

YOUTUBE_SHARE_STEPS = (
    "Open YouTube Studio → Content, open this video, keep Visibility on Private and choose Share privately. Add the "
    "people you chose (they need a Google account), then come back and press 'Viewers invited'. ClipFoundry never "
    "sends invitations itself, and private videos have no comments.")
TIKTOK_MANUAL_STEPS = (
    "On your phone: keep your TikTok account private (Settings and privacy → Privacy → Private account). Upload the "
    "exported video, paste the caption, and under 'Who can watch this video' choose {group}. Post it, then paste the "
    "post's link here or press 'Posted'. Do not choose Everyone.")


class AudienceBlocked(PublishError):
    """An upload that would not match the user's audience policy. Never retried automatically."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message, fix, "audience_blocked")


@dataclass
class Decision:
    platform: str
    intent: str
    route: str                 # "api" (upload through the API) or "manual" (handoff package) or "none"
    visibility: str            # provider visibility to request ("private", "FOLLOWER_OF_CREATOR", ...) or ""
    setup: str                 # expected audience setup state after a successful upload
    policy_version: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ settings
def intent(platform: str, settings: dict) -> str:
    value = str(settings.get(f"audience_{platform}_intent") or LOCAL_ONLY).upper()
    return value if value in INTENTS else LOCAL_ONLY


def tiktok_group(settings: dict) -> str:
    g = str(settings.get("audience_tiktok_group") or "FOLLOWERS").upper()
    return g if g in TIKTOK_GROUPS else "FOLLOWERS"


def policy_basis(platform: str, settings: dict) -> dict:
    """Everything an approval for this destination depends on."""
    basis = {"scheme": SCHEME, "platform": platform, "intent": intent(platform, settings),
             "group_version": int(settings.get(f"audience_{platform}_group_version") or 1)}
    if platform == "tiktok":
        basis.update(group=tiktok_group(settings), audited=bool(settings.get("tiktok_app_audited")),
                     private_account=bool(settings.get("audience_tiktok_private_confirmed")))
    return basis


def policy_version(platform: str, settings: dict) -> str:
    raw = json.dumps(policy_basis(platform, settings), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def tiktok_direct_eligible(settings: dict) -> tuple[bool, str]:
    """Whether TikTok Direct Post can reach approved followers for this app/account (else: manual handoff)."""
    if not settings.get("tiktok_app_audited"):
        return False, ("Your TikTok developer app is not audited, and unaudited apps can only post as 'Only me', which "
                       "test viewers cannot see.")
    if not settings.get("audience_tiktok_private_confirmed"):
        return False, "You have not confirmed that the TikTok account is private."
    return True, ""


# ------------------------------------------------------------------ the decision
def plan(platform: str, settings: dict) -> Decision:
    """How a new clip would reach this destination under the current policy (no network, no side effects)."""
    it = intent(platform, settings)
    ver = policy_version(platform, settings)
    if platform not in PLATFORMS or it == LOCAL_ONLY:
        return Decision(platform, LOCAL_ONLY, "none", "", "", ver, ["Clips stay on this PC for this destination."])
    if platform == "youtube":
        setup = SETUP_STAGING if it == OWNER_ONLY else SETUP_AWAITING_INVITES
        return Decision(platform, it, "api", "private", setup, ver)
    if it == OWNER_ONLY:
        return Decision(platform, it, "api", "SELF_ONLY", SETUP_STAGING, ver)
    ok, why = tiktok_direct_eligible(settings)
    visibility = TIKTOK_GROUPS[tiktok_group(settings)]
    if not ok:
        return Decision(platform, it, "manual", visibility, SETUP_MANUAL_PENDING, ver, [why])
    return Decision(platform, it, "api", visibility, SETUP_API_REQUESTED, ver)


def check(platform: str, requested: str, settings: dict, *, mode: str = "direct", options: dict | None = None,
          creator: dict | None = None, approved_policy: str | None = None) -> Decision:
    """Raise AudienceBlocked unless uploading with `requested` visibility matches the user's policy right now.

    Called right before every dispatch. `approved_policy` is the policy version stored with an approval; a different
    current version means the audience changed after approval (stale approval)."""
    opts = options or {}
    d = plan(platform, settings)
    if requested in WIDE or str(requested).lower() in WIDE:
        raise AudienceBlocked(
            f"{'Public' if 'PUBLIC' in requested.upper() else requested.capitalize()} posts are blocked: this version "
            "only shares clips with the people you chose.",
            "Use Private on YouTube (then invite viewers in YouTube Studio) or Followers/Friends on a private TikTok "
            "account.")
    if opts.get("publish_at"):
        raise AudienceBlocked("A scheduled public release (YouTube publishAt) is not allowed in this build.",
                              "ClipFoundry uploads at the planned time as Private instead.")
    if d.route == "none":
        raise AudienceBlocked(f"{platform.title()} is set to keep clips on this PC, so nothing is uploaded there.",
                              "Settings → Integrations → Selected audience: choose who should see the clips.")
    if approved_policy is not None and approved_policy != d.policy_version:
        raise AudienceBlocked("The audience settings changed after this post was approved.",
                              "Open the post, check who will see it and approve it again.")
    if platform == "youtube":
        if requested != "private":
            raise AudienceBlocked("YouTube uploads must be Private in this build.", "Choose Private.")
        return d
    # TikTok
    if mode == "inbox":
        # the draft lands in the user's own TikTok inbox; the user chooses who can see it in the app
        return Decision(platform, d.intent, "manual", d.visibility, SETUP_MANUAL_PENDING, d.policy_version,
                        ["Sent as a draft: choose Followers or Friends in the TikTok app, never Everyone."])
    if d.intent == OWNER_ONLY:
        if requested != "SELF_ONLY":
            raise AudienceBlocked("This TikTok destination is set to staging (Only me).",
                                  "Choose 'Only me', or set the destination to Selected audience.")
    else:
        if requested == "SELF_ONLY":
            raise AudienceBlocked("'Only me' cannot reach your test viewers.",
                                  "Choose Followers (or Friends), or set this destination to staging.")
        allowed = {d.visibility} | ({TIKTOK_GROUPS["FRIENDS"]} if d.visibility == TIKTOK_GROUPS["FOLLOWERS"] else set())
        if requested not in allowed:
            raise AudienceBlocked("That TikTok audience is not the group you chose.",
                                  f"Choose {'Followers' if d.visibility == 'FOLLOWER_OF_CREATOR' else 'Friends'}.")
        if d.route == "manual":
            raise AudienceBlocked("TikTok cannot post to your followers from this app: " + "; ".join(d.notes),
                                  "Use the manual TikTok package (Queue → Ready for manual TikTok posting).")
    if creator is not None and requested not in (creator.get("privacy_options") or []):
        raise AudienceBlocked("TikTok does not currently offer that audience for this account.",
                              "Check the account's privacy in the TikTok app, then try again.")
    return d


def check_scheduled(item: dict, settings: dict, creator: dict | None = None) -> Decision:
    """`check` for a scheduled post, bound to the policy its approval recorded."""
    approval = item.get("approval") or {}
    return check(item["platform"], item.get("privacy") or "", settings, mode=(item.get("options") or {}).get("mode")
                 or "direct", options=item.get("options"), creator=creator,
                 approved_policy=approval.get("audience_policy") if approval.get("hash") else None)


# ------------------------------------------------------------------ after the upload
def visibility_mismatch(platform: str, requested: str, returned: str) -> str:
    """Why the platform's reported visibility is wider than requested ("" when it is not)."""
    if not returned:
        return ""
    if returned in WIDE or returned.lower() in WIDE:
        return f"{platform.title()} reports the video as {returned}, wider than the {requested} that was requested."
    if platform == "youtube" and returned != "private":
        return f"YouTube reports '{returned}' instead of private."
    return ""


def record(pub_info: dict, decision: Decision, returned: str, evidence: str) -> dict:
    """The audience facts of an upload, kept apart from transfer success (stored in publications.info)."""
    setup = decision.setup
    if decision.platform == "tiktok" and decision.route == "api" and decision.intent == SELECTED_AUDIENCE \
            and returned and returned == decision.visibility:
        setup = SETUP_API_VERIFIED
    return {**pub_info, "audience": {"intent": decision.intent, "policy_version": decision.policy_version,
                                     "requested": decision.visibility, "returned": returned, "evidence": evidence,
                                     "setup": setup, "recorded_at": time.time()}}


def viewers_can_watch(pub: dict) -> bool:
    """True only when selected viewers have access by API evidence or the user's own confirmation."""
    a = (pub.get("info") or {}).get("audience") or {}
    return a.get("intent") == SELECTED_AUDIENCE and a.get("setup") in (SETUP_USER_CONFIRMED, SETUP_API_VERIFIED)


def summary(settings: dict) -> dict:
    """Plain-language destination descriptions for setup, Queue and the footer."""
    out = {}
    for p in PLATFORMS:
        d = plan(p, settings)
        if d.intent == LOCAL_ONLY:
            text = "Keep clips on this PC"
        elif d.intent == OWNER_ONLY:
            text = "Private staging (only you)"
        elif p == "youtube":
            text = "YouTube invited viewers (private video, you share it in Studio)"
        else:
            group = "approved followers" if tiktok_group(settings) == "FOLLOWERS" else "friends"
            text = f"TikTok {group} on your private account" + (" (you post it yourself)" if d.route == "manual"
                                                                 else "")
        out[p] = {**d.as_dict(), "text": text, "group": tiktok_group(settings) if p == "tiktok" else "invited",
                  "group_version": int(settings.get(f"audience_{p}_group_version") or 1)}
    return out


SCOPE_TEXT = ("This version prepares clips for invited YouTube viewers and approved followers on a private TikTok "
              "account. It does not post publicly. Reactions from this small group are test-audience evidence, not "
              "proof of how the wider public would respond. Connecting an account is not needed for clipping and "
              "exporting on this PC.")


def migrate_legacy(stored: dict) -> dict:
    """Settings to save once for databases from before the audience policy (never widens an audience).

    * A saved YouTube privacy of ``private`` (the old PRIVATE_ONLY behavior) becomes OWNER_ONLY staging.
    * A saved ``public`` or ``unlisted`` becomes LOCAL_ONLY: those modes are blocked in this build and nothing is
      retargeted automatically.
    """
    patch: dict = {}
    if "audience_youtube_intent" not in stored and "autopilot_youtube_privacy" in stored:
        old = str(stored.get("autopilot_youtube_privacy") or "").lower()
        patch["audience_youtube_intent"] = OWNER_ONLY if old == "private" else LOCAL_ONLY
        patch["audience_migrated_from"] = old
    return patch

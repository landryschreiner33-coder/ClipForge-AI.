"""Capability registry and integration cards (Settings → Integrations).

Three things are kept apart for every platform or service: whether ClipFoundry implements a capability (a fact of
this code), whether an account or key is connected (this PC's state), and whether the capability is available right
now (connected + permitted + within limits). A connected account does not make every capability available, and an
OAuth connection never grants media download or full analytics.

Implementation facts below describe this version's code; they are not promises about what a platform allows. Where
a platform needs approval (TikTok's audit, Google's derived-metrics exception) the card says so.
"""
from __future__ import annotations

import time

from .. import db

# implementation states
IMPLEMENTED = "implemented"
APPROVAL = "approval_required"     # implemented, but the platform must approve the app or the account first
NOT_IMPLEMENTED = "not_implemented"
UNSUPPORTED = "unsupported"        # the platform offers no supported way (this version does not work around it)
LOCAL = "local"                    # done on this PC; no platform involved

CAPS = ("discovery", "metadata", "transcript", "media", "upload", "visibility", "consent", "status", "analytics",
        "limits")
CAP_LABELS = {"discovery": "Finds videos", "metadata": "Reads titles and numbers", "transcript": "Transcript",
              "media": "Gets the video file", "upload": "Uploads", "visibility": "Who can watch",
              "consent": "Your OK", "status": "Checks the result", "analytics": "Results", "limits": "Limits"}

# platform -> capability -> (state, plain explanation)
REGISTRY: dict[str, dict[str, tuple[str, str]]] = {
    "youtube": {
        "discovery": (IMPLEMENTED, "Popular and searched videos through the YouTube Data API (your connected "
                                   "channel or an API key)."),
        "metadata": (IMPLEMENTED, "Title, channel, duration, views, likes and comments as YouTube reports them."),
        "transcript": (LOCAL, "Made on this PC with Whisper on your GPU; YouTube captions are not downloaded."),
        "media": (IMPLEMENTED, "A pasted link or a found video is downloaded only where access is allowed; your "
                               "connection to YouTube does not grant downloads."),
        "upload": (IMPLEMENTED, "Resumable upload through the YouTube Data API."),
        "visibility": (IMPLEMENTED, "Private only. You invite your viewers in YouTube Studio (no API for that)."),
        "consent": (IMPLEMENTED, "Your OK on each post, or the automatic-upload permission (Private only)."),
        "status": (IMPLEMENTED, "Upload processing and the returned privacy are read back after each upload."),
        "analytics": (APPROVAL, "Views, likes and comments are shown; using them for learning needs Google's "
                                "derived-metrics approval. Average percentage viewed needs the Analytics scope "
                                "and may be empty for a small private group."),
        "limits": (IMPLEMENTED, "Daily API quota units (an upload costs about 1,600), counted on this PC."),
    },
    "tiktok": {
        "discovery": (IMPLEMENTED, "Links to public TikTok videos found by web search (needs a Tavily key); TikTok "
                                   "has no open discovery API for this."),
        "metadata": (IMPLEMENTED, "Creator and title from TikTok's public embed endpoint; no view counts."),
        "transcript": (LOCAL, "Made on this PC with Whisper."),
        "media": (IMPLEMENTED, "Only where the video is accessible to the link importer; nothing is bypassed."),
        "upload": (APPROVAL, "Direct Post to your followers needs TikTok's app audit. Without it ClipFoundry sends "
                             "a draft to your TikTok inbox or prepares a ready-to-post package."),
        "visibility": (APPROVAL, "Followers or friends on a private account (audited apps); an unaudited app can "
                                 "only post 'Only me', which is staging, not a test."),
        "consent": (IMPLEMENTED, "Your OK on every post (TikTok requires it)."),
        "status": (IMPLEMENTED, "The post's publish status is read back; follower-only posts may not return a link."),
        "analytics": (UNSUPPORTED, "TikTok's video list API covers public posts only, so results of follower-only "
                                   "posts are unavailable here; enter them in Clips → Test feedback."),
        "limits": (IMPLEMENTED, "TikTok's posting caps per creator per day, as TikTok reports them."),
    },
    "web": {
        "discovery": (IMPLEMENTED, "Tavily web search finds public video links and the originals behind clips "
                                   "(paid credits beyond the free plan; capped by your monthly budget)."),
        "metadata": (IMPLEMENTED, "Only what the search result says; no statistics."),
        "media": (IMPLEMENTED, "Through the link importer, where accessible."),
        "limits": (IMPLEMENTED, "Free credits per month, then your discovery budget ($0 by default)."),
    },
    "library": {
        "discovery": (IMPLEMENTED, "Wikimedia Commons videos with free licenses."),
        "metadata": (IMPLEMENTED, "License, author and credit line as the library records them."),
        "media": (IMPLEMENTED, "Direct download from upload.wikimedia.org."),
    },
    "folders": {
        "discovery": (LOCAL, "Your videos folder and any watch folders you add."),
        "media": (LOCAL, "The files themselves."),
    },
    "live": {
        "discovery": (IMPLEMENTED, "Live streams of watched YouTube channels and stream links you add."),
        "media": (IMPLEMENTED, "HTTP/HLS recording within a time and size limit; protected streams are skipped."),
    },
    **{p: {"discovery": (NOT_IMPLEMENTED, f"No {name} connector in this version. A public {name} link you paste "
                                           "can still be imported where the link importer supports it.")}
       for p, name in (("twitch", "Twitch"), ("kick", "Kick"), ("reddit", "Reddit"), ("x", "X"),
                       ("instagram", "Instagram"), ("podcasts", "podcast"))},
    "google_trends": {"discovery": (UNSUPPORTED, "Google Trends has no supported public API; ClipFoundry does not "
                                                 "scrape it. Trend signals come from the platforms' own numbers.")},
}

CARD_LABELS = {"not_connected": "Not connected", "connected": "Connected", "permission_required":
               "Permission required", "rate_limited": "Rate limited", "error": "Error", "unsupported": "Unsupported",
               "requires_user_action": "Requires user action", "off": "Off", "not_implemented": "Not in this version"}


def _card(cid: str, name: str, status: str, detail: str, *, identity: str = "", missing: list[str] | None = None,
          action: str = "", caps: str = "", checked_at: float | None = None, **extra: object) -> dict:
    return {"id": cid, "name": name, "status": status, "status_label": CARD_LABELS[status], "detail": detail,
            "identity": identity, "missing": missing or [], "action": action,
            "capabilities": [{"id": c, "label": CAP_LABELS[c], "state": s, "detail": d}
                             for c, (s, d) in REGISTRY.get(caps or cid, {}).items()],
            "checked_at": checked_at, **extra}


def _limited(prefix: str) -> dict | None:
    from ..autopilot import state

    for key, value in (state.get_many(prefix) or {}).items():
        if isinstance(value, dict) and float(value.get("until") or 0) > time.time():
            return {"key": key, **value}
    return None


def cards(settings: dict | None = None) -> list[dict]:
    from ..pipeline import nvidia
    from ..publish import audience
    from ..publish.routes import _tiktok_state, _youtube_state

    settings = settings or db.get_settings()
    yt, tt = _youtube_state(settings), _tiktok_state(settings, None)
    out = []
    # YouTube
    dest = audience.destination("youtube", settings)
    if not yt["configured"]:
        st, detail, action = "requires_user_action", "Your Google Cloud app is not set up yet.", yt["setup"]
    elif yt["needs_reconnect"]:
        st, detail, action = "error", "Google asks you to connect again.", "Connect again"
    elif not yt["connected"]:
        st, detail, action = "not_connected", "Clips stay on this PC until you connect.", "Connect YouTube"
    elif not dest["confirmed"]:
        st, detail, action = "requires_user_action", "Confirm who watches (Private + your invited viewers).", \
            "Confirm the audience"
    else:
        st, detail, action = "connected", f"Uploads go to {dest['label'].lower()} as Private.", ""
    if st == "connected" and _limited("quota_wait:youtube"):
        st, detail = "rate_limited", "YouTube asked ClipFoundry to wait; uploads continue after the wait."
    out.append(_card("youtube", "YouTube", st, detail, identity=yt["name"], action=action,
                     missing=[] if yt["analytics"] or not yt["connected"] else
                     ["YouTube Analytics (average percentage viewed)"],
                     checked_at=yt.get("connected_at"), audience=dest, steps=audience.YOUTUBE_SHARE_STEPS))
    # TikTok
    dest = audience.destination("tiktok", settings)
    missing = []
    if tt["connected"] and not tt["can_direct_post"] and not tt["can_inbox"]:
        missing.append("video.upload or video.publish")
    if tt["connected"] and not tt["audited"]:
        missing.append("TikTok app audit (needed to post to followers)")
    if not tt["configured"]:
        st, detail, action = "requires_user_action", "Your TikTok developer app is not set up yet.", tt["setup"]
    elif tt["needs_reconnect"]:
        st, detail, action = "error", "TikTok asks you to connect again.", "Connect again"
    elif not tt["connected"]:
        st, detail, action = "not_connected", "Clips can still be posted by you from a ready-to-post package.", \
            "Connect TikTok"
    elif not tt["audited"]:
        st, detail, action = "permission_required", ("Unaudited apps cannot post to followers, so each clip is "
                                                     "prepared for you to post in the TikTok app."), ""
    elif not dest["confirmed"]:
        st, detail, action = "requires_user_action", "Confirm who watches (your approved followers).", \
            "Confirm the audience"
    else:
        st, detail, action = "connected", f"Posts go to {dest['label'].lower()} on your private account.", ""
    out.append(_card("tiktok", "TikTok", st, detail, identity=tt["name"], action=action, missing=missing,
                     checked_at=tt.get("connected_at"), audience=dest, steps=audience.TIKTOK_PRIVATE_STEPS))
    # Web search
    key = bool(settings.get("tavily_api_key"))
    out.append(_card("web", "Web search (Tavily)", "connected" if key else "not_connected",
                     "Finds public video links, including TikTok." if key else
                     "Optional: add a Tavily key to find TikTok links and originals of popular clips.",
                     action="" if key else "Add a key in Settings → Advanced", caps="web"))
    out.append(_card("library", "Free-license library", "connected" if settings.get("library_discovery") else "off",
                     "Wikimedia Commons videos with free licenses.", caps="library"))
    # NVIDIA
    v = nvidia.view(settings)
    if not v["enabled"]:
        st, detail = "off", "Optional. Local analysis is used."
    elif v["circuit"]["open"]:
        st, detail = "rate_limited" if "wait" in (v["circuit"].get("reason") or "") else "error", \
            v["circuit"].get("reason") or "Paused after failures"
    elif v["problems"]:
        st, detail = "requires_user_action", v["problems"][0]
    else:
        st, detail = "connected", f"{v['model']} ({v['mode']})"
    out.append(_card("nvidia", "NVIDIA AI (optional)", st, detail, caps="nvidia", nvidia=v))
    for cid, name in (("twitch", "Twitch"), ("kick", "Kick"), ("reddit", "Reddit"), ("x", "X"),
                      ("instagram", "Instagram"), ("podcasts", "Podcasts"), ("google_trends", "Google Trends")):
        state_ = REGISTRY[cid]["discovery"][0]
        out.append(_card(cid, name, "unsupported" if state_ == UNSUPPORTED else "not_implemented",
                         REGISTRY[cid]["discovery"][1]))
    return out


def matrix() -> dict:
    """The capability registry as data, for the docs page and the Integrations details."""
    return {"capabilities": CAP_LABELS, "platforms": {p: {c: {"state": s, "detail": d} for c, (s, d) in caps.items()}
                                                      for p, caps in REGISTRY.items()}}

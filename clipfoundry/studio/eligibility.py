"""Whether a finished output fits each destination, in words. A vertical clip is not automatically a Short.

Rules checked against the platforms' own help pages on 2026-11-04 (docs/PLATFORM_CAPABILITIES.md):
- YouTube: a square or vertical video of at most 3 minutes is a Short; longer ones upload as regular videos, up to
  15 minutes unless the channel is verified, and never longer than 12 hours.
- TikTok: each creator has their own limit (creator_info.max_video_post_duration_sec, read again before every post);
  every creator can post at least 3 minutes, some 5 or 10.
Nothing here truncates, speeds up, splits or relabels anything: a too-long story keeps its full master and the owner
chooses an alternative.
"""
from __future__ import annotations

SHORTS_MAX = 180.0
YOUTUBE_UNVERIFIED_MAX = 15 * 60.0
YOUTUBE_MAX = 12 * 3600.0
TIKTOK_BASELINE = 180.0
ALTERNATIVES = ["Upload the complete story to YouTube as a regular video", "Download the full master",
                "Split it into parts (only if you choose to)"]


def _fmt(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def youtube(duration: float, width: int, height: int) -> dict:
    vertical = width and height and width <= height
    if duration <= SHORTS_MAX and vertical:
        return {"state": "short", "eligible": True, "label": "YouTube Short",
                "text": f"{_fmt(duration)}, vertical: uploads as a YouTube Short."}
    if duration <= YOUTUBE_UNVERIFIED_MAX:
        why = "longer than Shorts allow (3:00)" if duration > SHORTS_MAX else "not vertical"
        return {"state": "regular", "eligible": True, "label": "Regular YouTube video",
                "text": f"{_fmt(duration)} is {why}: it uploads as a regular YouTube video, not a Short."}
    if duration <= YOUTUBE_MAX:
        # A connected account is not proof that YouTube has enabled long uploads. Keep the full master, but
        # do not send it automatically when that capability has not been established for this destination.
        return {"state": "needs_verified", "eligible": False, "label": "Check channel verification",
                "text": f"{_fmt(duration)} is longer than 15 minutes. Automatic upload is on hold because "
                        "ClipForge cannot confirm this channel's long-upload eligibility. Check the channel in "
                        "YouTube Studio, then upload the full master there.",
                "alternatives": ["Check channel verification in YouTube Studio", "Download the full master"]}
    return {"state": "too_long", "eligible": False, "label": "Too long for YouTube",
            "text": "Longer than YouTube's 12-hour maximum.", "alternatives": ALTERNATIVES[1:]}


def tiktok(duration: float, account_limit: float | None = None, account: str = "") -> dict:
    limit = float(account_limit) if account_limit else TIKTOK_BASELINE
    who = f"“{account}”" if account else "This TikTok account"
    if duration <= limit:
        known = "" if account_limit else " (ClipForge checks this account's own limit again before posting)"
        return {"state": "ok", "eligible": True, "label": "TikTok", "limit": limit,
                "text": f"{_fmt(duration)} fits {who}'s limit of {_fmt(limit)}{known}."}
    return {"state": "too_long", "eligible": False, "label": "Too long for TikTok", "limit": limit,
            "text": f"{_fmt(duration)} is longer than {who}'s limit of {_fmt(limit)}. The full story is kept.",
            "alternatives": ALTERNATIVES}


def for_output(duration: float, width: int, height: int, destinations: list[dict]) -> list[dict]:
    """Eligibility for each chosen destination connection (exact account names, never just the platform)."""
    out = []
    for d in destinations:
        name = d.get("nickname") or d.get("display_name") or d.get("label") or d.get("platform", "")
        if d.get("platform") == "youtube":
            e = youtube(duration, width, height)
        elif d.get("platform") == "tiktok":
            e = tiktok(duration, (d.get("info") or {}).get("max_video_post_duration_sec"), name)
        else:
            e = {"state": "unsupported", "eligible": False, "label": "Unsupported", "text": "Unknown destination."}
        out.append({"connection_id": d.get("id") or d.get("connection_id"), "platform": d.get("platform"),
                    "account": name, **e})
    return out

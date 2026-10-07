"""Real performance numbers of published clips, read from the platforms' official APIs.

Each refresh stores a timestamped snapshot. Only numbers an API actually returns are stored; anything it does not
report (for example watch time on TikTok, or YouTube Analytics before its data arrives) stays empty, with a note
saying why. Nothing is estimated, extrapolated or invented.
"""
from __future__ import annotations

import datetime as dt

from .. import db
from . import tiktok, youtube
from .common import PublishError


def _int(v: object) -> int | None:
    try:
        return int(str(v)) if v is not None and str(v).strip() != "" else None
    except ValueError:
        return None


def _float(v: object) -> float | None:
    try:
        return round(float(v), 3) if v is not None and str(v).strip() != "" else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _youtube(pub: dict) -> tuple[dict, str, list[str], dict]:
    token = youtube.Token(db.get_settings())
    st = youtube.video_statistics(token, pub["remote_id"])
    if st is None:
        return {}, "YouTube Data API v3", ["The video no longer exists on YouTube (or is not visible to this "
                                           "channel)."], {}
    metrics = {"views": _int(st.get("viewCount")), "likes": _int(st.get("likeCount")),
               "comments": _int(st.get("commentCount"))}
    raw = {"statistics": st}
    source = "YouTube Data API v3"
    notes: list[str] = []
    acc = db.get_account("youtube") or {}
    if youtube.SCOPES[2] not in (acc.get("scopes") or []):
        notes.append("Shares, watch time and retention come from YouTube Analytics: connect YouTube again and "
                     "allow analytics access to get them.")
        return metrics, source, notes, raw
    start = dt.datetime.fromtimestamp(pub["created_at"], dt.timezone.utc).date().isoformat()
    end = dt.datetime.now(dt.timezone.utc).date().isoformat()
    try:
        an = youtube.video_analytics(token, pub["remote_id"], start, end)
    except PublishError as exc:
        if exc.code == "accessNotConfigured":
            notes.append("Enable the YouTube Analytics API in your Google Cloud project to get shares, watch time "
                         "and retention.")
        else:
            notes.append(f"YouTube Analytics was not available: {exc}")
        return metrics, source, notes, raw
    source += " + YouTube Analytics API v2"
    if an is None:
        notes.append("YouTube Analytics has no data for this video yet; it usually appears 2-3 days after upload.")
        return metrics, source, notes, raw
    raw["analytics"] = an
    metrics.update({"shares": _int(an.get("shares")), "watch_time_minutes": _float(an.get("estimatedMinutesWatched")),
                    "avg_view_duration_s": _float(an.get("averageViewDuration")),
                    "avg_view_percentage": _float(an.get("averageViewPercentage"))})
    notes.append("Shares, watch time and retention come from YouTube Analytics, which runs 2-3 days behind.")
    return metrics, source, notes, raw


def _tiktok(pub: dict) -> tuple[dict, str, list[str], dict]:
    ids = [str(i) for i in (pub.get("info") or {}).get("post_ids") or []]
    source = "TikTok Display API (video.query)"
    if not ids:
        return {}, source, ["TikTok only reports statistics for posts with a public video ID. 'Only me', Followers "
                            "and Friends posts and inbox drafts usually have none; after posting from the TikTok app, "
                            "link the post with its URL, or enter your test viewers' results in Clips → Test "
                            "feedback."], {}
    if "video.list" not in ((db.get_account("tiktok") or {}).get("scopes") or []):
        return {}, source, ["ClipFoundry was not given TikTok's video.list permission. Turn on 'Video statistics' in "
                            "Settings → Publishing → TikTok and connect again."], {}
    videos = tiktok.video_statistics(tiktok.Token(db.get_settings()), ids)
    v = videos.get(ids[0])
    if not v:
        return {}, source, ["TikTok did not return this video for your account (deleted, private, or posted by "
                            "another account)."], {}
    metrics = {"views": _int(v.get("view_count")), "likes": _int(v.get("like_count")),
               "comments": _int(v.get("comment_count")), "shares": _int(v.get("share_count"))}
    return metrics, source, ["TikTok's API does not report watch time or retention."], {"video": v}


def refresh(pub: dict) -> dict:
    """Fetch and store the current numbers of one publication. Returns the new snapshot."""
    if pub["status"] not in ("done", "action_needed"):
        raise PublishError("There are no statistics for an upload that did not finish.")
    if pub["platform"] == "youtube":
        if not pub.get("remote_id"):
            raise PublishError("This upload has no YouTube video ID.")
        metrics, source, notes, raw = _youtube(pub)
        metrics["remote_id"] = pub["remote_id"]
    else:
        metrics, source, notes, raw = _tiktok(pub)
        metrics["remote_id"] = ((pub.get("info") or {}).get("post_ids") or [""])[0]
    return db.add_performance(pub, metrics, source, notes, raw)


def refresh_all() -> dict:
    done, failed = 0, []
    for pub in db.list_publications():
        if pub["status"] not in ("done", "action_needed"):
            continue
        try:
            refresh(pub)
            done += 1
        except PublishError as exc:
            failed.append({"publication_id": pub["id"], "platform": pub["platform"], "error": str(exc),
                           "fix": exc.fix})
    return {"refreshed": done, "failed": failed}

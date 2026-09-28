"""Publisher: uploads approved, due posts through the official YouTube Data API and TikTok Content Posting API.

Before every upload it checks again that the source may be used (rights), that the approval still matches the
exact content, that the clip was not published already, that the platform accepts posts right now and that the
account is connected. If the user has to do something (reconnect, approve again, pick another visibility, get the
app audited), the post stops there with a clear action item.

Uploads are idempotent: the YouTube upload session and the TikTok publish ID are stored as soon as they exist, so
after a crash or restart the upload is resumed or its outcome is read back, instead of posting the video twice.
What each platform actually did (public, private, scheduled, sent to the inbox) is recorded as reported.
"""
from __future__ import annotations

import datetime as dt
import time

import httpx

from .. import db
from ..pipeline import fingerprint
from ..publish import jobs as publish_jobs
from ..publish import tiktok, youtube
from ..publish.common import Cancelled as UploadCancelled
from ..publish.common import PublishError, client
from . import queue, quota, rights, state
from .host import Job, handler
from .scheduler import _audit, active_version_path, approval_valid, block_platform, blocked_until, tz

RECONNECT_WAIT = 30 * 60


def _item(item_id: str) -> dict | None:
    return db.fetch("scheduled_publications", item_id)


def _set(item: dict, status: str, note: str, event: str, **fields: object) -> None:
    db.update("scheduled_publications", item["id"], status=status, status_note=note[:500],
              audit=_audit(item, event, note), **fields)


def _action_needed(item: dict, key: str, title: str, detail: str, fix: str) -> None:
    _set(item, "action_needed", f"{detail} {fix}".strip(), "action_needed", last_error=detail, fix=fix)
    state.action(key, "publish", title, detail, fix, ref_type="scheduled", ref_id=item["id"])


def _next_local_midnight(settings: dict) -> float:
    now = dt.datetime.now(tz(settings))
    return dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(0, 5), tz(settings)).timestamp()


def already_published(item: dict) -> str:
    """Why this post would be a repeat ("" if it is not)."""
    for p in db.list_publications(item["clip_id"], item["platform"]):
        if p["status"] in ("done", "action_needed") and p.get("scheduled_id") != item["id"]:
            return "This clip was already published on this platform."
    mine = db.fetch("clip_fingerprints", item["clip_id"], "clip_id")
    if mine:
        for o in db.select("clip_fingerprints", "clip_id != ? AND clip_id IN (SELECT clip_id FROM publications WHERE "
                                                "platform = ? AND status IN ('done', 'action_needed'))",
                           (item["clip_id"], item["platform"])):
            if fingerprint.text_similarity(mine.get("text_sig") or [], o.get("text_sig") or []) >= 0.6 or \
                    fingerprint.same_video(mine.get("phash") or [], o.get("phash") or []):
                return "A clip with the same moment was already published on this platform."
    return ""


# ------------------------------------------------------------------ recovering an interrupted upload
def _youtube_upload_by_title(pub: dict) -> dict | None:
    """After an expired upload session: did the video arrive anyway? (recent uploads of the channel, 2 units)"""
    token = youtube.Token(db.get_settings())
    acc = db.get_account("youtube") or {}
    youtube._quota("channels.list", "publish")  # noqa: SLF001
    with client(30) as c:
        r = c.get(f"{youtube.API_URL}/channels", params={"part": "contentDetails", "id": acc.get("account_id", "")},
                  headers={"Authorization": f"Bearer {token.get()}"})
        items = r.json().get("items") or [] if r.status_code == 200 else []
        playlist = ((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") if items \
            else None
        if not playlist:
            return None
        youtube._quota("playlistItems.list", "publish")  # noqa: SLF001
        r = c.get(f"{youtube.API_URL}/playlistItems", params={"part": "snippet,contentDetails", "playlistId": playlist,
                                                              "maxResults": 10},
                  headers={"Authorization": f"Bearer {token.get()}"})
    for it in (r.json().get("items") or []) if r.status_code == 200 else []:
        sn = it.get("snippet") or {}
        if sn.get("title") == pub["title"]:
            return {"id": (it.get("contentDetails") or {}).get("videoId") or sn.get("resourceId", {}).get("videoId")}
    return None


def recover(pub: dict) -> str:
    """What happened to an upload that was interrupted: 'done', 'resume' (upload again/continue) or 'wait'."""
    if pub["status"] in ("done", "action_needed"):
        return "done"
    if pub["platform"] == "youtube":
        if (pub.get("info") or {}).get("upload_session"):
            return "resume"  # youtube.upload continues the stored session, or learns it already finished
        try:
            found = _youtube_upload_by_title(pub) if pub.get("status") == "uploading" else None
        except (PublishError, httpx.HTTPError, ValueError):
            found = None
        if found and found.get("id"):
            db.update_publication(pub["id"], status="done", remote_id=found["id"], url=youtube.video_url(found["id"]),
                                  message="The upload had finished before the interruption.")
            return "done"
        return "resume"
    if pub.get("remote_id"):
        outcome = publish_jobs._tiktok_outcome(pub, tiktok.fetch_status(tiktok.Token(db.get_settings()),  # noqa: SLF001
                                                                         pub["remote_id"]),
                                               (pub.get("info") or {}).get("username", ""))
        if outcome:
            db.update_publication(pub["id"], **outcome)
            return "done" if outcome.get("status") in ("done", "action_needed") else "resume"
        return "wait"  # TikTok is still processing the earlier upload: never post it a second time meanwhile
    return "resume"


# ------------------------------------------------------------------ the job
def _publication(item: dict, video: str, version: str, clip: dict) -> dict:
    pub = db.get_publication(item.get("publication_id") or "") if item.get("publication_id") else None
    if pub:
        return pub
    opts = dict(item.get("options") or {})
    if item["platform"] == "youtube":
        opts["publish_at"] = item["planned_at"]
    else:
        opts["duration"] = float(clip.get("duration") or 0)
    from ..publish.jobs import feature_snapshot

    version_row = db.get_version(version) if version else None
    pub = db.create_publication(item["clip_id"], item["platform"], project_id=clip["project_id"],
                                mode=opts.get("mode", "direct"), status="queued", message="Autopilot upload",
                                title=item["title"], description=item["description"], tags=item.get("tags") or [],
                                requested_privacy=item["privacy"], video_path=video, version_id=version,
                                options=opts, features=feature_snapshot(clip, version_row), scheduled_id=item["id"])
    db.update("scheduled_publications", item["id"], publication_id=pub["id"])
    return pub


def _handle_error(job: Job, item: dict, exc: PublishError, settings: dict) -> None:
    code = exc.code or ""
    platform = item["platform"]
    if code in ("network", "rate_limit_exceeded", "internal", "video_pull_failed"):
        raise queue.Retry(str(exc), exc.fix, delay=60 if code == "rate_limit_exceeded" else None)
    if code in ("quota_budget", "quotaExceeded"):
        until = quota.next_reset()
        _set(item, "approved", f"Waiting for the YouTube quota to reset. {exc}", "quota")
        raise queue.Wait("quota", until - time.time() + 120, str(exc))
    if code in ("uploadLimitExceeded", "spam_risk_too_many_posts", "reached_active_user_cap"):
        until = time.time() + 24 * 3600 if code != "spam_risk_too_many_posts" else _next_local_midnight(settings)
        block_platform(platform, until, str(exc))
        _set(item, "approved", f"{exc} It will be tried again after the limit resets.", "platform_limit",
             planned_at=None)
        raise queue.Fail(str(exc), exc.fix)
    if code in ("reconnect", "not_connected", "setup", "access_token_invalid", "auth_removed", "scope",
                "scope_not_authorized", "insufficientPermissions"):
        _action_needed(item, f"connect:{platform}", f"Reconnect {platform.title()} to publish", str(exc), exc.fix)
        raise queue.Fail(str(exc), exc.fix)
    if code in ("unaudited", "unaudited_client_can_only_post_to_private_accounts", "privacy_level_option_mismatch",
                "duration", "spam_risk_user_banned_from_posting", "user_banned_from_posting"):
        _action_needed(item, f"review:{item['id']}", f"Review “{item['title'][:50]}” for {platform.title()}", str(exc),
                       exc.fix or "Change the visibility and approve it again, or cancel it.")
        db.update("scheduled_publications", item["id"], approval={})
        raise queue.Fail(str(exc), exc.fix)
    if job.row["attempts"] >= job.row["max_attempts"]:
        _set(item, "failed", str(exc), "failed", last_error=str(exc), fix=exc.fix)
        raise queue.Fail(str(exc), exc.fix)
    raise queue.Retry(str(exc), exc.fix)


@handler("publish")
def publish(job: Job) -> dict:
    settings = db.get_settings()
    item = _item(job.payload.get("scheduled_id", ""))
    if not item:
        raise queue.Fail("The scheduled post was deleted")
    if item["status"] in ("published", "canceled", "replaced"):
        return {"message": f"Nothing to do: the post is {item['status']}"}
    clip = db.get_clip(item["clip_id"])
    if not clip or clip["status"] != "ready":
        _set(item, "failed", "The clip is missing or not rendered.", "failed")
        raise queue.Fail("The clip is missing or not rendered")
    project = db.get_project(clip["project_id"]) or {}
    source = db.fetch("sources", project.get("source_id") or "") if project.get("source_id") else None
    try:
        rights.gate(source, "publish", settings)
    except rights.RightsBlocked as exc:
        _set(item, "blocked", str(exc), "blocked")
        raise queue.Fail(str(exc), "Change the source's rights status in Autopilot → Sources.") from exc
    if not approval_valid({**item, "status": "approved"}):
        _set(item, "awaiting_approval", "The clip or its text changed after approval: approve it again.",
             "approval_invalidated", approval={})
        raise queue.Fail("The approval no longer matches the content")
    repeat = "" if settings.get("autopilot_allow_republish") else already_published(item)
    if repeat:
        _set(item, "canceled", f"Not published: {repeat}", "duplicate")
        return {"message": repeat}
    until, why = blocked_until(item["platform"])
    if until:
        raise queue.Wait("platform_limit", until - time.time() + 60, f"{item['platform']}: {why}")
    acc = db.get_account(item["platform"]) or {}
    if not acc.get("has_tokens"):
        _action_needed(item, f"connect:{item['platform']}", f"Connect {item['platform'].title()} to publish",
                       f"{item['platform'].title()} is not connected.", "Settings → Publishing → Connect.")
        raise queue.Wait("not_connected", RECONNECT_WAIT, f"{item['platform'].title()} is not connected")
    state.resolve(f"connect:{item['platform']}")
    video, version = active_version_path(clip)
    pub = _publication(item, video, version, clip)
    _set(item, "publishing", "Uploading", "upload_started")
    try:
        if pub["status"] not in ("queued",):
            what = recover(pub)
            if what == "wait":
                raise queue.Wait("tiktok_processing", 60, "TikTok is still processing the earlier upload")
            pub = db.get_publication(pub["id"]) or pub
        if pub["status"] not in ("done", "action_needed"):
            runner = publish_jobs.RUNNERS[item["platform"]]
            runner(pub, job.cancelled)
    except (queue.Canceled, UploadCancelled):
        db.update_publication(pub["id"], status="cancelled", message="Stopped before the upload finished")
        _set(item, "approved", "Stopped before the upload finished; it will get a new time.", "stopped",
             planned_at=None, publication_id="")
        raise queue.Canceled()
    except PublishError as exc:
        db.update_publication(pub["id"], status="failed", error=str(exc), fix=exc.fix)
        db.update("scheduled_publications", item["id"], publication_id="")
        _handle_error(job, _item(item["id"]) or item, exc, settings)
    pub = db.get_publication(pub["id"]) or pub
    return finish(item, pub)


def finish(item: dict, pub: dict) -> dict:
    """Record exactly what the platform did."""
    item = _item(item["id"]) or item
    if pub["status"] == "done":
        info = pub.get("info") or {}
        if info.get("scheduled"):
            note = pub.get("message") or "Uploaded and scheduled on YouTube"
        elif info.get("locked_private"):
            note = f"Published as Private: the platform did not allow {item['privacy']}. {pub.get('message', '')}"
        else:
            note = pub.get("message") or "Published"
        _set(item, "published", note, "published", last_error="", fix="")
        state.resolve(f"review:{item['id']}")
        state.event("published", f"{item['platform']}: “{item['title'][:60]}” — {note[:160]}", ref_type="scheduled",
                    ref_id=item["id"], url=pub.get("url", ""))
        return {"url": pub.get("url", ""), "message": note}
    if pub["status"] == "action_needed":
        _action_needed(item, f"inbox:{item['id']}", "Finish the TikTok post in the app", pub.get("message", ""),
                       "Open the TikTok app, finish and post the draft, then link it in the Publish Center.")
        return {"message": pub.get("message", "")}
    if pub["status"] == "processing":
        _set(item, "publishing", pub.get("message") or "Uploaded; the platform is processing it", "processing")
        raise queue.Wait("processing", 120, "The platform is still processing the upload")
    if pub["status"] == "failed":
        raise queue.Retry(pub.get("error") or "The upload failed", pub.get("fix") or "")
    return {"message": pub.get("message", "")}

"""User-pasted links, stored as ordinary sources and durable identification jobs.

Local processing intent is separate from reuse/publishing rights. Identifying a video grants neither a license
nor permission to download it: the existing access resolver and publishing gates still decide those steps.

Posting a pasted video's clips needs your own statement for that one video ("Post the clips for me": you made it, or
its creator allows you to post clips of it), recorded as a rule for that source with the date (`set_posting`). Its
clips are then scheduled like any covered video's, and go out under the usual approvals. Nothing is inferred: without
that statement, or another rule that covers the video, the clips stay in your Library.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from .. import config, db, netguard
from ..publish.common import PublishError, asked_to_wait, client, retry_after
from . import access, providers, queue, quota, rights, state, verify
from .host import Job, handler

LINK_PRIORITY = 80
TOP_PRIORITY = 99  # Manual Clip now is 100. Claim order changes; a running GPU step is never interrupted.
STREAM_EXTENSIONS = (".m3u8", ".mpd")
SHORT_TIKTOK_HOSTS = ("vm.tiktok.com", "vt.tiktok.com")
STATUS_LABELS = {
    "waiting": "Waiting", "getting_video": "Getting video", "listening": "Listening to video",
    "finding_clips": "Finding clips", "making_clips": "Making clips", "final_check": "Final check",
    "ready": "Ready", "watching_live": "Watching live", "waiting_stream": "Waiting for stream",
    "finished": "Finished", "inaccessible": "Could not access video", "canceled": "Canceled",
    "failed": "Could not finish", "removed": "Removed",
}
POSTING_BASIS = ("You confirmed that you made this video, or that its creator allows you to post clips of it "
                 "(Autopilot → Add a video, {day})")


def _checked_redirect(url: str) -> str:
    """Resolve a short share link without allowing a redirect into the local network."""
    with client(20) as c:
        response = netguard.open_checked(c, url)
        try:
            if response.status_code != 200:
                raise ValueError("The share link could not be opened. Paste the video's full link instead.")
            # open_checked pins the connection to an IP, while retaining the actual host in the request.
            parts = urlsplit(str(response.url))
            host = response.request.headers.get("host") or parts.netloc
            return urlunsplit((parts.scheme, host, parts.path, parts.query, ""))
        finally:
            response.close()


def _direct_url(raw: str) -> str:
    """Normalize a direct link's spelling without changing signed or content-selecting query parameters."""
    parts = urlsplit(raw.strip())
    if parts.scheme not in netguard.STREAM or not parts.hostname or parts.username or parts.password:
        raise ValueError("Not a public video or stream URL")
    host = parts.hostname.lower().encode("idna").decode()
    netloc = f"[{host}]" if ":" in host else host
    if parts.port is not None and (parts.scheme, parts.port) not in (("http", 80), ("https", 443)):
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def canonical_url(raw: str) -> dict:
    """One safe public video identity; platform tracking links map to the same source."""
    value = raw.strip()
    if not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError("Paste a video or stream link (up to 4096 characters).")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise ValueError("That video link is not a valid URL.") from exc
    if parts.username or parts.password:
        raise ValueError("Use a public link without a username or password.")
    netguard.check(value, schemes=netguard.STREAM, allow_private=False)
    host = (parts.hostname or "").lower().encode("idna").decode()
    if host in SHORT_TIKTOK_HOSTS:
        value = _checked_redirect(value)
        parts = urlsplit(value)
        host, port = (parts.hostname or "").lower(), parts.port
        netguard.check(value, allow_private=False)
    youtube = verify.link_video("youtube", value)
    if youtube:
        video_id = youtube[0]
        return {"platform": "youtube", "external_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}", "title": "YouTube video"}
    tiktok = verify.link_video("tiktok", value)
    if tiktok:
        video_id, handle = tiktok
        return {"platform": "tiktok", "external_id": video_id,
                "url": f"https://www.tiktok.com/@{handle.lower()}/video/{video_id}", "title": "TikTok video"}
    if host in (*verify.YOUTUBE_HOSTS, "youtu.be", *verify.TIKTOK_HOSTS, *SHORT_TIKTOK_HOSTS):
        raise ValueError("Paste the link to one video or stream, rather than a channel or playlist.")
    normalized = _direct_url(value)
    live = parts.scheme.lower() not in netguard.HTTP or parts.path.lower().endswith(STREAM_EXTENSIONS)
    title = unquote(PurePosixPath(parts.path).name)[:120] or ("Live stream" if live else "Video link")
    return {"platform": "stream" if live else "url",
            "external_id": hashlib.sha256(normalized.encode()).hexdigest()[:32], "url": normalized,
            "title": title, "kind": "live" if live else "recorded"}


def _enqueue(source: dict) -> dict:
    return queue.enqueue("identify_link", {"source_id": source["id"]},
                         priority=int((source.get("intake") or {}).get("priority") or LINK_PRIORITY),
                         idem_key=f"identify:{source['id']}", ref=("source", source["id"]),
                         max_attempts=5, timeout_s=120, message="Checking the video link", revive=False)


def add(url: str, post: bool = False) -> dict:
    """Add a link. `post` is your statement that you may post clips of this video (see set_posting)."""
    fields = canonical_url(url)
    existing = db.select("sources", "platform = ? AND external_id = ?",
                         (fields["platform"], fields["external_id"]))
    source = existing[0] if existing else None
    if source is None and fields["platform"] in ("url", "stream"):
        # Older configured feeds and manually added sources use another ID hash. Keep their project, explicit
        # permissions and job history instead of creating a second source for exactly the same public link.
        for candidate in db.select("sources", "platform IN ('url', 'stream') AND url != ''", (), "created_at"):
            try:
                same = _direct_url(candidate["url"]) == fields["url"]
            except ValueError:
                continue
            if same:
                source = candidate
                break
    already_added = bool(source)
    if source is None:
        try:
            source = db.insert("sources", {**fields, "user_added": 1, "status": "queued",
                                           "status_note": "Checking the video link", "intake": {
                                               "original_url": url.strip(), "added_at": time.time(),
                                               "priority": LINK_PRIORITY}})
        except sqlite3.IntegrityError:  # simultaneous pastes of the same identity are one item
            source = db.select("sources", "platform = ? AND external_id = ?",
                               (fields["platform"], fields["external_id"]))[0]
            already_added = True
    was_user_added = bool(source.get("user_added"))
    meta = source.get("intake") or {}
    if not was_user_added or meta.get("removed"):
        db.update("sources", source["id"], user_added=1, intake={**meta, "original_url": url.strip(),
                  "added_at": meta.get("added_at") or time.time(), "priority": LINK_PRIORITY, "removed": False})
        source = db.fetch("sources", source["id"]) or source
    # Existing completed and canceled items are shown, never silently restarted by a duplicate paste.
    if not already_added or (not was_user_added and source["status"] not in ("analyzed", "weak", "ingesting",
                                                                          "analyzing", "canceled", "blocked") and
                             not (source.get("intake") or {}).get("canceled") and
                             not any(j["status"] in queue.ACTIVE for j in _jobs(source))):
        _enqueue(source)
    if already_added:
        for job in _jobs(source):
            if job["status"] in queue.ACTIVE and job["priority"] < LINK_PRIORITY:
                db.update("worker_jobs", job["id"], priority=LINK_PRIORITY)
    source = db.fetch("sources", source["id"]) or source
    if post:
        now = posting(source)
        if now["can_change"] and not now["on"]:  # a block, or coverage that already posts it, stays as it is
            set_posting(source["id"], True)
    return {"item": item(db.fetch("sources", source["id"]) or source), "already_added": already_added}


def posting(source: dict, settings: dict | None = None, all_rules: list[dict] | None = None) -> dict:
    """Whether this video's clips are posted, why, and whether you can change that here (only your own statement
    for this one video can be turned on or off here; a block or another rule is changed in Permissions & sources)."""
    meta = source.get("intake") or {}
    if meta.get("canceled") or meta.get("removed") or source.get("status") in ("canceled", "removed"):
        return {"on": False, "by_you": False, "can_change": False, "label": "Canceled: nothing is posted"}
    r = rights.evaluate(source, settings, all_rules)
    rule = db.fetch("source_rights", r["rule_id"]) if r["rule_id"] else None
    by_you = bool(rule and rule["scope"] == "source" and rule["status"] == rights.ALLOWLISTED)
    if r["status"] == rights.BLOCKED:
        return {"on": False, "by_you": False, "can_change": False,
                "label": "Not posted: blocked in Permissions & sources"}
    if r["auto_allowed"]:
        why = "you confirmed you may post it" if by_you else r["label"].lower()
        return {"on": True, "by_you": by_you, "can_change": by_you, "label": f"Clips are posted ({why})"}
    if by_you:  # Settings → Advanced turned off automatic use of allowlisted videos
        return {"on": False, "by_you": True, "can_change": True,
                "label": "Not posted: Settings → Advanced turns off posting allowlisted videos"}
    return {"on": False, "by_you": False, "can_change": True, "label": "Clips stay in your Library"}


def set_posting(source_id: str, on: bool) -> dict:
    """Your statement for this one video. On: you made it, or its creator allows you to post clips of it, recorded as
    an Allowlisted rule for this source with the date; its finished clips are then planned and posted like any covered
    video's (YouTube by itself only with automatic publishing on, TikTok always after your OK). Off: the rule is
    removed and upcoming posts that have not started uploading are canceled; the clips stay in your Library."""
    source = db.fetch("sources", source_id)
    if not source or not source.get("user_added") or (source.get("intake") or {}).get("removed"):
        raise LookupError("Added video not found")
    now = posting(source)
    if not now["can_change"]:
        raise ValueError(f"{now['label']}. Change it in Autopilot → Permissions & sources.")
    if on:
        rights.confirm(source_id, rights.ALLOWLISTED, POSTING_BASIS.format(day=time.strftime("%Y-%m-%d")))
    else:
        for rule in db.select("source_rights", "scope = 'source' AND value = ? AND status = ? AND active = 1",
                              (source_id, rights.ALLOWLISTED)):
            rights.remove_rule(rule["id"])
        rights.apply(db.fetch("sources", source_id) or source)
        _cancel_posts(source)
    state.event("link_posting", f"{source['title'][:80]}: clips {'are posted' if on else 'are no longer posted'} "
                                "(your choice)", ref_type="source", ref_id=source_id)
    return item(db.fetch("sources", source_id) or source)


def identify(source: dict, settings: dict) -> dict:
    """Read only public/platform metadata; no cookies, authentication bypass or DRM handling."""
    netguard.check(source["url"], schemes=netguard.STREAM, allow_private=False)
    if source["platform"] == "youtube":
        api = providers.YouTubeDiscovery(settings)
        found = api._get("videos.list", "videos", {"part": providers.VIDEO_PARTS,
                                                   "id": source["external_id"]}, ttl=30)
        video = next((v for v in found.get("items") or [] if v.get("id") == source["external_id"]), None)
        if not video or (video.get("status") or {}).get("privacyStatus") == "private":
            raise queue.Fail("The video is private, unavailable, or no longer exists.")
        snippet = video.get("snippet") or {}
        live = video.get("liveStreamingDetails") or {}
        live_status = ("ended" if live.get("actualEndTime") else "live" if
                       snippet.get("liveBroadcastContent") == "live" or live.get("actualStartTime") else
                       "upcoming" if snippet.get("liveBroadcastContent") == "upcoming" else "")
        fields = {"title": str(snippet.get("title") or source["title"])[:120],
                  "channel_id": snippet.get("channelId") or "",
                  "channel_title": snippet.get("channelTitle") or "",
                  "license": (video.get("status") or {}).get("license") or "",
                  "duration": providers.iso_duration((video.get("contentDetails") or {}).get("duration")),
                  "published_at": providers.iso_time(snippet.get("publishedAt")),
                  "kind": "live" if live_status in ("live", "upcoming") else "recorded",
                  "live_status": live_status,
                  "scheduled_at": providers.iso_time(live.get("scheduledStartTime"))}
        fields["channel_check"] = verify.judge({**source, **fields}, fields["channel_id"],
                                               fields["channel_title"], verify.YOUTUBE_DATA)
        return fields
    if source["platform"] == "tiktok":
        from ..publish import tiktok

        with client(20) as c:
            response = c.get(tiktok.OEMBED_URL, params={"url": source["url"]})
        asked = retry_after(response)
        if asked is not None and (response.status_code == 429 or response.status_code >= 500):
            raise queue.Wait("platform", asked, "TikTok asked to wait before checking this video.")
        if response.status_code == 429 or response.status_code >= 500:
            raise queue.Retry("TikTok is temporarily unavailable.")
        if response.status_code != 200:
            raise queue.Fail("The TikTok video is private, unavailable, or no longer exists.")
        data = response.json()
        if not isinstance(data, dict) or str(data.get("embed_product_id") or "") != source["external_id"]:
            raise queue.Retry("TikTok returned an unreadable answer. The video will be checked again.")
        author = str(data.get("author_unique_id") or "").lstrip("@")
        if not verify.TIKTOK_HANDLE.fullmatch(author):
            raise queue.Retry("TikTok did not identify the video's creator.")
        fields = {"title": str(data.get("title") or source["title"])[:120], "channel_id": f"@{author}",
                  "channel_title": str(data.get("author_name") or author)[:120],
                  "kind": "recorded", "live_status": ""}
        fields["channel_check"] = verify.judge({**source, **fields}, fields["channel_id"],
                                               fields["channel_title"], verify.TIKTOK_EMBED)
        return fields
    if source["platform"] == "stream":
        return {"kind": "live", "live_status": "live"}
    # Read headers only. The actual media download remains bounded and checked by Clip Hunter.
    with client(20) as c:
        response = netguard.open_checked(c, source["url"])
        try:
            asked = retry_after(response)
            if asked is not None and (response.status_code == 429 or response.status_code >= 500):
                raise queue.Wait("server", asked, "The video server asked to wait before checking this video.")
            if response.status_code == 429 or response.status_code >= 500:
                raise queue.Retry("The video server is temporarily unavailable.")
            if response.status_code != 200:
                raise queue.Fail("Video found, but ClipFoundry cannot access the video file.")
            content = response.headers.get("content-type", "").lower().split(";", 1)[0]
            if content in ("application/vnd.apple.mpegurl", "application/x-mpegurl", "application/dash+xml"):
                return {"kind": "live", "live_status": "live"}
            if not content.startswith(("video/", "application/octet-stream", "binary/", "application/ogg")):
                raise queue.Fail("Video found, but ClipFoundry cannot access the video file. "
                                 "Use a direct public video or stream link.")
        finally:
            response.close()
    return {"kind": "recorded", "live_status": ""}


def _unavailable(source: dict, error: Exception) -> None:
    db.update("sources", source["id"], status="failed", error=str(error)[:500], status_note=str(error)[:300])
    state.event("link_unavailable", f"{source['title'][:80]}: {error}", "warning", ref_type="source",
                ref_id=source["id"])


@handler("identify_link")
def identify_link(job: Job) -> dict:
    source = db.fetch("sources", job.payload.get("source_id", ""))
    if not source:
        raise queue.Fail("The added video is no longer available.")
    meta = source.get("intake") or {}
    if meta.get("canceled") or meta.get("removed"):
        return {"message": "Canceled"}
    try:
        settings = db.get_settings()
        fields = identify(source, settings)
        scheduled_at = fields.pop("scheduled_at", None)
        fresh = db.fetch("sources", source["id"]) or source
        meta = fresh.get("intake") or {}
        job.check()
        if meta.get("canceled") or meta.get("removed"):
            return {"message": "Canceled"}
        db.update("sources", source["id"], **fields, intake={**meta, "identified": True,
                  "scheduled_at": scheduled_at}, error="")
        source = rights.apply(db.fetch("sources", source["id"]) or source, settings)
        r = rights.evaluate(source, settings)
        if not rights.local_allowed(source, r, settings):
            raise queue.Fail("This video is blocked by your content permissions.")
        if source["live_status"] == "upcoming":
            db.update("sources", source["id"], status="queued", status_note="Waiting for stream")
            delay = max(30.0, min(300.0, (scheduled_at or time.time() + 300) - time.time()))
            raise queue.Wait("stream_start", delay, "Waiting for the stream to start")
        found = access.resolve(source, settings)
        db.update("sources", source["id"], access=access.record(source, found))
        if not found["ok"]:
            raise queue.Fail("Video found, but ClipFoundry cannot access the video file. " + found["detail"])
        live = source["kind"] == "live" and source["live_status"] != "ended"
        kind, prefix = ("live_capture", "live") if live else ("hunt_source", "hunt")
        project = db.get_project(source.get("project_id") or "")
        if source["live_status"] == "ended" and project:
            live_state = config.projects_dir() / project["id"] / "live" / "state.json"
            if live_state.is_file():
                # The recorder drains any CSV tail and joins existing segments, even if the last app stopped
                # before it recorded that the stream ended. The canonical post-live job is enqueued afterwards.
                kind, prefix = "live_capture", "live"
        db.update("sources", source["id"], status="queued", status_note="Waiting for a safe turn")
        result = queue.enqueue(kind, {"source_id": source["id"]},
                               priority=int(meta.get("priority") or LINK_PRIORITY),
                               idem_key=f"{prefix}:{source['id']}", ref=("source", source["id"]),
                               max_attempts=5, timeout_s=(24 if live else 6) * 3600, revive=False)
        return {"source_id": source["id"], "job_id": result["id"], "message": "Added to Autopilot"}
    except queue.Wait:
        raise
    except providers.Unavailable as exc:
        error = queue.Fail("YouTube needs a connected account or API key to check this video.")
        _unavailable(source, error)
        raise error from exc
    except quota.QuotaDenied as exc:
        raise queue.Wait("quota", max(1.0, exc.retry_at - time.time()), "Waiting for YouTube to allow another check")
    except PublishError as exc:
        asked = asked_to_wait(exc)
        if asked is not None:
            raise queue.Wait("platform", asked, "The platform asked to wait before checking this video") from exc
        if exc.code in ("network", "response"):
            raise queue.Retry(str(exc), exc.fix) from exc
        _unavailable(source, exc)
        raise queue.Fail(str(exc), exc.fix) from exc
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, netguard.UnsafeUrl):
            _unavailable(source, exc)
            raise queue.Fail("The video link is not a safe public address.") from exc
        raise queue.Retry("Could not check the video yet. It will be tried again.") from exc
    except queue.Fail as exc:
        _unavailable(source, exc)
        raise


def _jobs(source: dict) -> list[dict]:
    return db.select("worker_jobs", "(ref_type = 'source' AND ref_id = ?) OR "
                     "json_extract(payload, '$.source_id') = ? OR (ref_type = 'clip' AND kind != 'publish' AND "
                     "ref_id IN (SELECT id FROM clips WHERE project_id = ?))",
                     (source["id"], source["id"], source.get("project_id") or ""), "created_at DESC")


def _failures(source: dict, jobs: list[dict]) -> list[dict]:
    """Historical failed attempts do not turn an already completed local video back into an access failure."""
    latest = {}
    for job in jobs:
        key = (job["kind"], (job.get("payload") or {}).get("clip_id") or "")
        latest.setdefault(key, job)
    failures = []
    for (kind, clip_id), job in latest.items():
        if job["status"] != "failed":
            continue
        if not clip_id and source["status"] in ("analyzed", "weak"):
            continue
        if clip_id and any(j["status"] == "completed" and j["kind"] == "quality_check" and
                           (j.get("payload") or {}).get("clip_id") == clip_id and
                           j["updated_at"] >= job["updated_at"] for j in jobs):
            continue
        failures.append(job)
    return failures


def item(source: dict, all_rules: list[dict] | None = None) -> dict:
    meta = source.get("intake") or {}
    jobs = _jobs(source)
    active = sorted((j for j in jobs if j["status"] in queue.ACTIVE),
                    key=lambda j: (j["status"] == "running", j["created_at"]), reverse=True)
    current = active[0] if active else None
    failures = _failures(source, jobs)
    progress, detail = 0.0, source.get("status_note") or ""
    status = "waiting"
    if meta.get("removed"):
        status = "removed"
    elif meta.get("canceled") or source["status"] == "canceled":
        status = "canceled"
    elif current:
        progress = float(current.get("progress") or 0)
        detail = current.get("error") or current.get("message") or detail
        kind, stage = current["kind"], current.get("stage") or ""
        if source.get("live_status") == "upcoming":
            status = "waiting_stream"
        elif kind == "live_capture" and source.get("live_status") == "live":
            status = "watching_live"
        elif current["status"] != "running":
            status = "waiting"
        elif kind == "live_capture":
            status = "watching_live"
        elif kind == "hunt_source":
            status = "listening" if stage == "transcribe" else "getting_video"
        elif kind in ("analyze_source", "post_live", "regenerate_clip"):
            status = "making_clips" if stage == "render" or kind == "regenerate_clip" else "finding_clips"
        elif kind == "quality_check":
            status = "final_check"
        elif kind == "package_clip":
            status = "making_clips"
        if kind == "post_live":
            detail = "Stream ended — checking the full recording"
        elif kind == "live_capture":
            detail = ("Found a strong moment — making clip" if stage == "render" else
                      "Listening for good moments")
    elif source["status"] == "failed" or failures:
        project = db.get_project(source.get("project_id") or "")
        has_media = bool(project and project.get("source_path") and Path(project["source_path"]).is_file())
        access_failure = (not has_media and source["status"] not in ("analyzed", "weak")) or any(
            j["kind"] == "identify_link" for j in failures)
        status, detail = "inaccessible" if access_failure else "failed", source.get("error") or next(
            (j.get("error") for j in failures), "Could not finish this video")
    elif source["status"] in ("analyzed", "weak"):
        status, progress = ("ready" if source.get("clips_selected") else "finished"), 1.0
    elif source.get("live_status") == "upcoming":
        status = "waiting_stream"
    can_remove = not source.get("project_id") and source["status"] not in ("ingesting", "analyzing")
    return {"id": source["id"], "title": source["title"], "url": source["url"], "platform": source["platform"],
            "kind": source["kind"], "live_status": source["live_status"], "status": status,
            "status_label": STATUS_LABELS[status], "detail": detail, "progress": progress,
            "project_id": source.get("project_id") or "", "added_at": meta.get("added_at") or source["created_at"],
            "scheduled_at": meta.get("scheduled_at"), "can_remove": can_remove,
            "can_cancel": bool(active) and status not in ("canceled", "removed"),
            "can_retry": status in ("inaccessible", "failed", "canceled", "removed")
            and not any(j["status"] == "running" for j in jobs),
            "can_prioritize": bool(active) and status != "canceled",
            "posting": posting(source, all_rules=all_rules)}


def links() -> list[dict]:
    all_rules = rights.rules()  # read once for the whole list
    return [item(s, all_rules) for s in db.select("sources", "user_added = 1", (), "created_at DESC", 200)
            if not (s.get("intake") or {}).get("removed")]


def action(source_id: str, operation: str) -> dict:
    source = db.fetch("sources", source_id)
    if not source or not source.get("user_added"):
        raise LookupError("Added video not found")
    meta = source.get("intake") or {}
    view = item(source)
    if operation in ("cancel", "remove"):
        if operation == "remove" and not view["can_remove"]:
            raise ValueError("This video has started processing. Cancel it to stop future work.")
        # Save the source flag first, so an identifier finishing concurrently cannot schedule another stage.
        previous_status = ((meta.get("previous_status") or source["status"]) if meta.get("canceled") else
                           source["status"])
        db.update("sources", source_id, intake={**meta, "canceled": True, "removed": operation == "remove",
                  "previous_status": previous_status},
                  status="canceled", status_note="Canceled by you")
        for job in _jobs(source):
            if job["status"] in queue.ACTIVE:
                queue.cancel(job["id"])
        _cancel_posts(source)
    elif operation == "retry":
        if not view["can_retry"]:
            raise ValueError("This video is already waiting, processing, or finished.")
        retryable = _resume_jobs(source)
        previous = meta.get("previous_status") or source["status"]
        status = previous if previous in ("analyzed", "weak") else "queued"
        db.update("sources", source_id, intake={**meta, "canceled": False, "removed": False, "previous_status": ""},
                  status=status, status_note="Waiting", error="")
        # Resume the most advanced usable stage. Upstream/downstream stages of one video never restart together.
        for job in retryable:
            db.update("worker_jobs", job["id"], status="queued", attempts=0, cancel_requested=0, run_after=time.time(),
                      finished_at=None, error="", fix="", message="Queued again", lease_owner="", lease_until=0)
        if not retryable and status == "queued":
            identifier = _enqueue(db.fetch("sources", source_id) or source)
            db.update("worker_jobs", identifier["id"], status="queued", attempts=0, cancel_requested=0,
                      run_after=time.time(), finished_at=None, error="", fix="", lease_owner="", lease_until=0)
    elif operation == "prioritize":
        if not view["can_prioritize"]:
            raise ValueError("Only waiting or active videos can be moved to the top.")
        for other in db.select("sources", "user_added = 1 AND id != ?", (source_id,)):
            other_meta = other.get("intake") or {}
            if other_meta.get("priority") == TOP_PRIORITY:
                db.update("sources", other["id"], intake={**other_meta, "priority": TOP_PRIORITY - 1})
        db.execute("UPDATE worker_jobs SET priority = ? WHERE priority = ? AND status IN ('queued','waiting',"
                   "'retrying') AND ref_id != ?", (TOP_PRIORITY - 1, TOP_PRIORITY, source_id))
        db.update("sources", source_id, intake={**meta, "priority": TOP_PRIORITY})
        for job in _jobs(source):
            if job["status"] in queue.ACTIVE:
                db.update("worker_jobs", job["id"], priority=TOP_PRIORITY)
    else:
        raise ValueError("That video action is not supported.")
    return item(db.fetch("sources", source_id) or source)


def _resume_jobs(source: dict) -> list[dict]:
    jobs = _jobs(source)
    project = db.get_project(source.get("project_id") or "")
    pdir = config.projects_dir() / project["id"] if project else None
    prior = (source.get("intake") or {}).get("previous_status") or source["status"]
    source_ranks = {"identify_link": 0, "hunt_source": 1, "live_capture": 1,
                    "analyze_source": 2, "post_live": 2}
    stages = [j for j in jobs if j["kind"] in source_ranks and j["status"] in ("failed", "canceled")]
    if stages and prior not in ("analyzed", "weak"):
        selected = max(stages, key=lambda j: (source_ranks[j["kind"]], j["created_at"]))
        if selected["kind"] == "analyze_source" and not (pdir and all((pdir / name).is_file() for name in
                ("transcript.json", "loudness.json", "candidates.json"))):
            selected = next((j for j in jobs if j["kind"] == "hunt_source"), None)
        elif selected["kind"] == "post_live" and not (project and project.get("source_path") and
                                                        Path(project["source_path"]).is_file()):
            selected = next((j for j in jobs if j["kind"] == "live_capture"), None)
        if selected:
            return [selected]
    # Different clips can resume independently; each clip resumes only its latest unfinished stage.
    pending = {}
    ranks = {"regenerate_clip": 0, "package_clip": 1, "quality_check": 2}
    for job in jobs:
        clip_id = (job.get("payload") or {}).get("clip_id") or ""
        if clip_id and job["kind"] in ranks and job["status"] in ("failed", "canceled"):
            prev = pending.get(clip_id)
            if not prev or (job["updated_at"], ranks[job["kind"]]) > (prev["updated_at"], ranks[prev["kind"]]):
                pending[clip_id] = job
    return list(pending.values())


def _cancel_posts(source: dict) -> None:
    """Cancel future posts while retaining completed local clips and any uncertain platform outcome."""
    from . import scheduler

    for post in db.select("scheduled_publications", "clip_id IN (SELECT id FROM clips WHERE project_id = ?) AND "
                          "status IN ('awaiting_approval', 'approved', 'blocked', 'action_needed', 'failed')",
                          (source.get("project_id") or "",)):
        publication = db.fetch("publications", post.get("publication_id") or "")
        if publication and publication["status"] not in ("queued", "failed", "cancelled"):
            continue  # accepted bytes, a pending platform answer, or an inbox draft stays recorded honestly
        try:
            scheduler.cancel(post["id"], "Canceled with the video by you")
        except ValueError:
            continue  # a publisher claimed it concurrently; the publishing gate rechecks the source flag
        state.resolve(f"publish:{post['id']}")

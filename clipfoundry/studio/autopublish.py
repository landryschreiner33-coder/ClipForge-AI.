"""After a ClipForge clip renders under a "Make & upload clips" request: check it, then upload it once per
YouTube destination the owner chose for that input. TikTok destinations wait for the owner's OK on each post.

The upload goes through the same Publish path as the button (connection, audience, kids answer, exact file hash,
quality gate, Pause publishing, per-account duplicate checks). A destination that already has a publication for this
clip is never uploaded again, so a re-render never repeats a post; new bytes need their own explicit request.
Every outcome is recorded per destination on the clip, in words.
"""
from __future__ import annotations

import logging
import time

from fastapi import HTTPException

from .. import db
from ..cloud import principal
from . import eligibility

log = logging.getLogger(__name__)


def _record(clip: dict, cid: str, state: str, text: str) -> None:
    clip = db.get_clip(clip["id"]) or clip
    analysis = dict(clip.get("analysis") or {})
    dests = {d["connection_id"]: d for d in analysis.get("destinations") or []}
    acc = db.get_connection(cid) or {}
    dests[cid] = {"connection_id": cid, "platform": acc.get("platform", ""),
                  "account": acc.get("nickname") or acc.get("display_name") or "", "state": state, "text": text,
                  "at": time.time()}
    analysis["destinations"] = list(dests.values())
    db.update_clip(clip["id"], analysis=analysis)


def after_render(clip_id: str) -> None:
    from ..autopilot import gate
    from ..publish import routes as publish_routes
    from ..publish.common import PublishError

    clip = db.get_clip(clip_id)
    if not clip or clip["status"] != "ready":
        return
    project = db.get_project(clip["project_id"]) or {}
    request = project.get("destinations") or {}
    if not request:
        return
    token = principal.bind(principal.Principal(user_id="studio-worker",
                                               workspace_id=project.get("workspace_id") or "local"))
    try:
        for cid in request.get("review") or []:
            _record(clip, cid, "review", "Waiting for your OK on this post (TikTok asks for it on every post).")
        auto = request.get("auto") or []
        if not auto:
            return
        settings = db.get_settings()
        report = gate.run(clip, settings)
        for cid in auto:
            if any(p.get("connection_id") == cid for p in db.list_publications(clip_id, "youtube")):
                continue  # this destination already has its post for this clip: never upload twice
            acc = db.get_connection(cid)
            if not acc or acc["status"] != "connected":
                _record(clip, cid, "needs_reconnect", "This account needs Reconnect; other accounts continue.")
                continue
            if acc["external_id"] != (request.get("accounts") or {}).get(cid):
                _record(clip, cid, "held", "The account behind this destination changed. Review the post.")
                continue
            info = clip.get("render_info") or {}
            fit = eligibility.youtube(float(clip.get("duration") or 0), int(info.get("width") or 1080),
                                      int(info.get("height") or 1920))
            if not fit["eligible"]:
                _record(clip, cid, "too_long", fit["text"])
                continue
            if report.get("status") != "passed":
                _record(clip, cid, "held", "Did not pass the final check: " + "; ".join(report.get("blockers")
                                                                                     or [])[:300])
                continue
            post = clip.get("post") or {}
            body = publish_routes.PublishBody(
                title=(post.get("title") or clip.get("title") or "")[:100],
                description=post.get("description") or clip.get("caption_text", "")[:4500],
                tags=list(post.get("tags") or [])[:15], privacy=request.get("privacy") or "private",
                made_for_kids=request.get("made_for_kids"), confirm=True, connection_id=cid,
                expected_account_id=acc["external_id"])
            try:
                pub = publish_routes.publish(clip_id, "youtube", body)
                _record(clip, cid, "queued", f"Uploading as {fit['label']}.")
                log.info("studio upload %s queued for %s", pub["id"], cid)
            except (PublishError, HTTPException) as exc:
                _record(clip, cid, "held", str(getattr(exc, "detail", None) or exc)[:300])
    finally:
        principal.reset(token)

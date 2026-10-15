"""Bounded, exact-post YouTube review. A batch click never grants permission for future work."""
from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict

from .. import config, db
from ..pipeline import artifact
from ..publish import audience
from ..publish.common import PublishError
from . import gate, packaging, queue, rights, scheduler

MAX_ITEMS = 50
PREVIEW_SECONDS = 10 * 60
MAX_PREVIEWS = 64
REUSE_OPTIONS = (
    {"value": "owned", "label": "My original content", "basis":
     "I created this content and have permission for any other material included in this clip."},
    {"value": "creator_permission", "label": "Creator permission", "basis":
     "The creator has given me permission to reuse this content, including the material in this clip."},
    {"value": "licensed", "label": "License allows this use", "basis":
     "I have checked a license that permits this reuse, including any music or other material in this clip."},
    {"value": "public_domain", "label": "Public domain", "basis":
     "I have checked that this content and the material inside this clip are in the public domain."},
    {"value": "custom", "label": "Other permission", "basis": ""},
)
_previews: OrderedDict[str, dict] = OrderedDict()
_lock = threading.Lock()


def resolve_reuse_basis(kind: str = "custom", basis: str = "") -> str:
    """Presets record the owner's assertion, never verified ownership or a reusable source rule."""
    option = next((row for row in REUSE_OPTIONS if row["value"] == kind), None)
    if option is None:
        raise ValueError("Choose one of the shown reuse permission options")
    return option["basis"] if kind != "custom" else str(basis).strip()


def _prune(now: float) -> None:
    for token, entry in list(_previews.items()):
        if entry["expires_at"] <= now and not entry.get("busy"):
            _previews.pop(token, None)
    while len(_previews) >= MAX_PREVIEWS:
        oldest = next((key for key, value in _previews.items() if not value.get("busy")), None)
        if oldest is None:
            raise ValueError("Other approvals are still running. Try again shortly.")
        _previews.pop(oldest, None)


def _inspect(item: dict, settings: dict, *, sha: str | None = None) -> tuple[dict, dict]:
    """Read and check actual current inputs. Supplying an already freshly computed SHA avoids hashing under SQL."""
    supplied_sha = sha is not None
    if item.get("platform") != "youtube":
        raise ValueError("TikTok needs its own post review. Open this post to approve it individually.")
    if item.get("status") not in ("awaiting_approval", "approved"):
        raise ValueError("This post is no longer waiting for review.")
    if item.get("replaces"):
        raise ValueError("This post replaces another planned clip. Review that change on its individual post page.")
    if not scheduler.publication_unstarted(item):
        raise ValueError("This upload has started or needs a status check. Open its individual review.")
    pending = ", ".join("?" for _ in queue.ACTIVE)
    if db.scalar("SELECT COUNT(*) FROM worker_jobs WHERE worker = 'publisher' AND "
                 f"status IN ({pending}) AND "
                 "((ref_type = 'scheduled' AND ref_id = ?) OR json_extract(payload, '$.scheduled_id') = ?)",
                 (*queue.ACTIVE, item["id"], item["id"])):
        raise ValueError("This post has upload work pending. Open its individual review to check its status.")
    if item["status"] == "approved" and sha is None and not scheduler.approval_problem(item):
        raise ValueError("This post is already approved.")
    account = db.get_account("youtube") or {}
    if not account.get("account_id") or not account.get("has_tokens"):
        raise ValueError("Connect your YouTube account before approving these posts.")
    clip, source = rights._post_source(item)
    if not clip or clip.get("status") != "ready":
        raise ValueError("The clip is missing or not rendered.")
    if rights._stopped(source) or (source and rights.evaluate(source, settings)["status"] == rights.BLOCKED):
        raise ValueError("This source is blocked or canceled.")
    path, version, _ = artifact.active(clip)
    if clip.get("active_version") and version != clip["active_version"]:
        raise ValueError("The selected clip version is missing or not rendered.")
    sha = sha if sha is not None else scheduler.video_sha256(path)
    if not sha:
        raise ValueError("The rendered video file is missing or cannot be read.")
    report = gate.report_for(clip)
    if not report or report.get("artifact_sha256") != sha:
        raise ValueError("The exact video needs a final quality check before it can be approved.")
    if not gate.context_valid(report, clip, settings):
        raise ValueError("The source's reuse terms changed. Wait for a fresh final check, then review again.")
    if report.get("status") != "passed":
        raise ValueError("The clip did not pass its final quality check. Open it to fix the reported problem.")
    metadata = (report.get("metadata") or {}).get("youtube") or {}
    if metadata.get("status") != "passed" or metadata.get("stale"):
        raise ValueError("This post's text needs a passing final check.")
    credit = rights.current_attribution(source, settings)
    if packaging.attribution_problem(item, "youtube", credit):
        raise ValueError("Add the required source credit in this post's individual review first.")
    heard = " ".join(packaging.clip_sentences(clip)[0])
    problems = packaging.validate({k: item.get(k) for k in ("title", "description", "tags")}, heard,
                                  allowed_lines=[credit], required_attribution=credit, platform="youtube")
    if problems:
        raise ValueError("Review this post's text first: " + "; ".join(problems[:2]))
    options = item.get("options") or {}
    # Validate the destination without choosing a COPPA answer for the owner.
    scheduler.check_platform({**item, "options": {**options, "made_for_kids":
                                                 False if options.get("made_for_kids") is None else
                                                 options["made_for_kids"]}})
    info = rights.review_info(item, settings) if not supplied_sha else {}
    binding = rights._confirmation_binding(item, settings, sha)
    fingerprint = {"binding": binding, "path": path, "status": item["status"],
                   "planned_at": item.get("planned_at"), "replaces": item.get("replaces"),
                   "metadata_id": item.get("metadata_id"), "publication_id": item.get("publication_id"),
                   "audience": item.get("audience"), "options": options,
                   "approval": item.get("approval"), "reuse_confirmation": item.get("reuse_confirmation"),
                   "destination": audience.destination("youtube", settings),
                   "auto_publish": bool(settings.get("autopilot_auto_publish")),
                   "review_before_publish": rights.review_before_publish(settings),
                   "category": settings.get("youtube_category_id") or "22",
                   "report": {k: report.get(k) for k in ("id", "status", "artifact_sha256", "coverage", "metadata")}}
    refresh_confirmation = bool(rights._confirmation_record(item)) and (
        not info.get("confirmed") or options.get("made_for_kids") is None)
    return fingerprint, {"needs_reuse_confirmation": bool(info.get("required") and not info.get("confirmed")) or
                         refresh_confirmation,
                         "needs_made_for_kids": options.get("made_for_kids") is None}


def preview(ids: list[str]) -> dict:
    if not ids or len(ids) > MAX_ITEMS or len(set(ids)) != len(ids) or any(
            not isinstance(value, str) or not value or len(value) > 100 for value in ids):
        raise ValueError("Select between 1 and 50 different posts to review together.")
    settings = db.get_settings()
    entries, shown = {}, []
    for item_id in ids:
        item = db.fetch("scheduled_publications", item_id)
        row = {"id": item_id, "eligible": False, "reason": "", "item": item,
               "needs_reuse_confirmation": False, "needs_made_for_kids": False}
        try:
            if not item:
                raise ValueError("This scheduled post no longer exists.")
            fingerprint, info = _inspect(item, settings)
            entries[item_id] = {"fingerprint": artifact.sha256_json(fingerprint), "details": fingerprint,
                                "info": info}
            row.update(eligible=True, **info)
        except (ValueError, OSError, PublishError) as exc:
            row["reason"] = str(exc)
        shown.append(row)
    now = time.time()
    token = secrets.token_urlsafe(32)
    with _lock:
        _prune(now)
        _previews[token] = {"expires_at": now + PREVIEW_SECONDS, "profile": str(config.db_path().resolve()),
                            "ids": list(ids), "entries": entries,
                            "skipped": {row["id"]: row["reason"] for row in shown if not row["eligible"]}}
    account = db.get_account("youtube") or {}
    return {"token": token, "expires_at": now + PREVIEW_SECONDS, "items": shown,
            "eligible_ids": list(entries), "account": {"id": account.get("account_id") or "",
                                                       "display_name": account.get("display_name") or ""},
            "reuse_options": list(REUSE_OPTIONS), "timezone": settings.get("autopilot_timezone"),
            "auto_publish": bool(settings.get("autopilot_auto_publish"))}


def approve(token: str, *, confirm: bool = False, reuse_confirmed: bool = False,
            reuse_kind: str = "custom", reuse_basis: str = "", made_for_kids: bool | None = None) -> dict:
    if not confirm:
        raise ValueError("Review the selected posts and confirm this approval first.")
    basis = resolve_reuse_basis(reuse_kind, reuse_basis)
    if len(basis) > 4000:
        raise ValueError("Keep the permission explanation within 4,000 characters.")
    request_hash = artifact.sha256_json({"confirm": confirm, "reuse_confirmed": reuse_confirmed,
                                         "reuse_kind": reuse_kind, "reuse_basis": basis,
                                         "made_for_kids": made_for_kids})
    with _lock:
        entry = _previews.get(token)
        if not entry or entry["expires_at"] <= time.time() or entry["profile"] != str(config.db_path().resolve()):
            raise ValueError("This review expired or the app restarted. Preview the selection again before approving.")
        if entry.get("result") is not None:
            if entry["request_hash"] != request_hash:
                raise ValueError("This review was already used. Preview the selection again to change your answers.")
            return entry["result"]
        if entry.get("busy"):
            raise ValueError("This selection is being approved. Wait for its result before retrying.")
        entry["busy"] = True
    results = []
    try:
        for item_id in entry["ids"]:
            expected = entry["entries"].get(item_id)
            if expected is None:
                results.append({"id": item_id, "status": "skipped", "reason": entry["skipped"][item_id]})
                continue
            try:
                item = db.fetch("scheduled_publications", item_id)
                if not item:
                    raise ValueError("This post was removed. Preview the selection again.")
                actual, info = _inspect(item, db.get_settings())
                if artifact.sha256_json(actual) != expected["fingerprint"]:
                    raise ValueError("This post, video, source or destination changed. Preview the selection again.")
                if info["needs_reuse_confirmation"] and (not reuse_confirmed or not basis):
                    raise ValueError("Confirm your reuse permission and choose its basis for these selected posts.")
                if info["needs_made_for_kids"] and made_for_kids is None:
                    raise ValueError("Choose whether the selected videos with no saved answer are made for kids.")
                options = dict(item.get("options") or {})
                if info["needs_made_for_kids"]:
                    options["made_for_kids"] = made_for_kids

                def guard(updated: dict, approval: dict, current: dict) -> None:
                    fresh, _ = _inspect(current, db.get_settings(), sha=approval["video_sha256"])
                    if artifact.sha256_json(fresh) != expected["fingerprint"]:
                        raise ValueError("This post changed while approving it. Preview the selection again.")
                    if updated["options"] != options:
                        raise ValueError("The post's settings changed. Preview the selection again.")

                scheduler.approve(item_id, {"options": options},
                                  reuse_confirmed=info["needs_reuse_confirmation"] and reuse_confirmed,
                                  reuse_basis=basis, review_guard=guard)
                results.append({"id": item_id, "status": "approved", "reason": "Approved by you."})
            except (ValueError, OSError, PublishError) as exc:
                results.append({"id": item_id, "status": "skipped", "reason": str(exc)})
        result = {"results": results, "approved": sum(row["status"] == "approved" for row in results),
                  "skipped": sum(row["status"] == "skipped" for row in results)}
        with _lock:
            entry.update(result=result, request_hash=request_hash)
        return result
    finally:
        with _lock:
            entry["busy"] = False

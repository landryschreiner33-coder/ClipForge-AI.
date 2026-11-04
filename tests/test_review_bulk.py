"""One batch click approves only the shown exact YouTube posts, without a future upload grant."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from quality_stub import passed_report
from test_autopilot_scheduler import make_clip


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_tiktok": False,
                      "autopilot_review_before_publish": True})
    db.save_account("youtube", tokens={"access_token": "fake-token"}, account_id="UCbulk-review",
                    display_name="Review channel")
    bulk_review._previews.clear()
    return tmp_path


def draft(data, name="A complete thought worth sharing", *, unknown=True, kids=None):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    source = db.insert("sources", {"platform": "local", "external_id": str(time.time_ns()),
                                   "title": name, "status": "analyzed"}) if unknown else None
    clip = make_clip(data, name, 90, source=source)
    for meta in db.select("metadata_candidates", "clip_id = ?", (clip["id"],)):
        db.update("metadata_candidates", meta["id"], description=name, tags=[])
    passed_report(clip)
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 1
    item = db.select("scheduled_publications", "clip_id = ?", (clip["id"],))[0]
    if kids is not None:
        db.update("scheduled_publications", item["id"], options={"made_for_kids": kids})
        item = db.fetch("scheduled_publications", item["id"])
    return item, clip, source


def accept(token, **fields):
    from clipfoundry.autopilot import bulk_review

    return bulk_review.approve(token, confirm=True, reuse_confirmed=True, reuse_kind="owned",
                               made_for_kids=False, **fields)


def test_batch_keeps_individual_assertions_and_schedule_without_a_future_grant(data):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, rights, scheduler

    first, _, source = draft(data)
    second, _, _ = draft(data, "This second complete thought also stands alone", kids=True)
    preview = bulk_review.preview([first["id"], second["id"]])
    assert all(row["eligible"] and row["needs_reuse_confirmation"] for row in preview["items"])
    assert preview["items"][0]["needs_made_for_kids"]
    assert not preview["items"][1]["needs_made_for_kids"]
    assert not db.select("publish_consents")
    assert all(item["status"] == "awaiting_approval" for item in db.select("scheduled_publications"))
    result = accept(preview["token"])
    assert result["approved"] == 2 and result["skipped"] == 0
    for original in (first, second):
        item = db.fetch("scheduled_publications", original["id"])
        assert item["status"] == "approved" and item["approval"]["by"] == "you"
        assert scheduler.approval_valid(item)
        assert item["planned_at"] == original["planned_at"]
        assert item["privacy"] == original["privacy"] and item["description"] == original["description"]
        assert item["reuse_confirmation"]["binding"]["scheduled_id"] == item["id"]
    assert db.fetch("scheduled_publications", second["id"])["options"]["made_for_kids"] is True
    assert rights.evaluate(db.fetch("sources", source["id"]))["status"] == rights.MANUAL
    third, _, _ = draft(data, "A later new thought still needs its own review")
    assert third["status"] == "awaiting_approval" and third["approval"] == {}
    assert not db.select("publish_consents") and not db.select("publications")


def test_known_source_does_not_get_an_invented_owner_rights_assertion(data):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    item, _, _ = draft(data, unknown=False)
    preview = bulk_review.preview([item["id"]])
    assert preview["eligible_ids"] == [item["id"]]
    assert not preview["items"][0]["needs_reuse_confirmation"]
    result = bulk_review.approve(preview["token"], confirm=True, made_for_kids=False)
    assert result["approved"] == 1
    assert db.fetch("scheduled_publications", item["id"])["reuse_confirmation"] == {}


def test_mixed_public_and_private_posts_keep_their_own_audience_text_and_time(data):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, scheduler
    from clipfoundry.publish import audience

    private, _, _ = draft(data)
    db.save_settings({"audience_youtube": "public", "audience_youtube_confirmed_at": time.time()})
    public, _, _ = draft(data, "Another complete useful thought for public viewers")
    assert private["privacy"] == "private" and public["privacy"] == "public"
    preview = bulk_review.preview([private["id"], public["id"]])
    assert preview["eligible_ids"] == [private["id"], public["id"]]
    assert accept(preview["token"])["approved"] == 2
    for before in (private, public):
        after = db.fetch("scheduled_publications", before["id"])
        assert scheduler.approval_valid(after)
        assert after["privacy"] == before["privacy"] and after["planned_at"] == before["planned_at"]
        assert after["description"] == before["description"] and after["title"] == before["title"]
        assert after["audience"]["intent"] == before["audience"]["intent"]
    assert db.fetch("scheduled_publications", private["id"])["audience"]["intent"] == audience.SELECTED


def test_stale_statement_needs_a_fresh_exact_post_confirmation_even_after_recorded_coverage(data):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, rights, scheduler

    item, clip, source = draft(data, kids=False)
    first_preview = bulk_review.preview([item["id"]])
    assert accept(first_preview["token"])["approved"] == 1
    old_statement = db.fetch("scheduled_publications", item["id"])["reuse_confirmation"]
    rights.add_rule("source", source["id"], rights.OWNED, "New original-content record")
    passed_report(clip)
    item = db.fetch("scheduled_publications", item["id"])
    assert not scheduler.approval_valid(item)
    assert rights.evaluate(db.fetch("sources", source["id"]))["status"] == rights.OWNED
    info = rights.review_info(item)
    assert info["required"] and not info["confirmed"] and "earlier permission" in info["explanation"]
    preview = bulk_review.preview([item["id"]])
    assert preview["items"][0]["eligible"] and preview["items"][0]["needs_reuse_confirmation"]
    assert accept(preview["token"])["approved"] == 1
    after = db.fetch("scheduled_publications", item["id"])
    assert scheduler.approval_valid(after)
    assert after["reuse_confirmation"]["binding"] != old_statement["binding"]
    assert rights.evaluate(db.fetch("sources", source["id"]))["status"] == rights.OWNED


def test_filling_a_missing_kids_answer_refreshes_an_existing_permission_statement(data):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, rights, scheduler

    item, _, _ = draft(data)
    statement = rights.make_reuse_confirmation(item, "Creator approved this exact clip")
    db.update("scheduled_publications", item["id"], reuse_confirmation=statement)
    assert rights.review_info(db.fetch("scheduled_publications", item["id"]))["confirmed"]
    preview = bulk_review.preview([item["id"]])
    assert preview["items"][0]["needs_made_for_kids"]
    assert preview["items"][0]["needs_reuse_confirmation"]
    assert accept(preview["token"])["approved"] == 1
    after = db.fetch("scheduled_publications", item["id"])
    assert scheduler.approval_valid(after) and after["options"]["made_for_kids"] is False
    assert after["reuse_confirmation"]["binding"]["payload_sha256"] != statement["binding"]["payload_sha256"]


def test_single_review_also_offers_refresh_for_a_stale_statement_with_known_coverage(data):
    from fastapi.testclient import TestClient
    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.autopilot import bulk_review, rights, scheduler

    item, clip, source = draft(data, kids=False)
    assert accept(bulk_review.preview([item["id"]])["token"])["approved"] == 1
    rights.add_rule("source", source["id"], rights.OWNED, "A recorded owner rule now covers the source")
    passed_report(clip)
    with TestClient(app, client=("127.0.0.1", 12345), base_url="http://127.0.0.1:8765") as client:
        route = f"/api/autopilot/scheduled/{item['id']}"
        detail = client.get(route)
        assert detail.status_code == 200 and detail.json()["item"]["reuse_review"]["required"]
        result = client.post(route + "/approve", headers={"X-ClipFoundry": "1"},
                             json={"confirm": True, "reuse_confirmed": True, "reuse_kind": "owned"})
        assert result.status_code == 200 and result.json()["reuse_review"]["confirmed"]
        assert scheduler.approval_valid(db.fetch("scheduled_publications", item["id"]))


def test_replacement_proposals_wait_for_individual_review_without_changing_either_post(data):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    first, _, _ = draft(data)
    replacement, _, _ = draft(data, "A different clip proposes a stronger replacement")
    db.update("scheduled_publications", replacement["id"], replaces=first["id"])
    before = db.select("scheduled_publications", "", (), "id")
    preview = bulk_review.preview([replacement["id"]])
    assert not preview["eligible_ids"] and "replaces another" in preview["items"][0]["reason"]
    assert accept(preview["token"])["approved"] == 0
    assert db.select("scheduled_publications", "", (), "id") == before


def test_same_body_retry_is_idempotent_and_changed_answers_need_a_new_preview(data):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    item, _, _ = draft(data)
    preview = bulk_review.preview([item["id"]])
    result = accept(preview["token"])
    before = db.fetch("scheduled_publications", item["id"])
    assert accept(preview["token"]) == result
    assert db.fetch("scheduled_publications", item["id"]) == before
    with pytest.raises(ValueError, match="already used"):
        bulk_review.approve(preview["token"], confirm=True, reuse_confirmed=True,
                            reuse_kind="licensed", made_for_kids=False)
    assert not bulk_review.preview([item["id"]])["eligible_ids"]


@pytest.mark.parametrize("change", ["file", "account", "terms", "text", "time", "privacy", "source", "kids"])
def test_changed_preview_skips_only_affected_post(data, change):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, rights

    first, clip, source = draft(data)
    second, _, _ = draft(data, "A separate second useful thought is complete")
    preview = bulk_review.preview([first["id"], second["id"]])
    if change == "file":
        video = Path(clip["output_path"])
        stat = video.stat()
        video.write_bytes(b"other")
        import os
        os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif change == "account":
        db.save_account("youtube", tokens={"access_token": "other-fake-token"}, account_id="UCanother")
    elif change == "terms":
        rights.add_rule("source", source["id"], rights.BLOCKED, "Do not use this source")
    elif change == "text":
        db.update("scheduled_publications", first["id"], title="Someone changed the title")
    elif change == "time":
        db.update("scheduled_publications", first["id"], planned_at=first["planned_at"] + 3600)
    elif change == "privacy":
        db.update("scheduled_publications", first["id"], privacy="public")
    elif change == "source":
        db.update("sources", source["id"], url="https://example.org/different-video")
    else:
        db.update("scheduled_publications", first["id"], options={"made_for_kids": True})
    result = accept(preview["token"])
    assert result["results"][0]["status"] == "skipped"
    assert db.fetch("scheduled_publications", first["id"])["status"] == "awaiting_approval"
    expected = "skipped" if change == "account" else "approved"
    assert result["results"][1]["status"] == expected


@pytest.mark.parametrize("kind", ["missing", "failed", "stale", "metadata", "file"])
def test_preview_requires_a_passing_current_exact_file_and_metadata_check(data, kind):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    item, clip, _ = draft(data)
    report = db.select("quality_reports", "clip_id = ?", (clip["id"],), "created_at DESC")[0]
    if kind == "missing":
        db.execute("DELETE FROM quality_reports WHERE clip_id = ?", (clip["id"],))
    elif kind == "failed":
        db.update("quality_reports", report["id"], status="failed", blockers=["No readable audio"])
    elif kind == "stale":
        db.update("quality_reports", report["id"], coverage={"rights_context": "old"})
    elif kind == "metadata":
        db.update("quality_reports", report["id"], metadata={"youtube": {"status": "failed"}})
    else:
        Path(clip["output_path"]).unlink()
    preview = bulk_review.preview([item["id"]])
    assert not preview["eligible_ids"] and preview["items"][0]["reason"]
    assert accept(preview["token"])["approved"] == 0


@pytest.mark.parametrize("state", ["queued", "waiting", "retrying", "running", "session", "unknown",
                                  "published", "tiktok", "failed"])
def test_active_uncertain_or_other_platform_work_cannot_be_bulk_approved(data, state):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, queue

    item, clip, _ = draft(data)
    if state in ("queued", "waiting", "retrying", "running"):
        job = queue.enqueue("publish", {"scheduled_id": item["id"]}, ref=("scheduled", item["id"]),
                            idem_key=f"publish:{item['id']}")
        db.update("worker_jobs", job["id"], status=state)
    elif state in ("session", "unknown"):
        publication = db.insert("publications", {"clip_id": clip["id"], "platform": "youtube", "status": "failed",
                                                 "info": {"upload_session": "opaque-session"} if state == "session"
                                                 else {"outcome_unknown": True}})
        db.update("scheduled_publications", item["id"], publication_id=publication["id"])
    elif state == "tiktok":
        db.update("scheduled_publications", item["id"], platform="tiktok")
    else:
        db.update("scheduled_publications", item["id"], status=state)
    preview = bulk_review.preview([item["id"]])
    assert not preview["eligible_ids"] and preview["items"][0]["reason"]


def test_missing_confirmation_basis_and_kids_are_clear_per_item_results(data):
    from clipfoundry.autopilot import bulk_review

    item, _, _ = draft(data)
    preview = bulk_review.preview([item["id"]])
    with pytest.raises(ValueError, match="confirm"):
        bulk_review.approve(preview["token"])
    result = bulk_review.approve(preview["token"], confirm=True)
    assert result["skipped"] == 1 and "permission" in result["results"][0]["reason"]
    preview = bulk_review.preview([item["id"]])
    result = bulk_review.approve(preview["token"], confirm=True, reuse_confirmed=True, reuse_kind="owned")
    assert result["skipped"] == 1 and "kids" in result["results"][0]["reason"]


def test_expired_lost_or_other_profile_tokens_require_new_review(data, monkeypatch):
    from clipfoundry.autopilot import bulk_review

    item, _, _ = draft(data)
    preview = bulk_review.preview([item["id"]])
    monkeypatch.setattr(bulk_review.time, "time", lambda: preview["expires_at"] + 1)
    with pytest.raises(ValueError, match="expired"):
        accept(preview["token"])
    with pytest.raises(ValueError, match="expired"):
        accept("token-from-before-restart")


def test_final_guard_rejects_new_bytes_during_approval_without_authorizing_them(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, scheduler

    item, clip, _ = draft(data)
    preview = bulk_review.preview([item["id"]])
    original = scheduler.approval_record

    def changed(updated, **fields):
        Path(clip["output_path"]).write_bytes(b"changed-during-approval")
        return original(updated, **fields)

    monkeypatch.setattr(scheduler, "approval_record", changed)
    result = accept(preview["token"])
    assert result["skipped"] == 1
    assert db.fetch("scheduled_publications", item["id"])["approval"] == {}


@pytest.mark.parametrize("change", ["text", "account", "job", "review_mode", "dispatch_mode"])
def test_final_guard_rechecks_mutable_inputs_atomically_after_hashing(data, monkeypatch, change):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, queue, scheduler

    item, _, _ = draft(data)
    preview = bulk_review.preview([item["id"]])
    original = scheduler.approval_record

    def changed(updated, **fields):
        approval = original(updated, **fields)
        if change == "text":
            db.update("scheduled_publications", item["id"], description="Changed during approval")
        elif change == "account":
            db.save_account("youtube", tokens={"access_token": "other-fake"}, account_id="UCanother")
        elif change == "job":
            queue.enqueue("publish", {"scheduled_id": item["id"]}, idem_key="unrelated-ref-publish-job")
        elif change == "review_mode":
            db.save_settings({"autopilot_review_before_publish": False})
        else:
            db.save_settings({"autopilot_auto_publish": False})
        return approval

    monkeypatch.setattr(scheduler, "approval_record", changed)
    result = accept(preview["token"])
    assert result["skipped"] == 1
    assert db.fetch("scheduled_publications", item["id"])["approval"] == {}


def test_final_guard_does_not_hash_video_while_holding_sqlite_write_lock(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review
    from clipfoundry.pipeline import artifact

    item, _, _ = draft(data)
    preview = bulk_review.preview([item["id"]])
    original = artifact.sha256_file
    hashes = []

    def without_sql_lock(path, *args, **kwargs):
        # An independent SQLite writer must remain able to begin while the large-file hash is read.
        with db.connect() as conn:
            conn.execute("PRAGMA busy_timeout=1")
            conn.execute("BEGIN IMMEDIATE")
            hashes.append(str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(artifact, "sha256_file", without_sql_lock)
    assert accept(preview["token"])["approved"] == 1
    assert len(hashes) >= 3


def test_preview_cache_is_bounded_and_invalid_for_another_data_profile(data, monkeypatch):
    from clipfoundry.autopilot import bulk_review

    monkeypatch.setattr(bulk_review, "MAX_PREVIEWS", 3)
    oldest = bulk_review.preview(["deleted-a"])
    for index in range(6):
        bulk_review.preview([f"deleted-{index}"])
    assert len(bulk_review._previews) == 3
    with pytest.raises(ValueError, match="expired"):
        accept(oldest["token"])
    preview = bulk_review.preview(["deleted-b"])
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(data / "another-profile"))
    with pytest.raises(ValueError, match="expired"):
        accept(preview["token"])


def test_partial_failure_does_not_rollback_or_duplicate_approved_posts(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, scheduler

    first, _, _ = draft(data)
    second, _, _ = draft(data, "A different useful thought deserves review")
    preview = bulk_review.preview([first["id"], second["id"], "deleted-post"])
    original = scheduler.approve

    def failure(item_id, *args, **kwargs):
        if item_id == second["id"]:
            raise ValueError("Review this clip individually")
        return original(item_id, *args, **kwargs)

    monkeypatch.setattr(scheduler, "approve", failure)
    result = accept(preview["token"])
    assert result["approved"] == 1 and result["skipped"] == 2
    assert db.fetch("scheduled_publications", first["id"])["status"] == "approved"
    assert db.fetch("scheduled_publications", second["id"])["status"] == "awaiting_approval"
    assert accept(preview["token"]) == result


def test_bulk_routes_are_local_csrf_guarded_and_bounded_and_return_review_details(data):
    from fastapi.testclient import TestClient
    from clipfoundry.api import app

    item, _, _ = draft(data)
    with TestClient(app, client=("127.0.0.1", 12345), base_url="http://127.0.0.1:8765") as client:
        route = "/api/autopilot/scheduled/bulk-preview"
        assert client.post(route, json={"ids": [item["id"]]}).status_code == 403
        headers = {"X-ClipFoundry": "1"}
        assert client.post(route, headers=headers, json={"ids": [str(i) for i in range(51)]}).status_code == 422
        assert client.post(route, headers=headers, json={"ids": []}).status_code == 422
        assert client.post(route, headers=headers, json={"ids": [item["id"], item["id"]]}).status_code == 409
        response = client.post(route, headers=headers, json={"ids": [item["id"]]})
        assert response.status_code == 200
        preview = response.json()
        assert preview["items"][0]["item"]["clip"]["video_url"]
        assert preview["account"] == {"id": "UCbulk-review", "display_name": "Review channel"}
        assert len(preview["reuse_options"]) == 5
        body = {"token": preview["token"], "confirm": True, "reuse_confirmed": True,
                "reuse_kind": "licensed", "made_for_kids": False}
        confirm_route = "/api/autopilot/scheduled/bulk-approve"
        assert client.post(confirm_route, json=body).status_code == 403
        result = client.post(confirm_route, headers=headers, json=body)
        assert result.status_code == 200 and result.json()["approved"] == 1

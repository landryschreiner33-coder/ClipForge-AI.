"""Independent bulk-review audit: selection is a one-time exact-post owner decision."""
from __future__ import annotations

import os

import pytest

from test_autopilot_publish import connect, env, make_item  # noqa: F401


def _draft(env, suffix="one"):
    from clipfoundry import db
    from clipfoundry.autopilot import packaging, rights
    from quality_stub import passed_report

    google, tiktok, tmp = env
    if not db.get_account("youtube"):
        connect(google, tiktok)
    item = make_item(tmp)
    clip = db.get_clip(item["clip_id"])
    source = db.insert("sources", {"platform": "local", "external_id": suffix,
                                   "status": "analyzed", "rights_status": rights.MANUAL})
    db.update_project(clip["project_id"], source_id=source["id"])
    packaging.package(clip, source, "youtube", db.get_settings())
    passed_report(clip)
    return db.fetch("scheduled_publications", item["id"]), clip, source


def _approve(preview, **kwargs):
    from clipfoundry.autopilot import bulk_review

    return bulk_review.approve(
        preview["token"], confirm=True, reuse_confirmed=True, reuse_kind="custom",
        reuse_basis="I reviewed these selected clips and hold the creator's written reuse permission.",
        made_for_kids=kwargs.pop("made_for_kids", False), **kwargs,
    )


def _snapshot():
    from clipfoundry import db

    return {table: db.select(table, order="id") for table in (
        "scheduled_publications", "sources", "source_rights", "publish_consents", "worker_jobs", "publications",
        "quality_reports", "action_items", "autopilot_events",
    )}


def test_bulk_preview_is_read_only_and_cannot_start_or_approve_any_upload(env):
    from clipfoundry.autopilot import bulk_review

    item, _clip, _source = _draft(env)
    before = _snapshot()
    preview = bulk_review.preview([item["id"]])
    assert preview["eligible_ids"] == [item["id"]]
    assert preview["items"][0]["needs_reuse_confirmation"]
    assert _snapshot() == before
    assert not env[0].sessions and not env[0].videos


def test_owner_selection_creates_individual_assertions_without_source_or_future_grant(env):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, rights, scheduler

    first, _clip, source = _draft(env)
    preview = bulk_review.preview([first["id"]])
    result = _approve(preview)
    assert result["approved"] == 1 and result["skipped"] == 0
    approved = db.fetch("scheduled_publications", first["id"])
    assert approved["approval"]["by"] == "you" and scheduler.approval_valid(approved)
    assert approved["reuse_confirmation"]["owner_confirmed"] is True
    assert not rights.confirmation_problem(approved)
    assert rights.evaluate(db.fetch("sources", source["id"]))["status"] == rights.MANUAL
    assert not db.select("source_rights") and not db.select("publish_consents")
    future, _clip, _source = _draft(env, "future")
    scheduler.process_due(db.get_settings(), future["planned_at"] + 1)
    current = db.fetch("scheduled_publications", future["id"])
    assert current["status"] == "awaiting_approval" and not current["approval"]
    assert not current["reuse_confirmation"]
    assert rights.confirmation_problem({**approved, "id": future["id"]})


@pytest.mark.parametrize("status", ["canceled", "removed"])
def test_source_stopped_after_selection_cannot_be_revived_by_bulk_approval(env, status):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    item, _clip, source = _draft(env)
    preview = bulk_review.preview([item["id"]])
    db.update("sources", source["id"], status=status)
    result = _approve(preview)
    assert result["approved"] == 0 and result["skipped"] == 1
    current = db.fetch("scheduled_publications", item["id"])
    assert current["status"] == "awaiting_approval" and not current["approval"]
    assert not current["reuse_confirmation"]


def test_known_credit_added_after_selection_cannot_be_waived_by_shared_owner_assertion(env):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, rights

    item, _clip, source = _draft(env)
    preview = bulk_review.preview([item["id"]])
    rights.add_rule("source", source["id"], rights.ALLOWLISTED, "Creator agreement",
                    conditions={"platforms": ["youtube"], "attribution": "Original creator: Example Creator"})
    before = db.fetch("scheduled_publications", item["id"])
    result = _approve(preview)
    assert result["approved"] == 0 and result["skipped"] == 1
    current = db.fetch("scheduled_publications", item["id"])
    assert current == before
    assert "Example Creator" not in current["description"]


def test_same_size_same_mtime_file_change_after_selection_requires_a_new_review(env):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    item, clip, _source = _draft(env)
    preview = bulk_review.preview([item["id"]])
    file_path = clip["output_path"]
    stamp = os.stat(file_path)
    with open(file_path, "r+b") as target:
        target.write(b"changed")
    os.utime(file_path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert os.stat(file_path).st_size == stamp.st_size
    result = _approve(preview)
    assert result["approved"] == 0 and result["skipped"] == 1
    assert not db.fetch("scheduled_publications", item["id"])["approval"]
    assert not env[0].sessions


def test_changed_connected_account_after_selection_is_not_an_approval_for_its_replacement(env):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    item, _clip, _source = _draft(env)
    preview = bulk_review.preview([item["id"]])
    db.save_account("youtube", account_id="another-channel", tokens={"access_token": "another-fake-token"})
    result = _approve(preview)
    assert result["approved"] == 0 and result["skipped"] == 1
    assert not db.fetch("scheduled_publications", item["id"])["approval"]
    assert not db.select("source_rights") and not db.select("publish_consents")


@pytest.mark.parametrize("status", ["canceled", "publishing", "reconciling", "published", "replaced"])
def test_post_state_change_after_selection_is_never_reset_to_approved(env, status):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    item, _clip, _source = _draft(env)
    preview = bulk_review.preview([item["id"]])
    db.update("scheduled_publications", item["id"], status=status, status_note="Keep the newer post state")
    before = db.fetch("scheduled_publications", item["id"])
    result = _approve(preview)
    assert result["approved"] == 0 and result["skipped"] == 1
    assert db.fetch("scheduled_publications", item["id"]) == before


@pytest.mark.parametrize("info", [{"upload_session": "existing-session"}, {"outcome_unknown": True}])
def test_started_or_unknown_transfer_after_selection_keeps_original_identity_and_payload(env, info):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    item, clip, _source = _draft(env)
    preview = bulk_review.preview([item["id"]])
    publication = db.create_publication(clip["id"], "youtube", scheduled_id=item["id"], status="failed",
                                        title="Keep original upload title", requested_privacy="private", info=info)
    db.update("scheduled_publications", item["id"], publication_id=publication["id"])
    before = db.fetch("scheduled_publications", item["id"])
    result = _approve(preview)
    assert result["approved"] == 0 and result["skipped"] == 1
    assert db.fetch("scheduled_publications", item["id"]) == before
    assert db.get_publication(publication["id"]) == publication


def test_shared_kids_answer_fills_missing_only_and_preserves_each_existing_answer(env):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    first, _clip, _source = _draft(env)
    second, _clip, _source = _draft(env, "second")
    db.update("scheduled_publications", first["id"], options={"made_for_kids": False})
    preview = bulk_review.preview([first["id"], second["id"]])
    assert set(preview["eligible_ids"]) == {first["id"], second["id"]}
    result = _approve(preview, made_for_kids=True)
    assert result["approved"] == 2 and result["skipped"] == 0
    assert db.fetch("scheduled_publications", first["id"])["options"]["made_for_kids"] is False
    assert db.fetch("scheduled_publications", second["id"])["options"]["made_for_kids"] is True


@pytest.mark.parametrize("status", ["queued", "waiting", "retrying", "running"])
def test_new_pending_publisher_work_after_selection_cannot_use_bulk_approval_to_bypass_future_time(env, status):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review, queue

    item, _clip, _source = _draft(env)
    preview = bulk_review.preview([item["id"]])
    work = queue.enqueue("publish", {"scheduled_id": item["id"]}, ref=("scheduled", item["id"]))
    db.update("worker_jobs", work["id"], status=status)
    before = db.fetch("scheduled_publications", item["id"])
    result = _approve(preview)
    assert result["approved"] == 0 and result["skipped"] == 1
    assert db.fetch("scheduled_publications", item["id"]) == before
    assert queue.get(work["id"])["status"] == status
    assert not env[0].sessions and not env[0].videos

"""Local schedule drafts wait for the owner's exact-post reuse review and publishing approval."""
from __future__ import annotations

import time

import pytest

from test_autopilot_scheduler import make_clip


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_tiktok": False,
                      "autopilot_review_before_publish": True, "autopilot_auto_publish": True})
    db.save_account("youtube", tokens={"access_token": "fake-token"}, account_id="UCowner-review")
    return tmp_path


def _draft(tmp, *, unknown=True):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    source = db.insert("sources", {"platform": "local", "external_id": str(time.time_ns()),
                                   "title": "Reviewable source", "status": "analyzed"}) if unknown else None
    clip = make_clip(tmp, "A complete thought worth sharing", 80, source=source)
    result = scheduler.plan_new(db.get_settings(), time.time())
    assert result["created"] == 1
    return clip, db.select("scheduled_publications")[0], source


def _automatic(item):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    updated = {**item, "options": {"made_for_kids": False}}
    approval = scheduler.approval_record(updated, at=time.time(), by="automatic", consent_id="old-permission")
    db.update("scheduled_publications", item["id"], status="approved", options=updated["options"],
              approval=approval)
    return db.fetch("scheduled_publications", item["id"])


def test_review_is_the_production_default_and_an_explicit_choice_survives_restart(data):
    from clipfoundry import config, db

    assert config.DEFAULT_SETTINGS["autopilot_review_before_publish"] is True
    assert config.validate_settings({"autopilot_review_before_publish": False}) == {
        "autopilot_review_before_publish": False}
    db.save_settings({"autopilot_review_before_publish": False})
    db.init()
    assert db.get_settings()["autopilot_review_before_publish"] is False


def test_unrecorded_reuse_does_not_prevent_a_local_schedule_draft_or_imply_a_license(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scheduler

    _clip, item, source = _draft(data)
    assert item["status"] == "awaiting_approval" and item["planned_at"]
    assert item["approval"] == {} and item["reuse_confirmation"] == {}
    assert rights.evaluate(db.fetch("sources", source["id"]))["status"] == rights.MANUAL
    assert scheduler.process_due(db.get_settings(), time.time())["publishing"] == 0
    assert not db.select("publications")


@pytest.mark.parametrize("stop", ["blocked", "canceled", "removed"])
def test_explicit_source_stops_still_prevent_schedule_drafts(data, stop):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scheduler
    from quality_stub import passed_report

    source = db.insert("sources", {"platform": "local", "external_id": stop, "status": "analyzed"})
    clip = make_clip(data, "Stopped source remains stopped", 90, source=source)
    if stop == "blocked":
        rights.add_rule("source", source["id"], rights.BLOCKED, "Owner blocked this source")
    else:
        db.update("sources", source["id"], status=stop)
    passed_report(clip)
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 0


def test_standing_permission_cannot_auto_approve_a_draft_in_review_mode(data):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler

    db.insert("publish_consents", {"platform": "youtube", "text": "Existing permission", "settings": {
        "account_id": "UCowner-review", "visibility": "private", "text_version": 3, "made_for_kids": False,
        "daily_limit": 0, "start_hour": 0, "end_hour": 24, "timezone": "America/Chicago"}})
    _clip, item, _source = _draft(data, unknown=False)
    assert not scheduler.auto_approve(item, db.get_settings(), time.time())
    view = autopublish.view(db.get_settings())
    assert view["review_before_publish"] and not view["youtube"]["enabled"]
    assert not view["youtube"]["can_enable"]
    with pytest.raises(ValueError, match="Review before publishing"):
        autopublish.enable("youtube", "private", False, 0, 0, 24, True)


def test_old_unstarted_automatic_approval_returns_to_review_with_its_exact_payload_and_identity(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler

    clip, draft, _source = _draft(data, unknown=False)
    item = _automatic(draft)
    pub = db.create_publication(clip["id"], "youtube", status="queued", scheduled_id=item["id"],
                                title=item["title"], description=item["description"], privacy=item["privacy"])
    db.update("scheduled_publications", item["id"], publication_id=pub["id"], status="publishing")
    work = queue.enqueue("publish", {"scheduled_id": item["id"]}, ref=("scheduled", item["id"]),
                         idem_key=f"publish:{item['id']}")
    assert scheduler.hold_automatic_approvals(db.get_settings()) == 1
    after = db.fetch("scheduled_publications", item["id"])
    for field in ("title", "description", "privacy", "options", "planned_at", "audience"):
        assert after[field] == item[field]
    assert after["publication_id"] == pub["id"] and after["status"] == "awaiting_approval"
    assert after["approval"] == {} and queue.get(work["id"])["status"] == "canceled"
    assert scheduler.hold_automatic_approvals(db.get_settings()) == 0


@pytest.mark.parametrize("info,remote,status", [
    ({"upload_session": "stored-session"}, "", "uploading"),
    ({"final_chunk_at": 1}, "", "failed"),
    ({"outcome_unknown": True}, "", "failed"),
    ({}, "platform-id", "processing"),
    ({}, "", "done"),
])
def test_started_or_uncertain_uploads_keep_their_session_and_approval(data, info, remote, status):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    clip, draft, _source = _draft(data, unknown=False)
    item = _automatic(draft)
    pub = db.create_publication(clip["id"], "youtube", status=status, info=info, remote_id=remote)
    db.update("scheduled_publications", item["id"], publication_id=pub["id"], status="publishing")
    assert scheduler.hold_automatic_approvals(db.get_settings()) == 0
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "publishing" and after["publication_id"] == pub["id"]
    assert after["approval"] == item["approval"] and db.get_publication(pub["id"])["info"] == info


def test_running_upload_worker_is_not_rewritten_by_the_schedule_pass(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler

    _clip, draft, _source = _draft(data, unknown=False)
    item = _automatic(draft)
    work = queue.enqueue("publish", {"scheduled_id": item["id"]}, ref=("scheduled", item["id"]))
    db.update("worker_jobs", work["id"], status="running")
    assert scheduler.hold_automatic_approvals(db.get_settings()) == 0
    assert db.fetch("scheduled_publications", item["id"])["approval"] == item["approval"]


def test_owner_reuse_review_is_required_and_remains_a_per_post_assertion(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scheduler

    clip, item, source = _draft(data)
    fields = {"options": {"made_for_kids": False}}
    with pytest.raises(ValueError, match="confirm"):
        scheduler.approve(item["id"], fields)
    with pytest.raises(ValueError, match="Explain your reuse permission"):
        scheduler.approve(item["id"], fields, reuse_confirmed=True, reuse_basis=" ")
    approved = scheduler.approve(item["id"], fields, reuse_confirmed=True,
                                 reuse_basis="Creator agreed to this clip on YouTube; checked the source and audio.")
    assert approved["status"] == "approved" and scheduler.approval_valid(approved)
    assert approved["approval"]["by"] == "you" and approved["reuse_confirmation"]["owner_confirmed"]
    assert rights.confirmation_problem(approved) == ""
    assert rights.evaluate(db.fetch("sources", source["id"]))["status"] == rights.MANUAL
    assert not db.select("source_rights")
    assert rights.review_info(approved)["required"] and rights.review_info(approved)["confirmed"]
    copied = {**approved, "id": "another-scheduled-post"}
    # An exact-post assertion cannot be borrowed by a second post, platform or changed payload.
    assert rights.confirmation_problem(copied)
    assert rights.confirmation_problem({**copied, "platform": "tiktok"})
    assert rights.confirmation_problem({**copied, "description": "Changed post"})
    scheduler.edit(item["id"], {"title": "Changed title"})
    edited = db.fetch("scheduled_publications", item["id"])
    assert edited["reuse_confirmation"] == {} and edited["approval"] == {}
    assert edited["status"] == "awaiting_approval"
    assert db.get_clip(clip["id"])["output_path"] == clip["output_path"]


def test_physical_failure_cannot_be_overridden_by_an_owner_reuse_confirmation(data):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, scheduler

    clip, item, _source = _draft(data)
    report = gate.report_for(clip)
    db.update("quality_reports", report["id"], status="failed", blockers=["File decode failed"])
    with pytest.raises(ValueError, match="final quality check"):
        scheduler.approve(item["id"], {"options": {"made_for_kids": False}},
                          reuse_confirmed=True, reuse_basis="Creator allowed this use")
    assert db.fetch("scheduled_publications", item["id"])["status"] == "awaiting_approval"


def test_reuse_terms_changed_after_owner_review_need_a_fresh_approval(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scheduler

    _clip, item, source = _draft(data)
    approved = scheduler.approve(item["id"], {"options": {"made_for_kids": False}},
                                 reuse_confirmed=True, reuse_basis="Creator checked and allowed this post")
    rights.add_rule("source", source["id"], rights.ALLOWLISTED, "New source agreement",
                    conditions={"platforms": ["youtube"], "attribution": "Creator credit required"})
    assert not scheduler.approval_valid(approved)
    assert "reuse terms" in scheduler.approval_problem(approved)
    assert scheduler.process_due(db.get_settings(), time.time())["publishing"] == 0
    assert db.fetch("scheduled_publications", item["id"])["status"] == "awaiting_approval"


def test_owner_assertion_cannot_waive_known_source_credit_before_approval(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scheduler
    from quality_stub import passed_report

    clip, item, source = _draft(data)
    credit = "Original creator: Example Creator (https://example.com/agreement)."
    db.update("sources", source["id"], local_path=clip["output_path"])
    source = db.fetch("sources", source["id"])
    rights.add_rule("folder", str(data), rights.LICENSED, "Recorded noncommercial permission",
                    conditions={"commercial": False, "attribution": credit})
    db.save_settings({"autopilot_commercial_use": True})
    assert rights.evaluate(source)["status"] == rights.MANUAL
    passed_report(clip)
    before = db.fetch("scheduled_publications", item["id"])
    fields = {"options": {"made_for_kids": False}}
    with pytest.raises(ValueError, match="source credit"):
        scheduler.approve(item["id"], fields, reuse_confirmed=True,
                          reuse_basis="Creator separately allowed this exact use")
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "awaiting_approval" and after["approval"] == {}
    assert after["description"] == before["description"] and after["reuse_confirmation"] == {}
    approved = scheduler.approve(item["id"], {**fields, "description": before["description"] + "\n\n" + credit},
                                 reuse_confirmed=True, reuse_basis="Creator separately allowed this exact use")
    assert approved["status"] == "approved" and scheduler.approval_valid(approved)
    assert credit in approved["description"]
    assert rights.evaluate(source)["status"] == rights.MANUAL


def test_unapproved_review_drafts_do_not_expire_after_two_days(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    _clip, item, _source = _draft(data)
    now = time.time()
    db.update("scheduled_publications", item["id"], planned_at=now - 7 * 86400)
    result = scheduler.process_due(db.get_settings(), now)
    after = db.fetch("scheduled_publications", item["id"])
    assert result["expired"] == 0 and result["publishing"] == 0
    assert after["status"] == "awaiting_approval" and after["planned_at"] >= now


def test_manually_approved_post_still_dispatches_at_its_time(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler

    _clip, item, _source = _draft(data)
    scheduler.approve(item["id"], {"options": {"made_for_kids": False}},
                      reuse_confirmed=True, reuse_basis="Creator permission checked for this post")
    now = time.time()
    db.update("scheduled_publications", item["id"], planned_at=now)
    assert scheduler.process_due(db.get_settings(), now)["publishing"] == 1
    assert db.fetch("scheduled_publications", item["id"])["status"] == "publishing"
    assert len(queue.jobs(("queued",), worker="publisher", ref=("scheduled", item["id"]))) == 1


def test_scheduled_api_exposes_review_and_requires_both_reuse_and_post_confirmation(data):
    from fastapi.testclient import TestClient
    from clipfoundry import db
    from clipfoundry.api import app

    _clip, item, _source = _draft(data)
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 12345)) as client:
        detail = client.get(f"/api/autopilot/scheduled/{item['id']}")
        assert detail.status_code == 200 and detail.json()["review_before_publish"]
        assert detail.json()["item"]["reuse_review"]["required"]
        response = client.post(f"/api/autopilot/scheduled/{item['id']}/approve", headers={"X-ClipFoundry": "1"},
                               json={"reuse_confirmed": True, "reuse_basis": "Creator allowed this post",
                                     "made_for_kids": False})
        assert response.status_code == 400 and "explicit confirmation" in response.text
        response = client.post(f"/api/autopilot/scheduled/{item['id']}/approve", headers={"X-ClipFoundry": "1"},
                               json={"confirm": True, "made_for_kids": False})
        assert response.status_code == 409
        response = client.post(f"/api/autopilot/scheduled/{item['id']}/approve", headers={"X-ClipFoundry": "1"},
                               json={"confirm": True, "reuse_confirmed": True,
                                     "reuse_basis": "Creator allowed this post", "made_for_kids": False})
        assert response.status_code == 200 and response.json()["reuse_review"]["confirmed"]
        assert db.fetch("scheduled_publications", item["id"])["approval"]["by"] == "you"

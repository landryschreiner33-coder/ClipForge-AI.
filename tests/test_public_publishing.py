"""Explicit public publishing against isolated local platform stand-ins; never real accounts."""
from __future__ import annotations

import time

import pytest

from test_audience import api, env  # noqa: F401 - reuse the isolated fake-platform fixtures
from test_autopilot_publish import H, connect, make_item, run_publish


def public_setup(client, platform="youtube"):
    result = client.post(f"/api/audience/{platform}", headers=H, json={"intent": "public", "confirm": True})
    assert result.status_code == 200, result.text
    assert result.json()[platform]["intent"] == "PUBLIC"


def public_item(tmp, platform="youtube"):
    return make_item(tmp, platform, approve={
        "privacy": "public" if platform == "youtube" else "PUBLIC_TO_EVERYONE",
        "options": {"made_for_kids": False} if platform == "youtube" else
        {"mode": "direct", "music_confirmed": True}})


def test_public_choice_requires_confirmation_and_has_no_default(env, api):
    from clipfoundry import db
    from clipfoundry.publish import audience, youtube

    assert db.get_settings()["audience_youtube"] == "selected"
    with pytest.raises(audience.AudienceBlocked):
        audience.check("youtube", "public", db.get_settings())
    api.post("/api/audience/youtube", headers=H, json={"intent": "public", "confirm": False})
    with pytest.raises(audience.AudienceBlocked, match="Choose who watches"):
        audience.check("youtube", "public", db.get_settings())
    public_setup(api)
    stamp = audience.check("youtube", "public", db.get_settings())
    assert stamp["intent"] == audience.PUBLIC and stamp["group"] == "public"
    assert youtube.video_body("title", "text", [], "public", False, audience_intent=stamp["intent"])[
        "status"]["privacyStatus"] == "public"
    with pytest.raises(audience.AudienceBlocked):
        youtube.video_body("title", "text", [], "public", False)  # no accidental low-level default
    assert audience.classify("youtube", "private", db.get_settings()) == audience.OWNER_ONLY


def test_public_upload_reports_actual_visibility_and_does_not_drift_halt(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler
    from clipfoundry.publish import audience, jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    item = public_item(tmp)
    assert scheduler.lead_seconds(item, db.get_settings()) == 0
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(after["publication_id"])
    assert google.videos[pub["remote_id"]]["status"]["privacyStatus"] == "public"
    assert "publishAt" not in google.videos[pub["remote_id"]]["status"]
    assert after["delivery"]["audience_setup"] == "public_api_verified"
    assert jobs.refresh(pub)["privacy"] == "public"
    assert not audience.halted("youtube")
    assert api.get(f"/api/autopilot/scheduled/{item['id']}").json()["item"]["audience_label"] == "Public audience"


def test_youtube_private_restriction_never_claims_public_delivery(env, api):
    from clipfoundry import db
    from clipfoundry.publish import audience

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    google.lock_private = True
    item = public_item(tmp)
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(after["publication_id"])
    assert pub["requested_privacy"] == "public" and pub["privacy"] == "private"
    assert pub["info"]["locked_private"]
    assert "Unaudited" in pub["message"] and "has not made it public" in pub["message"]
    assert after["delivery"]["audience_setup"] == "public_restricted"
    assert not audience.halted("youtube")  # narrower visibility is a blocker, not a wider-audience incident


def test_public_automation_requires_audit_and_connected_channel_specific_consent(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler
    from clipfoundry.publish import audience

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    with pytest.raises(ValueError, match="unaudited"):
        autopublish.enable("youtube", "public", False, 3, 0, 24, True)
    assert not autopublish.view(db.get_settings())["youtube"]["can_enable"]
    db.save_settings({"youtube_project_verified": True})
    consent = autopublish.enable("youtube", "public", False, 3, 0, 24, True)
    assert consent["settings"]["account_id"] and consent["settings"]["audience_intent"] == audience.PUBLIC
    assert "Public videos" in consent["text"] and "Existing posts" in consent["text"]
    item = make_item(tmp)
    stamp = audience.check("youtube", "public", db.get_settings())
    db.update("scheduled_publications", item["id"], privacy="public", audience=stamp)
    item = db.fetch("scheduled_publications", item["id"])
    assert scheduler.auto_approve(item, db.get_settings(), time.time())
    approved = db.fetch("scheduled_publications", item["id"])
    assert autopublish.still_covers(approved)
    db.save_account("youtube", account_id="UCother", display_name="Another channel")
    assert not autopublish.still_covers(approved)
    assert "another account" in scheduler.approval_problem(approved)
    assert not autopublish.view(db.get_settings())["youtube"]["enabled"]


@pytest.mark.parametrize("visibility", ["public", "private"])
def test_clearing_project_audit_blocks_new_public_automation_but_preserves_private(env, api, visibility):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, queue, scheduler
    from clipfoundry.publish import audience

    google, tiktok, tmp = env
    connect(google, tiktok)
    if visibility == "public":
        public_setup(api)
    db.save_settings({"youtube_project_verified": True})
    autopublish.enable("youtube", visibility, False, 3, 0, 24, True)
    items = [make_item(tmp) for _ in range(2)]
    for item in items:
        stamp = audience.check("youtube", visibility, db.get_settings())
        db.update("scheduled_publications", item["id"], privacy=visibility, audience=stamp)
    approved, pending = [db.fetch("scheduled_publications", item["id"]) for item in items]
    assert scheduler.auto_approve(approved, db.get_settings(), time.time())
    approved = db.fetch("scheduled_publications", approved["id"])
    db.save_settings({"youtube_project_verified": False})
    if visibility == "public":
        assert not autopublish.view(db.get_settings())["youtube"]["enabled"]
        assert not scheduler.auto_approve(pending, db.get_settings(), time.time())
        assert "audit" in db.fetch("scheduled_publications", pending["id"])["status_note"]
        assert not autopublish.still_covers(approved)
        with pytest.raises(queue.Fail, match="permission"):
            run_publish(approved["id"])
        assert db.fetch("scheduled_publications", approved["id"])["status"] == "awaiting_approval"
        assert not google.videos  # queued automatic work cannot create a real upload session
    else:
        assert autopublish.still_covers(approved)
        assert scheduler.auto_approve(pending, db.get_settings(), time.time())
        run_publish(approved["id"])
        assert len(google.videos) == 1
        assert next(iter(google.videos.values()))["status"]["privacyStatus"] == "private"


def test_existing_private_posts_keep_visibility_stamp_and_approval_after_public_default(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler

    google, tiktok, tmp = env
    connect(google, tiktok)
    private = make_item(tmp, approve={"options": {"made_for_kids": False}})
    old_stamp = dict(private["audience"])
    public_setup(api)
    db.save_settings({"youtube_project_verified": True})
    autopublish.enable("youtube", "public", False, 3, 0, 24, True)
    after = db.fetch("scheduled_publications", private["id"])
    assert after["privacy"] == "private" and after["audience"] == old_stamp
    assert scheduler.approval_valid(after)
    pending = make_item(tmp)
    assert not scheduler.auto_approve(pending, db.get_settings(), time.time())
    assert db.fetch("scheduled_publications", pending["id"])["privacy"] == "private"
    run_publish(private["id"])
    done = db.fetch("scheduled_publications", private["id"])
    pub = db.get_publication(done["publication_id"])
    assert pub["requested_privacy"] == pub["privacy"] == "private"
    assert done["audience"] == old_stamp


def test_legacy_public_plan_remains_held_even_after_public_automation(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler

    google, tiktok, tmp = env
    connect(google, tiktok)
    item = make_item(tmp)
    db.update("scheduled_publications", item["id"], privacy="public", status="blocked",
              audience={"intent": "LEGACY_PUBLIC", "policy_version": 1})
    public_setup(api)
    db.save_settings({"youtube_project_verified": True})
    autopublish.enable("youtube", "public", False, 3, 0, 24, True)
    held = db.fetch("scheduled_publications", item["id"])
    assert not scheduler.auto_approve(held, db.get_settings(), time.time())
    assert db.fetch("scheduled_publications", item["id"])["status"] == "blocked"
    assert not google.videos


def test_public_tiktok_still_requires_audit_and_per_post_approval(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler
    from clipfoundry.publish.common import PublishError

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api, "tiktok")
    with pytest.raises(PublishError, match="audited"):
        public_item(tmp, "tiktok")
    assert not tiktok.inits
    db.save_settings({"tiktok_app_audited": True})
    pending = make_item(tmp, "tiktok")
    assert not scheduler.auto_approve(pending, db.get_settings(), time.time())
    with pytest.raises(ValueError, match="each post"):
        autopublish.enable("tiktok", "PUBLIC_TO_EVERYONE", False, 3, 0, 24, True)
    item = public_item(tmp, "tiktok")
    run_publish(item["id"])
    done = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(done["publication_id"])
    assert tiktok.inits[-1]["post_info"]["privacy_level"] == "PUBLIC_TO_EVERYONE"
    assert done["delivery"]["audience_setup"] == "public_requested"
    assert done["delivery"]["visibility"]["returned"] is None
    assert pub["url"].startswith("https://www.tiktok.com/")


def test_public_tiktok_package_instructs_everyone_without_claiming_automatic_post(env, api):
    from clipfoundry import db

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api, "tiktok")
    item = make_item(tmp, "tiktok", approve={"privacy": "", "options": {"mode": "manual"}})
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "action_needed" and "Everyone" in after["status_note"]
    assert "private" not in after["status_note"].lower() and not tiktok.inits
    assert after["delivery"]["audience_setup"] == "manual_pending"


def test_public_approval_rejects_ineligible_source_and_changed_exact_bytes(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    item = public_item(tmp)
    source = db.insert("sources", {"platform": "youtube", "external_id": "unknown0001", "status": "analyzed",
                                   "url": "https://www.youtube.com/watch?v=unknown0001",
                                   "rights_status": "MANUAL_CONFIRMATION_REQUIRED"})
    clip = db.get_clip(item["clip_id"])
    db.update("projects", clip["project_id"], source_id=source["id"])
    with pytest.raises(queue.Fail):
        run_publish(item["id"])
    assert db.fetch("scheduled_publications", item["id"])["status"] == "blocked" and not google.videos
    db.update("projects", clip["project_id"], source_id="")
    db.update("scheduled_publications", item["id"], status="approved")
    from pathlib import Path

    Path(clip["output_path"]).write_bytes(b"changed after approval")
    with pytest.raises(queue.Fail, match="approval"):
        run_publish(item["id"])
    assert db.fetch("scheduled_publications", item["id"])["status"] == "awaiting_approval" and not google.videos


def test_queue_retry_label_is_derived_from_durable_job(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    _, _, tmp = env
    item = make_item(tmp)
    job = queue.enqueue("publish", {"scheduled_id": item["id"]}, idem_key=f"publish:{item['id']}")
    db.update("worker_jobs", job["id"], status="retrying", attempts=1, run_after=time.time() + 300,
              message="Retrying connection")
    shown = api.get(f"/api/autopilot/scheduled/{item['id']}").json()["item"]
    assert shown["delivery_state"] == "retrying" and shown["publishing_job"]["attempts"] == 1

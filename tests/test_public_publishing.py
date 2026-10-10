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


@pytest.mark.parametrize("mode", ["direct", "inbox"])
def test_manual_tiktok_approval_stays_bound_to_the_shown_account(env, api, monkeypatch, mode):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api, "tiktok")
    db.save_settings({"tiktok_app_audited": True})
    clip_id = make_item(tmp, "tiktok")["clip_id"]
    account_id = db.get_account("tiktok")["account_id"]
    # Hold the worker so the account can change after the user's per-post confirmation.
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    result = api.post(f"/api/clips/{clip_id}/publish/tiktok", headers=H, json={
        "description": "A confirmed public clip", "privacy": "PUBLIC_TO_EVERYONE", "mode": mode,
        "confirm": True, "expected_account_id": account_id})
    assert result.status_code == 200, result.text
    publication = result.json()
    assert publication["options"]["approved_account"] == account_id
    db.save_account("tiktok", account_id="another-creator", display_name="Another creator")
    jobs.worker._run(publication["id"])
    after = db.get_publication(publication["id"])
    assert after["status"] == "failed" and after["info"]["code"] == "reconnect"
    assert "Another TikTok account" in after["error"]
    assert not tiktok.inits  # Neither the direct post nor the inbox draft reaches the unseen account.


@pytest.mark.parametrize("platform", ["youtube", "tiktok"])
def test_emergency_pause_holds_manual_queue_before_upload_and_resume_starts_once(env, api, monkeypatch, platform):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api, platform)
    db.save_settings({"tiktok_app_audited": True})
    clip_id = make_item(tmp, platform)["clip_id"]
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    waits = []
    monkeypatch.setattr(jobs.worker, "later", lambda pub_id, at: waits.append((pub_id, at)))
    result = api.post(f"/api/clips/{clip_id}/publish/{platform}", headers=H, json={
        "title": "A confirmed public clip", "description": "A confirmed public clip", "confirm": True,
        "privacy": "public" if platform == "youtube" else "PUBLIC_TO_EVERYONE", "made_for_kids": False})
    assert result.status_code == 200, result.text
    publication_id = result.json()["id"]
    db.save_settings({"autopilot_publishing_paused": True})
    before = time.time()
    jobs.worker._run(publication_id)
    after = db.get_publication(publication_id)
    assert after["status"] == "queued" and "paused" in after["message"]
    assert waits == [(publication_id, after["info"]["retry_at"])]
    assert before + 30 <= waits[0][1] <= time.time() + 30
    assert not google.sessions and not tiktok.inits
    db.save_settings({"autopilot_publishing_paused": False})
    jobs.worker._run(publication_id)
    after = db.get_publication(publication_id)
    assert after["status"] == "done"
    assert len(google.videos) == (1 if platform == "youtube" else 0)
    assert len(tiktok.inits) == (1 if platform == "tiktok" else 0)


def test_emergency_pause_preserves_an_already_started_manual_youtube_session(env, api, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    clip_id = make_item(tmp)["clip_id"]
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    monkeypatch.setattr(jobs.worker, "later", lambda _pub_id, _at: None)
    google.rate_limit_puts, google.retry_after = 1, "600"
    result = api.post(f"/api/clips/{clip_id}/publish/youtube", headers=H, json={
        "title": "One exact upload", "description": "One exact upload", "confirm": True,
        "privacy": "public", "made_for_kids": False})
    assert result.status_code == 200, result.text
    publication_id = result.json()["id"]
    jobs.worker._run(publication_id)
    waiting = db.get_publication(publication_id)
    assert waiting["status"] == "queued" and waiting["info"]["upload_session"]
    assert len(google.sessions) == 1 and not google.videos
    db.save_settings({"autopilot_publishing_paused": True})
    jobs.worker._run(publication_id)  # Simulate the platform's Retry-After becoming due.
    after = db.get_publication(publication_id)
    assert after["status"] == "done" and len(google.videos) == 1 and len(google.sessions) == 1
    assert after["info"]["upload_session"] == waiting["info"]["upload_session"]


@pytest.mark.parametrize("status", ["MANUAL_CONFIRMATION_REQUIRED", "BLOCKED"])
def test_manual_publish_cannot_bypass_linked_source_reuse_gate(env, api, monkeypatch, status):
    from clipfoundry import db
    from clipfoundry.autopilot import rights
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    item = make_item(tmp)
    clip = db.get_clip(item["clip_id"])
    source = db.insert("sources", {"platform": "local", "external_id": "uncovered-local-fixture"})
    db.update("projects", clip["project_id"], source_id=source["id"])
    if status == rights.BLOCKED:
        rights.add_rule("source", source["id"], rights.BLOCKED, "Explicitly blocked")
    submitted = []
    monkeypatch.setattr(jobs.worker, "submit", submitted.append)
    result = api.post(f"/api/clips/{clip['id']}/publish/youtube", headers=H, json={
        "title": "Local source clip", "privacy": "public", "made_for_kids": False, "confirm": True})
    assert result.status_code == 400 and result.json()["code"] == "rights", result.text
    assert not submitted and not db.list_publications(clip["id"]) and not google.sessions


@pytest.mark.parametrize("change", ["unchanged", "rights", "bytes", "version"])
def test_manual_publish_rechecks_owned_source_and_exact_confirmed_file_at_start(env, api, monkeypatch, change):
    from pathlib import Path

    from clipfoundry import db
    from clipfoundry.autopilot import rights
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    item = make_item(tmp)
    clip = db.get_clip(item["clip_id"])
    source = db.insert("sources", {"platform": "local", "external_id": "owned-local-fixture"})
    rights.add_rule("source", source["id"], rights.OWNED, "My own video")
    db.update("projects", clip["project_id"], source_id=source["id"])
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    result = api.post(f"/api/clips/{clip['id']}/publish/youtube", headers=H, json={
        "title": "My own clip", "privacy": "public", "made_for_kids": False, "confirm": True})
    assert result.status_code == 200, result.text  # Eligible owned source and passing artifact are accepted.
    publication = result.json()
    if change == "rights":
        rights.add_rule("source", source["id"], rights.BLOCKED, "Permission withdrawn")
    elif change == "bytes":
        Path(clip["output_path"]).write_bytes(b"different bytes after confirmation")
    elif change == "version":
        alternative = tmp / "alternative.mp4"
        alternative.write_bytes(b"a newly selected version")
        version = db.create_version(clip["id"], "custom", status="ready", output_path=str(alternative))
        db.update_clip(clip["id"], active_version=version["id"])
    jobs.worker._run(publication["id"])
    after = db.get_publication(publication["id"])
    if change == "unchanged":
        assert after["status"] == "done" and len(google.videos) == 1
        return
    assert after["status"] == "failed", after
    assert after["info"]["code"] == ("rights" if change == "rights" else "approval_invalidated")
    assert not google.sessions and not google.videos


def test_manual_publish_respects_platform_agreement_and_failed_quality(env, api, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, rights
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    public_setup(api, "tiktok")
    db.save_settings({"tiktok_app_audited": True})
    item = make_item(tmp)
    clip = db.get_clip(item["clip_id"])
    source = db.insert("sources", {"platform": "local", "external_id": "licensed-local-fixture"})
    rights.add_rule("source", source["id"], rights.LICENSED, "License for YouTube only",
                    conditions={"platforms": ["youtube"], "third_party": True})
    db.update("projects", clip["project_id"], source_id=source["id"])
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    forbidden = api.post(f"/api/clips/{clip['id']}/publish/tiktok", headers=H, json={
        "description": "Licensed clip", "privacy": "PUBLIC_TO_EVERYONE", "confirm": True})
    assert forbidden.status_code == 400 and forbidden.json()["code"] == "rights", forbidden.text
    assert "allowed only on Youtube" in forbidden.json()["detail"]
    report = gate.report_for(clip)
    db.update("quality_reports", report["id"], status="failed", blockers=["Silence: no spoken story"])
    failed_qc = api.post(f"/api/clips/{clip['id']}/publish/youtube", headers=H, json={
        "title": "Licensed clip", "privacy": "public", "made_for_kids": False, "confirm": True})
    assert failed_qc.status_code == 400 and failed_qc.json()["code"] == "quality", failed_qc.text
    assert "Silence" in failed_qc.json()["detail"]
    assert not db.list_publications(clip["id"]) and not google.sessions and not tiktok.inits


def test_manual_legacy_clip_does_not_invent_an_autopilot_source_or_quality_requirement(env, api, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    video = tmp / "manual-original.mp4"
    video.write_bytes(b"manual legacy render fixture")
    project = db.create_project("Manual legacy project", origin="manual", status="ready")
    clip = db.create_clip(project["id"], start=0, end=20, duration=20, status="ready", output_path=str(video))
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    result = api.post(f"/api/clips/{clip['id']}/publish/youtube", headers=H, json={
        "title": "My manual clip", "privacy": "public", "made_for_kids": False, "confirm": True})
    assert result.status_code == 200, result.text
    jobs.worker._run(result.json()["id"])
    assert db.get_publication(result.json()["id"])["status"] == "done" and len(google.videos) == 1
    assert not db.select("sources") and not db.select("quality_reports")


def test_manual_unknown_final_outcome_holds_republish_and_recovers_read_only_once(env, api, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    clip_id = make_item(tmp)["clip_id"]
    account_id = db.get_account("youtube")["account_id"]
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    google.drop_final_reply, google.expire_sessions, google.hide_uploads = True, True, True
    body = {"title": "One confirmed upload despite a lost final reply", "privacy": "public",
            "made_for_kids": False, "confirm": True}
    first = api.post(f"/api/clips/{clip_id}/publish/youtube", headers=H, json=body)
    assert first.status_code == 200, first.text
    publication_id = first.json()["id"]
    jobs.worker._run(publication_id)
    held = db.get_publication(publication_id)
    assert held["status"] == "processing" and held["info"]["outcome_unknown"]
    assert len(google.videos) == 1 and not held["remote_id"]
    again = api.post(f"/api/clips/{clip_id}/publish/youtube", headers=H, json=body)
    assert again.status_code == 409 and "outcome is unknown" in again.json()["detail"]
    jobs.worker._run(publication_id)  # A delayed queue entry may only read, never start another upload.
    assert db.get_publication(publication_id)["info"]["outcome_unknown"] and len(google.videos) == 1
    db.save_account("youtube", account_id="another-channel", display_name="Another channel")
    wrong_account = api.post(f"/api/publications/{publication_id}/refresh", headers=H)
    assert wrong_account.status_code == 400 and wrong_account.json()["code"] == "reconnect"
    assert db.get_publication(publication_id)["status"] == "processing" and len(google.videos) == 1
    db.save_account("youtube", account_id=account_id, display_name="Original channel")
    refreshed = api.post(f"/api/publications/{publication_id}/refresh", headers=H)
    assert refreshed.status_code == 200 and refreshed.json()["info"]["outcome_unknown"]
    from clipfoundry.autopilot import publisher
    from clipfoundry.publish.common import PublishError

    def unavailable(*_args, **_kwargs):
        raise PublishError("YouTube is temporarily unavailable", "Use Refresh status later", "network")

    with monkeypatch.context() as unavailable_api:
        unavailable_api.setattr(publisher, "_youtube_upload_by_title", unavailable)
        response = api.post(f"/api/publications/{publication_id}/refresh", headers=H)
        assert response.status_code == 400 and response.json()["code"] == "network"
    assert db.get_publication(publication_id)["info"]["outcome_unknown"] and len(google.videos) == 1
    google.hide_uploads = False
    resolved = api.post(f"/api/publications/{publication_id}/refresh", headers=H)
    assert resolved.status_code == 200, resolved.text
    result = resolved.json()
    assert result["status"] == "done" and not result["info"]["outcome_unknown"]
    assert result["remote_id"] in google.videos and result["privacy"] == "public"
    assert result["delivery"]["audience_setup"] == "public_api_verified"
    calls_after_resolution = len(google.log)
    jobs.worker._run(publication_id)
    assert len(google.log) == calls_after_resolution and len(google.videos) == 1
    assert sum(1 for method, url in google.log if method == "POST" and "uploadType=resumable" in url) == 1


@pytest.mark.parametrize("evidence", ["older", "missing_time", "different_metadata", "ambiguous"])
def test_manual_unknown_recovery_never_accepts_an_unrelated_or_ambiguous_title(env, api, monkeypatch, evidence):
    import copy

    from clipfoundry import db
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    clip_id = make_item(tmp)["clip_id"]
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    google.drop_final_reply, google.expire_sessions, google.hide_uploads = True, True, True
    body = {"title": "A common title is insufficient evidence", "description": "Exact approved description",
            "tags": ["#science"], "privacy": "public", "made_for_kids": False, "confirm": True}
    first = api.post(f"/api/clips/{clip_id}/publish/youtube", headers=H, json=body)
    assert first.status_code == 200, first.text
    publication_id = first.json()["id"]
    jobs.worker._run(publication_id)
    held = db.get_publication(publication_id)
    assert held["info"]["outcome_unknown"]
    video = next(iter(google.videos.values()))
    if evidence == "older":
        video["uploaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(
            held["info"]["session_started"] - 60))
    elif evidence == "missing_time":
        video["uploaded_at"] = "not a platform date"
    elif evidence == "different_metadata":
        video["snippet"]["description"] = "An unrelated same-title video"
    else:
        duplicate = copy.deepcopy(video)
        duplicate["id"] = "unrelated-same-title-video"
        google.videos[duplicate["id"]] = duplicate
    google.hide_uploads = False
    reads = api.post(f"/api/publications/{publication_id}/refresh", headers=H)
    assert reads.status_code == 200, reads.text
    assert reads.json()["status"] == "processing" and reads.json()["info"]["outcome_unknown"]
    assert not reads.json()["remote_id"] and not reads.json()["url"]
    assert api.post(f"/api/clips/{clip_id}/publish/youtube", headers=H, json=body).status_code == 409
    assert sum(1 for method, url in google.log if method == "POST" and "uploadType=resumable" in url) == 1


def test_duplicate_processing_queue_entry_reads_tiktok_outcome_without_another_init(env, api, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api, "tiktok")
    db.save_settings({"tiktok_app_audited": True})
    clip_id = make_item(tmp, "tiktok")["clip_id"]
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    result = api.post(f"/api/clips/{clip_id}/publish/tiktok", headers=H, json={
        "description": "One confirmed TikTok post", "privacy": "PUBLIC_TO_EVERYONE", "confirm": True})
    assert result.status_code == 200, result.text
    publication_id = result.json()["id"]
    jobs.worker._run(publication_id)
    assert db.get_publication(publication_id)["status"] == "done" and len(tiktok.inits) == 1
    db.update_publication(publication_id, status="processing")  # Recovered/stale queue state, known platform handle.
    jobs.worker._run(publication_id)
    assert db.get_publication(publication_id)["status"] == "done" and len(tiktok.inits) == 1


def test_known_manual_failure_remains_retryable_with_new_explicit_confirmation(env, api, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import jobs
    from clipfoundry.publish.common import PublishError

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    clip_id = make_item(tmp)["clip_id"]
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    body = {"title": "A retry after a known refusal", "privacy": "public", "made_for_kids": False,
            "confirm": True}
    first = api.post(f"/api/clips/{clip_id}/publish/youtube", headers=H, json=body)
    assert first.status_code == 200, first.text
    def refuse_title(*_args, **_kwargs):
        raise PublishError("YouTube rejected this title before starting a transfer.", "Review the title.",
                           "invalidTitle")

    with monkeypatch.context() as refusal:
        refusal.setattr(jobs.youtube, "_start_session", refuse_title)
        jobs.worker._run(first.json()["id"])
    failed = db.get_publication(first.json()["id"])
    assert failed["status"] == "failed" and failed["info"]["code"] == "invalidTitle"
    assert not google.videos and not jobs.unknown_outcome(failed)
    retry = api.post(f"/api/clips/{clip_id}/publish/youtube", headers=H, json=body)
    assert retry.status_code == 200, retry.text
    jobs.worker._run(retry.json()["id"])
    assert db.get_publication(retry.json()["id"])["status"] == "done" and len(google.videos) == 1


@pytest.mark.parametrize("final_chunk", [False, True])
def test_manual_resume_never_sends_changed_bytes_into_an_existing_session(env, api, monkeypatch, final_chunk):
    from pathlib import Path

    from clipfoundry import db
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    item = make_item(tmp, size=100000 if final_chunk else 300000)
    clip = db.get_clip(item["clip_id"])
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)
    monkeypatch.setattr(jobs.worker, "later", lambda _pub_id, _at: None)
    google.rate_limit_puts, google.retry_after = 1, "600"
    first = api.post(f"/api/clips/{clip['id']}/publish/youtube", headers=H, json={
        "title": "The exact confirmed bytes", "privacy": "public", "made_for_kids": False, "confirm": True})
    assert first.status_code == 200, first.text
    publication_id = first.json()["id"]
    jobs.worker._run(publication_id)
    waiting = db.get_publication(publication_id)
    assert waiting["status"] == "queued" and waiting["info"]["upload_session"]
    Path(clip["output_path"]).write_bytes(b"changed video bytes")
    jobs.worker._run(publication_id)
    after = db.get_publication(publication_id)
    if final_chunk:
        assert after["status"] == "processing" and after["info"]["outcome_unknown"]
    else:
        assert after["status"] == "failed" and after["info"]["code"] == "approval_invalidated"
    assert not google.videos and len(google.sessions) == 1
    assert all(not session["data"] for session in google.sessions.values())

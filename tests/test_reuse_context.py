"""Changed recorded reuse terms refresh checks and never rewrite an approved post behind its owner's back."""
from __future__ import annotations

import time

import pytest

from quality_stub import passed_report
from test_audience import env  # noqa: F401 - isolated official-API stand-ins
from test_autopilot_publish import connect, make_item, run_publish

TEXT = "Talk to customers first, then build the product they asked for."
CREDIT = "Credit: Creator — https://example.com/original-video"


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_tiktok": False})
    return tmp_path


def make_clip(tmp_path, *, origin="autopilot", license_="youtube"):
    from clipfoundry import db
    from clipfoundry.autopilot import packaging

    source = db.insert("sources", {"platform": "youtube", "external_id": "abc12345678", "status": "analyzed",
                                   "url": "https://www.youtube.com/watch?v=abc12345678", "license": license_,
                                   "title": "Talk to customers first", "channel_title": "Creator",
                                   "rights_status": "manual"})
    project = db.create_project("Synthetic source", origin=origin, source_id=source["id"], status="ready")
    output = tmp_path / "synthetic.mp4"
    output.write_bytes(b"placeholder: media checks are represented by a stored report")
    clip = db.create_clip(project["id"], title="Talk to customers first", start=0, end=20, duration=20,
                          caption_text=TEXT, output_path=str(output), status="ready")
    meta = packaging.package(clip, source, "youtube", db.get_settings())
    return source, clip, meta


def agreement(source, *, attribution=CREDIT, third_party=False):
    from clipfoundry.autopilot import rights

    return rights.add_rule("source", source["id"], rights.LICENSED, "Synthetic signed permission for regression",
                           conditions={"kind": "agreement", "attribution": attribution,
                                       "platforms": ["youtube"], "third_party": third_party})


def credit_failure(clip):
    from clipfoundry import db
    from clipfoundry.autopilot import gate

    return gate.run(clip, db.get_settings())


def test_new_agreement_credit_is_used_before_cached_source_rights_are_refreshed(data):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, packaging, rights

    source, clip, old_meta = make_clip(data)
    passed_report(clip, ("youtube",))
    agreement(source)
    assert db.fetch("sources", source["id"])["rights_status"] == "manual"
    assert rights.current_attribution(source) == CREDIT
    for _ in range(20):
        allowed, reason = gate.schedulable(clip, "youtube", old_meta["id"])
        assert not allowed and "current reuse terms" in reason
    assert len(db.select("worker_jobs", "kind = 'quality_check'")) == 1
    rep = credit_failure(clip)
    assert rep["status"] == "passed" and rep["metadata"]["youtube"]["status"] == "failed"
    assert "missing required source attribution" in rep["metadata"]["youtube"]["problems"][0]
    repair = gate.repair_text(clip, rep, 10)
    assert repair and repair["kind"] == "package_clip"
    # Queueing a repair retains the selected text; only the actual packaging job replaces generated candidates.
    assert gate._selected(clip["id"], "youtube")["id"] == old_meta["id"]
    meta = packaging.package(clip, source, "youtube", db.get_settings())
    assert CREDIT in meta["description"]
    rep = credit_failure(clip)
    assert rep["metadata"]["youtube"]["status"] == "passed"
    assert gate.schedulable(clip, "youtube", meta["id"]) == (True, "")


def test_license_revocation_invalidates_report_without_granting_permission(data):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, rights

    source, clip, meta = make_clip(data, license_="creativeCommon")
    rep = passed_report(clip, ("youtube",))
    assert gate.context_valid(rep, clip)
    db.update("sources", source["id"], license="youtube")
    for _ in range(20):
        assert not gate.schedulable(clip, "youtube", meta["id"])[0]
    assert len(db.select("worker_jobs", "kind = 'quality_check'")) == 1
    with pytest.raises(rights.RightsBlocked):
        rights.gate(db.fetch("sources", source["id"]), "publish")


def test_current_terms_refresh_precedes_an_old_sound_rights_failure(data):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, queue
    from clipfoundry.pipeline import quality

    source, clip, _ = make_clip(data)
    rule = agreement(source, attribution="")
    db.insert("clip_analysis", {"clip_id": clip["id"], "audio": {"reaction_seconds": 18}}, key="clip_id")
    rep = passed_report(clip, ("youtube",))
    sound = quality.check("sound_rights", "Sound covered by the reuse terms", quality.HEURISTIC, quality.FAIL,
                          "The previous agreement did not cover third-party audio.")
    db.update("quality_reports", rep["id"], status="failed", checks=[sound], blockers=[sound["detail"]])
    db.update("source_rights", rule["id"], conditions={**rule["conditions"], "third_party": True})
    with pytest.raises(queue.Wait, match="current reuse terms"):
        gate.verify_file(clip, clip["output_path"])
    assert credit_failure(clip)["status"] == "passed"
    assert gate.verify_file(clip, clip["output_path"])["status"] == "passed"


def test_returning_to_previous_terms_enqueues_one_new_check_not_a_completed_job(data):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, queue

    source, clip, _ = make_clip(data)
    rule = agreement(source, attribution="")
    first = gate.request(clip)
    passed_report(clip, ("youtube",))
    db.update("worker_jobs", first["id"], status="completed")
    db.update("source_rights", rule["id"], conditions={**rule["conditions"], "third_party": True})
    second = gate.request(clip)
    credit_failure(clip)
    db.update("worker_jobs", second["id"], status="completed")
    db.update("source_rights", rule["id"], conditions=rule["conditions"])
    for _ in range(15):
        with pytest.raises(queue.Wait):
            gate.verify_file(clip, clip["output_path"])
    jobs = db.select("worker_jobs", "kind = 'quality_check'")
    assert len(jobs) == 3 and sum(job["status"] == "queued" for job in jobs) == 1


@pytest.mark.parametrize("status", ["failed", "canceled"])
def test_terms_refresh_does_not_revive_stopped_quality_work(data, status):
    from clipfoundry import db
    from clipfoundry.autopilot import gate

    source, clip, meta = make_clip(data)
    passed_report(clip, ("youtube",))
    job = gate.request(clip)
    db.update("worker_jobs", job["id"], status=status)
    agreement(source)
    for _ in range(15):
        assert not gate.schedulable(clip, "youtube", meta["id"])[0]
    assert len(db.select("worker_jobs", "kind = 'quality_check'")) == 1
    assert db.fetch("worker_jobs", job["id"])["status"] == status


@pytest.mark.parametrize("preserved", ["manual", "edit", "version", "source_canceled", "intake_canceled",
                                       "package_failed", "package_canceled", "approved", "published"])
def test_credit_repair_preserves_edits_existing_posts_and_stopped_work(data, preserved):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, queue

    source, clip, _ = make_clip(data, origin="manual" if preserved == "manual" else "autopilot")
    passed_report(clip, ("youtube",))
    agreement(source)
    rep = credit_failure(clip)
    if preserved in ("edit", "version"):
        db.update_clip(clip["id"], **({"edit": {"caption_text": "Owner's edit"}} if preserved == "edit" else
                                    {"active_version": "owner-version"}))
    elif preserved == "source_canceled":
        db.update("sources", source["id"], status="canceled")
    elif preserved == "intake_canceled":
        db.update("sources", source["id"], intake={"canceled": True})
    elif preserved.startswith("package_"):
        job = queue.enqueue("package_clip", {"clip_id": clip["id"]}, ref=("clip", clip["id"]))
        db.update("worker_jobs", job["id"], status=preserved.removeprefix("package_"))
    elif preserved in ("approved", "published"):
        db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "youtube", "status": preserved,
                                             "title": "Owner text", "description": "Keep this text",
                                             "privacy": "private"})
    with db.connect() as conn:
        before = list(conn.iterdump())
    assert gate.repair_text(db.get_clip(clip["id"]), rep, 10) is None
    with db.connect() as conn:
        assert list(conn.iterdump()) == before


def test_credit_repairs_are_bounded_per_current_terms(data):
    from clipfoundry import db
    from clipfoundry.autopilot import gate

    source, clip, _ = make_clip(data)
    passed_report(clip, ("youtube",))
    agreement(source)
    rep = credit_failure(clip)
    first = gate.repair_text(clip, rep, 10)
    assert gate.repair_text(clip, rep, 10)["id"] == first["id"]
    db.update("worker_jobs", first["id"], status="completed")
    second = gate.repair_text(clip, rep, 10)
    assert second["id"] != first["id"]
    db.update("worker_jobs", second["id"], status="completed")
    assert gate.repair_text(clip, rep, 10) is None
    assert len(db.select("worker_jobs", "kind = 'package_clip'")) == 2


@pytest.mark.parametrize("platform,meta", [("youtube", {"description": TEXT}),
                                         ("tiktok", {"caption": TEXT}), ("tiktok", {"description": TEXT})])
def test_required_credit_checks_actual_platform_text_and_preserves_links(platform, meta):
    from clipfoundry.autopilot import packaging

    field = next(iter(meta))
    assert packaging.attribution_problem(meta, platform, CREDIT)
    valid = {field: TEXT + "\n\n" + CREDIT + "\nOwner's extra text"}
    assert not packaging.attribution_problem(valid, platform, CREDIT)
    changed_url = {field: TEXT + "\n" + CREDIT.replace("original-video", "original/video")}
    assert packaging.attribution_problem(changed_url, platform, CREDIT)
    non_english = "著作者: 大地 — https://example.com/original-video"
    assert not packaging.attribution_problem({field: non_english}, platform, non_english)
    assert packaging.attribution_problem({field: non_english.replace("大地", "海")}, platform, non_english)
    multiline = "Credit: Creator\nhttps://example.com/original-video"
    assert not packaging.attribution_problem({field: TEXT + "\n\n" + multiline}, platform, multiline)


def attach_source(item):
    from clipfoundry import db

    source = db.insert("sources", {"platform": "youtube", "external_id": "abc12345678", "status": "analyzed",
                                   "url": "https://www.youtube.com/watch?v=abc12345678", "title": item["title"]})
    clip = db.get_clip(item["clip_id"])
    db.update_project(clip["project_id"], source_id=source["id"])
    return source, clip


def test_current_selected_metadata_cannot_replace_missing_credit_in_an_approved_post(env):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, queue

    google, tiktok, tmp = env
    connect(google, tiktok)
    item = make_item(tmp, approve={"options": {"made_for_kids": False}})
    source, clip = attach_source(item)
    agreement(source)
    passed_report(clip, ("youtube",))
    db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": "youtube", "selected": 1,
                                       "title": item["title"], "description": item["description"] + "\n" + CREDIT})
    before = db.fetch("scheduled_publications", item["id"])
    with pytest.raises(queue.Fail, match="missing the credit"):
        run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "awaiting_approval" and not after["approval"]
    assert not google.sessions and not google.videos
    assert {k: after[k] for k in ("title", "description", "privacy")} == {
        k: before[k] for k in ("title", "description", "privacy")}
    assert gate._selected(clip["id"], "youtube")["description"].endswith(CREDIT)


def test_stale_terms_on_an_awaiting_post_queue_one_check_and_never_approve(env):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler

    google, tiktok, tmp = env
    connect(google, tiktok)
    autopublish.enable("youtube", "private", False, 0, 0, 24, True)
    item = make_item(tmp, planned_in=-60)
    source, clip = attach_source(item)
    agreement(source, attribution="")
    before_text = (item["title"], item["description"], item["privacy"])
    for _ in range(20):
        scheduler.process_due(db.get_settings(), time.time())
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "awaiting_approval" and not after["approval"]
    assert (after["title"], after["description"], after["privacy"]) == before_text
    assert "current reuse terms" in after["status_note"]
    assert len(db.select("worker_jobs", "kind = 'quality_check'")) == 1
    assert not db.select("worker_jobs", "kind = 'publish'") and not google.sessions


def test_current_credited_suggestion_does_not_automatically_approve_uncredited_post(env):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler

    google, tiktok, tmp = env
    connect(google, tiktok)
    autopublish.enable("youtube", "private", False, 0, 0, 24, True)
    item = make_item(tmp, planned_in=-60)
    source, clip = attach_source(item)
    agreement(source)
    db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": "youtube", "selected": 1,
                                       "title": item["title"], "description": item["description"] + "\n" + CREDIT})
    passed_report(clip, ("youtube",))
    for _ in range(20):
        scheduler.process_due(db.get_settings(), time.time())
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "awaiting_approval" and not after["approval"]
    assert after["description"] == item["description"] and after["privacy"] == "private"
    assert "required source credit" in after["status_note"]
    assert not db.select("worker_jobs", "kind IN ('publish', 'quality_check', 'package_clip')")
    assert not google.sessions and not google.videos


def test_owner_can_fix_and_reapprove_unstarted_post_without_reusing_old_upload_text(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import publisher, queue, scheduler
    from clipfoundry.publish import youtube

    google, tiktok, tmp = env
    connect(google, tiktok)
    item = make_item(tmp, approve={"options": {"made_for_kids": False}})
    source, clip = attach_source(item)
    agreement(source, attribution="")
    passed_report(clip, ("youtube",))
    original = google.handle
    busy = [True]

    def initially_busy(handler, method, body):
        if busy[0] and method == "POST" and handler.path.startswith("/upload/youtube/v3/videos"):
            busy[0] = False
            return handler._send(429, {"error": {"code": 429, "message": "rate limited"}},
                                 {"Retry-After": "600"})
        return original(handler, method, body)

    monkeypatch.setattr(google, "handle", initially_busy)
    with pytest.raises(queue.Wait):
        run_publish(item["id"])
    waiting = db.fetch("scheduled_publications", item["id"])
    old_pub = db.get_publication(waiting["publication_id"])
    assert not old_pub["info"].get("upload_session") and not google.sessions
    agreement(source)
    passed_report(clip, ("youtube",))
    monkeypatch.setattr(publisher, "blocked_until", lambda _platform: (0.0, ""))
    with pytest.raises(queue.Fail, match="missing the credit"):
        run_publish(item["id"])
    assert db.fetch("scheduled_publications", item["id"])["status"] == "awaiting_approval"
    # A never-started local row is editable after a hold; preserve its identity and re-approve exact new text.
    scheduler.edit(item["id"], {"description": TEXT + "\n\n" + CREDIT + "\nOwner's extra text"})
    scheduler.approve(item["id"], {"options": {"made_for_kids": False}})
    monkeypatch.setattr(publisher, "blocked_until", lambda _platform: (0.0, ""))
    run_publish(item["id"])
    finished = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(finished["publication_id"])
    assert finished["status"] == "published" and pub["id"] == old_pub["id"]
    assert len(google.sessions) == len(google.videos) == 1
    uploaded = google.videos[pub["remote_id"]]
    assert uploaded["snippet"]["description"] == finished["description"]
    assert CREDIT in uploaded["snippet"]["description"]
    assert uploaded["status"]["privacyStatus"] == "private" and "publishAt" not in uploaded["status"]


def test_manual_publication_checks_its_own_credit_and_keeps_valid_owner_text(data):
    from clipfoundry import db
    from clipfoundry.publish import jobs
    from clipfoundry.publish.common import PublishError

    source, clip, _ = make_clip(data)
    agreement(source)
    passed_report(clip, ("youtube",))
    pub = db.create_publication(clip["id"], "youtube", project_id=clip["project_id"], video_path=clip["output_path"],
                                title=clip["title"], description=TEXT, requested_privacy="private")
    with pytest.raises(PublishError, match="missing the credit"):
        jobs._check_manual_publication(pub, db.get_settings())
    description = TEXT + "\n\n" + CREDIT + "\nMy own extra note."
    db.update_publication(pub["id"], description=description)
    jobs._check_manual_publication(db.get_publication(pub["id"]), db.get_settings())
    assert db.get_publication(pub["id"])["description"] == description
    # Once the exact upload is underway, term/text changes never abandon its session for a new upload.
    db.update_publication(pub["id"], description=TEXT, info={"upload_session": "synthetic-session"})
    jobs._check_manual_publication(db.get_publication(pub["id"]), db.get_settings())
    assert db.get_publication(pub["id"])["info"]["upload_session"] == "synthetic-session"


def test_unstarted_tiktok_publication_uses_the_reapproved_route_and_current_features(env):
    from clipfoundry import db
    from clipfoundry.autopilot import publisher, scheduler

    google, tiktok, tmp = env
    connect(google, tiktok)
    db.save_settings({"audience_tiktok": "owner_only"})
    item = make_item(tmp, "tiktok", approve={"privacy": "SELF_ONLY", "options": {"mode": "direct"}})
    clip = db.get_clip(item["clip_id"])
    initial = publisher._publication(item, clip["output_path"], "", clip)
    scheduler.edit(item["id"], {"options": {"mode": "inbox"}})
    approved = scheduler.approve(item["id"], {"privacy": "", "options": {"mode": "inbox"}})
    db.update_clip(clip["id"], score=83)
    current = publisher._publication(approved, clip["output_path"], "", db.get_clip(clip["id"]))
    assert current["id"] == initial["id"] and current["mode"] == "inbox" and current["requested_privacy"] == ""
    assert current["options"]["mode"] == "inbox" and current["features"]["viral_potential"] == 83
    assert not tiktok.uploads


def test_unknown_upload_outcome_keeps_same_identity_after_credit_terms_change(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import publisher
    from clipfoundry.publish import youtube

    google, tiktok, tmp = env
    connect(google, tiktok)
    monkeypatch.setattr(youtube, "_pause", lambda *_args: None)
    google.drop_final_reply = google.expire_sessions = google.hide_uploads = True
    item = make_item(tmp, approve={"options": {"made_for_kids": False}})
    source, clip = attach_source(item)
    agreement(source, attribution="")
    passed_report(clip, ("youtube",))
    run_publish(item["id"])
    row = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(row["publication_id"])
    assert row["status"] == "reconciling" and pub["info"].get("final_chunk_at")
    agreement(source)
    monkeypatch.setattr(publisher, "blocked_until", lambda _platform: (0.0, ""))
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "reconciling" and after["publication_id"] == pub["id"]
    assert not google.sessions and len(google.videos) == 1  # The fake deliberately expired the original session.
    assert CREDIT not in db.get_publication(pub["id"])["description"]

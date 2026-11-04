"""Local review never becomes an upload grant; owner assertions bind to the exact eventual post."""
from __future__ import annotations

import copy
import time

import pytest

from quality_stub import passed_report
from test_autopilot_publish import connect, env, make_item, run_publish  # noqa: F401


def attach_source(item, *, license_="youtube"):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    source = db.insert("sources", {"platform": "youtube", "external_id": "review12345", "status": "analyzed",
                                   "url": "https://www.youtube.com/watch?v=review12345", "license": license_,
                                   "title": "Talk to customers first", "rights_status": rights.MANUAL})
    clip = db.get_clip(item["clip_id"])
    db.update_project(clip["project_id"], source_id=source["id"])
    passed_report(clip, (item["platform"],))
    return source, clip


def approved_unknown(env, *, platform="youtube", public=False):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler
    from clipfoundry.publish import tiktok

    g, t, tmp = env
    connect(g, t)
    if public:
        db.save_settings({"audience_youtube": "public", "audience_youtube_confirmed_at": time.time()})
    item = make_item(tmp, platform)
    source, clip = attach_source(item)
    fields = {"options": {"made_for_kids": False}}
    creator = None
    if public:
        fields["privacy"] = "public"
    if platform == "tiktok":
        fields = {"privacy": "SELF_ONLY", "options": {"mode": "direct"}}
        creator = tiktok.creator_info(tiktok.Token(db.get_settings()))
    approved = scheduler.approve(item["id"], fields, creator, reuse_confirmed=True,
                                 reuse_basis="I checked the creator's written permission for this exact clip and sound.")
    return approved, source, clip


def test_uncovered_source_can_be_prepared_without_becoming_owned(env):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    _g, _t, tmp = env
    item = make_item(tmp)
    source, _clip = attach_source(item)
    assert rights.review_before_publish()
    assert rights.scheduling_allowed(source, "youtube") == (True, "")
    assert not rights.publication_allowed(source, "youtube", publication=item)[0]
    assert rights.evaluate(source)["status"] == rights.MANUAL
    assert db.fetch("sources", source["id"])["rights_status"] == rights.MANUAL
    assert not db.select("source_rights")


def test_review_discovery_ignores_missing_platform_coverage_but_not_blocks(env):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    source = {"id": "unrecorded", "platform": "youtube", "signal_id": "search", "url": "https://example.com/video"}
    settings = {**db.get_settings(), "autopilot_public_videos": False}
    assert rights.discovery_publishable(source, settings, platforms={"youtube"})
    assert rights.local_allowed(source, settings=settings)
    rule = rights.add_rule("source", source["id"], rights.BLOCKED, "Owner block")
    assert not rights.discovery_publishable(source, settings, all_rules=[rule], platforms={"youtube"})
    assert not rights.local_allowed(source, settings=settings)
    for blocked in ({**source, "status": "canceled"}, {**source, "intake": {"removed": True}}):
        assert not rights.discovery_publishable(blocked, settings, all_rules=[], platforms={"youtube"})


def test_turning_review_off_restores_coverage_requirement(env):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    _g, _t, tmp = env
    source, _clip = attach_source(make_item(tmp))
    settings = {**db.get_settings(), "autopilot_review_before_publish": False}
    assert not rights.scheduling_allowed(source, "youtube", settings)[0]
    assert not rights.discovery_publishable(source, settings, platforms={"youtube"})


@pytest.mark.parametrize("platform,public", [("youtube", False), ("youtube", True), ("tiktok", False)])
def test_exact_owner_approval_publishes_without_changing_recorded_source_rights(env, platform, public):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    item, source, _clip = approved_unknown(env, platform=platform, public=public)
    assert item["approval"]["by"] == "you"
    assert rights.review_info(item)["confirmed"]
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(after["publication_id"])
    assert after["status"] == "published"
    assert pub["options"]["reuse_confirmation"] == item["reuse_confirmation"]
    assert not rights.confirmation_problem(pub)
    assert db.fetch("sources", source["id"])["rights_status"] == rights.MANUAL
    assert not db.select("source_rights")
    if platform == "youtube":
        assert env[0].videos[pub["remote_id"]]["status"]["privacyStatus"] == ("public" if public else "private")


@pytest.mark.parametrize("change", ["title", "description", "tags", "privacy", "options", "audience", "bytes",
                                   "source_url", "source_license", "account", "version", "basis_removed",
                                   "owner_removed", "bad_binding", "wrong_platform"])
def test_reuse_assertion_cannot_cover_changed_content_or_destination(env, change):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    item, source, clip = approved_unknown(env)
    modified = copy.deepcopy(item)
    if change in ("title", "description", "privacy"):
        modified[change] += " changed"
    elif change == "tags":
        modified["tags"].append("changed")
    elif change == "options":
        modified["options"]["made_for_kids"] = True
    elif change == "audience":
        modified["audience"]["group_version"] += 1
    elif change == "bytes":
        from pathlib import Path

        Path(clip["output_path"]).write_bytes(b"changed bytes")
    elif change == "source_url":
        db.update("sources", source["id"], url="https://example.com/another-video")
    elif change == "source_license":
        db.update("sources", source["id"], license="creativeCommon")
    elif change == "account":
        db.save_account("youtube", account_id="different-channel")
    elif change == "version":
        db.update_clip(clip["id"], active_version="missing-version")
    elif change == "basis_removed":
        modified["reuse_confirmation"]["basis"] = ""
    elif change == "owner_removed":
        modified["reuse_confirmation"]["owner_confirmed"] = False
    elif change == "bad_binding":
        modified["reuse_confirmation"]["binding"]["video_sha256"] = "0" * 64
    else:
        modified["platform"] = "tiktok"
    assert rights.confirmation_problem(modified)


@pytest.mark.parametrize("stop", ["blocked", "canceled", "removed", "missing"])
def test_owner_assertion_never_overrides_explicit_stops_or_missing_source(env, stop):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    item, source, _clip = approved_unknown(env)
    if stop == "blocked":
        rights.add_rule("source", source["id"], rights.BLOCKED, "Owner explicitly stopped this video")
    elif stop == "missing":
        db.execute("DELETE FROM sources WHERE id = ?", (source["id"],))
    else:
        db.update("sources", source["id"], status=stop)
    assert not rights.publication_allowed(source, "youtube", publication=item)[0]
    with pytest.raises(ValueError):
        rights.make_reuse_confirmation(item, "A newly entered basis cannot override this stop")


def test_uncovered_manual_publish_cannot_borrow_a_scheduled_assertion(env):
    from clipfoundry import db
    from clipfoundry.publish import jobs
    from clipfoundry.publish.common import PublishError

    item, _source, clip = approved_unknown(env)
    with pytest.raises(PublishError, match="Not covered"):
        jobs.manual_eligibility(clip, "youtube", clip["output_path"], "", db.get_settings())
    altered = {**item, "description": "A different confirmed manual post"}
    with pytest.raises(PublishError, match="changed after"):
        jobs.manual_eligibility(clip, "youtube", clip["output_path"], "", db.get_settings(), publication=altered)


def test_confirmation_cannot_be_used_for_a_different_requested_platform(env):
    from clipfoundry.autopilot import rights

    item, source, _clip = approved_unknown(env)
    assert rights.publication_allowed(source, "youtube", publication=item)[0]
    allowed, why = rights.publication_allowed(source, "tiktok", publication=item)
    assert not allowed and "platform" in why


def test_owner_review_does_not_waive_known_credit_when_recorded_coverage_is_insufficient(env):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, rights

    _g, _t, tmp = env
    item = make_item(tmp)
    source, clip = attach_source(item)
    credit = "Credit: Original creator — https://example.com/creator"
    # Commercial use is not covered by this rule, so the source truthfully remains Not covered.
    source["local_path"] = str(tmp / "creator-original.mp4")
    db.update("sources", source["id"], local_path=source["local_path"])
    rights.add_rule("folder", str(tmp), rights.LICENSED, "Original limited agreement",
                    conditions={"commercial": False, "attribution": credit, "platforms": ["youtube"]})
    assert rights.evaluate(source)["status"] == rights.MANUAL
    assert rights.current_attribution(source) == credit
    passed_report(clip, ("youtube",))
    item["reuse_confirmation"] = rights.make_reuse_confirmation(item, "Separate written permission for this post")
    assert rights.publication_allowed(source, "youtube", publication=item)[0]
    with pytest.raises(gate.CreditRequired):
        gate.verify_file(clip, clip["output_path"], publication=item)
    item["description"] += "\n\n" + credit
    item["reuse_confirmation"] = rights.make_reuse_confirmation(item, "Separate written permission with source credit")
    assert gate.verify_file(clip, clip["output_path"], publication=item)["status"] == "passed"


def test_uncertain_source_sound_can_schedule_but_needs_exact_owner_review_to_upload(env):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, queue, rights
    from clipfoundry.pipeline import quality

    _g, _t, tmp = env
    item = make_item(tmp)
    source, clip = attach_source(item)
    rights.add_rule("source", source["id"], rights.LICENSED, "Creator agreement",
                    conditions={"platforms": ["youtube"], "third_party": False})
    db.insert("clip_analysis", {"clip_id": clip["id"], "audio": {"reaction_seconds": 18}}, key="clip_id")
    passed_report(clip, ("youtube",))
    report = gate.run(clip, db.get_settings())
    assert report["status"] == "passed"
    assert report["coverage"]["needs_reuse_review"]
    assert gate.sound_rights_check(clip)["status"] == quality.WARN
    assert rights.review_info(item)["required"]
    with pytest.raises(gate.ReuseReviewRequired):
        gate.verify_file(clip, clip["output_path"], publication=item)
    item["reuse_confirmation"] = rights.make_reuse_confirmation(item, "Written permission also covers this sound")
    assert gate.verify_file(clip, clip["output_path"], publication=item)["status"] == "passed"


def test_review_mode_never_turns_physical_media_failures_into_reuse_warnings(env):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, rights
    from clipfoundry.pipeline import quality

    _g, _t, tmp = env
    item = make_item(tmp)
    _source, clip = attach_source(item)
    report = passed_report(clip, ("youtube",))
    broken = quality.check("decode", "Video decodes", quality.DETERMINISTIC, quality.FAIL, "Broken media")
    db.update("quality_reports", report["id"], status="failed", checks=[broken], blockers=["Broken media"])
    current = gate.run(clip, db.get_settings())
    assert current["status"] == "failed" and current["coverage"]["needs_reuse_review"]
    item["reuse_confirmation"] = rights.make_reuse_confirmation(item, "Written creator permission")
    with pytest.raises(Exception, match="did not pass the final quality"):
        gate.verify_file(clip, clip["output_path"], publication=item)

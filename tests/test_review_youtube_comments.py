"""YouTube audience answers survive every upload path; comments are explained, never promised or changed."""
from __future__ import annotations

import time

import pytest

from test_audience import api, env  # noqa: F401 - isolated local platform fixtures
from test_autopilot_publish import H, connect, make_item, run_publish
from test_public_publishing import public_setup
from test_youtube import _connect, _publish, _wait, app_client, clip, google  # noqa: F401


@pytest.mark.parametrize("invalid", [None, "false", "true", "", 0, 1, [], {}])
def test_low_level_upload_requires_a_real_owner_boolean(invalid):
    from clipfoundry.publish import youtube
    from clipfoundry.publish.common import PublishError

    with pytest.raises(PublishError, match="made for kids"):
        youtube.video_body("A title", "A description", [], "private", invalid)


@pytest.mark.parametrize("path,body", [
    ("/api/clips/no-clip/publish/youtube", {"confirm": True}),
    ("/api/autopilot/auto-publish", {"agreed": True}),
    ("/api/autopilot/scheduled/no-post/approve", {"confirm": True}),
    ("/api/autopilot/scheduled/bulk-approve", {"token": "not-a-preview", "confirm": True}),
])
@pytest.mark.parametrize("invalid", ["false", "true", 0, 1])
def test_http_choices_do_not_coerce_ambiguous_saved_answers(api, path, body, invalid):
    response = api.post(path, headers=H, json={**body, "made_for_kids": invalid})
    assert response.status_code == 422, response.text
    assert any(error["loc"][-1] == "made_for_kids" for error in response.json()["detail"])


@pytest.mark.parametrize("kids", [False, True])
def test_manual_upload_sends_exact_answer_and_explains_private_comments(app_client, google, clip, kids):
    c, original_bytes = clip
    _connect(app_client, google)
    response = _publish(app_client, c["id"], made_for_kids=kids)
    assert response.status_code == 200, response.text
    pub = _wait(app_client, response.json()["id"])
    assert pub["status"] == "done", pub
    video = google.videos[pub["remote_id"]]
    assert video["bytes"] == original_bytes
    assert video["status"]["selfDeclaredMadeForKids"] is kids
    assert pub["options"]["made_for_kids"] is kids
    readback = pub["info"]["youtube_audience"]
    assert readback["requested_made_for_kids"] is kids
    assert readback["self_declared_made_for_kids"] is kids
    assert readback["made_for_kids"] is None  # fake API did not report its independent audience determination
    assert readback["comments_reason"] == "private" and "Private" in readback["comments_note"]


@pytest.mark.parametrize("kids", [False, True])
def test_scheduled_public_upload_keeps_explicit_answer_and_reports_returned_evidence(env, api, kids):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    g, t, tmp = env
    connect(g, t)
    public_setup(api)
    item = make_item(tmp, approve={"privacy": "public", "options": {"made_for_kids": kids}})
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(after["publication_id"])
    assert after["status"] == "published" and after["options"]["made_for_kids"] is kids
    assert g.videos[pub["remote_id"]]["status"]["selfDeclaredMadeForKids"] is kids
    assert pub["info"]["youtube_audience"]["comments_reason"] == ("made_for_kids" if kids else "not_reported")
    # The platform can classify a video differently. Read it on the existing Refresh status call, without
    # rewriting the owner answer, granting a new upload or claiming that a comment setting was returned.
    g.videos[pub["remote_id"]]["status"]["madeForKids"] = True
    refreshed = jobs.refresh(pub)
    assert refreshed["options"]["made_for_kids"] is kids
    assert refreshed["info"]["youtube_audience"]["made_for_kids"] is True
    assert refreshed["info"]["youtube_audience"]["comments_reason"] == "made_for_kids"
    assert len(g.videos) == 1


@pytest.mark.parametrize("kids", [False, True])
def test_automatic_permission_retains_owner_answer_on_wire(env, kids):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler

    g, t, tmp = env
    connect(g, t)
    db.save_settings({"autopilot_review_before_publish": False})
    consent = autopublish.enable("youtube", "private", kids, 0, 0, 24, True)
    item = make_item(tmp)
    assert scheduler.auto_approve(item, db.get_settings(), time.time())
    approved = db.fetch("scheduled_publications", item["id"])
    assert approved["options"]["made_for_kids"] is kids
    assert consent["settings"]["made_for_kids"] is kids
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(after["publication_id"])
    assert g.videos[pub["remote_id"]]["status"]["selfDeclaredMadeForKids"] is kids


def test_corrupted_legacy_answer_is_held_instead_of_silently_marked_for_children(env):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler
    from clipfoundry.publish.common import PublishError

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp)
    with pytest.raises(PublishError, match="made for kids"):
        scheduler.check_platform({**item, "options": {"made_for_kids": "false"}})
    db.save_settings({"autopilot_review_before_publish": False})
    consent = autopublish.enable("youtube", "private", False, 0, 0, 24, True)
    db.update("publish_consents", consent["id"], settings={**consent["settings"], "made_for_kids": "false"})
    assert not scheduler.auto_approve(item, db.get_settings(), time.time())
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "awaiting_approval" and not after["approval"]
    assert not g.videos


@pytest.mark.parametrize("kids", [False, True])
def test_bulk_upload_keeps_existing_answer_instead_of_the_common_missing_answer(env, kids):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review
    from test_review_bulk import draft

    g, t, tmp = env
    connect(g, t)
    db.save_settings({"autopilot_tiktok": False})
    item, _, _ = draft(tmp, unknown=False, kids=kids)
    preview = bulk_review.preview([item["id"]])
    assert preview["items"][0]["eligible"], preview["items"][0]["reason"]
    assert not preview["items"][0]["needs_made_for_kids"]
    result = bulk_review.approve(preview["token"], confirm=True, made_for_kids=not kids)
    assert result["approved"] == 1, result
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(after["publication_id"])
    assert after["options"]["made_for_kids"] is kids
    assert g.videos[pub["remote_id"]]["status"]["selfDeclaredMadeForKids"] is kids


def test_missing_platform_audience_evidence_is_not_invented():
    from clipfoundry.publish import youtube

    evidence = youtube.audience_readback({}, False, "public")
    assert evidence["made_for_kids"] is None and evidence["self_declared_made_for_kids"] is None
    assert evidence["comments_reason"] == "not_reported" and "does not report" in evidence["comments_note"]
    assert youtube.audience_readback({}, True, "public")["comments_reason"] == "requested_made_for_kids"


@pytest.mark.parametrize("status", [
    {"madeForKids": False, "selfDeclaredMadeForKids": False},
    {"madeForKids": False, "selfDeclaredMadeForKids": True},
    {"madeForKids": False},
    {"selfDeclaredMadeForKids": False},
])
def test_current_false_audience_evidence_takes_precedence_over_historical_approval(status):
    from clipfoundry.publish import youtube

    evidence = youtube.audience_readback(status, True, "public")
    assert evidence["requested_made_for_kids"] is True  # Approval history remains unchanged.
    assert evidence["made_for_kids"] is status.get("madeForKids")
    assert evidence["self_declared_made_for_kids"] is status.get("selfDeclaredMadeForKids")
    assert evidence["comments_reason"] == "not_reported"
    assert "does not report whether comments are enabled" in evidence["comments_note"]
    assert "did not return its final audience label" not in evidence["comments_note"]


def test_refresh_uses_owner_corrected_studio_audience_without_rewriting_upload_approval(env, api):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    google, tiktok, tmp = env
    connect(google, tiktok)
    public_setup(api)
    item = make_item(tmp, approve={"privacy": "public", "options": {"made_for_kids": True}})
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(after["publication_id"])
    assert pub["info"]["youtube_audience"]["comments_reason"] == "made_for_kids"
    google.videos[pub["remote_id"]]["status"].update(
        {"madeForKids": False, "selfDeclaredMadeForKids": False})
    refreshed = jobs.refresh(pub)
    evidence = refreshed["info"]["youtube_audience"]
    assert evidence["comments_reason"] == "not_reported"
    assert evidence["made_for_kids"] is False and evidence["self_declared_made_for_kids"] is False
    assert evidence["requested_made_for_kids"] is True
    assert refreshed["options"]["made_for_kids"] is True
    assert db.fetch("scheduled_publications", item["id"])["options"]["made_for_kids"] is True
    assert len(google.videos) == 1

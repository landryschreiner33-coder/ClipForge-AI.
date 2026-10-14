"""Owner-review counts preserve the distinction between a local plan and an approved upload."""
from __future__ import annotations

import time

import pytest

from test_audience import api, env  # noqa: F401
from test_autopilot_publish import H, connect, make_item, run_publish


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    return tmp_path


def test_review_plans_are_counted_separately_from_approved_uploads(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home

    now = time.time()
    for status, planned_at in (("awaiting_approval", now), ("awaiting_approval", now + 3600),
                               ("awaiting_approval", None), ("published", now), ("canceled", now),
                               ("blocked", now)):
        db.insert("scheduled_publications", {"clip_id": db.new_id(), "platform": "youtube", "status": status,
                                             "planned_at": planned_at})
    assert home.post_counts() == {"review": 3, "planned_for_review": 2, "fix": 1, "ready": 0, "scheduled": 0}


def test_empty_queue_has_no_review_plans_or_uploads(data):
    from clipfoundry.autopilot import home

    assert home.post_counts() == {"review": 0, "planned_for_review": 0, "fix": 0, "ready": 0, "scheduled": 0}


def _old_automatic_item(env):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler

    google, tiktok, tmp = env
    connect(google, tiktok)
    db.save_settings({"autopilot_review_before_publish": False})
    autopublish.enable("youtube", "private", False, 0, 0, 24, True)
    item = make_item(tmp)
    assert scheduler.auto_approve(item, db.get_settings(), time.time())
    item = db.fetch("scheduled_publications", item["id"])
    assert item["approval"]["by"] == "automatic"
    db.save_settings({"autopilot_review_before_publish": True})
    return item


def test_publish_now_cannot_reuse_a_previous_automatic_approval(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    item = _old_automatic_item(env)
    response = api.post(f"/api/autopilot/scheduled/{item['id']}/publish-now", headers=H)
    assert response.status_code == 409, response.text
    current = db.fetch("scheduled_publications", item["id"])
    assert current["publication_id"] == item["publication_id"]
    assert not queue.jobs(ref=("scheduled", item["id"]))
    assert not env[0].sessions and not env[0].videos


def test_retry_returns_a_previous_automatic_approval_to_review(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    item = _old_automatic_item(env)
    db.update("scheduled_publications", item["id"], status="failed")
    response = api.post(f"/api/autopilot/scheduled/{item['id']}/retry", headers=H)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "awaiting_approval"
    assert not response.json()["approval_valid"]
    assert not queue.jobs(worker="publisher", ref=("scheduled", item["id"]))
    assert not env[0].sessions and not env[0].videos


def test_confirming_an_unknown_upload_was_not_published_requires_new_owner_review(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    item = _old_automatic_item(env)
    clip = db.get_clip(item["clip_id"])
    pub = db.create_publication(item["clip_id"], "youtube", scheduled_id=item["id"], status="processing",
                                video_path=clip["output_path"], requested_privacy="private",
                                info={"upload_session": "held-session", "outcome_unknown": True,
                                      "final_chunk_at": time.time()})
    db.update("scheduled_publications", item["id"], status="reconciling", publication_id=pub["id"])
    response = api.post(f"/api/autopilot/scheduled/{item['id']}/resolve", headers=H,
                        json={"published": False})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "awaiting_approval"
    assert not response.json()["approval_valid"]
    assert db.get_publication(pub["id"])["info"]["upload_session"] == "held-session"
    assert not queue.jobs(worker="publisher", ref=("scheduled", item["id"]))
    assert not env[0].sessions and not env[0].videos


def test_review_policy_keeps_an_unknown_publication_even_without_its_session_marker(env):
    from clipfoundry import db
    from clipfoundry.publish import youtube

    item = _old_automatic_item(env)
    clip = db.get_clip(item["clip_id"])
    pub = db.create_publication(item["clip_id"], "youtube", scheduled_id=item["id"], status="processing",
                                video_path=clip["output_path"], requested_privacy="private",
                                info={"outcome_unknown": True, "code": youtube.OUTCOME_UNKNOWN})
    db.update("scheduled_publications", item["id"], status="reconciling", publication_id=pub["id"])
    before = len(env[0].log)
    run_publish(item["id"])
    current = db.fetch("scheduled_publications", item["id"])
    assert current["status"] == "reconciling" and current["publication_id"] == pub["id"]
    assert db.get_publication(pub["id"])["info"]["outcome_unknown"]
    assert all(method == "GET" for method, _path in env[0].log[before:])
    assert not env[0].sessions and not env[0].videos


def test_manual_publish_api_cannot_borrow_an_assertion_for_the_same_clip_and_text(env, api):
    from clipfoundry import db
    from test_review_reuse import approved_unknown

    item, _source, _clip = approved_unknown(env)
    response = api.post(f"/api/clips/{item['clip_id']}/publish/youtube", headers=H, json={
        "title": item["title"], "description": item["description"], "tags": item["tags"],
        "privacy": item["privacy"], "made_for_kids": False, "confirm": True,
        "reuse_confirmation": item["reuse_confirmation"],
        "options": {"reuse_confirmation": item["reuse_confirmation"]},
    })
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "rights"
    assert not db.list_publications(item["clip_id"], "youtube")
    assert not env[0].sessions and not env[0].videos

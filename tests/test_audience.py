"""The selected-audience policy (audience.py): every upload path asks it, it never widens an audience."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest
from quality_stub import passed_report

from clipfoundry import audience

YT_SELECTED = {"audience_youtube_intent": "SELECTED_AUDIENCE"}
TT_SELECTED = {"audience_tiktok_intent": "SELECTED_AUDIENCE", "audience_tiktok_group": "FOLLOWERS",
               "audience_tiktok_private_confirmed": True, "audience_tiktok_followers_reviewed": True}


def test_local_only_is_the_default_and_uploads_nothing():
    for platform in audience.PLATFORMS:
        d = audience.plan(platform, {})
        assert d.intent == "LOCAL_ONLY" and d.route == "none"
        with pytest.raises(audience.AudienceBlocked, match="keep clips on this PC"):
            audience.check(platform, "private" if platform == "youtube" else "SELF_ONLY", {})


@pytest.mark.parametrize("platform, requested, settings", [
    ("youtube", "public", YT_SELECTED), ("youtube", "unlisted", YT_SELECTED), ("youtube", "PUBLIC", YT_SELECTED),
    ("tiktok", "PUBLIC_TO_EVERYONE", {**TT_SELECTED, "tiktok_app_audited": True}),
    ("tiktok", "PUBLIC_TO_EVERYONE", {"audience_tiktok_intent": "OWNER_ONLY"}),
])
def test_public_and_anyone_with_the_link_are_always_blocked(platform, requested, settings):
    with pytest.raises(audience.AudienceBlocked, match="blocked"):
        audience.check(platform, requested, settings)


def test_youtube_is_private_without_a_later_public_release():
    d = audience.check("youtube", "private", YT_SELECTED)
    assert d.visibility == "private" and d.setup == "awaiting_invitations"
    with pytest.raises(audience.AudienceBlocked, match="publishAt"):
        audience.check("youtube", "private", YT_SELECTED, options={"publish_at": time.time() + 3600})
    staging = audience.check("youtube", "private", {"audience_youtube_intent": "OWNER_ONLY"})
    assert staging.setup == "owner_only_staging"


def test_tiktok_followers_need_an_audited_app_else_a_manual_package():
    d = audience.plan("tiktok", TT_SELECTED)  # not audited: TikTok would force "Only me"
    assert d.route == "manual" and d.visibility == "FOLLOWER_OF_CREATOR" and "audited" in d.notes[0]
    with pytest.raises(audience.AudienceBlocked, match="cannot post to your followers"):
        audience.check("tiktok", "FOLLOWER_OF_CREATOR", TT_SELECTED)
    ok = audience.check("tiktok", "FOLLOWER_OF_CREATOR", {**TT_SELECTED, "tiktok_app_audited": True},
                        creator={"privacy_options": ["FOLLOWER_OF_CREATOR", "SELF_ONLY"]})
    assert ok.route == "api" and ok.setup == "api_requested"
    # Friends is narrower than Followers: allowed; Only me cannot reach anyone
    audience.check("tiktok", "MUTUAL_FOLLOW_FRIENDS", {**TT_SELECTED, "tiktok_app_audited": True})
    with pytest.raises(audience.AudienceBlocked, match="cannot reach"):
        audience.check("tiktok", "SELF_ONLY", {**TT_SELECTED, "tiktok_app_audited": True})
    # an option TikTok does not offer right now for this account
    with pytest.raises(audience.AudienceBlocked, match="does not currently offer"):
        audience.check("tiktok", "FOLLOWER_OF_CREATOR", {**TT_SELECTED, "tiktok_app_audited": True},
                       creator={"privacy_options": ["SELF_ONLY"]})
    # an unconfirmed private account is not eligible either
    assert audience.plan("tiktok", {**TT_SELECTED, "tiktok_app_audited": True,
                                    "audience_tiktok_private_confirmed": False}).route == "manual"


def test_policy_version_changes_with_what_an_approval_depends_on():
    base = audience.policy_version("tiktok", TT_SELECTED)
    assert audience.policy_version("tiktok", {**TT_SELECTED, "audience_tiktok_group": "FRIENDS"}) != base
    assert audience.policy_version("tiktok", {**TT_SELECTED, "audience_tiktok_group_version": 2}) != base
    assert audience.policy_version("tiktok", dict(TT_SELECTED)) == base
    with pytest.raises(audience.AudienceBlocked, match="changed after"):
        audience.check("youtube", "private", YT_SELECTED, approved_policy="stale")


def test_viewers_can_watch_only_with_evidence_or_your_confirmation():
    d = audience.plan("youtube", YT_SELECTED)
    pub = {"info": audience.record({}, d, "private", "api_response")}
    assert not audience.viewers_can_watch(pub)  # a private upload alone is staging
    pub["info"]["audience"]["setup"] = audience.SETUP_USER_CONFIRMED
    assert audience.viewers_can_watch(pub)
    staged = {"info": audience.record({}, audience.plan("youtube", {"audience_youtube_intent": "OWNER_ONLY"}),
                                      "private", "api_response")}
    assert not audience.viewers_can_watch(staged)


def test_visibility_drift_is_detected():
    assert audience.visibility_mismatch("youtube", "private", "public")
    assert audience.visibility_mismatch("youtube", "private", "unlisted")
    assert not audience.visibility_mismatch("youtube", "private", "private")
    assert audience.visibility_mismatch("tiktok", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE")


def test_legacy_settings_migrate_without_widening(monkeypatch, tmp_path):
    """An older database: a saved private YouTube setting becomes owner-only staging, public becomes local-only."""
    for old, expected in (("private", "OWNER_ONLY"), ("public", "LOCAL_ONLY"), ("unlisted", "LOCAL_ONLY")):
        data = tmp_path / old
        data.mkdir()
        conn = sqlite3.connect(data / "clipfoundry.db")
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO settings VALUES ('autopilot_youtube_privacy', ?)", (json.dumps(old),))
        conn.execute("INSERT INTO settings VALUES ('autopilot_daily_target', '7')")
        conn.commit()
        conn.close()
        monkeypatch.setenv("CLIPFOUNDRY_DATA", str(data))
        from clipfoundry import db

        s = db.get_settings()
        assert s["audience_youtube_intent"] == expected and s["audience_migrated_from"] == old
        assert s["autopilot_daily_target"] == 7  # other settings are kept
        db.save_settings({"audience_youtube_intent": "SELECTED_AUDIENCE"})  # the user's own later choice stays
        db._ready.discard(str(data / "clipfoundry.db"))  # noqa: SLF001 - simulate the next start
        assert db.get_settings()["audience_youtube_intent"] == "SELECTED_AUDIENCE"


# ------------------------------------------------------------------ the scheduler and the manual TikTok package
@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_tiktok": True,
                      "autopilot_active_start": 0, "autopilot_active_end": 24, "autopilot_min_gap_minutes": 30})
    return tmp_path


def _clip(tmp, title: str = "Talk to customers first") -> dict:
    from clipfoundry import db
    from clipfoundry.pipeline import fingerprint

    video = tmp / f"c-{time.time_ns()}.mp4"
    video.write_bytes(b"video bytes")
    project = db.create_project(title, status="ready", origin="autopilot")
    clip = db.create_clip(project["id"], start=0, end=30, title=title, status="ready", output_path=str(video),
                          duration=30.0, caption_text=title, score=70.0)
    db.insert("clip_scores", {"clip_id": clip["id"], "clip": 70.0}, key="clip_id")
    db.insert("clip_fingerprints", {"clip_id": clip["id"], "text_sig": fingerprint.text_signature(title),
                                    "phash": [], "title_norm": title.lower()}, key="clip_id")
    for p in ("youtube", "tiktok"):
        db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": p, "style": "direct", "title": title,
                                          "description": title, "caption": f"{title} #test", "tags": ["test"],
                                          "hashtags": ["#test"], "score": 60.0, "selected": 1})
    passed_report(clip)
    return clip


def test_local_only_destinations_get_no_posts(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    _clip(data)
    scheduler.plan_new(db.get_settings(), time.time())
    assert db.select("scheduled_publications") == []  # clips stay local-ready


def test_followers_without_an_eligible_app_become_a_manual_package(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, state

    db.save_settings(TT_SELECTED)
    clip = _clip(data)
    scheduler.plan_new(db.get_settings(), time.time())
    [item] = db.select("scheduled_publications")
    assert item["platform"] == "tiktok" and item["status"] == "manual_handoff"
    assert "Followers" in item["fix"] and "Do not choose Everyone" in item["fix"]
    assert any(a["key"] == f"manual:{item['id']}" for a in state.open_actions())
    scheduler.plan_new(db.get_settings(), time.time())  # no second package for the same clip
    assert len(db.select("scheduled_publications")) == 1
    with pytest.raises(ValueError):
        scheduler.manual_posted(item["id"], "http://insecure.example/x")
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:  # the button's route exists and checks the link
        r = c.post(f"/api/autopilot/scheduled/{item['id']}/manual-posted", headers={"X-ClipFoundry": "1"},
                   json={"link": "not a link"})
        assert r.status_code == 400
    done = scheduler.manual_posted(item["id"], "https://www.tiktok.com/@me/video/7312345678901234567")
    pub = db.get_publication(done["publication_id"])
    assert done["status"] == "published" and pub["mode"] == "manual" and pub["remote_id"] == "7312345678901234567"
    assert pub["info"]["audience"]["evidence"] == "user" and pub["info"]["audience"]["setup"] == "user_confirmed"
    assert pub["clip_id"] == clip["id"]


def test_pause_publishing_keeps_approved_posts_waiting(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler

    db.save_settings({**YT_SELECTED, "autopilot_tiktok": False})
    _clip(data)
    now = time.time()
    scheduler.plan_new(db.get_settings(), now)
    [item] = db.select("scheduled_publications")
    scheduler.approve(item["id"], {"options": {"made_for_kids": False}})
    db.update("scheduled_publications", item["id"], planned_at=now - 1)
    db.save_settings({"autopilot_publish_paused": True})
    assert scheduler.process_due(db.get_settings(), now)["publishing"] == 0 and not queue.jobs(worker="publisher")
    assert "paused" in db.fetch("scheduled_publications", item["id"])["status_note"]
    db.save_settings({"autopilot_publish_paused": False})
    assert scheduler.process_due(db.get_settings(), now)["publishing"] == 1

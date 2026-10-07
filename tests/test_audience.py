"""Selected audience: uploads go only to the viewers the owner chose (YouTube Private + Studio invitations, TikTok
followers through an audited Direct Post or a ready-to-post package). Public, unlisted and Everyone are never sent,
nothing is scheduled to turn public, and posts planned before this version are held without being widened."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from fake_platforms import FakeGoogle, FakeTikTok
from test_autopilot_publish import H, connect, make_item, run_publish


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry import db
    from clipfoundry.publish import tiktok, youtube

    g, t = FakeGoogle(), FakeTikTok()
    for name, value in {"AUTH_URL": f"{g.url}/o/oauth2/v2/auth", "TOKEN_URL": f"{g.url}/token",
                        "REVOKE_URL": f"{g.url}/revoke", "API_URL": f"{g.url}/youtube/v3",
                        "UPLOAD_URL": f"{g.url}/upload/youtube/v3/videos", "CHUNK": 256 * 1024}.items():
        monkeypatch.setattr(youtube, name, value)
    monkeypatch.setattr(tiktok, "AUTH_URL", f"{t.url}/v2/auth/authorize/")
    monkeypatch.setattr(tiktok, "API_URL", f"{t.url}/v2")
    monkeypatch.setattr(tiktok, "POLL_SECONDS", 0.01)
    db.init()
    db.save_settings({"youtube_client_id": "cid.apps.googleusercontent.com", "youtube_client_secret": "csecret",
                      "tiktok_client_key": "tkkey", "tiktok_client_secret": "tksecret", "autopilot_enabled": True,
                      "autopilot_youtube": True, "autopilot_tiktok": True})
    yield g, t, tmp_path
    g.stop()
    t.stop()


@pytest.fixture()
def api(env):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


def _open_actions() -> dict:
    from clipfoundry import db

    return {r["key"]: r for r in db.select("action_items", "resolved_at IS NULL")}


# ------------------------------------------------------------------ the policy itself
def test_public_unlisted_and_everyone_are_refused_everywhere(env):
    from clipfoundry import db
    from clipfoundry.publish import audience, tiktok, youtube

    settings = db.get_settings()
    for privacy in ("public", "unlisted"):
        with pytest.raises(audience.AudienceBlocked):
            youtube.video_body("t", "d", [], privacy, False, "22")
        with pytest.raises(audience.AudienceBlocked):
            audience.check("youtube", privacy, settings)
    with pytest.raises(audience.AudienceBlocked):
        audience.check("tiktok", "PUBLIC_TO_EVERYONE", {**settings, "tiktok_app_audited": True})
    with pytest.raises(audience.AudienceBlocked):
        tiktok.validate("caption", "PUBLIC_TO_EVERYONE", {}, "direct", settings, None, 20)
    body = youtube.video_body("t", "d", [], "private", False, "22", publish_at=time.time() + 86400)
    assert body["status"]["privacyStatus"] == "private" and "publishAt" not in body["status"]


def test_nothing_uploads_until_the_owner_confirms_who_watches(env):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler
    from clipfoundry.publish import audience

    g, t, tmp = env
    connect(g, t)
    db.save_settings({"audience_youtube_confirmed_at": 0.0, "audience_tiktok_confirmed_at": 0.0})
    settings = db.get_settings()
    assert scheduler.uploadable_platforms(settings) == []
    with pytest.raises(audience.AudienceBlocked, match="Choose who watches"):
        audience.check("youtube", "private", settings)
    scheduler.audience_reminders(settings)
    assert {"audience_setup:youtube", "audience_setup:tiktok"} <= set(_open_actions())
    db.save_settings({"audience_youtube_confirmed_at": time.time()})
    scheduler.audience_reminders(db.get_settings())
    assert "audience_setup:youtube" not in _open_actions()
    assert scheduler.uploadable_platforms(db.get_settings()) == ["youtube"]


def test_owner_only_and_local_only(env):
    from clipfoundry import db
    from clipfoundry.publish import audience

    db.save_settings({"audience_youtube": "owner_only", "audience_tiktok": "local_only"})
    settings = db.get_settings()
    stamp = audience.check("youtube", "private", settings)
    assert stamp["intent"] == audience.OWNER_ONLY and stamp["visibility"] == "private"
    assert audience.visibility("tiktok", audience.OWNER_ONLY, settings) == "SELF_ONLY"
    with pytest.raises(audience.AudienceBlocked, match="keep clips on this PC"):
        audience.check("tiktok", "SELF_ONLY", settings)


# ------------------------------------------------------------------ YouTube
def test_youtube_upload_is_private_and_waits_for_the_owners_invitations(env, api):
    from clipfoundry import db

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp, approve={"options": {"made_for_kids": False}})
    assert item["approval"]["scheme"] == 3 and item["audience"]["intent"] == "SELECTED_AUDIENCE"
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(after["publication_id"])
    video = g.videos[pub["remote_id"]]
    assert video["status"]["privacyStatus"] == "private" and "publishAt" not in video["status"]
    assert after["status"] == "published" and "share it privately in YouTube Studio" in after["status_note"]
    assert after["delivery"]["audience_setup"] == "awaiting_invitations"
    assert after["delivery"]["visibility"] == {**after["delivery"]["visibility"], "requested": "private",
                                               "returned": "private", "evidence": "api"}
    assert after["delivery"]["analytics"] == "awaiting_viewer_access"
    assert "audience_share:youtube" in _open_actions()
    shown = api.get(f"/api/autopilot/scheduled/{item['id']}").json()["item"]
    assert shown["delivery_state"] == "awaiting_invitations"
    assert shown["delivery_label"] == "Awaiting viewer invitations"
    assert "yours" in api.get("/api/autopilot/scheduled?view=yours").json()["view"]
    r = api.post(f"/api/autopilot/scheduled/{item['id']}/audience-confirmed", headers=H)
    assert r.status_code == 200 and r.json()["delivery_state"] == "audience_user_confirmed"
    assert r.json()["delivery"]["audience_evidence"] == "user"  # the owner's word, not the platform's
    assert "audience_share:youtube" not in _open_actions()


def test_a_wider_visibility_reported_by_youtube_stops_uploads(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import queue
    from clipfoundry.publish import audience

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp, approve={"options": {"made_for_kids": False}})
    second = make_item(tmp, approve={"options": {"made_for_kids": False}},
                       text="Your environment beats your motivation every single time.")
    g.force_privacy = "public"  # never expected: the app asked for Private
    run_publish(item["id"])
    assert audience.halted("youtube")
    assert _open_actions()["audience:youtube"]["level"] == "error"
    with pytest.raises(queue.Wait):
        run_publish(second["id"])  # waits with its approval; nothing is uploaded meanwhile
    assert db.fetch("scheduled_publications", second["id"])["status"] == "approved"
    assert len(g.videos) == 1
    r = api.post("/api/audience/youtube/checked", headers=H)
    assert r.status_code == 200 and not r.json()["youtube"]["halted"]
    assert not audience.halted("youtube") and "audience:youtube" not in _open_actions()


def test_changing_the_test_group_needs_a_new_approval(env, api):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp, approve={"options": {"made_for_kids": False}})
    assert scheduler.approval_valid(item)
    r = api.post("/api/audience/youtube", json={"intent": "selected", "confirm": True, "group_changed": True},
                 headers=H)
    assert r.status_code == 200 and r.json()["youtube"]["group_version"] == 2
    approved = db.fetch("scheduled_publications", item["id"])
    assert scheduler.approval_problem(approved) == "who watches changed after approval"
    with pytest.raises(queue.Fail):
        run_publish(item["id"])  # the publisher asks for a new approval instead of uploading
    item = db.fetch("scheduled_publications", item["id"])
    assert item["status"] == "awaiting_approval" and not g.videos
    old = {**approved, "approval": {**approved["approval"], "scheme": 2}}
    assert scheduler.approval_problem(old) == "approved before ClipFoundry checked who may watch it"


def test_automatic_publishing_is_private_only(env):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish

    with pytest.raises(ValueError, match="Private only"):
        autopublish.enable("youtube", "public", False, 3, 9, 21, True)
    row = autopublish.enable("youtube", "private", False, 3, 9, 21, True)
    assert "as Private videos" in row["text"] and "never makes them public" in row["text"]
    assert row["settings"]["text_version"] == 2
    item = {"platform": "youtube", "approval": {"by": "automatic", "consent_id": row["id"]}}
    assert autopublish.still_covers(item)
    db.update("publish_consents", row["id"], settings={**row["settings"], "visibility": "public"})
    assert not autopublish.still_covers(item)


# ------------------------------------------------------------------ TikTok
def test_tiktok_without_an_audit_hands_the_owner_a_ready_to_post_package(env, api):
    from clipfoundry import db

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp, platform="tiktok", approve={"options": {"mode": "manual"}, "privacy": ""})
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "action_needed" and after["delivery"]["audience_setup"] == "manual_pending"
    assert "Followers" in after["status_note"] or "followers" in after["status_note"]
    assert t.inits == []  # nothing was sent to TikTok
    assert "audience_post:tiktok" in _open_actions()
    shown = api.get(f"/api/autopilot/scheduled/{item['id']}").json()["item"]
    assert shown["delivery_state"] == "manual_handoff"
    r = api.post(f"/api/autopilot/scheduled/{item['id']}/link",
                 json={"url": "https://www.tiktok.com/@testcreator/video/7300000000000000009"}, headers=H)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "published" and done["delivery"]["audience_setup"] == "manual_confirmed"
    assert done["delivery_state"] == "audience_user_confirmed"
    assert db.get_publication(done["publication_id"])["mode"] == "manual"
    assert "audience_post:tiktok" not in _open_actions()


def test_tiktok_direct_post_for_followers_needs_an_audited_app(env):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler
    from clipfoundry.publish import audience, tiktok
    from clipfoundry.publish.common import PublishError

    g, t, tmp = env
    connect(g, t)
    assert audience.tiktok_route(db.get_settings(), db.get_account("tiktok")) == "inbox"  # not audited
    with pytest.raises(PublishError, match="audited"):
        make_item(tmp, platform="tiktok", approve={"options": {"mode": "direct"}, "privacy": "FOLLOWER_OF_CREATOR"})
    with pytest.raises(PublishError):  # "Only me" is not the selected audience
        make_item(tmp, platform="tiktok", approve={"options": {"mode": "direct"}, "privacy": "SELF_ONLY"})
    db.save_settings({"tiktok_app_audited": True})
    assert audience.tiktok_route(db.get_settings(), db.get_account("tiktok")) == "direct"
    item = make_item(tmp, platform="tiktok", approve={"options": {"mode": "direct"}, "privacy": "FOLLOWER_OF_CREATOR"})
    run_publish(item["id"])
    assert t.inits[-1]["post_info"]["privacy_level"] == "FOLLOWER_OF_CREATOR"
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "published" and after["delivery"]["audience_setup"] == "account_group"
    assert audience.delivery_state(after) == "restricted_requested"
    t.privacy_options = ["SELF_ONLY"]  # a public account: TikTok does not offer followers-only
    creator = tiktok.creator_info(tiktok.Token(db.get_settings()))
    with pytest.raises(audience.AudienceBlocked, match="does not offer"):
        audience.check("tiktok", "FOLLOWER_OF_CREATOR", db.get_settings(), creator=creator)
    assert scheduler.APPROVAL_SCHEME == 3


# ------------------------------------------------------------------ posts from before this version
def _old_database(tmp_path) -> None:
    """Rows as an older version left them: public posts, a queued public upload, a public consent."""
    from clipfoundry import db

    db.init()
    project = db.create_project("old", status="ready")
    clip = db.create_clip(project["id"], start=0, end=20, title="old", status="ready", duration=20.0)
    rows = [("youtube", "public", "approved"), ("youtube", "unlisted", "awaiting_approval"),
            ("tiktok", "PUBLIC_TO_EVERYONE", "approved"), ("youtube", "private", "approved"),
            ("tiktok", "SELF_ONLY", "awaiting_approval"), ("youtube", "public", "published")]
    for platform, privacy, status in rows:
        db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": platform, "title": privacy,
                                             "privacy": privacy, "status": status,
                                             "approval": {"hash": "x", "scheme": 2}, "planned_at": time.time()})
    db.create_publication(clip["id"], "youtube", status="queued", requested_privacy="public", title="q")
    db.insert("publish_consents", {"platform": "youtube", "settings": {"visibility": "public"}, "text": "old"})
    db.save_settings({"autopilot_youtube_privacy": "private"})
    with db.connect() as conn:  # as an older version stored them, before the audience fields and the migration
        conn.execute("UPDATE scheduled_publications SET audience = '{}'")
        conn.execute("UPDATE publications SET audience = '{}'")
        conn.execute("UPDATE settings SET value = ? WHERE key = 'autopilot_youtube_privacy'", (json.dumps("public"),))
        conn.execute("DELETE FROM autopilot_state WHERE key = ?", (db.AUDIENCE_MIGRATION,))


def _migrate() -> None:
    from clipfoundry import config, db

    conn = sqlite3.connect(str(config.db_path()))
    conn.row_factory = sqlite3.Row
    try:
        db._migrate_audience(conn)  # noqa: SLF001
        conn.commit()
    finally:
        conn.close()


def test_migration_holds_public_posts_without_widening_anything(env, api):
    from clipfoundry import config, db

    g, t, tmp = env
    _old_database(tmp)
    _migrate()
    rows = db.select("scheduled_publications")
    by_title = {i["title"] + i["platform"]: i for i in rows if i["status"] != "published"}
    held = [i for i in rows if i["status"] == "blocked"]
    assert len(held) == 3 and all(i["audience"]["intent"] == "LEGACY_PUBLIC" and not i["approval"] for i in held)
    assert all("planned as public" in i["status_note"] for i in held)
    assert by_title["privateyoutube"]["audience"]["intent"] == "OWNER_ONLY"
    assert by_title["privateyoutube"]["status"] == "approved"  # nothing about it changed
    assert by_title["SELF_ONLYtiktok"]["audience"]["intent"] == "OWNER_ONLY"
    published = [i for i in rows if i["status"] == "published"]
    assert published and published[0]["audience"]["intent"] == "LEGACY_PUBLIC"  # history kept as it was
    queued = [p for p in db.list_publications() if p["title"] == "q"][0]
    assert queued["status"] == "cancelled"
    assert db.get_settings()["autopilot_youtube_privacy"] == "private"
    assert db.select("publish_consents", "revoked_at IS NULL") == []
    assert "consent_renew:youtube" in _open_actions()
    assert list((config.data_dir() / "backups").glob("clipfoundry-before-audience-v1-*.db"))
    before = [dict(i) for i in db.select("scheduled_publications")]
    _migrate()  # once only
    assert [dict(i) for i in db.select("scheduled_publications")] == before
    # the owner plans the held posts for the selected viewers: each needs a new approval, nothing goes out by itself
    r = api.post("/api/autopilot/scheduled/retarget", json={}, headers=H)
    assert r.status_code == 200 and r.json()["retargeted"] == 3
    for i in db.select("scheduled_publications", "id IN (%s)" % ",".join("?" * len(held)), [h["id"] for h in held]):
        assert i["status"] == "awaiting_approval" and i["audience"]["intent"] == "SELECTED_AUDIENCE"
        assert i["privacy"] == ("private" if i["platform"] == "youtube" else "")
        assert not i["approval"] and not i["planned_at"]


# ------------------------------------------------------------------ learning keeps audiences apart
def test_results_of_different_audiences_are_never_mixed(env):
    from clipfoundry.autopilot import learner

    def pub(platform, privacy, intent=""):
        return {"platform": platform, "requested_privacy": privacy, "audience": {"intent": intent} if intent else {}}

    assert learner.cohort(pub("youtube", "private", "SELECTED_AUDIENCE")) == "selected"
    assert learner.cohort(pub("youtube", "public")) == "public_legacy"
    assert learner.cohort(pub("youtube", "private")) == "owner_only"
    assert learner.cohort(pub("tiktok", "FOLLOWER_OF_CREATOR")) == "selected"
    assert learner.cohort(pub("tiktok", "PUBLIC_TO_EVERYONE")) == "public_legacy"


def test_delivery_labels_never_say_viewers_watched(env):
    from clipfoundry.publish import audience

    for state, label in audience.DELIVERY_LABELS.items():
        assert "watched" not in label.lower() and "live" not in label.lower(), state
    item = {"status": "published", "delivery": {"audience_setup": "owner_only"}}
    assert audience.delivery_state(item) == "uploaded_owner_only"
    assert audience.delivery_state({"status": "approved"}) == "local_ready"
    assert audience.delivery_state({"status": "approved", "planned_at": 1.0}) == "scheduled"
    assert audience.delivery_state({"status": "published", "audience": {"intent": "LEGACY_PUBLIC"}}) == "published"

"""Autopilot Publisher and Publish Center: gates, platform outcomes, idempotent recovery and the REST API."""
from __future__ import annotations

import os
import time
from urllib.parse import parse_qs, urlparse

import pytest

from fake_platforms import FakeGoogle, FakeTikTok

H = {"X-ClipFoundry": "1"}


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


def connect(g, t) -> None:
    from clipfoundry.publish import tiktok, youtube
    from clipfoundry.publish.common import challenge_hex, challenge_s256, code_verifier

    from clipfoundry import db

    s = db.get_settings()
    v = code_verifier()
    code = g.approve(youtube.auth_url(s, "http://127.0.0.1:8765/cb", "st", challenge_s256(v)))
    youtube.exchange_code(s, code, v, "http://127.0.0.1:8765/cb")
    v = code_verifier()
    code = t.approve(tiktok.auth_url(s, "http://127.0.0.1:8765/cb", "st", challenge_hex(v)))
    tiktok.exchange_code(s, code, v, "http://127.0.0.1:8765/cb")


def make_item(tmp, platform: str = "youtube", size: int = 300_000, planned_in: float = 7200, approve: dict | None =
              None, text: str = "Talk to customers first, then build the product they asked for.") -> dict:
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler
    from clipfoundry.pipeline import fingerprint

    video = tmp / f"clip-{time.time_ns()}.mp4"
    video.write_bytes(os.urandom(size))
    project = db.create_project("talk", status="ready", origin="autopilot")
    clip = db.create_clip(project["id"], start=0, end=20, title="Talk to customers first", status="ready",
                          output_path=str(video), duration=20.0, caption_text=text, score=72.0)
    db.insert("clip_fingerprints", {"clip_id": clip["id"], "text_sig": fingerprint.text_signature(text), "phash": [],
                                    "title_norm": "talk to customers first"}, key="clip_id")
    item = db.insert("scheduled_publications", {
        "clip_id": clip["id"], "platform": platform, "title": "Talk to customers first, then build",
        "description": text if platform == "tiktok" else f"{text}\n\nFollow for more clips like this.",
        "tags": ["customers"], "privacy": "public" if platform == "youtube" else "",
        "options": {"made_for_kids": None} if platform == "youtube" else {"mode": "direct"},
        "planned_at": time.time() + planned_in, "status": "awaiting_approval", "final_score": 70})
    if approve is not None:
        creator = None
        if platform == "tiktok" and approve.get("options", {}).get("mode", "direct") == "direct":
            from clipfoundry.publish import tiktok

            creator = tiktok.creator_info(tiktok.Token(db.get_settings()))
        item = scheduler.approve(item["id"], approve, creator)
    return item


def run_publish(item_id: str) -> dict:
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    row = queue.enqueue("publish", {"scheduled_id": item_id}, idem_key=f"publish:{item_id}")
    return host.HANDLERS["publish"](host.Job(queue.get(row["id"]), "test"))


def test_youtube_post_is_scheduled_with_publish_at(env):
    from clipfoundry import db

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp, approve={"options": {"made_for_kids": False}})
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    pub = db.get_publication(after["publication_id"])
    video = g.videos[pub["remote_id"]]
    assert video["status"]["privacyStatus"] == "private" and video["status"]["publishAt"]  # YouTube publishes it
    assert after["status"] == "published" and "scheduled" in after["status_note"].lower()
    assert pub["info"]["scheduled"] and pub["scheduled_id"] == item["id"]


def test_locked_private_is_reported_honestly(env):
    from clipfoundry import db

    g, t, tmp = env
    connect(g, t)
    g.lock_private = True  # an API project that has not passed YouTube's audit
    item = make_item(tmp, planned_in=60, approve={"options": {"made_for_kids": False}})
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "published" and "Published as Private" in after["status_note"]
    assert db.get_publication(after["publication_id"])["privacy"] == "private"


def test_tiktok_direct_post_and_unaudited_refusal(env):
    from clipfoundry import db
    from clipfoundry.autopilot import state

    g, t, tmp = env
    connect(g, t)
    ok = make_item(tmp, "tiktok", approve={"privacy": "SELF_ONLY", "options": {"mode": "direct"}})
    run_publish(ok["id"])
    assert db.fetch("scheduled_publications", ok["id"])["status"] == "published"
    assert t.uploads and list(t.uploads.values())[0]["privacy"] == "SELF_ONLY"
    t.init_error = "unaudited_client_can_only_post_to_private_accounts"
    bad = make_item(tmp, "tiktok", approve={"privacy": "SELF_ONLY", "options": {"mode": "direct"}},
                    text="Your environment beats your motivation every single time.")
    from clipfoundry.autopilot import queue

    with pytest.raises(queue.Fail):
        run_publish(bad["id"])
    after = db.fetch("scheduled_publications", bad["id"])
    assert after["status"] == "action_needed" and after["approval"] == {}  # the user decides what to do
    assert any(a["key"] == f"review:{bad['id']}" for a in state.open_actions())


def test_tiktok_inbox_needs_the_app_then_can_be_linked(env):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp, "tiktok", approve={"options": {"mode": "inbox"}})
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "action_needed" and "TikTok app" in after["status_note"]
    t.stats["7311111111111111111"] = {"view_count": 5, "like_count": 1, "comment_count": 0, "share_count": 0}
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        r = c.post(f"/api/autopilot/scheduled/{item['id']}/link", headers=H,
                   json={"url": "https://www.tiktok.com/@testcreator/video/7311111111111111111"})
        assert r.status_code == 200 and r.json()["status"] == "published"


def test_interrupted_upload_resumes_without_a_duplicate(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import jobs as publish_jobs

    g, t, tmp = env
    connect(g, t)
    item = make_item(tmp, size=1_100_000, approve={"options": {"made_for_kids": False}})

    class Crash(BaseException):
        pass

    real = publish_jobs._progress_writer

    def crashing(pub_id):  # the computer loses power after the first chunk
        write = real(pub_id)

        def w(frac):
            write(frac)
            if 0.1 < frac < 1.0:
                raise Crash()
        return w

    monkeypatch.setattr(publish_jobs, "_progress_writer", crashing)
    with pytest.raises(Crash):
        run_publish(item["id"])
    pub = db.get_publication(db.fetch("scheduled_publications", item["id"])["publication_id"])
    assert pub["status"] == "uploading" and pub["info"]["upload_session"]
    monkeypatch.setattr(publish_jobs, "_progress_writer", real)
    run_publish(item["id"])  # the job runs again after the restart
    assert len(g.videos) == 1 and len(g.sessions) == 1  # continued the same upload session
    assert db.fetch("scheduled_publications", item["id"])["status"] == "published"


def test_gates_before_every_upload(env):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, rights, scheduler

    g, t, tmp = env
    item = make_item(tmp, approve={"options": {"made_for_kids": False}})
    with pytest.raises(queue.Wait, match="not connected"):
        run_publish(item["id"])
    assert db.fetch("scheduled_publications", item["id"])["status"] == "action_needed"
    connect(g, t)
    db.update("scheduled_publications", item["id"], status="approved")
    scheduler.block_platform("youtube", time.time() + 3600, "Upload limit reached")
    with pytest.raises(queue.Wait):
        run_publish(item["id"])
    db.execute("DELETE FROM platform_limits")
    db.update("scheduled_publications", item["id"], title="Changed after approval")
    with pytest.raises(queue.Fail):
        run_publish(item["id"])
    assert db.fetch("scheduled_publications", item["id"])["status"] == "awaiting_approval"
    src = db.insert("sources", {"platform": "youtube", "external_id": "s1", "title": "s", "channel_id": "UCz"})
    rights.add_rule("channel", "UCz", rights.ALLOWLISTED, "program")
    clip = db.get_clip(item["clip_id"])
    db.update_project(clip["project_id"], source_id=src["id"])
    scheduler.approve(item["id"], {})
    rights.add_rule("source", src["id"], rights.BLOCKED, "permission withdrawn")
    with pytest.raises(queue.Fail):
        run_publish(item["id"])
    assert db.fetch("scheduled_publications", item["id"])["status"] == "blocked"
    assert not g.videos  # nothing was uploaded by any of these attempts


def test_duplicates_and_quota(env):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, quota

    g, t, tmp = env
    connect(g, t)
    first = make_item(tmp, planned_in=60, approve={"options": {"made_for_kids": False}})
    run_publish(first["id"])
    again = make_item(tmp, planned_in=60, approve={"options": {"made_for_kids": False}})  # same words
    out = run_publish(again["id"])
    assert "already published" in out["message"] and db.fetch("scheduled_publications", again["id"])["status"] == \
        "canceled"
    other = make_item(tmp, planned_in=60, approve={"options": {"made_for_kids": False}},
                      text="Why do most diets fail after two weeks? Because willpower is a terrible strategy.")
    quota.mark_exhausted("videos.insert", "quotaExceeded")
    with pytest.raises(queue.Wait):
        run_publish(other["id"])
    assert db.fetch("scheduled_publications", other["id"])["status"] == "approved" and len(g.videos) == 1


def test_publish_center_api(env):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.autopilot import queue

    g, t, tmp = env
    connect(g, t)
    yt = make_item(tmp)
    tt = make_item(tmp, "tiktok", text="Your environment beats your motivation every single time.")
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        items = c.get("/api/autopilot/scheduled").json()["items"]
        assert {i["id"] for i in items} == {yt["id"], tt["id"]}
        assert items[0]["clip"]["video_url"].startswith("/api/") and items[0]["source"]["rights_label"]
        assert c.post(f"/api/autopilot/scheduled/{yt['id']}/approve", headers=H,
                      json={"made_for_kids": False}).status_code == 400  # no explicit confirmation
        r = c.post(f"/api/autopilot/scheduled/{tt['id']}/approve", headers=H,
                   json={"privacy": "PUBLIC_TO_EVERYONE", "confirm": True})
        assert r.status_code == 400 and "Only me" in r.json()["detail"]
        r = c.post(f"/api/autopilot/scheduled/{tt['id']}/approve", headers=H, json={"privacy": "SELF_ONLY",
                                                                                   "confirm": True})
        assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approval_valid"]
        r = c.post(f"/api/autopilot/scheduled/{yt['id']}/approve", headers=H,
                   json={"made_for_kids": False, "privacy": "unlisted", "confirm": True})
        assert r.json()["privacy"] == "unlisted"
        r = c.patch(f"/api/autopilot/scheduled/{yt['id']}", headers=H, json={"title": "Invented: 5 secrets of Elon"})
        assert r.json()["status"] == "awaiting_approval" and r.json()["warnings"]
        c.post(f"/api/autopilot/scheduled/{yt['id']}/approve", headers=H, json={"confirm": True})
        r = c.post(f"/api/autopilot/scheduled/{yt['id']}/publish-now", headers=H)
        assert r.json()["status"] == "publishing" and queue.jobs(worker="publisher")[0]["priority"] == 100
        later = time.time() + 5 * 3600
        r = c.post(f"/api/autopilot/scheduled/{tt['id']}/reschedule", headers=H, json={"planned_at": later})
        assert r.json()["planned_at"] == pytest.approx(later)
        assert c.post(f"/api/autopilot/scheduled/{tt['id']}/cancel", headers=H).json()["status"] == "canceled"
        assert c.post(f"/api/autopilot/scheduled/{tt['id']}/retry", headers=H).json()["status"] == "approved"
        st = c.get("/api/autopilot/status").json()
        assert st["target"]["daily"] == 15 and "workers" in st and "gpu" in st and st["platforms"]["youtube"]
        stop = c.post("/api/autopilot/stop-all", headers=H).json()
        assert stop["paused"] and queue.get(queue.jobs(worker="publisher")[0]["id"])["status"] == "canceled"
        assert c.post("/api/autopilot/enable", headers=H, json={"enabled": False}).json()["enabled"] is False
    assert db.get_settings()["autopilot_enabled"] is False

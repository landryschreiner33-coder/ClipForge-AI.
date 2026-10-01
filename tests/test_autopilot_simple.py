"""Zero-config Autopilot: connect an account, press START AUTOPILOT, and Autopilot finds, checks and queues content
by itself. Only what really needs you is asked, in plain words; a video nothing covers is skipped (activity log), not
asked about, unless you turn the questions on. Against local stand-ins for Google and TikTok."""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from fake_platforms import FakeGoogle, FakeTikTok

H = {"X-ClipFoundry": "1"}
JARGON = ("worker", "feed", "provider", "source_scout", "trend_scan", "hunt_source", "queue", "lease", "quota",
          "MANUAL_CONFIRMATION_REQUIRED", "ALLOWLISTED", "signal")


@pytest.fixture()
def fakes(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry.publish import tiktok, youtube

    g, t = FakeGoogle(), FakeTikTok()
    for name, path in (("AUTH_URL", "/o/oauth2/v2/auth"), ("TOKEN_URL", "/token"), ("REVOKE_URL", "/revoke"),
                       ("API_URL", "/youtube/v3"), ("UPLOAD_URL", "/upload/youtube/v3/videos")):
        monkeypatch.setattr(youtube, name, g.url + path)
    monkeypatch.setattr(tiktok, "AUTH_URL", f"{t.url}/v2/auth/authorize/")
    monkeypatch.setattr(tiktok, "API_URL", f"{t.url}/v2")
    yield g, t
    g.stop()
    t.stop()


@pytest.fixture()
def client(fakes):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        # your own app credentials, entered once (Settings → General → Accounts); nothing else is configured
        c.put("/api/settings", json={"youtube_client_id": "cid.apps.googleusercontent.com",
                                     "youtube_client_secret": "csecret", "tiktok_client_key": "tkkey",
                                     "tiktok_client_secret": "tksecret"})
        yield c


def connect(c, fake, platform: str) -> None:
    """What the CONNECT button does: the platform's sign-in page, then its answer to ClipFoundry's callback."""
    auth_url = c.post(f"/api/publish/{platform}/connect", headers=H).json()["auth_url"]
    q = parse_qs(urlparse(auth_url).query)
    page = c.get(f"/api/oauth/{platform}/callback", params={"state": q["state"][0], "code": fake.approve(auth_url)})
    assert page.status_code == 200 and "connected" in page.text


def run(kind: str, payload: dict | None = None) -> dict:
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)  # registers the handlers
    row = queue.enqueue(kind, payload or {})
    return host.HANDLERS[kind](host.Job(queue.get(row["id"]), "test"))


def trending(g: FakeGoogle, n: int = 3, **kw) -> list[str]:
    ids = []
    for k in range(n):
        vid = f"trend{k}"
        g.add_video(vid, f"Podcast interview everyone is talking about part {k}", f"UCcreator00000000{k:02d}",
                    views=900_000 - k * 10_000, age_hours=6, duration="PT50M", **kw)
        ids.append(vid)
    g.popular = ids
    return ids


def words(value) -> str:
    """Every piece of text in a structure (to check what the simple page says)."""
    if isinstance(value, dict):
        return " ".join(words(v) for k, v in value.items() if k not in ("id", "key", "source_id", "url", "platform",
                                                                           "type", "status", "link", "kind", "path"))
    if isinstance(value, list):
        return " ".join(words(v) for v in value)
    return str(value) if isinstance(value, str) else ""


# ------------------------------------------------------------------ 1, 2: connect, start, and it finds sources itself
def test_a_fresh_user_connects_youtube_and_starts_without_adding_a_source(client, fakes):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    g, _ = fakes
    first = client.get("/api/autopilot/status").json()
    assert first["enabled"] is False and first["home"]["setup"]["started"] is False  # the first-run screen shows
    assert first["home"]["empty"] == "Connect YouTube to start finding content."
    # The way of working chosen in first-time setup is kept with the settings (Home skips its welcome after
    # "I'll make clips myself"); anything else is not stored.
    assert first["home"]["setup"]["mode"] == ""
    client.put("/api/settings", json={"setup_mode": "manual"})
    assert client.get("/api/autopilot/status").json()["home"]["setup"]["mode"] == "manual"
    client.put("/api/settings", json={"setup_mode": "everything"})
    assert db.get_settings()["setup_mode"] == "manual"
    client.put("/api/settings", json={"setup_mode": ""})

    connect(client, g, "youtube")
    st = client.post("/api/autopilot/start", headers=H).json()
    assert st["enabled"] and st["home"]["setup"]["started"] and st["home"]["setup"]["connected"] == ["youtube"]
    s = db.get_settings()
    assert s["autopilot_youtube"] and not s["autopilot_tiktok"]  # only where you are signed in
    for key in ("autopilot_sources_per_day", "autopilot_daily_target", "autopilot_clips_per_source",
                "autopilot_dynamic_replacement", "autopilot_learning", "autopilot_live_monitoring",
                "autopilot_auto_schedule", "autopilot_auto_publish", "trend_region", "trend_language"):
        assert s[key] == {"autopilot_sources_per_day": 3, "autopilot_daily_target": 15, "autopilot_clips_per_source": 5,
                          "trend_region": "US", "trend_language": "en"}.get(key, True), key
    kinds = {j["kind"] for j in queue.jobs(("queued",))}
    assert {"trend_scan", "feed_scan", "schedule_tick"} <= kinds  # discovery starts right away
    # nothing to configure: the only thing START sets up is your videos folder (watched, and yours)
    assert [f["name"] for f in db.select("source_feeds")] == ["Your videos folder"] and db.select("sources") == []
    assert [(r["scope"], r["status"]) for r in db.select("source_rights")] == [("folder", "OWNED")]
    assert st["home"]["empty"] == "Autopilot is looking for opportunities."
    assert st["home"]["needs_you"] == []  # it has not looked yet


def test_autopilot_discovers_and_creates_sources_by_itself(client, fakes):
    from clipfoundry import db

    g, _ = fakes
    ids = trending(g)
    connect(client, g, "youtube")
    client.post("/api/autopilot/start", headers=H)
    out = run("trend_scan")  # with the connected account: no API key, feed or folder
    assert out["signals"] >= 3
    run("source_scout")
    sources = db.select("sources")
    assert {s["external_id"] for s in sources} >= set(ids) and all(s["signal_id"] for s in sources)
    home = client.get("/api/autopilot/status").json()["home"]
    # Other creators' videos without an agreement or license are skipped, not asked about: no questions, and the
    # activity log says why. Needs you says once, plainly, that Autopilot has nothing to work with and what helps.
    assert home["opportunities"] == [] and home["skipped_today"] >= 3
    assert [(i["type"], i["title"]) for i in home["needs_you"]] == [("videos", "Autopilot needs videos to work with")]
    assert "belong to other people" in home["needs_you"][0]["detail"]
    assert "not covered by an agreement or license" in home["empty"]
    log = {a["id"]: a for a in client.get("/api/autopilot/activity").json()["items"]}
    for s in sources:
        assert not log[s["id"]]["used"] and log[s["id"]]["why"].startswith("Not covered")


# ------------------------------------------------------------------ 3: missing providers
def test_missing_optional_providers_do_not_stop_autopilot(client, fakes):
    from clipfoundry.autopilot import state

    g, _ = fakes
    trending(g, 1)
    connect(client, g, "youtube")  # no TikTok, no API key, no folders or feeds
    client.post("/api/autopilot/start", headers=H)
    run("trend_scan")
    run("source_scout")
    provs = state.get("providers")
    assert provs["youtube"]["status"] == "ok"
    assert provs["google_trends"]["status"] == provs["tiktok_trends"]["status"] == "unavailable"
    assert provs["web_search"]["status"] == "unavailable" and provs["library"]["status"] in ("ok", "error")
    home = client.get("/api/autopilot/status").json()["home"]
    assert home["skipped_today"] >= 1 and [i["type"] for i in home["needs_you"]] == ["videos"]
    # Without any way to discover online (YouTube not connected), Autopilot still runs, watches your videos folder
    # and says what would help.
    client.post("/api/publish/youtube/disconnect", headers=H)
    run("trend_scan")
    home = client.get("/api/autopilot/status").json()["home"]
    assert home["setup"]["can_discover"] is True  # your videos folder
    assert [i["type"] for i in home["needs_you"]] == ["videos"]
    assert client.get("/api/autopilot/status").json()["enabled"]


# ------------------------------------------------------------------ 4: manual content still works
def test_adding_content_by_hand_still_works(client, fakes, tmp_path):
    from clipfoundry import db

    video = tmp_path / "my_talk.mp4"
    video.write_bytes(os.urandom(2000))
    src = client.post("/api/autopilot/sources", headers=H, json={"path": str(video), "rights_status": "OWNED",
                                                                   "basis": "My own recording"}).json()
    assert src["rights_status"] == "OWNED" and src["status"] == "eligible"
    run("source_scout")
    assert db.fetch("sources", src["id"])["status"] == "queued"  # sent to the Clip Hunter
    folder = tmp_path / "recordings"
    folder.mkdir()
    feed = client.post("/api/autopilot/feeds", headers=H, json={"kind": "watch_folder", "name": "Mine",
                                                                  "config": {"path": str(folder)},
                                                                  "rights_status": "OWNED", "rights_basis": "mine"})
    assert feed.status_code == 200
    link = client.post("/api/autopilot/sources", headers=H, json={"url": "https://example.com/talk.mp4"}).json()
    assert link["rights_status"] == "MANUAL_CONFIRMATION_REQUIRED"  # a pasted link without a rights answer waits


# ------------------------------------------------------------------ 5, 6: rights gate and when you are asked
def test_rights_are_still_gated_and_answered_in_one_click(client, fakes):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, rights

    g, _ = fakes
    ids = trending(g, 2)
    connect(client, g, "youtube")
    client.post("/api/autopilot/start", headers=H)
    run("trend_scan")
    run("source_scout")
    src = {s["external_id"]: s for s in db.select("sources")}
    assert {src[v]["status"] for v in ids} == {"needs_rights"}
    assert not queue.jobs(worker="clip_hunter")  # nothing unconfirmed is ever clipped
    with pytest.raises(rights.RightsBlocked):
        rights.gate(src[ids[0]], "ingest")
    home = client.get("/api/autopilot/status").json()["home"]
    assert not [i for i in home["needs_you"] if i["type"] == "rights"]  # by default: skipped, never asked
    client.put("/api/settings", json={"rights_ask_per_video": True})  # Advanced: "Ask me about strong videos..."
    run("source_scout")
    home = client.get("/api/autopilot/status").json()["home"]
    q = [i for i in home["needs_you"] if i["type"] == "rights"]
    assert q and q[0]["question"] == "Can you use this content?" and q[0]["source"]["url"].startswith("https://")

    yes = client.post(f"/api/autopilot/sources/{src[ids[0]]['id']}/permission", headers=H, json={"allowed": True})
    assert yes.json()["rights_status"] == rights.ALLOWLISTED and "You said you have permission" in \
        yes.json()["rights_basis"]
    no = client.post(f"/api/autopilot/sources/{src[ids[1]]['id']}/permission", headers=H, json={"allowed": False})
    assert no.json()["rights_status"] == rights.BLOCKED and no.json()["status"] == "blocked"
    run("source_scout")
    after = {s["external_id"]: s for s in db.select("sources")}
    # Yes: allowed, but a YouTube-hosted video is still not downloaded (YouTube's terms). It is not asked about
    # either: the activity log offers "Add the file", and Autopilot moves on to other videos.
    assert after[ids[0]]["status"] == "needs_file" and not queue.jobs(worker="clip_hunter")
    home = client.get("/api/autopilot/status").json()["home"]
    assert not [i for i in home["needs_you"] if i["type"] == "file"]
    log = {a["id"]: a for a in client.get("/api/autopilot/activity").json()["items"]}
    assert log[after[ids[0]]["id"]]["can_add_file"] and "YouTube Studio" in log[after[ids[0]]["id"]]["why"]
    assert not [i for i in home["needs_you"] if i["type"] == "rights" and i["source"]["id"] == after[ids[1]]["id"]]
    video = os.path.join(os.environ["CLIPFOUNDRY_DATA"], "orig.mp4")
    with open(video, "wb") as fh:
        fh.write(os.urandom(1000))
    client.post(f"/api/autopilot/sources/{after[ids[0]]['id']}/file", headers=H, json={"path": video})
    run("source_scout")
    assert db.fetch("sources", after[ids[0]]["id"])["status"] == "queued"
    assert [j["ref_id"] for j in queue.jobs(worker="clip_hunter")] == [after[ids[0]]["id"]]
    assert db.fetch("sources", after[ids[1]]["id"])["status"] == "blocked"  # No stays no


def test_you_are_asked_only_about_strong_videos_and_only_when_needed(client, fakes, tmp_path):
    from clipfoundry import db
    from clipfoundry.autopilot import scout

    g, _ = fakes
    trending(g, 12)
    g.add_video("tiny", "podcast interview tiny channel", "UCsmall00000000001", views=10, age_hours=700,
                duration="PT5M", category="10")
    g.add_video("live1", "Podcast interview live now", "UClive000000000001", views=2_000_000, live_viewers=90_000,
                duration="P0D")  # a YouTube live stream: a yes could not be used without the download setting
    connect(client, g, "youtube")
    client.post("/api/autopilot/start", headers=H)
    client.put("/api/settings", json={"rights_ask_per_video": True})  # the questions are off by default
    run("trend_scan")
    run("source_scout")
    asked = [i for i in client.get("/api/autopilot/status").json()["home"]["needs_you"] if i["type"] == "rights"]
    unconfirmed = db.select("sources", "status = 'needs_rights'")
    assert len(unconfirmed) >= 12 and len(asked) == scout.RIGHTS_QUESTIONS  # not a dozen questions
    strongest = sorted((s for s in unconfirmed if s["kind"] != "live"), key=lambda s: -s["source_score"])
    strongest = strongest[:scout.RIGHTS_QUESTIONS]
    assert {i["source"]["id"] for i in asked} == {s["id"] for s in strongest}
    assert all(s["source_score"] >= scout.RIGHTS_MIN_SCORE for s in strongest)
    tiny = next(s for s in db.select("sources") if s["external_id"] == "tiny")
    live = next(s for s in db.select("sources") if s["external_id"] == "live1")
    assert live["status"] == "needs_rights" and live["kind"] == "live"
    assert not {tiny["id"], live["id"]} & {i["source"]["id"] for i in asked}

    # Once today's plan is covered by videos you may use, the open questions go away (nothing to decide today).
    for k in range(3):
        f = tmp_path / f"mine{k}.mp4"
        f.write_bytes(os.urandom(1000))
        client.post("/api/autopilot/sources", headers=H, json={"path": str(f), "rights_status": "OWNED",
                                                                 "basis": "mine"})
    run("source_scout")
    assert db.scalar("SELECT COUNT(*) FROM sources WHERE status = 'queued'") == 3
    assert not [i for i in client.get("/api/autopilot/status").json()["home"]["needs_you"] if i["type"] == "rights"]


# ------------------------------------------------------------------ 7, 8: the simple page and the advanced controls
def test_the_main_page_speaks_plainly_and_needs_no_configuration(client, fakes):
    g, _ = fakes
    trending(g, 2)
    connect(client, g, "youtube")
    st = client.post("/api/autopilot/start", headers=H).json()
    home = st["home"]
    assert set(home) == {"setup", "currently", "next_look", "working", "needs_you", "opportunities", "upcoming",
                         "empty", "auto_publish", "pc_note", "keep_awake", "skipped_today", "my_videos", "posts"}
    assert "PC on" in home["pc_note"] and home["auto_publish"]["tiktok"]["supported"] is False
    assert "between 9 AM and 9 PM" in home["pc_note"] and "window open" in home["pc_note"]
    assert home["my_videos"]["watching"] and home["my_videos"]["videos"] == 0
    run("trend_scan")
    run("source_scout")
    home = client.get("/api/autopilot/status").json()["home"]
    text = words(home)
    assert text and not [w for w in JARGON if w.lower() in text.lower()], text
    assert home["currently"] in ("Looking for opportunities", "Starting", "Finding trending videos",
                                 "Choosing the best videos", "Planning posting times", "Checking your folders")
    client.post("/api/autopilot/stop-all", headers=H)
    assert client.get("/api/autopilot/status").json()["home"]["currently"].startswith("Stopped")
    client.post("/api/autopilot/resume", headers=H)


def test_advanced_controls_are_all_still_there(client, fakes):
    for path in ("/api/autopilot/feeds", "/api/autopilot/rights", "/api/autopilot/sources", "/api/autopilot/jobs",
                 "/api/autopilot/workers", "/api/autopilot/quota", "/api/autopilot/trends", "/api/autopilot/gpu",
                 "/api/autopilot/learning", "/api/autopilot/events"):
        assert client.get(path).status_code == 200, path
    st = client.get("/api/autopilot/status").json()
    for key in ("workers", "gpu", "quota", "providers", "rights", "trends", "events", "actions", "queue"):
        assert key in st, key
    s = client.put("/api/settings", json={"trend_topics": "chess", "youtube_quota_default": 20000,
                                          "autopilot_process": "in_app", "rights_auto_creative_commons": True}).json()
    assert (s["trend_topics"], s["youtube_quota_default"], s["autopilot_process"]) == ("chess", 20000, "in_app")


def test_the_page_shows_the_video_being_worked_on_and_the_posts_waiting(client, fakes):
    """The redesigned Home and Autopilot pages show which video Autopilot works on (its thumbnail, the step and the
    job's own progress, never an estimate) and how many posts wait for your OK or for you to settle something."""
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    g, _ = fakes
    connect(client, g, "youtube")
    client.post("/api/autopilot/start", headers=H)
    home = client.get("/api/autopilot/status").json()["home"]
    assert home["working"] is None and home["posts"] == {"review": 0, "fix": 0}

    project = db.create_project("Morning show episode 12")
    src = db.insert("sources", {"id": db.new_id(), "platform": "local", "external_id": "ep12", "title": "Morning show",
                                "status": "analyzing", "project_id": project["id"]})
    job = queue.enqueue("analyze_source", {"source_id": src["id"]}, ref=("source", src["id"]))
    db.update("worker_jobs", job["id"], status="running")
    home = client.get("/api/autopilot/status").json()["home"]
    assert home["working"] == {"title": "Morning show", "project_id": project["id"], "has_thumbnail": False,
                               "step": "Finding the best moments", "progress": None}
    queue.progress(job["id"], 0.46)
    assert client.get("/api/autopilot/status").json()["home"]["working"]["progress"] == 0.46

    for status in ("awaiting_approval", "awaiting_approval", "reconciling", "action_needed", "failed", "blocked",
                   "published"):
        db.insert("scheduled_publications", {"id": db.new_id(), "clip_id": "c", "platform": "youtube",
                                             "status": status})
    # an OK from before ClipFoundry checked the exact file no longer covers the post: it waits for you again
    db.insert("scheduled_publications", {"id": db.new_id(), "clip_id": "c", "platform": "youtube", "status": "approved",
                                         "approval": {"hash": "old", "scheme": 1}})
    assert client.get("/api/autopilot/status").json()["home"]["posts"] == {"review": 3, "fix": 4}

    client.post("/api/autopilot/stop-all", headers=H)  # stopped: nothing is being worked on
    assert client.get("/api/autopilot/status").json()["home"]["working"] is None
    client.post("/api/autopilot/resume", headers=H)


# ------------------------------------------------------------------ 9: accounts that drop
def test_a_dropped_account_is_one_plain_needs_you_message(client, fakes):
    from clipfoundry import db

    g, t = fakes
    connect(client, g, "youtube")
    connect(client, t, "tiktok")
    st = client.post("/api/autopilot/start", headers=H).json()
    assert st["home"]["setup"]["connected"] == ["youtube", "tiktok"] and st["home"]["needs_you"] == []

    db.save_account("youtube", info={"needs_reconnect": True})  # Google refused the stored sign-in
    items = client.get("/api/autopilot/status").json()["home"]["needs_you"]
    assert [(i["type"], i["title"]) for i in items] == [("account", "Reconnect YouTube")]

    # TikTok disconnected while a post is planned there: one message, even though the publisher also noticed
    project = db.create_project("p", source_path="x.mp4", status="ready")
    clip = db.create_clip(project["id"], start=0, end=10, title="t", status="ready")
    db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "tiktok", "title": "My clip",
                                         "status": "approved", "planned_at": time.time() + 3600})
    client.post("/api/publish/tiktok/disconnect", headers=H)
    from clipfoundry.autopilot import state

    state.action("connect:tiktok", "publish", "Connect Tiktok to publish", "Tiktok is not connected.",
                 "Settings → Publishing → Connect.")
    items = client.get("/api/autopilot/status").json()["home"]["needs_you"]
    assert [(i["type"], i["title"]) for i in items] == [("account", "Reconnect YouTube"),
                                                        ("account", "Reconnect TikTok")]
    assert "1 planned post cannot go out" in items[1]["detail"]


# ------------------------------------------------------------------ 10: a night with nothing it may use
def test_a_night_of_other_peoples_videos_says_so_and_your_own_video_is_clipped(client, fakes):
    """The overnight report: connected, START AUTOPILOT, walked away, nothing happened. Every video found belonged to
    other people, so everything was skipped and the page said "Nothing right now". Now Needs you says it plainly,
    once, and a video put in your videos folder goes to the Clip Hunter by itself."""
    from clipfoundry import db
    from clipfoundry.autopilot import myvideos, queue

    g, _ = fakes
    trending(g, 3)
    connect(client, g, "youtube")
    client.post("/api/autopilot/start", headers=H)
    run("trend_scan")
    run("source_scout")
    home = client.get("/api/autopilot/status").json()["home"]
    item = next(i for i in home["needs_you"] if i["type"] == "videos")
    assert item["folder"]["path"] == home["my_videos"]["path"] and item["folder"]["videos"] == 0
    assert home["next_look"] and home["next_look"] > time.time()  # when it looks online again, for the page

    folder = myvideos.folder()
    assert folder.is_dir() and folder == Path(os.environ["CLIPFOUNDRY_VIDEOS"]).resolve()
    video = folder / "my skateboard trick.mp4"
    video.write_bytes(os.urandom(4000))
    home = client.get("/api/autopilot/status").json()["home"]
    assert not [i for i in home["needs_you"] if i["type"] == "videos"]  # found: it is picked up at the next check
    old = time.time() - 600  # finished copying a while ago
    os.utime(video, (old, old))
    run("feed_scan")
    run("source_scout")
    src = db.select("sources", "platform = 'local'")[0]
    assert (src["rights_status"], src["status"]) == ("OWNED", "queued") and "videos folder" in src["rights_basis"]
    assert [j["ref_id"] for j in queue.jobs(worker="clip_hunter")] == [src["id"]]
    home = client.get("/api/autopilot/status").json()["home"]
    assert not [i for i in home["needs_you"] if i["type"] == "videos"] and home["my_videos"]["videos"] == 1

    # all of it used and no new clip for a day: it asks for new videos instead
    db.update("sources", src["id"], status="exhausted")
    home = client.get("/api/autopilot/status").json()["home"]
    assert [(i["type"], i["title"]) for i in home["needs_you"]] == [("videos", "Autopilot has used all your videos")]


def test_the_videos_folder_is_set_up_once_and_a_removal_is_respected(client, fakes, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import myvideos

    opened = []
    monkeypatch.setattr(myvideos.subprocess, "Popen", lambda args, **kw: opened.append(args))
    monkeypatch.setattr(myvideos.sys, "platform", "linux")
    client.post("/api/autopilot/start", headers=H)
    client.post("/api/autopilot/enable", headers=H, json={"enabled": True})
    client.post("/api/autopilot/start", headers=H)
    feeds = db.select("source_feeds")
    assert len(feeds) == 1 and feeds[0]["config"]["my_videos"] and len(db.select("source_rights")) == 1
    assert client.get("/api/autopilot/my-videos").json()["watching"] is True
    # removed under Advanced: START does not bring it back...
    client.delete(f"/api/autopilot/feeds/{feeds[0]['id']}", headers=H)
    client.post("/api/autopilot/start", headers=H)
    assert db.select("source_feeds") == [] and client.get("/api/autopilot/my-videos").json()["watching"] is False
    # ...OPEN MY VIDEOS FOLDER does, shows it in the file manager, and looks at it right away
    out = client.post("/api/autopilot/my-videos/open", headers=H).json()
    assert out["opened"] and out["watching"] and opened == [["xdg-open", out["path"]]]
    assert len(db.select("source_feeds")) == 1 and len(db.select("source_rights", "active = 1")) == 1
    assert client.post("/api/autopilot/my-videos/open").status_code == 403  # only from ClipFoundry's own page


# ------------------------------------------------------------------ 11: the PC stays awake while Autopilot is on
class Kernel32:
    """Windows' SetThreadExecutionState, faked: records each request and the thread that made it; `answer` is what
    Windows returns (0 means it refused)."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self.answer = 0x80000000

    def SetThreadExecutionState(self, flags):  # noqa: N802 - the Windows function's name
        self.calls.append((flags, threading.get_ident()))
        return self.answer


@pytest.fixture()
def windows(monkeypatch):
    """A Windows keep-awake request against a fake kernel32, with a clock the test moves."""
    import ctypes

    from clipfoundry import awake

    k32 = Kernel32()
    monkeypatch.setattr(ctypes, "windll", type("WinDLL", (), {"kernel32": k32})(), raising=False)
    keeper = awake.KeepAwake()
    keeper.supported = True
    clock = [1000.0]
    keeper.clock = lambda: clock[0]
    monkeypatch.setattr(awake, "keeper", keeper)
    return k32, keeper, clock


def home_now(client) -> dict:
    return client.get("/api/autopilot/status").json()["home"]


def sleep_items(home: dict) -> list[dict]:
    return [i for i in home["needs_you"] if i["type"] == "sleep"]


def test_the_pc_is_kept_awake_while_autopilot_is_on(client, windows):
    from clipfoundry import awake, db
    from clipfoundry.autopilot import host, state

    k32, keeper, _ = windows
    sup = host.Supervisor()
    sup._keep_awake()  # Autopilot off: nothing asked
    assert k32.calls == [] and not keeper.holding
    assert home_now(client)["keep_awake"] == "off"
    assert "While Autopilot is on, ClipFoundry keeps this PC from going to sleep" in home_now(client)["pc_note"]
    client.post("/api/autopilot/start", headers=H)
    home = home_now(client)  # on, but not asked yet: the page does not claim it worked
    assert home["keep_awake"] == "pending" and "is asking Windows" in home["pc_note"] and not sleep_items(home)
    sup._keep_awake()
    sup._keep_awake()  # asked once, not every few seconds
    assert [f for f, _ in k32.calls] == [awake.ES_CONTINUOUS | awake.ES_SYSTEM_REQUIRED] and keeper.holding
    home = home_now(client)
    assert home["keep_awake"] == "on" and "is keeping this PC from going to sleep" in home["pc_note"]
    client.post("/api/autopilot/enable", headers=H, json={"enabled": False})
    sup._keep_awake()
    assert k32.calls[-1][0] == awake.ES_CONTINUOUS and not keeper.holding
    assert [e["message"] for e in state.events(10, kind="keep_awake")][:2] == [
        "No longer keeping this PC awake (Autopilot or Keep the PC awake is off)",
        "Keeping this PC awake while Autopilot is on"]
    # the setting (Advanced) turns it off, and on other systems nothing is asked at all
    db.save_settings({"autopilot_enabled": True, "autopilot_keep_awake": False})
    sup._keep_awake()
    assert not keeper.holding and len(k32.calls) == 2
    home = home_now(client)
    assert home["keep_awake"] == "off" and "Keep the PC awake is off in Settings" in home["pc_note"]
    assert awake.KeepAwake().hold(True) is (sys.platform == "win32")


def test_a_refused_keep_awake_request_is_shown_with_what_to_do_until_a_retry_works(client, windows):
    from clipfoundry import awake
    from clipfoundry.autopilot import host, state

    k32, keeper, clock = windows
    k32.answer = 0  # Windows refuses
    sup = host.Supervisor()
    client.post("/api/autopilot/start", headers=H)
    sup._keep_awake()
    assert len(k32.calls) == 1 and not keeper.holding and keeper.error
    home = home_now(client)
    assert home["keep_awake"] == "failed"
    assert "did not let ClipFoundry keep this PC awake" in home["pc_note"]
    assert "keeping this PC from going" not in home["pc_note"]
    [item] = sleep_items(home)
    assert item["title"] == "Your PC may go to sleep and stop Autopilot"
    assert "Power & battery" in item["fix"] and "Never" in item["fix"] and "tries again every minute" in item["fix"]
    assert home["needs_you"][0]["type"] == "sleep"  # before anything that needs a working PC
    assert "sleep" not in [e.get("type") for e in home["needs_you"][1:]]
    assert sup.status()["keep_awake"] is False and sup.status()["keep_awake_error"]
    # not asked again on every check (every 5 s), and said once in the activity log
    sup._keep_awake()
    clock[0] += awake.KeepAwake.retry_seconds - 1
    sup._keep_awake()
    assert len(k32.calls) == 1
    refused = [e for e in state.events(10, kind="keep_awake")]
    assert len(refused) == 1 and refused[0]["level"] == "warning" and "did not let" in refused[0]["message"]
    # a minute later it asks again; still refused: still shown, not logged again
    clock[0] += 1
    sup._keep_awake()
    assert len(k32.calls) == 2 and sleep_items(home_now(client)) and len(state.events(10, kind="keep_awake")) == 1
    # Windows accepts the next try: the warning goes away by itself and the page says it works
    k32.answer = 0x80000000
    clock[0] += awake.KeepAwake.retry_seconds
    sup._keep_awake()
    assert keeper.holding and not keeper.error
    home = home_now(client)
    assert home["keep_awake"] == "on" and not sleep_items(home)
    assert "is keeping this PC from going to sleep" in home["pc_note"]
    assert state.events(1, kind="keep_awake")[0]["message"] == "Keeping this PC awake while Autopilot is on"
    assert len({t for _, t in k32.calls}) == 1  # every try from the thread that now holds the request


@pytest.mark.parametrize("turn_off", ["autopilot", "setting"])
def test_turning_autopilot_or_keep_awake_off_clears_the_sleep_warning(client, windows, turn_off):
    from clipfoundry import awake, db
    from clipfoundry.autopilot import host

    k32, keeper, _ = windows
    k32.answer = 0
    sup = host.Supervisor()
    client.post("/api/autopilot/start", headers=H)
    sup._keep_awake()
    assert sleep_items(home_now(client))
    if turn_off == "autopilot":
        client.post("/api/autopilot/enable", headers=H, json={"enabled": False})
    else:
        client.put("/api/settings", headers=H, json={"autopilot_keep_awake": False})
        assert db.get_settings()["autopilot_keep_awake"] is False
    home = home_now(client)  # at once, before the next check
    assert home["keep_awake"] == "off" and not sleep_items(home)
    assert "did not let" not in home["pc_note"]
    sup._keep_awake()
    assert not keeper.error and len(k32.calls) == 1  # nothing to give up: it was never granted
    # turned on again right away: asked at once (the earlier refusal's wait is forgotten), and Windows says yes now
    k32.answer = 0x80000000
    if turn_off == "autopilot":
        client.post("/api/autopilot/enable", headers=H, json={"enabled": True})
    else:
        client.put("/api/settings", headers=H, json={"autopilot_keep_awake": True})
    assert home_now(client)["keep_awake"] == "pending"
    sup._keep_awake()
    assert keeper.holding and k32.calls[-1][0] == awake.ES_CONTINUOUS | awake.ES_SYSTEM_REQUIRED
    assert home_now(client)["keep_awake"] == "on"


def test_the_same_thread_asks_and_gives_up_keeping_the_pc_awake(client, windows):
    """SetThreadExecutionState is per thread: a request given up from another thread would leave the PC awake."""
    from clipfoundry import awake
    from clipfoundry.autopilot import host

    k32, keeper, _ = windows
    client.post("/api/autopilot/start", headers=H)
    sup = host.Supervisor()
    watcher = threading.Thread(target=sup._watch, daemon=True)
    watcher.start()
    deadline = time.time() + 10
    while not keeper.holding and time.time() < deadline:
        time.sleep(0.05)
    assert keeper.holding
    assert keeper.hold(False) is True and len(k32.calls) == 1  # another thread cannot give it up
    sup._stop.set()
    watcher.join(timeout=10)
    assert not watcher.is_alive() and not keeper.holding
    assert [f for f, _ in k32.calls] == [awake.ES_CONTINUOUS | awake.ES_SYSTEM_REQUIRED, awake.ES_CONTINUOUS]
    assert k32.calls[0][1] == k32.calls[1][1] == watcher.ident != threading.get_ident()

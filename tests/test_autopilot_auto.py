"""Hands-off Autopilot: automatic discovery (YouTube, originals behind short clips, optional web search, a free-license
library), eligibility without per-video questions (ownership, agreements with their conditions, licenses), getting
files only in allowed ways, automatic publishing where the platform allows it, and the schedule across downtime and
daylight saving time. Against local stand-ins for Google, TikTok, Tavily and Wikimedia Commons (mock/sandbox tests:
nothing here reaches a real service)."""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from zoneinfo import ZoneInfo

import pytest
from fake_platforms import FakeCommons, FakeGoogle, FakeTavily, FakeTikTok
from quality_stub import passed_report

CHI = ZoneInfo("America/Chicago")
H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry import db
    from clipfoundry.autopilot import providers
    from clipfoundry.publish import tiktok, youtube

    g, t, web, lib = FakeGoogle(), FakeTikTok(), FakeTavily(), FakeCommons()
    for name, value in {"AUTH_URL": f"{g.url}/o/oauth2/v2/auth", "TOKEN_URL": f"{g.url}/token",
                        "REVOKE_URL": f"{g.url}/revoke", "API_URL": f"{g.url}/youtube/v3",
                        "UPLOAD_URL": f"{g.url}/upload/youtube/v3/videos", "CHUNK": 256 * 1024}.items():
        monkeypatch.setattr(youtube, name, value)
    monkeypatch.setattr(tiktok, "AUTH_URL", f"{t.url}/v2/auth/authorize/")
    monkeypatch.setattr(tiktok, "API_URL", f"{t.url}/v2")
    monkeypatch.setattr(providers, "TAVILY_URL", f"{web.url}/search")
    monkeypatch.setattr(providers, "COMMONS_API", f"{lib.url}/w/api.php")
    db.init()
    db.save_settings({"autopilot_public_videos": False})  # exercise reuse-covered-only discovery
    db.save_settings({"youtube_api_key": "test-api-key", "trend_topics": "podcast, space", "autopilot_enabled": True,
                      "youtube_client_id": "cid.apps.googleusercontent.com", "youtube_client_secret": "csecret",
                      "tiktok_client_key": "tkkey", "tiktok_client_secret": "tksecret"})
    yield {"g": g, "t": t, "web": web, "lib": lib, "tmp": tmp_path}
    for s in (g, t, web, lib):
        s.stop()


def run(kind: str, payload: dict | None = None) -> dict:
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    row = queue.enqueue(kind, payload or {})
    return host.HANDLERS[kind](host.Job(queue.get(row["id"]), "test"))


# ------------------------------------------------------------------ discovery
def test_the_original_behind_a_popular_short_is_found(env):
    from clipfoundry import db

    g = env["g"]
    g.add_video("short01aaaa", "Best podcast moment #shorts", "UCclips0000000001", views=2_000_000, duration="PT45S",
                description="Full episode here: https://youtu.be/longvid0001 (and our merch link)")
    g.add_video("longvid0001", "Full episode 88 with Jane", "UCorig00000000001", views=300_000, duration="PT1H12M")
    g.popular = ["short01aaaa"]
    run("trend_scan")
    sigs = {s["external_id"]: s for s in db.select("trend_signals")}
    orig = sigs["longvid0001"]
    assert orig["provider"] == "youtube_original" and "original of" in orig["query"]
    assert orig["raw"]["found_from"].endswith("short01aaaa")
    views = orig["metrics"]["views"]
    assert views["value"] == 300_000 and views["source"] == "YouTube Data API" and views["at"]  # provenance kept
    run("source_scout")
    src = {s["external_id"]: s for s in db.select("sources")}
    assert src["short01aaaa"]["status"] == "skipped" and "short" in src["short01aaaa"]["status_note"]
    assert src["longvid0001"]["status"] in ("needs_rights", "needs_file", "eligible")  # a real candidate


def test_web_search_finds_tiktok_links_without_inventing_statistics(env):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, state

    web, g = env["web"], env["g"]
    db.save_settings({"tavily_api_key": web.key})
    for k in range(3):
        web.add(f"https://www.tiktok.com/@creator{k}/video/73000000000{k}", f"Podcast host reveals secret {k} | TikTok",
                score=0.9 - k / 10, published_date="Tue, 29 Sep 2026 10:00:00 GMT")
    web.add("https://www.youtube.com/watch?v=origfromtt1", "Podcast host reveals secret full interview")
    g.add_video("origfromtt1", "Podcast host reveals secret: full interview", "UCorig00000000002", duration="PT58M")
    run("trend_scan")
    sigs = {s["external_id"]: s for s in db.select("trend_signals")}
    tt = sigs["730000000000"]
    assert tt["platform"] == "tiktok" and tt["channel_id"] == "@creator0" and tt["title"] == "Podcast host reveals secret 0"
    for key in ("views", "likes", "comments"):  # web search does not report TikTok numbers: they stay unknown
        m = tt["metrics"][key]
        assert m["value"] is None and m["source"] == providers.TAVILY and "does not report" in m["note"] and m["at"]
    assert tt["published_at"] is not None
    assert sigs["origfromtt1"]["provider"] == "youtube_original"  # the long video behind the TikTok clip
    assert "tiktok.com" in sigs["origfromtt1"]["raw"]["found_from"]
    run("source_scout")
    assert not db.select("sources", "platform = 'tiktok'")  # a web result is a pointer, not something to clip
    assert db.select("sources", "external_id = 'origfromtt1'")
    use = providers.web_usage(db.get_settings())
    assert use["used"] == len(web.requests) and use["cost_usd"] == 0.0
    assert "podcast" not in state.get("trend:emerging")  # already one of your topics
    assert state.get("providers")["web_search"]["status"] == "ok"


def test_web_search_never_spends_beyond_the_monthly_allowance(env):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, state

    web = env["web"]
    db.save_settings({"tavily_api_key": web.key, "tavily_free_credits": 1, "discovery_monthly_budget_usd": 0})
    web.add("https://www.tiktok.com/@a/video/1", "podcast clip")
    run("trend_scan")
    assert len(web.requests) == 1  # the one included credit, then it stops
    run("trend_scan")
    assert len(web.requests) == 1 and state.get("providers")["web_search"]["status"] == "budget"
    db.save_settings({"discovery_monthly_budget_usd": 0.02})  # 2 more credits at $0.008
    assert providers.web_usage(db.get_settings())["allowed"] == 3


def test_a_failing_provider_does_not_stop_discovery(env):
    from clipfoundry import db
    from clipfoundry.autopilot import state

    web, g = env["web"], env["g"]
    db.save_settings({"tavily_api_key": web.key})
    web.fail = 10
    g.add_video("pod1", "podcast episode", "UCpod0000000000001", duration="PT1H")
    g.popular = ["pod1"]
    out = run("trend_scan")
    provs = state.get("providers")
    assert provs["web_search"]["status"] == "error" and provs["youtube"]["status"] == "ok"
    assert out["signals"] >= 1 and db.select("trend_signals", "external_id = 'pod1'")
    db.save_settings({"tavily_api_key": "wrong"})
    run("trend_scan")
    assert "did not accept" in state.get("providers")["web_search"]["detail"]


def test_the_library_brings_only_licenses_that_allow_reuse(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import access, rights, state

    lib = env["lib"]
    monkeypatch.setattr(access, "LIBRARY_HOSTS", {"commons": ("127.0.0.1",)})  # the stand-in serves the files
    monkeypatch.setattr(access, "LIBRARY_SCHEMES", ("http",))
    lib.add("talk-ccby.webm", "Space talk: life on Mars", "cc-by-4.0", "CC BY 4.0", artist="Ada Lovelace")
    lib.add("talk-pd.webm", "Space briefing from NASA", "pd", "Public domain", artist="NASA",
            attribution_required=False)
    lib.add("talk-sa.webm", "Space lecture share alike", "cc-by-sa-4.0", "CC BY-SA 4.0")
    lib.add("talk-nc.webm", "Space interview non commercial", "cc-by-nc-4.0", "CC BY-NC 4.0")
    lib.add("talk-person.webm", "Space parade with people", "cc-by-4.0", "CC BY 4.0", restrictions="personality")
    lib.add("tiny.webm", "Space short clip", "cc0", "CC0", length=30)
    run("trend_scan")
    assert all("ClipFoundry" in ua for ua in lib.user_agents)  # Wikimedia's User-Agent policy
    assert state.get("providers")["library"]["status"] == "ok"
    run("source_scout")
    src = {s["title"]: s for s in db.select("sources", "platform = 'commons'")}
    cc, pd = src["Space talk: life on Mars"], src["Space briefing from NASA"]
    assert cc["rights_status"] == rights.CC and cc["status"] in ("eligible", "queued")
    assert pd["rights_status"] == rights.PD and pd["status"] in ("eligible", "queued")
    for t in ("Space lecture share alike", "Space interview non commercial", "Space parade with people"):
        assert src[t]["rights_status"] == rights.MANUAL and src[t]["status"] == "needs_rights", t
    assert "share-alike" in src["Space lecture share alike"]["rights_basis"]
    assert src["Space short clip"]["status"] == "skipped"
    credit = rights.attribution(cc)
    assert "Ada Lovelace" in credit and "CC BY 4.0" in credit and "Wikimedia Commons" in credit
    assert rights.attribution(pd) == ""  # public domain without a required credit


def test_a_reupload_of_a_processed_video_is_skipped(env):
    from clipfoundry import db
    from clipfoundry.autopilot import scout

    db.insert("sources", {"platform": "youtube", "external_id": "orig", "title": "Joe explains the startup mistake "
                                                                                "everyone makes", "duration": 3000,
                          "status": "analyzed"})
    again = {"platform": "youtube", "external_id": "copy", "title": "Joe explains the startup mistake everyone makes",
             "duration": 3001}
    assert "Same video" in scout.repeat_of(again)
    assert scout.repeat_of({**again, "duration": 2400}) == ""  # same words, a different (later) episode


# ------------------------------------------------------------------ eligibility: agreements and their conditions
def _confirm(env, src: dict) -> None:
    """YouTube's own answer for this video names the channel the source claims (as the Data API reports it)."""
    from clipfoundry.autopilot import verify

    env["g"].add_video(src["external_id"], src.get("title") or "video", src["channel_id"])
    verify.ensure([src])
    assert verify.confirmed(src), src.get("channel_check")


def _agreement(client, **kw) -> dict:
    body = {"creator": "Pod Creator", "channels": ["UCpod0000000000001"], "evidence": "Email of 2026-09-01: you may "
            "clip and post my episodes", **kw}
    return client.post("/api/autopilot/agreements", headers=H, json=body)


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


def test_an_agreement_covers_a_creator_once_with_its_conditions(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    assert _agreement(client, evidence="").status_code == 400  # never a permission record without evidence
    assert _agreement(client, channels=["not-an-id"]).status_code == 400
    a = _agreement(client, attribution="Clip from Pod Creator's show", platforms=["tiktok"]).json()
    assert a["creator"] == "Pod Creator" and a["channels"] == ["UCpod0000000000001"]
    rule = db.fetch("source_rights", a["rules"][0])
    assert rule["evidence"].startswith("Email of 2026-09-01") and rule["conditions"]["platforms"] == ["tiktok"]
    src = db.insert("sources", {"platform": "youtube", "external_id": "ep1", "title": "Episode 1: the long talk",
                                "channel_id": "UCpod0000000000001", "url": "https://www.youtube.com/watch?v=ep1"})
    _confirm(env, src)
    r = rights.evaluate(src)
    assert r["status"] == rights.ALLOWLISTED and r["auto_allowed"] and "Agreement with Pod Creator" in r["basis"]
    assert rights.platform_allowed(src, "tiktok")[0] and not rights.platform_allowed(src, "youtube")[0]
    assert rights.attribution(rights.apply(src)) == "Clip from Pod Creator's show"
    # other people's material is not covered by an agreement with the creator
    music = {**src, "id": "m", "title": "Pod Creator reacts to the new trailer"}
    assert rights.evaluate(music)["status"] == rights.MANUAL and "reaction" in rights.evaluate(music)["basis"]
    assert client.delete(f"/api/autopilot/agreements/{a['id']}", headers=H).json()["ok"]
    assert rights.evaluate(src)["status"] == rights.MANUAL


def test_expired_and_non_commercial_agreements_are_not_used(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    src = db.insert("sources", {"platform": "youtube", "external_id": "ep2", "title": "Episode 2",
                                "channel_id": "UCpod0000000000001"})
    _confirm(env, src)
    past = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    _agreement(client, expires=past)
    assert rights.evaluate(src)["status"] == rights.MANUAL  # ended
    _agreement(client, commercial=False)
    r = rights.evaluate(src)
    assert r["status"] == rights.MANUAL and "commercial" in r["basis"]
    db.save_settings({"autopilot_commercial_use": False})  # your posts are not commercial: now it covers them
    assert rights.evaluate(src, db.get_settings())["status"] == rights.ALLOWLISTED


# ------------------------------------------------------------------ getting the file
def test_a_creator_folder_supplies_the_file_and_it_keeps_its_provenance(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import access, hunter, scout
    from clipfoundry.pipeline.common import JobContext

    shared = env["tmp"] / "Dropbox" / "Pod Creator raw"
    shared.mkdir(parents=True)
    f = shared / "ep77 raw [ytid77aaaaa].mp4"
    f.write_bytes(os.urandom(2000))
    old = time.time() - 600
    os.utime(f, (old, old))
    a = _agreement(client, media_folder=str(shared)).json()
    src = db.insert("sources", {"platform": "youtube", "external_id": "ytid77aaaaa", "title": "Episode 77",
                                "channel_id": "UCpod0000000000001", "url": "https://www.youtube.com/watch?v=ytid77aaaaa",
                                "status": "discovered", "source_score": 80.0, "expected_clips": 3.0,
                                "duration": 3600})
    _confirm(env, src)
    found = access.resolve(src, db.get_settings())
    assert found["ok"] and found["method"] == "creator_folder" and found["local_path"] == str(f)
    elsewhere = db.insert("sources", {"platform": "youtube", "external_id": "otherid0000", "title": "Episode 78",
                                      "channel_id": "UCpod0000000000001",
                                      "url": "https://www.youtube.com/watch?v=otherid0000"})
    _confirm(env, elsewhere)
    assert not access.resolve(elsewhere, db.get_settings())["ok"]  # not in the folder: skipped, not downloaded
    db.update("sources", elsewhere["id"], status="skipped")
    assert db.select("source_feeds", "kind = 'watch_folder'")  # new files in the folder are found by themselves
    run("rights_check")
    scout.select_for_today(db.get_settings())
    row = db.fetch("sources", src["id"])
    assert row["status"] == "queued" and row["access"]["method"] == "creator_folder"
    project = hunter.ensure_project(row, db.get_settings(), JobContext())
    prov = json.loads((hunter.config.projects_dir() / project["id"] / "provenance.json").read_text())
    assert prov["rights"]["status"] == "ALLOWLISTED" and prov["evidence"]["text"].startswith("Email of")
    assert prov["access"]["method"] == "creator_folder" and prov["file"]["bytes"] == 2000
    assert prov["rights"]["conditions"]["agreement_id"] == a["id"]


def test_no_allowed_way_to_the_file_skips_to_the_next_video(env):
    from clipfoundry import db
    from clipfoundry.autopilot import access, rights, scout, state

    rights.add_rule("channel", "UCown0000000000001", rights.ALLOWLISTED, "Clipping program", platform="youtube")
    hosted = db.insert("sources", {"platform": "youtube", "external_id": "h1", "title": "Hosted talk",
                                   "channel_id": "UCown0000000000001", "url": "https://www.youtube.com/watch?v=h1",
                                   "status": "eligible", "source_score": 90.0, "expected_clips": 3.0,
                                   "rights_status": rights.ALLOWLISTED})
    _confirm(env, hosted)
    f = env["tmp"] / "mine.mp4"
    f.write_bytes(os.urandom(500))
    rights.add_rule("folder", str(env["tmp"]), rights.OWNED, "My recordings")
    mine = db.insert("sources", {"platform": "local", "external_id": "m1", "title": "My talk", "local_path": str(f),
                                 "status": "eligible", "source_score": 50.0, "expected_clips": 3.0,
                                 "rights_status": rights.OWNED})
    gone = db.insert("sources", {"platform": "local", "external_id": "g1", "title": "Deleted", "status": "eligible",
                                 "local_path": str(env["tmp"] / "deleted.mp4"), "source_score": 70.0,
                                 "expected_clips": 3.0, "rights_status": rights.OWNED})
    db.save_settings({"autopilot_sources_per_day": 1})
    picked = scout.select_for_today(db.get_settings())
    assert [p["id"] for p in picked] == [mine["id"]]  # the stronger ones had no allowed way to their file
    assert db.fetch("sources", hosted["id"])["status"] == "needs_file"
    assert db.fetch("sources", gone["id"])["status"] == "needs_file"
    assert not [a for a in state.open_actions() if a["key"].startswith("file:")]  # nothing asked
    assert not access.resolve({"platform": "commons", "url": "https://evil.example.com/x.mp4"}, {})["ok"]
    lib = access.resolve({"platform": "commons", "url": "https://upload.wikimedia.org/wikipedia/commons/a/a.webm"}, {})
    assert lib["ok"] and lib["method"] == "library"


# ------------------------------------------------------------------ automatic publishing
def _clip(env, title="Talk to customers first", warn: str = "") -> dict:
    from clipfoundry import db

    video = env["tmp"] / f"clip-{time.time_ns()}.mp4"
    video.write_bytes(os.urandom(300_000))
    project = db.create_project(title, status="ready", origin="autopilot")
    clip = db.create_clip(project["id"], start=0, end=20, title=title, status="ready", output_path=str(video),
                          duration=20.0, caption_text=title, score=72.0)
    db.insert("clip_scores", {"clip_id": clip["id"], "clip": 72.0, "diversity": 80.0, "retention": 60.0}, key="clip_id")
    for p in ("youtube", "tiktok"):
        db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": p, "style": "direct", "title": title,
                                          "description": f"{title}\n\nFollow for more.", "caption": f"{title} #talk",
                                          "tags": ["talk"], "hashtags": ["#talk"], "score": 60.0, "selected": 1})
    rep = passed_report(clip)
    if warn:
        db.update("quality_reports", rep["id"], checks=[{"name": warn, "label": warn.title(), "status": "warn",
                                                         "kind": "heuristic", "detail": "possible problem"}])
    return clip


def _consent(client, **kw) -> object:
    body = {"platform": "youtube", "visibility": "public", "made_for_kids": False, "daily_limit": 2,
            "start_hour": 9, "end_hour": 21, "agreed": True, **kw}
    return client.post("/api/autopilot/auto-publish", headers=H, json=body)


def test_automatic_publishing_needs_an_explicit_complete_permission(env, client):
    assert _consent(client, agreed=False).status_code == 400
    assert _consent(client, visibility="").status_code == 400  # you choose the visibility, there is no preset
    assert _consent(client, made_for_kids=None).status_code == 400
    r = _consent(client, platform="tiktok")
    assert r.status_code == 400 and "TikTok" in r.json()["detail"]  # TikTok requires your OK on each post
    v = _consent(client).json()
    assert v["youtube"]["enabled"] and "up to 2 clips a day" in v["youtube"]["consent"]["text"]
    assert "public" in v["youtube"]["consent"]["text"] and "not made for kids" in v["youtube"]["consent"]["text"]
    assert not v["tiktok"]["supported"]


def test_posts_are_approved_automatically_and_labeled_as_such(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, state

    db.save_settings({"autopilot_youtube": True, "autopilot_tiktok": True, "autopilot_min_gap_minutes": 30})
    _consent(client)
    good = _clip(env, "Talk to customers first")
    held = _clip(env, "A clip with a framing warning", warn="framing")
    scheduler.plan_new(db.get_settings(), time.time())
    items = {(i["clip_id"], i["platform"]): i for i in db.select("scheduled_publications")}
    yt = items[(good["id"], "youtube")]
    assert yt["status"] == "approved" and yt["approval"]["by"] == "automatic" and yt["approval"]["consent_id"]
    assert yt["privacy"] == "public" and yt["options"]["made_for_kids"] is False
    assert yt["audit"][-1]["event"] == "auto_approved" and "not reviewed by you" in yt["audit"][-1]["detail"]
    assert scheduler.approval_valid(yt)
    assert items[(good["id"], "tiktok")]["status"] == "awaiting_approval"  # TikTok: your OK on each post
    h = items[(held["id"], "youtube")]
    assert h["status"] == "awaiting_approval" and "Held for your review" in h["status_note"]
    scheduler.process_due(db.get_settings(), time.time())
    approvals = next(a for a in state.open_actions() if a["key"] == "approvals")
    assert "TikTok" in approvals["title"]  # held YouTube posts do not nag: only TikTok needs you
    home = client.get("/api/autopilot/status").json()["home"]
    assert any(u["auto"] for u in home["upcoming"]) and home["auto_publish"]["youtube"]["enabled"]


def test_turning_it_off_returns_posts_to_review_and_the_publisher_checks_it(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler

    db.save_settings({"autopilot_youtube": True, "autopilot_tiktok": False})
    _consent(client)
    _clip(env)
    scheduler.plan_new(db.get_settings(), time.time())
    item = db.select("scheduled_publications")[0]
    assert item["status"] == "approved"
    # a new permission (different settings) replaces the old one: posts approved under the old one are re-checked
    _consent(client, visibility="unlisted")
    assert not autopublish.still_covers(db.fetch("scheduled_publications", item["id"]))
    back = client.delete("/api/autopilot/auto-publish/youtube", headers=H).json()
    after = db.fetch("scheduled_publications", item["id"])
    assert back["returned_to_review"] == 1 and after["status"] == "awaiting_approval" and after["approval"] == {}


def test_the_daily_limit_and_your_own_edits_are_respected(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    db.save_settings({"autopilot_youtube": True, "autopilot_tiktok": False, "autopilot_min_gap_minutes": 30,
                      "autopilot_youtube_daily_limit": 10})
    _consent(client, daily_limit=1)
    db.save_settings({"autopilot_youtube_daily_limit": 10})  # more posts are planned than may go out by themselves
    for k in range(5):
        _clip(env, f"Clip number {k} about customers")
    scheduler.plan_new(db.get_settings(), time.time())
    items = db.select("scheduled_publications")
    by_day: dict[str, int] = {}
    for i in items:
        if i["status"] == "approved":
            day = dt.datetime.fromtimestamp(i["planned_at"], CHI).date().isoformat()
            by_day[day] = by_day.get(day, 0) + 1
    assert by_day and max(by_day.values()) == 1  # at most one automatic post per day
    waiting = next(i for i in items if i["status"] == "awaiting_approval")
    scheduler.edit(waiting["id"], {"title": "My own title"})
    scheduler.process_due(db.get_settings(), time.time())
    assert db.fetch("scheduled_publications", waiting["id"])["status"] == "awaiting_approval"  # you decide


def test_an_automatically_approved_youtube_post_is_uploaded_and_scheduled_by_youtube(env, client):
    """The whole publishing leg against the stand-in: permission → automatic approval → due → upload with publishAt
    → recorded as uploaded and scheduled on YouTube (mock test: no real upload)."""
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue, scheduler
    from clipfoundry.publish import youtube
    from clipfoundry.publish.common import challenge_s256, code_verifier

    g = env["g"]
    s = db.get_settings()
    v = code_verifier()
    code = g.approve(youtube.auth_url(s, "http://127.0.0.1:8765/cb", "st", challenge_s256(v)))
    youtube.exchange_code(s, code, v, "http://127.0.0.1:8765/cb")
    db.save_settings({"autopilot_youtube": True, "autopilot_tiktok": False})
    _consent(client, visibility="public")
    _clip(env)
    now = time.time()
    scheduler.plan_new(db.get_settings(), now)
    item = db.select("scheduled_publications")[0]
    due = item["planned_at"] - 60 * float(db.get_settings()["autopilot_upload_lead_minutes"])
    assert scheduler.process_due(db.get_settings(), due + 1)["publishing"] == 1
    host.WorkerHost(periodic=False)
    job = queue.claim("publisher", "test")
    host.HANDLERS["publish"](host.Job(job, "test"))
    done = db.fetch("scheduled_publications", item["id"])
    assert done["status"] == "published" and "scheduled" in done["status_note"].lower()
    meta = next(iter(g.sessions.values()))["meta"]  # public later: private now, YouTube publishes it at publishAt
    assert meta["status"]["privacyStatus"] == "private" and meta["status"]["publishAt"]
    assert meta["status"]["selfDeclaredMadeForKids"] is False
    home = client.get("/api/autopilot/status").json()["home"]
    assert any(u["on_platform"] for u in home["upcoming"])  # uploaded: YouTube publishes it at its time


# ------------------------------------------------------------------ schedule: downtime and daylight saving time
def test_after_downtime_missed_posts_are_spread_out_not_dumped(env):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    db.save_settings({"autopilot_youtube": True, "autopilot_tiktok": False, "autopilot_min_gap_minutes": 45,
                      "autopilot_youtube_daily_limit": 15})
    now = time.time()
    ids = []
    for k in range(4):
        clip = _clip(env, f"Missed clip {k}")
        meta = db.select("metadata_candidates", "clip_id = ? AND platform = 'youtube'", (clip["id"],))[0]
        item = db.insert("scheduled_publications", {
            "clip_id": clip["id"], "platform": "youtube", "metadata_id": meta["id"], "title": f"Missed clip {k}",
            "description": "d", "tags": [], "privacy": "public", "options": {"made_for_kids": False},
            "planned_at": now - 3600 * (5 - k), "status": "awaiting_approval"})
        scheduler.approve(item["id"], {})
        ids.append(item["id"])
    out = scheduler.process_due(db.get_settings(), now)  # the PC was off for hours
    assert out["publishing"] == 0 and out["missed"] == 4
    times = sorted(db.fetch("scheduled_publications", i)["planned_at"] for i in ids)
    assert all(t > now for t in times) and all(b - a >= 45 * 60 for a, b in zip(times, times[1:]))
    for t in times:
        assert 9 <= dt.datetime.fromtimestamp(t, CHI).hour < 21


@pytest.mark.parametrize("day", [dt.date(2026, 3, 8), dt.date(2026, 11, 1)])  # DST starts / ends in Chicago
def test_posting_times_stay_inside_the_window_across_daylight_saving_changes(env, day):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    s = db.get_settings()
    assert (s["autopilot_active_start"], s["autopilot_active_end"]) == (9, 21)  # 9 a.m. to 9 p.m. by default
    slots = scheduler.grid(s, day, 4)
    local = [dt.datetime.fromtimestamp(t, CHI) for t in slots]
    assert len(slots) == 4 and all(x.date() == day and 9 <= x.hour < 21 for x in local)
    assert all(b - a >= 45 * 60 for a, b in zip(slots, slots[1:]))
    assert local[0].hour == 10 and local[0].minute == 30  # the first of four 3-hour blocks, on local clock time


# ------------------------------------------------------------------ quality: framing and other people's sound
def test_framing_is_checked_from_the_render_record():
    from clipfoundry.pipeline import quality

    status = lambda ri: quality.framing_checks(ri)[0]["status"]  # noqa: E731
    assert status({"mode": "face", "faces": 2, "crop_w": 0.316}) == quality.PASS
    assert status({"mode": "center", "faces": 0, "crop_w": 0.316, "layout": "fill"}) == quality.WARN
    assert status({"mode": "center", "faces": 0, "crop_w": 1.0}) == quality.PASS  # a vertical source: no crop
    assert status({"mode": "center", "faces": 0, "crop_w": 0.316, "layout": "fit"}) == quality.PASS
    assert status({"mode": "center"}) == quality.SKIP  # renders from before the framing record


def test_music_is_rejected_under_coverage_for_the_creators_own_material(env, client):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, rights
    from clipfoundry.pipeline import quality

    _agreement(client)
    src = db.insert("sources", {"platform": "youtube", "external_id": "ep9", "title": "Episode 9",
                                "channel_id": "UCpod0000000000001"})
    _confirm(env, src)
    rights.apply(src)
    project = db.create_project("ep9", status="ready", origin="autopilot", source_id=src["id"])
    clip = db.create_clip(project["id"], start=100, end=130, title="t", status="ready")
    db.insert("clip_analysis", {"clip_id": clip["id"], "audio": {"reaction_seconds": 14.0}}, key="clip_id")
    check = gate.sound_rights_check(clip)
    assert check["status"] == quality.FAIL and "possibly music" in check["detail"]
    db.update("clip_analysis", clip["id"], key="clip_id", audio={"reaction_seconds": 2.0})
    assert gate.sound_rights_check(clip)["status"] == quality.PASS
    own = db.create_project("mine", status="ready", origin="autopilot")
    mine = db.create_clip(own["id"], start=0, end=30, title="m", status="ready")
    assert gate.sound_rights_check(mine) is None  # your own content: not this check's business


# ------------------------------------------------------------------ one complete path (slow: real ffmpeg renders)
SPEECH = ("Here is the thing nobody tells you about starting a business. You do not need a big budget. You need one "
          "customer who really has the problem. Ask them what they tried last year. That answer is always the most "
          "useful part of the call. People love honest stories about mistakes. Keep the first version small and cut "
          "the slow parts. Your first ten customers are practice, so help them anyway. ")


@pytest.mark.slow
def test_one_complete_path_from_discovery_to_a_post_scheduled_on_youtube(env, client, monkeypatch):
    """discover → eligibility confirmed automatically (a CC BY license) → file obtained (the library's download) →
    clips rendered → final quality check → scheduled → approved automatically → uploaded and scheduled on YouTube.
    Mock/sandbox: the library, YouTube and TikTok are local stand-ins and the transcript is synthetic (no GPU)."""
    import shutil

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("needs ffmpeg")
    from synthetic_media import make_video, words_from

    from clipfoundry import db, netguard
    from clipfoundry.autopilot import access, gate, host, queue, scheduler
    from clipfoundry.pipeline import transcribe as tr
    from clipfoundry.publish import youtube
    from clipfoundry.publish.common import challenge_s256, code_verifier

    g, lib = env["g"], env["lib"]
    monkeypatch.setattr(access, "LIBRARY_HOSTS", {"commons": ("127.0.0.1",)})
    monkeypatch.setattr(access, "LIBRARY_SCHEMES", ("http",))
    monkeypatch.setattr(netguard, "allowed", lambda ip, allow_private: True)  # the stand-in lives on this computer
    original = make_video(env["tmp"] / "talk.mp4", seconds=75.0, size="360x640")  # vertical: nothing is cropped
    lib.add("business-talk.mp4", "Podcast talk: starting a business", "cc-by-4.0", "CC BY 4.0", artist="Ada Byron",
            data=original.read_bytes())

    def synthetic(wav, duration, settings, ctx, lo=0.0, hi=1.0, vad=True, allow_cpu_fallback=True):
        ws = [w for w in words_from(SPEECH * 8, step=0.36, length=0.28) if w["end"] < duration - 0.5]
        return {"segments": [{"start": ws[0]["start"], "end": ws[-1]["end"], "words": ws,
                              "text": " ".join(w["w"] for w in ws)}], "language": "en",
                "runtime": {"device": "cpu", "requested_device": "cpu", "compute_type": "int8", "model": "test"}}

    monkeypatch.setattr(tr, "transcribe", synthetic)
    s = db.get_settings()
    v = code_verifier()
    youtube.exchange_code(s, g.approve(youtube.auth_url(s, "http://127.0.0.1:8765/cb", "st", challenge_s256(v))), v,
                          "http://127.0.0.1:8765/cb")
    db.save_settings({"youtube_api_key": "", "trend_topics": "podcast", "autopilot_youtube": True,
                      "autopilot_tiktok": True, "encoder": "x264", "x264_preset": "ultrafast",
                      "autopilot_clips_per_source": 2, "autopilot_min_quality": 0, "min_duration": 12.0,
                      "max_duration": 40.0, "target_duration": 22.0})
    assert _consent(client, daily_limit=3).status_code == 200

    host.WorkerHost(periodic=False)

    def drain(worker: str) -> None:
        while (job := queue.claim(worker, "test")) is not None:
            queue.complete(job, "test", host.HANDLERS[job["kind"]](host.Job(job, "test")) or {})

    run("trend_scan")
    run("source_scout")
    src = db.select("sources", "platform = 'commons'")[0]
    assert src["rights_status"] == "CREATIVE_COMMONS" and src["status"] == "queued"  # no question asked
    assert src["access"]["method"] == "library"
    drain("clip_hunter")
    drain("analyzer")
    src = db.fetch("sources", src["id"])
    assert src["clips_selected"] >= 1, src["status_note"]
    from clipfoundry import config

    prov = json.loads((config.projects_dir() / src["project_id"] / "provenance.json").read_text())
    assert prov["rights"]["status"] == "CREATIVE_COMMONS" and prov["access"]["method"] == "library"
    assert "Ada Byron" in prov["attribution"] and prov["license"]["license"] == "cc-by-4.0"
    drain("packager")
    drain("quality_gate")
    clips = [c for c in db.list_clips(src["project_id"]) if c["status"] == "ready"]
    reports = [gate.report_for(c) for c in clips]
    assert all(r and r["status"] == "passed" for r in reports), [r and r["blockers"] for r in reports]
    assert all({"framing", "sound_rights"} <= {c["name"] for c in r["checks"]} for r in reports)
    scheduler.plan_new(db.get_settings(), time.time())
    items = db.select("scheduled_publications")
    yt = [i for i in items if i["platform"] == "youtube" and i["status"] == "approved"]
    tt = [i for i in items if i["platform"] == "tiktok"]
    assert yt and all(i["approval"]["by"] == "automatic" for i in yt), [(i["status"], i["status_note"]) for i in items]
    assert tt and all(i["status"] == "awaiting_approval" for i in tt)  # TikTok: your OK on each post
    assert "Wikimedia Commons" in yt[0]["description"] and "Ada Byron" in yt[0]["description"]  # the credit line
    first = min(yt, key=lambda i: i["planned_at"])
    due = first["planned_at"] - 60 * float(db.get_settings()["autopilot_upload_lead_minutes"])
    scheduler.process_due(db.get_settings(), due + 1)
    drain("publisher")
    done = db.fetch("scheduled_publications", first["id"])
    assert done["status"] == "published" and "scheduled" in done["status_note"].lower(), done["status_note"]
    meta = next(iter(g.sessions.values()))["meta"]
    assert meta["status"]["privacyStatus"] == "private" and meta["status"]["publishAt"]  # YouTube makes it public
    # a restart does not upload it again: the publish job is idempotent and the post is recorded as done
    assert queue.enqueue("publish", {"scheduled_id": first["id"]}, idem_key=f"publish:{first['id']}")
    drain("publisher")
    assert len(g.videos) == 1

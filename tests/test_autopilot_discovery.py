"""Trend Scout, Source Scout, trend scoring, the rights gate, the YouTube quota manager and data retention."""
from __future__ import annotations

import os
import time

import pytest

from fake_platforms import FakeGoogle

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


@pytest.fixture()
def google(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import youtube

    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    g = FakeGoogle()
    monkeypatch.setattr(youtube, "API_URL", f"{g.url}/youtube/v3")
    db.save_settings({"youtube_api_key": "test-api-key", "trend_topics": "podcast, ufc, gaming",
                      "autopilot_enabled": True})
    yield g
    g.stop()


def run(kind: str, payload: dict | None = None) -> dict:
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)  # registers the handlers
    row = queue.enqueue(kind, payload or {})
    return host.HANDLERS[kind](host.Job(queue.get(row["id"]), "test"))


# ------------------------------------------------------------------ trend score
def _sig(**kw) -> dict:
    from clipfoundry.autopilot import trends

    base = {"id": kw.pop("id", "s1"), "platform": kw.pop("platform", "feed"), "kind": "video", "raw": {},
            "published_at": time.time() - 3600 * kw.pop("age_h", 10)}
    views = kw.pop("views", None)
    likes = kw.pop("likes", None)
    base["metrics"] = {"views": trends.m(views), "likes": trends.m(likes), "comments": trends.m(kw.pop("comments", 0))}
    return {**base, **kw}


def test_momentum_beats_size():
    from clipfoundry.autopilot import trends

    now = time.time()
    fresh = _sig(id="fresh", views=500_000, likes=20_000, age_h=10)
    old = _sig(id="old", views=10_000_000, likes=200_000, age_h=24 * 700)
    fresh_hist = [{"at": now - 7200, "views": 380_000}, {"at": now, "views": 500_000}]
    old_hist = [{"at": now - 7200, "views": 9_999_900}, {"at": now, "views": 10_000_000}]
    a = trends.score(fresh, fresh_hist, {}, 2, now)
    b = trends.score(old, old_hist, {}, 0, now)
    assert a["mode"] == "momentum" and a["score"] > b["score"] + 20
    assert a["components"]["velocity"]["status"] == "observed"
    single = trends.score(fresh, [], {}, 0, now)
    assert single["components"]["velocity"]["status"] == "estimated"  # one reading: average since upload


def test_missing_metrics_are_never_filled_in():
    from clipfoundry.autopilot import trends

    s = _sig(views=5000, likes=None, age_h=5)
    r = trends.score(s, [], {}, 0)
    assert "engagement" not in r["components"] and any("engagement" in n for n in r["notes"])
    assert s["metrics"]["likes"]["status"] == "unavailable"


def test_youtube_data_keeps_youtube_order_without_derived_metrics_approval():
    from clipfoundry.autopilot import trends

    s = _sig(platform="youtube", views=900_000, likes=1000, platform_rank=3, raw={"list_size": 50})
    r = trends.score(s, [], {"youtube_derived_metrics_approved": False})
    assert r["mode"] == "platform_order" and list(r["components"]) == ["platform_order"]
    assert r["score"] == pytest.approx(96.0) and "Developer Policies" in r["notes"][0]
    approved = trends.score(s, [], {"youtube_derived_metrics_approved": True})
    assert approved["mode"] == "momentum" and trends.DERIVED_DISCLOSURE in approved["notes"]


def test_recurring_topics_across_creators():
    from clipfoundry.autopilot import trends

    sigs = [{"id": "a", "channel_id": "c1", "keywords": ["jones", "fight"]},
            {"id": "b", "channel_id": "c2", "keywords": ["jones", "reaction"]},
            {"id": "c", "channel_id": "c3", "keywords": ["fight", "jones"]},
            {"id": "d", "channel_id": "c1", "keywords": ["jones"]},
            {"id": "e", "channel_id": "c4", "keywords": ["cooking"]}]
    rec = trends.recurrence(sigs)
    assert rec["a"] == 2 and rec["e"] == 0  # the same creator does not count twice
    assert trends.topic_label(sigs[0], sigs) == "jones"


# ------------------------------------------------------------------ rights
def test_rights_evaluation_order_and_policy(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, verify

    settings = db.get_settings()
    src = db.insert("sources", {"platform": "youtube", "external_id": "v1", "title": "t", "channel_id": "UCabc",
                                "url": "https://www.youtube.com/watch?v=v1"})
    r = rights.evaluate(src, settings)
    assert r["status"] == rights.MANUAL and not r["auto_allowed"]  # public/trending is not authorization
    cc = rights.evaluate({**src, "license": "creativeCommon"}, settings)
    assert cc["status"] == rights.CC and cc["auto_allowed"]  # a CC BY license allows reuse (credit added)
    assert not rights.evaluate({**src, "license": "creativeCommon"}, {**settings, "rights_auto_creative_commons":
                                                                        False})["auto_allowed"]  # ...unless turned off
    with pytest.raises(ValueError):
        rights.add_rule("channel", "UCabc", rights.ALLOWLISTED)  # the permission must be recorded
    rights.add_rule("channel", "UCabc", rights.ALLOWLISTED, "Official clipping program, joined 2026-09-01",
                    platform="youtube")
    r = rights.evaluate(src, settings)  # the channel is only claimed: the rule does not count yet
    assert r["status"] == rights.MANUAL and r["basis"].startswith("channel not confirmed")
    src["channel_check"] = verify.judge(src, "UCabc", "ABC", verify.YOUTUBE_DATA)  # as YouTube reports it
    assert rights.evaluate(src, settings)["status"] == rights.ALLOWLISTED
    rights.add_rule("source", src["id"], rights.BLOCKED, "Contains licensed music")
    assert rights.evaluate(src, settings)["status"] == rights.BLOCKED  # BLOCKED always wins
    with pytest.raises(rights.RightsBlocked):
        rights.gate(src, "publish", settings)
    db.save_account("youtube", tokens={"access_token": "x", "expires_at": 0}, account_id="UCmine")
    mine = {**src, "id": "other", "channel_id": "UCmine"}
    assert rights.evaluate(mine, settings)["status"] == rights.MANUAL  # YouTube confirmed UCabc, not UCmine
    mine["channel_check"] = verify.judge(mine, "UCmine", "Me", verify.YOUTUBE_DATA)
    assert rights.evaluate(mine, settings)["status"] == rights.OWNED


def test_folder_rules_and_download_policy(data, tmp_path):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    folder = tmp_path / "recordings"
    folder.mkdir()
    f = folder / "ep1.mp4"
    f.write_bytes(b"x")
    rights.add_rule("folder", str(folder), rights.OWNED, "My podcast recordings")
    src = {"id": "s", "platform": "local", "local_path": str(f)}
    assert rights.evaluate(src)["status"] == rights.OWNED and rights.download_allowed(src, {})[0]
    yt = {"id": "y", "platform": "youtube", "url": "https://www.youtube.com/watch?v=abc"}
    ok, why = rights.download_allowed(yt, {"rights_allow_remote_download": False})
    assert not ok and "YouTube Studio" in why
    assert rights.download_allowed(yt, {"rights_allow_remote_download": True})[0]
    assert rights.download_allowed({"url": "https://cdn.example.com/licensed.mp4"}, {})[0]


# ------------------------------------------------------------------ quota
def test_quota_budgets_share_reserve_and_exhaustion(data):
    from clipfoundry.autopilot import quota

    s = {"youtube_quota_default": 300, "youtube_quota_uploads": 5, "youtube_quota_search": 10,
         "youtube_discovery_share": 40, "youtube_search_discovery_share": 50}
    for _ in range(5):
        quota.charge("search.list", "discovery", s)
    with pytest.raises(quota.QuotaDenied, match="share"):
        quota.check("search.list", "discovery", s)
    quota.check("videos.insert", "publish", s)  # publishing is unaffected by discovery's share
    for _ in range(120):
        quota.charge("videos.list", "discovery", s)
    with pytest.raises(quota.QuotaDenied):
        quota.check("videos.list", "discovery", s)  # 40% of 300
    quota.check("videos.list", "stats", s)
    st = quota.status(s)
    assert st["buckets"]["search"]["discovery_used"] == 5 and st["buckets"]["default"]["used"] == 120
    assert st["discovery_paused"]  # both shares used: polling stops until the reset
    quota.mark_exhausted("videos.insert", "quotaExceeded")
    with pytest.raises(quota.QuotaDenied, match="YouTube reported"):
        quota.check("videos.insert", "publish", s)  # YouTube's answer wins over our own count
    assert quota.next_reset() > time.time()


def test_quota_cache_deduplicates(data):
    from clipfoundry.autopilot import quota

    calls = []
    for _ in range(3):
        quota.cached(["x", {"a": 1}], 60, lambda: calls.append(1) or {"ok": True}, "videos.list")
    assert len(calls) == 1 and quota.status({})["cache"]["cache_hits"] == 2


# ------------------------------------------------------------------ Trend Scout + Source Scout end to end
def test_trend_and_source_scout(google, data, tmp_path, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import quota, rights, state

    g = google
    g.add_video("pod1", "The podcast moment everyone is talking about", "UCpod0000000000001", views=400_000,
                age_hours=8, duration="PT1H40M", category="22")
    g.add_video("ufc1", "UFC press conference full", "UCufc0000000000001", views=900_000, age_hours=20,
                duration="PT45M", category="17")
    g.add_video("short1", "podcast short clip", "UCsh00000000000001", views=50_000, duration="PT40S")
    g.add_video("kids1", "podcast for kids", "UCkid0000000000001", made_for_kids=True)
    g.add_video("cc1", "gaming podcast creative commons", "UCcc00000000000001", license_="creativeCommon",
                duration="PT30M", category="20")
    g.add_video("live1", "Live now", "UClive000000000001", live_viewers=12_000, duration="P0D")
    g.popular = ["ufc1", "pod1"]
    rights.add_rule("channel", "UCpod0000000000001", rights.ALLOWLISTED, "Creator's clipping program",
                    platform="youtube")
    folder = tmp_path / "recordings"
    folder.mkdir()
    rec = folder / "my_episode.mp4"
    rec.write_bytes(os.urandom(1000))
    old = time.time() - 600
    os.utime(rec, (old, old))
    from clipfoundry.autopilot import providers

    feed = providers.add_feed("watch_folder", "My recordings", {"path": str(folder)}, "OWNED", "My own recordings")
    rights.add_rule("folder", str(folder), rights.OWNED, "My own recordings")

    out = run("trend_scan")
    assert out["signals"] >= 6
    sigs = {s["external_id"]: s for s in db.select("trend_signals")}
    assert sigs["ufc1"]["platform_rank"] == 1 and sigs["ufc1"]["score_mode"] == "platform_order"
    assert sigs["live1"]["kind"] == "live" and sigs["live1"]["metrics"]["live_viewers"]["value"] == 12000
    assert sigs["pod1"]["metrics"]["views"]["status"] == "observed"
    provs = state.get("providers")
    assert provs["youtube"]["status"] == "ok" and provs["google_trends"]["status"] == "unavailable"
    assert provs["tiktok_trends"]["status"] == "unavailable" and provs[f"feed:{feed['id']}"]["status"] == "ok"
    usage = quota.usage()
    assert usage["search"]["by_purpose"]["discovery"] >= 3 and usage["default"]["units"] >= 2

    db.save_settings({"autopilot_sources_per_day": 2})
    run("source_scout")
    src = {s["external_id"]: s for s in db.select("sources")}
    assert "short1" in src and src["short1"]["status"] == "skipped" and "short" in src["short1"]["status_note"]
    assert src["kids1"]["status"] == "skipped"
    assert src["ufc1"]["rights_status"] == rights.MANUAL and src["ufc1"]["status"] == "needs_rights"
    assert src["cc1"]["rights_status"] == rights.CC
    assert src["pod1"]["rights_status"] == rights.ALLOWLISTED
    assert src["pod1"]["status"] == "needs_file"  # authorized, but downloading from YouTube is off by default
    local = next(s for s in src.values() if s["platform"] == "local")
    assert local["rights_status"] == rights.OWNED and local["status"] == "queued" and local["selected_day"]
    keys = {a["key"] for a in state.open_actions()}
    # By default nothing is asked: videos nothing covers, and a covered video whose file cannot be obtained, are
    # skipped (the activity log says why) and the next best video is tried.
    assert not [k for k in keys if k.startswith(("rights:", "file:"))]
    assert "YouTube does not allow downloading" in src["pod1"]["status_note"]
    # With "Ask me about strong videos nothing covers" on: today is one source short (2 per day, 1 queued), so there
    # is exactly one rights question, about the strongest video that needs it (not the YouTube live stream: without
    # the download setting a yes could not be used).
    db.save_settings({"rights_ask_per_video": True})
    run("source_scout")
    keys = {a["key"] for a in state.open_actions()}
    asked = sorted(k for k in keys if k.startswith("rights:"))
    strongest = max((s for s in src.values() if s["status"] == "needs_rights" and s["kind"] != "live"),
                    key=lambda s: s["source_score"])
    assert asked == [f"rights:{strongest['id']}"] and not [k for k in keys if k.startswith("file:")]
    from clipfoundry.autopilot import queue

    hunts = queue.jobs(worker="clip_hunter")
    assert [j["ref_id"] for j in hunts] == [local["id"]]
    # Dismissed questions are not asked again by the next scout run.
    from clipfoundry.autopilot import scout

    state.dismiss(asked[0])
    run("source_scout")
    assert asked[0] not in {a["key"] for a in state.open_actions()}
    monkeypatch.setattr(scout, "RIGHTS_QUESTIONS", 0)
    run("source_scout")
    assert not [a for a in state.open_actions() if a["key"].startswith("rights:")]


def test_search_quota_exhaustion_stops_discovery_honestly(google, data):
    from clipfoundry.autopilot import quota, state

    google.add_video("a1", "podcast one")
    google.search_quota_exceeded = True
    run("trend_scan")
    assert quota.exhausted("search")
    st = quota.status({})
    assert st["buckets"]["search"]["exhausted"] and any("used up" in w for w in st["warnings"])
    assert google.calls.get("/youtube/v3/search", 0) == 1  # did not keep hammering after the refusal
    assert any(a["kind"] == "quota" for a in state.open_actions())


def test_discovery_without_credentials_is_reported(data):
    from clipfoundry.autopilot import state

    run("trend_scan")
    yt = state.get("providers")["youtube"]
    assert yt["status"] == "not_configured" and "API key" in yt["fix"]


# ------------------------------------------------------------------ retention
def test_youtube_data_is_deleted_after_30_days(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scout

    now = time.time()
    old = now - 31 * 86400
    sig = db.insert("trend_signals", {"provider": "youtube_search", "platform": "youtube", "external_id": "old",
                                      "first_seen": old, "last_checked": old})
    db.insert("trend_signals", {"provider": "watch_folder", "platform": "local", "external_id": "mine",
                                "first_seen": old, "last_checked": old})
    db.execute("INSERT INTO trend_history (signal_id, at, views) VALUES (?, ?, 5)", (sig["id"], old))
    db.execute("INSERT INTO performance (id, publication_id, platform, fetched_at, views) VALUES "
               "('p1', 'pub', 'youtube', ?, 10), ('p2', 'pub', 'youtube', ?, 12), ('p3', 'pub', 'tiktok', ?, 3)",
               (old, now, old))
    out = scout.youtube_retention(now=now)
    assert out["youtube_signals_deleted"] == 1 and out["youtube_snapshots_deleted"] == 1
    assert [s["external_id"] for s in db.select("trend_signals")] == ["mine"]
    assert {r["id"] for r in db.select("performance")} == {"p2", "p3"}
    # Google's storage approval covers only the statistics of the connected user's own videos; public data about
    # other videos is still deleted after 30 days.
    db.save_settings({"youtube_derived_metrics_approved": True})
    db.execute("INSERT INTO performance (id, publication_id, platform, fetched_at, views) VALUES "
               "('p4', 'pub', 'youtube', ?, 9)", (old,))
    sig = db.insert("trend_signals", {"provider": "youtube_search", "platform": "youtube", "external_id": "old2",
                                      "first_seen": old, "last_checked": old})
    out = scout.youtube_retention(now=now)  # no connected account: nothing is authorized any more
    assert out["youtube_snapshots_deleted"] == 1 and out["youtube_signals_deleted"] == 1
    db.execute("INSERT INTO performance (id, publication_id, platform, fetched_at, views) VALUES "
               "('p5', 'pub', 'youtube', ?, 9)", (old,))
    db.insert("trend_signals", {"provider": "youtube_search", "platform": "youtube", "external_id": "old3",
                                "first_seen": old, "last_checked": old})
    db.save_account("youtube", {"access_token": "t"}, display_name="Me")
    out = scout.youtube_retention(now=now)
    assert out["own_statistics"] == "kept (storage approved)" and out["youtube_snapshots_deleted"] == 0
    assert out["youtube_signals_deleted"] == 1
    assert "p5" in {r["id"] for r in db.select("performance")}


def test_youtube_data_is_deleted_at_start_even_when_autopilot_is_off(data):
    # The hourly maintenance only runs while Autopilot is on; YouTube's 30-day rule holds either way.
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    old = time.time() - 31 * 86400
    db.insert("trend_signals", {"provider": "youtube_search", "platform": "youtube", "external_id": "old",
                                "first_seen": old, "last_checked": old})
    assert not db.get_settings()["autopilot_enabled"]
    with TestClient(app, base_url="http://127.0.0.1:8765"):
        assert db.select("trend_signals") == []


# ------------------------------------------------------------------ API
def test_autopilot_api(data, tmp_path):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    folder = tmp_path / "rec"
    folder.mkdir()
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        assert c.post("/api/autopilot/rights", json={"scope": "channel", "value": "UCx", "status": "LICENSED"}
                      ).status_code == 403  # state changes only from ClipFoundry's page
        bad = c.post("/api/autopilot/rights", headers=H, json={"scope": "channel", "value": "UCx",
                                                                  "status": "LICENSED"})
        assert bad.status_code == 400 and "license" in bad.json()["detail"]
        ok = c.post("/api/autopilot/rights", headers=H, json={"scope": "channel", "value": "UCx",
                                                                 "status": "LICENSED", "basis": "Contract #12"})
        assert ok.status_code == 200
        feed = c.post("/api/autopilot/feeds", headers=H, json={"kind": "watch_folder", "name": "Rec",
                                                                  "config": {"path": str(folder)},
                                                                  "rights_status": "OWNED", "rights_basis": "mine"})
        assert feed.status_code == 200
        rules = c.get("/api/autopilot/rights").json()["rules"]
        assert {r["scope"] for r in rules} == {"channel", "folder"}
        assert c.get("/api/autopilot/quota").json()["buckets"]["search"]["budget"] == 100
        assert len(c.get("/api/autopilot/workers").json()["workers"]) == 12
        stop = c.post("/api/autopilot/stop-all", headers=H).json()
        assert stop["paused"] and stop["canceled"] >= 1  # the queued rights check and feed scan
        assert c.get("/api/autopilot/workers").json()["paused"]
        assert c.post("/api/autopilot/resume", headers=H).json() == {"paused": False}


def test_legal_pages_are_served(data):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        for path, text in [("/legal/terms", "Terms of Service"), ("/legal/privacy", "Privacy Policy"),
                           ("/legal/privacy.html", "YouTube API Services"), ("/legal/", "Turn long videos into")]:
            r = c.get(path)
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and text in r.text
            assert 'href="site.css"' in r.text
        css = c.get("/legal/site.css")
        assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
        assert c.get("/legal", follow_redirects=False).headers["location"] == "/legal/"
        assert c.get("/legal/x").status_code == 404


def test_the_website_is_ready_to_publish():
    """docs/legal is published as the public website: only these files, no placeholders, nothing loaded from other
    sites, and the Privacy Policy and Terms linked at the top of every page (TikTok wants them visible without a
    menu)."""
    import re

    from clipfoundry.api import LEGAL_DIR

    assert sorted(p.name for p in LEGAL_DIR.iterdir()) == ["index.html", "privacy.html", "site.css", "terms.html"]
    for page in ("index.html", "privacy.html", "terms.html"):
        html = (LEGAL_DIR / page).read_text(encoding="utf-8")
        assert not re.search(r"\{\{|\[[A-Z][A-Z ]+\]", html), f"{page}: unresolved placeholder"
        assert not re.search(r"<script|<form|<iframe|<img|@import", html, re.I), page
        assert re.findall(r'<link rel="stylesheet" href="([^"]+)"', html) == ["site.css"], page
        header = html.split("<main", 1)[0]
        assert 'href="privacy.html"' in header and 'href="terms.html"' in header, page
        assert "landryschreiner456@gmail.com" in html and "Landry Schreiner" in html, page
    assert "url(" not in (LEGAL_DIR / "site.css").read_text(encoding="utf-8")

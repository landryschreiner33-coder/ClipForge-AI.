"""Real performance data: stored exactly as the platform APIs report it, never estimated."""
from __future__ import annotations

import csv
import io
import os
import time
from urllib.parse import parse_qs, urlparse

import pytest

from fake_platforms import FakeGoogle, FakeTikTok

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def fakes(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry.publish import jobs, tiktok, youtube

    g, t = FakeGoogle(), FakeTikTok()
    for name, value in {"AUTH_URL": f"{g.url}/o/oauth2/v2/auth", "TOKEN_URL": f"{g.url}/token",
                        "REVOKE_URL": f"{g.url}/revoke", "API_URL": f"{g.url}/youtube/v3",
                        "UPLOAD_URL": f"{g.url}/upload/youtube/v3/videos", "ANALYTICS_URL": f"{g.url}/v2/reports",
                        "CHUNK": 256 * 1024}.items():
        monkeypatch.setattr(youtube, name, value)
    monkeypatch.setattr(tiktok, "AUTH_URL", f"{t.url}/v2/auth/authorize/")
    monkeypatch.setattr(tiktok, "API_URL", f"{t.url}/v2")
    monkeypatch.setattr(tiktok, "POLL_SECONDS", 0.01)
    jobs.worker.cancelled.clear()
    yield g, t
    g.stop()
    t.stop()


@pytest.fixture()
def client(fakes, tmp_path):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        video = tmp_path / "clip.mp4"
        video.write_bytes(os.urandom(300_000))
        project = db.create_project("talk", source_path=str(tmp_path / "s.mp4"), status="ready")
        c.clip = db.create_clip(project["id"], start=0, end=20, title="t", status="ready", output_path=str(video),
                                duration=20.0, score=77.0, analysis={"subscores": {"hook": 70, "retention": 60,
                                                                                  "context": 80, "engagement": 50}})
        c.put("/api/settings", json={"youtube_client_id": "cid.apps.googleusercontent.com",
                                     "youtube_client_secret": "csecret", "tiktok_client_key": "tkkey",
                                     "tiktok_client_secret": "tksecret", "tiktok_app_audited": True})
        yield c


def _connect(c, fake, platform: str) -> None:
    auth = c.post(f"/api/publish/{platform}/connect", headers=H).json()["auth_url"]
    state = parse_qs(urlparse(auth).query)["state"][0]
    page = c.get(f"/api/oauth/{platform}/callback", params={"state": state, "code": fake.approve(auth)})
    assert "connected" in page.text


def _wait(c, pub_id: str) -> dict:
    for _ in range(400):
        p = c.get(f"/api/publications/{pub_id}").json()
        if p["status"] in ("done", "action_needed", "failed"):
            return p
        time.sleep(0.05)
    raise AssertionError(p)


def _youtube_pub(c, g) -> dict:
    _connect(c, g, "youtube")
    r = c.post(f"/api/clips/{c.clip['id']}/publish/youtube", headers=H, json={
        "title": "t", "description": "d", "tags": [], "privacy": "private", "made_for_kids": False, "confirm": True})
    return _wait(c, r.json()["id"])


def _tiktok_pub(c, t, privacy: str = "PUBLIC_TO_EVERYONE", mode: str = "direct") -> dict:
    _connect(c, t, "tiktok")
    r = c.post(f"/api/clips/{c.clip['id']}/publish/tiktok", headers=H, json={
        "description": "caption", "privacy": privacy if mode == "direct" else "", "mode": mode, "confirm": True})
    return _wait(c, r.json()["id"])


def test_youtube_numbers_are_stored_exactly_as_reported(client, fakes):
    g, _ = fakes
    pub = _youtube_pub(client, g)
    g.videos[pub["remote_id"]]["statistics"] = {"viewCount": "1234", "likeCount": "56", "commentCount": "7"}
    g.analytics = {"views": 1200, "likes": 55, "comments": 7, "shares": 9, "estimatedMinutesWatched": 311.5,
                   "averageViewDuration": 15.2, "averageViewPercentage": 71.3}
    p = client.post(f"/api/publications/{pub['id']}/stats", headers=H).json()
    s = p["stats"]
    assert (s["views"], s["likes"], s["comments"], s["shares"]) == (1234, 56, 7, 9)  # views from the Data API
    assert (s["watch_time_minutes"], s["avg_view_duration_s"], s["avg_view_percentage"]) == (311.5, 15.2, 71.3)
    assert "Analytics" in s["source"] and any("2-3 days" in n for n in s["notes"])
    assert s["raw"]["statistics"]["viewCount"] == "1234"
    g.videos[pub["remote_id"]]["statistics"]["viewCount"] = "2000"
    client.post(f"/api/publications/{pub['id']}/stats", headers=H)
    history = client.get(f"/api/publications/{pub['id']}/stats").json()
    assert [h["views"] for h in history] == [2000, 1234]  # snapshots over time, newest first


def test_missing_numbers_stay_empty(client, fakes):
    g, _ = fakes
    pub = _youtube_pub(client, g)
    g.videos[pub["remote_id"]]["statistics"] = {"viewCount": "10", "commentCount": "0"}  # likes hidden by the owner
    s = client.post(f"/api/publications/{pub['id']}/stats", headers=H).json()["stats"]
    assert s["views"] == 10 and s["comments"] == 0 and s["likes"] is None
    assert s["shares"] is None and s["watch_time_minutes"] is None  # Analytics has no data yet
    assert any("no data for this video yet" in n for n in s["notes"])
    g.analytics_disabled = True
    s = client.post(f"/api/publications/{pub['id']}/stats", headers=H).json()["stats"]
    assert s["views"] == 10 and s["watch_time_minutes"] is None
    assert any("Enable the YouTube Analytics API" in n for n in s["notes"])


def test_youtube_without_analytics_permission(client, fakes):
    g, _ = fakes
    g.scope = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
    pub = _youtube_pub(client, g)
    g.videos[pub["remote_id"]]["statistics"] = {"viewCount": "5", "likeCount": "1", "commentCount": "0"}
    g.analytics = {"shares": 3}
    s = client.post(f"/api/publications/{pub['id']}/stats", headers=H).json()["stats"]
    assert s["views"] == 5 and s["shares"] is None and "Analytics" not in s["source"]
    assert any("allow analytics access" in n for n in s["notes"])


def test_tiktok_public_post_stats(client, fakes):
    _, t = fakes
    pub = _tiktok_pub(client, t)
    t.stats["7300000000000000001"] = {"view_count": 900, "like_count": 80, "comment_count": 5, "share_count": 4}
    s = client.post(f"/api/publications/{pub['id']}/stats", headers=H).json()["stats"]
    assert (s["views"], s["likes"], s["comments"], s["shares"]) == (900, 80, 5, 4)
    assert s["watch_time_minutes"] is None and any("does not report watch time" in n for n in s["notes"])


def test_tiktok_inbox_draft_is_linked_after_posting_in_the_app(client, fakes):
    _, t = fakes
    pub = _tiktok_pub(client, t, mode="inbox")
    assert pub["status"] == "action_needed"
    s = client.post(f"/api/publications/{pub['id']}/stats", headers=H).json()["stats"]
    assert s["views"] is None and any("link the post with its URL" in n for n in s["notes"])
    bad = client.post(f"/api/publications/{pub['id']}/link", headers=H, json={"url": "https://example.com/x"})
    assert bad.status_code == 400
    t.stats["7311111111111111111"] = {"view_count": 42, "like_count": 3, "comment_count": 1, "share_count": 0}
    p = client.post(f"/api/publications/{pub['id']}/link", headers=H,
                    json={"url": "https://www.tiktok.com/@testcreator/video/7311111111111111111?is_from_webapp=1"}).json()
    assert p["stats"]["views"] == 42 and p["info"]["post_ids"] == ["7311111111111111111"] and p["url"]
    p = client.post(f"/api/publications/{pub['id']}/link", headers=H, json={"url": "7399999999999999999"}).json()
    assert p["stats"]["views"] is None and any("did not return this video" in n for n in p["stats"]["notes"])


def test_overview_totals_and_dataset_only_use_real_numbers(client, fakes):
    g, t = fakes
    yt = _youtube_pub(client, g)
    g.videos[yt["remote_id"]]["statistics"] = {"viewCount": "100", "commentCount": "2"}
    tt = _tiktok_pub(client, t)
    t.stats["7300000000000000001"] = {"view_count": 50, "like_count": 5, "comment_count": 1, "share_count": 2}
    assert client.post("/api/performance/refresh", headers=H).json() == {"refreshed": 2, "failed": []}
    ov = client.get("/api/performance").json()
    assert ov["published"] == 2 and ov["with_stats"] == 2
    assert ov["totals"]["views"] == {"total": 150, "publications": 2}
    assert ov["totals"]["likes"] == {"total": 5, "publications": 1}  # YouTube hid its likes: not counted as 0
    assert ov["totals"]["watch_time_minutes"] == {"total": None, "publications": 0}
    assert ov["check"]["samples"] == 2 and ov["check"]["spearman"] is None  # not enough data to say anything
    rows = list(csv.DictReader(io.StringIO(client.get("/api/performance/dataset").text.lstrip("﻿"))))
    assert {r["platform"] for r in rows} == {"youtube", "tiktok"}
    yt_row = next(r for r in rows if r["platform"] == "youtube")
    assert yt_row["views"] == "100" and yt_row["likes"] == "" and yt_row["viral_potential"] == "77.0"
    assert yt_row["hook"] == "70"
    assert client.get("/api/performance/dataset?format=json").json()[0]["publication_id"] in (yt["id"], tt["id"])


def test_ranking_check_needs_enough_samples():
    from clipfoundry import learning

    rows = [{"viral_potential": vp, "views": v, "platform": "youtube"}
            for vp, v in [(90, 5000), (85, 3000), (80, 4000), (70, 900), (65, 800), (60, 1000), (55, 300),
                          (50, 200), (45, 250), (40, 100)]]
    assert learning.ranking_check(rows[:9])["spearman"] is None
    check = learning.ranking_check(rows)
    assert check["samples"] == 10 and 0.8 < check["spearman"] <= 1.0
    assert learning.ranking_check(rows, platform="tiktok")["samples"] == 0
    assert learning.spearman([1, 1, 1], [1, 2, 3]) is None

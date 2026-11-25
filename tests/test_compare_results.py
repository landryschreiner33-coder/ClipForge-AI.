"""Results compared by channel, niche, format and clip length (autopilot/compare.py): one platform and audience at a
time, every post read at 48 hours, "too few posts" and "no clear difference yet" instead of guesses, comparable
periods, YouTube only with Google's approval for derived metrics, and a test to run next instead of a promise. All
posts here are synthetic and live in a temporary test database."""
from __future__ import annotations

import time

import pytest

H = {"X-ClipFoundry": "1"}
DAY = 86400


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def account(platform: str, external_id: str, name: str) -> str:
    from clipfoundry import db

    conn, _ = db.upsert_connection(platform, external_id, {"access_token": "x"}, display_name=name)
    return conn["id"]


def post(platform: str, views: float | None, *, layout: str = "split", topic: str = "gaming", duration: float = 30,
         days_ago: float = 5, connection: str = "", intent: str = "SELECTED_AUDIENCE", pct: float | None = None,
         read_after_h: float = 49) -> dict:
    from clipfoundry import db

    src = db.insert("sources", {"platform": "local", "external_id": f"s{time.time_ns()}", "topic": topic})
    project = db.create_project("p", status="ready", origin="autopilot", source_id=src["id"])
    clip = db.create_clip(project["id"], start=0, end=duration, title="t", status="ready", duration=duration,
                          render_info={"layout": layout})
    pub = db.create_publication(clip["id"], platform, status="done", remote_id=f"v{time.time_ns()}",
                                connection_id=connection or None,
                                audience={"intent": intent, "group_version": 1, "policy_version": 1})
    made = time.time() - days_ago * DAY
    db.execute("UPDATE publications SET created_at = ? WHERE id = ?", (made, pub["id"]))
    if views is not None:
        db.execute("INSERT INTO performance (id, publication_id, clip_id, platform, fetched_at, views, "
                   "avg_view_percentage) VALUES (?,?,?,?,?,?,?)",
                   (db.new_id(), pub["id"], clip["id"], platform, made + read_after_h * 3600, views, pct))
    return db.get_publication(pub["id"])


def place(result: dict, platform: str, cohort: str = "selected") -> dict:
    return next(p for p in result["places"] if p["platform"] == platform and p["cohort"] == cohort)


def group(pl: dict, name: str) -> dict:
    return next(g for g in pl["groups"] if g["group"] == name)


def test_a_clear_difference_needs_enough_posts_and_a_real_gap(data):
    from clipfoundry.autopilot import compare

    for k in range(8):
        post("tiktok", 900 + 40 * k, layout="pip")
        post("tiktok", 100 + 10 * k, layout="split")
    out = compare.compare("format")
    tt = place(out, "tiktok")
    pip, split = group(tt, "Picture-in-picture"), group(tt, "Gameplay + Facecam")
    assert pip["verdict"] == "higher" and split["verdict"] == "lower"
    assert pip["posts"] == 8 and pip["others"] == 8 and pip["p"] < compare.CLEAR_P
    assert pip["median_views"] == pytest.approx(1040) and "Higher so far" in pip["text"]
    assert "6 of your next 10" in pip["test"]
    # TikTok does not report average % viewed here: it says so instead of estimating
    assert pip["median_pct"] is None and not pip["pct_reported"] and "did not report" in tt["note"]
    assert "Not a promise of views" in out["note"]


def test_overlapping_posts_are_no_clear_difference_and_few_posts_are_too_few(data):
    from clipfoundry.autopilot import compare

    for k in range(6):
        post("tiktok", [100, 400, 150, 380, 220, 300][k], layout="pip", pct=40)
        post("tiktok", [120, 390, 160, 350, 240, 310][k], layout="split", pct=42)
    post("tiktok", 5000, layout="game")
    tt = place(compare.compare("format"), "tiktok")
    assert group(tt, "Picture-in-picture")["verdict"] == "inconclusive"
    assert "Alternate" in group(tt, "Picture-in-picture")["test"]
    game = group(tt, "Gameplay only")
    assert game["verdict"] == "too_few" and "Post 4 more Gameplay only clips" in game["test"]
    assert group(tt, "Gameplay + Facecam")["median_pct"] == pytest.approx(42)


def test_only_posts_read_at_48_hours_count_and_audiences_never_mix(data):
    from clipfoundry.autopilot import compare

    post("tiktok", 100, read_after_h=20)          # too young when read: not counted
    post("tiktok", None)                         # no reading at all
    post("tiktok", 300)                          # selected viewers
    post("tiktok", 9999, intent="OWNER_ONLY")    # only you: never compared
    post("tiktok", 50, intent="LEGACY_PUBLIC")   # an older public post: its own audience
    out = compare.compare("format")
    assert out["counted"] == 3
    assert {(p["platform"], p["cohort"]) for p in out["places"]} == {("tiktok", "selected"),
                                                                     ("tiktok", "public_legacy")}
    assert place(out, "tiktok")["posts"] == 1
    only = place(out, "tiktok")["groups"][0]
    assert only["verdict"] == "only_one" and "nothing to compare" in only["text"]


def test_youtube_waits_for_googles_approval(data):
    from clipfoundry import db, learning
    from clipfoundry.autopilot import compare

    for k in range(6):
        post("youtube", 500 + k, layout="pip")
        post("youtube", 50 + k, layout="split")
    yt = place(compare.compare("format"), "youtube")
    assert yt["available"] is False and yt["groups"] == [] and yt["note"] == learning.YOUTUBE_NOTE
    db.save_settings({"youtube_derived_metrics_approved": True})
    yt = place(compare.compare("format"), "youtube")
    assert yt["available"] and group(yt, "Picture-in-picture")["verdict"] == "higher"


def test_channels_niches_and_lengths(data):
    from clipfoundry.autopilot import compare

    main, second = account("tiktok", "a1", "Main channel"), account("tiktok", "a2", "Clips channel")
    for k in range(5):
        post("tiktok", 800 + k, connection=main, topic="Speedruns", duration=18)
        post("tiktok", 90 + k, connection=second, topic="Cooking", duration=40)
    tt = place(compare.compare("channel"), "tiktok")
    assert group(tt, "Main channel")["verdict"] == "higher" and group(tt, "Clips channel")["verdict"] == "lower"
    tt = place(compare.compare("niche"), "tiktok")
    assert {g["group"] for g in tt["groups"]} == {"speedruns", "cooking"}
    tt = place(compare.compare("length"), "tiktok")
    assert {g["group"] for g in tt["groups"]} == {"<20 s", "35-50 s"}
    with pytest.raises(ValueError):
        compare.compare("mood")


def test_comparable_periods(data):
    from clipfoundry.autopilot import compare

    for k in range(6):
        post("tiktok", 600 + k, days_ago=5 + k)      # the last 28 days
        post("tiktok", 60 + k, days_ago=35 + k)      # the 28 days before
        post("tiktok", 9000, days_ago=70 + k)        # older: in neither period
    periods = place(compare.compare("format"), "tiktok")["periods"]
    assert periods["recent"]["posts"] == 6 and periods["before"]["posts"] == 6
    assert periods["verdict"] == "higher" and "28 days" in periods["text"]


def test_compare_route_is_local_only(data):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    client = TestClient(app)
    for k in range(2):
        post("tiktok", 100 + k)
    r = client.get("/api/performance/compare?by=channel", headers=H)
    assert r.status_code == 200 and r.json()["by"] == "channel"
    assert client.get("/api/performance/compare?by=mood", headers=H).status_code == 400
    far = TestClient(app, base_url="http://192.168.1.20:8000")
    assert far.get("/api/performance/compare", headers=H).status_code in (403, 404)

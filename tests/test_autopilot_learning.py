"""Learning Worker: real results only, enough posts before concluding, shrinkage, and what it feeds back."""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

import pytest

CHI = ZoneInfo("America/Chicago")


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_learning": True})
    return tmp_path


def post(platform: str, hour: int, views: int, clip_score: float = 60, style: str = "curiosity",
         pct: float | None = None, retention: float | None = None, days_ago: int = 3, topic: str = "podcast") -> dict:
    from clipfoundry import db

    when = dt.datetime.combine(dt.datetime.now(CHI).date() - dt.timedelta(days=days_ago), dt.time(hour, 0),
                               CHI).timestamp()
    src = db.insert("sources", {"platform": "local", "external_id": f"s{time.time_ns()}", "topic": topic})
    project = db.create_project("p", status="ready", origin="autopilot", source_id=src["id"])
    clip = db.create_clip(project["id"], start=0, end=30, title="t", status="ready", duration=30.0,
                          caption_text="Why do most people quit? Because they start too fast.", score=clip_score)
    db.insert("clip_scores", {"clip_id": clip["id"], "clip": clip_score, "retention": retention}, key="clip_id")
    meta = db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": platform, "style": style,
                                             "title": "t", "selected": 1})
    item = db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": platform, "planned_at": when,
                                                "status": "published", "metadata_id": meta["id"]})
    pub = db.create_publication(clip["id"], platform, status="done", scheduled_id=item["id"],
                                features={"viral_potential": clip_score, "duration": 30.0})
    db.execute("UPDATE publications SET created_at = ? WHERE id = ?", (when, pub["id"]))
    db.execute("INSERT INTO performance (id, publication_id, clip_id, platform, fetched_at, views, avg_view_percentage) "
               "VALUES (?,?,?,?,?,?,?)", (db.new_id(), pub["id"], clip["id"], platform, when + 47 * 3600, views, pct))
    return pub


def run_learn() -> dict:
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    row = queue.enqueue("learn", {})
    return host.HANDLERS["learn"](host.Job(queue.get(row["id"]), "test"))


def test_nothing_is_concluded_from_too_few_posts(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import learner, state
    from clipfoundry.publish import stats

    monkeypatch.setattr(stats, "refresh", lambda pub: None)
    for k in range(5):
        post("tiktok", 19, 1000 * (k + 1))
    for k in range(8):
        post("youtube", 12, 500)
    out = run_learn()
    st = state.get("learning:status")
    assert st["samples"] == 5 and st["excluded_youtube"] == 8 and "Developer Policies" in st["note"]
    assert "Not enough results yet: 5 of 10" in out["message"]
    assert not db.select("learning_metrics") and learner.lift("hour", "19", "tiktok") == (1.0, 0)


def test_learns_posting_times_styles_and_weights(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import learner, scheduler, state
    from clipfoundry.publish import stats

    monkeypatch.setattr(stats, "refresh", lambda pub: None)
    for k in range(6):  # evenings do much better on this account; higher clip scores did better too
        post("tiktok", 19, 20000 + 1000 * k, clip_score=70 + k, style="debate")
        post("tiktok", 10, 800 + 50 * k, clip_score=50 + k, style="direct")
    post("tiktok", 3, 900000, clip_score=40)  # one lucky post at 3 am
    run_learn()
    evening, n = learner.lift("hour", "19", "tiktok")
    assert evening > 1.2 and n == 6
    assert learner.lift("hour", "3", "tiktok") == (1.0, 0)  # a single post is not a rule
    assert learner.lift("style", "debate", "tiktok")[0] > learner.lift("style", "direct", "tiktok")[0]
    w = learner.weights()
    assert w["clip"] > scheduler.FINAL_WEIGHTS["clip"]  # the clip score ordered these results well
    value, why = scheduler.final_score({"clip": 80, "packaging": 60}, w)
    assert any("your own results" in line for line in why)
    timing = scheduler.Timing("tiktok", db.get_settings())
    at7pm = dt.datetime.combine(dt.date.today(), dt.time(19, 0), CHI)
    at10am = dt.datetime.combine(dt.date.today(), dt.time(10, 0), CHI)
    assert timing.quality(at7pm)[0] > timing.quality(at10am)[0]
    st = state.get("learning:status")
    assert st["samples"] == 13 and any("19:00" in f for f in st["findings"])
    from clipfoundry.autopilot import packaging

    meta = {"title": "Here's the biggest mistake most people make", "caption": "Here's the biggest mistake",
            "hashtags": ["#a", "#b"], "style": "debate"}
    scored = packaging.score(meta, "tiktok", "Here's the biggest mistake most people make", [], [], [], [])
    assert scored["note"].endswith("posts in this style") and scored["components"]["your_results"] > 1


def test_retention_calibration_and_youtube_with_approval(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import learner
    from clipfoundry.publish import stats

    monkeypatch.setattr(stats, "refresh", lambda pub: None)
    db.save_settings({"youtube_derived_metrics_approved": True})
    for k in range(12):
        post("youtube", 12 + k % 5, 1000 + 100 * k, retention=40 + 4 * k, pct=30 + 3 * k)
    run_learn()
    est, note = learner.expected_retention(60)
    assert est == pytest.approx(45, abs=1.5) and "12 of your posts" in note


def test_stats_refresh_cadence(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import learner
    from clipfoundry.publish import stats

    calls = []
    monkeypatch.setattr(stats, "refresh", lambda pub: calls.append(pub["id"]))
    fresh = post("tiktok", 19, 100, days_ago=0)
    old = post("tiktok", 19, 100, days_ago=40)
    db.execute("UPDATE publications SET created_at = ? WHERE id = ?", (time.time() - 3600, fresh["id"]))
    db.execute("DELETE FROM performance WHERE publication_id = ?", (fresh["id"],))
    out = learner.refresh_due(db.get_settings())
    assert calls == [fresh["id"]] and out["refreshed"] == 1  # posts older than 30 days are left alone
    db.execute("INSERT INTO performance (id, publication_id, platform, fetched_at, views) VALUES (?,?,?,?,?)",
               ("x", fresh["id"], "tiktok", time.time() - 600, 5))
    calls.clear()
    learner.refresh_due(db.get_settings())
    assert calls == []  # read 10 minutes ago: not due yet (every 6 hours while new)
    assert old["id"] not in calls

"""Smart Scheduler: slots, limits, learned timing, approvals, due processing and dynamic replacement."""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

import pytest
from quality_stub import passed_report

CHI = ZoneInfo("America/Chicago")


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_tiktok": False,
                      "autopilot_active_start": 9, "autopilot_active_end": 21, "autopilot_min_gap_minutes": 60,
                      "autopilot_youtube_daily_limit": 3, "autopilot_daily_target": 15})
    return tmp_path


def _at(hour: int, minute: int = 0, days: int = 0) -> float:
    base = dt.datetime.now(CHI).date() + dt.timedelta(days=days)
    return dt.datetime.combine(base, dt.time(hour, minute), CHI).timestamp()


def make_clip(tmp, title: str, clip_score: float, packaging: float = 60.0, text: str = "", platform: str = "youtube",
              source: dict | None = None) -> dict:
    from clipfoundry import db
    from clipfoundry.pipeline import fingerprint

    video = tmp / f"{title[:10].replace(' ', '_')}-{time.time_ns()}.mp4"
    video.write_bytes(b"video")
    project = db.create_project(title, status="ready", origin="autopilot", source_id=(source or {}).get("id", ""))
    clip = db.create_clip(project["id"], start=0, end=30, title=title, status="ready", output_path=str(video),
                          duration=30.0, caption_text=text or title, score=clip_score)
    db.insert("clip_scores", {"clip_id": clip["id"], "clip": clip_score, "diversity": 80.0, "retention": 60.0},
              key="clip_id")
    db.insert("clip_fingerprints", {"clip_id": clip["id"], "text_sig": fingerprint.text_signature(text or title),
                                    "phash": [], "title_norm": title.lower()}, key="clip_id")
    for p in (platform,) if platform != "both" else ("youtube", "tiktok"):
        db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": p, "style": "direct", "title": title,
                                          "description": f"{title}\n\nFollow for more clips like this.",
                                          "caption": f"{title} #test", "tags": ["test"], "hashtags": ["#test"],
                                          "score": packaging, "selected": 1})
    passed_report(clip)
    return clip


def test_grid_spreads_posts_over_active_hours(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    s = db.get_settings()
    day = dt.datetime.now(CHI).date()
    slots = scheduler.grid(s, day, 3)
    local = [dt.datetime.fromtimestamp(t, CHI) for t in slots]
    assert len(slots) == 3 and all(9 <= x.hour < 21 for x in local)
    assert all(b - a >= 3600 for a, b in zip(slots, slots[1:]))
    assert local[0].hour == 11 and local[1].hour == 15  # centers of four-hour blocks: no "best times" assumed


def test_final_score_is_explained_and_ignores_missing_scores():
    from clipfoundry.autopilot import scheduler

    value, why = scheduler.final_score({"clip": 80, "packaging": 60, "trend": None, "publish_opportunity": 50})
    assert 60 < value < 80 and why[0].startswith("Clip Score 80")
    assert any("Trend Score" in w and "not available" in w for w in why)


def test_planning_respects_gaps_limits_and_scores(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    clips = [make_clip(data, f"Clip number {k}", 50 + 10 * k) for k in range(5)]
    now = _at(6)  # early morning, before the active hours
    out = scheduler.plan_new(db.get_settings(), now)
    assert out["created"] == 5
    items = db.select("scheduled_publications", "", (), "planned_at")
    assert all(i["status"] == "awaiting_approval" and i["privacy"] == "private" for i in items)
    assert all(i["audience"]["intent"] == "SELECTED_AUDIENCE" for i in items)  # for the viewers you invite
    days = [dt.datetime.fromtimestamp(i["planned_at"], CHI).date() for i in items]
    assert days.count(days[0]) == 3  # the YouTube daily limit of 3; the rest go to tomorrow
    same_day = [i["planned_at"] for i in items if dt.datetime.fromtimestamp(i["planned_at"], CHI).date() == days[0]]
    assert all(b - a >= 3600 for a, b in zip(same_day, same_day[1:]))
    best = max(items, key=lambda i: i["final_score"])
    assert best["clip_id"] == clips[-1]["id"] and best["planned_at"] == min(i["planned_at"] for i in items)
    assert best["scores"]["explanation"] and best["audit"][0]["event"] == "scheduled"
    assert scheduler.plan_new(db.get_settings(), now)["created"] == 0  # nothing is scheduled twice


def test_learned_timing_picks_your_best_hour(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    db.insert("learning_metrics", {"id": "h19", "dimension": "hour", "key": "19", "platform": "youtube",
                                   "metric": "performance", "n": 12, "lift": 1.8, "data": {"reliable": True}})
    make_clip(data, "Only clip", 70)
    scheduler.plan_new(db.get_settings(), _at(6))
    item = db.select("scheduled_publications")[0]
    assert dt.datetime.fromtimestamp(item["planned_at"], CHI).hour == 19 and "your results" in item["slot"]["note"]


def test_dynamic_replacement_with_audit_trail(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, state

    db.save_settings({"autopilot_youtube_daily_limit": 1, "autopilot_replacement_threshold": 15})
    for k in range(3):
        make_clip(data, f"Weak clip {k}", 50 + k)
    now = _at(6)
    scheduler.plan_new(db.get_settings(), now)
    assert len(db.select("scheduled_publications")) == 3  # today, tomorrow, the day after: all slots taken
    strong = make_clip(data, "Much stronger clip", 95, packaging=90)
    out = scheduler.plan_new(db.get_settings(), now)
    assert out["replaced"] == 1
    weak = db.select("scheduled_publications", "status = 'replaced'")[0]
    new = db.select("scheduled_publications", "clip_id = ?", (strong["id"],))[0]
    assert weak["replaced_by"] == new["id"] and new["replaces"] == weak["id"]
    assert new["planned_at"] == weak["planned_at"] and weak["final_score"] == min(
        i["final_score"] for i in db.select("scheduled_publications"))
    assert "Final Opportunity Score" in weak["audit"][-1]["detail"] and new["audit"][0]["event"] == "replacement"
    assert any(e["kind"] == "replaced" for e in state.events())
    make_clip(data, "Barely better clip", 53)
    assert scheduler.plan_new(db.get_settings(), now)["replaced"] == 0  # below the 15% threshold


def test_approved_posts_are_only_swapped_after_approving_the_replacement(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    db.save_settings({"autopilot_youtube_daily_limit": 1})
    for k in range(3):
        make_clip(data, f"Approved clip {k}", 50 + k)
    now = _at(6)
    scheduler.plan_new(db.get_settings(), now)
    for it in db.select("scheduled_publications"):
        scheduler.approve(it["id"], {"options": {"made_for_kids": False}})
    weakest = min(db.select("scheduled_publications"), key=lambda i: i["final_score"])
    strong = make_clip(data, "Stronger clip", 95, packaging=95)
    assert scheduler.plan_new(db.get_settings(), now)["replaced"] == 1
    pending = db.select("scheduled_publications", "clip_id = ?", (strong["id"],))[0]
    assert pending["replaces"] == weakest["id"] and "Approve it to replace" in pending["status_note"]
    assert db.fetch("scheduled_publications", weakest["id"])["status"] == "approved"  # untouched until you decide
    scheduler.approve(pending["id"], {"options": {"made_for_kids": False}})
    assert db.fetch("scheduled_publications", weakest["id"])["status"] == "replaced"


def test_approval_rules_and_invalidation(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler
    from clipfoundry.publish.common import PublishError

    clip = make_clip(data, "Clip for approval", 70, platform="both")
    db.save_settings({"autopilot_tiktok": True})
    scheduler.plan_new(db.get_settings(), _at(6))
    yt = db.select("scheduled_publications", "platform = 'youtube'")[0]
    tt = db.select("scheduled_publications", "platform = 'tiktok'")[0]
    assert tt["privacy"] == ""  # TikTok: never pre-selected
    assert tt["options"]["mode"] == "manual"  # TikTok is not connected: a package you post yourself
    with pytest.raises(PublishError, match="made for kids"):
        scheduler.approve(yt["id"], {})
    with pytest.raises(PublishError, match="turned off"):
        scheduler.approve(tt["id"], {"privacy": "PUBLIC_TO_EVERYONE"})  # never everyone
    with pytest.raises(PublishError, match="audited"):  # followers through the API need an audited app
        scheduler.approve(tt["id"], {"privacy": "FOLLOWER_OF_CREATOR", "mode": "direct",
                                     "options": {"mode": "direct"}})
    ok = scheduler.approve(tt["id"], {})
    assert ok["status"] == "approved" and scheduler.approval_valid(ok)
    with pytest.raises(PublishError, match="turned off"):
        scheduler.approve(yt["id"], {"options": {"made_for_kids": False}, "privacy": "unlisted"})
    ok = scheduler.approve(yt["id"], {"options": {"made_for_kids": False}})
    assert ok["privacy"] == "private" and ok["approval"]["hash"] and ok["approval"]["scheme"] == 3
    edited = scheduler.edit(yt["id"], {"title": "A new title"})
    assert edited["status"] == "awaiting_approval"  # edits need a new approval
    scheduler.approve(yt["id"], {})
    import os

    os.utime(clip["output_path"], (time.time() + 100, time.time() + 100))  # touched: the same bytes
    assert scheduler.approval_valid(db.fetch("scheduled_publications", yt["id"]))  # bound to content, not to times
    with open(clip["output_path"], "r+b") as fh:  # re-rendered in place: same size and time, other bytes
        fh.write(b"V")
    os.utime(clip["output_path"], (time.time() + 100, time.time() + 100))
    assert not scheduler.approval_valid(db.fetch("scheduled_publications", yt["id"]))


def test_due_processing(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler, state

    make_clip(data, "Due clip", 70)
    make_clip(data, "Unapproved clip", 60)
    now = time.time()
    scheduler.plan_new(db.get_settings(), now)
    due, other = sorted(db.select("scheduled_publications"), key=lambda i: -i["final_score"])
    scheduler.approve(due["id"], {"options": {"made_for_kids": False}})
    db.update("scheduled_publications", due["id"], planned_at=now + 600)  # YouTube uploads 30 min early
    out = scheduler.process_due(db.get_settings(), now)
    assert out["publishing"] == 1 and db.fetch("scheduled_publications", due["id"])["status"] == "publishing"
    assert queue.jobs(worker="publisher")[0]["ref_id"] == due["id"]
    assert any(a["key"] == "approvals" for a in state.open_actions())
    db.update("scheduled_publications", other["id"], planned_at=now - 3600)  # missed while waiting for approval
    scheduler.process_due(db.get_settings(), now)
    moved = db.fetch("scheduled_publications", other["id"])
    assert moved["planned_at"] > now and moved["audit"][-1]["event"] == "rescheduled"
    db.update("scheduled_publications", other["id"], planned_at=now - 49 * 3600)
    scheduler.process_due(db.get_settings(), now)
    assert db.fetch("scheduled_publications", other["id"])["status"] == "canceled"


def test_auto_publish_off_asks_first(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, state

    db.save_settings({"autopilot_auto_publish": False})
    make_clip(data, "Clip", 70)
    now = time.time()
    scheduler.plan_new(db.get_settings(), now)
    item = db.select("scheduled_publications")[0]
    scheduler.approve(item["id"], {"options": {"made_for_kids": False}})
    db.update("scheduled_publications", item["id"], planned_at=now + 60)
    assert scheduler.process_due(db.get_settings(), now)["publishing"] == 0
    assert any(a["key"] == f"publish:{item['id']}" for a in state.open_actions())


def test_repeats_and_blocked_sources_are_never_scheduled(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scheduler

    text = "The hard part is not the money. The hard part is the silence after you quit."
    first = make_clip(data, "First upload", 70, text=text)
    db.create_publication(first["id"], "youtube", status="done", title="First upload")
    make_clip(data, "Same moment again", 80, text=text)  # e.g. found again in a re-upload
    src = db.insert("sources", {"platform": "youtube", "external_id": "x1", "title": "t", "channel_id": "UCb"})
    rights.add_rule("channel", "UCb", rights.ALLOWLISTED, "program")
    make_clip(data, "From a source that gets blocked", 75, source=src)
    rights.add_rule("source", src["id"], rights.BLOCKED, "rights withdrawn")
    out = scheduler.plan_new(db.get_settings(), _at(6))
    titles = {i["title"] for i in db.select("scheduled_publications")}
    assert out["created"] == 0 and not titles


def test_reschedule_checks_the_gap_and_cancel(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    make_clip(data, "A", 70)
    make_clip(data, "B", 60)
    scheduler.plan_new(db.get_settings(), _at(6))
    a, b = db.select("scheduled_publications", "", (), "planned_at")
    with pytest.raises(ValueError, match="minutes from another"):
        scheduler.reschedule(b["id"], a["planned_at"] + 600)
    moved = scheduler.reschedule(b["id"], a["planned_at"] + 7200)
    assert moved["slot"]["note"] == "chosen by you" and moved["audit"][-1]["event"] == "rescheduled"
    assert scheduler.cancel(b["id"])["status"] == "canceled"

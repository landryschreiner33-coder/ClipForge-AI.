"""ClipForge AI's commands (brain/operations.py): each runs the app's own action, finds exactly one thing first, waits
for the owner's OK, reports what the app shows afterwards and lets the chat follow the work it queued."""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

import pytest
from test_autopilot_scheduler import make_clip
from test_postpack import PODCAST, _srt

CHI = ZoneInfo("America/Chicago")


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import api, db

    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_tiktok": False,
                      "autopilot_active_start": 9, "autopilot_active_end": 21, "autopilot_min_gap_minutes": 60,
                      "autopilot_timezone": "America/Chicago"})
    # work is queued but not run: a heavy-work line of its own (an earlier test's worker thread may still be running
    # the app's), whose thread is never started
    from clipfoundry import jobs

    line = jobs.Worker()
    monkeypatch.setattr(line, "start", lambda: None)
    monkeypatch.setattr(api, "worker", line)
    return tmp_path


def tool(name: str):
    from clipfoundry.brain import tools

    return tools.get(name)


def ctx():
    from clipfoundry.brain import tools

    return tools.Ctx(ws="local")


def press(name: str, args: dict):
    """What the OK button does: the preview's arguments, checked as a button's, then run."""
    from clipfoundry.brain import tools

    t = tool(name)
    card = t.preview(ctx(), tools.check_args(t, args))
    return card, t.run(ctx(), tools.check_args(t, card["args"], button=True))


def local(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, CHI).strftime("%Y-%m-%dT%H:%M")


def two_posts(data, titles=("Summit sunrise", "Lake swim")) -> tuple[dict, dict]:
    """Two approved-to-be YouTube posts on the same account, tomorrow at 10:00 and 14:00 Chicago time."""
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    for t in titles:
        make_clip(data, t, 70)
    scheduler.plan_new(db.get_settings(), time.time())
    rows = db.select("scheduled_publications", "", (), "planned_at")
    assert len(rows) >= 2
    day = dt.datetime.now(CHI).date() + dt.timedelta(days=1)
    for row, hour in zip(rows[:2], (10, 14)):
        at = dt.datetime.combine(day, dt.time(hour), CHI).timestamp()
        db.update("scheduled_publications", row["id"], planned_at=at)
    return tuple(db.fetch("scheduled_publications", r["id"]) for r in rows[:2])  # type: ignore[return-value]


def test_the_commands_wait_for_ok_and_are_the_owners_alone():
    from clipfoundry.brain import assistant, tools

    names = {"reschedule_post", "fix_post_conflicts", "cancel_upload", "cancel_post", "retry_post", "restart_work",
             "stop_work", "regenerate_post_text", "adjust_framing", "pause_mission", "change_setting"}
    for n in names:
        assert tool(n).risk in tools.WAITS and tool(n).preview is not None, n
    every = [t.name for t in tools.all_tools()]
    helper = tools.available("general", agent={"tools": every})
    assert not names & {t.name for t in helper} and "render_clip" not in {t.name for t in helper}
    # the one command that approves or posts (Landry, Nov 26) is approve_post, YouTube only; with "Ask me first" the
    # rules still say it never does (test_assistant_acts_alone.py)
    assert [n for n in every if "publish" in n or "approve" in n] == ["approve_post"]
    assert "never publish or approve a post" in assistant.rules({"ai_acts_alone": False})


def test_move_a_post_to_a_time_in_the_autopilot_time_zone(data):
    from clipfoundry import db

    a, b = two_posts(data)
    wanted = local(b["planned_at"] + 2 * 3600)
    card, done = press("reschedule_post", {"post": "lake swim", "when": wanted})
    assert card["label"].startswith("Move “Lake swim” (YouTube") and "America/Chicago" in " ".join(card["detail"])
    moved = db.fetch("scheduled_publications", b["id"])
    assert local(moved["planned_at"]) == wanted and moved["audit"][-1]["event"] == "rescheduled"
    assert "America/Chicago" in done.text and done.data["links"][0]["href"] == f"#/post/{b['id']}"
    assert done.data["work"][0] == {**done.data["work"][0], "kind": "post", "id": b["id"]}


def test_a_time_too_close_to_another_post_becomes_the_nearest_free_one(data):
    from clipfoundry import db
    from clipfoundry.brain.tools import ToolError

    a, b = two_posts(data)
    card, _done = press("reschedule_post", {"post": "lake", "when": local(a["planned_at"] + 600)})
    assert "less than 60 minutes from another post" in " ".join(card["detail"])
    moved = db.fetch("scheduled_publications", b["id"])["planned_at"]
    assert abs(moved - a["planned_at"]) >= 3600 and abs(moved - (a["planned_at"] + 600)) <= 3600
    with pytest.raises(ToolError, match="has passed"):
        tool("reschedule_post").preview(ctx(), {"post": "lake", "when": local(time.time() - 7200)})
    with pytest.raises(ToolError, match="2026-11-26T18:30"):
        tool("reschedule_post").preview(ctx(), {"post": "lake", "when": "tomorrow evening"})


def test_when_more_than_one_post_fits_it_names_them_and_asks(data):
    from clipfoundry.brain.tools import ToolError

    two_posts(data, ("Hike day one", "Hike day two"))
    with pytest.raises(ToolError, match="More than one post .* Ask the owner which one") as err:
        tool("reschedule_post").preview(ctx(), {"post": "hike", "when": "nearest_free"})
    assert "Hike day one" in str(err.value) and "Hike day two" in str(err.value)
    card = tool("reschedule_post").preview(ctx(), {"post": "hike 14:00", "when": "nearest_free"})  # its time decides
    assert "Hike day two" in card["label"]
    with pytest.raises(ToolError, match="No post that can be moved matches"):
        tool("reschedule_post").preview(ctx(), {"post": "kayak", "when": "nearest_free"})


def test_posts_too_close_together_are_fixed_on_one_card(data):
    from clipfoundry import db
    from clipfoundry.brain import operations
    from clipfoundry.brain.tools import ToolError

    a, b = two_posts(data)
    db.update("scheduled_publications", b["id"], planned_at=a["planned_at"] + 900)  # e.g. the gap was raised
    assert set(operations.conflicts()) == {b["id"]}
    listed = tool("posts").run(ctx(), {}).text
    assert "Too close to “Summit sunrise”" in listed and "fix_post_conflicts" in listed
    card, done = press("fix_post_conflicts", {})
    assert len(card["args"]["moves"]) == 1 and "→" in card["detail"][0]
    assert done.ok and operations.conflicts() == {} and "No posts are too close now" in done.text
    with pytest.raises(ToolError, match="No posts are too close"):
        tool("fix_post_conflicts").preview(ctx(), {})


def test_cancel_an_upload_and_take_a_post_off_the_schedule(data):
    from clipfoundry import db
    from clipfoundry.brain.tools import ToolError

    a, b = two_posts(data)
    with pytest.raises(ToolError, match="no post that is uploading now"):
        tool("cancel_upload").preview(ctx(), {"post": "summit"})
    db.update("scheduled_publications", a["id"], status="publishing")
    card, done = press("cancel_upload", {"post": "summit"})
    assert card["label"].startswith("Cancel the upload of “Summit sunrise” to YouTube")
    assert db.fetch("scheduled_publications", a["id"])["status"] == "canceled" and "canceled" in done.text
    card, done = press("cancel_post", {"post": "lake"})
    assert db.fetch("scheduled_publications", b["id"])["status"] == "canceled" and "will not be posted" in done.text
    card, done = press("retry_post", {"post": "lake"})  # and back: it needs a valid approval to go out
    assert db.fetch("scheduled_publications", b["id"])["status"] in ("approved", "awaiting_approval")


@pytest.fixture()
def clip(data):
    from clipfoundry import config, db
    from clipfoundry.pipeline import transcribe
    from clipfoundry.pipeline.common import write_json

    segs = transcribe.parse_subtitles(_srt(PODCAST))
    pdir = config.projects_dir() / "p1"
    pdir.mkdir(parents=True)
    write_json(pdir / "transcript.json", {"segments": segs})
    words = transcribe.flatten_words({"segments": segs})
    start = next(w["start"] for w in words if w["w"] == "Why")
    end = next(w["end"] for w in words if w["w"] == "later.")
    project = db.create_project("Running podcast", source_path=str(pdir / "source.mp4"), status="ready")
    return db.create_clip(project["id"], start=start, end=end, title="old title", hashtags=["#old"], status="ready",
                          score=80, caption_text="")


def test_new_post_text_and_a_new_crop_go_through_the_clip_editor_actions(clip):
    from clipfoundry import db
    from clipfoundry.brain import operations

    card, done = press("regenerate_post_text", {"project": "running podcast", "clip": "1"})
    assert "now: “old title”" in card["detail"][0]
    fresh = db.get_clip(clip["id"])
    assert fresh["title"] != "old title" and fresh["post"]["title"] in done.text
    card, done = press("adjust_framing", {"project": "running podcast", "clip": "best", "position": 30, "zoom": 1.2})
    assert card["label"].endswith("the picture at 30% from the left, zoom 1.2×")
    fresh = db.get_clip(clip["id"])
    assert fresh["edit"]["tracking"] == "manual" and fresh["edit"]["crop_x"] == 0.3 and fresh["status"] == "queued"
    assert done.data["work"][0]["kind"] == "clip"
    assert operations.work_state("clip", clip["id"])["state"] == "queued"


def test_render_a_clip_and_follow_it_to_completed(clip):
    from clipfoundry import db
    from clipfoundry.brain import operations
    from clipfoundry.brain.tools import ToolError

    done = tool("render_clip").run(ctx(), {"project": "running podcast", "clip": "1"})
    assert done.data["work"][0]["id"] == clip["id"] and operations.work_state("clip", clip["id"])["state"] == "queued"
    with pytest.raises(ToolError, match="already rendering"):
        tool("render_clip").run(ctx(), {"project": "running podcast", "clip": "1"})
    db.update_clip(clip["id"], status="rendering", progress=0.4)
    from clipfoundry import api

    api.worker.current = clip["id"]
    assert operations.work_state("clip", clip["id"])["state"] == "running"
    db.update_clip(clip["id"], status="ready", progress=1)
    api.worker.current = None
    assert operations.work_state("clip", clip["id"])["state"] == "completed"


def test_a_stalled_project_is_diagnosed_and_started_again_once(data, monkeypatch):
    from clipfoundry import api, db
    from clipfoundry.brain import operations
    from clipfoundry.brain.tools import ToolError

    source = data / "src.mp4"
    source.write_bytes(b"video")
    p = db.create_project("Stuck stream", status="processing", stage="transcribing", progress=0.3,
                          source_path=str(source))
    seen = tool("work").run(ctx(), {"words": "stuck"}).text
    assert "Project “Stuck stream”: stalled" in seen and "restart_work" in seen
    card, done = press("restart_work", {"project": "stuck stream"})
    assert card["label"].startswith("Start making the clips of “Stuck stream” again")
    assert [k for _kind, k, _x in list(api.worker.q.queue)] == [p["id"]]
    assert operations.work_state("project", p["id"])["state"] == "queued"
    with pytest.raises(ToolError, match="queued"):  # never twice in the line
        tool("restart_work").preview(ctx(), {"project": "stuck stream"})
    api.worker.q.get_nowait()
    monkeypatch.setattr(api.worker, "current", p["id"])
    db.update_project(p["id"], status="processing")
    assert operations.diagnose_project(db.get_project(p["id"]))["state"] == "running"
    old = time.time() - 20 * 60
    with db.connect() as conn:
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (old, p["id"]))
    d = operations.diagnose_project(db.get_project(p["id"]))
    assert d["state"] == "stalled" and "has not moved for 20 minutes" in d["why"]


def test_pause_a_mission_and_change_an_editing_setting(data):
    from clipfoundry import db
    from clipfoundry.brain.tools import ToolError

    src = db.insert("sources", {"title": "Friday night stream", "url": "https://www.twitch.tv/videos/1",
                                "platform": "twitch", "external_id": "1"})
    row = db.insert("source_submissions", {"source_id": src["id"], "settings": {}})
    card, done = press("pause_mission", {"mission": "friday stream", "paused": True})
    assert card["label"] == "Pause the uploads of “Friday night stream”" and "paused" in done.text
    assert db.fetch("source_submissions", row["id"])["settings"]["paused"] is True
    card, done = press("change_setting", {"setting": "clips per video", "value": "7"})
    assert card["label"].startswith("Change Clips per video from") and db.get_settings()["clip_count"] == 7
    for off_limits in ("autopilot_auto_publish", "daily target", "cloud spending limit"):
        with pytest.raises(ToolError, match="changed by the owner on their own pages"):
            tool("change_setting").preview(ctx(), {"setting": off_limits, "value": "true"})


def test_the_chat_follows_work_its_ok_button_queued(clip):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.brain import chat

    c = chat.open_chat("local")
    m = db.insert("brain_chat_messages", {"chat_id": c["id"], "role": "ai", "text": "Shall I?", "status": "done",
                                          "data": {"pending": [{"id": "a1", "tool": "adjust_framing", "risk": "change",
                                                                "label": "Frame", "detail": [], "blocked": "",
                                                                "state": "waiting", "result": "",
                                                                "args": {"clip_id": clip["id"],
                                                                         "edit": {"layout": "fit"}}}]}})
    out = chat.decide("local", c["id"], m["id"], "a1", True)
    assert out["data"]["pending"][0]["state"] == "done" and out["data"]["work"][0]["id"] == clip["id"]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        r = client.get(f"/api/brain/chats/work/clip/{clip['id']}")
        assert r.status_code == 200 and r.json()["state"] == "queued" and r.json()["href"] == f"#/clip/{clip['id']}"
        assert client.get("/api/brain/chats/work/nope/x").status_code == 404


def test_the_crew_checks_clips_and_reports_what_it_decided(clip, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import queue
    from clipfoundry.autopilot.host import MANUAL_PRIORITY
    from clipfoundry.brain import operations
    from clipfoundry.brain.tools import ToolError
    from clipfoundry.office import feed

    with pytest.raises(ToolError, match="Render them first"):  # the clip has no file yet
        db.update_clip(clip["id"], status="queued")
        tool("crew_check").run(ctx(), {"project": "running podcast"})
    video = db.get_project(clip["project_id"])["source_path"]
    db.update_clip(clip["id"], status="ready", output_path=video)
    open(video, "wb").write(b"not really a video")
    done = tool("crew_check").run(ctx(), {"project": "running podcast", "clip": "1"})
    job = queue.get(done.data["work"][0]["id"])
    assert job["kind"] == "quality_check" and job["priority"] == MANUAL_PRIORITY and job["ref_id"] == clip["id"]
    again = tool("crew_check").run(ctx(), {"project": "running podcast", "clip": "1"})
    assert again.data["work"][0]["id"] == job["id"]  # asking twice never queues the check twice
    assert operations.work_state("job", job["id"])["state"] == "queued"
    feed.decide("qc", "rework", ("clip", clip["id"]), "Returned to QUILL: title too long", job_id=job["id"],
                reported_by="check")
    said = tool("crew_report").run(ctx(), {"project": "running podcast", "clip": "1"}).text
    assert "sent back (Returned to QUILL: title too long)" in said and "quality check (queued" in said
    assert "regenerate_post_text" in said


def test_work_of_another_workspace_answers_like_work_that_is_gone(clip):
    from clipfoundry.brain import operations

    assert operations.work_state("clip", clip["id"], "local")["href"] == f"#/clip/{clip['id']}"
    other = operations.work_state("clip", clip["id"], "someone-else")
    assert other["state"] == "canceled" and other["href"] == "" and operations.work_owner("clip", "nope") is None

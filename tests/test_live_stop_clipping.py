"""Stop clipping: the stream stops being recorded and clipped at any time; what was made still uploads.

Platforms are never contacted: the recorder, the full-recording analysis and YouTube are stand-ins (the shared
live fixtures); every rule under test is ClipForge's own.
"""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_review_submitted_live import (FakeRecorder, _joined_file, add_live, broadcasts, data,  # noqa: F401
                                        going_live, post_live_jobs, recorder, turn_job)
from test_review_submitted_routes import H  # the app's own request header


def live_clip(project_id, folder, start=10.0, end=40.0, score=80.0, name="live.mp4"):
    """A clip made while the stream was live, with its file."""
    from clipfoundry import db

    out = Path(folder) / name
    out.write_bytes(b"checked clip bytes")
    return db.create_clip(project_id, start=start, end=end, status="ready", score=score, score_source="Live analysis",
                          output_path=str(out))


def recording(monkeypatch, minutes=2):
    """A stream that is being recorded, `minutes` of it heard; returns (source, job, recorder, picker calls)."""
    from clipfoundry.autopilot import live, queue

    asked = []
    monkeypatch.setattr(live, "detect", lambda sess, job: asked.append(sess.offset))
    broadcasts(monkeypatch, "b1")
    src = going_live(add_live())
    host = SimpleNamespace(_stop=threading.Event(), set_state=lambda *a, **kw: None)
    job = turn_job(src, host)
    with pytest.raises(queue.Wait, match="Watching live"):
        live.live_capture(job)
    rec = FakeRecorder.made[-1]
    for _ in range(minutes):
        rec.minute()
        with pytest.raises(queue.Wait, match="Watching live"):
            live.live_capture(job)
    return src, job, rec, asked


def test_stop_clipping_stops_the_recorder_and_the_picker_and_keeps_what_was_made(data, recorder, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, live, queue, submissions
    from clipfoundry.autopilot.host import MANUAL_PRIORITY, Job

    src, job, rec, asked = recording(monkeypatch)
    assert asked == [60.0, 120.0]  # the picker listened to both minutes
    project_id = db.fetch("sources", src["id"])["project_id"]
    clip = live_clip(project_id, data)
    post = db.insert("scheduled_publications", {"clip_id": clip["id"], "source_id": src["id"], "platform": "youtube",
                                                "status": "approved", "planned_at": 4102444800})
    view = intake.item(db.fetch("sources", src["id"]))
    assert view["can_stop_clipping"] and not view["clipping_stopped"]

    rec.minute()  # a third minute is recorded but not heard yet when the button is pressed
    after = intake.action(src["id"], "stop_clipping")
    assert after["clipping_stopped"] and not after["can_stop_clipping"] and not after["can_finish"]
    assert after["finishing"] and "still upload" in after["detail"]
    assert intake.clipping_stopped(src["id"]) and intake.finish_requested(src["id"])
    assert db.fetch("worker_jobs", job.id)["priority"] == MANUAL_PRIORITY
    with pytest.raises(ValueError, match="No clips are being made"):
        intake.action(src["id"], "stop_clipping")
    # nothing of what was made is touched by the press
    assert db.get_clip(clip["id"])["status"] == "ready"
    assert db.fetch("scheduled_publications", post["id"])["status"] == "approved"

    for _ in range(4):  # the closing turns: the last minute is kept for the recording, never searched for clips
        try:
            result = live.live_capture(job)
            break
        except queue.Wait:
            continue
    assert rec.stopped_reason == "finish" and result["minutes"] == 3
    assert asked == [60.0, 120.0]
    source = db.fetch("sources", src["id"])
    assert source["live_status"] == "stopped" and source["status"] == "analyzing"
    assert "no more clips are made" in source["status_note"]

    # the stream is closed without transcribing, searching or rendering anything from the full recording
    def never(*args, **kwargs):
        raise AssertionError("the full recording is not analyzed after Stop clipping")

    for name in ("prepare", "candidate_pool", "evaluate_select", "create_clips", "render_clips"):
        monkeypatch.setattr(live.process, name, never)
    closing = post_live_jobs()
    assert len(closing) == 1
    out = live.post_live(Job(closing[0], "test"))
    assert out["stopped"] and out["added"] == 0 and "1 clip(s) were made and still upload" in out["message"]
    source = db.fetch("sources", src["id"])
    assert source["status"] == "analyzed" and source["clips_selected"] == 1
    assert db.get_project(project_id)["status"] == "ready"
    # the clip made live goes on: handed to its checks, its approved post untouched, its upload request valid
    assert db.get_clip(clip["id"])["status"] == "ready"
    assert db.fetch("scheduled_publications", post["id"])["status"] == "approved"
    assert [j["payload"]["clip_id"] for j in queue.jobs(worker="packager")] == [clip["id"]]
    assert submissions.problem(source) == ""
    for row in queue.jobs(limit=100):  # the closing step and the clip's hand-over have run
        db.update("worker_jobs", row["id"], status="completed")
    shown = next(row for row in submissions.live_items() if row["id"] == src["id"])
    assert shown["live"]["clipping_stopped"] and shown["live"]["stopped"] and not shown["can_stop_clipping"]
    assert shown["status"] == "ready" and "still upload" in shown["detail"]


def test_stop_clipping_while_the_full_recording_is_analyzed_keeps_the_live_clip(data, monkeypatch):
    """Pressed between two renders after the stream: the clip being made is finished, the rest is never made, and
    a second cut of a live clip's moment does not replace the live clip or its planned upload."""
    from clipfoundry import db
    from clipfoundry.autopilot import host, intake, live, queue

    src = going_live(add_live())
    sess = live.Session(src, db.get_settings())
    sess.segments = [{"name": "r001_00000.mkv", "start": 0.0, "end": 120.0}]
    sess.offset = 120.0
    sess.save()
    _joined_file(sess)
    project_id = sess.project["id"]
    db.update("sources", src["id"], live_status="ended", status="analyzing")
    old = live_clip(project_id, data, start=20.0, end=40.0, score=60.0)
    post = db.insert("scheduled_publications", {"clip_id": old["id"], "source_id": src["id"], "platform": "youtube",
                                                "status": "awaiting_approval", "planned_at": 4102444800})
    story = {"structure": {"hook": True, "context": True, "payoff": True}}
    chosen = [{"start": 20, "end": 40, "score": 75, "analysis": story},   # a better cut of the live clip's moment
              {"start": 50, "end": 70, "score": 80, "analysis": story},
              {"start": 80, "end": 100, "score": 78, "analysis": story}]
    pdir = data / "prepared"
    pdir.mkdir()
    monkeypatch.setattr(live.process, "prepare", lambda *args: SimpleNamespace(id=project_id, pdir=pdir, opts={},
                                                                               meta={"duration": 120.0}))
    monkeypatch.setattr(live.process, "candidate_pool", lambda *args: [])
    monkeypatch.setattr(live.process, "evaluate_select", lambda *a, **kw: chosen)
    monkeypatch.setattr(live, "screen_stories", lambda p, rows, settings: rows)
    monkeypatch.setattr(live, "plan_clips", lambda p, rows, keep, src_id: rows)
    monkeypatch.setattr(live, "store_fingerprint", lambda *args: None)

    def create(p, keep, ctx, replace_existing=True, durable=False):
        return [db.get_clip(f"after-{k}") or db.create_clip(p.id, id=f"after-{k}", start=m["start"], end=m["end"],
                                                           status="queued", score=m["score"])
                for k, m in enumerate(keep)]

    rendered = []

    def render(p, rows, ctx, **kw):
        for row in rows:
            rendered.append(row["id"])
            out = pdir / f"{row['id']}.mp4"
            out.write_bytes(b"rendered")
            db.update_clip(row["id"], status="ready", output_path=str(out))
        if len(rendered) == 2:
            assert intake.item(db.fetch("sources", src["id"]))["can_stop_clipping"]
            intake.action(src["id"], "stop_clipping")  # pressed while the second clip was being made

    monkeypatch.setattr(live.process, "create_clips", create)
    monkeypatch.setattr(live.process, "render_clips", render)
    row = queue.enqueue("post_live", {"source_id": src["id"], "project_id": project_id}, priority=80,
                        idem_key=f"post_live:{src['id']}:{project_id}", ref=("source", src["id"]))
    out = live.post_live(host.Job(queue.get(row["id"]), "test"))
    assert rendered == ["after-0", "after-1"] and out["stopped"] and out["added"] == 1
    # the live clip and its planned post are exactly as they were
    assert db.get_clip(old["id"])["status"] == "ready"
    assert db.fetch("scheduled_publications", post["id"])["status"] == "awaiting_approval"
    second_cut = db.get_clip("after-0")
    assert second_cut["status"] == "superseded" and "live clip of this moment is kept" in second_cut["error"]
    assert db.get_clip("after-1")["status"] == "ready"           # finished before the stop took effect: kept
    never_made = db.get_clip("after-2")
    assert never_made["status"] == "superseded" and "Not made" in never_made["error"]
    packaged = sorted(j["payload"]["clip_id"] for j in queue.jobs(worker="packager"))
    assert packaged == sorted([old["id"], "after-1"])
    source = db.fetch("sources", src["id"])
    assert source["status"] == "analyzed" and source["clips_selected"] == 2
    assert db.fetch("worker_jobs", row["id"])["priority"] == host.MANUAL_PRIORITY
    # running the closing step again (a restart) changes nothing and makes nothing
    again = live.post_live(host.Job(queue.get(row["id"]), "test"))
    assert again["stopped"] and rendered == ["after-0", "after-1"]
    assert db.get_clip("after-2")["status"] == "superseded" and db.get_clip(old["id"])["status"] == "ready"


def test_stop_clipping_after_a_better_cut_took_the_live_clips_place_keeps_the_better_cut(data, monkeypatch):
    """The closing step put a better cut in a live clip's place and then failed before it finished. Stop clipping
    is pressed while it waits to run again: the re-run must keep the better cut, or the moment has no clip."""
    from clipfoundry import db
    from clipfoundry.autopilot import host, intake, live, queue

    src = going_live(add_live())
    sess = live.Session(src, db.get_settings())
    sess.segments = [{"name": "r001_00000.mkv", "start": 0.0, "end": 120.0}]
    sess.offset = 120.0
    sess.save()
    _joined_file(sess)
    project_id = sess.project["id"]
    db.update("sources", src["id"], live_status="ended", status="analyzing")
    old = live_clip(project_id, data, start=20.0, end=40.0, score=60.0)
    db.insert("scheduled_publications", {"clip_id": old["id"], "source_id": src["id"], "platform": "youtube",
                                         "status": "awaiting_approval", "planned_at": 4102444800})
    story = {"structure": {"hook": True, "context": True, "payoff": True}}
    chosen = [{"start": 20, "end": 40, "score": 75, "analysis": story},   # a better cut of the live clip's moment
              {"start": 50, "end": 70, "score": 80, "analysis": story}]
    pdir = data / "prepared"
    pdir.mkdir()
    monkeypatch.setattr(live.process, "prepare", lambda *args: SimpleNamespace(id=project_id, pdir=pdir, opts={},
                                                                               meta={"duration": 120.0}))
    monkeypatch.setattr(live.process, "candidate_pool", lambda *args: [])
    monkeypatch.setattr(live.process, "evaluate_select", lambda *a, **kw: chosen)
    monkeypatch.setattr(live, "screen_stories", lambda p, rows, settings: rows)
    monkeypatch.setattr(live, "plan_clips", lambda p, rows, keep, src_id: rows)
    fails = [True]

    def fingerprint(*args):
        if fails:
            fails.pop()
            raise RuntimeError("the clip's picture could not be read for its fingerprint")

    monkeypatch.setattr(live, "store_fingerprint", fingerprint)

    def create(p, keep, ctx, replace_existing=True, durable=False):
        return [db.get_clip(f"after-{k}") or db.create_clip(p.id, id=f"after-{k}", start=m["start"], end=m["end"],
                                                           status="queued", score=m["score"])
                for k, m in enumerate(keep)]

    def render(p, rows, ctx, **kw):
        for row in rows:
            out = pdir / f"{row['id']}.mp4"
            out.write_bytes(b"rendered")
            db.update_clip(row["id"], status="ready", output_path=str(out))

    monkeypatch.setattr(live.process, "create_clips", create)
    monkeypatch.setattr(live.process, "render_clips", render)
    row = queue.enqueue("post_live", {"source_id": src["id"], "project_id": project_id}, priority=80,
                        idem_key=f"post_live:{src['id']}:{project_id}", ref=("source", src["id"]))
    with pytest.raises(RuntimeError):
        live.post_live(host.Job(queue.get(row["id"]), "test"))  # failed after the better cut took over
    assert db.get_clip(old["id"])["status"] == "superseded" and db.get_clip("after-0")["status"] == "ready"
    db.update("worker_jobs", row["id"], status="retrying")  # what the worker host does with an unexpected error
    assert intake.item(db.fetch("sources", src["id"]))["can_stop_clipping"]
    intake.action(src["id"], "stop_clipping")
    out = live.post_live(host.Job(queue.get(row["id"]), "test"))
    assert out["stopped"]
    assert db.get_clip("after-0")["status"] == "ready"  # the moment keeps its better cut
    assert db.get_clip("after-1")["status"] == "ready"
    assert db.get_clip(old["id"])["status"] == "superseded"


def test_stop_clipping_before_the_stream_started_ends_the_input(data, recorder, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, live, queue

    calls = broadcasts(monkeypatch, live.StreamOffline)
    src = going_live(add_live())
    job = turn_job(src)
    with pytest.raises(queue.Wait) as waiting:
        live.live_capture(job)
    assert waiting.value.reason == "offline"
    assert intake.item(db.fetch("sources", src["id"]))["can_stop_clipping"]
    intake.action(src["id"], "stop_clipping")
    result = live.live_capture(job)
    assert result["minutes"] == 0 and len(calls) == 1  # the closing turn never contacts the platform
    after = db.fetch("sources", src["id"])
    assert after["status"] == "canceled" and "before anything was recorded" in after["status_note"]
    assert not post_live_jobs()


def test_stop_clipping_is_refused_when_no_clips_are_being_made(data):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.autopilot import intake, submissions

    src = add_live()  # only its link is being checked: nothing is recorded or analyzed yet
    assert not intake.item(db.fetch("sources", src["id"]))["can_stop_clipping"]
    with pytest.raises(ValueError, match="No clips are being made"):
        intake.action(src["id"], "stop_clipping")
    assert not intake.clipping_stopped(src["id"])
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    assert client.post(f"/api/autopilot/links/{src['id']}/stop_clipping", headers=H).status_code == 409
    video = submissions.add_link("https://www.youtube.com/watch?v=abcdefghijk", {"auto_upload": False})
    assert not video["item"]["can_stop_clipping"] and not video["item"]["clipping_stopped"]


def test_stop_clipping_through_the_app_and_after_stop_recording(data, recorder, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.autopilot import intake, live, queue

    src, job, rec, asked = recording(monkeypatch, minutes=1)
    intake.action(src["id"], "finish")  # Stop recording first: the full recording would still be analyzed
    assert intake.item(db.fetch("sources", src["id"]))["can_stop_clipping"]
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    assert client.post(f"/api/autopilot/links/{src['id']}/stop_clipping").status_code == 403  # the app only
    pressed = client.post(f"/api/autopilot/links/{src['id']}/stop_clipping", headers=H)
    assert pressed.status_code == 200 and pressed.json()["clipping_stopped"]
    assert client.post(f"/api/autopilot/links/{src['id']}/stop_clipping", headers=H).status_code == 409
    result = live.live_capture(job)
    assert result["minutes"] == 1 and asked == [60.0]
    assert "no more clips are made" in db.fetch("sources", src["id"])["status_note"]
    # Try again never takes the stop back: the stream stays closed to new clips
    db.update("sources", src["id"], status="failed")
    for row in queue.jobs(limit=100):
        db.update("worker_jobs", row["id"], status="failed")
    intake.action(src["id"], "retry")
    assert intake.clipping_stopped(src["id"]) and intake.finish_requested(src["id"])


def test_stop_clipping_pressed_while_a_minute_is_searched_makes_no_clip(data, recorder, monkeypatch):
    """The search of a minute takes a while. A press during it must not be followed by a new clip."""
    from clipfoundry import db
    from clipfoundry.autopilot import intake, live

    src, job, rec, asked = recording(monkeypatch, minutes=1)
    sess = live.Session(db.fetch("sources", src["id"]), db.get_settings())

    def found_while_pressed(sess, job):
        intake.action(src["id"], "stop_clipping")  # pressed while this minute was being searched
        return {"r": {"start": 10.0, "end": 40.0}, "sents": [], "loud": None}

    made = []
    monkeypatch.setattr(live, "detect", found_while_pressed)
    monkeypatch.setattr(live, "make_live_clip", lambda *args: made.append(args))
    live._clip_minute(sess, job)  # noqa: SLF001 - the step under test
    assert made == [] and sess.note == live.live_pick.NOTES["stopped"]

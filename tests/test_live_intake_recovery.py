"""Live sources retain recorded minutes and get fair, cancelable processing turns."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.autopilot import live

    db.init()
    db.save_settings({"autopilot_enabled": True})
    yield tmp_path
    live.stop_captures()
    live._captures.clear()


def source(data, name="one"):
    from clipfoundry import db

    recording = data / f"{name}.mkv"
    recording.write_bytes(b"recording")
    return db.insert("sources", {"platform": "local", "external_id": name, "title": name, "kind": "live",
                                 "local_path": str(recording), "user_added": 1, "status": "queued"})


def context(src, host=None, priority=80):
    from clipfoundry import db
    from clipfoundry.autopilot import host as host_mod, queue

    if src.get("user_added"):
        db.update("sources", src["id"], intake={**(src.get("intake") or {}), "priority": priority})
    row = queue.enqueue("live_capture", {"source_id": src["id"]}, priority=priority,
                        ref=("source", src["id"]))
    return host_mod.Job(row, "test", host)


def record_segment(sess, name, duration, job):
    sess.segments.append({"name": name, "start": sess.offset, "end": sess.offset + duration})
    sess.offset += duration
    sess.save()


def test_previous_csv_and_atomic_words_recovered(data):
    from clipfoundry import db
    from clipfoundry.autopilot import live
    from clipfoundry.pipeline.common import write_json

    src = source(data)
    sess = live.Session(src, db.get_settings())
    sess.listfile.write_text("r001_00000.mkv,0,60\nr001_00001.mkv,60,120\n")
    sess.segments = [{"name": "r001_00000.mkv", "start": 0, "end": 60}]
    sess.offset = 60
    sess.transcript = {"segments": [{"start": 1, "end": 2, "text": "saved", "words": []}]}
    sess.save()
    write_json(sess.pdir / "transcript.json", {"segments": []})  # crash left the derived file behind
    again = live.Session(db.fetch("sources", src["id"]), db.get_settings())
    again.listfile.write_text("r002_00000.mkv,0,30\n")
    assert live.finished_segments(again) == [("r001_00001.mkv", 60), ("r002_00000.mkv", 30)]
    assert again.offset == 60 and again.transcript["segments"][0]["text"] == "saved"
    cmd = live.capture_command(again, ["-i", src["local_path"]])
    assert cmd[cmd.index("-ss") + 1] == "150.000000"
    assert cmd.index("-ss") > cmd.index("-i")  # no copied keyframes from an already recorded interval


def test_user_added_local_capture_keeps_explicit_blocks(data):
    from clipfoundry import db
    from clipfoundry.autopilot import live, rights

    src = source(data)
    assert live.capture_allowed(src, db.get_settings())[0]
    rights.add_rule("folder", str(data), rights.BLOCKED, "Do not use")
    assert not live.capture_allowed(src, db.get_settings())[0]


def test_restart_recovers_committed_live_clip_and_missing_package(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue

    src = source(data)
    first = live.Session(src, db.get_settings())
    output = first.pdir / "committed.mp4"
    output.write_bytes(b"ready")
    clip = db.create_clip(first.project["id"], start=15, end=35, status="ready", score=75,
                          score_source="Live analysis", output_path=str(output))
    again = live.Session(db.fetch("sources", src["id"]), db.get_settings())
    assert [c["id"] for c in again.clips] == [clip["id"]]
    monkeypatch.setattr(live, "store_fingerprint", lambda *args: None)
    job = context(src, priority=90)
    live._resume_live_outputs(again, job)
    live._resume_live_outputs(again, job)
    packages = queue.jobs(worker="packager")
    assert len(packages) == 1 and packages[0]["priority"] == 90


def test_multiple_captures_take_bounded_turns_without_restarting_recorders(data, monkeypatch):
    from clipfoundry.autopilot import live, queue

    made = []

    class Recording:
        def __init__(self, sess, job, args, relays=None):
            self.sess, self.job_id, self.host = sess, job.id, job.host
            self.stopped_reason = ""
            self.proc = SimpleNamespace(poll=lambda: None)
            self.closed = False
            sess.listfile.write_text(f"r{sess.run:03d}_00000.mkv,0,60\nr{sess.run:03d}_00001.mkv,60,120\n")
            made.append(self)

        def stop(self, reason=""):
            self.stopped_reason = reason
            self.closed = True

    monkeypatch.setattr(live, "Capture", Recording)
    monkeypatch.setattr(live, "process_segment", record_segment)
    monkeypatch.setattr(live, "detect", lambda sess, job: None)
    monkeypatch.setattr(live, "input_args", lambda src, settings, **kw: [])
    host = SimpleNamespace(_stop=threading.Event(), set_state=lambda *a, **kw: None)
    first, second = context(source(data, "one"), host), context(source(data, "two"), host)
    for job in (first, second, first):
        with pytest.raises(queue.Wait, match="Watching live") as waiting:
            live.live_capture(job)
        assert waiting.value.reason == "live"
    assert len(made) == 2 and [c.sess.offset for c in made] == [120, 60]
    assert all(c.sess.run == 1 and not c.closed for c in made)
    live.stop_captures(host)
    assert all(c.closed for c in made)


def test_watchdog_honors_cancel_between_turns(data):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue

    src = source(data)
    job = context(src)
    queue.cancel(job.id)
    capture = live.Capture.__new__(live.Capture)
    capture.sess = SimpleNamespace(src=src)
    capture.job_id = job.id
    capture.host = SimpleNamespace(_stop=threading.Event())
    capture.proc = SimpleNamespace(poll=lambda: None)
    capture.stopped = SimpleNamespace(wait=lambda seconds: False)
    reasons = []
    capture.stop = reasons.append
    capture._watch()
    assert reasons == ["canceled"]
    assert db.fetch("sources", src["id"])["status"] == "canceled"


def test_parent_pipe_reaps_capture_and_releases_source_lock(data, monkeypatch):
    from clipfoundry import db, locks
    from clipfoundry.autopilot import live

    src = source(data)
    sess = live.Session(src, db.get_settings())
    monkeypatch.setattr(live, "capture_command", lambda s, a: [sys.executable, "-c", "import time; time.sleep(60)"])
    capture = live.Capture(sess, context(src), [])
    try:
        lock = locks.named(f"live-capture-{src['id']}")
        deadline = time.monotonic() + 5
        while not lock.held_elsewhere() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert lock.held_elsewhere()
    finally:
        capture.stop()
    assert capture.proc.poll() is not None and not lock.held_elsewhere()


def test_capture_wrapper_can_exit_normally_while_parent_pipe_is_open(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live

    src = source(data)
    sess = live.Session(src, db.get_settings())
    monkeypatch.setattr(live, "capture_command", lambda s, a: [sys.executable, "-c", "pass"])
    capture = live.Capture(sess, context(src), [])
    try:
        assert capture.proc.wait(timeout=5) == 0
        assert "Fatal Python error" not in capture.error()
    finally:
        capture.stop()


def test_capture_wrapper_imports_from_unrelated_cwd_and_preserves_media_cwd(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live

    src = source(data)
    sess = live.Session(src, db.get_settings())
    outside = data / "unrelated-launcher"
    outside.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    cmd = [sys.executable, "-c", "from pathlib import Path; Path('media-cwd.txt').write_text(str(Path.cwd()))"]
    monkeypatch.setattr(live, "capture_command", lambda s, a: cmd)
    capture = live.Capture(sess, context(src), [])
    try:
        assert capture.proc.wait(timeout=5) == 0, capture.error()
        assert (outside / "media-cwd.txt").read_text() == str(outside)
    finally:
        capture.stop()


def test_ended_stream_drains_old_csv_and_posts_once_with_parent_priority(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue

    src = source(data)
    sess = live.Session(src, db.get_settings())
    sess.listfile.write_text("r001_00000.mkv,0,60\nr001_00001.mkv,60,120\n")
    db.update("sources", src["id"], live_status="ended")
    monkeypatch.setattr(live, "process_segment", record_segment)
    monkeypatch.setattr(live, "finalize", lambda s: s.pdir / "source.mkv")
    job = context(src, priority=90)
    assert live.live_capture(job)["minutes"] == 2
    assert live.live_capture(job)["minutes"] == 2
    posts = [row for row in queue.jobs(worker="live_monitor") if row["kind"] == "post_live"]
    assert len(posts) == 1 and posts[0]["priority"] == 90


@pytest.mark.parametrize("reason", ["restart", "paused"])
@pytest.mark.parametrize("returncode", [0, 255])
def test_closing_or_pausing_during_a_turn_keeps_the_broadcast_open(data, monkeypatch, reason, returncode):
    """The recorder stops when the app closes or Autopilot is paused while a turn runs. The broadcast has not
    ended: the turn waits without using an attempt, and the next one starts a new recorder after the saved minutes
    instead of joining the recording and starting the post-live analysis."""
    from clipfoundry import config, db
    from clipfoundry.pipeline.common import read_json
    from clipfoundry.autopilot import live, queue

    made = []

    class Interrupted:
        def __init__(self, sess, job, args, relays=None):
            self.sess, self.job_id, self.host = sess, job.id, job.host
            self.stopped_reason = ""
            self.relays = []
            self.proc = SimpleNamespace(returncode=None)
            self.proc.poll = lambda: self.proc.returncode
            sess.listfile.write_text(f"r{sess.run:03d}_00000.mkv,0,60\n")
            made.append(self)

        def stop(self, why=""):
            self.stopped_reason = self.stopped_reason or why

        def error(self):
            return ""

    def segment_then_stop(sess, name, duration, job):
        record_segment(sess, name, duration, job)
        recorder = made[-1]
        recorder.stop(reason)  # the host's stop_captures or the watchdog, while this turn transcribes
        recorder.proc.returncode = returncode  # the recorder exits (ffmpeg's code after a stop signal, or 0)

    monkeypatch.setattr(live, "Capture", Interrupted)
    monkeypatch.setattr(live, "process_segment", segment_then_stop)
    monkeypatch.setattr(live, "detect", lambda sess, job: None)
    monkeypatch.setattr(live, "input_args", lambda src, settings, **kw: [])
    monkeypatch.setattr(live, "finalize", lambda s: s.pdir / "source.mkv")
    host = SimpleNamespace(_stop=threading.Event(), set_state=lambda *a, **kw: None)
    src = source(data)
    job = context(src, host)
    with pytest.raises(queue.Wait) as waiting:
        live.live_capture(job)
    assert waiting.value.reason == reason
    assert db.fetch("sources", src["id"])["live_status"] != "ended"
    assert not [row for row in queue.jobs(worker="live_monitor") if row["kind"] == "post_live"]
    assert not live._captures
    project = db.fetch("sources", src["id"])["project_id"]
    saved = read_json(config.projects_dir() / project / "live" / "state.json", {})
    assert saved["offset"] == 60 and not saved["capture_complete"]

    # The next turn records again, after the minute that was already saved
    monkeypatch.setattr(live, "process_segment", record_segment)
    with pytest.raises(queue.Wait, match="Watching live"):
        live.live_capture(job)
    assert len(made) == 2 and made[1].sess.run == 2 and made[1].sess.offset == 120


def test_server_wait_survives_recording_restart(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue
    from clipfoundry.pipeline.common import write_json

    src = source(data)
    sess = live.Session(src, db.get_settings())
    write_json(sess.segdir / "server-wait.json", {"until": time.time() + 600})
    attempts = []
    monkeypatch.setattr(live, "input_args", lambda *a, **kw: attempts.append(True) or [])
    with pytest.raises(queue.Wait) as wait:
        live.live_capture(context(src))
    assert wait.value.reason == "server" and wait.value.seconds > 599
    assert not attempts


@pytest.mark.parametrize("returncode", [0, 1])
def test_failed_live_input_does_not_claim_it_ended_or_block_other_source(data, monkeypatch, returncode):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue

    class FailedCapture:
        def __init__(self, sess, job, args, relays=None):
            self.sess, self.job_id, self.host = sess, job.id, job.host
            self.stopped_reason = ""
            self.proc = SimpleNamespace(poll=lambda: returncode, returncode=returncode)
            self.relays = [SimpleNamespace(error=lambda: "The media server refused the stream")]

        def stop(self, reason=""):
            pass

        def error(self):
            return "The media server refused the stream"

    monkeypatch.setattr(live, "Capture", FailedCapture)
    monkeypatch.setattr(live, "input_args", lambda src, settings, **kw: [])
    first, second = source(data, "one"), source(data, "two")
    for src in (first, second):
        with pytest.raises(queue.Retry, match="interrupted"):
            live.live_capture(context(src))
        assert db.fetch("sources", src["id"])["live_status"] != "ended"


@pytest.mark.parametrize("interruption", ["cancel", "priority"])
def test_post_live_retry_keeps_selection_and_completed_output(data, monkeypatch, interruption):
    from clipfoundry import db
    from clipfoundry.autopilot import host, live, queue

    src = source(data)
    project = db.create_project("Live", origin="live", source_id=src["id"])
    pdir = data / "prepared"
    pdir.mkdir()
    prepared = SimpleNamespace(id=project["id"], pdir=pdir)
    chosen = [{"start": 20, "end": 40, "score": 75}, {"start": 50, "end": 70, "score": 80}]
    selections = []
    rendered = []
    competing_jobs = []
    monkeypatch.setattr(live.process, "prepare", lambda *args: prepared)
    monkeypatch.setattr(live.process, "candidate_pool", lambda *args: [])
    monkeypatch.setattr(live.process, "evaluate_select", lambda *a, **kw: selections.append(True) or chosen)

    def create(p, keep, ctx, replace_existing=True, durable=False):
        assert durable and not replace_existing
        rows = []
        for index, moment in enumerate(keep):
            clip_id = f"stable-post-live-{index}"
            rows.append(db.get_clip(clip_id) or db.create_clip(p.id, id=clip_id, start=moment["start"],
                                                              end=moment["end"], status="queued"))
        return rows

    def render(p, rows, ctx, **kw):
        rendered.extend(c["id"] for c in rows)
        for row in rows:
            output = pdir / f"{row['id']}.mp4"
            output.write_bytes(b"verified output")
            db.update_clip(row["id"], status="ready", output_path=str(output))
        if len(rendered) == 1:
            if interruption == "cancel":
                raise queue.Canceled()  # completed bytes were committed, but packaging was interrupted
            higher = source(data, "higher-priority")
            db.update("sources", higher["id"], intake={"priority": 90})
            competing_jobs.append(queue.enqueue("hunt_source", {"source_id": higher["id"]}, priority=90))

    monkeypatch.setattr(live.process, "create_clips", create)
    monkeypatch.setattr(live.process, "render_clips", render)
    monkeypatch.setattr(live, "plan_clips", lambda p, rows, keep, src_id: rows)
    monkeypatch.setattr(live, "store_fingerprint", lambda *args: None)
    row = queue.enqueue("post_live", {"source_id": src["id"], "project_id": project["id"]}, priority=80)
    job = host.Job(row, "test")
    with pytest.raises(queue.Canceled if interruption == "cancel" else queue.Wait) as interrupted:
        live.post_live(job)
    assert db.get_clip("stable-post-live-0")["status"] == "ready"
    assert db.get_clip("stable-post-live-1")["status"] == "queued"
    if interruption == "priority":
        assert interrupted.value.reason == "priority"
        queue.cancel(competing_jobs[0]["id"])
    live.post_live(job)
    assert selections == [True] and rendered == ["stable-post-live-0", "stable-post-live-1"]
    packages = queue.jobs(worker="packager")
    assert len(packages) == 2 and all(p["priority"] == 80 for p in packages)

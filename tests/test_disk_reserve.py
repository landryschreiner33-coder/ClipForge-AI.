"""Low space holds ingestion and live recording without completing or deleting saved owner media."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from clipfoundry import db, netguard
from clipfoundry.autopilot import host, hunter, live, queue
from clipfoundry.pipeline.common import JobContext, read_json


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True})
    yield tmp_path
    live._captures.clear()


def disk(monkeypatch, free):
    monkeypatch.setattr(hunter.shutil, "disk_usage", lambda path: SimpleNamespace(free=free))


class Response:
    status_code = 200
    headers = {"content-type": "video/mp4"}

    def __init__(self):
        self.closed = False
        self.chunks_requested = 0

    def iter_bytes(self, size):
        for _ in range(2):
            self.chunks_requested += 1
            yield b"x" * 100

    def close(self):
        self.closed = True


def test_unknown_length_download_reserves_its_maximum_before_reading(data, monkeypatch):
    response = Response()
    monkeypatch.setattr(netguard, "open_checked", lambda *args, **kwargs: response)
    disk(monkeypatch, hunter.MIN_FREE_DISK + 1)
    dst = data / "saved.mp4"
    dst.write_bytes(b"owner media")
    with pytest.raises(queue.Wait) as wait:
        hunter._http_download("https://example.test/video", dst, JobContext(), {"user_added": 1}, {})
    assert wait.value.reason == "disk"
    assert response.closed and response.chunks_requested == 0
    assert dst.read_bytes() == b"owner media" and not dst.with_suffix(".mp4.part").exists()
    assert db.fetch("action_items", "disk:space", "key")["resolved_at"] is None


def test_download_rechecks_space_before_each_write(data, monkeypatch):
    response = Response()
    monkeypatch.setattr(netguard, "open_checked", lambda *args, **kwargs: response)
    space = iter([20_000_000_000, hunter.MIN_FREE_DISK + 1000, hunter.MIN_FREE_DISK + 50])
    monkeypatch.setattr(hunter.shutil, "disk_usage", lambda path: SimpleNamespace(free=next(space)))
    dst = data / "saved.mp4"
    dst.write_bytes(b"owner media")
    with pytest.raises(queue.Wait) as wait:
        hunter._http_download("https://example.test/video", dst, JobContext(), {"user_added": 1}, {})
    assert wait.value.reason == "disk" and response.chunks_requested == 2 and response.closed
    assert dst.read_bytes() == b"owner media" and not dst.with_suffix(".mp4.part").exists()


def saved_live(data):
    original = data / "own.mkv"
    original.write_bytes(b"owner original")
    src = db.insert("sources", {"platform": "local", "external_id": "own", "title": "Own stream", "kind": "live",
                                "local_path": str(original), "user_added": 1, "status": "ingesting"})
    sess = live.Session(src, db.get_settings())
    part = sess.segdir / "r001_00000.mkv"
    part.write_bytes(b"saved minute")
    sess.segments = [{"name": part.name, "start": 0, "end": 60}]
    sess.offset = 60
    sess.save()
    row = queue.enqueue("live_capture", {"source_id": src["id"]}, priority=80, ref=("source", src["id"]))
    worker_host = SimpleNamespace(_stop=threading.Event(), set_state=lambda *args, **kwargs: None)
    return src, sess, host.Job(row, "test", worker_host)


def test_live_admission_keeps_minutes_and_resumes_after_space_returns(data, monkeypatch):
    src, sess, job = saved_live(data)
    disk(monkeypatch, hunter.MIN_FREE_DISK + 1)
    started = []

    class Recording:
        def __init__(self, current, job, args, relays=None):
            self.sess, self.job_id, self.host = current, job.id, job.host
            self.stopped_reason = ""
            self.proc = SimpleNamespace(poll=lambda: None)
            started.append(self)

        def stop(self, reason=""):
            self.stopped_reason = self.stopped_reason or reason

    monkeypatch.setattr(live, "Capture", Recording)
    monkeypatch.setattr(live, "input_args", lambda *args, **kwargs: [])
    with pytest.raises(queue.Wait) as wait:
        live.live_capture(job)
    assert wait.value.reason == "disk" and not started
    saved = read_json(sess.segdir / "state.json")
    assert saved["offset"] == 60 and not saved["capture_complete"]
    assert (sess.segdir / "r001_00000.mkv").read_bytes() == b"saved minute"
    assert db.fetch("sources", src["id"])["live_status"] != "ended"
    disk(monkeypatch, 30_000_000_000)
    with pytest.raises(queue.Wait) as wait:
        live.live_capture(job)
    assert wait.value.reason == "live" and len(started) == 1 and started[0].sess.offset == 60
    assert db.fetch("action_items", "disk:space", "key")["resolved_at"] is not None


def test_live_watchdog_low_disk_is_a_pause_with_saved_source(data, monkeypatch):
    src, sess, job = saved_live(data)
    disk(monkeypatch, hunter.MIN_FREE_DISK - 1)
    capture = live.Capture.__new__(live.Capture)
    capture.sess, capture.job_id, capture.host = sess, job.id, job.host
    capture.proc = SimpleNamespace(poll=lambda: None)
    capture.stopped = SimpleNamespace(wait=lambda seconds: False)
    reasons = []
    capture.stop = reasons.append
    capture._watch()
    assert reasons == ["disk"]
    after = db.fetch("sources", src["id"])
    assert after["status"] == "ingesting" and after["live_status"] != "ended"
    assert "disk space" in after["status_note"]
    assert (sess.segdir / "r001_00000.mkv").read_bytes() == b"saved minute"


@pytest.mark.parametrize("returncode", [0, 255])
def test_disk_stop_during_live_turn_does_not_finalize(data, monkeypatch, returncode):
    src, sess, job = saved_live(data)
    disk(monkeypatch, 30_000_000_000)
    captures = []

    class Recording:
        def __init__(self, current, job, args, relays=None):
            self.sess, self.job_id, self.host = current, job.id, job.host
            self.stopped_reason = ""
            self.proc = SimpleNamespace(returncode=None, poll=lambda: self.proc.returncode)
            current.listfile.write_text(f"r{current.run:03d}_00000.mkv,0,60\n")
            captures.append(self)

        def stop(self, reason=""):
            self.stopped_reason = self.stopped_reason or reason

    def process_segment(current, name, duration, job):
        current.segments.append({"name": name, "start": current.offset, "end": current.offset + duration})
        current.offset += duration
        current.save()
        captures[-1].stop("disk")
        captures[-1].proc.returncode = returncode

    monkeypatch.setattr(live, "Capture", Recording)
    monkeypatch.setattr(live, "input_args", lambda *args, **kwargs: [])
    monkeypatch.setattr(live, "process_segment", process_segment)
    monkeypatch.setattr(live, "detect", lambda *args: None)
    monkeypatch.setattr(live, "finalize", lambda *args, **kwargs: pytest.fail("Disk pause must not finalize"))
    with pytest.raises(queue.Wait) as wait:
        live.live_capture(job)
    assert wait.value.reason == "disk" and not live._captures
    assert read_json(sess.segdir / "state.json")["offset"] == 120
    assert not read_json(sess.segdir / "state.json")["capture_complete"]
    assert db.fetch("sources", src["id"])["live_status"] != "ended"
    assert not [row for row in queue.jobs(worker="live_monitor") if row["kind"] == "post_live"]


def test_live_assembly_refuses_low_space_without_touching_previous_files(data, monkeypatch):
    src, sess, job = saved_live(data)
    output = sess.pdir / "source.mkv"
    output.write_bytes(b"previous complete recording")
    disk(monkeypatch, hunter.MIN_FREE_DISK)
    monkeypatch.setattr(live, "run_process", lambda *args, **kwargs: pytest.fail("No process should start"))
    with pytest.raises(queue.Wait) as wait:
        live.finalize(sess, cancel=job.cancelled)
    assert wait.value.reason == "disk"
    assert output.read_bytes() == b"previous complete recording"
    assert (sess.segdir / "r001_00000.mkv").read_bytes() == b"saved minute"


def test_canceled_live_assembly_keeps_previous_complete_source(data, monkeypatch):
    import subprocess
    import sys

    from clipfoundry.pipeline import ffmpeg_utils
    from clipfoundry.pipeline.common import Cancelled

    src, sess, job = saved_live(data)
    disk(monkeypatch, 30_000_000_000)
    previous = sess.pdir / "source.mkv"
    previous.write_bytes(b"previous complete source")
    cancelled = threading.Event()
    original = subprocess.Popen
    children = []

    def incomplete(cmd, **kwargs):
        script = "from pathlib import Path; import sys,time; Path(sys.argv[1]).write_bytes(b'partial'); time.sleep(60)"
        proc = original([sys.executable, "-c", script, cmd[-1]], **kwargs)
        children.append(proc)
        return proc

    monkeypatch.setattr(ffmpeg_utils.subprocess, "Popen", incomplete)
    timer = threading.Timer(.3, cancelled.set)
    timer.start()
    try:
        with pytest.raises(Cancelled):
            live.finalize(sess, cancel=cancelled.is_set)
    finally:
        timer.cancel()
        timer.join()
    assert len(children) == 1 and children[0].poll() is not None
    assert previous.read_bytes() == b"previous complete source"
    assert not (sess.pdir / "assembly.tmp.mkv").exists()
    assert (sess.segdir / "r001_00000.mkv").read_bytes() == b"saved minute"
    assert not read_json(sess.segdir / "state.json")["capture_complete"]

"""Live streams added in Missions: recorded and clipped while live, several at once, uploaded during the stream.

Product mode (discovery retired, review on). Platforms are never contacted: the public extractor, the recorder and
YouTube are stand-ins; every rule under test is ClipForge's own.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_autopilot_publish import connect, env, run_publish  # noqa: F401 - fake platforms, never real accounts


@pytest.fixture
def data(tmp_path, monkeypatch):
    from clipfoundry import db, netguard
    from clipfoundry.autopilot import host, live

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(netguard, "resolve", lambda host: [ipaddress.ip_address("8.8.8.8")])
    db.init()
    db.save_settings({"autopilot_enabled": True})
    db.save_account("youtube", tokens={"access_token": "isolated-live-token"}, account_id="UClive-test",
                    display_name="Isolated live channel")
    host.WorkerHost(periodic=False)
    yield tmp_path
    live.stop_captures()
    live._captures.clear()
    live._turns.clear()


def options(**changes):
    from clipfoundry.autopilot import submissions

    shown = submissions.setup()
    assert shown["can_upload"], shown["blocker"]
    return {"auto_upload": True, "account_id": shown["account_id"], "privacy": shown["privacy"],
            "made_for_kids": False, "audience_version": shown["audience"]["group_version"], "reuse_basis": "owned",
            "reuse_statement": "", "agreed": True, **changes}


def add_live(url="https://www.twitch.tv/SomeStreamer", **changes):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    out = submissions.add_link(url, options(**changes), live=True)
    return db.fetch("sources", out["item"]["id"])


def going_live(src, broadcast_id="b1"):
    """What the link check finds once the channel is live."""
    from clipfoundry import db

    db.update("sources", src["id"], kind="live", live_status="live", title="Speedrun night",
              access={"webpage": True})
    return db.fetch("sources", src["id"])


def turn_job(src, host=None, priority=80):
    from clipfoundry.autopilot import host as host_mod, queue

    row = queue.enqueue("live_capture", {"source_id": src["id"]}, priority=priority, idem_key=f"live:{src['id']}",
                        ref=("source", src["id"]), max_attempts=5, timeout_s=24 * 3600)
    return host_mod.Job(queue.get(row["id"]) or row, "test", host)


def record_segment(sess, name, duration, job):
    sess.segments.append({"name": name, "start": sess.offset, "end": sess.offset + duration})
    sess.offset += duration
    sess.save()


class FakeRecorder:
    """A recorder that writes one more minute to the segment list each time `minute()` is called."""

    made: list = []

    def __init__(self, sess, job, args, relays=None):
        self.sess, self.job_id, self.host = sess, job.id, job.host
        self.stopped_reason = ""
        self.relays = relays or []
        self.returncode = None
        self.proc = SimpleNamespace(poll=lambda: self.returncode)
        self.proc.returncode = None
        self.written = 0
        self.err = ""
        FakeRecorder.made.append(self)

    def minute(self, seconds=60.0):
        rows = self.sess.listfile.read_text() if self.sess.listfile.exists() else ""
        start = self.written * seconds
        rows += f"r{self.sess.run:03d}_{self.written:05d}.mkv,{start},{start + seconds}\n"
        self.sess.listfile.write_text(rows)
        self.written += 1

    def exit(self, code=0, err=""):
        self.returncode = code
        self.proc.returncode = code
        self.err = err

    def stop(self, reason=""):
        self.stopped_reason = self.stopped_reason or reason
        if self.returncode is None:
            self.exit(255)

    def error(self):
        return self.err


@pytest.fixture
def recorder(monkeypatch):
    from clipfoundry.autopilot import live

    FakeRecorder.made = []
    monkeypatch.setattr(live, "Capture", FakeRecorder)
    monkeypatch.setattr(live, "process_segment", record_segment)
    monkeypatch.setattr(live, "detect", lambda sess, job: None)
    monkeypatch.setattr(live, "finalize", lambda s, **kw: _joined_file(s))
    monkeypatch.setattr(live, "probe", lambda *a, **kw: {"has_video": True, "has_audio": True, "duration": 120.0,
                                                         "width": 1280, "height": 720, "fps": 30})
    return FakeRecorder


def _joined_file(sess):
    from clipfoundry import db

    out = sess.pdir / "source.mkv"
    out.write_bytes(b"joined recording " + str(len(sess.segments)).encode())
    db.update_project(sess.project["id"], source_path=str(out), source_filename=out.name, duration=sess.offset)
    return out


def broadcasts(monkeypatch, *ids):
    """input_args stand-in: each new recorder sees the next broadcast id (or raises what it is given)."""
    from clipfoundry.autopilot import live

    calls = []

    def fake(src, settings, public_relays=None, byte_budget=None, on_retry=None, broadcast=None):
        current = ids[min(len(calls), len(ids) - 1)]
        calls.append(current)
        if isinstance(current, BaseException) or (isinstance(current, type) and issubclass(current, BaseException)):
            raise current
        if broadcast is not None and current is not None:
            broadcast.update({"id": current, "title": f"Broadcast {current}", "url": src.get("url", "")})
        return []

    monkeypatch.setattr(live, "input_args", fake)
    return calls


def drain(job):
    """Turns that only transcribe the minutes still waiting (one per turn), then the turn after them."""
    from clipfoundry.autopilot import live, queue

    for _ in range(20):
        with pytest.raises(queue.Wait) as waiting:
            live.live_capture(job)
        if waiting.value.reason != "live" or "Watching" not in waiting.value.message:
            return waiting.value
    raise AssertionError("the turns never moved on")


def post_live_jobs():
    from clipfoundry.autopilot import queue

    return [row for row in queue.jobs(limit=1000) if row["kind"] == "post_live"]


# ------------------------------------------------------------------ adding a live link
def test_live_links_are_saved_with_live_consent_and_unsafe_schemes_are_refused(data):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, submissions

    src = add_live("https://www.twitch.tv/SomeStreamer")
    row = submissions.for_source(src)
    assert src["platform"] == "url" and src["intake"]["live_requested"] is True
    assert "record it while it is live" in row["text"] and "during the stream" in row["text"]
    assert row["settings"]["auto_upload"] and not row["settings"]["bound_project_id"]
    assert [j["kind"] for j in db.select("worker_jobs")] == ["identify_link"]

    page = intake.canonical_url("https://youtube.com/@Some.Channel/live")
    assert page["url"] == "https://www.youtube.com/@some.channel/live" and page["kind"] == "live"
    local = submissions.add_link("https://www.youtube.com/@Some.Channel/live", {"auto_upload": False}, live=True)
    assert "record it while it is live" in submissions.for_source(local["item"])["text"]
    for unsafe in ("rtmp://203.0.113.5/live/key", "srt://203.0.113.5:9000", "rtsp://203.0.113.5/cam"):
        with pytest.raises(ValueError):
            submissions.add_link(unsafe, options(), live=True)
    assert len(db.select("sources")) == 2


def test_channel_pages_and_offline_channels_wait_for_the_stream(data, monkeypatch):
    from clipfoundry import media_import
    from clipfoundry.autopilot import intake

    for url in ("https://www.twitch.tv/name", "https://kick.com/name", "https://www.youtube.com/@name/live",
                "https://m.twitch.tv/name/"):
        assert intake.channel_live_page(url), url
    for url in ("https://www.twitch.tv/videos/123", "https://www.twitch.tv/directory", "https://www.twitch.tv/a/b",
                "https://www.youtube.com/watch?v=abcdefghijk", "https://example.com/name"):
        assert not intake.channel_live_page(url), url

    def offline(url):
        raise media_import.MediaUnavailable(code="not_live")

    monkeypatch.setattr(media_import, "inspect_video", offline)
    assert intake._inspect("https://www.twitch.tv/name") == {"kind": "live", "live_status": "upcoming"}
    # A channel page still showing its last (ended) broadcast is not that recording: wait for the next one.
    monkeypatch.setattr(media_import, "inspect_video", lambda url: {"kind": "recorded", "title": "Old VOD"})
    assert intake._inspect("https://kick.com/name") == {"kind": "live", "live_status": "upcoming"}
    assert intake._inspect("https://example.com/v.mp4") == {"kind": "recorded", "title": "Old VOD"}


def test_user_not_live_is_its_own_answer_not_a_word_match():
    from yt_dlp.utils import DownloadError, UserNotLive

    from clipfoundry import media_import

    assert media_import.classify(UserNotLive())[0] == "not_live"
    assert media_import.unavailable(UserNotLive()).code == "not_live"
    assert media_import.classify(DownloadError("This channel is not currently live"))[0] != "not_live"


def test_submitted_live_link_routes_to_waiting_then_recording(data, monkeypatch):
    from clipfoundry import db, media_import
    from clipfoundry.autopilot import host, queue

    src = add_live()
    answers = [{"kind": "live", "live_status": "upcoming"}]
    monkeypatch.setattr(media_import, "inspect_video", lambda url: answers[-1])
    claim = queue.claim("source_scout", "test")
    with pytest.raises(queue.Wait) as waiting:
        host.HANDLERS["identify_link"](host.Job(claim, "test"))
    assert waiting.value.reason == "stream_start"
    assert db.fetch("sources", src["id"])["live_status"] == "upcoming"
    assert not [j for j in db.select("worker_jobs") if j["kind"] == "live_capture"]

    answers.append({"kind": "live", "live_status": "live", "title": "Speedrun night"})
    out = host.HANDLERS["identify_link"](host.Job(claim, "test"))
    capture = db.fetch("worker_jobs", out["job_id"])
    assert capture["kind"] == "live_capture" and capture["idem_key"] == f"live:{src['id']}"
    assert capture["worker"] == "live_monitor" and capture["timeout_s"] == 24 * 3600

    # A stream that never starts does not keep a submitted input waiting forever.
    stale = add_live("https://kick.com/othername")
    db.update("sources", stale["id"], intake={**stale["intake"], "added_at": time.time() - 25 * 3600})
    answers.append({"kind": "live", "live_status": "upcoming"})
    job = queue.enqueue("identify_link", {"source_id": stale["id"]}, idem_key=f"identify:{stale['id']}")
    with pytest.raises(queue.Fail, match="did not start within a day"):
        host.HANDLERS["identify_link"](host.Job(queue.get(job["id"]), "test"))


# ------------------------------------------------------------------ the upload permission while recording
def test_live_grant_binds_to_the_recording_project_then_to_the_joined_recording(data):
    from clipfoundry import db
    from clipfoundry.autopilot import live, submissions

    src = going_live(add_live())
    sess = live.Session(src, db.get_settings())
    row = submissions.for_source(src)
    cfg = row["settings"]
    assert cfg["live"] is True and cfg["bound_project_id"] == sess.project["id"]
    assert not cfg["source_path"] and not cfg["source_sha256"]
    assert submissions.problem(db.fetch("sources", src["id"])) == ""  # covered while recording
    with pytest.raises(ValueError):  # only the recorder binds a live input's recording
        submissions.bind_project(db.fetch("sources", src["id"]), sess.project)
    assert submissions.for_source(src)["settings"] == cfg
    other = db.create_project("Someone else's", origin="live", source_id=src["id"])
    with pytest.raises(ValueError, match="another project"):
        submissions.bind_live(db.fetch("sources", src["id"]), other)

    # The stream ended: the joined recording is bound before the full-recording analysis cuts clips from it.
    joined = sess.pdir / "source.mkv"
    joined.write_bytes(b"the joined recording")
    db.update_project(sess.project["id"], source_path=str(joined))
    submissions.bind_live_recording(db.fetch("sources", src["id"]), db.get_project(sess.project["id"]), joined)
    cfg = submissions.for_source(src)["settings"]
    assert cfg["source_path"] == str(joined) and cfg["source_sha256"]
    assert submissions.problem(db.fetch("sources", src["id"])) == ""
    joined.write_bytes(b"changed afterwards")
    assert "bytes changed" in submissions.problem(db.fetch("sources", src["id"]))

    # A recorded video's grant never becomes a live grant.
    import io

    video = submissions.add_file(io.BytesIO(b"an uploaded video"), "talk.mp4", options())
    file_src = db.fetch("sources", video["item"]["id"])
    db.update("sources", file_src["id"], kind="live")
    project = db.create_project("file", origin="live", source_id=file_src["id"])
    with pytest.raises(ValueError, match="submitted as a file"):
        submissions.bind_live(db.fetch("sources", file_src["id"]), project)


def test_live_clip_is_approved_and_uploaded_while_the_stream_is_still_recording(env, monkeypatch):
    from quality_stub import passed_report
    from test_autopilot_scheduler import make_clip

    from clipfoundry import db, netguard
    from clipfoundry.autopilot import live, scheduler, submissions

    google, tiktok, tmp = env
    connect(google, tiktok)
    db.save_settings({"autopilot_input_mode": "submitted", "autopilot_review_before_publish": True,
                      "autopilot_tiktok": False, "autopilot_youtube": True, "autopilot_enabled": True})
    monkeypatch.setattr(netguard, "resolve", lambda host: [ipaddress.ip_address("8.8.8.8")])
    src = going_live(add_live())
    sess = live.Session(src, db.get_settings())
    clip = make_clip(tmp, "The clutch play that won the run", 90, source=src)
    db.update_clip(clip["id"], project_id=sess.project["id"], score_source="Live analysis")
    db.execute("DELETE FROM projects WHERE id = ?", (clip["project_id"],))
    passed_report(db.get_clip(clip["id"]))
    assert db.get_project(sess.project["id"])["origin"] == "live"
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 1
    item = db.select("scheduled_publications", "clip_id = ?", (clip["id"],))[0]
    assert item["status"] == "approved" and item["approval"]["by"] == "submission"
    assert submissions.still_covers(item)
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "published", after
    uploaded = google.videos[db.get_publication(after["publication_id"])["remote_id"]]
    assert uploaded["bytes"] == Path(clip["output_path"]).read_bytes()
    assert db.fetch("sources", src["id"])["live_status"] == "live"  # uploaded during the stream

    # Another stream's grant never covers this stream's clips.
    second = going_live(add_live("https://kick.com/otherstreamer"))
    other = live.Session(second, db.get_settings())
    assert submissions.for_source(second)["settings"]["bound_project_id"] == other.project["id"]
    assert not submissions.still_covers({**after, "source_id": second["id"]})


# ------------------------------------------------------------------ Stop recording
def test_stop_recording_finishes_a_running_recorder_and_keeps_its_minutes(data, recorder, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, live, queue

    broadcasts(monkeypatch, "b1")
    src = going_live(add_live())
    host = SimpleNamespace(_stop=threading.Event(), set_state=lambda *a, **kw: None)
    job = turn_job(src, host)
    with pytest.raises(queue.Wait, match="Watching live"):
        live.live_capture(job)
    rec = recorder.made[-1]
    rec.minute()
    rec.minute()
    with pytest.raises(queue.Wait, match="Watching live"):
        live.live_capture(job)
    view = intake.item(db.fetch("sources", src["id"]))
    assert view["can_finish"] and not view["finishing"]

    intake.action(src["id"], "finish")
    assert intake.finish_requested(src["id"])
    view = intake.item(db.fetch("sources", src["id"]))
    assert view["finishing"] and not view["can_finish"]
    with pytest.raises(ValueError):
        intake.action(src["id"], "finish")
    result = live.live_capture(job)
    assert rec.stopped_reason == "finish" and result["minutes"] == 2
    after = db.fetch("sources", src["id"])
    assert after["live_status"] == "stopped" and after["status"] == "analyzing"
    assert after["status_note"].startswith("Stopped by you after 2 min")
    posts = post_live_jobs()
    assert len(posts) == 1 and posts[0]["worker"] == "analyzer"


def test_stop_recording_before_anything_was_recorded_ends_the_input(data, recorder, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, live, queue

    calls = broadcasts(monkeypatch, live.StreamOffline)
    src = going_live(add_live())
    job = turn_job(src)
    with pytest.raises(queue.Wait) as waiting:
        live.live_capture(job)
    assert waiting.value.reason == "offline"
    assert db.fetch("sources", src["id"])["live_status"] == "upcoming"
    assert intake.item(db.fetch("sources", src["id"]))["can_finish"]
    intake.action(src["id"], "finish")
    from clipfoundry.autopilot.host import MANUAL_PRIORITY

    assert db.fetch("worker_jobs", job.id)["priority"] == MANUAL_PRIORITY
    result = live.live_capture(job)
    assert result["minutes"] == 0 and len(calls) == 1  # the finishing turn never contacts the platform
    after = db.fetch("sources", src["id"])
    assert after["status"] == "canceled" and after["live_status"] == "stopped"
    assert "before anything was recorded" in after["status_note"]
    assert not post_live_jobs()


def test_stop_recording_is_refused_when_nothing_records(data):
    from clipfoundry import db
    from clipfoundry.autopilot import intake

    src = add_live()
    with pytest.raises(ValueError, match="Nothing is being recorded"):
        intake.action(src["id"], "finish")
    assert not intake.finish_requested(src["id"])
    assert not intake.item(db.fetch("sources", src["id"]))["can_finish"]


# ------------------------------------------------------------------ the next broadcast is a new input
def test_channel_link_can_be_added_again_only_after_its_broadcast_finished(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, queue, submissions

    first = add_live("https://www.twitch.tv/SomeStreamer")
    with pytest.raises(ValueError, match="already added"):
        add_live("https://twitch.tv/somestreamer")
    db.update("sources", first["id"], kind="live", live_status="ended", status="finished")
    with pytest.raises(ValueError, match="already added"):
        add_live("https://twitch.tv/somestreamer")  # its link check is still queued
    db.execute("UPDATE worker_jobs SET status = 'completed'")
    second = add_live("https://twitch.tv/somestreamer")
    assert second["id"] != first["id"]
    assert second["external_id"] == f"{first['external_id']}:{first['id'][:16]}"
    assert db.fetch("sources", first["id"])["intake"]["superseded_by"] == second["id"]
    assert submissions.for_source(second)["id"] != submissions.for_source(first)["id"]
    with pytest.raises(ValueError, match="added again"):
        intake.action(first["id"], "retry")

    db.update("sources", second["id"], kind="live", live_status="stopped", status="finished")
    db.execute("UPDATE worker_jobs SET status = 'completed'")
    third = add_live("https://www.twitch.tv/SomeStreamer")
    assert third["external_id"] == f"{first['external_id']}:{second['id'][:16]}"

    # Two adds at the same moment both pick the same identity: one of them is refused, never two recordings.
    db.update("sources", third["id"], kind="live", live_status="ended", status="finished")
    db.execute("UPDATE worker_jobs SET status = 'completed'")
    real = submissions._finished_broadcast
    seen = {}

    def snapshot(source):
        seen.setdefault(source["id"], real(source))
        return seen[source["id"]]

    monkeypatch.setattr(submissions, "_finished_broadcast", snapshot)
    add_live("https://www.twitch.tv/SomeStreamer")
    monkeypatch.setattr(submissions.db, "select", _without_newest(submissions.db.select, third["created_at"]))
    with pytest.raises(ValueError, match="already added"):
        add_live("https://www.twitch.tv/SomeStreamer")
    assert db.scalar("SELECT COUNT(*) FROM sources") == 4
    assert db.scalar("SELECT COUNT(*) FROM source_submissions") == 4  # no grant without its own input


def _without_newest(select, after):
    def older(table, *args, **kwargs):
        rows = select(table, *args, **kwargs)
        return [r for r in rows if table != "sources" or r.get("created_at", 0) <= after]
    return older


def test_recorded_videos_are_still_refused_twice(data):
    from clipfoundry.autopilot import submissions

    submissions.add_link("https://www.youtube.com/watch?v=abcdefghijk", options())
    with pytest.raises(ValueError, match="already added"):
        submissions.add_link("https://youtu.be/abcdefghijk", options())


# ------------------------------------------------------------------ offline, reconnects, other broadcasts
def test_channel_going_offline_mid_stream_waits_then_finishes(data, recorder, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue

    calls = broadcasts(monkeypatch, "b1", live.StreamOffline)
    src = going_live(add_live())
    host = SimpleNamespace(_stop=threading.Event(), set_state=lambda *a, **kw: None)
    job = turn_job(src, host)
    with pytest.raises(queue.Wait, match="Watching live"):
        live.live_capture(job)
    rec = recorder.made[-1]
    for _ in range(3):
        rec.minute()
    rec.exit(1, "Connection reset by peer")
    assert drain(job).reason == "reconnect"  # a dropped connection after recording uses no attempt
    with pytest.raises(queue.Wait) as offline:
        live.live_capture(job)
    assert offline.value.reason == "offline" and offline.value.seconds == 60
    assert db.fetch("sources", src["id"])["live_status"] == "live"  # a few minutes' grace
    monkeypatch.setattr(live, "OFFLINE_GRACE_SECONDS", 0)
    with pytest.raises(queue.Wait, match="finishing the recording"):
        live.live_capture(job)
    assert db.fetch("sources", src["id"])["live_status"] == "ended"
    result = live.live_capture(job)
    assert result["minutes"] == 3 and len(post_live_jobs()) == 1
    assert db.fetch("sources", src["id"])["status_note"].startswith("Live ended after 3 min")
    assert len(calls) == 3


def test_a_different_broadcast_ends_the_recording_instead_of_being_appended(data, recorder, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue

    calls = broadcasts(monkeypatch, "b1", "b2")
    src = going_live(add_live())
    host = SimpleNamespace(_stop=threading.Event(), set_state=lambda *a, **kw: None)
    job = turn_job(src, host)
    with pytest.raises(queue.Wait, match="Watching live"):
        live.live_capture(job)
    rec = recorder.made[-1]
    rec.minute()
    rec.minute()
    rec.exit(1, "Connection reset by peer")
    for _ in range(2):
        with pytest.raises(queue.Wait):
            live.live_capture(job)
    with pytest.raises(queue.Wait, match="Finishing the recorded broadcast"):
        live.live_capture(job)
    assert len(recorder.made) == 1 and calls == ["b1", "b2"]
    after = db.fetch("sources", src["id"])
    assert after["live_status"] == "ended" and "different broadcast" in after["status_note"]
    assert live.live_capture(job)["minutes"] == 2
    assert len(post_live_jobs()) == 1


def test_a_long_gap_without_a_broadcast_id_is_not_assumed_to_be_the_same_broadcast(data, recorder, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue

    broadcasts(monkeypatch, None)
    src = going_live(add_live())
    host = SimpleNamespace(_stop=threading.Event(), set_state=lambda *a, **kw: None)
    job = turn_job(src, host)
    with pytest.raises(queue.Wait, match="Watching live"):
        live.live_capture(job)
    rec = recorder.made[-1]
    rec.minute()
    rec.exit(1, "Connection reset by peer")
    with pytest.raises(queue.Wait):
        live.live_capture(job)
    sess = live.Session(db.fetch("sources", src["id"]), db.get_settings())
    sess.alive_at = time.time() - live.OFFLINE_GRACE_SECONDS - 5  # the app was closed for a while
    sess.save()
    with pytest.raises(queue.Wait, match="Finishing the recorded broadcast"):
        live.live_capture(job)
    assert db.fetch("sources", src["id"])["live_status"] == "ended"


def test_relay_size_limit_and_running_out_of_attempts_finish_instead_of_failing(data, recorder, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue

    relay = SimpleNamespace(reached_limit=lambda: True, error=lambda: "The stream reached the download size limit",
                            close=lambda: None)
    monkeypatch.setattr(live, "input_args", lambda src, settings, public_relays=None, **kw:
                        public_relays.append(relay) or [])
    src = going_live(add_live())
    host = SimpleNamespace(_stop=threading.Event(), set_state=lambda *a, **kw: None)
    job = turn_job(src, host)
    with pytest.raises(queue.Wait):
        live.live_capture(job)
    rec = recorder.made[-1]
    rec.minute()
    rec.exit(1, "download size limit")
    result = live.live_capture(job)
    assert result["minutes"] == 1
    after = db.fetch("sources", src["id"])
    assert after["live_status"] == "stopped" and after["status_note"].startswith("Recording limit reached")

    # A recorder that keeps failing after its minutes were saved: finished with what it has, never left unjoined.
    other = going_live(add_live("https://kick.com/otherstreamer"))
    broadcasts(monkeypatch, "k1")
    job = turn_job(other, host)
    with pytest.raises(queue.Wait):
        live.live_capture(job)
    rec = recorder.made[-1]
    rec.minute()
    rec.exit(1, "Server returned 500")
    assert drain(job).reason == "reconnect"
    with pytest.raises(queue.Wait, match="Watching live"):
        live.live_capture(job)  # a new recorder after the saved minute
    again = recorder.made[-1]
    assert again is not rec and again.sess.run == 2
    again.exit(1, "Server returned 500")  # fails before recording anything new
    db.execute("UPDATE worker_jobs SET attempts = max_attempts WHERE id = ?", (job.id,))
    job.row = db.fetch("worker_jobs", job.id)
    with pytest.raises(queue.Wait, match="Finishing what was recorded"):
        live.live_capture(job)
    assert db.fetch("sources", other["id"])["live_status"] == "ended"
    assert live.live_capture(job)["minutes"] == 1


# ------------------------------------------------------------------ several streams, GPU, failed moments
def test_live_minute_waits_for_the_gpu_without_stopping_the_recording(data, monkeypatch):
    from clipfoundry import db, gpu
    from clipfoundry.autopilot import live, queue
    from clipfoundry.autopilot.host import Job

    src = going_live(add_live())
    sess = live.Session(src, db.get_settings())
    seg = sess.segdir / "r001_00000.mkv"
    seg.write_bytes(b"minute")
    monkeypatch.setattr(live, "probe", lambda *a, **kw: {"has_audio": True, "has_video": True, "duration": 60.0})
    monkeypatch.setattr(live, "extract_audio", lambda path, wav, duration, cancel=None: Path(wav).write_bytes(b"w"))
    monkeypatch.setattr(live, "loudness_envelope", lambda wav: {"db": [-20.0] * 600})

    class Busy:
        def __init__(self, *args, max_wait_s=None, **kwargs):
            assert max_wait_s == live.GPU_WAIT_SECONDS

        def __enter__(self):
            raise gpu.GpuBusy("another stream is transcribing")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(gpu.manager, "heavy", Busy)
    row = queue.enqueue("live_capture", {"source_id": src["id"]})
    with pytest.raises(queue.Wait) as waiting:
        live.process_segment(sess, seg.name, 60.0, Job(queue.get(row["id"]), "test"))
    assert waiting.value.reason == "gpu" and waiting.value.seconds == 10
    assert not sess.segments and sess.offset == 0  # the minute stays pending
    assert not (sess.segdir / "r001_00000.wav").exists()


def test_unreadable_minute_is_kept_on_the_timeline_and_recording_continues(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue
    from clipfoundry.autopilot.host import Job

    src = going_live(add_live())
    sess = live.Session(src, db.get_settings())
    seg = sess.segdir / "r001_00000.mkv"
    seg.write_bytes(b"broken")

    def unreadable(*args, **kwargs):
        raise RuntimeError("Invalid data found when processing input")

    monkeypatch.setattr(live, "probe", unreadable)
    row = queue.enqueue("live_capture", {"source_id": src["id"]})
    live.process_segment(sess, seg.name, 60.0, Job(queue.get(row["id"]), "test"))
    assert sess.offset == 60.0 and sess.untranscribed == [[0.0, 60.0]]


def test_failed_moment_is_skipped_on_later_minutes(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue
    from clipfoundry.autopilot.host import Job
    from clipfoundry.pipeline import candidates as cand_mod

    src = going_live(add_live())
    sess = live.Session(src, db.get_settings())
    sess.offset = 120.0
    sess.words = [{"w": w, "start": i * 0.5, "end": i * 0.5 + 0.4}
                  for i, w in enumerate(("Okay. This is it. Watch this jump. Nobody does this. Wow. " * 8).split())]
    row = queue.enqueue("live_capture", {"source_id": src["id"]})
    job = Job(queue.get(row["id"]), "test")
    monkeypatch.setattr(live.deep, "optimize_bounds", lambda r, sents, loud, offset: {"start": 10.0, "end": 40.0})
    monkeypatch.setattr(live.postpack, "generate", lambda *a, **kw: {"title": "Watch this jump", "hashtags": []})
    monkeypatch.setattr(live.virality, "summary", lambda r: {"factors": {}, "subscores": {}})
    monkeypatch.setattr(live.scoring, "reason_text", lambda r: "Strong moment")

    def bad_segment(*args, **kwargs):
        raise RuntimeError("Invalid data found when processing input")

    monkeypatch.setattr(live, "_window_file", bad_segment)
    found = {"r": {"s0": 0, "s1": 1, "viral_potential": 80.0}, "loud": None,
             "sents": [{"text": "Watch this jump."}, {"text": "Nobody does this."}]}
    clip = live.make_live_clip(sess, found, job)
    assert db.get_clip(clip["id"])["status"] == "error"
    assert sess.skipped == [[10.0, 40.0]]
    assert live.Session(db.fetch("sources", src["id"]), db.get_settings()).skipped == [[10.0, 40.0]]

    class Considered(Exception):
        pass

    def considered(*args, **kwargs):
        raise Considered()

    monkeypatch.setattr(cand_mod, "find_candidates", lambda *a, **kw: [{"start": 12.0, "end": 38.0, "s0": 0, "s1": 2}])
    monkeypatch.setattr(live.virality, "variants", considered)
    assert live.detect(sess, job) is None  # the failed moment is not tried again on every later minute
    sess.skipped = []
    with pytest.raises(Considered):
        live.detect(sess, job)


def test_live_lanes_run_several_streams_at_once_and_one_job_never_twice(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue

    assert queue.WORKER_LANES["live_monitor"] >= 3
    assert queue.KIND_WORKER["post_live"] == "analyzer" and queue.KIND_WORKER["live_capture"] == "live_monitor"
    running, release = [], threading.Event()
    both = threading.Barrier(3, timeout=20)

    def turn(job):
        running.append((job.payload["source_id"], threading.current_thread().name))
        both.wait()
        release.wait(20)
        return {"message": "done"}

    monkeypatch.setitem(host.HANDLERS, "live_capture", turn)
    for name in ("one", "two"):
        queue.enqueue("live_capture", {"source_id": name}, idem_key=f"live:{name}", priority=80)
    worker_host = host.WorkerHost(workers=["live_monitor"], poll=0.05, periodic=False)
    assert worker_host.start()
    try:
        both.wait()  # both streams are inside their turn at the same time
        assert sorted(s for s, _ in running) == ["one", "two"]
        assert len({t for _, t in running}) == 2
        assert db.fetch("worker_state", "live_monitor", "name")["status"] == "working"
        release.set()
        deadline = time.time() + 20
        while time.time() < deadline and any(j["status"] != "completed" for j in queue.jobs(limit=100)):
            time.sleep(0.05)
        assert all(j["status"] == "completed" for j in queue.jobs(limit=100))
    finally:
        release.set()
        worker_host.stop()

    # A job claimed again while an earlier turn of it still runs in this process waits instead of running twice.
    row = queue.enqueue("live_capture", {"source_id": "three"}, idem_key="live:three")
    first = queue.claim("live_monitor", "lane-a")
    worker_host = host.WorkerHost(workers=["live_monitor"], periodic=False)
    worker_host._running[row["id"]] = host.Job(first, "lane-a", worker_host)
    db.execute("UPDATE worker_jobs SET status = 'queued', lease_owner = '' WHERE id = ?", (row["id"],))
    second = queue.claim("live_monitor", "lane-b")
    calls = []
    monkeypatch.setitem(host.HANDLERS, "live_capture", lambda job: calls.append(job) or {})
    worker_host._run("live_monitor", second)
    assert not calls
    after = queue.get(row["id"])
    assert after["status"] == "waiting" and after["wait_reason"] == "busy"


def test_one_stream_never_runs_two_turns_at_once(data, monkeypatch):
    from clipfoundry.autopilot import live, queue

    entered, release = threading.Event(), threading.Event()

    def slow_turn(job):
        entered.set()
        release.wait(10)
        return {"message": "done"}

    monkeypatch.setattr(live, "_live_turn", slow_turn)
    src = add_live()
    job = turn_job(src)
    first = threading.Thread(target=live.live_capture, args=(job,))
    first.start()
    assert entered.wait(5)
    with pytest.raises(queue.Wait) as waiting:
        live.live_capture(job)
    assert waiting.value.reason == "live"
    release.set()
    first.join(5)


# ------------------------------------------------------------------ Stop all jobs is a hold
def test_stop_all_holds_live_streams_and_resume_continues_them(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue, routes, state

    recording = going_live(add_live())
    waiting = add_live("https://kick.com/otherstreamer")
    analyzing = going_live(add_live("https://www.youtube.com/@third/live"))
    capture = queue.enqueue("live_capture", {"source_id": recording["id"]}, idem_key=f"live:{recording['id']}",
                            ref=("source", recording["id"]), priority=80)
    post = queue.enqueue("post_live", {"source_id": analyzing["id"], "project_id": "p"},
                         idem_key=f"post_live:{analyzing['id']}", ref=("source", analyzing["id"]))
    db.execute("UPDATE worker_jobs SET status = 'completed' WHERE kind = 'identify_link' AND "
               "json_extract(payload, '$.source_id') != ?", (waiting["id"],))
    old = db.insert("sources", {"platform": "url", "external_id": "old-discovered", "kind": "live",
                                "url": "https://www.twitch.tv/old", "status": "queued"})
    discovered = queue.enqueue("live_capture", {"source_id": old["id"]}, idem_key=f"live:{old['id']}")
    monkeypatch.setattr("clipfoundry.jobs.worker.cancel_all", lambda: 0)
    monkeypatch.setattr("clipfoundry.publish.jobs.worker.cancel_all", lambda: 0)
    routes.stop_all()
    assert state.paused()
    held = [row for row in db.select("worker_jobs") if row["status"] != "completed"]
    assert len(held) == 4
    assert all(row["status"] == "canceled" and row["wait_reason"] == queue.STOP_ALL for row in held)
    routes.resume()
    after = {row["id"]: row["status"] for row in db.select("worker_jobs")}
    assert after[capture["id"]] == after[post["id"]] == "queued"
    assert [row["status"] for row in db.select("worker_jobs") if row["kind"] == "identify_link" and
            row["payload"]["source_id"] == waiting["id"]] == ["queued"]
    assert after[discovered["id"]] == "canceled"  # only inputs you added in Live streams continue by themselves


def test_stop_all_during_a_running_turn_is_never_left_unclaimable(data, monkeypatch):
    """A turn that hands back its slot (a wait) after Stop all jobs was pressed is held, not parked forever."""
    from clipfoundry import db
    from clipfoundry.autopilot import host, live, queue, routes

    src = going_live(add_live())
    db.execute("UPDATE worker_jobs SET status = 'completed'")
    monkeypatch.setattr("clipfoundry.jobs.worker.cancel_all", lambda: 0)
    monkeypatch.setattr("clipfoundry.publish.jobs.worker.cancel_all", lambda: 0)

    def turn(job):
        routes.stop_all()  # pressed while this turn transcribes a minute
        raise queue.Wait("live", 2, "Watching live")

    monkeypatch.setitem(host.HANDLERS, "live_capture", turn)
    queue.enqueue("live_capture", {"source_id": src["id"]}, idem_key=f"live:{src['id']}", priority=80)
    worker_host = host.WorkerHost(workers=["live_monitor"], periodic=False)
    claim = queue.claim("live_monitor", "lane")
    worker_host._run("live_monitor", claim)
    row = queue.get(claim["id"])
    assert row["status"] == "canceled" and row["wait_reason"] == queue.STOP_ALL
    routes.resume()
    assert queue.get(claim["id"])["status"] == "queued" and not queue.get(claim["id"])["cancel_requested"]

    # An ordinary Cancel during a turn wins over the turn's wait in the same way.
    def canceled_turn(job):
        queue.cancel(job.id)
        raise queue.Wait("live", 2, "Watching live")

    monkeypatch.setitem(host.HANDLERS, "live_capture", canceled_turn)
    claim = queue.claim("live_monitor", "lane")
    worker_host._run("live_monitor", claim)
    assert queue.get(claim["id"])["status"] == "canceled"


def test_watchdog_holds_the_recording_when_stop_all_is_pressed(data):
    from clipfoundry import db
    from clipfoundry.autopilot import live, state

    src = going_live(add_live())
    job = turn_job(src)
    capture = live.Capture.__new__(live.Capture)
    capture.sess = SimpleNamespace(src=src)
    capture.job_id = job.id
    capture.host = SimpleNamespace(_stop=threading.Event())
    capture.proc = SimpleNamespace(poll=lambda: None)
    capture.stopped = SimpleNamespace(wait=lambda seconds: False)
    reasons = []
    capture.stop = reasons.append
    state.put("emergency_stop", True)
    capture._watch()
    assert reasons == ["paused"]
    after = db.fetch("sources", src["id"])
    assert after["status"] == "queued" and "Stop all jobs" in after["status_note"]

    state.put("emergency_stop", False)
    state.put(f"live_finish:{src['id']}", {"at": time.time()})
    reasons.clear()
    capture.sess = SimpleNamespace(src=src, segdir=Path(data), settings={})
    capture._watch()
    assert reasons == ["finish"]


# ------------------------------------------------------------------ after the stream
def test_approved_or_uploading_live_clip_is_never_replaced_by_the_post_live_cut(data):
    from clipfoundry import db
    from clipfoundry.autopilot import live

    project = db.create_project("live", origin="live", status="ready")
    clip = db.create_clip(project["id"], start=0, end=20, status="ready", score=60)
    item = db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "youtube", "status": "approved"})
    assert live._kept(clip["id"]) and not live._published(clip["id"])
    db.update("scheduled_publications", item["id"], status="awaiting_approval")
    assert not live._kept(clip["id"])

    # Compare-and-set: a post the scheduler started publishing meanwhile keeps its status.
    real = db.select

    def started_meanwhile(table, *args, **kwargs):
        rows = real(table, *args, **kwargs)
        if table == "scheduled_publications":
            db.execute("UPDATE scheduled_publications SET status = 'publishing' WHERE id = ?", (item["id"],))
        return rows

    db.select = started_meanwhile
    try:
        live.supersede(clip, "Replaced by the post-live analysis")
    finally:
        db.select = real
    assert db.fetch("scheduled_publications", item["id"])["status"] == "publishing"


def test_second_finishing_turn_reuses_the_joined_recording(data, recorder, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live, submissions

    joins = []
    monkeypatch.setattr(live, "finalize", lambda s, **kw: joins.append(1) or _joined_file(s))
    src = going_live(add_live())
    sess = live.Session(src, db.get_settings())
    sess.listfile.write_text("r001_00000.mkv,0,60\n")
    db.update("sources", src["id"], live_status="ended")
    job = turn_job(src)
    live.live_capture(job)
    joined = Path(db.get_project(sess.project["id"])["source_path"])
    sha_before = joined.read_bytes()
    live.live_capture(job)
    assert len(joins) == 1 and joined.read_bytes() == sha_before
    assert len(post_live_jobs()) == 1
    assert submissions.problem(db.fetch("sources", src["id"])) == ""


def test_live_streams_list_shows_each_stream_with_its_progress(data, recorder, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.autopilot import live, queue

    broadcasts(monkeypatch, "b1")
    one = going_live(add_live())
    two = add_live("https://kick.com/otherstreamer", auto_upload=False)
    submissions_video = __import__("clipfoundry.autopilot.submissions", fromlist=["add_link"])
    submissions_video.add_link("https://www.youtube.com/watch?v=abcdefghijk", options())
    host = SimpleNamespace(_stop=threading.Event(), set_state=lambda *a, **kw: None)
    job = turn_job(one, host)
    with pytest.raises(queue.Wait):
        live.live_capture(job)
    recorder.made[-1].minute()
    with pytest.raises(queue.Wait):
        live.live_capture(job)
    db.update_project(db.fetch("sources", one["id"])["project_id"], duration=60.0)
    db.execute("UPDATE worker_jobs SET status = 'waiting', wait_reason = 'live' WHERE id = ?", (job.id,))
    from test_review_submitted_routes import H

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.get("/api/autopilot/submissions/live", headers=H)
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()}
    assert set(rows) == {one["id"], two["id"]}  # recorded videos are not listed here
    assert rows[one["id"]]["live"]["minutes"] == 1.0 and rows[one["id"]]["can_finish"]
    assert rows[one["id"]]["submission"]["auto_upload"] and not rows[two["id"]]["submission"]["auto_upload"]
    assert not rows[two["id"]]["live"]["recording"]

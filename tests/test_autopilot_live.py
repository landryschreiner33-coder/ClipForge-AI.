"""Live Monitor: capture a growing recording in segments, clip it while it runs, analyze it when it ends."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).parent


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def test_segment_list_parsing_and_capture_rules(data):
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue, rights

    rec = data / "rec.mkv"
    rec.write_bytes(b"x")
    src = db.insert("sources", {"platform": "local", "external_id": "a", "title": "Stream", "kind": "live",
                                "local_path": str(rec), "status": "eligible"})
    assert not live.capture_allowed(src, db.get_settings())[0]  # rights unknown: never captured
    rights.add_rule("folder", str(data), rights.OWNED, "my recordings")
    assert live.capture_allowed(src, db.get_settings())[0]
    assert live.input_args(src, {})[:2] == ["-follow", "1"]  # follows a file that is still being written
    yt = {"id": "y", "platform": "youtube", "url": "https://www.youtube.com/watch?v=live1", "kind": "live"}
    with pytest.raises(queue.Fail, match="allow downloads"):
        live.input_args(yt, {"rights_allow_remote_download": False})
    assert live.input_args({"url": "rtmp://127.0.0.1/live/mine"}, {})[-1] == "rtmp://127.0.0.1/live/mine"
    sess = live.Session(db.fetch("sources", src["id"]), db.get_settings())
    sess.listfile.write_text("r001_00000.mkv,0.000000,10.020000\nr001_00001.mkv,10.020000,20.000000\n")
    assert live.finished_segments(sess) == [("r001_00000.mkv", 10.02), ("r001_00001.mkv", pytest.approx(9.98))]
    sess.segments.append({"name": "r001_00000.mkv", "start": 0, "end": 10.02})
    assert [n for n, _ in live.finished_segments(sess)] == ["r001_00001.mkv"]
    again = live.Session(db.fetch("sources", src["id"]), db.get_settings())
    assert again.run == 2 and again.project["id"] == sess.project["id"]  # a restart continues the same capture


def test_supersede_cancels_unpublished_schedule(data):
    from clipfoundry import db
    from clipfoundry.autopilot import live

    project = db.create_project("live", origin="live", status="ready")
    clip = db.create_clip(project["id"], start=0, end=20, status="ready", score=60)
    item = db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "youtube",
                                                "status": "awaiting_approval"})
    assert not live._published(clip["id"])  # noqa: SLF001
    live.supersede(clip, "Replaced by the post-live analysis")
    assert db.get_clip(clip["id"])["status"] == "superseded"
    assert db.fetch("scheduled_publications", item["id"])["status"] == "replaced"


@pytest.fixture(scope="module")
def talk_video(tmp_path_factory):
    if not shutil.which("ffmpeg") or not (shutil.which("espeak-ng") or shutil.which("espeak")):
        pytest.skip("ffmpeg and espeak-ng are needed to build the speech test video")
    out = tmp_path_factory.mktemp("media")
    subprocess.run([sys.executable, str(HERE / "make_test_video.py"), str(out), str(HERE / "fixtures" / "face.jpg")],
                   check=True, capture_output=True)
    # a recording like OBS writes: Matroska with a keyframe every second
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out / "talk.mp4"), "-c:v", "libx264", "-preset",
                    "ultrafast", "-g", "25", "-c:a", "aac", str(out / "talk.mkv")], check=True)
    return out


@pytest.mark.slow
def test_live_capture_and_post_live_analysis(talk_video, data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host, live, queue, rights
    from clipfoundry.pipeline import transcribe as tr

    db.save_settings({"autopilot_enabled": True, "autopilot_live_monitoring": True, "autopilot_clips_per_source": 3,
                      "autopilot_min_quality": 40, "encoder": "x264", "x264_preset": "ultrafast",
                      "min_duration": 12.0, "max_duration": 45.0, "target_duration": 25.0})
    monkeypatch.setattr(live, "SEGMENT_SECONDS", 10)
    monkeypatch.setattr(live, "STALL_SECONDS", 4)
    monkeypatch.setattr(live, "EDGE_MARGIN", 3.0)
    folder = data / "obs"
    folder.mkdir()
    rights.add_rule("folder", str(folder), rights.OWNED, "My stream recordings")
    growing = folder / "stream.mkv"
    full = (talk_video / "talk.mkv").read_bytes()
    growing.write_bytes(full[:len(full) // 6])

    def writer() -> None:  # OBS keeps writing for a few seconds, then the stream ends
        for k in range(2, 7):
            time.sleep(1.2)
            with open(growing, "ab") as fh:
                fh.write(full[len(full) * (k - 1) // 6:len(full) * k // 6])

    words_all = tr.flatten_words(tr.import_transcript(talk_video / "speech.srt", 0))
    clock = {"offset": 0.0}

    # Whisper stand-in, per segment
    def fake_transcribe(wav, duration, settings, ctx, lo=0.0, hi=1.0, vad=True, allow_cpu_fallback=True):
        assert allow_cpu_fallback is False  # Autopilot transcribes in strict GPU mode by default
        a, b = clock["offset"], clock["offset"] + duration
        clock["offset"] = b
        ws = [{**w, "start": w["start"] - a, "end": w["end"] - a} for w in words_all if a <= w["start"] < b]
        seg = {"start": ws[0]["start"], "end": ws[-1]["end"], "text": " ".join(w["w"] for w in ws), "words": ws} \
            if ws else None
        return {"language": "en", "segments": [seg] if seg else [],
                "runtime": {"device": "cpu", "requested_device": "cpu", "model": "test"}}

    monkeypatch.setattr(tr, "transcribe", fake_transcribe)
    src = db.insert("sources", {"platform": "local", "external_id": "obs1", "title": "My live stream", "kind": "live",
                                "local_path": str(growing), "status": "eligible", "live_status": "live",
                                "rights_status": "OWNED"})
    host.WorkerHost(periodic=False)

    def run(kind: str, payload: dict) -> dict:
        row = queue.enqueue(kind, payload)
        return host.HANDLERS[kind](host.Job(queue.get(row["id"]), "test"))

    assert run("live_watch", {})["started"] == [src["id"]]
    threading.Thread(target=writer, daemon=True).start()
    out = run("live_capture", {"source_id": src["id"]})
    project = db.get_project(db.fetch("sources", src["id"])["project_id"])
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                     str(talk_video / "talk.mkv")], capture_output=True, text=True).stdout)
    assert project["origin"] == "live" and abs(out["minutes"] * 60 - duration) < 3
    assert Path(project["source_path"]).name == "source.mkv" and Path(project["source_path"]).exists()
    live_clips = [c for c in db.list_clips(project["id"]) if c["status"] == "ready"]
    assert out["live_clips"] == len(live_clips) >= 1  # clipped while the stream was running
    for c in live_clips:
        assert Path(c["output_path"]).exists() and c["score_source"] == "Live analysis"
    post = queue.jobs(worker="live_monitor", status=("queued",))
    assert any(j["kind"] == "post_live" for j in post)
    result = run("post_live", {"source_id": src["id"], "project_id": project["id"]})
    s = db.fetch("sources", src["id"])
    assert s["status"] in ("analyzed", "weak") and "Post-live" in s["status_note"]
    ready = [c for c in db.list_clips(project["id"]) if c["status"] == "ready"]
    assert len(ready) >= 1 and result["added"] + len(live_clips) - result["replaced"] == len(ready)
    assert len(queue.jobs(worker="packager")) >= len(ready)

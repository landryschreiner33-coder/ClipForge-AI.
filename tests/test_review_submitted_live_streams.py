"""Two live streams recorded at the same time, clipped while live, and uploaded during the stream.

Only the outside world is replaced: the platform's stream (a local speech video played at real speed, as a stream
arrives), the platform's page check, Whisper (the video's own timed transcript) and YouTube (a local fake). The
worker host, its live lanes, the recorder subprocess, FFmpeg segmenting, detection, rendering, packaging, the final
quality checks, the scheduler, the per-input upload request and the uploads are the production code.
"""
from __future__ import annotations

import ipaddress
import json
import shutil
import time
from pathlib import Path

import pytest

from test_autopilot_publish import connect, env  # noqa: F401 - fake platforms, never real accounts
from zero_touch_support import BUSINESS, DIET, build_speech_video

H = {"X-ClipFoundry": "1"}
STREAMS = ("https://www.twitch.tv/first_streamer", "https://kick.com/second_streamer")


@pytest.mark.slow
@pytest.mark.skipif(not shutil.which("ffmpeg") or not (shutil.which("espeak-ng") or shutil.which("espeak")),
                    reason="ffmpeg and espeak-ng build the stream video")
def test_two_streams_record_at_once_and_upload_clips_while_still_live(env, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from clipfoundry import db, media_import, netguard
    from clipfoundry.api import app
    from clipfoundry.autopilot import host, live, queue, submissions
    from clipfoundry.pipeline import artifact, transcribe

    google, tiktok, tmp = env
    connect(google, tiktok)
    real_dns = netguard.resolve
    monkeypatch.setattr(netguard, "resolve", lambda name: [ipaddress.ip_address("8.8.8.8")]
                        if name.endswith(("twitch.tv", "kick.com")) else real_dns(name))
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_tiktok": False,
                      "autopilot_input_mode": "submitted", "autopilot_review_before_publish": True,
                      "autopilot_min_gap_minutes": 0, "autopilot_min_quality": 40, "autopilot_clips_per_source": 2,
                      "encoder": "x264", "x264_preset": "ultrafast", "layout": "fit", "whisper_device": "cpu",
                      "min_duration": 12.0, "max_duration": 30.0, "target_duration": 18.0,
                      "autopilot_max_source_gb": 0.5})
    # Two different broadcasts: identical words or pictures would rightly be held back as repeats of an upload.
    media = {url: build_speech_video(tmp / f"stream{n}", lines, repeats=repeats, flip=bool(n))
             for n, (url, lines, repeats) in enumerate(zip(STREAMS, (DIET, BUSINESS), (12, 9)))}
    words = {url: transcribe.flatten_words(transcribe.import_transcript(srt, 10_000)) for url, (_, srt) in media.items()}
    length = min(heard[-1]["end"] for heard in words.values()) + 1.0
    started = time.monotonic()

    def platform_page(url):
        # The channel is live (the page check a platform answers). Nothing is fetched from the internet.
        return {"kind": "live", "live_status": "live", "title": f"Live on {url.split('/')[-1]}"}

    def stream(src, settings, public_relays=None, byte_budget=None, on_retry=None, broadcast=None):
        # The broadcast arrives at real speed, as it would from the platform's stream relay.
        if broadcast is not None:
            broadcast.update({"id": f"broadcast-{src['id']}", "title": src["title"], "url": src["url"]})
        return ["-re", "-i", str(media[src["url"]][0])]

    def whisper(wav, duration, settings, ctx, lo=0.0, hi=1.0, vad=True, allow_cpu_fallback=True):
        saved = Path(wav).parent / "state.json"
        offset = float(json.loads(saved.read_text()).get("offset") or 0) if saved.exists() else 0.0
        project = next(p for p in (db.get_project(Path(wav).parent.name), db.get_project(Path(wav).parent.parent.name))
                       if p)
        script = words[db.fetch("sources", project["source_id"])["url"]]
        heard = [{**w, "start": max(0.0, w["start"] - offset), "end": min(duration, w["end"] - offset)}
                 for w in script if offset <= w["start"] < offset + duration]
        return {"language": "en", "segments": [{"start": heard[0]["start"], "end": heard[-1]["end"],
                "text": " ".join(w["w"] for w in heard), "words": heard}] if heard else [],
                "runtime": {"device": "cpu", "requested_device": "cpu", "model": "stream transcript"}}

    monkeypatch.setattr(media_import, "inspect_video", platform_page)
    monkeypatch.setattr(live, "input_args", stream)
    monkeypatch.setattr(live, "SEGMENT_SECONDS", 10)
    monkeypatch.setattr(live, "EDGE_MARGIN", 2.0)
    monkeypatch.setattr(transcribe, "transcribe", whisper)
    # The posting check runs every two seconds instead of every minute; nothing else about it changes.
    monkeypatch.setattr(host, "PERIODIC", [(kind, (lambda _s: 2.0) if kind == "schedule_tick" else period, active)
                                           for kind, period, active in host.PERIODIC])
    worker = None
    seen_live: dict[str, bool] = {}

    def wait(condition, what, timeout=300.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = condition()
            if value:
                return value
            time.sleep(0.2)
        raise AssertionError((what, [(j["kind"], j["status"], j["wait_reason"], j["message"][:80], j["error"][:120])
                                     for j in queue.jobs(limit=200)],
                              [(s["title"], s["status"], s["live_status"], s["status_note"]) for s in
                               db.select("sources")],
                              [(p["status"], p["status_note"]) for p in db.select("scheduled_publications")]))

    def uploaded(source_id):
        project = (db.fetch("sources", source_id) or {}).get("project_id") or ""
        done = [p for p in db.list_publications() if p["status"] == "done" and
                (db.get_clip(p["clip_id"]) or {}).get("project_id") == project]
        if done and source_id not in seen_live:
            # Recorded the moment its first upload is seen: was the stream still being recorded?
            seen_live[source_id] = db.fetch("sources", source_id)["live_status"] == "live" and \
                any(c.sess.src["id"] == source_id and c.proc.poll() is None for c in list(live._captures.values()))
        return done

    try:
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            setup = client.get("/api/autopilot/submissions/setup", headers=H).json()
            assert setup["can_upload"], setup
            request = {"auto_upload": True, "account_id": setup["account_id"], "privacy": setup["privacy"],
                       "made_for_kids": False, "audience_version": setup["audience"]["group_version"],
                       "reuse_basis": "owned", "reuse_statement": "", "agreed": True, "live": True}
            ids = []
            for url in STREAMS:
                added = client.post("/api/autopilot/submissions/link", headers=H, json={"url": url, **request})
                assert added.status_code == 200, added.text
                ids.append(added.json()["item"]["id"])
            worker = host.WorkerHost(poll=0.05)
            assert worker.start()

            # Both streams record at the same time, each on its own live lane.
            wait(lambda: len([c for c in list(live._captures.values()) if c.proc.poll() is None]) == 2,
                 "both recorders running", timeout=120)
            streams = client.get("/api/autopilot/submissions/live", headers=H).json()
            assert {s["id"] for s in streams} == set(ids) and all(s["live"]["recording"] for s in streams)
            assert all(s["can_finish"] for s in streams)

            # Clips from each stream are made, checked and uploaded while that stream is still live.
            for source_id in ids:
                wait(lambda source_id=source_id: uploaded(source_id), f"an upload from {source_id} while live",
                     timeout=length - 20)
            assert seen_live == {source_id: True for source_id in ids}, seen_live
            print(f"both streams uploaded while live after {time.monotonic() - started:.0f} s")

            # Stop recording: each stream finishes from what was recorded and keeps its clips and uploads.
            for source_id in ids:
                stopped = client.post(f"/api/autopilot/links/{source_id}/finish", headers=H)
                assert stopped.status_code == 200, stopped.text
            for source_id in ids:
                wait(lambda source_id=source_id: db.fetch("sources", source_id)["live_status"] == "stopped",
                     f"{source_id} stopped", timeout=120)
            assert not [c for c in list(live._captures.values()) if c.proc.poll() is None]
            for source_id in ids:
                wait(lambda source_id=source_id: any(j["kind"] == "post_live" and j["status"] == "completed" and
                                                     j["payload"]["source_id"] == source_id for j in queue.jobs(limit=500)),
                     f"full-recording analysis of {source_id}", timeout=600)
    finally:
        if worker:
            worker.stop(timeout=30)
        live.stop_captures()

    for source_id in ids:
        source = db.fetch("sources", source_id)
        project = db.get_project(source["project_id"])
        grant = submissions.for_source(source)["settings"]
        assert source["status_note"].startswith("Stopped by you") or source["status"] in ("analyzed", "weak")
        assert grant["bound_project_id"] == project["id"] and grant["live"] is True
        # The joined recording is what later approvals check, byte for byte.
        assert grant["source_path"] == project["source_path"]
        assert grant["source_sha256"] == artifact.sha256_file(project["source_path"])
        recorded = json.loads((Path(project["source_path"]).parent / "live" / "state.json").read_text())
        assert recorded["stopped_by_owner"] and len(recorded["segments"]) >= 3
    # Every upload is the exact file that passed its final checks, and each stream's request covered only its own.
    for publication in [p for p in db.list_publications() if p["status"] == "done"]:
        clip = db.get_clip(publication["clip_id"])
        report = db.select("quality_reports", "clip_id = ? AND status = 'passed'", (clip["id"],))[-1]
        upload = google.videos[publication["remote_id"]]
        assert artifact.sha256_file(clip["output_path"]) == report["artifact_sha256"]
        assert upload["bytes"] == Path(clip["output_path"]).read_bytes()
        item = db.select("scheduled_publications", "publication_id = ?", (publication["id"],))[0]
        assert item["approval"]["by"] == "submission"
        source = db.fetch("sources", item["source_id"])
        assert db.get_project(source["project_id"])["id"] == clip["project_id"]
    assert len(google.videos) == len([p for p in db.list_publications() if p["status"] == "done"]) >= 2

"""Complete autonomous loop against fake accounts, with actual media processing and artifact checks."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from fake_platforms import FakeGoogle, FakeTikTok
from zero_touch_support import (BROKEN, DIET, FIRST, SECOND, STREAM, CompleteLoopFixture,
                               build_speech_video, install_fixture_dns)

H = {"X-ClipFoundry": "1"}


def until(fixture: CompleteLoopFixture, condition, timeout: float = 240.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.1)
    state = fixture.snapshot()
    raise AssertionError({"sources": [(s["external_id"], s["status"], s["status_note"]) for s in state["sources"]],
                          "jobs": [(j["kind"], j["status"], j["message"], j["error"]) for j in state["jobs"][-20:]],
                          "reports": [(r["status"], r["blockers"], r["warnings"]) for r in state["reports"]],
                          "posts": [(p["status"], p["status_note"]) for p in state["posts"]]})


@pytest.mark.slow
def test_worker_host_runs_complete_loop_and_repeats_after_restart(monkeypatch, tmp_path):
    """One bad original does not block real render/check/publish/observe work, including the next discovery.

    The host dispatches every handler itself. The test supplies only fake platform inputs, a transcript in place
    of Whisper, the one-time publishing consent, one Start, and simulated time passing before results arrive.
    """
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.autopilot import host, state
    from clipfoundry.pipeline import artifact
    from clipfoundry.publish import tiktok, youtube
    from clipfoundry.publish.common import challenge_s256, code_verifier

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    google, tt = FakeGoogle(), FakeTikTok()
    for name, suffix in (("AUTH_URL", "/o/oauth2/v2/auth"), ("TOKEN_URL", "/token"), ("REVOKE_URL", "/revoke"),
                         ("API_URL", "/youtube/v3"), ("UPLOAD_URL", "/upload/youtube/v3/videos")):
        monkeypatch.setattr(youtube, name, google.url + suffix)
    monkeypatch.setattr(tiktok, "API_URL", tt.url + "/v2")
    db.init()
    db.save_settings({"youtube_client_id": "cid.apps.googleusercontent.com", "youtube_client_secret": "csecret"})
    verifier = code_verifier()
    callback = "http://127.0.0.1:8765/cb"
    code = google.approve(youtube.auth_url(db.get_settings(), callback, "state", challenge_s256(verifier)))
    youtube.exchange_code(db.get_settings(), code, verifier, callback)
    fixture = CompleteLoopFixture(tmp_path / "data", google, monkeypatch.setattr)
    worker = None
    try:
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            assert client.post("/api/autopilot/auto-publish", headers=H, json={"platform": "youtube",
                               "visibility": "public", "made_for_kids": False, "daily_limit": 4,
                               "start_hour": 0, "end_hour": 24, "agreed": True}).status_code == 200
            assert client.post("/api/autopilot/start", headers=H).status_code == 200
            worker = host.WorkerHost(poll=0.05)
            assert worker.start()
            until(fixture, lambda: db.select("sources", "external_id = ? AND status = 'failed'", (BROKEN,)))
            until(fixture, lambda: len([p for p in db.list_publications() if p["status"] == "done"]) == 1)
            # The upload marks its publication done before the handler returns; the job completes a moment later
            until(fixture, lambda: db.select("worker_jobs", "kind = 'publish' AND status = 'completed'"))
            assert len(google.videos) == 1
            first = db.select("sources", "external_id = ?", (FIRST,))[0]
            assert first["clips_selected"] >= 1 and first["id"] in fixture.transcriptions
            initial = fixture.snapshot()
            assert initial["posts"][0]["approval"]["by"] == "automatic"
            for pub in initial["publications"]:
                if pub["status"] != "done":
                    continue
                clip = db.get_clip(pub["clip_id"])
                report = next(r for r in initial["reports"] if r["clip_id"] == clip["id"] and r["status"] == "passed")
                assert artifact.sha256_file(clip["output_path"]) == report["artifact_sha256"]
                upload = next(u for u in initial["uploads"] if u["id"] == pub["remote_id"])
                assert upload["sha256"] == report["artifact_sha256"]
                assert Path(clip["output_path"]).stat().st_size == upload["bytes"]
                assert upload["status"]["privacyStatus"] == "private" and upload["status"]["publishAt"]
            done = {j["kind"] for j in initial["jobs"] if j["status"] == "completed"}
            assert {"trend_scan", "source_scout", "hunt_source", "analyze_source", "package_clip", "quality_check",
                    "schedule_tick", "publish"} <= done

            # A clean worker restart keeps the setting, history and idempotency keys. It needs no second Start.
            worker.stop(timeout=30)
            worker = host.WorkerHost(poll=0.05)
            assert worker.start(wait_for_lock=10)
            assert state.enabled(db.get_settings())
            fixture.repeat()
            until(fixture, lambda: len([p for p in db.list_publications() if p["status"] == "done"]) == 2)
            assert len(google.videos) == 2
            assert db.select("sources", "external_id = ?", (SECOND,))[0]["clips_selected"] >= 1
            assert len(google.sessions) == len(google.videos) == 2
            fixture.age_results()
            until(fixture, lambda: (state.get("learning:status") or {}).get("samples") == 2, timeout=60)
            readings = db.select("performance")
            assert len(readings) == 2 and all(r["views"] == 1234 for r in readings)
            assert all(r["avg_view_percentage"] is None for r in readings)
            learned = state.get("learning:status")
            assert learned["weights"] == {} and "2 of 10 posts with real numbers" in learned["message"]
            assert not any(a["type"] in ("rights", "failed") for a in client.get("/api/autopilot/status").json()
                           ["home"]["needs_you"])
    finally:
        if worker:
            worker.stop(timeout=30)
        fixture.stop()
        google.stop()
        tt.stop()


@pytest.mark.slow
def test_added_upcoming_stream_waits_survives_restart_and_finishes_real_post_live(monkeypatch, tmp_path):
    """Fake stream metadata and a finite transport replay exercise actual capture, segments and post-live clips."""
    import datetime as dt
    import json

    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.autopilot import access, host, intake, live, queue
    from clipfoundry.pipeline import transcribe
    from clipfoundry.publish import youtube

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    video, srt = build_speech_video(tmp_path / "stream", DIET, repeats=2)
    google = FakeGoogle()
    install_fixture_dns(monkeypatch.setattr)
    monkeypatch.setattr(youtube, "API_URL", google.url + "/youtube/v3")
    db.init()
    db.save_settings({"youtube_api_key": google.api_key, "autopilot_enabled": True,
                      "rights_allow_remote_download": True, "autopilot_live_monitoring": True,
                      "autopilot_clips_per_source": 1, "autopilot_min_quality": 40,
                      "autopilot_youtube": False, "autopilot_tiktok": False,
                      "encoder": "x264", "x264_preset": "ultrafast", "layout": "fit",
                      "whisper_device": "cpu", "min_duration": 12.0, "max_duration": 45.0,
                      "target_duration": 25.0})
    item = google.add_video(STREAM, "A live conversation about diets", "UCother00000001", duration="PT1M")
    item["snippet"]["liveBroadcastContent"] = "upcoming"
    item["liveStreamingDetails"] = {"scheduledStartTime": (dt.datetime.now(dt.timezone.utc) +
                                    dt.timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    real_resolve, real_input = access.resolve, live.input_args

    def external_media(source, settings):
        if source.get("external_id") == STREAM:
            return access._ok("local", "Fake platform's permitted stream transport", local_path=str(video))
        return real_resolve(source, settings)

    def transport(source, settings, **kwargs):
        if source.get("external_id") == STREAM:
            # The only replacement is the external live transport. Session, capture subprocess, FFmpeg,
            # segmentation, transcription windows, clipping and finalization retain production behavior.
            return ["-i", str(video)]
        return real_input(source, settings, **kwargs)

    def whisper(wav, duration, settings, ctx, lo=0.0, hi=1.0, vad=True, allow_cpu_fallback=True):
        state_path = Path(wav).parent / "state.json"
        offset = float(json.loads(state_path.read_text()).get("offset") or 0) if state_path.exists() else 0.0
        transcript = transcribe.import_transcript(srt, duration)
        words = [{**w, "start": max(0.0, w["start"] - offset), "end": min(duration, w["end"] - offset)}
                 for w in transcribe.flatten_words(transcript) if offset <= w["start"] < offset + duration]
        return {"language": "en", "segments": [{"start": words[0]["start"], "end": words[-1]["end"],
                "text": " ".join(w["w"] for w in words), "words": words}] if words else [],
                "runtime": {"device": "cpu", "requested_device": "cpu", "model": "sandbox transcript"}}

    monkeypatch.setattr(access, "resolve", external_media)
    monkeypatch.setattr(live, "input_args", transport)
    monkeypatch.setattr(live, "SEGMENT_SECONDS", 10)
    monkeypatch.setattr(live, "EDGE_MARGIN", 2.0)
    monkeypatch.setattr(transcribe, "transcribe", whisper)
    worker = None

    def wait(condition, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = condition()
            if value:
                return value
            time.sleep(0.1)
        raise AssertionError([(j["kind"], j["status"], j["message"], j["error"]) for j in queue.jobs()])

    try:
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            response = client.post("/api/autopilot/links", headers=H,
                                   json={"url": f"https://youtube.com/watch?v={STREAM}"})
            assert response.status_code == 200, response.text
            source_id = response.json()["item"]["id"]
            worker = host.WorkerHost(periodic=False, poll=0.05)
            assert worker.start()
            waiting = wait(lambda: next((j for j in queue.jobs() if j["kind"] == "identify_link" and
                                         j["status"] == "waiting"), None))
            assert waiting["wait_reason"] == "stream_start"
            assert intake.item(db.fetch("sources", source_id))["status"] == "waiting_stream"
            worker.stop(timeout=30)
            worker = host.WorkerHost(periodic=False, poll=0.05)
            assert worker.start(wait_for_lock=10)
            assert queue.get(waiting["id"])["status"] == "waiting"
            assert client.get("/api/autopilot/links").json()[0]["id"] == source_id
            assert not db.select("projects")
            item["snippet"]["liveBroadcastContent"] = "live"
            item["liveStreamingDetails"]["actualStartTime"] = dt.datetime.now(dt.timezone.utc).isoformat()
            wait(lambda: db.fetch("sources", source_id)["live_status"] == "ended", timeout=120)
            wait(lambda: any(j["kind"] == "post_live" and j["status"] == "completed" for j in queue.jobs()), timeout=180)
            source = db.fetch("sources", source_id)
            project = db.get_project(source["project_id"])
            assert project["origin"] == "live" and Path(project["source_path"]).exists()
            recorded = json.loads((Path(project["source_path"]).parent / "live" / "state.json").read_text())
            assert recorded["offset"] > 20 and len(recorded["segments"]) > 1
            clips = wait(lambda: [c for c in db.list_clips(project["id"]) if c["status"] == "ready"])
            assert all(Path(c["output_path"]).exists() for c in clips)
            wait(lambda: db.select("quality_reports", "clip_id = ? AND status = 'passed'", (clips[0]["id"],)))
            assert not db.list_publications()  # accessible local stream is retained without publishing rights
    finally:
        if worker:
            worker.stop(timeout=30)
        google.stop()

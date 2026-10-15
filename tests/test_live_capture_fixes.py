"""Split live HLS stays guarded; delayed public archives recover without inventing recorded minutes."""
from __future__ import annotations

from contextlib import contextmanager
import ipaddress
from pathlib import Path
import subprocess
import time

import httpx
import numpy as np
import pytest

from clipfoundry import db, netguard
from clipfoundry.autopilot import host, live, queue, rights, stream_access
from clipfoundry.pipeline.common import read_json


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_public_videos": True, "autopilot_max_source_gb": 1})
    yield tmp_path
    live.stop_captures()
    live._captures.clear()


def platform_source():
    return db.insert("sources", {"platform": "youtube", "external_id": "live-fix", "kind": "live",
                                 "title": "Public broadcast", "url": "https://www.youtube.com/watch?v=live-fix",
                                 "user_added": 1, "status": "ingesting", "live_status": "ended"})


def job_for(src):
    row = queue.enqueue("live_capture", {"source_id": src["id"]}, ref=("source", src["id"]))
    return host.Job(row, "test")


def extractor(monkeypatch, info=None, error=None):
    from clipfoundry import media_import

    @contextmanager
    def fake(*args, **kwargs):
        class Extractor:
            def extract_info(self, *a, **kw):
                if error:
                    raise error
                return info
        yield Extractor()

    monkeypatch.setattr(media_import, "public_extractor", fake)


def split_info():
    return {"is_live": True, "language": "en", "formats": [
        {"protocol": "m3u8_native", "height": 720, "vcodec": "avc1", "acodec": "none",
         "url": "https://media.example/video.m3u8"},
        {"protocol": "m3u8_native", "vcodec": "none", "acodec": "mp4a", "language": "en", "abr": 128,
         "url": "https://media.example/audio.m3u8"},
        {"protocol": "m3u8_native", "vcodec": "none", "acodec": "mp4a", "language": "fr", "abr": 256,
         "url": "https://media.example/dub.m3u8"},
    ]}


def test_split_formats_select_original_audio_and_ignore_drm(monkeypatch):
    info = split_info()
    info["formats"].append({"protocol": "m3u8_native", "height": 1080, "vcodec": "avc1", "acodec": "aac",
                            "has_drm": True, "url": "https://media.example/protected.m3u8"})
    extractor(monkeypatch, info)
    assert live._resolve_platform_stream("https://www.youtube.com/watch?v=x") == (
        "https://media.example/video.m3u8", "https://media.example/audio.m3u8")


def test_combined_hls_remains_preferred_and_video_only_is_actionable(monkeypatch):
    info = split_info()
    combined = {"protocol": "m3u8_native", "height": 480, "vcodec": "avc1", "acodec": "aac",
                "url": "https://media.example/combined.m3u8"}
    info["formats"].append(combined)
    extractor(monkeypatch, info)
    assert live._resolve_platform_stream("https://www.youtube.com/watch?v=x") == combined["url"]
    info["formats"] = info["formats"][:1]
    with pytest.raises(queue.Fail, match="no usable video and audio") as error:
        live._resolve_platform_stream("https://www.youtube.com/watch?v=x")
    assert "no transcription" in error.value.fix


def test_platform_metadata_keeps_exact_server_wait(monkeypatch):
    from clipfoundry.media_import import MediaUnavailable

    extractor(monkeypatch, error=MediaUnavailable(code="rate_limited", retry_after=7200))
    with pytest.raises(queue.Wait) as error:
        live._resolve_platform_stream("https://www.youtube.com/watch?v=x")
    assert error.value.seconds == 7200


@pytest.mark.parametrize("audio", ["http://127.0.0.1/private.m3u8", "file:///private.m3u8"])
def test_split_audio_cannot_escape_url_guard(monkeypatch, audio):
    monkeypatch.setattr(netguard, "resolve", lambda host: [ipaddress.ip_address(host) if host == "127.0.0.1" else
                                                         ipaddress.ip_address("8.8.8.8")])
    with pytest.raises(stream_access.StreamRefused, match="safe public HTTP"):
        stream_access.PublicStream("https://media.example/video.m3u8", audio_url=audio)


def test_ended_archive_wait_survives_restart_and_eventually_stops(data, monkeypatch):
    from clipfoundry import jobs
    from clipfoundry.media_import import MediaUnavailable

    src = platform_source()
    calls = []
    monkeypatch.setattr(jobs, "download_url", lambda *a, **kw: calls.append(True) or
                        (_ for _ in ()).throw(MediaUnavailable(code="extraction_failed")))
    job = job_for(src)
    monkeypatch.setattr(live, "ARCHIVE_MAX_ATTEMPTS", 2)
    with pytest.raises(queue.Wait, match="waiting for its public recording"):
        live.live_capture(job)
    fresh = db.fetch("sources", src["id"])
    sess = live.Session(fresh, db.get_settings())
    assert sess.archive_recovery["attempts"] == 1 and not sess.capture_complete and not sess.segments
    with pytest.raises(queue.Wait, match="Waiting for the platform"):
        live.live_capture(job)
    assert len(calls) == 1
    sess.archive_recovery["until"] = time.time() - 1
    sess.save()
    with pytest.raises(queue.Fail, match="after repeated checks"):
        live.live_capture(job)
    assert len(calls) == 2 and db.fetch("sources", src["id"])["status"] == "needs_file"
    with pytest.raises(queue.Fail, match="after repeated checks"):
        live.live_capture(job)
    assert len(calls) == 2


def test_ended_archive_obeys_long_server_wait_and_explicit_block(data, monkeypatch):
    from clipfoundry import jobs

    src = platform_source()
    calls = []
    monkeypatch.setattr(jobs, "download_url", lambda *a, **kw: calls.append(True) or
                        (_ for _ in ()).throw(queue.Wait("server", 7200)))
    with pytest.raises(queue.Wait) as error:
        live.live_capture(job_for(src))
    assert error.value.seconds == 7200
    assert live.Session(db.fetch("sources", src["id"]), db.get_settings()).archive_recovery["until"] > time.time() + 7190
    rights.add_rule("source", src["id"], rights.BLOCKED, "Do not use this video")
    assert live.live_capture(job_for(src))["skipped"]
    assert len(calls) == 1


def test_archive_recovery_uses_same_project_and_schedules_post_live_once(data, monkeypatch):
    from clipfoundry import jobs

    src = platform_source()
    calls = []

    def download(project_id, url, ctx, **kwargs):
        calls.append((project_id, url, kwargs))
        project = db.get_project(project_id)
        path = Path(project["source_path"])
        path.write_bytes(b"bounded public recording")

    monkeypatch.setattr(jobs, "download_url", download)
    monkeypatch.setattr(live, "probe", lambda *a, **kw: {"has_video": True, "has_audio": True, "duration": 120,
                                                       "width": 1280, "height": 720, "fps": 25})
    job = job_for(src)
    assert live.live_capture(job)["minutes"] == 2
    project = db.get_project(db.fetch("sources", src["id"])["project_id"])
    pdir = Path(project["source_path"]).parent
    saved = read_json(pdir / "live" / "state.json", {})
    assert saved["untranscribed"] == [[0, 120]] and saved["archive_recovery"]["complete"] == "source.mp4"
    assert not (pdir / "transcript.json").exists() and not (pdir / "loudness.json").exists()
    # A repeat/restart cannot overwrite the full post-live transcript with the empty live checkpoint.
    (pdir / "transcript.json").write_text('{"segments":[{"text":"archived speech"}]}')
    assert live.live_capture(job)["minutes"] == 2
    assert "archived speech" in (pdir / "transcript.json").read_text()
    posts = [r for r in queue.jobs(worker="live_monitor") if r["kind"] == "post_live"]
    assert len(calls) == len(posts) == 1 and calls[0][0] == project["id"]
    assert calls[0][2]["max_bytes"] > 0 and calls[0][2]["max_seconds"] == 240 * 60


@pytest.mark.parametrize("code", ["private", "protected", "login_required", "not_found", "unsupported_site"])
def test_archive_recovery_does_not_retry_access_refusals(data, monkeypatch, code):
    from clipfoundry import jobs
    from clipfoundry.media_import import MediaUnavailable

    monkeypatch.setattr(jobs, "download_url", lambda *a, **kw:
                        (_ for _ in ()).throw(MediaUnavailable(code=code)))
    src = platform_source()
    with pytest.raises(queue.Fail):
        live.live_capture(job_for(src))
    assert db.fetch("sources", src["id"])["status"] == "needs_file"


@pytest.mark.slow
def test_real_split_hls_capture_muxes_audio_in_sync_through_one_guarded_relay(data, monkeypatch):
    from clipfoundry.pipeline.ffmpeg_utils import ffmpeg_bin

    ffmpeg = ffmpeg_bin()
    media = data / "hls"
    media.mkdir()
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=96x160:r=25:d=3", "-f", "lavfi", "-i",
                    "aevalsrc=if(between(t\\,1\\,1.2)\\,0.2*sin(2*PI*440*t)\\,0):s=48000:d=3",
                    "-map", "0:v", "-vf", "drawbox=c=white:t=fill:enable='between(t,1,1.2)'", "-c:v", "libx264",
                    "-threads", "1", "-bf", "0", "-g", "25", "-f", "hls", "-hls_time", "1", "-hls_list_size", "0",
                    str(media / "video.m3u8"), "-map", "1:a", "-c:a", "aac", "-f", "hls", "-hls_time", "1",
                    "-hls_list_size", "0", str(media / "audio.m3u8")], check=True, capture_output=True, timeout=30)
    routes = {"https://media.example/" + p.name: p.read_bytes() for p in media.iterdir()}
    requests = []
    monkeypatch.setattr(netguard, "resolve", lambda _: [ipaddress.ip_address("8.8.8.8")])

    def reply(request):
        assert request.url.host == "8.8.8.8"
        address = f"{request.url.scheme}://{request.headers['host']}{request.url.raw_path.decode()}"
        requests.append(address)
        return httpx.Response(200, content=routes[address], headers={"content-type":
                              "application/vnd.apple.mpegurl" if address.endswith(".m3u8") else "video/mp2t"})

    monkeypatch.setattr(stream_access, "client", lambda _: httpx.Client(transport=httpx.MockTransport(reply)))
    extractor(monkeypatch, split_info())
    src = platform_source()
    sess = live.Session(src, db.get_settings())
    relays = []
    try:
        args = live.input_args(src, db.get_settings(), public_relays=relays)
        assert len(relays) == 1 and args.count("-i") == 1 and "media.example" not in " ".join(args)
        subprocess.run(live.capture_command(sess, args), check=True, capture_output=True, timeout=30)
    finally:
        for relay in relays:
            relay.close()
    segments = live.finished_segments(sess)
    assert len(segments) == 1
    recorded = sess.segdir / segments[0][0]
    audio = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(recorded), "-map", "0:a",
                            "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], check=True, capture_output=True).stdout
    picture = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(recorded), "-map", "0:v",
                              "-pix_fmt", "gray", "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
    sound = np.frombuffer(audio, dtype="<f4")
    rms = [float(np.sqrt(np.mean(sound[i:i + 960] ** 2))) for i in range(0, len(sound) - 960, 960)]
    sound_at = next(i * .02 for i, value in enumerate(rms) if value > .02)
    frames = np.frombuffer(picture, dtype=np.uint8).reshape(-1, 96 * 160)
    flash_at = next(i / 25 for i, frame in enumerate(frames) if frame.mean() > 200)
    assert abs(sound_at - flash_at) < .1 and .9 <= flash_at <= 1.1
    assert any("audio" in r for r in requests) and any("video" in r for r in requests)

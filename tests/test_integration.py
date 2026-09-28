"""Integration tests: real ffmpeg, OpenCV face detection and the full API flow.

Skipped automatically when ffmpeg (or espeak-ng for the speech test video) is missing.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).parent
FACE = HERE / "fixtures" / "face.jpg"
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def _ffprobe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _two_speaker_video(path: Path, seconds: float = 12.0, fps: int = 25) -> None:
    """Two faces far apart; the left one 'talks' in the first half, the right one in the second."""
    import cv2

    W, H, S = 1920, 1080, 360
    face = cv2.resize(cv2.imread(str(FACE)), (S, S))
    k = S / 256.0
    mouth = (int(109 * k), int(72 * k))  # mouth centre in the 256px fixture
    positions = [int(0.2 * W) - S // 2, int(0.8 * W) - S // 2]
    y0 = H // 2 - S // 2
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-framerate", str(fps), "-i", "pipe:0", "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(int(seconds * fps)):
        t = i / fps
        frame = np.full((H, W, 3), (40, 30, 30), np.uint8)
        speaker = 0 if t < seconds / 2 else 1
        for n, x0 in enumerate(positions):
            f = face.copy()
            if n == speaker:
                open_h = int(2 + 7 * abs(np.sin(t * 11)))
                cv2.ellipse(f, mouth, (int(12 * k), open_h), 0, 0, 360, (40, 30, 90), -1)
            frame[y0:y0 + S, x0:x0 + S] = f
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()


@needs_ffmpeg
def test_active_speaker_tracking(tmp_path):
    from clipfoundry.pipeline import reframe

    video = tmp_path / "two.mp4"
    _two_speaker_video(video)
    plan = reframe.plan(str(video), 0.0, 12.0, 1920, 1080, "auto", 25.0)
    assert plan.mode == "speaker"
    t = np.arange(plan.n) / 25.0
    first = plan.cx[(t > 1.5) & (t < 5.5)].mean()
    second = plan.cx[(t > 8.0) & (t < 11.5)].mean()
    assert abs(first - 0.2) < 0.1, first
    assert abs(second - 0.8) < 0.1, second
    center = reframe.plan(str(video), 0.0, 12.0, 1920, 1080, "center", 25.0)
    assert np.allclose(center.cx, 0.5)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    if not (shutil.which("ffmpeg") and (shutil.which("espeak-ng") or shutil.which("espeak"))):
        pytest.skip("ffmpeg and espeak-ng are needed to build the speech test video")
    out = tmp_path_factory.mktemp("media")
    subprocess.run([sys.executable, str(HERE / "make_test_video.py"), str(out), str(FACE)], check=True)
    return out


@pytest.mark.slow
def test_full_api_flow(media, tmp_path, monkeypatch):
    """MVP check: upload a real video -> multiple captioned 1080x1920 H.264/AAC clips -> ZIP export -> edit."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app) as client:
        assert client.get("/api/health").json()["ffmpeg"]
        with open(media / "talk.mp4", "rb") as v, open(media / "speech.srt", "rb") as s:
            r = client.post("/api/projects", files={"file": ("talk.mp4", v, "video/mp4"),
                                                    "transcript": ("speech.srt", s, "text/plain")},
                            data={"options": json.dumps({"clip_count": 5, "caption_style": "bold"})})
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        bad = client.post("/api/projects", files={"file": ("x.avi", b"123", "video/x-msvideo")})
        assert bad.status_code == 400

        project = _wait(client, pid)
        assert project["status"] == "ready", project
        clips = project["clips"]
        assert 2 <= len(clips) <= 5
        for c in clips:
            assert c["status"] == "ready", c["error"]
            assert 0 < c["score"] <= 100 and c["title"] and c["hook"] and len(c["hooks_alt"]) == 3
            assert c["hashtags"] and c["category"]
            vid = client.get(f"/api/clips/{c['id']}/video")
            assert vid.status_code == 200
            path = tmp_path / f"{c['id']}.mp4"
            path.write_bytes(vid.content)
            info = _ffprobe(path)
            v = next(s for s in info["streams"] if s["codec_type"] == "video")
            a = next(s for s in info["streams"] if s["codec_type"] == "audio")
            assert (v["codec_name"], v["width"], v["height"]) == ("h264", 1080, 1920)
            assert a["codec_name"] == "aac"
            assert abs(float(info["format"]["duration"]) - c["duration"]) < 0.5
        starts = sorted((c["start"], c["end"]) for c in clips)
        for (a0, a1), (b0, _) in zip(starts, starts[1:]):
            assert b0 >= a1 - 0.15 * (a1 - a0)  # distinct moments

        z = client.post(f"/api/projects/{pid}/export", json={"clip_ids": None})
        assert z.status_code == 200 and z.headers["content-type"] == "application/zip"

        # simple editor: switch layout, captions and silence cleanup, then re-render
        cid = clips[0]["id"]
        r = client.patch(f"/api/clips/{cid}", json={"hook": clips[0]["hooks_alt"][0], "edit": {
            "layout": "fit", "caption_style": "high_energy", "silence": "aggressive", "gain_db": -3,
            "hook": clips[0]["hooks_alt"][0], "not_allowed": 1}})
        assert r.status_code == 200 and "not_allowed" not in r.json()["edit"]
        assert client.post(f"/api/clips/{cid}/render").status_code == 200
        for _ in range(300):
            c = client.get(f"/api/clips/{cid}").json()
            if c["status"] in {"ready", "error"}:
                break
            time.sleep(1)
        assert c["status"] == "ready", c["error"]
        assert c["render_info"]["segments"] >= 1

        # versions: render the three alternatives, choose one, and export uses it
        r = client.post(f"/api/clips/{cid}/versions", json={"kinds": None})
        assert r.status_code == 200 and len(r.json()["versions"]) == 4
        for _ in range(600):
            vs = client.get(f"/api/clips/{cid}/versions").json()["versions"]
            if all(v["status"] in {"ready", "error"} for v in vs):
                break
            time.sleep(1)
        by_kind = {v["kind"]: v for v in vs}
        assert all(v["status"] == "ready" for v in vs), [(v["kind"], v["error"]) for v in vs]
        assert by_kind["faster"]["duration"] < by_kind["original"]["duration"]
        assert by_kind["faster"]["render_info"]["speed"] == 1.08
        faster = by_kind["faster"]["id"]
        assert client.post(f"/api/clips/{cid}/active-version", json={"version_id": faster}).json()["active"] == faster
        v_bytes = client.get(f"/api/versions/{faster}/video").content
        z = client.post(f"/api/projects/{pid}/export", json={"clip_ids": [cid]})
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
            mp4 = next(n for n in zf.namelist() if n.endswith(".mp4"))
            assert zf.read(mp4) == v_bytes  # the chosen version is what gets exported
            assert json.loads(zf.read("metadata.json"))["clips"][0]["version"] == "Faster pacing"
        assert client.delete(f"/api/versions/{faster}").status_code == 200
        assert client.get(f"/api/clips/{cid}/versions").json()["active"] == ""  # back to the original

        assert client.delete(f"/api/projects/{pid}").json()["ok"]
        assert client.get(f"/api/projects/{pid}").status_code == 404


def _wait(client, pid: str, timeout: float = 600) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = client.get(f"/api/projects/{pid}").json()
        if p["status"] in {"ready", "error", "cancelled"}:
            return p
        time.sleep(1.5)
    raise AssertionError("processing timed out")

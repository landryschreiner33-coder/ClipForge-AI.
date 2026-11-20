"""A real animated short, made and rendered on this computer (slow suite; docs/clipforge/ANIMATED_SHORTS.md):
espeak-ng reads the script, the pictures are designed cards (no picture maker is set up here), the camera moves
over them, and the built-in engine renders the 9:16 video with the highlighted captions, the ducked music bed and
the whooshes. Checks what a viewer gets: the frame, the length, the voice, and captions burnt in the middle.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.slow

SCRIPT = ("Did you know octopuses have three hearts? Two of them pump blood to the gills.\n\n"
          "The third one keeps the rest of the body going.\n\n"
          "And their blood is blue, because it carries copper instead of iron.")


@pytest.fixture()
def env(monkeypatch, tmp_path):
    if not (shutil.which("espeak-ng") or shutil.which("espeak")):
        pytest.skip("espeak-ng is not installed on this computer")
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.jobs import worker

    db.init()
    queued: list[str] = []
    monkeypatch.setattr(worker, "submit_studio", lambda job_id: queued.append(job_id))
    return queued


def _run(queued: list[str]) -> list[dict]:
    from clipfoundry import db
    from clipfoundry.studio import jobs as studio_jobs

    done = []
    while queued:
        job_id = queued.pop(0)
        studio_jobs.run(job_id)
        done.append(db.fetch("studio_jobs", job_id))
    return done


def _probe(path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_a_short_is_made_and_rendered_with_its_voice_captions_and_music(env):
    from clipfoundry import db
    from clipfoundry.makers import shorts
    from clipfoundry.studio import engine, video_flow
    from clipfoundry.studio.jobs import enqueue

    project = shorts.create("local", "local", name="Three hearts", options={"mode": "paste", "script": SCRIPT,
                                                                             "look": "comic", "music": "energetic"})
    jobs = _run(env)  # the build, then the preview it asks for
    assert [j["kind"] for j in jobs][:2] == ["short_build", "video_preview"]
    assert all(j["status"] == "done" for j in jobs), [j["error"] for j in jobs]
    project = db.fetch("studio_projects", project["id"])
    plan = video_flow.plan_at(project["id"], project["plan_revision"])
    scenes = shorts.ordered(shorts.scene_rows(project["id"]), plan)
    assert all(s["status"] == "ready" for s in scenes)
    assert all(s["info"]["voice"]["engine"] == "espeak" for s in scenes)
    assert all(s["info"]["picture"]["source"] == "card" for s in scenes)
    # the final render
    enqueue("local", "video_render", project["id"], project["plan_revision"])
    jobs = _run(env)
    assert jobs and jobs[-1]["status"] == "done", jobs[-1]["error"]
    art = db.select("studio_artifacts", "project_id = ? AND kind = 'final'", (project["id"],))[0]
    info = _probe(art["path"])
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (int(video["width"]), int(video["height"])) == (1080, 1920)
    assert video["r_frame_rate"] in ("30/1", "30000/1000")
    length = float(info["format"]["duration"])
    assert abs(length - engine.duration_ms(plan) / 1000) < 0.2
    assert 6 < length < 30
    assert audio["sample_rate"] == "48000"
    # the voice is clearly there (louder than a quiet bed), and the captions are burnt in the middle of the frame
    loud = subprocess.run(["ffmpeg", "-v", "info", "-i", art["path"], "-af", "volumedetect", "-f", "null", "-"],
                          capture_output=True, text=True).stderr
    mean = float(loud.split("mean_volume:")[1].split("dB")[0])
    assert mean > -32
    # the captions are burnt in the middle of the frame: white words, the spoken one in the style's highlight
    import numpy as np
    from PIL import Image

    from clipfoundry.pipeline.captions import STYLE_PRESETS

    lit = np.array([int(STYLE_PRESETS[plan["captions"]["style"]]["highlight"][k:k + 2], 16) for k in (1, 3, 5)])
    found = 0.0
    for at in ("1.0", "2.0", "3.0"):
        frame = f"{art['path']}.{at}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", at, "-i", art["path"], "-frames:v", "1", frame],
                       check=True)
        img = np.asarray(Image.open(frame).convert("RGB"), dtype=np.int16)
        h = img.shape[0]
        band = img[int(h * 0.44):int(h * 0.56)]
        white = (band > 225).all(axis=2)
        highlight = np.abs(band - lit).sum(axis=2) < 60
        found = max(found, float((white | highlight).mean()))
    assert found > 0.003

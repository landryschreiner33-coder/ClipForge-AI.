"""Decode actual encoded output: a missed face must not leave a moving subject outside the crop."""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from synthetic_media import needs_ffmpeg


@pytest.mark.slow
@needs_ffmpeg
def test_real_render_follows_moving_visual_subject_without_face_detection(tmp_path, monkeypatch):
    from clipfoundry import db
    from clipfoundry.pipeline import quality, reframe, render
    from clipfoundry.pipeline.common import JobContext, read_json, write_json
    from clipfoundry.pipeline.ffmpeg_utils import ffmpeg_bin, probe

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    monkeypatch.setattr(reframe, "_detector", lambda *_: None)
    # The same production crop/encoder path, at a smaller test export size to keep the regression fast.
    monkeypatch.setattr(render, "OUTPUT_W", 180)
    monkeypatch.setattr(render, "OUTPUT_H", 320)
    source = tmp_path / "moving-subject.mp4"
    command = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", "640x360", "-r", "12", "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", str(source)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for index in range(60):
            frame = np.zeros((360, 640, 3), dtype=np.uint8)
            centre = int(110 + 420 * index / 59)
            cv2.rectangle(frame, (centre - 28, 115), (centre + 28, 245), (20, 220, 40), -1)
            cv2.line(frame, (centre - 20, 130), (centre + 20, 230), (255, 255, 255), 4)
            process.stdin.write(frame.tobytes())
    finally:
        process.stdin.close()
        assert process.wait(timeout=30) == 0
    metadata = probe(source)
    project = {"id": "moving", "name": "Synthetic moving subject", "source_path": str(source),
               "dir": str(tmp_path / "project"), "options": {}, "info": metadata, **metadata}
    clip = {"id": "moving-clip", "project_id": "moving", "start": 0, "end": 5, "hook": "", "edit": {
        "start": 0, "end": 5, "captions_enabled": False, "tracking": "auto", "auto_zoom": False,
        "hook_overlay": False, "normalize_audio": False}}
    clip_directory = Path(project["dir"]) / "clips" / clip["id"]
    clip_directory.mkdir(parents=True)
    # A cached older stationary crop must be invalidated by the framing change.
    write_json(clip_directory / "framing.json", {"key": "v2-0.000-5.000-auto-12.000-0.500",
                                               "plan": reframe.static_plan("center", 12, 60).to_json()})
    result = render.render_clip(project, clip, [], {**db.get_settings(), "encoder": "x264",
                                                  "x264_preset": "ultrafast"}, JobContext())
    assert result["render_info"]["mode"] == "motion"
    assert quality.framing_checks(result["render_info"])[0]["status"] == "pass"
    assert quality.framing_checks({"mode": "motion", "crop_w": .3})[0]["status"] == "warn"
    framing = read_json(clip_directory / "framing.json")
    assert framing["key"].startswith("v3-")
    assert framing["plan"]["cx"][-1] - framing["plan"]["cx"][0] > .4
    capture = cv2.VideoCapture(result["output_path"])
    visible, positions = [], []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        mask = (frame[..., 1] > 120) & (frame[..., 1] > frame[..., 0] * 1.5) & (
            frame[..., 1] > frame[..., 2] * 1.5)
        visible.append(int(mask.sum()))
        positions.append(float(np.where(mask)[1].mean()) if mask.any() else -1)
    capture.release()
    assert len(visible) == 60
    assert min(visible[6:-6]) > 2500, "The actual encoded crop lost the moving subject"
    assert all(25 < position < 155 for position in positions[6:-6])


def test_explicit_center_mode_remains_stationary_without_running_analysis(monkeypatch):
    from clipfoundry.pipeline import reframe

    def forbidden(*_args, **_kwargs):
        raise AssertionError("An explicit fixed-centre choice must be preserved")

    monkeypatch.setattr(reframe, "analyze", forbidden)
    plan = reframe.plan("unused.mp4", 0, 5, 640, 360, "center", 12)
    assert np.all(plan.cx == .5) and np.all(plan.cy == .5)

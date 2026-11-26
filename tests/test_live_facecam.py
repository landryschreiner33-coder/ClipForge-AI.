"""Drawing the face cam while a stream is live: a picture from the newest whole recorded minute to draw on, and
the box saved where the stream's clips look for it (its own folder, cam.json), never anywhere else."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_review_submitted_live import data  # noqa: F401 - isolated data folder (tmp) and database
from test_review_submitted_routes import H  # the app's own request header


def _minute(path: Path, colour: str, seconds: float = 3) -> None:
    """A stand-in for one recorded minute (three seconds of one colour)."""
    from clipfoundry.pipeline.ffmpeg_utils import ffmpeg_bin

    subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c={colour}:s=320x180:d={seconds}:r=10", "-c:v", "mpeg4", str(path)], check=True)


def _live_project(minutes: int = 0) -> tuple[dict, Path]:
    from clipfoundry import config, db

    project = db.create_project("A live stream", origin="live", status="processing")
    folder = config.projects_dir() / project["id"] / "live"
    folder.mkdir(parents=True)
    for k, colour in zip(range(minutes), ("red", "blue", "green")):
        _minute(folder / f"r001_{k:05d}.mkv", colour)
    return project, folder.parent


def test_the_picture_comes_from_the_newest_whole_minute(data):
    from PIL import Image

    from clipfoundry.api import app

    project, pdir = _live_project(minutes=0)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        empty = client.get(f"/api/autopilot/submissions/live/{project['id']}/frame", headers=H)
        assert empty.status_code == 404 and "Nothing is recorded yet" in empty.json()["detail"]
        for k, colour in enumerate(("red", "blue")):
            _minute(pdir / "live" / f"r001_{k:05d}.mkv", colour)
        shot = client.get(f"/api/autopilot/submissions/live/{project['id']}/frame", headers=H)
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/jpeg"
    out = pdir / "live" / "facecam-frame.jpg"
    red, green, blue = Image.open(out).convert("RGB").getpixel((160, 90))
    assert red > 180 and blue < 80   # the red minute: the blue one is still being written


def test_the_box_is_saved_in_the_streams_folder_and_live_clips_use_it(data):
    from clipfoundry.api import app
    from clipfoundry.pipeline import facecam

    project, pdir = _live_project(minutes=1)
    url = f"/api/autopilot/submissions/live/{project['id']}/facecam"
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get(url, headers=H).json() == {"box": None, "locked": False}
        saved = client.put(url, headers=H, json={"box": [0.7, 0.05, 0.98, 0.4]})
        assert saved.status_code == 200 and saved.json() == {"box": [0.7, 0.05, 0.98, 0.4], "locked": True}
        tiny = client.put(url, headers=H, json={"box": [0.1, 0.1, 0.11, 0.11]})
        assert tiny.status_code == 422
        assert client.get(url, headers=H).json()["box"] == [0.7, 0.05, 0.98, 0.4]   # the bad box changed nothing
    # live renders pass the stream's folder as the project's "dir" (live.make_live_clip)
    assert facecam.chosen(pdir, {}) == {"kind": "manual", "box": [0.7, 0.05, 0.98, 0.4]}
    assert not Path("cam.json").exists()
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.put(url, headers=H, json={"box": None}).json() == {"box": None, "locked": False}
    assert facecam.chosen(pdir, {}) is None


@pytest.mark.parametrize("origin", ["upload", "url"])
def test_only_a_live_streams_recording_can_be_drawn_on(data, origin):
    from clipfoundry import config, db
    from clipfoundry.api import app

    project = db.create_project("A video", origin=origin, status="ready")
    (config.projects_dir() / project["id"] / "live").mkdir(parents=True)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        for path in ("frame", "facecam"):
            assert client.get(f"/api/autopilot/submissions/live/{project['id']}/{path}", headers=H).status_code == 404
        assert client.put(f"/api/autopilot/submissions/live/{project['id']}/facecam", headers=H,
                          json={"box": [0.1, 0.1, 0.4, 0.4]}).status_code == 404
        assert client.get("/api/autopilot/submissions/live/nope/frame", headers=H).status_code == 404
    assert not (config.projects_dir() / project["id"] / "cam.json").exists()


def test_live_rows_offer_to_draw_the_face_cam_while_recording():
    root = Path(__file__).resolve().parents[1] / "frontend/src"
    rows = (root / "components/liveStreams.tsx").read_text()
    assert "Draw the face cam" in rows and "submissions.lockLiveFacecam" in rows
    assert 'item.live.framing !== "off"' in rows   # without a split view there is no cam spot to fill
    assert "<FaceCamBox image" in rows
    assert "image ? <img" in (root / "components/faceCam.tsx").read_text()


def test_a_short_last_minute_still_gives_its_own_picture_never_an_older_one(data):
    """The recording started again: the newest whole minute is a second long. Its own picture comes back, and
    when no picture can be read the old one is gone (409), never shown as new."""
    from PIL import Image

    from clipfoundry.api import app

    project, pdir = _live_project(minutes=2)          # red, blue (blue still being written)
    url = f"/api/autopilot/submissions/live/{project['id']}/frame"
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get(url, headers=H).status_code == 200   # the red minute's picture is on disk now
        _minute(pdir / "live" / "r002_00000.mkv", "blue", seconds=1)   # a new run: a one-second minute
        _minute(pdir / "live" / "r002_00001.mkv", "green")             # being written
        assert client.get(url, headers=H).status_code == 200
        red, green, blue = Image.open(pdir / "live" / "facecam-frame.jpg").convert("RGB").getpixel((160, 90))
        assert blue > 180 and red < 80                       # the one-second minute's own picture
        (pdir / "live" / "r002_00000.mkv").write_bytes(b"not a video")
        broken = client.get(url, headers=H)
    assert broken.status_code == 409 and not (pdir / "live" / "facecam-frame.jpg").exists()

"""Text Stories keep their colours (batch 5c review): every picture is put together in RGB and turned into BT.709
limited range once, so the file's BT.709 tags are true. Before, FFmpeg's default conversion (BT.601) under BT.709
tags made a red background 10 codes off and the chat card's blue 6; a BT.601 phone clip was read as BT.709."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from clipfoundry.makers import chatstory as cs
from test_chat_stories import CHAT, needs_media
from test_text_stories import _espeak, _ready_story, _run, env  # noqa: F401

RED = (200, 60, 40)


def _clip(path: Path, size: str, matrix: str, tags: list[str]) -> Path:
    """A solid RED video converted with `matrix` (what a camera or phone wrote) and tagged with `tags`."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0xC83C28:s={size}:r=30:d=3",
                    "-vf", f"format=rgb24,scale=out_color_matrix={matrix}:out_range=tv,format=yuv420p",
                    "-c:v", "libx264", "-crf", "4", *tags, str(path)], check=True)
    return path


def _rgb(path: Path, at: float, x: int, y: int) -> np.ndarray:
    """The colour a player shows at (x, y): read with the file's own tags (BT.709)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at}", "-i", str(path), "-frames:v", "1", "-vf",
                          f"scale=in_color_matrix=bt709:in_range=tv,format=rgb24,crop=8:8:{x}:{y}", "-f", "rawvideo",
                          "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(8, 8, 3).reshape(-1, 3).mean(axis=0)


def _tags(path: Path) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_space",
                           "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.strip()


@needs_media
def test_background_videos_keep_their_colours_whatever_matrix_they_were_made_with(env):
    from clipfoundry import db
    from clipfoundry.makers import textstory
    from clipfoundry.studio import uploads

    tmp = env["tmp"]
    phone = uploads.store_file("local", _clip(tmp / "sd.mp4", "640x360", "bt601", []), "sd.mp4")  # untagged SD
    hd = uploads.store_file("local", _clip(tmp / "hd.mp4", "1280x720", "bt709", ["-colorspace", "bt709"]), "hd.mp4")
    story, url = _ready_story(env, script="One two three four five six seven eight nine ten.", title="",
                              backgrounds=[{"asset_id": phone["id"], "in_s": 0.5, "out_s": 1.5, "loop": False},
                                           {"asset_id": hd["id"], "in_s": 0.5, "out_s": 1.0, "loop": True}])
    env["client"].post(f"{url}/preview")
    assert [j["status"] for j in _run(env)] == ["done"]
    video = textstory.file_for(db.fetch("text_stories", story["id"]), "preview")
    assert _tags(video) == "bt709"
    first, looped = _rgb(video, 0.5, 4, 4), _rgb(video, 2.2, 4, 4)  # the SD clip, then the HD one's looped part
    assert np.abs(first - RED).max() <= 4, first
    assert np.abs(looped - RED).max() <= 4, looped


@needs_media
def test_the_chat_card_keeps_its_exact_colours(env):
    from clipfoundry import db
    from clipfoundry.makers import textstory

    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"kind": "chat", "script": CHAT}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    espeak = _espeak()
    c.patch(url, json={"chat": {"people": {"Me": {"voice": espeak}, "Sienna": {"voice": espeak}}}})
    c.post(f"{url}/backgrounds/auto")
    c.post(f"{url}/preview")
    assert [j["status"] for j in _run(env)] == ["done"]
    row = db.fetch("text_stories", story["id"])
    video = textstory.file_for(row, "preview")
    assert _tags(video) == "bt709"
    x, y = cs.card_box((360, 640))
    head = _rgb(video, 0.05, x + 56, y + 16)  # the header, between the unread number and the picture
    assert np.abs(head - np.array(cs.THEMES["dark"]["head"])).max() <= 4, head
    # the blue bubbles: the colour is exact, not just close (before: 6 codes off in green)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{row['narration']['times'][-1]['end'] - 0.1}", "-i",
                          str(video), "-frames:v", "1", "-vf", "scale=in_color_matrix=bt709:in_range=tv,format=rgb24",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    frame = np.frombuffer(raw, np.uint8).reshape(640, 360, 3).astype(int)
    blue = np.array(cs.THEMES["dark"]["me"])
    card = frame[y + round(cs.HEAD_H * 360 / 1080) + 4:, x:x + round(cs.CARD_W * 360 / 1080)].reshape(-1, 3)
    near = card[np.abs(card - blue).max(axis=1) < 16]
    assert len(near) > 200 and np.abs(np.median(near, axis=0) - blue).max() <= 2, np.median(near, axis=0)

"""End-to-end ClipForge Clips with real rendered files (slow): Full stories from real synthesized speech,
saved Brain style vs project override for caption placement (CF-07), a restart, "Make & upload clips" to two fake
YouTube channels (CF-03, CF-10) and a re-render that must not post again (CF-12).

Transcription is the fixture's measured script (no speech model is available offline); story detection, framing,
captions, audio, the quality gate and the uploads are the real code paths.
"""
from __future__ import annotations

import json
import subprocess
import time

import numpy as np
import pytest

from multi_fakes import FakeGoogleMulti, FakeTikTokMulti
from story_fixtures import speech_recording
from test_multi_accounts import connect

pytestmark = pytest.mark.slow
H = {"X-ClipFoundry": "1"}
OPEN_A = "So this one time I got completely lost in the forest with only a paper map."
CLOSE_A = "And that's how I learned to never trust an old paper map again."
OPEN_B = "My next story is about the day I tried to bake a wedding cake."
CLOSE_B = "And that's why I still keep a spare cake mix in the cupboard to this day."
PARTS = [
    ("intro", ["Hey everyone, welcome back to the channel.", "Today I have two stories for you."]),
    ("story", [OPEN_A, "The trail split near the creek and the compass kept spinning.",
               "We followed the ridge for an hour while the sun went down behind the pines.",
               "My friend insisted the map was upside down, and honestly he was right.",
               "We finally reached the parking lot long after dark, tired and hungry.", CLOSE_A]),
    ("sponsor", ["Quick thanks to today's sponsor.", "Use my code for a discount, link in the description."]),
    ("story", [OPEN_B, "The oven in that tiny kitchen only had two settings, off and very hot.",
               "The first layer came out black on the bottom, so we started again with more flour.",
               "Someone sat on the frosting bag and the sprinkles ended up everywhere.",
               "In the end we stacked three crooked layers and called it modern art.", CLOSE_B]),
    ("outro", ["Thanks for watching, everyone.", "See you next time."]),
]


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry import db
    from clipfoundry.pipeline import transcribe
    from clipfoundry.publish import tiktok, youtube

    video, transcript = speech_recording(tmp_path / "rec", PARTS)
    monkeypatch.setattr(transcribe, "transcribe", lambda *a, **k: transcript)
    g, t = FakeGoogleMulti(), FakeTikTokMulti()
    for name, value in {"AUTH_URL": f"{g.url}/o/oauth2/v2/auth", "TOKEN_URL": f"{g.url}/token",
                        "REVOKE_URL": f"{g.url}/revoke", "API_URL": f"{g.url}/youtube/v3",
                        "UPLOAD_URL": f"{g.url}/upload/youtube/v3/videos", "CHUNK": 256 * 1024}.items():
        monkeypatch.setattr(youtube, name, value)
    monkeypatch.setattr(tiktok, "AUTH_URL", f"{t.url}/v2/auth/authorize/")
    monkeypatch.setattr(tiktok, "API_URL", f"{t.url}/v2")
    db.init()
    db.save_settings({"youtube_client_id": "cid.apps.googleusercontent.com", "youtube_client_secret": "csecret",
                      "tiktok_client_key": "tkkey", "tiktok_client_secret": "tksecret", "caption_position": "top",
                      "video_preset": "ultrafast"})
    yield {"video": video, "transcript": transcript, "google": g, "tiktok": t, "tmp": tmp_path}
    g.stop()
    t.stop()


def _client():
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    return TestClient(app, base_url="http://127.0.0.1:8765")


def _upload(api, path) -> dict:
    data = path.read_bytes()
    up = api.post("/api/uploads", json={"filename": "two-stories.mp4", "size": len(data)}).json()
    while up["received"] < len(data):
        up = api.put(f"/api/uploads/{up['id']}?offset={up['received']}",
                     content=data[up["received"]:up["received"] + 1_000_000]).json()
    return api.post(f"/api/uploads/{up['id']}/complete").json()


def _wait_project(api, pid: str, timeout: float = 600) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        p = api.get(f"/api/projects/{pid}").json()
        if p["status"] in ("ready", "error", "cancelled"):
            return p
        time.sleep(0.5)
    raise AssertionError("project did not finish")


def _wait_clip(api, cid: str, timeout: float = 300) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        c = api.get(f"/api/clips/{cid}").json()
        if c["status"] in ("ready", "error"):
            return c
        time.sleep(0.5)
    raise AssertionError("clip did not render")


def _caption_rows(path) -> float:
    """Vertical centre (0 top .. 1 bottom) of the bright caption pixels over frames sampled across the clip."""
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
                                       str(path)], capture_output=True, text=True).stdout)
    duration = float(probe["format"]["duration"])
    centres = []
    for k in range(1, 9):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{duration * k / 9:.2f}", "-i", str(path), "-frames:v",
                              "1", "-vf", "scale=270:480,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True).stdout
        frame = np.frombuffer(raw, np.uint8).reshape(480, 270)
        rows = np.nonzero((frame > 200).sum(axis=1) > 3)[0]
        if len(rows):
            centres.append(rows.mean() / 480)
    assert centres, "no captions visible"
    return float(np.median(centres))


def _final_words(clip: dict) -> str:
    from clipfoundry.pipeline import artifact

    final = artifact.final_transcript(clip["render_info"]) or {}
    return " ".join(w["w"] for w in final.get("words", []))


def test_full_stories_real_render_brain_style_override_restart_and_two_channel_upload(env):
    from clipfoundry import db
    from clipfoundry.pipeline import audio_timing

    g, t = env["google"], env["tiktok"]
    with _client() as api:
        a = connect(api, g, "youtube", channel="UCchanA", title="Channel A")["connections"][0]
        b = next(c for c in connect(api, g, "youtube", channel="UCchanB", title="Channel B")["connections"]
                 if c["account_id"] == "UCchanB")
        tk = connect(api, t, "tiktok", open_id="open-a", name="Creator A")["connections"]
        tk = next(c for c in tk if c["platform"] == "tiktok")
        style = api.post("/api/studio/styles", json={"name": "My story style", "values": {
            "caption_position": "bottom"}, "modes": ["full_stories", "highlights"], "make_default": True}).json()
        asset = _upload(api, env["video"])
        made = api.post("/api/studio/clips", json={
            "asset_id": asset["id"], "mode": "full_stories", "style_id": "saved", "upload": {
                "intent": "make_and_upload", "destinations": [a["id"], b["id"], tk["id"]], "privacy": "private",
                "made_for_kids": False, "reuse_basis": "owned", "agreed": True}})
        assert made.status_code == 200, made.text
        pid = made.json()["id"]
        project = _wait_project(api, pid)
        assert project["status"] == "ready", project
        stories = api.get(f"/api/projects/{pid}/stories").json()["stories"]
        assert [s["kind"] for s in stories] == ["gap", "story", "gap", "story", "gap"]
        clips = sorted(project["clips"], key=lambda c: c["start"])
        assert len(clips) == 2 and all(c["status"] == "ready" for c in clips)
        decision = next(d for d in api.get(f"/api/projects/{pid}/guidance").json()["snapshot"]["decisions"]
                        if d["field"] == "caption_position")
        assert decision["value"] == "bottom" and decision["from"]["name"] == "My story style"
        for clip, (opening, closing) in zip(clips, ((OPEN_A, CLOSE_A), (OPEN_B, CLOSE_B))):
            full = db.get_clip(clip["id"])
            out = full["output_path"]
            info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                                              "-select_streams", "v", "-of", "json", out], capture_output=True,
                                             text=True).stdout)["streams"][0]
            assert (info["width"], info["height"]) == (1080, 1920)
            words = _final_words(full)
            assert words.startswith(opening.rstrip(".")[:30]) and words.rstrip(".").endswith(closing.rstrip(".")[-25:])
            assert audio_timing.require_valid(out)  # stored AAC packet clocks, auto-repair off
            assert _caption_rows(out) > 0.6  # lower captions, from the saved style
        # Make & upload: each clip once to each YouTube channel; TikTok waits for the owner's OK
        end = time.time() + 120
        while time.time() < end and len(g.videos) < 4:
            time.sleep(0.5)
        why = [[(d["account"], d["state"], d["text"]) for d in db.get_clip(c["id"])["analysis"].get("destinations")]
               for c in clips]
        assert len(g.uploads_to("UCchanA")) == 2 and len(g.uploads_to("UCchanB")) == 2, why
        for clip in clips:
            data = open(db.get_clip(clip["id"])["output_path"], "rb").read()
            assert sum(v["bytes"] == data for v in g.videos.values()) == 2
            dests = {d["account"]: d["state"] for d in db.get_clip(clip["id"])["analysis"]["destinations"]}
            assert dests["Creator A"] == "review"
        assert not t.inits

        # CF-12: a re-render makes new bytes; nothing is uploaded again by itself
        before = len(g.videos)
        api.post(f"/api/clips/{clips[0]['id']}/render", headers=H)
        _wait_clip(api, clips[0]["id"])
        time.sleep(1.0)
        assert len(g.videos) == before

        # CF-07 override: the same file with this project's own caption choice
        over = api.post("/api/studio/clips", json={"asset_id": asset["id"], "mode": "full_stories",
                                                   "style_id": "saved", "choices": {"caption_position": "top"}})
        over_project = _wait_project(api, over.json()["id"])
        assert db.get_project(over_project["id"])["info"].get("transcript_reused_from") == pid
        top_clip = db.get_clip(sorted(over_project["clips"], key=lambda c: c["start"])[0]["id"])
        assert _caption_rows(top_clip["output_path"]) < 0.4
        api.patch(f"/api/studio/styles/{style['id']}", json={"revision": 1, "values": {"caption_position": "middle"}})

    db._ready.clear()  # noqa: SLF001 - a restart: the next app start opens the database afresh
    with _client() as api:
        first = clips[1]["id"]
        api.post(f"/api/clips/{first}/render", headers=H)
        again = _wait_clip(api, first)
        assert again["status"] == "ready"
        # the project keeps the style revision its plan used: still lower captions, not the newer "middle"
        assert _caption_rows(db.get_clip(first)["output_path"]) > 0.6
        snap = api.get(f"/api/projects/{pid}/guidance").json()["snapshot"]
        assert next(e for e in snap["entries"] if e["level"] == "style")["revision"] == 1

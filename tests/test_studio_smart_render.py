"""Smart editing end to end with real speech (slow): two recordings with long pauses and a false start, a picture named after something said and no music of your own. "Make a YouTube video" with "Edit it for me" cuts the
dead air and the earlier take, shows the picture over the video when it is said, adds free music made by ClipForge
and soft whooshes, and the checked final render plays exactly that plan: shorter than the footage, the picture on
screen at its time, music under the pauses, captions in sync. "Edit it again" fast-paced is a new version with
punch-in zooms; Undo goes back.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from story_fixtures import speech_recording

pytestmark = pytest.mark.slow
SR = 16000


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.pipeline import transcribe

    a, ta = speech_recording(tmp_path / "a", [
        ("story", ["Welcome back to the channel.", "Today we finally drive up to the lake."]),
        ("story", ["The water was...", "The water was really cold and very clear.",
                   "We swam for hours until the sun went down."])], size="1280x720")
    b, tb = speech_recording(tmp_path / "b", [
        ("story", ["On the way home we stopped for dinner.", "Thanks for watching and see you next time."])],
        size="1280x720")
    lake = tmp_path / "Lake view.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0xff00ff:s=1600x900:d=1",
                    "-frames:v", "1", str(lake)], check=True)
    scripts = {"a.mp4": ta, "b.mp4": tb}
    (tmp_path / "a.mp4").write_bytes(a.read_bytes())
    (tmp_path / "b.mp4").write_bytes(b.read_bytes())

    def fake_transcribe(wav, duration, *args, **kw):  # the measured scripts stand in for a speech model offline
        from clipfoundry import db

        source = next(row for row in db.select("assets") if Path(row["path"]).parent == Path(wav).parent)
        return scripts.get(source["filename"]) or {"language": "", "duration": duration, "segments": []}

    monkeypatch.setattr(transcribe, "transcribe", fake_transcribe)
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        yield {"api": api, "files": {"a": tmp_path / "a.mp4", "b": tmp_path / "b.mp4", "lake": lake},
               "ta": ta, "tb": tb, "tmp": tmp_path}


def _upload(api, path) -> dict:
    data = path.read_bytes()
    up = api.post("/api/uploads", json={"filename": path.name, "size": len(data)}).json()
    while up["received"] < len(data):
        up = api.put(f"/api/uploads/{up['id']}?offset={up['received']}",
                     content=data[up["received"]:up["received"] + 1_000_000]).json()
    r = api.post(f"/api/uploads/{up['id']}/complete")
    assert r.status_code == 200, r.text
    return r.json()


def _wait(api, vid, done, timeout=400) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        v = api.get(f"/api/studio/videos/{vid}").json()
        if done(v):
            return v
        failed = [j for j in v["jobs"] if j["status"] == "failed"]
        assert not failed, failed
        time.sleep(0.4)
    raise AssertionError(f"timed out: {v['status']} {v['jobs']}")


def _frame_rgb(path: Path, t: float) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                                   "-vf", "scale=64:36", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return np.frombuffer(raw, dtype=np.uint8).reshape(36, 64, 3).astype(float)


def _pcm(path: Path) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar",
                                   str(SR), "-"])
    return np.frombuffer(raw, dtype=np.float32)


def _rms(x: np.ndarray, t0: float, t1: float) -> float:
    seg = x[int(t0 * SR):int(t1 * SR)]
    return float(np.sqrt((seg ** 2).mean())) if len(seg) else 0.0


def test_edit_it_for_me_trims_adds_pictures_music_and_effects_and_renders_that(env):
    from clipfoundry import db
    from clipfoundry.studio import engine

    api, f = env["api"], env["files"]
    ids = {k: _upload(api, p)["id"] for k, p in f.items()}
    r = api.post("/api/studio/videos", json={
        "name": "Lake day", "asset_ids": [ids["a"], ids["lake"], ids["b"]], "style_id": "settings",
        "brief": {"video_type": "Travel vlog", "aspect_ratio": "16:9", "feel": "balanced", "captions": True,
                  "music": "auto", "smart_edit": "smart", "sound_effects": True, "broll_images": True},
        "remember": {"enabled": False}})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
    v = _wait(api, vid, lambda v: any(a["kind"] == "preview" for a in v["artifacts"]))
    plan = v["plan"]
    smart = plan["smart"]
    source_s = sum(a["duration"] for a in v["assets"] if a["id"] in (ids["a"], ids["b"]))
    # trimmed: the 2.6 s gaps and the silence at the ends are cut, the false start left out
    assert v["duration"] < source_s - 4, (v["duration"], source_s)
    assert smart["stats"]["pauses_cut"] >= 1 and smart["stats"]["retakes"] == 1
    off = [o["summary"] for o in plan["outline"] if o["summary"].startswith("Left out")]
    assert off == ["Left out (an earlier take of the next line): The water was..."]
    # the picture is over the video, when "lake" is said, not a slide of its own
    assert [c["kind"] for c in plan["clips"]].count("image") == 0
    ov = plan["overlays"]
    assert [o["asset_id"] for o in ov] == [ids["lake"]] and "lake" in ov[0]["why"]
    shown = v["overlay_timeline"][0]
    # free music made by ClipForge and soft effects, all added to Your media and marked as automatic
    music = [i for i in plan["audio"] if i["role"] == "music"]
    fx = [i for i in plan["audio"] if i["role"] == "effect"]
    assert len(music) == 1 and music[0]["auto"] and music[0]["loop"] and music[0]["duck"]
    assert any(i["label"].startswith("Whoosh") for i in fx) and any(i["label"].startswith("Soft swish") for i in fx)
    names = {a["filename"] for a in v["assets"]}
    assert any(n.startswith("ClipForge music - ") for n in names)
    assert smart["ai"]["used"] is False and "ClipForge AI" in " ".join(plan["notes"])
    assert engine.validate(plan, {a["id"]: a for a in db.select("assets")}) == []

    # the final render plays exactly this plan
    rev = v["plan_revision"]
    assert api.post(f"/api/studio/videos/{vid}/render", json={"revision": rev}).status_code == 200
    _wait(api, vid, lambda v: any(a["kind"] == "final" and a["revision"] == rev for a in v["artifacts"]), 600)
    art = next(a for a in db.select("studio_artifacts", "project_id = ? AND kind = 'final'", (vid,)))
    info = art["info"]
    assert abs(info["duration"] - engine.duration_ms(plan) / 1000) < 0.1
    assert info["audio_timing"]["valid"]
    final = Path(art["path"])
    mid = (shown["out_start_ms"] + shown["out_end_ms"]) / 2000
    pic = _frame_rgb(final, mid)[4:26]  # above the captions
    assert pic[..., 0].mean() > 180 and pic[..., 2].mean() > 180 and pic[..., 1].mean() < 90  # the magenta picture
    before = _frame_rgb(final, max(0.2, shown["out_start_ms"] / 1000 - 1.5))[4:26]
    assert before[..., 1].mean() < 90 and abs(before[..., 0].mean() - pic[..., 0].mean()) > 100  # the dark slate
    # music is heard between sentences (the recordings themselves are silent there), and dips under speech
    x = _pcm(final)
    words = [w for w in __import__("json").loads(Path(str(final).replace("final.mp4", "final.timeline.json"))
                                                 .read_text())["words"]]
    said = [w["w"] for w in words]
    # every kept word is captioned, also a last word whose measured end runs into a cut pause
    assert said == [w for s in env["ta"]["segments"] + env["tb"]["segments"] if s["text"] != "The water was..."
                    for w in s["text"].split()], said
    gaps = [(a["end"] + 0.05, b["start"] - 0.05) for a, b in zip(words, words[1:]) if b["start"] - a["end"] > 0.3]
    assert gaps, words
    g0, g1 = max(gaps, key=lambda g: g[1] - g[0])
    assert _rms(x, g0, g1) > 0.003  # music, not silence
    talk = next(w for w in words if w["end"] - w["start"] > 0.15)
    assert _rms(x, talk["start"], talk["end"]) > _rms(x, g0, g1)  # speech stays on top

    # Edit it again, fast-paced: a new version with punch-in zooms; Undo goes back
    r = api.post(f"/api/studio/videos/{vid}/smart", json={"base_revision": rev, "choices": {"smart_edit": "tight"}})
    assert r.status_code == 200, r.text
    v2 = _wait(api, vid, lambda v: v["plan_revision"] > rev and not any(
        j["kind"] == "video_smart" and j["status"] in ("queued", "running") for j in v["jobs"]))
    assert v2["plan"]["smart"]["level"] == "tight" and any(c.get("zoom") for c in v2["plan"]["clips"])
    assert v2["duration"] <= v["duration"] + 0.05
    assert [i["role"] for i in v2["plan"]["audio"]].count("music") == 1  # the music is not doubled
    back = api.post(f"/api/studio/videos/{vid}/undo", json={"base_revision": v2["plan_revision"]}).json()
    assert back["plan"]["clips"] == plan["clips"]

"""Make a YouTube video (CF-09) end to end with real files (slow): three mixed-rate videos (two with real speech),
a supplied image and music; the brief's avoid request; reorder/trim/shorten edits as revisions; an unsupported edit
and a stale edit refused; exact reopen; preview and final renders with matching time maps, captions and audio
checks; cancellation and a missing source.
"""
from __future__ import annotations

import json
import subprocess
import time

import pytest

from story_fixtures import speech_recording

pytestmark = pytest.mark.slow


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.pipeline import transcribe

    v1, t1 = speech_recording(tmp_path / "a", [("story", [
        "Welcome to our trip to the mountains.", "We started early before sunrise.",
        "The road climbed through the pine forest for an hour."])])
    v3, t3 = speech_recording(tmp_path / "c", [("story", [
        "Here is the view from the very top.", "This is the boring part we skip.",
        "And this is where we finally had lunch together."])])
    a = tmp_path / "a_24fps_44k.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(v1), "-r", "24", "-ar", "44100", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(a)], check=True)
    b = tmp_path / "b_30fps_48k.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:d=5", "-f",
                    "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=5", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(b)], check=True)
    c = tmp_path / "c_25fps_32k_mono.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(v3), "-r", "25", "-ar", "32000", "-ac", "1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(c)], check=True)
    img = tmp_path / "broll.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=steelblue:s=1280x720:d=1",
                    "-frames:v", "1", str(img)], check=True)
    music = tmp_path / "music.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=220:sample_rate=48000:duration=60", "-c:a", "aac", str(music)], check=True)
    by_duration = {}

    def fake_transcribe(wav, duration, *a, **k):  # the measured scripts stand in for a speech model offline
        best = min((t1, t3), key=lambda script: abs(script["duration"] - duration))
        if abs(best["duration"] - duration) < 0.2:
            return best
        return {"language": "", "duration": duration, "source": "fixture", "segments": []}

    monkeypatch.setattr(transcribe, "transcribe", fake_transcribe)
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        yield {"api": api, "files": {"a": a, "b": b, "c": c, "img": img, "music": music}, "t1": t1, "t3": t3,
               "by_duration": by_duration}


def _upload(api, path) -> dict:
    data = path.read_bytes()
    up = api.post("/api/uploads", json={"filename": path.name, "size": len(data)}).json()
    while up["received"] < len(data):
        up = api.put(f"/api/uploads/{up['id']}?offset={up['received']}",
                     content=data[up["received"]:up["received"] + 1_000_000]).json()
    r = api.post(f"/api/uploads/{up['id']}/complete")
    assert r.status_code == 200, r.text
    return r.json()


def _wait(api, vid, done, timeout=300) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        v = api.get(f"/api/studio/videos/{vid}").json()
        if done(v):
            return v
        failed = [j for j in v["jobs"] if j["status"] == "failed"]
        assert not failed, failed
        time.sleep(0.4)
    raise AssertionError(f"timed out: {v['status']} {v['jobs']}")


def test_cf09_mixed_media_assembly_edits_reopen_and_server_render(env):
    from clipfoundry import db
    from clipfoundry.studio import engine

    api, f = env["api"], env["files"]
    ids = {k: _upload(api, p)["id"] for k, p in f.items()}
    r = api.post("/api/studio/videos", json={
        "name": "Mountain trip", "asset_ids": [ids["a"], ids["b"], ids["img"], ids["c"]], "style_id": "settings",
        "brief": {"video_type": "Travel vlog", "audience": "Friends and family", "goal": "Share the trip",
                  "aspect_ratio": "16:9", "feel": "balanced", "captions": True, "music": "supplied",
                  "music_asset_id": ids["music"], "must_keep": "lunch", "avoid": "boring part"},
        "remember": {"enabled": True, "name": "Trip style"}})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
    v = _wait(api, vid, lambda v: any(a["kind"] == "preview" for a in v["artifacts"]))
    plan = v["plan"]
    assert [c["asset_id"] for c in plan["clips"]][:3] == [ids["a"], ids["b"], ids["img"]]
    assert any("boring part" in n for n in plan["notes"])  # the avoid request removed that sentence
    c_parts = [c for c in plan["clips"] if c["asset_id"] == ids["c"]]
    assert len(c_parts) == 2 and c_parts[0]["out_ms"] < c_parts[1]["in_ms"]
    assert plan["transition"] == {"type": "dissolve", "ms": 400} and plan["music"]["asset_id"] == ids["music"]
    assert [s["name"] for s in api.get("/api/studio/styles").json()] == ["Trip style"]  # Remember this style
    assert api.get("/api/studio/styles").json()[0]["values"].get("feel") == "balanced"
    assert "must_keep" not in api.get("/api/studio/styles").json()[0]["values"]

    def edit(change, base=None):
        cur = api.get(f"/api/studio/videos/{vid}").json()["plan_revision"]
        return api.post(f"/api/studio/videos/{vid}/edits", json={"base_revision": base or cur, "edit": change})

    rev1 = v["plan_revision"]
    assert edit({"op": "move", "clip_id": plan["clips"][1]["id"], "to": 3}).status_code == 200
    assert edit({"op": "request", "text": "shorten the introduction by 2 seconds"}).status_code == 200
    trimmed = edit({"op": "trim", "clip_id": c_parts[1]["id"], "in_ms": c_parts[1]["in_ms"],
                    "out_ms": c_parts[1]["out_ms"] - 300})
    assert trimmed.status_code == 200
    bad = edit({"op": "color_grade", "look": "teal"})
    assert bad.status_code == 422 and "not supported" in bad.json()["detail"]
    vague = edit({"op": "request", "text": "add a laser effect"})
    assert vague.status_code == 422 and "cannot do that" in vague.json()["detail"]
    stale = edit({"op": "remove", "clip_id": plan["clips"][2]["id"]}, base=rev1)
    assert stale.status_code == 409  # another tab's newer edit is never overwritten
    keep = edit({"op": "remove", "clip_id": c_parts[1]["id"]})
    assert keep.status_code == 422 and "keep" in keep.json()["detail"]  # it holds "lunch", a must-keep
    v = api.get(f"/api/studio/videos/{vid}").json()
    assert v["plan_revision"] == rev1 + 3
    saved = v["plan"]
    intro = next(c for c in saved["clips"] if c["asset_id"] == ids["a"])
    assert intro["in_ms"] > plan["clips"][0]["in_ms"]  # shortened at a sentence start
    reopened = api.get(f"/api/studio/videos/{vid}").json()["plan"]
    assert reopened == saved  # save/reopen reproduces the plan exactly
    restored = api.post(f"/api/studio/videos/{vid}/restore", json={"revision": rev1}).json()
    assert restored["plan"]["clips"] == plan["clips"] and restored["plan_revision"] == rev1 + 4

    final = api.post(f"/api/studio/videos/{vid}/render", json={"revision": rev1 + 3})
    assert final.status_code == 200
    v = _wait(api, vid, lambda v: any(a["kind"] == "final" and a["revision"] == rev1 + 3 for a in v["artifacts"]))
    art = next(a for a in db.select("studio_artifacts", "project_id = ? AND kind = 'final'", (vid,)))
    info = art["info"]
    assert (info["width"], info["height"]) == (1920, 1080)
    assert abs(info["duration"] - engine.duration_ms(saved) / 1000) < 0.1
    assert info["audio_timing"]["valid"] and info["audio_timing"]["largest_clock_error_s"] < 0.001
    words = json.loads(open(art["path"].replace("final.mp4", "final.timeline.json")).read())["words"]
    assert [w["w"] for w in words][:2] != [] and "boring" not in " ".join(w["w"] for w in words)
    first = next(w for w in words if w["clip_id"] == intro["id"])
    seg = next(t for t in info["timeline"] if t["clip_id"] == intro["id"])
    assert abs(first["start"] - (seg["out_start_ms"] / 1000 + first["src_start"] - seg["src_in_ms"] / 1000)) < 0.002
    prev = next(a for a in db.select("studio_artifacts", "project_id = ? AND kind = 'preview' AND revision = ?",
                                     (vid, rev1 + 3)))
    assert prev["info"]["timeline"] == info["timeline"]  # preview and export follow the same plan
    media = api.get(f"/api/studio/videos/{vid}/media?kind=final&revision={rev1 + 3}&download=1")
    assert media.status_code == 200 and media.content[:12].find(b"ftyp") >= 0
    exported = api.get(f"/api/studio/videos/{vid}/export?revision={rev1 + 3}").json()
    assert exported["plan"] == saved and exported["format"] == "clipforge.edit-plan/v1"

    # cancellation: the render stops, no artifact appears for that revision, the plan stays
    api.post(f"/api/studio/videos/{vid}/render", json={"revision": rev1 + 4})
    api.post(f"/api/studio/videos/{vid}/cancel")
    time.sleep(2)
    v = api.get(f"/api/studio/videos/{vid}").json()
    assert not any(a["kind"] == "final" and a["revision"] == rev1 + 4 for a in v["artifacts"])
    assert v["status"] != "rendering"

    # a missing original is named, not rendered around
    import os

    asset_b = db.fetch("assets", ids["b"])
    os.chmod(asset_b["path"], 0o600)
    os.remove(asset_b["path"])
    refused = edit({"op": "set", "field": "transition", "value": "cut"})
    assert refused.status_code == 422 and "missing" in refused.json()["detail"]  # caught before any render
    api.post(f"/api/studio/videos/{vid}/render", json={"revision": rev1 + 4})  # the canceled render, asked again
    end = time.time() + 60
    while time.time() < end:
        job = api.get(f"/api/studio/videos/{vid}").json()["jobs"][0]
        if job["status"] in ("failed", "done"):
            break
        time.sleep(0.4)
    assert job["status"] == "failed" and "missing" in job["error"]

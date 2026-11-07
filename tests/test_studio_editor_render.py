"""Full-video renders through the segmented engine (slow, real FFmpeg): a long sequence of many short pieces stays in
sync to the frame, voiceover/music/effects tracks are heard where the plan puts them (music ducks under speech, a
muted track is silent), and footage and a voiceover added after the rough cut reach the checked final file, with
undo reusing an earlier identical render.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.slow
SR = 48000


def _tone_video(path: Path, seconds: float, freq: int, size: str = "640x360", rate: int = 30,
                quiet_after: float | None = None) -> Path:
    vol = f",volume='if(gte(t,{quiet_after}),0,1)':eval=frame" if quiet_after is not None else ""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
                    "-af", f"volume=0.5{vol}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(path)], check=True)
    return path


def _tone(path: Path, seconds: float, freq: int) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:sample_rate=44100:duration={seconds}", "-af", "volume=0.5",
                    str(path)], check=True)
    return path


def _pcm(path: Path) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar",
                                   str(SR), "-"])
    return np.frombuffer(raw, dtype=np.float32)


def _band(x: np.ndarray, t0: float, t1: float, freq: float) -> float:
    """Amplitude of the tone near `freq` between t0 and t1 seconds (Hann-windowed FFT, independent of the window
    length)."""
    seg = x[int(t0 * SR):int(t1 * SR)]
    win = np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg * win)) * 2 / win.sum()
    bins = np.fft.rfftfreq(len(seg), 1 / SR)
    return float(spec[(bins > freq - 15) & (bins < freq + 15)].max())


def _asset(path: Path, kind: str) -> dict:
    from clipfoundry.pipeline.ffmpeg_utils import probe
    from clipfoundry.studio import uploads

    info = probe(path) if kind == "video" else uploads.probe_audio(path)
    return {"id": path.stem, "kind": kind, "filename": path.name, "path": str(path), "sha256": path.stem,
            "probe": info}


def _plan(clips: list[dict], **extra) -> dict:
    from clipfoundry.studio import engine

    return {"schema": engine.SCHEMA, "timebase": 1000, "engine": engine.ENGINE,
            "output": {"aspect": "16:9", "fps": 30}, "layout": "fill", "clips": clips,
            "transition": {"type": "cut", "ms": 0}, "title": {"enabled": False, "text": "", "ms": 2500},
            "captions": {"enabled": False, "style": "clean", "position": "bottom", "size": "medium"},
            "audio": [], "tracks": engine.default_tracks(), "word_fixes": {}, "outline": [], "notes": [], **extra}


def test_a_long_sequence_of_many_pieces_stays_in_sync_to_the_frame(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.studio import engine

    freqs = {"low": 300, "mid": 700, "high": 1500}
    files = {name: _asset(_tone_video(tmp_path / f"{name}.mp4", 20, f, rate=(24, 25, 30)[k]), "video")
             for k, (name, f) in enumerate(freqs.items())}
    names = list(freqs)
    clips = []
    for n in range(120):  # 120 clips of 0.6 to 1.1 s, never a frame-friendly length
        src = names[n % 3]
        start = (n * 137) % 15000
        clips.append({"id": f"c{n}", "asset_id": src, "kind": "video", "in_ms": start,
                      "out_ms": start + 600 + (n * 53) % 500, "label": src, "gain_db": 0.0, "include": True})
    plan = _plan(clips, transition={"type": "dissolve", "ms": 120})
    assert engine.validate(plan, files) == []
    out = tmp_path / "r" / "preview.mp4"
    info = engine.render(plan, files, {}, out, preview=True, cache_dir=tmp_path / "pieces")
    els, overlap = engine.frame_map(plan, 30)
    assert info["frames"] == els[-1]["end_f"] == round(engine.duration_ms(plan) * 30 / 1000)
    assert info["pieces"] == 120 + 119  # every body and every join is its own small FFmpeg run
    assert abs(info["duration"] - info["frames"] / 30) < 0.02
    assert info["audio_timing"]["valid"] and info["audio_timing"]["largest_clock_error_s"] < 0.001
    frames = subprocess.check_output(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
                                      "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(out)])
    assert int(frames) == info["frames"]
    pcm = _pcm(out)
    # in the middle of every element, its own source tone dominates: no drift after 120 joins
    for e in els:
        mid = (e["start_f"] + e["frames"] / 2) / 30
        heard = {name: _band(pcm, mid - 0.08, mid + 0.08, f) for name, f in freqs.items()}
        assert max(heard, key=heard.get) == e["asset_id"], (e["clip_id"], heard)
    # rendering again reuses every piece (nothing re-encoded), and the file is identical in length
    t = time.monotonic()
    again = engine.render(plan, files, {}, tmp_path / "r2" / "preview.mp4", preview=True,
                          cache_dir=tmp_path / "pieces")
    assert again["frames"] == info["frames"] and time.monotonic() - t < 60


def test_voiceover_music_and_effects_tracks_are_heard_where_planned(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.studio import engine

    talk = _asset(_tone_video(tmp_path / "talk.mp4", 8, 440, quiet_after=4.0), "video")  # someone talks 0-4 s
    other = _asset(_tone_video(tmp_path / "other.mp4", 6, 440), "video")
    vo = _asset(_tone(tmp_path / "vo.wav", 2, 880), "audio")
    music = _asset(_tone(tmp_path / "music.mp3", 3, 220), "audio")
    fx = _asset(_tone(tmp_path / "fx.ogg", 1, 1320), "audio")
    assets = {a["id"]: a for a in (talk, other, vo, music, fx)}
    clips = [{"id": "c1", "asset_id": "talk", "kind": "video", "in_ms": 0, "out_ms": 8000, "label": "talk",
              "gain_db": 0.0, "include": True},
             {"id": "c2", "asset_id": "other", "kind": "video", "in_ms": 0, "out_ms": 4000, "label": "other",
              "gain_db": 0.0, "include": True, "mute": True}]
    audio = [{"id": "a1", "asset_id": "music", "role": "music", "label": "music", "start_ms": 0, "in_ms": 0,
              "out_ms": None, "length_ms": None, "gain_db": -6.0, "mute": False, "fade_in_ms": 0, "fade_out_ms": 0,
              "duck": True, "loop": True, "anchor": None},
             {"id": "a2", "asset_id": "vo", "role": "voiceover", "label": "vo", "start_ms": 0, "in_ms": 0,
              "out_ms": 2000, "length_ms": None, "gain_db": 0.0, "mute": False, "fade_in_ms": 0, "fade_out_ms": 0,
              "duck": False, "loop": False, "anchor": {"clip_id": "c2", "offset_ms": 1000}},
             {"id": "a3", "asset_id": "fx", "role": "effect", "label": "fx", "start_ms": 5000, "in_ms": 0,
              "out_ms": 1000, "length_ms": None, "gain_db": 0.0, "mute": False, "fade_in_ms": 0, "fade_out_ms": 0,
              "duck": False, "loop": False, "anchor": None}]
    plan = _plan(clips, audio=audio)
    tracks = engine.default_tracks()
    tracks["effects"]["mute"] = True
    plan["tracks"] = tracks
    assert engine.validate(plan, assets) == []
    info = engine.render(plan, assets, {}, tmp_path / "r" / "final.mp4", preview=True)
    pcm = _pcm(tmp_path / "r" / "final.mp4")
    assert info["audio_timing"]["valid"] and abs(info["duration"] - 12.0) < 0.05
    # the music loops under the whole video and dips while someone speaks (0-4 s), never the speech itself
    under_speech, alone = _band(pcm, 1.0, 3.5, 220), _band(pcm, 5.0, 7.5, 220)
    assert 20 * np.log10(alone / under_speech) > 6, (under_speech, alone)
    assert _band(pcm, 6.2, 7.8, 220) > 0.7 * alone  # still playing after the 3 s file looped twice
    assert 20 * np.log10(alone / _band(pcm, 9.3, 10.8, 220)) > 6  # it ducks under the voiceover as well
    assert info["ducking"]["depth_db"] == 12.0 and 0.3 < info["ducking"]["speech_share"] < 0.7
    # the voiceover follows its clip (c2 starts at 8 s, +1 s); the muted clip's own sound is silent
    assert _band(pcm, 9.2, 10.8, 880) > 50 * _band(pcm, 1.0, 2.6, 880)
    assert _band(pcm, 8.2, 11.8, 440) < 0.01 * _band(pcm, 1.0, 3.5, 440)
    # the effects track is muted: its sound is absent where it was placed
    assert _band(pcm, 5.1, 5.9, 1320) < 0.01 * _band(pcm, 9.2, 10.8, 880)


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
        time.sleep(0.3)
    raise AssertionError(f"timed out: {v['status']} {v['jobs']}")


def test_footage_and_voiceover_added_after_the_rough_cut_reach_the_checked_render(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.pipeline import transcribe

    monkeypatch.setattr(transcribe, "transcribe", lambda wav, duration, *a, **k: {
        "language": "", "duration": duration, "source": "fixture", "segments": []})
    first = _tone_video(tmp_path / "first.mp4", 4, 300)
    later = _tone_video(tmp_path / "later.mp4", 3, 1500, size="480x480")
    voice = _tone(tmp_path / "voice.m4a", 1.5, 880)
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        a = _upload(api, first)
        r = api.post("/api/studio/videos", json={"name": "Later", "asset_ids": [a["id"]], "style_id": "settings",
                                                 "brief": {"captions": False, "feel": "energetic"}})
        assert r.status_code == 200, r.text
        vid = r.json()["id"]
        v = _wait(api, vid, lambda v: any(x["kind"] == "preview" for x in v["artifacts"]))
        b, vo = _upload(api, later), _upload(api, voice)
        v = api.post(f"/api/studio/videos/{vid}/media", json={"asset_ids": [b["id"], vo["id"]]}).json()
        assert v["bin"] == [a["id"], b["id"], vo["id"]]

        def edit(change):
            cur = api.get(f"/api/studio/videos/{vid}").json()["plan_revision"]
            res = api.post(f"/api/studio/videos/{vid}/edits", json={"base_revision": cur, "edit": change})
            assert res.status_code == 200, res.text
            return res.json()

        v = edit({"op": "insert", "asset_id": b["id"], "at": 0})
        inserted = v["plan"]["clips"][0]
        v = edit({"op": "add_audio", "asset_id": vo["id"], "role": "voiceover", "clip_id": v["plan"]["clips"][1]["id"],
                  "offset_ms": 500})
        rev = v["plan_revision"]
        assert [s["clip_id"] for s in v["timeline"]][0] == inserted["id"]
        assert v["audio_timeline"][0]["out_start_ms"] == 3500  # 3 s inserted clip, then 0.5 s into the next
        final = api.post(f"/api/studio/videos/{vid}/render", json={"revision": rev})
        assert final.status_code == 200
        v = _wait(api, vid, lambda v: any(x["kind"] == "final" and x["revision"] == rev for x in v["artifacts"]))
        art = db.select("studio_artifacts", "project_id = ? AND kind = 'final' AND revision = ?", (vid, rev))[0]
        assert art["info"]["timeline"][0]["clip_id"] == inserted["id"] and art["info"]["audio_timing"]["valid"]
        pcm = _pcm(Path(art["path"]))
        assert _band(pcm, 3.6, 4.9, 880) > 20 * _band(pcm, 0.5, 2.5, 880)
        assert _band(pcm, 0.5, 2.5, 1500) > 20 * _band(pcm, 0.5, 2.5, 300)  # the inserted clip plays first
        # undo, then redo: the redo's plan equals a rendered revision, so its preview is reused, not re-rendered
        v = api.get(f"/api/studio/videos/{vid}").json()
        _wait(api, vid, lambda v: any(x["kind"] == "preview" and x["revision"] == rev for x in v["artifacts"]))
        u = api.post(f"/api/studio/videos/{vid}/undo", json={"base_revision": rev}).json()
        assert not u["audio_timeline"] and u["can_redo"]
        rr = api.post(f"/api/studio/videos/{vid}/redo", json={"base_revision": u["plan_revision"]}).json()
        _wait(api, vid, lambda v: any(x["kind"] == "preview" and x["revision"] == rr["plan_revision"]
                                      for x in v["artifacts"]))
        reused = db.select("studio_artifacts", "project_id = ? AND kind = 'preview' AND revision = ?",
                           (vid, rr["plan_revision"]))[0]
        assert reused["info"].get("reused_from") == rev
        original = db.select("studio_artifacts", "project_id = ? AND kind = 'preview' AND revision = ?",
                             (vid, rev))[0]
        assert reused["sha256"] == original["sha256"]
        v = api.get(f"/api/studio/videos/{vid}").json()
        assert v["preview"] == {"revision": rr["plan_revision"], "stale": False}

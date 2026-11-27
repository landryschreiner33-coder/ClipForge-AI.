"""An example video measured for real and its choices proven in a new project (slow, real FFmpeg; CF2-25/26).

The handoff's acceptance example: an example with short shots, lower-third captions and music that is quieter
during speech is uploaded and analyzed; its supported choices are saved as an Example style; a new full-video
project that uses it gets short shots, lower-third captions and the same music dip in its plan and in the rendered
sound, names the example (and its revision) as the source of each choice, lets a project choice override one, and
never contains the example's own footage or sound.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.slow
SR = 48000
SPEECH = [(0.6, 3.1), (3.5, 6.3), (7.0, 9.6), (10.1, 13.2), (14.0, 17.4), (18.0, 20.0)]
VOCAB = ("we climbed the ridge before sunrise and the valley opened below us with clouds rolling over distant peaks "
         "while our guide pointed at tracks in fresh snow then lunch by the frozen lake").split()
COLORS = ["0x2a4d69", "0x4b86b4", "0xadcbe3", "0x63ace5", "0x854442", "0x3c2f2f", "0xbe9b7b", "0x4a6741",
          "0x6f9283", "0x8d5524", "0xc68642", "0x5d3954", "0x2e4057", "0x66a182"]


def _words(spans, sentence_every: int = 0) -> list[dict]:
    out, n = [], 0
    for a, b in spans:
        t, first = a, len(out)
        while t + 0.3 <= b:
            out.append({"start": round(t, 2), "end": round(t + 0.3, 2), "w": VOCAB[n % len(VOCAB)]})
            n += 1
            t += 0.38
        if sentence_every and len(out) > first:
            out[-1]["w"] += "."
    return out


def _speech_filter(spans, label: str, index: int) -> str:
    on = "+".join(f"between(t,{a},{b})" for a, b in spans)
    return (f"[{index}:a]bandpass=f=1200:width_type=h:w=1800,"
            f"volume='if({on},1,0)*(0.6+0.4*sin(2*PI*4*t))':eval=frame[{label}]")


def _example(path: Path, *, shot: float = 1.5, dur: float = 21.0, duck_db: float = 12.0) -> Path:
    """Short shots of different pictures, lower-third captions (the editor's own), music that dips under speech."""
    from clipfoundry.studio import engine

    w, h = 540, 960
    n = int(dur / shot)
    inputs = []
    for k in range(n):
        c0, c1 = COLORS[k % len(COLORS)], COLORS[(k + 5) % len(COLORS)]
        inputs += ["-f", "lavfi", "-i", f"gradients=s={w}x{h}:r=30:d={shot}:c0={c0}:c1={c1}:seed={k}:speed=0.02"]
    ass = path.with_suffix(".ass")
    ass.write_text(engine.captions_ass(_words(SPEECH), {"style": "clean", "position": "bottom", "size": "medium"},
                                       w, h))
    chain = "".join(f"[{k}:v]noise=alls=6:allf=t,setsar=1[v{k}];" for k in range(n))
    chain += "".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[base];"
    chain += f"[base]ass={ass.name}:fontsdir={engine.config.FONTS_DIR}[cap];"
    on = "+".join(f"between(t,{a},{b})" for a, b in SPEECH)
    inputs += ["-f", "lavfi", "-i", f"anoisesrc=d={dur}:c=white:a=0.6:r=48000",
               "-f", "lavfi", "-i", f"sine=f=55:r=48000:d={dur}", "-f", "lavfi", "-i", f"sine=f=330:r=48000:d={dur}"]
    chain += _speech_filter(SPEECH, "sp", n) + ";"
    chain += (f"[{n + 1}:a][{n + 2}:a]amix=inputs=2:normalize=0,volume=0.15,"
              f"volume='if({on},{10 ** (-duck_db / 20):.4f},1)':eval=frame[mu];[sp][mu]amix=inputs=2:normalize=0[a]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", chain, "-map", "[cap]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", str(dur),
                    str(path)], check=True, cwd=path.parent)
    return path


TALK = [(0.4, 2.0), (2.5, 4.1), (4.6, 6.2), (6.7, 8.3), (8.8, 10.4)]


def _talking(path: Path, dur: float = 11.0) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:d={dur}",
                    "-f", "lavfi", "-i", f"anoisesrc=d={dur}:c=white:a=0.6:r=48000", "-filter_complex",
                    _speech_filter(TALK, "a", 1), "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset",
                    "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", str(dur), str(path)], check=True)
    return path


def _pcm(path: Path) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar",
                                   str(SR), "-"])
    return np.frombuffer(raw, dtype=np.float32)


def _band(x: np.ndarray, t0: float, t1: float, freq: float) -> float:
    seg = x[int(t0 * SR):int(t1 * SR)]
    win = np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg * win)) * 2 / win.sum()
    bins = np.fft.rfftfreq(len(seg), 1 / SR)
    return float(spec[(bins > freq - 15) & (bins < freq + 15)].max())


def _upload(api, path) -> dict:
    data = path.read_bytes()
    up = api.post("/api/uploads", json={"filename": path.name, "size": len(data)}).json()
    while up["received"] < len(data):
        up = api.put(f"/api/uploads/{up['id']}?offset={up['received']}",
                     content=data[up["received"]:up["received"] + 1_000_000]).json()
    r = api.post(f"/api/uploads/{up['id']}/complete")
    assert r.status_code == 200, r.text
    return r.json()


def _until(fetch, done, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        v = fetch()
        if done(v):
            return v
        time.sleep(0.3)
    raise AssertionError(f"timed out: {v}")


def test_an_example_is_measured_and_its_choices_reach_a_new_project_and_its_render(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.pipeline import transcribe

    def fixture_transcript(wav, duration, *a, **k):  # no speech model here: the known words of each file
        words = _words(SPEECH) if abs(duration - 21) < 0.5 else _words(TALK, sentence_every=1) \
            if abs(duration - 11) < 0.5 else []
        return {"language": "en", "duration": duration, "source": "fixture",
                "segments": [{"start": 0, "end": duration, "text": "", "words": words}]}

    monkeypatch.setattr(transcribe, "transcribe", fixture_transcript)
    example = _example(tmp_path / "example.mp4")
    talk = _talking(tmp_path / "talk.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x335577:s=640x360", "-frames:v",
                    "1", str(tmp_path / "view.png")], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100:"
                    "duration=40", "-af", "volume=0.5", str(tmp_path / "music.m4a")], check=True)
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        ex = _upload(api, example)
        r = api.post("/api/studio/references", json={"asset_id": ex["id"], "title": "Ridge vlog",
                                                     "likes": ["overall"], "note": "Quick cuts and clean captions"})
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        ref = _until(lambda: api.get(f"/api/studio/references/{rid}").json(),
                     lambda v: v["status"] in ("ready", "failed"))
        assert ref["status"] == "ready", ref
        an = ref["analysis"]
        assert an["coverage"]["frames_compared"] >= 200 and an["coverage"]["stills"] >= 14
        assert an["coverage"]["ranges"] == [{"start_ms": 0, "end_ms": 21000}]
        noticed = {o["id"]: o for o in an["observations"]}
        assert noticed["shots"]["kind"] == "measured" and "1.5 s" in noticed["shots"]["text"]
        assert noticed["captions"]["kind"] == "estimate" and "lower third" in noticed["captions"]["text"]
        assert noticed["music"]["kind"] == "estimate" and all(e["end_ms"] <= 21000 for o in an["observations"]
                                                              for e in o["evidence"])
        apply = {x["field"]: x["value"] for x in an["applicable"]}
        assert apply["shot_length_s"] == 1.5 and apply["caption_position"] == "bottom"
        assert apply["caption_size"] == "medium" and apply["duck_music"] is True
        assert 9 <= apply["duck_depth_db"] <= 15 and apply["aspect_ratio"] == "9:16"
        assert "No AI model" in an["method"]
        values = {x["field"]: x["value"] for x in an["applicable"] if x["selected"]}
        saved = api.put(f"/api/studio/references/{rid}/style", json={"values": values, "analysis_revision": 1})
        assert saved.status_code == 200, saved.text
        # a new project that uses the example; the shape is the project's own choice (it overrides the example)
        img, t, m = _upload(api, tmp_path / "view.png"), _upload(api, talk), _upload(api, tmp_path / "music.m4a")
        r = api.post("/api/studio/videos", json={
            "name": "Hike", "asset_ids": [img["id"], t["id"]], "style_id": "settings", "reference_id": rid,
            "brief": {"aspect_ratio": "16:9", "music": "supplied", "music_asset_id": m["id"]}})
        assert r.status_code == 200, r.text
        vid = r.json()["id"]
        v = _until(lambda: api.get(f"/api/studio/videos/{vid}").json(),
                   lambda v: any(x["kind"] == "preview" for x in v["artifacts"]) or
                   any(j["status"] == "failed" for j in v["jobs"]))
        assert not [j for j in v["jobs"] if j["status"] == "failed"], v["jobs"]
        plan = v["plan"]
        talk_clips = [c for c in plan["clips"] if c["asset_id"] == t["id"]]
        assert len(talk_clips) == 5 and all((c["out_ms"] - c["in_ms"]) <= 2000 for c in talk_clips)
        assert plan["captions"]["position"] == "bottom" and plan["captions"]["size"] == "medium"
        assert plan["ducking"]["depth_db"] == apply["duck_depth_db"] and plan["output"]["aspect"] == "16:9"
        decided = {d["field"]: d for d in v["guidance"]["decisions"]}
        for field in ("shot_length_s", "caption_position", "duck_depth_db"):
            assert decided[field]["from"]["level"] == "reference" and decided[field]["from"]["id"] == rid
            assert decided[field]["from"]["analysis_revision"] == 1
        assert decided["aspect_ratio"]["from"]["level"] == "project"
        assert decided["aspect_ratio"]["overridden"][0]["value"] == "9:16"
        # the example's own footage and sound are never in the project
        used = {c["asset_id"] for c in plan["clips"]} | {i["asset_id"] for i in plan["audio"]} | set(v["bin"])
        assert ex["id"] not in used
        art = db.select("studio_artifacts", "project_id = ? AND kind = 'preview'", (vid,))[0]
        assert art["info"]["ducking"]["depth_db"] == apply["duck_depth_db"]
        pcm = _pcm(Path(art["path"]))
        free = _band(pcm, 1.0, 3.5, 220)  # the picture without speech: music at its level
        under = _band(pcm, 5.0, 7.5, 220)  # speech: music dips by the example's amount
        dip = 20 * np.log10(free / under)
        assert abs(dip - apply["duck_depth_db"]) <= 3, dip

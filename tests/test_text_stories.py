"""Text Stories (makers/textstory.py) and voice styles (makers/voice_styles.py): a story read by a real voice
(espeak-ng) over a background, with a title card and highlighted captions; backgrounds you upload (trimmed, looped,
moved in the frame) or that ClipForge picks; styles, tone, pronunciations and favourite voices; AI writing and
revising; Stop; the preview and the export; the export opened in the editor."""
from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("espeak-ng") is None,
                                reason="needs FFmpeg and espeak-ng")

TITLE = "My neighbour kept stealing my packages"
SCRIPT = ("Every Friday a package went missing from my porch.\n\n"
          "So I mailed myself a box of glitter. On Saturday, his whole driveway sparkled.")


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry import api, db
    from clipfoundry.jobs import worker
    from clipfoundry.makers import voice

    db.init()
    queued: list[str] = []
    monkeypatch.setattr(worker, "submit_studio", lambda job_id: queued.append(job_id))
    voice.clear_cache()
    with TestClient(api.app, base_url="http://127.0.0.1:8765") as c:
        yield {"client": c, "queued": queued, "tmp": tmp_path}


def _run(env) -> list[dict]:
    from clipfoundry import db
    from clipfoundry.studio import jobs as studio_jobs

    done = []
    while env["queued"]:
        job_id = env["queued"].pop(0)
        if db.fetch("studio_jobs", job_id)["kind"].startswith("text_story"):
            studio_jobs.run(job_id)
            done.append(db.fetch("studio_jobs", job_id))
    return done


def _espeak() -> str:
    from clipfoundry.makers import voice

    return next(v["id"] for v in voice.voices() if v["id"].startswith("espeak:"))


def _probe(path: Path) -> dict:
    got = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(got.stdout)


def _video(path: Path, seconds: float, size: str = "640x360", colour: str = "red") -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={colour}:s={size}:r=30:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=f=330:d={seconds}", "-shortest", "-c:v", "libx264", "-pix_fmt",
                    "yuv420p", "-c:a", "aac", str(path)], check=True)
    return path


def _asset(env, name: str, seconds: float, size: str = "640x360", colour: str = "red") -> dict:
    from clipfoundry.studio import uploads

    src = _video(env["tmp"] / f"src-{name}", seconds, size, colour)
    return uploads.store_file("local", src, name)


# ------------------------------------------------------------------ voice styles
def test_pronunciations_change_what_is_said_and_the_captions_keep_what_is_written():
    from clipfoundry.makers import voice_styles as vs

    rules = vs.clean_rules([{"word": "GIF", "say": "jif"}, {"word": "New York", "say": "Noo Yawk"},
                            {"word": "AITA", "say": "am I the jerk"}, {"word": "", "say": "x"},
                            {"word": "gif", "say": "twice"}])
    assert [r["word"] for r in rules] == ["GIF", "New York", "AITA"]  # empty and repeated rules are dropped
    written = "AITA for saying gif, in New York? Yes."
    said, counts = vs.pronounce(written, rules)
    assert said == "am I the jerk for saying jif, in Noo Yawk? Yes."
    timed = [{"w": w, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, w in enumerate(said.split())]
    back = vs.words_back(timed, written, counts)
    assert [w["w"] for w in back] == ["AITA", "for", "saying", "gif,", "in", "New York?", "Yes."]
    assert back[0]["start"] == 0.0 and back[0]["end"] == timed[3]["end"]  # AITA lasts as long as its four words
    assert back[5]["start"] == timed[8]["start"] and back[5]["end"] == timed[9]["end"]
    assert vs.pronounce("Nothing to change.", []) == ("Nothing to change.", [1, 1, 1])


def test_a_style_sets_speed_and_tone_and_both_stay_in_range():
    from clipfoundry.makers import voice_styles as vs

    v = vs.clean_voice({"style": "dramatic"})
    assert (v["speed"], v["tone"]) == (0.9, -2.0)
    v = vs.clean_voice({"style": "meme", "voice": "espeak:en-us"}, v)
    assert (v["speed"], v["tone"], v["voice"]) == (1.3, 2.0, "espeak:en-us")
    assert vs.clean_voice({"speed": 9, "tone": -30}, v)[("speed")] == 1.4
    assert vs.clean_voice({"tone": -30}, v)["tone"] == -4.0
    for bad in ({"style": "opera"}, {"speed": "fast"}, {"tone": float("nan")}, {"voice": ""}):
        with pytest.raises(vs.VoiceStyleError):
            vs.clean_voice(bad)
    assert {s["id"] for s in vs.styles()} == {"energetic", "casual", "dramatic", "meme"}


def test_tone_moves_the_pitch_and_keeps_the_length(tmp_path):
    from clipfoundry.makers import voice_styles as vs

    sr = 48000
    t = np.arange(sr * 2) / sr
    src = tmp_path / "a.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2").tobytes())
    out = tmp_path / "b.wav"
    vs.shape(src, out, 4.0)
    with wave.open(str(out), "rb") as w:
        assert w.getframerate() == sr
        frames = w.getnframes()
        data = np.frombuffer(w.readframes(frames), "<i2").astype(float)
    assert abs(frames / sr - 2.0) < 0.05  # the same length
    peak = np.argmax(np.abs(np.fft.rfft(data))) * sr / len(data)
    assert abs(peak - 220 * 2 ** (4 / 12)) < 6  # four semitones higher: about 277 Hz


def test_favourite_voices_for_a_style_and_for_a_story(env):
    from clipfoundry.makers import voice_styles as vs

    c = env["client"]
    story = c.post("/api/studio/text-stories", json={}).json()
    r = c.put("/api/studio/voices/favourites", json={"scope": "style:dramatic",
                                                     "voice": {"voice": "espeak:en-gb", "style": "dramatic"}})
    assert r.status_code == 200 and r.json()["favourites"]["style:dramatic"]["voice"] == "espeak:en-gb"
    r = c.put("/api/studio/voices/favourites", json={"scope": f"project:{story['id']}",
                                                     "voice": {"voice": "espeak:en-us", "speed": 1.2}})
    assert r.json()["favourites"][f"project:{story['id']}"]["speed"] == 1.2
    assert vs.favourite_for("local", story["id"], "dramatic")["voice"] == "espeak:en-us"  # the story's wins
    assert vs.favourite_for("local", "", "dramatic")["voice"] == "espeak:en-gb"
    for bad in ({"scope": "everything", "voice": {"voice": "x"}}, {"scope": "style:opera", "voice": {"voice": "x"}}):
        assert c.put("/api/studio/voices/favourites", json=bad).status_code == 422
    assert c.put("/api/studio/voices/favourites", json={"scope": "project:tst-nobody", "voice": {"voice": "x"}}
                 ).status_code == 404
    # a new story starts with the default style's favourite; removing a favourite works
    c.put("/api/studio/voices/favourites", json={"scope": "style:casual", "voice": {"voice": "espeak:en-gb"}})
    assert c.post("/api/studio/text-stories", json={}).json()["voice"]["voice"] == "espeak:en-gb"
    r = c.put("/api/studio/voices/favourites", json={"scope": "style:casual", "voice": None})
    assert "style:casual" not in r.json()["favourites"]


def test_a_voice_preview_is_a_few_seconds_at_the_asked_speed_and_tone(env):
    c = env["client"]
    voice = _espeak()
    r = c.post("/api/studio/voices/preview", json={"voice": voice, "speed": 1.0, "tone": 0})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    slow = c.post("/api/studio/voices/preview", json={"voice": voice, "speed": 0.8, "tone": -2})
    assert slow.status_code == 200 and len(slow.content) > len(r.content)  # slower reads longer
    again = c.post("/api/studio/voices/preview", json={"voice": voice, "speed": 0.8, "tone": -2})
    assert again.content == slow.content  # kept: the same preview
    assert c.post("/api/studio/voices/preview", json={"voice": voice, "speed": "x"}).status_code == 422


# ------------------------------------------------------------------ backgrounds
def test_pieces_loop_or_hold_until_the_story_ends():
    from clipfoundry.makers import textstory

    a = {"asset_id": "a", "in_s": 2.0, "out_s": 6.0, "loop": False}
    b = {"asset_id": "b", "in_s": 0.0, "out_s": 3.0, "loop": True}
    plays = textstory.pieces([a, b], 12.0)
    assert [(p["asset_id"], p["length"]) for p in plays] == [("a", 4.0), ("b", 3.0), ("b", 3.0), ("b", 2.0)]
    plays = textstory.pieces([{**a, "loop": True}, b], 9.0)
    assert [p["asset_id"] for p in plays] == ["a", "a", "a"]  # a looping clip plays to the end
    assert sum(p["length"] for p in textstory.pieces([a], 10.0)) == 4.0  # nothing loops: the last picture holds


def test_clipforge_picks_your_best_background_or_draws_one(env):
    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"title": TITLE, "script": SCRIPT}).json()
    got = c.post(f"/api/studio/text-stories/{story['id']}/backgrounds/auto").json()
    assert len(got["backgrounds"]) == 1 and got["backgrounds"][0]["builtin"] in ("aurora", "sunset", "ocean")
    assert "no videos" in got["backgrounds"][0]["why"]
    _asset(env, "holiday.mp4", 6.0)
    best = _asset(env, "minecraft parkour gameplay.mp4", 8.0, "360x640", "blue")
    _asset(env, "tiny.mp4", 2.0)  # too short to use
    choices = c.get("/api/studio/text-stories/backgrounds", params={"text_story_id": story["id"]}).json()["videos"]
    assert [x["filename"] for x in choices] == ["minecraft parkour gameplay.mp4", "holiday.mp4"]
    assert "gameplay" in choices[0]["why"] or "minecraft" in choices[0]["why"]
    got = c.post(f"/api/studio/text-stories/{story['id']}/backgrounds/auto").json()
    assert got["backgrounds"][0]["asset_id"] == best["id"] and got["backgrounds"][-1]["loop"] is True


def test_backgrounds_must_be_your_own_videos_and_trims_stay_inside_them(env):
    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"script": SCRIPT}).json()
    clip = _asset(env, "clip.mp4", 6.0)
    url = f"/api/studio/text-stories/{story['id']}"
    got = c.patch(url, json={"backgrounds": [{"asset_id": clip["id"], "in_s": 5.8, "out_s": 99, "focus_x": 2}]})
    b = got.json()["backgrounds"][0]
    assert b["in_s"] <= 5.0 and b["out_s"] <= 6.01 and b["out_s"] - b["in_s"] >= 1.0 and b["focus_x"] == 1.0
    assert c.patch(url, json={"backgrounds": [{"asset_id": "nope"}]}).status_code == 404
    assert c.patch(url, json={"backgrounds": [{"builtin": "lava"}]}).status_code == 422
    assert c.patch(url, json={"captions": {"style": "comic"}}).status_code == 422
    assert c.patch(url, json={"script": "word " * 700}).status_code == 422


# ------------------------------------------------------------------ the whole story
def test_a_story_is_voiced_previewed_and_exported_with_its_title_card_and_captions(env):
    from clipfoundry import db
    from clipfoundry.makers import textstory

    c = env["client"]
    voice = _espeak()
    story = c.post("/api/studio/text-stories", json={"title": TITLE, "script": SCRIPT}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    clip = _asset(env, "satisfying slime.mp4", 4.0, "640x360", "green")
    got = c.patch(url, json={"voice": {"voice": voice, "style": "energetic"},
                             "pronunciations": [{"word": "glitter", "say": "glit er"}],
                             "backgrounds": [{"asset_id": clip["id"], "in_s": 1.0, "out_s": 3.0, "loop": True,
                                              "focus_x": 0.0}]}).json()
    assert got["voice"]["speed"] == 1.12 and got["steps"] == {"script": True, "voice": True, "background": True,
                                                              "preview": False, "export": False}
    started = c.post(f"{url}/preview").json()
    assert started["working"] and started["status"] == "voicing"
    assert c.patch(url, json={"title": "Changed while working"}).status_code == 409
    jobs = _run(env)
    assert [j["status"] for j in jobs] == ["done"], [j["error"] for j in jobs]
    done = c.get(url).json()
    assert done["status"] == "ready" and done["made"]["preview"]["current"] and done["narration"]["ready"]
    row = db.fetch("text_stories", story["id"])
    narration = row["narration"]
    words = narration["words"]
    # the captions show the words as written ("glitter", said as two words), the title is read first
    assert [w["w"] for w in words][:len(TITLE.split())] == (TITLE + ".").split()
    assert "glitter." in [w["w"] for w in words] and narration["title_words"] == len(TITLE.split())
    assert all(a["start"] <= b["start"] for a, b in zip(words, words[1:]))
    info = _probe(textstory.file_for(row, "preview"))
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (360, 640)
    assert abs(float(info["format"]["duration"]) - (narration["duration"] + textstory.TAIL_S)) < 0.25
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    ass = textstory.story_ass(row, narration, 1080, 1920)
    assert f",Title,,0,0,0,,{TITLE}" in ass and "Style: Title," in ass and ass.count(",Cap,,") > 5
    # pressing Preview again changes nothing; the file is served to the page
    assert c.post(f"{url}/preview").json()["status"] == "ready" and not env["queued"]
    r = c.get(f"{url}/file/preview")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    # the export: full size, ready to download
    c.post(f"{url}/export")
    assert [j["status"] for j in _run(env)] == ["done"]
    row = db.fetch("text_stories", story["id"])
    v = next(s for s in _probe(textstory.file_for(row, "export"))["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    r = c.get(f"{url}/file/export", params={"download": True})
    assert r.status_code == 200 and "attachment" in r.headers.get("content-disposition", "")
    # a changed script: the videos are out of date, the voice is made again on the next preview
    stale = c.patch(url, json={"script": SCRIPT + " The end."}).json()
    assert not stale["made"]["preview"]["current"] and not stale["narration"]["ready"]
    assert stale["made"]["preview"]["ready"]  # the old one can still be watched


def test_an_uploaded_background_that_is_too_short_loops_and_one_that_does_not_holds_its_last_picture(env):
    from clipfoundry import db
    from clipfoundry.makers import textstory

    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"script": "One. Two. Three. Four. Five. Six. Seven."}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    clip = _asset(env, "short.mp4", 2.0)
    c.patch(url, json={"voice": {"voice": _espeak()}, "backgrounds": [{"asset_id": clip["id"], "loop": False}]})
    c.post(f"{url}/preview")
    assert [j["status"] for j in _run(env)] == ["done"]
    row = db.fetch("text_stories", story["id"])
    total = row["narration"]["duration"] + textstory.TAIL_S
    assert total > 2.5
    assert abs(float(_probe(textstory.file_for(row, "preview"))["format"]["duration"]) - total) < 0.25


def test_stop_ends_the_work_and_says_so(env):
    from clipfoundry import db

    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"script": SCRIPT}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    c.post(f"{url}/backgrounds/auto")
    c.post(f"{url}/preview")
    stopped = c.post(f"{url}/stop").json()
    assert stopped["status"] == "draft" and "Stopped" in stopped["message"] and not stopped["working"]
    assert _run(env) == [] or db.fetch("text_stories", story["id"])["preview"] == {}
    assert c.patch(url, json={"title": "Fine again"}).status_code == 200


def test_clipforge_ai_writes_and_revises_the_story(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.makers import writer

    c = env["client"]
    story = c.post("/api/studio/text-stories", json={}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    assert c.post(f"{url}/write", json={"topic": "a cat"}).status_code == 422  # no AI set up
    monkeypatch.setattr(writer, "_usable", lambda settings: True)
    asks = []

    def fake(settings, prompt, cancel, beat, message):
        asks.append(prompt)
        words = " ".join(["word"] * 180)
        if "Revise" in prompt:
            return json.dumps({"title": "The cat came back", "script": "The ending is scarier now. " + words})
        return json.dumps({"title": "The cat that knew", "script": f"{words}\n\nFollow for part 2!"})

    monkeypatch.setattr(writer, "_ask_story", fake)
    started = c.post(f"{url}/write", json={"topic": "a cat that predicts storms", "tone": "creepy"}).json()
    assert started["status"] == "writing"
    assert [j["status"] for j in _run(env)] == ["done"]
    got = c.get(url).json()
    assert got["title"] == "The cat that knew" and "Follow for part" not in got["script"]
    assert "closing line" in " ".join(got["writer"]["notes"]) and "creepy" in asks[0].lower()
    assert "<<<a cat that predicts storms>>>" in asks[0]  # the topic is data, fenced
    c.post(f"{url}/write", json={"change": "make the ending scarier"})
    _run(env)
    got = c.get(url).json()
    assert got["title"] == "The cat came back" and got["script"].startswith("The ending is scarier now.")
    assert "make the ending scarier" in asks[-1] and "The cat that knew" in asks[-1]
    assert db.fetch("text_stories", story["id"])["writer"]["ask"]["change"] == "make the ending scarier"


def test_the_export_opens_in_the_editor_as_a_new_video(env):
    from clipfoundry import db

    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"title": "Short one", "script": "Just a few words here."}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    c.patch(url, json={"voice": {"voice": _espeak()}})
    c.post(f"{url}/backgrounds/auto")
    assert c.post(f"{url}/open-in-editor").status_code == 422  # export first
    c.post(f"{url}/export")
    _run(env)
    r = c.post(f"{url}/open-in-editor")
    assert r.status_code == 200
    project = db.fetch("studio_projects", r.json()["video_id"])
    assert project and project["name"] == "Short one" and len(project["asset_ids"]) == 1
    # the exported video is never offered back as a background
    assert c.get("/api/studio/text-stories/backgrounds").json()["videos"] == []
    c.delete(url)
    assert c.get(url).status_code == 404 and project["id"]

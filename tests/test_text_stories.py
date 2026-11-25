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


# ------------------------------------------------------------------ batch 4 review fixes (findings 7-19)
LONGER = ("Every Friday a package went missing from my porch, and every Friday my neighbour waved at me a little too "
          "cheerfully. So I mailed myself a box of glitter and waited by the window.")


def _ready_story(env, script: str = SCRIPT, title: str = TITLE, backgrounds: list | None = None) -> tuple[dict, str]:
    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"title": title, "script": script}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    c.patch(url, json={"voice": {"voice": _espeak()}})
    if backgrounds is None:
        c.post(f"{url}/backgrounds/auto")
    else:
        c.patch(url, json={"backgrounds": backgrounds})
    return story, url


def test_a_worker_that_takes_the_job_at_once_still_finds_it_is_the_storys_work(env, monkeypatch):
    """Finding 7: the story names its job before the worker can see it (the worker here runs it at once)."""
    from clipfoundry.jobs import worker
    from clipfoundry.studio import jobs as studio_jobs

    monkeypatch.setattr(worker, "submit_studio", lambda job_id: studio_jobs.run(job_id))
    c = env["client"]
    story, url = _ready_story(env)
    c.post(f"{url}/preview")
    got = c.get(url).json()
    assert got["status"] == "ready" and not got["working"] and got["made"]["preview"]["current"]


def test_stop_settles_a_story_whose_job_already_ended(env):
    """Finding 7: a story left working by a job that ended (here: done without saying so) can be stopped."""
    from clipfoundry import db

    c = env["client"]
    story, url = _ready_story(env)
    c.post(f"{url}/preview")
    job_id = db.fetch("text_stories", story["id"])["job_id"]
    db.update("studio_jobs", job_id, status="done")  # what a skipped job used to leave
    env["queued"].clear()
    got = c.post(f"{url}/stop").json()
    assert not got["working"] and got["status"] in ("draft", "failed")
    assert c.patch(url, json={"title": "Fine again"}).status_code == 200


def test_a_story_too_long_for_one_video_fails_the_writing_and_says_why(env, monkeypatch):
    """Finding 8: an AI story over 650 words is refused in the writer, and the story never stays 'writing'."""
    from clipfoundry.makers import textstory, writer

    c = env["client"]
    story = c.post("/api/studio/text-stories", json={}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    monkeypatch.setattr(writer, "_usable", lambda settings: True)
    monkeypatch.setattr(writer, "_ask_story", lambda *a, **k: json.dumps(
        {"title": "Too long", "script": " ".join(["word"] * (textstory.MAX_WORDS + 50))}))
    c.post(f"{url}/write", json={"topic": "a very long tale", "length": "long"})
    assert [j["status"] for j in _run(env)] == ["failed"]
    got = c.get(url).json()
    assert got["status"] == "failed" and not got["working"] and str(textstory.MAX_WORDS) in got["error"]
    assert got["script"] == ""  # nothing half-written was kept
    assert c.post(f"{url}/write", json={"topic": "a short tale"}).status_code == 200  # can try again


def test_a_stop_pressed_as_the_voice_finishes_is_never_written_back_to_working(env, monkeypatch):
    """Finding 9: Stop lands after the narration's last check; the render step must not set 'rendering' again."""
    from clipfoundry import db
    from clipfoundry.makers import textstory

    c = env["client"]
    story, url = _ready_story(env)
    real = textstory.make_narration

    def narrate_then_stop(s, lease=None):
        got = real(s, lease)
        textstory.stop(db.fetch("text_stories", s["id"]))  # the owner presses Stop right now
        return got

    monkeypatch.setattr(textstory, "make_narration", narrate_then_stop)
    c.post(f"{url}/preview")
    assert [j["status"] for j in _run(env)] == ["canceled"]
    got = c.get(url).json()
    assert got["status"] == "draft" and not got["working"] and "Stopped" in got["message"]
    assert not got["made"]["preview"]["ready"]
    assert not list(textstory.folder(story["id"]).glob("preview*"))  # no video, no captions file was kept


def test_a_pronunciation_of_several_title_words_keeps_the_first_story_word_in_the_captions(env):
    """Finding 10: "New York" said as two words counts as one title word, and no rule spans title and script."""
    from clipfoundry import db
    from clipfoundry.makers import textstory

    c = env["client"]
    story, url = _ready_story(env, script="It was loud and bright.", title="Moving to New York")
    c.patch(url, json={"pronunciations": [{"word": "New York", "say": "Noo Yawk"}]})
    narration = textstory.make_narration(db.fetch("text_stories", story["id"]))
    words = [w["w"] for w in narration["words"]]
    assert narration["title_words"] == 3 and words[:4] == ["Moving", "to", "New York.", "It"]
    ass = textstory.story_ass(db.fetch("text_stories", story["id"]), narration, 1080, 1920)
    assert ass.split("Title,,0,0,0,,", 1)[0].count("It") >= 1  # "It" is a caption, not part of the title card
    # a rule never joins the title's last word with the script's first
    other, url2 = _ready_story(env, script="York pizza is great.", title="I love New")
    c.patch(url2, json={"pronunciations": [{"word": "New York", "say": "Noo Yawk"}]})
    narration = textstory.make_narration(db.fetch("text_stories", other["id"]))
    assert narration["title_words"] == 3 and [w["w"] for w in narration["words"]][3] == "York"


def test_open_in_the_editor_follows_the_current_export_and_a_deleted_editor_video(env):
    """Finding 11: the editor link belongs to the export it was made from, and only while that video exists."""
    from clipfoundry import db

    c = env["client"]
    story, url = _ready_story(env, script="Just a few words here.", title="Short one")
    c.post(f"{url}/export")
    _run(env)
    first = c.post(f"{url}/open-in-editor").json()["video_id"]
    assert c.get(url).json()["project_id"] == first
    c.patch(url, json={"script": "Just a few other words here."})
    c.post(f"{url}/export")
    _run(env)
    assert c.get(url).json()["project_id"] == ""  # a new export: the button makes a new editor video
    second = c.post(f"{url}/open-in-editor").json()["video_id"]
    assert second != first and c.get(url).json()["project_id"] == second
    db.execute("DELETE FROM studio_projects WHERE id = ?", (second,))
    assert c.get(url).json()["project_id"] == ""  # deleted: no link to a missing video


def test_story_videos_sent_to_the_editor_are_never_backgrounds_after_a_new_export_or_deletion(env):
    """Finding 12: the exports' fingerprints outlive the export dict and the story."""
    c = env["client"]
    story, url = _ready_story(env, script=LONGER, title="Glitter")
    c.post(f"{url}/export")
    _run(env)
    c.post(f"{url}/open-in-editor")
    assert c.get("/api/studio/text-stories/backgrounds").json()["videos"] == []
    c.patch(url, json={"script": LONGER + " The end."})
    c.post(f"{url}/export")
    _run(env)
    assert c.get("/api/studio/text-stories/backgrounds").json()["videos"] == []  # still left out after a re-export
    c.delete(url)
    assert c.get("/api/studio/text-stories/backgrounds").json()["videos"] == []  # and after the story is gone


def test_a_linked_video_that_was_moved_or_deleted_is_not_offered_or_picked(env):
    """Finding 13: linked files are checked on disk like stored ones."""
    import time as _time

    from clipfoundry import db
    from clipfoundry.studio import uploads

    c = env["client"]
    gone = env["tmp"] / "gone gameplay.mp4"
    db.insert("assets", {"id": "as-linked-gone", "workspace_id": "local", "kind": "video",
                         "filename": "gone gameplay.mp4", "sha256": uploads.LINK_PREFIX + "abc", "size": 1000,
                         "path": str(gone), "probe": {"duration": 60.0, "width": 1080, "height": 1920},
                         "created_at": _time.time(), "updated_at": _time.time()})
    assert c.get("/api/studio/text-stories/backgrounds").json()["videos"] == []
    story = c.post("/api/studio/text-stories", json={"script": SCRIPT}).json()
    got = c.post(f"/api/studio/text-stories/{story['id']}/backgrounds/auto").json()
    assert got["backgrounds"][0].get("builtin")  # ClipForge draws one instead of picking the missing file


def test_the_story_voice_is_kept_when_a_style_is_picked_and_a_style_brings_its_favourite(env):
    """Finding 14: "Keep this voice for this story" changes what picking a style does."""
    c = env["client"]
    story = c.post("/api/studio/text-stories", json={}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    c.put("/api/studio/voices/favourites", json={"scope": "style:dramatic",
                                                 "voice": {"voice": "espeak:en-gb", "speed": 0.8, "tone": -3}})
    got = c.patch(url, json={"voice": {"style": "dramatic"}}).json()["voice"]
    assert (got["voice"], got["speed"], got["tone"]) == ("espeak:en-gb", 0.8, -3.0)  # the style's favourite
    c.patch(url, json={"voice": {"style": "casual", "voice": "espeak:en-us"}})
    c.put("/api/studio/voices/favourites", json={"scope": f"project:{story['id']}",
                                                 "voice": {"voice": "espeak:en-us"}})
    got = c.patch(url, json={"voice": {"style": "dramatic"}}).json()["voice"]
    assert (got["voice"], got["speed"], got["tone"]) == ("espeak:en-us", 0.9, -2.0)  # kept voice, style's pace
    got = c.patch(url, json={"voice": {"style": "meme"}}).json()["voice"]
    assert (got["voice"], got["speed"]) == ("espeak:en-us", 1.3)


def test_deleting_a_story_forgets_what_clipforge_ai_remembered_about_it(env, monkeypatch):
    """Finding 15: the Brain note kept for the story goes with it."""
    from clipfoundry import db
    from clipfoundry.makers import writer

    c = env["client"]
    story = c.post("/api/studio/text-stories", json={}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    monkeypatch.setattr(writer, "_usable", lambda settings: True)
    monkeypatch.setattr(writer, "_ask_story", lambda *a, **k: json.dumps(
        {"title": "The secret title", "script": " ".join(["word"] * 200)}))
    c.post(f"{url}/write", json={"topic": "a secret"})
    _run(env)
    scope = f"project:{story['id']}"
    assert db.scalar("SELECT COUNT(*) FROM brain_memories WHERE scope = ?", (scope,)) >= 1
    c.delete(url)
    assert db.scalar("SELECT COUNT(*) FROM brain_memories WHERE scope = ?", (scope,)) == 0
    assert not db.scalar("SELECT COUNT(*) FROM brain_memories WHERE text LIKE '%secret title%'")


def test_hear_samples_of_the_storys_words_and_the_engines_copy_are_not_left_behind(env, monkeypatch):
    """Finding 16: a sample of the page's own words is not kept; the voice engine's copy goes with the story."""
    from clipfoundry import config, db
    from clipfoundry.makers import textstory, voice

    c = env["client"]
    previews = config.data_dir() / "voices" / "previews"
    r = c.post("/api/studio/voices/preview", json={"voice": _espeak(), "text": "My neighbour stole my packages."})
    assert r.status_code == 200 and len(r.content) > 1000
    assert not list(previews.glob("*.wav"))  # sent once, then deleted
    c.post("/api/studio/voices/preview", json={"voice": _espeak()})
    assert len(list(previews.glob("*.wav"))) == 1  # the usual sample sentence is kept
    made = config.data_dir() / "engines" / "made"
    made.mkdir(parents=True, exist_ok=True)
    real = voice.speak

    def speak_with_an_original(text, out, **kw):
        got = real(text, out, **kw)
        original = made / "engine-take.wav"
        original.write_bytes(Path(out).read_bytes())
        original.with_suffix(".json").write_text(json.dumps({"text": text}))
        return {**got, "original": str(original)}

    monkeypatch.setattr(voice, "speak", speak_with_an_original)
    story, url = _ready_story(env)
    textstory.make_narration(db.fetch("text_stories", story["id"]))
    assert not list(made.iterdir())
    kept = textstory.folder(story["id"])
    assert (kept / "voice-original.wav").is_file() and (kept / "voice-original.json").is_file()
    c.delete(url)
    assert not kept.exists()


def test_a_failed_or_stopped_render_leaves_no_partial_video_or_captions_file(env, monkeypatch):
    """Finding 17: the partial export and its .ass file go when FFmpeg fails (or Stop ends it)."""
    from clipfoundry import db
    from clipfoundry.makers import textstory
    from clipfoundry.pipeline import ffmpeg_utils

    c = env["client"]
    story, url = _ready_story(env)
    c.post(f"{url}/preview")
    assert [j["status"] for j in _run(env)] == ["done"]

    def broken(args, **kw):
        Path(args[-1]).write_bytes(b"half a video")
        raise ffmpeg_utils.FFmpegError("the encoder stopped")

    monkeypatch.setattr(ffmpeg_utils, "run", broken)
    c.post(f"{url}/export")
    assert [j["status"] for j in _run(env)] == ["failed"]
    folder = textstory.folder(story["id"])
    assert not list(folder.glob("export*")) and not list(folder.glob("*.ass"))
    assert db.fetch("text_stories", story["id"])["status"] == "failed"
    assert list(folder.glob("preview-*.mp4"))  # the earlier preview stays


def test_pronunciations_of_words_with_their_own_punctuation_are_used():
    """Finding 18: "Dr." and "C++" match as written; "C" alone is not "C++"."""
    from clipfoundry.makers import voice_styles as vs

    rules = vs.clean_rules([{"word": "Dr.", "say": "Doctor"}, {"word": "C++", "say": "see plus plus"}])
    said, counts = vs.pronounce("Ask (Dr. Lee) about C++, not C.", rules)
    assert said == "Ask (Doctor Lee) about see plus plus, not C."
    assert counts == [1, 1, 1, 1, 3, 1, 1]
    assert vs.pronounce("Dr Lee", rules)[0] == "Dr Lee"  # without the rule's own full stop it is another word


def test_a_short_looping_background_loops_to_the_end_of_a_long_story(env):
    """Finding 19: a 1 s loop covers a story of any length (it used to freeze after 80 plays)."""
    from clipfoundry.makers import textstory

    plays = textstory.pieces([{"asset_id": "a", "in_s": 0.0, "out_s": 1.0, "loop": True}], 250.0)
    assert abs(sum(p["length"] for p in plays) - 250.0) < 0.01
    runs = textstory._runs(plays)  # noqa: SLF001
    assert len(runs) == 1 and runs[0]["times"] == 250 and runs[0]["play"] == 1.0


def test_a_trimmed_looping_clip_repeats_exactly_its_part(env):
    """Finding 19: the looped part is the trimmed part (green then blue), made once and looped by FFmpeg."""
    from clipfoundry import db
    from clipfoundry.makers import textstory
    from clipfoundry.studio import uploads

    parts = []
    for colour in ("red", "green", "blue"):
        parts.append(_video(env["tmp"] / f"{colour}.mp4", 0.5, "640x360", colour))
    joined = env["tmp"] / "rgb.mp4"
    listing = env["tmp"] / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
                    str(joined)], check=True)
    clip = uploads.store_file("local", joined, "rgb.mp4")
    story, url = _ready_story(env, script="One two three four five six seven eight nine ten.", title="",
                              backgrounds=[{"asset_id": clip["id"], "in_s": 0.5, "out_s": 1.5, "loop": True}])
    env["client"].post(f"{url}/preview")
    assert [j["status"] for j in _run(env)] == ["done"]
    row = db.fetch("text_stories", story["id"])
    path = textstory.file_for(row, "preview")
    total = float(_probe(path)["format"]["duration"])
    assert total > 2.5

    def corner(t: float) -> tuple[int, int, int]:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-vf",
                              "crop=8:8:0:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True,
                             check=True).stdout
        return raw[0], raw[1], raw[2]

    def name(rgb) -> str:
        r, g, b = rgb
        return "green" if g > 100 and g > r + 50 and g > b + 50 else "blue" if b > 100 and b > r + 50 else "other"

    assert [name(corner(t)) for t in (0.25, 0.75, 1.25, 1.75, 2.25)] == ["green", "blue", "green", "blue", "green"]
    assert not list(textstory.folder(story["id"]).glob("preview-loop*"))  # the looped part is not kept


@pytest.mark.parametrize("how", ["delete", "stop"])
def test_a_story_deleted_or_stopped_while_clipforge_ai_writes_gets_no_brain_note(env, monkeypatch, how):
    """Second review of finding 15: the answer that arrives after Delete (or Stop) leaves no note about the story."""
    from clipfoundry import db
    from clipfoundry.makers import writer

    c = env["client"]
    story = c.post("/api/studio/text-stories", json={}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    monkeypatch.setattr(writer, "_usable", lambda settings: True)

    def answer(*a, **k):  # the owner presses Delete or Stop while the model is still answering
        assert c.request("DELETE", url).status_code == 200 if how == "delete" else \
            c.post(f"{url}/stop").status_code == 200
        return json.dumps({"title": "The secret title", "script": " ".join(["word"] * 200)})

    monkeypatch.setattr(writer, "_ask_story", answer)
    c.post(f"{url}/write", json={"topic": "a secret"})
    _run(env)
    scope = f"project:{story['id']}"
    assert db.scalar("SELECT COUNT(*) FROM brain_memories WHERE scope = ?", (scope,)) == 0
    assert not db.scalar("SELECT COUNT(*) FROM brain_memories WHERE text LIKE '%secret title%'")
    if how == "stop":
        got = c.get(url).json()
        assert got["status"] == "draft" and got["script"] == "" and "Nothing new was kept" in got["message"]


def test_a_page_that_looks_in_the_middle_of_a_stop_never_turns_it_into_a_failure(env, monkeypatch):
    """Second review of finding 7: a look at the story between Stop marking its job and settling the story settles
    it as stopped, and a story that has just finished is never settled again."""
    from clipfoundry import db
    from clipfoundry.makers import textstory
    from clipfoundry.studio import jobs as studio_jobs

    c = env["client"]
    story, url = _ready_story(env)
    c.post(f"{url}/preview")
    job_id = db.fetch("text_stories", story["id"])["job_id"]
    looked = {}
    real = textstory._settle

    def stop_hook_runs_late(story_id, how, error="", *, job_id=None):
        if not looked:  # the Stop's own settle: the page polls just before it
            looked["polling"] = True
            looked.update(c.get(url).json())
        real(story_id, how, error, **({"job_id": job_id} if job_id else {}))

    monkeypatch.setattr(textstory, "_settle", stop_hook_runs_late)
    assert studio_jobs.cancel(job_id)
    env["queued"].clear()
    assert looked["status"] == "draft" and "Nothing new was kept" in looked["message"] and not looked["error"]
    got = c.get(url).json()
    assert got["status"] == "draft" and not got["error"]
    # a result written first stays: settling only changes a story that is still working on that job
    db.update("text_stories", story["id"], status="ready", message="The preview is ready.")
    real(story["id"], "failed", textstory.STUCK)
    assert db.fetch("text_stories", story["id"])["status"] == "ready"


def test_an_older_stop_never_stops_a_newer_job(env):
    """Third look at finding 7: a Stop sent from a page that still showed the finished job leaves the new one alone."""
    from clipfoundry import db
    from clipfoundry.makers import textstory

    c = env["client"]
    story, url = _ready_story(env)
    c.post(f"{url}/preview")
    seen = db.fetch("text_stories", story["id"])  # what the other tab still shows: working on the first job
    db.update("studio_jobs", seen["job_id"], status="done")
    db.update("text_stories", story["id"], status="ready")
    env["queued"].clear()
    c.post(f"{url}/export")  # a second press starts a new job
    newer = db.fetch("text_stories", story["id"])
    assert newer["job_id"] != seen["job_id"] and newer["status"] in textstory.WORKING
    textstory.stop(seen)
    now = db.fetch("text_stories", story["id"])
    assert now["status"] == newer["status"] and now["job_id"] == newer["job_id"]

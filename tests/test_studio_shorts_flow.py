"""Make → Animated short, end to end without real voices or camera moves (docs/clipforge/ANIMATED_SHORTS.md):
a pasted script becomes scenes, the build job makes each scene's voice, picture and moving clip, and the plan is one
clip per scene with centred highlighted captions, ducked music and a whoosh on every other cut. Changing one scene
makes only that scene again; the owner's edits in the editor (order, trims, removed clips, word fixes, levels) stay;
a failing scene never stops the others; a scene changed while it is being made waits for the next build; Stop says
how to go on; ClipForge AI writes a script when asked and the short can stop for the owner to check it.

The voice and the motion are stand-ins (a tone and a plain clip of the right length, made with FFmpeg) so these
tests stay quick; tests/test_studio_shorts_render.py renders a real short with espeak-ng (slow suite).
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
import wave
from pathlib import Path

import pytest

SCRIPT = ("Did you know octopuses have three hearts? Two of them pump blood to the gills.\n\n"
          "[Visual: an octopus waving with all eight arms]\nThe third one keeps the rest of the body going.\n\n"
          "And their blood is blue, because it carries copper instead of iron.")


def _tone(path: Path, seconds: float) -> None:
    import numpy as np

    sr = 48000
    t = np.arange(int(sr * seconds)) / sr
    data = (0.2 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


def _clip(audio: Path, out: Path, seconds: float) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=navy:s=108x192:r=30:d={seconds}",
                    "-i", str(audio), "-af", "apad", "-t", f"{seconds:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", "48000", str(out)], check=True)


class Calls:
    def __init__(self):
        self.speak: list[str] = []
        self.clips: list[str] = []
        self.fail: set[str] = set()     # words the stand-in voice refuses to say
        self.during_clip = None         # called while a clip is being made (the owner editing meanwhile)
        self.rule = ""                  # what the stand-in voice's licence asks of what it makes


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.jobs import worker

    db.init()
    queued: list[str] = []
    monkeypatch.setattr(worker, "submit_studio", lambda job_id: queued.append(job_id))
    calls = Calls()

    voice = types.ModuleType("clipfoundry.makers.voice")

    class VoiceError(RuntimeError):
        pass

    def speak(text, out, *, voice="auto", speed=1.0, lang="en", cancel=None):
        calls.speak.append(text)
        if any(bad in text for bad in calls.fail):
            raise VoiceError("This voice could not say that scene.")
        seconds = round(0.3 * len(text.split()) / speed, 3)
        _tone(Path(out), seconds)
        return {"path": Path(out), "duration_s": seconds, "words": None, "engine": "espeak", "voice": "Test voice",
                "fallback": "", "rule": calls.rule}

    def time_words(wav, text, *, engine_words=None, settings=None, listen=True):
        words, t = [], 0.0
        for w in text.split():
            words.append({"w": w, "start": round(t, 3), "end": round(t + 0.25, 3)})
            t += 0.3
        return words, "estimated"

    voice.VoiceError = VoiceError
    voice.speak = speak
    voice.time_words = time_words
    voice.default_voice = lambda: "espeak:en-us"
    voice.voices = lambda: [{"id": "auto", "name": "Best voice", "lang": "en", "gender": "", "about": "",
                             "engine": ""}]
    voice.release = lambda: None

    motion = types.ModuleType("clipfoundry.makers.motion")

    class MotionError(RuntimeError):
        pass

    def still_clip(picture, audio, out, *, duration_s, move="zoom_in", fps=30, size=(1080, 1920), strength=0.08,
                   cancel=None, progress=None):
        calls.clips.append(str(picture))
        if calls.during_clip:
            hook, calls.during_clip = calls.during_clip, None
            hook()
        frames = round(duration_s * fps)
        _clip(Path(audio), Path(out), frames / fps)
        return {"path": Path(out), "duration_s": frames / fps, "frames": frames}

    motion.MotionError = MotionError
    motion.MOVES = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "still")
    motion.pick_move = lambda i: ("zoom_in", "pan_right", "zoom_out", "pan_left")[i % 4]
    motion.still_clip = still_clip
    motion.video_clip = lambda *a, **k: (_ for _ in ()).throw(MotionError("no video in these tests"))

    import clipfoundry.makers as makers

    for name, mod in (("voice", voice), ("motion", motion)):
        monkeypatch.setitem(sys.modules, f"clipfoundry.makers.{name}", mod)
        monkeypatch.setattr(makers, name, mod, raising=False)
    from clipfoundry.makers import shorts

    monkeypatch.setattr(shorts, "_status_cache", {})
    return {"queued": queued, "calls": calls, "tmp": tmp_path}


def _run(env, kinds=("short_build",)) -> list[dict]:
    """Run the queued jobs of these kinds, in order, as the worker would (previews are left out)."""
    from clipfoundry import db
    from clipfoundry.studio import jobs as studio_jobs

    done = []
    while env["queued"]:
        job_id = env["queued"].pop(0)
        job = db.fetch("studio_jobs", job_id)
        if job["kind"] in kinds:
            studio_jobs.run(job_id)
            done.append(db.fetch("studio_jobs", job_id))
    return done


def _make(env, script=SCRIPT, **options):
    from clipfoundry.makers import shorts

    project = shorts.create("local", "local", name="", options={"mode": "paste", "script": script, **options})
    jobs = _run(env)
    assert jobs and all(j["status"] == "done" for j in jobs), [j["error"] for j in jobs]
    return _fresh(project["id"])


def _fresh(project_id: str) -> dict:
    from clipfoundry import db

    return db.fetch("studio_projects", project_id)


def _plan(project_id: str) -> dict:
    from clipfoundry.studio import video_flow

    return video_flow.plan_at(project_id, _fresh(project_id)["plan_revision"])


def _scenes(project_id: str, plan=None) -> list[dict]:
    from clipfoundry.makers import shorts

    return shorts.ordered(shorts.scene_rows(project_id), plan)


def _edit(project_id: str, change: dict) -> dict:
    from clipfoundry.studio import video_flow

    return video_flow.edit(project_id, _fresh(project_id)["plan_revision"], change)


def test_a_pasted_script_becomes_one_clip_per_scene(env):
    from clipfoundry.makers import shorts
    from clipfoundry.studio import engine, uploads, video_flow

    project = _make(env)
    assert project["workflow"] == "animated_short" and project["status"] == "ready"
    plan = _plan(project["id"])
    scenes = _scenes(project["id"], plan)
    assert len(scenes) >= 3 and all(s["status"] == "ready" for s in scenes)
    assert [c["id"] for c in plan["clips"]] == [s["id"] for s in scenes]  # clip id = scene id, in script order
    assert plan["maker"] == "animated_short" and plan["output"] == {"aspect": "9:16", "fps": 30}
    assert plan["layout"] == "fill" and plan["transition"]["type"] == "cut" and plan["clean_sound"] == "off"
    assert plan["captions"]["highlight"] is True and plan["captions"]["position"] == "middle"
    music = [a for a in plan["audio"] if a["role"] == "music"]
    assert len(music) == 1 and music[0]["gain_db"] == shorts.MUSIC_DB and music[0]["duck"] and music[0]["auto"]
    whooshes = [a for a in plan["audio"] if a["role"] == "effect"]
    assert [w["anchor"]["clip_id"] for w in whooshes] == [c["id"] for c in plan["clips"]][1::2]
    assert engine.validate(plan, video_flow._assets(project, plan)) == []
    # the direction line is the next scene's picture; the others follow their own words
    pictured = next(s for s in scenes if s["picture_from"] == "script")
    assert "octopus waving" in pictured["picture_prompt"]
    assert all(s["picture_prompt"] for s in scenes)
    # each clip's transcript is its scene's own words, so captions show the script exactly
    for s in scenes:
        clip = uploads.asset(s["clip_asset_id"], "local")
        words = video_flow.transcript_words(clip, {}, cached_only=True)
        assert [w["w"] for w in words] == s["narration"].split()
    # every clip but the last cuts a moment after its words; the last one plays out
    for c, s in zip(plan["clips"], scenes):
        voiced = s["info"]["voice"]["duration_ms"]
        if c is plan["clips"][-1]:
            assert c["out_ms"] == s["duration_ms"]
        else:
            assert c["out_ms"] == min(s["duration_ms"], voiced + shorts.TAIL_MS)
    view = video_flow.view(project)
    assert view["workflow"] == "animated_short" and view["short"]["stage"] == "ready"
    assert all(x["in_plan"] and x["included"] and x["picture"]["source"] == "card" for x in view["short"]["scenes"])
    assert any("designed cards" in n for n in view["short"]["notes"])
    assert view["short"]["voice_rule"] == "" and not any("About the voice" in n for n in view["short"]["notes"])


def test_a_voice_whose_licence_asks_for_a_label_says_so_with_the_short(env):
    from clipfoundry.makers import shorts

    env["calls"].rule = "Label what this voice makes as machine-generated where you post it."
    project = _make(env)
    view = shorts.view(project)
    assert view["voice_rule"] == env["calls"].rule
    assert f"About the voice: {env['calls'].rule}" in view["notes"]
    # the captions can follow the look (the page's first choice) or be chosen
    assert shorts.options()["captions"][0] == {"id": "", "label": "Fits the look"}
    assert shorts.clean_options({"captions": ""})["captions"] == ""


def test_changing_one_scene_makes_only_that_scene_again(env):
    from clipfoundry.makers import shorts

    project = _make(env)
    before = _plan(project["id"])
    scenes = _scenes(project["id"], before)
    spoken, moved = len(env["calls"].speak), len(env["calls"].clips)
    shorts.update_scene(_fresh(project["id"]), scenes[1]["id"], {"narration": "Two of them pump blood to the gills fast."})
    # until the build starts, the short says it is waiting to make the change, not that it is ready
    waiting = shorts.view(_fresh(project["id"]))
    assert waiting["stage"] == "making" and waiting["message"] == "Waiting to make the changes"
    assert [x["status"] for x in waiting["scenes"]].count("waiting") == 1
    _run(env)
    assert _fresh(project["id"])["short"]["stage"] == "ready"
    after = _plan(project["id"])
    assert len(env["calls"].speak) == spoken + 1 and len(env["calls"].clips) == moved + 1
    assert [c["asset_id"] for c in after["clips"]][0] == before["clips"][0]["asset_id"]
    assert after["clips"][1]["asset_id"] != before["clips"][1]["asset_id"]
    assert _fresh(project["id"])["plan_revision"] == 2
    # a build with nothing to do saves no new version
    shorts.make(_fresh(project["id"]))
    _run(env)
    assert _fresh(project["id"])["plan_revision"] == 2 and len(env["calls"].speak) == spoken + 1


def test_the_owners_editor_changes_stay_when_scenes_are_made_again(env):
    from clipfoundry.makers import shorts
    from clipfoundry.studio import engine, video_flow

    project = _make(env)
    plan = _plan(project["id"])
    first, second, third = plan["clips"][:3]
    music = next(a for a in plan["audio"] if a["role"] == "music")
    _edit(project["id"], {"op": "trim", "clip_id": first["id"], "in_ms": 100, "out_ms": first["out_ms"] - 50})
    _edit(project["id"], {"op": "remove", "clip_id": second["id"]})
    _edit(project["id"], {"op": "move", "clip_id": third["id"], "to": 0})
    _edit(project["id"], {"op": "audio_set", "audio_id": music["id"], "field": "gain_db", "value": -26})
    _edit(project["id"], {"op": "set", "field": "caption_position", "value": "top"})
    word = video_flow.transcript_words(db_asset(first["asset_id"]), {}, cached_only=True)[0]
    _edit(project["id"], {"op": "fix_word", "asset_id": first["asset_id"], "start_ms": int(round(word["start"] * 1000)),
                          "text": "Wow"})
    shorts.update_scene(_fresh(project["id"]), third["id"], {"narration": "The third one keeps everything else going."})
    _run(env)
    after = _plan(project["id"])
    by_id = {c["id"]: c for c in after["clips"]}
    assert after["clips"][0]["id"] == third["id"]                       # the order stays
    assert by_id[first["id"]]["in_ms"] == 100                           # the trim stays
    assert by_id[second["id"]]["include"] is False                      # the removed clip stays removed
    assert by_id[third["id"]]["asset_id"] != third["asset_id"]          # the changed scene is new
    assert next(a for a in after["audio"] if a["role"] == "music")["gain_db"] == -26
    assert after["captions"]["position"] == "top"
    assert after["word_fixes"].get(first["asset_id"])                    # unchanged scene: its word fix stays
    assert third["asset_id"] not in after["word_fixes"]
    assert engine.validate(after, video_flow._assets(_fresh(project["id"]), after)) == []
    whooshes = [a["anchor"]["clip_id"] for a in after["audio"] if a["role"] == "effect"]
    shown = [c["id"] for c in after["clips"] if c.get("include", True)]
    assert whooshes == shown[1::2]


def db_asset(asset_id: str) -> dict:
    from clipfoundry import db

    return db.fetch("assets", asset_id)


def test_scenes_added_and_deleted_take_their_place(env):
    from clipfoundry.makers import shorts
    from clipfoundry.studio import engine, video_flow

    project = _make(env)
    scenes = _scenes(project["id"], _plan(project["id"]))
    sid = shorts.add_scene(_fresh(project["id"]), scenes[0]["id"], "Octopuses can also taste with their arms.")
    _run(env)
    plan = _plan(project["id"])
    assert [c["id"] for c in plan["clips"]][:2] == [scenes[0]["id"], sid]
    shorts.add_scene(_fresh(project["id"]), None, "Here is a strange fact.")
    _run(env)
    plan = _plan(project["id"])
    assert plan["clips"][0]["scene_id"] not in {s["id"] for s in scenes} | {sid}  # the new first scene
    shorts.delete_scene(_fresh(project["id"]), scenes[1]["id"])
    _run(env)
    plan = _plan(project["id"])
    assert scenes[1]["id"] not in {c["id"] for c in plan["clips"]}
    assert engine.validate(plan, video_flow._assets(_fresh(project["id"]), plan)) == []
    with pytest.raises(shorts.ShortError):
        shorts.update_scene(_fresh(project["id"]), scenes[0]["id"], {"narration": "   "})


def test_options_set_music_and_captions_again_over_the_editor(env):
    from clipfoundry.makers import shorts
    from clipfoundry.studio import library

    project = _make(env)
    _edit(project["id"], {"op": "set", "field": "caption_position", "value": "top"})
    clips_before = [c["asset_id"] for c in _plan(project["id"])["clips"]]
    shorts.set_options(_fresh(project["id"]), {"music": "calm", "captions": "clean"})
    _run(env)
    plan = _plan(project["id"])
    music = next(a for a in plan["audio"] if a["role"] == "music")
    assert library.MUSIC[library.music_key("calm", project["id"])]["title"] in music["label"]
    assert plan["captions"]["style"] == "clean" and plan["captions"]["position"] == "top"
    assert [c["asset_id"] for c in plan["clips"]] == clips_before  # nothing else was made again
    shorts.set_options(_fresh(project["id"]), {"captions": "off", "music": "none"})
    _run(env)
    plan = _plan(project["id"])
    assert plan["captions"]["enabled"] is False and not [a for a in plan["audio"] if a["role"] == "music"]
    with pytest.raises(shorts.ShortError):
        shorts.set_options(_fresh(project["id"]), {"music": "loud"})


def test_a_failing_scene_never_stops_the_others(env):
    from clipfoundry.studio import video_flow

    env["calls"].fail.add("copper")
    project = _make(env)
    scenes = _scenes(project["id"], _plan(project["id"]))
    failed = [s for s in scenes if s["status"] == "failed"]
    assert len(failed) == 1 and "could not say" in failed[0]["error"]
    plan = _plan(project["id"])
    assert failed[0]["id"] not in {c["id"] for c in plan["clips"]} and len(plan["clips"]) == len(scenes) - 1
    view = video_flow.view(_fresh(project["id"]))["short"]
    assert any("not in the video yet" in n for n in view["notes"])
    assert "could not be made" in _fresh(project["id"])["message"]
    # Try again after the voice works
    from clipfoundry.makers import shorts

    env["calls"].fail.clear()
    shorts.update_scene(_fresh(project["id"]), failed[0]["id"], {"again": True})
    _run(env)
    assert all(s["status"] == "ready" for s in _scenes(project["id"]))
    assert failed[0]["id"] in {c["id"] for c in _plan(project["id"])["clips"]}


def test_a_scene_changed_while_it_is_made_waits_for_the_next_build(env):
    from clipfoundry.makers import shorts

    project = shorts.create("local", "local", name="", options={"mode": "paste", "script": SCRIPT})
    first = _scenes(project["id"])[0]
    env["calls"].during_clip = lambda: shorts.update_scene(_fresh(project["id"]), first["id"],
                                                           {"narration": "Octopuses have three hearts, really."})
    _run(env)  # both builds: the one that was cut short, then the one the change asked for
    scene = next(s for s in _scenes(project["id"]) if s["id"] == first["id"])
    assert scene["status"] == "ready"
    plan = _plan(project["id"])
    clip = next(c for c in plan["clips"] if c["id"] == first["id"])
    from clipfoundry.studio import uploads, video_flow

    words = video_flow.transcript_words(uploads.asset(clip["asset_id"], "local"), {}, cached_only=True)
    assert [w["w"] for w in words] == "Octopuses have three hearts, really.".split()


def test_stop_says_how_to_go_on(env):
    from clipfoundry import db
    from clipfoundry.makers import shorts
    from clipfoundry.studio import jobs as studio_jobs

    project = shorts.create("local", "local", name="Hearts", options={"mode": "paste", "script": SCRIPT})
    job = db.select("studio_jobs", "target_id = ?", (project["id"],))[0]
    env["calls"].during_clip = lambda: studio_jobs.cancel(job["id"])
    _run(env)
    short = _fresh(project["id"])
    assert short["short"]["stage"] == "stopped" and "Make the short" in short["message"]
    assert short["status"] in ("draft", "ready")
    assert not [s for s in _scenes(project["id"]) if s["status"] in shorts.WORKING]
    shorts.make(_fresh(project["id"]))
    _run(env)
    assert _fresh(project["id"])["status"] == "ready" and all(s["status"] == "ready" for s in _scenes(project["id"]))


def test_clipforge_ai_writes_the_script_and_the_owner_can_check_it_first(env, monkeypatch):
    from clipfoundry.makers import shorts, writer

    with pytest.raises(shorts.ShortError, match="ClipForge AI"):
        monkeypatch.setattr(writer, "ready", lambda settings: {"configured": False, "label": "", "local": False})
        shorts.create("local", "local", name="", options={"mode": "write", "topic": "why the sea is salty"})
    monkeypatch.setattr(writer, "ready", lambda settings: {"configured": True, "label": "Built-in AI", "local": True})
    asked = {}

    def write(topic, **kw):
        asked.update(topic=topic, **kw)
        return {"title": "Why the sea is salty", "character": "a friendly cartoon water drop",
                "scenes": [{"narration": "Why is the sea salty, when rain is not?", "picture": "a drop of rain"},
                           {"narration": "Rivers carry tiny bits of salt from the rocks.", "picture": "a river"},
                           {"narration": "The sun takes the water, and the salt stays behind.", "picture": "the sun"}],
                "notes": [], "model": "Built-in AI", "local": True, "memories": [], "knowhow": ["hooks"]}

    monkeypatch.setattr(writer, "write", write)
    project = shorts.create("local", "local", name="", options={"mode": "write", "topic": "why the sea is salty",
                                                                "tone": "curious", "review": True})
    _run(env)
    short = _fresh(project["id"])
    assert asked["topic"] == "why the sea is salty" and short["name"] == "Why the sea is salty"
    assert short["status"] == "needs_input" and short["short"]["stage"] == "review"
    assert short["plan_revision"] == 0 and not env["calls"].speak  # nothing is made before the owner checks it
    scenes = _scenes(project["id"])
    assert [s["picture_from"] for s in scenes] == ["ai"] * 3
    shorts.update_scene(short, scenes[0]["id"], {"narration": "Why is the sea salty when rain is not?"})
    assert _fresh(project["id"])["short"]["stage"] == "review"  # a change while they check it is no build to wait for
    _run(env)
    assert _fresh(project["id"])["short"]["stage"] == "review" and not env["calls"].speak  # still waiting for them
    shorts.make(_fresh(project["id"]))
    _run(env)
    short = _fresh(project["id"])
    assert short["status"] == "ready" and short["plan_revision"] >= 1
    assert short["short"]["character"] == "a friendly cartoon water drop"
    assert short["short"]["writer"]["model"] == "Built-in AI"


def test_bad_scripts_and_choices_are_refused_in_plain_words(env):
    from clipfoundry.makers import shorts

    for options, words in (({"mode": "paste", "script": "   "}, ""), ({"mode": "paste", "script": SCRIPT, "look": "x"},
                                                                       "look"),
                           ({"mode": "paste", "script": SCRIPT, "speed": 3}, "speed"),
                           ({"mode": "nope"}, "Paste"), ({"mode": "write", "topic": ""}, "about")):
        with pytest.raises(shorts.ShortError) as err:
            shorts.create("local", "local", name="", options=options)
        assert words in str(err.value)


def test_the_api_makes_and_changes_a_short(env):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        h = {"X-ClipFoundry": "1"}
        opts = api.get("/api/studio/shorts/options", headers=h).json()
        assert {x["id"] for x in opts["looks"]} and opts["voices"][0]["id"] == "auto"
        assert opts["links"] == {"makers": "#/settings/makers", "ai": "#/settings/ai"}
        r = api.post("/api/studio/shorts", json={"mode": "paste", "script": SCRIPT, "look": "comic"}, headers=h)
        assert r.status_code == 200, r.text
        video = r.json()
        assert video["workflow"] == "animated_short" and video["short"]["look"] == "comic"
        _run(env)
        video = api.get(f"/api/studio/videos/{video['id']}", headers=h).json()
        scene = video["short"]["scenes"][0]
        r = api.patch(f"/api/studio/shorts/{video['id']}/scenes/{scene['id']}", json={"move": "pan_up"}, headers=h)
        assert r.status_code == 200 and r.json()["short"]["scenes"][0]["move"] == "pan_up"
        r = api.post(f"/api/studio/shorts/{video['id']}/scenes", json={"after": scene["id"], "narration": "Wow."},
                     headers=h)
        assert r.status_code == 200 and len(r.json()["short"]["scenes"]) == len(video["short"]["scenes"]) + 1
        r = api.put(f"/api/studio/shorts/{video['id']}/options", json={"music": "energetic"}, headers=h)
        assert r.status_code == 200 and r.json()["short"]["music"] == "energetic"
        r = api.put(f"/api/studio/shorts/{video['id']}/options", json={"music": "loud"}, headers=h)
        assert r.status_code == 422 and "music" in r.json()["detail"]
        assert api.post("/api/studio/shorts/vid-nope/make", headers=h).status_code == 404
        listed = api.get("/api/studio/projects?kind=short", headers=h).json()
        assert [x["id"] for x in listed] == [video["id"]] and listed[0]["mode"] == "animated_short"
        assert video["id"] not in [x["id"] for x in api.get("/api/studio/projects?kind=full_video", headers=h).json()]
        _run(env)

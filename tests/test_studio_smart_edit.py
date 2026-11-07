"""Smart editing (the plan side; nothing here encodes video): dead air, lone fillers and repeated takes cut, the
length fitted with the opening, ending and must-keeps protected, images shown over the video when they are named,
music and sound effects chosen and attached, ClipForge AI's advice checked and bounded, "Edit it for me" again as
an undoable version that keeps your look and your own sounds, the engine's joins/zoom/overlay rules, and the AI
helper setup (presets, a fake Ollama for download/import, free online services through the OpenAI-style client).
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.jobs import worker

    db.init()
    monkeypatch.setattr(worker, "submit_studio", lambda job_id: None)  # jobs here are run by the test itself
    return tmp_path


def _asset(tmp_path, name: str, kind: str, seconds: float = 30.0, width=1280, height=720) -> dict:
    from clipfoundry import db

    folder = tmp_path / "files" / name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"x")
    probe = {"duration": seconds if kind != "image" else 0, "has_audio": kind != "image", "width": width,
             "height": height}
    return db.insert("assets", {"id": f"as-{Path(name).stem}", "workspace_id": "local", "kind": kind,
                                "filename": name, "sha256": f"sha-{name}", "size": 1, "path": str(path),
                                "probe": probe})


def _words(script: list[tuple[float, str]]) -> list[dict]:
    """Words at the given start times, each 0.3 s long (a sentence ends with punctuation)."""
    return [{"start": t, "end": round(t + 0.3, 3), "w": w} for t, w in script]


def _say(start: float, text: str, step: float = 0.35) -> list[tuple[float, str]]:
    return [(round(start + k * step, 3), w) for k, w in enumerate(text.split())]


def _project(assets: list[dict], brief: dict, name: str = "Lake day") -> dict:
    from clipfoundry.studio import video_flow

    return video_flow.create("local", "local", name=name, asset_ids=[a["id"] for a in assets],
                             brief=brief, style_id="settings", remember={"enabled": False})


def _cut(project, words, ctx=None) -> dict:
    from clipfoundry.studio import video_flow

    return video_flow.rough_cut(project, video_flow._assets(project), words, ctx)


def test_pauses_lone_fillers_and_repeated_takes_are_cut(env):
    from clipfoundry.studio import engine, video_flow

    v = _asset(env, "talk.mp4", "video", 20)
    script = (_say(1.0, "Today we drive to the lake.") +           # 1.0 .. 2.75
              _say(5.0, "The water was") +                          # a false start (5.0 .. 6.0) ...
              _say(7.5, "The water was really cold and clear.") +   # ... and the take that counts (.. 9.9)
              [(10.6, "um")] +                                      # an um on its own after a pause
              _say(11.3, "We swam") + _say(13.0, "until sunset."))  # a 1.05 s pause inside a sentence
    words = {v["id"]: _words(script)}
    project = _project([v], {"smart_edit": "smart", "music": "none", "sound_effects": False})
    plan = _cut(project, words)
    assets = video_flow._assets(project, plan)
    assert engine.validate(plan, assets) == []
    on = [c for c in plan["clips"] if c["include"]]
    off = [c for c in plan["clips"] if not c["include"]]
    # the false start is switched off in place (Put back restores it), the later take plays
    assert len(off) == 1 and off[0]["in_ms"] < 5000 + 100 < off[0]["out_ms"]
    assert any("earlier take" in o["summary"] for o in plan["outline"])
    # no kept part covers the long pauses: 2.75-5.0 (between sentences) and 11.95-13.0 (inside one)
    for a, b in ((2900, 4800), (12150, 12850)):
        assert not any(c["in_ms"] < a and c["out_ms"] > b for c in on), (a, b, on)
    # the um is left out, the words around it are not clipped
    assert not any(c["in_ms"] <= 10650 <= c["out_ms"] for c in on)
    for t in (1.0, 7.5, 11.3, 13.0):
        assert any(c["in_ms"] <= t * 1000 and (t + 0.3) * 1000 <= c["out_ms"] for c in on), t
    # inside one recording every join is a straight cut with a tiny sound fade; the first part keeps the transition
    assert "join" not in plan["clips"][0] and all(c.get("join") == "cut" for c in plan["clips"][1:])
    assert all(c.get("fade_in_ms") == 10 for c in plan["clips"][1:])
    assert plan["smart"]["stats"]["pauses_cut"] >= 2 and plan["smart"]["stats"]["retakes"] == 1
    assert any("Cut" in n and "pause" in n for n in plan["notes"])
    assert engine.duration_ms(plan) < 13000  # 13.9 s of speech and pauses become shorter
    # the frame map: a jump cut never overlaps its neighbour, a dissolve between recordings does
    els, overlap = engine.frame_map(plan, 30)
    assert overlap == round(plan["transition"]["ms"] * 30 / 1000)
    assert all(b["start_f"] == a["end_f"] for a, b in zip(els, els[1:]))


def test_a_stumble_inside_a_sentence_keeps_the_second_time(env):
    from clipfoundry.studio import engine, smart_edit, video_flow

    v = _asset(env, "talk.mp4", "video", 20)
    script = _say(1.0, "The water was the water was really cold.") + _say(5.0, "So so we swam.")
    ws = _words(script)
    assert smart_edit.stumbles(ws, {"i0": 0, "i1": 7}) == {0, 1, 2}
    assert smart_edit.stumbles(ws, {"i0": 8, "i1": 11}) == set()  # one word twice is not a stumble
    project = _project([v], {"smart_edit": "smart", "music": "none"})
    plan = _cut(project, {v["id"]: ws})
    on = [c for c in plan["clips"] if c["include"]]
    first_was, second_the = ws[2], ws[3]
    assert not any(c["in_ms"] <= first_was["start"] * 1000 < c["out_ms"] for c in on)  # the first "was" is cut
    assert any(c["in_ms"] <= second_the["start"] * 1000 and second_the["end"] * 1000 <= c["out_ms"] for c in on)
    assert plan["smart"]["stats"]["stumbles"] == 3 and any("stumbles" in n for n in plan["notes"])
    assert engine.validate(plan, video_flow._assets(project, plan)) == []
    # must-keep words are never touched
    keep = _project([v], {"smart_edit": "smart", "music": "none", "must_keep": "water"}, "Keep")
    assert _cut(keep, {v["id"]: ws})["smart"]["stats"]["stumbles"] == 0


def test_fast_paced_cuts_shorter_pauses_and_punches_in(env):
    from clipfoundry.studio import engine, video_flow

    v = _asset(env, "talk.mp4", "video", 20)
    script = _say(1.0, "One two three.") + _say(2.6, "Four five six.") + _say(4.2, "Seven eight nine.")
    words = {v["id"]: _words(script)}
    smart = _cut(_project([v], {"smart_edit": "smart", "music": "none"}), words)
    project = _project([v], {"smart_edit": "tight", "music": "none"}, "Fast")
    tight = _cut(project, words)
    assert len([c for c in smart["clips"] if c["include"]]) == 1  # 0.55 s pauses stay in "smart"
    assert len([c for c in tight["clips"] if c["include"]]) == 3  # and are cut in "fast-paced"
    assert [c.get("zoom", 1.0) for c in tight["clips"]] == [1.0, engine_zoom(), 1.0]
    assert engine.validate(tight, video_flow._assets(project, tight)) == []


def engine_zoom():
    from clipfoundry.studio import smart_edit

    return smart_edit.PUNCH_IN


def test_length_is_fitted_with_opening_ending_and_must_keep_protected(env):
    from clipfoundry.studio import engine

    v = _asset(env, "long.mp4", "video", 400)
    script, t = [], 1.0
    lines = ["Welcome to the mountain trip story.",                       # the opening
             "Um yeah so basically like okay.",                            # weak
             "We climbed 2000 meters before lunch which was incredible.",  # strong
             "So yeah anyway like you know.",                              # weak
             "The summit view changed how I see hiking forever.",          # strong, must keep "summit"
             "Okay so yeah.",                                              # weak
             "That is why you should start before sunrise."]               # the ending
    for _ in range(6):  # about 1.8 min of talking
        for line in lines:
            script += _say(t, line)
            t += len(line.split()) * 0.35 + 2.0
    words = {v["id"]: _words(script)}
    project = _project([v], {"smart_edit": "smart", "music": "none", "target_duration_s": 60,
                             "must_keep": "summit"})
    plan = _cut(project, words)
    assert plan["smart"]["stats"]["fit_left_out"] > 0
    assert engine.duration_ms(plan) <= 60000 * 1.1
    on = [c for c in plan["clips"] if c["include"]]
    assert on[0]["in_ms"] < 1500 and on[-1]["out_ms"] > (t - 3) * 1000  # opening and ending stay
    said = " ".join(o["summary"] for o in plan["outline"] if not o["summary"].startswith("Left out"))
    assert said.count("summit") == 6  # every must-keep stays
    assert any("fit about 1.0 min" in n for n in plan["notes"])
    left = [o["summary"] for o in plan["outline"] if o["summary"].startswith("Left out")]
    assert left and not any("summit" in x for x in left)
    assert all(x.startswith("Left out (to fit your length): ") for x in left)


def test_images_are_shown_over_the_video_when_they_are_named(env):
    from clipfoundry.studio import engine, video_flow

    v = _asset(env, "talk.mp4", "video", 40)
    lake = _asset(env, "Lake_Tahoe.jpg", "image")
    other = _asset(env, "IMG_2034.png", "image", width=900, height=1600)
    script = []
    t = 0.5
    for line in ["Hello and welcome back everyone.", "Today is a big day for us.", "We finally drove up to see it.",
                 "The lake was bluer than any photo.", "We stayed there for hours and hours.",
                 "Then we drove home in the dark.", "It was the best trip of the summer.",
                 "Thanks for watching this one."]:
        script += _say(t, line)
        t += len(line.split()) * 0.35 + 0.3
    words = {v["id"]: _words(script)}
    project = _project([v, lake, other], {"smart_edit": "smart", "music": "none"})
    plan = _cut(project, words)
    assert [c["kind"] for c in plan["clips"]] == ["video"]  # images are no longer separate slides
    by = {o["asset_id"]: o for o in plan["overlays"]}
    assert set(by) == {lake["id"], other["id"]}
    lake_said = next(w["start"] for w in words[v["id"]] if w["w"].lower().startswith("lake"))
    placed = {x["overlay_id"]: x for x in engine.overlay_timeline(plan)}
    assert abs(placed[by[lake["id"]]["id"]]["out_start_ms"] - (lake_said * 1000 - 300)) < 400
    assert "lake" in by[lake["id"]]["why"].lower()
    assert all(o["motion"] == "zoom" and o["auto"] for o in plan["overlays"])
    assert engine.validate(plan, video_flow._assets(project, plan)) == []
    # without any speech, images stay in the sequence as before
    silent = _asset(env, "scenery.mp4", "video", 10)
    project2 = _project([silent, lake], {"smart_edit": "smart", "music": "none"}, "Scenery")
    plan2 = _cut(project2, {})
    assert [c["kind"] for c in plan2["clips"]] == ["video", "image"] and plan2["overlays"] == []


def test_music_and_sound_effects_are_attached(env):
    from clipfoundry.studio import engine, smart_edit, video_flow

    a = _asset(env, "a.mp4", "video", 20)
    b = _asset(env, "b.mp4", "video", 20)
    song = _asset(env, "my song.mp3", "audio", 95)
    whoosh = _asset(env, "ClipForge effect - Whoosh.m4a", "audio", 0.9)
    swish = _asset(env, "ClipForge effect - Soft swish.m4a", "audio", 0.45)
    words = {a["id"]: _words(_say(1.0, "First part of the day.")), b["id"]: _words(_say(1.0, "Second part here."))}
    project = _project([a, b, song], {"smart_edit": "smart", "music": "auto", "title_card": True})
    values = project["guidance"]["values"]
    choice = smart_edit.choose_music(project, video_flow._assets(project), values)
    assert choice == {"how": "bin", "asset_id": song["id"], "mood": "balanced"}  # your own long audio file
    plan = _cut(project, words, {"music": choice, "library": {"whoosh": whoosh, "swish": swish}})
    music = [i for i in plan["audio"] if i["role"] == "music"]
    assert [(m["asset_id"], m["loop"], m["duck"], m["fade_in_ms"], m["fade_out_ms"]) for m in music] == \
        [(song["id"], True, True, 1500, 2500)]
    fx = [i for i in plan["audio"] if i["role"] == "effect"]
    second = next(c for c in plan["clips"] if c["asset_id"] == b["id"])
    # a whoosh after the title and one where the second recording starts, centred on the dissolve
    assert sorted(i["anchor"]["clip_id"] for i in fx) == sorted([plan["clips"][0]["id"], second["id"]])
    assert all(i["anchor"]["offset_ms"] == plan["transition"]["ms"] // 2 - 540 and i["gain_db"] == -14 for i in fx)
    assert engine.validate(plan, video_flow._assets(project, plan)) == []
    # without a music file of your own, ClipForge's free music in the video's mood
    project2 = _project([a, b], {"smart_edit": "smart", "music": "auto", "feel": "calm"}, "Calm one")
    lib = smart_edit.choose_music(project2, video_flow._assets(project2), project2["guidance"]["values"])
    assert lib["how"] == "library" and lib["key"].startswith("calm-") and lib["mood"] == "calm"
    assert smart_edit.choose_music(_project([a], {"smart_edit": "smart", "music": "none"}, "No music"),
                                   {}, {}) == {"how": ""}


def test_clips_kept_as_they_are_get_music_only_when_asked(env, monkeypatch):
    from clipfoundry.studio import library, video_flow

    v = _asset(env, "talk.mp4", "video", 20)
    made = []
    monkeypatch.setattr(library, "asset", lambda ws, key: made.append(key) or _asset(env, library.filename(key),
                                                                                     "audio", 50))
    plain = _project([v], {})  # no choice at all: the old rough cut, nothing added
    assert video_flow.prepare_smart(plain, video_flow._assets(plain), {}, {}) == {} and made == []
    asked = _project([v], {"smart_edit": "off", "music": "library"}, "Asked")
    assets = video_flow._assets(asked)
    ctx = video_flow.prepare_smart(asked, assets, {}, {})
    assert len(made) == 1 and made[0].startswith("balanced-") and ctx["library"] == {}  # music, no effects
    plan = video_flow.rough_cut(asked, assets, {}, ctx)
    music = [i for i in plan["audio"] if i["role"] == "music"]
    assert len(music) == 1 and music[0]["auto"] and any("free background music" in n for n in plan["notes"])
    assert len(plan["clips"]) == 1 and "smart" not in plan  # the clips themselves are kept as they are


def test_ai_advice_is_checked_bounded_and_used(env):
    from clipfoundry.studio import ai_editor, engine, smart_edit, video_flow

    v = _asset(env, "talk.mp4", "video", 60)
    lines = ["We start at the old harbour today.", "My cousin talks about his cat again.",
             "The boats leave at six every morning.", "Here the fish market opens its doors.",
             "Anyway that reminds me of school.", "We end the day with grilled sardines."]
    script, t = [], 1.0
    for line in lines:
        script += _say(t, line)
        t += len(line.split()) * 0.35 + 0.4
    words = {v["id"]: _words(script)}
    project = _project([v], {"smart_edit": "smart", "music": "none", "must_keep": "school"})
    table = smart_edit.sentence_table(project, video_flow._assets(project), words)
    assert [s["i"] for s in table] == list(range(6))
    answer = json.dumps({"leave_out": [{"i": 1, "why": "off topic"}, {"i": 4, "why": "aside"}, {"i": 99}],
                         "pictures": [{"i": 2, "search": "fishing boats"}, {"i": 50, "search": "nothing"}],
                         "chapters": [{"i": 0, "title": "The harbour"}, {"i": 3, "title": "Fish market"},
                                      {"i": 5, "title": "Dinner"}], "music": "calm"})
    seen = {}

    def fake(settings, prompt, **kw):
        seen.update(kw, prompt=prompt)
        return "<think>hm</think>" + answer

    protected = {s["i"] for s in table if "school" in s["text"].lower()}
    advice = ai_editor.advise(table, project["brief"], {"ai_provider": "ollama"}, protected=protected, complete=fake)
    assert seen["system"] == ai_editor.SYSTEM and seen["task"] == "smart_edit"
    assert "[3] (video 1, 0:" in seen["prompt"] and "must keep: school".lower() in seen["prompt"].lower()
    assert advice["cut"] == {1: "off topic"}  # 4 holds a must-keep, 99 is not a sentence
    assert advice["pictures"] == [{"i": 2, "search": "fishing boats"}] and advice["music"] == "calm"
    assert advice["sent"].startswith("Stayed on this computer")
    plan = _cut(project, words, {"ai": advice})
    off = [o["summary"] for o in plan["outline"] if o["summary"].startswith("Left out")]
    assert off == ["Left out (off topic): My cousin talks about his cat again."]
    assert plan["smart"]["ai"]["used"] and plan["smart"]["picture_queries"][0]["query"] == "fishing boats"
    assert [c["title"] for c in plan["chapters"]] == ["The harbour", "Fish market", "Dinner"]
    assert engine.validate(plan, video_flow._assets(project, plan)) == []
    # a model that wants to cut nearly everything is held to a share of each window
    greedy = json.dumps({"leave_out": [{"i": i} for i in range(6)]})
    capped = ai_editor.advise(table, {}, {"ai_provider": "ollama"}, complete=lambda *a, **k: greedy)
    assert len(capped["cut"]) == int(6 * ai_editor.MAX_CUT_SHARE)
    with pytest.raises(ai_editor.AdviceError):
        ai_editor.advise(table, {}, {"ai_provider": "ollama"}, complete=lambda *a, **k: "no json here")
    with pytest.raises(ai_editor.AdviceError):
        ai_editor.advise(table, {}, {"ai_provider": "heuristic"}, complete=fake)
    # chapters YouTube accepts: three or more, the first at 0:00, each at least 10 s (this video is too short)
    assert smart_edit.chapter_times(plan) == []


def test_ai_windows_bound_every_request():
    from clipfoundry.studio import ai_editor

    sentences = [{"i": i, "file": 1, "start": i * 3.0, "dur": 2.5, "text": "word " * 40} for i in range(400)]
    wins = ai_editor.windows(sentences)
    assert sum(len(w) for w in wins) == 400 and len(wins) > 1
    assert all(len(ai_editor.build_prompt(w, {}, 1, 1)) < ai_editor.WINDOW_CHARS + 2500 for w in wins)
    # the story so far (earlier parts' chapters) is short, and a request with it stays bounded
    so_far = ai_editor.story_so_far([{"i": 3, "title": f"Chapter {n}"} for n in range(40)], 120)
    assert so_far.startswith("Earlier parts (120 sentences") and len(so_far) <= ai_editor.SO_FAR_CHARS
    assert all(len(ai_editor.build_prompt(w, {}, 2, 3, so_far=so_far)) < ai_editor.WINDOW_CHARS + 3000 for w in wins)
    assert ai_editor.story_so_far([], 0) == ""


def _settle(project_id: str):
    from clipfoundry import db
    from clipfoundry.studio import video_flow

    p = db.fetch("studio_projects", project_id)
    return p, video_flow.plan_at(project_id, p["plan_revision"])


class _Lease:
    def progress(self, *_a, **_k):
        pass

    def canceled(self):
        return False

    def alive(self):
        return True


def test_edit_it_for_me_again_is_an_undoable_version_that_keeps_your_choices(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import library, video_flow

    v = _asset(env, "talk.mp4", "video", 30)
    fx = _asset(env, "door.wav", "audio", 1.0)
    script = _say(1.0, "This is the first thing I say.") + _say(6.0, "And this comes after a long pause.")
    (Path(v["path"]).parent / "transcript.json").write_text(json.dumps(
        {"segments": [{"words": _words(script)}]}))  # what the build job listened to
    project = _project([v, fx], {"music": "none"})  # made before smart editing: one whole clip
    plan = video_flow.rough_cut(project, video_flow._assets(project), {v["id"]: _words(script)})
    video_flow.save_revision(project["id"], plan, "Rough cut from your brief", None,
                             {"action": "build", "prev": None, "redo": None})
    assert len(plan["clips"]) == 1
    video_flow.edit(project["id"], 1, {"op": "set", "field": "caption_size", "value": "large"})
    video_flow.edit(project["id"], 2, {"op": "add_audio", "asset_id": fx["id"], "role": "effect", "start_ms": 500})
    monkeypatch.setattr(library, "asset", lambda ws, key: _asset(env, library.filename(key), "audio",
                                                                 50 if key not in library.EFFECTS else 0.9))
    queued = []
    monkeypatch.setattr(video_flow, "enqueue", lambda ws, kind, target, rev=0: queued.append((kind, rev)) or
                        {"id": f"job-{kind}-{rev}"})
    with pytest.raises(video_flow.Conflict):
        video_flow.smart_again(project["id"], 1, {"smart_edit": "smart"})
    with pytest.raises(video_flow.VideoError):
        video_flow.smart_again(project["id"], 3, {"smart_edit": "wild"})
    out = video_flow.smart_again(project["id"], 3, {"smart_edit": "smart", "music": "library"})
    assert out == {"job": "job-video_smart-3"} and queued[-1] == ("video_smart", 3)
    assert db.fetch("studio_projects", project["id"])["brief"]["smart_edit"] == "smart"
    video_flow.smart_job({"target_id": project["id"], "revision": 3}, _Lease())
    p, new = _settle(project["id"])
    assert p["plan_revision"] == 4 and queued[-1] == ("video_preview", 4)
    assert len([c for c in new["clips"] if c["include"]]) == 2  # the long pause is cut now
    assert new["captions"]["size"] == "large"  # your look stays
    roles = sorted((i["role"], bool(i.get("auto"))) for i in new["audio"])
    assert roles == [("effect", False), ("music", True)]  # your door sound stays (one recording: no whoosh)
    assert len({i["id"] for i in new["audio"]}) == len(new["audio"])
    assert any(a.startswith("as-ClipForge music") for a in p["asset_ids"])  # the music is in Your media
    assert any("free background music" in n for n in new["notes"])
    assert any("ClipForge AI was not used" in n for n in new["notes"])
    # a stale job (the video changed after it was queued) changes nothing
    with pytest.raises(video_flow.VideoError):
        video_flow.smart_job({"target_id": project["id"], "revision": 3}, _Lease())
    video_flow.undo(project["id"], 4)
    _p, back = _settle(project["id"])
    assert len(back["clips"]) == 1


def test_engine_rules_for_joins_zoom_and_pictures_over_the_video(env):
    from clipfoundry.studio import engine

    v = _asset(env, "v.mp4", "video", 20)
    img = _asset(env, "pic.png", "image")
    snd = _asset(env, "s.m4a", "audio", 5)
    assets = {a["id"]: a for a in (v, img, snd)}
    clips = [{"id": "c1", "asset_id": v["id"], "kind": "video", "in_ms": 0, "out_ms": 3000, "label": "v",
              "gain_db": 0.0, "include": True},
             {"id": "c2", "asset_id": v["id"], "kind": "video", "in_ms": 4000, "out_ms": 6000, "label": "v",
              "gain_db": 0.0, "include": True, "join": "cut", "zoom": 1.1},
             {"id": "c3", "asset_id": v["id"], "kind": "video", "in_ms": 9000, "out_ms": 12000, "label": "v",
              "gain_db": 0.0, "include": True}]
    plan = {"schema": 2, "timebase": 1000, "engine": engine.ENGINE, "output": {"aspect": "16:9", "fps": 30},
            "layout": "fit", "clips": clips, "transition": {"type": "dissolve", "ms": 500},
            "title": {"enabled": False, "text": "", "ms": 2000}, "captions": {"enabled": False}, "audio": [],
            "tracks": engine.default_tracks(), "word_fixes": {}, "ducking": {"depth_db": 12},
            "overlays": [{"id": "o1", "asset_id": img["id"], "clip_id": "c3", "offset_ms": 0, "length_ms": 9000,
                          "motion": "zoom", "label": "pic"},
                         {"id": "o2", "asset_id": img["id"], "clip_id": "c1", "offset_ms": 2000, "length_ms": 800,
                          "motion": "still", "label": "pic2"}]}
    assert engine.validate(plan, assets) == []
    tl = engine.timeline(plan)
    assert [(s["out_start_ms"], s["out_end_ms"]) for s in tl] == [(0, 3000), (3000, 5000), (4500, 7500)]
    placed = {x["overlay_id"]: x for x in engine.overlay_timeline(plan)}
    assert (placed["o1"]["out_start_ms"], placed["o1"]["out_end_ms"]) == (5000, 7500)  # after the dissolve, inside c3
    assert (placed["o2"]["out_start_ms"], placed["o2"]["out_end_ms"]) == (2000, 2800)
    els, _ = engine.frame_map(plan, 30)
    assert [e["ov_in"] for e in els] == [0, 0, 15]
    bad = json.loads(json.dumps(plan))
    bad["clips"][1]["zoom"] = 3
    bad["clips"][2]["join"] = "wipe"
    bad["overlays"][0].update(asset_id=snd["id"])
    bad["overlays"][1].update(clip_id="nope", length_ms=100, motion="spin")
    problems = " ".join(engine.validate(bad, assets))
    for words in ("zoom of", "unknown join", "not an image or video", "not in this video", "at least 0.5 s",
                  "unknown motion"):
        assert words in problems, words
    # a short clip is fine between two straight cuts, not when it dissolves into the next one
    plan["clips"][1]["out_ms"] = 4600
    assert "transition is longer" in " ".join(engine.validate(plan, assets))
    plan["clips"][2]["join"] = "cut"
    assert engine.validate(plan, assets) == []


def test_overlay_edits(env):
    from clipfoundry.studio import video_flow

    v = _asset(env, "talk.mp4", "video", 20)
    img = _asset(env, "pic.png", "image")
    project = _project([v, img], {"music": "none"})
    plan = video_flow.rough_cut(project, video_flow._assets(project), {})
    video_flow.save_revision(project["id"], plan, "Rough cut", None, {"action": "build", "prev": None, "redo": None})
    cid = plan["clips"][0]["id"]
    out = video_flow.edit(project["id"], 1, {"op": "overlay_add", "asset_id": img["id"], "clip_id": cid,
                                             "offset_ms": 1000, "length_ms": 3000})
    _p, p = _settle(project["id"])
    assert out["note"].startswith("Showed pic.png") and p["overlays"][0]["motion"] == "zoom"
    video_flow.edit(project["id"], 2, {"op": "overlay_set", "overlay_id": "o1", "field": "motion", "value": "still"})
    video_flow.edit(project["id"], 3, {"op": "set", "clip_id": cid, "field": "zoom", "value": 1.2})
    with pytest.raises(video_flow.VideoError):
        video_flow.edit(project["id"], 4, {"op": "overlay_set", "overlay_id": "o1", "field": "length_ms",
                                           "value": 100})
    video_flow.edit(project["id"], 4, {"op": "overlay_remove", "overlay_id": "o1"})
    _p, p = _settle(project["id"])
    assert p["overlays"] == [] and p["clips"][0]["zoom"] == 1.2


def test_smart_edit_route_refuses_unknown_choices_and_stale_versions(env):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app
    from clipfoundry.studio import video_flow

    v = _asset(env, "talk.mp4", "video", 20)
    project = _project([v], {"music": "none"})
    plan = video_flow.rough_cut(project, video_flow._assets(project), {})
    video_flow.save_revision(project["id"], plan, "Rough cut", None, {"action": "build", "prev": None, "redo": None})
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        h = {"X-ClipFoundry": "1"}
        r = api.post(f"/api/studio/videos/{project['id']}/smart", json={"base_revision": 1,
                                                                        "choices": {"rocket": True}}, headers=h)
        assert r.status_code == 422 and "Unknown choices" in r.json()["detail"]
        r = api.post(f"/api/studio/videos/{project['id']}/smart", json={"base_revision": 7, "choices": {}},
                     headers=h)
        assert r.status_code == 409
        view = api.get(f"/api/studio/videos/{project['id']}", headers=h).json()
        assert view["ai_helper"] == {"configured": False, "label": "", "local": False}
        assert view["overlay_timeline"] == [] and view["chapters"] == []
        lib = api.get("/api/studio/sound-library", headers=h).json()
        assert {m["mood"] for m in lib["music"]} == {"calm", "balanced", "energetic"} and "free" in lib["license"].lower()


def test_creating_with_smart_choices_is_checked(env):
    from clipfoundry.studio import video_flow

    v = _asset(env, "talk.mp4", "video", 20)
    with pytest.raises(video_flow.VideoError):
        _project([v], {"smart_edit": "maximum"})
    with pytest.raises(video_flow.VideoError):
        _project([v], {"music": "loud"})
    p = _project([v], {"smart_edit": "tight", "music": "library", "sound_effects": False, "punch_in": True})
    values = p["guidance"]["values"]
    assert values["smart_edit"] == "tight" and values["music"] == "library" and values["sound_effects"] is False


# ------------------------------------------------------------------ ClipForge AI's model setup
class _FakeOllama(BaseHTTPRequestHandler):
    blobs: dict = {}
    created: list = []
    chats: list = []

    def log_message(self, *a):
        pass

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/version":
            return self._json(200, {"version": "0.12.0"})
        if self.path == "/api/tags":
            return self._json(200, {"models": [{"name": "qwen2.5:3b", "size": 1_900_000_000}]})
        return self._json(404, {})

    def do_HEAD(self):  # noqa: N802
        self.send_response(200 if self.path.split("/")[-1] in self.blobs else 404)
        self.end_headers()

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        if self.headers.get("Transfer-Encoding") == "chunked":
            data = b""
            while True:
                size = int(self.rfile.readline().strip(), 16)
                if not size:
                    self.rfile.readline()
                    break
                data += self.rfile.read(size)
                self.rfile.readline()
        else:
            data = self.rfile.read(n)
        if self.path.startswith("/api/blobs/"):
            self.blobs[self.path.split("/")[-1]] = data
            return self._json(201, {})
        body = json.loads(data or b"{}")
        if self.path == "/api/pull":
            lines = [{"status": "pulling manifest"}, {"status": "pulling abc", "total": 100, "completed": 40},
                     {"status": "pulling abc", "total": 100, "completed": 100}, {"status": "success"}]
            out = "\n".join(json.dumps(x) for x in lines).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return None
        if self.path == "/api/create":
            self.created.append(body)
            return self._json(200, {"status": "success"})
        if self.path == "/api/chat":
            self.chats.append(body)
            return self._json(200, {"message": {"content": '{"music": "calm"}'}})
        return self._json(404, {})


@pytest.fixture()
def ollama():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _FakeOllama.blobs, _FakeOllama.created, _FakeOllama.chats = {}, [], []
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _wait_task():
    import time

    from clipfoundry import ai_setup

    end = time.time() + 20
    while time.time() < end:
        t = ai_setup.task()
        if t.get("state") != "running":
            return t
        time.sleep(0.05)
    raise AssertionError(ai_setup.task())


def test_ollama_status_download_and_model_file_import(env, ollama):
    import hashlib

    from clipfoundry import ai_setup

    st = ai_setup.ollama_status(ollama)
    assert st["running"] and st["models"] == [{"name": "qwen2.5:3b", "size_gb": 1.9}]
    down = ai_setup.ollama_status("http://127.0.0.1:9")
    assert not down["running"] and "ollama.com/download" in down["problem"]
    with pytest.raises(ai_setup.SetupError):
        ai_setup.pull(ollama, "bad name; rm -rf")
    ai_setup.pull(ollama, "qwen2.5:3b")
    t = _wait_task()
    assert t["state"] == "done" and t["completed"] == t["total"] == 100
    gguf = env / "my-model.gguf"
    gguf.write_bytes(b"GGUF" + b"\0" * (2 << 20))
    with pytest.raises(ai_setup.SetupError):
        ai_setup.import_gguf(ollama, str(env / "nope.gguf"), "mine")
    with pytest.raises(ai_setup.SetupError):
        ai_setup.import_gguf(ollama, str(gguf), "Bad Name!")
    ai_setup.import_gguf(ollama, str(gguf), "my-model")
    t = _wait_task()
    digest = "sha256:" + hashlib.sha256(gguf.read_bytes()).hexdigest()
    assert t["state"] == "done", t
    assert _FakeOllama.blobs[digest] == gguf.read_bytes()
    assert _FakeOllama.created[-1] == {"model": "my-model", "files": {"my-model.gguf": digest}, "stream": False}


def test_presets_and_the_openai_style_client_for_free_services(env, ollama, monkeypatch):
    import httpx

    from clipfoundry import ai_setup
    from clipfoundry.pipeline import llm

    ids = [p["id"] for p in ai_setup.PRESETS]
    assert ids[:3] == ["builtin", "ollama", "lmstudio"] and {"gemini", "groq", "openrouter"} <= set(ids)
    assert all(p["cost"].startswith("Free") for p in ai_setup.PRESETS if p["id"] != "anthropic")
    assert ai_setup.preset_for_url("https://api.groq.com/openai/v1/")["id"] == "groq"
    assert ai_setup.preset_for_url("http://localhost:1234/v1") is None
    assert llm.provider_label({"ai_provider": "openai_compatible", "openai_url": "https://api.groq.com/openai/v1",
                               "openai_model": "openai/gpt-oss-20b"}) == "Groq openai/gpt-oss-20b"
    assert ai_setup.recommended_model(4096) == "qwen2.5:3b" and ai_setup.recommended_model(8192) == "qwen2.5:7b"
    # the smart editor's own instructions and a larger context reach a local Ollama model
    out = llm.complete({"ai_provider": "ollama", "ollama_url": ollama, "ollama_model": "qwen2.5:3b"}, "hi",
                       system="EDITOR", num_ctx=8192, task="smart_edit")
    assert out == '{"music": "calm"}'
    sent = _FakeOllama.chats[-1]
    assert sent["messages"][0]["content"] == "EDITOR" and sent["options"]["num_ctx"] == 8192
    # an online service: the key goes with the request, a used-up free tier is explained, no GPU lock is taken
    calls = []

    def post(url, json=None, headers=None, timeout=None):  # noqa: A002
        calls.append((url, headers))
        return httpx.Response(429, request=httpx.Request("POST", url), text="slow down")

    monkeypatch.setattr(httpx, "post", post)
    settings = {"ai_provider": "openai_compatible", "openai_url": "https://api.groq.com/openai/v1",
                "openai_api_key": "gsk-test", "openai_model": "openai/gpt-oss-20b"}
    with pytest.raises(llm.ProviderError, match="free limit"):
        llm.complete(settings, "hi")
    assert calls[0][1] == {"Authorization": "Bearer gsk-test"}
    assert calls[0][0] == "https://api.groq.com/openai/v1/chat/completions"
    assert not llm.is_local(settings) and llm.is_local({"ai_provider": "ollama"})


def test_ai_setup_routes(env, ollama, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    db.save_settings({"ollama_url": ollama})
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        h = {"X-ClipFoundry": "1"}
        view = api.get("/api/ai/setup", headers=h).json()
        assert view["ollama"]["running"] and view["presets"][1]["id"] == "ollama"
        assert view["provider"] == "heuristic" and view["recommended"] in ("qwen2.5:3b", "qwen2.5:7b")
        r = api.post("/api/ai/ollama/pull", json={"model": "../../etc"}, headers=h)
        assert r.status_code == 400
        r = api.post("/api/ai/ollama/import", json={"path": "/nope.txt", "name": "x"}, headers=h)
        assert r.status_code == 400 and ".gguf" in r.json()["detail"]


# ------------------------------------------------------------------ takes across files, chatter, the cold open
def _lines(start: float, lines: list[str], gap: float = 1.0, step: float = 0.35) -> tuple[list, float]:
    """Sentences one after another from `start`, `gap` seconds apart; returns (timed words, the end time)."""
    script, t = [], start
    for line in lines:
        script += _say(t, line, step)
        t += len(line.split()) * step + gap
    return script, t


def test_the_same_line_in_another_file_keeps_the_cleanest_take_and_a_refrain_stays(env):
    from clipfoundry.studio import engine, smart_edit, video_flow

    a = _asset(env, "take1.mp4", "video", 60)
    b = _asset(env, "take2.mp4", "video", 60)
    refrain = "Let's get into the next one right now."
    first, _t = _lines(1.0, ["Um the the lake was um really cold that morning.",  # a rough take of line one
                             refrain, "We packed the tent before the rain came down.", refrain])
    second, _t = _lines(1.0, ["The lake was really cold that morning.",            # the clean take, in file two
                              refrain, "Then we drove home along the coast road.", refrain])
    words = {a["id"]: _words(first), b["id"]: _words(second)}
    project = _project([a, b], {"smart_edit": "smart", "music": "none", "sound_effects": False})
    values = (project.get("guidance") or {}).get("values") or {}
    judged = smart_edit.judge_sentences(project, video_flow._assets(project), words, values)
    one, two = judged["talks"]
    assert one["status"][0] == "retake" and "take2.mp4" in one["why"][0] and two["status"][0] == "keep"
    assert judged["stats"]["takes"] == 1 and any("said again" in n for n in judged["notes"])
    # the refrain is said four times: a catchphrase, never a retake
    assert all(t["status"][k] == "keep" for t in (one, two) for k, s in enumerate(t["sents"]) if "next one" in s["text"])
    plan = _cut(project, words)
    assert plan["smart"]["stats"]["takes"] == 1
    off = [o["summary"] for o in plan["outline"] if o["summary"].startswith("Left out")]
    assert len(off) == 1 and "another take of this line" in off[0] and "lake was" in off[0]
    assert engine.validate(plan, video_flow._assets(project, plan)) == []
    # a must-keep word protects a take
    keep = _project([a, b], {"smart_edit": "smart", "music": "none", "must_keep": "lake"}, "Keep")
    assert _cut(keep, words)["smart"]["stats"]["takes"] == 0


def test_chatter_warm_ups_camera_talk_and_a_sign_off_before_the_end_are_left_out(env):
    from clipfoundry.studio import smart_edit, video_flow

    first_part = ["Okay so.", "Is this thing on?", "Alright let's go.",
                  "Today we climb the mountain behind the village before the snow comes.",
                  "The path starts at the old church and follows the stream.",
                  "That's it for today, thanks for watching and see you next time.", "Did we get that?"]
    rec1, _t = _lines(0.5, first_part, gap=0.8)
    rec2, _t = _lines(0.5, ["Here is the summit at last with the whole valley below us.",
                            "Thanks for watching, see you in the next one."], gap=0.8)
    a = _asset(env, "walk.mp4", "video", 40)
    b = _asset(env, "summit.mp4", "video", 40)
    words = {a["id"]: _words(rec1), b["id"]: _words(rec2)}
    project = _project([a, b], {"smart_edit": "smart", "music": "none", "sound_effects": False})
    values = (project.get("guidance") or {}).get("values") or {}
    judged = smart_edit.judge_sentences(project, video_flow._assets(project), words, values)
    one, two = judged["talks"]
    assert one["status"] == ["chatter", "chatter", "chatter", "keep", "keep", "chatter", "chatter"]
    assert "throat-clearer" in one["why"][0] and "is this thing on" in one["why"][1]
    assert "sign-off in the middle" in one["why"][5] and "whoever is recording" in one["why"][6]
    assert two["status"] == ["keep", "keep"]  # the last recording's sign-off is the video's ending
    assert judged["stats"]["chatter"] == 5 and any("never meant for the viewer" in n for n in judged["notes"])
    plan = _cut(project, words)
    assert plan["smart"]["stats"]["chatter"] == 5
    assert smart_edit.chatter([], True) == {}
    # with cut_retakes off the takes rule is off too, chatter is still left out
    alone = _project([a], {"smart_edit": "smart", "music": "none", "cut_retakes": False}, "Alone")
    plan = _cut(alone, {a["id"]: _words(rec1)})
    said = [o["summary"] for o in plan["outline"] if not o["summary"].startswith("Left out")]
    assert any("thanks for watching" in s for s in said)  # now the only recording: its sign-off is the ending
    assert not any("Did we get that" in s for s in said)


HIKE = ["Welcome back to the channel and to the start of a long walk.", "We left the car at the bottom of the valley.",
        "The first hour follows a forest road with nothing to see.", "Then the trees stop and the ground turns to rock.",
        "Why did nobody tell me the secret that 90 percent of hikers never learn?",
        "Water runs out faster than you think up here.", "We filled the bottles at a spring near the hut.",
        "The hut keeper told us the pass was still open.", "From the hut it is two hours to the ridge.",
        "The wind picked up as soon as we reached the ridge.", "My hands went numb inside the gloves.",
        "We stopped for bread and cheese behind a boulder.", "A pair of ravens watched us the whole time.",
        "After lunch the path crosses a field of loose stones.", "Every step slid back half a step.",
        "The last part is a scramble with a fixed cable.", "The cable was cold enough to hurt.",
        "At the top the clouds opened for about a minute.", "We could see the lake and the village far below.",
        "Then the fog came back and we started down.", "Going down is harder on the knees than going up.",
        "We reached the hut again just before dark.", "The keeper had soup ready for everyone.",
        "That night the temperature dropped below freezing.", "In the morning the stones were white with frost.",
        "The walk back to the car took three more hours.", "My boots are finished after this trip.",
        "Next time I will bring thicker gloves and more water.", "The whole trip cost us nothing but time.",
        "If you only do one walk this year, do this one.", "The best views come after the worst stretch.",
        "Thanks for coming along on this one.", "See you on the next walk."]


def test_a_long_video_opens_with_its_strongest_line(env):
    from clipfoundry.studio import engine, smart_edit, video_flow

    v = _asset(env, "hike.mp4", "video", 400)
    script, end = _lines(1.0, HIKE, gap=1.0, step=0.4)
    assert end >= 140
    words = {v["id"]: _words(script)}
    project = _project([v], {"smart_edit": "smart", "music": "none", "sound_effects": False})
    plan = _cut(project, words)
    hook = plan["clips"][0]
    assert hook["id"] == "hook" and hook["hook"] is True and hook["include"]
    secret = next(s for s in smart_edit.sentence_table(project, video_flow._assets(project), words)
                  if "secret" in s["text"])
    assert hook["in_ms"] <= secret["start"] * 1000 < hook["out_ms"] and hook["out_ms"] - hook["in_ms"] < 12000
    # the line still plays where it was said, in a clip that is not the cold open
    assert any(c["include"] and c["id"] != "hook" and c["in_ms"] <= secret["start"] * 1000 < c["out_ms"]
               for c in plan["clips"])
    assert plan["outline"][0]["summary"].startswith("Cold open: “Why did nobody tell me")
    assert any(n.startswith("Opened with the strongest line") for n in plan["notes"])
    assert plan["smart"]["stats"]["cold_open"].startswith("Why did nobody")
    assert engine.validate(plan, video_flow._assets(project, plan)) == []
    assert smart_edit._locate(plan, v["id"], int(secret["start"] * 1000) + 100)["clip_id"] != "hook"
    # switched off in the brief, or a short video: no cold open
    plain = _cut(_project([v], {"smart_edit": "smart", "music": "none", "cold_open": False}, "Plain"), words)
    assert not any(c.get("hook") for c in plain["clips"])
    short_words = {v["id"]: _words(_lines(1.0, HIKE[:8], gap=1.0, step=0.4)[0])}
    assert not any(c.get("hook") for c in _cut(project, short_words)["clips"])
    # ClipForge AI's hook wins when it names a line that plays
    ravens = next(s for s in smart_edit.sentence_table(project, video_flow._assets(project), words)
                  if "ravens" in s["text"])
    led = _cut(project, words, {"ai": {"hook": {"i": ravens["i"], "why": "a surprise"}, "cut": {}}})
    assert led["clips"][0]["id"] == "hook" and led["clips"][0]["in_ms"] <= ravens["start"] * 1000 < led["clips"][0]["out_ms"]
    assert any("chosen by ClipForge AI" in n for n in led["notes"])
    # shorten the introduction skips the cold open and cuts the clip after it
    whole = _cut(_project([v], {"smart_edit": "smart", "music": "none", "cut_pauses": False}, "Whole"), words)
    assert whole["clips"][0]["id"] == "hook" and whole["clips"][1]["include"]
    shorter, note = video_flow.apply_edit(whole, {"op": "shorten_intro", "seconds": 8}, words)
    assert shorter["clips"][0]["in_ms"] == whole["clips"][0]["in_ms"] and "Shortened" in note
    assert shorter["clips"][1]["in_ms"] > whole["clips"][1]["in_ms"]


def test_ai_advice_has_a_time_budget_a_story_so_far_a_hook_and_skips_what_the_rules_cut():
    import time

    from clipfoundry.studio import ai_editor

    sentences = [{"i": i, "file": 1, "start": i * 3.0, "dur": 2.5, "text": f"sentence {i} " + "word " * 30}
                 for i in range(80)]
    assert len(ai_editor.windows(sentences)) >= 2
    prompts = []

    def fake(settings, prompt, **kw):
        prompts.append(prompt)
        return json.dumps({"leave_out": [{"i": 3, "why": "weak"}], "chapters": [{"i": 0, "title": "The start"}],
                           "hook": {"i": 2, "why": "a question"}, "music": "calm"})

    advice = ai_editor.advise(sentences, {}, {"ai_provider": "ollama", "ai_edit_timeout_s": 60}, complete=fake,
                              skip={1, 5})
    assert advice["hook"] == {"i": 2, "why": "a question"} and advice["not_sent"] == 2
    assert "[1] " not in prompts[0] and "[2] " in prompts[0]  # what the rules cut is not sent
    assert advice["read"] == 78 and advice["skipped_sentences"] == 0 and advice["budget_s"] == 900
    assert len(prompts) >= 2 and "Earlier parts (" in prompts[1] and "The start" in prompts[1]
    assert "Earlier parts" not in prompts[0]
    # a hook the model also wants left out is no hook
    def contrary(settings, prompt, **kw):
        return json.dumps({"leave_out": [{"i": 2}], "hook": {"i": 2}})
    assert ai_editor.advise(sentences[:5], {}, {"ai_provider": "ollama"}, complete=contrary)["hook"] is None
    # the time budget: the first part is always read, the rest is left to the rules and said so
    slow = []

    def slowly(settings, prompt, **kw):
        slow.append(prompt)
        time.sleep(0.2)
        return json.dumps({"leave_out": []})

    tight = ai_editor.advise(sentences, {}, {"ai_provider": "ollama", "ai_edit_timeout_s": 60}, complete=slowly,
                             budget_s=0.1)
    assert len(slow) == 1 and tight["read"] == len(ai_editor.windows(sentences)[0])
    assert tight["skipped_sentences"] == 80 - tight["read"] and any("time budget" in p for p in tight["problems"])
    assert ai_editor.budget_for({"ai_edit_timeout_s": 60}) == 900 and ai_editor.budget_for({"ai_edit_timeout_s": 2}) == 120

"""Following a script (studio/script_cut.py and the video_flow wiring): one clip per run of script lines, the best
take of each line, other takes switched off behind it and swapped in with "Use this take" (a clip split around the
line), off-script speech switched off at the end, headings as chapters, the script given with a new video or added
later (a new version that Undo reverts), the checked payload, and transcripts kept in a linked file's work folder
with the speech model released after a batch. No speech model, no FFmpeg: words are given."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_studio_smart_edit import _Lease, _asset, _cut, _project, _say, _settle, _words, env  # noqa: F401

SCRIPT = """# The lake

Welcome back, today we walk to the hidden lake behind the ridge.
The water was cold and clear that morning.
We swam for ten minutes and then dried off in the sun.
Nobody else came the whole afternoon.
"""


def _speech(start: float, lines: list[str], gap: float = 0.6) -> list[dict]:
    script, t = [], start
    for line in lines:
        script += _say(t, line, 0.4)
        t += len(line.split()) * 0.4 + gap
    return _words(script)


def _two_takes(env):
    """Recording one says every line (line two with a filler, line three fluffed); recording two says lines two
    and three cleanly, with some talk that is not in the script."""
    a = _asset(env, "cam-a.mp4", "video", 120)
    b = _asset(env, "cam-b.mp4", "video", 120)
    first = _speech(1.0, ["Welcome back, today we walk to the hidden lake behind the ridge.",
                          "The water was um cold and clear that morning.",
                          "We swam for the the ten minutes and um then dried off in the sun.",
                          "Nobody else came the whole afternoon."])
    second = _speech(1.0, ["Let me say the middle part again from here.",
                           "The water was cold and clear that morning.",
                           "We swam for ten minutes and then dried off in the sun.",
                           "And that is the part we needed, I think we got it."], gap=1.0)
    return a, b, {a["id"]: first, b["id"]: second}


def test_the_cut_follows_the_script_with_the_best_take_of_every_line(env):
    from clipfoundry.studio import engine, script, video_flow

    a, b, words = _two_takes(env)
    parsed = script.parse("lake.md", SCRIPT)
    project = _project([a, b], {"smart_edit": "smart", "music": "none", "sound_effects": False})
    project["script"] = video_flow.script_payload(parsed)
    plan = _cut(project, words)
    assert engine.validate(plan, video_flow._assets(project, plan)) == []
    on = [c for c in plan["clips"] if c["include"]]
    # (line 1 is the heading) line 2 from recording one; lines 3 and 4 said more cleanly in recording two, as one
    # clip; line 5 from recording one again
    assert [(c["asset_id"], c["take_of"]["lines"]) for c in on] == [(a["id"], [2]), (b["id"], [3, 4]), (a["id"], [5])]
    assert on[1]["take_of"]["takes"]["3"]["in_ms"] < on[1]["take_of"]["takes"]["4"]["in_ms"]
    assert "join" not in on[1] and on[2].get("join") is None  # a change of recording: the transition plays
    alts = [c for c in plan["clips"] if not c["include"] and "line" in c["take_of"]]
    assert sorted(c["take_of"]["line"] for c in alts) == [3, 4] and all(c["asset_id"] == a["id"] for c in alts)
    assert all(c["take_of"]["quality"] < 1.0 for c in alts)
    off_script = [c for c in plan["clips"] if not c["include"] and c["take_of"].get("off_script")]
    assert len(off_script) == 2 and all(c["asset_id"] == b["id"] for c in off_script)
    rows = {o["clip_id"]: o["summary"] for o in plan["outline"]}
    assert rows[on[0]["id"]].startswith("Line 2: Welcome back") and rows[on[1]["id"]].startswith("Lines 3 to 4: The water")
    assert any(s.startswith("Another take of line 4 (") for s in rows.values())
    assert any(s.startswith("Not in the script: Let me say") for s in rows.values())
    assert plan["chapters"] == [{"clip_id": on[0]["id"], "offset_ms": 0, "title": "The lake"}]
    assert plan["notes"][0] == "Followed your script: 4 of 4 lines were found in the footage."
    assert plan["script"]["filename"] == "lake.md" and plan["smart"]["script"] is True
    by_n = {row["n"]: row for row in plan["script"]["lines"]}
    assert by_n[1]["status"] == "heading" and by_n[3]["status"] == "matched" and by_n[3]["clip_id"] == on[1]["id"]
    assert [t["clip_id"] for t in by_n[4]["takes"]] == [c["id"] for c in alts if c["take_of"]["line"] == 4]
    assert by_n[5]["clip_id"] == on[2]["id"] and by_n[5]["takes"] == []
    assert plan["smart"]["stats"]["lines_found"] == 4 and plan["smart"]["stats"]["alternatives"] == 2
    assert plan["smart"]["ai"]["used"] is False
    # the script decides even with smart editing off, and rough_cut takes that road
    plain = _project([a, b], {"smart_edit": "off", "music": "none"}, "Plain")
    plain["script"] = project["script"]
    assert _cut(plain, words)["smart"]["script"] is True


def test_use_this_take_swaps_a_line_and_splits_the_clip_around_it(env):
    from clipfoundry.studio import engine, script, video_flow

    a, b, words = _two_takes(env)
    project = _project([a, b], {"smart_edit": "smart", "music": "none", "sound_effects": False})
    project["script"] = video_flow.script_payload(script.parse("lake.md", SCRIPT))
    plan = _cut(project, words)
    assets = video_flow._assets(project, plan)
    alt4 = next(c for c in plan["clips"] if not c["include"] and c["take_of"].get("line") == 4)
    chain = next(c for c in plan["clips"] if c["include"] and c["take_of"]["lines"] == [3, 4])
    new, note = video_flow.apply_edit(plan, {"op": "use_take", "clip_id": alt4["id"]}, words, assets)
    assert engine.validate(new, assets) == []
    assert note.startswith("Line 4 now plays from cam-a.mp4")
    on = [c for c in new["clips"] if c["include"]]
    assert [(c["asset_id"], c["take_of"]["lines"]) for c in on] == [(a["id"], [2]), (b["id"], [3]), (a["id"], [4]),
                                                                    (a["id"], [5])]
    assert on[1]["id"] == chain["id"] and on[1]["out_ms"] == chain["take_of"]["takes"]["3"]["out_ms"]
    assert on[2]["in_ms"] == alt4["in_ms"] and on[2]["out_ms"] == alt4["out_ms"]
    assert on[3].get("join") == "cut" and on[3].get("fade_in_ms") == 10  # back in recording one: a straight cut
    retired = next(c for c in new["clips"] if not c["include"] and c["take_of"].get("line") == 4)
    assert retired["asset_id"] == b["id"] and retired["in_ms"] == chain["take_of"]["takes"]["4"]["in_ms"]
    assert new["clips"].index(retired) == new["clips"].index(on[2]) + 1
    assert len({c["id"] for c in new["clips"]}) == len(new["clips"])
    rows = {o["clip_id"]: o["summary"] for o in new["outline"]}
    assert rows[on[2]["id"]].startswith("Line 4: We swam for the the ten")
    assert rows[retired["id"]].startswith("Another take of line 4 (the one that played before)")
    assert rows[on[1]["id"]].startswith("Line 3: ")
    line4 = next(r for r in new["script"]["lines"] if r["n"] == 4)
    assert line4["clip_id"] == on[2]["id"] and [t["clip_id"] for t in line4["takes"]] == [retired["id"]]
    # swapping back restores the earlier take, and the chapter stays at the start
    back, _n = video_flow.apply_edit(new, {"op": "use_take", "clip_id": retired["id"]}, words, assets)
    assert engine.validate(back, assets) == []
    assert [c["asset_id"] for c in back["clips"] if c["include"]] == [a["id"], b["id"], b["id"], a["id"]]
    assert back["chapters"][0]["clip_id"] == on[0]["id"]
    with pytest.raises(video_flow.VideoError):
        video_flow.apply_edit(new, {"op": "use_take", "clip_id": on[0]["id"]}, words, assets)
    with pytest.raises(video_flow.VideoError):
        video_flow.apply_edit(new, {"op": "use_take", "clip_id": "nope"}, words, assets)


def test_a_script_can_come_with_the_video_or_later_and_the_payload_is_checked(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import script, video_flow

    a, b, words = _two_takes(env)
    for asset, ws in ((a, words[a["id"]]), (b, words[b["id"]])):
        (Path(asset["path"]).parent / "transcript.json").write_text(json.dumps({"segments": [{"words": ws}]}))
    parsed = script.parse("lake.md", SCRIPT)
    project = video_flow.create("local", "local", name="Lake", asset_ids=[a["id"], b["id"]],
                                brief={"smart_edit": "smart", "music": "none"}, style_id="settings",
                                remember={"enabled": False}, script=parsed)
    stored = db.fetch("studio_projects", project["id"])["script"]
    assert stored["filename"] == "lake.md" and [ln["n"] for ln in stored["lines"]] == [1, 2, 3, 4, 5]
    assert stored["lines"][0]["kind"] == "heading" and stored["lines"][1]["tokens"]
    queued = []
    monkeypatch.setattr(video_flow, "enqueue", lambda ws, kind, target, rev=0: queued.append((kind, rev)) or
                        {"id": f"job-{kind}-{rev}"})
    video_flow.build({"target_id": project["id"]}, _Lease())
    p, plan = _settle(project["id"])
    assert plan["script"]["filename"] == "lake.md" and plan["smart"]["script"] is True
    view = video_flow.view(p)
    assert view["script"]["counts"]["lines"] == 4 and view["script"]["lines"][1]["text"].startswith("Welcome back")
    # a later script on a project made without one: a new version that Undo reverts
    other = _project([a, b], {"smart_edit": "smart", "music": "none"}, "Later")
    video_flow.build({"target_id": other["id"]}, _Lease())
    o, before = _settle(other["id"])
    assert not before.get("script") and video_flow.view(o)["script"] is None
    with pytest.raises(video_flow.Conflict):
        video_flow.set_script(other["id"], 99, {"text": SCRIPT})
    out = video_flow.set_script(other["id"], 1, {"text": SCRIPT, "filename": "typed.txt"})
    assert out == {"job": "job-video_smart-1", "script": True} and queued[-1] == ("video_smart", 1)
    video_flow.smart_job({"target_id": other["id"], "revision": 1}, _Lease())
    o, after = _settle(other["id"])
    assert o["plan_revision"] == 2 and after["script"]["filename"] == "typed.txt"
    assert any(r["revision"] == 2 and r["note"] == "Followed your script" for r in video_flow.view(o)["revisions"])
    # taking the script away cuts from the brief again
    assert video_flow.set_script(other["id"], 2, None)["script"] is False
    video_flow.smart_job({"target_id": other["id"], "revision": 2}, _Lease())
    o, plain = _settle(other["id"])
    assert o["plan_revision"] == 3 and not plain.get("script") and db.fetch("studio_projects", o["id"])["script"] == {}
    # the payload
    assert video_flow.script_payload(None) == {} and video_flow.script_payload({}) == {}
    typed = video_flow.script_payload({"text": "One line here.\nAnd another one."})
    assert [ln["text"] for ln in typed["lines"]] == ["One line here.", "And another one."] and typed["counts"]["lines"] == 2
    given = video_flow.script_payload({"lines": [{"text": " spaced   out ", "kind": "odd", "tokens": ["x"]}]})
    assert given["lines"] == [{"n": 1, "text": "spaced out", "kind": "line", "speaker": "", "section": "",
                               "tokens": script.normalize("spaced out")}]
    for bad in ("text", {"lines": "no"}, {"lines": [{"kind": "line"}]}, {"text": "   "}, {"lines": []}):
        with pytest.raises(video_flow.VideoError):
            video_flow.script_payload(bad)


def test_transcripts_of_a_linked_file_live_in_its_work_folder_and_the_model_is_released(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.pipeline import transcribe
    from clipfoundry.studio import uploads, video_flow

    own = env / "footage" / "holiday.mp4"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"x")
    linked = db.insert("assets", {"id": "as-linked", "workspace_id": "local", "kind": "video", "filename": "holiday.mp4",
                                  "sha256": "quick:abc", "size": 1, "path": str(own),
                                  "probe": {"duration": 30.0, "has_audio": True, "width": 1920, "height": 1080}})
    work = uploads.work_dir(linked)
    assert work != own.parent and work.is_dir()
    calls = {"extract": [], "long": [], "released": 0}
    monkeypatch.setattr(video_flow, "extract_audio", lambda src, dst, dur, progress=None, cancel=None:
                        calls["extract"].append((src, dst)) or dst.write_bytes(b"wav"))

    def fake_long(wav, duration, settings, ctx, *, parts_dir, lo, hi, label, **kw):
        calls["long"].append((wav, parts_dir, lo, hi, label))
        ctx.progress(lo, label)
        return {"segments": [{"words": [{"start": 1.0, "end": 1.3, "w": "hello"}]}]}

    monkeypatch.setattr(transcribe, "transcribe_long", fake_long)
    monkeypatch.setattr(transcribe, "release_model", lambda: calls.__setitem__("released", calls["released"] + 1))
    progress = []

    class Lease(_Lease):
        def progress(self, f, m=""):
            progress.append((round(f, 3), m))

    words = video_flow.listen({linked["id"]: linked}, [linked["id"], "missing"], {}, Lease(), 0.1, 0.5)
    assert words == {linked["id"]: [{"start": 1.0, "end": 1.3, "w": "hello"}]}
    assert calls["extract"] == [(own, work / "audio.wav")]  # the sound goes to the work folder, never beside the file
    assert calls["long"][0][1] == work / "transcript.parts" and calls["long"][0][4] == "Listening to holiday.mp4"
    assert calls["long"][0][2] == pytest.approx(0.14) and calls["long"][0][3] == pytest.approx(0.5)
    assert (work / "transcript.json").is_file() and not (own.parent / "transcript.json").exists()
    assert calls["released"] == 1 and progress[0] == (0.1, "Listening to holiday.mp4")
    # cached: no second transcription, the model is still released after the batch
    assert video_flow.transcript_words(linked, {}, cached_only=True) == words[linked["id"]]
    video_flow.listen({linked["id"]: linked}, [linked["id"]], {})
    assert len(calls["long"]) == 1 and calls["released"] == 2
    # the model is released even when listening fails
    monkeypatch.setattr(video_flow, "transcript_words", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        video_flow.listen({linked["id"]: linked}, [linked["id"]], {})
    assert calls["released"] == 3

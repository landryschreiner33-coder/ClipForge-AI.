"""Animated shorts and the owner's changes in the editor (docs/clipforge/ANIMATED_SHORTS.md): fades that no longer fit
a clip that got shorter are shortened, a whoosh the owner muted or removed is never put back, sounds attached to a
deleted scene are named in the notes, a scene added after a clip the owner replaced goes after it, and the Scenes
panel's length is the video's.

Same stand-in voice and camera moves as tests/test_studio_shorts_flow.py.
"""
from __future__ import annotations

from test_studio_shorts_flow import _edit, _fresh, _make, _plan, _run, _scenes, _tone, env  # noqa: F401


def _own_file(env, pid: str, kind: str) -> dict:
    """A file of the owner's in the short's media bin."""
    from PIL import Image

    from clipfoundry import db

    if kind == "audio":
        path = env["tmp"] / "pop.wav"
        _tone(path, 1.0)
        probe = {"duration": 1.0, "has_audio": True}
    else:
        path = env["tmp"] / "beach.png"
        Image.new("RGB", (1080, 1920), "#3a7").save(path)
        probe = {"duration": 0, "has_audio": False, "width": 1080, "height": 1920}
    asset = db.insert("assets", {"id": f"as-own-{kind}", "workspace_id": "local", "kind": kind, "filename": path.name,
                                 "sha256": f"own-{kind}", "size": path.stat().st_size, "path": str(path),
                                 "probe": probe})
    db.update("studio_projects", pid, asset_ids=list(_fresh(pid)["asset_ids"]) + [asset["id"]])
    return asset


def _valid(pid: str) -> None:
    from clipfoundry.studio import engine, video_flow

    plan = _plan(pid)
    assert engine.validate(plan, video_flow._assets(_fresh(pid), plan)) == []


def test_fades_that_no_longer_fit_a_shorter_clip_are_shortened(env):
    from clipfoundry.makers import shorts

    project = _make(env)
    pid = project["id"]
    last = _plan(pid)["clips"][-1]
    length = last["out_ms"] - last["in_ms"]
    _edit(pid, {"op": "set", "clip_id": last["id"], "field": "fade_out_ms", "value": length - 100})
    _edit(pid, {"op": "set", "clip_id": last["id"], "field": "fade_in_ms", "value": 100})
    # a scene after it: the old last clip loses the pause at the end and gets shorter than its fades
    shorts.add_scene(_fresh(pid), last["scene_id"], "And octopuses can change colour in a blink.")
    jobs = _run(env)
    assert [j["status"] for j in jobs] == ["done"], [j["error"] for j in jobs]
    clip = next(c for c in _plan(pid)["clips"] if c["id"] == last["id"])
    assert clip["out_ms"] - clip["in_ms"] < length
    assert 0 < clip["fade_in_ms"] + clip["fade_out_ms"] <= clip["out_ms"] - clip["in_ms"]
    assert clip["fade_out_ms"] > clip["fade_in_ms"]  # shortened in proportion
    _valid(pid)


def test_a_whoosh_the_owner_muted_or_removed_is_never_put_back(env):
    from clipfoundry.makers import shorts

    project = _make(env, script="One.\n\nTwo two.\n\nThree three three.\n\nFour four.\n\nFive.")
    pid = project["id"]
    plan = _plan(pid)
    whooshes = [a for a in plan["audio"] if a["role"] == "effect"]
    assert [w["anchor"]["clip_id"] for w in whooshes] == [c["id"] for c in plan["clips"]][1::2]
    muted, removed = whooshes[0], whooshes[1]
    _edit(pid, {"op": "audio_set", "audio_id": muted["id"], "field": "mute", "value": True})
    _edit(pid, {"op": "audio_remove", "audio_id": removed["id"]})
    first = _scenes(pid, _plan(pid))[0]
    for change in ({"narration": "One, then."}, {"move": "pan_up"}):  # two builds: it stays as the owner left it
        shorts.update_scene(_fresh(pid), first["id"], change)
        _run(env)
        effects = [a for a in _plan(pid)["audio"] if a["role"] == "effect"]
        on = {}
        for a in effects:
            on.setdefault(a["anchor"]["clip_id"], []).append(a)
        assert len(on[muted["anchor"]["clip_id"]]) == 1 and on[muted["anchor"]["clip_id"]][0]["mute"] is True
        assert not on[muted["anchor"]["clip_id"]][0].get("auto")  # the owner's now
        assert removed["anchor"]["clip_id"] not in on
        _valid(pid)


def test_sounds_attached_to_a_deleted_scene_are_named(env):
    from clipfoundry.makers import shorts

    project = _make(env)
    pid = project["id"]
    gone = _scenes(pid, _plan(pid))[1]
    pop = _own_file(env, pid, "audio")
    _edit(pid, {"op": "add_audio", "asset_id": pop["id"], "role": "effect", "clip_id": gone["id"], "offset_ms": 100})
    shorts.delete_scene(_fresh(pid), gone["id"])
    _run(env)
    plan = _plan(pid)
    assert pop["id"] not in [a["asset_id"] for a in plan["audio"]]
    assert any("no longer in the short" in n and "pop.wav" in n for n in plan["notes"])
    _valid(pid)


def test_a_scene_added_after_a_clip_the_owner_replaced_goes_after_it(env):
    from clipfoundry.makers import shorts

    project = _make(env)
    pid = project["id"]
    scenes = _scenes(pid, _plan(pid))
    beach = _own_file(env, pid, "image")
    _edit(pid, {"op": "replace", "clip_id": scenes[1]["id"], "asset_id": beach["id"]})
    new = shorts.add_scene(_fresh(pid), scenes[1]["id"], "Octopuses can taste with their arms.")
    _run(env)
    plan = _plan(pid)
    ids = [c["id"] for c in plan["clips"]]
    assert ids.index(new) == ids.index(scenes[1]["id"]) + 1
    mine = plan["clips"][ids.index(scenes[1]["id"])]
    assert mine["asset_id"] == beach["id"] and not mine.get("scene_id")  # the owner's picture stays
    _valid(pid)


def test_the_scenes_panel_says_how_long_the_video_is(env):
    from clipfoundry.makers import shorts
    from clipfoundry.studio import engine

    project = _make(env)
    pid = project["id"]
    plan = _plan(pid)
    assert shorts.view(_fresh(pid))["seconds"] == round(engine.duration_ms(plan) / 1000, 1)
    _edit(pid, {"op": "remove", "clip_id": plan["clips"][1]["id"]})  # switched off in the editor: not counted
    plan = _plan(pid)
    assert shorts.view(_fresh(pid))["seconds"] == round(engine.duration_ms(plan) / 1000, 1)
    shorts.add_scene(_fresh(pid), None, "Here is a strange fact.")  # not made yet: an estimate is added
    waiting = shorts.view(_fresh(pid))["seconds"]
    assert waiting > round(engine.duration_ms(plan) / 1000, 1)

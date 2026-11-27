"""Undo, redo and going back to a version of an animated short (docs/clipforge/ANIMATED_SHORTS.md): the scenes and the
short's choices go back with the video, so the Scenes panel shows what the video shows and the next build keeps it.
A change the owner made after the version being left, still waiting to be made, stays and is made on top.

Same stand-in voice and camera moves as tests/test_studio_shorts_flow.py.
"""
from __future__ import annotations

import pytest
from test_studio_shorts_flow import SCRIPT, _edit, _fresh, _make, _plan, _run, _scenes, env  # noqa: F401


def _scene(scene_id: str) -> dict | None:
    from clipfoundry import db

    return db.fetch("short_scenes", scene_id)


def _words(project_id: str, scene_id: str) -> list[str]:
    from clipfoundry.studio import uploads, video_flow

    clip = next(c for c in _plan(project_id)["clips"] if c.get("scene_id") == scene_id)
    return [w["w"] for w in video_flow.transcript_words(uploads.asset(clip["asset_id"], "local"), {},
                                                        cached_only=True)]


def _clip_of(project_id: str, scene_id: str) -> str:
    return next(c["asset_id"] for c in _plan(project_id)["clips"] if c.get("scene_id") == scene_id)


def _undo(project_id: str) -> None:
    from clipfoundry.studio import video_flow

    video_flow.undo(project_id, _fresh(project_id)["plan_revision"])


def test_undo_puts_a_scenes_words_back_and_the_next_build_keeps_them(env):
    from clipfoundry.makers import shorts
    from clipfoundry.studio import video_flow

    project = _make(env)
    pid = project["id"]
    first, second = _scenes(pid, _plan(pid))[:2]
    new_words = "Two of them push blood through the gills."
    shorts.update_scene(_fresh(pid), second["id"], {"narration": new_words})
    _run(env)
    assert _words(pid, second["id"]) == new_words.split()

    _undo(pid)
    row = _scene(second["id"])
    assert row["narration"] == second["narration"] and row["clip_asset_id"] == second["clip_asset_id"]
    assert row["status"] == "ready" and _clip_of(pid, second["id"]) == second["clip_asset_id"]
    shown = next(x for x in shorts.view(_fresh(pid))["scenes"] if x["id"] == second["id"])
    assert shown["in_plan"] and shown["narration"] == second["narration"]  # the panel shows what the video shows

    video_flow.redo(pid, _fresh(pid)["plan_revision"])
    assert _scene(second["id"])["narration"] == new_words and _words(pid, second["id"]) == new_words.split()

    _undo(pid)
    spoken, moved = len(env["calls"].speak), len(env["calls"].clips)
    shorts.update_scene(_fresh(pid), first["id"], {"move": "pan_up"})  # another change: a new build
    _run(env)
    assert _clip_of(pid, second["id"]) == second["clip_asset_id"]  # the undone words stay undone
    assert _scene(second["id"])["narration"] == second["narration"]
    assert _scene(second["id"])["clip_key"] == second["clip_key"]
    assert len(env["calls"].speak) == spoken  # only the camera move of the first scene was made again
    assert len(env["calls"].clips) == moved + 1 and _scene(first["id"])["clip_key"] != first["clip_key"]


def test_undo_brings_a_deleted_scene_back_and_takes_an_added_one_away(env):
    from clipfoundry.makers import shorts
    from clipfoundry.studio import engine, video_flow

    project = _make(env)
    pid = project["id"]
    scenes = _scenes(pid, _plan(pid))
    gone = scenes[1]
    shorts.delete_scene(_fresh(pid), gone["id"])
    _run(env)
    assert gone["id"] not in [c.get("scene_id") for c in _plan(pid)["clips"]] and _scene(gone["id"]) is None

    _undo(pid)
    back = _scene(gone["id"])
    assert back is not None and back["narration"] == gone["narration"] and back["status"] == "ready"
    assert back["clip_asset_id"] == gone["clip_asset_id"] and back["picture_asset_id"] == gone["picture_asset_id"]
    assert [s["id"] for s in _scenes(pid, _plan(pid))] == [s["id"] for s in scenes]
    shorts.update_scene(_fresh(pid), scenes[0]["id"], {"move": "pan_up"})
    _run(env)
    assert _clip_of(pid, gone["id"]) == gone["clip_asset_id"]  # the next build keeps it in the video

    added = shorts.add_scene(_fresh(pid), scenes[0]["id"], "Octopuses can taste with their arms.")
    _run(env)
    assert added in [c.get("scene_id") for c in _plan(pid)["clips"]]
    _undo(pid)
    assert _scene(added) is None and added not in [c.get("scene_id") for c in _plan(pid)["clips"]]
    shorts.update_scene(_fresh(pid), scenes[0]["id"], {"move": "zoom_out"})
    _run(env)
    plan = _plan(pid)
    assert added not in [c.get("scene_id") for c in plan["clips"]]
    assert engine.validate(plan, video_flow._assets(_fresh(pid), plan)) == []


def test_undo_puts_the_shorts_choices_back_and_they_are_not_made_again(env):
    from clipfoundry.makers import shorts
    from clipfoundry.studio import library

    project = _make(env)
    pid = project["id"]
    before = _plan(pid)
    music_before = next(a for a in before["audio"] if a["role"] == "music")["asset_id"]
    short = _fresh(pid)["short"]
    rows = _scenes(pid, before)
    spoken = len(env["calls"].speak)
    shorts.set_options(_fresh(pid), {"voice": "espeak:en-gb", "captions": "clean", "music": "calm"})
    _run(env)
    changed = _plan(pid)
    assert changed["captions"]["style"] == "clean"
    assert len(env["calls"].speak) == spoken + len(rows)  # every scene was read by the new voice
    assert all(_scene(s["id"])["clip_key"] != s["clip_key"] for s in rows)

    _undo(pid)
    now = _fresh(pid)["short"]
    assert {k: now[k] for k in ("voice", "voice_used", "captions", "music")} == \
        {k: short[k] for k in ("voice", "voice_used", "captions", "music")}
    assert _fresh(pid)["guidance"]["values"]["music"] == short["music"]
    spoken = len(env["calls"].speak)
    first = _scenes(pid, _plan(pid))[0]
    shorts.update_scene(_fresh(pid), first["id"], {"move": "pan_down"})
    _run(env)
    plan = _plan(pid)
    assert len(env["calls"].speak) == spoken  # the voice was not changed again
    assert plan["captions"]["style"] == before["captions"]["style"]  # nor the captions
    assert next(a for a in plan["audio"] if a["role"] == "music")["asset_id"] == music_before  # nor the music
    assert library.MUSIC[library.music_key(short["music"], pid)]["title"] in \
        next(a for a in plan["audio"] if a["role"] == "music")["label"]
    assert [_scene(s["id"])["clip_key"] for s in rows[1:]] == [s["clip_key"] for s in rows[1:]]


def test_a_change_still_waiting_stays_through_undo_and_is_made_on_top(env):
    from clipfoundry.makers import shorts

    project = _make(env)
    pid = project["id"]
    a, b = _scenes(pid, _plan(pid))[:2]
    shorts.update_scene(_fresh(pid), a["id"], {"narration": "Octopus hearts: there are three of them."})
    _run(env)
    waiting = "The gills get two of the hearts."
    shorts.update_scene(_fresh(pid), b["id"], {"narration": waiting})  # its build has not run yet
    _undo(pid)  # undoes the change of scene a, which is in the video
    assert _scene(a["id"])["narration"] == a["narration"]
    assert _scene(b["id"])["narration"] == waiting and _scene(b["id"])["status"] == "waiting"
    _run(env)
    assert _clip_of(pid, a["id"]) == a["clip_asset_id"]
    assert _words(pid, b["id"]) == waiting.split()
    assert _fresh(pid)["short"]["stage"] == "ready"


def test_undo_while_a_build_waits_asks_for_a_new_build(env):
    from clipfoundry import db
    from clipfoundry.makers import shorts

    project = _make(env)
    pid = project["id"]
    a = _scenes(pid, _plan(pid))[0]
    shorts.update_scene(_fresh(pid), a["id"], {"narration": "Three hearts beat in every octopus."})
    _run(env)
    shorts.set_options(_fresh(pid), {"music": "energetic"})  # waits
    build = _fresh(pid)["short"]["build"]
    _undo(pid)
    assert _fresh(pid)["short"]["build"] == build + 1
    jobs = db.select("studio_jobs", "target_id = ? AND kind = 'short_build' AND status = 'queued'", (pid,))
    assert sorted(j["revision"] for j in jobs) == [build, build + 1]
    _run(env)
    assert _fresh(pid)["short"]["music"] == "energetic"  # the waiting choice stays and is made
    assert _scene(a["id"])["narration"] == a["narration"]


def test_going_back_to_the_first_version_puts_every_scene_back(env):
    from clipfoundry.makers import shorts
    from clipfoundry.studio import video_flow

    project = _make(env)
    pid = project["id"]
    scenes = _scenes(pid, _plan(pid))
    shorts.update_scene(_fresh(pid), scenes[0]["id"], {"narration": "Octopuses: three hearts, blue blood."})
    _run(env)
    shorts.delete_scene(_fresh(pid), scenes[-1]["id"])
    _run(env)
    added = shorts.add_scene(_fresh(pid), None, "Here is a strange fact.")
    _run(env)
    _edit(pid, {"op": "set", "field": "caption_position", "value": "top"})

    video_flow.restore(pid, 1)
    now = _scenes(pid, _plan(pid))
    assert [(s["id"], s["narration"], s["clip_asset_id"]) for s in now] == \
        [(s["id"], s["narration"], s["clip_asset_id"]) for s in scenes]
    assert _scene(added) is None
    shorts.update_scene(_fresh(pid), scenes[1]["id"], {"move": "still"})
    _run(env)
    assert [c.get("scene_id") for c in _plan(pid)["clips"]] == [s["id"] for s in scenes]


def test_saving_a_version_and_what_goes_with_it_is_one_step(env):
    from clipfoundry import db
    from clipfoundry.studio import video_flow

    project = _make(env)
    pid = project["id"]
    plan = _plan(pid)
    rev = _fresh(pid)["plan_revision"]

    def broken(conn, new_rev):
        conn.execute("UPDATE studio_projects SET name = 'changed' WHERE id = ?", (pid,))
        raise RuntimeError("stopped half way")

    with pytest.raises(RuntimeError):
        video_flow.save_revision(pid, plan, "test", rev, also=broken)
    assert _fresh(pid)["plan_revision"] == rev and _fresh(pid)["name"] != "changed"  # nothing was kept
    assert not db.select("edit_plans", "project_id = ? AND revision = ?", (pid, rev + 1))
    with pytest.raises(video_flow.Conflict):
        video_flow.save_revision(pid, plan, "test", rev - 1 if rev > 1 else rev + 5)
    seen = []
    new = video_flow.save_revision(pid, plan, "test", rev, also=lambda conn, r: seen.append(r))
    assert new == rev + 1 and seen == [rev + 1]


def test_versions_saved_before_scenes_were_kept_still_undo(env):
    from clipfoundry import db
    from clipfoundry.makers import shorts
    from clipfoundry.studio import video_flow

    project = _make(env)
    pid = project["id"]
    a = _scenes(pid, _plan(pid))[0]
    for row in db.select("edit_plans", "project_id = ?", (pid,)):  # as an older version of ClipForge saved them
        plan = row["plan"]
        plan["short"] = {k: v for k, v in plan["short"].items() if k in ("scenes", "applied")}
        db.execute("UPDATE edit_plans SET plan = ? WHERE project_id = ? AND revision = ?",
                   (__import__("json").dumps(plan), pid, row["revision"]))
    shorts.update_scene(_fresh(pid), a["id"], {"narration": "Three hearts, every one of them busy."})
    _run(env)
    video_flow.undo(pid, _fresh(pid)["plan_revision"])  # the scenes stay as they are; nothing breaks
    assert _scene(a["id"])["narration"] == "Three hearts, every one of them busy."

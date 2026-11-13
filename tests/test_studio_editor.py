"""The full-video editor after the rough cut (CF2-05 to CF2-08 plan side): any number of files and audio items,
files added later and inserted or swapped in, voiceover/music/effects tracks with gain, mute, fades, ducking and
clip attachment, caption word fixes, undo/redo/restore/named versions as new revisions, the frame-exact time map,
the block mixer and the disk-space check. Renders are covered by the slow suites (test_studio_video.py,
test_studio_editor_render.py); nothing here encodes media.
"""
from __future__ import annotations

import json

import pytest

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def _asset(tmp_path, n: int, kind: str, seconds: float = 10.0, workspace: str = "local", audio=True) -> dict:
    from clipfoundry import db

    ext = {"video": ".mp4", "image": ".png", "audio": ".m4a"}[kind]
    path = tmp_path / f"f{workspace}{n}{ext}"
    path.write_bytes(b"x")
    probe = {"duration": seconds if kind != "image" else 0, "has_audio": kind != "image" and audio}
    return db.insert("assets", {"id": f"as-{workspace}-{kind}-{n}", "workspace_id": workspace, "kind": kind,
                                "filename": path.name, "sha256": f"{workspace}{kind}{n}", "size": 1,
                                "path": str(path), "probe": probe})


def _project(tmp_path, assets: list[dict], brief: dict | None = None, words: dict | None = None) -> dict:
    """A project built exactly as the build job would, without listening to anything."""
    from clipfoundry import db
    from clipfoundry.studio import video_flow

    project = video_flow.create("local", "local", name="Trip", asset_ids=[a["id"] for a in assets],
                                brief=brief or {}, style_id="settings", remember={"enabled": False})
    plan = video_flow.rough_cut(project, video_flow._assets(project), words or {})
    video_flow.save_revision(project["id"], plan, "Rough cut from your brief", None,
                             {"action": "build", "prev": None, "redo": None})
    return db.fetch("studio_projects", project["id"])


def _plan(project_id: str) -> dict:
    from clipfoundry import db
    from clipfoundry.studio import video_flow

    return video_flow.plan_at(project_id, db.fetch("studio_projects", project_id)["plan_revision"])


def _edit(project_id: str, change: dict) -> dict:
    from clipfoundry import db
    from clipfoundry.studio import video_flow

    return video_flow.edit(project_id, db.fetch("studio_projects", project_id)["plan_revision"], change)


def test_older_plans_read_as_the_new_schema_without_rewriting_history(env):
    from clipfoundry import db
    from clipfoundry.studio import engine, video_flow

    v, m = _asset(env, 1, "video"), _asset(env, 2, "audio", 60)
    project = _project(env, [v])
    old = {"schema": 1, "timebase": 1000, "engine": "ffmpeg-v1", "output": {"aspect": "16:9", "fps": 30},
           "layout": "fit", "clips": [{"id": "c1", "asset_id": v["id"], "kind": "video", "in_ms": 0, "out_ms": 4000,
                                       "label": "a", "gain_db": 0.0, "include": True}],
           "transition": {"type": "cut", "ms": 0}, "title": {"enabled": False, "text": "", "ms": 2500},
           "captions": {"enabled": True, "style": "clean", "position": "bottom"},
           "music": {"asset_id": m["id"], "level_db": -20.0}, "outline": [], "notes": []}
    db.execute("INSERT INTO edit_plans (project_id, revision, plan, note, created_at) VALUES (?, 2, ?, 'old', 0)",
               (project["id"], json.dumps(old)))
    db.execute("UPDATE studio_projects SET plan_revision = 2 WHERE id = ?", (project["id"],))
    plan = video_flow.plan_at(project["id"], 2)
    assert plan["schema"] == engine.SCHEMA and "music" not in plan
    assert [(i["role"], i["asset_id"], i["gain_db"], i["loop"], i["duck"]) for i in plan["audio"]] == \
        [("music", m["id"], -20.0, True, True)]
    assert not engine.validate(plan, video_flow._assets(db.fetch("studio_projects", project["id"]), plan))
    stored = db.select("edit_plans", "project_id = ? AND revision = 2", (project["id"],))[0]["plan"]
    assert stored["schema"] == 1 and stored["music"]["level_db"] == -20.0  # history is never rewritten
    # a later edit saves the new schema; the music level control still works on the music track
    _edit(project["id"], {"op": "set", "field": "music_level_db", "value": -12})
    assert [i["gain_db"] for i in _plan(project["id"])["audio"]] == [-12.0]


def test_no_fixed_count_limit_on_files_clips_or_audio_items(env):
    """150 files and 400 audio items are accepted and validated; the time map stays frame-exact (no drift)."""
    from clipfoundry.studio import engine, video_flow

    files = [_asset(env, n, ("video", "image", "audio")[n % 3], 3.0 + (n % 7) * 0.37) for n in range(150)]
    project = _project(env, files)
    plan = _plan(project["id"])
    assert len(plan["clips"]) == 100 and len(project["asset_ids"]) == 150  # audio waits in the bin
    sounds = [a for a in files if a["kind"] == "audio"]
    p = plan
    assets = video_flow._assets(project, plan)
    for k in range(400):
        p, _ = video_flow.apply_edit(p, {"op": "add_audio", "asset_id": sounds[k % len(sounds)]["id"],
                                         "role": "effect", "start_ms": k * 731}, {}, assets)
    assert len(p["audio"]) == 400 and len({i["id"] for i in p["audio"]}) == 400
    p, _ = video_flow.apply_edit(p, {"op": "set", "field": "transition", "value": "dissolve"}, {}, assets)
    assert engine.validate(p, assets) == []
    for fps in engine.FPS:
        els, overlap = engine.frame_map(p, fps)
        assert els[-1]["end_f"] == round(engine.duration_ms(p) * fps / 1000)
        for e in els:  # every element within one frame of its ideal length: rounding never accumulates
            ideal = (e["ideal_end_ms"] - (e.get("out_start_ms") or 0)) * fps / 1000
            assert abs(e["frames"] - ideal) <= 1.0
        assert all(b["start_f"] == a["end_f"] - overlap for a, b in zip(els, els[1:]))
    placed = engine.audio_timeline(p)
    assert len(placed) == sum(1 for k in range(400) if k * 731 < engine.duration_ms(p) - 20)
    assert all(x["out_end_ms"] <= engine.duration_ms(p) for x in placed)


def test_files_added_after_the_rough_cut_are_inserted_or_swapped_in(env):
    from clipfoundry import db
    from clipfoundry.studio import video_flow

    a, b = _asset(env, 1, "video", 8), _asset(env, 2, "video", 6)
    project = _project(env, [a, b], words={a["id"]: [{"w": "hi", "start": 2.0, "end": 2.5},
                                                     {"w": "there.", "start": 2.6, "end": 3.2}]})
    later, still, voice = _asset(env, 3, "video", 12), _asset(env, 4, "image"), _asset(env, 5, "audio", 4)
    theirs = _asset(env, 6, "video", 5, workspace="other")
    with pytest.raises(video_flow.VideoError):
        video_flow.add_media(project["id"], [theirs["id"]])  # never another workspace's file
    with pytest.raises(video_flow.VideoError, match="media first"):
        _edit(project["id"], {"op": "insert", "asset_id": later["id"], "at": 1})
    out = video_flow.add_media(project["id"], [later["id"], still["id"], voice["id"], later["id"]])
    assert out["added"] == [later["id"], still["id"], voice["id"]]
    assert db.select("studio_jobs", "kind = 'video_media' AND target_id = ?", (project["id"],))
    before = _plan(project["id"])
    r = _edit(project["id"], {"op": "insert", "asset_id": later["id"], "at": 1})
    plan = _plan(project["id"])
    new = plan["clips"][1]
    assert new["asset_id"] == later["id"] and (new["in_ms"], new["out_ms"]) == (0, 12000)  # no words yet: whole file
    assert [c["id"] for c in plan["clips"] if c["id"] != new["id"]] == [c["id"] for c in before["clips"]]
    assert "position 2" in r["note"]
    with pytest.raises(video_flow.VideoError, match="audio track"):
        _edit(project["id"], {"op": "insert", "asset_id": voice["id"], "at": 0})
    first = plan["clips"][0]
    _edit(project["id"], {"op": "set", "clip_id": first["id"], "field": "gain_db", "value": -4})
    _edit(project["id"], {"op": "replace", "clip_id": first["id"], "asset_id": still["id"]})
    swapped = _plan(project["id"])["clips"][0]
    assert swapped["id"] == first["id"] and swapped["asset_id"] == still["id"] and swapped["kind"] == "image"
    assert swapped["out_ms"] - swapped["in_ms"] == first["out_ms"] - first["in_ms"]  # same place, same length
    assert swapped["gain_db"] == -4.0  # your clip settings stay
    assert db.fetch("assets", a["id"])  # the replaced original is never deleted


def test_audio_tracks_gain_mute_fades_ducking_and_clip_attachment(env):
    from clipfoundry.studio import engine, video_flow

    a, b = _asset(env, 1, "video", 8), _asset(env, 2, "video", 6)
    vo, music, fx = _asset(env, 3, "audio", 3), _asset(env, 4, "audio", 30), _asset(env, 5, "audio", 1)
    project = _project(env, [a, b, vo, music, fx], brief={"music": "supplied", "music_asset_id": music["id"],
                                                          "voiceover_asset_ids": [vo["id"]]})
    plan = _plan(project["id"])
    roles = {i["role"]: i for i in plan["audio"]}
    assert roles["music"]["loop"] and roles["music"]["duck"] and roles["music"]["gain_db"] == -18.0
    assert roles["voiceover"]["start_ms"] == 0 and not roles["voiceover"]["duck"]
    second = plan["clips"][1]
    _edit(project["id"], {"op": "add_audio", "asset_id": fx["id"], "role": "effect", "clip_id": second["id"],
                          "offset_ms": 250})
    fx_id = next(i["id"] for i in _plan(project["id"])["audio"] if i["asset_id"] == fx["id"])
    where = {x["audio_id"]: x for x in engine.audio_timeline(_plan(project["id"]))}
    assert where[fx_id]["out_start_ms"] == engine.timeline(_plan(project["id"]))[1]["out_start_ms"] + 250
    _edit(project["id"], {"op": "move", "clip_id": second["id"], "to": 0})  # the effect moves with its clip
    assert {x["audio_id"]: x for x in engine.audio_timeline(_plan(project["id"]))}[fx_id]["out_start_ms"] == 250
    with pytest.raises(video_flow.VideoError, match="never ducks"):
        _edit(project["id"], {"op": "audio_set", "audio_id": roles["voiceover"]["id"], "field": "duck",
                              "value": True})
    _edit(project["id"], {"op": "audio_set", "audio_id": roles["voiceover"]["id"], "field": "fade_out_ms",
                          "value": 500})
    with pytest.raises(video_flow.VideoError, match="fades"):
        _edit(project["id"], {"op": "audio_set", "audio_id": roles["voiceover"]["id"], "field": "fade_in_ms",
                              "value": 2900})  # 2.9 s + 0.5 s of fades in a 3 s voiceover
    _edit(project["id"], {"op": "audio_trim", "audio_id": roles["voiceover"]["id"], "in_ms": 500, "out_ms": 2500})
    _edit(project["id"], {"op": "audio_move", "audio_id": roles["voiceover"]["id"], "start_ms": 1200})
    _edit(project["id"], {"op": "track_set", "track": "music", "field": "gain_db", "value": -6})
    _edit(project["id"], {"op": "track_set", "track": "effects", "field": "mute", "value": True})
    _edit(project["id"], {"op": "audio_set", "audio_id": roles["music"]["id"], "field": "loop", "value": False})
    plan = _plan(project["id"])
    v = next(i for i in plan["audio"] if i["id"] == roles["voiceover"]["id"])
    assert (v["in_ms"], v["out_ms"], v["start_ms"], v["fade_out_ms"]) == (500, 2500, 1200, 500)
    assert plan["tracks"]["music"]["gain_db"] == -6.0 and plan["tracks"]["effects"]["mute"]
    m = next(i for i in plan["audio"] if i["id"] == roles["music"]["id"])
    assert not m["loop"] and m["out_ms"] == 30000
    with pytest.raises(video_flow.VideoError, match="out of range|between"):
        _edit(project["id"], {"op": "track_set", "track": "music", "field": "gain_db", "value": 40})
    _edit(project["id"], {"op": "audio_remove", "audio_id": fx_id})
    assert fx_id not in {i["id"] for i in _plan(project["id"])["audio"]}
    from clipfoundry import db

    assert fx["id"] in db.fetch("studio_projects", project["id"])["asset_ids"]  # the file stays in the media bin


def test_undo_redo_restore_and_named_versions_never_lose_work(env):
    from clipfoundry import db
    from clipfoundry.studio import video_flow

    a, b, c = (_asset(env, n, "video", 6) for n in (1, 2, 3))
    project = _project(env, [a, b, c])
    pid = project["id"]
    rough = _plan(pid)
    _edit(pid, {"op": "move", "clip_id": rough["clips"][0]["id"], "to": 2})
    moved = _plan(pid)
    _edit(pid, {"op": "remove", "clip_id": rough["clips"][1]["id"]})
    removed = _plan(pid)
    cur = lambda: db.fetch("studio_projects", pid)["plan_revision"]  # noqa: E731
    view = video_flow.view(db.fetch("studio_projects", pid))
    assert view["can_undo"] and not view["can_redo"]
    with pytest.raises(video_flow.Conflict):
        video_flow.undo(pid, cur() - 1)  # a stale tab is refused
    video_flow.undo(pid, cur())
    assert _plan(pid)["clips"] == moved["clips"]
    video_flow.undo(pid, cur())
    assert _plan(pid)["clips"] == rough["clips"]
    view = video_flow.view(db.fetch("studio_projects", pid))
    assert not view["can_undo"] and view["can_redo"]
    with pytest.raises(video_flow.VideoError, match="nothing to undo"):
        video_flow.undo(pid, cur())
    video_flow.redo(pid, cur())
    assert _plan(pid)["clips"] == moved["clips"]
    video_flow.redo(pid, cur())
    assert _plan(pid)["clips"] == removed["clips"]
    assert not video_flow.view(db.fetch("studio_projects", pid))["can_redo"]
    revisions_before = cur()
    assert revisions_before == 7  # rough, 2 edits, 2 undos, 2 redos: each a new revision, nothing overwritten
    video_flow.name_revision(pid, 2, "  Before   the cut ")
    video_flow.restore(pid, 2)
    view = video_flow.view(db.fetch("studio_projects", pid))
    assert _plan(pid)["clips"] == moved["clips"] and view["revisions"][0]["note"] == "Back to version 2 “Before the cut”"
    assert next(r for r in view["revisions"] if r["revision"] == 2)["name"] == "Before the cut"
    video_flow.undo(pid, cur())  # undo goes back to what you had before restoring
    assert _plan(pid)["clips"] == removed["clips"]
    # an edit after an undo starts a new branch: redo is gone, but every earlier revision is still readable
    video_flow.undo(pid, cur())
    _edit(pid, {"op": "set", "field": "captions", "value": False})
    assert not video_flow.view(db.fetch("studio_projects", pid))["can_redo"]
    assert [r["revision"] for r in db.select("edit_plans", "project_id = ?", (pid,), "revision")] == \
        list(range(1, cur() + 1))


def test_caption_word_fixes_change_the_text_and_keep_the_timing(env):
    from clipfoundry.studio import engine, video_flow

    a = _asset(env, 1, "video", 6)
    words = {a["id"]: [{"w": "Welcome", "start": 1.0, "end": 1.4}, {"w": "too", "start": 1.5, "end": 1.7},
                       {"w": "um", "start": 1.8, "end": 1.9}, {"w": "Banff.", "start": 2.0, "end": 2.6}]}
    project = _project(env, [a], words=words)
    plan, assets = _plan(project["id"]), video_flow._assets(project)
    plan, note = video_flow.apply_edit(plan, {"op": "fix_word", "asset_id": a["id"], "start_ms": 1500, "text": "to"},
                                       words, assets)
    assert "“too” to “to”" in note
    plan, _ = video_flow.apply_edit(plan, {"op": "fix_word", "asset_id": a["id"], "start_ms": 1800, "text": ""},
                                    words, assets)
    heard = engine.output_words(plan, words)
    assert [w["w"] for w in heard] == ["Welcome", "to", "Banff."]
    assert heard[1]["src_start"] == 1.5
    with pytest.raises(video_flow.VideoError, match="not in this file"):
        video_flow.apply_edit(plan, {"op": "fix_word", "asset_id": a["id"], "start_ms": 9999, "text": "x"}, words,
                              assets)


def test_block_mixer_crossfades_exactly_across_block_edges(env, monkeypatch):
    import numpy as np

    from clipfoundry.studio import engine

    monkeypatch.setattr(engine, "MIX_BLOCK", 1000)  # many block edges inside the overlap
    one = env / "one.raw"
    two = env / "two.raw"
    np.full((4000, 2), 0.5, dtype=np.float32).tofile(one)
    np.full((3000, 2), 0.5, dtype=np.float32).tofile(two)
    out = env / "bus.raw"
    engine.mix(6000, [{"start": 0, "n": 4000, "path": one, "ramp_out": 1000},
                      {"start": 3000, "n": 3000, "path": two, "ramp_in": 1000}], out)
    bus = np.fromfile(out, dtype=np.float32).reshape(-1, 2)
    assert bus.shape == (6000, 2)
    assert np.allclose(bus[:, 0], 0.5, atol=1e-6)  # the crossfade keeps a constant level through the join
    three = env / "three.raw"
    np.full((500, 2), 0.25, dtype=np.float32).tofile(three)
    engine.mix(6000, [{"start": 5800, "n": 500, "path": three}], out)  # an item past the end is cut, not wrapped
    bus = np.fromfile(out, dtype=np.float32).reshape(-1, 2)
    assert bus.shape == (6000, 2) and np.allclose(bus[5800:, 0], 0.25) and not bus[:5800].any()


def test_a_render_that_would_fill_the_disk_is_explained_before_it_starts(env, monkeypatch):
    import shutil
    from collections import namedtuple

    from clipfoundry.studio import engine

    a = _asset(env, 1, "video", 3600)
    project = _project(env, [a])
    plan = _plan(project["id"])
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: usage(10**12, 10**12 - 10**8, 10**8))
    out = env / "r" / "final.mp4"
    with pytest.raises(engine.RenderSpaceError, match="GB of free disk space"):
        engine.render(plan, {a["id"]: a}, {}, out)
    assert not out.exists() and not (env / "r" / "pieces").exists()


def test_editor_routes_undo_redo_name_and_media(env):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    a, b, extra = _asset(env, 1, "video", 6), _asset(env, 2, "video", 6), _asset(env, 3, "audio", 2)
    project = _project(env, [a, b])
    pid = project["id"]
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        v = api.get(f"/api/studio/videos/{pid}").json()
        assert v["can_undo"] is False and v["bin"] == [a["id"], b["id"]] and v["timeline"]
        r = api.post(f"/api/studio/videos/{pid}/edits", json={"base_revision": v["plan_revision"],
                                                              "edit": {"op": "set", "field": "caption_size",
                                                                       "value": "small"}})
        assert r.status_code == 200 and r.json()["plan"]["captions"]["size"] == "small"
        stale = api.post(f"/api/studio/videos/{pid}/undo", json={"base_revision": v["plan_revision"]})
        assert stale.status_code == 409
        undone = api.post(f"/api/studio/videos/{pid}/undo", json={"base_revision": r.json()["plan_revision"]})
        assert undone.status_code == 200 and undone.json()["plan"]["captions"]["size"] == "medium"
        redone = api.post(f"/api/studio/videos/{pid}/redo", json={"base_revision": undone.json()["plan_revision"]})
        assert redone.json()["plan"]["captions"]["size"] == "small"
        named = api.put(f"/api/studio/videos/{pid}/revisions/1/name", json={"name": "Rough cut"})
        assert named.status_code == 200 and named.json()["revisions"][-1]["name"] == "Rough cut"
        added = api.post(f"/api/studio/videos/{pid}/media", json={"asset_ids": [extra["id"]]})
        assert added.status_code == 200 and added.json()["bin"][-1] == extra["id"]
        bad = api.post(f"/api/studio/videos/{pid}/media", json={"asset_ids": ["as-nope"]})
        assert bad.status_code in (404, 422)
        exported = api.get(f"/api/studio/videos/{pid}/export").json()
        assert exported["format"] == "clipforge.edit-plan/v2"

"""Characters and places of an animated short (makers/cast.py), the owner's timing and transitions between scenes
(docs/clipforge/ANIMATED_SHORTS.md): every picture of a scene a character is in is drawn with the character's details
and reference pictures; a change to the character makes only those pictures again; a change for one shot stays on
that shot; locked details are never changed; a picture that lost a character's colours is flagged, with Looks right;
the library keeps reusable characters, and each short keeps its own copy.

The voice and motion are the stand-ins of tests/test_studio_shorts_flow.py; the picture maker is a fake that draws a
plain-coloured picture and records what it was asked."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from test_studio_shorts_flow import _fresh, _make, _plan, _run, _scenes, env  # noqa: F401

SCRIPT = ("Mia walked to the lighthouse in the rain.\n\nThe door was open, and a light was on.\n\n"
          "Inside, an old cat was waiting for her.")
MIA = {"kind": "character", "name": "Mia", "appearance": "a ten-year-old girl with curly red hair",
       "clothing": "a yellow raincoat and green boots", "colors": "yellow and green", "props": "a blue umbrella"}


class FakePictures:
    """The local picture maker: draws one colour, records each prompt and its reference pictures."""

    class EngineError(Exception):
        pass

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.asked: list[dict] = []
        self.colour = "yellow"
        self.model = "flux2-klein-4b"

    def status(self, role):
        return {"ready": role == "image", "engine": "Fake pictures", "why": "", "model": self.model}

    def make_image(self, prompt, **kw):
        self.asked.append({"prompt": prompt, "references": [str(r) for r in kw.get("references") or []],
                           "seed": kw.get("seed")})
        path = self.tmp / f"made-{len(self.asked)}.png"
        im = Image.new("RGB", (90, 160), "#2b4a8a")
        im.paste(Image.new("RGB", (40, 60), self.colour), (25, 60))
        im.save(path)
        path.with_suffix(".json").write_text(json.dumps({"references": len(kw.get("references") or [])}))
        return path


@pytest.fixture()
def drawn(env, monkeypatch):  # noqa: F811
    from clipfoundry.makers import local_engines, shorts

    fake = FakePictures(env["tmp"])
    monkeypatch.setattr(local_engines, "module", lambda: fake)
    monkeypatch.setattr(local_engines, "made_here", lambda path: False)
    monkeypatch.setattr(shorts, "_status_cache", {})
    return fake


def _picture_file(env, name: str, colour: str) -> dict:
    from clipfoundry.studio import uploads

    path = env["tmp"] / name
    Image.new("RGB", (300, 400), colour).save(path)
    return uploads.store_file("local", path, name)


def _prompts_for(fake: FakePictures, words: str) -> list[dict]:
    return [a for a in fake.asked if words in a["prompt"]]


def test_a_character_reaches_every_picture_with_its_reference_and_changes_only_its_shots(env, drawn):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.makers import cast, shorts

    project = _make(env, SCRIPT)
    before = {s["id"]: s["picture_key"] for s in _scenes(project["id"])}
    assert len(drawn.asked) == 3 and not any("Mia:" in a["prompt"] for a in drawn.asked)
    ref = _picture_file(env, "mia.png", "#ffcc00")
    member_id = shorts.cast_add(_fresh(project["id"]), {**MIA, "refs": [ref["id"]], "locked": ["appearance"]})
    lib = cast.library("local")
    assert [x["name"] for x in lib] == ["Mia"] and lib[0]["refs"][0]["asset_id"] == ref["id"]
    _run(env)
    drawn_with_mia = _prompts_for(drawn, "Mia: a ten-year-old girl with curly red hair; wearing a yellow raincoat")
    assert len(drawn_with_mia) == 3  # every scene: the cast is in every shot until the owner picks
    assert all(a["references"] == [str(Path(ref["path"]))] for a in drawn_with_mia)
    scenes = _scenes(project["id"])
    assert all(s["picture_key"] != before[s["id"]] for s in scenes)  # (the fake draws the same bytes)
    assert all(s["info"]["picture"]["references"] == 1 for s in scenes)
    # the owner takes Mia out of the second shot: only that picture is made again, without her
    second = scenes[1]
    n = len(drawn.asked)
    shorts.update_scene(_fresh(project["id"]), second["id"], {"cast": []})
    _run(env)
    assert len(drawn.asked) == n + 1 and "Mia" not in drawn.asked[-1]["prompt"]
    assert drawn.asked[-1]["references"] == []
    view = shorts.view(_fresh(project["id"]))
    assert [x["cast"] for x in view["scenes"]] == [[member_id], [], [member_id]]
    assert view["scenes"][1]["cast_chosen"] and not view["scenes"][0]["cast_chosen"]
    assert view["cast"][0]["library"] == "same" and view["cast"][0]["refs"] == [{"asset_id": ref["id"], "ok": True}]
    # a change for one shot stays on that shot; the locked look is never changed
    third = view["scenes"][2]
    n = len(drawn.asked)
    done = shorts.cast_apply(_fresh(project["id"]), member_id,
                             {"clothing": "a red raincoat", "appearance": "a tall woman"}, third["id"])
    assert done == {"changed": ["clothing"], "kept": ["appearance"]}
    _run(env)
    assert len(drawn.asked) == n + 1 and "wearing a red raincoat" in drawn.asked[-1]["prompt"]
    assert "curly red hair" in drawn.asked[-1]["prompt"]
    view = shorts.view(_fresh(project["id"]))
    assert view["scenes"][2]["overrides"] == {member_id: {"clothing": "a red raincoat"}}
    assert view["cast"][0]["clothing"] == MIA["clothing"]  # the other shots keep the yellow raincoat
    # a change for every shot changes the short's copy, so only the shots Mia is in are made again
    n = len(drawn.asked)
    shorts.cast_apply(_fresh(project["id"]), member_id, {"props": "a lantern"})
    _run(env)
    assert len(drawn.asked) == n + 2 and all("with a lantern" in a["prompt"] for a in drawn.asked[n:])
    view = shorts.view(_fresh(project["id"]))
    assert view["cast"][0]["props"] == "a lantern" and view["cast"][0]["library"] == "differs"
    assert cast.library("local")[0]["props"] == "a blue umbrella"  # the library keeps its own until saved
    shorts.cast_to_library(_fresh(project["id"]), member_id)
    assert cast.library("local")[0]["props"] == "a lantern"
    assert shorts.view(_fresh(project["id"]))["cast"][0]["library"] == "same"
    # the one-shot change can be taken back
    shorts.cast_clear_override(_fresh(project["id"]), third["id"], member_id)
    _run(env)
    assert "wearing a yellow raincoat" in drawn.asked[-1]["prompt"]
    # removing the character makes its pictures again without it and forgets it in the scenes
    shorts.cast_remove(_fresh(project["id"]), member_id)
    _run(env)
    assert all("Mia:" not in a["prompt"] for a in drawn.asked[-2:])
    assert all("cast" not in s["info"] or s["info"]["cast"] == [] for s in _scenes(project["id"]))
    assert db.fetch("cast_library", lib[0]["id"])  # the library keeps Mia for other shorts


def test_a_picture_that_lost_the_characters_colours_is_flagged_until_the_owner_says_it_looks_right(env, drawn):  # noqa: F811,E501
    from clipfoundry.makers import shorts

    drawn.colour = "#cc2222"  # the maker drew red, not Mia's yellow
    project = shorts.create("local", "local", name="", options={"mode": "paste", "script": SCRIPT})
    shorts.cast_add(_fresh(project["id"]), {**MIA, "locked": ["colors"]})
    _run(env)
    view = shorts.view(_fresh(project["id"]))
    flags = view["scenes"][0]["drift"]["flags"]
    assert view["scenes"][0]["drift"]["how"] == "colours" and not view["scenes"][0]["drift"]["ok"]
    assert [f["why"] for f in flags] == ["There is no yellow in this picture.", "There is no green in this picture."]
    assert flags[0]["name"] == "Mia" and flags[0]["detail"] == "yellow and green"
    sid = view["scenes"][0]["id"]
    shorts.update_scene(_fresh(project["id"]), sid, {"drift_ok": True})
    assert shorts.view(_fresh(project["id"]))["scenes"][0]["drift"]["ok"]
    # Make again draws it anew; a picture with her colours is not flagged
    drawn.colour = "yellow"
    shorts.update_scene(_fresh(project["id"]), sid, {"new_picture": True})
    _run(env)
    drift = shorts.view(_fresh(project["id"]))["scenes"][0]["drift"]
    assert [f["why"] for f in drift["flags"]] == ["There is no green in this picture."] and not drift["ok"]
    # the owner's own picture is never checked
    own = _picture_file(env, "own.png", "#123456")
    shorts.update_scene(_fresh(project["id"]), sid, {"picture_asset_id": own["id"]})
    _run(env)
    assert shorts.view(_fresh(project["id"]))["scenes"][0]["drift"] is None


def test_the_look_check_asks_the_built_in_model_when_it_is_there(tmp_path):
    from clipfoundry.makers import cast

    path = tmp_path / "p.png"
    Image.new("RGB", (90, 160), "yellow").save(path)
    mia = {"id": "cm-1", **MIA}
    asked = {}

    def complete(settings, prompt, **kw):
        asked.update(prompt=prompt, images=kw.get("images"))
        return json.dumps({"checks": [{"name": "Mia", "matches": False, "differs": ["short black hair"]}]})

    got = cast.check(path, [mia], {}, complete=complete)
    assert got["how"] == "looked" and "Mia: a ten-year-old girl" in asked["prompt"]
    assert asked["images"][0].startswith("data:image/jpeg;base64,")
    assert got["flags"][-1] == {"member": "cm-1", "name": "Mia", "detail": "short black hair",
                                "why": "ClipForge AI says this does not look like the description."}
    assert [f["why"] for f in got["flags"][:-1]] == ["There is no green in this picture."]


def test_a_change_in_the_owners_words_is_proposed_and_never_touches_locked_details(env, monkeypatch):  # noqa: F811
    from clipfoundry.makers import cast

    mia = {"id": "cm-1", **MIA, "locked": ["clothing"]}
    seen = {}

    def complete(settings, prompt, **kw):
        seen["prompt"] = prompt
        return json.dumps({"clothing": "a purple coat", "props": "a blue umbrella and a lantern",
                           "note": "Gave her a lantern."})

    got = cast.propose(mia, "give her a lantern and a purple coat", {}, complete=complete)
    assert got["changes"] == {"props": "a blue umbrella and a lantern"} and got["kept"] == ["clothing"]
    assert got["note"] == "Gave her a lantern. Locked, so not changed: clothes."
    assert "- clothing (locked): a yellow raincoat" in seen["prompt"] and "<<<give her a lantern" in seen["prompt"]
    with pytest.raises(cast.CastError, match="Say what"):
        cast.propose(mia, "  ", {}, complete=complete)
    with pytest.raises(cast.CastError, match="needs ClipForge AI"):
        cast.propose(mia, "taller", {"ai_provider": "heuristic"})
    with pytest.raises(cast.CastError, match="could not be read"):
        cast.propose(mia, "taller", {}, complete=lambda *a, **k: "no json here")


def test_details_are_checked_and_long_casts_fit_the_picture_idea(env):  # noqa: F811
    from clipfoundry.makers import cast

    with pytest.raises(cast.CastError, match="name"):
        cast.clean({"kind": "character"}, "local")
    with pytest.raises(cast.CastError, match="character or a place"):
        cast.clean({"kind": "robot", "name": "x"}, "local")
    with pytest.raises(cast.CastError, match="300"):
        cast.clean({"name": "x", "appearance": "y" * 301}, "local")
    with pytest.raises(cast.CastError, match="Lock one"):
        cast.clean({"name": "x", "locked": ["hair"]}, "local")
    with pytest.raises(cast.CastError, match="your pictures") as exc:
        cast.clean({"name": "x", "refs": ["as-nope"]}, "local")
    assert exc.value.status == 404
    place = cast.clean({"kind": "place", "name": "Old lighthouse", "appearance": "white with a red top",
                        "clothing": "ignored", "props": "gulls"}, "local")
    assert place["clothing"] == "" and cast.describe(place) == \
        "the setting is Old lighthouse: white with a red top; with gulls there"
    locked_last = {**MIA, "locked": ["props"]}
    assert cast.describe(locked_last).startswith("Mia: with a blue umbrella; a ten-year-old girl")
    big = {"cast": [{"id": f"cm-{k}", "kind": "character", "name": f"N{k}", "appearance": "word " * 55}
                    for k in range(6)]}
    text = cast.prompt_text(big, {"info": {}})
    assert len(text) <= cast.MAX_PROMPT + 6 and text.count("N") >= 6
    assert cast.prompt_text({"cast": []}, {"info": {}}) == ""
    assert cast.colour_words("Navy boots, GOLDEN hair, grey-green scarf") == ["blue", "gold", "grey", "green"]


def test_the_owners_timing_and_transitions_reach_the_plan(env):  # noqa: F811
    from clipfoundry.makers import shorts
    from clipfoundry.studio import engine, video_flow

    project = _make(env, SCRIPT)
    first = _scenes(project["id"])[0]
    voiced = first["info"]["voice"]["duration_ms"]
    clip_before = first["clip_asset_id"]
    shorts.update_scene(_fresh(project["id"]), first["id"], {"hold_ms": 2000})
    _run(env)
    plan = _plan(project["id"])
    first = _scenes(project["id"], plan)[0]
    assert first["clip_asset_id"] != clip_before and first["duration_ms"] >= voiced + shorts.END_MS + 2000 - 40
    assert plan["clips"][0]["out_ms"] == voiced + shorts.TAIL_MS + 2000
    assert shorts.view(_fresh(project["id"]))["scenes"][0]["hold_ms"] == 2000
    with pytest.raises(shorts.ShortError, match="stays after its words"):
        shorts.update_scene(_fresh(project["id"]), first["id"], {"hold_ms": 1234})
    clips = [c["asset_id"] for c in plan["clips"]]
    shorts.set_options(_fresh(project["id"]), {"transition": "dissolve"})
    _run(env)
    plan = _plan(project["id"])
    assert plan["transition"]["type"] == "dissolve" and 120 <= plan["transition"]["ms"] <= shorts.TRANSITION_MS
    assert [c["asset_id"] for c in plan["clips"]] == clips  # nothing was made again
    project = _fresh(project["id"])
    assert engine.validate(plan, video_flow._assets(project, plan)) == []
    with pytest.raises(shorts.ShortError, match="cut, a dissolve or a fade"):
        shorts.set_options(project, {"transition": "spin"})
    options = shorts.options()
    assert [t["id"] for t in options["transitions"]] == ["cut", "dissolve", "fade"]
    assert options["holds_ms"] == [0, 500, 1000, 2000, 3000] and options["cast"]["max_cast"] == 6


def test_the_api_keeps_a_library_and_a_shorts_cast(env, drawn):  # noqa: F811
    from fastapi.testclient import TestClient

    from clipfoundry.api import app
    from clipfoundry.makers import shorts
    from clipfoundry.studio import project_delete

    ref = _picture_file(env, "ref.png", "#ffcc00")
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        h = {"X-ClipFoundry": "1"}
        r = api.post("/api/studio/cast", json={"name": "Rex", "appearance": "a small brown dog", "refs": [ref["id"]]},
                     headers=h)
        assert r.status_code == 200, r.text
        rex = r.json()
        assert rex["id"].startswith("chr-") and rex["library_id"] == rex["id"]
        assert api.post("/api/studio/cast", json={"name": ""}, headers=h).status_code == 422
        assert api.post("/api/studio/cast", json={"name": "X", "refs": ["as-nope"]}, headers=h).status_code == 404
        r = api.patch(f"/api/studio/cast/{rex['id']}", json={"colors": "brown and white"}, headers=h)
        assert r.status_code == 200 and r.json()["colors"] == "brown and white"
        assert [x["name"] for x in api.get("/api/studio/cast", headers=h).json()["library"]] == ["Rex"]
        # the library's reference pictures are kept when a project that also has the file is deleted
        assert ref["id"] in project_delete.named_elsewhere("local", "full_video", "vid-x")
        video = api.post("/api/studio/shorts", json={"mode": "paste", "script": SCRIPT}, headers=h).json()
        _run(env)
        r = api.post(f"/api/studio/shorts/{video['id']}/cast", json={"library_id": rex["id"]}, headers=h)
        assert r.status_code == 200 and r.json()["short"]["cast"][0]["name"] == "Rex"
        member = r.json()["short"]["cast"][0]
        assert api.post(f"/api/studio/shorts/{video['id']}/cast", json={"library_id": rex["id"]},
                        headers=h).status_code == 409
        r = api.post(f"/api/studio/shorts/{video['id']}/cast/{member['id']}/propose", json={"words": "make him big"},
                     headers=h)
        assert r.status_code == 422 and "needs ClipForge AI" in r.json()["detail"]
        r = api.post(f"/api/studio/shorts/{video['id']}/cast/{member['id']}/apply",
                     json={"changes": {"appearance": "a big brown dog"}}, headers=h)
        assert r.status_code == 200 and r.json()["applied"] == {"changed": ["appearance"], "kept": []}
        _run(env)
        scene = shorts.view(_fresh(video["id"]))["scenes"][0]
        r = api.post(f"/api/studio/shorts/{video['id']}/cast/{member['id']}/reference",
                     json={"scene_id": scene["id"]}, headers=h)
        assert r.status_code == 200
        refs = r.json()["short"]["cast"][0]["refs"]
        assert [x["asset_id"] for x in refs] == [ref["id"], scene["picture_asset_id"]]
        r = api.patch(f"/api/studio/shorts/{video['id']}/scenes/{scene['id']}", json={"all_cast": True}, headers=h)
        assert r.status_code == 200
        assert api.delete(f"/api/studio/shorts/{video['id']}/cast/cm-nope", headers=h).status_code == 404
        r = api.delete(f"/api/studio/shorts/{video['id']}/cast/{member['id']}", headers=h)
        assert r.status_code == 200 and r.json()["short"]["cast"] == []
        assert api.delete(f"/api/studio/cast/{rex['id']}", headers=h).json() == {"deleted": True}
        assert api.delete(f"/api/studio/cast/{rex['id']}", headers=h).status_code == 404
        _run(env)


# ------------------------------------------------------------------ batch 4 review fixes (findings 20-24)
def test_who_is_in_the_shot_sent_with_another_change_never_enters_the_picture_history(env, drawn):  # noqa: F811
    """Finding 20: a scene PATCH with `cast` and narration keeps the scene's pictures a list of pictures."""
    from clipfoundry.makers import shorts

    project = _make(env, SCRIPT)
    member_id = shorts.cast_add(_fresh(project["id"]), dict(MIA))
    _run(env)
    first = _scenes(project["id"])[0]
    shorts.update_scene(_fresh(project["id"]), first["id"], {"cast": [member_id], "narration": "Mia ran home."})
    _run(env)
    row = next(s for s in _scenes(project["id"]) if s["id"] == first["id"])
    assert all(isinstance(p, dict) for p in row.get("pictures") or [])
    view = shorts.view(_fresh(project["id"]))  # the editor page opens
    assert view["scenes"][0]["cast"] == [member_id] and view["scenes"][0]["cast_chosen"]
    # an owner's picture sent with `cast` is recorded in the history
    pic = _picture_file(env, "own.png", "#336699")
    shorts.update_scene(_fresh(project["id"]), first["id"], {"cast": [], "picture_asset_id": pic["id"]})
    row = next(s for s in _scenes(project["id"]) if s["id"] == first["id"])
    assert any(p.get("asset_id") == pic["id"] for p in row["pictures"])


def test_a_one_shot_change_back_to_the_usual_look_clears_that_shots_change(env, drawn):  # noqa: F811
    """Finding 21: for one shot the changes are compared with the member as that shot shows it."""
    from clipfoundry.makers import shorts

    project = _make(env, SCRIPT)
    member_id = shorts.cast_add(_fresh(project["id"]), dict(MIA))
    _run(env)
    third = _scenes(project["id"])[2]
    shorts.cast_apply(_fresh(project["id"]), member_id, {"clothing": "a red raincoat"}, third["id"])
    _run(env)
    assert shorts.view(_fresh(project["id"]))["scenes"][2]["overrides"] == {member_id: {"clothing": "a red raincoat"}}
    n = len(drawn.asked)
    done = shorts.cast_apply(_fresh(project["id"]), member_id, {"clothing": MIA["clothing"]}, third["id"])
    assert done == {"changed": ["clothing"], "kept": []}
    _run(env)
    assert shorts.view(_fresh(project["id"]))["scenes"][2]["overrides"] == {}
    assert len(drawn.asked) == n + 1 and "wearing a yellow raincoat" in drawn.asked[-1]["prompt"]
    # the same again changes nothing, and says so
    assert shorts.cast_apply(_fresh(project["id"]), member_id, {"clothing": MIA["clothing"]}, third["id"]) == \
        {"changed": [], "kept": []}


def test_a_dissolve_is_fitted_again_when_a_scene_gets_shorter(env):  # noqa: F811
    """Finding 22: shortening a scene's words after a dissolve was chosen never fails the build."""
    from clipfoundry.makers import shorts
    from clipfoundry.studio import engine, video_flow

    project = _make(env, SCRIPT)
    shorts.set_options(_fresh(project["id"]), {"transition": "dissolve"})
    _run(env)
    assert _plan(project["id"])["transition"] == {"type": "dissolve", "ms": shorts.TRANSITION_MS}
    first = _scenes(project["id"])[0]
    shorts.update_scene(_fresh(project["id"]), first["id"], {"narration": "Rain."})  # about 0.55 s on screen
    jobs = _run(env)
    assert jobs and all(j["status"] == "done" for j in jobs), [j["error"] for j in jobs]
    project = _fresh(project["id"])
    plan = _plan(project["id"])
    shortest = min(c["out_ms"] - c["in_ms"] for c in plan["clips"])
    assert plan["transition"]["type"] in ("dissolve", "cut") and plan["transition"]["ms"] * 2 < shortest
    assert project["short"].get("stage") != "failed"
    assert engine.validate(plan, video_flow._assets(project, plan)) == []  # noqa: SLF001


def test_a_good_reference_picture_can_be_removed_while_another_is_missing(env):  # noqa: F811
    """Finding 24: only reference pictures new to the member are checked."""
    from clipfoundry.makers import cast

    a = _picture_file(env, "a.png", "#ffcc00")
    b = _picture_file(env, "b.png", "#00ccff")
    rex = cast.library_add("local", {"name": "Rex", "appearance": "a small brown dog", "refs": [a["id"], b["id"]]})
    Path(b["path"]).unlink()  # B is missing now (the page shows it as Missing)
    got = cast.library_change("local", rex["id"], {"refs": [b["id"]]})  # remove A
    assert [r["asset_id"] for r in got["refs"]] == [b["id"]] and got["refs"][0]["ok"] is False
    with pytest.raises(cast.CastError):  # a missing picture cannot be added anew
        cast.library_change("local", rex["id"], {"refs": [b["id"], "as-nope"]})


def test_the_library_list_can_delete_a_character(env):  # noqa: F811
    """Finding 23: the page's library list offers Delete (the privacy page promises it)."""
    page = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "ShortCast.tsx").read_text()
    assert "shorts.libraryDelete(" in page and "from your library" in page


def _voice_lengths(monkeypatch, lengths: dict[str, float]) -> None:
    """The stand-in voice reads these narrations (by their first words) for exactly these many seconds."""
    import sys

    from test_studio_shorts_flow import _tone

    voice = sys.modules["clipfoundry.makers.voice"]
    real = voice.speak

    def speak(text, out, **kw):
        got = real(text, out, **kw)
        seconds = next((s for start, s in lengths.items() if text.startswith(start)), None)
        if seconds is not None:
            _tone(Path(out), seconds)
            got["duration_s"] = seconds
        return got

    monkeypatch.setattr(voice, "speak", speak)


def test_a_dissolve_is_fitted_on_the_whole_frames_the_editor_counts(env, monkeypatch):  # noqa: F811
    """Second review of finding 22: a scene a little over twice the dissolve in milliseconds can still be a frame
    short of it on whole frames; the editor refuses that, so the short is fitted with the editor's own check."""
    from clipfoundry.makers import shorts
    from clipfoundry.studio import engine, video_flow

    # the first scene ends at 2650 ms (frame 79.5) and the second runs 645 ms: 19 frames for 10 + 10 of dissolve
    _voice_lengths(monkeypatch, {"Mia walked": 2.4, "Rain falls": 0.395})
    project = _make(env, SCRIPT)
    shorts.set_options(_fresh(project["id"]), {"transition": "dissolve"})
    _run(env)
    assert _plan(project["id"])["transition"] == {"type": "dissolve", "ms": shorts.TRANSITION_MS}
    second = _scenes(project["id"])[1]
    shorts.update_scene(_fresh(project["id"]), second["id"], {"narration": "Rain falls."})
    jobs = _run(env)
    assert jobs and all(j["status"] == "done" for j in jobs), [j["error"] for j in jobs]
    project = _fresh(project["id"])
    plan = _plan(project["id"])
    assert [c["out_ms"] - c["in_ms"] for c in plan["clips"]][:2] == [2650, 645]
    assert plan["transition"]["type"] == "dissolve" and plan["transition"]["ms"] < shorts.TRANSITION_MS
    assert not engine.transition_too_long(plan)
    assert engine.validate(plan, video_flow._assets(project, plan)) == []  # noqa: SLF001


def test_a_dissolve_turned_into_a_cut_for_a_very_short_scene_comes_back_when_the_scene_grows(env, monkeypatch):  # noqa: F811,E501
    """Second review of finding 22: the cut ClipForge made to fit a very short scene is not kept for good."""
    from clipfoundry.makers import shorts

    _voice_lengths(monkeypatch, {"Rain.": 0.08})
    project = _make(env, SCRIPT)
    shorts.set_options(_fresh(project["id"]), {"transition": "dissolve"})
    _run(env)
    second = _scenes(project["id"])[1]
    shorts.update_scene(_fresh(project["id"]), second["id"], {"narration": "Rain."})
    _run(env)
    assert _plan(project["id"])["transition"] == {"type": "cut", "ms": 0}
    assert _fresh(project["id"])["short"]["transition"] == "dissolve"  # still the owner's choice
    shorts.update_scene(_fresh(project["id"]), second["id"], {"narration": "The door was open, and a light was on."})
    jobs = _run(env)
    assert jobs and all(j["status"] == "done" for j in jobs), [j["error"] for j in jobs]
    assert _plan(project["id"])["transition"] == {"type": "dissolve", "ms": shorts.TRANSITION_MS}


def test_apply_to_every_shot_reaches_a_shot_with_its_own_words(env, drawn):  # noqa: F811
    """Second review of finding 21: a proposal made from one shot that brings the usual look back, applied to every
    shot, changes that shot too (it no longer keeps its own words for that detail), and says so."""
    from clipfoundry.makers import shorts

    project = _make(env, SCRIPT)
    shorts.cast_add(_fresh(project["id"]), dict(MIA))
    _run(env)
    member_id = _fresh(project["id"])["short"]["cast"][0]["id"]
    third = _scenes(project["id"])[2]
    shorts.cast_apply(_fresh(project["id"]), member_id, {"clothing": "a red raincoat"}, third["id"])
    _run(env)
    n = len(drawn.asked)
    done = shorts.cast_apply(_fresh(project["id"]), member_id, {"clothing": MIA["clothing"]})
    assert done == {"changed": ["clothing"], "kept": []}
    _run(env)
    view = shorts.view(_fresh(project["id"]))
    assert view["scenes"][2]["overrides"] == {} and view["cast"][0]["clothing"] == MIA["clothing"]
    assert len(drawn.asked) == n + 1 and "wearing a yellow raincoat" in drawn.asked[-1]["prompt"]
    # now every shot shows it: the same again changes nothing, and says so
    assert shorts.cast_apply(_fresh(project["id"]), member_id, {"clothing": MIA["clothing"]}) == \
        {"changed": [], "kept": []}


def test_deleting_a_library_entry_deletes_its_reference_pictures_nothing_else_uses(env, drawn):  # noqa: F811
    """Second review of finding 23: a reference picture kept only by the library goes with the library entry; one a
    short or another entry still uses stays."""
    from pathlib import Path as P

    from clipfoundry import db
    from clipfoundry.makers import cast

    only = _picture_file(env, "only-library.png", "#ff0000")
    shared = _picture_file(env, "shared.png", "#00ff00")
    used = _picture_file(env, "in-a-short.png", "#0000ff")
    gone = cast.library_add("local", {"kind": "character", "name": "Ortiz", "appearance": "a sailor",
                                      "refs": [only["id"], shared["id"], used["id"]]})
    cast.library_add("local", {"kind": "character", "name": "Ana", "appearance": "a pilot", "refs": [shared["id"]]})
    from clipfoundry.makers import shorts

    project = _make(env, SCRIPT)
    shorts.cast_add(_fresh(project["id"]), {**MIA, "refs": [used["id"]]})
    files = {a["id"]: P(db.fetch("assets", a["id"])["path"]) for a in (only, shared, used)}
    assert all(f.is_file() for f in files.values())
    assert cast.library_delete("local", gone["library_id"]) == [only["id"]]
    assert db.fetch("assets", only["id"]) is None and not files[only["id"]].exists()
    assert db.fetch("assets", shared["id"]) and files[shared["id"]].is_file()
    assert db.fetch("assets", used["id"]) and files[used["id"]].is_file()
    assert all(str(f).startswith(str(env["tmp"])) for f in files.values())  # only this test's own folder


def test_a_library_delete_at_the_moment_a_short_takes_the_character_keeps_its_pictures(env, drawn, monkeypatch):  # noqa: F811,E501
    """Third look at finding 23: From my library and Delete at the same moment; the short gets the pictures."""
    from pathlib import Path as P

    from clipfoundry import db
    from clipfoundry.makers import cast, shorts

    ref = _picture_file(env, "ortiz.png", "#ffcc00")
    entry = cast.library_add("local", {"kind": "character", "name": "Ortiz", "appearance": "a sailor",
                                       "refs": [ref["id"]]})
    project = _make(env, SCRIPT)
    real = shorts._set_cast

    def deleted_meanwhile(project, new, waiting="Waiting to make the pictures again"):
        cast.library_delete("local", entry["library_id"])  # lands after the short read the entry
        real(project, new, waiting)

    monkeypatch.setattr(shorts, "_set_cast", deleted_meanwhile)
    shorts.cast_add(_fresh(project["id"]), {"library_id": entry["library_id"]})
    member = _fresh(project["id"])["short"]["cast"][0]
    assert member["refs"] == [ref["id"]] and db.fetch("assets", ref["id"])
    assert P(db.fetch("assets", ref["id"])["path"]).is_file() and str(env["tmp"]) in db.fetch("assets", ref["id"])["path"]


def test_cuts_the_owner_asks_for_stay_cuts_when_the_scene_grows(env, monkeypatch):  # noqa: F811
    """Third look at finding 22: once the owner sets the transition in the editor, the fitted dissolve is not asked
    for again."""
    from clipfoundry.makers import shorts
    from clipfoundry.studio import video_flow

    _voice_lengths(monkeypatch, {"Rain.": 0.08})
    project = _make(env, SCRIPT)
    shorts.set_options(_fresh(project["id"]), {"transition": "dissolve"})
    _run(env)
    second = _scenes(project["id"])[1]
    shorts.update_scene(_fresh(project["id"]), second["id"], {"narration": "Rain."})
    _run(env)
    assert _plan(project["id"])["short"]["fitted"]["to"] == {"type": "cut", "ms": 0}
    video_flow.edit(project["id"], _fresh(project["id"])["plan_revision"],
                    {"op": "set", "field": "transition", "value": "cut"})
    assert "fitted" not in _plan(project["id"])["short"]
    shorts.update_scene(_fresh(project["id"]), second["id"], {"narration": "The door was open, and a light was on."})
    _run(env)
    assert _plan(project["id"])["transition"] == {"type": "cut", "ms": 0}


def test_without_characters_the_main_character_keeps_the_look_of_the_first_picture(env, drawn):  # noqa: F811
    """A short ClipForge AI described a main character for, with no characters added: every later picture is drawn
    with the first one, so the character looks the same; a picture an earlier look or character drew is never used."""
    from clipfoundry import db
    from clipfoundry.makers import shorts

    project = _make(env, SCRIPT)
    assert all(a["references"] == [] for a in drawn.asked)   # no main character described: nothing to keep
    shorts._rebuild(_fresh(project["id"]), {"character": "a small fox in a red scarf"})
    n = len(drawn.asked)
    _run(env)
    made = drawn.asked[n:]
    scenes = _scenes(project["id"])
    first = db.fetch("assets", scenes[0]["picture_asset_id"])
    assert len(made) == 3 and made[0]["references"] == []   # the old pictures were of no main character
    assert [a["references"] for a in made[1:]] == [[str(Path(first["path"]))]] * 2
    view = shorts.view(_fresh(project["id"]))
    assert [s["picture"]["kept_from"] for s in view["scenes"]] == [0, 1, 1]
    # once characters are added, their own reference pictures (or their words) are used instead
    shorts.cast_add(_fresh(project["id"]), {**MIA})
    n = len(drawn.asked)
    _run(env)
    assert len(drawn.asked) == n + 3 and all(a["references"] == [] for a in drawn.asked[n:])
    assert [s["picture"]["kept_from"] for s in shorts.view(_fresh(project["id"]))["scenes"]] == [0, 0, 0]


def test_a_words_only_picture_maker_draws_the_main_character_from_its_description(env, drawn, monkeypatch):  # noqa: F811
    from clipfoundry.makers import shorts

    drawn.model = "z-image-turbo"
    project = _make(env, SCRIPT)
    shorts._rebuild(_fresh(project["id"]), {"character": "a small fox in a red scarf"})
    n = len(drawn.asked)
    _run(env)
    assert len(drawn.asked) == n + 3 and all(a["references"] == [] for a in drawn.asked[n:])
    assert all("fox in a red scarf" in a["prompt"] for a in drawn.asked[n:])

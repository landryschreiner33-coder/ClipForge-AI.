"""Finishing a ClipForge video in FilmCraft (or any editor that reads OpenTimelineIO): the timeline is frame-exact
against the FFmpeg engine's own frame map, joins become centred OTIO transitions, the clips' sound, voiceover, music
(looped) and overlapping effects land on their own tracks, pictures over the video on V2, chapters as markers,
captions as SRT on the same output timeline, FilmCraft's sequence settings and clip volume in metadata.filmcraft, a
README naming what does not carry over, and a portable .zip with the media. Opening in FilmCraft is tested with
stand-in programs (a fake app and command-line tool that record what they were given); the real FilmCraft is
checked on GitHub's Mac and Linux machines by .github/workflows/filmcraft-check.yml (scripts/filmcraft_check.py).
"""
from __future__ import annotations

import json
import os
import stat
import sys
import time
import zipfile
from pathlib import Path

import pytest

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("CLIPFOUNDRY_FILMCRAFT", raising=False)
    monkeypatch.delenv("CLIPFOUNDRY_FILMCRAFT_CLI", raising=False)
    from clipfoundry import db
    from clipfoundry.jobs import worker

    db.init()
    monkeypatch.setattr(worker, "submit_studio", lambda job_id: None)
    return tmp_path


def _asset(tmp_path, name: str, kind: str, seconds: float = 30.0, audio: bool = True) -> dict:
    from clipfoundry import db

    folder = tmp_path / "files" / name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"x")
    probe = {"duration": seconds if kind != "image" else 0, "has_audio": kind != "image" and audio,
             "width": 1920, "height": 1080}
    return db.insert("assets", {"id": f"as-{Path(name).stem.replace(' ', '-')}", "workspace_id": "local",
                                "kind": kind, "filename": name, "sha256": f"sha-{name}", "size": 1, "path": str(path),
                                "probe": probe})


def _words(start: float, text: str) -> list[dict]:
    return [{"start": round(start + 0.4 * i, 3), "end": round(start + 0.4 * i + 0.3, 3), "w": w}
            for i, w in enumerate(text.split())]


def _video(env, *, aspect="9:16", fps=30, transition=("dissolve", 500), title=True, captions=True) -> dict:
    """A project with two talking clips (the second trimmed), an image, a title card, a picture over the first
    clip, a voiceover, a looping music bed and two sound effects that overlap, saved as version 1."""
    from clipfoundry import db
    from clipfoundry.studio import video_flow

    a = _asset(env, "talk one.mp4", "video", 20)
    b = _asset(env, "talk two.mp4", "video", 30)
    pic = _asset(env, "lake.png", "image")
    vo = _asset(env, "voice.m4a", "audio", 6)
    music = _asset(env, "bed.m4a", "audio", 7.3)
    fx1, fx2 = _asset(env, "whoosh.wav", "audio", 1.5), _asset(env, "ding.wav", "audio", 1.0)
    for v, text, at in ((a, "Hello and welcome to the lake today.", 1.0), (b, "Now we swim out to the island.", 3.0)):
        (Path(v["path"]).parent / "transcript.json").write_text(json.dumps({"segments": [{"words": _words(at, text)}]}))
    project = video_flow.create("local", "local", name="Lake day: part 1/2", asset_ids=[a["id"], pic["id"], b["id"]],
                                brief={}, style_id="settings", remember={"enabled": False})
    plan = video_flow.rough_cut(project, video_flow._assets(project), {})
    plan["output"] = {"aspect": aspect, "fps": fps}
    plan["layout"] = "fit"
    plan["clips"] = [
        {"id": "c1", "asset_id": a["id"], "kind": "video", "in_ms": 500, "out_ms": 6200, "label": "Welcome",
         "gain_db": -3.0, "include": True, "fade_in_ms": 200},
        {"id": "c2", "asset_id": pic["id"], "kind": "image", "in_ms": 0, "out_ms": 3000, "label": "Lake",
         "include": True},
        {"id": "c3", "asset_id": b["id"], "kind": "video", "in_ms": 2333, "out_ms": 9871, "label": "Swim",
         "include": True, "zoom": 1.2, "layout": "fill"},
        {"id": "c4", "asset_id": b["id"], "kind": "video", "in_ms": 12000, "out_ms": 15000, "label": "Left out",
         "include": False},
        {"id": "c5", "asset_id": b["id"], "kind": "video", "in_ms": 16000, "out_ms": 19500, "label": "Island",
         "include": True, "join": "cut", "mute": True},
    ]
    plan["transition"] = {"type": transition[0], "ms": transition[1]}
    plan["title"] = {"enabled": title, "text": "Lake day", "ms": 2000}
    plan["captions"] = {**(plan.get("captions") or {}), "enabled": captions, "style": "clean"}
    plan["overlays"] = [{"id": "o1", "asset_id": pic["id"], "clip_id": "c1", "offset_ms": 1500, "length_ms": 2000,
                         "motion": "zoom", "label": "Lake shot"}]
    base = {"in_ms": 0, "length_ms": None, "gain_db": 0.0, "mute": False, "fade_in_ms": 0, "fade_out_ms": 0,
            "duck": False, "loop": False, "anchor": None}
    plan["audio"] = [
        {**base, "id": "a1", "asset_id": vo["id"], "role": "voiceover", "label": "Intro voice", "start_ms": 1000,
         "out_ms": 4000},
        {**base, "id": "a2", "asset_id": music["id"], "role": "music", "label": "Bed", "start_ms": 0, "out_ms": None,
         "loop": True, "duck": True, "gain_db": -18.0},
        {**base, "id": "a3", "asset_id": fx1["id"], "role": "effect", "label": "Whoosh", "start_ms": 5000,
         "out_ms": 1500},
        {**base, "id": "a4", "asset_id": fx2["id"], "role": "effect", "label": "Ding", "start_ms": 5500,
         "out_ms": 1000, "gain_db": 2.0},
    ]
    plan["tracks"] = {**plan.get("tracks", {}), "music": {"gain_db": -2.0, "mute": False}}
    plan["chapters"] = [{"title": "Welcome", "clip_id": "c1", "offset_ms": 0},
                        {"title": "The lake", "clip_id": "c3", "offset_ms": 0},
                        {"title": "The island", "clip_id": "c5", "offset_ms": 0}]
    video_flow.save_revision(project["id"], plan, "Test cut", None, {"action": "build", "prev": None, "redo": None})
    return db.fetch("studio_projects", project["id"])


def _built(project: dict, **kw):
    from clipfoundry import db
    from clipfoundry.studio import interchange, video_flow

    plan = video_flow.plan_at(project["id"], project["plan_revision"])
    assets = video_flow._assets(project, plan)
    words = {aid: video_flow.transcript_words(a, db.get_settings(), cached_only=True) for aid, a in assets.items()
             if a["kind"] == "video"}
    tl = interchange.build(plan, assets, words, name="Lake day v1", url_for=lambda a: Path(a["path"]).as_uri(), **kw)
    return plan, assets, tl


def _layout(track: dict) -> list[dict]:
    """Each item of an OTIO track with its place: start/end on the track and, for clips, the frames it shows
    including the transitions on both sides (what the clip contributes to the program)."""
    rows, pos = [], 0.0
    kids = track["children"]
    for i, c in enumerate(kids):
        if c["OTIO_SCHEMA"].startswith("Transition"):
            continue
        d = c["source_range"]["duration"]["value"]
        before = kids[i - 1] if i and kids[i - 1]["OTIO_SCHEMA"].startswith("Transition") else None
        after = kids[i + 1] if i + 1 < len(kids) and kids[i + 1]["OTIO_SCHEMA"].startswith("Transition") else None
        rows.append({"item": c, "start": pos, "end": pos + d,
                     "shown_from": pos - (before["in_offset"]["value"] if before else 0),
                     "shown_to": pos + d + (after["out_offset"]["value"] if after else 0),
                     "src": c["source_range"]["start_time"]["value"],
                     "src_shown_from": c["source_range"]["start_time"]["value"] - (before["in_offset"]["value"]
                                                                                   if before else 0)})
        pos += d
    return rows


@pytest.mark.parametrize("fps,transition,title", [(30, ("dissolve", 500), True), (25, ("fade", 333), True),
                                                    (24, ("cut", 0), False), (60, ("dissolve", 517), False)])
def test_picture_track_is_frame_exact_against_the_render_frame_map(env, fps, transition, title):
    from clipfoundry.studio import engine

    project = _video(env, fps=fps, transition=transition, title=title)
    plan, _assets, tl = _built(project)
    els, _ = engine.frame_map(plan, fps)
    v1 = tl.otio["tracks"]["children"][0]
    assert v1["kind"] == "Video" and v1["name"] == "Video 1"
    rows = _layout(v1)
    assert len(rows) == len(els) == (5 if title else 4)  # the left-out clip is not in the timeline
    assert rows[-1]["end"] == els[-1]["end_f"] == tl.frames
    for row, e in zip(rows, els):
        # every element shows exactly the frames the render gives it, transitions included
        assert (row["shown_from"], row["shown_to"]) == (e["start_f"], e["end_f"])
        if e["kind"] == "video":  # and starts at the same source time
            assert row["src_shown_from"] == pytest.approx(e["src_in_ms"] * fps / 1000, abs=1e-5)
            assert row["item"]["metadata"]["clipforge"]["clip_id"] == e["clip_id"]
    transitions = [c for c in v1["children"] if c["OTIO_SCHEMA"] == "Transition.1"]
    expected = sum(1 for e in els[1:] if e["ov_in"])
    assert len(transitions) == expected == tl.counts["transitions"]
    if transition[0] == "cut":
        assert expected == 0
    else:  # the island clip's join is a straight cut whatever the plan's transition
        assert expected == len(els) - 2
        name = {"dissolve": "Cross Dissolve", "fade": "Dip to Black"}[transition[0]]
        assert {t["name"] for t in transitions} == {name}
    meta = tl.otio["metadata"]
    w, h = engine.ASPECTS["9:16"]
    assert meta["filmcraft"]["settings"]["width"] == w and meta["filmcraft"]["settings"]["height"] == h
    assert meta["filmcraft"]["settings"]["frame_rate"] == {"num": fps, "den": 1}
    assert meta["clipforge"]["frames"] == tl.frames and tl.otio["global_start_time"]["rate"] == fps
    title_item = rows[0]["item"]
    if title:
        assert title_item["name"] == "Title: Lake day"
        assert title_item["media_references"]["DEFAULT_MEDIA"]["OTIO_SCHEMA"] == "GeneratorReference.1"
        assert title_item["markers"][0]["name"] == "Title: Lake day"


def test_sound_tracks_follow_the_cuts_and_keep_volume_loops_and_overlaps(env):
    from clipfoundry.studio import engine

    project = _video(env)
    plan, _assets, tl = _built(project)
    tracks = {t["name"]: t for t in tl.otio["tracks"]["children"]}
    assert list(tracks) == ["Video 1", "Pictures over the video", "Sound from your videos", "Voiceover", "Music",
                            "Sound effects 1", "Sound effects 2"]
    v1, a1 = _layout(tracks["Video 1"]), _layout(tracks["Sound from your videos"])
    assert [(r["start"], r["end"]) for r in a1] == [(r["start"], r["end"]) for r in v1]  # same cuts
    kinds = [r["item"]["OTIO_SCHEMA"] for r in a1]
    # title (gap), clip 1 (sound), the image (gap), clip 3 (sound), clip 5 muted (gap)
    assert kinds == ["Gap.1", "Clip.2", "Gap.1", "Clip.2", "Gap.1"]
    assert a1[1]["item"]["metadata"]["filmcraft"] == {"gain_db": -3.0, "link": 2}
    assert v1[1]["item"]["metadata"]["filmcraft"]["link"] == 2  # picture and sound of a clip are linked
    fades = [c for c in tracks["Sound from your videos"]["children"] if c["OTIO_SCHEMA"] == "Transition.1"]
    # crossfades where a side has sound: title->c1, c1->image, image->c3 (c3->c5 is a straight cut)
    assert [f["name"] for f in fades] == ["Cross Fade (+3dB)"] * 3
    # voiceover where it was placed
    fps = 30
    vo = _layout(tracks["Voiceover"])
    assert [r["item"]["OTIO_SCHEMA"] for r in vo] == ["Gap.1", "Clip.2"]
    assert (vo[1]["start"], vo[1]["end"]) == (30, 150) and vo[1]["src"] == 0  # 1 s in, 4 s long
    # the music bed loops: whole copies of its 7.3 s file (219 frames) to the end of the video, at its volume
    music = _layout(tracks["Music"])
    assert all(r["src"] == 0 for r in music) and music[-1]["end"] == tl.frames
    assert [r["end"] - r["start"] for r in music[:-1]] == [219] * (len(music) - 1)
    assert music[0]["item"]["metadata"]["filmcraft"] == {"gain_db": -18.0}
    assert music[0]["item"]["metadata"]["clipforge"]["duck"] is True
    assert tracks["Music"]["metadata"]["filmcraft"] == {"volume_db": -2.0, "muted": False}
    # two effects that overlap in time go on two lanes
    fx1, fx2 = _layout(tracks["Sound effects 1"]), _layout(tracks["Sound effects 2"])
    assert (fx1[-1]["start"], fx1[-1]["end"]) == (150, 195) and (fx2[-1]["start"], fx2[-1]["end"]) == (165, 195)
    assert fx2[-1]["item"]["metadata"]["filmcraft"]["gain_db"] == 2.0
    # the picture over the first clip, where the render shows it
    els, _ = engine.frame_map(plan, fps)
    over = engine._overlay_frames(plan, els, fps, _assets)
    o = next(o for items in over.values() for o in items)
    pics = _layout(tracks["Pictures over the video"])
    assert (pics[-1]["start"], pics[-1]["end"]) == (o["start_f"], o["end_f"])
    assert tl.counts == {"clips": 4, "title": True, "transitions": 3, "overlays": 1, "audio_items": 4,
                         "audio_tracks": 5, "captions": tl.counts["captions"], "chapters": 3}
    assert [m["name"] for m in tl.otio["tracks"]["markers"]] == ["Welcome", "The lake", "The island"]


def test_captions_are_srt_on_the_output_timeline(env):
    from clipfoundry.studio import engine

    project = _video(env)
    plan, _assets, tl = _built(project)
    blocks = [b.splitlines() for b in tl.srt.strip().split("\n\n")]
    assert blocks and all(b[0].isdigit() and " --> " in b[1] for b in blocks)

    def sec(t: str) -> float:
        h, m, rest = t.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    spans = [tuple(sec(x) for x in b[1].split(" --> ")) for b in blocks]
    assert all(a < b for a, b in spans) and all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1))
    assert spans[-1][1] <= tl.frames / tl.fps
    words = engine.output_words(plan, {aid: [] for aid in _assets}, engine.render_timeline(plan, 30))
    assert words == []  # sanity: captions come from the cached transcripts, through the same time map
    text = " ".join(" ".join(b[2:]) for b in blocks)
    assert "welcome to the lake" in text.lower() and "island" in text.lower()
    assert tl.counts["captions"] == len(blocks)


def test_captions_off_writes_no_srt(env):
    project = _video(env, captions=False)
    _plan, _assets, tl = _built(project)
    assert tl.srt == "" and tl.counts["captions"] == 0


def test_the_timeline_reads_in_opentimelineio_itself(env):
    """When the OpenTimelineIO library is installed (pip install opentimelineio), it reads the file and agrees on
    every track's length and every clip's place."""
    otio = pytest.importorskip("opentimelineio")
    project = _video(env)
    _plan, _assets, tl = _built(project)
    t = otio.adapters.read_from_string(json.dumps(tl.otio), "otio_json")
    assert t.duration().rescaled_to(30).value == pytest.approx(tl.frames)
    v1 = t.tracks[0]
    assert [c.name for c in v1.find_clips()] == ["Title: Lake day", "Welcome", "Lake", "Swim", "Island"]
    assert v1.duration().rescaled_to(30).value == pytest.approx(tl.frames)
    for track in t.tracks:
        assert track.duration().rescaled_to(30).value <= tl.frames + 1e-6
    # OTIO's own idea of where each clip sits matches ours
    for clip, row in zip(v1.find_clips(), _layout(tl.otio["tracks"]["children"][0])):
        assert clip.range_in_parent().start_time.rescaled_to(30).value == pytest.approx(row["start"])


def test_package_files_readme_and_portable_zip(env):
    from clipfoundry.studio import interchange

    project = _video(env)
    folder = env / "out"
    pkg = interchange.for_video(project, 1, folder, portable=False)
    assert pkg.timeline.name == "Lake day part 1 2 v1.otio" and pkg.captions.name == "Lake day part 1 2 v1.srt"
    doc = json.loads(pkg.timeline.read_text())
    urls = {c["media_references"]["DEFAULT_MEDIA"]["target_url"] for t in doc["tracks"]["children"]
            for c in t["children"] if c["OTIO_SCHEMA"] == "Clip.2"
            and c["media_references"]["DEFAULT_MEDIA"]["OTIO_SCHEMA"] == "ExternalReference.1"}
    assert all(u.startswith("file:///") for u in urls) and any("talk%20one.mp4" in u for u in urls)
    assert doc["metadata"]["clipforge"]["video_id"] == project["id"] and doc["metadata"]["clipforge"]["revision"] == 1
    readme = pkg.readme.read_text()
    for words in ("ducking", "Sound fades", "Punch-in zooms", "Fill the frame", "blurred background", "push-in",
                  "caption look", "loudness"):
        assert words.lower() in readme.lower()
    if pkg.title:  # FFmpeg drew the title card: the timeline uses the picture
        assert any(u.endswith("Title%20card.png") for u in [
            c["media_references"]["DEFAULT_MEDIA"].get("target_url", "") for c in doc["tracks"]["children"][0]["children"]
            if c["OTIO_SCHEMA"] == "Clip.2"])
    # the portable package points inside itself and carries every file once
    port = interchange.for_video(project, 1, env / "portable", portable=True)
    out = interchange.zip_package(port, env / "t.zip")
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        doc = json.loads(z.read(port.timeline.name))
    assert {port.timeline.name, port.captions.name, "README.txt"} <= names
    media = {n for n in names if n.startswith("media/")}
    assert media == {"media/talk one.mp4", "media/talk two.mp4", "media/lake.png", "media/voice.m4a",
                     "media/bed.m4a", "media/whoosh.wav", "media/ding.wav"}
    urls = {c["media_references"]["DEFAULT_MEDIA"].get("target_url") for t in doc["tracks"]["children"]
            for c in t["children"] if c["OTIO_SCHEMA"] == "Clip.2"}
    assert "media/talk%20one.mp4" in urls and not any(u.startswith("file:") for u in urls if u)


def _fake_program(path: Path, body: str) -> str:
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


FAKE_APP = """import json, sys
from pathlib import Path
Path(__file__).with_suffix(".log").write_text(json.dumps(sys.argv[1:]))
"""
FAKE_CLI = """import json, sys
from pathlib import Path
args = sys.argv[1:]
Path(__file__).with_suffix(".log").write_text(json.dumps(args))
out = Path(args[args.index("--save-as") + 1])
out.write_text("{}")
print(json.dumps({"items": [], "sequences": [7], "errors": [], "documents": [
    {"format": "OpenTimelineIO", "sequences": [7], "linkedMedia": 7, "offlineMedia": [], "report": []}]}))
"""


def _wait_for(p: Path, seconds: float = 10.0) -> list:
    end = time.time() + seconds
    while time.time() < end:
        if p.is_file() and p.read_text():
            return json.loads(p.read_text())
        time.sleep(0.05)
    raise AssertionError(f"{p} was never written")


@pytest.mark.skipif(sys.platform in ("win32", "darwin"), reason="the stand-ins are started as Linux programs")
def test_open_in_filmcraft_with_and_without_its_command_line_tool(env, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    project = _video(env)
    tools = env / "tools"
    tools.mkdir()
    (tools / "cli").mkdir(parents=True)
    app_path = _fake_program(tools / "filmcraft", FAKE_APP)
    cli_path = _fake_program(tools / "cli" / "filmcraft-cli", FAKE_CLI)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # no real FilmCraft on this machine's PATH
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        # not installed: the timeline is still written, and the page says where to get FilmCraft
        st = api.get("/api/studio/filmcraft", headers=H).json()
        assert st["available"] and not st["installed"] and st["page"].startswith("https://getartcraft.com/")
        r = api.post(f"/api/studio/videos/{project['id']}/filmcraft", json={}, headers=H).json()
        assert r["installed"] is False and r["opened"] is False and r["revision"] == 1
        assert Path(r["folder"], r["timeline"]).is_file() and Path(r["folder"], "README.txt").is_file()
        assert r["counts"]["clips"] == 4 and any("ducking" in x for x in r["not_carried"])
        # the app alone: started with the timeline and captions to import
        monkeypatch.setenv("CLIPFOUNDRY_FILMCRAFT", app_path)
        r = api.post(f"/api/studio/videos/{project['id']}/filmcraft", json={"revision": 1}, headers=H).json()
        assert r["opened"] and r["how"] == "timeline"
        assert _wait_for(tools / "filmcraft.log") == [str(Path(r["folder"], r["timeline"])),
                                                       str(Path(r["folder"], r["captions"]))]
        (tools / "filmcraft.log").unlink()
        # app and command-line tool: imported into a FilmCraft project first, and the app opens the project
        monkeypatch.setenv("CLIPFOUNDRY_FILMCRAFT_CLI", cli_path)
        st = api.get("/api/studio/filmcraft", headers=H).json()
        assert st["installed"] and st["app"] and st["cli"]
        r = api.post(f"/api/studio/videos/{project['id']}/filmcraft", json={}, headers=H).json()
        assert r["opened"] and r["how"] == "project" and r["project"].endswith(".fcproj") and r["warnings"] == []
        cli_args = json.loads((tools / "cli" / "filmcraft-cli.log").read_text())
        assert cli_args == ["--compact", "import", str(Path(r["folder"], r["timeline"])),
                            str(Path(r["folder"], r["captions"])), "--save-as", r["project"]]
        assert _wait_for(tools / "filmcraft.log") == [r["project"]]
        # a failing import falls back to opening the timeline in the app
        _fake_program(tools / "cli" / "filmcraft-cli", "import sys\nprint('broken', file=sys.stderr)\nsys.exit(3)\n")
        (tools / "filmcraft.log").unlink()
        r = api.post(f"/api/studio/videos/{project['id']}/filmcraft", json={}, headers=H).json()
        assert r["opened"] and r["how"] == "timeline" and "broken" in r["warnings"][0]
        assert len(_wait_for(tools / "filmcraft.log")) == 2
        # an unknown video is not found
        assert api.post("/api/studio/videos/nope/filmcraft", json={}, headers=H).status_code == 404


def test_online_studio_offers_the_download_but_never_opens_programs(env, monkeypatch):
    from clipfoundry.studio import filmcraft

    monkeypatch.setattr(filmcraft.cloud_settings, "enabled", lambda: True)
    st = filmcraft.status()
    assert st["available"] is False and st["installed"] is False and "download" in st["message"]


def test_timeline_zip_route(env):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    project = _video(env)
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        r = api.get(f"/api/studio/videos/{project['id']}/timeline.zip", headers=H)
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        assert "Lake%20day%20part%201%202%20v1%20timeline.zip" in r.headers["content-disposition"]
        z = zipfile.ZipFile(__import__("io").BytesIO(r.content))
        assert "media/talk one.mp4" in z.namelist()
        r = api.get(f"/api/studio/videos/{project['id']}/timeline.zip?media=0", headers=H)
        names = zipfile.ZipFile(__import__("io").BytesIO(r.content)).namelist()
        assert not any(n.startswith("media/") for n in names) and any(n.endswith(".otio") for n in names)
        # the scratch folders are gone once sent
        leftovers = [p for p in (Path(os.environ["CLIPFOUNDRY_DATA"]) / "videos" / project["id"]).glob("handoff-*")]
        assert leftovers == []
        assert api.get(f"/api/studio/videos/{project['id']}/timeline.zip?revision=9", headers=H).status_code == 404


def test_a_missing_original_is_refused_before_writing(env):
    from clipfoundry.studio import interchange

    project = _video(env)
    Path(env / "files" / "talk two.mp4" / "talk two.mp4").unlink()
    with pytest.raises(interchange.HandoffError, match="missing"):
        interchange.for_video(project, 1, env / "x", portable=False)

"""What an animated short keeps of its files (docs/clipforge/ANIMATED_SHORTS.md, "Tidying"): every file a build stores
is listed for its short (short_files), so a file nothing names any more goes at the next build (a clip a later build
replaced before any version kept it, a picture that left the scene's earlier pictures, a deleted scene's files that
no version kept), anything a saved version names stays for undo, and deleting the short reaches every file on its
list. What the picture, video and voice makers on this computer made for a short is kept with what the short made
from it (not in engines/made), so it goes when that does.

Same stand-in voice and camera moves as tests/test_studio_shorts_flow.py.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from test_studio_shorts_flow import SCRIPT, _fresh, _make, _plan, _run, _scenes, env  # noqa: F401


def _listed(project_id: str) -> set[str]:
    from clipfoundry import db

    return {r["asset_id"] for r in db.select("short_files", "project_id = ?", (project_id,))}


def _gone(asset: dict) -> bool:
    from clipfoundry import db

    return db.fetch("assets", asset["id"]) is None and not Path(asset["path"]).parent.exists()


def _kept(asset_id: str) -> bool:
    from clipfoundry import db

    row = db.fetch("assets", asset_id)
    return bool(row) and Path(row["path"]).is_file()


def _named_by_versions(project_id: str) -> str:
    from clipfoundry import db

    return " ".join(json.dumps(r["plan"]) for r in db.select("edit_plans", "project_id = ?", (project_id,)))


def test_every_file_a_build_stores_is_listed_for_its_short(env):
    project = _make(env)
    pid = project["id"]
    scenes = _scenes(pid, _plan(pid))
    made = {s["picture_asset_id"] for s in scenes} | {s["clip_asset_id"] for s in scenes}
    assert made and _listed(pid) == made


def test_a_clip_an_overtaken_build_made_goes_once_a_later_build_replaces_it(env, monkeypatch):
    """The review's case: a build makes a scene's clip and puts it in the scene, but a newer change overtakes the
    build, so it saves no version; the next build makes the scene again. Nothing names the first clip any more, so it
    goes (row, read-only copy and folder with its transcript). The clip the first version shows stays for undo."""
    from clipfoundry import db
    from clipfoundry.makers import shorts
    from clipfoundry.studio import uploads, video_flow

    project = _make(env)
    pid = project["id"]
    first, second = _scenes(pid, _plan(pid))[:2]
    calls = env["calls"]
    shorts.update_scene(_fresh(pid), first["id"], {"narration": "Octopuses have three busy hearts."})
    shorts.update_scene(_fresh(pid), second["id"], {"narration": "Two of them push blood through the gills."})
    # while the second scene's clip is made (the first scene's new clip is in its scene by then), the owner changes
    # the first scene again: this build is overtaken and saves no version
    calls.during_clip = lambda: setattr(calls, "during_clip", lambda: shorts.update_scene(
        _fresh(pid), first["id"], {"narration": "Octopuses have three hearts and blue blood."}))
    overtaken: list[str] = []
    real = shorts.save_plan

    def watch(project_id, build=None):
        overtaken.append(db.fetch("short_scenes", first["id"])["clip_asset_id"])
        return real(project_id, build)

    monkeypatch.setattr(shorts, "save_plan", watch)
    _run(env)
    middle = overtaken[0]
    assert middle not in (first["clip_asset_id"], db.fetch("short_scenes", first["id"])["clip_asset_id"])
    assert middle not in _named_by_versions(pid)  # the overtaken build saved no version naming it
    assert db.fetch("assets", middle) is None and middle not in _listed(pid)
    assert not any(p.name == middle for p in uploads.assets_dir("local").iterdir())  # its folder went too
    assert _kept(first["clip_asset_id"])  # the first version shows it: undo can bring it back
    now = db.fetch("short_scenes", first["id"])
    assert _kept(now["clip_asset_id"]) and now["clip_asset_id"] in _listed(pid)
    video_flow.restore(pid, 1)
    assert db.fetch("short_scenes", first["id"])["clip_asset_id"] == first["clip_asset_id"]


def test_a_thrown_away_clip_is_gone_from_the_list_and_the_folder(env, monkeypatch):
    """A clip made for words that changed while it was made is deleted at once, with its list entry."""
    from clipfoundry import db
    from clipfoundry.makers import shorts
    from clipfoundry.studio import uploads

    project = _make(env)
    pid = project["id"]
    scene = _scenes(pid, _plan(pid))[0]
    stored: list[dict] = []
    real = uploads.store_file
    monkeypatch.setattr(uploads, "store_file", lambda *a, **k: stored.append(real(*a, **k)) or stored[-1])
    env["calls"].during_clip = lambda: shorts.update_scene(_fresh(pid), scene["id"],
                                                           {"narration": "Octopuses: three hearts, one body."})
    shorts.update_scene(_fresh(pid), scene["id"], {"narration": "Octopuses have three busy hearts."})
    _run(env)
    thrown, kept = [a for a in stored if a["kind"] == "video"]
    assert _gone(thrown) and thrown["id"] not in _listed(pid)
    assert _kept(kept["id"]) and kept["id"] in _listed(pid)
    assert db.fetch("short_scenes", scene["id"])["clip_asset_id"] == kept["id"]


def test_a_picture_that_left_the_earlier_pictures_goes_unless_a_version_kept_it(env, monkeypatch):
    """A scene keeps its newest pictures to choose from; one that falls off that list and that no saved version
    shows goes at the next build. One a version shows stays (undo shows it again)."""
    from clipfoundry import db
    from clipfoundry.makers import shorts

    monkeypatch.setattr(shorts, "MAX_EARLIER", 1)  # a scene keeps two pictures: the newest and one earlier
    project = _make(env)
    pid = project["id"]
    scene = _scenes(pid, _plan(pid))[0]
    first_picture = scene["picture_asset_id"]
    calls = env["calls"]
    # a new picture, and while its clip is made another new picture: the first new one is never in a version
    calls.during_clip = lambda: shorts.update_scene(_fresh(pid), scene["id"], {"new_picture": True})
    shorts.update_scene(_fresh(pid), scene["id"], {"new_picture": True})
    _run(env)
    pictures = [e["asset_id"] for e in db.fetch("short_scenes", scene["id"])["pictures"]]
    assert len(pictures) == 2
    never_shown, shown = pictures
    assert never_shown not in _named_by_versions(pid) and shown in _named_by_versions(pid)
    assert all(_kept(a) for a in (first_picture, never_shown, shown))  # all still named somewhere

    shorts.update_scene(_fresh(pid), scene["id"], {"new_picture": True})
    _run(env)
    now = [e["asset_id"] for e in db.fetch("short_scenes", scene["id"])["pictures"]]
    assert never_shown not in now and shown in now
    assert db.fetch("assets", never_shown) is None and never_shown not in _listed(pid)
    assert _kept(first_picture) and first_picture not in now  # off the list, but the first version shows it
    assert all(_kept(a) for a in now)


def test_deleting_the_short_reaches_every_file_on_its_list(env):
    """A file only the short's list names (a build was stopped after storing it, before a scene took it) goes with
    the short; the window counts it with what ClipForge made for the scenes. A file another short lists stays."""
    from clipfoundry import config, db
    from clipfoundry.makers import shorts
    from clipfoundry.studio import project_delete, uploads

    project = _make(env)
    pid = project["id"]
    other = _make(env, script="Owls turn their heads almost all the way round.")
    scenes = _scenes(pid, _plan(pid))
    loose = env["tmp"] / "loose.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=108x192:r=30:d=0.5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(loose)], check=True)
    stray = uploads.store_file("local", loose, "Scene 9.mp4")
    shorts._list_file(pid, "local", stray["id"])  # as the build does right after storing a file
    shared_with_other = _scenes(other["id"], _plan(other["id"]))[0]["picture_asset_id"]
    shorts._list_file(pid, "local", shared_with_other)  # the same bytes, made for the other short too
    plan = project_delete.plan("local", pid, "full_video")
    assert f"What ClipForge made for its scenes: {len(scenes)} pictures and {len(scenes) + 1} clips." in plan["goes"]
    out = project_delete.delete("local", pid, "full_video")
    assert out["deleted"]
    for s in scenes:
        assert db.fetch("assets", s["picture_asset_id"]) is None and db.fetch("assets", s["clip_asset_id"]) is None
    assert _gone(stray) and not db.select("short_files", "project_id = ?", (pid,))
    assert _kept(shared_with_other) and shared_with_other in _listed(other["id"])
    assert not (config.data_dir() / "videos" / pid).exists()


def _loose(env, name: str, colour: str) -> dict:
    """A file stored as a build stores one (its bytes made here, so no other test's file has them)."""
    from clipfoundry.studio import uploads

    loose = env["tmp"] / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={colour}:s=108x192:r=30:d=0.5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(loose)], check=True)
    return uploads.store_file("local", loose, f"{name}.mp4")


def test_a_file_only_another_shorts_list_names_stays_until_that_short_lets_it_go(env):
    """Files are stored once, so two shorts' builds can store the same bytes and both list them before a scene
    takes them. Then only the other short's list names the file: tidying this short and deleting it both leave it,
    and it goes once the other short lets it go too."""
    from clipfoundry.makers import shorts
    from clipfoundry.studio import project_delete

    pid = _make(env)["id"]
    other = _make(env, script="Owls turn their heads almost all the way round.")["id"]
    both = _loose(env, "Scene 7", "navy")
    shorts._list_file(pid, "local", both["id"])
    shorts._list_file(other, "local", both["id"])
    assert shorts._tidy_files(pid, "local") == 0 and shorts._drop(both["id"], "local", pid) is False
    assert _kept(both["id"])
    project_delete.delete("local", pid, "full_video")
    assert _kept(both["id"]) and both["id"] in _listed(other)
    assert shorts._tidy_files(other, "local") == 1 and _gone(both)


def test_tidying_leaves_a_file_an_upload_of_the_same_bytes_was_just_given(env, monkeypatch):
    """The owner uploads bytes ClipForge already has as a short's stray file: the upload is given the stored copy
    and records it a moment later. A tidy that runs in between does not delete that copy from under the upload."""
    from clipfoundry import db
    from clipfoundry.makers import shorts
    from clipfoundry.studio import uploads

    pid = _make(env)["id"]
    stray = _loose(env, "Scene 8", "teal")
    shorts._list_file(pid, "local", stray["id"])  # as a stopped build leaves it: nothing names it
    data = Path(stray["path"]).read_bytes()
    up = uploads.start("local", "mine.mp4", len(data))
    uploads.put_chunk(up["id"], 0, data)
    real_update, tidied = db.update, []

    def tidy_first(table, value, key="id", **fields):
        if table == "uploads" and fields.get("status") == "complete":  # the copy is handed out, not recorded yet
            tidied.append(shorts._tidy_files(pid, "local"))
        return real_update(table, value, key, **fields)

    monkeypatch.setattr(db, "update", tidy_first)
    assert uploads.complete(up["id"])["id"] == stray["id"]
    assert tidied == [0] and _kept(stray["id"])
    assert shorts._tidy_files(pid, "local") == 0 and _kept(stray["id"])  # the upload names it now


# ------------------------------------------------------------------ the makers on this computer
class FakeMakers:
    """The local makers: each writes its file and a note into engines/made, as clipfoundry/engines does."""
    class EngineError(RuntimeError):
        pass

    def __init__(self):
        self.n = 0

    def _out(self, kind: str, suffix: str) -> Path:
        from clipfoundry import config

        folder = config.data_dir() / "engines" / "made" / kind / "2026-11-10"
        folder.mkdir(parents=True, exist_ok=True)
        self.n += 1
        path = folder / f"{kind}{self.n:04d}{suffix}"
        path.with_suffix(".json").write_text(json.dumps({"model": "test", "licence": "Apache-2.0", "file": path.name}))
        return path

    def status(self, role):
        return {"ready": role in ("image", "video"), "engine": "Fake makers", "why": ""}

    def make_image(self, prompt, *, negative="", style="", width=1080, height=1920, seed=None, progress=None,
                   cancel=None):
        from PIL import Image

        path = self._out("picture", ".png")
        Image.new("RGB", (108, 192), (seed or 0) % 256).save(path)
        return path

    def make_video(self, prompt, *, image=None, seconds=4.0, width=720, height=1280, seed=None, progress=None,
                   cancel=None):
        path = self._out("video", ".mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=green:s=72x128:r=24:d=0.5",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
        return path


def _makers(env, monkeypatch) -> FakeMakers:
    """Pictures and video from FakeMakers; the stand-in voice reads as the local voice engine, which leaves its own
    original and note in engines/made like the real one."""
    import shutil
    import sys

    from clipfoundry.makers import local_engines, shorts

    fake = FakeMakers()
    monkeypatch.setattr(local_engines, "module", lambda: fake)
    monkeypatch.setattr(shorts, "_status_cache", {})
    voice = sys.modules["clipfoundry.makers.voice"]
    motion = sys.modules["clipfoundry.makers.motion"]
    real_speak = voice.speak

    def speak(text, out, **kw):
        got = real_speak(text, out, **kw)
        original = fake._out("voice", ".wav")
        shutil.copyfile(out, original)
        return {**got, "engine": "engine", "original": str(original)}

    def video_clip(video, audio, out, *, duration_s, fps=30, size=(1080, 1920), cancel=None, **kw):
        return motion.still_clip(Path(video), audio, out, duration_s=duration_s, fps=fps)

    monkeypatch.setattr(voice, "speak", speak)
    monkeypatch.setattr(motion, "video_clip", video_clip)
    return fake


def _made_files() -> list[Path]:
    from clipfoundry import config

    return sorted(p for p in (config.data_dir() / "engines" / "made").rglob("*") if p.is_file())


def test_what_the_makers_made_for_a_short_is_kept_with_it_and_goes_with_it(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.makers import shorts
    from clipfoundry.studio import project_delete, uploads

    _makers(env, monkeypatch)
    project = _make(env, motion="animate")
    pid = project["id"]
    scenes = _scenes(pid, _plan(pid))
    assert all(s["info"]["picture"]["source"] == "engine" and s["info"]["motion"]["how"] == "engine"
               for s in scenes), [s["info"] for s in scenes]
    assert _made_files() == []  # nothing the short uses is left in engines/made
    for s in scenes:
        picture = uploads.work_dir(db.fetch("assets", s["picture_asset_id"]))
        clip = uploads.work_dir(db.fetch("assets", s["clip_asset_id"]))
        assert json.loads((picture / "maker.json").read_text())["licence"] == "Apache-2.0"
        assert (clip / "maker.mp4").is_file() and (clip / "maker.json").is_file()
        voices = shorts.short_dir(pid) / "voice" / "maker"
        assert (voices / f"{s['voice_key']}.wav").is_file() and (voices / f"{s['voice_key']}.json").is_file()

    # a scene made again: its old clip (no version but the first shows it) stays with its originals...
    first = scenes[0]
    shorts.update_scene(_fresh(pid), first["id"], {"move": "pan_up", "again": True})
    _run(env)
    assert (uploads.work_dir(db.fetch("assets", first["clip_asset_id"])) / "maker.mp4").is_file()

    plan = project_delete.plan("local", pid, "full_video")
    made_line = next(line for line in plan["goes"] if line.startswith("What ClipForge made for its scenes:"))
    assert made_line.endswith(", with the originals of the pictures, video clips and voices made for it on this "
                              "computer."), made_line
    assert not any("engines/made" in line for line in plan["stays"])
    folder = shorts.short_dir(pid).parent
    project_delete.delete("local", pid, "full_video")
    assert not db.select("assets") and _made_files() == [] and not folder.exists()


def test_the_voices_original_goes_when_its_voice_is_tidied(env, monkeypatch):
    from clipfoundry.makers import shorts

    _makers(env, monkeypatch)
    monkeypatch.setattr(shorts, "MAX_VOICES", 2)
    project = _make(env)
    pid = project["id"]
    scene = _scenes(pid, _plan(pid))[0]
    old_key = scene["voice_key"]
    voices = shorts.short_dir(pid) / "voice"
    os.utime(voices / f"{old_key}.wav", (1e9, 1e9))  # the oldest recorded voice
    shorts.update_scene(_fresh(pid), scene["id"], {"narration": "Octopuses have three busy hearts."})
    _run(env)
    assert not (voices / f"{old_key}.wav").exists()
    assert not (voices / "maker" / f"{old_key}.wav").exists() and not (voices / "maker" / f"{old_key}.json").exists()
    kept = {p.stem for p in voices.glob("*.wav")}
    assert {p.stem for p in (voices / "maker").glob("*.wav")} == kept


def test_what_a_maker_made_that_the_short_could_not_use_is_deleted_with_its_note(env, monkeypatch):
    """A picture of the maker's that does not open and a video clip the short could not move to the voice are not
    left in engines/made: they go with their notes, and the scene says why the card or the camera stood in."""
    import sys

    from clipfoundry.makers import shorts

    fake = _makers(env, monkeypatch)
    real_image = fake.make_image

    def broken_image(*a, **k):
        path = real_image(*a, **k)
        path.write_bytes(path.read_bytes()[:40])  # cut short: it does not open
        return path

    monkeypatch.setattr(fake, "make_image", broken_image)
    motion = sys.modules["clipfoundry.makers.motion"]
    monkeypatch.setattr(motion, "video_clip", lambda *a, **k: (_ for _ in ()).throw(
        motion.MotionError("This video could not be fitted to the voice.")))
    project = _make(env, motion="animate")
    scenes = _scenes(project["id"], _plan(project["id"]))
    assert all(s["info"]["picture"]["source"] == "card" for s in scenes)
    assert all("could not be fitted" in s["info"]["motion"]["why"] for s in scenes)
    left = [p for p in _made_files() if p.parent.parent.name != "voice"]
    assert left == [], left  # the voices were used: they are kept with the short, not here
    assert shorts.voice_originals(project["id"]).is_dir()


def test_a_picture_you_chose_for_two_scenes_goes_with_the_short(env, tmp_path):
    """The owner uploads their own picture for one scene and later uploads it again for another ("Use my picture"
    twice: ClipForge keeps one copy, so both are that copy). Both uploads are the short's own, so deleting the short
    removes ClipForge's copy of the picture instead of keeping it as a file the owner added again."""
    import time

    from clipfoundry import db
    from clipfoundry.makers import shorts
    from clipfoundry.studio import project_delete, uploads

    project = _make(env)
    pid = project["id"]
    png = tmp_path / "owl.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=orange:s=64x64", "-frames:v", "1",
                    str(png)], check=True)

    def upload() -> dict:
        data = png.read_bytes()
        up = uploads.start("local", "owl.png", len(data))
        uploads.put_chunk(up["id"], 0, data)
        return uploads.complete(up["id"])

    scenes = _scenes(pid, _plan(pid))
    owl = upload()
    shorts.update_scene(_fresh(pid), scenes[0]["id"], {"picture_asset_id": owl["id"]})
    _run(env)
    time.sleep(0.01)
    assert upload()["id"] == owl["id"]  # the same picture again, for the next scene
    shorts.update_scene(_fresh(pid), scenes[1]["id"], {"picture_asset_id": owl["id"]})
    _run(env)
    assert [r["taken"] for r in db.select("uploads", "asset_id = ?", (owl["id"],))] == [pid, pid]
    plan = project_delete.plan("local", pid, "full_video")
    assert any(line.startswith("ClipForge's cop") and "“owl.png”" in line for line in plan["goes"])
    assert not any("added it again" in line for line in plan["stays"])
    project_delete.delete("local", pid, "full_video")
    assert db.fetch("assets", owl["id"]) is None

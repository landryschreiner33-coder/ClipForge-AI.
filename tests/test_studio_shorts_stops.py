"""Animated shorts when work stops, races or goes wrong (docs/clipforge/ANIMATED_SHORTS.md): Stop all jobs and a lost
build leave the short ready to go on, an old build never overrides a newer one, the script check is never skipped,
picture ideas never overwrite the owner's words, a stand-in voice gets another try, and errors are plain words.

Same stand-in voice and camera moves as tests/test_studio_shorts_flow.py.
"""
from __future__ import annotations

import errno
import time
from pathlib import Path

import pytest
from test_studio_shorts_flow import SCRIPT, _fresh, _make, _plan, _run, _scenes, env  # noqa: F401

THREE = ("Octopuses have three hearts and blue blood.\n\n"
         "Two hearts pump blood through the gills.\n\n"
         "The third heart keeps the rest of the body going.")


def _job(project_id: str) -> dict:
    from clipfoundry import db

    return db.select("studio_jobs", "target_id = ? AND kind = 'short_build'", (project_id,), "created_at DESC")[0]


def test_stop_all_jobs_stops_a_waiting_build_and_the_short_can_go_on(env, monkeypatch):
    from clipfoundry.jobs import worker
    from clipfoundry.makers import shorts
    from clipfoundry.office import work

    project = shorts.create("local", "local", name="", options={"mode": "paste", "script": SCRIPT})
    pid = project["id"]
    job = _job(pid)
    env["queued"].clear()
    worker.q.put(("studio", job["id"], None))
    assert worker.cancel_all() == 1
    short = _fresh(pid)
    assert short["short"]["stage"] == "stopped" and "Make the short" in short["message"]
    assert short["status"] == "draft"  # nothing was made yet
    shorts.make(_fresh(pid))
    _run(env)
    assert _fresh(pid)["status"] == "ready" and _fresh(pid)["plan_revision"] == 1
    assert work.STUDIO_KINDS["short_build"] == "Making the animated short"  # how the robot office names it


def test_stop_all_jobs_stops_the_build_that_is_running(env, monkeypatch):
    from clipfoundry.jobs import worker
    from clipfoundry.makers import shorts
    from clipfoundry.studio import jobs as studio_jobs

    project = shorts.create("local", "local", name="", options={"mode": "paste", "script": SCRIPT})
    job = _job(project["id"])
    lease = studio_jobs.claim(job["id"])
    monkeypatch.setattr(worker, "current", job["id"])
    monkeypatch.setattr(worker, "current_kind", "studio")
    try:
        worker.cancel_all()
    finally:
        worker.cancelled.discard(job["id"])
    assert lease.canceled()  # the build stops at its next check
    assert _fresh(project["id"])["short"]["stage"] == "stopped"


def test_stop_frees_a_short_whose_build_was_lost(env):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.makers import shorts

    project = shorts.create("local", "local", name="", options={"mode": "paste", "script": SCRIPT})
    pid = project["id"]
    db.update("studio_jobs", _job(pid)["id"], status="failed", error="lost")  # nothing will make it any more
    env["queued"].clear()
    assert _fresh(pid)["short"]["stage"] == "making"
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        r = api.post(f"/api/studio/videos/{pid}/cancel", headers={"X-ClipFoundry": "1"})
        assert r.status_code == 200 and r.json()["canceled"] == 0
    assert _fresh(pid)["short"]["stage"] == "stopped"  # so the page offers Make the short again
    made = _make(env)  # a short that is ready: Stop changes nothing
    shorts.stopped(made["id"])
    assert _fresh(made["id"])["short"]["stage"] == "ready" and _fresh(made["id"])["status"] == "ready"


def test_an_old_build_that_stops_late_leaves_the_newer_one_alone(env):
    from clipfoundry.makers import shorts

    project = _make(env)
    pid = project["id"]
    first = _scenes(pid, _plan(pid))[0]
    old = _fresh(pid)["short"]["build"]
    shorts.update_scene(_fresh(pid), first["id"], {"narration": "Three hearts beat inside every octopus."})
    shorts.stopped(pid, old)  # the earlier build noticed its stop only now
    short = _fresh(pid)
    assert short["short"]["stage"] == "making" and short["status"] == "building"
    shorts.stopped(pid, short["short"]["build"])
    assert _fresh(pid)["short"]["stage"] == "stopped"


def test_a_build_given_up_after_repeated_interruptions_offers_try_again(env):
    from clipfoundry import db
    from clipfoundry.makers import shorts
    from clipfoundry.studio import jobs as studio_jobs

    project = shorts.create("local", "local", name="", options={"mode": "paste", "script": SCRIPT})
    pid = project["id"]
    job = _job(pid)
    db.execute("UPDATE studio_jobs SET status = 'running', attempts = ?, lease_until = ?, lease_token = 'gone' "
               "WHERE id = ?", (studio_jobs.MAX_ATTEMPTS, time.time() - 5, job["id"]))
    studio_jobs.run(job["id"])  # the app started again; the build's last lease ran out long ago
    assert db.fetch("studio_jobs", job["id"])["status"] == "failed"
    short = _fresh(pid)
    assert short["status"] == "failed" and short["short"]["stage"] == "failed"
    assert "Try again" in short["short"]["message"]
    env["queued"].clear()
    shorts.make(_fresh(pid))
    _run(env)
    assert _fresh(pid)["status"] == "ready"


def test_try_again_after_the_writer_failed_still_stops_at_the_script(env, monkeypatch):
    from clipfoundry.makers import shorts, writer

    monkeypatch.setattr(writer, "ready", lambda settings: {"configured": True, "label": "Built-in AI", "local": True})
    answers = []

    def write(topic, **kw):
        if not answers:
            answers.append("timeout")
            raise writer.WriterError("ClipForge AI could not answer (timeout).")
        return {"title": "Salty seas", "character": "", "notes": [], "model": "Built-in AI", "local": True,
                "memories": [], "knowhow": [],
                "scenes": [{"narration": "Why is the sea salty, when rain is not?", "picture": "a raindrop"},
                           {"narration": "Rivers carry tiny bits of salt from the rocks.", "picture": "a river"}]}

    monkeypatch.setattr(writer, "write", write)
    project = shorts.create("local", "local", name="", options={"mode": "write", "topic": "salty seas",
                                                                "review": True})
    pid = project["id"]
    _run(env)
    short = _fresh(pid)
    assert short["short"]["stage"] == "failed" and short["short"]["message"] == \
        "ClipForge AI could not answer (timeout)."
    shorts.make(_fresh(pid))  # Try again
    _run(env)
    short = _fresh(pid)
    assert short["short"]["stage"] == "review" and short["status"] == "needs_input"
    assert not env["calls"].speak  # nothing was made before the owner checked the script
    scene = _scenes(pid)[0]
    shorts.update_scene(_fresh(pid), scene["id"], {"narration": "Why is the sea salty, if rain is fresh?"})
    assert _fresh(pid)["status"] == "needs_input"  # still waiting for the owner, not "building"
    _run(env)
    shorts.make(_fresh(pid))
    _run(env)
    assert _fresh(pid)["status"] == "ready" and env["calls"].speak


def test_a_build_overtaken_by_a_change_saves_no_version_of_its_own(env):
    from clipfoundry import db
    from clipfoundry.makers import shorts

    project = shorts.create("local", "local", name="", options={"mode": "paste", "script": SCRIPT})
    pid = project["id"]
    last = _scenes(pid)[-1]
    env["calls"].during_clip = lambda: shorts.update_scene(_fresh(pid), last["id"],
                                                           {"narration": "Their blood is blue, thanks to copper."})
    _run(env)
    short = _fresh(pid)
    assert short["plan_revision"] == 1 and short["short"]["stage"] == "ready" and short["status"] == "ready"
    previews = db.select("studio_jobs", "target_id = ? AND kind = 'video_preview'", (pid,))
    assert [p["revision"] for p in previews] == [1]  # one preview, of the short as it is now
    plan = _plan(pid)
    assert last["id"] in [c.get("scene_id") for c in plan["clips"]]


def test_picture_ideas_never_overwrite_what_the_owner_typed_meanwhile(env, monkeypatch):
    from clipfoundry.makers import shorts, writer

    monkeypatch.setattr(writer, "ready", lambda settings: {"configured": True, "label": "Built-in AI", "local": True})
    project = shorts.create("local", "local", name="", options={"mode": "paste", "script": THREE})
    pid = project["id"]
    one, two, three = _scenes(pid)
    new_words = "Two of the hearts push blood through the gills."

    def picture_ideas(narrations, **kw):  # slow: the owner edits two scenes while it thinks
        shorts.update_scene(_fresh(pid), one["id"], {"picture_prompt": "a lighthouse made of candy"})
        shorts.update_scene(_fresh(pid), two["id"], {"narration": new_words})
        return {"pictures": ["AI idea one", "AI idea two", "AI idea three"], "character": "", "model": "Built-in AI",
                "local": True, "memories": [], "knowhow": []}

    monkeypatch.setattr(writer, "picture_ideas", picture_ideas)
    _run(env)
    rows = {s["id"]: s for s in _scenes(pid)}
    assert (rows[one["id"]]["picture_prompt"], rows[one["id"]]["picture_from"]) == \
        ("a lighthouse made of candy", "owner")
    assert rows[two["id"]]["narration"] == new_words and rows[two["id"]]["picture_from"] == "words"
    assert rows[two["id"]]["picture_prompt"] != "AI idea two"  # made from the words it says now
    assert (rows[three["id"]]["picture_prompt"], rows[three["id"]]["picture_from"]) == ("AI idea three", "ai")


def test_a_stand_in_voice_gets_another_try(env):
    from clipfoundry.makers import shorts

    env["calls"].stand_in = "The chosen voice could not read this scene, so another voice read it."
    project = _make(env, script=THREE)
    pid = project["id"]
    rows = _scenes(pid, _plan(pid))
    assert all((s["info"].get("voice") or {}).get("fallback") for s in rows)
    shown = shorts.view(_fresh(pid))["scenes"]
    assert all(x["voice"]["fallback"] for x in shown)  # so the page can offer Try again
    env["calls"].stand_in = ""  # the chosen voice works again
    spoken = len(env["calls"].speak)
    shorts.update_scene(_fresh(pid), rows[0]["id"], {"again": True})
    _run(env)
    assert len(env["calls"].speak) == spoken + 1
    assert not (_scenes(pid, _plan(pid))[0]["info"].get("voice") or {}).get("fallback")
    shorts.make(_fresh(pid))  # Make the short tries the chosen voice for the others too
    _run(env)
    assert len(env["calls"].speak) == spoken + len(rows)
    assert not any((s["info"].get("voice") or {}).get("fallback") for s in _scenes(pid, _plan(pid)))


def test_errors_reach_the_owner_in_plain_words(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.makers import shorts

    env["calls"].error = OSError(errno.ENOSPC, "No space left on device", "/Users/someone/ClipForge/voice.wav")
    project = shorts.create("local", "local", name="", options={"mode": "paste", "script": THREE})
    pid = project["id"]
    _run(env)
    failed = [s for s in _scenes(pid) if s["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["error"] == "There is not enough free disk space. Free some space, then press Try again."
    env["calls"].error = KeyError("boom")
    shorts.update_scene(_fresh(pid), failed[0]["id"], {"again": True})
    _run(env)
    error = next(s for s in _scenes(pid) if s["id"] == failed[0]["id"])["error"]
    assert error == "Something went wrong while making this scene. Press Try again."

    def broken(*a, **k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(shorts, "_make_scenes", broken)
    shorts.update_scene(_fresh(pid), failed[0]["id"], {"again": True})
    _run(env)
    short = _fresh(pid)
    plain = "Something went wrong while making this short. Press Try again."
    assert short["short"]["stage"] == "failed" and short["short"]["message"] == plain
    assert _job(pid)["error"] == plain  # the job keeps the plain words too (the log keeps the cause)
    assert not any("Error" in (s["error"] or "") for s in _scenes(pid))
    assert db.fetch("studio_projects", pid)["message"] == plain


def test_a_picture_maker_set_up_later_swaps_the_cards_on_one_press(env, monkeypatch):
    from PIL import Image

    from clipfoundry.makers import local_engines, shorts

    project = _make(env, script=THREE)
    pid = project["id"]
    view = shorts.view(_fresh(pid))
    assert view["cards_to_swap"] == 0 and all(x["picture"]["source"] == "card" for x in view["scenes"])
    # this ClipForge has the local makers (clipfoundry/engines), none set up: the note says where to set one up
    assert local_engines.available()
    assert any("no picture maker is set up. Set one up in Settings → Pictures, video, voice" in n
               for n in view["notes"])
    monkeypatch.setattr(local_engines, "module", lambda: None)  # a ClipForge without the local makers
    monkeypatch.setattr(shorts, "_status_cache", {})
    assert any("this ClipForge has no picture maker yet" in n for n in shorts.view(_fresh(pid))["notes"])

    class Engines:
        def status(self, role):
            return {"ready": role == "image", "engine": "Fake pictures", "why": ""}

        def make_image(self, prompt, **kw):
            path = env["tmp"] / f"engine-{kw['seed']}.png"
            Image.new("RGB", (108, 192), "#cc3333").save(path)
            return path

    monkeypatch.setattr(local_engines, "module", lambda: Engines())
    monkeypatch.setattr(shorts, "_status_cache", {})
    view = shorts.view(_fresh(pid))
    assert view["cards_to_swap"] == 3  # the page offers Draw real pictures
    assert any("A picture maker is ready now: press Draw real pictures" in n for n in view["notes"])
    shorts.make(_fresh(pid))
    _run(env)
    view = shorts.view(_fresh(pid))
    assert view["cards_to_swap"] == 0 and all(x["picture"]["source"] == "engine" for x in view["scenes"])
    assert view["stage"] == "ready"


def test_a_clip_thrown_away_is_deleted_and_leftovers_are_tidied(env, monkeypatch):
    import os

    from clipfoundry import db
    from clipfoundry.makers import shorts
    from clipfoundry.studio import uploads

    project = _make(env)
    pid = project["id"]
    scene = _scenes(pid, _plan(pid))[0]
    folder = shorts.short_dir(pid)
    old, recent, part = folder / "tmpleft", folder / "tmpnow", folder / "voice" / "gone.part.wav"
    for p in (old, recent):
        p.mkdir()
        (p / "scene-1.mp4").write_bytes(b"x")
    part.write_bytes(b"x")
    for p in (old, part):  # left by an app that was closed in the middle of a build, two hours ago
        os.utime(p, (time.time() - 7200, time.time() - 7200))
    stored = []
    real = uploads.store_file
    monkeypatch.setattr(uploads, "store_file", lambda *a, **k: stored.append(real(*a, **k)) or stored[-1])
    env["calls"].during_clip = lambda: shorts.update_scene(_fresh(pid), scene["id"],
                                                           {"narration": "Octopuses: three hearts, one body."})
    shorts.update_scene(_fresh(pid), scene["id"], {"narration": "Octopuses have three busy hearts."})
    _run(env)
    clips = [a for a in stored if a["kind"] == "video"]
    assert len(clips) == 2  # one for the words changed while it was made, one for the words now
    thrown, kept = clips
    assert _scenes(pid, _plan(pid))[0]["clip_asset_id"] == kept["id"]
    assert db.fetch("assets", thrown["id"]) is None and not Path(thrown["path"]).exists()
    assert db.fetch("assets", kept["id"]) and Path(kept["path"]).is_file()
    assert not old.exists() and not part.exists() and recent.exists()
    # a thrown-away clip whose bytes are a file already in use stays
    shorts._drop_unused(db.fetch("assets", _scenes(pid, _plan(pid))[1]["clip_asset_id"]), "local")
    assert all(db.fetch("assets", s["clip_asset_id"]) for s in _scenes(pid, _plan(pid)))


def test_the_speech_model_is_released_whenever_it_was_asked(env, monkeypatch):
    from clipfoundry.makers import looks, motion

    _make(env)
    assert env["calls"].released == 0  # nothing listened: nothing to give back
    env["calls"].model_used = True  # it listened, but no scene's word times came from it
    seen = []
    real = motion.still_clip
    monkeypatch.setattr(motion, "still_clip", lambda *a, **k: seen.append(k.get("background")) or real(*a, **k))
    project = _make(env, script=THREE)
    assert env["calls"].released == 1
    assert seen and set(seen) == {looks.get(project["short"]["look"]).bottom}  # see-through pictures lie on it


def test_voice_samples_are_made_once_and_a_stand_in_is_not_kept(env, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import config
    from clipfoundry.api import app
    from clipfoundry.makers import shorts, voice

    real = voice.speak
    started, nested = [], []

    def speak(text, out, **kw):  # a second request for the same voice arrives while the first is being made
        if not started:
            started.append(out)
            nested.append(shorts.voice_sample("espeak:en-us", 1.05))
        return real(text, out, **kw)

    monkeypatch.setattr(voice, "speak", speak)
    path, note = shorts.voice_sample("espeak:en-us", 1.05)
    assert note == "" and path.is_file() and nested and nested[0][0] == path
    spoken = len(env["calls"].speak)
    assert shorts.voice_sample("espeak:en-us", 1.05) == (path, "") and len(env["calls"].speak) == spoken
    folder = config.data_dir() / "shorts" / "samples"
    assert not list(folder.glob("*.part.wav"))

    env["calls"].stand_in = "The chosen voice is not on this computer, so another voice read this."
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        r = api.post("/api/studio/shorts/voice-sample", json={"voice": "espeak:de", "speed": 1.0},
                     headers={"X-ClipFoundry": "1"})
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    assert "another voice" in __import__("urllib.parse").parse.unquote(r.headers["x-clipforge-note"])
    kept = [p for p in folder.glob("*.wav") if not p.name.endswith(".part.wav")]
    assert kept == [path]  # the stand-in's sample was not kept as the chosen voice's
    assert not list(folder.glob("*.part.wav"))  # and its one-time file is gone
    with pytest.raises(shorts.ShortError):
        env["calls"].error = OSError(errno.EIO, "Input/output error", "/tmp/x")
        shorts.voice_sample("espeak:fr", 1.0)
    assert Path(folder).is_dir()

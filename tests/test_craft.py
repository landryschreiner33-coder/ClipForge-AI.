"""FilmCraft and EffectCraft inside ClipForge (clipfoundry/craft): fetching them safely, the edit FilmCraft makes with
its own tools (ClipForge's look and sound, EffectCraft's animated title, the AI's finishing with checked steps and
effect shots), FilmCraft's render of the final video with the built-in editor as the backup, FilmCraft's editor on the
editor page and its saves coming back as new versions. The apps are stand-ins here (programs that answer like
filmcraft-cli and effectcraft-cli and record what they were asked); the real apps are checked on GitHub's Mac and
Linux machines (.github/workflows/filmcraft-check.yml, scripts/filmcraft_check.py).
"""
from __future__ import annotations

import io
import json
import os
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from tests.test_studio_filmcraft import H, _video, env  # noqa: F401 - env is the shared fixture

REPO = Path(__file__).resolve().parents[1]
linux_only = pytest.mark.skipif(sys.platform in ("win32", "darwin"), reason="the stand-ins are started as programs")

FAKE_FILM = r'''
import json, subprocess, sys
from pathlib import Path
from urllib.parse import unquote, urlparse
sys.path.insert(0, REPO)
from clipfoundry.studio import interchange

args = [a for a in sys.argv[1:] if a != "--compact"]
log = Path(LOG)
fail = set(json.loads(FAIL))


def say(x):
    print(json.dumps(x))


def record(entry):
    with log.open("a") as f:
        f.write(json.dumps(entry) + "\n")


if args == ["--version"]:
    print("filmcraft-cli 0.17.1")
    sys.exit(0)
if args[0] == "import":
    out = Path(args[args.index("--save-as") + 1])
    files = args[1:args.index("--save-as")]
    otio = json.loads(Path(next(f for f in files if f.endswith(".otio"))).read_text())
    n, tracks, media = 0, {"video": [], "audio": []}, []
    for t in otio["tracks"]["children"]:
        items = []
        for p in interchange.placements(t):
            n += 1
            items.append({"clip": n, "startFrame": p["start"], "durationFrames": p["frames"]})
            ref = (p["clip"].get("media_references") or {}).get("DEFAULT_MEDIA") or {}
            if ref.get("target_url", "").startswith("file://"):
                media.append({"File": {"path": unquote(urlparse(ref["target_url"]).path)}})
        tracks["video" if t["kind"] == "Video" else "audio"].append({"name": t["name"], "items": items})
    s = otio["metadata"]["filmcraft"]["settings"]
    doc = {"settings": {"width": s["width"], "height": s["height"], "fps": s["frame_rate"]["num"]},
           "tracks": tracks, "media": media, "next": 1000, "log": []}
    out.write_text(json.dumps(doc))
    record({"cmd": "import", "files": files})
    say({"documents": [{"path": str(out), "offlineMedia": []}], "items": []})
    sys.exit(0)
if args[0] == "commands":
    say([{"id": i, "label": i, "params": "{...}"} for i in
         ("effects.setParam", "effects.apply", "lumetri.applyPreset", "file.import", "timeline.razor")])
    sys.exit(0)
if args[:2] == ["inspect", "sequence"]:
    say(json.loads(Path(args[args.index("--project") + 1]).read_text())["tracks"])
    sys.exit(0)
project = Path(args[1])
rest = [a for a in args[2:] if a not in ("--save", "--gpu-rendering", "off")]
save = "--save" in args
doc = json.loads(project.read_text())
if rest[0] == "run":
    for n, line in enumerate(Path(rest[1]).read_text().splitlines(), 1):
        step = json.loads(line)
        ok = step["id"] not in fail
        doc["log"].append(step)
        say({"line": n, "id": step["id"], "ok": ok, **({"result": {}} if ok else {"error": "unknown parameter"})})
    record({"cmd": "run", "steps": len(doc["log"])})
elif rest[0] == "exec":
    cmd, params = rest[1], json.loads(rest[2])
    record({"cmd": cmd, "params": params})
    if cmd == "file.import":
        doc["next"] += 1
        doc["media"] += [{"File": {"path": p}} for p in params["paths"]]
        say({"items": [doc["next"]], "errors": []})
    elif cmd == "file.exportMedia":
        st = doc["settings"]
        frames = max((i["startFrame"] + i["durationFrames"] for t in doc["tracks"]["video"] for i in t["items"]),
                     default=30)
        secs = frames / st["fps"]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c=black:s={st['width']}x{st['height']}:r={st['fps']}", "-f", "lavfi", "-i",
                        "sine=frequency=440:sample_rate=48000", "-t", f"{secs:.6f}", "-c:v", "libx264", "-pix_fmt",
                        "yuv420p", "-c:a", "aac", "-ac", "2", params["path"]], check=True)
        say({"job": 1, "state": "done"})
    elif cmd == "effects.list":
        say({"effects": [{"id": "gaussian_blur"}, {"id": "glow"}]})
    elif cmd == "lumetri.presets":
        say({"presets": [{"name": "Warm"}, {"folder": "Cinematic", "name": "Teal Shadows, Warm Skin"}]})
    else:
        say({"ok": True})
if save:
    project.write_text(json.dumps(doc))
'''

FAKE_EFFECT = r'''
import json, sys
from pathlib import Path
args = sys.argv[1:]
with Path(LOG).open("a") as f:
    f.write(json.dumps(args) + "\n")
if args[0] == "script":
    Path(args[args.index("--save-as") + 1]).write_text(json.dumps({"script": Path(args[1]).read_text()}))
    print(json.dumps({"ok": True, "result": "ok"}))
elif args[0] == "render":
    Path(args[args.index("--out") + 1]).write_bytes(b"shot")
    print(json.dumps({"ok": True, "frames": 30}))
'''


def _program(path: Path, body: str, **values) -> str:
    head = f"#!{sys.executable}\n" + "".join(f"{k} = {json.dumps(str(v) if not isinstance(v, str) else v)}\n"
                                             for k, v in values.items())
    path.write_text(head + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture()
def tools(env, monkeypatch):  # noqa: F811
    folder = env / "stand-ins"
    folder.mkdir()
    logs = {"film": folder / "filmcraft.log", "effect": folder / "effectcraft.log"}
    film = _program(folder / "filmcraft-cli", FAKE_FILM, REPO=str(REPO), LOG=str(logs["film"]), FAIL="[]")
    effect = _program(folder / "effectcraft-cli", FAKE_EFFECT, LOG=str(logs["effect"]))
    monkeypatch.setenv("CLIPFOUNDRY_FILMCRAFT_CLI", film)
    monkeypatch.setenv("CLIPFOUNDRY_EFFECTCRAFT_CLI", effect)
    return {"folder": folder, "logs": logs, "film": film, "effect": effect}


def _inputs(project: dict):
    from clipfoundry import db
    from clipfoundry.studio import video_flow

    plan = video_flow.plan_at(project["id"], project["plan_revision"])
    assets = video_flow._assets(project, plan)
    words = {aid: video_flow.transcript_words(a, db.get_settings(), cached_only=True) for aid, a in assets.items()
             if a["kind"] == "video"}
    return plan, assets, words


def _log(path: Path) -> list:
    return [json.loads(x) for x in path.read_text().splitlines()] if path.is_file() else []


# ------------------------------------------------------------------ fetching the apps
def test_pinned_releases_cover_every_platform_with_checksums():
    from clipfoundry.craft import apps

    for app in apps.APPS.values():
        assert set(app.files) >= {"macos", "linux-x86_64", "linux-aarch64", "windows-x64", "windows-arm64"}
        for name, sha, size in app.files.values():
            assert len(sha) == 64 and int(sha, 16) >= 0 and 1 << 20 < size < apps.MAX_DOWNLOAD
            assert app.version in name
        assert app.url(app.files["macos"][0]).startswith(f"https://github.com/{app.repo}/releases/download/v")
    assert "web" in apps.APPS["filmcraft"].files


def _zip(path: Path, entries: dict, link: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o100755 if name.endswith("-cli") else 0o100644) << 16
            z.writestr(info, data)
        if link:
            info = zipfile.ZipInfo(link)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "/etc/passwd")
    return path


def test_unpacking_refuses_files_outside_the_folder_and_links(tmp_path):
    from clipfoundry.craft import apps

    ok = _zip(tmp_path / "ok.zip", {"bin/filmcraft-cli": b"#!", "share/readme.txt": b"hi"})
    apps._unpack(ok, (tmp_path / "a").resolve())
    assert (tmp_path / "a/bin/filmcraft-cli").stat().st_mode & 0o111
    with pytest.raises(apps.CraftUnavailable, match="outside"):
        apps._unpack(_zip(tmp_path / "slip.zip", {"../../evil": b"x"}), tmp_path / "b")
    with pytest.raises(apps.CraftUnavailable, match="link"):
        apps._unpack(_zip(tmp_path / "link.zip", {"x": b"1"}, link="bin/ls"), tmp_path / "c")
    tgz = tmp_path / "t.tar.gz"
    with tarfile.open(tgz, "w:gz") as t:
        info = tarfile.TarInfo("../../evil")
        info.size = 1
        t.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(apps.CraftUnavailable, match="outside"):
        apps._unpack(tgz, tmp_path / "d")
    assert not (tmp_path.parent / "evil").exists()


def test_install_checks_the_download_and_only_then_replaces(env, monkeypatch):  # noqa: F811
    from clipfoundry.craft import apps

    plat = apps.platform_key()
    if not plat:
        pytest.skip("no release for this machine")
    payload = _zip(env / "release.zip", {"filmcraft-cli-0.17.1/bin/filmcraft-cli": b"#!/bin/sh\n"})
    data = payload.read_bytes()
    import hashlib

    app = apps.APPS["filmcraft"]
    fake = apps.App(**{**app.__dict__, "files": {**app.files, plat: ("release.zip", hashlib.sha256(data).hexdigest(),
                                                                     len(data))}})
    monkeypatch.setitem(apps.APPS, "filmcraft", fake)

    def download(url, dest, sha256, size, progress, cancelled):
        assert url == fake.url("release.zip")
        dest.write_bytes(data)
        progress(len(data))

    monkeypatch.setattr(apps, "_download", download)
    got = apps.install_part("filmcraft", plat)
    assert Path(got["abs"]).name == "filmcraft-cli" and Path(got["abs"]).parent.name == "bin"
    monkeypatch.delenv("CLIPFOUNDRY_FILMCRAFT_CLI", raising=False)
    assert apps.find_cli("filmcraft")["source"] == "clipforge"
    # a download that does not unpack to the tool leaves the working install alone
    bad = _zip(env / "bad.zip", {"nothing.txt": b"x"}).read_bytes()
    monkeypatch.setitem(apps.APPS, "filmcraft", apps.App(**{**fake.__dict__, "version": "0.17.2", "files": {
        **fake.files, plat: ("bad.zip", hashlib.sha256(bad).hexdigest(), len(bad))}}))
    monkeypatch.setattr(apps, "_download", lambda url, dest, *a: dest.write_bytes(bad))
    with pytest.raises(apps.CraftUnavailable, match="command-line tool was not in the download"):
        apps.install_part("filmcraft", plat)
    assert Path(got["abs"]).is_file()
    assert not list(apps.tools_root().glob(".*.part"))


def test_the_online_studio_never_fetches_programs(env, monkeypatch):  # noqa: F811
    from clipfoundry.craft import apps

    monkeypatch.setattr(apps.cloud_settings, "enabled", lambda: True)
    with pytest.raises(apps.CraftUnavailable, match="operator"):
        apps.install()
    assert apps.status()["can_install"] is False


# ------------------------------------------------------------------ the edit in FilmCraft and its render
def test_native_steps_reproduce_clipforge_look_and_sound(env):  # noqa: F811
    from clipfoundry.craft import finish
    from tests.test_studio_filmcraft import _built

    project = _video(env)
    plan, _assets, tl = _built(project)
    seq = {"video": [], "audio": []}
    n = 0
    from clipfoundry.studio import interchange

    for t in tl.otio["tracks"]["children"]:
        items = []
        for p in interchange.placements(t):
            n += 1
            items.append({"clip": n, "startFrame": p["start"], "durationFrames": p["frames"]})
        seq["video" if t["kind"] == "Video" else "audio"].append({"name": t["name"], "items": items})
    clips = finish.match(tl.otio, seq)
    assert all(c["id"] is not None for c in clips)
    steps, notes = finish.native_steps(plan, tl, clips)
    assert not notes
    ids = {(c["track"], c["meta"].get("label") or c["meta"].get("clip_id")): c["id"] for c in clips}
    by = lambda iid: [s for s in steps if s["params"].get("clip") == iid or iid in (s["params"].get("clips") or [])]  # noqa: E731
    swim = next(c for c in clips if c["track"] == "Video 1" and c["meta"].get("clip_id") == "c3")
    scale = next(s for s in by(swim["id"]) if s["params"].get("param") == "scale")["params"]["value"]
    assert scale == pytest.approx(100 * swim["meta"]["cover"] * 1.2, rel=1e-3)  # fill the frame, then the punch-in
    bg = [c for c in clips if c["track"] == "Blurred background"]
    assert bg and all({"effects.apply", "effects.setParam"} <= {s["id"] for s in by(c["id"])} for c in bg)
    welcome = next(c for c in clips if c["track"] == "Video 1" and c["meta"].get("clip_id") == "c1")
    assert not [s for s in by(welcome["id"]) if s["params"].get("param") == "scale"]  # fitted: shown whole
    assert [s["id"] for s in steps if s["for"] == "ducking"] == ["essentialSound.setType", "essentialSound.setType",
                                                                  "essentialSound.set",
                                                                  "essentialSound.generateDucking"]
    style = next(s for s in steps if s["id"] == "captions.setStyle")["params"]
    assert style["track"] == "C1" and style["font"] == "Inter" and 0 < style["margin"] <= 0.45
    over = next(c for c in clips if c["track"] == "Pictures over the video")
    keys = [s["params"] for s in by(over["id"]) if s["params"].get("keyframe")]
    assert {k["effect"] for k in keys} == {"motion", "opacity"}
    assert len(ids) and len(steps) < 80


@linux_only
def test_filmcraft_edits_and_renders_the_final_video(env, tools):  # noqa: F811
    from clipfoundry.craft import finish

    project = _video(env)
    plan, assets, words = _inputs(project)
    out = env / "render" / "r1" / "final.mp4"
    out.parent.mkdir(parents=True)
    seen = []
    info = finish.render(plan, assets, words, out, name="Lake day", revision=1, settings={},
                         progress=lambda f, m: seen.append((f, m)))
    assert out.is_file() and info["engine"] == "filmcraft" and info["has_audio"]
    assert abs(info["duration"] - info["expected_duration"]) <= 0.1
    assert seen and seen[-1][0] < 1 and any("FilmCraft" in m for _f, m in seen)
    report = info["filmcraft"]
    assert report["steps"] > 10 and report["failed"] == [] and report["ai"]["used"] is False
    assert [s["use"] for s in report["shots"]] == ["title"] and report["shots"][0]["app"] == "EffectCraft"
    film = _log(tools["logs"]["film"])
    assert film[0]["cmd"] == "import" and any(f.endswith(".srt") for f in film[0]["files"])
    exported = next(x for x in film if x["cmd"] == "file.exportMedia")["params"]
    assert exported["loudnessLufs"] == -14 and exported["burnCaptions"] is True and exported["wait"] is True
    # the EffectCraft title replaced the still in the edit
    steps = json.loads((out.parent / "filmcraft" / "report.json").read_text())["steps_run"]
    assert any(s["id"] == "clip.replaceFromBin" and s["for"] == "animated title (EffectCraft)" for s in steps)
    effect = _log(tools["logs"]["effect"])
    assert effect[0][0] == "script" and "--empty" in effect[0] and effect[1][:1] == ["render"] and "hq" in effect[1]
    assert effect[1][effect[1].index("--comp") + 1] == "ClipForge Title" and report["shots"][0]["checks"] == "ok"
    script = Path(effect[0][1]).read_text()
    # EffectCraft 0.9 has no layer.property("Source Text"): the title only uses the helpers, which report back
    assert "cfStyle(t, FS" in script and 'property("Source Text")' not in script.split("TITLE")[-1]
    assert script.rstrip().endswith('"ok";')
    # the same plan again reuses the edit the person may have seen in the editor
    n = len(film)
    finish.render(plan, assets, words, out, name="Lake day", revision=1, settings={})
    assert [x["cmd"] for x in _log(tools["logs"]["film"])[n:]] == ["file.exportMedia"]


@linux_only
def test_a_failing_step_is_reported_and_the_rest_still_run(env, tools):  # noqa: F811
    from clipfoundry.craft import finish

    _program(Path(tools["film"]), FAKE_FILM, REPO=str(REPO), LOG=str(tools["logs"]["film"]),
             FAIL='["captions.setStyle"]')
    project = _video(env)
    plan, assets, words = _inputs(project)
    out = env / "r1" / "final.mp4"
    out.parent.mkdir()
    info = finish.render(plan, assets, words, out, name="Lake day", revision=1, settings={})
    assert [f["id"] for f in info["filmcraft"]["failed"]] == ["captions.setStyle"] and out.is_file()


@linux_only
def test_the_ai_finishes_with_checked_filmcraft_tools_and_an_effects_shot(env, tools, monkeypatch):  # noqa: F811
    from clipfoundry.craft import ai as craft_ai
    from clipfoundry.craft import finish
    from clipfoundry.pipeline import llm

    project = _video(env)
    plan, assets, words = _inputs(project)
    asked = {}

    def complete(settings, prompt, *, system=None, task="", **kw):
        asked.update(prompt=prompt, system=system, task=task, kw=kw)
        rows = json.loads(prompt.split("The sequence (FilmCraft clip ids):\n", 1)[1].split("\n", 1)[0])
        clip = next(r["clip"] for r in rows if r["track"] == "Video 1" and r.get("said"))
        return json.dumps({"summary": "Warmer colour and a lower third.", "steps": [
            {"id": "lumetri.applyPreset", "params": {"name": "Warm", "clips": [clip]}, "why": "warmth"},
            {"id": "timeline.razor", "params": {"clip": clip, "frame": 10}, "why": "cut"},
            {"id": "effects.apply", "params": {"clips": [clip], "effect": "glow", "lut": "/etc/passwd"}},
            {"id": "effects.apply", "params": {"clips": [99999], "effect": "glow"}}],
            "shots": [{"name": "Lower third", "at_s": 3, "seconds": 2,
                       "script": "var t = comp.layers.addText('Lake day');"},
                      {"name": "Sneaky", "at_s": 1, "seconds": 1, "script": "system.callSystem('rm -rf /')"}]})

    monkeypatch.setattr(llm, "complete", complete)
    out = env / "r1" / "final.mp4"
    out.parent.mkdir()
    info = finish.render(plan, assets, words, out, name="Lake day", revision=1,
                         settings={"ai_provider": "ollama", "craft_ai_finish": True, "ollama_model": "m"})
    ai = info["filmcraft"]["ai"]
    assert ai["used"] and ai["summary"] == "Warmer colour and a lower third." and ai["steps"] == 1 and ai["shots"] == 1
    assert len(ai["refused"]) == 4 and any("not a finishing tool" in r for r in ai["refused"])
    assert any("file or address" in r for r in ai["refused"]) and any("not in this sequence" in r for r in ai["refused"])
    assert asked["task"] == "filmcraft_finish" and "timeline.razor" not in asked["prompt"]
    # a model on this computer gets a context that holds the request, minutes to answer, and answers in JSON
    assert asked["kw"] == {"num_ctx": 8192, "timeout": 600.0, "json_object": True, "max_tokens": 1200}
    assert asked["prompt"].endswith(craft_ai.SHORT)  # and is asked for a short answer
    assert "/" + "files" not in asked["prompt"] and str(env) not in asked["prompt"]  # never a path
    # FilmCraft's names have commas in them: the lists are JSON
    looks = asked["prompt"].split("Colour looks (for lumetri.applyPreset name): ", 1)[1].split("\n", 1)[0]
    assert json.loads(looks) == ["Warm", "Teal Shadows, Warm Skin"]
    film = _log(tools["logs"]["film"])
    placed = [x for x in film if x["cmd"] == "file.import"]
    assert len(placed) == 2  # the title shot and the AI's lower third
    shots = info["filmcraft"]["shots"]
    assert [s["use"] for s in shots] == ["title", "over the video"] and shots[1]["what"] == "Lower third"
    effect = _log(tools["logs"]["effect"])
    assert any("4444" in a and "rgba" in a for a in effect if a[0] == "render")  # laid over with transparency


class _Timeline:
    width, height, fps, frames, counts = 1080, 1920, 30, 30 * 600, {"captions": 3}


class _Edit:
    timeline = _Timeline()


def test_the_request_fits_a_model_on_this_computer():
    from clipfoundry.craft import ai

    said = "and that is why we went to the lake early in the morning before anyone else got there, " * 3
    rows = []
    for i in range(200):
        track, what = (("Video 1", "video") if i % 2 == 0 else ("Music", "sound") if i % 4 == 1 else
                       ("Pictures over the video", "picture over the video"))
        rows.append({"clip": i + 1, "track": track, "what": what, "from_s": i * 3.0, "to_s": i * 3.0 + 3,
                     **({"said": said[:160]} if track == "Video 1" else {})})
    catalog = [{"id": t, "label": t.split(".")[-1], "params": "p" * 600} for t in sorted(ai.ALLOWED)]
    effects = [f"Effect number {i}, with a long name" for i in range(120)]
    looks = [f"Look {i}, Teal Shadows, Warm Skin" for i in range(60)]
    plan = {"title": {"text": "Lake day"}}
    full = ai.build_prompt(plan, _Edit(), rows, catalog, effects, looks)
    assert len(full) > ai.LOCAL_PROMPT_CHARS and "p" * 600 in full  # an online service gets everything
    short = ai.build_prompt(plan, _Edit(), rows, catalog, effects, looks, ai.LOCAL_PROMPT_CHARS)
    assert len(short) <= ai.LOCAL_PROMPT_CHARS and short.endswith(ai.ANSWER)
    lines = short.split("\n")
    kept = json.loads(lines[lines.index("The sequence (FilmCraft clip ids):") + 1])
    tools = json.loads(lines[lines.index("Tools you may use (id, parameters):") + 1])
    assert kept and all(r["track"] == "Video 1" for r in kept)  # the main video's clips come first
    assert [r["from_s"] for r in kept] == sorted(r["from_s"] for r in kept)  # in their order
    assert {t["id"] for t in tools} == ai.ALLOWED  # every tool is still offered
    looks_sent = json.loads(next(x for x in lines if x.startswith("Colour looks")).split(": ", 1)[1])
    assert looks_sent and looks_sent[0] == looks[0]  # whole names, commas and all
    # a short request is not changed
    few = ai.build_prompt(plan, _Edit(), rows[:6], catalog[:3], effects[:3], looks[:3], ai.LOCAL_PROMPT_CHARS)
    assert few == ai.build_prompt(plan, _Edit(), rows[:6], catalog[:3], effects[:3], looks[:3])
    assert ai.prompt_limit({"ai_provider": "builtin"}) == ai.LOCAL_PROMPT_CHARS
    assert ai.prompt_limit({"ai_provider": "ollama"}) == ai.LOCAL_PROMPT_CHARS
    assert ai.prompt_limit({"ai_provider": "ollama", "ollama_url": "https://ai.example.com"}) == ai.REMOTE_PROMPT_CHARS
    assert ai.prompt_limit({"ai_provider": "anthropic"}) == ai.REMOTE_PROMPT_CHARS


def test_the_built_in_ai_finishes_the_edit_once_it_is_downloaded(monkeypatch):
    from clipfoundry import builtin_ai
    from clipfoundry.craft import ai, finish
    from clipfoundry.pipeline import llm

    def never(*_a, **_k):
        raise AssertionError("nothing is sent before the built-in AI is downloaded")

    monkeypatch.setattr(llm, "complete", never)
    monkeypatch.setattr(builtin_ai, "ready", lambda _s: False)
    s = {"ai_provider": "builtin", "craft_ai_finish": True}
    got = ai.finish(None, None, None, {}, {}, s)
    assert got == {"used": False, "why": "the built-in AI is not downloaded yet"}
    plan = {"version": 3, "clips": []}
    before = finish.edit_key(plan, s)
    assert before == finish.edit_key(plan, {"ai_provider": "heuristic"})
    monkeypatch.setattr(builtin_ai, "ready", lambda _s: True)
    monkeypatch.setattr(builtin_ai, "chosen_level", lambda _s: "basic")
    basic = finish.edit_key(plan, s)
    monkeypatch.setattr(builtin_ai, "chosen_level", lambda _s: "standard")
    assert len({before, basic, finish.edit_key(plan, s)}) == 3  # downloading it, or another level, edits again
    assert ai.disclosure(s).startswith("Stays on this computer")


def test_a_slow_local_answer_can_be_cancelled(monkeypatch):
    import threading
    import time

    from clipfoundry.craft import ai
    from clipfoundry.pipeline import llm
    from clipfoundry.studio.jobs import Canceled

    release = threading.Event()
    monkeypatch.setattr(llm, "complete", lambda *_a, **_k: release.wait(20) and "{}")
    t0 = time.monotonic()
    try:
        with pytest.raises(Canceled):
            ai.ask({"ai_provider": "builtin"}, "prompt", cancelled=lambda: True)
        assert time.monotonic() - t0 < 5
    finally:
        release.set()
    monkeypatch.setattr(llm, "complete", lambda *_a, **_k: '{"steps": []}')
    assert ai.ask({}, "prompt") == '{"steps": []}'


def test_the_built_in_ai_gets_the_wait_and_json_answer_it_is_asked_for(monkeypatch):
    from clipfoundry import builtin_ai
    from clipfoundry.pipeline import llm

    seen = []
    monkeypatch.setattr(builtin_ai, "chat", lambda _s, _sys, _p, **kw: seen.append(kw) or "{}")
    llm.complete({"ai_provider": "builtin"}, "x", task="filmcraft_finish", timeout=600, json_object=True,
                 max_tokens=1500)
    llm.complete({"ai_provider": "builtin"}, "x")
    assert seen == [{"timeout": 600.0, "json_object": True, "max_tokens": 1500},
                    {"timeout": 180.0, "json_object": False, "max_tokens": None}]


def test_a_cut_off_answer_gives_the_steps_it_finished():
    from clipfoundry.craft import ai

    step = {"id": "lumetri.applyPreset", "params": {"name": "Teal Shadows, Warm Skin", "clips": [3]}, "why": "w"}
    raw = json.dumps({"summary": "Warmer.", "steps": [step, step, {"id": "effects.apply"}]})
    got = ai.parse(raw[:raw.rindex('{"id": "effects.apply"') + 12])  # stops in the middle of the third step
    assert got == {"summary": "Warmer.", "steps": [step, step], "cut_off": True}
    ok, refused = ai.check_steps(got["steps"], {3})
    assert len(ok) == 1 and refused == ["step 2: the same as an earlier step"]  # a repeated step runs once
    assert ai.parse(raw) == json.loads(raw) and "cut_off" not in ai.parse(raw)
    for bad in ('{"summary": "Warmer.", "steps": [{"id": "lum', "no json here", '["a list"]'):
        with pytest.raises(ValueError):
            ai.parse(bad)


def test_a_step_with_a_parameter_filmcraft_lacks_runs_again_without_it():
    from clipfoundry.craft import ai

    class Film:
        def __init__(self):
            self.ran = []

        def run_steps(self, _project, steps):
            out = []
            for st in steps:
                self.ran.append(st)
                p = st["params"]
                if "duration" in (p.get("params") or {}):
                    out.append({"id": st["id"], "ok": False, "error": "`Cross Dissolve` has no param `duration`"})
                elif "speed" in p:
                    out.append({"id": st["id"], "ok": False, "error": "invalid parameters: has no param `speed`"})
                elif p.get("param") == "opacity":
                    out.append({"id": st["id"], "ok": False, "error": "no param `opacity`"})
                else:
                    out.append({"id": st["id"], "ok": True, "error": ""})
            return out

    film = Film()
    steps = [{"id": "sequence.applyVideoTransition", "params": {"clip": 3, "effect": "Cross Dissolve",
                                                                 "params": {"duration": 30}}, "for": "AI: soft"},
             {"id": "graphics.newText", "params": {"text": "Hi", "speed": 2}, "for": "AI: title"},
             {"id": "effects.setParam", "params": {"clip": 3, "effect": "motion", "param": "opacity"}, "for": "AI"},
             {"id": "markers.add", "params": {"frame": 3}, "for": "AI: mark"}]
    ran, results = ai.run_checked(film, "p", steps)
    assert [r["ok"] for r in results] == [True, True, False, True]
    assert ran[0]["params"] == {"clip": 3, "effect": "Cross Dissolve"} and ran[0]["for"] == "AI: soft (without `duration`)"
    assert ran[1]["params"] == {"text": "Hi"} and ran[2] == steps[2] and len(film.ran) == 6  # 4, then 2 again
    assert ai.without_unknown(steps[2], "`Motion` has no param `clip`") is None  # never without what it acts on
    assert ai.without_unknown(steps[3], "some other error") is None


def test_shot_scripts_cannot_use_files_programs_or_the_network(tmp_path):
    from clipfoundry.craft import shots
    from clipfoundry.craft.runner import CraftError, EffectCraft

    for body in ("system.callSystem('ls')", "var f = new File('/etc/hosts')", "$.evalFile('/x.jsx')",
                 "#include '/x.jsx'", "app.project.save()", "app.project.renderQueue.render()", ""):
        with pytest.raises(CraftError):
            shots.script_shot(EffectCraft("/nonexistent"), tmp_path, "x", body, 1080, 1920, 30, 2)
    assert '"\\u2028"' in shots._js("\u2028") and shots._js('a"b') == '"a\\"b"'


def test_ai_steps_are_checked_before_they_run():
    from clipfoundry.craft import ai

    ok, refused = ai.check_steps([
        {"id": "effects.setParam", "params": {"clip": 3, "effect": "motion", "param": "scale", "value": 110}},
        {"id": "file.exportMedia", "params": {"path": "/tmp/x.mp4"}},
        {"id": "graphics.newText", "params": {"text": "C:\\Windows\\system32"}},
        {"id": "graphics.newText", "params": {"text": "Lake day", "url": "x"}},
        {"id": "effects.apply", "params": {"clips": [3, 4], "effect": "glow"}},
        "nonsense"], {3})
    assert [s["id"] for s in ok] == ["effects.setParam"]
    assert len(refused) == 5
    many, over = ai.check_steps([{"id": "markers.add", "params": {"frame": i}} for i in range(50)], set())
    assert len(many) == ai.MAX_STEPS and "over the limit" in over[-1]
    assert ai._safe({"text": "one/two", "n": 3}) and not ai._safe({"text": "https://x.y"})
    assert not ai._safe({"name": "../../x"}) and not ai._safe({"name": "~/x"})


# ------------------------------------------------------------------ the render job: FilmCraft first, built-in as backup
class _Lease:
    def __init__(self):
        self.reports = []

    def progress(self, frac, message=""):
        self.reports.append((frac, message))

    def canceled(self):
        return False

    def alive(self):
        return True


def test_final_render_engine_choice_and_backup(env, monkeypatch):  # noqa: F811
    from clipfoundry.craft import apps, finish
    from clipfoundry.craft.runner import CraftError
    from clipfoundry.studio import video_flow

    project = _video(env)
    plan, assets, words = _inputs(project)
    job = {"revision": 1}
    out = env / "final.mp4"
    args = (project, job, plan, assets, words, out)
    monkeypatch.setattr(apps, "find_cli", lambda key: None)
    assert video_flow._craft_render(*args, {"edit_engine": "auto"}, _Lease(), False) == (None, "")
    with pytest.raises(video_flow.VideoError, match="not set up"):
        video_flow._craft_render(*args, {"edit_engine": "filmcraft"}, _Lease(), False)
    monkeypatch.setattr(apps, "find_cli", lambda key: {"path": "/x", "version": "", "source": "env"})
    monkeypatch.setattr(finish, "render", lambda *a, **k: {"engine": "filmcraft"})
    assert video_flow._craft_render(*args, {"edit_engine": "auto"}, _Lease(), False) == ({"engine": "filmcraft"}, "")
    assert video_flow._craft_render(*args, {"edit_engine": "ffmpeg"}, _Lease(), False) == (None, "")
    assert video_flow._craft_render(*args, {"edit_engine": "auto"}, _Lease(), True) == (None, "")  # previews: quick

    def broken(*a, **k):
        raise CraftError("FilmCraft drew 'media not found'")

    monkeypatch.setattr(finish, "render", broken)
    info, why = video_flow._craft_render(*args, {"edit_engine": "auto"}, _Lease(), False)
    assert info is None and "media not found" in why and "built-in editor" in why
    with pytest.raises(CraftError):
        video_flow._craft_render(*args, {"edit_engine": "filmcraft"}, _Lease(), False)


def test_edit_engine_setting_is_checked():
    from clipfoundry import config

    assert config.validate_settings({"edit_engine": "filmcraft"}) == {"edit_engine": "filmcraft"}
    assert config.validate_settings({"edit_engine": "premiere"}) == {}
    assert config.DEFAULT_SETTINGS["edit_engine"] == "auto" and config.DEFAULT_SETTINGS["craft_ai_finish"] is True


# ------------------------------------------------------------------ FilmCraft's editor on the editor page
def test_web_session_serves_only_the_projects_files_and_saves_map_back(tmp_path):
    from clipfoundry.craft import web
    from clipfoundry.craft.runner import CraftError

    media = tmp_path / "media"
    media.mkdir()
    a, b = media / "talk one.mp4", media / "shot.mov"
    a.write_bytes(b"aaa")
    b.write_bytes(b"bb")
    project = tmp_path / "edit.fcproj"
    project.write_text(json.dumps({"media": [{"File": {"path": str(a)}}, {"File": {"path": str(b)}},
                                             {"File": {"path": str(a)}}], "title": "Lake / day"}))
    manifest = tmp_path / "web-r1.json"
    got = web.session(project, manifest, "/api/x/files")
    assert [m["name"] for m in got["media"]] == ["01-talk-one.mp4", "02-shot.mov"]
    assert got["media"][0]["url"] == "/api/x/files/01-talk-one.mp4" and got["media"][0]["bytes"] == 3
    webdoc = json.loads(manifest.with_suffix(".fcproj").read_text())
    assert [m["File"]["path"] for m in webdoc["media"]] == ["/files/01-talk-one.mp4", "/files/02-shot.mov",
                                                            "/files/01-talk-one.mp4"]
    assert str(tmp_path) not in json.dumps(webdoc) and webdoc["title"] == "Lake / day"
    assert web.media_file(manifest, "01-talk-one.mp4") == a.resolve()
    assert web.media_file(manifest, "../edit.fcproj") is None and web.media_file(manifest, str(a)) is None
    # a save maps the editor's names back to this computer's files
    webdoc["media"].append({"File": {"path": "/files/01-talk-one.mp4"}})
    clean, need = web.accept(json.dumps(webdoc).encode(), manifest)
    assert not need and json.loads(clean)["media"][-1]["File"]["path"] == str(a.resolve())
    # a file the person added in the editor must be sent first
    webdoc["media"].append({"File": {"path": "/files/logo.png"}})
    clean, need = web.accept(json.dumps(webdoc).encode(), manifest)
    assert clean is None and need == ["logo.png"]
    received = tmp_path / "upload.part"
    received.write_bytes(b"png")
    web.add_file(manifest, tmp_path / "added", "logo.png", received)
    clean, need = web.accept(json.dumps(webdoc).encode(), manifest)
    assert not need and json.loads(clean)["media"][-1]["File"]["path"].endswith("-logo.png")
    # anything else that names a file or an address is refused
    for bad in ("/etc/passwd", "C:\\Users\\x\\a.mp4", "file:///etc/hosts", "https://example.com/a.mp4",
                "~/.ssh/id_rsa", "\\\\server\\share\\a.mp4"):
        with pytest.raises(CraftError, match="outside this video's files"):
            web.accept(json.dumps({"media": [{"File": {"path": bad}}]}).encode(), manifest)
    for name in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(CraftError):
            web.clean_name(name)
    with pytest.raises(CraftError, match="not a FilmCraft project"):
        web.accept(b"\x00\x01PK", manifest)
    assert web.accept(json.dumps({"export": "/exports/v.mp4"}).encode(), manifest)[0]


def test_hand_finished_versions_render_from_the_save_and_later_edits_start_again(env, monkeypatch):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.craft import web
    from clipfoundry.studio import video_flow

    project = _video(env)
    digest, _p = web.store_save(video_flow.filmcraft_saves(project["id"]), b'{"tracks": {}}')
    made = video_flow.save_filmcraft(project["id"], 1, digest, 1)
    assert made["revision"] == 2
    plan = video_flow.plan_at(project["id"], 2)
    assert plan["filmcraft"]["project"] == digest and plan["filmcraft"]["opened_on"] == 1
    assert video_flow.plan_hash(plan) != video_flow.plan_hash(video_flow.plan_at(project["id"], 1))
    jobs = db.select("studio_jobs", "target_id = ? AND kind = 'video_preview' AND revision = 2", (project["id"],))
    assert jobs  # its preview is rendered (by FilmCraft)
    # the same save again changes nothing; a conflict is refused
    assert video_flow.save_filmcraft(project["id"], 2, digest, 2)["unchanged"]
    with pytest.raises(video_flow.Conflict):
        video_flow.save_filmcraft(project["id"], 1, digest, 1)
    # undo and redo keep versions as they were; any other edit starts again from ClipForge's cut
    video_flow.undo(project["id"], 2)
    assert "filmcraft" not in video_flow.plan_at(project["id"], 3)
    video_flow.redo(project["id"], 3)
    assert video_flow.plan_at(project["id"], 4)["filmcraft"]["project"] == digest
    rev = video_flow.save_revision(project["id"], video_flow.plan_at(project["id"], 4), "Trimmed", 4)
    assert "filmcraft" not in video_flow.plan_at(project["id"], rev)
    # a hand-finished version is rendered only by FilmCraft: without it, the render says so
    from clipfoundry.craft import apps

    monkeypatch.setattr(apps, "find_cli", lambda key: None)
    p4 = video_flow.plan_at(project["id"], 4)
    with pytest.raises(video_flow.VideoError, match="finished in FilmCraft's editor"):
        video_flow._craft_render(project, {"revision": 4}, p4, {}, {}, env / "x.mp4", {"edit_engine": "ffmpeg"},
                                 _Lease(), True)


@linux_only
def test_a_tool_still_running_when_clipforge_quits_is_stopped(env):  # noqa: F811
    import threading
    import time

    from clipfoundry.craft import runner

    # the tool starts a helper of its own, which must stop too
    slow = _program(env / "slow-cli", "import subprocess, sys, time\n"
                    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                    "open(PIDFILE, 'w').write(str(child.pid))\ntime.sleep(60)\n", PIDFILE=str(env / "child.pid"))
    got = {}
    t = threading.Thread(target=lambda: got.update(done=runner.call(slow, [], timeout=120)))
    t0 = time.monotonic()
    t.start()
    while not (env / "child.pid").is_file() and time.monotonic() - t0 < 20:
        time.sleep(0.05)
    assert runner._RUNNING
    child = int((env / "child.pid").read_text())
    try:
        runner.stop_all()  # what ClipForge does when it quits
        t.join(timeout=10)
        assert not t.is_alive() and got["done"].returncode != 0 and time.monotonic() - t0 < 30
        assert not runner._RUNNING
        for _ in range(100):  # the helper is gone too (a zombie until its parent's parent reaps it counts as gone)
            try:
                os.kill(child, 0)
                state = Path(f"/proc/{child}/stat").read_text().split()[2] if Path(f"/proc/{child}").exists() else "Z"
                if state == "Z":
                    break
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the tool's helper kept running")
        with pytest.raises(runner.CraftError, match="quitting"):  # and nothing new starts
            runner.call(slow, [], timeout=5)
    finally:
        runner._CLOSING.clear()


@linux_only
def test_the_server_stopping_stops_running_tools(env):  # noqa: F811
    """uvicorn ends a server stopped by a signal by raising the signal again, so atexit never runs: the app's own
    shutdown stops the tools."""
    import threading
    import time

    from fastapi.testclient import TestClient

    from clipfoundry.api import app
    from clipfoundry.craft import runner

    slow = _program(env / "slow-cli", "import time\ntime.sleep(60)\n")
    got = {}
    t = threading.Thread(target=lambda: got.update(done=runner.call(slow, [], timeout=120)))
    with TestClient(app, base_url="http://127.0.0.1:8765"):
        t.start()
        t0 = time.monotonic()
        while not runner._RUNNING and time.monotonic() - t0 < 10:
            time.sleep(0.05)
        assert runner._RUNNING
    t.join(timeout=10)
    assert not t.is_alive() and got["done"].returncode != 0 and not runner._CLOSING.is_set()


def test_an_effectcraft_without_empty_for_scripts_runs_the_script_in_its_own_project(env):  # noqa: F811
    from clipfoundry.craft import runner

    log = env / "old-effect.log"
    old = _program(env / "old-effectcraft-cli", r'''
import json, sys
from pathlib import Path
args = sys.argv[1:]
with Path(LOG).open("a") as f:
    f.write(json.dumps(args) + "\n")
if "--empty" in args:
    print("error: unexpected argument --empty", file=sys.stderr)
    sys.exit(2)
Path(args[args.index("--save-as") + 1]).write_text("{}")
print(json.dumps({"result": "ok"}))
''', LOG=str(log))
    js = env / "shot.jsx"
    js.write_text("1;")
    got = runner.EffectCraft(old).script(js, env / "shot.ecproj")
    calls = _log(log)
    assert got["result"] == "ok" and len(calls) == 2 and "--empty" in calls[0] and "--empty" not in calls[1]
    # a script that fails is reported, never run a second time
    bad = _program(env / "bad-effectcraft-cli", r'''
import json, sys
from pathlib import Path
with Path(LOG).open("a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
print(json.dumps({"error": {"line": 9, "message": "TypeError"}}))
sys.exit(1)
''', LOG=str(env / "bad.log"))
    with pytest.raises(runner.CraftError, match="TypeError"):
        runner.EffectCraft(bad).script(js, env / "shot.ecproj")
    assert len(_log(env / "bad.log")) == 1


@linux_only
def test_editor_page_flow_open_files_save_and_the_web_build(env, tools, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.craft import apps
    from clipfoundry.studio import jobs, video_flow

    project = _video(env)
    vid = project["id"]
    web_dir = env / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<!doctype html><title>FilmCraft</title>")
    (web_dir / "filmcraft_web_bg.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
    (env / "secret.txt").write_text("no")
    monkeypatch.setattr(apps, "web_root", lambda key: web_dir)
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        st = api.get("/api/craft", headers=H).json()
        assert st["editor"] and st["engine"] == "auto" and {a["key"] for a in st["apps"]} == {"filmcraft",
                                                                                             "effectcraft"}
        r = api.get("/craft/filmcraft/index.html")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        r = api.get("/craft/filmcraft/filmcraft_web_bg.wasm")
        assert r.headers["content-type"] == "application/wasm"
        for path in ("/craft/filmcraft/../secret.txt", "/craft/filmcraft/%2e%2e/secret.txt",
                     "/craft/filmcraft/..%2fsecret.txt", "/craft/filmcraft/%2fetc%2fpasswd"):
            r = api.get(path)
            assert r.text != "no" and "root:" not in r.text
        # not made yet: the page asks FilmCraft (and the AI) to make the edit
        s = api.get(f"/api/studio/videos/{vid}/filmcraft/editor", headers=H).json()
        assert s["ready"] is False and s["editor_ready"] and s["cli_ready"]
        r = api.post(f"/api/studio/videos/{vid}/filmcraft/prepare", json={"revision": 1}, headers=H).json()
        job = db.select("studio_jobs", "target_id = ? AND kind = 'filmcraft_edit'", (vid,))[0]
        lease = jobs.claim(job["id"])
        video_flow.filmcraft_edit_job(job, lease)
        s = api.get(f"/api/studio/videos/{vid}/filmcraft/editor", headers=H).json()
        assert s["ready"] and s["steps"] > 10 and s["shots"][0]["app"] == "EffectCraft" and s["media"]
        doc = json.loads(api.get(s["project"], headers=H).content)
        names = [m["name"] for m in s["media"]]
        f = api.get(s["media"][0]["url"] + s["media_query"], headers=H)
        assert f.status_code == 200 and f.content == b"x"
        assert api.get(f"/api/studio/videos/{vid}/filmcraft/files/nope.mp4?revision=1", headers=H).status_code == 404
        assert all(m["File"]["path"].startswith("/files/") for m in doc["media"]) and names
        # the person saves in FilmCraft: a file they added is asked for, then it becomes version 2
        doc["media"].append({"File": {"path": "/files/my logo.png"}})
        body = json.dumps(doc).encode()
        r = api.post(f"/api/studio/videos/{vid}/filmcraft/save?revision=1&base=1", content=body, headers=H)
        assert r.status_code == 409 and r.json() == {"need": ["my logo.png"]}
        r = api.post(f"/api/studio/videos/{vid}/filmcraft/files/my%20logo.png?revision=1", content=b"PNG", headers=H)
        assert r.json() == {"name": "my logo.png", "bytes": 3}
        r = api.post(f"/api/studio/videos/{vid}/filmcraft/save?revision=1&base=1", content=body, headers=H)
        assert r.status_code == 200 and r.json()["revision"] == 2
        plan = video_flow.plan_at(vid, 2)
        saved = video_flow.filmcraft_saves(vid) / f"{plan['filmcraft']['project']}.fcproj"
        kept = json.loads(saved.read_text())
        assert all(Path(m["File"]["path"]).is_file() for m in kept["media"])
        # a save naming any other file is refused, and nothing is made
        doc["media"].append({"File": {"path": str(env / "secret.txt")}})
        r = api.post(f"/api/studio/videos/{vid}/filmcraft/save?revision=2&base=2", content=json.dumps(doc),
                     headers=H)
        assert r.status_code == 400 and "outside this video's files" in r.json()["detail"]
        assert db.fetch("studio_projects", vid)["plan_revision"] == 2
        # version 2 opens on the person's own save
        s = api.get(f"/api/studio/videos/{vid}/filmcraft/editor?revision=2", headers=H).json()
        assert s["hand"] and s["ready"] and any(m["name"].endswith("my-logo.png") or "logo" in m["name"]
                                                for m in s["media"])

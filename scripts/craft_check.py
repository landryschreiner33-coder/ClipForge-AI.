"""Check FilmCraft and EffectCraft inside ClipForge with the real apps (run by .github/workflows/filmcraft-check.yml).

1. ClipForge fetches the apps itself (craft/apps.py: the pinned release files, checked against their SHA-256) and
   finds them in its own folder.
2. A ClipForge video (the same media and plan as filmcraft_check.py) is edited in FilmCraft with its own tools and
   rendered by FilmCraft (craft/finish.py), with EffectCraft's animated title placed in the edit. Every FilmCraft step
   must apply, the title shot must be in the edit, and the file must have the right length, size and sound.
3. The AI finishing pass with a stand-in AI answer (real clip ids, a colour look and an effect FilmCraft lists, a
   keyframed zoom and one EffectCraft effects shot) on the real apps: every step applies and the shot is placed.
4. With --browser: FilmCraft's editor on ClipForge's editor page in headless Chrome. The page opens the version with
   its files (no "media not found"), and FilmCraft's Save comes back to ClipForge as version 2, whose saved project
   names only this video's files.

    python scripts/craft_check.py --out /tmp/craft-check [--browser]

Writes report.json in --out and exits 1 when anything is wrong.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--browser", action="store_true")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ["CLIPFOUNDRY_DATA"] = str(out / "data")
    os.environ.setdefault("CLIPFOUNDRY_WORKERS", "off")
    os.environ.setdefault("CLIPFOUNDRY_CRAFT_GPU", "off")
    for k in ("CLIPFOUNDRY_FILMCRAFT_CLI", "CLIPFOUNDRY_EFFECTCRAFT_CLI", "CLIPFOUNDRY_FILMCRAFT"):
        os.environ.pop(k, None)
    import filmcraft_check as fc_check

    from clipfoundry import db
    from clipfoundry.craft import apps, finish
    from clipfoundry.studio import video_flow

    problems: list[str] = []
    report: dict = {"platform": apps.platform_key()}

    def want(cond: bool, what: str) -> None:
        if not cond:
            problems.append(what)
            print("PROBLEM:", what, flush=True)

    # 1. ClipForge fetches the apps
    db.init()
    t0 = time.monotonic()
    st = apps.install(("cli", "web"), wait=True)
    report["install"] = {"seconds": round(time.monotonic() - t0, 1), "task": st.get("task"),
                         "apps": st.get("apps")}
    for key in ("filmcraft", "effectcraft"):
        got = apps.find_cli(key)
        want(bool(got) and got["source"] == "clipforge", f"{key} is not set up in ClipForge's folder: {got}")
        if got:
            report[f"{key}_version"] = subprocess.run([got["path"], "--version"], capture_output=True, text=True,
                                                      timeout=60).stdout.strip()
    web = apps.web_root("filmcraft")
    want(bool(web) and (web / "index.html").is_file(), f"FilmCraft's editor is not set up: {web}")
    if problems:
        return finish_report(out, report, problems)

    # 2. the edit in FilmCraft and its render
    files = fc_check.make_media(out / "media")
    project = fc_check.seed(files)
    plan = video_flow.plan_at(project["id"], 1)
    assets = video_flow._assets(project, plan)
    settings = db.get_settings()
    words = {aid: video_flow.transcript_words(a, settings, cached_only=True) for aid, a in assets.items()
             if a["kind"] == "video"}
    final = video_flow.video_dir(project["id"]) / "r1" / "final.mp4"
    final.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    try:
        info = finish.render(plan, assets, words, final, name=project["name"], revision=1, settings=settings,
                             progress=lambda f, m: print(f"  {f:.2f} {m}", flush=True))
    except Exception as exc:  # noqa: BLE001 - reported
        want(False, f"FilmCraft's edit or render failed: {exc}")
        info = None
    if info:
        fc = info["filmcraft"]
        report["render"] = {k: info[k] for k in ("duration", "expected_duration", "width", "height", "fps",
                                                 "has_audio")}
        report["render"]["seconds"] = round(time.monotonic() - t0, 1)
        report["edit"] = {"steps": fc["steps"], "failed": fc["failed"], "shots": fc["shots"], "notes": fc["notes"]}
        want(not fc["failed"], f"{len(fc['failed'])} FilmCraft steps did not apply: {fc['failed'][:8]}")
        want(not fc["notes"], f"notes from the edit: {fc['notes']}")
        want([s["use"] for s in fc["shots"]] == ["title"], f"the EffectCraft title is not in the edit: {fc['shots']}")
        want(abs(info["duration"] - info["expected_duration"]) <= 0.1, f"render length {info['duration']}")
        steps = json.loads((final.parent / "filmcraft" / "report.json").read_text())["steps_run"]
        report["steps_by_tool"] = {}
        for s in steps:
            report["steps_by_tool"][s["id"]] = report["steps_by_tool"].get(s["id"], 0) + 1
        seq = finish.tools()[0].inspect(final.parent / "filmcraft" / "edit.fcproj")
        report["sequence_after"] = {k: seq.get(k) for k in ("durationFrames", "settings")}

    # 3. the AI's finishing on the real apps, with a stand-in AI answer
    from clipfoundry.pipeline import llm

    asked: dict = {}

    def answer(_settings, prompt, *, system=None, task="", **_kw):
        asked["prompt"] = prompt
        rows = json.loads(prompt.split("The sequence (FilmCraft clip ids):\n", 1)[1].split("\n", 1)[0])
        clip = next(r for r in rows if r["track"] == "Video 1" and r["what"] == "clip")
        effects = re.search(r"Video effects \(for effects.apply\): (.*)", prompt).group(1).split(", ")
        looks = re.search(r"Colour looks \(for lumetri.applyPreset\): (.*)", prompt).group(1).split(", ")
        start = round(clip["from_s"] * fc_check.FPS)
        steps = [{"id": "effects.setParam", "params": {"clip": clip["clip"], "effect": "motion", "param": "scale",
                                                         "value": 100, "frame": start, "keyframe": True}},
                 {"id": "effects.setParam", "params": {"clip": clip["clip"], "effect": "motion", "param": "scale",
                                                         "value": 108, "frame": start + 45, "keyframe": True}}]
        if looks and looks[0]:
            steps.append({"id": "lumetri.applyPreset", "params": {"name": looks[0], "clips": [clip["clip"]]}})
        pick = next((e for e in effects if "glow" in e.lower()), effects[0] if effects and effects[0] else "")
        if pick:
            steps.append({"id": "effects.apply", "params": {"clips": [clip["clip"]], "effect": pick}})
        return json.dumps({"summary": "A slow push-in, a colour look and a lower third.", "steps": steps, "shots": [
            {"name": "Lower third", "at_s": 3.0, "seconds": 2.5, "script": LOWER_THIRD}]})

    llm.complete = answer
    ai_final = out / "ai" / "final.mp4"
    ai_final.parent.mkdir(parents=True, exist_ok=True)
    try:
        info = finish.render(plan, assets, words, ai_final, name=project["name"], revision=1,
                             settings={**settings, "ai_provider": "ollama", "craft_ai_finish": True})
        ai = info["filmcraft"]["ai"]
        report["ai"] = ai
        report["ai_catalog"] = asked.get("prompt", "").split("Tools you may use (id, parameters):\n", 1)[-1][:3000]
        want(ai.get("used") and not ai.get("failed") and not ai.get("refused"), f"the AI's steps did not all apply: {ai}")
        want(ai.get("shots") == 1, f"the AI's effects shot was not placed: {ai}")
        want(abs(info["duration"] - info["expected_duration"]) <= 0.1, f"AI render length {info['duration']}")
    except Exception as exc:  # noqa: BLE001 - reported
        want(False, f"the AI finishing pass failed: {exc}")

    # 4. FilmCraft's editor on the editor page
    if args.browser:
        report["browser"] = browser_check(out, project, want)
    return finish_report(out, report, problems)


LOWER_THIRD = """
var bar = comp.layers.addSolid([0.05, 0.05, 0.08], "Bar", Math.round(W * 0.8), Math.round(H * 0.07), 1, DUR);
bar.property("Transform").property("Position").setValue([W / 2, H * 0.78]);
var op = bar.property("Transform").property("Opacity");
op.setValueAtTime(0, 0);
op.setValueAtTime(0.4, 85);
var t = comp.layers.addText("Lake day");
var doc = t.property("Source Text").value;
doc.fontSize = Math.round(H * 0.035);
doc.fillColor = [1, 1, 1];
t.property("Source Text").setValue(doc);
t.property("Transform").property("Position").setValue([W / 2, H * 0.79]);
"""


def browser_check(out: Path, project: dict, want) -> dict:
    """The real page in headless Chrome: open FilmCraft's editor on version 1, then save it back as version 2."""
    from playwright.sync_api import sync_playwright

    from clipfoundry import db
    from clipfoundry.studio import video_flow

    port = 8799
    env = dict(os.environ, CLIPFOUNDRY_WORKERS="off")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "clipfoundry.api:app", "--port", str(port),
                               "--log-level", "warning"], cwd=ROOT, env=env)
    got: dict = {"console": []}
    try:
        import httpx

        for _ in range(60):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/craft", headers={"X-ClipFoundry": "1"}).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(1)
        session = httpx.get(f"http://127.0.0.1:{port}/api/studio/videos/{project['id']}/filmcraft/editor?revision=1",
                            headers={"X-ClipFoundry": "1"}).json()
        got["session"] = {k: session.get(k) for k in ("ready", "editor_ready", "cli_ready", "steps", "media")}
        want(session.get("ready"), f"the editor page has no FilmCraft edit to open: {got['session']}")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=[
                "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.on("console", lambda m: got["console"].append(f"{m.type}: {m.text}"[:300]))
            page.goto(f"http://127.0.0.1:{port}/#/video/{project['id']}")
            page.get_by_role("button", name=re.compile(r"Edit version 1 in FilmCraft")).click(timeout=60000)
            frame = None
            for _ in range(180):
                frame = next((f for f in page.frames if "/craft/filmcraft/" in f.url), None)
                if frame and frame.evaluate("() => !!window.filmcraft"):
                    break
                time.sleep(1)
            want(frame is not None, "FilmCraft's editor did not load in the page")
            if frame is None:
                return got
            opened = False
            for _ in range(240):  # the page hands FilmCraft the files, then opens the project
                text = page.locator(".craft-editor").inner_text()
                if "did not open" in text:
                    break
                if "Starting FilmCraft" not in text and "Handing FilmCraft" not in text:
                    opened = True
                    break
                time.sleep(1)
            got["dialog"] = page.locator(".craft-editor").inner_text()[:600]
            page.screenshot(path=str(out / "editor.png"))
            want(opened and "did not open" not in got["dialog"], f"the project did not open: {got['dialog']}")
            info = frame.evaluate("() => filmcraft.info()")
            got["info"] = info
            seq = frame.evaluate("() => filmcraft.execute('sequence.inspect', {})")
            got["sequence"] = {k: seq.get(k) for k in ("name", "durationFrames", "settings")} if isinstance(seq, dict) \
                else seq
            tracks = [*(seq.get("video") or []), *(seq.get("audio") or [])] if isinstance(seq, dict) else []
            got["tracks"] = {t.get("name"): len(t.get("items") or []) for t in tracks}
            want(sum(got["tracks"].values()) > 5, f"the opened sequence has too few clips: {got['tracks']}")
            files = frame.evaluate("() => filmcraft.files()")
            got["files"] = files[:40] if isinstance(files, list) else files
            # FilmCraft's Save: the page sends the project back and it becomes version 2
            page.locator("iframe.craft-frame").click(position={"x": 400, "y": 300})
            page.keyboard.press("Meta+S" if sys.platform == "darwin" else "Control+S")
            for _ in range(60):
                if (db.fetch("studio_projects", project["id"]) or {}).get("plan_revision", 1) >= 2:
                    break
                time.sleep(1)
            row = db.fetch("studio_projects", project["id"])
            got["after_save"] = {"plan_revision": row["plan_revision"]}
            want(row["plan_revision"] >= 2, "FilmCraft's Save did not come back to ClipForge as version 2")
            if row["plan_revision"] >= 2:
                plan = video_flow.plan_at(project["id"], 2)
                saved = video_flow.filmcraft_saves(project["id"]) / f"{plan['filmcraft']['project']}.fcproj"
                text = saved.read_text()
                got["after_save"]["bytes"] = len(text)
                want("/files/" not in text, "the saved project still names the editor's own files")
            page.screenshot(path=str(out / "editor-saved.png"))
            browser.close()
    except Exception as exc:  # noqa: BLE001 - reported
        want(False, f"the editor page check failed: {exc}")
    finally:
        server.terminate()
        server.wait(timeout=30)
    return got


def finish_report(out: Path, report: dict, problems: list[str]) -> int:
    report["problems"] = problems
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({"problems": problems, "edit": report.get("edit"), "ai": report.get("ai")}, indent=2,
                     default=str))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

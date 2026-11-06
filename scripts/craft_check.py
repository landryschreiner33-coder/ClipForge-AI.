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
5. With --builtin-ai: the same AI finishing pass answered by ClipForge's built-in model (builtin_ai.py: the pinned
   llama.cpp engine and the Basic model, downloaded and checked the way the app does it). Its request must fit the
   model, its answer must be read, and at least one of its FilmCraft steps or EffectCraft shots must land in the edit
   that FilmCraft renders. What it chose, what FilmCraft refused and how long it took are reported.

    python scripts/craft_check.py --out /tmp/craft-check [--browser] [--builtin-ai]

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
    ap.add_argument("--builtin-ai", action="store_true")
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

    report["effectcraft_probe"] = effect_probe(out / "probe")

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
        want(False, f"FilmCraft's edit or render failed: {exc!r}")
        info = None
    if info:
        fc = info["filmcraft"]
        report["render"] = {k: info[k] for k in ("duration", "expected_duration", "width", "height", "fps",
                                                 "has_audio")}
        report["render"]["seconds"] = round(time.monotonic() - t0, 1)
        report["edit"] = {"steps": fc["steps"], "failed": fc["failed"], "shots": fc["shots"], "notes": fc["notes"]}
        want(not fc["failed"], f"{len(fc['failed'])} FilmCraft steps did not apply: {fc['failed'][:8]}")
        print("shots:", json.dumps([{k: v for k, v in x.items() if k != "item"} for x in fc["shots"]]), flush=True)
        want(all(x.get("checks") == "ok" for x in fc["shots"]),
             f"EffectCraft's title script could not set everything: {[x.get('checks') for x in fc['shots']]}")
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
    real_complete = llm.complete

    def answer(_settings, prompt, *, system=None, task="", **_kw):
        asked["prompt"] = prompt
        rows = json.loads(prompt.split("The sequence (FilmCraft clip ids):\n", 1)[1].split("\n", 1)[0])
        talk = [r for r in rows if r["track"] == "Video 1" and r["what"] == "video"]
        asked["rows"] = rows
        clip = talk[0] if talk else next(r for r in rows if r["track"] == "Video 1")
        effects = json.loads(re.search(r"Video effects \(for effects.apply\): (.*)", prompt).group(1))
        looks = json.loads(re.search(r"Colour looks \(for lumetri.applyPreset name\): (.*)", prompt).group(1))
        start = round(clip["from_s"] * fc_check.FPS)
        steps = [{"id": "effects.setParam", "params": {"clip": clip["clip"], "effect": "motion", "param": "scale",
                                                         "value": 100, "frame": start, "keyframe": True}},
                 {"id": "effects.setParam", "params": {"clip": clip["clip"], "effect": "motion", "param": "scale",
                                                         "value": 108, "frame": start + 45, "keyframe": True}}]
        if looks:
            steps.append({"id": "lumetri.applyPreset", "params": {"name": looks[0], "clips": [clip["clip"]]}})
        pick = next((e for e in effects if "glow" in e.lower()), effects[0] if effects else "")
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
        print("ai:", json.dumps(ai)[:1500], flush=True)
        report["ai_catalog"] = asked.get("prompt", "").split("Tools you may use (id, parameters):\n", 1)[-1][:3000]
        want(ai.get("used") and not ai.get("failed") and not ai.get("refused"), f"the AI's steps did not all apply: {ai}")
        want(ai.get("shots") == 1, f"the AI's effects shot was not placed: {ai}")
        want(abs(info["duration"] - info["expected_duration"]) <= 0.1, f"AI render length {info['duration']}")
    except Exception as exc:  # noqa: BLE001 - reported
        want(False, f"the AI finishing pass failed: {exc!r} (rows: {asked.get('rows', [])[:6]})")

    # 4. FilmCraft's editor on the editor page
    if args.browser:
        report["browser"] = browser_check(out, project, want)

    # 5. the built-in model finishing the edit with FilmCraft's tools
    if args.builtin_ai:
        llm.complete = real_complete
        report["builtin_ai"] = builtin_check(out, plan, assets, words, project, settings, want)
    return finish_report(out, report, problems)


def builtin_check(out: Path, plan: dict, assets: dict, words: dict, project: dict, settings: dict, want) -> dict:
    from clipfoundry import builtin_ai
    from clipfoundry.craft import ai as craft_ai
    from clipfoundry.craft import finish
    from clipfoundry.pipeline import llm

    level = "basic"
    row: dict = {"level": level, "model": builtin_ai.MODELS[level]["model"]}
    t0 = time.monotonic()
    try:
        builtin_ai._install_engine(lambda *_a: None)  # noqa: SLF001 - the same code the app runs, without its thread
        builtin_ai._install_level(level, lambda *_a: None)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001 - reported
        want(False, f"the built-in model could not be downloaded: {exc!r}")
        return row
    row["download_s"] = round(time.monotonic() - t0, 1)
    s = {**settings, "ai_provider": "builtin", "builtin_ai_level": level, "builtin_ai_idle_minutes": 30,
         "craft_ai_finish": True}
    if sys.platform == "darwin" and os.environ.get("GITHUB_ACTIONS"):
        # GitHub's Mac machines can't use the graphics chip (about 5 words a second); a real Mac uses it
        craft_ai.LOCAL_TIMEOUT_S = 1500.0
        row["timeout_s"] = craft_ai.LOCAL_TIMEOUT_S
    want(craft_ai.usable(s), "the built-in model is downloaded but ClipForge does not see it as set up")
    seen: dict = {}
    real = llm.complete

    def recording(settings_, prompt, **kw):
        seen["prompt_chars"] = len(prompt)
        t = time.monotonic()
        try:
            seen["raw"] = real(settings_, prompt, **kw)
        except Exception as exc:  # noqa: BLE001 - reported below through the AI pass
            seen["error"] = repr(exc)
            raise
        finally:
            seen["answer_s"] = round(time.monotonic() - t, 1)
        return seen["raw"]

    llm.complete = recording
    final = out / "builtin" / "final.mp4"
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        info = finish.render(plan, assets, words, final, name=project["name"], revision=1, settings=s,
                             progress=lambda f, m: print(f"  {f:.2f} {m}", flush=True))
        got = info["filmcraft"]["ai"]
        row.update(ai=got, render={k: info[k] for k in ("duration", "expected_duration", "has_audio")})
        landed = (got.get("steps") or 0) - len(got.get("failed") or []) + (got.get("shots") or 0)
        row["landed"] = landed
        want(bool(got.get("used")), f"the built-in model's answer was not used: {got.get('why') or got}")
        want(str(got.get("provider", "")).startswith("Built-in model"), f"another AI answered: {got.get('provider')}")
        want(seen.get("prompt_chars", 0) <= craft_ai.LOCAL_PROMPT_CHARS, f"request too long: {seen.get('prompt_chars')}")
        want(landed > 0, f"none of the built-in model's steps or shots landed in the edit: {got}")
        want(abs(info["duration"] - info["expected_duration"]) <= 0.1, f"built-in model render length {info['duration']}")
    except Exception as exc:  # noqa: BLE001 - reported
        want(False, f"the edit with the built-in model failed: {exc!r}")
    finally:
        llm.complete = real
        builtin_ai.server.stop()
    row.update({k: seen[k] for k in ("prompt_chars", "answer_s", "error") if k in seen})
    row["engine"] = dict(builtin_ai.last_answer)  # llama.cpp's timings and why the answer stopped
    row["raw_answer"] = str(seen.get("raw", ""))[:4000]
    if not row.get("landed"):
        from clipfoundry import config

        try:
            tail = (config.data_dir() / "logs" / "builtin-ai.log").read_text(errors="replace").splitlines()[-60:]
        except OSError as exc:
            tail = [f"no engine log: {exc}"]
        print("built-in model engine log (end):\n" + "\n".join(tail), flush=True)
    print("built-in model:", json.dumps({k: v for k, v in row.items() if k != "raw_answer"})[:2500], flush=True)
    print("built-in model answer:", row["raw_answer"], flush=True)
    return row


LOWER_THIRD = """
var bar = comp.layers.addSolid([0.05, 0.05, 0.08], "Bar", Math.round(W * 0.8), Math.round(H * 0.07), 1, DUR);
cfSet(bar, "Position", [W / 2, H * 0.78]);
cfKeys(bar, "Opacity", [[0, 0], [0.4, 85]]);
var t = comp.layers.addText("Lake day");
cfStyle(t, Math.round(H * 0.035), [1, 1, 1]);
cfSet(t, "Position", [W / 2, H * 0.79]);
"""


PROBE = r"""
var comp = app.project.items.addComp("ClipForge Probe", 320, 180, 1, 1, 30);
var t = comp.layers.addText("Hi");
var s = comp.layers.addSolid([1, 0, 0], "S", 320, 180, 1, 1);
var got = [];
function walk(p, depth, path) {
  var n = 0;
  try { n = p.numProperties || 0; } catch (e) { got.push(path + " numProperties! " + e.message); }
  for (var i = 1; i <= n && got.length < 90; i++) {
    try {
      var c = p.property(i);
      got.push(path + "/" + c.name + " [" + c.matchName + "]");
      if (depth < 1) walk(c, depth + 1, path + "/" + c.name);
    } catch (e) { got.push(path + " #" + i + "! " + e.message); }
  }
}
walk(t, 0, "text");
walk(s, 0, "solid");
var tries = [["text.sourceText", function () { return t.text.sourceText; }],
  ["Source Text", function () { return t.property("Source Text"); }],
  ["ADBE Text Document", function () { return t.property("ADBE Text Properties").property("ADBE Text Document"); }],
  ["Text/Source Text", function () { return t.property("Text").property("Source Text"); }],
  ["value.fontSize", function () { return t.property("ADBE Text Properties").property("ADBE Text Document").value.fontSize; }],
  ["Transform/Position", function () { return s.property("Transform").property("Position").value; }],
  ["ADBE Position", function () { return s.property("ADBE Transform Group").property("ADBE Position").value; }],
  ["transform.position", function () { return s.transform.position.value; }]];
for (var k = 0; k < tries.length; k++) {
  try { var v = tries[k][1](); got.push(tries[k][0] + " = " + (v === null ? "null" : v === undefined ? "undefined" : String(v))); }
  catch (e) { got.push(tries[k][0] + " ! " + e.message); }
}
got.join("\n");
"""


def effect_probe(folder: Path) -> dict:
    """What EffectCraft's scripting model offers on a text layer and a solid (printed for whoever reads the log)."""
    from clipfoundry.craft import apps
    from clipfoundry.craft.runner import EffectCraft, call

    got: dict = {}
    cli = apps.find_cli("effectcraft")
    if not cli:
        return {"error": "EffectCraft is not set up"}
    folder.mkdir(parents=True, exist_ok=True)
    try:
        for args in (["--help"], ["script", "--help"]):
            done = call(cli["path"], args, timeout=60, what="EffectCraft")
            got[" ".join(args)] = (done.stdout or done.stderr)[:2500]
        js = folder / "probe.jsx"
        js.write_text(PROBE)
        res = EffectCraft(cli["path"]).script(js, folder / "probe.ecproj")
        got["result"] = res.get("result")
        got["output"] = res.get("output")
    except Exception as exc:  # noqa: BLE001 - only a report
        got["error"] = repr(exc)
    print("EffectCraft probe:\n" + "\n".join(f"--- {k}\n{v}" for k, v in got.items()), flush=True)
    return got


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
        rev = (db.fetch("studio_projects", project["id"]) or {}).get("plan_revision") or 1
        got["revision"] = rev
        session = httpx.get(f"http://127.0.0.1:{port}/api/studio/videos/{project['id']}/filmcraft/editor"
                            f"?revision={rev}", headers={"X-ClipFoundry": "1"}).json()
        got["session"] = {k: session.get(k) for k in ("ready", "editor_ready", "cli_ready", "steps", "media")}
        want(session.get("ready"), f"the editor page has no FilmCraft edit to open: {got['session']}")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=[
                "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.on("console", lambda m: got["console"].append(f"{m.type}: {m.text}"[:300]))
            page.goto(f"http://127.0.0.1:{port}/#/video/{project['id']}")
            button = page.get_by_role("button", name=re.compile(rf"Edit version {rev} in FilmCraft"))
            try:
                button.click(timeout=60000)
            except Exception:
                snap(page, out / "editor-page.png", full_page=True)
                panel = page.locator("#vr-filmcraft").locator("xpath=..")
                print("editor page:", page.url, "\n", (panel.inner_text() if panel.count() else
                                                       page.locator("body").inner_text())[:3000], flush=True)
                print("/api/craft:", httpx.get(f"http://127.0.0.1:{port}/api/craft",
                                               headers={"X-ClipFoundry": "1"}).text[:2000], flush=True)
                print("console:", got["console"][:30], flush=True)
                raise
            frame = None
            save_button = page.get_by_role("button", name="Save to ClipForge")
            opened = False
            for _ in range(300):  # FilmCraft starts, then the page hands it the files and opens the project
                frame = next((f for f in page.frames if "/craft/filmcraft/" in f.url), None)
                text = page.locator(".craft-editor").inner_text()
                if "did not open" in text:
                    break
                if save_button.count() and save_button.is_enabled():
                    opened = True
                    break
                time.sleep(1)
            got["dialog"] = page.locator(".craft-editor").inner_text()[:800]
            snap(page, out / "editor.png")
            if frame is not None:
                try:
                    got["load"] = frame.evaluate("() => ({load: window.filmcraftLoad || null, api: !!window.filmcraft,"
                                                 " url: location.href, gpu: !!navigator.gpu,"
                                                 " webgl2: !!document.createElement('canvas').getContext('webgl2'),"
                                                 " text: document.body.innerText.slice(0, 600)})")
                except Exception as exc:  # noqa: BLE001 - only a report
                    got["load"] = repr(exc)
            if not opened:
                print("editor dialog:", got["dialog"], "\nframe:", got.get("load"), "\nconsole:",
                      got["console"][-40:], flush=True)
            want(frame is not None, "FilmCraft's editor did not load in the page")
            want(opened, f"the project did not open in FilmCraft's editor: {got['dialog']} / {got.get('load')}")
            if not opened or frame is None:
                return got
            got["info"] = frame.evaluate("() => filmcraft.info()")
            seq = frame.evaluate("() => filmcraft.execute('sequence.inspect', {})")
            got["sequence"] = {k: seq.get(k) for k in ("name", "durationFrames", "settings")} if isinstance(seq, dict) \
                else seq
            tracks = [*(seq.get("video") or []), *(seq.get("audio") or [])] if isinstance(seq, dict) else []
            got["tracks"] = {t.get("name"): len(t.get("items") or []) for t in tracks}
            want(sum(got["tracks"].values()) > 5, f"the opened sequence has too few clips: {got['tracks']}")
            files = frame.evaluate("() => filmcraft.files()")
            got["files"] = files[:40] if isinstance(files, list) else files
            print("editor opened:", json.dumps({k: got[k] for k in ("load", "tracks", "files")}, default=str)[:3000],
                  flush=True)

            def saved_version(seconds: int) -> bool:
                for _ in range(seconds):
                    if (db.fetch("studio_projects", project["id"]) or {}).get("plan_revision", 1) > rev:
                        return True
                    time.sleep(1)
                return False

            # FilmCraft's own Save (Ctrl/Cmd+S in the editor), then ClipForge's Save button
            page.locator("iframe.craft-frame").click(position={"x": 400, "y": 300})
            page.keyboard.press("Meta+S" if sys.platform == "darwin" else "Control+S")
            got["ctrl_s"] = saved_version(30)
            if not got["ctrl_s"]:
                save_button.click()
                got["button"] = saved_version(60)
            row = db.fetch("studio_projects", project["id"])
            got["after_save"] = {"plan_revision": row["plan_revision"]}
            print("after save:", {k: got.get(k) for k in ("ctrl_s", "button", "after_save")}, flush=True)
            want(row["plan_revision"] > rev, f"FilmCraft's save did not come back to ClipForge as version {rev + 1}")
            if row["plan_revision"] > rev:
                plan = video_flow.plan_at(project["id"], row["plan_revision"])
                saved = video_flow.filmcraft_saves(project["id"]) / f"{plan['filmcraft']['project']}.fcproj"
                text = saved.read_text()
                got["after_save"]["bytes"] = len(text)
                want("/files/" not in text, "the saved project still names the editor's own files")
            snap(page, out / "editor-saved.png")
            browser.close()
    except Exception as exc:  # noqa: BLE001 - reported
        want(False, f"the editor page check failed: {exc!r}")
    finally:
        server.terminate()
        server.wait(timeout=30)
    return got


def snap(page, path: Path, **kw) -> None:
    """A screenshot for the uploaded files. Only a picture: a slow machine that can't take it in time (GitHub's Mac,
    while FilmCraft redraws after a save) is noted, not counted as a problem."""
    try:
        page.screenshot(path=str(path), timeout=60000, **kw)
    except Exception as exc:  # noqa: BLE001 - noted
        print(f"no screenshot {path.name}: {str(exc).splitlines()[0][:200]}", flush=True)


def left_running() -> list[str]:
    """FilmCraft or EffectCraft processes still running (none should be once the check is done)."""
    if sys.platform == "win32":
        return []
    time.sleep(3)
    done = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,pgid=,etime=,command="], capture_output=True, text=True,
                          check=False)
    return [line.strip()[:400] for line in done.stdout.splitlines() if "craft-cli" in line and "ps -A" not in line]


def finish_report(out: Path, report: dict, problems: list[str]) -> int:
    report["left_running"] = left_running()
    print("left running:", report["left_running"], flush=True)
    report["problems"] = problems
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({"problems": problems, "edit": report.get("edit"), "ai": report.get("ai")}, indent=2,
                     default=str))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

"""Check watching and listening on a real computer with real footage (run by .github/workflows/watch-listen-check.yml;
docs/clipforge/WATCH_AND_LISTEN.md).

1. Gets a real film: Tears of Steel (Blender Foundation, CC BY 3.0, 12 minutes of talk, action and explosions) and
   its English subtitles as the transcript, or takes --video and --subtitles.
2. Listens to the whole sound track (listen.analyze) and watches the whole video frame by frame (watch.scan), and
   prints how long each took and what was found: the sounds named over time, the shots, the moments where the
   picture comes alive.
3. With --level (basic or standard): downloads the built-in model and has it say what happens in each part of the
   film (eyes.describe_video), printing every answer.
4. Picks clips twice with the app's own pipeline (process.prepare, candidate_pool, evaluate_select): with watching
   and listening off (as before this change) and on, and prints both lists with each clip's explanation.

Writes a JSON report (--out) and, on GitHub, a summary. Exits 1 when the sound model does not load, nothing is
heard or watched, or a run fails. Everything goes into a fresh data folder, never the user's own.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILM = "https://storage.googleapis.com/shaka-demo-assets/tos-ttml/"  # Tears of Steel, CC BY 3.0 (Blender Foundation)


def fetch(url: str, dest: Path) -> Path:
    if not dest.exists():
        print(f"downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:  # noqa: S310 - fixed https host
            shutil.copyfileobj(r, f)
    return dest


def get_film(folder: Path) -> tuple[Path, Path]:
    """Tears of Steel: the DASH demo's 1280x534 video and English sound joined into one file, and the subtitles."""
    import subprocess

    folder.mkdir(parents=True, exist_ok=True)
    film = folder / "tears-of-steel.mp4"
    subs = fetch(FILM + "s-eng.ttml", folder / "tos-eng.ttml")
    if not film.exists():
        v = fetch(FILM + "v-0720p-2500k-libx264.mp4", folder / "tos-v.mp4")
        a = fetch(FILM + "a-eng-0128k-aac.mp4", folder / "tos-a.mp4")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(v), "-i", str(a), "-map",
                        "0:v:0", "-map", "1:a:0", "-c", "copy", str(film)], check=True)
    return film, subs


def subtitles_to_json(path: Path, out: Path) -> Path:
    """A TTML or SRT subtitle file as ClipForge's JSON transcript (segments; words spread over each cue)."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    segs = []
    if path.suffix.lower() in (".ttml", ".xml", ".dfxp"):
        for m in re.finditer(r'<p[^>]*begin="([^"]+)"[^>]*end="([^"]+)"[^>]*>(.*?)</p>', text, re.S):
            words = html.unescape(re.sub(r"<[^>]+>", " ", m.group(3)))
            segs.append({"start": _secs(m.group(1)), "end": _secs(m.group(2)), "text": " ".join(words.split())})
    else:
        from clipfoundry.pipeline.transcribe import parse_subtitles

        segs = [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in parse_subtitles(text)]
    out.write_text(json.dumps({"language": "en", "segments": [s for s in segs if s["text"]]}))
    return out


def _secs(t: str) -> float:
    if t.endswith("s") and ":" not in t:
        return float(t[:-1])
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def senses_pass(film: Path, report: dict, level: str) -> list[str]:
    from clipfoundry.pipeline import listen, watch
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import extract_audio, probe
    from clipfoundry.pipeline.senses import Senses

    problems: list[str] = []
    work = Path(tempfile.mkdtemp(prefix="senses-"))
    meta = probe(film)
    wav = work / "audio.wav"
    extract_audio(film, wav, meta["duration"])
    row: dict = {"duration": round(meta["duration"], 1), "computer": f"{platform.system()} {platform.machine()}",
                 "cpus": os.cpu_count()}
    report["senses"] = row
    t0 = time.monotonic()
    heard = listen.analyze(wav, JobContext(), work / "sounds.json")
    row["listen_s"] = round(time.monotonic() - t0, 1)
    if heard is None:
        return [f"listen: nothing heard ({listen.problem() or 'no reason given'})"]
    row["listen_x_realtime"] = round(meta["duration"] / max(0.1, row["listen_s"]), 1)
    row["heard_events"] = [f"{listen.stamp(e['start'])}-{listen.stamp(e['end'])} {listen.WORDS[e['kind']]} "
                           f"({e['peak']:.2f})" for e in heard.events if e["kind"] in listen.NOTE_KINDS][:60]
    row["sounds_by_minute"] = {listen.stamp(m * 60): [n for n, _ in heard.top_sounds(m * 60, m * 60 + 60, 4)]
                               for m in range(int(meta["duration"] // 60) + 1)}
    t0 = time.monotonic()
    watched = watch.scan(film, meta, JobContext(), work / "watch.json")
    row["watch_s"] = round(time.monotonic() - t0, 1)
    if watched is None:
        return problems + ["watch: the video was not watched"]
    row["watch_x_realtime"] = round(meta["duration"] / max(0.1, row["watch_s"]), 1)
    row["frames"], row["fps"], row["shots"] = watched.n, watched.fps, len(watched.shots())
    row["faces_share"] = round(float((watched.faces > 0).mean()), 2)
    row["alive_moments"] = [f"{listen.stamp(m['at'])} ({m['action']:.2f})" for m in watched.moments(limit=15)]
    row["segments"] = len(watched.segments())
    senses = Senses(heard, watched)
    row["anchors"] = [f"{listen.stamp(a['at'])} {a['kind']}: {a['why']}" for a in senses.anchors()]
    if level:
        problems += describe_pass(film, senses, row, level, work)
    return problems


def describe_pass(film: Path, senses, row: dict, level: str, work: Path) -> list[str]:
    from clipfoundry import builtin_ai
    from clipfoundry.pipeline import eyes, listen

    settings = {"ai_provider": "builtin", "builtin_ai_level": level, "builtin_ai_idle_minutes": 60,
                "ai_edit_timeout_s": 120, "ai_eyes": True, "ai_watch": True}
    t0 = time.monotonic()
    builtin_ai._install_engine(lambda *a: None)  # noqa: SLF001
    builtin_ai._install_level(level, lambda *a: None)  # noqa: SLF001
    row["model_install_s"] = round(time.monotonic() - t0, 1)
    try:
        t0 = time.monotonic()
        got = eyes.describe_video(str(film), senses.watched, settings, None, cache=work / "seen.json",
                                  heard=lambda a, b: senses.heard.note(a, b),
                                  priority=lambda a, b: senses.interest(a, b),
                                  budget=float(os.environ.get("WATCH_BUDGET_S") or eyes.describe_budget_s(
                                      settings, senses.watched.duration)))
        row["describe_s"] = round(time.monotonic() - t0, 1)
    finally:
        builtin_ai.server.stop()
    parts = got.pop("parts")
    row["describe"] = got
    row["seen"] = [f"{listen.stamp(p['start'])}-{listen.stamp(p['end'])}{' (same)' if p.get('same') else ''}: "
                   f"{p['what']} [{', '.join(p['tags'])}; action {p['action']}]" for p in parts]
    print("\n".join(row["seen"]), flush=True)
    if not got["answered"]:
        return [f"describe: the model described nothing ({'; '.join(got['problems'][:3])})"]
    return []


def picks_pass(film: Path, transcript: Path, report: dict, level: str, modes: list[str]) -> list[str]:
    """Clips picked by the app's own pipeline, with watching and listening off and on."""
    from clipfoundry import db
    from clipfoundry.pipeline import process
    from clipfoundry.pipeline.common import JobContext

    problems = []
    report["picks"] = {}
    for mode in modes:
        on = mode == "after"
        db.save_settings({"ai_listen": on, "ai_watch": on, "deep_analysis": True, "clip_count": 5, "min_score": 0,
                          "ai_provider": "builtin" if level else "heuristic", "builtin_ai_level": level or "auto",
                          "ai_scout": True, "ai_eyes": True, "ai_edit_timeout_s": 120,
                          "ai_watch_budget_s": float(os.environ.get("WATCH_BUDGET_S") or 0)})
        pdir = Path(os.environ["CLIPFOUNDRY_DATA"]) / "projects" / mode
        pdir.mkdir(parents=True, exist_ok=True)
        src = pdir / "source.mp4"
        if not src.exists():
            try:
                os.link(film, src)
            except OSError:
                shutil.copy2(film, src)
        project = db.create_project(f"Tears of Steel ({mode})", source_path=str(src),
                                    options={"transcript_file": str(transcript)})
        t0 = time.monotonic()
        try:
            p = process.prepare(project["id"], JobContext())
            cands = process.candidate_pool(p, JobContext())
            chosen = process.evaluate_select(p, cands, JobContext())
        except Exception as exc:  # noqa: BLE001
            problems.append(f"picks ({mode}): {type(exc).__name__}: {exc}")
            continue
        finally:
            try:
                from clipfoundry import builtin_ai

                builtin_ai.server.stop()
            except Exception:  # noqa: BLE001
                pass
        rows = []
        for k, r in enumerate(chosen, 1):
            words = " ".join(p.sentences[j]["text"] for j in range(r["s0"], r["s1"] + 1)) if r["s0"] >= 0 else ""
            senses = getattr(p, "senses", None)   # None: an app from before this change (--app)
            sensed = senses.summary(r["start"], r["end"]) if senses is not None and senses.any() else {}
            rows.append({"rank": k, "start": round(r["start"], 1), "end": round(r["end"], 1),
                         "score": r.get("clip_score", r["score"]), "viral_potential": r["score"],
                         "words": words[:240], "why": (r.get("explanation") or [])[:8],
                         "sense": r.get("sense"), "seen": sensed.get("seen"), "heard": sensed.get("heard")})
        report["picks"][mode] = {"seconds": round(time.monotonic() - t0, 1), "clips": rows,
                                 "pool": len(cands), "senses": p.info.get("senses"), "stages":
                                     (p.info.get("quality") or {}).get("stages")}
        print(f"\n== {mode}: {len(rows)} clips in {report['picks'][mode]['seconds']} s", flush=True)
        for c in rows:
            print(f"{c['rank']}. {c['start']:.1f}-{c['end']:.1f} s, score {c['score']}: {c['words'][:120]}")
            for w in c["why"]:
                print(f"     {w}")
        if not rows:
            problems.append(f"picks ({mode}): no clips")
    return problems


def summary(report: dict) -> str:
    s = report.get("senses") or {}
    out = []
    if s:   # not when an older ClipForge without watching and listening runs (--app)
        out += [f"## Watching and listening on {s.get('computer', '?')} ({s.get('cpus')} CPUs)", "",
                f"{report.get('film')}, {s.get('duration')} s. Listening took {s.get('listen_s')} s "
                f"({s.get('listen_x_realtime')}x real time); watching {s.get('frames')} frames at {s.get('fps')} fps "
                f"took {s.get('watch_s')} s ({s.get('watch_x_realtime')}x). {s.get('shots')} shots, faces in "
                f"{round(100 * (s.get('faces_share') or 0))}% of frames.", ""]
        if s.get("describe"):
            d = s["describe"]
            out += [f"The model described {d['answered']} of {d['segments']} parts in {s.get('describe_s')} s "
                    f"(coverage {round(100 * d['coverage'])}%).", ""]
        out += ["Heard: " + "; ".join(s.get("heard_events", [])[:20]), ""]
    for mode, got in (report.get("picks") or {}).items():
        out += [f"### Picks, watching and listening {'on' if mode == 'after' else 'off'} ({got['seconds']} s)", "",
                "| # | Time | Score | Words |", "|---|---|---|---|"]
        out += [f"| {c['rank']} | {c['start']:.0f}-{c['end']:.0f} s | {c['score']} | {c['words'][:90]} |"
                for c in got["clips"]]
        out.append("")
    if report.get("problems"):
        out += ["**Problems:** " + "; ".join(report["problems"])]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--video", type=Path)
    ap.add_argument("--subtitles", type=Path)
    ap.add_argument("--films", type=Path, default=Path(tempfile.gettempdir()) / "clipforge-films")
    ap.add_argument("--level", default="", help="built-in model level for describing and picking (basic/standard)")
    ap.add_argument("--modes", default="before,after", help="which pick runs: before, after or both")
    ap.add_argument("--no-picks", action="store_true")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--app", type=Path, default=ROOT, help="the ClipForge checkout to run (default: this one)")
    a = ap.parse_args()
    os.environ["CLIPFOUNDRY_DATA"] = tempfile.mkdtemp(prefix="clipforge-watch-check-")
    sys.path.insert(0, str(a.app))
    film, subs = (a.video, a.subtitles) if a.video else get_film(a.films)
    transcript = subtitles_to_json(subs, Path(os.environ["CLIPFOUNDRY_DATA"]) / "transcript-import.json")
    report: dict = {"film": film.name, "level": a.level}
    problems = senses_pass(film, report, a.level) if (a.app / "clipfoundry/pipeline/listen.py").exists() else []
    if not a.no_picks:
        problems += picks_pass(film, transcript, report, a.level, [m for m in a.modes.split(",") if m])
    report["problems"] = problems
    text = summary(report)
    print("\n" + text, flush=True)
    if a.out:
        a.out.write_text(json.dumps(report, indent=2))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

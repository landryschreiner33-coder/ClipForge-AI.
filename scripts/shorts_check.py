"""Does Make → Animated short work on a real computer with that computer's own voices?

Run by .github/workflows/shorts-check.yml on macOS (the `say` voices), Windows (the Windows voices through
PowerShell) and Linux (espeak-ng), and by hand anywhere: python scripts/shorts_check.py --out <folder>.

It lists the voices, reads a sentence with the voice ClipForge picks and up to two more English ones (and once
faster), then makes a short from a pasted script with the picked voice (designed cards and camera moves: no picture
maker is set up), renders it and checks what a viewer gets: 1080x1920 at 30 fps, 48 kHz sound with the voice clearly
in it, the length of the plan, and captions burnt in the middle of the frame. Writes <out>/report.json, keeps the
voices, the frames and the final video, and exits 1 when a check fails. Nothing is downloaded and nothing leaves the
computer.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENTENCE = "Did you know octopuses have three hearts? Two of them pump blood to the gills."
SCRIPT = ("Did you know octopuses have three hearts? Two of them pump blood to the gills.\n\n"
          "[Visual: an octopus waving with all eight arms]\nThe third one keeps the rest of the body going.\n\n"
          "And their blood is blue, because it carries copper instead of iron.")
ENGINE = {"darwin": "say", "win32": "sapi"}   # the voice program each system's own voices use


def _wav(path: Path) -> dict:
    with wave.open(str(path), "rb") as w:
        return {"rate": w.getframerate(), "channels": w.getnchannels(), "bits": 8 * w.getsampwidth(),
                "seconds": round(w.getnframes() / float(w.getframerate()), 3)}


def _probe(path: Path) -> dict:
    from clipfoundry.pipeline import ffmpeg_utils

    out = subprocess.run([ffmpeg_utils.ffprobe_bin(), "-v", "error", "-show_streams", "-show_format", "-of", "json",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def _mean_volume(path: Path) -> float:
    from clipfoundry.pipeline import ffmpeg_utils

    err = subprocess.run([ffmpeg_utils.ffmpeg_bin(), "-v", "info", "-i", str(path), "-af", "volumedetect", "-f", "null",
                          "-"], capture_output=True, text=True).stderr
    return float(err.split("mean_volume:")[1].split("dB")[0])


class Check:
    def __init__(self, out: Path):
        self.out = out
        self.report: dict = {"system": f"{platform.system()} {platform.release()} ({platform.machine()})",
                             "python": sys.version.split()[0], "steps": [], "ok": True}

    def step(self, name: str, ok: bool, **facts) -> bool:
        self.report["steps"].append({"step": name, "ok": bool(ok), **facts})
        self.report["ok"] = self.report["ok"] and bool(ok)
        print(f"{'ok  ' if ok else 'FAIL'} {name} {json.dumps(facts)[:600]}", flush=True)  # ASCII: any console
        return bool(ok)

    def save(self) -> None:
        (self.out / "report.json").write_text(json.dumps(self.report, indent=2, ensure_ascii=False), encoding="utf-8")


def _voices(c: Check) -> list[dict]:
    from clipfoundry.makers import voice

    listing = voice.voices()
    own = [v for v in listing if v["id"] != "auto"]
    expected = ENGINE.get(sys.platform, "espeak")
    mine = [v for v in own if v["engine"] == expected]
    c.step("voices are listed", bool(mine), count=len(own), expected_engine=expected,
           first=[f"{v['id']} ({v['lang']})" for v in own[:12]], auto=listing[0].get("about", ""),
           default=voice.default_voice())
    return mine


def _speak(c: Check, mine: list[dict]) -> None:
    from clipfoundry.makers import voice

    english = [v for v in mine if v["lang"].lower().startswith("en")] or mine
    best = voice.default_voice()
    picked = [v for v in mine if v["id"] == best] + [v for v in english if v["id"] != best][:2]
    words = len(SENTENCE.split())
    for k, v in enumerate(picked):
        out = c.out / f"voice-{k + 1}.wav"
        try:
            got = voice.speak(SENTENCE, out, voice=v["id"], speed=1.0)
            info = _wav(Path(got["path"]))
            timed, how = voice.time_words(Path(got["path"]), SENTENCE, engine_words=got["words"], listen=False)
            c.step(f"speaks with {v['id']}",
                   info["rate"] == 48000 and info["channels"] == 1 and info["bits"] == 16
                   and 1.5 < info["seconds"] < 15 and got["engine"] == v["engine"] and not got["fallback"]
                   and len(timed) == words and all(a["end"] <= b["start"] + 1e-6 for a, b in zip(timed, timed[1:])),
                   wav=info, engine=got["engine"], voice=got["voice"], fallback=got["fallback"], timing=how,
                   first_words=[(w["w"], w["start"], w["end"]) for w in timed[:4]])
        except Exception as exc:  # noqa: BLE001 - the report says what broke
            c.step(f"speaks with {v['id']}", False, error=f"{exc.__class__.__name__}: {exc}",
                   trace=traceback.format_exc()[-1500:])
    if picked:
        try:
            slow = voice.speak(SENTENCE, c.out / "speed-1.0.wav", voice=picked[0]["id"], speed=1.0)
            fast = voice.speak(SENTENCE, c.out / "speed-1.3.wav", voice=picked[0]["id"], speed=1.3)
            ratio = fast["duration_s"] / max(0.01, slow["duration_s"])
            c.step("a faster speed reads faster", ratio < 0.92, normal_s=slow["duration_s"], fast_s=fast["duration_s"],
                   ratio=round(ratio, 3))
        except Exception as exc:  # noqa: BLE001
            c.step("a faster speed reads faster", False, error=f"{exc.__class__.__name__}: {exc}")


def _short(c: Check) -> None:
    import numpy as np
    from PIL import Image

    from clipfoundry import db
    from clipfoundry.jobs import worker
    from clipfoundry.makers import shorts
    from clipfoundry.pipeline.captions import STYLE_PRESETS
    from clipfoundry.studio import engine, video_flow
    from clipfoundry.studio import jobs as studio_jobs

    queued: list[str] = []
    worker.submit_studio = queued.append  # this script runs the jobs itself, in order

    def run() -> list[dict]:
        done = []
        while queued:
            job_id = queued.pop(0)
            studio_jobs.run(job_id)
            done.append(db.fetch("studio_jobs", job_id))
        return done

    started = time.monotonic()
    project = shorts.create("local", "local", name="Shorts check", options={"mode": "paste", "script": SCRIPT,
                                                                             "look": "comic", "music": "energetic"})
    jobs = run()
    project = db.fetch("studio_projects", project["id"])
    plan = video_flow.plan_at(project["id"], project["plan_revision"]) if project["plan_revision"] else None
    rows = shorts.ordered(shorts.scene_rows(project["id"]), plan)
    voices = sorted({(r["info"].get("voice") or {}).get("engine", "") for r in rows})
    c.step("the short is made", bool(plan) and all(j["status"] == "done" for j in jobs)
           and all(r["status"] == "ready" for r in rows) and voices == [ENGINE.get(sys.platform, "espeak")],
           seconds=round(time.monotonic() - started, 1), jobs=[(j["kind"], j["status"], j["error"]) for j in jobs],
           scenes=[(r["status"], r["error"], round(r["duration_ms"] / 1000, 2)) for r in rows], voice_engines=voices,
           voice=sorted({(r["info"].get("voice") or {}).get("voice", "") for r in rows}),
           timing=sorted({(r["info"].get("voice") or {}).get("timing", "") for r in rows}),
           notes=shorts.view(project, plan)["notes"])
    if not plan:
        return
    started = time.monotonic()
    studio_jobs.enqueue("local", "video_render", project["id"], project["plan_revision"])
    jobs = run()
    arts = db.select("studio_artifacts", "project_id = ? AND kind = 'final'", (project["id"],))
    if not (jobs and jobs[-1]["status"] == "done" and arts):
        c.step("the short is rendered", False, jobs=[(j["kind"], j["status"], j["error"]) for j in jobs])
        return
    final = c.out / "final.mp4"
    shutil.copyfile(arts[0]["path"], final)
    info = _probe(final)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
    length = float(info["format"]["duration"])
    wanted = engine.duration_ms(plan) / 1000
    mean = _mean_volume(final)
    c.step("the short is rendered", (int(video["width"]), int(video["height"])) == (1080, 1920)
           and video["r_frame_rate"] in ("30/1", "30000/1000") and audio.get("sample_rate") == "48000"
           and abs(length - wanted) < 0.25 and mean > -32,
           seconds=round(time.monotonic() - started, 1), size=f"{video['width']}x{video['height']}",
           fps=video["r_frame_rate"], audio_rate=audio.get("sample_rate"), length=round(length, 2),
           plan_length=round(wanted, 2), mean_volume_db=mean)
    lit = np.array([int(STYLE_PRESETS[plan["captions"]["style"]]["highlight"][k:k + 2], 16) for k in (1, 3, 5)])
    best, frame_at = 0.0, ""
    from clipfoundry.pipeline import ffmpeg_utils

    for at in ("1.0", "2.0", "3.0"):
        frame = c.out / f"frame-{at}.png"
        subprocess.run([ffmpeg_utils.ffmpeg_bin(), "-y", "-v", "error", "-ss", at, "-i", str(final), "-frames:v", "1",
                        str(frame)], check=True)
        img = np.asarray(Image.open(frame).convert("RGB"), dtype=np.int16)
        band = img[int(img.shape[0] * 0.44):int(img.shape[0] * 0.56)]
        share = float(((band > 225).all(axis=2) | (np.abs(band - lit).sum(axis=2) < 60)).mean())
        if share > best:
            best, frame_at = share, at
    c.step("captions are burnt in the middle", best > 0.003, share=round(best, 4), frame=frame_at)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, help="folder for report.json, the voices and the final video")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ["CLIPFOUNDRY_DATA"] = str(out / "data")  # never the repository's own data folder
    sys.path.insert(0, str(ROOT))
    c = Check(out)
    try:
        from clipfoundry import db

        db.init()
        mine = _voices(c)
        _speak(c, mine)
        _short(c)
    except Exception as exc:  # noqa: BLE001 - the report says what broke
        c.step("the check ran to the end", False, error=f"{exc.__class__.__name__}: {exc}",
               trace=traceback.format_exc()[-3000:])
    c.save()
    print(f"\n{'ALL OK' if c.report['ok'] else 'SOMETHING FAILED'}: {out / 'report.json'}")
    return 0 if c.report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

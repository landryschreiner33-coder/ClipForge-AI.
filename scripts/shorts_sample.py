"""Make a sample animated short from a script file and keep what a viewer would see.

    python scripts/shorts_sample.py --script sample.txt --out <folder> [--look cartoon3d] [--music balanced]
        [--captions ""] [--speed 1.05] [--voice auto] [--pictures <folder>] [--stills 0.4,2,5] [--option key=value]

It makes the short exactly as the app does (the same jobs, in order), renders the final video and writes into <out>:
final.mp4, still-<seconds>.jpg for each time asked, sheet.jpg (the stills side by side), each scene's picture
(scene-01.jpg ...) and report.json (the scenes, the plan's sounds, the notes and how long everything took).

--pictures <folder> stands in for the picture maker: scene N's picture is <folder>/scene-NN.(png|jpg|webp) when it
exists, and the short treats it as the picture maker's own (so prompts, looks and motion go the usual way). That is
how a picture made on another computer (a GitHub machine with the real model) is shown with this computer's motion,
captions and sound. <folder>/character.(png|jpg|webp) is the picture of the short's main character: with it the
stand-in says it can be shown a picture, as FLUX.2 klein can, so the scenes are asked for from that picture.

--batch <file> asks for no pictures: it writes what the short would ask the picture maker for (the main character,
then each scene, in the short's own words) as a batch for scripts/shorts_pictures.py, and stops there.
Nothing is downloaded and nothing leaves the computer; the data folder is <out>/data.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def _value(text: str):
    low = text.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text


class _Replay:
    """A stand-in picture maker that hands out ready pictures, scene after scene (see --pictures); with `record` it
    hands out blank pictures and only keeps what it was asked for (see --batch)."""

    EngineError = RuntimeError

    def __init__(self, folder: Path | None, made: Path, real, record: bool = False):
        self.folder, self.made, self.real, self.calls, self.record = folder, made, real, [], record

    def _ready(self, name: str) -> Path | None:
        if self.folder is None:
            return None
        return next((self.folder / f"{name}{s}" for s in SUFFIXES if (self.folder / f"{name}{s}").is_file()), None)

    def status(self, role: str) -> dict:
        if role == "image":
            return {"ready": True, "engine": "Ready pictures (sample)", "why": ""}
        return self.real.status(role) if self.real is not None else {"ready": False, "engine": "", "why": "Not set up."}

    def picture_references(self) -> int:
        return 4 if self.record or self._ready("character") else 0

    def make_image(self, prompt: str, **kw):
        from clipfoundry.makers import pictures

        cast = (kw.get("width"), kw.get("height")) == pictures.CAST_SIZE
        n = sum(1 for c in self.calls if c["name"] != "character") + 1
        name = "character" if cast else f"scene-{n:02d}"
        self.calls.append({"name": name, "prompt": prompt, "references": len(kw.get("references") or ()),
                           **{k: v for k, v in kw.items() if k in ("negative", "style", "seed", "width", "height")}})
        self.made.mkdir(parents=True, exist_ok=True)
        src = self._ready(name)
        if src is not None:
            out = self.made / f"sample-{name}-{int(time.time() * 1000)}{src.suffix}"
            shutil.copyfile(src, out)
        elif self.record:
            from PIL import Image

            out = self.made / f"sample-{name}-{int(time.time() * 1000)}.png"
            Image.new("RGB", (108, 192), (90, 90, 96)).save(out)
        else:
            raise RuntimeError(f"no ready picture for {name}")
        out.with_suffix(".json").write_text(json.dumps({"sample": True, "prompt": prompt}), encoding="utf-8")
        return out

    def __getattr__(self, name: str):  # the voice and anything else: the real makers
        if self.real is None:
            raise AttributeError(name)
        return getattr(self.real, name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--script", required=True, help="a text file: the script to paste")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="Sample short")
    ap.add_argument("--look", default="")
    ap.add_argument("--music", default="")
    ap.add_argument("--captions", default=None)
    ap.add_argument("--speed", type=float, default=None)
    ap.add_argument("--voice", default="")
    ap.add_argument("--pictures", default="", help="a folder of ready pictures: scene-01.png, scene-02.png, ...")
    ap.add_argument("--stills", default="0.5,2.5,6,10,15,20", help="seconds to keep a still at")
    ap.add_argument("--option", action="append", default=[], help="another option of the short, as key=value")
    ap.add_argument("--preview", action="store_true", help="the fast small preview instead of the final video")
    ap.add_argument("--batch", default="", help="write the picture requests as a batch file and stop (no video)")
    ap.add_argument("--batch-name", default="after", help="the folder name of the batch's pictures")
    ap.add_argument("--batch-size", default="448x800", help="the size of the batch's scene pictures")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ["CLIPFOUNDRY_DATA"] = str(out / "data")  # never the repository's own data folder
    sys.path.insert(0, str(ROOT))

    from PIL import Image

    from clipfoundry import config, db
    from clipfoundry.jobs import worker
    from clipfoundry.makers import local_engines, shorts
    from clipfoundry.pipeline import ffmpeg_utils
    from clipfoundry.studio import engine, video_flow
    from clipfoundry.studio import jobs as studio_jobs

    db.init()
    replay = None
    if args.pictures or args.batch:
        replay = _Replay(Path(args.pictures).resolve() if args.pictures else None,
                         config.data_dir() / "engines" / "made", local_engines.module(), record=bool(args.batch))
        local_engines.module = lambda: replay  # type: ignore[assignment]

    queued: list[str] = []
    worker.submit_studio = queued.append  # this script runs the jobs itself, in order

    def run() -> list[dict]:
        done = []
        while queued:
            job_id = queued.pop(0)
            studio_jobs.run(job_id)
            done.append(db.fetch("studio_jobs", job_id))
        return done

    options = {"mode": "paste", "script": Path(args.script).read_text(encoding="utf-8")}
    for key in ("look", "music", "voice"):
        if getattr(args, key):
            options[key] = getattr(args, key)
    if args.captions is not None:
        options["captions"] = args.captions
    if args.speed is not None:
        options["speed"] = args.speed
    for item in args.option:
        key, _, value = item.partition("=")
        options[key.strip()] = _value(value)

    report: dict = {"options": {k: v for k, v in options.items() if k != "script"}, "ok": True}
    started = time.monotonic()
    project = shorts.create("local", "local", name=args.name, options=options)
    jobs = run()
    project = db.fetch("studio_projects", project["id"])
    plan = video_flow.plan_at(project["id"], project["plan_revision"]) if project["plan_revision"] else None
    rows = shorts.ordered(shorts.scene_rows(project["id"]), plan)
    report["made_s"] = round(time.monotonic() - started, 1)
    report["jobs"] = [(j["kind"], j["status"], j["error"]) for j in jobs]
    report["scenes"] = [{"n": n, "status": r["status"], "error": r["error"], "narration": r["narration"],
                         "picture": r["picture_prompt"], "move": r["move"], "seconds": round(r["duration_ms"] / 1000, 2),
                         "info": r["info"]} for n, r in enumerate(rows, 1)]
    if replay is not None:
        report["picture_requests"] = replay.calls
    if args.batch:
        w, h = (int(x) for x in args.batch_size.lower().split("x"))
        items = []
        for c in replay.calls:
            # the character's picture keeps its own shape (3:4), at about the scenes' size
            cast = {"width": round(h * 0.72 * 0.75 / 16) * 16, "height": round(h * 0.72 / 16) * 16} \
                if c["name"] == "character" else {}
            items.append({"name": f"{args.batch_name}/{c['name']}", "prompt": c["prompt"],
                          "negative": c.get("negative") or "", "seed": int(c.get("seed") or 0), **cast,
                          **({"references": [f"{args.batch_name}/character"]} if c.get("references") else {})})
        batch = {"about": f"What ClipForge asks the picture maker for the sample script ({args.name}), in the words "
                          "of the short itself.", "model": "flux2-klein-4b", "width": w, "height": h, "items": items}
        Path(args.batch).write_text(json.dumps(batch, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {len(items)} picture requests to {args.batch}")
        return 0
    if not plan:
        report["ok"] = False
        (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print("no plan was made:", report["jobs"])
        return 1
    view = shorts.view(project, plan)
    report["notes"] = view.get("notes")
    report["plan"] = {"clips": [{k: c.get(k) for k in ("id", "in_ms", "out_ms", "label", "zoom")} for c in plan["clips"]],
                      "captions": plan.get("captions"), "transition": plan.get("transition"),
                      "audio": [{k: a.get(k) for k in ("label", "role", "gain_db", "anchor", "start_ms", "duck")}
                                for a in plan.get("audio") or []],
                      "length_s": round(engine.duration_ms(plan) / 1000, 2)}
    for n, r in enumerate(rows, 1):  # each scene's picture, as the short keeps it
        asset = db.fetch("assets", r["picture_asset_id"]) if r["picture_asset_id"] else None
        if asset and Path(asset["path"]).is_file():
            with Image.open(asset["path"]) as im:
                im.convert("RGB").resize((540, 960)).save(out / f"scene-{n:02d}.jpg", quality=88)

    started = time.monotonic()
    kind = "video_preview" if args.preview else "video_render"
    studio_jobs.enqueue("local", kind, project["id"], project["plan_revision"])
    jobs = run()
    arts = db.select("studio_artifacts", "project_id = ? AND kind = ?", (project["id"], "preview" if args.preview else "final"))
    report["render_s"] = round(time.monotonic() - started, 1)
    report["render_jobs"] = [(j["kind"], j["status"], j["error"]) for j in jobs]
    if not (jobs and jobs[-1]["status"] == "done" and arts):
        report["ok"] = False
        (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print("the render failed:", report["render_jobs"])
        return 1
    final = out / "final.mp4"
    shutil.copyfile(sorted(arts, key=lambda a: a.get("created_at") or 0)[-1]["path"], final)
    length = engine.duration_ms(plan) / 1000
    stills = []
    for text in [t for t in args.stills.split(",") if t.strip()]:
        at = float(text)
        if at >= length:
            continue
        still = out / f"still-{at:05.1f}.jpg"
        subprocess.run([ffmpeg_utils.ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(final),
                        "-frames:v", "1", "-q:v", "3", str(still)], check=True)
        stills.append(still)
    if stills:
        tiles = [Image.open(s).convert("RGB").resize((360, 640)) for s in stills]
        sheet = Image.new("RGB", (360 * len(tiles) + 8 * (len(tiles) - 1), 640), (12, 12, 16))
        for k, tile in enumerate(tiles):
            sheet.paste(tile, (k * 368, 0))
        sheet.save(out / "sheet.jpg", quality=88)
    report["final"] = {"path": str(final), "length_s": round(length, 2), "bytes": final.stat().st_size}
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"made in {report['made_s']} s, rendered in {report['render_s']} s: {final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

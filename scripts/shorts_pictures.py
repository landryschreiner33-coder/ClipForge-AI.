"""Make real pictures for sample animated shorts on a computer that can download the picture model.

    python scripts/shorts_pictures.py --spec scripts/samples/<batch>.json --out <folder> [--data <folder>]

Run by .github/workflows/shorts-samples.yml on a GitHub Linux machine (no graphics card: a picture takes minutes),
because the cloud workspace where ClipForge is developed cannot reach the models. It sets ClipForge's own ComfyUI up
exactly as the app does (scripts/local_engines_check.py), downloads the batch's picture model, and makes each picture
of the batch with the graph the app sends (clipfoundry/engines/graphs.py). Each picture is saved into <out> as a JPEG
as soon as it is made, with a line in <out>/report.json (the words, the seed, the size, the seconds), so a run that
is cut short keeps what it made. --push commits and pushes <out> after every picture (the workflow's own checkout).

The batch file: {"model": "flux2-klein-4b", "width": 576, "height": 1024,
                 "items": [{"name": "after/scene-01", "prompt": "...", "negative": "", "seed": 7,
                            "references": ["after/character"]}]}
`references` are pictures made earlier in the same batch (by name) that the model is shown while it draws.
Nothing of this computer's ClipForge is touched; everything goes into --data (a temporary folder by default).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def log(*parts) -> None:
    print(*parts, flush=True)


def _push(folder: Path, message: str) -> None:
    """Commit `folder` and push it to the branch that is checked out (other pushes may have landed meanwhile)."""
    def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=check)

    branch = os.environ.get("GITHUB_REF_NAME") or git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    git("add", "--", str(folder))
    if not git("diff", "--cached", "--quiet", check=False).returncode:
        return
    git("commit", "-m", message)
    for attempt in range(5):
        if not git("push", "origin", f"HEAD:{branch}", check=False).returncode:
            return
        pulled = git("pull", "--rebase", "origin", branch, check=False)
        log(f"push {attempt + 1} was refused; pulled: {pulled.returncode} {pulled.stderr[-200:]}")
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("the pictures could not be pushed")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default="")
    ap.add_argument("--push", action="store_true", help="commit and push --out after every picture")
    ap.add_argument("--only", default="", help="make only the items whose name starts with this")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    data = Path(args.data) if args.data else Path(tempfile.mkdtemp(prefix="clipforge-shorts-pictures-"))
    data.mkdir(parents=True, exist_ok=True)
    os.environ["CLIPFOUNDRY_DATA"] = str(data)
    os.environ.pop("CLIPFOUNDRY_MODE", None)

    import local_engines_check as lec
    from PIL import Image

    from clipfoundry.engines import catalog, comfy_server, graphs, models, tasks
    from clipfoundry.engines.comfy import Comfy

    report_path = out / "report.json"
    report: dict = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    report.setdefault("pictures", {})
    report["batch"] = Path(args.spec).name
    model = catalog.by_id(spec.get("model") or "flux2-klein-4b")
    if model is None or model.role != "image":
        raise SystemExit(f"no picture model {spec.get('model')!r}")
    width, height = int(spec.get("width") or 576), int(spec.get("height") or 1024)
    items = [i for i in spec["items"] if i["name"].startswith(args.only)]
    todo = [i for i in items if not (out / f"{i['name']}.jpg").is_file()]
    log(f"{len(todo)} of {len(items)} pictures to make with {model.name} at {width}x{height}")
    if not todo:
        return 0

    run = lec.Run(out)
    pngs = data / "sample-pngs"
    failed = 0
    try:
        lec.fill_missing(report, True, [model.id])
        model = catalog.by_id(model.id)
        lec.setup_comfy(report)
        extra = ["--bf16-unet"] if comfy_server.torch_flavor() != "cuda" else []  # 16 GB machines: bf16 on the processor
        lec.start_comfy(run, report, extra)
        started = time.time()
        view = tasks.start(f"Downloading {model.name} (samples)", models.install_steps(model, "clipforge", None),
                           wait=True)
        if view["state"] != "done" or models.missing(model, "clipforge", None):
            raise RuntimeError(f"downloading {model.name} failed: {view.get('error')}")
        report["download_seconds"] = round(time.time() - started)
        client = Comfy(run.base, timeout=120)
        w, h = graphs.picture_size(model, width, height)
        for item in todo:
            name = item["name"]
            dest = out / f"{name}.jpg"
            dest.parent.mkdir(parents=True, exist_ok=True)
            started = time.time()
            try:
                refs = []
                for ref in item.get("references") or []:
                    src = pngs / f"{ref}.png"
                    if not src.is_file():
                        raise RuntimeError(f"the reference picture {ref!r} was not made in this run")
                    refs.append(client.upload_image(src))
                kwargs = {"references": refs} if refs else {}
                graph, steps_node = graphs.picture(model, item["prompt"], item.get("negative") or "", w, h,
                                                   int(item.get("seed") or 0),
                                                   prefix=f"{graphs.PREFIX}/sample-{int(time.time())}", **kwargs)
                files = client.run(graph, timeout_s=5400, steps_node=steps_node, labels=graphs.labels(graph))
                png = pngs / f"{name}.png"   # kept on this machine only (a later item may be shown it)
                png.parent.mkdir(parents=True, exist_ok=True)
                client.download(files[-1], png)
                with Image.open(png) as im:
                    im.convert("RGB").save(dest, "JPEG", quality=90)
                report["pictures"][name] = {"prompt": item["prompt"], "seed": int(item.get("seed") or 0),
                                            "size": [w, h], "references": item.get("references") or [],
                                            "seconds": round(time.time() - started, 1), "model": model.id}
                log(f"made {name} in {report['pictures'][name]['seconds']} s")
            except Exception as exc:  # noqa: BLE001 - one picture never stops the batch
                failed += 1
                report["pictures"][name] = {"prompt": item["prompt"], "error": f"{exc.__class__.__name__}: {exc}"[:600],
                                            "seconds": round(time.time() - started, 1)}
                log(f"!! {name} failed: {exc}\n{traceback.format_exc()[-1500:]}")
            report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            if args.push:
                _push(out, f"Sample pictures: {name} ({Path(args.spec).stem})")
    finally:
        lec.stop_comfy(run)
        try:
            tail = (data / "logs" / "comfyui.log").read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
            log("--- the end of comfyui.log\n" + "\n".join(tail))
        except OSError:
            pass
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

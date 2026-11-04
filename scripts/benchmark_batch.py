"""Capacity benchmark for a ClipForge server (docs/clipforge/FEATURE_CHECKLIST.md, prompt §16.9).

Runs the real Clips pipeline (Highlights or Full stories) over every video in a folder, one after another in one
heavy slot, exactly as the server would, in an isolated data folder, and writes report.json:
source hours, output count and duration, wall time per stage and per video, peak memory (RSS of this process and its
FFmpeg children), peak disk use of the data folder, failures, and whether a day's workload fits in a day.

    CLIPFOUNDRY_DATA=/tmp/bench python scripts/benchmark_batch.py /path/to/authorized/videos --mode full_stories \
        --daily-hours 5 --out /tmp/bench/report.json

Use owner-authorized footage that represents a real day (more than five source hours). Nothing is uploaded. The
report states plainly when the batch is smaller than the daily target or ran somewhere other than the proposed host:
a short clip is never extrapolated into a capacity claim.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _disk(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--mode", choices=("highlights", "full_stories"), default="full_stories")
    ap.add_argument("--daily-hours", type=float, default=5.0, help="source hours the server must handle per day")
    ap.add_argument("--host-label", default=platform.node(), help="e.g. 'Oracle A1 2 OCPU / 12 GB'")
    ap.add_argument("--out", default="benchmark-report.json")
    a = ap.parse_args()
    if not os.environ.get("CLIPFOUNDRY_DATA"):
        print("Set CLIPFOUNDRY_DATA to an empty benchmark folder (never the owner's real data).")
        return 2
    os.environ.setdefault("CLIPFOUNDRY_WORKERS", "off")
    from clipfoundry import config, db
    from clipfoundry.pipeline import process
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe

    db.init()
    data = config.data_dir()
    videos = sorted(p for p in Path(a.folder).iterdir() if p.suffix.lower() in config.VIDEO_EXTENSIONS)
    if not videos:
        print("No videos found.")
        return 2
    peak_disk = [0]
    stop = threading.Event()

    def watch_disk():
        while not stop.wait(5):
            peak_disk[0] = max(peak_disk[0], _disk(data))

    threading.Thread(target=watch_disk, daemon=True).start()
    rows, t_all = [], time.time()
    for v in videos:
        meta = probe(v)
        project = db.create_project(v.stem[:120], status="queued", clip_mode=a.mode)
        pdir = config.projects_dir() / project["id"]
        pdir.mkdir(parents=True)
        src = pdir / ("source" + v.suffix.lower())
        try:
            os.link(v, src)
        except OSError:
            shutil.copy2(v, src)
        db.update_project(project["id"], source_path=str(src))
        stages: dict[str, float] = {}
        last = {"stage": "", "t": time.time()}

        def report(frac: float, msg: str, pid=project["id"]):
            stage = (db.get_project(pid) or {}).get("stage") or msg
            if stage != last["stage"]:
                now = time.time()
                if last["stage"]:
                    stages[last["stage"]] = stages.get(last["stage"], 0.0) + now - last["t"]
                last.update(stage=stage, t=now)

        t0 = time.time()
        error = ""
        try:
            process.run_project(project["id"], JobContext(report))
        except Exception as exc:  # noqa: BLE001 - the report records every failure
            error = str(exc)[:300]
        if last["stage"]:
            stages[last["stage"]] = stages.get(last["stage"], 0.0) + time.time() - last["t"]
        clips = db.list_clips(project["id"])
        rows.append({"file": v.name, "source_seconds": meta["duration"], "wall_seconds": round(time.time() - t0, 1),
                     "stages": {k: round(x, 1) for k, x in stages.items()}, "outputs": len(clips),
                     "output_seconds": round(sum(c.get("duration") or 0 for c in clips if c["status"] == "ready"), 1),
                     "failed_outputs": sum(1 for c in clips if c["status"] == "error"), "error": error})
        print(json.dumps(rows[-1]))
    stop.set()
    peak_disk[0] = max(peak_disk[0], _disk(data))
    wall = time.time() - t_all
    source_h = sum(r["source_seconds"] for r in rows) / 3600
    rss_self = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    rss_children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    hours_per_source_hour = (wall / 3600) / source_h if source_h else None
    daily_wall_h = hours_per_source_hour * a.daily_hours if hours_per_source_hour else None
    verdict = ("unverified: the batch is smaller than the daily target" if source_h < a.daily_hours else
               "fits with headroom" if daily_wall_h is not None and daily_wall_h <= 18 else
               "insufficient: a day's work does not fit in 18 hours of processing")
    report = {"host": a.host_label, "machine": platform.platform(), "cpus": os.cpu_count(), "mode": a.mode,
              "settings": {k: db.get_settings().get(k) for k in ("whisper_model", "whisper_device", "video_preset")},
              "videos": rows, "source_hours": round(source_h, 2), "wall_hours": round(wall / 3600, 2),
              "outputs": sum(r["outputs"] for r in rows), "output_hours": round(sum(r["output_seconds"] for r in rows)
                                                                                 / 3600, 2),
              "failures": [r for r in rows if r["error"] or r["failed_outputs"]],
              "peak_rss_mb": {"app": round(rss_self, 1), "largest_child": round(rss_children, 1)},
              "peak_data_disk_gb": round(peak_disk[0] / 1e9, 2), "retained_disk_gb": round(_disk(data) / 1e9, 2),
              "processing_hours_per_source_hour": round(hours_per_source_hour, 3) if hours_per_source_hour else None,
              "daily_target_source_hours": a.daily_hours, "verdict": verdict}
    Path(a.out).write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("source_hours", "wall_hours", "outputs", "peak_rss_mb",
                                             "peak_data_disk_gb", "verdict")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

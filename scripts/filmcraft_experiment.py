"""Repeatable FilmCraft integration experiment (docs/clipforge/EDITOR_INTEGRATION.md).

Run only with an already-built, owner-approved FilmCraft CLI:

    FILMCRAFT_CLI=/abs/path/filmcraft-cli python scripts/filmcraft_experiment.py --out /tmp/fc-exp

It writes synthetic media only (no owner footage), drives the CLI as a subprocess with a private working folder,
and records every result in report.json. Edit commands it cannot map are recorded as unsupported; nothing is
assumed to work because the CLI exited 0.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clipfoundry.pipeline import audio_timing  # noqa: E402
from clipfoundry.pipeline.ffmpeg_utils import ffmpeg_bin, probe  # noqa: E402

SOURCES = [  # name, fps, sample rate, channels, seconds, tone Hz
    ("a_24fps_44k.mp4", 24, 44100, 2, 6.0, 440),
    ("b_30fps_48k.mp4", 30, 48000, 2, 5.0, 660),
    ("c_25fps_32k_mono.mp4", 25, 32000, 1, 4.0, 550),
]
# Operations the experiment needs, and words to look for in `filmcraft-cli commands --json`.
NEEDED = {"trim": ("trim", "ripple"), "razor": ("razor",), "reorder": ("move", "reorder"), "insert": ("insert",),
          "captions": ("caption", "subtitle"), "music": ("import",), "save": ("save",), "undo": ("undo",)}


def make_media(out: Path) -> list[Path]:
    ff = ffmpeg_bin()
    paths = []
    for name, fps, rate, ch, secs, hz in SOURCES:
        p = out / name
        layout = "mono" if ch == 1 else "stereo"
        subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate={fps}:d={secs}",
                        "-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate={rate}:duration={secs}",
                        "-af", f"aformat=channel_layouts={layout}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(p)], check=True)
        paths.append(p)
    still = out / "broll.png"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=steelblue:s=1280x720:d=1",
                    "-frames:v", "1", str(still)], check=True)
    music = out / "music.m4a"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=20",
                    "-c:a", "aac", str(music)], check=True)
    return [*paths, still, music]


def cli(exe: str, args: list[str], cwd: Path, timeout: float = 1800) -> dict:
    t0 = time.time()
    # A minimal environment: no tokens, no proxy credentials, a private HOME inside the experiment folder.
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(cwd / "home"), "LANG": "C.UTF-8"}
    (cwd / "home").mkdir(exist_ok=True)
    r = subprocess.run([exe, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    return {"args": args, "exit": r.returncode, "seconds": round(time.time() - t0, 2),
            "stdout": r.stdout[-4000:], "stderr": r.stderr[-4000:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    exe = os.environ.get("FILMCRAFT_CLI", "")
    if not exe or not Path(exe).is_file():
        print("Set FILMCRAFT_CLI to an owner-approved, already-built filmcraft-cli binary.")
        return 2
    out = Path(a.out)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    media = make_media(out)
    report: dict = {"filmcraft_cli": exe, "steps": [], "unsupported": [], "checks": {}}
    version = cli(exe, ["--version"], out)
    report["version"] = version["stdout"].strip()
    commands = cli(exe, ["commands", "--json"], out)
    report["steps"].append({k: v for k, v in commands.items() if k != "stdout"})
    listing = commands["stdout"].lower()
    for op, words in NEEDED.items():
        if not any(w in listing for w in words):
            report["unsupported"].append(op)
    project = out / "experiment.fcproj"
    report["steps"].append(cli(exe, ["--project", str(project), "--save", "import", *map(str, media)], out))
    report["steps"].append(cli(exe, ["--project", str(project), "inspect", "sequence"], out))
    export = out / "export.mp4"
    report["steps"].append(cli(exe, ["--project", str(project), "export", str(export)], out))
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    report["peak_child_rss_mb"] = round(usage.ru_maxrss / 1024, 1)
    if export.exists():
        info = probe(export)
        report["checks"]["output"] = {k: info.get(k) for k in ("duration", "width", "height", "fps", "has_audio")}
        try:
            report["checks"]["aac_packet_timing"] = audio_timing.require_valid(export)
        except Exception as exc:  # noqa: BLE001 - the report records the failure itself
            report["checks"]["aac_packet_timing"] = {"ok": False, "error": str(exc)}
    else:
        report["checks"]["output"] = {"ok": False, "error": "export wrote no file"}
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("version", "unsupported", "checks", "peak_child_rss_mb")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

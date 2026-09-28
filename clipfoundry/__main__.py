"""Entry point.

    python -m clipfoundry                 # start the app (http://127.0.0.1:8765)
    python -m clipfoundry --open          # ...and open the browser
    python -m clipfoundry process video.mp4 --count 5   # headless run, no UI
    python -m clipfoundry gpu-check [video.mp4]         # verify that transcription runs on the NVIDIA GPU
    python -m clipfoundry workers                       # autopilot workers (the app starts them by itself)
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _serve(host: str, port: int, open_browser: bool) -> None:
    import uvicorn

    url = f"http://{'127.0.0.1' if host in {'0.0.0.0', '::'} else host}:{port}"
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    _print_transcription_mode()
    print(f"\n  ClipFoundry is running at {url}\n  Press Ctrl+C to stop.\n")
    uvicorn.run("clipfoundry.api:app", host=host, port=port, log_level="warning")


def _print_transcription_mode() -> None:
    from . import db
    from .pipeline import transcribe

    try:
        lines = transcribe.startup_banner(db.get_settings())
    except Exception as exc:  # noqa: BLE001 - never block startup on diagnostics
        lines = [f"Transcription: device check failed ({exc}); CPU will be used if the GPU cannot be."]
    print()
    for line in lines:
        print("  " + line)


def _process(args: argparse.Namespace) -> int:
    from . import config, db
    from .pipeline import process
    from .pipeline.common import JobContext

    db.init()
    src = Path(args.video).resolve()
    if not src.exists() or src.suffix.lower() not in config.VIDEO_EXTENSIONS:
        print(f"Not a supported video file: {src}")
        return 2
    patch = {k: v for k, v in {"ai_provider": args.provider}.items() if v}
    if patch:
        db.save_settings(patch)
    opts = config.validate_settings({k: v for k, v in {
        "clip_count": args.count, "caption_style": args.style, "tracking": args.tracking,
        "layout": args.layout, "silence": args.silence}.items() if v is not None})
    project = db.create_project(src.stem, source_filename=src.name, options=opts, status="processing")
    pdir = config.projects_dir() / project["id"]
    pdir.mkdir(parents=True, exist_ok=True)
    dest = pdir / f"source{src.suffix.lower()}"
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)
    if args.transcript:
        t = Path(args.transcript)
        shutil.copy2(t, pdir / f"imported_transcript{t.suffix.lower()}")
        opts["transcript_file"] = str(pdir / f"imported_transcript{t.suffix.lower()}")
    db.update_project(project["id"], source_path=str(dest), options=opts)

    last = [0.0, ""]

    def report(frac: float, msg: str) -> None:
        if time.time() - last[0] > 1.0 or msg != last[1]:
            last[0], last[1] = time.time(), msg
            print(f"  [{frac * 100:5.1f}%] {msg}", flush=True)

    t0 = time.time()
    process.run_project(project["id"], JobContext(report))
    db.update_project(project["id"], status="ready", progress=1.0, message="Done")
    clips = db.list_clips(project["id"])
    quality = (db.get_project(project["id"]) or {}).get("info", {}).get("quality") or {}
    print(f"\nDone in {time.time() - t0:.0f}s. {len(clips)} clip(s) passed the quality bar"
          f" ({quality.get('evaluated', 0)} candidates evaluated; scores are estimates, not guarantees):")
    for c in clips:
        sub = (c.get("analysis") or {}).get("subscores") or {}
        print(f"  #{c['rank'] + 1}  Viral Potential {c['score']:5.1f}  {c['duration']:5.1f}s  [{c['category']}] {c['title']}")
        if sub:
            print(f"       hook {sub['hook']} / retention {sub['retention']} / context {sub['context']} / "
                  f"engagement {sub['engagement']}  ({(c['analysis'].get('structure') or {}).get('label', '')})")
        print(f"       hook: {c['hook']}")
        print(f"       {c['status']}: {c['output_path'] or c['error']}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="clipfoundry", description="ClipFoundry local AI clipper")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CLIPFOUNDRY_PORT", 8765)))
    parser.add_argument("--open", action="store_true", help="open the browser")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("process", help="process a video without the UI")
    p.add_argument("video")
    p.add_argument("--count", type=int, default=None)
    p.add_argument("--transcript", help="optional .srt/.vtt/.json transcript (skips Whisper)")
    p.add_argument("--style", choices=["clean", "bold", "high_energy", "minimal"])
    p.add_argument("--tracking", choices=["auto", "center", "face", "speaker", "screen"])
    p.add_argument("--layout", choices=["fill", "fit"])
    p.add_argument("--silence", choices=["off", "light", "aggressive"])
    p.add_argument("--provider", choices=["heuristic", "ollama", "openai_compatible", "anthropic"])
    g = sub.add_parser("gpu-check", help="run a real transcription and report whether it used the NVIDIA GPU")
    g.add_argument("media", nargs="?", help="optional video/audio file (its first --seconds are transcribed)")
    g.add_argument("--seconds", type=float, default=None, help="audio length to test (default 300, 120 synthetic)")
    w = sub.add_parser("workers", help="run the autopilot workers (the app normally starts them itself)")
    w.add_argument("--managed", action="store_true", help=argparse.SUPPRESS)  # started by the app: exit with it
    args = parser.parse_args()
    if args.cmd == "workers":
        from .autopilot.host import run_worker_process

        return run_worker_process(managed=args.managed)
    if args.cmd == "process":
        return _process(args)
    if args.cmd == "gpu-check":
        from .gpucheck import run

        return run(args.media, args.seconds)
    _serve(args.host, args.port, args.open)
    return 0


if __name__ == "__main__":
    sys.exit(main())

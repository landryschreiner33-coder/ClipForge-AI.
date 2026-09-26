"""`python -m clipfoundry gpu-check [video]` (or `start.bat gpu-check`, or drag a video onto gpu-check.bat).

Runs a real faster-whisper transcription through the same code path as the app and reports the device and compute
type CTranslate2 actually used, GPU utilization and memory (sampled with nvidia-smi), CPU usage and speed.
"""
from __future__ import annotations

import tempfile
import time
import wave
from pathlib import Path

import numpy as np

from . import db
from .pipeline import cuda, transcribe
from .pipeline.common import JobContext


def _synthetic_wav(path: Path, seconds: float) -> None:
    """Speech-band noise with syllable-like bursts. Enough to keep the encoder and decoder busy (VAD is off)."""
    sr = 16000
    t = np.arange(int(seconds * sr)) / sr
    rng = np.random.default_rng(7)
    voice = sum(np.sin(2 * np.pi * f * t) / (k + 1) for k, f in enumerate((140, 280, 720, 1150, 2400)))
    bursts = (np.sin(2 * np.pi * 3.2 * t) > 0).astype(np.float32)
    sig = 0.25 * voice * bursts + 0.03 * rng.standard_normal(t.size)
    pcm = (np.clip(sig / np.abs(sig).max(), -1, 1) * 20000).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def run(media: str | None, seconds: float | None) -> int:
    settings = db.get_settings()
    print("\n  ClipFoundry GPU check\n  ---------------------")
    st = cuda.probe(refresh=True)
    gpus = st["gpus"]
    names = ", ".join(f"{g['name']} ({g['vram_mb']} MB, driver {g['driver']})" for g in gpus)
    print(f"  NVIDIA GPU          : {names or 'none reported by nvidia-smi'}")
    print(f"  CTranslate2         : {st['ctranslate2'] or 'not installed'} - CUDA devices: {st['devices']}")
    if st["devices"]:
        print(f"  GPU compute types   : {', '.join(st['compute_types']) or 'unknown'}")
    for lib in st["libraries"]:
        where = lib["path"] or lib.get("error", "")
        print(f"  {lib['name']:<20}: {'OK ' if lib['ok'] else 'MISSING '} {lib['what']} {('- ' + where) if where else ''}")
    if st["toolkit"]:
        print(f"  CUDA Toolkit        : {st['toolkit']} (CUDA_PATH; not required, the pip libraries are enough)")
    print()
    for line in transcribe.startup_banner(settings, st):
        print("  " + line)

    with tempfile.TemporaryDirectory(prefix="clipfoundry-gpu-") as tmp:
        wav = Path(tmp) / "check.wav"
        if media:
            from .pipeline.ffmpeg_utils import run as ffmpeg

            src = Path(media)
            if not src.exists():
                print(f"\n  File not found: {src}")
                return 2
            secs = seconds or 300.0
            print(f"\n  Test audio: first {secs:.0f} s of {src.name}")
            ffmpeg(["-t", f"{secs:.3f}", "-i", str(src), "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", str(wav)])
            vad = True
        else:
            secs = seconds or 120.0
            print(f"\n  Test audio: {secs:.0f} s of synthetic sound. For a realistic speed test pass a video:"
                  "\n              start.bat gpu-check \"C:\\path\\to\\video.mp4\"  (or drag it onto gpu-check.bat)")
            _synthetic_wav(wav, secs)
            vad = False
        dur = _wav_seconds(wav)

        last = [""]

        def report(frac: float, msg: str) -> None:
            if msg.split("  ")[0] != last[0]:
                last[0] = msg.split("  ")[0]
                print(f"  ... {last[0]}", flush=True)

        monitor = cuda.GpuMonitor(gpus[0]["index"] if gpus else 0)
        sampling = monitor.start()
        time.sleep(0.6 if sampling else 0)
        baseline = monitor.samples[-1][2] if monitor.samples else None
        try:
            result = transcribe.transcribe(wav, dur, settings, JobContext(report), vad=vad)
        except Exception as exc:  # noqa: BLE001
            monitor.stop()
            print(f"\n  FAIL: transcription did not run: {exc}")
            return 1
        monitor.stop()

    rt = result["runtime"]
    on_gpu = rt["device"] == "cuda"
    print("\n  Result\n  ------")
    print(f"  Device used         : {'GPU' if on_gpu else 'CPU'} - device={rt['device']}, compute_type="
          f"{rt['compute_type']}, model {rt['model']}, beam size {rt['beam_size']}")
    print(f"  Speed               : {rt['audio_seconds']:.0f} s of audio in {rt['seconds']:.1f} s "
          f"({rt['speed']:.1f}x realtime); model load {rt['load_seconds']:.1f} s")
    print(f"  CPU usage           : {rt['cpu_seconds'] / max(rt['seconds'], 0.1):.1f} cores on average "
          f"while transcribing")
    window = monitor.window(rt["started"], rt["ended"])
    if window:
        util = [s[1] for s in window]
        mem = max(s[2] for s in window)
        extra = f" (+{mem - baseline} MB for Whisper)" if baseline is not None else ""
        print(f"  GPU utilization     : average {sum(util) / len(util):.0f}%, peak {max(util)}% "
              f"({len(util)} samples)")
        print(f"  GPU memory          : {mem} MB in use{extra}")
    elif gpus:
        print("  GPU utilization     : no samples (the run was too short to sample)")
    print()
    if on_gpu:
        print(f"  PASS: faster-whisper ran on the GPU ({rt['gpu'] or 'CUDA'}, {rt['compute_type']}).")
        if rt.get("warning"):
            print(f"  Note: {rt['warning']}")
        print("\n  Watching it in Windows Task Manager: Performance > GPU. CUDA work does not appear on the default"
              "\n  \"3D\" graph; click the title of one of the small graphs and choose \"Cuda\" (or \"Compute_0\").")
        return 0
    print("  FAIL: transcription ran on the CPU.")
    reason = rt.get("warning") or transcribe.whisper_plan(settings, st)["reason"]
    print(f"  Reason: {reason}")
    if rt.get("fix"):
        print(f"  Fix: {rt['fix']}")
    return 1

"""`python -m clipfoundry gpu-check [video]`. On Windows: double-click gpu-check.bat or drag a video onto it.

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


def _fail(msg: str, fix: str = "") -> int:
    print(f"\n  FAIL: {msg}")
    if fix:
        print(f"  Fix: {fix}")
    return 1


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

    # The app's own configuration with the device forced to CUDA: same model, compute type, beam size, language.
    plan = transcribe.whisper_plan(settings, st, device="cuda")
    model_name, compute = plan["model"], plan["compute_type"]

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
            try:
                ffmpeg(["-t", f"{secs:.3f}", "-i", str(src), "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", str(wav)])
            except Exception as exc:  # noqa: BLE001 - ffmpeg missing, no audio track, unreadable file
                print(f"\n  Could not read audio from {src.name}: {exc}")
                return 2
            vad = True
        else:
            secs = seconds or 120.0
            print(f"\n  Test audio: {secs:.0f} s of synthetic sound. For a realistic speed test pass a video:"
                  "\n              drag a video onto gpu-check.bat, or run: gpu-check.bat \"C:\\path\\to\\video.mp4\"")
            _synthetic_wav(wav, secs)
            vad = False  # synthetic audio contains no speech, so VAD would skip all of it
        dur = _wav_seconds(wav)

        opts = transcribe.transcribe_options(settings, "cuda", vad)
        print("\n  Configuration (the same code and settings the app uses for GPU transcription):")
        print(f"    model={model_name}  device=cuda  compute_type={compute}  beam_size={opts['beam_size']}  "
              f"language={opts['language'] or 'auto'}  word_timestamps=on  "
              f"vad={'on' if vad else 'off (synthetic audio has no speech)'}")
        if plan["note"]:
            print(f"    Note: {plan['note']}")
        if not st["devices"]:
            return _fail("CTranslate2 reports no CUDA device, so faster-whisper cannot create a model with "
                         "device=\"cuda\" (nothing was downloaded).",
                         st.get("fix") or ("install the latest NVIDIA driver" if gpus else
                                           "this PC has no NVIDIA GPU that CUDA can use"))

        last = [""]

        def report(frac: float, msg: str) -> None:
            if msg.split("  ")[0] != last[0]:
                last[0] = msg.split("  ")[0]
                print(f"  ... {last[0]}", flush=True)

        ctx = JobContext(report)
        monitor = cuda.GpuMonitor(gpus[0]["index"] if gpus else 0)
        sampling = monitor.start()
        time.sleep(0.6 if sampling else 0)
        baseline = monitor.samples[-1][2] if monitor.samples else None
        try:
            print(f"\n  Step 1/2: initializing Whisper '{model_name}' with device=\"cuda\", compute_type=\"{compute}\"")
            try:
                model, loaded = transcribe.load_model(model_name, "cuda", compute, ctx)
            except Exception as exc:  # noqa: BLE001
                return _fail(f"the Whisper model did not initialize on CUDA.\n  CTranslate2 error: {exc}",
                             transcribe._fix_for(exc))  # noqa: SLF001
            print(f"  CTranslate2 loaded the model on device={loaded['device']}, compute_type="
                  f"{loaded['compute_type']} in {loaded['seconds']:.1f} s")
            if loaded["device"] != "cuda":
                return _fail(f"CTranslate2 put the model on {loaded['device']}, not cuda.")

            print("\n  Step 2/2: transcribing on the GPU")
            try:
                result = transcribe.run_model(model, loaded, wav, dur, settings, model_name, "cuda", compute,
                                              ctx, vad=vad)
            except Exception as exc:  # noqa: BLE001 - e.g. cuBLAS is only loaded at the first GPU computation
                return _fail(f"the model initialized on CUDA, but transcription failed on the GPU.\n"
                             f"  CTranslate2 error: {exc}", transcribe._fix_for(exc))  # noqa: SLF001
        finally:
            monitor.stop()

    rt = result["runtime"]
    print("\n  Result\n  ------")
    print(f"  Device used         : GPU - device={rt['device']}, compute_type={rt['compute_type']}, "
          f"model {rt['model']}, beam size {rt['beam_size']}")
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
    print(f"\n  PASS: Whisper '{rt['model']}' initialized on CUDA ({compute}) and transcribed on the GPU"
          f"{' (' + plan['gpu'] + ')' if plan['gpu'] else ''}.")
    if plan["problem"]:
        print("  (The library pre-check warning above was wrong: the GPU works.)")
    print("\n  Watching it in Windows Task Manager: Performance > GPU. CUDA work does not appear on the default"
          "\n  \"3D\" graph; click the title of one of the small graphs and choose \"Cuda\" (or \"Compute_0\").")
    return 0

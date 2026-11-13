"""Local transcription with faster-whisper (word-level timestamps).

Also supports importing an existing SRT/VTT/JSON transcript, which skips
Whisper entirely (word timings are then interpolated inside each cue).

A long recording goes through `transcribe_long`: it is listened to in pieces of about twenty minutes cut where
nobody speaks, each piece is saved as soon as it is done so a restart continues where it stopped, and only one
piece of samples is in memory at a time. The Whisper model is held between pieces and files (`load_model`) and
given back at the end of a batch (`release_model`).
"""
from __future__ import annotations

import gc
import html
import os
import platform
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio, cuda, models
from .common import Cancelled, JobContext, log, read_json, write_json


GPU_MODEL, CPU_MODEL = "large-v3-turbo", "small"
LOW_VRAM_MB = 5000  # below this, int8_float16 keeps large-v3-turbo comfortably inside GPU memory
# Fastest types first. float16 runs on the Tensor Cores of RTX cards (RTX 3050: compute capability 8.6).
_PREFERRED = {"cuda": ["float16", "int8_float16", "int8", "float32"], "cpu": ["int8", "int8_float32", "float32"]}

last_run: dict = {}  # runtime details of the most recent Whisper run (shown on the Dashboard)


def _pick_compute(device: str, requested: str, supported: set[str], vram_mb: int) -> tuple[str, str]:
    note = ""
    if requested and requested != "auto":
        if not supported or requested in supported:
            return requested, ""
        note = f"compute type {requested} is not supported on {device.upper()}"
    order = list(_PREFERRED[device])
    if device == "cuda" and 0 < vram_mb < LOW_VRAM_MB:
        order.remove("int8_float16")
        order.insert(0, "int8_float16")
    choice = next((ct for ct in order if not supported or ct in supported), order[0])
    return choice, (f"{note}; using {choice}" if note else "")


def whisper_plan(settings: dict, status: dict | None = None, device: str | None = None) -> dict:
    """Decide device, compute type and model; `device` forces one (gpu-check forces "cuda").

    CUDA is attempted whenever CTranslate2 reports a CUDA device. The CUDA library pre-check never switches to the
    CPU on its own: it only adds a warning, and a real CUDA failure is what triggers the (reported) CPU fallback.
    """
    status = status if status is not None else cuda.probe()
    want = device or settings.get("whisper_device", "auto") or "auto"
    gpu = status["gpus"][0] if status.get("gpus") else {}
    devices = int(status.get("devices") or 0)
    gpu_name = gpu.get("name") or ("NVIDIA GPU" if devices else "")
    problem = fix = ""
    if want == "cpu":
        device, reason = "cpu", "CPU selected in Settings"
        if devices:
            reason += f" ({gpu_name} is available: set Settings > Transcription > Device to Auto to use it)"
    elif want == "cuda" or devices > 0:
        device = "cuda"
        reason = {"auto": "NVIDIA CUDA GPU detected"}.get(want, "GPU selected in Settings")
        if status.get("libs_ok") is False or not devices:
            problem = status.get("problem") or "CTranslate2 reports no CUDA device."
            fix = status.get("fix") or cuda.DRIVER_FIX
    else:
        device = "cpu"
        problem, fix = status.get("problem", ""), status.get("fix", "")
        reason = problem or "no NVIDIA CUDA GPU detected"
        if sys.platform == "darwin" and platform.machine().lower() == "arm64":
            reason = "Native Apple silicon CPU; this speech engine does not use Metal"
            # CUDA is not an Apple-silicon prerequisite. Preserve genuine missing-engine diagnostics.
            if status.get("ctranslate2"):
                problem = fix = ""
    supported = set(status.get("compute_types") or []) if device == "cuda" else set(cuda.cpu_compute_types())
    compute, note = _pick_compute(device, settings.get("whisper_compute_type", "auto") or "auto", supported,
                                  int(gpu.get("vram_mb") or 0))
    model = settings.get("whisper_model", "auto") or "auto"
    if model == "auto":
        model = GPU_MODEL if device == "cuda" else CPU_MODEL
    return {"mode": "gpu" if device == "cuda" else "cpu", "device": device, "compute_type": compute, "model": model,
            "reason": reason, "gpu": gpu_name, "vram_mb": int(gpu.get("vram_mb") or 0), "problem": problem,
            "fix": fix, "note": note}


def transcribe_options(settings: dict, device: str, vad: bool = True) -> dict:
    """The exact faster-whisper transcribe() arguments the app uses (shared with gpu-check)."""
    return {
        "language": settings.get("language") or None,
        "beam_size": int(settings.get("whisper_beam_size") or 0) or (5 if device == "cuda" else 1),
        "word_timestamps": True,
        "vad_filter": vad,
        "vad_parameters": {"min_silence_duration_ms": 500} if vad else None,
        "condition_on_previous_text": False,
    }


def _gpu_label(plan: dict) -> str:
    vram = f", {plan['vram_mb'] / 1024:.0f} GB" if plan.get("vram_mb") else ""
    return f"{plan['gpu']}{vram}"


def startup_banner(settings: dict, status: dict | None = None) -> list[str]:
    """Console lines saying whether transcription will run in GPU mode or CPU mode, and why."""
    plan = whisper_plan(settings, status)
    pad = " " * 15
    if plan["mode"] == "gpu":
        lines = [f"Transcription: GPU mode - {_gpu_label(plan)} (CUDA)",
                 f"{pad}faster-whisper {plan['model']}, compute type {plan['compute_type']}"]
        if plan["problem"]:
            lines.append(f"{pad}Warning: {plan['problem']}")
            lines.append(f"{pad}The GPU is still tried first; if it fails, transcription falls back to the CPU.")
    else:
        lines = [f"Transcription: CPU mode - faster-whisper {plan['model']}, compute type {plan['compute_type']}",
                 f"{pad}Reason: {plan['reason']}"]
    if plan["fix"]:
        lines.append(f"{pad}Fix: {plan['fix']}")
    if plan["note"]:
        lines.append(f"{pad}Note: {plan['note']}")
    return lines


def whisper_installed() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def model_cached(model: str) -> bool:
    """True when the model is downloaded completely and verified (see pipeline/models.py)."""
    return models.is_ready(model)


def _is_oom(exc: BaseException | None) -> bool:
    return exc is not None and "out of memory" in str(exc).lower()


def _fix_for(exc: BaseException) -> str:
    if isinstance(exc, models.ModelError):
        return exc.fix or models.NET_FIX
    msg = str(exc).lower()
    if _is_oom(exc):
        return "choose a smaller Whisper model or compute type int8_float16 in Settings"
    if any(k in msg for k in ("cublas", "cudnn", "cannot be loaded", "not found")):
        return cuda.GPU_FIX
    if "driver" in msg or "insufficient" in msg:
        return cuda.DRIVER_FIX
    return "run gpu-check.bat for a detailed diagnosis"


class GpuTranscriptionFailed(RuntimeError):
    """The GPU was expected for this transcription, it could not be used, and a CPU fallback is not allowed."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.fix = fix


def _plan_attempts(settings: dict, allow_cpu_fallback: bool) -> tuple[dict, list[tuple[str, str, str]]]:
    """The plan for this machine and the (model, device, compute type) attempts in order: the plan itself, then
    int8_float16 on the GPU (tried only after running out of GPU memory) and, when allowed, the CPU model.

    `allow_cpu_fallback=False` (strict GPU, Autopilot's default) never runs on the CPU when an NVIDIA GPU is
    expected: a GPU that cannot be used raises GpuTranscriptionFailed here, before anything runs.
    """
    status = cuda.probe(refresh=True)
    plan = whisper_plan(settings, status)
    gpu_expected = plan["device"] == "cuda" or (bool(status.get("gpus")) and
                                                 (settings.get("whisper_device") or "auto") != "cpu")
    if not allow_cpu_fallback and gpu_expected and plan["device"] != "cuda":
        raise GpuTranscriptionFailed(f"{plan['problem'] or 'The NVIDIA GPU cannot be used for transcription.'} "
                                     "CPU fallback is off for Autopilot.", plan["fix"] or cuda.DRIVER_FIX)
    if plan["mode"] == "gpu":
        log.info("Transcription: GPU mode - %s", _gpu_label(plan))
        if plan["problem"]:
            log.warning("CUDA pre-check: %s Trying the GPU anyway.", plan["problem"])
    else:
        log.info("Transcription: CPU mode - %s", plan["reason"])
        if plan["fix"]:
            log.warning("GPU not used for transcription. Fix: %s", plan["fix"])
    attempts = [(plan["model"], plan["device"], plan["compute_type"])]
    if plan["device"] == "cuda":
        if plan["compute_type"] != "int8_float16" and "int8_float16" in status.get("compute_types", []):
            attempts.append((plan["model"], "cuda", "int8_float16"))  # only after running out of GPU memory
        auto_model = (settings.get("whisper_model", "auto") or "auto") == "auto"
        if allow_cpu_fallback:
            attempts.append((CPU_MODEL if auto_model else plan["model"], "cpu", "int8"))
    return plan, attempts


def _run_attempts(plan: dict, attempts: list[tuple[str, str, str]], ctx: JobContext, lo: float,
                  allow_cpu_fallback: bool, run: Callable[[str, str, str], dict]) -> dict:
    """Call `run(model, device, compute type)` for the attempts in order until one succeeds, with the fallback rules
    shared by whole files and the pieces of a long recording: a GPU failure falls through to the CPU (loudly), and
    running out of GPU memory first retries the GPU with int8_float16. The result's runtime says what ran and why.
    """
    warning = plan["problem"] if plan["mode"] == "cpu" and plan["fix"] else ""
    fix = plan["fix"]
    last: Exception | None = None
    for i, (model_name, dev, ct) in enumerate(attempts):
        if i and dev == "cuda" and not _is_oom(last):
            continue
        log.info("Transcription starting: device=%s compute_type=%s model=%s", dev, ct, model_name)
        try:
            result = run(model_name, dev, ct)
        except Cancelled:
            raise
        except Exception as exc:  # GPU runtime missing (cuBLAS/cuDNN), out of memory, driver, ...
            last = exc
            fix = _fix_for(exc)
            log.warning("Transcription on device=%s compute_type=%s failed: %s", dev, ct, exc)
            if dev == "cuda":
                warning = (f"Whisper '{model_name}' could not be prepared: {exc}" if isinstance(exc, models.ModelError)
                           else f"GPU transcription failed ({ct}): {str(exc).strip()[:300]}")
                nxt = next((a for a in attempts[i + 1:] if a[1] == "cpu" or _is_oom(exc)), None)
                if nxt:
                    log.warning("Falling back to device=%s compute_type=%s model=%s. Fix: %s", nxt[1], nxt[2],
                                nxt[0], fix)
                    ctx.progress(lo, f"GPU transcription failed, continuing on {nxt[1].upper()} ({nxt[2]})")
            release_model()  # a model that just failed is not worth holding: free its memory before the next attempt
            continue
        rt = result["runtime"]
        if dev == "cuda" and i:
            warning = f"Ran out of GPU memory with {plan['compute_type']}; used {ct} instead."
            fix = ""
        rt.update({"gpu": plan["gpu"] if dev == "cuda" else "", "warning": warning if warning else "",
                   "fix": fix if warning else ""})
        log.info("Transcription finished on device=%s compute_type=%s: %.0f s of audio in %.1f s (%.1fx realtime)",
                 rt["device"], rt["compute_type"], rt["audio_seconds"], rt["seconds"], rt["speed"])
        last_run.clear()
        last_run.update(rt, at=time.time())
        return result
    if plan["device"] == "cuda" and not allow_cpu_fallback:
        raise GpuTranscriptionFailed(f"GPU transcription failed and CPU fallback is off for Autopilot: {last}", fix)
    raise RuntimeError(f"Transcription failed: {last}")


def transcribe(audio_path: Path, duration: float, settings: dict, ctx: JobContext,
               lo: float = 0.0, hi: float = 1.0, vad: bool = True, allow_cpu_fallback: bool = True) -> dict:
    """Transcribe a whole file with word timestamps (`transcribe_long` cuts a long recording into pieces).

    `allow_cpu_fallback=False` (strict GPU, Autopilot's default) never runs on the CPU when an NVIDIA GPU is
    expected: a CUDA failure raises GpuTranscriptionFailed instead. The manual workflow keeps the visible CPU
    fallback. Progress maps the file onto lo..hi.
    """
    plan, attempts = _plan_attempts(settings, allow_cpu_fallback)

    def run(model_name: str, device: str, compute: str) -> dict:
        return _run_whisper(audio_path, duration, settings, model_name, device, compute, ctx, lo, hi, vad)

    return _run_attempts(plan, attempts, ctx, lo, allow_cpu_fallback, run)


# ------------------------------------------------------------------ long recordings
def _hms(seconds: float) -> str:
    """h:mm:ss, always with the hour, so positions in a long recording line up."""
    h, rem = divmod(int(max(0.0, seconds)), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def part_bounds(audio_path: Path, duration: float, chunk_s: float) -> list[tuple[float, float]]:
    """The [start, end) pieces of a long recording: one every `chunk_s`, the last up to 1.25 × `chunk_s` so there is
    no tiny tail, and every cut moved to the quietest moment within 30 s of the nominal boundary."""
    count = int(duration // chunk_s)
    if duration - count * chunk_s > 0.25 * chunk_s:
        count += 1
    radius = min(30.0, chunk_s / 4)  # the cuts stay in order whatever chunk_s is
    cuts = [0.0] + [audio.quiet_point(audio_path, k * chunk_s, radius_s=radius) for k in range(1, count)] + [duration]
    return list(zip(cuts, cuts[1:]))


def _saved_part(path: Path, start: float, end: float) -> dict | None:
    """The piece an earlier run saved at `path`, if it covers the planned [start, end) (within 10 ms)."""
    part = read_json(path, None)
    if not isinstance(part, dict) or not isinstance(part.get("result"), dict):
        return None
    result = part["result"]
    if not isinstance(result.get("segments"), list) or not isinstance(result.get("runtime"), dict):
        return None
    try:
        same = abs(float(part["start"]) - start) <= 0.01 and abs(float(part["end"]) - end) <= 0.01
    except (KeyError, TypeError, ValueError):
        return None
    return part if same else None


def _transcribe_piece(audio_path: Path, settings: dict, ctx: JobContext, plan: dict,
                      attempts: list[tuple[str, str, str]], start: float, end: float, lo: float, hi: float,
                      vad: bool, allow_cpu_fallback: bool, report: Callable[[float], None]) -> dict:
    """One piece of a long recording, [start, end) seconds, through the same attempts as a whole file."""
    samples = audio.read_samples(audio_path, start, end)

    def run(model_name: str, device: str, compute: str) -> dict:
        return _run_whisper(audio_path, end - start, settings, model_name, device, compute, ctx, lo, hi, vad,
                            samples=samples, offset_s=start, report_position=report)

    return _run_attempts(plan, attempts, ctx, lo, allow_cpu_fallback, run)


def merge_parts(parts: list[dict], duration: float) -> dict:
    """One transcript from the pieces of a long recording: segments in order, a sentence heard twice at a seam
    dropped, times monotonic, the language of the first piece that heard one, and a runtime that sums the pieces'
    work (with `parts` and `resumed` counts; device, compute type and model are those of the last piece run)."""
    segments: list[dict] = []
    for part in parts:
        segs = [dict(s, words=[dict(w) for w in s.get("words", [])]) for s in part["result"]["segments"]]
        if (segments and segs and segs[0]["text"] == segments[-1]["text"]
                and abs(segs[0]["start"] - segments[-1]["end"]) <= 1.0):
            segs.pop(0)  # the same sentence heard at the end of one piece and the start of the next
        segments.extend(segs)
    last_word: dict | None = None
    for i, seg in enumerate(segments):
        if i and seg["start"] < segments[i - 1]["start"]:
            seg["start"] = segments[i - 1]["start"]
        seg["end"] = max(seg["end"], seg["start"])
        for word in seg["words"]:
            if last_word is not None and word["start"] < last_word["start"]:
                word["start"] = last_word["start"]
            if word["end"] < word["start"]:
                word["end"] = round(word["start"] + 0.05, 3)
            last_word = word
    runtimes = [part["result"]["runtime"] for part in parts]

    def numbers(key: str) -> list[float]:
        return [float(rt[key]) for rt in runtimes if isinstance(rt.get(key), (int, float))]

    last = next((part["result"] for part in reversed(parts) if not part.get("resumed")), parts[-1]["result"])
    seconds = sum(numbers("seconds"))
    flagged = next((rt for rt in runtimes if rt.get("warning")), {})
    runtime = dict(last["runtime"])
    runtime.update({
        "seconds": round(seconds, 1), "audio_seconds": round(duration, 1),
        "speed": round(duration / max(seconds, 1e-6), 1),
        "load_seconds": round(sum(numbers("load_seconds")), 1), "cpu_seconds": round(sum(numbers("cpu_seconds")), 1),
        "started": min(numbers("started"), default=time.time()), "ended": max(numbers("ended"), default=time.time()),
        "parts": len(parts), "resumed": sum(1 for part in parts if part.get("resumed")),
        "warning": flagged.get("warning", ""), "fix": flagged.get("fix", ""),
    })
    language = next((part["result"].get("language") for part in parts if part["result"].get("language")), "")
    return {"language": language, "duration": duration, "source": last["source"], "segments": segments,
            "runtime": runtime}


def transcribe_long(audio_path: Path, duration: float, settings: dict, ctx: JobContext, *, parts_dir: Path,
                    chunk_s: float = 1200.0, lo: float = 0.0, hi: float = 1.0, vad: bool = True,
                    allow_cpu_fallback: bool = True, label: str = "", keep_parts: bool = False) -> dict:
    """Transcribe a recording of any length, in pieces when it is long, with the same result as `transcribe()`.

    Up to 1.25 × `chunk_s` of sound is one `transcribe()` call. Longer sound is cut into pieces of about `chunk_s`
    (see `part_bounds`), each piece is read from the file on its own (`audio.read_samples`), run through the same
    device and compute fallback as a whole file, and saved at once as `parts_dir/part-NNNN.json`
    ({"start", "end", "result"}); a piece already saved for the same [start, end) is reused, so a crash, a closed
    app or a cancel (`ctx.check()` between pieces) loses at most the piece being listened to. The pieces are merged
    (`merge_parts`) and `parts_dir` is deleted unless `keep_parts` is set. Progress maps the whole recording onto
    lo..hi by time position with the message "<label or Transcribing>  h:mm:ss/h:mm:ss" (the caller passes the
    file's name as `label`). The runtime carries `parts` (pieces) and `resumed` (pieces reused from disk). The
    Whisper model stays loaded between pieces; the caller releases it with `release_model()` when its batch is done.
    """
    if duration <= chunk_s * 1.25:
        result = transcribe(audio_path, duration, settings, ctx, lo, hi, vad, allow_cpu_fallback)
        # a stand-in `transcribe` (the tests', or a caller's) may return segments alone: the runtime is added to
        result.setdefault("runtime", {}).update(parts=1, resumed=0)
        last_run.update(parts=1, resumed=0)
        return result
    bounds = part_bounds(audio_path, duration, chunk_s)
    plan, attempts = _plan_attempts(settings, allow_cpu_fallback)
    parts_dir.mkdir(parents=True, exist_ok=True)
    name, whole = label or "Transcribing", _hms(duration)

    def report(position: float) -> None:
        ctx.progress(lo + (hi - lo) * min(1.0, position / duration), f"{name}  {_hms(position)}/{whole}")

    parts: list[dict] = []
    for k, (start, end) in enumerate(bounds):
        ctx.check()
        path = parts_dir / f"part-{k:04d}.json"
        part = _saved_part(path, start, end)
        if part is not None:
            log.info("Transcription piece %d/%d (%s-%s) reused from %s", k + 1, len(bounds), _hms(start), _hms(end),
                     path.name)
            part["resumed"] = True
            parts.append(part)
            report(end)
            continue
        report(start)
        piece_lo, piece_hi = lo + (hi - lo) * start / duration, lo + (hi - lo) * end / duration
        result = _transcribe_piece(audio_path, settings, ctx, plan, attempts, start, end, piece_lo, piece_hi, vad,
                                   allow_cpu_fallback, report)
        rt = result["runtime"]
        done = (rt["model"], rt["requested_device"], rt["requested_compute_type"])
        if done in attempts:
            attempts = attempts[attempts.index(done):]  # the next pieces start from what worked, not from the plan
        part = {"start": start, "end": end, "result": result}
        write_json(path, part)
        parts.append(part)
    merged = merge_parts(parts, duration)
    last_run.clear()
    last_run.update(merged["runtime"], at=time.time())
    if not keep_parts:
        shutil.rmtree(parts_dir, ignore_errors=True)  # the caller stores the merged transcript
    return merged


# ------------------------------------------------------------------ the model
_CUDA_WORDS = ("cuda", "cublas", "cudnn", "out of memory", "device", "driver")
_FILE_WORDS = ("model.bin", "config.json", "vocabulary", "tokenizer", "preprocessor", "unable to open", "parse",
               "json", "end of file", "eof", "corrupt", "invalid", "no such file", "cannot find")

_held: dict | None = None  # the Whisper model kept between pieces and files: {"key", "model", "loaded"}
_held_lock = threading.Lock()


def _model_file_error(exc: BaseException) -> bool:
    """Errors that point at damaged model files (worth one repair), never at CUDA problems."""
    msg = str(exc).lower()
    if any(w in msg for w in _CUDA_WORDS):
        return False
    return isinstance(exc, (OSError, ValueError)) or any(w in msg for w in _FILE_WORDS)


def prepare_model(model_name: str, ctx: JobContext | None = None, lo: float = 0.0) -> Path:
    """Download/verify/repair the model files before WhisperModel ever sees them."""
    ctx = ctx or JobContext()
    if not model_cached(model_name):
        ctx.progress(lo, f"Checking Whisper '{model_name}' model files...")

    def report(done: int, total: int) -> None:
        ctx.progress(lo, f"Downloading Whisper '{model_name}' (first run only)  {done / 1e6:,.0f} / {total / 1e6:,.0f} MB")

    return models.ensure_model(model_name, report)


def _new_whisper(path: Path, device: str, compute: str) -> object:
    """A fresh WhisperModel: CTranslate2 loads the files here (imported late because faster-whisper is optional)."""
    from faster_whisper import WhisperModel

    return WhisperModel(str(path), device=device, compute_type=compute, cpu_threads=min(os.cpu_count() or 4, 8))


def _create_model(model_name: str, path: Path, device: str, compute: str, ctx: JobContext,
                  lo: float) -> tuple[object, dict]:
    """Load the model from its verified files, repairing them once if they turn out to be damaged."""
    cuda.prepare()
    where = f"{'GPU' if device == 'cuda' else 'CPU'} ({device}, {compute})"
    ctx.progress(lo, f"Loading Whisper '{model_name}' on {where}...")
    t_load = time.time()
    try:
        model = _new_whisper(path, device, compute)
    except Exception as exc:  # noqa: BLE001
        if not _model_file_error(exc) or Path(model_name).is_dir():
            raise
        log.warning("Whisper '%s' could not be loaded from %s (%s); re-checking the files", model_name, path, exc)
        models.mark_suspect(model_name)
        path = prepare_model(model_name, ctx, lo)  # re-verifies every hash, re-downloads bad files
        model = _new_whisper(path, device, compute)
    loaded = {"device": str(getattr(model.model, "device", device)),
              "compute_type": str(getattr(model.model, "compute_type", compute)),
              "seconds": round(time.time() - t_load, 1), "path": str(path)}
    log.info("Whisper '%s' loaded by CTranslate2 on %s/%s in %.1f s from %s", model_name, loaded["device"],
             loaded["compute_type"], loaded["seconds"], path)
    return model, loaded


def _drop_held() -> None:
    """Forget the held model and collect it so CTranslate2 frees its memory. The caller holds `_held_lock`."""
    global _held
    if _held is None:
        return
    key = _held["key"]
    _held = None
    gc.collect()
    log.info("Whisper '%s' released from %s/%s", key["model"], key["device"], key["compute_type"])


def load_model(model_name: str, device: str, compute: str, ctx: JobContext | None = None,
               lo: float = 0.0) -> tuple[object, dict]:
    """The faster-whisper model and what CTranslate2 actually loaded it on.

    The model is held once loaded: asking again for the same model, device, compute type and model folder returns
    the held one (its `loaded` then says `seconds` 0 and `reused` True), so the pieces of a long recording and the
    files of a batch share one load instead of reloading a gigabyte for each. Asking for a different one releases
    the held model first, so only one is ever in GPU memory. The heavy worker runs one job at a time; whoever runs
    a batch (the studio build job) calls `release_model()` at the end to give the GPU back to the local AI model.
    """
    global _held
    ctx = ctx or JobContext()
    path = prepare_model(model_name, ctx, lo)  # a few stat() calls once the files are verified
    key = {"model": model_name, "device": device, "compute_type": compute, "path": str(path)}
    with _held_lock:
        if _held is not None and _held["key"] == key:
            log.info("Whisper '%s' is already loaded on %s/%s: reusing it", model_name, _held["loaded"]["device"],
                     _held["loaded"]["compute_type"])
            return _held["model"], dict(_held["loaded"], seconds=0.0, reused=True)
        _drop_held()  # a different model: free its memory before the new one loads
    model, loaded = _create_model(model_name, path, device, compute, ctx, lo)  # nothing is held while this runs
    with _held_lock:
        _drop_held()  # a model another thread loaded meanwhile (the worker never does): the newest one is held
        _held = {"key": key, "model": model, "loaded": loaded}
    return model, loaded


def release_model() -> None:
    """Drop the held Whisper model so its (GPU) memory is free for the local AI model; the next load loads again."""
    with _held_lock:
        _drop_held()


def held_model() -> dict | None:
    """The held model's key (model, device, compute_type, path) with its `loaded` details, or None (Dashboard)."""
    with _held_lock:
        if _held is None:
            return None
        return {**_held["key"], "loaded": dict(_held["loaded"])}


def run_model(model, loaded: dict, audio_path: Path, duration: float, settings: dict, model_name: str,
              device: str, compute: str, ctx: JobContext, lo: float = 0.0, hi: float = 1.0,
              vad: bool = True, *, samples: np.ndarray | None = None, offset_s: float = 0.0,
              report_position: Callable[[float], None] | None = None) -> dict:
    """Transcribe the file, or `samples` (a stretch of it that starts `offset_s` seconds in), with a loaded model.

    Every segment and word time is in the file's own time: `offset_s` is added before it is stored. Progress maps
    the audio onto lo..hi after each decoded segment; `report_position` (called with the position in seconds)
    replaces that message when the caller reports the whole recording itself (`transcribe_long`).
    """
    opts = transcribe_options(settings, device, vad)
    where = f"{'GPU' if device == 'cuda' else 'CPU'} ({device}, {compute})"
    t0, cpu0 = time.time(), time.process_time()
    if samples is None:
        samples = audio.read_samples(Path(audio_path))  # not the path: faster-whisper's PyAV decode breaks on PyAV 19
    segments, info = model.transcribe(samples, **opts)  # type: ignore[attr-defined]
    del samples  # a 4-hour source is ~1 GB of samples: don't hold it here while the segments decode
    total = duration or float(getattr(info, "duration", 0) or 0) or 1.0
    label = f"Transcribing on {where}, {model_name}"
    out_segments = []
    for seg in segments:
        ctx.check()
        words = [
            {"start": round(w.start + offset_s, 3), "end": round(w.end + offset_s, 3), "w": w.word.strip(),
             "p": round(float(w.probability), 3)}
            for w in (seg.words or [])
            if w.word and w.word.strip()
        ]
        out_segments.append({"start": round(seg.start + offset_s, 3), "end": round(seg.end + offset_s, 3),
                             "text": seg.text.strip(), "words": words})
        if report_position is not None:
            report_position(offset_s + seg.end)
        else:
            ctx.progress(lo + (hi - lo) * min(1.0, seg.end / total),
                         f"{label}  {int(seg.end // 60)}:{int(seg.end % 60):02d}"
                         f" / {int(total // 60)}:{int(total % 60):02d}")
    t1 = time.time()
    secs = max(t1 - t0, 1e-6)
    return {
        "language": getattr(info, "language", "") or "",
        "duration": total,
        "source": f"faster-whisper:{model_name}:{loaded['device']}",
        "segments": out_segments,
        "runtime": {"model": model_name, "device": loaded["device"], "compute_type": loaded["compute_type"],
                    "requested_device": device, "requested_compute_type": compute, "beam_size": opts["beam_size"],
                    "load_seconds": loaded["seconds"], "seconds": round(secs, 1),
                    "audio_seconds": round(total, 1), "speed": round(total / secs, 1),
                    "cpu_seconds": round(time.process_time() - cpu0, 1), "started": t0, "ended": t1},
    }


def _run_whisper(audio_path: Path, duration: float, settings: dict, model_name: str, device: str,
                 compute: str, ctx: JobContext, lo: float, hi: float, vad: bool = True, *,
                 samples: np.ndarray | None = None, offset_s: float = 0.0,
                 report_position: Callable[[float], None] | None = None) -> dict:
    model, loaded = load_model(model_name, device, compute, ctx, lo)
    return run_model(model, loaded, audio_path, duration, settings, model_name, device, compute, ctx, lo, hi, vad,
                     samples=samples, offset_s=offset_s, report_position=report_position)


# ------------------------------------------------------------------ import
_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?")


def _ts(text: str) -> float:
    m = _TIME.search(text)
    if not m:
        raise ValueError(f"bad timestamp {text!r}")
    h, mnt, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + int(s) + (int(ms.ljust(3, "0")) / 1000 if ms else 0.0)


def _interp_words(text: str, start: float, end: float) -> list[dict]:
    tokens = text.split()
    if not tokens:
        return []
    weights = [len(t) + 1 for t in tokens]
    total = sum(weights)
    span = max(0.05, end - start)
    words, t = [], start
    for tok, wgt in zip(tokens, weights):
        d = span * wgt / total
        words.append({"start": round(t, 3), "end": round(t + d * 0.92, 3), "w": tok})  # no confidence: not measured
        t += d
    return words


def parse_subtitles(raw: str) -> list[dict]:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    segments = []
    for block in re.split(r"\n\s*\n", raw):
        lines = [ln.strip() for ln in block.strip().split("\n") if ln.strip()]
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if idx is None:
            continue
        a, b = lines[idx].split("-->", 1)
        try:
            start, end = _ts(a), _ts(b.strip().split(" ")[0])
        except ValueError:
            continue
        text = " ".join(lines[idx + 1:])
        text = re.sub(r"<[^>]+>|\{[^}]*\}", "", html.unescape(text)).strip()
        if not text or end <= start:
            continue
        segments.append({"start": start, "end": end, "text": text, "words": _interp_words(text, start, end)})
    return segments


def import_transcript(path: Path, duration: float) -> dict:
    if path.suffix.lower() == ".json":
        data = read_json(path, {})
        segs = data.get("segments") if isinstance(data, dict) else None
        if not segs:
            raise ValueError("JSON transcript must contain a 'segments' list")
        for s in segs:
            if not s.get("words"):
                s["words"] = _interp_words(s.get("text", ""), float(s["start"]), float(s["end"]))
        return {"language": data.get("language", ""), "duration": duration, "source": "import:json",
                "segments": segs}
    segs = parse_subtitles(path.read_text(encoding="utf-8-sig", errors="replace"))
    if not segs:
        raise ValueError("No subtitle cues found in the transcript file")
    return {"language": "", "duration": duration, "source": f"import:{path.suffix.lower()[1:]}", "segments": segs}


def flatten_words(transcript: dict) -> list[dict]:
    words = []
    for seg in transcript.get("segments", []):
        for w in seg.get("words", []):
            if w.get("w"):
                word = {"start": float(w["start"]), "end": float(w["end"]), "w": str(w["w"])}
                if w.get("p") is not None:
                    word["p"] = float(w["p"])  # Whisper word confidence, used for the speaker clarity estimate
                words.append(word)
    words.sort(key=lambda w: w["start"])
    # enforce monotonic, non-overlapping timings
    for i in range(1, len(words)):
        if words[i]["start"] < words[i - 1]["start"]:
            words[i]["start"] = words[i - 1]["start"]
        if words[i]["end"] < words[i]["start"]:
            words[i]["end"] = words[i]["start"] + 0.05
    return words

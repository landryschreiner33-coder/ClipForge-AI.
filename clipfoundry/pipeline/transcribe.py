"""Local transcription with faster-whisper (word-level timestamps).

Also supports importing an existing SRT/VTT/JSON transcript, which skips
Whisper entirely (word timings are then interpolated inside each cue).
"""
from __future__ import annotations

import gc
import html
import os
import re
import time
from pathlib import Path

from .. import config
from . import cuda, models
from .common import Cancelled, JobContext, log, read_json


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


def transcribe(audio_path: Path, duration: float, settings: dict, ctx: JobContext,
               lo: float = 0.0, hi: float = 1.0, vad: bool = True) -> dict:
    status = cuda.probe(refresh=True)
    plan = whisper_plan(settings, status)
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
        attempts.append((CPU_MODEL if auto_model else plan["model"], "cpu", "int8"))
    warning = plan["problem"] if plan["mode"] == "cpu" and plan["fix"] else ""
    fix = plan["fix"]
    last: Exception | None = None
    for i, (model_name, dev, ct) in enumerate(attempts):
        if i and dev == "cuda" and not _is_oom(last):
            continue
        log.info("Transcription starting: device=%s compute_type=%s model=%s", dev, ct, model_name)
        try:
            result = _run_whisper(audio_path, duration, settings, model_name, dev, ct, ctx, lo, hi, vad)
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
            gc.collect()  # release GPU memory before the next attempt
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
    raise RuntimeError(f"Transcription failed: {last}")


_CUDA_WORDS = ("cuda", "cublas", "cudnn", "out of memory", "device", "driver")
_FILE_WORDS = ("model.bin", "config.json", "vocabulary", "tokenizer", "preprocessor", "unable to open", "parse",
               "json", "end of file", "eof", "corrupt", "invalid", "no such file", "cannot find")


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


def load_model(model_name: str, device: str, compute: str, ctx: JobContext | None = None,
               lo: float = 0.0) -> tuple[object, dict]:
    """Create the faster-whisper model and return it with what CTranslate2 actually loaded it on."""
    cuda.prepare()
    from faster_whisper import WhisperModel

    ctx = ctx or JobContext()
    path = prepare_model(model_name, ctx, lo)
    where = f"{'GPU' if device == 'cuda' else 'CPU'} ({device}, {compute})"
    ctx.progress(lo, f"Loading Whisper '{model_name}' on {where}...")
    t_load = time.time()
    threads = min(os.cpu_count() or 4, 8)
    try:
        model = WhisperModel(str(path), device=device, compute_type=compute, cpu_threads=threads)
    except Exception as exc:  # noqa: BLE001
        if not _model_file_error(exc) or Path(model_name).is_dir():
            raise
        log.warning("Whisper '%s' could not be loaded from %s (%s); re-checking the files", model_name, path, exc)
        models.mark_suspect(model_name)
        path = prepare_model(model_name, ctx, lo)  # re-verifies every hash, re-downloads bad files
        model = WhisperModel(str(path), device=device, compute_type=compute, cpu_threads=threads)
    loaded = {"device": str(getattr(model.model, "device", device)),
              "compute_type": str(getattr(model.model, "compute_type", compute)),
              "seconds": round(time.time() - t_load, 1), "path": str(path)}
    log.info("Whisper '%s' loaded by CTranslate2 on %s/%s in %.1f s from %s", model_name, loaded["device"],
             loaded["compute_type"], loaded["seconds"], path)
    return model, loaded


def run_model(model, loaded: dict, audio_path: Path, duration: float, settings: dict, model_name: str,
              device: str, compute: str, ctx: JobContext, lo: float = 0.0, hi: float = 1.0,
              vad: bool = True) -> dict:
    opts = transcribe_options(settings, device, vad)
    where = f"{'GPU' if device == 'cuda' else 'CPU'} ({device}, {compute})"
    t0, cpu0 = time.time(), time.process_time()
    segments, info = model.transcribe(str(audio_path), **opts)  # type: ignore[attr-defined]
    total = duration or float(getattr(info, "duration", 0) or 0) or 1.0
    label = f"Transcribing on {where}, {model_name}"
    out_segments = []
    for seg in segments:
        ctx.check()
        words = [
            {"start": round(w.start, 3), "end": round(w.end, 3), "w": w.word.strip(),
             "p": round(float(w.probability), 3)}
            for w in (seg.words or [])
            if w.word and w.word.strip()
        ]
        out_segments.append({"start": round(seg.start, 3), "end": round(seg.end, 3),
                             "text": seg.text.strip(), "words": words})
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
                 compute: str, ctx: JobContext, lo: float, hi: float, vad: bool = True) -> dict:
    model, loaded = load_model(model_name, device, compute, ctx, lo)
    return run_model(model, loaded, audio_path, duration, settings, model_name, device, compute, ctx, lo, hi, vad)


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
        words.append({"start": round(t, 3), "end": round(t + d * 0.92, 3), "w": tok, "p": 1.0})
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
                words.append({"start": float(w["start"]), "end": float(w["end"]), "w": str(w["w"])})
    words.sort(key=lambda w: w["start"])
    # enforce monotonic, non-overlapping timings
    for i in range(1, len(words)):
        if words[i]["start"] < words[i - 1]["start"]:
            words[i]["start"] = words[i - 1]["start"]
        if words[i]["end"] < words[i]["start"]:
            words[i]["end"] = words[i]["start"] + 0.05
    return words

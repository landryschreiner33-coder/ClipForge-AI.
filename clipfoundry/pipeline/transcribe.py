"""Local transcription with faster-whisper (word-level timestamps).

Also supports importing an existing SRT/VTT/JSON transcript, which skips
Whisper entirely (word timings are then interpolated inside each cue).
"""
from __future__ import annotations

import html
import os
import re
from pathlib import Path

from .. import config
from .common import Cancelled, JobContext, log, read_json


def resolve_whisper(settings: dict) -> tuple[str, str, str]:
    device = settings.get("whisper_device", "auto")
    if device == "auto":
        device = "cuda" if cuda_available() else "cpu"
    compute = settings.get("whisper_compute_type", "auto")
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    model = settings.get("whisper_model", "auto") or "auto"
    if model == "auto":
        model = "large-v3-turbo" if device == "cuda" else "small"
    return model, device, compute


_dll_dirs_added = False


def add_nvidia_dll_dirs() -> None:
    """Windows: expose cuBLAS/cuDNN DLLs from the optional `nvidia-*` pip wheels to CTranslate2."""
    global _dll_dirs_added
    if _dll_dirs_added or os.name != "nt":
        return
    _dll_dirs_added = True
    import site
    import sys

    roots = [Path(p) for p in site.getsitepackages() + [site.getusersitepackages()]] + [Path(sys.prefix) / "Lib" / "site-packages"]
    for root in roots:
        for bin_dir in (root / "nvidia").glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))  # type: ignore[attr-defined]
            except (OSError, AttributeError):
                pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def cuda_available() -> bool:
    add_nvidia_dll_dirs()
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def whisper_installed() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def model_cached(model: str) -> bool:
    root = config.models_dir()
    slug = model.replace("/", "--")
    return any(slug in p.name for p in root.glob("models--*")) or (Path(model).is_dir())


def transcribe(audio_path: Path, duration: float, settings: dict, ctx: JobContext,
               lo: float = 0.0, hi: float = 1.0) -> dict:
    model_name, device, compute = resolve_whisper(settings)
    attempts = [(device, compute)]
    if device == "cuda":
        attempts.append(("cpu", "int8"))
    last: Exception | None = None
    for dev, ct in attempts:
        try:
            return _run_whisper(audio_path, duration, settings, model_name, dev, ct, ctx, lo, hi)
        except Cancelled:
            raise
        except Exception as exc:  # GPU runtime missing (cuDNN/cuBLAS), OOM, ...
            last = exc
            log.warning("Whisper on %s/%s failed: %s", dev, ct, exc)
            if dev == "cuda":
                ctx.progress(lo, "GPU transcription unavailable, falling back to CPU")
    raise RuntimeError(f"Transcription failed: {last}")


def _run_whisper(audio_path: Path, duration: float, settings: dict, model_name: str, device: str,
                 compute: str, ctx: JobContext, lo: float, hi: float) -> dict:
    add_nvidia_dll_dirs()
    from faster_whisper import WhisperModel

    if not model_cached(model_name):
        ctx.progress(lo, f"Downloading Whisper '{model_name}' model (first run only)...")
    else:
        ctx.progress(lo, f"Loading Whisper '{model_name}' on {device.upper()}...")
    threads = min(os.cpu_count() or 4, 8)
    model = WhisperModel(model_name, device=device, compute_type=compute,
                         download_root=str(config.models_dir()), cpu_threads=threads)
    beam = int(settings.get("whisper_beam_size") or 0) or (5 if device == "cuda" else 1)
    segments, info = model.transcribe(
        str(audio_path),
        language=settings.get("language") or None,
        beam_size=beam,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
    )
    total = duration or float(getattr(info, "duration", 0) or 0) or 1.0
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
                     f"Transcribing ({model_name}, {device.upper()})  {int(seg.end // 60)}:{int(seg.end % 60):02d}"
                     f" / {int(total // 60)}:{int(total % 60):02d}")
    return {
        "language": getattr(info, "language", "") or "",
        "duration": total,
        "source": f"faster-whisper:{model_name}:{device}",
        "segments": out_segments,
    }


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

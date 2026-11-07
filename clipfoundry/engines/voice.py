"""The built-in voice: Supertonic 3 (Supertone Inc.) run inside ClipForge with ONNX Runtime on the processor.

Why this voice: it reads letters directly (no phoneme step, so none of the GPL-3.0 eSpeak NG / phonemizer chain other
small voices need inside the program), it is about 400 MB, it is fast on an ordinary processor, and it speaks 31
languages with 10 voices. Its weights come under BigScience's OpenRAIL-M: free, commercial use allowed, with use rules
that Settings shows before the download (catalog.SUPERTONIC_RULE).

The pipeline follows Supertone's MIT-licensed reference code (github.com/supertone-inc/supertonic-py, Copyright (c)
2025 Supertone Inc.): text -> character ids (unicode_indexer.json) -> duration predictor (seconds for the sentence) and
text encoder -> a few flow steps of the vector estimator from noise -> vocoder -> 44.1 kHz audio. Long text is read
sentence by sentence (at most 300 characters at a time) with a short pause between, and each sentence's real start and
end are known; the times of the words inside a sentence are estimated from their length (marked "estimated").
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
import uuid
import wave
from pathlib import Path

from .. import config
from . import Cancel, EngineError, Progress, catalog, files

log = logging.getLogger(__name__)

LANGS = ("en", "ko", "ja", "ar", "bg", "cs", "da", "de", "el", "es", "et", "fi", "fr", "hi", "hr", "hu", "id", "it",
         "lt", "lv", "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "tr", "uk", "vi")
VOICES = [  # Supertonic 3's ten voices (it names them M1-M5 and F1-F5)
    {"id": f"{g}{n}", "name": f"{'Man' if g == 'M' else 'Woman'} {n}", "gender": "male" if g == "M" else "female",
     "lang": "multilingual", "about": ""}
    for g in ("F", "M") for n in range(1, 6)
]
DEFAULT_VOICE = "F1"
MIN_SPEED, MAX_SPEED = 0.7, 2.0
IDLE_UNLOAD_S = 600.0


# ------------------------------------------------------------------ files
def model() -> catalog.Model:
    return catalog.SUPERTONIC_3


def folder(m: catalog.Model | None = None) -> Path:
    return config.models_dir() / "voice" / (m or model()).id


def _path(m: catalog.Model, f: catalog.ModelFile) -> Path:
    return folder(m) / f.path


def installed(m: catalog.Model | None = None) -> bool:
    m = m or model()
    mark = files.read_marker(folder(m))
    if not mark or mark.get("revision") != m.files[0].revision or mark.get("model") != m.id:
        return False
    return all(_path(m, f).is_file() and _path(m, f).stat().st_size == f.size for f in m.files)


def download_bytes(m: catalog.Model | None = None) -> int:
    m = m or model()
    return 0 if installed(m) else sum(f.size for f in m.files if not (_path(m, f).is_file()
                                                                    and _path(m, f).stat().st_size == f.size))


def install_steps(m: catalog.Model | None = None) -> list:
    from ..cloud import settings as cloud_settings

    m = m or model()
    if cloud_settings.enabled():
        raise EngineError("The online studio's server is set up by its operator; it does not fetch models.")
    if installed(m):
        return []

    def check_space(report, cancelled) -> None:
        files.need_space(folder(m), download_bytes(m), m.name)

    def fetch_all(report, cancelled) -> None:
        total = sum(f.size for f in m.files)
        done_before = 0
        for f in m.files:
            dest = _path(m, f)
            label = f"Downloading the voice ({total / 1e6:.0f} MB)"
            files.fetch(f.pin, dest, lambda d, b=done_before: report(label, b + d, total), cancelled,
                        lambda d, b=done_before: report("Checking the voice", b + d, total))
            done_before += f.size
        files.write_marker(folder(m), {"model": m.id, "revision": m.files[0].revision,
                                      "files": {f.path: f.sha256 for f in m.files}})

    return [check_space, fetch_all]


def remove(m: catalog.Model | None = None) -> None:
    unload()
    files.remove_tree(folder(m or model()))


# ------------------------------------------------------------------ text
_EMOJI = re.compile("[\U0001f600-\U0001f64f\U0001f300-\U0001f5ff\U0001f680-\U0001f6ff\U0001f700-\U0001faff"
                    "☀-➿\U0001f1e6-\U0001f1ff]+")
_SYMBOLS = {"–": "-", "‑": "-", "—": "-", "¯": " ", "_": " ", "“": '"', "”": '"',
            "‘": "'", "’": "'", "´": "'", "`": "'", "[": " ", "]": " ", "|": " ", "/": " ",
            "#": " ", "→": " ", "←": " "}
_SPECIAL = re.compile(r"[♥☆♡©\\]")
_SPACE_BEFORE = [(re.compile(r" ([,.!?;:'])"), r"\1")]
_DUP_QUOTES = re.compile(r"([\"'`])\1+")
_END = re.compile(r"[.!?;:,'\")\]}…。」』】〉》›»]$")
_SENTENCE = re.compile(r"(?<!Mr\.)(?<!Mrs\.)(?<!Ms\.)(?<!Dr\.)(?<!Prof\.)(?<!Sr\.)(?<!Jr\.)(?<!etc\.)(?<!vs\.)"
                       r"(?<!Inc\.)(?<!Ltd\.)(?<!Co\.)(?<!St\.)(?<!\b[A-Z]\.)(?<=[.!?])\s+")


def clean(text: str) -> str:
    """The same clean-up as Supertone's reference: normalised letters, no emoji or decorative symbols, tidy spacing
    and a full stop at the end."""
    text = unicodedata.normalize("NFKD", text)
    text = _EMOJI.sub("", text)
    for old, new in _SYMBOLS.items():
        text = text.replace(old, new)
    text = _SPECIAL.sub("", text)
    for old, new in (("@", " at "), ("e.g.,", "for example, "), ("i.e.,", "that is, ")):
        text = text.replace(old, new)
    for pattern, repl in _SPACE_BEFORE:
        text = pattern.sub(repl, text)
    text = _DUP_QUOTES.sub(r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text and not _END.search(text):
        text += "."
    return text


def chunks(text: str, max_len: int = 300) -> list[str]:
    """Paragraphs, then sentences, joined up to `max_len` characters (a sentence longer than that is cut at commas,
    then at spaces)."""
    out: list[str] = []
    for para in [p.strip() for p in re.split(r"\n\s*\n+", text.strip()) if p.strip()]:
        current = ""
        for sentence in _SENTENCE.split(para):
            sentence = sentence.strip()
            if not sentence:
                continue
            for piece in _split_long(sentence, max_len):
                if current and len(current) + 1 + len(piece) > max_len:
                    out.append(current)
                    current = piece
                else:
                    current = f"{current} {piece}".strip()
        if current:
            out.append(current)
    return out


def _split_long(sentence: str, max_len: int) -> list[str]:
    if len(sentence) <= max_len:
        return [sentence]
    parts, current = [], ""
    for bit in re.split(r"(?<=,)\s+", sentence):
        while len(bit) > max_len:
            cut = bit.rfind(" ", 0, max_len)
            cut = cut if cut > max_len // 3 else max_len
            parts.append(bit[:cut].strip())
            bit = bit[cut:].strip()
        if current and len(current) + 1 + len(bit) > max_len:
            parts.append(current)
            current = bit
        else:
            current = f"{current} {bit}".strip()
    if current:
        parts.append(current)
    return [p for p in parts if p]


def word_times(text: str, start: float, end: float) -> list[dict]:
    """Estimated start and end of each word of one sentence spoken from `start` to `end` (by length; a pause after
    punctuation)."""
    words = text.split()
    if not words:
        return []
    weights = [max(1, sum(c.isalnum() for c in w)) + (2.5 if w[-1] in ".!?;:" else 1.2 if w[-1] == "," else 0.0)
               for w in words]
    span = max(0.05, end - start)
    lead = min(0.08, span * 0.05)
    t, unit = start + lead, (span - lead) / sum(weights)
    out = []
    for w, k in zip(words, weights):
        spoken = unit * (k - (2.5 if w[-1] in ".!?;:" else 1.2 if w[-1] == "," else 0.0))
        out.append({"text": w, "start_s": round(t, 3), "end_s": round(t + max(0.04, spoken), 3)})
        t += unit * k
    return out


# ------------------------------------------------------------------ the model
class Engine:
    def __init__(self, base: Path) -> None:
        import numpy as np
        import onnxruntime as ort

        self.np = np
        cfg = json.loads((base / "onnx" / "tts.json").read_text(encoding="utf-8"))
        self.sample_rate = int(cfg["ae"]["sample_rate"])
        self.base_chunk = int(cfg["ae"]["base_chunk_size"])
        self.compress = int(cfg["ttl"]["chunk_compress_factor"])
        self.ldim = int(cfg["ttl"]["latent_dim"])
        self.indexer = json.loads((base / "onnx" / "unicode_indexer.json").read_text(encoding="utf-8"))
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        import os

        opts.intra_op_num_threads = max(1, min(8, (os.cpu_count() or 4) - 1))
        prov = ["CPUExecutionProvider"]
        load = lambda name: ort.InferenceSession(str(base / "onnx" / name), sess_options=opts, providers=prov)  # noqa: E731
        self.dp = load("duration_predictor.onnx")
        self.enc = load("text_encoder.onnx")
        self.est = load("vector_estimator.onnx")
        self.voc = load("vocoder.onnx")
        self.base = base
        self._styles: dict[str, tuple] = {}

    def style(self, voice: str) -> tuple:
        if voice not in self._styles:
            path = self.base / "voice_styles" / f"{voice}.json"
            if not path.is_file():
                raise EngineError(f"The voice {voice!r} is not there.")
            data = json.loads(path.read_text(encoding="utf-8"))
            arr = lambda d: self.np.array(d["data"], dtype=self.np.float32).reshape(*d["dims"])  # noqa: E731
            self._styles[voice] = (arr(data["style_ttl"]), arr(data["style_dp"]))
        return self._styles[voice]

    def ids(self, text: str, lang: str):
        np = self.np
        wrapped = f"<{lang}>{text}</{lang}>"
        values = []
        for ch in wrapped:
            code = ord(ch)
            idx = self.indexer[code] if code < len(self.indexer) else -1
            if idx == -1:
                idx = self.indexer[ord(" ")]
            values.append(idx)
        ids = np.array([values], dtype=np.int64)
        mask = np.ones((1, 1, len(values)), dtype=np.float32)
        return ids, mask

    def say(self, text: str, voice: str, lang: str, speed: float, steps: int, cancel: Cancel):
        """Audio (float32, mono) and its length in seconds for one sentence or chunk."""
        np = self.np
        ttl, dp = self.style(voice)
        ids, mask = self.ids(text, lang)
        dur, *_ = self.dp.run(None, {"text_ids": ids, "style_dp": dp, "text_mask": mask})
        dur = dur / speed
        emb, *_ = self.enc.run(None, {"text_ids": ids, "style_ttl": ttl, "text_mask": mask})
        seconds = float(dur.reshape(-1)[0])
        samples = int(seconds * self.sample_rate)
        size = self.base_chunk * self.compress
        latent_len = max(1, (samples + size - 1) // size)
        x = np.random.default_rng().standard_normal((1, self.ldim * self.compress, latent_len)).astype(np.float32)
        lmask = np.ones((1, 1, latent_len), dtype=np.float32)
        total = np.array([steps], dtype=np.float32)
        for step in range(steps):
            if cancel():
                raise EngineError("Stopped.")
            x, *_ = self.est.run(None, {"noisy_latent": x, "text_emb": emb, "style_ttl": ttl, "text_mask": mask,
                                        "latent_mask": lmask, "current_step": np.array([step], dtype=np.float32),
                                        "total_step": total})
        wav, *_ = self.voc.run(None, {"latent": x})
        wav = np.asarray(wav, dtype=np.float32).reshape(-1)[:samples]
        return wav, samples / self.sample_rate


_engine: Engine | None = None
_engine_lock = threading.Lock()
_last_used = 0.0
_watch: threading.Thread | None = None


def _get() -> Engine:
    global _engine, _last_used, _watch
    with _engine_lock:
        if _engine is None:
            if not installed():
                raise EngineError("The voice is not downloaded yet. Download it in Settings, Pictures, video, voice.")
            try:
                _engine = Engine(folder())
            except EngineError:
                raise
            except Exception as exc:  # noqa: BLE001 - a damaged download, an old ONNX Runtime
                raise EngineError(f"The voice could not start ({exc.__class__.__name__}: {str(exc)[:160]}). Remove "
                                  "it in Settings and download it again.") from exc
            if _watch is None or not _watch.is_alive():
                _watch = threading.Thread(target=_idle, daemon=True, name="voice-idle")
                _watch.start()
        _last_used = time.time()
        return _engine


def _idle() -> None:
    while True:
        time.sleep(30)
        with _engine_lock:
            if _engine is None:
                return
        if time.time() - _last_used > IDLE_UNLOAD_S:
            unload()
            return


def unload() -> None:
    global _engine
    with _engine_lock:
        _engine = None


def _write_wav(path: Path, wav, rate: int) -> None:
    import numpy as np

    peak = float(np.max(np.abs(wav))) if wav.size else 0.0
    if peak > 0.99:  # never clip
        wav = wav * (0.99 / peak)
    pcm = (np.clip(wav, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def speak(text: str, *, voice: str = "default", speed: float = 1.0, lang: str = "en",
          progress: Progress | None = None, cancel: Cancel | None = None) -> dict:
    import numpy as np

    cancel = cancel or (lambda: False)
    m = model()
    pieces = chunks(clean(str(text or "")), int(m.defaults["chunk_ko" if lang == "ko" else "chunk"]))
    if not pieces:
        raise EngineError("There are no words to say.")
    if sum(len(p) for p in pieces) > 20000:
        raise EngineError("That is too much text for one voice-over (at most about 20,000 letters).")
    voice = voice if voice in {v["id"] for v in VOICES} else DEFAULT_VOICE
    lang = lang if lang in LANGS else "na"
    rate_speed = max(MIN_SPEED, min(MAX_SPEED, float(m.defaults["speed"]) * float(speed or 1.0)))
    steps = int(m.defaults["steps"])
    if progress:
        progress(0.02, "Loading the voice")
    engine = _get()
    pause = np.zeros(int(float(m.defaults["pause_s"]) * engine.sample_rate), dtype=np.float32)
    parts, words, t = [], [], 0.0
    started = time.time()
    for i, piece in enumerate(pieces):
        if cancel():
            raise EngineError("Stopped.")
        if progress:
            progress(0.05 + 0.9 * i / len(pieces), f"Speaking part {i + 1} of {len(pieces)}")
        try:
            wav, seconds = engine.say(piece, voice, lang, rate_speed, steps, cancel)
        except EngineError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise EngineError(f"The voice stopped ({exc.__class__.__name__}: {str(exc)[:160]}).") from exc
        words.extend(word_times(piece, t, t + seconds))
        parts.append(wav)
        t += seconds
        if i < len(pieces) - 1:
            parts.append(pause)
            t += len(pause) / engine.sample_rate
    audio = np.concatenate(parts)
    out_dir = config.data_dir() / "engines" / "made" / "voice" / time.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{uuid.uuid4().hex[:16]}.wav"
    _write_wav(path, audio, engine.sample_rate)
    duration = len(audio) / engine.sample_rate
    note = {"model": m.id, "model_name": m.name, "maker": m.maker, "licence": m.licence, "licence_url": m.licence_url,
            "rule": catalog.SUPERTONIC_RULE, "voice": voice, "lang": lang, "speed": speed, "text": str(text)[:20000],
            "duration_s": round(duration, 3), "word_timing": "estimated", "seconds_taken": round(time.time() - started, 2),
            "made_at": time.time(), "file": path.name}
    path.with_suffix(".json").write_text(json.dumps({**note, "words": words}, indent=1), encoding="utf-8")
    if progress:
        progress(1.0, "Done")
    return {"path": path, "duration_s": round(duration, 3), "words": words, "word_timing": "estimated",
            "sample_rate": engine.sample_rate, "voice": voice, "model": m.id, "licence": m.licence,
            "rule": catalog.SUPERTONIC_RULE}


def voices() -> list[dict]:
    return [dict(v) for v in VOICES] if installed() else []


def status() -> dict:
    from ..cloud import settings as cloud_settings

    if cloud_settings.enabled():
        return {"ready": False, "engine": "", "why": "The voice is made by the desktop app."}
    if not installed():
        return {"ready": False, "engine": "", "why": "The voice is not downloaded yet (Settings, Pictures, video, "
                                                     "voice)."}
    return {"ready": True, "engine": f"{model().name} (on this computer)", "why": "", "model": model().id}

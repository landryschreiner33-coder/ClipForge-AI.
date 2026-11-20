"""The meaning model: a small sentence-embedding network that turns any text into 384 numbers, so two sentences
that say the same thing in different words end up close together (docs/clipforge/SMARTER_AI.md).

The model is all-MiniLM-L6-v2 (sentence-transformers, Apache-2.0), 22 million parameters, run on the CPU through
ONNX Runtime; its 90 MB file and word list are downloaded once from the official repository at a pinned revision and
checked against pinned SHA-256 hashes. The word-piece tokenizer is implemented here (no extra packages). Without the
model (setting off, no ONNX Runtime, download refused, cloud mode) every caller falls back to the word-based vectors
it used before, so nothing stops working; it only sees a little less.

Who uses it: the deep clip analysis (one topic? does the ending tie back? is this clip a repeat?), diversity, Full
stories (a change of subject between two sentences), and the brain's memories (a question finds the memory that
means the same thing).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Callable

import httpx
import numpy as np

from . import config

MODEL = "minilm-l6-v2"          # the embedder id recorded next to every vector that was made with it
DIM = 384
MAX_TOKENS = 256                # all-MiniLM-L6-v2 was trained on 256 word pieces; longer texts are cut
BATCH = 32
RETRY_S = 3600.0                # after a failed download, use the fallback for this long before trying again
CACHE_VECTORS = 40000           # recent results kept in memory (a two-hour video is about 2,500 sentences)

REPO = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
FILES = {  # local name: (path in the repository, bytes, sha256)
    "model.onnx": ("onnx/model.onnx", 90405214, "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452"),
    "vocab.txt": ("vocab.txt", 231508, "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3"),
}
LICENSE = (
    "all-MiniLM-L6-v2, https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 (Nils Reimers and the\n"
    "sentence-transformers authors), Apache License 2.0. Based on MiniLM-L6-H384-uncased (Microsoft, MIT).\n\n"
    "Licensed under the Apache License, Version 2.0 (the \"License\"); you may not use this file except in\n"
    "compliance with the License. You may obtain a copy of the License at\n"
    "http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing,\n"
    "software distributed under the License is distributed on an \"AS IS\" BASIS, WITHOUT WARRANTIES OR\n"
    "CONDITIONS OF ANY KIND, either express or implied.\n")
MARKER = "clipforge-verified.json"
SETTING = "meaning_model"       # the on/off switch in the settings (on by default)


class MeaningError(RuntimeError):
    """The meaning model cannot be used right now; callers fall back to word-based vectors."""


def download_bytes() -> int:
    return sum(size for _path, size, _sha in FILES.values())


def hub_url(name: str) -> str:
    """Where a file is fetched from; HF_ENDPOINT points at a mirror."""
    base = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
    return f"{base}/{REPO}/resolve/{REVISION}/{FILES[name][0]}"


def model_dir() -> Path:
    return config.models_dir() / "meaning" / MODEL


def _expected() -> dict:
    return {name: sha for name, (_path, _size, sha) in FILES.items()}


def model_ready() -> bool:
    folder = model_dir()
    try:
        marker = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if marker.get("files") != _expected():
        return False
    return all((folder / n).is_file() and (folder / n).stat().st_size == size
               for n, (_path, size, _sha) in FILES.items())


def _fetch(name: str, folder: Path, progress: Callable[[int], None] | None = None) -> None:
    _path, size, sha = FILES[name]
    part = folder / f"{name}.{uuid.uuid4().hex[:8]}.part"
    digest, have = hashlib.sha256(), 0
    try:
        with httpx.stream("GET", hub_url(name), follow_redirects=True,
                          timeout=httpx.Timeout(20.0, read=120.0)) as r:
            if r.status_code != 200:
                raise MeaningError(f"The meaning model download answered {r.status_code}.")
            with open(part, "wb") as fh:
                for block in r.iter_bytes(1 << 18):
                    if _cancel.is_set():
                        raise MeaningError("Canceled.")
                    have += len(block)
                    if have > size:
                        raise MeaningError("The meaning model download was larger than expected.")
                    digest.update(block)
                    fh.write(block)
                    if progress:
                        progress(have)
        if have != size or digest.hexdigest() != sha:
            raise MeaningError("The downloaded meaning model did not match its published checksum.")
        part.replace(folder / name)
    finally:
        part.unlink(missing_ok=True)


# ------------------------------------------------------------------ availability
_lock = threading.Lock()
_model = None
_failed_at = 0.0
_last_error = ""
_cancel = threading.Event()
_task: dict = {}
_task_lock = threading.Lock()


def in_cloud() -> bool:
    try:
        from .cloud import settings as cloud_settings
        return bool(cloud_settings.enabled())
    except Exception:  # noqa: BLE001 - the cloud package is optional
        return False


def enabled(settings: dict | None = None) -> bool:
    """The setting (on by default). `settings` may be the merged pipeline options; without it the saved settings
    are read."""
    if settings is None:
        try:
            from . import db
            settings = db.get_settings()
        except Exception:  # noqa: BLE001 - no database yet (tests, first start): the default applies
            settings = {}
    return bool(settings.get(SETTING, config.DEFAULT_SETTINGS.get(SETTING, True)))


def usable(settings: dict | None = None) -> bool:
    """True when a call to embed() would use the model without downloading anything (it is on, present and
    loadable here)."""
    return model_ready() and enabled(settings) and runtime_ok() and not in_cloud()


def runtime_ok() -> bool:
    try:
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_model(progress: Callable[[str, int, int], None] | None = None) -> Path:
    """The verified model folder, downloading it if needed (raises MeaningError when it cannot be had)."""
    global _failed_at, _last_error
    folder = model_dir()
    if model_ready():
        return folder
    if in_cloud():
        raise MeaningError("The meaning model runs in the desktop app.")
    if _failed_at and time.monotonic() - _failed_at < RETRY_S:
        raise MeaningError(_last_error or "The meaning model could not be downloaded a moment ago.")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        done = 0
        total = download_bytes()
        for name in FILES:
            size = FILES[name][1]
            if progress:
                progress(f"Downloading {name}", done, total)

            def tick(have: int, base: int = done, label: str = name) -> None:
                if progress:
                    progress(f"Downloading {label}", base + have, total)
            _fetch(name, folder, tick)
            done += size
        (folder / "LICENSE.txt").write_text(LICENSE, encoding="utf-8")
        (folder / MARKER).write_text(json.dumps({"files": _expected(), "repo": REPO, "revision": REVISION}),
                                     encoding="utf-8")
        _failed_at, _last_error = 0.0, ""
    except (httpx.HTTPError, OSError, MeaningError) as exc:
        _failed_at = time.monotonic()
        if isinstance(exc, MeaningError):
            _last_error = str(exc)
            raise
        _last_error = "The meaning model could not be downloaded (is the computer online?)."
        raise MeaningError(_last_error) from exc
    return folder


# ------------------------------------------------------------------ the tokenizer (BERT uncased word pieces)
_PUNCT_CATEGORIES = ("P", "S")


def _is_punct(ch: str) -> bool:
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith(_PUNCT_CATEGORIES)


def _is_cjk(cp: int) -> bool:
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF or 0x2A700 <= cp <= 0x2B73F
            or 0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF or 0xF900 <= cp <= 0xFAFF
            or 0x2F800 <= cp <= 0x2FA1F)


class WordPiece:
    """The tokenizer of BERT-uncased models: lower-case, strip accents, split punctuation and CJK characters, then
    greedy longest-match word pieces ("##" continues a word)."""

    def __init__(self, vocab_path: Path, max_tokens: int = MAX_TOKENS):
        words = vocab_path.read_text(encoding="utf-8").splitlines()
        self.ids = {w: i for i, w in enumerate(words)}
        self.cls = self.ids["[CLS]"]
        self.sep = self.ids["[SEP]"]
        self.pad = self.ids["[PAD]"]
        self.unk = self.ids["[UNK]"]
        self.max_tokens = max_tokens

    @staticmethod
    def words(text: str) -> list[str]:
        out: list[str] = []
        cleaned = []
        for ch in text:
            cp = ord(ch)
            if cp == 0 or cp == 0xFFFD or (unicodedata.category(ch) == "Cc" and ch not in "\t\n\r"):
                continue
            cleaned.append(" " if ch in "\t\n\r" else ch)
        text = unicodedata.normalize("NFD", "".join(cleaned).lower())
        word: list[str] = []
        for ch in text:
            if unicodedata.category(ch) == "Mn":
                continue  # accents
            if ch.isspace():
                if word:
                    out.append("".join(word))
                    word = []
            elif _is_punct(ch) or _is_cjk(ord(ch)):
                if word:
                    out.append("".join(word))
                    word = []
                out.append(ch)
            else:
                word.append(ch)
        if word:
            out.append("".join(word))
        return out

    def pieces(self, word: str) -> list[int]:
        if len(word) > 100:
            return [self.unk]
        out: list[int] = []
        start = 0
        while start < len(word):
            end = len(word)
            found = None
            while start < end:
                sub = word[start:end]
                if start:
                    sub = "##" + sub
                k = self.ids.get(sub)
                if k is not None:
                    found = k
                    break
                end -= 1
            if found is None:
                return [self.unk]
            out.append(found)
            start = end
        return out

    def encode(self, text: str) -> list[int]:
        ids: list[int] = []
        for w in self.words(text):
            ids.extend(self.pieces(w))
            if len(ids) >= self.max_tokens - 2:
                break
        return [self.cls, *ids[:self.max_tokens - 2], self.sep]


# ------------------------------------------------------------------ the model
class _Loaded:
    def __init__(self, session, tokenizer: WordPiece):
        self.session = session
        self.tokenizer = tokenizer
        self.inputs = [i.name for i in session.get_inputs()]
        outputs = [o.name for o in session.get_outputs()]
        self.pooled = "sentence_embedding" if "sentence_embedding" in outputs else None
        self.hidden = "last_hidden_state" if "last_hidden_state" in outputs else outputs[0]


def _loaded() -> _Loaded:
    global _model, _failed_at, _last_error
    with _lock:
        if _model is not None:
            return _model
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise MeaningError("ONNX Runtime is not installed.") from exc
        folder = ensure_model()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) // 2))
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3
        try:
            session = ort.InferenceSession(str(folder / "model.onnx"), sess_options=opts,
                                           providers=["CPUExecutionProvider"])
            tok = WordPiece(folder / "vocab.txt")
            model = _Loaded(session, tok)
            if "input_ids" not in model.inputs:
                raise ValueError("unexpected inputs")
        except Exception as exc:  # noqa: BLE001 - any loading problem means "use the fallback"
            _failed_at, _last_error = time.monotonic(), "The meaning model could not be loaded."
            raise MeaningError(_last_error) from exc
        _model = model
        return model


def _run(model: _Loaded, texts: list[str]) -> np.ndarray:
    encoded = [model.tokenizer.encode(t) for t in texts]
    order = sorted(range(len(texts)), key=lambda k: len(encoded[k]))  # similar lengths together: less padding
    out = np.zeros((len(texts), DIM), dtype=np.float32)
    for b in range(0, len(order), BATCH):
        idx = order[b:b + BATCH]
        width = max(len(encoded[k]) for k in idx)
        ids = np.full((len(idx), width), model.tokenizer.pad, dtype=np.int64)
        mask = np.zeros((len(idx), width), dtype=np.int64)
        for row, k in enumerate(idx):
            ids[row, :len(encoded[k])] = encoded[k]
            mask[row, :len(encoded[k])] = 1
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in model.inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        feed = {k: v for k, v in feed.items() if k in model.inputs}
        if model.pooled:
            vecs = np.asarray(model.session.run([model.pooled], feed)[0], dtype=np.float32)
        else:
            hidden = np.asarray(model.session.run([model.hidden], feed)[0], dtype=np.float32)
            m = mask[:, :, None].astype(np.float32)
            vecs = (hidden * m).sum(axis=1) / np.maximum(m.sum(axis=1), 1.0)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        vecs = np.divide(vecs, norms, out=np.zeros_like(vecs), where=norms > 1e-9)
        for row, k in enumerate(idx):
            out[k] = vecs[row]
    return out


_cache: dict[str, np.ndarray] = {}
_cache_order: list[str] = []
_cache_vectors = 0


def _key(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8", "replace"), digest_size=12).hexdigest()


def embed(texts: list[str], settings: dict | None = None) -> np.ndarray:
    """Unit vectors (len(texts) x 384) for the texts. Raises MeaningError when the model cannot be used."""
    global _cache_vectors
    if not enabled(settings):
        raise MeaningError("The meaning model is switched off in the settings.")
    model = _loaded()
    out = np.zeros((len(texts), DIM), dtype=np.float32)
    todo: dict[str, list[int]] = {}
    with _lock:
        for k, t in enumerate(texts):
            key = _key(t)
            hit = _cache.get(key)
            if hit is not None:
                out[k] = hit
            else:
                todo.setdefault(key, []).append(k)
    if todo:
        keys = list(todo)
        vecs = _run(model, [texts[todo[key][0]] for key in keys])
        with _lock:
            for key, v in zip(keys, vecs):
                for k in todo[key]:
                    out[k] = v
                if key not in _cache:
                    _cache[key] = v
                    _cache_order.append(key)
                    _cache_vectors += 1
            while _cache_vectors > CACHE_VECTORS and _cache_order:
                _cache.pop(_cache_order.pop(0), None)
                _cache_vectors -= 1
    return out


def embed_or_none(texts: list[str], settings: dict | None = None) -> np.ndarray | None:
    """The vectors, or None when the model is off or unavailable (the caller uses its word-based fallback)."""
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    try:
        return embed(texts, settings)
    except MeaningError:
        return None


def embed_one(text: str, settings: dict | None = None) -> np.ndarray | None:
    v = embed_or_none([text], settings)
    return None if v is None else v[0]


# ------------------------------------------------------------------ the settings page
def status(settings: dict | None = None) -> dict:
    ready = model_ready()
    with _task_lock:
        task = dict(_task)
    on = enabled(settings)
    why = ""
    if in_cloud():
        why = "The meaning model runs in the desktop app."
    elif not runtime_ok():
        why = "ONNX Runtime is not installed, so the meaning model cannot run."
    elif not on:
        why = "Switched off: clips and memories are compared by their words only."
    elif not ready and _failed_at and time.monotonic() - _failed_at < RETRY_S:
        why = _last_error
    return {"model": MODEL, "name": "all-MiniLM-L6-v2", "license": "Apache-2.0", "download_bytes": download_bytes(),
            "ready": ready, "enabled": on, "usable": ready and on and runtime_ok() and not in_cloud(),
            "problem": why, "task": task, "folder": str(model_dir())}


def install(on_done: Callable[[dict], None] | None = None) -> dict:
    """Download the model in the background (progress in status()["task"])."""
    if in_cloud():
        raise MeaningError("The meaning model runs in the desktop app.")
    with _task_lock:
        if _task.get("state") == "running":
            return dict(_task)
        _cancel.clear()
        _task.clear()
        _task.update(state="running", status="Starting", completed=0, total=download_bytes(), error="",
                     started_at=time.time(), updated_at=time.time())

    def report(status_text: str, completed: int, total: int) -> None:
        with _task_lock:
            _task.update(status=status_text, completed=completed, total=total, updated_at=time.time())

    def work() -> None:
        global _failed_at
        try:
            _failed_at = 0.0  # a person asked: try now even after a recent failure
            ensure_model(report)
            _loaded()
            with _task_lock:
                _task.update(state="done", status="Ready", completed=download_bytes(), updated_at=time.time())
        except MeaningError as exc:
            with _task_lock:
                _task.update(state="error", status="Failed", error=str(exc), updated_at=time.time())
        if on_done:
            with _task_lock:
                snapshot = dict(_task)
            on_done(snapshot)

    threading.Thread(target=work, name="meaning-model-install", daemon=True).start()
    with _task_lock:
        return dict(_task)


def cancel() -> None:
    _cancel.set()


def remove() -> None:
    """Delete the downloaded model (it is downloaded again on the next use when the setting is on)."""
    global _model
    import shutil
    with _lock:
        _model = None
        _cache.clear()
        _cache_order.clear()
    shutil.rmtree(model_dir(), ignore_errors=True)


def reset_for_tests() -> None:
    global _model, _failed_at, _last_error, _cache_vectors
    with _lock:
        _model = None
        _failed_at, _last_error = 0.0, ""
        _cache.clear()
        _cache_order.clear()
        _cache_vectors = 0
    with _task_lock:
        _task.clear()
    _cancel.clear()

"""Setting up the optional AI helper: ready-made choices, and Ollama on this computer (check, download a model,
or import a model file you already have).

Every choice here is free to use: a model running on this computer through Ollama or LM Studio (private, works
offline, uses the GPU), or an online service's free tier with your own key (Google Gemini, Groq, OpenRouter's free
models). Free tiers have daily limits that the services set and change; when one is used up, ClipForge's built-in
editor carries on alone. The Claude API is listed as the paid option it is. A key is stored like every other secret
(sealed on this computer) and only sent to the service it belongs to.

Model names of online services change over time; each preset suggests one, and "Load models" lists what the
service offers with your key, so a retired name is easy to replace.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from pathlib import Path

import httpx

OLLAMA_DOWNLOAD = "https://ollama.com/download"
PRESETS = [
    {"id": "builtin", "name": "Built-in AI", "provider": "builtin", "url": "", "model": "", "needs_key": False,
     "local": True, "cost": "Free",
     "about": "Comes with ClipForge: a free model (Gemma 4 or Qwen3-VL) that runs on this computer. Private, works "
              "without internet once downloaded, no limits. Download it once below.", "key_url": ""},
    {"id": "ollama", "name": "Ollama on this computer", "provider": "ollama", "url": "http://localhost:11434",
     "model": "qwen2.5:3b", "needs_key": False, "local": True, "cost": "Free",
     "about": "Runs on your own computer: private, works without internet, no limits. Install the free Ollama app, "
              "then download a model here.", "key_url": OLLAMA_DOWNLOAD},
    {"id": "lmstudio", "name": "LM Studio on this computer", "provider": "openai_compatible",
     "url": "http://localhost:1234/v1", "model": "", "needs_key": False, "local": True, "cost": "Free",
     "about": "Runs on your own computer. Load any model file (.gguf) in LM Studio and start its local server.",
     "key_url": "https://lmstudio.ai"},
    {"id": "gemini", "name": "Google Gemini", "provider": "openai_compatible",
     "url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.5-flash",
     "needs_key": True, "local": False, "cost": "Free tier with daily limits",
     "about": "Free key from Google AI Studio. On the free tier Google may use what is sent to improve its "
              "products, and people may review it, so do not use it for private videos.",
     "key_url": "https://aistudio.google.com/apikey"},
    {"id": "groq", "name": "Groq", "provider": "openai_compatible", "url": "https://api.groq.com/openai/v1",
     "model": "openai/gpt-oss-20b", "needs_key": True, "local": False, "cost": "Free tier with daily limits",
     "about": "Free key, no card needed. Very fast answers.", "key_url": "https://console.groq.com/keys"},
    {"id": "openrouter", "name": "OpenRouter", "provider": "openai_compatible", "url": "https://openrouter.ai/api/v1",
     "model": "", "needs_key": True, "local": False, "cost": "Free models (names end in :free), small daily limit",
     "about": "One key for many models. Only models whose name ends in :free cost nothing; ClipForge picks one when "
              "you load the list.", "key_url": "https://openrouter.ai/keys"},
    {"id": "anthropic", "name": "Claude API", "provider": "anthropic", "url": "", "model": "claude-haiku-5-5",
     "needs_key": True, "local": False, "cost": "Paid per use",
     "about": "Anthropic's Claude. Not free: every request is billed to your Anthropic account.",
     "key_url": "https://console.anthropic.com/settings/keys"},
]
# Small models that edit well and fit an ordinary graphics card; sizes are the download, roughly.
OLLAMA_MODELS = [
    {"name": "qwen2.5:3b", "size_gb": 1.9, "about": "Fast. Good for 4 to 6 GB graphics cards and laptops."},
    {"name": "llama3.2:3b", "size_gb": 2.0, "about": "Fast. A good second choice for smaller graphics cards."},
    {"name": "gemma3:4b", "size_gb": 3.3, "about": "Balanced speed and quality."},
    {"name": "qwen2.5:7b", "size_gb": 4.7, "about": "Better choices; for 8 GB graphics cards or Apple silicon Macs."},
    {"name": "llama3.1:8b", "size_gb": 4.9, "about": "Better choices; for 8 GB graphics cards or Apple silicon Macs."},
]
MODEL_NAME = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,80}(:[a-z0-9._-]{1,40})?$")
_task: dict = {}
_task_lock = threading.Lock()


class SetupError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def preset_for_url(url: str) -> dict | None:
    base = (url or "").rstrip("/").lower()
    for p in PRESETS:
        if p["url"] and p["provider"] == "openai_compatible" and not p["local"] and base == p["url"].lower():
            return p
    return None


def presets() -> dict:
    return {"presets": PRESETS, "ollama_models": OLLAMA_MODELS, "ollama_download": OLLAMA_DOWNLOAD}


def recommended_model(vram_mb: int | None, mac: bool = False) -> str:
    if mac or (vram_mb or 0) >= 7500:
        return "qwen2.5:7b"
    return "qwen2.5:3b"


def _base(url: str) -> str:
    return (url or "http://localhost:11434").rstrip("/")


def ollama_status(url: str) -> dict:
    """Is Ollama running, and which models does it have? (Never raises: the page shows what is wrong.)"""
    base = _base(url)
    try:
        version = httpx.get(f"{base}/api/version", timeout=3).json().get("version", "")
        tags = httpx.get(f"{base}/api/tags", timeout=5).json().get("models") or []
    except (httpx.HTTPError, ValueError) as exc:
        return {"running": False, "version": "", "models": [], "problem": (
            f"Ollama is not running at {base}. Install it from {OLLAMA_DOWNLOAD} and start it, then check again."
            if isinstance(exc, httpx.ConnectError) else f"Ollama did not answer ({exc.__class__.__name__}).")}
    models = [{"name": m.get("name") or m.get("model") or "", "size_gb": round((m.get("size") or 0) / 1e9, 1)}
              for m in tags if isinstance(m, dict)]
    return {"running": True, "version": version, "models": [m for m in models if m["name"]], "problem": ""}


def task() -> dict:
    with _task_lock:
        return dict(_task)


def _set(**fields) -> None:
    with _task_lock:
        _task.update(fields, updated_at=time.time())


def _start(kind: str, name: str, target) -> dict:
    with _task_lock:
        if _task.get("state") == "running":
            raise SetupError(f"Already {_task.get('kind')}ing {_task.get('model')}; wait for it to finish.", 409)
        _task.clear()
        _task.update(kind=kind, model=name, state="running", status="Starting", completed=0, total=0, error="",
                     started_at=time.time(), updated_at=time.time())
    threading.Thread(target=target, daemon=True, name=f"ollama-{kind}").start()
    return task()


def pull(url: str, model: str) -> dict:
    """Download a model into Ollama in the background (progress in task())."""
    model = (model or "").strip().lower()
    if not MODEL_NAME.match(model):
        raise SetupError("Type a model name like qwen2.5:3b.")
    base = _base(url)

    def run() -> None:
        try:
            with httpx.stream("POST", f"{base}/api/pull", json={"model": model, "name": model, "stream": True},
                              timeout=httpx.Timeout(30.0, read=600.0)) as r:
                if r.status_code != 200:
                    raise SetupError(f"Ollama answered {r.status_code}: {r.read().decode('utf-8', 'replace')[:200]}")
                for line in r.iter_lines():
                    _progress_line(line)
            if task().get("state") == "running":
                _set(state="done", status="Downloaded")
        except (httpx.HTTPError, SetupError, ValueError) as exc:
            _set(state="failed", error=_why(exc, base))

    return _start("download", model, run)


def _progress_line(line: str) -> None:
    import json

    if not line.strip():
        return
    data = json.loads(line)
    if data.get("error"):
        raise SetupError(str(data["error"])[:300])
    fields = {"status": str(data.get("status") or "")[:120]}
    if data.get("total"):
        fields.update(total=int(data["total"]), completed=int(data.get("completed") or 0))
    if data.get("status") == "success":
        fields["state"] = "done"
    _set(**fields)


def _why(exc: Exception, base: str) -> str:
    if isinstance(exc, httpx.ConnectError):
        return f"Ollama is not running at {base}. Start it, then try again."
    return str(exc)[:300] or exc.__class__.__name__


def import_gguf(url: str, path: str, name: str) -> dict:
    """Add a model file (.gguf) you already have to Ollama under `name`, in the background. Only on this computer:
    a server in cloud mode never reads a path someone typed."""
    from .cloud import settings as cloud_settings

    if cloud_settings.enabled():
        raise SetupError("Importing a model file works only in the desktop app.", 403)
    name = (name or "").strip().lower()
    if not MODEL_NAME.match(name):
        raise SetupError("Give the model a short name of lowercase letters, numbers, dots or dashes, like my-model.")
    file = Path(os.path.expanduser((path or "").strip().strip('"')))
    if file.suffix.lower() != ".gguf":
        raise SetupError("Choose a model file that ends in .gguf.")
    if not file.is_file():
        raise SetupError("That file was not found on this computer.")
    size = file.stat().st_size
    if size < 1 << 20:
        raise SetupError("That file is too small to be a model.")
    base = _base(url)

    def run() -> None:
        try:
            _set(status="Reading the file", total=size, completed=0)
            h = hashlib.sha256()
            done = 0
            with open(file, "rb") as fh:
                for block in iter(lambda: fh.read(8 << 20), b""):
                    h.update(block)
                    done += len(block)
                    _set(completed=done)
            digest = "sha256:" + h.hexdigest()
            if httpx.head(f"{base}/api/blobs/{digest}", timeout=10).status_code != 200:
                _set(status="Copying the file into Ollama", completed=0)

                def body():
                    sent = 0
                    with open(file, "rb") as fh:
                        for block in iter(lambda: fh.read(8 << 20), b""):
                            sent += len(block)
                            _set(completed=sent)
                            yield block

                r = httpx.post(f"{base}/api/blobs/{digest}", content=body(),
                               timeout=httpx.Timeout(30.0, read=1800.0, write=1800.0))
                if r.status_code not in (200, 201):
                    raise SetupError(f"Ollama did not accept the file ({r.status_code}: {r.text[:200]}).")
            _set(status="Creating the model", completed=0, total=0)
            r = httpx.post(f"{base}/api/create", json={"model": name, "files": {file.name: digest}, "stream": False},
                           timeout=httpx.Timeout(30.0, read=1800.0))
            if r.status_code != 200:  # an older Ollama: a Modelfile that points at the uploaded blob
                r = httpx.post(f"{base}/api/create", json={"name": name, "modelfile": f"FROM @{digest}",
                                                            "stream": False}, timeout=httpx.Timeout(30.0, read=1800.0))
            if r.status_code != 200:
                raise SetupError(f"Ollama could not create the model ({r.status_code}: {r.text[:200]}).")
            _set(state="done", status="Imported")
        except (httpx.HTTPError, SetupError, OSError, ValueError) as exc:
            _set(state="failed", error=_why(exc, base))

    return _start("import", name, run)

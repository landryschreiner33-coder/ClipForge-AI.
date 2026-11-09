"""Pictures and short video clips from words, made on this computer by ComfyUI with a model from catalog.py.

Which ComfyUI (Settings, "engines_comfyui"): ClipForge's own (comfy_server.py: set up from Settings, started when
needed, stopped when idle), or one already on this computer (the ComfyUI desktop app on port 8000, a manual install on
8188, or the address in Settings), or none. Only the words of the request (and a picture to animate) go to it.

Each job holds the graphics card the way transcription does (gpu.py), so the two never compete for its memory, and
everything it makes is copied to <data>/engines/made/<kind>/<day>/ with a note next to it (model, licence, words,
seed), which is how a made picture can be traced back.
"""
from __future__ import annotations

import json
import logging
import secrets
import struct
import threading
import time
import uuid
from pathlib import Path

from .. import config
from . import Cancel, EngineError, Progress, catalog, graphs, models
from .comfy import Comfy

log = logging.getLogger(__name__)

APP_PORTS = (8000, 8188)  # the ComfyUI desktop app, then a manual install (python main.py)
_found: dict = {"at": 0.0, "key": "", "base": None}
_found_lock = threading.Lock()


# ------------------------------------------------------------------ which ComfyUI
def mode(settings: dict) -> str:
    m = str(settings.get("engines_comfyui") or "clipforge")
    return m if m in config.ENGINES_COMFYUI else "clipforge"


def find_app(settings: dict, max_age: float = 15.0) -> str | None:
    """The address of a running ComfyUI that is not ClipForge's own (the one in Settings, else the usual ports)."""
    typed = str(settings.get("engines_comfyui_url") or "").rstrip("/")
    key = typed or "auto"
    with _found_lock:
        if _found["key"] == key and time.monotonic() - _found["at"] < max_age:
            return _found["base"]
    candidates = [typed] if typed else [f"http://127.0.0.1:{p}" for p in APP_PORTS]
    base = next((c for c in candidates if Comfy(c, timeout=2).alive()), None)
    with _found_lock:
        _found.update(at=time.monotonic(), key=key, base=base)
    return base


def forget_found() -> None:
    with _found_lock:
        _found.update(at=0.0, key="", base=None)


def base_url(settings: dict, progress: Progress | None = None) -> str:
    """The ComfyUI to send work to; starts ClipForge's own when that is the one chosen."""
    from . import comfy_server

    m = mode(settings)
    if m == "off":
        raise EngineError("Pictures and video are turned off. Turn them on in Settings, Pictures, video, voice.")
    if m == "app":
        base = find_app(settings, max_age=0)
        if not base:
            where = settings.get("engines_comfyui_url") or "this computer (ports 8000 and 8188)"
            raise EngineError(f"ComfyUI is not running on {where}. Open the ComfyUI app, or choose ClipForge's own "
                              "ComfyUI in Settings, Pictures, video, voice.")
        return base
    return comfy_server.server.ensure(settings, progress)


# ------------------------------------------------------------------ which model
_machine: dict = {"at": 0.0, "view": None}


def machine() -> dict:
    """This computer, for choosing models: {"flavor": "mps"|"cuda"|"cpu"|"", "memory_mb", "vram_mb", "gpu"}
    (asked at most once a minute: reading the graphics card starts a program)."""
    from ..builtin_ai import memory_mb
    from . import comfy_server

    now = time.monotonic()
    if _machine["view"] is not None and now - _machine["at"] < 60:
        return _machine["view"]
    gpu = comfy_server.nvidia()
    view = {"flavor": comfy_server.torch_flavor() if comfy_server.platform_key() else "",
            "memory_mb": memory_mb(), "vram_mb": int(gpu.get("vram_mb") or 0), "gpu": gpu}
    _machine.update(at=now, view=view)
    return view


def fit(model: catalog.Model, computer: dict) -> str:
    """How `model` suits this computer: "good", "slow" (it runs, slowly: less memory than it likes), "cpu" (no
    graphics to use: very slow) or "" (not known)."""
    if model.role == "voice":
        return "good"
    flavor = computer.get("flavor") or ""
    if flavor == "mps":
        have = int(computer.get("memory_mb") or 0)
        return "" if not have else "good" if have >= model.memory_gb * 1024 * 0.95 else "slow"
    if flavor == "cuda":
        return "good" if int(computer.get("vram_mb") or 0) >= model.vram_gb * 1024 * 0.95 else "slow"
    return "cpu" if flavor == "cpu" else ""


def ranked(role: str, computer: dict) -> list[catalog.Model]:
    """The models for `role`, the best one for this computer first: the first in the catalog's order (best result
    first) that suits it, else the one that needs the least memory."""
    options = catalog.for_role(role)
    good = [m for m in options if fit(m, computer) == "good"]
    rest = sorted((m for m in options if m not in good), key=lambda m: (m.memory_gb, m.vram_gb))
    return good + rest


def _visible(model: catalog.Model, settings: dict, base: str | None) -> bool:
    return not models.missing(model, mode(settings), base)


def chosen(role: str, settings: dict, base: str | None = None) -> catalog.Model | None:
    """The model for `role`: the one in Settings when ComfyUI has it, else the best one for this computer that it
    has."""
    key = {"image": "engines_picture", "video": "engines_video"}[role]
    wanted = catalog.by_id(str(settings.get(key) or ""))
    options = ([wanted] if wanted and wanted.role == role else []) + [m for m in ranked(role, machine())
                                                                       if m is not wanted]
    m = mode(settings)
    if m == "app":
        base = base or find_app(settings)
        if not base:
            return None
    return next((x for x in options if _visible(x, settings, base)), None)


def status(role: str, settings: dict) -> dict:
    from ..cloud import settings as cloud_settings
    from . import comfy_server

    what = "pictures" if role == "image" else "video clips"
    if cloud_settings.enabled():
        return {"ready": False, "engine": "", "why": "Pictures and video are made by the desktop app."}
    m = mode(settings)
    if m == "off":
        return {"ready": False, "engine": "", "why": "Pictures and video are turned off in Settings."}
    if not catalog.for_role(role):
        return {"ready": False, "engine": "", "why": f"ClipForge has no model for {what} yet."}
    if m == "clipforge":
        if not comfy_server.installed():
            return {"ready": False, "engine": "", "why": "ComfyUI is not set up yet (Settings, Pictures, video, "
                                                          "voice)."}
        model = chosen(role, settings)
        if not model:
            return {"ready": False, "engine": "ClipForge's ComfyUI",
                    "why": f"Download a model for {what} in Settings, Pictures, video, voice."}
        return {"ready": True, "engine": f"ClipForge's ComfyUI · {model.name}", "why": "", "model": model.id}
    base = find_app(settings)
    if not base:
        return {"ready": False, "engine": "", "why": "ComfyUI is not running. Open the ComfyUI app, or choose "
                                                      "ClipForge's own ComfyUI in Settings."}
    model = chosen(role, settings, base)
    if not model:
        return {"ready": False, "engine": f"ComfyUI at {base}",
                "why": f"That ComfyUI has none of the models ClipForge uses for {what}. Download one in Settings, "
                       "Pictures, video, voice."}
    return {"ready": True, "engine": f"ComfyUI at {base} · {model.name}", "why": "", "model": model.id}


# ------------------------------------------------------------------ making things
def made_dir(kind: str) -> Path:
    d = config.data_dir() / "engines" / "made" / kind / time.strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _seed(seed: int | None) -> int:
    return int(seed) % (1 << 31) if seed is not None else secrets.randbelow(1 << 31)


def _gpu(kind: str, label: str, cancel: Cancel, progress: Progress | None):
    from ..gpu import manager

    settings = _settings()
    return manager.heavy(kind, label=label[:120], cancelled=cancel,
                         max_wait_s=float(settings.get("gpu_wait_minutes") or 20) * 60,
                         on_wait=(lambda text: progress(0.0, text)) if progress else None)


def _settings() -> dict:
    from .. import db

    return db.get_settings()


def _run(kind: str, role: str, graph_for, note: dict, progress: Progress | None, cancel: Cancel | None,
         timeout_s: float) -> tuple[Path, dict]:
    from ..pipeline.common import Cancelled
    from . import comfy_server

    cancel = cancel or (lambda: False)
    settings = _settings()
    started = time.time()
    try:
        with _gpu("picture maker" if role == "image" else "video maker", note.get("prompt", ""), cancel, progress), \
                comfy_server.job():
            base = base_url(settings, progress)
            model = chosen(role, settings, base)
            if model is None:
                raise EngineError(status(role, settings).get("why") or "No model is set up for this.")
            client = Comfy(base, timeout=60)
            # the names that ComfyUI takes the files by, and a new place to save to (an identical graph would be
            # answered from ComfyUI's cache, with a file ClipForge's own ComfyUI no longer has)
            names = models.names(model, mode(settings), base)
            prefix = f"{graphs.PREFIX}/{kind}-{uuid.uuid4().hex[:8]}"
            graph, steps_node, extra = graph_for(model, client, names, prefix)
            lacking = client.missing_nodes(graphs.class_types(graph))
            if lacking:
                raise EngineError(f"This ComfyUI lacks {', '.join(lacking)}; it may be too old for {model.name}. "
                                  "Update it, or use ClipForge's own ComfyUI.")
            outputs = client.run(graph, progress=progress, cancel=cancel, timeout_s=timeout_s,
                                 steps_node=steps_node, labels=graphs.labels(graph))
            wanted = [o for o in outputs if o["key"] in (("images",) if role == "image" else ("images", "videos",
                                                                                                "gifs", "video"))]
            out = (wanted or outputs)[-1]
            suffix = Path(out["filename"]).suffix.lower() or (".png" if role == "image" else ".mp4")
            dest = made_dir(kind) / f"{uuid.uuid4().hex[:16]}{suffix}"
            if progress:
                progress(0.95, "Saving")
            client.download(out, dest)
            if mode(settings) == "clipforge":  # ClipForge's own ComfyUI keeps no second copy
                _drop_comfy_copy(out)
    except Cancelled as exc:
        raise EngineError("Stopped.") from exc
    except EngineError:
        raise
    except Exception as exc:  # noqa: BLE001 - every failure reaches the person in plain words
        from ..gpu import GpuBusy

        if isinstance(exc, GpuBusy):
            raise EngineError(str(exc)) from exc
        log.exception("making %s failed", kind)
        raise EngineError(f"Making the {kind} failed ({exc.__class__.__name__}: {str(exc)[:200]}).") from exc
    info = {**note, **extra, "model": model.id, "model_name": model.name, "maker": model.maker,
            "licence": model.licence, "licence_url": model.licence_url, "rule": model.rule,
            "engine": status(role, settings).get("engine"), "seconds_taken": round(time.time() - started, 1),
            "made_at": time.time(), "file": dest.name}
    dest.with_suffix(".json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return dest, info


def _drop_comfy_copy(out: dict) -> None:
    from . import comfy_server

    base = (comfy_server.work_dir() / "output").resolve()
    target = (base / out.get("subfolder", "") / out["filename"]).resolve()
    if base in target.parents and target.is_file():
        try:
            target.unlink()
        except OSError:
            pass


def png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise EngineError("ComfyUI handed back something that is not a picture.")
    return struct.unpack(">II", head[16:24])


def make_image(prompt: str, *, negative: str = "", style: str = "", width: int = 1080, height: int = 1920,
               seed: int | None = None, progress: Progress | None = None, cancel: Cancel | None = None) -> Path:
    prompt = " ".join(str(prompt or "").split())
    if not prompt:
        raise EngineError("Say what the picture should show.")
    words = f"{prompt}. {style.strip()}" if style and style.strip() else prompt
    s = _seed(seed)

    def graph_for(model: catalog.Model, client: Comfy, names: dict[str, str], prefix: str):
        w, h = graphs.picture_size(model, width, height)
        g, node = graphs.picture(model, words[:4000], negative[:2000], w, h, s, names=names, prefix=prefix)
        return g, node, {"width": w, "height": h}

    path, info = _run("picture", "image", graph_for, {"prompt": words[:4000], "negative": negative[:2000], "seed": s,
                                                     "asked_width": width, "asked_height": height},
                      progress, cancel, timeout_s=1800)
    w, h = png_size(path)
    if (w, h) != (info["width"], info["height"]):
        log.info("picture came back %sx%s (asked %sx%s)", w, h, info["width"], info["height"])
    return path


def make_video(prompt: str, *, image: Path | str | None = None, seconds: float = 4.0, width: int = 720,
               height: int = 1280, seed: int | None = None, progress: Progress | None = None,
               cancel: Cancel | None = None) -> Path:
    prompt = " ".join(str(prompt or "").split())
    if not prompt:
        raise EngineError("Say what the clip should show.")
    start = Path(image) if image else None
    if start is not None and not start.is_file():
        raise EngineError("The picture to animate is missing.")
    s = _seed(seed)

    def graph_for(model: catalog.Model, client: Comfy, names: dict[str, str], prefix: str):
        w, h, frames, fps = graphs.video_shape(model, width, height, seconds)
        uploaded = client.upload_image(start) if start is not None else ""
        g, node = graphs.video(model, prompt[:4000], "", w, h, frames, fps, s, uploaded, names=names, prefix=prefix)
        return g, node, {"width": w, "height": h, "frames": frames, "fps": fps, "seconds": round(frames / fps, 2),
                         "from_picture": bool(start)}

    path, _info = _run("video", "video", graph_for, {"prompt": prompt[:4000], "seed": s, "asked_seconds": seconds,
                                                    "asked_width": width, "asked_height": height},
                       progress, cancel, timeout_s=3 * 3600)
    if path.stat().st_size < 1000:
        raise EngineError("ComfyUI handed back an empty video.")
    return path


def make_room(kind: str) -> None:
    """Heavy work that is not ours is about to use the graphics card: ClipForge's own ComfyUI unloads its models."""
    from . import comfy_server

    if kind in ("picture maker", "video maker") or not comfy_server.server.running():
        return
    try:
        Comfy(f"http://127.0.0.1:{comfy_server.server.port}", timeout=10).free()
    except Exception:  # noqa: BLE001 - a courtesy
        pass

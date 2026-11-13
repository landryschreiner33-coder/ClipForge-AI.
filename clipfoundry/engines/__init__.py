"""Local engines: the programs on this computer that make pictures, video and speech for ClipForge
(docs/clipforge/LOCAL_ENGINES.md).

This is the one door other parts of ClipForge use (the animated-shorts maker, the media finders, the AI). Every call
is blocking and meant for a job thread; every call takes the same two callbacks: `progress(fraction, message)` and
`cancel() -> bool`. Everything that goes wrong is one error class, `EngineError`, whose message is written for the
person. `status(role)` never raises.

Roles: "image" (a still picture from words), "video" (a few seconds of motion from words or a picture) and "voice"
(speech from words). Pictures and video are made by ComfyUI (ClipForge's own copy, the ComfyUI app already on this
computer, or a ComfyUI on the person's rented cloud computer: remote.py) with a model from catalog.py; the voice runs
inside ClipForge (voice.py). Settings → Pictures, video, voice sets them up (overview(), setup(), remove(),
connect_remote()).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

ROLES = ("image", "video", "voice")

Progress = Callable[[float, str], None]
Cancel = Callable[[], bool]


class EngineError(RuntimeError):
    """An engine could not do the job; the message says why, in plain words."""


def _settings() -> dict:
    from .. import db

    return db.get_settings()


def status(role: str) -> dict:
    """{"ready": bool, "engine": str, "why": str} for one role. Never raises."""
    if role not in ROLES:
        return {"ready": False, "engine": "", "why": f"Unknown role {role!r}."}
    try:
        if role == "voice":
            from . import voice

            return voice.status()
        from . import makers

        return makers.status(role, _settings())
    except Exception as exc:  # noqa: BLE001 - a status read must never break the page asking
        return {"ready": False, "engine": "", "why": f"Could not check ({exc.__class__.__name__})."}


def make_image(prompt: str, *, negative: str = "", style: str = "", width: int = 1080, height: int = 1920,
               seed: int | None = None, progress: Progress | None = None, cancel: Cancel | None = None) -> Path:
    """A still picture (PNG) made from `prompt` by the picture model. The size is rounded to what the model draws
    (a multiple of 16, at most about 2 megapixels, same shape); a note with the model, licence, words and seed is
    saved next to it (same name, .json)."""
    from . import makers

    return makers.make_image(prompt, negative=negative, style=style, width=width, height=height, seed=seed,
                             progress=progress, cancel=cancel)


def make_video(prompt: str, *, image: Path | str | None = None, seconds: float = 4.0, width: int = 720,
               height: int = 1280, seed: int | None = None, progress: Progress | None = None,
               cancel: Cancel | None = None) -> Path:
    """A short silent video (MP4, H.264) made from `prompt`, animating `image` when one is given. Length, size and
    frame rate are rounded to what the model makes (the note next to it says what was made)."""
    from . import makers

    return makers.make_video(prompt, image=image, seconds=seconds, width=width, height=height, seed=seed,
                             progress=progress, cancel=cancel)


def speak(text: str, *, voice: str = "default", speed: float = 1.0, lang: str = "en",
          progress: Progress | None = None, cancel: Cancel | None = None) -> dict:
    """Speech from `text`: {"path": <wav, mono>, "duration_s": float, "words": [{"text", "start_s", "end_s"}],
    "word_timing": "estimated", ...}. Sentence starts and ends are exact; word times inside a sentence are
    estimated from word length."""
    from . import voice as voice_engine

    return voice_engine.speak(text, voice=voice, speed=speed, lang=lang, progress=progress, cancel=cancel)


def voices() -> list[dict]:
    """The voices the voice engine offers: [{"id", "name", "lang", "gender", "about"}] (empty until it is set up)."""
    from . import voice

    return voice.voices()


# ------------------------------------------------------------------ Settings → Pictures, video, voice
def overview() -> dict:
    """Everything the Settings section shows (cheap: does not start anything)."""
    from . import catalog, comfy_server, makers, models, remote, tasks, voice
    from ..cloud import settings as cloud_settings

    settings = _settings()
    mode = makers.mode(settings)
    app = makers.find_app(settings) if mode == "app" else None
    cloud = remote.check(settings) if mode == "remote" else None
    machine = makers.machine()
    flavor = machine["flavor"]
    # which model suits the computer that makes pictures and clips: this one, or the cloud computer
    maker_machine = remote.machine(cloud) if cloud else machine
    best = {r: makers.ranked(r, maker_machine)[0].id for r in ROLES if catalog.for_role(r)}
    # a cloud computer that did not answer has no graphics card to suit yet
    recommended = {best[r] for r in best if len(catalog.for_role(r)) > 1} if not cloud or cloud["base"] else set()
    out_models = []
    seen: dict = {}  # the model folders of the ComfyUI app (or of the cloud computer), asked once
    where = models.folders(mode, app) if mode == "clipforge" or (mode == "app" and app) else None
    for m in catalog.MODELS:
        if m.role == "voice":
            ready = voice.installed(m)
            out_models.append(_model_view(m, ready, 0 if ready else voice.download_bytes(m), True, ready, machine,
                                          recommended))
            continue
        base = app if mode == "app" else cloud["base"] if cloud else None
        try:
            lacking = models.missing(m, mode, base, seen) if mode != "off" else list(m.files)
            removable = bool(where) and bool(models.removal_plan(m, mode, base, seen, where)[0])
        except EngineError:
            lacking, removable = list(m.files), False
        out_models.append(_model_view(m, not lacking, sum(f.size for f in lacking), where is not None, removable,
                                      maker_machine, recommended))
    return {
        "online": cloud_settings.enabled(),
        "roles": {r: status(r) for r in ROLES},
        "comfyui": {"mode": mode, "url": settings.get("engines_comfyui_url") or "", "app_found": app,
                    "remote": _remote_view(cloud, settings),
                    "installed": comfy_server.installed(), "running": comfy_server.server.running(),
                    "version": catalog.COMFYUI["version"], "supported": bool(comfy_server.platform_key()),
                    "mac_too_old": comfy_server.mac_too_old(), "flavor": flavor,
                    "flavor_label": catalog.TORCH[flavor]["label"] if flavor else "",
                    "download_bytes": comfy_server.download_bytes() if comfy_server.platform_key() else 0,
                    "disk_bytes": comfy_server.disk_bytes() if comfy_server.platform_key() else 0,
                    "gpu": machine["gpu"], "idle_minutes": float(settings.get("engines_idle_minutes") or 10),
                    "licence": "GPL-3.0", "source": "https://github.com/comfyanonymous/ComfyUI"},
        "models": out_models,
        "chosen": {"image": settings.get("engines_picture") or "", "video": settings.get("engines_video") or "",
                   "voice": settings.get("engines_voice") or ""},
        "memory_mb": machine["memory_mb"],
        "vram_mb": machine["vram_mb"],
        "task": tasks.view(),
        "voice_rule": catalog.SUPERTONIC_RULE,
    }


def _remote_view(cloud: dict | None, settings: dict) -> dict:
    """The cloud computer for Settings (never its key: only whether one is kept)."""
    view = dict(cloud) if cloud else {"url": str(settings.get("engines_remote_url") or ""), "base": None, "why": "",
                                      "host": "", "gpu": "", "vram_mb": 0, "ram_mb": 0, "version": "", "device": ""}
    view["key_set"] = bool(settings.get("engines_remote_key"))
    view["found"] = view.pop("base", None)
    return view


def connect_remote(url: str, key: str | None = None) -> dict:
    """Settings → "A cloud computer" → Save and check: keep the address (and the key, when one is given: "" removes
    it), use the cloud computer for pictures and video, and check it now."""
    from .. import db
    from . import makers, remote

    patch: dict = {"engines_comfyui": "remote", "engines_remote_url": remote.normalize(url)}
    if key is not None:
        patch["engines_remote_key"] = remote.clean_key(key)
    db.save_settings(patch)
    makers.forget_found()
    return overview()


def remote_command(model_id: str, agreed: bool = False) -> dict:
    """The command that puts a model on the cloud computer (remote.command_for)."""
    from . import remote

    return remote.command_for(model_id, _settings(), agreed=agreed)


def _model_view(m, ready: bool, need: int, can_download: bool, removable: bool, machine: dict,
                recommended: set[str]) -> dict:
    from . import makers

    return {"id": m.id, "role": m.role, "name": m.name, "maker": m.maker, "licence": m.licence,
            "licence_url": m.licence_url, "about": m.about, "rule": m.rule, "bytes": m.bytes, "download_bytes": need,
            "ready": ready, "can_download": can_download, "removable": removable, "memory_gb": m.memory_gb,
            "vram_gb": m.vram_gb, "seconds": m.seconds, "fit": makers.fit(m, machine),
            "recommended": m.id in recommended}


def setup(what: str, model_id: str = "", agreed: bool = False) -> dict:
    """Start one set-up in the background: "comfyui" (ClipForge's own ComfyUI) or "model" (a model's files). A model
    whose licence comes with use rules (catalog.Model.rule) is only downloaded once the person agreed to them."""
    from . import catalog, comfy_server, makers, models, tasks, voice

    settings = _settings()
    if what == "comfyui":
        steps = comfy_server.setup_steps()
        return tasks.start("Setting up ComfyUI", steps, on_done=makers.forget_found)
    if what != "model":
        raise EngineError(f"Unknown set-up {what!r}.")
    m = catalog.by_id(model_id)
    if m is None:
        raise EngineError("Unknown model.")
    if m.rule and not agreed:
        raise EngineError(f"{m.name} comes with use rules; agree to them to download it. {m.rule}")
    if m.role == "voice":
        return tasks.start(f"Downloading {m.name}", voice.install_steps(m))
    mode = makers.mode(settings)
    if mode == "off":
        raise EngineError("Pictures and video are turned off. Choose a ComfyUI first.")
    if mode == "remote":
        raise EngineError(f"ClipForge cannot download {m.name} onto your cloud computer by itself. Press \"Put it on "
                          "your cloud computer\" next to it: it shows a command to paste into the cloud computer.")
    base = makers.find_app(settings, max_age=0) if mode == "app" else None
    if mode == "app" and not base:
        raise EngineError("ComfyUI is not running. Open the ComfyUI app first, then download the model.")
    return tasks.start(f"Downloading {m.name}", models.install_steps(m, mode, base))


def cancel() -> dict:
    from . import tasks

    return tasks.cancel()


def remove(what: str, model_id: str = "") -> dict:
    """Delete ClipForge's own ComfyUI ("comfyui") or a model's files ("model"), to free disk space: only the files
    ClipForge downloaded into the folders of the ComfyUI in use, and never a file another model there still uses."""
    from . import catalog, comfy_server, makers, models, tasks, voice
    from .comfy import Comfy

    if tasks.running():
        raise EngineError("Wait for the set-up to finish, or cancel it, first.")
    m = catalog.by_id(model_id)
    if what == "model" and m is not None and m.role == "voice":  # the voice runs inside ClipForge, not in ComfyUI
        voice.remove(m)
        return overview()
    with comfy_server.removing():  # refused while a picture or clip is being made; none starts meanwhile
        if what == "comfyui":
            comfy_server.remove()
            return overview()
        if what != "model" or m is None:
            raise EngineError("Unknown model.")
        settings = _settings()
        mode = makers.mode(settings)
        if mode == "off":
            raise EngineError("Pictures and video are turned off. Choose a ComfyUI in Settings first.")
        if mode == "remote":
            raise EngineError(f"{m.name} on your cloud computer stays there: delete its files in ComfyUI's models "
                              "folder on the cloud computer, or delete the whole pod in RunPod.")
        base = makers.find_app(settings, max_age=0) if mode == "app" else None
        if mode == "app" and not base:
            raise EngineError("ComfyUI is not running. Open the ComfyUI app first, then remove the model.")
        paths, kept = models.removal_plan(m, mode, base)
        if not paths:
            if kept:
                raise EngineError(f"{m.name}'s files are also used by {_and(_users(kept))}, so they were kept.")
            raise EngineError(f"ClipForge did not download {m.name}'s files into this ComfyUI, so it leaves them "
                              "alone. Remove them in ComfyUI itself.")
        # only a stopped download (.part files) is left of ClipForge's: ComfyUI never opens one
        stopped = all(p.suffix == ".part" for p in paths)
        stopped_bytes = sum(p.stat().st_size for p in paths if p.is_file()) if stopped else 0
        # ComfyUI keeps the model files it loaded open (Windows then refuses to delete them): ClipForge's own ComfyUI
        # lets go of them (release_files), a ComfyUI app is asked to unload its models
        if not stopped and mode == "clipforge":
            comfy_server.server.release_files()
        elif not stopped:
            Comfy(str(base), timeout=30).free()
        models.remove(m, mode, base)
    view = overview()
    notes = []
    if stopped:
        notes.append(f"Deleted {m.name}'s stopped download ({_size(stopped_bytes)}).")
        if any(v["id"] == m.id and v["ready"] for v in view["models"]):
            notes.append(f"{m.name} itself stays: ClipForge did not download its files.")
    if kept:
        names = [f.name for f, _ in kept]
        users = _users(kept)
        notes.append(("" if stopped else f"{m.name} removed. ") + f"Kept {_and(names)} "
                     f"({_size(sum(f.size for f, _ in kept))}): {_and(users)} {'needs' if len(users) == 1 else 'need'} "
                     f"{'it' if len(names) == 1 else 'them'} too.")
    if notes:
        view["note"] = " ".join(notes)
    return view


def _users(kept) -> list[str]:
    return sorted({u for _, users in kept for u in users})


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _size(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{max(1, round(n / 1e6))} MB"


def make_room(kind: str) -> None:
    """Heavy work is about to use the graphics card (gpu.py): ClipForge's own ComfyUI hands its memory back."""
    try:
        from . import makers

        makers.make_room(kind)
    except Exception:  # noqa: BLE001 - a courtesy
        pass


def shutdown() -> None:
    try:
        from . import comfy_server, tasks, voice

        tasks.stop()  # a set-up under way stops its download or uv first
        comfy_server.shutdown()
        voice.unload()
    except Exception:  # noqa: BLE001 - shutting down
        pass

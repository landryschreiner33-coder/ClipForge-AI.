"""The model files of the picture and video makers: whether ComfyUI has them, downloading them into the right folder,
and removing them again.

ClipForge's own ComfyUI reads <models>/comfy/<folder>/ (its extra_model_paths.yaml). A ComfyUI that is already on
this computer (the desktop app, a manual install) tells ClipForge its model folders (GET /internal/folder_paths) and
ClipForge downloads into the first one of each kind; for a ComfyUI on another computer ClipForge can only use models it
already has. Every file ClipForge downloaded and checked is listed in <models>/comfy/clipforge-verified.json, so a
model counts as set up only when each of its files is there with its size and was checked once, and Remove only ever
deletes files ClipForge downloaded itself.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from . import EngineError, catalog, files
from .comfy import Comfy, local_address

INDEX = "clipforge-verified.json"
_lock = threading.Lock()


def index_path() -> Path:
    from .comfy_server import models_root

    return models_root() / INDEX


def _read_index() -> dict:
    try:
        data = json.loads(index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    got = data.get("files") if isinstance(data, dict) else None
    return got if isinstance(got, dict) else {}


def _write_index(entries: dict) -> None:
    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(INDEX + ".tmp")
    tmp.write_text(json.dumps({"files": entries}, indent=1), encoding="utf-8")
    tmp.replace(path)


def _record(path: Path, f: catalog.ModelFile, model_id: str) -> None:
    with _lock:
        entries = _read_index()
        entries[str(path)] = {"sha256": f.sha256, "size": f.size, "model": model_id, "verified_at": time.time()}
        _write_index(entries)


def verified(path: Path, f: catalog.ModelFile) -> bool:
    """`path` is the file ClipForge downloaded and checked (and it still has its size)."""
    entry = _read_index().get(str(path)) or {}
    try:
        return entry.get("sha256") == f.sha256 and path.is_file() and path.stat().st_size == f.size
    except OSError:
        return False


# ------------------------------------------------------------------ where the files go
def folders(mode: str, base: str | None) -> dict[str, Path] | None:
    """Where each kind of model file goes for the ComfyUI in use (None: ClipForge cannot put files there)."""
    from .comfy_server import models_root

    if mode == "clipforge":
        return {sub: models_root() / sub for sub in catalog.MODEL_FOLDERS}
    if not base or not local_address(base):
        return None
    try:
        r = Comfy(base, timeout=10)._get("/internal/folder_paths")  # noqa: SLF001
        data = r.json() if r.status_code == 200 else {}
    except (EngineError, ValueError):
        return None
    out: dict[str, Path] = {}
    for sub in catalog.MODEL_FOLDERS:
        paths = data.get(sub) if isinstance(data, dict) else None
        if isinstance(paths, list) and paths and isinstance(paths[0], str):
            out[sub] = Path(paths[0])
    # an older ComfyUI calls diffusion_models "unet" and text_encoders "clip"
    if "diffusion_models" not in out and isinstance(data.get("unet"), list) and data["unet"]:
        out["diffusion_models"] = Path(data["unet"][0])
    if "text_encoders" not in out and isinstance(data.get("clip"), list) and data["clip"]:
        out["text_encoders"] = Path(data["clip"][0])
    return out or None


def file_path(f: catalog.ModelFile, where: dict[str, Path]) -> Path:
    return where[f.folder] / f.name


# ------------------------------------------------------------------ what is there
def missing(model: catalog.Model, mode: str, base: str | None, seen: dict[str, list[str] | None] | None = None
            ) -> list[catalog.ModelFile]:
    """The files of `model` the ComfyUI in use does not have yet."""
    if mode == "clipforge":
        where = folders("clipforge", None) or {}
        return [f for f in model.files if not verified(file_path(f, where), f)]
    if not base:
        return list(model.files)
    seen = {} if seen is None else seen
    out = []
    for f in model.files:
        if f.folder not in seen:
            try:
                seen[f.folder] = Comfy(base, timeout=10).model_files(f.folder)
            except EngineError:
                seen[f.folder] = None
        names = seen[f.folder]
        if names is None or not any(n == f.name or n.replace("\\", "/").endswith("/" + f.name) for n in names):
            out.append(f)
    return out


def download_bytes(model: catalog.Model, mode: str, base: str | None) -> int:
    return sum(f.size for f in missing(model, mode, base))


# ------------------------------------------------------------------ getting and removing them
def install_steps(model: catalog.Model, mode: str, base: str | None) -> list:
    """The steps that download the files of `model` ComfyUI does not have yet."""
    where = folders(mode, base)
    if where is None:
        raise EngineError("ClipForge can only put models into a ComfyUI on this computer. Download them in that "
                          "ComfyUI, or use ClipForge's own ComfyUI.")
    todo = missing(model, mode, base)
    lacking = sorted({f.folder for f in todo if f.folder not in where})
    if lacking:
        raise EngineError(f"That ComfyUI has no {', '.join(lacking)} folder; it may be too old. Update it, or use "
                          "ClipForge's own ComfyUI.")
    if not todo:
        return []
    total = sum(f.size for f in todo)
    first = file_path(todo[0], where)

    def check_space(report, cancelled) -> None:
        files.need_space(first.parent, total, model.name)

    steps = [check_space]
    for n, f in enumerate(todo, 1):
        steps.append(_download_step(model, f, file_path(f, where), n, len(todo)))
    return steps


def _download_step(model: catalog.Model, f: catalog.ModelFile, dest: Path, n: int, of: int):
    def step(report, cancelled) -> None:
        label = f"{model.name}: file {n} of {of} ({f.size / 1e9:.1f} GB)"
        if dest.is_file():
            # a file with the same name and size (another program put it there): use it once it is checked
            if dest.stat().st_size == f.size and files.sha256_file(
                    dest, lambda d: report(f"Checking {label}", d, f.size), cancelled) == f.sha256:
                _record(dest, f, model.id)
                return
            if str(dest) not in _read_index():  # someone else's file of that name: never replaced
                raise EngineError(f"{dest} is already there but is not the file {model.name} needs; ClipForge did "
                                  "not replace it. Move it away and try again.")
        files.fetch(f.pin, dest, lambda d: report(f"Downloading {label}", d, f.size), cancelled,
                    lambda d: report(f"Checking {label}", d, f.size))
        _record(dest, f, model.id)

    return step


def remove(model: catalog.Model, keep: set[str]) -> list[str]:
    """Delete the files of `model` that ClipForge downloaded and no model in `keep` (ids) still uses."""
    used = {(f.folder, f.name) for m in catalog.MODELS if m.id in keep and m.id != model.id for f in m.files}
    removed = []
    with _lock:
        entries = _read_index()
        for path_s, entry in list(entries.items()):
            path = Path(path_s)
            mine = next((f for f in model.files if f.name == path.name and entry.get("sha256") == f.sha256), None)
            if not mine or (mine.folder, mine.name) in used:
                continue
            try:
                path.unlink(missing_ok=True)
                path.with_name(path.name + ".part").unlink(missing_ok=True)
            except OSError as exc:
                raise EngineError(f"Could not delete {path.name} ({exc}).") from exc
            entries.pop(path_s, None)
            removed.append(path.name)
        _write_index(entries)
    return removed

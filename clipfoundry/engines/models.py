"""The model files of the picture and video makers: whether ComfyUI has them, downloading them into the right folder,
and removing them again.

ClipForge's own ComfyUI reads <models>/comfy/<folder>/ (its extra_model_paths.yaml). A ComfyUI that is already on
this computer (the desktop app, a manual install) tells ClipForge its model folders (GET /internal/folder_paths) and
ClipForge downloads into the first one of each kind; for a ComfyUI on another computer ClipForge can only use models it
already has. Every file ClipForge downloaded and checked is listed in <models>/comfy/clipforge-verified.json, so a
model counts as set up only when each of its files is there with its size and was checked once, and Remove only ever
deletes files ClipForge downloaded itself, in the folders of the ComfyUI in use, and never a file another model there
still uses.

A ComfyUI app may keep a model in a subfolder of its model folder ("flux2/flux-2-klein-4b.safetensors"); ComfyUI then
only takes the file by that name, so the graphs are given the names it lists (names()).
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
        entries.pop(str(_part(path)), None)
        _write_index(entries)


def _record_part(path: Path, f: catalog.ModelFile, model_id: str) -> None:
    """A download into `path` is starting: its `.part` file is ClipForge's (Remove may delete it if it stops)."""
    with _lock:
        entries = _read_index()
        entries[str(_part(path))] = {"part_of": f.sha256, "model": model_id, "started_at": time.time()}
        _write_index(entries)


def _part(path: Path) -> Path:
    return path.with_name(path.name + ".part")


def _our_part(path: Path, mode: str, entries: dict) -> bool:
    """Whether the `.part` file next to `path` is a download of ClipForge's that stopped: in ClipForge's own folders
    every file is; in a ComfyUI app's folders only one ClipForge started (another program may use that name)."""
    part = _part(path)
    return part.is_file() and (mode == "clipforge" or str(part) in entries)


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
def _listed(base: str, folder: str, seen: dict[str, list[str] | None]) -> list[str] | None:
    """The file names a ComfyUI lists in one model folder (asked once per `seen`)."""
    if folder not in seen:
        try:
            seen[folder] = Comfy(base, timeout=10).model_files(folder)
        except EngineError:
            seen[folder] = None
    return seen[folder]


def _match(f: catalog.ModelFile, listed: list[str] | None) -> str | None:
    """The name ComfyUI lists `f` by: the file itself at the top of its folder first, else the first one in a
    subfolder ("sub/name", "sub\\name" on Windows); None when it does not list it."""
    if not listed:
        return None
    if f.name in listed:
        return f.name
    return next((n for n in listed if n.replace("\\", "/").endswith("/" + f.name)), None)


def missing(model: catalog.Model, mode: str, base: str | None, seen: dict[str, list[str] | None] | None = None
            ) -> list[catalog.ModelFile]:
    """The files of `model` the ComfyUI in use does not have yet."""
    if mode == "clipforge":
        where = folders("clipforge", None) or {}
        return [f for f in model.files if not verified(file_path(f, where), f)]
    if not base:
        return list(model.files)
    seen = {} if seen is None else seen
    return [f for f in model.files if _match(f, _listed(base, f.folder, seen)) is None]


def names(model: catalog.Model, mode: str, base: str | None, seen: dict[str, list[str] | None] | None = None
          ) -> dict[str, str]:
    """{file name: the name the ComfyUI in use takes it by} for the graphs (ClipForge's own ComfyUI has each file at
    the top of its folder)."""
    if mode == "clipforge" or not base:
        return {f.name: f.name for f in model.files}
    seen = {} if seen is None else seen
    return {f.name: _match(f, _listed(base, f.folder, seen)) or f.name for f in model.files}


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
        _record_part(dest, f, model.id)
        files.fetch(f.pin, dest, lambda d: report(f"Downloading {label}", d, f.size), cancelled,
                    lambda d: report(f"Checking {label}", d, f.size))
        _record(dest, f, model.id)

    return step


def _present(f: catalog.ModelFile, mode: str, base: str | None, where: dict[str, Path],
             seen: dict[str, list[str] | None]) -> bool:
    if mode == "clipforge":
        return f.folder in where and verified(file_path(f, where), f)
    return bool(base) and _match(f, _listed(str(base), f.folder, seen)) is not None


def _still_needed(other: catalog.Model, f: catalog.ModelFile, mode: str, base: str | None,
                  where: dict[str, Path], seen: dict[str, list[str] | None], entries: dict) -> bool:
    """Whether `other`, which shares the file `f`, still needs it in the ComfyUI in use: every other file of it is
    there, or ClipForge downloaded (or was downloading) one of them there. A file of the person's own that only has
    the name of one of its files (FLUX.1's VAE and Z-Image's are both ae.safetensors) is not enough."""
    rest = [g for g in other.files if (g.folder, g.name) != (f.folder, f.name)]
    if rest and all(_present(g, mode, base, where, seen) for g in rest):
        return True
    return any(g.folder in where and (verified(file_path(g, where), g) or _our_part(file_path(g, where), mode, entries))
               for g in rest)


def removal_plan(model: catalog.Model, mode: str, base: str | None, seen: dict[str, list[str] | None] | None = None,
                 where: dict[str, Path] | None = None
                 ) -> tuple[list[Path], list[tuple[catalog.ModelFile, list[str]]]]:
    """What Remove would delete for `model` in the ComfyUI in use: (the files ClipForge downloaded there and the
    `.part` files of a download that was stopped, [(a shared file that stays, the models that still need it)]).
    A shared file (the picture models' text encoder) stays while another model there still needs it."""
    if mode not in ("clipforge", "app"):
        return [], []
    where = folders(mode, base) if where is None else where
    if not where:
        return [], []
    seen = {} if seen is None else seen
    entries = _read_index()
    paths: list[Path] = []
    kept: list[tuple[catalog.ModelFile, list[str]]] = []
    for f in model.files:
        if f.folder not in where:
            continue
        path = file_path(f, where)
        ours = (entries.get(str(path)) or {}).get("sha256") == f.sha256 and path.is_file()
        our_part = _our_part(path, mode, entries)
        if not ours and not our_part:
            continue  # not a file ClipForge downloaded, nor one it was downloading
        # a stopped download of a shared file belongs to the model whose download it was (its index entry says)
        started_by = (entries.get(str(_part(path))) or {}).get("model") if our_part else None
        users = [m.name for m in catalog.MODELS if m.id != model.id and m.role != "voice"
                 and any((g.folder, g.name, g.sha256) == (f.folder, f.name, f.sha256) for g in m.files)
                 and (m.id == started_by or _still_needed(m, f, mode, base, where, seen, entries))]
        if users:
            kept.append((f, users))
            continue
        paths += [path] if ours else []
        paths += [_part(path)] if our_part else []
    return paths, kept


def _delete(path: Path, tries: int = 6) -> None:
    """Delete a file; Windows refuses while a program still holds it, which a ComfyUI that was just asked to unload
    its models (or a virus scanner) stops doing within moments."""
    for n in range(tries):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if n == tries - 1:
                raise
            time.sleep(0.5 * (n + 1))


def remove(model: catalog.Model, mode: str, base: str | None) -> list[str]:
    """Delete the files of `model` that ClipForge downloaded into the folders of the ComfyUI in use (and the `.part`
    files of a stopped download) that no other model there still needs (removal_plan); returns their names."""
    paths, _ = removal_plan(model, mode, base)
    removed = []
    with _lock:
        entries = _read_index()
        for path in paths:
            try:
                existed = path.is_file()
                _delete(path)
                if path.suffix != ".part" and (mode == "clipforge" or str(_part(path)) in entries):
                    _delete(_part(path))
                    entries.pop(str(_part(path)), None)
            except OSError as exc:
                _write_index(entries)
                raise EngineError(f"Could not delete {path.name} ({exc}). Close the programs that use it and try "
                                  "again.") from exc
            entries.pop(str(path), None)
            if existed:
                removed.append(path.name)
        _write_index(entries)
    return removed

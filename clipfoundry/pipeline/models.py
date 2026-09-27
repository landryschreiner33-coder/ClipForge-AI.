"""Whisper model files: complete download, verification and self-repair.

faster-whisper normally downloads into the Hugging Face cache layout

    models/models--<org>--<repo>/snapshots/<40-character commit>/<file>

huggingface_hub writes the downloaded blobs with Windows long-path syntax, but not that snapshot entry. When
ClipFoundry lives in a deep folder (e.g. a ZIP extracted in Downloads), the entry for the longest file name,
preprocessor_config.json, passes Windows' 260-character limit and the download dies with WinError 3, leaving a
half-installed model. So ClipFoundry keeps every model in a short, flat folder

    models/<name>/config.json, model.bin, preprocessor_config.json, tokenizer.json, vocabulary.*

downloads it file by file, checks every file against the sizes and hashes published on the Hub, and only then hands
the folder to WhisperModel. Missing, truncated or corrupted files are deleted and downloaded again.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from .. import config
from .common import log, write_json

# The files faster-whisper loads (the same list as faster_whisper.utils.download_model).
PATTERNS = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*")
MARKER = "clipfoundry-model.json"  # written only after every file was verified
NET_FIX = "check the internet connection (each Whisper model is downloaded only once), then try again"

Progress = Callable[[int, int], None]  # bytes present, bytes total


class ModelError(RuntimeError):
    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.fix = fix


def repo_id(name: str) -> str:
    if "/" in name:
        return name
    from faster_whisper.utils import _MODELS

    if name not in _MODELS:
        raise ModelError(f"Unknown Whisper model '{name}'.", f"choose one of: {', '.join(sorted(_MODELS))}")
    return _MODELS[name]


def model_dir(name: str) -> Path:
    return config.models_dir() / name.replace("/", "--")


def _long(path: Path | str) -> str:
    """Windows extended-length form, so paths over 260 characters (old cache layout) can still be used."""
    p = os.path.abspath(str(path))
    if os.name != "nt" or p.startswith("\\\\?\\"):
        return p
    return "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p


def _read_marker(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / MARKER).read_text(encoding="utf-8"))
        return data if isinstance(data.get("files"), dict) and data["files"] else None
    except (OSError, ValueError):
        return None


def local_problems(folder: Path) -> list[str]:
    """Fast check (no network, no hashing) against the file list recorded after the last verified download."""
    marker = _read_marker(folder)
    if marker is None:
        return ["not downloaded yet" if not folder.exists() else "the download never completed"]
    problems = []
    for name, size in marker["files"].items():
        path = folder / name
        if not path.is_file():
            problems.append(f"{name} is missing")
        elif path.stat().st_size != size:
            problems.append(f"{name} is incomplete ({path.stat().st_size:,} of {size:,} bytes)")
    return problems


def is_ready(name: str) -> bool:
    if Path(name).is_dir():
        return True
    try:
        return not local_problems(model_dir(name))
    except OSError:
        return False


def remote_manifest(repo: str) -> tuple[str, dict[str, dict]]:
    """Commit and {file: size/sha256/git_sha1} of the model files published on the Hub."""
    from huggingface_hub import HfApi

    info = HfApi(endpoint=os.environ.get("HF_ENDPOINT") or None).model_info(repo, files_metadata=True)
    files = {}
    for sib in info.siblings or []:
        if any(fnmatch.fnmatch(sib.rfilename, p) for p in PATTERNS):
            lfs = sib.lfs
            files[sib.rfilename] = {"size": sib.size, "sha256": lfs.sha256 if lfs else None,
                                    "git_sha1": None if lfs else sib.blob_id}
    if not {"config.json", "model.bin"} <= set(files) or not any(n.startswith("vocabulary.") for n in files):
        raise ModelError(f"{repo} does not look like a faster-whisper model (files: {', '.join(sorted(files))}).")
    if not info.sha:
        raise ModelError(f"The Hub did not report a revision for {repo}.")
    return info.sha, files


def _hash_ok(path: Path, meta: dict) -> bool:
    if meta.get("sha256"):
        h, want = hashlib.sha256(), meta["sha256"]
    elif meta.get("git_sha1"):  # git blob hash of a small (non-LFS) file
        h, want = hashlib.sha1(b"blob %d\0" % path.stat().st_size), meta["git_sha1"]
    else:
        return True
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest() == want


def file_problem(folder: Path, name: str, meta: dict, deep: bool) -> str:
    path = folder / name
    if not path.is_file():
        return f"{name} is missing"
    size = path.stat().st_size
    if meta.get("size") is not None and size != meta["size"]:
        return f"{name} is incomplete ({size:,} of {meta['size']:,} bytes)"
    if name.endswith(".json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return f"{name} is not valid JSON"
    if deep and not _hash_ok(path, meta):
        return f"{name} is corrupted (checksum mismatch)"
    return ""


def _discard(folder: Path, names: list[str]) -> None:
    """Delete bad files *and* their huggingface_hub metadata, which would otherwise make the hub skip them."""
    (folder / MARKER).unlink(missing_ok=True)
    meta_dir = folder / ".cache" / "huggingface" / "download"
    for name in names:
        for path in (folder / name, meta_dir / f"{name}.metadata", meta_dir / f"{name}.lock"):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("could not delete %s: %s", path, exc)


def _bytes_present(folder: Path, files: dict) -> int:
    done = sum((folder / n).stat().st_size for n in files if (folder / n).is_file())
    meta_dir = folder / ".cache" / "huggingface" / "download"
    if meta_dir.is_dir():
        done += sum(p.stat().st_size for p in meta_dir.glob("*.incomplete") if p.is_file())
    return done


def _download(repo: str, commit: str, folder: Path, files: dict, progress: Progress | None) -> None:
    from huggingface_hub import hf_hub_download

    total = sum(int(m.get("size") or 0) for m in files.values())
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(0.5):
            try:
                progress(min(_bytes_present(folder, files), total), total)  # type: ignore[misc]
            except OSError:
                pass

    watcher = threading.Thread(target=watch, daemon=True) if progress else None
    if watcher:
        watcher.start()
    try:
        for name in sorted(files, key=lambda n: files[n].get("size") or 0):  # small files first, model.bin last
            if not file_problem(folder, name, files[name], deep=False):
                continue
            log.info("Downloading %s/%s (%s bytes)", repo, name, files[name].get("size"))
            hf_hub_download(repo, name, revision=commit, local_dir=folder,
                            endpoint=os.environ.get("HF_ENDPOINT") or None)
    finally:
        stop.set()
        if watcher:
            watcher.join(timeout=2)
    if progress:
        progress(min(_bytes_present(folder, files), total), total)


def _legacy_dirs(repo: str) -> list[Path]:
    slug = "models--" + repo.replace("/", "--")
    return [config.models_dir() / slug, config.models_dir() / ".locks" / slug]


def _adopt_legacy(repo: str, folder: Path, files: dict | None) -> list[str]:
    """Move complete files from the old models--org--repo cache into `folder` instead of downloading them again."""
    snaps = _legacy_dirs(repo)[0] / "snapshots"
    moved: list[str] = []
    try:
        commits = sorted(os.listdir(_long(snaps)))
    except OSError:
        return moved
    for commit in commits:
        try:
            names = os.listdir(_long(snaps / commit))
        except OSError:
            continue
        for name in names:
            if name in moved or (files is not None and name not in files) or (folder / name).exists():
                continue
            try:
                src = os.path.realpath(_long(snaps / commit / name))  # snapshot entries may link into blobs/
                size = os.path.getsize(src)
                if not size or (files is not None and size != files[name].get("size")):
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                shutil.move(src, str(folder / name))
                moved.append(name)
            except OSError as exc:
                log.info("could not reuse %s from the old model cache: %s", name, exc)
    if moved:
        log.info("Reused %s from the old model cache for %s", ", ".join(sorted(moved)), repo)
    return moved


def _remove_legacy(repo: str) -> None:
    for d in _legacy_dirs(repo):
        if os.path.isdir(_long(d)):
            shutil.rmtree(_long(d), ignore_errors=True)


def _offline_usable(folder: Path) -> bool:
    """Without the Hub's file list: every file faster-whisper needs is present and readable."""
    names = {p.name for p in folder.iterdir() if p.is_file()} if folder.is_dir() else set()
    need = {"config.json", "model.bin", "tokenizer.json"}
    if "large-v3" in folder.name or "turbo" in folder.name:
        need.add("preprocessor_config.json")  # 128 mel bins; without it faster-whisper would assume 80
    if not need <= names or not any(n.startswith("vocabulary.") for n in names):
        return False
    return all(not file_problem(folder, n, {}, deep=False) for n in names if n.endswith(".json"))


def mark_suspect(name: str) -> None:
    """Force the next ensure_model() to re-check every file (hashes included) against the Hub."""
    if not Path(name).is_dir():
        (model_dir(name) / MARKER).unlink(missing_ok=True)


def ensure_model(name: str, progress: Progress | None = None) -> Path:
    """Return a folder with the complete, verified model `name`, downloading or repairing it first."""
    if Path(name).is_dir():  # a model folder chosen by the user
        if not (Path(name) / "model.bin").is_file():
            raise ModelError(f"{name} does not contain a faster-whisper model (model.bin is missing).")
        return Path(name)
    folder = model_dir(name)
    if not local_problems(folder):
        return folder
    repo = repo_id(name)
    try:
        commit, files = remote_manifest(repo)
    except ModelError:
        raise
    except Exception as exc:  # offline, proxy, Hub outage
        if not _offline_usable(folder):
            _adopt_legacy(repo, folder, None)
        if _offline_usable(folder):
            log.warning("Could not check Whisper '%s' against Hugging Face (%s); using the local files", name, exc)
            return folder
        state = local_problems(folder)[0]
        raise ModelError(f"Whisper model '{name}' is not ready ({state}) and could not be downloaded from "
                         f"Hugging Face: {exc}", NET_FIX) from exc
    folder.mkdir(parents=True, exist_ok=True)
    _adopt_legacy(repo, folder, files)
    problems: dict[str, str] = {}
    for attempt in (1, 2):
        _discard(folder, [n for n, m in files.items() if file_problem(folder, n, m, deep=False)])
        t0 = time.time()
        try:
            _download(repo, commit, folder, files, progress)
        except Exception as exc:  # noqa: BLE001
            raise ModelError(f"Downloading Whisper '{name}' from Hugging Face failed: {exc}", NET_FIX) from exc
        problems = {n: p for n, m in files.items() if (p := file_problem(folder, n, m, deep=True))}
        if not problems:
            write_json(folder / MARKER, {"repo": repo, "commit": commit, "verified": int(time.time()),
                                         "files": {n: m["size"] for n, m in files.items()}})
            _remove_legacy(repo)
            log.info("Whisper '%s' is complete and verified (%d files, %.2f GB) in %s [%.0f s]", name, len(files),
                     sum(m["size"] or 0 for m in files.values()) / 1e9, folder, time.time() - t0)
            return folder
        log.warning("Whisper '%s' failed verification (%s); downloading the bad files again (attempt %d)",
                    name, "; ".join(problems.values()), attempt)
        _discard(folder, list(problems))
    raise ModelError(f"Whisper model '{name}' is still incomplete after downloading it twice: "
                     f"{'; '.join(problems.values())}",
                     f"check free disk space and the connection, or delete {folder} and try again")

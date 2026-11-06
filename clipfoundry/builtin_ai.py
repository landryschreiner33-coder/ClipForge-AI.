"""The built-in AI: a free model that runs on this computer, set up from inside the app.

ClipForge downloads two things once, when you choose "Set up the built-in AI" in Settings → AI helper, and checks
every byte against a fixed SHA-256 before using them:

* the engine: llama.cpp's `llama-server` (MIT license), a pinned release built by the llama.cpp project for this
  kind of computer (Mac with Apple silicon, Windows x64 with Vulkan for any graphics card, Linux x64);
* one model, at the level that fits this computer (Basic: Qwen3-VL 2B; Standard: Gemma 4 E4B; Pro: Gemma 4 26B
  A4B). All three are Apache 2.0, read images as well as text (used by later phases), and come from fixed revisions
  of ggml-org's or Qwen's own repositories on Hugging Face.

When a job asks the AI something, the engine starts on this computer only: 127.0.0.1, a free port and a fresh random
key for each start, no web page, no network access of its own (`--offline`). It loads the model, answers, and stops
after some idle minutes so the memory goes back to video work. A server left over from a run that was killed is
stopped at the next start (its process id is recorded), and on Windows the engine runs in a job object that closes
with the app.

Nothing here is required: without the built-in AI the rules decide alone, exactly as before.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable

import httpx

from . import config

log = logging.getLogger(__name__)

ENGINE_VERSION = "b12017"  # llama.cpp release, 2026-10-30
ENGINE_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{version}/{file}"
ENGINE_LICENSE = ("llama.cpp, https://github.com/ggml-org/llama.cpp, release {version}.\n"
                  "MIT License. Copyright (c) 2023-2026 The ggml authors.\n"
                  "Permission is hereby granted, free of charge, to any person obtaining a copy of this software and "
                  "associated documentation files (the \"Software\"), to deal in the Software without restriction, "
                  "including without limitation the rights to use, copy, modify, merge, publish, distribute, "
                  "sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is "
                  "furnished to do so, subject to the following conditions: The above copyright notice and this "
                  "permission notice shall be included in all copies or substantial portions of the Software.\n"
                  "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.\n")
ENGINES: dict[str, dict] = {
    "darwin-arm64": {"file": "llama-b12017-bin-macos-arm64.tar.gz", "size": 16508951, "server": "llama-b12017/llama-server",
                     "sha256": "4cfa51501cc3c602b404f43682e713405b4b946847876c5081d0a3f93ff26914"},
    "windows-x64": {"file": "llama-b12017-bin-win-vulkan-x64.zip", "size": 37514219, "server": "llama-server.exe",
                    "sha256": "e3d43788fed7b2e5983320975cb21d91fbc2579698a497f0f8cecbe9c029312b"},
    "linux-x64": {"file": "llama-b12017-bin-ubuntu-x64.tar.gz", "size": 22880375, "server": "llama-b12017/llama-server",
                  "sha256": "16fe348b1bc2e943bc4c220938ce46af789e88291138bca5bd68c0cc017769a5"},
}
LEVELS = ("basic", "standard", "pro")
MODELS: dict[str, dict] = {
    "basic": {
        "name": "Basic", "model": "Qwen3-VL 2B", "license": "Apache 2.0", "memory_gb": 8,
        "repo": "Qwen/Qwen3-VL-2B-Instruct-GGUF", "revision": "52d6c8ffea26cc873ac5ad116f8631268d7eb503",
        "files": [{"name": "Qwen3VL-2B-Instruct-Q4_K_M.gguf", "role": "model", "size": 1107409952,
                   "sha256": "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae"},
                  {"name": "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf", "role": "vision", "size": 445053216,
                   "sha256": "f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82"}],
        "about": "For computers with 8 GB of memory or no graphics card. Fast; simpler judgments.",
    },
    "standard": {
        "name": "Standard", "model": "Gemma 4 E4B", "license": "Apache 2.0", "memory_gb": 16,
        "repo": "ggml-org/gemma-4-E4B-it-GGUF", "revision": "a69f018d7678a2b9f5e705f8903d6fb29b9b25dc",
        "files": [{"name": "gemma-4-E4B-it-Q4_0.gguf", "role": "model", "size": 4590807392,
                   "sha256": "a555b900214b477d8880e7832e0b8925e139b0159640036b09fe472b6f2097f2"},
                  {"name": "mmproj-gemma-4-E4B-it-Q8_0.gguf", "role": "vision", "size": 559874816,
                   "sha256": "197f49a93027f9843772bd24a6a9e0be2a32a788de5a3def330e9c585d86edd1"}],
        "about": "For a Mac with 16 GB, or a PC with 16 GB and a graphics card. The recommended level.",
    },
    "pro": {
        "name": "Pro", "model": "Gemma 4 26B A4B", "license": "Apache 2.0", "memory_gb": 32,
        "repo": "ggml-org/gemma-4-26B-A4B-it-GGUF", "revision": "bb4531cda34d1ea09d9814959ed4d5833cf2a4c8",
        "files": [{"name": "gemma-4-26B-A4B-it-Q4_0.gguf", "role": "model", "size": 14618145824,
                   "sha256": "d208665ab1cd3a69f7a9a4bc59430e8448c8093d9b06334f566ac59d6d504a03"},
                  {"name": "mmproj-gemma-4-26B-A4B-it-Q8_0.gguf", "role": "vision", "size": 806408320,
                   "sha256": "cc4e855736da450bf1e162d8cccfe0ad685727d0c9e04ef7dd8d884f3121039b"}],
        "about": "For a Mac with 32 GB or more, or a graphics card with 24 GB. Best judgment; a large download.",
    },
}
MARKER = "clipforge-verified.json"   # written only after every file of a folder was checked
ALIAS = "clipforge-builtin"
CONTEXT = 8192
START_TIMEOUT_S = 300.0              # loading a large model from a slow disk can take minutes
DEFAULT_IDLE_MIN = 10.0
IDLE_POLL_S = 15.0
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

Progress = Callable[[int, int], None]


class BuiltinError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ this computer
def platform_key() -> str:
    import platform

    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "darwin":
        return "darwin-arm64" if arm else ""
    if sys.platform == "win32":
        return "" if arm else "windows-x64"
    if sys.platform.startswith("linux"):
        return "" if arm else "linux-x64"
    return ""


def memory_mb() -> int:
    """Total memory of this computer in MB (0 when it cannot be read)."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                 timeout=5).stdout
            return int(out.strip()) // (1 << 20)
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = Status()
            st.dwLength = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))  # type: ignore[attr-defined]
            return int(st.ullTotalPhys // (1 << 20))
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        pass
    return 0


def vram_mb() -> int:
    try:
        from .pipeline import cuda

        gpus = cuda.probe().get("gpus") or []
        return int((gpus[0] if gpus else {}).get("vram_mb") or 0)
    except Exception:  # noqa: BLE001 - only a hint for the level
        return 0


def recommended_level(mem_mb: int, gpu_mb: int, mac: bool) -> str:
    """Basic or Standard, from memory and graphics card. Pro is only ever chosen by hand (a 15 GB download)."""
    if mac:
        return "standard" if mem_mb >= 15000 else "basic"
    if gpu_mb >= 7500 or (mem_mb >= 15000 and gpu_mb >= 3500):
        return "standard"
    return "basic"


# ------------------------------------------------------------------ files on disk
def root() -> Path:
    return config.models_dir() / "builtin-ai"


def engine_dir() -> Path:
    return root() / f"engine-{ENGINE_VERSION}"


def level_dir(level: str) -> Path:
    return root() / level


def _sha256(path: Path, progress: Callable[[int], None] | None = None) -> str:
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(8 << 20), b""):
            h.update(block)
            done += len(block)
            if progress:
                progress(done)
    return h.hexdigest()


def _marker(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / MARKER).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_marker(folder: Path, data: dict) -> None:
    tmp = folder / (MARKER + ".tmp")
    tmp.write_text(json.dumps({**data, "verified_at": time.time()}, indent=1), encoding="utf-8")
    tmp.replace(folder / MARKER)


def engine_path() -> Path | None:
    """The verified server program, or None (never a file that was not checked)."""
    spec = ENGINES.get(platform_key())
    if not spec:
        return None
    m = _marker(engine_dir())
    exe = engine_dir() / spec["server"]
    if not m or m.get("sha256") != spec["sha256"] or not exe.is_file():
        return None
    return exe


def model_files(level: str) -> dict[str, Path] | None:
    """{role: path} of a verified level, or None. Only sizes are re-checked here (hashes were checked once)."""
    spec = MODELS.get(level)
    m = _marker(level_dir(level)) if spec else None
    if not spec or not m or m.get("revision") != spec["revision"]:
        return None
    out = {}
    for f in spec["files"]:
        p = level_dir(level) / f["name"]
        if not p.is_file() or p.stat().st_size != f["size"] or (m.get("files") or {}).get(f["name"]) != f["sha256"]:
            return None
        out[f["role"]] = p
    return out


def installed_levels() -> list[str]:
    return [lvl for lvl in LEVELS if model_files(lvl)]


def chosen_level(settings: dict) -> str:
    """The level the AI uses: the saved one when it is installed, else the best installed one."""
    want = str(settings.get("builtin_ai_level") or "auto")
    have = installed_levels()
    if want in have:
        return want
    for lvl in ("standard", "pro", "basic"):
        if lvl in have:
            return lvl
    return ""


def ready(settings: dict) -> bool:
    return bool(engine_path() and chosen_level(settings))


def label(settings: dict) -> str:
    lvl = chosen_level(settings)
    return f"Built-in AI ({MODELS[lvl]['model']})" if lvl else "Built-in AI (not set up yet)"


# ------------------------------------------------------------------ downloads
_task: dict = {}
_task_lock = threading.Lock()
_cancel = threading.Event()


def task() -> dict:
    with _task_lock:
        return dict(_task)


def _set(**fields) -> None:
    with _task_lock:
        _task.update(fields, updated_at=time.time())


def _download_url(url: str, dest: Path, size: int, progress: Callable[[int], None]) -> None:
    """Stream a file (resuming a partial one), never longer than `size`."""
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if have > size:
        part.unlink()
        have = 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with httpx.stream("GET", url, headers=headers, follow_redirects=True,
                      timeout=httpx.Timeout(30.0, read=120.0)) as r:
        if r.status_code == 200 and have:
            have = 0  # the server ignored the range: start over
        elif r.status_code not in (200, 206):
            raise BuiltinError(f"The download answered {r.status_code}.")
        with open(part, "ab" if have else "wb") as fh:
            for block in r.iter_bytes(1 << 20):
                if _cancel.is_set():
                    raise BuiltinError("Canceled.")
                have += len(block)
                if have > size:
                    raise BuiltinError("The download is larger than expected; it was stopped.")
                fh.write(block)
                progress(have)
    part.replace(dest)


def _safe_extract(archive: Path, dest: Path) -> None:
    """Unpack the engine: no absolute paths, no '..', and links only to files inside `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    base = dest.resolve()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                target = (dest / info.filename).resolve()
                if not str(target).startswith(str(base) + os.sep) and target != base:
                    raise BuiltinError(f"The engine archive contains an unsafe path ({info.filename}).")
            z.extractall(dest)
        return
    with tarfile.open(archive, "r:gz") as t:
        members = t.getmembers()
        for m in members:
            target = (dest / m.name).resolve()
            if not str(target).startswith(str(base) + os.sep):
                raise BuiltinError(f"The engine archive contains an unsafe path ({m.name}).")
            if m.issym() or m.islnk():
                link = (target.parent / m.linkname).resolve() if m.issym() else (dest / m.linkname).resolve()
                if not str(link).startswith(str(base) + os.sep):
                    raise BuiltinError(f"The engine archive contains a link out of its folder ({m.name}).")
            elif not (m.isfile() or m.isdir()):
                raise BuiltinError(f"The engine archive contains a special file ({m.name}).")
        try:
            t.extractall(dest, members=members, filter="data")
        except TypeError:  # an older Python without extraction filters: the checks above already ran
            t.extractall(dest, members=members)


def _install_engine(report: Callable[[str, int, int], None]) -> Path:
    key = platform_key()
    spec = ENGINES.get(key)
    if not spec:
        raise BuiltinError("The built-in AI needs a Mac with Apple silicon, or a 64-bit Windows or Linux PC.")
    exe = engine_path()
    if exe:
        return exe
    folder = engine_dir()
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    root().mkdir(parents=True, exist_ok=True)
    archive = root() / spec["file"]
    url = ENGINE_URL.format(version=ENGINE_VERSION, file=spec["file"])
    if not (archive.is_file() and archive.stat().st_size == spec["size"]):
        _download_url(url, archive, spec["size"], lambda n: report("Downloading the AI engine", n, spec["size"]))
    report("Checking the AI engine", 0, spec["size"])
    if _sha256(archive) != spec["sha256"]:
        archive.unlink(missing_ok=True)
        raise BuiltinError("The AI engine download was damaged (checksum mismatch). Try again.")
    tmp = root() / f".engine-{ENGINE_VERSION}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    _safe_extract(archive, tmp)
    exe = tmp / spec["server"]
    if not exe.is_file():
        raise BuiltinError("The AI engine archive does not contain its server program.")
    if os.name != "nt":
        exe.chmod(0o755)
    (tmp / "NOTICE-llama.cpp.txt").write_text(ENGINE_LICENSE.format(version=ENGINE_VERSION), encoding="utf-8")
    _write_marker(tmp, {"version": ENGINE_VERSION, "platform": key, "sha256": spec["sha256"], "source": url})
    tmp.replace(folder)
    archive.unlink(missing_ok=True)
    return folder / spec["server"]


def _hub_url(repo: str, revision: str, name: str) -> str:
    base = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
    return f"{base}/{repo}/resolve/{revision}/{name}"


def _install_level(level: str, report: Callable[[str, int, int], None]) -> dict[str, Path]:
    spec = MODELS[level]
    have = model_files(level)
    if have:
        return have
    folder = level_dir(level)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MARKER).unlink(missing_ok=True)
    total = sum(f["size"] for f in spec["files"])
    done_before = 0
    hashes: dict[str, str] = {}
    for f in sorted(spec["files"], key=lambda x: x["size"]):  # the small vision part first
        path = folder / f["name"]
        if not (path.is_file() and path.stat().st_size == f["size"]):
            path.unlink(missing_ok=True)
            _download_url(_hub_url(spec["repo"], spec["revision"], f["name"]), path, f["size"],
                          lambda n, base=done_before: report(f"Downloading {spec['model']}", base + n, total))
        got = _sha256(path, lambda n, base=done_before: report(f"Checking {spec['model']}", base + n, total))
        if got != f["sha256"]:
            path.unlink(missing_ok=True)
            raise BuiltinError(f"{f['name']} was damaged in the download (checksum mismatch). Try again.")
        hashes[f["name"]] = got
        done_before += f["size"]
    _write_marker(folder, {"level": level, "repo": spec["repo"], "revision": spec["revision"], "files": hashes})
    return model_files(level) or {}


def _free_bytes(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free


def needed_bytes(level: str) -> int:
    spec = MODELS[level]
    need = 0 if engine_path() else ENGINES.get(platform_key(), {}).get("size", 0) * 4  # archive + unpacked
    if not model_files(level):
        need += sum(f["size"] for f in spec["files"])
    return need


def install(level: str, on_done: Callable[[str], None] | None = None) -> dict:
    """Download and check the engine and one level in the background (progress in task())."""
    from .cloud import settings as cloud_settings

    if cloud_settings.enabled():
        raise BuiltinError("The built-in AI runs in the desktop app.", 403)
    if level not in MODELS:
        raise BuiltinError("Choose Basic, Standard or Pro.")
    if not platform_key():
        raise BuiltinError("The built-in AI needs a Mac with Apple silicon, or a 64-bit Windows or Linux PC.")
    need = needed_bytes(level)
    free = _free_bytes(root())
    if need and free < need + (2 << 30):
        raise BuiltinError(f"Not enough free disk space: the built-in AI needs about {(need + (2 << 30)) / 1e9:.1f} GB "
                           f"and {free / 1e9:.1f} GB is free.", 507)
    with _task_lock:
        if _task.get("state") == "running":
            raise BuiltinError("The built-in AI is already being set up; wait for it to finish.", 409)
        _cancel.clear()
        _task.clear()
        _task.update(level=level, state="running", status="Starting", completed=0, total=0, error="",
                     started_at=time.time(), updated_at=time.time())

    def report(status: str, completed: int, total: int) -> None:
        _set(status=status, completed=int(completed), total=int(total))

    def run() -> None:
        try:
            _install_engine(report)
            _install_level(level, report)
            _set(state="done", status="Ready", completed=0, total=0)
            if on_done:
                on_done(level)
        except (BuiltinError, httpx.HTTPError, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
            canceled = _cancel.is_set()
            _set(state="canceled" if canceled else "failed", status="Canceled" if canceled else "Failed",
                 error="" if canceled else _why(exc))
            log.warning("built-in AI setup (%s) stopped: %s", level, exc)

    threading.Thread(target=run, daemon=True, name=f"builtin-ai-{level}").start()
    return task()


def cancel() -> dict:
    _cancel.set()
    return task()


def _why(exc: Exception) -> str:
    if isinstance(exc, httpx.ConnectError):
        return "Could not connect. Check the internet connection, then try again (the download resumes)."
    if isinstance(exc, httpx.TimeoutException):
        return "The download stalled. Try again (it resumes where it stopped)."
    return str(exc)[:300] or exc.__class__.__name__


def remove(level: str) -> None:
    if level not in MODELS:
        raise BuiltinError("Unknown level.")
    if server.level == level:
        server.stop()
    shutil.rmtree(level_dir(level), ignore_errors=True)


# ------------------------------------------------------------------ the running engine
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _win_job():
    """A Windows job object that kills the engine when ClipForge's process ends, however it ends."""
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        job = k32.CreateJobObjectW(None, None)

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        return job
    except Exception:  # noqa: BLE001 - without it, the pid file still stops a leftover engine at the next start
        return None


def _assign(job, proc: subprocess.Popen) -> None:
    if job is None:
        return
    try:
        import ctypes

        ctypes.windll.kernel32.AssignProcessToJobObject(job, int(proc._handle))  # type: ignore[attr-defined]  # noqa: SLF001
    except Exception:  # noqa: BLE001
        pass


def _linux_pdeathsig() -> None:  # runs in the child before exec: die with the parent
    try:
        import ctypes
        import signal

        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except Exception:  # noqa: BLE001
        pass


def build_command(exe: Path, files: dict[str, Path], port: int, key: str, threads: int) -> list[str]:
    cmd = [str(exe), "-m", str(files["model"]), "--host", "127.0.0.1", "--port", str(port), "--api-key", key,
           "-a", ALIAS, "-c", str(CONTEXT), "-ngl", "auto", "-np", "1", "--no-webui", "--offline",
           "--reasoning-budget", "0", "-t", str(threads)]
    if files.get("vision"):
        cmd += ["--mmproj", str(files["vision"])]
    return cmd


class Server:
    """One engine process at a time, started on demand and stopped when idle."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.proc: subprocess.Popen | None = None
        self.level = ""
        self.port = 0
        self.key = ""
        self.last_used = 0.0
        self.started_at = 0.0
        self.idle_s = DEFAULT_IDLE_MIN * 60
        self._job = None
        self._watch: threading.Thread | None = None
        self._exit_hook = False

    @property
    def pid_file(self) -> Path:
        return root() / "engine.pid"

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _record(self) -> dict | None:
        try:
            data = json.loads(self.pid_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) and int(data.get("pid") or 0) > 0 else None
        except (OSError, ValueError, TypeError):
            return None

    def _shared(self, level: str) -> tuple[str, str] | None:
        """An engine another ClipForge process (the Autopilot worker, say) started and still runs: reuse it."""
        rec = self._record()
        if not rec or int(rec.get("owner") or 0) == os.getpid() or not _alive(int(rec.get("owner") or 0)):
            return None
        if not _is_our_engine(int(rec["pid"]), str(rec.get("exe") or "")):
            return None
        if rec.get("level") != level:
            raise BuiltinError("The built-in AI is running at another level in another ClipForge window; try again "
                               "in a few minutes.")
        return f"http://127.0.0.1:{int(rec['port'])}/v1", str(rec.get("key") or "")

    def _stop_leftover(self) -> None:
        """A server from a run that was killed (Force Quit, a crash) still holds memory: stop it."""
        rec = self._record()
        if not rec:
            return
        pid, exe, owner = int(rec["pid"]), str(rec.get("exe") or ""), int(rec.get("owner") or 0)
        if owner != os.getpid() and _alive(owner):
            return  # a live ClipForge process owns it
        self.pid_file.unlink(missing_ok=True)
        if not _is_our_engine(pid, exe):
            return
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10,
                               creationflags=NO_WINDOW)
            else:
                import signal

                os.kill(pid, signal.SIGTERM)
            log.info("stopped a built-in AI engine left over from an earlier run (pid %s)", pid)
        except (OSError, subprocess.SubprocessError):
            pass

    def ensure(self, settings: dict) -> tuple[str, str]:
        """(base URL, key) of a running engine for the chosen level; starts or restarts it as needed."""
        level = chosen_level(settings)
        exe = engine_path()
        if not exe or not level:
            raise BuiltinError("The built-in AI is not set up yet. Set it up in Settings → AI helper.")
        self.idle_s = max(60.0, float(settings.get("builtin_ai_idle_minutes") or DEFAULT_IDLE_MIN) * 60)
        with self._lock:
            if self.running() and self.level == level:
                self.last_used = time.time()
                return f"http://127.0.0.1:{self.port}/v1", self.key
            self.stop()
            shared = self._shared(level)
            if shared:
                return shared
            self._stop_leftover()
            files = model_files(level) or {}
            port, key = _free_port(), secrets.token_urlsafe(24)
            threads = max(1, min(8, (os.cpu_count() or 4) - 1))
            cmd = build_command(exe, files, port, key, threads)
            logs = config.data_dir() / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            out = open(logs / "builtin-ai.log", "ab")  # noqa: SIM115 - handed to the process, closed below
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("HF_", "HUGGING"))}
            kwargs: dict = {"stdout": out, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL,
                            "cwd": str(exe.parent), "env": env}
            if sys.platform == "win32":
                kwargs["creationflags"] = NO_WINDOW
                self._job = self._job or _win_job()
            elif sys.platform.startswith("linux"):
                kwargs["preexec_fn"] = _linux_pdeathsig
            log.info("starting the built-in AI (%s) on port %s", MODELS[level]["model"], port)
            try:
                proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 - a verified program, fixed arguments
            except OSError as exc:
                raise BuiltinError(f"The built-in AI could not start: {exc}") from exc
            finally:
                out.close()
            _assign(self._job, proc)
            if not self._exit_hook:
                import atexit

                atexit.register(shutdown)  # the Autopilot worker process stops its engine too
                self._exit_hook = True
            self.proc, self.level, self.port, self.key = proc, level, port, key
            self.started_at = self.last_used = time.time()
            try:
                fd = os.open(self.pid_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump({"pid": proc.pid, "exe": str(exe), "owner": os.getpid(), "port": port, "key": key,
                               "level": level}, fh)
            except OSError:
                pass
            try:
                self._wait_ready()
            except BuiltinError:
                self.stop()
                raise
            if self._watch is None or not self._watch.is_alive():
                self._watch = threading.Thread(target=self._idle_loop, daemon=True, name="builtin-ai-idle")
                self._watch.start()
            return f"http://127.0.0.1:{self.port}/v1", self.key

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if not self.running():
                raise BuiltinError("The built-in AI stopped while loading its model. Its log is in data/logs/"
                                   "builtin-ai.log; a computer with too little memory is the usual cause.")
            try:
                r = httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=2, trust_env=False)
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise BuiltinError("The built-in AI took too long to load its model.")

    def touch(self) -> None:
        self.last_used = time.time()

    def _idle_loop(self) -> None:
        while True:
            time.sleep(IDLE_POLL_S)
            with self._lock:
                if not self.running():
                    return
                if time.time() - self.last_used > self.idle_s:
                    log.info("stopping the idle built-in AI")
                    self.stop()
                    return

    def stop(self) -> None:
        with self._lock:
            proc, self.proc = self.proc, None
            self.level, self.port, self.key = "", 0, ""
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            rec = self._record() if proc is not None else None
            if rec and int(rec.get("pid") or 0) == proc.pid:
                self.pid_file.unlink(missing_ok=True)

    def view(self) -> dict:
        return {"running": self.running(), "level": self.level if self.running() else "",
                "since": self.started_at if self.running() else 0, "idle_minutes": round(self.idle_s / 60, 1)}


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                                 text=True, timeout=10, creationflags=NO_WINDOW).stdout
            return f'"{pid}"' in out
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _is_our_engine(pid: int, exe: str) -> bool:
    """Only a process running the engine program ClipForge installed is ever stopped."""
    try:
        if sys.platform.startswith("linux"):
            return os.path.realpath(f"/proc/{pid}/exe") == os.path.realpath(exe)
        if sys.platform == "darwin":
            out = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True,
                                 timeout=5).stdout.strip()
            return bool(out) and os.path.realpath(out) == os.path.realpath(exe)
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                                 text=True, timeout=10, creationflags=NO_WINDOW).stdout
            return Path(exe).name.lower() in out.lower()
    except (OSError, subprocess.SubprocessError):
        return False
    return False


server = Server()


def chat(settings: dict, system: str, prompt: str, *, timeout: float = 180.0, json_object: bool = False) -> str:
    """One request to the built-in AI; the answer's text (`json_object`: always one JSON object)."""
    base, key = server.ensure(settings)
    body = {"model": ALIAS, "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if json_object:
        body["response_format"] = {"type": "json_object"}
    try:
        r = httpx.post(f"{base}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"},
                       timeout=timeout, trust_env=False)
    finally:
        server.touch()
    if r.status_code != 200:
        raise BuiltinError(f"The built-in AI answered {r.status_code}: {r.text[:200]}")
    try:
        return r.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise BuiltinError("The built-in AI sent an answer in an unexpected shape.") from exc


def status(settings: dict) -> dict:
    """Everything Settings shows: this computer, the levels, what is installed and what is running."""
    mem, gpu = memory_mb(), vram_mb()
    key = platform_key()
    rec = recommended_level(mem, gpu, sys.platform == "darwin")
    engine = ENGINES.get(key)
    levels = []
    for lvl in LEVELS:
        spec = MODELS[lvl]
        levels.append({"id": lvl, "name": spec["name"], "model": spec["model"], "license": spec["license"],
                       "about": spec["about"], "memory_gb": spec["memory_gb"], "installed": bool(model_files(lvl)),
                       "download_bytes": sum(f["size"] for f in spec["files"]) + (0 if engine_path() or not engine
                                                                                   else engine["size"]),
                       "recommended": lvl == rec, "fits": mem == 0 or mem >= spec["memory_gb"] * 900})
    return {"supported": bool(engine), "engine": {"version": ENGINE_VERSION, "installed": bool(engine_path()),
                                                  "license": "MIT (llama.cpp)"},
            "computer": {"memory_mb": mem, "vram_mb": gpu, "mac": sys.platform == "darwin"},
            "levels": levels, "recommended": rec, "level": chosen_level(settings), "task": task(),
            "server": server.view()}


def make_room(kind: str) -> None:
    """Other heavy work (transcription) is about to use the graphics card: stop the engine this process started, so
    the two never compete for its memory. It starts again, in seconds, the next time the AI is asked something.
    A Mac with plenty of shared memory keeps it loaded."""
    if kind == "local AI model" or not server.running():
        return
    if sys.platform == "darwin" and memory_mb() >= 24000:
        return
    log.info("stopping the built-in AI to make room for %s", kind)
    server.stop()


def shutdown() -> None:
    try:
        server.stop()
    except Exception:  # noqa: BLE001 - shutting down
        pass

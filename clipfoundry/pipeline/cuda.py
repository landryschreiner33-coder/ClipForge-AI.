"""NVIDIA CUDA detection for faster-whisper / CTranslate2.

CTranslate2 finds the GPU through the NVIDIA driver, but it loads the CUDA math libraries (cuBLAS, and cuDNN on
some builds) by file name only when the model first runs. If they are missing, or only a different CUDA version
is installed (for example CUDA 13 while CTranslate2 needs `cublas64_12.dll`), the model loads fine and then fails
mid-transcription. This module:

* makes the `nvidia-*` pip wheels from requirements-gpu.txt visible (PATH / DLL directories, or preloading on Linux),
* reads the exact library names the installed CTranslate2 build loads from its binary,
* loads each one the same way CTranslate2 does and reports precisely what is missing and how to fix it.
"""
from __future__ import annotations

import ctypes
import importlib.util
import mmap
import os
import re
import shutil
import site
import subprocess
import sys
import threading
import time
from pathlib import Path

from .common import log

WINDOWS = sys.platform == "win32"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if WINDOWS else 0
GPU_FIX = ("run start.bat again (it installs the GPU libraries automatically), or run: "
           r".venv\Scripts\python -m pip install -r requirements-gpu.txt" if WINDOWS else
           "run: .venv/bin/python -m pip install -r requirements-gpu.txt")
DRIVER_FIX = "install the latest NVIDIA driver (Game Ready or Studio) and restart ClipFoundry"

# Names CTranslate2 passes to LoadLibrary/dlopen. The CUDA runtime itself is linked statically.
_LIB_RE = re.compile(rb"libcu(?:blasLt|blas|dnn)[a-z_]*\.so\.\d+|cu(?:blasLt|blas|dnn)[a-z_]*64_\d+\.dll")

_lock = threading.RLock()
_added: set[str] = set()
_loaded: list[object] = []  # keep preloaded libraries referenced
_required: list[str] | None = None
_status: dict | None = None


def pip_lib_dirs() -> list[Path]:
    """bin (Windows) or lib (Linux) folders of installed nvidia-* wheels such as nvidia-cublas-cu12."""
    roots: list[Path] = []
    try:
        roots += [Path(p) for p in site.getsitepackages()]
    except AttributeError:  # very old virtualenv
        pass
    roots += [Path(p) for p in sys.path if p.endswith("site-packages")]
    sub = "bin" if WINDOWS else "lib"
    dirs: list[Path] = []
    for root in dict.fromkeys(roots):
        base = root / "nvidia"
        if base.is_dir():
            for d in sorted(base.glob(f"*/{sub}")) + sorted(base.glob(f"*/*/{sub}")):
                if d.is_dir() and d not in dirs:
                    dirs.append(d)
    return dirs


def prepare() -> list[Path]:
    """Expose pip-installed NVIDIA libraries to CTranslate2. Safe to call repeatedly."""
    with _lock:
        dirs = pip_lib_dirs()
        if WINDOWS:
            path = os.environ.get("PATH", "")
            for d in reversed(dirs):
                if str(d) in _added:
                    continue
                _added.add(str(d))
                try:
                    os.add_dll_directory(str(d))  # type: ignore[attr-defined]
                except (OSError, AttributeError):
                    pass
                path = str(d) + os.pathsep + path  # CTranslate2 uses LoadLibrary, which searches PATH
            os.environ["PATH"] = path
        return dirs


def _ctranslate2_binaries() -> list[Path]:
    spec = importlib.util.find_spec("ctranslate2")
    if not spec or not spec.origin:
        return []
    pkg = Path(spec.origin).parent
    if WINDOWS:
        return sorted(pkg.glob("ctranslate2*.dll")) or sorted(pkg.glob("_ext*.pyd"))
    return sorted(pkg.parent.glob("ctranslate2.libs/libctranslate2*.so*")) + sorted(pkg.glob("libctranslate2*.so*"))


def required_libraries() -> list[str]:
    """CUDA libraries the installed CTranslate2 build loads at run time, e.g. ['cublas64_12.dll']."""
    global _required
    with _lock:
        if _required is None:
            names: set[str] = set()
            for binary in _ctranslate2_binaries():
                try:
                    with open(binary, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                        names.update(m.group().decode() for m in _LIB_RE.finditer(mm))  # type: ignore[arg-type]
                except (OSError, ValueError) as exc:
                    log.debug("could not scan %s: %s", binary, exc)
            # cuBLAS loads cuBLASLt itself; check the library CTranslate2 asks for first
            _required = sorted(names, key=lambda n: ("blasLt" in n, n))
        return list(_required)


def describe(lib: str) -> str:
    m = re.search(r"(?:64_|\.so\.)(\d+)", lib)
    major = m.group(1) if m else "?"
    if "cudnn" in lib:
        return f"cuDNN {major}"
    return f"CUDA {major} cuBLAS" if "cublas" in lib else lib


def _load(target: str) -> object:
    if WINDOWS:
        if os.sep in target or "/" in target:
            return ctypes.WinDLL(target)  # full path: dependencies are searched next to it
        return ctypes.WinDLL(target, winmode=0)  # by name, same search order as CTranslate2's LoadLibrary
    return ctypes.CDLL(target, mode=ctypes.RTLD_GLOBAL)


def _module_path(lib: object, name: str) -> str:
    try:
        if WINDOWS:
            buf = ctypes.create_unicode_buffer(1024)
            ctypes.windll.kernel32.GetModuleFileNameW(ctypes.c_void_p(lib._handle), buf, 1024)  # type: ignore[attr-defined]
            return buf.value
        with open("/proc/self/maps", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.rstrip().endswith("/" + name):
                    return line.split(None, 5)[-1].strip()
    except (OSError, AttributeError, ValueError):
        pass
    return ""


def check_library(name: str, dirs: list[Path]) -> dict:
    """Load `name` like CTranslate2 would; if that fails, preload it from the nvidia pip wheels."""
    try:
        lib = _load(name)
        _loaded.append(lib)
        return {"name": name, "what": describe(name), "ok": True, "path": _module_path(lib, name)}
    except OSError as exc:
        error = str(exc)
    for d in dirs:
        path = d / name
        if not path.exists():
            continue
        try:
            if not WINDOWS:  # libcublas needs libcublasLt from the same wheel
                for dep in sorted(d.glob("libcublasLt.so*")):
                    _loaded.append(_load(str(dep)))
            _loaded.append(_load(str(path)))
            return {"name": name, "what": describe(name), "ok": True, "path": str(path)}
        except OSError as exc:
            error = str(exc)
    return {"name": name, "what": describe(name), "ok": False, "path": "", "error": error}


def nvidia_smi_path() -> str | None:
    found = shutil.which("nvidia-smi")
    if found or not WINDOWS:
        return found
    for cand in (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
                 Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVSMI" /
                 "nvidia-smi.exe"):
        if cand.exists():
            return str(cand)
    return None


def gpu_info() -> list[dict]:
    """NVIDIA GPUs as reported by the driver (nvidia-smi), independent of CUDA libraries."""
    exe = nvidia_smi_path()
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--query-gpu=index,name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            try:
                gpus.append({"index": int(parts[0]), "name": parts[1], "vram_mb": int(float(parts[2])),
                             "driver": parts[3]})
            except ValueError:
                continue
    return gpus


def _toolkit_version() -> str:
    m = re.search(r"v?(\d+\.\d+)\W*$", os.environ.get("CUDA_PATH", ""))
    return m.group(1) if m else ""


def probe(refresh: bool = False) -> dict:
    """Everything needed to decide GPU vs CPU transcription. Cached; `refresh` re-checks the libraries."""
    global _status
    with _lock:
        if _status is not None and not refresh:
            return _status
        dirs = prepare()
        st: dict = {"devices": 0, "gpus": _status["gpus"] if _status else gpu_info(), "compute_types": [],
                    "libraries": [], "libs_ok": None, "ctranslate2": "", "toolkit": _toolkit_version(),
                    "pip_dirs": [str(d) for d in dirs], "problem": "", "fix": ""}
        try:
            import ctranslate2

            st["ctranslate2"] = ctranslate2.__version__
            st["devices"] = int(ctranslate2.get_cuda_device_count())
        except Exception as exc:  # noqa: BLE001
            st["problem"] = f"CTranslate2 (used by faster-whisper) could not be loaded: {exc}"
            _status = st
            return st
        name = st["gpus"][0]["name"] if st["gpus"] else "An NVIDIA GPU"
        if st["devices"] > 0:
            try:
                st["compute_types"] = sorted(ctranslate2.get_supported_compute_types("cuda"))
            except Exception:  # noqa: BLE001
                pass
            required = required_libraries()
            st["libraries"] = [check_library(lib, dirs) for lib in required]
            st["libs_ok"] = all(lib["ok"] for lib in st["libraries"]) if required else None
            missing = [lib for lib in st["libraries"] if not lib["ok"]]
            if missing:
                libs = ", ".join(f"{lib['what']} ({lib['name']})" for lib in missing)
                st["problem"] = f"{name} was found, but CTranslate2 {st['ctranslate2']} cannot load {libs}."
                want = re.search(r"CUDA (\d+)", missing[0]["what"])
                if st["toolkit"] and want and not st["toolkit"].startswith(want.group(1) + "."):
                    st["problem"] += (f" The installed CUDA Toolkit is {st['toolkit']}; CTranslate2 needs the CUDA "
                                      f"{want.group(1)} libraries, which requirements-gpu.txt provides alongside it.")
                st["fix"] = GPU_FIX
        elif st["gpus"]:
            st["problem"] = (f"{name} was found by the NVIDIA driver ({st['gpus'][0]['driver']}), but CUDA is not "
                             f"usable by CTranslate2 {st['ctranslate2']}. The driver is probably too old.")
            st["fix"] = DRIVER_FIX
        _status = st
        return st


_cpu_types: list[str] | None = None


def cpu_compute_types() -> list[str]:
    global _cpu_types
    if _cpu_types is None:
        try:
            import ctranslate2

            _cpu_types = sorted(ctranslate2.get_supported_compute_types("cpu"))
        except Exception:  # noqa: BLE001
            _cpu_types = []
    return _cpu_types


class GpuMonitor:
    """Samples GPU utilization and memory with `nvidia-smi --loop-ms` (used by `gpu-check`)."""

    def __init__(self, index: int = 0, interval_ms: int = 250):
        self.index, self.interval_ms = index, interval_ms
        self.samples: list[tuple[float, int, int]] = []  # (time, util %, memory MB)
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        exe = nvidia_smi_path()
        if not exe:
            return False
        try:
            self._proc = subprocess.Popen(
                [exe, f"--id={self.index}", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits",
                 f"--loop-ms={self.interval_ms}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=NO_WINDOW)
        except OSError:
            return False
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        return True

    def _read(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            parts = [p.strip() for p in line.split(",")]
            try:
                self.samples.append((time.time(), int(float(parts[0])), int(float(parts[1]))))
            except (ValueError, IndexError):
                continue

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread:
            self._thread.join(timeout=2)

    def window(self, t0: float, t1: float) -> list[tuple[float, int, int]]:
        return [s for s in self.samples if t0 <= s[0] <= t1]

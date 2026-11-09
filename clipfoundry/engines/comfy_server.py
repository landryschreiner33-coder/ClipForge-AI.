"""ClipForge's own ComfyUI: set up from inside the app and run on this computer only, like the built-in model.

ComfyUI (github.com/comfyanonymous/ComfyUI) is GPL-3.0, so it stays a separate program: ClipForge downloads its
official source release, gives it a private Python of its own and talks to it over HTTP on 127.0.0.1. Nothing of
ComfyUI is imported into ClipForge.

Setting it up (one background job, Settings shows the progress; every download is pinned in catalog.py):

1. uv, the Python package installer from Astral (MIT or Apache-2.0), from its pinned wheel on PyPI;
2. a private Python (python-build-standalone, installed by uv, which checks each download against its own hashes);
3. PyTorch for this computer: Apple silicon (Metal), an NVIDIA graphics card (CUDA), or the processor alone;
4. ComfyUI's source at a pinned release, checked against its SHA-256, and ComfyUI's own requirements, with the
   versions ClipForge was tested with (catalog.CONSTRAINTS).

Everything lives in `<data>/tools/comfy/`; the models live in `<data>/models/comfy/` (shared with "the ComfyUI app"
only through the setting that points ClipForge at another ComfyUI). Running: a free port on 127.0.0.1, its own
output/input/temp/user folders under `<data>/engines/comfy/`, no browser, no previews; it starts when a picture or a
video is asked for, stays warm for the next scenes and stops after the idle minutes in Settings. On Windows it runs in
a job object that closes with ClipForge; on Linux it dies with ClipForge; a server left over from a run that was
killed is stopped at the next start (its process id is recorded).
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import httpx

from .. import config
from . import EngineError, catalog, files
from .comfy import Comfy

log = logging.getLogger(__name__)

START_TIMEOUT_S = 240.0
IDLE_POLL_S = 15.0
DEFAULT_IDLE_MIN = 10.0
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# ------------------------------------------------------------------ this computer
def platform_key() -> str:
    """mac-arm64, windows-x64 or linux-x64 (the computers ClipForge can set ComfyUI up on); "" otherwise."""
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "darwin":
        return "mac-arm64" if arm else ""
    if sys.platform == "win32":
        return "" if arm else "windows-x64"
    if sys.platform.startswith("linux"):
        return "" if arm else "linux-x64"
    return ""


def nvidia() -> dict:
    """The first NVIDIA graphics card and its driver, as the driver reports it ({} when there is none)."""
    if sys.platform == "darwin":
        return {}
    try:
        from ..pipeline import cuda

        gpus = cuda.gpu_info()
    except Exception:  # noqa: BLE001 - only a hint
        return {}
    return dict(gpus[0]) if gpus else {}


def _driver_major(gpu: dict) -> float:
    try:
        return float(".".join(str(gpu.get("driver") or "0").split(".")[:2]))
    except ValueError:
        return 0.0


def torch_flavor() -> str:
    """Which PyTorch this computer gets: "mps" (Mac with Apple silicon), "cuda" (an NVIDIA card with a recent
    enough driver) or "cpu"."""
    key = platform_key()
    if key == "mac-arm64":
        return "mps"
    gpu = nvidia()
    if gpu and _driver_major(gpu) >= catalog.TORCH["cuda"]["min_driver"]:
        return "cuda"
    return "cpu"


# ------------------------------------------------------------------ files on disk
def root() -> Path:
    return config.data_dir() / "tools" / "comfy"


def uv_dir() -> Path:
    return root() / f"uv-{catalog.UV_VERSION}"


def app_dir() -> Path:
    return root() / f"app-{catalog.COMFYUI['version']}"


def env_dir(flavor: str | None = None) -> Path:
    return root() / f"env-{flavor or torch_flavor()}"


def work_dir() -> Path:
    d = config.data_dir() / "engines" / "comfy"
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_root() -> Path:
    return config.models_dir() / "comfy"


def uv_exe() -> Path:
    return uv_dir() / ("uv.exe" if sys.platform == "win32" else "uv")


def env_python(flavor: str | None = None) -> Path:
    env = env_dir(flavor)
    return env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def main_py() -> Path:
    return app_dir() / catalog.COMFYUI["inner"] / "main.py"


def _env_marker(flavor: str) -> dict | None:
    return files.read_marker(env_dir(flavor))


def installed() -> bool:
    """ClipForge's own ComfyUI is set up for this computer: the source and an environment that were checked."""
    flavor = torch_flavor()
    m = _env_marker(flavor)
    app = files.read_marker(app_dir())
    return bool(platform_key() and m and app and m.get("comfyui") == catalog.COMFYUI["version"]
                and m.get("torch") == catalog.TORCH[flavor]["packages"] and m.get("constraints") == catalog.CONSTRAINTS_ID
                and app.get("sha256") == catalog.COMFYUI["sha256"] and env_python(flavor).is_file()
                and main_py().is_file())


def download_bytes() -> int:
    """About how much setting it up downloads (Python, PyTorch for this computer, ComfyUI and its packages)."""
    if installed():
        return 0
    return catalog.TORCH[torch_flavor()]["bytes"] + catalog.COMFYUI["size"] + catalog.SETUP_EXTRA_BYTES


def disk_bytes() -> int:
    """About how much room it takes once set up (unpacked packages are bigger than their downloads)."""
    return catalog.TORCH[torch_flavor()]["disk"] + catalog.SETUP_EXTRA_DISK


# ------------------------------------------------------------------ setting it up
def _uv_env() -> dict:
    """uv's settings for the set-up: everything in ClipForge's folder, nothing from the person's own uv or pip
    settings, and the Python it installs is not put on the PATH (~/.local/bin) or into the Windows registry."""
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("UV_", "PIP_", "VIRTUAL_ENV", "CONDA", "PYTHONHOME", "PYTHONPATH"))}
    env.update(UV_CACHE_DIR=str(root() / "cache"), UV_PYTHON_INSTALL_DIR=str(root() / "python"),
               UV_PYTHON_PREFERENCE="only-managed", UV_NO_CONFIG="1", UV_LINK_MODE="copy",
               UV_NO_PROGRESS="1", UV_HTTP_TIMEOUT="120", PYTHONNOUSERSITE="1",
               UV_PYTHON_INSTALL_BIN="0", UV_PYTHON_INSTALL_REGISTRY="0")
    return env


def _run(cmd: list[str], what: str, cancelled, timeout_s: float = 3600.0) -> str:
    """Run one set-up command; its output goes to <data>/logs/comfy-setup.log. Stops when cancelled."""
    logs = config.data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "comfy-setup.log", "a", encoding="utf-8", errors="replace") as out:
        out.write(f"\n$ {' '.join(cmd)}\n")
        out.flush()
        kwargs: dict = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL,
                        "env": _uv_env(), "cwd": str(root()), "text": True, "encoding": "utf-8", "errors": "replace"}
        if sys.platform == "win32":
            kwargs["creationflags"] = NO_WINDOW
        try:
            proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 - pinned programs, fixed arguments
        except OSError as exc:
            raise EngineError(f"Could not {what}: {exc}") from exc
        tail: list[str] = []
        lines: list[str] = []

        def pump() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                out.write(line)
                tail.append(line.rstrip())
                del tail[:-20]
                lines.append(line)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout_s
        while proc.poll() is None:
            if cancelled() or time.monotonic() > deadline:
                proc.kill()
                proc.wait(timeout=10)
                reader.join(timeout=5)
                raise EngineError("Stopped." if cancelled() else f"Could not {what}: it took too long.")
            time.sleep(0.3)
        reader.join(timeout=10)
        if proc.returncode != 0:
            last = next((t for t in reversed(tail) if t.strip()), "")
            raise EngineError(f"Could not {what} (exit {proc.returncode}). {last[:240]} The full log is in "
                              "data/logs/comfy-setup.log.")
        return "".join(lines)


def _step_uv(report, cancelled) -> None:
    key = platform_key()
    pin = catalog.UV.get(key)
    if not pin:
        raise EngineError("ClipForge can set ComfyUI up on a Mac with Apple silicon or a 64-bit Windows or Linux PC.")
    if uv_exe().is_file() and (files.read_marker(uv_dir()) or {}).get("sha256") == pin.sha256:
        return
    files.need_space(root(), pin.size * 3, "the installer")
    wheel = root() / "downloads" / pin.name
    files.fetch(pin, wheel, lambda n: report("Downloading the installer (uv)", n, pin.size), cancelled,
                lambda n: report("Checking the installer (uv)", n, pin.size))
    tmp = root() / f".uv-{catalog.UV_VERSION}.tmp"
    files.remove_tree(tmp)
    tmp.mkdir(parents=True)
    name = "uv.exe" if sys.platform == "win32" else "uv"
    with zipfile.ZipFile(wheel) as z:  # a wheel is a zip: the program is <dist>.data/scripts/uv
        inner = [i for i in z.namelist() if i.endswith(f".data/scripts/{name}")]
        if not inner:
            raise EngineError("The installer download does not contain the uv program.")
        with z.open(inner[0]) as src, open(tmp / name, "wb") as dst:
            shutil.copyfileobj(src, dst, files.CHUNK)
    (tmp / name).chmod(0o755)
    (tmp / "NOTICE-uv.txt").write_text(catalog.UV_NOTICE, encoding="utf-8")
    files.write_marker(tmp, {"version": catalog.UV_VERSION, "sha256": pin.sha256, "source": pin.url})
    files.remove_tree(uv_dir())
    tmp.replace(uv_dir())
    wheel.unlink(missing_ok=True)


def _step_source(report, cancelled) -> None:
    spec = catalog.COMFYUI
    m = files.read_marker(app_dir())
    if m and m.get("sha256") == spec["sha256"] and main_py().is_file():
        return
    pin = files.Pinned(spec["file"], spec["url"], spec["size"], spec["sha256"])
    files.need_space(root(), pin.size * 4, "ComfyUI")
    archive = root() / "downloads" / pin.name
    files.fetch(pin, archive, lambda n: report("Downloading ComfyUI", n, pin.size), cancelled,
                lambda n: report("Checking ComfyUI", n, pin.size))
    report("Unpacking ComfyUI", 0, 0)
    tmp = root() / f".app-{spec['version']}.tmp"
    files.remove_tree(tmp)
    files.extract(archive, tmp)
    if not (tmp / spec["inner"] / "main.py").is_file():
        raise EngineError("The ComfyUI download does not contain ComfyUI.")
    (tmp / "NOTICE-ComfyUI.txt").write_text(catalog.COMFYUI_NOTICE, encoding="utf-8")
    files.write_marker(tmp, {"version": spec["version"], "sha256": spec["sha256"], "source": spec["url"]})
    files.remove_tree(app_dir())
    tmp.replace(app_dir())
    archive.unlink(missing_ok=True)


def _step_env(report, cancelled) -> None:
    flavor = torch_flavor()
    if installed():
        return
    torch = catalog.TORCH[flavor]
    files.need_space(root(), torch["disk"] + catalog.SETUP_EXTRA_DISK, "ComfyUI's Python packages")
    uv = str(uv_exe())
    env = env_dir(flavor)
    report("Getting a private Python for ComfyUI", 0, 0)
    # --no-bin / --no-registry: the Python stays in ClipForge's folder (uv would otherwise add python3.12 to
    # ~/.local/bin, ahead of the person's own, and register it in Windows)
    _run([uv, "python", "install", "--no-bin", "--no-registry", catalog.PYTHON_VERSION], "get a Python for ComfyUI",
         cancelled, 1800)
    if env.exists():
        files.remove_tree(env)
    _run([uv, "venv", str(env), "--python", catalog.PYTHON_VERSION, "--seed", "--exclude-newer", catalog.EXCLUDE_NEWER],
         "make ComfyUI's Python environment", cancelled, 600)
    py = str(env_python(flavor))
    constraints = root() / "constraints.txt"
    constraints.write_text(catalog.CONSTRAINTS, encoding="utf-8")
    report(f"Downloading PyTorch for {torch['label']} (about {torch['bytes'] / 1e9:.1f} GB)", 0, 0)
    # PyTorch alone (--no-deps): what it needs comes with ComfyUI's packages below, from PyPI as it was on the
    # checked day. PyTorch's own index (the builds for NVIDIA cards and for the processor) has no upload dates, so
    # the date cut-off can only apply to PyPI.
    cmd = [uv, "pip", "install", "--python", py, "--no-deps", *torch["packages"]]
    if torch.get("index"):
        cmd += ["--index-url", torch["index"]]
    else:
        cmd += ["--exclude-newer", catalog.EXCLUDE_NEWER]
    _run(cmd, "install PyTorch", cancelled, 5400)
    report("Installing ComfyUI's packages and what PyTorch needs", 0, 0)
    _run([uv, "pip", "install", "--python", py, "-r", str(app_dir() / catalog.COMFYUI["inner"] / "requirements.txt"),
          "--constraint", str(constraints), "--exclude-newer", catalog.EXCLUDE_NEWER],
         "install ComfyUI's packages", cancelled, 3600)
    report("Checking PyTorch", 0, 0)
    out = _run([py, "-I", "-c", "import json, torch; print(json.dumps({'torch': torch.__version__, "
                "'cuda': bool(torch.cuda.is_available()), 'mps': bool(getattr(torch.backends, 'mps', None) and "
                "torch.backends.mps.is_available())}))"], "check PyTorch", cancelled, 300)
    try:
        probe = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        probe = {}
    problem = torch_problem(flavor, probe)
    if problem:
        raise EngineError(problem)
    files.write_marker(env, {"comfyui": catalog.COMFYUI["version"], "torch": torch["packages"], "flavor": flavor,
                             "constraints": catalog.CONSTRAINTS_ID, "python": catalog.PYTHON_VERSION, "probe": probe})


def torch_problem(flavor: str, probe: dict) -> str:
    """Why the PyTorch that was installed is not the one this computer needs ("" when it is)."""
    version = str(probe.get("torch") or "")
    if not version.startswith(catalog.TORCH_VERSION):
        return (f"ComfyUI's PyTorch is {version or 'missing'} instead of {catalog.TORCH_VERSION}. Remove ComfyUI in "
                "Settings and set it up again; the log is data/logs/comfy-setup.log.")
    if flavor == "cuda" and not probe.get("cuda"):
        return ("PyTorch cannot use the NVIDIA graphics card. Update the NVIDIA driver (version "
                f"{catalog.TORCH['cuda']['min_driver']:.0f} or newer) and set ComfyUI up again.")
    if flavor == "cuda" and "+cu" not in version:
        return "ComfyUI got the PyTorch without graphics-card support. Remove ComfyUI and set it up again."
    if flavor == "mps" and not probe.get("mps"):
        return "PyTorch cannot use this Mac's graphics (Metal). macOS 14 or newer is needed."
    return ""


def setup_steps() -> list:
    """The steps that set ClipForge's own ComfyUI up (nothing is done twice)."""
    from ..cloud import settings as cloud_settings

    if cloud_settings.enabled():
        raise EngineError("The online studio's server is set up by its operator; it does not fetch programs.")
    if not platform_key():
        raise EngineError("ClipForge can set ComfyUI up on a Mac with Apple silicon or a 64-bit Windows or Linux PC.")
    if mac_too_old():
        raise EngineError("Making pictures and video on a Mac needs macOS 14 (Sonoma) or newer; this Mac has macOS "
                          f"{platform.mac_ver()[0]}. Update macOS in System Settings, General, Software Update.")
    return [_step_uv, _step_source, _step_env]


def mac_too_old() -> bool:
    """PyTorch for Apple silicon needs macOS 14 or newer."""
    if sys.platform != "darwin":
        return False
    try:
        return int((platform.mac_ver()[0] or "0").split(".")[0]) < 14
    except ValueError:
        return False


def remove() -> None:
    if server._shared():  # noqa: SLF001 - its files are in use (and Windows would refuse to delete them part way)
        raise EngineError("ComfyUI is in use by another copy of ClipForge that is open. Close it first, then remove "
                          "ComfyUI.")
    server.stop()
    for p in (root() / "cache", root() / "downloads"):
        files.remove_tree(p)
    for p in root().glob("env-*"):
        files.remove_tree(p)
    for p in root().glob("app-*"):
        files.remove_tree(p)


# ------------------------------------------------------------------ running it
def extra_paths_yaml() -> Path:
    """ComfyUI's list of extra model folders: ClipForge's models folder (so models survive ComfyUI updates)."""
    base = models_root()
    for sub in catalog.MODEL_FOLDERS:
        (base / sub).mkdir(parents=True, exist_ok=True)
    lines = ["clipforge:", f"  base_path: {json.dumps(str(base))}"]
    lines += [f"  {sub}: {sub}" for sub in catalog.MODEL_FOLDERS]
    path = root() / "extra_model_paths.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_command(port: int, flavor: str) -> list[str]:
    w = work_dir()
    for sub in ("output", "input", "temp", "user"):  # ComfyUI stops at once (exit 2) when --user-directory is missing
        (w / sub).mkdir(parents=True, exist_ok=True)
    cmd = [str(env_python(flavor)), "-s", str(main_py()), "--listen", "127.0.0.1", "--port", str(port),
           "--disable-auto-launch", "--extra-model-paths-config", str(extra_paths_yaml()),
           "--output-directory", str(w / "output"), "--input-directory", str(w / "input"),
           "--temp-directory", str(w / "temp"), "--user-directory", str(w / "user"),
           "--preview-method", "none", "--disable-metadata", *catalog.COMFYUI.get("flags", ())]
    if flavor == "cpu":
        cmd.append("--cpu")
    return cmd


class Server:
    """One ComfyUI process at a time, started on demand and stopped when idle."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.last_used = 0.0
        self.started_at = 0.0
        self.idle_s = DEFAULT_IDLE_MIN * 60
        self._job = None
        self._watch: threading.Thread | None = None
        self._exit_hook = False

    @property
    def pid_file(self) -> Path:
        return root() / "comfy.pid"

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _record(self) -> dict | None:
        try:
            data = json.loads(self.pid_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) and int(data.get("pid") or 0) > 0 else None
        except (OSError, ValueError, TypeError):
            return None

    def _shared(self) -> str | None:
        """A ComfyUI another ClipForge process started and still uses: share it."""
        from .. import builtin_ai

        rec = self._record()
        if not rec or int(rec.get("owner") or 0) == os.getpid() or not builtin_ai._alive(int(rec.get("owner") or 0)):  # noqa: SLF001
            return None
        if not _is_ours(int(rec["pid"])):
            return None
        base = f"http://127.0.0.1:{int(rec['port'])}"
        return base if Comfy(base, timeout=3).alive() else None

    def _stop_leftover(self) -> None:
        from .. import builtin_ai

        rec = self._record()
        if not rec:
            return
        pid, owner = int(rec["pid"]), int(rec.get("owner") or 0)
        if owner != os.getpid() and builtin_ai._alive(owner):  # noqa: SLF001 - a live ClipForge process owns it
            return
        self.pid_file.unlink(missing_ok=True)
        if not _is_ours(pid):
            return
        _kill(pid)
        log.info("stopped a ComfyUI left over from an earlier run (pid %s)", pid)

    def ensure(self, settings: dict, progress=None) -> str:
        """The address of a running ClipForge ComfyUI; starts it when needed."""
        from .. import builtin_ai

        if not installed():
            raise EngineError("ComfyUI is not set up yet. Set it up in Settings, Pictures, video, voice.")
        self.idle_s = max(60.0, float(settings.get("engines_idle_minutes") or DEFAULT_IDLE_MIN) * 60)
        with self._lock:
            if self.running():
                self.last_used = time.time()
                return f"http://127.0.0.1:{self.port}"
            shared = self._shared()
            if shared:
                return shared
            self._stop_leftover()
            flavor = torch_flavor()
            port = builtin_ai._free_port()  # noqa: SLF001
            cmd = build_command(port, flavor)
            logs = config.data_dir() / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            out = open(logs / "comfyui.log", "ab")  # noqa: SIM115 - handed to the process, closed below
            env = {k: v for k, v in os.environ.items()
                   if not k.upper().startswith(("HF_", "HUGGING", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"))}
            env.update(PYTHONNOUSERSITE="1", HF_HUB_OFFLINE="1", DO_NOT_TRACK="1", PYTHONUTF8="1")
            if flavor == "mps":
                env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"  # an operation Metal lacks runs on the processor
            kwargs: dict = {"stdout": out, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL,
                            "cwd": str(main_py().parent), "env": env}
            if sys.platform == "win32":
                kwargs["creationflags"] = NO_WINDOW
                self._job = self._job or builtin_ai._win_job()  # noqa: SLF001
            elif sys.platform.startswith("linux"):
                kwargs["preexec_fn"] = builtin_ai._linux_pdeathsig  # noqa: SLF001
            log.info("starting ClipForge's ComfyUI (%s) on port %s", flavor, port)
            if progress:
                progress(0.01, "Starting ComfyUI")
            try:
                proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 - the checked environment, fixed arguments
            except OSError as exc:
                raise EngineError(f"ComfyUI could not start: {exc}") from exc
            finally:
                out.close()
            builtin_ai._assign(self._job, proc)  # noqa: SLF001
            if not self._exit_hook:
                import atexit

                atexit.register(shutdown)
                self._exit_hook = True
            self.proc, self.port = proc, port
            self.started_at = self.last_used = time.time()
            try:
                fd = os.open(self.pid_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump({"pid": proc.pid, "owner": os.getpid(), "port": port, "main": str(main_py())}, fh)
            except OSError:
                pass
            try:
                self._wait_ready()
            except EngineError:
                self.stop()
                raise
            if self._watch is None or not self._watch.is_alive():
                self._watch = threading.Thread(target=self._idle_loop, daemon=True, name="comfy-idle")
                self._watch.start()
            return f"http://127.0.0.1:{self.port}"

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if not self.running():
                raise EngineError("ComfyUI stopped while starting. Its log is data/logs/comfyui.log.")
            try:
                r = httpx.get(f"http://127.0.0.1:{self.port}/system_stats", timeout=2, trust_env=False)
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise EngineError("ComfyUI took too long to start. Its log is data/logs/comfyui.log.")

    def touch(self) -> None:
        self.last_used = time.time()

    def _idle_loop(self) -> None:
        while True:
            time.sleep(IDLE_POLL_S)
            with self._lock:
                if not self.running():
                    return
                if time.time() - self.last_used > self.idle_s and not busy.is_set():
                    log.info("stopping the idle ComfyUI")
                    self.stop()
                    return

    def stop(self) -> None:
        with self._lock:
            proc, self.proc = self.proc, None
            self.port = 0
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            rec = self._record() if proc is not None else None
            if rec and proc is not None and int(rec.get("pid") or 0) == proc.pid:
                self.pid_file.unlink(missing_ok=True)

    def release_files(self) -> None:
        """Model files are about to be deleted, and Windows refuses to delete a file a program holds open: this
        process's ComfyUI is stopped (it starts again when needed); one that another ClipForge process started and
        shares is not this process's to stop, so it is asked to unload its models instead."""
        self.stop()
        other = self._shared()
        if other:
            Comfy(other, timeout=30).free()

    def view(self) -> dict:
        return {"running": self.running(), "since": self.started_at if self.running() else 0,
                "idle_minutes": round(self.idle_s / 60, 1)}


busy = threading.Event()  # set while a picture or a video is being made, so the idle stop and Remove wait
_jobs_cond = threading.Condition()
_jobs = 0      # pictures and clips being made (job)
_removals = 0  # removals under way (removing)


@contextlib.contextmanager
def job():
    """One picture or clip, from starting ComfyUI to saving the file: meanwhile the idle stop leaves ComfyUI running
    and Remove is refused (it stops or empties the ComfyUI the job uses); a Remove under way is waited for first."""
    global _jobs
    with _jobs_cond:
        while _removals:
            _jobs_cond.wait()
        _jobs += 1
        busy.set()
    try:
        yield
    finally:
        with _jobs_cond:
            _jobs -= 1
            if not _jobs:
                busy.clear()
            _jobs_cond.notify_all()
        server.touch()


@contextlib.contextmanager
def removing():
    """Removing ComfyUI or model files: refused while a picture or clip is being made; new ones wait until it ends."""
    global _removals
    with _jobs_cond:
        if _jobs or busy.is_set():
            raise EngineError("A picture or clip is being made right now. Wait for it to finish, or stop it, first.")
        _removals += 1
    try:
        yield
    finally:
        with _jobs_cond:
            _removals -= 1
            _jobs_cond.notify_all()


def _cmdline(pid: int) -> str:
    try:
        if sys.platform.startswith("linux"):
            return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        if sys.platform == "darwin":
            return subprocess.run(["/bin/ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True,
                                  timeout=5).stdout
        if sys.platform == "win32":
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                                 capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout
            return out
    except (OSError, subprocess.SubprocessError):
        return ""
    return ""


def _is_ours(pid: int) -> bool:
    """Only a process running ClipForge's own ComfyUI (its main.py in ClipForge's tools folder) is ever stopped."""
    line = _cmdline(pid)
    return bool(line) and str(root()) in line and "main.py" in line


def _kill(pid: int) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10,
                           creationflags=NO_WINDOW)
        else:
            import signal

            os.kill(pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass


server = Server()


def shutdown() -> None:
    try:
        server.stop()
    except Exception:  # noqa: BLE001 - shutting down
        pass

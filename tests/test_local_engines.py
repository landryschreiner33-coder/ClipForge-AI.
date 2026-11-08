"""The local makers (clipfoundry/engines): the pins, pinned downloads, model files, ClipForge's own ComfyUI, the
graphs, the picture and video makers against a stand-in ComfyUI, the built-in voice with a stand-in model, and the
Settings routes. The real ComfyUI, the real models and the real voice are checked on Mac, Windows and Linux machines
by scripts/local_engines_check.py (.github/workflows/local-engines-check.yml)."""
from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import re
import struct
import tarfile
import threading
import time
import wave
import zipfile
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from clipfoundry import config
from clipfoundry.engines import EngineError, catalog, comfy, comfy_server, files, graphs, makers, models, tasks, voice


# ------------------------------------------------------------------ helpers
def png_bytes(width: int, height: int, rgb: tuple[int, int, int] = (40, 90, 200)) -> bytes:
    row = b"\x00" + bytes(rgb) * width
    raw = zlib.compress(row * height)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


MP4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 4000


class FileServer:
    """Serves byte strings by path, with Range support (or without, when `ranges` is False)."""

    def __init__(self, blobs: dict[str, bytes], ranges: bool = True) -> None:
        self.blobs, self.ranges, self.hits = blobs, ranges, []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                owner.hits.append((path, self.headers.get("Range")))
                data = owner.blobs.get(path)
                if data is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                start = 0
                rng = self.headers.get("Range")
                if rng and owner.ranges:
                    start = int(re.match(r"bytes=(\d+)-", rng).group(1))
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                else:
                    self.send_response(200)
                body = data[start:]
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def file_server():
    servers = []

    def start(blobs, ranges=True):
        s = FileServer(blobs, ranges)
        servers.append(s)
        return s

    yield start
    for s in servers:
        s.stop()


def pin_for(server: FileServer, name: str, data: bytes) -> files.Pinned:
    server.blobs[f"/{name}"] = data
    return files.Pinned(name, f"{server.url}/{name}", len(data), hashlib.sha256(data).hexdigest())


def run_steps(steps) -> dict:
    return tasks.start("test", steps, wait=True)


# ------------------------------------------------------------------ the stand-in ComfyUI
LOADERS = {"UNETLoader": ("unet_name", "diffusion_models"), "CLIPLoader": ("clip_name", "text_encoders"),
           "VAELoader": ("vae_name", "vae")}


class FakeComfy:
    """Enough of ComfyUI's HTTP API for ClipForge's client: it checks graphs the way ComfyUI does (node types it
    knows, model file names it has, links to nodes that exist), "runs" them and serves what they saved."""

    NODES = {"EmptyImage", "SaveImage", "CreateVideo", "SaveVideo", "UNETLoader", "CLIPLoader", "VAELoader",
             "ModelSamplingAuraFlow", "CLIPTextEncode", "ConditioningZeroOut", "EmptySD3LatentImage", "KSampler",
             "VAEDecode", "EmptyFlux2LatentImage", "Flux2Scheduler", "KSamplerSelect", "RandomNoise", "CFGGuider",
             "SamplerCustomAdvanced", "ModelSamplingSD3", "Wan22ImageToVideoLatent", "LoadImage"}

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.nodes = set(self.NODES)
        self.models: dict[str, list[str]] = {"diffusion_models": [], "text_encoders": [], "vae": []}
        self.prompts: list[dict] = []
        self.uploads: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.history: dict[str, dict] = {}
        self.outputs: dict[tuple[str, str], bytes] = {}
        self.fail_with = ""          # an execution error message for the next graph
        self.polls_before_done = 1   # how many /history polls see nothing yet
        self._polls: dict[str, int] = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:
                pass

            def _send(self, code: int, body=None, raw: bytes | None = None, ctype="application/json") -> None:
                data = raw if raw is not None else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self) -> bytes:
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def do_GET(self) -> None:  # noqa: N802
                u = urlsplit(self.path)
                owner.calls.append(("GET", u.path))
                if u.path == "/system_stats":
                    return self._send(200, {"system": {"comfyui_version": "0.43.0", "python_version": "3.12"},
                                            "devices": [{"name": "cpu", "type": "cpu"}]})
                if u.path.startswith("/object_info/"):
                    cls = u.path.split("/", 2)[2]
                    return self._send(200, {cls: {"input": {}}} if cls in owner.nodes else {})
                if u.path.startswith("/models/"):
                    folder = u.path.split("/", 2)[2]
                    return self._send(200, owner.models.get(folder, [])) if folder in owner.models else self._send(404, {})
                if u.path == "/internal/folder_paths":
                    return self._send(200, {k: [str(owner.tmp / "app-models" / k)] for k in owner.models})
                if u.path.startswith("/history/"):
                    pid = u.path.split("/", 2)[2]
                    seen = owner._polls.get(pid, 0)
                    owner._polls[pid] = seen + 1
                    if seen < owner.polls_before_done or pid not in owner.history:
                        return self._send(200, {})
                    return self._send(200, {pid: owner.history[pid]})
                if u.path == "/view":
                    q = parse_qs(u.query)
                    key = (q.get("subfolder", [""])[0], q.get("filename", [""])[0])
                    data = owner.outputs.get(key)
                    return self._send(200, raw=data, ctype="application/octet-stream") if data else self._send(404, {})
                return self._send(404, {})

            def do_POST(self) -> None:  # noqa: N802
                u = urlsplit(self.path)
                body = self._body()
                owner.calls.append(("POST", u.path))
                if u.path == "/prompt":
                    return owner._prompt(self, json.loads(body))
                if u.path == "/upload/image":
                    m = re.search(rb'filename="([^"]+)"', body)
                    name = m.group(1).decode() if m else "upload.png"
                    owner.uploads.append(name)
                    return self._send(200, {"name": name, "subfolder": "", "type": "input"})
                if u.path in ("/interrupt", "/queue", "/free"):
                    return self._send(200, {})
                return self._send(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def have(self, model: catalog.Model) -> None:
        for f in model.files:
            if f.name not in self.models.setdefault(f.folder, []):
                self.models[f.folder].append(f.name)

    def _prompt(self, h, body: dict) -> None:
        graph = body["prompt"]
        errors = {}
        for nid, node in graph.items():
            cls = node["class_type"]
            if cls not in self.nodes:
                return h._send(400, {"error": {"message": f"Cannot execute because node {cls} does not exist."},
                                     "node_errors": {}})
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] not in graph:
                    errors[nid] = {"class_type": cls, "errors": [{"message": "Required input is missing"}]}
            if cls in LOADERS:
                key, folder = LOADERS[cls]
                if node["inputs"][key] not in self.models.get(folder, []):
                    errors[nid] = {"class_type": cls, "errors": [{"message": "Value not in list",
                                                                  "details": f"{key}: '{node['inputs'][key]}'"}]}
        if errors:
            return h._send(400, {"error": {"message": "Prompt outputs failed validation"}, "node_errors": errors})
        pid = f"p{len(self.prompts) + 1}"
        self.prompts.append(graph)
        if self.fail_with:
            self.history[pid] = {"outputs": {}, "status": {"status_str": "error", "completed": False, "messages": [
                ["execution_error", {"node_id": "8", "exception_message": self.fail_with,
                                     "exception_type": "RuntimeError"}]]}}
            self.fail_with = ""
        else:
            self.history[pid] = {"outputs": self._outputs(graph), "status": {"status_str": "success",
                                                                             "completed": True, "messages": []}}
        h._send(200, {"prompt_id": pid, "number": len(self.prompts), "node_errors": {}})

    def _outputs(self, graph: dict) -> dict:
        out = {}
        size = next(((n["inputs"]["width"], n["inputs"]["height"]) for n in graph.values()
                     if "width" in n["inputs"] and "height" in n["inputs"]), (64, 64))
        for nid, node in graph.items():
            prefix = node["inputs"].get("filename_prefix", "")
            sub, _, stem = prefix.rpartition("/")
            if node["class_type"] == "SaveImage":
                name = f"{stem}_{len(self.prompts):05d}_.png"
                self.outputs[(sub, name)] = png_bytes(*size)
                out[nid] = {"images": [{"filename": name, "subfolder": sub, "type": "output"}]}
            elif node["class_type"] == "SaveVideo":
                name = f"{stem}_{len(self.prompts):05d}_.mp4"
                self.outputs[(sub, name)] = MP4
                out[nid] = {"images": [{"filename": name, "subfolder": sub, "type": "output"}], "animated": [True]}
        return out

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_comfy(tmp_path, monkeypatch):
    c = FakeComfy(tmp_path)
    monkeypatch.setattr(comfy, "_socket", lambda base, cid: None)  # the stand-in has no websocket: poll
    monkeypatch.setattr(comfy, "POLL_S", 0.05)
    yield c
    c.stop()


@pytest.fixture
def app_settings(monkeypatch, fake_comfy):
    """ClipForge set to use "the ComfyUI app" at the stand-in's address."""
    values = dict(config.DEFAULT_SETTINGS, engines_comfyui="app", engines_comfyui_url=fake_comfy.url)
    from clipfoundry import engines

    monkeypatch.setattr(makers, "_settings", lambda: values)
    monkeypatch.setattr(engines, "_settings", lambda: values)
    makers.forget_found()
    return values


def mac(memory_gb: int) -> dict:
    return {"flavor": "mps", "memory_mb": memory_gb * 1024, "vram_mb": 0, "gpu": {}}


# ------------------------------------------------------------------ the pins
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def test_every_download_is_pinned_to_a_size_and_checksum():
    for key, pin in catalog.UV.items():
        assert pin.url.startswith("https://files.pythonhosted.org/") and pin.name in pin.url
        assert pin.size > 1_000_000 and HEX64.match(pin.sha256), key
        assert catalog.UV_VERSION in pin.name
    spec = catalog.COMFYUI
    assert spec["url"] == f"https://github.com/comfyanonymous/ComfyUI/archive/refs/tags/v{spec['version']}.tar.gz"
    assert spec["inner"] == f"ComfyUI-{spec['version']}" and spec["file"] == f"ComfyUI-{spec['version']}.tar.gz"
    assert spec["size"] > 1_000_000 and HEX64.match(spec["sha256"]), "fill from scripts/local_engines_check.py --pins"
    for m in catalog.MODELS:
        assert m.files and m.licence and m.licence_url.startswith("https://") and m.about
        for f in m.files:
            assert HEX40.match(f.revision), f"{m.id}: {f.path} must be pinned to a commit"
            assert f.size > 0 and HEX64.match(f.sha256), f"{m.id}: {f.path} needs its SHA-256"
            assert f.path.endswith(f.name)
            if m.role != "voice":
                assert f.folder in catalog.MODEL_FOLDERS and f.name.endswith(".safetensors")
    for flavor in catalog.TORCH.values():
        assert all("==" in p for p in flavor["packages"])


def test_models_are_free_for_commercial_use_and_run_on_a_mac():
    allowed = {"Apache-2.0", "MIT", "BSD-3-Clause"}
    for m in catalog.MODELS:
        if m.role == "voice":
            assert m.licence.startswith("OpenRAIL-M")
            continue
        assert m.licence in allowed, m.id
        for f in m.files:  # the number formats Metal cannot run are never chosen
            assert not re.search(r"fp8|int8|nvfp4|fp4|gguf", f.name, re.I), f.name
        assert m.memory_gb >= 16 and m.vram_gb >= 8 and m.graph
    assert {m.role for m in catalog.MODELS} == {"image", "video", "voice"}
    assert "machine-generated" in catalog.SUPERTONIC_RULE


def test_the_picture_models_share_one_text_encoder():
    a = next(f for f in catalog.Z_IMAGE_TURBO.files if f.folder == "text_encoders")
    b = next(f for f in catalog.FLUX2_KLEIN_4B.files if f.folder == "text_encoders")
    assert (a.folder, a.name, a.size, a.sha256) == (b.folder, b.name, b.size, b.sha256)


def test_comfyui_runs_offline_without_add_on_nodes(monkeypatch):
    monkeypatch.setattr(comfy_server, "env_python", lambda flavor=None: Path("/py"))
    cmd = comfy_server.build_command(8123, "mps")
    assert cmd[cmd.index("--listen") + 1] == "127.0.0.1" and cmd[cmd.index("--port") + 1] == "8123"
    for flag in ("--offline", "--disable-all-custom-nodes", "--disable-auto-launch", "--disable-metadata"):
        assert flag in cmd
    assert "--cpu" not in cmd and "--cpu" in comfy_server.build_command(8123, "cpu")
    yaml = Path(cmd[cmd.index("--extra-model-paths-config") + 1]).read_text()
    assert json.dumps(str(comfy_server.models_root())) in yaml
    for sub in catalog.MODEL_FOLDERS:
        assert f"  {sub}: {sub}" in yaml and (comfy_server.models_root() / sub).is_dir()
    for key in ("--output-directory", "--input-directory", "--temp-directory", "--user-directory"):
        folder = Path(cmd[cmd.index(key) + 1])
        assert folder.parent == comfy_server.work_dir()
        assert folder.is_dir()  # ComfyUI refuses to start when --user-directory does not exist yet


# ------------------------------------------------------------------ ClipForge's own ComfyUI
def test_pytorch_for_each_computer(monkeypatch):
    monkeypatch.setattr(comfy_server, "platform_key", lambda: "mac-arm64")
    assert comfy_server.torch_flavor() == "mps"
    monkeypatch.setattr(comfy_server, "platform_key", lambda: "windows-x64")
    monkeypatch.setattr(comfy_server, "nvidia", lambda: {"name": "RTX", "vram_mb": 8192, "driver": "581.15"})
    assert comfy_server.torch_flavor() == "cuda"
    monkeypatch.setattr(comfy_server, "nvidia", lambda: {"name": "RTX", "vram_mb": 8192, "driver": "566.36"})
    assert comfy_server.torch_flavor() == "cpu"  # too old a driver for CUDA 13
    monkeypatch.setattr(comfy_server, "nvidia", lambda: {})
    assert comfy_server.torch_flavor() == "cpu"
    v = catalog.TORCH_VERSION
    assert comfy_server.torch_problem("cuda", {"torch": f"{v}+cu130", "cuda": True}) == ""
    assert "driver" in comfy_server.torch_problem("cuda", {"torch": f"{v}+cu130", "cuda": False})
    assert "graphics-card support" in comfy_server.torch_problem("cuda", {"torch": f"{v}+cpu", "cuda": True})
    assert "macOS 14" in comfy_server.torch_problem("mps", {"torch": v, "mps": False})
    assert comfy_server.torch_problem("mps", {"torch": v, "mps": True}) == ""
    assert "instead of" in comfy_server.torch_problem("cpu", {"torch": "2.9.0"})


def test_setting_comfyui_up_is_refused_where_it_cannot_work(monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_MODE", "cloud")
    with pytest.raises(EngineError, match="operator"):
        comfy_server.setup_steps()
    monkeypatch.delenv("CLIPFOUNDRY_MODE")
    monkeypatch.setattr(comfy_server, "platform_key", lambda: "")
    with pytest.raises(EngineError, match="Apple silicon"):
        comfy_server.setup_steps()
    monkeypatch.setattr(comfy_server, "platform_key", lambda: "mac-arm64")
    monkeypatch.setattr(comfy_server, "mac_too_old", lambda: True)
    with pytest.raises(EngineError, match="macOS 14"):
        comfy_server.setup_steps()
    monkeypatch.setattr(comfy_server, "mac_too_old", lambda: False)
    assert len(comfy_server.setup_steps()) == 3


def test_installed_only_with_every_checked_part(monkeypatch):
    monkeypatch.setattr(comfy_server, "platform_key", lambda: "linux-x64")
    monkeypatch.setattr(comfy_server, "nvidia", lambda: {})
    assert not comfy_server.installed()
    app = comfy_server.app_dir()
    comfy_server.main_py().parent.mkdir(parents=True)
    comfy_server.main_py().write_text("# ComfyUI")
    files.write_marker(app, {"version": catalog.COMFYUI["version"], "sha256": catalog.COMFYUI["sha256"]})
    env = comfy_server.env_dir("cpu")
    py = comfy_server.env_python("cpu")
    py.parent.mkdir(parents=True)
    py.write_text("")
    mark = {"comfyui": catalog.COMFYUI["version"], "torch": catalog.TORCH["cpu"]["packages"], "flavor": "cpu",
            "constraints": catalog.CONSTRAINTS_ID}
    files.write_marker(env, {**mark, "constraints": "an older set"})
    assert not comfy_server.installed()
    files.write_marker(env, mark)
    assert comfy_server.installed()
    assert comfy_server.download_bytes() == 0
    comfy_server.remove()
    assert not comfy_server.installed() and not app.exists() and not env.exists()


def test_only_clipforges_own_comfyui_is_ever_stopped(monkeypatch):
    mine = f"{comfy_server.env_python('cpu')} -s {comfy_server.main_py()} --port 1234"
    monkeypatch.setattr(comfy_server, "_cmdline", lambda pid: mine if pid == 1 else "python main.py --port 8188")
    assert comfy_server._is_ours(1)  # noqa: SLF001
    assert not comfy_server._is_ours(2)  # noqa: SLF001 - someone's own ComfyUI


def test_setup_installs_uv_from_its_wheel(file_server, monkeypatch):
    srv = file_server({})
    exe = "uv.exe" if comfy_server.sys.platform == "win32" else "uv"
    wheel = io.BytesIO()
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr(f"uv-{catalog.UV_VERSION}.data/scripts/{exe}", b"#!/bin/sh\necho uv\n")
        z.writestr("uv/__init__.py", "")
    pin = pin_for(srv, "uv.whl", wheel.getvalue())
    monkeypatch.setattr(comfy_server, "platform_key", lambda: "linux-x64")
    monkeypatch.setattr(catalog, "UV", {"linux-x64": pin})
    assert run_steps([comfy_server._step_uv])["state"] == "done"  # noqa: SLF001
    assert comfy_server.uv_exe().read_bytes().startswith(b"#!/bin/sh")
    assert (comfy_server.uv_dir() / "NOTICE-uv.txt").is_file()
    assert files.read_marker(comfy_server.uv_dir())["sha256"] == pin.sha256
    n = len(srv.hits)
    assert run_steps([comfy_server._step_uv])["state"] == "done"  # noqa: SLF001 - nothing is done twice
    assert len(srv.hits) == n


def test_setup_unpacks_the_pinned_comfyui_source(file_server, monkeypatch):
    srv = file_server({})
    inner = catalog.COMFYUI["inner"]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in ((f"{inner}/main.py", b"print('ComfyUI')\n"), (f"{inner}/requirements.txt", b"torch\n")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    pin = pin_for(srv, "ComfyUI.tar.gz", buf.getvalue())
    monkeypatch.setitem(catalog.COMFYUI, "url", pin.url)
    monkeypatch.setitem(catalog.COMFYUI, "size", pin.size)
    monkeypatch.setitem(catalog.COMFYUI, "sha256", pin.sha256)
    assert run_steps([comfy_server._step_source])["state"] == "done"  # noqa: SLF001
    assert comfy_server.main_py().read_text().startswith("print")
    assert "GPL" in (comfy_server.app_dir() / "NOTICE-ComfyUI.txt").read_text()
    monkeypatch.setitem(catalog.COMFYUI, "sha256", "0" * 64)  # a different pin: downloaded again, and refused
    view = run_steps([comfy_server._step_source])  # noqa: SLF001
    assert view["state"] == "failed" and "checksum" in view["error"]


# ------------------------------------------------------------------ pinned downloads
def test_a_download_resumes_and_is_checked(file_server, tmp_path):
    srv = file_server({})
    data = bytes(range(256)) * 5000
    pin = pin_for(srv, "blob.bin", data)
    dest = tmp_path / "blob.bin"
    dest.with_name("blob.bin.part").write_bytes(data[:300_000])  # an earlier, stopped download
    files.fetch(pin, dest)
    assert dest.read_bytes() == data and srv.hits[-1][1] == "bytes=300000-"
    assert not dest.with_name("blob.bin.part").exists()
    n = len(srv.hits)
    files.fetch(pin, dest)  # already there and right: only checked
    assert len(srv.hits) == n


def test_a_server_that_ignores_ranges_starts_over(file_server, tmp_path):
    srv = file_server({}, ranges=False)
    data = b"x" * 100_000 + b"y" * 100_000
    pin = pin_for(srv, "b.bin", data)
    dest = tmp_path / "b.bin"
    dest.with_name("b.bin.part").write_bytes(b"x" * 50_000)
    files.fetch(pin, dest)
    assert dest.read_bytes() == data


def test_a_wrong_or_oversized_download_is_deleted(file_server, tmp_path):
    srv = file_server({})
    good = pin_for(srv, "c.bin", b"right" * 1000)
    wrong = files.Pinned("c.bin", good.url, good.size, "0" * 64)
    with pytest.raises(EngineError, match="checksum"):
        files.fetch(wrong, tmp_path / "c.bin")
    assert not (tmp_path / "c.bin").exists() and not (tmp_path / "c.bin.part").exists()
    small = files.Pinned("c.bin", good.url, 100, good.sha256)
    with pytest.raises(EngineError, match="larger than expected"):
        files.fetch(small, tmp_path / "c2.bin")
    with pytest.raises(EngineError, match="HTTP 404"):
        files.fetch(files.Pinned("gone", f"{srv.url}/gone", 10, "0" * 64), tmp_path / "gone")


def test_a_stopped_download_keeps_what_it_has(file_server, tmp_path):
    srv = file_server({})
    data = b"z" * (5 * files.CHUNK)
    pin = pin_for(srv, "d.bin", data)
    seen = []

    def cancelled() -> bool:
        return len(seen) >= 2

    with pytest.raises(EngineError, match="resumes"):
        files.fetch(pin, tmp_path / "d.bin", progress=seen.append, cancelled=cancelled)
    assert 0 < (tmp_path / "d.bin.part").stat().st_size < len(data)


def test_no_download_starts_without_room(monkeypatch, tmp_path):
    monkeypatch.setattr(files.shutil, "disk_usage", lambda p: type("U", (), {"free": 3 << 30})())
    files.need_space(tmp_path, 512 << 20, "it")
    with pytest.raises(EngineError, match="Not enough free disk space for the model"):
        files.need_space(tmp_path, 2 << 30, "the model")


def test_archives_cannot_write_outside_their_folder(tmp_path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escape.txt", "no")
    with pytest.raises(EngineError, match="outside"):
        files.extract(z, tmp_path / "out1")
    assert not (tmp_path / "escape.txt").exists()
    t = tmp_path / "bad.tar.gz"
    with tarfile.open(t, "w:gz") as tf:
        link = tarfile.TarInfo("app/link")
        link.type, link.linkname = tarfile.SYMTYPE, "../../etc/passwd"
        tf.addfile(link)
    with pytest.raises(EngineError, match="link out"):
        files.extract(t, tmp_path / "out2")
    d = tmp_path / "dev.tar.gz"
    with tarfile.open(d, "w:gz") as tf:
        dev = tarfile.TarInfo("app/dev")
        dev.type = tarfile.CHRTYPE
        tf.addfile(dev)
    with pytest.raises(EngineError, match="special file"):
        files.extract(d, tmp_path / "out3")
    ok = tmp_path / "ok.tar.gz"
    with tarfile.open(ok, "w:gz") as tf:
        info = tarfile.TarInfo("app/sub/a.txt")
        info.size = 2
        tf.addfile(info, io.BytesIO(b"hi"))
    files.extract(ok, tmp_path / "out4")
    assert (tmp_path / "out4" / "app" / "sub" / "a.txt").read_bytes() == b"hi"


# ------------------------------------------------------------------ model files
def tiny_models(srv: FileServer, monkeypatch) -> tuple[catalog.Model, catalog.Model]:
    """Two small picture "models" served by `srv` that share a text encoder, like the real two."""
    def mf(folder, name, data):
        srv.blobs[f"/repo/resolve/{'a' * 40}/split_files/{folder}/{name}"] = data
        return catalog.ModelFile(folder, name, "repo", "a" * 40, f"split_files/{folder}/{name}", len(data),
                                 hashlib.sha256(data).hexdigest())

    shared = mf("text_encoders", "te.safetensors", b"t" * 3000)
    a = dataclasses.replace(catalog.Z_IMAGE_TURBO, id="tiny-a", files=(
        mf("diffusion_models", "a.safetensors", b"a" * 5000), shared, mf("vae", "vae-a.safetensors", b"v" * 700)))
    b = dataclasses.replace(catalog.FLUX2_KLEIN_4B, id="tiny-b", files=(
        mf("diffusion_models", "b.safetensors", b"b" * 4000), shared, mf("vae", "vae-b.safetensors", b"w" * 600)))
    monkeypatch.setattr(catalog, "hf_url", lambda repo, rev, path: f"{srv.url}/{repo}/resolve/{rev}/{path}")
    monkeypatch.setattr(catalog, "MODELS", (a, b, catalog.WAN22_TI2V_5B, catalog.SUPERTONIC_3))
    return a, b


def test_models_download_once_and_removal_keeps_shared_files(file_server, monkeypatch):
    srv = file_server({})
    a, b = tiny_models(srv, monkeypatch)
    assert models.download_bytes(a, "clipforge", None) == a.bytes
    assert run_steps(models.install_steps(a, "clipforge", None))["state"] == "done"
    assert models.missing(a, "clipforge", None) == []
    assert [f.name for f in models.missing(b, "clipforge", None)] == ["b.safetensors", "vae-b.safetensors"]
    hits = len(srv.hits)
    assert run_steps(models.install_steps(b, "clipforge", None))["state"] == "done"
    assert len(srv.hits) - hits == 2  # the shared text encoder was not downloaded again
    root = comfy_server.models_root()
    assert models.remove(a, keep={"tiny-b"}) == ["a.safetensors", "vae-a.safetensors"]
    assert (root / "text_encoders" / "te.safetensors").is_file() and models.missing(b, "clipforge", None) == []
    assert sorted(models.remove(b, keep=set())) == ["b.safetensors", "te.safetensors", "vae-b.safetensors"]
    assert not any(any((root / sub).glob("*.safetensors")) for sub in catalog.MODEL_FOLDERS)
    assert models._read_index() == {}  # noqa: SLF001


def test_a_file_clipforge_did_not_download_is_never_replaced(file_server, monkeypatch):
    srv = file_server({})
    a, _ = tiny_models(srv, monkeypatch)
    theirs = comfy_server.models_root() / "vae" / "vae-a.safetensors"
    theirs.parent.mkdir(parents=True, exist_ok=True)
    theirs.write_bytes(b"q" * 700)  # same name and size, different file
    view = run_steps(models.install_steps(a, "clipforge", None))
    assert view["state"] == "failed" and "did not replace it" in view["error"]
    assert theirs.read_bytes() == b"q" * 700
    right = comfy_server.models_root() / "diffusion_models" / "a.safetensors"
    assert right.is_file()  # the files before it were downloaded and checked
    theirs.write_bytes(b"v" * 700)  # the right file, put there by someone else: checked and used
    assert run_steps(models.install_steps(a, "clipforge", None))["state"] == "done"
    assert models.missing(a, "clipforge", None) == []


def test_a_comfyui_app_gets_models_in_its_own_folders(file_server, monkeypatch, fake_comfy):
    srv = file_server({})
    a, _ = tiny_models(srv, monkeypatch)
    where = models.folders("app", fake_comfy.url)
    assert where["vae"] == fake_comfy.tmp / "app-models" / "vae"
    assert run_steps(models.install_steps(a, "app", fake_comfy.url))["state"] == "done"
    assert (fake_comfy.tmp / "app-models" / "diffusion_models" / "a.safetensors").read_bytes() == b"a" * 5000
    fake_comfy.have(a)
    assert models.missing(a, "app", fake_comfy.url) == []
    assert models.folders("app", "http://192.168.1.20:8188") is None  # another computer: ClipForge cannot write there
    with pytest.raises(EngineError, match="only put models into a ComfyUI on this computer"):
        models.install_steps(a, "app", "http://192.168.1.20:8188")


# ------------------------------------------------------------------ choosing a model
def test_the_best_model_for_each_computer():
    assert [m.id for m in makers.ranked("image", mac(16))] == ["flux2-klein-4b", "z-image-turbo"]
    assert [m.id for m in makers.ranked("image", mac(32))] == ["z-image-turbo", "flux2-klein-4b"]
    nv8 = {"flavor": "cuda", "memory_mb": 32768, "vram_mb": 8192, "gpu": {}}
    assert makers.ranked("image", nv8)[0].id == "flux2-klein-4b"
    assert makers.fit(catalog.WAN22_TI2V_5B, mac(16)) == "slow" and makers.fit(catalog.WAN22_TI2V_5B, mac(36)) == "good"
    assert makers.fit(catalog.Z_IMAGE_TURBO, {"flavor": "cpu"}) == "cpu"
    assert makers.fit(catalog.SUPERTONIC_3, {"flavor": "cpu"}) == "good"


def test_the_chosen_model_is_the_one_in_settings_when_it_is_there(app_settings, fake_comfy, monkeypatch):
    monkeypatch.setattr(makers, "machine", lambda: mac(48))
    assert makers.chosen("image", app_settings) is None
    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    assert makers.chosen("image", app_settings).id == "flux2-klein-4b"
    fake_comfy.have(catalog.Z_IMAGE_TURBO)
    assert makers.chosen("image", app_settings).id == "z-image-turbo"  # the better one for this Mac
    app_settings["engines_picture"] = "flux2-klein-4b"
    assert makers.chosen("image", app_settings).id == "flux2-klein-4b"
    app_settings["engines_picture"] = "wan2.2-ti2v-5b"  # not a picture model: ignored
    assert makers.chosen("image", app_settings).id == "z-image-turbo"


def test_status_says_what_is_missing(app_settings, fake_comfy, monkeypatch):
    from clipfoundry import engines

    st = engines.status("image")
    assert not st["ready"] and "none of the models" in st["why"]
    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    st = engines.status("image")
    assert st["ready"] and st["model"] == "flux2-klein-4b" and fake_comfy.url in st["engine"]
    app_settings["engines_comfyui"] = "off"
    assert "turned off" in engines.status("image")["why"]
    app_settings["engines_comfyui"] = "clipforge"
    assert "not set up" in engines.status("video")["why"]
    assert "not downloaded" in engines.status("voice")["why"]
    monkeypatch.setenv("CLIPFOUNDRY_MODE", "cloud")
    assert "desktop app" in engines.status("image")["why"]
    assert engines.status("nonsense")["ready"] is False


# ------------------------------------------------------------------ the graphs
def _links_ok(graph: dict) -> None:
    for nid, node in graph.items():
        assert set(node) == {"class_type", "inputs"}
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert len(value) == 2 and value[0] in graph and isinstance(value[1], int), (nid, value)


def test_picture_graphs_follow_the_official_examples():
    z, steps = graphs.picture(catalog.Z_IMAGE_TURBO, "a red bicycle", "blurry", 768, 1344, 42)
    _links_ok(z)
    assert steps == "8" and z["8"]["class_type"] == "KSampler"
    k = z["8"]["inputs"]
    assert (k["steps"], k["cfg"], k["sampler_name"], k["scheduler"], k["seed"]) == (8, 1.0, "res_multistep", "simple", 42)
    assert z["4"]["inputs"]["shift"] == 3.0 and z["2"]["inputs"]["type"] == "lumina2"
    assert z["6"]["class_type"] == "ConditioningZeroOut"  # no guidance: the negative words are not used
    assert (z["7"]["inputs"]["width"], z["7"]["inputs"]["height"]) == (768, 1344)
    names = {f.name for f in catalog.Z_IMAGE_TURBO.files}
    assert {z["1"]["inputs"]["unet_name"], z["2"]["inputs"]["clip_name"], z["3"]["inputs"]["vae_name"]} == names
    f, steps = graphs.picture(catalog.FLUX2_KLEIN_4B, "a red bicycle", "", 1024, 1024, 7)
    _links_ok(f)
    assert steps == "11" and f["11"]["class_type"] == "SamplerCustomAdvanced"
    assert f["6"]["inputs"] == {"steps": 4, "width": 1024, "height": 1024}
    assert f["9"]["inputs"]["cfg"] == 1.0 and f["7"]["inputs"]["sampler_name"] == "euler"
    assert f["2"]["inputs"]["type"] == "flux2" and f["8"]["inputs"]["noise_seed"] == 7
    for g in (z, f):
        assert any(n["class_type"] == "SaveImage" and n["inputs"]["filename_prefix"] == "clipforge/picture"
                   for n in g.values())
    with pytest.raises(ValueError):
        graphs.picture(catalog.WAN22_TI2V_5B, "x", "", 64, 64, 1)


def test_the_video_graph_follows_the_official_example():
    m = catalog.WAN22_TI2V_5B
    g, steps = graphs.video(m, "waves on a beach", "", 480, 832, 49, 24, 3)
    _links_ok(g)
    k = g[steps]["inputs"]
    assert (k["steps"], k["cfg"], k["sampler_name"], k["scheduler"]) == (20, 5.0, "uni_pc", "simple")
    assert g["4"]["inputs"]["shift"] == 8.0 and g["2"]["inputs"]["type"] == "wan"
    assert g["6"]["inputs"]["text"] == catalog.WAN_NEGATIVE  # Wan's own default negative words
    assert g["7"]["inputs"] == {"vae": ["3", 0], "width": 480, "height": 832, "length": 49, "batch_size": 1}
    assert g["10"]["inputs"]["fps"] == 24.0
    assert g["11"]["inputs"]["format"] == "mp4" and g["11"]["inputs"]["format.codec"] == "h264"
    assert "12" not in g
    g2, _ = graphs.video(m, "the picture moves", "", 480, 832, 49, 24, 3, image="clipforge-abc.png")
    _links_ok(g2)
    assert g2["12"] == {"class_type": "LoadImage", "inputs": {"image": "clipforge-abc.png"}}
    assert g2["7"]["inputs"]["start_image"] == ["12", 0]


def test_sizes_are_rounded_to_what_the_models_make():
    z = catalog.Z_IMAGE_TURBO
    assert graphs.picture_size(z, 1080, 1920) == (1088, 1920)
    w, h = graphs.picture_size(z, 4000, 4000)
    assert w == h and w * h <= z.defaults["max_pixels"] * 1.02 and w % 16 == 0
    m = catalog.WAN22_TI2V_5B
    w, h, frames, fps = graphs.video_shape(m, 720, 1280, 4.0)
    assert w % 32 == 0 and h % 32 == 0 and w * h <= 1280 * 704 * 1.05 and fps == 24
    assert (frames - 1) % 4 == 0 and frames == 97
    assert graphs.video_shape(m, 480, 832, 60.0)[2] == 121  # at most 5 seconds
    assert graphs.video_shape(m, 480, 832, 0.1)[2] >= 5


def test_the_model_free_checks():
    g, _ = graphs.check_picture()
    assert graphs.class_types(g) == ["EmptyImage", "SaveImage"]
    g, _ = graphs.check_video(frames=25)
    assert graphs.class_types(g) == ["CreateVideo", "EmptyImage", "SaveVideo"] and g["1"]["inputs"]["batch_size"] == 25


# ------------------------------------------------------------------ making pictures and clips
def test_a_picture_from_the_comfyui_app(app_settings, fake_comfy, monkeypatch):
    from clipfoundry import engines

    monkeypatch.setattr(makers, "machine", lambda: mac(16))
    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    seen = []
    path = engines.make_image("A lighthouse at dusk", style="watercolour", width=1080, height=1920, seed=5,
                              progress=lambda f, m: seen.append((f, m)))
    assert path.suffix == ".png" and makers.png_size(path) == (1088, 1920)
    assert path.parent.parent.name == "picture" and path.parent.parent.parent.name == "made"
    note = json.loads(path.with_suffix(".json").read_text())
    assert note["model"] == "flux2-klein-4b" and note["licence"] == "Apache-2.0" and note["seed"] == 5
    assert note["prompt"] == "A lighthouse at dusk. watercolour" and (note["width"], note["height"]) == (1088, 1920)
    sent = fake_comfy.prompts[-1]
    assert sent["4"]["inputs"]["text"] == "A lighthouse at dusk. watercolour"
    assert seen and seen[0][1] == "Sending the request to ComfyUI" and seen[-1][1] == "Saving"
    assert ("POST", "/free") not in fake_comfy.calls  # someone's own ComfyUI keeps its models loaded
    with pytest.raises(EngineError, match="Say what"):
        engines.make_image("   ")


def test_a_clip_from_a_picture(app_settings, fake_comfy, tmp_path):
    from clipfoundry import engines

    fake_comfy.have(catalog.WAN22_TI2V_5B)
    start = tmp_path / "start.png"
    start.write_bytes(png_bytes(64, 64))
    path = engines.make_video("The waves roll in", image=start, seconds=2.0, width=480, height=832, seed=1)
    assert path.suffix == ".mp4" and path.read_bytes()[4:8] == b"ftyp"
    sent = fake_comfy.prompts[-1]
    assert sent["12"]["inputs"]["image"] == fake_comfy.uploads[-1] and fake_comfy.uploads[-1].startswith("clipforge-")
    note = json.loads(path.with_suffix(".json").read_text())
    assert note["from_picture"] and note["frames"] == 49 and note["fps"] == 24 and note["model"] == "wan2.2-ti2v-5b"
    with pytest.raises(EngineError, match="missing"):
        engines.make_video("x", image=tmp_path / "nope.png")


def test_comfyui_problems_reach_the_person_in_plain_words(app_settings, fake_comfy):
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    fake_comfy.fail_with = "MPS backend out of memory (MPS allocated: 17.2 GB)"
    with pytest.raises(EngineError, match="ran out of memory"):
        engines.make_image("a cat")
    fake_comfy.models["vae"].clear()  # ComfyUI lost a file between the check and the run
    makers.forget_found()
    with pytest.raises(EngineError, match="none of the models"):
        engines.make_image("a cat")
    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    fake_comfy.nodes.discard("EmptyFlux2LatentImage")
    with pytest.raises(EngineError, match="lacks EmptyFlux2LatentImage"):
        engines.make_image("a cat")
    assert comfy.plain("Value not in list: unet_name: 'x'").startswith("ComfyUI does not have a model file")
    assert "damaged" in comfy.plain("Error while deserializing header: HeaderTooLarge")
    assert comfy.plain("") == "ComfyUI stopped without saying why."


def test_stopping_a_picture_interrupts_comfyui(app_settings, fake_comfy):
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    fake_comfy.polls_before_done = 10_000
    asked = []

    def cancel() -> bool:
        asked.append(1)
        return len(asked) > 3

    with pytest.raises(EngineError, match="Stopped"):
        engines.make_image("a cat", cancel=cancel)
    assert ("POST", "/interrupt") in fake_comfy.calls and ("POST", "/queue") in fake_comfy.calls


def test_a_comfyui_that_is_not_running(app_settings, fake_comfy):
    from clipfoundry import engines

    app_settings["engines_comfyui_url"] = "http://127.0.0.1:9"
    with pytest.raises(EngineError, match="not running"):
        engines.make_image("a cat")
    app_settings["engines_comfyui"] = "off"
    with pytest.raises(EngineError, match="turned off"):
        engines.make_image("a cat")


def test_clipforges_own_comfyui_hands_its_memory_back(monkeypatch, fake_comfy):
    port = int(fake_comfy.url.rsplit(":", 1)[1])
    monkeypatch.setattr(comfy_server.server, "running", lambda: True)
    monkeypatch.setattr(comfy_server.server, "port", port)
    makers.make_room("picture maker")  # its own work: nothing to free
    assert ("POST", "/free") not in fake_comfy.calls
    makers.make_room("transcription")
    assert ("POST", "/free") in fake_comfy.calls


# ------------------------------------------------------------------ the built-in voice
def test_text_is_cleaned_and_cut_like_the_reference():
    assert voice.clean("Hello 😀 “world” — ok") == 'Hello "world" - ok.'
    assert voice.clean("Done!") == "Done!"
    assert voice.clean("email me @ home") == "email me at home."
    long = " ".join(f"Sentence number {i} is here, with a few words." for i in range(40))
    parts = voice.chunks(long, 300)
    assert len(parts) > 3 and all(len(p) <= 300 for p in parts)
    assert " ".join(parts).split() == long.split()
    assert voice.chunks("Dr. Smith arrived. He sat.", 300) == ["Dr. Smith arrived. He sat."]
    huge = "word " * 200
    assert all(len(p) <= 120 for p in voice.chunks(huge, 120))
    assert voice.chunks("One.\n\nTwo.") == ["One.", "Two."]


def test_word_times_cover_the_sentence_in_order():
    words = voice.word_times("Here is a sentence, with a pause.", 1.0, 3.0)
    assert [w["text"] for w in words] == "Here is a sentence, with a pause.".split()
    assert words[0]["start_s"] >= 1.0 and words[-1]["end_s"] <= 3.0
    assert all(a["end_s"] <= b["start_s"] + 1e-6 for a, b in zip(words, words[1:]))
    assert voice.word_times("", 0, 1) == []


class StandInVoice:
    sample_rate = 44100

    def __init__(self) -> None:
        self.said = []

    def say(self, text, voice_id, lang, speed, steps, cancel):
        import numpy as np

        self.said.append((text, voice_id, lang, round(speed, 3), steps))
        seconds = 0.05 * len(text)
        t = np.arange(int(seconds * self.sample_rate)) / self.sample_rate
        return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), seconds


def test_speaking_writes_a_wav_with_word_times(monkeypatch):
    from clipfoundry import engines

    fake = StandInVoice()
    monkeypatch.setattr(voice, "_get", lambda: fake)
    text = "First sentence here. " + "Second one is a little longer, with a comma. " * 8
    got = engines.speak(text, voice="M3", speed=1.0, lang="en")
    path = Path(got["path"])
    with wave.open(str(path)) as w:
        assert w.getframerate() == 44100 and w.getnchannels() == 1 and w.getsampwidth() == 2
        seconds = w.getnframes() / w.getframerate()
    assert abs(seconds - got["duration_s"]) < 0.01
    assert len(fake.said) > 1 and all(s[1] == "M3" and s[2] == "en" and s[4] == 8 for s in fake.said)
    pauses = 0.3 * (len(fake.said) - 1)
    assert abs(got["duration_s"] - (sum(0.05 * len(s[0]) for s in fake.said) + pauses)) < 0.01
    assert [w["text"] for w in got["words"]] == voice.clean(text).split()
    assert got["word_timing"] == "estimated" and "machine-generated" in got["rule"]
    note = json.loads(path.with_suffix(".json").read_text())
    assert note["licence"].startswith("OpenRAIL-M") and note["voice"] == "M3" and len(note["words"]) == len(got["words"])
    assert fake.said[0][3] == 1.05  # Supertonic's natural pace
    engines.speak("Bonjour.", voice="nobody", lang="xx", speed=9)
    assert fake.said[-1][1] == voice.DEFAULT_VOICE and fake.said[-1][2] == "na" and fake.said[-1][3] == 2.0
    with pytest.raises(EngineError, match="no words"):
        engines.speak("  😀 ")


def test_the_voice_downloads_checks_and_removes(file_server, monkeypatch):
    srv = file_server({})
    rev = "b" * 40

    def mf(path, data):
        srv.blobs[f"/v/resolve/{rev}/{path}"] = data
        folder, _, name = path.rpartition("/")
        return catalog.ModelFile(folder, name, "v", rev, path, len(data), hashlib.sha256(data).hexdigest())

    small = dataclasses.replace(catalog.SUPERTONIC_3, files=(mf("onnx/tts.json", b"{}"), mf("voice_styles/F1.json",
                                                                                            b"[1]"), mf("LICENSE", b"L")))
    monkeypatch.setattr(catalog, "SUPERTONIC_3", small)
    monkeypatch.setattr(catalog, "hf_url", lambda repo, r, path: f"{srv.url}/{repo}/resolve/{r}/{path}")
    assert not voice.installed() and voice.download_bytes() == small.bytes and voice.voices() == []
    assert run_steps(voice.install_steps())["state"] == "done"
    assert voice.installed() and voice.download_bytes() == 0 and len(voice.voices()) == 10
    assert voice.status()["ready"] and voice.install_steps() == []
    voice.remove()
    assert not voice.installed() and not voice.folder().exists()


# ------------------------------------------------------------------ the background job
def test_one_setup_at_a_time_with_plain_errors():
    order = []

    def ok(report, cancelled):
        report("Working", 1, 2)
        order.append("ok")

    def bad(report, cancelled):
        raise EngineError("It broke, in plain words.")

    view = tasks.start("A", [ok, bad, ok], wait=True)
    assert view["state"] == "failed" and view["error"] == "It broke, in plain words." and order == ["ok"]
    gate = threading.Event()

    def slow(report, cancelled):
        while not cancelled():
            gate.wait(0.01)
        raise EngineError("Stopped.")

    tasks.start("B", [slow])
    with pytest.raises(EngineError, match="already running"):
        tasks.start("C", [ok])
    tasks.cancel()
    for _ in range(200):
        if not tasks.running():
            break
        time.sleep(0.01)
    assert tasks.view()["state"] == "canceled" and tasks.view()["error"] == ""
    done = []
    assert tasks.start("D", [ok], on_done=lambda: done.append(1), wait=True)["state"] == "done" and done


# ------------------------------------------------------------------ Settings
def test_engine_settings_are_checked():
    v = config.validate_settings({"engines_comfyui": "app", "engines_comfyui_url": "http://127.0.0.1:8000/",
                                  "engines_picture": "flux2-klein-4b", "engines_idle_minutes": 500})
    assert v == {"engines_comfyui": "app", "engines_comfyui_url": "http://127.0.0.1:8000",
                 "engines_picture": "flux2-klein-4b", "engines_idle_minutes": 120.0}
    assert config.validate_settings({"engines_comfyui": "somewhere"}) == {}
    assert config.validate_settings({"engines_comfyui_url": "file:///etc/passwd"}) == {}
    assert config.validate_settings({"engines_video": "../../evil"}) == {}
    assert config.validate_settings({"engines_comfyui_url": ""}) == {"engines_comfyui_url": ""}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from clipfoundry import api

    return TestClient(api.app)


APP = {"X-ClipFoundry": "1"}


def test_settings_shows_every_maker(client, monkeypatch):
    monkeypatch.setattr(makers, "machine", lambda: mac(16))
    r = client.get("/api/engines")
    assert r.status_code == 200
    d = r.json()
    ids = [m["id"] for m in d["models"]]
    assert ids == ["z-image-turbo", "flux2-klein-4b", "wan2.2-ti2v-5b", "supertonic-3"]
    by = {m["id"]: m for m in d["models"]}
    assert by["flux2-klein-4b"]["recommended"] and not by["z-image-turbo"]["recommended"]
    assert by["z-image-turbo"]["fit"] == "slow" and by["supertonic-3"]["fit"] == "good"
    assert not by["wan2.2-ti2v-5b"]["recommended"]  # the only video model: nothing to choose between
    assert d["comfyui"]["version"] == catalog.COMFYUI["version"] and d["comfyui"]["licence"] == "GPL-3.0"
    assert d["memory_mb"] == 16 * 1024 and "machine-generated" in d["voice_rule"]
    assert d["trial"]["state"] == "idle" and d["task"]["state"] == "idle"
    assert set(d["roles"]) == {"image", "video", "voice"}


def test_changes_only_come_from_clipforges_own_page(client):
    for path, body in (("/api/engines/setup", {"what": "comfyui"}), ("/api/engines/remove", {"what": "comfyui"}),
                       ("/api/engines/try", {"role": "voice"}), ("/api/engines/cancel", {})):
        assert client.post(path, json=body).status_code == 403, path
    r = client.post("/api/engines/setup", json={"what": "model", "model": "nope"}, headers=APP)
    assert r.status_code == 409 and "Unknown model" in r.json()["detail"]
    r = client.post("/api/engines/try", json={"role": "voice"}, headers=APP)
    assert r.status_code == 409 and "not downloaded" in r.json()["detail"]
    assert client.post("/api/engines/try", json={"role": "music"}, headers=APP).status_code == 400


def test_a_voice_try_from_settings(client, monkeypatch):
    fake = StandInVoice()
    monkeypatch.setattr(voice, "_get", lambda: fake)
    monkeypatch.setattr(voice, "installed", lambda m=None: True)
    r = client.post("/api/engines/try", json={"role": "voice", "voice": "F2"}, headers=APP)
    assert r.status_code == 200
    for _ in range(300):
        view = client.get("/api/engines").json()["trial"]
        if view["state"] != "running":
            break
        time.sleep(0.02)
    assert view["state"] == "done" and view["file"].startswith("/api/engines/made/voice/")
    got = client.get(view["file"])
    assert got.status_code == 200 and got.headers["content-type"] == "audio/wav" and got.content[:4] == b"RIFF"
    assert fake.said[0][1] == "F2"


def test_only_made_files_are_served(client):
    made = config.data_dir() / "engines" / "made" / "picture" / "2026-11-07"
    made.mkdir(parents=True, exist_ok=True)
    (made / "a.png").write_bytes(png_bytes(4, 4))
    (made / "notes.txt").write_text("no")
    (config.data_dir() / "secret.png").write_bytes(b"no")
    assert client.get("/api/engines/made/picture/2026-11-07/a.png").status_code == 200
    assert client.get("/api/engines/made/picture/2026-11-07/notes.txt").status_code == 404
    assert client.get("/api/engines/made/..%2F..%2Fsecret.png").status_code == 404
    assert client.get("/api/engines/made/../../secret.png").status_code == 404


def test_the_online_studio_offers_no_local_makers(monkeypatch):
    from fastapi import HTTPException

    from clipfoundry.engines import routes

    monkeypatch.setenv("CLIPFOUNDRY_MODE", "cloud")
    for call in (routes.engines_view, lambda: routes.engines_setup({"what": "comfyui"}),
                 lambda: routes.engines_try({"role": "voice"}), lambda: routes.engines_made("picture/a.png")):
        with pytest.raises(HTTPException) as err:
            call()
        assert err.value.status_code == 404

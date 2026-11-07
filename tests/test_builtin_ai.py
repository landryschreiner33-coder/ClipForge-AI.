"""The built-in model (clipfoundry/builtin_ai.py): choosing the level from the computer, downloading and checking the
engine and a model (resume, damaged files, unsafe archives), starting the engine on this computer only with a fresh
key, sharing it with another ClipForge process, stopping it when idle, when other GPU work needs the memory and when
it was left over from a killed run, and ClipForge AI using it like any other provider.

The engine here is a stand-in program that speaks the same HTTP as llama.cpp's server (tests/fake_llama_server.py);
the real engine and models are checked by scripts/builtin_ai_check.py on GitHub's Mac, Windows and Linux machines.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

FAKE = Path(__file__).with_name("fake_llama_server.py")


class _Files(BaseHTTPRequestHandler):
    """Serves the fake engine archive and model files, with byte ranges (resumed downloads)."""
    files: dict[str, bytes] = {}
    requests: list[tuple[str, str]] = []

    def log_message(self, *a):  # noqa: D401
        pass

    def do_GET(self):  # noqa: N802
        type(self).requests.append((self.path, self.headers.get("Range", "")))
        data = self.files.get(self.path)
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            body = data[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            body = data
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _tar(entries: list[tuple[str, bytes | None, str]]) -> bytes:
    """A .tar.gz from (name, content or None for a folder, link target or '')."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, content, link in entries:
            info = tarfile.TarInfo(name)
            if link:
                info.type, info.linkname = tarfile.SYMTYPE, link
                t.addfile(info)
            elif content is None:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                t.addfile(info)
            else:
                info.size, info.mode = len(content), 0o755
                t.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _engine_archive() -> bytes:
    launcher = f"#!{sys.executable}\nimport runpy, sys\nsys.argv[0] = {str(FAKE)!r}\nrunpy.run_path({str(FAKE)!r}, run_name='__main__')\n"
    return _tar([("llama-test/", None, ""), ("llama-test/llama-server", launcher.encode(), ""),
                 ("llama-test/libggml.dylib", None, ""), ("llama-test/libllama.0.dylib", b"lib", ""),
                 ("llama-test/libllama.dylib", None, "libllama.0.dylib")])


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture()
def hub(monkeypatch, tmp_path):
    """A local stand-in for GitHub releases (the engine) and Hugging Face (the models)."""
    if sys.platform == "win32":
        pytest.skip("the stand-in engine is a script with a #! line")
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import builtin_ai, db

    db.init()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Files)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    archive = _engine_archive()
    model, vision = os.urandom(300_000), os.urandom(50_000)
    _Files.files = {"/engine/v1/llama-test.tar.gz": archive, "/org/tiny/resolve/rev1/tiny.gguf": model,
                    "/org/tiny/resolve/rev1/mmproj-tiny.gguf": vision}
    _Files.requests = []
    monkeypatch.setattr(builtin_ai, "platform_key", lambda: "linux-x64")
    monkeypatch.setattr(builtin_ai, "ENGINE_VERSION", "v1")
    monkeypatch.setattr(builtin_ai, "ENGINE_URL", base + "/engine/{version}/{file}")
    monkeypatch.setattr(builtin_ai, "ENGINES", {"linux-x64": {"file": "llama-test.tar.gz", "size": len(archive),
                                                              "sha256": _sha(archive),
                                                              "server": "llama-test/llama-server"}})
    level = {"name": "Basic", "model": "Tiny VL", "license": "Apache 2.0", "memory_gb": 1, "repo": "org/tiny",
             "revision": "rev1", "about": "test",
             "files": [{"name": "tiny.gguf", "role": "model", "size": len(model), "sha256": _sha(model)},
                       {"name": "mmproj-tiny.gguf", "role": "vision", "size": len(vision), "sha256": _sha(vision)}]}
    monkeypatch.setattr(builtin_ai, "MODELS", {"basic": level, "standard": {**level, "name": "Standard",
                                                                              "revision": "rev2"},
                                               "pro": {**level, "name": "Pro", "revision": "rev3"}})
    monkeypatch.setenv("HF_ENDPOINT", base)
    monkeypatch.setattr(builtin_ai, "IDLE_POLL_S", 0.05)
    monkeypatch.setattr(builtin_ai, "_is_our_engine", lambda pid, exe: _alive_pid(pid))
    builtin_ai.server.stop()
    yield {"base": base, "model": model, "vision": vision, "archive": archive, "tmp": tmp_path}
    builtin_ai.server.stop()
    server.shutdown()


def _alive_pid(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _wait_task(timeout: float = 20.0) -> dict:
    from clipfoundry import builtin_ai

    end = time.time() + timeout
    while time.time() < end:
        t = builtin_ai.task()
        if t.get("state") != "running":
            return t
        time.sleep(0.05)
    raise AssertionError(builtin_ai.task())


def test_the_level_follows_the_computer():
    from clipfoundry.builtin_ai import recommended_level

    assert recommended_level(8192, 0, mac=True) == "basic"
    assert recommended_level(16384, 0, mac=True) == "standard"
    assert recommended_level(65536, 0, mac=True) == "standard"  # Pro is only ever chosen by hand
    assert recommended_level(16384, 0, mac=False) == "basic"     # no graphics card: the CPU would be slow
    assert recommended_level(16384, 4096, mac=False) == "standard"
    assert recommended_level(8192, 8192, mac=False) == "standard"
    assert recommended_level(0, 0, mac=False) == "basic"


def test_settings_accept_the_builtin_provider_and_levels_only():
    from clipfoundry import config

    ok = config.validate_settings({"ai_provider": "builtin", "builtin_ai_level": "pro", "builtin_ai_idle_minutes": 0})
    assert ok == {"ai_provider": "builtin", "builtin_ai_level": "pro", "builtin_ai_idle_minutes": 1.0}
    assert "builtin_ai_level" not in config.validate_settings({"builtin_ai_level": "huge"})


def test_install_downloads_checks_and_records_every_file(hub):
    from clipfoundry import builtin_ai

    assert builtin_ai.engine_path() is None and builtin_ai.installed_levels() == []
    done = []
    builtin_ai.install("basic", on_done=done.append)
    t = _wait_task()
    assert t["state"] == "done" and done == ["basic"], t
    exe = builtin_ai.engine_path()
    assert exe and exe.name == "llama-server" and os.access(exe, os.X_OK)
    folder = builtin_ai.engine_dir()
    assert (folder / "NOTICE-llama.cpp.txt").read_text().startswith("llama.cpp")
    assert (folder / "llama-test" / "libllama.dylib").is_symlink()  # links inside the folder are kept
    files = builtin_ai.model_files("basic")
    assert files["model"].read_bytes() == hub["model"] and files["vision"].read_bytes() == hub["vision"]
    assert builtin_ai.installed_levels() == ["basic"]
    assert not list(builtin_ai.root().glob("*.tar.gz")) and not list(builtin_ai.root().rglob("*.part"))
    # a second install has nothing to download
    _Files.requests.clear()
    builtin_ai.install("basic")
    assert _wait_task()["state"] == "done" and _Files.requests == []
    # a file that changed size afterwards is no longer trusted
    with open(files["model"], "ab") as fh:
        fh.write(b"x")
    assert builtin_ai.model_files("basic") is None and builtin_ai.installed_levels() == []


def test_a_damaged_download_is_deleted_and_explained(hub):
    from clipfoundry import builtin_ai

    _Files.files["/org/tiny/resolve/rev1/tiny.gguf"] = bytes(len(hub["model"]))  # right size, wrong bytes
    builtin_ai.install("basic")
    t = _wait_task()
    assert t["state"] == "failed" and "checksum mismatch" in t["error"]
    assert not (builtin_ai.level_dir("basic") / "tiny.gguf").exists()
    assert builtin_ai.model_files("basic") is None
    assert builtin_ai.engine_path() is not None  # the engine part that was fine stays


def test_a_stopped_download_resumes_where_it_stopped(hub):
    from clipfoundry import builtin_ai

    folder = builtin_ai.level_dir("basic")
    folder.mkdir(parents=True)
    (folder / "tiny.gguf.part").write_bytes(hub["model"][:100_000])
    builtin_ai.install("basic")
    assert _wait_task()["state"] == "done"
    assert ("/org/tiny/resolve/rev1/tiny.gguf", "bytes=100000-") in _Files.requests
    assert builtin_ai.model_files("basic")["model"].read_bytes() == hub["model"]


@pytest.mark.parametrize("entries, why", [
    ([("../evil", b"x", "")], "unsafe path"),
    ([("/abs/evil", b"x", "")], "unsafe path"),
    ([("llama-test/", None, ""), ("llama-test/passwd", None, "/etc/passwd")], "link out of its folder"),
    ([("llama-test/", None, ""), ("llama-test/up", None, "../../outside")], "link out of its folder"),
])
def test_an_unsafe_engine_archive_is_refused(hub, entries, why):
    from clipfoundry import builtin_ai

    bad = _tar(entries)
    _Files.files["/engine/v1/llama-test.tar.gz"] = bad
    builtin_ai.ENGINES["linux-x64"].update(size=len(bad), sha256=_sha(bad))
    builtin_ai.install("basic")
    t = _wait_task()
    assert t["state"] == "failed" and why in t["error"], t
    assert builtin_ai.engine_path() is None
    assert not (hub["tmp"] / "evil").exists()


def test_a_tampered_engine_never_runs(hub):
    from clipfoundry import builtin_ai

    _Files.files["/engine/v1/llama-test.tar.gz"] = hub["archive"][:-10] + b"0123456789"
    builtin_ai.install("basic")
    t = _wait_task()
    assert t["state"] == "failed" and "checksum mismatch" in t["error"] and builtin_ai.engine_path() is None


def test_not_enough_disk_space_is_said_before_downloading(hub, monkeypatch):
    from clipfoundry import builtin_ai

    monkeypatch.setattr(builtin_ai, "_free_bytes", lambda p: 10_000)
    with pytest.raises(builtin_ai.BuiltinError, match="Not enough free disk space"):
        builtin_ai.install("basic")
    assert _Files.requests == []


def _install(level="basic"):
    from clipfoundry import builtin_ai

    builtin_ai.install(level)
    assert _wait_task()["state"] == "done"


def test_the_engine_runs_on_this_computer_only_with_a_fresh_key(hub):
    from clipfoundry import builtin_ai

    _install()
    settings = {"ai_provider": "builtin", "builtin_ai_level": "auto"}
    answer = builtin_ai.chat(settings, "SYSTEM", "Score this clip")
    assert json.loads(answer) == {"echo": "Score this clip", "system": "SYSTEM"}
    argv = json.loads((builtin_ai.engine_dir() / "llama-test" / "last-argv.json").read_text())
    opt = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("-")}
    assert opt["--host"] == "127.0.0.1" and "--no-webui" in argv and "--offline" in argv
    assert opt["-m"].endswith("tiny.gguf") and opt["--mmproj"].endswith("mmproj-tiny.gguf")
    assert len(opt["--api-key"]) >= 24
    first = (builtin_ai.server.port, builtin_ai.server.key)
    rec = json.loads(builtin_ai.server.pid_file.read_text())
    assert rec["owner"] == os.getpid() and rec["port"] == first[0] and rec["level"] == "basic"
    assert (builtin_ai.server.pid_file.stat().st_mode & 0o077) == 0  # only this user can read the key
    # without the key, the engine answers nobody
    import httpx

    r = httpx.post(f"http://127.0.0.1:{first[0]}/v1/chat/completions", json={"messages": []}, trust_env=False)
    assert r.status_code == 401
    # the same engine answers the next request; a restart gets a new port and key
    builtin_ai.chat(settings, "S", "again")
    assert (builtin_ai.server.port, builtin_ai.server.key) == first
    builtin_ai.server.stop()
    assert not builtin_ai.server.pid_file.exists()
    builtin_ai.chat(settings, "S", "after a restart")
    assert builtin_ai.server.key != first[1]


def test_the_engine_stops_when_idle(hub):
    from clipfoundry import builtin_ai

    _install()
    builtin_ai.chat({"builtin_ai_level": "basic"}, "S", "hi")
    proc = builtin_ai.server.proc
    builtin_ai.server.idle_s = 0.2
    end = time.time() + 10
    while builtin_ai.server.running() and time.time() < end:
        time.sleep(0.05)
    assert not builtin_ai.server.running() and proc.poll() is not None


def test_other_gpu_work_frees_the_engines_memory(hub, monkeypatch):
    from clipfoundry import builtin_ai, gpu

    _install()
    builtin_ai.chat({"builtin_ai_level": "basic"}, "S", "hi")
    with gpu.manager.heavy("local AI model", "x"):
        assert builtin_ai.server.running()  # the AI's own requests keep it
    monkeypatch.setattr(builtin_ai.sys, "platform", "linux")
    with gpu.manager.heavy("transcription", "talk.mp4"):
        assert not builtin_ai.server.running()


def test_a_leftover_engine_is_stopped_and_a_live_one_is_shared(hub):
    import subprocess

    from clipfoundry import builtin_ai

    _install()
    exe = builtin_ai.engine_path()
    files = builtin_ai.model_files("basic")
    # an engine whose ClipForge process was killed (its owner pid is gone)
    stray = subprocess.Popen(builtin_ai.build_command(exe, files, builtin_ai._free_port(), "k" * 24, 1),
                             cwd=exe.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dead_owner = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_owner.wait()
    builtin_ai.server.pid_file.write_text(json.dumps({"pid": stray.pid, "exe": str(exe), "owner": dead_owner.pid,
                                                      "port": 1, "key": "k", "level": "basic"}))
    builtin_ai.chat({"builtin_ai_level": "basic"}, "S", "hi")
    assert stray.wait(timeout=10) is not None
    assert builtin_ai.server.proc.pid != stray.pid
    builtin_ai.server.stop()
    # an engine another live ClipForge process (the Autopilot worker) runs is used, not stopped
    port = builtin_ai._free_port()
    other = subprocess.Popen(builtin_ai.build_command(exe, files, port, "shared-key-" + "x" * 20, 1),
                             cwd=exe.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        for _ in range(100):
            try:
                import httpx

                if httpx.get(f"http://127.0.0.1:{port}/health", trust_env=False).status_code == 200:
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.05)
        builtin_ai.server.pid_file.write_text(json.dumps({"pid": other.pid, "exe": str(exe), "owner": owner.pid,
                                                          "port": port, "key": "shared-key-" + "x" * 20,
                                                          "level": "basic"}))
        assert json.loads(builtin_ai.chat({"builtin_ai_level": "basic"}, "S", "shared"))["echo"] == "shared"
        assert not builtin_ai.server.running() and other.poll() is None  # used, not owned, not stopped
    finally:
        other.kill()
        owner.kill()


def test_a_model_that_fails_to_load_is_explained(hub, monkeypatch):
    from clipfoundry import builtin_ai

    _install()
    monkeypatch.setenv("FAKE_LLAMA_FAIL", "1")
    with pytest.raises(builtin_ai.BuiltinError, match="stopped while loading"):
        builtin_ai.chat({"builtin_ai_level": "basic"}, "S", "hi")
    assert not builtin_ai.server.running()


def test_the_ai_helper_uses_the_builtin_ai_like_any_provider(hub):
    from clipfoundry.pipeline import llm

    settings = {"ai_provider": "builtin", "builtin_ai_level": "auto"}
    with pytest.raises(llm.ProviderError, match="not set up yet"):
        llm.complete(settings, "hi")
    assert llm.check_provider(settings)["ok"] is False
    assert llm.provider_label(settings) == "Built-in model (not set up yet)" and llm.is_local(settings)
    _install()
    out = llm.complete(settings, "Score this", system="EDITOR")
    assert json.loads(out) == {"echo": "Score this", "system": "EDITOR"}
    assert llm.provider_label(settings) == "Built-in model (Tiny VL)"
    check = llm.check_provider(settings)
    assert check["ok"] and "on this computer" in check["detail"]
    from clipfoundry.studio import ai_editor, edit_requests

    assert ai_editor.is_local(settings, "builtin") and edit_requests._local(settings, "builtin")
    assert ai_editor.disclosure(settings, "builtin").startswith("Stayed on this computer")


def test_routes_set_up_use_and_remove_the_builtin_ai(hub):
    from fastapi.testclient import TestClient

    from clipfoundry import builtin_ai, db
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        h = {"X-ClipFoundry": "1"}
        view = api.get("/api/ai/setup", headers=h).json()
        assert view["presets"][0]["id"] == "builtin" and view["builtin"]["supported"]
        assert [lvl["id"] for lvl in view["builtin"]["levels"]] == ["basic", "standard", "pro"]
        assert api.post("/api/ai/builtin/use", json={"level": "basic"}, headers=h).status_code == 409
        assert api.post("/api/ai/builtin/install", json={"level": "huge"}, headers=h).status_code == 400
        r = api.post("/api/ai/builtin/install", json={"level": "basic"}, headers=h)
        assert r.status_code == 200 and r.json()["state"] == "running"
        assert _wait_task()["state"] == "done"
        s = db.get_settings()
        assert s["ai_provider"] == "builtin" and s["builtin_ai_level"] == "basic"  # it became ClipForge AI's model
        st = api.get("/api/ai/builtin", headers=h).json()
        assert st["level"] == "basic" and st["levels"][0]["installed"] and st["engine"]["installed"]
        r = api.post("/api/ai/builtin/remove", json={"level": "basic"}, headers=h)
        assert r.status_code == 200 and not r.json()["levels"][0]["installed"]
        assert db.get_settings()["ai_provider"] == "heuristic"
        assert builtin_ai.engine_path() is not None  # the engine stays; only the model's space is freed


def test_a_chosen_provider_is_kept_when_the_download_finishes(hub):
    from clipfoundry import api as api_module, db

    db.save_settings({"ai_provider": "ollama"})
    api_module._builtin_ready("basic")
    assert db.get_settings()["ai_provider"] == "ollama" and db.get_settings()["builtin_ai_level"] == "basic"

"""Whisper model download, verification and self-repair against a local stand-in for the Hugging Face Hub."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from clipfoundry import config
from clipfoundry.pipeline import models, transcribe
from clipfoundry.pipeline.common import JobContext

REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"  # what "large-v3-turbo" resolves to
COMMIT = "41f9da4ebb5e8e2e03bdc5e0dbc8a3e4b2c3d4e5"
LFS = {"model.bin"}


def _files() -> dict[str, bytes]:
    return {
        "config.json": json.dumps({"alignment_heads": [[2, 4]], "lang_ids": [50259]}).encode(),
        "preprocessor_config.json": json.dumps({"feature_size": 128, "n_samples": 480000}).encode(),
        "tokenizer.json": json.dumps({"version": "1.0", "model": {"type": "BPE"}}).encode(),
        "vocabulary.json": json.dumps(["<|endoftext|>", "hello"]).encode(),
        "model.bin": os.urandom(300_000),
    }


class FakeHub:
    """Serves model_info (with file sizes and hashes) and /resolve downloads (with HEAD, ETag and Range)."""

    def __init__(self) -> None:
        self.files = _files()
        self.served: dict[str, bytes] = {}  # override what is actually sent (corruption tests)
        self.gets: Counter = Counter()
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:
                pass

            def _file(self) -> str | None:
                prefix = f"/{REPO}/resolve/"
                if not self.path.startswith(prefix):
                    return None
                return self.path[len(prefix):].split("?")[0].split("/", 1)[1]

            def _headers_for(self, name: str) -> dict:
                data = hub.files[name]
                if name in LFS:
                    return {"X-Repo-Commit": COMMIT, "ETag": f'"{hashlib.sha256(data).hexdigest()}"',
                            "Content-Length": str(len(hub.served.get(name, data)))}
                git = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
                return {"X-Repo-Commit": COMMIT, "ETag": f'"{git}"', "Content-Length": str(len(data))}

            def do_HEAD(self) -> None:  # noqa: N802
                name = self._file()
                if name not in hub.files:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                for k, v in self._headers_for(name).items():
                    self.send_header(k, v)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith(f"/api/models/{REPO}"):
                    body = json.dumps({"id": REPO, "modelId": REPO, "sha": COMMIT, "private": False, "siblings": [
                        {"rfilename": n, "size": len(d),
                         "blobId": hashlib.sha1(b"blob %d\0" % len(d) + d).hexdigest(),
                         **({"lfs": {"sha256": hashlib.sha256(d).hexdigest(), "size": len(d), "pointerSize": 134}}
                            if n in LFS else {})}
                        for n, d in hub.files.items()] + [{"rfilename": "README.md", "size": 10}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                name = self._file()
                if name not in hub.files:
                    self.send_response(404)
                    self.end_headers()
                    return
                hub.gets[name] += 1
                data = hub.served.get(name, hub.files[name])
                start = 0
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    start = int(rng[6:].split("-")[0] or 0)
                self.send_response(206 if start else 200)
                headers = self._headers_for(name)
                headers["Content-Length"] = str(len(data) - start)
                if start:
                    headers["Content-Range"] = f"bytes {start}-{len(data) - 1}/{len(data)}"
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data[start:])

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def hub(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from huggingface_hub.utils import _http

    _http.close_session()  # the next request builds a client that honours NO_PROXY
    fake = FakeHub()
    monkeypatch.setenv("HF_ENDPOINT", fake.url)
    yield fake
    fake.stop()
    _http.close_session()


def _folder() -> Path:
    return models.model_dir("large-v3-turbo")


def test_fresh_download_is_complete_and_verified(hub):
    seen = []
    folder = models.ensure_model("large-v3-turbo", lambda done, total: seen.append((done, total)))
    assert folder == config.models_dir() / "large-v3-turbo"
    for name, data in hub.files.items():
        assert (folder / name).read_bytes() == data
    assert not models.local_problems(folder) and models.is_ready("large-v3-turbo")
    assert json.loads((folder / models.MARKER).read_text())["commit"] == COMMIT
    assert seen and seen[-1][0] == seen[-1][1] == sum(len(d) for d in hub.files.values())
    assert not list(config.models_dir().glob("models--*"))  # no Hugging Face cache layout


def test_missing_preprocessor_config_is_downloaded_before_use(hub):
    """The reported case: model present but preprocessor_config.json never made it to disk."""
    folder = _folder()
    folder.mkdir(parents=True)
    for name, data in hub.files.items():
        if name != "preprocessor_config.json":
            (folder / name).write_bytes(data)
    assert models.local_problems(folder) and not models.is_ready("large-v3-turbo")
    models.ensure_model("large-v3-turbo")
    assert (folder / "preprocessor_config.json").read_bytes() == hub.files["preprocessor_config.json"]
    assert hub.gets == Counter({"preprocessor_config.json": 1})  # model.bin was verified, not downloaded again


def test_truncated_file_is_redownloaded_even_though_hub_metadata_says_complete(hub):
    folder = models.ensure_model("large-v3-turbo")
    data = hub.files["model.bin"]
    (folder / "model.bin").write_bytes(data[:1000])  # e.g. a copy interrupted by a crash; hub metadata untouched
    assert "model.bin is incomplete" in models.local_problems(folder)[0]
    models.ensure_model("large-v3-turbo")
    assert (folder / "model.bin").read_bytes() == data and hub.gets["model.bin"] == 2


def test_corrupted_file_of_the_right_size_is_repaired(hub):
    folder = models.ensure_model("large-v3-turbo")
    bad = bytearray(hub.files["model.bin"])
    bad[5000] ^= 0xFF
    (folder / "model.bin").write_bytes(bytes(bad))
    assert models.is_ready("large-v3-turbo")  # the fast check cannot see a flipped byte...
    models.mark_suspect("large-v3-turbo")  # ...which is what a failed WhisperModel load triggers
    models.ensure_model("large-v3-turbo")
    assert (folder / "model.bin").read_bytes() == hub.files["model.bin"] and hub.gets["model.bin"] == 2


def test_hub_keeps_sending_bad_data_gives_clear_error(hub):
    bad = bytearray(hub.files["model.bin"])
    bad[0] ^= 0xFF
    hub.served["model.bin"] = bytes(bad)
    with pytest.raises(models.ModelError) as err:
        models.ensure_model("large-v3-turbo")
    assert "model.bin" in str(err.value) and hub.gets["model.bin"] >= 2
    assert not models.is_ready("large-v3-turbo")


def test_old_cache_layout_is_reused_and_removed(hub):
    snap = config.models_dir() / f"models--{REPO.replace('/', '--')}" / "snapshots" / COMMIT
    blobs = snap.parent.parent / "blobs"
    snap.mkdir(parents=True)
    blobs.mkdir()
    (blobs / "abc").write_bytes(hub.files["model.bin"])
    (snap / "model.bin").symlink_to(Path("..") / ".." / "blobs" / "abc")
    (snap / "config.json").write_bytes(hub.files["config.json"])  # preprocessor_config.json missing, as reported
    folder = models.ensure_model("large-v3-turbo")
    assert (folder / "model.bin").read_bytes() == hub.files["model.bin"]
    assert hub.gets["model.bin"] == 0 and hub.gets["config.json"] == 0
    assert hub.gets["preprocessor_config.json"] == 1
    assert not snap.parent.parent.exists()


def test_offline_use_of_a_verified_model_needs_no_network(hub):
    folder = models.ensure_model("large-v3-turbo")
    hub.stop()
    assert models.ensure_model("large-v3-turbo") == folder


def test_offline_with_missing_files_explains_the_fix(hub):
    hub.stop()
    with pytest.raises(models.ModelError) as err:
        models.ensure_model("large-v3-turbo")
    assert "not downloaded yet" in str(err.value) and err.value.fix == models.NET_FIX


def test_load_model_initializes_from_the_verified_folder_and_repairs_once(hub, monkeypatch):
    import types

    import faster_whisper

    inits: list[str] = []

    class FakeWhisper:
        def __init__(self, path, device, compute_type, cpu_threads):
            inits.append(path)
            if len(inits) == 1:
                raise RuntimeError(f"Unable to open file 'model.bin' in model '{path}'")
            self.model = types.SimpleNamespace(device=device, compute_type=compute_type)

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisper)
    corrupt = bytearray(hub.files["model.bin"])
    folder = models.ensure_model("large-v3-turbo")
    corrupt[10] ^= 0xFF
    (folder / "model.bin").write_bytes(bytes(corrupt))
    model, loaded = transcribe.load_model("large-v3-turbo", "cuda", "float16", JobContext())
    assert inits == [str(folder), str(folder)] and loaded["device"] == "cuda"
    assert (folder / "model.bin").read_bytes() == hub.files["model.bin"]  # repaired between the two attempts


def test_cuda_errors_never_trigger_a_redownload(hub, monkeypatch):
    import faster_whisper

    models.ensure_model("large-v3-turbo")

    class FailingWhisper:
        def __init__(self, *a, **k):
            raise RuntimeError("CUDA failed with error out of memory")

    monkeypatch.setattr(faster_whisper, "WhisperModel", FailingWhisper)
    with pytest.raises(RuntimeError, match="out of memory"):
        transcribe.load_model("large-v3-turbo", "cuda", "float16")
    assert hub.gets["model.bin"] == 1 and models.is_ready("large-v3-turbo")

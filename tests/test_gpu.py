"""GPU / CPU selection for faster-whisper, fallback behaviour and diagnostics (no GPU needed)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from clipfoundry.pipeline import cuda, transcribe
from clipfoundry.pipeline.common import JobContext

RTX3050 = {"index": 0, "name": "NVIDIA GeForce RTX 3050", "vram_mb": 6144, "driver": "566.36"}
AMPERE_TYPES = ["bfloat16", "float16", "float32", "int8", "int8_bfloat16", "int8_float16", "int8_float32"]


def status(**kw) -> dict:
    st = {"devices": 1, "gpus": [RTX3050], "compute_types": AMPERE_TYPES, "libraries": [], "libs_ok": True,
          "ctranslate2": "4.8.2", "toolkit": "", "problem": "", "fix": ""}
    st.update(kw)
    return st


MISSING = status(libs_ok=False, problem="NVIDIA GeForce RTX 3050 was found, but CTranslate2 cannot load cublas64_12.dll.",
                 fix=cuda.GPU_FIX)
NO_GPU = status(devices=0, gpus=[], compute_types=[], libs_ok=None)


def test_rtx3050_uses_cuda_float16_turbo():
    plan = transcribe.whisper_plan({}, status())
    assert (plan["mode"], plan["device"], plan["compute_type"], plan["model"]) == \
        ("gpu", "cuda", "float16", "large-v3-turbo")
    assert plan["problem"] == "" and plan["fix"] == ""


def test_low_vram_gpu_prefers_int8_float16():
    small = dict(RTX3050, name="NVIDIA GeForce RTX 3050 Laptop GPU", vram_mb=4096)
    assert transcribe.whisper_plan({}, status(gpus=[small]))["compute_type"] == "int8_float16"


def test_unknown_library_list_still_attempts_cuda():
    assert transcribe.whisper_plan({}, status(libs_ok=None))["device"] == "cuda"


def test_no_gpu_uses_cpu_int8():
    plan = transcribe.whisper_plan({}, NO_GPU)
    assert (plan["device"], plan["compute_type"], plan["model"]) == ("cpu", "int8", "small")
    assert "no NVIDIA CUDA GPU" in plan["reason"] and plan["fix"] == ""


def test_missing_cuda_libraries_is_cpu_with_reason_and_fix():
    plan = transcribe.whisper_plan({}, MISSING)
    assert plan["device"] == "cpu" and plan["compute_type"] == "int8"
    assert "cublas64_12.dll" in plan["reason"] and "requirements-gpu.txt" in plan["fix"]


def test_forced_settings():
    cpu = transcribe.whisper_plan({"whisper_device": "cpu"}, status())
    assert cpu["device"] == "cpu" and "Device to Auto" in cpu["reason"]
    forced = transcribe.whisper_plan({"whisper_device": "cuda"}, MISSING)
    assert forced["device"] == "cuda" and forced["fix"]  # forced GPU is always attempted


def test_unsupported_compute_type_is_replaced():
    plan = transcribe.whisper_plan({"whisper_compute_type": "float16"}, NO_GPU)
    assert plan["compute_type"] == "int8" and "not supported" in plan["note"]
    pascal = status(compute_types=["float32", "int8", "int8_float32"])
    assert transcribe.whisper_plan({}, pascal)["compute_type"] == "int8"
    assert transcribe.whisper_plan({"whisper_compute_type": "int8_float16"}, status())["compute_type"] == "int8_float16"


def test_banner_says_gpu_or_cpu_mode():
    gpu = transcribe.startup_banner({}, status())
    assert gpu[0].startswith("Transcription: GPU mode - NVIDIA GeForce RTX 3050, 6 GB (CUDA)")
    assert "large-v3-turbo, compute type float16" in gpu[1]
    cpu = transcribe.startup_banner({}, MISSING)
    assert cpu[0].startswith("Transcription: CPU mode") and any(line.strip().startswith("Fix:") for line in cpu)


def _fake_run(calls: list, fail: dict):
    def run(audio, duration, settings, model, device, compute, ctx, lo, hi, vad=True):
        calls.append((model, device, compute))
        if (device, compute) in fail:
            raise RuntimeError(fail[(device, compute)])
        return {"language": "en", "duration": 60.0, "source": f"faster-whisper:{model}:{device}", "segments": [],
                "runtime": {"model": model, "device": device, "compute_type": compute, "beam_size": 5,
                            "load_seconds": 1.0, "seconds": 5.0, "audio_seconds": 60.0, "speed": 12.0,
                            "cpu_seconds": 2.0, "started": 0.0, "ended": 5.0}}
    return run


@pytest.fixture
def gpu_present(monkeypatch):
    monkeypatch.setattr(cuda, "probe", lambda refresh=False: status())


def test_gpu_run_logs_device_and_compute(gpu_present, monkeypatch, caplog):
    calls: list = []
    monkeypatch.setattr(transcribe, "_run_whisper", _fake_run(calls, {}))
    with caplog.at_level("INFO", logger="clipfoundry"):
        out = transcribe.transcribe(Path("a.wav"), 60.0, {}, JobContext())
    assert calls == [("large-v3-turbo", "cuda", "float16")]
    assert out["runtime"]["device"] == "cuda" and out["runtime"]["warning"] == ""
    assert "Transcription starting: device=cuda compute_type=float16 model=large-v3-turbo" in caplog.text
    assert "GPU mode" in caplog.text
    assert transcribe.last_run["device"] == "cuda"


def test_cuda_failure_falls_back_to_cpu_loudly(gpu_present, monkeypatch, caplog):
    calls: list = []
    err = "Library cublas64_12.dll is not found or cannot be loaded"
    monkeypatch.setattr(transcribe, "_run_whisper", _fake_run(calls, {("cuda", "float16"): err}))
    with caplog.at_level("INFO", logger="clipfoundry"):
        out = transcribe.transcribe(Path("a.wav"), 60.0, {}, JobContext())
    assert calls == [("large-v3-turbo", "cuda", "float16"), ("small", "cpu", "int8")]  # no pointless int8 retry
    rt = out["runtime"]
    assert rt["device"] == "cpu" and "cublas64_12.dll" in rt["warning"] and "requirements-gpu.txt" in rt["fix"]
    assert "Falling back to device=cpu compute_type=int8" in caplog.text


def test_out_of_memory_retries_on_gpu_with_int8_float16(gpu_present, monkeypatch):
    calls: list = []
    oom = "CUDA failed with error out of memory"
    monkeypatch.setattr(transcribe, "_run_whisper", _fake_run(calls, {("cuda", "float16"): oom}))
    out = transcribe.transcribe(Path("a.wav"), 60.0, {"whisper_model": "large-v3"}, JobContext())
    assert calls == [("large-v3", "cuda", "float16"), ("large-v3", "cuda", "int8_float16")]
    assert out["runtime"]["compute_type"] == "int8_float16" and "out of GPU memory" in out["runtime"]["warning"]


def test_required_libraries_read_from_ctranslate2():
    if not cuda._ctranslate2_binaries():
        pytest.skip("ctranslate2 binary not found")
    libs = cuda.required_libraries()
    assert any("cublas" in lib for lib in libs), libs
    assert cuda.describe("cublas64_12.dll") == "CUDA 12 cuBLAS" and cuda.describe("cudnn64_9.dll") == "cuDNN 9"


@pytest.mark.skipif(cuda.WINDOWS or not shutil.which("cc"), reason="needs a C compiler (Linux/macOS)")
def test_check_library_preloads_from_pip_wheel_dir(tmp_path):
    lib_dir = tmp_path / "nvidia" / "fakeblas" / "lib"
    lib_dir.mkdir(parents=True)
    src = tmp_path / "f.c"
    src.write_text("int fake_blas_version(void) { return 12; }\n")
    name = "libcffakeblas.so.12"
    subprocess.run(["cc", "-shared", "-fPIC", f"-Wl,-soname,{name}", "-o", str(lib_dir / name), str(src)],
                   check=True)  # real CUDA libraries carry their soname too
    missing = cuda.check_library(name, [])
    assert not missing["ok"] and missing["error"]
    found = cuda.check_library(name, [lib_dir])
    assert found["ok"] and found["path"] == str(lib_dir / name)
    assert cuda.check_library(name, [])["ok"]  # now resolvable by name, as CTranslate2 would load it


def test_probe_without_gpu_is_cpu_mode():
    st = cuda.probe(refresh=True)
    if st["devices"]:
        pytest.skip("machine has a CUDA GPU")
    assert transcribe.whisper_plan({}, st)["mode"] == "cpu"


def test_run_whisper_reports_what_ctranslate2_loaded(monkeypatch, caplog):
    import types

    import faster_whisper

    seen = {}

    class FakeModel:
        def __init__(self, name, device, compute_type, download_root, cpu_threads):
            seen.update(device=device, compute_type=compute_type)
            self.model = types.SimpleNamespace(device=device, compute_type=compute_type)

        def transcribe(self, path, **kw):
            seen.update(kw)
            word = types.SimpleNamespace(start=0.5, end=0.9, word=" hello", probability=0.9)
            seg = types.SimpleNamespace(start=0.4, end=1.0, text=" hello", words=[word])
            return iter([seg]), types.SimpleNamespace(language="en", duration=30.0)

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    msgs: list[str] = []
    with caplog.at_level("INFO", logger="clipfoundry"):
        out = transcribe._run_whisper(Path("a.wav"), 30.0, {}, "large-v3-turbo", "cuda", "float16",
                                      JobContext(lambda f, m: msgs.append(m)), 0.0, 1.0, vad=False)
    assert seen["device"] == "cuda" and seen["compute_type"] == "float16" and seen["beam_size"] == 5
    assert seen["vad_filter"] is False and seen["vad_parameters"] is None
    assert "loaded by CTranslate2 on cuda/float16" in caplog.text
    assert any("Transcribing on GPU (cuda, float16)" in m for m in msgs)
    rt = out["runtime"]
    assert rt["device"] == "cuda" and rt["compute_type"] == "float16" and rt["audio_seconds"] == 30.0
    assert out["segments"][0]["words"][0]["w"] == "hello"


ROOT = Path(__file__).resolve().parent.parent


def test_gpu_check_command_parses():
    import sys

    out = subprocess.run([sys.executable, "-m", "clipfoundry", "--open", "gpu-check", "--help"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and "media" in out.stdout and "--seconds" in out.stdout


def test_windows_launchers_use_the_venv_and_crlf():
    bat = (ROOT / "gpu-check.bat").read_bytes()
    start = (ROOT / "start.bat").read_bytes()
    for raw in (bat, start):
        assert raw.count(b"\n") == raw.count(b"\r\n"), "Windows batch files must use CRLF line endings"
    text = bat.decode()
    assert 'call "%~dp0start.bat" --setup-only' in text  # same environment setup as the app
    assert '".venv\\Scripts\\python.exe" -m clipfoundry gpu-check %*' in text
    setup_exit = start.decode().index('if /i "%~1"=="--setup-only" exit /b 0')
    assert setup_exit < start.decode().index("-m clipfoundry --open")  # setup-only never starts the app

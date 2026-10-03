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


def test_missing_cuda_library_still_attempts_cuda_with_warning():
    # The pre-check alone must never switch to the CPU: that made gpu-check run small/cpu while CUDA was present.
    plan = transcribe.whisper_plan({}, MISSING)
    assert (plan["device"], plan["compute_type"], plan["model"]) == ("cuda", "float16", "large-v3-turbo")
    assert "cublas64_12.dll" in plan["problem"] and "requirements-gpu.txt" in plan["fix"]


def test_old_driver_is_cpu_with_reason_and_fix():
    old_driver = status(devices=0, compute_types=[], libs_ok=None, fix=cuda.DRIVER_FIX,
                        problem="NVIDIA GeForce RTX 3050 was found by the NVIDIA driver, but CUDA is not usable.")
    plan = transcribe.whisper_plan({}, old_driver)
    assert plan["device"] == "cpu" and "not usable" in plan["reason"] and plan["fix"] == cuda.DRIVER_FIX


def test_gpu_check_plan_is_the_app_plan_on_cuda():
    settings = {"whisper_model": "auto", "whisper_compute_type": "auto", "language": "en", "whisper_beam_size": 0}
    for st in (status(), MISSING, status(libs_ok=None)):
        app, check = transcribe.whisper_plan(settings, st), transcribe.whisper_plan(settings, st, device="cuda")
        assert (app["model"], app["device"], app["compute_type"]) == (check["model"], "cuda", "float16")
    forced = transcribe.whisper_plan({"whisper_device": "cpu"}, status(), device="cuda")
    assert (forced["device"], forced["model"], forced["compute_type"]) == ("cuda", "large-v3-turbo", "float16")
    assert transcribe.transcribe_options(settings, "cuda")["beam_size"] == 5


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
    warn = transcribe.startup_banner({}, MISSING)
    assert warn[0].startswith("Transcription: GPU mode") and any("Warning:" in line for line in warn)
    assert any(line.strip().startswith("Fix:") for line in warn)
    cpu = transcribe.startup_banner({}, NO_GPU)
    assert cpu[0].startswith("Transcription: CPU mode - faster-whisper small, compute type int8")


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


def test_strict_gpu_never_transcribes_on_the_cpu(gpu_present, monkeypatch):
    """Autopilot's strict GPU mode: a CUDA failure stops the transcription instead of falling back."""
    calls: list = []
    err = "Library cublas64_12.dll is not found or cannot be loaded"
    monkeypatch.setattr(transcribe, "_run_whisper", _fake_run(calls, {("cuda", "float16"): err}))
    with pytest.raises(transcribe.GpuTranscriptionFailed, match="cublas64_12.dll") as info:
        transcribe.transcribe(Path("a.wav"), 60.0, {}, JobContext(), allow_cpu_fallback=False)
    assert calls == [("large-v3-turbo", "cuda", "float16")]  # the CPU was never tried
    assert "requirements-gpu.txt" in info.value.fix


def test_strict_gpu_still_retries_on_the_gpu_after_running_out_of_memory(gpu_present, monkeypatch):
    calls: list = []
    monkeypatch.setattr(transcribe, "_run_whisper", _fake_run(calls, {("cuda", "float16"): "CUDA out of memory"}))
    out = transcribe.transcribe(Path("a.wav"), 60.0, {}, JobContext(), allow_cpu_fallback=False)
    assert calls[-1] == ("large-v3-turbo", "cuda", "int8_float16") and out["runtime"]["device"] == "cuda"


def test_strict_gpu_when_the_gpu_is_there_but_unusable(monkeypatch):
    calls: list = []
    monkeypatch.setattr(transcribe, "_run_whisper", _fake_run(calls, {}))
    broken = status(devices=0, compute_types=[], libs_ok=None, fix=cuda.DRIVER_FIX,
                    problem="NVIDIA GeForce RTX 3050 was found by the NVIDIA driver, but CUDA is not usable.")
    monkeypatch.setattr(cuda, "probe", lambda refresh=False: broken)
    with pytest.raises(transcribe.GpuTranscriptionFailed, match="not usable"):
        transcribe.transcribe(Path("a.wav"), 60.0, {}, JobContext(), allow_cpu_fallback=False)
    assert calls == []  # detection alone is not enough: nothing ran on the CPU instead
    transcribe.transcribe(Path("a.wav"), 60.0, {}, JobContext())  # the manual workflow keeps its visible fallback
    assert calls == [("small", "cpu", "int8")]
    monkeypatch.setattr(cuda, "probe", lambda refresh=False: NO_GPU)
    out = transcribe.transcribe(Path("a.wav"), 60.0, {}, JobContext(), allow_cpu_fallback=False)
    assert out["runtime"]["device"] == "cpu"  # a PC without an NVIDIA GPU: the CPU is the plan, not a fallback


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


def silent_wav(path: Path, frames: int = 1600) -> Path:
    """A WAV like the one ffmpeg_utils.extract_audio writes (16 kHz, mono, 16-bit)."""
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(b"\0\0" * frames)
    return path


def test_run_whisper_reports_what_ctranslate2_loaded(monkeypatch, caplog, tmp_path):
    import types

    import faster_whisper

    from clipfoundry.pipeline import models

    seen = {}
    monkeypatch.setattr(models, "ensure_model", lambda name, progress=None: tmp_path)

    class FakeModel:
        def __init__(self, path, device, compute_type, cpu_threads):
            seen.update(path=path, device=device, compute_type=compute_type)
            self.model = types.SimpleNamespace(device=device, compute_type=compute_type)

        def transcribe(self, path, **kw):
            seen.update(kw)
            word = types.SimpleNamespace(start=0.5, end=0.9, word=" hello", probability=0.9)
            seg = types.SimpleNamespace(start=0.4, end=1.0, text=" hello", words=[word])
            return iter([seg]), types.SimpleNamespace(language="en", duration=30.0)

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    msgs: list[str] = []
    with caplog.at_level("INFO", logger="clipfoundry"):
        out = transcribe._run_whisper(silent_wav(tmp_path / "a.wav"), 30.0, {}, "large-v3-turbo", "cuda", "float16",
                                      JobContext(lambda f, m: msgs.append(m)), 0.0, 1.0, vad=False)
    assert seen["device"] == "cuda" and seen["compute_type"] == "float16" and seen["beam_size"] == 5
    assert seen["path"] == str(tmp_path)  # WhisperModel only ever gets the verified local folder
    assert seen["vad_filter"] is False and seen["vad_parameters"] is None
    assert "loaded by CTranslate2 on cuda/float16" in caplog.text
    assert any("Transcribing on GPU (cuda, float16)" in m for m in msgs)
    rt = out["runtime"]
    assert rt["device"] == "cuda" and rt["compute_type"] == "float16" and rt["audio_seconds"] == 30.0
    assert out["segments"][0]["words"][0]["w"] == "hello"


def test_whisper_gets_the_samples_so_a_newer_pyav_cannot_break_transcription(monkeypatch, tmp_path):
    """faster-whisper decodes a file path with PyAV and passes `metadata_errors`, which PyAV 19 removed: every
    transcription on a fresh install failed with "open() got an unexpected keyword argument 'metadata_errors'".
    The app reads its own 16 kHz mono WAV and hands Whisper the samples, so PyAV is never used for it."""
    import types
    import wave

    import faster_whisper
    import numpy as np

    from clipfoundry.pipeline import models

    pcm = (np.sin(np.linspace(0, 200 * np.pi, 16000)) * 12000).astype(np.int16)
    wav = tmp_path / "audio.wav"
    with wave.open(str(wav), "wb") as w:  # what ffmpeg_utils.extract_audio writes: 16 kHz, mono, 16-bit
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(pcm.tobytes())
    monkeypatch.setattr(models, "ensure_model", lambda name, progress=None: tmp_path)
    seen = {}

    class FakeModel:
        def __init__(self, path, device, compute_type, cpu_threads):
            self.model = types.SimpleNamespace(device=device, compute_type=compute_type)

        def transcribe(self, audio, **kw):
            seen["audio"] = audio
            if not isinstance(audio, np.ndarray):  # what faster-whisper does with a path
                audio = faster_whisper.audio.decode_audio(audio)
            return iter([]), types.SimpleNamespace(language="en", duration=len(audio) / 16000)

    def pyav_19_open(*args, **kwargs):
        if "metadata_errors" in kwargs:
            raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
        raise AssertionError("PyAV should not be needed to read the app's own WAV")

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    monkeypatch.setattr(faster_whisper.audio.av, "open", pyav_19_open)
    out = transcribe._run_whisper(wav, 1.0, {}, "small", "cpu", "int8", JobContext(lambda f, m: None), 0.0, 1.0)
    audio = seen["audio"]
    assert isinstance(audio, np.ndarray) and audio.dtype == np.float32 and audio.shape == (16000,)
    assert np.array_equal(audio, pcm.astype(np.float32) / 32768.0)  # the same scaling as faster-whisper's decoder
    assert out["segments"] == [] and out["runtime"]["audio_seconds"] == 1.0


@pytest.mark.parametrize("channels,rate", [(2, 16000), (1, 44100)])
def test_a_wav_whisper_cannot_take_as_is_is_refused_plainly(tmp_path, channels, rate):
    import wave

    from clipfoundry.pipeline import audio

    wav = tmp_path / "audio.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(channels), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"\0\0" * channels * 100)
    with pytest.raises(ValueError, match="16 kHz mono"):
        audio.read_samples(wav)


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


# ---------------------------------------------------------------- gpu-check: strict CUDA, no CPU fallback
class _Loaded:
    """Stand-in for a faster-whisper model; records how gpu-check drives it."""


@pytest.fixture
def check_env(monkeypatch, tmp_path):
    from clipfoundry import db, gpucheck
    from clipfoundry.pipeline import models

    calls: dict = {"load": [], "run": []}
    (tmp_path / "model.bin").write_bytes(b"x")
    monkeypatch.setattr(transcribe, "prepare_model", lambda name, ctx=None, lo=0.0: tmp_path)
    monkeypatch.setattr(models, "is_ready", lambda name: True)
    monkeypatch.setattr(db, "get_settings", lambda: {"whisper_device": "auto", "whisper_model": "auto",
                                                     "whisper_compute_type": "auto", "language": ""})
    monkeypatch.setattr(cuda, "probe", lambda refresh=False: status())
    monkeypatch.setattr(cuda.GpuMonitor, "start", lambda self: False)

    def fake_run(model, loaded, wav, dur, settings, name, device, compute, ctx, lo=0.0, hi=1.0, vad=True):
        calls["run"].append((name, device, compute, vad))
        return {"runtime": {"model": name, "device": loaded["device"], "compute_type": loaded["compute_type"],
                            "beam_size": 5, "load_seconds": 1.0, "seconds": 2.0, "audio_seconds": 2.0,
                            "speed": 1.0, "cpu_seconds": 0.5, "started": 0.0, "ended": 2.0}}

    monkeypatch.setattr(transcribe, "run_model", fake_run)
    return gpucheck, calls, monkeypatch


def _load_as(calls, device="cuda", compute="float16", error=None):
    def load(name, dev, ct, ctx=None, lo=0.0):
        calls["load"].append((name, dev, ct))
        if error:
            raise RuntimeError(error)
        return _Loaded(), {"device": device, "compute_type": compute, "seconds": 1.0}
    return load


def test_gpu_check_passes_only_when_model_is_on_cuda(check_env, capsys):
    gpucheck, calls, mp = check_env
    mp.setattr(transcribe, "load_model", _load_as(calls))
    assert gpucheck.run(None, 2) == 0
    out = capsys.readouterr().out
    assert calls["load"] == [("large-v3-turbo", "cuda", "float16")]
    assert calls["run"] == [("large-v3-turbo", "cuda", "float16", False)]
    assert 'device="cuda", compute_type="float16"' in out and "PASS" in out


def test_gpu_check_never_falls_back_to_cpu(check_env, capsys, monkeypatch):
    gpucheck, calls, mp = check_env
    mp.setattr(transcribe, "load_model", _load_as(calls, error="Library cublas64_12.dll is not found or cannot be loaded"))
    mp.setattr(transcribe, "_run_whisper", lambda *a, **k: pytest.fail("CPU fallback path must not run"))
    assert gpucheck.run(None, 2) == 1
    out = capsys.readouterr().out
    assert calls["load"] == [("large-v3-turbo", "cuda", "float16")] and calls["run"] == []
    assert "did not initialize on CUDA" in out and "cublas64_12.dll" in out and "PASS" not in out


def test_gpu_check_fails_if_ctranslate2_reports_cpu(check_env, capsys):
    gpucheck, calls, mp = check_env
    mp.setattr(transcribe, "load_model", _load_as(calls, device="cpu", compute="int8_float32"))
    assert gpucheck.run(None, 2) == 1
    assert "not cuda" in capsys.readouterr().out and calls["run"] == []


def test_gpu_check_attempts_cuda_despite_library_precheck(check_env, capsys):
    gpucheck, calls, mp = check_env
    mp.setattr(cuda, "probe", lambda refresh=False: MISSING)
    mp.setattr(transcribe, "load_model", _load_as(calls))
    assert gpucheck.run(None, 2) == 0
    assert calls["load"] == [("large-v3-turbo", "cuda", "float16")]
    assert "pre-check warning above was wrong" in capsys.readouterr().out


def test_gpu_check_stops_at_model_files_before_touching_cuda(check_env, capsys):
    from clipfoundry.pipeline import models

    gpucheck, calls, mp = check_env

    def broken(name, ctx=None, lo=0.0):
        raise models.ModelError("Whisper model 'large-v3-turbo' is not ready (not downloaded yet)", models.NET_FIX)

    mp.setattr(transcribe, "prepare_model", broken)
    mp.setattr(transcribe, "load_model", _load_as(calls))
    assert gpucheck.run(None, 2) == 1
    out = capsys.readouterr().out
    assert "model files are not ready" in out and models.NET_FIX in out and calls["load"] == []

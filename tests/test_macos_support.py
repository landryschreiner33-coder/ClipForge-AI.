"""Platform decisions and failure paths without requiring a Mac or touching a real Keychain."""
from types import SimpleNamespace

import pytest

from clipfoundry import awake, macos_secrets, secure
from clipfoundry.pipeline import ffmpeg_utils, transcribe


def test_mac_keychain_roundtrip_authenticated_and_no_plaintext_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path))
    values = {}
    backend = SimpleNamespace(get_password=lambda service, account: values.get((service, account)),
                              set_password=lambda service, account, value: values.__setitem__((service, account), value))
    monkeypatch.setattr(macos_secrets, "_backend", lambda: backend)
    monkeypatch.setattr(secure.sys, "platform", "darwin")
    first, second = secure.seal("private-token"), secure.seal("private-token")
    assert first.startswith("keychain:v1:") and first != second
    assert "private-token" not in first and len(values) == 1
    assert secure.unseal(first) == secure.unseal(second) == "private-token"
    damaged = first[:-4] + "AAAA"
    with pytest.raises(secure.SecretError):
        secure.unseal(damaged)
    values.clear()
    with pytest.raises(secure.SecretError, match="Unlock"):
        secure.unseal(first)
    assert not values  # Reading a copied profile must not create a replacement key.
    def locked():
        raise RuntimeError("locked")
    monkeypatch.setattr(macos_secrets, "_backend", locked)
    with pytest.raises(secure.SecretError, match="protect"):
        secure.seal("private-token")


def test_mac_secret_requires_original_platform(monkeypatch):
    monkeypatch.setattr(secure.sys, "platform", "linux")
    with pytest.raises(secure.SecretError, match="original Mac"):
        secure.unseal("keychain:v1:abc:payload")


def test_mac_sleep_hold_is_one_child_and_released(monkeypatch):
    calls = []
    class Child:
        code = None
        def poll(self): return self.code
        def terminate(self): self.code = 0; calls.append("terminate")
        def wait(self, timeout): return self.code
    def spawn(args, **kwargs):
        calls.append(args)
        return Child()
    monkeypatch.setattr(awake.sys, "platform", "darwin")
    monkeypatch.setattr(awake.subprocess, "Popen", spawn)
    keeper = awake.KeepAwake()
    assert keeper.hold(True) and keeper.hold(True)
    assert len(calls) == 1 and calls[0][:3] == ["/usr/bin/caffeinate", "-i", "-w"]
    assert keeper.status(True) == "on"
    assert keeper.hold(False) is False and calls[-1] == "terminate"
    assert keeper.status(False) == "off"


def test_mac_sleep_failure_is_visible_and_retried_after_backoff(monkeypatch):
    monkeypatch.setattr(awake.sys, "platform", "darwin")
    calls = []
    def refused(*args, **kwargs):
        calls.append(1)
        raise OSError("unavailable")
    monkeypatch.setattr(awake.subprocess, "Popen", refused)
    keeper = awake.KeepAwake()
    keeper.clock = lambda: 1.0
    assert keeper.hold(True) is False and keeper.status(True) == "failed"
    assert keeper.hold(True) is False and len(calls) == 1
    keeper.clock = lambda: 100.0
    keeper.hold(True)
    assert len(calls) == 2


def test_videotoolbox_is_checked_and_explicit_failure_is_not_hidden(monkeypatch):
    monkeypatch.setattr(ffmpeg_utils, "videotoolbox_available", lambda: True)
    args, name = ffmpeg_utils.video_encoder_args({"encoder": "auto", "crf": 20})
    assert name == "h264_videotoolbox" and args[args.index("-allow_sw") + 1] == "0"
    monkeypatch.setattr(ffmpeg_utils, "videotoolbox_available", lambda: False)
    monkeypatch.setattr(ffmpeg_utils, "nvenc_available", lambda: False)
    assert ffmpeg_utils.video_encoder_args({"encoder": "auto"})[1] == "libx264"
    with pytest.raises(ffmpeg_utils.FFmpegError, match="Apple hardware"):
        ffmpeg_utils.video_encoder_args({"encoder": "videotoolbox"})


def test_apple_cpu_plan_does_not_request_cuda_install(monkeypatch):
    monkeypatch.setattr(transcribe.sys, "platform", "darwin")
    monkeypatch.setattr(transcribe.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(transcribe.cuda, "cpu_compute_types", lambda: ["int8"])
    status = {"devices": 0, "gpus": [], "ctranslate2": "test", "problem": "", "fix": ""}
    plan = transcribe.whisper_plan({}, status)
    assert plan["device"] == "cpu" and not plan["fix"] and "Apple silicon" in plan["reason"]


def test_mac_health_treats_cpu_as_supported(monkeypatch):
    from clipfoundry import gpu
    from clipfoundry.office import health
    monkeypatch.setattr(health.sys, "platform", "darwin")
    monkeypatch.setattr(gpu.manager, "status", lambda settings: {
        "available": False, "whisper": {"device": "cpu"}, "problem": ""})
    monkeypatch.setattr(transcribe, "whisper_installed", lambda: True)
    assert health.gpu({})["status"] == "healthy"
    monkeypatch.setattr(transcribe, "whisper_installed", lambda: False)
    assert health.gpu({})["status"] == "error"

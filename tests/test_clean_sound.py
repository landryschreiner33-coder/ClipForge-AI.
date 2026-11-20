"""Clean up the sound (pipeline/cleanup.py): what it decides to do, what it does to the sound (noise, hum, breaths,
uneven levels, a dead microphone channel), that the cleaned sound lines up with the picture sample for sample, the
cache, the pinned voice-model download, and how clip renders, the full-video editor and the before/after switch use it.

The voice model itself is not downloaded in tests (conftest points its address at a closed port), so these runs use
the built-in spectral noise gate; `test_the_real_voice_model` runs DeepFilterNet when its files are provided in
CLIPFORGE_TEST_DFN_DIR (the CI workflow downloads them)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from synthetic_media import needs_ffmpeg

SR = 48000
pytestmark = needs_ffmpeg


# ------------------------------------------------------------------ synthetic sound
def spoken(seconds: float, run: float = 1.6, pause: float = 0.9, start: float = 0.3) -> list[dict]:
    """Words (0.3 s each) in runs of `run` seconds with a pause between runs."""
    out, t = [], start
    while t + run < seconds:
        w = t
        while w + 0.3 <= t + run:
            out.append({"w": "word", "start": round(w, 3), "end": round(w + 0.3, 3)})
            w += 0.35
        t += run + pause
    return out


def voice(seconds: float, words: list[dict], level: float = 0.25) -> np.ndarray:
    """A buzzy voice-like sound (a gliding pitch with harmonics) only while the words are spoken."""
    t = np.arange(int(seconds * SR)) / SR
    f0 = 140 + 35 * np.sin(2 * np.pi * 0.9 * t) + 10 * np.sin(2 * np.pi * 3.1 * t)
    phase = 2 * np.pi * np.cumsum(f0) / SR
    v = sum(np.sin(h * phase) * 0.7 ** h for h in range(1, 16))
    v /= np.abs(v).max()
    env = np.zeros_like(t)
    for w in words:
        a, b = int(w["start"] * SR), int(w["end"] * SR)
        env[a:b] = np.sin(np.linspace(0, np.pi, b - a)) ** 0.5
    return level * v * env


def noise(seconds: float, level: float = 0.01, seed: int = 0) -> np.ndarray:
    return level * np.random.default_rng(seed).standard_normal(int(seconds * SR))


def hum(seconds: float, level: float = 0.01, base: float = 60.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return level * sum(np.sin(2 * np.pi * base * h * t) / h for h in (1, 2, 3, 4))


def music(seconds: float, level: float = 0.05) -> np.ndarray:
    """Sustained chords that change every second (a music bed)."""
    t = np.arange(int(seconds * SR)) / SR
    chords = [(220.0, 277.2, 329.6), (196.0, 246.9, 293.7), (174.6, 220.0, 261.6)]
    out = np.zeros_like(t)
    for k in range(int(seconds) + 1):
        sel = (t >= k) & (t < k + 1)
        for f in chords[k % 3]:
            out[sel] += sum(np.sin(2 * np.pi * f * h * t[sel]) / h for h in (1, 2, 3))
    return level * out / np.abs(out).max()


def write(path: Path, x: np.ndarray) -> Path:
    x = np.asarray(x, np.float32)
    channels = 1 if x.ndim == 1 else x.shape[1]
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", str(channels), "-i", "pipe:0",
                    str(path)], input=x.tobytes(), check=True)
    return path


def db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)) + 1e-12))


def spans(x: np.ndarray, words: list[dict], inside: bool) -> np.ndarray:
    keep = np.zeros(x.size, bool)
    for w in words:
        keep[int(w["start"] * SR):int(w["end"] * SR)] = True
    if not inside:  # pauses, away from the word edges
        grown = keep.copy()
        for w in words:
            grown[max(0, int((w["start"] - 0.15) * SR)):int((w["end"] + 0.15) * SR)] = True
        keep = ~grown
    return x[keep]


def lag(a: np.ndarray, b: np.ndarray, span: int = 400) -> int:
    n = min(a.size, b.size) - 2 * span
    return max(range(-span, span + 1), key=lambda k: float(np.dot(a[span:span + n], b[span + k:span + k + n])))


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    return tmp_path


# ------------------------------------------------------------------ what it decides
def test_auto_cleans_noisy_speech_removes_hum_and_stays_in_place(data):
    from clipfoundry.pipeline import cleanup

    words = spoken(12)
    dry = voice(12, words)
    src = write(data / "talk.wav", dry + noise(12) + hum(12))
    r = cleanup.clean(src, 0.0, 12.0, words, "auto")
    rep = r.report
    assert rep["applied"] == "gentle" and rep["denoiser"] == "gate" and rep["hum_hz"] == 60.0
    assert rep["music"] is False and rep["channel"] == "both"
    assert rep["noise_below_voice_db_after"] > rep["noise_below_voice_db_before"] + 5
    assert "60 Hz hum removed" in rep["summary"] and "simpler noise filter" in rep["summary"]
    out = np.fromfile(r.path, np.float32)
    assert out.size == 12 * SR  # exactly the range, so every cut lines up
    assert abs(lag(dry, out)) <= 10  # the hum filters' phase shift is a fraction of a millisecond
    # in a pause, the hum's harmonics are gone (relative to the voice)
    pause = slice(int(2.05 * SR), int(2.65 * SR))
    spec_in = np.abs(np.fft.rfft((dry + noise(12) + hum(12))[pause] * np.hanning(pause.stop - pause.start)))
    spec_out = np.abs(np.fft.rfft(out[pause] * np.hanning(pause.stop - pause.start)))
    freqs = np.fft.rfftfreq(pause.stop - pause.start, 1 / SR)
    ref_in, ref_out = db(spans(dry + noise(12), words, True)), db(spans(out, words, True))
    for f in (120.0, 180.0):
        k = np.abs(freqs - f) < 3
        drop = (20 * np.log10(spec_in[k].max()) - ref_in) - (20 * np.log10(spec_out[k].max()) - ref_out)
        assert drop > 15, (f, drop)


def test_auto_leaves_music_alone(data):
    from clipfoundry.pipeline import cleanup

    words = spoken(12)
    src = write(data / "song.wav", voice(12, words) + music(12) + noise(12, 0.002))
    r = cleanup.clean(src, 0.0, 12.0, words, "auto")
    assert r.path is None and r.report["applied"] is None and r.report["music"] is True
    assert r.report["summary"] == "The sound was left as it is: there is music in the background."
    # asked for explicitly, it still cleans
    assert cleanup.clean(src, 0.0, 12.0, words, "gentle").path is not None


def test_auto_leaves_sound_that_is_mostly_not_speech_or_silent(data):
    from clipfoundry.pipeline import cleanup

    src = write(data / "room.wav", noise(8))
    left = cleanup.clean(src, 0.0, 8.0, [], "auto")
    assert left.path is None and left.report["why"] == "it is mostly not speech"
    quiet = write(data / "silent.wav", np.zeros(8 * SR))
    assert cleanup.clean(quiet, 0.0, 8.0, spoken(8), "strong").report["why"] == "there is no sound to clean up"
    assert cleanup.clean(src, 0.0, 8.0, [], "off").report["applied"] is None


def test_a_dead_or_inverted_microphone_channel_is_not_mixed_in(data):
    from clipfoundry.pipeline import cleanup

    words = spoken(10)
    v = voice(10, words) + noise(10, 0.003)
    src = write(data / "left-only.wav", np.stack([v, noise(10, 0.0005, 1)], 1))
    r = cleanup.clean(src, 0.0, 10.0, words, "gentle")
    assert r.report.get("channel") == "left", r.report
    assert "left microphone channel" in r.report["summary"]
    base = {"left_db": -20.0, "right_db": -21.0}
    assert cleanup.channel_choice({**base, "correlation": 0.9})[1] == "both"
    assert cleanup.channel_choice({**base, "correlation": -0.95})[1] == "left"
    assert cleanup.channel_choice({"left_db": -50.0, "right_db": -20.0, "correlation": 0.0})[1] == "right"
    # an inverted channel would cancel the voice if the two were mixed
    inverted = write(data / "inverted.wav", np.stack([v, -v], 1))
    assert cleanup.clean(inverted, 0.0, 10.0, words, "gentle").report["channel"] in ("left", "right")


def test_quiet_and_loud_passages_are_evened_out(data):
    from clipfoundry.pipeline import cleanup

    words = spoken(16)
    loud, quiet = [w for w in words if w["start"] < 8], [w for w in words if w["start"] >= 8]
    x = voice(16, loud, 0.3) + voice(16, quiet, 0.05) + noise(16, 0.001)
    src = write(data / "uneven.wav", x)
    before = db(spans(x, loud, True)) - db(spans(x, quiet, True))
    assert before > 14
    for mode, most in (("gentle", before - 4), ("strong", before - 8)):
        out = np.fromfile(cleanup.clean(src, 0.0, 16.0, words, mode).path, np.float32)
        after = db(spans(out, loud, True)) - db(spans(out, quiet, True))
        assert abs(after) < most, (mode, before, after)


def test_breaths_in_pauses_are_softened(data):
    from clipfoundry.pipeline import cleanup

    words = spoken(12)
    x = voice(12, words) + noise(12, 0.0005)
    a = int(2.15 * SR)
    burst = np.convolve(np.random.default_rng(3).standard_normal(int(0.35 * SR)), np.ones(8) / 8, "same")
    x[a:a + burst.size] += 0.02 * burst * np.hanning(burst.size)
    src = write(data / "breath.wav", x)
    r = cleanup.clean(src, 0.0, 12.0, words, "strong")
    assert r.report["breaths_softened"] >= 1
    out = np.fromfile(r.path, np.float32)
    region = slice(a + int(0.08 * SR), a + burst.size - int(0.08 * SR))
    was = db(x[region]) - db(spans(x, words, True))
    now = db(out[region]) - db(spans(out, words, True))
    assert now < was - 6, (was, now)


# ------------------------------------------------------------------ the cache
def test_cleaned_sound_is_cached_and_redone_when_the_file_changes(data, monkeypatch):
    from clipfoundry.pipeline import cleanup

    words = spoken(8)
    src = write(data / "talk.wav", voice(8, words) + noise(8))
    first = cleanup.clean(src, 1.0, 7.0, words, "gentle")
    assert np.fromfile(first.path, np.float32).size == 6 * SR

    def boom(*a, **k):
        raise AssertionError("cleaned again")

    monkeypatch.setattr(cleanup, "_process", boom)
    again = cleanup.clean(src, 1.0, 7.0, words, "gentle")
    assert again.path == first.path and again.report["summary"] == first.report["summary"]
    with pytest.raises(AssertionError):
        cleanup.clean(src, 1.0, 7.0, words, "strong")
    write(src, voice(8, words) + noise(8, 0.02))
    os.utime(src, ns=(os.stat(src).st_atime_ns, os.stat(src).st_mtime_ns + 10**9))
    with pytest.raises(AssertionError):
        cleanup.clean(src, 1.0, 7.0, words, "gentle")


def test_a_failure_keeps_the_original_sound_and_a_cancel_stops(data, monkeypatch):
    from clipfoundry.pipeline import cleanup
    from clipfoundry.pipeline.common import Cancelled

    words = spoken(6)
    src = write(data / "talk.wav", voice(6, words) + noise(6))

    def full(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cleanup, "_process", full)
    kept = cleanup.clean_or_keep(src, 0.0, 6.0, words, "gentle")
    assert kept.path is None and kept.report["summary"] == \
        "The sound was left as it is: it could not be cleaned up on this computer."

    def stop(*a, **k):
        raise Cancelled()

    monkeypatch.setattr(cleanup, "_process", stop)
    with pytest.raises(Cancelled):
        cleanup.clean_or_keep(src, 0.0, 6.0, words, "gentle")
    assert not list((cleanup.cache_dir() / "work").glob("*"))  # no half-made files left behind


def test_the_cache_stays_under_its_size_limit(data, monkeypatch):
    from clipfoundry.pipeline import cleanup

    folder = cleanup.cache_dir()
    files = []
    for k in range(5):
        p = folder / f"k{k}.f32"
        p.write_bytes(b"\0" * 1000)
        os.utime(p, (1000 + k, 1000 + k))
        files.append(p)
    monkeypatch.setattr(cleanup, "CACHE_CAP", 2500)
    cleanup._trim_cache(files[0])
    assert [p.exists() for p in files] == [True, False, False, False, True]


# ------------------------------------------------------------------ the voice model download
class _Files(BaseHTTPRequestHandler):
    files: dict[str, bytes] = {}
    hits: list[str] = []

    def log_message(self, *a):  # noqa: D401
        pass

    def do_GET(self):  # noqa: N802
        name = self.path.rsplit("/", 1)[-1]
        self.hits.append(name)
        body = self.files.get(name)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def release(data, monkeypatch):
    from clipfoundry.pipeline import cleanup

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Files)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Files.hits = []
    monkeypatch.setattr(cleanup, "MODEL_URL", f"http://127.0.0.1:{server.server_address[1]}/model/{{file}}")
    monkeypatch.setattr(cleanup, "model_dir", lambda: data / "models" / "clean-sound")
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    yield server
    server.shutdown()


def _publish(monkeypatch, files: dict[str, bytes]) -> None:
    from clipfoundry.pipeline import cleanup

    _Files.files = files
    monkeypatch.setattr(cleanup, "MODEL_FILES", {n: (len(b), hashlib.sha256(b).hexdigest()) for n, b in files.items()})


def test_the_voice_model_is_downloaded_once_and_checked(release, monkeypatch):
    from clipfoundry.pipeline import cleanup

    _publish(monkeypatch, {"denoiser_model.onnx": b"m" * 3000, "initial_states.npz": b"s" * 200, "meta.json": b"{}"})
    folder = cleanup.ensure_model()
    assert cleanup.model_ready() and (folder / "LICENSE.txt").read_text().startswith("DeepFilterNet 3")
    assert sorted(p.name for p in folder.iterdir()) == ["LICENSE.txt", cleanup.MARKER, "denoiser_model.onnx",
                                                        "initial_states.npz", "meta.json"]
    hits = len(_Files.hits)
    cleanup.ensure_model()
    assert len(_Files.hits) == hits  # verified files are not fetched again
    # these bytes are no real model: loading fails, so cleaning falls back to the noise gate
    assert cleanup.denoiser_kind() == "gate"


def test_a_tampered_voice_model_is_refused_and_not_retried_at_once(release, monkeypatch):
    from clipfoundry.pipeline import cleanup

    _publish(monkeypatch, {"denoiser_model.onnx": b"m" * 3000, "initial_states.npz": b"s" * 200, "meta.json": b"{}"})
    _Files.files = {**_Files.files, "denoiser_model.onnx": b"x" * 3000}  # same size, other bytes
    with pytest.raises(cleanup.CleanupError, match="checksum"):
        cleanup.ensure_model()
    assert not cleanup.model_ready()
    assert not list(cleanup.model_dir().glob("*.part")) and not (cleanup.model_dir() / "denoiser_model.onnx").exists()
    hits = len(_Files.hits)
    with pytest.raises(cleanup.CleanupError, match="a moment ago"):
        cleanup.ensure_model()
    assert len(_Files.hits) == hits
    _Files.files = {**_Files.files, "denoiser_model.onnx": b"m" * 3100}  # too large
    monkeypatch.setattr(cleanup, "_failed_at", 0.0)
    with pytest.raises(cleanup.CleanupError, match="larger than expected"):
        cleanup.ensure_model()


@pytest.mark.slow
def test_the_real_voice_model(release, data, monkeypatch):
    """DeepFilterNet itself (files from CLIPFORGE_TEST_DFN_DIR, served by the stand-in release so the pinned hashes
    are checked): a pause's noise drops a lot, and the output lines up with the input."""
    from clipfoundry.pipeline import cleanup

    folder = os.environ.get("CLIPFORGE_TEST_DFN_DIR")
    if not folder:
        pytest.skip("set CLIPFORGE_TEST_DFN_DIR to a folder with the three model files")
    _Files.files = {n: Path(folder, n).read_bytes() for n in cleanup.MODEL_FILES}
    monkeypatch.setattr(cleanup, "_denoiser", None)
    assert cleanup.denoiser_kind() == "deepfilternet"
    model = cleanup._model()
    x = noise(4, 0.01).astype(np.float32)
    y = cleanup._denoise(model, x, 0.0, None)
    assert y.size == x.size and db(y[SR:]) < db(x[SR:]) - 25
    if shutil.which("espeak-ng"):
        wav = data / "dfn-speech.wav"
        subprocess.run(["espeak-ng", "-w", str(wav), "Today I want to show you how this works."], check=True)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                             capture_output=True, check=True).stdout
        speech = np.frombuffer(raw, np.float32) * 0.5
        mixed = (speech + noise(speech.size / SR, 0.005)[:speech.size]).astype(np.float32)
        assert lag(speech, cleanup._denoise(model, mixed, 0.0, None)) in (-1, 0, 1)


# ------------------------------------------------------------------ settings, renders and the editors
def test_the_setting_and_clip_edits_only_take_known_levels(data):
    from clipfoundry import config

    assert config.DEFAULT_SETTINGS["clean_sound"] == "auto"
    ok = config.validate_settings({"clean_sound": "strong"})
    assert ok["clean_sound"] == "strong"
    assert "clean_sound" not in config.validate_settings({"clean_sound": "loud"})


def _project(data: Path, seconds: float, sound: np.ndarray):
    from clipfoundry.pipeline.ffmpeg_utils import probe

    wav = write(data / "sound.wav", sound)
    src = data / "talk.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=640x360:r=25:d={seconds}",
                    "-i", str(wav), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-b:a", "192k", "-shortest", str(src)], check=True)
    meta = probe(src)
    return src, meta


def _audio(path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def test_a_clip_render_uses_the_cleaned_sound_in_sync(data):
    from clipfoundry import config
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext

    words = spoken(10)
    src, meta = _project(data, 10, voice(10, words) + noise(10, 0.01))
    project = {"source_path": str(src), "dir": str(data / "proj"), "info": meta, "options": {}, **meta}
    settings = {**config.DEFAULT_SETTINGS, "encoder": "x264", "x264_preset": "ultrafast", "silence": "off",
                "auto_zoom": False, "hook_overlay": False}
    outs = {}
    for mode in ("off", "gentle"):
        clip = {"id": f"c-{mode}", "start": 1.0, "end": 9.0, "hook": "", "edit": {"clean_sound": mode}}
        outs[mode] = render.render_clip(project, clip, words, settings, JobContext(), out_dir=data / mode)
    info = outs["gentle"]["render_info"]["audio_processing"]
    assert info["clean_sound"]["applied"] == "gentle" and info["clean_sound"]["summary"].startswith("Sound cleaned")
    assert "clean_sound" not in outs["off"]["render_info"]["audio_processing"]
    plain, cleaned = _audio(outs["off"]["output_path"]), _audio(outs["gentle"]["output_path"])
    assert abs(plain.size - cleaned.size) < SR * 0.05
    # same words at the same moments: compare loudness envelopes (10 ms) of the two renders
    env = lambda x: np.sqrt(np.convolve(x[:min(plain.size, cleaned.size)] ** 2, np.ones(480) / 480, "same"))  # noqa
    assert abs(lag(env(plain)[::48], env(cleaned)[::48], 20)) <= 1  # within 1 ms
    rel = [{**w, "start": w["start"] - 1.0, "end": w["end"] - 1.0} for w in words if w["end"] > 1.0 and w["start"] < 9.0]
    assert db(spans(cleaned, rel, False)) - db(spans(cleaned, rel, True)) < \
        db(spans(plain, rel, False)) - db(spans(plain, rel, True)) - 5


def test_the_before_and_after_switch(data, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import api, db as store

    words = spoken(10)
    src, meta = _project(data, 10, voice(10, words) + noise(10, 0.01))
    store.init()
    project = store.create_project("talk", source_path=str(src), status="ready", info=meta,
                                   **{k: meta[k] for k in ("duration", "width", "height", "fps")})
    clip = store.create_clip(project["id"], start=1.0, end=8.0, title="t", status="ready", edit={"end": 7.5})
    monkeypatch.setattr(api, "load_words", lambda p: words)
    with TestClient(api.app, base_url="http://127.0.0.1:8765") as client:
        h = {"X-ClipFoundry": "1"}
        assert client.post(f"/api/clips/{clip['id']}/sound-check", json={"mode": "off"}, headers=h).status_code == 400
        r = client.post(f"/api/clips/{clip['id']}/sound-check", json={"mode": "gentle"}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["applied"] == "gentle" and body["after"] and body["summary"].startswith("Sound cleaned")
        before = client.get(body["before"], headers=h)
        after = client.get(body["after"], headers=h)
        assert before.headers["content-type"] == after.headers["content-type"] == "audio/wav"
        (data / "b.wav").write_bytes(before.content)
        (data / "a.wav").write_bytes(after.content)
        b, a = _audio(data / "b.wav"), _audio(data / "a.wav")
        assert abs(b.size - 6.7 * SR) < SR * 0.05 and abs(a.size - b.size) < 10  # the edited trim, both the same
        rel = [{**w, "start": w["start"] - 1.0, "end": w["end"] - 1.0} for w in words if w["end"] > 1.0 and w["start"] < 7.7]
        assert abs(db(spans(a, rel, True)) - db(spans(b, rel, True))) < 1.5  # matched loudness
        assert db(spans(a, rel, False)) < db(spans(b, rel, False)) - 5  # quieter pauses
        assert client.get(f"/api/clips/{clip['id']}/sound-check/other", headers=h).status_code == 404
        # the render reuses the cleaning made for the comparison
        from clipfoundry.pipeline import cleanup
        monkeypatch.setattr(cleanup, "_process", lambda *a, **k: (_ for _ in ()).throw(AssertionError("again")))
        again = cleanup.clean(src, 1.0, 7.7, words, "gentle")
        assert again.path is not None


def test_the_full_video_editor_cleans_each_file_once(data):
    from test_studio_editor_render import _asset, _plan

    from clipfoundry.studio import engine, video_flow

    words = spoken(10)
    src, _meta = _project(data, 10, voice(10, words) + noise(10, 0.01))
    a = _asset(src, "video")
    clips = [{"id": "c1", "asset_id": a["id"], "kind": "video", "in_ms": 500, "out_ms": 4000, "label": "a",
              "gain_db": 0.0, "include": True},
             {"id": "c2", "asset_id": a["id"], "kind": "video", "in_ms": 5000, "out_ms": 9000, "label": "a",
              "gain_db": 0.0, "include": True}]
    plan = _plan(clips)
    assert engine.validate({**plan, "clean_sound": "loud"}, {a["id"]: a}) == ["Unknown sound cleanup choice."]
    plan, note = video_flow.apply_edit(plan, {"op": "set", "field": "clean_sound", "value": "strong"},
                                       {a["id"]: words}, {a["id"]: a})
    assert plan["clean_sound"] == "strong" and engine.validate(plan, {a["id"]: a}) == []
    with pytest.raises(video_flow.VideoError):
        video_flow.apply_edit(plan, {"op": "set", "field": "clean_sound", "value": "loud"}, {}, {a["id"]: a})
    info = engine.render(plan, {a["id"]: a}, {a["id"]: words}, data / "r" / "preview.mp4", preview=True)
    assert list(info["clean_sound"]) == [a["id"]] and info["clean_sound"][a["id"]]["applied"] == "strong"
    off = engine.render({**plan, "clean_sound": "off"}, {a["id"]: a}, {a["id"]: words}, data / "o" / "preview.mp4",
                        preview=True)
    assert off["clean_sound"] == {}
    # the plan's own choice wins over Settings; without one, Settings decide
    plain = engine.render({k: v for k, v in plan.items() if k != "clean_sound"}, {a["id"]: a}, {a["id"]: words},
                          data / "s" / "preview.mp4", preview=True, settings={"clean_sound": "gentle"})
    assert plain["clean_sound"][a["id"]]["applied"] == "gentle"
    cleaned, original = _audio(data / "r" / "preview.mp4"), _audio(data / "o" / "preview.mp4")
    assert abs(cleaned.size - original.size) < SR * 0.05
    env = lambda x: np.sqrt(np.convolve(x[:min(cleaned.size, original.size)] ** 2, np.ones(480) / 480, "same"))  # noqa
    assert abs(lag(env(original)[::48], env(cleaned)[::48], 20)) <= 1

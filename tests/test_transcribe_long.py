"""Long recordings are transcribed in pieces cut where nobody speaks, resumable, with one held Whisper model.

No real model: `_new_whisper` is replaced by a fake that hears one word every half second of the samples it is
given, and the machine is made CPU-only so the plan is the same everywhere.
"""
from __future__ import annotations

import json
import re
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from clipfoundry.pipeline import audio, cuda, transcribe
from clipfoundry.pipeline.common import Cancelled, JobContext, read_json

RATE = 16000
LONG_S = 3000.0  # 50 minutes: three pieces of 20 minutes
GAPS = (612.0, 1212.0, 1795.0, 2392.0)  # one second of silence centred here; 1212 and 2392 are near the cuts

CPU_ONLY = {"devices": 0, "gpus": [], "compute_types": [], "libraries": [], "libs_ok": None, "ctranslate2": "4.4.0",
            "toolkit": "", "pip_dirs": [], "problem": "", "fix": ""}


def write_tone(path: Path, seconds: float, gaps: tuple[float, ...] = ()) -> None:
    """A 16 kHz mono 16-bit WAV of a steady tone, silent for one second around each of `gaps`, written in blocks."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        block = 60 * RATE
        for first in range(0, int(seconds * RATE), block):
            n = min(block, int(seconds * RATE) - first)
            t = (np.arange(n) + first) / RATE
            x = 0.3 * np.sin(2 * np.pi * 220.0 * t)
            for gap in gaps:
                x[(t >= gap - 0.5) & (t < gap + 0.5)] = 0.0
            w.writeframes((x * 32767).astype(np.int16).tobytes())


@pytest.fixture(scope="module")
def long_wav(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("sound") / "long.wav"
    write_tone(path, LONG_S, GAPS)
    return path


class FakeWhisper:
    """Hears one word every 0.5 s of the samples it gets, in sentences of six words, with times relative to the
    samples (0-based) like faster-whisper. `repeat_seam` makes every call start and end with the same sentence."""

    def __init__(self, repeat_seam: bool = False):
        self.model = types.SimpleNamespace(device="cpu", compute_type="int8")
        self.calls: list[int] = []  # samples received by each transcribe() call
        self.repeat_seam = repeat_seam

    def transcribe(self, samples, **opts):
        self.calls.append(len(samples))
        seconds = len(samples) / RATE
        return self._segments(seconds), types.SimpleNamespace(language="en", duration=seconds)

    def _segments(self, seconds: float):
        n_words = int(seconds / 0.5)
        for first in range(0, n_words, 6):
            words = [types.SimpleNamespace(start=i * 0.5, end=i * 0.5 + 0.4, word=f" w{i}", probability=0.9)
                     for i in range(first, min(first + 6, n_words))]
            text = " ".join(w.word.strip() for w in words)
            if self.repeat_seam and (first == 0 or first + 6 >= n_words):
                text = "same sentence at the seam"
            yield types.SimpleNamespace(start=words[0].start, end=words[-1].end, text=text, words=words)


@pytest.fixture
def fake_model(monkeypatch, tmp_path):
    """A CPU-only machine with a fake Whisper; the model folder is a directory so no download is attempted."""
    monkeypatch.setattr(cuda, "probe", lambda refresh=False: dict(CPU_ONLY))
    monkeypatch.setattr(cuda, "prepare", lambda: [])
    model_dir = tmp_path / "whisper-small"
    model_dir.mkdir()
    (model_dir / "model.bin").write_bytes(b"\0")
    state = {"loads": 0, "models": []}

    def new_whisper(path, device, compute):
        state["loads"] += 1
        model = FakeWhisper(repeat_seam=state.get("repeat_seam", False))
        state["models"].append(model)
        return model

    monkeypatch.setattr(transcribe, "_new_whisper", new_whisper)
    state["settings"] = {"whisper_model": str(model_dir)}
    transcribe.release_model()
    yield state
    transcribe.release_model()


def transcribe_calls(state: dict) -> int:
    return sum(len(m.calls) for m in state["models"])


def all_words(result: dict) -> list[dict]:
    return [w for seg in result["segments"] for w in seg["words"]]


# ------------------------------------------------------------------ (h) reading ranges and finding quiet moments
def test_read_samples_returns_exactly_the_range(tmp_path):
    pcm = (np.arange(5 * RATE) % 20000 - 10000).astype(np.int16)  # a ramp: every sample is recognisable
    wav = tmp_path / "ramp.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    whole = audio.read_samples(wav)
    assert whole.dtype == np.float32 and whole.shape == (5 * RATE,)
    part = audio.read_samples(wav, 1.0, 2.5)
    assert part.shape == (int(1.5 * RATE),)
    assert np.array_equal(part, pcm[RATE:int(2.5 * RATE)].astype(np.float32) / 32768.0)
    assert np.array_equal(audio.read_samples(wav, 4.0), whole[4 * RATE:])  # open end: to the end of the file
    assert audio.read_samples(wav, 4.5, 99.0).shape == (RATE // 2,)  # clamped to the file
    assert audio.read_samples(wav, 7.0, 8.0).shape == (0,)


def test_quiet_point_finds_the_silent_gap(long_wav):
    assert abs(audio.quiet_point(long_wav, 1200.0, radius_s=30.0) - 1212.0) < 0.6
    assert abs(audio.quiet_point(long_wav, 2400.0, radius_s=30.0) - 2392.0) < 0.6
    assert abs(audio.quiet_point(long_wav, 600.0) - 612.0) < 0.6
    assert 1500.0 - 30.0 <= audio.quiet_point(long_wav, 1500.0) <= 1500.0 + 30.0  # no gap there: still in range
    assert 0.0 <= audio.quiet_point(long_wav, 2.0) <= 32.0  # clamped to the start of the file
    assert LONG_S - 32.0 <= audio.quiet_point(long_wav, LONG_S + 10.0) <= LONG_S  # and to its end


# ------------------------------------------------------------------ (a) a short file takes the single-call path
def test_short_file_is_one_call(fake_model, tmp_path):
    wav = tmp_path / "short.wav"
    write_tone(wav, 30.0)
    parts_dir = tmp_path / "transcript.parts"
    out = transcribe.transcribe_long(wav, 30.0, fake_model["settings"], JobContext(), parts_dir=parts_dir,
                                     chunk_s=1200.0)
    assert out["runtime"]["parts"] == 1 and out["runtime"]["resumed"] == 0
    assert transcribe_calls(fake_model) == 1 and fake_model["models"][0].calls == [30 * RATE]
    assert not parts_dir.exists()  # nothing to resume: no part files were made
    assert out["language"] == "en" and len(all_words(out)) == 60
    assert transcribe.last_run["parts"] == 1


def test_a_file_just_over_one_chunk_is_still_one_call(fake_model, tmp_path):
    wav = tmp_path / "medium.wav"
    write_tone(wav, 140.0)
    out = transcribe.transcribe_long(wav, 140.0, fake_model["settings"], JobContext(), parts_dir=tmp_path / "p",
                                     chunk_s=120.0)
    assert out["runtime"]["parts"] == 1 and transcribe_calls(fake_model) == 1  # up to 1.25 x chunk_s: no tiny tail


# ------------------------------------------------------------------ (b) pieces cut at the quiet points
def test_long_file_is_cut_at_the_quiet_points(fake_model, long_wav, tmp_path):
    bounds = transcribe.part_bounds(long_wav, LONG_S, 1200.0)
    assert len(bounds) == 3 and bounds[0][0] == 0.0 and bounds[-1][1] == LONG_S
    assert abs(bounds[0][1] - 1212.0) < 1.0 and abs(bounds[1][1] - 2392.0) < 1.0
    assert all(b[0] == a[1] for a, b in zip(bounds, bounds[1:]))
    assert len(transcribe.part_bounds(long_wav, LONG_S, 1400.0)) == 2  # 3000 = 1400 + 1600: the tail joins the last

    out = transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], JobContext(),
                                     parts_dir=tmp_path / "transcript.parts", chunk_s=1200.0)
    model = fake_model["models"][0]
    assert len(model.calls) == 3 and out["runtime"]["parts"] == 3 and out["runtime"]["resumed"] == 0
    assert [round(n / RATE) for n in model.calls] == [round(b - a) for a, b in bounds]
    words = all_words(out)
    assert words[0]["start"] == 0.0 and LONG_S - 1.0 <= words[-1]["start"] <= LONG_S
    assert all(a["start"] <= b["start"] for a, b in zip(words, words[1:]))  # absolute times, in order
    # the second piece's first word is at its own start in the file, not at zero
    second = next(w for w in words if w["start"] >= bounds[1][0])
    assert abs(second["start"] - bounds[1][0]) < 0.6 and words[-1]["p"] == 0.9
    assert out["language"] == "en" and out["duration"] == LONG_S
    assert out["source"].startswith("faster-whisper:") and out["runtime"]["device"] == "cpu"
    assert out["runtime"]["audio_seconds"] == LONG_S and out["runtime"]["speed"] > 0
    assert not (tmp_path / "transcript.parts").exists()  # merged: the pieces are gone


# ------------------------------------------------------------------ (c) one held model for every piece
def test_model_is_loaded_once_and_released_on_request(fake_model, long_wav, tmp_path):
    ctx = JobContext()
    transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], ctx, parts_dir=tmp_path / "a",
                               chunk_s=1200.0)
    assert fake_model["loads"] == 1
    held = transcribe.held_model()
    assert held is not None and held["device"] == "cpu" and held["compute_type"] == "int8"
    assert held["path"] == fake_model["settings"]["whisper_model"] and held["loaded"]["device"] == "cpu"
    transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], ctx, parts_dir=tmp_path / "b",
                               chunk_s=1200.0)
    assert fake_model["loads"] == 1  # the next file reuses the held model too
    transcribe.release_model()
    assert transcribe.held_model() is None
    transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], ctx, parts_dir=tmp_path / "c",
                               chunk_s=1200.0)
    assert fake_model["loads"] == 2 and transcribe.held_model() is not None


def test_a_different_model_replaces_the_held_one(fake_model, tmp_path):
    other = tmp_path / "whisper-other"
    other.mkdir()
    (other / "model.bin").write_bytes(b"\0")
    transcribe.load_model(fake_model["settings"]["whisper_model"], "cpu", "int8")
    transcribe.load_model(fake_model["settings"]["whisper_model"], "cpu", "int8")
    assert fake_model["loads"] == 1
    _, loaded = transcribe.load_model(str(other), "cpu", "int8")
    assert fake_model["loads"] == 2 and transcribe.held_model()["model"] == str(other)
    assert loaded["seconds"] >= 0 and "reused" not in loaded
    _, again = transcribe.load_model(str(other), "cpu", "int8")
    assert again["reused"] is True and again["seconds"] == 0.0


def test_a_failed_load_holds_nothing(fake_model, monkeypatch):
    def broken(path, device, compute):
        raise RuntimeError("CUDA driver version is insufficient")

    monkeypatch.setattr(transcribe, "_new_whisper", broken)
    with pytest.raises(RuntimeError, match="insufficient"):
        transcribe.load_model(fake_model["settings"]["whisper_model"], "cpu", "int8")
    assert transcribe.held_model() is None


# ------------------------------------------------------------------ (d) resume from the pieces on disk
def test_resume_transcribes_only_the_missing_piece(fake_model, long_wav, tmp_path):
    parts_dir = tmp_path / "transcript.parts"
    first = transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], JobContext(), parts_dir=parts_dir,
                                       chunk_s=1200.0, keep_parts=True)
    files = sorted(p.name for p in parts_dir.iterdir())
    assert files == ["part-0000.json", "part-0001.json", "part-0002.json"]
    saved = read_json(parts_dir / "part-0001.json")
    assert set(saved) == {"start", "end", "result"} and saved["result"]["segments"]
    (parts_dir / "part-0001.json").unlink()
    before = transcribe_calls(fake_model)

    again = transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], JobContext(), parts_dir=parts_dir,
                                       chunk_s=1200.0)
    assert transcribe_calls(fake_model) == before + 1  # only the missing piece was listened to again
    assert again["runtime"]["resumed"] == 2 and again["runtime"]["parts"] == 3
    assert [w["start"] for w in all_words(again)] == [w["start"] for w in all_words(first)]
    assert not parts_dir.exists()


def test_a_piece_saved_for_other_bounds_is_not_reused(fake_model, long_wav, tmp_path):
    parts_dir = tmp_path / "transcript.parts"
    parts_dir.mkdir()
    bounds = transcribe.part_bounds(long_wav, LONG_S, 1200.0)
    stale = {"start": 0.0, "end": bounds[0][1] + 5.0, "result": {"segments": [], "runtime": {}, "language": "xx"}}
    (parts_dir / "part-0000.json").write_text(json.dumps(stale), encoding="utf-8")
    out = transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], JobContext(), parts_dir=parts_dir,
                                     chunk_s=1200.0)
    assert out["runtime"]["resumed"] == 0 and transcribe_calls(fake_model) == 3 and out["language"] == "en"


# ------------------------------------------------------------------ (e) cancel between pieces, then resume
def test_cancel_keeps_the_finished_piece_for_the_retry(fake_model, long_wav, tmp_path):
    parts_dir = tmp_path / "transcript.parts"
    state = {"cancel_once_a_piece_is_saved": True}
    ctx = JobContext(is_cancelled=lambda: state["cancel_once_a_piece_is_saved"]
                     and (parts_dir / "part-0000.json").exists())
    with pytest.raises(Cancelled):
        transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], ctx, parts_dir=parts_dir,
                                   chunk_s=1200.0)
    assert sorted(p.name for p in parts_dir.iterdir()) == ["part-0000.json"]
    assert transcribe_calls(fake_model) == 1

    state["cancel_once_a_piece_is_saved"] = False
    out = transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], ctx, parts_dir=parts_dir,
                                     chunk_s=1200.0)
    assert out["runtime"]["resumed"] == 1 and out["runtime"]["parts"] == 3 and transcribe_calls(fake_model) == 3
    assert abs(len(all_words(out)) - LONG_S / 0.5) <= 3  # a word every half second; the cuts round a few away


# ------------------------------------------------------------------ (f) progress: the whole file on lo..hi
def test_progress_covers_the_whole_file_in_order(fake_model, long_wav, tmp_path):
    seen: list[tuple[float, str]] = []
    ctx = JobContext(report=lambda frac, msg: seen.append((frac, msg)))
    transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], ctx, parts_dir=tmp_path / "p",
                               chunk_s=1200.0, lo=0.2, hi=0.6, label="interview.mp4")
    fracs = [f for f, _ in seen]
    assert all(0.2 <= f <= 0.6 for f in fracs)
    assert all(a <= b for a, b in zip(fracs, fracs[1:]))
    positions = [m for _, m in seen if m.startswith("interview.mp4  ")]
    assert len(positions) > 100 and positions == [m for _, m in seen if "Loading Whisper" not in m]
    assert all(re.fullmatch(r"interview\.mp4  \d+:\d\d:\d\d/0:50:00", m) for m in positions)
    assert positions[0] == "interview.mp4  0:00:00/0:50:00" and positions[-1] == "interview.mp4  0:49:59/0:50:00"
    assert "interview.mp4  0:20:11/0:50:00" in positions  # the second piece starts at its quiet point, in file time
    assert abs(fracs[-1] - 0.6) < 0.001


def test_progress_without_a_label_says_transcribing(fake_model, long_wav, tmp_path):
    seen: list[str] = []
    transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], JobContext(lambda f, m: seen.append(m)),
                               parts_dir=tmp_path / "p", chunk_s=1200.0)
    assert seen[-1] == "Transcribing  0:49:59/0:50:00"


# ------------------------------------------------------------------ (g) a sentence repeated at a seam
def test_merge_drops_the_sentence_repeated_at_the_seam():
    def part(start, end, segs, resumed=False):
        rt = {"model": "m", "device": "cpu", "compute_type": "int8", "requested_device": "cpu",
              "requested_compute_type": "int8", "beam_size": 1, "load_seconds": 0.0, "seconds": 10.0,
              "audio_seconds": end - start, "speed": 1.0, "cpu_seconds": 5.0, "started": start, "ended": start + 10,
              "gpu": "", "warning": "", "fix": ""}
        p = {"start": start, "end": end, "result": {"language": "en", "duration": end - start, "source": "f",
                                                      "segments": segs, "runtime": rt}}
        if resumed:
            p["resumed"] = True
        return p

    def seg(start, end, text):
        return {"start": start, "end": end, "text": text, "words": [{"start": start, "end": end, "w": text}]}

    parts = [part(0, 100, [seg(0, 4, "hello"), seg(97, 99.8, "see you at the seam")], resumed=True),
             part(100, 200, [seg(100.2, 103, "see you at the seam"), seg(104, 106, "after"), seg(105, 107, "after")]),
             part(200, 300, [seg(205, 208, "see you at the seam"), seg(199.5, 209, "late start")])]
    out = transcribe.merge_parts(parts, 300.0)
    texts = [s["text"] for s in out["segments"]]
    assert texts == ["hello", "see you at the seam", "after", "after", "see you at the seam", "late start"]
    assert out["segments"][-1]["start"] == 205.0  # kept monotonic: never before the previous segment
    words = [w for s in out["segments"] for w in s["words"]]
    assert all(a["start"] <= b["start"] for a, b in zip(words, words[1:]))
    rt = out["runtime"]
    assert rt["parts"] == 3 and rt["resumed"] == 1 and rt["seconds"] == 30.0 and rt["audio_seconds"] == 300.0
    assert rt["speed"] == 10.0 and rt["cpu_seconds"] == 15.0 and rt["started"] == 0 and rt["ended"] == 210
    assert out["language"] == "en" and out["duration"] == 300.0


def test_seam_duplicate_is_dropped_on_the_long_path(fake_model, long_wav, tmp_path):
    fake_model["repeat_seam"] = True
    out = transcribe.transcribe_long(long_wav, LONG_S, fake_model["settings"], JobContext(), parts_dir=tmp_path / "p",
                                     chunk_s=1200.0)
    seam_sentences = [s for s in out["segments"] if s["text"] == "same sentence at the seam"]
    assert len(seam_sentences) == 2 * 3 - 2  # every piece says it twice; the repeat at each of the two seams is dropped


# ------------------------------------------------------------------ the whole-file path through the held model
def test_transcribe_keeps_its_shape_and_uses_the_held_model(fake_model, tmp_path):
    wav = tmp_path / "short.wav"
    write_tone(wav, 10.0)
    out = transcribe.transcribe(wav, 10.0, fake_model["settings"], JobContext())
    assert out["language"] == "en" and out["duration"] == 10.0 and len(out["segments"]) == 4
    assert out["runtime"]["device"] == "cpu" and out["runtime"]["warning"] == "" and "parts" not in out["runtime"]
    transcribe.transcribe(wav, 10.0, fake_model["settings"], JobContext())
    assert fake_model["loads"] == 1 and transcribe_calls(fake_model) == 2


def test_run_model_offsets_every_time_by_the_samples_position(fake_model, tmp_path):
    model, loaded = transcribe.load_model(fake_model["settings"]["whisper_model"], "cpu", "int8")
    samples = np.zeros(3 * RATE, dtype=np.float32)
    positions: list[float] = []
    out = transcribe.run_model(model, loaded, tmp_path / "none.wav", 3.0, {}, "m", "cpu", "int8", JobContext(),
                               samples=samples, offset_s=100.0, report_position=positions.append)
    words = all_words(out)
    assert words[0]["start"] == 100.0 and words[-1]["end"] == 102.9 and out["segments"][0]["start"] == 100.0
    assert positions == [102.9]  # the file position after each decoded segment, not the piece's own time

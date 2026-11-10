"""The animated short's voice (clipfoundry/makers/voice.py): real espeak-ng reading into a trimmed 48 kHz WAV, word
times estimated from the sound (pauses at the script's punctuation), aligned to heard words, and chosen from the
engine, the speech model or the estimate; the local engine and its fallback; macOS `say` and Windows SAPI commands
and voice lists (stand-in programs, nothing real runs) and their speed, set by FFmpeg after they read; unknown voices,
speed limits and cancelling.
"""
from __future__ import annotations

import math
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

SCENE = "When the rain finally stopped, the whole valley turned bright green overnight."


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.makers import local_engines, voice

    db.init()
    monkeypatch.setattr(local_engines, "module", lambda: None)  # no local engine unless a test brings one
    voice.clear_cache()
    yield tmp_path
    voice.clear_cache()


def _need_espeak():
    from clipfoundry.makers import voice

    if not voice._espeak():
        pytest.skip("espeak-ng is needed for real speech")


def _write_wav(path: Path, parts: list[tuple[str, float]], rate: int = 22050) -> Path:
    """A mono 16-bit WAV of ("tone" | "quiet", seconds) parts: a stand-in for a voice program's output."""
    chunks = []
    for kind, seconds in parts:
        n = int(round(seconds * rate))
        t = np.arange(n) / rate
        chunks.append(0.3 * np.sin(2 * np.pi * 220 * t) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t)) if kind == "tone"
                      else np.zeros(n))
    x = np.concatenate(chunks) if chunks else np.zeros(0)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def _frames_db(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate()
        x = np.frombuffer(wf.readframes(wf.getnframes()), "<i2").astype(np.float64) / 32768
    hop = rate // 100
    n = len(x) // hop
    return 20 * np.log10(np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-6), rate


def _quiet_runs(db: np.ndarray, at_least: int) -> tuple[int, int, list[tuple[int, int]]]:
    """First and last loud 10 ms frame, and the quiet runs of `at_least` frames between them."""
    loud = db > np.percentile(db[db > -100], 95) - 30
    idx = np.flatnonzero(loud)
    first, last = int(idx[0]), int(idx[-1])
    runs, k = [], first
    while k <= last:
        if loud[k]:
            k += 1
            continue
        m = k
        while m <= last and not loud[m]:
            m += 1
        if m - k >= at_least:
            runs.append((k, m))
        k = m
    return first, last, runs


def _assert_tidy(words: list[dict], length: float) -> None:
    for w in words:
        assert 0.0 <= w["start"] < w["end"] <= length + 1e-9
        assert round(w["start"], 3) == w["start"] and round(w["end"], 3) == w["end"]
    for a, b in zip(words, words[1:]):
        assert a["end"] <= b["start"] and a["start"] < b["start"]


def _stand_in_seconds(speed: float) -> float:
    """How long a stand-in program's 0.5 s of sound lasts as a voice file at `speed`: 40 ms of silence each side."""
    return 0.5 / speed + 0.08


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


# ------------------------------------------------------------------ espeak-ng, for real
def test_espeak_reads_into_a_trimmed_48k_mono_wav(env):
    _need_espeak()
    from clipfoundry.makers import voice

    out = env / "scene.wav"
    got = voice.speak(SCENE, out, voice="espeak:en-us")
    assert got["path"] == str(out) and got["engine"] == "espeak" and got["voice"] == "American man (simple voice)"
    assert got["fallback"] == "" and got["words"] is None and got["voice_id"] == "espeak:en-us"
    with wave.open(str(out), "rb") as wf:
        assert (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) == (1, 2, 48000)
        assert abs(wf.getnframes() / 48000 - got["duration_s"]) < 0.002
    # 12 words at 175 a minute is about 4 s; espeak-ng is a little quicker
    assert 2.5 < got["duration_s"] < 6.0
    db, _ = _frames_db(out)
    first, last, _ = _quiet_runs(db, 10)
    assert 3 <= first <= 5, "about 40 ms of silence before the first sound"
    assert 3 <= len(db) - 1 - last <= 5, "about 40 ms of silence after the last sound"
    assert db[:3].max() < -50 and db[-3:].max() < -50
    assert not list(env.glob(".voice-*")), "no half-written file is left beside the voice"

    fast = voice.speak(SCENE, env / "fast.wav", voice="espeak:en-us", speed=1.4)
    slow = voice.speak(SCENE, env / "slow.wav", voice="espeak:en-us", speed=0.7)
    assert fast["duration_s"] < 0.85 * got["duration_s"] < 0.85 * slow["duration_s"]


def test_the_estimate_puts_the_commas_pause_between_the_right_words(env):
    _need_espeak()
    from clipfoundry.makers import voice

    out = env / "scene.wav"
    length = voice.speak(SCENE, out, voice="espeak:en-us")["duration_s"]
    db, _ = _frames_db(out)
    first, last, runs = _quiet_runs(db, 10)
    assert len(runs) == 1, "espeak-ng pauses once, at the comma"
    pause_start, pause_end = runs[0][0] / 100, runs[0][1] / 100

    words = voice.estimate_words(out, SCENE)
    assert [w["w"] for w in words] == SCENE.split(), "the script's own tokens, punctuation and all"
    _assert_tidy(words, length)
    stopped, the = words[4], words[5]
    assert stopped["w"] == "stopped," and the["w"] == "the"
    assert abs(stopped["end"] - pause_start) <= 0.03 and abs(the["start"] - pause_end) <= 0.03
    assert all(w["end"] <= pause_start + 0.03 for w in words[:5])
    assert all(w["start"] >= pause_end - 0.03 for w in words[5:])
    # the words cover the voiced time, end to end
    assert abs(words[0]["start"] - first / 100) <= 0.03
    assert abs(words[-1]["end"] - (last + 1) / 100) <= 0.03


def test_fast_speech_still_finds_short_pauses_at_the_punctuation(env):
    _need_espeak()
    from clipfoundry.makers import voice

    text = "Octopuses have three hearts, and two of them stop when they swim. That is why they crawl."
    out = env / "fast.wav"
    length = voice.speak(text, out, voice="espeak:en-us", speed=1.4)["duration_s"]
    words = voice.estimate_words(out, text)
    _assert_tidy(words, length)
    gaps = [a["w"] for a, b in zip(words, words[1:]) if b["start"] - a["end"] >= 0.05]
    assert gaps == ["hearts,", "swim."]


def test_the_estimate_always_answers(env):
    from clipfoundry.makers import voice

    silent = _write_wav(env / "silent.wav", [("quiet", 2.0)])
    words = voice.estimate_words(silent, "Nothing at all here.")
    assert [w["w"] for w in words] == ["Nothing", "at", "all", "here."]
    _assert_tidy(words, 2.0)
    assert words[0]["start"] == 0.0 and words[-1]["end"] == 2.0

    broken = env / "broken.wav"
    broken.write_bytes(b"not a sound file")
    words = voice.estimate_words(broken, "Four words said here.")
    assert len(words) == 4 and words[-1]["end"] == pytest.approx(4 * 60 / 175, abs=0.01)

    assert voice.estimate_words(silent, "") == [] and voice.estimate_words(silent, " — ... ") == []
    tone = _write_wav(env / "tone.wav", [("quiet", 0.3), ("tone", 1.0), ("quiet", 0.4), ("tone", 1.0), ("quiet", 0.3)])
    words = voice.estimate_words(tone, "Wait — what happened here?")
    assert [w["w"] for w in words] == ["Wait", "what", "happened", "here?"], "a lone dash is not a word"
    assert words[0]["end"] == pytest.approx(1.3, abs=0.02) and words[1]["start"] == pytest.approx(1.7, abs=0.02)
    # numbers weigh what they take to say
    assert voice._weight("1999") > voice._weight("2") and voice._syllables("1999") == 5
    assert voice._syllables("3,000") == 3 and voice._syllables("3.5") == 3 and voice._syllables("FBI") == 3


# ------------------------------------------------------------------ heard words
def test_align_words_takes_the_heard_times_and_fills_the_rest(env):
    from clipfoundry.makers import voice

    text = "Octopuses have three hearts, and two of them stop."
    heard = [{"w": " Octopuses", "start": 0.10, "end": 0.70}, {"w": "have", "start": 0.70, "end": 0.90},
             # "three" was not heard; "hearts" was heard as "harts"; "um" is not in the script
             {"w": "harts,", "start": 1.20, "end": 1.50}, {"w": "um", "start": 1.55, "end": 1.65},
             {"w": "And", "start": 1.70, "end": 1.85}, {"w": "two", "start": 1.85, "end": 2.00},
             {"w": "of", "start": 2.00, "end": 2.10}, {"w": "them", "start": 2.10, "end": 2.30}]
    words = voice.align_words(text, heard)
    assert [w["w"] for w in words] == text.split()
    _assert_tidy(words, 10.0)
    by = {w["w"]: w for w in words}
    assert (by["Octopuses"]["start"], by["Octopuses"]["end"]) == (0.1, 0.7)
    assert (by["and"]["start"], by["them"]["end"]) == (1.7, 2.3)
    assert 0.9 <= by["three"]["start"] < by["three"]["end"] <= 1.2, "a missing word sits between its neighbours"
    assert (by["hearts,"]["start"], by["hearts,"]["end"]) == (1.2, 1.5), "heard differently: takes that time"
    assert by["stop."]["start"] >= 2.3 and by["stop."]["end"] > by["stop."]["start"], "the end is carried on"

    # no gap for the missing word: it takes time from both neighbours
    tight = voice.align_words("one two three", [{"w": "one", "start": 0.0, "end": 0.5},
                                                {"w": "three", "start": 0.5, "end": 1.0}])
    assert [w["w"] for w in tight] == ["one", "two", "three"]
    _assert_tidy(tight, 1.0)
    assert tight[1]["end"] - tight[1]["start"] >= 0.1
    # a missing first word, and nothing heard at all
    lead = voice.align_words("Well, here we go.", [{"w": "here", "start": 1.0, "end": 1.2},
                                                    {"w": "we", "start": 1.2, "end": 1.4},
                                                    {"w": "go", "start": 1.4, "end": 1.8}])
    assert lead[0]["w"] == "Well," and lead[0]["end"] <= 1.0 and lead[0]["start"] >= 0.0
    assert [w["w"] for w in voice.align_words("Two words.", [])] == ["Two", "words."]


def test_time_words_picks_the_engine_then_listening_then_the_estimate(env, monkeypatch):
    from clipfoundry.makers import voice
    from clipfoundry.pipeline import transcribe

    wav = _write_wav(env / "voice.wav", [("quiet", 0.04), ("tone", 0.8), ("quiet", 0.3), ("tone", 0.8),
                                         ("quiet", 0.04)], rate=48000)
    text = "Hello there, my friend."
    calls = []

    def fake_transcribe(path, duration, settings, ctx, lo=0.0, hi=1.0, vad=True, allow_cpu_fallback=True):
        with wave.open(str(path), "rb") as wf:
            calls.append({"rate": wf.getframerate(), "duration": duration, "settings": settings, "vad": vad,
                          "cpu": allow_cpu_fallback, "cancelled": ctx.cancelled()})
        return {"segments": [{"words": [{"w": "Hello", "start": 0.05, "end": 0.40, "p": 0.9},
                                        {"w": "there,", "start": 0.40, "end": 0.84},
                                        {"w": "my", "start": 1.14, "end": 1.40},
                                        {"w": "friend.", "start": 1.40, "end": 1.98}]}]}

    def no_listening(*args, **kwargs):
        raise AssertionError("listening must not run")

    monkeypatch.setattr(transcribe, "whisper_installed", lambda: True)
    monkeypatch.setattr(transcribe, "whisper_plan", lambda settings: {"model": "small", "device": "cpu"})
    monkeypatch.setattr(transcribe, "transcribe", no_listening)

    # the engine said when it spoke each word
    engine = [{"w": "hello", "start": 0.04, "end": 0.42}, {"w": "there", "start": 0.42, "end": 0.84},
              {"w": "my", "start": 1.14, "end": 1.4}, {"w": "friend", "start": 1.4, "end": 5.0}]
    words, how = voice.time_words(wav, text, engine_words=engine, settings={})
    assert how == "engine" and [w["w"] for w in words] == text.split()
    assert words[0]["start"] == 0.04 and words[-1]["end"] <= _wav_seconds(wav)

    # no speech model downloaded: listening is skipped and nothing is downloaded
    monkeypatch.setattr(transcribe, "model_cached", lambda model: False)
    used = {}
    words, how = voice.time_words(wav, text, settings={}, used=used)
    assert how == "estimated" and [w["w"] for w in words] == text.split()
    assert used == {}, "the speech model was not loaded"

    # downloaded: it listens to a 16 kHz copy without voice detection, and the heard times are used
    monkeypatch.setattr(transcribe, "model_cached", lambda model: True)
    monkeypatch.setattr(transcribe, "transcribe", fake_transcribe)
    words, how = voice.time_words(wav, text, settings={"whisper_model": "auto"},
                                  engine_words=[{"w": "something", "start": 0, "end": 1}])
    assert how == "listened" and calls[-1]["rate"] == 16000 and calls[-1]["vad"] is False
    assert calls[-1]["settings"] == {"whisper_model": "auto"} and calls[-1]["cpu"] is True
    assert [(w["w"], w["start"]) for w in words] == [("Hello", 0.05), ("there,", 0.4), ("my", 1.14),
                                                       ("friend.", 1.4)]
    assert voice.time_words(wav, text, settings={}, listen=False)[1] == "estimated"

    # a GPU plan may fall back to the CPU only when that model is downloaded too
    monkeypatch.setattr(transcribe, "whisper_plan", lambda settings: {"model": "large-v3-turbo", "device": "cuda"})
    monkeypatch.setattr(transcribe, "model_cached", lambda model: model == "large-v3-turbo")
    assert voice.time_words(wav, text, settings={})[1] == "listened" and calls[-1]["cpu"] is False

    # a failure leaves the estimate; heard words that do not match the script are not trusted; cancel stops
    monkeypatch.setattr(transcribe, "transcribe", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no GPU")))
    used = {}
    assert voice.time_words(wav, text, settings={}, used=used)[1] == "estimated"
    assert used == {"model": True}, "the model was asked (and may be loaded) though its words were not used"
    monkeypatch.setattr(transcribe, "transcribe", lambda *a, **k: {"segments": [{"words": [
        {"w": "completely", "start": 0, "end": 1}, {"w": "different", "start": 1, "end": 2}]}]})
    assert voice.time_words(wav, text, settings={})[1] == "estimated"
    from clipfoundry.pipeline.common import Cancelled

    def cancelled(*args, **kwargs):
        raise Cancelled()

    monkeypatch.setattr(transcribe, "transcribe", cancelled)
    with pytest.raises(Cancelled):
        voice.time_words(wav, text, settings={})
    monkeypatch.setattr(transcribe, "whisper_installed", lambda: False)
    assert voice.time_words(wav, text, settings={})[1] == "estimated"

    released = []
    monkeypatch.setattr(transcribe, "release_model", lambda: released.append(True))
    voice.release()
    assert released == [True]


# ------------------------------------------------------------------ the local engine
class FakeEngines:
    """A stand-in for clipfoundry.engines with a ready voice engine."""

    class EngineError(Exception):
        pass

    def __init__(self, folder: Path, ready: bool = True):
        self.folder, self.ready, self.calls, self.fail, self.extra = folder, ready, [], None, {}

    def status(self, role):
        return {"ready": self.ready and role == "voice", "engine": "Fake voice", "why": ""}

    def voices(self):
        return [{"id": "lumi", "name": "Lumi", "lang": "es-ES", "gender": "female", "about": "Spanish"},
                {"id": "nova", "name": "Nova", "lang": "en-US", "gender": "female", "about": "Warm and clear"}]

    def speak(self, text, *, voice, speed, lang, progress, cancel):
        self.calls.append({"text": text, "voice": voice, "speed": speed, "lang": lang, "cancel": cancel()})
        progress(0.5, "Reading")
        if self.fail is not None:
            raise self.fail
        path = _write_wav(self.folder / f"engine{len(self.calls)}.wav",
                          [("quiet", 0.5), ("tone", 0.6), ("quiet", 0.25), ("tone", 0.7), ("quiet", 0.6)], 24000)
        # the shape of clipfoundry.engines.speak: words as text / start_s / end_s
        return {"path": path, "duration_s": 2.65, "sample_rate": 24000, "voice": voice, "model": "Fake",
                "words": [{"text": "Hello", "start_s": 0.5, "end_s": 1.1},
                          {"text": "world", "start_s": 1.35, "end_s": 2.05}], **self.extra}


def test_the_engine_reads_and_its_word_times_follow_the_trim(env, monkeypatch):
    from clipfoundry.makers import local_engines, voice

    engines = FakeEngines(env)
    monkeypatch.setattr(local_engines, "module", lambda: engines)
    listing = voice.voices()
    ids = [v["id"] for v in listing]
    assert ids[:3] == ["auto", "engine:nova", "engine:lumi"], "auto first, then the engine's, English first"
    assert listing[0]["engine"] == "engine" and "Nova" in listing[0]["about"]
    assert listing[1] == {"id": "engine:nova", "name": "Nova", "lang": "en-US", "gender": "female",
                          "about": "Warm and clear", "engine": "engine"}
    assert voice.default_voice() == "engine:nova"

    out = env / "engine.wav"
    got = voice.speak("Hello world", out, speed=2.0, lang="en")
    assert got["engine"] == "engine" and got["voice"] == "Nova" and got["fallback"] == ""
    assert engines.calls[-1] == {"text": "Hello world", "voice": "nova", "speed": 1.4, "lang": "en", "cancel": False}
    with wave.open(str(out), "rb") as wf:
        assert (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) == (1, 2, 48000)
    # 0.5 s of lead silence became 0.04 s: the engine's word times moved with it
    assert got["words"][0] == {"w": "Hello", "start": pytest.approx(0.04, abs=0.011),
                               "end": pytest.approx(0.64, abs=0.011)}
    assert got["duration_s"] == pytest.approx(0.04 + 1.55 + 0.04, abs=0.02)
    words, how = voice.time_words(out, "Hello world!", engine_words=got["words"], listen=False)
    assert how == "engine" and [w["w"] for w in words] == ["Hello", "world!"]

    assert voice.speak("Hola", env / "es.wav", lang="es")["voice"] == "Lumi", "auto picks the asked language"
    assert got["rule"] == ""
    # the engine's own file is named, for the short to keep with the voice made from it
    assert got["original"] == str(env / f"engine{1}.wav") and Path(got["original"]).is_file()

    # times the engine only estimated give way to listening or the estimate from the sound; a licence's rule for
    # what the voice makes travels with it, so the short can show it
    engines.extra = {"word_timing": "estimated", "rule": "Label   what this voice makes as machine-generated."}
    got = voice.speak("Hello world", env / "estimated.wav")
    assert got["words"] is None and got["rule"] == "Label what this voice makes as machine-generated."


def test_engine_problems_fall_back_to_this_computers_voice(env, monkeypatch):
    _need_espeak()
    from clipfoundry.makers import local_engines, voice

    engines = FakeEngines(env)
    monkeypatch.setattr(local_engines, "module", lambda: engines)
    used = "“American man (simple voice)”"

    engines.fail = engines.EngineError("the voice model is missing")
    got = voice.speak("Hello there.", env / "a.wav", voice="engine:nova")
    assert got["engine"] == "espeak" and got["voice_id"] == "espeak:en-us"
    assert got["fallback"] == (f"The local voice engine could not read this, so ClipForge used {used} instead. "
                               "The engine said: The voice model is missing.")

    engines.fail = OSError(2, "No such file", "/models/nova.onnx")
    got = voice.speak("Hello there.", env / "b.wav")
    assert got["fallback"] == f"The local voice engine could not read this, so ClipForge used {used} instead."
    assert "/models" not in got["fallback"]

    engines.fail = KeyError("a fault inside the engine")
    assert voice.speak("Hello there.", env / "c.wav")["engine"] == "espeak"

    engines.fail = None
    monkeypatch.setattr(engines, "speak", lambda text, **kw: {"path": None})
    got = voice.speak("Hello there.", env / "d.wav")
    assert got["fallback"].startswith("The local voice engine did not make a sound file, so ClipForge used")

    engines.ready = False
    voice.clear_cache()
    got = voice.speak("Hello there.", env / "e.wav", voice="engine:nova")
    assert got["fallback"] == f"The local voice engine is not ready, so ClipForge used {used} instead."


def test_cancel_is_checked_before_and_after_the_engine(env, monkeypatch):
    from clipfoundry.makers import local_engines, voice
    from clipfoundry.pipeline.common import Cancelled

    engines = FakeEngines(env)
    monkeypatch.setattr(local_engines, "module", lambda: engines)
    with pytest.raises(Cancelled):
        voice.speak("Hello world", env / "x.wav", cancel=lambda: True)
    assert engines.calls == []

    flag = {"stop": False}
    real = engines.speak

    def speak_then_cancel(text, **kw):
        result = real(text, **kw)
        flag["stop"] = True  # the owner pressed Cancel while the engine read
        return result

    monkeypatch.setattr(engines, "speak", speak_then_cancel)
    with pytest.raises(Cancelled):
        voice.speak("Hello world", env / "x.wav", cancel=lambda: flag["stop"])
    assert not (env / "x.wav").exists()


# ------------------------------------------------------------------ macOS and Windows (stand-in programs)
SAY_LIST = """Albert              en_US    # Hello! My name is Albert.
Alex                en_US    # Most people recognize me by my voice.
Amélie              fr_CA    # Bonjour! Je m’appelle Amélie.
Bad News            en_US    # Hello! My name is Bad News.
Daniel              en_GB    # Hello! My name is Daniel.
Eddy (English (US)) en_US    # Hello! My name is Eddy.
Fiona               en-scotland # Hello! My name is Fiona.
Samantha            en_US    # Hello! My name is Samantha.
Zarvox              en_US    # Hello! My name is Zarvox.
Zoe (Enhanced)      en_US    # Hello! My name is Zoe.
"""


class FakePrograms:
    """Stands in for the voice programs: answers the listings and writes a sound file where the program would."""

    def __init__(self, folder: Path, listing: str = ""):
        self.folder, self.listing, self.calls = folder, listing, []

    def __call__(self, args, *, timeout, cancel=None, env=None):
        self.calls.append({"args": list(args), "env": dict(env or {}), "timeout": timeout})
        out = ""
        if args[1:] == ["-v", "?"] or (len(args) > 4 and "GetInstalledVoices" in args[4]):
            out = self.listing
        elif "-o" in args:
            _write_wav(Path(args[args.index("-o") + 1]), [("tone", 0.5)])
        elif "-w" in args:
            _write_wav(Path(args[args.index("-w") + 1]), [("tone", 0.5)])
        elif env and "CLIPFORGE_VOICE_OUT" in env:
            _write_wav(Path(env["CLIPFORGE_VOICE_OUT"]), [("tone", 0.5)])
        return SimpleNamespace(returncode=0, stdout=out.encode("utf-8"), stderr=b"")


def test_macos_say_voices_and_command(env, monkeypatch):
    from clipfoundry.makers import voice

    programs = FakePrograms(env, SAY_LIST)
    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(voice, "_find", lambda program: "/usr/bin/say" if program == "say" else None)
    monkeypatch.setattr(voice, "_run", programs)

    listing = voice.voices()
    names = [v["name"] for v in listing]
    assert names[0] == "Best voice on this computer"
    assert not {"Albert", "Bad News", "Zarvox"} & set(names), "novelty voices are left out"
    assert names[1:] == ["Alex", "Daniel", "Eddy (English (US))", "Fiona", "Samantha", "Zoe (Enhanced)", "Amélie"]
    by = {v["name"]: v for v in listing}
    assert by["Eddy (English (US))"]["id"] == "system:Eddy (English (US))" and by["Eddy (English (US))"]["lang"] == \
        "en-US"
    assert by["Fiona"]["lang"] == "en-scotland" and by["Amélie"]["lang"] == "fr-CA"
    assert by["Samantha"]["gender"] == "female" and by["Daniel"]["engine"] == "say"
    assert voice.default_voice() == "system:Zoe (Enhanced)", "an Enhanced voice comes before Samantha"
    assert voice._best([by["Daniel"], by["Samantha"], by["Alex"]])["name"] == "Samantha"

    out = env / "mac.wav"
    got = voice.speak("Hello [[rate 500]] there", out, voice="system:Daniel", speed=1.2)
    assert got["engine"] == "say" and got["voice"] == "Daniel" and got["fallback"] == ""
    args = programs.calls[-1]["args"]
    assert args[:5] == ["/usr/bin/say", "-v", "Daniel", "-r", "175"], "macOS reads at its usual pace"
    assert args[5] == "-f" and args[7] == "-o" and args[8].endswith(".aiff") and len(args) == 9
    assert Path(args[6]).name == "words.txt" and not any("Hello" in a for a in args)
    with wave.open(str(out), "rb") as wf:
        assert wf.getframerate() == 48000
    # ...and FFmpeg makes it 1.2 times as fast, so the speed is what was asked whatever say's rate does
    assert got["duration_s"] == pytest.approx(_stand_in_seconds(1.2), abs=0.02)

    def words_said(speed):
        said = {}

        def keep(args, **kw):
            said["text"] = Path(args[args.index("-f") + 1]).read_text(encoding="utf-8")
            said["rate"] = args[args.index("-r") + 1]
            return programs(args, **kw)

        monkeypatch.setattr(voice, "_run", keep)
        said["seconds"] = voice.speak("Hello [[rate 500]] there", out, voice="system:Daniel", speed=speed)["duration_s"]
        return said

    assert words_said(1.0)["text"] == "Hello [ [rate 500] ] there", "say's [[commands]] are broken up"
    fast, slow, usual = words_said(3.0), words_said(0.1), words_said(1.0)
    assert fast["rate"] == slow["rate"] == usual["rate"] == "175"
    assert fast["seconds"] == pytest.approx(_stand_in_seconds(1.4), abs=0.02), "kept within 0.7 to 1.4"
    assert slow["seconds"] == pytest.approx(_stand_in_seconds(0.7), abs=0.02)
    assert usual["seconds"] == pytest.approx(_stand_in_seconds(1.0), abs=0.02)


def test_macos_without_enhanced_voices_prefers_samantha(env, monkeypatch):
    from clipfoundry.makers import voice

    listing = "\n".join(line for line in SAY_LIST.splitlines() if "Enhanced" not in line)
    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(voice, "_find", lambda program: "/usr/bin/say" if program == "say" else None)
    monkeypatch.setattr(voice, "_run", FakePrograms(env, listing))
    assert voice.default_voice() == "system:Samantha"


def test_windows_sapi_voices_and_command(env, monkeypatch):
    from clipfoundry.makers import voice

    listing = ("\ufeffMicrosoft David Desktop|en-US|Male\r\nMicrosoft Hedda Desktop|de-DE|Female\r\n"
               "Microsoft Zira Desktop|en-US|Female\r\n")
    programs = FakePrograms(env, listing)
    powershell = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(voice, "_find", lambda program: powershell if program == "powershell" else None)
    monkeypatch.setattr(voice, "_run", programs)

    listing = voice.voices()
    assert [v["id"] for v in listing] == ["auto", "system:Microsoft David Desktop", "system:Microsoft Zira Desktop",
                                          "system:Microsoft Hedda Desktop"]
    assert listing[2]["gender"] == "female" and listing[2]["engine"] == "sapi" and listing[3]["lang"] == "de-DE"
    assert programs.calls[0]["args"][:4] == [powershell, "-NoProfile", "-NonInteractive", "-Command"]
    assert voice.default_voice() == "system:Microsoft Zira Desktop"

    text = "Héllo there, \"friend\"; $(Remove-Item x) & more"
    said = {}

    def keep(args, **kw):
        if kw.get("env"):
            said["text"] = Path(kw["env"]["CLIPFORGE_VOICE_TEXT"]).read_text(encoding="utf-8")
        return programs(args, **kw)

    monkeypatch.setattr(voice, "_run", keep)
    got = voice.speak(text, env / "win.wav", voice="system:Microsoft David Desktop", speed=1.4)
    assert got["engine"] == "sapi" and got["voice"] == "Microsoft David Desktop"
    call = programs.calls[-1]
    assert call["args"] == [powershell, "-NoProfile", "-NonInteractive", "-Command", voice.SAPI_SPEAK]
    assert '"' not in voice.SAPI_SPEAK and '"' not in voice.SAPI_LIST, "fixed scripts, single quotes only"
    assert not any("Héllo" in a or "David" in a for a in call["args"]), "words and voice stay off the command line"
    env_vars = call["env"]
    assert env_vars["CLIPFORGE_VOICE_NAME"] == "Microsoft David Desktop"
    assert said["text"] == text and Path(env_vars["CLIPFORGE_VOICE_TEXT"]).name == "words.txt"
    assert env_vars["CLIPFORGE_VOICE_OUT"].endswith(".wav")
    # Windows reads at its usual pace (its rate has only whole steps) and FFmpeg sets the speed afterwards
    assert "CLIPFORGE_VOICE_RATE" not in env_vars and "Rate" not in voice.SAPI_SPEAK
    assert got["duration_s"] == pytest.approx(_stand_in_seconds(1.4), abs=0.02)

    def seconds(speed):
        return voice.speak("Hi", env / "w.wav", voice="system:Microsoft David Desktop", speed=speed)["duration_s"]

    assert seconds(0.7) == pytest.approx(_stand_in_seconds(0.7), abs=0.02)
    assert seconds(1.0) == pytest.approx(_stand_in_seconds(1.0), abs=0.02)
    calm, lively, fast = seconds(0.95), seconds(1.05), seconds(1.15)
    assert calm > lively + 0.03 and lively > fast + 0.03, "the shorts' Calm, Lively and Fast all sound different"


# ------------------------------------------------------------------ choices, limits and failures
def test_unknown_voices_fall_back_with_a_plain_reason(env):
    _need_espeak()
    from clipfoundry.makers import voice

    used = "“American man (simple voice)”"
    got = voice.speak("Hello there.", env / "a.wav", voice="system:Nobody")
    assert got["engine"] == "espeak" and got["voice_id"] == "espeak:en-us"
    assert got["fallback"] == f"The voice you picked is not on this computer, so ClipForge used {used} instead."
    got = voice.speak("Hello there.", env / "b.wav", voice="engine:nova")
    assert got["fallback"] == f"The local voice engine is not ready, so ClipForge used {used} instead."
    assert voice.speak("Hello there.", env / "c.wav", voice="espeak:en-gb+f3")["voice"] == \
        "British woman (simple voice)"
    assert voice.speak("Hello there.", env / "d.wav", voice=None)["fallback"] == ""


def test_speed_is_kept_within_its_limits(env, monkeypatch):
    from clipfoundry.makers import voice

    programs = FakePrograms(env)
    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(voice, "_find", lambda program: "/usr/bin/espeak-ng" if program == "espeak-ng" else None)
    monkeypatch.setattr(voice, "_run", programs)
    rates = []
    for speed in (0.1, 0.7, 1.0, 1.2, 1.4, 9, "fast", float("nan"), None):
        got = voice.speak("Hello there.", env / "s.wav", voice="espeak:en-us", speed=speed)
        args = programs.calls[-1]["args"]
        assert args[:5] == ["/usr/bin/espeak-ng", "-b", "1", "-v", "en-us"] and args[7] == "-f" and args[9] == "-w"
        rates.append(args[args.index("-s") + 1])
        # espeak-ng reads at the speed asked itself (measured even), so FFmpeg leaves its sound as it is
        assert got["duration_s"] == pytest.approx(_stand_in_seconds(1.0), abs=0.02)
    assert rates == ["122", "122", "175", "210", "245", "245", "175", "175", "175"]
    assert voice._speed(math.inf) == 1.0


def test_a_hanging_voice_program_is_stopped_by_cancel(env, monkeypatch):
    from clipfoundry.makers import voice
    from clipfoundry.pipeline.common import Cancelled

    script = env / "espeak-ng"
    script.write_text("#!/bin/sh\nif [ \"$1\" = \"--voices\" ]; then\n"
                      "  echo 'Pty Language Age/Gender VoiceName File Other Languages'\n"
                      "  echo ' 2  en-us --/M English_(America) gmw/en-US (en 3)'\n  exit 0\nfi\nexec sleep 30\n")
    script.chmod(0o755)
    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(voice, "_find", lambda program: str(script) if program == "espeak-ng" else None)
    assert [v["id"] for v in voice.voices()] == ["auto", "espeak:en-us", "espeak:en-us+f3"]
    began = time.monotonic()
    with pytest.raises(Cancelled):
        voice.speak("Hello there.", env / "c.wav", cancel=lambda: time.monotonic() - began > 0.3)
    assert time.monotonic() - began < 5.0 and not (env / "c.wav").exists()


def test_no_voice_at_all_says_what_to_do(env, monkeypatch):
    from clipfoundry.makers import voice

    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(voice, "_find", lambda program: None)
    listing = voice.voices()
    assert [v["id"] for v in listing] == ["auto"] and listing[0]["engine"] == ""
    assert voice.default_voice() == ""
    with pytest.raises(voice.VoiceError) as caught:
        voice.speak("Hello there.", env / "x.wav")
    assert str(caught.value).startswith("No voice is available on this computer. Install espeak-ng")
    with pytest.raises(voice.VoiceError) as caught:
        voice.speak(" 🎉 ✨ ", env / "x.wav")
    assert str(caught.value) == "There are no words to read. Write what the voice should say, then try again."

    # a voice that is there but does not work
    voice.clear_cache()
    monkeypatch.setattr(voice, "_find", lambda program: "/usr/bin/espeak-ng" if program == "espeak-ng" else None)
    monkeypatch.setattr(voice, "_run", lambda args, **kw: SimpleNamespace(returncode=1, stdout=b"", stderr=b"boom"))
    with pytest.raises(voice.VoiceError) as caught:
        voice.speak("Hello there.", env / "x.wav")
    assert str(caught.value).startswith("No voice is available on this computer that could read these words. "
                                        "“American man (simple voice)” did not work on this computer.")


def test_the_voice_list_is_kept_for_ten_minutes(env, monkeypatch):
    from clipfoundry.makers import local_engines, voice

    programs = FakePrograms(env, SAY_LIST)
    clock = {"now": 1000.0}
    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(voice, "_find", lambda program: "/usr/bin/say" if program == "say" else None)
    monkeypatch.setattr(voice, "_run", programs)
    monkeypatch.setattr(voice, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    first = voice.voices()
    first[1]["name"] = "changed by the caller"
    clock["now"] += 599
    assert voice.voices()[1]["name"] == "Alex" and len(programs.calls) == 1, "kept, and callers get copies"
    clock["now"] += 2
    voice.voices()
    assert len(programs.calls) == 2, "looked up again after ten minutes"
    voice.clear_cache()
    voice.voices()
    assert len(programs.calls) == 3
    monkeypatch.setattr(local_engines, "module", lambda: FakeEngines(env))
    assert voice.voices()[1]["id"] == "engine:nova", "an engine that became ready shows at once"


def test_spoken_text_leaves_out_emoji_but_the_words_keep_the_script(env):
    from clipfoundry.makers import voice

    assert voice._speakable("This is crazy 🤯🤯!\nRight?  30° and 5% off") == "This is crazy !\nRight? 30° and 5% off" \
        .replace("\n", " ")
    assert voice._speakable("co\u00adoperate 👍🏽 ok") == "cooperate ok"
    tone = _write_wav(env / "t.wav", [("quiet", 0.04), ("tone", 1.0), ("quiet", 0.04)])
    assert [w["w"] for w in voice.estimate_words(tone, "So crazy🤯 right 🎉")] == ["So", "crazy🤯", "right"]


def test_auto_reads_with_engine_voices_that_speak_every_language(env, monkeypatch):
    from clipfoundry.makers import local_engines, voice

    engines = FakeEngines(env)
    # the real engine lists its voices like this: one model for every language
    engines.voices = lambda: [{"id": "F1", "name": "Sarah", "lang": "multilingual", "gender": "female"},
                              {"id": "M1", "name": "Tom", "lang": "mul", "gender": "male"}]
    engines.extra = {"word_timing": "estimated"}
    monkeypatch.setattr(local_engines, "module", lambda: engines)
    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(voice, "_find", lambda program: "/usr/bin/espeak-ng" if program == "espeak-ng" else None)
    monkeypatch.setattr(voice, "_run", FakePrograms(env))
    listing = voice.voices()
    assert voice.default_voice() == "engine:F1"
    assert listing[0]["engine"] == "engine" and "Sarah" in listing[0]["about"]
    got = voice.speak("Hello world", env / "m.wav")
    assert (got["engine"], got["voice_id"], got["fallback"]) == ("engine", "engine:F1", "")
    assert got["words"] is None, "its word times are only estimated: the sound or the speech model times them"
    assert voice._auto_order(listing, "fr")[0]["id"] == "engine:F1", "it reads French too"


def test_the_settings_hint_only_names_a_place_that_exists(env, monkeypatch):
    from clipfoundry.makers import local_engines, voice

    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(voice, "_find", lambda program: None)
    with pytest.raises(voice.VoiceError) as caught:  # this ClipForge has no local makers: Settings has no such place
        voice.speak("Hello there.", env / "x.wav")
    assert "Settings" not in str(caught.value) and str(caught.value).endswith("(for example: sudo apt install "
                                                                             "espeak-ng).")
    assert "Settings" not in voice.voices()[0]["about"]
    voice.clear_cache()
    monkeypatch.setattr(local_engines, "module", lambda: FakeEngines(env, ready=False))
    with pytest.raises(voice.VoiceError) as caught:
        voice.speak("Hello there.", env / "x.wav")
    assert str(caught.value).endswith("or download the voice in ClipForge's Settings → Pictures, video, voice.")


def test_a_failed_voice_listing_is_looked_up_again_soon(env, monkeypatch):
    from clipfoundry.makers import voice

    programs = FakePrograms(env, SAY_LIST)
    clock = {"now": 1000.0}
    fails = [True]

    def listing(args, **kw):
        if fails:  # a cold start of the voice program that does not answer in time
            fails.pop()
            programs.calls.append({"args": list(args)})
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"timed out")
        return programs(args, **kw)

    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(voice, "_find", lambda program: "/usr/bin/say" if program == "say" else None)
    monkeypatch.setattr(voice, "_run", listing)
    monkeypatch.setattr(voice, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    assert [v["id"] for v in voice.voices()] == ["auto"]
    clock["now"] += 10
    voice.voices()
    assert len(programs.calls) == 1, "not asked again at once"
    clock["now"] += 25
    assert voice.voices()[1]["name"] == "Alex" and len(programs.calls) == 2, "asked again after half a minute"
    clock["now"] += 300
    voice.voices()
    assert len(programs.calls) == 2, "a listing that worked is kept for ten minutes"


def test_brackets_in_the_words_are_never_voice_commands(env, monkeypatch):
    from clipfoundry.makers import voice

    programs = FakePrograms(env, SAY_LIST)
    said = []

    def keep(args, **kw):
        if "-f" in args:
            said.append(Path(args[args.index("-f") + 1]).read_text(encoding="utf-8"))
        return programs(args, **kw)

    monkeypatch.setattr(voice, "_run", keep)
    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(voice, "_find", lambda program: "/usr/bin/espeak-ng" if program == "espeak-ng" else None)
    words = "Say [[like this]] and [[[[slnc 3000]]]] or [one] now"
    voice.speak(words, env / "e.wav", voice="espeak:en-us")  # espeak-ng reads [[...]] as phoneme codes
    voice.clear_cache()
    monkeypatch.setattr(voice, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(voice, "_find", lambda program: "/usr/bin/say" if program == "say" else None)
    voice.speak(words, env / "s.wav", voice="system:Daniel")  # say acts on [[...]] commands
    assert said == ["Say [ [like this] ] and [ [ [ [slnc 3000] ] ] ] or [one] now"] * 2

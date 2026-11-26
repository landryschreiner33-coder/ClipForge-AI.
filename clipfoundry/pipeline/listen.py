"""ClipForge AI listens to the whole sound track (docs/clipforge/WATCH_AND_LISTEN.md).

Until now ClipForge "heard" a reaction when the sound got louder while nobody spoke: a laugh, but also a door, a
song, a car or a mouse click. This module names the sounds instead. YAMNet (Google, Apache-2.0; 521 sound classes
from AudioSet) runs over every 0.96 s of the 16 kHz track made for transcription, one window every 0.48 s, on the
CPU through ONNX Runtime. The network ships inside ClipForge (clipfoundry/assets/models/yamnet.onnx, 7.5 MB, built
from Google's own weights by scripts/export_yamnet.py), so nothing is downloaded and nothing leaves the computer. An
hour of sound takes about a minute.

The 521 classes are read as a few kinds a video editor cares about (GROUPS): speech, laughter, applause, cheering,
screaming, a gasp, crying, singing, music, booms (explosions, gunshots, fireworks), crashes, engines, alarms, animals,
sound effects and silence. For each window the strongest class of each kind is kept, and runs above a kind's
threshold become events ("laughter 0:42-0:45"). What the rest of ClipForge reads:

* `reaction_runs`: laughter, applause, cheering, screaming or a gasp where nobody speaks: the clip's payoff and the
  part of it a cut must keep. Music, engines and noise are no longer mistaken for a reaction.
* `features`: what is heard inside a clip (the deep analysis' bounded "heard" adjustment, the "Why" of a clip).
* `notes`: a short line per stretch for the model reading the transcript ("[heard: laughter, applause]").
* `top_sounds`: the most likely sounds in any stretch, for ClipForge AI's answers about a video.

Every result is cached next to the project (sounds.json) and is an estimate from the sound alone.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import logging
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .. import config
from .common import JobContext, read_json, write_json

log = logging.getLogger("clipfoundry.pipeline.listen")

MODEL = config.ASSETS_DIR / "models" / "yamnet.onnx"
CLASS_MAP = config.ASSETS_DIR / "models" / "yamnet_class_map.csv"
MODEL_SHA256 = "f609c3257468bb4c6300799849570c510242c7271ba5840a5ac7592a7d7cc3a5"
VERSION = 2
SETTING = "ai_listen"

# YAMNet's own feature settings (research/audioset/yamnet/params.py)
SR = 16000
WIN = 400                  # 25 ms
STEP = 160                 # 10 ms
NFFT = 512
BANDS = 64
MEL_LO, MEL_HI = 125.0, 7500.0
LOG_OFFSET = 0.001
PATCH = 96                 # log-mel frames per window (0.96 s)
PATCH_STEP = 48            # 0.48 s
HOP = PATCH_STEP * STEP / SR          # seconds between windows
SPAN = ((PATCH - 1) * STEP + WIN) / SR  # seconds one window hears (0.975)
PATCH_SAMPLES = (PATCH - 1) * STEP + WIN
CHUNK = 512                # windows decoded and run together (about four minutes of sound)
BATCH = 128
TOP = 5                    # classes kept per window for "what does it sound like here"

GROUPS: dict[str, tuple[str, ...]] = {
    "speech": ("Speech", "Child speech, kid speaking", "Conversation", "Narration, monologue", "Whispering"),
    "laughter": ("Laughter", "Baby laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"),
    "applause": ("Applause", "Clapping"),
    "cheering": ("Cheering", "Crowd", "Whoop", "Children shouting", "Chant"),
    "screaming": ("Screaming", "Shout", "Yell", "Bellow"),
    "gasp": ("Gasp",),
    "crying": ("Crying, sobbing", "Baby cry, infant cry", "Whimper", "Wail, moan"),
    "singing": ("Singing", "Choir", "Rapping", "Child singing", "Synthetic singing", "Humming", "Yodeling"),
    "music": ("Music",),
    "boom": ("Explosion", "Gunshot, gunfire", "Machine gun", "Fusillade", "Artillery fire", "Cap gun", "Fireworks",
             "Firecracker", "Boom", "Burst, pop", "Bang", "Eruption"),
    "crash": ("Smash, crash", "Breaking", "Shatter", "Glass", "Slam", "Thump, thud", "Crack", "Crushing"),
    "engine": ("Vehicle", "Engine", "Race car, auto racing", "Accelerating, revving, vroom", "Skidding",
               "Tire squeal", "Motorcycle", "Aircraft", "Helicopter", "Jet engine"),
    "alarm": ("Siren", "Alarm", "Smoke detector, smoke alarm", "Fire alarm", "Car alarm", "Buzzer",
              "Police car (siren)", "Ambulance (siren)", "Fire engine, fire truck (siren)", "Civil defense siren"),
    # named animals only: the catch-all "Animal" and "Wild animals" also fire on drones, buzzing and robot noises
    "animal": ("Dog", "Bark", "Cat", "Meow", "Bird", "Roar", "Growling", "Howl", "Livestock, farm animals, "
               "working animals", "Horse"),
    "effects": ("Sound effect", "Whoosh, swoosh, swish", "Boing", "Zing", "Beep, bleep", "Video game music"),
    "silence": ("Silence",),
}
THRESHOLD = {"speech": 0.5, "laughter": 0.22, "applause": 0.3, "cheering": 0.3, "screaming": 0.25, "gasp": 0.2,
             "crying": 0.25, "singing": 0.35, "music": 0.4, "boom": 0.25, "crash": 0.25, "engine": 0.4,
             "alarm": 0.3, "animal": 0.4, "effects": 0.3, "silence": 0.6}
REACTIONS = ("laughter", "applause", "cheering", "screaming", "gasp")   # a crowd or a person answering a moment
EXCITING = ("boom", "crash", "screaming", "cheering")                    # something happens
WORDS = {"speech": "speech", "laughter": "laughter", "applause": "applause", "cheering": "cheering",
         "screaming": "screaming or shouting", "gasp": "a gasp", "crying": "crying", "singing": "singing",
         "music": "music", "boom": "an explosion or gunshot", "crash": "a crash", "engine": "an engine",
         "alarm": "an alarm or siren", "animal": "an animal", "effects": "a sound effect", "silence": "silence"}
NOTE_KINDS = ("laughter", "applause", "cheering", "screaming", "gasp", "crying", "singing", "boom", "crash", "alarm",
              "animal")   # what a line of transcript is annotated with (speech and music are said separately)
REACTION_MIN = 0.4         # a wordless reaction this long counts (as virality.REACTION_MIN)


# ------------------------------------------------------------------ the model
class _Model:
    def __init__(self) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, min(4, (__import__("os").cpu_count() or 2) - 1))
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(MODEL), opts, providers=["CPUExecutionProvider"])
        self.names = class_names()
        index = {n: k for k, n in enumerate(self.names)}
        self.members = {g: [index[n] for n in names if n in index] for g, names in GROUPS.items()}

    def run(self, patches: np.ndarray) -> np.ndarray:
        out = [self.session.run(["scores"], {"patches": patches[k:k + BATCH]})[0]
               for k in range(0, len(patches), BATCH)]
        return np.concatenate(out) if out else np.zeros((0, len(self.names)), np.float32)


_lock = threading.Lock()
_model: _Model | None = None
_problem = ""


def class_names() -> list[str]:
    with open(CLASS_MAP, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return [r[2] for r in rows[1:]]


def _load() -> _Model | None:
    global _model, _problem
    with _lock:
        if _model is not None or _problem:
            return _model
        try:
            if not MODEL.is_file():
                raise FileNotFoundError("the sound model is missing from this installation")
            got = hashlib.sha256(MODEL.read_bytes()).hexdigest()
            if got != MODEL_SHA256:
                raise ValueError("the sound model file is not the one ClipForge ships")
            _model = _Model()
        except Exception as exc:  # noqa: BLE001 - listening is a bonus: loudness alone decides without it
            _problem = str(exc) or exc.__class__.__name__
            log.warning("sound model unavailable: %s", _problem)
        return _model


def enabled(settings: dict | None = None) -> bool:
    return bool((settings or {}).get(SETTING, True))


def usable(settings: dict | None = None) -> bool:
    """The setting is on and the model loads on this computer."""
    return enabled(settings) and _load() is not None


def problem() -> str:
    _load()
    return _problem


def reset_for_tests() -> None:
    global _model, _problem
    with _lock:
        _model, _problem = None, ""


# ------------------------------------------------------------------ features (as YAMNet's features.py)
_MEL: np.ndarray | None = None


def _hz_to_mel(f: np.ndarray) -> np.ndarray:
    return 1127.0 * np.log1p(np.asarray(f, dtype=np.float64) / 700.0)


def mel_matrix() -> np.ndarray:
    """tf.signal.linear_to_mel_weight_matrix(64, 257, 16000, 125, 7500): HTK mel, the DC bin left out."""
    global _MEL
    if _MEL is None:
        lin = np.linspace(0.0, SR / 2.0, NFFT // 2 + 1)[1:]
        m = _hz_to_mel(lin)[:, None]
        edges = np.linspace(_hz_to_mel(MEL_LO), _hz_to_mel(MEL_HI), BANDS + 2)
        lo, mid, hi = edges[:-2], edges[1:-1], edges[2:]
        w = np.maximum(0.0, np.minimum((m - lo) / (mid - lo), (hi - m) / (hi - mid)))
        _MEL = np.vstack([np.zeros((1, BANDS)), w]).astype(np.float32)
    return _MEL


def log_mel(x: np.ndarray) -> np.ndarray:
    """[frames, 64] log mel spectrogram of 16 kHz samples (periodic Hann window, magnitude, no padding)."""
    if len(x) < WIN:
        return np.zeros((0, BANDS), np.float32)
    n = 1 + (len(x) - WIN) // STEP
    idx = np.arange(WIN)[None, :] + STEP * np.arange(n)[:, None]
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(WIN) / WIN)).astype(np.float32)
    spec = np.abs(np.fft.rfft(x[idx] * win, n=NFFT, axis=1)).astype(np.float32)
    return np.log(spec @ mel_matrix() + LOG_OFFSET)


def patch_count(samples: int) -> int:
    """How many windows YAMNet makes of a track this long (it pads with silence to whole windows)."""
    return 1 + max(0, -(-(samples - PATCH_SAMPLES) // (PATCH_STEP * STEP)))


def patches(x: np.ndarray, first: int, count: int) -> np.ndarray:
    """Windows first .. first+count-1 of a whole track whose samples `x` start at window `first`'s first sample."""
    need = (count - 1) * PATCH_STEP * STEP + PATCH_SAMPLES
    if len(x) < need:
        x = np.concatenate([x, np.zeros(need - len(x), np.float32)])
    lm = log_mel(x[:need].astype(np.float32))
    idx = np.arange(PATCH)[None, :] + PATCH_STEP * np.arange(count)[:, None]
    return lm[idx]


# ------------------------------------------------------------------ what was heard
def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def _unb64(s: str, dtype, shape=None) -> np.ndarray:
    a = np.frombuffer(base64.b64decode(s.encode("ascii")), dtype=dtype)
    return a.reshape(shape) if shape is not None else a


@dataclass
class Heard:
    """The sounds of one recording, one row per 0.48 s window (window k hears k·0.48 .. k·0.48+0.975 s)."""
    duration: float
    groups: dict[str, np.ndarray]           # kind -> strongest member's score per window (0-1)
    top_ids: np.ndarray                      # [windows, TOP] class ids, most likely first
    top_scores: np.ndarray                   # [windows, TOP] their scores (0-1)
    names: list[str] = field(default_factory=class_names)
    events: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.events:
            self.events = find_events(self.groups)

    @property
    def n(self) -> int:
        return len(self.top_ids)

    def _range(self, t0: float, t1: float) -> tuple[int, int]:
        """Windows whose middle lies in [t0, t1] (at least the one nearest t0)."""
        a = int(np.ceil((t0 - SPAN / 2) / HOP - 1e-9))
        b = int(np.floor((t1 - SPAN / 2) / HOP + 1e-9)) + 1
        a, b = max(0, a), min(self.n, b)
        if b <= a:
            k = min(self.n - 1, max(0, int(round((t0 - SPAN / 2) / HOP))))
            return k, k + 1
        return a, b

    def level(self, kind: str, t0: float, t1: float) -> float:
        a, b = self._range(t0, t1)
        g = self.groups.get(kind)
        return float(g[a:b].max()) if g is not None and b > a else 0.0

    def share(self, kind: str, t0: float, t1: float) -> float:
        """The part of [t0, t1] where `kind` is heard above its threshold."""
        a, b = self._range(t0, t1)
        g = self.groups.get(kind)
        return float((g[a:b] >= THRESHOLD[kind]).mean()) if g is not None and b > a else 0.0

    def events_in(self, t0: float, t1: float, kinds: tuple[str, ...] | None = None) -> list[dict]:
        return [e for e in self.events if e["end"] > t0 and e["start"] < t1 and (kinds is None or e["kind"] in kinds)]

    def reaction_runs(self, t0: float, t1: float, words: list[dict] | None = None,
                      kinds: tuple[str, ...] = REACTIONS) -> list[tuple[float, float]]:
        """Stretches in [t0, t1) where a reaction (laughter, applause, cheering, screaming, a gasp; or `kinds`) is
        heard and nobody speaks, at least REACTION_MIN long: (start, end) in seconds."""
        out: list[tuple[float, float]] = []
        spoken = sorted((float(w["start"]), float(w["end"])) for w in (words or [])
                        if float(w["end"]) > t0 and float(w["start"]) < t1)
        for e in sorted(self.events_in(t0, t1, kinds), key=lambda e: e["start"]):
            a, b = max(t0, e["start"]), min(t1, e["end"])
            pieces = [(a, b)]
            for ws, we in spoken:
                nxt = []
                for pa, pb in pieces:
                    if we <= pa or ws >= pb:
                        nxt.append((pa, pb))
                        continue
                    if ws > pa:
                        nxt.append((pa, ws))
                    if we < pb:
                        nxt.append((we, pb))
                pieces = nxt
            out += [(round(pa, 2), round(pb, 2)) for pa, pb in pieces if pb - pa >= REACTION_MIN]
        merged: list[tuple[float, float]] = []
        for a, b in sorted(out):
            if merged and a <= merged[-1][1] + 0.05:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        return merged

    def top_sounds(self, t0: float, t1: float, n: int = 4, floor: float = 0.15) -> list[tuple[str, float]]:
        """The most likely sounds in [t0, t1] (by their strongest window), "Speech" and "Music" included."""
        a, b = self._range(t0, t1)
        best: dict[int, float] = {}
        for ids, sc in zip(self.top_ids[a:b], self.top_scores[a:b]):
            for i, s in zip(ids, sc):
                if s >= floor and s > best.get(int(i), 0.0):
                    best[int(i)] = float(s)
        order = sorted(best.items(), key=lambda kv: -kv[1])[:n]
        return [(self.names[i] if 0 <= i < len(self.names) else str(i), round(s, 2)) for i, s in order]

    def features(self, t0: float, t1: float) -> dict:
        """What is heard in a clip: kinds, shares and events (small, stored with the clip)."""
        dur = max(0.1, t1 - t0)
        ev = self.events_in(t0, t1 + 3.0)   # a reaction just after the end belongs to the clip (virality.REACTION_AFTER)
        kinds = {}
        for e in ev:
            if e["start"] >= t1 and e["kind"] not in REACTIONS:
                continue
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        react = [e for e in ev if e["kind"] in REACTIONS]
        last = [e for e in react if e["end"] >= t1 - min(8.0, 0.35 * dur)]
        first = [e for e in react if e["start"] <= t0 + 1.0 and e["end"] > t0]
        return {"speech": round(self.share("speech", t0, t1), 2), "music": round(self.share("music", t0, t1), 2),
                "silence": round(self.share("silence", t0, t1), 2), "events": kinds,
                "reactions": len(react), "ends_on_reaction": bool(last), "opens_on_reaction": bool(first),
                "exciting": sum(1 for e in ev if e["kind"] in EXCITING and e["start"] < t1),
                "moments": [{"kind": e["kind"], "at": round(e["start"] - t0, 1), "peak": e["peak"]}
                            for e in ev if e["kind"] in NOTE_KINDS][:8],
                "sounds": [n for n, _ in self.top_sounds(t0, t1, 5)],
                "estimated": "named from the sound by YAMNet (an estimate)"}

    def note(self, t0: float, t1: float) -> str:
        """A few words for a model reading the transcript: what else is heard in [t0, t1]."""
        kinds = []
        for e in self.events_in(t0, t1, NOTE_KINDS):
            if WORDS[e["kind"]] not in kinds:
                kinds.append(WORDS[e["kind"]])
        if self.share("music", t0, t1) >= 0.5:
            kinds.append("music")
        return ", ".join(kinds[:4])

    def to_json(self) -> dict:
        return {"version": VERSION, "duration": round(self.duration, 3), "hop": HOP, "span": SPAN,
                "windows": self.n, "groups": {k: _b64(np.round(v * 255).astype(np.uint8)) for k, v in
                                               self.groups.items()},
                "top_ids": _b64(self.top_ids.astype(np.uint16)), "top_scores": _b64(
                    np.round(self.top_scores * 255).astype(np.uint8)), "events": self.events}

    @staticmethod
    def from_json(d: dict) -> "Heard | None":
        try:
            n = int(d["windows"])
            groups = {k: _unb64(v, np.uint8).astype(np.float32) / 255.0 for k, v in d["groups"].items()}
            if any(len(g) != n for g in groups.values()):
                return None
            return Heard(float(d["duration"]), groups, _unb64(d["top_ids"], np.uint16, (n, TOP)).astype(np.int32),
                         _unb64(d["top_scores"], np.uint8, (n, TOP)).astype(np.float32) / 255.0,
                         events=list(d.get("events") or []) or [])
        except (KeyError, TypeError, ValueError):
            return None


def find_events(groups: dict[str, np.ndarray]) -> list[dict]:
    """Runs of windows above a kind's threshold (continuing while above 60% of it, gaps of one window bridged), as
    {kind, start, end, peak}. Speech and silence are not events (they are read as shares)."""
    events: list[dict] = []
    for kind, g in groups.items():
        if kind in ("speech", "silence"):
            continue
        thr = THRESHOLD[kind]
        k, n = 0, len(g)
        while k < n:
            if g[k] < thr:
                k += 1
                continue
            a = k
            j = k
            while j + 1 < n and (g[j + 1] >= 0.6 * thr or (j + 2 < n and g[j + 2] >= thr)):
                j += 1
            peak = float(g[a:j + 1].max())
            if kind != "music" or j - a >= 3:   # music: at least about two seconds
                events.append({"kind": kind, "start": round(a * HOP, 2), "end": round(j * HOP + SPAN, 2),
                               "peak": round(peak, 2)})
            k = j + 1
    events.sort(key=lambda e: (e["start"], e["kind"]))
    return events


def _wav_info(wav: Path) -> tuple[int, int]:
    with wave.open(str(wav), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getframerate() != SR or wf.getsampwidth() != 2:
            raise ValueError(f"{wav.name} is not 16 kHz mono 16-bit audio")
        return wf.getnframes(), wf.getframerate()


def _key(wav: Path) -> dict:
    st = wav.stat()
    return {"version": VERSION, "model": MODEL_SHA256[:16], "size": st.st_size, "mtime": int(st.st_mtime)}


def analyze(wav: Path | str, ctx: JobContext | None = None, cache: Path | None = None,
            progress: Callable[[float], None] | None = None, settings: dict | None = None) -> Heard | None:
    """Listen to the whole 16 kHz track. None when the setting is off, the model cannot run here or the file cannot
    be read (callers then go by loudness alone, as before)."""
    wav = Path(wav)
    if not enabled(settings) or not wav.is_file():
        return None
    key = _key(wav)
    if cache is not None and cache.is_file():
        saved = read_json(cache, {}) or {}
        if saved.get("key") == key:
            heard = Heard.from_json(saved.get("heard") or {})
            if heard is not None:
                return heard
    model = _load()
    if model is None:
        return None
    try:
        frames, _ = _wav_info(wav)
    except (OSError, ValueError, wave.Error) as exc:
        log.warning("listen: %s", exc)
        return None
    total = patch_count(frames)
    scores_groups = {g: np.zeros(total, np.float32) for g in GROUPS}
    top_ids = np.zeros((total, TOP), np.int32)
    top_sc = np.zeros((total, TOP), np.float32)
    step = PATCH_STEP * STEP
    with wave.open(str(wav), "rb") as wf:
        for first in range(0, total, CHUNK):
            if ctx:
                ctx.check()
            count = min(CHUNK, total - first)
            wf.setpos(min(frames, first * step))
            raw = wf.readframes((count - 1) * step + PATCH_SAMPLES)
            x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            sc = model.run(patches(x, first, count))
            for g, idx in model.members.items():
                if idx:
                    scores_groups[g][first:first + count] = sc[:, idx].max(axis=1)
            order = np.argsort(-sc, axis=1)[:, :TOP]
            top_ids[first:first + count] = order
            top_sc[first:first + count] = np.take_along_axis(sc, order, axis=1)
            if progress:
                progress((first + count) / total)
    heard = Heard(frames / SR, scores_groups, top_ids, top_sc, names=model.names)
    if cache is not None:
        try:
            write_json(cache, {"key": key, "heard": heard.to_json()})
        except OSError as exc:
            log.warning("listen: could not keep the result: %s", exc)
    return heard


def load(cache: Path) -> Heard | None:
    """What an earlier run heard, without listening again (None when there is nothing usable)."""
    saved = read_json(cache, {}) or {}
    return Heard.from_json(saved.get("heard") or {}) if saved else None


def stamp(t: float) -> str:
    t = int(max(0.0, t))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"

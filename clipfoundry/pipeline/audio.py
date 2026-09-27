"""Loudness envelope of the extracted 16 kHz mono track (fast, streaming)."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

HOP = 0.1  # seconds per envelope frame


def loudness_envelope(wav_path: Path, hop: float = HOP) -> dict:
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        hop_n = max(1, int(sr * hop))
        chunk_frames = hop_n * 600  # one minute per read
        out: list[np.ndarray] = []
        rest = np.zeros(0, dtype=np.float32)
        while True:
            raw = wf.readframes(chunk_frames)
            if not raw:
                break
            x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if ch > 1:
                x = x.reshape(-1, ch).mean(axis=1)
            x = np.concatenate([rest, x])
            n = len(x) // hop_n
            if n:
                frames = x[: n * hop_n].reshape(n, hop_n)
                out.append(np.sqrt(np.mean(frames * frames, axis=1) + 1e-12))
            rest = x[n * hop_n:]
    rms = np.concatenate(out) if out else np.zeros(1, dtype=np.float32)
    db = 20.0 * np.log10(rms + 1e-6)
    return {"hop": hop, "db": np.round(db, 1).tolist()}


class Loudness:
    """Prefix-sum accelerated queries over the loudness envelope."""

    def __init__(self, env: dict):
        self.hop = float(env.get("hop", HOP))
        db = np.asarray(env.get("db") or [-60.0], dtype=np.float64)
        self.db = db
        speech = db[db > -45.0]
        ref = speech if len(speech) > 20 else db
        self.median = float(np.median(ref))
        self.std = float(np.std(ref)) or 1.0
        z = (db - self.median) / self.std
        self.z = z
        self._c1 = np.concatenate([[0.0], np.cumsum(z)])
        self._c2 = np.concatenate([[0.0], np.cumsum(z * z)])

    def _idx(self, t: float) -> int:
        return int(min(len(self.db), max(0, round(t / self.hop))))

    def stats(self, t0: float, t1: float) -> tuple[float, float]:
        """Mean and std of the z-scored loudness in [t0, t1)."""
        a, b = self._idx(t0), self._idx(t1)
        if b <= a:
            return 0.0, 0.0
        n = b - a
        s1 = self._c1[b] - self._c1[a]
        s2 = self._c2[b] - self._c2[a]
        mean = s1 / n
        var = max(0.0, s2 / n - mean * mean)
        return float(mean), float(var ** 0.5)

    def spread_db(self, t0: float, t1: float) -> float | None:
        """Loud-vs-quiet spread in [t0, t1] (90th minus 10th percentile, dB): a rough speech-to-background ratio."""
        a, b = self._idx(t0), self._idx(t1)
        if b - a < 10:
            return None
        seg = self.db[a:b]
        return float(np.percentile(seg, 90) - np.percentile(seg, 10))

    def quietest(self, t0: float, t1: float) -> float:
        """Time of the quietest frame in [t0, t1] (used to snap cut points)."""
        a, b = self._idx(t0), self._idx(t1)
        if b <= a + 1:
            return (t0 + t1) / 2
        k = int(np.argmin(self.db[a:b]))
        return (a + k) * self.hop + self.hop / 2

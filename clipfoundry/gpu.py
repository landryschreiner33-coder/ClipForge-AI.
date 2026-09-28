"""GPU resource manager.

An RTX 3050 has 4-8 GB of memory: two Whisper models, or Whisper next to a local LLM, can exhaust it. This manager

* lets only one heavy GPU operation run at a time, across the app and the autopilot worker process (lock file),
* makes autopilot work wait until enough GPU memory is free (another program may be using it),
* reports GPU availability, the job holding the GPU, the jobs waiting for it, and the last transcription (device
  actually used, and any fallback, which is never silent),
* leaves CPU work (discovery, scheduling, metadata) free to run at the same time.

It wraps calls into the existing transcription code (`pipeline/transcribe.py`) without changing how that code picks
the device, compute type or model.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator

from . import locks
from .pipeline import cuda
from .pipeline.common import Cancelled

HEAVY_LOCK = "gpu-heavy"
CUDA_WORDS = ("cuda", "cublas", "cudnn", "out of memory", "ctranslate2", "nvidia", "gpu")


class GpuBusy(RuntimeError):
    """The GPU (or enough of its memory) did not become free in time."""


def _state():
    from .autopilot import state  # late import: autopilot.state imports db, which imports config only

    return state


def is_cuda_error(exc: BaseException) -> bool:
    return any(w in str(exc).lower() for w in CUDA_WORDS)


class GpuManager:
    def __init__(self) -> None:
        self._local = threading.local()
        self._mem: tuple[float, dict | None] = (0.0, None)
        self._mem_lock = threading.Lock()

    # -------------------------------------------------------------- memory
    def memory(self, max_age: float = 3.0) -> dict | None:
        """Used/free GPU memory from the NVIDIA driver (None without an NVIDIA GPU)."""
        with self._mem_lock:
            at, cached = self._mem
            if time.monotonic() - at < max_age:
                return cached
            exe = cuda.nvidia_smi_path()
            mem = None
            if exe:
                try:
                    out = subprocess.run([exe, "--query-gpu=memory.used,memory.total,utilization.gpu",
                                          "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                         timeout=10, creationflags=cuda.NO_WINDOW).stdout
                    used, total, util = (float(x) for x in out.splitlines()[0].split(",")[:3])
                    mem = {"used_mb": int(used), "total_mb": int(total), "free_mb": int(total - used),
                           "utilization": int(util)}
                except (OSError, subprocess.SubprocessError, ValueError, IndexError):
                    mem = None
            self._mem = (time.monotonic(), mem)
            return mem

    # -------------------------------------------------------------- the lock
    @contextmanager
    def heavy(self, kind: str, label: str = "", job_id: str = "", cancelled: Callable[[], bool] | None = None,
              need_free_mb: int = 0, max_wait_s: float | None = None,
              on_wait: Callable[[str], None] | None = None) -> Iterator[None]:
        """Hold the GPU for one heavy operation (transcription, a local LLM call...)."""
        if getattr(self._local, "depth", 0):  # already held by this thread
            yield
            return
        cancelled = cancelled or (lambda: False)
        st = _state()
        me = {"kind": kind, "label": label[:120], "job_id": job_id, "pid": os.getpid(), "since": time.time()}
        wait_key = f"gpu:wait:{os.getpid()}:{threading.get_ident()}"
        lock = locks.named(HEAVY_LOCK)
        t0 = time.monotonic()
        st.put(wait_key, me)
        try:
            first = True
            while not lock.acquire(timeout=0 if first else 2.0, cancelled=cancelled):
                first = False
                if cancelled():
                    raise Cancelled()
                holder = st.get("gpu:holder") or {}
                if max_wait_s is not None and time.monotonic() - t0 > max_wait_s:
                    raise GpuBusy(f"The GPU stayed busy with {holder.get('kind', 'another job')} for "
                                  f"{max(1, int(max_wait_s // 60))} minute(s).")
                if on_wait:
                    busy = f"{holder.get('kind', 'another job')}: {holder.get('label', '')}".rstrip(": ")
                    on_wait(f"Waiting for the GPU ({busy})")
        finally:
            st.delete(wait_key)
        try:
            if need_free_mb:
                self._wait_for_memory(need_free_mb, t0, max_wait_s, cancelled, on_wait)
            st.put("gpu:holder", {**me, "since": time.time()})
            self._local.depth = 1
            yield
        except Exception as exc:
            if is_cuda_error(exc):
                st.put("gpu:last_error", {"kind": kind, "label": label, "error": str(exc)[:500], "at": time.time()})
            raise
        finally:
            self._local.depth = 0
            st.delete("gpu:holder")
            lock.release()

    def _wait_for_memory(self, need_mb: int, t0: float, max_wait_s: float | None, cancelled: Callable[[], bool],
                         on_wait: Callable[[str], None] | None) -> None:
        while True:
            mem = self.memory(max_age=0)
            if mem is None or mem["free_mb"] >= need_mb:
                return
            if max_wait_s is not None and time.monotonic() - t0 > max_wait_s:
                raise GpuBusy(f"Only {mem['free_mb']} MB of GPU memory was free (needs {need_mb} MB); another "
                              "program is probably using the GPU.")
            if on_wait:
                on_wait(f"Waiting for GPU memory: {mem['free_mb']} MB free, {need_mb} MB needed")
            for _ in range(10):
                if cancelled():
                    raise Cancelled()
                time.sleep(0.5)

    # -------------------------------------------------------------- reporting
    def record_transcription(self, runtime: dict, label: str = "") -> None:
        """Remember what the last transcription actually ran on. A CPU fallback becomes a visible action item."""
        st = _state()
        info = {k: runtime.get(k) for k in ("model", "device", "compute_type", "requested_device", "speed",
                                            "audio_seconds", "seconds", "warning", "fix", "gpu")}
        info.update(label=label, at=time.time())
        st.put("gpu:last_transcription", info)
        fell_back = runtime.get("requested_device") == "cuda" and runtime.get("device") != "cuda"
        if fell_back or runtime.get("warning"):
            st.action("gpu:fallback", "gpu", "GPU transcription did not run as configured",
                      runtime.get("warning") or "Transcription ran on the CPU instead of the GPU.",
                      runtime.get("fix") or "Run gpu-check.bat for a diagnosis.", level="warning")
        elif runtime.get("device") == "cuda":
            st.resolve("gpu:fallback")

    def status(self, settings: dict) -> dict:
        from .pipeline import transcribe

        st = _state()
        probe = cuda.probe()
        plan = transcribe.whisper_plan(settings, probe)
        holder = st.get("gpu:holder")
        if holder and not locks.named(HEAVY_LOCK).held_elsewhere():
            holder = None  # left behind by a process that ended
        waiters = sorted(st.get_many("gpu:wait:").values(), key=lambda w: w.get("since", 0))
        return {
            "available": probe["devices"] > 0, "name": plan["gpu"], "vram_mb": plan["vram_mb"],
            "memory": self.memory(), "libs_ok": probe["libs_ok"], "problem": plan["problem"], "fix": plan["fix"],
            "mode": plan["mode"], "whisper": {"model": plan["model"], "device": plan["device"],
                                              "compute_type": plan["compute_type"], "reason": plan["reason"]},
            "busy": bool(holder), "holder": holder, "waiting": waiters,
            "last_transcription": st.get("gpu:last_transcription"), "last_error": st.get("gpu:last_error"),
            "min_free_mb": int(settings.get("gpu_min_free_vram_mb") or 0),
        }


manager = GpuManager()

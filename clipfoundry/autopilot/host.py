"""The worker host: one thread per worker, a lease heartbeat, periodic jobs and crash recovery.

The host runs either in its own process (`python -m clipfoundry workers`, started and watched by the app) or as
threads inside the app. Only one host runs at a time (a lock file decides), and all coordination goes through the
SQLite queue, so the app, the host and a restarted host always agree on what is left to do.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
from typing import Callable

from .. import config, db, locks
from ..pipeline import common as pipeline_common
from ..pipeline.common import log
from . import queue, state

MANUAL_PRIORITY = 100          # jobs started by a user action run even while Autopilot is off
POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 15.0
APP_HEARTBEAT_STALE = 60.0     # a managed worker process exits when the app stops beating for this long

Handler = Callable[["Job"], "dict | None"]
HANDLERS: dict[str, Handler] = {}
MAINTENANCE_STEPS: list[Callable[["Job"], "dict | None"]] = []  # e.g. the 30-day YouTube data rule (scout.py)


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return register


# ------------------------------------------------------------------ handler context
class Job:
    """What a handler gets: the job row, progress/log helpers and cooperative cancellation."""

    def __init__(self, row: dict, owner: str, host: "WorkerHost | None" = None):
        self.row = row
        self.id: str = row["id"]
        self.kind: str = row["kind"]
        self.worker: str = row["worker"]
        self.payload: dict = row.get("payload") or {}
        self.owner = owner
        self.host = host
        self.cancel_event = threading.Event()
        self.timed_out = False
        self._last_progress = 0.0

    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check(self) -> None:
        if self.cancel_event.is_set():
            raise queue.Canceled()

    def progress(self, fraction: float | None = None, message: str | None = None, stage: str | None = None,
                 force: bool = False) -> None:
        now = time.monotonic()
        if force or stage is not None or now - self._last_progress >= 0.5 or (fraction or 0) >= 1.0:
            self._last_progress = now
            queue.progress(self.id, fraction, message, stage)
            if self.host and (message or stage):
                self.host.set_state(self.worker, "working", self, stage=stage, message=message)

    def log(self, event: str, message: str = "", level: str = "info", **data: object) -> None:
        queue.log_line(self.id, self.worker, level, event, message, **data)

    def wait(self, reason: str, seconds: float, message: str = "") -> None:
        raise queue.Wait(reason, seconds, message)

    def pipeline_ctx(self, lo: float = 0.0, hi: float = 1.0) -> pipeline_common.JobContext:
        """A pipeline JobContext whose progress fills [lo, hi] of this job and which stops when the job is canceled."""
        return pipeline_common.JobContext(lambda f, m: self.progress(lo + (hi - lo) * f, m), self.cancelled)


# ------------------------------------------------------------------ periodic jobs
def _minutes(key: str, default: float) -> Callable[[dict], float]:
    return lambda s: 60.0 * float(s.get(key) or default)


PERIODIC: list[tuple[str, Callable[[dict], float], Callable[[dict], bool]]] = [
    ("maintenance", lambda s: 3600.0, lambda s: True),
    ("schedule_tick", lambda s: 60.0, lambda s: state.enabled(s)),
    ("feed_scan", lambda s: 180.0, lambda s: state.enabled(s)),
    ("trend_scan", _minutes("trend_poll_minutes", 60), lambda s: state.enabled(s)),
    ("learn", lambda s: 6 * 3600.0, lambda s: state.enabled(s) and bool(s.get("autopilot_learning"))),
    ("live_watch", lambda s: 60.0, lambda s: state.enabled(s) and bool(s.get("autopilot_live_monitoring"))),
]
PERIOD_ADJUST: dict[str, Callable[[dict, float], float]] = {}  # e.g. the quota manager slows discovery down


def run_periodic(settings: dict, now: float | None = None) -> list[str]:
    """Enqueue every periodic job that is due (idempotent per time slot, safe from any process)."""
    now = now or time.time()
    started = []
    for kind, period_fn, active in PERIODIC:
        if kind not in HANDLERS or not active(settings):
            continue
        period = max(30.0, period_fn(settings))
        if kind in PERIOD_ADJUST:
            period = PERIOD_ADJUST[kind](settings, period)
        due = float(state.get(f"next:{kind}", 0) or 0)
        if now < due:
            continue
        queue.enqueue(kind, {"periodic": True}, idem_key=f"{kind}:{int(now // period)}", max_attempts=2,
                      timeout_s=max(600.0, period * 4), message="Scheduled run")
        state.put(f"next:{kind}", now + period)
        started.append(kind)
    return started


# ------------------------------------------------------------------ the host
class WorkerHost:
    def __init__(self, workers: list[str] | None = None, poll: float = POLL_SECONDS, periodic: bool = True,
                 managed: bool = False):
        from . import handlers  # noqa: F401 - registers every job handler

        self.names = workers or list(queue.WORKERS)
        self.owner = queue.host_id()
        self.poll = poll
        self.periodic = periodic
        self.managed = managed
        self._stop = threading.Event()
        self._wake = {n: threading.Event() for n in self.names}
        self._threads: list[threading.Thread] = []
        self._running: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.host_lock = locks.named("worker-host")
        self.started = False

    # -------------------------------------------------------------- lifecycle
    def start(self, wait_for_lock: float = 0.0) -> bool:
        if self.started:
            return True
        if not self.host_lock.acquire(timeout=wait_for_lock):
            log.info("Another ClipFoundry worker host is running; not starting a second one")
            return False
        self.started = True
        db.init()
        queue.recover()
        for name in self.names:
            self.set_state(name, "idle", message="Ready")
            t = threading.Thread(target=self._loop, args=(name,), daemon=True, name=f"cf-worker-{name}")
            t.start()
            self._threads.append(t)
        t = threading.Thread(target=self._supervise, daemon=True, name="cf-worker-supervisor")
        t.start()
        self._threads.append(t)
        state.event("host_started", f"Workers started ({'separate process' if self.managed else 'in the app'})",
                    pid=os.getpid())
        return True

    def stop(self, timeout: float = 10.0) -> None:
        if not self.started:
            return
        self._stop.set()
        for ev in self._wake.values():
            ev.set()
        with self._lock:
            for job in self._running.values():
                job.cancel_event.set()
        deadline = time.monotonic() + timeout
        for t in self._threads:
            t.join(timeout=max(0.1, deadline - time.monotonic()))
        for name in self.names:
            self.set_state(name, "idle", message="Stopped")
        alive = [t for t in self._threads if t.is_alive()]
        if alive:
            # A job that has not reached its next safe point may still act (an upload, a render): no other host
            # may start until it has, so the host lock is only released once those threads are done.
            log.warning("%d worker thread(s) still finishing; the worker host lock is kept until they stop",
                        len(alive))

            def release_when_done() -> None:
                for t in alive:
                    t.join()
                self.host_lock.release()

            threading.Thread(target=release_when_done, daemon=True, name="cf-worker-release").start()
        else:
            self.host_lock.release()
        self.started = False

    def wake(self, worker: str | None = None) -> None:
        for name, ev in self._wake.items():
            if worker is None or name == worker:
                ev.set()

    def running(self) -> dict[str, Job]:
        with self._lock:
            return dict(self._running)

    # -------------------------------------------------------------- state for the UI
    def set_state(self, name: str, status: str, job: Job | None = None, stage: str | None = None,
                  message: str | None = None, error: str | None = None) -> None:
        fields = {"name": name, "status": status, "host": self.owner, "pid": os.getpid(), "heartbeat": time.time(),
                  "job_id": job.id if job else "", "ref_type": (job.row.get("ref_type") if job else "") or "",
                  "ref_id": (job.row.get("ref_id") if job else "") or ""}
        if stage is not None:
            fields["stage"] = stage
        elif job is None:
            fields["stage"] = ""
        if message is not None:
            fields["message"] = message[:300]
        if error is not None:
            fields["last_error"] = error[:1000]
        if status == "completed":
            fields["last_completed_at"] = time.time()
        now = time.time()
        with db.connect() as conn:
            exists = conn.execute("SELECT 1 FROM worker_state WHERE name = ?", (name,)).fetchone()
            if exists:
                cols = ", ".join(f"{k} = ?" for k in [*fields, "updated_at"])
                conn.execute(f"UPDATE worker_state SET {cols} WHERE name = ?", [*fields.values(), now, name])
            else:
                row = {**fields, "updated_at": now}
                conn.execute(f"INSERT INTO worker_state ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                             list(row.values()))

    # -------------------------------------------------------------- loops
    def _gate(self, settings: dict) -> tuple[bool, int]:
        """(may run at all, minimum job priority)."""
        if state.paused():
            return False, 0
        return True, 0 if state.enabled(settings) else MANUAL_PRIORITY

    def _loop(self, name: str) -> None:
        while not self._stop.is_set():
            try:
                settings = db.get_settings()
                ok, min_priority = self._gate(settings)
                job_row = self._claim(name, min_priority) if ok else None
                if job_row is None:
                    idle = "Stopped (STOP ALL JOBS)" if not ok else (
                        "Idle" if min_priority == 0 else "Autopilot is off")
                    self._idle(name, idle)
                    self._wake[name].wait(timeout=self.poll)
                    self._wake[name].clear()
                    continue
                self._run(name, job_row)
            except Exception:  # noqa: BLE001 - a worker loop must never die
                log.exception("worker %s loop error", name)
                time.sleep(self.poll)

    def _token(self, name: str) -> str:
        """A lease token for one claim: only this claim can renew or finish the job, so a thread still working on
        a job that was recovered and claimed again (even by this same process) cannot overwrite the outcome."""
        return f"{self.owner}/{name}/{secrets.token_hex(4)}"

    def _claim(self, name: str, min_priority: int) -> dict | None:
        # Autopilot off: min_priority limits the claim to jobs a user started by hand, inside the claim itself
        return queue.claim(name, self._token(name), min_priority=min_priority if min_priority > 0 else None)

    def _idle(self, name: str, message: str) -> None:
        row = db.fetch("worker_state", name, "name") or {}
        now = time.time()
        # "Completed"/"Failed" stay visible for a while after the job ends, then the worker shows as idle
        recent_done = row.get("status") in ("completed", "failed") and now - float(row.get("updated_at") or 0) < 600
        if not recent_done and (row.get("status") != "idle" or row.get("message") != message):
            self.set_state(name, "idle", message=message)
        elif now - float(row.get("heartbeat") or 0) > HEARTBEAT_SECONDS:
            db.execute("UPDATE worker_state SET heartbeat = ?, host = ?, pid = ? WHERE name = ?",
                       (now, self.owner, os.getpid(), name))

    def _run(self, name: str, row: dict) -> None:
        token = row["lease_owner"]
        job = Job(row, token, self)
        with self._lock:
            self._running[job.id] = job
        self.set_state(name, "working", job, stage=row["kind"], message=row.get("message") or "Working")
        fn = HANDLERS.get(row["kind"])
        try:
            if fn is None:
                raise queue.Fail(f"No handler for job kind {row['kind']}")
            result = fn(job) or {}
            job.check()
            queue.complete(row, token, result, str(result.get("message") or "Done"))
            self.set_state(name, "completed", None, message=str(result.get("message") or f"{row['kind']} done"))
        except queue.Wait as w:
            queue.wait(row, token, w.reason, w.seconds, w.message)
            self.set_state(name, "waiting", job, message=w.message)
        except queue.Canceled:
            if job.timed_out:
                queue.fail(row, token, f"Stopped after the {int(row['timeout_s'] // 60)} min time limit",
                           "It will run again on the next cycle; check the log if this repeats.")
                self.set_state(name, "failed", None, message="Timed out", error="time limit reached")
            else:
                queue.mark_canceled(row, token, "Canceled")
                self.set_state(name, "idle", None, message="Canceled")
        except queue.Retry as exc:
            status = queue.retry_or_fail(row, token, str(exc), exc.fix, exc.delay)
            self.set_state(name, "failed" if status == "failed" else "waiting", None, message=str(exc),
                           error=str(exc))
        except queue.Fail as exc:
            queue.fail(row, token, str(exc), exc.fix)
            self.set_state(name, "failed", None, message=str(exc), error=str(exc))
        except Exception as exc:  # noqa: BLE001 - unexpected: retry with backoff, keep the pipeline going
            detail = f"{type(exc).__name__}: {exc}"
            log.error("job %s (%s) crashed: %s\n%s", row["id"], row["kind"], detail, traceback.format_exc())
            job.log("crash", detail, "error", trace=traceback.format_exc()[-4000:])
            status = queue.retry_or_fail(row, token, detail)
            self.set_state(name, "failed" if status == "failed" else "waiting", None, message=detail, error=detail)
        finally:
            with self._lock:
                self._running.pop(job.id, None)

    def _supervise(self) -> None:
        last_recover = 0.0
        last_beat = 0.0
        while not self._stop.is_set():
            try:
                now = time.time()
                self._heartbeat()
                if now - last_recover > 30:
                    queue.expire_timeouts(now)
                    queue.recover(now)
                    last_recover = now
                settings = db.get_settings()
                if self.periodic and not state.paused():
                    for kind in run_periodic(settings, now):
                        self.wake(queue.KIND_WORKER[kind])
                if now - last_beat > HEARTBEAT_SECONDS:
                    state.put("host_heartbeat", {"at": now, "owner": self.owner, "pid": os.getpid(),
                                                 "managed": self.managed})
                    last_beat = now
                if self.managed:
                    beat = state.get("app_heartbeat") or {}
                    if now - float(beat.get("at") or 0) > APP_HEARTBEAT_STALE:
                        log.warning("ClipFoundry app stopped responding; stopping the worker process")
                        threading.Thread(target=self.stop, daemon=True).start()
                        return
            except Exception:  # noqa: BLE001
                log.exception("worker supervisor error")
            self._stop.wait(timeout=min(self.poll, 5.0))

    def _heartbeat(self) -> None:
        """Renew the leases of running jobs and pass on cancel requests, timeouts and STOP ALL JOBS."""
        stop_all = state.paused()
        for job in self.running().values():
            flags = queue.renew(job.id, job.owner)
            if flags is None or stop_all:
                job.cancel_event.set()
            elif flags["cancel_requested"]:
                job.timed_out = flags["cancel_requested"] == 2
                job.cancel_event.set()


# ------------------------------------------------------------------ app side: start / supervise the host
class Supervisor:
    """Runs in the app: keeps the worker host alive (own process by default, threads as a fallback)."""

    def __init__(self) -> None:
        self.mode = "off"
        self.host: WorkerHost | None = None
        self.proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.restarts: list[float] = []

    def start(self) -> None:
        settings = db.get_settings()
        self.mode = os.environ.get("CLIPFOUNDRY_WORKERS") or settings.get("autopilot_process") or "separate"
        if self.mode == "off":
            return
        self._beat()
        if self.mode == "separate" and not self._spawn():
            self.mode = "in_app"
        if self.mode == "in_app":
            self.host = WorkerHost()
            if not self.host.start():
                self.host = None
        self._thread = threading.Thread(target=self._watch, daemon=True, name="cf-worker-watch")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.host:
            self.host.stop()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _beat(self) -> None:
        state.put("app_heartbeat", {"at": time.time(), "pid": os.getpid()})

    def _spawn(self) -> bool:
        log_dir = config.data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            out = open(log_dir / "workers.log", "ab")  # noqa: SIM115 - handed to the child process
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self.proc = subprocess.Popen([sys.executable, "-m", "clipfoundry", "workers", "--managed"],
                                         stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         env={**os.environ, "CLIPFOUNDRY_DATA": str(config.data_dir())},
                                         creationflags=flags, cwd=str(config.ROOT_DIR))
            out.close()
            state.event("host_spawned", "Started the autopilot worker process", pid=self.proc.pid)
            return True
        except OSError as exc:
            state.action("workers:spawn", "workers", "The autopilot worker process could not be started",
                         f"{exc}. The workers run inside the app instead.", level="warning")
            return False

    def _watch(self) -> None:
        while not self._stop.wait(timeout=5.0):
            try:
                self._beat()
                if self.mode == "separate" and self.proc and self.proc.poll() is not None:
                    now = time.time()
                    self.restarts = [t for t in self.restarts if now - t < 600] + [now]
                    if len(self.restarts) > 5:
                        state.action("workers:crashing", "workers", "The autopilot worker process keeps stopping",
                                     "It stopped more than 5 times in 10 minutes; the workers now run inside the "
                                     "app. See data/logs/workers.log.", level="error")
                        self.mode = "in_app"
                        self.host = WorkerHost()
                        self.host.start(wait_for_lock=15)
                    else:
                        self._spawn()
            except Exception:  # noqa: BLE001
                log.exception("worker supervisor (app side) error")

    def status(self) -> dict:
        beat = state.get("host_heartbeat") or {}
        alive = time.time() - float(beat.get("at") or 0) < 3 * HEARTBEAT_SECONDS
        return {"mode": self.mode, "alive": alive, "pid": beat.get("pid"), "managed": beat.get("managed"),
                "process_running": bool(self.proc and self.proc.poll() is None), "last_heartbeat": beat.get("at")}


supervisor = Supervisor()


def run_worker_process(managed: bool = False) -> int:
    """`python -m clipfoundry workers`: run the worker host until stopped."""
    host = WorkerHost(managed=managed)
    if not host.start(wait_for_lock=30):
        print("Another ClipFoundry worker host is already running.")
        return 1
    print(f"ClipFoundry workers running (pid {os.getpid()}). Press Ctrl+C to stop.")
    try:
        while host.started:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        host.stop()
    return 0

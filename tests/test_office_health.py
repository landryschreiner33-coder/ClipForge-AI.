"""System Guardian readings (office/health.py) and the worker log file: a failed CUDA run is never shown as Healthy,
a missing account is information rather than a fault, the database advice promises no backup that does not exist,
an Autopilot that is on but finds nothing says why, and data/logs/workers.log stays bounded."""
from __future__ import annotations

import logging
import time

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path / "data"


def _gpu_as_found(monkeypatch) -> None:
    """An RTX 3050 the driver reports as present; the last error and last transcription are the real stored ones."""
    from clipfoundry import gpu
    from clipfoundry.autopilot import state

    monkeypatch.setattr(gpu.manager, "status", lambda settings: {
        "available": True, "name": "NVIDIA GeForce RTX 3050", "problem": "", "fix": "", "busy": False,
        "last_error": state.get("gpu:last_error"), "last_transcription": state.get("gpu:last_transcription")})


def _healthy_basics(monkeypatch) -> None:
    """Readings this sandbox cannot take like the owner's PC (no GPU, workers off in tests) set to Healthy, so a test
    sees only the reading it is about."""
    from clipfoundry.office import health

    for name in ("gpu", "ffmpeg", "disk"):
        monkeypatch.setattr(health, name, lambda *_a, _n=name, **_k: health._c(_n, _n, "healthy", "fine"))
    from clipfoundry import db

    db.insert("worker_state", {"name": "scout", "heartbeat": time.time(), "updated_at": time.time()}, key="name")


def test_a_failed_cuda_run_is_an_error_until_the_gpu_works_again(data, monkeypatch):
    from clipfoundry import gpu
    from clipfoundry.office import health

    _gpu_as_found(monkeypatch)
    assert health.gpu({})["status"] == "healthy"
    with pytest.raises(RuntimeError):
        with gpu.manager.heavy("transcription", "talk.mp4"):
            raise RuntimeError("CUDA failed with error cublas64_12.dll is not found")
    reading = health.gpu({})
    assert reading["status"] == "error" and "cublas64_12.dll" in reading["reason"]
    assert "gpu-check.bat" in reading["action"] and "ClipFoundry folder" in reading["action"]
    # a later transcription that really ran on the GPU clears it
    gpu.manager.record_transcription({"device": "cuda", "requested_device": "cuda", "compute_type": "float16"}, "x")
    assert health.gpu({})["status"] == "healthy"


def test_a_cpu_fallback_is_degraded_and_says_so(data, monkeypatch):
    from clipfoundry import gpu
    from clipfoundry.office import health

    _gpu_as_found(monkeypatch)
    gpu.manager.record_transcription({"device": "cpu", "requested_device": "cuda", "compute_type": "int8",
                                      "warning": "GPU transcription failed (float16): cuDNN missing",
                                      "fix": "Run start.bat again."}, "talk.mp4")
    reading = health.gpu({})
    assert reading["status"] == "degraded" and "CPU instead of the GPU" in reading["reason"]
    assert "cuDNN missing" in reading["reason"] and reading["action"] == "Run start.bat again."
    # another program holding the GPU is not a GPU failure
    from clipfoundry.autopilot import state

    state.put("gpu:last_error", {"kind": "transcription", "error": "Only 300 MB of GPU memory was free (needs 2500 "
                                 "MB); another program is probably using the GPU.", "at": time.time()})
    reading = health.gpu({})
    assert reading["status"] == "degraded" and "could not get the GPU" in reading["reason"]


def test_no_connected_account_is_information_not_an_unknown_overall(data, monkeypatch):
    from clipfoundry.office import health

    _healthy_basics(monkeypatch)
    out = health.check()
    acc = next(c for c in out["checks"] if c["id"] == "accounts")
    assert acc["status_label"] == "Not connected" and acc["info"] and "stay on this PC" in acc["reason"]
    assert out["status"] == "healthy" and out["label"] == "Healthy"
    # a real fault still decides the overall status
    monkeypatch.setattr(health, "disk", lambda: health._c("disk", "Disk space", "error", "Only 1.0 GB free."))
    assert health.check()["status"] == "error"


def test_the_database_advice_promises_no_backup_folder(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.office import health

    def broken(*_a, **_k):
        raise RuntimeError("database disk image is malformed")

    monkeypatch.setattr(db, "scalar", broken)
    reading = health.database()
    assert reading["status"] == "error" and "malformed" in reading["reason"]
    assert "backups" not in reading["action"]
    assert "copy the whole data folder" in reading["action"] and "ClipFoundry closed" in reading["action"]
    assert str(data) in reading["action"]


def test_autopilot_on_with_nowhere_to_look_is_an_error(data):
    from clipfoundry import db
    from clipfoundry.office import health

    db.save_settings({"autopilot_enabled": True, "library_discovery": False})
    reading = health.discovery(db.get_settings())
    assert reading["status"] == "error" and "nowhere to look" in reading["reason"]
    assert "videos folder" in reading["action"]
    db.save_settings({"library_discovery": True})
    assert health.discovery(db.get_settings())["status"] == "healthy"


def test_a_search_that_stopped_starting_is_detected(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, state
    from clipfoundry.office import health

    db.save_settings({"autopilot_enabled": False, "library_discovery": True, "trend_poll_minutes": 180})
    off = health.discovery(db.get_settings())
    assert off["info"] and off["status_label"] == "Off"  # not a fault, and not counted
    db.save_settings({"autopilot_enabled": True})
    state.put("trend:last_scan", {"at": time.time() - 3600, "signals": 3, "active": 1})
    fine = health.discovery(db.get_settings())
    assert fine["status"] == "healthy" and "free-license library" in fine["reason"]
    state.put("trend:last_scan", {"at": time.time() - 7 * 3600, "signals": 3, "active": 1})
    late = health.discovery(db.get_settings())
    assert late["status"] == "degraded" and "7 h ago" in late["reason"] and "every 3 h" in late["reason"]
    assert "Background work" in late["action"]
    # a search that is running, or waiting for a time the platform asked for, is not late
    job = queue.enqueue("trend_scan", {"periodic": True})
    assert queue.claim(queue.KIND_WORKER["trend_scan"], "w")["id"] == job["id"]
    assert "Searching for videos now" in health.discovery(db.get_settings())["reason"]
    db.execute("UPDATE worker_jobs SET status = 'waiting', run_after = ?, message = ? WHERE id = ?",
               (time.time() + 1800, "YouTube asked to wait 30 min", job["id"]))
    waiting = health.discovery(db.get_settings())
    assert waiting["status"] == "healthy" and "30 min" in waiting["reason"]
    # turning Autopilot on again starts the clock again
    db.execute("DELETE FROM worker_jobs")
    state.event("autopilot_on", "Autopilot turned on")
    assert health.discovery(db.get_settings())["status"] == "healthy"
    db.execute("UPDATE autopilot_events SET at = ? WHERE kind = 'autopilot_on'", (time.time() - 6.5 * 3600,))
    late = health.discovery(db.get_settings())
    assert late["status"] == "degraded" and "since Autopilot was turned on 6.5 h ago" in late["reason"]


def test_silent_workers_and_stalled_leases_are_reported(data):
    """The existing readings behind "Autopilot says running but nothing is happening"."""
    from clipfoundry import db
    from clipfoundry.autopilot import queue
    from clipfoundry.office import health

    db.save_settings({"autopilot_enabled": True})
    db.insert("worker_state", {"name": "scout", "heartbeat": time.time() - 600, "updated_at": time.time()}, key="name")
    reading = health.scheduler(db.get_settings())
    assert reading["status"] == "error" and "10 min ago" in reading["reason"] and "start.bat" in reading["action"]
    job = queue.enqueue("rights_check", ref=("source", "s1"))
    queue.claim(queue.KIND_WORKER["rights_check"], "w")
    db.execute("UPDATE worker_jobs SET lease_until = ? WHERE id = ?", (time.time() - 120, job["id"]))
    reading = health.queue_age(db.get_settings())
    assert reading["status"] == "degraded" and "stopped reporting" in reading["reason"]


@pytest.fixture()
def root_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield root
    for h in root.handlers:
        if h not in handlers:
            h.close()
    root.handlers, root.level = handlers, level
    logging.getLogger("httpx").setLevel(logging.NOTSET)


def test_the_worker_log_is_size_bounded_and_keeps_its_format(tmp_path, monkeypatch, root_logging):
    import httpx

    from clipfoundry.__main__ import setup_logging
    from clipfoundry.autopilot import host

    monkeypatch.setattr(host, "LOG_MAX_BYTES", 4000)
    root_logging.handlers = []
    setup_logging()
    host.log_to_file(tmp_path / "logs")
    assert not [h for h in root_logging.handlers if type(h) is logging.StreamHandler]  # nothing left on the console
    log = logging.getLogger("clipfoundry")
    for i in range(400):
        log.info("step %03d of a long night of work", i)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as c:
        c.get("https://www.googleapis.com/youtube/v3/videos?id=x&key=AIza-secret")
    for h in root_logging.handlers:
        h.flush()
    files = sorted(p.name for p in (tmp_path / "logs").iterdir())
    assert files == ["workers.log", "workers.log.1", "workers.log.2", "workers.log.3"]  # 3 older files at most
    assert all((tmp_path / "logs" / f).stat().st_size <= 4000 for f in files)
    text = (tmp_path / "logs" / "workers.log").read_text("utf-8")
    assert "INFO clipfoundry: step 399 of a long night of work" in text  # the same format as on the console
    assert "AIza-secret" not in "".join((tmp_path / "logs" / f).read_text("utf-8") for f in files)


def test_the_worker_console_file_is_cut_back_at_each_start(tmp_path, monkeypatch):
    from clipfoundry.autopilot import host

    monkeypatch.setattr(host, "LOG_MAX_BYTES", 100)
    console = tmp_path / "workers-console.log"
    console.write_bytes(b"x" * 50)
    host._cut_back(console)
    assert console.exists() and not (tmp_path / "workers-console.log.1").exists()
    console.write_bytes(b"y" * 500)
    host._cut_back(console)
    assert not console.exists() and (tmp_path / "workers-console.log.1").read_bytes() == b"y" * 500

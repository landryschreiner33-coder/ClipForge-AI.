"""Cancellation wakes blocked media I/O and reaps children, rather than leaving a renewed lease hung."""
from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest

from clipfoundry.pipeline import ffmpeg_utils, reframe
from clipfoundry.pipeline.common import Cancelled, JobContext


@pytest.mark.parametrize("operation", ["read", "write", "wait"])
def test_cancel_interrupts_blocked_media_operations(operation):
    cancelled = threading.Event()
    timer = threading.Timer(.2, cancelled.set)
    started = time.monotonic()
    watch = ffmpeg_utils.MediaWatchdog(cancelled.is_set, timeout=10)
    proc = None
    timer.start()
    try:
        with pytest.raises(Cancelled), watch:
            proc = watch.add(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE))
            if operation == "read":
                proc.stdout.read(1)
            elif operation == "write":
                proc.stdin.write(b"x" * (4 << 20))
            else:
                proc.wait()
    finally:
        timer.cancel()
        timer.join()
    assert time.monotonic() - started < 5
    assert proc is not None and proc.poll() is not None
    assert all(stream.closed for stream in (proc.stdin, proc.stdout, proc.stderr))
    assert not watch._thread.is_alive()


def test_bounded_helper_stops_and_reaps_a_silent_process(monkeypatch):
    original = subprocess.Popen
    processes = []

    def record(*args, **kwargs):
        proc = original(*args, **kwargs)
        processes.append(proc)
        return proc

    monkeypatch.setattr(ffmpeg_utils.subprocess, "Popen", record)
    with pytest.raises(ffmpeg_utils.FFmpegError, match="took too long"):
        ffmpeg_utils.run_process([sys.executable, "-c", "import time; time.sleep(60)"], timeout=.2)
    assert len(processes) == 1 and processes[0].poll() is not None
    assert processes[0].stdout.closed and processes[0].stderr.closed


@pytest.mark.parametrize("stage", ["progress", "frames"])
def test_ffmpeg_stages_cancel_while_the_child_produces_no_output(monkeypatch, stage):
    original = subprocess.Popen
    processes = []
    cancelled = threading.Event()

    def stalled(_cmd, **kwargs):
        proc = original([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        processes.append(proc)
        return proc

    monkeypatch.setattr(ffmpeg_utils.subprocess, "Popen", stalled)
    monkeypatch.setattr(ffmpeg_utils, "ffmpeg_bin", lambda: "ffmpeg")
    monkeypatch.setattr(reframe, "ffmpeg_bin", lambda: "ffmpeg")
    timer = threading.Timer(.2, cancelled.set)
    timer.start()
    try:
        with pytest.raises(Cancelled):
            if stage == "progress":
                ffmpeg_utils.run([], cancel=cancelled.is_set)
            else:
                list(reframe._sample_frames("unused.mp4", 0, 1, 2, 2, JobContext(None, cancelled.is_set)))
    finally:
        timer.cancel()
        timer.join()
    assert len(processes) == 1 and processes[0].poll() is not None
    assert processes[0].stdout.closed


def test_second_child_start_failure_releases_first_child():
    proc = None
    with pytest.raises(OSError), ffmpeg_utils.MediaWatchdog(timeout=10) as watch:
        proc = watch.add(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                          stdout=subprocess.PIPE))
        raise OSError("encoder failed to start")
    assert proc is not None and proc.poll() is not None and proc.stdout.closed


def test_cancel_reaps_both_children_in_decode_encode_pair():
    cancelled = threading.Event()
    timer = threading.Timer(.2, cancelled.set)
    processes = []
    timer.start()
    try:
        with pytest.raises(Cancelled), ffmpeg_utils.MediaWatchdog(cancelled.is_set, timeout=10) as watch:
            for _ in range(2):
                processes.append(watch.add(subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)))
            processes[0].stdout.read(1)
    finally:
        timer.cancel()
        timer.join()
    assert all(proc.poll() is not None and proc.stdin.closed and proc.stdout.closed for proc in processes)


def test_unreadable_cancel_state_stops_child_instead_of_losing_watchdog():
    calls = 0

    def cancel_state():
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("state is temporarily unreadable")
        return False

    proc = None
    with pytest.raises(ffmpeg_utils.FFmpegError, match="cancellation state"), \
            ffmpeg_utils.MediaWatchdog(cancel_state, timeout=10) as watch:
        proc = watch.add(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                          stdout=subprocess.PIPE))
        proc.stdout.read(1)
    assert proc is not None and proc.poll() is not None and proc.stdout.closed
    assert not watch._thread.is_alive()


def test_exit_race_cannot_replace_original_pipeline_failure(monkeypatch):
    original = ValueError("original pipeline failure")
    proc = subprocess.Popen([sys.executable, "-c", "pass"], stdout=subprocess.PIPE)
    proc.wait()
    # Simulate an exit between poll and kill: wait still reaps the exited real process.
    monkeypatch.setattr(proc, "poll", lambda: None)
    monkeypatch.setattr(proc, "kill", lambda: (_ for _ in ()).throw(ProcessLookupError("already exited")))
    with pytest.raises(ValueError) as error, ffmpeg_utils.MediaWatchdog(timeout=10) as watch:
        watch.add(proc)
        raise original
    assert error.value is original and proc.stdout.closed

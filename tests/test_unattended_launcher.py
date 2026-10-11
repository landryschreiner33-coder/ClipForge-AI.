"""Exercise owned fake/short-lived children, never the app, OAuth or owner profiles."""
from __future__ import annotations

import io
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from clipfoundry import unattended


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class StopsAfter:
    def __init__(self, waits: int):
        self.remaining = waits
        self.stopped = False
        self.waits = []

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.waits.append(seconds)
        self.remaining -= 1
        self.stopped = self.remaining <= 0
        return self.stopped


class FakeChild:
    def __init__(self, result=9):
        self.result = result
        self.cleanup = []

    def poll(self):
        return self.result

    def stop(self, graceful=True):
        self.cleanup.append(graceful)


def test_restarts_with_bounded_backoff_and_cleans_every_exited_child(monkeypatch):
    monkeypatch.setattr(unattended, "_port_available", lambda *_: True)
    children = []

    def spawn(*_):
        child = FakeChild()
        children.append(child)
        return child

    stop = StopsAfter(8)
    result = unattended._supervise([], {}, logging.getLogger("test"), stop, "127.0.0.1", 8899,
                                   spawn=spawn, clock=lambda: 0)
    assert result == 0
    assert stop.waits == [2, 4, 8, 16, 32, 60, 60, 60]
    assert len(children) == 8
    assert all(child.cleanup == [False] for child in children)


def test_long_successful_uptime_resets_backoff(monkeypatch):
    monkeypatch.setattr(unattended, "_port_available", lambda *_: True)
    timestamps = iter([0, 0, 1, 1, 2, 302])
    stop = StopsAfter(3)
    unattended._supervise([], {}, logging.getLogger("test"), stop, "127.0.0.1", 8899,
                           spawn=lambda *_: FakeChild(), clock=lambda: next(timestamps))
    assert stop.waits == [2, 4, 2]


def test_explicit_stop_cleans_running_child_without_a_restart(monkeypatch):
    monkeypatch.setattr(unattended, "_port_available", lambda *_: True)
    child = FakeChild(result=None)
    stop = StopsAfter(1)
    assert unattended._supervise([], {}, logging.getLogger("test"), stop, "127.0.0.1", 8899,
                                 spawn=lambda *_: child) == 0
    assert stop.waits == [0.25]
    assert child.cleanup == [True]


def test_spawn_failures_back_off_and_stop_without_tight_loop(monkeypatch):
    monkeypatch.setattr(unattended, "_port_available", lambda *_: True)
    calls = []

    def fail(*_):
        calls.append(1)
        raise PermissionError("synthetic; not owner data")

    stop = StopsAfter(3)
    assert unattended._supervise([], {}, logging.getLogger("test"), stop, "127.0.0.1", 8899,
                                 spawn=fail, clock=lambda: 0) == 0
    assert len(calls) == 3
    assert stop.waits == [2, 4, 8]


def test_occupied_port_does_not_start_another_process():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert unattended._supervise([], {}, logging.getLogger("test"), threading.Event(), "127.0.0.1", port,
                                     spawn=lambda *_: pytest.fail("Must not start a second server")) == 2


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX TIME_WAIT/reuseaddr behavior")
def test_closed_server_time_wait_does_not_block_a_restart():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert not unattended._port_available("127.0.0.1", port)
        with socket.create_connection(("127.0.0.1", port)) as client:
            accepted, _ = listener.accept()
            accepted.shutdown(socket.SHUT_RDWR)
            accepted.close()  # The server closes first, leaving its local port in TIME_WAIT.
            assert client.recv(1) == b""
    assert unattended._port_available("127.0.0.1", port)


def test_profile_lock_prevents_duplicate_even_on_a_different_port(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path))
    lock = unattended.locks.named("unattended-app")
    assert lock.acquire(timeout=0)
    try:
        assert unattended.run("127.0.0.1", _port()) == 2
    finally:
        lock.release()


def test_port_lock_prevents_duplicate_between_profiles(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path))
    port = _port()
    name = unattended.hashlib.sha256(f"port:{port}".encode()).hexdigest()[:20]
    lock = unattended._PortLock(name)
    assert lock.acquire(timeout=0)
    try:
        assert unattended.run("127.0.0.1", port) == 2
    finally:
        lock.release()


def test_command_and_environment_preserve_selected_profile_port(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "profile"))
    monkeypatch.setenv("CLIPFOUNDRY_PORT", "8899")
    seen = {}

    def supervise(command, env, logger, stop, host, port):
        seen.update(command=command, env=env, host=host, port=port)
        return 0

    monkeypatch.setattr(unattended, "_supervise", supervise)
    assert unattended.run("127.0.0.1", _port()) == 0
    assert seen["env"]["CLIPFOUNDRY_DATA"] == str((tmp_path / "profile").resolve())
    assert seen["env"]["CLIPFOUNDRY_PORT"] == str(seen["port"])
    assert seen["env"]["PYTHONUNBUFFERED"] == "1"
    assert seen["command"][:3] == [sys.executable, "-m", "clipfoundry"]
    assert seen["command"][3:] == ["--host", "127.0.0.1", "--port", str(seen["port"]), "--unattended-child"]
    assert "--open" not in seen["command"] and "--unattended" not in seen["command"]
    assert not (tmp_path / "profile" / "clipfoundry.db").exists()
    assert not unattended.locks.named("unattended-app").held_elsewhere()


def test_cli_unattended_flag_dispatches_without_starting_owner_app(monkeypatch):
    from clipfoundry import __main__

    monkeypatch.setattr(sys, "argv", ["clipfoundry", "--unattended", "--port", "8899"])
    seen = []
    monkeypatch.setattr(unattended, "run", lambda *args: seen.append(args) or 0)
    monkeypatch.setattr(__main__, "_serve", lambda *_: pytest.fail("Parent must not start the app"))
    assert __main__.main() == 0
    assert seen == [("127.0.0.1", 8899, False)]


def test_child_gate_requires_parent_handshake_before_any_app_work(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert not unattended.child_gate()
    monkeypatch.setattr(sys, "stdin", io.StringIO("wrong\n"))
    assert not unattended.child_gate()
    monkeypatch.setattr(sys, "stdin", io.StringIO("start\n"))
    assert unattended.child_gate()


def _wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    pytest.fail("Disposable child did not reach the expected state")


def _alive(pid: int) -> bool:
    if sys.platform.startswith("linux"):
        try:
            if Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0] == "Z":
                return False
        except FileNotFoundError:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@pytest.mark.skipif(sys.platform == "win32", reason="Process-group test; Windows Job Object needs a Windows host")
@pytest.mark.parametrize("unexpected_exit", [False, True])
def test_real_child_cleanup_includes_grandchild_after_stop_or_app_crash(tmp_path, unexpected_exit):
    pid_file = tmp_path / "grandchild.pid"
    descendant = ("import os,time,pathlib; "
                  f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)")
    script = ("import sys,subprocess,time,pathlib,os; assert sys.stdin.readline() == 'start\\n'; "
              f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); "
              f"p=pathlib.Path({str(pid_file)!r}); "
              "\nwhile not p.exists(): time.sleep(.01)\n" +
              ("os._exit(7)\n" if unexpected_exit else "time.sleep(60)\n"))
    child = unattended.AppChild([sys.executable, "-u", "-c", script], dict(os.environ), logging.getLogger("test"))
    pid = None
    try:
        _wait_for(pid_file.exists)
        pid = int(pid_file.read_text())
        assert _alive(pid)
        if unexpected_exit:
            _wait_for(lambda: child.poll() is not None)
            assert child.poll() == 7
        child.stop(graceful=not unexpected_exit)
        assert child.poll() is not None
        _wait_for(lambda: not _alive(pid))
    finally:
        child.stop(graceful=False)
        if pid and _alive(pid):
            os.kill(pid, signal.SIGKILL)


def test_real_child_output_rotates_during_a_long_run(monkeypatch, tmp_path):
    monkeypatch.setattr(unattended, "LOG_MAX_BYTES", 4096)
    logger, handler = unattended._logger(tmp_path)
    script = ("import sys,time; assert sys.stdin.readline() == 'start\\n'; "
              "sys.stdout.write('synthetic output\\n' * 20000); sys.stdout.flush(); time.sleep(60)")
    child = unattended.AppChild([sys.executable, "-u", "-c", script], dict(os.environ), logger)
    try:
        _wait_for(lambda: (tmp_path / "unattended.log.2").exists())
        assert child.poll() is None
        files = list(tmp_path.glob("unattended.log*"))
        assert len(files) == 3
        assert all(path.stat().st_size <= 4096 for path in files)
    finally:
        child.stop()
        handler.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal integration; requires a Windows host there")
def test_real_watchdog_restarts_then_sigint_stops_all_owned_processes(tmp_path):
    records = tmp_path / "children.txt"
    source = ("import sys,subprocess,os,time,pathlib\n"
              "assert sys.stdin.readline() == 'start\\n'\n"
              f"p=pathlib.Path({str(records)!r})\n"
              "first=not p.exists()\n"
              "descendant=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
              "with p.open('a') as out: out.write(f'{os.getpid()} {descendant.pid}\\n')\n"
              "if first: time.sleep(.03); os._exit(7)\n"
              "time.sleep(60)\n")
    launcher = ("import sys\n"
                "from clipfoundry import unattended\n"
                "unattended.MIN_RESTART_SECONDS=.03\n"
                "unattended.MAX_RESTART_SECONDS=.06\n"
                "original=unattended._supervise\n"
                "def supervise(command,env,logger,stop,host,port):\n"
                f"    child=[sys.executable,'-u','-c',{source!r}]\n"
                "    return original(child,env,logger,stop,host,port)\n"
                "unattended._supervise=supervise\n"
                f"sys.exit(unattended.run('127.0.0.1',{_port()}))\n")
    env = {**os.environ, "CLIPFOUNDRY_DATA": str(tmp_path / "isolated profile")}
    proc = subprocess.Popen([sys.executable, "-u", "-c", launcher], env=env, cwd=str(unattended.config.ROOT_DIR),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    owned = []
    try:
        _wait_for(lambda: records.exists() and len(records.read_text().splitlines()) >= 2)
        owned = [int(value) for value in records.read_text().split()]
        assert len(owned) == 4
        proc.send_signal(signal.SIGINT)
        assert proc.wait(timeout=5) == 0
        for pid in owned:
            _wait_for(lambda pid=pid: not _alive(pid))
        assert len(records.read_text().splitlines()) == 2
        log = (tmp_path / "isolated profile" / "logs" / "unattended.log").read_text()
        assert "App exited (7); restarting" in log
        assert log.count("Started app process.") == 2
        assert not (tmp_path / "isolated profile" / "clipfoundry.db").exists()
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        if records.exists():
            owned = [int(value) for value in records.read_text().split()]
        for pid in owned:
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)
        proc.stdout.close()


def test_failed_windows_job_assignment_kills_gated_child_before_app_start(monkeypatch):
    order = []

    class Job:
        def assign(self, proc):
            order.append("assign")
            raise PermissionError("Synthetic Job Object assignment denial")

        def close(self):
            order.append("close job")

    class Process:
        def __init__(self, *_args, **_kwargs):
            order.append("spawn")
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO()
            self.running = True

        def poll(self):
            return None if self.running else -9

        def kill(self):
            order.append("kill gated child")
            self.running = False

        def wait(self, timeout=None):
            assert not self.running
            return -9

    monkeypatch.setattr(unattended.sys, "platform", "win32")
    monkeypatch.setattr(unattended.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    monkeypatch.setattr(unattended, "_WindowsJob", Job)
    monkeypatch.setattr(unattended.subprocess, "Popen", Process)
    with pytest.raises(PermissionError, match="Synthetic"):
        unattended.AppChild(["fake child"], {}, logging.getLogger("test"))
    assert order == ["spawn", "assign", "close job", "kill gated child"]

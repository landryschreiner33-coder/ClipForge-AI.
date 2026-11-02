"""Desktop lifecycle checks: no owner profile, downloads, or platform uploads."""
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import socket
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='Native desktop uses POSIX ownership')


@pytest.fixture
def desktop():
    if sys.platform == 'win32':
        pytest.skip('POSIX only')
    spec = importlib.util.spec_from_file_location('cf_desktop', Path(__file__).parents[1] / 'macos/desktop_runtime.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Ticks:
    def __init__(self, n=1):
        self.n = n

    def wait(self, seconds):
        self.n -= 1
        return self.n < 0


def test_desktop_does_not_claim_an_occupied_port(desktop):
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        server.listen()
        assert not desktop.port_available(server.getsockname()[1])
        assert server.fileno() >= 0


def test_parent_death_asks_owned_watchdog_to_shutdown(desktop, monkeypatch):
    killed = []
    monkeypatch.setattr(desktop.os, 'getppid', lambda: 999)
    monkeypatch.setattr(desktop.os, 'kill', lambda *args: killed.append(args))
    desktop.observe(123, 8765, 'current', Ticks())
    assert killed == [(os.getpid(), signal.SIGTERM)]


@pytest.mark.parametrize('returned,expected', [('current', ['ready']), ('old', []), ('', [])])
def test_readiness_belongs_to_this_launch(desktop, monkeypatch, returned, expected):
    events = []
    class LocalServer:
        def open(self, url, timeout):
            return io.BytesIO(json.dumps({'session': returned}).encode())
    monkeypatch.setattr(desktop.urllib.request, 'build_opener', lambda *_: LocalServer())
    monkeypatch.setattr(desktop, 'report', lambda state, message='': events.append(state))
    desktop.observe(os.getppid(), 8765, 'current', Ticks())
    assert events == expected


def test_startup_timeout_stops_owned_watchdog(desktop, monkeypatch):
    events, killed = [], []
    class Offline:
        def open(self, *args, **kwargs):
            raise OSError('offline')
    monkeypatch.setattr(desktop.urllib.request, 'build_opener', lambda *_: Offline())
    monkeypatch.setattr(desktop, 'report', lambda state, message='': events.append(state))
    monkeypatch.setattr(desktop.os, 'kill', lambda *args: killed.append(args))
    desktop.observe(os.getppid(), 8765, 'current', Ticks(), timeout=-1)
    assert events == ['error']
    assert killed == [(os.getpid(), signal.SIGTERM)]


def test_existing_launcher_lock_preserves_saved_data(desktop, monkeypatch, tmp_path, capsys):
    import fcntl
    saved = tmp_path / 'data/keep.txt'
    saved.parent.mkdir()
    saved.write_text('existing Brain and clips')
    monkeypatch.setattr(sys, 'argv', ['desktop', '--parent', str(os.getppid()), '--session', 'current', '--base', str(tmp_path)])
    previous_umask = os.umask(0o077)
    try:
        with (tmp_path / 'launcher.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert desktop.main() == 2
        assert saved.read_text() == 'existing Brain and clips'
        assert 'Another ClipFoundry' in capsys.readouterr().out
    finally:
        os.umask(previous_umask)


def test_desktop_probe_is_cheap_and_launch_specific(monkeypatch):
    from clipfoundry.api import desktop_status
    monkeypatch.delenv('CLIPFOUNDRY_DESKTOP_SESSION', raising=False)
    assert desktop_status()['session'] == ''
    monkeypatch.setenv('CLIPFOUNDRY_DESKTOP_SESSION', 'non-secret-test-nonce')
    assert desktop_status()['session'] == 'non-secret-test-nonce'

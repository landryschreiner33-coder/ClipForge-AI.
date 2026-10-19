"""Exercise runtime policy and disposable environments without app/account access."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import types

import pytest

import windows_bootstrap as bootstrap


GOOD = {"implementation": "cpython", "version": [3, 12, 10], "bits": 64,
        "platform": "win-amd64", "free_threaded": False}


@pytest.mark.parametrize("change, expected", [
    ({}, True), ({"version": [3, 11, 9]}, True),
    ({"version": [3, 10, 11]}, False), ({"version": [3, 13, 0]}, False),
    ({"version": [3, 14, 0]}, False), ({"version": [3, 15, 0]}, False),
    ({"bits": 32}, False), ({"bits": True}, False),
    ({"platform": "win32"}, False), ({"platform": "win-arm64"}, False),
    ({"platform": "linux-x86_64"}, False), ({"implementation": "pypy"}, False),
    ({"free_threaded": True}, False), ({"free_threaded": "false"}, False),
    ({"version": [3, 12]}, False), ({"version": [3, 12, "10"]}, False),
    ({"version": [3, True, 0]}, False),
])
def test_runtime_policy_uses_actual_implementation_architecture_and_version(change, expected):
    assert bootstrap.compatible_runtime({**GOOD, **change}) is expected


@pytest.mark.parametrize("details", [None, [], "cpython", {}, {"version": [3, 12, 10]}])
def test_missing_or_malformed_runtime_is_never_accepted(details):
    assert not bootstrap.compatible_runtime(details)


def test_actual_child_probe_reports_runtime_without_touching_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert bootstrap.probe_runtime(sys.executable) == bootstrap.runtime_details()
    assert list(tmp_path.iterdir()) == []


def test_cli_check_is_read_only_and_matches_runtime_policy(tmp_path):
    helper = str(Path(bootstrap.__file__).absolute())
    expected = 0 if bootstrap.compatible_runtime(bootstrap.runtime_details()) else 1
    result = subprocess.run([sys.executable, helper, "--check-python"], cwd=tmp_path, capture_output=True)
    assert result.returncode == expected
    assert result.stdout == result.stderr == b""
    assert list(tmp_path.iterdir()) == []


def test_cli_unsupported_runtime_refuses_before_making_any_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "runtime_details", lambda: {**GOOD, "bits": 32})
    assert bootstrap.main(["--prepare-venv", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []
    assert "64-bit CPython 3.12 or 3.11" in capsys.readouterr().err


def test_actual_probe_rejects_missing_executable(tmp_path):
    assert bootstrap.probe_runtime(tmp_path / "missing-python.exe") is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("probe", 20), OSError("unavailable")])
def test_probe_failure_is_not_a_compatible_runtime(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(bootstrap.subprocess, "run", fail)
    assert bootstrap.probe_runtime("test-python.exe") is None


@pytest.fixture
def host_runtime_policy(monkeypatch):
    """Only allow this test host to exercise real venv/child processes on Linux too."""
    actual = bootstrap.runtime_details()
    monkeypatch.setattr(bootstrap, "compatible_runtime", lambda details: details == actual)
    return actual


def test_actual_creation_and_reuse_preserve_data_and_installed_markers(tmp_path, host_runtime_policy):
    root = tmp_path / "app & percent% bang! with spaces"
    root.mkdir()
    data = root / "data"
    data.mkdir()
    (data / "brain-and-accounts.txt").write_bytes(b"saved state is never a setup input")
    environment = bootstrap.prepare_venv(root)
    executable = bootstrap.environment_python(environment)
    assert bootstrap.probe_runtime(executable) == host_runtime_policy
    marker = environment / "installed-requirements.txt"
    marker.write_bytes(b"existing dependency marker")
    before = executable.stat().st_mtime_ns
    assert bootstrap.prepare_venv(root) == environment
    assert executable.stat().st_mtime_ns == before
    assert marker.read_bytes() == b"existing dependency marker"
    assert (data / "brain-and-accounts.txt").read_bytes() == b"saved state is never a setup input"
    assert not list(root.glob(".venv-backup-*"))


def test_actual_replacement_preserves_incompatible_environment_and_data(tmp_path, host_runtime_policy):
    old = tmp_path / ".venv"
    old.mkdir()
    (old / "old-installed-files.bin").write_bytes(b"unsupported old environment")
    data = tmp_path / "data"
    data.mkdir()
    (data / "clip.mp4").write_bytes(b"owner media unchanged")
    bootstrap.prepare_venv(tmp_path)
    assert bootstrap.probe_runtime(bootstrap.environment_python(old)) == host_runtime_policy
    backups = list(tmp_path.glob(".venv-backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "old-installed-files.bin").read_bytes() == b"unsupported old environment"
    assert (data / "clip.mp4").read_bytes() == b"owner media unchanged"
    assert not list(tmp_path.glob(".venv-failed-*"))


def test_failed_creation_preserves_partial_and_restores_old_environment(tmp_path, monkeypatch):
    old = tmp_path / ".venv"
    old.mkdir()
    (old / "original.txt").write_bytes(b"restore me")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/clip.mp4").write_bytes(b"unchanged")
    monkeypatch.setattr(bootstrap, "probe_runtime", lambda executable: None)

    def fail(command, **kwargs):
        assert command == [sys.executable, "-m", "venv", str(old)]
        old.mkdir()
        (old / "partial.txt").write_bytes(b"keep partial too")
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(bootstrap.subprocess, "run", fail)
    with pytest.raises(bootstrap.BootstrapError, match="not changed"):
        bootstrap.prepare_venv(tmp_path)
    assert (old / "original.txt").read_bytes() == b"restore me"
    failed = list(tmp_path.glob(".venv-failed-*"))
    assert len(failed) == 1
    assert (failed[0] / "partial.txt").read_bytes() == b"keep partial too"
    assert not list(tmp_path.glob(".venv-backup-*"))
    assert (tmp_path / "data/clip.mp4").read_bytes() == b"unchanged"


def test_known_active_environment_refuses_replacement_without_moving_files(tmp_path, monkeypatch):
    old = tmp_path / ".venv"
    old.mkdir()
    (old / "original.txt").write_bytes(b"running app")
    monkeypatch.setattr(bootstrap, "probe_runtime", lambda executable: None)
    original = bootstrap.assert_environment_stopped

    def active(environment):
        original(environment, [environment / "Scripts/python.exe"])

    monkeypatch.setattr(bootstrap, "assert_environment_stopped", active)
    with pytest.raises(bootstrap.BootstrapError, match="still using"):
        bootstrap.prepare_venv(tmp_path)
    assert (old / "original.txt").read_bytes() == b"running app"
    assert not list(tmp_path.glob(".venv-backup-*"))


def test_neighbor_environment_is_not_mistaken_for_this_app(tmp_path):
    bootstrap.assert_environment_stopped(tmp_path / ".venv", [tmp_path / ".venv-other/Scripts/python.exe"])


def test_concurrent_setup_cannot_replace_or_create_environment(tmp_path):
    with bootstrap.setup_lock(tmp_path):
        with pytest.raises(bootstrap.BootstrapError, match="Another ClipFoundry setup"):
            bootstrap.prepare_venv(tmp_path)
    assert not (tmp_path / ".venv").exists()


@pytest.mark.skipif(os.name == "nt", reason="Unprivileged symlink creation needs additional Windows policy")
def test_linked_environment_is_preserved_instead_of_replaced(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    (target / "keep.txt").write_bytes(b"outside file")
    (tmp_path / ".venv").symlink_to(target, target_is_directory=True)
    with pytest.raises(bootstrap.BootstrapError, match="folder is a link"):
        bootstrap.prepare_venv(tmp_path)
    assert (target / "keep.txt").read_bytes() == b"outside file"
    assert (tmp_path / ".venv").is_symlink()


def test_batch_prefers_verified_python_and_checks_environment_before_pip():
    body = (Path(bootstrap.__file__).parent / "start.bat").read_text()
    probes = ["py -3.12-64", "py -3.12 ", "py -3.11-64", "py -3.11 "]
    assert [body.index(probe) for probe in probes] == sorted(body.index(probe) for probe in probes)
    assert '"%CLIPFOUNDRY_BOOTSTRAP_PYTHON%" "%~dp0windows_bootstrap.py" --check-python' in body
    assert body.index("--prepare-venv") < body.index('"%VPY%" -m pip install')
    assert "PYTHON_MANAGER_AUTOMATIC_INSTALL=false" in body
    assert 'set "PYLAUNCHER_ALLOW_INSTALL="' in body
    assert "DisableDelayedExpansion" in body
    assert "py -3 " not in body
    assert b"\r\n" in (Path(bootstrap.__file__).parent / "start.bat").read_bytes()


def _function(callback):
    class Function:
        def __call__(self, *args):
            return callback(*args)
    return Function()


def test_windows_process_probe_keeps_full_handle_width_and_releases_every_handle(monkeypatch):
    from ctypes import wintypes
    entries = iter([(1, "other.exe"), (2, "python.exe"), (3, "PYTHONW.EXE"), (4, "python.exe")])
    opened, closed = [], []

    def next_entry(snapshot, pointer):
        assert snapshot == 0x567890123
        try:
            pointer._obj.pid, pointer._obj.name = next(entries)
            return 1
        except StopIteration:
            return 0

    def open_process(access, inherited, pid):
        opened.append((access, inherited, pid))
        return 0 if pid == 4 else pid + 100

    def query(process, flags, buffer, size):
        assert flags == 0 and size._obj.value >= 32768
        buffer.value = r"C:\CF14\.venv\Scripts\python.exe" if process == 102 else r"C:\Other\pythonw.exe"
        size._obj.value = len(buffer.value)
        return 1

    kernel = types.SimpleNamespace(
        CreateToolhelp32Snapshot=_function(lambda flags, pid: 0x567890123),
        Process32FirstW=_function(next_entry), Process32NextW=_function(next_entry),
        OpenProcess=_function(open_process), QueryFullProcessImageNameW=_function(query),
        CloseHandle=_function(lambda handle: closed.append(handle)),
    )
    monkeypatch.setattr(bootstrap.ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(bootstrap.ctypes, "get_last_error", lambda: 18, raising=False)
    paths = bootstrap.windows_python_paths()
    assert paths == [Path(r"C:\CF14\.venv\Scripts\python.exe"), Path(r"C:\Other\pythonw.exe")]
    assert opened == [(0x1000, False, pid) for pid in (2, 3, 4)]
    assert closed == [102, 103, 0x567890123]
    assert kernel.CreateToolhelp32Snapshot.restype is wintypes.HANDLE
    assert kernel.OpenProcess.restype is wintypes.HANDLE


def test_incomplete_windows_process_snapshot_refuses_without_leaking_snapshot(monkeypatch):
    closed = []
    kernel = types.SimpleNamespace(
        CreateToolhelp32Snapshot=_function(lambda flags, pid: 12),
        Process32FirstW=_function(lambda *args: 0), Process32NextW=_function(lambda *args: 0),
        OpenProcess=_function(lambda *args: 0), QueryFullProcessImageNameW=_function(lambda *args: 0),
        CloseHandle=_function(lambda handle: closed.append(handle)),
    )
    monkeypatch.setattr(bootstrap.ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(bootstrap.ctypes, "get_last_error", lambda: 5, raising=False)
    with pytest.raises(bootstrap.BootstrapError, match="could not finish checking"):
        bootstrap.windows_python_paths()
    assert closed == [12]

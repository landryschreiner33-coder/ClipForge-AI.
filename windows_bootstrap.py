"""Prepare the supported Windows Python environment without importing the app.

Only the standard library is used. Runtime probes never change files; replacing
an incompatible environment preserves it and never changes the application's data.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import sysconfig
import uuid


class BootstrapError(Exception):
    pass


def runtime_details():
    return {"implementation": sys.implementation.name,
            "version": list(sys.version_info[:3]), "bits": struct.calcsize("P") * 8,
            "platform": sysconfig.get_platform(),
            "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED"))}


def compatible_runtime(details):
    if not isinstance(details, dict):
        return False
    version = details.get("version")
    return (details.get("implementation") == "cpython"
            and isinstance(version, list) and len(version) == 3
            and all(type(part) is int for part in version)
            and version[:2] in ([3, 12], [3, 11])
            and type(details.get("bits")) is int and details["bits"] == 64
            and details.get("platform") == "win-amd64"
            and details.get("free_threaded") is False)


def runtime_label(details):
    version = ".".join(str(part) for part in details["version"])
    return "CPython " + version + " (" + str(details["bits"]) + "-bit, " + details["platform"] + ")"


def probe_runtime(executable):
    try:
        result = subprocess.run([str(executable), str(Path(__file__).absolute()), "--runtime-json"],
                                check=False, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=20)
        if result.returncode:
            return None
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _reparse(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


@contextmanager
def setup_lock(root):
    path = root / ".venv-setup.lock"
    if _reparse(path):
        raise BootstrapError("The environment setup lock is a link. No environment was changed.")
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BootstrapError("Another ClipFoundry setup is running. Keep its window open and retry later.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def windows_python_paths():
    """Inspect executable paths only; never stop or modify any running process."""
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("name", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value or not snapshot:
        raise BootstrapError("Windows could not check running apps. Close ClipFoundry and retry.")
    result = []
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.name.lower() in ("python.exe", "pythonw.exe"):
                process = kernel.OpenProcess(0x1000, False, entry.pid)
                if process:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buffer))
                        if kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                            result.append(Path(buffer.value))
                    finally:
                        kernel.CloseHandle(process)
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:
            raise BootstrapError("Windows could not finish checking running apps. Close ClipFoundry and retry.")
    finally:
        kernel.CloseHandle(snapshot)
    return result


def assert_environment_stopped(environment, processes=None):
    if processes is None:
        processes = windows_python_paths() if os.name == "nt" else []
    prefix = os.path.normcase(os.path.abspath(environment)) + os.sep
    if any(os.path.normcase(os.path.abspath(path)).startswith(prefix) for path in processes):
        raise BootstrapError("ClipFoundry is still using this environment. Close its other windows and retry.")


def preserved_path(root, kind):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return root / (".venv-" + kind + "-" + stamp + "-" + uuid.uuid4().hex[:8])


def environment_python(environment):
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def prepare_venv(root):
    root = Path(root).resolve(strict=True)
    environment = root / ".venv"
    with setup_lock(root):
        if _reparse(environment):
            raise BootstrapError("The .venv folder is a link. Keep it intact and use a fresh extracted app folder.")
        details = probe_runtime(environment_python(environment))
        if compatible_runtime(details):
            print("Using existing environment:", runtime_label(details))
            return environment
        backup = None
        if environment.exists():
            assert_environment_stopped(environment)
            backup = preserved_path(root, "backup")
            try:
                environment.rename(backup)
            except OSError as exc:
                raise BootstrapError("The incompatible .venv is in use or cannot be moved. "
                                     "Close ClipFoundry and retry.") from exc
            print("Preserved incompatible environment:", backup.name)
        print("Creating environment with", runtime_label(runtime_details()))
        try:
            result = subprocess.run([sys.executable, "-m", "venv", str(environment)], check=False)
            if result.returncode or not compatible_runtime(probe_runtime(environment_python(environment))):
                raise BootstrapError("The new Python environment could not be created or verified.")
        except (OSError, BootstrapError) as exc:
            # Do not delete either the old environment or a partially created one.
            try:
                if environment.exists():
                    partial = preserved_path(root, "failed")
                    environment.rename(partial)
                    print("Preserved incomplete environment:", partial.name)
                if backup is not None:
                    backup.rename(environment)
                    print("Restored the previous environment without changing app data.")
            except OSError:
                raise BootstrapError("Setup stopped. The old and incomplete environments were preserved. "
                                     "Close ClipFoundry, then retry in a fresh extracted app folder.") from exc
            raise BootstrapError(str(exc) + " Your Brain, accounts, videos and app data were not changed. "
                                 "Install 64-bit Python 3.12 from python.org and reopen this launcher.") from exc
        return environment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--check-python", action="store_true")
    options.add_argument("--runtime-json", action="store_true")
    options.add_argument("--prepare-venv", metavar="APP_FOLDER")
    arguments = parser.parse_args(argv)
    if arguments.runtime_json:
        print(json.dumps(runtime_details()))
        return 0
    if arguments.check_python:
        return 0 if compatible_runtime(runtime_details()) else 1
    if not compatible_runtime(runtime_details()):
        print("Setup needs standard 64-bit CPython 3.12 or 3.11 for Windows AMD64. "
              "Install Python 3.12 (Windows installer 64-bit) from "
              "https://www.python.org/downloads/release/python-31210/.",
              file=sys.stderr)
        return 1
    try:
        prepare_venv(arguments.prepare_venv)
    except (OSError, BootstrapError) as exc:
        print("Environment setup could not finish:", exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Readable Windows ClipFoundry setup using only Python's standard library.

The accompanying app.zip is a fixed, checked source build. No app download, custom
executable, PowerShell loader, antivirus exception or administrator access is used.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass

COMMIT = "718358f30110ab871e21059177f83ccd9ea3d3a9"
ARCHIVE_HASH = "2975806f4366bf2eba491b93e0634cf4f88083ce327657cf5ffc84456ac2d0cc"
START_HASH = "40cfe91a8c4818f6837d794beca0b610fa9d45863c381ea1dafd27c427e9f23c"
ARCHIVE_PREFIX = "ClipForge-AI.-" + COMMIT + "/"
KNOWN_RELEASES = {
    revision: START_HASH for revision in (
        "28aee85b4ef239584da296cec900bc3d8dde4399",
        "4838aa897e59b68a1365dd7ed7f4d60f52dfcc8c",
        "7201047b795085f0cb608ea643efadf90074290c",
        "987ebb288ae9097bedbd80d0adee2b3c05c4271f",
        COMMIT,
    )
}
MARKER = ".clipfoundry-oneclick.json"
RUNNING_ERROR = "ClipFoundry is still running. Close its app/setup windows, then reopen this installer."


class SetupError(RuntimeError):
    pass


def file_hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def absolute(path: Path) -> Path:
    # resolve() follows links; verification must inspect the original path instead.
    return Path(os.path.abspath(path))


def path_key(path: Path) -> str:
    return os.path.normcase(str(absolute(path)))


def no_reparse_path(path: Path) -> bool:
    try:
        current = absolute(path)
        for part in (current, *current.parents):
            try:
                info = part.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return False
        return True
    except OSError:
        return False


def managed_marker(root: Path, owner: str, strict: bool = False) -> dict | None:
    marker_file = root / MARKER
    try:
        if not no_reparse_path(root) or not no_reparse_path(marker_file):
            return None
        if marker_file.stat().st_size > 16384:
            return None
        marker = json.loads(marker_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(marker, dict) or marker.get("kind") not in (
        "clipfoundry-oneclick-v1", "clipfoundry-oneclick-v2"
    ) or marker.get("owner") != owner:
        return None
    revision = marker.get("commit")
    if not isinstance(revision, str) or revision not in KNOWN_RELEASES:
        if strict:
            raise SetupError("An existing managed app has an unrecognized revision. Its data was left unchanged.")
        return None
    try:
        start = root / "start.bat"
        matches = no_reparse_path(start) and file_hash(start) == KNOWN_RELEASES[revision]
    except OSError:
        matches = False
    if not matches:
        if strict:
            raise SetupError("An existing managed app could not be verified. Its data was left unchanged.")
        return None
    return marker


def managed_profile(root: Path, owner: str, roots: list[Path]) -> Path:
    marker = managed_marker(root, owner, strict=True)
    if not marker:
        raise SetupError("The managed app profile could not be verified. No existing data was changed.")
    value = str(root) if marker["kind"] == "clipfoundry-oneclick-v1" else marker.get("data_root")
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise SetupError("The managed app profile path is invalid. No existing data was changed.")
    profile = absolute(Path(value))
    if path_key(profile) not in {path_key(candidate) for candidate in roots} or not no_reparse_path(profile / "data"):
        raise SetupError("The managed app profile is outside a verified installation. No existing data was changed.")
    origin = managed_marker(profile, owner, strict=True)
    if not origin:
        raise SetupError("The original managed app profile could not be verified. No existing data was changed.")
    if origin["kind"] == "clipfoundry-oneclick-v2" and (
        not isinstance(origin.get("data_root"), str) or path_key(Path(origin["data_root"])) != path_key(profile)
    ):
        raise SetupError("The managed app profile has an unexpected chain. No existing data was changed.")
    return profile


def local_app_data() -> Path:
    from ctypes import wintypes
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    buffer = ctypes.create_unicode_buffer(32768)
    if shell.SHGetFolderPathW(None, 28, None, 0, buffer) != 0 or not buffer.value:
        raise SetupError("Windows could not locate your local application folder. No files were changed.")
    return Path(buffer.value)


def install_roots(bases: list[Path] | None = None) -> list[Path]:
    if bases is None:
        bases = []
        drive = os.environ.get("SystemDrive", "")
        if re.fullmatch(r"[A-Za-z]:", drive):
            bases.append(Path(drive + "\\CF14"))
        bases.append(local_app_data() / "CF14")
    result = []
    seen = set()
    for base in bases:
        candidates = [Path(str(base) + suffix) for suffix in ("", "-Open", "-Open2", "-Open3", "-Open4")]
        versioned = str(base) + "-" + COMMIT[:12]
        candidates.extend([Path(versioned)] + [Path(versioned + "-" + str(number)) for number in range(2, 10)])
        pattern = re.compile(re.escape(base.name) + r"-[0-9a-f]{12}(?:-[2-9])?")
        try:
            children = sorted(
                (child for child in base.parent.iterdir() if pattern.fullmatch(child.name) and child.is_dir()),
                key=lambda child: child.name,
            )
        except OSError:
            children = []
        if len(children) > 512:
            raise SetupError("Too many managed app folders were found. No files were changed.")
        candidates.extend(children)
        for candidate in candidates:
            key = path_key(candidate)
            if len(str(candidate)) <= 100 and key not in seen:
                seen.add(key)
                result.append(candidate)
    return result


@dataclass
class Install:
    root: Path
    data_root: Path
    stage: Path | None = None


def remove_owned_stage(stage: Path | None, owner: str) -> None:
    if not stage or not no_reparse_path(stage):
        return
    try:
        stamp = stage / ".owned-stage"
        if not no_reparse_path(stamp) or stamp.read_text(encoding="utf-8") != owner:
            return
        shutil.rmtree(stage)
    except OSError:
        pass  # Cleanup must not replace the useful setup error or remove an unknown folder.


def find_install(roots: list[Path], owner: str) -> Install:
    entries = []
    for root in roots:
        if not root.is_dir():
            continue
        marker = managed_marker(root, owner, strict=True)
        if not marker:
            continue
        profile = managed_profile(root, owner, roots)
        entry = Install(root, profile)
        entries.append((entry, marker["commit"]))
    profiles = {path_key(entry.data_root): entry.data_root for entry, _ in entries}
    if len(profiles) > 1:
        raise SetupError("More than one managed data folder was found. No profiles were combined or changed.")
    for entry, revision in entries:
        if revision == COMMIT:
            return entry
    profile = next(iter(profiles.values()), None)
    for root in roots:
        if root.exists() or root.is_symlink():
            continue
        stage = None
        try:
            if not root.parent.is_dir() or not no_reparse_path(root.parent):
                continue
            stage = Path(tempfile.mkdtemp(prefix="CFsetup-", dir=root.parent))
            (stage / ".owned-stage").write_text(owner, encoding="utf-8")
            return Install(root, profile or root, stage)
        except OSError:
            remove_owned_stage(stage, owner)
    raise SetupError("Could not find a writable short installation folder. No existing installation was changed.")


def write_marker(app: Path, data_root: Path, owner: str) -> None:
    payload = {"kind": "clipfoundry-oneclick-v2", "commit": COMMIT, "owner": owner,
               "data_root": str(absolute(data_root))}
    (app / MARKER).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def checked_entries(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    result = []
    seen = set()
    total = 0
    entries = archive.infolist()
    if len(entries) > 20000:
        raise SetupError("Unexpected archive size.")
    reserved = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", re.I)
    for entry in entries:
        name = entry.filename
        if not name.startswith(ARCHIVE_PREFIX):
            raise SetupError("Unexpected archive folder.")
        relative = name[len(ARCHIVE_PREFIX):]
        if not relative:
            continue
        parts = relative.rstrip("/").split("/")
        if ("\\" in relative or ":" in relative or "\x00" in relative or relative.startswith("/")
                or any(part in ("", ".", "..") or part[-1:] in (".", " ") or reserved.fullmatch(part)
                       for part in parts)):
            raise SetupError("Unexpected archive path.")
        if any(ord(char) < 32 or char in '<>"|?*' for char in relative):
            raise SetupError("Unexpected archive path.")
        path = PurePosixPath(*parts)
        key = str(path).casefold()
        if key in seen:
            raise SetupError("Duplicate archive path.")
        seen.add(key)
        mode = entry.external_attr >> 16
        if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise SetupError("Unexpected archive file type.")
        total += entry.file_size
        if entry.file_size > 512 * 1024 * 1024 or total > 1024 * 1024 * 1024:
            raise SetupError("Unexpected archive size.")
        result.append((entry, path))
    return result


def expand_checked_archive(zip_path: Path, app: Path) -> None:
    if not no_reparse_path(zip_path) or file_hash(zip_path) != ARCHIVE_HASH:
        raise SetupError("The app archive did not match the verified build. Download a fresh source package and retry.")
    if app.exists() or not no_reparse_path(app):
        raise SetupError("The fresh extraction folder is unavailable. No existing installation was changed.")
    with zipfile.ZipFile(zip_path) as archive:
        entries = checked_entries(archive)  # Validate every name before creating any app file.
        app.mkdir()
        for entry, relative in entries:
            target = app.joinpath(*relative.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination, 1024 * 1024)
    if (file_hash(app / "start.bat") != START_HASH or not (app / "frontend/dist/index.html").is_file()
            or (app / ".venv").exists() or (app / "data").exists() or (app / MARKER).exists()):
        raise SetupError("The installation is incomplete or contains unexpected profile data. No old files were changed.")


def exclusive_move(source: Path, destination: Path) -> None:
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        kernel.MoveFileExW.restype = wintypes.BOOL
        if not kernel.MoveFileExW(str(source), str(destination), 0):
            raise SetupError("The installation destination changed. No existing folder was replaced.")
    else:
        # Linux-only test equivalent of Windows' no-replace move; runtime setup rejects non-Windows.
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise SetupError("No exclusive directory-move primitive is available.")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
            raise SetupError("The installation destination changed. No existing folder was replaced.")


def windows_owner() -> str:
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise SetupError("Windows could not verify your user identity. No files were changed.")
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not size.value or size.value > 1024 * 1024:
            raise SetupError("Windows could not verify your user identity. No files were changed.")
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise SetupError("Windows could not verify your user identity. No files were changed.")
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        text = ctypes.c_void_p()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise SetupError("Windows could not verify your user identity. No files were changed.")
        try:
            result = ctypes.wstring_at(text)
            if not re.fullmatch(r"S-1-[0-9]+(?:-[0-9]+)+", result):
                raise SetupError("Windows returned an unexpected user identity. No files were changed.")
            return result
        finally:
            kernel.LocalFree(text)
    finally:
        kernel.CloseHandle(token)


class WindowsMutex:
    def __init__(self, owner: str):
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateMutexW(None, False, "Local\\ClipFoundryOneClick-" + owner)
        self.held = False
        if not self.handle:
            raise SetupError("Windows could not create the setup lock. No files were changed.")

    def __enter__(self):
        state = self.kernel.WaitForSingleObject(self.handle, 0)
        self.held = state in (0, 0x80)  # WAIT_OBJECT_0 or an abandoned previous owner.
        if state not in (0, 0x80, 0x102):
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise SetupError("Windows could not check the setup lock. No files were changed.")
        return self

    def __exit__(self, *unused):
        if self.held:
            self.kernel.ReleaseMutex(self.handle)
        if self.handle:
            self.kernel.CloseHandle(self.handle)


def windows_python_paths() -> list[Path]:
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
        raise SetupError("Windows could not check running apps. Close ClipFoundry and retry.")
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
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES; fail closed on partial enumeration.
            raise SetupError("Windows could not finish checking running apps. Close ClipFoundry and retry.")
    finally:
        kernel.CloseHandle(snapshot)
    return result


def probe_lock(path: Path) -> None:
    if not no_reparse_path(path):
        raise SetupError("The app lock path could not be verified. No data was changed.")
    try:
        with path.open("r+b") as stream:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.lockf(stream, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0, os.SEEK_SET)
                fcntl.lockf(stream, fcntl.LOCK_UN, 1, 0, os.SEEK_SET)
    except OSError as exc:
        raise SetupError(RUNNING_ERROR) from exc


def assert_profile_stopped(data_root: Path, roots: list[Path], owner: str,
                           processes: list[Path] | None = None) -> None:
    locks = data_root / "data/locks"
    if not no_reparse_path(locks):
        raise SetupError("The app lock folder could not be verified. No data was changed.")
    try:
        lock_folder = locks.stat()
    except FileNotFoundError:
        lock_folder = None
    except OSError as exc:
        raise SetupError("The app lock folder could not be inspected. No data was changed.") from exc
    if lock_folder:
        if not stat.S_ISDIR(lock_folder.st_mode):
            raise SetupError("The app lock folder is not a directory. No data was changed.")
        try:
            # iterdir propagates scan failures. glob/is_file can silently omit a
            # dangling reparse point which the app would follow when creating a lock.
            for file in locks.iterdir():
                if not file.name.casefold().endswith(".lock"):
                    continue
                if not no_reparse_path(file) or not stat.S_ISREG(file.lstat().st_mode):
                    raise SetupError("The app lock path could not be verified. No data was changed.")
                probe_lock(file)
        except OSError as exc:
            raise SetupError("The app lock folder could not be inspected. No data was changed.") from exc
    if processes is None:
        processes = windows_python_paths() if os.name == "nt" else []
    for root in roots:
        if not managed_marker(root, owner):
            continue
        if path_key(managed_profile(root, owner, roots)) != path_key(data_root):
            continue
        prefix = path_key(root / ".venv") + os.sep
        if any(path_key(process).startswith(prefix) for process in processes):
            raise SetupError(RUNNING_ERROR)


def free_port() -> int:
    for port in range(8765, 8776):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                listener.bind(("127.0.0.1", port))
                listener.listen(1)
                return port
            except OSError:
                pass
    raise SetupError("The ClipFoundry browser ports are busy. Close its other window and retry.")


def system_cmd() -> Path:
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    kernel.GetSystemDirectoryW.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    size = kernel.GetSystemDirectoryW(buffer, len(buffer))
    if not size or size >= len(buffer):
        raise SetupError("Windows could not locate its command interpreter. No app was started.")
    return Path(buffer.value) / "cmd.exe"


def invoke_launcher(root: Path, setup_only: bool, environment: dict[str, str]) -> None:
    env = dict(environment)
    env["CF_BOOTSTRAP_START"] = str(root / "start.bat")
    cmd = system_cmd()
    suffix = " --setup-only" if setup_only else ""
    # Paths are expanded once inside quotes; /d and /v:off avoid AutoRun/delayed expansion.
    # No downloaded/user text is interpolated into the command body.
    command = '"' + str(cmd) + '" /d /v:off /s /c ""%CF_BOOTSTRAP_START%"' + suffix + '"'
    result = subprocess.run(command, executable=str(cmd), cwd=root, env=env, shell=False, check=False)
    if result.returncode:
        raise SetupError("Setup stopped. Keep the error above and reopen this installer to retry.")


def start_setup(package: Path) -> None:
    if os.name != "nt":
        raise SetupError("This setup is for Windows 10 or Windows 11.")
    if sys.version_info < (3, 11):
        raise SetupError("ClipFoundry needs Python 3.11 or newer. Install Python, then reopen this setup.")
    owner = windows_owner()
    with WindowsMutex(owner) as mutex:
        if not mutex.held:
            print("ClipFoundry is already starting or running. Keep its first window open.")
            return
        install = None
        try:
            roots = install_roots()
            install = find_install(roots, owner)
            assert_profile_stopped(install.data_root, roots, owner)
            if install.stage:
                archive = package / "app.zip"
                if not archive.is_file():
                    raise SetupError("The included app.zip is missing. Extract the complete source package and retry.")
                print("Preparing the included, verified app files in a short folder...")
                app = install.stage / "app"
                expand_checked_archive(archive, app)
                write_marker(app, install.data_root, owner)
                exclusive_move(app, install.root)
            environment = dict(os.environ)
            environment["CLIPFOUNDRY_DATA"] = str(install.data_root / "data")
            environment.pop("CLIPFOUNDRY_WORKERS", None)
            print("ClipFoundry folder:", install.root)
            print("Your saved Brain, accounts and clips:", environment["CLIPFOUNDRY_DATA"])
            print("First-time dependency setup can take several minutes. Keep this window open.")
            invoke_launcher(install.root, True, environment)
            assert_profile_stopped(install.data_root, roots, owner)
            port = free_port()
            environment["CLIPFOUNDRY_PORT"] = str(port)
            print("The app will open at http://127.0.0.1:" + str(port))
            invoke_launcher(install.root, False, environment)
        finally:
            if install:
                remove_owned_stage(install.stage, owner)


def main() -> int:
    print("ClipFoundry - readable Python setup")
    try:
        start_setup(Path(__file__).absolute().parent)
    except (SetupError, OSError, zipfile.BadZipFile) as exc:
        print("Setup could not finish:", exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

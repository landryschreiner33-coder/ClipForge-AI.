"""Build an inspectable source launcher from the already pinned application, without a compiled wrapper."""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile


def python_pins(source: bytes) -> dict[str, str]:
    pins = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("COMMIT", "ARCHIVE_HASH", "START_HASH"):
                    if target.id in pins or not isinstance(node.value, ast.Constant):
                        raise ValueError("The Python launcher must have unique literal application pins")
                    pins[target.id] = node.value.value
    return pins


def validate_archive(archive: bytes, revision: str, start_hash: str) -> int:
    import io

    prefix = f"ClipForge-AI.-{revision}/"
    reserved = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", re.I)
    seen = set()
    files = 0
    total = 0
    with zipfile.ZipFile(io.BytesIO(archive)) as payload:
        entries = payload.infolist()
        if len(entries) > 20000 or payload.testzip() is not None:
            raise ValueError("The app archive is damaged or unexpectedly large")
        for entry in entries:
            if not entry.filename.startswith(prefix):
                raise ValueError("The application wrapper does not name its pinned revision")
            relative = entry.filename[len(prefix):]
            if not relative:
                continue
            parts = relative.rstrip("/").split("/")
            if ("\\" in relative or ":" in relative or relative.startswith("/")
                    or any(ord(char) < 32 or char in '<>\"|?*' for char in relative)
                    or any(part in ("", ".", "..") or part[-1:] in (".", " ") or reserved.fullmatch(part)
                           for part in parts)):
                raise ValueError("The application contains an unsafe Windows path")
            key = "/".join(parts).casefold()
            if key in seen:
                raise ValueError("The application contains duplicate Windows paths")
            seen.add(key)
            mode = entry.external_attr >> 16
            if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError("The application contains an unsupported file type")
            if parts[0].lower() in (".venv", "data", ".clipfoundry-oneclick.json"):
                raise ValueError("The application unexpectedly contains local profile data")
            if relative.lower().endswith((".exe", ".dll")):
                raise ValueError("The source distribution unexpectedly contains a Windows executable")
            total += entry.file_size
            if entry.file_size > 512 * 1024 * 1024 or total > 1024 * 1024 * 1024:
                raise ValueError("The application is unexpectedly large")
            files += not entry.is_dir()
        if hashlib.sha256(payload.read(prefix + "start.bat")).hexdigest() != start_hash:
            raise ValueError("The app launcher does not match its verified pin")
        payload.getinfo(prefix + "frontend/dist/index.html")
    return files


def build(directory: Path, destination: Path) -> dict:
    setup = (directory / "plain_setup.py").read_bytes()
    archive = (directory / "app.zip").read_bytes()
    script = (directory / "bootstrap.ps1").read_text()
    matches = {key: re.search(rf"(?m)^\${key} = '([0-9a-f]{{{length}}})'$", script)
               for key, length in (("Commit", 40), ("ArchiveHash", 64), ("StartHash", 64))}
    if not all(matches.values()):
        raise ValueError("The verified bootstrap application pins were not found")
    revision = matches["Commit"].group(1)
    digest = matches["ArchiveHash"].group(1)
    start_hash = matches["StartHash"].group(1)
    if hashlib.sha256(archive).hexdigest() != digest:
        raise ValueError("The generated application archive does not match its verified pin")
    if python_pins(setup) != {"COMMIT": revision, "ARCHIVE_HASH": digest, "START_HASH": start_hash}:
        raise ValueError("The Python launcher needs the same exact application pins")
    app_files = validate_archive(archive, revision, start_hash)
    command = (directory / "Open-ClipFoundry.cmd").read_bytes()
    command = command.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    members = {"Open-ClipFoundry.cmd": command, "setup.py": setup, "app.zip": archive,
               "README.txt": (directory / "PLAIN_SETUP_README.txt").read_bytes()}
    handle, temporary = tempfile.mkstemp(prefix=".plain-setup-", suffix=".zip", dir=destination.parent)
    os.close(handle)
    temporary = Path(temporary)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
            for name, data in members.items():
                info = zipfile.ZipInfo(name, date_time=(2026, 10, 13, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                package.writestr(info, data)
        with zipfile.ZipFile(temporary) as package:
            if set(package.namelist()) != set(members) or package.testzip() is not None:
                raise ValueError("The source launcher ZIP did not verify")
            for name, data in members.items():
                if package.read(name) != data:
                    raise ValueError(f"The source launcher ZIP changed {name}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"source_commit": revision, "app_archive_sha256": digest, "zip_bytes": destination.stat().st_size,
            "zip_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "members_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in members.items()},
            "app_files": app_files, "no_custom_exe": True, "defender_acceptance_verified": False,
            "native_windows_verified": False}


if __name__ == "__main__":
    import json

    root = Path(__file__).resolve().parent
    result = build(root, root.parent / "ClipFoundry-Source-Setup.zip")
    print(json.dumps(result, indent=2))

"""Pin a verified app ZIP and sync both bootstrap entry points before building the EXE."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile


def pin_bundle(archive: Path, commit: str, directory: Path) -> tuple[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit must be an exact lower-case Git SHA")
    prefix = f"ClipForge-AI.-{commit}/"
    with zipfile.ZipFile(archive) as payload:
        for entry in payload.infolist():
            if not entry.filename.startswith(prefix):
                raise ValueError("archive contains another revision folder")
            relative = entry.filename[len(prefix):]
            if "\\" in relative or ":" in relative or ".." in relative.split("/") or relative.startswith("/"):
                raise ValueError("archive contains an unsafe path")
        start_hash = hashlib.sha256(payload.read(prefix + "start.bat")).hexdigest()
        payload.getinfo(prefix + "frontend/dist/index.html")
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    script_path = directory / "bootstrap.ps1"
    script = script_path.read_text(encoding="utf-8")
    old_commit = re.search(r"(?m)^\$Commit = '([0-9a-f]{40})'$", script)
    old_start = re.search(r"(?m)^\$StartHash = '([0-9a-f]{64})'$", script)
    release_table = re.search(r"(?s)\$KnownReleases = @\{(.*?)\n\$KnownReleases\[\$Commit\]", script)
    if not old_commit or not old_start or not release_table:
        raise ValueError("bootstrap release pins were not found")
    known = dict(re.findall(r"'([0-9a-f]{40})'\s*=\s*'([0-9a-f]{64})'", release_table.group(1)))
    known[old_commit.group(1)] = old_start.group(1)
    rows = (f"    '{revision}' = '{digest}'" for revision, digest in sorted(known.items()))
    table = "$KnownReleases = @{\n" + "\n".join(rows) + "\n}"
    script = script[:release_table.start()] + table + script[release_table.end() - len("\n$KnownReleases[$Commit]"):]
    for name, value in (("Commit", commit), ("ArchiveHash", archive_hash), ("StartHash", start_hash)):
        script, count = re.subn(rf"(?m)^\${name} = '[0-9a-f]+'$", f"${name} = '{value}'", script, count=1)
        if count != 1:
            raise ValueError(f"missing {name} pin")
    bat_path = directory.parent / "Open-ClipFoundry.bat"
    header = bat_path.read_text(encoding="utf-8").split("# CF_POWERSHELL_BEGIN\n", 1)[0]
    if not header.endswith("\n") or "# CF_POWERSHELL_BEGIN\n" not in bat_path.read_text(encoding="utf-8"):
        raise ValueError("BAT bootstrap wrapper was not found")
    # app.zip is a generated payload, never owner data. Replace only this known build input.
    if archive.resolve() != (directory / "app.zip").resolve():
        fd, temporary = tempfile.mkstemp(prefix=".app-", suffix=".zip", dir=directory)
        os.close(fd)
        try:
            shutil.copyfile(archive, temporary)
            os.replace(temporary, directory / "app.zip")
        finally:
            Path(temporary).unlink(missing_ok=True)
    script_path.write_text(script, encoding="utf-8")
    with bat_path.open("w", encoding="utf-8", newline="\r\n") as output:
        output.write(header + "# CF_POWERSHELL_BEGIN\n" + script)
    return archive_hash, start_hash


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--archive", required=True, type=Path)
    args = parser.parse_args()
    archive_hash, start_hash = pin_bundle(args.archive, args.commit, Path(__file__).resolve().parent)
    print(f"App revision: {args.commit}\nArchive SHA-256: {archive_hash}\nstart.bat SHA-256: {start_hash}")


if __name__ == "__main__":
    main()

"""Pin a checked source ZIP and preserve managed-profile history in every source launcher.

This updates build inputs only. It does not build or run the historical EXE wrapper.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
import zipfile

from build_plain_zip import validate_archive


PIN_NAMES = {"COMMIT": ("Commit", 40), "ARCHIVE_HASH": ("ArchiveHash", 64), "START_HASH": ("StartHash", 64)}


def python_release_pins(source: str) -> tuple[dict[str, str], dict[str, str], dict[str, ast.Assign]]:
    """Read literal pins without executing the setup module or its Windows APIs."""
    assignments = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in (*PIN_NAMES, "KNOWN_RELEASES"):
                if target.id in assignments or len(node.targets) != 1:
                    raise ValueError("Python release pins must have unique assignments")
                assignments[target.id] = node
    if set(assignments) != {*PIN_NAMES, "KNOWN_RELEASES"}:
        raise ValueError("Python release pins were not found")
    pins = {}
    for name, (_, length) in PIN_NAMES.items():
        node = assignments[name].value
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            raise ValueError("Python release pins must be literal strings")
        if not re.fullmatch(rf"[0-9a-f]{{{length}}}", node.value):
            raise ValueError("Python release pin has an invalid value")
        pins[name] = node.value
    releases = assignments["KNOWN_RELEASES"].value
    if isinstance(releases, ast.Dict):
        known = ast.literal_eval(releases)
        if len(known) != len(releases.keys):
            raise ValueError("Python release history has duplicate revisions")
    elif isinstance(releases, ast.DictComp):
        # Accept the original source launcher's exact bounded comprehension during its first upgrade.
        if len(releases.generators) != 1:
            raise ValueError("Python release history is not a supported literal map")
        generator = releases.generators[0]
        if (not isinstance(generator.target, ast.Name) or not isinstance(releases.key, ast.Name)
                or generator.target.id != releases.key.id or generator.ifs or generator.is_async
                or not isinstance(generator.iter, ast.Tuple) or not isinstance(releases.value, ast.Name)
                or releases.value.id != "START_HASH"):
            raise ValueError("Python release history is not a supported literal map")
        revisions = []
        for item in generator.iter.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                revisions.append(item.value)
            elif isinstance(item, ast.Name) and item.id == "COMMIT":
                revisions.append(pins["COMMIT"])
            else:
                raise ValueError("Python release history is not a supported literal map")
        if len(set(revisions)) != len(revisions):
            raise ValueError("Python release history has duplicate revisions")
        known = dict.fromkeys(revisions, pins["START_HASH"])
    else:
        raise ValueError("Python release history is not a supported literal map")
    if not isinstance(known, dict) or any(
            not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision)
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for revision, digest in known.items()):
        raise ValueError("Python release history contains an invalid pin")
    if known.get(pins["COMMIT"]) != pins["START_HASH"]:
        raise ValueError("Python release history does not contain its current launcher pin")
    return pins, known, assignments


def powershell_release_pins(script: str) -> tuple[dict[str, str], dict[str, str], re.Match]:
    pins = {}
    for python_name, (script_name, length) in PIN_NAMES.items():
        matches = re.findall(rf"(?m)^\${script_name} = '([0-9a-f]{{{length}}})'$", script)
        if len(matches) != 1:
            raise ValueError(f"bootstrap has no unique {script_name} pin")
        pins[python_name] = matches[0]
    tables = list(re.finditer(r"(?ms)^\$KnownReleases = @\{\n(.*?)^\}\n(?=\$KnownReleases\[\$Commit\] = \$StartHash$)",
                              script))
    if len(tables) != 1:
        raise ValueError("bootstrap release history was not found")
    table = tables[0]
    known = {}
    for row in table.group(1).splitlines():
        entry = re.fullmatch(r"\s*'([0-9a-f]{40})' = '([0-9a-f]{64})'", row)
        if not entry or entry[1] in known:
            raise ValueError("bootstrap release history has an invalid or duplicate row")
        known[entry[1]] = entry[2]
    if pins["COMMIT"] in known and known[pins["COMMIT"]] != pins["START_HASH"]:
        raise ValueError("bootstrap current launcher pin conflicts with its release history")
    known[pins["COMMIT"]] = pins["START_HASH"]
    return pins, known, table


def pin_bundle(archive: Path, commit: str, directory: Path) -> tuple[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit must be an exact lower-case Git SHA")
    archive_bytes = archive.read_bytes()
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as payload:
            start_hash = hashlib.sha256(payload.read(f"ClipForge-AI.-{commit}/start.bat")).hexdigest()
    except KeyError as error:
        raise ValueError("archive contains another revision folder or no start.bat") from error
    validate_archive(archive_bytes, commit, start_hash)
    archive_hash = hashlib.sha256(archive_bytes).hexdigest()
    script_path = directory / "bootstrap.ps1"
    python_path = directory / "plain_setup.py"
    script = script_path.read_text(encoding="utf-8")
    python = python_path.read_text(encoding="utf-8")
    old_pins, known, release_table = powershell_release_pins(script)
    python_pins, python_known, assignments = python_release_pins(python)
    if python_pins != old_pins or python_known != known:
        raise ValueError("Python and bootstrap release pins/history must agree before an update")
    if commit in known and known[commit] != start_hash:
        raise ValueError("the new payload conflicts with a verified historical launcher pin")
    new_pins = {"COMMIT": commit, "ARCHIVE_HASH": archive_hash, "START_HASH": start_hash}
    rows = (f"    '{revision}' = '{digest}'" for revision, digest in sorted(known.items()))
    table = "$KnownReleases = @{\n" + "\n".join(rows) + "\n}\n"
    script = script[:release_table.start()] + table + script[release_table.end():]
    for name, (script_name, _) in PIN_NAMES.items():
        script, count = re.subn(rf"(?m)^\${script_name} = '[0-9a-f]+'$",
                                f"${script_name} = '{new_pins[name]}'", script)
        if count != 1:
            raise ValueError(f"missing {script_name} pin")
    python_known[commit] = start_hash
    changes = {name: f'{name} = "{value}"\n' for name, value in new_pins.items()}
    changes["KNOWN_RELEASES"] = "KNOWN_RELEASES = {\n" + "\n".join(
        f'    "{revision}": "{digest}",' for revision, digest in sorted(python_known.items())
    ) + "\n}\n"
    lines = python.splitlines(keepends=True)
    for name, node in sorted(assignments.items(), key=lambda item: item[1].lineno, reverse=True):
        lines[node.lineno - 1:node.end_lineno] = [changes[name]]
    python = "".join(lines)
    updated_pins, updated_known, _ = python_release_pins(python)
    ps_pins, ps_known, _ = powershell_release_pins(script)
    if updated_pins != ps_pins or updated_known != ps_known:
        raise ValueError("updated launcher pins did not verify")
    bat_path = directory.parent / "Open-ClipFoundry.bat"
    old_bat = bat_path.read_text(encoding="utf-8")
    marker = "# CF_POWERSHELL_BEGIN\n"
    if old_bat.count(marker) != 1:
        raise ValueError("BAT bootstrap wrapper was not found")
    header = old_bat.split(marker, 1)[0]
    if not header.endswith("\n"):
        raise ValueError("BAT bootstrap header is malformed")
    # Validate every input and prepare all bytes before replacing these known build outputs.
    outputs = {
        directory / "app.zip": archive_bytes,
        script_path: script.encode("utf-8"),
        python_path: python.encode("utf-8"),
        bat_path: (header + marker + script).replace("\n", "\r\n").encode("utf-8"),
    }
    temporary_paths = []
    try:
        for destination, content in outputs.items():
            handle, temporary = tempfile.mkstemp(prefix=".pin-", dir=destination.parent)
            temporary = Path(temporary)
            temporary_paths.append((temporary, destination))
            with os.fdopen(handle, "wb") as output:
                output.write(content)
        for temporary, destination in temporary_paths:
            os.replace(temporary, destination)
    finally:
        for temporary, _ in temporary_paths:
            temporary.unlink(missing_ok=True)
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

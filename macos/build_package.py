"""Build a reviewable source setup from a clean committed tree and verified upstream runtime."""
from __future__ import annotations

import argparse
import gzip
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(root: Path, runtime: Path, output: Path) -> dict:
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root)
    if git("status", "--porcelain").strip():
        raise RuntimeError("Commit the complete tested source tree before packaging")
    revision = git("rev-parse", "HEAD").decode().strip()
    sources = json.loads((runtime / "runtime-sources.json").read_text())
    python = (runtime / "python-macos.tar.gz").read_bytes()
    if sha(python) != sources["python"]["sha256"]:
        raise ValueError("Python archive checksum failed")
    # Check the bundled runtime's paths and its executable's architecture before distribution.
    with tarfile.open(fileobj=BytesIO(python), mode="r:gz") as archive:
        for item in archive:
            if item.name.startswith("/") or ".." in Path(item.name).parts:
                raise ValueError("Unsafe Python archive member")
            if item.issym() or item.islnk():
                # This pinned build uses only relative links within the python tree.
                if item.linkname.startswith("/") or ".." in Path(item.linkname).parts:
                    raise ValueError("Unexpected Python archive link")
        executable = archive.extractfile("python/bin/python3.12").read(8)
        if executable != bytes.fromhex("cffaedfe0c000001"):
            raise ValueError("Python executable is not ARM64 Mach-O")
    selected = ["clipfoundry", "frontend/dist", "requirements.txt", "requirements-macos.txt",
                "macos", "docs/legal", "AI_HANDOFF.md", "CLAUDE_HANDOFF.md", "AI_CHANGELOG.md",
                ".clipfoundry/ai-change-log.jsonl"]
    source = git("archive", "HEAD", *selected)
    app_bytes = BytesIO()
    with tarfile.open(fileobj=BytesIO(source)) as tar, zipfile.ZipFile(
            app_bytes, "w", compression=zipfile.ZIP_DEFLATED) as app:
        for item in tar:
            if item.isfile():
                app.writestr(item.name, tar.extractfile(item).read())
    manifest = {"schema_version": 1, "source_commit": revision, "platform": "macos-arm64",
                "minimum_macos": "14", "app_sha256": sha(app_bytes.getvalue()),
                "python": sources["python"], "video_tools": {}}
    for name in ("ffmpeg", "ffprobe"):
        meta = sources[name + "-darwin-arm64.gz"]
        compressed = (runtime / (name + "-darwin-arm64.gz")).read_bytes()
        if sha(compressed) != meta["sha256"]:
            raise ValueError("Video tool checksum failed")
        binary = gzip.decompress(compressed)
        if binary[:8] != bytes.fromhex("cffaedfe0c000001"):
            raise ValueError("Video tool is not ARM64 Mach-O")
        manifest["video_tools"][name] = {**meta, "binary_sha256": sha(binary)}
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "ClipFoundry-Mac-Apple-Silicon.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        prefix = "ClipFoundry-Mac/"
        launcher = git("show", "HEAD:macos/Open-ClipFoundry.command").decode().replace(
            "__PYTHON_SHA256__", sources["python"]["sha256"])
        entry = zipfile.ZipInfo(prefix + "Open-ClipFoundry.command")
        entry.create_system = 3
        entry.external_attr = 0o100755 << 16
        bundle.writestr(entry, launcher)
        for source_name, target in [("macos/setup.py", "setup.py"), ("macos/README.md", "READ-ME.md")]:
            bundle.writestr(prefix + target, git("show", "HEAD:" + source_name))
        bundle.writestr(prefix + "manifest.json", json.dumps(manifest, indent=2) + "\n")
        bundle.writestr(prefix + "app.zip", app_bytes.getvalue())
        bundle.writestr(prefix + "python-macos.tar.gz", python, compress_type=zipfile.ZIP_STORED)
    result = {"file": destination.name, "source_commit": revision, "sha256": sha(destination.read_bytes()),
              "bytes": destination.stat().st_size, "native_mac_verified": False}
    (output / "mac-release.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(Path(__file__).resolve().parents[1], args.runtime_dir, args.output), indent=2))

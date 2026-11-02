"""Exercise the distributed setup on an ephemeral native macOS runner, with no owner data."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

from build_package import build


def main():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("This test requires a native Apple-silicon runner")
    root = Path(__file__).resolve().parents[1]
    work = Path(os.environ["RUNNER_TEMP"]) / "clipfoundry-native-check"
    runtime = work / "runtime"
    runtime.mkdir(parents=True)
    sources = json.loads((root / "macos/runtime-sources.json").read_text())
    (runtime / "runtime-sources.json").write_text(json.dumps(sources))
    for key, meta in sources.items():
        name = "python-macos.tar.gz" if key == "python" else key
        with urllib.request.urlopen(meta["url"], timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != meta["sha256"]:
            raise ValueError(f"Checksum mismatch for {name}")
        (runtime / name).write_bytes(data)
    # Builder checks the Python archive before extraction and tests the actual distributed app tree.
    release = build(root, runtime, work / "output")
    with tarfile.open(runtime / "python-macos.tar.gz") as tar:
        tar.extractall(work / "python-runtime", filter="data")
    with zipfile.ZipFile(work / "output" / release["file"]) as bundle:
        bundle.extractall(work / "bundle")
    python = work / "python-runtime/python/bin/python3.12"
    subprocess.run([str(python), "-I", str(root / "macos/ci_install.py"),
                    str(work / "bundle/ClipFoundry-Mac"), str(work / "profile")], check=True, timeout=900)
    app = work / "profile/releases" / release["source_commit"]
    env = dict(os.environ, CLIPFOUNDRY_DATA=str(work / "smoke-data"), CLIPFOUNDRY_WORKERS="off",
               CLIPFOUNDRY_FFMPEG=str(app / "tools/ffmpeg/bin"))
    subprocess.run([str(app / ".venv/bin/python"), "macos/native_smoke.py"],
                   cwd=app, env=env, check=True, timeout=120)
    print("Native Apple-silicon package setup and app smoke tests passed.")


if __name__ == "__main__":
    main()

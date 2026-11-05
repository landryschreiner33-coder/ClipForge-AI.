"""Install the ClipForge Windows setup ZIP on a Windows machine the way a person would, and check the result.

Runs on a disposable GitHub Windows runner (see .github/workflows/windows-setup-check.yml), never on a person's PC:
it installs into C:\\CF14 and starts the app on 127.0.0.1.

1. The previous release: extract its ZIP, run its setup.py, wait for the app, save one synthetic setting, close it.
2. This release, over it: it must keep the same data folder and the setting, put the app in a new folder and serve
   exactly this commit's page and icon.
3. Close it and open it again: same folder, no second copy, the setting still there.

Closing means ending the setup window's whole process tree, as closing the console window does. Nothing here signs
in, uploads or contacts a social account. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

SETTING = ("caption_position", "top")  # a synthetic choice that both releases store unchanged


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract(package: Path, destination: Path) -> Path:
    # Same result as Explorer's Extract All: the four files side by side.
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None, f"{package.name} is damaged"
        names = sorted(archive.namelist())
        assert names == ["Open-ClipFoundry.cmd", "README.txt", "app.zip", "setup.py"], names
        archive.extractall(destination)
    return destination


def http(url: str, method: str = "GET", body: dict | None = None) -> bytes:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-ClipFoundry": "1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status == 200, (url, response.status)
        return response.read()


class Run:
    """One opening of Open-ClipFoundry.cmd: setup.py with the checked Python, its output kept in a log."""

    def __init__(self, folder: Path, log: Path):
        self.log_path = log
        self.log = log.open("wb")
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(folder / "setup.py")], cwd=folder, stdin=subprocess.DEVNULL,
            stdout=self.log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

    def text(self) -> str:
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def wait_ready(self, minutes: int) -> str:
        deadline = time.monotonic() + minutes * 60
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError("setup stopped early:\n" + self.text()[-4000:])
            found = re.search(r"The app will open at (http://127\.0\.0\.1:\d+)", self.text())
            if found:
                try:
                    json.loads(http(found.group(1) + "/api/health"))
                    return found.group(1)
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    pass
            time.sleep(5)
        raise AssertionError("the app did not answer in time:\n" + self.text()[-4000:])

    def close(self, url: str) -> None:
        subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.process.wait(timeout=120)
        self.log.close()
        port = int(url.rsplit(":", 1)[1])
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)):
                    return
            time.sleep(2)
        raise AssertionError(f"the app still answers on port {port} after its window closed")


def folder_from(log: str) -> Path:
    found = re.findall(r"^(?:ClipForge|ClipFoundry) folder: (.+?)\s*$", log, re.M)
    assert len(found) == 1, found
    return Path(found[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--previous-url", required=True)
    parser.add_argument("--previous-sha256", required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    assert os.name == "nt", "This check installs the Windows setup; run it on Windows."
    work = args.work
    work.mkdir(parents=True)
    evidence: dict = {"python": sys.version, "platform": sys.platform, "windows": os.environ.get("ImageOS", "")}

    package = args.zip.read_bytes()
    evidence["zip"] = {"file": args.zip.name, "bytes": len(package), "sha256": sha256(package)}
    previous = work / "previous.zip"
    with urllib.request.urlopen(args.previous_url, timeout=300) as response:
        previous.write_bytes(response.read())
    assert sha256(previous.read_bytes()) == args.previous_sha256, "the previous release download changed"
    evidence["previous_zip"] = {"url": args.previous_url, "sha256": args.previous_sha256}

    # 1. the previous release with one synthetic setting
    old = Run(extract(previous, work / "previous"), work / "previous-setup.log")
    url = old.wait_ready(30)
    old_health = json.loads(http(url + "/api/health"))
    http(url + "/api/settings", "PUT", {SETTING[0]: SETTING[1]})
    assert json.loads(http(url + "/api/settings"))[SETTING[0]] == SETTING[1]
    old_root = folder_from(old.text())
    old_marker = (old_root / ".clipfoundry-oneclick.json").read_bytes()
    old.close(url)
    evidence["previous"] = {"folder": str(old_root), "data_dir": old_health["data_dir"],
                            "version": old_health["version"]}

    # 2. this release over it
    current = extract(args.zip, work / "current")
    with zipfile.ZipFile(current / "app.zip") as app:
        prefix = f"ClipForge-AI.-{args.commit}/"
        index = app.read(prefix + "frontend/dist/index.html")
        icon = app.read(prefix + "frontend/dist/app-icon.png")
        files = {info.filename[len(prefix):]: sha256(app.read(info)) for info in app.infolist() if not info.is_dir()}
    new = Run(current, work / "setup.log")
    url = new.wait_ready(30)
    health = json.loads(http(url + "/api/health"))
    root = folder_from(new.text())
    marker = json.loads((root / ".clipfoundry-oneclick.json").read_text(encoding="utf-8"))
    assert marker["commit"] == args.commit, marker
    assert Path(marker["data_root"]) == old_root, (marker, old_root)
    assert root != old_root and (old_root / ".clipfoundry-oneclick.json").read_bytes() == old_marker
    assert health["data_dir"] == old_health["data_dir"], (health["data_dir"], old_health["data_dir"])
    assert json.loads(http(url + "/api/settings"))[SETTING[0]] == SETTING[1], "the saved setting was lost"
    page = http(url + "/")
    assert page == index and b"<title>ClipForge</title>" in page, "the app serves another page"
    assert http(url + "/app-icon.png") == icon, "the app serves another icon"
    installed = {path: sha256((root / path).read_bytes()) for path in files}
    assert installed == files, [path for path in files if installed[path] != files[path]][:10]
    new.close(url)
    evidence["install"] = {"folder": str(root), "data_dir": health["data_dir"], "version": health["version"],
                           "source_commit": marker["commit"], "files_checked": len(files),
                           "page_sha256": sha256(page), "icon_sha256": sha256(icon),
                           "setting_kept": True, "previous_folder_kept": True}

    # 3. close and open again
    again = Run(current, work / "reopen.log")
    url = again.wait_ready(15)
    assert folder_from(again.text()) == root, "reopening made another copy"
    assert "Preparing the included" not in again.text(), "reopening extracted the app again"
    assert json.loads(http(url + "/api/health"))["data_dir"] == health["data_dir"]
    assert json.loads(http(url + "/api/settings"))[SETTING[0]] == SETTING[1]
    again.close(url)
    evidence["reopen"] = {"same_folder": True, "setting_kept": True}

    print(json.dumps(evidence, indent=2))
    (work / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

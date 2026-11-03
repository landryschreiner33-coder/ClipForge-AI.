"""Deliver the tested personal preview; never imply Developer ID/notarization."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

REPO = "landryschreiner33-coder/ClipForge-AI."
RUN = 41656652146
COMMIT = "bc3ce2cdc23ccc7a495d2cfc2ed15aba3fe161e3"
ARTIFACT = 13240393392
ARCHIVE_SHA256 = "49bc9aeffcd8cfa183ee6e3ccdddfb843dfd86e9084570514be35cc37ff39709"
TAG = "macos-personal-2026-11-03-bc3ce2c"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", f"repos/{REPO}/{path}"]))


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    if os.environ.get("GH_REPO") != REPO:
        raise RuntimeError("Unexpected repository")
    tested = api(f"actions/runs/{RUN}")
    assert tested["conclusion"] == "success" and tested["head_sha"] == COMMIT
    assert tested["path"] == ".github/workflows/macos-desktop.yml"
    assert tested["head_repository"]["full_name"] == REPO
    assert tested["event"] in ("push", "workflow_dispatch")
    artifact = api(f"actions/artifacts/{ARTIFACT}")
    assert not artifact["expired"] and artifact["workflow_run"]["id"] == RUN
    assert artifact["digest"] == "sha256:" + ARCHIVE_SHA256

    with tempfile.TemporaryDirectory(prefix="clipfoundry-personal-") as temporary:
        work = Path(temporary)
        archive = work / "tested.zip"
        with archive.open("wb") as target:
            run("gh", "api", f"repos/{REPO}/actions/artifacts/{ARTIFACT}/zip", stdout=target)
        assert sha(archive) == ARCHIVE_SHA256, "Tested artifact bytes changed"
        names = ("ClipFoundry-Development.dmg", "ClipFoundry-Corresponding-Source.tar.gz")
        with zipfile.ZipFile(archive) as bundle:
            for name in names:
                assert bundle.namelist().count(name) == 1
                bundle.extract(name, work)
        dmg = work / "ClipFoundry-Mac-Apple-Silicon.dmg"
        shutil.move(work / names[0], dmg)
        sources = work / names[1]
        run("hdiutil", "verify", str(dmg))
        mount = work / "mounted"
        mount.mkdir()
        run("hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(dmg))
        try:
            app = mount / "ClipFoundry.app"
            build = json.loads((app / "Contents/Resources/build.json").read_text())
            assert build["source_commit"] == COMMIT and build["platform"] == "macos-arm64"
            assert (app / "Contents/Resources/ClipFoundry.icns").is_file()
            run("codesign", "--verify", "--deep", "--strict", str(app))
        finally:
            run("hdiutil", "detach", str(mount))
        url = f"https://github.com/{REPO}/releases/download/{TAG}/"
        manifest = {
            "file": dmg.name, "url": url + dmg.name, "sha256": sha(dmg), "bytes": dmg.stat().st_size,
            "source_commit": COMMIT, "minimum_macos": "15", "architecture": "arm64",
            "release_kind": "personal-preview", "developer_id_signed": False, "notarized": False,
            "signing": "ad-hoc development signature only; macOS per-app approval may be required",
            "tested_run": f"https://github.com/{REPO}/actions/runs/{RUN}",
            "artifact_sha256": ARCHIVE_SHA256,
            "sources_file": sources.name, "sources_url": url + sources.name, "sources_sha256": sha(sources),
        }
        metadata = work / "mac-personal-preview.json"
        metadata.write_text(json.dumps(manifest, indent=2) + "\n")
        notes = work / "notes.md"
        notes.write_text(
            "Native local ClipFoundry app for Apple silicon, macOS 15 or newer.\n\n"
            "Download the DMG, drag ClipFoundry into Applications, and open it. Python and video tools are bundled. "
            "Quit any older ClipFoundry launcher first. Existing local Brain, clips and settings are preserved.\n\n"
            "**Unsigned personal preview: not Developer ID signed or Apple-notarized.** macOS may require "
            "System Settings → Privacy & Security → Open Anyway after the first launch attempt. "
            "An Apple Developer membership is not required to run it yourself.\n\n"
            "This is the unchanged DMG from the successful native app and 1,575-test run. "
            "Physical M5 Max hardware and real social uploads were not tested.\n\n"
            "Keep the app running and the Mac awake for scheduled work. Closing the window keeps it running; "
            "Quit stops it. The speech model downloads when first needed.\n\n"
            f"DMG SHA-256: `{manifest['sha256']}`\n\n"
            "Exact corresponding source and dependency notices accompany this download.\n"
        )
        existing = subprocess.run(["gh", "release", "view", TAG, "--json", "isDraft"],
                                  capture_output=True, text=True)
        if existing.returncode:
            run("gh", "release", "create", TAG, "--target", COMMIT, "--draft", "--prerelease",
                "--title", "ClipFoundry for Mac — personal preview", "--notes-file", str(notes),
                str(dmg), str(sources), str(metadata))
        # A retry may finish an interrupted draft, but never replaces published bytes.
        release = api(f"releases/tags/{TAG}")
        assets = {asset["name"]: asset for asset in release["assets"]}
        for path in (dmg, sources, metadata):
            assert path.name in assets, "Incomplete draft: finish its missing assets before publication"
            assert assets[path.name]["digest"] == "sha256:" + sha(path), "Release asset mismatch"
        if release["draft"]:
            run("gh", "release", "edit", TAG, "--draft=false", "--latest=false")
        print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

"""Deliver a tested personal Mac preview; never imply Developer ID/notarization.

Publishes exactly the DMG that a successful "Native Mac desktop app" run (macos-desktop.yml) built, smoke-tested
and regression-tested. The run is given by the person who starts the workflow (input `tested_run`); its commit,
artifact and digest are read from GitHub and checked, never typed in. A retry finishes an interrupted draft but never
replaces bytes that were already published.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

REPO = "landryschreiner33-coder/ClipForge-AI."
ARTIFACT_NAME = "ClipFoundry-Development-NOT-NOTARIZED"  # the build workflow's artifact (internal name kept)
DMG_NAME = "ClipForge-Mac-Apple-Silicon.dmg"


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
    run_id = os.environ.get("TESTED_RUN", "")
    tag = os.environ.get("TAG", "")
    if not re.fullmatch(r"[0-9]{6,20}", run_id):
        raise RuntimeError("tested_run must be the numeric ID of a Native Mac desktop app run")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,60}", tag):
        raise RuntimeError("tag must be lower-case letters, digits, dots and dashes")

    tested = api(f"actions/runs/{run_id}")
    assert tested["path"] == ".github/workflows/macos-desktop.yml", "Not a Native Mac desktop app run"
    assert tested["status"] == "completed" and tested["conclusion"] == "success", "That run did not pass"
    assert tested["head_repository"]["full_name"] == REPO
    assert tested["event"] in ("push", "workflow_dispatch")
    commit = tested["head_sha"]
    jobs = api(f"actions/runs/{run_id}/jobs?per_page=100")["jobs"]
    assert jobs and all(job["conclusion"] == "success" for job in jobs), "Every build and regression job must pass"
    artifacts = [a for a in api(f"actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
                 if a["name"] == ARTIFACT_NAME]
    assert len(artifacts) == 1 and not artifacts[0]["expired"], "The tested DMG artifact is missing or expired"
    artifact = artifacts[0]
    archive_sha256 = (artifact.get("digest") or "").removeprefix("sha256:")
    assert re.fullmatch(r"[0-9a-f]{64}", archive_sha256), "The artifact has no recorded digest"

    with tempfile.TemporaryDirectory(prefix="clipforge-personal-") as temporary:
        work = Path(temporary)
        archive = work / "tested.zip"
        with archive.open("wb") as target:
            run("gh", "api", f"repos/{REPO}/actions/artifacts/{artifact['id']}/zip", stdout=target)
        assert sha(archive) == archive_sha256, "Tested artifact bytes changed"
        names = ("ClipFoundry-Development.dmg", "ClipFoundry-Corresponding-Source.tar.gz")
        with zipfile.ZipFile(archive) as bundle:
            for name in names:
                assert bundle.namelist().count(name) == 1
                bundle.extract(name, work)
        dmg = work / DMG_NAME
        shutil.move(work / names[0], dmg)
        sources = work / "ClipForge-Corresponding-Source.tar.gz"
        shutil.move(work / names[1], sources)
        run("hdiutil", "verify", str(dmg))
        mount = work / "mounted"
        mount.mkdir()
        run("hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(dmg))
        try:
            # The bundle keeps its ClipFoundry identity so the Keychain items and data folder stay the same.
            app = mount / "ClipFoundry.app"
            build = json.loads((app / "Contents/Resources/build.json").read_text())
            assert build["source_commit"] == commit and build["platform"] == "macos-arm64"
            assert (app / "Contents/Resources/ClipFoundry.icns").is_file()
            run("codesign", "--verify", "--deep", "--strict", str(app))
        finally:
            run("hdiutil", "detach", str(mount))
        url = f"https://github.com/{REPO}/releases/download/{tag}/"
        manifest = {
            "file": dmg.name, "url": url + dmg.name, "sha256": sha(dmg), "bytes": dmg.stat().st_size,
            "source_commit": commit, "minimum_macos": "15", "architecture": "arm64",
            "release_kind": "personal-preview", "developer_id_signed": False, "notarized": False,
            "signing": "ad-hoc development signature only; macOS per-app approval may be required",
            "tested_run": f"https://github.com/{REPO}/actions/runs/{run_id}",
            "artifact_sha256": archive_sha256,
            "sources_file": sources.name, "sources_url": url + sources.name, "sources_sha256": sha(sources),
        }
        metadata = work / "mac-personal-preview.json"
        metadata.write_text(json.dumps(manifest, indent=2) + "\n")
        notes = work / "notes.md"
        notes.write_text(
            "ClipForge (formerly ClipFoundry) for Apple silicon, macOS 15 or newer: Make clips (Highlights or Full "
            "stories) from a video file or a link to one video, Make a YouTube video in the full-video editor "
            "(voiceover, music and effects tracks, versions, your script), FilmCraft and EffectCraft inside the app, "
            "ClipForge AI with a built-in model, its memory and chat, example videos, Find media, the Brain map, "
            "several accounts and the robot office, in one dark studio. ClipForge works only on the videos you add; "
            "it no longer searches the internet for videos.\n\n"
            "New in 2026.11.07: ClipForge AI is far smarter. It understands what is said (a small meaning model, "
            "downloaded once and checked against fixed fingerprints), reads the whole video and names moments the "
            "word lists miss, ranks the finalists with green, yellow and red verdicts, looks at frames of the best "
            "clips and picks their thumbnails, listens to the voice for emphasis, laughter and flat delivery, and "
            "learns your taste from the clips you keep and drop; every change to a score is capped and explained next "
            "to the clip. Long videos: Full stories makes one clip per story without asking, footage is used where it "
            "is on your Mac (files of many gigabytes), a script in any common format is matched to the footage and cut "
            "in script order with the cleanest take of each line, and Edit it for me keeps the best take, drops "
            "warm-ups and opens with the strongest line. The whole app has a new look: layered dark surfaces, one "
            "accent colour, and Settings as a side list.\n\n"
            "Download the DMG, drag the app into Applications, and open it. Python and video tools are bundled. "
            "Quit any older ClipFoundry first. The app keeps its ClipFoundry name in Finder so your existing "
            "Brain, clips, accounts and settings stay where they are.\n\n"
            "**Unsigned personal preview: not Developer ID signed or Apple-notarized.** macOS may require "
            "System Settings → Privacy & Security → Open Anyway after the first launch attempt.\n\n"
            "This is the unchanged DMG from the successful native build, smoke test and regression run linked in "
            "mac-personal-preview.json. Physical Mac hardware and real social uploads were not tested.\n\n"
            f"Source commit: `{commit}`\n\nDMG SHA-256: `{manifest['sha256']}`\n\n"
            "Exact corresponding source and dependency notices accompany this download.\n"
        )
        # GitHub's tag endpoint does not resolve an unpublished draft. Find it
        # through the authenticated collection so interrupted runs reuse it.
        matches = [item for item in api("releases?per_page=100") if item["tag_name"] == tag]
        assert len(matches) <= 1, "Ambiguous preview release"
        if not matches:
            run("gh", "release", "create", tag, "--target", commit, "--draft", "--prerelease",
                "--title", "ClipForge for Mac — personal preview", "--notes-file", str(notes),
                str(dmg), str(sources), str(metadata))
            matches = [item for item in api("releases?per_page=100") if item["tag_name"] == tag]
        assert len(matches) == 1, "Expected one preview draft"
        release = api(f"releases/{matches[0]['id']}")
        assets = {asset["name"]: asset for asset in release["assets"]}
        for path in (dmg, sources, metadata):
            assert path.name in assets, "Incomplete draft: finish its missing assets before publication"
            assert assets[path.name]["digest"] == "sha256:" + sha(path), "Release asset mismatch"
        if release["draft"]:
            run("gh", "api", "--method", "PATCH", f"repos/{REPO}/releases/{release['id']}",
                "-F", "draft=false", "-F", "prerelease=true", "-f", "make_latest=false",
                stdout=subprocess.DEVNULL)
        print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

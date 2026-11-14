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
            "ClipForge (formerly ClipFoundry) for Apple silicon, macOS 15 or newer: Make clips (Highlights, Full "
            "story or Story parts) from a video file or a link to one video, Make a YouTube video planned with "
            "ClipForge AI and edited in the full-video editor (voiceover, music and effects tracks, versions, your "
            "script), Make an animated short, FilmCraft and EffectCraft inside the app, ClipForge AI with a built-in "
            "model, its memory, its chat and helper agents, example videos, Find media, the Brain map, several "
            "accounts and the robot office, in one dark studio. ClipForge works only on the videos you add; it no "
            "longer searches the internet for videos.\n\n"
            "New in 2026.11.13.2: pictures and video clips can be made on a cloud computer you rent by the hour "
            "(for example a RunPod pod with a big graphics card) instead of on this Mac. Choose it in Settings → "
            "Pictures, video, voice → A cloud computer, paste the pod's address and press Save and check; "
            "ClipForge gives you one command to copy into the pod that puts the models on it. Your videos, "
            "projects, the voice and ClipForge AI stay on this Mac, and making things on this Mac is still the "
            "default. Remember to press Stop on the pod when you finish: it costs money while it is on.\n\n"
            "New in 2026.11.13: ClipForge AI is a real assistant. Both chats hold a real conversation that knows your "
            "projects and memories; it can find and open projects, remember what you tell it and propose a change to "
            "a video's cut, and when it wants to rename, forget or delete something it shows a card and waits for "
            "your OK. Helper agents (eight ready-made ones, or your own, in Brain → Agents) work alongside it. Make a "
            "YouTube video starts with your files and your idea: ClipForge AI writes the plan with you (Ask me "
            "questions, or Just do it) and edits the video from it. Make an animated short turns a pasted script, or "
            "one ClipForge AI writes, into a voice-over short with pictures, camera moves and word-by-word captions. "
            "ClipForge can also make pictures, short clips and voice-overs on this Mac with ComfyUI and a built-in "
            "voice (large optional downloads, set up in Settings). Story clips show the whole picture, centred and "
            "still, as Full story or Story parts, never longer than five minutes. Projects can be deleted from the "
            "Projects page, after a window that lists what goes and what stays.\n\n"
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

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
            "story or Story parts) from a video file or a link to one video, clip live streams while they are live "
            "(several at once), Make a YouTube video planned with "
            "ClipForge AI and edited in the full-video editor (voiceover, music and effects tracks, versions, your "
            "script), Make an animated short, Make a text story, Check a video, FilmCraft and EffectCraft inside the "
            "app, ClipForge AI with a built-in model, its memory, its chat and helper agents, example videos, Find "
            "media, the Brain's knowledge map, several accounts and a crew of 25 robots on a cutaway ship, in one "
            "space studio. ClipForge works only on the videos and streams you add; it no longer searches the internet "
            "for videos to clip (Find media and a text story's Find free footage search free footage sites only "
            "when you ask).\n\n"
            "New in 2026.11.27, the biggest update so far. Editing: phone HDR video no longer comes out flat and "
            "grey; Automatic colour gently corrects white balance and brightness and leaves cartoons and graphics as "
            "drawn; there are nine looks with a strength, Clean up grainy footage and Steady shaky footage (Settings "
            "→ Defaults, the clip editor's Colour tab and a full video's Colour panel). Short clips punch in on jump "
            "cuts and push in on key words with a soft whoosh, and end in a seamless loop; these are on by default "
            "and can be changed per clip. "
            "Full videos get speed changes from 0.25× to 4× with speed ramps, freeze frames, slow zooms and pans, "
            "split edits, room tone under titles and photos, music that ends on the last frame, and several cameras "
            "of one recording lined up by their sound and switched to whoever is talking, with a camera or pictures "
            "in a corner. After every render in ClipForge's own editor the sound is measured and corrected toward "
            "-14 LUFS, and the final check before posting also reports loudness, picture levels and colour tags."
            "\n\n"
            "Clips: ClipForge listens to every sound (laughter, cheering, explosions) and watches the picture to find "
            "moments, leaves out ad reads, talk to chat and goodbyes, starts clips on the first real word (Put it "
            "back in the clip editor), says why each clip ranks where it does and suggests trims. Stream clips have "
            "layouts (Gameplay + Facecam, Picture-in-picture, Gameplay only) with a face cam box you can draw, also "
            "on a live stream in Missions while it records. Each clip gets three kinds of title and tidier hashtags, and a viral "
            "prediction (score, hook, hold curve, heatmap and fixes you can add to your edit); Make → Check a video "
            "predicts any video up to 10 minutes.\n\n"
            "Make → Make a text story makes narrated stories or text-message chats like the ones on TikTok, up to "
            "ten minutes, from your script or one ClipForge AI writes, over your own or found background footage. "
            "Animated shorts keep a library of characters and places with their details and reference pictures, "
            "ease their camera moves, get two new sideways pushes, and show an example picture for each look.\n\n"
            "Once a model is set up (the free built-in one in Settings → ClipForge AI, or an AI helper), ClipForge AI "
            "does what you ask without a second OK (Settings → ClipForge AI → Ask me first (OK button) brings the OK "
            "back for every change, though rendering a clip again still starts at once; "
            "deleting always asks, a TikTok post always waits for your OK on its page, and cancelling, retrying or "
            "approving several posts at once waits for one OK): it can move, cancel, retry and approve posts, trim, "
            "render and change clips, pause missions, change settings and say why something is stuck. Talk to AI "
            "keeps saved chats, 👍 and 👎 teach it, it reads "
            "your results and what the last render did, and Brain → Learned picks up your habits from your edits.\n\n"
            "Publishing: Cancel upload stops a post's upload before it is posted (if YouTube or TikTok already has the "
            "whole video, it says it is too late); Missions is in the menu, with each mission's next upload and its "
            "own Pause uploads; a post's Change the time box offers the nearest free time when the time you pick is "
            "too close to another post; "
            "Publishing → Results → Compare compares your posts fairly. Settings → Processing can send Make clips to "
            "your own ClipForge worker on another computer (Full Cloud). Look: the gold robot icon, more background "
            "and accent colours and one of your own, a black hole drawn with its light bending as the ship orbits "
            "it and a little ship in front, pop-ups that ease in and out, and a Taser on a charger in the office's "
            "Control room with twelve zap reactions (Settings → Appearance hides it).\n\n"
            "New in 2026.11.20: the space studio moves as if the ship were flying. Behind every page the sky "
            "streams past to the left: the small stars slide slowly, brighter stars twinkle and drift faster, "
            "specks of dust rush past and now and then a shooting star crosses. The black hole's disk turns, its "
            "inner streaks faster than its outer ones. A new page fades in and rises a little, a new tab fades in "
            "only what is under the tab bar you chose it in, and Settings keeps its title and list of sections "
            "while a section loads. Motion → Reduced in Settings → Appearance holds the sky and the black hole "
            "still and makes page and tab changes instant; Robot activity → Low power and a hidden window hold "
            "the sky and the black hole still too. If the black hole draws too slowly, it holds still for a "
            "while and then tries again.\n\n"
            "New in 2026.11.19.2: a new look, the space studio, in Courier Prime type under one starry sky. Studio is "
            "a cutaway ship with its crew of 25 robots and CORE: every room is named, a team goes to its consoles only "
            "while it has real work, and the badge above each robot shows its job state (pick a robot to see its "
            "task). Beside the ship, Working on shows what is being made now on a screen, what's going on, the queue, "
            "how many things need you, Talk to ClipForge AI and, at the bottom, the next post to publish; the Make tab "
            "holds Make clips, Make a YouTube video, Make an animated short and Clip a live stream. The Studio's "
            "layout is new: a panel order saved in Customize studio no longer applies to it, and what is being made "
            "and the next post always show. Talk to AI also sits in the menu right under Studio and is a Brain tab. "
            "Make clips takes three steps (Choose a video, Pick what to make, Make clips), with everything else under "
            "More options; when the clips are ready, Review clips opens them, and Export is now called Save to "
            "computer. In the Brain, Memory shows your knowledge map as a galaxy whose links flicker like lightning "
            "(picking a dot runs a light from CORE to it), Styles has a caption preview you can play, and Example "
            "videos, Example notes, Skills and Performance history are under More. Projects, Publishing, Accounts and "
            "Settings → Appearance (with a live preview at desktop, tablet and phone sizes) have the new look too. If "
            "your accent colour was the old default violet, it becomes Glacier blue once; you can pick violet again in "
            "Settings → Appearance. Reduce motion under the ship (the same switch as Motion in Settings → Appearance) "
            "holds the ship and the lightning still, and Robot activity → Low power in Settings → Appearance keeps the "
            "robots still; real work always shows.\n\n"
            "New in 2026.11.19: live clips put quality over quantity. When you add a stream in Missions → Live "
            "streams, How picky chooses Only the best moments (the default, about three clips an hour while the "
            "stream is live), Balanced or Every good moment. Stop clipping stops recording a stream at any time and "
            "makes no more clips from it, not even from the full recording, while the clips already made keep their "
            "checks and still upload as planned. Clips of a video or stream with a face cam over the picture now "
            "use a split view: the face cam on top and the whole picture below it (Settings → Defaults → Split view "
            "and Under the face cam; for a live stream, its own Split view choice when you add it; for one clip, "
            "the clip editor's Layout). You choose which channels each post goes to: tick YouTube channels and "
            "TikTok accounts on Prepare post, send several clips at once to your YouTube channels with Post "
            "selected… on a video's page, tick the YouTube channels for each video or stream in Missions, and with "
            "two or more ticked let the clips take turns between them. ClipForge AI knows more in chat (16 "
            "playbooks, a guide to the app and the advice of your switched-on skills), clip picking follows your "
            "Brain (your memories, imported lessons, viral examples and skills), clips run longer by default (25, "
            "45 and 90 seconds for the shortest, ideal and longest clip, keeping a moment's build-up and ending), "
            "lessons from your posted results become memories, and titles, post text and hashtags follow what you "
            "told it.\n\n"
            "New in 2026.11.16.2: the cloud computer has its own place in Settings. Open Settings → Cloud "
            "computer and press Use a cloud computer to see the box for your pod's address and the step-by-step "
            "RunPod guide. Settings → Pictures, video, voice points to it too, and messages about the cloud computer "
            "name it. Nothing else changed.\n\n"
            "New in 2026.11.16: clip live streams while they are live. Paste one or more stream links (Twitch or "
            "Kick channels, YouTube live videos or a channel's live page, or a public .m3u8 address) in Missions → "
            "Live streams. ClipForge records each one on this Mac, up to the Largest source limits in Settings → "
            "Advanced (4 hours or 8 GB unless you changed them), makes vertical, captioned clips from strong moments "
            "as the stream goes on and, with Make & upload clips, uploads the clips that pass the final checks to your "
            "YouTube account during the stream, at your posting pace. Several streams can record at once. Stop "
            "recording keeps every upload made so far, and when a stream ends the whole recording is checked once "
            "more, adding moments the live pass missed while the stream has fewer clips than Clips per source (5 "
            "unless you changed it). Also fixed: a job that was running when you pressed Cancel or Stop all jobs, "
            "and then paused, retried or crashed, could be left waiting with nothing to pick it up.\n\n"
            "New in 2026.11.13.2: pictures and video clips can be made on a cloud computer you rent by the hour "
            "(for example a RunPod pod with a big graphics card) instead of on this Mac. Choose it in Settings → "
            "Cloud computer (Use a cloud computer), paste the pod's address and press Save and check; "
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
            "Quit any older copy first, then choose Replace when Finder asks. The app shows as ClipForge in Finder, "
            "the Dock and Launchpad; its file is still ClipFoundry.app, so it replaces the installed copy in place "
            "and your Brain, clips, accounts and settings stay where they are.\n\n"
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

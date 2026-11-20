"""Check that a real FilmCraft opens ClipForge's timelines exactly (run by .github/workflows/filmcraft-check.yml).

Makes real media with FFmpeg (two talking clips at different sizes, rates and tones, a picture, a voiceover, a music
bed that has to loop and two sound effects that overlap), builds a ClipForge video with a title card, dissolves, a
straight cut, a muted clip, a picture over the video, captions and chapters, then writes it twice: as "Open in
FilmCraft" does (absolute paths to the originals) and as the portable .zip (relative paths). For each, FilmCraft's own
command-line tool imports the timeline and captions into a project, and the script compares what FilmCraft holds with
what ClipForge meant: sequence size and rate, every clip's start and length on the timeline, transitions, track names,
clip volumes, the looping music, chapter markers, caption cues and offline files. Finally FilmCraft renders the
project and FFprobe checks the length, size and sound of the file.

    python scripts/filmcraft_check.py --cli /path/to/filmcraft-cli --out /tmp/filmcraft-check [--expect-app]

`--expect-app`: FilmCraft.app was installed in ~/Applications (Mac); ClipForge's detection must find it there.
Writes report.json in --out and exits 1 when anything differs.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FPS = 30


def sh(cmd: list[str], timeout: float = 600, check: bool = True) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd), flush=True)
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if done.stdout.strip():
        print(done.stdout[-4000:], flush=True)
    if done.stderr.strip():
        print(done.stderr[-4000:], file=sys.stderr, flush=True)
    if check and done.returncode != 0:
        raise SystemExit(f"command failed ({done.returncode}): {' '.join(cmd)}")
    return done


def ffprobe(path: Path) -> dict:
    out = sh(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(out.stdout)


def make_media(folder: Path) -> dict[str, Path]:
    # one folder per file, as ClipForge keeps uploads (a video's transcript cache sits next to it)
    f = {k: folder / k / v for k, v in {"one": "talk one.mp4", "two": "talk two.mp4", "pic": "lake.png",
                                        "voice": "voice.wav", "music": "bed.wav", "fx1": "whoosh.wav",
                                        "fx2": "ding.wav"}.items()}
    for p in f.values():
        p.parent.mkdir(parents=True, exist_ok=True)
    ff = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "error"]
    sh(ff + ["-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=12", "-f", "lavfi", "-i",
             "sine=frequency=440:sample_rate=48000:duration=12", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(f["one"])])
    sh(ff + ["-f", "lavfi", "-i", "smptehdbars=s=1280x720:r=25:d=24", "-f", "lavfi", "-i",
             "sine=frequency=660:sample_rate=44100:duration=24", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(f["two"])])
    sh(ff + ["-f", "lavfi", "-i", "testsrc=s=1600x1200:d=1", "-frames:v", "1", str(f["pic"])])
    for key, freq, dur in (("voice", 300, 4), ("music", 220, 3.3), ("fx1", 880, 1.5), ("fx2", 1200, 1.0)):
        sh(ff + ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={dur}", "-ac", "2",
                 str(f[key])])
    return f


def seed(files: dict[str, Path]) -> dict:
    """The ClipForge project: assets with their real probes, cached transcripts for captions, version 1 saved."""
    from clipfoundry import db
    from clipfoundry.studio import video_flow

    db.init()

    def asset(key: str, kind: str) -> dict:
        p = files[key]
        info = ffprobe(p)
        dur = float(info["format"].get("duration") or 0)
        v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
        probe = {"duration": dur if kind != "image" else 0, "width": v.get("width"), "height": v.get("height"),
                 "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]), "has_video": bool(v)}
        return db.insert("assets", {"id": f"as-{key}", "workspace_id": "local", "kind": kind, "filename": p.name,
                                    "sha256": f"sha-{key}", "size": p.stat().st_size, "path": str(p), "probe": probe})

    a, b, pic = asset("one", "video"), asset("two", "video"), asset("pic", "image")
    vo, music, fx1, fx2 = (asset(k, "audio") for k in ("voice", "music", "fx1", "fx2"))
    for v, words in ((a, "Hello and welcome to the lake today."), (b, "Now we swim out to the island.")):
        ws = [{"start": 1.0 + 0.4 * i, "end": 1.3 + 0.4 * i, "w": w} for i, w in enumerate(words.split())]
        (Path(v["path"]).parent / "transcript.json").write_text(json.dumps({"segments": [{"words": ws}]}))
    from clipfoundry.jobs import worker

    # the project's own rough cut is not wanted (version 1 is the plan below): its job is never handed to this
    # process's worker, where it would race the plan below and could save a rough cut as version 2
    held, worker.submit_studio = worker.submit_studio, lambda job_id: None
    try:
        project = video_flow.create("local", "local", name="Lake day", asset_ids=[a["id"], pic["id"], b["id"]],
                                    brief={}, style_id="settings", remember={"enabled": False})
    finally:
        worker.submit_studio = held
    for job in db.select("studio_jobs", "target_id = ? AND kind = 'video_build'", (project["id"],)):
        db.update("studio_jobs", job["id"], status="canceled", message="Not needed by the check")
    plan = video_flow.rough_cut(project, video_flow._assets(project), {})
    plan["output"] = {"aspect": "9:16", "fps": FPS}
    plan["layout"] = "fit"
    plan["clips"] = [
        {"id": "c1", "asset_id": a["id"], "kind": "video", "in_ms": 500, "out_ms": 6200, "label": "Welcome",
         "gain_db": -3.0, "include": True},
        {"id": "c2", "asset_id": pic["id"], "kind": "image", "in_ms": 0, "out_ms": 3000, "label": "Lake",
         "include": True},
        {"id": "c3", "asset_id": b["id"], "kind": "video", "in_ms": 2333, "out_ms": 9871, "label": "Swim",
         "include": True},
        {"id": "c4", "asset_id": b["id"], "kind": "video", "in_ms": 16000, "out_ms": 19500, "label": "Island",
         "include": True, "join": "cut", "mute": True},
    ]
    plan["transition"] = {"type": "dissolve", "ms": 500}
    plan["title"] = {"enabled": True, "text": "Lake day", "ms": 2000}
    plan["captions"] = {**(plan.get("captions") or {}), "enabled": True, "style": "clean"}
    plan["overlays"] = [{"id": "o1", "asset_id": pic["id"], "clip_id": "c1", "offset_ms": 1500, "length_ms": 2000,
                         "motion": "still", "label": "Lake shot"}]
    base = {"in_ms": 0, "length_ms": None, "gain_db": 0.0, "mute": False, "fade_in_ms": 0, "fade_out_ms": 0,
            "duck": False, "loop": False, "anchor": None}
    plan["audio"] = [
        {**base, "id": "a1", "asset_id": vo["id"], "role": "voiceover", "label": "Intro voice", "start_ms": 1000,
         "out_ms": 3000},
        {**base, "id": "a2", "asset_id": music["id"], "role": "music", "label": "Bed", "start_ms": 0, "out_ms": None,
         "loop": True, "gain_db": -18.0},
        {**base, "id": "a3", "asset_id": fx1["id"], "role": "effect", "label": "Whoosh", "start_ms": 5000,
         "out_ms": 1500},
        {**base, "id": "a4", "asset_id": fx2["id"], "role": "effect", "label": "Ding", "start_ms": 5500,
         "out_ms": 1000, "gain_db": 2.0},
    ]
    plan["chapters"] = [{"title": "Welcome", "clip_id": "c1", "offset_ms": 0},
                        {"title": "The lake", "clip_id": "c3", "offset_ms": 0}]
    video_flow.save_revision(project["id"], plan, "FilmCraft check", None,
                             {"action": "build", "prev": None, "redo": None})
    db.update("studio_projects", project["id"], status="ready", message="")
    return db.fetch("studio_projects", project["id"])


def layout(track: dict) -> list[dict]:
    """(start frame, frames, kind) of every clip in an OTIO track, transitions taking no room."""
    out, pos = [], 0
    for c in track["children"]:
        if c["OTIO_SCHEMA"].startswith("Transition"):
            continue
        d = round(c["source_range"]["duration"]["value"])
        if c["OTIO_SCHEMA"].startswith("Clip"):
            out.append({"start": pos, "frames": d, "name": c["name"],
                        "gain_db": (c["metadata"].get("filmcraft") or {}).get("gain_db", 0.0)})
        pos += d
    return out


def cli_json(cli: str, args: list[str], timeout: float = 600) -> dict:
    done = sh([cli, "--compact", *args], timeout=timeout)
    for line in reversed(done.stdout.strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    raise SystemExit(f"no JSON from filmcraft-cli {' '.join(args)}")


def check_package(cli: str, otio_path: Path, srt_path: Path, work: Path, label: str, problems: list[str]) -> dict:
    doc = json.loads(otio_path.read_text())
    meta = doc["metadata"]["clipforge"]
    frames, width, height = meta["frames"], meta["width"], meta["height"]
    project = work / f"{label}.fcproj"
    imported = cli_json(cli, ["import", str(otio_path), str(srt_path), "--save-as", str(project)])
    report: dict = {"import": imported}

    def want(cond: bool, what: str) -> None:
        if not cond:
            problems.append(f"[{label}] {what}")

    want(project.is_file(), "no FilmCraft project was written")
    want(not imported.get("errors"), f"import errors: {imported.get('errors')}")
    offline = [m for d in imported.get("documents") or [] if isinstance(d, dict) for m in d.get("offlineMedia") or []]
    want(not offline, f"offline media after import: {offline}")
    try:
        seq = cli_json(cli, ["inspect", "sequence", "--project", str(project)])
    except SystemExit:
        tree = cli_json(cli, ["inspect", "project", "--project", str(project)])
        seq_id = tree.get("activeSequence")
        report["note"] = "active sequence not saved; inspected by id"
        seq = cli_json(cli, ["exec", "sequence.inspect", json.dumps({"item": seq_id}), "--project", str(project)])
    report["sequence"] = {k: seq.get(k) for k in ("name", "settings", "durationFrames")}
    s = seq.get("settings") or {}
    want((s.get("width"), s.get("height")) == (width, height), f"sequence is {s.get('width')}x{s.get('height')}, "
                                                                  f"expected {width}x{height}")
    want(s.get("frame_rate") == {"num": FPS, "den": 1}, f"sequence rate {s.get('frame_rate')}, expected {FPS}")
    want(abs(int(seq.get("durationFrames") or 0) - frames) <= 1,
         f"sequence is {seq.get('durationFrames')} frames, expected {frames}")
    tracks = {t["name"]: t for t in doc["tracks"]["children"]}
    fc_tracks = [*(seq.get("video") or []), *(seq.get("audio") or [])]
    by_name = {t["name"]: t for t in fc_tracks}
    for name, t in tracks.items():
        mine = layout(t)
        theirs = by_name.get(name)
        want(theirs is not None, f"track {name!r} missing in FilmCraft (has {sorted(by_name)})")
        if not theirs:
            continue
        got = sorted((int(i["startFrame"]), int(i["durationFrames"])) for i in theirs["items"])
        exp = sorted((m["start"], m["frames"]) for m in mine)
        want(got == exp, f"track {name!r}: clips at {got}, expected {exp}")
        gains = sorted(round(float(i.get("gainDb") or 0), 2) for i in theirs["items"])
        want(gains == sorted(round(float(m["gain_db"]), 2) for m in mine), f"track {name!r}: clip volumes {gains}")
        n_trans = sum(1 for c in t["children"] if c["OTIO_SCHEMA"].startswith("Transition"))
        want(len(theirs.get("transitions") or []) == n_trans,
             f"track {name!r}: {len(theirs.get('transitions') or [])} transitions, expected {n_trans}")
        if name == "Video 1":
            report["v1_transitions"] = [x.get("effect") for x in theirs.get("transitions") or []]
    want(len(seq.get("markers") or []) == len(doc["tracks"]["markers"]),
         f"{len(seq.get('markers') or [])} markers, expected {len(doc['tracks']['markers'])}")
    caps = cli_json(cli, ["exec", "captions.list", "--project", str(project)])
    cues = sum(len(t.get("captions") or []) for t in caps.get("tracks") or [])
    expected_cues = srt_path.read_text().count(" --> ")
    want(cues == expected_cues, f"{cues} caption cues, expected {expected_cues}")
    report["captions"] = cues
    # FilmCraft renders the project: length, size and sound of the file
    out = work / f"{label}.mp4"
    sh([cli, "export", str(out), "--project", str(project), "--gpu-rendering", "off"], timeout=1200)
    info = ffprobe(out)
    v = next((x for x in info["streams"] if x["codec_type"] == "video"), {})
    dur = float(info["format"].get("duration") or 0)
    report["render"] = {"duration": dur, "width": v.get("width"), "height": v.get("height"),
                        "audio": any(x["codec_type"] == "audio" for x in info["streams"])}
    want(abs(dur - frames / FPS) <= 2 / FPS + 0.05, f"render is {dur:.3f} s, expected {frames / FPS:.3f} s")
    want((v.get("width"), v.get("height")) == (width, height), f"render is {v.get('width')}x{v.get('height')}")
    want(report["render"]["audio"], "render has no sound")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect-app", action="store_true")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ["CLIPFOUNDRY_DATA"] = str(out / "data")
    os.environ.setdefault("CLIPFOUNDRY_WORKERS", "off")
    sys.path.insert(0, str(ROOT))
    from clipfoundry.studio import filmcraft, interchange

    problems: list[str] = []
    report: dict = {"cli_version": sh([args.cli, "--version"]).stdout.strip()}
    files = make_media(out / "media")
    project = seed(files)
    # ClipForge's own detection finds this FilmCraft
    os.environ[filmcraft.CLI_ENV] = args.cli
    found = filmcraft.find()
    report["found"] = found
    if found["cli"] != args.cli:
        problems.append(f"ClipForge did not find the command-line tool: {found}")
    if args.expect_app:
        os.environ.pop(filmcraft.CLI_ENV)
        app = filmcraft.find()
        report["found_app"] = app
        if not app["app"].endswith("FilmCraft.app") or not app["version"]:
            problems.append(f"ClipForge did not find FilmCraft.app in Applications: {app}")
        else:
            report["app_version"] = sh([app["exe"], "--version"], check=False).stdout.strip()
    # 1. "Open in FilmCraft": absolute paths to the originals
    pkg = interchange.for_video(project, 1, out / "local", portable=False)
    report["counts"] = pkg.built.counts
    report["local"] = check_package(args.cli, pkg.timeline, pkg.captions, out, "local", problems)
    # 2. the portable .zip, unpacked somewhere else
    port = interchange.for_video(project, 1, out / "portable-src", portable=True)
    z = interchange.zip_package(port, out / "timeline.zip")
    there = Path(tempfile.mkdtemp(prefix="unpacked ", dir=out))
    with zipfile.ZipFile(z) as zz:
        zz.extractall(there)
    shutil.rmtree(out / "portable-src")
    report["portable"] = check_package(args.cli, there / port.timeline.name, there / port.captions.name, out,
                                       "portable", problems)
    report["problems"] = problems
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({"problems": problems, "counts": report["counts"]}, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

"""A throwaway ClipFoundry for the beginner-flow browser test (e2e/sandbox/beginner-flow.spec.ts).

It never touches your real ClipFoundry: its own temporary data folder, its own port (8799), local stand-ins for
Google's and TikTok's sign-in pages and APIs ("test connections", nothing reaches the real platforms and nothing is
posted), and a synthetic transcript instead of Whisper (no model download, no GPU needed). Autopilot's workers run
inside this process, so they talk to the stand-ins.

    python e2e/sandbox/run_sandbox.py [--port 8799]

Playwright starts and stops it by itself (npm run test:sandbox in the e2e folder).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

SPEECH = ("Here is the thing nobody tells you about starting a podcast. You do not need expensive gear. You need one "
          "good question. Ask your guest what they got wrong last year. That answer is always the best part of the "
          "episode. People love honest stories about mistakes. Keep the recording short and cut the slow parts. Your "
          "first ten episodes are practice, so publish them anyway. ")
INTERVIEW = ("I almost quit the company in the second year. We had three months of money left and no customers. "
             "Then one buyer called back and asked a simple question. Could we deliver in a week instead of a month? "
             "We said yes before we knew how. That promise changed the whole business. The lesson is simple: "
             "listen to customers first. That is why speed mattered more than features. ")
TRENDING = [  # what the stand-in for YouTube reports as trending (other creators' videos: skipped unless covered)
    ("pod1", "The podcast moment everyone is talking about", "UCpodcast000000001", 950_000, "PT1H10M"),
    ("int1", "Podcast interview: the founder who almost quit", "UCinterview0000001", 610_000, "PT48M"),
    ("pod2", "Podcast debate gets heated over remote work", "UCdebate0000000001", 420_000, "PT55M"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("CLIPFOUNDRY_SANDBOX_PORT", 8799)))
    parser.add_argument("--scenario", choices=("beginner", "zero-touch"), default="beginner")
    args = parser.parse_args()
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        sys.exit("The sandbox needs ffmpeg and ffprobe on the PATH (winget install Gyan.FFmpeg).")

    data = Path(tempfile.mkdtemp(prefix="clipfoundry-sandbox-"))
    os.environ["CLIPFOUNDRY_DATA"] = str(data)
    os.environ["CLIPFOUNDRY_VIDEOS"] = str(data / "Videos" / "ClipFoundry")  # your videos folder, inside the sandbox
    os.environ["CLIPFOUNDRY_WORKERS"] = "in_app"  # the workers must run here, next to the stand-ins
    for var in ("NO_PROXY", "no_proxy"):
        os.environ[var] = "127.0.0.1,localhost"

    from fake_platforms import FakeGoogle, FakeTikTok
    from synthetic_media import make_video, words_from

    from clipfoundry import db
    from clipfoundry.pipeline import transcribe
    from clipfoundry.publish import tiktok, youtube

    google, tt = FakeGoogle(), FakeTikTok()
    for name, path in (("AUTH_URL", "/o/oauth2/v2/auth"), ("TOKEN_URL", "/token"), ("REVOKE_URL", "/revoke"),
                       ("API_URL", "/youtube/v3"), ("UPLOAD_URL", "/upload/youtube/v3/videos")):
        setattr(youtube, name, google.url + path)
    youtube.ANALYTICS_URL = f"{google.url}/v2/reports"
    tiktok.AUTH_URL, tiktok.API_URL = f"{tt.url}/v2/auth/authorize/", f"{tt.url}/v2"
    for vid, title, channel, views, duration in TRENDING:
        google.add_video(vid, title, channel, views=views, age_hours=5, duration=duration)
    google.popular = [v[0] for v in TRENDING]

    db.init()
    # The test connections: the stand-ins' own app codes. A real user pastes their own once (Settings → General).
    db.save_settings({"youtube_client_id": "cid.apps.googleusercontent.com", "youtube_client_secret": "csecret",
                      "tiktok_client_key": "tkkey", "tiktok_client_secret": "tksecret",
                      "trend_topics": "podcast, interview", "encoder": "x264", "x264_preset": "ultrafast",
                      "library_discovery": False})  # offline: the free-license library is not searched

    # The original file of a video (what "Add the file" asks for), a synthetic talk
    original = data / "sandbox" / "original.mp4"
    original.parent.mkdir(parents=True)
    make_video(original, seconds=75.0)
    # A creator's shared folder (a synced Dropbox, say) with the raw file of their trending video, named by its
    # YouTube ID. The test records an agreement with this creator that names the folder. Older than a minute, so
    # it does not look like a file still being synced.
    shared = data / "sandbox" / "Podcast creator shared"
    shared.mkdir()
    raw = shared / "episode 112 raw [pod1].mp4"
    shutil.copyfile(original, raw)
    old = time.time() - 600
    os.utime(raw, (old, old))

    said: dict[str, str] = {}  # project folder → what its video says (the stand-in's videos say different things)

    def synthetic_transcript(wav, duration, settings, ctx, lo=0.0, hi=1.0, vad=True, allow_cpu_fallback=True):
        text = (said.get(str(Path(wav).parent), SPEECH) * 8).split()
        words = [w for w in words_from(" ".join(text), step=0.36, length=0.28) if w["end"] < duration - 0.5]
        return {"segments": [{"start": words[0]["start"], "end": words[-1]["end"], "words": words,
                              "text": " ".join(w["w"] for w in words)}], "language": "en",
                "runtime": {"device": "cpu", "requested_device": "cpu", "compute_type": "int8",
                            "model": "sandbox transcript"}}

    transcribe.transcribe = synthetic_transcript

    if args.scenario == "beginner":
        # Public discovery (autopilot_public_videos, on by default) clips the trending videos on this PC. The
        # stand-in for YouTube serves no media, so the importer gets the synthetic talk for the stand-in's own
        # videos and refuses every other address: the sandbox never downloads anything from the internet.
        from urllib.parse import parse_qs, urlparse

        from clipfoundry.autopilot import hunter
        from clipfoundry.media_import import MediaUnavailable

        def public_video(project_id, url, ctx, max_bytes=None, max_seconds=None):
            vid = (parse_qs(urlparse(url).query).get("v") or [""])[0]
            if urlparse(url).hostname != "www.youtube.com" or vid not in google.catalog:
                raise MediaUnavailable("The sandbox downloads nothing from the internet")
            if vid == "pod2":  # like a video behind a login: Autopilot says so and goes on with the others
                raise MediaUnavailable("This video could not be downloaded. The site may require a login, "
                                       "restrict downloads, or use an unsupported player.")
            project = db.get_project(project_id)
            target = Path(project["source_path"])
            shutil.copyfile(original, target)
            said[str(target.parent)] = INTERVIEW if vid == "int1" else SPEECH
            db.update_project(project_id, source_path=str(target), source_filename=target.name)

        hunter.download_url = public_video

    import uvicorn

    from clipfoundry.api import app

    scenario = None
    if args.scenario == "zero-touch":
        from zero_touch_support import CompleteLoopFixture

        google.catalog.clear()
        scenario = CompleteLoopFixture(data, google, setattr)

        # These controls exist only in this executable and are served only on its own loopback port. They
        # expose fixture observations or change external inputs/time; no production API has reset/test routes.
        @app.get("/sandbox/state")
        def sandbox_state():
            return scenario.snapshot()

        @app.post("/sandbox/next-video")
        def sandbox_next_video():
            scenario.repeat()
            return {"ok": True}

        @app.post("/sandbox/age-results")
        def sandbox_age_results():
            scenario.age_results()
            return {"ok": True}

        @app.post("/sandbox/due-public-posts")
        def sandbox_due_public_posts():
            return scenario.due_public_posts()

        @app.post("/sandbox/upcoming-stream")
        def sandbox_upcoming_stream():
            return {"url": scenario.upcoming_stream()}

        @app.post("/sandbox/start-stream")
        def sandbox_start_stream():
            scenario.start_stream()
            return {"ok": True}

        @app.post("/sandbox/restart-workers")
        def sandbox_restart_workers():
            from clipfoundry.autopilot import host

            old = host.supervisor.host
            if old:
                old.stop(timeout=30)
            replacement = host.WorkerHost(poll=0.1)
            if not replacement.start(wait_for_lock=10):
                raise RuntimeError("The previous worker host has not finished its safe step")
            host.supervisor.host = replacement
            return {"ok": True, "owner": replacement.owner, "enabled": db.get_settings()["autopilot_enabled"]}

        # api.py's SPA fallback was registered before this executable's fixture routes. Put only these sandbox
        # routes before that fallback so requests receive observations rather than the frontend's index.html.
        fixture_routes = [route for route in app.router.routes if getattr(route, "path", "").startswith("/sandbox/")]
        for route in fixture_routes:
            app.router.routes.remove(route)
        app.router.routes[:0] = fixture_routes

    print(f"\n  ClipFoundry sandbox at http://127.0.0.1:{args.port}  (data: {data})\n", flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        google.stop()
        tt.stop()
        if scenario:
            scenario.stop()
        shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    main()

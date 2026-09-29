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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

SPEECH = ("Here is the thing nobody tells you about starting a podcast. You do not need expensive gear. You need one "
          "good question. Ask your guest what they got wrong last year. That answer is always the best part of the "
          "episode. People love honest stories about mistakes. Keep the recording short and cut the slow parts. Your "
          "first ten episodes are practice, so publish them anyway. ")
TRENDING = [  # what the stand-in for YouTube reports as trending (other creators' videos: they need your OK)
    ("pod1", "The podcast moment everyone is talking about", "UCpodcast000000001", 950_000, "PT1H10M"),
    ("int1", "Podcast interview: the founder who almost quit", "UCinterview0000001", 610_000, "PT48M"),
    ("pod2", "Podcast debate gets heated over remote work", "UCdebate0000000001", 420_000, "PT55M"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("CLIPFOUNDRY_SANDBOX_PORT", 8799)))
    args = parser.parse_args()
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        sys.exit("The sandbox needs ffmpeg and ffprobe on the PATH (winget install Gyan.FFmpeg).")

    data = Path(tempfile.mkdtemp(prefix="clipfoundry-sandbox-"))
    os.environ["CLIPFOUNDRY_DATA"] = str(data)
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
    tiktok.AUTH_URL, tiktok.API_URL = f"{tt.url}/v2/auth/authorize/", f"{tt.url}/v2"
    for vid, title, channel, views, duration in TRENDING:
        google.add_video(vid, title, channel, views=views, age_hours=5, duration=duration)
    google.popular = [v[0] for v in TRENDING]

    db.init()
    # The test connections: the stand-ins' own app codes. A real user pastes their own once (Settings → General).
    db.save_settings({"youtube_client_id": "cid.apps.googleusercontent.com", "youtube_client_secret": "csecret",
                      "tiktok_client_key": "tkkey", "tiktok_client_secret": "tksecret",
                      "trend_topics": "podcast, interview", "encoder": "x264", "x264_preset": "ultrafast"})

    # The original file of a video (what "Add the video file" asks for), a synthetic talk
    original = data / "sandbox" / "original.mp4"
    original.parent.mkdir(parents=True)
    make_video(original, seconds=75.0)

    def synthetic_transcript(wav, duration, settings, ctx, lo=0.0, hi=1.0, vad=True, allow_cpu_fallback=True):
        text = (SPEECH * 8).split()
        words = [w for w in words_from(" ".join(text), step=0.36, length=0.28) if w["end"] < duration - 0.5]
        return {"segments": [{"start": words[0]["start"], "end": words[-1]["end"], "words": words,
                              "text": " ".join(w["w"] for w in words)}], "language": "en",
                "runtime": {"device": "cpu", "requested_device": "cpu", "compute_type": "int8",
                            "model": "sandbox transcript"}}

    transcribe.transcribe = synthetic_transcript

    import uvicorn

    from clipfoundry.api import app

    print(f"\n  ClipFoundry sandbox at http://127.0.0.1:{args.port}  (data: {data})\n", flush=True)
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        google.stop()
        tt.stop()
        shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    main()

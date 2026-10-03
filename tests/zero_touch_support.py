"""External fixtures for the complete-loop sandbox: media, platforms and a Whisper stand-in.

Every output clip, artifact, quality report, approval, upload and learning observation comes from production
handlers. The fixture controls only inputs and elapsed wall-clock deadlines; it never writes a passing outcome.
"""
from __future__ import annotations

import hashlib
import ipaddress
import datetime as dt
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from fake_platforms import _Server


FIRST = "loopfirst01"
BROKEN = "loopbroken1"
SECOND = "loopagain01"
STREAM = "loopstream1"
MANUAL = "manualvideo1"

BUSINESS = [
    "Here's the biggest mistake most people make when they start a business.",
    "They spend months building a product nobody asked for.",
    "I did exactly that. I spent a whole year and all my savings on it.",
    "And when we launched, we got three customers. Three.",
    "So what changed? I started talking to people before building anything.",
    "That's why my second company made money in the first month.",
    "The lesson is simple. Talk to customers first, then build.",
]
STORY = [
    "Let me tell you a story about the worst day of my career.",
    "I was on stage in front of two thousand people and my laptop died.",
    "No slides. No notes. Nothing.",
    "So I just told the truth about how scared I was.",
    "And it turned out to be the best talk I ever gave.",
    "Honestly, the audience loved it because it was real.",
    "In the end, being honest beat being perfect.",
]
DIET = [
    "Why do most diets fail after two weeks?",
    "Because willpower is a terrible strategy.",
    "Your environment beats your motivation every single time.",
    "If there is no junk food in your house, you simply cannot eat it.",
    "That is the whole secret. Change the environment, not your mindset.",
]


def install_fixture_dns(patch) -> None:
    """The fake YouTube catalog's public names resolve without external DNS; all other checks stay in force."""
    from clipfoundry import netguard

    real_resolve = netguard.resolve

    def fixture_dns(host: str):
        if host.lower() in ("youtube.com", "www.youtube.com", "youtu.be"):
            return [ipaddress.ip_address("142.250.72.206")]
        return real_resolve(host)

    patch(netguard, "resolve", fixture_dns)


class FixtureMedia(_Server):
    def __init__(self, files: dict[str, Path]):
        self.files = files
        super().__init__()

    def handle(self, h, method: str, body: bytes) -> None:
        path = self.files.get(urlparse(h.path).path)
        if method != "GET" or not path or not path.exists():
            return h._send(404, {"detail": "Fixture video not available"})
        return h._send(200, path.read_bytes(), {"Content-Type": "video/mp4"})


def build_speech_video(folder: Path, lines: list[str], *, flip: bool = False, repeats: int = 12) -> tuple[Path, Path]:
    """Real espeak audio with its timed transcript, over a moving FFmpeg pattern.

    These reduced originals keep real media processing practical in a CPU sandbox. The fake catalog represents
    longer episodes, as in the beginner sandbox. Fit framing is selected because a generated pattern has no face.
    """
    import make_test_video

    folder.mkdir(parents=True, exist_ok=True)
    previous = make_test_video.SCRIPT
    try:
        make_test_video.SCRIPT = lines * repeats
        wav, srt, duration = make_test_video.synth(folder)
    finally:
        make_test_video.SCRIPT = previous
    video = folder / "original.mp4"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
           f"testsrc2=s=320x180:r=12:d={duration}", "-i", str(wav)]
    if flip:
        cmd += ["-vf", "hflip,vflip"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-g", "12", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(video)]
    subprocess.run(cmd, check=True, capture_output=True)
    return video, srt


class CompleteLoopFixture:
    """A fake creator's originals, public metadata and metrics. Requires an isolated data folder."""

    def __init__(self, data: Path, google, patch):
        from clipfoundry import db
        from clipfoundry.autopilot import access, host, live, providers, scheduler
        from clipfoundry.pipeline import transcribe
        from clipfoundry.publish import youtube

        self.data, self.google = data, google
        # Upload every planned YouTube post at once (YouTube publishes it at its time), so the loop's uploads happen
        # during the run whatever the time of day. The setting's maximum lead (12 hours) was not enough: run at
        # night, the day's second slot was 13.8 hours away and its upload never started (2026-10-03).
        patch(scheduler, "lead_seconds", lambda item, settings: 48 * 3600.0 if item["platform"] == "youtube" else 0.0)
        self.transcriptions: list[str] = []
        self.first, self.first_srt = build_speech_video(data / "sandbox" / "business", BUSINESS)
        self.second, self.second_srt = build_speech_video(data / "sandbox" / "story", STORY, flip=True)
        self.broken = data / "sandbox" / "broken.mp4"
        self.broken.write_bytes(b"This fixture is an unreadable video, not synthetic success.")
        self.media = FixtureMedia({"/manual.mp4": self.second, "/broken.mp4": self.broken})
        self.files = {FIRST: self.first, SECOND: self.second, MANUAL: self.second, BROKEN: self.broken}
        self.srts = {FIRST: self.first_srt, SECOND: self.second_srt, MANUAL: self.second_srt,
                     BROKEN: self.first_srt}
        self.real_resolve = access.resolve
        self.stream_video: Path | None = None
        install_fixture_dns(patch)

        def originals(source: dict, settings: dict) -> dict:
            original = self.files.get(source.get("external_id"))
            if original and source.get("platform") == "youtube":
                # This is the fake creator's original file, the network boundary of the fixture. Rights still
                # come from Google's confirmation of the connected channel, never from this file mapping.
                return access._ok("local", "Sandbox creator's original", local_path=str(original))
            return self.real_resolve(source, settings)

        def whisper(wav, duration, settings, ctx, lo=0.0, hi=1.0, vad=True, allow_cpu_fallback=True):
            wav = Path(wav)
            project = db.get_project(wav.parent.name)
            if not project and wav.parent.name == "live":
                project = db.get_project(wav.parent.parent.name)
            source = db.fetch("sources", (project or {}).get("source_id") or "") or {}
            srt = self.srts.get(source.get("external_id"), self.second_srt)
            result = transcribe.import_transcript(srt, duration)
            if wav.parent.name == "live":
                state_path = wav.parent / "state.json"
                offset = float(json.loads(state_path.read_text()).get("offset") or 0)
                words = [{**w, "start": max(0.0, w["start"] - offset), "end": min(duration, w["end"] - offset)}
                         for w in transcribe.flatten_words(result) if offset <= w["start"] < offset + duration]
                result["segments"] = [{"start": words[0]["start"], "end": words[-1]["end"], "words": words,
                                       "text": " ".join(w["w"] for w in words)}] if words else []
            result["runtime"] = {"device": "cpu", "requested_device": "cpu", "compute_type": "int8",
                                 "model": "sandbox fixture transcript"}
            self.transcriptions.append(source.get("id") or str(wav))
            return result

        patch(access, "resolve", originals)
        patch(transcribe, "transcribe", whisper)
        original_input = live.input_args

        def stream_transport(source, settings, **kwargs):
            if source.get("external_id") == STREAM and self.stream_video:
                # Only the fake platform's transport is replaced: the real capture subprocess owns its lock and
                # FFmpeg writes real segments for the live and post-live production handlers to process.
                return ["-i", str(self.stream_video)]
            return original_input(source, settings, **kwargs)

        patch(live, "input_args", stream_transport)
        patch(live, "SEGMENT_SECONDS", 10)
        patch(live, "EDGE_MARGIN", 2.0)
        patch(youtube, "ANALYTICS_URL", f"{google.url}/v2/reports")
        patch(providers, "COMMONS_API", "http://127.0.0.1:9/w/api.php")
        patch(providers, "TAVILY_URL", "http://127.0.0.1:9/search")
        patch(host, "POLL_SECONDS", 0.1)
        # Discovery normally sleeps for hours and learning for six hours. Use the same production periodic
        # dispatcher with shorter fixture clock periods, so successive runs get real, distinct idempotency
        # slots. Resetting next:* alone inside the same multi-hour slot would correctly return the old job.
        patch(host, "PERIODIC", [(kind, (lambda settings: 30.0) if kind in ("trend_scan", "learn") else period,
                                  active) for kind, period, active in host.PERIODIC])
        google.default_statistics = {"viewCount": "1234", "likeCount": "87", "commentCount": "9"}
        google.analytics = None  # unreported retention remains missing; the learner must not fabricate it
        db.save_settings({"trend_topics": "podcast", "encoder": "x264", "x264_preset": "ultrafast",
                          "layout": "fit", "whisper_device": "cpu", "library_discovery": False,
                          "rights_allow_remote_download": True,
                          "autopilot_clips_per_source": 1, "autopilot_sources_per_day": 1,
                          "autopilot_daily_target": 4, "autopilot_min_quality": 40,
                          "autopilot_active_start": 0, "autopilot_active_end": 24,
                          "autopilot_upload_lead_minutes": 720,
                          "autopilot_tiktok": False, "autopilot_youtube": True,
                          "min_duration": 12.0, "max_duration": 45.0, "target_duration": 25.0,
                          "youtube_derived_metrics_approved": True})
        self.add_catalog(FIRST, "Podcast business mistakes and talking to customers", self.first)
        self.add_catalog(BROKEN, "Podcast with an unreadable original recording", self.broken, views=990_000)
        # This manually pasted video has accessible media but no reuse permission. It must produce a local
        # checked clip and stay out of automatic publishing, even while ordinary discovery continues.
        google.add_video(MANUAL, "An honest stage story with a broken laptop", "UCother00000001", views=1000,
                         duration="PT6M")
        google.popular = [BROKEN, FIRST]

    def add_catalog(self, external_id: str, title: str, video: Path, views: int = 950_000) -> None:
        from clipfoundry.pipeline.ffmpeg_utils import probe

        duration = max(1800.0, float(probe(video)["duration"])) if external_id != BROKEN else 1800.0
        self.google.add_video(external_id, title, "UC123", views=views, age_hours=5,
                              duration=f"PT{int(duration)}S")

    def repeat(self) -> None:
        """The upstream platform exposes another video; ordinary periodic discovery must pick it up."""
        self.add_catalog(SECOND, "Podcast honest stage story with a broken laptop", self.second)
        self.google.popular = [SECOND]
        self.elapse_period("trend_scan")

    def upcoming_stream(self) -> str:
        if self.stream_video is None:
            self.stream_video, transcript = build_speech_video(self.data / "sandbox" / "live", DIET, repeats=2)
            self.files[STREAM], self.srts[STREAM] = self.stream_video, transcript
        item = self.google.add_video(STREAM, "A live conversation about diets", "UCother00000001", duration="PT1M")
        item["snippet"]["liveBroadcastContent"] = "upcoming"
        item["liveStreamingDetails"] = {"scheduledStartTime": (dt.datetime.now(dt.timezone.utc) +
                                       dt.timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        return f"https://www.youtube.com/watch?v={STREAM}"

    def start_stream(self) -> None:
        item = self.google.catalog[STREAM]
        item["snippet"]["liveBroadcastContent"] = "live"
        item["liveStreamingDetails"]["actualStartTime"] = dt.datetime.now(dt.timezone.utc).isoformat()

    @staticmethod
    def elapse_period(kind: str) -> None:
        from clipfoundry.autopilot import state

        state.put(f"next:{kind}", 0)

    def age_results(self, hours: float = 24.0) -> None:
        """Advance the fixture's result-observation age without changing upload bytes or outcomes.

        The learner compares readings at least 20 hours after upload. Advancing only the age lets tests exercise
        that policy quickly while real lease and cancellation deadlines remain accurate.
        """
        from clipfoundry import db

        db.execute("UPDATE publications SET created_at = created_at - ? WHERE status = 'done'", (hours * 3600,))
        db.execute("DELETE FROM performance")  # future observation is fetched again from the fake platform
        self.elapse_period("learn")

    def snapshot(self) -> dict:
        from clipfoundry import db
        from clipfoundry.autopilot import state
        clips = db.select("clips")
        uploads = [{"id": remote_id, "sha256": hashlib.sha256(video["bytes"]).hexdigest(),
                    "bytes": len(video["bytes"]), "status": video["status"]}
                   for remote_id, video in self.google.videos.items()]
        return {"sources": db.select("sources"), "clips": clips, "reports": db.select("quality_reports"),
                "posts": db.select("scheduled_publications"), "publications": db.list_publications(),
                "performance": db.select("performance"), "learning": state.get("learning:status"),
                "jobs": db.select("worker_jobs"), "uploads": uploads, "transcriptions": self.transcriptions,
                "manual_url": f"https://www.youtube.com/watch?v={MANUAL}",
                "broken_url": f"https://www.youtube.com/watch?v={BROKEN}"}

    def stop(self) -> None:
        self.media.stop()

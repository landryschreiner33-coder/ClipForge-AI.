"""Measured audio from newly submitted media keeps its source clock through the exact uploaded bytes."""
import time
from pathlib import Path

import numpy as np
import pytest

from synthetic_media import needs_ffmpeg, words_from
from test_autopilot_publish import connect, env  # noqa: F401
from test_upload_audio import _ffmpeg, _frequency, _rms, _samples


@pytest.mark.slow
@needs_ffmpeg
def test_gapped_first_track_stays_in_sync_and_passes_final_checks_before_fake_upload(env):
    from clipfoundry import db
    from clipfoundry.pipeline import artifact, blueprint, quality, render
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe
    from clipfoundry.publish import youtube

    google, tiktok, tmp = env
    connect(google, tiktok)
    source = tmp / "interrupted-multiple-tracks.mkv"
    # The first track starts late and has a real timestamp interruption. A second, continuous stereo track
    # sounds different and would win FFmpeg's automatic selection without the explicit first-track mapping.
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=5",
            "-f", "lavfi", "-i", "aevalsrc=0.75*sin(2*PI*440*t):s=48000:d=3.8",
            "-f", "lavfi", "-i", "aevalsrc=sin(2*PI*880*t)|sin(2*PI*880*t):s=48000:d=5",
            "-filter_complex", "[1:a]asetpts=PTS+0.4/TB+gte(T\\,1)*0.6/TB[first]", "-map", "0:v",
            "-map", "[first]", "-map", "2:a", "-disposition:a:0", "0", "-disposition:a:1", "0",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "pcm_s16le", source)
    meta = probe(source)
    assert meta["audio_start"] == pytest.approx(.4, abs=.01)
    project = {"id": "p-gap-audio", "name": "Synthetic interrupted audio", "source_path": str(source),
               "dir": str(tmp / "gap-project"), "info": meta, "options": {}, **meta}
    clip = {"id": "c-gap-audio", "project_id": project["id"], "start": .2, "end": 4.8,
            "hook": "", "edit": {}}
    words = [{"w": "Synthetic", "start": .5, "end": .7}, {"w": "interruption.", "start": 2.1, "end": 2.4},
             {"w": "Returning", "start": 3.2, "end": 3.5}, {"w": "tone.", "start": 4, "end": 4.3}]
    plan = blueprint.Blueprint(clip["id"], project["id"], "source", "synthetic-input",
                               [blueprint.Interval(.2, 2.6), blueprint.Interval(3, 4.8)], speed=1.25,
                               framing=blueprint.Framing(mode="center"),
                               audio=blueprint.Audio(normalize=False, gain_db=12))
    assert not blueprint.errors(blueprint.validate(plan, 5, words))
    result = render.render_clip(project, clip, words,
                                {**db.get_settings(), "encoder": "x264", "x264_preset": "ultrafast"},
                                JobContext(), blueprint=plan)
    output = Path(result["output_path"])
    samples = _samples(output)
    assert np.isfinite(samples).all() and np.max(abs(samples)) < .95
    assert _rms(samples[480:3840]) < .0005  # (.4 - .2) / 1.25 = .16 s of original initial silence.
    assert _rms(samples[14400:38400]) > .1
    assert _rms(samples[50880:62400]) < .0005  # Original 1.4-2.0 s gap maps to .96-1.44 s.
    assert _rms(samples[74400:86400]) > .1
    assert _frequency(samples[105600:144000, 0], 48000) == pytest.approx(440, abs=3)
    assert len(samples) / 48000 == pytest.approx(3.36, abs=.05)
    report = quality.evaluate(output, result["render_info"], clip)
    assert report["passed"], report["blockers"]
    checks = {item["name"]: item["status"] for item in report["checks"]}
    assert checks["audio_stream"] == checks["decode"] == checks["av_timing"] == "pass"
    assert report["artifact_sha256"] == artifact.sha256_file(output)

    uploaded = youtube.upload(str(output), {"snippet": {"title": "Synthetic interrupted audio regression"},
                                           "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}},
                              youtube.Token(db.get_settings()))
    received = tmp / "fake-youtube-interrupted.mp4"
    received.write_bytes(google.videos[uploaded["id"]]["bytes"])
    assert artifact.sha256_file(received) == report["artifact_sha256"]
    assert np.array_equal(_samples(received), samples)


@pytest.mark.slow
@needs_ffmpeg
@pytest.mark.parametrize("youtube_enabled", [True, False])
def test_submitted_file_uses_saved_brain_then_uploads_exact_checked_unclipped_audio_once(env, monkeypatch,
                                                                                       youtube_enabled):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, knowledge, queue, rights, scheduler, submissions
    from clipfoundry.pipeline import artifact, transcribe

    google, tiktok, tmp = env
    connect(google, tiktok)
    db.save_settings({"encoder": "x264", "x264_preset": "ultrafast", "tracking": "center", "auto_zoom": False,
                      "hook_overlay": False, "silence": "off", "caption_style": "bold",
                      "caption_position": "bottom", "autopilot_clips_per_source": 1,
                      "autopilot_youtube": youtube_enabled, "autopilot_tiktok": True, "autopilot_min_quality": 0,
                      "min_duration": 12, "max_duration": 28, "target_duration": 20})
    note = knowledge.create({"kind": "reference", "title": "Readable captions",
                             "content": "Captions should be in the middle."})
    example = knowledge.create({"kind": "example", "title": "Preferred caption example", "example_label": "good",
                                "features": {"captions": "minimal"}})
    original_knowledge = db.select("brain_knowledge", order="id")
    source_path = tmp / "Original business recording.mkv"
    # This surround track used to overload when it was downmixed after loudness processing. The source also
    # has real late/gapped timestamps; the separate test above checks the edit positions explicitly.
    tone = "(0.03+0.72*lt(mod(t\\,1)\\,0.05))*sin(2*PI*440*t)"
    generated = "aevalsrc=" + "|".join([tone] * 6) + ":s=48000:d=43.8:c=5.1"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=360x640:rate=12:duration=45", "-f", "lavfi", "-i", generated,
            "-filter_complex", "[1:a]asetpts=PTS+0.6/TB+gte(T\\,10)*0.6/TB[a]", "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "pcm_s16le", source_path)
    speech = ("Here is the thing nobody tells you about starting a business. You do not need a big budget. "
              "You need one customer who really has the problem. Ask them what they tried last year. "
              "That answer is always the most useful part of the call. People love honest stories about mistakes. "
              "Keep the first version small and cut the slow parts. Your first ten customers are practice, "
              "so help them anyway. ")

    def synthetic_transcript(wav, duration, settings, ctx, lo=0., hi=1., vad=True, allow_cpu_fallback=True):
        words = [w for w in words_from(speech * 4, start=.7, step=.36, length=.28) if w["end"] < duration - .5]
        return {"source": "synthetic-test-transcript", "language": "en", "segments": [
            {"start": words[0]["start"], "end": words[-1]["end"], "words": words,
             "text": " ".join(w["w"] for w in words)}]}

    monkeypatch.setattr(transcribe, "transcribe", synthetic_transcript)
    setup = submissions.setup()
    options = {"auto_upload": True, "account_id": setup["account_id"], "privacy": setup["privacy"],
               "made_for_kids": False, "audience_version": setup["audience"]["group_version"],
               "reuse_basis": "owned", "reuse_statement": "", "agreed": True}
    with source_path.open("rb") as media:
        submitted = submissions.add_file(media, source_path.name, options)
    source_id = submitted["item"]["id"]
    assert db.get_settings()["autopilot_review_before_publish"] is True
    assert not db.select("publish_consents")  # The grant covers this one new input, never other queued sources.
    host.WorkerHost(periodic=False)

    def drain(worker):
        count = 0
        while (row := queue.claim(worker, "submitted-audio")) is not None:
            outcome = host.HANDLERS[row["kind"]](host.Job(row, "submitted-audio")) or {}
            queue.complete(row, "submitted-audio", outcome)
            count += 1
            assert count < 20, "The submitted workflow must not spin or enqueue duplicate work."
        return count

    assert drain("clip_hunter") == 1
    assert drain("analyzer") == 1
    source = db.fetch("sources", source_id)
    clips = db.list_clips(source["project_id"])
    assert len(clips) == 1 and clips[0]["status"] == "ready", source["status_note"]
    clip = clips[0]
    render_info = clip["render_info"]
    brain_ids = {row["knowledge_id"] for row in render_info["brain_knowledge"]}
    assert brain_ids == {note["id"], example["id"]}
    assert render_info["artifact"]["settings"]["caption_style"] == "minimal"
    assert render_info["artifact"]["settings"]["caption_position"] == "middle"
    captions = Path(render_info["artifact"]["captions"]["ass"]).read_text(encoding="utf-8")
    assert "Style: Caption,Poppins Medium,62," in captions
    assert drain("packager") == 1 and drain("quality_gate") == 1
    clip = db.get_clip(clip["id"])
    report = gate.report_for(clip)
    assert report["status"] == "passed", report["blockers"]
    assert set(report["metadata"]) == {"youtube"}  # This input's grant never targets the connected TikTok account.
    assert report["metadata"]["youtube"]["status"] == "passed", report["metadata"]
    checks = {item["name"]: item["status"] for item in report["checks"]}
    assert checks["decode"] == checks["audio_stream"] == checks["av_timing"] == "pass"
    now = time.time()
    scheduler.plan_new(db.get_settings(), now)
    [planned] = db.select("scheduled_publications")
    assert planned["status"] == "approved" and planned["approval"]["by"] == "submission", planned["status_note"]
    due = planned["planned_at"] - 60 * float(db.get_settings()["autopilot_upload_lead_minutes"])
    scheduler.process_due(db.get_settings(), due + 1)
    assert drain("publisher") == 1
    posted = db.fetch("scheduled_publications", planned["id"])
    assert posted["status"] == "published" and len(google.videos) == len(google.sessions) == 1
    publication = db.get_publication(posted["publication_id"])
    received = tmp / "exact-submitted-upload.mp4"
    received.write_bytes(google.videos[publication["remote_id"]]["bytes"])
    assert artifact.sha256_file(received) == artifact.sha256_file(clip["output_path"]) == report["artifact_sha256"]
    assert google.videos[publication["remote_id"]]["status"]["privacyStatus"] == options["privacy"]
    samples = _samples(received)
    assert samples.size and np.isfinite(samples).all()
    assert np.max(abs(samples)) < .95 and not np.any(abs(samples) >= .999)
    # Choose a quiet, steady part away from the deliberately generated transient at each whole source second.
    candidate = [samples[start:start + 9600, 0] for start in range(48000, len(samples) - 9600, 4800)]
    steady = min((chunk for chunk in candidate if _rms(chunk) > .01), key=lambda chunk: np.max(abs(chunk)))
    assert _frequency(steady, 48000) == pytest.approx(440, abs=5)
    spectrum = abs(np.fft.rfft(steady * np.hanning(len(steady)))) ** 2
    frequencies = np.fft.rfftfreq(len(steady), 1 / 48000)
    assert spectrum[abs(frequencies - 440) < 12].sum() / spectrum.sum() > .98
    assert np.array_equal(samples, _samples(Path(clip["output_path"])))
    assert db.fetch("sources", source_id)["rights_status"] == rights.MANUAL
    assert db.get_settings()["autopilot_youtube"] is youtube_enabled
    assert db.get_settings()["autopilot_tiktok"] is True
    # Input reuse statements do not become Brain guidance.
    assert db.select("brain_knowledge", order="id") == original_knowledge
    db.init()
    scheduler.process_due(db.get_settings(), due + 86400)
    queue.enqueue("publish", {"scheduled_id": planned["id"]}, idem_key=f"publish:{planned['id']}")
    assert drain("publisher") == 0
    assert len(google.videos) == len(google.sessions) == 1

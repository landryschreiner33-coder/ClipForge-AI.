"""Clip Hunter and Deep Clip Analyzer: staged ranking, boundaries, diversity, fingerprints, weak sources."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from clipfoundry.pipeline import candidates, deep, diversity, fingerprint, semantic, transcribe
from clipfoundry.pipeline.audio import Loudness
from clipfoundry.pipeline.common import JobContext
from clipfoundry.pipeline.text_utils import build_sentences
from test_core import SCRIPT, _srt, flat_loudness
from test_virality import PODCAST

HERE = Path(__file__).parent
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
OPTS = {"min_duration": 15.0, "max_duration": 60.0, "target_duration": 30.0, "clip_count": 3, "min_score": 50.0,
        "min_quality": 0.0, "ai_provider": "heuristic", "ai_max_candidates": 0}


def _talk(lines: list[str]):
    words = transcribe.flatten_words({"segments": transcribe.parse_subtitles(_srt(lines))})
    return words, build_sentences(words)


COOKING = ["Boil the pasta water with plenty of salt.", "The pasta needs salted water and a big pot.",
           "Stir the pasta so it does not stick to the pot.", "Save a cup of pasta water for the sauce.",
           "The sauce gets glossy when you add pasta water.", "Toss the pasta in the sauce before serving."]
ENGINES = ["The car engine needs fresh oil every season.", "Old engine oil makes the car run hot.",
           "Check the engine oil level before a long car trip.", "A car with low oil can damage the engine.",
           "Change the oil filter when you change the engine oil.", "The car engine sounds smoother with new oil."]


def test_semantic_embeddings_see_one_topic_versus_several():
    words, sents = _talk(COOKING + ENGINES + COOKING[:3])
    emb = semantic.embed_sentences(sents)
    live = emb[np.linalg.norm(emb, axis=1) > 0]
    assert emb.shape[0] == len(sents) and np.allclose(np.linalg.norm(live, axis=1), 1)
    cooking = semantic.features(emb, 0, 5)
    mixed = semantic.features(emb, 3, 8)  # three cooking lines, then engines
    assert cooking["coherence"] > mixed["coherence"] + 0.05 and cooking["score"] > mixed["score"] + 0.1
    assert mixed["min_adjacent"] < cooking["min_adjacent"] - 0.1  # the topic changes inside
    assert mixed["context_dependency"] > 0.3  # starts in the middle of the cooking part
    after = semantic.features(emb, 12, 14)  # back to cooking right after the engine part
    assert after["context_dependency"] < semantic.features(emb, 7, 9)["context_dependency"]


def test_long_videos_use_the_fast_embedding_path():
    lines = [f"Topic {i % 7} is about {w} and {w}s today." for i, w in enumerate(["cats", "dogs", "cars", "trains",
                                                                               "money", "music", "food"] * 80)]
    t0 = time.time()
    emb = semantic.embed_texts(lines)
    assert emb.shape[0] == 560 and time.time() - t0 < 5


def test_boundaries_cut_in_the_pause_without_clipping_words():
    words, sents = _talk(SCRIPT)
    db_env = np.full(int(sents[-1]["end"] * 10 + 20), -20.0)
    i = next(k for k, x in enumerate(sents) if x["text"].startswith("So what changed"))
    j = next(k for k, x in enumerate(sents) if x["text"].startswith("That's why my second"))
    prev_end, first = sents[i - 1]["end"], sents[i]["start"]
    assert first - prev_end > 0.3 and sents[j + 1]["start"] - sents[j]["end"] > 0.3  # real pauses around it
    db_env[int((first - 0.2) * 10)] = -60.0  # the quietest moment of the pause
    loud = Loudness({"hop": 0.1, "db": db_env.tolist()})
    b = deep.optimize_bounds({"s0": i, "s1": j}, sents, loud, sents[-1]["end"] + 1)
    assert prev_end <= b["start"] <= first and b["lead_in"] <= 0.35 + 1e-6
    assert abs(b["start"] - (first - 0.15)) < 0.11  # lands on the dip
    assert sents[j]["end"] + 0.12 - 1e-6 <= b["end"] <= sents[j + 1]["start"] and b["tail"] <= 0.6 + 1e-6


def test_audio_reactions_are_marked_as_estimates():
    words = [{"start": t, "end": t + 0.3, "w": "word"} for t in np.arange(0, 4, 0.4)] + \
            [{"start": t, "end": t + 0.3, "w": "word"} for t in np.arange(7, 10, 0.4)]
    env = np.full(110, -25.0)
    env[45:65] = -5.0  # loud, and nobody speaks: laughter or applause
    a = deep.audio_features(0.0, 10.0, words, Loudness({"hop": 0.1, "db": env.tolist()}))
    assert a["reactions"] == 1 and a["reaction_seconds"] >= 1.5 and a["silence_ratio"] < 0.1
    assert any("laughter" in e for e in a["estimated"])


def _deep_inputs():
    words, sents = _talk(PODCAST + SCRIPT)
    loud = flat_loudness(words[-1]["end"])
    cands = candidates.find_candidates(words, sents, loud, OPTS, pool_size=60, max_overlap=0.5)
    return words, sents, loud, cands


def test_staged_ranking_tracks_every_candidate():
    words, sents, loud, cands = _deep_inputs()
    assert len(cands) >= 10  # a 3.5-minute talk; long videos give 30-100 (see the next test)
    chosen, results, notes = deep.evaluate_select(sents, words, loud, OPTS, JobContext(), "talk", cands)
    st = notes["stages"]
    assert st["pool"] == len(cands) >= st["fast"] >= st["semantic"] >= st["deep"] >= st["selected"] == len(chosen)
    tracked = {c["cid"]: c for c in notes["candidates"]}
    assert len(tracked) == len(cands)
    assert all(c["stage"] == "selected" for c in tracked.values() if c["cid"] in {r["cid"] for r in chosen})
    assert all(c["reasons"] for c in tracked.values() if c["stage"] != "selected")  # every rejection says why
    for r in chosen:
        assert r["clip_score"] >= 0 and r["explanation"][0].startswith("Viral Potential")
        assert r["bounds"]["lead_in"] <= 0.35 + 1e-6 and 0 <= r["diversity"]["score"] <= 100
        assert not [f for f in r["analysis"]["flags"] if f["severity"] == "block"]
        assert r["deep"]["audio"]["estimated"] and r["deep"]["extras"]["trend_relevance"] is None
    for a in chosen:
        for b in chosen:
            if a is not b:
                assert diversity.similarity(a, b, sents)["combined"] < diversity.SIMILAR


def test_long_videos_give_a_broad_pool():
    import random

    rng = random.Random(3)
    syl = ["zor", "mel", "tak", "vin", "rup", "dal", "kes", "pom", "lur", "bex", "sat", "quo"]
    ends = ["ax", "ile", "ome", "urn", "ict", "ase", "ent", "ory"]
    vocab = [a + b for a in syl for b in ends]
    lines = [" ".join(rng.sample(vocab, 3)).capitalize() + " " + " ".join(rng.sample(vocab, 5)) + "."
             for _ in range(420)]
    words, sents = _talk(lines)
    loud = flat_loudness(words[-1]["end"])
    t0 = time.time()
    pool = candidates.find_candidates(words, sents, loud, OPTS, pool_size=60, max_overlap=0.5)
    assert words[-1]["end"] > 20 * 60 and 30 <= len(pool) <= 60 and time.time() - t0 < 20


def test_trend_relevance_counts_only_when_there_is_a_trend():
    words, sents, loud, cands = _deep_inputs()
    _, results, _ = deep.evaluate_select(sents, words, loud, OPTS, JobContext(), "talk", cands,
                                         trend_keywords=["running", "runners", "race"])
    running = [r for r in results if "runners" in r["caption_text"]]
    assert running and running[0]["deep"]["extras"]["trend_relevance"] > 0
    assert any("trending topic" in line for line in running[0]["explanation"])


def test_diversity_rejects_variants_and_published_repeats():
    words, sents = _talk(PODCAST)
    k = next(i for i, s in enumerate(sents) if s["text"].startswith("Here's the thing"))

    def res(s0: int, s1: int, score: float) -> dict:
        text = " ".join(s["text"] for s in sents[s0:s1 + 1])
        return {"s0": s0, "s1": s1, "start": sents[s0]["start"], "end": sents[s1]["end"], "score": score,
                "clip_score": score, "caption_text": text, "title": text[:40],
                "analysis": {"flags": []}}

    a, b = res(k, k + 6, 80), res(k + 1, k + 6, 75)
    chosen, rejected = diversity.select([a, b], 3, 50, sents)
    assert chosen == [a] and "Overlaps" in rejected[0]["reasons"][0]
    prior = [{"clip_id": "old", "text_sig": fingerprint.text_signature(a["caption_text"]), "title_norm": ""}]
    chosen, rejected = diversity.select([a], 3, 50, sents, prior=prior)
    assert not chosen and "already published or scheduled" in rejected[0]["reasons"][0]


def test_text_fingerprints():
    a = " ".join(PODCAST[5:12])
    b = " ".join(PODCAST[20:27])
    sa = fingerprint.text_signature(a)
    assert fingerprint.text_similarity(sa, fingerprint.text_signature(a)) == 1.0
    assert fingerprint.text_similarity(sa, fingerprint.text_signature(b)) < 0.15
    assert 0.3 < fingerprint.text_similarity(sa, fingerprint.text_signature(" ".join(PODCAST[6:12]))) < 1.0
    assert fingerprint.title_similarity("The HARD part is the silence #life", "the hard part is the silence") == 1


@needs_ffmpeg
def test_video_fingerprint_survives_reencoding(tmp_path):
    def make(src: str, out: Path, crf: int) -> None:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"{src}=size=320x240:rate=25",
                        "-t", "4", "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p", str(out)], check=True)

    make("testsrc", tmp_path / "a.mp4", 18)
    make("testsrc", tmp_path / "b.mp4", 35)
    make("mandelbrot", tmp_path / "c.mp4", 18)
    ha, hb, hc = (fingerprint.video_signature(str(tmp_path / f"{n}.mp4"), 4.0) for n in "abc")
    assert len(ha) == fingerprint.FRAMES
    assert fingerprint.same_video(ha, hb) and not fingerprint.same_video(ha, hc)


# ------------------------------------------------------------------ end to end: watch folder -> clips
@pytest.fixture(scope="module")
def talk_video(tmp_path_factory):
    if not shutil.which("ffmpeg") or not (shutil.which("espeak-ng") or shutil.which("espeak")):
        pytest.skip("ffmpeg and espeak-ng are needed to build the speech test video")
    out = tmp_path_factory.mktemp("media")
    subprocess.run([sys.executable, str(HERE / "make_test_video.py"), str(out), str(HERE / "fixtures" / "face.jpg")],
                   check=True, capture_output=True)
    return out


@pytest.mark.slow
def test_clip_hunter_and_analyzer_end_to_end(talk_video, tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.autopilot import host, providers, queue, rights, state
    from clipfoundry.pipeline import transcribe as tr

    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_clips_per_source": 3, "autopilot_min_quality": 40,
                      "encoder": "x264", "x264_preset": "ultrafast", "min_duration": 12.0, "max_duration": 45.0,
                      "target_duration": 25.0})
    folder = tmp_path / "recordings"
    folder.mkdir()
    video = folder / "talk.mp4"
    os.link(talk_video / "talk.mp4", video)
    old = time.time() - 600
    os.utime(video, (old, old))
    providers.add_feed("watch_folder", "Recordings", {"path": str(folder)})
    rights.add_rule("folder", str(folder), rights.OWNED, "My recordings")
    srt = talk_video / "speech.srt"
    calls = []

    # Whisper stand-in
    def fake_transcribe(wav, duration, settings, ctx, lo=0.0, hi=1.0, vad=True, allow_cpu_fallback=True):
        assert allow_cpu_fallback is False  # Autopilot transcribes in strict GPU mode by default
        calls.append(str(wav))
        t = tr.import_transcript(srt, duration)
        t["runtime"] = {"device": "cpu", "requested_device": "cpu", "compute_type": "int8", "model": "test"}
        return t

    monkeypatch.setattr(tr, "transcribe", fake_transcribe)
    host.WorkerHost(periodic=False)

    def run(kind: str, payload: dict) -> dict:
        row = queue.enqueue(kind, payload)
        return host.HANDLERS[kind](host.Job(queue.get(row["id"]), "test"))

    run("feed_scan", {})
    run("source_scout", {})
    src = db.select("sources")[0]
    assert src["rights_status"] == "OWNED" and src["status"] == "queued"
    hunt = run("hunt_source", {"source_id": src["id"]})
    assert calls and hunt["candidates"] >= 3
    project = db.get_project(db.fetch("sources", src["id"])["project_id"])
    assert project["origin"] == "autopilot" and Path(project["source_path"]).parent != folder
    assert sorted(p.name for p in folder.iterdir()) == ["talk.mp4"]  # nothing written into the user's folder
    assert state.get("gpu:last_transcription")["device"] == "cpu"
    out = run("analyze_source", {"source_id": src["id"], "project_id": project["id"]})
    clips = [c for c in db.list_clips(project["id"]) if c["status"] == "ready"]
    assert out["clips"] == len(clips) >= 1
    s = db.fetch("sources", src["id"])
    assert s["status"] in ("analyzed", "weak") and s["clips_selected"] == len(clips)
    cand_rows = db.select("clip_candidates", "project_id = ?", (project["id"],))
    assert len(cand_rows) == hunt["candidates"] and {c["clip_id"] for c in cand_rows if c["clip_id"]} == \
        {c["id"] for c in clips}
    for c in clips:
        sc = db.fetch("clip_scores", c["id"], "clip_id")
        assert sc["clip"] is not None and sc["diversity"] is not None and sc["explanation"]
        fp = db.fetch("clip_fingerprints", c["id"], "clip_id")
        assert len(fp["phash"]) == fingerprint.FRAMES and fp["source_key"].startswith("local:")
        assert db.fetch("clip_analysis", c["id"], "clip_id")["boundary"]["lead_in"] <= 0.35 + 1e-6
    assert len(queue.jobs(worker="packager")) == len(clips)

    # every clip was planned before it was rendered, and its file is bound to exactly that plan
    from clipfoundry.autopilot import gate, scheduler
    from clipfoundry.pipeline import blueprint as bpm
    from clipfoundry.pipeline import export

    for c in clips:
        plan = bpm.plan_of(c["id"])
        assert plan is not None and plan.origin == "strategist" and plan.reasons and plan.intervals
        assert c["render_info"]["artifact"]["blueprint"]["sha256"] == plan.sha256()

    # the rest of the slice: packaging from what is heard, the final quality gate, the schedule, the export
    def drain(worker: str) -> None:
        while (job := queue.claim(worker, "test")) is not None:
            queue.complete(job, "test", host.HANDLERS[job["kind"]](host.Job(job, "test")) or {})

    drain("packager")
    drain("quality_gate")
    for c in clips:
        rep = gate.report_for(c)
        assert rep and rep["status"] == "passed", (rep or {}).get("blockers")
        assert rep["bindings"]["blueprint"]["sha256"] == bpm.plan_of(c["id"]).sha256()
    db.save_settings({"audience_youtube_intent": "SELECTED_AUDIENCE"})  # default keeps clips local: no plan at all
    planned = scheduler.plan_new(db.get_settings(), time.time())
    assert planned["created"] >= 1
    items = db.select("scheduled_publications")
    assert items and all(i["status"] == "awaiting_approval" for i in items)  # nothing goes out without approval
    zpath = export.build_zip(project, clips, tmp_path / "exports")
    assert zpath.exists() and zpath.stat().st_size > sum(Path(c["output_path"]).stat().st_size for c in clips) * 0.9


@needs_ffmpeg
def test_strict_gpu_pauses_the_hunt_instead_of_using_the_cpu(tmp_path, monkeypatch):
    from synthetic_media import make_video

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue, rights, state
    from clipfoundry.pipeline import transcribe as tr

    db.init()
    folder = tmp_path / "recordings"
    folder.mkdir()
    make_video(folder / "talk.mp4", seconds=4.0)
    rights.add_rule("folder", str(folder), rights.OWNED, "My recordings")
    src = db.insert("sources", {"platform": "local", "external_id": "talk", "title": "Talk",
                                "local_path": str(folder / "talk.mp4")})
    seen = {}

    def cuda_broken(*args, **kwargs):  # what transcribe() raises when the GPU fails and the CPU is not allowed
        seen.update(kwargs)
        raise tr.GpuTranscriptionFailed("GPU transcription failed and CPU fallback is off for Autopilot: cublas",
                                        "Install requirements-gpu.txt.")

    monkeypatch.setattr(tr, "transcribe", cuda_broken)
    host.WorkerHost(periodic=False)
    job = queue.enqueue("hunt_source", {"source_id": src["id"]})
    claimed = queue.claim("clip_hunter", "test")
    with pytest.raises(queue.Wait) as paused:
        host.HANDLERS["hunt_source"](host.Job(claimed, "test"))
    assert seen["allow_cpu_fallback"] is False  # strict GPU is Autopilot's default
    assert paused.value.reason == "gpu_failed"
    queue.wait(claimed, "test", paused.value.reason, paused.value.seconds, paused.value.message)
    row = queue.get(job["id"])
    assert row["status"] == "waiting" and row["run_after"] > time.time() + 600
    action = next(a for a in state.open_actions() if a["key"] == "gpu:strict")
    assert "gpu-check" in action["fix"] and "Allow CPU transcription" in action["fix"]
    assert db.fetch("sources", src["id"])["status_note"].startswith("Paused: GPU transcription failed")
    resumed = queue.claim("clip_hunter", "test", now=row["run_after"] + 1)
    assert resumed["attempts"] == 1  # the pause did not use up an attempt

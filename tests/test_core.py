"""Fast unit tests for the clip pipeline (no ffmpeg / models needed)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from clipfoundry import config
from clipfoundry.pipeline import candidates, captions, hooks, llm, render, scoring, transcribe
from clipfoundry.pipeline.audio import Loudness
from clipfoundry.pipeline.text_utils import build_sentences

SCRIPT = [
    "Here's the biggest mistake most people make when they start a business.",
    "They spend months building a product nobody asked for.",
    "I did exactly that. I spent a whole year and all my savings on it.",
    "And when we launched, we got three customers. Three.",
    "So what changed? I started talking to people before building anything.",
    "That's why my second company made money in the first month.",
    "The lesson is simple. Talk to customers first, then build.",
    "Um, okay, let's move on to something else.",
    "People ask me about the weather in the mountains a lot.",
    "It is usually cold. Sometimes it rains. That is about it.",
    "Why do most diets fail after two weeks?",
    "Because willpower is a terrible strategy.",
    "Your environment beats your motivation every single time.",
    "If there is no junk food in your house, you simply cannot eat it.",
    "That is the whole secret. Change the environment, not your mindset.",
    "Anyway, uh, that was a lot of talking.",
    "Next week we will talk about the schedule and some logistics.",
    "The meeting is on Tuesday. Bring your notes. That's all for today.",
]


def _srt(lines: list[str], wps: float = 2.8, gap: float = 0.5) -> str:
    out, t = [], 0.5
    for k, line in enumerate(lines, 1):
        d = len(line.split()) / wps
        a, b = t, t + d

        def ts(x: float) -> str:
            ms = int(round(x * 1000))
            return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

        out.append(f"{k}\n{ts(a)} --> {ts(b)}\n{line}\n")
        t = b + gap
    return "\n".join(out)


@pytest.fixture()
def transcript():
    segs = transcribe.parse_subtitles(_srt(SCRIPT))
    words = transcribe.flatten_words({"segments": segs})
    return words, build_sentences(words)


def flat_loudness(duration: float) -> Loudness:
    return Loudness({"hop": 0.1, "db": [-20.0] * int(duration * 10 + 10)})


def test_parse_subtitles_and_words(transcript):
    words, sentences = transcript
    assert len(words) == sum(len(s.split()) for s in SCRIPT)
    assert all(w["end"] > w["start"] for w in words)
    assert all(words[i]["start"] >= words[i - 1]["start"] for i in range(1, len(words)))
    assert sentences[0]["text"].startswith("Here's the biggest mistake")
    assert sentences[0]["text"].endswith("business.")


def test_vtt_parsing():
    vtt = "WEBVTT\n\n00:01.000 --> 00:03.500 align:start\n<v Bob>Hello <b>there</b> friend.\n"
    segs = transcribe.parse_subtitles(vtt)
    assert segs[0]["text"] == "Hello there friend."
    assert segs[0]["start"] == 1.0 and segs[0]["end"] == 3.5


def test_candidates_are_natural_diverse_and_gated(transcript):
    words, sentences = transcript
    opts = dict(config.DEFAULT_SETTINGS)
    cands = candidates.find_candidates(words, sentences, flat_loudness(words[-1]["end"]), opts, pool_size=8)
    assert cands
    for c in cands:  # every candidate starts and ends on a sentence boundary
        assert c["start"] == sentences[c["s0"]]["start"]
        assert c["end"] == sentences[c["s1"]]["end"]
    for i, a in enumerate(cands):  # no two candidates cover the same moment
        for b in cands[i + 1:]:
            inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
            assert inter <= 0.15 * min(a["dur"], b["dur"]) + 1e-6
    results, _ = scoring.evaluate(cands, sentences, opts, _ctx(), "test", 0, 1, words=words,
                                  loud=flat_loudness(words[-1]["end"]))
    chosen = scoring.select(results, 10, 50)
    assert 1 <= len(chosen) < 10  # quality gate: fewer clips than requested when content is thin
    firsts = {sentences[c["s0"]]["text"] for c in chosen}
    assert any(t.startswith("Here's the biggest mistake") for t in firsts)
    for c in chosen:
        last = sentences[c["s1"]]["text"]
        assert not last.startswith(("Next week", "Anyway", "Um")), last
        assert 0 <= c["score"] <= 100
        assert c["hook"] and len(c["hooks_alt"]) == 3


def _ctx():
    from clipfoundry.pipeline.common import JobContext

    return JobContext()


def test_refine_bounds_pads_into_pauses(transcript):
    _, sentences = transcript
    cand = {"s0": 1, "s1": 3}
    start, end = candidates.refine_bounds(cand, sentences, 999)
    assert sentences[0]["end"] <= start <= sentences[1]["start"]
    assert sentences[3]["end"] <= end <= sentences[4]["start"]


def test_hooks_are_grounded():
    text = "I lost ten thousand dollars in my first startup. The lesson is simple: talk to customers first."
    assert hooks.is_grounded("The lesson is simple: talk to customers first", text)
    assert not hooks.is_grounded("How Elon Musk lost 10 million dollars", text)
    assert not hooks.is_grounded("I lost 50,000 dollars", text)
    hook, alts = hooks.heuristic_hooks(["Why do most diets fail after two weeks?",
                                        "Because willpower is a terrible strategy.",
                                        "Change the environment, not your mindset."])
    assert hook == "Why do most diets fail after two weeks?"
    assert len(alts) == 3
    for h in [hook, *alts]:
        assert hooks.is_grounded(h.strip("“”"), "Why do most diets fail after two weeks? Because willpower is a "
                                                          "terrible strategy. Change the environment, not your mindset.")


def test_llm_response_parsing():
    raw = 'Sure! {"hook": 8, "engagement": "7", "context": 11, "payoff": 6, "standalone": 9, "category": "story",' \
          ' "title": "The day my laptop died", "hook_text": "My laptop died on stage", "alt_hooks": ["a", "b", "c", "d"],' \
          ' "hashtags": "#stage, public speaking", "start_sentence": 1, "end_sentence": 3, "reason": "ok"} trailing'
    out = llm.parse_response(raw, 5)
    assert out["scores"]["context"] == 10.0 and out["scores"]["engagement"] == 7.0
    assert out["category"] == "Story"
    assert out["range"] == (1, 3)
    assert len(out["alt_hooks"]) == 3
    assert out["hashtags"][0] == "#stage"
    with pytest.raises(llm.ProviderError):
        llm.parse_response("no json here", 3)


def test_heuristic_provider_raises_for_fallback():
    with pytest.raises(llm.ProviderError):
        llm.evaluate({"ai_provider": "heuristic"}, "v", ["a"], "", 10)


def test_keep_segments_and_timeline():
    words = [{"start": 0.2, "end": 0.6, "w": "one"}, {"start": 0.7, "end": 1.0, "w": "two"},
             {"start": 3.0, "end": 3.4, "w": "three"}, {"start": 3.5, "end": 3.9, "w": "four."}]
    fps = 25.0
    off = render.keep_segments(words, 0.0, 5.0, "off", fps)
    assert off == [(0.0, 5.0)]
    light = render.keep_segments(words, 0.0, 5.0, "light", fps)
    assert len(light) >= 2
    for a, b in light:  # frame aligned
        assert abs(a * fps - round(a * fps)) < 1e-6 and abs(b * fps - round(b * fps)) < 1e-6
    tl = render.Timeline(light)
    assert tl.duration < 5.0
    assert tl.to_out(3.0) < 3.0  # the pause before "three" was removed
    assert tl.contains(0.3) and not tl.contains(2.0)
    aggressive = render.Timeline(render.keep_segments(words, 0.0, 5.0, "aggressive", fps))
    assert aggressive.duration <= tl.duration


def test_zoom_curve_bounds():
    words = [{"start": i * 1.0, "end": i * 1.0 + 0.8, "w": "word." if i % 4 == 3 else "word"} for i in range(30)]
    z = render.zoom_curve(words, 30 * 25, 25.0, 0.07)
    assert z.min() >= 0.999 and z.max() <= 1.0701
    assert np.abs(np.diff(z)).max() < 0.02  # eased, no jumps


@pytest.mark.parametrize("style", config.CAPTION_STYLES)
def test_ass_generation(style):
    words = [{"start": 0.1 + i * 0.4, "end": 0.45 + i * 0.4, "w": w}
             for i, w in enumerate("this {is} a caption test, with several words.".split())]
    ass = captions.build_ass(words, {"caption_style": style, "hook_overlay": True, "hook_seconds": 2}, 5.0,
                             "A hook line")
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Dialogue: 2,0:00:00.00,0:00:02.00,Hook" in ass
    assert "{is}" not in ass  # braces escaped
    dialogues = [ln for ln in ass.splitlines() if ln.startswith("Dialogue: 1")]
    assert dialogues
    if style != "minimal":
        assert "\\c&H" in ass  # word-level highlight
    srt = captions.build_srt(words)
    assert srt.startswith("1\n00:00:00,100 --> ")


def test_settings_validation():
    clean = config.validate_settings({"clip_count": "10", "caption_style": "nope", "auto_zoom": "false",
                                      "crf": 99, "unknown": 1, "ai_provider": "ollama"})
    assert clean == {"clip_count": 10, "auto_zoom": False, "crf": 35, "ai_provider": "ollama"}


def test_camera_path_is_smooth_and_resets_on_cuts():
    from clipfoundry.pipeline import reframe

    t = np.arange(0, 10, 1 / 8)
    target = np.where(t < 5, 0.3, 0.7) + np.random.default_rng(0).normal(0, 0.01, len(t))
    path = reframe.build_path(t, target, [5.0], 25.0, 250, 0.32, 0.5)
    assert abs(path[100] - 0.3) < 0.06 and abs(path[240] - 0.7) < 0.06
    assert np.abs(np.diff(path[:120])).max() < 0.01  # no jitter inside a shot
    assert abs(path[126] - 0.7) < 0.08  # jumps right after the cut instead of panning


def test_export_metadata(tmp_path):
    from clipfoundry.pipeline import export

    clip_file = tmp_path / "clip.mp4"
    clip_file.write_bytes(b"fake")
    (tmp_path / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    project = {"name": "My Video", "source_filename": "my.mp4"}
    clip = {"id": "abc", "title": "Great: title?", "hook": "Hook", "hooks_alt": ["a", "b", "c"], "caption_text": "hi",
            "hashtags": ["#x"], "category": "Story", "score": 81.5, "scores": {}, "score_source": "Local heuristic",
            "start": 65.0, "end": 90.0, "duration": 25.0, "output_path": str(clip_file), "edit": {}}
    z = export.build_zip(project, [clip], tmp_path / "out")
    import zipfile

    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        meta = json.loads(zf.read("metadata.json"))
    assert "01 - Great title.mp4" in names and "metadata.csv" in names
    assert meta["clips"][0]["source_timestamp"] == "1:05 - 1:30"
    assert meta["clips"][0]["viral_potential_estimate"] == 81.5

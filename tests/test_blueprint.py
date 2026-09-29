"""Clip Blueprint: validation, edits on top of the plan, storage, and real renders that follow a plan (synthetic
ffmpeg video with a synthetic transcript)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipfoundry import config
from clipfoundry.pipeline import blueprint as bpm
from clipfoundry.pipeline import render
from clipfoundry.pipeline.common import JobContext

from synthetic_media import make_video, needs_ffmpeg, words_from

SPEECH = ("Talk to customers before you build anything. Most founders skip this step and regret it later. "
          "Ask them which problem costs them real money every week.")
WORDS = words_from(SPEECH)  # one word every 0.4 s from 0.2 s; the last one ends at 10.5 s
FIRST, THIRD = (0.1, 2.95), (6.55, 10.6)  # "Talk ... anything." and "Ask ... week.", cut between words


def plan(*intervals: tuple[float, float], **fields) -> bpm.Blueprint:
    fields.setdefault("framing", bpm.Framing(mode="center"))
    return bpm.Blueprint(clip_id="c1", project_id="p1", source_id="s1", input_hash="test",
                         intervals=[bpm.Interval(a, b) for a, b in intervals], **fields)


def messages(bp: bpm.Blueprint, level: str = "error") -> str:
    return " | ".join(i["message"] for i in bpm.validate(bp, 11.0, WORDS) if i["level"] == level)


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path / "data"


# ------------------------------------------------------------------ validation
def test_a_sound_plan_passes():
    assert bpm.validate(plan(FIRST, THIRD, hook=bpm.Hook(text="Talk to customers before you build anything")),
                        11.0, WORDS) == []


@pytest.mark.parametrize("bp, expected", [
    (plan(), "no source intervals"),
    (plan((3.0, 2.0)), "ends before it starts"),
    (plan((1.0, 1.2)), "shorter than"),
    (plan((10.0, 12.5)), "outside the source"),
    (plan(THIRD, FIRST), "comes before interval"),
    (plan((0.1, 5.0), (4.0, 8.0)), "overlaps"),
    (plan((0.1, 2.75)), "inside the word"),  # "anything." is said from 2.6 to 2.9 s
    (plan(FIRST, speed=2.0), "speed 2.0"),
    (plan(FIRST, framing=bpm.Framing(mode="orbit")), "framing mode"),
    (plan(FIRST, captions=bpm.Captions(style="comic")), "caption style"),
    (plan(FIRST, audio=bpm.Audio(gain_db=30.0)), "gain"),
    (plan(FIRST, emphasis=[{"at": 5.0, "word": "regret"}]), "outside the kept intervals"),
    (plan(FIRST, hook=bpm.Hook(text="Elon Musk says 90% of startups fail")), "on-screen hook"),
    (plan(FIRST, payoff=bpm.Payoff(text="Ask them", at=6.6)), "payoff line is cut out"),
])
def test_what_the_renderer_cannot_follow_is_rejected(bp, expected):
    assert expected in messages(bp)


def test_your_own_edits_are_warned_about_not_blocked():
    mine = bpm.with_edit(plan(FIRST), {"end": 2.75, "hook": "My take on customer research"})
    assert mine.origin == "edit" and mine.hook.written_by == "you"
    assert messages(mine) == ""
    assert "inside the word" in messages(mine, "warning") and "written by you" in messages(mine, "warning")


def test_unknown_instructions_are_reported_never_applied():
    raw = {**plan(FIRST).to_dict(), "music_bed": {"track": "lofi"}}
    raw["captions"]["animation"] = "bounce"
    bp = bpm.Blueprint.from_dict(raw)
    assert set(bp.unsupported) == {"captions.animation: not supported by the renderer",
                                   "music_bed: not supported by the renderer"}
    assert bpm.validate(bp, 11.0, WORDS) == []  # left out, reported
    assert "animation" not in bpm.render_options(bp) and bp.summary()["unsupported"] == bp.unsupported


def test_edits_and_versions_become_new_plans():
    base = plan(FIRST, THIRD, emphasis=[{"at": 9.4, "word": "money"}])
    assert bpm.with_edit(base, {}) is base
    trimmed = bpm.with_edit(base, {"start": 6.55, "caption_style": "bold"})
    assert [(i.start, i.end) for i in trimmed.intervals] == [(6.55, 10.6)]
    assert trimmed.captions.style == "bold" and trimmed.emphasis == base.emphasis
    assert trimmed.sha256() != base.sha256() and "changed by you" in trimmed.reasons[-1]
    faster = bpm.with_edit(base, {"silence": "aggressive", "remove_fillers": True, "speed": 1.08}, "version")
    assert faster.origin == "version" and faster.speed == 1.08 and faster.audio.silence == "aggressive"
    assert [(i.start, i.end) for i in faster.intervals] == [FIRST, THIRD]
    later = bpm.shifted(base, -6.0)
    assert later.intervals[1].start == pytest.approx(0.55) and later.emphasis[0]["at"] == pytest.approx(3.4)


def test_plans_are_stored_and_manual_clips_have_none(data):
    base = plan(FIRST, THIRD)
    assert bpm.for_render({"id": "c1", "edit": {}}, 11.0, WORDS) is None  # no plan: a manual clip renders as before
    bpm.save(base, [])
    assert bpm.for_render({"id": "c1", "edit": {}}, 11.0, WORDS).sha256() == base.sha256()
    edited = bpm.for_render({"id": "c1", "edit": {"end": 10.6, "start": 6.55}}, 11.0, WORDS)
    assert edited.origin == "edit"
    with pytest.raises(bpm.BlueprintInvalid, match="speed"):
        bpm.for_render({"id": "c1", "edit": {"speed": 3.0}}, 11.0, WORDS)
    from clipfoundry import db

    rows = db.select("clip_blueprints", "clip_id = 'c1'", (), "created_at")
    assert [(r["origin"], r["status"]) for r in rows] == [("strategist", "valid"), ("edit", "valid"),
                                                          ("edit", "invalid")]
    bpm.save(base, [])  # the same plan is stored once
    assert len(db.select("clip_blueprints", "clip_id = 'c1'")) == 3


# ------------------------------------------------------------------ real renders
@needs_ffmpeg
def test_the_render_follows_a_plan_that_cuts_out_a_sentence(data, tmp_path):
    from clipfoundry.pipeline import quality
    from clipfoundry.pipeline.ffmpeg_utils import probe

    src = make_video(tmp_path / "src.mp4", seconds=11.0)
    meta = probe(src)
    project = {"id": "p1", "name": "synthetic", "source_path": str(src), "dir": str(tmp_path / "proj"), "info": meta,
               "options": {}, **meta}
    bp = plan(FIRST, THIRD, emphasis=[{"at": 9.4, "word": "money"}],
              captions=bpm.Captions(style="bold", emphasis=True))
    assert bpm.validate(bp, meta["duration"], WORDS) == []
    clip = {"id": "c1", "start": 0.0, "end": 11.0, "hook": "", "edit": {}}
    out = render.render_clip(project, clip, WORDS, {**config.DEFAULT_SETTINGS, "encoder": "x264",
                                                    "x264_preset": "ultrafast"}, JobContext(), blueprint=bp)

    art = out["render_info"]["artifact"]
    assert art["blueprint"]["sha256"] == bp.sha256() and art["blueprint"]["intervals"] == [list(FIRST), list(THIRD)]
    assert json.loads((Path(art["path"]).parent / "blueprint.json").read_text()) == bp.to_dict()
    assert art["settings"]["caption_style"] == "bold"
    edl = json.loads(Path(art["edl"]).read_text())["segments"]
    assert all(any(a - 0.05 <= s["src_start"] and s["src_end"] <= b + 0.05 for a, b in (FIRST, THIRD)) for s in edl)
    expected = (FIRST[1] - FIRST[0]) + (THIRD[1] - THIRD[0])
    assert abs(art["duration"] - expected) < 0.15, (art["duration"], expected)
    heard = json.loads(Path(art["transcript"]).read_text())["text"]
    assert heard == "Talk to customers before you build anything. Ask them which problem costs them real money every week."
    srt = Path(art["captions"]["srt"]).read_text()
    assert "founders" not in srt and "regret" not in srt  # the cut sentence never flashes up in the captions
    assert out["render_info"]["emphasis_words"] == 1  # the plan's emphasis, not a recomputed one
    rep = quality.evaluate(art["path"], out["render_info"], {"edit": {}})
    assert rep["passed"], rep["blockers"]
    assert {c["name"]: c["status"] for c in rep["checks"]}["cuts"] == "pass"
    assert rep["bindings"]["blueprint"]["sha256"] == bp.sha256()


# ------------------------------------------------------------------ weak middle parts cut out automatically
TALK = ("Talk to customers before you build anything. Um, you know, like, yeah. Most founders skip this step and "
        "regret it later. Subscribe to the channel for more. Ask them which problem costs them real money every week.")
TALK_WORDS = words_from(TALK)  # a 0.1 s pause after every word; the last one ends at 14.9 s
WITHOUT_WEAK = ("Talk to customers before you build anything. Most founders skip this step and regret it later. "
                "Ask them which problem costs them real money every week.")
T, M, A = ("Talk to customers before you build anything. ", "Most founders skip this step and regret it later. ",
           "Ask them which problem costs them real money every week.")


def whole(words: list[dict], **fields) -> bpm.Blueprint:
    return plan((0.1, words[-1]["end"] + 0.1), **fields)


def kept(bp: bpm.Blueprint) -> list[tuple[float, float]]:
    return [(i.start, i.end) for i in bp.intervals]


def test_weak_middle_parts_are_cut_out_in_order_at_sentence_boundaries():
    base = whole(TALK_WORDS, emphasis=[{"at": 1.0, "word": "customers"}, {"at": 8.6, "word": "Subscribe"}])
    cut = bpm.with_middle_cuts(base, TALK_WORDS, TALK_WORDS, 5.0)
    assert kept(cut) == [(0.1, 2.95), (4.95, 8.55), (10.95, 15.0)]  # chronological, never reordered
    assert bpm.heard_text(cut, TALK_WORDS) == WITHOUT_WEAK
    assert cut.reasons[-2:] == ["cut out filler in the middle (2.0 s): “Um, you know, like, yeah.”",
                                "cut out a promotional aside in the middle (2.4 s): “Subscribe to the channel for "
                                "more.”"]
    assert cut.emphasis == [{"at": 1.0, "word": "customers"}]  # no stress on a word that is no longer said
    assert bpm.validate(cut, 16.0, TALK_WORDS) == []
    for edge in (x for i in cut.intervals for x in (i.start, i.end)):  # every cut lands in a pause
        assert not any(w["start"] < edge < w["end"] for w in TALK_WORDS)
    assert base.intervals == [bpm.Interval(0.1, 15.0)]  # the continuous plan itself is not changed


@pytest.mark.parametrize("words, min_seconds, fields", [
    (TALK_WORDS, 15.0, {}),  # the clip would get shorter than the shortest clip allowed
    (words_from(TALK, step=0.3), 5.0, {}),  # the words run together: no pause to cut in
    (words_from(T + M + "Subscribe to the channel for more. It shows which problem costs them money. " + A), 5.0,
     {}),  # "It" would point at something else
    (words_from(T + "Um, you know, like, right? " + M + A), 5.0, {}),  # questions stay
    (words_from("Um, you know, like, yeah. " + T + M + A + " Subscribe to the channel for more."), 5.0,
     {}),  # the first and last sentences are never cut
    (words_from("Talk to customers first. Um, you know, like, yeah, so, basically, like, you know, um, yeah, so. "
                "Ask what costs money."), 1.0, {}),  # most of the clip would go
    (words_from(T + "Um, you know, like, yeah. " + M + A), 5.0,
     {"payoff": bpm.Payoff(text="Um, you know, like, yeah.")}),  # the payoff line stays
])
def test_the_clip_stays_continuous_when_no_cut_is_safe(words, min_seconds, fields):
    base = whole(words, **fields)
    assert bpm.with_middle_cuts(base, words, words, min_seconds) is base


def test_the_hook_line_stays_and_at_most_two_parts_are_cut():
    hooked = whole(TALK_WORDS, hook=bpm.Hook(text="Subscribe for more"))
    assert kept(bpm.with_middle_cuts(hooked, TALK_WORDS, TALK_WORDS, 5.0)) == [(0.1, 2.95), (4.95, 15.0)]
    words = words_from(T + "Um, you know, like, yeah. " + M + "Subscribe to the channel for more. Most of them say no "
                       "at first. Uh, like, you know, so. " + A)
    cut = bpm.with_middle_cuts(whole(words), words, words, 5.0)
    assert len(cut.intervals) == 3 and "Uh, like, you know, so." in bpm.heard_text(cut, words)
    assert "Most of them say no at first." in bpm.heard_text(cut, words)


@pytest.mark.parametrize("sentence, why", [
    ("Um, you know, like, yeah.", "filler"),
    ("Okay, so, I mean, well.", "filler"),
    ("Hit the bell so you never miss one.", "a promotional aside"),
    ("So anyway, moving on.", "a warm-up line"),
    ("It works.", ""),  # short, but it says something
    ("Most of them say no at first.", ""),
    ("So, like, you know, the product is great.", ""),
    ("Let's talk about pricing.", ""),  # names the topic
    ("Check out my results after a month.", ""),
])
def test_only_sentences_that_say_nothing_are_weak(sentence, why):
    assert bpm._weak(sentence) == why  # noqa: SLF001


def test_the_strategist_cuts_only_when_the_clip_stays_long_enough():
    clip = {"id": "c1", "project_id": "p1", "start": 0.1, "end": 15.0, "score": 0.8, "reason": "advice",
            "hashtags": ["#customers", "#subscribe"]}
    short_ok = bpm.build(clip, {"id": "p1", "options": {"min_duration": 5}}, TALK_WORDS, dict(config.DEFAULT_SETTINGS))
    assert kept(short_ok) == [(0.1, 2.95), (4.95, 8.55), (10.95, 15.0)]
    assert bpm.validate(short_ok, 16.0, TALK_WORDS) == []
    assert short_ok.payoff.text == "Ask them which problem costs them real money every week."
    assert "Subscribe" not in [e["word"] for e in short_ok.emphasis]
    default = bpm.build(clip, {"id": "p1", "options": {}}, TALK_WORDS, dict(config.DEFAULT_SETTINGS))
    assert config.DEFAULT_SETTINGS["min_duration"] == 15.0 and kept(default) == [(0.1, 15.0)]


def test_a_cut_clip_is_described_by_what_is_heard():
    bp = bpm.with_middle_cuts(whole(TALK_WORDS), TALK_WORDS, TALK_WORDS, 5.0)
    promo = {"title": "Subscribe to the channel for more", "caption": "Subscribe to the channel for more",
             "description": "", "hook": "", "hashtags": ["#subscribe"]}
    fields = bpm.heard_fields(bp, TALK_WORDS, {"id": "c1", "post": promo, "hook": ""}, dict(config.DEFAULT_SETTINGS))
    assert fields["caption_text"] == WITHOUT_WEAK
    assert "subscribe" not in json.dumps(fields["post"]).lower() and fields["title"] == fields["post"]["title"]
    grounded = {"title": "Talk to customers before you build anything", "caption": "", "description": "", "hook": "",
                "hashtags": ["#customers"]}
    assert bpm.heard_fields(bp, TALK_WORDS, {"id": "c1", "post": grounded}, {}) == {"caption_text": WITHOUT_WEAK}
    assert bpm.heard_fields(whole(TALK_WORDS), TALK_WORDS, {"id": "c1", "post": promo}, {}) == {}


@needs_ffmpeg
def test_a_clip_with_its_weak_parts_cut_out_renders_captions_packages_and_passes_the_gate(data, tmp_path):
    from clipfoundry.autopilot import packaging
    from clipfoundry.pipeline import quality
    from clipfoundry.pipeline.ffmpeg_utils import probe

    src = make_video(tmp_path / "src.mp4", seconds=16.0)
    meta = probe(src)
    project = {"id": "p1", "name": "synthetic", "source_path": str(src), "dir": str(tmp_path / "proj"), "info": meta,
               "options": {"min_duration": 5}, **meta}
    clip = {"id": "c1", "project_id": "p1", "start": 0.1, "end": 15.0, "hook": "", "edit": {}, "score": 0.8}
    settings = {**config.DEFAULT_SETTINGS, "encoder": "x264", "x264_preset": "ultrafast"}
    bp = bpm.build(clip, project, TALK_WORDS, settings)
    assert len(bp.intervals) == 3 and bpm.validate(bp, meta["duration"], TALK_WORDS) == []
    out = render.render_clip(project, clip, TALK_WORDS, settings, JobContext(), blueprint=bp)

    info = out["render_info"]
    art = info["artifact"]
    expected = sum(i.end - i.start for i in bp.intervals)
    assert abs(art["duration"] - expected) < 0.15, (art["duration"], expected)
    assert json.loads(Path(art["transcript"]).read_text())["text"] == WITHOUT_WEAK
    srt = Path(art["captions"]["srt"]).read_text()
    assert "Subscribe" not in srt and "yeah" not in srt and "regret" in srt
    sents, sha = packaging.clip_sentences({**clip, "output_path": art["path"], "render_info": info})
    assert " ".join(sents) == WITHOUT_WEAK and sha == art["sha256"]
    chosen = packaging.package({**clip, "output_path": art["path"], "render_info": info, "title": ""}, None,
                               "youtube", settings)
    assert "subscribe" not in (chosen["title"] + chosen.get("description", "")).lower()
    rep = quality.evaluate(art["path"], info, {"edit": {}})
    assert rep["passed"], rep["blockers"]
    assert {c["name"]: c["status"] for c in rep["checks"]}["cuts"] == "pass"
    assert rep["bindings"]["blueprint"]["sha256"] == bp.sha256()

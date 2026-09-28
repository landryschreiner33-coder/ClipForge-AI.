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

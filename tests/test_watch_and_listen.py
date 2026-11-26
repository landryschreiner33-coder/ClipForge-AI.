"""ClipForge AI watches and listens (docs/clipforge/WATCH_AND_LISTEN.md): the built-in sound model, the frame-by-frame
watch, the model's words for each part of the video, and how all three feed clip picking and ClipForge AI's answers."""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from clipfoundry import db
from clipfoundry.pipeline import candidates as cand_mod
from clipfoundry.pipeline import deep, eyes, listen, scout, virality, watch
from clipfoundry.pipeline.audio import Loudness
from clipfoundry.pipeline.common import JobContext
from clipfoundry.pipeline.senses import Senses
from clipfoundry.pipeline.text_utils import build_sentences
from synthetic_media import make_video, needs_ffmpeg


# ------------------------------------------------------------------ helpers
def heard_with(duration: float, **runs: list[tuple[float, float, float]]) -> listen.Heard:
    """A Heard whose kinds are `value` over [start, end) seconds (runs={"laughter": [(10, 12, 0.7)]})."""
    n = listen.patch_count(int(duration * listen.SR))
    groups = {g: np.zeros(n, np.float32) for g in listen.GROUPS}
    mid = np.arange(n) * listen.HOP + listen.SPAN / 2
    for kind, spans in runs.items():
        for a, b, v in spans:
            groups[kind][(mid >= a) & (mid < b)] = v
    return listen.Heard(duration, groups, np.zeros((n, listen.TOP), np.int32), np.zeros((n, listen.TOP), np.float32))


def watched_with(duration: float, fps: float = 2.0, busy: tuple[float, float] | None = None,
                 cuts: list[float] | None = None, faces: bool = True) -> watch.Watched:
    n = int(duration * fps)
    t = np.arange(n) / fps
    motion = np.full(n, 0.3, np.float32)
    if busy:
        motion[(t >= busy[0]) & (t < busy[1])] = 25.0
    return watch.Watched(fps, duration, motion, np.full(n, 0.5, np.float32), np.full(n, 0.6, np.float32),
                         np.full(n, 0.4, np.float32), np.full(n, 1 if faces else 0, np.int32),
                         np.full(n, 0.3 if faces else 0.0, np.float32), np.zeros((n, 64), np.uint8), cuts or [])


def talk(n_sentences: int = 30, words_each: int = 8, gap: float = 1.0) -> list[dict]:
    """A transcript of short sentences (0.3 s words, 0.4 s apart) with a `gap` second pause after each one."""
    out, t = [], 0.5
    for s in range(n_sentences):
        for k in range(words_each):
            w = f"word{s}x{k}" + ("." if k == words_each - 1 else "")
            out.append({"w": w, "start": round(t, 3), "end": round(t + 0.3, 3)})
            t += 0.4
        t += gap
    return out


def opts(**kw) -> dict:
    return {"min_duration": 10.0, "max_duration": 40.0, "target_duration": 20.0, "clip_count": 3, **kw}


def write_wav(path: Path, x: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(listen.SR)
        wf.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


# ------------------------------------------------------------------ listening
def test_the_sound_model_ships_and_loads():
    listen.reset_for_tests()
    assert listen.MODEL.is_file() and listen.MODEL.stat().st_size < 9_000_000
    assert len(listen.class_names()) == 521
    assert listen.usable({}) and listen.problem() == ""
    assert not listen.usable({"ai_listen": False})
    # every class a kind is read from exists in the model's own list (a typo would silently hear nothing)
    names = set(listen.class_names())
    for kind, members in listen.GROUPS.items():
        assert set(members) <= names, (kind, set(members) - names)


def test_features_match_yamnet_framing():
    assert listen.patch_count(listen.SR) == 2                    # 1 s: two 0.96 s windows, 0.48 s apart
    assert listen.patch_count(listen.PATCH_SAMPLES) == 1
    x = np.random.default_rng(1).normal(0, 0.1, listen.SR * 3).astype(np.float32)
    p = listen.patches(x, 0, listen.patch_count(len(x)))
    assert p.shape == (listen.patch_count(len(x)), 96, 64)
    lm = listen.log_mel(x)
    assert np.allclose(p[1], lm[48:144])                          # window k starts 48 log-mel frames after k-1
    m = listen.mel_matrix()
    assert m.shape == (257, 64) and not m[0].any()                # the DC bin is left out, as in TensorFlow


def test_it_hears_a_tone_and_silence(tmp_path):
    t = np.arange(listen.SR * 4) / listen.SR
    x = np.concatenate([0.5 * np.sin(2 * np.pi * 1000 * t), np.zeros(listen.SR * 4)]).astype(np.float32)
    heard = listen.analyze(write_wav(tmp_path / "a.wav", x), cache=tmp_path / "sounds.json")
    assert heard is not None and abs(heard.duration - 8.0) < 0.01
    tone = [n for n, _ in heard.top_sounds(0.5, 3.0, 3)]
    assert {"Sine wave", "Beep, bleep"} & set(tone), tone
    assert heard.share("silence", 5.0, 7.5) > 0.8
    assert heard.share("speech", 0, 8) == 0.0


def test_listening_is_kept_and_read_back(tmp_path, monkeypatch):
    x = (0.2 * np.sin(2 * np.pi * 440 * np.arange(listen.SR * 3) / listen.SR)).astype(np.float32)
    wav = write_wav(tmp_path / "a.wav", x)
    first = listen.analyze(wav, cache=tmp_path / "sounds.json")
    calls = []
    monkeypatch.setattr(listen._Model, "run", lambda self, p: calls.append(1) or np.zeros((len(p), 521)))
    again = listen.analyze(wav, cache=tmp_path / "sounds.json")
    assert not calls and again is not None and again.n == first.n
    assert np.allclose(again.groups["music"], first.groups["music"], atol=1 / 255)
    assert listen.analyze(wav, settings={"ai_listen": False}) is None


def test_events_and_reactions_leave_out_the_words():
    h = heard_with(30, laughter=[(10.0, 13.0, 0.7)], music=[(0, 30, 0.8)], speech=[(0, 10, 0.9)])
    kinds = [e["kind"] for e in h.events]
    assert "laughter" in kinds and "music" in kinds
    laugh = next(e for e in h.events if e["kind"] == "laughter")
    assert 9.0 <= laugh["start"] <= 10.5 and 12.5 <= laugh["end"] <= 14.0
    # somebody talks over the first second of the laugh: only the wordless rest counts
    words = [{"w": "yes", "start": laugh["start"], "end": laugh["start"] + 1.0}]
    runs = h.reaction_runs(0, 30, words)
    assert len(runs) == 1 and runs[0][0] >= laugh["start"] + 1.0
    assert h.reaction_runs(0, 30, words, kinds=("crash",)) == []       # music is never a reaction
    f = h.features(0.0, 11.0)
    assert f["ends_on_reaction"] and f["reactions"] == 1 and f["music"] > 0.9
    assert "laughter" in h.note(8, 12) and "music" in h.note(8, 12)
    back = listen.Heard.from_json(json.loads(json.dumps(h.to_json())))
    assert back is not None and back.events == h.events


def test_a_song_is_no_longer_a_reaction_but_a_laugh_is():
    """Before, any loud stretch without words passed for a reaction; with the sound named, music does not."""
    loud = Loudness({"hop": 0.1, "db": [-30.0] * 100 + [-8.0] * 50 + [-30.0] * 150})   # loud 10-15 s, no words
    assert virality.wordless_loud([], loud, 0, 30)                    # loudness alone: "a reaction"
    loud.heard = heard_with(30, music=[(10, 15, 0.9)])
    assert virality.wordless_loud([], loud, 0, 30) == []               # it was a song
    loud.heard = heard_with(30, laughter=[(10, 12, 0.6)])
    assert virality.wordless_loud([], loud, 0, 30)


# ------------------------------------------------------------------ watching
@needs_ffmpeg
def test_watching_a_video_finds_its_cuts_and_movement(tmp_path):
    a = make_video(tmp_path / "a.mp4", 6.0, size="320x180", audio=False)                     # moving pattern
    b = make_video(tmp_path / "b.mp4", 6.0, size="320x180", audio=False, frozen=True)        # a grey still
    lst = tmp_path / "list.txt"
    lst.write_text(f"file '{a}'\nfile '{b}'\n")
    src = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i",
                    str(lst), "-c", "copy", str(src)], check=True)
    meta = {"duration": 12.0, "width": 320, "height": 180, "has_video": True}
    w = watch.scan(src, meta, JobContext(), tmp_path / "watch.json")
    assert w is not None and w.fps == 2.0 and abs(w.n - 24) <= 2
    assert any(5.0 <= c <= 7.0 for c in w.cuts), w.cuts
    assert w.motion[2:10].mean() > 3 * max(0.1, w.motion[14:].mean())
    assert w.features(0, 6)["action"] > w.features(6.5, 12)["action"]
    assert w.keyframes(0, 12, 4) == sorted(w.keyframes(0, 12, 4)) and len(w.keyframes(0, 12, 4)) == 4
    parts = w.segments()
    assert parts[0]["start"] == 0.0 and parts[-1]["end"] == 12.0
    assert all(p["end"] - p["start"] <= watch.SEGMENT_MAX + 1e-6 for p in parts)
    again = watch.scan(src, meta, JobContext(), tmp_path / "watch.json")      # read back, not decoded again
    assert again is not None and again.cuts == w.cuts and np.allclose(again.motion, w.motion, atol=0.25)
    assert watch.scan(src, meta, settings={"ai_watch": False}) is None


def test_still_parts_take_the_words_of_the_part_before():
    w = watched_with(40, busy=(30, 34), cuts=[20.0])
    parts = w.segments()
    assert [round(p["start"]) for p in parts] == [0, 7, 13, 20, 27, 33]
    assert parts[1]["same_as_before"] and not parts[4]["same_as_before"]   # the burst of movement is new
    assert max(w.moments(), key=lambda m: m["action"])["at"] >= 28


# ------------------------------------------------------------------ the model says what happens
def test_describing_asks_about_the_likeliest_parts_first_and_keeps_answers(tmp_path):
    video = make_video(tmp_path / "v.mp4", 40.0, size="160x90", fps=5, audio=False) if _ffmpeg() else None
    if video is None:
        pytest.skip("ffmpeg is needed")
    w = watched_with(40, busy=(30, 34), cuts=[20.0])
    asked: list[str] = []

    def fake(opts, prompt, **kw):
        asked.append(prompt.split(" of a video")[0].split("from ")[1])
        assert kw["images"] and kw["json_schema"] == eyes.DESCRIBE_SCHEMA
        return json.dumps({"what": f"a man juggles fire ({prompt[:30]})", "tags": ["fall or crash", "made-up tag"],
                           "people": 1, "action": 8, "text_on_screen": ""})

    o = {"ai_provider": "builtin", "ai_eyes": True}
    got = eyes.describe_video(str(video), w, o, JobContext(), cache=tmp_path / "seen.json",
                              priority=lambda a, b: 5.0 if a >= 27 else 0.0, complete=fake, budget=60)
    assert asked[0].startswith("0:27") or asked[0].startswith("0:33")
    assert got["answered"] == len(asked) < len(w.segments())          # still parts copied the part before
    assert any(p.get("same") for p in got["parts"]) and got["coverage"] == 1.0
    assert all(p["tags"] == ["fall or crash"] for p in got["parts"])  # only known tags are kept
    again = eyes.describe_video(str(video), w, o, JobContext(), cache=tmp_path / "seen.json",
                                complete=lambda *a, **k: pytest.fail("asked again"), budget=60)
    assert again["asked"] == 0 and len(again["parts"]) == len(got["parts"])


def test_describing_stops_when_the_time_is_up(tmp_path):
    if not _ffmpeg():
        pytest.skip("ffmpeg is needed")
    video = make_video(tmp_path / "v.mp4", 4.0, size="160x90", audio=False)
    w = watched_with(200, busy=(30, 34), cuts=[float(c) for c in range(10, 200, 10)])
    got = eyes.describe_video(str(video), w, {"ai_provider": "builtin"}, None, budget=0.0,
                              complete=lambda *a, **k: pytest.fail("no time to ask"))
    assert got["asked"] == 0 and any("Out of time" in p for p in got["problems"])


def _ffmpeg() -> bool:
    import shutil

    return bool(shutil.which("ffmpeg"))


# ------------------------------------------------------------------ what clip picking does with it
def test_senses_anchor_new_clips_and_explain_their_points():
    words = talk(30)
    sentences = build_sentences(words)
    pause = sentences[12]["end"] + 0.2                                    # a laugh in the pause after sentence 12
    s = Senses(heard_with(sentences[-1]["end"] + 5, laughter=[(pause, pause + 1.5, 0.8)]),
               watched_with(sentences[-1]["end"] + 5))
    anchors = s.anchors()
    assert anchors and anchors[0]["kind"] == "laughter" and anchors[0]["end_after"]
    loud = Loudness({"hop": 0.1, "db": [-20.0] * int(10 * (sentences[-1]["end"] + 5))})
    loud.heard = s.heard
    feats = cand_mod.sentence_features(sentences, words)
    added = cand_mod.from_senses(sentences, feats, loud, opts(), s, [])
    assert added and added[0]["s1"] == 12 and added[0]["sense"]["kind"] == "laughter"
    assert 10.0 <= added[0]["dur"] <= 40.0
    # the cut keeps the laugh after the last word
    start, end = cand_mod.refine_bounds(added[0], sentences, sentences[-1]["end"] + 5, loud)
    assert end >= pause + 0.4
    # the same moment found by the word rules is marked instead of added twice
    found = [dict(added[0], sense=None)]
    found[0].pop("sense")
    again = cand_mod.from_senses(sentences, feats, loud, opts(), s, found)
    assert again == [] and found[0]["sense"]["kind"] == "laughter"
    pts, why = s.adjust(s.features(added[0]["start"], added[0]["end"]), s.base_action())
    assert 0 < pts <= 9 and any("heard laughter at the end" in w for w in why)


def test_the_senses_never_move_a_score_more_than_nine_points():
    s = Senses(heard_with(60, laughter=[(5, 8, 0.9), (15, 18, 0.9), (25, 28, 0.9)], boom=[(20, 22, 0.9)],
                          cheering=[(28, 31, 0.9)]),
               watched_with(60, busy=(0, 30)),
               [{"start": 0, "end": 30, "what": "a fight breaks out", "tags": ["fight", "fall or crash"],
                 "action": 10, "people": 3, "text": ""}])
    pts, why = s.adjust(s.features(0, 30), 0.1)
    assert 7.0 <= pts <= 9.0 and len(why) >= 2
    most = {"heard": {"ends_on_reaction": True, "exciting": 5, "speech": 1.0,
                      "moments": [{"kind": "laughter"}] * 5},
            "watched": {"action": 1.0, "opening_action": 1.0},
            "seen": {"coverage": 1.0, "action_mean": 10, "exciting": ["fight", "fall or crash"], "nothing": 0,
                     "lines": []}}
    pts, why = Senses().adjust(most, 0.0)
    # each within its own bound, and the cap says what it took off, so the lines add up to the points
    assert pts == 9.0 and [w.split()[0] for w in why] == ["+5.0", "+3.0", "+4.0", "-3.0"]
    assert "at most ±9 in all" in why[-1] and sum(float(w.split()[0]) for w in why) == pts
    dull = Senses(heard_with(60, silence=[(0, 60, 0.9)]), watched_with(60, faces=False),
                  [{"start": 0, "end": 60, "what": "an empty room", "tags": ["nothing happens"], "action": 0,
                    "people": 0, "text": ""}])
    pts, why = dull.adjust(dull.features(0, 30), dull.base_action())
    assert -9.0 <= pts < -3 and why
    assert 0.0 <= s.interest(0, 30) <= 1.0 and s.interest(0, 30) > dull.interest(0, 30)
    assert Senses().adjust(Senses().features(0, 30)) == (0.0, [])


def test_clip_score_counts_and_explains_what_was_seen_and_heard():
    base = {"extras": {}, "audio": {"score": 0.5}, "semantic": {"score": 0.5}}
    r = {"score": 60.0, "deep": {**base, "senses": {"adjust": 4.5, "why": ["+4.5 ClipForge AI heard laughter"]}}}
    with_senses, why = deep.clip_score(r)
    without, _ = deep.clip_score({"score": 60.0, "deep": base})
    assert with_senses == pytest.approx(without + 4.5, abs=0.11)
    assert "+4.5 ClipForge AI heard laughter" in why


def test_the_scout_and_the_judge_read_what_was_seen_and_heard():
    words = talk(6)
    sentences = build_sentences(words)
    pause = sentences[2]["end"] + 0.2
    s = Senses(heard_with(40, laughter=[(pause, pause + 1.5, 0.8)]), None,
               [{"start": 0, "end": 40, "what": "two hosts at a desk", "tags": ["conversation"], "action": 3,
                 "people": 2, "text": ""}])
    b = scout.Brief("Show", 10, 40, 20)
    notes = scout._sense_notes(s, sentences, 0, len(sentences) - 1)
    text = scout.scout_prompt(b, sentences, 0, len(sentences) - 1, 1, 1, notes)
    assert "⟨seen: two hosts at a desk" in text and "heard: laughter" in text
    assert text.count("seen: two hosts") == 1                            # said once, not on every line
    plain = scout.scout_prompt(b, sentences, 0, len(sentences) - 1, 1, 1)
    assert "⟨" not in plain                                              # without the senses: as before
    finalists = [{"s0": 0, "s1": 2, "start": sentences[0]["start"], "end": sentences[2]["end"]},
                 {"s0": 3, "s1": 5, "start": sentences[3]["start"], "end": sentences[5]["end"]}]
    judged = scout.judge_prompt(b, finalists, sentences, s)
    assert "Seen: 0:00 two hosts at a desk" in judged and "Heard: " in judged
    assert scout.windows(sentences, notes=notes)[0] == (0, len(sentences) - 1)


def test_finalists_get_their_points_in_the_deep_stage(monkeypatch):
    words = talk(40)
    sentences = build_sentences(words)
    end = sentences[-1]["end"] + 5
    pause = sentences[20]["end"] + 0.2
    s = Senses(heard_with(end, laughter=[(pause, pause + 1.5, 0.8)]), watched_with(end))
    loud = Loudness({"hop": 0.1, "db": [-20.0] * int(10 * end)})
    loud.heard = s.heard
    o = {**opts(), "ai_provider": "heuristic", "deep_analysis": True, "min_score": 0}
    cands = cand_mod.find_candidates(words, sentences, loud, o, pool_size=12, max_overlap=0.5)
    cands += cand_mod.from_senses(sentences, cand_mod.sentence_features(sentences, words), loud, o, s, cands)
    for k, c in enumerate(cands):
        c["cid"] = k
    chosen, results, notes = deep.evaluate_select(sentences, words, loud, o, JobContext(), "Show", cands,
                                                  senses=s)
    assert notes["stages"]["sensed"] >= 1
    assert all("senses" in r["deep"] for r in results)
    laughs = [r for r in results if r["start"] < pause < r["end"] + 3.0 and r["deep"]["senses"]["adjust"] > 0]
    assert laughs and any(any("heard laughter" in w for w in r["explanation"]) for r in laughs)


def test_moments_seen_and_heard_never_push_out_the_best_talk_clips():
    """Three deep-stage places are kept for moments built around what was seen and heard, but only up to three: when
    such moments already rank there (a film full of action), no talk clip gives its place to one more."""
    words = talk(70)
    sentences = build_sentences(words)
    end = sentences[-1]["end"] + 5
    s = Senses(heard_with(end), watched_with(end))
    loud = Loudness({"hop": 0.1, "db": [-20.0] * int(10 * end)})
    o = {**opts(), "ai_provider": "heuristic", "deep_analysis": True, "min_score": 0}
    cands = cand_mod.find_candidates(words, sentences, loud, o, pool_size=30, max_overlap=0.5)
    assert len(cands) > deep.DEEP_KEEP + deep.SENSE_RESERVED
    for k, c in enumerate(cands):
        c["cid"] = k
        if k % 2:   # every other one, so that some rank in the deep stage's places and some below them
            c["sense"] = {"kind": "action", "why": "the picture comes alive", "at": c["start"] + 1.0}
    _, _, notes = deep.evaluate_select(sentences, words, loud, o, JobContext(), "Show", cands, senses=s)
    gave = [c for c in notes["candidates"] if any("gave its place to a moment ClipForge AI saw or heard" in r
                                                  for r in c["reasons"])]
    assert not gave, gave


# ------------------------------------------------------------------ review fixes (PR #88)
def test_a_sense_switched_off_leaves_out_what_an_earlier_run_saved(tmp_path):
    """Watching off (or another model) after a run with the built-in model: the saved descriptions no longer add
    clips or points; listening off: sounds.json is not read for picking or for the cut's pauses either."""
    from clipfoundry.pipeline import llm, render

    pdir = tmp_path / "proj"
    pdir.mkdir()
    heard = heard_with(60, laughter=[(20, 22, 0.8)])
    (pdir / "sounds.json").write_text(json.dumps({"key": {}, "heard": heard.to_json()}))
    on = {"ai_provider": "builtin", "ai_eyes": True, "ai_watch": True, "ai_listen": True}
    (pdir / "seen.json").write_text(json.dumps({"key": {"model": llm.provider_label(on)}, "parts": [
        {"id": "a", "start": 10, "end": 18, "what": "a fight", "tags": ["fight"], "action": 9, "people": 2,
         "text": ""}]}))
    meta = {"width": 1280, "has_video": True}
    assert Senses.load(pdir, on, meta).seen and Senses.load(pdir, on, meta).heard is not None
    assert Senses.load(pdir).seen                                         # no settings: everything, as before
    for off in ({**on, "ai_watch": False}, {**on, "ai_eyes": False}, {**on, "ai_provider": "heuristic"}):
        assert Senses.load(pdir, off, meta).seen == [], off
    other = {**on, "builtin_ai_level": "standard" if "basic" in llm.provider_label(on).lower() else "basic"}
    if llm.provider_label(other) != llm.provider_label(on):
        assert Senses.load(pdir, other, meta).seen == []                  # another model's words do not count
    assert Senses.load(pdir, {**on, "ai_watch": False}, meta, any_model=True).seen == []
    assert Senses.load(pdir, {**on, "ai_provider": "heuristic"}, meta, any_model=True).seen   # chat may read them
    assert Senses.load(pdir, {**on, "ai_listen": False}, meta).heard is None
    words = [{"w": "so", "start": 18.0, "end": 19.9}]
    (pdir / "loudness.json").write_text(json.dumps({"hop": 0.1, "db": [-40.0] * 600}))
    assert render.heard(pdir, words, 15, 30, on) and not render.heard(pdir, words, 15, 30, {"ai_listen": False})


def test_a_video_with_two_frames_does_not_fail_the_job():
    """A 1-second video (or a podcast whose picture is a 2-second card): too few frames to smooth over, but the
    action curve is still one value per frame and clip picking goes on."""
    for dur, fps in ((1.0, 2.0), (1.5, 2.0), (2.0, 2.0), (2.0, 1.0), (4.0, 0.5)):
        w = watched_with(dur, fps=fps, busy=(0, 0.6))
        assert len(w.action()) == w.n, (dur, fps)
        s = Senses(None, w)
        s.anchors()
        s.features(0, dur)
    big = watched_with(30, busy=(10, 14))
    a = big.action()
    win = int(round(big.fps))
    z = np.clip(big._z(), 0.0, 6.0) / 6.0
    same = np.convolve(z, np.ones(2 * win + 1) / (2 * win + 1), mode="same")
    assert np.allclose(a, np.clip(0.75 * same, 0, 1) + np.minimum(a - 0.75 * same, 0.75), atol=1e-5)


def test_stopping_while_the_model_watches_keeps_what_it_described(tmp_path):
    if not _ffmpeg():
        pytest.skip("ffmpeg is needed")
    from clipfoundry.pipeline.common import Cancelled

    video = make_video(tmp_path / "v.mp4", 40.0, size="160x90", fps=5, audio=False)
    w = watched_with(40, busy=(30, 34), cuts=[float(c) for c in range(4, 40, 4)])
    answered = []

    class StopAfterThree(JobContext):
        def check(self):
            if len(answered) >= 3:
                raise Cancelled()

    def fake(opts, prompt, **kw):
        answered.append(prompt)
        return json.dumps({"what": "a man juggles", "tags": [], "people": 1, "action": 5, "text_on_screen": ""})

    o = {"ai_provider": "builtin", "ai_eyes": True}
    with pytest.raises(Cancelled):
        eyes.describe_video(str(video), w, o, StopAfterThree(), cache=tmp_path / "seen.json", complete=fake,
                            budget=60)
    kept = json.loads((tmp_path / "seen.json").read_text())["parts"]
    assert len([p for p in kept if not p.get("same")]) == 3
    again = []
    eyes.describe_video(str(video), w, o, JobContext(), cache=tmp_path / "seen.json",
                        complete=lambda *a, **k: again.append(1) or fake(*a, **k), budget=60)
    assert len(again) == len(w.segments()) - len(kept) or len(again) < len(w.segments())


def test_autopilot_with_complete_stories_only_does_not_lose_a_place_to_a_wordless_moment(monkeypatch):
    """Autopilot and post-live decline clips without a transcript story after the selection ("Require a complete
    story"): a time window built around a moment does not compete for a place there."""
    from types import SimpleNamespace

    from clipfoundry.pipeline import process

    seen_by_deep = []

    def fake_deep(*a, **k):
        seen_by_deep.append(a[6])
        raise RuntimeError("stop")

    monkeypatch.setattr(deep, "evaluate_select", fake_deep)
    talk_clip = {"s0": 0, "s1": 2, "start": 0.0, "end": 20.0}
    timed = {"s0": -1, "s1": -1, "start": 40.0, "end": 70.0, "sense": {"kind": "action"}, "signals": {"talk": 0.1}}
    for origin, require, kept in (("autopilot", True, 1), ("live", True, 1), ("autopilot", False, 2),
                                  (None, True, 2)):
        p = SimpleNamespace(project={"origin": origin, "name": "x"}, settings={"discovery_require_complete_clips":
                                                                               require},
                            opts={"deep_analysis": True}, sentences=[{"text": "hi"}], stage=lambda *a: None,
                            words=[], loud=None, meta={}, brief=None, pdir=Path("."), senses=None)
        with pytest.raises(RuntimeError):
            process.evaluate_select(p, [dict(talk_clip), dict(timed)], JobContext())
        assert len(seen_by_deep[-1]) == kept, (origin, require)


def test_a_clip_overlapping_any_chosen_clip_is_turned_away():
    """The time window (no words) is chosen first; a talk clip overlapping it by 30% is turned away even when
    another chosen talk clip is more alike in words."""
    from clipfoundry.pipeline import diversity

    def r(start, end, score, text, s0):
        return {"start": start, "end": end, "score": score, "clip_score": score, "caption_text": text, "s0": s0,
                "s1": s0, "title": text[:10], "analysis": {"flags": []}}

    x = r(100, 130, 90, "", -1)
    y = r(300, 330, 85, "the dragon story with the dragon and the castle", 0)
    z = r(121, 151, 80, "the dragon story with the dragon and the castle again", 1)
    sentences = [{"text": y["caption_text"], "start": 300, "end": 330},
                 {"text": z["caption_text"], "start": 121, "end": 151}]
    chosen, rejected = diversity.select([x, y, z], 5, 0, sentences)
    assert [c["start"] for c in chosen] == [100, 300]
    assert any(c["start"] == 121 and any("Overlaps" in w for w in c["reasons"]) for c in rejected)


def test_a_lone_line_between_long_silences_is_not_a_two_second_clip():
    words = [{"w": "ha!", "start": 200.0, "end": 201.9}]
    words += [{"w": "far", "start": 20.0, "end": 20.5}, {"w": "away.", "start": 20.6, "end": 21.0}]
    words.sort(key=lambda w: w["start"])
    sentences = build_sentences(words)
    end = 400.0
    s = Senses(heard_with(end, laughter=[(202.0, 204.0, 0.9)]), watched_with(end))
    loud = Loudness({"hop": 0.1, "db": [-20.0] * int(10 * end)})
    o = opts(min_duration=20.0, max_duration=60.0, target_duration=30.0)
    added = cand_mod.from_senses(sentences, cand_mod.sentence_features(sentences, words), loud, o, s, [], words, end)
    assert all(c["dur"] >= max(5.0, 0.75 * o["min_duration"]) for c in added), added


def test_a_shot_cut_inside_the_cheer_does_not_cut_the_cheer_short():
    end = 300.0
    w = watched_with(end, busy=(180, 205), cuts=[201.5])
    s = Senses(heard_with(end, cheering=[(199.7, 203.0, 0.9)], boom=[(190, 191, 0.9)]), w)
    a = {"at": 199.7, "until": 203.0, "kind": "cheering", "why": "x", "strength": 0.9, "end_after": True}
    got = cand_mod._time_window(a, [], s, opts(min_duration=10.0, max_duration=60.0, target_duration=30.0), end,
                                s.base_action())
    assert got is not None and got["end"] >= 203.0


def test_a_no_speech_video_shorter_than_a_window_gets_no_window_past_its_end():
    s = Senses(heard_with(3.0, laughter=[(1.0, 2.5, 0.9)]), None)
    loud = Loudness({"hop": 0.1, "db": [-20.0] * 30})
    got = cand_mod.fallback_windows(loud, 3.0, opts(), 8, senses=s)
    assert all(w["end"] <= 3.0 for w in got)


def test_the_watch_tool_says_a_moment_is_past_the_end(tmp_path):
    from clipfoundry.brain import toolbox
    from clipfoundry.brain.tools import Ctx, ToolError

    assert toolbox._seconds("1:75") is None and toolbox._seconds("1:75:00") is None
    assert toolbox._seconds("1:15") == 75 and toolbox._seconds("1:02:03") == 3723 and toolbox._seconds("83 s") == 83
    pdir = tmp_path / "p"
    pdir.mkdir()
    (pdir / "source.mp4").write_bytes(b"0")
    (pdir / "sounds.json").write_text(json.dumps({"key": {}, "heard": heard_with(60, laughter=[(20, 22, .8)])
                                                  .to_json()}))
    project = db.create_project("Short one", duration=60, source_path=str(pdir / "source.mp4"))
    ctx = Ctx(ws=project.get("workspace_id") or "local", project_id=project["id"])
    with pytest.raises(ToolError, match="only 1:00 long"):
        toolbox._watch(ctx, {"at": "45:00"})


def test_a_whole_video_answer_names_every_kind_of_sound():
    """A one-hour show with a laugh every minute: the answer about the whole video still names the explosion near
    the end and the applause at the very end, and says how often each was heard."""
    end = 3600.0
    s = Senses(heard_with(end, laughter=[(60.0 * k + 9, 60.0 * k + 11, 0.8) for k in range(55)],
                          boom=[(3300, 3301.5, 0.9)], applause=[(3500, 3504, 0.8)]), None)
    text = " ".join(s.describe(0, end, False))
    assert "laughter 55 times" in text and "explosion" in text and "applause" in text
    short = " ".join(s.describe(0, 100, False))
    assert "laughter" in short and "times" not in short            # a short stretch keeps its moment-by-moment lines


def test_an_exciting_tag_counts_only_when_the_model_also_saw_action():
    """Real answers from the 2B model on GitHub: a man at a control room, tagged "fall or crash" five times with an
    action of 3. The repeats are read once and the tag is not believed without action; a real fight still counts."""
    raw = json.dumps({"what": "A man with glasses sits in a control room", "people": 1, "action": 3,
                      "tags": ["fall or crash"] * 5, "text_on_screen": ""})
    got = eyes._read_answer(raw)
    assert got["tags"] == ["fall or crash"]
    desk = {"start": 0, "end": 8, "what": got["what"], "tags": got["tags"], "action": 3, "people": 1, "text": ""}
    fight = {"start": 20, "end": 28, "what": "two men fight", "tags": ["fight"], "action": 8, "people": 2, "text": ""}
    s = Senses(None, None, [desk, fight])
    assert s.features(0, 8)["seen"]["exciting"] == [] and s.features(20, 28)["seen"]["exciting"] == ["fight"]
    assert [a["at"] for a in s.anchors() if a["kind"] == "seen"] == [20]


# ------------------------------------------------------------------ answers about a clip
def test_chat_answers_what_is_seen_and_heard(tmp_path):
    from clipfoundry.brain import toolbox
    from clipfoundry.brain.tools import Ctx, ToolError

    pdir = tmp_path / "proj"
    pdir.mkdir()
    (pdir / "source.mp4").write_bytes(b"0")
    project = db.create_project("Late night show", duration=60, source_path=str(pdir / "source.mp4"))
    heard = heard_with(60, laughter=[(20, 22, 0.8)], applause=[(40, 43, 0.7)])
    (pdir / "sounds.json").write_text(json.dumps({"key": {}, "heard": heard.to_json()}))
    (pdir / "seen.json").write_text(json.dumps({"key": {}, "parts": [
        {"id": "a", "start": 15, "end": 25, "what": "the host trips over a cable", "tags": ["fall or crash"],
         "people": 1, "action": 8, "text": ""}]}))
    s = Senses.load(pdir)
    db.create_clip(project["id"], rank=0, start=12.0, end=24.0, title="Cable trip", hook="", hooks_alt=[],
                   caption_text="watch this", hashtags=[], category="funny", score=80, scores={},
                   score_source="local", reason="", analysis={"senses": s.summary(12.0, 24.0)}, post={},
                   edit={}, status="ready", duration=12.0)
    ctx = Ctx(ws=project.get("workspace_id") or "local", project_id=project["id"])
    text = toolbox._clip(ctx, {"clip": "1"}).text
    assert "What is seen (ClipForge AI watched it): 0:03 the host trips over a cable" in text
    assert "What is heard: 0:07 laughter" in text
    got = toolbox._watch(ctx, {"at": "0:41"}).text
    assert "applause" in got and "around 0:41" in got
    whole = toolbox._watch(ctx, {}).text
    assert "laughter" in whole and "applause" in whole and "trips over a cable" in whole
    with pytest.raises(ToolError):
        toolbox._watch(ctx, {"at": "soon"})
    empty = db.create_project("Not watched", duration=10, source_path=str(tmp_path / "none" / "s.mp4"))
    with pytest.raises(ToolError, match="has not watched"):
        toolbox._watch(Ctx(ws=empty.get("workspace_id") or "local", project_id=empty["id"]), {})


def test_settings_say_what_is_on():
    st = Senses.status({"ai_provider": "heuristic"})
    assert st["listen"]["on"] and st["listen"]["usable"] and st["listen"]["classes"] == 521
    assert st["watch"]["on"] and not st["describe"]["on"] and not st["describe"]["builtin"]
    off = Senses.status({"ai_listen": False, "ai_watch": False, "ai_provider": "builtin"})
    assert not off["listen"]["on"] and not off["watch"]["on"] and not off["describe"]["on"]
    assert Senses.status({"ai_provider": "builtin"})["describe"]["on"]


def test_a_moment_nobody_talks_over_becomes_a_clip_of_its_own():
    """A fight two minutes after the last line: no sentence window can hold it, so a stretch of time around it does,
    its edges on shot cuts, and it is judged more on what happens than on its (few) words."""
    words = talk(6)                                                   # about 25 s of talk, then nothing
    sentences = build_sentences(words)
    end = 200.0
    w = watched_with(end, busy=(150, 158), cuts=[140.0, 162.0, 175.0])
    s = Senses(heard_with(end, boom=[(154, 155.5, 0.9)]), w)
    loud = Loudness({"hop": 0.1, "db": [-20.0] * int(10 * end)})
    o = opts()
    added = cand_mod.from_senses(sentences, cand_mod.sentence_features(sentences, words), loud, o, s, [], words, end)
    timed = [c for c in added if c["s0"] == -1]
    assert timed, added
    c = timed[0]
    assert c["start"] <= 154 <= c["end"] and o["min_duration"] <= c["dur"] <= o["max_duration"]
    assert 140.0 in (c["start"], c["end"]) or 162.0 in (c["start"], c["end"]) or 175.0 in (c["start"], c["end"])
    assert c["criteria"]["engagement"] > 0.3 and c["signals"]["talk"] == 0.0
    r = virality.no_speech(c)
    judged = s.judge_clip(c["start"], c["end"], words, r["viral_potential"], s.base_action())
    assert judged["talk"] == 0.0 and judged["show"] > r["viral_potential"]
    assert 0 < judged["show_adjust"] <= 12.0 and "little is said here (0% of the time)" in judged["show_why"]
    # this window's score already comes from what happens in it, so the deep stage does not move it there twice
    assert deep._timed(r) and not deep._timed({"s0": -1, "signals": {"seen_and_heard": 0.5}})
    once = s.judge_clip(c["start"], c["end"], words, r["viral_potential"], s.base_action(), blend=False)
    assert once["show_adjust"] == 0.0 and "show_why" not in once and once["adjust"] == judged["adjust"]
    # a clip that is talked through keeps its words' score
    busy_talk = s.judge_clip(sentences[0]["start"], sentences[-1]["end"], words, 60.0, s.base_action())
    assert busy_talk["talk"] > 0.5 and busy_talk["show_adjust"] == 0.0 and "show_why" not in busy_talk


def test_quiet_action_near_a_few_lines_gets_a_time_window_too():
    """A battle with a shout now and then: lines are near the moment, but under half of the stretch is talk, so a
    stretch of time around it is offered as well (judged on what happens), next to the sentence windows (judged on
    their words). The selection keeps the better of the two."""
    words = []
    for k, t0 in enumerate((100.0, 125.0, 150.0, 172.0)):            # four short shouts, 25 s apart
        words += [{"w": f"come{k}", "start": t0, "end": t0 + 0.4}, {"w": "on!", "start": t0 + 0.5, "end": t0 + 0.9}]
    sentences = build_sentences(words)
    end = 220.0
    s = Senses(heard_with(end, boom=[(160, 161.5, 0.9)], crash=[(166, 167, 0.8)]),
               watched_with(end, busy=(150, 175), cuts=[148.0, 177.0]))
    loud = Loudness({"hop": 0.1, "db": [-20.0] * int(10 * end)})
    o = opts()
    feats = cand_mod.sentence_features(sentences, words)
    found = [cand_mod.window(sentences, feats, 2, 3, loud, o, cand_mod.common_words(sentences))]   # 150-173 s
    added = cand_mod.from_senses(sentences, feats, loud, o, s, found, words, end)
    timed = [c for c in added if c["s0"] == -1]
    assert timed and any(c["start"] <= 160 <= c["end"] for c in timed), added
    assert all(c["signals"]["talk"] < 0.5 and c["criteria"]["engagement"] >= cand_mod.TIME_MIN_SHOW / 100
               for c in timed)


def test_a_lone_sound_over_a_still_stretch_is_not_a_clip():
    """End credits: nothing moves, nobody is on screen, and the sound model hears one gasp in the music. Too little
    happens there to stand on what happens, so no time window is made."""
    end = 300.0
    s = Senses(heard_with(end, gasp=[(280, 281, 0.3)]), watched_with(end, faces=False))
    a = {"at": 280.5, "until": 281.0, "kind": "gasp", "why": "ClipForge AI heard a gasp", "strength": 0.3,
         "end_after": True}
    assert s.show(s.features(250.0, 285.0), s.base_action()) < cand_mod.TIME_MIN_SHOW
    assert cand_mod._time_window(a, talk(4), s, opts(), end, s.base_action()) is None


def test_the_time_window_never_cuts_through_a_word():
    words = [{"w": "hey", "start": 99.8, "end": 100.4}]
    a, b = cand_mod._snap(100.0, 125.0, None, words, 10.0, 40.0)
    assert a == 99.8 and b == 125.0

"""Which live moment becomes a clip: quality over quantity (autopilot/live_pick.py and live.detect).

The rules are ClipForge's own arithmetic, so the first half needs no recording. The second half runs the live
picker on a stand-in stream: the words, the loudness and the candidate moments are given, nothing is recorded.
"""
from __future__ import annotations

import pytest

from clipfoundry.autopilot import live_pick
from test_review_submitted_live import add_live, data, going_live, turn_job  # noqa: F401 - shared live stand-ins

MINUTE = 60.0


def moment(start, score, length=30.0):
    return {"start": float(start), "end": float(start) + length, "live_score": float(score)}


def choose(rated, *, edge, clips=(), name="best", floor=55.0, history=None):
    return live_pick.choose(rated, clips=list(clips), edge=float(edge), unit=MINUTE, floor=floor,
                            pace=live_pick.rule(name), minute_best=history or {}, edge_margin=15.0)


def pick(rated, **kw):
    """The moment taken and why (`choose` without the moment waited for)."""
    return choose(rated, **kw)[:2]


def heard(minutes=live_pick.MIN_HISTORY, score=60.0):
    """A stream's own history: `minutes` rated minutes whose best moment scored `score`."""
    return {str(k): score for k in range(minutes)}


def test_unknown_choice_means_the_best_moments_only():
    assert live_pick.rule(None)["name"] == live_pick.rule("everything")["name"] == "best"
    assert live_pick.rule("most")["per_hour"] is None
    assert set(live_pick.PICKS) == set(live_pick.LABELS)


def test_the_first_minutes_and_weak_moments_are_not_clipped():
    assert pick([moment(20, 90)], edge=2 * MINUTE) == (None, "warming")
    assert pick([moment(200, 54.9)], edge=10 * MINUTE) == (None, "floor")
    assert pick([], edge=10 * MINUTE) == (None, "nothing")
    found, why = pick([moment(200, 55)], edge=10 * MINUTE)
    assert why == "taken" and found["start"] == 200


def test_the_stronger_of_two_close_moments_is_waited_for():
    """A good moment is ready, a better one just happened: nothing is taken until the better one has settled."""
    ready, forming = moment(300, 62), moment(520, 80)
    assert pick([ready, forming], edge=10 * MINUTE) == (None, "settling")  # ended 50 s ago: hold is 2 minutes
    assert choose([ready, forming], edge=10 * MINUTE)[2] is forming  # the caller is told which one is waited for
    found, _ = pick([ready, forming], edge=12 * MINUTE)
    assert found is forming
    # without the stronger one the ready moment is taken at once
    assert pick([ready], edge=10 * MINUTE)[0] is ready
    # "Every good moment" does not hold back: it takes the strongest that has finished being said
    assert pick([ready, forming], edge=10 * MINUTE, name="most")[0] is forming
    assert pick([ready, moment(575, 80)], edge=10 * MINUTE, name="most")[0] is ready
    assert pick([moment(575, 80)], edge=10 * MINUTE, name="most") == (None, "settling")  # still being said


def test_clips_keep_their_distance_unless_a_moment_stands_out():
    made = [{"start": 290.0, "end": 320.0}]
    assert pick([moment(400, 60)], edge=10 * MINUTE, clips=made) == (None, "gap")
    assert pick([moment(400, 60), moment(100, 58, 20)], edge=20 * MINUTE, clips=[{"start": 700.0, "end": 730.0}],
                )[0]["start"] == 400  # far enough from the clip at 700 s
    # the reason given is the strongest moment's, not a weaker one's further down
    assert pick([moment(400, 60), moment(100, 40)], edge=10 * MINUTE, clips=made) == (None, "gap")
    standout = moment(400, 60 + live_pick.STANDOUT)
    assert pick([standout], edge=10 * MINUTE, clips=made, history=heard())[0] is standout
    # what stands out is measured against the stream: before enough of it was heard, nothing does
    assert pick([standout], edge=10 * MINUTE, clips=made) == (None, "gap")


def test_an_hour_gets_three_clips_and_one_standout():
    made = [{"start": 600.0 * k, "end": 600.0 * k + 30} for k in (1, 2, 3)]  # at 10, 20 and 30 minutes
    edge = 45 * MINUTE
    assert pick([moment(2400, 65)], edge=edge, clips=made) == (None, "pace")
    standout = moment(2400, 75)
    assert pick([standout], edge=edge, clips=made, history=heard())[0] is standout
    assert pick([standout], edge=edge, clips=made) == (None, "pace")  # no history yet: no standout either
    assert pick([moment(2500, 90)], edge=edge, clips=[*made, {"start": 2400.0, "end": 2430.0}],
                history=heard()) == (None, "pace")
    # an hour later the first clips no longer count
    assert pick([moment(4300, 65)], edge=75 * MINUTE, clips=made)[0]["start"] == 4300
    # the other choices: six an hour, or no limit
    assert pick([moment(2400, 65)], edge=edge, clips=made, name="balanced")[0]["start"] == 2400
    many = [{"start": 60.0 * k, "end": 60.0 * k + 30} for k in range(1, 40)]
    assert pick([moment(2500, 65)], edge=edge, clips=many, name="most")[0]["start"] == 2500


def test_a_moment_must_beat_most_of_its_own_stream():
    history = {str(k): 60.0 + k for k in range(20)}  # minutes rated 60..79
    bar = live_pick.stream_bar(history, live_pick.PICKS["best"]["top"])
    assert 76 <= bar <= 77
    assert pick([moment(1500, 70)], edge=30 * MINUTE, history=history) == (None, "stream")
    assert pick([moment(1500, 77)], edge=30 * MINUTE, history=history)[0]["start"] == 1500
    # every clip the hour already has raises the bar: the third must be among the very best so far
    one = [{"start": 600.0, "end": 630.0}]
    two = [*one, {"start": 900.0, "end": 930.0}]
    assert pick([moment(1500, 77)], edge=30 * MINUTE, history=history, clips=one) == (None, "stream")
    assert pick([moment(1500, 77.5)], edge=30 * MINUTE, history=history, clips=one)[0]["start"] == 1500
    assert pick([moment(1500, 77.5)], edge=30 * MINUTE, history=history, clips=two) == (None, "stream")
    assert pick([moment(1500, 78.5)], edge=30 * MINUTE, history=history, clips=two)[0]["start"] == 1500
    # too little of the stream heard to compare it with itself: only the floor counts
    assert live_pick.stream_bar({str(k): 90.0 for k in range(live_pick.MIN_HISTORY - 1)}, 0.8) is None
    assert pick([moment(400, 60)], edge=10 * MINUTE, history={str(k): 90.0 for k in range(5)})[0]["start"] == 400
    # "Every good moment" never compares
    assert pick([moment(1500, 56)], edge=30 * MINUTE, history=history, name="most")[0]["start"] == 1500


def test_a_lively_sound_lifts_a_moment_within_bounds():
    flat = {"mean_z": -0.4, "peak_z": 0.6, "reactions": 0}
    loud = {"mean_z": 1.4, "peak_z": 3.5, "reactions": 3}
    assert live_pick.liveliness(flat, None)[0] == 0.0
    value, signs = live_pick.liveliness(loud, {"score": 0.9})
    assert value == pytest.approx(0.975) and len(signs) == 4
    assert live_pick.liveliness(loud, None)[0] == 1.0  # no kept sound file: the three loudness signs decide


def test_the_live_score_explains_itself(monkeypatch):
    from clipfoundry.pipeline import deep, semantic
    from clipfoundry.pipeline.audio import Loudness

    sents = [{"text": "Wait, watch this jump right now."}, {"text": "Nobody has ever landed it."},
             {"text": "He did it, that is the record!"}]
    words, t = [], 100.0
    for s in sents:
        s["start"] = t
        for w in s["text"].split():
            words.append({"w": w, "start": t, "end": t + 0.3})
            t += 0.4
        s["end"] = t
    # a quiet stream with a loud burst inside the moment
    db_levels = [-30.0] * 2000
    db_levels[1020:1060] = [-8.0] * 40
    loud = Loudness({"hop": 0.1, "db": db_levels})
    emb = semantic.embed_sentences(sents, {"meaning_model": False})
    r = {"s0": 0, "s1": 2, "start": 100.0, "end": t, "viral_potential": 70.0}
    lively = live_pick.rate(r, sents, words, loud, emb, {"score": 0.9, "monotone": False})
    quiet = live_pick.rate({**r, "start": 150.0, "end": 150.0 + (t - 100.0)}, sents, [], loud, emb)
    assert lively["score"] > quiet["score"] and 0 <= lively["score"] <= 100
    assert lively["why"][0].startswith("Viral Potential 70")
    assert any("livelier than the rest of the stream" in line and "estimated" in line for line in lively["why"])
    base, _ = deep.clip_score({"score": 70.0, "deep": {"semantic": semantic.features(emb, 0, 2),
                                                       "audio": lively["audio"], "visual": None, "seen": None,
                                                       "prosody": {"score": 0.9, "monotone": False},
                                                       "extras": deep.text_extras([s["text"] for s in sents],
                                                                                  semantic.features(emb, 0, 2),
                                                                                  t - 100.0, None)}})
    assert live_pick.LIFT[0] <= lively["score"] - base <= live_pick.LIFT[1]


def test_the_whole_stream_keeps_its_pace():
    best, most = live_pick.rule("best"), live_pick.rule("most")
    assert live_pick.total_cap(best, 5, 20 * 60) == 5          # a short stream: what a recorded video gets
    assert live_pick.total_cap(best, 5, 3 * 3600) == 9         # three hours at three an hour
    assert live_pick.total_cap(live_pick.rule("balanced"), 5, 3 * 3600) == 18
    assert live_pick.total_cap(most, 5, 3 * 3600) == 5         # as before: the recorded-video limit


# ------------------------------------------------------------------ the picker on a stand-in stream
SPEECH = ("Okay so here is the plan. Watch this jump right now. Nobody has ever landed it. He did it, wow. "
          "That is the new record. ").split()


@pytest.fixture
def stream(data, monkeypatch):  # noqa: F811 - the shared live fixture
    """A stream that has been recording for `minutes`; `moments` are what the candidate search would find."""
    from clipfoundry import db
    from clipfoundry.autopilot import live
    from clipfoundry.pipeline import candidates as cand_mod

    def start(minutes, moments, url="https://www.twitch.tv/SomeStreamer", **choices):
        if choices:
            db.save_settings(choices)
        src = going_live(add_live(url))
        sess = live.Session(src, db.get_settings())
        sess.offset = minutes * 60.0
        sess.env = [-25.0] * int(sess.offset * 10)
        sess.words = [{"w": SPEECH[i % len(SPEECH)], "start": i * 0.5, "end": i * 0.5 + 0.4}
                      for i in range(int(sess.offset * 2))]
        sess.segments = [{"name": f"r001_{k:05d}.mkv", "start": k * 60.0, "end": (k + 1) * 60.0}
                         for k in range(int(minutes))]
        scores = {}

        def find(words, sents, loud, opts, pool_size=12):
            assert pool_size == live_pick.POOL
            out = []
            for at, score in moments:
                inside = [k for k, s in enumerate(sents) if s["start"] >= at and s["end"] <= at + 30]
                if inside:
                    out.append({"start": sents[inside[0]]["start"], "end": sents[inside[-1]]["end"],
                                "s0": inside[0], "s1": inside[-1]})
                    scores[(inside[0], inside[-1])] = score
            return out

        def analyze(a, b, sents, feats, words, loud, opts):
            return {"s0": a, "s1": b, "start": sents[a]["start"], "end": sents[b]["end"], "raw": scores[(a, b)],
                    "viral_potential": scores[(a, b)], "blocked": False,
                    "structure": {"hook": True, "context": True, "payoff": True}, "flags": []}

        monkeypatch.setattr(cand_mod, "find_candidates", find)
        monkeypatch.setattr(live.virality, "variants", lambda s0, s1, sents, opts, feats: [(s0, s1)])
        monkeypatch.setattr(live.virality, "analyze", analyze)
        # These streams are about which moment is taken and when; how much of it is kept has its own tests below.
        monkeypatch.setattr(live_pick, "fuller", lambda s0, s1, sents, feats, opts: [])
        return sess, turn_job(src)

    return start


def test_live_picker_takes_the_strongest_settled_moment(stream):
    from clipfoundry.autopilot import live

    sess, job = stream(10, [(200, 70.0), (320, 85.0), (585, 95.0)], autopilot_live_pick="most")
    found = live.detect(sess, job)
    assert found and 320 <= found["r"]["start"] < 350  # the strongest that has finished being said
    assert found["r"]["live_score"] == sess.minute_best[str(int(found["r"]["start"] // 60))]
    assert found["r"]["explanation"][0].startswith("Viral Potential 85")
    assert "9" not in sess.minute_best  # the moment at the live edge is rated when it is complete


def test_live_picker_waits_instead_of_taking_the_weaker_moment(stream):
    from clipfoundry.autopilot import live

    sess, job = stream(10, [(200, 70.0), (500, 90.0)])
    assert live_pick.pace(sess.project, sess.settings)["name"] == "best"
    assert live.detect(sess, job) is None
    assert sess.note == live_pick.NOTES["settling"]
    from clipfoundry import db

    again = live.Session(db.fetch("sources", sess.src["id"]), sess.settings)  # saved with the stream
    assert again.note == live_pick.NOTES["settling"] and again.minute_best == sess.minute_best
    assert again.held == sess.held and 500 <= sess.held[0]["start"] < 530  # the moment waited for comes first
    sess.offset += 120.0
    sess.env += [-25.0] * 1200
    found = live.detect(sess, job)
    assert found and 500 <= found["r"]["start"] < 530 and sess.note == live_pick.NOTES["taken"]


def test_a_moment_waited_for_is_not_lost_when_the_search_cuts_the_speech_differently(stream):
    """A minute later the search may no longer return the moment the picker waited for (more was said, so it cuts
    the same speech another way). The moment is remembered and rated again, and the weaker one is not taken."""
    from clipfoundry.autopilot import live

    moments = [(200, 70.0), (500, 90.0)]
    sess, job = stream(10, moments)
    assert live.detect(sess, job) is None and sess.note == live_pick.NOTES["settling"]
    moments.remove((500, 90.0))  # the next search does not find it again
    sess.offset += 120.0
    sess.env += [-25.0] * 1200
    found = live.detect(sess, job)
    assert found and 500 <= found["r"]["start"] < 530 and found["r"]["viral_potential"] == 90.0
    assert found["r"]["explanation"][0].startswith("Viral Potential 90")


def test_moments_remembered_between_searches_are_few_and_strong():
    weak, good, best, taken = moment(100, 50), moment(200, 70), moment(300, 90), moment(400, 80)
    many = [moment(500 + 40 * k, 60 + k) for k in range(8)]
    kept = live_pick.keep([weak, good, best, taken, *many], taken, best, 55.0)
    assert kept[0]["start"] == 300 and len(kept) == live_pick.HELD          # the one waited for first
    assert all(k["start"] not in (100, 400) for k in kept)                  # neither weak nor already taken
    assert live_pick.keep([], None, None, 55.0) == []


def test_live_picker_makes_few_clips_from_a_long_ordinary_stream(stream, monkeypatch):
    """Half an hour in which every minute has a moment that passes the minimum quality: the old picker made a clip
    nearly every minute; the default now keeps a few."""
    from clipfoundry.autopilot import live

    moments = [(60.0 * k + 5, 60.0 + (k * 7) % 23) for k in range(0, 30)]
    made = {}
    for name in ("best", "most"):
        sess, job = stream(0, moments, url=f"https://www.twitch.tv/{name}streamer", autopilot_live_pick=name)
        assert live_pick.pace(sess.project, sess.settings)["name"] == name
        for minute in range(1, 31):
            sess.offset = minute * 60.0
            sess.env = [-25.0] * int(sess.offset * 10)
            sess.words = [{"w": SPEECH[i % len(SPEECH)], "start": i * 0.5, "end": i * 0.5 + 0.4}
                          for i in range(int(sess.offset * 2))]
            found = live.detect(sess, job)
            if found:
                r = found["r"]
                sess.clips.append({"id": f"c{len(sess.clips)}", "start": r["start"], "end": r["end"],
                                   "score": r["live_score"]})
        made[name] = [c["score"] for c in sess.clips]
    assert len(made["most"]) >= 15
    assert 1 <= len(made["best"]) <= 3
    assert min(made["best"]) >= sorted(made["most"])[-4]  # each is among the strongest few the old picker made


# ------------------------------------------------------------------ longer clips: the whole moment
def spoken(n=12, seconds=4.0, gap=0.5):
    """n sentences of `seconds` each with `gap` between them, and features that say nothing starts anew."""
    sents = [{"start": k * (seconds + gap), "end": k * (seconds + gap) + seconds, "text": f"Line {k}."}
             for k in range(n)]
    feats = [{"transition": False, "boundary": 0.0, "gap_before": gap} for _ in sents]
    return sents, feats


def lasts(sents, version):
    return sents[version[1]]["end"] - sents[version[0]]["start"]


def test_fuller_versions_add_the_build_up_and_the_ending_within_the_length_allowed():
    sents, feats = spoken()
    opts = {"target_duration": 30.0, "max_duration": 40.0}
    versions = live_pick.fuller(5, 6, sents, feats, opts)
    assert versions and (5, 6) not in versions and len(set(versions)) == len(versions)
    assert all(a <= 5 and b >= 6 for a, b in versions)             # the moment itself is always inside
    assert all(lasts(sents, v) <= 40.0 for v in versions)          # never over the longest clip allowed
    assert abs(lasts(sents, versions[0]) - 30.0) == min(abs(lasts(sents, v) - 30.0) for v in versions)
    assert any(a < 5 for a, _ in versions) and any(b > 6 for _, b in versions)  # earlier lines and later ones
    # a moment that already runs as long as allowed has no fuller version
    assert live_pick.fuller(0, 8, sents, feats, opts) == []


@pytest.mark.parametrize("mark", [{"transition": True}, {"boundary": 1.4}, {"gap_before": live_pick.FULL_PAUSE + 0.5}])
def test_fuller_versions_stop_where_something_else_begins(mark):
    sents, feats = spoken()
    feats[3].update(mark)   # sentence 3 starts the moment's subject ...
    feats[9].update(mark)   # ... and sentence 9 starts the next one
    versions = live_pick.fuller(5, 6, sents, feats, {"target_duration": 30.0, "max_duration": 90.0})
    assert versions and min(a for a, _ in versions) == 3 and max(b for _, b in versions) == 8
    assert (3, 8) in versions  # the whole story, from its first line to its last


def test_the_whole_story_is_always_among_the_versions(monkeypatch):
    sents, feats = spoken(n=30)
    feats[2]["transition"] = feats[27]["transition"] = True
    opts = {"target_duration": 20.0, "max_duration": 200.0}
    monkeypatch.setattr(live_pick, "FULL_TRY", 3)
    versions = live_pick.fuller(14, 15, sents, feats, opts)
    assert (2, 26) in versions and len(versions) <= 3 + 2 * live_pick.FULL_ENDS + 1
    assert sum(1 for a, _ in versions if a == 2) >= live_pick.FULL_ENDS  # from its first line ...
    assert sum(1 for _, b in versions if b == 26) >= live_pick.FULL_ENDS  # ... and to its last
    # What was said last may still go on: without a new beginning after it, no version is anchored on the end.
    feats[27]["transition"] = False
    late = live_pick.fuller(14, 15, sents, feats, opts)
    assert all(b < 29 for a, b in late if a != 2)


def version(seconds, potential, raw=0.5):
    return {"start": 100.0, "end": 100.0 + seconds, "viral_potential": potential, "raw": raw}


def test_the_fuller_version_is_taken_when_it_is_about_as_strong():
    opts = {"target_duration": 45.0}
    core = version(20.0, 80.0)
    assert live_pick.fullest([core, version(44.0, 78.0)], opts)["end"] == 144.0   # 2 points for 24 more seconds
    assert live_pick.fullest([core, version(44.0, 70.0)], opts) is core           # it falls apart when made longer
    assert live_pick.fullest([core, version(22.0, 78.0)], opts) is core           # 2 points for 2 seconds is no trade
    # a moment is never traded down further than the whole missing length is worth
    worst = live_pick.FULL_WORTH * 45.0
    assert live_pick.fullest([core, version(45.0, 80.0 - worst - 0.1)], opts) is core
    # past the length aimed for, only the estimate decides
    assert live_pick.fullest([version(46.0, 80.0), version(80.0, 79.0)], opts)["end"] == 146.0
    assert live_pick.fullest([version(46.0, 80.0), version(80.0, 81.0)], opts)["end"] == 180.0
    # once a version has its live rating, that decides: not the first estimate
    rated = [{**core, "live": {"score": 82.0}}, {**version(44.0, 78.0), "live": {"score": 70.0}}]
    assert live_pick.ranked(rated, opts)[0]["end"] == 120.0


def told_in_full(monkeypatch, back=4, on=2, potential=78.0):
    """The stand-in stream's moments get one fuller version: `back` sentences earlier to `on` sentences later."""
    from clipfoundry.autopilot import live

    usual = live.virality.analyze
    monkeypatch.setattr(live_pick, "fuller", lambda s0, s1, sents, feats, opts: [(s0 - back, s1 + on)])
    # the stand-in speech repeats itself, which the live rating marks down the longer it runs: rate by the estimate
    monkeypatch.setattr(live_pick, "rate", lambda r, *a, **kw: {
        "score": r["viral_potential"], "why": [f"Viral Potential {r['viral_potential']:.0f}"]})

    def analyze(a, b, sents, feats, words, loud, opts):
        try:
            return usual(a, b, sents, feats, words, loud, opts)
        except KeyError:  # not one of the stream's moments: the fuller version
            return {"s0": a, "s1": b, "start": sents[a]["start"], "end": sents[b]["end"], "raw": 0.5,
                    "viral_potential": potential, "blocked": False,
                    "structure": {"hook": True, "context": True, "payoff": True}, "flags": []}

    monkeypatch.setattr(live.virality, "analyze", analyze)


LONGER = {"min_duration": 25.0, "target_duration": 45.0, "max_duration": 90.0}


def test_a_live_clip_keeps_the_build_up_and_the_ending(stream, monkeypatch):
    from clipfoundry.autopilot import live

    sess, job = stream(10, [(200, 80.0)], autopilot_live_pick="most", **LONGER)
    found = live.detect(sess, job)["r"]
    assert 200 <= found["start"] and found["end"] <= 230 and "fuller" not in found
    told_in_full(monkeypatch)
    full = live.detect(sess, job)["r"]
    assert full["start"] < found["start"] and full["end"] > found["end"]
    assert full["fuller"] == {"from": round(found["end"] - found["start"], 1),
                              "to": round(full["end"] - full["start"], 1), "core": [found["start"], found["end"]]}
    assert full["end"] - full["start"] <= 90.0
    assert any(line.startswith("Kept the build-up and the ending") for line in full["explanation"])
    assert full["live_score"] == 78.0  # the fuller version's own estimate is what the stream's bars see


def test_a_moment_that_falls_apart_when_made_longer_stays_as_found(stream, monkeypatch):
    from clipfoundry.autopilot import live

    sess, job = stream(10, [(200, 80.0)], autopilot_live_pick="most", **LONGER)
    told_in_full(monkeypatch, potential=60.0)
    found = live.detect(sess, job)["r"]
    assert 200 <= found["start"] and "fuller" not in found
    assert not any(line.startswith("Kept the build-up") for line in found["explanation"])


def test_a_fuller_version_never_runs_into_a_clip_already_made(stream, monkeypatch):
    from clipfoundry.autopilot import live

    sess, job = stream(10, [(200, 80.0)], autopilot_live_pick="most", **LONGER)
    told_in_full(monkeypatch, back=8, on=0)
    sess.clips.append({"id": "earlier", "start": 150.0, "end": 199.0, "score": 90.0})
    found = live.detect(sess, job)["r"]
    assert found["start"] >= 199.0 and "fuller" not in found  # the build-up is the earlier clip: not shown twice


def test_a_fuller_version_never_shows_a_short_clip_again(stream, monkeypatch):
    """A short clip just before the moment: the longer version shares only a small part of its own length with
    it, but every second of that is the clip's footage again."""
    from clipfoundry.autopilot import live

    sess, job = stream(10, [(200, 80.0)], autopilot_live_pick="most", **LONGER)
    told_in_full(monkeypatch, back=8, on=0)
    sess.clips.append({"id": "short", "start": 190.0, "end": 195.0, "score": 90.0})
    found = live.detect(sess, job)["r"]
    assert found["start"] >= 195.0 and "fuller" not in found


def test_a_remembered_fuller_version_follows_the_same_overlap_rule(stream, monkeypatch):
    """A fuller version remembered from the last search, and a clip made since that covers part of its build-up:
    the moment is tried again as it was found, not with footage of that clip."""
    from clipfoundry.autopilot import live

    moments = [(200, 80.0)]
    sess, job = stream(10, moments, autopilot_live_pick="most", **LONGER)
    told_in_full(monkeypatch, back=8, on=0)
    full = live.detect(sess, job)["r"]
    core = full["fuller"]["core"]
    assert full["start"] + 5.0 < core[0]
    sess.held = live_pick.keep([full], None, full, 0.0)
    moments.clear()  # the next search does not find the moment again
    sess.clips.append({"id": "since", "start": full["start"] - 30.0, "end": full["start"] + 5.0, "score": 90.0})
    found = live.detect(sess, job)["r"]
    assert [found["start"], found["end"]] == core and "fuller" not in found


def test_a_fuller_version_too_weak_for_the_stream_leaves_the_moment_as_found(stream, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import live

    sess, job = stream(10, [(200, 62.0)], autopilot_live_pick="most", autopilot_min_quality=61, **LONGER)
    assert sess.settings["autopilot_min_quality"] == db.get_settings()["autopilot_min_quality"] == 61
    told_in_full(monkeypatch, potential=60.0)   # worth taking for its length, but under this stream's minimum
    found = live.detect(sess, job)["r"]
    assert found["viral_potential"] == 62.0 and "fuller" not in found


def test_two_moments_that_are_one_story_are_rated_once(stream, monkeypatch):
    from clipfoundry.autopilot import live

    sess, job = stream(10, [(200, 80.0), (240, 79.0)], autopilot_live_pick="most", **LONGER)
    monkeypatch.setattr(live_pick, "fuller", lambda s0, s1, sents, feats, opts: [(40, 60)])
    usual, seen = live.virality.analyze, []

    def analyze(a, b, sents, *rest):
        if (a, b) != (40, 60):
            return usual(a, b, sents, *rest)
        return {"s0": a, "s1": b, "start": sents[a]["start"], "end": sents[b]["end"], "raw": 0.5,
                "viral_potential": 85.0, "blocked": False,
                "structure": {"hook": True, "context": True, "payoff": True}, "flags": []}

    monkeypatch.setattr(live.virality, "analyze", analyze)
    monkeypatch.setattr(live_pick, "rate", lambda r, *a, **kw: {"score": r["viral_potential"], "why": ["estimate"]})
    monkeypatch.setattr(live_pick, "choose", lambda rated, **kw: (seen.extend(rated) or rated[0], "taken", None))
    assert live.detect(sess, job)["r"]["s0"] == 40
    assert [(r["s0"], r["s1"]) for r in seen] == [(40, 60)]


TOURNAMENT = (
    "Okay chat I have to tell you what happened at the tournament last weekend. "
    "So we get to the venue at eight in the morning. And the first thing I see is my old teammate Marcus. "
    "The same Marcus who left our team two years ago. He walks up to me and he does not even say hello. "
    "He just says we are going to destroy you today. So now I am angry before the first match even starts. "
    "We win our first three games and they win theirs. And of course we meet them in the final. "
    "First map they beat us thirteen to two. I am thinking this is going to be the worst day of my life. "
    "But then our captain calls a timeout and says one thing. He says Marcus always pushes left when he is ahead. "
    "So on the second map we put three people on the left side. And he pushes left every single round. "
    "We win that map thirteen to four. Third map goes to overtime and it comes down to me against Marcus. "
    "One against one, ten seconds on the clock. I hear him on the left, I turn, and I hit the shot. "
    "The whole room went crazy. And Marcus walked over, shook my hand and said good game. "
    "That was the best moment of my whole career.")
CAT = (
    "Here is the story of the worst game I ever played. It was the final boss of the hardest mode. "
    "Nobody on the server had beaten it yet. We had been trying for six weeks. "
    "Every night from eight until two in the morning. "
    "My girlfriend was ready to throw my computer out the window. So this one night everything goes perfectly. "
    "We get the boss down to one percent. One percent, after six weeks. And then my cat jumps on my keyboard. "
    "My character walks straight off the platform. "
    "I am the healer so without me everybody dies in five seconds. "
    "Nobody says anything in voice chat for a full minute. Then our leader just says, was that a cat? "
    "And everybody starts laughing so hard that nobody is angry anymore. We beat the boss the next night. "
    "But the clip of my cat has two million views. So the cat is more famous than I am. "
    "And honestly she deserves it.")
SMALL_TALK = "Thank you for the sub. Welcome in everybody. Let me check the settings. One second."


def told(parts):
    """Words of a stream: each part is said at a steady pace, with six seconds of silence between the parts."""
    words, t = [], 2.0
    for part in parts:
        for w in part.split():
            length = 0.22 + 0.03 * len(w) / 4
            words.append({"w": w, "start": round(t, 2), "end": round(t + length, 2), "p": 0.9})
            t += length + (0.5 if w[-1] in ".?!" else 0.06)
        t += 6.0
    return words, t


def test_a_story_told_on_stream_is_clipped_with_its_build_up_and_its_ending(data, monkeypatch):  # noqa: F811
    """The real analysis on a stand-in stream of two stories of about a minute each: without fuller versions the
    clips are the stories' strongest lines; with them they are longer, and never longer than allowed."""
    from clipfoundry import db
    from clipfoundry.autopilot import live

    words, total = told([SMALL_TALK, TOURNAMENT, SMALL_TALK, CAT, SMALL_TALK])
    db.save_settings({"autopilot_live_pick": "most", **LONGER})
    made = {}
    for name in ("found", "full"):
        src = going_live(add_live(f"https://www.twitch.tv/{name}storyteller"))
        sess, job = live.Session(src, db.get_settings()), turn_job(src)
        with monkeypatch.context() as only_here:
            if name == "found":
                only_here.setattr(live_pick, "fuller", lambda s0, s1, sents, feats, opts: [])
            for minute in range(1, int(total // 60) + 3):
                sess.offset = minute * 60.0
                sess.env = [-25.0] * int(sess.offset * 10)
                sess.words = [w for w in words if w["end"] <= sess.offset]
                found = live.detect(sess, job)
                if found:
                    sess.clips.append({"id": f"c{len(sess.clips)}", **{k: found["r"].get(k) for k in (
                        "start", "end", "fuller", "explanation")}, "score": found["r"]["live_score"]})
        made[name] = sess.clips
    lengths = {name: [round(c["end"] - c["start"], 1) for c in clips] for name, clips in made.items()}
    assert made["found"] and made["full"]
    assert max(lengths["full"]) <= LONGER["max_duration"]
    grown = [c for c in made["full"] if c["fuller"]]
    assert grown and all(c["fuller"]["to"] > c["fuller"]["from"] for c in grown)
    assert all(any(line.startswith("Kept the build-up and the ending") for line in c["explanation"]) for c in grown)
    assert sum(lengths["full"]) / len(lengths["full"]) > sum(lengths["found"]) / len(lengths["found"])
    assert max(lengths["full"]) >= LONGER["target_duration"] > min(lengths["found"])


def test_a_stream_keeps_the_choices_it_was_added_with(data):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.autopilot import live

    db.save_settings({"autopilot_live_pick": "balanced", "autopilot_live_framing": "off"})
    src = going_live(add_live())
    sess = live.Session(src, db.get_settings())
    # no split view: the layout from Settings, and the Settings' own look for a face cam is off for this stream
    assert "layout" not in sess.project["options"] and sess.project["options"]["split_view"] == "off"
    assert sess.project["options"]["live_framing"] == "off" and sess.project["options"]["live_pick"] == "balanced"
    db.save_settings({"autopilot_live_pick": "most", "autopilot_live_framing": "split"})
    again = live.Session(db.fetch("sources", src["id"]), db.get_settings())
    assert "layout" not in again.project["options"] and again.project["options"]["live_framing"] == "off"
    assert live_pick.pace(again.project, db.get_settings())["name"] == "balanced"
    later = live.Session(going_live(add_live("https://kick.com/another")), db.get_settings())
    assert later.project["options"]["layout"] == "split" and later.project["options"]["live_pick"] == "most"
    # a wrong value never reaches a stream
    db.save_settings({"autopilot_live_pick": "everything", "autopilot_live_framing": "sideways"})
    assert db.get_settings()["autopilot_live_pick"] == "most" and db.get_settings()["autopilot_live_framing"] == "split"
    assert live_pick.choices({"intake": {"live_choices": {"framing": "sideways", "pick": "all"}}},
                               {"autopilot_live_pick": "?", "autopilot_live_framing": "?"}) == \
        {"layout": "auto", "live_framing": "auto", "live_pick": "best"}
    assert live_pick.choices({"intake": {"live_choices": {"framing": "auto", "pick": "best"}}},
                               db.get_settings()) == {"layout": "auto", "live_framing": "auto", "live_pick": "best"}


def test_a_stream_recording_since_before_the_choice_keeps_its_layout(data):  # noqa: F811
    """A stream that was being recorded before streams had a framing choice: its card says No split view, and its
    next clips are planned that way too (not with the Settings' own split view)."""
    from clipfoundry import db
    from clipfoundry.autopilot import live, submissions
    from clipfoundry.pipeline import render

    src = going_live(add_live())
    project = db.create_project("Older stream", origin="live", source_id=src["id"], status="processing",
                                options={"live_pick": "best"})
    db.update("sources", src["id"], project_id=project["id"])
    assert db.get_settings()["split_view"] == "auto"
    sess = live.Session(db.fetch("sources", src["id"]), db.get_settings())
    opts = sess.project["options"]
    assert opts["live_framing"] == "off" and opts["split_view"] == "off" and opts["live_pick"] == "best"
    planned = render.cam_layout(render.effective_options(db.get_settings(), opts, {}),
                                render.layout_chosen(sess.project, {"edit": {}}))
    assert planned == db.get_settings()["layout"]
    shown = next(row for row in submissions.live_items() if row["id"] == src["id"])
    assert shown["live"]["framing_label"] == "No split view"

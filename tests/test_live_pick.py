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


def pick(rated, *, edge, clips=(), name="best", floor=55.0, history=None):
    return live_pick.choose(rated, clips=list(clips), edge=float(edge), unit=MINUTE, floor=floor,
                            pace=live_pick.rule(name), minute_best=history or {}, edge_margin=15.0)


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
    standout = moment(400, 55 + live_pick.STANDOUT)
    assert pick([standout], edge=10 * MINUTE, clips=made)[0] is standout


def test_an_hour_gets_three_clips_and_one_standout():
    made = [{"start": 600.0 * k, "end": 600.0 * k + 30} for k in (1, 2, 3)]  # at 10, 20 and 30 minutes
    edge = 45 * MINUTE
    assert pick([moment(2400, 65)], edge=edge, clips=made) == (None, "pace")
    standout = moment(2400, 75)
    assert pick([standout], edge=edge, clips=made)[0] is standout
    assert pick([moment(2500, 90)], edge=edge, clips=[*made, {"start": 2400.0, "end": 2430.0}]) == (None, "pace")
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
    assert live.stream_pace(sess.project, sess.settings)["name"] == "best"
    assert live.detect(sess, job) is None
    assert sess.note == live_pick.NOTES["settling"]
    from clipfoundry import db

    again = live.Session(db.fetch("sources", sess.src["id"]), sess.settings)  # saved with the stream
    assert again.note == live_pick.NOTES["settling"] and again.minute_best == sess.minute_best
    sess.offset += 120.0
    sess.env += [-25.0] * 1200
    found = live.detect(sess, job)
    assert found and 500 <= found["r"]["start"] < 530 and sess.note == live_pick.NOTES["taken"]


def test_live_picker_makes_few_clips_from_a_long_ordinary_stream(stream, monkeypatch):
    """Half an hour in which every minute has a moment that passes the minimum quality: the old picker made a clip
    nearly every minute; the default now keeps a few."""
    from clipfoundry.autopilot import live

    moments = [(60.0 * k + 5, 60.0 + (k * 7) % 23) for k in range(0, 30)]
    made = {}
    for name in ("best", "most"):
        sess, job = stream(0, moments, url=f"https://www.twitch.tv/{name}streamer", autopilot_live_pick=name)
        assert live.stream_pace(sess.project, sess.settings)["name"] == name
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


def test_a_stream_keeps_the_choices_it_was_added_with(data):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.autopilot import live

    db.save_settings({"autopilot_live_pick": "balanced", "autopilot_live_framing": "off"})
    src = going_live(add_live())
    sess = live.Session(src, db.get_settings())
    assert "layout" not in sess.project["options"]  # no split view: the layout from Settings, as before
    assert sess.project["options"]["live_framing"] == "off" and sess.project["options"]["live_pick"] == "balanced"
    db.save_settings({"autopilot_live_pick": "most", "autopilot_live_framing": "split"})
    again = live.Session(db.fetch("sources", src["id"]), db.get_settings())
    assert "layout" not in again.project["options"] and again.project["options"]["live_framing"] == "off"
    assert live.stream_pace(again.project, db.get_settings())["name"] == "balanced"
    later = live.Session(going_live(add_live("https://kick.com/another")), db.get_settings())
    assert later.project["options"]["layout"] == "split" and later.project["options"]["live_pick"] == "most"
    # a wrong value never reaches a stream
    db.save_settings({"autopilot_live_pick": "everything", "autopilot_live_framing": "sideways"})
    assert db.get_settings()["autopilot_live_pick"] == "most" and db.get_settings()["autopilot_live_framing"] == "split"
    assert live.stream_choices({"intake": {"live_choices": {"framing": "sideways", "pick": "all"}}},
                               {"autopilot_live_pick": "?", "autopilot_live_framing": "?"}) == \
        {"layout": "auto", "live_framing": "auto", "live_pick": "best"}
    assert live.stream_choices({"intake": {"live_choices": {"framing": "auto", "pick": "best"}}},
                               db.get_settings()) == {"layout": "auto", "live_framing": "auto", "live_pick": "best"}

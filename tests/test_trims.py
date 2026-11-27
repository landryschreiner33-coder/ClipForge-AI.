"""Suggested trims (pipeline/trims.py) and the pauses Remove pauses keeps because they build tension."""
from __future__ import annotations

from clipfoundry.pipeline import render, trims


def words_of(text: str, t0: float = 0.0, gap: float = 0.08, pauses: dict[int, float] | None = None) -> list[dict]:
    """Timed words, 0.3 s each, with an extra pause after the word at index k (pauses={k: seconds})."""
    out, t = [], t0
    for k, w in enumerate(text.split()):
        out.append({"w": w, "start": round(t, 3), "end": round(t + 0.3, 3), "p": 0.95})
        t += 0.3 + gap + (pauses or {}).get(k, 0.0)
    return out


def ids(result: dict) -> list[str]:
    return [s["id"] for s in result["suggestions"]]


def test_warm_up_words_before_the_point_are_trimmed_with_the_reason():
    ws = words_of("So um okay the one mistake every new streamer makes is buying gear first. They should test "
                  "their voice and their schedule before spending a single dollar on a camera. That's why the "
                  "cheapest setup wins.")
    r = trims.suggest(ws, 0.0, ws[-1]["end"] + 0.3)
    lead = next(s for s in r["suggestions"] if s["id"] == "lead_in")
    assert lead["edit"]["start"] == round(ws[3]["start"] - trims.PAD, 2) and "so, um, okay" in lead["why"]
    assert lead["seconds"] > 0.8


def test_a_clip_that_starts_or_stops_mid_sentence_is_offered_the_whole_sentence():
    ws = words_of("I bought the cheap mic first. Then the stream crashed and nobody could hear me for an hour. "
                  "It was the worst night of my life. Never again.")
    clip_start, clip_end = ws[8]["start"] - 0.05, ws[18]["end"] + 0.05  # "stream crashed ..." to "... It"
    r = trims.suggest(ws, clip_start, clip_end)
    starts = next(s for s in r["suggestions"] if s["id"] == "start_mid_sentence")
    ends = next(s for s in r["suggestions"] if s["id"] == "end_mid_sentence")
    assert starts["edit"]["start"] == round(ws[6]["start"] - trims.PAD, 2)  # "Then"
    assert abs(ends["edit"]["end"] - (ws[25]["end"] + trims.END_PAD)) < 0.01  # "... my life."
    assert starts["seconds"] < 0 and ends["seconds"] < 0  # both make the clip longer


def test_an_outro_and_talk_after_the_point_are_offered_as_a_tighter_end():
    body = ("Here is the trick nobody tells you about ranked. You queue at night when the good players are asleep. "
            "That's why my rank jumped two tiers in a week. ")
    outro = words_of(body + "Thanks for watching and don't forget to subscribe.")
    r = trims.suggest(outro, 0.0, outro[-1]["end"] + 0.3)
    cut = next(s for s in r["suggestions"] if s["id"] == "outro")
    assert "Thanks for watching" in cut["why"] and cut["seconds"] > 1.5
    drift = words_of(body + "Yeah exactly. Right right. Anyway moving on to the next question.")
    r = trims.suggest(drift, 0.0, drift[-1]["end"] + 0.3)
    assert "after_payoff" in ids(r)


def test_dead_air_is_offered_but_a_pause_after_a_question_is_kept():
    text = ("You know what happened next? The whole team just left the game. I sat there alone for ten minutes "
            "waiting for a teammate who never came back to the lobby at all.")
    ws = words_of(text, pauses={4: 2.0, 12: 2.0})  # after "next?" (tension) and after "game." (dead air)
    end = ws[-1]["end"] + 0.3
    r = trims.suggest(ws, 0.0, end, silence="off")
    air = next(s for s in r["suggestions"] if s["id"] == "dead_air")
    assert air["edit"] == {"silence": "light"} and "keeps 1 pause that builds tension" in air["why"]
    assert r["kept_pauses"] and r["kept_pauses"][0]["why"] == "Builds tension: a pause after a question"
    segs = render.keep_segments(ws, 0.0, end, "light", 30.0)
    cuts = [(a1, b0) for (_, a1), (b0, _) in zip(segs, segs[1:])]  # what each cut takes out

    def left(g0: float, g1: float) -> float:
        return (g1 - g0) - sum(max(0.0, min(b, g1) - max(a, g0)) for a, b in cuts)

    assert 0.9 <= left(ws[4]["end"], ws[5]["start"]) <= 1.1  # the pause after the question keeps about a second
    assert left(ws[12]["end"], ws[13]["start"]) < 0.6  # the plain pause keeps only the padding
    assert "dead_air" not in ids(trims.suggest(ws, 0.0, end, silence="light"))  # already removing pauses


def test_tension_pause_reasons():
    assert trims.tension_pause(words_of("and the answer is")) == "after “the answer is”"
    assert trims.tension_pause(words_of("guess what")) == "after “guess what”"
    assert trims.tension_pause(words_of("so I went home.")) == ""
    assert trims.tension_pause([]) == ""


def test_the_clip_trims_route_reads_the_saved_clip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.pipeline.common import write_json

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "source.mp4").write_bytes(b"x")
    ws = words_of("So um the one mistake every new streamer makes is buying gear first before testing anything "
                  "at all on a real stream with real people.")
    write_json(folder / "transcript.json", {"segments": [{"start": 0, "end": ws[-1]["end"], "text": "",
                                                          "words": [{"w": w["w"], "start": w["start"],
                                                                     "end": w["end"], "p": 0.9}
                                                                    for w in ws]}]})
    project = db.create_project("talk", source_path=str(folder / "source.mp4"), status="ready")
    clip = db.create_clip(project["id"], start=0.0, end=ws[-1]["end"] + 0.3, title="t", status="ready")
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        body = c.get(f"/api/clips/{clip['id']}/trims").json()
    assert "lead_in" in ids(body) and body["length"] > 8

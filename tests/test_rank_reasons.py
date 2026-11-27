"""Why a clip ranks where it does: one plain line each for opening, context, pacing, payoff, audio and framing."""
from __future__ import annotations

from clipfoundry.pipeline import virality


def summary(**over) -> dict:
    base = {"factors": {"opening": 8.0, "standalone": 7.0, "pacing": 7.0},
            "signals": {"to_content_s": 0.4, "wps": 2.9, "dead_air": 0.02, "mean_confidence": 0.93},
            "structure": {"hook": True, "context": True, "payoff": True}, "flags": []}
    base.update(over)
    return base


def by_area(rs: list[dict]) -> dict:
    return {r["area"]: r for r in rs}


def test_a_strong_clip_gets_a_concrete_good_reason_in_every_area():
    rs = by_area(virality.reasons(summary(), {"mode": "split"}))
    assert list(rs) == list(virality.REASON_AREAS)
    assert all(r["good"] is True for r in rs.values())
    assert "0.4 s" in rs["Opening"]["text"] and "2.9 words a second" in rs["Pacing"]["text"]
    assert "93%" in rs["Audio"]["text"] and "Split view" in rs["Framing"]["text"]


def test_flags_and_weak_measurements_become_the_reasons_against():
    flags = [{"id": "slow_opening", "severity": "warn", "label": "Slow opening", "detail": "starts with a warm-up line"},
             {"id": "weak_context", "severity": "block", "label": "Needs outside context",
              "detail": "refers back to earlier parts of the video"},
             {"id": "weak_ending", "severity": "block", "label": "Weak ending", "detail": "ends mid-sentence"}]
    s = summary(flags=flags, signals={"to_content_s": 2.5, "wps": 1.4, "dead_air": 0.12, "mean_confidence": 0.62})
    s["factors"]["pacing"] = 3.0
    rs = by_area(virality.reasons(s, {"mode": "center", "crop_w": 0.3}))
    assert rs["Opening"]["good"] is False and "warm-up line" in rs["Opening"]["text"]
    assert rs["Context"]["good"] is False and "earlier parts" in rs["Context"]["text"]
    assert rs["Payoff"]["good"] is False and "mid-sentence" in rs["Payoff"]["text"]
    assert rs["Pacing"]["good"] is False and "1.2 s of dead air per 10 s" in rs["Pacing"]["text"]
    assert rs["Audio"]["good"] is False and rs["Framing"]["good"] is False


def test_missing_measurements_say_so_instead_of_guessing():
    s = summary(signals={"to_content_s": 0.5, "wps": 3.0, "dead_air": 0.0, "mean_confidence": None},
                structure={"payoff": False})
    rs = by_area(virality.reasons(s))
    assert rs["Audio"]["good"] is None and rs["Payoff"]["good"] is None and rs["Framing"]["good"] is None
    assert virality.reasons({}) == []


def test_clips_from_the_api_carry_their_reasons(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    project = db.create_project("talk", status="ready")
    clip = db.create_clip(project["id"], start=0, end=20, title="t", status="ready", analysis=summary())
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        got = c.get(f"/api/clips/{clip['id']}").json()
    assert [r["area"] for r in got["analysis"]["reasons"]] == list(virality.REASON_AREAS)

"""Highlighted captions (plan `captions.highlight`, made for animated shorts): one caption event per spoken word
with that word in the style's highlight colour, the plain events unchanged for exports, the editor switch, the
engine's check, and the editing-app choice that keeps a short with the built-in engine (docs/clipforge/
ANIMATED_SHORTS.md). Nothing here encodes media.
"""
from __future__ import annotations

import pytest


def _words(text: str, start: float = 0.0, step: float = 0.3) -> list[dict]:
    out, t = [], start
    for w in text.split():
        out.append({"w": w, "start": round(t, 3), "end": round(t + step - 0.05, 3)})
        t += step
    return out


def test_each_spoken_word_is_highlighted_in_its_own_event():
    from clipfoundry.studio import engine

    words = _words("Did you know octopuses have three hearts")
    caps = {"enabled": True, "style": "bold", "highlight": True}
    plain = engine.caption_events(words, caps)
    lit = engine.highlight_events(words, caps)
    # the same groups on screen, split into one event per word
    assert len(lit) == len(words)
    assert lit[0][0] == plain[0][0] and abs(lit[-1][1] - plain[-1][1]) < 0.4
    for (a, b, text), w in zip(lit, words):
        assert a < b
        assert text.count("{\\c") == 1 and "{\\r}" in text  # exactly one word is coloured
        coloured = text.split("{\\c", 1)[1].split("}", 1)[1].split("{\\r}", 1)[0]
        assert coloured.lower() == w["w"].lower()
    # back to back: no flicker between the words of one group
    for (a1, b1, _), (a2, _b2, _) in zip(lit, lit[1:]):
        assert a2 >= a1 and a2 - b1 < 0.5


def test_highlight_follows_the_style_and_never_breaks_the_subtitle_markup():
    from clipfoundry.studio import engine

    words = [{"w": "{weird}", "start": 0.0, "end": 0.3}, {"w": "back\\slash", "start": 0.3, "end": 0.6}]
    lit = engine.highlight_events(words, {"enabled": True, "style": "high_energy", "highlight": True})
    joined = " ".join(t for _, _, t in lit)
    assert "{weird}" not in joined and "(WEIRD)" in joined  # the style writes in capitals; braces are escaped
    assert "back\\slash" not in joined and "BACK/SLASH" in joined


def test_highlight_holds_through_short_gaps_and_ends_after_the_last_word():
    from clipfoundry.studio import engine

    words = _words("one two three four five six seven eight", step=0.4)
    lit = engine.highlight_events(words, {"enabled": True, "style": "bold", "highlight": True})
    assert lit[-1][1] >= words[-1]["end"]
    assert all(b - a >= 0.02 for a, b, _ in lit)


def test_the_check_and_the_editor_switch():
    from clipfoundry.studio import engine, video_flow

    plan = {"schema": engine.SCHEMA, "timebase": 1000, "engine": engine.ENGINE, "output": {"aspect": "9:16", "fps": 30},
            "layout": "fill", "clips": [], "transition": {"type": "cut", "ms": 0},
            "title": {"enabled": False, "text": "", "ms": 2500},
            "captions": {"enabled": True, "style": "bold", "position": "middle", "size": "medium", "highlight": "yes"},
            "audio": [], "tracks": engine.default_tracks(), "word_fixes": {}, "ducking": {"depth_db": 12.0}}
    problems = engine.validate(plan, {})
    assert "Highlighting the spoken word is either on or off." in problems
    plan["captions"]["highlight"] = False
    assert "Highlighting the spoken word is either on or off." not in engine.validate(plan, {})
    new, note = video_flow.apply_edit(plan, {"op": "set", "field": "caption_highlight", "value": True}, {})
    assert new["captions"]["highlight"] is True and note
    with pytest.raises(video_flow.VideoError):
        video_flow.apply_edit(plan, {"op": "set", "field": "caption_highlight", "value": "on"}, {})


def test_a_short_stays_with_the_built_in_engine_unless_filmcraft_is_chosen(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.craft import apps
    from clipfoundry.studio import video_flow

    monkeypatch.setattr(apps, "find_cli", lambda name: None)  # FilmCraft is not set up: never reached for a short
    short_plan = {"maker": "animated_short"}
    assert video_flow._craft_render({}, {}, short_plan, {}, {}, tmp_path / "x.mp4", {"edit_engine": "auto"}, None,
                                    False) == (None, "")
    # choosing FilmCraft for every final video still means FilmCraft (here: not set up, so it says so)
    with pytest.raises(video_flow.VideoError):
        video_flow._craft_render({}, {}, short_plan, {}, {}, tmp_path / "x.mp4", {"edit_engine": "filmcraft"}, None,
                                 False)

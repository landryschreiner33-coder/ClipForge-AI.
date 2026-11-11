"""How scripts/assistant_check.py judges an answer. The check talks with the real built-in model on GitHub's machines
(.github/workflows/assistant-check.yml); here its judgements are tried on answers written by hand, so a check that
passes there means what it says."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

WHY = "This version of ClipForge cannot delete projects from the chat yet; use the Projects page."


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("assistant_check",
                                                  Path(__file__).parents[1] / "scripts" / "assistant_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _not_offered(project: str) -> dict:
    """A delete that could not even be shown as a button, as ClipForge AI saves it (assistant._offer)."""
    return {"tool": "delete_project", "label": f"Could not delete {project}", "ok": False, "why": WHY,
            "not_offered": True}


WRONG_ARGS = {"tool": "delete_project", "label": "Delete project", "ok": False,
              "why": "delete_project: kind must be one of clips, full_video."}


def _turn(answer: str = "", steps: list | None = None, asked: tuple = ("delete_project",)) -> dict:
    return {"n": 8, "name": "delete", "said": "Delete the Old gear review project.", "answer": answer,
            "seconds": 4.2, "rounds": [{"who": "ClipForge AI", "asked": list(asked)}], "pending": [],
            "helpers": [], "steps": steps or [], "checks": []}


def test_only_a_change_that_could_not_be_offered_counts_as_the_answers_words(check):
    # a change whose arguments were wrong went back to the model, which must answer: it is not the answer's words
    assert check.not_offered({"steps": [WRONG_ARGS]}) == []
    gone = _not_offered("Old gear review")
    assert check.not_offered({"steps": [WRONG_ARGS, gone]}) == [gone]
    assert check.not_offered({"steps": [{**gone, "ok": True}]}) == []


def test_the_delete_turn_wants_the_right_project_and_never_a_false_claim(check):
    ok, how = check.delete_verdict(_turn("", [_not_offered("Old gear review")]))
    assert ok and "the owner sees “Could not delete Old gear review" in how
    ok, how = check.delete_verdict(_turn("", [_not_offered("Whistler bike park day")]))
    assert not ok and how == "the delete it tried was for another project: Could not delete Whistler bike park day"
    ok, how = check.delete_verdict(_turn("", [WRONG_ARGS]))  # asked again, it said nothing: no polite no
    assert not ok and "the answer says nothing" in how
    ok, how = check.delete_verdict(_turn("It's been removed.", [_not_offered("Old gear review")]))
    assert not ok and how.startswith("the answer says it was deleted")
    ok, _how = check.delete_verdict(_turn("I can't delete projects from the chat; use the Projects page.", [],
                                          asked=()))
    assert ok


def test_the_summary_shows_the_step_that_is_the_answers_words(check):
    report = {"computer": {"platform": "Linux", "memory_mb": 16384, "cpus": 4}, "setup": {}, "level": "basic",
              "model": "stand-in", "mode": "fake", "problems": [], "misses": [],
              "turns": [_turn("", [_not_offered("Old gear review")]), _turn("", [WRONG_ARGS])]}
    rows = [ln for ln in check.summary(report).splitlines() if ln.startswith("| 8 |")]
    assert len(rows) == 2
    assert "[not done: Could not delete Old gear review: This version of ClipForge cannot" in rows[0]  # clipped
    assert "(empty)" not in rows[0]
    assert "(empty)" in rows[1]  # the model was asked again and said nothing

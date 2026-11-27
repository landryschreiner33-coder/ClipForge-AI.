"""How scripts/assistant_check.py judges an answer. The check talks with the real built-in model on GitHub's machines
(.github/workflows/assistant-check.yml); here its judgements are tried on answers written by hand, so a check that
passes there means what it says."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

WHY = "That project is not there any more: it was deleted."  # brain/toolbox.py GONE: deleted while it was offered
TWO = "More than one project fits “gear review”: “Old gear review”, “Old gear review 2”. Ask the owner which one."


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("assistant_check",
                                                  Path(__file__).parents[1] / "scripts" / "assistant_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _not_offered(project: str, why: str = WHY) -> dict:
    """A delete that could not even be shown as a button, as ClipForge AI saves it (assistant._offer)."""
    return {"tool": "delete_project", "label": f"Could not delete {project}", "ok": False, "why": why,
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
    button = {"tool": "delete_project", "label": "Delete the clips project “Old gear review”", "state": "waiting"}
    ok, how = check.delete_verdict({**_turn("Press OK to delete it."), "pending": [button]})
    assert ok and how == "a delete button waits for the OK: Delete the clips project “Old gear review”"
    ok, how = check.delete_verdict({**_turn("It's been deleted."), "pending": [button]})
    assert not ok and how.endswith("(its button still waits for the OK)")


def test_the_summary_shows_the_step_that_is_the_answers_words(check):
    report = {"computer": {"platform": "Linux", "memory_mb": 16384, "cpus": 4}, "setup": {}, "level": "basic",
              "model": "stand-in", "mode": "fake", "problems": [], "misses": [],
              "turns": [_turn("", [_not_offered("gear review", TWO)]), _turn("", [WRONG_ARGS])]}
    rows = [ln for ln in check.summary(report).splitlines() if ln.startswith("| 8 |")]
    assert len(rows) == 2
    assert "[not done: Could not delete gear review: More than one project fits “gear review”: “Old gear" in rows[0]
    assert "Ask the owner which one" not in rows[0]  # each part is clipped
    assert "(empty)" not in rows[0]
    assert "(empty)" in rows[1]  # the model was asked again and said nothing


def test_githubs_machines_without_a_graphics_chip_get_three_times_the_time_for_a_note_too(check):
    # GitHub's Mac writes about 2 tokens a second: a planner note of full length (agents.NOTE_TOKENS) cannot be
    # written in the 120 s other computers get, so the note's time grows there as the answers' time does
    assert check.slow_limits("basic", github=False, mac=True) is None
    assert check.slow_limits("standard", github=False, mac=False) is None
    assert check.slow_limits("basic", github=True, mac=False) is None  # GitHub's Linux at the Basic level keeps up
    slow = check.slow_limits("standard", github=True, mac=False)
    assert slow["turn_s"] == 900.0 and slow["consult_s"] == 3 * check.CONSULT_BUDGET_S == 360.0
    assert check.slow_limits("basic", github=True, mac=True) == slow
    assert check.slow_limits("standard", github=True, mac=True) == slow
    assert "an answer may take 900 s instead of the app's 300 s" in slow["note"]
    assert "a planner's note 360 s instead of 120 s" in slow["note"]


def test_the_planner_note_gets_the_runs_time_and_is_judged_by_it(check, tmp_path, monkeypatch):
    from clipfoundry.brain import agents

    asked: list[float] = []

    def note(ws: str, task: str, *, budget_s: float) -> list[dict]:
        asked.append(budget_s)
        return [{"agent": {"name": "Script writer"}, "text": "Open on the trail's best drop.", "ok": True}]

    monkeypatch.setattr(agents, "consult", note)
    report: dict = {"turns": [], "problems": [], "misses": [], "finished": False}
    run = check.Run(tmp_path / "report.json", report)
    assert run.consult_budget_s == check.CONSULT_BUDGET_S == 120.0
    check.consult(run, {"helps_plans": True})
    run.consult_budget_s = 360.0  # what slow_limits gives a machine without a graphics chip
    check.consult(run, {"helps_plans": True})
    assert asked == [120.0, 360.0]
    usual, slow = report["turns"]
    assert "finished within 150 s" in [c["what"] for c in usual["checks"]]
    assert "finished within 390 s" in [c["what"] for c in slow["checks"]]
    assert all(c["ok"] for t in report["turns"] for c in t["checks"]) and not report["problems"]

"""ClipForge AI changes several posts at once (cancel_post, retry_post and approve_post with all: true): post words,
days and times narrow them strictly, one card lists them and always waits for the owner's OK (a misread "all" never
changes many posts on its own), and one post that cannot be changed never stops the others. Fake data only: nothing
is posted."""
from __future__ import annotations

import datetime as dt
import time

from fake_model import WS, answers_finish, install, say  # noqa: F401
from test_assistant_commands import CHI, ctx, data, make_clip, press, tool, two_posts  # noqa: F401


def _three(data) -> tuple[dict, dict, dict]:  # noqa: F811
    """Summit sunrise and Lake swim tomorrow at 10:00 and 14:00 Chicago time, Trail build in four days."""
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    a, b = two_posts(data)
    make_clip(data, "Trail build", 70)
    scheduler.plan_new(db.get_settings(), time.time())
    c = next(r for r in db.select("scheduled_publications", "", (), "planned_at") if r["id"] not in (a["id"], b["id"]))
    day = dt.datetime.now(CHI).date() + dt.timedelta(days=4)
    db.update("scheduled_publications", c["id"], planned_at=dt.datetime.combine(day, dt.time(11), CHI).timestamp())
    return a, b, db.fetch("scheduled_publications", c["id"])


def test_cancel_every_planned_post_with_one_card(data):  # noqa: F811
    from clipfoundry import db

    rows = _three(data)
    card, done = press("cancel_post", {"all": True})
    assert card["label"] == "Don't post these 3 posts" and card["ask"] is True
    assert card["detail"][0].startswith("“Summit sunrise” on YouTube") and len(card["args"]["posts"]) == 3
    assert done.ok and done.text.startswith("Took them off the schedule (3): “Summit sunrise”, “Lake swim”")
    assert {db.fetch("scheduled_publications", r["id"])["status"] for r in rows} == {"canceled"}
    assert done.summary == "Took posts off the schedule (3 of 3)"


def test_words_and_days_narrow_them_strictly(data):  # noqa: F811
    import pytest

    from clipfoundry.brain import tools

    a, b, c = _three(data)
    card = tool("cancel_post").preview(ctx(), tools.check_args(tool("cancel_post"), {"all": True,
                                                                                     "post": "tomorrow"}))
    assert card["label"] == "Don't post these 2 posts" and set(card["args"]["posts"]) == {a["id"], b["id"]}
    card = tool("cancel_post").preview(ctx(), {"all": True, "post": "all my posts at 14:00"})
    assert card["args"]["post"] == b["id"] and "posts" not in card["args"]  # only one fits: the one-post card
    with pytest.raises(tools.ToolError, match="matching “sunrise lake”"):  # no post holds both words
        tool("cancel_post").preview(ctx(), {"all": True, "post": "sunrise lake"})
    card = tool("cancel_post").preview(ctx(), {"all": True, "post": "trail"})
    assert card["args"]["post"] == c["id"]


def test_no_post_fits_says_so(data):  # noqa: F811
    import pytest

    from clipfoundry.brain.tools import ToolError

    _three(data)
    with pytest.raises(ToolError, match="There is no post that is planned matching “kayak”"):
        tool("cancel_post").preview(ctx(), {"all": True, "post": "kayak"})


def test_retry_every_failed_post(data):  # noqa: F811
    from clipfoundry import db

    a, b, c = _three(data)
    for r in (a, b):
        db.update("scheduled_publications", r["id"], status="failed", last_error="upload timed out")
    card, done = press("retry_post", {"all": True})
    assert card["label"] == "Try these 2 posts again" and "valid approval" in card["detail"][-1]
    assert done.ok and "(2)" in done.text
    assert {db.fetch("scheduled_publications", r["id"])["status"] for r in (a, b)} <= {"approved",
                                                                                     "awaiting_approval"}
    assert db.fetch("scheduled_publications", c["id"])["status"] == c["status"]


def test_approve_all_leaves_out_what_the_post_page_would_refuse(data):  # noqa: F811
    from clipfoundry.brain import tools

    _three(data)
    t = tool("approve_post")
    card = t.preview(ctx(), tools.check_args(t, {"all": True}))
    assert card["blocked"].startswith("None of them can be approved here: “Summit sunrise”: connect YouTube again")


def test_one_post_that_cannot_change_never_stops_the_others(data):  # noqa: F811
    from clipfoundry import db

    a, b, c = _three(data)
    t = tool("cancel_post")
    card = t.preview(ctx(), {"all": True})
    db.update("scheduled_publications", b["id"], status="published")  # it went out meanwhile
    from clipfoundry.brain import tools

    done = t.run(ctx(), tools.check_args(t, card["args"], button=True))
    assert done.ok and "(2)" in done.text and "Could not: “Lake swim”" in done.text
    assert db.fetch("scheduled_publications", b["id"])["status"] == "published"


def test_clipforge_ai_shows_the_card_and_waits_even_when_it_acts_alone(data, monkeypatch):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.brain import assistant, operations, tools

    rows = _three(data)
    install(monkeypatch, say("", ("cancel_post", {"all": True})), ai_acts_alone=True,
            **{k: v for k, v in db.get_settings().items() if k.startswith("autopilot_")})
    out = assistant.think(db.get_settings(), "SYSTEM", [{"role": "user", "content": "cancel all my posts"}],
                          [tools.get("cancel_post")], tools.Ctx(ws=WS, deadline=time.monotonic() + 60),
                          said="cancel all my posts")
    assert out.pending[0]["state"] == "waiting" and out.pending[0]["label"] == "Don't post these 3 posts"
    assert {db.fetch("scheduled_publications", r["id"])["status"] for r in rows} != {"canceled"}
    assert "all: true for every post that fits" in tools.signature(tools.get("cancel_post"), True)
    assert operations.BULK_MAX >= 50

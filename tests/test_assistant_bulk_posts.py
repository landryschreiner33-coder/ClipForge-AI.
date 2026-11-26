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
    assert done.ok and done.text.startswith("Took them off the schedule (3): “Summit sunrise” (canceled), “Lake swim”")
    assert card["detail"][0].endswith(": waiting for your approval")  # each line says the state it is in
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
    assert card["ask"] is True  # …which still waits for the OK: it came from "all"
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


# ------------------------------------------------------------------ the review's findings (Nov 26)
def _card(name: str, args: dict) -> dict:
    from clipfoundry.brain import tools

    return tool(name).preview(ctx(), tools.check_args(tool(name), args))


def test_dates_and_times_narrow_them_exactly(data):  # noqa: F811
    import pytest

    from clipfoundry import db
    from clipfoundry.brain.tools import ToolError

    a, b, c = _three(data)
    tomorrow = dt.datetime.now(CHI).date() + dt.timedelta(days=1)
    four = tomorrow + dt.timedelta(days=3)
    for said in (tomorrow.strftime("%b %d"), tomorrow.strftime("%d %B"), tomorrow.isoformat(),
                 f"the {tomorrow.day}{'th' if 10 <= tomorrow.day % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(tomorrow.day % 10, 'th')}"):
        assert set(_card("cancel_post", {"all": True, "post": said})["args"]["posts"]) == {a["id"], b["id"]}, said
    assert _card("cancel_post", {"all": True, "post": four.strftime("%B %d")})["args"]["post"] == c["id"]
    assert _card("cancel_post", {"all": True, "post": "2 pm"})["args"]["post"] == b["id"]  # 14:00, not 12:00
    with pytest.raises(ToolError, match="There is no post"):
        _card("cancel_post", {"all": True, "post": "4:00"})  # never 14:00 by a part of its digits
    with pytest.raises(ToolError, match="could not read “28”"):
        _card("cancel_post", {"all": True, "post": "posts on 28"})  # never a post at 14:28 or on the 28th by chance
    db.update("scheduled_publications", c["id"], title="Top 10 trail tricks")
    assert _card("cancel_post", {"all": True, "post": "top 10"})["args"]["post"] == c["id"]  # a title's number
    with pytest.raises(ToolError, match="not a time of day"):
        _card("cancel_post", {"all": True, "post": "25:00"})


def test_status_words_keep_only_those_posts(data):  # noqa: F811
    from clipfoundry import db

    a, b, c = _three(data)
    db.update("scheduled_publications", a["id"], status="failed", last_error="upload timed out")
    db.update("scheduled_publications", b["id"], status="canceled")
    card = _card("retry_post", {"all": True, "post": "every failed post"})
    assert card["args"]["post"] == a["id"] and card["ask"] is True  # never the canceled one
    card = _card("retry_post", {"all": True})
    assert set(card["args"]["posts"]) == {a["id"], b["id"]}


def test_more_than_fifty_says_so_and_upcoming_posts_come_first(data, monkeypatch):  # noqa: F811
    from clipfoundry.brain import operations

    a, b, c = _three(data)
    monkeypatch.setattr(operations, "BULK_MAX", 2)
    card = _card("cancel_post", {"all": True})
    assert card["args"]["posts"] == [a["id"], b["id"]]  # the soonest
    assert "Only the first 2 of the 3 posts that fit" in " ".join(card["detail"])


def test_an_account_narrows_them_by_every_word_and_approve_takes_a_channel(data):  # noqa: F811
    import pytest

    from clipfoundry.brain import tools
    from clipfoundry.brain.tools import ToolError

    _three(data)
    with pytest.raises(ToolError, match="on that account"):
        _card("cancel_post", {"all": True, "account": "cooking channel"})  # "channel" alone is no match
    assert tools.check_args(tool("approve_post"), {"all": True, "channel": "fishing"})["channel"] == "fishing"
    with pytest.raises(ToolError, match="on that account"):
        _card("approve_post", {"all": True, "channel": "cooking"})
    assert "channel narrow it" in tools.signature(tool("approve_post"))


# ------------------------------------------------------------------ the second review's findings (Nov 26)
def _suffix(d: int) -> str:
    return "th" if 10 <= d % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")


def test_a_day_and_an_hour_said_together_are_read_apart(data):  # noqa: F811
    import pytest

    from clipfoundry.brain.tools import ToolError

    a, b, c = _three(data)
    t = dt.datetime.now(CHI).date() + dt.timedelta(days=1)
    for said in (f"{t.day} {t.strftime('%b')} 2 pm", f"{t.strftime('%b')} {t.day} 2 pm",
                 f"{t.day} {t.strftime('%B')} 14:00", f"{t.strftime('%b')} {t.day}, {t.year} at 2pm"):
        assert _card("cancel_post", {"all": True, "post": said})["args"]["post"] == b["id"], said
    assert set(_card("cancel_post", {"all": True, "post": f"{t.strftime('%b')} {t.day}, {t.year}"})["args"]["posts"]) \
        == {a["id"], b["id"]}
    for said in ("15 pm", "0 am"):
        with pytest.raises(ToolError, match="not a time of day"):
            _card("cancel_post", {"all": True, "post": said})
    assert _card("cancel_post", {"all": True, "post": "tomorrow morning"})["args"]["post"] == a["id"]
    assert _card("cancel_post", {"all": True, "post": "tomorrow afternoon"})["args"]["post"] == b["id"]


def test_month_letters_inside_a_title_word_are_no_month(data):  # noqa: F811
    import pytest

    from clipfoundry import db
    from clipfoundry.brain.tools import ToolError

    a, b, c = _three(data)
    db.update("scheduled_publications", c["id"], title="Novice 3 marketing tips")
    for said in ("marketing", "novice 3", "marketing tips"):
        assert _card("cancel_post", {"all": True, "post": said})["args"]["post"] == c["id"], said
    with pytest.raises(ToolError):  # a readable error, never a crash ("ſ" is no "s" here)
        _card("cancel_post", {"all": True, "post": "ſep 5"})


def test_a_day_just_gone_finds_the_posts_that_failed_on_it(data):  # noqa: F811
    from clipfoundry import db

    a, b, c = _three(data)
    gone = dt.datetime.now(CHI).date() - dt.timedelta(days=1)
    for row, hour in ((a, 10), (b, 14)):
        db.update("scheduled_publications", row["id"], status="failed", last_error="upload timed out",
                  planned_at=dt.datetime.combine(gone, dt.time(hour), CHI).timestamp())
    for said in ("yesterday", gone.strftime("%A").lower(), f"the {gone.day}{_suffix(gone.day)}",
                 f"{gone.strftime('%b')} {gone.day}"):
        assert set(_card("retry_post", {"all": True, "post": said})["args"]["posts"]) == {a["id"], b["id"]}, said


def test_one_post_on_a_channel_is_found_by_every_word_of_its_name(data, monkeypatch):  # noqa: F811
    import pytest

    from clipfoundry.brain import operations
    from clipfoundry.brain.tools import ToolError

    a, b, c = _three(data)
    names = {a["id"]: "Fishing channel", b["id"]: "Cooking show", c["id"]: "Cooking show"}
    monkeypatch.setattr(operations, "_account", lambda item: ("conn", names.get(item["id"], "x")))
    with pytest.raises(ToolError):  # "channel" alone never takes the Fishing channel's post
        _card("approve_post", {"post": "summit sunrise", "channel": "my cooking channel"})
    with pytest.raises(ToolError):
        operations.find_post({"post": "summit sunrise", "account": "cooking channel"}, operations.CANCELABLE,
                             "is planned")
    assert operations.find_post({"post": "summit sunrise", "account": "fishing"}, operations.CANCELABLE,
                                "is planned")["id"] == a["id"]


def test_approve_all_offers_the_posts_it_can_approve_first(data, monkeypatch):  # noqa: F811
    from clipfoundry.brain import operations

    a, b, c = _three(data)
    monkeypatch.setattr(operations, "BULK_MAX", 1)
    monkeypatch.setattr(operations, "_approve_problems", lambda r, s: ["TikTok posts wait for you"]
                        if r["id"] == a["id"] else [])
    card = _card("approve_post", {"all": True})
    assert not card["blocked"] and card["args"]["posts"] == [b["id"]]
    text = " ".join(card["detail"])
    assert "Only the first 1 of the 2 posts that fit" in text and "Left out: “Summit sunrise”: TikTok" in text

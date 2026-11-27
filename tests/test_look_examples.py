"""Example pictures of the looks of an animated short, made by the picture maker on this computer
(makers/look_examples.py): one job draws the same small scene in every look and keeps each as it comes; asking while
it runs starts nothing new; Stop keeps the ones already made; with no picture maker the page is told why, and a maker
that draws nothing fails the job with its reason. The picture maker is the fake of tests/test_studio_shorts_cast.py."""
from __future__ import annotations

from PIL import Image
from test_studio_shorts_cast import FakePictures, drawn  # noqa: F401
from test_studio_shorts_flow import _run, env  # noqa: F401


def test_every_look_gets_an_example_from_the_picture_maker(env, drawn):  # noqa: F811
    from clipfoundry.makers import look_examples
    from clipfoundry.makers.looks import LOOKS

    first = look_examples.start("local")
    assert first["can_make"] and first["job"]["status"] == "queued" and first["examples"] == {}
    again = look_examples.start("local")  # asked twice while it waits: still one job
    assert len(env["queued"]) == 1 and again["job"] == first["job"]
    done = _run(env, kinds=("look_examples",))
    assert done[0]["status"] == "done" and done[0]["result"]["made"] == [look.id for look in LOOKS]
    assert len(drawn.asked) == len(LOOKS)
    for look, asked in zip(LOOKS, drawn.asked):
        assert look_examples.IDEA in asked["prompt"] and asked["seed"] == look_examples.SEED
        assert look.prompt.split(",")[0] in asked["prompt"]  # each look's own style words
    view = look_examples.view()
    assert set(view["examples"]) == {look.id for look in LOOKS} and view["job"]["status"] == "done"
    with Image.open(look_examples.file("anime")) as im:
        assert im.size == look_examples.SIZE
    assert view["examples"]["anime"]["engine"] == "Fake pictures"
    assert view["examples"]["anime"]["url"].startswith("/api/studio/shorts/look-examples/anime?v=")
    look_examples.start("local")  # a new round once the last one finished
    assert len(env["queued"]) == 1


def test_stop_keeps_the_examples_already_made(env, drawn, monkeypatch):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.makers import look_examples

    look_examples.start("local")
    job_id = env["queued"][0]
    made = drawn.make_image

    def make_then_stop(prompt, **kw):
        path = made(prompt, **kw)
        if len(drawn.asked) == 2:
            look_examples.stop()  # the owner presses Stop while the second example is drawn
        return path

    monkeypatch.setattr(drawn, "make_image", make_then_stop)
    _run(env, kinds=("look_examples",))
    assert db.fetch("studio_jobs", job_id)["status"] == "canceled"
    assert set(look_examples.view()["examples"]) == {"cartoon3d"}  # the second was drawn after Stop: not kept


def test_no_picture_maker_says_why_and_a_maker_that_draws_nothing_fails_with_its_reason(env, drawn,
                                                                                         monkeypatch):  # noqa: F811
    import pytest

    from clipfoundry import db
    from clipfoundry.makers import look_examples

    monkeypatch.setattr(drawn, "status", lambda role: {"ready": False, "engine": "", "why": "Not installed.",
                                                       "model": ""})
    view = look_examples.view()
    assert not view["can_make"] and view["why"] == "Not installed."
    with pytest.raises(look_examples.ExampleError):
        look_examples.start("local")
    assert env["queued"] == []

    monkeypatch.setattr(drawn, "status", FakePictures.status.__get__(drawn))
    monkeypatch.setattr(drawn, "make_image", lambda prompt, **kw: drawn.tmp / "nothing.png")
    look_examples.start("local")
    job = _run(env, kinds=("look_examples",))[0]
    assert job["status"] == "failed" and "no picture" in job["error"]
    assert look_examples.view()["examples"] == {}


def test_the_page_reads_and_makes_examples_through_the_api(env, drawn):  # noqa: F811
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    c = TestClient(app)
    assert c.get("/api/studio/shorts/look-examples/anime").status_code == 404
    assert c.post("/api/studio/shorts/look-examples").json()["job"]["status"] == "queued"
    _run(env, kinds=("look_examples",))
    got = c.get("/api/studio/shorts/look-examples").json()
    assert len(got["examples"]) == 8
    pic = c.get(got["examples"]["comic"]["url"])
    assert pic.status_code == 200 and pic.headers["content-type"] == "image/jpeg"
    assert c.post("/api/studio/shorts/look-examples/stop").json()["job"]["status"] == "done"

"""ClipForge AI reads how the owner's posts did (brain/insights.py): totals as Publishing → Results counts them, the
best and weakest posts read fairly at 48 hours, comparisons by format, what it learned from the results, YouTube only
with Google's approval for derived metrics; the ready-made helpers get the tools their jobs need. All posts here are
synthetic and live in a temporary test database."""
from __future__ import annotations

import time

import pytest

DAY = 86400


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def post(platform: str, views: float | None, title: str, *, layout: str = "split", days_ago: float = 5,
         project: str = "Stream night", pct: float | None = None, likes: int | None = None,
         intent: str = "SELECTED_AUDIENCE", read_after_h: float = 49) -> dict:
    from clipfoundry import db

    p = db.create_project(project, status="ready")
    clip = db.create_clip(p["id"], start=0, end=30, title=title, status="ready", duration=30,
                          render_info={"layout": layout})
    pub = db.create_publication(clip["id"], platform, status="done", remote_id=f"v{time.time_ns()}", title=title,
                                audience={"intent": intent, "group_version": 1, "policy_version": 1})
    made = time.time() - days_ago * DAY
    db.execute("UPDATE publications SET created_at = ? WHERE id = ?", (made, pub["id"]))
    if views is not None:
        db.execute("INSERT INTO performance (id, publication_id, clip_id, platform, fetched_at, views, likes, "
                   "avg_view_percentage) VALUES (?,?,?,?,?,?,?,?)",
                   (db.new_id(), pub["id"], clip["id"], platform, made + read_after_h * 3600, views, likes, pct))
    return db.get_publication(pub["id"])


def run(args: dict | None = None):
    from clipfoundry.brain import tools

    t = tools.get("results")
    return t.run(tools.Ctx(ws="local"), tools.check_args(t, args or {}))


def test_results_list_totals_and_the_best_and_weakest_posts_read_fairly(data):
    for k, views in enumerate([5400, 120, 900, 3100, 40, 700, 260, 1500]):
        post("tiktok", views, f"Clip number {k}", likes=views // 10, pct=30 + k)
    post("tiktok", 99999, "Brand new clip", days_ago=0.5, read_after_h=6)  # under 48 hours: not ranked
    res = run()
    text = res.text
    assert res.ok and res.summary == "Read your results (9 posts)"
    assert "TikTok: 9 post(s), 9 with numbers" in text and "112,019 views" in text
    best = text.split("Best posts")[1].split("Weakest:")[0]
    assert "1. “Clip number 0” (from “Stream night”) on TikTok: 5,400 views at 48 hours, 30% watched" in best
    assert "Brand new clip" not in text.split("Best posts")[1]  # a reading at 6 hours is never ranked
    weak = text.split("Weakest:")[1]
    assert "“Clip number 4”" in weak and "40 views" in weak and "“Clip number 1”" in weak
    assert "1 post(s) are under 48 hours old: too new to compare yet." in text
    assert "not a promise of views" in text
    assert {"label": "Publishing → Results", "href": "#/publishing/results"} in res.data["links"]


def test_youtube_numbers_wait_for_googles_approval_and_the_owners_own_views_never_count(data):
    from clipfoundry import db

    post("youtube", 8000, "Big YouTube short")
    post("tiktok", 300, "Seen by me only", intent="OWNER_ONLY")
    text = run().text
    assert "YouTube: 1 post(s); their numbers are not used here" in text and "8,000" not in text
    assert "Best posts" not in text  # only the owner saw the TikTok post: nothing to rank
    db.save_settings({"youtube_derived_metrics_approved": True})
    text = run({"platform": "youtube"}).text
    assert "8,000 views at 48 hours" in text and "TikTok" not in text


def test_results_narrow_to_a_period_and_to_words(data):
    post("tiktok", 500, "Old clutch", days_ago=60, project="Old stream")
    post("tiktok", 800, "Fresh clutch", days_ago=3, project="New stream")
    assert "Old clutch" not in run().text and "Fresh clutch" in run().text
    assert "Old clutch" in run({"period": "90"}).text
    only = run({"period": "all", "words": "old stream"}).text
    assert "Old clutch" in only and "Fresh clutch" not in only
    assert "No post from ClipForge went out in that time that matches those words" in run({"words": "kayak"}).text


def test_results_compare_by_format_and_list_what_was_learned(data):
    from clipfoundry.brain import lessons, memories

    for k in range(6):
        post("tiktok", 900 + 40 * k, f"Pip {k}", layout="pip")
        post("tiktok", 100 + 10 * k, f"Split {k}", layout="split")
    memories.remember("local", "From your results: look for a big reaction. Clips with it were watched 12 points "
                      "further.", kind="fact", source="did", tags=[lessons.TAG, "clip picking"])
    text = run({"by": "format"}).text
    assert "By format on TikTok (your selected viewers):" in text
    assert "- Picture-in-picture (6 posts): Higher so far" in text and "Next:" in text
    assert "What ClipForge learned from your results" in text and "look for a big reaction" in text


def test_no_posts_yet_says_so(data):
    res = run()
    assert res.ok and "No post from ClipForge went out in that time" in res.text


def test_without_a_model_how_are_my_clips_doing_reads_the_results(data):
    from clipfoundry.brain import chat

    post("tiktok", 2500, "Rage quit")
    c = chat.open_chat("local")
    for said in ("How are my clips doing?", "show me my results", "which clip did best?", "how did my posts do"):
        out = chat.send("local", c["id"], said)
        assert "“Rage quit”" in out["ai"]["text"] and out["ai"]["data"]["tool"] == "results", said
    out = chat.send("local", c["id"], "How do I make my clips better?")
    assert out["ai"]["data"].get("tool") != "results"


def test_the_ready_made_helpers_have_the_tools_their_jobs_need(data):
    from clipfoundry.brain import agents

    tools = {t["template"]: set(t["tools"]) for t in agents.TEMPLATES}
    assert {"results", "posts"} <= tools["growth_coach"] and "clip" in tools["hook_writer"]
    assert "clip" in tools["thumbnail_designer"] and "clip" in tools["editor"] and "results" in tools["researcher"]
    allowed = {t["name"] for t in agents.agent_tools()}
    for name, have in tools.items():
        assert have <= allowed, name  # every one can really be given to a helper
    coach = agents.add("local", template="growth_coach")
    assert set(coach["tools"]) == tools["growth_coach"]


def test_helpers_added_before_get_the_new_tools_unless_the_owner_changed_them(data):
    from clipfoundry import db
    from clipfoundry.brain import agents

    coach = agents.add("local", template="growth_coach")
    hooks = agents.add("local", template="hook_writer")
    critic = agents.add("local", template="critic")
    old = agents.EARLIER
    db.update("brain_agents", coach["id"], tools=old["growth_coach"]["tools"],
              instructions=old["growth_coach"]["instructions"])
    db.update("brain_agents", hooks["id"], tools=old["hook_writer"]["tools"], instructions="My own way of working.")
    db.update("brain_agents", critic["id"], tools=["knowhow"])  # the owner chose this
    agents._upgraded.clear()
    got = {a["template"]: a for a in agents.list_("local")}
    assert set(got["growth_coach"]["tools"]) == set(agents.BY_TEMPLATE["growth_coach"]["tools"])
    assert got["growth_coach"]["instructions"].startswith("Read the owner's results first")
    assert "clip" in got["hook_writer"]["tools"] and got["hook_writer"]["instructions"] == "My own way of working."
    assert got["critic"]["tools"] == ["knowhow"]

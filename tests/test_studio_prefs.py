"""Robot names (CF-13) and synced appearance/layout preferences (CF-14), backend side."""
from __future__ import annotations

import pytest

from cloud_support import ORIGIN, OWNER, SECOND, cloud_env, sign_in


@pytest.fixture()
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


def test_rename_editor_to_nova_keeps_every_real_id(api):
    from clipfoundry.office import roles

    before = {r["id"]: (r["manager"], r.get("kinds"), r["department"]) for r in roles.ROLES}
    editor = next(r for r in roles.ROLES if r["title"] == "Video Editor")
    r = api.put(f"/api/robots/names/{editor['id']}", json={"name": "  Nova  "})
    assert r.status_code == 200
    assert r.json() == {"role_id": editor["id"], "default_name": editor["name"], "role": "Video Editor",
                        "display_name": "Nova", "custom": True}
    assert {r["id"]: (r["manager"], r.get("kinds"), r["department"]) for r in roles.ROLES} == before
    names = api.get("/api/robots/names").json()
    assert names[editor["id"]]["display_name"] == "Nova" and len(names) == len(roles.ROLES) + 1  # and CORE
    assert api.delete(f"/api/robots/names/{editor['id']}").json()["display_name"] == editor["name"]


def test_every_robot_including_core_can_be_renamed_and_all_reset_with_confirmation(api):
    from clipfoundry.office import roles, view

    ids = [r["id"] for r in roles.ROLES] + ["core"]
    for n, rid in enumerate(ids):
        assert api.put(f"/api/robots/names/{rid}", json={"name": f"Robot {n} ✨"}).status_code == 200, rid
    names = api.get("/api/robots/names").json()
    assert names["core"] == {"role_id": "core", "default_name": "CORE", "role": "Brain Core",
                             "display_name": f"Robot {len(ids) - 1} ✨", "custom": True}
    assert all(names[rid]["custom"] for rid in ids)
    # a name is display only: work still goes to the same role ids
    assert roles.role_for("video_render") == "check" and {r["id"] for r in view.role_states({})} == set(roles.BY_ID)
    assert api.post("/api/robots/names/reset", json={}).status_code == 422  # not confirmed: nothing changes
    assert api.get("/api/robots/names").json()["core"]["custom"]
    after = api.post("/api/robots/names/reset", json={"confirm": True}).json()
    assert not any(v["custom"] for v in after.values()) and after["core"]["display_name"] == "CORE"


def test_robot_names_accept_unicode_reject_blank_and_never_become_markup(api):
    rid = "command"
    assert api.put(f"/api/robots/names/{rid}", json={"name": "Ñandú 🤖"}).json()["display_name"] == "Ñandú 🤖"
    assert api.put(f"/api/robots/names/{rid}", json={"name": "   "}).status_code == 422
    assert api.put(f"/api/robots/names/{rid}", json={"name": "x" * 33}).status_code == 422
    assert api.put(f"/api/robots/names/{rid}", json={"name": "a‮b"}).status_code == 422  # bidi override
    tag = api.put(f"/api/robots/names/{rid}", json={"name": "<img src=x onerror=alert(1)>"})
    assert tag.status_code == 422 or tag.json()["display_name"] == "<img src=x onerror=alert(1)>"[:32]
    assert api.put("/api/robots/names/not-a-robot", json={"name": "Nova"}).status_code == 422
    # duplicates are allowed; the role keeps them apart
    api.put("/api/robots/names/tracker", json={"name": "Nova"})
    api.put("/api/robots/names/vector", json={"name": "Nova"})
    names = api.get("/api/robots/names").json()
    assert names["tracker"]["role"] != names["vector"]["role"]


def test_appearance_and_layouts_persist_per_device_with_conflicts_and_reset(api):
    a = api.get("/api/preferences/appearance").json()
    assert a["value"]["palette"] == "studio" and a["value"]["clips_mode"] == "highlights" and a["revision"] == 0
    assert "theme" not in a["value"] and a["schema_version"] == 2  # dark only
    saved = api.put("/api/preferences/appearance", json={"value": {"palette": "graphite", "accent": "teal",
                                                                   "density": "compact", "text_size": "large",
                                                                   "office_size": "compact", "motion": "reduced"},
                                                         "revision": 0}).json()
    assert saved["revision"] == 1 and saved["value"]["accent"] == "teal" and saved["value"]["text_size"] == "large"
    stale = api.put("/api/preferences/appearance", json={"value": {"accent": "pink"}, "revision": 0})
    assert stale.status_code == 409  # another device saved first: no silent overwrite
    for bad in ({"palette": "light"}, {"theme": "neon"}, {"text_size": "huge"}, {"office_size": 3}):
        assert api.put("/api/preferences/appearance", json={"value": bad}).status_code == 422, bad
    desk = api.get("/api/preferences/layout/desktop").json()
    assert [p["id"] for p in desk["value"]["screens"]["studio"]] == ["needs_you", "pinned", "current", "office",
                                                                    "recent", "publishing"]
    assert all("size" not in p for p in desk["value"]["screens"]["studio"])  # a stacked page has no widths
    panels = desk["value"]["screens"]["review"]
    panels.reverse()
    panels[0]["size"] = 0.5
    panels[1]["visible"] = False
    r = api.put("/api/preferences/layout/desktop", json={"value": desk["value"], "revision": desk["revision"]})
    assert r.status_code == 200, r.text
    phone = api.get("/api/preferences/layout/phone").json()
    assert all("size" not in p for p in phone["value"]["screens"]["review"])  # never desktop sizes on a phone
    hidden = {"screens": {"studio": [{"id": p, "visible": False} for p in ("needs_you", "pinned", "current",
                                                                             "office", "recent", "publishing")]}}
    bad = api.put("/api/preferences/layout/desktop", json={"value": hidden})
    assert bad.status_code == 422 and "at least one panel" in bad.json()["detail"]
    old_screen = {"screens": {"office": [{"id": p, "visible": True} for p in ("map", "team", "activity")]}}
    assert api.put("/api/preferences/layout/desktop", json={"value": old_screen}).status_code == 422
    api.put("/api/robots/names/command", json={"name": "Boss"})
    api.post("/api/studio/styles", json={"name": "Keep me", "values": {"feel": "calm"}})
    reset = api.delete("/api/preferences/layout/desktop").json()
    assert reset["default"] and reset["value"]["screens"]["review"][0]["id"] == "preview"
    assert api.get("/api/robots/names").json()["command"]["display_name"] == "Boss"  # reset touched layouts only
    assert [s["name"] for s in api.get("/api/studio/styles").json()] == ["Keep me"]
    assert api.get("/api/preferences/appearance").json()["value"]["accent"] == "teal"


def test_a_saved_light_or_system_theme_becomes_dark_and_keeps_every_other_choice(api):
    import json

    from clipfoundry import db
    from clipfoundry.cloud.principal import LOCAL_OWNER as me

    for theme in ("light", "system"):
        db.execute("DELETE FROM preferences")
        db.execute("INSERT INTO preferences (workspace_id, user_id, pref_key, schema_version, value, revision, "
                   "updated_at) VALUES (?, ?, 'appearance', 1, ?, 4, 0)",
                   (me.workspace_id, me.user_id, json.dumps({"theme": theme, "accent": "coral",
                                                             "density": "compact", "clips_mode": "full_stories"})))
        got = api.get("/api/preferences/appearance").json()
        assert "theme" not in got["value"] and got["value"]["palette"] == "studio"
        assert (got["value"]["accent"], got["value"]["density"], got["value"]["clips_mode"]) == \
            ("coral", "compact", "full_stories")
        # a page loaded before the update may still send its theme: it is accepted and changes nothing
        r = api.put("/api/preferences/appearance", json={"value": {"theme": "light"}, "revision": 4}).json()
        assert "theme" not in r["value"] and r["value"]["accent"] == "coral"


def test_pinned_projects_are_checked_and_an_older_editor_layout_is_kept(api):
    pins = api.put("/api/preferences/appearance", json={"value": {"pinned": ["abc123", "abc123", "x-1"]}}).json()
    assert pins["value"]["pinned"] == ["abc123", "x-1"]  # each once, in order
    assert api.put("/api/preferences/appearance", json={"value": {"pinned": ["../etc"]}}).status_code == 422
    too_many = [f"p{i}" for i in range(13)]
    assert api.put("/api/preferences/appearance", json={"value": {"pinned": too_many}}).status_code == 422
    import json

    from clipfoundry import db
    from clipfoundry.cloud.principal import LOCAL_OWNER as me

    old ={"screens": {"create": [{"id": p, "visible": True, "size": 0.25}
                                  for p in ("intake", "style", "destinations", "summary")],
                       "review": [{"id": "guidance", "visible": True, "size": 0.4},
                                  {"id": "preview", "visible": True, "size": 0.2},
                                  {"id": "outputs", "visible": False, "size": 0.2},
                                  {"id": "transcript", "visible": True, "size": 0.2}],
                       "office": [{"id": p, "visible": True, "size": 0.333} for p in ("map", "team", "activity")]}}
    db.execute("INSERT INTO preferences (workspace_id, user_id, pref_key, schema_version, value, revision, "
               "updated_at) VALUES (?, ?, 'layout:desktop', 1, ?, 2, 0)", (me.workspace_id, me.user_id,
                                                                            json.dumps(old)))
    got = api.get("/api/preferences/layout/desktop").json()
    assert not got["default"]
    assert [p["id"] for p in got["value"]["screens"]["review"]] == ["guidance", "preview", "outputs", "transcript"]
    assert got["value"]["screens"]["review"][2]["visible"] is False and set(got["value"]["screens"]) == \
        {"studio", "review"}
    assert got["revision"] == 2  # the next save replaces the old row instead of being refused as a conflict


def test_names_and_preferences_sync_across_devices_and_stay_in_their_workspace(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    idp = cloud_env(monkeypatch, tmp_path)
    with TestClient(app, base_url=ORIGIN) as desk, TestClient(app, base_url=ORIGIN) as phone, \
            TestClient(app, base_url=ORIGIN) as other:
        sign_in(desk, idp, OWNER)
        sign_in(phone, idp, OWNER)
        sign_in(other, idp, SECOND)
        desk.put("/api/robots/names/frame", json={"name": "Nova"})
        desk.put("/api/preferences/appearance", json={"value": {"accent": "teal"}})
        assert phone.get("/api/robots/names").json()["frame"]["display_name"] == "Nova"  # the other device
        assert phone.get("/api/preferences/appearance").json()["value"]["accent"] == "teal"
        assert other.get("/api/robots/names").json()["frame"]["display_name"] == "FRAME"
        assert other.get("/api/preferences/appearance").json()["value"]["accent"] == "violet"
        other.put("/api/robots/names/frame", json={"name": "Theirs"})
        reset = other.post("/api/robots/names/reset", json={"confirm": True})
        assert reset.status_code == 200, reset.text
        assert desk.get("/api/robots/names").json()["frame"]["display_name"] == "Nova"  # only their own names reset
    from clipfoundry.cloud import settings as cloud_settings

    cloud_settings.reset()

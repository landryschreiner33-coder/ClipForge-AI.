"""The Brain map (handoff section 6): every style, skill and example video, linked only by recorded facts.

A project links to a style, skill, example or note only when its guidance snapshot recorded applying it; an Example
style links to the example video it was learned from; nothing crosses workspaces; "just used" is a snapshot made in
the last 15 minutes, never a decoration.
"""
from __future__ import annotations

import io
import time

import pytest

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


def _skill(api, name: str, text: str) -> dict:
    r = api.post("/api/studio/skills", files={"file": (name, io.BytesIO(text.encode()), "text/markdown")})
    assert r.status_code == 200, r.text
    api.patch(f"/api/studio/skills/{r.json()['id']}", json={"enabled": True})
    return r.json()


def _snapshot(api, mode: str, **kw) -> dict:
    r = api.post("/api/studio/guidance/preview", json={"mode": mode, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_links_come_only_from_recorded_use_and_provenance(api, tmp_path):
    from clipfoundry import db
    from clipfoundry.studio import styles

    style = api.post("/api/studio/styles", json={"name": "Top captions", "values": {"caption_position": "top"},
                                                 "modes": ["highlights"]}).json()
    unused = api.post("/api/studio/styles", json={"name": "Never used", "values": {"caption_position": "middle"},
                                                  "modes": ["highlights"]}).json()
    skill = _skill(api, "bold.md", "- Use bold captions.")
    note = api.post("/api/brain/knowledge", headers=H, json={
        "kind": "instruction", "title": "Lower third", "content": "", "preferences": {"caption_position": "bottom"}}
    ).json()
    clip = tmp_path / "ex.mp4"
    clip.write_bytes(b"x")
    asset = db.insert("assets", {"workspace_id": "local", "kind": "video", "filename": "ex.mp4", "sha256": "e1",
                                 "size": 1, "path": str(clip), "probe": {"duration": 30}})
    example = db.insert("reference_videos", {"workspace_id": "local", "asset_id": asset["id"], "title": "Fast edit",
                                             "status": "ready", "analysis_revision": 1})
    learned = styles.create("local", "Fast edit style", {"caption_style": "bold"}, ["highlights"], source="example",
                            reference_id=example["id"], provenance={"title": "Fast edit", "analysis_revision": 1})
    db.update("reference_videos", example["id"], style_id=learned["id"])

    # a clips project made with the style chosen: the snapshot records the style, the skill and (not) the note
    snap = _snapshot(api, "highlights", style_id=style["id"])
    p = db.create_project("Interview clips", status="ready")
    db.update_project(p["id"], guidance=snap, workspace_id="local")
    # an older snapshot without its "used" list still links through its decisions
    old = {"mode": "full_video", "created_at": time.time() - 3 * 86400, "decisions": [
        {"field": "caption_position", "value": "bottom", "from": {"level": "brain", "id": note["id"], "revision": 1,
                                                                   "name": "Lower third"}},
        {"field": "aspect", "value": "16:9", "from": {"level": "settings", "id": "", "revision": 0,
                                                       "name": "Settings"}}]}
    v = db.insert("studio_projects", {"workspace_id": "local", "name": "Lake trip", "guidance": old})
    # another workspace's project and style never appear
    other_style = styles.create("elsewhere", "Theirs", {"caption_position": "top"}, ["highlights"])
    db.insert("studio_projects", {"workspace_id": "elsewhere", "name": "Not mine",
                                  "guidance": {**snap, "used": [{"level": "style", "id": other_style["id"],
                                                                 "revision": 1, "name": "Theirs",
                                                                 "fields": ["caption_position"]}]}})

    m = api.get("/api/studio/brain/map").json()
    assert {s["name"] for s in m["styles"]} == {"Top captions", "Never used", "Fast edit style"}
    assert [s["name"] for s in m["skills"]] == [skill["name"]] and m["skills"][0]["enabled"]
    assert [e["title"] for e in m["examples"]] == ["Fast edit"] and m["examples"][0]["style_id"] == learned["id"]
    assert next(s for s in m["styles"] if s["id"] == learned["id"])["reference_id"] == example["id"]
    by_project = {x["id"]: x for x in m["projects"]}
    assert set(by_project) == {p["id"], v["id"]}  # "Not mine" is in another workspace
    used = {link["node"]: link for link in by_project[p["id"]]["links"]}
    assert used[f"style:{style['id']}"]["fields"] == ["Caption position"]
    assert f"skill:{skill['id']}" in used and f"style:{unused['id']}" not in used
    assert f"note:{note['id']}" not in used  # overridden by the style, so the note did not decide anything
    assert by_project[p["id"]]["href"] == f"#/project/{p['id']}"
    older = {link["node"] for link in by_project[v["id"]]["links"]}
    assert f"note:{note['id']}" in older and by_project[v["id"]]["href"] == f"#/video/{v['id']}"
    # "just used" is only what a snapshot recorded in the last 15 minutes
    recent = {a["node"] for a in m["applied"]}
    assert f"style:{style['id']}" in recent and f"note:{note['id']}" not in recent


def test_an_example_chosen_for_a_project_links_to_the_video_or_its_kept_style(api, tmp_path):
    from clipfoundry import db
    from clipfoundry.studio import brain_map, styles

    clip = tmp_path / "ex.mp4"
    clip.write_bytes(b"x")
    asset = db.insert("assets", {"workspace_id": "local", "kind": "video", "filename": "ex.mp4", "sha256": "e2",
                                 "size": 1, "path": str(clip), "probe": {"duration": 30}})
    example = db.insert("reference_videos", {"workspace_id": "local", "asset_id": asset["id"], "title": "Calm talk",
                                             "status": "ready", "analysis_revision": 1})
    learned = styles.create("local", "Calm talk style", {"caption_position": "middle"}, ["highlights"],
                            source="example", reference_id=example["id"])
    entry = {"level": "reference", "id": example["id"], "revision": 1, "name": "Example “Calm talk”",
             "style_id": learned["id"], "fields": ["caption_position"]}
    p = db.create_project("Talk clips", status="ready")
    db.update_project(p["id"], guidance={"mode": "highlights", "created_at": time.time() - 3600, "used": [entry]},
                      workspace_id="local")
    m = brain_map.build("local")
    assert m["projects"][0]["links"][0]["node"] == f"example:{example['id']}" and not m["applied"]
    db.execute("DELETE FROM reference_videos WHERE id = ?", (example["id"],))  # deleted, style kept
    m = brain_map.build("local")
    assert m["projects"][0]["links"][0]["node"] == f"style:{learned['id']}"
    assert m["examples"] == []

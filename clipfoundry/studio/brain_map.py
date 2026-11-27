"""The Brain map (handoff section 6): every saved style, skill and example video in a workspace, and the projects
whose recorded guidance used them.

Every link is a recorded fact, never an inferred one:
- "used in" comes from a project's guidance snapshot (`guidance.resolve` records each entry it applied, with its
  revision and the fields it decided);
- "learned from" comes from an Example style's link to the example video it was saved from.

Brain notes and their clip evidence come from the knowledge API, which the screen already reads; this map adds the
projects that used a note (snapshot entries of level "brain"). Nothing here is written: it is a read model.
"""
from __future__ import annotations

import time

from .. import db
from . import capabilities, skills, styles

RECENT_S = 15 * 60       # "just used": a snapshot recorded in the last 15 minutes
MAX_PROJECTS = 200       # the newest projects with recorded guidance; older ones are counted, not listed
_LEVEL = {"style": "style", "skill": "skill", "project_skill": "skill", "reference": "example", "example": "example",
          "brain": "note"}


def _used(snapshot: dict) -> list[dict]:
    """The entries a snapshot applied: its `used` list, or, for snapshots recorded before that list existed, the
    winners of its decisions."""
    if not isinstance(snapshot, dict):
        return []
    if isinstance(snapshot.get("used"), list):
        return [u for u in snapshot["used"] if isinstance(u, dict) and u.get("id")]
    out: dict[tuple, dict] = {}
    for d in snapshot.get("decisions") or []:
        e = (d or {}).get("from") or {}
        if e.get("level") in _LEVEL and e.get("id"):
            out.setdefault((e["level"], e["id"]), {**e, "fields": []})["fields"].append(d.get("field"))
    return list(out.values())


def _node(entry: dict, examples: dict[str, dict], style_ids: set[str]) -> str:
    """The map node an applied entry stands for. An example's entry names the example video, or the Example style
    itself when the video was deleted and the style kept."""
    kind = _LEVEL[entry["level"]]
    if kind == "example":
        if entry["id"] in examples:
            return f"example:{entry['id']}"
        sid = entry.get("style_id") or entry["id"]
        return f"style:{sid}" if sid in style_ids else f"example:{entry['id']}"
    return f"{kind}:{entry['id']}"


def build(workspace_id: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    style_rows = db.select("styles", "workspace_id = ?", (workspace_id,), "updated_at DESC", 500)
    skill_rows = db.select("skills", "workspace_id = ?", (workspace_id,), "updated_at DESC", 500)
    example_rows = db.select("reference_videos", "workspace_id = ? AND project_only = 0", (workspace_id,),
                             "updated_at DESC", 500)
    examples = {r["id"]: r for r in example_rows}
    style_ids = {r["id"] for r in style_rows}

    projects: list[dict] = []
    for p in db.list_projects():
        if (p.get("workspace_id") or "local") == workspace_id and p.get("guidance"):
            projects.append({"id": p["id"], "kind": "clips", "name": p["name"], "href": f"#/project/{p['id']}",
                             "snapshot": p["guidance"], "created_at": p["created_at"]})
    for v in db.select("studio_projects", "workspace_id = ?", (workspace_id,), "created_at DESC", 2000):
        if v.get("guidance"):
            projects.append({"id": v["id"], "kind": "full_video", "name": v["name"], "href": f"#/video/{v['id']}",
                             "snapshot": v["guidance"], "created_at": v["created_at"]})
    listed = []
    applied: dict[str, dict] = {}
    for p in sorted(projects, key=lambda x: -x["created_at"]):
        used = _used(p["snapshot"])
        if not used:
            continue
        at = float(p["snapshot"].get("created_at") or p["created_at"])
        links = []
        for u in used:
            if u.get("level") not in _LEVEL:
                continue
            node = _node(u, examples, style_ids)
            links.append({"node": node, "revision": u.get("revision"), "name": str(u.get("name") or "")[:120],
                          "fields": [capabilities.FIELDS[f].label if f in capabilities.FIELDS else str(f)
                                     for f in (u.get("fields") or [])]})
            if now - at <= RECENT_S and (node not in applied or applied[node]["at"] < at):
                applied[node] = {"node": node, "at": at, "project": p["name"]}
        if links and len(listed) < MAX_PROJECTS:
            listed.append({"id": p["id"], "kind": p["kind"], "name": p["name"], "href": p["href"], "at": at,
                           "mode": p["snapshot"].get("mode") or "", "links": links})
    used_count = sum(1 for p in projects if _used(p["snapshot"]))

    def example_view(r: dict) -> dict:
        return {"id": r["id"], "title": r["title"], "status": r["status"], "enabled": bool(r["enabled"]),
                "avoid": bool(r["avoid"]), "scope": r["scope"], "modes": r.get("modes") or [],
                "likes": r.get("likes") or [], "note": (r.get("note") or "")[:600],
                "analysis_revision": r["analysis_revision"], "style_id": r.get("style_id") or "",
                "updated_at": r["updated_at"]}

    return {
        "styles": [styles.view(r) for r in style_rows],
        "skills": [{k: v for k, v in skills.view(r).items() if k not in ("unsupported", "blocked")}
                   for r in skill_rows],
        "examples": [example_view(r) for r in example_rows],
        "projects": listed,
        "omitted_projects": max(0, used_count - len(listed)),
        "applied": sorted(applied.values(), key=lambda a: -a["at"]),
        "recent_seconds": RECENT_S,
    }

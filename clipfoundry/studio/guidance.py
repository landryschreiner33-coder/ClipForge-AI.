"""Resolve the editing guidance for one project into a recorded snapshot.

Precedence, highest first (deterministic):
1. the project's explicit choices (the brief and the Customize controls);
2. the style chosen for this project;
3. skills: the ones switched on for this project, then the ones enabled for every project;
4. enabled Brain notes whose topic matches the source (the existing saved guidance);
5. Settings.
When two entries of the same level disagree about one field, neither is applied: the next level decides and the
conflict is shown, so an unrelated rule is never picked silently. The snapshot records every entry's ID and revision,
what it decided, what it overrode and why, so a retry or a later render reproduces the same plan and the review
screen can say exactly what was "Used from your Brain". Changing a style, skill or note later affects only new plans.
"""
from __future__ import annotations

import time

from .. import db
from . import capabilities

SCHEMA = 1


def _entry(level: str, ident: str, revision, name: str) -> dict:
    return {"level": level, "id": ident, "revision": revision, "name": name}


def _brain_candidates(mode: str, context: dict, settings: dict) -> list[tuple[dict, dict]]:
    """Enabled Brain notes that match this source, with their supported preferences for `mode`."""
    from ..autopilot import knowledge

    fields = capabilities.for_mode(mode)
    out = []
    for row, compiled in knowledge.matching(context, settings):
        prefs = {k: v for k, v in (compiled.get("preferences") or {}).items() if k in fields}
        if prefs:
            out.append((_entry("brain", row["id"], row["revision"], row["title"]), prefs))
    return out


def resolve(mode: str, *, project_choices: dict | None = None, style: dict | None = None,
            project_skills: list[dict] | None = None, global_skills: list[dict] | None = None,
            settings: dict | None = None, context: dict | None = None) -> dict:
    """The guidance snapshot for a new plan. `style` and skills are database rows (styles / skills tables)."""
    if mode not in capabilities.MODES:
        raise ValueError(f"Unknown mode {mode}")
    settings = settings if settings is not None else db.get_settings()
    fields = capabilities.for_mode(mode)
    chosen, problems = capabilities.clean(project_choices or {}, (mode,))  # unknown choices are reported
    levels: list[tuple[str, list[tuple[dict, dict]]]] = [
        ("project", [(_entry("project", "", 0, "This project's choices"), chosen)] if chosen else []),
        ("style", [(_entry("style", style["id"], style["revision"], style["name"]),
                    {k: v for k, v in (style.get("values_json") or {}).items() if k in fields})] if style else []),
        ("project_skill", [(_entry("skill", s["id"], s["revision"], s["name"]),
                            {k: v for k, v in (s.get("supported") or {}).items() if k in fields})
                           for s in project_skills or [] if mode in (s.get("modes") or capabilities.MODES)]),
        ("skill", [(_entry("skill", s["id"], s["revision"], s["name"]),
                    {k: v for k, v in (s.get("supported") or {}).items() if k in fields})
                   for s in global_skills or [] if mode in (s.get("modes") or capabilities.MODES)]),
        ("brain", _brain_candidates(mode, context or {}, settings)),
    ]
    values: dict = {}
    decisions: dict[str, dict] = {}
    conflicts: list[dict] = []
    for field in fields:
        winner = None
        passed_over: list[dict] = []
        for level, entries in levels:
            offers = [(e, prefs[field]) for e, prefs in entries if field in prefs]
            if not offers:
                continue
            distinct = {repr(v) for _, v in offers}
            if len(distinct) > 1:
                conflicts.append({"field": field, "label": fields[field].label, "level": level,
                                  "entries": [{**e, "value": v} for e, v in offers],
                                  "resolution": "Not applied: these disagree. The next level decides; choose a value "
                                                "in this project to settle it."})
                passed_over += [{**e, "value": v, "reason": "conflicts with another entry of the same level"}
                                for e, v in offers]
                continue
            if winner is None:
                winner = (offers[0][0], offers[0][1], [e for e, _ in offers])
            else:
                passed_over += [{**e, "value": v, "reason": f"overridden by {winner[0]['name']}"} for e, v in offers]
        if winner is not None:
            entry, value, sharing = winner
            values[field] = value
            decisions[field] = {"field": field, "value": value, "text": fields[field].describe(value),
                                "from": entry, "also": sharing[1:], "overridden": passed_over}
        elif field in settings:
            values[field] = settings[field]
            decisions[field] = {"field": field, "value": settings[field], "text": fields[field].describe(
                settings[field]) if fields[field].kind != "text" else "", "from": _entry("settings", "", 0,
                                                                                         "Settings"),
                                "also": [], "overridden": passed_over}
    used = {}
    for d in decisions.values():
        e = d["from"]
        if e["level"] in ("style", "skill", "brain"):
            used.setdefault((e["level"], e["id"]), {**e, "fields": []})["fields"].append(d["field"])
    return {"schema": SCHEMA, "mode": mode, "created_at": time.time(), "values": values,
            "decisions": list(decisions.values()), "conflicts": conflicts, "problems": problems,
            "used": list(used.values()),
            "entries": [e for _, entries in levels for e, _ in entries]}


def render_values(snapshot: dict) -> dict:
    """The snapshot's values the clip renderer understands (render.effective_options keys)."""
    keys = ("caption_style", "caption_position", "caption_emphasis", "layout", "tracking")
    return {k: v for k, v in (snapshot.get("values") or {}).items() if k in keys}


def brain_influences(snapshot: dict) -> list[dict]:
    """The snapshot's Brain-note decisions in the existing influence format (brain_influences table)."""
    out: dict[str, dict] = {}
    for d in snapshot.get("decisions") or []:
        e = d["from"]
        if e["level"] != "brain":
            continue
        item = out.setdefault(e["id"], {"knowledge_id": e["id"], "revision": e["revision"],
                                        "snapshot": {"title": e["name"], "kind": "instruction", "example_label": "",
                                                     "preferences": {}, "features": {}, "tags": [], "media": {}},
                                        "decisions": {}})
        item["decisions"][d["field"]] = {"before": None, "after": d["value"]}
        item["snapshot"]["preferences"][d["field"]] = d["value"]
    return list(out.values())

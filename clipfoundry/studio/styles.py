"""Saved styles ("My story style"): reusable editing choices with revisions.

A style stores only supported editing choices (capabilities.py) and the brief's starting answers. Never a project's
private source paths, must-keep timecodes, destinations, consent or credentials. Changing a style saves a new
revision; projects keep the revision their plan used (their guidance snapshot), so older work never changes silently.
"""
from __future__ import annotations

import os
import time

from .. import db
from . import capabilities


class StyleError(ValueError):
    pass


class Conflict(StyleError):
    pass


def view(row: dict) -> dict:
    values = row.get("values_json") or {}
    return {"id": row["id"], "name": row["name"], "revision": row["revision"], "modes": row.get("modes") or [],
            "values": values, "source": row.get("source"), "is_default": bool(row.get("is_default")),
            "reference_id": row.get("reference_id") or "", "provenance": row.get("provenance") or {},
            "effects": [capabilities.FIELDS[k].describe(v) for k, v in values.items() if k in capabilities.FIELDS
                        and capabilities.FIELDS[k].kind != "text"],
            "updated_at": row.get("updated_at")}


def _clean(values: dict, modes: list[str]) -> dict:
    private = sorted(set(values) & capabilities.PROJECT_ONLY)
    if private:
        raise StyleError("A style remembers editing choices only, not " + ", ".join(private) + ".")
    clean, problems = capabilities.clean(values, tuple(modes) or capabilities.MODES)
    if problems:
        raise StyleError("; ".join(problems))
    return clean


def _revision_row(style_id: str, rev: int, name: str, clean: dict, modes: list, provenance: dict, at: float) -> None:
    enc = db._encode("style_revisions", {"values_json": clean, "modes": modes, "provenance": provenance})  # noqa: SLF001
    db.execute("INSERT INTO style_revisions (style_id, revision, name, values_json, modes, provenance, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?)", (style_id, rev, name, enc["values_json"], enc["modes"],
                                                enc["provenance"], at))


def create(workspace_id: str, name: str, values: dict, modes: list[str], source: str = "manual",
           make_default: bool = False, reference_id: str = "", provenance: dict | None = None) -> dict:
    name = " ".join((name or "").split())[:60]
    if not name:
        raise StyleError("Give the style a name.")
    modes = [m for m in modes if m in capabilities.MODES] or list(capabilities.MODES)
    clean = _clean(values, modes)
    first = not db.select("styles", "workspace_id = ?", (workspace_id,), limit=1)
    row = db.insert("styles", {"id": "st-" + os.urandom(6).hex(), "workspace_id": workspace_id, "name": name,
                               "modes": modes, "values_json": clean, "source": source,
                               "is_default": int(make_default or (first and source != "example")),
                               "reference_id": reference_id, "provenance": provenance or {}})
    if make_default:
        set_default(row["id"])
    _revision_row(row["id"], 1, name, clean, modes, provenance or {}, row["created_at"])
    return view(db.fetch("styles", row["id"]))  # type: ignore[arg-type]


def get(style_id: str, workspace_id: str) -> dict:
    row = db.fetch("styles", style_id)
    if not row or row["workspace_id"] != workspace_id:
        raise StyleError("Style not found.")
    return row


def at_revision(style_id: str, revision: int) -> dict | None:
    rows = db.select("style_revisions", "style_id = ? AND revision = ?", (style_id, revision))
    return rows[0] if rows else None


def update(style_id: str, workspace_id: str, *, expected_revision: int, name: str | None = None,
           values: dict | None = None, provenance: dict | None = None) -> dict:
    """Save a new revision. A stale `expected_revision` (another tab saved first) is a conflict, never a lost edit."""
    row = get(style_id, workspace_id)
    if expected_revision != row["revision"]:
        raise Conflict(f"This style was changed elsewhere (now revision {row['revision']}). Reload it and try again.")
    clean = _clean(values, row["modes"]) if values is not None else row["values_json"]
    new_name = " ".join((name or row["name"]).split())[:60] or row["name"]
    rev = row["revision"] + 1
    prov = provenance if provenance is not None else (row.get("provenance") or {})
    enc = db._encode("styles", {"values_json": clean, "provenance": prov})  # noqa: SLF001
    changed = db.execute("UPDATE styles SET name = ?, values_json = ?, provenance = ?, revision = ?, updated_at = ? "
                         "WHERE id = ? AND revision = ?", (new_name, enc["values_json"], enc["provenance"], rev,
                                                           time.time(), style_id, row["revision"]))
    if not changed:
        raise Conflict("This style was changed elsewhere. Reload it and try again.")
    _revision_row(style_id, rev, new_name, clean, row["modes"], prov, time.time())
    return view(db.fetch("styles", style_id))  # type: ignore[arg-type]


def set_default(style_id: str) -> None:
    row = db.fetch("styles", style_id)
    db.execute("UPDATE styles SET is_default = 0 WHERE workspace_id = ?", (row["workspace_id"],))
    db.execute("UPDATE styles SET is_default = 1 WHERE id = ?", (style_id,))


def default(workspace_id: str) -> dict | None:
    rows = db.select("styles", "workspace_id = ? AND is_default = 1", (workspace_id,), limit=1)
    return rows[0] if rows else None


def remember_from_brief(workspace_id: str, name: str, brief: dict, mode: str) -> dict:
    """"Remember this style": keep the brief's editing choices (and its video type/audience as starting answers),
    never the project's goal, must-keep ranges, files or destinations."""
    values = {k: v for k, v in brief.items() if k in capabilities.FIELDS and k not in capabilities.PROJECT_ONLY}
    return create(workspace_id, name, values, [mode], source="brief")


def delete(style_id: str, workspace_id: str) -> None:
    get(style_id, workspace_id)
    db.execute("DELETE FROM styles WHERE id = ?", (style_id,))  # revisions stay: projects' snapshots cite them

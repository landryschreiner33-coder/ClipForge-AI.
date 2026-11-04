"""Account-synced display preferences and robot names.

Appearance (theme, accent, density, motion) and layouts are saved per signed-in user and workspace, with a schema
version and a revision for conflict checks. Layouts are separate for desktop, tablet and phone, so a phone never
inherits desktop panel sizes; every screen keeps at least one visible panel, and Reset layout touches layouts only.
Robot names are display metadata keyed by the stable role ID: they never change a worker, a job, a manager link or a
handoff, and events keep their original IDs.
"""
from __future__ import annotations

import time
import unicodedata

from .. import db

APPEARANCE_SCHEMA = 1
LAYOUT_SCHEMA = 1
THEMES = ("system", "light", "dark")
ACCENTS = ("violet", "blue", "coral", "green", "pink")
DENSITIES = ("comfortable", "compact")
MOTIONS = ("system", "full", "reduced")
DEVICES = ("desktop", "tablet", "phone")
CLIP_MODES = ("highlights", "full_stories")
# The panels each arrangeable screen has (frontend/src/layout.ts uses the same IDs).
PANELS = {"create": ("intake", "style", "destinations", "summary"),
          "review": ("preview", "outputs", "transcript", "guidance"),
          "office": ("map", "team", "activity")}
DEFAULT_APPEARANCE = {"theme": "system", "accent": "violet", "density": "comfortable", "motion": "system",
                      "clips_mode": "highlights", "remember_style": True}
NAME_MAX = 32


class PrefError(ValueError):
    pass


class Conflict(PrefError):
    pass


def default_layout(device: str) -> dict:
    sized = device != "phone"
    return {"screens": {screen: [{"id": p, "visible": True, **({"size": round(1 / len(panels), 3)} if sized else {})}
                                 for p in panels] for screen, panels in PANELS.items()}}


def _row(workspace_id: str, user_id: str, key: str) -> dict | None:
    rows = db.select("preferences", "workspace_id = ? AND user_id = ? AND pref_key = ?", (workspace_id, user_id, key))
    return rows[0] if rows else None


def _save(workspace_id: str, user_id: str, key: str, schema: int, value: dict, expected: int | None) -> dict:
    row = _row(workspace_id, user_id, key)
    now = time.time()
    if row is None:
        if expected not in (None, 0):
            raise Conflict("These preferences were reset elsewhere. Reload and try again.")
        db.execute("INSERT INTO preferences (workspace_id, user_id, pref_key, schema_version, value, revision, "
                   "updated_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                   (workspace_id, user_id, key, schema, db._encode("preferences", {"value": value})["value"],  # noqa: SLF001
                    now))
        return {"value": value, "revision": 1, "schema_version": schema}
    if expected is not None and expected != row["revision"]:
        raise Conflict("These preferences were changed on another device. Reload to see them.")
    changed = db.execute("UPDATE preferences SET value = ?, revision = revision + 1, schema_version = ?, "
                         "updated_at = ? WHERE workspace_id = ? AND user_id = ? AND pref_key = ? AND revision = ?",
                         (db._encode("preferences", {"value": value})["value"], schema, now, workspace_id,  # noqa: SLF001
                          user_id, key, row["revision"]))
    if not changed:
        raise Conflict("These preferences were changed on another device. Reload to see them.")
    return {"value": value, "revision": row["revision"] + 1, "schema_version": schema}


# ------------------------------------------------------------------ appearance
def get_appearance(workspace_id: str, user_id: str) -> dict:
    row = _row(workspace_id, user_id, "appearance")
    value = {**DEFAULT_APPEARANCE, **((row or {}).get("value") or {})}
    return {"value": value, "revision": (row or {}).get("revision", 0), "schema_version": APPEARANCE_SCHEMA}


def set_appearance(workspace_id: str, user_id: str, value: dict, expected: int | None) -> dict:
    allowed = {"theme": THEMES, "accent": ACCENTS, "density": DENSITIES, "motion": MOTIONS, "clips_mode": CLIP_MODES}
    out = dict(get_appearance(workspace_id, user_id)["value"])
    for key, v in (value or {}).items():
        if key == "remember_style":
            if type(v) is not bool:
                raise PrefError("remember_style must be true or false")
            out[key] = v
        elif key in allowed:
            if v not in allowed[key]:
                raise PrefError(f"{key}: choose one of {', '.join(allowed[key])}")
            out[key] = v
        else:
            raise PrefError(f"Unknown appearance setting “{key}”")
    return _save(workspace_id, user_id, "appearance", APPEARANCE_SCHEMA, out, expected)


# ------------------------------------------------------------------ layouts
def get_layout(workspace_id: str, user_id: str, device: str) -> dict:
    if device not in DEVICES:
        raise PrefError("Unknown device class")
    row = _row(workspace_id, user_id, f"layout:{device}")
    if not row or row["schema_version"] != LAYOUT_SCHEMA:  # an older layout format: start from the preset
        return {"value": default_layout(device), "revision": (row or {}).get("revision", 0),
                "schema_version": LAYOUT_SCHEMA, "default": True}
    return {"value": row["value"], "revision": row["revision"], "schema_version": LAYOUT_SCHEMA, "default": False}


def validate_layout(device: str, value: dict) -> dict:
    screens = (value or {}).get("screens")
    if not isinstance(screens, dict) or set(screens) - set(PANELS):
        raise PrefError("A layout lists the Create, Review and Office screens only.")
    out = default_layout(device)["screens"]
    for screen, panels in screens.items():
        if not isinstance(panels, list):
            raise PrefError("Each screen lists its panels.")
        ids = [p.get("id") for p in panels if isinstance(p, dict)]
        if sorted(ids) != sorted(PANELS[screen]):
            raise PrefError(f"The {screen} layout must list each of its panels once.")
        clean = []
        for p in panels:
            item = {"id": p["id"], "visible": bool(p.get("visible", True))}
            if device != "phone":  # phones stack panels; sizes from a wide screen never apply there
                size = p.get("size", round(1 / len(ids), 3))
                if isinstance(size, bool) or not isinstance(size, (int, float)) or not 0.1 <= size <= 0.9:
                    raise PrefError("Panel sizes are between 10% and 90%.")
                item["size"] = round(float(size), 3)
            clean.append(item)
        if not any(p["visible"] for p in clean):
            raise PrefError(f"Keep at least one panel of the {screen} screen visible.")
        out[screen] = clean
    return {"screens": out}


def set_layout(workspace_id: str, user_id: str, device: str, value: dict, expected: int | None) -> dict:
    if device not in DEVICES:
        raise PrefError("Unknown device class")
    return _save(workspace_id, user_id, f"layout:{device}", LAYOUT_SCHEMA, validate_layout(device, value), expected)


def reset_layout(workspace_id: str, user_id: str, device: str) -> dict:
    """Reset only this device class's layout: styles, edits, appearance and robot names are untouched."""
    db.execute("DELETE FROM preferences WHERE workspace_id = ? AND user_id = ? AND pref_key = ?",
               (workspace_id, user_id, f"layout:{device}"))
    return get_layout(workspace_id, user_id, device)


# ------------------------------------------------------------------ robot names
def _roles() -> dict[str, dict]:
    from ..office.roles import ROLES

    return {r["id"]: r for r in ROLES}


def clean_name(name: str) -> str:
    if not isinstance(name, str):
        raise PrefError("A name is text.")
    text = unicodedata.normalize("NFC", " ".join(name.split()))
    if not text:
        raise PrefError("Type a name, or use Reset name to go back to the original.")
    if any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co") for c in text):
        raise PrefError("Use letters, numbers, spaces and punctuation only.")
    if len(text) > NAME_MAX:  # code points, so an emoji or accented letter counts as one
        raise PrefError(f"Use at most {NAME_MAX} characters ({len(text)} now).")
    return text


def robot_names(workspace_id: str) -> dict:
    roles = _roles()
    rows = {r["role_id"]: r["display_name"] for r in db.select("robot_names", "workspace_id = ?", (workspace_id,))}
    return {rid: {"role_id": rid, "default_name": r["name"], "role": r["title"], "display_name": rows.get(rid) or
                  r["name"], "custom": rid in rows} for rid, r in roles.items()}


def rename_robot(workspace_id: str, role_id: str, name: str) -> dict:
    if role_id not in _roles():
        raise PrefError("Unknown robot.")
    text = clean_name(name)
    db.execute("INSERT INTO robot_names (workspace_id, role_id, display_name, updated_at) VALUES (?, ?, ?, ?) "
               "ON CONFLICT(workspace_id, role_id) DO UPDATE SET display_name = excluded.display_name, "
               "updated_at = excluded.updated_at", (workspace_id, role_id, text, time.time()))
    return robot_names(workspace_id)[role_id]


def reset_robot(workspace_id: str, role_id: str) -> dict:
    if role_id not in _roles():
        raise PrefError("Unknown robot.")
    db.execute("DELETE FROM robot_names WHERE workspace_id = ? AND role_id = ?", (workspace_id, role_id))
    return robot_names(workspace_id)[role_id]

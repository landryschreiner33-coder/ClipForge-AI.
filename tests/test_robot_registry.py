"""Robot crew registry checks.

Reads the TypeScript registry as text (frontend/src/robots/registry.ts) and the design manifest
(design/characters/MANIFEST.json) and checks that both describe the same, complete crew.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "frontend" / "src" / "robots" / "registry.ts"
MANIFEST = ROOT / "design" / "characters" / "MANIFEST.json"

MANAGERS = {"TRACKER", "VECTOR", "FRAME", "SCRIPT", "CLOCK", "HARBOR", "SWITCH", "CURATOR"}
WORKERS = {
    "RADAR", "ARCHIVE", "PULSE", "GAVEL", "SPARK", "STORY", "BOOST", "SPLICE",
    "GLYPH", "QUILL", "CHECK", "LOCK", "DOCK", "METRIC", "SYNAPSE", "PATCH",
}
DIRECTIONS = {"down", "up", "left", "right"}
EXPECTED_DEPARTMENTS = {
    "boss_hub": ("command", set()),
    "discover": ("tracker", {"radar", "archive"}),
    "analyze": ("vector", {"pulse", "gavel", "boost"}),
    "clip_studio": ("frame", {"spark", "story", "splice"}),
    "caption": ("script", {"glyph", "quill"}),
    "schedule": ("clock", set()),
    "upload_dock": ("harbor", {"lock", "dock"}),
    "system": ("switch", {"check", "patch"}),
    "brain": ("curator", {"metric", "synapse"}),
}

ROLE_RE = re.compile(
    r'id: "(?P<id>[a-z]+)",\s*name: "(?P<name>[A-Z]+)",\s*job: "(?P<job>[^"]+)",\s*rank: "(?P<rank>\w+)",\s*'
    r'department: "(?P<dept>\w+)",\s*managerId: (?P<mgr>null|"[a-z]+")'
)
DEPT_RE = re.compile(
    r'\{\s*id: "(?P<id>\w+)",\s*label: "[^"]+",\s*color: "#[0-9A-Fa-f]{6}",\s*managerId: "(?P<mgr>\w+)",\s*'
    r"workerIds: \[(?P<workers>[^\]]*)\],?\s*\}"
)


@pytest.fixture(scope="module")
def registry_text() -> str:
    return REGISTRY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ts_roles(registry_text: str) -> dict[str, dict]:
    block = registry_text.split("export const ROLES: RobotRole[] = [", 1)[1].split("\n];", 1)[0]
    chunks = re.split(r"\n  \{\n", block)
    roles: dict[str, dict] = {}
    for chunk in chunks:
        m = ROLE_RE.search(chunk)
        if not m:
            continue
        dirs = re.search(r"directions: \[([^\]]*)\]", chunk)
        roles[m["id"]] = {
            "id": m["id"],
            "name": m["name"],
            "rank": m["rank"],
            "department": m["dept"],
            "managerId": None if m["mgr"] == "null" else m["mgr"].strip('"'),
            "directions": set(re.findall(r'"(\w+)"', dirs[1])) if dirs else set(),
        }
    return roles


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _check_crew(roles: dict[str, dict], where: str) -> None:
    by_rank: dict[str, set[str]] = {"director": set(), "manager": set(), "worker": set()}
    for r in roles.values():
        by_rank.setdefault(r["rank"], set()).add(r["name"])
    assert len(roles) == 25, f"{where}: expected 25 roles, got {len(roles)}"
    assert "core" not in roles, f"{where}: CORE must not be counted as a role"
    assert by_rank["director"] == {"COMMAND"}, f"{where}: director must be COMMAND only"
    assert roles["command"]["managerId"] is None
    assert by_rank["manager"] == MANAGERS, f"{where}: managers differ: {by_rank['manager'] ^ MANAGERS}"
    assert by_rank["worker"] == WORKERS, f"{where}: workers differ: {by_rank['worker'] ^ WORKERS}"
    for rid, r in roles.items():
        assert set(r["directions"]) == DIRECTIONS, f"{where}: {rid} directions {r['directions']}"
        if r["rank"] == "manager":
            assert r["managerId"] == "command", f"{where}: manager {rid} must report to command"
    # departments: each worker reports to that department's manager
    for dept, (mgr, workers) in EXPECTED_DEPARTMENTS.items():
        assert roles[mgr]["department"] == dept, f"{where}: {mgr} should run {dept}"
        members = {rid for rid, r in roles.items() if r["department"] == dept and r["rank"] == "worker"}
        assert members == workers, f"{where}: {dept} workers {members} != {workers}"
        for w in workers:
            assert roles[w]["managerId"] == mgr, f"{where}: {w} must report to {mgr}"
    assert roles["quill"]["department"] == "caption"
    assert roles["metric"]["department"] == "brain"
    assert roles["synapse"]["department"] == "brain"


def test_registry_crew_is_complete(ts_roles: dict[str, dict]) -> None:
    _check_crew(ts_roles, "registry.ts")


def test_registry_ids_unique(registry_text: str) -> None:
    block = registry_text.split("export const ROLES: RobotRole[] = [", 1)[1].split("\n];", 1)[0]
    ids = re.findall(r'^    id: "([a-z]+)"', block, re.M)
    assert len(ids) == 25 and len(set(ids)) == 25, ids


def test_registry_departments_table(registry_text: str) -> None:
    found = {}
    for m in DEPT_RE.finditer(registry_text):
        found[m["id"]] = (m["mgr"], set(re.findall(r'"(\w+)"', m["workers"])))
    assert found == EXPECTED_DEPARTMENTS


def test_core_is_separate(registry_text: str, manifest: dict) -> None:
    assert re.search(r"export const CORE = \{", registry_text)
    assert manifest["core"]["id"] == "core"
    assert manifest["core"]["countedAsRole"] is False
    assert all(r["id"] != "core" for r in manifest["roles"])


def test_manifest_crew_is_complete(manifest: dict) -> None:
    roles = {r["id"]: {**r, "directions": set(r["directions"])} for r in manifest["roles"]}
    _check_crew(roles, "MANIFEST.json")
    for r in manifest["roles"]:
        assert r["source"].startswith("frontend/src/robots/art/"), r["source"]
        assert set(r["states"]) == set(manifest["states"]), r["id"]
        work = r["states"]["work"]["frames"]
        assert 2 <= work <= 4, f"{r['id']} work frames {work}"
        for state, timing in r["states"].items():
            assert len(timing["ms"]) == timing["frames"] >= 1, (r["id"], state)


def test_manifest_matches_registry(ts_roles: dict[str, dict], manifest: dict) -> None:
    man = {r["id"]: r for r in manifest["roles"]}
    assert set(man) == set(ts_roles)
    for rid, r in ts_roles.items():
        m = man[rid]
        assert (m["name"], m["rank"], m["department"], m["managerId"]) == (
            r["name"], r["rank"], r["department"], r["managerId"],
        ), rid
        assert set(m["directions"]) == r["directions"]

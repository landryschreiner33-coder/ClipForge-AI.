"""Test double for the final quality gate: records that the gate passed a clip's current file and its selected
packaging. Scheduling and publishing tests work with placeholder files (random bytes, not videos) and use this; the
gate itself is tested on real renders in test_artifact_quality.py."""
from __future__ import annotations


def passed_report(clip: dict, platforms: tuple[str, ...] = ("youtube", "tiktok")) -> dict:
    from clipfoundry import db
    from clipfoundry.autopilot import gate
    from clipfoundry.pipeline import artifact, quality

    path, version, _ = artifact.active(db.get_clip(clip["id"]) or clip)
    metadata = {}
    for p in platforms:
        meta = gate._selected(clip["id"], p)  # noqa: SLF001
        if meta:
            metadata[p] = {"status": "passed", "problems": [], "stale": False, "metadata_id": meta["id"]}
    return db.insert("quality_reports", {
        "clip_id": clip["id"], "version_id": version, "artifact_path": path, "artifact_sha256": artifact.sha256_file(path),
        "file_stamp": quality.file_stamp(path), "gate_version": quality.GATE_VERSION, "status": "passed",
        "metadata": metadata, "checks": [], "blockers": [], "warnings": [], "coverage": {"note": "test double"}})

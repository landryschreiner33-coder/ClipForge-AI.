"""Final Quality Gate: the last check between a packaged clip and the schedule.

It checks the exact file that would be published (pipeline/quality.py: hash, streams, dimensions, duration, full
decode, black/frozen/silent stretches, caption timing, cuts inside words, content estimates) and the packaging
selected for each platform against what is heard in that file (grounding, quotes, repetition, duplicate titles,
and whether it was written for this render at all). The result is stored as a report bound to the file's SHA-256,
its final transcript, time map and blueprint.

* The scheduler only plans a clip for a platform when the report of its current file passed and the platform's
  packaging passed against that file. A new render has a new file, so it needs a new report (and a stale package is
  written again).
* The publisher hashes the file again right before uploading and needs a passing report with that hash.
* Blockers keep the clip out and are listed on the clip; warnings travel with the post to the Publish Center.
"""
from __future__ import annotations

import time
from pathlib import Path

from .. import db
from ..pipeline import artifact, quality
from . import packaging, queue, rights, state
from .host import Job, handler


def _source(clip: dict) -> dict | None:
    project = db.get_project(clip["project_id"]) or {}
    return db.fetch("sources", project.get("source_id") or "") if project.get("source_id") else None


def _has_audio(clip: dict) -> bool:
    project = db.get_project(clip["project_id"]) or {}
    return bool((project.get("info") or {}).get("has_audio", True))


def _selected(clip_id: str, platform: str) -> dict | None:
    rows = db.select("metadata_candidates", "clip_id = ? AND platform = ? AND selected = 1", (clip_id, platform),
                     "created_at DESC", 1)
    return rows[0] if rows else None


# ------------------------------------------------------------------ reports
def report_for(clip: dict) -> dict | None:
    """The stored report of the file that would be published now (found by size and modification time, without
    hashing the file), or None when that file has not been checked."""
    path, _, _ = artifact.active(clip)
    if not path or not Path(path).is_file():
        return None
    rows = db.select("quality_reports", "clip_id = ? AND artifact_path = ? AND file_stamp = ? AND gate_version = ?",
                     (clip["id"], path, quality.file_stamp(path), quality.GATE_VERSION), "updated_at DESC", 1)
    return rows[0] if rows else None


def check_metadata(clip: dict, sha: str, settings: dict) -> dict:
    """For each Autopilot platform: does the selected packaging describe this very file, and only what is said in
    it? (Word matching: it catches invented names, numbers, quotes and topics, but does not prove a claim true.)"""
    sents, _ = packaging.clip_sentences(clip)
    text = " ".join(sents)
    attribution = rights.attribution(_source(clip) or {})
    prior = packaging.prior_titles(clip["id"])
    out = {}
    for platform in packaging.platforms(settings):
        meta = _selected(clip["id"], platform)
        if not meta:
            out[platform] = {"status": "missing", "problems": ["not packaged yet"], "metadata_id": ""}
            continue
        problems = []
        stale = bool(meta.get("artifact_sha256")) and meta["artifact_sha256"] != sha
        if stale:
            problems.append("written for an earlier render of this clip")
        problems += packaging.validate(meta, text, prior, [attribution])
        out[platform] = {"status": "failed" if problems else "passed", "problems": problems, "stale": stale,
                         "metadata_id": meta["id"],
                         "hash": artifact.sha256_json({k: meta.get(k) for k in ("title", "description", "caption",
                                                                                 "tags", "hashtags")}),
                         "method": "grounding by word matching (heuristic)"}
    return out


MUSIC_SHARE = 0.35  # of the clip: loud sound without speech (music, or a lot of laughter and applause)


def sound_rights_check(clip: dict) -> dict | None:
    """Coverage that does not include other people's material (an agreement with a creator, a CC or public domain
    license) must not carry someone else's music. Speech-to-text finds no words in music, so a clip with long loud
    stretches without words is rejected. A heuristic: it cannot hear background music under speech."""
    src = _source(clip)
    if not src:
        return None
    r = rights.evaluate(src)
    if r["status"] not in (rights.LICENSED, rights.ALLOWLISTED, rights.CC, rights.PD) or \
            (r.get("conditions") or {}).get("third_party"):
        return None
    audio = (db.fetch("clip_analysis", clip["id"], "clip_id") or {}).get("audio") or {}
    name, label = "sound_rights", "Sound covered by the reuse terms"
    if not audio:
        return quality.check(name, label, quality.HEURISTIC, quality.SKIP, "No sound analysis for this clip.")
    dur = max(1.0, float(clip.get("end") or 0) - float(clip.get("start") or 0))
    share = float(audio.get("reaction_seconds") or 0) / dur
    if share >= MUSIC_SHARE:
        return quality.check(name, label, quality.HEURISTIC, quality.FAIL,
                             f"{share:.0%} of the clip is loud sound without speech (possibly music). The coverage "
                             f"({r['label']}) includes only the creator's own material.")
    return quality.check(name, label, quality.HEURISTIC, quality.PASS,
                         f"Mostly speech ({share:.0%} loud sound without speech; background music under speech cannot "
                         "be ruled out).")


def run(clip: dict, settings: dict, cancelled=None) -> dict:
    """Check the clip's current file (reusing the media checks of an earlier report of the same file) and its
    packaging; store and return the report."""
    path, version, render_info = artifact.active(clip)
    if not path or not Path(path).is_file():
        raise queue.Fail("The rendered clip file is missing", "Render the clip again.")
    existing = report_for(clip)
    if existing:
        media = {k: existing[k] for k in ("artifact_path", "artifact_sha256", "file_stamp", "checks", "blockers",
                                          "warnings", "bindings", "coverage")}
        media["passed"] = existing["status"] == "passed"
    else:
        media = quality.evaluate(path, render_info, clip, _has_audio(clip), cancelled)
    sound = sound_rights_check(clip)  # rights can change, so this is judged again every time
    checks = [c for c in media["checks"] if c["name"] != "sound_rights"] + ([sound] if sound else [])
    media = {**media, "checks": checks,
             "blockers": [f"{c['label']}: {c['detail']}" for c in checks if c["status"] == quality.FAIL],
             "warnings": [f"{c['label']}: {c['detail']}" for c in checks if c["status"] == quality.WARN]}
    media["passed"] = not media["blockers"]
    metadata = check_metadata(clip, media["artifact_sha256"], settings)
    fields = {"clip_id": clip["id"], "version_id": version, "gate_version": quality.GATE_VERSION,
              "status": "passed" if media["passed"] else "failed", "metadata": metadata,
              **{k: media[k] for k in ("artifact_path", "artifact_sha256", "file_stamp", "checks", "blockers",
                                       "warnings", "bindings", "coverage")}}
    if existing:
        db.update("quality_reports", existing["id"], **fields)
        return db.fetch("quality_reports", existing["id"]) or {**existing, **fields}
    return db.insert("quality_reports", fields)


def request(clip: dict, priority: int = 0) -> dict | None:
    """Queue a gate run for the clip's current file and packaging (once per file and packaging)."""
    path, _, _ = artifact.active(clip)
    if not path or not Path(path).is_file():
        return None
    selected = sorted(filter(None, ((_selected(clip["id"], p) or {}).get("id") for p in ("youtube", "tiktok"))))
    key = f"quality:{clip['id']}:{quality.file_stamp(path)}:{','.join(selected)}"
    return queue.enqueue("quality_check", {"clip_id": clip["id"]}, idem_key=key, ref=("clip", clip["id"]),
                         priority=priority, timeout_s=1800, message="Waiting for the final quality check")


def schedulable(clip: dict, platform: str, metadata_id: str) -> tuple[bool, str]:
    """May this clip be planned for this platform with this packaging? Queues the check when it is missing."""
    rep = report_for(clip)
    md = (rep or {}).get("metadata", {}).get(platform) or {}
    if rep is None or md.get("metadata_id") != metadata_id:
        request(clip)
        return False, "waiting for the final quality check"
    if rep["status"] != "passed":
        return False, "failed the final quality check: " + "; ".join(rep["blockers"][:2])
    if md.get("status") != "passed":
        if md.get("stale"):
            queue.enqueue("package_clip", {"clip_id": clip["id"]}, ref=("clip", clip["id"]),
                          idem_key=f"package:{clip['id']}:{rep['artifact_sha256'][:16]}")
        return False, "its text did not pass the final check: " + "; ".join(md.get("problems", [])[:2])
    return True, ""


def verify_file(clip: dict, path: str) -> dict:
    """Right before an upload: hash the file itself and find a passing report for exactly that content.
    Raises queue.Wait while a check is pending and queue.Fail when the file did not pass."""
    if not path or not Path(path).is_file():
        raise queue.Fail("The rendered clip file is missing", "Render the clip again.")
    sha = artifact.sha256_file(path)
    rows = db.select("quality_reports", "clip_id = ? AND artifact_sha256 = ? AND gate_version = ?",
                     (clip["id"], sha, quality.GATE_VERSION), "updated_at DESC", 1)
    if not rows:
        request(clip, priority=100)
        raise queue.Wait("quality", 60, "Checking the final file before uploading it")
    if rows[0]["status"] != "passed":
        raise queue.Fail("The file did not pass the final quality check: " + "; ".join(rows[0]["blockers"][:2]),
                         "Fix the clip in the editor and render it again.")
    return rows[0]


def summary(rep: dict | None, platform: str = "") -> dict | None:
    """What the Publish Center shows."""
    if not rep:
        return None
    md = ((rep.get("metadata") or {}).get(platform) or {}) if platform else {}
    return {"status": rep["status"], "blockers": rep["blockers"], "warnings": rep["warnings"],
            "text_status": md.get("status"), "text_problems": md.get("problems") or [],
            "checked_at": rep["updated_at"], "sha256": rep["artifact_sha256"], "coverage": rep.get("coverage") or {},
            "checks": [{k: c.get(k) for k in ("name", "label", "kind", "status", "detail")} for c in rep["checks"]]}


# ------------------------------------------------------------------ the worker
@handler("quality_check")
def quality_check(job: Job) -> dict:
    settings = db.get_settings()
    clip = db.get_clip(job.payload.get("clip_id", ""))
    if not clip or clip["status"] != "ready":
        raise queue.Fail("The clip is missing or not rendered")
    job.progress(0.1, "Checking the rendered file", stage="quality")
    rep = run(clip, settings, job.cancelled)
    job.check()
    title = (clip.get("title") or "")[:80]
    if rep["status"] != "passed":
        state.event("quality_failed", f"“{title}” did not pass the final quality check: {rep['blockers'][0]}",
                    "warning", ref_type="clip", ref_id=clip["id"], blockers=rep["blockers"])
        return {"status": "failed", "blockers": len(rep["blockers"]), "message": "Did not pass: " + rep["blockers"][0]}
    stale = [p for p, m in rep["metadata"].items() if m.get("stale")]
    if stale:  # packaging written for an earlier render: write it again for this one, then check again
        queue.enqueue("package_clip", {"clip_id": clip["id"]}, ref=("clip", clip["id"]),
                      idem_key=f"package:{clip['id']}:{rep['artifact_sha256'][:16]}", priority=job.row["priority"])
    ok = [p for p, m in rep["metadata"].items() if m["status"] == "passed"]
    bad = {p: m["problems"] for p, m in rep["metadata"].items() if m["status"] != "passed" and not m.get("stale")}
    if bad:
        state.event("quality_text", f"“{title}”: packaging not usable for " + ", ".join(
            f"{p} ({'; '.join(v[:2])})" for p, v in bad.items()), "warning", ref_type="clip", ref_id=clip["id"])
    if ok:
        queue.enqueue("schedule_tick", {"reason": "quality"}, idem_key=f"schedule_tick:{int(time.time() // 60)}")
    warn = f", {len(rep['warnings'])} warning(s)" if rep["warnings"] else ""
    return {"status": "passed", "platforms": ok, "warnings": len(rep["warnings"]),
            "message": f"Passed{warn}; text ready for " + (", ".join(ok) or "no platform yet")}

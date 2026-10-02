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

import shutil
import time
from pathlib import Path

from .. import db
from ..pipeline import artifact, process, quality
from . import packaging, queue, rights, state
from .host import Job, handler

MAX_REGENERATIONS = 2
# Re-encoding the same approved plan can fix output corruption and rendering defects. It cannot fix a weak moment,
# absent source sound, reuse terms, or a bad creative decision, so those checks never trigger an automatic edit.
REGENERATABLE = {"hash", "codecs", "dimensions", "decode", "captions", "cuts"}


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
    if existing and existing["artifact_sha256"] != artifact.sha256_file(path):
        existing = None  # same size and time but other bytes (an edit in place): check the file again
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


def request(clip: dict, priority: int = 0, sha: str = "") -> dict | None:
    """Queue a gate run for the clip's current file and packaging (once per file and packaging). `sha`: the hash of
    bytes that were found unchecked although the file's size and time are unchanged, so it is checked once more."""
    path, _, _ = artifact.active(clip)
    source = _source(clip)
    if source:
        priority = queue.source_priority(source, priority)
    if not path or not Path(path).is_file():
        return repair_media(clip, priority=priority)
    selected = sorted(filter(None, ((_selected(clip["id"], p) or {}).get("id") for p in ("youtube", "tiktok"))))
    key = f"quality:{clip['id']}:{quality.file_stamp(path)}:{','.join(selected)}" + (f":{sha[:16]}" if sha else "")
    return queue.enqueue("quality_check", {"clip_id": clip["id"]}, idem_key=key, ref=("clip", clip["id"]),
                         priority=priority, timeout_s=1800, message="Waiting for the final quality check")


def _render_identity(clip: dict) -> str:
    return artifact.sha256_json({k: clip.get(k) for k in ("edit", "start", "end", "active_version",
                                                        "output_path", "render_info")})


ORIGINAL_FIELDS = ("status", "progress", "error", "output_path", "render_info", "duration")


def _edit_identity(clip: dict) -> str:
    return artifact.sha256_json({k: clip.get(k) for k in ("edit", "start", "end", "active_version")})


def repair_media(clip: dict, report: dict | None = None, priority: int = 0) -> dict | None:
    """At most two durable attempts to regenerate an automatic clip from the unchanged plan. Local output remains
    available when repair is impossible; a canceled repair and edits made after it was queued are respected."""
    project = db.get_project(clip["project_id"]) or {}
    source = _source(clip)
    if project.get("origin") not in ("autopilot", "live") or clip.get("active_version") or not source \
            or source.get("status") in ("canceled", "removed"):
        return None
    if not Path(project.get("source_path") or "").is_file():
        return None
    failed = {c["name"] for c in (report or {}).get("checks", []) if c["status"] == quality.FAIL}
    if report and (not failed or not failed <= REGENERATABLE):
        return None
    if db.scalar("SELECT COUNT(*) FROM scheduled_publications WHERE clip_id = ? AND status IN "
                 "('publishing', 'reconciling', 'published')", (clip["id"],)):
        return None  # preserve the exact file of an upload that may already have reached the platform
    jobs = [j for j in queue.jobs(ref=("clip", clip["id"]), limit=100) if j["kind"] == "regenerate_clip"]
    active = next((j for j in jobs if j["status"] in queue.ACTIVE), None)
    if active:
        return active
    if len(jobs) >= MAX_REGENERATIONS or any(j["status"] == "canceled" for j in jobs):
        return None
    count = len(jobs) + 1
    return queue.enqueue("regenerate_clip", {"clip_id": clip["id"], "render_identity": _render_identity(clip),
                                              "edit_identity": _edit_identity(clip),
                                              "original_clip": {k: clip.get(k) for k in ORIGINAL_FIELDS}},
                         idem_key=f"regenerate:{clip['id']}:{count}", ref=("clip", clip["id"]),
                         priority=queue.source_priority(source, max(10, priority)),
                         max_attempts=1, timeout_s=1800, revive=False,
                         message="Making a fresh copy after the final check")


def recover_regenerations() -> int:
    """Restore a saved local output after the app died inside an automatic rerender. The queue has already
    recovered the abandoned lease; live jobs and an intentional change to the edit are left alone."""
    restored = 0
    for row in db.select("worker_jobs", "kind = 'regenerate_clip' AND status IN ('failed', 'canceled')"):
        payload = row.get("payload") or {}
        clip = db.get_clip(payload.get("clip_id") or "")
        before = payload.get("original_clip") or {}
        path = before.get("output_path") or ""
        if not clip or not path or _edit_identity(clip) != payload.get("edit_identity"):
            continue
        if (clip.get("render_info") or {}).get("manual_render_pending"):
            continue  # the explicit editor render owns this file, even when the edit itself did not change
        original = Path(path)
        backup = original.with_name(f"{original.name}.regeneration-{row['id']}.bak")
        if not backup.is_file():
            continue
        if clip.get("status") == "ready" and Path(clip.get("output_path") or "").is_file() \
                and _render_identity(clip) != payload.get("render_identity"):
            # A later attempt (or this attempt just before a crash) completed the new file. The saved older
            # output must never replace it; finish its normal file/text checks instead.
            try:
                backup.unlink()
            except OSError:
                continue
            queue.enqueue("package_clip", {"clip_id": clip["id"]}, ref=("clip", clip["id"]),
                          idem_key=f"package:regeneration-recovered:{row['id']}", priority=row["priority"], revive=False)
            continue
        if db.scalar("SELECT COUNT(*) FROM worker_jobs WHERE kind = 'regenerate_clip' AND ref_id = ? "
                     "AND status IN ('queued', 'running', 'waiting', 'retrying')", (clip["id"],)):
            continue
        try:
            shutil.copy2(backup, original)
            db.update_clip(clip["id"], **{k: before.get(k) for k in ORIGINAL_FIELDS})
            backup.unlink()
        except OSError as exc:
            state.event("quality_recovery_failed", f"Could not restore this saved clip: {exc}", "warning",
                        ref_type="clip", ref_id=clip["id"])
            continue  # a damaged or inaccessible clip must not stop every worker at startup
        restored += 1
        state.event("quality_recovered", "Restored the saved clip after an interrupted fresh copy",
                    ref_type="clip", ref_id=clip["id"])
        if row["status"] == "failed":
            repair_media(db.get_clip(clip["id"]), priority=row["priority"])
    return restored


def repair_text(clip: dict, rep: dict, priority: int) -> dict | None:
    """Missing, stale or rejected generated text is safely regenerated without changing the video."""
    key = f"quality_text:{clip['id']}:{rep['artifact_sha256']}"
    attempts = int(state.get(key, 0) or 0)
    if attempts >= MAX_REGENERATIONS:
        return None
    previous = db.fetch("worker_jobs", f"repair_text:{key}:{attempts}", "idem_key") if attempts else None
    if previous and previous["status"] in queue.ACTIVE:
        return previous
    if previous and previous["status"] == "canceled":
        return None
    attempts += 1
    state.put(key, attempts)
    source = _source(clip)
    if source:
        priority = queue.source_priority(source, priority)
    return queue.enqueue("package_clip", {"clip_id": clip["id"]}, ref=("clip", clip["id"]),
                         idem_key=f"repair_text:{key}:{attempts}", priority=max(10, priority), revive=False)


@handler("regenerate_clip")
def regenerate_clip(job: Job) -> dict:
    clip = db.get_clip(job.payload.get("clip_id") or "")
    if not clip:
        raise queue.Fail("The clip was removed")
    if _render_identity(clip) != job.payload.get("render_identity"):
        if clip.get("status") == "ready":
            queue.enqueue("package_clip", {"clip_id": clip["id"]}, ref=("clip", clip["id"]),
                          idem_key=f"package:regenerated:{job.id}", priority=job.row["priority"], revive=False)
        return {"message": "The clip changed; keeping the newer edit"}
    source = _source(clip)
    settings = db.get_settings()
    if not source or not rights.local_allowed(source, rights.recheck(source, settings), settings):
        return {"message": "This video can no longer be processed; keeping the saved clip"}
    job.progress(0.1, "Making a fresh copy of the same clip", stage="render")
    original = Path(clip.get("output_path") or "")
    backup = original.with_name(f"{original.name}.regeneration-{job.id}.bak") if original.is_file() else None
    if backup and not backup.exists():
        pending = backup.with_name(f"{backup.name}.partial")
        try:
            shutil.copy2(original, pending)
            pending.replace(backup)
        finally:
            pending.unlink(missing_ok=True)
    release_backup = False
    try:
        process.render_single(clip["id"], job.pipeline_ctx(0.1, 0.9))
        job.check()
        updated = db.get_clip(clip["id"]) or {}
        if updated.get("status") != "ready":
            raise queue.Fail(updated.get("error") or "The new copy could not be rendered")
        release_backup = True
    except Exception:
        if backup and backup.is_file():
            shutil.copy2(backup, original)
            db.update_clip(clip["id"], **{k: clip.get(k) for k in ORIGINAL_FIELDS})
            release_backup = True
        raise
    finally:
        if release_backup and backup and backup.exists():
            backup.unlink()
    queue.enqueue("package_clip", {"clip_id": clip["id"]}, ref=("clip", clip["id"]),
                  idem_key=f"package:regenerated:{job.id}", priority=job.row["priority"], revive=False)
    state.event("quality_regenerated", "Made a fresh copy; checking its file and text again",
                ref_type="clip", ref_id=clip["id"])
    return {"message": "Fresh copy ready for the final check"}


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
            repair_text(clip, rep, 10)
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
        stale = report_for(clip)  # checked at this size and time, but those were other bytes: check these ones
        request(clip, priority=100, sha=sha if stale and stale["artifact_sha256"] != sha else "")
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
    try:
        rep = run(clip, settings, job.cancelled)
    except queue.Fail:
        if repair_media(clip, priority=job.row["priority"]):
            return {"status": "repairing", "message": "Making a fresh copy before checking it again"}
        raise
    job.check()
    title = (clip.get("title") or "")[:80]
    if rep["status"] != "passed":
        state.event("quality_failed", f"“{title}” did not pass the final quality check: {rep['blockers'][0]}",
                    "warning", ref_type="clip", ref_id=clip["id"], blockers=rep["blockers"])
        if repair_media(clip, rep, job.row["priority"]):
            return {"status": "repairing", "message": "Making a fresh copy after the final check"}
        from . import scout

        scout.refill(_source(clip) or {})
        return {"status": "failed", "blockers": len(rep["blockers"]), "message": "Did not pass: " + rep["blockers"][0]}
    stale = [p for p, m in rep["metadata"].items() if m.get("stale")]
    if stale:  # packaging written for an earlier render: write it again for this one, then check again
        repair_text(clip, rep, job.row["priority"])
    ok = [p for p, m in rep["metadata"].items() if m["status"] == "passed"]
    bad = {p: m["problems"] for p, m in rep["metadata"].items() if m["status"] != "passed" and not m.get("stale")}
    if bad:
        state.event("quality_text", f"“{title}”: packaging not usable for " + ", ".join(
            f"{p} ({'; '.join(v[:2])})" for p, v in bad.items()), "warning", ref_type="clip", ref_id=clip["id"])
        repair_text(clip, rep, job.row["priority"])
    if ok:
        queue.enqueue("schedule_tick", {"reason": "quality"}, idem_key=f"schedule_tick:{int(time.time() // 60)}")
    warn = f", {len(rep['warnings'])} warning(s)" if rep["warnings"] else ""
    return {"status": "passed", "platforms": ok, "warnings": len(rep["warnings"]),
            "message": f"Passed{warn}; text ready for " + (", ".join(ok) or "no platform yet")}

"""Explicit, source-bound make-and-upload requests, separate from Brain knowledge and standing consent.

Only a newly supplied input is eligible. Its acquired original bytes are bound once before analysis; every
resulting post is then approved against its own final bytes, payload, terms and existing account/audience.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import BinaryIO

from .. import config, db
from ..pipeline import artifact
from ..publish import audience
from . import intake, queue, rights, state

REUSE_BASES = [
    {"id": "owned", "label": "My original video", "text": "I own this video's footage and sound and may edit and upload clips from it."},
    {"id": "permission", "label": "I have permission", "text": "I have permission or a license covering this video's footage and sound, editing, and uploading clips to this YouTube channel."},
    {"id": "legal_exception", "label": "Another legal basis", "text": "I checked the footage and sound and have the legal basis described below to edit and upload clips from this video."},
]


def setup(settings: dict | None = None) -> dict:
    settings = settings if settings is not None else db.get_settings()
    account = db.get_account("youtube") or {}
    dest = audience.destination("youtube", settings)
    privacy = audience.visibility("youtube", dest["intent"], settings)
    blocker = ("Connect your YouTube channel in Settings → Integrations first." if not account.get("has_tokens") or
               not account.get("account_id") else "Choose and confirm who watches in Settings → Integrations → YouTube first."
               if not dest["confirmed"] else "YouTube is set to keep clips on this PC." if dest["intent"] == audience.LOCAL_ONLY else "")
    return {"account_id": str(account.get("account_id") or ""), "account_name": account.get("display_name") or
            account.get("account_id") or "", "connected": bool(account.get("has_tokens")), "audience": dest,
            "privacy": privacy, "can_upload": not blocker, "blocker": blocker, "reuse_bases": REUSE_BASES,
            "input_mode": settings.get("autopilot_input_mode", "submitted")}


def _options(options: dict) -> dict:
    if not isinstance(options, dict) or type(options.get("auto_upload")) is not bool:
        raise ValueError("Choose Make and upload, or Make clips only.")
    if not options["auto_upload"]:
        return {"auto_upload": False}
    view = setup()
    if not view["can_upload"]:
        raise ValueError(view["blocker"])
    if options.get("agreed") is not True:
        raise ValueError("Confirm that this video may be edited and its finished clips uploaded automatically.")
    if type(options.get("made_for_kids")) is not bool:
        raise ValueError("Say whether this video's clips are made for kids (YouTube requires this answer).")
    if options.get("account_id") != view["account_id"]:
        raise ValueError("The connected YouTube channel changed. Review this submission again.")
    if options.get("privacy") not in ("private", "public") or options["privacy"] != view["privacy"]:
        raise ValueError("Who watches changed. Review the visibility in Settings and submit again.")
    if type(options.get("audience_version")) is not int or options["audience_version"] != view["audience"]["group_version"]:
        raise ValueError("The chosen audience changed. Review this submission again.")
    basis = next((b for b in REUSE_BASES if b["id"] == options.get("reuse_basis")), None)
    statement = options.get("reuse_statement") or ""
    if not basis or not isinstance(statement, str) or len(statement) > 4000:
        raise ValueError("Choose your reuse basis and use at most 4,000 characters for its details.")
    if basis["id"] == "legal_exception" and not statement.strip():
        raise ValueError("Explain the legal basis covering the footage, sound, edits and YouTube upload.")
    full_statement = basis["text"] + (" Details: " + statement.strip() if statement.strip() else "")
    if len(full_statement) > 4000:
        available = 4000 - len(basis["text"]) - len(" Details: ")
        raise ValueError(f"The reuse statement, including the selected basis, must fit within 4,000 characters. "
                         f"Shorten its details to at most {available:,} characters.")
    return {"auto_upload": True, "account_id": view["account_id"], "privacy": view["privacy"],
            "made_for_kids": options["made_for_kids"], "audience": {"intent": view["audience"]["intent"],
            "platform": "youtube", "policy_version": audience.POLICY_VERSION,
            "group": view["audience"]["group"], "group_version": view["audience"]["group_version"],
            "visibility": view["privacy"]}, "reuse_basis": basis["id"], "reuse_statement": full_statement}


def _identity(source: dict) -> str:
    return artifact.sha256_json({k: source.get(k) or "" for k in ("id", "platform", "external_id", "url", "local_path")})


def _terms(source: dict, settings: dict) -> str:
    return artifact.sha256_json({"evaluation": rights.evaluate(source, settings),
                                 "attribution": rights.current_attribution(source, settings)})


def for_source(source: dict | None) -> dict | None:
    sid = ((source or {}).get("intake") or {}).get("submission_id")
    # The explicit source-bound record is authoritative even if an older intake refresh lost its UI marker.
    # Never infer authorization just from a local file or user_added: a matching saved request must exist.
    rows = db.select("source_submissions", "source_id = ?", ((source or {}).get("id") or "",), limit=2) if not sid else []
    row = db.fetch("source_submissions", sid) if sid else rows[0] if len(rows) == 1 else None
    return row if row and row["source_id"] == (source or {}).get("id") else None


def reuse_confirmation(item: dict, settings: dict) -> dict | None:
    """Carry an existing per-input reuse assertion onto its exact new clip; this is not post approval."""
    if item.get("platform") != "youtube":
        return None
    clip = db.get_clip(item.get("clip_id") or "") or {}
    project = db.get_project(clip.get("project_id") or "") or {}
    source = db.fetch("sources", project.get("source_id") or item.get("source_id") or "") or {}
    row = for_source(source)
    if not row or problem(source, settings):
        return None
    cfg = row["settings"]
    if clip.get("project_id") != cfg.get("bound_project_id") or \
            float(clip.get("created_at") or 0) < row["created_at"] or \
            float(item.get("created_at") or 0) < row["created_at"] or \
            item.get("privacy") != cfg["privacy"] or any(
                (item.get("audience") or {}).get(k) != cfg["audience"].get(k) for k in
                ("intent", "platform", "policy_version", "group", "group_version", "visibility")) or \
            (item.get("options") or {}).get("made_for_kids") is not cfg["made_for_kids"]:
        return None
    try:
        confirmation = rights.make_reuse_confirmation(item, cfg["reuse_statement"], settings)
    except (OSError, ValueError):
        return None
    return {**confirmation, "submission_id": row["id"], "confirmed_from": "source_submission"}


def _create(fields: dict, cfg: dict, *, original_url: str = "", sha: str = "") -> dict:
    if db.select("sources", "platform = ? AND external_id = ?", (fields["platform"], fields["external_id"])):
        raise ValueError("This video was already added. Its existing work and permissions are unchanged; check its progress below.")
    if fields["platform"] != "local":
        from . import verify

        # Older hand-added links used another identity hash. Re-pasting one cannot attach a grant to its old
        # project or create a second pipeline around the same already-imported video.
        for existing in db.select("sources", "url != ''"):
            prior = verify.link_video(fields["platform"], existing["url"]) if fields["platform"] in ("youtube", "tiktok") else None
            same = bool(prior and prior[0] == fields["external_id"])
            try:
                same = same or intake._direct_url(existing["url"]) == fields["url"]
            except ValueError:
                pass
            if same:
                raise ValueError("This video was already added. Its existing work and permissions are unchanged; check its progress below.")
    now, source_id, submission_id = time.time(), db.new_id(), db.new_id()
    source = {**fields, "id": source_id, "user_added": 1, "status": "queued", "status_note": "Waiting to make clips",
              "created_at": now, "updated_at": now,
              "intake": {"submitted": True, "submission_id": submission_id, "original_url": original_url,
                         "added_at": now, "priority": intake.LINK_PRIORITY}}
    cfg = {**cfg, "source_identity": _identity(source), "source_sha256": sha,
           "source_path": fields.get("local_path") or "", "bound_project_id": "", "terms_sha256": ""}
    text = (f"Make clips from this video using relevant saved Brain guidance and app settings. Upload qualifying "
            f"finished clips automatically to YouTube channel {cfg['account_id']} as {cfg['privacy']}, marked "
            f"{'made for kids' if cfg['made_for_kids'] else 'not made for kids'}. {cfg['reuse_statement']} "
            "This request covers this input only, with current required credit and final quality checks. It does not "
            "approve earlier clips, other inputs or TikTok posts. I can cancel this video's future work."
            if cfg["auto_upload"] else "Make local clips from this input using relevant Brain guidance and app settings. Do not upload them automatically.")
    # Insert both records together. Neither a periodic scout nor a worker can see a half-created publishing grant.
    try:
        with db.connect() as conn:
            encoded = db._encode("sources", source)
            conn.execute(f"INSERT INTO sources ({', '.join(encoded)}) VALUES ({', '.join('?' for _ in encoded)})", list(encoded.values()))
            conn.execute("INSERT INTO source_submissions (id,source_id,platform,settings,text,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                         (submission_id, source_id, "youtube", json.dumps(cfg), text, now, now))
            conn.execute("INSERT INTO settings (key,value) VALUES ('autopilot_enabled','true') ON CONFLICT(key) DO UPDATE SET value='true'")
    except sqlite3.IntegrityError as exc:
        raise ValueError("This video was already added. Check its existing progress; no new upload permission was created.") from exc
    source = db.fetch("sources", source_id) or source
    try:
        _enqueue(source)
    except Exception:
        # The accepted input and enabled workers commit together. A crash or failed enqueue is recovered by
        # the ordinary posting tick, without asking the owner to re-upload or granting an old source access.
        state.event("submission_waiting", "Input saved; the next posting check will start its creation job", "warning",
                    ref_type="source", ref_id=source_id)
    state.event("video_submitted", "Video submitted for automatic YouTube clips" if cfg["auto_upload"] else
                "Video submitted for local clip creation", ref_type="source", ref_id=source_id)
    view = item(source)
    return {"item": view, "submission": view["submission"], "already_added": False}


def _enqueue(source: dict) -> dict:
    if source["platform"] != "local":
        return intake._enqueue(source)
    return queue.enqueue("hunt_source", {"source_id": source["id"]}, priority=intake.LINK_PRIORITY,
                         idem_key=f"hunt:{source['id']}", ref=("source", source["id"]), max_attempts=5,
                         timeout_s=6 * 3600, message="Making clips from your file", revive=False)


def recover_unstarted(limit: int = 24) -> int:
    """Close only the accepted-input/enqueue crash window, never revive an attempted or canceled job."""
    if not state.enabled():
        return 0
    recovered = 0
    rows = db.select("sources", "status='queued' AND project_id='' AND json_extract(intake,'$.submitted')=1 "
                     "AND NOT EXISTS (SELECT 1 FROM worker_jobs j WHERE j.kind IN ('identify_link','hunt_source') "
                     "AND ((j.ref_type='source' AND j.ref_id=sources.id) OR json_extract(j.payload,'$.source_id')=sources.id))",
                     (), "created_at", max(1, min(100, limit)))
    for source in rows:
        grant = for_source(source)
        if not grant or grant.get("revoked_at") or not rights.local_allowed(source):
            continue
        _enqueue(source)
        recovered += 1
    return recovered


def add_link(url: str, options: dict) -> dict:
    cfg = _options(options)
    fields = intake.canonical_url(url)
    if fields.get("kind") == "live" or fields["platform"] == "stream":
        raise ValueError("Use a recorded video for Make and upload. Live streams remain available in the existing stream tools.")
    return _create(fields, cfg, original_url=url.strip())


def add_file(file: BinaryIO, filename: str, options: dict) -> dict:
    from .hunter import max_source_bytes, require_disk_space

    cfg = _options(options)
    name = Path(str(filename or "video.mp4").replace("\\", "/")).name
    ext = Path(name).suffix.lower()
    if ext not in config.VIDEO_EXTENSIONS:
        raise ValueError("Use an MP4, MOV, MKV, WEBM, M4V or another supported video file.")
    folder = config.data_dir() / "submitted" / db.new_id()
    folder.mkdir(parents=True, exist_ok=False)
    path = folder / f"source{ext}"
    total, digest = 0, hashlib.sha256()
    limit = max_source_bytes(db.get_settings())
    try:
        with path.open("xb") as out:
            while chunk := file.read(4 * 1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"This file exceeds the configured source limit ({limit / 1e9:g} GB).")
                try:
                    require_disk_space(folder, len(chunk))
                except queue.Wait as exc:
                    raise ValueError(str(exc)) from exc
                digest.update(chunk)
                out.write(chunk)
        if not total:
            raise ValueError("The video file is empty.")
        sha = digest.hexdigest()
        result = _create({"platform": "local", "external_id": sha, "local_path": str(path),
                          "url": path.as_uri(), "title": Path(name).stem[:120] or "Video file", "kind": "recorded"}, cfg, sha=sha)
        return result
    except Exception:
        # Only this failed submission's newly-created copy is removed, never owner media or an existing project.
        if not db.scalar("SELECT COUNT(*) FROM sources WHERE local_path=?", (str(path),)):
            shutil.rmtree(folder, ignore_errors=True)
        raise


def bind_project(source: dict, project: dict) -> None:
    row = for_source(source)
    if not row:
        return
    cfg = row["settings"]
    if project.get("source_id") != source.get("id"):
        raise ValueError("The submitted source does not match this project's input.")
    path = Path(project.get("source_path") or "")
    if not path.is_file():
        raise ValueError("The submitted source video file is missing.")
    try:
        sha = artifact.sha256_file(path)
    except OSError as exc:
        raise ValueError("The submitted source video file disappeared or cannot be read.") from exc
    if not sha or (cfg.get("source_sha256") and sha != cfg["source_sha256"]):
        raise ValueError("The submitted video changed; add it as a new input before creating or uploading new clips.")
    if cfg.get("bound_project_id") and cfg["bound_project_id"] != project["id"]:
        raise ValueError("The submitted video is already bound to another project.")
    if not cfg.get("bound_project_id"):
        settings = db.get_settings()
        db.update("source_submissions", row["id"], settings={**cfg, "source_sha256": sha,
                  "source_path": str(path), "bound_project_id": project["id"], "terms_sha256": _terms(source, settings)})


def problem(source: dict, settings: dict | None = None, require_bound: bool = True, *, quick: bool = False) -> str:
    settings = settings if settings is not None else db.get_settings()
    source = db.fetch("sources", source.get("id") or "") or source
    row = for_source(source)
    if not row or row.get("revoked_at"):
        return "This video has no active source submission request."
    cfg = row["settings"]
    if not cfg.get("auto_upload"):
        return "This video was submitted for local clips only."
    if _identity(source) != cfg.get("source_identity"):
        return "The submitted source identity changed. Review and submit the new input."
    if rights._stopped(source) or rights.evaluate(source, settings)["status"] == rights.BLOCKED:
        return "This submitted video is blocked or canceled."
    current = setup(settings)
    if not current["can_upload"]:
        return current["blocker"]
    if cfg.get("account_id") != current["account_id"]:
        return "Another YouTube channel is connected now; this submission does not authorize that channel."
    stamp = cfg.get("audience") or {}
    if cfg.get("privacy") != current["privacy"] or any(stamp.get(k) != current["audience"].get(k) for k in
                                                       ("intent", "group", "group_version")):
        return "Who watches changed since this video was submitted; review its new destination."
    if type(cfg.get("made_for_kids")) is not bool:
        return "The submitted video needs a genuine made-for-kids answer."
    if require_bound:
        project = db.get_project(source.get("project_id") or "") or {}
        if not cfg.get("bound_project_id") or project.get("id") != cfg["bound_project_id"] or \
                project.get("source_path") != cfg.get("source_path") or project.get("source_id") != source.get("id"):
            return "The submitted original has not been bound to its project yet, or was replaced."
        from .scheduler import video_sha256

        # A quick display check may reuse the memo; every actual approval/dispatch hashes the original again.
        source_sha = video_sha256(cfg.get("source_path") or "", quick=quick)
        if not source_sha or source_sha != cfg.get("source_sha256"):
            return "The submitted original's bytes changed or are missing; new clips need a new submission."
        if cfg.get("terms_sha256") != _terms(source, settings):
            return "The reuse terms or source credit changed since this video was prepared; review it again."
    return ""


def target_platforms(source: dict, settings: dict) -> list[str] | None:
    row = for_source(source)
    return (["youtube"] if (row["settings"] or {}).get("auto_upload") else []) if row else None


def post_fields(source: dict) -> dict | None:
    row = for_source(source)
    cfg = (row or {}).get("settings") or {}
    if not cfg.get("auto_upload"):
        return None
    return {"privacy": cfg["privacy"], "options": {"made_for_kids": cfg["made_for_kids"]}, "audience": cfg["audience"]}


def still_covers(item: dict, *, quick: bool = False) -> bool:
    approval = item.get("approval") or {}
    source = db.fetch("sources", item.get("source_id") or "") or {}
    row = for_source(source)
    if not row or approval.get("submission_id") != row["id"] or problem(source, quick=quick):
        return False
    cfg = row["settings"]
    clip = db.get_clip(item.get("clip_id") or "") or {}
    if clip.get("project_id") != cfg.get("bound_project_id"):
        return False
    stamp = item.get("audience") or {}
    intended = cfg["audience"]
    return (item.get("platform") == "youtube" and item.get("privacy") == cfg["privacy"] and
            (item.get("options") or {}).get("made_for_kids") is cfg["made_for_kids"] and
            all(stamp.get(k) == intended.get(k) for k in
                ("intent", "platform", "policy_version", "group", "group_version", "visibility")))


def auto_approve(item: dict, settings: dict, now: float) -> bool:
    from . import autopublish, gate, packaging, scheduler
    from ..publish.common import PublishError

    if item.get("platform") != "youtube" or item.get("status") != "awaiting_approval" or not item.get("planned_at"):
        return False
    source = db.fetch("sources", item.get("source_id") or "") or {}
    row = for_source(source)
    if not row or not row["settings"].get("auto_upload"):
        return False
    events = item.get("audit") or []
    if any(a.get("event") in ("edited", "cancelled", "canceled") for a in events):
        return False
    if any(a.get("event") == "approval_invalidated" for a in events):
        # A repaired generated file needs a fresh exact-file check/approval, not another reuse statement.
        # Manual text/options/clip edits still require the owner to review their changed post.
        metadata = db.fetch("metadata_candidates", item.get("metadata_id") or "") or {}
        clip = db.get_clip(item.get("clip_id") or "") or {}
        if not any(a.get("event") == "submission_approved" for a in events) or clip.get("edit") or clip.get("active_version") or \
                any(item.get(k) != metadata.get(k) for k in ("title", "description", "tags")):
            return False
    why = problem(source, settings)
    if why:
        scheduler._note(item, "Submission held: " + why)
        return False
    clip = db.get_clip(item.get("clip_id") or "") or {}
    cfg = row["settings"]
    if not clip or clip.get("project_id") != cfg.get("bound_project_id") or float(clip.get("created_at") or 0) < row["created_at"] or \
            float(item.get("created_at") or 0) < row["created_at"]:
        return False
    if item.get("privacy") != cfg["privacy"] or item.get("audience") != cfg["audience"] or \
            (item.get("options") or {}).get("made_for_kids") is not cfg["made_for_kids"]:
        scheduler._note(item, "Submission held: the post's destination or made-for-kids answer changed.")
        return False
    report = gate.report_for(clip)
    sha = scheduler.video_sha256(artifact.active(clip)[0])
    if not sha:
        return False
    if report and report.get("artifact_sha256") != sha:
        gate.request(clip, sha=sha)
        return False
    if report and not gate.context_valid(report, clip, settings):
        gate._request_terms_check(clip, priority=100)
        return False
    ok, why = autopublish.qualifies(report)
    if not ok:
        scheduler._note(item, "Submission held for review: " + why)
        return False
    # Keep the existing exact-file/text scheduler gate; a passing media-only report is insufficient.
    if not gate.schedulable(clip, "youtube", item.get("metadata_id") or "")[0]:
        return False
    if packaging.attribution_problem(item, "youtube", rights.current_attribution(source, settings)):
        scheduler._note(item, "Submission held: required source credit is missing from the upload text.")
        return False
    updated = dict(item)
    try:
        scheduler.check_platform(updated)
        updated["reuse_confirmation"] = rights.make_reuse_confirmation(updated, cfg["reuse_statement"], settings)
    except (PublishError, ValueError):
        return False
    updated["reuse_confirmation"].update(submission_id=row["id"], confirmed_from="source_submission")
    approval = scheduler.approval_record(updated, at=now, by="submission", submission_id=row["id"])
    if not approval or approval["video_sha256"] != sha or problem(source, settings):
        return False
    # A newer manual edit/cancellation must not lose ownership while hashing the original and rendered files.
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = db._decode("scheduled_publications", conn.execute("SELECT * FROM scheduled_publications WHERE id=?", (item["id"],)).fetchone())
        if not current or any(current.get(k) != item.get(k) for k in ("status", "updated_at", "audit", "approval", "publication_id")):
            return False
        conn.execute("UPDATE scheduled_publications SET status='approved',approval=?,reuse_confirmation=?,status_note=?,audit=?,updated_at=? WHERE id=?",
                     (json.dumps(approval), json.dumps(updated["reuse_confirmation"]),
                      "Approved automatically for this submitted video. You can cancel it until uploading starts.",
                      json.dumps(scheduler._audit(item, "submission_approved", "Approved under this input's make-and-upload request", submission_id=row["id"])), time.time(), item["id"]))
    state.event("submission_approved", "Finished clip approved under its source submission request", ref_type="scheduled", ref_id=item["id"])
    return True


def item(source: dict) -> dict:
    view = intake.item(source)
    row = for_source(source)
    if not row:
        return view
    cfg = row["settings"] or {}
    posts = db.select("scheduled_publications", "source_id = ?", (source["id"],))
    counts = {"clips_ready": int(db.scalar("SELECT COUNT(*) FROM clips WHERE project_id=? AND status='ready'", (source.get("project_id") or "",)) or 0),
              "posts_waiting": sum(p["status"] in ("awaiting_approval", "approved") for p in posts),
              "posts_uploading": sum(p["status"] in ("publishing", "reconciling") for p in posts),
              "posts_uploaded": sum(p["status"] == "published" for p in posts),
              "posts_failed": sum(p["status"] in ("failed", "blocked", "action_needed") for p in posts)}
    hold = next((p.get("status_note") or p.get("last_error") or "Review this clip in Queue."
                 for p in posts if p["status"] in ("awaiting_approval", "failed", "blocked", "action_needed")), "")
    status = ("needs_attention" if view["status"] in ("failed", "inaccessible", "canceled", "removed") or counts["posts_failed"] else
              "needs_attention" if hold else
              "uploading" if counts["posts_uploading"] else "waiting" if counts["posts_waiting"] else
              "uploaded" if counts["posts_uploaded"] and not view["can_cancel"] else
              "local_ready" if not cfg.get("auto_upload") and view["status"] in ("ready", "finished") else "creating")
    view["submission"] = {"id": row["id"], "auto_upload": cfg.get("auto_upload", False), "account_id": cfg.get("account_id", ""),
                          "privacy": cfg.get("privacy", ""), "made_for_kids": cfg.get("made_for_kids"), "created_at": row["created_at"],
                          "status": status, "progress": counts, "hold_reason": hold}
    if cfg.get("auto_upload") and counts["posts_waiting"] and view["status"] not in ("canceled", "removed"):
        view["can_cancel"] = True
    return view


def list_items() -> list[dict]:
    return [item(source) for source in db.select("sources", "user_added=1 AND json_extract(intake,'$.submitted')=1", (), "created_at DESC", 200)]

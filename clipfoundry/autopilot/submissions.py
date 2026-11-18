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

from urllib.parse import urlsplit

from .. import config, db, netguard
from ..pipeline import artifact
from ..publish import audience
from . import intake, queue, rights, state
from .targets import account_name, usable

REUSE_BASES = [
    {"id": "owned", "label": "My original video", "text": "I own this video's footage and sound and may edit and upload clips from it."},
    {"id": "permission", "label": "I have permission", "text": "I have permission or a license covering this video's footage and sound, editing, and uploading clips to this YouTube channel.",
     # Said, and saved, when the request names more than one channel: the permission must cover each of them.
     "text_many": "I have permission or a license covering this video's footage and sound, editing, and uploading clips to each YouTube channel I chose."},
    {"id": "legal_exception", "label": "Another legal basis", "text": "I checked the footage and sound and have the legal basis described below to edit and upload clips from this video."},
]


MAX_CHANNELS = 20
CONNECT_FIRST = "Connect a YouTube channel in Accounts first."
# A request from before channel choice names the default channel only; it keeps its original wording and checks.
LEGACY_CONNECT_FIRST = "Connect your YouTube channel in Settings → Integrations first."


def _workspace() -> str:
    from ..cloud import principal

    try:
        return principal.workspace_id()
    except principal.NotSignedIn:  # a background worker in cloud mode: Autopilot runs in the primary workspace
        return db.PRIMARY_WORKSPACE


def channels(workspace_id: str = "") -> list[dict]:
    """Every YouTube channel of this workspace (default first), and whether a new upload can go to it now."""
    from ..publish import connection_routes

    return [{"id": acc["id"], "account_id": acc["external_id"], "name": account_name(acc),
             "avatar": acc.get("avatar_url") or "", "is_default": acc["is_default"],
             "post_by_default": connection_routes.post_by_default(acc), "ok": usable(acc),
             "text": connection_routes.health(acc)["text"]}
            for acc in db.list_connections(workspace_id or _workspace(), "youtube")]


def _audience_blocker(dest: dict) -> str:
    return ("Choose and confirm who watches in Settings → Integrations → YouTube first." if not dest["confirmed"] else
            "YouTube is set to keep clips on this PC." if dest["intent"] == audience.LOCAL_ONLY else "")


def setup(settings: dict | None = None) -> dict:
    """What Make and upload would use now. `account_id`/`account_name` describe the default channel (older pages);
    `channels` lists every channel the owner can choose. Uploading needs at least one usable channel."""
    settings = settings if settings is not None else db.get_settings()
    account = db.get_account("youtube") or {}
    dest = audience.destination("youtube", settings)
    privacy = audience.visibility("youtube", dest["intent"], settings)
    found = channels()
    blocker = CONNECT_FIRST if not any(c["ok"] for c in found) else _audience_blocker(dest)
    return {"account_id": str(account.get("account_id") or ""), "account_name": account.get("display_name") or
            account.get("account_id") or "", "connected": bool(account.get("has_tokens")), "audience": dest,
            "privacy": privacy, "can_upload": not blocker, "blocker": blocker, "reuse_bases": REUSE_BASES,
            "input_mode": settings.get("autopilot_input_mode", "submitted"), "channels": found}


def _legacy_blocker(view: dict) -> str:
    """The check a request without a channel list always had: the default channel must be connected."""
    return LEGACY_CONNECT_FIRST if not view["connected"] or not view["account_id"] else _audience_blocker(view["audience"])


def _chosen(options: dict, view: dict) -> dict[str, str] | None:
    """The channels ticked for this video, checked now: {connection_id: channel ID} in the owner's order. "All" was
    already resolved to explicit channels by the page, so a channel connected later is never included. A request
    without a channel list (an older page) means the default channel, exactly as before (None)."""
    raw = options.get("connections")
    if raw in (None, []) and options.get("account_id"):
        blocker = _legacy_blocker(view)
        if blocker:
            raise ValueError(blocker)
        if options.get("account_id") != view["account_id"]:
            raise ValueError("The connected YouTube channel changed. Review this submission again.")
        return None
    if not isinstance(raw, list) or not raw:
        raise ValueError("Choose at least one YouTube channel.")
    if len(raw) > MAX_CHANNELS:
        raise ValueError(f"Choose at most {MAX_CHANNELS} YouTube channels for one video.")
    workspace = _workspace()
    chosen: dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"] or \
                not isinstance(entry.get("account_id"), str) or not entry["account_id"]:
            raise ValueError("Choose the YouTube channels for this video again.")
        if entry["id"] in chosen:
            raise ValueError("Choose each YouTube channel only once.")
        acc = db.get_connection(entry["id"])
        mine = bool(acc and acc["workspace_id"] == workspace and acc["platform"] == "youtube")
        if not mine or not usable(acc) or acc["external_id"] != entry["account_id"]:
            name = (account_name(acc) if mine else "") or "A chosen YouTube channel"
            raise ValueError(f"{name} changed or needs Reconnect. Review this video again.")
        chosen[entry["id"]] = acc["external_id"]
    return chosen


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
    chosen = _chosen(options, view)
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
    said = basis.get("text_many") if chosen and len(chosen) > 1 else None
    said = said or basis["text"]
    full_statement = said + (" Details: " + statement.strip() if statement.strip() else "")
    if len(full_statement) > 4000:
        available = 4000 - len(said) - len(" Details: ")
        raise ValueError(f"The reuse statement, including the selected basis, must fit within 4,000 characters. "
                         f"Shorten its details to at most {available:,} characters.")
    split = options.get("split") or "each"
    if split not in SPLITS:
        raise ValueError("Choose how the clips are shared between the channels again.")
    if split == "turns" and (chosen is None or len(chosen) < 2):
        raise ValueError("Tick at least two YouTube channels to split the clips between them.")
    destination = {"account_id": view["account_id"]} if chosen is None else \
        {"account_id": next(iter(chosen.values())), "connections": chosen,
         **({"split": "turns"} if split == "turns" else {})}  # absent means every channel gets every clip
    return {"auto_upload": True, **destination, "privacy": view["privacy"],
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
    if not row or not _covers(row["settings"], item) or \
            problem(source, settings, connection_id=item.get("connection_id") or ""):
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


def _finished_broadcast(source: dict) -> bool:
    """A channel page (twitch.tv/name, youtube.com/@name/live) names every broadcast of that channel. Once the
    recording of an earlier broadcast is over, the same link may start a new input for the next one."""
    if source.get("kind") != "live" or source.get("platform") not in ("url", "stream"):
        return False
    if not (source.get("live_status") in ("ended", "stopped") or source.get("status") in ("failed", "canceled", "error")):
        return False
    return not db.scalar("SELECT COUNT(*) FROM worker_jobs WHERE kind IN ('identify_link', 'live_capture') AND "
                         "status IN ('queued', 'retrying', 'waiting', 'running') AND "
                         "json_extract(payload, '$.source_id') = ?", (source["id"],))


def _live_choices(options: dict) -> dict:
    """What the owner chose for this stream in Live streams: how picky it is and whether its clips get a split
    view. A choice left out follows Settings; a wrong one is refused, never guessed."""
    out = {}
    for key, name, allowed in (("live_pick", "pick", config.LIVE_PICKS), ("live_framing", "framing",
                                                                       config.LIVE_FRAMINGS)):
        value = options.get(key) or ""
        if value and value not in allowed:
            raise ValueError("Choose how this stream is clipped again, then add it.")
        if value:
            out[name] = value
    return out


def _create(fields: dict, cfg: dict, *, original_url: str = "", sha: str = "", live: bool = False,
            live_choices: dict | None = None) -> dict:
    # Earlier broadcasts of the same channel link carry ":<id>" after the link's identity.
    same_identity = db.select("sources", "platform = ? AND (external_id = ? OR external_id LIKE ?)",
                              (fields["platform"], fields["external_id"], fields["external_id"] + ":%"), "created_at DESC")
    again = bool(same_identity) and all(_finished_broadcast(row) for row in same_identity)
    if same_identity and not again:
        raise ValueError("This video was already added. Its existing work and permissions are unchanged; check its progress below.")
    previous = same_identity[0] if again else None
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
            if same and not _finished_broadcast(existing):
                raise ValueError("This video was already added. Its existing work and permissions are unchanged; check its progress below.")
            if same and (previous is None or existing["created_at"] > previous["created_at"]):
                previous = existing
    now, source_id, submission_id = time.time(), db.new_id(), db.new_id()
    if previous is not None:
        # A new broadcast on the same channel page is a new input with its own identity and its own request. It
        # never reuses the earlier broadcast's source, project, recording or upload permission. The identity names
        # the input it follows, so two adds of the same link at once collide instead of recording twice.
        fields = {**fields, "external_id": f"{fields['external_id'].split(':')[0][:64]}:{previous['id'][:16]}"}
    source = {**fields, "id": source_id, "user_added": 1, "status": "queued", "status_note": "Waiting to make clips",
              "created_at": now, "updated_at": now,
              "intake": {"submitted": True, "submission_id": submission_id, "original_url": original_url,
                         "added_at": now, "priority": intake.LINK_PRIORITY, "live_requested": bool(live),
                         **({"live_choices": live_choices} if live_choices else {})}}
    cfg = {**cfg, "source_identity": _identity(source), "source_sha256": sha,
           "source_path": fields.get("local_path") or "", "bound_project_id": "", "terms_sha256": ""}
    where, others = f"YouTube channel {cfg.get('account_id')}", "other inputs"
    if cfg["auto_upload"] and not _legacy(cfg):
        names = [account_name(db.get_connection(cid)) or external for cid, external in targets(cfg).items()]
        where = f"YouTube channel {names[0]}" if len(names) == 1 else \
            f"YouTube channels {', '.join(names[:-1])} and {names[-1]}"
        if takes_turns(cfg):
            where += " (each clip to one of them, taking turns)"
        others = "other inputs, other YouTube channels"
    text = (f"Make clips from this video using relevant saved Brain guidance and app settings. Upload qualifying "
            f"finished clips automatically to {where} as {cfg['privacy']}, marked "
            f"{'made for kids' if cfg['made_for_kids'] else 'not made for kids'}. {cfg['reuse_statement']} "
            "If this link is a live stream, record it while it is live, and upload qualifying clips during the "
            "stream and from the full recording afterwards. "
            "This request covers this input only, with current required credit and final quality checks. It does not "
            f"approve earlier clips, {others} or TikTok posts. I can cancel this video's future work."
            if cfg["auto_upload"] else "Make local clips from this input using relevant Brain guidance and app "
            "settings. If it is a live stream, record it while it is live. Do not upload them automatically.")
    # Insert both records together. Neither a periodic scout nor a worker can see a half-created publishing grant.
    try:
        with db.connect() as conn:
            encoded = db._encode("sources", source)
            conn.execute(f"INSERT INTO sources ({', '.join(encoded)}) VALUES ({', '.join('?' for _ in encoded)})", list(encoded.values()))
            conn.execute("INSERT INTO source_submissions (id,source_id,platform,settings,text,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                         (submission_id, source_id, "youtube", json.dumps(cfg), text, now, now))
            conn.execute("INSERT INTO settings (key,value) VALUES ('autopilot_enabled','true') ON CONFLICT(key) DO UPDATE SET value='true'")
            if previous is not None:
                # The earlier input stays as it is (its clips and uploads), but it cannot start recording again.
                conn.execute("UPDATE sources SET intake = json_set(COALESCE(intake, '{}'), '$.superseded_by', ?) "
                             "WHERE id = ?", (source_id, previous["id"]))
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


def add_link(url: str, options: dict, *, live: bool = False) -> dict:
    """A video or a live stream. `live` only says where the owner added it (Live streams); what the link really is
    (a recorded video, a live broadcast, or a channel waiting to go live) is decided when it is checked."""
    cfg = _options(options)
    fields = intake.canonical_url(url)
    if urlsplit(fields["url"]).scheme.lower() not in netguard.HTTP:
        # The recorder reads typed links only through the guarded public HTTP relay (live.input_args).
        raise ValueError("Use the stream's web page or an https:// stream link. RTMP, SRT and RTSP addresses "
                         "cannot be recorded safely.")
    return _create(fields, cfg, original_url=url.strip(), live=live,
                   live_choices=_live_choices(options) if live else None)


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
    if cfg.get("live"):
        # Only the live recorder (bind_live, bind_live_recording) binds a live input's recording.
        raise ValueError("This live input's recording is bound by its live recorder.")
    if not cfg.get("bound_project_id"):
        settings = db.get_settings()
        db.update("source_submissions", row["id"], settings={**cfg, "source_sha256": sha,
                  "source_path": str(path), "bound_project_id": project["id"], "terms_sha256": _terms(source, settings)})


def bind_live(source: dict, project: dict) -> None:
    """Bind a submitted live input to the project its recorder writes into.

    A live stream has no original file while it is being recorded. Its grant is bound to the source and this one
    project instead; every clip is still approved against its own exact final bytes. The joined recording is bound
    by bind_live_recording when the stream ends, before the full-recording analysis.
    """
    row = for_source(source)
    if not row:
        return
    cfg = row["settings"]
    if project.get("source_id") != source.get("id") or source.get("kind") != "live":
        raise ValueError("The submitted live input does not match this recording's project.")
    if cfg.get("bound_project_id") and cfg["bound_project_id"] != project["id"]:
        raise ValueError("The submitted live input is already bound to another project.")
    if cfg.get("bound_project_id"):
        return
    if cfg.get("source_path") or cfg.get("source_sha256"):
        raise ValueError("This input was submitted as a file, not a live stream.")
    db.update("source_submissions", row["id"], settings={**cfg, "live": True, "bound_project_id": project["id"],
              "terms_sha256": _terms(source, db.get_settings())})


def bind_live_recording(source: dict, project: dict, path: Path) -> None:
    """After a submitted live stream ends: bind the full recording ClipForge joined from its own minutes."""
    row = for_source(source)
    if not row or not row["settings"].get("live"):
        return
    cfg = row["settings"]
    if cfg.get("bound_project_id") != project.get("id") or project.get("source_id") != source.get("id"):
        raise ValueError("The submitted live input is bound to another project.")
    try:
        sha = artifact.sha256_file(path)
    except OSError as exc:
        raise ValueError("The joined live recording cannot be read.") from exc
    if sha and (cfg.get("source_path"), cfg.get("source_sha256")) != (str(path), sha):
        # Joining again after a crash may write a new container around the same minutes; the newest join is the
        # file every later post-live clip is cut from, so it is the one later approvals check.
        db.update("source_submissions", row["id"], settings={**cfg, "source_path": str(path), "source_sha256": sha})


def targets(cfg: dict) -> dict[str, str]:
    """The channels a make-and-upload request covers: {connection_id: channel ID}, in the owner's order. A request
    from before channel choice has no list ({}): it covers the default channel it named (see problem())."""
    chosen = (cfg or {}).get("connections")
    return dict(chosen) if isinstance(chosen, dict) else {}


def _legacy(cfg: dict) -> bool:
    return not isinstance((cfg or {}).get("connections"), dict)


SPLITS = ("each", "turns")   # every chosen channel gets every clip, or each clip goes to one of them in turn


def takes_turns(cfg: dict) -> bool:
    """Do the request's channels share its clips, each clip going to one of them? Only with two or more channels;
    a request that does not say gives every channel every clip, as before."""
    return (cfg or {}).get("split") == "turns" and len(targets(cfg)) > 1


def clip_turn(source: dict, clip: dict, dealt: dict) -> str | None:
    """The one channel (connection ID) a clip's post goes to when its request's channels take turns; None when
    they do not. A clip never changes channel: whatever became of an earlier post of it (held, failed, canceled),
    the next one goes to the same channel. A new clip goes to the channel that has the fewest of this input's
    clips so far, the owner's order deciding a tie, so the clips end up shared evenly. A channel that needs
    Reconnect gets no new clips meanwhile (the ones it has wait for it) and catches up afterwards.

    `dealt` is one planning pass's memory ({} at its start): the clips given out in the pass before their posts
    exist (`took_turn`)."""
    cfg = (for_source(source) or {}).get("settings") or {}
    if not cfg.get("auto_upload") or not takes_turns(cfg):
        return None
    chosen = targets(cfg)
    for post in db.select("scheduled_publications", "clip_id = ? AND platform = 'youtube'", (clip["id"],), "created_at"):
        if post.get("connection_id") in chosen:
            return post["connection_id"]
    memo = dealt.setdefault(source["id"], {})
    if clip["id"] in memo.get("clips", {}):
        return memo["clips"][clip["id"]]
    if "counts" not in memo:
        memo["counts"], counted = {cid: 0 for cid in chosen}, set()
        for post in db.select("scheduled_publications", "source_id = ? AND platform = 'youtube' AND status NOT IN "
                                                        "('canceled', 'replaced')", (source["id"],)):
            key = (post["clip_id"], post.get("connection_id"))
            if post.get("connection_id") in memo["counts"] and key not in counted:
                counted.add(key)
                memo["counts"][post["connection_id"]] += 1
        memo["open"] = [cid for cid in chosen if not _channel_problem(chosen, cid)] or list(chosen)
    order = list(chosen)
    return min(memo["open"], key=lambda cid: (memo["counts"][cid], order.index(cid)))


def took_turn(source: dict, clip: dict, connection_id: str, dealt: dict) -> None:
    """Count a clip for its channel for the rest of this planning pass (its post may not exist yet)."""
    memo = dealt.setdefault(source["id"], {})
    clips = memo.setdefault("clips", {})
    if clip["id"] not in clips and connection_id in memo.get("counts", {}):
        clips[clip["id"]] = connection_id
        memo["counts"][connection_id] += 1


def _covers(cfg: dict, item: dict) -> bool:
    """Is this post's destination one the request names? A request from before channel choice covers only posts
    that go to the default channel (no connection of their own)."""
    if _legacy(cfg):
        return not item.get("connection_id")
    return bool(item.get("connection_id")) and item["connection_id"] in targets(cfg)


def _channel_problem(chosen: dict[str, str], connection_id: str) -> str:
    if connection_id not in chosen:
        return "This channel was not chosen for this video."
    acc = db.get_connection(connection_id)
    name = account_name(acc) or "A chosen YouTube channel"
    if not acc or acc.get("platform") != "youtube" or not usable(acc):
        return f"{name} needs Reconnect. Other channels continue."
    if acc["external_id"] != chosen[connection_id]:
        return f"The account behind {name} changed; this video's request does not cover it."
    return ""


def _destination_problem(cfg: dict, connection_id: str = "") -> str:
    """One channel's problem, or, without a channel, "" when at least one chosen channel can still take uploads."""
    chosen = targets(cfg)
    if connection_id:
        return _channel_problem(chosen, connection_id)
    found = [_channel_problem(chosen, cid) for cid in chosen]
    if not found:
        return "Choose at least one YouTube channel."
    return "" if "" in found else found[0]


def problem(source: dict, settings: dict | None = None, require_bound: bool = True, *, quick: bool = False,
            connection_id: str = "") -> str:
    """Why this video's request does not cover a new upload now ("" when it does). With `connection_id`, for that
    one chosen channel; a channel that needs Reconnect holds only its own posts."""
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
    if _legacy(cfg):
        blocker = _legacy_blocker(current)
        if blocker:
            return blocker
        if cfg.get("account_id") != current["account_id"]:
            return "Another YouTube channel is connected now; this submission does not authorize that channel."
    else:
        if not current["can_upload"]:
            return current["blocker"]
        why = _destination_problem(cfg, connection_id)
        if why:
            return why
    stamp = cfg.get("audience") or {}
    if cfg.get("privacy") != current["privacy"] or any(stamp.get(k) != current["audience"].get(k) for k in
                                                       ("intent", "group", "group_version")):
        return "Who watches changed since this video was submitted; review its new destination."
    if type(cfg.get("made_for_kids")) is not bool:
        return "The submitted video needs a genuine made-for-kids answer."
    if require_bound:
        project = db.get_project(source.get("project_id") or "") or {}
        # While a submitted live stream records there is no original file yet: the grant covers this project only.
        recording = bool(cfg.get("live")) and not cfg.get("source_path") and source.get("kind") == "live"
        if not cfg.get("bound_project_id") or project.get("id") != cfg["bound_project_id"] or \
                project.get("source_id") != source.get("id") or \
                (not recording and project.get("source_path") != cfg.get("source_path")):
            return "The submitted original has not been bound to its project yet, or was replaced."
        from .scheduler import video_sha256

        # A quick display check may reuse the memo; every actual approval/dispatch hashes the original again.
        source_sha = "" if recording else video_sha256(cfg.get("source_path") or "", quick=quick)
        if not recording and (not source_sha or source_sha != cfg.get("source_sha256")):
            return "The submitted original's bytes changed or are missing; new clips need a new submission."
        if cfg.get("terms_sha256") != _terms(source, settings):
            return "The reuse terms or source credit changed since this video was prepared; review it again."
    return ""


def target_platforms(source: dict, settings: dict) -> list[str] | None:
    row = for_source(source)
    return (["youtube"] if (row["settings"] or {}).get("auto_upload") else []) if row else None


def target_connections(source: dict) -> list[str] | None:
    """The YouTube connections this video's posts go to: None without a request, [] for Make clips only, the chosen
    connection IDs, or [""] (the default channel, unbound) for a request from before channel choice."""
    row = for_source(source)
    if not row:
        return None
    cfg = row["settings"] or {}
    if not cfg.get("auto_upload"):
        return []
    return [""] if _legacy(cfg) else list(targets(cfg))


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
    if not row or approval.get("submission_id") != row["id"] or not _covers(row["settings"], item) or \
            problem(source, quick=quick, connection_id=item.get("connection_id") or ""):
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
    if not _covers(row["settings"], item):
        scheduler._note(item, "Submission held: this channel was not chosen for this video.")
        return False
    why = problem(source, settings, connection_id=item.get("connection_id") or "")
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
    if not approval or approval["video_sha256"] != sha or \
            problem(source, settings, connection_id=item.get("connection_id") or ""):
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
                          "status": status, "progress": counts, "hold_reason": hold, "channels": _channel_list(cfg),
                          "split": "turns" if cfg.get("auto_upload") and takes_turns(cfg) else "each"}
    if cfg.get("auto_upload") and counts["posts_waiting"] and view["status"] not in ("canceled", "removed"):
        view["can_cancel"] = True
    return view


def _channel_list(cfg: dict) -> list[dict]:
    """The channels this video's request uploads to, named as in Accounts now."""
    if not cfg.get("auto_upload"):
        return []
    if not _legacy(cfg):
        return [{"id": cid, "name": account_name(db.get_connection(cid)) or external, "account_id": external}
                for cid, external in targets(cfg).items()]
    external = cfg.get("account_id") or ""
    if not external:
        return []
    acc = next((c for c in db.list_connections(_workspace(), "youtube") if c["external_id"] == external), None)
    return [{"id": (acc or {}).get("id") or "", "name": account_name(acc) or external, "account_id": external}]


def list_items() -> list[dict]:
    return [item(source) for source in db.select("sources", "user_added=1 AND json_extract(intake,'$.submitted')=1", (), "created_at DESC", 200)]


def _live_view(source: dict, view: dict) -> dict:
    """What the Live streams card shows. Counts only; nothing here hashes a recording."""
    project = db.get_project(source.get("project_id") or "") or {}
    clips = db.select("clips", "project_id = ?", (project.get("id") or "",)) if project else []
    recording = view["status"] == "watching_live" and source.get("live_status") == "live"
    from . import live_pick

    # The stream's own choices: saved with its project once it records, before that as it was added.
    chosen = {**live_pick.choices(source, db.get_settings()), **{k: v for k, v in (project.get("options") or {}).items()
                                                                 if k in ("live_pick", "live_framing")}}
    if project and "live_framing" not in (project.get("options") or {}):
        chosen["live_framing"] = "off"  # a stream that was being recorded before streams had this choice
    return {"recording": recording, "finishing": view.get("finishing", False),
            "minutes": round(float(project.get("duration") or 0) / 60, 1) if project.get("origin") == "live" else 0.0,
            "live_clips": sum(c["status"] == "ready" and c.get("score_source") == "Live analysis" for c in clips),
            "ended": source.get("live_status") in ("ended", "stopped"), "stopped": source.get("live_status") == "stopped",
            "clipping_stopped": bool(view.get("clipping_stopped")),
            "pick": chosen["live_pick"], "pick_label": live_pick.LABELS[chosen["live_pick"]],
            "framing": chosen["live_framing"], "framing_label": live_pick.FRAMING_LABELS[chosen["live_framing"]],
            # why no clip is being made right now, while the stream is recorded
            "note": ((project.get("info") or {}).get("live_note") or "") if recording else ""}


def live_items() -> list[dict]:
    """Inputs added in Live streams, and submitted links that turned out to be live broadcasts."""
    rows = db.select("sources", "user_added=1 AND json_extract(intake,'$.submitted')=1 AND (kind='live' OR "
                     "json_extract(intake,'$.live_requested')=1)", (), "created_at DESC", 200)
    out = []
    for source in rows:
        if (source.get("intake") or {}).get("removed"):
            continue
        view = item(source)
        out.append({**view, "live": _live_view(source, view)})
    return out

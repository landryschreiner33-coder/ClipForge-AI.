"""Delete a project: a clips project (Highlights or Full stories, the `projects` table) or a full video (Make a
YouTube video, `studio_projects`). The Projects page, a project's own page and ClipForge AI's actions all use this.

What goes is everything ClipForge keeps only for that project:
* its clips with their versions, scores and suggested post text, or its edit history (every revision), previews,
  finished videos, change requests and media searches, and its folder in the data folder;
* the media it was made from when no other project or example uses it: ClipForge's copy of an upload or of a
  downloaded link (with the transcript and preview copy made from it), or, for a file used where it is, only what
  ClipForge made from it;
* its chat with ClipForge AI and the memories that apply to this project only (what happened in it, what the owner
  said for this video);
* its planned posts that have not started uploading (canceled; they stay in the post history).

What stays: the owner's own files where they are (never deleted, never changed), everything posted already (post
history, results, and the clip fingerprints that stop a clip from being posted twice), the memories that apply to
every video, a platform or a mode, and the taste ClipForge AI learned from choices. Deleting a project is tidying up,
not a verdict on its clips, so it is not a taste lesson.

`plan` says all of this in plain sentences without changing anything, so a confirmation can show exactly what will
happen; `delete` does it and returns the same sentences. Work running for the project is stopped first. Autopilot's
work, a post that is uploading (or may already be live) and a video still being copied in are never interrupted:
deleting waits for them.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import config, db
from ..cloud import principal
from . import uploads

KINDS = ("clips", "full_video")
WAIT_S = 10.0  # how long a delete request waits for the project's stopped work to end
# Rows that belong to one project and nothing else, by the column that names it. A table added later for one
# project's work (an animated short's scenes, an agent's run) belongs here too; a listed table that does not exist
# in this database is skipped, so a line can land before the feature that makes the table.
VIDEO_TABLES = (("edit_plans", "project_id"), ("studio_artifacts", "project_id"), ("edit_requests", "project_id"),
                ("media_suggestions", "project_id"), ("media_imports", "project_id"), ("short_scenes", "project_id"))
CLIPS_TABLES = (("story_proposals", "project_id"), ("link_imports", "project_id"))
POST_LIVE = ("publishing", "reconciling")       # a planned post uploading, or one that may already be live
POST_PLANNED = ("awaiting_approval", "approved")  # planned and not started: canceled with the project
UPLOAD_OPEN = ("queued", "uploading")             # a post sent from a clip's page that has not finished sending
POSTED = ("done", "processing")                   # on YouTube or TikTok
AUTOPILOT_OPEN = ("queued", "running", "waiting", "retrying")
COPY_QUIET_S = 60.0  # a video being copied into its project folder changes far more often than this
JOB_WORDS = {"video_build": "building the video", "video_smart": "editing it for you",
             "video_preview": "making a preview", "video_render": "rendering the finished video",
             "filmcraft_edit": "editing it in FilmCraft", "video_media": "reading the files added to it",
             "media_suggest": "finding media", "media_import": "adding media", "asset_prepare": "preparing a file",
             "link_import": "downloading its video"}
_ASSET_REF = re.compile(r"as-[A-Za-z0-9_-]{2,64}")  # an asset id anywhere in a project's saved choices


class DeleteError(ValueError):
    """Why a project was not deleted, in plain words. `status`: 404 not found (or another workspace's), 409 work on
    it must end first, 422 an unknown kind. `code`: not_found, blocked (wait for it), stopping (try again in a
    moment: deleting already asked the work to stop) or kind."""

    def __init__(self, message: str, status: int = 422, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class _Survey:
    """Everything deleting one project touches, read without changing anything."""
    kind: str
    row: dict
    clips: int = 0
    versions: int = 0
    revisions: int = 0
    renders: int = 0
    keys: set[str] = field(default_factory=set)     # the heavy-work thread's keys: project, clips, versions
    jobs: list[dict] = field(default_factory=list)  # open studio jobs of the project (and of media it alone uses)
    working: list[str] = field(default_factory=list)
    blocked: str = ""
    drop: list[dict] = field(default_factory=list)  # media nothing else uses: deleted
    keep: list[dict] = field(default_factory=list)  # media something else uses: kept
    folders: list[Path] = field(default_factory=list)
    planned_posts: list[str] = field(default_factory=list)
    posted: int = 0
    memories: int = 0
    chat_messages: int = 0
    freed_bytes: int = 0


# ------------------------------------------------------------------ reading
def _load(ws: str, project_id: str, kind: str) -> dict:
    if kind not in KINDS:
        raise DeleteError("Say which kind of project to delete: clips or full_video.", 422, "kind")
    if kind == "clips":
        row = db.get_project(project_id) if project_id else None
        mine = row is not None and (row.get("workspace_id") or "local") == ws
    else:
        row = db.fetch("studio_projects", project_id) if project_id else None
        mine = row is not None and row["workspace_id"] == ws
    if not mine:
        raise DeleteError("Project not found.", 404, "not_found")
    return row  # type: ignore[return-value]


def _inside_data(path: Path) -> bool:
    data = config.data_dir().resolve()
    return data in path.resolve().parents


def _bytes(folder: Path, shared_too: bool = False) -> int:
    """What deleting `folder` frees: a file with another hard link (a project's link to an upload ClipForge keeps)
    frees nothing unless that is deleted too (`shared_too`)."""
    total = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and (shared_too or st.st_nlink <= 1):
                total += st.st_size
    return total


def _asset_folder(asset: dict) -> Path | None:
    """The folder that holds only what ClipForge keeps for this asset (a stored upload's copy and everything made
    from it, or what was made from a file used where it is), or None when there is nothing of ClipForge's to
    delete. Never a folder outside the data folder or one that holds the owner's own file."""
    if uploads.is_linked(asset):
        folder = uploads.assets_dir(asset["workspace_id"]) / asset["id"]
    else:
        folder = Path(asset["path"]).parent
    if folder.name != asset["id"] or not _inside_data(folder):
        return None
    return folder


def _used_elsewhere(ws: str, kind: str, project_id: str) -> str:
    """Everything that names media outside this project, as one text to search: other clips projects and their link
    imports, examples, and every other video (its media, brief and setup, and every saved revision, so an older
    revision can still be restored). An asset id found anywhere in it counts as a use: when in doubt the file stays."""
    other_clips = project_id if kind == "clips" else ""
    other_video = project_id if kind == "full_video" else ""
    with db.connect() as conn:
        texts = [r[0] or "" for r in conn.execute("SELECT asset_id FROM projects WHERE id != ?", (other_clips,))]
        texts += [r[0] or "" for r in conn.execute("SELECT asset_id FROM link_imports WHERE project_id != ?",
                                                   (other_clips,))]
        texts += [r[0] or "" for r in conn.execute("SELECT asset_id FROM reference_videos")]
        texts += [" ".join(str(v) for v in tuple(r)) for r in conn.execute(
            "SELECT * FROM studio_projects WHERE workspace_id = ? AND id != ?", (ws, other_video))]
        texts += [r[0] or "" for r in conn.execute(
            "SELECT plan FROM edit_plans WHERE project_id != ? AND project_id IN (SELECT id FROM studio_projects "
            "WHERE workspace_id = ?)", (other_video, ws))]
    return "\n".join(texts)


def _video_asset_ids(row: dict) -> list[str]:
    """Every asset a video names: its media, its brief and setup, and every saved revision of its plan."""
    text = json.dumps(row, default=str)
    for rev in db.select("edit_plans", "project_id = ?", (row["id"],), "revision ASC"):
        text += json.dumps(rev.get("plan"), default=str)
    return list(dict.fromkeys(_ASSET_REF.findall(text)))


def _copying(folder: Path) -> bool:
    """A video is still being copied into this project folder (a clips project made by uploading a file): the folder
    or a file in it changed within the last minute. A copy that stopped halfway (the app was closed) leaves the
    project deletable."""
    try:
        newest = os.stat(folder).st_mtime
        names = os.listdir(folder)
    except OSError:
        return False
    for name in names:
        try:  # os.stat, not the folder listing: on Windows the listing can lag behind a file still being written
            newest = max(newest, os.stat(folder / name).st_mtime)
        except OSError:
            continue
    return time.time() - newest < COPY_QUIET_S


def _pending() -> tuple[str | None, set[str]]:
    """The heavy-work thread's current key and the keys waiting for it (not already canceled)."""
    from ..jobs import worker

    try:
        waiting = {item[1] for item in list(worker.q.queue)}
    except Exception:  # noqa: BLE001 - a snapshot only
        waiting = set()
    return worker.current, waiting - set(worker.cancelled)


def _survey(ws: str, project_id: str, kind: str) -> _Survey:
    row = _load(ws, project_id, kind)
    s = _Survey(kind, row)
    current, waiting = _pending()
    if kind == "clips":
        clip_ids = [r["id"] for r in db.select("clips", "project_id = ?", (project_id,))]
        version_ids = [r["id"] for r in db.select(
            "clip_versions", "clip_id IN (SELECT id FROM clips WHERE project_id = ?)", (project_id,))]
        s.clips, s.versions = len(clip_ids), len(version_ids)
        s.keys = {project_id, *clip_ids, *version_ids}
        for key, words in ((project_id, "making its clips"), *((c, "rendering a clip") for c in clip_ids),
                           *((v, "making a version of a clip") for v in version_ids)):
            if (key == current or key in waiting) and words not in s.working:
                s.working.append(words)
        links = db.select("link_imports", "project_id = ?", (project_id,))
        s.jobs = [j for link in links for j in db.select(
            "studio_jobs", "kind = 'link_import' AND target_id = ? AND status IN ('queued', 'running')", (link["id"],))]
        asset_ids = list(dict.fromkeys(a for a in [row.get("asset_id"), *(link.get("asset_id") for link in links)]
                                       if a))
        pdir = config.projects_dir() / project_id
        if pdir.resolve().parent == config.projects_dir().resolve() and pdir.is_dir():
            s.folders.append(pdir)
        from . import link_import

        s.folders += [f for f in (link_import.imports_dir() / link["id"] for link in links) if f.is_dir()]
        # Autopilot's own work and posts on their way out are never interrupted: deleting waits for them
        refs = [("project", project_id), *(("clip", c) for c in clip_ids)]
        if row.get("source_id"):
            refs.append(("source", row["source_id"]))
        busy = any(db.scalar(f"SELECT 1 FROM worker_jobs WHERE ref_type = ? AND ref_id = ? AND status IN "
                             f"({', '.join('?' * len(AUTOPILOT_OPEN))}) LIMIT 1", (t, i, *AUTOPILOT_OPEN))
                   for t, i in refs)
        posts = db.select("scheduled_publications", "clip_id IN (SELECT id FROM clips WHERE project_id = ?)",
                          (project_id,))
        sent = db.select("publications", "clip_id IN (SELECT id FROM clips WHERE project_id = ?)", (project_id,))
        live = [p for p in posts if p["status"] in POST_LIVE] + [p for p in sent if p["status"] in UPLOAD_OPEN]
        if busy:
            s.blocked = ("Autopilot is still working on this video. Wait until it finishes, or stop it on the "
                         "Autopilot page, then delete the project.")
        elif live:
            s.blocked = ("One of its clips is being posted right now, or ClipForge is still checking whether a post "
                         "went live. Wait until that finishes (see Publishing), then delete the project.")
        elif row.get("status") == "uploading" and _copying(pdir):
            s.blocked = "ClipForge is still copying this video in. Wait until that finishes, then delete the project."
        s.planned_posts = [p["id"] for p in posts if p["status"] in POST_PLANNED]
        s.posted = sum(1 for p in sent if p["status"] in POSTED) + sum(1 for p in posts if p["status"] == "published")
    else:
        s.revisions = int(db.scalar("SELECT COUNT(*) FROM edit_plans WHERE project_id = ?", (project_id,)) or 0)
        s.renders = int(db.scalar("SELECT COUNT(*) FROM studio_artifacts WHERE project_id = ?", (project_id,)) or 0)
        s.jobs = db.select("studio_jobs", "target_id = ? AND status IN ('queued', 'running')", (project_id,),
                           "created_at ASC")
        for imp in db.select("media_imports", "project_id = ? AND status IN ('queued', 'importing')", (project_id,)):
            s.jobs += db.select("studio_jobs", "kind = 'media_import' AND target_id = ? AND status IN "
                                "('queued', 'running')", (imp["id"],))
        asset_ids = _video_asset_ids(row)
        vdir = config.data_dir() / "videos" / project_id
        if vdir.is_dir() and _inside_data(vdir):
            s.folders.append(vdir)
    elsewhere = _used_elsewhere(ws, kind, project_id) if asset_ids else ""
    for aid in asset_ids:
        asset = db.fetch("assets", aid)
        if not asset or asset["workspace_id"] != ws:
            continue
        (s.keep if aid in elsewhere else s.drop).append(asset)
    for asset in s.drop:  # preparing a file that is about to go is work on this project too
        s.jobs += db.select("studio_jobs", "kind = 'asset_prepare' AND target_id = ? AND status IN "
                            "('queued', 'running')", (asset["id"],))
    for job in s.jobs:
        words = JOB_WORDS.get(job["kind"], "working on it")
        if words not in s.working:
            s.working.append(words)
    scope = f"project:{project_id}"
    s.memories = int(db.scalar("SELECT COUNT(*) FROM brain_memories WHERE workspace_id = ? AND (scope = ? OR "
                               "project_id = ?)", (ws, scope, project_id)) or 0)
    s.chat_messages = int(db.scalar("SELECT COUNT(*) FROM brain_chat_messages WHERE chat_id IN (SELECT id FROM "
                                    "brain_chats WHERE workspace_id = ? AND project_id = ?)", (ws, project_id)) or 0)
    s.freed_bytes = sum(_bytes(f) for f in s.folders) + sum(
        _bytes(f, shared_too=True) for f in (_asset_folder(a) for a in s.drop) if f and f.is_dir())
    return s


# ------------------------------------------------------------------ the words
def size_words(n: int) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB"
    return f"{max(1, round(n / 1e3))} KB"


def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def _names(assets: list[dict], limit: int = 3) -> str:
    names = [f"“{(a.get('filename') or 'a file')[:60]}”" for a in assets[:limit]]
    more = len(assets) - limit
    return ", ".join(names) + (f" and {_n(more, 'more')}" if more > 0 else "")


def _view(s: _Survey) -> dict:
    row, name = s.row, f"“{s.row['name']}”"
    goes: list[str] = []
    if s.kind == "clips":
        goes.append(f"The project {name}" + (
            f" and its {_n(s.clips, 'clip')}, with their edits and versions." if s.clips else "."))
    else:
        made = [f"its edit history ({_n(s.revisions, 'saved version')})"] if s.revisions else []
        made += ["its previews and finished videos"] if s.renders else []
        goes.append(f"The video project {name}" + (f" with {' and '.join(made)}." if made else "."))
    copies = [a for a in s.drop if not uploads.is_linked(a)]
    linked = [a for a in s.drop if uploads.is_linked(a)]
    if copies:
        goes.append(f"ClipForge's {'copy' if len(copies) == 1 else 'copies'} of {_names(copies)}, which no other "
                    "project uses.")
    if linked:
        goes.append(f"What ClipForge made from {_names(linked)} to work with "
                    f"{'it' if len(linked) == 1 else 'them'} (sound, transcript, preview).")
    if s.planned_posts:
        goes.append(f"{_n(len(s.planned_posts), 'planned post')} of its clips that "
                    f"{'has' if len(s.planned_posts) == 1 else 'have'} not been uploaded yet.")
    if s.memories or s.chat_messages:
        parts = [f"{_n(s.memories, 'note')} ClipForge AI kept only for this project"] if s.memories else []
        if s.chat_messages:
            parts.append(f"its chat about it ({_n(s.chat_messages, 'message')})")
        text = " and ".join(parts)
        goes.append(text[0].upper() + text[1:] + ".")
    if s.freed_bytes:
        goes.append(f"In all, about {size_words(s.freed_bytes)} of space is freed.")
    stays = ["Your own files on this computer stay where they are, unchanged."]
    if s.keep:
        stays.append(f"{_names(s.keep)} {'stays' if len(s.keep) == 1 else 'stay'} in ClipForge because another "
                     "project or example uses " + ("it." if len(s.keep) == 1 else "them."))
    if s.posted:
        stays.append("Anything already posted to YouTube or TikTok stays there, with its history.")
    stays.append("What ClipForge AI learned for all your videos stays: your rules and your taste.")
    working = ""
    if s.working:
        working = f"ClipForge is still working on it ({', '.join(s.working)}). Deleting stops that first."
    return {"id": row["id"], "kind": s.kind, "name": row["name"], "blocked": s.blocked, "working": working,
            "goes": goes, "stays": stays, "freed_bytes": s.freed_bytes,
            "counts": {"clips": s.clips, "versions": s.versions, "revisions": s.revisions, "renders": s.renders,
                       "files": len(s.drop), "files_kept": len(s.keep), "planned_posts": len(s.planned_posts),
                       "memories": s.memories, "chat_messages": s.chat_messages}}


def plan(ws: str, project_id: str, kind: str) -> dict:
    """What deleting this project would do, in plain sentences, without changing anything. `blocked` is "" when it
    can be deleted now; otherwise the reason `delete` would give."""
    return _view(_survey(ws, project_id, kind))


# ------------------------------------------------------------------ deleting
def _stop(s: _Survey) -> None:
    from ..jobs import worker
    from .jobs import cancel as cancel_job

    for key in s.keys:
        worker.cancel(key)  # a queued item is skipped; the running one stops at its next safe point
    for job in s.jobs:
        cancel_job(job["id"])


def _running(s: _Survey) -> bool:
    from ..jobs import worker

    return worker.current is not None and worker.current in s.keys | {j["id"] for j in s.jobs}


def _remove(folder: Path, copies: set[tuple[int, int]]) -> None:
    """Delete a folder of ClipForge's without changing anything outside it. Windows refuses to delete a read-only
    file: an upload's copy (`copies`, kept read-only) or a file only this folder holds is made writable first, but a
    link to the owner's own file is never changed (a read-only one then stays behind, taking no space of its own)."""
    for root, dirs, files in os.walk(folder, topdown=False):
        for name in files:
            path = os.path.join(root, name)
            try:
                os.unlink(path)
            except PermissionError:
                try:
                    st = os.lstat(path)
                    if stat.S_ISLNK(st.st_mode) or (st.st_nlink > 1 and (st.st_dev, st.st_ino) not in copies):
                        continue
                    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
                    os.unlink(path)
                except OSError:
                    pass
            except OSError:
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except OSError:
                pass
    shutil.rmtree(folder, ignore_errors=True)


def _unpin(ws: str, project_id: str) -> None:
    """A deleted project leaves the pinned list, so it no longer takes one of the pin places."""
    for pref in db.select("preferences", "workspace_id = ? AND pref_key = 'appearance'", (ws,)):
        value = pref.get("value") if isinstance(pref.get("value"), dict) else {}
        pins = value.get("pinned") if isinstance(value.get("pinned"), list) else []
        if project_id in pins:
            value = {**value, "pinned": [p for p in pins if p != project_id]}
            db.execute("UPDATE preferences SET value = ?, revision = revision + 1, updated_at = ? WHERE "
                       "workspace_id = ? AND user_id = ? AND pref_key = 'appearance'",
                       (json.dumps(value), time.time(), ws, pref["user_id"]))


def delete(ws: str, project_id: str, kind: str, *, wait: float = 0.0) -> dict:
    """Delete the project and what only it uses (see the module notes); returns `plan`'s words with "deleted":
    True. Running work is asked to stop and given up to `wait` seconds; DeleteError (409, "stopping") when it has
    not stopped by then, so the caller can ask again in a moment."""
    s = _survey(ws, project_id, kind)
    if s.blocked:
        raise DeleteError(s.blocked, 409, "blocked")
    if s.working:
        _stop(s)
        end = time.monotonic() + max(0.0, wait)
        while _running(s) and time.monotonic() < end:
            time.sleep(0.2)
        if _running(s):
            raise DeleteError("ClipForge is still stopping the work on this project. Try deleting it again in a "
                              "moment.", 409, "stopping")
        s = _survey(ws, project_id, kind)  # what is there now that the work has stopped
        if s.blocked:
            raise DeleteError(s.blocked, 409, "blocked")
    out = _view(s)
    if s.planned_posts:
        from ..autopilot import scheduler

        for post_id in s.planned_posts:
            try:
                scheduler.cancel(post_id, "Canceled: its project was deleted")
            except ValueError:
                pass  # it started uploading in the meantime: it finishes, and its history stays
    scope = f"project:{project_id}"
    with db.connect() as conn:  # one transaction: the project is either all there or all gone
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if kind == "clips":
            for table in db.CLIP_CHILDREN:
                conn.execute(f"DELETE FROM {table} WHERE clip_id IN (SELECT id FROM clips WHERE project_id = ?)",
                             (project_id,))
            conn.execute("DELETE FROM clip_candidates WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM clips WHERE project_id = ?", (project_id,))
            for table, column in CLIPS_TABLES:
                if table in have:
                    conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (project_id,))
            # Autopilot's record of the video it found stays, without a link to the project that is gone (its
            # "Open its clips" would lead nowhere, and a video with a project cannot be removed from that list)
            conn.execute("UPDATE sources SET project_id = '' WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        else:
            for table, column in VIDEO_TABLES:
                if table in have:
                    conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (project_id,))
            conn.execute("DELETE FROM studio_projects WHERE id = ?", (project_id,))
        conn.execute("DELETE FROM brain_chat_messages WHERE chat_id IN (SELECT id FROM brain_chats WHERE "
                     "workspace_id = ? AND project_id = ?)", (ws, project_id))
        conn.execute("DELETE FROM brain_chats WHERE workspace_id = ? AND project_id = ?", (ws, project_id))
        conn.execute("DELETE FROM brain_memory_uses WHERE memory_id IN (SELECT id FROM brain_memories WHERE "
                     "workspace_id = ? AND (scope = ? OR project_id = ?))", (ws, scope, project_id))
        conn.execute("DELETE FROM brain_memories WHERE workspace_id = ? AND (scope = ? OR project_id = ?)",
                     (ws, scope, project_id))
        for asset in s.drop:
            for table, column in (("asset_sources", "asset_id"), ("uploads", "asset_id"), ("assets", "id")):
                conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (asset["id"],))
    stored = [a for a in s.drop + s.keep if not uploads.is_linked(a) and Path(a["path"]).is_file()]
    copies = {(st.st_dev, st.st_ino) for st in (os.stat(a["path"]) for a in stored)}
    for folder in s.folders + [f for f in (_asset_folder(a) for a in s.drop) if f]:
        _remove(folder, copies)
    for asset in s.keep:  # a kept copy stays read-only (on Windows its project link had to be made writable)
        if asset in stored:
            try:
                os.chmod(asset["path"], 0o440)
            except OSError:
                pass
    _unpin(ws, project_id)
    return {**out, "deleted": True}


# ------------------------------------------------------------------ routes
router = APIRouter()


def _refused(exc: DeleteError) -> JSONResponse:
    return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status)


def answer_delete(project_id: str, kind: str):
    """The HTTP answer to a delete: the words of what happened, or the reason with its code."""
    try:
        return {"ok": True, **delete(principal.workspace_id(), project_id, kind, wait=WAIT_S)}
    except DeleteError as exc:
        return _refused(exc)


@router.get("/api/projects/{project_id}/delete-plan")
def clips_plan(project_id: str):
    try:
        return plan(principal.workspace_id(), project_id, "clips")
    except DeleteError as exc:
        return _refused(exc)


@router.get("/api/studio/videos/{video_id}/delete-plan")
def video_plan(video_id: str):
    try:
        return plan(principal.workspace_id(), video_id, "full_video")
    except DeleteError as exc:
        return _refused(exc)


@router.delete("/api/studio/videos/{video_id}")
def delete_video(video_id: str):
    return answer_delete(video_id, "full_video")

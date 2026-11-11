"""Delete a project: a clips project (Highlights, Full stories or Story parts, the `projects` table) or a full video
(Make a YouTube video or an animated short, `studio_projects`). The Projects page, a project's own page and
ClipForge AI's actions all use this.

What goes is everything ClipForge keeps only for that project:
* its clips with their versions, scores and suggested post text, or its edit history (every revision), previews,
  finished videos, change requests and media searches, an animated short's scenes with every picture and clip its
  builds stored (its list, `short_files`, also names one no scene or version names) and the originals the picture,
  video and voice makers on this computer made for them (kept with them, with their notes; one that could not be
  kept with them stays in engines/made, and the window says so), and its folder in the data folder;
* the media it was made from when no other project or example uses it: ClipForge's copy of an upload or of a
  downloaded link (with the transcript and preview copy made from it), or, for a file used where it is, only what
  ClipForge made from it;
* its chat with ClipForge AI and the memories that apply to this project only (what happened in it, what the owner
  said for this video);
* its planned posts that have not started uploading (canceled; they stay in the post history).

What stays: the owner's own files where they are (never deleted, never changed), everything posted already (post
history, results, and the clip fingerprints that stop a clip from being posted twice), the memories that apply to
every video, a platform or a mode, the taste ClipForge AI learned from choices, and a file the owner added again
within the last day (an upload no project took: a new page may be about to use it). Deleting a project is tidying up, not a verdict on its
clips, so it is not a taste lesson.

`plan` says all of this in plain sentences without changing anything, so a confirmation can show exactly what will
happen; `delete` does it and returns the same sentences. The window's moment (`as_of`) goes back with the delete, so
a file the window said stays is not deleted because the window stayed open. Work running for the project is stopped
first. Autopilot's work, a post that is uploading (or may already be live) and a video still being copied in are never
interrupted: deleting waits for them.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
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
                ("media_suggestions", "project_id"), ("media_imports", "project_id"), ("short_scenes", "project_id"),
                ("short_files", "project_id"))
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
             "link_import": "downloading its video", "short_build": "making the short"}
_ASSET_REF = re.compile(r"as-[A-Za-z0-9_-]{2,64}")  # an asset id anywhere in a project's saved choices
SCENE_FILES = ("picture_asset_id", "clip_asset_id", "pictures")  # what an animated short's scene names (short_scenes)


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
    targets: set[str] = field(default_factory=set)  # what the project's studio jobs name: it, its imports, its media
    working: list[str] = field(default_factory=list)
    blocked: str = ""
    drop: list[dict] = field(default_factory=list)  # media nothing else uses: deleted
    keep: list[dict] = field(default_factory=list)  # media something else uses: kept
    again: list[dict] = field(default_factory=list)  # media the owner uploaded again since: kept
    handed: list[dict] = field(default_factory=list)  # media handed out again while it was being deleted: kept
    made: set[str] = field(default_factory=set)  # what ClipForge made for an animated short's scenes
    engine: dict[str, set[str]] = field(default_factory=dict)  # the makers' pictures and clips (_short_made)
    voices: bool = False  # the short read words with a maker's voice (_short_made)
    makers: list[str] = field(default_factory=list)  # the makers' originals that go with them ("pictures", ...)
    makers_left: list[str] = field(default_factory=list)  # the makers' originals left in engines/made: they stay
    as_of: float = 0.0  # the moment "added again" is judged at: when the window was shown
    source_copy: str = ""  # a clips project's own copy of its video (a recording, a download, an older upload)
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


def _files(folder: Path) -> dict[object, list[int]]:
    """Every file in `folder` once (a render reused for a later revision is one file with two links here): its
    size, its number of links and how many of them are in the folder."""
    files: dict[object, list[int]] = {}
    for root, _dirs, names in os.walk(folder):
        for name in names:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                key = (st.st_dev, st.st_ino) if st.st_ino else os.path.join(root, name)
                seen = files.setdefault(key, [st.st_size, st.st_nlink, 0])
                seen[2] += 1
    return files


def _bytes(folder: Path, shared_too: bool = False) -> int:
    """What deleting `folder` frees: a file with a link outside it too (a project's link to an upload ClipForge
    keeps) frees nothing unless that is deleted too (`shared_too`)."""
    return sum(size for size, links, here in _files(folder).values() if shared_too or here >= links)


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
    imports, examples, and every other video (its media, brief and setup, every saved revision, so an older revision
    can still be restored, its media imports, and an animated short's scenes and the list of files its builds stored:
    files are stored once, so another short's build may have stored the same bytes). An asset id found anywhere in it
    counts as a use: when in doubt the file stays."""
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
        texts += [r[0] or "" for r in conn.execute(  # an import for no project at all ('') is a use too
            "SELECT asset_id FROM media_imports WHERE project_id != ? OR project_id = ''", (other_video,))]
        texts += [" ".join(str(v or "") for v in tuple(r)) for r in conn.execute(
            f"SELECT {', '.join(SCENE_FILES)} FROM short_scenes WHERE project_id != ?", (other_video,))]
        texts += [r[0] or "" for r in conn.execute("SELECT asset_id FROM short_files WHERE project_id != ?",
                                                   (other_video,))]
    return "\n".join(texts)


def named_elsewhere(ws: str, kind: str, project_id: str) -> str:
    """`_used_elsewhere` for the animated shorts' tidying (makers/shorts.py): one text of every asset id named
    outside this project; an id found in it stays."""
    return _used_elsewhere(ws, kind, project_id)


def _video_asset_ids(row: dict) -> list[str]:
    """Every asset a video names: its media, its brief and setup, every saved revision of its plan, and an animated
    short's scene files (each scene's picture, its earlier pictures and its clip, also one not in the plan yet) and
    every file on its list (`short_files`: one its builds stored that no scene or version names any more)."""
    text = json.dumps(row, default=str)
    for rev in db.select("edit_plans", "project_id = ?", (row["id"],), "revision ASC"):
        text += json.dumps(rev.get("plan"), default=str)
    with db.connect() as conn:
        for r in conn.execute(f"SELECT {', '.join(SCENE_FILES)} FROM short_scenes WHERE project_id = ?",
                              (row["id"],)):
            text += " " + " ".join(str(v or "") for v in tuple(r))
        text += " " + " ".join(r[0] or "" for r in conn.execute(
            "SELECT asset_id FROM short_files WHERE project_id = ? ORDER BY created_at", (row["id"],)))
    return list(dict.fromkeys(_ASSET_REF.findall(text)))


def _d(value) -> dict:
    return value if isinstance(value, dict) else {}


def _short_made(project_id: str) -> tuple[set[str], dict[str, set[str]], bool]:
    """What ClipForge made for an animated short's scenes: each scene's clip and the pictures it made, as the scenes
    are now and as every saved version kept them (also a scene deleted since), but not a picture the owner chose:
    that one is ClipForge's copy of their file. Who made a scene's picture is its info.picture.source, which still
    says "upload" while a new picture waits to replace the owner's. Every file on the short's list (`short_files`:
    what its builds stored) is made too. Also which of those the makers on this computer made ({"pictures": ids,
    "video clips": ids}), and whether its voice engine read for it, from the same places and from the short's voice
    notes (a build stopped before any clip was made): the short keeps their originals with what it made from them
    (_maker_originals)."""
    made: set[str] = set()
    engine: dict[str, set[str]] = {"pictures": set(), "video clips": set()}
    voices = False

    def scene(row: dict, earlier: list[dict]) -> None:
        nonlocal voices
        info = _d(row.get("info"))
        who = _d(info.get("picture")).get("source") or ("upload" if row.get("picture_source") == "upload" else "")
        made.add(row.get("clip_asset_id") or "")
        if who != "upload":
            made.add(row.get("picture_asset_id") or "")
        made.update(e.get("asset_id") or "" for e in earlier if e.get("source") != "upload")
        if who == "engine":
            engine["pictures"].add(row.get("picture_asset_id") or "")
        engine["pictures"].update(e.get("asset_id") or "" for e in earlier if e.get("source") == "engine")
        if _d(info.get("motion")).get("how") == "engine":
            engine["video clips"].add(row.get("clip_asset_id") or "")
        voices |= _d(info.get("voice")).get("engine") == "engine"

    for rev in db.select("edit_plans", "project_id = ?", (project_id,)):
        plan = _d(rev.get("plan"))
        made.update(_d(c).get("asset_id") or "" for c in plan.get("clips") or [] if _d(c).get("scene_id"))
        for row in _d(_d(plan.get("short")).get("rows")).values():
            scene(_d(row), [])
    for row in db.select("short_scenes", "project_id = ?", (project_id,)):
        scene(row, [_d(e) for e in row.get("pictures") or []])
    made.update(r["asset_id"] for r in db.select("short_files", "project_id = ?", (project_id,)))
    voices = voices or bool(_engine_voices(project_id))
    return made - {""}, {k: v - {""} for k, v in engine.items()}, voices


def _engine_voices(project_id: str) -> set[str]:
    """The keys of the short's recorded voices that its voice engine read (their notes say so)."""
    keys: set[str] = set()
    notes = config.data_dir() / "videos" / project_id / "short" / "voice"
    if notes.is_dir():
        for note in notes.glob("*.json"):
            try:
                if _d(json.loads(note.read_text(encoding="utf-8"))).get("engine") == "engine":
                    keys.add(note.stem)
            except (OSError, ValueError):
                continue
    return keys


def _maker_originals(project_id: str, drop: list[dict], made: set[str], engine: dict[str, set[str]],
                     voices: bool) -> tuple[list[str], list[str]]:
    """The originals the makers on this computer made for a short ("pictures", "video clips", "voices"): those it
    keeps with what it made from them (a picture's or clip's own folder, its voice folder), which deleting it removes,
    and those it could not keep there (made by a version from before it did, or the move failed), which stay in
    engines/made."""
    from ..makers import shorts

    kinds = {"image": "pictures", "video": "video clips"}
    goes: set[str] = set()
    stays: set[str] = set()
    for asset in drop:
        kind = kinds.get(asset.get("kind") or "")
        if kind is None or asset["id"] not in made:
            continue
        folder = _asset_folder(asset)
        if folder is not None and (folder / f"{shorts.MAKER}.json").is_file():
            goes.add(kind)
        elif asset["id"] in engine[kind]:
            stays.add(kind)
    kept = shorts.voice_originals(project_id)
    try:
        have = {p.stem for p in kept.iterdir() if p.is_file()} if kept.is_dir() else set()
    except OSError:
        have = set()
    if have:
        goes.add("voices")
    if voices and (not have or _engine_voices(project_id) - have):
        stays.add("voices")
    order = ("pictures", "video clips", "voices")
    return [k for k in order if k in goes], [k for k in order if k in stays]


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


def _own_source(row: dict, pdir: Path) -> str:
    """The name of a clips project's own copy of its video, when the project folder holds the only link to it: a
    live recording, a download, a video copied in by an older upload. "" when it is a link to a file kept elsewhere
    (ClipForge's stored copy, handled with the media, or the owner's own file, which stays)."""
    src = Path(row.get("source_path") or "")
    try:
        st = os.lstat(src)
    except OSError:
        return ""
    if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1 or src.parent.resolve() != pdir.resolve():
        return ""
    return row.get("source_filename") or src.name


AGAIN_S = 24 * 3600  # how long a file added again stays protected while no project uses it yet


def _added_again(asset: dict, row: dict, seen: float) -> bool:
    """The owner added this file again, so a page may be about to use it, and it stays. ClipForge keeps one copy per
    file, so every upload of the same bytes is this file. Only uploads that finished in the day before `seen` (when
    the window was shown) count, and only uploads no project took (uploads.taken: each page sends the uploads it made
    a project from or added to it, and those are that project's; one a project took was for that project, also one
    deleted since). When this project took uploads of its own, the page sent all of them, so any other such upload
    is another page's ("again"). Add from this computer leaves such an upload too (uploads._hand_out). Otherwise (a
    project made before uploads were marked, or only from files ClipForge got another way) it is "again" when, in
    that day:
    * an upload finished after the project was made that did not make it: one that started after ClipForge had the
      file (also a file ClipForge got another way: Find media, a link, a short's build), or one that started before
      the project was made (another page's: a page makes its project only from finished uploads); or
    * the file was dropped twice: the project was made from one drop at most, so another page may hold the other.
    The uploads that started before ClipForge had the file count as one drop (the one that stored it and the same
    file sent alongside it, also when saving was slow). The time the project was made is used, not the time it last
    changed: stopping its work (deleting does that first) changes the project, and the answer must stay what the
    window said."""
    stored, made, day = float(asset.get("created_at") or 0), float(row.get("created_at") or 0), seen - AGAIN_S
    done = "FROM uploads WHERE asset_id = ? AND status = 'complete' AND taken = '' AND updated_at > ?"
    if db.scalar("SELECT 1 FROM uploads WHERE taken = ? LIMIT 1", (row["id"],)):  # its pages sent their uploads
        return bool(db.scalar(f"SELECT 1 {done} LIMIT 1", (asset["id"], day)))
    if db.scalar(f"SELECT 1 {done} AND (created_at > ? OR created_at < ?) LIMIT 1",
                 (asset["id"], max(made, day), stored, made)):
        return True
    later = int(db.scalar(f"SELECT COUNT(*) {done} AND created_at > ?", (asset["id"], day, stored)) or 0)
    first = 1 if db.scalar(f"SELECT 1 {done} AND created_at <= ? LIMIT 1", (asset["id"], day, stored)) else 0
    return later + first >= 2


def _handed_out(conn, asset_id: str, since: float) -> bool:
    """ClipForge handed this copy out again after `since`, the moment the window looked (an upload of the same bytes,
    Add from this computer, a build storing the same bytes): whoever got it holds it now, so it stays. Asked inside
    the delete's transaction, which such a hand-out waits for (it marks the copy, assets.reused_at, first)."""
    row = conn.execute("SELECT reused_at FROM assets WHERE id = ?", (asset_id,)).fetchone()
    return row is not None and float(row[0] or 0) > since


def _pending() -> tuple[str | None, set[str]]:
    """The heavy-work thread's current key and the keys waiting for it (not already canceled)."""
    from ..jobs import worker

    try:
        waiting = {item[1] for item in list(worker.q.queue)}
    except Exception:  # noqa: BLE001 - a snapshot only
        waiting = set()
    return worker.current, waiting - set(worker.cancelled)


def _survey(ws: str, project_id: str, kind: str, as_of: float | None = None) -> _Survey:
    row = _load(ws, project_id, kind)
    s = _Survey(kind, row)
    now = time.time()
    s.as_of = min(now, as_of) if as_of is not None and math.isfinite(as_of) else now
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
        s.targets = {link["id"] for link in links}
        s.jobs = [j for link in links for j in db.select(
            "studio_jobs", "kind = 'link_import' AND target_id = ? AND status IN ('queued', 'running')", (link["id"],))]
        asset_ids = list(dict.fromkeys(a for a in [row.get("asset_id"), *(link.get("asset_id") for link in links)]
                                       if a))
        pdir = config.projects_dir() / project_id
        if pdir.resolve().parent == config.projects_dir().resolve() and pdir.is_dir():
            s.folders.append(pdir)
            s.source_copy = _own_source(row, pdir)
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
        # a post's publish step that is already running (canceling the post does not stop it; it may be uploading)
        live += [p for p in posts if db.scalar("SELECT 1 FROM worker_jobs WHERE ref_type = 'scheduled' AND ref_id = ? "
                                               "AND status = 'running' LIMIT 1", (p["id"],))]
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
        imports = db.select("media_imports", "project_id = ?", (project_id,))
        s.targets = {project_id, *(imp["id"] for imp in imports)}
        for imp in imports:
            if imp["status"] in ("queued", "importing"):
                s.jobs += db.select("studio_jobs", "kind = 'media_import' AND target_id = ? AND status IN "
                                    "('queued', 'running')", (imp["id"],))
        asset_ids = _video_asset_ids(row)
        s.made, s.engine, s.voices = _short_made(project_id)
        vdir = config.data_dir() / "videos" / project_id
        if vdir.is_dir() and _inside_data(vdir):
            s.folders.append(vdir)
    elsewhere = _used_elsewhere(ws, kind, project_id) if asset_ids else ""
    for aid in asset_ids:
        asset = db.fetch("assets", aid)
        if not asset or asset["workspace_id"] != ws:
            continue
        if aid in elsewhere:
            s.keep.append(asset)
        elif _added_again(asset, row, s.as_of):
            s.again.append(asset)
        else:
            s.drop.append(asset)
    if kind == "full_video" and row.get("workflow") == "animated_short":
        s.makers, s.makers_left = _maker_originals(project_id, s.drop, s.made, s.engine, s.voices)
    for asset in s.drop:  # preparing a file that is about to go is work on this project too
        s.targets.add(asset["id"])
        s.jobs += db.select("studio_jobs", "kind = 'asset_prepare' AND target_id = ? AND status IN "
                            "('queued', 'running')", (asset["id"],))
    # A job that was asked to stop is no longer queued or running in its row, but the heavy-work thread may still be
    # inside it until its next safe point: it is this project's work for as long as it runs.
    job = db.fetch("studio_jobs", current) if current else None
    if job and job["target_id"] in s.targets and all(j["id"] != job["id"] for j in s.jobs):
        s.jobs.append(job)
    for job in s.jobs:
        words = JOB_WORDS.get(job["kind"], "working on it")
        if words not in s.working:
            s.working.append(words)
    s.memories = int(db.scalar("SELECT COUNT(*) FROM brain_memories WHERE workspace_id = ? AND scope = ?",
                               (ws, f"project:{project_id}")) or 0)
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


def _listed(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _names(assets: list[dict], limit: int = 3) -> str:
    names = [f"“{(a.get('filename') or 'a file')[:60]}”" for a in assets[:limit]]
    more = len(assets) - limit
    return ", ".join(names) + (f" and {more} more" if more > 0 else "")


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
    if s.source_copy:
        source = f"“{s.source_copy[:60]}”"
        goes.append(f"The recording of the live stream ({source}). ClipForge has the only copy."
                    if row.get("origin") == "live" else f"ClipForge's copy of the video it was made from ({source}).")
    made = [a for a in s.drop if a["id"] in s.made and not uploads.is_linked(a)]  # the only copy: counted, not named
    copies = [a for a in s.drop if not uploads.is_linked(a) and a["id"] not in s.made]
    linked = [a for a in s.drop if uploads.is_linked(a)]
    originals = f"the originals of the {_listed(s.makers)} made for it on this computer" if s.makers else ""
    if made:
        pictures = sum(1 for a in made if a.get("kind") == "image")
        parts = [_n(pictures, "picture")] if pictures else []
        parts += [_n(len(made) - pictures, "clip")] if len(made) > pictures else []
        goes.append(f"What ClipForge made for its scenes: {' and '.join(parts)}" +
                    (f", with {originals}." if originals else "."))
    elif originals:
        goes.append(originals[0].upper() + originals[1:] + ".")
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
    if s.again:
        stays.append(f"{_names(s.again)} {'stays' if len(s.again) == 1 else 'stay'} in ClipForge because you added "
                     + ("it" if len(s.again) == 1 else "them") + " again since.")
    if s.handed:
        stays.append(f"{_names(s.handed)} {'stays' if len(s.handed) == 1 else 'stay'} in ClipForge because "
                     + ("it was" if len(s.handed) == 1 else "they were") + " used again just now.")
    if s.makers_left:
        stays.append(f"Originals of the {_listed(s.makers_left)} made for it on this computer that ClipForge could "
                     "not keep with it stay in engines/made, each with a note of the words it was made from.")
    if s.posted:
        stays.append("Anything already posted to YouTube or TikTok stays there, with its history.")
    stays.append("What ClipForge AI learned for all your videos stays: your rules and your taste.")
    working = ""
    if s.working:
        working = f"ClipForge is still working on it ({', '.join(s.working)}). Deleting stops that first."
    return {"id": row["id"], "kind": s.kind, "name": row["name"], "blocked": s.blocked, "working": working,
            "goes": goes, "stays": stays, "freed_bytes": s.freed_bytes, "as_of": s.as_of,
            "counts": {"clips": s.clips, "versions": s.versions, "revisions": s.revisions, "renders": s.renders,
                       "files": len(s.drop) + (1 if s.source_copy else 0),
                       "files_kept": len(s.keep) + len(s.again) + len(s.handed),
                       "planned_posts": len(s.planned_posts),
                       "memories": s.memories, "chat_messages": s.chat_messages}}


def plan(ws: str, project_id: str, kind: str) -> dict:
    """What deleting this project would do, in plain sentences, without changing anything. `blocked` is "" when it
    can be deleted now; otherwise the reason `delete` would give. `as_of` is the moment it was judged: send it back
    with the delete."""
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


def _remove(folder: Path, copies: set[tuple[int, int]]) -> bool:
    """Delete a folder of ClipForge's without changing anything outside it. Windows refuses to delete a read-only
    file: an upload's copy (`copies`, kept read-only) or a file only this folder holds is made writable first, but a
    link to the owner's own file is never changed (a read-only one then stays behind, taking no space of its own).
    True when a file could not be deleted for now (on Windows, one open in another program, such as a player)."""
    stuck = False
    for root, dirs, files in os.walk(folder, topdown=False):
        for name in files:
            path = os.path.join(root, name)
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except PermissionError:
                try:
                    st = os.lstat(path)
                    if stat.S_ISLNK(st.st_mode) or (st.st_nlink > 1 and (st.st_dev, st.st_ino) not in copies):
                        # never made writable (it may be the owner's own file): read-only, it stays on purpose;
                        # writable, it was refused because it is open, so the next start tries again
                        stuck = stuck or (not stat.S_ISLNK(st.st_mode) and bool(st.st_mode & stat.S_IWRITE))
                        continue
                    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
                    os.unlink(path)
                except FileNotFoundError:
                    pass
                except OSError:
                    stuck = True
            except OSError:
                stuck = True
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except OSError:
                pass
    shutil.rmtree(folder, ignore_errors=True)
    return stuck


def remove_asset_files(asset: dict) -> bool:
    """Delete the folder ClipForge keeps for one asset whose rows are gone (what tidying an animated short does with
    a file nothing names any more), the way deleting a project does: its read-only copy is made writable first
    (Windows), nothing outside the data folder or of the owner's is touched, and a file another program still has
    open is deleted at the next start. False when there was nothing of ClipForge's to delete."""
    folder = _asset_folder(asset)
    if folder is None or not folder.is_dir():
        return False
    copies: set[tuple[int, int]] = set()
    if not uploads.is_linked(asset):
        try:
            st = os.stat(asset["path"])
            copies.add((st.st_dev, st.st_ino))
        except (OSError, TypeError, ValueError):
            pass
    if _remove(folder, copies):
        _later([folder])
    return True


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


_LATER = "delete-later.json"  # in the data folder: folders a delete could not finish removing
_later_lock = threading.Lock()


def _ours(folder: Path) -> bool:
    """A folder a delete removes: a project's, a video's, a link download's or an upload's own folder in the data
    folder (so a damaged or edited list of leftovers can never point anywhere else)."""
    data = config.data_dir().resolve()
    try:
        parent = folder.resolve().parent
    except OSError:
        return False
    return parent in {config.projects_dir().resolve(), data / "videos", data / "link-imports"} or (
        parent.parent == data / "assets")


def _read_later(path: Path) -> list[str]:
    try:
        listed = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    except (OSError, ValueError):
        return []
    return [p for p in listed if isinstance(p, str)] if isinstance(listed, list) else []


def _write_later(path: Path, listed: list[str]) -> None:
    if not listed:
        path.unlink(missing_ok=True)
        return
    tmp = path.with_name(_LATER + ".tmp")
    tmp.write_text(json.dumps(listed), encoding="utf-8")
    os.replace(tmp, path)


def _later(folders: list[Path]) -> None:
    """Remember folders with a file that could not be deleted yet, so the next start finishes them."""
    with _later_lock:
        path = config.data_dir() / _LATER
        try:
            _write_later(path, list(dict.fromkeys([*_read_later(path), *(str(f) for f in folders)])))
        except OSError:
            pass  # nothing more to do: the folder stays until it is deleted by hand


def _copies() -> dict[tuple[int, int], str]:
    """ClipForge's own upload copies (kept read-only), by file: a folder a delete left may still hold a link to one
    that stays, which may be made writable to be deleted (never the owner's own files: those are linked assets)."""
    out: dict[tuple[int, int], str] = {}
    for asset in db.select("assets"):
        if uploads.is_linked(asset):
            continue
        try:
            st = os.stat(asset["path"])
        except (OSError, TypeError, ValueError):
            continue
        out[(st.st_dev, st.st_ino)] = asset["path"]
    return out


def _finish(listed: str, copies: dict[tuple[int, int], str]) -> str:
    """Delete one listed folder: "done", "in use" (a file in it is still open) or "skipped" (it is not there, or it
    is not one of ClipForge's own folders)."""
    try:
        folder = Path(listed)
        if not folder.exists() or not _ours(folder):
            return "skipped"
        linked = [copies[k] for k in _files(folder) if k in copies]
        stuck = _remove(folder, set(copies))
        for path in linked:  # a copy that stays is read-only again (its link here had to be made writable)
            try:
                os.chmod(path, 0o440)
            except OSError:
                pass
        return "in use" if stuck else "done"
    except (OSError, ValueError):
        return "skipped"


def finish_later() -> int:
    """At start: delete what earlier deletes could not (the program that had a file open is closed by now). Only
    folders a delete listed, and only ClipForge's own (see `_ours`), are touched. Returns how many were finished."""
    with _later_lock:
        path = config.data_dir() / _LATER
        listed = _read_later(path)
        if not listed:
            return 0
        copies = _copies()
        results = {p: _finish(p, copies) for p in listed}
        try:
            _write_later(path, [p for p, r in results.items() if r == "in use"])
        except OSError:
            pass
        return sum(1 for r in results.values() if r == "done")


STOPPING = "ClipForge is still stopping the work on this project. Try deleting it again in a moment."
POSTING = ("One of its clips is being posted right now, or ClipForge is still checking whether a post went live. "
           "Wait until that finishes (see Publishing), then delete the project.")


def delete(ws: str, project_id: str, kind: str, *, wait: float = 0.0, as_of: float | None = None) -> dict:
    """Delete the project and what only it uses (see the module notes); returns `plan`'s words with "deleted":
    True ("left_behind": True when some files were in use; the next start removes them). `as_of` is the plan's
    moment (a file added again is judged as the window judged it). Running work is asked to stop and given up to
    `wait` seconds; DeleteError (409, "stopping") when it has not stopped by then, so the caller can ask again in a
    moment."""
    s = _survey(ws, project_id, kind, as_of)
    if s.blocked:
        raise DeleteError(s.blocked, 409, "blocked")
    end = time.monotonic() + max(0.0, wait)
    while s.working:
        _stop(s)
        while _running(s) and time.monotonic() < end:
            time.sleep(0.2)
        if _running(s):
            raise DeleteError(STOPPING, 409, "stopping")
        # what is there now that the work has stopped: a step that ended may have queued the next one
        s = _survey(ws, project_id, kind, as_of)
        if s.blocked:
            raise DeleteError(s.blocked, 409, "blocked")
        if s.working:
            if time.monotonic() >= end:
                _stop(s)
                raise DeleteError(STOPPING, 409, "stopping")
            time.sleep(0.2)
    out = _view(s)
    if s.planned_posts:
        from ..autopilot import scheduler

        for post_id in s.planned_posts:
            try:
                scheduler.cancel(post_id, "Canceled: its project was deleted")
            except ValueError as exc:
                post = db.fetch("scheduled_publications", post_id)
                if post and post["status"] in POST_LIVE:  # it started uploading in the meantime: wait for it
                    raise DeleteError(POSTING, 409, "blocked") from exc
    scope = f"project:{project_id}"
    with db.connect() as conn:  # one transaction: the project is either all there or all gone
        # Nothing else can change the database until this commits: a copy handed out (uploads._reuse) or a file
        # another project took since the last look waits for it, so the files are looked at once more here.
        conn.execute("BEGIN IMMEDIATE")
        named = _used_elsewhere(ws, kind, project_id) if s.drop else ""
        now_used = [a for a in s.drop if a["id"] in named]
        handed = [a for a in s.drop if a not in now_used and _handed_out(conn, a["id"], s.as_of)]
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
        # the scope says whom a memory is for (a memory saved again for another project or a platform keeps the
        # project_id it was first saved with, so that column is not used here)
        conn.execute("DELETE FROM brain_memory_uses WHERE memory_id IN (SELECT id FROM brain_memories WHERE "
                     "workspace_id = ? AND scope = ?)", (ws, scope))
        conn.execute("DELETE FROM brain_memories WHERE workspace_id = ? AND scope = ?", (ws, scope))
        s.drop = [a for a in s.drop if a not in now_used and a not in handed]
        for asset in s.drop:
            for table, column in (("asset_sources", "asset_id"), ("uploads", "asset_id"), ("assets", "id")):
                conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (asset["id"],))
    if now_used or handed:  # the answer says what happened
        s.keep += now_used
        s.handed += handed
        s.freed_bytes -= sum(_bytes(f, shared_too=True) for f in (_asset_folder(a) for a in now_used + handed)
                             if f and f.is_dir())
        if kind == "full_video" and s.row.get("workflow") == "animated_short":
            s.makers, s.makers_left = _maker_originals(project_id, s.drop, s.made, s.engine, s.voices)
        out = _view(s)
    kept = s.keep + s.again + s.handed
    stored = [a for a in s.drop + kept if not uploads.is_linked(a) and Path(a["path"]).is_file()]
    copies = {(st.st_dev, st.st_ino) for st in (os.stat(a["path"]) for a in stored)}
    folders = s.folders + [f for f in (_asset_folder(a) for a in s.drop) if f]
    left = [f for f in folders if _remove(f, copies)]
    for asset in kept:  # a kept copy stays read-only (on Windows its project link had to be made writable)
        if asset in stored:
            try:
                os.chmod(asset["path"], 0o440)
            except OSError:
                pass
    if left:
        _later(left)
    _unpin(ws, project_id)
    return {**out, "deleted": True, "left_behind": bool(left)}


# ------------------------------------------------------------------ routes
router = APIRouter()


def _refused(exc: DeleteError) -> JSONResponse:
    return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status)


def from_this_computer(request: Request) -> None:
    """Deleting cancels planned posts and deletes ClipForge AI's notes, which only ClipForge's own page on this
    computer may change (publish/common.py app_request: the page's header, and a request from this computer, so a
    web site that points its name at this computer cannot delete anything). Said in words about deleting."""
    from ..cloud import settings as cloud_settings
    from ..publish import common

    if not cloud_settings.enabled():
        try:
            common.local_only(request)
        except HTTPException as exc:
            raise HTTPException(403, "Projects can only be deleted in ClipForge on the computer that runs it "
                                     "(http://127.0.0.1).") from exc
    common.app_request(request)


def answer_delete(project_id: str, kind: str, as_of: float | None = None):
    """The HTTP answer to a delete: the words of what happened, or the reason with its code. `as_of` is the plan's
    moment, which the page sends back."""
    try:
        return {"ok": True, **delete(principal.workspace_id(), project_id, kind, wait=WAIT_S, as_of=as_of)}
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


@router.delete("/api/studio/videos/{video_id}", dependencies=[Depends(from_this_computer)])
def delete_video(video_id: str, as_of: float | None = None):
    return answer_delete(video_id, "full_video", as_of)

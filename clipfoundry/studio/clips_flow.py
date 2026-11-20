"""Make clips: Highlights, Full stories or Story parts from one uploaded file or link.

Story parts is Full stories cut into parts: the project is a Full stories project (the same styles, skills and
examples apply) whose options say how its stories are cut ("story_split": "whole" or "parts", studio/story_review.py).

The project gets its own folder with the source as a hard link to the immutable asset (no copy, and deleting the
project never deletes the original), a frozen guidance snapshot, and, for "Make & upload clips", the explicit
upload request for this input: the exact destinations, audience, kids answer and reuse statement, recorded once.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from .. import config, db
from ..jobs import worker
from . import guidance, prefs, skills, styles, uploads
from .capabilities import CLIP_MODES

REUSE_BASES = {
    "owned": "I own this video's footage and sound and may edit and upload clips from it.",
    "permission": "I have permission or a license covering this video's footage and sound, editing, and uploading "
                  "clips to the chosen channels.",
}


# What Make clips can ask for, and how each story setting cuts the stories (story_review.SPLITS)
STORY_SPLITS = {"full_stories": "whole", "story_parts": "parts"}
REQUEST_MODES = (*CLIP_MODES, "story_parts")


class FlowError(ValueError):
    pass


def guidance_mode(mode: str) -> str:
    """The project type whose styles, skills and examples apply: Story parts are Full stories cut into parts."""
    return "full_stories" if mode == "story_parts" else mode


def _link_source(asset: dict, pdir: Path) -> Path:
    pdir.mkdir(parents=True, exist_ok=True)
    dest = pdir / ("source" + Path(asset["path"]).suffix)
    try:
        os.link(asset["path"], dest)
    except OSError:
        os.symlink(asset["path"], dest)  # another filesystem: a link still never copies or owns the original
    return dest


def _reuse_analysis(asset_id: str, workspace_id: str, pdir: Path) -> str:
    """Reuse another project's transcript of the very same file (same content hash): no second transcription."""
    for other in db.select("projects", "asset_id = ? AND workspace_id = ?", (asset_id, workspace_id),
                           "updated_at DESC"):
        odir = Path(other.get("source_path") or "").parent
        if odir != pdir and (odir / "transcript.json").exists():
            for name in ("transcript.json", "loudness.json"):
                if (odir / name).exists():
                    shutil.copy2(odir / name, pdir / name)
            return other["id"]
    return ""


def _style(workspace_id: str, style_id: str) -> dict | None:
    if style_id in ("", "settings"):
        return None
    if style_id == "saved":
        return styles.default(workspace_id)
    return styles.get(style_id, workspace_id)


def upload_request(workspace_id: str, upload: dict | None) -> dict:
    """Validate "Make & upload clips". YouTube destinations upload automatically once their clip passes its checks;
    TikTok destinations always wait for the owner's OK on each post (TikTok's per-post flow)."""
    if not upload or upload.get("intent") != "make_and_upload":
        return {}
    ids = upload.get("destinations") or []
    if not isinstance(ids, list) or not ids:
        raise FlowError("Choose at least one account to upload to, or choose Make clips only.")
    accounts = []
    for cid in ids:
        acc = db.get_connection(str(cid))
        if not acc or acc["workspace_id"] != workspace_id:
            raise FlowError("One of the chosen accounts is not in this workspace.")
        if acc["status"] != "connected" or not acc.get("has_tokens"):
            raise FlowError(f"{acc.get('display_name') or 'An account'} is not connected. Reconnect it in Accounts.")
        accounts.append(acc)
    auto = [a["id"] for a in accounts if a["platform"] == "youtube"]
    review = [a["id"] for a in accounts if a["platform"] == "tiktok"]
    if auto:
        if type(upload.get("made_for_kids")) is not bool:
            raise FlowError("Say whether these clips are made for kids (YouTube requires this answer).")
        if upload.get("privacy") not in ("private", "unlisted", "public"):
            raise FlowError("Choose who can watch the YouTube uploads.")
        basis = upload.get("reuse_basis")
        if basis not in REUSE_BASES or upload.get("agreed") is not True:
            raise FlowError("Confirm the reuse statement for this video before uploading its clips.")
    return {"connections": [a["id"] for a in accounts], "auto": auto, "review": review,
            "privacy": upload.get("privacy") or "private", "made_for_kids": upload.get("made_for_kids"),
            "reuse_basis": upload.get("reuse_basis") or "", "statement": REUSE_BASES.get(upload.get("reuse_basis"), ""),
            "accounts": {a["id"]: a["external_id"] for a in accounts}, "requested_at": time.time()}


def prepare(workspace_id: str, *, mode: str, style_id: str = "saved", choices: dict | None = None,
            skills_on: list[str] | None = None, skills_off: list[str] | None = None, upload: dict | None = None,
            title: str = "", reference_id: str = "") -> dict:
    """Validate a Make clips request and freeze its guidance; the same for a file and a link, so a link import can
    never lose the chosen mode, style, skill overrides, destinations or reuse statement."""
    if mode not in REQUEST_MODES:
        raise FlowError("Choose Highlights, Full stories or Story parts.")
    from . import reference

    request_mode, mode = mode, guidance_mode(mode)
    try:
        style = _style(workspace_id, style_id)
        examples = reference.guidance_inputs(workspace_id, mode, reference_id)
    except (styles.StyleError, reference.ReferenceError) as exc:
        raise FlowError(str(exc)) from exc
    request = upload_request(workspace_id, upload)
    enabled = skills.enabled_skills(workspace_id)
    off = set(skills_off or [])
    on = [db.fetch("skills", sid) for sid in skills_on or []]
    on = [s for s in on if s and s["workspace_id"] == workspace_id]
    snapshot = guidance.resolve(mode, project_choices=choices, style=style, project_skills=on,
                                global_skills=[s for s in enabled if s["id"] not in off and s not in on],
                                context={"title": title, "caption_text": ""}, **examples)
    if snapshot["problems"]:
        raise FlowError("; ".join(snapshot["problems"]))
    options = guidance.render_values(snapshot)
    if request_mode in STORY_SPLITS:
        options["story_split"] = STORY_SPLITS[request_mode]
    return {"mode": mode, "request_mode": request_mode, "guidance": snapshot, "destinations": request,
            "options": options}


def remember_mode(workspace_id: str, user_id: str, mode: str) -> None:
    try:
        prefs.set_appearance(workspace_id, user_id, {"clips_mode": mode}, None)  # remembered for the next project
    except prefs.PrefError:
        pass


def attach_source(project_id: str, asset: dict, *, submit: bool = True) -> dict:
    """Give a project its immutable source (a hard link to the asset) and start the clip pipeline."""
    project = db.get_project(project_id)
    if project is None:
        raise FlowError("The project was deleted.")
    pdir = config.projects_dir() / project_id
    src = _link_source(asset, pdir)
    reused = _reuse_analysis(asset["id"], project["workspace_id"], pdir)
    info = {**(project.get("info") or {}), "asset_sha256": asset["sha256"],
            **({"transcript_reused_from": reused} if reused else {})}
    db.update_project(project_id, source_path=str(src), asset_id=asset["id"], info=info)
    if submit:
        worker.submit_project(project_id)
    return db.get_project(project_id)  # type: ignore[return-value]


def create(workspace_id: str, user_id: str, *, asset_id: str, mode: str, style_id: str = "saved",
           choices: dict | None = None, skills_on: list[str] | None = None, skills_off: list[str] | None = None,
           upload: dict | None = None, reference_id: str = "", upload_ids=None) -> dict:
    """A clips project from the owner's video file. `upload_ids`: the owner's uploads of it that the page sent (they
    become this project's, uploads.taken)."""
    if mode not in REQUEST_MODES:
        raise FlowError("Choose Highlights, Full stories or Story parts.")
    try:
        asset = uploads.asset(asset_id, workspace_id)
    except uploads.UploadError as exc:
        raise FlowError(str(exc)) from exc
    if asset["kind"] != "video":
        raise FlowError("Clips are made from a video file.")
    name = Path(asset["filename"]).stem[:120]
    ready = prepare(workspace_id, mode=mode, style_id=style_id, choices=choices, skills_on=skills_on,
                    skills_off=skills_off, upload=upload, title=name, reference_id=reference_id)
    project = db.create_project(name, source_filename=asset["filename"], status="queued", workspace_id=workspace_id,
                                asset_id=asset_id, clip_mode=ready["mode"], guidance=ready["guidance"],
                                destinations=ready["destinations"], options=ready["options"])
    remember_mode(workspace_id, user_id, mode)
    uploads.taken(workspace_id, upload_ids, project["id"], [asset_id])  # the page's uploads of the video
    return attach_source(project["id"], asset)

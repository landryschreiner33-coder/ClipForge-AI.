"""Local, searchable teaching material and narrowly typed, explicitly approved clip preferences.

Uploaded prose is reference data: it is never executed, sent to a model, or parsed as commands. An owner may
separately approve the supported preferences attached to an instruction or example. Those preferences affect
new Autopilot blueprints; examples never enter the real-results learner. Every actual choice keeps a revision
snapshot, so deleting or editing a reference cannot rewrite a clip's explanation.
"""
from __future__ import annotations

import io
import json
import math
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .. import config, db
from ..pipeline.ffmpeg_utils import FFmpegError, NO_WINDOW, ffprobe_bin

DOCUMENTS = (".txt", ".md", ".csv", ".json", ".docx")
VIDEOS = (".mp4", ".mov", ".webm")
MAX_DOCUMENT = 2 * 1024 * 1024
MAX_VIDEO = 64 * 1024 * 1024
MAX_TEXT = 100_000
FEATURES = ("hook", "pacing", "captions", "storytelling")
PREFERENCES = {"caption_style": tuple(config.CAPTION_STYLES), "caption_position": ("bottom", "middle", "top"),
               "pacing": ("safe_cuts", "continuous"), "caption_emphasis": (False, True)}


class Invalid(ValueError):
    pass


class Conflict(Invalid):
    """Another edit replaced the revision this write was prepared from."""


def _text(value: object, maximum: int, label: str) -> str:
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise Invalid(f"{label} must be text of at most {maximum:,} characters")
    return value.strip()


def clean(data: dict) -> dict:
    unknown = set(data) - {"kind", "title", "content", "tags", "features", "preferences", "example_label", "enabled"}
    if unknown:
        raise Invalid("Unsupported fields: " + ", ".join(sorted(unknown)))
    kind = data.get("kind", "reference")
    if kind not in ("reference", "instruction", "example"):
        raise Invalid("Choose reference, instruction, or example")
    title = _text(data.get("title", ""), 160, "Title")
    if not title:
        raise Invalid("Give this knowledge a title")
    content = _text(data.get("content", ""), MAX_TEXT, "Notes")
    tags = data.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 20:
        raise Invalid("Use at most 20 topic tags")
    tags = list(dict.fromkeys(_text(t, 50, "Topic tag").lower() for t in tags if t))
    features = data.get("features", {})
    if not isinstance(features, dict) or set(features) - set(FEATURES):
        raise Invalid("Example features may describe hook, pacing, captions, and storytelling")
    features = {k: _text(v, 2000, k.title()) for k, v in features.items() if v}
    preferences = data.get("preferences", {})
    if not isinstance(preferences, dict) or set(preferences) - set(PREFERENCES):
        raise Invalid("Only the listed caption and pacing preferences are supported")
    for key, value in preferences.items():
        if value not in PREFERENCES[key] or (key == "caption_emphasis" and type(value) is not bool):
            raise Invalid(f"Unsupported {key} preference")
    label = data.get("example_label", "")
    if kind == "example" and label not in ("good", "bad"):
        raise Invalid("Label the example good or bad")
    if kind != "example" and (label or features):
        raise Invalid("Example labels and features belong to examples")
    if kind == "reference" and preferences:
        raise Invalid("References are searchable only. Choose instruction to approve clip preferences")
    enabled = data.get("enabled", True)
    if type(enabled) is not bool:
        raise Invalid("Enabled must be true or false")
    return {"kind": kind, "title": title, "content": content, "tags": tags, "features": features,
            "preferences": preferences, "example_label": label, "enabled": int(enabled)}


def view(row: dict) -> dict:
    out = {k: v for k, v in row.items() if k != "asset_path"}
    out["enabled"] = bool(row["enabled"])
    out["approved"] = bool(row.get("approved_at"))
    out["has_asset"] = bool(row.get("asset_path"))
    out["state"] = "disabled" if not row["enabled"] else "reference" if row["kind"] == "reference" else \
        "approved" if row.get("approved_at") else "needs_approval"
    return out


def get(knowledge_id: str) -> dict:
    row = db.fetch("brain_knowledge", knowledge_id)
    if not row:
        raise Invalid("That saved knowledge no longer exists")
    return row


def create(data: dict, **asset: object) -> dict:
    # Approval cannot be supplied via import, upload, or JSON creation. It is a separate owner action.
    return view(db.insert("brain_knowledge", {**clean(data), **asset}))


def edit(knowledge_id: str, data: dict) -> dict:
    row = get(knowledge_id)
    combined = {k: row[k] for k in ("kind", "title", "content", "tags", "features", "preferences", "example_label")}
    combined["enabled"] = bool(row["enabled"])
    combined.update(data)
    new = clean(combined)
    if all(new[k] == row[k] for k in new):
        return view(get(knowledge_id))
    changed = any(new[k] != row[k] for k in new if k != "enabled")
    if changed:
        new["approved_at"] = None
    # All edits advance the revision, including enable/disable. Otherwise a delayed content edit could restore
    # a disabled rule, or overwrite another lesson with the same revision an owner has already reviewed.
    new.update(revision=int(row["revision"]) + 1, updated_at=time.time())
    encoded = {key: json.dumps(value) if key in db.JSON_FIELDS["brain_knowledge"] else value
               for key, value in new.items()}
    count = db.execute("UPDATE brain_knowledge SET " + ", ".join(f"{key} = ?" for key in encoded) +
                       " WHERE id = ? AND revision = ?", (*encoded.values(), knowledge_id, row["revision"]))
    if not count:
        raise Conflict("This knowledge changed. Reload and review the current revision before saving your changes")
    return view(get(knowledge_id))


def approve(knowledge_id: str, revision: int) -> dict:
    row = get(knowledge_id)
    if row["kind"] == "reference" or not row["preferences"]:
        raise Invalid("Add a supported clip preference to an instruction or example before approving it")
    if not row["enabled"]:
        raise Invalid("Enable this knowledge before approving it")
    # One atomic revision check prevents a stale approval from approving material edited in another tab.
    count = db.execute("UPDATE brain_knowledge SET approved_at = ?, updated_at = ? WHERE id = ? AND revision = ? "
                       "AND enabled = 1", (time.time(), time.time(), knowledge_id, revision))
    if not count:
        raise Invalid("This knowledge changed. Reload and review the current revision before approving it")
    return view(get(knowledge_id))


def delete(knowledge_id: str) -> None:
    row = get(knowledge_id)
    # Stored paths are derived from generated ids, never from uploaded names or external paths.
    db.execute("DELETE FROM brain_knowledge WHERE id = ?", (knowledge_id,))
    if row["asset_path"]:
        shutil.rmtree(config.data_dir() / "brain" / "knowledge" / knowledge_id, ignore_errors=True)


def search(query: str = "", kind: str = "", *, limit: int | None = 500) -> list[dict]:
    if kind and kind not in ("reference", "instruction", "example"):
        raise Invalid("Unknown knowledge kind")
    where, args = [], []
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if query.strip():
        # Literal substring search, with bound values (percent/underscore are not user wildcard syntax).
        escaped = query.strip()[:200].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\' "
                     "OR features LIKE ? ESCAPE '\\')")
        args.extend([f"%{escaped}%"] * 4)
    return [view(r) for r in db.select("brain_knowledge", " AND ".join(where), args, "updated_at DESC", limit)]


def document_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in DOCUMENTS:
        raise Invalid("Supported documents: TXT, Markdown, CSV, JSON, and DOCX (no macros)")
    if not data or len(data) > MAX_DOCUMENT:
        raise Invalid("Documents must be nonempty and at most 2 MB")
    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 512 or sum(e.file_size for e in entries) > 8 * 1024 * 1024 or any(
                    e.flag_bits & 1 or "vba" in e.filename.lower() or ".." in Path(e.filename).parts for e in entries
                ):
                    raise Invalid("DOCX contains unsupported macros, encryption, or oversized content")
                raw = archive.read("word/document.xml")
                if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                    raise Invalid("DOCX entities and external document types are unsupported")
                root = ElementTree.fromstring(raw)
                text = "\n".join("".join(p.itertext()) for p in root.iter(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"))
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError):
            raise Invalid("That file is not a supported DOCX document") from None
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise Invalid("Save text documents using UTF-8 encoding") from None
    if ext == ".json":
        try:
            json.loads(text)
        except (ValueError, RecursionError):
            raise Invalid("That JSON document is invalid") from None
    text = _text(text, MAX_TEXT, "Extracted document")
    if not text:
        raise Invalid("No searchable text was found in the document")
    return text


def probe_example(path: Path) -> dict:
    """Read a bounded, local media container. Nested playlists and remote protocols are never allowed."""
    try:
        result = subprocess.run([ffprobe_bin(), "-v", "error", "-protocol_whitelist", "file", "-format_whitelist",
                                 "mov,matroska,webm", "-show_format", "-show_streams", "-of", "json", str(path)],
                                capture_output=True, timeout=15, creationflags=NO_WINDOW)
        data = json.loads(result.stdout) if result.returncode == 0 else {}
    except (FFmpegError, OSError, subprocess.TimeoutExpired, ValueError):
        raise Invalid("Could not read this example. Use a playable MP4, MOV, or WebM clip and installed FFmpeg") \
            from None
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and not
                  s.get("disposition", {}).get("attached_pic")), None)
    duration = float((data.get("format") or {}).get("duration") or 0)
    if not video or not math.isfinite(duration) or not 0 < duration <= 600:
        raise Invalid("Examples must contain a video stream and be at most 10 minutes long")
    return {"duration_s": round(duration, 3), "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0), "has_audio": any(s.get("codec_type") == "audio" for s in streams),
            "provenance": "Local ffprobe measurement"}


def asset_file(knowledge_id: str) -> tuple[Path, dict]:
    row = get(knowledge_id)
    path = Path(row["asset_path"]).resolve() if row["asset_path"] else Path()
    directory = (config.data_dir() / "brain" / "knowledge" / knowledge_id).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise Invalid("The original uploaded file is missing")
    return path, row


def choose(clip: dict, options: dict, settings: dict) -> tuple[dict, list[dict]]:
    """Approved preferences only. Topic tags scope a rule; instructions win over examples, then newest approval.

    Labels alone do not infer a rule from a video: a bad example uses the owner's corrective preferences.
    The return records actual changes, rather than claiming every search result influenced the decision.
    """
    if settings.get("brain_paused"):
        return options, []
    haystack = " ".join(str(clip.get(k) or "") for k in ("title", "hook", "caption_text", "category")).lower()
    candidates = db.select("brain_knowledge", "enabled = 1 AND approved_at IS NOT NULL AND kind != 'reference'", (),
                           "CASE kind WHEN 'instruction' THEN 0 ELSE 1 END, approved_at DESC, id")
    out, owners = dict(options), {}
    for row in candidates:
        if row["tags"] and not any(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", haystack) for t in row["tags"]):
            continue
        for key, value in row["preferences"].items():
            if key not in owners:
                owners[key] = row
                out[key] = value
    influenced = {}
    for key, row in owners.items():
        before = options.get(key, "safe_cuts" if key == "pacing" else None)
        if before == out[key]:
            continue
        item = influenced.setdefault(row["id"], {"knowledge_id": row["id"], "revision": row["revision"],
             "snapshot": {k: row[k] for k in ("title", "kind", "example_label", "preferences", "features", "tags")},
             "decisions": {}})
        item["decisions"][key] = {"before": before, "after": out[key]}
    return out, list(influenced.values())


def record(blueprint: dict) -> None:
    for item in (blueprint["blueprint"].get("knowledge") or []):
        # This includes revision snapshots only, never raw uploaded bytes or private filesystem paths.
        db.execute("INSERT OR IGNORE INTO brain_influences "
                   "(id, clip_id, blueprint_id, knowledge_id, revision, snapshot, decisions, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (db.new_id(), blueprint["clip_id"], blueprint["id"], item["knowledge_id"], item["revision"],
                    json.dumps(item["snapshot"]), json.dumps(item["decisions"]), time.time()))


def influences(clip_id: str = "", limit: int | None = 100) -> list[dict]:
    rows = db.select("brain_influences", "clip_id = ?" if clip_id else "", (clip_id,) if clip_id else (),
                     "created_at DESC", limit)
    for row in rows:
        clip = db.get_clip(row["clip_id"]) or {}
        row["clip_title"] = clip.get("title") or "Deleted clip"
        row["knowledge_exists"] = bool(db.fetch("brain_knowledge", row["knowledge_id"]))
    return rows


def export() -> dict:
    # The workspace lists are bounded for browsing; an export must include every saved record.
    return {"schema_version": 1, "exported_at": time.time(), "knowledge": search(limit=None),
            "influences": influences(limit=None),
            "note": "All saved knowledge text, metadata, and influence records, separate from posting results. "
                    "Uploaded files are downloaded separately. "
                    "Approval is local and cannot be restored by importing this JSON. No model fine-tuning."}

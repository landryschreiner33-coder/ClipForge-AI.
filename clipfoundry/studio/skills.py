"""Declarative editing skills: imported text that can set supported editing choices, and nothing else.

A skill file (Markdown, plain text, a Claude-style SKILL.md, or the versioned JSON schema in
docs/clipforge/SKILL_SCHEMA.md) is parsed into three lists shown before it is enabled:
- supported: editing choices from the capability registry, with the line they came from;
- unsupported: instructions ClipForge does not apply (kept and shown, never silently dropped, kept on export);
- blocked: anything asking to run code or commands, reveal or use secrets, change accounts, approve or publish,
  bypass limits, fetch links or reach another workspace. Blocked text is never executed or followed.
Nothing in a skill is ever executed: no scripts, no shell, no network, no tools. Imported text is data.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .. import db
from . import capabilities

SCHEMA_ID = "clipforge.skill/v1"
MAX_BYTES = 200 * 1024
MAX_SKILLS = 100
FORMATS = {".md": "markdown", ".markdown": "markdown", ".txt": "text", ".json": "json"}
EXAMPLE = Path(__file__).with_name("examples") / "story-captions.skill.md"


class SkillError(ValueError):
    pass


BLOCKED = [
    (re.compile(r"\b(run|execute|exec|eval|launch|invoke|call)\b.{0,40}\b(command|script|shell|bash|terminal|python|"
                r"code|program|tool)s?\b"), "asks to run code or commands"),
    (re.compile(r"\b(curl|wget|rm\s+-rf|sudo|chmod|chown|pip\s+install|npm\s+install|powershell|subprocess|"
                r"os\.system)\b"), "contains a shell command"),
    (re.compile(r"\b(api[ _-]?keys?|passwords?|passphrases?|secrets?|access[ _-]?tokens?|refresh[ _-]?tokens?|"
                r"credentials?|cookies?|private keys?)\b"), "mentions secrets or credentials"),
    (re.compile(r"\b(publish|upload|post|schedule)\b.{0,40}\b(to|on|automatically|without|immediately|now|"
                r"youtube|tiktok|public)\b"), "asks to publish or upload"),
    (re.compile(r"\b(connect|disconnect|switch|change|add|remove|use)\b.{0,30}\baccounts?\b"),
     "asks to change accounts"),
    (re.compile(r"\b(approve|approval|consent|permission|authori[sz]e)\b"), "touches approval or permissions"),
    (re.compile(r"\bignore\b.{0,30}\b(previous|prior|above|earlier|all|other|system)\b.{0,20}\b(instructions?|rules?|"
                r"prompts?)\b"), "tries to override ClipForge's rules"),
    (re.compile(r"\b(other|another|every)\s+(users?|workspaces?|owners?)\b"), "reaches beyond this workspace"),
    (re.compile(r"\b(bypass|disable|skip|turn off)\b.{0,30}\b(quota|limit|check|gate|guard|review|safety)s?\b"),
     "asks to bypass a check or limit"),
    (re.compile(r"\b(download|fetch|open|visit|send|post)\b.{0,40}(https?://|www\.|webhook|e-?mail)"),
     "asks to fetch or send data over the network"),
]
CODE_FENCE = re.compile(r"^\s*```\s*([A-Za-z0-9_+-]*)")


def _seconds(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b", text)
    if not m or not re.search(r"\b(length|long|duration|runtime|keep (it|videos?)|target|around|about)\b", text):
        return None
    n, unit = float(m.group(1)), m.group(2)
    return n * (3600 if unit.startswith(("hour", "hr")) else 60 if unit.startswith("min") else 1)


def recognize(line: str) -> dict:
    """The supported editing choices one instruction line states (lower-cased, bullet stripped)."""
    t = line.lower()
    out: dict = {}
    if re.search(r"\bcaptions?\b|\bsubtitles?\b", t):
        if re.search(r"\b(no|without|turn off|disable|skip|hide)\b.{0,12}\b(captions?|subtitles?)\b", t):
            out["captions"] = False
        elif re.search(r"\b(add|burn in|always (use|add|show)|include|turn on|enable|show)\b.{0,8}\b(captions?|"
                       r"subtitles?)\b", t):
            out["captions"] = True
        pos = re.search(r"\b(bottom|lower|low|middle|cent(?:er|re)d?|top|upper)\b", t)
        if pos:
            word = pos.group(1)
            out["caption_position"] = "bottom" if word in ("bottom", "lower", "low") else \
                "top" if word in ("top", "upper") else "middle"
        style = re.search(r"\b(bold|minimal|clean|high[- ]energy)\b", t)
        if style:
            out["caption_style"] = style.group(1).replace("-", "_").replace(" ", "_")
    if re.search(r"\b(highlight|emphasi[sz]e|stress)\b.{0,15}\b(key|important)?\s*words\b", t):
        out["caption_emphasis"] = True
    if re.search(r"\b(calm|storytelling|relaxed|slow[- ]paced|gentle)\b", t) and \
            re.search(r"\b(pac\w*|feel|tone|edit\w*|style|story\w*)\b", t):
        out["feel"] = "calm"
    elif re.search(r"\b(energetic|fast[- ]paced|high[- ]energy|punchy|snappy)\b", t) and "caption" not in t:
        out["feel"] = "energetic"
    elif re.search(r"\bbalanced\b", t):
        out["feel"] = "balanced"
    if re.search(r"\b(cross[- ]?fades?|dissolves?)\b", t):
        out["transition"] = "dissolve"
    elif re.search(r"\bfades? (to|through) black\b", t):
        out["transition"] = "fade"
    elif re.search(r"\b(hard|jump|straight) cuts?\b", t):
        out["transition"] = "cut"
    ratio = re.search(r"\b(16:9|9:16|1:1|4:5)\b", t)
    if ratio:
        out["aspect_ratio"] = ratio.group(1)
    elif re.search(r"\b(widescreen|horizontal|landscape)\b", t):
        out["aspect_ratio"] = "16:9"
    elif re.search(r"\bsquare\b", t):
        out["aspect_ratio"] = "1:1"
    if re.search(r"\bblur(red)? (background|bars|sides)\b|\bfit\b.{0,20}\bframe\b", t):
        out["layout"] = "fit"
    elif re.search(r"\b(fill|crop to fill)\b.{0,10}\bframe\b", t):
        out["layout"] = "fill"
    if re.search(r"\bfollow\b.{0,15}\b(face|speaker|subject)\b", t):
        out["tracking"] = "speaker" if "speaker" in t else "face"
    elif re.search(r"\b(keep|stay)\b.{0,10}\bcent(er|re)d\b|\bcent(er|re) crop\b", t):
        out["tracking"] = "center"
    if re.search(r"\bno\b.{0,12}\bmusic\b|\bwithout music\b", t):
        out["music"] = "none"
    elif re.search(r"\b(use|add|include)\b.{0,15}\b(my|the|supplied|own)\b.{0,15}\bmusic\b", t):
        out["music"] = "supplied"
    if re.search(r"\b(no|skip|without)\b.{0,10}\btitle( card)?\b", t):
        out["title_card"] = False
    elif re.search(r"\b(add|start with|open with|begin with)\b.{0,10}\btitle( card)?\b", t):
        out["title_card"] = True
    if re.search(r"\b(remove|cut|trim)\b.{0,20}\b(filler|weak|dead air|ums?)\b", t):
        out["pacing"] = "safe_cuts"
    elif re.search(r"\b(never cut|keep (it )?continuous|no cuts inside)\b", t):
        out["pacing"] = "continuous"
    seconds = _seconds(t)
    if seconds is not None:
        out["target_duration_s"] = seconds
    return out


def _frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta = {}
    for raw in text[3:end].splitlines():
        key, sep, value = raw.partition(":")
        if sep and key.strip() and re.fullmatch(r"[A-Za-z_][\w-]*", key.strip()):
            meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, text[end + 4:]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "skill"


def parse(filename: str, data: bytes) -> dict:
    """Parse a skill file into its preview. Raises SkillError for files that cannot be a skill at all."""
    ext = Path(filename or "").suffix.lower()
    if Path(filename or "").name != (filename or "") or "/" in (filename or "") or "\\" in (filename or ""):
        raise SkillError("Upload the skill file itself (a name without folders).")
    if ext not in FORMATS:
        raise SkillError("Use a .md, .txt or .json skill file. ZIP files and scripts are not imported.")
    if len(data) > MAX_BYTES:
        raise SkillError(f"A skill file may be at most {MAX_BYTES // 1024} KB.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillError("The skill file is not UTF-8 text.") from exc
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        raise SkillError("The skill file contains control characters; save it as plain text.")
    text = text.lstrip("﻿")
    fmt = FORMATS[ext]
    meta: dict = {}
    explicit: dict = {}
    unsupported: list[dict] = []
    if fmt == "json":
        try:
            doc = json.loads(text)
        except ValueError as exc:
            raise SkillError(f"The JSON skill is not valid JSON ({exc.msg}).") from exc
        if not isinstance(doc, dict) or doc.get("schema") != SCHEMA_ID:
            raise SkillError(f'A JSON skill needs "schema": "{SCHEMA_ID}".')
        known = {"schema", "id", "name", "version", "description", "modes", "topics", "preferences", "instructions",
                 "unsupported"}
        for key in sorted(set(doc) - known):
            unsupported.append({"text": f"{key}: {json.dumps(doc[key])[:200]}", "why": "unknown field (kept)"})
        meta = {k: doc.get(k) for k in ("id", "name", "version", "description")}
        modes, topics = doc.get("modes") or [], doc.get("topics") or []
        if not isinstance(modes, list) or not isinstance(topics, list):
            raise SkillError("modes and topics must be lists.")
        meta["modes"], meta["topics"] = modes, topics
        prefs = doc.get("preferences") or {}
        if not isinstance(prefs, dict):
            raise SkillError("preferences must be an object.")
        explicit, problems = capabilities.clean(prefs)
        unsupported += [{"text": p, "why": "not an editing choice ClipForge applies"} for p in problems]
        unsupported += [u for u in doc.get("unsupported") or [] if isinstance(u, dict) and "text" in u]
        body = doc.get("instructions") or ""
        if not isinstance(body, str):
            raise SkillError("instructions must be text.")
    else:
        meta, body = _frontmatter(text)
        meta.setdefault("modes", [])
        meta.setdefault("topics", [])
    supported: dict = dict(explicit)
    sources: dict[str, list] = {k: [{"line": "preferences", "value": v}] for k, v in explicit.items()}
    blocked: list[dict] = []
    in_code, code_lang, code_lines = False, "", []
    for raw in body.splitlines():
        fence = CODE_FENCE.match(raw)
        if fence:
            if in_code:
                blocked.append({"text": f"Code block ({code_lang or 'no language'}, {len(code_lines)} lines)",
                                "why": "code is never executed"})
                in_code, code_lines = False, []
            else:
                in_code, code_lang = True, fence.group(1)
            continue
        if in_code:
            code_lines.append(raw)
            continue
        line = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", raw).strip()
        if not line or line.startswith("#") or len(line) < 3:
            continue
        low = line.lower()
        why = next((w for pattern, w in BLOCKED if pattern.search(low)), None)
        if why:
            blocked.append({"text": line[:300], "why": why})
            continue
        found = recognize(line)
        if found:
            for k, v in found.items():
                sources.setdefault(k, []).append({"line": line[:300], "value": v})
            continue
        if re.search(r"https?://", low):
            unsupported.append({"text": line[:300], "why": "links are kept as text and never fetched"})
        elif len(line.split()) >= 3:
            unsupported.append({"text": line[:300], "why": "not an editing choice ClipForge applies yet"})
    if in_code:
        blocked.append({"text": f"Unclosed code block ({code_lang or 'no language'})", "why": "code is never executed"})
    for key, said in sources.items():
        values = {json.dumps(s["value"]) for s in said}
        if len(values) > 1:
            supported.pop(key, None)
            unsupported.append({"text": "; ".join(f"“{s['line']}”" for s in said),
                                "why": f"contradictory {capabilities.FIELDS[key].label.lower()} instructions: none "
                                       "applied"})
        else:
            supported[key] = said[0]["value"]
    clean, problems = capabilities.clean(supported)
    unsupported += [{"text": p, "why": "invalid value"} for p in problems]
    modes = [m for m in meta.get("modes") or [] if m in capabilities.MODES] or list(capabilities.MODES)
    name = str(meta.get("name") or Path(filename).stem)[:80].strip() or "Imported skill"
    return {"skill_key": _slug(str(meta.get("id") or name)), "name": name,
            "description": str(meta.get("description") or "")[:300], "version": str(meta.get("version") or "1")[:20],
            "modes": modes, "topics": [str(t)[:40] for t in meta.get("topics") or []][:20],
            "original": text, "original_format": fmt, "supported": clean,
            "effects": [capabilities.FIELDS[k].describe(v) for k, v in clean.items()],
            "unsupported": unsupported[:200], "blocked": blocked[:200]}


def view(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "skill_key", "name", "description", "version", "revision", "modes", "topics",
                                    "supported", "unsupported", "blocked", "original_format", "origin",
                                    "updated_at")} | {
        "enabled": bool(row.get("enabled")),
        "effects": [capabilities.FIELDS[k].describe(v) for k, v in (row.get("supported") or {}).items()
                    if k in capabilities.FIELDS]}


def save(workspace_id: str, filename: str, data: bytes) -> dict:
    """Store an imported skill switched off (its preview is shown; enabling is the owner's explicit step). The same
    skill ID imported again becomes a new revision of that skill."""
    parsed = parse(filename, data)
    existing = db.select("skills", "workspace_id = ? AND skill_key = ?", (workspace_id, parsed["skill_key"]))
    fields = {k: parsed[k] for k in ("name", "description", "version", "modes", "topics", "original",
                                     "original_format", "supported", "unsupported", "blocked")}
    if existing:
        db.update("skills", existing[0]["id"], revision=existing[0]["revision"] + 1, enabled=0,
                  origin=filename[:200], **fields)
        return view(db.fetch("skills", existing[0]["id"]))  # type: ignore[arg-type]
    if (db.scalar("SELECT COUNT(*) FROM skills WHERE workspace_id = ?", (workspace_id,)) or 0) >= MAX_SKILLS:
        raise SkillError(f"A workspace can hold at most {MAX_SKILLS} skills; delete one first.")
    row = db.insert("skills", {"id": "sk-" + _slug(parsed["skill_key"])[:20] + "-" + str(int(time.time() * 1000))[-6:],
                               "workspace_id": workspace_id, "skill_key": parsed["skill_key"], "enabled": 0,
                               "origin": filename[:200], **fields})
    return view(row)


def edit(skill_id: str, text: str) -> dict:
    row = db.fetch("skills", skill_id)
    if not row:
        raise SkillError("Skill not found.")
    ext = {"markdown": ".md", "text": ".txt", "json": ".json"}[row["original_format"]]
    parsed = parse(f"edited{ext}", text.encode("utf-8"))
    db.update("skills", skill_id, revision=row["revision"] + 1, **{
        k: parsed[k] for k in ("description", "version", "modes", "topics", "original", "supported", "unsupported",
                               "blocked")})
    return view(db.fetch("skills", skill_id))  # type: ignore[arg-type]


def export(row: dict) -> dict:
    """The versioned JSON form of a skill; unsupported and refused text stays listed, nothing disappears."""
    body = row["original"]
    if row["original_format"] == "json":
        try:
            body = json.loads(body).get("instructions") or ""
        except ValueError:
            pass
    return {"schema": SCHEMA_ID, "id": row["skill_key"], "name": row["name"], "version": row["version"],
            "description": row["description"], "modes": row["modes"], "topics": row["topics"],
            "preferences": row["supported"], "instructions": body,
            "unsupported": row["unsupported"] + [{"text": b["text"], "why": "refused: " + b["why"]}
                                                 for b in row["blocked"]]}


def enabled_skills(workspace_id: str) -> list[dict]:
    return db.select("skills", "workspace_id = ? AND enabled = 1", (workspace_id,), "name, id")

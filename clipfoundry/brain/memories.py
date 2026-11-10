"""ClipForge AI's memories: the one door to what it remembers (docs/clipforge/CLIPFORGE_AI.md).

A memory is plain words with what a model needs to use it well: its kind (a standing rule, a fact, an episode of
what happened, an asset, an answer), where it came from (you said it, it watched what you did, it guessed, a brain
file), how sure it is, where it applies (every video, one video, one platform, one mode), and its meaning as numbers
(meaning.py). `recall` picks the few memories that fit a question within a model's budget, rules first;
`record_use` keeps track of which answers used which memories, so every answer can explain itself and the Brain
page can show what a memory did. Nothing here ever runs anything: memories are data for a prompt.
"""
from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field

import numpy as np

from .. import db
from ..pipeline.text_utils import tokens
from . import meaning

log = logging.getLogger("clipfoundry.brain")

FORMAT = "clipforge.brain-memories/v1"
KINDS = ("rule", "fact", "episode", "asset", "answer")
SOURCES = ("said", "did", "guessed", "imported")
CONFIDENCE = {"said": 1.0, "imported": 0.7, "did": 0.8, "guessed": 0.5}
RANK = {"said": 3, "imported": 2, "did": 1, "guessed": 0}      # the stronger source wins when twins merge
BOOST = {"said": 0.15, "did": 0.05, "guessed": -0.10, "imported": 0.0}
MODES = ("clips", "video")
WHERE = ("change_request", "filmcraft", "smart_edit", "chat", "guidance", "short_script",
         "agent")  # agent: a helper agent's job
MAX_TEXT = 600
MAX_TAGS = 12
MAX_RULES = 8
MIN_SCORE = 0.2
MIN_MEANING = 0.15              # a memory needs a word in common or this much meaning in common: boosts alone never
DUPLICATE = 0.92
GUESS_DAYS = 60                 # a guess expires unless confirmed
STALE_DAYS = 90                 # an unused guess is reported by the brain check
RECENT_S = 30 * 86400
CHECK_ROWS = 4000               # the duplicate check compares at most this many memories of one kind
MAX_IMPORT = 20000
HEADER = "What the owner has told ClipForge AI (standing rules first; follow them):"


class Invalid(ValueError):
    status = 422

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


_WORDS = re.compile(r"(?:[^\W_]|')+")


def _norm(text: object) -> str:
    """The words of a memory, lower-cased and single-spaced, in any language (the letters and digits of every script;
    punctuation and spacing ignored): two memories with the same norm say the same thing. Text without a letter or a
    digit (only emoji) keeps itself. For words made of a-z, 0-9 and apostrophes it is the norm stored before Nov 9 2026
    (`_legacy_norm`)."""
    t = str(text or "").lower().replace("’", "'")
    return " ".join(_WORDS.findall(t)) or " ".join(t.split())


def _legacy_norm(text: object) -> str:
    """The norm stored before Nov 9 2026: a-z and 0-9 words only, so every memory in another script stored ''."""
    return " ".join(tokens(str(text or "")))


def _same_words(ws: str, kind: str, text: object, *, other_than: str = "") -> dict | None:
    """The oldest memory of this kind in the workspace that says the same words as `text` (`_norm`), or None. A norm
    stored before Nov 9 2026 is found too and compared again by its text: those were the same for every memory in
    another script."""
    norm = _norm(text)
    keys = sorted({norm, _legacy_norm(text)})
    where = f"workspace_id = ? AND kind = ? AND norm IN ({', '.join('?' for _ in keys)})"
    params: tuple = (ws, kind, *keys)
    if other_than:
        where, params = where + " AND id != ?", (*params, other_than)
    for row in db.select("brain_memories", where, params, "created_at ASC"):
        if _norm(row["text"]) == norm:
            return row
    return None


def _clean(text: object, what: str = "remember") -> str:
    out = " ".join(str(text or "").split())
    if not out:
        raise Invalid(f"Say what to {what}.")
    if len(out) > MAX_TEXT:
        raise Invalid(f"Keep a memory under {MAX_TEXT} characters.")
    return out


def _scope(scope: str | None, project_id: str, platform: str, mode: str) -> str:
    if scope:
        s = str(scope).strip()
        kind, _, value = s.partition(":")
        if s == "all" or (kind in ("project", "platform", "mode") and value and len(s) <= 80
                          and (kind != "mode" or value in MODES)):
            return s
        raise Invalid("A memory applies to all, project:<id>, platform:<name> or mode:<clips|video>.")
    if project_id:
        return f"project:{project_id}"
    if platform:
        return f"platform:{platform}"
    if mode:
        if mode not in MODES:
            raise Invalid("The mode is clips or video.")
        return f"mode:{mode}"
    return "all"


def _tags(tags: object) -> list[str]:
    if not isinstance(tags, (list, tuple)):
        return []
    out = []
    for t in tags[:MAX_TAGS]:
        s = " ".join(str(t).split())[:40]
        if s and s not in out:
            out.append(s)
    return out


def view(row: dict) -> dict:
    """A memory for the API: no vector, no normalised words."""
    out = {k: v for k, v in row.items() if k not in ("meaning", "norm")}
    out["expired"] = bool(row.get("expires_at") and row["expires_at"] <= time.time())
    out["has_meaning"] = bool(row.get("meaning")) and row.get("meaning_model") == meaning.model()
    return out


# ------------------------------------------------------------------ writing
def remember(ws: str, text: object, *, kind: str = "fact", source: str = "said", scope: str | None = None,
             project_id: str = "", platform: str = "", mode: str = "", tags: object = (), data: dict | None = None,
             confidence: float | None = None, expires_at: float | None = None) -> dict:
    """Keep a memory. The same words (case and spacing ignored) of the same kind in this workspace update the
    existing memory instead of adding a twin (`twin`): the stronger source and confidence win, the scope widens to
    `all` when the new one says so (otherwise it takes the new scope, its video or platform with it), and a confirmed
    guess no longer expires."""
    if kind not in KINDS:
        raise Invalid(f"A memory is one of: {', '.join(KINDS)}.")
    if source not in SOURCES:
        raise Invalid(f"A memory's source is one of: {', '.join(SOURCES)}.")
    text = _clean(text)
    scope = _scope(scope, project_id, platform, mode)
    if scope.startswith("project:"):
        project_id = scope[8:]
    elif scope.startswith("platform:"):
        platform = scope[9:]
    conf = CONFIDENCE[source] if confidence is None else max(0.0, min(1.0, float(confidence)))
    if source == "guessed" and expires_at is None:
        expires_at = time.time() + GUESS_DAYS * 86400
    norm = _norm(text)
    old = twin(ws, text, kind)
    if old:
        stronger = source if RANK[source] >= RANK[old["source"]] else old["source"]
        fields = {"text": text if RANK[source] >= RANK[old["source"]] else old["text"], "source": stronger,
                  "confidence": max(conf, float(old.get("confidence") or 0)),
                  "scope": "all" if scope == "all" or old["scope"] == "all" else scope,
                  "tags": _tags(list(old.get("tags") or []) + list(_tags(tags))),
                  "data": {**(old.get("data") or {}), **(data or {})}, "enabled": 1,
                  "expires_at": None if stronger != "guessed" else (old.get("expires_at") or expires_at),
                  "revision": int(old.get("revision") or 1) + 1}
        merged = fields["scope"]  # the video or platform it is kept for always follows its scope
        fields["project_id"] = merged[8:] if merged.startswith("project:") else ""
        fields["platform"] = merged[9:] if merged.startswith("platform:") else ""
        if fields["text"] != old["text"] or old.get("meaning_model") != meaning.model():
            fields["meaning"], fields["meaning_model"] = meaning.make(fields["text"])
        db.update("brain_memories", old["id"], **fields)
        return db.fetch("brain_memories", old["id"])
    vec, vec_model = meaning.make(text)
    row = {"workspace_id": ws, "kind": kind, "text": text, "norm": norm, "source": source, "confidence": conf,
           "scope": scope, "project_id": project_id if scope.startswith("project:") else "",
           "platform": platform if scope.startswith("platform:") else "", "tags": _tags(tags), "data": data or {},
           "meaning": vec, "meaning_model": vec_model, "enabled": 1,
           "expires_at": expires_at, "revision": 1}
    return db.insert("brain_memories", row)


def twin(ws: str, text: object, kind: str | tuple[str, ...]) -> dict | None:
    """The memory of this workspace that already says `text` (the same words, case and spacing ignored) as this kind
    (or as one of these kinds, the first found first), or None: with one kind, the one `remember` updates instead of
    adding a twin."""
    for k in (kind,) if isinstance(kind, str) else kind:
        row = _same_words(ws, k, text)
        if row:
            return row
    return None


def episode(ws: str, text: object, *, project_id: str = "", platform: str = "", data: dict | None = None,
            source: str = "did") -> dict:
    """What happened, in one line, remembered for the video it happened in."""
    return remember(ws, text, kind="episode", source=source, project_id=project_id, platform=platform, data=data)


def get(ws: str, memory_id: str) -> dict:
    row = db.fetch("brain_memories", memory_id)
    if not row or row["workspace_id"] != ws:
        raise Invalid("Memory not found.", 404)
    return row


def edit(ws: str, memory_id: str, *, text: object = None, kind: str | None = None, scope: str | None = None,
         tags: object = None, enabled: bool | None = None) -> dict:
    row = get(ws, memory_id)
    fields: dict = {}
    if text is not None:
        new = _clean(text)
        if new != row["text"]:
            vec, vec_model = meaning.make(new)
            fields.update(text=new, norm=_norm(new), meaning=vec, meaning_model=vec_model)
    if kind is not None:
        if kind not in KINDS:
            raise Invalid(f"A memory is one of: {', '.join(KINDS)}.")
        fields["kind"] = kind
    if scope is not None:
        s = _scope(scope, "", "", "")
        fields.update(scope=s, project_id=s[8:] if s.startswith("project:") else "",
                      platform=s[9:] if s.startswith("platform:") else "")
    if tags is not None:
        fields["tags"] = _tags(tags)
    if enabled is not None:
        fields["enabled"] = 1 if enabled else 0
    if not fields:
        return row
    if "norm" in fields or "kind" in fields:
        if _same_words(ws, fields.get("kind", row["kind"]), fields.get("text", row["text"]), other_than=memory_id):
            raise Invalid("Another memory already says that.", 409)
    fields["revision"] = int(row.get("revision") or 1) + 1
    db.update("brain_memories", memory_id, **fields)
    return db.fetch("brain_memories", memory_id)


def confirm(ws: str, memory_id: str) -> dict:
    """A guess you agree with becomes something you said: full confidence, no expiry."""
    row = get(ws, memory_id)
    db.update("brain_memories", memory_id, source="said", confidence=1.0, expires_at=None, enabled=1,
              revision=int(row.get("revision") or 1) + 1)
    return db.fetch("brain_memories", memory_id)


def forget(ws: str, memory_id: str) -> dict:
    """Delete a memory and the record of where it was used; an answer that used it keeps its own copy."""
    row = get(ws, memory_id)
    db.execute("DELETE FROM brain_memory_uses WHERE memory_id = ?", (memory_id,))
    db.execute("DELETE FROM brain_memories WHERE id = ?", (memory_id,))
    return view(row)


# ------------------------------------------------------------------ reading
def _query_terms(query: str) -> list[str]:
    return [t for t in meaning.terms(query) if "_" not in t]  # words and stems; pairs are for the vector


def _scores(query: str, rows: list[dict], project_id: str = "") -> list[tuple[float, float, float]]:
    """(score, words, meaning) per row: the share of the question's words found in the memory, weighted by how
    rare each word is in this brain, blended with the cosine of the meanings, plus the source and recency boosts."""
    q_terms = set(_query_terms(query))
    which = meaning.model()
    q_vec = meaning.embed(query, which)
    now = time.time()
    docs = [set(_query_terms(r["text"])) for r in rows]
    n = len(rows)
    idf = {t: math.log((n + 1) / (sum(1 for d in docs if t in d) + 1)) + 1.0 for t in q_terms}
    total = sum(idf.values()) or 1.0
    out = []
    for r, d in zip(rows, docs):
        words = sum(idf[t] for t in q_terms if t in d) / total if q_terms else 0.0
        vec = meaning.unpack(r.get("meaning")) if r.get("meaning_model") == which else None
        sim = max(0.0, meaning.cosine(q_vec, vec))
        score = 0.55 * words + 0.45 * sim + BOOST.get(r["source"], 0.0)
        if project_id and r.get("project_id") == project_id:
            score += 0.10
        if max(r.get("last_used_at") or 0, r.get("created_at") or 0) > now - RECENT_S:
            score += 0.05
        out.append((score, words, sim))
    return out


def _in_scope(row: dict, project_id: str, platform: str, mode: str) -> bool:
    s = row.get("scope") or "all"
    return s == "all" or (bool(project_id) and s == f"project:{project_id}") or \
        (bool(platform) and s == f"platform:{platform}") or (bool(mode) and s == f"mode:{mode}")


def candidates(ws: str, *, project_id: str = "", platform: str = "", mode: str = "",
               kinds: tuple[str, ...] | None = None) -> list[dict]:
    """Enabled, unexpired memories that apply here."""
    rows = db.select("brain_memories", "workspace_id = ? AND enabled = 1 AND (expires_at IS NULL OR expires_at > ?)",
                     (ws, time.time()), "created_at DESC")
    return [r for r in rows if _in_scope(r, project_id, platform, mode) and (not kinds or r["kind"] in kinds)]


@dataclass
class Recall:
    """What a question recalled: the memories in the order a model should read them, and the prompt block."""
    memories: list[dict] = field(default_factory=list)

    @property
    def ids(self) -> list[str]:
        return [m["id"] for m in self.memories]

    @property
    def empty(self) -> bool:
        return not self.memories

    def lines(self) -> list[str]:
        return [f"- [{m['kind']}] {m['text']}" for m in self.memories]

    def prompt(self) -> str:
        return (HEADER + "\n" + "\n".join(self.lines())) if self.memories else ""

    def snapshot(self) -> list[dict]:
        """What an answer keeps about the memories it used, even after one is forgotten."""
        return [{"id": m["id"], "kind": m["kind"], "text": m["text"], "score": round(m.get("score", 0.0), 3)}
                for m in self.memories]


def recall(query: str, ws: str, *, project_id: str = "", platform: str = "", mode: str = "",
           kinds: tuple[str, ...] | None = None, limit: int = 6, budget_chars: int = 1200,
           rules: bool = True) -> Recall:
    """The few memories a model should read for `query`: every rule that applies (the most relevant first, at most
    MAX_RULES), then the best other memories with a score of at least MIN_SCORE, cut to `limit` memories and
    `budget_chars` characters of memory lines (rules are never cut before facts)."""
    rows = candidates(ws, project_id=project_id, platform=platform, mode=mode, kinds=kinds)
    if not rows:
        return Recall()
    scores = _scores(query or "", rows, project_id)
    scored = [{**view(r), "score": round(s[0], 4), "words": round(s[1], 3), "meaning": round(s[2], 3)}
              for r, s in zip(rows, scores)]
    chosen: list[dict] = []
    if rules:
        standing = [m for m in scored if m["kind"] == "rule"]
        standing.sort(key=lambda m: (-m["score"], -float(m.get("confidence") or 0), -m["created_at"]))
        chosen += standing[:MAX_RULES]
    others = [m for m in scored if m["kind"] != "rule" or not rules]
    floor = meaning.min_similar()
    others = [m for m in others if m["score"] >= MIN_SCORE and (m["words"] > 0 or m["meaning"] >= floor)]
    others.sort(key=lambda m: (-m["score"], -m["created_at"]))
    chosen += others[:max(0, limit)]
    out, used = [], 0
    for m in chosen:
        line = len(f"- [{m['kind']}] {m['text']}") + 1
        if used + line > budget_chars and out:
            if m["kind"] == "rule":
                continue
            break
        out.append(m)
        used += line
    return Recall(out)


def record_use(ws: str, memory_ids: list[str], where: str, ref_id: str = "") -> int:
    """An answer used these memories: remember where, and count it on each memory."""
    if where not in WHERE:
        raise Invalid("Unknown place of use.")
    now = time.time()
    n = 0
    for mid in dict.fromkeys(memory_ids):
        if not mid:
            continue
        db.insert("brain_memory_uses", {"memory_id": mid, "workspace_id": ws, "where_used": where,
                                        "ref_id": ref_id or "", "created_at": now})
        n += db.execute("UPDATE brain_memories SET used_count = used_count + 1, last_used_at = ? WHERE id = ? AND "
                        "workspace_id = ?", (now, mid, ws))
    return n


def uses(ws: str, memory_id: str, limit: int = 50) -> list[dict]:
    get(ws, memory_id)
    return db.select("brain_memory_uses", "memory_id = ?", (memory_id,), "created_at DESC", limit)


def list_(ws: str, q: str = "", kind: str = "", project_id: str = "", limit: int = 200) -> list[dict]:
    """Every memory, newest first; with `q`, the ones that match it, best first, each with its score."""
    where, args = ["workspace_id = ?"], [ws]
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if project_id:
        where.append("(project_id = ? OR scope = 'all')")
        args.append(project_id)
    rows = db.select("brain_memories", " AND ".join(where), args, "created_at DESC")
    if not q.strip():
        return [view(r) for r in rows[:max(1, min(int(limit), 1000))]]
    floor = meaning.min_similar()
    scored = [(s[0], r) for r, s in zip(rows, _scores(q, rows, project_id)) if s[1] > 0 or s[2] >= floor]
    scored.sort(key=lambda x: (-x[0], -x[1]["created_at"]))
    return [{**view(r), "score": round(s, 4)} for s, r in scored[:max(1, min(int(limit), 1000))]]


# ------------------------------------------------------------------ health
def check(ws: str) -> dict:
    """How the brain is doing: counts, memories without a meaning or with an old embedder, near-duplicates, stale
    guesses, expired memories, size. `ok` is False when anything needs Tidy or Rebuild."""
    rows = db.select("brain_memories", "workspace_id = ?", (ws,), "created_at DESC")
    now = time.time()
    counts = {k: 0 for k in KINDS}
    sources = {s: 0 for s in SOURCES}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        sources[r["source"]] = sources.get(r["source"], 0) + 1
    missing = [r["id"] for r in rows if not r.get("meaning")]
    which = meaning.model()
    old = [r["id"] for r in rows if r.get("meaning") and r.get("meaning_model") != which]
    expired = [r["id"] for r in rows if r.get("expires_at") and r["expires_at"] <= now]
    stale = [r["id"] for r in rows if r["source"] == "guessed" and r.get("enabled") and
             max(r.get("last_used_at") or 0, r["created_at"]) < now - STALE_DAYS * 86400]
    pairs: list[list[str]] = []
    truncated = False
    for kind in KINDS:
        same = [r for r in rows if r["kind"] == kind and r.get("enabled") and r.get("meaning_model") == which
                and r.get("meaning")]
        if len(same) > CHECK_ROWS:
            same, truncated = same[:CHECK_ROWS], True
        if len(same) < 2:
            continue
        m = np.stack([meaning.unpack(r["meaning"]) for r in same])
        sim = m @ m.T
        for i in range(len(same)):
            for j in range(i + 1, len(same)):
                if sim[i, j] >= DUPLICATE and len(pairs) < 200:
                    pairs.append([same[i]["id"], same[j]["id"]])
    problems = []
    for code, ids, text in (
            ("missing_meaning", missing, "memories have no meaning yet (Rebuild makes it)"),
            ("old_meaning", old, "memories were embedded by an older embedder (Rebuild updates them)"),
            ("duplicates", [p[0] for p in pairs], "memories look like twins (review them; Tidy merges exact twins)"),
            ("stale_guesses", stale, f"guesses were not used for {STALE_DAYS} days (confirm or forget them)"),
            ("expired", expired, "memories have expired (Tidy removes them)")):
        if ids:
            problems.append({"code": code, "count": len(ids), "text": f"{len(ids)} {text}", "ids": ids[:20]})
    size = sum(len(r["text"]) + len(r.get("meaning") or b"") + 200 for r in rows)
    return {"ok": not problems, "total": len(rows), "enabled": sum(1 for r in rows if r.get("enabled")),
            "counts": counts, "sources": sources, "meaning_model": which, "problems": problems,
            "duplicates": pairs[:50], "duplicates_truncated": truncated, "size_bytes": size,
            "uses": int(db.scalar("SELECT COUNT(*) FROM brain_memory_uses WHERE workspace_id = ?", (ws,)) or 0),
            "checked_at": now}


def rebuild(ws: str) -> int:
    """Recompute the meaning of every memory made by another embedder (or none)."""
    n = 0
    which = meaning.model()
    for r in db.select("brain_memories", "workspace_id = ?", (ws,)):
        if r.get("meaning") and r.get("meaning_model") == which:
            continue
        vec, vec_model = meaning.make(r["text"])
        db.update("brain_memories", r["id"], meaning=vec, meaning_model=vec_model)
        n += 1
    return n


def tidy(ws: str) -> dict:
    """Remove expired memories and merge exact twins (the same words and kind), keeping the stronger one."""
    now = time.time()
    expired = db.select("brain_memories", "workspace_id = ? AND expires_at IS NOT NULL AND expires_at <= ?",
                        (ws, now))
    for r in expired:
        db.execute("DELETE FROM brain_memory_uses WHERE memory_id = ?", (r["id"],))
        db.execute("DELETE FROM brain_memories WHERE id = ?", (r["id"],))
    merged = 0
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in db.select("brain_memories", "workspace_id = ?", (ws,), "created_at ASC"):
        norm = _norm(r["text"])
        if norm != r["norm"]:  # stored before Nov 9 2026, when every memory in another script had the same norm
            db.execute("UPDATE brain_memories SET norm = ? WHERE id = ?", (norm, r["id"]))
        groups.setdefault((r["kind"], norm), []).append(r)
    for twins in groups.values():
        if len(twins) < 2:
            continue
        twins.sort(key=lambda r: (-RANK[r["source"]], -float(r.get("confidence") or 0), -int(r.get("revision") or 1)))
        keep, rest = twins[0], twins[1:]
        db.update("brain_memories", keep["id"], used_count=int(keep.get("used_count") or 0) +
                  sum(int(r.get("used_count") or 0) for r in rest),
                  tags=_tags(list(keep.get("tags") or []) + [t for r in rest for t in (r.get("tags") or [])]),
                  revision=int(keep.get("revision") or 1) + 1)
        for r in rest:
            db.execute("UPDATE brain_memory_uses SET memory_id = ? WHERE memory_id = ?", (keep["id"], r["id"]))
            db.execute("DELETE FROM brain_memories WHERE id = ?", (r["id"],))
            merged += 1
    return {"expired": len(expired), "merged": merged}


# ------------------------------------------------------------------ files
EXPORT_FIELDS = ("id", "kind", "text", "source", "confidence", "scope", "project_id", "platform", "tags", "data",
                 "enabled", "expires_at", "used_count", "last_used_at", "revision", "created_at", "updated_at")


def export(ws: str) -> dict:
    rows = db.select("brain_memories", "workspace_id = ?", (ws,), "created_at ASC")
    return {"format": FORMAT, "exported_at": time.time(), "count": len(rows),
            "memories": [{k: r.get(k) for k in EXPORT_FIELDS} for r in rows]}


def import_(ws: str, data: object) -> dict:
    """Merge a brain file: a memory with a newer revision updates the one with the same id, an unknown id is added
    (with a fresh id when that id belongs to another workspace), the rest are skipped. Nothing is deleted."""
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("memories"), list):
        raise Invalid(f"This is not a ClipForge AI brain file ({FORMAT}).")
    if len(data["memories"]) > MAX_IMPORT:
        raise Invalid(f"A brain file holds at most {MAX_IMPORT} memories.")
    out = {"added": 0, "updated": 0, "skipped": 0, "invalid": 0}
    for m in data["memories"]:
        if not isinstance(m, dict) or m.get("kind") not in KINDS:
            out["invalid"] += 1
            continue
        try:
            text = _clean(m.get("text"))
            scope = _scope(m.get("scope") or "all", "", "", "")
        except Invalid:
            out["invalid"] += 1
            continue
        source = m.get("source") if m.get("source") in SOURCES else "imported"
        vec, vec_model = meaning.make(text)
        fields = {"kind": m["kind"], "text": text, "norm": _norm(text), "source": source,
                  "confidence": max(0.0, min(1.0, float(m.get("confidence") or CONFIDENCE[source]))),
                  "scope": scope, "project_id": scope[8:] if scope.startswith("project:") else "",
                  "platform": scope[9:] if scope.startswith("platform:") else "", "tags": _tags(m.get("tags")),
                  "data": m.get("data") if isinstance(m.get("data"), dict) else {},
                  "enabled": 1 if m.get("enabled", 1) else 0,
                  "expires_at": float(m["expires_at"]) if m.get("expires_at") else None,
                  "revision": max(1, int(m.get("revision") or 1)),
                  "meaning": vec, "meaning_model": vec_model}
        existing = db.fetch("brain_memories", str(m.get("id") or "")) if m.get("id") else None
        if existing and existing["workspace_id"] == ws:
            if fields["revision"] > int(existing.get("revision") or 1):
                db.update("brain_memories", existing["id"], **fields)
                out["updated"] += 1
            else:
                out["skipped"] += 1
            continue
        if _same_words(ws, fields["kind"], text):
            out["skipped"] += 1
            continue
        row = {**fields, "workspace_id": ws, "used_count": int(m.get("used_count") or 0),
               "last_used_at": m.get("last_used_at") or None}
        if m.get("id") and not existing:
            row["id"] = str(m["id"])[:40]
        if m.get("created_at"):
            row["created_at"] = float(m["created_at"])
        db.insert("brain_memories", row)
        out["added"] += 1
    return out

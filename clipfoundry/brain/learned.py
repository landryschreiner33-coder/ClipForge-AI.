"""What ClipForge learns from your edits, and how you see, check, change and undo it (Brain → Learned).

Every edit you save on a clip is an observation (`observe`, called by the clip editor's save, api.patch_clip): where
you moved its start and end compared with where ClipForge put them, how you framed it, which kind of title you
picked, how you styled the captions and how much you cut the pauses. Thumbs up or down on a clip is explicit
feedback: it is a lesson for the clip-choice model too (taste.py).

When at least three clips agree (`infer`), the trend is written down in words as a preference that is only being
tried. It is checked (`evaluate`) on a reusable set: your own edited clips, across their formats (highlights, full
stories, live clips), one left out at a time, comparing what ClipForge did before (its own choice) with what the
trend would have done, against what you did in the end. Only a trend that gets clearly closer to your edits (20% or
more, on at least four clips) is used for new clips; the check's numbers stay with it.

A preference is "explicit" when you set or changed it yourself, "inferred" when it is a trend in your edits. Each one
can be turned off, changed or deleted, and every change to what is in use is a numbered version: rolling back to a
version puts back the preferences (and whether the clip-choice model is used) as they were then. Learning only
touches editing choices; publishing rules, accounts, spending limits and daily targets are never learned.
"""
from __future__ import annotations

import statistics
import time
from collections import Counter

from .. import db

KINDS = ("trim", "framing", "title", "captions", "pacing", "feedback")
FIELDS = {"framing": ("tracking", "crop_x", "layout", "zoom"),
          "captions": ("caption_style", "caption_position", "caption_size", "highlight_words", "captions_enabled"),
          "pacing": ("silence", "speed", "remove_fillers"),
          "trim": ("start_shift", "end_shift"), "title": ("title_kind",)}
KEY_KIND = {k: kind for kind, keys in FIELDS.items() for k in keys}
NUMERIC = {"crop_x", "zoom", "caption_size", "speed", "start_shift", "end_shift"}
SPREAD = {"crop_x": 0.25, "zoom": 0.3, "caption_size": 0.3, "speed": 0.15}   # how far apart agreeing values may be
RENDER_DEFAULTS = {"crop_x": 0.5, "zoom": 1.0, "caption_size": 1.0, "speed": 1.0, "captions_enabled": True}
ONLY_AT_START = {"start_shift", "end_shift", "title_kind"}   # used when a clip is made, not editor values
LABELS = {"tracking": "framing that follows", "crop_x": "the picture's position", "layout": "the layout",
          "zoom": "zoom", "caption_style": "the caption style", "caption_position": "caption position",
          "caption_size": "caption size", "highlight_words": "word-by-word highlight",
          "captions_enabled": "captions", "silence": "pause cutting", "speed": "speed",
          "remove_fillers": "cutting “um” and “uh”", "title_kind": "title", "start_shift": "where clips start",
          "end_shift": "where clips end"}
TITLE_WORDS = {"search": "Searchable", "curiosity": "Curiosity", "moment": "The moment"}
MIN_EVIDENCE = 3      # clips that agree before a trend is written down
AGREE = 0.7           # the share of those clips that must agree
SHIFT_MIN = 0.4       # seconds: a smaller move of a clip's start or end is not a habit
MAX_SHIFT = 3.0       # the most a learned trim moves a new clip
EVAL_MIN = 4          # clips in the check before a trend can be used
PROMOTE = 0.2         # how much closer to your edits the trend must get (20%)
RECENT = 40           # latest edited clips a trend is read from
STATUSES = ("trying", "in_use", "off")


class LearnedError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _set(item_id: str, **fields: object) -> None:
    """Change a preference's columns (one of them is called `value`, which db.update takes as the row's id)."""
    db._update("learned_items", item_id, dict(fields))


def on(settings: dict | None = None) -> bool:
    """Learning from edits is on (Settings: learn_from_edits). Off, nothing is recorded or used."""
    s = settings if settings is not None else db.get_settings()
    return bool(s.get("learn_from_edits", True))


def _ws(clip: dict) -> tuple[str, dict]:
    project = db.get_project(str(clip.get("project_id") or "")) or {}
    return str(project.get("workspace_id") or "local"), project


def _fmt(clip: dict, project: dict) -> str:
    if (project.get("origin") or "") == "live" or (project.get("info") or {}).get("live"):
        return "live"
    if clip.get("category") == "story" or project.get("clip_mode") == "stories":
        return "story"
    return str(project.get("clip_mode") or "highlights")


def _value(edit: dict, project: dict, settings: dict, key: str) -> object:
    """The value a clip has for `key` after your edit: yours, else its video's, else Settings'. A value the clip
    started with because it was learned, and that you left as it was, is not your choice (None: not counted)."""
    if key in (edit.get("learned_keys") or []):
        return None
    for where in (edit, project.get("options") or {}, settings, RENDER_DEFAULTS):
        if where.get(key) is not None:
            return where[key]
    return None


def mine(before_edit: dict, edit: dict) -> dict:
    """The clip editor's save: a value that was learned and that you changed is now yours (it leaves
    learned_keys). Returns the edit to store."""
    keys = [k for k in (edit.get("learned_keys") or []) if edit.get(k) == before_edit.get(k) and k in edit]
    out = {k: v for k, v in edit.items() if k != "learned_keys"}
    if keys:
        out["learned_keys"] = keys
    return out


# ------------------------------------------------------------------ observing your edits
def observe(before: dict, after: dict, settings: dict | None = None) -> list[dict]:
    """Record what an edit of one clip says about your taste (before and after the editor's save). Returns the
    events written; never raises (an edit is saved whatever happens here)."""
    try:
        return _observe(before, after, settings if settings is not None else db.get_settings())
    except Exception:  # noqa: BLE001 - learning must never stop a save
        import logging

        logging.getLogger("clipfoundry.learned").exception("edit not learned")
        return []


def _observe(before: dict, after: dict, settings: dict) -> list[dict]:
    if not on(settings):
        return []
    ws, project = _ws(after)
    fmt = _fmt(after, project)
    be, ae = before.get("edit") or {}, after.get("edit") or {}
    out = []

    def add(kind: str, data: dict) -> None:
        out.append(db.insert("learned_events", {"workspace_id": ws, "clip_id": after["id"],
                                                "project_id": after.get("project_id") or "", "kind": kind,
                                                "fmt": fmt, "data": data}))

    if any(be.get(k) != ae.get(k) for k in ("start", "end")):  # against ClipForge's own pick (the clip's start/end)
        start, end = float(after["start"]), float(after["end"])
        for t in be.get("auto_trims") or []:   # a trim ClipForge made for you is where your own move starts from
            if t.get("side") == "start":
                start = float(t.get("to", start))
            elif t.get("side") == "end":
                end = float(t.get("to", end))
        add("trim", {"start_shift": round(float(ae.get("start", start)) - start, 2),
                     "end_shift": round(float(ae.get("end", end)) - end, 2)})
    for kind in ("framing", "captions", "pacing"):
        keys = FIELDS[kind]
        if any(be.get(k) != ae.get(k) for k in keys):
            add(kind, {k: _value(ae, project, settings, k) for k in keys})
    bp, ap = before.get("post") or {}, after.get("post") or {}
    if ap.get("title") and ap.get("title") != bp.get("title") and ap["title"] in (bp.get("titles") or []):
        from ..pipeline import postpack

        kws = postpack.topics(str(ap.get("clip_text") or ""))
        titles = bp.get("titles") or [""]
        offered = titles[int(bp.get("recommended_title") or 0) % len(titles)]
        add("title", {"title_kind": postpack.title_kind(ap["title"], kws),
                      "base": {"title_kind": postpack.title_kind(offered, kws) if offered else ""}})
    if out:
        infer(ws, settings)
    return out


def feedback(clip_id: str, good: bool, why: str = "") -> dict:
    """Your thumbs up or down on a clip: explicit feedback, and a lesson for the clip-choice model."""
    from .. import taste

    clip = db.get_clip(clip_id)
    if not clip:
        raise LearnedError("That clip is not there any more.", 404)
    ws, project = _ws(clip)
    taste.record(clip, "reselected" if good else "deselected", ws)
    if not on():  # learning from edits is off: the thumbs counts for clip choices only
        return {"id": "", "kind": "feedback"}
    return db.insert("learned_events", {"workspace_id": ws, "clip_id": clip_id, "project_id": clip["project_id"],
                                        "kind": "feedback", "fmt": _fmt(clip, project),
                                        "data": {"good": bool(good), "why": str(why or "")[:300]}})


# ------------------------------------------------------------------ trends
def _latest(ws: str, kind: str) -> list[dict]:
    """The latest event of this kind for each of your most recently edited clips (your final choice there)."""
    seen, out = set(), []
    for e in db.select("learned_events", "workspace_id = ? AND kind = ?", (ws, kind), "created_at DESC", 400):
        if e["clip_id"] in seen:
            continue
        seen.add(e["clip_id"])
        out.append(e)
        if len(out) >= RECENT:
            break
    return out


def _baseline(key: str, settings: dict) -> object:
    if key in ("start_shift", "end_shift"):
        return 0.0
    if key == "title_kind":
        return ""   # the package's own recommendation
    return settings.get(key, RENDER_DEFAULTS.get(key))


def trend(key: str, values: list, settings: dict) -> object | None:
    """The value your edits agree on for one key, or None when they do not agree enough (the rules above)."""
    values = [v for v in values if v is not None]
    if len(values) < MIN_EVIDENCE:
        return None
    if key in ("start_shift", "end_shift"):
        moved = [float(v) for v in values]
        mid = statistics.median(moved)
        same = sum(1 for v in moved if abs(v) >= SHIFT_MIN and (v > 0) == (mid > 0)) / len(moved)
        if abs(mid) < SHIFT_MIN or same < AGREE:
            return None
        return round(max(-MAX_SHIFT, min(MAX_SHIFT, mid)), 1)
    if key in NUMERIC:
        nums = [_num(v) for v in values]
        nums = [v for v in nums if v is not None]
        if len(nums) < MIN_EVIDENCE:
            return None
        mid = statistics.median(nums)
        close = sum(1 for v in nums if abs(v - mid) <= SPREAD.get(key, 0.2)) / len(nums)
        base = _baseline(key, settings)
        if close < AGREE or (isinstance(base, (int, float)) and abs(mid - float(base)) < SPREAD.get(key, 0.2) / 2):
            return None
        return round(mid, 2)
    value, n = Counter(map(_hashable, values)).most_common(1)[0]
    if n / len(values) < AGREE or value == _hashable(_baseline(key, settings)):
        return None
    return value


def _hashable(v: object) -> object:
    return tuple(v) if isinstance(v, list) else v


def _same(key: str, old: object, new: object) -> bool:
    """A trend that moved by less than its values may differ (a quarter of a second for a trim) has not changed."""
    if key in NUMERIC:
        a, b = _num(old), _num(new)
        return a is not None and b is not None and abs(a - b) < SPREAD.get(key, 0.5) / 2
    return _hashable(old) == new


def _num(v: object) -> float | None:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _phrase(key: str, value: object) -> str:
    """What a preference does, in words ("put captions in the middle")."""
    v = str(value).replace("_", " ")
    if key in ("start_shift", "end_shift"):
        side = "start" if key == "start_shift" else "end"
        way = "later" if float(value) > 0 else "earlier"  # type: ignore[arg-type]
        return f"{side} clips about {abs(float(value)):.1f} s {way} than ClipForge picks"  # type: ignore[arg-type]
    if key == "title_kind":
        return f"pick the {TITLE_WORDS.get(str(value), value)} title"
    if key == "crop_x":
        return f"place the picture {round(float(value) * 100)}% from the left"  # type: ignore[arg-type]
    if key == "caption_position":
        return "put captions in the middle" if value == "middle" else f"put captions at the {v}"
    if key in ("zoom", "speed", "caption_size"):
        what = {"zoom": "zoom in to", "speed": "play clips at", "caption_size": "make captions"}[key]
        return f"{what} {float(value):g}× {'the usual size' if key == 'caption_size' else ''}".strip()  # type: ignore
    if isinstance(value, bool):
        return f"turn {LABELS.get(key, key)} {'on' if value else 'off'}"
    noun = {"caption_style": "caption style", "layout": "layout", "tracking": "framing",
            "silence": "pause cutting"}.get(key, LABELS.get(key, key))
    return f"use {'the ' if key in ('caption_style', 'layout') else ''}{v} {noun}"


def _words(key: str, value: object, mine: bool = False) -> str:
    """A trend: "You usually …"; one you set: "Always …"."""
    return ("Always " if mine else "You usually ") + _phrase(key, value)


def infer(ws: str, settings: dict | None = None) -> list[dict]:
    """Write down (or update) the trends your latest edits agree on, check each new or changed one, and use the
    ones the check supports. An item you changed yourself (explicit) is never overwritten by a trend."""
    settings = settings if settings is not None else db.get_settings()
    changed = []
    for kind, keys in FIELDS.items():
        events = _latest(ws, kind)
        for key in keys:
            value = trend(key, [(e.get("data") or {}).get(key) for e in events], settings)
            row = db.select("learned_items", "workspace_id = ? AND key = ? AND source = 'inferred'", (ws, key),
                            limit=1)
            if value is None:
                continue
            evidence = sum(1 for e in events if (e.get("data") or {}).get(key) is not None)
            if row and _same(key, row[0]["value"], value):
                if int(row[0]["evidence"] or 0) != evidence:  # more clips agree: check it again on more clips
                    _set(row[0]["id"], evidence=evidence)
                    item = db.fetch("learned_items", row[0]["id"]) or row[0]
                    changed.append(_check_and_use(ws, item, settings) if item["status"] != "off" else item)
                continue
            fields = {"workspace_id": ws, "key": key, "kind": kind, "source": "inferred",
                      "text": _words(key, value), "value": list(value) if isinstance(value, tuple) else value,
                      "evidence": evidence, "status": "trying"}
            if row and row[0]["status"] == "off":
                continue   # you turned this one off: a new value of it waits until you turn it on
            if row and row[0]["status"] == "in_use":
                # a trend in use moved: the new value is used only if it passes the check too, else the old one stays
                ev = evaluate(ws, {**row[0], **fields}, settings)
                if ev["passed"]:
                    _set(row[0]["id"], **{**fields, "status": "in_use"}, evaluation=ev,
                         version=int(row[0]["version"] or 1) + 1)
                    record_version(ws, f"Updated: {fields['text']} (checked on {ev['n']} clips: {ev['summary']})", ev)
                changed.append(db.fetch("learned_items", row[0]["id"]) or row[0])
                continue
            if row:
                _set(row[0]["id"], **fields, version=int(row[0]["version"] or 1) + 1)
                item = db.fetch("learned_items", row[0]["id"]) or {}
            else:
                item = db.insert("learned_items", fields)
            changed.append(_check_and_use(ws, item, settings))
    return changed


def _check_and_use(ws: str, item: dict, settings: dict) -> dict:
    ev = evaluate(ws, item, settings)
    _set(item["id"], evaluation=ev)
    item = db.fetch("learned_items", item["id"]) or item
    if ev["passed"] and item["status"] != "in_use":
        explicit = db.select("learned_items", "workspace_id = ? AND key = ? AND source = 'explicit' AND status = "
                             "'in_use'", (ws, item["key"]), limit=1)
        if not explicit:  # what you set yourself wins over a trend
            _set(item["id"], status="in_use")
            record_version(ws, f"Started using: {item['text']} (checked on {ev['n']} clips: {ev['summary']})", ev)
            item = db.fetch("learned_items", item["id"]) or item
    return item


def recheck(ws: str, settings: dict | None = None) -> list[dict]:
    """Check every preference again on the clip set as it is now (more edits make a better check); a trend the
    check now supports is used. One in use is never stopped by a check: you turn it off or roll back."""
    settings = settings if settings is not None else db.get_settings()
    out = []
    for item in db.select("learned_items", "workspace_id = ?", (ws,)):
        if item["source"] == "inferred" and item["status"] == "trying":
            out.append(_check_and_use(ws, item, settings))
        else:
            _set(item["id"], evaluation=evaluate(ws, item, settings))
            out.append(db.fetch("learned_items", item["id"]) or item)
    return out


# ------------------------------------------------------------------ the check
def evaluate(ws: str, item: dict, settings: dict | None = None) -> dict:
    """Check a preference on the reusable set (your edited clips of its kind, across formats), one clip left out at
    a time: how far ClipForge's own choice was from your final edit (before) and how far the trend, read from the
    other clips, would have been (after). {n, before, after, unit, by_format, passed, summary, at}."""
    settings = settings if settings is not None else db.get_settings()
    key = item["key"]
    events = [e for e in _latest(ws, KEY_KIND[key]) if (e.get("data") or {}).get(key) is not None]
    values = [_hashable(e["data"][key]) for e in events]
    numeric = key in NUMERIC
    rows = []
    for i, e in enumerate(events):
        actual = values[i]
        base = _hashable(((e.get("data") or {}).get("base") or {}).get(key, _baseline(key, settings)))
        others = values[:i] + values[i + 1:]
        guess = trend(key, list(others), settings) if item["source"] == "inferred" else _hashable(item["value"])
        guess = base if guess is None else guess  # no trend: ClipForge does what it did
        if numeric:
            a, b, g = _num(actual), _num(base), _num(guess)
            if a is None:
                continue
            err_before, err_after = abs(a - (b or 0.0)), abs(a - (g if g is not None else b or 0.0))
        else:
            err_before, err_after = float(actual != _hashable(base)), float(actual != guess)
        rows.append((e.get("fmt") or "highlights", err_before, err_after))
    n = len(rows)
    before = round(sum(r[1] for r in rows) / n, 3) if n else None
    after = round(sum(r[2] for r in rows) / n, 3) if n else None
    by_format = {}
    for fmt in sorted({r[0] for r in rows}):
        part = [r for r in rows if r[0] == fmt]
        by_format[fmt] = {"n": len(part), "before": round(sum(r[1] for r in part) / len(part), 3),
                          "after": round(sum(r[2] for r in part) / len(part), 3)}
    passed = bool(n >= EVAL_MIN and before is not None and after is not None and before > 0
                  and before - after >= PROMOTE * before)
    unit = "s" if key in ("start_shift", "end_shift") else "" if numeric else "share"
    if n == 0:
        summary = "no clips to check yet"
    elif numeric:
        summary = f"off by {before:.2f}{unit} before, {after:.2f}{unit} with it"
    else:
        summary = (f"matched your choice in {round((1 - before) * 100)}% of clips before, "
                   f"{round((1 - after) * 100)}% with it")
    if n and n < EVAL_MIN:
        summary += f"; needs {EVAL_MIN - n} more clip(s) to decide"
    return {"n": n, "before": before, "after": after, "unit": unit, "by_format": by_format, "passed": passed,
            "summary": summary, "at": round(time.time(), 3)}


def taste_check(ws: str, folds: int = 5) -> dict:
    """The clip-choice model (taste.py) checked on your own keep/leave-out choices: fitted on four fifths, tested on
    the fifth left out, five times. Before: guessing the more common choice every time; after: the model's guess.
    {n, before, after, passed, summary}: shares of choices it got right."""
    import json as _json

    from .. import taste

    rows = [r for r in taste.events(ws) if r.get("features")]
    n = len(rows)
    if n < taste.MIN_EVENTS + 3:
        return {"n": n, "before": None, "after": None, "passed": False,
                "summary": f"needs {taste.MIN_EVENTS + 3 - n} more clip choice(s) to check"}
    right_before = right_after = tested = 0
    for k in range(folds):
        test = rows[k::folds]
        train_rows = [r for i, r in enumerate(rows) if i % folds != k]
        m = taste.fit(train_rows, min_events=taste.MIN_EVENTS - 3, min_each=max(2, taste.MIN_EACH - 1))
        if not m:
            continue
        common = sum(1 for r in train_rows if float(r["value"]) > 0) * 2 >= len(train_rows)
        for r in test:
            try:
                x = _json.loads(r["features"])
            except (TypeError, ValueError):
                continue
            kept = float(r["value"]) > 0
            right_before += int(kept == common)
            right_after += int((taste.predict(m, x)["p"] >= 0.5) == kept)
            tested += 1
    if not tested:
        return {"n": n, "before": None, "after": None, "passed": False,
                "summary": "not enough of both choices (kept and left out) to check yet"}
    before, after = round(right_before / tested, 3), round(right_after / tested, 3)
    return {"n": tested, "before": before, "after": after, "passed": after > before,
            "summary": f"guessed {round(before * 100)}% of your choices right without it, {round(after * 100)}% with "
                       f"it (each choice tested while left out)"}


# ------------------------------------------------------------------ what new clips use
def defaults(ws: str, settings: dict | None = None) -> dict:
    """The preferences in use, for new clips: editing choices (a video's own options and your edits of a clip still
    win) plus start_shift, end_shift and title_kind. What you set yourself wins over a trend."""
    if not on(settings):
        return {}
    out: dict = {}
    rows = db.select("learned_items", "workspace_id = ? AND status = 'in_use'", (ws,))
    for row in sorted(rows, key=lambda r: r["source"] == "explicit"):  # explicit last: it wins
        out[row["key"]] = row["value"]
    return out


def shift_bounds(start: float, end: float, words: list[dict], opts: dict) -> tuple[float, float]:
    """A new clip's start and end moved the way you usually move them (at most 3 s, onto a word's edge, never
    shorter than the shortest clip allowed)."""
    a, b = float(opts.get("start_shift") or 0), float(opts.get("end_shift") or 0)
    if not a and not b:
        return start, end
    ns, ne = start + a, end + b
    if a:
        edges = [w["start"] for w in words if abs(w["start"] - ns) <= 0.6]
        ns = min(edges, key=lambda t: abs(t - ns)) if edges else ns
    if b:
        edges = [w["end"] for w in words if abs(w["end"] - ne) <= 0.6]
        ne = min(edges, key=lambda t: abs(t - ne)) if edges else ne
    ns = max(0.0, ns)
    if ne - ns < float(opts.get("min_duration") or 5) or ne <= ns:
        return start, end
    return round(ns, 3), round(ne, 3)


# ------------------------------------------------------------------ seeing, changing and undoing
def view(ws: str) -> dict:
    from .. import taste

    items = db.select("learned_items", "workspace_id = ?", (ws,), "updated_at DESC")
    counts = Counter(e["kind"] for e in db.select("learned_events", "workspace_id = ?", (ws,), limit=5000))
    rules = db.select("brain_memories", "workspace_id = ? AND enabled = 1 AND kind = 'rule'", (ws,))
    return {"on": on(), "explicit": [i for i in items if i["source"] == "explicit"],
            "inferred": [i for i in items if i["source"] == "inferred"], "observed": dict(counts),
            "rules": len(rules), "taste": {**taste.status(ws), "used": use_taste(ws), "check": taste_check(ws)},
            "versions": versions(ws)[:20], "keys": {k: LABELS.get(k, k) for k in KEY_KIND},
            "rules_text": {"min_evidence": MIN_EVIDENCE, "agree": AGREE, "eval_min": EVAL_MIN, "promote": PROMOTE}}


def _item(ws: str, item_id: str) -> dict:
    row = db.fetch("learned_items", item_id)
    if not row or row["workspace_id"] != ws:
        raise LearnedError("That preference is not there any more.", 404)
    return row


def set_status(ws: str, item_id: str, status: str) -> dict:
    """Turn a preference on (in use) or off. Turning one on is your choice: it is used even if its check did not
    decide yet; an explicit one of the same setting is turned off, so only one is in use."""
    if status not in ("in_use", "off"):
        raise LearnedError("Choose on or off.")
    row = _item(ws, item_id)
    if row["status"] == status:
        return row
    if status == "in_use":
        for other in db.select("learned_items", "workspace_id = ? AND key = ? AND id != ? AND status = 'in_use'",
                               (ws, row["key"], item_id)):
            _set(other["id"], status="off")
    _set(item_id, status=status)
    record_version(ws, f"{'Turned on' if status == 'in_use' else 'Turned off'} by you: {row['text']}")
    return db.fetch("learned_items", item_id) or row


def change(ws: str, item_id: str, value: object) -> dict:
    """Change a preference's value. The changed one is yours (explicit) and in use; the trend it came from stays
    listed, turned off, so a later trend never overwrites what you set."""
    from .. import config

    row = _item(ws, item_id)
    key = row["key"]
    value = _clean(key, value, config)
    text = _words(key, value, mine=True)
    if row["source"] == "explicit":
        _set(item_id, value=value, text=text, status="in_use", version=int(row["version"] or 1) + 1)
        saved = db.fetch("learned_items", item_id) or row
    else:
        _set(item_id, status="off")
        mine = db.select("learned_items", "workspace_id = ? AND key = ? AND source = 'explicit'", (ws, key), limit=1)
        fields = {"value": value, "text": text, "status": "in_use", "kind": row["kind"], "evidence": 0}
        if mine:
            _set(mine[0]["id"], **fields, version=int(mine[0]["version"] or 1) + 1)
            saved = db.fetch("learned_items", mine[0]["id"]) or mine[0]
        else:
            saved = db.insert("learned_items", {"workspace_id": ws, "key": key, "source": "explicit", **fields})
    record_version(ws, f"Set by you: {saved['text']}")
    return saved


def _clean(key: str, value: object, config) -> object:
    if key in ("start_shift", "end_shift"):
        try:
            v = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise LearnedError("Give the seconds as a number, like 1.5 or -0.5.") from exc
        return round(max(-MAX_SHIFT, min(MAX_SHIFT, v)), 1)
    if key == "title_kind":
        if value not in TITLE_WORDS:
            raise LearnedError("Choose Searchable, Curiosity or The moment.")
        return value
    choices = {"caption_style": config.CAPTION_STYLES, "caption_position": ("bottom", "middle", "top"),
               "tracking": config.TRACKING_MODES, "layout": config.CLIP_LAYOUTS, "silence": config.SILENCE_MODES}
    if key in choices:
        if value not in choices[key]:
            raise LearnedError(f"That is not a choice for {LABELS.get(key, key)}.")
        return value
    if key in ("highlight_words", "captions_enabled", "remove_fillers"):
        if not isinstance(value, bool):
            raise LearnedError("Choose on or off.")
        return value
    if key in ("caption_size", "speed"):
        v = _num(value)
        if v is None:
            raise LearnedError("Give a number.")
        return round(max(0.5, min(2.0, v)), 2)
    if key in ("crop_x", "zoom"):
        try:
            v = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise LearnedError("Give a number.") from exc
        return round(max(0.0, min(1.0, v)), 2) if key == "crop_x" else round(max(1.0, min(2.5, v)), 2)
    if key == "layout" and value in config.CLIP_LAYOUTS:
        return value
    raise LearnedError(f"That is not a choice for {LABELS.get(key, key)}.")


def remove(ws: str, item_id: str) -> dict:
    row = _item(ws, item_id)
    db.execute("DELETE FROM learned_items WHERE id = ?", (item_id,))
    record_version(ws, f"Deleted: {row['text']}")
    return row


def forget_edits(ws: str) -> dict:
    """Forget the edits ClipForge read (and the trends written from them). What you set yourself stays; the version
    list keeps what was in use, so going back still works."""
    n = db.execute("DELETE FROM learned_events WHERE workspace_id = ?", (ws,))
    m = db.execute("DELETE FROM learned_items WHERE workspace_id = ? AND source = 'inferred'", (ws,))
    record_version(ws, f"Forgot {n} edit(s) and {m} trend(s) (by you)")
    return {"edits": int(n or 0), "trends": int(m or 0)}


def set_on(on_: bool) -> dict:
    """Learning from edits on or off (off: nothing is recorded and nothing learned is used)."""
    db.save_settings({"learn_from_edits": bool(on_)})
    return {"on": on()}


# ------------------------------------------------------------------ versions and rollback
def use_taste(ws: str) -> bool:
    """Whether the clip-choice model (taste.py) moves Clip Scores (a rollback can turn it off and on)."""
    row = db.select("learned_versions", "workspace_id = ?", (ws,), "number DESC", 1)
    items = (row[0].get("items") if row else None) or {}
    return bool(items.get("taste", True)) if isinstance(items, dict) else True


def _snapshot(ws: str, taste: bool | None = None) -> dict:
    """What is in use at a version: the preferences, whether clip choices move Clip Scores, and the rules you told
    ClipForge AI (Brain → Memory), which are the instructions its prompts carry, word for word."""
    rows = db.select("learned_items", "workspace_id = ?", (ws,), "created_at ASC")
    rules = db.select("brain_memories", "workspace_id = ? AND kind = 'rule'", (ws,), "created_at ASC", 500)
    return {"items": [{k: r[k] for k in ("id", "key", "kind", "source", "text", "value", "status", "evidence",
                                         "version")} for r in rows],
            "taste": use_taste(ws) if taste is None else bool(taste),
            "rules": [{"id": r["id"], "text": r["text"], "enabled": bool(r["enabled"]),
                       "revision": int(r["revision"] or 1)} for r in rules]}


def record_version(ws: str, what: str, evaluation: dict | None = None, *, taste: bool | None = None) -> dict:
    number = int(db.scalar("SELECT COALESCE(MAX(number), 0) FROM learned_versions WHERE workspace_id = ?",
                           (ws,)) or 0) + 1
    return db.insert("learned_versions", {"workspace_id": ws, "number": number, "what": what[:300],
                                          "items": _snapshot(ws, taste), "evaluation": evaluation or {}})


def versions(ws: str) -> list[dict]:
    return [{k: v["items"].get(k) if k in ("taste",) else v[k] for k in ("id", "number", "what", "created_at",
                                                                          "evaluation", "taste")}
            | {"in_use": [i["text"] for i in (v.get("items") or {}).get("items", []) if i.get("status") == "in_use"]}
            for v in db.select("learned_versions", "workspace_id = ?", (ws,), "number DESC", 100)]


def set_taste(ws: str, used: bool) -> dict:
    record_version(ws, "Clip choices " + ("used again for Clip Scores" if used else "no longer move Clip Scores")
                   + " (by you)", taste=used)
    return {"used": use_taste(ws)}


def rollback(ws: str, number: int) -> dict:
    """Put the preferences back as they were in version `number` (their values and whether each was in use, the
    clip-choice model on or off); preferences added since are turned off, not deleted. A new version records it."""
    row = db.select("learned_versions", "workspace_id = ? AND number = ?", (ws, int(number)), limit=1)
    if not row:
        raise LearnedError("That version is not there.", 404)
    snap = row[0].get("items") or {}
    kept = {i["id"]: i for i in snap.get("items", [])}
    for item in db.select("learned_items", "workspace_id = ?", (ws,)):
        was = kept.pop(item["id"], None)
        if was is None:
            _set(item["id"], status="off")
        else:
            _set(item["id"], status=was["status"], value=was["value"], text=was["text"])
    for gone in kept.values():  # deleted since: back as it was
        db.insert("learned_items", {"workspace_id": ws, **{k: gone[k] for k in ("id", "key", "kind", "source", "text",
                                                                              "value", "status", "evidence")}})
    changed_rules = _rules_back(ws, snap.get("rules"))
    what = f"Rolled back to version {number}" + (f" ({changed_rules} rule(s) put back)" if changed_rules else "")
    return record_version(ws, what, taste=bool(snap.get("taste", True)))


def _rules_back(ws: str, then: list | None) -> int:
    """Rules (ClipForge AI's prompt instructions) as they were: their words and whether each was on; a rule told
    since is turned off, not forgotten. A version made before rules were kept with versions leaves them alone."""
    if then is None:
        return 0
    from . import memories

    was = {r["id"]: r for r in then}
    n = 0
    for rule in db.select("brain_memories", "workspace_id = ? AND kind = 'rule'", (ws,), limit=500):
        old = was.get(rule["id"])
        text = old["text"] if old and old["text"] != rule["text"] else None
        enabled = bool(old["enabled"]) if old else False
        if text is None and enabled == bool(rule["enabled"]):
            continue
        try:
            memories.edit(ws, rule["id"], text=text, enabled=enabled)
            n += 1
        except memories.Invalid:
            continue
    return n

"""ClipForge AI reads the whole video and ranks the finalists (docs/clipforge/SMARTER_AI.md).

Two passes around the local analysis, both with the same brief every time (the video's title, what makes a clip from
the built-in playbooks, the owner's rules from the brain, the wanted length):

1. Scout. Before the candidates are scored, the model reads the transcript in order, one window at a time, and names
   up to four moments per window that would stand alone as a short. Each moment is snapped to sentences, checked for
   length and scored by the local analysis like every other candidate; one that repeats a candidate the local analysis
   already found strengthens it instead. Nothing the model says is trusted on its own: a nominated moment still has
   to pass every stage. The model's job is to catch what word lists miss: a story told plainly, a quiet confession,
   a joke whose setup and punchline use ordinary words.
2. Judge. After the deep stages, the finalists (at most 12) are put side by side in one request, and the model ranks
   them and gives each a verdict: green (would stand alone), yellow (works, with a weakness), red (would not work as a
   clip, with the reason). The ranking moves a finalist's Clip Score by at most ±10 points, and only by as much as the
   model disagrees with the local ranking (percentile against percentile); a red verdict costs 6 more and is shown as
   a warning with the model's reason. The model never adds a clip the local analysis rejected and never removes one
   on its own.

Both passes run inside a time budget (ai_edit_timeout_s × 10, at most 10 minutes), report progress to the job, stop
at once when the job is cancelled and leave the local decisions as they are when the model is slow or wrong. The
built-in model answers inside a JSON schema (enforced while it writes), so a small model cannot answer in the wrong
shape.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from . import candidates as cand_mod
from . import llm, virality
from .audio import Loudness
from .common import JobContext

log = logging.getLogger("clipfoundry.pipeline.scout")

WINDOW_CHARS = 8000
MAX_PER_WINDOW = 4
MAX_NOMINATIONS = 12
JUDGE_MAX = 12
JUDGE_WEIGHT = 10.0         # the most the model's ranking can move a Clip Score
RED_PENALTY = 6.0
GREEN_BONUS = 2.0
SCOUT_BONUS = 0.08          # stage-1 bonus for a moment the model named (about the weight of the relevance term)
RESERVED = 4                # deep-stage places kept for the model's nominations
KNOWHOW_CHARS = 1100
MEMORY_CHARS = 500
FINALIST_CHARS = 700
KINDS = ("story", "insight", "funny", "emotional", "controversial", "how_to")

SYSTEM = ("You are a short-form video editor's assistant. You read transcripts of long videos and find the moments "
          "that work as vertical short clips on their own. Use only the words given; never invent anything. Reply "
          "with one JSON object and nothing else.")

SCOUT_SCHEMA = {
    "type": "object",
    "properties": {"moments": {"type": "array", "maxItems": MAX_PER_WINDOW, "items": {
        "type": "object",
        "properties": {"first": {"type": "integer"}, "last": {"type": "integer"},
                       "kind": {"type": "string", "enum": list(KINDS)}, "why": {"type": "string", "maxLength": 160}},
        "required": ["first", "last", "kind", "why"]}}},
    "required": ["moments"]}
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "ranking": {"type": "array", "maxItems": JUDGE_MAX, "items": {"type": "integer"}},
        "verdicts": {"type": "array", "maxItems": JUDGE_MAX, "items": {
            "type": "object",
            "properties": {"n": {"type": "integer"}, "verdict": {"type": "string", "enum": ["green", "yellow", "red"]},
                           "note": {"type": "string", "maxLength": 140}},
            "required": ["n", "verdict", "note"]}}},
    "required": ["ranking", "verdicts"]}

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="scout-ai")


# ------------------------------------------------------------------ the brief
@dataclass
class Brief:
    video_name: str
    min_s: float
    max_s: float
    target_s: float
    knowhow: str = ""
    memories: str = ""
    memory_ids: list[str] = field(default_factory=list)
    taste: str = ""

    def text(self) -> str:
        parts = [f'The video: "{self.video_name[:120]}".' if self.video_name else "",
                 f"A clip is {self.min_s:.0f} to {self.max_s:.0f} seconds long, ideally about {self.target_s:.0f}."]
        if self.memories:
            parts.append(self.memories)
        if self.taste:
            parts.append(self.taste)
        if self.knowhow:
            parts.append(self.knowhow)
        return "\n".join(p for p in parts if p)


def brief(opts: dict, project: dict | None = None) -> Brief:
    """The brief every request carries: title, lengths, the owner's rules that apply (brain memories) and the
    built-in playbooks about picking a clip. Never fails the job."""
    b = Brief(str((project or {}).get("name") or opts.get("video_name") or ""), float(opts.get("min_duration", 20)),
              float(opts.get("max_duration", 60)), float(opts.get("target_duration", 35)))
    try:
        from ..brain import knowhow
        b.knowhow = knowhow.select("which moment makes a clip: hook, ending, stands alone", "clips", limit=3,
                                   budget_chars=KNOWHOW_CHARS).prompt()
    except Exception:  # noqa: BLE001
        log.exception("know-how failed")
    ws = (project or {}).get("workspace_id")
    if ws:
        try:
            from .. import brain as ai_brain
            rec = ai_brain.recall("which clips to pick from this video", ws, project_id=str(project.get("id") or ""),
                                  mode="clips", kinds=("rule", "fact"), limit=4, budget_chars=MEMORY_CHARS)
            b.memories, b.memory_ids = rec.prompt(), list(rec.ids)
            if rec.ids:
                ai_brain.record_use(ws, rec.ids, "clips", str(project.get("id") or ""))
        except Exception:  # noqa: BLE001
            log.exception("recall failed")
        try:
            from .. import taste
            b.taste = taste.brief_line(str(ws))
        except Exception:  # noqa: BLE001
            log.exception("taste failed")
    return b


def configured(opts: dict) -> bool:
    """A model is set up and the scout is on."""
    return opts.get("ai_provider", "heuristic") in llm.PROVIDERS and bool(opts.get("ai_scout", True))


def budget_s(opts: dict) -> float:
    return min(600.0, max(60.0, float(opts.get("ai_edit_timeout_s", 60)) * 10))


def _timeout(opts: dict) -> float:
    return min(120.0, max(20.0, float(opts.get("ai_edit_timeout_s", 60)) * 2))


# ------------------------------------------------------------------ asking
def _ask(opts: dict, prompt: str, schema: dict, label: str, ctx: JobContext, beat: Callable[[str], None],
         deadline: float, notes: dict, complete: Callable[..., str] | None = None, max_tokens: int = 600) -> dict | None:
    """One request, waited for in one-second steps so the job keeps reporting and can be cancelled. None when the
    answer is late, unreadable or the provider fails (recorded in notes["problems"])."""
    fn = complete or llm.complete
    timeout = min(_timeout(opts), max(5.0, deadline - time.monotonic()))
    call = _pool.submit(fn, opts, prompt, task="scout", system=SYSTEM, num_ctx=8192, json_object=True,
                        json_schema=schema, timeout=timeout, max_tokens=max_tokens)
    stop = time.monotonic() + timeout
    while True:
        try:
            raw = call.result(timeout=1.0)
            break
        except concurrent.futures.TimeoutError:
            ctx.check()
            beat(f"ClipForge AI is reading {label}")
            if time.monotonic() > stop:
                notes["problems"].append(f"{label}: no answer within {timeout:g} s.")
                return None
        except llm.ProviderError as exc:
            notes["problems"].append(f"{label}: {str(exc)[:200]}")
            return None
        except Exception as exc:  # noqa: BLE001 - reported, the local analysis decides
            notes["problems"].append(f"{label}: {exc.__class__.__name__}")
            return None
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        notes["problems"].append(f"{label}: the answer was not readable.")
        return None
    notes["answered"] += 1
    return data


def _clean(text: object, limit: int) -> str:
    return " ".join(str(text or "").split()).strip("\"'“”. ")[:limit]


# ------------------------------------------------------------------ 1. the scout
def windows(sentences: list[dict], chars: int = WINDOW_CHARS) -> list[tuple[int, int]]:
    """Sentence index ranges [first, last] that fit one request each."""
    out: list[list[int]] = []
    size = 0
    for k, s in enumerate(sentences):
        line = len(s["text"][:240]) + 16
        if not out or size + line > chars:
            out.append([k, k])
            size = 0
        out[-1][1] = k
        size += line
    return [(a, b) for a, b in out]


def _stamp(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def scout_prompt(b: Brief, sentences: list[dict], first: int, last: int, part: int, parts: int) -> str:
    lines = "\n".join(f'{k} [{_stamp(sentences[k]["start"])}] {sentences[k]["text"][:240]}' for k in range(first, last + 1))
    return (f"{b.text()}\n\nPart {part} of {parts} of the transcript. Each line is one sentence: its number, its start "
            f"time, its words.\n\n{lines}\n\n"
            f"Name up to {MAX_PER_WINDOW} moments in this part that would work as a short clip on their own: a complete "
            f"thought or story with a strong first line and an ending that lands, {b.min_s:.0f} to {b.max_s:.0f} "
            "seconds long (use the start times). Skip greetings, sponsor reads, housekeeping and anything that needs "
            "what was said before it. For each moment give the first and last sentence numbers, its kind (story, "
            "insight, funny, emotional, controversial, how_to) and in a few words why a viewer would stay. Fewer is "
            "better than weak ones; an empty list is a fine answer.\n"
            'Answer: {"moments": [{"first": <number>, "last": <number>, "kind": "...", "why": "..."}]}')


def _fit(sentences: list[dict], first: int, last: int, lo: int, hi: int, min_s: float, max_s: float
         ) -> tuple[int, int] | None:
    """Snap a nominated range to the window and the allowed length: too long is cut from the end (the model's first
    line is the hook), too short grows forward sentence by sentence."""
    if first > last or last < lo or first > hi:
        return None
    first, last = max(lo, first), min(hi, last)

    def dur(a: int, b: int) -> float:
        return sentences[b]["end"] - sentences[a]["start"]

    while last > first and dur(first, last) > max_s:
        last -= 1
    while dur(first, last) < min_s and last + 1 <= hi and dur(first, last + 1) <= max_s:
        last += 1
    if dur(first, last) < 0.6 * min_s or dur(first, last) > 1.05 * max_s:
        return None
    return first, last


def nominate(sentences: list[dict], feats: list[dict], loud: Loudness, opts: dict, ctx: JobContext, found: list[dict],
             b: Brief, *, lo: float = 0.0, hi: float = 0.0, deadline: float | None = None,
             complete: Callable[..., str] | None = None) -> tuple[list[dict], dict]:
    """Read the transcript and return (new candidates, notes). A nominated moment that a found candidate already
    covers (overlap above 60%) marks that candidate instead (`scout`) and raises its stage-1 score a little."""
    notes = {"windows": 0, "read": 0, "asked": 0, "answered": 0, "nominated": 0, "added": 0, "confirmed": 0,
             "problems": [], "provider": llm.provider_label(opts), "coverage": 0.0}
    if not sentences or not configured(opts):
        return [], notes
    deadline = deadline or (time.monotonic() + budget_s(opts) * 0.6)
    wins = windows(sentences)
    notes["windows"] = len(wins)
    global_top = cand_mod.common_words(sentences)
    local = {**opts, "min_duration": float(opts.get("min_duration", 20))}
    added: list[dict] = []
    for n, (first, last) in enumerate(wins):
        ctx.check()
        if time.monotonic() > deadline:
            notes["problems"].append(f"Out of time after {n} of {len(wins)} parts; the rest was left to the local analysis.")
            break
        frac = lo + (hi - lo) * n / max(1, len(wins))
        beat = (lambda msg, f=frac: ctx.progress(f, msg))
        beat(f"ClipForge AI is reading part {n + 1} of {len(wins)}")
        notes["asked"] += 1
        data = _ask(opts, scout_prompt(b, sentences, first, last, n + 1, len(wins)), SCOUT_SCHEMA,
                    f"part {n + 1} of {len(wins)}", ctx, beat, deadline, notes, complete, max_tokens=400)
        notes["read"] = n + 1
        if not data:
            continue
        for m in (data.get("moments") or [])[:MAX_PER_WINDOW]:
            if not isinstance(m, dict):
                continue
            try:
                rng = _fit(sentences, int(m.get("first")), int(m.get("last")), first, last, b.min_s, b.max_s)
            except (TypeError, ValueError):
                rng = None
            if rng is None:
                continue
            notes["nominated"] += 1
            kind = m.get("kind") if m.get("kind") in KINDS else "moment"
            note = {"kind": kind, "why": _clean(m.get("why"), 160), "part": n + 1}
            w = cand_mod.window(sentences, feats, rng[0], rng[1], loud, local, global_top)
            twin = max((c for c in found + added if c.get("s0", -1) >= 0), key=lambda c: cand_mod._overlap(w, c),
                       default=None)
            if twin is not None and cand_mod._overlap(w, twin) > 0.6:
                if "scout" not in twin:
                    twin["scout"] = note
                    twin["stage1"] = twin["stage1"] + SCOUT_BONUS
                    notes["confirmed"] += 1
                continue
            if len(added) >= MAX_NOMINATIONS:
                continue
            w["scout"] = note
            w["stage1"] += SCOUT_BONUS
            added.append(w)
            notes["added"] += 1
    notes["coverage"] = round(notes["read"] / max(1, len(wins)), 3)
    return added, notes


# ------------------------------------------------------------------ 2. the judge
def judge_prompt(b: Brief, finalists: list[dict], sentences: list[dict]) -> str:
    rows = []
    for n, r in enumerate(finalists, 1):
        text = " ".join(sentences[k]["text"] for k in range(r["s0"], r["s1"] + 1)) if r.get("s0", -1) >= 0 \
            else (r.get("caption_text") or "")
        if len(text) > FINALIST_CHARS:
            text = text[:FINALIST_CHARS - 1].rsplit(" ", 1)[0] + "…"
        rows.append(f'Finalist {n} ({r["end"] - r["start"]:.0f} s): "{text}"')
    listed = "\n".join(rows)
    return (f"{b.text()}\n\nThe {len(finalists)} finalists below are candidate clips from this video, each with its "
            f"length and words (cut at {FINALIST_CHARS} characters).\n\n{listed}\n\n"
            "Rank them from the one most likely to hold a viewer who has never seen this video to the least, and give "
            'each a verdict: "green" (works on its own), "yellow" (works, with a weakness), "red" (would not work as a '
            "clip: it needs what came before, has no ending, is a greeting or a sponsor read, or repeats another "
            "finalist). Judge by the first line, whether the ending lands, whether it stands alone, and how much a "
            "viewer learns or feels. In each note say the weakness or the strength in a few words.\n"
            'Answer: {"ranking": [the finalist numbers, best first], "verdicts": [{"n": 1, "verdict": "green", '
            '"note": "..."}]}')


def judge(results: list[dict], sentences: list[dict], opts: dict, ctx: JobContext, b: Brief | None, *,
          score_key: str = "clip_score", frac: float = 0.0, deadline: float | None = None,
          complete: Callable[..., str] | None = None) -> dict:
    """Rank the finalists side by side. Each gets `judge` = {rank, of, verdict, note, adjust}; the caller folds
    `adjust` into its score. Returns notes."""
    notes = {"asked": 0, "answered": 0, "finalists": 0, "problems": [], "provider": llm.provider_label(opts),
             "verdicts": {}}
    pool = [r for r in results if r.get("s0", -1) >= 0]
    if len(pool) < 2 or not configured(opts):
        return notes
    deadline = deadline or (time.monotonic() + max(_timeout(opts), budget_s(opts) * 0.4))
    b = b or brief(opts)
    order = sorted(pool, key=lambda r: r.get(score_key, r.get("score", 0)), reverse=True)[:JUDGE_MAX]
    n = len(order)
    notes["finalists"] = n
    notes["asked"] = 1
    beat = (lambda msg: ctx.progress(frac, msg))
    beat(f"ClipForge AI is ranking the {n} finalists")
    data = _ask(opts, judge_prompt(b, order, sentences), JUDGE_SCHEMA, "the finalists", ctx, beat, deadline, notes,
                complete, max_tokens=700)
    if not data:
        return notes
    ranking: list[int] = []
    for x in data.get("ranking") or []:
        try:
            k = int(x)
        except (TypeError, ValueError):
            continue
        if 1 <= k <= n and k not in ranking:
            ranking.append(k)
    if len(ranking) < max(2, n // 2):
        notes["problems"].append("The ranking named too few finalists; it was not used.")
        return notes
    ranking += [k for k in range(1, n + 1) if k not in ranking]  # unranked finalists keep the local order, last
    verdicts: dict[int, tuple[str, str]] = {}
    for v in data.get("verdicts") or []:
        if not isinstance(v, dict):
            continue
        try:
            k = int(v.get("n"))
        except (TypeError, ValueError):
            continue
        if 1 <= k <= n and v.get("verdict") in ("green", "yellow", "red"):
            verdicts[k] = (v["verdict"], _clean(v.get("note"), 140))
    for local_pos, r in enumerate(order):
        k = local_pos + 1
        model_pos = ranking.index(k)
        model_pct = 1.0 - model_pos / max(1, n - 1)
        local_pct = 1.0 - local_pos / max(1, n - 1)
        adjust = JUDGE_WEIGHT * (model_pct - local_pct)
        verdict, note = verdicts.get(k, ("", ""))
        if verdict == "red":
            adjust -= RED_PENALTY
            flags = r.get("analysis", {}).get("flags")
            if isinstance(flags, list) and not any(f.get("id") == "ai_red" for f in flags):
                flags.append(virality._flag("ai_red", "ClipForge AI: would not stand alone", "warn",
                                            note or "the model's verdict was red"))
        elif verdict == "green":
            adjust += GREEN_BONUS
        r["judge"] = {"rank": model_pos + 1, "of": n, "verdict": verdict, "note": note, "adjust": round(adjust, 1),
                      "provider": notes["provider"]}
        notes["verdicts"][verdict or "none"] = notes["verdicts"].get(verdict or "none", 0) + 1
    return notes

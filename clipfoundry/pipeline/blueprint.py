"""Clip Blueprint: the Engagement Strategist's plan for one clip, written and checked before anything is rendered.

A blueprint is typed, versioned data, not instructions in prose:

* where the clip comes from (clip, project and source ids) and a hash of the inputs it was planned from
* the source intervals, in seconds of the original recording, in output order
* speed, framing (tracking mode, crop position, layout, zoom) and captions (style, position, emphasis, colors)
* emphasis events: the words to stress, at their source time
* the audio adjustments the renderer supports (silence cleanup, filler removal, loudness normalization, gain)
* the intended hook (on-screen text) and payoff (the line that delivers the point), and why the moment was chosen
* anything the renderer cannot do, listed as unsupported: reported and left out, never claimed as applied

`validate` rejects a blueprint the renderer could not follow faithfully: no intervals, intervals outside the source,
reversed, overlapping or out of order (the renderer plays the source forwards only), cuts inside a word, a speed or
an option the renderer does not support, emphasis outside the kept intervals, or on-screen text that is not said in
the clip (no fabricated speech, no changed meaning).

The Strategist plans one continuous range, and cuts weak middle sentences (filler, a promotional aside, a warm-up
line) out of it only when every rule for a safe cut holds (`middle_cuts`); otherwise the moment stays continuous.

The renderer follows a validated blueprint exactly. Edits made in the editor and alternative versions are applied
on top of the plan as a new blueprint (`with_edit`), which is stored before that render too, so every rendered file
is bound to the blueprint it was made from. Manual projects have no plan and render as they always did.
"""
from __future__ import annotations

import dataclasses
import time
from dataclasses import asdict, dataclass, field

from .. import config
from . import artifact

SCHEMA_VERSION = 1
MIN_INTERVAL = 0.5         # seconds; anything shorter is a flash, not an edit
MAX_TOTAL = 180.0          # seconds of output at most (YouTube Shorts' limit)
WORD_TOLERANCE = 0.03      # a cut this close to a word edge still counts as between words
SPEED_RANGE = (0.8, 1.25)  # what the renderer can play without changing the voice pitch (atempo)
GAIN_RANGE = (-12.0, 12.0)
ZOOM_RANGE = (1.0, 2.5)
POSITIONS = ("bottom", "middle", "top")
ORIGINS = ("strategist", "edit", "version")


class BlueprintInvalid(ValueError):
    """The plan cannot be rendered faithfully; the message lists why."""


@dataclass
class Interval:
    start: float
    end: float


@dataclass
class Framing:
    mode: str = "auto"
    crop_x: float = 0.5
    layout: str = "fill"
    zoom: float = 1.0
    auto_zoom: bool = False


@dataclass
class Captions:
    style: str = "clean"
    position: str = "bottom"
    enabled: bool = True
    highlight_words: bool = True
    emphasis: bool = False
    size: float | None = None
    highlight_color: str | None = None


@dataclass
class Audio:
    silence: str = "off"
    remove_fillers: bool = False
    normalize: bool = True
    gain_db: float = 0.0


@dataclass
class Hook:
    text: str = ""
    overlay: bool = False
    seconds: float = 3.0
    written_by: str = "clip"  # "clip": taken from the clip's own words; "you": typed in the editor


@dataclass
class Payoff:
    text: str = ""
    at: float | None = None  # source time where the payoff line starts


@dataclass
class Blueprint:
    clip_id: str
    project_id: str
    source_id: str
    input_hash: str
    intervals: list[Interval]
    speed: float = 1.0
    framing: Framing = field(default_factory=Framing)
    captions: Captions = field(default_factory=Captions)
    emphasis: list[dict] = field(default_factory=list)  # {"at": source seconds, "word": str}
    audio: Audio = field(default_factory=Audio)
    hook: Hook = field(default_factory=Hook)
    payoff: Payoff = field(default_factory=Payoff)
    reasons: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    knowledge: list[dict] = field(default_factory=list)  # approved reference revisions that changed this plan
    origin: str = "strategist"
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Blueprint":
        """Build from stored JSON. Unknown instructions are not dropped silently: they become `unsupported`."""
        data = dict(data)
        extra: list[str] = list(data.get("unsupported") or [])

        def sub(kind: type, value: object, name: str):
            value = value if isinstance(value, dict) else {}
            names = {f.name for f in dataclasses.fields(kind)}
            extra.extend(f"{name}.{k}: not supported by the renderer" for k in value if k not in names)
            return kind(**{k: v for k, v in value.items() if k in names})

        top = {f.name for f in dataclasses.fields(cls)}
        extra.extend(f"{k}: not supported by the renderer" for k in data if k not in top)
        return cls(
            clip_id=str(data.get("clip_id") or ""), project_id=str(data.get("project_id") or ""),
            source_id=str(data.get("source_id") or ""), input_hash=str(data.get("input_hash") or ""),
            intervals=[Interval(float(i["start"]), float(i["end"])) for i in data.get("intervals") or []],
            speed=float(data.get("speed", 1.0)), framing=sub(Framing, data.get("framing"), "framing"),
            captions=sub(Captions, data.get("captions"), "captions"),
            emphasis=[{"at": float(e["at"]), "word": str(e.get("word", ""))} for e in data.get("emphasis") or []],
            audio=sub(Audio, data.get("audio"), "audio"), hook=sub(Hook, data.get("hook"), "hook"),
            payoff=sub(Payoff, data.get("payoff"), "payoff"), reasons=[str(r) for r in data.get("reasons") or []],
            unsupported=list(dict.fromkeys(extra)), knowledge=list(data.get("knowledge") or []),
            origin=str(data.get("origin") or "strategist"),
            schema_version=int(data.get("schema_version") or 0))

    def window(self) -> tuple[float, float]:
        return self.intervals[0].start, self.intervals[-1].end

    def sha256(self) -> str:
        return artifact.sha256_json(self.to_dict())

    def summary(self) -> dict:
        return {"schema_version": self.schema_version, "sha256": self.sha256(), "origin": self.origin,
                "intervals": [[i.start, i.end] for i in self.intervals], "unsupported": self.unsupported}


# ------------------------------------------------------------------ validation
def _heard(words: list[dict], intervals: list[Interval]) -> list[dict]:
    return [w for w in words if any(i.start - WORD_TOLERANCE <= w["start"] and w["end"] <= i.end + WORD_TOLERANCE
                                    for i in intervals)]


def _inside_word(t: float, words: list[dict]) -> dict | None:
    return next((w for w in words if w["start"] + WORD_TOLERANCE < t < w["end"] - WORD_TOLERANCE), None)


def validate(bp: Blueprint, source_duration: float | None, words: list[dict]) -> list[dict]:
    """Every problem, as {"level": "error" | "warning", "message"}. Errors mean the plan must not be rendered."""
    issues: list[dict] = []

    def err(msg: str) -> None:
        issues.append({"level": "error", "message": msg})

    def warn(msg: str) -> None:
        issues.append({"level": "warning", "message": msg})

    mine = bp.origin == "strategist"  # the machine's own plan is held to the strictest standard
    if bp.schema_version != SCHEMA_VERSION:
        err(f"schema version {bp.schema_version} is not {SCHEMA_VERSION}")
    if bp.origin not in ORIGINS:
        err(f"unknown origin {bp.origin!r}")
    if not bp.intervals:
        err("no source intervals")
        return issues
    prev_end = None
    for k, iv in enumerate(bp.intervals, 1):
        if iv.end <= iv.start:
            err(f"interval {k} ends before it starts ({iv.start:.2f}-{iv.end:.2f} s)")
        elif iv.end - iv.start < MIN_INTERVAL:
            err(f"interval {k} is shorter than {MIN_INTERVAL} s")
        if iv.start < 0 or (source_duration and iv.end > source_duration + 0.05):
            err(f"interval {k} ({iv.start:.2f}-{iv.end:.2f} s) is outside the source "
                f"(0-{(source_duration or 0):.2f} s)")
        if prev_end is not None and iv.start < prev_end - 1e-6:
            err(f"interval {k} overlaps or comes before interval {k - 1}: the renderer plays the source forwards")
        prev_end = max(prev_end or iv.end, iv.end)
        for edge, t in (("starts", iv.start), ("ends", iv.end)):
            w = _inside_word(t, words)
            if w:
                (err if mine else warn)(f"interval {k} {edge} inside the word “{w['w']}” ({t:.2f} s)")
    total = sum(max(0.0, i.end - i.start) for i in bp.intervals) / max(bp.speed, 0.01)
    if total > MAX_TOTAL:
        err(f"{total:.0f} s of output is longer than {MAX_TOTAL:.0f} s")
    if not SPEED_RANGE[0] <= bp.speed <= SPEED_RANGE[1]:
        err(f"speed {bp.speed} is outside {SPEED_RANGE[0]}-{SPEED_RANGE[1]}")
    f, c, a = bp.framing, bp.captions, bp.audio
    if f.mode not in config.TRACKING_MODES:
        err(f"unknown framing mode {f.mode!r}")
    if f.layout not in config.LAYOUTS:
        err(f"unknown layout {f.layout!r}")
    if not 0.0 <= f.crop_x <= 1.0:
        err(f"crop position {f.crop_x} is outside 0-1")
    if not ZOOM_RANGE[0] <= f.zoom <= ZOOM_RANGE[1]:
        err(f"zoom {f.zoom} is outside {ZOOM_RANGE[0]}-{ZOOM_RANGE[1]}")
    if c.style not in config.CAPTION_STYLES:
        err(f"unknown caption style {c.style!r}")
    if c.position not in POSITIONS:
        err(f"unknown caption position {c.position!r}")
    if a.silence not in config.SILENCE_MODES:
        err(f"unknown silence mode {a.silence!r}")
    if not GAIN_RANGE[0] <= a.gain_db <= GAIN_RANGE[1]:
        err(f"gain {a.gain_db} dB is outside {GAIN_RANGE[0]}-{GAIN_RANGE[1]} dB")
    if c.emphasis and not c.enabled:
        warn("caption emphasis is on but captions are off: the emphasis only drives the zoom")
    for e in bp.emphasis:
        if not any(i.start - WORD_TOLERANCE <= e["at"] <= i.end + WORD_TOLERANCE for i in bp.intervals):
            err(f"emphasis on “{e['word']}” at {e['at']:.2f} s is outside the kept intervals")
    heard = " ".join(w["w"] for w in _heard(words, bp.intervals))
    if bp.hook.text and words:
        from .postpack import grounding_problems

        problems = grounding_problems(bp.hook.text, heard)
        if problems:
            (err if bp.hook.written_by == "clip" else warn)(
                "on-screen hook: " + "; ".join(problems[:3]) + (" (written by you)" if bp.hook.written_by != "clip"
                                                                  else ""))
    if bp.payoff.at is not None and not any(i.start - WORD_TOLERANCE <= bp.payoff.at <= i.end for i in bp.intervals):
        (err if mine else warn)("the payoff line is cut out of the clip")
    return issues


def errors(issues: list[dict]) -> list[str]:
    return [i["message"] for i in issues if i["level"] == "error"]


def heard_text(bp: Blueprint, words: list[dict]) -> str:
    """What the plan's intervals keep of the clip's words (the text a multi-interval clip is described by)."""
    return " ".join(w["w"].strip() for w in _heard(words, bp.intervals))


def heard_fields(bp: Blueprint, words: list[dict], clip: dict, settings: dict) -> dict:
    """Clip fields for a plan with middle cuts, so the clip is described by what is heard: its caption text, and
    its post package written again from the kept sentences when the one written for the whole range uses words that
    were cut out. {} for a continuous plan."""
    from . import postpack
    from .text_utils import build_sentences

    if len(bp.intervals) < 2:
        return {}
    sents = [s["text"] for s in build_sentences(_heard(words, bp.intervals))]
    out: dict = {"caption_text": heard_text(bp, words)}
    if not clip.get("post") or postpack.checks(clip["post"], " ".join(sents)):
        post = postpack.generate(sents, clip.get("hook") or "", clip.get("hooks_alt") or [], clip.get("category") or "",
                                 settings, use_ai=False)
        out.update(post=post, title=post["title"] or clip.get("title") or "", hashtags=post["hashtags"])
    return out


# ------------------------------------------------------------------ the Engagement Strategist
MAX_MIDDLE_CUTS = 2   # weak middle parts cut out of one clip at most (more jumps read as choppy)
MIN_CUT = 1.0         # seconds a cut must save to be worth a jump
MAX_CUT_SHARE = 0.35  # of the clip; the rest carries the context
CUT_GAP = 0.08        # seconds of pause needed on both sides of a cut (the renderer snaps cuts to video frames)
CUT_PAD = 0.15        # seconds of that pause kept next to the words that stay
# first words that point back at what was just said ("It has ten lessons."): the line before them must stay
REFERS_BACK = {"it", "it's", "its", "this", "that", "that's", "these", "those", "they", "they're", "them", "their",
               "he", "she", "him", "her", "his", "which", "there", "such", "same", "both"}


# a sentence made only of these says nothing ("Um, you know, like, yeah.")
FILLER_ONLY = {"um", "uh", "erm", "hmm", "mm", "ah", "like", "yeah", "okay", "ok", "so", "well", "basically",
               "anyway"}
FILLER_PAIRS = [("you", "know"), ("i", "mean"), ("kind", "of"), ("sort", "of")]
# "check out my ..." is left out: it also starts sentences that report something ("check out my results")
PROMO_CUT = ["subscribe", "sponsor", "in the description", "patreon", "promo code", "discount code", "hit the bell",
             "smash that like"]
# words a warm-up line may use besides its phrase and still say nothing ("Welcome back to the channel.")
WARM_UP_WORDS = {"guys", "everyone", "everybody", "video", "channel", "today", "back", "moving", "move", "start",
                 "started", "begin", "get", "going"}


def _only_filler(text: str) -> bool:
    from .text_utils import tokens

    toks = tokens(text)
    rest, k = [], 0
    while k < len(toks):
        if tuple(toks[k:k + 2]) in FILLER_PAIRS:
            k += 2
            continue
        rest.append(toks[k])
        k += 1
    return len(toks) >= 2 and all(t in FILLER_ONLY for t in rest)


def _warm_up(text: str) -> bool:
    from .text_utils import SLOW_OPEN_PHRASES, TRANSITION_PHRASES, content_tokens, tokens

    low = text.lower()
    phrases = [p for p in (*SLOW_OPEN_PHRASES, *TRANSITION_PHRASES) if p in low]
    said = {t for p in phrases for t in tokens(p)} | WARM_UP_WORDS
    return bool(phrases) and all(t in said for t in content_tokens(text))


def _weak(text: str) -> str:
    """Why a sentence adds nothing to the clip ("" when it does). Conservative on purpose: a sentence is weak only
    when it is nothing but filler words, a promotional aside, or a warm-up phrase with no words of its own ("Let's
    talk about pricing." names the topic, so it stays)."""
    from .text_utils import count_phrases

    if count_phrases(text.lower(), PROMO_CUT):
        return "a promotional aside"
    if _only_filler(text):
        return "filler"
    if _warm_up(text):
        return "a warm-up line"
    return ""


def middle_cuts(heard: list[dict], protect: set[int], min_seconds: float) -> list[dict]:
    """Weak sentences in the middle of a clip that can be cut out without changing what it says. Each cut runs from
    the end of a complete sentence to the start of the next kept one, with a pause on both sides; the sentence after
    it does not point back at removed words; the first and last sentences, questions and `protect`ed sentences (hook,
    payoff) stay; and the clip keeps `min_seconds` and most of its length. Chronological order is never changed.
    Returns [{"first", "last" (sentence indices), "end", "start" (source times of the kept edges), "why", "text"}]."""
    from .candidates import sentence_features
    from .text_utils import build_sentences, ends_sentence, tokens

    sents = build_sentences(heard)
    if len(sents) < 3:
        return []
    feats = sentence_features(sents, heard)
    weak = {k: _weak(s["text"]) for k, s in enumerate(sents)}
    runs: list[list[int]] = []
    for k in range(1, len(sents) - 1):
        if not weak[k] or k in protect or feats[k]["question"]:
            continue
        if runs and runs[-1][-1] == k - 1:
            runs[-1].append(k)
        else:
            runs.append([k])
    total = sents[-1]["end"] - sents[0]["start"]
    cuts: list[dict] = []
    for run in runs:
        a, b = run[0], run[-1]
        prev, nxt = sents[a - 1], sents[b + 1]
        gap1, gap2 = sents[a]["start"] - prev["end"], nxt["start"] - sents[b]["end"]
        if gap1 < CUT_GAP or gap2 < CUT_GAP:
            continue  # no pause to cut in: the words run together
        if not ends_sentence(heard[prev["i1"]]["w"]) or not ends_sentence(heard[sents[b]["i1"]]["w"]):
            continue  # not at a sentence boundary
        if sum(feats[k]["content"] for k in run) >= 2 and (tokens(nxt["text"]) or [""])[0] in REFERS_BACK:
            continue  # "It ..." would now point at something else
        end, start = prev["end"] + min(CUT_PAD, gap1 / 2), nxt["start"] - min(CUT_PAD, gap2 / 2)
        removed = start - end + sum(c["start"] - c["end"] for c in cuts)
        if start - end < MIN_CUT or removed > MAX_CUT_SHARE * total or total - removed < min_seconds:
            continue
        cuts.append({"first": a, "last": b, "end": round(end, 3), "start": round(start, 3), "why": weak[a],
                     "text": " ".join(sents[k]["text"] for k in run)})
        if len(cuts) >= MAX_MIDDLE_CUTS:
            break
    return cuts


def _quotes(sentence: str, text: str) -> bool:
    """Does `text` (the on-screen hook) use this sentence's words, so cutting it would leave the hook unsaid?"""
    from .text_utils import content_tokens

    mine, theirs = set(content_tokens(sentence)), set(content_tokens(text))
    return bool(mine & theirs)


def with_middle_cuts(bp: Blueprint, heard: list[dict], words: list[dict], min_seconds: float) -> Blueprint:
    """The plan with its weak middle parts cut out (several intervals, in order), or the continuous plan unchanged
    when no cut is safe or the cut plan would not pass validation."""
    from .text_utils import build_sentences

    sents = build_sentences(heard)
    protect = {k for k, s in enumerate(sents)
               if (bp.payoff.at is not None and s["start"] - WORD_TOLERANCE <= bp.payoff.at <= s["end"])
               or (bp.payoff.text and s["text"] in bp.payoff.text) or (bp.hook.text and _quotes(s["text"],
                                                                                                bp.hook.text))}
    cuts = middle_cuts(heard, protect, min_seconds)
    if not cuts:
        return bp
    start, end = bp.window()
    edges = [start, *[x for c in cuts for x in (c["end"], c["start"])], end]
    new = Blueprint.from_dict(bp.to_dict())
    new.intervals = [Interval(round(a, 3), round(b, 3)) for a, b in zip(edges[::2], edges[1::2])]
    new.emphasis = [e for e in bp.emphasis if any(i.start <= e["at"] <= i.end for i in new.intervals)]
    new.reasons = [*bp.reasons, *(f"cut out {c['why']} in the middle ({c['start'] - c['end']:.1f} s): "
                                  f"“{c['text'][:80]}”" for c in cuts)]
    if errors(validate(new, None, words)):
        return bp  # a safe cut cannot be established: the moment stays continuous
    return new


def build(clip: dict, project: dict, words: list[dict], settings: dict, *, source_id: str = "",
          selection: dict | None = None, video_path: str | None = None, video_offset: float = 0.0) -> Blueprint:
    """The plan for a clip chosen by the analyzer: its range (moved onto a hard scene cut when one is right next to
    it and no word is lost), weak middle parts cut out when that is safe (`with_middle_cuts`), the configured look
    and sound, the words worth stressing, the hook and the payoff. `video_path` is the file to look for scene cuts
    in; `video_offset` is where it starts in source time (a live window file)."""
    from . import render
    from ..autopilot import knowledge
    from .postpack import _payoff_sentence  # noqa: PLC2701 - the shared "which line delivers the point" rule
    from .text_utils import build_sentences

    opts = render.effective_options(settings, project.get("options") or {}, {})
    opts, influences = knowledge.choose(clip, opts, settings)
    start, end = float(clip["start"]), float(clip["end"])
    reasons = [r for r in [clip.get("reason") or ""] if r] + [str(x) for x in ((selection or {}).get("explanation")
                                                                                or [])[:4]]
    reasons += [f"Approved {i['snapshot']['kind']} '{i['snapshot']['title']}' (revision {i['revision']}): "
                + ", ".join(f"{k.replace('_', ' ')} = {d['after']}" for k, d in i["decisions"].items())
                for i in influences]
    if video_path:
        local = [{**w, "start": w["start"] - video_offset, "end": w["end"] - video_offset} for w in words]
        start, end, snapped = render.snap_to_cuts(video_path, start - video_offset, end - video_offset, local, {})
        start, end = start + video_offset, end + video_offset
        reasons += [f"{edge} moved onto the scene cut" for edge in snapped]
    heard = [w for w in words if w["end"] > start and w["start"] < end]
    keywords = {t.lstrip("#").lower() for t in ((clip.get("post") or {}).get("hashtags") or clip.get("hashtags") or [])}
    emphasis = [{"at": round(heard[i]["start"], 3), "word": heard[i]["w"]}
                for i in sorted(render.emphasis_words(heard, keywords))]
    sents = build_sentences(heard)
    payoff_text = _payoff_sentence([s["text"] for s in sents]) if sents else ""
    payoff_at = next((s["start"] for s in sents if payoff_text.startswith(s["text"])), None)
    source_words = [[w["w"], round(w["start"], 3), round(w["end"], 3)] for w in heard]
    bp = Blueprint(
        clip_id=clip["id"], project_id=clip.get("project_id") or project.get("id", ""), source_id=source_id,
        input_hash=artifact.sha256_json({"words": source_words, "range": [clip["start"], clip["end"]],
                                         "score": clip.get("score"),
                                         "source": video_path or project.get("source_path")}),
        intervals=[Interval(round(start, 3), round(end, 3))],
        speed=float(opts.get("speed") or 1.0),
        framing=Framing(mode=opts.get("tracking") or "auto", crop_x=float(opts.get("crop_x", 0.5) or 0.5),
                        layout=opts.get("layout") or "fill", zoom=float(opts.get("zoom") or 1.0),
                        auto_zoom=bool(opts.get("auto_zoom"))),
        captions=Captions(style=opts.get("caption_style") or "clean", position=opts.get("caption_position") or "bottom",
                          enabled=bool(opts.get("captions_enabled", True)),
                          highlight_words=bool(opts.get("highlight_words", True)),
                          emphasis=bool(opts.get("caption_emphasis")), size=opts.get("caption_size"),
                          highlight_color=opts.get("highlight_color")),
        emphasis=emphasis,
        audio=Audio(silence=opts.get("silence") or "off", remove_fillers=bool(opts.get("remove_fillers")),
                    normalize=bool(opts.get("normalize_audio", True)), gain_db=float(opts.get("gain_db") or 0.0)),
        hook=Hook(text=clip.get("hook") or "", overlay=bool(opts.get("hook_overlay")),
                  seconds=float(opts.get("hook_seconds") or 3.0)),
        payoff=Payoff(text=payoff_text, at=round(payoff_at, 3) if payoff_at is not None else None),
        reasons=reasons, knowledge=influences)
    shortest = {**settings, **{k: v for k, v in (project.get("options") or {}).items() if v is not None}}
    if opts.get("pacing") == "continuous":
        return bp
    return with_middle_cuts(bp, heard, words, float(shortest.get("min_duration") or 0.0))


# ------------------------------------------------------------------ edits and versions on top of the plan
_EDIT_FIELDS = {"tracking": ("framing", "mode"), "crop_x": ("framing", "crop_x"), "layout": ("framing", "layout"),
                "zoom": ("framing", "zoom"), "auto_zoom": ("framing", "auto_zoom"),
                "caption_style": ("captions", "style"), "caption_position": ("captions", "position"),
                "captions_enabled": ("captions", "enabled"), "highlight_words": ("captions", "highlight_words"),
                "caption_emphasis": ("captions", "emphasis"), "caption_size": ("captions", "size"),
                "highlight_color": ("captions", "highlight_color"), "silence": ("audio", "silence"),
                "remove_fillers": ("audio", "remove_fillers"), "normalize_audio": ("audio", "normalize"),
                "gain_db": ("audio", "gain_db"), "hook": ("hook", "text"), "hook_overlay": ("hook", "overlay"),
                "hook_seconds": ("hook", "seconds")}


def with_edit(bp: Blueprint, edit: dict, origin: str = "edit") -> Blueprint:
    """The plan with the editor's (or a version's) changes applied. A trim replaces the intervals with the trimmed
    range; everything else overrides the matching field. Returns `bp` itself when nothing changes."""
    edit = {k: v for k, v in (edit or {}).items() if v is not None}
    if not edit:
        return bp
    new = Blueprint.from_dict(bp.to_dict())
    changed = []
    if "start" in edit or "end" in edit:
        s, e = float(edit.get("start", bp.intervals[0].start)), float(edit.get("end", bp.intervals[-1].end))
        new.intervals = [Interval(round(s, 3), round(e, 3))]
        new.emphasis = [x for x in new.emphasis if s <= x["at"] <= e]
        changed.append("range")
    if "speed" in edit:
        new.speed = float(edit["speed"])
        changed.append("speed")
    for key, (part, attr) in _EDIT_FIELDS.items():
        if key in edit:
            setattr(getattr(new, part), attr, edit[key])
            changed.append(key)
    if "hook" in edit and edit["hook"] != bp.hook.text:
        new.hook.written_by = "you" if origin == "edit" else bp.hook.written_by
    if "caption_words" in edit:
        changed.append("caption text")
    if not changed:
        return bp
    new.origin = origin
    who = "you" if origin == "edit" else "the version"
    new.reasons = [*bp.reasons, f"changed by {who}: {', '.join(changed)}"]
    return new


def shifted(bp: Blueprint, delta: float) -> Blueprint:
    """The same plan on a time line that starts `delta` seconds later (live clips render from a window file)."""
    new = Blueprint.from_dict(bp.to_dict())
    new.intervals = [Interval(round(i.start + delta, 3), round(i.end + delta, 3)) for i in bp.intervals]
    new.emphasis = [{**e, "at": round(e["at"] + delta, 3)} for e in bp.emphasis]
    if new.payoff.at is not None:
        new.payoff.at = round(new.payoff.at + delta, 3)
    return new


def render_options(bp: Blueprint) -> dict:
    """The renderer's options that the plan decides."""
    f, c, a, h = bp.framing, bp.captions, bp.audio, bp.hook
    out = {"tracking": f.mode, "crop_x": f.crop_x, "layout": f.layout, "zoom": f.zoom, "auto_zoom": f.auto_zoom,
           "caption_style": c.style, "caption_position": c.position, "captions_enabled": c.enabled,
           "highlight_words": c.highlight_words, "caption_emphasis": c.emphasis, "silence": a.silence,
           "remove_fillers": a.remove_fillers, "normalize_audio": a.normalize, "gain_db": a.gain_db,
           "speed": bp.speed, "hook": h.text, "hook_overlay": h.overlay, "hook_seconds": h.seconds}
    if c.size is not None:
        out["caption_size"] = c.size
    if c.highlight_color is not None:
        out["highlight_color"] = c.highlight_color
    return out


def emphasis_indices(bp: Blueprint, words: list[dict]) -> set[int]:
    """Which of the rendered words (in source time, same order as rendered) the plan stresses."""
    out = set()
    for e in bp.emphasis:
        k = next((i for i, w in enumerate(words) if abs(w["start"] - e["at"]) < 0.02), None)
        if k is not None:
            out.add(k)
    return out


# ------------------------------------------------------------------ storage
def save(bp: Blueprint, issues: list[dict], version_id: str = "") -> dict:
    """Store a plan (every render's plan is stored before the render). The same plan is stored once."""
    from .. import db
    from ..autopilot import knowledge

    sha = bp.sha256()
    rows = db.select("clip_blueprints", "clip_id = ? AND sha256 = ? AND version_id = ?", (bp.clip_id, sha, version_id),
                     "created_at DESC", 1)
    if rows:
        if rows[0]["status"] == "valid" and rows[0]["origin"] == "strategist":
            knowledge.record(rows[0])
        return rows[0]
    saved = db.insert("clip_blueprints", {"clip_id": bp.clip_id, "version_id": version_id, "origin": bp.origin,
                                         "schema_version": bp.schema_version, "sha256": sha,
                                         "blueprint": bp.to_dict(), "status": "invalid" if errors(issues) else "valid",
                                         "issues": issues, "created_at": time.time()})
    if saved["status"] == "valid" and saved["origin"] == "strategist":
        knowledge.record(saved)
    return saved


def plan_of(clip_id: str) -> Blueprint | None:
    """The Engagement Strategist's own plan for a clip (None for clips that have none, e.g. manual projects)."""
    from .. import db

    rows = db.select("clip_blueprints", "clip_id = ? AND origin = 'strategist' AND status = 'valid'", (clip_id,),
                     "created_at DESC", 1)
    return Blueprint.from_dict(rows[0]["blueprint"]) if rows else None


def for_render(clip: dict, source_duration: float | None, words: list[dict], version_edit: dict | None = None,
               version_id: str = "") -> Blueprint | None:
    """The plan this render must follow: the strategist's plan with the clip's edits (and a version's overrides)
    on top, validated and stored. None when the clip has no plan. Raises BlueprintInvalid."""
    base = plan_of(clip["id"])
    if base is None:
        return None
    bp = with_edit(base, clip.get("edit") or {}, "edit")
    if version_edit:
        bp = with_edit(bp, version_edit, "version")
    issues = validate(bp, source_duration, words)
    save(bp, issues, version_id)
    problems = errors(issues)
    if problems:
        raise BlueprintInvalid("The clip's plan cannot be rendered as it is: " + "; ".join(problems[:3]))
    return bp

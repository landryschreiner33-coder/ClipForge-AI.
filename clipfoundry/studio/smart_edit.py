"""Smart editing: ClipForge edits the rough cut instead of only placing your files one after another.

What it does, in this order (each step is written in the plan's notes, and everything stays editable and undoable):

1. **Listens for what to leave out.** Sentences you asked to avoid are removed. A repeated take of the same line (a
   false start, or saying a sentence twice) keeps only the later take. With the AI helper set up (Settings → AI
   helper), it also suggests weak or off-topic sentences; the built-in rules work without it.
2. **Fits your length.** When the footage is longer than the length you asked for, the weakest passages (by what is
   said: how much is said per second, strong or emotional words, a payoff, numbers; filler counts against) are left
   out until it fits. Your must-keep words, the opening and the ending are never left out. Left-out parts stay in the
   sequence, switched off, so "Put back" restores any of them.
3. **Cuts dead air.** Inside what is kept, pauses longer than a threshold (0.7 s, or 0.4 s for "fast-paced") are cut
   to a short natural breath, and "um"/"uh" are cut when they are heard on their own. Pauses are found from the word
   timings and confirmed in the sound itself (a stretch at least 30 dB below the speaker's level), so a cut never
   lands inside an audible word. The joins inside one recording are straight cuts with a 10 ms sound fade (no clicks);
   "fast-paced" also punches in a little on every other cut to hide the jump.
4. **Adds pictures.** Your images are shown over the video while the talking goes on (B-roll): an image whose file
   name matches something said appears when it is said; the others are spread over long talking stretches. Each one
   pushes in slowly and fades in and out. Without any speech, images stay in the sequence as before.
5. **Adds sound.** Background music under the whole video that dips under speech and fades in and out: your own
   music file, or free music made by ClipForge on this computer (studio/library.py) in the video's mood. Soft
   whooshes mark the changes from one recording to the next and a soft swish each picture.

Nothing is invented: no narration, no statements, no fake footage. A length the footage cannot reach is explained.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

from ..pipeline.text_utils import (EMOTION_WORDS, HOOK_WORDS, PAYOFF_PHRASES, STOPWORDS, build_sentences,
                                   content_tokens, tokens)
from . import engine

LEVELS = {"smart": {"pause_s": 0.7, "pad_s": 0.16, "label": "Edit it for me"},
          "tight": {"pause_s": 0.4, "pad_s": 0.1, "label": "Fast-paced"}}
LEVEL_CHOICES = ("off", "smart", "tight")
PURE_FILLERS = {"um", "umm", "uh", "uhh", "uhm", "erm", "er", "ah", "hmm", "mm", "mhm"}
FILLER_GAP_S = 0.22          # an um/uh heard on its own is cut when it leaves at least this much out
FILLER_PAD_S = 0.05
FADE_MS = 10                 # sound fade at a jump cut (no click)
PUNCH_IN = 1.1
OVERLAY_MS = {"calm": 4500, "balanced": 3500, "energetic": 2600}
QUIET_DB = 30.0              # a pause is this far below the speaker's typical level
FRAME_S = 0.01
JUNK_NAME = {"img", "dsc", "dscn", "image", "photo", "pic", "picture", "screenshot", "screen", "shot", "pxl", "copy",
             "final", "edit", "edited", "jpg", "jpeg", "png", "webp", "clipforge", "effect", "music", "untitled",
             "whatsapp", "export", "file", "new", "version"}
MUSIC_CHOICES = ("none", "supplied", "find", "auto", "library")


# ------------------------------------------------------------------ options
def options(values: dict, brief: dict) -> dict:
    """The smart-editing choices: the brief's own answer wins, then the guidance values, then the defaults."""
    def pick(key, default):
        if key in brief and brief[key] not in (None, ""):
            return brief[key]
        return values.get(key, default)

    level = pick("smart_edit", "off")
    level = level if level in LEVEL_CHOICES else "off"
    return {"level": level, "cut_pauses": bool(pick("cut_pauses", True)), "cut_retakes": bool(pick("cut_retakes", True)),
            "fit_length": bool(pick("fit_length", True)), "punch_in": bool(pick("punch_in", level == "tight")),
            "sound_effects": bool(pick("sound_effects", True)), "broll": bool(pick("broll_images", True)),
            "music": pick("music", "auto") if pick("music", "auto") in MUSIC_CHOICES else "auto",
            "ai": bool(pick("ai_edit", True))}


# ------------------------------------------------------------------ measuring the sound
def levels(asset: dict) -> "object | None":
    """Loudness (dBFS) of every 10 ms of the recording, from the 16 kHz copy made for transcription (None when that
    copy is not there: the word timings alone then decide)."""
    import wave

    import numpy as np

    wav = Path(asset["path"]).parent / "audio.wav"
    if not wav.is_file():
        return None
    try:
        with wave.open(str(wav)) as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                return None
            hop = int(w.getframerate() * FRAME_S)
            out = []
            while True:
                raw = w.readframes(hop * 6000)
                if not raw:
                    break
                x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768
                n = len(x) // hop
                if n:
                    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
                    out.append(20 * np.log10(np.maximum(rms, 1e-9)))
    except (OSError, EOFError, wave.Error):
        return None
    return np.concatenate(out) if out else None


def quiet_spans(db_levels, min_s: float) -> list[tuple[int, int]]:
    """Stretches (ms) at least `min_s` long that are clearly quieter than the speaker (never inside a word)."""
    import numpy as np

    if db_levels is None or not len(db_levels):
        return []
    voiced = db_levels[db_levels > -60]
    if not len(voiced):
        return []
    threshold = max(-58.0, float(np.percentile(voiced, 90)) - QUIET_DB)
    quiet = np.concatenate([[False], db_levels < threshold, [False]])
    edges = np.flatnonzero(quiet[1:] != quiet[:-1])
    spans = []
    for a, b in zip(edges[::2], edges[1::2]):
        if (b - a) * FRAME_S >= min_s:
            spans.append((int(a * FRAME_S * 1000), int(b * FRAME_S * 1000)))
    return spans


# ------------------------------------------------------------------ reading what is said
def _toks(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in PURE_FILLERS]


def is_filler(word: dict) -> bool:
    return re.sub(r"[^a-z]", "", str(word.get("w", "")).lower()) in PURE_FILLERS


def retakes(sents: list[dict]) -> dict[int, int]:
    """{sentence: the later take that replaces it}: a false start (the next sentence starts the same way) or the
    same line said twice in a row."""
    out = {}
    for k in range(len(sents) - 1):
        a, b = _toks(sents[k]["text"]), _toks(sents[k + 1]["text"])
        if len(a) < 2 or not b or sents[k + 1]["start"] - sents[k]["end"] > 6.0:
            continue
        prefix = 0
        for x, y in zip(a, b):
            if x != y:
                break
            prefix += 1
        similar = difflib.SequenceMatcher(None, a, b).ratio()
        false_start = prefix >= 2 and prefix >= 0.6 * len(a) and len(b) >= len(a)
        repeated = len(a) >= 4 and similar >= 0.8
        if false_start or repeated:
            out[k] = k + 1
    return out


def stumbles(ws: list[dict], s: dict) -> set[int]:
    """Words of a stumble inside one sentence: a run of two or more words said again right away ("the water was
    the water was really cold") keeps only the second time."""
    idx = [i for i in range(s["i0"], s["i1"] + 1) if not is_filler(ws[i])]
    norm = [re.sub(r"[^a-z0-9']", "", str(ws[i]["w"]).lower()) for i in idx]
    out: set[int] = set()
    k = 0
    while k < len(idx):
        hit = 0
        for n in (4, 3, 2):
            if k + 2 * n <= len(idx) and all(norm[k:k + n]) and norm[k:k + n] == norm[k + n:k + 2 * n]:
                hit = n
                break
        if hit:
            out.update(idx[k:k + hit])
            k += hit
        else:
            k += 1
    return out


def score(s: dict) -> float:
    """How much a sentence carries, 0 to about 1 (no AI): information per second, strong or emotional words, a
    payoff, numbers; filler and very short asides count against it."""
    text = s["text"].lower()
    toks = tokens(text)
    content = content_tokens(text)
    dur = max(0.6, s["end"] - s["start"])
    value = 0.5 * min(1.0, len(content) / dur / 1.6)
    value += 0.15 * min(1.0, sum(1 for t in toks if t in HOOK_WORDS or t in EMOTION_WORDS) / 2)
    value += 0.1 if any(p in text for p in PAYOFF_PHRASES) else 0.0
    value += 0.08 if re.search(r"\d", text) else 0.0
    value += 0.05 if text.rstrip().endswith(("?", "!")) else 0.0
    fillers = sum(1 for t in toks if t in PURE_FILLERS or t in ("like", "basically", "literally"))
    value -= 0.4 * fillers / max(1, len(toks))
    value -= 0.2 if len(toks) <= 3 else 0.0
    return round(value, 4)


def sentence_table(project: dict, assets: dict[str, dict], words: dict[str, list[dict]]) -> list[dict]:
    """Every sentence of the videos in the media bin, numbered across the whole project (what the AI helper reads)."""
    out = []
    n_file = 0
    for aid in project["asset_ids"]:
        a = assets.get(aid)
        if not a or a["kind"] != "video":
            continue
        ws = words.get(aid) or []
        if not ws:
            continue
        n_file += 1
        for k, s in enumerate(build_sentences(ws)):
            out.append({"i": len(out), "asset_id": aid, "k": k, "file": n_file, "start": s["start"],
                        "dur": round(s["end"] - s["start"], 1), "text": s["text"]})
    return out


def _phrases(text: str) -> list[str]:
    return [p.strip().lower() for p in re.split(r"[,;\n]|\band\b", text or "") if len(p.strip()) >= 3]


# ------------------------------------------------------------------ cutting one recording
def _runs(ws: list[dict], sents: list[dict], keep: list[bool], opts: dict, level: dict, length_ms: int,
          quiet: list[tuple[int, int]], drop: set[int] | None = None) -> list[tuple[int, int]]:
    """The kept parts of one recording (ms), with long pauses, lone fillers and stumbles (`drop`) cut out."""
    pause_s, pad_s = level["pause_s"], level["pad_s"]
    drop = drop or set()
    kept: list[int] = []
    sentence_of: dict[int, int] = {}
    for k, s in enumerate(sents):
        if not keep[k]:
            continue
        idx = list(range(s["i0"], s["i1"] + 1))
        real = [i for i in idx if not is_filler(ws[i])]
        for i in idx:
            if i in drop:
                continue
            if opts["cut_pauses"] and real and is_filler(ws[i]):
                continue  # an um/uh in a sentence with real words: left out when it leaves a gap worth cutting
            kept.append(i)
            sentence_of[i] = k
    if not kept:
        return []
    groups: list[list[int]] = [[kept[0]]]
    soft: list[bool] = []  # was the cut before group n made around a filler (small pads)?
    for prev, i in zip(kept, kept[1:]):
        gap = ws[i]["start"] - ws[prev]["end"]
        between = range(prev + 1, i)
        dropped_sentence = any(not keep[sentence_of.get(j, -1)] if j in sentence_of else not is_filler(ws[j])
                               for j in between)
        filler_between = bool(between) and all(is_filler(ws[j]) for j in between)
        if dropped_sentence or (opts["cut_pauses"] and gap > pause_s) or \
                (filler_between and gap >= FILLER_GAP_S):
            groups.append([i])
            soft.append(filler_between and not dropped_sentence and gap <= pause_s)
        else:
            groups[-1].append(i)
    out: list[list[int]] = []
    for n, g in enumerate(groups):
        first, last = g[0], g[-1]
        pre = FILLER_PAD_S if n and soft[n - 1] else pad_s
        post = FILLER_PAD_S if n < len(soft) and soft[n] else pad_s
        a = ws[first]["start"] - pre
        b = ws[last]["end"] + post
        if first > 0:  # never take in any of the word before (it may be left out)
            a = max(a, ws[first - 1]["end"] + 0.02)
        if last + 1 < len(ws):
            b = min(b, ws[last + 1]["start"] - 0.02)
        out.append([max(0, int(a * 1000)), min(length_ms, int(b * 1000))])
    if opts["cut_pauses"] and quiet:  # pauses the word timings missed, confirmed in the sound
        starts = sorted(int(w["start"] * 1000) for w in ws)
        split: list[list[int]] = []
        for a, b in out:
            cur = a
            for q0, q1 in quiet:
                if q1 - q0 < pause_s * 1000 or q0 <= cur + 150 or q1 >= b - 150:
                    continue
                if any(q0 + 50 < st < q1 - 50 for st in starts):
                    continue  # a word is said to start in there: keep it rather than risk a clipped word
                keep_q = int(min(pad_s, 0.12) * 1000)
                split.append([cur, q0 + keep_q])
                cur = q1 - keep_q
            split.append([cur, b])
        out = split
    merged: list[list[int]] = []
    for a, b in out:  # a part shorter than half a second joins its neighbour
        if merged and (b - a < 500 or merged[-1][1] - merged[-1][0] < 500) and a - merged[-1][1] < 1000:
            merged[-1][1] = b
        elif b - a >= 250:
            merged.append([a, b])
    return [(a, b) for a, b in merged if b - a >= 250]


def _span(ws: list[dict], s: dict, pad_s: float, length_ms: int) -> tuple[int, int]:
    a, b = s["start"] - pad_s, s["end"] + pad_s
    if s["i0"] > 0:
        a = max(a, ws[s["i0"] - 1]["end"] + 0.02)
    if s["i1"] + 1 < len(ws):
        b = min(b, ws[s["i1"] + 1]["start"] - 0.02)
    return max(0, int(a * 1000)), min(length_ms, int(b * 1000))


# ------------------------------------------------------------------ the plan
def build(project: dict, assets: dict[str, dict], words: dict[str, list[dict]], values: dict, *,
          ctx: dict | None = None) -> dict:
    """The smart rough cut (a complete plan in the engine's schema). `ctx`: what the build job prepared:
    `ai` (ai_editor advice), `ai_problem`, `library` ({key: asset}) and `music` (the chosen music asset id and
    how it was chosen)."""
    ctx = ctx or {}
    brief = project.get("brief") or {}
    opts = options(values, brief)
    level = LEVELS.get(opts["level"], LEVELS["smart"])
    feel = (ctx.get("ai") or {}).get("music") if (ctx.get("ai") or {}).get("music") in ("calm", "balanced",
                                                                                         "energetic") else None
    feel = values.get("feel", "balanced") if values.get("feel") else (feel or "balanced")
    from .video_flow import FEEL_TRANSITIONS, IMAGE_MS, _audio_item  # noqa: PLC0415 - shared rough-cut helpers

    t_type, t_ms = FEEL_TRANSITIONS.get(feel, FEEL_TRANSITIONS["balanced"])
    if values.get("transition"):
        t_type = values["transition"]
        t_ms = 0 if t_type == "cut" else (t_ms or 400)
    avoid, keep_words = _phrases(brief.get("avoid", "")), _phrases(brief.get("must_keep", ""))
    ai = ctx.get("ai") or {}
    table = sentence_table(project, assets, words)
    by_key = {(s["asset_id"], s["k"]): s["i"] for s in table}
    ai_cut = {int(k): v for k, v in (ai.get("cut") or {}).items()}
    notes: list[str] = []
    stats = {"pauses_cut": 0, "seconds_saved": 0.0, "trimmed_s": 0.0, "retakes": 0, "stumbles": 0, "ai_left_out": 0, "fit_left_out": 0,
             "fillers": 0, "overlays": 0, "effects": 0, "music": ""}

    # ---- 1. what is said, per recording; what to leave out
    talks: list[dict] = []
    for aid in project["asset_ids"]:
        a = assets.get(aid)
        if not a or a["kind"] != "video":
            continue
        ws = words.get(aid) or []
        sents = build_sentences(ws) if ws else []
        status = ["keep"] * len(sents)
        why = [""] * len(sents)
        for k, s in enumerate(sents):
            text = s["text"].lower()
            hit = next((p for p in avoid if p in text), None)
            protected = any(p in text for p in keep_words)
            if hit and not protected:
                status[k], why[k] = "avoid", hit
                notes.append(f"Removed “{s['text'][:80]}” from {a['filename']} because you asked to avoid “{hit}”.")
        if opts["cut_retakes"]:
            for k in retakes(sents):
                if status[k] == "keep" and not any(p in sents[k]["text"].lower() for p in keep_words):
                    status[k], why[k] = "retake", "an earlier take of the next line"
                    stats["retakes"] += 1
        for k, s in enumerate(sents):
            g = by_key.get((aid, k))
            if g in ai_cut and status[k] == "keep" and not any(p in s["text"].lower() for p in keep_words):
                status[k], why[k] = "ai", ai_cut[g] or "suggested by the AI helper"
                stats["ai_left_out"] += 1
        talks.append({"asset": a, "words": ws, "sents": sents, "status": status, "why": why,
                      "scores": [score(s) for s in sents]})
    talking = [t for t in talks if t["sents"]]

    # ---- 2. fit the length (whole passages, weakest first; opening, ending and must-keeps stay)
    target = float(values.get("target_duration_s") or 0)
    pad = level["pad_s"]

    def estimate() -> float:
        total = 0.0
        for t in talks:
            if not t["sents"]:
                total += engine._length(t["asset"]) / 1000  # noqa: SLF001
                continue
            for k, s in enumerate(t["sents"]):
                if t["status"][k] == "keep":
                    gap = (t["sents"][k + 1]["start"] - s["end"]) if k + 1 < len(t["sents"]) else 0
                    total += s["end"] - s["start"] + min(max(gap, 0), level["pause_s"] if opts["cut_pauses"]
                                                         else max(gap, 0))
        images = sum(1 for aid in project["asset_ids"] if (assets.get(aid) or {}).get("kind") == "image")
        if not (opts["broll"] and talking):
            total += images * IMAGE_MS / 1000
        return total

    if opts["fit_length"] and target and talking and estimate() > target * 1.08:
        beats = []
        for t in talking:
            cur: list[int] = []
            for k, s in enumerate(t["sents"]):
                if t["status"][k] != "keep":
                    continue
                if cur and (s["start"] - t["sents"][cur[-1]]["end"] > 1.5 or
                            s["end"] - t["sents"][cur[0]]["start"] > 25):
                    beats.append((t, cur))
                    cur = []
                cur.append(k)
            if cur:
                beats.append((t, cur))
        protected = {id(beats[0][1]), id(beats[-1][1])} if beats else set()
        ranked = sorted((b for b in beats if id(b[1]) not in protected and not any(
            p in b[0]["sents"][k]["text"].lower() for k in b[1] for p in keep_words)),
            key=lambda b: sum(b[0]["scores"][k] for k in b[1]) / len(b[1]))
        for t, ks in ranked:
            if estimate() <= target * 1.02:
                break
            for k in ks:
                t["status"][k], t["why"][k] = "fit", "to fit your length"
                stats["fit_left_out"] += 1
        if estimate() > target * 1.1:
            notes.append(f"Even without its weaker parts the video is about {estimate() / 60:.1f} min, longer than "
                         f"the {target / 60:.1f} min you asked for: your must-keep parts, the opening and the "
                         "ending stay. Remove more in the sequence if you like.")
    elif target and talking and estimate() < target * 0.9:
        notes.append(f"Your footage adds up to about {estimate() / 60:.1f} min, shorter than the "
                     f"{target / 60:.1f} min you asked for. Nothing is invented to fill the difference.")

    # ---- 3. the sequence: kept parts with the dead air cut out, left-out parts switched off in place
    clips: list[dict] = []
    outline: list[dict] = []
    overlay_mode = opts["broll"] and bool(talking)
    talk_by_asset = {t["asset"]["id"]: t for t in talks}
    images_for_overlay: list[dict] = []
    for n, aid in enumerate(project["asset_ids"], 1):
        a = assets.get(aid)
        if not a or a["kind"] == "audio":
            continue
        if a["kind"] == "image":
            if overlay_mode:
                images_for_overlay.append(a)
                continue
            clips.append({"id": f"c{n}", "asset_id": aid, "kind": "image", "in_ms": 0, "out_ms": IMAGE_MS,
                          "label": a["filename"], "gain_db": 0.0, "include": True})
            outline.append({"clip_id": f"c{n}", "label": a["filename"], "summary": "Your image",
                            "duration": IMAGE_MS / 1000})
            continue
        t = talk_by_asset[aid]
        length = engine._length(a)  # noqa: SLF001
        ws, sents = t["words"], t["sents"]
        if not sents:
            clips.append({"id": f"c{n}", "asset_id": aid, "kind": "video", "in_ms": 0, "out_ms": length,
                          "label": a["filename"], "gain_db": 0.0, "include": True})
            outline.append({"clip_id": f"c{n}", "label": a["filename"], "summary": "No speech",
                            "duration": round(length / 1000, 1)})
            continue
        keep_mask = [s == "keep" for s in t["status"]]
        quiet = quiet_spans(levels(a), level["pause_s"]) if opts["cut_pauses"] else []
        drop: set[int] = set()
        if opts["cut_retakes"]:
            for k, s in enumerate(sents):
                if keep_mask[k] and not any(p in s["text"].lower() for p in keep_words):
                    drop |= stumbles(ws, s)
            stats["stumbles"] += len(drop)
        runs = _runs(ws, sents, keep_mask, opts, level, length, quiet, drop)
        if opts["cut_pauses"] and runs:
            dropped = [_span(ws, s, pad, length) for s, k in zip(sents, keep_mask) if not k]
            for (_a1, b1), (a2, _b2) in zip(runs, runs[1:]):
                if any(d0 < a2 and d1 > b1 for d0, d1 in dropped):
                    continue  # a left-out sentence, not a pause
                stats["pauses_cut"] += 1
                stats["seconds_saved"] += (a2 - b1) / 1000
            stats["trimmed_s"] += (runs[0][0] + max(0, length - runs[-1][1])) / 1000
            stats["fillers"] += sum(1 for k, s in enumerate(sents) if keep_mask[k]
                                    for i in range(s["i0"], s["i1"] + 1) if is_filler(ws[i]))
        parts = [("keep", a_, b, "") for a_, b in runs]
        # left-out sentences in place, merged per stretch, so "Put back" restores them where they were said
        off: list[list] = []
        for k, s in enumerate(sents):
            if t["status"][k] in ("keep", "avoid"):
                continue
            a_, b = _span(ws, s, pad, length)
            if off and off[-1][3] == t["status"][k] and a_ - off[-1][2] < 1500:
                off[-1][2] = b
                off[-1][4].append(s["text"])
            else:
                off.append([t["status"][k], a_, b, t["status"][k], [s["text"]], t["why"][k]])
        parts += [(o[0], o[1], o[2], o[5], " ".join(o[4])) for o in off]  # type: ignore[misc]
        parts.sort(key=lambda p: p[1])
        kept_index = 0
        for j, part in enumerate(parts):
            kind, a_ms, b_ms = part[0], part[1], part[2]
            cid = f"c{n}" + (f"-{j + 1}" if len(parts) > 1 else "")
            inside = [s for s in sents if s["end"] * 1000 > a_ms and s["start"] * 1000 < b_ms]
            heard = " ".join(w["w"].strip() for w in ws if a_ms <= w["start"] * 1000 < b_ms)
            said = (part[4] if len(part) > 4 and kind != "keep" else heard)[:140]
            clip = {"id": cid, "asset_id": aid, "kind": "video", "in_ms": a_ms, "out_ms": b_ms,
                    "label": a["filename"], "gain_db": 0.0, "include": kind == "keep"}
            kept = [p for p in keep_words if any(p in s["text"].lower() for s in inside)]
            if kept:
                clip["must_keep"] = kept
            if j:  # inside one recording every join is a straight cut, with a tiny sound fade
                clip.update(join="cut", fade_in_ms=FADE_MS)
            if j + 1 < len(parts):
                clip["fade_out_ms"] = FADE_MS
            if kind == "keep":
                if j and opts["punch_in"] and kept_index % 2 == 1:
                    clip["zoom"] = PUNCH_IN
                kept_index += 1
            clips.append(clip)
            outline.append({"clip_id": cid, "label": a["filename"], "duration": round((b_ms - a_ms) / 1000, 1),
                            "summary": (said or "No speech") if kind == "keep" else
                            f"Left out ({part[3]}): {said}", **({"keeps": kept} if kept else {})})
    if stats["retakes"]:
        notes.append(f"Left out {stats['retakes']} earlier take{'s' if stats['retakes'] != 1 else ''} of a line "
                     "you said again (switched off in the sequence; Put back restores one).")
    if stats["stumbles"]:
        notes.append(f"Cut {stats['stumbles']} word{'s' if stats['stumbles'] != 1 else ''} of stumbles said twice "
                     "in a row (the second time stays).")
    if stats["ai_left_out"]:
        notes.append(f"The AI helper suggested leaving out {stats['ai_left_out']} weak or off-topic "
                     f"sentence{'s' if stats['ai_left_out'] != 1 else ''} (switched off in the sequence).")
    if stats["fit_left_out"]:
        notes.append(f"Left out {stats['fit_left_out']} weaker sentence{'s' if stats['fit_left_out'] != 1 else ''} "
                     f"to fit about {target / 60:.1f} min (switched off in the sequence).")
    if stats["pauses_cut"]:
        notes.append(f"Cut {stats['pauses_cut']} pause{'s' if stats['pauses_cut'] != 1 else ''} longer than "
                     f"{level['pause_s']:g} s, saving {stats['seconds_saved']:.0f} s"
                     + (" (every other cut zooms in a little)" if opts["punch_in"] else "") + ".")
    if stats["trimmed_s"] >= 1:
        notes.append(f"Trimmed {stats['trimmed_s']:.0f} s of silence before the first and after the last words "
                     "of your recordings.")
    if not any(c["include"] for c in clips) and clips:
        clips[0]["include"] = True  # never an empty video
    audio = []
    if opts["music"] == "supplied" and brief.get("music_asset_id") in assets:
        audio.append(_audio_item("a1", assets[brief["music_asset_id"]], "music",
                                 gain_db=float(values.get("music_level_db", -18)),
                                 duck=bool(values.get("duck_music", True)), fade_in_ms=1500, fade_out_ms=2500))
    at = 0
    for aid in brief.get("voiceover_asset_ids") or []:
        if aid in assets:
            item = _audio_item(f"a{len(audio) + 1}", assets[aid], "voiceover", start_ms=at)
            audio.append(item)
            at += engine.item_length(item) or 0
    plan = {"schema": engine.SCHEMA, "timebase": 1000, "engine": engine.ENGINE,
            "output": {"aspect": values.get("aspect_ratio", "16:9"), "fps": int(values.get("frame_rate") or 30)},
            "layout": values.get("layout", "fit"), "clips": clips, "transition": {"type": t_type, "ms": t_ms},
            "title": {"enabled": bool(values.get("title_card")), "text": project["name"], "ms": 2500},
            "captions": {"enabled": values.get("captions", True), "style": values.get("caption_style", "clean"),
                         "position": values.get("caption_position", "bottom"),
                         "size": values.get("caption_size", "medium")},
            "audio": audio, "tracks": engine.default_tracks(), "word_fixes": {},
            "ducking": {"depth_db": float(values.get("duck_depth_db", engine.DUCK_DEPTH_DB))},
            "overlays": [], "outline": outline, "notes": notes}

    # ---- 4. pictures over the video
    if images_for_overlay:
        _place_pictures(plan, images_for_overlay, talks, ai, table, feel, stats)
        matched = stats.pop("matched", 0)
        n, shown = len(images_for_overlay), stats["overlays"]
        when = ("" if not matched else " when its name is said" if shown == 1 else
                ", each when its name is said" if matched == shown else f", {matched} of them when the name is said")
        what = "your image" if n == 1 else f"{shown} of your {n} images" if shown < n else f"your {n} images"
        if shown:
            notes.append(f"Showed {what} over the video while the talking goes on{when}.")
        if shown < n:
            notes.append(f"{n - shown} image{'s' if n - shown != 1 else ''} found no free spot over the video; show "
                         f"or insert {'it' if n - shown == 1 else 'them'} from Pictures over the video.")
    picture_queries = []
    for p in ai.get("pictures") or []:
        where = _where_said(plan, talks, table, p["i"])
        if where:
            picture_queries.append({"query": p["search"], **where})
    # ---- 5. sound: music and effects
    library = ctx.get("library") or {}
    music = ctx.get("music") or {}
    if not any(i["role"] == "music" for i in audio) and music.get("asset_id") in assets:
        m = assets[music["asset_id"]]
        gain = float(values.get("music_level_db", -20 if music.get("how") == "library" else -18))
        audio.append({**_audio_item(f"a{len(audio) + 1}", m, "music", gain_db=gain,
                                    duck=bool(values.get("duck_music", True)), fade_in_ms=1500, fade_out_ms=2500),
                      "auto": True})
        stats["music"] = m["filename"]
        notes.append({"library": f"Added free background music “{m['filename']}” (made by ClipForge on this "
                                 f"computer, free to use) in a {music.get('mood') or feel} mood; it dips while "
                                 "people speak.",
                      "bin": f"Added your music file “{m['filename']}” under the whole video; it dips while "
                             "people speak."}.get(music.get("how"), f"Added music “{m['filename']}”."))
    if opts["sound_effects"] and library:
        _place_effects(plan, library, stats)
        if stats["effects"]:
            notes.append(f"Added {stats['effects']} soft sound effect{'s' if stats['effects'] != 1 else ''} at scene "
                         "changes and pictures (made by ClipForge, free to use).")
    plan["chapters"] = _chapters(plan, talks, table, ai)
    plan["smart"] = {"level": opts["level"], "options": opts,
                     "stats": {**stats, "seconds_saved": round(stats["seconds_saved"], 1),
                               "trimmed_s": round(stats["trimmed_s"], 1)},
                     "ai": {k: ai.get(k) for k in ("provider", "sent", "local", "problems", "windows",
                                                   "skipped_sentences") if k in ai} | (
                         {"used": True} if ai else {"used": False, "problem": ctx.get("ai_problem", "")}),
                     "picture_queries": picture_queries[:6]}
    if ai:
        notes.append(f"The AI helper ({ai.get('provider')}) read what is said and helped choose the cuts"
                     + (", pictures" if ai.get("pictures") else "") + (" and chapters" if plan["chapters"] else "")
                     + ".")
    elif ctx.get("ai_problem"):
        notes.append(f"The AI helper was not used ({ctx['ai_problem']}); ClipForge's built-in editor decided.")
    total = engine.duration_ms(plan) / 1000
    if target and total > target * 1.1 and not opts["fit_length"]:
        notes.append(f"The video is {total / 60:.1f} min; you asked for about {target / 60:.1f} min.")
    return plan


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _locate(plan: dict, asset_id: str, src_ms: int) -> dict | None:
    """The included clip that plays `src_ms` of `asset_id`, with the offset into it."""
    for c in plan["clips"]:
        if c.get("include", True) and c["asset_id"] == asset_id and c["in_ms"] <= src_ms < c["out_ms"]:
            return {"clip_id": c["id"], "offset_ms": max(0, src_ms - c["in_ms"])}
    return None


def _where_said(plan: dict, talks: list[dict], table: list[dict], i: int) -> dict | None:
    if not 0 <= i < len(table):
        return None
    s = table[i]
    return _locate(plan, s["asset_id"], int(s["start"] * 1000) + 100)


def _name_words(filename: str) -> set[str]:
    stem = Path(filename).stem.lower()
    return {w.rstrip("s") for w in re.split(r"[^a-z]+", stem) if len(w) >= 3 and w not in JUNK_NAME
            and w not in STOPWORDS}


def _place_pictures(plan: dict, images: list[dict], talks: list[dict], ai: dict, table: list[dict], feel: str,
                    stats: dict) -> None:
    """Your images over the video: when their name is said (or where the AI helper suggested a matching picture),
    otherwise spread over the longest talking stretches, never in the first 3 s or the last 2 s, 4 s apart."""
    length = OVERLAY_MS.get(feel, 3500)
    segs = {s["clip_id"]: s for s in engine.timeline(plan)}
    total = engine.duration_ms(plan)
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return start >= 3000 and end <= total - 2000 and all(end + 4000 <= a or start >= b + 4000 for a, b in taken)

    def put(img: dict, where: dict, why: str, most: int = 0) -> bool:
        seg = segs.get(where["clip_id"])
        if not seg:
            return False
        start = seg["out_start_ms"] + where["offset_ms"]
        end = min(seg["out_end_ms"], start + (most or length))
        if end - start < 1500 or not free(start, end):
            return False
        taken.append((start, end))
        plan["overlays"].append({"id": f"o{len(plan['overlays']) + 1}", "asset_id": img["id"],
                                 "clip_id": where["clip_id"], "offset_ms": where["offset_ms"],
                                 "length_ms": end - start, "motion": "zoom", "label": img["filename"], "auto": True,
                                 "why": why})
        stats["overlays"] += 1
        return True

    left = []
    for img in images:  # 1. said by name
        names = _name_words(img["filename"])
        done = False
        if names:
            for t in talks:
                for w in t["words"]:
                    tok = re.sub(r"[^a-z]", "", str(w.get("w", "")).lower()).rstrip("s")
                    if tok and tok in names:
                        why = f"you say “{w['w'].strip(' ,.!?')}”"
                        if any(put(img, where, why) for where in _near(plan, segs, t["asset"]["id"],
                                                                        int(w["start"] * 1000), length)):
                            done = True
                            stats["matched"] = stats.get("matched", 0) + 1
                            break
                if done:
                    break
        if not done:
            left.append(img)
    for p in ai.get("pictures") or []:  # 2. where the AI helper wanted a picture of something this image shows
        q = {w.rstrip("s") for w in re.split(r"[^a-z]+", p["search"].lower()) if len(w) >= 3}
        img = next((im for im in left if _name_words(im["filename"]) & q), None)
        where = _where_said(plan, talks, table, p["i"])
        if img and where and put(img, where, f"the AI helper suggested a picture of {p['search']}"):
            left.remove(img)
    if not left:
        return
    # 3. spread the rest over long talking stretches
    bodies = sorted((s for s in segs.values() if s["kind"] == "video" and s["out_end_ms"] - s["out_start_ms"] >= 2500),
                    key=lambda s: s["out_start_ms"])
    for k, img in enumerate(left):
        want = total * (k + 1) / (len(left) + 1)
        best = None  # the free spot closest to an even spread (shortened to fit a gap when needed)
        for s in bodies:
            starts = set(range(max(3000, s["out_start_ms"]), s["out_end_ms"] - 1500 + 1, 250))
            starts |= {b + 4000 for _a, b in taken if s["out_start_ms"] <= b + 4000 <= s["out_end_ms"] - 1500}
            for start in sorted(starts):
                end = min(s["out_end_ms"], start + length, total - 2000)
                if end - start >= 1500 and free(start, end):
                    d = abs((start + end) / 2 - want)
                    if best is None or d < best[0]:
                        best = (d, s["clip_id"], start - s["out_start_ms"], end - start)
        if best:
            put(img, {"clip_id": best[1], "offset_ms": best[2]}, "spread over a long talking stretch", best[3])


def _near(plan: dict, segs: dict, asset_id: str, said_ms: int, length: int):
    """Places for a picture of something said at `said_ms` (source time), best first: just before the word; earlier
    in the same clip so that it still covers the word when the clip ends soon after (a jump cut); the start of the
    next clip when that follows within 1.5 s."""
    where = _locate(plan, asset_id, max(0, said_ms - 300))
    if not where:
        return
    yield where
    seg = segs.get(where["clip_id"])
    if not seg:
        return
    clip_len = seg["out_end_ms"] - seg["out_start_ms"]
    earlier = max(0, clip_len - length)
    if earlier < where["offset_ms"]:
        yield {"clip_id": where["clip_id"], "offset_ms": earlier}
    said_out = seg["out_start_ms"] + where["offset_ms"] + 300
    order = [c["id"] for c in plan["clips"] if c.get("include", True)]
    k = order.index(where["clip_id"]) if where["clip_id"] in order else -1
    if 0 <= k < len(order) - 1:
        nxt = segs.get(order[k + 1])
        if nxt and nxt["kind"] == "video" and nxt["out_start_ms"] - said_out <= 1500:
            yield {"clip_id": order[k + 1], "offset_ms": 0}


def _place_effects(plan: dict, library: dict, stats: dict) -> None:
    """A soft whoosh where one recording changes to the next (and after the title), a softer swish as each picture
    appears. Effects are attached to their clip, so they move with it."""
    from .video_flow import _audio_item  # noqa: PLC0415

    t = plan["transition"]
    half = (t.get("ms") or 0) // 2 if t.get("type") != "cut" else 0
    prev = None
    whooshes = 0
    for c in plan["clips"]:
        if not c.get("include", True):
            continue
        change = (prev is None and plan["title"]["enabled"]) or (prev is not None and c.get("join") != "cut" and
                                                                  prev["asset_id"] != c["asset_id"])
        if change and "whoosh" in library and whooshes < 30:
            item = _audio_item(f"a{len(plan['audio']) + 1}", library["whoosh"], "effect", gain_db=-14.0)
            item.update(anchor={"clip_id": c["id"], "offset_ms": half - 540}, auto=True, label="Whoosh (ClipForge)")
            plan["audio"].append(item)
            whooshes += 1
        prev = c
    swishes = 0
    if "swish" in library:
        for o in plan.get("overlays") or []:
            if swishes >= 20:
                break
            item = _audio_item(f"a{len(plan['audio']) + 1}", library["swish"], "effect", gain_db=-18.0)
            item.update(anchor={"clip_id": o["clip_id"], "offset_ms": o["offset_ms"] - 270}, auto=True,
                        label="Soft swish (ClipForge)")
            plan["audio"].append(item)
            swishes += 1
    stats["effects"] = whooshes + swishes


def _chapters(plan: dict, talks: list[dict], table: list[dict], ai: dict) -> list[dict]:
    """Chapters for a YouTube description: from the AI helper's topic changes, else one per recording when its file
    name says something. YouTube needs at least three, the first at 0:00, each at least 10 s long."""
    marks: list[dict] = []
    for ch in ai.get("chapters") or []:
        where = _where_said(plan, talks, table, ch["i"])
        if where:
            marks.append({"clip_id": where["clip_id"], "offset_ms": max(0, where["offset_ms"] - 100),
                          "title": ch["title"]})
    if not marks:
        for t in talks:
            first = next((c for c in plan["clips"] if c["asset_id"] == t["asset"]["id"] and c.get("include", True)),
                         None)
            name = " ".join(w for w in re.split(r"[^A-Za-z]+", Path(t["asset"]["filename"]).stem)
                            if len(w) >= 3 and w.lower() not in JUNK_NAME)
            if first and name:
                marks.append({"clip_id": first["id"], "offset_ms": 0, "title": name[:60]})
    seen, out = set(), []
    for m in marks:
        if (m["clip_id"], m["offset_ms"]) not in seen:
            seen.add((m["clip_id"], m["offset_ms"]))
            out.append(m)
    return out


def chapter_times(plan: dict) -> list[dict]:
    """The chapters with their times in the current plan, or [] when YouTube would not accept them."""
    segs = {s["clip_id"]: s for s in engine.timeline(plan)}
    rows = sorted(({"title": c["title"], "ms": min(segs[c["clip_id"]]["out_end_ms"] - 1,
                                                    segs[c["clip_id"]]["out_start_ms"] + int(c.get("offset_ms") or 0))}
                   for c in plan.get("chapters") or [] if c.get("clip_id") in segs), key=lambda r: r["ms"])
    if not rows:
        return []
    rows[0]["ms"] = 0
    out = [rows[0]]
    for r in rows[1:]:
        if r["ms"] - out[-1]["ms"] >= 10000:
            out.append(r)
    total = engine.duration_ms(plan)
    if len(out) < 3 or total - out[-1]["ms"] < 10000:
        return []
    return out


def choose_music(project: dict, assets: dict[str, dict], values: dict, mood: str = "") -> dict:
    """Which music a smart edit uses: {"how": "supplied" | "bin" | "library" | "", "asset_id" or "key", "mood"}."""
    brief = project.get("brief") or {}
    opts = options(values, brief)
    mode = opts["music"]
    feel = values.get("feel") or (mood if mood in ("calm", "balanced", "energetic") else "balanced")
    if mode in ("none", "find"):
        return {"how": ""}
    if mode == "supplied":
        return {"how": "supplied", "asset_id": brief.get("music_asset_id")}
    voice = set(brief.get("voiceover_asset_ids") or [])
    if mode == "auto":
        mine = [a for aid in project["asset_ids"] if (a := assets.get(aid)) and a["kind"] == "audio"
                and aid not in voice and not a["filename"].startswith("ClipForge ")
                and float((a.get("probe") or {}).get("duration") or 0) >= 20]
        if mine:
            best = max(mine, key=lambda a: float((a.get("probe") or {}).get("duration") or 0))
            return {"how": "bin", "asset_id": best["id"], "mood": feel}
    from . import library

    return {"how": "library", "key": library.music_key(feel, project["id"]), "mood": feel}

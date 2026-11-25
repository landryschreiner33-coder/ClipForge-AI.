"""Suggested trims for one clip, each with its reason: a tighter start (warm-up words or a warm-up line before the
point), a tighter end (talk after the point, an outro), a start or end that cuts a sentence in half, and how much dead
air "Remove pauses" would take out. Pauses that build tension (after a question, "guess what", "and the answer is")
are kept, here and when the clip is rendered (`tension_pause`, used by render.keep_segments).

Nothing here changes a clip. The clip editor lists the suggestions; Use puts one into the editor's unsaved changes,
so each can be checked on the timeline, saved and undone like any other trim.
"""
from __future__ import annotations

from .text_utils import (AD_PHRASES, CHAT_CHORES, DANGLING_STARTS, OUTRO_PHRASES, PAYOFF_PHRASES, PROMO_PHRASES,
                         RESPONSE_STARTS, SLOW_OPEN_PHRASES, TRANSITION_PHRASES, build_sentences, count_phrases,
                         count_words, ends_sentence, repeat_run, tokens)

PAD = 0.12            # kept before the first word of a new start (the word's attack is never clipped)
END_PAD = 0.35        # kept after the last word of a new end (the sentence's fall is heard)
MIN_SAVING = 0.4      # a trim that saves less than this is not worth suggesting
MIN_LEFT = 8.0        # never suggest a clip shorter than this
LEAD_IN = {"um", "uh", "erm", "hmm", "mm", "ah", "so", "okay", "ok", "alright", "right", "well", "yeah", "like",
           "anyway", "anyways", "now", "oh"}
LEAD_PAIRS = {("you", "know"), ("i", "mean"), ("all", "right")}
# A pause right after these words builds tension: the viewer waits for the answer, so it is kept (shorter).
TENSION_ENDS = ("guess what", "wait for it", "you know what", "here's the thing", "the answer is", "and the answer",
                "it was", "and it was", "turns out", "you won't believe", "watch this", "look at this",
                "and the winner is", "and then", "and suddenly", "and he said", "and she said", "and they said")
TENSION_KEEP = {"light": 1.0, "aggressive": 0.6}   # seconds of a tension pause kept by Remove pauses


def _clean(word: str) -> list[str]:
    return tokens(word)


def tension_pause(before: list[dict]) -> str:
    """Why the pause after these words (the clip's words so far) builds tension; "" when it does not."""
    if not before:
        return ""
    last = str(before[-1].get("w") or "").strip()
    if last.endswith("?"):
        return "after a question"
    if last.endswith(("...", "…", "—", "–")):
        return "after a line left hanging"
    tail = " ".join(t for w in before[-6:] for t in _clean(str(w.get("w") or "")))
    for phrase in TENSION_ENDS:
        if tail == phrase or tail.endswith(" " + phrase):
            return f"after “{phrase}”"
    return ""


def _lead_in(ws: list[dict]) -> int:
    """How many words at the start are warm-up ("so, um, okay") before the first real word (at most five)."""
    k = 0
    while k < min(len(ws), 6):
        t = _clean(ws[k]["w"])
        if not t:
            k += 1
            continue
        pair = tuple(_clean(ws[k]["w"]) + _clean(ws[k + 1]["w"]))[:2] if k + 1 < len(ws) else ()
        if len(t) == 1 and pair in LEAD_PAIRS:
            k += 2
            continue
        if len(t) == 1 and t[0] in LEAD_IN:
            k += 1
            continue
        break
    return k if k <= 5 else 0


def _sentence_text(s: dict) -> str:
    return " ".join(s.get("text", "").lower().split())


def suggest(words: list[dict], start: float, end: float, silence: str = "off", fps: float = 30.0,
            all_words: list[dict] | None = None, loud: list[tuple[float, float]] | None = None) -> dict:
    """Suggestions for the clip [start, end] given the transcript's words (all of them, or those around the clip).

    Returns {"suggestions": [{"id", "label", "edit", "seconds", "why"}], "kept_pauses": [{"at", "seconds", "why"}],
    "length": end - start}. "seconds" is how much shorter (negative: longer) the clip gets. `loud` (render.heard):
    reactions without words, which Remove pauses keeps."""
    from .render import SILENCE_PRESETS, keep_segments

    everything = all_words if all_words is not None else words
    ws = [w for w in words if w["end"] > start + 0.02 and w["start"] < end - 0.02]
    out: list[dict] = []
    kept: list[dict] = []
    length = end - start
    if not ws:
        return {"suggestions": out, "kept_pauses": kept, "length": round(length, 2)}
    sents = build_sentences(ws)
    new_start, new_end = start, end

    # --- a start or an end that cuts a sentence in half: the clip opens or stops mid-thought
    before = [w for w in everything if w["end"] <= ws[0]["start"] + 1e-6]
    if before and not ends_sentence(before[-1]["w"]) and ws[0]["start"] - before[-1]["end"] < 0.45:
        k = len(before) - 1
        while k > 0 and not ends_sentence(before[k - 1]["w"]) and before[-1]["end"] - before[k]["start"] < 12.0:
            k -= 1
        if before[-1]["end"] - before[k]["start"] < 12.0 and (k == 0 or ends_sentence(before[k - 1]["w"])):
            to = max(0.0, before[k]["start"] - PAD)
            out.append({"id": "start_mid_sentence", "label": "Start where the sentence starts", "edit": {"start":
                        round(to, 2)}, "seconds": round(-(start - to), 2),
                        "why": f"The clip opens in the middle of a sentence (“…{ws[0]['w']}”); starting "
                               f"{start - to:.1f} s earlier on “{before[k]['w']}” gives the viewer the whole "
                               "thought."})
    after = [w for w in everything if w["start"] >= ws[-1]["end"] - 1e-6]
    if after and not ends_sentence(ws[-1]["w"]) and after[0]["start"] - ws[-1]["end"] < 0.6:
        k = 0
        while k < len(after) - 1 and not ends_sentence(after[k]["w"]) and after[k]["end"] - ws[-1]["end"] < 8.0:
            k += 1
        if ends_sentence(after[k]["w"]) and after[k]["end"] - ws[-1]["end"] < 8.0:
            to = after[k]["end"] + END_PAD
            out.append({"id": "end_mid_sentence", "label": "End where the sentence ends",
                        "edit": {"end": round(to, 2)}, "seconds": round(-(to - end), 2),
                        "why": f"The clip stops in the middle of a sentence (“{ws[-1]['w']}…”); ending "
                               f"{to - end:.1f} s later on “{after[k]['w']}” lets the line land."})

    # --- warm-up before the point: words ("so, um") or a whole line ("hey guys, welcome back")
    lead = _lead_in(ws)
    if lead and lead < len(ws):
        to = max(start, ws[lead]["start"] - PAD)
        if to - start >= MIN_SAVING and end - to >= MIN_LEFT:
            said = ", ".join(w["w"].strip(",.!?").lower() for w in ws[:lead])
            out.append({"id": "lead_in", "label": "Start on the first real word", "edit": {"start": round(to, 2)},
                        "seconds": round(to - start, 2),
                        "why": f"Skips “{said}” ({to - start:.1f} s) so the first thing heard is the point."})
            new_start = to
    if len(sents) >= 3 and count_phrases(_sentence_text(sents[0]), SLOW_OPEN_PHRASES):
        second = sents[1]
        first_word = (tokens(second["text"]) or [""])[0]
        to = second["start"] - PAD
        if first_word not in DANGLING_STARTS and to - start >= MIN_SAVING and end - to >= MIN_LEFT:
            out.append({"id": "warm_up", "label": "Cut the warm-up line", "edit": {"start": round(to, 2)},
                        "seconds": round(to - start, 2),
                        "why": f"“{sents[0]['text'][:70]}” is a warm-up; the clip makes sense from "
                               f"“{second['text'][:50]}”."})

    # --- talk after the point: an outro or promo at the end, or replies and a change of topic after the payoff
    tail = len(sents)
    while tail > 1 and (count_phrases(_sentence_text(sents[tail - 1]), OUTRO_PHRASES + PROMO_PHRASES)
                        or count_words(_sentence_text(sents[tail - 1]), CHAT_CHORES + AD_PHRASES)):
        tail -= 1
    if tail < len(sents):
        to = sents[tail - 1]["end"] + END_PAD
        if end - to >= MIN_SAVING and to - new_start >= MIN_LEFT:
            out.append({"id": "outro", "label": "Cut the outro", "edit": {"end": round(min(end, to), 2)},
                        "seconds": round(end - min(end, to), 2),
                        "why": f"Ends on “{sents[tail]['text'][:60]}” instead of stopping on the point."})
            new_end = min(end, to)
    elif repeat_run([s["text"] for s in sents]) and len(sents) >= 4:
        run = repeat_run([s["text"] for s in sents])
        cut = len(sents) - run
        to = sents[cut - 1]["end"] + END_PAD if cut > 0 else end
        if cut > 0 and end - to >= MIN_SAVING and to - new_start >= MIN_LEFT:
            out.append({"id": "repeats", "label": "End before it repeats itself", "edit": {"end": round(to, 2)},
                        "seconds": round(end - to, 2),
                        "why": f"The last {run} lines say the same thing (“{sents[cut]['text'][:50]}”); ending on "
                               f"“{sents[cut - 1]['text'][:50]}” keeps the point sharp."})
            new_end = to
    else:
        payoff = max((k for k, s in enumerate(sents) if count_phrases(_sentence_text(s), PAYOFF_PHRASES)),
                     default=None)
        if payoff is not None and payoff < len(sents) - 1:
            rest = sents[payoff + 1:]
            drift = all((tokens(s["text"]) or [""])[0] in RESPONSE_STARTS
                        or count_phrases(_sentence_text(s), TRANSITION_PHRASES)
                        or count_words(_sentence_text(s), CHAT_CHORES) for s in rest)
            to = sents[payoff]["end"] + END_PAD
            if drift and end - to >= 2.0 and to - new_start >= MIN_LEFT:
                out.append({"id": "after_payoff", "label": "End on the point", "edit": {"end": round(to, 2)},
                            "seconds": round(end - to, 2),
                            "why": f"After “{sents[payoff]['text'][:60]}” the talk drifts "
                                   f"({end - to:.1f} s of replies or a new topic)."})
                new_end = to

    # --- dead air: what Remove pauses (light) would take out, and the pauses it keeps because they build tension
    for k in range(len(ws) - 1):
        gap = ws[k + 1]["start"] - ws[k]["end"]
        why = tension_pause(ws[:k + 1]) if gap > SILENCE_PRESETS["light"][0] else ""
        if why:
            kept.append({"at": round(ws[k]["end"], 2), "seconds": round(min(gap, TENSION_KEEP["light"]), 2),
                         "why": f"Builds tension: a pause {why}"})
    if silence not in SILENCE_PRESETS:
        segs = keep_segments(ws, new_start, new_end, "light", fps, loud=loud)
        saved = (new_end - new_start) - sum(b - a for a, b in segs)
        if saved >= 0.8:
            n = max(0, len(segs) - 1)
            one = len(kept) == 1
            note = (f"; keeps {len(kept)} pause{'' if one else 's'} that build{'s' if one else ''} tension"
                    if kept else "")
            out.append({"id": "dead_air", "label": "Remove the dead air", "edit": {"silence": "light"},
                        "seconds": round(saved, 2),
                        "why": f"Takes out {n} pause{'s' if n != 1 else ''} ({saved:.1f} s) where nobody "
                               f"speaks{note}."})
    return {"suggestions": out, "kept_pauses": kept, "length": round(length, 2)}

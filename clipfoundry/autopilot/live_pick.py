"""Which moment of a live stream becomes a clip: quality over quantity.

A stream is long and mostly ordinary. Taking every moment that passes the app's minimum quality makes dozens of
clips an hour, far more than the posting pace uploads, and the weak ones go out first. So a live moment has to be

* strong on its own: its score is at or above the minimum quality plus the stream's margin (`above`);
* strong for this stream: once enough of the stream was heard, it beats most of the stream's own minutes (`top`),
  and more of them with every clip the hour already has;
* settled: it ended a while ago (`hold`) and nothing stronger is still being said, so the better of two moments
  close together is the one taken;
* within the pace: so many clips per recorded hour (`per_hour`) and so far apart (`gap`), not in the first minutes
  (`warm`). One standout moment an hour may go over the pace.

The score is the same kind of estimate as a recorded video's Clip Score (Viral Potential with bounded, explained
adjustments), plus how lively the moment sounds compared with the rest of the stream: louder than usual, a shout,
laughter or a crowd without words, a voice that moves. All of it is estimated from the words and the sound; none
of it is a platform's number.

Everything here is plain arithmetic on what `live.detect` hands over, so it can be tested without a recording.
"""
from __future__ import annotations

import numpy as np

from .. import config
from ..pipeline import deep, semantic

# How picky a stream is, by the owner's choice for that stream. Times are in recorded minutes.
#   per_hour  clips per recorded hour, at most (None: no limit)
#   gap       minutes between the starts of two clips, at least (one long scene is not clipped three times)
#   hold      minutes a moment must have been over before it is taken
#   warm      minutes of stream before the first clip: a stream opens with a waiting screen and small talk, and
#             the stream has to be heard for a while before a moment can be compared with it
#   above     points above the app's minimum quality
#   top       share of the stream's own minutes the moment must beat (0 = no such rule); it rises with every clip
#             already made in the hour, up to "the best the stream has had" for the hour's last clip
PICKS: dict[str, dict] = {
    "best": {"per_hour": 3, "gap": 3, "hold": 2, "warm": 6, "above": 5.0, "top": 0.85},
    "balanced": {"per_hour": 6, "gap": 2, "hold": 1, "warm": 4, "above": 0.0, "top": 0.6},
    "most": {"per_hour": None, "gap": 0, "hold": 0, "warm": 0, "above": 0.0, "top": 0.0},
}
DEFAULT_PICK = "best"
LABELS = {"best": "Only the best moments", "balanced": "Balanced", "most": "Every good moment"}
STANDOUT = 15.0      # this far above the stream's bar a moment is taken despite the pace (one extra an hour)
MIN_HISTORY = 6      # minutes of the stream that must have been rated before it is compared with itself
POOL = 20            # moments looked at per minute (the recorded analysis looks at 60 of a whole video)
VOICE_TOP = 4        # ... of which this many get their voice listened to
LIFT = (-2.0, 8.0)   # what a lively or flat sound can change, in points
LIVELY_USUAL = 0.2   # the liveliness of an ordinary minute: neither helps nor hurts
OVERLAP = 0.15       # a moment sharing more than this of its length with a clip is that clip again


FRAMING_LABELS = {"auto": "Split view when there is a face cam", "split": "Always split view",
                  "off": "No split view"}


def rule(name: str | None) -> dict:
    """The pace and bars of one pickiness, with its name."""
    name = name if name in PICKS else DEFAULT_PICK
    return {"name": name, **PICKS[name]}


def choices(src: dict, settings: dict) -> dict:
    """How this stream's clips are framed and how picky it is: what the owner chose when adding the stream, else
    the Settings. Stored with the stream's project, so a later change of the Settings never changes a stream that
    is already being clipped. A split-view choice is the clips' layout; "off" leaves the layout to Settings."""
    chosen = (src.get("intake") or {}).get("live_choices") or {}
    framing = chosen.get("framing") if chosen.get("framing") in config.LIVE_FRAMINGS else \
        settings.get("autopilot_live_framing")
    framing = framing if framing in config.LIVE_FRAMINGS else "auto"
    pick = chosen.get("pick") if chosen.get("pick") in PICKS else settings.get("autopilot_live_pick")
    # "off" also switches off the Settings' own split view (render.cam_layout), which would otherwise look for a cam
    return {"live_framing": framing, "live_pick": pick if pick in PICKS else DEFAULT_PICK,
            **({"layout": framing} if framing != "off" else {"split_view": "off"})}


def pace(project: dict | None, settings: dict) -> dict:
    """The pace and bars of a stream (`rule`). A stream started before it had choices uses the Settings."""
    return rule(((project or {}).get("options") or {}).get("live_pick") or settings.get("autopilot_live_pick"))


def liveliness(audio: dict, voice: dict | None) -> tuple[float, list[str]]:
    """How lively a moment sounds, 0-1, and what made it so. `audio` is deep.audio_features (loudness against the
    stream's usual level), `voice` is ears.analyze (pitch, emphasis, laughter) or None when the sound was not
    kept."""
    parts = [(0.30, max(0.0, min(1.0, float(audio.get("mean_z") or 0.0) / 1.2)), "louder than the stream usually is"),
             (0.25, max(0.0, min(1.0, (float(audio.get("peak_z") or 0.0) - 1.0) / 2.0)), "a shout or a loud burst"),
             (0.20, min(1.0, float(audio.get("reactions") or 0) / 2.0), "loud moments without words (laughter, a "
                                                                        "crowd, the game)")]
    if voice:
        parts.append((0.25, max(0.0, min(1.0, float(voice.get("score") or 0.0))), "a voice that rises and falls"))
    weight = sum(w for w, _, _ in parts)
    value = sum(w * v for w, v, _ in parts) / weight
    return round(value, 3), [label for _, v, label in parts if v >= 0.5]


def rate(r: dict, sents: list[dict], words: list[dict], loud, emb, voice: dict | None = None) -> dict:
    """The live score of an analysed moment (`r` is virality.analyze's result for sentences s0..s1 of `sents`):
    {"score", "why", "lively", "audio", "voice"}."""
    texts = [sents[k]["text"] for k in range(r["s0"], r["s1"] + 1)]
    sem = semantic.features(emb, r["s0"], r["s1"])
    audio = deep.audio_features(r["start"], r["end"], words, loud)
    shaped = {"score": float(r["viral_potential"]),
              "deep": {"semantic": sem, "audio": audio, "extras": deep.text_extras(texts, sem, r["end"] - r["start"],
                                                                                   None),
                       "visual": None, "prosody": voice, "seen": None}}
    base, why = deep.clip_score(shaped)
    lively, signs = liveliness(audio, voice)
    lift = max(LIFT[0], min(LIFT[1], 20.0 * (lively - LIVELY_USUAL)))
    if abs(lift) >= 0.5:
        why.append(f"{lift:+.1f} " + ("livelier than the rest of the stream: " + ", ".join(signs) if lift > 0 and signs
                                      else "livelier than the rest of the stream" if lift > 0
                                      else "quieter and flatter than the rest of the stream")
                   + " (estimated from the sound)")
    return {"score": round(max(0.0, min(100.0, base + lift)), 1), "why": why, "lively": lively, "audio": audio,
            "voice": voice}


def stream_bar(minute_best: dict, share: float) -> float | None:
    """The score a moment must reach to beat `share` of the stream's own minutes so far (None: no rule, or not
    enough of the stream rated yet)."""
    values = [float(v) for v in (minute_best or {}).values()]
    if share <= 0 or len(values) < MIN_HISTORY:
        return None
    return float(np.quantile(values, share))


def overlaps(a: dict, b: dict, share: float = OVERLAP) -> bool:
    return min(a["end"], b["end"]) - max(a["start"], b["start"]) > share * (a["end"] - a["start"])


def choose(rated: list[dict], *, clips: list[dict], edge: float, unit: float, floor: float, pace: dict,
           minute_best: dict, edge_margin: float) -> tuple[dict | None, str]:
    """The moment to clip now, or None and why not: "warming" (the stream just started), "nothing" (no moment),
    "floor" (none strong enough), "stream" (none strong enough for this stream), "pace" (the hour's clips are
    made), "gap" (too close to a clip), "settling" (the strongest moment is still being said or may be topped:
    wait for it). The reason is the strongest moment's: that is what the owner is waiting for.

    `rated` are moments with "start", "end" and "live_score"; `clips` the stream's clips so far; `edge` how much
    of the stream is recorded; `unit` the length of a recorded minute in seconds."""
    if edge < pace["warm"] * unit:
        return None, "warming"
    if not rated:
        return None, "nothing"
    made = sum(1 for c in clips if c["start"] > edge - 60 * unit)
    usual = stream_bar(minute_best, pace["top"])
    # Each clip already made this hour raises the bar for the next one, so the hour's clips are not simply the
    # first few good moments: the last one has to be among the very best the stream has had.
    share = pace["top"] + (1.0 - pace["top"]) * min(1.0, made / pace["per_hour"]) if pace["per_hour"] else pace["top"]
    bar = stream_bar(minute_best, share)
    hold = max(edge_margin, pace["hold"] * unit)
    reason = ""
    for r in sorted(rated, key=lambda item: item["live_score"], reverse=True):
        score = float(r["live_score"])
        if score < floor:
            reason = reason or "floor"
            break
        standout = score >= max(floor, usual or 0.0) + STANDOUT
        if bar is not None and score < bar and not standout:
            reason = reason or "stream"
            break
        if pace["per_hour"] is not None and made >= pace["per_hour"] + (1 if standout else 0):
            reason = reason or "pace"
            if not standout:
                break  # weaker ones are no standouts either
            continue
        if not standout and any(abs(r["start"] - c["start"]) < pace["gap"] * unit for c in clips):
            reason = reason or "gap"
            continue
        if r["end"] > edge - hold:
            if pace["hold"] > 0:
                return None, reason or "settling"  # wait for it rather than take a weaker moment now
            reason = reason or "settling"
            continue  # no hold-back: a moment still being said only waits for its own turn
        return r, "taken"
    return None, reason or "floor"


NOTES = {
    "warming": "Listening: the first minutes of a stream are not clipped",
    "nothing": "Listening for a strong moment",
    "floor": "Listening: nothing strong enough yet",
    "stream": "Listening: waiting for one of this stream's best moments",
    "pace": "This hour's clips are made; only a standout moment is added before the hour is over",
    "gap": "A clip was just made; the next one comes a few minutes later",
    "settling": "A strong moment just happened; waiting a moment in case a better one follows",
    "taken": "Making a clip",
    "stopped": "Clipping stopped by you; clips already made still upload",
}


def total_cap(pace: dict, per_video: int, recorded_s: float) -> int:
    """How many clips the whole stream may end up with, the ones added from the full recording included: the
    pace over its length, and never fewer than a recorded video gets."""
    if pace["per_hour"] is None:
        return per_video
    hours = max(0.0, recorded_s) / 3600.0
    return max(per_video, int(np.ceil(hours * pace["per_hour"])))

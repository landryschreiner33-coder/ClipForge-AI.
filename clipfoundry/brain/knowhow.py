"""ClipForge AI's craft know-how: what good editors know, as short playbooks in plain words with the numbers an
editor needs (docs/clipforge/CLIPFORGE_AI.md, "Know-how").

The playbooks were distilled in November 2026 from two guides the owner gave ClipForge AI (a cinematic filmmaking and
post-production guide and a viral short-form video strategy guide) and from ClipForge's own editing rules. They are
built in: the same on every computer, never sent anywhere on their own, and the owner's memories always win over
them (a model reads the memories first and is told so). Because they are plain words, a small local model can use
them, and the chat can answer with them when no model is set up.

`select(query, task)` picks the few playbooks that fit a question or a job, inside a character budget, the way
`memories.recall` picks memories; `answer(query)` is the one playbook that answers a question on its own;
`principles(task)` is the one-line reminder a task's system prompt carries.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..pipeline.text_utils import content_tokens

HEADER = "ClipForge AI's craft know-how (built in; what the owner said always wins over it):"
TASKS = ("chat", "clips", "change", "smart_edit", "finish", "post")
SELECT_MIN = 0.20     # share of a question's (weighted) words a playbook must cover to be picked for it
ANSWER_MIN = 0.30     # ... to answer the question on its own, without a model
SOURCE = ("Distilled from two guides the owner gave ClipForge AI in November 2026 (cinematic filmmaking and "
          "post-production; viral short-form video strategy) and ClipForge's own editing rules.")


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    summary: str
    tasks: tuple[str, ...]
    lines: tuple[str, ...]
    words: tuple[str, ...] = ()   # other words a question may use for it

    @property
    def text(self) -> str:
        return f"{self.title}: " + " ".join(self.lines)


TOPICS: tuple[Topic, ...] = (
    Topic("hooks", "Hooks and openings", "The first three seconds: what grabs a viewer and what loses one.",
          ("chat", "clips", "change", "smart_edit", "post"), (
              "The first 3 seconds decide: open on the strongest line, with no greeting, no 'in this video' and no "
              "setup; the point lands within 3 seconds.",
              "On the first frame, three things at once: something moving, a 3-6 word headline on screen and the "
              "voice already speaking.",
              "A loss or a warning ('stop doing this', 'the mistake that costs you') hooks better than a promise; "
              "a question the clip answers later beats a summary.",
              "Starting in the middle of the action beats an introduction; 'you', numbers, names and specifics "
              "pull people in.",
              "Plain words a ten-year-old understands, 180-210 words a minute, and sentences joined by 'but' or "
              "'therefore', never 'and then'."),
          ("opening", "open", "start", "first seconds", "intro", "intros", "grab", "attention", "headline",
           "title", "scroll", "hook rate", "beginning", "curiosity")),
    Topic("endings", "Endings and loops", "Stop on the payoff; no outro; where a call to action goes.",
          ("chat", "clips", "change", "smart_edit"), (
              "Stop 2-3 seconds after the payoff. No 'to recap', 'in conclusion', 'let me know in the comments', "
              "'follow for part two' or 'thanks for watching'.",
              "A call to action belongs in the middle third of the video, never at the end, and never announces "
              "that the video is ending.",
              "A short that loops well ends on a line that leads back into its first line, with the same framing "
              "and the same sound bed.",
              "Hide the ending: the viewer should not see it coming."),
          ("end", "ending", "outro", "finish", "last", "loop", "looping", "cta", "call to action", "comments",
           "subscribe", "recap", "conclusion", "sign off")),
    Topic("pacing", "Pacing and cuts", "Why and when to cut, shot lengths, and how often something must change.",
          ("chat", "change", "smart_edit", "finish"), (
              "Cut for emotion first, then story, then rhythm (Walter Murch: 51, 23 and 10 percent); eye line and "
              "screen position come after that.",
              "Let a reaction land before the cut; cut to the listener a few frames after the speaker starts (a "
              "J-cut of 4-8 frames).",
              "Shot length: a modern average of 3-6 s, action 2-3 s, never under 1.5 s; vary the tempo, because a "
              "flat rhythm bores more than a slow one.",
              "Shorts: something changes every 2-5 s (a push-in from 100 to 106 percent over 4 s, a B-roll cut on "
              "a key word, a caption pop); a still frame longer than 2-3 s loses viewers.",
              "Long videos: a visual change every 5-7 s, a bigger one every 30-60 s, a new promise every 2-3 "
              "minutes; fast cuts never save a slow idea."),
          ("cut", "cuts", "cutting", "rhythm", "tempo", "speed", "slow", "fast", "boring", "shot length", "j-cut",
           "l-cut", "match cut", "jump cut", "transition", "transitions", "b-roll", "pattern interrupt", "zoom",
           "punch in", "dynamic", "flow", "edit", "editing")),
    Topic("captions", "Captions and safe zones", "Caption size, timing, colour and where the phone apps cover.",
          ("chat", "clips", "change", "finish"), (
              "Captions 1-3 words at a time, timed to the voice, in a bold sans-serif with a 4-8 px stroke or a "
              "deep shadow; the key word in one accent colour (yellow, lime or cyan).",
              "Keep captions 45-55 percent from the top of a 9:16 frame and faces in the upper middle; the headline "
              "on screen is 3-6 words, centred, above the face.",
              "Phone apps cover the top 15 percent and the bottom 35 percent of a 9:16 frame, 11 percent on the left "
              "and 28 percent on the right in the lower half: nothing important goes there.",
              "A 1080p source cropped to 9:16 is upscaled 1.78 times, so keep the subject centred; a 4K source "
              "stays sharp (1215 x 2160)."),
          ("subtitles", "subtitle", "caption", "text", "font", "safe zone", "safe zones", "covered", "buttons",
           "stroke", "outline", "readable", "framing", "crop", "reframe", "9:16", "vertical", "face", "faces",
           "position", "placement", "words on screen")),
    Topic("sound", "Voice and sound mix", "Levels, the voice chain, music under speech and loudness targets.",
          ("chat", "change", "finish", "smart_edit"), (
              "Loudness order: the voice first (peaks -6 to -12 dBFS), hard effects next (-10 to -20), ambience "
              "under it (-30 to -40), music under speech at -20 to -30.",
              "Voice chain: denoise, high-pass 80-100 Hz, cut 200-400 Hz by 3-4 dB, boost 2.5-5 kHz by 2-3 dB, "
              "de-ess 6-8 kHz, compress 2.5:1 to 3.5:1 with 3-6 dB of gain reduction.",
              "Music under speech: notch 1-4 kHz by 3-6 dB and duck 3-5 dB with a 150-250 ms release; never cut to "
              "pure silence, lay room tone under every edit.",
              "Every effect needs three layers of sound: the hit, the body and the tail; a sub-bass drop at 40-60 "
              "Hz sells a big moment.",
              "Deliver at -14 LUFS and -1 dBTP for YouTube, TikTok and Instagram, -16 LUFS for podcasts, -23 (EBU) "
              "or -24 (US TV) for broadcast; check the mix on a phone speaker."),
          ("loud", "loudness", "lufs", "volume", "level", "levels", "mix", "mixing", "audio", "voice", "dialogue",
           "noise", "hiss", "echo", "eq", "compressor", "compression", "de-ess", "sibilance", "ducking", "duck",
           "quiet", "clean sound", "room tone", "silence", "normalize", "normalise", "db", "decibels", "bass")),
    Topic("music", "Music by mood", "Which music fits which feeling, tempo, and how to hit the moment.",
          ("chat", "smart_edit", "finish", "change"), (
              "Choose the mood before the track: wonder is bright and open (Lydian), happy is major (Ionian), "
              "adventurous is Mixolydian, hopeful is Dorian, sad is minor (Aeolian), fear is Phrygian or Locrian.",
              "Tempo follows the cut: 60-80 BPM calm or sad, 90-110 hopeful or balanced, 120-160 action or happy, "
              "140 and up energetic.",
              "Horror: low drones, long silences, sudden stabs. Suspense: a pulse and a rising line. Victory: brass "
              "and a wide major chord. Loneliness: one instrument and a lot of room.",
              "Hard-sync a hit to the key moment; let the music fall to 12-24 frames of silence right before the "
              "payoff, then come back bigger.",
              "A sudden move to a distant chord (a chromatic mediant) marks a reveal or a twist; dissonance that "
              "never resolves keeps dread alive."),
          ("music", "track", "song", "soundtrack", "bpm", "mood", "sad", "happy", "scary", "horror", "tense",
           "suspense", "epic", "calm", "energetic", "beat", "drop", "instrument", "chord", "melody", "background")),
    Topic("colour", "Colour by mood", "Correct before you grade; waveform targets; palettes by genre.",
          ("chat", "finish", "change"), (
              "Correct first (exposure, white balance, skin), grade second; never grade on top of a wrong exposure.",
              "On the waveform: shadows 0-33 IRE, mids 33-66, highlights 66-100, skin 15-75 by complexion; a film "
              "look holds everything between 2 and 92 IRE.",
              "Lighting ratios: high key 1:1 to 2:1, natural 4:1, low key 8:1 to 16:1; grain at 15-25 percent and "
              "halation kept subtle sell film.",
              "By mood: horror desaturated blues and greens, low key; natural warm earth tones at 4:1; dream or "
              "romance warm golds, soft, 2:1; action teal and orange, full range; mystery slate blues, 4:1 to 8:1.",
              "8-bit footage bands when pushed: lift and saturate gently, and add grain before heavy colour moves."),
          ("color", "colors", "colour", "colours", "grade", "grading", "look", "looks", "lut", "warm", "cold",
           "teal", "orange", "cinematic", "film look", "exposure", "white balance", "skin", "contrast", "saturation",
           "grain", "dark", "bright", "tone", "palette", "lumetri")),
    Topic("effects", "Effects that earn their place", "Which effects are worth it, and the rule that each one needs its sound.",
          ("chat", "finish", "change"), (
              "Effects that earn their place, best value first: an invisible split screen, removing an object, "
              "atmosphere (dust, fog, rain), relighting, a replaced phone screen, a stop trick, 3D tracked text, a "
              "set extension, green screen, dream distortion, a portal.",
              "An effect is finished only with its sound, and it serves the story: if a viewer notices the effect "
              "instead of the moment, cut it.",
              "In shorts, whip pans, crash zooms, match cuts and kinetic typography on accent words are pattern "
              "interrupts, one every 2-5 seconds at most.",
              "Hide the seams: motion blur that matches the shutter, grain over the composite, the same black level "
              "in every layer."),
          ("effect", "effects", "vfx", "visual effects", "motion graphics", "animation", "animated", "overlay",
           "green screen", "tracking", "typography", "titles", "glitch", "flash", "shake", "effectcraft",
           "transition effect", "fancy")),
    Topic("clips", "Picking a clip", "What makes a moment work on its own, lengths, and the numbers that matter.",
          ("chat", "clips"), (
              "A clip stands alone: no 'as I said', no reply to something outside it, no topic change inside; at "
              "most 3 seconds of exposition.",
              "It has a tiny arc: a premise, a barrier, a resolution; friction, a counter-intuitive claim or a "
              "vulnerable admission carries it.",
              "Under 15 s needs 80 percent of viewers to finish it, 15-30 s 60 percent, 30-60 s 45 percent; a hook "
              "rate (3-second views over impressions) under 20 percent fails, 25-40 is average, 60-70 is top.",
              "Shares (1 percent of views and up) and saves (2 percent and up) matter more than likes; over 50 "
              "percent leaving in the first 3 seconds stops distribution.",
              "Sub-frame edits with 4-10 ms crossfades, room tone underneath and a matched spectrum join two takes "
              "without a seam; never change what was meant."),
          ("clip", "clips", "pick", "choose", "best moment", "moments", "highlight", "viral", "views", "completion",
           "watch time", "shares", "saves", "likes", "length", "long", "short", "seconds", "frankenbite", "take",
           "standalone")),
    Topic("platforms", "Platforms and export", "Export settings, how each platform judges a short, and the first words.",
          ("chat", "finish", "post"), (
              "Export 1080 x 1920, 30 or 60 fps (24 or 30 for story pieces), H.264 High profile, 4:2:0, Rec. 709, "
              "a keyframe every half second, 18-22 Mbps; AAC 48 kHz at 256-320 kbps.",
              "YouTube Shorts run up to 3 minutes and are judged on viewed versus swiped away (70-80 percent is "
              "good); TikTok on watch time, completion, rewatches, shares and saves; Reels on sends per reach (2-3 "
              "percent and up), and over 3 minutes is held back.",
              "Say the keyword in the first 3-5 seconds and show it on screen; write a 100-200 word caption with "
              "3-5 niche hashtags, never #fyp.",
              "Since the platforms' 2025 retention changes a calm, intentional edit beats a gimmick; the hook still "
              "has to land on frame one."),
          ("export", "render", "bitrate", "resolution", "format", "codec", "fps", "frame rate", "upload", "youtube",
           "shorts", "tiktok", "instagram", "reels", "platform", "platforms", "hashtag", "hashtags", "seo", "keyword",
           "description", "post", "publish", "algorithm", "quality")),
    Topic("retention", "Reading a retention graph", "What each shape of the audience-retention curve means.",
          ("chat", "post"), (
              "A cliff in the first 3 seconds: the hook or the thumbnail promised something else.",
              "A valley in the middle: a slow passage; cut it, or add a change of picture, pace or sound there.",
              "A drop at a chapter: the chapter title gave the answer away; name the question, not the answer.",
              "A fall at the end: the outro; end on the payoff instead.",
              "A flat line that climbs at the end: the loop works and people watched twice."),
          ("retention", "graph", "analytics", "drop", "drop off", "leave", "leaving", "stats", "statistics",
           "performance", "views fell", "audience", "rewatch", "curve", "dropped")),
    Topic("talking", "Talking-head edits", "Pauses and takes, punch-ins, more than one speaker, pictures on cue.",
          ("chat", "smart_edit", "change"), (
              "Cut pauses over 0.4-0.7 s, false starts and the weaker of two takes (usually the earlier one); keep "
              "the breaths that carry feeling.",
              "Alternate a wide and a 10 percent punch-in at sentence changes; push in on the sentence with the key "
              "word and ease back out after it.",
              "Two or more speakers: an eased camera that follows the one talking, or a stacked 50/50 split; a "
              "blurred pillarbox is the weakest choice.",
              "Show the number, the name or the thing on screen the moment it is said; a picture every 5-7 seconds "
              "keeps a talking head alive."),
          ("talking head", "interview", "podcast", "speaker", "speakers", "pauses", "pause", "um", "filler",
           "takes", "retake", "split screen", "two people", "guest", "pictures", "image", "images", "vlog")),
)
BY_ID = {t.id: t for t in TOPICS}

# What a job reads when the words do not pick anything better (in this order).
DEFAULTS = {
    "clips": ("hooks", "clips", "endings"),
    "change": ("pacing",),
    "smart_edit": ("talking", "endings", "pacing"),
    "finish": ("colour", "effects", "sound"),
    "post": ("hooks", "platforms"),
    "chat": (),
}

# The one-line reminder a task's system prompt carries (the playbooks above are the detail).
PRINCIPLES = {
    "clips": ("Judge like a short-form editor: the first 3 seconds must grab without a greeting or setup; a loss or "
              "warning framing and an open question hook best; the clip must stand alone and stop 2-3 seconds after "
              "its payoff; an outro line ('to recap', 'follow for part two', 'thanks for watching') is a weak ending."),
    "change": ("Edit like a good editor: emotion and story before rhythm, the first 3 seconds carry the hook, "
               "captions 1-3 words timed to the voice, music 20-30 dB under speech, and end 2-3 seconds after the "
               "payoff with no outro."),
    "smart_edit": ("Keep the strongest line first, cut warm-ups and repeated takes, keep reactions, leave out outro "
                   "lines ('to recap', 'thanks for watching') unless the brief wants them, and change something every "
                   "few seconds."),
    "finish": ("Correct before you grade, pick the look by the mood, keep only effects that serve the story and give "
               "each its sound, and keep the voice first in the mix."),
    "post": ("The on-screen hook is 3-6 plain words; a loss or warning framing beats a promise; a title says the "
             "keyword early; 3-5 specific hashtags, never #fyp."),
}


# ------------------------------------------------------------------ matching words
def _terms(text: str) -> set[str]:
    toks = content_tokens(text)
    return set(toks) | {f"~{t[:4]}" for t in toks if len(t) >= 4} | {f"{a}_{b}" for a, b in zip(toks, toks[1:])}


def _strong_terms(t: Topic) -> set[str]:
    """The words a playbook is about: its title and the words a question may use for it."""
    out = _terms(t.title)
    for w in t.words:
        out |= _terms(w)
    return out


_STRONG = {t.id: _strong_terms(t) for t in TOPICS}
_TERMS = {t.id: _STRONG[t.id] | _terms(" ".join((t.summary, *t.lines))) for t in TOPICS}
_DF: dict[str, int] = {}
for _ts in _TERMS.values():
    for _term in _ts:
        _DF[_term] = _DF.get(_term, 0) + 1
_N = len(TOPICS)
WEAK = 0.5  # a word that only appears inside a playbook's lines counts half as much as one it is about


def _idf(term: str) -> float:
    df = _DF.get(term, 0)
    return math.log((_N + 1) / (1 + df)) if df else 0.0


def score(query: str, topic: Topic) -> float:
    """The share of the question's words that the playbook covers (0-1): rarer words count more, and a word the
    playbook is about (its title, its own words) counts twice as much as one that only appears inside its lines.
    Words no playbook knows do not count, so a question about penguins and loudness is still a loudness question."""
    q = [t for t in _terms(query) if _DF.get(t)]
    total = sum(_idf(t) for t in q)
    if total <= 0:
        return 0.0
    strong, own = _STRONG[topic.id], _TERMS[topic.id]
    return sum(_idf(t) * (1.0 if t in strong else WEAK) for t in q if t in own) / total


# ------------------------------------------------------------------ what a job or a question reads
def view(t: Topic, s: float = 0.0) -> dict:
    return {"id": t.id, "title": t.title, "summary": t.summary, "lines": list(t.lines), "tasks": list(t.tasks),
            "chars": len(t.text), "score": round(s, 3)}


@dataclass
class Picked:
    """What a job or a question picked: the playbooks in the order a model should read them, and the prompt block."""
    topics: list[dict] = field(default_factory=list)

    @property
    def ids(self) -> list[str]:
        return [t["id"] for t in self.topics]

    @property
    def empty(self) -> bool:
        return not self.topics

    def prompt(self) -> str:
        return (HEADER + "\n" + "\n".join(BY_ID[t["id"]].text for t in self.topics)) if self.topics else ""

    def snapshot(self) -> list[dict]:
        return [{"id": t["id"], "title": t["title"], "score": t["score"]} for t in self.topics]


def select(query: str, task: str = "", *, limit: int = 3, budget_chars: int = 1200, fill: bool = True) -> Picked:
    """The few playbooks for `query` and `task`: the ones the words pick (a playbook not meant for the task counts
    for less), then, with `fill`, the task's defaults, cut to `limit` playbooks and `budget_chars` characters of
    prompt text."""
    task = task if task in TASKS else ""
    scored = []
    for t in TOPICS:
        s = score(query or "", t) * (1.0 if not task or task in t.tasks else 0.6)
        if s >= SELECT_MIN:
            scored.append((s, t))
    scored.sort(key=lambda x: (-x[0], TOPICS.index(x[1])))
    chosen = [(s, t) for s, t in scored]
    if fill and task:
        have = {t.id for _, t in chosen}
        chosen += [(0.0, BY_ID[tid]) for tid in DEFAULTS.get(task, ()) if tid not in have]
    out, used = [], len(HEADER) + 1
    for s, t in chosen:
        if len(out) >= max(0, limit):
            break
        if used + len(t.text) + 1 > budget_chars:
            continue
        out.append(view(t, s))
        used += len(t.text) + 1
    return Picked(out)


def answer(query: str) -> dict | None:
    """The one playbook that answers a question on its own (None when none fits well enough)."""
    best = max(((score(query, t), t) for t in TOPICS), key=lambda x: (x[0], -TOPICS.index(x[1])), default=None)
    if not best or best[0] < ANSWER_MIN:
        return None
    return view(best[1], best[0])


def answer_text(topic: dict) -> str:
    """The chat's words for a playbook answer, without a model."""
    lines = "\n".join(f"- {line}" for line in topic["lines"])
    return (f"From my built-in know-how, {topic['title'].lower()}:\n{lines}\nWhat you tell me with “remember: …” "
            "always wins over this. With a model set up (Settings → ClipForge AI) I can answer with your own "
            "memories too.")


def principles(task: str) -> str:
    return PRINCIPLES.get(task, "")


def topics() -> list[dict]:
    """Every playbook, for the Brain page."""
    return [view(t) for t in TOPICS]

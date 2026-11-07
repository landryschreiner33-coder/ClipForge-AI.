"""Labelled long recordings for Full stories (CF-04, CF-05 and the ambiguous/incomplete cases).

Timed transcripts follow the annotated intervals exactly; each story has a distinguishable opening and closing
sentence, its own vocabulary, natural short pauses and a few longer in-story pauses that must not split it.
`speech_video` renders the same script as real synthesized speech (espeak-ng) for render checks.
"""
from __future__ import annotations

import itertools
import random

WORD = 0.32
INTERWORD = 0.06

STORY_WORDS = {
    "forest": ["trail", "pine", "compass", "ridge", "creek", "backpack", "campfire", "tent", "boots", "forest",
               "hiking", "map", "valley", "lantern", "branches"],
    "kitchen": ["oven", "flour", "sugar", "frosting", "recipe", "mixer", "eggs", "butter", "cake", "kitchen",
                "baking", "sprinkles", "whisk", "batter", "timer"],
    "highway": ["highway", "engine", "dashboard", "gas", "station", "radio", "tires", "mirror", "motel", "road",
                "miles", "trucker", "exit", "detour", "headlights"],
    "garden": ["tomatoes", "shovel", "soil", "seeds", "watering", "fence", "roses", "weeds", "compost", "garden",
               "sunflowers", "hose", "beetles", "rake", "harvest"],
}
TEMPLATES = ["We walked past the {a} and the {b} while my friend checked the {c}",
             "Then the {a} started to look different and the {b} was nowhere near the {c}",
             "My cousin kept talking about the {a} even though the {b} needed attention",
             "Somehow the {a} ended up next to the {b} and nobody could explain the {c}",
             "We laughed about the {a} for a while and then looked for the {b}",
             "The {a} was much bigger than we expected and the {b} was soaked",
             "I tried to fix the {a} with the {b} but the {c} made it worse",
             "Everyone gathered around the {a} to talk about the {b} and the {c}"]


def _sentence_words(text: str, t: float) -> tuple[list[dict], float]:
    words = []
    for w in text.split():
        words.append({"start": round(t, 3), "end": round(t + WORD, 3), "w": w})
        t += WORD + INTERWORD
    return words, t - INTERWORD


def _fill(rng: random.Random, topic: str, start: float, end: float, opening: str, closing: str) -> list[str]:
    """Sentences for a story occupying [start, end]: the opening, generated middle, the closing."""
    middle = []
    budget = (end - start) - (len(opening.split()) + len(closing.split())) * (WORD + INTERWORD) - 2.0
    vocab = STORY_WORDS[topic]
    cycle = itertools.cycle(TEMPLATES)
    while True:
        a, b, c = rng.sample(vocab, 3)
        s = next(cycle).format(a=a, b=b, c=c) + "."
        cost = len(s.split()) * (WORD + INTERWORD) + 0.75  # speech + an even pause + a share of long pauses
        if budget - cost < 2.0:
            break
        middle.append(s)
        budget -= cost
    return [opening, *middle, closing]


def timed(segments: list[tuple[float, float, list[str]]], duration: float, long_pause_every: int = 9) -> dict:
    """A transcript whose sentences start 0.3 s after each segment's start and end 0.6 s before its end; pauses are
    spread evenly, with a longer in-story pause every `long_pause_every` sentences."""
    out = []
    for seg_start, seg_end, sentences in segments:
        n = len(sentences)
        speech = sum(len(s.split()) * (WORD + INTERWORD) - INTERWORD for s in sentences)
        longs = (n - 1) // long_pause_every if long_pause_every else 0
        avail = seg_end - seg_start - 0.3 - 0.6 - speech - 1.1 * longs
        pause = avail / (n - 1) if n > 1 else 0.0
        assert pause >= 0.3 or n == 1, f"sentences do not fit {seg_start}-{seg_end} (pause {pause:.2f})"
        t = seg_start + 0.3
        for k, s in enumerate(sentences):
            words, t_end = _sentence_words(s, t)
            out.append({"start": words[0]["start"], "end": words[-1]["end"], "text": s, "words": words})
            t = t_end + pause + (1.1 if long_pause_every and k and (k + 1) % long_pause_every == 0 else 0.0)
        assert out[-1]["end"] <= seg_end - 0.55, (seg_end, out[-1]["end"])
    return {"language": "en", "duration": duration, "source": "fixture", "segments": out}


def three_stories() -> tuple[dict, dict]:
    """CF-04: 12:00 recording. intro 0:00-0:15, A 0:15-3:10, gap 3:10-3:25, B 3:25-7:05 (crosses the 6:00 chunk
    boundary), gap 7:05-7:20, C 7:20-11:40, outro 11:40-12:00."""
    rng = random.Random(4)
    labels = {
        "intro": (0, 15), "A": (15, 190), "gap1": (190, 205), "B": (205, 425), "gap2": (425, 440),
        "C": (440, 700), "outro": (700, 720)}
    openings = {"A": "So this one time I got completely lost in the forest with nothing but a paper map.",
                "B": "My next story is about the day I tried to bake a wedding cake in a tiny kitchen.",
                "C": "Another time we drove across the country on a highway with no gas stations at all."}
    closings = {"A": "And that's how I learned to never trust an old paper map again.",
                "B": "And that's why I still keep a spare cake mix in the cupboard to this day.",
                "C": "And that was the end of our great highway adventure, the end."}
    segs = [
        (0, 15, ["Hey everyone, welcome back to the channel.", "Today I have three stories for you."]),
        (15, 190, _fill(rng, "forest", 15, 190, openings["A"], closings["A"])),
        (190, 205, ["Quick thanks to today's sponsor.", "Use my code for a discount, link in the description."]),
        (205, 425, _fill(rng, "kitchen", 205, 425, openings["B"], closings["B"])),
        (425, 440, ["Okay, that one still makes me laugh.", "Grab a drink, because the last one is long."]),
        (440, 700, _fill(rng, "highway", 440, 700, openings["C"], closings["C"])),
        (700, 720, ["Thanks for watching, everyone.", "Like and subscribe, and see you next time."]),
    ]
    return timed(segs, 720.0), {"labels": labels, "openings": openings, "closings": closings}


def cut_off_and_ambiguous() -> tuple[dict, dict]:
    """Two stories run together with no pause or wording between them, and the recording stops mid-story."""
    rng = random.Random(9)
    first = _fill(rng, "garden", 0, 90, "So this one time our whole garden was taken over by beetles.",
                  "We finally saved the tomatoes after a long summer.")
    second = _fill(rng, "forest", 90, 170, "The ridge above the creek was where the lantern went missing.",
                   "We walked past the compass and the ridge while my friend checked the")
    t = timed([(0, 90, first), (90, 170.4, second)], 170.4, long_pause_every=0)
    # no pause at all between the two stories, and the last words run to the very end of the recording
    return t, {"labels": {"first": (0, 90), "second": (90, 170.4)}}


def read_aloud(parts: list[tuple[str, list[str]]], pause: float = 0.15, pauses: dict[str, float] | None = None,
               tail: float = 2.0) -> tuple[dict, dict]:
    """A recording read at one steady pace, like a text-to-speech voice or a narrator reading posts: `pause`
    seconds after every sentence and no longer silence anywhere, so wording alone has to tell the stories apart.
    `pauses` maps a sentence's text to a longer pause after it. Returns the transcript and the labels:
    {"parts": [(kind, first word start, last word end), ...]}."""
    out, labels, t = [], [], 0.6
    for kind, sentences in parts:
        first = None
        for text in sentences:
            words, t_end = _sentence_words(text, t)
            out.append({"start": words[0]["start"], "end": words[-1]["end"], "text": text, "words": words})
            first = words[0]["start"] if first is None else first
            t = t_end + (pauses or {}).get(text, pause)
        labels.append((kind, first, out[-1]["end"]))
    duration = round(t + tail, 3)
    return {"language": "en", "duration": duration, "source": "fixture", "segments": out}, {"parts": labels}


REDDIT_TITLES = ["AITA for refusing to let my sister bring her kids to my wedding?",
                 "TIFU by locking myself out on the balcony in the middle of winter.",
                 "My husband keeps inviting his mother on our date nights and I am done.",
                 "WIBTA if I told my roommate's girlfriend about the smell in the fridge?",
                 "Am I wrong for selling the car my dad left me?"]
REDDIT_VOCAB = {
    "wedding": ["venue", "bridesmaids", "invitations", "reception", "sister", "nephews", "seating", "toddlers",
                "ceremony", "caterer", "dress", "vows", "flowers", "photographer", "cake"],
    "balcony": ["balcony", "sliding", "door", "snow", "neighbour", "ladder", "phone", "socks", "landlord",
                "shivering", "lighter", "gutter", "blanket", "keys", "frost"],
    "inlaws": ["husband", "mother", "restaurant", "dinner", "reservation", "anniversary", "menu", "therapist",
               "boundaries", "cinema", "wine", "babysitter", "weekend", "texts", "apology"],
    "roommate": ["fridge", "roommate", "girlfriend", "lease", "kitchen", "tupperware", "smell", "chores",
                 "rent", "bathroom", "groceries", "sponge", "trash", "landlady", "hallway"],
    "car": ["car", "garage", "brother", "will", "mechanic", "dealership", "inheritance", "keys", "mileage",
            "title", "lawyer", "funeral", "cousin", "paint", "engine"],
}


def reddit_reader() -> tuple[dict, dict]:
    """A narrator reading five posts straight through, the way a text-to-speech channel does: no pauses, a short
    separator before each post ("Story one.", "Next story."), the post's title, an update and read-out comments
    inside the posts, a remark after one of them, a greeting first and a goodbye last."""
    rng = random.Random(7)
    stories: list[list[str]] = []
    for topic, title in zip(REDDIT_VOCAB, REDDIT_TITLES):
        vocab = REDDIT_VOCAB[topic]
        cycle = itertools.cycle(TEMPLATES)
        body = []
        for _ in range(14):
            a, b, c = rng.sample(vocab, 3)
            body.append(next(cycle).format(a=a, b=b, c=c) + ".")
        stories.append([title, *body])
    stories[1].insert(9, "Update: the landlord finally called me back the next morning.")
    stories[1].insert(10, "Edit: thanks for the advice everyone, the keys were in the gutter.")
    stories[2].insert(8, "Top comment: your husband needs to pick a side, and it is not hers.")
    stories[2].insert(9, "Someone replied that the mother is the real problem in this story.")
    parts = [
        ("intro", ["Hey everyone, welcome back to the channel.", "Today I have five stories for you."]),
        ("story", ["Story one.", *stories[0]]),
        ("remark", ["Man, that one still gets me every time."]),
        ("story", ["Story two.", *stories[1]]),
        ("story", ["Next story.", *stories[2]]),
        ("story", ["This one is from r slash relationships.", *stories[3]]),
        ("story", ["Story five.", *stories[4], "So, am I the asshole here?"]),
        ("outro", ["Thanks for watching, everyone.", "Like and subscribe, and see you next time."]),
    ]
    pauses = {stories[1][5]: 3.5, stories[3][6]: 3.2}  # long breaths inside two stories: never a split
    transcript, labels = read_aloud(parts, pauses=pauses)
    return transcript, {**labels, "titles": REDDIT_TITLES}


def speech_script(transcript: dict) -> list[tuple[float, str]]:
    return [(s["start"], s["text"]) for s in transcript["segments"]]


# ------------------------------------------------------------------ real synthesized speech (espeak-ng)
def speech_recording(folder, parts: list[tuple[str, list[str]]], pause: float = 0.45, gap: float = 2.6,
                     size: str = "640x360") -> tuple["object", dict]:
    """A recording of real speech: each part is (kind, sentences), spoken by espeak-ng with `pause` between
    sentences and `gap` between parts, over a dark slate picture (burned-in captions are the only bright pixels).
    Returns (video path, transcript) where every sentence has its measured start/end and evenly spread word times.
    """
    import subprocess
    import wave
    from pathlib import Path

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rate = 22050
    pieces, segments, t = [], [], 0.4
    pieces.append(("silence", 0.4))
    for p_index, (kind, sentences) in enumerate(parts):
        for s_index, text in enumerate(sentences):
            wav = folder / f"s{p_index:02d}_{s_index:02d}.wav"
            subprocess.run(["espeak-ng", "-s", "165", "-w", str(wav), text], check=True, capture_output=True)
            with wave.open(str(wav)) as w:
                rate = w.getframerate()
                secs = w.getnframes() / rate
            words = text.split()
            # espeak pads each sentence with a little silence; spoken time is spread over the words
            lead, tail = 0.08, 0.12
            span = max(0.2, secs - lead - tail)
            step = span / len(words)
            segments.append({"start": round(t + lead, 3), "end": round(t + lead + span, 3), "text": text, "kind": kind,
                             "words": [{"start": round(t + lead + k * step, 3),
                                        "end": round(t + lead + (k + 0.85) * step, 3), "w": w_}
                                       for k, w_ in enumerate(words)]})
            pieces.append(("wav", wav))
            t += secs
            last = s_index == len(sentences) - 1
            hold = gap if last else pause
            pieces.append(("silence", hold))
            t += hold
    listing = folder / "parts.txt"
    lines = []
    for n, (what, value) in enumerate(pieces):
        if what == "silence":
            sil = folder / f"sil{n:03d}.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"anullsrc=r={rate}:cl=mono", "-t", f"{value:.3f}", str(sil)], check=True)
            value = sil
        lines.append(f"file '{value}'")
    listing.write_text("\n".join(lines))
    audio = folder / "speech.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
                    str(audio)], check=True)
    video = folder / "recording.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x2a3a52:s={size}:r=25", "-i",
                    str(audio), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
                    str(video)], check=True)
    return video, {"language": "en", "duration": t, "source": "fixture:espeak", "segments": segments}

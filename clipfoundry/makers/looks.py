"""The looks of an animated short: how its pictures are drawn, and how a scene's card looks without a picture engine
(docs/clipforge/ANIMATED_SHORTS.md).

A look is one style sentence for the picture engine (the same words in every scene of a short, so its pictures look
like one film), its light, what the engine should avoid, the colours and font of the designed cards (cards.py), the
captions that fit it, and its finish: the grade every scene gets and what drifts through the air (fx.py).

`scene_prompt` writes what the picture engine is asked for a scene: the shot, what it shows, the short's main
character, the light, the look and how a picture for a phone is composed (the subject large in the upper middle, a
calm lower third for the captions, nothing written in it). The picture models ClipForge uses read sentences, put the
most weight on what comes first and ignore "avoid" lists, so everything is said as what to draw, in that order. No
artist, studio, film or creator is ever named: a look is described by what it is made of.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

# Every picture: no writing inside it (the captions carry the words) and none of the usual generation faults.
NEGATIVE_ALWAYS = ("text, letters, words, captions, subtitles, watermark, logo, signature, frame, border, blurry, "
                   "low quality, deformed, extra fingers, extra limbs")
PROMPT_RECIPE = 2   # part of a scene's picture key (shorts.picture_keys): changed words draw the pictures again
# How a picture for a short is framed, whatever its look (said last: the picture model weighs it least, the camera
# and the captions rely on it most).
COMPOSITION = ("Vertical 9:16 composition, the subject large in the upper middle of the frame, a calm uncluttered "
               "lower third, nothing written anywhere.")
# The shot of each scene in turn: mostly close, some medium, a wide one now and then (a short is watched on a phone:
# a face or a thing fills it). The first scene is the cover and the hook: close.
SHOTS = ("Close-up shot", "Medium shot", "Close-up shot from a low angle", "Wide establishing shot", "Close-up shot",
         "Medium shot from slightly above", "Extreme close-up", "Medium shot", "Close-up shot", "Wide shot from a low "
         "angle")
_HAS_SHOT = re.compile(r"\b(close[- ]?up|wide shot|medium shot|establishing shot|low angle|high angle|bird'?s[- ]eye|"
                       r"overhead|from above|from below|aerial|first[- ]person|point of view|pov|macro|portrait of|"
                       r"view of|seen from)\b", re.I)
MAX_PROMPT = 1200
# The finish of each look (fx.finish, fx.Frame): small numbers, the same for every scene of a short.
GRADES = {
    "cartoon3d": {"contrast": 1.04, "saturation": 1.08, "bloom": 0.18, "vignette": 0.18},
    "storybook": {"contrast": 1.02, "saturation": 1.03, "warmth": 0.25, "bloom": 0.12, "vignette": 0.22, "grain": 2},
    "anime": {"contrast": 1.05, "saturation": 1.1, "bloom": 0.25, "vignette": 0.15},
    "comic": {"contrast": 1.08, "saturation": 1.1, "vignette": 0.1},
    "cinematic": {"contrast": 1.08, "saturation": 0.94, "warmth": 0.1, "bloom": 0.15, "vignette": 0.35, "grain": 4},
    "paper": {"contrast": 1.02, "vignette": 0.15, "grain": 2},
    "flat": {"contrast": 1.02},
    "eerie": {"contrast": 1.08, "saturation": 0.72, "warmth": -0.3, "vignette": 0.45, "grain": 6},
    "clay": {"contrast": 1.04, "saturation": 1.05, "warmth": 0.12, "bloom": 0.1, "vignette": 0.25, "grain": 2},
    "doodle": {"contrast": 1.03, "saturation": 1.05},
}
# What drifts over each look's scenes when the scene itself names nothing (director.air_for).
AIR = {"cartoon3d": ("dust",), "storybook": ("dust", "rays"), "anime": ("dust", "rays"), "cinematic": ("dust",),
       "eerie": ("fog", "dust"), "clay": ("dust",)}


@dataclass(frozen=True)
class Look:
    id: str
    name: str
    about: str
    prompt: str          # the style sentence, the same in every picture of a short
    negative: str        # what to avoid, on top of NEGATIVE_ALWAYS (for picture models that listen to it)
    top: str             # card gradient, top colour
    bottom: str          # card gradient, bottom colour
    accent: str          # card shapes
    ink: str             # card words
    font: str            # card font file in config.FONTS_DIR
    caption_style: str   # engine caption style (pipeline/captions.py STYLE_PRESETS)
    light: str = ""      # the look's light, one sentence
    captions: str = ""   # the caption look that fits it (studio/caption_looks.py)
    best_for: str = ""   # what the look suits, for the picker

    @property
    def grade(self) -> dict:
        return dict(GRADES.get(self.id) or {})

    @property
    def air(self) -> tuple[str, ...]:
        return tuple(AIR.get(self.id) or ())


LOOKS: tuple[Look, ...] = (
    Look("cartoon3d", "3D cartoon", "Bright animated-film characters with soft light",
         "Stylised 3D animated film render, rounded simplified forms, big expressive eyes, smooth matte materials "
         "with a soft glow, gentle contact shadows, rich saturated colours, clean uncluttered background",
         "photo, realistic skin, grainy, dark",
         "#7AD3FF", "#3C6CF0", "#FFD84D", "#FFFFFF", "Poppins-Black.ttf", "bold",
         "Soft key light from the upper left with a bright rim light along the edges.", "pop",
         "Stories, explainers, talking things"),
    Look("cinematic", "Cinematic", "Painted film stills with dramatic light",
         "Cinematic painterly realism with visible brush texture, deep shadows, atmospheric haze, a muted palette of "
         "a few earth colours, deep focus",
         "cartoon, anime, oversaturated, plastic skin",
         "#1D2B3A", "#0B0F14", "#E8B04B", "#F5F1E8", "Anton-Regular.ttf", "bold",
         "One motivated light from the side, the rest falling into shadow.", "impact",
         "History, true stories, big ideas"),
    Look("doodle", "Bold cartoon", "Thick outlines and flat colour, like a storytime cartoon",
         "Modern 2D cartoon illustration, thick uniform black outlines, flat colour fills with one soft shadow tone, "
         "simple rounded shapes, big heads with dot eyes, exaggerated poses, cream paper background with two or "
         "three simple props",
         "photo, 3D render, gradients, texture, clutter",
         "#FFF3D6", "#FFD9A0", "#FF6B4A", "#1B1B1B", "Fredoka-Bold.ttf", "bold",
         "Even flat light, no cast shadows.", "pop",
         "Funny stories, what-ifs, everyday moments"),
    Look("anime", "Anime", "Clean line art, bold colour and big skies",
         "Cel-shaded animation key frame, crisp clean line art, flat colours with one hard-edged shadow tone, simple "
         "expressive eyes, a dramatic sky, painted background with less detail than the character",
         "photo, 3D render, western cartoon, muddy colors",
         "#FF9AC1", "#6A5BFF", "#FFF27A", "#FFFFFF", "Poppins-Black.ttf", "high_energy",
         "Bright daylight with strong highlights and a soft glow.", "impact",
         "Drama, adventures, feelings"),
    Look("storybook", "Storybook", "Soft watercolour, like a children's book",
         "Soft watercolour storybook illustration, visible brush strokes and paper grain, cosy muted colours, simple "
         "shapes, plain airy background",
         "photo, 3D render, harsh shadows, neon",
         "#FCE9C8", "#F2B48A", "#8C5A3C", "#3B2616", "Poppins-Black.ttf", "bold",
         "Warm gentle light from a window.", "soft",
         "Bedtime stories, fables, gentle facts"),
    Look("clay", "Clay", "Hand-made clay figures on a little set",
         "Stop-motion clay animation still, figures made of textured modelling clay with visible thumbprints, a "
         "handmade miniature set, soft shadows, shallow depth of field",
         "photo, smooth plastic, glossy, neon",
         "#F6D9B8", "#D98E5F", "#5B8E7D", "#2B1D14", "Fredoka-Bold.ttf", "bold",
         "Warm studio tabletop lighting from one side.", "pop",
         "Funny stories, kids, how things work"),
    Look("comic", "Comic book", "Ink outlines, halftone dots and punchy angles",
         "Comic book illustration, bold black ink outlines, halftone dot shading, vivid flat primary colours, a "
         "dynamic low camera angle, plain surfaces",
         "photo, soft watercolor, pastel, blurry lines",
         "#FFD23F", "#FF5E5B", "#1B1B1B", "#1B1B1B", "Anton-Regular.ttf", "high_energy",
         "Hard dramatic light with solid black shadows.", "comic",
         "Action, facts, gaming, news"),
    Look("paper", "Paper cut-out", "Layered craft paper with soft shadows",
         "Layered cut-paper collage, visible paper edges and fibre texture, soft shallow shadows between the layers, "
         "a frontal stage-like arrangement of a few large simple pieces",
         "photo, realistic, glossy, neon",
         "#BDE7D8", "#6FBFA5", "#F28C6B", "#1F3B35", "Poppins-Black.ttf", "bold",
         "Soft even light from above.", "soft",
         "Fables, history, simple ideas"),
    Look("flat", "Flat vector", "Simple shapes and flat colour, like an explainer",
         "Flat vector illustration, solid colour fills with two tones per object, large simple geometric shapes, a "
         "pale plain background, generous empty space",
         "photo, 3D render, gradients, texture, clutter",
         "#5CE1E6", "#3A86FF", "#FFBE0B", "#FFFFFF", "Poppins-Black.ttf", "bold",
         "No shading or cast shadows.", "pop",
         "Explainers, comparisons, how-tos"),
    Look("eerie", "Dark and eerie", "Fog, moonlight and deep shadows for mysteries",
         "Dark moody illustration, drifting fog, deep shadows and large areas of darkness, muted desaturated colours, "
         "worn surfaces, something half-seen at the edge of the frame",
         "bright, cheerful, pastel, cartoonish, sunny",
         "#2A2440", "#07060C", "#9D7CFF", "#E9E4FF", "Anton-Regular.ttf", "high_energy",
         "A single cold light from above.", "impact",
         "Mysteries, scary stories, true crime"),
)
BY_ID = {look.id: look for look in LOOKS}
DEFAULT = "cartoon3d"


def get(look_id: str | None) -> Look:
    """The look with this id; an unknown or empty id is the default look."""
    return BY_ID.get(str(look_id or ""), BY_ID[DEFAULT])


def view() -> list[dict]:
    """The looks for the page's picker (no prompt words: those are ClipForge's business)."""
    keep = ("id", "name", "about", "top", "bottom", "accent", "best_for")
    return [{k: v for k, v in asdict(look).items() if k in keep} for look in LOOKS]


def _clean(text: object) -> str:
    return " ".join(str(text or "").split())


def prompt_for(look: Look, picture: str, character: str = "") -> tuple[str, str]:
    """The picture engine's (prompt, negative) as shorts made before the viral-look upgrade ask for it, and for a
    scene's motion: the scene's picture idea, the short's main character and the look's style words."""
    parts = [_clean(picture).rstrip(" ."), _clean(character).rstrip(" ."), look.prompt]
    return ". ".join(p for p in parts if p), f"{NEGATIVE_ALWAYS}, {look.negative}"


def shot_for(seq: int, idea: str = "") -> str:
    """The shot of the scene at this place in the short; "" when its picture idea already says how it is framed."""
    if _HAS_SHOT.search(idea or ""):
        return ""
    return SHOTS[int(seq) % len(SHOTS)]


_PART = re.compile(r",| with | who | wearing | in a | in an | holding | that ", re.I)
_SMALL = frozenset("a an the his her its their my our your one two little small tiny big young old".split())


def anchors(character: str) -> list[str]:
    """The words a picture idea names the short's main character by: the thing it is ("robot" for "a tiny round
    white robot with big blue eyes"), or its name and the thing ("mia" and "girl" for "Mia, a ten-year-old girl with
    red hair")."""
    parts = [x for x in _PART.split(_clean(character)) if x.strip()]

    def last(part: str) -> str:
        words = [w.strip(".;:!?'\"()").lower() for w in part.split()]
        words = [w for w in words if len(w) >= 3 and w not in _SMALL]
        return words[-1] if words else ""

    out = [last(parts[0])] if parts else []
    named = bool(parts) and len(parts[0].split()) <= 2 and parts[0].strip()[:1].isupper()
    if named and len(parts) > 1:
        out.append(last(parts[1]))
    return [w for w in dict.fromkeys(out) if w]


_THEY = re.compile(r"\b(?:he|she|they|him|her|his|hers|them|their|himself|herself|themselves)\b", re.I)


def shows_character(idea: str, character: str, said: str = "") -> bool:
    """Whether a scene's picture shows the short's main character: its picture idea names them, or the words of a
    scene without a picture idea of its own (`said`) name them or speak of someone as he, she or they."""
    low = f"{_clean(idea)} {_clean(said)}".lower()
    return bool(anchors(character)) and (any(re.search(rf"\b{re.escape(a)}s?\b", low) for a in anchors(character))
                                         or bool(said and _THEY.search(said)))


def called(character: str) -> str:
    """What a prompt calls the short's main character: their name ("Mia"), or what they are ("The robot")."""
    first = _clean(character).split(",")[0].split()
    if first and len(first) <= 2 and first[0][:1].isupper() and first[0].lower() not in _SMALL:
        return first[0].strip(".;:!?'\"()")
    names = anchors(character)
    return f"The {names[0]}" if names else "The main character"


def scene_prompt(look: Look, *, idea: str, narration: str = "", source: str = "", character: str = "", seq: int = 0,
                 referenced: bool = False, shown: bool = True) -> tuple[str, str]:
    """The picture engine's (prompt, negative) for one scene of a short: the shot, what it shows, the main character,
    the light, the look, the composition. `source` "words": the scene has no picture idea of its own (no script
    direction, no AI), so its own words say the moment (`idea` is then the idea of the scene before it, or empty).
    `shown`: the scene shows the main character (a scene that does not leaves them out of the words). `referenced`:
    the engine is shown the picture of the main character (image 1), so the prompt points at it instead of
    describing the character again."""
    idea = _clean(idea).rstrip(" .")
    said = _clean(narration).rstrip(" .")
    character = _clean(character).rstrip(" .")
    shot = shot_for(seq, idea)
    if source == "words" and said:
        idea = f"{idea}. The moment it shows: {said}" if idea else said
    first = f"{shot}: {idea}" if shot and idea else idea or shot
    parts = [first[:1].upper() + first[1:]]
    if character and shown and referenced:
        parts.append(f"{called(character)} is the character from image 1: keep the same design, proportions and "
                     "colours")
    elif character and shown:
        parts.append(f"The main character: {character}")
    parts += [look.light.rstrip(" ."), look.prompt.rstrip(" ."), COMPOSITION.rstrip(" .")]
    return (". ".join(p for p in parts if p) + ".")[:MAX_PROMPT], f"{NEGATIVE_ALWAYS}, {look.negative}"


def cast_prompt(look: Look, character: str) -> tuple[str, str]:
    """The picture of a short's main character alone, which every scene that shows them is then drawn from: the whole
    figure, facing the viewer, on a plain background, in the short's look."""
    who = _clean(character).rstrip(" .")
    text = (f"Full-body character design of {who}, standing in a relaxed neutral pose facing the viewer, the whole "
            f"figure visible and centred on a plain flat light-grey background, even soft front lighting. "
            f"{look.prompt.rstrip(' .')}. Nothing written anywhere.")
    return text[:MAX_PROMPT], f"{NEGATIVE_ALWAYS}, {look.negative}"


MOVES_SLOW = ("blinks and breathes gently", "turns the head slightly", "hair and cloth sway softly",
              "small natural movement")


def motion_prompt(look: Look, idea: str, character: str = "", seq: int = 0) -> tuple[str, str]:
    """What the video engine is asked when it animates a scene's picture: who is in it (to hold steady), one slow
    small movement, a still camera (ClipForge's own camera does the moving), then the look. The picture itself
    already says how everything looks."""
    who = _clean(character).rstrip(" .") or _clean(idea).rstrip(" .")
    move = MOVES_SLOW[int(seq) % len(MOVES_SLOW)]
    text = f"{who}, {move}. Static shot, slow subtle motion. {_clean(idea).rstrip(' .')}. {look.prompt.rstrip(' .')}."
    return text[:MAX_PROMPT], f"{NEGATIVE_ALWAYS}, {look.negative}, inconsistent face, morphing features"

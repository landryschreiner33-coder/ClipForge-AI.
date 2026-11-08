"""The looks of an animated short: how its pictures are drawn, and how a scene's card looks without a picture engine
(docs/clipforge/ANIMATED_SHORTS.md).

A look is words for the picture engine (added to every scene's picture idea, so all scenes share one style), what the
engine should avoid, the colours and font of the designed cards (cards.py) and the caption style that fits it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

# Every picture: no writing inside it (the captions carry the words) and none of the usual generation faults.
NEGATIVE_ALWAYS = ("text, letters, words, captions, subtitles, watermark, logo, signature, frame, border, blurry, "
                   "low quality, deformed, extra fingers, extra limbs")


@dataclass(frozen=True)
class Look:
    id: str
    name: str
    about: str
    prompt: str          # style words added to every picture prompt
    negative: str        # what to avoid, on top of NEGATIVE_ALWAYS
    top: str             # card gradient, top colour
    bottom: str          # card gradient, bottom colour
    accent: str          # card shapes
    ink: str             # card words
    font: str            # card font file in config.FONTS_DIR
    caption_style: str   # engine caption style (pipeline/captions.py STYLE_PRESETS)


LOOKS: tuple[Look, ...] = (
    Look("cartoon3d", "3D cartoon", "Bright animated-film characters with soft light",
         "3D animated film still, cute expressive characters, soft studio lighting, vibrant colors, smooth shapes, "
         "shallow depth of field", "photo, realistic skin, grainy, dark",
         "#7AD3FF", "#3C6CF0", "#FFD84D", "#FFFFFF", "Poppins-Black.ttf", "bold"),
    Look("storybook", "Storybook", "Soft watercolour, like a children's book",
         "soft watercolor storybook illustration, warm gentle light, hand-painted textures, cozy colors",
         "photo, 3D render, harsh shadows, neon",
         "#FCE9C8", "#F2B48A", "#8C5A3C", "#3B2616", "Poppins-Black.ttf", "bold"),
    Look("anime", "Anime", "Clean line art, bold colour and big skies",
         "anime illustration, clean line art, cel shading, vivid colors, dramatic sky, detailed background",
         "photo, 3D render, western cartoon, muddy colors",
         "#FF9AC1", "#6A5BFF", "#FFF27A", "#FFFFFF", "Poppins-Black.ttf", "high_energy"),
    Look("comic", "Comic book", "Ink outlines, halftone dots and punchy angles",
         "comic book panel, bold ink outlines, halftone shading, punchy saturated colors, dynamic camera angle",
         "photo, soft watercolor, pastel, blurry lines",
         "#FFD23F", "#FF5E5B", "#1B1B1B", "#1B1B1B", "Anton-Regular.ttf", "high_energy"),
    Look("cinematic", "Cinematic", "Realistic film stills with dramatic light",
         "cinematic film still, realistic, dramatic lighting, 35mm photograph, rich color grade, atmospheric depth",
         "cartoon, illustration, anime, oversaturated, plastic skin",
         "#1D2B3A", "#0B0F14", "#E8B04B", "#F5F1E8", "Anton-Regular.ttf", "bold"),
    Look("paper", "Paper cut-out", "Layered craft paper with soft shadows",
         "layered paper cut-out art, craft paper textures, soft drop shadows, playful handmade diorama",
         "photo, realistic, glossy, neon",
         "#BDE7D8", "#6FBFA5", "#F28C6B", "#1F3B35", "Poppins-Black.ttf", "bold"),
    Look("flat", "Flat vector", "Simple shapes and flat colour, like an explainer",
         "flat vector illustration, simple geometric shapes, bold flat colors, clean composition, minimal details",
         "photo, 3D render, gradients, texture, clutter",
         "#5CE1E6", "#3A86FF", "#FFBE0B", "#FFFFFF", "Poppins-Black.ttf", "bold"),
    Look("eerie", "Dark and eerie", "Fog, moonlight and deep shadows for mysteries",
         "dark moody illustration, drifting fog, cold moonlight, deep shadows, mysterious atmosphere, muted colors",
         "bright, cheerful, pastel, cartoonish, sunny",
         "#2A2440", "#07060C", "#9D7CFF", "#E9E4FF", "Anton-Regular.ttf", "high_energy"),
)
BY_ID = {look.id: look for look in LOOKS}
DEFAULT = "cartoon3d"


def get(look_id: str | None) -> Look:
    """The look with this id; an unknown or empty id is the default look."""
    return BY_ID.get(str(look_id or ""), BY_ID[DEFAULT])


def view() -> list[dict]:
    """The looks for the page's picker (no prompt words: those are ClipForge's business)."""
    return [{k: v for k, v in asdict(look).items() if k in ("id", "name", "about", "top", "bottom", "accent")}
            for look in LOOKS]


def prompt_for(look: Look, picture: str, character: str = "") -> tuple[str, str]:
    """The picture engine's (prompt, negative) for one scene: the scene's picture idea, the short's main character
    (the same in every scene, so they look like one story) and the look's style words."""
    parts = [" ".join(str(picture or "").split()).rstrip(" ."), " ".join(str(character or "").split()).rstrip(" ."),
             look.prompt]
    return ". ".join(p for p in parts if p), f"{NEGATIVE_ALWAYS}, {look.negative}"

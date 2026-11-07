"""The editing choices ClipForge actually implements, per workflow mode.

One registry shared by the skill parser, styles, the brief, the guidance resolver and the renderers, so a value is
"supported" only if something downstream really applies it. Anything else stays visibly unsupported.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import config

MODES = ("highlights", "full_stories", "full_video")
CLIP_MODES = ("highlights", "full_stories")


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str                           # choice | bool | number | text
    modes: tuple[str, ...]
    choices: tuple = ()
    minimum: float | None = None
    maximum: float | None = None
    max_length: int = 0
    applies: str = ""                   # where it takes effect, in words (shown with "Used from your Brain")
    words: dict = field(default_factory=dict)  # value -> plain words

    def validate(self, value):
        if self.kind == "choice":
            if value not in self.choices:
                raise ValueError(f"{self.label}: choose one of {', '.join(map(str, self.choices))}")
            return value
        if self.kind == "bool":
            if type(value) is not bool:
                raise ValueError(f"{self.label} must be true or false")
            return value
        if self.kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
                raise ValueError(f"{self.label} must be a number")
            if (self.minimum is not None and value < self.minimum) or (self.maximum is not None and value > self.maximum):
                raise ValueError(f"{self.label} must be between {self.minimum:g} and {self.maximum:g}")
            return float(value)
        if not isinstance(value, str) or len(value) > self.max_length or "\x00" in value:
            raise ValueError(f"{self.label} must be text of at most {self.max_length} characters")
        return " ".join(value.split())

    def describe(self, value) -> str:
        if self.kind == "bool":
            return f"{self.label}: {'on' if value else 'off'}"
        if self.name == "target_duration_s":
            return "Length: use your judgment" if not value else f"Length: about {round(value / 60, 1):g} min"
        if self.name == "shot_length_s":
            return "Shots: keep each file whole" if not value else f"Shots: about {value:g} s, pauses cut out"
        if self.name == "duck_depth_db":
            return f"Music dips {value:g} dB under speech"
        return f"{self.label}: {self.words.get(value, value)}"


ALL = MODES
FIELDS: dict[str, Field] = {f.name: f for f in (
    Field("caption_style", "Caption style", "choice", ALL, tuple(config.CAPTION_STYLES),
          applies="burned-in captions"),
    Field("caption_position", "Caption position", "choice", ALL, ("bottom", "middle", "top"),
          applies="caption placement", words={"bottom": "lower third", "middle": "centre", "top": "top"}),
    Field("caption_emphasis", "Caption emphasis", "bool", CLIP_MODES, applies="highlighted key words"),
    Field("captions", "Captions", "bool", ("full_video",), applies="whether captions are burned in"),
    Field("pacing", "Pacing", "choice", ("highlights",), ("safe_cuts", "continuous"),
          applies="removal of weak middle sentences", words={"safe_cuts": "tighten when safe",
                                                              "continuous": "continuous"}),
    Field("layout", "Framing", "choice", ALL, tuple(config.LAYOUTS), applies="fill the frame or fit with a "
          "blurred background", words={"fill": "fill the frame", "fit": "fit with blurred background"}),
    Field("tracking", "Subject tracking", "choice", CLIP_MODES, ("auto", "center", "face", "speaker", "screen"),
          applies="which subject the vertical frame follows"),
    Field("feel", "Feel", "choice", ("full_video",), ("calm", "balanced", "energetic"),
          applies="transition type and length", words={"calm": "calm / storytelling", "balanced": "balanced",
                                                        "energetic": "energetic"}),
    Field("transition", "Transitions", "choice", ("full_video",), ("cut", "dissolve", "fade"),
          applies="joins between clips"),
    Field("aspect_ratio", "Shape", "choice", ("full_video",), ("16:9", "9:16", "1:1", "4:5"),
          applies="output frame size"),
    Field("target_duration_s", "Length", "number", ("full_video",), minimum=0, maximum=4 * 3600,
          applies="the rough cut's length (0 = use your judgment)"),
    Field("music", "Music", "choice", ("full_video",), ("none", "supplied", "find", "auto", "library"),
          applies="a music bed you supplied, free music made by ClipForge, or one found in Media sources",
          words={"none": "no added music", "supplied": "your supplied track",
                 "find": "music found in Media sources (suggested or added under this project's license rules)",
                 "auto": "picked for you (your music file, or free music made by ClipForge)",
                 "library": "free music made by ClipForge on this computer"}),
    Field("smart_edit", "Editing", "choice", ("full_video",), ("off", "smart", "tight"),
          applies="how much the rough cut is edited: pauses, repeated takes and weak parts cut, length fitted",
          words={"off": "keep my clips as they are", "smart": "edit it for me", "tight": "fast-paced"}),
    Field("sound_effects", "Sound effects", "bool", ("full_video",),
          applies="soft whooshes at scene changes and as pictures appear"),
    Field("broll_images", "Pictures over the video", "bool", ("full_video",),
          applies="your images shown over the video while the talking goes on"),
    Field("punch_in", "Zoom on cuts", "bool", ("full_video",),
          applies="a small zoom on every other jump cut"),
    Field("music_level_db", "Music level", "number", ("full_video",), minimum=-36, maximum=-6,
          applies="music volume under speech (it ducks further while someone speaks)"),
    Field("title_card", "Title card", "bool", ("full_video",), applies="an opening title"),
    Field("caption_size", "Caption size", "choice", ("full_video",), ("small", "medium", "large"),
          applies="how large burned-in captions are"),
    Field("frame_rate", "Frame rate", "choice", ("full_video",), (24, 25, 30, 50, 60),
          applies="frames per second of the video", words={24: "24 fps", 25: "25 fps", 30: "30 fps", 50: "50 fps",
                                                            60: "60 fps"}),
    Field("duck_music", "Music under speech", "bool", ("full_video",),
          applies="music dips while someone speaks"),
    Field("duck_depth_db", "Music dip under speech", "number", ("full_video",), minimum=0, maximum=30,
          applies="how many dB music and effects dip while someone speaks"),
    Field("shot_length_s", "Shot length", "number", ("full_video",), minimum=0, maximum=60,
          applies="the rough cut cuts speech into shots of about this length at sentence ends and leaves out the "
                  "pauses between them (0 keeps each file whole)"),
    Field("video_type", "Video type", "text", ("full_video",), max_length=80, applies="the brief's starting answer"),
    Field("audience", "Audience", "text", ("full_video",), max_length=120, applies="the brief's starting answer"),
)}

# The project's own answers that must never be remembered as a reusable style (they belong to one project).
PROJECT_ONLY = {"goal", "must_keep", "avoid", "asset_order", "music_asset_id", "consent", "destinations"}


def for_mode(mode: str) -> dict[str, Field]:
    return {k: f for k, f in FIELDS.items() if mode in f.modes}


def clean(values: dict, modes: tuple[str, ...] = MODES) -> tuple[dict, list[str]]:
    """The supported, valid values among `values` (for any of `modes`) and the problems with the rest."""
    out, problems = {}, []
    for key, value in (values or {}).items():
        f = FIELDS.get(key)
        if f is None or not set(f.modes) & set(modes):
            problems.append(f"“{key}” is not an editing choice ClipForge applies here")
            continue
        try:
            out[key] = f.validate(value)
        except ValueError as exc:
            problems.append(str(exc))
    return out, problems


def registry() -> list[dict]:
    """The registry as data, for the UI and the skill import preview."""
    return [{"name": f.name, "label": f.label, "kind": f.kind, "modes": list(f.modes), "choices": list(f.choices),
             "minimum": f.minimum, "maximum": f.maximum, "applies": f.applies} for f in FIELDS.values()]

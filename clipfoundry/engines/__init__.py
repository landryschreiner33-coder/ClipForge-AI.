"""Local engines: the programs on this computer that make pictures, video and speech for ClipForge
(docs/clipforge/LOCAL_ENGINES.md).

This is the one door other parts of ClipForge use (the animated-shorts maker, the media finders, the AI). Every call
is blocking and meant for a job thread; every call takes the same two callbacks: `progress(fraction, message)` and
`cancel() -> bool`. Everything that goes wrong is one error class, `EngineError`, whose message is written for the
person. `status(role)` never raises.

Roles: "image" (a still picture from words), "video" (a few seconds of motion from words or a picture) and "voice"
(speech from words). Which engine serves a role is decided from the settings and from what is running or installed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

ROLES = ("image", "video", "voice")

Progress = Callable[[float, str], None]
Cancel = Callable[[], bool]


class EngineError(RuntimeError):
    """An engine could not do the job; the message says why, in plain words."""


def status(role: str) -> dict:
    """{"ready": bool, "engine": str, "why": str} for one role. Never raises."""
    if role not in ROLES:
        return {"ready": False, "engine": "", "why": f"Unknown role {role!r}."}
    return {"ready": False, "engine": "", "why": "No local engine is set up yet."}


def make_image(prompt: str, *, negative: str = "", style: str = "", width: int = 1080, height: int = 1920,
               seed: int | None = None, progress: Progress | None = None, cancel: Cancel | None = None) -> Path:
    """A still picture (PNG) made from `prompt` by the image engine."""
    raise EngineError("No image engine is set up yet.")


def make_video(prompt: str, *, image: Path | str | None = None, seconds: float = 4.0, width: int = 720,
               height: int = 1280, seed: int | None = None, progress: Progress | None = None,
               cancel: Cancel | None = None) -> Path:
    """A short silent video (MP4) made from `prompt`, animating `image` when one is given."""
    raise EngineError("No video engine is set up yet.")


def speak(text: str, *, voice: str = "default", speed: float = 1.0, lang: str = "en",
          progress: Progress | None = None, cancel: Cancel | None = None) -> dict:
    """Speech from `text`: {"path": <wav, mono>, "duration_s": float, "words": [{"text", "start_s", "end_s"}] | None}."""
    raise EngineError("No voice engine is set up yet.")


def voices() -> list[dict]:
    """The voices the voice engine offers: [{"id", "name", "lang", "gender", "about"}]."""
    return []

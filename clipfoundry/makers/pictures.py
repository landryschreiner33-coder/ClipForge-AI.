"""A scene's picture for an animated short (docs/clipforge/ANIMATED_SHORTS.md): made by the local picture engine
when one is set up (clipfoundry/engines through local_engines.py), otherwise a designed card with the scene's key
words (cards.py). A failing engine never stops the short: the card stands in and the reason is kept for the page.

A short with an editing style asks in its own words (looks.scene_prompt) and may show the engine the picture of its
main character (`make_cast` makes that one), so every scene shows the same character; an engine that cannot draw
from that picture is asked once more in words alone.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable

from ..pipeline.common import Cancelled
from ..studio.jobs import Canceled
from . import cards, local_engines
from .looks import Look

log = logging.getLogger(__name__)
PICTURE_SIZE = (1080, 1920)   # what the picture engine is asked for (portrait, the short's own frame)
CAST_SIZE = (864, 1152)       # the main character's picture: the whole figure, taller than wide
SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


class _NoPicture(Exception):
    """The engine answered without a usable picture; the message is the owner's sentence."""


def _opens(path: Path) -> bool:
    """Whether a picture opens all the way (one cut short by a crash or a full disk does not)."""
    from PIL import Image

    try:
        with Image.open(path) as im:
            im.load()
        return True
    except Exception as exc:  # noqa: BLE001 - any picture that does not open is the same problem
        log.warning("the picture engine's picture does not open: %s", exc)
        return False



def _from_engine(prompt: str, negative: str, out_dir: Path, *, style: str, size: tuple[int, int], seed: int,
                 references: tuple = (), name: str = "picture", cancel: Callable[[], bool] | None = None,
                 progress: Callable[[float, str], None] | None = None) -> dict:
    """One picture from the picture maker, taken into `out_dir`: {"path", "note"}. Raises _NoPicture with the owner's
    sentence when it made none that can be used (the work being stopped passes through)."""
    made: Path | None = None
    shown = {"references": [str(r) for r in references]} if references else {}
    try:
        made = Path(local_engines.module().make_image(  # type: ignore[union-attr]
            prompt, negative=negative, style=style, width=size[0], height=size[1], seed=seed,
            progress=progress, cancel=cancel, **shown))
        suffix = made.suffix.lower() if made.suffix.lower() in SUFFIXES else ".png"
        if not made.is_file() or made.stat().st_size == 0:
            raise _NoPicture("The picture maker gave no picture, so ClipForge drew a card.")
        if not _opens(made):
            raise _NoPicture("The picture maker's picture could not be opened, so ClipForge drew a card.")
        path = out_dir / f"{name}-{seed}{suffix}"
        note = made.with_suffix(".json")
        shutil.copyfile(made, path)
        taken = False
        if local_engines.made_here(made):  # the short takes the maker's picture; its note goes with the short
            try:
                made.unlink()
                taken = True
            except OSError as exc:  # another program has it open (Windows): it stays there, with its note
                log.warning("the picture maker's picture could not be taken out of engines/made: %s", exc)
        return {"path": path, "note": str(note) if taken and note.is_file() else ""}
    except (Canceled, Cancelled, _NoPicture):
        local_engines.discard_made(made)
        raise
    except OSError as exc:  # its words are for the log
        local_engines.discard_made(made)
        log.warning("the picture engine's picture could not be saved: %s", exc)
        raise _NoPicture("The picture maker's picture could not be saved, so ClipForge drew a card. Check that the "
                         "disk has free space.") from exc
    except local_engines.errors() as exc:  # written for the owner
        raise _NoPicture(f"The picture maker could not make this picture ({str(exc)[:160]}).") from exc
    except Exception as exc:  # noqa: BLE001 - a broken engine never stops the short
        log.exception("picture engine failed")
        raise _NoPicture("The picture maker stopped with an error, so ClipForge drew a card.") from exc


def make(narration: str, picture: str, look: Look, out_dir: Path, *, character: str = "", seed: int = 0,
         index: int = 0, cancel: Callable[[], bool] | None = None,
         progress: Callable[[float, str], None] | None = None, asks: list[tuple] | None = None) -> dict:
    """Make the picture into `out_dir`: {"path", "source": "engine" | "card", "engine", "why", "tried", "prompt",
    "negative", "note", "referenced"}. `why` says why the engine did not make it ("" when it did); `tried`: the
    engine was asked (so a card means it failed, not that none is set up). The maker's picture is taken out of its
    folder (engines/made): copied to `out_dir`, then deleted there (left there, with its note, when another program
    has it open), and `note` is the note it saved with it, for the caller to keep with the picture ("" when the
    picture stayed). A picture of the maker's that cannot be used, or was made as the work was stopped, is deleted
    with its note.

    `asks` (a short with an editing style): what to ask the engine, in order, each (prompt, negative, the pictures
    it is shown); the next is asked only when the one before it made no picture (the main character's picture could
    not be drawn from, so the words alone are tried). `referenced` says whether the picture was drawn from one.
    Without `asks` the engine is asked as shorts always asked: the idea, the character and the look's style words."""
    from .looks import prompt_for

    out_dir.mkdir(parents=True, exist_ok=True)
    if asks:
        style = ""
    else:
        prompt, negative = prompt_for(look, picture, character)
        asks, style = [(prompt, negative, ())], look.id
    prompt, negative = asks[0][0], asks[0][1]
    state = local_engines.status("image")
    why = state["why"] or "No picture maker is set up."
    if state["ready"]:
        for k, (prompt, negative, shown) in enumerate(asks):
            try:
                got = _from_engine(prompt, negative, out_dir, style=style, size=PICTURE_SIZE, seed=seed,
                                   references=tuple(shown or ()), cancel=cancel, progress=progress)
                return {"path": got["path"], "source": "engine", "engine": state["engine"], "why": "", "tried": True,
                        "prompt": prompt, "negative": negative, "note": got["note"], "referenced": bool(shown)}
            except _NoPicture as exc:
                why = str(exc)
            if cancel and cancel():
                raise Cancelled("Stopped.")
            if k + 1 < len(asks):
                log.warning("the picture maker made no picture from the main character's picture (%s); asking in "
                            "words alone", why)
    path = cards.make_card(cards.key_words(narration), look, out_dir / f"card-{seed}.png", index=index, seed=seed)
    return {"path": Path(path), "source": "card", "engine": "", "why": why, "tried": bool(state["ready"]),
            "prompt": prompt, "negative": negative, "referenced": False}


def make_cast(look: Look, character: str, out_dir: Path, *, seed: int = 0,
              cancel: Callable[[], bool] | None = None,
              progress: Callable[[float, str], None] | None = None) -> dict:
    """The picture of a short's main character alone (looks.cast_prompt), which the scenes that show them are drawn
    from: {"path", "note", "prompt", "why"}; "path" is None, and `why` says so in the owner's words, when the picture
    maker made none (the scenes then describe the character in words)."""
    from .looks import cast_prompt

    out_dir.mkdir(parents=True, exist_ok=True)
    prompt, negative = cast_prompt(look, character)
    try:
        got = _from_engine(prompt, negative, out_dir, style="", size=CAST_SIZE, seed=seed, name="character",
                           cancel=cancel, progress=progress)
    except _NoPicture as exc:
        if cancel and cancel():
            raise Cancelled("Stopped.") from exc
        return {"path": None, "note": "", "prompt": prompt, "why": str(exc)}
    return {**got, "prompt": prompt, "why": ""}

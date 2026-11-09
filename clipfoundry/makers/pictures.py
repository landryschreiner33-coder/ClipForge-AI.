"""A scene's picture for an animated short (docs/clipforge/ANIMATED_SHORTS.md): made by the local picture engine
when one is set up (clipfoundry/engines through local_engines.py), otherwise a designed card with the scene's key
words (cards.py). A failing engine never stops the short: the card stands in and the reason is kept for the page.
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


def make(narration: str, picture: str, look: Look, out_dir: Path, *, character: str = "", seed: int = 0,
         index: int = 0, cancel: Callable[[], bool] | None = None,
         progress: Callable[[float, str], None] | None = None) -> dict:
    """Make the picture into `out_dir`: {"path", "source": "engine" | "card", "engine", "why", "tried", "prompt",
    "negative"}. `why` says why the engine did not make it ("" when it did); `tried`: the engine was asked (so a
    card means it failed, not that none is set up)."""
    from .looks import prompt_for

    out_dir.mkdir(parents=True, exist_ok=True)
    prompt, negative = prompt_for(look, picture, character)
    state = local_engines.status("image")
    why = state["why"] or "No picture maker is set up."
    if state["ready"]:
        try:
            made = Path(local_engines.module().make_image(  # type: ignore[union-attr]
                prompt, negative=negative, style=look.id, width=PICTURE_SIZE[0], height=PICTURE_SIZE[1], seed=seed,
                progress=progress, cancel=cancel))
            suffix = made.suffix.lower() if made.suffix.lower() in SUFFIXES else ".png"
            if not made.is_file() or made.stat().st_size == 0:
                raise _NoPicture("The picture maker gave no picture, so ClipForge drew a card.")
            if not _opens(made):
                raise _NoPicture("The picture maker's picture could not be opened, so ClipForge drew a card.")
            path = out_dir / f"picture-{seed}{suffix}"
            shutil.copyfile(made, path)  # the engine's file stays the engine's
            return {"path": path, "source": "engine", "engine": state["engine"], "why": "", "tried": True,
                    "prompt": prompt, "negative": negative}
        except (Canceled, Cancelled):
            raise
        except _NoPicture as exc:
            why = str(exc)
        except OSError as exc:  # its words are for the log
            log.warning("the picture engine's picture could not be saved: %s", exc)
            why = "The picture maker's picture could not be saved, so ClipForge drew a card. Check that the disk " \
                  "has free space."
        except local_engines.errors() as exc:  # written for the owner
            why = f"The picture maker could not make this picture ({str(exc)[:160]})."
        except Exception:  # noqa: BLE001 - a broken engine never stops the short
            log.exception("picture engine failed")
            why = "The picture maker stopped with an error, so ClipForge drew a card."
        if cancel and cancel():
            raise Cancelled("Stopped.")
    path = cards.make_card(cards.key_words(narration), look, out_dir / f"card-{seed}.png", index=index, seed=seed)
    return {"path": Path(path), "source": "card", "engine": "", "why": why, "tried": bool(state["ready"]),
            "prompt": prompt, "negative": negative}

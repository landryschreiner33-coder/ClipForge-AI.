"""The one door from the makers to the local engines (clipfoundry/engines, set up under Settings → Pictures, video, voice;
docs/clipforge/LOCAL_ENGINES.md and docs/clipforge/ANIMATED_SHORTS.md).

The engines module is made by separate work and may be missing from this ClipForge, or present with no engine set
up. Everything here answers in both cases and never raises: a maker asks `status(role)` and uses its own fallback
when the role is not ready, or when an engine call raises one of `errors()`.
"""
from __future__ import annotations

import logging
from pathlib import Path

ROLES = ("image", "video", "voice")
log = logging.getLogger(__name__)


def module():
    """The engines module, or None when this ClipForge does not have it."""
    try:
        from .. import engines  # noqa: PLC0415 - optional, made by the local-engines work
    except ImportError:
        return None
    return engines


def available() -> bool:
    return module() is not None


def made_here(path: Path | str) -> bool:
    """Whether `path` is a file the makers saved in their own folder (<data>/engines/made): what a maker such as the
    animated shorts takes into its project, with its note, instead of leaving a copy there."""
    from .. import config

    try:
        made = (config.data_dir() / "engines" / "made").resolve()
        target = Path(path).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return made in target.parents and target.is_file()


def status(role: str) -> dict:
    """{"ready": bool, "engine": str, "why": str, "available": bool} for one role. Never raises."""
    mod = module()
    if mod is None:
        return {"ready": False, "engine": "", "why": "This version of ClipForge does not have the local makers yet.",
                "available": False}
    try:
        got = mod.status(role) or {}
    except Exception as exc:  # noqa: BLE001 - a broken engine is reported, never fatal
        log.exception("engine status failed")
        return {"ready": False, "engine": "", "why": f"The {role} engine could not be checked ({exc}).",
                "available": True}
    return {"ready": bool(got.get("ready")), "engine": str(got.get("engine") or ""), "why": str(got.get("why") or ""),
            "available": True}


def errors() -> tuple[type[BaseException], ...]:
    """What an engine call may raise for a reason the owner should read (anything else is a bug and is logged)."""
    mod = module()
    err = getattr(mod, "EngineError", None) if mod is not None else None
    return ((err,) if isinstance(err, type) and issubclass(err, BaseException) else ()) + (OSError,)

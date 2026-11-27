"""Example pictures of the looks of an animated short, made by the picture maker on this computer
(docs/clipforge/ANIMATED_SHORTS.md).

The page draws each look itself (frontend lookArt.tsx), so every card has an example even with no picture maker. With
one set up, Make examples asks it for the same small scene in every look, so the owner sees what that maker draws in
each style before choosing. One job at a time draws them all, in the app's heavy-work thread; each finished example
is kept as it comes, so a stopped job keeps the ones it made. They live in the data folder (look_examples/), stay on
this computer and are not part of any project.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageOps

from .. import config, db
from ..pipeline.common import Cancelled
from ..studio.jobs import Canceled, Lease, cancel as cancel_job, enqueue, handler, on_stop
from . import local_engines
from .looks import BY_ID, LOOKS

log = logging.getLogger(__name__)

KIND = "look_examples"
TARGET = "looks"
# The same small scene in every look: something living, a place and a sky, so the look's light and lines show.
IDEA = "a small red fox sitting on a grassy hill at dusk, a lighthouse on a far hill behind it, wide shot"
SAY = "A fox on a hill at dusk"
SEED = 7
SIZE = (360, 640)    # kept small: a card's example, not a picture for a short
WORKING = ("queued", "running")


class ExampleError(Exception):
    status = 409


def folder() -> Path:
    return config.data_dir() / "look_examples"


def _index_path() -> Path:
    return folder() / "examples.json"


def _index() -> dict:
    try:
        got = json.loads(_index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"examples": {}, "job_id": "", "round": 0}
    if not isinstance(got, dict):
        return {"examples": {}, "job_id": "", "round": 0}
    examples = got.get("examples") if isinstance(got.get("examples"), dict) else {}
    return {"examples": {k: v for k, v in examples.items() if k in BY_ID and isinstance(v, dict)},
            "job_id": str(got.get("job_id") or ""), "round": int(got.get("round") or 0)}


def _save(index: dict) -> None:
    folder().mkdir(parents=True, exist_ok=True)
    tmp = _index_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(index), encoding="utf-8")
    tmp.replace(_index_path())


def file(look_id: str) -> Path | None:
    """The example picture of this look, when the picture maker made one."""
    entry = _index()["examples"].get(look_id)
    if not entry:
        return None
    path = folder() / f"{look_id}.jpg"
    return path if path.is_file() else None


def _job(index: dict) -> dict | None:
    return db.fetch("studio_jobs", index["job_id"]) if index["job_id"] else None


def view() -> dict:
    """{"examples": {look: {"url", "engine", "at"}}, "job": {"status", "progress", "message", "error"} | None,
    "can_make", "why"}: what the page shows on the look cards and the Make examples button."""
    index = _index()
    state = local_engines.status("image")
    examples = {}
    for look_id, entry in index["examples"].items():
        if file(look_id):
            at = int(entry.get("at") or 0)
            examples[look_id] = {"url": f"/api/studio/shorts/look-examples/{look_id}?v={at}",
                                 "engine": str(entry.get("engine") or "the picture maker"), "at": at}
    job = _job(index)
    return {"examples": examples,
            "job": {k: job.get(k) for k in ("status", "progress", "message", "error")} if job else None,
            "can_make": bool(state["ready"]), "why": "" if state["ready"] else (state["why"] or
                                                                              "No picture maker is set up.")}


def start(workspace_id: str) -> dict:
    """Ask the picture maker for an example of every look (one job; asking while it runs changes nothing)."""
    state = local_engines.status("image")
    if not state["ready"]:
        raise ExampleError(state["why"] or "Set up a picture maker first, then make the examples.")
    index = _index()
    job = _job(index)
    if job and job["status"] in WORKING:
        return view()
    index["round"] += 1
    job = enqueue(workspace_id, KIND, TARGET, index["round"])
    index["job_id"] = job["id"]
    _save(index)
    return view()


def stop() -> dict:
    index = _index()
    job = _job(index)
    if job and job["status"] in WORKING:
        cancel_job(job["id"])
    return view()


@on_stop(KIND)
def _stopped(job: dict, how: str) -> None:  # the examples already made stay; nothing else to settle
    log.info("look examples job %s %s", job.get("id"), how)


def _keep(made: Path, look_id: str) -> None:
    """A small copy of the maker's picture, as this look's example."""
    folder().mkdir(parents=True, exist_ok=True)
    out = folder() / f"{look_id}.jpg"
    with Image.open(made) as im:
        small = ImageOps.fit(ImageOps.exif_transpose(im).convert("RGB"), SIZE, Image.Resampling.LANCZOS)
    tmp = out.with_suffix(".part.jpg")
    small.save(tmp, "JPEG", quality=86)
    tmp.replace(out)


@handler(KIND)
def make_job(job: dict, lease: Lease) -> dict:
    from . import pictures

    if _index()["job_id"] != job["id"]:
        return {"skipped": True}
    made, why = [], ""
    with tempfile.TemporaryDirectory(prefix="clipforge-look-examples-") as tmp:
        for i, look in enumerate(LOOKS):
            if lease.canceled():
                raise Canceled()
            lease.progress(i / len(LOOKS), f"Drawing the {look.name} example ({i + 1} of {len(LOOKS)})")

            def step(frac: float, _message: str = "", i: int = i, name: str = look.name) -> None:
                lease.progress((i + max(0.0, min(frac, 1.0))) / len(LOOKS),
                               f"Drawing the {name} example ({i + 1} of {len(LOOKS)})")

            try:
                got = pictures.make(SAY, IDEA, look, Path(tmp) / look.id, seed=SEED, index=i,
                                    cancel=lease.canceled, progress=step)
            except (Canceled, Cancelled):
                raise Canceled() from None
            if lease.canceled():  # stopped while it was drawn: this one is not kept
                raise Canceled()
            if got["source"] != "engine":
                why = got["why"] or "The picture maker did not make the example."
                break  # the maker is not drawing: asking it for the other looks would fail the same way
            _keep(Path(got["path"]), look.id)
            index = _index()
            index["examples"][look.id] = {"engine": got["engine"], "at": int(time.time())}
            _save(index)
            made.append(look.id)
            shutil.rmtree(Path(tmp) / look.id, ignore_errors=True)
    if why and not made:
        raise ExampleError(why)
    return {"made": made, "why": why}

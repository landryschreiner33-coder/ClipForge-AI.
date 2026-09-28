"""Background uploads. One publication at a time, on its own thread so rendering keeps going meanwhile."""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from .. import db
from ..pipeline.common import log
from . import youtube
from .common import Cancelled, PublishError

ACTIVE = ("queued", "uploading", "processing")


def feature_snapshot(clip: dict, version: dict | None = None) -> dict:
    """What the clip looked like when it was published, stored next to its real performance later so the ranking
    can be checked against actual results."""
    a = clip.get("analysis") or {}
    return {"viral_potential": clip.get("score"), "subscores": a.get("subscores") or {},
            "factors": a.get("factors") or {}, "structure": (a.get("structure") or {}).get("label", ""),
            "flags": [f.get("id") for f in a.get("flags") or []], "category": clip.get("category", ""),
            "duration": (version or clip).get("duration"), "version": (version or {}).get("kind", "original"),
            "scored_by": clip.get("score_source", ""), "snapshot_at": time.time()}


def _progress_writer(pub_id: str) -> Callable[[float], None]:
    last = [0.0, -1.0]

    def write(frac: float) -> None:
        now = time.time()
        if frac >= 1.0 or frac - last[1] >= 0.01 and now - last[0] >= 0.5:
            last[0], last[1] = now, frac
            db.update_publication(pub_id, progress=round(min(frac, 1.0), 4))

    return write


def run_youtube(pub: dict, cancelled: Callable[[], bool]) -> None:
    settings = db.get_settings()
    token = youtube.Token(settings)
    opts = pub.get("options") or {}
    body = youtube.video_body(pub["title"], pub["description"], pub.get("tags") or [], pub["requested_privacy"],
                              bool(opts.get("made_for_kids")), settings.get("youtube_category_id") or "22")
    db.update_publication(pub["id"], status="uploading", progress=0, message="Uploading to YouTube")
    video = youtube.upload(pub["video_path"], body, token, _progress_writer(pub["id"]), cancelled)
    vid = video.get("id", "")
    st = video.get("status") or {}
    privacy = st.get("privacyStatus") or pub["requested_privacy"]
    wanted = pub["requested_privacy"]
    locked = wanted != "private" and privacy == "private"
    if locked:
        message = f"Uploaded, but YouTube set it to Private instead of {wanted.capitalize()}. {youtube.UNVERIFIED_NOTE}"
    else:
        message = (f"Uploaded to YouTube as {privacy.capitalize()}. YouTube is processing it; it shows up on your "
                   "channel within a few minutes.")
        if wanted != "private" and not settings.get("youtube_project_verified"):
            message += (" Your API project is not marked as audited, so YouTube may still lock it to Private: "
                        "use Refresh status or check YouTube Studio.")
    db.update_publication(pub["id"], status="done", progress=1.0, remote_id=vid, url=youtube.video_url(vid),
                          privacy=privacy, message=message,
                          info={"studio_url": youtube.studio_url(vid), "upload_status": st.get("uploadStatus", ""),
                                "locked_private": locked})


RUNNERS: dict[str, Callable[[dict, Callable[[], bool]], None]] = {"youtube": run_youtube}


def refresh(pub: dict) -> dict:
    """Ask the platform for the current state of an uploaded video."""
    if pub["platform"] == "youtube" and pub.get("remote_id"):
        st = youtube.video_status(youtube.Token(db.get_settings()), pub["remote_id"])
        info = {**(pub.get("info") or {}), **{k: v for k, v in st.items() if k != "exists"}, "checked_at": time.time()}
        if not st["exists"]:
            db.update_publication(pub["id"], info=info, message="This video no longer exists on YouTube.")
        else:
            locked = pub["requested_privacy"] != "private" and st["privacy"] == "private"
            msg = pub.get("message", "")
            if locked and not (pub.get("info") or {}).get("locked_private"):
                msg = f"YouTube set this video to Private. {youtube.UNVERIFIED_NOTE}"
            info["locked_private"] = locked or (pub.get("info") or {}).get("locked_private", False)
            db.update_publication(pub["id"], privacy=st["privacy"], info=info, message=msg)
    return db.get_publication(pub["id"]) or pub


class PublishWorker:
    def __init__(self) -> None:
        self.q: queue.Queue = queue.Queue()
        self.cancelled: set[str] = set()
        self.current: str | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, daemon=True, name="clipfoundry-publisher")
            self._thread.start()

    def submit(self, pub_id: str) -> None:
        self.q.put(pub_id)
        self.start()

    def cancel(self, pub_id: str) -> None:
        self.cancelled.add(pub_id)

    def _loop(self) -> None:
        while True:
            pub_id = self.q.get()
            self.current = pub_id
            try:
                self._run(pub_id)
            except Exception:  # noqa: BLE001 - never let the publisher die
                log.exception("publish job crashed")
            finally:
                self.current = None
                self.cancelled.discard(pub_id)
                self.q.task_done()

    def _run(self, pub_id: str) -> None:
        pub = db.get_publication(pub_id)
        if not pub:
            return
        if pub_id in self.cancelled:
            db.update_publication(pub_id, status="cancelled", message="Cancelled before the upload started.")
            return
        runner = RUNNERS.get(pub["platform"])
        if runner is None:
            db.update_publication(pub_id, status="failed", error=f"Unknown platform {pub['platform']}")
            return
        try:
            runner(pub, lambda: pub_id in self.cancelled)
        except Cancelled:
            db.update_publication(pub_id, status="cancelled", message="Upload cancelled. Nothing was published.")
        except PublishError as exc:
            log.warning("%s publish failed: %s", pub["platform"], exc)
            db.update_publication(pub_id, status="failed", error=str(exc), fix=exc.fix,
                                  info={**(pub.get("info") or {}), "code": exc.code})
        except Exception as exc:  # noqa: BLE001
            log.exception("%s publish failed", pub["platform"])
            db.update_publication(pub_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:500])


worker = PublishWorker()

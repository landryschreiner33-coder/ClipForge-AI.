"""Background uploads. One publication at a time, on its own thread so rendering keeps going meanwhile."""
from __future__ import annotations

import os
import queue
import threading
import time
from typing import Callable

from .. import audience, db
from ..pipeline.common import log
from . import tiktok, youtube
from .common import SHORT_WAIT, Cancelled, PublishError, asked_to_wait, sleep_exactly, wait_text

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
    """Upload as Private (the audience policy's only YouTube visibility); never a later public release."""
    settings = db.get_settings()
    token = youtube.Token(settings)
    opts = pub.get("options") or {}
    decision = audience.check("youtube", pub["requested_privacy"], settings, options=opts)
    body = youtube.video_body(pub["title"], pub["description"], pub.get("tags") or [], pub["requested_privacy"],
                              bool(opts.get("made_for_kids")), settings.get("youtube_category_id") or "22")
    db.update_publication(pub["id"], status="uploading", progress=0, message="Uploading to YouTube (Private)")

    def remember(session: str) -> None:  # lets an interrupted upload resume instead of uploading twice
        current = db.get_publication(pub["id"]) or pub
        db.update_publication(pub["id"], info={**(current.get("info") or {}), "upload_session": session,
                                               "session_started": time.time()})

    def final_chunk() -> None:  # from now on the video may exist on YouTube even if its answer never arrives
        current = db.get_publication(pub["id"]) or pub
        db.update_publication(pub["id"], info={**(current.get("info") or {}), "final_chunk_at": time.time()})

    info = pub.get("info") or {}
    video = youtube.upload(pub["video_path"], body, token, _progress_writer(pub["id"]), cancelled,
                           on_session=remember, resume_session=info.get("upload_session", ""),
                           on_final_chunk=final_chunk, may_be_complete=bool(info.get("final_chunk_at")))
    vid = video.get("id", "")
    st = video.get("status") or {}
    privacy = st.get("privacyStatus") or ""
    info = {**((db.get_publication(pub["id"]) or pub).get("info") or {}), "studio_url": youtube.studio_url(vid),
            "upload_status": st.get("uploadStatus", "")}
    info = audience.record(info, decision, privacy, "api_response" if privacy else "unknown")
    if decision.setup == audience.SETUP_AWAITING_INVITES:
        message = ("Uploaded privately. Test viewers cannot watch yet: share it privately in YouTube Studio with the "
                   "people you chose, then press 'Viewers invited'.")
    else:
        message = "Uploaded privately for you only (staging). No test viewer can see it."
    db.update_publication(pub["id"], status="done", progress=1.0, remote_id=vid, url=youtube.video_url(vid),
                          privacy=privacy or "unknown", message=message, info=info)


def _tiktok_outcome(pub: dict, st: dict, username: str) -> dict:
    """Publication fields for a TikTok status/fetch answer (empty while TikTok is still working on it)."""
    status = st.get("status", "")
    if status == "PUBLISH_COMPLETE":
        ids = st.get("publicaly_available_post_id") or []  # TikTok's spelling
        url = tiktok.post_url(username, str(ids[0])) if ids else ""
        seen = tiktok.PRIVACY_LABELS.get(pub["requested_privacy"], pub["requested_privacy"])
        info = {**(pub.get("info") or {}), "post_ids": ids, "tiktok_status": status}
        aud = info.get("audience") or {}
        if aud:  # TikTok published with exactly the privacy level that was sent (it rejects options it lacks)
            setup = aud.get("setup")
            if aud.get("intent") == audience.SELECTED_AUDIENCE and aud.get("requested") == pub["requested_privacy"]:
                setup = audience.SETUP_API_VERIFIED
            info["audience"] = {**aud, "returned": pub["requested_privacy"], "evidence": "api_publish_complete",
                                "setup": setup}
        return {"status": "done", "progress": 1.0, "url": url, "privacy": pub["requested_privacy"],
                "message": f"Posted on TikTok ({seen}). {tiktok.PROCESSING_NOTE}"
                           + ("" if url else " Open your TikTok profile to see it."), "info": info}
    if status == "SEND_TO_USER_INBOX":
        return {"status": "action_needed", "progress": 1.0,
                "message": "Sent to your TikTok inbox. Open the TikTok app, tap the notification about the new video, "
                           "edit it if you like, choose who can see it and post it.",
                "info": {**(pub.get("info") or {}), "tiktok_status": status}}
    if status == "FAILED":
        err = tiktok.api_error(st.get("fail_reason", ""), st.get("fail_reason", ""))
        return {"status": "failed", "error": str(err), "fix": err.fix,
                "info": {**(pub.get("info") or {}), "tiktok_status": status, "code": err.code}}
    return {}


def run_tiktok(pub: dict, cancelled: Callable[[], bool]) -> None:
    settings = db.get_settings()
    token = tiktok.Token(settings)
    opts = pub.get("options") or {}
    mode = pub.get("mode") or "direct"
    username = ""
    decision = audience.check("tiktok", pub["requested_privacy"], settings, mode=mode, options=opts)
    db.update_publication(pub["id"], info=audience.record(pub.get("info") or {}, decision, "", "requested"))
    if mode == "direct":  # TikTok asks apps to read the creator's current options right before posting
        info = tiktok.creator_info(token)
        username = info["username"]
        tiktok.validate(pub["description"], pub["requested_privacy"], opts, mode, settings, info,
                        float(opts.get("duration") or 0))
    size = os.path.getsize(pub["video_path"])
    where = "TikTok" if mode == "direct" else "your TikTok inbox"
    db.update_publication(pub["id"], status="uploading", progress=0, message=f"Uploading to {where}")
    init = tiktok.init_upload(token, mode, size, pub["description"], pub["requested_privacy"], opts)
    current = db.get_publication(pub["id"]) or pub
    db.update_publication(pub["id"], remote_id=init["publish_id"], info={**(current.get("info") or {}),
                                                                         "username": username})
    tiktok.upload_chunks(init["upload_url"], pub["video_path"], _progress_writer(pub["id"]), cancelled)
    db.update_publication(pub["id"], status="processing", progress=1.0,
                          message=f"Uploaded. TikTok is processing it. {tiktok.PROCESSING_NOTE}")
    deadline = time.time() + tiktok.POLL_TIMEOUT
    while time.time() < deadline:
        time.sleep(tiktok.POLL_SECONDS)
        current = db.get_publication(pub["id"]) or pub
        try:
            st = tiktok.fetch_status(token, init["publish_id"])
        except PublishError as exc:  # the video is uploaded: only reading its state has to wait
            asked = asked_to_wait(exc)
            if asked is None or asked > SHORT_WAIT:
                raise
            sleep_exactly(asked, cancelled)
            continue
        outcome = _tiktok_outcome(current, st, username)
        if outcome:
            db.update_publication(pub["id"], **outcome)
            return
    db.update_publication(pub["id"], message="Uploaded; TikTok is still processing it. Use Refresh status later, "
                                             "or check your TikTok profile.")


RUNNERS: dict[str, Callable[[dict, Callable[[], bool]], None]] = {"youtube": run_youtube, "tiktok": run_tiktok}


def refresh(pub: dict) -> dict:
    """Ask the platform for the current state of an uploaded video."""
    if pub["platform"] == "youtube" and pub.get("remote_id"):
        st = youtube.video_status(youtube.Token(db.get_settings()), pub["remote_id"])
        info = {**(pub.get("info") or {}), **{k: v for k, v in st.items() if k != "exists"}, "checked_at": time.time()}
        if not st["exists"]:
            db.update_publication(pub["id"], info=info, message="This video no longer exists on YouTube.")
        else:
            msg = pub.get("message", "")
            drift = audience.visibility_mismatch("youtube", pub["requested_privacy"], st["privacy"])
            if drift:  # visibility drift after upload: say so plainly; nothing is changed remotely by itself
                info["visibility_drift"] = {"at": time.time(), "detail": drift}
                msg = f"{drift} Set it back to Private in YouTube Studio."
            aud = info.get("audience") or {}
            if aud:
                info["audience"] = {**aud, "returned": st["privacy"], "evidence": "api_status",
                                    "checked_at": time.time()}
            db.update_publication(pub["id"], privacy=st["privacy"], info=info, message=msg)
    if pub["platform"] == "tiktok" and pub.get("remote_id") and pub["status"] in ("processing", "action_needed"):
        token = tiktok.Token(db.get_settings())
        outcome = _tiktok_outcome(pub, tiktok.fetch_status(token, pub["remote_id"]),
                                  (pub.get("info") or {}).get("username", ""))
        if outcome and not (pub["status"] == "action_needed" and outcome["status"] == "action_needed"):
            db.update_publication(pub["id"], **outcome)
    return db.get_publication(pub["id"]) or pub


def _clock(ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


class PublishWorker:
    """Uploads you start in the Publish Center, one at a time. When a platform asks to wait (Retry-After, or a rate
    limit), the upload is not failed and not retried sooner: it stays queued with its time (`info.retry_at`) and
    starts again then, continuing a YouTube upload session where it stopped. The time survives a restart."""

    def __init__(self) -> None:
        self.q: queue.Queue = queue.Queue()
        self.cancelled: set[str] = set()
        self.current: str | None = None
        self.timers: dict[str, threading.Timer] = {}
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
        timer = self.timers.pop(pub_id, None)
        if timer:  # waiting for the platform's time: nothing is running, so it is canceled right away
            timer.cancel()
            self.cancelled.discard(pub_id)
            db.update_publication(pub_id, status="cancelled", message="Cancelled while waiting. Nothing was published.")

    def later(self, pub_id: str, at: float) -> None:
        """Start this upload again at `at` (the time the platform asked for), not before."""
        old = self.timers.pop(pub_id, None)
        if old:
            old.cancel()
        timer = threading.Timer(max(0.0, at - time.time()), self._due, [pub_id])
        timer.daemon = True
        self.timers[pub_id] = timer
        timer.start()

    def _due(self, pub_id: str) -> None:
        self.timers.pop(pub_id, None)
        self.submit(pub_id)

    def resume_waiting(self) -> int:
        """After a restart: uploads that were waiting for a platform's time start again at that time."""
        n = 0
        for pub in db.list_publications():
            at = (pub.get("info") or {}).get("retry_at")
            if pub["status"] == "queued" and at and not pub.get("scheduled_id"):
                self.later(pub["id"], float(at))
                n += 1
        return n

    def cancel_all(self) -> int:
        """STOP ALL JOBS: queued uploads are canceled, the running one stops at its next chunk."""
        n = 0
        for pub_id in list(self.timers):
            self.cancel(pub_id)
            n += 1
        while True:
            try:
                pub_id = self.q.get_nowait()
            except queue.Empty:
                break
            self.cancelled.add(pub_id)
            db.update_publication(pub_id, status="cancelled", message="Stopped with Stop all jobs")
            self.q.task_done()
            n += 1
        if self.current:
            self.cancelled.add(self.current)
            n += 1
        return n

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
        if not pub or pub["status"] == "cancelled":
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
            current = db.get_publication(pub_id) or pub
            name = "YouTube" if pub["platform"] == "youtube" else "TikTok"
            if current["status"] == "processing":  # uploaded: only reading the outcome failed; never upload it twice
                db.update_publication(pub_id, message=f"Uploaded; {name} did not say yet whether it is posted ({exc}). "
                                                      "Use Refresh status later, or check your profile.")
                return
            asked = asked_to_wait(exc)
            if asked is not None:  # the platform asked to wait: start again exactly then, never sooner
                at = time.time() + asked
                db.update_publication(pub_id, status="queued", error="", fix="",
                                      message=f"{name} asked to wait {wait_text(asked)}. The upload starts again "
                                              f"at {_clock(at)}.",
                                      info={**(current.get("info") or {}), "retry_at": at, "code": exc.code})
                self.later(pub_id, at)
                return
            log.warning("%s publish failed: %s", pub["platform"], exc)
            db.update_publication(pub_id, status="failed", error=str(exc), fix=exc.fix,
                                  info={**(current.get("info") or {}), "code": exc.code})
        except Exception as exc:  # noqa: BLE001
            log.exception("%s publish failed", pub["platform"])
            db.update_publication(pub_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:500])


worker = PublishWorker()

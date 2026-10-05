"""Background uploads. One publication at a time, on its own thread so rendering keeps going meanwhile."""
from __future__ import annotations

import os
import queue
import threading
import time
from typing import Callable

from .. import db
from ..pipeline.common import log
from . import tiktok, youtube
from .common import SHORT_WAIT, Cancelled, PublishError, asked_to_wait, sleep_exactly, wait_text

ACTIVE = ("queued", "uploading", "processing")
LOCAL_TEST_WAIT = 30.0
LOCAL_TEST_NOTE = "Local test mode is on. Clips stay on this computer; platform uploads are held."


class LocalTestPaused(Cancelled):
    """Pause the existing upload without discarding its resumable session or final-byte marker."""


def local_test_mode() -> bool:
    return bool(db.get_settings().get("autopilot_local_test_mode"))


def check_local_test_mode() -> None:
    if local_test_mode():
        raise PublishError(LOCAL_TEST_NOTE, "Turn off Local test mode before publishing.", "local_test_mode")


def check_local_test_publication(pub: dict) -> None:
    """A local test never grants reuse permission, even when a later upload is started manually."""
    clip = db.get_clip(pub.get("clip_id") or "") or {}
    project = db.get_project(clip.get("project_id") or pub.get("project_id") or "") or {}
    if not (project.get("options") or {}).get("local_test_mode"):
        return
    from ..autopilot import gate, queue as work_queue, rights

    source_id = project.get("source_id") or ""
    source = db.fetch("sources", source_id) if source_id else None
    if source_id and source is None:
        raise PublishError("The original video's reuse permission cannot be confirmed.",
                           "Restore the source and confirm its reuse permission before publishing.", "rights_blocked")
    settings = db.get_settings()
    try:
        rights.gate(source, "publish", settings)
    except rights.RightsBlocked as exc:
        raise PublishError(str(exc), "Confirm reuse permission in Autopilot → Permissions & sources.",
                           "rights_blocked") from exc
    allowed, why = rights.platform_allowed(source, pub["platform"], settings)
    if not allowed:
        raise PublishError(why, "The reuse terms must cover this platform before publishing.", "rights_blocked")
    current = db.get_publication(pub.get("id") or "") or pub
    info = current.get("info") or {}
    if info.get("upload_session") or current.get("remote_id") or info.get("final_chunk_at"):
        return  # continue or reconcile the same accepted upload; do not replace its already approved bytes
    if not clip:
        raise PublishError("The clip is missing.", "Restore the clip before publishing.", "quality")
    try:
        gate.verify_file(clip, pub.get("video_path") or "")
    except work_queue.Wait as exc:
        raise PublishError(exc.message, "Wait for the final file check, then publish again.",
                           "quality_pending") from exc
    except work_queue.Fail as exc:
        raise PublishError(str(exc), exc.fix or "Fix the clip and render it again before publishing.",
                           "quality") from exc


def upload_cancelled(cancelled: Callable[[], bool]) -> Callable[[], bool]:
    def check() -> bool:
        if cancelled():
            return True
        if local_test_mode():
            raise LocalTestPaused()
        return False

    return check


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
    check_local_test_mode()
    check_local_test_publication(pub)
    cancelled = upload_cancelled(cancelled)
    settings = db.get_settings()
    token = youtube.Token(settings)
    opts = pub.get("options") or {}
    publish_at = opts.get("publish_at") if (opts.get("publish_at") or 0) > time.time() + 300 else None
    body = youtube.video_body(pub["title"], pub["description"], pub.get("tags") or [], pub["requested_privacy"],
                              bool(opts.get("made_for_kids")), settings.get("youtube_category_id") or "22",
                              publish_at)
    db.update_publication(pub["id"], status="uploading", progress=0, message="Uploading to YouTube")

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
    privacy = st.get("privacyStatus") or pub["requested_privacy"]
    wanted = pub["requested_privacy"]
    info = {**((db.get_publication(pub["id"]) or pub).get("info") or {}), "studio_url": youtube.studio_url(vid),
            "upload_status": st.get("uploadStatus", "")}
    if publish_at and st.get("publishAt"):
        when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(publish_at))
        message = (f"Uploaded as Private and scheduled: YouTube makes it public at {when}.")
        if not settings.get("youtube_project_verified"):
            message += (" Your API project is not marked as audited: YouTube may keep it Private at that time. "
                        "Check it with Refresh status after the scheduled time.")
        db.update_publication(pub["id"], status="done", progress=1.0, remote_id=vid, url=youtube.video_url(vid),
                              privacy="private", message=message,
                              info={**info, "publish_at": publish_at, "scheduled": True, "locked_private": False})
        return
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
                          privacy=privacy, message=message, info={**info, "locked_private": locked})


def _tiktok_outcome(pub: dict, st: dict, username: str) -> dict:
    """Publication fields for a TikTok status/fetch answer (empty while TikTok is still working on it)."""
    status = st.get("status", "")
    if status == "PUBLISH_COMPLETE":
        ids = st.get("publicaly_available_post_id") or []  # TikTok's spelling
        url = tiktok.post_url(username, str(ids[0])) if ids else ""
        seen = tiktok.PRIVACY_LABELS.get(pub["requested_privacy"], pub["requested_privacy"])
        return {"status": "done", "progress": 1.0, "url": url, "privacy": pub["requested_privacy"],
                "message": f"Posted on TikTok ({seen}). {tiktok.PROCESSING_NOTE}"
                           + ("" if url else " Open your TikTok profile to see it."),
                "info": {**(pub.get("info") or {}), "post_ids": ids, "tiktok_status": status}}
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
    check_local_test_mode()
    check_local_test_publication(pub)
    cancelled = upload_cancelled(cancelled)
    settings = db.get_settings()
    token = tiktok.Token(settings)
    opts = pub.get("options") or {}
    mode = pub.get("mode") or "direct"
    username = ""
    if mode == "direct":  # TikTok asks apps to read the creator's current options right before posting
        info = tiktok.creator_info(token)
        username = info["username"]
        tiktok.validate(pub["description"], pub["requested_privacy"], opts, mode, settings, info,
                        float(opts.get("duration") or 0))
    size = os.path.getsize(pub["video_path"])
    where = "TikTok" if mode == "direct" else "your TikTok inbox"
    saved = pub.get("info") or {}
    resuming = (pub["status"] == "uploading" or saved.get("local_test_hold")) \
        and pub.get("remote_id") and saved.get("upload_url")
    offset = int(saved.get("upload_offset") or 0) if resuming else 0
    if resuming and saved.get("local_test_hold"):
        # A mode change may interrupt a request after TikTok accepted bytes. Read its confirmed position before
        # continuing that same publish ID; never initialize another post or guess how many bytes arrived.
        status = tiktok.fetch_status(token, pub["remote_id"])
        outcome = _tiktok_outcome(pub, status, saved.get("username", ""))
        if outcome:
            db.update_publication(pub["id"], **outcome)
            return
        offset = status.get("uploaded_bytes")
        if status.get("status") != "PROCESSING_UPLOAD" or offset == size:
            db.update_publication(pub["id"], status="processing",
                                  message="Uploaded; TikTok is still processing it. Use Refresh status later.")
            return
        chunk, total = tiktok.chunking(size)
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset < size \
                or offset % chunk or offset // chunk >= total:
            raise PublishError("TikTok could not confirm where the held upload should continue.",
                               "Check TikTok for the video, then refresh its status before retrying.",
                               youtube.OUTCOME_UNKNOWN)
        db.update_publication(pub["id"], info={**saved, "upload_offset": offset})
    db.update_publication(pub["id"], status="uploading", progress=offset / size, message=f"Uploading to {where}")
    if resuming:
        init = {"publish_id": pub["remote_id"], "upload_url": saved["upload_url"]}
    else:
        if cancelled():
            raise Cancelled()
        init = tiktok.init_upload(token, mode, size, pub["description"], pub["requested_privacy"], opts,
                                  cancelled=cancelled)
        db.update_publication(pub["id"], remote_id=init["publish_id"],
                              info={**saved, "username": username, "upload_url": init["upload_url"],
                                    "upload_size": size, "upload_offset": 0, "final_chunk_at": 0})

    def final_chunk() -> None:
        current = db.get_publication(pub["id"]) or pub
        db.update_publication(pub["id"], info={**(current.get("info") or {}), "final_chunk_at": time.time()})

    tiktok.upload_chunks(init["upload_url"], pub["video_path"], _progress_writer(pub["id"]), cancelled,
                         resume_offset=offset, on_final_chunk=final_chunk)
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
            old = pub.get("info") or {}
            waiting = old.get("scheduled") and st["privacy"] == "private" and time.time() < float(
                old.get("publish_at") or 0) + 600
            locked = pub["requested_privacy"] != "private" and st["privacy"] == "private" and not waiting
            msg = pub.get("message", "")
            if waiting:
                msg = "Scheduled: YouTube makes it public at " + time.strftime(
                    "%Y-%m-%d %H:%M UTC", time.gmtime(float(old["publish_at"]))) + "."
            elif locked and not old.get("locked_private"):
                msg = f"YouTube kept this video Private. {youtube.UNVERIFIED_NOTE}"
            elif old.get("scheduled") and st["privacy"] == "public":
                msg = "Published: YouTube made it public at its scheduled time."
            info["locked_private"] = locked or (old.get("locked_private", False) and st["privacy"] == "private")
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
            held = (pub.get("info") or {}).get("local_test_hold") and pub["status"] in ("queued", "uploading")
            if (pub["status"] == "queued" or held) and at and not pub.get("scheduled_id"):
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
        if local_test_mode():
            self._hold_local_test(pub)
            return
        runner = RUNNERS.get(pub["platform"])
        if runner is None:
            db.update_publication(pub_id, status="failed", error=f"Unknown platform {pub['platform']}")
            return
        try:
            runner(pub, lambda: pub_id in self.cancelled)
        except LocalTestPaused:
            self._hold_local_test(db.get_publication(pub_id) or pub)
        except Cancelled:
            db.update_publication(pub_id, status="cancelled", message="Upload cancelled. Nothing was published.")
        except PublishError as exc:
            current = db.get_publication(pub_id) or pub
            if exc.code == "local_test_mode":
                self._hold_local_test(current)
                return
            info = current.get("info") or {}
            if exc.code == "rights_blocked" and (info.get("upload_session") or current.get("remote_id")
                                                  or info.get("final_chunk_at")):
                db.update_publication(pub_id, error=str(exc), fix=exc.fix,
                                      message="Upload held: reuse permission is missing. The existing upload record "
                                              "is kept; check the platform before starting another upload.")
                return
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

    def _hold_local_test(self, pub: dict) -> None:
        # Keeping the upload phase and identifiers lets TikTok and YouTube continue the same upload later.
        if pub["status"] not in ("queued", "uploading"):
            return
        at = max(time.time() + LOCAL_TEST_WAIT, float((pub.get("info") or {}).get("retry_at") or 0))
        db.update_publication(pub["id"], message=LOCAL_TEST_NOTE,
                              info={**(pub.get("info") or {}), "local_test_hold": True, "retry_at": at})
        self.later(pub["id"], at)


worker = PublishWorker()

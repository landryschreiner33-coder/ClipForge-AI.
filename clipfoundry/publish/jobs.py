"""Background uploads. One publication at a time, on its own thread so rendering keeps going meanwhile."""
from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import httpx

from .. import db
from ..pipeline.common import log
from . import audience, tiktok, youtube
from .common import SHORT_WAIT, Cancelled, PublishError, asked_to_wait, sleep_exactly, wait_text

ACTIVE = ("queued", "uploading", "processing")


def transfer_started(pub: dict | None) -> bool:
    """A local publication row alone does not establish that the platform accepted an upload session."""
    info = (pub or {}).get("info") or {}
    return bool(info.get("upload_session") or info.get("final_chunk_at") or (pub or {}).get("remote_id"))


def manual_eligibility(clip: dict, platform: str, path: str, version_id: str, settings: dict) -> None:
    """Manual Publish keeps the existing source terms and checks the selected Autopilot artifact, too."""
    from ..autopilot import gate, queue as work_queue, rights, verify
    from ..pipeline import artifact

    project = db.get_project(clip["project_id"]) or {}
    source_id = project.get("source_id") or ""
    source = db.fetch("sources", source_id) if source_id else None
    if source_id and not source:
        raise PublishError("This clip's source record is missing.", "Restore its source and review the clip again.",
                           "rights")
    if source and verify.ensure([source], settings):
        source = db.fetch("sources", source["id"]) or source
    try:
        rights.gate(source, "publish", settings)
    except rights.RightsBlocked as exc:
        raise PublishError(str(exc), "Review the source's reuse terms in Autopilot → Sources.", "rights") from exc
    allowed, why = rights.platform_allowed(source, platform, settings)
    if not allowed:
        raise PublishError(why, "The agreement for this video does not cover this platform.", "rights")
    current_path, current_version, _ = artifact.active(clip)
    if current_version != version_id or not current_path or Path(current_path).resolve() != Path(path).resolve():
        raise PublishError("The selected video version changed after confirmation.",
                           "Review the selected version and publish again.", "approval_invalidated")
    applicable = source_id or project.get("origin") == "autopilot" or bool(
        db.select("quality_reports", "clip_id = ?", (clip["id"],), limit=1))
    if applicable:
        try:
            gate.verify_file(clip, path)
        except work_queue.Wait as exc:
            raise PublishError(exc.message, "Wait for the final quality check, then publish again.", "quality") \
                from exc
        except work_queue.Fail as exc:
            raise PublishError(str(exc), exc.fix, "quality") from exc


def _check_manual_publication(pub: dict, settings: dict) -> None:
    """Recheck just before starting; resumable transfers keep their original bytes and platform handle."""
    if pub.get("scheduled_id"):
        return
    info = pub.get("info") or {}
    expected = (pub.get("options") or {}).get("approved_video_sha256")
    if expected:
        from ..pipeline import artifact

        try:
            actual = artifact.sha256_file(pub["video_path"])
        except OSError as exc:
            if info.get("final_chunk_at"):
                raise youtube._outcome_unknown() from exc
            raise PublishError("The confirmed video file is missing.", "Render it and review it again.",
                               "approval_invalidated") from exc
        if actual != expected:
            if info.get("final_chunk_at"):
                raise youtube._outcome_unknown()
            raise PublishError("The video file changed after confirmation.", "Review the file and publish again.",
                               "approval_invalidated")
    if info.get("upload_session") or pub.get("remote_id"):
        return  # Continue the same bytes without rejudging an upload halfway through its transfer.
    clip = db.get_clip(pub["clip_id"])
    if not clip or clip["status"] != "ready":
        raise PublishError("The clip is missing or not rendered.", "Render the clip and review it again.", "quality")
    manual_eligibility(clip, pub["platform"], pub["video_path"], pub.get("version_id") or "", settings)


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
    if opts.get("approved_account") and opts["approved_account"] != (db.get_account("youtube") or {}).get(
            "account_id"):
        raise PublishError("Another YouTube account is connected than the one this upload was approved for.",
                           "Reconnect the original account, or review a new post for this account.", "reconnect")
    _check_manual_publication(pub, settings)
    info = pub.get("info") or {}
    stamp = pub.get("audience") or {}
    if not info.get("upload_session"):  # an upload under way keeps going; a new one is checked against the policy
        stamp = audience.check("youtube", pub["requested_privacy"], settings, stamp=stamp or None)
        db.update_publication(pub["id"], audience=stamp)
    body = youtube.video_body(pub["title"], pub["description"], pub.get("tags") or [], pub["requested_privacy"],
                              bool(opts.get("made_for_kids")), settings.get("youtube_category_id") or "22",
                              audience_intent=stamp.get("intent") or "")
    requested = pub["requested_privacy"]
    db.update_publication(pub["id"], status="uploading", progress=0,
                          message=f"Uploading to YouTube as {requested.capitalize()}",
                          info={**info, "upload_snippet": body["snippet"]},
                          delivery={**(pub.get("delivery") or {}), "transfer": "uploading"})

    def remember(session: str) -> None:  # lets an interrupted upload resume instead of uploading twice
        current = db.get_publication(pub["id"]) or pub
        db.update_publication(pub["id"], info={**(current.get("info") or {}), "upload_session": session,
                                               "session_started": time.time()})

    def final_chunk() -> None:  # from now on the video may exist on YouTube even if its answer never arrives
        current = db.get_publication(pub["id"]) or pub
        db.update_publication(pub["id"], info={**(current.get("info") or {}), "final_chunk_at": time.time()})

    video = youtube.upload(pub["video_path"], body, token, _progress_writer(pub["id"]), cancelled,
                           on_session=remember, resume_session=info.get("upload_session", ""),
                           on_final_chunk=final_chunk, may_be_complete=bool(info.get("final_chunk_at")))
    vid = video.get("id", "")
    st = video.get("status") or {}
    privacy = st.get("privacyStatus") or ""
    info = {**((db.get_publication(pub["id"]) or pub).get("info") or {}), "studio_url": youtube.studio_url(vid),
            "upload_status": st.get("uploadStatus", "")}
    delivery = audience.delivery_after_upload("youtube", stamp, privacy, "api")
    locked_private = requested == "public" and privacy == "private"
    if requested == "private" and privacy and privacy != "private":
        audience.incident("youtube", f"YouTube reports the new video {vid} as {privacy}, not Private.", vid)
        message = f"YouTube reports this video as {privacy.capitalize()}, not Private. Check it in YouTube Studio."
    elif locked_private:
        message = ("Uploaded to YouTube, but YouTube reports Private instead of the requested Public visibility. "
                   "Check this video's visibility and your channel's restrictions in YouTube Studio. "
                   "ClipFoundry has not made it public.")
    elif stamp.get("intent") == audience.PUBLIC:
        message = "Uploaded to YouTube as Public (YouTube confirmed)." if privacy == "public" else \
            "Uploaded to YouTube; Public was requested, but YouTube did not report visibility. Check it in Studio."
    elif stamp.get("intent") == audience.OWNER_ONLY:
        message = "Uploaded to YouTube as Private. Only you can see it (staging, nobody is invited)."
    else:
        message = ("Uploaded to YouTube as Private. Next: share it privately in YouTube Studio with the people you "
                   "picked; until then nobody else can watch it.")
    db.update_publication(pub["id"], status="done", progress=1.0, remote_id=vid, url=youtube.video_url(vid),
                          privacy=privacy, message=message, info={**info, "locked_private": locked_private},
                          delivery=delivery)


def _tiktok_outcome(pub: dict, st: dict, username: str) -> dict:
    """Publication fields for a TikTok status/fetch answer (empty while TikTok is still working on it)."""
    status = st.get("status", "")
    if status == "PUBLISH_COMPLETE":
        ids = st.get("publicaly_available_post_id") or []  # TikTok's spelling
        url = tiktok.post_url(username, str(ids[0])) if ids else ""
        seen = tiktok.PRIVACY_LABELS.get(pub["requested_privacy"], pub["requested_privacy"])
        # TikTok accepted the post with the requested audience; its status answer does not report the audience back
        delivery = audience.delivery_after_upload("tiktok", pub.get("audience") or {}, "", "api")
        return {"status": "done", "progress": 1.0, "url": url, "privacy": pub["requested_privacy"],
                "message": f"Posted on TikTok, asked for {seen} (TikTok does not report who can see it: check it "
                           f"in the app). {tiktok.PROCESSING_NOTE}"
                           + ("" if url else " Open your TikTok profile to see it."),
                "info": {**(pub.get("info") or {}), "post_ids": ids, "tiktok_status": status}, "delivery": delivery}
    if status == "SEND_TO_USER_INBOX":
        public = (pub.get("audience") or {}).get("intent") == audience.PUBLIC
        group = "Everyone" if public else audience.TIKTOK_GROUP_LABELS[
            (pub.get("audience") or {}).get("group") or audience.tiktok_group(db.get_settings())].split(" (")[0]
        account_step = "" if public else " (keep your account private)"
        return {"status": "action_needed", "progress": 1.0,
                "message": "Sent to your TikTok inbox. Open the TikTok app, tap the notification about the new video, "
                           f"choose {group} as who can watch{account_step} and post it. Then paste "
                           "the post's link here.",
                "info": {**(pub.get("info") or {}), "tiktok_status": status},
                "delivery": audience.delivery_after_upload("tiktok", pub.get("audience") or {}, "", "manual")}
    if status == "FAILED":
        err = tiktok.api_error(st.get("fail_reason", ""), st.get("fail_reason", ""))
        return {"status": "failed", "error": str(err), "fix": err.fix,
                "info": {**(pub.get("info") or {}), "tiktok_status": status, "code": err.code}}
    return {}


def run_tiktok(pub: dict, cancelled: Callable[[], bool]) -> None:
    settings = db.get_settings()
    token = tiktok.Token(settings)
    opts = pub.get("options") or {}
    if opts.get("approved_account") and opts["approved_account"] != (db.get_account("tiktok") or {}).get(
            "account_id"):
        raise PublishError("Another TikTok account is connected than the one this upload was approved for.",
                           "Reconnect the original account, or review a new post for this account.", "reconnect")
    _check_manual_publication(pub, settings)
    mode = pub.get("mode") or "direct"
    username = ""
    creator = None
    if mode == "direct":  # TikTok asks apps to read the creator's current options right before posting
        creator = tiktok.creator_info(token)
        username = creator["username"]
        tiktok.validate(pub["description"], pub["requested_privacy"], opts, mode, settings, creator,
                        float(opts.get("duration") or 0))
    stamp = audience.check("tiktok", pub["requested_privacy"], settings, mode=mode, creator=creator,
                           stamp=pub.get("audience") or None)
    db.update_publication(pub["id"], audience=stamp)
    size = os.path.getsize(pub["video_path"])
    where = "TikTok" if mode == "direct" else "your TikTok inbox"
    db.update_publication(pub["id"], status="uploading", progress=0, message=f"Uploading to {where}")
    init = tiktok.init_upload(token, mode, size, pub["description"], pub["requested_privacy"], opts,
                              audience_stamp=stamp)
    db.update_publication(pub["id"], remote_id=init["publish_id"], info={**(pub.get("info") or {}),
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


def unknown_outcome(pub: dict) -> bool:
    info = pub.get("info") or {}
    return bool(info.get("outcome_unknown") or info.get("code") == youtube.OUTCOME_UNKNOWN)


def _hold_manual_unknown(pub: dict, exc: PublishError) -> dict:
    info = dict(pub.get("info") or {})
    if exc.code != youtube.OUTCOME_UNKNOWN:
        info["outcome_error"] = {"code": exc.code, "detail": str(exc), "fix": exc.fix}
    cause = info.get("outcome_error") or {}
    fix = f"{cause['fix']} " if cause.get("fix") else ""
    detail = f"{cause['detail']} {exc}" if cause.get("detail") and cause["detail"] not in str(exc) else str(exc)
    db.update_publication(pub["id"], status="processing", error=detail,
                          message="Upload outcome unknown: YouTube may already have the video. Another upload "
                                  "is held to avoid a duplicate.",
                          fix=fix + "Open YouTube Studio → Content and use Refresh status to find the existing upload. "
                              "ClipFoundry will not upload this clip again while the outcome is unknown.",
                          info={**info, "outcome_unknown": True,
                                "code": youtube.OUTCOME_UNKNOWN, "studio_url": "https://studio.youtube.com/"},
                          delivery={**(pub.get("delivery") or {}), "transfer": "outcome_unknown"})
    return db.get_publication(pub["id"]) or pub


def _cancel_publication(pub_id: str, message: str) -> None:
    pub = db.get_publication(pub_id)
    if pub and pub["platform"] == "youtube" and (pub.get("info") or {}).get("final_chunk_at"):
        _hold_manual_unknown(pub, youtube._outcome_unknown())
    elif pub:
        db.update_publication(pub_id, status="cancelled", message=message)


def _refresh_manual_unknown(pub: dict) -> dict:
    """Read the original account's recent uploads; uncertainty never starts another transfer."""
    from ..autopilot.publisher import _youtube_upload_by_title

    approved_account = (pub.get("options") or {}).get("approved_account")
    if not approved_account or approved_account != (db.get_account("youtube") or {}).get("account_id"):
        raise PublishError("Reconnect the original YouTube account before checking this upload's outcome.",
                           "The uncertain upload stays held; no video is uploaded to the current account.",
                           "reconnect")
    try:
        found = _youtube_upload_by_title(pub, require_exact_metadata=True)
        video_id = (found or {}).get("id") or ""
        status = youtube.video_status(youtube.Token(db.get_settings()), video_id) if video_id else None
    except (httpx.HTTPError, ValueError) as exc:
        raise PublishError("YouTube's upload outcome could not be checked.",
                           "Check the connection and use Refresh status again; no new upload is started.",
                           "network") from exc
    if not status or not status.get("exists"):
        return _hold_manual_unknown(pub, youtube._outcome_unknown())
    info = {**(pub.get("info") or {}), "outcome_unknown": False, "code": "",
            "studio_url": youtube.studio_url(video_id), "checked_at": time.time(),
            "locked_private": pub.get("requested_privacy") == "public" and status.get("privacy") == "private"}
    delivery = audience.delivery_after_upload("youtube", pub.get("audience") or {},
                                               status.get("privacy") or "", "api")
    db.update_publication(pub["id"], status="done", remote_id=video_id, url=youtube.video_url(video_id),
                          privacy=status.get("privacy") or "", progress=1.0, error="", fix="", info=info,
                          delivery=delivery, message="The upload was found on YouTube; only its final reply was lost.")
    return refresh(db.get_publication(pub["id"]) or pub)


RUNNERS: dict[str, Callable[[dict, Callable[[], bool]], None]] = {"youtube": run_youtube, "tiktok": run_tiktok}


def refresh(pub: dict) -> dict:
    """Ask the platform for the current state of an uploaded video."""
    if pub["platform"] == "youtube" and not pub.get("scheduled_id") and unknown_outcome(pub):
        return _refresh_manual_unknown(pub)
    if pub["platform"] == "youtube" and pub.get("remote_id"):
        st = youtube.video_status(youtube.Token(db.get_settings()), pub["remote_id"])
        info = {**(pub.get("info") or {}), **{k: v for k, v in st.items() if k != "exists"}, "checked_at": time.time()}
        if not st["exists"]:
            db.update_publication(pub["id"], info=info, message="This video no longer exists on YouTube.")
        else:
            delivery = dict(pub.get("delivery") or {})
            delivery["visibility"] = {**(delivery.get("visibility") or {}), "returned": st["privacy"],
                                      "evidence": "api", "checked_at": time.time()}
            msg = pub.get("message", "")
            # only uploads made under the audience policy are held to it; what was posted before is reported as is
            governed = int((pub.get("audience") or {}).get("policy_version") or 0) >= 1
            requested = (pub.get("audience") or {}).get("visibility") or pub.get("requested_privacy") or "private"
            if requested == "private" and st["privacy"] != "private" and governed:
                audience.incident("youtube", f"YouTube reports video {pub['remote_id']} as {st['privacy']}, not "
                                             "Private.", pub["remote_id"])
                msg = (f"YouTube reports this video as {st['privacy'].capitalize()}, not Private. ClipFoundry stopped "
                       "uploading to YouTube until you check it in YouTube Studio.")
            if (pub.get("audience") or {}).get("intent") == audience.PUBLIC:
                delivery["audience_setup"] = "public_api_verified" if st["privacy"] == "public" else \
                    "public_restricted"
                delivery["analytics"] = "awaiting_observations" if st["privacy"] == "public" else \
                    "awaiting_viewer_access"
                info["locked_private"] = st["privacy"] == "private"
                msg = "Public visibility confirmed by YouTube." if st["privacy"] == "public" else \
                    f"YouTube reports {st['privacy'] or 'unknown'} visibility; Public was requested. Check Studio."
            db.update_publication(pub["id"], privacy=st["privacy"], info=info, message=msg, delivery=delivery)
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
            _cancel_publication(pub_id, "Cancelled while waiting. Nothing was published.")

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
            _cancel_publication(pub_id, "Stopped with Stop all jobs")
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
        if not pub or pub["status"] in ("cancelled", "done", "action_needed"):
            return
        if not pub.get("scheduled_id") and pub["platform"] == "youtube" and unknown_outcome(pub):
            try:
                refresh(pub)  # A stale retry/recovered queue entry may only read the uncertain outcome.
            except PublishError as exc:
                db.update_publication(pub_id, message=f"Upload outcome still unknown: {exc}", fix=exc.fix)
            return
        if pub["status"] == "processing" and pub.get("remote_id"):
            try:
                refresh(pub)  # The bytes arrived already; only ask the platform whether processing finished.
            except PublishError as exc:
                db.update_publication(pub_id, message=f"Uploaded; the platform's outcome could not be read: {exc}",
                                      fix=exc.fix)
            return
        if pub_id in self.cancelled:
            _cancel_publication(pub_id, "Cancelled before the upload started.")
            return
        info = pub.get("info") or {}
        if not pub.get("scheduled_id") and db.get_settings().get("autopilot_publishing_paused") \
                and not transfer_started(pub):
            # Submission and upload can be separated by a queue or a platform wait. Recheck the pause at start;
            # transfers already under way keep their existing session and may finish, as scheduled uploads do.
            at = time.time() + 30.0
            db.update_publication(pub_id, status="queued", message="Publishing is paused: waiting for Resume",
                                  info={**info, "retry_at": at})
            self.later(pub_id, at)
            return
        runner = RUNNERS.get(pub["platform"])
        if runner is None:
            db.update_publication(pub_id, status="failed", error=f"Unknown platform {pub['platform']}")
            return
        try:
            runner(pub, lambda: pub_id in self.cancelled)
        except Cancelled:
            _cancel_publication(pub_id, "Upload cancelled. Nothing was published.")
        except PublishError as exc:
            current = db.get_publication(pub_id) or pub
            name = "YouTube" if pub["platform"] == "youtube" else "TikTok"
            if pub["platform"] == "youtube" and not pub.get("scheduled_id") and (
                    exc.code == youtube.OUTCOME_UNKNOWN or
                    (current.get("info") or {}).get("final_chunk_at") and asked_to_wait(exc) is None):
                held = _hold_manual_unknown(current, exc)
                try:
                    refresh(held)
                except PublishError as lookup_error:
                    db.update_publication(pub_id, message=f"Upload outcome still unknown: {lookup_error}",
                                          fix=lookup_error.fix)
                return
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
            current = db.get_publication(pub_id) or pub
            if pub["platform"] == "youtube" and (current.get("info") or {}).get("final_chunk_at"):
                _hold_manual_unknown(current, youtube._outcome_unknown())
            else:
                db.update_publication(pub_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:500])


worker = PublishWorker()

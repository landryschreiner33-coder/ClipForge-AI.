"""Explainable scores (coverage, confidence, missing parts) and specific media-access failures.

Real yt-dlp extraction runs against a fake HTTP transport and fake yt-dlp errors; no internet or accounts.
"""
from __future__ import annotations

import errno
import io
import ipaddress
import time

import httpx
import pytest


# ------------------------------------------------------------------ Trend Score and Source Score
def _signal(**kw) -> dict:
    from clipfoundry.autopilot import trends

    note = kw.pop("note", "")
    metrics = {k: trends.m(kw.pop(k, None), note=note) for k in ("views", "likes", "comments")}
    return {"id": kw.pop("id", "s1"), "platform": kw.pop("platform", "tiktok"), "kind": "video", "raw": {},
            "keywords": kw.pop("keywords", ["jones", "fight"]), "metrics": metrics,
            "published_at": time.time() - 3600 * kw.pop("age_h", 1), **kw}


def test_sparse_data_cannot_rank_high_and_says_what_is_missing():
    """The audit's case: a ten-minute-old web result without any numbers scored 99.7 because only recency and topic
    recurrence were averaged. Missing parts now count as neutral, so it stays near 50 with low confidence, and a
    measured fresh video outranks it."""
    from clipfoundry.autopilot import trends

    now = time.time()
    bare = _signal(id="bare", age_h=10 / 60, note="web search results have no statistics")
    r = trends.score(bare, [], {}, 4, now)
    assert r["confidence"] == "low" and r["coverage"] < 0.5 and r["readings"] == 0
    assert r["score"] <= 50 + 50 * r["coverage"] + 0.1 and r["score"] < 70
    assert set(r["missing"]) == {"velocity", "acceleration", "engagement", "size"}
    assert r["missing"]["size"] == "web search results have no statistics"
    assert not set(r["missing"]) & set(r["components"])  # missing stays missing: never a 0 in the parts
    assert r["evidence"]["missing"] == r["missing"] and any("confidence low" in n for n in r["notes"])

    measured = _signal(id="measured", views=500_000, likes=20_000, comments=2_000, age_h=10)
    hist = [{"at": now - 7200, "views": 300_000}, {"at": now - 3600, "views": 380_000}, {"at": now, "views": 500_000}]
    m = trends.score(measured, hist, {}, 4, now)
    assert m["confidence"] == "high" and m["readings"] == 3 and m["coverage"] == 1.0 and not m["missing"]
    assert m["score"] > r["score"] + 10


def test_measured_zero_is_kept_and_unknown_rank_is_neutral_not_last():
    from clipfoundry.autopilot import trends

    zero = trends.score(_signal(views=0, likes=0, age_h=2), [], {}, 0)
    assert zero["components"]["size"]["value"] == 0.0  # a measured zero is data
    assert zero["missing"]["engagement"] == "0 views so far"  # no rate can be computed from it
    yt = {"id": "y", "platform": "youtube", "kind": "video", "platform_rank": None, "raw": {"list_size": 50},
          "metrics": {}}
    unranked = trends.score(yt, [], {"youtube_derived_metrics_approved": False})
    assert unranked["score"] == 50.0 and unranked["coverage"] == 0.0 and unranked["confidence"] == "low"
    ranked = trends.score({**yt, "platform_rank": 3}, [], {"youtube_derived_metrics_approved": False})
    assert ranked["score"] == pytest.approx(96.0) and ranked["confidence"] == "medium"  # one listing so far


def test_confidence_words_and_spaced_readings():
    from clipfoundry.autopilot import trends

    assert trends.confidence(0.8, 2) == "high"
    assert trends.confidence(0.8, 1) == "medium" and trends.confidence(0.6, 5) == "medium"
    assert trends.confidence(0.4, 5) == "low" and trends.confidence(0.9, 0) == "low"
    assert trends.spaced_readings([0, 60, 600, 1300, 1400, 2600]) == 3  # readings minutes apart count once
    value, coverage = trends.combine({"a": {"value": 1.0}, "b": {"value": None}}, {"a": 0.5, "b": 0.5})
    assert (value, coverage) == (0.75, 0.5)  # 50 + 50 × coverage at most


@pytest.fixture
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def test_stored_scores_keep_coverage_confidence_and_missing_parts(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scout, trends

    now = time.time()
    sig = {"provider": "feed", "platform": "feed", "external_id": "v1", "kind": "video", "title": "Jones fight recap",
           "url": "https://public.example/v1", "keywords": ["jones", "fight"], "published_at": now - 600,
           "metrics": {"views": trends.m(None, note="not reported")}, "raw": {}}
    stored = scout.upsert_signal(sig, now)
    scout.rescore(db.get_settings(), now)
    row = db.fetch("trend_signals", stored["id"])
    ev = row["components"]["evidence"]
    assert ev["confidence"] == "low" and ev["weight"] == 0.0 and "velocity" in ev["missing"]
    assert ev["missing"]["velocity"] == "not reported" and "velocity" not in row["components"]

    src = {"platform": "feed", "external_id": "v1", "kind": "recorded", "category": "Comedy", "duration": 1800,
           "published_at": now - 600}
    sc = scout.score_source(src, row, db.get_settings(), now)
    parts = sc["components"]
    # the sparse trend part counts with its own coverage, so the Source Score cannot claim more evidence than it has
    assert sc["coverage"] < 0.6 and sc["confidence"] == "low" and parts["evidence"]["missing"]["creator"]
    assert "confidence low" in parts["trend"]["note"] and "quality" not in parts["trend"]
    own = scout.score_source({"platform": "local", "external_id": "f", "kind": "recorded"}, None,
                             db.get_settings(), now)
    assert own["score"] == 50.0 and own["confidence"] == "low"  # nothing known before the file is read
    assert set(own["missing"]) >= {"trend", "clip_potential", "creator"} and own["expected"] >= 1


# ------------------------------------------------------------------ specific media-access failures
def _wrapped(inner: Exception):
    """What yt-dlp raises: DownloadError carrying the extractor's error in exc_info."""
    import sys

    from yt_dlp.utils import DownloadError

    try:
        raise inner
    except Exception:  # noqa: BLE001 - capture exc_info exactly like yt-dlp's report_error
        return DownloadError(f"ERROR: {inner}", sys.exc_info())


def _http(status: int, headers: dict | None = None):
    from yt_dlp.networking.common import Response
    from yt_dlp.networking.exceptions import HTTPError

    return HTTPError(Response(io.BytesIO(b""), "https://public.example/watch", headers or {}, status))


def _extractor(message: str, cause=None):
    from yt_dlp.utils import ExtractorError

    return ExtractorError(message, expected=True, cause=cause)


def _geo():
    from yt_dlp.utils import GeoRestrictedError

    return GeoRestrictedError("The uploader has not made this video available in your country.")


def _unsupported():
    from yt_dlp.utils import UnsupportedError

    return UnsupportedError("https://public.example/page")


def _timeout():
    from yt_dlp.networking.exceptions import TransportError

    return TransportError("timed out")


@pytest.mark.parametrize("make, code", [
    (lambda: _extractor("Private video. Sign in if you've been granted access to this video"), "private"),
    (lambda: _extractor("Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies for the "
                        "authentication."), "login_required"),
    (lambda: _extractor("Join this channel to get access to members-only content like this video"), "login_required"),
    (_geo, "geo_blocked"),
    (_unsupported, "unsupported_site"),
    (lambda: _extractor("This video is DRM protected"), "protected"),
    (lambda: _extractor("Video unavailable. This video has been removed by the uploader"), "not_found"),
    (lambda: _extractor("Unable to download webpage: HTTP Error 401", _http(401)), "login_required"),
    (lambda: _extractor("Unable to download webpage: HTTP Error 403", _http(403)), "access_denied"),
    (lambda: _extractor("Unable to download webpage: HTTP Error 404", _http(404)), "not_found"),
    (lambda: _extractor("Unable to download webpage: HTTP Error 503", _http(503)), "network"),
    (_timeout, "network"),
    (lambda: OSError(errno.ENOSPC, "No space left on device"), "disk_space"),
    (lambda: _extractor("Unable to extract video data"), "extraction_failed"),
])
def test_fake_ytdlp_errors_get_a_specific_code(make, code):
    from clipfoundry import media_import

    err = media_import.unavailable(_wrapped(make()))
    assert err.code == code and str(err) == media_import.ACCESS[code][1] and err.fix
    assert err.temporary == (code in ("network", "disk_space"))


def test_rate_limit_keeps_the_wait_the_website_named():
    from clipfoundry import media_import

    err = media_import.unavailable(_wrapped(_extractor("HTTP Error 429", _http(429, {"Retry-After": "120"}))))
    assert (err.code, err.retry_after, err.temporary) == ("rate_limited", 120.0, True)
    plain = media_import.unavailable(_wrapped(_extractor("HTTP Error 429: Too Many Requests", _http(429))))
    assert (plain.code, plain.retry_after) == ("rate_limited", None)


@pytest.fixture
def public_site(monkeypatch, data):
    from clipfoundry import media_import, netguard

    routes, calls = {}, []
    client_class = httpx.Client

    def serve(request):
        calls.append(request)
        status, headers, body = routes.get(request.url.path, (404, {}, b"missing"))
        return httpx.Response(status, headers=headers, content=b"" if request.method == "HEAD" else body)

    monkeypatch.setattr(media_import.httpx, "Client",
                        lambda **kw: client_class(transport=httpx.MockTransport(serve), **kw))
    monkeypatch.setattr(netguard, "resolve", lambda host: [ipaddress.ip_address("8.8.8.8")])
    return routes, calls, data


@pytest.mark.parametrize("status, code", [(401, "login_required"), (403, "access_denied"), (404, "not_found"),
                                          (451, "geo_blocked")])
def test_website_answers_become_specific_reasons(public_site, status, code):
    from clipfoundry import db, jobs, media_import
    from clipfoundry.pipeline.common import JobContext

    routes, _, tmp_path = public_site
    routes["/watch"] = (status, {"Content-Type": "text/html"}, b"<html>no</html>")
    with pytest.raises(media_import.MediaUnavailable) as seen:
        media_import.inspect_video("https://public.example/watch")
    assert seen.value.code == code
    pdir = tmp_path / "project"
    pdir.mkdir()
    project = db.create_project("Imported", source_path=str(pdir / "source.mp4"))
    with pytest.raises(media_import.MediaUnavailable) as seen:
        jobs.download_url(project["id"], "https://public.example/watch", JobContext())
    assert seen.value.code == code and str(seen.value) == media_import.ACCESS[code][1]


@pytest.mark.parametrize("status", [429, 503])
def test_busy_website_is_checked_again_later_not_given_up(public_site, status):
    from clipfoundry import media_import
    from clipfoundry.autopilot import queue

    routes, _, _ = public_site
    routes["/watch"] = (status, {}, b"busy")
    with pytest.raises(queue.Retry) as seen:  # intake checks the link again later
        media_import.inspect_video("https://public.example/watch")
    assert str(seen.value) == media_import.ACCESS["rate_limited" if status == 429 else "network"][1]


def test_page_without_a_video_is_an_unsupported_site(public_site):
    from clipfoundry import media_import

    routes, _, _ = public_site
    routes["/watch"] = (200, {"Content-Type": "text/html"}, b"<html><body><p>Just words.</p></body></html>")
    with pytest.raises(media_import.MediaUnavailable) as seen:
        media_import.inspect_video("https://public.example/watch")
    assert seen.value.code == "unsupported_site"


def test_drm_and_encrypted_streams_are_protected_and_never_fetched(public_site):
    from clipfoundry import media_import

    routes, calls, _ = public_site
    routes["/enc.m3u8"] = (200, {"Content-Type": "application/vnd.apple.mpegurl"},
                           b"#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"/key\"\n#EXTINF:1,\n/seg0.ts\n#EXT-X-ENDLIST\n")
    with media_import.public_extractor() as ydl:
        with pytest.raises(media_import.MediaUnavailable) as drm:
            ydl.dl("x.mp4", {"url": "https://public.example/movie.mp4", "protocol": "https", "ext": "mp4",
                             "has_drm": True})
        with pytest.raises(media_import.MediaUnavailable) as encrypted:
            ydl.dl("x.mp4", {"url": "https://public.example/enc.m3u8", "protocol": "m3u8_native", "ext": "mp4"})
    assert drm.value.code == encrypted.value.code == "protected"
    assert not any(r.url.path in ("/movie.mp4", "/key", "/seg0.ts") for r in calls)


def _candidate(external_id: str, score: float, **kw) -> dict:
    from clipfoundry import db

    return db.insert("sources", {"platform": "url", "external_id": external_id, "kind": "recorded",
                                 "url": f"https://public.example/{external_id}", "title": f"Podcast {external_id}",
                                 "channel_title": "Some creator", "topic": "podcast", "category": "Comedy",
                                 "signal_id": f"sig-{external_id}", "published_at": time.time() - 3600,
                                 "metrics": {"views": {"value": 1200, "status": "observed"}}, "duration": 1800,
                                 "expected_clips": 3, "source_score": score, "status": "eligible", **kw})


def _hunt(source_id: str):
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    claimed = queue.claim("clip_hunter", "test")
    assert claimed["ref_id"] == source_id
    return host.HANDLERS["hunt_source"](host.Job(claimed, "test"))


def test_inaccessible_candidate_keeps_discovery_info_and_autopilot_picks_another(public_site):
    from clipfoundry import db, media_import
    from clipfoundry.autopilot import access, home, queue, rights, scout

    routes, _, _ = public_site
    routes["/locked"] = (401, {"Content-Type": "text/html"}, b"<html>sign in</html>")
    db.save_settings({"autopilot_sources_per_day": 1})
    settings = db.get_settings()
    locked = rights.apply(_candidate("locked", 90), settings)
    other = rights.apply(_candidate("other", 60), settings)
    assert [s["id"] for s in scout.select_for_today(settings)] == [locked["id"]]
    with pytest.raises(queue.Fail) as failed:
        _hunt(locked["id"])
    assert "Autopilot goes on with other videos" in failed.value.fix
    row = db.fetch("sources", locked["id"])
    assert row["status"] == "failed"
    got = row["access"]
    assert (got["ok"], got["state"], got["reason"]) == (False, access.UNAVAILABLE, "login_required")
    assert got["method"] == "webpage" and got["fix"] == media_import.ACCESS["login_required"][2]
    # everything discovery found is still there, and nothing about the reuse rights changed
    for key in ("title", "url", "channel_title", "topic", "signal_id", "published_at", "metrics", "source_score",
                "rights_status"):
        assert row[key] == locked[key], key
    why = next(a for a in home.activity() if a["id"] == locked["id"])
    assert why["why"].startswith("Could not get the video file: The website only shares this video with signed-in")
    assert "add the file in Clips → Add video" in why["why"] and why["access"] == "Sign-in required"
    # the failed video freed its turn: the next one is picked, the failed one is not tried again
    picked = scout.select_for_today(db.get_settings())
    assert [s["id"] for s in picked] == [other["id"]]
    assert db.fetch("sources", other["id"])["status"] == "queued"


def test_rate_limit_waits_exactly_as_asked_and_disk_space_waits_for_room(public_site, monkeypatch):
    import shutil

    from clipfoundry import db
    from clipfoundry.autopilot import queue, rights, scout, state

    routes, _, _ = public_site
    routes["/slow"] = (429, {"Retry-After": "7200"}, b"")
    settings = db.get_settings()
    slow = rights.apply(_candidate("slow", 90), settings)
    scout.select_for_today(settings)
    with pytest.raises(queue.Wait) as waited:
        _hunt(slow["id"])
    assert waited.value.seconds == 7200  # never shortened
    assert db.fetch("sources", slow["id"])["status"] == "queued"

    routes["/busy"] = (429, {}, b"")
    busy = rights.apply(_candidate("busy", 80), settings)
    db.update("worker_jobs", next(j["id"] for j in queue.jobs() if j["ref_id"] == slow["id"]), status="canceled")
    scout.select_for_today(db.get_settings())
    with pytest.raises(queue.Retry):  # no wait named: the usual retries, then another video
        _hunt(busy["id"])
    row = db.fetch("sources", busy["id"])
    assert row["access"]["reason"] == "rate_limited" and row["access"]["temporary"]
    assert row["status"] != "failed" and row["status_note"].startswith("Retrying after:")

    routes["/full"] = (200, {"Content-Type": "text/html"},
                       b'<html><head><title>Talk</title></head><body><video src="/full.mp4"></video></body></html>')
    routes["/full.mp4"] = (200, {"Content-Type": "video/mp4"}, b"public video")
    full = rights.apply(_candidate("full", 70), settings)
    db.update("worker_jobs", next(j["id"] for j in queue.jobs() if j["ref_id"] == busy["id"]), status="canceled")
    scout.select_for_today(db.get_settings())
    real = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda p: real(p)._replace(free=1_000_000))
    with pytest.raises(queue.Wait) as room:
        _hunt(full["id"])
    assert room.value.reason == "disk" and "disk:space" in {a["key"] for a in state.open_actions()}
    assert db.fetch("sources", full["id"])["access"]["reason"] == "disk_space"

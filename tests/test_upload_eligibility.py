"""Publishing-focused discovery uses real metadata and records, never a public-link or prose permission guess."""
from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import pytest

from fake_platforms import FakeGoogle


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_tiktok": False,
                      "autopilot_discovery_uploadable_only": True, "audience_youtube": "public",
                      "audience_youtube_confirmed_at": 1.0, "audience_youtube_group_version": 1,
                      "autopilot_auto_schedule": True, "autopilot_auto_publish": True,
                      "autopilot_active_start": 0, "autopilot_active_end": 24})
    return tmp_path


@pytest.fixture
def google(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import youtube

    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    fake = FakeGoogle()
    monkeypatch.setattr(youtube, "API_URL", f"{fake.url}/youtube/v3")
    db.save_settings({"youtube_api_key": fake.api_key, "trend_topics": "podcast"})
    requests = []
    original = fake.handle

    def handle(handler, method, body):
        url = urlparse(handler.path)
        params = parse_qs(url.query)
        # No keys, tokens or raw request data in the test's observable record.
        requests.append((url.path, params.get("videoLicense"), params.get("chart")))
        return original(handler, method, body)

    monkeypatch.setattr(fake, "handle", handle)
    yield fake, requests
    fake.stop()


def public_source(**changes):
    return {"platform": "youtube", "external_id": "abc12345678", "channel_id": "UCcreator000000001",
            "url": "https://www.youtube.com/watch?v=abc12345678", "title": "Podcast useful interview",
            "status": "eligible", "signal_id": "synthetic-signal", **changes}


def preview(signal):
    from clipfoundry.autopilot import scout

    return scout._preview_source({**signal, "id": "synthetic-signal"})


def test_public_coverage_is_required_even_when_local_processing_is_allowed(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    settings = db.get_settings()
    source = public_source()
    assert rights.local_allowed(source, settings=settings)
    assert not rights.discovery_publishable(source, settings)
    # Explicit input still works locally and remains subject to the publishing rights gate.
    assert rights.local_allowed({**source, "user_added": True}, settings=settings)
    with pytest.raises(rights.RightsBlocked):
        rights.gate(source, "schedule", settings)
    with pytest.raises(rights.RightsBlocked):
        rights.gate(source, "publish", settings)


def test_owned_channel_requires_platform_confirmation_and_blocks_still_win(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, verify

    source = public_source()
    db.save_account("youtube", tokens={"access_token": "synthetic-only"}, account_id=source["channel_id"])
    assert not rights.discovery_publishable(source, db.get_settings())
    source["channel_check"] = verify.judge(source, source["channel_id"], "Creator", verify.YOUTUBE_DATA)
    assert rights.discovery_publishable(source, db.get_settings())
    rights.add_rule("channel", source["channel_id"], rights.BLOCKED, "Excluded footage", platform="youtube")
    assert not rights.discovery_publishable(source, db.get_settings())


def test_agreement_for_another_platform_does_not_fill_youtube_work_queue(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, verify

    source = public_source()
    source["channel_check"] = verify.judge(source, source["channel_id"], "Creator", verify.YOUTUBE_DATA)
    db.save_account("youtube", tokens={"access_token": "synthetic-only"}, account_id="different-channel")
    rights.add_agreement("Creator", [source["channel_id"]], "Existing signed agreement",
                         platforms=["tiktok"])
    assert not rights.discovery_publishable(source, db.get_settings())
    assert rights.discovery_publishable(source, db.get_settings(), platforms={"tiktok"})


def test_youtube_search_requests_cc_but_actual_license_still_controls_admission(google):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, rights

    fake, requests = google
    fake.add_video("abc12345678", "Podcast useful interview", license_="youtube")
    fake.add_video("def12345678", "Podcast clear answer", license_="creativeCommon")
    found = providers.YouTubeDiscovery(db.get_settings()).discover(["podcast"], [], False)
    assert any(path.endswith("/search") and license_ == ["creativeCommon"] for path, license_, _ in requests)
    assert not any(chart == ["mostPopular"] for _, _, chart in requests)
    usable = [signal["external_id"] for signal in found if rights.discovery_publishable(preview(signal),
                                                                                    db.get_settings())]
    assert usable == ["def12345678"]  # The fake intentionally ignores the search filter.


def test_creator_uploads_survive_exhausted_broad_search_quota(google):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, rights

    fake, requests = google
    creator = "UCcreator000000001"
    fake.add_video("abc12345678", "Podcast useful interview", channel=creator)
    fake.search_quota_exceeded = True
    db.save_account("youtube", tokens={"access_token": "synthetic-only"}, account_id=creator)
    provider = providers.YouTubeDiscovery(db.get_settings())
    found = provider.discover(["podcast"], [{"channel_id": creator, "name": "Your channel"}], False)
    paths = [request[0] for request in requests]
    assert paths.index("/youtube/v3/playlistItems") < paths.index("/youtube/v3/search")
    assert provider.errors and [signal["external_id"] for signal in found] == ["abc12345678"]
    assert found[0]["raw"]["curated_channel"] and rights.discovery_publishable(preview(found[0]), db.get_settings())


def test_reusable_web_search_verifies_page_license_claim_with_actual_platform_metadata(google, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, rights

    fake, _ = google
    fake.add_video("abc12345678", "Podcast useful interview", license_="youtube")
    fake.add_video("def12345678", "Podcast clear answer", license_="creativeCommon")
    web = providers.WebSearch({**db.get_settings(), "tavily_api_key": "synthetic-only"})
    calls = []

    def search(query, domains, max_results, time_range):
        calls.append(domains)
        return [{"title": "This page claims CC BY", "url": "https://youtu.be/abc12345678"},
                {"title": "Another page", "url": "https://youtu.be/def12345678"}]

    monkeypatch.setattr(web, "search", search)
    found = web.discover(["podcast"], providers.YouTubeDiscovery(db.get_settings()))
    assert calls == [["youtube.com"]]
    usable = [signal["external_id"] for signal in found if rights.discovery_publishable(preview(signal),
                                                                                    db.get_settings())]
    assert usable == ["def12345678"]


def test_reusable_web_search_does_not_spend_on_unverifiable_results(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import providers

    web = providers.WebSearch({**db.get_settings(), "tavily_api_key": "synthetic-only"})

    def unexpected(*args, **kwargs):
        pytest.fail("No web credits should be spent without metadata verification")

    monkeypatch.setattr(web, "search", unexpected)
    assert web.discover(["podcast"], None) == []
    assert "waits for YouTube metadata" in web.stopped


def _posting_source(data, *, restricted=False):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, rights, verify

    db.save_account("youtube", tokens={"access_token": "synthetic-only"}, account_id="different-channel")
    autopublish.enable("youtube", "public", False, 0, 0, 24, True)
    source = db.insert("sources", public_source(status="analyzed"))
    if restricted:
        db.update("sources", source["id"], channel_check=verify.judge(source, source["channel_id"], "Creator",
                                                                    verify.YOUTUBE_DATA))
        rights.add_agreement("Creator", [source["channel_id"]], "Existing signed agreement", platforms=["tiktok"])
    project = db.create_project("Synthetic local clip", origin="autopilot", source_id=source["id"], status="ready")
    output = data / "finished.mp4"
    output.write_bytes(b"synthetic bytes; no media gate is invoked by the read-only explanation")
    db.create_clip(project["id"], start=0, end=20, duration=20, status="ready", output_path=str(output))


@pytest.mark.parametrize("restricted", [False, True])
def test_posting_explains_recorded_permissions_and_specific_source_choices_without_mutation(data, restricted):
    from clipfoundry import db
    from clipfoundry.autopilot import readiness

    _posting_source(data, restricted=restricted)
    with db.connect() as conn:
        before = list(conn.iterdump())
    result = readiness.view(db.get_settings(), {"youtube": {"connected": True}}, True)
    shown = result["platforms"][0]
    assert shown["code"] == "rights" and shown["counts"]["local_only"] == 1
    assert shown["counts"]["other_platform"] == int(restricted)
    expected = "only for another destination" if restricted else "being public does not grant permission"
    assert expected in shown["detail"]
    guidance = result["source_guidance"]
    assert guidance["uploadable_only"] and len(guidance["options"]) == 3
    assert all(option["link"] == "#/missions/sources" for option in guidance["options"])
    with db.connect() as conn:
        assert list(conn.iterdump()) == before


def test_zero_daily_limit_means_no_app_cap_in_readiness(data):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, readiness

    db.save_account("youtube", tokens={"access_token": "synthetic-only"}, account_id="synthetic-channel")
    autopublish.enable("youtube", "public", False, 0, 0, 24, True)
    db.save_settings({"autopilot_youtube_daily_limit": 0})
    result = readiness.view(db.get_settings(), {"youtube": {"connected": True}}, True)
    assert result["platforms"][0]["code"] == "rendering"


def test_empty_source_message_explains_uploadable_search_and_local_only_clips(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    state.put("trend:last_scan", time.time())
    db.insert("sources", public_source(status="needs_rights"))
    message = home.empty_message(db.get_settings(), True, [])
    assert "posting permission and usable originals" in message
    assert "recorded creator agreements and free-license media" in message
    assert "without coverage stay local" in message

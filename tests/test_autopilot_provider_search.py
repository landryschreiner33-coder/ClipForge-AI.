"""Official YouTube discovery requests, with a transport that honors the requested filters."""
from __future__ import annotations

import datetime as dt
import time

import httpx
import pytest


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from clipfoundry import db
    from clipfoundry.autopilot import providers

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"youtube_api_key": "test-api-key"})
    catalog, popular, requests = {}, [], []
    failures = {}

    def respond(request):
        params = {k: v for k, v in request.url.params.items() if k != "key"}
        requests.append({"path": request.url.path, "params": params})
        if request.url.path.endswith("/search"):
            if params.get("videoDuration") in failures:
                return failures[params["videoDuration"]]
            live = params.get("eventType") == "live"
            after = providers.iso_time(params.get("publishedAfter"))
            hits = []
            for item in catalog.values():
                sn = item["snippet"]
                if (sn["liveBroadcastContent"] == "live") != live:
                    continue
                if any(word not in sn["title"].lower() for word in params.get("q", "").lower().split()):
                    continue
                if after and providers.iso_time(sn["publishedAt"]) < after:
                    continue
                duration = providers.iso_duration(item["contentDetails"]["duration"])
                if params.get("videoDuration") == "long" and duration <= 1200:
                    continue
                if params.get("videoDuration") == "medium" and not 240 <= duration <= 1200:
                    continue
                hits.append(item)
            hits.sort(key=lambda item: -int(item["statistics"].get("viewCount", 0)))
            hits = hits[:int(params["maxResults"])]
            return httpx.Response(200, json={"items": [{"id": {"videoId": item["id"]}} for item in hits]})
        if params.get("chart") == "mostPopular":
            return httpx.Response(200, json={"items": [catalog[vid] for vid in popular]})
        return httpx.Response(200, json={"items": [catalog[vid] for vid in params["id"].split(",")
                                                  if vid in catalog]})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(providers, "client", lambda timeout: httpx.Client(transport=transport))
    return catalog, popular, requests, failures


def video(vid: str, title: str, duration: str = "PT30M", views: int = 1000, age_hours: float = 4,
          description: str = "", live: bool = False) -> dict:
    published = dt.datetime.fromtimestamp(time.time() - age_hours * 3600, dt.timezone.utc)
    return {"id": vid, "snippet": {"title": title, "channelId": "UCcreator", "channelTitle": "Creator",
                                    "categoryId": "22", "publishedAt": published.isoformat(),
                                    "description": description, "liveBroadcastContent": "live" if live else "none"},
            "statistics": {"viewCount": str(views)}, "contentDetails": {"duration": duration},
            "status": {"privacyStatus": "public", "license": "youtube"}}


def test_empty_topics_find_recent_long_and_medium_videos_without_short_result_crowding(api, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, quota

    catalog, _, requests, _ = api
    monkeypatch.setattr(providers.time, "time", lambda now=time.time(): now)
    for item in [video("long0000001", "A recent interview", views=2000),
                 video("long0000002", "A recent commentary", views=1000),
                 video("medium00001", "A recent discussion", duration="PT10M"),
                 video("short000001", "A very popular Short", duration="PT40S", views=10_000_000),
                 video("old00000001", "An old recording", age_hours=80, views=20_000_000)]:
        catalog[item["id"]] = item
    discovery = providers.YouTubeDiscovery(db.get_settings())
    signals = discovery.discover([], [], False)
    assert [signal["external_id"] for signal in signals] == ["long0000001", "long0000002", "medium00001"]
    searches = [request["params"] for request in requests if request["path"].endswith("/search")]
    assert len(searches) == 2 and {search["videoDuration"] for search in searches} == {"long", "medium"}
    for search in searches:
        assert "q" not in search and search["order"] == "viewCount" and search["maxResults"] == "25"
        assert search["regionCode"] == "US" and search["relevanceLanguage"] == "en"
        assert providers.iso_time(search["publishedAfter"]) == pytest.approx(time.time() - 72 * 3600, abs=1)
    assert [signal["platform_rank"] for signal in signals] == [1, 2, 1]
    assert [signal["raw"]["list_size"] for signal in signals] == [2, 2, 1]
    metric = signals[0]["metrics"]["views"]
    assert metric["value"] == 2000 and metric["status"] == "observed" and metric["source"] == providers.YOUTUBE_DATA
    assert signals[0]["metrics"]["likes"]["value"] is None
    # A repeat pass reuses the actual quota cache, including the two separate duration queries.
    discovery.discover([], [], False)
    assert len(requests) == 4 and discovery.cache_hits == 4
    assert quota.usage()["search"]["calls"] == 2


def test_topic_candidates_request_long_videos_and_leave_live_search_unfiltered(api):
    from clipfoundry import db
    from clipfoundry.autopilot import providers

    catalog, _, requests, _ = api
    for item in [video("long0000001", "Podcast interview"),
                 video("short000001", "Podcast clip", duration="PT50S", views=10_000_000),
                 video("live0000001", "Live interview", duration="P0D", live=True)]:
        catalog[item["id"]] = item
    signals = providers.YouTubeDiscovery(db.get_settings()).discover(["podcast"], [], True)
    assert {signal["external_id"] for signal in signals} == {"long0000001", "live0000001"}
    searches = [request["params"] for request in requests if request["path"].endswith("/search")]
    assert searches[0]["q"] == "podcast" and searches[0]["videoDuration"] == "long"
    assert searches[1]["eventType"] == "live"
    assert "videoDuration" not in searches[1] and "publishedAfter" not in searches[1]


def test_empty_topic_search_stops_at_its_quota_and_keeps_completed_results(api):
    from clipfoundry import db
    from clipfoundry.autopilot import providers

    catalog, _, requests, _ = api
    catalog["long0000001"] = video("long0000001", "A recent interview")
    settings = {**db.get_settings(), "youtube_quota_search": 1, "youtube_search_discovery_share": 100}
    discovery = providers.YouTubeDiscovery(settings)
    signals = discovery.discover([], [], True)
    assert [signal["external_id"] for signal in signals] == ["long0000001"]
    assert len([request for request in requests if request["path"].endswith("/search")]) == 1
    assert len(discovery.denied) == 1 and not discovery.errors


def test_second_search_platform_error_keeps_the_first_search_and_chart(api):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, quota

    catalog, popular, requests, failures = api
    catalog["chart000001"] = video("chart000001", "Popular recording")
    catalog["long0000001"] = video("long0000001", "Recent interview")
    popular.append("chart000001")
    failures["medium"] = httpx.Response(403, json={"error": {"message": "quota", "errors": [
        {"reason": "quotaExceeded"}]}})
    discovery = providers.YouTubeDiscovery(db.get_settings())
    signals = discovery.discover([], [], True)
    assert {signal["external_id"] for signal in signals} == {"chart000001", "long0000001"}
    assert len([request for request in requests if request["path"].endswith("/search")]) == 2
    assert discovery.errors[0].code == "quotaExceeded" and quota.exhausted("search")


@pytest.mark.parametrize("duration, follows_original", [("PT3M59S", True), ("PT4M", False)])
def test_original_links_cover_every_video_below_the_source_minimum(api, duration, follows_original):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, scout

    catalog, popular, _, _ = api
    assert providers.SHORT_SECONDS == scout.MIN_SOURCE_SECONDS
    catalog["clip0000001"] = video("clip0000001", "A popular short clip", duration=duration,
                                   description="Full video: https://youtu.be/orig0000001")
    catalog["orig0000001"] = video("orig0000001", "The full interview")
    popular.append("clip0000001")
    signals = providers.YouTubeDiscovery(db.get_settings()).discover(["podcast"], [], False)
    originals = [signal for signal in signals if signal["provider"] == "youtube_original"]
    assert bool(originals) == follows_original
    if originals:
        assert originals[0]["external_id"] == "orig0000001"
        assert originals[0]["raw"]["found_from"].endswith("clip0000001")

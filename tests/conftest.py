import os
import tempfile

# Keep test runs away from the user's real data folder.
os.environ.setdefault("CLIPFOUNDRY_DATA", tempfile.mkdtemp(prefix="clipfoundry-test-"))
# The app starts no autopilot worker process in tests; autopilot tests run a worker host in threads themselves.
os.environ.setdefault("CLIPFOUNDRY_WORKERS", "off")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_discovery_services(monkeypatch):
    """Tests never reach Wikimedia Commons, Tavily or TikTok's embed API: their addresses point at a closed local
    port, unless a test points them at a stand-in (tests/fake_platforms.py)."""
    from clipfoundry.autopilot import providers
    from clipfoundry.autopilot import search_connections
    from clipfoundry.publish import tiktok

    monkeypatch.setattr(providers, "COMMONS_API", "http://127.0.0.1:9/w/api.php")
    monkeypatch.setattr(providers, "TAVILY_URL", "http://127.0.0.1:9/search")
    monkeypatch.setattr(search_connections, "TAVILY_USAGE_URL", "http://127.0.0.1:9/usage")
    monkeypatch.setattr(tiktok, "OEMBED_URL", "http://127.0.0.1:9/oembed")


@pytest.fixture(autouse=True)
def _no_voice_model_download(monkeypatch):
    """Tests never download the sound cleanup model: its address points at a closed local port, so cleanup uses its
    built-in noise gate unless a test installs the model itself (tests/test_clean_sound.py)."""
    from clipfoundry.pipeline import cleanup

    monkeypatch.setattr(cleanup, "MODEL_URL", "http://127.0.0.1:9/{file}")
    monkeypatch.setattr(cleanup, "_failed_at", 0.0)
    monkeypatch.setattr(cleanup, "_denoiser", None)


@pytest.fixture(autouse=True)
def _no_meaning_model_download(monkeypatch):
    """Tests never download the meaning model (clipfoundry/embedder.py): its address points at a closed local port, so
    the word-based vectors are used unless a test installs a model itself (tests/test_meaning_model.py)."""
    from clipfoundry import embedder

    monkeypatch.setattr(embedder, "hub_url", lambda name: f"http://127.0.0.1:9/{name}")
    embedder.reset_for_tests()
    yield
    embedder.reset_for_tests()


@pytest.fixture(autouse=True)
def _own_videos_folder(monkeypatch, tmp_path):
    """Autopilot's videos folder lives in the user's Videos folder: tests use one of their own instead."""
    monkeypatch.setenv("CLIPFOUNDRY_VIDEOS", str(tmp_path / "videos folder"))


@pytest.fixture(autouse=True)
def _audience_confirmed(monkeypatch):
    """Most tests are about something other than choosing who watches: they start with both destinations confirmed
    (the owner's step in Settings → Integrations). tests/test_audience.py covers the unconfirmed case."""
    from clipfoundry import config

    monkeypatch.setitem(config.DEFAULT_SETTINGS, "audience_youtube_confirmed_at", 1.0)
    monkeypatch.setitem(config.DEFAULT_SETTINGS, "audience_tiktok_confirmed_at", 1.0)


@pytest.fixture(autouse=True)
def _legacy_automatic_publishing_contract(monkeypatch, request):
    """Existing suites exercise the explicitly enabled automatic-publishing contract.

    New ``test_review_*`` suites keep the production default so they verify local planning and owner review.
    Existing byte, reuse, approval, audience, recovery and platform-wait assertions remain in force.
    """
    if request.module.__name__.split(".")[-1].startswith("test_review_"):
        return
    from clipfoundry import config

    monkeypatch.setitem(config.DEFAULT_SETTINGS, "autopilot_review_before_publish", False)


# Suites that test the product as it ships: automatic source discovery is retired (config.DISCOVERY_RETIRED).
PRODUCT_DEFAULT_SUITES = ("test_review_submitted_", "test_studio_", "test_discovery_retired", "test_clipforge_",
                          "test_media_library", "test_reference_", "test_editor_", "test_submitted_")


@pytest.fixture(autouse=True)
def _historical_discovery_contract(monkeypatch, request):
    """Dormant-engine coverage. Automatic source discovery is retired in the product: no setting, migration, screen
    or restart can turn it on (tests/test_discovery_retired.py). Its code is still in the source, so the earlier
    suites keep exercising it (queue, retry, deduplication, recovery and publishing paths it shares with submitted
    videos) with the retirement switched off for that test only. Delete these suites together with the engine code;
    see docs/clipforge/STUDIO_UPGRADE_MATRIX.md (CF2-16)."""
    if request.module.__name__.split(".")[-1].startswith(PRODUCT_DEFAULT_SUITES):
        return
    from clipfoundry import config

    monkeypatch.setattr(config, "DISCOVERY_RETIRED", False)
    monkeypatch.setitem(config.DEFAULT_SETTINGS, "autopilot_input_mode", "discovery")

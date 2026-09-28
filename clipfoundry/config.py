"""Paths, defaults and persisted user settings."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

APP_NAME = "ClipFoundry"

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent
ASSETS_DIR = PACKAGE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
YUNET_MODEL = ASSETS_DIR / "models" / "face_detection_yunet_2023mar.onnx"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
TRANSCRIPT_EXTENSIONS = {".srt", ".vtt", ".json"}

OUTPUT_W, OUTPUT_H = 1080, 1920

CAPTION_STYLES = ["clean", "bold", "high_energy", "minimal"]
TRACKING_MODES = ["auto", "center", "face", "speaker", "screen", "manual"]
LAYOUTS = ["fill", "fit"]
SILENCE_MODES = ["off", "light", "aggressive"]
AI_PROVIDERS = ["heuristic", "ollama", "openai_compatible", "anthropic"]
CLIP_COUNTS = [3, 5, 10]


def data_dir() -> Path:
    d = Path(os.environ.get("CLIPFOUNDRY_DATA") or (ROOT_DIR / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def projects_dir() -> Path:
    d = data_dir() / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    d = data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "clipfoundry.db"


# Every persisted setting must have a default here; the type of the default is
# used to coerce incoming values from the UI.
DEFAULT_SETTINGS: dict[str, Any] = {
    # Transcription (faster-whisper)
    "whisper_model": "auto",          # auto | tiny | base | small | medium | large-v3 | large-v3-turbo ...
    "whisper_device": "auto",         # auto | cuda | cpu
    "whisper_compute_type": "auto",   # auto | float16 | int8_float16 | int8 | float32
    "whisper_beam_size": 0,           # 0 = auto (5 on GPU, 1 on CPU)
    "language": "",                   # "" = auto-detect
    # Clip discovery
    "clip_count": 5,
    "min_duration": 15.0,
    "max_duration": 60.0,
    "target_duration": 30.0,
    "min_score": 50.0,                # clips below this AI estimate are dropped (best one is always kept)
    # Stage 2 AI evaluation (all optional; heuristic works fully offline)
    "ai_provider": "heuristic",
    "ai_max_candidates": 12,
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.1:8b",
    "openai_url": "http://localhost:1234/v1",
    "openai_model": "",
    "openai_api_key": "",
    "anthropic_api_key": "",
    "anthropic_model": "claude-opus-5",
    # Rendering defaults (per-clip overrides live in the clip's edit params)
    "caption_style": "bold",
    "caption_position": "bottom",      # bottom | middle | top
    "highlight_words": True,
    "tracking": "auto",
    "layout": "fill",
    "silence": "light",
    "remove_fillers": True,           # with silence cleanup: an "um"/"uh" goes together with the pause around it
    "auto_zoom": True,                # subtle push-ins on sentences with an emphasized word
    "caption_emphasis": False,        # key words in their own color
    "hook_overlay": True,
    "hook_seconds": 3.0,
    "normalize_audio": True,
    "encoder": "auto",                # auto | nvenc | x264
    "crf": 20,
    "x264_preset": "veryfast",
    "max_fps": 30,
    "ffmpeg_path": "",                # optional explicit path to ffmpeg(.exe) or its folder
    # Publishing (official APIs, your own developer apps; OAuth tokens are stored separately)
    "youtube_client_id": "",
    "youtube_client_secret": "",
    "youtube_project_verified": False,  # True once Google's YouTube API audit lifted the private-only restriction
    "youtube_category_id": "22",        # People & Blogs
    "tiktok_client_key": "",
    "tiktok_client_secret": "",
    "tiktok_app_audited": False,        # True once TikTok's audit lifted the private-only (SELF_ONLY) restriction
    "tiktok_direct_post": True,         # request video.publish (Direct Post) when connecting
    "tiktok_read_stats": True,          # request video.list (views, likes... of your own videos) when connecting
    # Autopilot (docs/AUTOPILOT.md). Off until turned on; every post still needs the user's approval (platform rules).
    "autopilot_enabled": False,
    "autopilot_process": "separate",    # separate: workers run in their own process | in_app: threads in the app
    "autopilot_daily_target": 15,       # a target, never a quota: quality, rights and platform limits come first
    "autopilot_sources_per_day": 3,
    "autopilot_clips_per_source": 5,
    "autopilot_min_quality": 60.0,      # minimum Viral Potential for autopilot clips
    "autopilot_youtube": True,
    "autopilot_tiktok": True,
    "autopilot_auto_schedule": True,
    "autopilot_auto_publish": True,     # publish approved posts at their scheduled time without another click
    "autopilot_dynamic_replacement": True,
    "autopilot_replacement_threshold": 15.0,  # % better than the weakest future item before it is replaced
    "autopilot_live_monitoring": False,
    "autopilot_learning": True,
    "autopilot_timezone": "America/Chicago",
    "autopilot_active_start": 9,        # local hour, inclusive
    "autopilot_active_end": 23,         # local hour, exclusive
    "autopilot_min_gap_minutes": 45,
    "autopilot_youtube_daily_limit": 15,
    "autopilot_tiktok_daily_limit": 15,
    "autopilot_youtube_privacy": "public",  # suggested visibility; you confirm it when approving
    "autopilot_upload_lead_minutes": 30,    # YouTube: upload this early and let YouTube publish at the planned time
    "autopilot_allow_republish": False,
    # Discovery (Trend Scout / Source Scout)
    "trend_region": "US",
    "trend_language": "en",
    "trend_topics": ("podcast, interview, UFC, boxing, NBA, NFL, soccer, gaming, esports, stand-up comedy, "
                     "commentary, news, live stream, science, business, education"),
    "trend_poll_minutes": 60,
    "trend_max_age_hours": 72,
    "youtube_api_key": "",              # optional: discovery without a connected account (uses the same quota)
    "youtube_derived_metrics_approved": False,  # Google granted this project the derived-metrics exception
    # Rights: which statuses allow automatic clipping (OWNED always does; BLOCKED never)
    "rights_auto_licensed": True,
    "rights_auto_allowlisted": True,
    "rights_auto_creative_commons": False,
    "rights_allow_remote_download": False,  # download platform-hosted sources with the URL importer
    # YouTube Data API quota of your Google Cloud project (per day, resets at midnight Pacific Time)
    "youtube_quota_default": 10000,     # units for everything except uploads and searches
    "youtube_quota_uploads": 100,       # videos.insert calls
    "youtube_quota_search": 100,        # search.list calls
    "youtube_discovery_share": 40,      # % of the default bucket that discovery may use
    "youtube_search_discovery_share": 90,  # % of the search bucket that discovery may use
    # GPU resource manager
    "gpu_min_free_vram_mb": 1200,       # autopilot waits for this much free GPU memory before heavy GPU work
    "gpu_wait_minutes": 20,
}

SECRET_KEYS = {"openai_api_key", "anthropic_api_key", "youtube_client_secret", "tiktok_client_secret",
               "youtube_api_key"}
SEALED_KEYS = {"youtube_client_secret", "tiktok_client_secret", "youtube_api_key"}  # encrypted at rest (secure.py)
AUTOPILOT_PROCESS = ["separate", "in_app"]
YOUTUBE_PRIVACY = ["public", "unlisted", "private"]


def coerce_setting(key: str, value: Any) -> Any:
    default = DEFAULT_SETTINGS[key]
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(default, int):
        return int(float(value))
    if isinstance(default, float):
        return float(value)
    return "" if value is None else str(value).strip()


def validate_settings(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key not in DEFAULT_SETTINGS:
            continue
        v = coerce_setting(key, value)
        if key == "clip_count":
            v = max(1, min(20, v))
        elif key in {"min_duration", "max_duration", "target_duration"}:
            v = max(5.0, min(180.0, v))
        elif key == "caption_style" and v not in CAPTION_STYLES:
            continue
        elif key == "tracking" and v not in TRACKING_MODES:
            continue
        elif key == "layout" and v not in LAYOUTS:
            continue
        elif key == "silence" and v not in SILENCE_MODES:
            continue
        elif key == "ai_provider" and v not in AI_PROVIDERS:
            continue
        elif key == "crf":
            v = max(10, min(35, v))
        elif key == "max_fps":
            v = max(15, min(60, v))
        elif key in _RANGES:
            lo, hi = _RANGES[key]
            v = type(v)(max(lo, min(hi, v)))
        elif key == "autopilot_process" and v not in AUTOPILOT_PROCESS:
            continue
        elif key == "autopilot_youtube_privacy" and v not in YOUTUBE_PRIVACY:
            continue
        elif key == "autopilot_timezone" and not valid_timezone(v):
            continue
        elif key == "trend_region":
            v = v.upper()[:2]
        out[key] = v
    return out


_RANGES: dict[str, tuple[float, float]] = {
    "autopilot_daily_target": (1, 100), "autopilot_sources_per_day": (1, 30), "autopilot_clips_per_source": (1, 10),
    "autopilot_min_quality": (0.0, 100.0), "autopilot_replacement_threshold": (0.0, 500.0),
    "autopilot_active_start": (0, 23), "autopilot_active_end": (1, 24), "autopilot_min_gap_minutes": (0, 1440),
    "autopilot_youtube_daily_limit": (0, 100), "autopilot_tiktok_daily_limit": (0, 100),
    "autopilot_upload_lead_minutes": (5, 720), "trend_poll_minutes": (15, 1440), "trend_max_age_hours": (6, 720),
    "youtube_quota_default": (0, 10_000_000), "youtube_quota_uploads": (0, 100_000),
    "youtube_quota_search": (0, 100_000), "youtube_discovery_share": (0, 90),
    "youtube_search_discovery_share": (0, 100), "gpu_min_free_vram_mb": (0, 48_000), "gpu_wait_minutes": (1, 720),
}


def valid_timezone(name: str) -> bool:
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(name)
        return True
    except Exception:  # noqa: BLE001 - unknown zone, or no time zone database (Windows: pip install tzdata)
        return False

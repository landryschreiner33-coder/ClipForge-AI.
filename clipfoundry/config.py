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
    "auto_zoom": True,
    "hook_overlay": True,
    "hook_seconds": 3.0,
    "normalize_audio": True,
    "encoder": "auto",                # auto | nvenc | x264
    "crf": 20,
    "x264_preset": "veryfast",
    "max_fps": 30,
    "ffmpeg_path": "",                # optional explicit path to ffmpeg(.exe) or its folder
}

SECRET_KEYS = {"openai_api_key", "anthropic_api_key"}


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
        out[key] = v
    return out

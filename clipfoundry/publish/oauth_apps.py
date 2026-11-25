"""ClipForge's own app registrations at Google and TikTok, so Connect is one sign-in with no codes to paste.

Which registration a sign-in uses (per platform; the first complete one wins):
  1. your own developer app, when you entered both of its codes under Settings → Publishing → Advanced
     (youtube_client_id + youtube_client_secret, tiktok_client_key + tiktok_client_secret);
  2. environment variables: CLIPFORGE_YOUTUBE_CLIENT_ID + CLIPFORGE_YOUTUBE_CLIENT_SECRET,
     CLIPFORGE_TIKTOK_CLIENT_KEY + CLIPFORGE_TIKTOK_BROKER;
  3. oauth_apps.json in ClipForge's data folder;
  4. oauth_apps.json next to this package, written by the release build from the repository's secrets
     (scripts/write_oauth_apps.py; the file is never committed).

Google says a Desktop-app client "cannot keep secrets confidential", so its client secret may ship inside the app;
PKCE, the state check and the 127.0.0.1 redirect are what protect the sign-in. TikTok says its client secret lives
server-side only, so the built-in TikTok registration names a token broker instead (deploy/tiktok_broker): the app
sends the sign-in code, its PKCE verifier and the redirect address there, the broker adds the secret, and TikTok's
answer comes back. The app never has TikTok's secret, and the broker keeps nothing.

File format: {"youtube": {"client_id": "...", "client_secret": "..."},
              "tiktok": {"client_key": "...", "broker": "https://..."}}
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from .. import config

FILE = "oauth_apps.json"
BUNDLED = Path(__file__).resolve().parents[1] / FILE


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _broker_ok(url: str) -> bool:
    """Only an https broker (or one on this computer, for tests and development) is ever sent a sign-in code."""
    try:
        u = urlsplit(url)
    except ValueError:
        return False
    return (u.scheme == "https" and bool(u.hostname)) or (u.scheme == "http" and u.hostname in ("127.0.0.1",
                                                                                               "localhost"))


def built_in() -> dict:
    """The built-in registrations: {"youtube": {...}, "tiktok": {...}}, each complete or absent."""
    out: dict[str, dict] = {}
    env = {"youtube": {"client_id": os.environ.get("CLIPFORGE_YOUTUBE_CLIENT_ID", ""),
                       "client_secret": os.environ.get("CLIPFORGE_YOUTUBE_CLIENT_SECRET", "")},
           "tiktok": {"client_key": os.environ.get("CLIPFORGE_TIKTOK_CLIENT_KEY", ""),
                      "broker": os.environ.get("CLIPFORGE_TIKTOK_BROKER", "")}}
    for source in (env, _read(config.data_dir() / FILE), _read(BUNDLED)):
        yt = source.get("youtube") or {}
        if "youtube" not in out and str(yt.get("client_id") or "").strip() and str(yt.get("client_secret") or ""
                                                                                    ).strip():
            out["youtube"] = {"client_id": str(yt["client_id"]).strip(), "client_secret": str(yt["client_secret"])}
        tk = source.get("tiktok") or {}
        broker = str(tk.get("broker") or "").strip().rstrip("/")
        if "tiktok" not in out and str(tk.get("client_key") or "").strip() and _broker_ok(broker):
            out["tiktok"] = {"client_key": str(tk["client_key"]).strip(), "broker": broker}
    return out


def own(settings: dict, platform: str) -> bool:
    """You entered both codes of your own developer app (Advanced)."""
    if platform == "youtube":
        return bool(str(settings.get("youtube_client_id") or "").strip() and settings.get("youtube_client_secret"))
    return bool(str(settings.get("tiktok_client_key") or "").strip() and settings.get("tiktok_client_secret"))


def source(settings: dict, platform: str) -> str:
    """"own" (your developer app), "built_in" (ClipForge's) or "" (neither: Connect can't start)."""
    if own(settings, platform):
        return "own"
    return "built_in" if platform in built_in() else ""


def effective(settings: dict) -> dict:
    """`settings` with the registration each sign-in uses. Your own app wins; otherwise ClipForge's is filled in.
    A half-entered own app (one code) never mixes with the built-in one. The result is used for sign-in only and is
    never saved or shown (it may hold the built-in YouTube client secret)."""
    out = dict(settings)
    apps = built_in()
    if not own(settings, "youtube") and "youtube" in apps:
        out["youtube_client_id"] = apps["youtube"]["client_id"]
        out["youtube_client_secret"] = apps["youtube"]["client_secret"]
    out["tiktok_broker"] = ""
    if not own(settings, "tiktok") and "tiktok" in apps:
        out["tiktok_client_key"] = apps["tiktok"]["client_key"]
        out["tiktok_client_secret"] = ""
        out["tiktok_broker"] = apps["tiktok"]["broker"]
    return out


def describe(settings: dict) -> dict:
    """What the Accounts and Settings pages say about each platform's sign-in (no codes, no secrets)."""
    view = {}
    for platform in ("youtube", "tiktok"):
        where = source(settings, platform)
        view[platform] = {"ready": bool(where), "source": where,
                          "text": {"own": "Signs in through your own developer app (Advanced).",
                                   "built_in": "One sign-in: ClipForge's own app registration.",
                                   "": "This copy of ClipForge has no built-in sign-in for this platform. Install a "
                                       "release build, or use your own developer app under Settings → Publishing → "
                                       "Advanced."}[where]}
    return view

"""Write clipfoundry/oauth_apps.json for a release build, from the repository's secrets (never committed).

    CLIPFORGE_YOUTUBE_CLIENT_ID, CLIPFORGE_YOUTUBE_CLIENT_SECRET   ClipForge's Google "Desktop app" OAuth client
    CLIPFORGE_TIKTOK_CLIENT_KEY, CLIPFORGE_TIKTOK_BROKER          ClipForge's TikTok app key and its token broker

A platform whose values are missing is left out: that build then asks for your own developer app instead (Settings →
Publishing → Advanced). Prints which platforms were written, never the values.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "clipfoundry" / "oauth_apps.json"


def main() -> int:
    apps = {}
    yt_id, yt_secret = os.environ.get("CLIPFORGE_YOUTUBE_CLIENT_ID", ""), os.environ.get(
        "CLIPFORGE_YOUTUBE_CLIENT_SECRET", "")
    if yt_id.strip() and yt_secret.strip():
        apps["youtube"] = {"client_id": yt_id.strip(), "client_secret": yt_secret.strip()}
    tk_key, broker = os.environ.get("CLIPFORGE_TIKTOK_CLIENT_KEY", ""), os.environ.get("CLIPFORGE_TIKTOK_BROKER", "")
    if tk_key.strip() and broker.strip().startswith("https://"):
        apps["tiktok"] = {"client_key": tk_key.strip(), "broker": broker.strip().rstrip("/")}
    if not apps:
        OUT.unlink(missing_ok=True)
        print("No built-in sign-in: this build asks for your own developer apps.")
        return 0
    OUT.write_text(json.dumps(apps, indent=2) + "\n", encoding="utf-8")
    print("Built-in sign-in written for:", ", ".join(sorted(apps)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

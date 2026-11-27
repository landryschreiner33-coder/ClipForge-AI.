"""Write clipfoundry/oauth_apps.json for a release build, from the repository's secrets (never committed).

    CLIPFORGE_YOUTUBE_CLIENT_ID, CLIPFORGE_YOUTUBE_CLIENT_SECRET   ClipForge's Google "Desktop app" OAuth client
    CLIPFORGE_TIKTOK_CLIENT_KEY, CLIPFORGE_TIKTOK_BROKER          ClipForge's TikTok app key and its token broker

A platform whose values are missing is left out: that build then asks for your own developer app instead (Settings →
Publishing → Advanced). Prints which platforms were written, never the values.

--release (a build with a version number, made to be downloaded): a platform left out is flagged on GitHub (a
warning on the run and a line in its summary), because without it every person who connects that account has to make
their own developer app first. --require makes it fail instead.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "clipfoundry" / "oauth_apps.json"


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    apps = {}
    yt_id, yt_secret = os.environ.get("CLIPFORGE_YOUTUBE_CLIENT_ID", ""), os.environ.get(
        "CLIPFORGE_YOUTUBE_CLIENT_SECRET", "")
    if yt_id.strip() and yt_secret.strip():
        apps["youtube"] = {"client_id": yt_id.strip(), "client_secret": yt_secret.strip()}
    tk_key, broker = os.environ.get("CLIPFORGE_TIKTOK_CLIENT_KEY", ""), os.environ.get("CLIPFORGE_TIKTOK_BROKER", "")
    if tk_key.strip() and broker.strip().startswith("https://"):
        apps["tiktok"] = {"client_key": tk_key.strip(), "broker": broker.strip().rstrip("/")}
    missing = [name for name in ("youtube", "tiktok") if name not in apps]
    if not apps:
        OUT.unlink(missing_ok=True)
        print("No built-in sign-in: this build asks for your own developer apps.")
    else:
        OUT.write_text(json.dumps(apps, indent=2) + "\n", encoding="utf-8")
        print("Built-in sign-in written for:", ", ".join(sorted(apps)))
    if missing and ("--release" in args or "--require" in args):
        names = " and ".join({"youtube": "YouTube", "tiktok": "TikTok"}[m] for m in missing)
        note = (f"This release has no built-in {names} sign-in: everyone who connects {names} must make their own "
                "developer app first. Add the CLIPFORGE_* secrets (scripts/write_oauth_apps.py) and build again.")
        print(f"::{'error' if '--require' in args else 'warning'} title=No built-in sign-in::{note}")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as out:
                out.write(f"**No built-in sign-in for {names}.** {note}\n")
        if "--require" in args:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

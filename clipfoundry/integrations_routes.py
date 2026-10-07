"""Settings → Integrations: one honest card per connection (no upload, no paid call to draw a card)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from . import audience, db
from .pipeline import nvidia
from .publish.common import app_request, local_only
from .publish.routes import _tiktok_state, _youtube_state

router = APIRouter(prefix="/api/integrations")
STATES = ("Not connected", "Connected", "Permission required", "Rate limited", "Error", "Unsupported",
          "Requires user action")


def _platform_card(pid: str, name: str, st: dict, settings: dict) -> dict:
    if not st["configured"]:
        state, nxt = "Requires user action", "Add your app's client ID and secret (see the setup steps)."
    elif st["needs_reconnect"]:
        state, nxt = "Permission required", "Reconnect: the platform no longer accepts the saved sign-in."
    elif not st["connected"]:
        state, nxt = "Not connected", "Connect your account."
    else:
        state, nxt = "Connected", ""
    caps, missing = [], []
    if pid == "youtube":
        caps = ["Private uploads", "Your video statistics"] + (["Analytics (retention)"] if st["analytics"] else [])
        if st["connected"] and not st["analytics"]:
            missing.append("YouTube Analytics permission (retention numbers)")
        caps.append("Invited viewers: you add them in YouTube Studio (no API exists for this)")
    else:
        caps = [c for c, ok in (("Direct post", st["can_direct_post"]), ("Send to your TikTok inbox",
                                                                         st["can_inbox"]),
                                ("Read your post statistics", st["can_read_stats"])) if ok]
        if not st["audited"]:
            missing.append("TikTok app audit (until then API posts are 'Only me'; Followers/Friends use a manual "
                           "package)")
    plan = audience.plan(pid, settings)
    return {"id": pid, "name": name, "state": state, "identity": st.get("name") or "", "capabilities": caps,
            "missing": missing, "next": nxt or (st.get("restriction") or ""), "audience": plan.as_dict(),
            "last_check": st.get("connected_at"), "setup": st.get("setup") or ""}


@router.get("", dependencies=[Depends(local_only)])
def integrations() -> dict:
    settings = db.get_settings()
    nv = nvidia.status(settings)
    cards = [_platform_card("youtube", "YouTube", _youtube_state(settings), settings),
             _platform_card("tiktok", "TikTok", _tiktok_state(settings, None), settings),
             {"id": "nvidia", "name": "NVIDIA AI (optional)", "state": nv["state"], "identity": nv["model"],
              "capabilities": ["Rank transcript moments", "Write titles and descriptions"],
              "missing": [nv["blocker"]] if nv["blocker"] and nv["enabled"] else [], "next": nv["blocker"],
              "detail": nv, "last_check": None}]
    return {"cards": cards, "states": STATES, "audience": audience.summary(settings)}


@router.post("/nvidia/test", dependencies=[Depends(app_request)])
def nvidia_test() -> dict:
    """The explicit "Run small AI test" (uses a little of today's budget); never run automatically."""
    try:
        return nvidia.small_test(db.get_settings())
    except (nvidia.NvidiaUnavailable, nvidia.NvidiaError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/nvidia/disconnect", dependencies=[Depends(app_request)])
def nvidia_disconnect() -> dict:
    """Clears the saved key and stops new calls; clips and usage history are kept."""
    db.save_settings({"nvidia_api_key": "", "nvidia_enabled": False, "nvidia_cloud_optin": False})
    return nvidia.status(db.get_settings())

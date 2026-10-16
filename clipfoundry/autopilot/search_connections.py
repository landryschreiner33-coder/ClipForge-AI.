"""Explicit, bounded checks of saved discovery credentials, separate from posting permissions."""
from __future__ import annotations

import hashlib
import json
import threading
import time

import httpx

from .. import db
from ..publish import youtube
from ..publish.common import PublishError, client, retry_after
from . import providers, quota, state

TAVILY_USAGE_URL = "https://api.tavily.com/usage"
PROVIDERS = ("youtube", "tavily")
_LOCKS = {name: threading.Lock() for name in PROVIDERS}
RECHECK_SECONDS = 30


def _identity(provider: str, settings: dict) -> str:
    key = str(settings.get(f"{provider}_api_key") or "").strip()
    identity = [provider, key]
    if provider == "youtube" and not key:
        account = db.get_account("youtube") or {}
        identity.extend([settings.get("youtube_client_id"), settings.get("youtube_client_secret"),
                         account.get("account_id"), account.get("connected_at"), account.get("scopes"),
                         bool(account.get("has_tokens"))])
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _mode(provider: str, settings: dict) -> str:
    if str(settings.get(f"{provider}_api_key") or "").strip():
        return "api_key"
    return "connected_account" if provider == "youtube" else "not_configured"


def view() -> dict:
    """Read-only status; saved secrets and their fingerprints never leave this module."""
    settings = db.get_settings()
    result = {}
    for provider in PROVIDERS:
        record = state.get(f"search:check:{provider}") or {}
        check = {k: v for k, v in record.items() if k != "identity"} if record else None
        if check:
            check["current"] = record.get("identity") == _identity(provider, settings)
        mode = _mode(provider, settings)
        configured = mode == "api_key" or (provider == "youtube" and youtube.configured(settings)
                                           and bool((db.get_account("youtube") or {}).get("has_tokens")))
        result[provider] = {"configured": bool(configured), "auth_mode": mode, "last_check": check}
    return result


def _result(provider: str, ok: bool, status: str, detail: str, fix: str = "", code: str = "",
            until: float | None = None) -> dict:
    return {"provider": provider, "ok": ok, "status": status, "detail": detail, "fix": fix, "code": code,
            "until": until, "at": time.time()}


def _tavily(settings: dict) -> dict:
    key = str(settings.get("tavily_api_key") or "").strip()
    if not key:
        raise providers.Unavailable("not_configured", "No Tavily search key is saved.",
                                    "Paste the API key from your Tavily dashboard and save changes first.")
    with client(15) as connection:
        response = connection.get(TAVILY_USAGE_URL, headers={"Authorization": f"Bearer {key}"})
    delay = retry_after(response)
    if delay is not None:
        providers.defer("web", delay)
    if response.status_code in (401, 403):
        raise providers.Unavailable("error", "Tavily did not accept this search key.",
                                    "Copy an active API key from your Tavily dashboard, replace it here and save.",
                                    retry_after=delay)
    if response.status_code == 429:
        raise providers.Unavailable("quota", "Tavily is limiting requests.",
                                    "Check Tavily's usage dashboard. Honor its requested wait before trying again.",
                                    retry_after=delay)
    if response.status_code in (402, 432, 433):
        raise providers.Unavailable("budget", "Tavily reports an account or credit limit.",
                                    "Check your plan and usage in Tavily. Changing a key does not replenish credits.",
                                    retry_after=delay)
    if response.status_code != 200:
        raise providers.Unavailable("error", "Tavily could not complete the connection check.",
                                    "Try again after any requested wait; check Tavily's service status if it persists.",
                                    retry_after=delay)
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("key"), dict) \
            or not isinstance(data.get("account"), dict):
        raise ValueError("invalid usage response")
    key_usage, account = data["key"], data["account"]
    for value in (key_usage.get("usage"), account.get("plan_usage"), account.get("plan_limit")):
        if type(value) is not int or value < 0:
            raise ValueError("invalid usage counts")
    if not isinstance(account.get("current_plan"), str) or not account["current_plan"]:
        raise ValueError("invalid usage plan")
    return _result("tavily", True, "connected", "Tavily accepted the saved key and returned account usage.",
                   "This check runs no search. Search credits, your app allowance and provider limits still apply.")


def test(provider: str) -> dict:
    """One explicit local-page action. No search, uploads, account changes or automatic credential switching."""
    if provider not in PROVIDERS:
        raise ValueError("Unknown search provider")
    if not _LOCKS[provider].acquire(blocking=False):
        return _result(provider, False, "waiting", "A connection check is already running.",
                       "Wait for its result before trying again.", "check_running")
    try:
        settings = db.get_settings()
        identity = _identity(provider, settings)
        previous = state.get(f"search:check:{provider}") or {}
        now = time.time()
        wait = providers.wait_until("youtube" if provider == "youtube" else "web")
        if provider == "tavily":
            wait = max(wait, float(state.get("web:wait_until", 0) or 0))
        if wait > now:
            return _result(provider, False, "waiting", "This service asked ClipFoundry to wait.",
                           "Other searches and local folders can continue. Try this check after the wait.",
                           "provider_wait", wait)
        due = float(previous.get("at") or 0) + RECHECK_SECONDS
        if previous.get("identity") == identity and due > now:
            return _result(provider, False, "waiting", "This saved connection was just checked.",
                           "Wait a few seconds before checking it again.", "check_cooldown", due)
        try:
            if provider == "youtube":
                discovery = providers.YouTubeDiscovery(settings)
                discovery.check_connection()
                mode = "API key" if discovery.auth_mode == "api_key" else "connected account"
                result = _result(provider, True, "connected", f"YouTube accepted the saved {mode} for a data read.",
                                 f"This made {discovery.calls} general-quota read(s), including any sign-in retry; "
                                 "no search was run. Search quota and download access are separate; "
                                 "this does not test uploading.")
            else:
                result = _tavily(settings)
        except quota.QuotaDenied as exc:
            result = _result(provider, False, "quota", str(exc),
                             "YouTube quota resets at midnight Pacific Time. Other providers and folders continue.",
                             "quota_budget", exc.retry_at)
        except PublishError as exc:
            # Unexpected OAuth token-service descriptions are not safe display text; known provider errors
            # already use static messages. Never persist a remote body that could reflect a credential.
            safe = exc.code in {"api_key_invalid", "api_key_restricted", "api_key_rejected", "api_disabled",
                                "quota_budget", "quotaExceeded", "dailyLimitExceeded", "rate_limit",
                                "rateLimitExceeded", "userRateLimitExceeded", "reconnect", "setup",
                                "not_connected", "insufficientPermissions", "forbidden", "response",
                                "invalidPageToken", "youtubeSignupRequired"}
            result = _result(provider, False, "error", str(exc) if safe else "Google could not confirm this sign-in.",
                             exc.fix if safe else "Check the YouTube account connection in Settings → Accounts.",
                             exc.code or "connection_error",
                             time.time() + exc.retry_after if exc.retry_after is not None else None)
        except providers.Unavailable as exc:
            result = _result(provider, False, exc.status, str(exc), exc.fix, exc.status,
                             time.time() + exc.retry_after if exc.retry_after is not None else None)
        except (httpx.HTTPError, ValueError, TypeError):
            result = _result(provider, False, "error", "The search service could not be checked.",
                             "Check your connection and try again. No secret or provider response is shown here.",
                             "network_or_response")
        result["auth_mode"] = _mode(provider, settings)
        state.put(f"search:check:{provider}", {**result, "identity": identity})
        return {**result, "current": _identity(provider, db.get_settings()) == identity}
    finally:
        _LOCKS[provider].release()

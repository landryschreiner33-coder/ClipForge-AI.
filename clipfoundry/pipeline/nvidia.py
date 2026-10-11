"""Optional NVIDIA-hosted text AI (build.nvidia.com / NVIDIA API Catalog): off by default, never required.

What it may do: read short, minimized transcript excerpts of clip candidates and return the same JSON the local
providers return (scores, a tight sentence range, grounded title and hooks). It never sees video or audio, never
finds trends, never checks a finished file, and never decides anything: the deterministic code still owns schedules,
gates, quotas, privacy and every state change, and model text is only data (rule 12).

Guards, in the order a request meets them:

1. Off unless you turned it on, chose it as the AI provider and agreed once that approved excerpts leave this PC.
2. "Development" (the free catalog preview) is only used for work you start yourself; unattended Autopilot work stays
   local. "Production" needs your own endpoint plus a price and a daily spending cap; an unknown price is not $0.
3. A daily budget of requests and tokens, reserved before each request inside one database transaction, so two jobs
   cannot both take the last of it; a retry or a repair counts too, and a request whose answer was lost keeps its
   reservation (uncertain usage).
4. Only the configured host gets the key: no redirects are followed, https only.
5. Errors: a refused key or a retired model stops calls for an hour; 429 honors Retry-After exactly; 5xx and timeouts
   open the circuit after 3 failures in a row. Each failure falls back to local analysis for that one step.
6. At most one formatting repair for an answer that is not JSON, inside the same budget.
7. Answers are cached by model, prompt version and content hash, so the same excerpt is never paid for twice.

Tests use a fake transport (tests/test_nvidia.py); no key is needed to run the app or its tests.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import time
from typing import Any, Callable

import httpx

from .. import db
from ..pipeline.common import log

CATALOG_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"  # a candidate to evaluate, not a promise it stays listed
PROMPT_VERSION = 1
CACHE_DAYS = 30
CIRCUIT_FAILURES = 3
STATE_KEY = "nvidia:circuit"
# the transport is replaceable so tests (and nothing else) can answer without the network
Transport = Callable[[str, str, dict, dict, float], httpx.Response]


class NvidiaUnavailable(RuntimeError):
    """This request is not sent (off, not allowed, over budget, circuit open) or failed: use local analysis."""

    def __init__(self, message: str, code: str = "unavailable"):
        super().__init__(message)
        self.code = code


def _send(method: str, url: str, headers: dict, body: dict, timeout: float) -> httpx.Response:
    with httpx.Client(timeout=timeout, follow_redirects=False) as c:  # the key never follows a redirect
        return c.request(method, url, headers=headers, json=body or None)


transport: Transport = _send


# ------------------------------------------------------------------ configuration
def api_key(settings: dict) -> str:
    return str(settings.get("nvidia_api_key") or os.environ.get("NVIDIA_API_KEY") or "").strip()


def base_url(settings: dict) -> str:
    if settings.get("nvidia_mode") == "production":
        return str(settings.get("nvidia_production_url") or "").rstrip("/")
    return CATALOG_URL


def view(settings: dict) -> dict:
    """What Settings → Integrations → NVIDIA AI shows (the key itself never leaves the backend)."""
    key = api_key(settings)
    mode = settings.get("nvidia_mode") or "development"
    problems = configuration_problems(settings)
    used = usage_today(settings)
    return {"enabled": bool(settings.get("nvidia_enabled")), "selected": settings.get("ai_provider") == "nvidia",
            "has_key": bool(key), "key_from_env": bool(os.environ.get("NVIDIA_API_KEY")) and
            not settings.get("nvidia_api_key"), "model": settings.get("nvidia_model") or DEFAULT_MODEL,
            "mode": mode, "opted_in": bool(settings.get("nvidia_opt_in_at")),
            "endpoint": base_url(settings) or "", "problems": problems, "usage": used,
            "circuit": circuit(), "limits": {k: settings.get(k) for k in (
                "nvidia_daily_requests", "nvidia_daily_tokens", "nvidia_max_output_tokens",
                "nvidia_max_input_tokens", "nvidia_price_per_mtok_usd", "nvidia_daily_spend_cap_usd")},
            "data_note": ("When on, the sentences of the strongest clip candidates (links and email addresses "
                          "removed) and the video's name are sent to NVIDIA. Video, audio, account tokens and "
                          "viewer lists are never sent. Choosing selected viewers does not keep these excerpts on "
                          "this PC. Check NVIDIA's current terms for retention and training before you turn it on."),
            "development_note": ("Development mode uses NVIDIA's hosted catalog, which NVIDIA describes as "
                                 "development and prototyping access. ClipFoundry uses it only for work you start "
                                 "yourself; Autopilot keeps using local analysis.")}


def configuration_problems(settings: dict) -> list[str]:
    out = []
    if not settings.get("nvidia_enabled"):
        out.append("NVIDIA AI is off.")
    if not api_key(settings):
        out.append("No NVIDIA API key is saved (or set as NVIDIA_API_KEY).")
    if not settings.get("nvidia_opt_in_at"):
        out.append("You have not agreed yet that approved excerpts leave this PC.")
    if settings.get("nvidia_mode") == "production":
        url = str(settings.get("nvidia_production_url") or "")
        if not url.startswith("https://"):
            out.append("Production mode needs your own https endpoint.")
        if _price(settings) is None:
            out.append("Production mode needs a price per million tokens (an unknown price is not $0).")
        if float(settings.get("nvidia_daily_spend_cap_usd") or 0) <= 0:
            out.append("Production mode needs a daily spending cap above $0.")
    return out


def _price(settings: dict) -> float | None:
    v = settings.get("nvidia_price_per_mtok_usd")
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


# ------------------------------------------------------------------ circuit breaker
def circuit() -> dict:
    from ..autopilot import state

    c = state.get(STATE_KEY) or {}
    return {**c, "open": float(c.get("until") or 0) > time.time()}


def _trip(reason: str, seconds: float, consecutive: bool = False) -> None:
    from ..autopilot import state

    c = state.get(STATE_KEY) or {}
    fails = int(c.get("fails") or 0) + 1
    if consecutive and fails < CIRCUIT_FAILURES:
        state.put(STATE_KEY, {**c, "fails": fails, "reason": reason, "at": time.time()})
        return
    state.put(STATE_KEY, {"fails": fails, "reason": reason, "at": time.time(), "until": time.time() + seconds})


def _ok() -> None:
    from ..autopilot import state

    state.put(STATE_KEY, {"fails": 0})


# ------------------------------------------------------------------ budget (reserved before each request)
def _day(settings: dict) -> str:
    from ..autopilot.scout import tz

    return dt.datetime.now(tz(settings)).strftime("%Y-%m-%d")


def usage_today(settings: dict) -> dict:
    day = _day(settings)
    rows = db.select("ai_usage", "provider = 'nvidia' AND day = ?", (day,))
    tokens = sum(int(r["input_tokens"] or 0) + int(r["output_tokens"] or 0) if r["status"] == "done"
                 else int(r["reserved_tokens"] or 0) for r in rows if r["status"] != "canceled")
    costs = [r["cost_usd"] for r in rows if r["status"] != "canceled"]
    return {"day": day, "requests": sum(r["status"] != "canceled" for r in rows), "tokens": tokens,
            "cost_usd": None if any(c is None for c in costs) or not costs else round(sum(costs), 4),
            "cost_known": bool(costs) and all(c is not None for c in costs)}


def reserve(settings: dict, tokens: int, task: str, job_id: str = "") -> str:
    """Take budget for one request atomically, or raise NvidiaUnavailable naming the limit that was reached."""
    day = _day(settings)
    max_req = int(settings.get("nvidia_daily_requests") or 0)
    max_tok = int(settings.get("nvidia_daily_tokens") or 0)
    price = _price(settings)
    cap = float(settings.get("nvidia_daily_spend_cap_usd") or 0)
    rid = db.new_id()
    now = time.time()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")  # one reservation at a time across threads and processes
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN status = 'done' THEN COALESCE(input_tokens, 0) + "
                "COALESCE(output_tokens, 0) ELSE reserved_tokens END), 0) AS t, COALESCE(SUM(cost_usd), 0) AS c "
                "FROM ai_usage WHERE provider = 'nvidia' AND day = ? AND status != 'canceled'", (day,)).fetchone()
            if row["n"] + 1 > max_req:
                raise NvidiaUnavailable(f"Today's NVIDIA request limit ({max_req}) is used up; local analysis is "
                                        "used until tomorrow.", "budget")
            if row["t"] + tokens > max_tok:
                raise NvidiaUnavailable(f"Today's NVIDIA token limit ({max_tok:,}) would be passed; local analysis "
                                        "is used until tomorrow.", "budget")
            if settings.get("nvidia_mode") == "production" and price is not None and \
                    row["c"] + tokens * price / 1e6 > cap:
                raise NvidiaUnavailable(f"Today's spending cap (${cap:.2f}) would be passed.", "budget")
            conn.execute("INSERT INTO ai_usage (id, provider, day, job_id, task, model, status, reserved_tokens, "
                         "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (rid, "nvidia", day, job_id, task, settings.get("nvidia_model") or DEFAULT_MODEL,
                          "reserved", tokens, now, now))
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    return rid


def _settle(rid: str, settings: dict, status: str, usage: dict | None = None, error: str = "") -> None:
    fields: dict[str, Any] = {"status": status, "error": error[:300]}
    if usage and usage.get("prompt_tokens") is not None:
        fields["input_tokens"] = int(usage["prompt_tokens"])
        fields["output_tokens"] = int(usage.get("completion_tokens") or 0)
        price = _price(settings)
        fields["cost_usd"] = None if price is None else round(
            (fields["input_tokens"] + fields["output_tokens"]) * price / 1e6, 6)
    elif status == "done":
        status = fields["status"] = "uncertain"  # no usage reported: the reservation keeps counting
    db.update("ai_usage", rid, **fields)


# ------------------------------------------------------------------ the request
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def minimize(text: str, limit_tokens: int) -> str:
    """Links and email addresses removed; cut at the input limit (whole lines only, and said so)."""
    text = EMAIL_RE.sub("[email]", URL_RE.sub("[link]", text))
    limit = max(200, int(limit_tokens) * 4)
    if len(text) <= limit:
        return text
    kept = text[:limit].rsplit("\n", 1)[0]
    return kept + "\n[the rest was not sent]"


def _allowed(settings: dict, unattended: bool) -> None:
    if settings.get("ai_provider") != "nvidia":
        raise NvidiaUnavailable("NVIDIA AI is not the selected provider.", "off")
    problems = configuration_problems(settings)
    if problems:
        raise NvidiaUnavailable(problems[0], "setup")
    if unattended and (settings.get("nvidia_mode") or "development") != "production":
        raise NvidiaUnavailable("Development mode is not used for unattended Autopilot work; local analysis is "
                                "used.", "development_only")
    c = circuit()
    if c["open"]:
        raise NvidiaUnavailable(f"NVIDIA AI is paused until {time.strftime('%H:%M', time.localtime(c['until']))}: "
                                f"{c.get('reason') or 'repeated failures'}.", "circuit")


def _cache_key(settings: dict, system: str, prompt: str) -> str:
    digest = hashlib.sha256(json.dumps([settings.get("nvidia_model") or DEFAULT_MODEL, PROMPT_VERSION, system,
                                        prompt], ensure_ascii=False).encode()).hexdigest()
    return f"nvidia:{digest}"


def _has_json(text: str) -> bool:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return False
    try:
        return isinstance(json.loads(m.group(0)), dict)
    except ValueError:
        return False


def _request(settings: dict, messages: list[dict], task: str, job_id: str) -> tuple[str, dict]:
    url = base_url(settings) + "/chat/completions"
    if not url.startswith("https://"):
        raise NvidiaUnavailable("The NVIDIA endpoint must use https.", "setup")
    max_out = int(settings.get("nvidia_max_output_tokens") or 800)
    body = {"model": settings.get("nvidia_model") or DEFAULT_MODEL, "messages": messages, "temperature": 0.2,
            "max_tokens": max_out, "stream": False}
    est = sum(len(m["content"]) for m in messages) // 4 + max_out
    rid = reserve(settings, est, task, job_id)
    headers = {"Authorization": f"Bearer {api_key(settings)}", "Accept": "application/json"}
    timeout = float(settings.get("nvidia_timeout_s") or 60)
    try:
        r = transport("POST", url, headers, body, timeout)
    except httpx.TimeoutException:
        _settle(rid, settings, "uncertain", error="timeout")  # it may have been processed: the reservation stays
        _trip("timeouts", 600, consecutive=True)
        raise NvidiaUnavailable("NVIDIA did not answer in time; local analysis is used.", "timeout") from None
    except httpx.HTTPError as exc:
        _settle(rid, settings, "failed", error=type(exc).__name__)
        _trip("not reachable", 600, consecutive=True)
        raise NvidiaUnavailable("NVIDIA could not be reached; local analysis is used.", "network") from None
    if r.is_redirect:
        _settle(rid, settings, "failed", error=f"redirect {r.status_code}")
        _trip("the endpoint redirected (the key is never sent elsewhere)", 3600)
        raise NvidiaUnavailable("The NVIDIA endpoint redirected; nothing was sent there.", "redirect")
    if r.status_code in (401, 403):
        _settle(rid, settings, "failed", error=str(r.status_code))
        _trip("the API key was refused", 3600)
        raise NvidiaUnavailable("NVIDIA refused the API key. Check it in Settings → Integrations.", "auth")
    if r.status_code in (404, 410):
        _settle(rid, settings, "failed", error=str(r.status_code))
        _trip(f"model {body['model']} is not available", 3600)
        raise NvidiaUnavailable(f"The model {body['model']} is not available (it may have been retired).", "model")
    if r.status_code == 429:
        from ..publish.common import retry_after

        wait = retry_after(r) or 60.0
        _settle(rid, settings, "failed", error="429")
        _trip("NVIDIA asked to wait (rate limit)", wait)  # exactly as long as asked, never shorter
        raise NvidiaUnavailable(f"NVIDIA asked to wait {int(wait)} s; local analysis is used meanwhile.", "rate")
    if r.status_code >= 500 or r.status_code != 200:
        _settle(rid, settings, "failed", error=str(r.status_code))
        _trip(f"server error {r.status_code}", 600, consecutive=True)
        raise NvidiaUnavailable(f"NVIDIA answered with an error ({r.status_code}); local analysis is used.", "server")
    try:
        data = r.json()
        text = str(data["choices"][0]["message"]["content"] or "")
    except (ValueError, KeyError, IndexError, TypeError):
        _settle(rid, settings, "uncertain", error="unreadable answer")
        raise NvidiaUnavailable("NVIDIA's answer could not be read; local analysis is used.", "format") from None
    _settle(rid, settings, "done", data.get("usage") if isinstance(data.get("usage"), dict) else None)
    _ok()
    return text, data


def complete(settings: dict, system: str, prompt: str, *, task: str = "clip_scoring", unattended: bool = False,
             job_id: str = "") -> str:
    """One JSON-answer request. Raises NvidiaUnavailable whenever local analysis should be used instead."""
    _allowed(settings, unattended)
    prompt = minimize(prompt, int(settings.get("nvidia_max_input_tokens") or 6000))
    key = _cache_key(settings, system, prompt)
    hit = db.fetch("api_cache", key, "key")
    if hit and float(hit["expires_at"]) > time.time():
        return json.loads(hit["response"])["text"]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    text, _ = _request(settings, messages, task, job_id)
    if not _has_json(text):  # one repair, inside the same budget; then local analysis
        messages += [{"role": "assistant", "content": text[:4000]},
                     {"role": "user", "content": "Reply again with only the JSON object, no other text."}]
        text, _ = _request(settings, messages, task + ":repair", job_id)
        if not _has_json(text):
            raise NvidiaUnavailable("NVIDIA's answer was not valid JSON after one repair; local analysis is used.",
                                    "format")
    now = time.time()
    db.execute("INSERT OR REPLACE INTO api_cache (key, method, response, fetched_at, expires_at) VALUES (?,?,?,?,?)",
               (key, "nvidia.chat", json.dumps({"text": text}), now, now + CACHE_DAYS * 86400))
    return text


# ------------------------------------------------------------------ Settings: check and test
def check(settings: dict) -> dict:
    """Check the configuration without generating anything (no usage). NVIDIA's model list does not prove the key
    works, so the answer says so."""
    problems = [p for p in configuration_problems(settings) if "off" not in p and "agreed" not in p]
    if problems:
        return {"ok": False, "detail": problems[0], "key_verified": False}
    model = settings.get("nvidia_model") or DEFAULT_MODEL
    try:
        r = transport("GET", base_url(settings) + "/models", {"Authorization": f"Bearer {api_key(settings)}"}, {},
                      15.0)
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": f"NVIDIA could not be reached ({type(exc).__name__}).", "key_verified": False}
    if r.status_code in (401, 403):
        return {"ok": False, "detail": "NVIDIA refused the API key.", "key_verified": False}
    if r.status_code != 200:
        return {"ok": False, "detail": f"NVIDIA answered {r.status_code}.", "key_verified": False}
    try:
        ids = [m.get("id") for m in r.json().get("data", [])]
    except (ValueError, AttributeError):
        ids = []
    listed = model in ids
    return {"ok": listed, "key_verified": False, "models": ids[:200],
            "detail": (f"{model} is listed. This check does not use the key for a request, so the key is not "
                       "verified until you run the small AI test.") if listed else
            f"{model} is not in NVIDIA's model list; choose another model."}


TEST_PROMPT = ("Sentences are numbered.\n[0] Water boils at a lower temperature on high mountains.\n"
               "[1] That is because the air pressure is lower there.\n"
               'Return JSON: {"hook": 0-10, "payoff": 0-10, "start_sentence": 0, "end_sentence": 1, '
               '"reason": "one short sentence"}')


def small_test(settings: dict) -> dict:
    """The explicit Run small AI test: harmless synthetic text, counted against today's budget."""
    started = time.time()
    try:
        text = complete({**settings, "nvidia_mode": settings.get("nvidia_mode") or "development"},
                        "Reply with a single JSON object and nothing else.", TEST_PROMPT, task="settings_test")
    except NvidiaUnavailable as exc:
        return {"ok": False, "detail": str(exc), "code": exc.code}
    ok = _has_json(text)
    log.info("NVIDIA small test finished in %.1f s (valid JSON: %s)", time.time() - started, ok)
    return {"ok": ok, "detail": "The model answered with valid JSON; the key works." if ok else
            "The model answered, but not with valid JSON.", "seconds": round(time.time() - started, 1),
            "usage": usage_today(settings)}


def disconnect() -> dict:
    """Forget the key and stop new requests (clips and earlier results stay)."""
    patch = {"nvidia_enabled": False, "nvidia_api_key": "", "nvidia_opt_in_at": 0.0}
    settings = db.get_settings()
    if settings.get("ai_provider") == "nvidia":
        patch["ai_provider"] = "heuristic"
    db.save_settings(patch)
    return {"disconnected": True}

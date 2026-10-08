"""The optional NVIDIA text-AI adapter, with a mocked transport only (no key, no network, no cost)."""
from __future__ import annotations

import json

import httpx
import pytest

ON = {"nvidia_enabled": True, "nvidia_cloud_optin": True, "nvidia_api_key": "nvapi-test-0000",
      "nvidia_daily_requests": 10, "nvidia_daily_tokens": 50000}
SEGS = [{"id": i, "start": i * 10.0, "end": i * 10.0 + 10, "text": f"sentence {i} about building habits"}
        for i in range(8)]


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr("time.sleep", lambda s: None)
    from clipfoundry import db

    db.init()
    return tmp_path


def _answer(moments: list[dict], usage: dict | None = None) -> dict:
    return {"model": "nvidia/nemotron-3.5-lightning-30b-a3b", "usage": usage or {"prompt_tokens": 100,
                                                                                  "completion_tokens": 40},
            "choices": [{"message": {"content": json.dumps({"schema": "moments.v1", "moments": moments})}}]}


GOOD = {"start_id": 1, "end_id": 3, "score": 81, "hook": 8, "context": 7, "payoff": 9, "reason": "clear payoff",
        "evidence_ids": [1, 3], "uncertainty": 0.2}


class Fake(httpx.BaseTransport):
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request):
        self.requests.append(request)
        r = self.responses.pop(0)
        return r if isinstance(r, httpx.Response) else httpx.Response(200, json=r)


def test_off_by_default_and_no_call_without_opt_in(data):
    from clipfoundry import db
    from clipfoundry.pipeline import nvidia

    s = db.get_settings()
    assert not s["nvidia_enabled"] and nvidia.status(s)["state"] == "Not connected"
    t = Fake()
    out = nvidia.rank_moments({**ON, "nvidia_cloud_optin": False}, SEGS, transport=t)
    assert out["fallback"] and "opted in" in out["note"] and not t.requests


def test_grounded_moments_are_validated_and_mapped_to_real_times(data):
    from clipfoundry.pipeline import nvidia

    t = Fake(_answer([GOOD]))
    out = nvidia.rank_moments(ON, SEGS, "proj1", transport=t)
    [m] = out["moments"]
    assert (m["start"], m["end"]) == (10.0, 40.0) and out["provider"] == "nvidia" and not out["fallback"]
    req = t.requests[0]
    assert req.url.host == "integrate.api.nvidia.com" and req.headers["authorization"] == "Bearer nvapi-test-0000"
    assert nvidia.usage_today() == {"requests": 1, "tokens": 140, "cost_usd": 0.0}  # reported usage replaces the hold
    again = Fake()
    assert nvidia.rank_moments(ON, SEGS, transport=again)["moments"] and not again.requests  # cached


@pytest.mark.parametrize("bad", [
    {**GOOD, "start_id": 99}, {**GOOD, "start_id": 3, "end_id": 1}, {**GOOD, "score": 140},
    {**GOOD, "evidence_ids": [42]},
])
def test_invalid_answers_get_one_repair_then_fall_back(data, bad):
    from clipfoundry.pipeline import nvidia

    t = Fake(_answer([bad]), _answer([bad]))
    out = nvidia.rank_moments(ON, SEGS, transport=t)
    assert out["fallback"] and out["moments"] == [] and len(t.requests) == 2  # one repair, never a loop
    assert nvidia.usage_today()["requests"] == 2  # the repair came out of the same budget


def test_repair_that_works_is_used(data):
    from clipfoundry.pipeline import nvidia

    t = Fake({"choices": [{"message": {"content": "Sure! Here you go"}}]}, _answer([GOOD]))
    assert nvidia.rank_moments(ON, SEGS, transport=t)["moments"][0]["score"] == 81


def test_the_key_never_leaves_the_approved_host(data):
    from clipfoundry.pipeline import nvidia

    t = Fake(httpx.Response(307, headers={"location": "https://evil.example/steal"}))
    with pytest.raises(nvidia.NvidiaError, match="redirect"):
        nvidia.chat(ON, [{"role": "user", "content": "hi"}], task="t", transport=t)
    assert len(t.requests) == 1  # not followed
    assert not nvidia.approved_host("http://integrate.api.nvidia.com/v1", ON)
    prod = {**ON, "nvidia_mode": "production", "nvidia_production_url": "http://plain.example/v1"}
    assert "HTTPS endpoint" in nvidia.blocker(prod)


def test_budgets_are_reserved_before_sending(data):
    from clipfoundry.pipeline import nvidia

    s = {**ON, "nvidia_daily_requests": 1}
    nvidia.chat(s, [{"role": "user", "content": "hi"}], task="t", transport=Fake(_answer([])))
    t = Fake()
    with pytest.raises(nvidia.NvidiaUnavailable, match="request budget"):
        nvidia.chat(s, [{"role": "user", "content": "hi"}], task="t", transport=t)
    assert not t.requests
    with pytest.raises(nvidia.NvidiaUnavailable, match="token budget"):
        nvidia.chat({**ON, "nvidia_daily_tokens": 100}, [{"role": "user", "content": "x" * 2000}], task="t",
                    transport=t)


def test_unknown_price_blocks_production_and_paid_calls_need_a_cap(data):
    from clipfoundry.pipeline import nvidia

    prod = {**ON, "nvidia_mode": "production", "nvidia_production_url": "https://ai.example.com/v1",
            "nvidia_production_terms_confirmed": True}
    assert "unknown" in nvidia.blocker(prod)
    priced = {**prod, "nvidia_price_input_per_mtok": "0.5", "nvidia_price_output_per_mtok": "1.5"}
    assert "spending cap" in nvidia.blocker(priced)
    assert nvidia.blocker({**priced, "nvidia_spend_cap_usd": 1.0}) == ""


def test_experimental_access_is_never_used_by_unattended_autopilot_work(data):
    from clipfoundry.pipeline import nvidia

    token = nvidia.UNATTENDED.set(True)
    try:
        assert "unattended" in nvidia.blocker(ON)
    finally:
        nvidia.UNATTENDED.reset(token)
    assert nvidia.blocker(ON) == ""


def test_rate_limits_retry_with_retry_after_then_open_the_breaker(data):
    from clipfoundry.pipeline import nvidia

    busy = [httpx.Response(429, headers={"retry-after": "1"}) for _ in range(3)]
    with pytest.raises(nvidia.NvidiaError, match="busy"):
        nvidia.chat(ON, [{"role": "user", "content": "hi"}], task="t", transport=Fake(*busy))
    assert "paused after repeated failures" in nvidia.blocker(ON)
    assert nvidia.status(ON)["state"] == "Rate limited"


def test_timeouts_keep_the_worst_case_counted(data):
    from clipfoundry.pipeline import nvidia

    class Slow(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(nvidia.NvidiaError, match="in time"):
        nvidia.chat(ON, [{"role": "user", "content": "hi"}], task="t", transport=Slow())
    used = nvidia.usage_today()
    assert used["requests"] == 3 and used["tokens"] >= 3 * 800  # uncertain usage is not assumed to be zero


def test_long_transcripts_are_covered_in_overlapping_chunks(data):
    from clipfoundry.pipeline import nvidia

    segs = [{"id": i, "start": float(i), "end": i + 1.0, "text": "w" * 500} for i in range(60)]
    parts = nvidia.chunks(segs, max_chars=6000, overlap=2)
    assert parts[0][0]["id"] == 0 and parts[-1][-1]["id"] == 59 and len(parts) > 1
    assert parts[1][0]["id"] == parts[0][-2]["id"]  # overlap keeps context across the cut


def test_llm_provider_falls_back_and_status_check_never_generates(data):
    from clipfoundry.pipeline import llm

    s = {"ai_provider": "nvidia", "nvidia_enabled": False}
    with pytest.raises(llm.ProviderError):
        llm.complete(s, "prompt")
    assert llm.check_provider(s)["ok"] is False


def test_integrations_cards_and_disconnect(data):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    db.save_settings(ON)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        cards = {x["id"]: x for x in c.get("/api/integrations").json()["cards"]}
        assert cards["nvidia"]["state"] == "Connected" and "nvapi" not in json.dumps(cards)  # never the key
        assert cards["youtube"]["state"] == "Requires user action"
        r = c.post("/api/integrations/nvidia/disconnect", headers={"X-ClipFoundry": "1"})
        assert r.json()["state"] == "Not connected" and not db.get_settings()["nvidia_api_key"]

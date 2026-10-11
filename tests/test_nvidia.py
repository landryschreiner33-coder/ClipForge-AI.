"""Optional NVIDIA-hosted text AI: off by default, no request without opt-in, development mode never used for
unattended Autopilot work, budgets reserved before each request, one repair, honest failures, local fallback.
Every test uses a fake transport; no key and no network are needed."""
from __future__ import annotations

import json
import threading

import httpx
import pytest

H = {"X-ClipFoundry": "1"}
GOOD = json.dumps({"hook": 7, "opening": 6, "curiosity": 6, "emotion": 5, "density": 6, "payoff": 7,
                   "standalone": 8, "pacing": 6, "retention": 6, "category": "Educational", "title": "Why water boils",
                   "hook_text": "Water boils sooner up high", "alt_hooks": [], "hashtags": ["#science"],
                   "start_sentence": 0, "end_sentence": 1, "reason": "Clear question and answer."})


class Fake:
    """Answers like NVIDIA's OpenAI-compatible endpoint; records every request (headers included)."""

    def __init__(self, *answers):
        self.answers = list(answers) or [(200, {"choices": [{"message": {"content": GOOD}}],
                                                "usage": {"prompt_tokens": 120, "completion_tokens": 60}})]
        self.calls: list[dict] = []
        self.lock = threading.Lock()

    def __call__(self, method, url, headers, body, timeout):
        with self.lock:
            self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
            answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        status, payload, *extra = answer
        return httpx.Response(status, json=payload, headers=(extra[0] if extra else {}),
                              request=httpx.Request(method, url))


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    from clipfoundry import db

    db.init()
    return tmp_path


@pytest.fixture()
def fake(monkeypatch):
    from clipfoundry.pipeline import nvidia

    f = Fake()
    monkeypatch.setattr(nvidia, "transport", f)
    return f


def ready(**extra):
    from clipfoundry import db

    db.save_settings({"ai_provider": "nvidia", "nvidia_enabled": True, "nvidia_api_key": "nvapi-test-secret",
                      **extra})
    db.save_settings({"nvidia_opt_in_at": 1.0})  # (the settings page cannot set this; its own button does)
    return db.get_settings()


def ask(settings, prompt="[0] Water boils at a lower temperature up high.\n[1] The air pressure is lower.",
        **kw):
    from clipfoundry.pipeline import llm

    return llm.complete(settings, prompt, **kw)


def test_off_by_default_and_local_analysis_makes_no_request(data, fake):
    from clipfoundry import db
    from clipfoundry.pipeline import llm, nvidia

    s = db.get_settings()
    assert not s["nvidia_enabled"] and s["ai_provider"] == "heuristic"
    with pytest.raises(llm.ProviderError):
        ask(s)
    with pytest.raises(llm.ProviderError, match="off"):
        ask({**s, "ai_provider": "nvidia"})  # chosen but not turned on
    assert fake.calls == [] and not db.select("ai_usage")
    assert nvidia.view(s)["has_key"] is False


def test_no_request_before_the_opt_in(data, fake):
    from clipfoundry import db
    from clipfoundry.pipeline import llm

    db.save_settings({"ai_provider": "nvidia", "nvidia_enabled": True, "nvidia_api_key": "nvapi-test-secret"})
    with pytest.raises(llm.ProviderError, match="agreed"):
        ask(db.get_settings())
    assert fake.calls == []


def test_a_request_is_minimized_reserved_and_cached(data, fake):
    from clipfoundry import db
    from clipfoundry.pipeline import llm, nvidia

    s = ready()
    out = llm.parse_response(ask(s, "[0] Mail me at sam@example.com or see https://evil.example/x\n[1] Done."), 2)
    assert out["title"] == "Why water boils" and out["range"] == (0, 1)
    sent = fake.calls[0]
    assert sent["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer nvapi-test-secret"
    text = json.dumps(sent["body"])
    assert "sam@example.com" not in text and "evil.example" not in text and "[email]" in text
    assert sent["body"]["max_tokens"] == 800 and sent["body"]["model"] == nvidia.DEFAULT_MODEL
    row = db.select("ai_usage")[0]
    assert row["status"] == "done" and row["input_tokens"] == 120 and row["output_tokens"] == 60
    assert row["cost_usd"] is None  # unknown price: never $0
    ask(s, "[0] Mail me at sam@example.com or see https://evil.example/x\n[1] Done.")
    assert len(fake.calls) == 1  # the same excerpt is answered from the cache
    assert nvidia.usage_today(s)["cost_known"] is False


def test_development_mode_is_never_used_for_unattended_autopilot_work(data, fake):
    from clipfoundry.pipeline import llm

    s = ready()
    with pytest.raises(llm.ProviderError, match="unattended"):
        ask(s, unattended=True)
    with pytest.raises(llm.ProviderError, match="unattended"):
        ask({**s, "origin": "autopilot"})  # what the clip pipeline passes for Autopilot projects
    assert fake.calls == []


def test_production_needs_an_endpoint_a_price_and_a_cap(data, fake):
    from clipfoundry import db
    from clipfoundry.pipeline import llm, nvidia

    s = ready(nvidia_mode="production")
    probs = nvidia.configuration_problems(s)
    assert any("https endpoint" in p for p in probs) and any("price" in p for p in probs)
    with pytest.raises(llm.ProviderError):
        ask(s, unattended=True)
    db.save_settings({"nvidia_production_url": "http://plain.example/v1"})
    assert db.get_settings()["nvidia_production_url"] == ""  # never over plain http
    s = ready(nvidia_mode="production", nvidia_production_url="https://ai.example/v1",
              nvidia_price_per_mtok_usd=0.5, nvidia_daily_spend_cap_usd=0.01)
    ask(s, unattended=True)
    assert fake.calls[0]["url"] == "https://ai.example/v1/chat/completions"
    assert db.select("ai_usage")[0]["cost_usd"] == pytest.approx(180 * 0.5 / 1e6)


def test_daily_budget_is_reserved_atomically(data, fake):
    from clipfoundry import db
    from clipfoundry.pipeline import llm, nvidia

    s = ready(nvidia_daily_requests=3)
    results = []

    def one(k):
        try:
            nvidia.reserve(s, 100, "race")
            results.append("ok")
        except nvidia.NvidiaUnavailable:
            results.append("refused")

    threads = [threading.Thread(target=one, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 3 and results.count("refused") == 5  # never more than the limit
    with pytest.raises(llm.ProviderError, match="request limit"):
        ask(s)
    assert fake.calls == []
    db.execute("DELETE FROM ai_usage")
    s = ready(nvidia_daily_tokens=500)  # a request needs its prompt plus 800 output tokens: over the limit
    with pytest.raises(llm.ProviderError, match="token limit"):
        ask(s)


def test_one_repair_then_local_fallback(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.pipeline import llm, nvidia

    bad = (200, {"choices": [{"message": {"content": "Sure! Here are my thoughts."}}],
                 "usage": {"prompt_tokens": 50, "completion_tokens": 10}})
    f = Fake(bad, (200, {"choices": [{"message": {"content": GOOD}}]}))
    monkeypatch.setattr(nvidia, "transport", f)
    s = ready()
    assert json.loads(ask(s))["title"] == "Why water boils" and len(f.calls) == 2
    rows = sorted(db.select("ai_usage"), key=lambda r: r["task"])
    assert [r["task"] for r in rows] == ["clip_scoring", "clip_scoring:repair"]
    assert rows[1]["status"] == "uncertain"  # no usage reported: its reservation keeps counting
    f2 = Fake(bad, bad, bad)
    monkeypatch.setattr(nvidia, "transport", f2)
    with pytest.raises(llm.ProviderError, match="after one repair"):
        ask(s, "[0] Another excerpt.")
    assert len(f2.calls) == 2  # never a third try


@pytest.mark.parametrize("answer, code, words", [
    ((401, {"error": "bad key"}), "auth", "refused the API key"),
    ((404, {"error": "no model"}), "model", "not available"),
    ((429, {"error": "slow down"}, {"Retry-After": "120"}), "rate", "wait 120 s"),
    ((302, {}, {"Location": "https://elsewhere.example/"}), "redirect", "redirected"),
])
def test_refusals_stop_calls_and_fall_back(data, monkeypatch, answer, code, words):
    from clipfoundry.pipeline import llm, nvidia

    f = Fake(answer)
    monkeypatch.setattr(nvidia, "transport", f)
    s = ready()
    with pytest.raises(llm.ProviderError, match=words):
        ask(s)
    c = nvidia.circuit()
    assert c["open"]
    if code == "rate":
        assert c["until"] - c["at"] == pytest.approx(120, abs=1)  # exactly as long as asked
    with pytest.raises(llm.ProviderError, match="paused until"):
        ask(s, "[0] Something else.")
    assert len(f.calls) == 1


def test_timeouts_count_as_uncertain_usage_and_open_the_circuit_after_three(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.pipeline import llm, nvidia

    f = Fake(httpx.ReadTimeout("slow"))
    monkeypatch.setattr(nvidia, "transport", f)
    s = ready()
    for k in range(3):
        with pytest.raises(llm.ProviderError, match="in time"):
            ask(s, f"[0] Excerpt {k}.")
    assert nvidia.circuit()["open"] and all(r["status"] == "uncertain" for r in db.select("ai_usage"))
    assert nvidia.usage_today(s)["tokens"] > 0  # a lost answer still counts against today's budget


def test_a_server_error_is_one_failed_step_that_falls_back(data, monkeypatch):
    """The clip scorer (pipeline/scoring.py) keeps its local result on ProviderError; one 5xx does not stop NVIDIA."""
    from clipfoundry.pipeline import llm, nvidia

    f = Fake((500, {"error": "boom"}))
    monkeypatch.setattr(nvidia, "transport", f)
    s = ready()
    with pytest.raises(llm.ProviderError, match=r"error \(500\)"):
        llm.evaluate(s, "video", ["Water boils sooner up high."], "", 20.0)
    assert len(f.calls) == 1 and not nvidia.circuit()["open"]


def test_settings_page_endpoints(data, fake, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        cards = {k["id"]: k for k in c.get("/api/integrations").json()["cards"]}
        assert cards["nvidia"]["status"] == "off" and cards["twitch"]["status"] == "not_implemented"
        assert cards["google_trends"]["status"] == "unsupported"
        c.put("/api/settings", json={"ai_provider": "nvidia", "nvidia_enabled": True, "nvidia_api_key": "nvapi-x",
                                     "nvidia_opt_in_at": 99})  # the agreement cannot be set by a settings save
        assert db.get_settings()["nvidia_opt_in_at"] == 0
        assert c.get("/api/settings").json()["nvidia_api_key"] == "********"  # never sent to the page
        assert "nvapi-x" not in c.get("/api/integrations/nvidia").text
        assert c.post("/api/integrations/nvidia/opt-in", json={"agree": True}).status_code == 403
        assert c.post("/api/integrations/nvidia/opt-in", json={"agree": True}, headers=H).json()["opted_in"]
        fake.answers = [(200, {"data": [{"id": "nvidia/nemotron-3.5-lightning-30b-a3b"}]})]
        chk = c.post("/api/integrations/nvidia/check", headers=H).json()
        assert chk["ok"] and chk["key_verified"] is False and "not verified" in chk["detail"]
        assert not db.select("ai_usage")  # the check generates nothing
        fake.answers = [(200, {"choices": [{"message": {"content": '{"hook": 6}'}}],
                               "usage": {"prompt_tokens": 30, "completion_tokens": 5}})]
        test = c.post("/api/integrations/nvidia/test", headers=H).json()
        assert test["ok"] and test["usage"]["requests"] == 1
        c.post("/api/integrations/nvidia/disconnect", headers=H)
        s = db.get_settings()
        assert not s["nvidia_enabled"] and not s["nvidia_api_key"] and s["ai_provider"] == "heuristic"

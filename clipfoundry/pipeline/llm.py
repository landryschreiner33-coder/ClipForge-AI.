"""Optional Stage 2 AI providers.

* ollama             - local LLM via http://localhost:11434 (free)
* openai_compatible  - any local OpenAI-style server: LM Studio, llama.cpp, vLLM (free)
* anthropic          - Claude API (paid, needs an API key; strictly optional)

Only the handful of strongest Stage 1 candidates are sent, never the full
transcript.  Every provider returns the same dict shape; callers fall back to
the heuristic evaluator on any error.
"""
from __future__ import annotations

import json
import re

import httpx

SYSTEM_PROMPT = (
    "You are a strict, honest short-form video editor. You evaluate candidate clips cut from a longer "
    "video for TikTok, YouTube Shorts and Reels. Only use information present in the transcript. "
    "Never invent facts, names, numbers or events. Reply with a single JSON object and nothing else."
)

CATEGORIES = ["Story", "Educational", "Motivational", "Funny", "Opinion", "Emotional", "Business", "Q&A",
              "Highlight"]


# Factors an LLM can judge from the text (speaker clarity and uniqueness are measured locally).
AI_FACTORS = ("hook", "opening", "curiosity", "emotion", "density", "payoff", "standalone", "pacing", "retention")


class ProviderError(RuntimeError):
    pass


def build_prompt(video_name: str, sentences: list[str], context_before: str, duration: float) -> str:
    numbered = "\n".join(f"[{k}] {s}" for k, s in enumerate(sentences))
    ctx = f'Context right before the clip (NOT part of the clip): "{context_before}"\n' if context_before else ""
    return (
        f"Source video: {video_name}\n"
        f"Candidate clip, about {duration:.0f} seconds. Sentences are numbered.\n{ctx}"
        f"CLIP TRANSCRIPT:\n{numbered}\n\n"
        "Score each factor from 0 to 10 (be strict; 5 is an average clip):\n"
        "- hook: do the first 3 seconds grab attention?\n"
        "- opening: does it get to the point immediately (no warm-up, greeting or slow setup)?\n"
        "- curiosity: does it open a question or gap that makes viewers want the answer?\n"
        "- emotion: emotional intensity (tension, humor, passion, surprise)\n"
        "- density: useful information or story per second, no filler or repetition\n"
        "- payoff: does it build to a satisfying conclusion, punchline or insight, and stop there?\n"
        "- standalone: does it make sense without the rest of the video?\n"
        "- pacing: tight delivery without dead air or rambling\n"
        "- retention: will viewers watch to the end?\n"
        "Also return:\n"
        f"- category: one of {', '.join(CATEGORIES)}\n"
        "- title: max 8 words, based only on the clip\n"
        "- hook_text: on-screen hook, max 12 words, grounded in what is said in the clip\n"
        "- alt_hooks: list of 3 alternative hooks, max 12 words each, grounded in the clip\n"
        "- hashtags: list of 3-5 relevant hashtags\n"
        "- start_sentence, end_sentence: the tightest sentence range (indices above) that keeps the full "
        "thought, hook and payoff\n"
        "- reason: one short sentence explaining the scores\n"
        'JSON keys: {"hook", "opening", "curiosity", "emotion", "density", "payoff", "standalone", "pacing", '
        '"retention", "category", "title", "hook_text", "alt_hooks", "hashtags", "start_sentence", "end_sentence", '
        '"reason"}'
    )


def parse_response(text: str, n_sentences: int) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ProviderError("model did not return JSON")
    try:
        data = json.loads(m.group(0))
    except ValueError as exc:
        raise ProviderError(f"invalid JSON from model: {exc}") from exc
    out: dict = {"scores": {}, "factors": {}}
    for key in ("hook", "engagement", "context", "payoff", "standalone"):  # older five-criterion answers
        try:
            out["scores"][key] = max(0.0, min(10.0, float(data.get(key, 5))))
        except (TypeError, ValueError):
            out["scores"][key] = 5.0
    for key in AI_FACTORS:  # only the factors the model actually returned
        try:
            if data.get(key) is not None:
                out["factors"][key] = max(0.0, min(10.0, float(data[key])))
        except (TypeError, ValueError):
            pass
    cat = str(data.get("category") or "").strip()
    out["category"] = next((c for c in CATEGORIES if c.lower() == cat.lower()), "")
    out["title"] = str(data.get("title") or "").strip().strip('"')[:90]
    out["hook_text"] = str(data.get("hook_text") or "").strip().strip('"')[:140]
    alts = data.get("alt_hooks") or []
    out["alt_hooks"] = [str(a).strip().strip('"')[:140] for a in alts if str(a).strip()][:3] \
        if isinstance(alts, list) else []
    tags = data.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.replace(",", " ").split()
    out["hashtags"] = ["#" + re.sub(r"[^\w]", "", str(t)) for t in tags if re.sub(r"[^\w]", "", str(t))][:6]
    try:
        s0 = int(data.get("start_sentence", 0))
        s1 = int(data.get("end_sentence", n_sentences - 1))
        if 0 <= s0 <= s1 < n_sentences:
            out["range"] = (s0, s1)
    except (TypeError, ValueError):
        pass
    out["reason"] = str(data.get("reason") or "").strip()[:240]
    return out


def _ollama(settings: dict, prompt: str) -> str:
    url = settings.get("ollama_url", "http://localhost:11434").rstrip("/") + "/api/chat"
    body = {
        "model": settings.get("ollama_model") or "llama3.1:8b",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_ctx": 4096},
    }
    r = httpx.post(url, json=body, timeout=180)
    if r.status_code != 200:
        raise ProviderError(f"Ollama error {r.status_code}: {r.text[:200]}")
    return r.json().get("message", {}).get("content", "")


def _openai_compatible(settings: dict, prompt: str) -> str:
    base = (settings.get("openai_url") or "http://localhost:1234/v1").rstrip("/")
    headers = {}
    if settings.get("openai_api_key"):
        headers["Authorization"] = f"Bearer {settings['openai_api_key']}"
    body = {
        "model": settings.get("openai_model") or "local-model",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=180)
    if r.status_code != 200:
        raise ProviderError(f"OpenAI-compatible server error {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


def _anthropic(settings: dict, prompt: str) -> str:
    try:
        import anthropic
    except ImportError as exc:
        raise ProviderError("The 'anthropic' package is not installed (pip install anthropic)") from exc
    key = settings.get("anthropic_api_key") or None  # None -> SDK reads ANTHROPIC_API_KEY / ant profile
    client = anthropic.Anthropic(api_key=key, max_retries=2, timeout=120)
    model = settings.get("anthropic_model") or "claude-opus-5"
    kwargs = dict(
        model=model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    if not model.startswith("claude-haiku"):
        kwargs["output_config"] = {"effort": "low"}  # scoring is a light task
    try:
        try:
            # Server-side refusal fallback (routes a declined request to a fallback model).
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                               **kwargs)
        except anthropic.BadRequestError:
            resp = client.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        raise ProviderError("Anthropic API key is invalid") from exc
    except anthropic.NotFoundError as exc:
        raise ProviderError(f"Unknown Anthropic model '{model}'") from exc
    except anthropic.RateLimitError as exc:
        raise ProviderError("Anthropic rate limit reached") from exc
    except anthropic.APIStatusError as exc:
        raise ProviderError(f"Anthropic API error {exc.status_code}") from exc
    except anthropic.APIConnectionError as exc:
        raise ProviderError("Could not reach the Anthropic API") from exc
    if resp.stop_reason == "refusal":
        raise ProviderError("The model declined to score this clip")
    return "".join(b.text for b in resp.content if b.type == "text")


def _nvidia(settings: dict, prompt: str) -> str:
    """Optional NVIDIA-hosted model (pipeline/nvidia.py): its own guards, budget and fallback to local analysis."""
    from . import nvidia

    try:
        return nvidia.complete(settings, SYSTEM_PROMPT, prompt, task=str(settings.get("_ai_task") or "clip_scoring"),
                               unattended=settings.get("origin") == "autopilot" or bool(settings.get("_unattended")))
    except nvidia.NvidiaUnavailable as exc:
        raise ProviderError(str(exc)) from exc


PROVIDERS = {"ollama": _ollama, "openai_compatible": _openai_compatible, "anthropic": _anthropic, "nvidia": _nvidia}
LOCAL_PROVIDERS = {"ollama", "openai_compatible"}


def provider_label(settings: dict) -> str:
    p = settings.get("ai_provider", "heuristic")
    if p == "ollama":
        return f"Ollama {settings.get('ollama_model')}"
    if p == "openai_compatible":
        return f"Local server {settings.get('openai_model') or ''}".strip()
    if p == "anthropic":
        return f"Claude {settings.get('anthropic_model')}"
    if p == "nvidia":
        mode = "production" if settings.get("nvidia_mode") == "production" else "development"
        return f"NVIDIA {settings.get('nvidia_model')} ({mode})"
    return "Local heuristic"


def complete(settings: dict, prompt: str, *, unattended: bool = False, task: str = "") -> str:
    """One JSON-answer request to the configured provider (raises ProviderError in heuristic mode or on failure).
    `unattended`: Autopilot work nobody started by hand (a development-only cloud provider is not used for it)."""
    provider = settings.get("ai_provider", "heuristic")
    if unattended or task:
        settings = {**settings, "_unattended": unattended or bool(settings.get("_unattended")), "_ai_task": task}
    fn = PROVIDERS.get(provider)
    if fn is None:
        raise ProviderError("heuristic mode")
    try:
        if provider in LOCAL_PROVIDERS:  # a local model shares the GPU with Whisper: one heavy GPU job at a time
            from .. import gpu

            try:
                with gpu.manager.heavy("local AI model", str(settings.get("ollama_model") if provider == "ollama"
                                                             else settings.get("openai_model") or "local model"),
                                       max_wait_s=900):
                    return fn(settings, prompt)
            except gpu.GpuBusy as exc:
                raise ProviderError(str(exc)) from exc
        return fn(settings, prompt)
    except httpx.HTTPError as exc:
        raise ProviderError(f"{provider} is not reachable: {exc}") from exc


def evaluate(settings: dict, video_name: str, sentences: list[str], context_before: str,
             duration: float) -> dict:
    text = complete(settings, build_prompt(video_name, sentences, context_before, duration))
    return parse_response(text, len(sentences))


def check_provider(settings: dict) -> dict:
    """Lightweight availability probe for the Settings page."""
    provider = settings.get("ai_provider", "heuristic")
    try:
        if provider == "ollama":
            r = httpx.get(settings.get("ollama_url", "http://localhost:11434").rstrip("/") + "/api/tags", timeout=3)
            models = [m.get("name") for m in r.json().get("models", [])]
            ok = settings.get("ollama_model") in models or any(
                str(m).split(":")[0] == str(settings.get("ollama_model")).split(":")[0] for m in models)
            return {"ok": ok, "detail": "model ready" if ok else
                    f"Ollama is running but '{settings.get('ollama_model')}' is not pulled", "models": models}
        if provider == "openai_compatible":
            base = (settings.get("openai_url") or "").rstrip("/")
            r = httpx.get(f"{base}/models", timeout=3)
            models = [m.get("id") for m in r.json().get("data", [])]
            return {"ok": r.status_code == 200, "detail": "server reachable", "models": models}
        if provider == "nvidia":
            from . import nvidia

            v = nvidia.view(settings)
            return {"ok": not v["problems"], "detail": v["problems"][0] if v["problems"] else
                    "Set up. Use Check connection or Run small AI test in Settings → Integrations."}
        if provider == "anthropic":
            try:
                import anthropic  # noqa: F401
            except ImportError:
                return {"ok": False, "detail": "pip install anthropic"}
            has_key = bool(settings.get("anthropic_api_key"))
            return {"ok": has_key, "detail": "API key set (paid usage)" if has_key else
                    "No API key saved (the SDK may still use ANTHROPIC_API_KEY)"}
        return {"ok": True, "detail": "Offline heuristic scoring (no AI model needed)"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"not reachable: {exc.__class__.__name__}"}

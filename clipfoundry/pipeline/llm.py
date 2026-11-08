"""Optional Stage 2 AI providers.

* builtin            - the built-in model (builtin_ai.py): llama.cpp and a free model ClipForge downloads and runs on
                       this computer (free)
* ollama             - local LLM via http://localhost:11434 (free)
* openai_compatible  - any OpenAI-style server: LM Studio, llama.cpp, vLLM on this computer (free), or an online
                       service you have a key for, such as the free tiers of Google Gemini, Groq or OpenRouter
                       (ai_setup.PRESETS)
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


def build_prompt(video_name: str, sentences: list[str], context_before: str, duration: float,
                 priorities: list[str] | None = None) -> str:
    numbered = "\n".join(f"[{k}] {s}" for k, s in enumerate(sentences))
    ctx = f'Context right before the clip (NOT part of the clip): "{context_before}"\n' if context_before else ""
    # Only fixed factor names leave this PC. Raw Brain notes, example media and private paths are never sent.
    supported = ("hook", "opening", "curiosity", "emotion", "density", "payoff", "standalone", "pacing",
                 "uniqueness", "clarity", "retention")
    selected = [key for key in supported if key in (priorities or [])]
    guidance = ("Saved editing priorities: " + ", ".join(selected) + ". Favor ranges that satisfy these priorities "
                "while preserving complete context and the payoff. Keep scores honest; these are editing "
                "preferences, never source facts.\n") if selected else ""
    from ..brain import knowhow

    return (
        guidance + knowhow.principles("clips") + "\n" + f"Source video: {video_name}\n"
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


def _system(settings: dict) -> str:
    return str(settings.get("_system") or SYSTEM_PROMPT)


def _timeout(settings: dict) -> float:
    """Seconds to wait for a local model's answer (`complete(timeout=...)`; 180 by default)."""
    return float(settings.get("_timeout") or 180)


def _ollama(settings: dict, prompt: str) -> str:
    url = settings.get("ollama_url", "http://localhost:11434").rstrip("/") + "/api/chat"
    body = {
        "model": settings.get("ollama_model") or "llama3.1:8b",
        "messages": [{"role": "system", "content": _system(settings)}, {"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_ctx": int(settings.get("_num_ctx") or 4096),
                    **({"num_predict": int(settings["_max_tokens"])} if settings.get("_max_tokens") else {})},
    }
    r = httpx.post(url, json=body, timeout=_timeout(settings))
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
        "messages": [{"role": "system", "content": _system(settings)}, {"role": "user", "content": prompt}],
        "temperature": 0.2,
        **({"max_tokens": int(settings["_max_tokens"])} if settings.get("_max_tokens") else {}),
    }
    r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=_timeout(settings))
    if r.status_code == 429:
        raise ProviderError("The AI service's free limit is used up for now (rate limit). Try again later.")
    if r.status_code in (401, 403):
        raise ProviderError("The AI service refused the API key. Check it in Settings → ClipForge AI.")
    if r.status_code != 200:
        raise ProviderError(f"OpenAI-compatible server error {r.status_code}: {r.text[:200]}")
    try:
        return r.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ProviderError("The AI service sent an answer in an unexpected shape.") from exc


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
        system=_system(settings),
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


def _builtin(settings: dict, prompt: str) -> str:
    from .. import builtin_ai

    try:
        extra = {k[1:]: settings[k] for k in ("_json_schema", "_images") if settings.get(k)}
        return builtin_ai.chat(settings, _system(settings), prompt, timeout=_timeout(settings),
                               json_object=bool(settings.get("_json_object")),
                               max_tokens=int(settings.get("_max_tokens") or 0) or None, **extra)
    except builtin_ai.BuiltinError as exc:
        raise ProviderError(str(exc)) from exc


def _nvidia(settings: dict, prompt: str) -> str:
    """Optional NVIDIA-hosted model (pipeline/nvidia.py): its own guards, budget and fallback to local analysis."""
    from . import nvidia

    try:
        return nvidia.complete(settings, _system(settings), prompt,
                               task=str(settings.get("_ai_task") or "clip_scoring"),
                               unattended=settings.get("origin") == "autopilot" or bool(settings.get("_unattended")))
    except nvidia.NvidiaUnavailable as exc:
        raise ProviderError(str(exc)) from exc


PROVIDERS = {"builtin": _builtin, "ollama": _ollama, "openai_compatible": _openai_compatible, "anthropic": _anthropic,
             "nvidia": _nvidia}
LOCAL_PROVIDERS = {"builtin", "ollama", "openai_compatible"}


def provider_label(settings: dict) -> str:
    p = settings.get("ai_provider", "heuristic")
    if p == "builtin":
        from .. import builtin_ai

        return builtin_ai.label(settings)
    if p == "ollama":
        return f"Ollama {settings.get('ollama_model')}"
    if p == "openai_compatible":
        from .. import ai_setup

        preset = ai_setup.preset_for_url(settings.get("openai_url") or "")
        name = preset["name"] if preset else "Local server"
        return f"{name} {settings.get('openai_model') or ''}".strip()
    if p == "anthropic":
        return f"Claude {settings.get('anthropic_model')}"
    if p == "nvidia":
        mode = "production" if settings.get("nvidia_mode") == "production" else "development"
        return f"NVIDIA {settings.get('nvidia_model')} ({mode})"
    return "Local heuristic"


def is_local(settings: dict, provider: str | None = None) -> bool:
    """True when the provider runs on this computer (a localhost address)."""
    from urllib.parse import urlparse

    provider = provider or settings.get("ai_provider", "heuristic")
    if provider == "builtin":
        return True  # always 127.0.0.1, started by ClipForge
    if provider == "ollama":
        url = settings.get("ollama_url") or "http://localhost:11434"
    elif provider == "openai_compatible":
        url = settings.get("openai_url") or "http://localhost:1234/v1"
    else:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


def _strip_thinking(text: str) -> str:
    """Some local models write their reasoning in <think> tags before the answer; only the answer is read."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def complete(settings: dict, prompt: str, *, unattended: bool = False, task: str = "", system: str | None = None,
             num_ctx: int | None = None, timeout: float | None = None, json_object: bool = False,
             max_tokens: int | None = None, json_schema: dict | None = None, images: list[str] | None = None) -> str:
    """One JSON-answer request to the configured provider (raises ProviderError in heuristic mode or on failure).
    `unattended`: Autopilot work nobody started by hand (a development-only cloud provider is not used for it).
    `system` replaces the clip-scoring instructions; `num_ctx` asks a local Ollama model for a larger context;
    `timeout` is how long a local model may take; `json_object` makes the built-in model answer with one JSON object;
    `max_tokens` caps the answer's length (the built-in model, Ollama and OpenAI-compatible servers); `json_schema`
    makes the built-in model's answer follow a JSON schema exactly (other providers get the prompt's instructions);
    `images` are base64 data URLs the built-in model looks at (its vision part; other providers ignore them)."""
    provider = settings.get("ai_provider", "heuristic")
    if unattended or task or system or num_ctx or timeout or json_object or max_tokens or json_schema or images:
        settings = {**settings, "_unattended": unattended or bool(settings.get("_unattended")), "_ai_task": task,
                    **({"_system": system} if system else {}), **({"_num_ctx": int(num_ctx)} if num_ctx else {}),
                    **({"_timeout": float(timeout)} if timeout else {}), **({"_json_object": True} if json_object else {}),
                    **({"_max_tokens": int(max_tokens)} if max_tokens else {}),
                    **({"_json_schema": json_schema} if json_schema else {}), **({"_images": images} if images else {})}
    fn = PROVIDERS.get(provider)
    if fn is None:
        raise ProviderError("heuristic mode")
    try:
        if provider in LOCAL_PROVIDERS and is_local(settings, provider):
            # a local model shares the GPU with Whisper: one heavy GPU job at a time
            from .. import gpu

            try:
                with gpu.manager.heavy("local AI model", provider_label(settings) if provider == "builtin" else str(
                        settings.get("ollama_model") if provider == "ollama" else
                        settings.get("openai_model") or "local model"), max_wait_s=900):
                    return _strip_thinking(fn(settings, prompt))
            except gpu.GpuBusy as exc:
                raise ProviderError(str(exc)) from exc
        return _strip_thinking(fn(settings, prompt))
    except httpx.HTTPError as exc:
        raise ProviderError(f"{provider} is not reachable: {exc}") from exc


# ------------------------------------------------------------------ conversations (ClipForge AI's chat)
class Canceled(ProviderError):
    """The person stopped the answer while it was being written."""


def _turns(messages: list[dict]) -> list[dict]:
    """The exchange as alternating owner/assistant turns, starting with the owner (what every provider accepts):
    other roles are dropped, empty turns skipped, two turns in a row by the same side joined."""
    out: list[dict] = []
    for m in messages:
        role = "assistant" if m.get("role") == "assistant" else "user" if m.get("role") == "user" else ""
        text = str(m.get("content") or "").strip()
        if not role or not text:
            continue
        if out and out[-1]["role"] == role:
            out[-1] = {"role": role, "content": out[-1]["content"] + "\n\n" + text}
        else:
            out.append({"role": role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _said(err) -> str:
    """An error a server sent in the middle of an answer, as words."""
    return str((err.get("message") if isinstance(err, dict) else None) or err)[:200]


def _sse(r: httpx.Response, on_text, cancel, deadline: float, timeout: float) -> str:
    """The text of an OpenAI-style streamed answer (data: lines), reported as it grows."""
    import time

    text = ""
    for line in r.iter_lines():
        if cancel and cancel():
            raise Canceled("Stopped.")
        if time.monotonic() > deadline:
            raise ProviderError(f"The model took longer than {int(timeout)} seconds.")
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if not isinstance(chunk, dict):
            continue
        if chunk.get("error"):  # the service failed in the middle of the answer (OpenRouter says it this way)
            raise ProviderError(f"OpenAI-compatible server error: {_said(chunk['error'])}")
        for choice in chunk.get("choices") or []:
            piece = (choice.get("delta") or {}).get("content") or ""
            if piece:
                text += piece
                on_text(text)
    return text


def _conv_builtin(settings: dict, system: str, turns: list[dict], o: dict) -> str:
    from .. import builtin_ai

    try:
        return builtin_ai.converse(settings, [{"role": "system", "content": system}, *turns], timeout=o["timeout"],
                                   json_object=o["json_object"], json_schema=o["json_schema"],
                                   max_tokens=o["max_tokens"], temperature=o["temperature"], on_text=o["on_text"],
                                   cancel=o["cancel"])
    except builtin_ai.Canceled as exc:
        raise Canceled(str(exc)) from exc
    except builtin_ai.BuiltinError as exc:
        raise ProviderError(str(exc)) from exc


def _conv_ollama(settings: dict, system: str, turns: list[dict], o: dict) -> str:
    import time

    url = settings.get("ollama_url", "http://localhost:11434").rstrip("/") + "/api/chat"
    body: dict = {"model": settings.get("ollama_model") or "llama3.1:8b",
                  "messages": [{"role": "system", "content": system}, *turns], "stream": bool(o["on_text"]),
                  "options": {"temperature": o["temperature"], "num_ctx": int(o["num_ctx"] or 8192),
                              **({"num_predict": int(o["max_tokens"])} if o["max_tokens"] else {})}}
    if o["json_schema"]:
        body["format"] = o["json_schema"]
    elif o["json_object"]:
        body["format"] = "json"
    if not o["on_text"]:
        r = httpx.post(url, json=body, timeout=o["timeout"])
        if r.status_code != 200:
            raise ProviderError(f"Ollama error {r.status_code}: {r.text[:200]}")
        try:
            return str((r.json().get("message") or {}).get("content") or "")
        except (AttributeError, ValueError) as exc:
            raise ProviderError("Ollama sent an answer in an unexpected shape.") from exc
    deadline, text = time.monotonic() + o["timeout"], ""
    with httpx.stream("POST", url, json=body, timeout=httpx.Timeout(o["timeout"], connect=10.0)) as r:
        if r.status_code != 200:
            r.read()
            raise ProviderError(f"Ollama error {r.status_code}: {r.text[:200]}")
        for line in r.iter_lines():
            if o["cancel"] and o["cancel"]():
                raise Canceled("Stopped.")
            if time.monotonic() > deadline:
                raise ProviderError(f"The model took longer than {int(o['timeout'])} seconds.")
            try:
                chunk = json.loads(line) if line.strip() else {}
            except ValueError:
                continue
            if not isinstance(chunk, dict):
                continue
            if chunk.get("error"):  # Ollama failed in the middle of the answer (out of memory, a crashed runner)
                raise ProviderError(f"Ollama error: {_said(chunk['error'])}")
            piece = (chunk.get("message") or {}).get("content") or ""
            if piece:
                text += piece
                o["on_text"](text)
            if chunk.get("done"):
                break
    return text


def _conv_openai(settings: dict, system: str, turns: list[dict], o: dict) -> str:
    import time

    base = (settings.get("openai_url") or "http://localhost:1234/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {settings['openai_api_key']}"} if settings.get("openai_api_key") else {}
    body: dict = {"model": settings.get("openai_model") or "local-model", "temperature": o["temperature"],
                  "messages": [{"role": "system", "content": system}, *turns],
                  **({"max_tokens": int(o["max_tokens"])} if o["max_tokens"] else {})}
    if o["json_schema"]:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": o["json_schema"]}}
    elif o["json_object"]:
        body["response_format"] = {"type": "json_object"}

    def refused(r: httpx.Response) -> None:
        if r.status_code == 429:
            raise ProviderError("The AI service's free limit is used up for now (rate limit). Try again later.")
        if r.status_code in (401, 403):
            raise ProviderError("The AI service refused the API key. Check it in Settings → ClipForge AI.")
        if r.status_code != 200:
            raise ProviderError(f"OpenAI-compatible server error {r.status_code}: {r.text[:200]}")

    for attempt in (1, 2):  # a server that does not know response_format is asked again without it
        if not o["on_text"]:
            r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=o["timeout"])
            if r.status_code in (400, 422) and attempt == 1 and "response_format" in body:
                body.pop("response_format")
                continue
            refused(r)
            try:
                return r.json()["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ProviderError("The AI service sent an answer in an unexpected shape.") from exc
        with httpx.stream("POST", f"{base}/chat/completions", json={**body, "stream": True}, headers=headers,
                          timeout=httpx.Timeout(o["timeout"], connect=10.0)) as r:
            if r.status_code != 200:
                r.read()
                if r.status_code in (400, 422) and attempt == 1 and "response_format" in body:
                    body.pop("response_format")
                    continue
                refused(r)
            return _sse(r, o["on_text"], o["cancel"], time.monotonic() + o["timeout"], o["timeout"])
    raise ProviderError("The AI service did not answer.")


def _conv_anthropic(settings: dict, system: str, turns: list[dict], o: dict) -> str:
    try:
        import anthropic
    except ImportError as exc:
        raise ProviderError("The 'anthropic' package is not installed (pip install anthropic)") from exc
    client = anthropic.Anthropic(api_key=settings.get("anthropic_api_key") or None, max_retries=2,
                                 timeout=o["timeout"])
    model = settings.get("anthropic_model") or "claude-opus-5"
    try:
        resp = client.messages.create(model=model, max_tokens=int(o["max_tokens"] or 2000), system=system,
                                      messages=turns)
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
        raise ProviderError("The model declined to answer")
    return "".join(b.text for b in resp.content if b.type == "text")


def _conv_flat(settings: dict, system: str, turns: list[dict], o: dict) -> str:
    """A provider that takes one prompt (NVIDIA): the conversation written out, the newest message last."""
    lines = [("The owner" if t["role"] == "user" else "You") + ": " + t["content"] for t in turns[:-1]]
    prompt = (("The conversation so far:\n" + "\n\n".join(lines) + "\n\n") if lines else "") + \
        "The owner's new message: " + (turns[-1]["content"] if turns else "")
    fn = PROVIDERS[settings.get("ai_provider", "heuristic")]
    flat = {**settings, "_system": system, "_ai_task": o["task"], "_timeout": o["timeout"],
            **({"_max_tokens": int(o["max_tokens"])} if o["max_tokens"] else {}),
            **({"_json_object": True} if o["json_object"] or o["json_schema"] else {})}
    return fn(flat, prompt)


CONVERSE = {"builtin": _conv_builtin, "ollama": _conv_ollama, "openai_compatible": _conv_openai,
            "anthropic": _conv_anthropic, "nvidia": _conv_flat}


def converse(settings: dict, messages: list[dict], *, system: str = "", task: str = "chat", json_object: bool = False,
             json_schema: dict | None = None, max_tokens: int | None = None, timeout: float | None = None,
             temperature: float = 0.4, num_ctx: int | None = None, on_text=None, cancel=None) -> str:
    """A conversation with the configured provider: `messages` is the exchange so far, oldest first
    ([{"role": "user" | "assistant", "content": str}]; the instructions go in `system`). Returns the answer's text,
    without any <think> part. Raises ProviderError in heuristic mode or on failure, and Canceled when `cancel()`
    returned True while the answer streamed.

    `json_schema` makes the built-in model, Ollama and servers that support it answer in exactly that shape (others
    get `json_object` or the instructions alone); `on_text(text_so_far)` streams the answer as it is written (the
    built-in model, Ollama and OpenAI-style servers; the others answer all at once and never call it); `timeout`
    bounds the whole answer, and a model on this computer waits for the GPU at most that long; `cancel()` also stops
    that wait; `num_ctx` is Ollama's context size."""
    provider = settings.get("ai_provider", "heuristic")
    fn = CONVERSE.get(provider)
    if fn is None or provider not in PROVIDERS:
        raise ProviderError("heuristic mode")
    turns = _turns(messages)
    if not turns:
        raise ProviderError("Nothing to answer.")
    o = {"task": task, "json_object": json_object, "json_schema": json_schema, "max_tokens": max_tokens,
         "timeout": float(timeout or 180), "temperature": float(temperature), "num_ctx": num_ctx,
         "on_text": on_text, "cancel": cancel}
    if provider in ("anthropic", "nvidia"):
        o["on_text"] = None  # answered at once; the caller shows it when it arrives
    try:
        if provider in LOCAL_PROVIDERS and is_local(settings, provider):
            from .. import gpu  # a local model shares the GPU with Whisper: one heavy GPU job at a time
            from .common import Cancelled

            try:
                with gpu.manager.heavy("local AI model", provider_label(settings) if provider == "builtin" else str(
                        settings.get("ollama_model") if provider == "ollama" else
                        settings.get("openai_model") or "local model"), cancelled=cancel,
                        max_wait_s=min(900.0, o["timeout"])):
                    return _strip_thinking(fn(settings, system, turns, o))
            except gpu.GpuBusy as exc:
                raise ProviderError(str(exc)) from exc
            except Cancelled as exc:  # stopped while waiting for the GPU
                raise Canceled("Stopped.") from exc
        return _strip_thinking(fn(settings, system, turns, o))
    except httpx.HTTPError as exc:
        raise ProviderError(f"{provider} is not reachable: {exc}") from exc


def evaluate(settings: dict, video_name: str, sentences: list[str], context_before: str,
             duration: float) -> dict:
    prompt = build_prompt(video_name, sentences, context_before, duration, settings.get("brain_priorities"))
    text = complete(settings, prompt)
    return parse_response(text, len(sentences))


def check_provider(settings: dict) -> dict:
    """Lightweight availability probe for the Settings page."""
    provider = settings.get("ai_provider", "heuristic")
    try:
        if provider == "builtin":
            from .. import builtin_ai

            if not builtin_ai.platform_key():
                return {"ok": False, "detail": "The built-in model does not run on this kind of computer", "models": []}
            if not builtin_ai.ready(settings):
                return {"ok": False, "detail": "Not set up yet: choose a level and download it", "models": []}
            return {"ok": True, "detail": f"Ready: {builtin_ai.label(settings)}, on this computer", "models": []}
        if provider == "ollama":
            r = httpx.get(settings.get("ollama_url", "http://localhost:11434").rstrip("/") + "/api/tags", timeout=3)
            models = [m.get("name") for m in r.json().get("models", [])]
            ok = settings.get("ollama_model") in models or any(
                str(m).split(":")[0] == str(settings.get("ollama_model")).split(":")[0] for m in models)
            return {"ok": ok, "detail": "model ready" if ok else
                    f"Ollama is running but '{settings.get('ollama_model')}' is not pulled", "models": models}
        if provider == "openai_compatible":
            base = (settings.get("openai_url") or "").rstrip("/")
            headers = {"Authorization": f"Bearer {settings['openai_api_key']}"} if settings.get("openai_api_key") \
                else {}
            r = httpx.get(f"{base}/models", headers=headers, timeout=8 if not is_local(settings, provider) else 3)
            if r.status_code in (401, 403):
                return {"ok": False, "detail": "The service refused the API key", "models": []}
            models = [str(m.get("id") or "").removeprefix("models/") for m in (r.json().get("data") or [])
                      if isinstance(m, dict)] if r.status_code == 200 else []
            model = str(settings.get("openai_model") or "")
            if r.status_code != 200:
                return {"ok": False, "detail": f"The server answered {r.status_code}", "models": []}
            if model and models and model.removeprefix("models/") not in models:
                return {"ok": False, "detail": f"Reachable, but “{model}” is not one of its models; pick one",
                        "models": models}
            return {"ok": True, "detail": "Reachable" + (f"; using {model}" if model else "; pick a model"),
                    "models": models}
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

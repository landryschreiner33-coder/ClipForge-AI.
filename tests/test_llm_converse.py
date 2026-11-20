"""llm.converse: the conversation call behind ClipForge AI's chat, with every kind of model it can use.

The model servers on this computer (Ollama, and OpenAI-style servers such as LM Studio) are played by a small web
server that answers from a script and remembers every request it got; the online services (Anthropic, NVIDIA) and the
built-in model are replaced by stand-ins. Nothing leaves the computer.
"""
from __future__ import annotations

import json
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

TALK = [{"role": "user", "content": "Make the intro shorter"},
        {"role": "assistant", "content": "Which video?"},
        {"role": "user", "content": "The hike one"}]
SCHEMA = {"type": "object", "properties": {"say": {"type": "string"}}, "required": ["say"]}


# ------------------------------------------------------------------ a model server on this computer
class Stream:
    """A streamed answer: its lines, sent `pause` seconds apart (`sse`: OpenAI-style events; else Ollama's lines)."""

    def __init__(self, lines: list[str], *, sse: bool = False, pause: float = 0.0):
        self.lines, self.sse, self.pause = lines, sse, pause


class _Model(BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401
        pass

    def do_POST(self):  # noqa: N802
        srv = self.server
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        srv.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                             "body": body})
        answer = srv.script.pop(0) if srv.script else (500, {"error": "no answer left in the test's script"})
        try:
            if isinstance(answer, Stream):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream" if answer.sse else "application/x-ndjson")
                self.end_headers()
                for n, line in enumerate(answer.lines):
                    if n and answer.pause:
                        time.sleep(answer.pause)
                    self.wfile.write(line.encode() + (b"\n\n" if answer.sse else b"\n"))
                    self.wfile.flush()
                    srv.sent += 1
                return
            code, out = answer
            raw = out.encode() if isinstance(out, str) else json.dumps(out).encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain" if isinstance(out, str) else "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            srv.cut = True  # the app closed the connection: the model stops writing


@pytest.fixture()
def data(monkeypatch, tmp_path):
    """A data folder of the test's own (a local model takes the GPU lock, which is recorded there)."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


@pytest.fixture()
def model(data):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    srv.script, srv.requests, srv.sent, srv.cut = [], [], 0, False
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _ollama(srv, **extra) -> dict:
    return {"ai_provider": "ollama", "ollama_url": srv.url, "ollama_model": "qwen-test", **extra}


def _openai(srv, **extra) -> dict:
    return {"ai_provider": "openai_compatible", "openai_url": srv.url + "/v1", "openai_model": "local-test", **extra}


def _ollama_lines(*pieces: str, done: bool = True) -> list[str]:
    lines = [json.dumps({"model": "qwen-test", "message": {"role": "assistant", "content": p}, "done": False})
             for p in pieces]
    if done:
        lines.append(json.dumps({"model": "qwen-test", "message": {"role": "assistant", "content": ""},
                                 "done": True, "done_reason": "stop"}))
    return lines


def _events(*pieces: str, done: bool = True) -> list[str]:
    lines = ["data: " + json.dumps({"choices": [{"index": 0, "delta": {"role": "assistant"}}]})]
    lines += ["data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": p}, "finish_reason": None}]})
              for p in pieces]
    if done:
        lines += ["data: " + json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
                  "data: [DONE]"]
    return lines


def _wait_for(check, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if check():
            return True
        time.sleep(0.02)
    return False


# ------------------------------------------------------------------ the conversation itself
def test_the_conversation_alternates_and_starts_with_the_owner():
    from clipfoundry.pipeline import llm

    messages = [
        {"role": "assistant", "content": "Hello, I am ClipForge AI."},  # an answer before the owner said anything
        {"role": "system", "content": "be nice"},                       # instructions go in `system`, not here
        {"role": "user", "content": "  first  "},
        {"role": "user", "content": "second"},                          # the same side twice: one turn
        {"role": "tool", "content": "a tool's output"},
        {"role": "assistant", "content": "   "},                        # empty turns are skipped
        {"role": "assistant", "content": "answer one"},
        {"role": "assistant", "content": "answer two"},
        {"role": "user", "content": None},
        {"role": "user", "content": "third"},
    ]
    assert llm._turns(messages) == [{"role": "user", "content": llm.EARLIER},  # the opening answer is kept
                                    {"role": "assistant", "content": "Hello, I am ClipForge AI."},
                                    {"role": "user", "content": "first\n\nsecond"},
                                    {"role": "assistant", "content": "answer one\n\nanswer two"},
                                    {"role": "user", "content": "third"}]
    assert messages[2]["content"] == "  first  "  # the caller's list is left as it was
    assert llm._turns([{"role": "user", "content": "a"}, {"role": "assistant", "content": ""},
                       {"role": "user", "content": "b"}]) == [{"role": "user", "content": "a\n\nb"}]
    assert llm._turns([{"role": "assistant", "content": "only me"}]) == []  # nothing of the owner's to answer
    assert llm._turns([]) == []


def test_without_a_model_nothing_is_sent(monkeypatch):
    from clipfoundry.pipeline import llm

    def never(*a, **k):
        raise AssertionError("nothing may be sent")

    monkeypatch.setattr(llm.httpx, "post", never)
    monkeypatch.setattr(llm.httpx, "stream", never)
    for settings in ({"ai_provider": "heuristic"}, {}, {"ai_provider": "something else"}):
        with pytest.raises(llm.ProviderError, match="heuristic mode"):
            llm.converse(settings, TALK, system="S")
    with pytest.raises(llm.ProviderError, match="Nothing to answer"):
        llm.converse({"ai_provider": "ollama"}, [{"role": "assistant", "content": "only the AI spoke"}])


# ------------------------------------------------------------------ Ollama
def test_ollama_answers_the_whole_conversation(model):
    from clipfoundry.pipeline import llm

    model.script = [(200, {"message": {"role": "assistant", "content": '<think>hmm</think>{"say": "Done."}'}}),
                    (200, {"message": {"content": "two"}}), (200, {"message": {"content": "three"}})]
    got = llm.converse(_ollama(model), TALK, system="SYSTEM", json_schema=SCHEMA, max_tokens=300, temperature=0.2,
                       timeout=20)
    assert got == '{"say": "Done."}'  # the model's thinking is left out
    req = model.requests[0]
    assert req["path"] == "/api/chat"
    assert req["body"] == {"model": "qwen-test", "stream": False, "format": SCHEMA,
                           "messages": [{"role": "system", "content": "SYSTEM"}, *TALK],
                           "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": 300}}
    assert llm.converse(_ollama(model), TALK, json_object=True, num_ctx=4096) == "two"
    body = model.requests[1]["body"]
    assert body["format"] == "json" and body["options"] == {"temperature": 0.4, "num_ctx": 4096}
    assert llm.converse(_ollama(model), TALK) == "three"
    assert "format" not in model.requests[2]["body"]  # no reply shape asked: none sent


def test_ollama_streams_the_answer_as_it_is_written(model):
    from clipfoundry.pipeline import llm

    lines = _ollama_lines('{"say": "', "Hel", 'lo"}')
    lines[2:2] = ["", "not json", "[1, 2]"]  # blank or broken lines are skipped
    lines.append(json.dumps({"message": {"content": "after the end"}}))
    model.script = [Stream(lines)]
    seen: list[str] = []
    got = llm.converse(_ollama(model), TALK, system="S", json_schema=SCHEMA, on_text=seen.append)
    assert seen == ['{"say": "', '{"say": "Hel', '{"say": "Hello"}']
    assert got == '{"say": "Hello"}'
    assert model.requests[0]["body"]["stream"] is True and model.requests[0]["body"]["format"] == SCHEMA


def test_ollama_failures_are_said_in_plain_words(model):
    from clipfoundry.pipeline import llm

    model.script = [(500, "model 'qwen-test' not found"), (404, "no such model"), (200, "<html>not json</html>"),
                    (200, ["a list"]),
                    Stream(_ollama_lines("Half an ans", done=False) + [json.dumps({"error": "out of memory"})])]
    with pytest.raises(llm.ProviderError, match="Ollama error 500: model 'qwen-test' not found"):
        llm.converse(_ollama(model), TALK)
    with pytest.raises(llm.ProviderError, match="Ollama error 404: no such model"):
        llm.converse(_ollama(model), TALK, on_text=lambda t: None)
    for _ in range(2):  # an answer that is not Ollama's JSON
        with pytest.raises(llm.ProviderError, match="unexpected shape"):
            llm.converse(_ollama(model), TALK)
    seen: list[str] = []
    with pytest.raises(llm.ProviderError, match="out of memory"):  # Ollama stopped in the middle of the answer
        llm.converse(_ollama(model), TALK, on_text=seen.append)
    assert seen == ["Half an ans"]
    with pytest.raises(llm.ProviderError, match="ollama is not reachable"):
        llm.converse({"ai_provider": "ollama", "ollama_url": "http://127.0.0.1:9"}, TALK)


# ------------------------------------------------------------------ OpenAI-style servers
def test_an_openai_style_server_gets_the_reply_shape_and_the_key(model):
    from clipfoundry.pipeline import llm

    model.script = [(200, {"choices": [{"message": {"content": "<think>x</think>Plain words"}}]}),
                    (200, {"choices": [{"message": {"content": None}}]})]
    got = llm.converse(_openai(model, openai_api_key="sk-test"), TALK, system="SYS", json_schema=SCHEMA,
                       max_tokens=120, temperature=0.3)
    assert got == "Plain words"
    req = model.requests[0]
    assert req["path"] == "/v1/chat/completions" and req["headers"]["authorization"] == "Bearer sk-test"
    assert req["body"] == {"model": "local-test", "temperature": 0.3, "max_tokens": 120,
                           "messages": [{"role": "system", "content": "SYS"}, *TALK],
                           "response_format": {"type": "json_schema",
                                               "json_schema": {"name": "answer", "schema": SCHEMA}}}
    assert llm.converse(_openai(model), TALK, json_object=True) == ""
    req = model.requests[1]
    assert "authorization" not in req["headers"] and "max_tokens" not in req["body"]
    assert req["body"]["response_format"] == {"type": "json_object"}


def test_an_openai_style_server_streams_events(model):
    from clipfoundry.pipeline import llm

    lines = _events('{"say": ', '"Hi', ' there"}')
    lines[2:2] = [": keep-alive", "data: not json", "data: [1]", "event: ping"]  # ignored
    lines.append("data: " + json.dumps({"choices": [{"delta": {"content": "after the end"}}]}))
    model.script = [Stream(lines, sse=True)]
    seen: list[str] = []
    got = llm.converse(_openai(model), TALK, json_schema=SCHEMA, on_text=seen.append)
    assert seen == ['{"say": ', '{"say": "Hi', '{"say": "Hi there"}']
    assert got == '{"say": "Hi there"}'
    body = model.requests[0]["body"]
    assert body["stream"] is True and body["response_format"]["json_schema"]["schema"] == SCHEMA


@pytest.mark.parametrize("streamed", [False, True])
def test_a_server_that_refuses_the_reply_shape_is_asked_once_more_without_it(model, streamed):
    from clipfoundry.pipeline import llm

    ok = Stream(_events("All ", "good"), sse=True) if streamed else (200, {"choices": [{"message": {"content":
                                                                                                    "All good"}}]})
    model.script = [(400, {"error": {"message": "response_format is not supported"}}), ok]
    seen: list[str] = []
    got = llm.converse(_openai(model), TALK, system="S", json_schema=SCHEMA,
                       on_text=seen.append if streamed else None)
    assert got == "All good" and seen == (["All ", "All good"] if streamed else [])
    first, second = (r["body"] for r in model.requests)
    assert "response_format" in first and "response_format" not in second
    assert {k: v for k, v in first.items() if k != "response_format"} == second
    # asked again only once, and only when the reply shape could be the reason
    model.requests.clear()
    model.script = [(422, "bad request"), (400, "still bad")]
    with pytest.raises(llm.ProviderError, match="OpenAI-compatible server error 400: still bad"):
        llm.converse(_openai(model), TALK, json_object=True, on_text=seen.append if streamed else None)
    assert len(model.requests) == 2
    model.requests.clear()
    model.script = [(400, "context too long")]
    with pytest.raises(llm.ProviderError, match="error 400: context too long"):
        llm.converse(_openai(model), TALK, on_text=seen.append if streamed else None)
    assert len(model.requests) == 1


def test_openai_style_failures_are_said_in_plain_words(model):
    from clipfoundry.pipeline import llm

    model.script = [(401, "bad key"), (429, "slow down"), (200, {"choices": []}), (200, "not json"),
                    (403, "no"),
                    Stream(_events("Half", done=False) + ["data: " + json.dumps(
                        {"error": {"code": "server_error", "message": "Provider disconnected unexpectedly"},
                         "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "error"}]})], sse=True)]
    with pytest.raises(llm.ProviderError, match="refused the API key"):
        llm.converse(_openai(model, openai_api_key="sk-bad"), TALK)
    with pytest.raises(llm.ProviderError, match="rate limit"):
        llm.converse(_openai(model), TALK)
    for _ in range(2):
        with pytest.raises(llm.ProviderError, match="unexpected shape"):
            llm.converse(_openai(model), TALK)
    with pytest.raises(llm.ProviderError, match="refused the API key"):
        llm.converse(_openai(model), TALK, on_text=lambda t: None)
    seen: list[str] = []
    with pytest.raises(llm.ProviderError, match="Provider disconnected unexpectedly"):  # an error mid-answer
        llm.converse(_openai(model), TALK, on_text=seen.append)
    assert seen == ["Half"]


# ------------------------------------------------------------------ stopping and the time limit
@pytest.mark.parametrize("kind", ["ollama", "openai"])
def test_stop_ends_a_streamed_answer_and_closes_the_connection(model, kind):
    from clipfoundry.pipeline import llm

    pieces = [f"w{n} " for n in range(40)]
    model.script = [Stream(_ollama_lines(*pieces), pause=0.05) if kind == "ollama" else
                    Stream(_events(*pieces), sse=True, pause=0.05)]
    stop = threading.Event()
    seen: list[str] = []

    def on_text(text: str) -> None:
        seen.append(text)
        stop.set()  # the owner presses Stop as soon as the first words arrive

    settings = _ollama(model) if kind == "ollama" else _openai(model)
    with pytest.raises(llm.Canceled, match="Stopped"):
        llm.converse(settings, TALK, on_text=on_text, cancel=stop.is_set)
    assert seen == ["w0 "]
    assert _wait_for(lambda: model.cut), "the model was never told to stop writing"
    assert model.sent < 40


@pytest.mark.parametrize("kind", ["ollama", "openai"])
def test_a_streamed_answer_has_a_time_limit_for_the_whole_answer(model, kind):
    from clipfoundry.pipeline import llm

    pieces = [f"w{n} " for n in range(12)]
    model.script = [Stream(_ollama_lines(*pieces), pause=0.3) if kind == "ollama" else
                    Stream(_events(*pieces), sse=True, pause=0.3)]
    seen: list[str] = []
    t0 = time.monotonic()
    with pytest.raises(llm.ProviderError, match="took longer than 1 seconds"):
        llm.converse(_ollama(model) if kind == "ollama" else _openai(model), TALK, timeout=1.0,
                     on_text=seen.append)
    assert time.monotonic() - t0 < 2.5  # each piece came in time; the whole answer did not
    assert 0 < len(seen) < 12


def _hold_the_gpu(release: threading.Event) -> threading.Thread:
    """Another heavy job (a transcription) holds the GPU until `release` is set."""
    from clipfoundry import gpu

    held = threading.Event()

    def run():
        with gpu.manager.heavy("transcription", "talk.mp4"):
            held.set()
            release.wait(20)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    assert held.wait(5)
    return t


def test_stop_works_while_the_answer_waits_for_the_gpu(model):
    from clipfoundry.pipeline import llm

    release, stop = threading.Event(), threading.Event()
    holder = _hold_the_gpu(release)
    threading.Timer(0.3, stop.set).start()
    t0 = time.monotonic()
    try:
        with pytest.raises(llm.Canceled, match="Stopped"):
            llm.converse(_ollama(model), TALK, on_text=lambda t: None, cancel=stop.is_set, timeout=60)
        assert time.monotonic() - t0 < 3
    finally:
        release.set()
        holder.join(10)
    assert model.requests == []  # the model was never asked


def test_the_wait_for_the_gpu_counts_in_the_time_limit(model):
    from clipfoundry.pipeline import llm

    release = threading.Event()
    holder = _hold_the_gpu(release)
    t0 = time.monotonic()
    try:
        with pytest.raises(llm.ProviderError, match=r"The GPU stayed busy with transcription for 2 seconds\.$"):
            llm.converse(_ollama(model), TALK, timeout=1.5)
        assert time.monotonic() - t0 < 5
    finally:
        release.set()
        holder.join(10)
    assert model.requests == []
    model.script = [(200, {"message": {"content": "free again"}})]
    assert llm.converse(_ollama(model), TALK, timeout=5) == "free again"


def test_a_gpu_that_frees_partway_leaves_the_model_only_the_rest_of_the_time(model, monkeypatch):
    """The answer's time limit covers the wait for the GPU: the model gets what is left of it, never the whole time
    again (a chat during a transcription would otherwise think for twice its limit)."""
    from clipfoundry.pipeline import llm

    given: list[float] = []
    real = llm.CONVERSE["ollama"]

    def timed(settings, system, turns, o):
        given.append(o["timeout"])
        return real(settings, system, turns, o)

    monkeypatch.setitem(llm.CONVERSE, "ollama", timed)
    release = threading.Event()
    holder = _hold_the_gpu(release)
    threading.Timer(0.8, release.set).start()
    model.script = [(200, {"message": {"content": "after the wait"}})]
    t0 = time.monotonic()
    assert llm.converse(_ollama(model), TALK, timeout=3.0) == "after the wait"
    holder.join(10)
    assert len(given) == 1 and 1.0 < given[0] <= 3.0 - 0.7 and time.monotonic() - t0 < 3.0

    # freed with too little left to answer in: nothing is sent, and the owner reads why
    release = threading.Event()
    holder = _hold_the_gpu(release)
    threading.Timer(1.3, release.set).start()
    with pytest.raises(llm.ProviderError, match=r"^The graphics card was busy with other work for [12] of the 2 "
                                                r"seconds this answer had, so there was no time left to answer\."):
        llm.converse(_ollama(model), TALK, timeout=1.9)
    holder.join(10)
    assert len(given) == 1 and len(model.requests) == 1


def test_too_little_time_after_the_wait_is_said_plainly_and_a_slow_model_is_not_called_unreachable(model):
    """A model on this computer is asked only with a useful part of the time left (5 seconds, or a tenth of a long
    limit: it reads the prompt before its first word), and a model that is still too slow is said to be slow, with
    the time it had and how much of it went to waiting for the graphics card: never "not reachable"."""
    from clipfoundry import builtin_ai
    from clipfoundry.pipeline import llm

    assert [builtin_ai.answer_floor(t) for t in (300, 120, 60, 10, 2)] == [30, 12, 6, 5, 1]
    release = threading.Event()
    holder = _hold_the_gpu(release)
    threading.Timer(1.2, release.set).start()
    model.script = [Stream(['{"message": {"content": "one"}}', '{"message": {"content": "two"}}'], pause=2.5)]
    with pytest.raises(llm.ProviderError) as got:
        llm.converse(_ollama(model), TALK, timeout=3.0)
    holder.join(10)
    assert str(got.value) == "The model took longer than 3 seconds (1 of them waiting for the graphics card)."
    model.script = [Stream(['{"message": {"content": "one"}}', '{"message": {"content": "two"}}'], pause=2.0)]
    with pytest.raises(llm.ProviderError, match=r"^The model took longer than 1 seconds\.$"):
        llm.converse(_ollama(model), TALK, timeout=1.0)


# ------------------------------------------------------------------ online services and the built-in model
@pytest.fixture()
def claude(monkeypatch):
    """A stand-in for the Anthropic client: remembers how it was made and what it was asked."""
    import anthropic

    got = types.SimpleNamespace(made=[], asked=[], answer=None)

    class Client:
        def __init__(self, **kwargs):
            got.made.append(kwargs)
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            got.asked.append(kwargs)
            if isinstance(got.answer, BaseException):
                raise got.answer
            return got.answer

    monkeypatch.setattr(anthropic, "Anthropic", Client)
    return got


def _reply(*texts: str, stop: str = "end_turn"):
    blocks = [types.SimpleNamespace(type="thinking", thinking="private")]
    blocks += [types.SimpleNamespace(type="text", text=t) for t in texts]
    return types.SimpleNamespace(stop_reason=stop, content=blocks)


def test_anthropic_gets_the_conversation_as_alternating_messages(claude):
    import anthropic

    from clipfoundry.pipeline import llm

    claude.answer = _reply('{"say": "Sure', '."}')
    seen: list[str] = []
    messages = [{"role": "assistant", "content": "Hi!"}, *TALK[:1], {"role": "user", "content": "please"}, *TALK[1:]]
    got = llm.converse({"ai_provider": "anthropic", "anthropic_api_key": "sk-ant-test"}, messages, system="SYS",
                       json_schema=SCHEMA, timeout=30, on_text=seen.append)
    assert got == '{"say": "Sure."}'
    assert seen == []  # answered all at once, not streamed
    assert claude.made == [{"api_key": "sk-ant-test", "max_retries": 2, "timeout": 30.0}]
    assert claude.asked == [{"model": "claude-opus-5", "max_tokens": 2000, "system": "SYS",
                             "messages": [{"role": "user", "content": llm.EARLIER},
                                          {"role": "assistant", "content": "Hi!"},
                                          {"role": "user", "content": "Make the intro shorter\n\nplease"},
                                          *TALK[1:]]}]
    llm.converse({"ai_provider": "anthropic", "anthropic_model": "claude-haiku-5"}, TALK, max_tokens=300)
    assert claude.made[-1]["api_key"] is None  # no key saved: the SDK finds one itself
    assert claude.asked[-1]["model"] == "claude-haiku-5" and claude.asked[-1]["max_tokens"] == 300
    claude.answer = _reply("no", stop="refusal")
    with pytest.raises(llm.ProviderError, match="declined to answer"):
        llm.converse({"ai_provider": "anthropic"}, TALK)
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    claude.answer = anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)
    with pytest.raises(llm.ProviderError, match="Anthropic API key is invalid"):
        llm.converse({"ai_provider": "anthropic"}, TALK)
    claude.answer = anthropic.APIConnectionError(request=request)
    with pytest.raises(llm.ProviderError, match="Could not reach the Anthropic API"):
        llm.converse({"ai_provider": "anthropic"}, TALK)


def test_nvidia_gets_the_conversation_written_out(monkeypatch):
    from clipfoundry.pipeline import llm, nvidia

    calls: list[dict] = []

    def complete(settings, system, prompt, *, task="clip_scoring", unattended=False, job_id=""):
        calls.append({"settings": settings, "system": system, "prompt": prompt, "task": task,
                      "unattended": unattended})
        return '<think>private</think>{"say": "Cut it to 3 seconds."}'

    monkeypatch.setattr(nvidia, "complete", complete)
    seen: list[str] = []
    settings = {"ai_provider": "nvidia", "nvidia_api_key": "nv-test"}
    got = llm.converse(settings, TALK, system="SYS", task="chat", json_schema=SCHEMA, max_tokens=500, timeout=40,
                       on_text=seen.append)
    assert got == '{"say": "Cut it to 3 seconds."}' and seen == []
    call = calls[0]
    assert call["prompt"] == ("The conversation so far:\nThe owner: Make the intro shorter\n\nYou: Which video?\n\n"
                              "The owner's new message: The hike one")
    assert call["system"] == "SYS" and call["task"] == "chat" and call["unattended"] is False
    assert call["settings"]["_json_object"] is True and call["settings"]["_max_tokens"] == 500
    assert call["settings"]["_timeout"] == 40.0 and call["settings"]["nvidia_api_key"] == "nv-test"
    llm.converse(settings, [{"role": "user", "content": "hello"}], system="SYS")
    assert calls[1]["prompt"] == "The owner's new message: hello" and "_json_object" not in calls[1]["settings"]

    def unavailable(*a, **k):
        raise nvidia.NvidiaUnavailable("Today's NVIDIA budget is used up.", "budget")

    monkeypatch.setattr(nvidia, "complete", unavailable)
    with pytest.raises(llm.ProviderError, match="NVIDIA budget is used up"):
        llm.converse(settings, TALK, system="SYS")


def test_the_builtin_model_gets_the_system_text_first(data, monkeypatch):
    from clipfoundry import builtin_ai
    from clipfoundry.pipeline import llm

    calls: list[dict] = []

    def converse(settings, messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        if kwargs["on_text"]:
            kwargs["on_text"]('{"say": "Hi')
        return '{"say": "Hi"}'

    monkeypatch.setattr(builtin_ai, "converse", converse)
    seen: list[str] = []
    stop = lambda: False  # noqa: E731
    got = llm.converse({"ai_provider": "builtin"}, TALK, system="SYS", json_schema=SCHEMA, max_tokens=90,
                       timeout=12, temperature=0.1, on_text=seen.append, cancel=stop)
    assert got == '{"say": "Hi"}' and seen == ['{"say": "Hi']
    assert 11 < calls[0].pop("timeout") <= 12.0  # what is left of the 12 seconds after the wait for the GPU
    assert calls == [{"messages": [{"role": "system", "content": "SYS"}, *TALK],
                      "json_object": False, "json_schema": SCHEMA, "max_tokens": 90, "temperature": 0.1,
                      "on_text": seen.append, "cancel": stop, "limit": 12.0}]  # limit: the whole time, for its words

    def stopped(*a, **k):
        raise builtin_ai.Canceled("Stopped.")

    monkeypatch.setattr(builtin_ai, "converse", stopped)
    with pytest.raises(llm.Canceled):
        llm.converse({"ai_provider": "builtin"}, TALK)

    def broken(*a, **k):
        raise builtin_ai.BuiltinError("The built-in model is not set up yet.")

    monkeypatch.setattr(builtin_ai, "converse", broken)
    with pytest.raises(llm.ProviderError, match="not set up yet") as err:
        llm.converse({"ai_provider": "builtin"}, TALK)
    assert not isinstance(err.value, llm.Canceled)

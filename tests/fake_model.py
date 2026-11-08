"""A stand-in for llm.converse in ClipForge AI's tests (tests/test_clipforge_ai_*.py).

It answers from a script, one answer per call, and streams each answer through `on_text` the way a real provider
does: piece by piece, stopping with llm.Canceled as soon as `cancel()` says so. It records every call (the
conversation, the system prompt, the reply shape, the limits), and it can wait before answering (`ready`) or in the
middle of an answer (`flowing`), so a test can look at a chat while the answer is still being written. Nothing
leaves the computer.

An answer in the script is a dict (sent as JSON), a string (sent as it is), a list of strings (the pieces it streams
in), an exception (raised) or a function of the call that returns one of these.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

WS = "local"


def say(text: str = "", *calls: tuple[str, dict], ask: dict | None = None) -> dict:
    """One answer in the assistant's shape: {"say", "do": [{"tool", "args"}], "ask"}."""
    out: dict = {"say": text, "do": [{"tool": name, "args": args} for name, args in calls]}
    if ask:
        out["ask"] = ask
    return out


class FakeModel:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []
        self.ready = threading.Event()      # cleared: the next answer waits before its first piece
        self.flowing = threading.Event()    # cleared: an answer waits after its first piece
        self.started = threading.Event()    # set once an answer has streamed its first piece
        self.ready.set()
        self.flowing.set()
        self.pause_call: int | None = None  # only this call (0 = the first) waits for `flowing`
        self.checks_cancel = True           # False: like a provider that answers all at once (no stopping midway)
        self._lock = threading.Lock()

    def __call__(self, settings, messages, *, system="", task="chat", json_object=False, json_schema=None,
                 max_tokens=None, timeout=None, temperature=0.4, num_ctx=None, on_text=None, cancel=None):
        from clipfoundry.pipeline import llm

        call = {"settings": dict(settings), "messages": [dict(m) for m in messages], "system": system, "task": task,
                "json_object": json_object, "json_schema": json_schema, "max_tokens": max_tokens,
                "timeout": timeout, "streamed": on_text is not None, "cancel": cancel}
        with self._lock:
            self.calls.append(call)
            index = len(self.calls) - 1
            answer = self.answers.pop(0) if self.answers else {"say": "", "do": []}
        if not self.ready.wait(10):
            raise AssertionError("the test never let the fake model answer")
        if callable(answer) and not isinstance(answer, BaseException):
            answer = answer(call)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, dict):
            answer = json.dumps(answer, ensure_ascii=False)
        pieces = list(answer) if isinstance(answer, list) else _quarters(answer)
        stop = cancel if self.checks_cancel else None
        raw = ""
        for n, piece in enumerate(pieces):
            if stop is not None and stop():
                raise llm.Canceled("Stopped.")
            raw += piece
            if on_text is not None:
                on_text(raw)
            if n == 0 and self.pause_call in (None, index):
                self.started.set()
                if not self.flowing.wait(10):
                    raise AssertionError("the test never let the fake model go on")
        if stop is not None and stop():
            raise llm.Canceled("Stopped.")
        return raw

    # ------------------------------------------------------------------ reading what the model was given
    def tools_offered(self, n: int = -1) -> list[str]:
        """The tool names the reply shape of call `n` allowed (an empty list: no tools in that round)."""
        do = (self.calls[n]["json_schema"] or {}).get("properties", {}).get("do", {})
        return list((do.get("items") or {}).get("properties", {}).get("tool", {}).get("enum") or [])

    def last_user(self, n: int = -1) -> str:
        return [m for m in self.calls[n]["messages"] if m["role"] == "user"][-1]["content"]


def _quarters(raw: str) -> list[str]:
    cuts = sorted({max(1, len(raw) * k // 4) for k in (1, 2, 3, 4)}) if raw else [0]
    return [raw[a:b] for a, b in zip([0, *cuts[:-1]], cuts)]


def install(monkeypatch, *answers, **settings) -> FakeModel:
    """The fake model as ClipForge AI's model (Ollama on this computer unless `settings` say otherwise)."""
    from clipfoundry import db
    from clipfoundry.pipeline import llm

    fake = FakeModel(*answers)
    monkeypatch.setattr(llm, "converse", fake)
    db.save_settings({"ai_provider": "ollama", "ollama_url": "http://localhost:11434", **settings})
    return fake


def settled(chat_id: str, message_id: str, timeout: float = 10.0, ws: str = WS) -> dict:
    """The message once its answer is finished (as the page sees it)."""
    from clipfoundry.brain import chat

    end = time.time() + timeout
    while time.time() < end:
        found = [m for m in chat.messages(ws, chat_id) if m["id"] == message_id]
        if found and found[0]["status"] != "thinking":
            return found[0]
        time.sleep(0.02)
    raise AssertionError(f"still thinking: {[m for m in chat.messages(ws, chat_id) if m['id'] == message_id]}")


@pytest.fixture(autouse=True)
def answers_finish():
    """Every answer a test started in the background is finished before the next test begins (the answers share
    one pool of workers): all the workers meet at a barrier, which they reach only when nothing else runs."""
    yield
    from clipfoundry.brain import assistant

    n = assistant._pool._max_workers  # noqa: SLF001
    barrier = threading.Barrier(n, timeout=20)
    for f in [assistant._pool.submit(barrier.wait) for _ in range(n)]:  # noqa: SLF001
        f.result(timeout=30)


def wait_for(check, timeout: float = 10.0, what: str = "the condition"):
    end = time.time() + timeout
    while time.time() < end:
        got = check()
        if got:
            return got
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")

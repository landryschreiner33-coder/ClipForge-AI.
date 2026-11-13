"""A stand-in for llama.cpp's llama-server in tests: the same flags, /health (503 while "loading", then 200) and an
OpenAI-style /v1/chat/completions that needs the key and echoes the prompt as JSON. A conversation (more than the
system text and one message, or a streamed answer) is echoed whole: every message, and the options it was asked with.
"stream": true answers like llama.cpp does, in pieces (data: {...} lines, then data: [DONE]), 0.3 seconds apart when
the last message says SLOW; last-stream.json then says how many pieces there were, how many were sent, and whether
the app closed the connection first. FAKE_LLAMA_FAIL=1 makes it exit while loading, like an engine that ran out of
memory."""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    argv = sys.argv[1:]
    opt = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("-")}
    Path("last-argv.json").write_text(json.dumps(argv), encoding="utf-8")
    if os.environ.get("FAKE_LLAMA_FAIL"):
        time.sleep(0.2)
        return 3
    key, started = opt["--api-key"], time.monotonic()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401
            pass

        def _json(self, code: int, body: dict) -> None:
            out = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def _stream(self, content: str, slow: bool) -> None:
            pieces = [content[i:i + 8] for i in range(0, len(content), 8)]
            events = [{"choices": [{"index": 0, "delta": {"role": "assistant", "content": None}}]}]
            events += [{"choices": [{"index": 0, "delta": {"content": p}, "finish_reason": None}]} for p in pieces]
            events.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 20, "completion_tokens": len(pieces)},
                           "timings": {"predicted_n": len(pieces), "predicted_ms": 1.0}})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            sent, cut = 0, False
            try:
                for n, event in enumerate(events):
                    if slow and n:
                        time.sleep(0.3)
                    self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                    self.wfile.flush()
                    sent += 1
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                cut = True  # the app stopped reading: the engine stops writing
            Path("last-stream.json").write_text(json.dumps({"pieces": len(events), "sent": sent, "cut": cut}),
                                                encoding="utf-8")

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                if time.monotonic() - started < 0.3:
                    return self._json(503, {"error": {"code": 503, "message": "Loading model"}})
                return self._json(200, {"status": "ok"})
            return self._json(404, {})

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if self.headers.get("Authorization") != f"Bearer {key}":
                return self._json(401, {"error": "Invalid API Key"})
            if self.path != "/v1/chat/completions":
                return self._json(404, {})
            msgs = body.get("messages") or []
            echo = {"echo": msgs[-1]["content"], "system": msgs[0]["content"]}
            if len(msgs) > 2 or body.get("stream"):
                echo.update(messages=msgs, options={k: v for k, v in body.items() if k not in ("messages", "model")})
            content = json.dumps(echo)
            if body.get("stream"):
                return self._stream(content, slow="SLOW" in str(msgs[-1]["content"]))
            return self._json(200, {"choices": [{"message": {"role": "assistant", "content": content},
                                                 "finish_reason": "stop"}]})

    ThreadingHTTPServer((opt["--host"], int(opt["--port"])), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""A stand-in for llama.cpp's llama-server in tests: the same flags, /health (503 while "loading", then 200) and an
OpenAI-style /v1/chat/completions that needs the key and echoes the prompt as JSON. FAKE_LLAMA_FAIL=1 makes it exit
while loading, like an engine that ran out of memory."""
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
            content = json.dumps({"echo": msgs[-1]["content"], "system": msgs[0]["content"]})
            return self._json(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})

    ThreadingHTTPServer((opt["--host"], int(opt["--port"])), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

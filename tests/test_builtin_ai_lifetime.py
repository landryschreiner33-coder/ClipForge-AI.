"""The built-in model's engine (llama-server) lives as long as ClipForge needs it, no longer and no shorter.

On Linux the engine is told to stop when its parent ends (the parent-death signal), and Linux counts the *thread*
that started a program as its parent, not the whole ClipForge. Requests run on short-lived threads (FastAPI's worker
threads retire after about ten idle seconds; job threads end with their job), so an engine started from one of them
stopped with it, mid-use or right after loading its model. The engine is started from one lasting thread instead.

The engine here is the stand-in program of tests/test_builtin_ai.py (tests/fake_llama_server.py).
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tests.test_builtin_ai import _install, hub  # noqa: F401 - hub is the shared fixture

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the parent-death signal is Linux's")
BASIC = {"builtin_ai_level": "basic"}


def _gone(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return True
    return state in ("Z", "X")


@linux_only
def test_the_engine_started_from_a_short_lived_thread_outlives_it(hub):  # noqa: F811
    """A question asked from a request's thread started the engine; when that thread retired, the engine stopped
    with it, so the next question waited for the model to load again (minutes on a large model)."""
    from clipfoundry import builtin_ai

    _install()
    got = []
    request = threading.Thread(target=lambda: got.append(builtin_ai.server.ensure(BASIC)))
    request.start()
    request.join(60)
    assert got, "the engine did not start"
    first = builtin_ai.server.proc
    time.sleep(1.5)  # the signal comes at once when the thread ends
    assert builtin_ai.server.running(), f"the engine stopped with the thread that started it (exit {first.poll()})"
    assert builtin_ai.server.ensure(BASIC) == got[0] and builtin_ai.server.proc is first  # the same, loaded engine


@linux_only
def test_the_engine_started_from_a_short_lived_thread_answers_later(hub):  # noqa: F811
    """The same, through the way ClipForge AI asks: an answer from one thread, the next from another."""
    from clipfoundry import builtin_ai

    _install()
    answers, engines = [], []
    for word in ("one", "two"):
        t = threading.Thread(target=lambda w=word: answers.append(builtin_ai.chat(BASIC, "S", w)))
        t.start()
        t.join(60)
        engines.append(builtin_ai.server.proc.pid)
        time.sleep(1.0)
    assert [json.loads(a)["echo"] for a in answers] == ["one", "two"]
    assert builtin_ai.server.running() and len(set(engines)) == 1, "the model was loaded again for the second answer"


@linux_only
def test_an_engine_that_cannot_start_is_explained_from_the_lasting_thread(hub, monkeypatch):  # noqa: F811
    """A start that fails in the lasting thread still reaches the person as a plain explanation."""
    from clipfoundry import builtin_ai

    _install()
    monkeypatch.setattr(builtin_ai, "build_command", lambda exe, files, port, key, threads: [
        str(Path(exe).parent / "no-such-program")])
    with pytest.raises(builtin_ai.BuiltinError, match="could not start"):
        builtin_ai.server.ensure(BASIC)
    assert not builtin_ai.server.running()


CLIPFORGE_THAT_ENDS = """
import json, os, sys, threading
from pathlib import Path

sys.path.insert(0, sys.argv[1])
os.environ["CLIPFOUNDRY_DATA"] = sys.argv[2]
from clipfoundry import builtin_ai

exe, files = Path(sys.argv[3]), {k: Path(v) for k, v in json.loads(sys.argv[4]).items()}
builtin_ai.engine_path = lambda: exe
builtin_ai.model_files = lambda level: files
builtin_ai.chosen_level = lambda settings: "basic"
builtin_ai.MODELS = {"basic": {"model": "Tiny VL"}}
server = builtin_ai.Server()
job = threading.Thread(target=lambda: server.ensure({}))
job.start()
job.join()
print(server.proc.pid, flush=True)
os._exit(0)  # ClipForge ends without tidying up, as when it crashes
"""


@linux_only
def test_the_engine_still_ends_with_clipforge(hub, tmp_path):  # noqa: F811
    """Starting the engine from a lasting thread must not cost the reason for the signal: when ClipForge ends, even
    without tidying up (a crash, Force Quit), its engine ends too instead of holding gigabytes of memory."""
    from clipfoundry import builtin_ai

    _install()
    repo = Path(builtin_ai.__file__).resolve().parents[1]
    files = {k: str(v) for k, v in builtin_ai.model_files("basic").items()}
    run = subprocess.run([sys.executable, "-I", "-c", CLIPFORGE_THAT_ENDS, str(repo), str(tmp_path / "other-data"),
                          str(builtin_ai.engine_path()), json.dumps(files)], capture_output=True, text=True,
                         timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    pid = int(run.stdout.split()[-1])
    deadline = time.monotonic() + 10
    while not _gone(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _gone(pid), "the built-in model's engine kept running after ClipForge ended"

"""Calling FilmCraft's and EffectCraft's command-line tools.

Every call is one process with a fixed argument list (never a shell), a time limit, and a way to stop it when the job
is canceled. Both tools print JSON; the last JSON line of the output is the answer. FilmCraft's `run` prints one JSON
line per step: `{"line", "id", "ok", "result" | "error"}`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
TICKS = 254_016_000_000  # FilmCraft ticks per second


class CraftError(RuntimeError):
    """A command-line tool failed (the reason is written for the person, with the tool's own last line)."""


def _gpu_args() -> list[str]:
    """`CLIPFOUNDRY_CRAFT_GPU=off` renders on the processor (machines without a usable graphics card, CI)."""
    return ["--gpu-rendering", "off"] if os.environ.get("CLIPFOUNDRY_CRAFT_GPU", "").lower() == "off" else []


def call(exe: str, args: list[str], *, timeout: float, cwd: Path | None = None,
         cancelled: Callable[[], bool] | None = None, what: str = "") -> subprocess.CompletedProcess:
    cmd = [exe, *args]
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,  # noqa: S603
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                creationflags=NO_WINDOW)
    except OSError as exc:
        raise CraftError(f"{what or Path(exe).name} could not start: {exc}") from exc
    deadline = time.monotonic() + timeout
    out_parts: list[str] = []
    err_parts: list[str] = []
    while True:
        try:
            out, err = proc.communicate(timeout=1.0)
            out_parts.append(out or "")
            err_parts.append(err or "")
            break
        except subprocess.TimeoutExpired:
            try:
                stop = bool(cancelled and cancelled())
            except BaseException:  # the job lost its lease while asking: the tool is stopped too
                proc.kill()
                proc.communicate()
                raise
            if stop:
                proc.kill()
                proc.communicate()
                raise CraftError("Stopped.") from None
            if time.monotonic() > deadline:
                proc.kill()
                proc.communicate()
                raise CraftError(f"{what or Path(exe).name} took longer than {timeout / 60:.0f} minutes and was "
                                 "stopped.") from None
    return subprocess.CompletedProcess(cmd, proc.returncode, "".join(out_parts), "".join(err_parts))


def json_lines(text: str) -> list:
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith(("{", "[")):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def last_json(done: subprocess.CompletedProcess, what: str):
    found = json_lines(done.stdout)
    if done.returncode != 0 or not found:
        tail = [x for x in (done.stderr or "").strip().splitlines() if x.strip()]
        why = (found[-1].get("error") if found and isinstance(found[-1], dict) else None) or \
            (tail[-1] if tail else f"exit status {done.returncode}")
        raise CraftError(f"{what} failed: {str(why)[:300]}")
    return found[-1]


# ------------------------------------------------------------------ FilmCraft
class FilmCraft:
    def __init__(self, cli: str, cancelled: Callable[[], bool] | None = None):
        self.cli = cli
        self.cancelled = cancelled

    def _run(self, args: list[str], what: str, timeout: float = 600, cwd: Path | None = None):
        return call(self.cli, ["--compact", *args], timeout=timeout, cwd=cwd, cancelled=self.cancelled,
                    what="FilmCraft")

    def version(self) -> str:
        done = call(self.cli, ["--version"], timeout=60, what="FilmCraft")
        return (done.stdout or done.stderr).strip().split()[-1] if done.returncode == 0 else ""

    def import_files(self, files: list[Path], project: Path) -> dict:
        done = self._run(["import", *map(str, files), "--save-as", str(project)], "Importing the timeline")
        return last_json(done, "Importing the timeline into FilmCraft")

    def inspect(self, project: Path) -> dict:
        return last_json(self._run(["inspect", "sequence", "--project", str(project)], "inspect"),
                         "Reading the FilmCraft sequence")

    def exec(self, project: Path, command: str, params: dict | None = None, *, save: bool = False,
             timeout: float = 600):
        args = ["--project", str(project), *(["--save"] if save else []), *_gpu_args(), "exec", command,
                json.dumps(params or {})]
        return last_json(self._run(args, command, timeout), f"FilmCraft {command}")

    def run_steps(self, project: Path, steps: list[dict], *, timeout: float = 900) -> list[dict]:
        """Run `steps` ({"id", "params"}) in one process and save; returns one result per step (later steps still
        run when one fails)."""
        if not steps:
            return []
        script = project.with_suffix(".steps.jsonl")
        script.write_text("".join(json.dumps({"id": s["id"], "params": s.get("params") or {}}) + "\n"
                                  for s in steps), encoding="utf-8")
        done = self._run(["--project", str(project), "--save", "run", str(script), "--keep-going"], "steps",
                         timeout)
        lines = [x for x in json_lines(done.stdout) if isinstance(x, dict) and "ok" in x]
        if not lines and done.returncode != 0:
            tail = [x for x in (done.stderr or "").splitlines() if x.strip()]
            raise CraftError(f"FilmCraft could not run the edit: {(tail[-1] if tail else done.returncode)}"[:300])
        results = []
        for n, step in enumerate(steps):
            got = next((x for x in lines if int(x.get("line") or 0) == n + 1), lines[n] if n < len(lines) else None)
            results.append({"id": step["id"], "ok": bool(got and got.get("ok")),
                            "result": (got or {}).get("result"), "error": (got or {}).get("error") or
                            ("" if got else "not run")})
        return results

    def commands(self) -> list[dict]:
        found = last_json(self._run(["commands", "--json"], "commands"), "Listing FilmCraft's tools")
        return found if isinstance(found, list) else found.get("commands", [])

    def export(self, project: Path, out: Path, params: dict, *, timeout: float) -> dict:
        return self.exec(project, "file.exportMedia", {"path": str(out), "wait": True, **params}, timeout=timeout)


# ------------------------------------------------------------------ EffectCraft
class EffectCraft:
    def __init__(self, cli: str, cancelled: Callable[[], bool] | None = None):
        self.cli = cli
        self.cancelled = cancelled

    def _confined(self, folder: Path) -> list[str]:
        """Reads and writes only inside the shot's own folder."""
        return ["--automation-read-root", str(folder), "--automation-write-root", str(folder)]

    def script(self, script: Path, project: Path, *, timeout: float = 300) -> dict:
        """Build a project with an After Effects-style script (EffectCraft's scripting sandbox: the script reads
        only its own folder and writes nothing)."""
        args = ["script", str(script), "--save-as", str(project), "--json"]
        done = call(self.cli, [*args, "--empty"], timeout=timeout, cwd=script.parent, cancelled=self.cancelled,
                    what="EffectCraft")
        if done.returncode != 0 and not any(isinstance(x, dict) and x.get("error") for x in json_lines(done.stdout)):
            # an EffectCraft that does not take --empty with a script: it starts from its own demo project, so
            # the shot's composition has a ClipForge name and is rendered by that name
            done = call(self.cli, args, timeout=timeout, cwd=script.parent, cancelled=self.cancelled,
                        what="EffectCraft")
        got = last_json(done, "EffectCraft's script")
        if isinstance(got, dict) and got.get("error"):
            raise CraftError(f"EffectCraft's script failed: {str(got['error'])[:300]}")
        return got if isinstance(got, dict) else {"result": got}

    def steps(self, steps: list[dict], project: Path, *, timeout: float = 300) -> dict:
        file = project.with_suffix(".steps.json")
        file.write_text(json.dumps([{"command": s["id"], "params": s.get("params") or {}} for s in steps]))
        done = call(self.cli, ["run", "--commands", str(file), "--empty", "--save-as", str(project), "--json",
                               *self._confined(project.parent)],
                    timeout=timeout, cwd=project.parent, cancelled=self.cancelled, what="EffectCraft")
        return last_json(done, "EffectCraft")

    def render(self, project: Path, comp: str, out: Path, *, alpha: bool = True, timeout: float = 900) -> dict:
        args = ["render", str(project), "--comp", comp, "--out", str(out), "--format", "prores",
                "--prores", "4444" if alpha else "hq", "--json"]
        if alpha:
            args += ["--channels", "rgba"]
        done = call(self.cli, args, timeout=timeout, cwd=project.parent, cancelled=self.cancelled,
                    what="EffectCraft")
        got = last_json(done, "EffectCraft's render")
        if not out.is_file() or out.stat().st_size == 0:
            raise CraftError("EffectCraft's render wrote no file.")
        return got if isinstance(got, dict) else {}

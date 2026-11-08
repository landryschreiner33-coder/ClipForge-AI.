"""What ClipForge AI can do in the app: its tools (docs/clipforge/CLIPFORGE_AI.md, "Actions").

A tool is one thing the assistant (or a helper agent) may do, with arguments the model fills in and ClipForge checks
before anything runs. Every tool has a risk:

* ``look``   reads only (your projects, your memories, the know-how). Runs at once.
* ``make``   adds something new or proposes something you still decide on (a memory, a change proposal you apply or
             discard, a helper agent's work). Runs at once; it never touches what you already have.
* ``change`` changes something you have (renames a project, forgets a memory).
* ``delete`` removes something you have (a project).

``change`` and ``delete`` tools never run on the model's word: the chat shows what would happen and a button, and
only the owner's press runs them (`chat.decide`). Other parts of ClipForge add their own tools with `register` (the
new-video planner adds "make a YouTube video"); ClipForge's own tools are in toolbox.py.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from typing import Callable

RISKS = ("look", "make", "change", "delete")
WAITS = ("change", "delete")          # risks that wait for the owner's OK
PLACES = ("general", "video")         # the general chat, and a video's chat
MAX_TEXT = 1500                       # what one tool result may give the model to read


class ToolError(ValueError):
    """The tool could not do it; the message is a plain sentence for the model and the owner."""


class TryAgain(ToolError):
    """Not right now, but pressing OK again in a moment works (the message says so); the button stays."""


@dataclass
class Ctx:
    """Where a tool runs: the workspace, the chat and its video ('' in the general chat), the AI message it belongs
    to, and the helper agent running it (None for ClipForge AI itself)."""
    ws: str
    chat: dict = field(default_factory=dict)
    project_id: str = ""
    message_id: str = ""
    agent: dict | None = None
    deadline: float = 0.0             # time.monotonic() by which the turn must be finished (0: none)
    cancel: Callable[[], bool] | None = None
    on_helper: Callable[[dict], None] | None = None  # an agent's work as it is written (ask_agent)


@dataclass
class Result:
    """What a tool did: `text` for the model to read, `summary` for the owner's step line, `data` merged into the
    AI message (for example a change request's id, links to open, an agent's work)."""
    text: str
    summary: str = ""
    data: dict = field(default_factory=dict)
    ok: bool = True


@dataclass
class Tool:
    name: str
    description: str                  # what the model reads about it
    args: dict                        # JSON schema (type object) of its arguments
    run: Callable[[Ctx, dict], Result]
    risk: str = "look"
    label: str = ""                   # the owner's words for it, with {arg} placeholders ("Looked at {project}")
    places: tuple[str, ...] = PLACES  # where it is offered
    preview: Callable[[Ctx, dict], dict] | None = None
    """change/delete: what pressing OK would do, shown before the press: {"label", "detail": [sentences],
    "blocked": "" or why it cannot be done now}. Raises ToolError when it makes no sense (no such project)."""
    for_agents: bool = True           # helper agents may be given it

    def __post_init__(self) -> None:
        if self.risk not in RISKS:
            raise ValueError(f"unknown risk {self.risk!r}")
        if not self.name.replace("_", "").isalnum() or not self.name.islower():
            raise ValueError(f"tool names are lower_case words: {self.name!r}")
        if (self.args or {}).get("type", "object") != "object":
            raise ValueError("a tool's arguments are one JSON object")

    def words(self, args: dict) -> str:
        """The label with the arguments filled in."""
        text = self.label or self.name.replace("_", " ").capitalize()
        for k, v in (args or {}).items():
            text = text.replace("{" + k + "}", str(v)[:80])
        return text.replace("{", "").replace("}", "") if "{" in text else text


_registry: dict[str, Tool] = {}
_lock = threading.Lock()
_loaded = False


def register(tool: Tool) -> Tool:
    """Offer a tool to ClipForge AI (a later registration with the same name replaces the earlier one)."""
    with _lock:
        _registry[tool.name] = tool
    return tool


def unregister(name: str) -> None:
    with _lock:
        _registry.pop(name, None)


def _builtins() -> None:
    global _loaded
    if not _loaded:
        _loaded = True
        from . import toolbox  # noqa: F401 - registers ClipForge's own tools


def get(name: str) -> Tool | None:
    _builtins()
    return _registry.get(str(name or ""))


def all_tools() -> list[Tool]:
    _builtins()
    return list(_registry.values())


def available(place: str, *, agent: dict | None = None) -> list[Tool]:
    """The tools offered in a chat (`place`: "general" or "video"); for a helper agent, only the look and make tools
    it was given, never handing work on to another agent."""
    tools = [t for t in all_tools() if place in t.places]
    if agent is not None:
        allowed = set(agent.get("tools") or [])
        tools = [t for t in tools if t.name in allowed and t.for_agents and t.risk in ("look", "make")
                 and t.name != "ask_agent"]
    return tools


# ------------------------------------------------------------------ checking what the model filled in
def _type_ok(value: object, kind: str) -> bool:
    return {"string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool), "array": isinstance(value, list),
            "object": isinstance(value, dict)}.get(kind, True)


def _coerce(value: object, spec: dict) -> object:
    kind = spec.get("type", "string")
    if kind == "string" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if kind == "integer" and isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    if kind == "integer" and isinstance(value, float) and value.is_integer():
        return int(value)
    if kind == "number" and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    if kind == "boolean" and isinstance(value, str) and value.lower() in ("true", "false", "yes", "no"):
        return value.lower() in ("true", "yes")
    if kind == "array" and isinstance(value, str):
        return [value]
    return value


def check_args(tool: Tool, args: object) -> dict:
    """The arguments as the tool will get them: known names only, simple types coerced (\"3\" -> 3), strings
    trimmed and cut to their maxLength, enums and required ones checked. Raises ToolError with what is wrong."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolError(f"{tool.name} takes its arguments as an object, like {{\"name\": value}}.")
    props = (tool.args or {}).get("properties") or {}
    out: dict = {}
    for name, spec in props.items():
        if name not in args or args[name] in (None, ""):
            continue
        value = _coerce(args[name], spec)
        kind = spec.get("type", "string")
        if not _type_ok(value, kind):
            raise ToolError(f"{tool.name}: {name} should be {kind}.")
        if kind == "string":
            value = " ".join(value.split())[: int(spec.get("maxLength") or 2000)]
            if not value:
                continue
        if kind == "array":
            item = (spec.get("items") or {}).get("type", "string")
            value = [_coerce(v, {"type": item}) for v in value][: int(spec.get("maxItems") or 20)]
            if any(not _type_ok(v, item) for v in value):
                raise ToolError(f"{tool.name}: every {name} should be {item}.")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolError(f"{tool.name}: {name} must be one of {', '.join(map(str, spec['enum']))}.")
        if kind in ("integer", "number"):
            lo, hi = spec.get("minimum"), spec.get("maximum")
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                raise ToolError(f"{tool.name}: {name} must be between {lo} and {hi}.")
        out[name] = value
    for name in (tool.args or {}).get("required") or []:
        if name not in out:
            raise ToolError(f"{tool.name} needs {name}.")
    return out


def signature(tool: Tool) -> str:
    """One line the model reads: name(arg: type, optional?: type) — description."""
    props = (tool.args or {}).get("properties") or {}
    need = set((tool.args or {}).get("required") or [])
    parts = []
    for name, spec in props.items():
        kind = "|".join(f'"{v}"' for v in spec["enum"]) if "enum" in spec else \
            {"string": "text", "integer": "number", "number": "number", "boolean": "true|false",
             "array": "list of text"}.get(spec.get("type", "string"), "text")
        parts.append(f"{name}{'' if name in need else '?'}: {kind}")
    waits = " Waits for the owner's OK." if tool.risk in WAITS else ""
    return f"- {tool.name}({', '.join(parts)}): {tool.description}{waits}"


def describe(tools: list[Tool]) -> str:
    return "\n".join(signature(t) for t in tools)


def reply_schema(tools: list[Tool]) -> dict:
    """The JSON shape of one answer from the assistant: what it says, the tools it uses now (at most three) and an
    optional question with choices. The built-in model is held to it while it writes; the arguments of each tool are
    checked afterwards (check_args)."""
    names = [t.name for t in tools]
    call = {"type": "object", "properties": {"tool": {"type": "string", "enum": names} if names else {"type": "string"},
                                             "args": {"type": "object"}},
            "required": ["tool", "args"], "additionalProperties": False}
    schema: dict = {"type": "object",
                    "properties": {"say": {"type": "string"},
                                   "do": {"type": "array", "items": call, "maxItems": 3} if names else
                                   {"type": "array", "maxItems": 0},
                                   "ask": {"type": "object",
                                           "properties": {"question": {"type": "string"},
                                                          "choices": {"type": "array", "items": {"type": "string"},
                                                                      "maxItems": 4}},
                                           "required": ["question", "choices"], "additionalProperties": False}},
                    "required": ["say", "do"], "additionalProperties": False}
    return schema


def clip(text: object, limit: int = MAX_TEXT) -> str:
    s = str(text or "").strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

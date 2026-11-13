"""REST endpoints for ClipForge AI's memories (docs/clipforge/CLIPFORGE_AI.md). Reads need a local or signed-in
request, writes the app's own header, like the rest of /api/brain."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from ..cloud import principal
from ..publish.common import app_request, local_only
from . import knowhow, memories, tools

router = APIRouter(prefix="/api/brain/memories")
READ = [Depends(local_only)]
WRITE = [Depends(app_request)]


def _err(exc: memories.Invalid) -> HTTPException:
    return HTTPException(exc.status, str(exc))


MAX_DEPTH = 100  # lists and objects inside one another in a request: a brain file has five, with a memory's data


class Input(BaseModel):
    """What a request sends. Half of an emoji in a text (a message cut in the middle of one) is left out before the
    fields are checked: it cannot be saved, and the refusal of it could not even be sent back (a server error). A
    body nested more than MAX_DEPTH deep (nothing ClipForge sends comes near) is refused in plain words: what a
    brain file stores is sent back with every list of memories, and nesting of a few hundred levels can be read
    and stored but not sent, so one such memory made the Memory page and every recall fail."""

    @model_validator(mode="before")
    @classmethod
    def _whole(cls, data: Any) -> Any:
        try:
            return tools.clean(data, MAX_DEPTH)
        except RecursionError:
            raise HTTPException(422, "That is nested too deeply to read.") from None


class MemoryIn(Input):
    text: str = Field(max_length=4000)
    kind: str = "fact"
    scope: str | None = None
    project_id: str = ""
    platform: str = ""
    mode: str = ""
    tags: list[str] = Field(default_factory=list)


class MemoryPatch(Input):
    text: str | None = Field(default=None, max_length=4000)
    kind: str | None = None
    scope: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None


class RecallIn(Input):
    query: str = Field(default="", max_length=4000)
    project_id: str = ""
    platform: str = ""
    mode: str = ""
    limit: int = Field(default=6, ge=0, le=50)


class ImportIn(Input):
    data: dict


class UndoIn(Input):
    words: str = Field(max_length=4000)  # what the chip says was kept


@router.get("", dependencies=READ)
def list_memories(q: str = "", kind: str = "", project_id: str = "", limit: int = 200) -> list[dict]:
    return memories.list_(principal.workspace_id(), q[:4000], kind, project_id, limit)


@router.post("", dependencies=WRITE)
def add(body: MemoryIn) -> dict:
    try:
        return memories.view(memories.remember(principal.workspace_id(), body.text, kind=body.kind, source="said",
                                               scope=body.scope, project_id=body.project_id, platform=body.platform,
                                               mode=body.mode, tags=body.tags))
    except memories.Invalid as exc:
        raise _err(exc) from exc


@router.post("/recall", dependencies=READ)
def recall(body: RecallIn) -> dict:
    """What ClipForge AI would read for these words, with scores (nothing is recorded as used)."""
    try:
        r = memories.recall(body.query, principal.workspace_id(), project_id=body.project_id, platform=body.platform,
                            mode=body.mode, limit=body.limit)
    except memories.Invalid as exc:
        raise _err(exc) from exc
    return {"memories": r.memories, "prompt": r.prompt()}


@router.get("/check", dependencies=READ)
def check() -> dict:
    return memories.check(principal.workspace_id())


class KnowHowIn(Input):
    query: str = Field(default="", max_length=4000)
    task: str = ""


@router.get("/knowhow", dependencies=READ)
def knowhow_topics() -> dict:
    """ClipForge AI's built-in craft know-how: every playbook, and where it came from."""
    return {"topics": knowhow.topics(), "source": knowhow.SOURCE, "tasks": list(knowhow.TASKS)}


@router.post("/knowhow/select", dependencies=READ)
def knowhow_select(body: KnowHowIn) -> dict:
    """What ClipForge AI would read from its know-how for these words (nothing is recorded)."""
    picked = knowhow.select(body.query, body.task, limit=3, budget_chars=2400)
    return {"topics": picked.snapshot(), "prompt": picked.prompt(), "answer": knowhow.answer(body.query)}


@router.post("/rebuild", dependencies=WRITE)
def rebuild() -> dict:
    return {"rebuilt": memories.rebuild(principal.workspace_id())}


@router.post("/tidy", dependencies=WRITE)
def tidy() -> dict:
    return memories.tidy(principal.workspace_id())


@router.get("/export", dependencies=READ)
def export() -> JSONResponse:
    return JSONResponse(memories.export(principal.workspace_id()),
                        headers={"Content-Disposition": 'attachment; filename="clipforge-ai-brain.json"'})


@router.post("/import", dependencies=WRITE)
def import_file(body: ImportIn) -> dict:
    try:
        return memories.import_(principal.workspace_id(), body.data)
    except memories.Invalid as exc:
        raise _err(exc) from exc


@router.get("/{memory_id}/uses", dependencies=READ)
def uses(memory_id: str) -> list[dict]:
    try:
        return memories.uses(principal.workspace_id(), memory_id)
    except memories.Invalid as exc:
        raise _err(exc) from exc


@router.post("/{memory_id}/confirm", dependencies=WRITE)
def confirm(memory_id: str) -> dict:
    try:
        return memories.view(memories.confirm(principal.workspace_id(), memory_id))
    except memories.Invalid as exc:
        raise _err(exc) from exc


@router.patch("/{memory_id}", dependencies=WRITE)
def edit(memory_id: str, body: MemoryPatch) -> dict:
    try:
        return memories.view(memories.edit(principal.workspace_id(), memory_id, text=body.text, kind=body.kind,
                                           scope=body.scope, tags=body.tags, enabled=body.enabled))
    except memories.Invalid as exc:
        raise _err(exc) from exc


@router.delete("/{memory_id}", dependencies=WRITE)
def forget(memory_id: str) -> dict:
    try:
        return {"forgotten": memories.forget(principal.workspace_id(), memory_id)}
    except memories.Invalid as exc:
        raise _err(exc) from exc


@router.post("/{memory_id}/undo", dependencies=WRITE)
def undo(memory_id: str, body: UndoIn) -> dict:
    """A chat's Undo chip: only while the memory is as that answer added it (memories.undo)."""
    try:
        return {"forgotten": memories.undo(principal.workspace_id(), memory_id, body.words)}
    except memories.Invalid as exc:
        raise _err(exc) from exc


# ------------------------------------------------------------------ the chat
from . import chat as chat_module  # noqa: E402

chats = APIRouter(prefix="/api/brain/chats")


def _chat_err(exc: chat_module.ChatError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


class OpenChat(Input):
    project_id: str = ""


class Say(Input):
    text: str = Field(max_length=4000)
    base_revision: int | None = None
    choice: bool = False  # a quick reply pressed: words the model or the editor wrote (chat.send)
    forget: str | None = Field(default=None, max_length=4000)  # a "Which one?" button: the memory's words it shows


class Decide(Input):
    do: bool


@chats.post("", dependencies=WRITE)
def open_chat(body: OpenChat) -> dict:
    """The chat of one video, or the general chat, with its last messages, ClipForge AI's model (ready or not, and
    the built-in model's setup) and the helper agents you can talk to with @."""
    from . import agents, assistant

    ws = principal.workspace_id()
    try:
        chat = chat_module.open_chat(ws, body.project_id)
    except chat_module.ChatError as exc:
        raise _chat_err(exc) from exc
    return {**chat, "messages": chat_module.messages(ws, chat["id"]), "ai": assistant.status(ws),
            "agents": [agents.card(a) | {"role": a["role"]} for a in agents.list_(ws, enabled_only=True)]}


@chats.get("/{chat_id}/messages", dependencies=READ)
def chat_messages(chat_id: str, after: str = "", limit: int = chat_module.KEEP) -> list[dict]:
    try:
        return chat_module.messages(principal.workspace_id(), chat_id, after, limit)
    except chat_module.ChatError as exc:
        raise _chat_err(exc) from exc


@chats.post("/{chat_id}/messages", dependencies=WRITE)
def say(chat_id: str, body: Say) -> dict:
    try:
        return chat_module.send(principal.workspace_id(), chat_id, body.text, body.base_revision, choice=body.choice,
                                forget=body.forget)
    except chat_module.ChatError as exc:
        raise _chat_err(exc) from exc


@chats.delete("/{chat_id}/messages", dependencies=WRITE)
def clear_chat(chat_id: str) -> dict:
    try:
        return {"cleared": chat_module.clear(principal.workspace_id(), chat_id)}
    except chat_module.ChatError as exc:
        raise _chat_err(exc) from exc


@chats.post("/{chat_id}/messages/{chat_message_id}/apply", dependencies=WRITE)
def apply_change(chat_id: str, chat_message_id: str) -> dict:
    try:
        return chat_module.apply(principal.workspace_id(), chat_id, chat_message_id)
    except chat_module.ChatError as exc:
        raise _chat_err(exc) from exc


@chats.post("/{chat_id}/messages/{chat_message_id}/discard", dependencies=WRITE)
def discard_change(chat_id: str, chat_message_id: str) -> dict:
    try:
        return chat_module.discard(principal.workspace_id(), chat_id, chat_message_id)
    except chat_module.ChatError as exc:
        raise _chat_err(exc) from exc


@chats.post("/{chat_id}/stop", dependencies=WRITE)
def stop_answer(chat_id: str) -> list[dict]:
    """Stop the answer being written in this chat; it keeps what it wrote so far."""
    try:
        return chat_module.stop(principal.workspace_id(), chat_id)
    except chat_module.ChatError as exc:
        raise _chat_err(exc) from exc


@chats.post("/{chat_id}/messages/{chat_message_id}/actions/{action_id}", dependencies=WRITE)
def decide_action(chat_id: str, chat_message_id: str, action_id: str, body: Decide) -> dict:
    """The owner's OK (do: true) or no (do: false) for a change or delete ClipForge AI proposed. Only this request,
    sent by the app's own page, can run it; the model never can."""
    try:
        return chat_module.decide(principal.workspace_id(), chat_id, chat_message_id, action_id, body.do)
    except chat_module.ChatError as exc:
        raise _chat_err(exc) from exc


# ------------------------------------------------------------------ helper agents
from . import agents as agents_module  # noqa: E402

agent_routes = APIRouter(prefix="/api/brain/agents")


def _agent_err(exc: agents_module.AgentError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


class AgentIn(Input):
    template: str = Field(default="", max_length=40)
    name: str = Field(default="", max_length=200)
    icon: str = Field(default="", max_length=40)
    role: str = Field(default="", max_length=1000)
    instructions: str = Field(default="", max_length=8000)
    tools: list[str] | None = None
    helps_plans: bool | None = None
    enabled: bool = True


class AgentPatch(Input):
    name: str | None = Field(default=None, max_length=200)
    icon: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=1000)
    instructions: str | None = Field(default=None, max_length=8000)
    tools: list[str] | None = None
    helps_plans: bool | None = None
    enabled: bool | None = None
    position: int | None = Field(default=None, ge=0, le=1000)


@agent_routes.get("", dependencies=READ)
def list_agents() -> dict:
    """Your helper agents, the ready-made ones you can add, the tools an agent may be given and the icons."""
    ws = principal.workspace_id()
    mine = agents_module.list_(ws)
    have = {a["template"] for a in mine}
    return {"agents": mine, "templates": [{**t, "added": t["template"] in have} for t in agents_module.TEMPLATES],
            "tools": agents_module.agent_tools(), "icons": list(agents_module.ICONS),
            "limit": agents_module.MAX_AGENTS}


@agent_routes.post("", dependencies=WRITE)
def add_agent(body: AgentIn) -> dict:
    try:
        return agents_module.add(principal.workspace_id(), template=body.template, name=body.name, icon=body.icon,
                                 role=body.role, instructions=body.instructions, tools_=body.tools,
                                 helps_plans=body.helps_plans, enabled=body.enabled)
    except agents_module.AgentError as exc:
        raise _agent_err(exc) from exc


@agent_routes.patch("/{agent_id}", dependencies=WRITE)
def edit_agent(agent_id: str, body: AgentPatch) -> dict:
    try:
        return agents_module.edit(principal.workspace_id(), agent_id, **body.model_dump())
    except agents_module.AgentError as exc:
        raise _agent_err(exc) from exc


@agent_routes.delete("/{agent_id}", dependencies=WRITE)
def remove_agent(agent_id: str) -> dict:
    try:
        return {"removed": agents_module.remove(principal.workspace_id(), agent_id)}
    except agents_module.AgentError as exc:
        raise _agent_err(exc) from exc

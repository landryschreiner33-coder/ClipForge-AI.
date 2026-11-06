"""REST endpoints for ClipForge AI's memories (docs/clipforge/CLIPFORGE_AI.md). Reads need a local or signed-in
request, writes the app's own header, like the rest of /api/brain."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..cloud import principal
from ..publish.common import app_request, local_only
from . import knowhow, memories

router = APIRouter(prefix="/api/brain/memories")
READ = [Depends(local_only)]
WRITE = [Depends(app_request)]


def _err(exc: memories.Invalid) -> HTTPException:
    return HTTPException(exc.status, str(exc))


class MemoryIn(BaseModel):
    text: str = Field(max_length=4000)
    kind: str = "fact"
    scope: str | None = None
    project_id: str = ""
    platform: str = ""
    mode: str = ""
    tags: list[str] = Field(default_factory=list)


class MemoryPatch(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    kind: str | None = None
    scope: str | None = None
    tags: list[str] | None = None
    enabled: bool | None = None


class RecallIn(BaseModel):
    query: str = Field(default="", max_length=4000)
    project_id: str = ""
    platform: str = ""
    mode: str = ""
    limit: int = Field(default=6, ge=0, le=50)


class ImportIn(BaseModel):
    data: dict


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


class KnowHowIn(BaseModel):
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


# ------------------------------------------------------------------ the chat
from . import chat as chat_module  # noqa: E402

chats = APIRouter(prefix="/api/brain/chats")


def _chat_err(exc: chat_module.ChatError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


class OpenChat(BaseModel):
    project_id: str = ""


class Say(BaseModel):
    text: str = Field(max_length=4000)
    base_revision: int | None = None


@chats.post("", dependencies=WRITE)
def open_chat(body: OpenChat) -> dict:
    """The chat of one video, or the general chat, with its last messages."""
    ws = principal.workspace_id()
    try:
        chat = chat_module.open_chat(ws, body.project_id)
    except chat_module.ChatError as exc:
        raise _chat_err(exc) from exc
    return {**chat, "messages": chat_module.messages(ws, chat["id"])}


@chats.get("/{chat_id}/messages", dependencies=READ)
def chat_messages(chat_id: str, after: str = "", limit: int = chat_module.KEEP) -> list[dict]:
    try:
        return chat_module.messages(principal.workspace_id(), chat_id, after, limit)
    except chat_module.ChatError as exc:
        raise _chat_err(exc) from exc


@chats.post("/{chat_id}/messages", dependencies=WRITE)
def say(chat_id: str, body: Say) -> dict:
    try:
        return chat_module.send(principal.workspace_id(), chat_id, body.text, body.base_revision)
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

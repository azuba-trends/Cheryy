"""FastAPI surface for the desktop UI.

Endpoints:
  GET  /health                       - health
  POST /setup/validate_key           - validate a Gemini API key
  POST /setup/apply_key              - store key + initialise providers
  GET  /setup/self_test              - run capability checks
  GET  /setup/status                 - provider + capability snapshot

  GET  /chat/conversations           - list past conversations
  GET  /chat/conversations/{id}/messages
  POST /chat/send                    - send a message, run agent
  POST /chat/cancel/{task_id}

  GET  /tasks                        - recent tasks
  GET  /tasks/{id}                   - one task
  POST /tasks/{id}/pause
  POST /tasks/{id}/resume
  POST /tasks/{id}/cancel

  GET  /memory                       - list memory records
  POST /memory                       - add a record
  DELETE /memory/{id}                - deactivate a record
  POST /memory/search

  GET  /files                        - list safe-roots
  POST /files/action                 - run a controlled fs tool

  GET  /activity                     - recent log events
  GET  /monitors                     - monitor layout
  GET  /running_apps

  GET  /providers/status             - provider status

  WS   /ws/voice                     - audio chunks + events
  WS   /ws/events                    - general UI event stream
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text

from .. import agent as agent_mod
from .. import computer, diagnostics
from ..config import get_settings
from ..db import session_scope
from ..logging_setup import bus, configure_logging, get_logger, LogEvent
from ..memory import get_memory_store, MemoryRecord
from ..providers.registry import get_registry
from ..secrets import mask_key
from ..setup import apply_validated_key, run_self_test, validate_api_key
from ..tasks import get_task_engine, Status
from ..tools import get_tool_registry

log = get_logger("cheryy.api")
configure_logging()


app = FastAPI(title="CHERYY Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "tauri://localhost", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _on_startup() -> None:
    from ..db import init_db
    await init_db()
    reg = get_registry()
    await reg.initialize()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class KeyIn(BaseModel):
    api_key: str

class ChatIn(BaseModel):
    message: str
    conversation_id: int | None = None

class MemoryIn(BaseModel):
    category: str
    content: str
    importance: float = 0.5
    confidence: float = 1.0
    tags: list[str] = Field(default_factory=list)

class FileActionIn(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "cheryy", "ts": time.time()}


@app.post("/setup/validate_key")
async def setup_validate_key(body: KeyIn) -> dict[str, Any]:
    return await validate_api_key(body.api_key)


@app.post("/setup/apply_key")
async def setup_apply_key(body: KeyIn) -> dict[str, Any]:
    info = await apply_validated_key(body.api_key)
    return {"ok": True, "info": info, "preview": mask_key(body.api_key)}


@app.get("/setup/self_test")
async def setup_self_test() -> dict[str, Any]:
    return await run_self_test()


@app.get("/setup/status")
async def setup_status() -> dict[str, Any]:
    reg = get_registry()
    await reg.initialize()
    status = await reg.status()
    status["preview_key"] = mask_key(get_settings().gemini_api_key)
    return status


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

_agent: agent_mod.Agent | None = None


def get_agent() -> agent_mod.Agent:
    global _agent
    if _agent is None:
        _agent = agent_mod.Agent()
    return _agent


@app.get("/chat/conversations")
async def chat_conversations() -> list[dict[str, Any]]:
    return await get_agent().list_conversations()


@app.get("/chat/conversations/{cid}/messages")
async def chat_messages(cid: int) -> list[dict[str, Any]]:
    return await get_agent().list_messages(cid)


@app.post("/chat/send")
async def chat_send(body: ChatIn) -> dict[str, Any]:
    return await get_agent().chat(body.message, source="chat", conversation_id=body.conversation_id)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@app.get("/tasks")
async def tasks_list() -> list[dict[str, Any]]:
    items = await get_task_engine().list_recent()
    return [_task_to_dict(t) for t in items]


@app.get("/tasks/{tid}")
async def task_get(tid: int) -> dict[str, Any]:
    t = await get_task_engine().get(tid)
    if t is None:
        raise HTTPException(404, "task not found")
    return _task_to_dict(t)


@app.post("/tasks/{tid}/pause")
async def task_pause(tid: int) -> dict[str, Any]:
    await get_task_engine().pause(tid)
    return {"ok": True}


@app.post("/tasks/{tid}/resume")
async def task_resume(tid: int) -> dict[str, Any]:
    await get_task_engine().resume(tid)
    return {"ok": True}


@app.post("/tasks/{tid}/cancel")
async def task_cancel(tid: int) -> dict[str, Any]:
    await get_task_engine().cancel(tid)
    return {"ok": True}


def _task_to_dict(t) -> dict[str, Any]:
    return {
        "id": t.id,
        "user_request": t.user_request,
        "plan": [s.__dict__ for s in t.plan],
        "current_step": t.current_step,
        "progress": t.progress,
        "status": t.status.value,
        "observations": t.observations,
        "verification": t.verification,
        "result": t.result,
        "error": t.error,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

@app.get("/memory")
async def memory_list(category: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    records = await get_memory_store().list(category=category, limit=limit)
    return [r.to_dict() for r in records]


@app.post("/memory")
async def memory_add(body: MemoryIn) -> dict[str, Any]:
    rid = await get_memory_store().add(
        body.category, body.content,
        importance=body.importance, confidence=body.confidence, tags=body.tags,
    )
    return {"id": rid}


class MemorySearchIn(BaseModel):
    query: str
    categories: list[str] | None = None
    top_k: int = 8


@app.post("/memory/search")
async def memory_search(body: MemorySearchIn) -> list[dict[str, Any]]:
    rs = await get_memory_store().search(body.query, categories=body.categories, top_k=body.top_k)
    return [r.to_dict() for r in rs]


@app.delete("/memory/{mid}")
async def memory_forget(mid: int) -> dict[str, Any]:
    await get_memory_store().delete(mid, hard=False)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

@app.get("/files")
async def files_list(path: str, recursive: bool = False, limit: int = 200) -> dict[str, Any]:
    tool = get_tool_registry().get("filesystem.list")
    if not tool:
        return {"error": "fs tool unavailable"}
    return await tool(path=path, recursive=recursive, limit=limit)


@app.post("/files/action")
async def files_action(body: FileActionIn) -> dict[str, Any]:
    t = get_tool_registry().get(body.name)
    if not t:
        return {"success": False, "error": f"unknown tool: {body.name}"}
    return (await t(**body.args)).to_dict()


# ---------------------------------------------------------------------------
# Live PC / system
# ---------------------------------------------------------------------------

@app.get("/monitors")
async def monitors() -> dict[str, Any]:
    return {"monitors": [m.to_dict() for m in computer.list_monitors()]}


@app.get("/running_apps")
async def running_apps() -> dict[str, Any]:
    return {"apps": computer.list_running_apps()}


@app.get("/activity")
async def activity(limit: int = 100) -> dict[str, Any]:
    events = bus.recent(limit=limit)
    return {"events": [e.__dict__ for e in events]}


@app.get("/providers/status")
async def providers_status() -> dict[str, Any]:
    reg = get_registry()
    await reg.initialize()
    return await reg.status()


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@app.get("/diagnostics/health")
async def diag_health() -> dict[str, Any]:
    return await diagnostics.health_report()


@app.post("/diagnostics/repair")
async def diag_repair() -> dict[str, Any]:
    return await diagnostics.safe_repair()


# ---------------------------------------------------------------------------
# WebSocket event stream
# ---------------------------------------------------------------------------

@app.websocket("/ws/events")
async def ws_events(ws: WebSocket) -> None:
    await ws.accept()
    queue: asyncio.Queue[LogEvent] = asyncio.Queue()

    def put(ev: LogEvent) -> None:
        try:
            queue.put_nowait(ev)
        except Exception:
            pass

    unsubscribe = bus.subscribe(put)
    try:
        await ws.send_text(json.dumps({"type": "hello", "ts": time.time()}))
        while True:
            ev = await queue.get()
            await ws.send_text(json.dumps({"type": "event", "event": ev.__dict__}))
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe()


@app.websocket("/ws/voice")
async def ws_voice(ws: WebSocket) -> None:
    """Audio in / events out.

    Client sends JSON: {"kind": "audio", "pcm_b64": "..."} | {"kind": "stop"}
    Server sends JSON: {"type": "voice_state", ...} | {"type": "voice_transcript", ...}
    """
    await ws.accept()
    from ..voice import VoiceSession
    loop_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def cb(ev: dict[str, Any]) -> None:
        try:
            loop_q.put_nowait(ev)
        except Exception:
            pass

    session = VoiceSession(on_event=cb)
    await session.start()
    try:
        async def pump_consumer():
            while True:
                ev = await loop_q.get()
                await ws.send_text(json.dumps(ev))

        consumer = asyncio.create_task(pump_consumer())
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                continue
            kind = data.get("kind")
            if kind == "audio":
                pcm = base64.b64decode(data.get("pcm_b64", ""))
                await session.push_audio(pcm)
            elif kind == "text":
                await session.push_text(data.get("text", ""))
            elif kind == "stop":
                break
        consumer.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        await session.stop()
"""Top-level agent.

Coordinates: chat history, memory retrieval, planner, task engine, tools,
provider registry, voice synchronisation.

The agent runs in a per-session loop. UI events are pushed through a queue
that the FastAPI server streams to the desktop client.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from ..db import session_scope, now_iso
from ..logging_setup import get_logger, bus, LogEvent
from ..memory import get_memory_store
from ..planner import plan
from ..providers.base import Capability, LLMMessage, LLMRequest
from ..providers.registry import get_registry
from ..security import audit
from ..tasks import TaskEngine, TaskStep, get_task_engine
from ..tools import ToolResult, get_tool_registry
from ..voice import VoiceSession
from .. import memory as _memory_mod

log = get_logger("cheryy.agent")


@dataclass
class ChatTurn:
    role: str
    content: str
    ts: str = field(default_factory=now_iso)
    voice_text: str | None = None
    task_id: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


SYSTEM_PROMPT = """You are CHERYY, a careful Windows desktop AI assistant.
You are honest, professional, calm, and you verify your work.
Never claim something was completed unless it actually was.
Never delete anything on the user's computer — that is a hard rule.

When you respond:
- Be concise. Speak naturally.
- If you will perform a multi-step task, describe the plan briefly first.
- When the task is complete, summarise the actual result (file paths, links, what was verified)."""


class Agent:
    """One CHERYY agent per user session."""

    def __init__(self) -> None:
        self.task_engine: TaskEngine = get_task_engine()
        self._memory = get_memory_store()
        self._voice = VoiceSession(on_event=self._on_voice_event)
        self._voice_task: asyncio.Task | None = None
        self._active_task_id: int | None = None

    # ---------- voice
    async def start_voice(self) -> None:
        if self._voice_task is None or self._voice_task.done():
            self._voice_task = asyncio.create_task(self._voice.start())
        await asyncio.sleep(0)

    async def stop_voice(self) -> None:
        await self._voice.stop()
        if self._voice_task:
            try:
                await self._voice_task
            except Exception:
                pass
            self._voice_task = None

    def _on_voice_event(self, ev: dict[str, Any]) -> None:
        bus.emit(LogEvent(ts=now_iso(), level="INFO", message=f"voice: {ev}", source="voice"))

    # ---------- conversation
    async def chat(self, message: str, *, source: str = "chat", conversation_id: int | None = None) -> dict[str, Any]:
        reg = get_registry()
        if reg.llm() is None:
            return {"reply": "CHERYY isn't connected to an AI provider yet. Add a Gemini API key in Settings.", "spoken": None}
        if conversation_id is None:
            conversation_id = await self._new_conversation(source=source)
        # 1. Persist user message
        await self._add_message(conversation_id, "user", message)

        # 2. Memory retrieval
        relevant = await self._memory.search(message, top_k=6)

        # 3. Build LLM request
        req = LLMRequest(
            messages=[
                LLMMessage(role="system", content=_build_system(SYSTEM_PROMPT, relevant)),
                LLMMessage(role="user", content=message),
            ],
            temperature=0.4,
            max_tokens=1024,
        )
        # 4. Decide: plan+execute vs. plain answer
        plan_steps: list[TaskStep] = []
        if _should_plan(message):
            try:
                plan_steps = await plan(message, context=_context_summary(relevant))
            except Exception as e:
                log.info("planner unavailable, plain answer: %s", e)
        if plan_steps:
            # Create + run task
            task_id = await self.task_engine.create(message, plan=plan_steps)
            self._active_task_id = task_id
            ack = "Sure. I'll plan that out, perform the steps, and verify the result before I tell you it's done."
            await self._add_message(conversation_id, "assistant", ack)
            asyncio.create_task(self._execute_plan(conversation_id, task_id))
            return {"reply": ack, "task_id": task_id, "spoken": ack}
        # Plain conversational reply
        resp = await reg.generate(req, capability=Capability.GENERAL)
        reply = resp.content
        await self._add_message(conversation_id, "assistant", reply)
        # Always speak chat replies (chat-to-voice).
        asyncio.create_task(self._voice.speak(reply))
        return {"reply": reply, "task_id": None, "spoken": reply}

    async def _execute_plan(self, conversation_id: int, task_id: int) -> None:
        async def step_runner(idx: int, step: TaskStep, ctx: dict[str, Any]) -> ToolResult:
            tool = get_tool_registry().get(step.tool) if step.tool else None
            if not tool:
                return ToolResult(False, step.tool or "?", error=f"unknown tool: {step.tool}")
            return await tool(**(step.args or {}), _task_id=task_id)

        await self.task_engine.run(task_id, step_runner=step_runner)
        task = await self.task_engine.get(task_id)
        if task is None:
            return
        summary: str
        if task.status.value == "COMPLETED":
            summary = f"Done. {len(task.plan)} step(s) completed."
        elif task.status.value == "FAILED":
            summary = f"I couldn't finish that. Last issue: {task.error or 'unknown'}."
        elif task.status.value == "CANCELLED":
            summary = "Stopped as you asked."
        else:
            summary = f"Task ended in state {task.status.value}."
        await self._add_message(conversation_id, "assistant", summary, task_id=task_id)
        await self._voice.speak(summary)
        bus.emit(LogEvent(ts=now_iso(), level="INFO", message=f"task {task_id} → {task.status.value}", source="agent"))

    # ---------- conversation helpers
    async def _new_conversation(self, *, source: str) -> int:
        async with session_scope() as s:
            res = await s.execute(
                text("INSERT INTO conversations (started_at, source) VALUES (:now, :src)"),
                {"now": now_iso(), "src": source},
            )
            return res.lastrowid

    async def _add_message(self, conversation_id: int, role: str, content: str, *, task_id: int | None = None, voice_text: str | None = None) -> None:
        async with session_scope() as s:
            await s.execute(
                text(
                    "INSERT INTO messages (conversation_id, ts, role, content, voice_text, task_id) "
                    "VALUES (:cid, :ts, :role, :content, :vt, :tid)"
                ),
                {
                    "cid": conversation_id,
                    "ts": now_iso(),
                    "role": role,
                    "content": content,
                    "vt": voice_text,
                    "tid": task_id,
                },
            )

    async def list_messages(self, conversation_id: int, limit: int = 200) -> list[dict[str, Any]]:
        async with session_scope() as s:
            res = await s.execute(
                text("SELECT * FROM messages WHERE conversation_id=:cid ORDER BY id ASC LIMIT :l"),
                {"cid": conversation_id, "l": limit},
            )
            return [dict(r) for r in res.mappings()]

    async def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        async with session_scope() as s:
            res = await s.execute(
                text("SELECT * FROM conversations ORDER BY id DESC LIMIT :l"),
                {"l": limit},
            )
            return [dict(r) for r in res.mappings()]


def _should_plan(message: str) -> bool:
    triggers = (
        "create", "make", "write", "build", "prepare", "generate",
        "open", "publish", "upload", "find", "search", "research",
        "send", "schedule", "organize", "summarize",
    )
    msg = message.lower()
    return any(t in msg for t in triggers)


def _context_summary(records: list[Any]) -> str:
    out = []
    for r in records:
        out.append(f"- ({r.category}) {r.content}")
    return "\n".join(out[:8])


def _build_system(base: str, relevant: list[Any]) -> str:
    if not relevant:
        return base
    extra = "\n\nRelevant memory:\n" + _context_summary(relevant)
    return base + extra
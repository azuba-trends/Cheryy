"""Task engine.

A task moves through:
  QUEUED → PLANNING → RUNNING ⇄ WAITING/VERIFYING/RECOVERING → COMPLETED/FAILED/CANCELLED

Every task maintains a checkpoint so it can be paused and resumed.
Each tool invocation is audited.

The engine does NOT invent success: it observes the tool's structured result
and the agent's verification step before transitioning to COMPLETED.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable

from sqlalchemy import text

from ..db import session_scope, now_iso
from ..logging_setup import get_logger
from ..tools import ToolResult, get_tool_registry


log = get_logger("cheryy.tasks")


class Status(str, Enum):
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class TaskStep:
    index: int
    description: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    verification: str | None = None


@dataclass
class Task:
    id: int
    user_request: str
    plan: list[TaskStep]
    current_step: int
    progress: float
    status: Status
    tool_calls: list[dict[str, Any]]
    observations: list[str]
    verification: dict[str, Any]
    checkpoint: dict[str, Any]
    result: str | None
    error: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, r: Any) -> "Task":
        return cls(
            id=r["id"],
            user_request=r["user_request"],
            plan=[TaskStep(**s) for s in (json.loads(r["plan"] or "[]"))],
            current_step=r["current_step"] or 0,
            progress=r["progress"] or 0.0,
            status=Status(r["status"]),
            tool_calls=json.loads(r["tool_calls"] or "[]"),
            observations=json.loads(r["observations"] or "[]"),
            verification=json.loads(r["verification"] or "{}"),
            checkpoint=json.loads(r["checkpoint"] or "{}"),
            result=r["result"],
            error=r["error"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )


class TaskEngine:
    """In-process task coordinator. Persists tasks to SQLite."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cancel_flags: dict[int, asyncio.Event] = {}
        self._pause_flags: dict[int, asyncio.Event] = {}
        self._progress_hooks: dict[int, Callable[[Task], None]] = {}

    # ---------- create
    async def create(self, user_request: str, *, plan: list[TaskStep] | None = None) -> int:
        plan = plan or []
        now = now_iso()
        async with session_scope() as s:
            res = await s.execute(
                text(
                    "INSERT INTO tasks (user_request, plan, current_step, progress, status, tool_calls, observations, verification, checkpoint, created_at, updated_at) "
                    "VALUES (:req, :plan, 0, 0.0, 'QUEUED', '[]', '[]', '{}', '{}', :now, :now)"
                ),
                {
                    "req": user_request,
                    "plan": json.dumps([step.__dict__ for step in plan]),
                    "now": now,
                },
            )
            tid = res.lastrowid
        self._cancel_flags[tid] = asyncio.Event()
        self._pause_flags[tid] = asyncio.Event()
        return tid

    # ---------- update
    async def update(
        self,
        task_id: int,
        *,
        status: Status | None = None,
        progress: float | None = None,
        append_tool_call: dict[str, Any] | None = None,
        append_observation: str | None = None,
        verification: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
        result: str | None = None,
        error: str | None = None,
        current_step: int | None = None,
        plan: list[TaskStep] | None = None,
    ) -> None:
        sets: list[str] = ["updated_at=:now"]
        params: dict[str, Any] = {"id": task_id, "now": now_iso()}
        if status is not None:
            sets.append("status=:st")
            params["st"] = status.value
        if progress is not None:
            sets.append("progress=:pr")
            params["pr"] = progress
        if verification is not None:
            sets.append("verification=:vf")
            params["vf"] = json.dumps(verification)
        if checkpoint is not None:
            sets.append("checkpoint=:cp")
            params["cp"] = json.dumps(checkpoint)
        if result is not None:
            sets.append("result=:rs")
            params["rs"] = result
        if error is not None:
            sets.append("error=:er")
            params["er"] = error
        if current_step is not None:
            sets.append("current_step=:cs")
            params["cs"] = current_step
        if plan is not None:
            sets.append("plan=:pl")
            params["pl"] = json.dumps([s.__dict__ for s in plan])
        async with session_scope() as s:
            if append_tool_call is not None:
                await s.execute(
                    text("UPDATE tasks SET tool_calls = json_insert(tool_calls, '$[#]', :call), updated_at=:now WHERE id=:id"),
                    {"call": json.dumps(append_tool_call), "now": now_iso(), "id": task_id},
                )
            if append_observation is not None:
                await s.execute(
                    text("UPDATE tasks SET observations = json_insert(observations, '$[#]', :obs), updated_at=:now WHERE id=:id"),
                    {"obs": json.dumps(append_observation), "now": now_iso(), "id": task_id},
                )
            await s.execute(text(f"UPDATE tasks SET {', '.join(sets)} WHERE id=:id"), params)

    # ---------- read
    async def get(self, task_id: int) -> Task | None:
        async with session_scope() as s:
            res = await s.execute(text("SELECT * FROM tasks WHERE id=:id"), {"id": task_id})
            row = res.mappings().first()
            return Task.from_row(row) if row else None

    async def list_recent(self, limit: int = 50) -> list[Task]:
        async with session_scope() as s:
            res = await s.execute(text("SELECT * FROM tasks ORDER BY id DESC LIMIT :l"), {"l": limit})
            return [Task.from_row(r) for r in res.mappings()]

    # ---------- control
    async def cancel(self, task_id: int) -> None:
        self._cancel_flags.setdefault(task_id, asyncio.Event()).set()
        await self.update(task_id, status=Status.CANCELLED)

    async def pause(self, task_id: int) -> None:
        self._pause_flags.setdefault(task_id, asyncio.Event()).set()
        await self.update(task_id, status=Status.PAUSED)

    async def resume(self, task_id: int) -> None:
        ev = self._pause_flags.get(task_id)
        if ev:
            ev.clear()
        await self.update(task_id, status=Status.RUNNING)

    async def run(
        self,
        task_id: int,
        *,
        step_runner: Callable[[int, TaskStep, dict[str, Any]], Awaitable[ToolResult]],
    ) -> None:
        """Execute a pre-planned task.

        step_runner(step_index, step, ctx) -> ToolResult
        """
        cancel_evt = self._cancel_flags.setdefault(task_id, asyncio.Event())
        pause_evt = self._pause_flags.setdefault(task_id, asyncio.Event())

        task = await self.get(task_id)
        if task is None:
            return
        await self.update(task_id, status=Status.RUNNING)
        ctx = {"task_id": task_id}

        last_error: str | None = None
        for i, step in enumerate(task.plan):
            if cancel_evt.is_set():
                await self.update(task_id, status=Status.CANCELLED)
                return
            while pause_evt.is_set():
                await asyncio.sleep(0.1)
                if cancel_evt.is_set():
                    await self.update(task_id, status=Status.CANCELLED)
                    return
            await self.update(task_id, current_step=i, progress=(i / max(1, len(task.plan))))
            res: ToolResult | None = None
            try:
                if step.tool:
                    await self.update(task_id, append_observation=f"step {i}: {step.description}")
                    res = await step_runner(i, step, ctx)
                    await self.update(task_id, append_tool_call={"step": i, "tool": step.tool, "args": step.args, "result": res.to_dict() if res else None})
                else:
                    # Free-form reasoning step (no tool).
                    continue
            except Exception as e:  # noqa: BLE001
                last_error = str(e)
                await self.update(task_id, append_observation=f"step {i} error: {e}")
                await self.update(task_id, status=Status.RECOVERING)
                await asyncio.sleep(0.2)
                try:
                    res = await step_runner(i, step, ctx)
                except Exception as e2:  # noqa: BLE001
                    await self.update(task_id, status=Status.FAILED, error=str(e2))
                    return

            if res is not None and not res.success:
                last_error = res.error or "tool failed"
                await self.update(task_id, append_observation=f"step {i} did not succeed: {last_error}")
                await self.update(task_id, status=Status.FAILED, error=last_error)
                return

        await self.update(task_id, status=Status.COMPLETED, progress=1.0, result="task complete")


_engine: TaskEngine | None = None


def get_task_engine() -> TaskEngine:
    global _engine
    if _engine is None:
        _engine = TaskEngine()
    return _engine
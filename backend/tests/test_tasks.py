"""Task engine tests."""
from __future__ import annotations

import pytest

from cheryy.db import init_db
from cheryy.tasks import TaskStep, get_task_engine, Status


@pytest.mark.asyncio
async def test_task_create_and_run():
    await init_db()
    engine = get_task_engine()
    tid = await engine.create("hello", plan=[TaskStep(index=0, description="noop")])
    task = await engine.get(tid)
    assert task is not None
    assert task.status == Status.QUEUED


@pytest.mark.asyncio
async def test_task_cancel():
    await init_db()
    engine = get_task_engine()
    tid = await engine.create("x")
    await engine.cancel(tid)
    t = await engine.get(tid)
    assert t.status == Status.CANCELLED


@pytest.mark.asyncio
async def test_task_pause_resume():
    await init_db()
    engine = get_task_engine()
    tid = await engine.create("x")
    await engine.pause(tid)
    t = await engine.get(tid)
    assert t.status == Status.PAUSED
    await engine.resume(tid)
    t = await engine.get(tid)
    assert t.status == Status.RUNNING


@pytest.mark.asyncio
async def test_task_run_with_step_runner():
    await init_db()
    engine = get_task_engine()
    from cheryy.tools import ToolResult

    async def runner(idx, step, ctx):
        return ToolResult(True, step.tool or "noop", data={"step": idx})

    tid = await engine.create("plan test", plan=[
        TaskStep(index=0, description="step one", tool="noop"),
        TaskStep(index=1, description="step two", tool="noop"),
    ])
    await engine.run(tid, step_runner=runner)
    t = await engine.get(tid)
    assert t.status == Status.COMPLETED
    assert t.progress == 1.0
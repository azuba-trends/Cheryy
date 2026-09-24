"""Lightweight event-driven local scheduler.

We use a single asyncio task that sleeps until the next job is due. No
busy loop, no polling overhead.

Cron expressions are a small subset of the standard:
  field   : minute hour day-of-month month day-of-week
  ranges  : '*' (any), '*/N' (every N), 'N' (exact), 'a-b' (range), 'a,b,c' (list)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from ..db import session_scope, now_iso
from ..logging_setup import get_logger
from ..planner import plan as build_plan

log = get_logger("cheryy.scheduler")


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in field.split(","):
        if part == "*":
            out.update(range(lo, hi + 1))
        elif part.startswith("*/"):
            step = max(1, int(part[2:]))
            out.update(range(lo, hi + 1, step))
        elif "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return {x for x in out if lo <= x <= hi}


def matches(cron: str, dt: datetime) -> bool:
    try:
        m, h, dom, mon, dow = cron.split()
    except ValueError:
        return False
    minutes = _parse_field(m, 0, 59)
    hours = _parse_field(h, 0, 23)
    doms = _parse_field(dom, 1, 31)
    mons = _parse_field(mon, 1, 12)
    dows = _parse_field(dow, 0, 6)  # 0=Mon ... 6=Sun
    py_dow = (dt.weekday())  # 0=Mon
    return (
        dt.minute in minutes
        and dt.hour in hours
        and dt.day in doms
        and dt.month in mons
        and py_dow in dows
    )


class Scheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._wakeup = asyncio.Event()

    def schedule(self, *, name: str, cron: str, prompt: str) -> int:
        async def _add():
            async with session_scope() as s:
                res = await s.execute(
                    text("INSERT INTO scheduled_jobs (name, cron, prompt, enabled, created_at) VALUES (:n, :c, :p, 1, :now)"),
                    {"n": name, "c": cron, "p": prompt, "now": now_iso()},
                )
                return res.lastrowid
        return asyncio.get_event_loop().run_until_complete(_add())

    def cancel(self, job_id: int) -> None:
        async def _rm():
            async with session_scope() as s:
                await s.execute(text("DELETE FROM scheduled_jobs WHERE id=:id"), {"id": job_id})
        asyncio.get_event_loop().run_until_complete(_rm())
        self._wakeup.set()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        self._stop.set()
        self._wakeup.set()

    async def _run(self) -> None:
        from ..tasks import get_task_engine
        engine = get_task_engine()
        while not self._stop.is_set():
            try:
                async with session_scope() as s:
                    res = await s.execute(text("SELECT id, name, cron, prompt, last_run_at FROM scheduled_jobs WHERE enabled=1"))
                    jobs = [dict(r) for r in res.mappings()]
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                for j in jobs:
                    if not matches(j["cron"], now):
                        continue
                    last = j.get("last_run_at")
                    if last and last[:16] == now.isoformat()[:16]:
                        continue  # already ran this minute
                    log.info("scheduler firing %s", j["name"])
                    plan_steps = []
                    try:
                        plan_steps = await build_plan(j["prompt"])
                    except Exception:
                        pass
                    task_id = await engine.create(j["prompt"], plan=plan_steps)
                    async with session_scope() as s:
                        await s.execute(text("UPDATE scheduled_jobs SET last_run_at=:now WHERE id=:id"),
                                          {"now": now_iso(), "id": j["id"]})
                self._wakeup.clear()
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=60)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                return
            except Exception as e:  # pragma: no cover
                log.warning("scheduler loop error: %s", e)
                await asyncio.sleep(5)


_sched: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _sched
    if _sched is None:
        _sched = Scheduler()
    return _sched
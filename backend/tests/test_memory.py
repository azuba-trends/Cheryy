"""Memory tests."""
from __future__ import annotations

import pytest

from cheryy.db import init_db
from cheryy.memory import get_memory_store


@pytest.mark.asyncio
async def test_add_search_roundtrip():
    await init_db()
    store = get_memory_store()
    rid = await store.add("preference", "User prefers dark mode.", importance=0.9)
    assert rid > 0
    res = await store.search("dark mode")
    assert any("dark mode" in r.content for r in res)


@pytest.mark.asyncio
async def test_forget_deactivates_only():
    await init_db()
    store = get_memory_store()
    rid = await store.add("episodic", "User asked for a presentation.")
    await store.delete(rid)
    rec = await store.get(rid)
    assert rec is not None
    assert rec.active is False


@pytest.mark.asyncio
async def test_list_by_category():
    await init_db()
    store = get_memory_store()
    await store.add("profile", "name = Arindam")
    await store.add("profile", "language = English")
    await store.add("task", "yesterday task")
    profiles = await store.list(category="profile")
    assert len(profiles) == 2
    tasks = await store.list(category="task")
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_search_ranks_by_importance():
    await init_db()
    store = get_memory_store()
    a = await store.add("semantic", "CHERYY can browse the web.", importance=0.2)
    b = await store.add("semantic", "CHERYY is great at browsing the web for research.", importance=0.9)
    res = await store.search("browsing the web")
    assert res[0].id == b
    assert res[-1].id == a
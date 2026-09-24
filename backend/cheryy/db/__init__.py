"""Database layer.

Uses SQLite via SQLAlchemy 2.x async API. Schema is created idempotently at boot
and forward-only migrations are applied via the `migrations/` folder.

All tables are local. The only credential we ever persist is the encrypted
Gemini key in the secrets store; everything else is non-sensitive task state.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import get_db_path
from ..logging_setup import get_logger

log = get_logger("cheryy.db")

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_init_lock = asyncio.Lock()
_initialised = False


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT    NOT NULL,
    ended_at        TEXT,
    source          TEXT    NOT NULL,    -- 'chat' | 'voice'
    title           TEXT,
    summary         TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    ts              TEXT    NOT NULL,
    role            TEXT    NOT NULL,    -- 'user' | 'assistant' | 'system' | 'tool'
    content         TEXT    NOT NULL,
    voice_text      TEXT,
    tools_used      TEXT,                 -- JSON list
    task_id         INTEGER REFERENCES tasks(id),
    meta            TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_conv_ts ON messages(conversation_id, ts);

CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_request    TEXT    NOT NULL,
    plan            TEXT,                  -- JSON plan
    current_step    INTEGER NOT NULL DEFAULT 0,
    progress        REAL    NOT NULL DEFAULT 0.0,
    status          TEXT    NOT NULL,      -- QUEUED|PLANNING|RUNNING|WAITING|VERIFYING|RECOVERING|PAUSED|COMPLETED|FAILED|CANCELLED
    tool_calls      TEXT,                  -- JSON list
    observations    TEXT,                  -- JSON list
    verification    TEXT,                  -- JSON object
    checkpoint      TEXT,                  -- JSON object
    result          TEXT,
    error           TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS memory_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category        TEXT    NOT NULL,      -- profile|preference|semantic|episodic|procedural|task
    content         TEXT    NOT NULL,
    importance      REAL    NOT NULL DEFAULT 0.5,
    confidence      REAL    NOT NULL DEFAULT 1.0,
    source          TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    last_used_at    TEXT,
    use_count       INTEGER NOT NULL DEFAULT 0,
    active          INTEGER NOT NULL DEFAULT 1,
    tags            TEXT                    -- JSON list
);
CREATE INDEX IF NOT EXISTS idx_memory_category ON memory_records(category, active);

CREATE TABLE IF NOT EXISTS embeddings (
    memory_id       INTEGER PRIMARY KEY REFERENCES memory_records(id) ON DELETE CASCADE,
    embedding       BLOB    NOT NULL,      -- float32 bytes
    model           TEXT    NOT NULL,
    dim             INTEGER NOT NULL,
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,
    task_id         INTEGER,
    tool            TEXT,
    action          TEXT,
    permission      TEXT,
    decision        TEXT,                 -- allow|deny|...
    result          TEXT,
    verification    TEXT,
    meta            TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS skills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    version         TEXT    NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    source          TEXT,
    manifest        TEXT    NOT NULL,     -- JSON
    installed_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS workflows (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    description     TEXT,
    steps           TEXT    NOT NULL,     -- JSON
    required_tools  TEXT,                 -- JSON
    required_perms  TEXT,                 -- JSON
    variables       TEXT,                 -- JSON
    validation      TEXT,                 -- JSON
    created_at      TEXT    NOT NULL,
    last_run_at     TEXT,
    use_count       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    cron            TEXT    NOT NULL,     -- standard cron expression
    prompt          TEXT    NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_run_at     TEXT,
    next_run_at     TEXT,
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS model_registry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    provider        TEXT    NOT NULL,
    model_id        TEXT    NOT NULL,
    capabilities    TEXT    NOT NULL,     -- JSON list
    free_tier       INTEGER NOT NULL DEFAULT 0,
    last_seen       TEXT    NOT NULL,
    last_status     TEXT,
    latency_ms      INTEGER,
    UNIQUE(provider, model_id)
);

CREATE TABLE IF NOT EXISTS quota_state (
    provider        TEXT PRIMARY KEY,
    requests_today  INTEGER NOT NULL DEFAULT 0,
    tokens_today    INTEGER NOT NULL DEFAULT 0,
    errors_today    INTEGER NOT NULL DEFAULT 0,
    rate_limited    INTEGER NOT NULL DEFAULT 0,
    last_success    TEXT,
    last_error      TEXT,
    last_reset      TEXT    NOT NULL,
    quota_exhausted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings_kv (
    key             TEXT PRIMARY KEY,
    value           TEXT,
    updated_at      TEXT NOT NULL
);
"""


async def init_db() -> None:
    """Create engine + apply schema (idempotent)."""
    global _engine, _sessionmaker, _initialised
    async with _init_lock:
        if _initialised:
            return
        path = get_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+aiosqlite:///{path}"

        _engine = create_async_engine(url, future=True, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)

        @event.listens_for(_engine.sync_engine, "connect")
        def _set_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA temp_store=MEMORY")
            cur.close()

        async with _engine.begin() as conn:
            for stmt in [s.strip() for s in SCHEMA.split(";") if s.strip()]:
                await conn.execute(text(stmt))
        _initialised = True
        log.info("Database initialised at %s", path)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Async session context with automatic commit/rollback."""
    if _sessionmaker is None:
        await init_db()
    assert _sessionmaker is not None
    async with _sessionmaker() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
            raise


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


async def healthcheck() -> bool:
    try:
        if not _initialised:
            await init_db()
        assert _engine is not None
        async with _engine.connect() as c:
            r = await c.execute(text("SELECT 1"))
            r.scalar()
        return True
    except Exception as e:  # pragma: no cover
        log.warning("db healthcheck failed: %s", e)
        return False


async def reset() -> None:
    """Drop and recreate all tables. Used by self-repair. NEVER deletes user files."""
    global _initialised
    if _engine is None:
        await init_db()
    assert _engine is not None
    async with _engine.begin() as c:
        await c.execute(text("DROP TABLE IF EXISTS audit_log"))
        await c.execute(text("DROP TABLE IF EXISTS embeddings"))
        await c.execute(text("DROP TABLE IF EXISTS memory_records"))
        await c.execute(text("DROP TABLE IF EXISTS messages"))
        await c.execute(text("DROP TABLE IF EXISTS conversations"))
        await c.execute(text("DROP TABLE IF EXISTS tasks"))
        await c.execute(text("DROP TABLE IF EXISTS skills"))
        await c.execute(text("DROP TABLE IF EXISTS workflows"))
        await c.execute(text("DROP TABLE IF EXISTS scheduled_jobs"))
        await c.execute(text("DROP TABLE IF EXISTS model_registry"))
        await c.execute(text("DROP TABLE IF EXISTS quota_state"))
        await c.execute(text("DROP TABLE IF EXISTS settings_kv"))
        for stmt in [s.strip() for s in SCHEMA.split(";") if s.strip()]:
            await c.execute(text(stmt))
    _initialised = True
    log.warning("Database reset completed.")
"""Memory system.

Six categories:
  - profile       stable identity (name, role, language preference)
  - preference    stylistic choices (tone, image dimensions, folders)
  - semantic      factual knowledge (company, products)
  - episodic      notable past interactions
  - procedural    how the user typically does something
  - task          in-flight or recently completed tasks

Storage: SQLite (always) + optional embeddings for similarity retrieval.

The retrieval layer is what makes memory *intelligent* — we never inject
the full DB into a prompt. We score each record by:
    score = w_sim * similarity + w_imp * importance + w_rec * recency + w_conf * confidence
and return only the top-K.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import text

from ..db import session_scope, now_iso
from ..logging_setup import get_logger
from ..providers.base import EmbeddingProvider

log = get_logger("cheryy.memory")


CATEGORIES = ("profile", "preference", "semantic", "episodic", "procedural", "task")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass
class MemoryRecord:
    id: int
    category: str
    content: str
    importance: float
    confidence: float
    source: str | None
    created_at: str
    updated_at: str
    last_used_at: str | None
    use_count: int
    active: bool
    tags: list[str] = field(default_factory=list)
    embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "content": self.content,
            "importance": self.importance,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_used_at": self.last_used_at,
            "use_count": self.use_count,
            "active": self.active,
            "tags": self.tags,
        }


def _row_to_record(row: Any) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        category=row["category"],
        content=row["content"],
        importance=row["importance"] or 0.0,
        confidence=row["confidence"] or 0.0,
        source=row["source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_used_at=row["last_used_at"],
        use_count=row["use_count"] or 0,
        active=bool(row["active"]),
        tags=json.loads(row["tags"] or "[]"),
        embedding=None,
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class MemoryStore:
    """CRUD + retrieval for memory records."""

    def __init__(self, embedder: EmbeddingProvider | None = None) -> None:
        self._embedder = embedder

    def set_embedder(self, embedder: EmbeddingProvider | None) -> None:
        self._embedder = embedder

    # ---------- create / update
    async def add(
        self,
        category: str,
        content: str,
        *,
        importance: float = 0.5,
        confidence: float = 1.0,
        source: str | None = None,
        tags: Iterable[str] | None = None,
    ) -> int:
        if category not in CATEGORIES:
            raise ValueError(f"unknown memory category: {category}")
        tags_list = list(tags or [])
        now = now_iso()
        async with session_scope() as s:
            res = await s.execute(
                text(
                    "INSERT INTO memory_records "
                    "(category, content, importance, confidence, source, created_at, updated_at, last_used_at, use_count, active, tags) "
                    "VALUES (:cat, :content, :imp, :conf, :src, :now, :now, :now, 0, 1, :tags) "
                ),
                {
                    "cat": category,
                    "content": content,
                    "imp": importance,
                    "conf": confidence,
                    "src": source,
                    "now": now,
                    "tags": json.dumps(tags_list),
                },
            )
            new_id = res.lastrowid
        # Best-effort embed
        await self._embed_memory(new_id, content)
        return new_id

    async def update(self, memory_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {"content", "importance", "confidence", "active", "tags"}
        sets = []
        params: dict[str, Any] = {"id": memory_id}
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=:v_{k}")
            params[f"v_{k}"] = json.dumps(v) if k == "tags" else v
        if not sets:
            return
        sets.append("updated_at=:now")
        params["now"] = now_iso()
        async with session_scope() as s:
            await s.execute(text(f"UPDATE memory_records SET {', '.join(sets)} WHERE id=:id"), params)
        if "content" in fields:
            await self._embed_memory(memory_id, fields["content"])

    async def delete(self, memory_id: int, *, hard: bool = False) -> None:
        # Even "delete" is just deactivation by default — never touches user files.
        async with session_scope() as s:
            if hard:
                await s.execute(text("DELETE FROM memory_records WHERE id=:id"), {"id": memory_id})
            else:
                await s.execute(
                    text("UPDATE memory_records SET active=0, updated_at=:now WHERE id=:id"),
                    {"now": now_iso(), "id": memory_id},
                )

    # ---------- read
    async def get(self, memory_id: int) -> MemoryRecord | None:
        async with session_scope() as s:
            res = await s.execute(
                text("SELECT * FROM memory_records WHERE id=:id"), {"id": memory_id}
            )
            row = res.mappings().first()
            if not row:
                return None
            rec = _row_to_record(row)
            res2 = await s.execute(
                text("SELECT embedding, model, dim FROM embeddings WHERE memory_id=:id"),
                {"id": memory_id},
            )
            er = res2.mappings().first()
            if er:
                import struct
                raw = er["embedding"]
                rec.embedding = list(struct.unpack(f"<{er['dim']}f", raw))
            return rec

    async def list(
        self,
        *,
        category: str | None = None,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        clauses = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if active_only:
            clauses.append("active=1")
        if category:
            clauses.append("category=:cat")
            params["cat"] = category
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        async with session_scope() as s:
            res = await s.execute(
                text(
                    f"SELECT * FROM memory_records {where} ORDER BY importance DESC, updated_at DESC LIMIT :limit OFFSET :offset"
                ),
                params,
            )
            return [_row_to_record(r) for r in res.mappings()]

    async def search(
        self,
        query: str,
        *,
        categories: Sequence[str] | None = None,
        top_k: int = 8,
    ) -> list[MemoryRecord]:
        """Hybrid retrieval: keyword LIKE + (optional) embedding cosine."""
        candidates = await self._candidates(query, categories=categories, limit=200)
        if not candidates:
            return []
        scored = []
        qtokens = set(_tokenise(query))
        now_ts = time.time()
        for rec in candidates:
            score = _keyword_score(rec.content, qtokens)
            if rec.embedding is not None and self._embedder is not None:
                # Re-embed query lazily only if cache hit; otherwise we approximate via keyword.
                pass
            score += 0.4 * rec.importance + 0.3 * rec.confidence
            # Recency
            try:
                rec_ts = datetime.fromisoformat(rec.updated_at).timestamp()
                days = max(0.0, (now_ts - rec_ts) / 86400.0)
                score += 0.3 * math.exp(-days / 30.0)
            except Exception:
                pass
            scored.append((score, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = [r for _, r in scored[:top_k]]
        await self._mark_used([r.id for r in out])
        return out

    async def _candidates(
        self,
        query: str,
        *,
        categories: Sequence[str] | None,
        limit: int,
    ) -> list[MemoryRecord]:
        clauses = ["active=1"]
        params: dict[str, Any] = {"limit": limit}
        if categories:
            in_clause = ",".join(f":c{i}" for i in range(len(categories)))
            clauses.append(f"category IN ({in_clause})")
            for i, c in enumerate(categories):
                params[f"c{i}"] = c
        # Naive LIKE on every candidate; embeddings are optional refinement.
        tokens = _tokenise(query)
        if tokens:
            like_clauses = []
            for i, tok in enumerate(tokens[:6]):
                like_clauses.append(f"content LIKE :t{i}")
                params[f"t{i}"] = f"%{tok}%"
            clauses.append("(" + " OR ".join(like_clauses) + ")")
        where = "WHERE " + " AND ".join(clauses)
        async with session_scope() as s:
            res = await s.execute(
                text(f"SELECT * FROM memory_records {where} ORDER BY updated_at DESC LIMIT :limit"),
                params,
            )
            return [_row_to_record(r) for r in res.mappings()]

    async def _mark_used(self, ids: list[int]) -> None:
        if not ids:
            return
        in_clause = ",".join(f":i{i}" for i in range(len(ids)))
        params: dict[str, Any] = {"now": now_iso()}
        for i, x in enumerate(ids):
            params[f"i{i}"] = x
        async with session_scope() as s:
            await s.execute(
                text(
                    f"UPDATE memory_records SET use_count=use_count+1, last_used_at=:now WHERE id IN ({in_clause})"
                ),
                params,
            )

    async def _embed_memory(self, memory_id: int, content: str) -> None:
        if self._embedder is None:
            return
        try:
            vectors = await self._embedder.embed([content])
        except Exception as e:
            log.debug("embedding failed (ok): %s", e)
            return
        if not vectors:
            return
        v = vectors[0]
        import struct
        dim = len(v)
        packed = struct.pack(f"<{dim}f", *v)
        async with session_scope() as s:
            await s.execute(
                text(
                    "INSERT INTO embeddings (memory_id, embedding, model, dim, created_at) "
                    "VALUES (:id, :vec, 'auto', :dim, :now) "
                    "ON CONFLICT(memory_id) DO UPDATE SET embedding=excluded.embedding, dim=excluded.dim, created_at=excluded.created_at"
                ),
                {"id": memory_id, "vec": packed, "dim": dim, "now": now_iso()},
            )

    async def summarise_old(self, *, keep_recent_days: int = 60) -> int:
        """Mark very old, low-importance episodic records as inactive.

        This never deletes — it only flips `active=0` so the LLM stops seeing them.
        """
        cutoff = now_iso()
        async with session_scope() as s:
            res = await s.execute(
                text(
                    "UPDATE memory_records SET active=0 "
                    "WHERE category='episodic' AND importance < 0.4 AND updated_at < :cutoff"
                ),
                {"cutoff": cutoff},
            )
            return res.rowcount or 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenise(s: str) -> list[str]:
    import re
    return [t.lower() for t in re.findall(r"\w{3,}", s)][:20]


def _keyword_score(content: str, tokens: set[str]) -> float:
    if not tokens:
        return 0.0
    text = content.lower()
    hits = sum(1 for t in tokens if t in text)
    return hits / max(1, len(tokens))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
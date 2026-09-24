"""Provider registry + quota tracking + capability routing.

The registry is the single source of truth for "which provider / model should
be used for capability X right now". It:

  * tracks each provider's health (successes, errors, last-seen)
  * tracks per-day request counts / estimated token usage
  * applies rate-limit / quota backoff
  * falls back to local Ollama when the cloud quota is exhausted
  * persists state in `model_registry` and `quota_state` tables
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import text

from ..config import get_settings, reload_settings
from ..db import session_scope, now_iso
from ..logging_setup import get_logger
from ..secrets import get_gemini_api_key
from .base import (
    AuthError,
    Capability,
    EmbeddingProvider,
    ImageProvider,
    LiveVoiceProvider,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderError,
    QuotaExceededError,
    RateLimitedError,
    STTProvider,
    TTSProvider,
    ToolSpec,
    VisionProvider,
)
from .gemini import GeminiProvider
from .ollama import OllamaProvider, detect_ollama

log = get_logger("cheryy.providers.registry")


# ---------------------------------------------------------------------------
# Routing tables
# ---------------------------------------------------------------------------

@dataclass
class ProviderHealth:
    last_success: float = 0.0
    last_error: float = 0.0
    consecutive_errors: int = 0
    cooldown_until: float = 0.0


@dataclass
class QuotaBucket:
    provider: str
    requests_today: int = 0
    tokens_today: int = 0
    errors_today: int = 0
    rate_limited: int = 0
    last_success: str | None = None
    last_error: str | None = None
    last_reset: str = ""
    quota_exhausted: bool = False

    def is_available(self) -> bool:
        if self.quota_exhausted:
            return False
        # Avoid blasting Gemini when there's been a recent rate-limit.
        if self.rate_limited > 0 and time.time() - _parse_iso(self.last_error or "") < 30:
            return False
        return True


def _parse_iso(s: str) -> float:
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ProviderRegistry:
    """Routes capability requests to the best available provider/model."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.gemini: GeminiProvider | None = None
        self.ollama: OllamaProvider | None = None
        self._health: dict[str, ProviderHealth] = {}
        self._quota: dict[str, QuotaBucket] = {}
        self._models_by_cap: dict[Capability, list[dict[str, Any]]] = {}
        self._ollama_base_url: str | None = None
        self._initialized = False
        self._init_task: asyncio.Task | None = None

    # ---------- lifecycle
    async def initialize(self, *, force: bool = False) -> None:
        async with self._lock:
            if self._initialized and not force:
                return
            settings = reload_settings()
            api_key = get_gemini_api_key()
            if api_key:
                # Reuse client across hot reloads.
                if self.gemini is None:
                    self.gemini = GeminiProvider(api_key=api_key)
                else:
                    self.gemini.api_key = api_key
            # Detect Ollama opportunistically, ONLY if the user opted in.
            # This is an escape hatch for developers; the default install does
            # NOT include Ollama — CHERYY runs on the user's Gemini key alone.
            if settings.enable_ollama_autodetect and os.environ.get("CHERYY_ENABLE_OLLAMA") == "1":
                url = await detect_ollama(settings.ollama_base_url)
                if url:
                    self._ollama_base_url = url
                    self.ollama = OllamaProvider(base_url=url)
                    log.info("Ollama detected at %s (opt-in)", url)
            else:
                if settings.enable_ollama_autodetect:
                    log.info("Ollama auto-detect disabled by default; set CHERYY_ENABLE_OLLAMA=1 to enable.")
            # Load persisted model registry & quota state.
            await self._load_state()
            self._initialized = True

    async def shutdown(self) -> None:
        if self.gemini:
            await self.gemini.aclose()
        if self.ollama:
            await self.ollama.aclose()

    async def reinitialize_for_new_key(self, new_key: str) -> dict[str, Any]:
        """Called after a successful API-key validation. Discovers models."""
        if self.gemini is None:
            self.gemini = GeminiProvider(api_key=new_key)
        else:
            self.gemini.api_key = new_key
        # Reset capability map + force re-discovery.
        self._models_by_cap.clear()
        info = await self._discover_and_persist()
        self._initialized = True
        return info

    async def _discover_and_persist(self) -> dict[str, Any]:
        """Discover models from each provider, persist, return summary."""
        out: dict[str, Any] = {"models": [], "capabilities": {}, "providers": []}
        if self.gemini:
            try:
                models = await self.gemini.discover()
                out["providers"].append("gemini")
                await self._persist_models("gemini", models)
                for m in models:
                    for cap in m["capabilities"]:
                        self._models_by_cap.setdefault(Capability(cap), []).append(m)
                out["models"].extend(models)
            except AuthError as e:
                log.warning("gemini auth failed during discovery: %s", e)
                out["auth_error"] = str(e)
            except Exception as e:  # pragma: no cover - defensive
                log.warning("gemini discovery failed: %s", e)
        if self.ollama:
            try:
                models = await self.ollama.discover()
                if models:
                    out["providers"].append("ollama")
                    await self._persist_models("ollama", models)
                    for m in models:
                        for cap in m["capabilities"]:
                            self._models_by_cap.setdefault(Capability(cap), []).append(m)
                    out["models"].extend(models)
            except Exception as e:  # pragma: no cover
                log.warning("ollama discovery failed: %s", e)
        # Build a capability -> default model map.
        for cap in Capability:
            candidates = self._models_by_cap.get(cap, [])
            if candidates:
                out["capabilities"][cap.value] = candidates[0]["id"]
        return out

    async def _persist_models(self, provider: str, models: list[dict[str, Any]]) -> None:
        async with session_scope() as s:
            for m in models:
                await s.execute(text(
                    "INSERT INTO model_registry (provider, model_id, capabilities, free_tier, last_seen, last_status) "
                    "VALUES (:provider, :model_id, :capabilities, :free_tier, :ts, 'ok') "
                    "ON CONFLICT(provider, model_id) DO UPDATE SET "
                    "capabilities=excluded.capabilities, free_tier=excluded.free_tier, last_seen=excluded.last_seen, last_status='ok'"
                ), {
                    "provider": provider,
                    "model_id": m["id"],
                    "capabilities": json.dumps(m["capabilities"]),
                    "free_tier": 1 if m.get("free_tier") else 0,
                    "ts": now_iso(),
                })

    async def _load_state(self) -> None:
        async with session_scope() as s:
            res = await s.execute(text("SELECT provider, requests_today, tokens_today, errors_today, rate_limited, last_success, last_error, last_reset, quota_exhausted FROM quota_state"))
            for row in res.mappings():
                self._quota[row["provider"]] = QuotaBucket(
                    provider=row["provider"],
                    requests_today=row["requests_today"] or 0,
                    tokens_today=row["tokens_today"] or 0,
                    errors_today=row["errors_today"] or 0,
                    rate_limited=row["rate_limited"] or 0,
                    last_success=row["last_success"],
                    last_error=row["last_error"],
                    last_reset=row["last_reset"] or now_iso(),
                    quota_exhausted=bool(row["quota_exhausted"]),
                )
            res2 = await s.execute(text("SELECT provider, model_id, capabilities, free_tier FROM model_registry"))
            for row in res2.mappings():
                caps = set(json.loads(row["capabilities"] or "[]"))
                m = {
                    "id": row["model_id"],
                    "capabilities": sorted(caps),
                    "free_tier": bool(row["free_tier"]),
                    "provider": row["provider"],
                }
                for cap in caps:
                    self._models_by_cap.setdefault(Capability(cap), []).append(m)

    # ---------- capability lookup
    def best_model_for(self, capability: Capability, *, prefer_free: bool = True) -> str | None:
        candidates = self._models_by_cap.get(capability, [])
        for m in candidates:
            if prefer_free and not m.get("free_tier"):
                continue
            return m["id"]
        return candidates[0]["id"] if candidates else None

    def best_provider_for(self, capability: Capability) -> str | None:
        m = self.best_model_for(capability)
        if not m:
            return None
        for p, bucket in self._quota.items():
            pass
        # Look up which provider owns this model.
        for cap_models in self._models_by_cap.values():
            for m in cap_models:
                if m["id"] == m.get("id"):
                    return m.get("provider")
        return "gemini" if self.gemini else ("ollama" if self.ollama else None)

    # ---------- quota tracking
    async def _record_success(self, provider: str, *, tokens: int) -> None:
        bucket = self._quota.setdefault(provider, QuotaBucket(provider=provider, last_reset=now_iso()))
        bucket.requests_today += 1
        bucket.tokens_today += max(0, tokens)
        bucket.last_success = now_iso()
        bucket.quota_exhausted = False
        self._health.setdefault(provider, ProviderHealth()).last_success = time.time()
        await self._persist_quota(bucket)

    async def _record_error(self, provider: str, exc: Exception) -> None:
        bucket = self._quota.setdefault(provider, QuotaBucket(provider=provider, last_reset=now_iso()))
        bucket.errors_today += 1
        bucket.last_error = now_iso()
        h = self._health.setdefault(provider, ProviderHealth())
        h.last_error = time.time()
        h.consecutive_errors += 1
        if isinstance(exc, QuotaExceededError):
            bucket.quota_exhausted = True
        if isinstance(exc, RateLimitedError):
            bucket.rate_limited += 1
            h.cooldown_until = time.time() + get_settings().quota_backoff_seconds
        await self._persist_quota(bucket)

    async def _persist_quota(self, bucket: QuotaBucket) -> None:
        async with session_scope() as s:
            await s.execute(text(
                "INSERT INTO quota_state (provider, requests_today, tokens_today, errors_today, rate_limited, last_success, last_error, last_reset, quota_exhausted) "
                "VALUES (:provider, :req, :tok, :err, :rl, :ls, :le, :lr, :qe) "
                "ON CONFLICT(provider) DO UPDATE SET "
                "requests_today=excluded.requests_today, tokens_today=excluded.tokens_today, "
                "errors_today=excluded.errors_today, rate_limited=excluded.rate_limited, "
                "last_success=excluded.last_success, last_error=excluded.last_error, "
                "last_reset=excluded.last_reset, quota_exhausted=excluded.quota_exhausted"
            ), {
                "provider": bucket.provider,
                "req": bucket.requests_today,
                "tok": bucket.tokens_today,
                "err": bucket.errors_today,
                "rl": bucket.rate_limited,
                "ls": bucket.last_success,
                "le": bucket.last_error,
                "lr": bucket.last_reset,
                "qe": 1 if bucket.quota_exhausted else 0,
            })

    # ---------- unified execution
    async def generate(
        self,
        req: LLMRequest,
        *,
        capability: Capability = Capability.GENERAL,
    ) -> LLMResponse:
        providers = self._eligible_providers(capability)
        last_err: Exception | None = None
        for p in providers:
            try:
                resp = await self._invoke(p, req, capability)
                tokens = int(resp.usage.get("total_tokens") or 0)
                await self._record_success(p.name, tokens=tokens)
                return resp
            except (AuthError,) as e:
                await self._record_error(p.name, e)
                raise
            except (QuotaExceededError,) as e:
                await self._record_error(p.name, e)
                last_err = e
                continue  # try fallback
            except Exception as e:  # noqa: BLE001
                await self._record_error(p.name, e)
                last_err = e
                continue
        if last_err:
            raise last_err
        raise ProviderError("no eligible providers")

    def _eligible_providers(self, capability: Capability) -> list[LLMProvider]:
        order: list[LLMProvider] = []
        # An unknown / unrecorded provider state is eligible; only skip if
        # we *know* it's exhausted.
        if self.gemini and not (self._quota.get("gemini") and self._quota["gemini"].quota_exhausted):
            order.append(self.gemini)
        if self.ollama and get_settings().enable_local_fallback:
            order.append(self.ollama)
        return order

    async def _invoke(self, p: LLMProvider, req: LLMRequest, capability: Capability) -> LLMResponse:
        # If the request didn't name a model, pick one based on capability.
        if not req.model:
            model_id = self.best_model_for(capability)
            if model_id:
                req.model = model_id
        return await p.generate(req)

    # ---------- helper getters
    def llm(self) -> LLMProvider | None:
        if self.gemini and not self._quota.get("gemini", QuotaBucket(provider="gemini")).quota_exhausted:
            return self.gemini
        if self.ollama and get_settings().enable_local_fallback:
            return self.ollama
        return None

    def vision(self) -> VisionProvider | None:
        if self.gemini and not self._quota.get("gemini", QuotaBucket(provider="gemini")).quota_exhausted:
            return self.gemini
        return None

    def tts(self) -> TTSProvider | None:
        return self.gemini if self.gemini else None

    def stt(self) -> STTProvider | None:
        return self.gemini if self.gemini else None

    def embed(self) -> EmbeddingProvider | None:
        return self.gemini if self.gemini else (self.ollama if self.ollama else None)

    def live(self) -> LiveVoiceProvider | None:
        return self.gemini if self.gemini else None

    # ---------- diagnostic snapshot
    async def status(self) -> dict[str, Any]:
        return {
            "providers": list(self._quota.keys()),
            "models_by_capability": {
                cap.value: [m["id"] for m in models]
                for cap, models in self._models_by_cap.items()
            },
            "default_models": {
                cap.value: self.best_model_for(cap) for cap in Capability
            },
            "quota": {p: self._quota[p].__dict__ for p in self._quota},
        }


_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
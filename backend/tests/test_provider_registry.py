"""Provider registry tests — focus on the routing & fallback logic."""
from __future__ import annotations

import pytest

from cheryy.providers.base import Capability, ProviderError, QuotaExceededError, RateLimitedError, LLMMessage, LLMRequest
from cheryy.providers.registry import ProviderRegistry


@pytest.mark.asyncio
async def test_registry_status_before_init():
    reg = ProviderRegistry()
    status = await reg.status()
    assert "providers" in status
    assert "default_models" in status
    assert "models_by_capability" in status


class _FakeProvider:
    name = "fake"
    def __init__(self, fail: Exception | None = None):
        self._fail = fail
        self.calls = 0
    async def generate(self, req: LLMRequest) -> "LLMResponse":
        from cheryy.providers.base import LLMResponse
        self.calls += 1
        if self._fail is not None:
            raise self._fail
        return LLMResponse(content="ok", model="fake", usage={"total_tokens": 7})


@pytest.mark.asyncio
async def test_falls_back_on_quota():
    reg = ProviderRegistry()
    primary = _FakeProvider(QuotaExceededError("daily quota exhausted"))
    fallback = _FakeProvider()
    reg.gemini = primary  # type: ignore[assignment]
    reg.ollama = fallback  # type: ignore[assignment]
    from cheryy.config import get_settings
    get_settings().enable_local_fallback = True
    resp = await reg.generate(LLMRequest(messages=[LLMMessage(role="user", content="ping")]))
    assert resp.content == "ok"
    assert fallback.calls == 1
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_raises_on_quota_when_no_fallback():
    reg = ProviderRegistry()
    primary = _FakeProvider(QuotaExceededError("quota"))
    reg.gemini = primary  # type: ignore[assignment]
    # No ollama fallback
    from cheryy.config import get_settings
    get_settings().enable_local_fallback = False
    with pytest.raises(QuotaExceededError):
        await reg.generate(LLMRequest(messages=[LLMMessage(role="user", content="ping")]))
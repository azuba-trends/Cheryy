"""Provider tests (no network required)."""
from __future__ import annotations

import pytest

from cheryy.providers.gemini import (
    GeminiProvider,
    _looks_free_tier,
    infer_capabilities,
)
from cheryy.providers.base import (
    AuthError,
    Capability,
    ProviderError,
    QuotaExceededError,
    RateLimitedError,
)


def test_infer_capabilities_flash():
    caps = infer_capabilities("gemini-1.5-flash")
    assert Capability.GENERAL in caps
    assert Capability.VISION in caps
    assert Capability.TOOLING in caps


def test_infer_capabilities_pro():
    caps = infer_capabilities("gemini-1.5-pro")
    assert Capability.PLANNER in caps
    assert Capability.GENERAL in caps


def test_infer_capabilities_tts():
    caps = infer_capabilities("gemini-2.5-flash-preview-tts")
    assert Capability.TTS in caps


def test_infer_capabilities_embedding():
    caps = infer_capabilities("text-embedding-004")
    assert Capability.EMBEDDING in caps


def test_infer_capabilities_unknown_still_safe():
    caps = infer_capabilities("totally-unknown-model")
    # No crash, may have no caps.
    assert isinstance(caps, set)


def test_free_tier_lookup():
    assert _looks_free_tier("gemini-1.5-flash", {}) is True
    assert _looks_free_tier("gemini-1.5-flash-latest", {}) is True
    assert _looks_free_tier("gemini-1.5-pro", {}) is False
    assert _looks_free_tier("gemini-2.0-flash-exp", {}) is True


@pytest.mark.asyncio
async def test_provider_missing_key_raises_auth():
    p = GeminiProvider(api_key=None)
    with pytest.raises(AuthError):
        await p.list_models()


def test_raise_for_status_mapping():
    """Static smoke test: the error classifier picks the right category."""
    from cheryy.providers.gemini import _raise_for_status
    import httpx

    class _Resp:
        status_code = 401
        text = "API_KEY_INVALID"
        def json(self): return {"error": {"message": "API_KEY_INVALID"}}

    class _QuotaResp:
        status_code = 429
        text = "RESOURCE_EXHAUSTED quota exceeded"
        def json(self): return {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota exceeded"}}

    class _RLResp:
        status_code = 429
        text = "rate limited"
        def json(self): return {"error": {"message": "rate limited"}}

    class _Ok:
        status_code = 200
        text = ""
        def json(self): return {}

    # Auth error
    try:
        _raise_for_status(_Resp())
    except AuthError:
        pass
    else:
        pytest.fail("expected AuthError")
    # Quota
    try:
        _raise_for_status(_QuotaResp())
    except QuotaExceededError:
        pass
    else:
        pytest.fail("expected QuotaExceededError")
    # Rate limit
    try:
        _raise_for_status(_RLResp())
    except RateLimitedError:
        pass
    else:
        pytest.fail("expected RateLimitedError")
    # Ok
    _raise_for_status(_Ok())
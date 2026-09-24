"""Provider abstractions and shared types."""
from __future__ import annotations

import asyncio
import enum
import random
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Iterable


class Capability(str, enum.Enum):
    GENERAL = "general_reasoning"
    PLANNER = "agent_planning"
    VISION = "multimodal_vision"
    LIVE_VOICE = "live_voice"
    TTS = "text_to_speech"
    STT = "transcription"
    TOOLING = "structured_tool_calling"
    EMBEDDING = "embedding"
    IMAGE_GEN = "image_generation"
    FAST = "fast_inference"


class ProviderError(Exception):
    """Generic provider failure."""


class QuotaExceededError(ProviderError):
    """Daily / monthly quota exhausted."""


class RateLimitedError(ProviderError):
    """Transient per-minute rate-limit."""


class AuthError(ProviderError):
    """API key invalid, expired, or restricted."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LLMMessage:
    role: str                       # system | user | assistant | tool
    content: str | list[dict[str, Any]] = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    def to_openai_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]           # JSON schema
    requires_confirmation: bool = False


@dataclass
class LLMRequest:
    messages: list[LLMMessage]
    model: str | None = None
    temperature: float = 0.4
    max_tokens: int = 2048
    tools: list[ToolSpec] = field(default_factory=list)
    tool_choice: str | None = None        # "auto" | "none" | "required"
    response_format_json: bool = False
    images: list[bytes] = field(default_factory=list)  # multimodal
    system: str | None = None
    stop: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str
    model: str
    finish_reason: str = "stop"
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] | None = None
    latency_ms: int = 0


# ---------------------------------------------------------------------------
# Provider interfaces
# ---------------------------------------------------------------------------

class LLMProvider:
    name = "base"

    async def generate(self, req: LLMRequest) -> LLMResponse:  # pragma: no cover - abstract
        raise NotImplementedError

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:  # pragma: no cover - abstract
        raise NotImplementedError
        yield ""  # make this an async generator

    async def list_models(self) -> list[dict[str, Any]]:
        return []

    async def healthcheck(self) -> bool:
        try:
            await self.generate(LLMRequest(
                messages=[LLMMessage(role="user", content="ping")],
                max_tokens=8,
            ))
            return True
        except Exception:
            return False


class VisionProvider:
    """Stand-alone vision interface. Concrete providers may also be an
    LLMProvider; see GeminiProvider for the concrete composition."""

    async def describe(self, image: bytes, prompt: str = "Describe the image.") -> str:  # pragma: no cover
        raise NotImplementedError


class TTSProvider:
    async def synth(self, text: str, *, voice: str | None = None, language: str | None = None) -> bytes:
        raise NotImplementedError  # pragma: no cover


class STTProvider:
    async def transcribe(self, audio: bytes, *, language: str | None = None) -> str:
        raise NotImplementedError  # pragma: no cover


class LiveVoiceProvider:
    """Real-time bidirectional voice. The base class is a no-op; Gemini Live
    provides a concrete implementation."""

    async def start(self, *, system: str, voice: str | None = None) -> None:
        raise NotImplementedError  # pragma: no cover

    async def stop(self) -> None: ...  # pragma: no cover

    async def send_audio(self, chunk: bytes) -> None: ...  # pragma: no cover

    async def send_text(self, text: str) -> None: ...  # pragma: no cover

    async def receive(self) -> AsyncIterator[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError
        yield {}  # async generator


class EmbeddingProvider:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError  # pragma: no cover


class ImageProvider:
    async def generate(self, prompt: str, *, size: tuple[int, int] = (1024, 1024)) -> bytes:
        raise NotImplementedError  # pragma: no cover


# ---------------------------------------------------------------------------
# Retry helpers (used by Gemini + Ollama)
# ---------------------------------------------------------------------------

_RETRYABLE = (RateLimitedError, asyncio.TimeoutError)


async def with_retries(
    fn: Callable[[], Any],
    *,
    max_retries: int = 3,
    base_delay: float = 0.8,
    on_error: Callable[[Exception, int], None] | None = None,
) -> Any:
    """Run an async function with exponential backoff for transient errors.

    Quota errors are NOT retried — they're surfaced so the registry can switch
    models. Only transient (rate-limit, timeout, network) failures are retried.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except (QuotaExceededError, AuthError) as e:
            if on_error:
                on_error(e, attempt)
            raise
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if not isinstance(e, _RETRYABLE) and not _is_transient(e):
                raise
            if attempt >= max_retries:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.25)
            if on_error:
                on_error(e, attempt)
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc
    return None  # unreachable


def _is_transient(exc: Exception) -> bool:
    msg = (str(exc) or "").lower()
    return any(s in msg for s in (
        "timeout", "timed out", "temporarily", "503", "502", "504",
        "connection reset", "connection aborted", "network",
    ))
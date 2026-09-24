"""Provider abstractions.

CHERYY supports a small set of orthogonal providers:

  LLMProvider        : text + structured tool calls
  VisionProvider     : image understanding
  LiveVoiceProvider  : real-time duplex voice (Gemini Live API)
  TTSProvider        : synthesise speech from text
  STTProvider        : transcribe recorded speech to text
  EmbeddingProvider  : embeddings for memory retrieval
  ImageProvider      : text -> image

The GeminiProvider implements all of these except ImageProvider (which is
optional and uses an external service).

Local Ollama is supported as an optional LLM / embedding fallback. CHERYY never
auto-downloads large models — it just detects what's already on the machine.
"""
from __future__ import annotations

from .base import (
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ToolSpec,
    VisionProvider,
    LiveVoiceProvider,
    TTSProvider,
    STTProvider,
    EmbeddingProvider,
    ImageProvider,
    Capability,
    ProviderError,
    QuotaExceededError,
    RateLimitedError,
    AuthError,
)
from .registry import ProviderRegistry, get_registry
from .gemini import GeminiProvider
from .ollama import OllamaProvider, detect_ollama

__all__ = [
    "LLMMessage", "LLMProvider", "LLMRequest", "LLMResponse", "ToolSpec",
    "VisionProvider", "LiveVoiceProvider", "TTSProvider", "STTProvider",
    "EmbeddingProvider", "ImageProvider",
    "Capability", "ProviderError", "QuotaExceededError", "RateLimitedError", "AuthError",
    "ProviderRegistry", "get_registry",
    "GeminiProvider", "OllamaProvider", "detect_ollama",
]
"""Optional Ollama local provider.

CHERYY never *requires* Ollama — if it isn't installed we silently skip it.
If it is, we discover installed models and use them as a fallback for LLM
and embeddings (capability permitting).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

import httpx

from .base import (
    Capability,
    EmbeddingProvider,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderError,
    ToolSpec,
    with_retries,
)
from ..logging_setup import get_logger
from ..config import get_settings

log = get_logger("cheryy.providers.ollama")


async def detect_ollama(base_url: str | None = None) -> str | None:
    """Return the working base URL of a local Ollama daemon or None."""
    candidates = []
    if base_url:
        candidates.append(base_url)
    s = get_settings()
    if s.ollama_base_url:
        candidates.append(s.ollama_base_url)
    candidates.append("http://127.0.0.1:11434")
    for url in candidates:
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"{url.rstrip('/')}/api/tags")
                if r.status_code == 200:
                    return url.rstrip("/")
        except Exception:
            continue
    return None


class OllamaProvider(LLMProvider, EmbeddingProvider):
    name = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> list[dict[str, Any]]:
        r = await self._client.get(f"{self.base_url}/api/tags")
        r.raise_for_status()
        return r.json().get("models", [])

    async def discover(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            models = await self.list_models()
        except Exception as e:
            log.info("ollama not reachable: %s", e)
            return out
        for m in models:
            mid = m.get("name") or m.get("model", "")
            if not mid:
                continue
            caps = {Capability.GENERAL, Capability.FAST, Capability.TOOLING}
            if "embed" in mid:
                caps = {Capability.EMBEDDING}
            out.append({
                "id": mid,
                "raw": m,
                "capabilities": sorted(c.value for c in caps),
                "free_tier": True,
                "display_name": mid,
                "description": "",
            })
        return out

    # ---------- generate (OpenAI-compatible passthrough when available, else native /api/chat)
    async def generate(self, req: LLMRequest) -> LLMResponse:
        model = req.model or (req.metadata or {}).get("model") or "llama3.1"
        url = f"{self.base_url}/api/chat"
        msgs = []
        if req.system:
            msgs.append({"role": "system", "content": req.system})
        for m in req.messages:
            msgs.append({"role": m.role, "content": m.content if isinstance(m.content, str) else ""})
        body = {
            "model": model,
            "messages": msgs,
            "stream": False,
            "options": {"temperature": req.temperature, "num_predict": req.max_tokens},
        }
        if req.tools:
            body["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in req.tools
            ]

        async def _do() -> LLMResponse:
            t0 = time.time()
            r = await self._client.post(url, json=body)
            r.raise_for_status()
            j = r.json()
            msg = j.get("message", {})
            tool_calls = None
            if msg.get("tool_calls"):
                tool_calls = []
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    tool_calls.append({
                        "id": f"call_{int(time.time()*1000)}",
                        "type": "function",
                        "function": {"name": fn.get("name", ""), "arguments": fn.get("arguments", "{}")},
                    })
            return LLMResponse(
                content=msg.get("content", ""),
                model=model,
                finish_reason="stop" if not tool_calls else "tool_calls",
                tool_calls=tool_calls,
                usage={
                    "prompt_tokens": j.get("prompt_eval_count", 0),
                    "completion_tokens": j.get("eval_count", 0),
                    "total_tokens": (j.get("prompt_eval_count", 0) or 0) + (j.get("eval_count", 0) or 0),
                },
                raw=j,
                latency_ms=int((time.time() - t0) * 1000),
            )

        return await with_retries(_do, max_retries=1)

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        model = req.model or "llama3.1"
        url = f"{self.base_url}/api/chat"
        msgs = []
        if req.system:
            msgs.append({"role": "system", "content": req.system})
        for m in req.messages:
            msgs.append({"role": m.role, "content": m.content if isinstance(m.content, str) else ""})
        body = {"model": model, "messages": msgs, "stream": True}
        async with self._client.stream("POST", url, json=body) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line:
                    continue
                try:
                    j = __import__("json").loads(line)
                except Exception:
                    continue
                chunk = j.get("message", {}).get("content", "")
                if chunk:
                    yield chunk

    # ---------- embeddings
    async def embed(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.base_url}/api/embeddings"
        out: list[list[float]] = []
        for t in texts:
            r = await self._client.post(url, json={"model": "nomic-embed-text", "prompt": t})
            r.raise_for_status()
            j = r.json()
            out.append(j.get("embedding", []))
        return out
"""Google Gemini provider implementation.

Talks to the public Gemini API (`generativelanguage.googleapis.com`):

  * REST generateContent for LLM + vision
  * REST listModels for capability discovery
  * Live (WebSocket) for real-time voice
  * REST embedContent for embeddings
  * REST synthesizeSpeech / transcribe for TTS / STT

Quota / rate-limit errors are surfaced as typed exceptions so the registry
can switch models. Free-tier-capable models are preferred.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Any, AsyncIterator

import httpx

from .base import (
    AuthError,
    Capability,
    EmbeddingProvider,
    LiveVoiceProvider,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderError,
    QuotaExceededError,
    RateLimitedError,
    STTProvider,
    ToolSpec,
    TTSProvider,
    VisionProvider,
    with_retries,
)
from ..logging_setup import get_logger
from ..config import get_settings

log = get_logger("cheryy.providers.gemini")


# ---------------------------------------------------------------------------
# Capability inference
# ---------------------------------------------------------------------------

_CAP_HINTS: dict[str, set[Capability]] = {
    # Live voice candidates
    "live": {Capability.LIVE_VOICE, Capability.GENERAL},
    # Native TTS (gemini-2.5-flash-preview-tts, gemini-2.5-pro-preview-tts)
    "tts": {Capability.TTS},
    # Native audio transcription (gemini-2.5-flash with audio)
    "audio": {Capability.STT, Capability.GENERAL},
    # Text embeddings
    "embedding": {Capability.EMBEDDING},
    "text-embedding": {Capability.EMBEDDING},
    # Image generation (Imagen family)
    "imagen": {Capability.IMAGE_GEN},
    # Flash / pro general models
    "flash": {Capability.GENERAL, Capability.TOOLING, Capability.FAST},
    "pro": {Capability.GENERAL, Capability.PLANNER, Capability.TOOLING},
    "nano": {Capability.FAST},
}


def infer_capabilities(model_id: str, declared: list[str] | None = None) -> set[Capability]:
    """Map a model id to a set of capabilities using simple heuristics.

    This is robust to vendor renames because it's content-based, not
    enumerated, and we always defer to declared input/output modalities if the
    API tells us.
    """
    caps: set[Capability] = set()
    mid = model_id.lower()
    for hint, c in _CAP_HINTS.items():
        if hint in mid:
            caps |= c

    # Always support tooling when the family does.
    if Capability.GENERAL in caps:
        caps.add(Capability.TOOLING)

    # Vision: most current Gemini text models accept image input.
    if any(k in mid for k in ("flash", "pro", "nano")) and "embedding" not in mid and "tts" not in mid:
        caps.add(Capability.VISION)

    return caps


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    body = resp.text
    code = 0
    status = ""
    try:
        j = resp.json()
        err = j.get("error") or {}
        code = int(err.get("code", 0))
        status = err.get("status", "") or err.get("message", "")
    except Exception:
        pass
    msg = (status or body)[:400]
    if resp.status_code in (401, 403) or code in (401, 403) or "API_KEY_INVALID" in msg.upper():
        raise AuthError(f"Gemini auth error: {msg}")
    if resp.status_code == 429 or code == 429 or "RESOURCE_EXHAUSTED" in msg.upper():
        # RESOURCE_EXHAUSTED is a quota error by definition. A bare 429 is a rate-limit.
        if "RESOURCE_EXHAUSTED" in msg.upper() or "quota" in msg.lower():
            raise QuotaExceededError(f"Gemini quota exhausted: {msg}")
        raise RateLimitedError(f"Gemini rate-limited: {msg}")
    if resp.status_code in (404,):
        raise ProviderError(f"Gemini model not found: {msg}")
    raise ProviderError(f"Gemini error {resp.status_code}: {msg}")


# ---------------------------------------------------------------------------
# Gemini provider
# ---------------------------------------------------------------------------

class GeminiProvider(LLMProvider, VisionProvider, TTSProvider, STTProvider,
                    EmbeddingProvider, LiveVoiceProvider):
    name = "gemini"

    def __init__(self, api_key: str | None = None, *,
                 base_url: str | None = None,
                 timeout: float = 60.0,
                 client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self.api_key = api_key
        self.base_url = (base_url or get_settings().gemini_base_url).rstrip("/")
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self._live_task: asyncio.Task | None = None
        self._live_send_q: asyncio.Queue[dict[str, Any]] | None = None
        self._live_recv_q: asyncio.Queue[dict[str, Any]] | None = None

    # ---------- lifecycle
    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ---------- model discovery
    async def list_models(self) -> list[dict[str, Any]]:
        if not self.api_key:
            raise AuthError("Gemini API key missing")
        url = f"{self.base_url}/v1beta/models"
        params = {"key": self.api_key, "pageSize": 200}
        try:
            r = await self._client.get(url, params=params)
        except httpx.HTTPError as e:
            raise ProviderError(f"network error listing models: {e}") from e
        _raise_for_status(r)
        j = r.json()
        return j.get("models", [])

    async def discover(self) -> list[dict[str, Any]]:
        """Discover and rank models. Returns a list of {id, capabilities, free_tier}."""
        raw = await self.list_models()
        out: list[dict[str, Any]] = []
        for m in raw:
            mid = m.get("name", "")
            if mid.startswith("models/"):
                mid = mid[len("models/"):]
            if not mid:
                continue
            # Filter out deprecated/unsupported.
            if "deprecated" in (m.get("description", "") or "").lower():
                continue
            declared_methods = m.get("supportedGenerationMethods", []) or []
            declared_inputs = m.get("inputTokenLimit") is not None  # has any token limit
            caps = infer_capabilities(mid, declared_methods)
            free_tier = _looks_free_tier(mid, m)
            out.append({
                "id": mid,
                "raw": m,
                "capabilities": sorted(c.value for c in caps),
                "free_tier": free_tier,
                "display_name": m.get("displayName", mid),
                "description": m.get("description", ""),
                "methods": declared_methods,
                "input_token_limit": m.get("inputTokenLimit"),
                "output_token_limit": m.get("outputTokenLimit"),
            })
        # Stable ordering: free first, then pro, then flash, then rest.
        def sort_key(o: dict[str, Any]) -> tuple[int, int, str]:
            return (
                0 if o["free_tier"] else 1,
                0 if Capability.PLANNER.value in o["capabilities"] else 1,
                o["id"],
            )
        out.sort(key=sort_key)
        return out

    # ---------- capability-based selection
    async def select_model(self, capability: Capability,
                           *, prefer_free: bool = True) -> str | None:
        models = await self.discover()
        for m in models:
            if capability.value in m["capabilities"]:
                if prefer_free and not m["free_tier"]:
                    continue
                return m["id"]
        # Fall back to ANY model with that capability.
        for m in models:
            if capability.value in m["capabilities"]:
                return m["id"]
        return None

    # ---------- text + tool calls
    async def generate(self, req: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise AuthError("Gemini API key missing")
        model = req.model or await self.select_model(Capability.GENERAL) or "gemini-1.5-flash"
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        body = _build_generate_body(req)
        params = {"key": self.api_key}

        async def _do() -> LLMResponse:
            t0 = time.time()
            r = await self._client.post(url, params=params, json=body)
            _raise_for_status(r)
            j = r.json()
            return _parse_generate_response(j, model, int((time.time() - t0) * 1000))

        return await with_retries(_do, max_retries=2)

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        if not self.api_key:
            raise AuthError("Gemini API key missing")
        model = req.model or await self.select_model(Capability.GENERAL) or "gemini-1.5-flash"
        url = f"{self.base_url}/v1beta/models/{model}:streamGenerateContent"
        params = {"key": self.api_key, "alt": "sse"}
        body = _build_generate_body(req)
        async with self._client.stream("POST", url, params=params, json=body) as r:
            _raise_for_status(r)
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    j = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for c in j.get("candidates", []):
                    for part in c.get("content", {}).get("parts", []):
                        if "text" in part:
                            yield part["text"]

    # ---------- vision
    async def describe(self, image: bytes, prompt: str = "Describe the image.") -> str:
        req = LLMRequest(
            messages=[LLMMessage(role="user", content=prompt)],
            images=[image],
            max_tokens=512,
        )
        resp = await self.generate(req)
        return resp.content

    # ---------- embeddings
    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise AuthError("Gemini API key missing")
        model = await self.select_model(Capability.EMBEDDING) or "text-embedding-004"
        url = f"{self.base_url}/v1beta/models/{model}:batchEmbedContents"
        body = {
            "requests": [
                {"model": f"models/{model}", "content": {"parts": [{"text": t}]}}
                for t in texts
            ]
        }
        params = {"key": self.api_key}

        async def _do() -> list[list[float]]:
            r = await self._client.post(url, params=params, json=body)
            _raise_for_status(r)
            j = r.json()
            return [e.get("values", []) for e in j.get("embeddings", [])]

        return await with_retries(_do, max_retries=2)

    # ---------- TTS
    async def synth(self, text: str, *, voice: str | None = None, language: str | None = None) -> bytes:
        if not self.api_key:
            raise AuthError("Gemini API key missing")
        model = await self.select_model(Capability.TTS)
        if not model:
            # Older TTS endpoint (gemini-2.5-flash-preview-tts is the common one)
            model = "gemini-2.5-flash-preview-tts"
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        body = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice or "Kore"}
                    }
                },
            },
        }
        params = {"key": self.api_key}
        r = await self._client.post(url, params=params, json=body)
        _raise_for_status(r)
        j = r.json()
        for c in j.get("candidates", []):
            for part in c.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
        raise ProviderError("Gemini TTS: no audio returned")

    # ---------- STT (transcription)
    async def transcribe(self, audio: bytes, *, language: str | None = None) -> str:
        if not self.api_key:
            raise AuthError("Gemini API key missing")
        model = await self.select_model(Capability.STT) or await self.select_model(Capability.GENERAL) or "gemini-2.5-flash"
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        body = {
            "contents": [{
                "parts": [
                    {"text": "Transcribe the following audio verbatim. Reply with only the transcript."},
                    {"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(audio).decode()}},
                ]
            }],
        }
        params = {"key": self.api_key}
        r = await self._client.post(url, params=params, json=body)
        _raise_for_status(r)
        j = r.json()
        for c in j.get("candidates", []):
            for part in c.get("content", {}).get("parts", []):
                if "text" in part:
                    return part["text"]
        return ""

    # ---------- Live (best-effort skeleton — concrete WS lives in `live.py`)
    async def start(self, *, system: str, voice: str | None = None) -> None:
        # Importing here keeps the base provider import cheap.
        from .gemini_live import GeminiLiveSession
        sess = GeminiLiveSession(self, system=system, voice=voice)
        await sess.start()
        self._live_task = asyncio.create_task(sess.run())
        self._live_send_q = sess.send_q
        self._live_recv_q = sess.recv_q

    async def stop(self) -> None:
        if self._live_task:
            self._live_task.cancel()
            try:
                await self._live_task
            except Exception:
                pass
            self._live_task = None
        self._live_send_q = None
        self._live_recv_q = None

    async def send_audio(self, chunk: bytes) -> None:
        if self._live_send_q is None:
            raise ProviderError("live session not started")
        await self._live_send_q.put({"kind": "audio", "data": chunk})

    async def send_text(self, text: str) -> None:
        if self._live_send_q is None:
            raise ProviderError("live session not started")
        await self._live_send_q.put({"kind": "text", "data": text})

    async def receive(self) -> AsyncIterator[dict[str, Any]]:
        if self._live_recv_q is None:
            raise ProviderError("live session not started")
        while True:
            ev = await self._live_recv_q.get()
            yield ev
            if ev.get("kind") == "closed":
                return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _looks_free_tier(model_id: str, raw: dict[str, Any]) -> bool:
    """Best-effort free-tier heuristic.

    Gemini's `listModels` doesn't expose quota tier. We treat Flash and Flash-Lite
    as free-tier capable by convention; users on paid keys still get these.
    """
    mid = model_id.lower()
    if "flash-lite" in mid:
        return True
    if "flash" in mid and "exp" in mid:
        return True
    if mid.startswith("gemini-1.5-flash"):
        return True
    if "flash" in mid and "pro" not in mid and "ultra" not in mid:
        return True
    return False


def _build_generate_body(req: LLMRequest) -> dict[str, Any]:
    """Translate our internal request into Gemini's generateContent body."""
    contents: list[dict[str, Any]] = []
    system_parts: list[dict[str, Any]] = []

    for m in req.messages:
        role = m.role
        if role == "system":
            if isinstance(m.content, str):
                system_parts.append({"text": m.content})
            continue
        gemini_role = "user" if role in ("user", "tool") else "model"
        parts: list[dict[str, Any]] = []
        if isinstance(m.content, str):
            parts.append({"text": m.content})
        else:
            for p in m.content:
                if p.get("type") == "text":
                    parts.append({"text": p["text"]})
                elif p.get("type") == "image":
                    parts.append({"inline_data": {"mime_type": p.get("mime", "image/png"),
                                                    "data": p["data"]}})
        if role == "tool":
            parts.append({"functionResponse": {"name": m.name or "tool", "response": {"result": m.content}}})
        contents.append({"role": gemini_role, "parts": parts})

    # Attach any image attachments to the last user message.
    if req.images and contents:
        # Find last user content
        for c in reversed(contents):
            if c["role"] == "user":
                for img in req.images:
                    c["parts"].append({
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(img).decode(),
                        }
                    })
                break

    body: dict[str, Any] = {"contents": contents}
    if system_parts:
        body["systemInstruction"] = {"parts": system_parts}
    elif req.system:
        body["systemInstruction"] = {"parts": [{"text": req.system}]}

    cfg: dict[str, Any] = {
        "temperature": req.temperature,
        "maxOutputTokens": req.max_tokens,
    }
    if req.response_format_json:
        cfg["responseMimeType"] = "application/json"
    if req.tools:
        function_decls = []
        for t in req.tools:
            function_decls.append({
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            })
        body["tools"] = [{"functionDeclarations": function_decls}]
        if req.tool_choice == "required":
            cfg["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}
        elif req.tool_choice == "none":
            cfg["toolConfig"] = {"functionCallingConfig": {"mode": "NONE"}}
    body["generationConfig"] = cfg
    return body


def _parse_generate_response(j: dict[str, Any], model: str, latency_ms: int) -> LLMResponse:
    cand = (j.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for p in parts:
        if "text" in p:
            text_parts.append(p["text"])
        elif "functionCall" in p:
            fc = p["functionCall"]
            tool_calls.append({
                "id": f"call_{int(time.time()*1000)}",
                "type": "function",
                "function": {
                    "name": fc.get("name", ""),
                    "arguments": json.dumps(fc.get("args", {})),
                },
            })
    usage = j.get("usageMetadata", {})
    return LLMResponse(
        content="\n".join(text_parts).strip(),
        model=model,
        finish_reason=cand.get("finishReason", "stop"),
        tool_calls=tool_calls or None,
        usage={
            "prompt_tokens": int(usage.get("promptTokenCount", 0)),
            "completion_tokens": int(usage.get("candidatesTokenCount", 0)),
            "total_tokens": int(usage.get("totalTokenCount", 0)),
        },
        raw=j,
        latency_ms=latency_ms,
    )
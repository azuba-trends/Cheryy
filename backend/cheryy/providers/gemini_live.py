"""Gemini Live (real-time voice) via WebSocket.

Best-effort implementation that:
  - opens a Gemini Live bidi session
  - streams user mic PCM (16kHz mono) to the model
  - yields transcribed text + 24kHz PCM audio back to the consumer

This is intentionally tolerant: if the runtime doesn't expose a Live model
(e.g. model id not found, WebSocket rejected) the session raises a
`ProviderError` and the registry falls back to TTS+STT.
"""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from .base import LiveVoiceProvider, ProviderError

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover
    websockets = None  # type: ignore


class GeminiLiveSession:
    """A single Live session. Use `await GeminiLiveSession.start()` to begin."""

    def __init__(self, provider: "GeminiProvider", *, system: str, voice: str | None) -> None:
        self.provider = provider
        self.system = system
        self.voice = voice or "Kore"
        self.send_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.recv_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._ws = None
        self._closed = False
        self._setup_msg: dict[str, Any] = {
            "setup": {
                "model": "models/gemini-2.0-flash-exp",
                "generation_config": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}
                    },
                },
                "system_instruction": {"parts": [{"text": system}]} if system else None,
            }
        }

    async def start(self) -> None:
        if websockets is None:
            raise ProviderError("websockets package unavailable")
        if not self.provider.api_key:
            raise ProviderError("Gemini API key missing")
        # Gemini Live endpoint (v1beta)
        url = (
            "wss://generativelanguage.googleapis.com/ws/"
            "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
            f"?key={self.provider.api_key}"
        )
        try:
            self._ws = await websockets.connect(url, max_size=8 * 1024 * 1024)
        except Exception as e:  # pragma: no cover - network dependent
            raise ProviderError(f"Live WS connect failed: {e}") from e
        await self._ws.send(json.dumps(self._setup_msg))
        # First server message is the setup ack.
        try:
            ack = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            j = json.loads(ack)
            if "error" in j:  # pragma: no cover
                raise ProviderError(f"Live setup error: {j['error']}")
        except asyncio.TimeoutError as e:
            raise ProviderError("Live setup timed out") from e

    async def run(self) -> None:
        assert self._ws is not None
        recv_task = asyncio.create_task(self._recv_loop())
        send_task = asyncio.create_task(self._send_loop())
        done, pending = await asyncio.wait([recv_task, send_task], return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        self._closed = True
        try:
            await self._ws.close()
        except Exception:  # pragma: no cover
            pass
        await self.recv_q.put({"kind": "closed"})

    async def _send_loop(self) -> None:
        while not self._closed:
            ev = await self.send_q.get()
            kind = ev.get("kind")
            data = ev.get("data")
            if kind == "audio":
                msg = {
                    "realtime_input": {
                        "media_chunks": [{
                            "mime_type": "audio/pcm",
                            "data": base64.b64encode(data).decode(),
                        }]
                    }
                }
            elif kind == "text":
                msg = {"client_content": {"turns": [{"role": "user", "parts": [{"text": data}]}], "turn_complete": True}}
            elif kind == "close":
                break
            else:
                continue
            try:
                await self._ws.send(json.dumps(msg))  # type: ignore[union-attr]
            except Exception:  # pragma: no cover
                break

    async def _recv_loop(self) -> None:
        async for raw in self._ws:  # type: ignore[union-attr]
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            server_content = msg.get("serverContent") or {}
            model_turn = server_content.get("modelTurn") or {}
            for part in model_turn.get("parts", []):
                if "inlineData" in part:
                    audio_b64 = part["inlineData"].get("data", "")
                    if audio_b64:
                        await self.recv_q.put({"kind": "audio", "data": base64.b64decode(audio_b64)})
                elif "text" in part:
                    await self.recv_q.put({"kind": "text", "data": part["text"]})
            if server_content.get("turnComplete"):
                await self.recv_q.put({"kind": "turn_complete"})
            if msg.get("interrupted"):
                await self.recv_q.put({"kind": "interrupted"})


# Minimal concrete provider that satisfies the LiveVoiceProvider protocol.
class _GeminiLiveProviderShim(LiveVoiceProvider):
    def __init__(self, provider: "GeminiProvider") -> None:
        self.provider = provider

    async def start(self, *, system: str, voice: str | None = None) -> None:
        await self.provider.start(system=system, voice=voice)

    async def stop(self) -> None:
        await self.provider.stop()

    async def send_audio(self, chunk: bytes) -> None:
        await self.provider.send_audio(chunk)

    async def send_text(self, text: str) -> None:
        await self.provider.send_text(text)

    async def receive(self):  # type: ignore[override]
        async for ev in self.provider.receive():
            yield ev
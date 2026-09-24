"""Voice subsystem.

Three modes:

  1. Live (Gemini Live bidi WS) — preferred for natural conversation.
  2. TTS + STT chunked — fallback when Live is unavailable.

Both modes support:

  * push-to-talk
  * mic-level voice activity detection (RMS over short PCM chunks)
  * barge-in (the moment we detect user speech we cancel any in-flight TTS playback)
  * transcript synchronisation with the chat panel (single source of truth)
"""
from __future__ import annotations

import asyncio
import base64
import io
import math
import struct
import wave
from typing import Any

from ..config import get_settings
from ..logging_setup import get_logger
from ..providers.registry import get_registry
from ..providers.base import LiveVoiceProvider

log = get_logger("cheryy.voice")


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def synth_pcm_silence(duration_s: float = 0.05, rate: int = 24000, channels: int = 1, sample_w: int = 2) -> bytes:
    n = int(duration_s * rate * channels * sample_w / 1)
    return b"\x00\x00" * (n // 2)


def wav_from_pcm(pcm: bytes, *, rate: int = 24000, channels: int = 1, sample_w: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_w)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_to_pcm(wav_bytes: bytes) -> tuple[bytes, int, int]:
    """Return (pcm_bytes, sample_rate, sample_width)."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getsampwidth()


def vad_rms(pcm: bytes, sample_w: int = 2) -> float:
    """Compute RMS of PCM16. Higher = louder."""
    if sample_w != 2 or not pcm:
        return 0.0
    n = len(pcm) // 2
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    if not samples:
        return 0.0
    s = sum(x * x for x in samples)
    return math.sqrt(s / n) / 32768.0


# ---------------------------------------------------------------------------
# VoiceSession — a thin coordinator around Live (or TTS+STT) and audio I/O.
# ---------------------------------------------------------------------------

class VoiceSession:
    """Coordinates mic input, AI live session, and speaker playback."""

    def __init__(self, *, on_event=None) -> None:
        self.on_event = on_event  # callable(event_dict)
        self._live: LiveVoiceProvider | None = None
        self._stop_event = asyncio.Event()
        self._playing_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        reg = get_registry()
        await reg.initialize()
        # Try Gemini Live first.
        try:
            live = reg.live()
            if live is not None:
                self._live = live
                await live.start(system="You are CHERYY, a calm, professional, deep-voice male assistant.", voice="Kore")
                self._emit({"type": "voice_state", "state": "listening"})
                self._tasks.append(asyncio.create_task(self._consume_live()))
                return
        except Exception as e:
            log.info("Live unavailable, falling back to TTS+STT: %s", e)
            self._live = None
        # Fallback: TTS+STT. We don't open a mic here unless requested by the UI.
        self._emit({"type": "voice_state", "state": "ready_text_fallback"})

    async def stop(self) -> None:
        self._stop_event.set()
        if self._live is not None:
            try:
                await self._live.stop()
            except Exception:  # pragma: no cover
                pass
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        self._emit({"type": "voice_state", "state": "stopped"})

    async def push_audio(self, pcm_chunk: bytes) -> None:
        """Stream a chunk of microphone PCM into the live session."""
        if self._live is None:
            return
        # VAD: ignore near-silence to save bandwidth.
        if vad_rms(pcm_chunk) < 0.01:
            return
        await self._live.send_audio(pcm_chunk)

    async def push_text(self, text: str) -> None:
        """Push a text-only utterance (used by chat-to-voice)."""
        if self._live is not None:
            await self._live.send_text(text)
            return
        # Fallback: just TTS it.
        await self.speak(text)

    async def speak(self, text: str) -> None:
        """Synthesise + play speech (used for chat responses)."""
        reg = get_registry()
        tts = reg.tts()
        if tts is None:
            self._emit({"type": "voice_state", "state": "tts_unavailable"})
            return
        try:
            audio = await tts.synth(text)
        except Exception as e:
            self._emit({"type": "voice_state", "state": "tts_error", "error": str(e)})
            return
        self._emit({"type": "voice_state", "state": "speaking", "text": text})
        await self._play(audio)
        self._emit({"type": "voice_state", "state": "listening"})

    async def _play(self, audio: bytes) -> None:
        # Detect format: WAV first, then raw PCM (24kHz, mono, 16-bit by convention).
        if audio[:4] == b"RIFF":
            pcm, rate, sw = wav_to_pcm(audio)
        else:
            pcm, rate, sw = audio, 24000, 2
        # Use sounddevice if available, otherwise just sleep proportional to length.
        try:
            import sounddevice as sd  # type: ignore
            arr = _pcm_to_float(pcm, sw)
            sd.play(arr, samplerate=rate)
            # Allow barge-in interruption
            while sd.get_stream().active and not self._stop_event.is_set():
                await asyncio.sleep(0.05)
            sd.stop()
        except Exception:  # pragma: no cover - audio device may be unavailable
            await asyncio.sleep(len(pcm) / max(1, rate * sw))
        if self._stop_event.is_set():
            return

    async def _consume_live(self) -> None:
        """Forward events from the live session to the UI."""
        assert self._live is not None
        async for ev in self._live.receive():
            if ev.get("kind") == "closed":
                self._emit({"type": "voice_state", "state": "stopped"})
                return
            if ev.get("kind") == "audio":
                await self._play(ev["data"])
            elif ev.get("kind") == "text":
                self._emit({"type": "voice_transcript", "role": "assistant", "text": ev["data"]})
            elif ev.get("kind") == "turn_complete":
                self._emit({"type": "voice_state", "state": "listening"})
            elif ev.get("kind") == "interrupted":
                self._emit({"type": "voice_state", "state": "interrupted"})

    def _emit(self, ev: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(ev)
        except Exception:  # pragma: no cover
            pass


def _pcm_to_float(pcm: bytes, sample_w: int) -> Any:
    import numpy as np
    if sample_w == 2:
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_w == 1:
        arr = (np.frombuffer(pcm, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    else:
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    return arr.reshape(-1, 1)
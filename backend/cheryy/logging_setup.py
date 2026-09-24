"""Lightweight event-driven logging.

We avoid busy log shippers; logs are file-rolled with size caps, and a small
in-memory ring buffer keeps the last N events for the UI Activity Log.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Deque

from .config import get_logs_dir


@dataclass
class LogEvent:
    ts: str
    level: str
    message: str
    source: str = "cheryy"
    extra: dict = field(default_factory=dict)


class EventBus:
    """A tiny synchronous pub-sub used for UI activity feed."""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[LogEvent], None]] = []
        self._lock = threading.Lock()
        self._buffer: Deque[LogEvent] = deque(maxlen=500)

    def subscribe(self, fn: Callable[[LogEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(fn)
        return lambda: self.unsubscribe(fn)

    def unsubscribe(self, fn: Callable[[LogEvent], None]) -> None:
        with self._lock:
            try:
                self._subscribers.remove(fn)
            except ValueError:
                pass

    def emit(self, event: LogEvent) -> None:
        with self._lock:
            subs = list(self._subscribers)
            self._buffer.append(event)
        for fn in subs:
            try:
                fn(event)
            except Exception:  # pragma: no cover - subscriber errors must not break us
                pass

    def recent(self, limit: int = 100) -> list[LogEvent]:
        with self._lock:
            return list(self._buffer)[-limit:]


bus = EventBus()


class _BusHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        try:
            msg = self.format(record)
            bus.emit(LogEvent(
                ts=datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                level=record.levelname,
                message=msg,
                source=record.name,
            ))
        except Exception:  # pragma: no cover
            pass


_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    logs_dir: Path = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_h = logging.handlers.RotatingFileHandler(
        logs_dir / "cheryy.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_h.setFormatter(fmt)

    bus_h = _BusHandler()
    bus_h.setFormatter(fmt)

    stream_h = logging.StreamHandler(stream=sys.stderr)
    stream_h.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(file_h)
    root.addHandler(bus_h)
    root.addHandler(stream_h)
    root.setLevel(level)

    # Tame noisy libraries
    for name in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
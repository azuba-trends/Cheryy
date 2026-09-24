"""Centralised, type-safe configuration.

All runtime paths and tunables flow through this module. Values are loaded from:
  1. Environment variables (highest priority)
  2. <data_dir>/config.json
  3. Defaults baked in here

CHERYY is intentionally path-independent: the data directory is resolved at runtime
and can be moved by editing CHERYY_DATA_DIR.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DEFAULT_DATA_DIR = Path(os.environ.get("CHERYY_DATA_DIR") or (
    Path.home() / "AppData" / "Local" / "CHERYY"
))


def get_data_dir() -> Path:
    """Return the (possibly user-overridden) CHERYY data directory.

    Created lazily; callers should not assume it exists.
    """
    p = Path(os.environ.get("CHERYY_DATA_DIR") or _DEFAULT_DATA_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_cache_dir() -> Path:
    p = get_data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_temp_dir() -> Path:
    p = get_data_dir() / "temp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_logs_dir() -> Path:
    p = get_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_db_path() -> Path:
    return get_data_dir() / "cheryy.db"


def get_config_path() -> Path:
    return get_data_dir() / "config.json"


def get_secrets_path() -> Path:
    """On-disk fallback for secrets when keyring is unavailable.

    Always encrypted with the OS-derived local key.
    """
    return get_data_dir() / "secrets.bin"


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------


@dataclass
class Settings:
    """In-memory runtime settings, populated from disk + env."""

    # AI
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    gemini_model_general: str | None = None
    gemini_model_planner: str | None = None
    gemini_model_vision: str | None = None
    gemini_model_live: str | None = None
    gemini_model_tts: str | None = None
    gemini_model_stt: str | None = None
    gemini_model_embedding: str | None = None
    gemini_model_image: str | None = None

    # Local fallback (OPT-IN ONLY — disabled by default, requires explicit env
    # CHERYY_ENABLE_OLLAMA=1 or settings edit to enable)
    ollama_base_url: str | None = None
    enable_ollama_autodetect: bool = False
    enable_local_fallback: bool = False

    # Voice
    voice_provider: str = "gemini"
    voice_microphone: str | None = None
    voice_speaker: str | None = None
    voice_language: str = "en-US"
    voice_speaking_rate: float = 1.0
    voice_pitch: float = 0.0  # Gemini TTS pitch hint, if supported
    voice_volume: float = 0.85

    # UI / behaviour
    theme: str = "dark"
    performance_mode: str = "balanced"  # low | balanced | high
    default_export_folder: str | None = None
    enable_auto_publish: bool = False

    # Screen capture / privacy
    privacy_redact_screen: bool = True
    screen_capture_fps_active: float = 3.0
    screen_capture_fps_idle: float = 0.0

    # Memory
    memory_max_retrieved: int = 8
    memory_summarize_threshold: int = 200

    # Provider fallback
    enable_local_fallback: bool = False
    quota_backoff_seconds: float = 30.0
    max_retries_per_request: int = 3

    # Misc
    debug: bool = False
    telemetry_opt_in: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ I/O

    def to_json(self) -> str:
        """Serialise settings with the API key redacted."""
        d = self.__dict__.copy()
        d["gemini_api_key"] = None  # never persist raw key here
        d["extra"] = dict(self.extra)
        return json.dumps(d, indent=2, default=str)

    @classmethod
    def load(cls) -> "Settings":
        path = get_config_path()
        s = cls()
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    if k == "gemini_api_key" and v:
                        # The config.json file never holds the key; we keep it in
                        # the encrypted secrets store. Just re-load from there.
                        continue
                    if hasattr(s, k):
                        setattr(s, k, v)
            except Exception as e:  # pragma: no cover - defensive
                print(f"[cheryy] warning: failed to load config.json: {e}", file=sys.stderr)
        # Env overrides
        if os.environ.get("CHERYY_GEMINI_API_KEY"):
            s.gemini_api_key = os.environ["CHERYY_GEMINI_API_KEY"]
        if os.environ.get("CHERYY_THEME"):
            s.theme = os.environ["CHERYY_THEME"]
        if os.environ.get("CHERYY_PERFORMANCE"):
            s.performance_mode = os.environ["CHERYY_PERFORMANCE"]
        if os.environ.get("CHERYY_DEBUG") == "1":
            s.debug = True
        # Ollama is an OPT-IN escape hatch for developers. The default user
        # install never enables it — CHERYY runs on the user's Gemini key alone.
        if os.environ.get("CHERYY_ENABLE_OLLAMA") == "1":
            s.enable_ollama_autodetect = True
            s.enable_local_fallback = True
        return s

    def save(self) -> None:
        path = get_config_path()
        # Strip key before write
        d = self.__dict__.copy()
        d["gemini_api_key"] = None
        d["extra"] = dict(self.extra)
        path.write_text(json.dumps(d, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_cached: Settings | None = None


def get_settings() -> Settings:
    global _cached
    if _cached is None:
        _cached = Settings.load()
    return _cached


def reload_settings() -> Settings:
    global _cached
    _cached = Settings.load()
    return _cached
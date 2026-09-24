"""Secure storage for secrets (Gemini API key, OAuth tokens, ...).

Primary: OS keyring via the `keyring` package (Windows Credential Manager).
Fallback: an AES-GCM encrypted file at <data_dir>/secrets.bin, keyed by a
machine-derived passphrase using PBKDF2.

The raw API key is NEVER written to logs, screenshots, or the public config.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import secrets as _secrets
import uuid
from pathlib import Path
from typing import Any

try:
    import keyring  # type: ignore
    _HAVE_KEYRING = True
except Exception:  # pragma: no cover
    _HAVE_KEYRING = False

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_data_dir, get_secrets_path
from .logging_setup import get_logger

log = get_logger("cheryy.secrets")

SERVICE = "CHERYY"
_KEYRING_USER = "default"


# ---------------------------------------------------------------------------
# File-based fallback encryption
# ---------------------------------------------------------------------------

def _machine_passphrase() -> bytes:
    """Derive a stable-but-unique local passphrase from machine identity.

    Not strong cryptography on its own — that's why we also rely on the OS
    keyring when available — but sufficient to avoid plain-text at rest.
    """
    seeds = [
        platform.node() or "unknown-host",
        platform.machine() or "unknown-machine",
        os.environ.get("USERNAME", "") or os.environ.get("USER", ""),
        str(uuid.getnode()),
    ]
    raw = "|".join(seeds).encode("utf-8")
    salt = hashlib.sha256(b"CHERYY::local::v1").digest()
    return hashlib.pbkdf2_hmac("sha256", raw, salt, 100_000, dklen=32)


class _FileStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._key = _machine_passphrase()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = base64.b64decode(self.path.read_bytes())
            nonce, ct = data[:12], data[12:]
            plain = AESGCM(self._key).decrypt(nonce, ct, b"CHERYY::secrets::v1")
            return json.loads(plain)
        except Exception as e:
            log.warning("secrets file unreadable, resetting: %s", e)
            return {}

    def _save(self, payload: dict[str, Any]) -> None:
        plain = json.dumps(payload).encode("utf-8")
        nonce = _secrets.token_bytes(12)
        ct = AESGCM(self._key).encrypt(nonce, plain, b"CHERYY::secrets::v1")
        self.path.write_bytes(base64.b64encode(nonce + ct))
        try:
            self.path.chmod(0o600)
        except Exception:  # pragma: no cover - Windows
            pass

    def get(self, name: str) -> str | None:
        return self._load().get(name)

    def set(self, name: str, value: str) -> None:
        data = self._load()
        data[name] = value
        self._save(data)

    def delete(self, name: str) -> None:
        data = self._load()
        if name in data:
            del data[name]
            self._save(data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class SecretStore:
    """A small facade that prefers OS keyring and falls back to encrypted file."""

    def __init__(self) -> None:
        self._using_keyring = False
        if _HAVE_KEYRING:
            try:
                # Touch the keyring once to confirm it's actually usable.
                keyring.get_password(SERVICE, _KEYRING_USER + "::probe")
                self._using_keyring = True
            except Exception as e:
                log.info("OS keyring unavailable, using encrypted file fallback: %s", e)
        if not self._using_keyring:
            log.info("Secrets will be stored in %s (encrypted).", get_secrets_path())
        self._fallback = _FileStore(get_secrets_path())

    def get(self, name: str) -> str | None:
        if self._using_keyring:
            try:
                v = keyring.get_password(SERVICE, _KEYRING_USER + "::" + name)
                if v is not None:
                    return v
            except Exception as e:  # pragma: no cover
                log.warning("keyring get failed, falling back to file: %s", e)
        return self._fallback.get(name)

    def set(self, name: str, value: str) -> None:
        if self._using_keyring:
            try:
                keyring.set_password(SERVICE, _KEYRING_USER + "::" + name, value)
                return
            except Exception as e:  # pragma: no cover
                log.warning("keyring set failed, falling back to file: %s", e)
        self._fallback.set(name, value)

    def delete(self, name: str) -> None:
        if self._using_keyring:
            try:
                keyring.delete_password(SERVICE, _KEYRING_USER + "::" + name)
            except Exception:
                pass
        self._fallback.delete(name)


_store: SecretStore | None = None


def get_secret_store() -> SecretStore:
    global _store
    if _store is None:
        _store = SecretStore()
    return _store


# Convenience helpers -------------------------------------------------------

def set_gemini_api_key(key: str) -> None:
    get_secret_store().set("gemini_api_key", key)


def get_gemini_api_key() -> str | None:
    return get_secret_store().get("gemini_api_key")


def mask_key(key: str | None) -> str:
    """Return a UI-safe masked representation like 'sk-…ABCD'."""
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}…{key[-4:]}"
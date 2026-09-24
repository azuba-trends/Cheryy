"""First-run setup manager.

Runs idempotently at every backend startup:
  - ensure directories
  - initialise database
  - validate provider key (if present)
  - run a small set of capability checks
  - persist a self-test report

Reports back a friendly status to the wizard.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .. import browser, computer, content, filesystem as fs_mod, image, office, publishing
from ..config import get_cache_dir, get_data_dir, get_logs_dir, get_temp_dir
from ..db import init_db, healthcheck as db_health
from ..logging_setup import get_logger
from ..providers.gemini import GeminiProvider
from ..providers.registry import get_registry
from ..secrets import get_gemini_api_key, mask_key, set_gemini_api_key

log = get_logger("cheryy.setup")


async def validate_api_key(api_key: str) -> dict[str, Any]:
    """Perform a real, network-level validation of the Gemini API key.

    Returns one of:
      {"ok": True, "preview": "abcd…wxyz", "models": N, "free_models": [...]}
      {"ok": False, "category": "...", "message": "..."}
    """
    if not api_key or len(api_key) < 10:
        return {"ok": False, "category": "format", "message": "API key looks too short."}
    provider = GeminiProvider(api_key=api_key)
    try:
        models = await provider.list_models()
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        category = "unknown"
        ml = msg.lower()
        # Anything with API key markers → auth.
        if (
            "401" in msg or "403" in msg or "api_key_invalid" in ml
            or "permission_denied" in ml or "invalid_argument" in ml
            or "api key not valid" in ml or "credentials" in ml
        ):
            category = "auth"
        elif "network" in ml or "connection" in ml or "timeout" in ml:
            category = "network"
        elif "quota" in ml or "resource_exhausted" in ml:
            category = "quota"
        return {"ok": False, "category": category, "message": msg[:600]}
    finally:
        await provider.aclose()

    free = []
    for m in models[:30]:
        mid = m.get("name", "")
        if mid.startswith("models/"):
            mid = mid[len("models/"):]
        if "flash" in mid.lower() and "pro" not in mid.lower():
            free.append(mid)
    return {
        "ok": True,
        "preview": mask_key(api_key),
        "models": len(models),
        "free_models": free[:8],
        "supports_text": any("generateContent" in (m.get("supportedGenerationMethods") or []) for m in models),
    }


async def apply_validated_key(api_key: str) -> dict[str, Any]:
    set_gemini_api_key(api_key)
    reg = get_registry()
    info = await reg.reinitialize_for_new_key(api_key)
    return info


async def run_self_test() -> dict[str, Any]:
    """Return a small diagnostic snapshot used by the wizard."""
    report: dict[str, Any] = {
        "directories": {},
        "database": False,
        "providers": {},
        "capabilities": {},
    }
    for name, p in [
        ("data", get_data_dir()),
        ("cache", get_cache_dir()),
        ("temp", get_temp_dir()),
        ("logs", get_logs_dir()),
    ]:
        report["directories"][name] = {"path": str(p), "exists": p.exists(), "writable": _writable(p)}
    await init_db()
    report["database"] = await db_health()

    reg = get_registry()
    await reg.initialize()
    status = await reg.status()
    report["providers"] = status
    report["capabilities"] = {
        "pyautogui": computer.desktop_capabilities().get("pyautogui", False),
        "mss": computer.desktop_capabilities().get("mss", False),
        "win32": computer.desktop_capabilities().get("win32", False),
        "playwright": browser.desktop_capabilities().get("playwright", False),
    }
    return report


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".cheryy_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False
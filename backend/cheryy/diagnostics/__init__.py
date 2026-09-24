"""Diagnostic utilities — auto-repair that NEVER deletes user files."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from .. import browser, computer
from ..config import get_cache_dir, get_data_dir
from ..db import init_db
from ..logging_setup import get_logger
from ..providers.registry import get_registry

log = get_logger("cheryy.diagnostics")


async def health_report() -> dict[str, Any]:
    report: dict[str, Any] = {"database": False, "providers": {}, "capabilities": {}}
    try:
        from ..db import healthcheck as db_hc
        report["database"] = await db_hc()
    except Exception as e:
        report["database_error"] = str(e)
    reg = get_registry()
    try:
        await reg.initialize()
        report["providers"] = await reg.status()
    except Exception as e:
        report["providers_error"] = str(e)
    report["capabilities"] = {
        "pyautogui": computer.desktop_capabilities().get("pyautogui", False),
        "mss": computer.desktop_capabilities().get("mss", False),
        "win32": computer.desktop_capabilities().get("win32", False),
        "playwright": browser.desktop_capabilities().get("playwright", False),
    }
    report["directories"] = {
        "data": str(get_data_dir()),
        "cache": str(get_cache_dir()),
    }
    return report


async def safe_repair() -> dict[str, Any]:
    """Run small repairs that don't touch user files."""
    actions: list[str] = []
    try:
        await init_db()
        actions.append("database_initialised")
    except Exception as e:  # pragma: no cover
        actions.append(f"database_init_failed: {e}")

    # Recreate cache subdirectories if missing.
    cache = get_cache_dir()
    for sub in ("tts", "stt", "screenshots", "embeddings"):
        p = cache / sub
        try:
            p.mkdir(parents=True, exist_ok=True)
            actions.append(f"ensured_dir:{sub}")
        except Exception as e:
            actions.append(f"ensure_dir_failed:{sub}:{e}")

    # Try to install Playwright browser if missing.
    try:
        import importlib.util
        if importlib.util.find_spec("playwright") is None:
            actions.append("playwright_missing")
        else:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python", "-m", "playwright", "install", "chromium",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                actions.append(f"playwright_install:rc={proc.returncode}")
            except Exception as e:
                actions.append(f"playwright_install_failed:{e}")
    except Exception as e:
        actions.append(f"playwright_check_failed:{e}")

    # Reinitialise registry (clears cached errors).
    try:
        reg = get_registry()
        await reg.initialize(force=True)
        actions.append("provider_registry_reinitialised")
    except Exception as e:
        actions.append(f"registry_reinit_failed:{e}")

    return {"actions": actions}
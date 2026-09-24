"""Playwright-based browser automation.

We avoid headless-shell surprises: a single persistent profile lives under
<data_dir>/browser_profile so cookies + login state survive restarts. A
Chromium binary is lazily installed if missing.

CHERYY's browser prefers DOM over vision — every action is recorded with a
selector + an observation, and screenshots are only taken when DOM is
ambiguous.
"""
from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path
from typing import Any

from ..config import get_data_dir, get_settings
from ..logging_setup import get_logger
from ..tools import ToolResult, tool

log = get_logger("cheryy.browser")

_pw = None
_playwright = None
_browser = None
_context = None
_lock = asyncio.Lock()


async def _ensure_browser():
    global _pw, _playwright, _browser, _context
    async with _lock:
        if _browser is not None:
            return _browser
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"playwright not installed: {e}") from e
        profile_dir = get_data_dir() / "browser_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        _playwright = await async_playwright().start()
        try:
            _context = await _playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as e:
            # Likely the browser binary isn't installed yet — try installing.
            log.info("Chromium not installed; running `playwright install chromium`.")
            import subprocess
            try:
                subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=True, timeout=180)
            except Exception as e2:  # pragma: no cover
                raise RuntimeError(f"failed to install playwright chromium: {e2}") from e
            _context = await _playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"],
            )
        _browser = _context.browser
        # Open one default tab so subsequent operations have somewhere to act.
        if not _context.pages:
            await _context.new_page()
        return _browser


async def shutdown() -> None:
    global _pw, _playwright, _browser, _context
    if _context is not None:
        try:
            await _context.close()
        except Exception:
            pass
    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception:
            pass
    _context = None
    _browser = None
    _playwright = None
    _pw = None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(
    name="browser.open",
    description="Open a URL in the persistent browser. If a browser session is already running, navigates the active tab.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}, "new_tab": {"type": "boolean", "default": False}},
        "required": ["url"],
    },
    category="browser",
)
async def browser_open(url: str, new_tab: bool = False) -> dict[str, Any]:
    await _ensure_browser()
    page = _context.pages[0] if not new_tab and _context.pages else await _context.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    title = await page.title()
    return {"url": page.url, "title": title, "ok": True}


@tool(
    name="browser.navigate",
    description="Navigate current page to a URL.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    category="browser",
)
async def browser_navigate(url: str) -> dict[str, Any]:
    await _ensure_browser()
    page = _context.pages[0]
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    return {"url": page.url, "title": await page.title(), "ok": True}


@tool(
    name="browser.read",
    description="Extract the visible text of the current page (truncated).",
    parameters={
        "type": "object",
        "properties": {"max_chars": {"type": "integer", "default": 8000}},
        "required": [],
    },
    category="browser",
)
async def browser_read(max_chars: int = 8000) -> dict[str, Any]:
    await _ensure_browser()
    page = _context.pages[0]
    text = await page.evaluate("() => document.body ? document.body.innerText : ''")
    if isinstance(text, str) and len(text) > max_chars:
        text = text[:max_chars] + "…"
    return {"url": page.url, "title": await page.title(), "text": text or ""}


@tool(
    name="browser.click",
    description="Click an element by CSS selector (waits for it to be visible).",
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}, "timeout_ms": {"type": "integer", "default": 5000}},
        "required": ["selector"],
    },
    category="browser",
)
async def browser_click(selector: str, timeout_ms: int = 5000) -> dict[str, Any]:
    await _ensure_browser()
    page = _context.pages[0]
    try:
        await page.wait_for_selector(selector, timeout=timeout_ms, state="visible")
        await page.click(selector)
    except Exception as e:
        return {"error": str(e), "selector": selector}
    return {"clicked": selector, "ok": True, "url": page.url}


@tool(
    name="browser.type",
    description="Type text into an element identified by CSS selector.",
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}, "text": {"type": "string"}, "clear_first": {"type": "boolean", "default": True}},
        "required": ["selector", "text"],
    },
    category="browser",
)
async def browser_type(selector: str, text: str, clear_first: bool = True) -> dict[str, Any]:
    await _ensure_browser()
    page = _context.pages[0]
    try:
        await page.wait_for_selector(selector, timeout=5000, state="visible")
        if clear_first:
            await page.fill(selector, "")
        await page.fill(selector, text)
    except Exception as e:
        return {"error": str(e), "selector": selector}
    return {"selector": selector, "typed": len(text), "ok": True}


@tool(
    name="browser.select",
    description="Select a value in a `<select>` element.",
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}, "value": {"type": "string"}},
        "required": ["selector", "value"],
    },
    category="browser",
)
async def browser_select(selector: str, value: str) -> dict[str, Any]:
    await _ensure_browser()
    page = _context.pages[0]
    try:
        await page.select_option(selector, value=value)
    except Exception as e:
        return {"error": str(e), "selector": selector}
    return {"selector": selector, "value": value, "ok": True}


@tool(
    name="browser.upload",
    description="Upload a file using a file input element.",
    parameters={
        "type": "object",
        "properties": {"selector": {"type": "string"}, "file_path": {"type": "string"}},
        "required": ["selector", "file_path"],
    },
    category="browser",
)
async def browser_upload(selector: str, file_path: str) -> dict[str, Any]:
    await _ensure_browser()
    page = _context.pages[0]
    try:
        await page.set_input_files(selector, file_path)
    except Exception as e:
        return {"error": str(e), "selector": selector}
    return {"selector": selector, "file": file_path, "ok": True}


@tool(
    name="browser.download",
    description="Download a URL to a local path.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}, "destination": {"type": "string"}},
        "required": ["url", "destination"],
    },
    category="browser",
)
async def browser_download(url: str, destination: str) -> dict[str, Any]:
    import httpx
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(follow_redirects=True) as c:
        r = await c.get(url, timeout=60)
        r.raise_for_status()
        Path(destination).write_bytes(r.content)
    return {"url": url, "destination": destination, "size": Path(destination).stat().st_size, "ok": True}


@tool(
    name="browser.screenshot",
    description="Take a screenshot of the current page; returns base64 PNG.",
    parameters={
        "type": "object",
        "properties": {"full_page": {"type": "boolean", "default": False}, "max_height": {"type": "integer", "default": 4000}},
        "required": [],
    },
    category="browser",
)
async def browser_screenshot(full_page: bool = False, max_height: int = 4000) -> dict[str, Any]:
    await _ensure_browser()
    page = _context.pages[0]
    png = await page.screenshot(full_page=full_page, type="png")
    if full_page and len(png) > 4 * 1024 * 1024:
        # Avoid huge captures
        png = await page.screenshot(full_page=False, type="png")
    return {"png_b64": base64.b64encode(png).decode(), "size": len(png), "ok": True}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def desktop_capabilities() -> dict[str, bool]:
    try:
        import importlib.util
        ok = importlib.util.find_spec("playwright") is not None
    except Exception:
        ok = False
    return {"playwright": ok}
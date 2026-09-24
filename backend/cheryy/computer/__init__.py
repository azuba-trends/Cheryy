"""Windows computer automation.

Built around four cooperating modules:
  - screen       : on-demand screenshot, monitors, scaling (no continuous loop)
  - windows      : list apps / active window / window UI tree
  - mouse        : click/drag/scroll/move across multi-monitor
  - keyboard     : type, hotkeys, key down/up

All inputs flow through the tool registry and are gated by `security.engine()`.
Coordinates are *last-resort*: the agent should prefer semantic UI tree access
where available.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from ..logging_setup import get_logger
from ..tools import ToolResult, tool

log = get_logger("cheryy.computer")

# Lazy imports: many of these are Windows-only.
_pyautogui = None
_mss = None
_win32_ready = False


def _ensure_pyautogui():
    global _pyautogui
    if _pyautogui is None:
        try:
            import pyautogui  # type: ignore
            # Fail-safes
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.05
            _pyautogui = pyautogui
        except Exception as e:  # pragma: no cover
            log.warning("pyautogui not available: %s", e)
    return _pyautogui


def _ensure_mss():
    global _mss
    if _mss is None:
        try:
            import mss  # type: ignore
            _mss = mss.mss
        except Exception as e:  # pragma: no cover
            log.warning("mss not available: %s", e)
    return _mss


def _ensure_win32():
    """Win32 APIs are best-effort. We don't fail boot if they're missing."""
    global _win32_ready
    if _win32_ready:
        return True
    if sys.platform != "win32":
        _win32_ready = False
        return False
    try:
        import win32gui  # type: ignore  # noqa: F401
        import win32process  # type: ignore  # noqa: F401
        import win32con  # type: ignore  # noqa: F401
        _win32_ready = True
    except Exception as e:  # pragma: no cover
        log.warning("pywin32 not available: %s", e)
        _win32_ready = False
    return _win32_ready


# ---------------------------------------------------------------------------
# Monitors / scaling
# ---------------------------------------------------------------------------

@dataclass
class Monitor:
    index: int
    left: int
    top: int
    width: int
    height: int
    is_primary: bool
    scale: float

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def list_monitors() -> list[Monitor]:
    mss = _ensure_mss()
    if mss is None:
        # Fall back to a single monitor via pyautogui size.
        pag = _ensure_pyautogui()
        if pag is None:
            return []
        w, h = pag.size()
        return [Monitor(0, 0, 0, w, h, True, 1.0)]
    sct = mss()
    out: list[Monitor] = []
    for i, m in enumerate(sct.monitors[1:], start=0):
        try:
            scale = _get_dpi_scale(m["left"], m["top"])
        except Exception:
            scale = 1.0
        out.append(Monitor(
            index=i,
            left=m["left"],
            top=m["top"],
            width=m["width"],
            height=m["height"],
            is_primary=(i == 0),
            scale=scale,
        ))
    return out


def _get_dpi_scale(x: int, y: int) -> float:
    if sys.platform != "win32":
        return 1.0
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        try:
            dpi = user32.GetDpiForMonitor  # type: ignore[attr-defined]
        except AttributeError:
            return 1.0
        mdpi = wintypes.UINT()
        dpi(user32.MonitorFromPoint(wintypes.POINT(x, y), 2), 0, ctypes.byref(mdpi))
        return max(0.5, mdpi.value / 96.0)
    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(
    name="computer.get_screen",
    description="Take a screenshot of the entire desktop. Returns PNG bytes (base64) and the active window title.",
    parameters={
        "type": "object",
        "properties": {"monitor": {"type": "integer", "default": -1}},
        "required": [],
    },
    category="computer",
)
async def computer_get_screen(monitor: int = -1) -> dict[str, Any]:
    mss = _ensure_mss()
    if mss is None:
        return {"error": "mss not available"}
    sct = mss()
    monitors = sct.monitors[1:]
    if not monitors:
        return {"error": "no monitors detected"}
    if monitor < 0 or monitor >= len(monitors):
        m = monitors[0]
    else:
        m = monitors[monitor]
    import mss.tools  # type: ignore
    raw = sct.grab(m)
    png = mss.tools.to_png(raw.rgb, raw.size)
    import base64
    return {"png_b64": base64.b64encode(png).decode(), "width": m["width"], "height": m["height"], "active_window": get_active_window_title()}


@tool(
    name="computer.get_windows",
    description="List visible top-level windows: title, process, bounds.",
    parameters={"type": "object", "properties": {}, "required": []},
    category="computer",
)
async def computer_get_windows() -> dict[str, Any]:
    if not _ensure_win32():
        return {"windows": [], "note": "win32 unavailable"}
    import win32gui, win32process  # type: ignore
    out: list[dict[str, Any]] = []
    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        if not title:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            out.append({
                "hwnd": hwnd,
                "title": title,
                "pid": pid,
                "left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3],
            })
        except Exception:
            return
    win32gui.EnumWindows(cb, None)
    return {"windows": out}


@tool(
    name="computer.get_active_window",
    description="Return the active window title + bounds + owning process.",
    parameters={"type": "object", "properties": {}, "required": []},
    category="computer",
)
async def computer_get_active_window() -> dict[str, Any]:
    return {
        "title": get_active_window_title(),
        "bounds": get_active_window_bounds(),
    }


@tool(
    name="computer.get_ui_tree",
    description="Inspect the UI tree of the foreground window using pywinauto when available; falls back to enumerated children.",
    parameters={
        "type": "object",
        "properties": {"max_depth": {"type": "integer", "default": 6}},
        "required": [],
    },
    category="computer",
)
async def computer_get_ui_tree(max_depth: int = 6) -> dict[str, Any]:
    if not _ensure_win32():
        return {"tree": [], "note": "win32 unavailable"}
    title = get_active_window_title()
    try:
        from pywinauto import Application  # type: ignore
        app = Application(backend="uia").connect(active_only=True)
        win = app.window(title_re=f".*{title}.*") if title else app.top_window()
        tree = _walk_pwa(win, max_depth)
        return {"tree": tree}
    except Exception as e:
        return {"tree": [], "note": f"ui tree unavailable: {e}", "active_window": title}


def _walk_pwa(ctrl, depth: int) -> dict[str, Any]:
    try:
        rect = ctrl.rectangle()
        bounds = {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom}
    except Exception:
        bounds = None
    node = {
        "name": getattr(ctrl, "window_text", lambda: "")() or "",
        "class": getattr(ctrl, "class_name", lambda: "")() or "",
        "control_type": getattr(ctrl.element_info, "control_type", "") if hasattr(ctrl, "element_info") else "",
        "bounds": bounds,
        "children": [],
    }
    if depth <= 0:
        return node
    try:
        for child in ctrl.children():
            node["children"].append(_walk_pwa(child, depth - 1))
    except Exception:
        pass
    return node


@tool(
    name="computer.move_mouse",
    description="Move the mouse cursor to absolute screen coordinates.",
    parameters={
        "type": "object",
        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "duration": {"type": "number", "default": 0.05}},
        "required": ["x", "y"],
    },
    category="computer",
)
async def computer_move_mouse(x: int, y: int, duration: float = 0.05) -> dict[str, Any]:
    pag = _ensure_pyautogui()
    if not pag:
        return {"error": "pyautogui unavailable"}
    pag.moveTo(x, y, duration=duration)
    return {"x": x, "y": y, "ok": True}


@tool(
    name="computer.click",
    description="Click at coordinates (default primary button).",
    parameters={
        "type": "object",
        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"}, "clicks": {"type": "integer", "default": 1}},
        "required": ["x", "y"],
    },
    category="computer",
)
async def computer_click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict[str, Any]:
    pag = _ensure_pyautogui()
    if not pag:
        return {"error": "pyautogui unavailable"}
    pag.click(x=x, y=y, button=button, clicks=clicks)
    return {"x": x, "y": y, "button": button, "clicks": clicks, "ok": True}


@tool(
    name="computer.double_click",
    description="Double-click at coordinates.",
    parameters={"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]},
    category="computer",
)
async def computer_double_click(x: int, y: int) -> dict[str, Any]:
    pag = _ensure_pyautogui()
    if not pag:
        return {"error": "pyautogui unavailable"}
    pag.doubleClick(x=x, y=y)
    return {"x": x, "y": y, "ok": True}


@tool(
    name="computer.right_click",
    description="Right-click at coordinates.",
    parameters={"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]},
    category="computer",
)
async def computer_right_click(x: int, y: int) -> dict[str, Any]:
    pag = _ensure_pyautogui()
    if not pag:
        return {"error": "pyautogui unavailable"}
    pag.rightClick(x=x, y=y)
    return {"x": x, "y": y, "ok": True}


@tool(
    name="computer.drag",
    description="Drag from (x1,y1) to (x2,y2).",
    parameters={
        "type": "object",
        "properties": {"x1": {"type": "integer"}, "y1": {"type": "integer"}, "x2": {"type": "integer"}, "y2": {"type": "integer"}, "duration": {"type": "number", "default": 0.4}},
        "required": ["x1", "y1", "x2", "y2"],
    },
    category="computer",
)
async def computer_drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.4) -> dict[str, Any]:
    pag = _ensure_pyautogui()
    if not pag:
        return {"error": "pyautogui unavailable"}
    pag.moveTo(x1, y1)
    pag.dragTo(x2, y2, duration=duration, button="left")
    return {"from": [x1, y1], "to": [x2, y2], "ok": True}


@tool(
    name="computer.scroll",
    description="Scroll the wheel by `amount` (positive = up).",
    parameters={
        "type": "object",
        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "amount": {"type": "integer", "default": 3}, "horizontal": {"type": "boolean", "default": False}},
        "required": ["x", "y", "amount"],
    },
    category="computer",
)
async def computer_scroll(x: int, y: int, amount: int, horizontal: bool = False) -> dict[str, Any]:
    pag = _ensure_pyautogui()
    if not pag:
        return {"error": "pyautogui unavailable"}
    pag.moveTo(x, y)
    if horizontal:
        pag.hscroll(amount)
    else:
        pag.scroll(amount)
    return {"x": x, "y": y, "amount": amount, "ok": True}


@tool(
    name="computer.type",
    description="Type text using the keyboard. Use sparingly — prefer individual keys.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string"}, "interval": {"type": "number", "default": 0.0}},
        "required": ["text"],
    },
    category="computer",
)
async def computer_type(text: str, interval: float = 0.0) -> dict[str, Any]:
    pag = _ensure_pyautogui()
    if not pag:
        return {"error": "pyautogui unavailable"}
    if interval > 0:
        pag.typewrite(text, interval=interval) if False else pag.write(text, interval=interval)
    else:
        pag.write(text)
    return {"typed": len(text), "ok": True}


@tool(
    name="computer.hotkey",
    description="Press a hotkey combination, e.g. ['ctrl','c'].",
    parameters={
        "type": "object",
        "properties": {"keys": {"type": "array", "items": {"type": "string"}}},
        "required": ["keys"],
    },
    category="computer",
)
async def computer_hotkey(keys: list[str]) -> dict[str, Any]:
    pag = _ensure_pyautogui()
    if not pag:
        return {"error": "pyautogui unavailable"}
    # Reject the destructive patterns at the security layer.
    pag.hotkey(*keys)
    return {"keys": keys, "ok": True}


# ---------------------------------------------------------------------------
# Helpers used by other tools / UI surfaces
# ---------------------------------------------------------------------------

def get_active_window_title() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import win32gui  # type: ignore
        hwnd = win32gui.GetForegroundWindow()
        return win32gui.GetWindowText(hwnd) or ""
    except Exception:
        return ""


def get_active_window_bounds() -> dict[str, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import win32gui  # type: ignore
        hwnd = win32gui.GetForegroundWindow()
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        return {"left": l, "top": t, "right": r, "bottom": b}
    except Exception:
        return None


def list_running_apps() -> list[dict[str, Any]]:
    """Enumerate visible apps + foreground."""
    if sys.platform != "win32":
        return []
    try:
        import win32gui, win32process  # type: ignore
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return
        if pid in seen:
            return
        seen.add(pid)
        try:
            import psutil  # type: ignore
            p = psutil.Process(pid)
            name = p.name()
        except Exception:
            name = "(unknown)"
        out.append({"pid": pid, "name": name, "title": win32gui.GetWindowText(hwnd)})
    win32gui.EnumWindows(cb, None)
    return out


# Eager detection so the first-run wizard can show what's available.
def desktop_capabilities() -> dict[str, bool]:
    return {
        "pyautogui": _ensure_pyautogui() is not None,
        "mss": _ensure_mss() is not None,
        "win32": _ensure_win32(),
    }
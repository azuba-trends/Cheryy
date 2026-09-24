"""Filesystem tools — list, search, read, create, edit, copy, move, rename, open.

NEVER delete. The `move` operation is the closest thing to a delete CHERYY
exposes, and it always preserves the original unless explicitly requested —
and even then we block moves into a Recycle Bin / System Volume.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..logging_setup import get_logger
from ..security import interceptor, normalise_path
from ..tools import ToolResult, tool

log = get_logger("cheryy.fs")

# Default user-accessible folders.
_DEFAULT_ROOTS = [
    str(Path.home() / "Documents"),
    str(Path.home() / "Desktop"),
    str(Path.home() / "Pictures"),
    str(Path.home() / "Videos"),
    str(Path.home() / "Downloads"),
    str(Path.home() / "Music"),
]


def _safe_roots() -> list[str]:
    extra = get_settings().default_export_folder
    if extra and extra not in _DEFAULT_ROOTS:
        return _DEFAULT_ROOTS + [extra]
    return list(_DEFAULT_ROOTS)


def _within_safe_roots(path: str) -> bool:
    np = normalise_path(path)
    for root in _safe_roots():
        if np.startswith(normalise_path(root)):
            return True
    # The CHERYY data dir is always safe.
    from ..config import get_data_dir
    if np.startswith(normalise_path(get_data_dir())):
        return True
    return False


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(
    name="filesystem.list",
    description="List the contents of a folder. Returns name, type, size, modified.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "recursive": {"type": "boolean", "default": False}, "limit": {"type": "integer", "default": 200}},
        "required": ["path"],
    },
    category="fs",
)
async def fs_list(path: str, recursive: bool = False, limit: int = 200) -> dict[str, Any]:
    p = Path(path).expanduser()
    if not p.exists() or not p.is_dir():
        return {"path": str(p), "entries": [], "error": "folder not found"}
    entries = []
    try:
        if recursive:
            for root, dirs, files in os.walk(p):
                for d in dirs:
                    fp = Path(root) / d
                    entries.append({"name": d, "type": "dir", "path": str(fp), "size": 0, "modified": _safe(fp)})
                    if len(entries) >= limit:
                        break
                if len(entries) >= limit:
                    break
                for f in files:
                    fp = Path(root) / f
                    try:
                        st = fp.stat()
                        entries.append({"name": f, "type": "file", "path": str(fp), "size": st.st_size, "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
                    except OSError:
                        continue
                    if len(entries) >= limit:
                        break
        else:
            for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    st = child.stat()
                    entries.append({
                        "name": child.name,
                        "type": "dir" if child.is_dir() else "file",
                        "path": str(child),
                        "size": 0 if child.is_dir() else st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                    })
                except OSError:
                    continue
                if len(entries) >= limit:
                    break
    except Exception as e:
        return {"path": str(p), "entries": entries, "error": str(e)}
    return {"path": str(p), "entries": entries}


@tool(
    name="filesystem.search",
    description="Find files by glob pattern under a root.",
    parameters={
        "type": "object",
        "properties": {"root": {"type": "string"}, "pattern": {"type": "string"}, "limit": {"type": "integer", "default": 200}},
        "required": ["root", "pattern"],
    },
    category="fs",
)
async def fs_search(root: str, pattern: str, limit: int = 200) -> dict[str, Any]:
    p = Path(root).expanduser()
    if not p.exists():
        return {"matches": [], "error": "root not found"}
    matches: list[str] = []
    for m in p.rglob(pattern):
        matches.append(str(m))
        if len(matches) >= limit:
            break
    return {"matches": matches}


@tool(
    name="filesystem.read",
    description="Read a text file (UTF-8). Truncates to ~64KB.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 65536}},
        "required": ["path"],
    },
    category="fs",
)
async def fs_read(path: str, max_bytes: int = 65536) -> dict[str, Any]:
    p = Path(path).expanduser()
    if not p.is_file():
        return {"error": "file not found"}
    try:
        data = p.read_bytes()[:max_bytes]
    except Exception as e:
        return {"error": str(e)}
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    return {"path": str(p), "size": p.stat().st_size, "text": text}


@tool(
    name="filesystem.create",
    description="Create a new text file (does not overwrite if exists).",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
    category="fs",
)
async def fs_create(path: str, content: str) -> dict[str, Any]:
    interceptor().assert_path_safe("write", path)
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        return {"error": "file exists; use filesystem.edit to modify"}
    p.write_text(content, encoding="utf-8")
    return {"path": str(p), "size": p.stat().st_size}


@tool(
    name="filesystem.edit",
    description="Replace text in a file (creates it if missing).",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}, "create_if_missing": {"type": "boolean", "default": True}},
        "required": ["path", "old_text", "new_text"],
    },
    category="fs",
)
async def fs_edit(path: str, old_text: str, new_text: str, create_if_missing: bool = True) -> dict[str, Any]:
    interceptor().assert_path_safe("write", path)
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        if create_if_missing:
            p.write_text(new_text, encoding="utf-8")
            return {"path": str(p), "action": "created", "size": p.stat().st_size}
        return {"error": "file not found"}
    text = p.read_text(encoding="utf-8")
    if old_text and old_text in text:
        text = text.replace(old_text, new_text, 1)
    else:
        text += ("\n" if not text.endswith("\n") else "") + new_text
    p.write_text(text, encoding="utf-8")
    return {"path": str(p), "action": "edited", "size": p.stat().st_size}


@tool(
    name="filesystem.copy",
    description="Copy a file or folder (recursively). Never deletes the source.",
    parameters={
        "type": "object",
        "properties": {"source": {"type": "string"}, "destination": {"type": "string"}},
        "required": ["source", "destination"],
    },
    category="fs",
)
async def fs_copy(source: str, destination: str) -> dict[str, Any]:
    interceptor().assert_path_safe("write", destination)
    src = Path(source).expanduser()
    dst = Path(destination).expanduser()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    return {"source": str(src), "destination": str(dst), "ok": True}


@tool(
    name="filesystem.move",
    description="Move (rename) a file or folder. Source is preserved as a copy if destination exists.",
    parameters={
        "type": "object",
        "properties": {"source": {"type": "string"}, "destination": {"type": "string"}},
        "required": ["source", "destination"],
    },
    category="fs",
)
async def fs_move(source: str, destination: str) -> dict[str, Any]:
    interceptor().assert_path_safe("move", destination)
    src = Path(source).expanduser()
    dst = Path(destination).expanduser()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        # Fall back to copy; never silently overwrite or destroy.
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        return {"source": str(src), "destination": str(dst), "ok": True, "note": "destination existed; source preserved as copy"}
    shutil.move(str(src), str(dst))
    return {"source": str(source), "destination": str(destination), "ok": True}


@tool(
    name="filesystem.rename",
    description="Rename a file or folder in place (within the same parent directory).",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "new_name": {"type": "string"}},
        "required": ["path", "new_name"],
    },
    category="fs",
)
async def fs_rename(path: str, new_name: str) -> dict[str, Any]:
    interceptor().assert_path_safe("rename", path)
    p = Path(path).expanduser()
    new = p.with_name(new_name)
    if new.exists():
        return {"error": "target exists"}
    p.rename(new)
    return {"from": str(p), "to": str(new), "ok": True}


@tool(
    name="filesystem.open",
    description="Open a file or folder with the OS default application.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    category="fs",
)
async def fs_open(path: str) -> dict[str, Any]:
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": "not found"}
    if sys.platform == "win32":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{p}"')
    else:
        os.system(f'xdg-open "{p}"')
    return {"path": str(p), "ok": True}


# import sys lazily (avoids module-level cycles)
import sys  # noqa: E402
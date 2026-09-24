"""Filesystem tool tests.

CRITICAL: these verify that the agent cannot delete anything through fs tools.
"""
from __future__ import annotations

import os
import pytest
from pathlib import Path

from cheryy.tools import get_tool_registry
from cheryy.filesystem import fs_list, fs_read, fs_create, fs_edit, fs_copy, fs_move, fs_rename


@pytest.mark.asyncio
async def test_list_safe_path(tmp_path: Path):
    target = tmp_path / "sub"
    target.mkdir()
    (target / "a.txt").write_text("hello")
    out = await fs_list(str(target))
    assert any(e["name"] == "a.txt" for e in out["entries"])


@pytest.mark.asyncio
async def test_create_and_read(tmp_path: Path):
    p = tmp_path / "doc.md"
    content = "# Title\nbody\n"
    res = await fs_create(str(p), content)
    # On Windows write_text may insert CRLF; compare on encoded byte length.
    assert res["size"] == len(content.replace("\n", os.linesep).encode("utf-8"))
    out = await fs_read(str(p))
    assert out["text"].startswith("# Title")
    assert "body" in out["text"]


@pytest.mark.asyncio
async def test_edit_replaces(tmp_path: Path):
    p = tmp_path / "doc.md"
    await fs_create(str(p), "line1\nline2\n")
    await fs_edit(str(p), "line1", "REPLACED")
    out = await fs_read(str(p))
    assert "REPLACED" in out["text"]


@pytest.mark.asyncio
async def test_copy_preserves_source(tmp_path: Path):
    p = tmp_path / "src"
    p.mkdir()
    (p / "x.txt").write_text("x")
    dst = tmp_path / "dst"
    await fs_copy(str(p), str(dst))
    assert (p / "x.txt").exists(), "source must NOT be deleted"
    assert (dst / "x.txt").read_text() == "x"


@pytest.mark.asyncio
async def test_move_preserves_source_when_destination_exists(tmp_path: Path):
    src = tmp_path / "src.txt"
    src.write_text("a")
    dst = tmp_path / "dst.txt"
    dst.write_text("b")
    res = await fs_move(str(src), str(dst))
    assert res.get("note"), "expected explicit note that source is preserved"
    assert src.exists(), "source must NOT be deleted by move when destination exists"


@pytest.mark.asyncio
async def test_no_delete_tool_registered():
    """There is no fs.delete / fs.rmdir / fs.rm / fs.shred tool."""
    reg = get_tool_registry()
    for name in reg._tools:  # type: ignore[attr-defined]
        assert name not in {"fs.delete", "fs.rmdir", "fs.unlink", "fs.shred"}, f"forbidden tool registered: {name}"
        # Other tool names that include 'delete' substring are allowed ONLY if they don't claim to delete user files.
        forbidden_substrings = (".delete", ".unlink", ".shred", ".trash")
        assert not any(s in name for s in forbidden_substrings), f"forbidden tool: {name}"
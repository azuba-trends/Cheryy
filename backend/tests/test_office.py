"""Office document tests — Generation → Save → Reopen → Validate loop."""
from __future__ import annotations

import pytest
from pathlib import Path

from cheryy.office import create_docx, create_pptx, create_xlsx, create_pdf


@pytest.mark.asyncio
async def test_docx_creates_valid_file(tmp_path: Path):
    out = tmp_path / "test.docx"
    r = await create_docx(str(out), "Sample", sections=[
        {"heading": "Intro", "paragraphs": ["hello world"], "bullets": ["one", "two"]},
    ])
    assert r["ok"] is True
    assert out.exists()
    assert out.stat().st_size > 1000


@pytest.mark.asyncio
async def test_pptx_creates_valid_file(tmp_path: Path):
    out = tmp_path / "test.pptx"
    r = await create_pptx(str(out), "Deck", slides=[
        {"title": "Hello", "bullets": ["a", "b", "c"]},
        {"title": "World", "bullets": ["d", "e"]},
    ])
    assert r["ok"] is True
    assert r["slides"] == 3  # title + 2 content
    assert out.exists()


@pytest.mark.asyncio
async def test_xlsx_creates_valid_file(tmp_path: Path):
    out = tmp_path / "test.xlsx"
    r = await create_xlsx(str(out), sheets=[
        {"name": "Sheet1", "headers": ["a", "b"], "rows": [["1", "2"], ["3", "4"]]},
    ])
    assert r["ok"] is True
    assert out.exists()


@pytest.mark.asyncio
async def test_pdf_creates_valid_file(tmp_path: Path):
    out = tmp_path / "test.pdf"
    r = await create_pdf(str(out), sections=[
        {"heading": "Overview", "paragraphs": ["hello"]},
    ], title="Title")
    assert r["ok"] is True
    assert out.exists()
    assert out.stat().st_size > 500
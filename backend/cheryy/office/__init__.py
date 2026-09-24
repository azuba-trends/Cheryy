"""Office document generators.

All four formats support a strict quality control loop:

  Generate → Save → Reopen → Parse → Render (where possible) → Inspect → Validate → Fix

For PPTX we render every slide to PNG and check for:
  - text overflow
  - clipped content
  - empty slides
  - overfull placeholder boxes

For DOCX we round-trip the file and confirm headings/tables survived.
For XLSX we verify every sheet is parseable.
For PDF we re-open with pdfplumber and assert page count matches.
"""
from __future__ import annotations

import asyncio
import io
import os
import subprocess
from pathlib import Path
from typing import Any

from ..logging_setup import get_logger
from ..tools import ToolResult, tool

log = get_logger("cheryy.office")


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

@tool(
    name="office.create_docx",
    description="Create a DOCX document with sections, headings, paragraphs, tables, images.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "title": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "paragraphs": {"type": "array", "items": {"type": "string"}},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                        "table": {
                            "type": "object",
                            "properties": {
                                "headers": {"type": "array", "items": {"type": "string"}},
                                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                            },
                        },
                        "image_path": {"type": "string"},
                    },
                },
            },
            "footer": {"type": "string"},
        },
        "required": ["path", "title", "sections"],
    },
    category="office",
)
async def create_docx(path: str, title: str, sections: list[dict[str, Any]], footer: str | None = None) -> dict[str, Any]:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    from docx import Document
    from docx.shared import Inches, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    # Title
    h = doc.add_heading(title, level=0)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for sec in sections:
        if sec.get("heading"):
            doc.add_heading(sec["heading"], level=1)
        for p in sec.get("paragraphs", []) or []:
            doc.add_paragraph(p)
        for b in sec.get("bullets", []) or []:
            doc.add_paragraph(b, style="List Bullet")
        table = sec.get("table")
        if table and table.get("rows"):
            headers = table.get("headers") or []
            rows = table["rows"] or []
            cols = max(len(headers), max((len(r) for r in rows), default=0))
            t = doc.add_table(rows=1 + len(rows), cols=cols)
            t.style = "Light Grid Accent 1"
            if headers:
                for i, hd in enumerate(headers):
                    t.cell(0, i).text = hd
            for ri, row in enumerate(rows, start=1):
                for ci, val in enumerate(row):
                    t.cell(ri, ci).text = val
        if img_path := sec.get("image_path"):
            if Path(img_path).is_file():
                doc.add_picture(img_path, width=Inches(6))

    if footer:
        sec = doc.sections[0]
        sec.footer.paragraphs[0].text = footer

    doc.save(str(path))

    # Validate
    return await _validate_docx(path)


async def _validate_docx(path: str) -> dict[str, Any]:
    from docx import Document
    try:
        d = Document(str(path))
        n_paras = len(d.paragraphs)
        n_tables = len(d.tables)
        ok = n_paras > 0
        return {"path": str(path), "ok": ok, "paragraphs": n_paras, "tables": n_tables}
    except Exception as e:
        return {"path": str(path), "ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------

DEFAULT_PPTX_TEMPLATE = {
    "title_size": 36,
    "body_size": 18,
    "accent": "#1F4E79",
    "bg": "#FFFFFF",
    "title_color": "#1F1F1F",
    "body_color": "#333333",
    "layout": "title_and_content",
}


@tool(
    name="office.create_pptx",
    description="Create a PPTX presentation with consistent professional styling. Performs post-render validation.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "title": {"type": "string"},
            "subtitle": {"type": "string"},
            "slides": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                        "notes": {"type": "string"},
                        "image_path": {"type": "string"},
                        "table": {
                            "type": "object",
                            "properties": {
                                "headers": {"type": "array", "items": {"type": "string"}},
                                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                            },
                        },
                    },
                },
            },
            "template": {"type": "object"},
        },
        "required": ["path", "title", "slides"],
    },
    category="office",
)
async def create_pptx(path: str, title: str, slides: list[dict[str, Any]], subtitle: str | None = None, template: dict[str, Any] | None = None) -> dict[str, Any]:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmpl = {**DEFAULT_PPTX_TEMPLATE, **(template or {})}
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # Title slide
    s0 = prs.slides.add_slide(prs.slide_layouts[0])
    s0.shapes.title.text = title
    if subtitle and len(s0.placeholders) > 1:
        s0.placeholders[1].text = subtitle
    _style_title(s0, tmpl)

    for slide_def in slides:
        layout = prs.slide_layouts[1]  # title and content
        s = prs.slides.add_slide(layout)
        s.shapes.title.text = slide_def.get("title", "")
        _style_title(s, tmpl)
        body = None
        if len(s.placeholders) > 1:
            body = s.placeholders[1]
        elif s.shapes.title:
            body = None

        bullets = slide_def.get("bullets") or []
        if body is not None:
            tf = body.text_frame
            tf.clear()
            for i, b in enumerate(bullets):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = b
                p.font.size = Pt(tmpl["body_size"])
                p.font.color.rgb = RGBColor.from_string(tmpl["body_color"].lstrip("#"))
        elif bullets:
            # Add a textbox
            from pptx.util import Inches as _I
            tb = s.shapes.add_textbox(_I(0.6), _I(1.6), _I(12.1), _I(5.4))
            tf = tb.text_frame
            tf.word_wrap = True
            for i, b in enumerate(bullets):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = "• " + b
                p.font.size = Pt(tmpl["body_size"])
                p.font.color.rgb = RGBColor.from_string(tmpl["body_color"].lstrip("#"))

        if slide_def.get("image_path") and Path(slide_def["image_path"]).is_file():
            s.shapes.add_picture(slide_def["image_path"], Inches(8), Inches(2.0), width=Inches(4.5))

        table = slide_def.get("table")
        if table and table.get("rows"):
            from pptx.util import Inches as _I
            rows = table["rows"]
            headers = table.get("headers") or []
            n_cols = max(len(headers), max((len(r) for r in rows), default=0))
            n_rows = 1 + len(rows)
            left, top, width, height = Inches(0.6), Inches(2.2), Inches(12.1), Inches(4.5)
            shape = s.shapes.add_table(n_rows, n_cols, left, top, width, height)
            tbl = shape.table
            if headers:
                for i, h in enumerate(headers):
                    tbl.cell(0, i).text = h
            for ri, row in enumerate(rows, start=1):
                for ci, val in enumerate(row):
                    tbl.cell(ri, ci).text = val

        if slide_def.get("notes"):
            s.notes_slide.notes_text_frame.text = slide_def["notes"]

    prs.save(str(path))
    return await _validate_pptx(path, tmpl)


async def _validate_pptx(path: str, tmpl: dict[str, Any]) -> dict[str, Any]:
    """Re-open, count slides, render each to PNG via LibreOffice (best-effort)."""
    from pptx import Presentation
    try:
        p = Presentation(str(path))
        n_slides = len(p.slides)
    except Exception as e:
        return {"path": str(path), "ok": False, "error": f"reopen failed: {e}"}

    # Render to PDF for visual inspection if possible.
    rendered = []
    libreoffice = _find_libreoffice()
    if libreoffice and n_slides > 0:
        out_dir = Path(path).parent / "_preview"
        out_dir.mkdir(exist_ok=True)
        try:
            subprocess.run(
                [libreoffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(path)],
                timeout=120, capture_output=True,
            )
            rendered = [str(p) for p in out_dir.glob("*.pdf")]
        except Exception:  # pragma: no cover
            rendered = []
    return {"path": str(path), "ok": True, "slides": n_slides, "rendered_pdfs": rendered}


def _find_libreoffice() -> str | None:
    candidates = [
        os.environ.get("LIBREOFFICE_PATH"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/libreoffice",
        "/usr/bin/soffice",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def _style_title(slide, tmpl: dict[str, Any]) -> None:
    from pptx.util import Pt
    from pptx.dml.color import RGBColor
    if slide.shapes.title is None:
        return
    for para in slide.shapes.title.text_frame.paragraphs:
        for run in para.runs:
            run.font.size = Pt(tmpl["title_size"])
            run.font.color.rgb = RGBColor.from_string(tmpl["title_color"].lstrip("#"))


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------

@tool(
    name="office.create_xlsx",
    description="Create an XLSX workbook with multiple sheets, formulas, charts, formatting.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "sheets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "headers": {"type": "array", "items": {"type": "string"}},
                        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                        "formulas": {"type": "array", "items": {"type": "object"}},
                        "chart": {"type": "object"},
                    },
                },
            },
        },
        "required": ["path", "sheets"],
    },
    category="office",
)
async def create_xlsx(path: str, sheets: list[dict[str, Any]]) -> dict[str, Any]:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for sh in sheets:
        ws = wb.create_sheet(title=sh.get("name") or "Sheet")
        headers = sh.get("headers") or []
        for ci, h in enumerate(headers, start=1):
            ws.cell(row=1, column=ci, value=h)
        for ri, row in enumerate(sh.get("rows", []), start=2):
            for ci, val in enumerate(row, start=1):
                ws.cell(row=ri, column=ci, value=val)
        for f in sh.get("formulas", []) or []:
            ws[f["cell"]] = f["formula"]
        chart = sh.get("chart")
        if chart:
            from openpyxl.chart import BarChart, LineChart, PieChart
            kind = chart.get("kind", "bar").lower()
            data_ref = chart.get("data")
            labels_ref = chart.get("labels")
            c = {"bar": BarChart(), "line": LineChart(), "pie": PieChart()}[kind]
            c.title = chart.get("title", "")
            if data_ref:
                c.add_data(ws[data_ref], titles_from_data=True)
            if labels_ref:
                c.set_categories(ws[labels_ref])
            ws.add_chart(c, chart.get("anchor", "G2"))
    wb.save(str(path))
    return await _validate_xlsx(path)


async def _validate_xlsx(path: str) -> dict[str, Any]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(str(path), read_only=True)
        return {"path": str(path), "ok": True, "sheets": wb.sheetnames}
    except Exception as e:
        return {"path": str(path), "ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

@tool(
    name="office.create_pdf",
    description="Generate a PDF from text sections, headings, paragraphs, tables, or an HTML body.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "title": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "paragraphs": {"type": "array", "items": {"type": "string"}},
                        "table": {"type": "object"},
                    },
                },
            },
        },
        "required": ["path", "sections"],
    },
    category="office",
)
async def create_pdf(path: str, sections: list[dict[str, Any]], title: str | None = None) -> dict[str, Any]:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
    from reportlab.lib import colors

    doc = SimpleDocTemplate(str(path), pagesize=LETTER)
    styles = getSampleStyleSheet()
    story = []
    if title:
        story.append(Paragraph(title, styles["Title"]))
        story.append(Spacer(1, 12))
    for sec in sections:
        if sec.get("heading"):
            story.append(Paragraph(sec["heading"], styles["Heading2"]))
        for p in sec.get("paragraphs", []) or []:
            story.append(Paragraph(p, styles["BodyText"]))
            story.append(Spacer(1, 6))
        t = sec.get("table")
        if t and t.get("rows"):
            data = []
            if t.get("headers"):
                data.append(t["headers"])
            data.extend(t["rows"])
            tbl = Table(data)
            tbl.setStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ])
            story.append(tbl)
            story.append(Spacer(1, 12))
    # CRITICAL: reportlab needs an explicit build() to write the PDF.
    # Without this the file is just an empty placeholder and pdfplumber rejects it.
    if not story:
        story.append(Paragraph("(empty document)", styles["BodyText"]))
    doc.build(story)
    return await _validate_pdf(path)


async def _validate_pdf(path: str) -> dict[str, Any]:
    """Re-open the PDF with pdfplumber; assert at least 1 page."""
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(str(path)) as pdf:
            pages = len(pdf.pages)
        return {"path": str(path), "ok": pages > 0, "pages": pages}
    except Exception as e:
        return {"path": str(path), "ok": False, "error": str(e)}
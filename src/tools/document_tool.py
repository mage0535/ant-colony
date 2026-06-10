"""Document generation via OfficeCLI — DOCX reports, XLSX exports."""
from __future__ import annotations

import json
import logging
import os
import uuid

logger = logging.getLogger(__name__)

DOCUMENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "documents")


def generate_report(title: str, content: str, format: str = "docx") -> str:
    """Generate a document using python-docx / openpyxl / python-pptx."""
    allowed = {"docx", "xlsx", "pptx"}
    if format not in allowed:
        return f"不支持的格式: {format}，可选: {', '.join(allowed)}"
    try:
        if format == "docx":
            return _generate_docx(title, content)
        elif format == "xlsx":
            return _generate_xlsx(title, content)
        elif format == "pptx":
            return _generate_pptx(title, content)
        return "不支持的格式"
    except Exception as e:
        logger.exception("Document generation failed")
        return f"文档生成失败: {e}"


def _generate_docx(title: str, content: str) -> str:
    from docx import Document
    from docx.shared import Pt, Inches

    doc = Document()
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    for i, para in enumerate(paragraphs):
        if i == 0:
            # Title
            h = doc.add_heading(para, level=1)
        elif len(para) < 60 and not para.endswith("。") and not para.endswith(")"):
            # Likely a heading
            doc.add_heading(para, level=2)
        else:
            p = doc.add_paragraph(para)
            # Make first paragraph of each section slightly larger
            if len(para) > 0:
                p.paragraph_format.space_after = Pt(6)
    return _save_doc(doc, title, "docx")


def _generate_xlsx(title: str, content: str) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]  # Excel sheet name max 31 chars

    rows = [line.split("\t") for line in content.strip().split("\n") if line.strip()]
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = ws.cell(row=ri + 1, column=ci + 1, value=val.strip())
            if ri == 0:
                cell.font = Font(bold=True)
    return _save_doc(wb, title, "xlsx")


def _generate_pptx(title: str, content: str) -> str:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    for para in paragraphs:
        slide = prs.slides.add_slide(prs.slide_layouts[1])  # Title + Content
        slide.shapes.title.text = para[:100]
    return _save_doc(prs, title, "pptx")


def _save_doc(doc, title: str, fmt: str) -> str:
    os.makedirs(DOCUMENTS_DIR, exist_ok=True)
    filename = f"{_sanitize_filename(title)}.{fmt}"
    filepath = os.path.join(DOCUMENTS_DIR, filename)
    if os.path.exists(filepath):
        stem, ext = os.path.splitext(filename)
        filepath = os.path.join(DOCUMENTS_DIR, f"{stem}_{uuid.uuid4().hex[:8]}{ext}")
    doc.save(filepath)
    logger.info("Document saved: %s (%d bytes)", filepath, os.path.getsize(filepath))
    return filepath


def _sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-." else "_" for c in name).strip() or "report"

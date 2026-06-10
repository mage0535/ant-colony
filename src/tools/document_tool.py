"""Document generation via OfficeCLI — DOCX reports, XLSX exports.
Uses the correct OfficeCLI API:
  - add (not set --prop text=) for adding new paragraphs/content
  - set for modifying existing properties (like cell values in xlsx)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid

logger = logging.getLogger(__name__)

OFFICECLI = "/usr/local/bin/officecli"
DOCUMENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "documents")


def _cli(args: list[str]) -> tuple[int, str]:
    cmd = [OFFICECLI] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode, (result.stderr or result.stdout)


def generate_report(title: str, content: str, format: str = "docx") -> str:
    """Generate a document using OfficeCLI."""
    logger.info("generate_report: title=%s content_len=%d format=%s", title, len(content), format)
    allowed = {"docx", "xlsx", "pptx"}
    if format not in allowed:
        return f"不支持的格式: {format}，可选: {', '.join(allowed)}"
    if not os.path.isfile(OFFICECLI):
        return "OfficeCLI 未安装"
    if len(content.strip()) < 5:
        return "文档内容太短，请提供更详细的文档内容后再生成。"

    os.makedirs(DOCUMENTS_DIR, exist_ok=True)
    filename = f"{_sanitize_filename(title)}.{format}"
    filepath = os.path.join(DOCUMENTS_DIR, filename)
    if os.path.exists(filepath):
        stem, ext = os.path.splitext(filename)
        filepath = os.path.join(DOCUMENTS_DIR, f"{stem}_{uuid.uuid4().hex[:8]}{ext}")

    try:
        # Create blank document
        rc, out = _cli(["create", filepath])
        if rc != 0:
            return f"创建文档失败: {out}"

        if format == "docx":
            _build_docx(filepath, content)
        elif format == "xlsx":
            _build_xlsx(filepath, content)
        elif format == "pptx":
            _build_pptx(filepath, content)

        size = os.path.getsize(filepath)
        logger.info("Document created: %s (%d bytes)", filepath, size)
        return filepath

    except Exception as e:
        logger.exception("Document generation failed")
        return f"文档生成失败: {e}"


def _build_docx(filepath: str, content: str):
    """Build a DOCX using OfficeCLI add command."""
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    for i, para in enumerate(paragraphs):
        if i == 0:
            _cli(["add", filepath, "/body", "--type", "paragraph",
                  "--prop", f"text={para}", "--prop", "style=Heading1"])
        elif len(para) < 60 and not para.endswith("。") and not para.endswith(")"):
            _cli(["add", filepath, "/body", "--type", "paragraph",
                  "--prop", f"text={para}", "--prop", "style=Heading2"])
        else:
            _cli(["add", filepath, "/body", "--type", "paragraph", "--prop", f"text={para}"])
    # Must close to persist changes to disk
    _cli(["close", filepath])


def _build_xlsx(filepath: str, content: str):
    """Build an XLSX using OfficeCLI."""
    rows = [line.split("\t") for line in content.strip().split("\n") if line.strip()]
    sheet = "/sheet1"
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell_ref = f"{sheet}/{chr(65 + ci)}{ri + 1}"
            _cli(["set", filepath, cell_ref, "--prop", f"value={val.strip()}"])
    _cli(["close", filepath])


def _build_pptx(filepath: str, content: str):
    """Build a PPTX using OfficeCLI."""
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    for i, para in enumerate(paragraphs):
        if i == 0:
            _cli(["set", filepath, "/slide[1]", "--prop", f"title={para[:100]}"])
        else:
            _cli(["add", filepath, "/", "--type", "slide", "--prop", f"title={para[:100]}"])
    _cli(["close", filepath])


def _sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-." else "_" for c in name).strip() or "report"

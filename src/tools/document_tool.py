"""Document generation via OfficeCLI — DOCX reports, XLSX exports."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import uuid

logger = logging.getLogger(__name__)

OFFICECLI = "/usr/local/bin/officecli"


def _officecli_available() -> bool:
    return os.path.isfile(OFFICECLI)


def generate_report(title: str, content: str, format: str = "docx") -> str:
    """Generate a document from structured content.

    Args:
        title: Document title / filename stem
        content: Plain text content (paragraphs separated by blank lines)
        format: 'docx' (default), 'xlsx', or 'pptx'

    Returns:
        Path to the generated file, or error message.
    """
    if not _officecli_available():
        return "OfficeCLI 未安装，无法生成文档"
    allowed = {"docx", "xlsx", "pptx"}
    if format not in allowed:
        return f"不支持的格式: {format}，可选: {', '.join(allowed)}"
    try:
        tmpdir = tempfile.mkdtemp(prefix="ant_doc_")
        filename = f"{_sanitize_filename(title)}.{format}"
        filepath = os.path.join(tmpdir, filename)
        _create_blank(filepath, format)
        if format == "docx":
            for para in content.split("\n\n"):
                para = para.strip()
                if not para:
                    continue
                _run_cli(["set", filepath, "/", "--prop", f"text={para}"])
                is_heading = len(para) < 60 and not para.endswith("。")
                if is_heading:
                    _run_cli(["set", filepath, "/", "--prop", "style=Heading1"])
        elif format == "xlsx":
            rows = [line.split("\t") for line in content.strip().split("\n")]
            for ri, row in enumerate(rows):
                for ci, val in enumerate(row):
                    cell = chr(65 + ci) + str(ri + 1)
                    _run_cli(["set", filepath, cell, "--prop", f"value={val}"])
        elif format == "pptx":
            _run_cli(["set", filepath, "/", "--layout", "title"])
            for para in content.split("\n\n"):
                para = para.strip()
                if para:
                    _run_cli(["set", filepath, "--add-slide", "--prop", f"title={para[:100]}"])
        return filepath
    except Exception as e:
        logger.error("Document generation failed: %s", e)
        return f"文档生成失败: {e}"


def _create_blank(filepath: str, format: str) -> None:
    _run_cli(["create", filepath])
    if format in ("docx",):
        _run_cli(["set", filepath, "/", "--add-paragraph", "--prop", "text="])
    elif format == "pptx":
        _run_cli(["set", filepath, "/", "--add-slide", "--prop", "title=Slide 1"])


def _run_cli(args: list[str]) -> str:
    cmd = [OFFICECLI] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        logger.warning("officecli %s failed: %s", args[0], result.stderr[:200])
    return result.stdout


def _sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-." else "_" for c in name).strip() or "report"

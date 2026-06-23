from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from typing import Any

from src.gateway.wecom_outbound import download_media

logger = logging.getLogger(__name__)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_TEMPLATES_DIR = os.path.join(_REPO_ROOT, "data", "templates")
_LATEST_TEMPLATE_FILENAME = "latest_template.json"


def handle_wecom_file(payload: dict[str, Any]) -> dict[str, Any]:
    """Download a WeCom file, preserve template metadata, and return a structured summary."""
    media_id = payload.get("media_id", "")
    if not media_id:
        return {"summary": ""}

    filename = payload.get("content", "document")
    try:
        data, fname_hint = download_media(media_id)
        if fname_hint and fname_hint != media_id:
            filename = fname_hint
    except Exception as exc:
        logger.error("WeCom media download failed: %s", exc)
        return {"summary": f"文件 {filename} 下载失败：{exc}"}

    ext = os.path.splitext(filename)[1].lower()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp_path = ""
    try:
        tmp.write(data)
        tmp_path = tmp.name
        tmp.close()

        from_user_id = payload.get("from_user_id", "")
        template_meta = {
            "template_candidate": False,
            "template_path": "",
            "template_kind": "not_template",
        }
        if from_user_id:
            try:
                template_meta = prepare_template_candidate(tmp_path, filename, from_user_id)
            except Exception as exc:
                logger.warning("Failed to preserve template candidate %s: %s", filename, exc)

        summary = summarize_file_bytes(
            data,
            filename,
            from_user_id=from_user_id,
            source_path=tmp_path,
            preserve_template=False,
            owner_type=_infer_knowledge_owner_type(payload),
            owner_id=_infer_knowledge_owner_id(payload),
        )
        return {"summary": summary, "filename": filename, **template_meta}
    except Exception as exc:
        logger.exception("File processing failed")
        return {"summary": f"文件 {filename} 处理失败：{exc}"}
    finally:
        try:
            if tmp_path:
                os.unlink(tmp_path)
        except Exception:
            pass


def prepare_template_candidate(source_path: str, filename: str, user_id: str) -> dict[str, Any]:
    """Persist an Office template candidate so generation can use the original file later."""
    ext = os.path.splitext(filename)[1].lower()
    template_kind_map = {
        ".docx": "docx_template",
        ".xlsx": "xlsx_template",
        ".pptx": "pptx_template",
    }
    template_kind = template_kind_map.get(ext)
    if not template_kind:
        return {
            "template_candidate": False,
            "template_path": "",
            "template_kind": "not_template",
        }

    safe_user = _sanitize_path_component(user_id or "anonymous")
    safe_name = _sanitize_filename(filename)
    target_dir = os.path.join(_TEMPLATES_DIR, safe_user)
    os.makedirs(target_dir, exist_ok=True)

    target_path = os.path.join(target_dir, safe_name)
    if os.path.exists(target_path):
        stem, ext = os.path.splitext(safe_name)
        target_path = os.path.join(target_dir, f"{stem}_{next(tempfile._get_candidate_names())}{ext}")

    shutil.copyfile(source_path, target_path)
    payload = {
        "template_candidate": True,
        "template_path": target_path,
        "template_kind": template_kind,
        "captured_at": time.time(),
    }
    latest_path = os.path.join(target_dir, _LATEST_TEMPLATE_FILENAME)
    try:
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Failed to write latest template pointer for %s: %s", user_id, exc)
    return payload


def get_latest_template_candidate(
    user_id: str,
    now: float | None = None,
    max_age_seconds: int = 1800,
    expected_kind: str | None = None,
) -> str | None:
    safe_user = _sanitize_path_component(user_id or "anonymous")
    latest_path = os.path.join(_TEMPLATES_DIR, safe_user, _LATEST_TEMPLATE_FILENAME)
    if not os.path.isfile(latest_path):
        return None
    try:
        with open(latest_path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        logger.warning("Failed to read latest template pointer for %s: %s", user_id, exc)
        return None
    captured_at = float(payload.get("captured_at") or 0)
    current_time = now if now is not None else time.time()
    if current_time - captured_at > max_age_seconds:
        return None
    template_kind = str(payload.get("template_kind") or "").strip()
    if expected_kind and template_kind != expected_kind:
        return None
    template_path = str(payload.get("template_path") or "").strip()
    if not template_path or not os.path.isfile(template_path):
        return None
    return template_path


def summarize_file_bytes(
    data: bytes,
    filename: str,
    from_user_id: str = "",
    source_path: str = "",
    preserve_template: bool = True,
    owner_type: str = "organization",
    owner_id: str = "*",
) -> str:
    """Convert, index, and summarize a file payload regardless of transport."""
    filename = _normalize_office_filename(filename, data)
    tmp_path = source_path
    cleanup_needed = False
    if not tmp_path:
        ext = os.path.splitext(filename)[1].lower()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tmp.write(data)
        tmp_path = tmp.name
        tmp.close()
        cleanup_needed = True

    try:
        from src.knowledge.document_converter import convert_document, guess_type

        ftype = guess_type(filename)
        office_ext = os.path.splitext(filename)[1].lower()
        if ftype == "other" and office_ext in {".docx", ".xlsx", ".pptx"}:
            ftype = "document"
        if ftype == "other":
            return f"收到文件 {filename}（{_fmt_size(len(data))}），但暂不支持此格式。支持 .docx/.pdf/.xlsx/.pptx/.csv/.epub 等格式。"

        if from_user_id and preserve_template:
            try:
                prepare_template_candidate(tmp_path, filename, from_user_id)
            except Exception as exc:
                logger.warning("Failed to preserve template candidate %s: %s", filename, exc)

        markdown_text = convert_document(tmp_path)
        if not markdown_text or not markdown_text.strip():
            return f"文件 {filename} 已收到，但未能提取到文本内容。"
        markdown_text = markdown_text.replace("\x00", "")

        try:
            from src.knowledge.collector import KnowledgeCollector
            from src.knowledge.repository_factory import build_knowledge_repository

            repo = build_knowledge_repository()
            collector = KnowledgeCollector(repo)
            entry = collector.collect_file(tmp_path, owner_type=owner_type, owner_id=owner_id)
            logger.info("File indexed: %s (id=%s)", filename, entry.id if entry else "?")
        except Exception as exc:
            logger.warning("Failed to index file into knowledge base: %s", exc)

        text_preview = markdown_text[:5000]
        summary = (
            f"用户发送了文件：{filename}（{_fmt_size(len(data))}）\n\n"
            f"以下是文件内容：\n---\n{text_preview}\n---\n"
        )
        if len(markdown_text) > 5000:
            summary += "\n（文件内容较长，仅展示前 5000 字。已全部索引至知识库，可通过 search_knowledge 搜索完整内容）"
        return summary
    finally:
        if cleanup_needed:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / 1024 / 1024:.1f}MB"


def _sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-." else "_" for c in name).strip() or "template.docx"


def _sanitize_path_component(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in value).strip() or "anonymous"


def _normalize_office_filename(filename: str, data: bytes) -> str:
    """Recover Office suffixes when upstream transport loses the original extension."""
    name = (filename or "").strip() or "document"
    if os.path.splitext(name)[1]:
        return name
    if data.startswith(b"PK\x03\x04"):
        lowered = data[:4096].lower()
        if b"word/" in lowered or b"document.xml" in lowered:
            return f"{name}.docx"
        if b"xl/" in lowered or b"workbook.xml" in lowered:
            return f"{name}.xlsx"
        if b"ppt/" in lowered or b"presentation.xml" in lowered:
            return f"{name}.pptx"
    return name


def _infer_knowledge_owner_type(payload: dict[str, Any]) -> str:
    if payload.get("project_id"):
        return "project"
    if payload.get("dept_id"):
        return "department"
    if payload.get("is_direct"):
        return "personal"
    if payload.get("space_id"):
        return "project"
    return "organization"


def _infer_knowledge_owner_id(payload: dict[str, Any]) -> str:
    owner_type = _infer_knowledge_owner_type(payload)
    if owner_type == "personal":
        return str(payload.get("from_user_id") or payload.get("from") or "*")
    if owner_type == "department":
        return str(payload.get("dept_id") or "*")
    if owner_type == "project":
        return str(payload.get("project_id") or payload.get("space_id") or "*")
    return "*"

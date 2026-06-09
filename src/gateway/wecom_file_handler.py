from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

from src.gateway.wecom_outbound import download_media, send_text

logger = logging.getLogger(__name__)


def handle_wecom_file(payload: dict[str, Any]) -> str:
    """Download a WeCom file message, convert to text, and return the text content.
    
    Returns a descriptive message for the Agent to respond with, including
    the extracted text content.
    """
    media_id = payload.get("media_id", "")
    if not media_id:
        return ""
    
    filename = payload.get("content", "未知文件")
    file_size = payload.get("file_size", 0)
    
    try:
        data, fname_hint = download_media(media_id)
        if fname_hint and fname_hint != media_id:
            filename = fname_hint
    except Exception as e:
        logger.error("WeCom media download failed: %s", e)
        return f"文件 {filename} 下载失败：{e}"
    
    # Determine file extension
    ext = os.path.splitext(filename)[1].lower()
    
    # Write to temp file for processing
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    try:
        tmp.write(data)
        tmp_path = tmp.name
        tmp.close()
        
        # Check if this is a supported document type
        from src.knowledge.document_converter import convert_document, guess_type
        ftype = guess_type(filename)
        
        if ftype == "other":
            msg = f"收到文件 {filename}（{_fmt_size(len(data))}），但不支持此格式。支持 .docx/.pdf/.xlsx/.pptx/.csv/.epub 等格式。"
            send_text(payload.get("from_user_id", ""), msg)
            return msg
        
        # Convert document to text
        markdown_text = convert_document(tmp_path)
        if not markdown_text or not markdown_text.strip():
            msg = f"文件 {filename} 已收到但未能提取到文本内容。"
            send_text(payload.get("from_user_id", ""), msg)
            return msg
        
        # Index into gbrain/PostgreSQL knowledge base
        try:
            from src.knowledge.gbrain_repo import GbrainKnowledgeRepository
            from src.knowledge.collector import KnowledgeCollector

            repo = GbrainKnowledgeRepository()
            collector = KnowledgeCollector(repo)

            entry = collector.collect_file(tmp_path, owner_type="company", owner_id="*")
            logger.info("File indexed: %s (id=%s)", filename, entry.id if entry else "?")
        except Exception as e:
            logger.warning("Failed to index file into knowledge base: %s", e)
        
        # Truncate very long text
        text_preview = markdown_text[:5000]
        
        summary = (
            f"用户发送了文件：{filename}（{_fmt_size(len(data))}）\n\n"
            f"以下是文件内容：\n---\n{text_preview}\n---\n"
        )
        if len(markdown_text) > 5000:
            summary += f"\n（文件内容较长，仅展示前 5000 字。已全部索引至知识库，可通过 search_knowledge 搜索完整内容）"
        
        return summary
        
    except Exception as e:
        logger.exception("File processing failed")
        return f"文件 {filename} 处理失败：{e}"
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size/1024:.1f}KB"
    else:
        return f"{size/1024/1024:.1f}MB"

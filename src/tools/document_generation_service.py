from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any
from urllib.parse import quote

from src.tools.document_requirements import (
    build_fallback_content,
    build_template_prompt_block,
    infer_document_family,
    split_template_and_request,
)
from src.observability.langsmith_support import traceable_op

logger = logging.getLogger(__name__)


def build_document_download_url(filename: str) -> str:
    base_url = (
        os.environ.get("ANT_COLONY_DOCUMENT_BASE_URL") or "http://127.0.0.1:18092"
    ).rstrip("/")
    return f"{base_url}/api/v1/documents/{quote(filename)}"


@traceable_op("generate_document", run_type="tool")
def generate_document(args: dict[str, Any]) -> str:
    from src.gateway.wecom_file_handler import get_latest_template_candidate
    from src.tools.document_tool import generate_report

    title = args.get("title", "文档")
    content = args.get("content", "")
    fmt = args.get("format", "docx")
    user_id = args.get("from", "")
    context_text = args.pop("_context_text", "")
    source_provider = args.get("_source_provider", "")
    expected_template_kind = {
        "docx": "docx_template",
        "xlsx": "xlsx_template",
        "pptx": "pptx_template",
    }.get(fmt)
    template_path = args.get("_template_path") or (
        get_latest_template_candidate(user_id, expected_kind=expected_template_kind)
        if user_id and fmt in {"docx", "xlsx", "pptx"}
        else None
    )

    content = re.sub(r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL).strip()
    context_text = re.sub(r"<tool_call>.*?</tool_call>", "", context_text, flags=re.DOTALL).strip()
    template_text, request_text = split_template_and_request(context_text or content)

    if len(content.strip()) < 100:
        content = (request_text or content or title).strip()
    if not content.strip():
        return "请提供文档内容后再生成。请告诉我文档的具体内容、章节和需要包含的信息。"

    original_len = len(content)
    enriched = False
    err = ""
    try:
        from src.config.bootstrap import build_settings_service

        snapshot = None
        try:
            snapshot = build_settings_service().build_runtime_snapshot()
        except Exception as exc:
            err = f"settings: {exc}"

        if snapshot and snapshot.llm_profiles:
            for profile in snapshot.llm_profiles:
                if not profile.enabled:
                    continue
                api_base = (profile.api_base or "").rstrip("/")
                if not api_base or not profile.api_key:
                    continue

                import httpx

                template_block = build_template_prompt_block(
                    template_path,
                    template_text if len(template_text) > 50 else context_text,
                )
                prompt_text = (
                    "你是企业文档撰写专家。下面包含两部分：\n"
                    "【模板】一份文档模板/草稿，规定了章节结构、标题层级、编号格式、签字栏等框架\n"
                    "【要求】用户的具体需求\n\n"
                    "你的任务：完全按照【模板】的章节结构和格式框架，根据【要求】将内容充实为一篇可直接使用的正式文档。\n\n"
                    "规则：\n"
                    "1. 章节结构、标题层级、编号格式（1. / 1.1 / 第一条 等）、表格、签字栏全部继承自模板。\n"
                    "2. 模板中的空章节、占位符、简短标题要展开为有实质内容的完整段落。\n"
                    "3. 用户要求中的条目必须逐条吸收进正文，不能只重排模板原文。\n"
                    "4. 语言正式、条款式，符合企业规章制度格式。\n"
                    "5. 输出完整文档正文（含标题），不要额外说明，不要对话。\n"
                    "6. 如果模板与要求冲突，以要求为准；模板负责版式与章节框架，要求负责实际制度内容。\n\n"
                    "=== 【模板】===\n"
                    + template_block
                    + "\n\n=== 【要求】===\n"
                    + request_text
                )
                response = httpx.post(
                    api_base + "/chat/completions",
                    headers={"Authorization": "Bearer " + profile.api_key},
                    json={
                        "model": profile.model_name,
                        "messages": [{"role": "user", "content": prompt_text}],
                        "max_tokens": 16384,
                    },
                    timeout=180,
                )
                if response.status_code == 200:
                    llm_content = response.json()["choices"][0]["message"]["content"]
                    if llm_content and len(llm_content.strip()) >= 20:
                        content = llm_content
                        enriched = True
                else:
                    err = f"API {response.status_code}: {response.text[:200]}"
                break
    except Exception as exc:
        err = str(exc)

    if enriched:
        logger.info("Content enriched: %d -> %d chars", original_len, len(content))
    elif err:
        logger.warning("Content enrichment skipped: %s", err)
        family = infer_document_family(title, request_text or content)
        content = build_fallback_content(title, request_text or content, family=family)

    result = generate_report(title, content, fmt, template_path=template_path)
    if result.startswith("文档生成失败") or result.startswith("OfficeCLI"):
        return result

    filename = os.path.basename(result)
    pushed = False

    def print_debug(message: str) -> None:
        print("[builtin]", message, file=sys.stderr, flush=True)

    download_url = build_document_download_url(filename)
    if source_provider == "wecom_bot":
        return "[BOT_FILE]" + json.dumps(
            {
                "path": result,
                "filename": filename,
                "caption": f"文档已生成：{title}",
                "download_url": download_url,
            },
            ensure_ascii=False,
        )

    if user_id:
        print_debug("send_file: user_id=%s file=%s" % (user_id, filename))
        try:
            from src.gateway.wecom_outbound import send_file, send_file_card

            pushed = send_file_card(user_id, filename, download_url)
            print_debug("send_file_card -> %s" % pushed)
            if pushed:
                send_file(user_id, result)
        except Exception as exc:
            print_debug("send_file ERROR: %s" % exc)

    if pushed:
        return ""
    return f"文档已生成，点击下载：{download_url}"

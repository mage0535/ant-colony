from __future__ import annotations

import re

FILE_CONTEXT_PREFIX = (
    "【系统提示】你已经收到了用户上传文档的实际内容。"
    "下面“用户发送了文件”和“以下是文件内容”部分就是文档内容本身。"
    "不要再说没有收到文件，也不要优先去知识库搜索同名文档；"
    "请直接基于这些内容完成用户请求。"
)
TEMPLATE_SECTION_MARKER = "=== 【模板文件内容】==="
REQUEST_SECTION_MARKER = "=== 【用户要求】==="

FILE_PAIRING_HINTS = ("文档", "文件", "模板", "附件", "这个", "按这个", "参考这个", "生成", "分析", "提取")
FILE_REFERENTIAL_HINTS = ("文档", "文件", "模板", "附件", "按这个", "参考这个", "分析这个", "优化内容", "提取", "整理", "总结", "精炼")
DOCUMENT_INTENT_TOKENS = ("生成", "形成", "整理成", "做成", "写成")
DOCUMENT_TYPE_TOKENS = ("规定", "制度", "办法", "文档", "报告", "通知", "纪要", "方案")


def build_combined_file_message_content(file_text: str, request_text: str) -> str:
    return (
        FILE_CONTEXT_PREFIX
        + "\n\n"
        + TEMPLATE_SECTION_MARKER
        + "\n"
        + (file_text or "")
        + "\n\n"
        + REQUEST_SECTION_MARKER
        + "\n"
        + (request_text or "")
    )


def should_buffer_text_for_file_pairing(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    return any(token in normalized for token in FILE_PAIRING_HINTS)


def looks_file_referential(text: str) -> bool:
    normalized = (text or "").strip()
    return any(token in normalized for token in FILE_REFERENTIAL_HINTS)


def should_generate_document_from_content(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized or "用户发送了文件：" not in normalized:
        return False
    return looks_document_generation_request(normalized)


def looks_document_generation_request(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    return any(token in normalized for token in DOCUMENT_INTENT_TOKENS) and any(
        token in normalized for token in DOCUMENT_TYPE_TOKENS
    )


def infer_document_title(text: str) -> str:
    normalized = (text or "").replace("\n", " ")
    match = re.search(r"生成(?:一个|一份)?([^\n，。]{2,40}?(?:规定|制度|办法|文档|报告|通知|纪要|方案))", normalized)
    if match:
        return match.group(1).strip()
    return "文档"

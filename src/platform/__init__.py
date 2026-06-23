"""Compatibility facade over the unified capability backend.

This module remains intentionally thin. New tool-layer code should prefer
`invoke_capability(...)` / `invoke_capability_first(...)` so capability IDs
stay explicit and context/audit metadata can flow through one path.
"""

from __future__ import annotations

import logging
import os

from src.platform.capability_audit import CapabilityInvocationContext
from src.platform.capability_backend import CapabilityBackend, CapabilityProvider

logger = logging.getLogger(__name__)


def _try_feishu():
    if not (os.environ.get("FEISHU_APP_ID") and os.environ.get("FEISHU_APP_SECRET")):
        return None
    from src.platform.api_feishu import FeishuClient

    try:
        return FeishuClient()
    except Exception as exc:
        logger.warning("Feishu client failed: %s", exc)
    return None


def _try_dingtalk():
    if not (os.environ.get("DINGTALK_CLIENT_ID") and os.environ.get("DINGTALK_CLIENT_SECRET")):
        return None
    from src.platform.api_dingtalk import DingTalkClient

    try:
        return DingTalkClient()
    except Exception as exc:
        logger.warning("DingTalk client failed: %s", exc)
    return None


def _try_wecom():
    if not os.environ.get("WECOM_CORP_ID") or not os.environ.get("WECOM_SECRET"):
        return None
    from src.platform.api_wecom import WeComClient

    try:
        return WeComClient()
    except Exception as exc:
        logger.warning("WeCom client failed: %s", exc)
    return None


def _try_stirling():
    from src.platform.stirling_pdf_provider import StirlingPdfProvider

    provider = StirlingPdfProvider()
    if not provider.is_configured():
        return None
    return provider


def _try_officecli():
    from src.platform.officecli_provider import OfficeCliProvider

    provider = OfficeCliProvider()
    if not provider.is_configured():
        return None
    return provider


def _try_ocrmypdf():
    from src.platform.ocrmypdf_provider import OcrmypdfProvider

    provider = OcrmypdfProvider()
    if not provider.is_configured():
        return None
    return provider


def get_capability_backend() -> CapabilityBackend:
    from src.platform.internal_capability_provider import InternalCapabilityProvider

    return CapabilityBackend(
        [
            CapabilityProvider("officecli", "OfficeCLI", _try_officecli),
            CapabilityProvider("stirling", "Stirling-PDF", _try_stirling),
            CapabilityProvider("ocrmypdf", "OCRmyPDF", _try_ocrmypdf),
            CapabilityProvider("internal", "系统能力", lambda: InternalCapabilityProvider()),
            CapabilityProvider("feishu", "飞书", _try_feishu),
            CapabilityProvider("dingtalk", "钉钉", _try_dingtalk),
            CapabilityProvider("wecom", "企业微信", _try_wecom),
        ]
    )


def _invoke_formatted(capability_id: str, empty_message: str, *args):
    backend = get_capability_backend()
    results = backend.invoke(capability_id, *args)
    return backend.format_results(results, empty_message)


def _invoke_first_content(capability_id: str, empty_message: str, *args):
    backend = get_capability_backend()
    result = backend.invoke_first(capability_id, *args)
    return result.content if result else empty_message


def build_capability_context(
    *,
    user_id: str = "",
    platform: str = "",
    transport: str = "",
    scope: str = "",
    scope_id: str = "",
    source_chat_id: str = "",
    metadata: dict | None = None,
) -> CapabilityInvocationContext:
    return CapabilityInvocationContext(
        user_id=user_id,
        platform=platform,
        transport=transport,
        scope=scope,
        scope_id=scope_id,
        source_chat_id=source_chat_id,
        metadata=metadata or {},
    )


def invoke_capability(capability_id: str, *args, context: CapabilityInvocationContext | dict | None = None, empty_message: str = "") -> str:
    backend = get_capability_backend()
    results = backend.invoke(capability_id, *args, context=context)
    return backend.format_results(results, empty_message)


def invoke_capability_first(
    capability_id: str,
    *args,
    context: CapabilityInvocationContext | dict | None = None,
    empty_message: str = "",
) -> str:
    backend = get_capability_backend()
    result = backend.invoke_first(capability_id, *args, context=context)
    return result.content if result else empty_message


def _build_formatted_wrapper(capability_id: str, empty_message: str):
    def _wrapper(*args):
        return _invoke_formatted(capability_id, empty_message, *args)

    return _wrapper


def _build_first_content_wrapper(capability_id: str, empty_message: str):
    def _wrapper(*args):
        return _invoke_first_content(capability_id, empty_message, *args)

    return _wrapper


contact_search = _build_formatted_wrapper("contacts.search", "未找到匹配的联系人")
calendar_agenda = _build_formatted_wrapper("calendar.list", "未找到日程信息（需配置飞书/钉钉/企微凭证）")
doc_search = _build_formatted_wrapper("docs.search", "未找到匹配的文档（需配置飞书/钉钉/企微凭证）")
approval_list = _build_formatted_wrapper("approval.list", "无待审批事项（需配置飞书/钉钉凭证）")
calendar_create = _build_formatted_wrapper("calendar.create", "创建日程失败（需配置飞书/钉钉/企微凭证）")
pdf_service_status = _build_formatted_wrapper("files.pdf.service_status", "暂无可用 PDF 服务状态信息")
office_service_status = _build_formatted_wrapper("files.office.service_status", "暂无可用 Office 文档服务状态信息")
generate_docx = _build_first_content_wrapper("files.docx.generate", "暂无可用 DOCX 生成能力")
generate_xlsx = _build_first_content_wrapper("files.xlsx.generate", "暂无可用 XLSX 生成能力")
generate_pptx = _build_first_content_wrapper("files.pptx.generate", "暂无可用 PPTX 生成能力")
docx_template_outline = _build_first_content_wrapper("files.docx.template_outline", {})
xlsx_template_outline = _build_first_content_wrapper("files.xlsx.template_outline", {})
pptx_template_outline = _build_first_content_wrapper("files.pptx.template_outline", {})
read_docx = _build_first_content_wrapper("files.docx.read", "暂无可用 DOCX 读取能力")
read_xlsx = _build_first_content_wrapper("files.xlsx.read", "暂无可用 XLSX 读取能力")
read_pptx = _build_first_content_wrapper("files.pptx.read", "暂无可用 PPTX 读取能力")
ocr_pdf = _build_first_content_wrapper("files.pdf.ocr", "暂无可用 PDF OCR 能力")
merge_pdfs = _build_first_content_wrapper("files.pdf.merge", "暂无可用 PDF 合并能力")
split_pdf = _build_first_content_wrapper("files.pdf.split", "暂无可用 PDF 拆分能力")
compress_pdf = _build_first_content_wrapper("files.pdf.compress", "暂无可用 PDF 压缩能力")
protect_pdf = _build_first_content_wrapper("files.pdf.protect", "暂无可用 PDF 加密能力")
read_pdf = _build_first_content_wrapper("files.pdf.read", "暂无可用 PDF 读取能力")
extract_pdf_images = _build_first_content_wrapper("files.pdf.extract_images", "暂无可用 PDF 图片提取能力")
watermark_pdf = _build_first_content_wrapper("files.pdf.watermark", "暂无可用 PDF 水印能力")
drive_search = _build_formatted_wrapper("drive.search", "未找到匹配的网盘文件（待接入企业网盘能力）")
mail_summary = _build_formatted_wrapper("mail.summary", "暂无可用邮箱能力（待接入企业邮箱能力）")


def create_doc(title: str, content: str = "") -> str:
    result = invoke_capability_first("docs.create", title, content, empty_message="需配置企业微信凭证")
    return result or "文档创建成功"


list_meetings = _build_formatted_wrapper("meeting.list", "未找到会议信息（需配置企微/钉钉凭证）")


def create_meeting(title: str, start_at: str, end_at: str, attendees: str = "") -> str:
    attendee_list = [a.strip() for a in attendees.split(",") if a.strip()] if attendees else []
    return invoke_capability("meeting.create", title, start_at, end_at, attendee_list, empty_message="创建会议失败（需配置企微凭证）")


def who_is_admin() -> str:
    backend = get_capability_backend()
    results = backend.invoke("org.admins")
    if not results:
        return "未配置平台管理员信息"
    return "\n\n".join(f"[{item.provider_label}]\n{item.content}" for item in results)


def who_is_leader() -> str:
    backend = get_capability_backend()
    results = backend.invoke("org.leaders")
    if not results:
        return "未查询到部门负责人信息（需配置企微凭证）"
    return "\n\n".join(f"[{item.provider_label}]\n{item.content}" for item in results)


def list_capabilities() -> str:
    backend = get_capability_backend()
    lines: list[str] = []
    for capability_id in backend.list_capabilities():
        info = backend.describe_capability(capability_id)
        if not info:
            continue
        providers = ", ".join(info.get("providers", [])) or "-"
        lines.append(f"{capability_id} | {info.get('method_name', '')} | {providers}")
    return "\n".join(lines) if lines else "当前未注册任何能力协议"

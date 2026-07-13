from __future__ import annotations

import logging
import inspect
from dataclasses import dataclass
from typing import Any, Callable

from src.platform.capability_audit import (
    CapabilityInvocationContext,
    coerce_capability_context,
    record_capability_audit,
)
from src.observability.langsmith_support import traceable_op

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlatformCapabilityResult:
    provider: str
    provider_label: str
    content: str
    success: bool = True


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    capability_id: str
    method_name: str
    provider_ids: frozenset[str] | None = None
    risk_level: str = "low"
    domain: str = ""
    requires_user_context: bool = False
    audit_scope: str = "default"


CapabilityClientFactory = Callable[[], Any | None]


@dataclass(slots=True)
class CapabilityProvider:
    provider_id: str
    provider_label: str
    factory: CapabilityClientFactory


class CapabilityBackend:
    """Unified backend for enterprise IM application capabilities."""

    DEFAULT_CAPABILITIES: dict[str, CapabilitySpec] = {
        "contacts.search": CapabilitySpec("contacts.search", "search_user", domain="contacts", requires_user_context=True),
        "calendar.list": CapabilitySpec("calendar.list", "get_agenda", domain="calendar", requires_user_context=True),
        "calendar.create": CapabilitySpec("calendar.create", "create_event"),
        "docs.search": CapabilitySpec("docs.search", "search_docs", domain="docs", requires_user_context=True),
        "docs.read": CapabilitySpec("docs.read", "read_docs_document", domain="docs", requires_user_context=True),
        "docs.create": CapabilitySpec("docs.create", "create_doc", frozenset({"wecom_robot_mcp", "wecom"}), domain="docs", requires_user_context=True),
        "docs.edit": CapabilitySpec("docs.edit", "edit_doc_content", frozenset({"wecom_robot_mcp"}), risk_level="medium", domain="docs", requires_user_context=True, audit_scope="sensitive"),
        "docs.smartpage.create": CapabilitySpec("docs.smartpage.create", "smartpage_create", frozenset({"wecom_robot_mcp"}), domain="docs", requires_user_context=True),
        "sheet.append": CapabilitySpec("sheet.append", "sheet_append_data", frozenset({"wecom_robot_mcp"}), risk_level="medium", domain="docs", requires_user_context=True, audit_scope="sensitive"),
        "todo.create": CapabilitySpec("todo.create", "create_todo", frozenset({"wecom_robot_mcp"}), risk_level="medium", domain="todo", requires_user_context=True, audit_scope="sensitive"),
        "todo.list": CapabilitySpec("todo.list", "list_todos", frozenset({"wecom_robot_mcp"}), domain="todo", requires_user_context=True),
        "todo.detail": CapabilitySpec("todo.detail", "get_todo_detail", frozenset({"wecom_robot_mcp"}), domain="todo", requires_user_context=True),
        "todo.update": CapabilitySpec("todo.update", "update_todo", frozenset({"wecom_robot_mcp"}), risk_level="medium", domain="todo", requires_user_context=True, audit_scope="sensitive"),
        "todo.delete": CapabilitySpec("todo.delete", "delete_todo", frozenset({"wecom_robot_mcp"}), risk_level="high", domain="todo", requires_user_context=True, audit_scope="sensitive"),
        "todo.user.search": CapabilitySpec("todo.user.search", "search_todo_userid", frozenset({"wecom_robot_mcp"}), domain="todo", requires_user_context=True),
        "todo.user_status.change": CapabilitySpec("todo.user_status.change", "change_todo_user_status", frozenset({"wecom_robot_mcp"}), risk_level="medium", domain="todo", requires_user_context=True, audit_scope="sensitive"),
        "approval.list": CapabilitySpec("approval.list", "list_approvals", frozenset({"wecom", "feishu", "dingtalk"}), domain="approval", requires_user_context=True),
        "approval.detail": CapabilitySpec("approval.detail", "get_approval_detail", risk_level="medium", domain="approval", requires_user_context=True),
        "meeting.list": CapabilitySpec("meeting.list", "list_meetings", frozenset({"wecom", "dingtalk"}), domain="meeting", requires_user_context=True),
        "meeting.get": CapabilitySpec("meeting.get", "get_meeting_detail", risk_level="medium", domain="meeting", requires_user_context=True),
        "meeting.create": CapabilitySpec("meeting.create", "create_meeting", frozenset({"wecom"})),
        "calendar.detail": CapabilitySpec("calendar.detail", "get_event_detail", risk_level="medium", domain="calendar", requires_user_context=True),
        "apps.query": CapabilitySpec("apps.query", "query_enterprise_apps", domain="apps", requires_user_context=True),
        "apps.catalog": CapabilitySpec("apps.catalog", "list_accessible_applications", domain="apps", requires_user_context=True),
        "apps.action": CapabilitySpec("apps.action", "run_enterprise_app_action", risk_level="medium", domain="apps", requires_user_context=True, audit_scope="sensitive"),
        "meeting.room.query": CapabilitySpec("meeting.room.query", "query_meeting_room", domain="meeting", requires_user_context=True),
        "org.admins": CapabilitySpec("org.admins", "get_admin_users"),
        "org.leaders": CapabilitySpec("org.leaders", "get_department_leaders", frozenset({"wecom"})),
        "drive.search": CapabilitySpec("drive.search", "search_drive_docs", domain="drive", requires_user_context=True),
        "drive.read": CapabilitySpec("drive.read", "read_drive_doc", domain="drive", requires_user_context=True),
        "drive.list": CapabilitySpec("drive.list", "list_drive_docs", frozenset({"internal"}), domain="drive"),
        "drive.sync": CapabilitySpec("drive.sync", "sync_drive_docs", frozenset({"internal"}), risk_level="medium", domain="drive", requires_user_context=True),
        "im.entry.menu": CapabilitySpec("im.entry.menu", "build_entry_menu", frozenset({"internal"}), domain="im", requires_user_context=True),
        "im.entry.payloads": CapabilitySpec("im.entry.payloads", "build_entry_payloads", frozenset({"internal"}), domain="im", requires_user_context=True),
        "mail.summary": CapabilitySpec("mail.summary", "summarize_mailbox"),
        "mail.list": CapabilitySpec("mail.list", "list_mail_messages", frozenset({"internal"}), domain="mail"),
        "mail.search": CapabilitySpec("mail.search", "search_mail_messages", frozenset({"internal"}), domain="mail"),
        "mail.get": CapabilitySpec("mail.get", "get_mail_message", frozenset({"internal"}), risk_level="medium", domain="mail", requires_user_context=True),
        "mail.send": CapabilitySpec("mail.send", "send_mail_message", frozenset({"internal"}), risk_level="medium", domain="mail", requires_user_context=True, audit_scope="sensitive"),
        "ops.workorder.lookup": CapabilitySpec("ops.workorder.lookup", "lookup_workorder", frozenset({"internal"}), domain="operations", requires_user_context=True),
        "ops.workorder.analyze": CapabilitySpec("ops.workorder.analyze", "analyze_workorder", frozenset({"internal"}), domain="operations", requires_user_context=True),
        "files.office.service_status": CapabilitySpec("files.office.service_status", "healthcheck_office", frozenset({"officecli", "internal"})),
        "files.docx.generate": CapabilitySpec("files.docx.generate", "generate_docx_document", frozenset({"officecli", "internal"})),
        "files.xlsx.generate": CapabilitySpec("files.xlsx.generate", "generate_xlsx_document", frozenset({"officecli", "internal"})),
        "files.pptx.generate": CapabilitySpec("files.pptx.generate", "generate_pptx_document", frozenset({"officecli", "internal"})),
        "files.docx.template_outline": CapabilitySpec("files.docx.template_outline", "extract_docx_template_outline", frozenset({"officecli", "internal"})),
        "files.xlsx.template_outline": CapabilitySpec("files.xlsx.template_outline", "extract_xlsx_template_outline", frozenset({"officecli", "internal"})),
        "files.pptx.template_outline": CapabilitySpec("files.pptx.template_outline", "extract_pptx_template_outline", frozenset({"officecli", "internal"})),
        "files.docx.read": CapabilitySpec("files.docx.read", "read_docx_document", frozenset({"officecli", "internal"})),
        "files.xlsx.read": CapabilitySpec("files.xlsx.read", "read_xlsx_document", frozenset({"officecli", "internal"})),
        "files.pptx.read": CapabilitySpec("files.pptx.read", "read_pptx_document", frozenset({"officecli", "internal"})),
        "files.pdf.merge": CapabilitySpec("files.pdf.merge", "merge_pdf_documents", frozenset({"stirling", "internal"})),
        "files.pdf.split": CapabilitySpec("files.pdf.split", "split_pdf_document", frozenset({"stirling", "internal"})),
        "files.pdf.compress": CapabilitySpec("files.pdf.compress", "compress_pdf_document", frozenset({"stirling", "internal"})),
        "files.pdf.protect": CapabilitySpec("files.pdf.protect", "protect_pdf_document", frozenset({"stirling", "internal"})),
        "files.pdf.read": CapabilitySpec("files.pdf.read", "read_pdf_document", frozenset({"stirling", "internal"})),
        "files.pdf.extract_images": CapabilitySpec("files.pdf.extract_images", "extract_pdf_images", frozenset({"stirling", "internal"})),
        "files.pdf.watermark": CapabilitySpec("files.pdf.watermark", "watermark_pdf_document", frozenset({"stirling", "internal"})),
        "files.pdf.service_status": CapabilitySpec("files.pdf.service_status", "healthcheck"),
        "files.pdf.ocr": CapabilitySpec("files.pdf.ocr", "ocr_pdf_document", frozenset({"ocrmypdf"})),
    }

    def __init__(self, providers: list[CapabilityProvider], capabilities: dict[str, CapabilitySpec] | None = None) -> None:
        self.providers = providers
        self.capabilities = capabilities or self.DEFAULT_CAPABILITIES

    def call_all(
        self,
        method_name: str,
        *args: Any,
        capability_id: str = "",
        context: CapabilityInvocationContext | dict[str, Any] | None = None,
        providers: set[str] | None = None,
        **kwargs: Any,
    ) -> list[PlatformCapabilityResult]:
        results: list[PlatformCapabilityResult] = []
        resolved_context = coerce_capability_context(context)
        for provider in self.providers:
            if providers and provider.provider_id not in providers:
                continue
            client = self._safe_client(provider)
            if not client:
                continue
            if not hasattr(client, method_name):
                continue
            try:
                method = getattr(client, method_name)
                call_kwargs = dict(kwargs)
                if "capability_context" in inspect.signature(method).parameters:
                    call_kwargs["capability_context"] = resolved_context
                response = method(*args, **call_kwargs)
                if response:
                    result = PlatformCapabilityResult(
                        provider=provider.provider_id,
                        provider_label=provider.provider_label,
                        content=str(response),
                        success=True,
                    )
                    results.append(result)
                    if capability_id:
                        record_capability_audit(
                            capability_id,
                            provider.provider_id,
                            provider.provider_label,
                            True,
                            resolved_context,
                            {"method_name": method_name},
                        )
            except Exception as exc:
                result = PlatformCapabilityResult(
                    provider=provider.provider_id,
                    provider_label=provider.provider_label,
                    content=str(exc),
                    success=False,
                )
                results.append(result)
                if capability_id:
                    record_capability_audit(
                        capability_id,
                        provider.provider_id,
                        provider.provider_label,
                        False,
                        resolved_context,
                        {"method_name": method_name, "error": str(exc)},
                    )
        return results

    def call_first(
        self,
        method_name: str,
        *args: Any,
        capability_id: str = "",
        context: CapabilityInvocationContext | dict[str, Any] | None = None,
        providers: set[str] | None = None,
        **kwargs: Any,
    ) -> PlatformCapabilityResult | None:
        results = self.call_all(
            method_name,
            *args,
            capability_id=capability_id,
            context=context,
            providers=providers,
            **kwargs,
        )
        return results[0] if results else None

    def format_results(self, results: list[PlatformCapabilityResult], empty_message: str) -> str:
        safe_results = [item for item in results if item.success and item.content.strip()]
        if not safe_results:
            return empty_message
        return "\n".join(f"[{item.provider_label}] {item.content}" for item in safe_results)

    @traceable_op("capability_invoke", run_type="tool")
    def invoke(
        self,
        capability_id: str,
        *args: Any,
        context: CapabilityInvocationContext | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[PlatformCapabilityResult]:
        spec = self.capabilities.get(capability_id)
        if not spec:
            logger.warning("Unknown capability requested: %s", capability_id)
            return []
        provider_filter = set(spec.provider_ids) if spec.provider_ids else None
        resolved_context = coerce_capability_context(context)
        platform_provider = _platform_provider_id(resolved_context.platform)
        platform_scoped_domains = {"apps", "contacts", "calendar", "docs", "approval", "meeting", "drive", "mail", "todo"}
        has_platform_provider = any(
            provider.provider_id == platform_provider for provider in self.providers
        )
        if spec.domain in platform_scoped_domains and platform_provider and has_platform_provider:
            scoped_providers = {"internal", platform_provider}
            if platform_provider == "wecom":
                scoped_providers.add("wecom_robot_mcp")
            provider_filter = scoped_providers if provider_filter is None else provider_filter & scoped_providers
        return self.call_all(
            spec.method_name,
            *args,
            capability_id=capability_id,
            context=context,
            providers=provider_filter,
            **kwargs,
        )

    @traceable_op("capability_invoke_first", run_type="tool")
    def invoke_first(
        self,
        capability_id: str,
        *args: Any,
        context: CapabilityInvocationContext | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> PlatformCapabilityResult | None:
        results = self.invoke(capability_id, *args, context=context, **kwargs)
        if not results:
            return None
        for item in results:
            if item.success:
                return item
        return None

    def supports(self, capability_id: str) -> bool:
        return capability_id in self.capabilities

    def list_capabilities(self) -> list[str]:
        return sorted(self.capabilities.keys())

    def describe_capability(self, capability_id: str) -> dict[str, Any] | None:
        spec = self.capabilities.get(capability_id)
        if not spec:
            return None
        provider_labels: list[str] = []
        for provider in self.providers:
            if spec.provider_ids and provider.provider_id not in spec.provider_ids:
                continue
            provider_labels.append(provider.provider_label)
        info = {
            "capability_id": spec.capability_id,
            "method_name": spec.method_name,
            "providers": provider_labels,
        }
        if spec.risk_level != "low":
            info["risk_level"] = spec.risk_level
        if spec.domain:
            info["domain"] = spec.domain
        if spec.requires_user_context:
            info["requires_user_context"] = spec.requires_user_context
        if spec.audit_scope != "default":
            info["audit_scope"] = spec.audit_scope
        return info

    def _safe_client(self, provider: CapabilityProvider) -> Any | None:
        try:
            return provider.factory()
        except Exception as exc:
            logger.warning("%s capability client init failed: %s", provider.provider_id, exc)
            return None


def _platform_provider_id(platform: str) -> str:
    normalized = str(platform or "").strip().lower()
    aliases = {
        "wecom_bot": "wecom",
        "wecom_callback": "wecom",
        "feishu_bot": "feishu",
        "dingtalk_bot": "dingtalk",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"wecom", "feishu", "dingtalk"} else ""

from __future__ import annotations

import json
import os
import os
from pathlib import Path

from src.knowledge.repository_factory import build_knowledge_repository


class InternalCapabilityProvider:
    """Internal capability provider backed by existing local tools/integrations."""

    def healthcheck(self) -> str | None:
        return "internal-provider-ready"

    def healthcheck_office(self) -> str | None:
        from src.tools.document_tool import OFFICECLI

        return "officecli-ready" if os.path.isfile(OFFICECLI) else None

    def search_drive_docs(self, query: str) -> str | None:
        from src.knowledge.cloud_drive import list_drives

        listing = list_drives(user_id="")
        if not listing:
            return None
        if not query:
            return listing

        lines = [line for line in listing.splitlines() if query.lower() in line.lower()]
        if not lines:
            return f"未找到与“{query}”匹配的网盘结果。当前可先检查云盘是否已注册并完成同步。"
        return "\n".join(lines)

    def read_drive_doc(self, query: str) -> str | None:
        repo = build_knowledge_repository()
        results = repo.search(query, limit=1)
        if not results:
            return None
        return results[0].content[:4000]

    def list_drive_docs(self) -> str | None:
        from src.knowledge.cloud_drive import list_drives

        return list_drives(user_id="")

    def sync_drive_docs(self, drive_id: str, remote_path: str, local_path: str = "") -> str | None:
        from src.knowledge.cloud_drive import sync_from_cloud

        return sync_from_cloud(drive_id=drive_id, remote_path=remote_path, local_path=local_path, user_id="")

    def summarize_mailbox(self, query: str = "") -> str | None:
        from src.tools.email_tool import list_inbox, search_emails

        if query.strip():
            return search_emails(query)
        return list_inbox(limit=10)

    def read_docs_document(self, query: str) -> str | None:
        repo = build_knowledge_repository()
        results = repo.search(query, limit=1)
        if not results:
            return None
        return results[0].content[:4000]

    def search_docs(self, query: str) -> str | None:
        repo = build_knowledge_repository()
        results = repo.search(query, limit=5)
        if not results:
            return None
        lines = [f"[{item.owner_type.value}] {item.content[:120]}" for item in results]
        return "\n".join(lines)

    def list_mail_messages(self, limit: int = 10) -> str | None:
        from src.tools.email_tool import list_inbox

        return list_inbox(limit=limit)

    def search_mail_messages(self, query: str) -> str | None:
        from src.tools.email_tool import search_emails

        return search_emails(query)

    def get_mail_message(self, uid: str) -> str | None:
        from src.tools.email_tool import get_email

        return get_email(uid=uid)

    def send_mail_message(self, to: str, subject: str, body: str, cc: str | None = None) -> str | None:
        from src.tools.email_tool import send_email

        return send_email(to=to, subject=subject, body=body, cc=cc)

    def generate_docx_document(self, title: str, content: str, template_path: str | None = None) -> str | None:
        from src.tools.document_tool import generate_report

        return generate_report(title, content, "docx", template_path=template_path)

    def generate_xlsx_document(self, title: str, content: str, template_path: str | None = None) -> str | None:
        from src.tools.document_tool import generate_report

        return generate_report(title, content, "xlsx", template_path=template_path)

    def generate_pptx_document(self, title: str, content: str, template_path: str | None = None) -> str | None:
        from src.tools.document_tool import generate_report

        return generate_report(title, content, "pptx", template_path=template_path)

    def extract_docx_template_outline(self, path: str) -> dict | None:
        from src.tools.document_tool import extract_docx_template_outline

        return extract_docx_template_outline(path)

    def extract_xlsx_template_outline(self, path: str) -> dict | None:
        from src.tools.document_tool import extract_xlsx_template_outline

        return extract_xlsx_template_outline(path)

    def extract_pptx_template_outline(self, path: str) -> dict | None:
        from src.tools.document_tool import extract_pptx_template_outline

        return extract_pptx_template_outline(path)

    def read_docx_document(self, path: str) -> str | None:
        from src.platform.officecli_provider import OfficeCliProvider

        return OfficeCliProvider().read_docx_document(path)

    def read_xlsx_document(self, path: str) -> str | None:
        from src.platform.officecli_provider import OfficeCliProvider

        return OfficeCliProvider().read_xlsx_document(path)

    def read_pptx_document(self, path: str) -> str | None:
        from src.platform.officecli_provider import OfficeCliProvider

        return OfficeCliProvider().read_pptx_document(path)

    def merge_pdf_documents(self, paths: list[str], output_path: str) -> str | None:
        from src.tools.pdf_tool import merge_pdfs

        return merge_pdfs(paths, output_path)

    def split_pdf_document(self, path: str, pages: str, output_path: str) -> str | None:
        from src.tools.pdf_tool import split_pdf

        return split_pdf(path, pages, output_path)

    def compress_pdf_document(self, path: str, output_path: str) -> str | None:
        from src.tools.pdf_tool import compress_pdf

        return compress_pdf(path, output_path)

    def protect_pdf_document(self, path: str, password: str, output_path: str) -> str | None:
        from src.tools.pdf_tool import protect_pdf

        return protect_pdf(path, password, output_path)

    def read_pdf_document(self, path: str) -> str | None:
        from src.tools.pdf_tool import read_pdf

        return read_pdf(path)

    def extract_pdf_images(self, path: str, output_dir: str) -> str | None:
        from src.tools.pdf_tool import extract_images

        return extract_images(path, output_dir)

    def watermark_pdf_document(self, path: str, watermark_text: str, output_path: str) -> str | None:
        from src.tools.pdf_tool import add_watermark

        return add_watermark(path, watermark_text, output_path)

    def build_entry_menu(self, platform: str, user_id: str, is_admin: bool = False) -> str | None:
        from src.gateway.entry_links import build_platform_entry_menu

        return json.dumps(build_platform_entry_menu(platform, user_id, is_admin=is_admin), ensure_ascii=False)

    def build_entry_payloads(self, platform: str, user_id: str, is_admin: bool = False) -> str | None:
        from src.gateway.entry_links import build_platform_entry_payloads

        return json.dumps(build_platform_entry_payloads(platform, user_id, is_admin=is_admin), ensure_ascii=False)

    def query_meeting_room(self, query: str, days: int = 1) -> str | None:
        if not _sample_enterprise_apps_enabled():
            return None
        samples = _load_sample_enterprise_apps()
        rooms = samples.get("meeting_rooms", [])
        keyword = _extract_room_keyword(query)
        matches = []
        for item in rooms:
            name = str(item.get("room_name", ""))
            if keyword and keyword not in name:
                continue
            matches.append(f"{name}：{item.get('date', '')} {item.get('start', '')}-{item.get('end', '')}，{item.get('title', '')}，申请人 {item.get('applicant', '')}")
        if matches:
            return "\n".join(matches)
        return f"本地样例数据中未发现{keyword or '会议室'}占用记录"

    def query_enterprise_apps(self, query: str, action: str = "query") -> str | None:
        if not _sample_enterprise_apps_enabled():
            return None
        samples = _load_sample_enterprise_apps()
        sections: list[str] = []
        if any(word in query for word in ("会议室", "会议", "占用", "申请")):
            room = self.query_meeting_room(query)
            if room:
                sections.append("【会议室/会议】\n" + room)
        if "审批" in query or "流程" in query or "申请" in query:
            approvals = samples.get("approvals", [])
            if approvals:
                lines = [f"{item.get('title', '')}：{item.get('status', '')}，申请人 {item.get('applicant', '')}，当前节点 {item.get('current_node', '')}" for item in approvals]
                sections.append("【审批/流程】\n" + "\n".join(lines))
        if "第三方" in query or "工单" in query or "订单" in query:
            apps = samples.get("third_party_apps", [])
            if apps:
                lines = [f"{item.get('name', '')}：{item.get('summary', '')}" for item in apps]
                sections.append("【第三方应用】\n" + "\n".join(lines))
        return "\n\n".join(sections) if sections else None

    def run_enterprise_app_action(self, action: str, payload: dict | None = None) -> str | None:
        if not _sample_enterprise_apps_enabled():
            return None
        return f"本地能力已收到动作请求：{action}。真实执行会按平台权限进入对应 IM 应用 API。"

    def lookup_workorder(self, workorder_id: str) -> str | None:
        data = _load_sample_workorders()
        if not workorder_id:
            return "请提供工单号"
        item = data.get(workorder_id)
        if not item:
            return f"未找到工单：{workorder_id}"
        return json.dumps(item, ensure_ascii=False, indent=2)

    def analyze_workorder(self, workorder_id: str) -> str | None:
        data = _load_sample_workorders()
        item = data.get(workorder_id)
        if not item:
            return f"未找到工单：{workorder_id}"
        status = str(item.get("status", ""))
        risk = "低"
        reasons: list[str] = []
        if status in {"blocked", "delayed"}:
            risk = "高"
            reasons.append("工单当前处于阻塞或延迟状态")
        if item.get("pending_approval"):
            reasons.append("存在待审批事项")
        if item.get("pending_material"):
            reasons.append("存在待料风险")
        if not reasons:
            reasons.append("当前无明显异常，可按计划推进")
        return f"工单 {workorder_id} 风险等级：{risk}\n" + "\n".join(f"- {r}" for r in reasons)


def _load_sample_workorders() -> dict[str, dict]:
    path = Path("data/business_systems/sample_workorders.json")
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_sample_enterprise_apps() -> dict[str, list[dict]]:
    path = Path("data/business_systems/sample_enterprise_apps.json")
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _sample_enterprise_apps_enabled() -> bool:
    return os.environ.get("ANT_COLONY_ENABLE_SAMPLE_BUSINESS_DATA", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _extract_room_keyword(query: str) -> str:
    import re

    match = re.search(r"([\u4e00-\u9fffA-Za-z0-9一二三四五六七八九十]+号?会议室)", query)
    return match.group(1) if match else ("会议室" if "会议室" in query else "")

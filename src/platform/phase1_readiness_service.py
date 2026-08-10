from __future__ import annotations

import os
import time
from typing import Any

from src.store.database import Database


def collect_phase1_readiness(*, platform: str = "wecom", user_id: str = "") -> dict[str, Any]:
    """Report whether Phase 1 office capabilities are truly usable on this deployment.

    The report intentionally avoids live destructive actions. It checks local
    state, configured credentials, and bounded provider readiness so operators
    can distinguish implemented code from tenant permission or edition limits.
    """

    normalized_platform = (platform or "wecom").strip() or "wecom"
    normalized_user = (user_id or "").strip()
    items = {
        "knowledge": _knowledge_status(),
        "tasks": _task_status(),
        "contacts": _contacts_status(normalized_platform),
        "mail": _mail_status(normalized_platform, normalized_user),
        "calendar": _env_status(
            "calendar",
            "日程/日历",
            ["WECOM_CORP_ID", "WECOM_AGENT_ID", "WECOM_SECRET"],
            "确认企业微信应用凭据和日历/日程权限；如果租户未开放日历接口，会保持降级状态。",
        ),
        "approval": _env_status(
            "approval",
            "审批/流程",
            ["WECOM_CORP_ID", "WECOM_AGENT_ID", "WECOM_SECRET"],
            "确认企业微信应用已开通审批读取范围，审批数据会按当前用户权限返回。",
        ),
        "meeting": _env_status(
            "meeting",
            "会议/会议室",
            ["WECOM_CORP_ID", "WECOM_AGENT_ID", "WECOM_SECRET"],
            "确认企业微信会议室/日程权限；部分接口要求企业微信专业版或更高版本。",
        ),
        "documents": _document_status(),
    }
    return {
        "platform": normalized_platform,
        "user_id": normalized_user,
        "checked_at": int(time.time()),
        "overall_status": _overall_status(items),
        "items": items,
        "phase2_gate": _phase2_gate(items),
    }


def _knowledge_status() -> dict[str, Any]:
    total = _count("knowledge_items")
    return _item(
        name="知识库问答",
        status="ready" if total > 0 else "needs_config",
        summary=f"已索引知识条目 {total} 条。",
        metrics={"entries": total},
        next_action="继续通过知识库管理页上传和维护文档。" if total > 0 else "先导入公司说明书或上传部门知识文档。",
    )


def _task_status() -> dict[str, Any]:
    total = _count("tasks") + _count("task_drafts")
    return _item(
        name="任务闭环",
        status="ready",
        summary=f"任务表和草稿表可用，当前记录 {total} 条。",
        metrics={"records": total},
        next_action="可直接在 Bot 中创建、查询和更新任务状态。",
    )


def _contacts_status(platform: str) -> dict[str, Any]:
    total = _count("org_users", "platform=?", [platform])
    status = "ready" if total > 0 else "needs_config"
    return _item(
        name="通讯录搜索",
        status=status,
        summary=f"本地组织通讯录缓存 {total} 人；真实接口受企业 IM 通讯录权限限制。",
        metrics={"cached_users": total},
        next_action="定期同步通讯录；若真实接口返回 48009 等权限错误，继续使用本地组织缓存兜底。" if total > 0 else "先在管理员后台同步企业 IM 通讯录。",
    )


def _mail_status(platform: str, user_id: str) -> dict[str, Any]:
    from src.platform.mail_account_service import list_mail_accounts

    accounts = list_mail_accounts(platform=platform).get("accounts", [])
    configured = [item for item in accounts if item.get("enabled") and item.get("password_configured")]
    protocols: dict[str, int] = {}
    for item in accounts:
        proto = str(item.get("protocol") or "imap")
        protocols[proto] = protocols.get(proto, 0) + 1
    current_user_configured = bool(user_id and any(item.get("user_id") == user_id for item in configured))
    if user_id:
        status = "ready" if current_user_configured else "needs_config"
        summary = "当前用户邮箱已配置。" if current_user_configured else "当前用户邮箱尚未配置。"
    else:
        status = "ready" if configured else "needs_config"
        summary = f"已启用邮箱配置 {len(configured)} 个。"
    return _item(
        name="邮件摘要",
        status=status,
        summary=summary,
        metrics={"configured_accounts": len(configured), "all_accounts": len(accounts), "protocols": protocols},
        next_action="管理员后台 -> 邮箱配置中为员工配置 IMAP/POP3/Exchange 账号；Exchange EWS 需可访问服务器，Microsoft Graph 需后续 OAuth 应用授权。",
    )


def _document_status() -> dict[str, Any]:
    from src.tools.document_tool import OFFICECLI

    office_ready = os.path.isfile(OFFICECLI)
    doc_mcp = bool(os.environ.get("WECOM_ROBOT_DOC_MCP_URL"))
    todo_mcp = bool(os.environ.get("WECOM_ROBOT_TODO_MCP_URL"))
    status = "ready" if office_ready else "blocked"
    if office_ready and not (doc_mcp and todo_mcp):
        status = "degraded"
    return _item(
        name="文档/文件处理",
        status=status,
        summary=f"本地 Office 能力：{'可用' if office_ready else '不可用'}；企微文档 MCP：{'已配置' if doc_mcp else '未配置'}；企微待办 MCP：{'已配置' if todo_mcp else '未配置'}。",
        metrics={"officecli": office_ready, "wecom_doc_mcp": doc_mcp, "wecom_todo_mcp": todo_mcp},
        next_action="本地文档生成依赖 officecli；企微在线文档/待办能力需在后台配置机器人 MCP URL。",
    )


def _env_status(key: str, name: str, required_env: list[str], next_action: str) -> dict[str, Any]:
    present = [item for item in required_env if os.environ.get(item)]
    missing = [item for item in required_env if not os.environ.get(item)]
    status = "ready" if not missing else "needs_config"
    return _item(
        name=name,
        status=status,
        summary="核心凭据已加载。" if status == "ready" else f"缺少 {', '.join(missing)}。",
        metrics={"present_env": present, "missing_env": missing},
        next_action=next_action,
    )


def _item(*, name: str, status: str, summary: str, metrics: dict[str, Any], next_action: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "summary": summary,
        "metrics": metrics,
        "next_action": next_action,
    }


def _count(table: str, where: str = "", params: list[Any] | None = None) -> int:
    try:
        conn = Database.get().connect()
        sql = f"SELECT COUNT(*) AS n FROM {table}"
        if where:
            sql += f" WHERE {where}"
        row = conn.execute(sql, params or []).fetchone()
        return int(row["n"] if row else 0)
    except Exception:
        return 0


def _overall_status(items: dict[str, dict[str, Any]]) -> str:
    statuses = {str(item.get("status") or "") for item in items.values()}
    if "blocked" in statuses:
        return "blocked"
    if "needs_config" in statuses or "degraded" in statuses:
        return "degraded"
    return "ready"


def _phase2_gate(items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    blocking = [
        item["name"]
        for item in items.values()
        if item.get("status") in {"blocked", "needs_config"} and item["name"] in {"通讯录搜索", "邮件摘要", "审批/流程"}
    ]
    return {
        "ready_for_phase2": not blocking,
        "blocking_items": blocking,
        "recommendation": "阶段二可以推进主动通知和跨应用聚合。" if not blocking else "先补齐阻塞项，再扩大主动通知和跨应用联动。",
    }

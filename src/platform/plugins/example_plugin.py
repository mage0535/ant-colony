"""Example plugin — demonstrates the PlatformPlugin interface.

Copy this file and modify for your platform integration.

Usage:
    from src.platform.plugins import get_plugin
    plugin = get_plugin("example_app")
    result = plugin.search_user("zhangsan")
"""

from __future__ import annotations
from typing import Any

from src.platform.plugin_base import PlatformPlugin


class ExampleAppPlugin(PlatformPlugin):
    """Full-featured example for an imaginary 'ExampleApp' platform.

    Implements every method to show expected return shapes.
    In production, replace the fake returns with real API calls.
    """

    plugin_id = "example_app"  # type: ignore[misc]
    plugin_name = "示例应用 (ExampleApp)"  # type: ignore[misc]

    # ── lifecycle ──────────────────────────────────────────────────────

    def initialize(self, config: dict[str, Any]) -> bool:
        """Load API keys, set up HTTP session, verify connectivity."""
        self._api_key = config.get("api_key", "")
        self._base_url = config.get("base_url", "https://api.example.local")
        return bool(self._api_key)

    # ── user search ────────────────────────────────────────────────────

    def search_user(self, query: str) -> str | None:
        """Look up a user by name, email, or employee ID.

        Example return:
            '张三 (zhangsan) — 技术部 — zhangsan@example.com'
        """
        return f"示例用户匹配: {query}"

    # ── agenda / calendar ──────────────────────────────────────────────

    def get_agenda(self, days: int = 7) -> str | None:
        """Fetch upcoming events for the next N days.

        Example return:
            '📅 06-10 09:00 周会\n📅 06-11 14:00 项目评审'
        """
        return f"示例日程 (未来 {days} 天): 无待办事项"

    def create_event(self, summary: str, start_at: str, end_at: str) -> str | None:
        """Create a calendar event and return its ID.

        Example return:
            '已创建事件: evt_abc123 — 周会 (2025-06-10 09:00~10:00)'
        """
        return f"示例事件已创建: {summary} / {start_at} → {end_at}"

    # ── document / knowledge search ────────────────────────────────────

    def search_docs(self, query: str) -> str | None:
        """Full-text search across docs, wiki, or knowledge base.

        Example return (multi-line):
            '📄 项目章程 (匹配度 0.92)\n📄 需求文档 v2 (匹配度 0.78)'
        """
        return f"示例文档搜索: {query} → 无匹配结果"

    # ── approvals ──────────────────────────────────────────────────────

    def list_approvals(self, status: str = "pending") -> str | None:
        """List approval requests by status.

        Args:
            status: 'pending', 'approved', or 'rejected'.

        Example return:
            '待审批 (3): 请假-张三, 报销-李四, 用章-王五'
        """
        return f"示例审批列表 (status={status}): 无待审批项"

    # ── admin users ────────────────────────────────────────────────────

    def get_admin_users(self) -> str | None:
        """Return platform administrators for escalation / permissions.

        Example return:
            '管理员: admin@example.com, root@example.com'
        """
        return "示例管理员: admin@example.com"

    # ── generic app query (workbench extension) ────────────────────────

    def query_app(self, app_id: str, action: str, params: dict[str, Any]) -> str | None:
        """Route a query to a specific workbench app.

        Mapping convention:
            seal_approval   → 用章审批
            reimbursement   → 报销申请
            attendance      → 考勤打卡
            leave_request   → 请假申请

        Example usage in Agent tool:
            query_app("reimbursement", "list", {"page": 1, "limit": 5})
        """
        return f"示例应用查询: app={app_id}, action={action}, params={params}"

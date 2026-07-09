"""
Feishu (Lark) OpenAPI client — stdlib only, no external SDK.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class FeishuClient:
    """Feishu OpenAPI client with lazy tenant access token management.

    Reads FEISHU_APP_ID, FEISHU_APP_SECRET from environment variables.
    Domain defaults to ``cn`` (open.feishu.cn); set FEISHU_DOMAIN=intl
    to use the international endpoint (open.larksuite.com).
    """

    _BASE_URLS = {
        "cn": "https://open.feishu.cn",
        "intl": "https://open.larksuite.com",
    }

    def __init__(self) -> None:
        self._app_id = os.environ.get("FEISHU_APP_ID")
        self._app_secret = os.environ.get("FEISHU_APP_SECRET")
        domain = os.environ.get("FEISHU_DOMAIN", "cn")
        self._base = self._BASE_URLS.get(domain, self._BASE_URLS["cn"])
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _ensure_token(self) -> str | None:
        """Return a valid token or None if credentials are missing."""
        if not self._app_id or not self._app_secret:
            return None
        if self._token and time.time() < self._token_expires_at:
            return self._token
        self._token = self._fetch_token()
        return self._token

    def _fetch_token(self) -> str:
        url = f"{self._base}/open-apis/auth/v3/tenant_access_token/internal"
        body = json.dumps({
            "app_id": self._app_id,
            "app_secret": self._app_secret,
        }).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        with urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code", -1) != 0:
            raise RuntimeError(
                f"Feishu token fetch failed: {data.get('msg', 'unknown error')}"
            )
        expire = data.get("expire", 7200)
        self._token_expires_at = time.time() + expire - 100  # 100s safety margin
        return data["tenant_access_token"]

    # ------------------------------------------------------------------
    # Low-level request
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict | None = None,
    ) -> dict | None:
        """Make an authenticated request to the Feishu API.

        Returns ``None`` when credentials are not configured.
        Raises ``RuntimeError`` on HTTP or business-logic errors.
        """
        token = self._ensure_token()
        if token is None:
            return None

        url = self._base + path
        if query:
            url += "?" + urlencode(query)

        req = Request(url, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        if body is not None:
            req.add_header("Content-Type", "application/json; charset=utf-8")
            req.data = json.dumps(body, ensure_ascii=False).encode("utf-8")

        try:
            with urlopen(req) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Feishu HTTP {e.code} for {method} {path}: {text}"
            ) from e
        except URLError as e:
            raise RuntimeError(
                f"Feishu request failed for {method} {path}: {e.reason}"
            ) from e

        code = resp_data.get("code", -1)
        if code != 0:
            msg = resp_data.get("msg", "unknown error")
            raise RuntimeError(
                f"Feishu business error {code} for {method} {path}: {msg}"
            )

        return resp_data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_user(self, query: str) -> str | None:
        """Search users by name or email.

        Returns formatted lines: ``name | email | department``
        """
        data = self._request(
            "GET",
            "/open-apis/search/v1/user",
            query={"query": query},
        )
        if data is None:
            return None
        users = (data.get("data") or {}).get("users") or []
        if not users:
            return None
        lines: list[str] = []
        for u in users:
            name = u.get("name", "").strip()
            email = u.get("email", "").strip()
            dept = u.get("department_name", "").strip()
            lines.append(f"{name} | {email} | {dept}")
        return "\n".join(lines)

    def get_agenda(self, days: int = 7) -> str | None:
        """Fetch calendar events for the next *days* days.

        Returns formatted lines: ``YYYY-MM-DD HH:MM  summary``
        """
        now = datetime.now(timezone.utc)
        start_ts = int(now.timestamp())
        end_ts = int((now + timedelta(days=days)).timestamp())
        data = self._request(
            "GET",
            "/open-apis/calendar/v4/calendars/primary/events",
            query={
                "page_size": "50",
                "start_time": str(start_ts),
                "end_time": str(end_ts),
            },
        )
        if data is None:
            return None
        items = (data.get("data") or {}).get("items") or []
        if not items:
            return None
        lines: list[str] = []
        for ev in items:
            summary = ev.get("summary", "(无标题)")
            start = ev.get("start", {})
            ts_str = start.get("timestamp", "")
            if ts_str:
                dt = datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
                dt_str = dt.strftime("%Y-%m-%d %H:%M")
            else:
                dt_str = start.get("date", "")
            lines.append(f"{dt_str} {summary}")
        return "\n".join(lines)

    def search_docs(self, query: str) -> str | None:
        """Search files in Drive by keyword.

        Returns formatted lines: ``[title](url)``
        """
        data = self._request(
            "GET",
            "/open-apis/drive/v1/files",
            query={"search_keyword": query, "page_size": "10"},
        )
        if data is None:
            return None
        files = (data.get("data") or {}).get("files") or []
        if not files:
            return None
        lines: list[str] = []
        for f in files:
            title = f.get("name", "(无标题)")
            file_token = f.get("file_token", "")
            file_type = f.get("type", "doc")
            url = self._build_doc_url(file_token, file_type)
            lines.append(f"[{title}]({url})")
        return "\n".join(lines)

    def read_docs_document(self, query: str) -> str | None:
        return self.search_docs(query)

    def list_approvals(self, status: str = "pending", *, query: str = "", capability_context=None) -> str | None:
        """List approval instances by status.

        Returns formatted lines: ``title | applicant | start_time``
        """
        data = self._request(
            "POST",
            "/open-apis/approval/v4/instances",
            query={"page_size": "10"},
            body={"status": status},
        )
        if data is None:
            return None
        instances = (data.get("data") or {}).get("instances") or []
        if not instances:
            return None
        lines: list[str] = []
        user_id = str(getattr(capability_context, "user_id", "") or "")
        for inst in instances:
            applicant_info = inst.get("applicant", {}) or {}
            applicant_id = str(
                applicant_info.get("user_id")
                or applicant_info.get("open_id")
                or inst.get("user_id")
                or ""
            )
            if user_id and applicant_id and applicant_id != user_id:
                continue
            title = inst.get("name", "(无标题)")
            applicant = applicant_info.get("name", "")
            if query and not _fuzzy_contains(title, query):
                continue
            start_time = inst.get("start_time", "")
            lines.append(f"{title} | {applicant} | {start_time}")
        return "\n".join(lines)

    def get_approval_detail(self, query: str) -> str | None:
        return self.list_approvals(query or "pending")

    def get_event_detail(self, query: str) -> str | None:
        return self.get_agenda(days=30)

    def query_meeting_room(self, query: str, days: int = 1, capability_context=None) -> str | None:
        del capability_context
        agenda = self.get_agenda(days=days)
        if not agenda:
            return None
        lines = [line for line in agenda.splitlines() if "会议室" in line or "会议" in line or query in line]
        return "\n".join(lines[:20]) if lines else None

    def query_enterprise_apps(self, query: str, action: str = "query", capability_context=None) -> str | None:
        del capability_context
        sections: list[str] = []
        if any(word in query for word in ("会议室", "会议", "日程")):
            agenda = self.get_agenda(days=7)
            if agenda:
                sections.append("【日程/会议】\n" + agenda)
        if "审批" in query or "流程" in query or "申请" in query:
            approvals = self.list_approvals("pending")
            if approvals:
                sections.append("【审批/流程】\n" + approvals)
        if "文档" in query or "资料" in query:
            docs = self.search_docs(query)
            if docs:
                sections.append("【云文档】\n" + docs)
        return "\n\n".join(sections) if sections else None

    def list_accessible_applications(self, query: str = "", capability_context=None) -> str | None:
        del capability_context
        data = self._request("GET", "/open-apis/bot/v3/info")
        if not data:
            return None
        bot = data.get("bot") or data.get("data") or {}
        name = str(bot.get("app_name") or bot.get("name") or "")
        if not name:
            return None
        if query and not _fuzzy_contains(name, query):
            return None
        return f"{name}：当前已接入的飞书机器人应用"

    def run_enterprise_app_action(self, action: str, payload: dict | None = None) -> str | None:
        payload = payload or {}
        if action == "calendar.create":
            return self.create_event(str(payload.get("summary", "日程")), str(payload.get("start_at", "")), str(payload.get("end_at", "")))
        return f"飞书暂未开放该动作的自动执行器：{action}"

    def create_event(self, summary: str, start_at: str, end_at: str) -> str | None:
        """Create a calendar event.

        *start_at* and *end_at* are Unix timestamps (seconds) as strings.
        """
        body = {
            "summary": summary,
            "start": {
                "timestamp": start_at,
                "timezone": "Asia/Shanghai",
            },
            "end": {
                "timestamp": end_at,
                "timezone": "Asia/Shanghai",
            },
        }
        data = self._request(
            "POST",
            "/open-apis/calendar/v4/calendars/primary/events",
            body=body,
        )
        if data is None:
            return None
        event = data.get("data") or {}
        event_id = event.get("event_id", "")
        return f"事件已创建: {event.get('summary', summary)} (ID: {event_id})"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_doc_url(file_token: str, file_type: str) -> str:
        """Build a human-friendly Feishu document URL from its token."""
        path_map = {
            "doc": "docs",
            "sheet": "sheets",
            "bitable": "base",
            "slide": "slides",
            "mindnote": "mindnote",
            "file": "drive",
            "wiki": "wiki",
            "docs": "docs",
        }
        segment = path_map.get(file_type, "docs")
        return f"https://open.feishu.cn/{segment}/{file_token}"

    def get_admin_users(self) -> str | None:
        resp = self._request("GET", "/open-apis/contact/v3/users", query={"page_size": "50"})
        if not resp:
            return None
        admins = []
        for u in resp.get("data", {}).get("items", []):
            name = u.get("name", "") or u.get("name", {}).get("zh_cn", "")
            if u.get("is_tenant_manager"):
                admins.append(f"{name} (租户管理员)")
            if u.get("is_leader"):
                admins.append(f"{name} (部门负责人)")
        return "\n".join(admins[:20]) if admins else None


def _fuzzy_contains(title: str, query: str) -> bool:
    from src.platform.enterprise_query import plan_enterprise_query

    terms = plan_enterprise_query(query).query_terms
    if not terms:
        return True
    normalized_title = str(title or "").replace("申请", "审批").replace("流程", "")
    return any(
        str(term).replace("申请", "审批").replace("流程", "") in normalized_title
        for term in terms
    )

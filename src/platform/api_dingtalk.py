"""
DingTalk OpenAPI client — stdlib only, no external SDK.
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class DingTalkClient:
    """DingTalk OpenAPI client with lazy access token management.

    Reads ``DINGTALK_CLIENT_ID`` and ``DINGTALK_CLIENT_SECRET`` from the
    environment (equivalent to AppKey / AppSecret in the DingTalk console).
    """

    _BASE = "https://oapi.dingtalk.com"

    def __init__(self) -> None:
        self._client_id = os.environ.get("DINGTALK_CLIENT_ID")
        self._client_secret = os.environ.get("DINGTALK_CLIENT_SECRET")
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _ensure_token(self) -> str | None:
        """Return a valid token or ``None`` when credentials are missing."""
        if not self._client_id or not self._client_secret:
            return None
        if self._token and time.time() < self._token_expires_at:
            return self._token
        self._token = self._fetch_token()
        return self._token

    def _fetch_token(self) -> str:
        query = urlencode({
            "appkey": self._client_id,
            "appsecret": self._client_secret,
        })
        url = f"{self._BASE}/gettoken?{query}"
        req = Request(url, method="GET")
        try:
            with urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"DingTalk HTTP {e.code} fetching token: {text}"
            ) from e
        except URLError as e:
            raise RuntimeError(
                f"DingTalk token request failed: {e.reason}"
            ) from e

        errcode = data.get("errcode", -1)
        if errcode != 0:
            raise RuntimeError(
                f"DingTalk token fetch failed (errcode={errcode}): "
                f"{data.get('errmsg', 'unknown error')}"
            )
        expires_in = data.get("expires_in", 7200)
        self._token_expires_at = time.time() + expires_in - 100
        return data["access_token"]

    # ------------------------------------------------------------------
    # Low-level request
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
    ) -> dict | None:
        """Make an authenticated request to the DingTalk API.

        Returns ``None`` when credentials are not configured.
        Raises ``RuntimeError`` on HTTP or business-logic errors.
        """
        token = self._ensure_token()
        if token is None:
            return None

        qs = urlencode({"access_token": token})
        url = f"{self._BASE}{path}?{qs}"
        req = Request(url, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json; charset=utf-8")
            req.data = json.dumps(body, ensure_ascii=False).encode("utf-8")

        try:
            with urlopen(req) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"DingTalk HTTP {e.code} for {method} {path}: {text}"
            ) from e
        except URLError as e:
            raise RuntimeError(
                f"DingTalk request failed for {method} {path}: {e.reason}"
            ) from e

        errcode = resp_data.get("errcode", -1)
        if errcode != 0:
            msg = resp_data.get("errmsg", "unknown error")
            raise RuntimeError(
                f"DingTalk business error {errcode} for {method} {path}: {msg}"
            )

        return resp_data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_user(self, query: str) -> str | None:
        """Search users by mobile or name.

        1. If *query* looks like a phone number, try
           ``/topapi/v2/user/getbymobile``.
        2. Otherwise fall back to listing department-1 members and
           matching by name substring.

        Returns formatted lines: ``name | userid | dept``
        """
        if self._ensure_token() is None:
            return None

        # --- Try mobile lookup first ---
        if re.fullmatch(r"1\d{10}", query):
            result = self._request(
                "POST",
                "/topapi/v2/user/getbymobile",
                body={"mobile": query},
            )
            if result is not None:
                user = result.get("result") or {}
                name = (user.get("name") or "").strip()
                userid = (user.get("userid") or "").strip()
                if name:
                    return f"{name} | {userid} | (mobile match)"

        # --- Fallback: list dept members and match name ---
        return self._search_user_by_name(query)

    def _search_user_by_name(self, name_query: str) -> str | None:
        """List department-1 members and filter by name substring."""
        result = self._request(
            "POST",
            "/topapi/v2/user/list",
            body={"dept_id": 1, "cursor": 0, "size": 100},
        )
        if result is None:
            return None

        result_data = result.get("result") or {}
        user_list = result_data.get("list") or []

        lines: list[str] = []
        q = name_query.lower()
        for u in user_list:
            name = (u.get("name") or "").strip()
            if q not in name.lower():
                continue
            userid = (u.get("userid") or "").strip()
            dept = (u.get("dept") or u.get("dept_id_list") or [])
            if isinstance(dept, list):
                dept_str = ",".join(str(d) for d in dept)
            else:
                dept_str = str(dept)
            lines.append(f"{name} | {userid} | {dept_str}")

        return "\n".join(lines) if lines else None

    def get_agenda(self, days: int = 7) -> str | None:
        """Fetch calendar events for the next *days* days.

        Returns formatted lines: ``YYYY-MM-DD HH:MM  summary``
        """
        now = datetime.now(timezone.utc)
        start_ts = int(now.timestamp() * 1000)  # DingTalk uses ms
        end_ts = int((now + timedelta(days=days)).timestamp() * 1000)

        result = self._request(
            "POST",
            "/topapi/calendar/v2/event/list",
            body={
                "calendar_id": "primary",
                "time_range": {
                    "start_time": start_ts,
                    "end_time": end_ts,
                },
                "max_results": 50,
            },
        )
        if result is None:
            return None

        items = (result.get("result") or {}).get("items") or []
        if not items:
            return None

        lines: list[str] = []
        for ev in items:
            summary = ev.get("summary", "(无标题)")
            start_ms = (ev.get("start") or {}).get("start_time", 0)
            if start_ms:
                dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
                dt_str = dt.strftime("%Y-%m-%d %H:%M")
            else:
                dt_str = ""
            lines.append(f"{dt_str}  {summary}")

        return "\n".join(lines) if lines else None

    def search_docs(self, query: str) -> str | None:
        """Search DingTalk documents / space by keyword.

        Returns formatted lines: ``title | space_id | doc_id``

        Note: The DingTalk doc search API requires specific application
        permissions (``qyapi_manage_doc``). If the call fails with a
        permission error, the message is propagated.
        """
        result = self._request(
            "POST",
            "/topapi/doc/content/search",
            body={"search_word": query, "offset": 0, "size": 10},
        )
        if result is None:
            return None

        items = (result.get("result") or {}).get("items") or []
        if not items:
            return None

        lines: list[str] = []
        for item in items:
            title = (item.get("title") or "").strip()
            space_id = (item.get("space_id") or "").strip()
            doc_id = (item.get("doc_id") or "").strip()
            lines.append(f"{title} | {space_id} | {doc_id}")

        return "\n".join(lines) if lines else None

    def read_docs_document(self, query: str) -> str | None:
        return self.search_docs(query)

    def list_approvals(self, status: str = "pending") -> str | None:
        """List approval process instances by status.

        Supported status values (DingTalk): ``NEW``, ``RUNNING``,
        ``COMPLETED``, ``TERMINATED``, ``CANCELED``.

        Returns formatted lines: ``title | applicant | created``

        Requires ``qyapi_manage_process`` permission.
        """
        # Map common shorthand to DingTalk values
        status_map = {
            "pending": "NEW",
            "running": "RUNNING",
            "completed": "COMPLETED",
            "terminated": "TERMINATED",
            "canceled": "CANCELED",
        }
        dt_status = status_map.get(status.lower(), status)

        result = self._request(
            "POST",
            "/topapi/processinstance/listids",
            body={"process_code": "ALL", "status": dt_status, "size": 10},
        )
        if result is None:
            return None

        instance_ids = (result.get("result") or {}).get("list") or []
        if not instance_ids:
            return None

        lines: list[str] = []
        for inst_id in instance_ids[:10]:
            detail = self._request(
                "POST",
                "/topapi/processinstance/get",
                body={"process_instance_id": inst_id},
            )
            if detail is None:
                continue
            proc = detail.get("process_instance") or {}
            title = (proc.get("title") or "").strip()
            applicant = (proc.get("originator_name") or (proc.get("originator_userid") or ""))
            created = proc.get("create_time", "")
            lines.append(f"{title} | {applicant} | {created}")

        return "\n".join(lines) if lines else None

    def get_approval_detail(self, query: str) -> str | None:
        return self.list_approvals(query or "pending")

    def create_event(self, summary: str, start_at: str, end_at: str) -> str | None:
        """Create a calendar event.

        *start_at* and *end_at* are Unix timestamps **in seconds** (as
        strings). They are converted to milliseconds internally for the
        DingTalk API.
        """
        body = {
            "calendar_id": "primary",
            "summary": summary,
            "start": {
                "start_time": int(start_at) * 1000,
                "timezone": "Asia/Shanghai",
            },
            "end": {
                "start_time": int(end_at) * 1000,
                "timezone": "Asia/Shanghai",
            },
        }
        result = self._request(
            "POST",
            "/topapi/calendar/v2/event/create",
            body=body,
        )
        if result is None:
            return None

        event = result.get("result") or {}
        event_id = event.get("event_id", "")
        return f"事件已创建: {summary} (ID: {event_id})"

    def get_event_detail(self, query: str) -> str | None:
        return self.get_agenda(days=30)

    def get_meeting_detail(self, query: str) -> str | None:
        return None

    def get_admin_users(self) -> str | None:
        result = self._request("POST", "/topapi/org/admin/list", body={})
        if result is None:
            return None
        admin_list = result.get("result", {}).get("admin_list", [])
        admins = []
        for a in admin_list:
            userid = a.get("userid", "")
            sys_level = a.get("sys_level", 0)
            role = "主管理员" if sys_level == 1 else "子管理员"
            # Try to get user name
            try:
                user_info = self._request("POST", "/topapi/v2/user/get", body={"userid": userid})
                name = user_info.get("result", {}).get("name", userid) if user_info else userid
            except Exception:
                name = userid
            admins.append(f"{name} ({role})")
        return "\n".join(admins[:20]) if admins else None

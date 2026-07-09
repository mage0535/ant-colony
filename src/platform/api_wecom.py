from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
from datetime import datetime
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"
_corp_id: str = ""
_agent_id: int = 0
_app_secret: str = ""
_token_cache: tuple[str, float] = ("", 0)


def _init_creds():
    global _corp_id, _agent_id, _app_secret
    _corp_id = os.environ.get("WECOM_CORP_ID", "")
    _agent_id = int(os.environ.get("WECOM_AGENT_ID", "1000006"))
    _app_secret = os.environ.get("WECOM_SECRET", "")


def _get_token() -> str:
    global _token_cache
    if not _corp_id:
        _init_creds()
    token, expires = _token_cache
    if token and time.time() < expires - 60:
        return token
    url = f"{WECOM_API}/gettoken?corpid={_corp_id}&corpsecret={_app_secret}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"WeCom token error: {data.get('errmsg')}")
    _token_cache = (data["access_token"], time.time() + data.get("expires_in", 7200))
    return _token_cache[0]


def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    token = _get_token()
    url = f"{WECOM_API}/{path}?access_token={token}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    if result.get("errcode", 0) != 0:
        raise RuntimeError(f"WeCom API error ({path}): {result.get('errmsg')}")
    return result


def _post_optional(path: str, body: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return _post(path, body)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.info("WeCom endpoint unavailable: %s", path)
            return None
        raise
    except RuntimeError as exc:
        logger.info("WeCom endpoint failed: %s: %s", path, exc)
        return None


def _post_optional_diagnostic(path: str, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    try:
        return _post(path, body), ""
    except urllib.error.HTTPError as exc:
        logger.info("WeCom endpoint unavailable: %s: HTTP %s", path, exc.code)
        return None, f"HTTP {exc.code}"
    except RuntimeError as exc:
        logger.info("WeCom endpoint failed: %s: %s", path, exc)
        return None, str(exc)


def _get(path: str, params: str = "") -> dict[str, Any]:
    token = _get_token()
    url = f"{WECOM_API}/{path}?access_token={token}&{params}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as resp:
        result = json.loads(resp.read())
    if result.get("errcode", 0) != 0:
        raise RuntimeError(f"WeCom API error ({path}): {result.get('errmsg')}")
    return result


class WeComClient:

    def search_user(self, query: str) -> str | None:
        try:
            # Get all departments first
            dept_resp = _get("department/list")
            dept_ids = [d["id"] for d in dept_resp.get("department", [])]
            results = []
            for dept_id in dept_ids[:5]:  # search top 5 depts
                resp = _get("user/list", f"department_id={dept_id}&fetch_child=1")
                for user in resp.get("userlist", []):
                    name = user.get("name", "")
                    alias = user.get("alias", "")
                    mobile = user.get("mobile", "")
                    email = user.get("email", "")
                    dept_name = user.get("department", [""])[0] if user.get("department") else ""
                    if query.lower() in name.lower() or query.lower() in alias.lower() or query == mobile:
                        results.append(f"{name} | {mobile} | {email} | {dept_name}")
            return "\n".join(results[:10]) if results else None
        except Exception as e:
            logger.warning("WeCom search_user failed: %s", e)
            raise

    def get_agenda(self, days: int = 7) -> str | None:
        try:
            now = int(time.time())
            end = int(time.time() + days * 86400)
            resp = _post("oa/calendar/getbycalendar", {
                "cal_id": "",
                "start_time": now,
                "end_time": end,
            })
            events = []
            cal_list = resp.get("calendar_list", [])
            for cal in cal_list:
                for ev in cal.get("schedule_items", []):
                    summary = ev.get("summary", "(无标题)")
                    start_ts = ev.get("start_time", {}).get("time", 0)
                    end_ts = ev.get("end_time", {}).get("time", 0)
                    start_str = datetime.fromtimestamp(start_ts).strftime("%m-%d %H:%M") if start_ts else ""
                    end_str = datetime.fromtimestamp(end_ts).strftime("%H:%M") if end_ts else ""
                    events.append(f"{start_str}-{end_str} {summary}")
            return "\n".join(events[:20]) if events else None
        except Exception as e:
            logger.warning("WeCom get_agenda failed: %s", e)
            raise

    def query_meeting_room(self, query: str, days: int = 1) -> str | None:
        room_name = _extract_room_name(query)
        start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        end = int((datetime.now() + timedelta(days=max(1, days))).timestamp())
        sections: list[str] = []
        errors: list[str] = []
        for path, body in (
            ("oa/meetingroom/get_booking_info", {"start_time": start, "end_time": end, "city": "", "building": "", "floor": ""}),
            ("oa/meetingroom/bookinfo/get", {"start_time": start, "end_time": end, "room_name": room_name}),
            ("meeting/get_user_meetinglist", {"begin_time": start, "end_time": end, "limit": 50}),
        ):
            resp, error = _post_optional_diagnostic(path, body)
            if not resp:
                if error:
                    errors.append(error)
                continue
            text = _format_room_payload(resp, room_name)
            if text:
                sections.append(text)
        if sections:
            return "\n".join(dict.fromkeys(sections))
        try:
            meeting_text = self.list_meetings()
        except Exception as exc:
            logger.info("WeCom meeting fallback failed: %s", exc)
            meeting_text = None
            errors.append(str(exc))
        try:
            agenda_text = self.get_agenda(days=days)
        except Exception as exc:
            logger.info("WeCom agenda fallback failed: %s", exc)
            agenda_text = None
            errors.append(str(exc))
        candidates = _filter_lines_by_keyword("\n".join(x for x in [meeting_text, agenda_text] if x), room_name)
        if candidates:
            return f"{room_name or '会议室'}相关占用信息：\n{candidates}"
        if errors:
            if any("48002" in error or "forbidden" in error.lower() for error in errors):
                return (
                    f"暂时无法读取{room_name or '该会议室'}的真实占用数据："
                    "当前企业微信应用缺少会议室或会议数据接口权限（错误码 48002）。"
                    "请由企业管理员为承载 AI 助手的自建应用补充会议室、会议和日程只读权限后重试。"
                )
            return (
                f"暂时无法读取{room_name or '该会议室'}的真实占用数据："
                "当前租户未开放可用的会议室查询接口。系统没有使用模拟数据代替真实结果。"
            )
        return f"没有查到{room_name or '该会议室'}在当前查询时段的真实占用记录。"

    def create_event(self, summary: str, start_at: str, end_at: str) -> str | None:
        try:
            start_dt = datetime.strptime(start_at, "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(end_at, "%Y-%m-%d %H:%M")
            resp = _post("oa/calendar/add", {
                "calendar": {
                    "summary": summary,
                    "color": "44B549",
                    "perm_type": "user",
                },
                "schedule": {
                    "summary": summary,
                    "start_time": {"time": int(start_dt.timestamp())},
                    "end_time": {"time": int(end_dt.timestamp())},
                },
            })
            cal_id = resp.get("cal_id", "")
            return f"日程已创建 (ID: {cal_id})" if cal_id else "日程创建成功"
        except Exception as e:
            logger.warning("WeCom create_event failed: %s", e)
            raise

    def search_docs(self, query: str) -> str | None:
        try:
            resp = _post("doc/search", {"query": query, "offset": 0, "limit": 10})
            results = []
            for doc in resp.get("item_list", []):
                title = doc.get("title", "(无标题)")
                url = doc.get("url", "")
                creator = doc.get("creator_name", "")
                item = f"{title} | 创建者: {creator}"
                if url:
                    item += f" | {url}"
                results.append(item)
            return "\n".join(results) if results else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.warning("WeCom search_docs endpoint unavailable (HTTP 404)")
                return None
            logger.warning("WeCom search_docs failed: %s", e)
            raise
        except Exception as e:
            logger.warning("WeCom search_docs failed: %s", e)
            raise

    def create_doc(self, title: str, content: str = "") -> str | None:
        try:
            resp = _post("doc/create", {
                "title": title,
                "content": content,
            })
            doc_id = resp.get("docid", "")
            url = resp.get("url", "")
            return f"文档已创建: {title} (docid: {doc_id})\n{url}"
        except Exception as e:
            logger.warning("WeCom create_doc failed: %s", e)
            raise

    def read_docs_document(self, query: str) -> str | None:
        return self.search_docs(query)

    def list_meetings(self) -> str | None:
        try:
            now = int(time.time())
            resp = _post("meeting/get_user_meetinglist", {
                "begin_time": now - 30 * 86400,
                "end_time": now + 30 * 86400,
                "limit": 10,
            })
            meetings = []
            for m in resp.get("meeting_list", []):
                title = m.get("title", "(无标题)")
                start_ts = m.get("start_time", 0)
                start_str = datetime.fromtimestamp(start_ts).strftime("%m-%d %H:%M") if start_ts else ""
                status = m.get("status", 0)
                status_str = {0: "未开始", 1: "进行中", 2: "已结束"}.get(status, "未知")
                meetings.append(f"{start_str} {title} [{status_str}]")
            return "\n".join(meetings[:10]) if meetings else None
        except Exception as e:
            logger.warning("WeCom list_meetings failed: %s", e)
            raise

    def get_meeting_detail(self, query: str) -> str | None:
        return self.list_meetings()

    def get_event_detail(self, query: str) -> str | None:
        return self.get_agenda(days=30)

    def get_approval_detail(self, query: str) -> str | None:
        return self.list_approvals(query or "pending")

    def list_approvals(self, status: str = "pending") -> str | None:
        now = int(time.time())
        start = now - 30 * 86400
        end = now + 7 * 86400
        sections: list[str] = []
        template_resp = _post_optional("oa/gettemplatedetail", {})
        if template_resp:
            text = _format_approval_payload(template_resp)
            if text:
                sections.append(text)
        for path, body in (
            ("oa/getapprovalinfo", {"starttime": start, "endtime": end, "cursor": 0, "size": 20}),
            ("oa/applyevent/get_approval_info", {"starttime": start, "endtime": end, "cursor": 0, "size": 20}),
        ):
            resp = _post_optional(path, body)
            if not resp:
                continue
            text = _format_approval_payload(resp)
            if text:
                sections.append(text)
        return "\n".join(dict.fromkeys(sections)) if sections else None

    def create_meeting(self, title: str, start_at: str, end_at: str, attendees: list[str] | None = None) -> str | None:
        try:
            start_dt = datetime.strptime(start_at, "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(end_at, "%Y-%m-%d %H:%M")
            body = {
                "title": title,
                "start_time": int(start_dt.timestamp()),
                "end_time": int(end_dt.timestamp()),
                "attendees": [{"userid": uid} for uid in (attendees or [])],
            }
            resp = _post("meeting/create", body)
            meeting_id = resp.get("meetingid", "")
            return f"会议已创建: {title} (meetingid: {meeting_id})" if meeting_id else "会议创建成功"
        except Exception as e:
            logger.warning("WeCom create_meeting failed: %s", e)
            raise

    def query_enterprise_apps(self, query: str, action: str = "query") -> str | None:
        sections: list[str] = []
        if any(word in query for word in ("会议室", "会议", "房间", "占用", "申请")):
            room = _optional_client_call(self.query_meeting_room, query)
            if room:
                sections.append("【会议室/会议】\n" + room)
        if "审批" in query or "申请" in query or "流程" in query:
            approvals = _optional_client_call(self.list_approvals, "pending")
            if approvals:
                sections.append("【审批/流程】\n" + approvals)
        if "日程" in query or "安排" in query or "会议" in query:
            agenda = _optional_client_call(self.get_agenda, days=7)
            if agenda:
                sections.append("【日程】\n" + agenda)
        if not sections:
            docs = _optional_client_call(self.search_docs, query)
            if docs:
                sections.append("【在线文档】\n" + docs)
        return "\n\n".join(sections) if sections else None

    def run_enterprise_app_action(self, action: str, payload: dict[str, Any] | None = None) -> str | None:
        payload = payload or {}
        if action == "meeting.create":
            return self.create_meeting(
                str(payload.get("title", "会议")),
                str(payload.get("start_at", "")),
                str(payload.get("end_at", "")),
                list(payload.get("attendees", []) or []),
            )
        if action == "calendar.create":
            return self.create_event(str(payload.get("summary", "日程")), str(payload.get("start_at", "")), str(payload.get("end_at", "")))
        return f"企业微信暂未开放该动作的自动执行器：{action}"

    def get_admin_users(self) -> str | None:
        """Return formatted platform admin list — ONLY DB-registered admins."""
        try:
            from src.platform.admin_registry import list_admins
            entries = list_admins("wecom")
            if entries:
                admins = []
                for e in entries:
                    name = e.get("name", e["user_id"])
                    admins.append(f"{name} (企业管理员)")
                return "\n".join(admins) if admins else None
        except Exception:
            pass
        return None

    def get_department_leaders(self) -> str | None:
        """Return formatted department leader list — from WeCom is_leader_in_dept."""
        try:
            dept_resp = _get("department/list")
            dept_ids = [d["id"] for d in dept_resp.get("department", [])]
            leaders = []
            seen = set()
            for dept_id in dept_ids[:10]:
                resp = _get("user/list", f"department_id={dept_id}&fetch_child=1")
                for u in resp.get("userlist", []):
                    name = u.get("name", "")
                    userid = u.get("userid", "")
                    is_leader = u.get("is_leader_in_dept", [0])
                    if is_leader and any(is_leader):
                        if userid not in seen:
                            seen.add(userid)
                            dept_ids_for_user = u.get("department", [])
                            dept_names = []
                            for did in dept_ids_for_user:
                                for d2 in dept_resp.get("department", []):
                                    if d2["id"] == did:
                                        dept_names.append(d2.get("name", str(did)))
                                        break
                            dept_str = "/".join(dept_names[:3])
                            leaders.append(f"{name} (部门负责人: {dept_str})")
            return "\n".join(leaders[:30]) if leaders else None
        except Exception as e:
            logger.warning("WeCom get_department_leaders failed: %s", e)
            return None

    def get_admin_userids(self) -> set[str]:
        """Return admin WeCom user IDs — only DB-registered + API (no dept leader fallback)."""
        ids: set[str] = set()
        try:
            from src.platform.admin_registry import get_admin_ids
            ids.update(get_admin_ids("wecom"))
        except Exception:
            pass
        return ids

    def get_department_leader_ids(self) -> set[str]:
        """Return department leader user IDs from WeCom."""
        ids: set[str] = set()
        try:
            dept_resp = _get("department/list")
            for d in dept_resp.get("department", []):
                resp2 = _get("user/list", f"department_id={d['id']}&fetch_child=1")
                for u in resp2.get("userlist", []):
                    is_leader = u.get("is_leader_in_dept", [0])
                    if is_leader and any(is_leader):
                        uid = u.get("userid", "")
                        if uid:
                            ids.add(uid)
        except Exception:
            pass
        return ids


def _extract_room_name(query: str) -> str:
    import re

    match = re.search(r"([\u4e00-\u9fffA-Za-z0-9一二三四五六七八九十]+号?会议室)", query)
    if match:
        return match.group(1)
    return "会议室" if "会议室" in query else query.strip()


def _format_room_payload(payload: dict[str, Any], room_name: str) -> str:
    lines: list[str] = []
    raw_items: list[Any] = []
    for key in ("booking_list", "bookings", "meeting_room_list", "room_list", "meeting_list", "schedule_items"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_items.extend(value)
    for value in payload.values():
        if isinstance(value, dict):
            for nested_key in ("booking_list", "meeting_room_list", "room_list", "meeting_list", "schedule_items"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    raw_items.extend(nested)
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("summary") or item.get("name") or item.get("room_name") or item.get("meeting_room_name") or "")
        location = str(item.get("location") or item.get("room_name") or item.get("meeting_room_name") or "")
        if room_name and room_name != "会议室" and room_name not in title and room_name not in location:
            continue
        start_ts = int(item.get("start_time") or item.get("begin_time") or 0)
        end_ts = int(item.get("end_time") or 0)
        start = datetime.fromtimestamp(start_ts).strftime("%m-%d %H:%M") if start_ts else ""
        end = datetime.fromtimestamp(end_ts).strftime("%H:%M") if end_ts else ""
        prefix = location or room_name
        label = title or "会议室占用"
        if prefix and prefix not in label:
            label = f"{prefix} {label}"
        lines.append(f"{start}-{end} {label}".strip())
    return "\n".join(lines[:20])


def _format_approval_payload(payload: dict[str, Any]) -> str:
    items: list[Any] = []
    for key in ("sp_no_list", "approval_list", "template_names", "apply_list"):
        value = payload.get(key)
        if isinstance(value, list):
            items.extend(value)
    for value in payload.values():
        if isinstance(value, dict):
            for nested_key in ("sp_no_list", "approval_list", "template_names", "apply_list"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    items.extend(nested)
    lines: list[str] = []
    for item in items[:20]:
        if isinstance(item, dict):
            title = item.get("template_name") or item.get("title") or item.get("name") or item.get("sp_no") or json.dumps(item, ensure_ascii=False)
            status = item.get("status") or item.get("apply_status") or ""
            lines.append(f"{title} {status}".strip())
        else:
            lines.append(str(item))
    return "\n".join(lines)


def _filter_lines_by_keyword(text: str, keyword: str) -> str:
    if not text.strip():
        return ""
    if not keyword or keyword == "会议室":
        return text
    lines = [line for line in text.splitlines() if keyword in line or "会议室" in line]
    return "\n".join(lines[:20])


def _optional_client_call(method, *args: Any, **kwargs: Any) -> Any | None:
    try:
        return method(*args, **kwargs)
    except Exception as exc:
        logger.info("Optional WeCom application capability failed: %s", exc)
        return None

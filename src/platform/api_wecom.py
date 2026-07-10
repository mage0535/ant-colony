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

from src.platform.capability_audit import CapabilityInvocationContext
from src.platform.enterprise_query import EnterpriseQueryPlan, plan_enterprise_query

logger = logging.getLogger(__name__)

WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"
_corp_id: str = ""
_agent_id: int = 0
_app_secret: str = ""
_token_cache: dict[str, tuple[str, float]] = {}


def _init_creds():
    global _corp_id, _agent_id, _app_secret
    _corp_id = os.environ.get("WECOM_CORP_ID", "")
    _agent_id = int(os.environ.get("WECOM_AGENT_ID", "1000006"))
    _app_secret = os.environ.get("WECOM_SECRET", "")


def _resolve_domain_secret(domain: str) -> str:
    domain_variables = {
        "approval": ("WECOM_APPROVAL_SECRET",),
        "meeting": ("WECOM_MEETING_SECRET", "WECOM_CALENDAR_SECRET"),
        "calendar": ("WECOM_CALENDAR_SECRET", "WECOM_MEETING_SECRET"),
        "docs": ("WECOM_DOCS_SECRET",),
        "contacts": ("WECOM_CONTACT_SECRET",),
        "apps": ("WECOM_APPLICATION_SECRET",),
    }
    for variable in domain_variables.get(str(domain or "").lower(), ()):
        value = os.environ.get(variable, "").strip()
        if value:
            return value
    return os.environ.get("WECOM_SECRET", "").strip() or _app_secret


def _get_token(secret: str | None = None) -> str:
    if not _corp_id:
        _init_creds()
    resolved_secret = secret or _app_secret
    token, expires = _token_cache.get(resolved_secret, ("", 0))
    if token and time.time() < expires - 60:
        return token
    url = f"{WECOM_API}/gettoken?corpid={_corp_id}&corpsecret={resolved_secret}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"WeCom token error: {data.get('errmsg')}")
    _token_cache[resolved_secret] = (data["access_token"], time.time() + data.get("expires_in", 7200))
    return _token_cache[resolved_secret][0]


def _post(path: str, body: dict[str, Any], *, secret: str | None = None) -> dict[str, Any]:
    token = _get_token(secret)
    url = f"{WECOM_API}/{path}?access_token={token}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    if result.get("errcode", 0) != 0:
        raise RuntimeError(f"WeCom API error ({path}): {result.get('errmsg')}")
    return result


def _post_optional(path: str, body: dict[str, Any], *, secret: str | None = None) -> dict[str, Any] | None:
    try:
        return _post(path, body, secret=secret)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.info("WeCom endpoint unavailable: %s", path)
            return None
        raise
    except RuntimeError as exc:
        logger.info("WeCom endpoint failed: %s: %s", path, exc)
        return None


def _post_optional_diagnostic(
    path: str,
    body: dict[str, Any],
    *,
    secret: str | None = None,
) -> tuple[dict[str, Any] | None, str]:
    try:
        return _post(path, body, secret=secret), ""
    except urllib.error.HTTPError as exc:
        logger.info("WeCom endpoint unavailable: %s: HTTP %s", path, exc.code)
        return None, f"HTTP {exc.code}"
    except RuntimeError as exc:
        logger.info("WeCom endpoint failed: %s: %s", path, exc)
        return None, str(exc)


def _get(path: str, params: str = "", *, secret: str | None = None) -> dict[str, Any]:
    token = _get_token(secret)
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
            secret = _resolve_domain_secret("contacts")
            dept_resp = _get("department/list", secret=secret)
            dept_ids = [d["id"] for d in dept_resp.get("department", [])]
            results = []
            for dept_id in dept_ids[:5]:  # search top 5 depts
                resp = _get("user/list", f"department_id={dept_id}&fetch_child=1", secret=secret)
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
            cal_id = _get_app_calendar_id()
            if not cal_id:
                return None
            resp = _post("oa/schedule/get_by_calendar", {
                "cal_id": cal_id,
                "offset": 0, "limit": 50,
            }, secret=_resolve_domain_secret("calendar"))
            events = []
            schedule_list = resp.get("schedule_list", [])
            for ev in schedule_list:
                summary = ev.get("summary", "(无标题)")
                start_ts = ev.get("start_time", {}).get("time", 0)
                end_ts = ev.get("end_time", {}).get("time", 0)
                if start_ts and end_ts and (start_ts < end < end_ts or start_ts < now < end_ts or (start_ts >= now and start_ts <= end)):
                    start_str = datetime.fromtimestamp(start_ts).strftime("%m-%d %H:%M") if start_ts else ""
                    end_str = datetime.fromtimestamp(end_ts).strftime("%H:%M") if end_ts else ""
                    events.append(f"{start_str}-{end_str} {summary}")
            return "\n".join(events[:20]) if events else None
        except Exception as e:
            logger.warning("WeCom get_agenda failed: %s", e)
            return None

    def query_meeting_room(
        self,
        query: str,
        days: int = 1,
        capability_context: CapabilityInvocationContext | None = None,
    ) -> str | None:
        del capability_context
        plan = plan_enterprise_query(query)
        room_name = plan.entities[0] if plan.entities else "会议室"
        # Same-day time range (API does not support cross-day queries)
        now = datetime.now()
        start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        end = int(now.replace(hour=23, minute=59, second=59, microsecond=0).timestamp())
        sections: list[str] = []
        errors: list[str] = []
        payloads: list[dict[str, Any]] = []

        secret = _resolve_domain_secret("meeting")

        # Step 1: list all meeting rooms
        room_list_resp = _post_optional("oa/meetingroom/list", {
            "city": "", "building": "", "floor": "",
        }, secret=secret)
        room_list: list[dict[str, Any]] = []
        room_map: dict[str, dict[str, Any]] = {}
        if room_list_resp:
            room_list = room_list_resp.get("meetingroom_list", [])
            for r in room_list:
                name = r.get("name", "")
                if name:
                    room_map[name] = r
        if room_list_resp:
            payloads.append(room_list_resp)

        # Step 2: match user's spoken name to real room
        matched_rooms: list[str] = []
        if room_name and room_name != "会议室":
            if room_name in room_map:
                matched_rooms.append(room_name)
            else:
                numbers = _extract_numbers(room_name)
                for rn in room_map:
                    if any(n in rn for n in numbers):
                        matched_rooms.append(rn)
                if not matched_rooms:
                    matched_rooms = list(room_map.keys())[:3]

        # Step 3: get same-day booking info using meetingroom_id
        for query_room in (matched_rooms or list(room_map.keys()) or [room_name]):
            room_info = room_map.get(query_room, {})
            room_id = room_info.get("meetingroom_id")
            if room_id is not None:
                info, err = _post_optional_diagnostic("oa/meetingroom/get_booking_info", {
                    "meetingroom_id": room_id,
                    "start_time": start,
                    "end_time": end,
                }, secret=secret)
                if info:
                    payloads.append(info)
                    text = _format_room_payload(info, query_room)
                    if text:
                        sections.append(text)
                elif err:
                    errors.append(err)

        # Step 4: fallback meeting API
        meeting_resp, meeting_err = _post_optional_diagnostic("meeting/list", {
            "begin_time": start, "end_time": end, "limit": 50,
        }, secret=secret)
        if meeting_resp:
            payloads.append(meeting_resp)
        elif meeting_err:
            errors.append(meeting_err)

        if plan.operation == "availability" and payloads:
            availability = _format_room_availability(payloads)
            if availability:
                return availability

        if sections:
            return "\n".join(dict.fromkeys(sections))

        # Step 5: room list fallback
        if room_list:
            lines = [f"{r.get('name', '')} (容纳{r.get('capacity', '?')}人)" for r in room_list]
            first_room = lines[0].split("(")[0].strip() if lines else "会议室"
            return (
                f"当前企业共 {len(room_list)} 间会议室：\n"
                + "\n".join(lines)
                + f"\n\n暂未获取到今日占用详情。可使用具体会议室名称（如\"{first_room}\"）查询占用情况。"
            )

        if errors:
            if any("48002" in error or "forbidden" in error.lower() for error in errors):
                return (
                    f"暂时无法读取{room_name or '该会议室'}的真实占用数据："
                    "当前企业微信应用缺少会议室或会议数据接口权限（错误码 48002）。"
                    "请由企业管理员为承载 AI 助手的自建应用补充会议室、会议和日程只读权限后重试。"
                )
            return f"暂时无法读取{room_name or '该会议室'}的真实占用数据。"
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
            }, secret=_resolve_domain_secret("calendar"))
            cal_id = resp.get("cal_id", "")
            return f"日程已创建 (ID: {cal_id})" if cal_id else "日程创建成功"
        except Exception as e:
            logger.warning("WeCom create_event failed: %s", e)
            raise

    def search_docs(self, query: str) -> str | None:
        try:
            resp = _post(
                "doc/search",
                {"query": query, "offset": 0, "limit": 10},
                secret=_resolve_domain_secret("docs"),
            )
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
            resp = _post("wedoc/create_doc", {
                "doc_name": title,
                "doc_type": 3,
            }, secret=_resolve_domain_secret("docs"))
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
            resp = _post("meeting/list", {
                "begin_time": now - 30 * 86400,
                "end_time": now + 30 * 86400,
                "limit": 10,
            }, secret=_resolve_domain_secret("meeting"))
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

    def get_approval_detail(
        self,
        query: str,
        capability_context: CapabilityInvocationContext | None = None,
    ) -> str | None:
        return self.list_approvals(
            "pending",
            query=query,
            capability_context=capability_context,
        )

    def list_approvals(
        self,
        status: str = "pending",
        *,
        query: str = "",
        capability_context: CapabilityInvocationContext | None = None,
    ) -> str | None:
        if str(status).lower() not in {"pending", "all", "approved", "rejected", "审批中", "所有"}:
            query = query or str(status)
            status = "all"
        # When user provides a specific query (name, type), don't pre-filter by status
        search_status = status
        if query:
            search_status = "all"
        # Determine if user wants personal scope vs all
        force_personal = _looks_personal_approval_query(query)
        if str(search_status).lower() in ("pending", "审批中") and not query:
            force_personal = True
        # If query contains a person name, try to resolve to userid for precise match
        target_userid = _resolve_query_name_to_userid(query)
        loaded = self._load_user_approval_details(capability_context, force_personal=force_personal)
        if isinstance(loaded, tuple):
            details, error = loaded
        else:
            details, error = loaded, ""
        if error:
            normalized_error = error.lower()
            if (
                "48002" in error
                or "301055" in error
                or "forbidden" in normalized_error
                or "no approval auth" in normalized_error
            ):
                return (
                    "暂时无法读取当前用户的真实审批数据："
                    "企业微信 AI 助手应用缺少审批数据读取权限"
                    + ("（错误码 48002）。" if "48002" in error else "。")
                )
            return f"暂时无法读取当前用户的真实审批数据：{error}"
        if not details:
            return "当前用户权限范围内没有查到审批记录。"
        plan = plan_enterprise_query(query or "查询我的审批")
        terms = plan.query_terms
        filtered = [
            item
            for item in details
            if _approval_matches(item, terms, search_status, target_userid=target_userid)
        ]
        return "\n".join(
            f"{item['name']}（{item['sp_no']}）：{item['status']}，申请人 {item['applicant']}"
            for item in filtered[:20]
        ) or "当前用户权限范围内没有与该条件匹配的审批记录。"

    def _load_user_approval_details(
        self,
        capability_context: CapabilityInvocationContext | None = None,
        *,
        force_personal: bool = False,
    ) -> tuple[list[dict[str, str]], str]:
        now = int(time.time())
        start = now - 14 * 86400
        end = now + 7 * 86400
        approval_secret = _resolve_domain_secret("approval")
        response, error = _post_optional_diagnostic(
            "oa/getapprovalinfo",
            {"starttime": start, "endtime": end, "cursor": 0, "size": 100},
            secret=approval_secret,
        )
        if not response:
            return [], error
        user_id = capability_context.user_id if capability_context else ""
        can_view_all = not force_personal and _is_approval_admin(user_id)
        # Resolve user IDs to display names
        user_ids_to_resolve: set[str] = set()
        details: list[dict[str, str]] = []
        raw_details: list[dict[str, Any]] = []
        for sp_no in response.get("sp_no_list", [])[:100]:
            detail = _post_optional(
                "oa/getapprovaldetail",
                {"sp_no": sp_no},
                secret=approval_secret,
            )
            info = detail.get("info", {}) if isinstance(detail, dict) else {}
            if not info:
                continue
            participants = _approval_participants(info)
            if user_id and not can_view_all and user_id not in participants:
                continue
            applyer = info.get("applyer") or {}
            applicant_uid = applyer.get("userid", "")
            if applicant_uid:
                user_ids_to_resolve.add(applicant_uid)
            raw_details.append({
                "sp_no": str(info.get("sp_no") or sp_no),
                "name": str(info.get("sp_name") or info.get("template_name") or "未命名审批"),
                "status": _approval_status_label(info.get("sp_status")),
                "applicant": applicant_uid,
                "applicant_uid": applicant_uid,
            })
        # Batch resolve user names
        name_map = _batch_resolve_user_names(user_ids_to_resolve)
        for rd in raw_details:
            resolved = name_map.get(rd["applicant"], rd["applicant"])
            details.append({
                "sp_no": rd["sp_no"],
                "name": rd["name"],
                "status": rd["status"],
                "applicant": resolved,
                "applicant_uid": rd["applicant_uid"],
            })
        return details, ""

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
            resp = _post("meeting/create", body, secret=_resolve_domain_secret("meeting"))
            meeting_id = resp.get("meetingid", "")
            return f"会议已创建: {title} (meetingid: {meeting_id})" if meeting_id else "会议创建成功"
        except Exception as e:
            logger.warning("WeCom create_meeting failed: %s", e)
            raise

    def query_enterprise_apps(
        self,
        query: str,
        action: str = "query",
        capability_context: CapabilityInvocationContext | None = None,
    ) -> str | None:
        del action
        plan = plan_enterprise_query(query)
        sections: list[str] = []
        for domain in plan.domains:
            if domain == "meeting_room":
                value = _optional_client_call(
                    self.query_meeting_room,
                    query,
                    capability_context=capability_context,
                )
                label = "会议室"
            elif domain == "approval":
                value = _optional_client_call(
                    self.list_approvals,
                    "all",
                    query=query,
                    capability_context=capability_context,
                )
                label = "审批"
            elif domain == "meeting":
                value = _optional_client_call(self.list_meetings)
                label = "会议"
            elif domain == "calendar":
                value = _optional_client_call(self.get_agenda, days=7)
                label = "日程"
            elif domain == "docs":
                value = _optional_client_call(self.search_docs, query)
                label = "在线文档"
            else:
                value = None
                label = domain
            if value:
                sections.append(f"【{label}】\n{value}")
        return "\n\n".join(sections) if sections else None

    def list_accessible_applications(
        self,
        query: str = "",
        capability_context: CapabilityInvocationContext | None = None,
    ) -> str | None:
        user_id = capability_context.user_id if capability_context else ""
        user_departments: set[str] = set()
        if user_id:
            user = _get(
                "user/get",
                f"userid={user_id}",
                secret=_resolve_domain_secret("contacts"),
            )
            user_departments = {str(item) for item in user.get("department", [])}
        response = _get("agent/list", secret=_resolve_domain_secret("apps"))
        lines: list[str] = []
        normalized_query = _normalize_match_text(query)
        for agent in response.get("agentlist", []):
            if not _agent_visible_to_user(agent, user_id, user_departments):
                continue
            name = str(agent.get("name") or "未命名应用")
            description = str(agent.get("description") or "")
            if normalized_query and not any(
                marker in normalized_query for marker in ("第三方应用", "业务系统", "所有应用")
            ):
                searchable = _normalize_match_text(name + description)
                if normalized_query not in searchable and searchable not in normalized_query:
                    continue
            lines.append(
                f"{name}（应用 ID: {agent.get('agentid', '')}）"
                + (f"：{description}" if description else "")
            )
        return "\n".join(lines) if lines else None

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
    for key in ("booking_list", "bookings", "meetingroom_list", "meeting_room_list", "room_list", "meeting_list", "schedule_items"):
        value = payload.get(key)
        if isinstance(value, list):
            raw_items.extend(value)
    for value in payload.values():
        if isinstance(value, dict):
            for nested_key in ("booking_list", "meetingroom_list", "meeting_room_list", "room_list", "meeting_list", "schedule_items"):
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


def _format_room_availability(payloads: list[dict[str, Any]]) -> str:
    rooms: dict[str, str] = {}
    bookings: dict[str, list[str]] = {}
    for payload in payloads:
        for item in _nested_list_items(payload, ("meetingroom_list", "room_list", "meeting_room_list")):
            room_id = str(item.get("room_id") or item.get("meeting_room_id") or item.get("id") or "")
            room_name = str(item.get("room_name") or item.get("meeting_room_name") or item.get("name") or "")
            if room_name:
                rooms[room_id or room_name] = room_name
        for item in _nested_list_items(payload, ("booking_list", "bookings", "schedule_items", "meeting_list")):
            room_id = str(item.get("room_id") or item.get("meeting_room_id") or "")
            room_name = str(item.get("room_name") or item.get("meeting_room_name") or item.get("location") or "")
            key = room_id or room_name
            if not key:
                continue
            if room_name:
                rooms.setdefault(key, room_name)
            start = _format_timestamp(item.get("start_time") or item.get("begin_time"), "%H:%M")
            end = _format_timestamp(item.get("end_time"), "%H:%M")
            bookings.setdefault(key, []).append(f"{start}-{end}".strip("-"))
    if not rooms:
        return ""
    lines = []
    for key, name in rooms.items():
        occupied = [slot for slot in bookings.get(key, []) if slot]
        if occupied:
            lines.append(f"{name}：已占用时段 {', '.join(occupied)}；其他时段可申请")
        else:
            lines.append(f"{name}：当前查询时段内无预订，可申请")
    return "\n".join(lines)


def _nested_list_items(payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
    for value in payload.values():
        if isinstance(value, dict):
            items.extend(_nested_list_items(value, keys))
    return items


def _format_timestamp(value: Any, pattern: str) -> str:
    if isinstance(value, dict):
        value = value.get("time")
    try:
        timestamp = int(value or 0)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(timestamp).strftime(pattern) if timestamp else ""


def _approval_participants(info: dict[str, Any]) -> set[str]:
    participants = {
        str((info.get("applyer") or {}).get("userid") or ""),
    }
    for record in info.get("sp_record", []) or []:
        if not isinstance(record, dict):
            continue
        for detail in record.get("details", []) or []:
            if not isinstance(detail, dict):
                continue
            approver = detail.get("approver") or {}
            participants.add(str(approver.get("userid") or ""))
    return {user_id for user_id in participants if user_id}


def _approval_status_label(value: Any) -> str:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return str(value or "未知")
    return {
        1: "审批中",
        2: "已通过",
        3: "已驳回",
        4: "已撤销",
        6: "通过后撤销",
        7: "已删除",
        10: "已支付",
    }.get(status, f"状态 {status}")


def _approval_matches(item: dict[str, str], terms: tuple[str, ...], status: str, *, target_userid: str = "") -> bool:
    normalized_status = str(status or "").lower()
    if normalized_status in {"pending", "审批中"} and item.get("status") != "审批中":
        return False
    # Fuzzy person name match: check if cleaned name overlaps with applicant
    if target_userid:
        applicant_name = str(item.get("applicant", ""))
        if _fuzzy_name_match(target_userid, applicant_name):
            return True
    if not terms:
        return True if not target_userid else False
    name = _normalize_match_text(item.get("name", ""))
    applicant = _normalize_match_text(item.get("applicant", ""))
    applicant_uid = str(item.get("applicant_uid", "")).lower()
    for term in terms:
        nt = _normalize_match_text(term)
        if nt in name or name in nt:
            return True
        if nt in applicant or applicant in nt:
            return True
        if applicant_uid and (nt in applicant_uid or applicant_uid in nt):
            return True
    return False


def _normalize_match_text(value: str) -> str:
    replacements = {
        "申批": "审批",
        "申请": "审批",
        "流程": "",
        "员工": "",
        "的": "",
    }
    normalized = str(value or "").lower().replace(" ", "")
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def _fuzzy_name_match(query_name: str, applicant_name: str) -> bool:
    """Fuzzy match for Chinese names — allows one-character difference."""
    if not query_name or not applicant_name:
        return False
    qc = set(query_name)
    ac = set(applicant_name)
    overlap = qc & ac
    if len(overlap) >= len(qc) - 1 and len(overlap) >= 1:
        return True
    return False


def _looks_personal_approval_query(query: str) -> bool:
    """Returns True if the query asks for the user's own approvals."""
    normalized = str(query or "").replace(" ", "").lower()
    personal_words = ("我的", "我", "个人", "自己", "本人")
    all_words = ("所有", "全部", "所有人员", "公司", "全员", "全部审批")
    if any(w in normalized for w in all_words):
        return False
    return any(w in normalized for w in personal_words)


def _resolve_query_name_to_userid(query: str) -> str:
    """Try to find a person name in the query. Returns cleaned name string for fuzzy matching."""
    if not query:
        return ""
    if _looks_personal_approval_query(query):
        return ""
    normalized = str(query).replace(" ", "").lower()
    if any(w in normalized for w in ("所有", "全部", "公司", "全员")):
        return ""
    cleaned = normalized
    for _domain, aliases in (
        ("approval", ("审批", "申批")),
    ):
        for alias in aliases:
            cleaned = cleaned.replace(alias, "")
    for word in ("查询", "查一下", "查", "看看", "的", "情况", "状态", "进度"):
        cleaned = cleaned.replace(word, "")
    cleaned = cleaned.strip()
    return cleaned if len(cleaned) >= 2 else ""


def _is_approval_admin(user_id: str) -> bool:
    if not user_id:
        return False
    try:
        from src.platform.admin_registry import get_admin_ids

        return user_id in get_admin_ids("wecom")
    except Exception:
        return False


def _agent_visible_to_user(
    agent: dict[str, Any],
    user_id: str,
    user_departments: set[str],
) -> bool:
    allowed_users = {
        str(item.get("userid") or "")
        for item in (agent.get("allow_userinfos") or {}).get("user", [])
        if isinstance(item, dict)
    }
    allowed_departments = {
        str(item.get("partyid") or item.get("department_id") or "")
        for item in (agent.get("allow_partys") or {}).get("party", [])
        if isinstance(item, dict)
    }
    allowed_tags = (agent.get("allow_tags") or {}).get("tag", [])
    if not allowed_users and not allowed_departments and not allowed_tags:
        return True
    if user_id and user_id in allowed_users:
        return True
    return bool(user_departments & allowed_departments)


def _optional_client_call(method, *args: Any, **kwargs: Any) -> Any | None:
    try:
        return method(*args, **kwargs)
    except Exception as exc:
        logger.info("Optional WeCom application capability failed: %s", exc)
        return None


def _extract_numbers(text: str) -> list[str]:
    import re
    nums = re.findall(r'[0-9零一二三四五六七八九十百千万]+', text)
    cn_map = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "十": "10", "零": "0"}
    result = []
    for n in nums:
        if n.isdigit():
            result.append(n)
        else:
            mapped = "".join(cn_map.get(c, c) for c in n)
            result.append(mapped)
    return list(dict.fromkeys(result))


def _batch_resolve_user_names(user_ids: set[str]) -> dict[str, str]:
    """Resolve WeCom userids to display names via contacts API."""
    name_map: dict[str, str] = {}
    if not user_ids:
        return name_map
    for uid in user_ids:
        try:
            resp = _get("user/get", f"userid={uid}", secret=None)  # use app secret, not contacts sync secret
            name = resp.get("name", "")
            if name:
                name_map[uid] = name
                logger.debug("Resolved user %s -> %s", uid, name)
        except Exception:
            logger.info("Could not resolve user name for %s", uid)
    return name_map


_calendar_id_cache: str | None = None


def _get_app_calendar_id() -> str:
    """Get or create the default calendar for this WeCom app. Caches the cal_id."""
    global _calendar_id_cache
    if _calendar_id_cache:
        return _calendar_id_cache
    secret = _resolve_domain_secret("calendar")
    try:
        resp = _post("oa/calendar/add", {
            "calendar": {
                "summary": "AI 助手日程",
                "color": "#0078D4",
                "description": "由企业 AI 助手自动创建的日历",
                "set_as_default": 1,
            }
        }, secret=secret)
        cal_id = resp.get("cal_id", "")
        if cal_id:
            _calendar_id_cache = cal_id
            logger.info("Created default calendar: %s", cal_id)
            return cal_id
    except Exception as e:
        logger.info("Could not create / access app calendar: %s (will retry next call)", e)
    return ""

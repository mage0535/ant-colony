from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from typing import Any

from src.platform.capability_audit import CapabilityInvocationContext
from src.platform.enterprise_query import EnterpriseQueryPlan, plan_enterprise_query

logger = logging.getLogger(__name__)

WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"
_corp_id: str = ""
_agent_id: int = 0
_app_secret: str = ""
_token_cache: dict[str, tuple[str, float]] = {}
_token_lock = threading.Lock()


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
    with _token_lock:
        token, expires = _token_cache.get(resolved_secret, ("", 0))
        if token and time.time() < expires - 60:
            return token
    url = f"{WECOM_API}/gettoken?corpid={_corp_id}&corpsecret={resolved_secret}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"WeCom token error: {data.get('errmsg')}")
    with _token_lock:
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
        raise RuntimeError(f"WeCom API error ({path}): [{result.get('errcode', 0)}] {result.get('errmsg')}")
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
        raise RuntimeError(f"WeCom API error ({path}): [{result.get('errcode', 0)}] {result.get('errmsg')}")
    return result


class WeComClient:
    last_process_event_error: str = ""

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

        # Step 1: list all meeting rooms
        secret = _resolve_domain_secret("meeting")
        room_list_resp = _post_optional("oa/meetingroom/list", {
            "city": "", "building": "", "floor": "",
        }, secret=secret)
        room_list_error = ""
        if not room_list_resp:
            room_list_resp, room_list_error = _post_optional_diagnostic(
                "oa/meetingroom/list",
                {"city": "", "building": "", "floor": ""},
                secret=secret,
            )
        room_list: list[dict[str, Any]] = []
        if room_list_resp:
            room_list = room_list_resp.get("meetingroom_list", [])

        if not room_list:
            if room_list_error:
                return f"暂时无法读取会议室真实占用数据：{room_list_error}"
            return f"没有查到{room_name or '该会议室'}的会议室列表。"

        booking_resp, booking_error = _post_optional_diagnostic(
            "oa/meetingroom/bookinfo",
            {"days": max(int(days or 1), 1)},
            secret=secret,
        )
        if booking_resp:
            availability = _format_room_availability([room_list_resp, booking_resp])
            if availability:
                return availability

        # Step 2: build room approval map from approval API (fallback occupancy source)
        room_bookings, errors = _build_room_approval_map(room_list, filter_today=bool(plan.start_date))
        if booking_error:
            errors.append(booking_error)
        occupied_rooms = set(room_bookings.keys())

        # Step 3: match user's query to real room
        matched_rooms: list[str] = []
        if room_name and room_name != "会议室":
            if room_name in {r.get("name", "") for r in room_list}:
                matched_rooms.append(room_name)
            else:
                numbers = _extract_numbers(room_name)
                for r in room_list:
                    rn = r.get("name", "")
                    if any(n in rn for n in numbers) or _match_room_name_approval(rn, room_name):
                        matched_rooms.append(rn)
                if not matched_rooms:
                    # Try matching original query against room names
                    for r in room_list:
                        rn = r.get("name", "")
                        if room_name in rn or any(c in rn for c in room_name if c.isdigit()):
                            matched_rooms.append(rn)
                if not matched_rooms:
                    matched_rooms = [r.get("name", "") for r in room_list[:3] if r.get("name")]

        # Step 4: format result
        if plan.operation == "availability":
            return _format_room_availability_from_approvals(room_list, room_bookings, errors)
        elif matched_rooms:
            return _format_specific_room_from_approvals(matched_rooms, room_bookings, errors)
        else:
            return _format_room_availability_from_approvals(room_list, room_bookings, errors)

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
        """Search WeCom online documents. Fallback gracefully since the doc/search endpoint is deprecated."""
        try:
            resp = _post(
                "wedoc/search",
                {"query": query, "limit": 10},
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
            return None

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
            err_msg = str(e)
            if "730007" in err_msg:
                logger.info("WeCom meeting module requires Professional edition (730007)")
                return None
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

    def list_process_events(
        self,
        capability_context: CapabilityInvocationContext | None = None,
    ) -> list[dict[str, Any]]:
        """Return structured approval/process events for automatic notifications."""
        self.last_process_event_error = ""
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
            if error:
                self.last_process_event_error = error
                logger.info("WeCom process event list unavailable: %s", error)
            return []
        user_id = capability_context.user_id if capability_context else ""
        can_view_all = _is_approval_admin(user_id)
        events: list[dict[str, Any]] = []
        user_ids_to_resolve: set[str] = set()
        raw_events: list[dict[str, Any]] = []
        for sp_no in response.get("sp_no_list", [])[:100]:
            detail = _post_optional("oa/getapprovaldetail", {"sp_no": sp_no}, secret=approval_secret)
            info = detail.get("info", {}) if isinstance(detail, dict) else {}
            if not info:
                continue
            participants = _approval_participants(info)
            if user_id and not can_view_all and user_id not in participants:
                continue
            applyer = info.get("applyer") or {}
            applicant_uid = str(applyer.get("userid") or "")
            handlers = _approval_current_handler_userids(info)
            user_ids_to_resolve.update(uid for uid in [applicant_uid, *handlers] if uid)
            raw_events.append(
                {
                    "source": "approval",
                    "item_id": str(info.get("sp_no") or sp_no),
                    "title": str(info.get("sp_name") or info.get("template_name") or "未命名审批"),
                    "status": _approval_status_label(info.get("sp_status")),
                    "current_node": _approval_current_node(info),
                    "applicant_user_id": applicant_uid,
                    "applicant_name": applicant_uid,
                    "recipient_user_ids": handlers,
                    "content": _approval_content_summary(info),
                    "event_time": _format_timestamp(info.get("apply_time"), "%Y-%m-%d %H:%M"),
                }
            )
        name_map = _batch_resolve_user_names(user_ids_to_resolve)
        for event in raw_events:
            applicant_uid = str(event.get("applicant_user_id") or "")
            event["applicant_name"] = name_map.get(applicant_uid, applicant_uid)
            if event.get("recipient_user_ids"):
                event["current_node"] = "、".join(
                    name_map.get(str(uid), str(uid))
                    for uid in event.get("recipient_user_ids", [])
                    if str(uid)
                )
            events.append(event)
        return events

    def create_meeting(self, title: str, start_at: str, end_at: str, attendees: list[str] | None = None) -> str | None:
        try:
            start_dt = datetime.strptime(start_at, "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(end_at, "%Y-%m-%d %H:%M")
            start_ts = int(start_dt.timestamp())
            end_ts = int(end_dt.timestamp())
            body = {
                "title": title,
                "start_time": start_ts,
                "end_time": end_ts,
                "meeting_duration": max(end_ts - start_ts, 60),
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
        except Exception as e:
            logger.info("WeCom get_admin_users failed: %s", e)
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
        except Exception as e:
            logger.info("WeCom get_admin_userids failed: %s", e)
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


def _build_room_approval_map(
    room_list: list[dict[str, Any]],
    filter_today: bool = False,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Return {room_name: [approval details]} from approval API, and error list.
    Only rooms with matching approval records appear as keys.
    """
    if not room_list:
        return {}, []
    room_bookings: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    # Build room name set for matching
    room_names: set[str] = {r.get("name", "") for r in room_list if r.get("name")}
    if not room_names:
        return {}, []
    # Query approval API
    now = int(time.time())
    today_start = int(datetime.combine(date.today(), datetime.min.time()).timestamp())
    try:
        approval_resp = _post_optional("oa/getapprovalinfo", {
            "starttime": today_start - 7 * 86400,
            "endtime": now,
            "offset": 0,
            "size": 100,
        }, secret=_resolve_domain_secret("approval"))
        if not approval_resp or not approval_resp.get("sp_no_list"):
            return {}, errors
        for sp_no in approval_resp.get("sp_no_list", [])[:50]:
            try:
                detail = _post_optional("oa/getapprovaldetail", {"sp_no": sp_no},
                                        secret=_resolve_domain_secret("approval"))
                if not detail:
                    continue
                info = detail.get("info", {}) or {}
                apply_data = info.get("apply_data", {}) or {}
                sp_status = info.get("sp_status", 0)
                if sp_status not in {1, 2}:
                    continue  # Only pending or approved
                applicant_userid = str((info.get("applyer") or {}).get("userid", "") or "")
                if not applicant_userid:
                    continue
                # Extract room name from Selector options
                matched_room = ""
                meeting_time = ""
                meeting_subject = ""
                for item in (apply_data.get("contents") or apply_data.get("content") or []) or []:
                    if isinstance(item, dict):
                        ctrl = item.get("control", "")
                        val = item.get("value", {}) or {}
                        if ctrl == "Selector":
                            options = (val.get("selector") or {}).get("options", []) or []
                            for opt in options:
                                opt_text = ""
                                for tv in (opt.get("value") or []):
                                    if isinstance(tv, dict):
                                        opt_text = tv.get("text", "")
                                        if opt_text:
                                            break
                                for rn in room_names:
                                    if rn in opt_text or _match_room_name_approval(opt_text, rn):
                                        matched_room = rn
                                        break
                                if matched_room:
                                    break
                        elif ctrl in ("Text", "Textarea"):
                            text_val = val.get("text", "") or ""
                            if text_val and ("日" in text_val or ":" in text_val):
                                meeting_time = text_val
                            elif text_val and not meeting_subject:
                                meeting_subject = text_val
                if not matched_room:
                    continue
                # If filtering for today, check meeting date
                if filter_today and meeting_time:
                    import re as _re
                    date_match = _re.search(r"(\d{1,2})月(\d{1,2})日", meeting_time)
                    if date_match:
                        m = int(date_match.group(1))
                        d = int(date_match.group(2))
                        today = date.today()
                        if m != today.month or d != today.day:
                            continue
                apply_time = info.get("apply_time", 0)
                time_str = datetime.fromtimestamp(apply_time).strftime("%m-%d %H:%M") if apply_time else ""
                status_label = {1: "审批中", 2: "已批准"}.get(sp_status, f"状态{sp_status}")
                room_bookings.setdefault(matched_room, []).append({
                    "applicant_uid": applicant_userid,
                    "time": time_str,
                    "status": status_label,
                    "subject": meeting_subject,
                    "meeting_time": meeting_time,
                })
            except Exception:
                continue
        # Resolve user names
        if room_bookings:
            all_uids: set[str] = set()
            for apps in room_bookings.values():
                for a in apps:
                    all_uids.add(a["applicant_uid"])
            from src.platform.api_wecom import _batch_resolve_user_names
            name_map = _batch_resolve_user_names(all_uids)
            for apps in room_bookings.values():
                for a in apps:
                    a["applicant_name"] = name_map.get(a["applicant_uid"], a["applicant_uid"])
    except Exception as e:
        logger.info("Approval-based room occupancy query failed: %s", e)
    return room_bookings, errors


def _format_room_availability_from_approvals(
    room_list: list[dict[str, Any]],
    room_bookings: dict[str, list[dict[str, Any]]],
    errors: list[str],
) -> str:
    """Format availability as a natural summary."""
    occupied: list[dict[str, Any]] = []
    available: list[dict[str, Any]] = []
    for r in room_list:
        rname = r.get("name", "")
        bookings = room_bookings.get(rname, [])
        if bookings:
            occupied.append({"name": rname, "capacity": r.get("capacity", "?"), "bookings": bookings})
        else:
            available.append({"name": rname, "capacity": r.get("capacity", "?")})

    total = len(room_list)
    if not occupied:
        avail_names = "、".join(f"{a['name']}（容{a['capacity']}人）" for a in available)
        result = f"今日共 {total} 间会议室，均无人申请，全部可申请：{avail_names}"
    else:
        occ_lines = []
        for o in occupied:
            b = o["bookings"][0]
            line = f"  • {o['name']}（容{o['capacity']}人）：{b['applicant_name']} {b['time']} 申请「{b['subject'] or '会议室预定'}」— {b['status']}"
            if b.get("meeting_time"):
                line += f"（{b['meeting_time']}）"
            occ_lines.append(line)
        if available:
            avail_names = "、".join(f"{a['name']}（容{a['capacity']}人）" for a in available)
            result = (
                f"今日共 {total} 间会议室，{len(occupied)} 间已被申请：\n"
                + "\n".join(occ_lines)
                + f"\n\n其余 {len(available)} 间可申请：{avail_names}"
            )
        else:
            result = (
                f"今日共 {total} 间会议室，全部已被申请：\n"
                + "\n".join(occ_lines)
            )
    if errors:
        result += "\n\n（部分接口查询失败：" + "；".join(errors[:2]) + "）"
    return result


def _format_specific_room_from_approvals(
    matched_rooms: list[str],
    room_bookings: dict[str, list[dict[str, Any]]],
    errors: list[str],
) -> str:
    """Format specific room query as a natural summary."""
    lines: list[str] = []
    for rname in matched_rooms:
        bookings = room_bookings.get(rname, [])
        if bookings:
            for b in bookings:
                line = f"{rname}：{b['applicant_name']} {b['time']} 申请「{b['subject'] or '会议室预定'}」— {b['status']}"
                if b.get("meeting_time"):
                    line += f"（{b['meeting_time']}）"
                lines.append(line)
        else:
            lines.append(f"{rname}：可申请")
    if not lines:
        return "没有找到匹配的会议室信息。"
    if len(lines) == 1:
        return lines[0]
    return "\n".join(lines)


def _match_room_name_approval(option_text: str, room_name: str) -> bool:
    """Check if an approval selector option matches a room name."""
    if not option_text or not room_name:
        return False
    ot = option_text.strip().lower()
    rn = room_name.strip().lower()
    if rn in ot:
        return True
    # Fuzzy: extract all digit groups and match any
    import re
    num_pattern = r"\d+"
    for tn in (ot, rn):
        rn_nums = set(re.findall(num_pattern, rn))
        ot_nums = set(re.findall(num_pattern, ot))
        if rn_nums and ot_nums and rn_nums & ot_nums:
            return True
    return False


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
    for item in raw_items[:]:
        if isinstance(item, dict) and isinstance(item.get("schedule"), list):
            parent_room = str(item.get("room_name") or item.get("meeting_room_name") or "")
            parent_schedule = item["schedule"]
            raw_items.remove(item)  # Remove parent — only expandable children remain
            if parent_schedule:
                for s in parent_schedule:
                    if isinstance(s, dict):
                        s = dict(s)
                        if parent_room and not s.get("room_name") and not s.get("meeting_room_name"):
                            s["room_name"] = parent_room
                        raw_items.append(s)
            # If schedule is empty, don't inject placeholder — the WeCom API
            # always returns a booking_list entry with empty schedule regardless
            # of actual occupancy on non-professional editions.
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("subject") or item.get("summary") or item.get("name") or item.get("room_name") or item.get("meeting_room_name") or "")
        location = str(item.get("location") or item.get("room_name") or item.get("meeting_room_name") or room_name or "")
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
            room_id = str(item.get("room_id") or item.get("meetingroom_id") or item.get("meeting_room_id") or item.get("id") or "")
            room_name = str(item.get("room_name") or item.get("meeting_room_name") or item.get("name") or "")
            if room_name:
                rooms[room_id or room_name] = room_name
        booking_items = _nested_list_items(payload, ("booking_list", "bookings", "schedule_items", "meeting_list"))
        expanded: list[dict[str, Any]] = []
        for item in booking_items:
            if isinstance(item.get("schedule"), list):
                parent_room = str(item.get("room_name") or item.get("meeting_room_name") or "")
                parent_rid = str(item.get("room_id") or item.get("meetingroom_id") or "")
                if item["schedule"]:
                    for s in item["schedule"]:
                        if isinstance(s, dict):
                            s = dict(s)
                            if parent_room and not s.get("room_name"):
                                s["room_name"] = parent_room
                            if parent_rid and not s.get("room_id") and not s.get("meetingroom_id") and not s.get("meeting_room_id"):
                                s["meeting_room_id"] = parent_rid
                            expanded.append(s)
                # Empty schedule: don't inject placeholder — the WeCom API
                # always returns a booking_list entry regardless of occupancy
            else:
                expanded.append(item)
        for item in expanded:
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


def _approval_current_handler_userids(info: dict[str, Any]) -> list[str]:
    if _approval_status_label(info.get("sp_status")) != "审批中":
        return []
    handlers: list[str] = []
    for record in info.get("sp_record", []) or []:
        if not isinstance(record, dict):
            continue
        record_status = str(record.get("sp_status") or record.get("status") or "")
        if record_status and record_status not in {"1", "审批中", "pending"}:
            continue
        record_handlers: list[str] = []
        for detail in record.get("details", []) or []:
            if not isinstance(detail, dict):
                continue
            status = str(detail.get("sp_status") or detail.get("status") or "")
            approver = detail.get("approver") or {}
            userid = str(approver.get("userid") or "")
            if userid and status in {"1", "审批中", "pending"} and userid not in record_handlers:
                record_handlers.append(userid)
        if record_handlers:
            handlers.extend(record_handlers)
            break
    return handlers


def _approval_current_node(info: dict[str, Any]) -> str:
    return "、".join(_approval_current_handler_userids(info))


def _approval_content_summary(info: dict[str, Any]) -> str:
    labels: list[str] = []
    apply_data = info.get("apply_data") or {}
    contents = apply_data.get("contents") if isinstance(apply_data, dict) else []
    for content in contents or []:
        if not isinstance(content, dict):
            continue
        title = _approval_control_value(content.get("title") or content.get("control"))
        value = _approval_control_value(content.get("value"))
        if title and value:
            labels.append(f"{title}：{value}")
        elif value:
            labels.append(value)
        if len("；".join(labels)) > 120:
            break
    return "；".join(labels)[:160] if labels else str(info.get("sp_name") or info.get("template_name") or "审批流程")


def _approval_control_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        if text[0] in "{[":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return ""
            return _approval_control_value(parsed)
        return text
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [_approval_control_value(item) for item in value]
        return "、".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "title", "name", "value", "new_text"):
            if key in value:
                parsed = _approval_control_value(value.get(key))
                if parsed:
                    return parsed
        for key in ("tips", "members", "userlist", "children", "departments", "files"):
            v = value.get(key)
            if isinstance(v, list) and v:
                parsed = _approval_control_value(v)
                if parsed:
                    return parsed
        return ""
    return str(value)


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
    org_all_words = ("所有人员", "全部人员", "全部人", "公司", "全员", "全部审批", "全部流程")
    if any(w in normalized for w in org_all_words) and not any(w in normalized for w in personal_words):
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
    # Batch resolve: use user/list on root department to get all users at once
    try:
        resp = _get("user/list", "department_id=1&fetch_child=1", secret=None)
        for u in resp.get("userlist", []):
            uid = u.get("userid", "")
            name = u.get("name", "")
            if uid and name and uid in user_ids:
                name_map[uid] = name
    except Exception:
        logger.info("Batch user resolve failed, falling back to per-user lookup")
    # Fallback: resolve remaining users individually
    remaining = [u for u in user_ids if u not in name_map]
    for uid in remaining:
        try:
            resp = _get("user/get", f"userid={uid}", secret=None)
            name = resp.get("name", "")
            if name:
                name_map[uid] = name
        except Exception:
            logger.info("Could not resolve user name for %s", uid)
    return name_map


_calendar_id_cache: str | None = None


def _load_persisted_calendar_id() -> str:
    """Try to load persisted cal_id from runtime_settings.json."""
    import json as _json
    try:
        path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "runtime_settings.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                settings = _json.load(f)
            return settings.get("wecom_calendar_id", "") or ""
    except Exception:
        pass
    return ""


def _persist_calendar_id(cal_id: str):
    """Persist cal_id to runtime_settings.json."""
    import json as _json
    try:
        path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "runtime_settings.json")
        settings = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                settings = _json.load(f)
        settings["wecom_calendar_id"] = cal_id
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Could not persist calendar id: %s", e)


def _get_app_calendar_id() -> str:
    """Get or create the default calendar for this WeCom app. Persists cal_id across restarts."""
    global _calendar_id_cache
    if _calendar_id_cache:
        return _calendar_id_cache
    persisted = _load_persisted_calendar_id()
    if persisted:
        _calendar_id_cache = persisted
        logger.info("Loaded persisted calendar id: %s", persisted)
        return persisted
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
            _persist_calendar_id(cal_id)
            logger.info("Created and persisted default calendar: %s", cal_id)
            return cal_id
    except Exception as e:
        logger.info("Could not create / access app calendar: %s (will retry next call)", e)
    return ""

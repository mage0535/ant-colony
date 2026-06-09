from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"
_corp_id: str = ""
_agent_id: int = 0
_app_secret: str = ""
_token_cache: tuple[str, float] = ("", 0)


def _init_creds():
    global _corp_id, _agent_id, _app_secret
    import os
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
                results.append(f"{title} | 创建者: {creator}")
            return "\n".join(results) if results else None
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

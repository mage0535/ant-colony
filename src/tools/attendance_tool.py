"""Agent tool: query personal attendance records and leave balance from the attendance app's SQLite database."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ATTENDANCE_DB = "/opt/wecom-attendance/data/attendance.db"


def query_attendance(user_id: str, days: int = 7, start_date: str = "", end_date: str = "",
                     query_type: str = "attendance") -> str:
    """Query attendance or leave records for a given user.
    
    Args:
        user_id: WeCom user ID (FromUserName)
        days: Number of past days to query (default 7)
        start_date: Start date in YYYY-MM-DD format (overrides days if set)
        end_date: End date in YYYY-MM-DD format
        query_type: "attendance" for check-in records, "leave" for leave/absence records
    
    Returns:
        Formatted attendance/leave data string.
    """
    if not user_id:
        return "无法查询：缺少用户ID"

    db_path = Path(ATTENDANCE_DB)
    if not db_path.exists():
        return f"考勤数据库不存在：{ATTENDANCE_DB}"

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        
        # Calculate date range - exclude today by default
        today = datetime.now().strftime("%Y-%m-%d")
        if start_date:
            sd = start_date
            ed = end_date if end_date else today
        else:
            ed = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            start = datetime.now() - timedelta(days=days + 1)
            sd = start.strftime("%Y-%m-%d")
        
        # Check if user exists
        cur = conn.execute("SELECT user_id, name FROM employees WHERE user_id = ?", (user_id,))
        employee = cur.fetchone()
        if not employee:
            conn.close()
            return f"未找到员工（user_id: {user_id}），请确认企微账号已同步到系统"
        user_name = employee["name"]
        
        if query_type == "leave":
            cur = conn.execute(
                """SELECT id, start_at, end_at, approval_type, template_name, duration_days, approval_status, payload_json
                   FROM approval_records
                   WHERE user_id = ? AND start_at >= ? AND start_at <= ?
                   ORDER BY start_at DESC LIMIT 20""",
                (user_id, sd, ed),
            )
            leaves = cur.fetchall()
            conn.close()
            if not leaves:
                return f"{user_name} 在 {sd} ~ {ed} 期间没有审批记录"

            TYPE_CN = {"leave": "请假", "outing": "外出", "overtime": "加班", "business_trip": "出差", "other": ""}
            STATUS_CN = {"approved": "已批准", "processing": "审批中", "rejected": "已驳回", "cancelled": "已撤销", "withdraw": "已撤回"}

            lines = [f"{user_name} {sd} ~ {ed} 的审批记录："]
            lines.append("日期\t\t类型\t\t天数\t事由\t\t状态")
            for l in leaves:
                s = str(l['start_at'])[:10] if l['start_at'] else '?'
                e = str(l['end_at'])[:10] if l['end_at'] else '?'
                atype = l['approval_type'] or ''
                tname = l['template_name'] or ''
                type_cn = TYPE_CN.get(atype, tname or atype)
                status_cn = STATUS_CN.get(l['approval_status'] or '', l['approval_status'] or '')
                dur = f"{l['duration_days']}天" if l['duration_days'] else '-'
                reason = ''
                if l['payload_json']:
                    try:
                        import json
                        p = json.loads(l['payload_json'])
                        reason = p.get('sp_name', '') or ''
                    except:
                        reason = ''
                lines.append(f"  {s}~{e}\t{type_cn}\t{dur}\t{reason}\t{status_cn}")
            return "\n".join(lines)
        
        # Query attendance records
        cur = conn.execute("SELECT user_id, name FROM employees WHERE user_id = ?", (user_id,))
        employee = cur.fetchone()
        if not employee:
            conn.close()
            return f"未找到员工（user_id: {user_id}），请确认企微账号已同步到系统"
        
        user_name = employee["name"]
        
        # Query attendance records (exclude today)
        cur = conn.execute(
            """SELECT attendance_date, checkin_at, checkout_at, status, work_hours
               FROM attendance_records 
               WHERE user_id = ? AND attendance_date >= ? AND attendance_date <= ? AND attendance_date < ?
               ORDER BY attendance_date DESC""",
            (user_id, sd, ed, today),
        )
        records = cur.fetchall()
        conn.close()
        
        if not records:
            return f"{user_name} 在 {sd} ~ {ed} 期间没有打卡记录"

        STATUS_CN = {
            "normal": "正常",
            "normal+early_leave": "正常+早退",
            "late": "迟到",
            "late+early_leave": "迟到+早退",
            "late+missing_checkout": "迟到+缺下班卡",
            "minor_late": "轻微迟到",
            "minor_late+early_leave": "轻微迟到+早退",
            "minor_late+missing_checkout": "轻微迟到+缺下班卡",
            "missing_checkout": "缺下班卡",
            "missing_checkin+early_leave": "缺上班卡+早退",
            "outing": "外出",
            "other": "其他",
        }

        lines = [f"{user_name} {sd} ~ {ed} 的考勤记录："]
        lines.append("日期\t\t日期性质\t上班\t\t下班\t\t状态\t\t工时")
        for r in records:
            date_str = r["attendance_date"]
            raw_status = r["status"] if r["status"] else "other"
            if raw_status.startswith("leave"):
                parts = raw_status.split(":", 1)
                status_cn = "请假" + (f"（{parts[1]}）" if len(parts) > 1 else "")
            else:
                status_cn = STATUS_CN.get(raw_status, raw_status)

            work_hours = r["work_hours"] or 0

            def _fmt_time(val: Any) -> str:
                if not val:
                    return ""
                try:
                    t = datetime.fromisoformat(str(val))
                    t_cn = t + timedelta(hours=8)
                    return t_cn.strftime("%H:%M")
                except:
                    return str(val)[11:16] if len(str(val)) > 10 else str(val)

            check_in = _fmt_time(r["checkin_at"])
            check_out = _fmt_time(r["checkout_at"])
            date_type = "工作日" if check_in or check_out else "周末休息"
            if not check_in and not check_out:
                status_cn = date_type
            hours_str = f"{round(work_hours, 2)}" if work_hours else ""
            lines.append(f"  {date_str}\t{date_type}\t{check_in}\t{check_out}\t{status_cn}\t{hours_str}")

        return "\n".join(lines)
    
    except sqlite3.Error as e:
        logger.error("Attendance DB query failed: %s", e)
        return f"查询考勤数据失败：{e}"
    except Exception as e:
        logger.error("Attendance query unexpected error: %s", e)
        return f"查询出错：{e}"


_WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"
_WECOM_CORP_ID = "[corp-id]"
_WECOM_SECRET = "zadqkUlK20kxQuacPRVitKQQ_pMywEvjS8GtSyZaVIk"


def _wecom_access_token() -> str:
    import urllib.request, json
    url = f"{_WECOM_API_BASE}/gettoken?corpid={_WECOM_CORP_ID}&corpsecret={_WECOM_SECRET}"
    resp = json.loads(urllib.request.urlopen(urllib.request.Request(url), timeout=10).read())
    if resp.get("errcode") != 0:
        raise RuntimeError(f"WeCom token failed: {resp.get('errmsg', '')}")
    return resp["access_token"]


def query_leave_balance(user_id: str) -> str:
    """Query real-time leave balance from WeCom approval system vacation quota API."""
    if not user_id:
        return "无法查询：缺少用户ID"

    try:
        import urllib.request, json

        token = _wecom_access_token()
        url = f"{_WECOM_API_BASE}/oa/vacation/getuservacationquota?access_token={token}"
        payload = json.dumps({"userid": user_id}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())

        if resp.get("errcode") != 0:
            return f"查询假期余额失败：{resp.get('errmsg', '未知错误')}"

        lists = resp.get("lists", [])
        if not lists:
            return f"用户 {user_id} 暂无假期余额数据"

        lines = ["假期余额明细（来自企业微信）："]
        for v in lists:
            raw_name = v.get("vacationname", "未命名")
            if isinstance(raw_name, dict):
                name = raw_name.get("zh_CN", raw_name.get("en", "未命名"))
            else:
                name = raw_name or "未命名"
            assign_sec = v.get("assignduration", 0) or 0
            used_sec = v.get("usedduration", 0) or 0
            left_sec = v.get("leftduration", 0) or 0
            total_days = round(assign_sec / 86400, 1)
            used_days = round(used_sec / 86400, 1)
            left_days = round(left_sec / 86400, 1)
            if total_days > 0 or used_days > 0 or left_days > 0:
                lines.append(f"  {name}：已用 {used_days} 天，剩余 {left_days} 天（总额度 {total_days} 天）")

        if len(lines) == 1:
            return f"用户 {user_id} 的假期余额均为 0"

        return "\n".join(lines)

    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        return f"查询假期余额失败(HTTP {e.code})：{body}"
    except Exception as e:
        logger.warning("Leave balance query failed: %s", e)
        return f"查询假期余额失败：{e}"

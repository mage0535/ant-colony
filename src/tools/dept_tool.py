"""Department head - can view subordinates' attendance and approval records."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import urllib.request
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

ATTENDANCE_DB = "/opt/wecom-attendance/data/attendance.db"
LEADER_CACHE_FILE = "/home/codexcheck/ant-colony-probe/data/dept_leaders.json"


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for p in ["/home/codexcheck/ant-colony-probe/infra/.env.wecom", os.path.expanduser("~/ant-colony-probe/infra/.env.wecom")]:
        if os.path.isfile(p):
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if line and "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()
    return env

_ENV = _load_env()


def _get_app_token() -> str:
    corpid = _ENV.get("WECOM_CORP_ID", "")
    secret = _ENV.get("WECOM_SECRET", "")
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corpid}&corpsecret={secret}"
    resp = json.loads(urllib.request.urlopen(urllib.request.Request(url), timeout=10).read())
    return resp["access_token"]


def sync_dept_leaders() -> dict[str, list[str]]:
    """Fetch department leaders from WeCom and cache. Returns {dept_id: [leader_user_ids]}"""
    try:
        token = _get_app_token()
        # Get all departments
        depts = json.loads(urllib.request.urlopen(urllib.request.Request(f"https://qyapi.weixin.qq.com/cgi-bin/department/list?access_token={token}"), timeout=10).read())
        if depts.get("errcode", 0) != 0:
            logger.warning("Dept list failed: %s", depts.get("errmsg"))
            return _load_cached()
        dept_names = {}
        for d in depts.get("department", []):
            dept_names[d["id"]] = d.get("name", "")

        # Get all users with leader info
        result: dict[str, list[str]] = {}
        all_users = json.loads(urllib.request.urlopen(urllib.request.Request(f"https://qyapi.weixin.qq.com/cgi-bin/user/list?access_token={token}&department_id=1&fetch_child=1"), timeout=15).read())
        if all_users.get("errcode", 0) != 0:
            logger.warning("User list failed: %s", all_users.get("errmsg"))
            return _load_cached()
        
        for u in all_users.get("userlist", []):
            uid = u["userid"]
            is_leader = u.get("is_leader_in_dept", [0])
            if isinstance(is_leader, int):
                is_leader = [is_leader]
            depts_for_user = u.get("department", [])
            for i, dept_id in enumerate(depts_for_user):
                is_ldr = is_leader[i] if i < len(is_leader) else 0
                if is_ldr == 1:
                    dept_key = str(dept_id)
                    result.setdefault(dept_key, []).append(uid)
        
        os.makedirs(os.path.dirname(LEADER_CACHE_FILE), exist_ok=True)
        with open(LEADER_CACHE_FILE, "w") as f:
            json.dump({"leaders": result, "dept_names": dept_names, "updated_at": datetime.now().isoformat()}, f, ensure_ascii=False)
        logger.info("Synced %d department leaders", len(result))
        return result
    except Exception as e:
        logger.error("Leader sync failed: %s", e)
        return _load_cached()


def _load_cached() -> dict[str, list[str]]:
    try:
        with open(LEADER_CACHE_FILE) as f:
            data = json.load(f)
        return data.get("leaders", {})
    except:
        return {}


def _get_dept_name(dept_id: str) -> str:
    try:
        with open(LEADER_CACHE_FILE) as f:
            data = json.load(f)
        return data.get("dept_names", {}).get(dept_id, f"部门{dept_id}")
    except:
        return f"部门{dept_id}"


def get_user_depts(user_id: str) -> list[int]:
    """Get all department IDs for a user from attendance DB."""
    try:
        conn = sqlite3.connect(ATTENDANCE_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT user_id, name, department_name FROM employees WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
        conn.close()
        if not user:
            return []
        return [1]  # fallback
    except:
        return []


def query_subordinates(user_id: str, query_type: str = "all", days: int = 7) -> str:
    leaders = sync_dept_leaders()
    user_depts = [d for d, ids in leaders.items() if user_id in ids]
    if not user_depts:
        return "你目前不是任何部门的负责人，无法查看下属的考勤和审批记录。"

    token = _get_app_token()
    conn = sqlite3.connect(ATTENDANCE_DB)
    conn.row_factory = sqlite3.Row

    sd = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    ed = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    def _fmt_cn(val):
        """Convert UTC datetime string to China time HH:MM"""
        if not val:
            return "--:--"
        try:
            t = datetime.fromisoformat(str(val))
            t_cn = t + timedelta(hours=8)
            return t_cn.strftime("%H:%M")
        except:
            return str(val)[11:16] if len(str(val)) > 10 else str(val)[:5]

    ATTEND_STATUS_CN = {
        "normal": "正常", "normal+early_leave": "正常+早退",
        "late": "迟到", "late+early_leave": "迟到+早退",
        "late+missing_checkout": "迟到+缺下班卡",
        "minor_late": "轻微迟到", "minor_late+early_leave": "轻微迟到+早退",
        "minor_late+missing_checkout": "轻微迟到+缺下班卡",
        "missing_checkout": "缺下班卡", "missing_checkin+early_leave": "缺上班卡+早退",
        "outing": "外出", "other": "其他",
    }
    APPROVE_STATUS_CN = {"approved": "已批准", "processing": "审批中", "rejected": "已驳回"}
    TYPE_CN = {"leave": "请假", "outing": "外出", "overtime": "加班", "business_trip": "出差"}

    results = []
    for dept_id in user_depts:
        dept_name = _get_dept_name(dept_id)
        try:
            url = f"https://qyapi.weixin.qq.com/cgi-bin/user/list?access_token={token}&department_id={dept_id}&fetch_child=0"
            members = json.loads(urllib.request.urlopen(urllib.request.Request(url), timeout=10).read())
            users = members.get("userlist", [])
        except:
            users = []
        subordinate_ids = [u["userid"] for u in users if u["userid"] != user_id]
        if not subordinate_ids:
            continue

        lines = [f"\n📋 {dept_name}"]
        for uid in subordinate_ids:
            name = uid
            try:
                cur = conn.execute("SELECT name FROM employees WHERE user_id=?", (uid,))
                e = cur.fetchone()
                if e and e[0]:
                    name = e[0]
            except:
                pass

            if query_type in ("attendance", "all"):
                cur = conn.execute(
                    "SELECT attendance_date, checkin_at, checkout_at, status FROM attendance_records WHERE user_id=? AND attendance_date>=? AND attendance_date<=? ORDER BY attendance_date DESC LIMIT 3",
                    (uid, sd, ed),
                )
                att_records = cur.fetchall()
                if att_records:
                    lines.append(f"  【考勤】{name}")
                    for r in att_records:
                        s = ATTEND_STATUS_CN.get(r["status"], r["status"])
                        lines.append(f"    {r['attendance_date']}: {_fmt_cn(r['checkin_at'])}~{_fmt_cn(r['checkout_at'])} [{s}]")

            if query_type in ("approval", "all"):
                cur = conn.execute(
                    "SELECT start_at, end_at, approval_type, template_name, duration_days, approval_status FROM approval_records WHERE user_id=? AND start_at>=? AND start_at<=? ORDER BY start_at DESC LIMIT 3",
                    (uid, sd, ed),
                )
                app_records = cur.fetchall()
                if app_records:
                    lines.append(f"  【审批】{name}")
                    for r in app_records:
                        t = TYPE_CN.get(r["approval_type"], r["template_name"] or r["approval_type"])
                        st = APPROVE_STATUS_CN.get(r["approval_status"], r["approval_status"])
                        s = str(r["start_at"])[:10] if r["start_at"] else "?"
                        e = str(r["end_at"])[:10] if r["end_at"] else "?"
                        lines.append(f"    {s}~{e} {t} {r['duration_days']}天 [{st}]")

        if len(lines) > 1:
            results.extend(lines)

    conn.close()
    if not results:
        return "你的部门下属在查询期间没有考勤和审批记录"
    return "部门考勤和审批记录：" + "\n".join(results)


def query_subordinate_by_name(manager_id: str, name: str, query_type: str = "attendance", days: int = 7) -> str:
    """Department head queries a specific subordinate by name."""
    leaders = sync_dept_leaders()
    user_depts = [d for d, ids in leaders.items() if manager_id in ids]
    if not user_depts:
        return "你目前不是任何部门的负责人。"

    target_id = None
    # First try local DB
    try:
        conn2 = sqlite3.connect(ATTENDANCE_DB)
        cur2 = conn2.execute("SELECT user_id, name FROM employees")
        for row in cur2.fetchall():
            uname = row[1] or ""
            if name in uname or uname in name or row[0].lower() == name.lower():
                target_id = row[0]
                break
        conn2.close()
    except:
        pass

    # Fallback to WeCom API
    if not target_id:
        token = _get_app_token()
        for dept_id in user_depts:
            try:
                members = json.loads(urllib.request.urlopen(urllib.request.Request(f"https://qyapi.weixin.qq.com/cgi-bin/user/list?access_token={token}&department_id={dept_id}"), timeout=10).read())
                for u in members.get("userlist", []):
                    if u["userid"] == manager_id: continue
                    uname = u.get("name", "")
                    if name in uname or uname in name or u["userid"].lower() == name.lower():
                        target_id = u["userid"]
                        break
            except:
                pass
            if target_id:
                break

    if not target_id:
        return f"未找到名为「{name}」的员工。"

    conn = sqlite3.connect(ATTENDANCE_DB)
    conn.row_factory = sqlite3.Row
    sd = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    ed = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    cur = conn.execute("SELECT name FROM employees WHERE user_id=?", (target_id,))
    row = cur.fetchone()
    dname = row[0] if row and row[0] else target_id

    def _fmt(val):
        if not val: return "--:--"
        try: return (datetime.fromisoformat(str(val)) + timedelta(hours=8)).strftime("%H:%M")
        except: return str(val)[11:16] if len(str(val)) > 10 else str(val)[:5]

    ASC = {"normal":"正常","normal+early_leave":"正常+早退","late":"迟到","late+early_leave":"迟到+早退","minor_late":"轻微迟到","missing_checkout":"缺下班卡"}
    lines = []

    if query_type in ("attendance", "all"):
        cur = conn.execute("SELECT attendance_date, checkin_at, checkout_at, status FROM attendance_records WHERE user_id=? AND attendance_date>=? AND attendance_date<=? ORDER BY attendance_date DESC", (target_id, sd, ed))
        records = cur.fetchall()
        if records:
            lines.append(f"【考勤】{dname} {sd}~{ed}：")
            for r in records:
                s = ASC.get(r["status"], r["status"])
                lines.append(f"  {r['attendance_date']}: {_fmt(r['checkin_at'])}~{_fmt(r['checkout_at'])} [{s}]")
        elif query_type == "attendance":
            lines.append(f"{dname} 在 {sd}~{ed} 期间没有考勤记录")

    if query_type in ("approval", "all", "leave"):
        TC = {"leave":"请假","outing":"外出","overtime":"加班","business_trip":"出差"}
        SC = {"approved":"已批准","processing":"审批中","rejected":"已驳回"}
        cur = conn.execute("SELECT start_at, end_at, approval_type, template_name, duration_days, approval_status FROM approval_records WHERE user_id=? AND start_at>=? AND start_at<=? ORDER BY start_at DESC", (target_id, sd, ed))
        records = cur.fetchall()
        if records:
            lines.append(f"【审批】{dname} {sd}~{ed}：")
            for r in records:
                t = TC.get(r["approval_type"], r["template_name"] or r["approval_type"])
                st = SC.get(r["approval_status"], r["approval_status"])
                s = str(r["start_at"])[:10] or "?"; e = str(r["end_at"])[:10] or "?"
                lines.append(f"  {s}~{e} {t} {r['duration_days']}天 [{st}]")
        elif query_type in ("approval", "leave"):
            lines.append(f"{dname} 在 {sd}~{ed} 期间没有审批记录")

    conn.close()
    return "\n".join(lines) if lines else f"{dname} 在 {sd}~{ed} 期间没有数据"


def query_subordinate_balance(manager_id: str, name: str) -> str:
    """Department head queries a specific subordinate's leave balance via WeCom API."""
    leaders = sync_dept_leaders()
    user_depts = [d for d, ids in leaders.items() if manager_id in ids]
    if not user_depts:
        return "你目前不是任何部门的负责人。"

    # First try local DB for user lookup (more reliable)
    target_id = None
    target_name = name
    try:
        conn = sqlite3.connect(ATTENDANCE_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT user_id, name FROM employees")
        for row in cur.fetchall():
            uname = row["name"] or ""
            if name in uname or uname in name or row["user_id"].lower() == name.lower():
                target_id = row["user_id"]
                target_name = uname or row["user_id"]
                break
        conn.close()
    except:
        pass

    # Fallback to WeCom API department lists
    if not target_id:
        token = _get_app_token()
        for dept_id in user_depts:
            try:
                members = json.loads(urllib.request.urlopen(urllib.request.Request(
                    f"https://qyapi.weixin.qq.com/cgi-bin/user/list?access_token={token}&department_id={dept_id}"), timeout=10).read())
                for u in members.get("userlist", []):
                    if u["userid"] == manager_id:
                        continue
                    uname = u.get("name", "")
                    if name in uname or uname in name or u["userid"].lower() == name.lower():
                        target_id = u["userid"]
                        target_name = uname or u["userid"]
                        break
            except:
                pass
            if target_id:
                break

    if not target_id:
        return f"未找到名为「{name}」的员工。"

    # Call WeCom vacation quota API for subordinate
    try:
        import urllib.request, json
        corpid = _ENV.get("WECOM_CORP_ID", "")
        secret = _ENV.get("WECOM_SECRET", "")
        token2 = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corpid}&corpsecret={secret}"), timeout=10).read())["access_token"]
        url = f"https://qyapi.weixin.qq.com/cgi-bin/oa/vacation/getuservacationquota?access_token={token2}"
        payload = json.dumps({"userid": target_id}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if resp.get("errcode") != 0:
            return f"查询 {target_name} 假期余额失败：{resp.get('errmsg', '未知错误')}"
        lists = resp.get("lists", [])
        if not lists:
            return f"{target_name} 暂无假期余额数据"
        lines = [f"{target_name} 假期余额明细："]
        for v in lists:
            raw_name = v.get("vacationname", "未命名")
            if isinstance(raw_name, dict):
                vname = raw_name.get("zh_CN", raw_name.get("en", "未命名"))
            else:
                vname = raw_name or "未命名"
            assign_sec = v.get("assignduration", 0) or 0
            used_sec = v.get("usedduration", 0) or 0
            left_sec = v.get("leftduration", 0) or 0
            if assign_sec > 0 or used_sec > 0 or left_sec > 0:
                lines.append(f"  {vname}：已用 {round(used_sec/86400,1)} 天，剩余 {round(left_sec/86400,1)} 天（总额度 {round(assign_sec/86400,1)} 天）")
        if len(lines) > 1:
            return "\n".join(lines)
        return f"{target_name} 的假期余额均为 0"
    except Exception as e:
        logger.warning("Subordinate balance query failed: %s", e)
        return f"查询 {target_name} 假期余额失败：{e}"

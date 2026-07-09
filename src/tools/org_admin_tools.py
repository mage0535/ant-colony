from __future__ import annotations

from typing import Any


def _resolve_user_id(args: dict[str, Any]) -> str:
    return str(args.get("user_id") or args.get("from") or args.get("_context_user_id") or "")


def attendance_tool(args: dict[str, Any]) -> str:
    from src.tools.attendance_tool import query_attendance

    return query_attendance(_resolve_user_id(args), int(args.get("days", 7)))


def leave_tool(args: dict[str, Any]) -> str:
    from src.tools.attendance_tool import query_attendance

    return query_attendance(_resolve_user_id(args), int(args.get("days", 30)), query_type="leave")


def leave_balance_tool(args: dict[str, Any]) -> str:
    from src.tools.attendance_tool import query_leave_balance

    return query_leave_balance(_resolve_user_id(args))


def dept_attendance_tool(args: dict[str, Any]) -> str:
    from src.tools.dept_tool import query_subordinates

    return query_subordinates(_resolve_user_id(args), "all", int(args.get("days", 7)))


def subordinate_tool(args: dict[str, Any]) -> str:
    from src.tools.dept_tool import query_subordinate_by_name

    return query_subordinate_by_name(
        _resolve_user_id(args),
        args.get("name", ""),
        args.get("type", "all"),
        int(args.get("days", 7)),
    )


def subordinate_balance_tool(args: dict[str, Any]) -> str:
    from src.tools.dept_tool import query_subordinate_balance

    return query_subordinate_balance(_resolve_user_id(args), args.get("name", ""))


def add_admin_tool(args: dict[str, Any]) -> str:
    from src.knowledge.acl import Role, resolve_role
    from src.platform.admin_registry import add_admin, get_admin_ids
    from src.platform.api_wecom import _get

    name = args.get("name", "")
    platform = args.get("platform", "wecom")
    from_user = args.get("from", "")
    if not name:
        return "请提供要添加的管理员姓名"
    current_admins = get_admin_ids(platform)
    role = resolve_role(from_user)
    if current_admins and role < Role.admin:
        return "权限不足：仅管理员可添加管理员。请先联系现有管理员添加。"
    try:
        dept_resp = _get("department/list")
        for dept in dept_resp.get("department", []):
            users = _get("user/list", f"department_id={dept['id']}&fetch_child=1")
            for user in users.get("userlist", []):
                if user.get("name", "") == name:
                    add_admin(platform, user["userid"], name, from_user)
                    return f"已添加 {name} 为企业管理员"
        return f"未找到员工: {name}"
    except Exception as exc:
        return f"添加失败: {exc}"


def remove_admin_tool(args: dict[str, Any]) -> str:
    from src.platform.admin_registry import list_admins, remove_admin

    name = args.get("name", "")
    platform = args.get("platform", "wecom")
    if not name:
        return "请提供要移除的管理员姓名"
    for admin in list_admins(platform):
        if admin["name"] == name or admin["user_id"] == name:
            remove_admin(platform, admin["user_id"])
            return f"已移除管理员: {name}"
    return f"未找到管理员: {name}"

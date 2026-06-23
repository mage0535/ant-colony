from __future__ import annotations
from typing import Any


def select_role_tool(args: dict[str, Any]) -> str:
    try:
        from src.platform.role_manager import select_role

        query = args.get("query", "")
        if not query:
            return ""
        result = select_role(query)
        role = result["role"]
        output = role.name
        if role.content:
            output += "\n\n" + role.content[:2000]
        return output
    except Exception:
        return ""


def list_roles_tool(args: dict[str, Any]) -> str:
    from src.platform.role_manager import list_categories, list_roles

    category = args.get("category", "")
    if category:
        roles = list_roles(category)
        title = f"{category} 类角色 ({len(roles)} 个):"
    else:
        categories = list_categories()
        roles = list_roles()
        title = f"全部 {len(roles)} 个角色（按领域分类）:"
    lines = [title]
    for role in roles:
        tags = ", ".join(role.tags[:4])
        lines.append(f"  **{role.name}** — {role.description} [{tags}]")
    if not category:
        lines.append(f"\n领域: {', '.join(categories)}")
    return "\n".join(lines)


def set_role_tool(args: dict[str, Any]) -> str:
    from src.platform.role_manager import get_role

    name = args.get("name", "")
    if not name:
        return "请指定角色名称"
    role = get_role(name)
    if not role:
        return f"未找到角色 '{name}'，请使用 list_roles 查看可用角色"
    lines = [f"已切换到 **{role.name}** ({role.category})"]
    if role.content:
        lines.append(f"\n=== 角色定义: {role.name} ===\n{role.content[:2000]}")
    return "\n".join(lines)


def office_hours_tool(args: dict[str, Any]) -> str:
    from src.tools.gstack_skills import office_hours

    return office_hours(goal=args.get("goal", ""), context=args.get("context", ""))


def review_doc_tool(args: dict[str, Any]) -> str:
    from src.tools.gstack_skills import review_doc

    return review_doc(doc_type=args.get("type", "general"), content=args.get("content", ""))


def investigate_tool(args: dict[str, Any]) -> str:
    from src.tools.gstack_skills import investigate

    return investigate(issue=args.get("issue", ""), context=args.get("context", ""))


def spec_tool_handler(args: dict[str, Any]) -> str:
    from src.tools.gstack_skills import spec_tool

    return spec_tool(goal=args.get("goal", ""))


def retro_tool(args: dict[str, Any]) -> str:
    from src.tools.gstack_skills import retro_tool

    return retro_tool(period=args.get("period", "本周"), data=args.get("data", ""))

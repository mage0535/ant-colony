from __future__ import annotations

import json
import uuid
from typing import Any


def search_knowledge_tool(args: dict[str, Any]) -> str:
    from src.knowledge.repository_factory import build_knowledge_repository

    repo = build_knowledge_repository()
    query = str(args.get("query", ""))
    if not query:
        return "请提供搜索关键词 (query)"
    user_id = args.get("user_id", "*")
    results = repo.search_accessible(query, user_id, limit=5) if user_id and user_id != "*" else repo.search(query, limit=5)
    if not results:
        return f"未找到关于 '{query}' 的知识条目"
    lines = [f"搜索 '{query}' 找到 {len(results)} 条结果:"]
    for result in results:
        title = str(result.metadata.get("title", "")).strip() or result.content.splitlines()[0][:60]
        lines.append(f"  [{result.owner_type.value}] {title}")
    return "\n".join(lines)


def list_knowledge_tool(args: dict[str, Any]) -> str:
    from src.knowledge.contracts import KnowledgeOwnerType
    from src.knowledge.repository_factory import build_knowledge_repository

    repo = build_knowledge_repository()
    user_id = args.get("user_id", "")
    owner_type = args.get("owner_type", "")
    owner_id = args.get("owner_id", "")
    if user_id:
        results = repo.list_accessible(user_id)
    elif owner_type and owner_id:
        try:
            resolved_owner_type = KnowledgeOwnerType(owner_type)
        except ValueError:
            return f"无效 owner_type: {owner_type}"
        results = repo.list_for_owner(resolved_owner_type, owner_id)
    else:
        results = repo.list_for_owner(KnowledgeOwnerType.ORGANIZATION, "*")
    if not results:
        return "知识库为空"
    lines = [f"知识条目 ({len(results)} 条):"]
    for result in results[:20]:
        title = str(result.metadata.get("title", "")).strip() or result.content.splitlines()[0][:60]
        lines.append(f"  [{result.owner_type.value}] {title}")
    return "\n".join(lines)


def add_document_tool(args: dict[str, Any]) -> str:
    from src.knowledge.acl import Role, resolve_role
    from src.knowledge.collector import _acl_for_owner_type
    from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
    from src.knowledge.repository_factory import build_knowledge_repository

    scope = args.get("scope", "personal")
    user_id = args.get("user_id", "")
    title = args.get("title", "未命名文档")
    content = args.get("content", "")
    owner_id = args.get("owner_id", "")
    if not user_id:
        return "请提供用户ID"
    if not content:
        return "请提供文档内容"
    role = resolve_role(user_id)
    scope_requirements: dict[str, Role] = {
        "company": Role.leader,
        "department": Role.leader,
        "project": Role.member,
        "personal": Role.self,
    }
    required_role = scope_requirements.get(scope, Role.self)
    if role < required_role:
        return f"权限不足：当前角色 {role.name}，添加 '{scope}' 范围文档需要 {required_role.name} 权限"
    scope_type_map = {
        "company": "organization",
        "department": "department",
        "project": "project",
        "personal": "personal",
    }
    owner_type_str = scope_type_map.get(scope, "personal")
    owner_type = KnowledgeOwnerType(owner_type_str)
    resolved_owner_id = owner_id or (user_id if scope == "personal" else "*")
    read_roles, write_roles = _acl_for_owner_type(owner_type_str)
    repo = build_knowledge_repository()
    entry = KnowledgeEntry(
        id=str(uuid.uuid4()),
        owner_type=owner_type,
        owner_id=resolved_owner_id,
        content=content,
        tags=[title],
        metadata={"title": title, "added_by": user_id, "scope": scope},
        read_roles=read_roles,
        write_roles=write_roles,
    )
    repo.save(entry)
    return f"文档 '{title}' 已添加到知识库（归属：{scope}）"


def register_cloud_drive_tool(args: dict[str, Any]) -> str:
    from src.knowledge.cloud_drive import register_drive

    config = args.get("config", "{}")
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            config = {}
    try:
        drive_id = register_drive(
            name=args.get("name", ""),
            driver_type=args.get("driver_type", ""),
            config=config,
            scope=args.get("scope", "organization"),
            scope_id=args.get("scope_id", "*"),
            rclone_remote=args.get("rclone_remote", ""),
            user_id=args.get("user_id", ""),
        )
        return f"云盘 '{args.get('name')}' 已注册 (ID: {drive_id})"
    except (PermissionError, ValueError) as exc:
        return str(exc)


def list_cloud_drives_tool(args: dict[str, Any]) -> str:
    from src.platform import invoke_capability

    return invoke_capability("drive.list", empty_message="暂无可用云盘列表能力")


def sync_from_cloud_tool(args: dict[str, Any]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "drive.sync",
        args.get("drive_id", ""),
        args.get("remote_path", ""),
        args.get("local_path", ""),
        context={"user_id": args.get("user_id", ""), "scope": args.get("scope", ""), "scope_id": args.get("scope_id", "")},
        empty_message="暂无可用云盘同步能力",
    )


def delete_cloud_drive_tool(args: dict[str, Any]) -> str:
    from src.knowledge.cloud_drive import delete_drive

    try:
        deleted = delete_drive(args.get("drive_id", ""), user_id=args.get("user_id", ""))
        return "云盘已删除" if deleted else "云盘不存在"
    except PermissionError as exc:
        return str(exc)


def promote_knowledge_tool(args: dict[str, Any]) -> str:
    from src.knowledge.contracts import KnowledgeOwnerType
    from src.knowledge.repository_factory import build_knowledge_repository
    from src.knowledge.service import KnowledgeService

    entry_id = str(args.get("entry_id", ""))
    target_scope = str(args.get("target_scope", "department"))
    target_id = str(args.get("target_id", ""))
    if not entry_id or not target_id:
        return "请提供 entry_id 和 target_id"

    repo = build_knowledge_repository()
    service = KnowledgeService(repo)
    entry = repo.get(entry_id)
    if entry is None:
        return f"未找到知识条目：{entry_id}"

    scope_map = {
        "personal": KnowledgeOwnerType.PERSONAL,
        "project": KnowledgeOwnerType.PROJECT,
        "department": KnowledgeOwnerType.DEPARTMENT,
        "organization": KnowledgeOwnerType.ORGANIZATION,
    }
    owner_type = scope_map.get(target_scope, KnowledgeOwnerType.DEPARTMENT)
    promoted = service.promote_entry(
        entry,
        target_owner_type=owner_type,
        target_owner_id=target_id,
        new_entry_id=f"{entry.id}-promoted-{target_scope}",
        extra_tags=["promoted"],
    )
    return f"已将知识条目 {entry_id} 升级为 {target_scope}/{target_id}（新ID: {promoted.id}）"


def update_knowledge_tool(args: dict[str, Any]) -> str:
    from src.knowledge.repository_factory import build_knowledge_repository

    entry_id = str(args.get("entry_id", ""))
    new_content = str(args.get("content", ""))
    if not entry_id or not new_content:
        return "请提供 entry_id 和 content"

    repo = build_knowledge_repository()
    entry = repo.get(entry_id)
    if entry is None:
        return f"未找到知识条目：{entry_id}"

    title = str(args.get("title", "")).strip()
    tags = args.get("tags")
    if isinstance(tags, str):
        tags = [part.strip() for part in tags.split(",") if part.strip()]
    if not isinstance(tags, list):
        tags = entry.tags

    entry.content = f"{title}\n\n{new_content}" if title else new_content
    entry.tags = list(tags)
    if title:
        entry.metadata["title"] = title
    repo.save(entry)
    return f"已更新知识条目：{entry_id}"


def delete_knowledge_tool(args: dict[str, Any]) -> str:
    from src.knowledge.repository_factory import build_knowledge_repository

    entry_id = str(args.get("entry_id", ""))
    user_id = str(args.get("user_id", ""))
    if not entry_id:
        return "请提供 entry_id"
    deleted = build_knowledge_repository().delete(entry_id, user_id=user_id)
    return f"已删除知识条目：{entry_id}" if deleted else f"删除失败或未找到知识条目：{entry_id}"


def import_company_guides_tool(args: dict[str, Any]) -> str:
    del args
    from src.knowledge.company_guides import import_company_guides
    from src.knowledge.repository_factory import build_knowledge_repository

    entries = import_company_guides(build_knowledge_repository())
    titles = [str(item.metadata.get("title", item.id)) for item in entries]
    return f"已导入 {len(entries)} 份公司级说明书到 organization/company 知识库：\n" + "\n".join(f"- {title}" for title in titles)

from __future__ import annotations

import json
import re
import uuid
from typing import Any


_SEARCH_STOPWORDS = {
    "我", "想", "让", "其他", "同事", "也", "类似", "你的", "员工", "应该", "怎么", "如何", "操作",
    "方法", "请问", "一下", "一下子", "这个", "那个", "有关", "相关", "接入", "使用", "帮我", "查", "搜索",
}
_GUIDE_KEYWORDS = {
    "企业微信", "企微", "AI", "ai", "机器人", "助手", "激活", "说明书", "指南", "知识库", "权限", "模板", "文档", "流程", "管理",
}
_OWNER_TYPE_LABELS = {
    "organization": "公司",
    "department": "部门",
    "project": "项目",
    "personal": "个人",
}


def owner_type_label(owner_type: str) -> str:
    return _OWNER_TYPE_LABELS.get(owner_type, owner_type)


def _candidate_queries(query: str) -> list[str]:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", query).strip()
    if not text:
        return []
    tokens = [part.strip() for part in text.split() if part.strip()]
    candidates: list[str] = [query.strip()]

    keyword_hits = [word for word in _GUIDE_KEYWORDS if word.lower() in text.lower()]
    if keyword_hits:
        candidates.append(" ".join(sorted(dict.fromkeys(keyword_hits), key=lambda item: len(item), reverse=True)[:6]))

    meaningful_tokens = [
        token for token in tokens
        if token not in _SEARCH_STOPWORDS and len(token) >= 2
    ]
    if meaningful_tokens:
        candidates.append(" ".join(meaningful_tokens[:6]))
        candidates.extend(meaningful_tokens[:6])

    unique: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def search_knowledge_entries(query: str, *, user_id: str = "", space_id: str = "", limit: int = 5):
    from src.knowledge.contracts import KnowledgeOwnerType
    from src.knowledge.repository_factory import build_knowledge_repository

    repo = build_knowledge_repository()
    merged = []
    seen_ids: set[str] = set()
    for candidate in _candidate_queries(query):
        results = repo.search_accessible(candidate, user_id=user_id, space_id=space_id, limit=limit) if user_id and user_id != "*" else repo.search(candidate, limit=limit)
        for result in results:
            if result.id in seen_ids:
                continue
            seen_ids.add(result.id)
            merged.append(result)
            if len(merged) >= limit:
                return merged
    if merged:
        return merged

    try:
        visible_entries = repo.list_accessible(user_id=user_id, limit=200) if user_id and user_id != "*" else repo.list_for_owner(KnowledgeOwnerType.ORGANIZATION, "*")
    except Exception:
        visible_entries = []

    tokens = []
    for candidate in _candidate_queries(query):
        tokens.extend([part for part in re.split(r"[^\w\u4e00-\u9fff]+", candidate) if part.strip()])
    normalized_tokens = [token for token in dict.fromkeys(tokens) if token not in _SEARCH_STOPWORDS and len(token) >= 2]

    scored = []
    for entry in visible_entries:
        title = str(entry.metadata.get("title", ""))
        haystack = f"{title}\n{' '.join(entry.tags)}\n{entry.content[:4000]}"
        score = 0
        for token in normalized_tokens:
            if token in title:
                score += 5
            elif token in " ".join(entry.tags):
                score += 3
            elif token in haystack:
                score += 1
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored[:limit]]


def search_knowledge_tool(args: dict[str, Any]) -> str:
    from src.knowledge.linking import build_knowledge_open_url

    query = str(args.get("query", ""))
    if not query:
        return "请提供搜索关键词 (query)"
    user_id = args.get("user_id", "*")
    space_id = str(args.get("space_id", ""))
    results = search_knowledge_entries(query, user_id=str(user_id), space_id=space_id, limit=5)
    if not results:
        return f"未找到关于 '{query}' 的知识条目"
    lines = [f"搜索 '{query}' 找到 {len(results)} 条结果:"]
    for result in results:
        title = str(result.metadata.get("title", "")).strip() or result.content.splitlines()[0][:60]
        lines.append(f"  [{owner_type_label(result.owner_type.value)}] {title}")
        lines.append(f"  打开查看：{build_knowledge_open_url(result.id)}")
    return "\n".join(lines)


def list_knowledge_tool(args: dict[str, Any]) -> str:
    from src.knowledge.contracts import KnowledgeOwnerType
    from src.knowledge.linking import build_knowledge_open_url
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
        lines.append(f"  [{owner_type_label(result.owner_type.value)}] {title}")
        lines.append(f"  打开查看：{build_knowledge_open_url(result.id)}")
    return "\n".join(lines)


def add_document_tool(args: dict[str, Any]) -> str:
    from src.knowledge.acl import default_write_scope, may_write, resolve_role
    from src.knowledge.collector import _acl_for_owner_type
    from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
    from src.knowledge.repository_factory import build_knowledge_repository

    scope = str(args.get("scope", "auto") or "auto")
    user_id = args.get("user_id", "")
    title = args.get("title", "未命名文档")
    content = args.get("content", "")
    owner_id = args.get("owner_id", "")
    if not user_id:
        return "请提供用户ID"
    if not content:
        return "请提供文档内容"
    role = resolve_role(user_id)
    scope_type_map = {
        "company": "organization",
        "organization": "organization",
        "department": "department",
        "project": "project",
        "personal": "personal",
    }
    if scope == "auto" or not owner_id:
        owner_type_str, resolved_owner_id = default_write_scope(role, user_id)
    else:
        owner_type_str = scope_type_map.get(scope, "personal")
        resolved_owner_id = owner_id
    if not may_write(role, owner_type_str, resolved_owner_id, user_id):
        return "权限不足：系统已按企业 IM 组织架构校验，你不能写入该知识范围"
    owner_type = KnowledgeOwnerType(owner_type_str)
    read_roles, write_roles = _acl_for_owner_type(owner_type_str)
    repo = build_knowledge_repository()
    entry = KnowledgeEntry(
        id=str(uuid.uuid4()),
        owner_type=owner_type,
        owner_id=resolved_owner_id,
        content=content,
        tags=[title],
        metadata={"title": title, "added_by": user_id, "scope": owner_type_str},
        read_roles=read_roles,
        write_roles=write_roles,
    )
    repo.save(entry)
    return f"文档 '{title}' 已添加到知识库（归属：{owner_type_label(owner_type_str)} / {resolved_owner_id}）"


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
    from src.knowledge.acl import default_write_scope, may_read, may_write, resolve_role
    from src.knowledge.contracts import KnowledgeOwnerType
    from src.knowledge.repository_factory import build_knowledge_repository
    from src.knowledge.service import KnowledgeService

    entry_id = str(args.get("entry_id", ""))
    target_scope = str(args.get("target_scope", "auto") or "auto")
    target_id = str(args.get("target_id", ""))
    user_id = str(args.get("user_id", ""))
    if not entry_id:
        return "请提供 entry_id"
    if not user_id:
        return "请提供用户ID"

    repo = build_knowledge_repository()
    service = KnowledgeService(repo)
    entry = repo.get(entry_id)
    if entry is None:
        return f"未找到知识条目：{entry_id}"
    role = resolve_role(user_id)
    if not may_read(role, entry.owner_type.value, entry.owner_id, user_id):
        return "权限不足：你不能读取该知识条目"

    scope_map = {
        "personal": KnowledgeOwnerType.PERSONAL,
        "project": KnowledgeOwnerType.PROJECT,
        "department": KnowledgeOwnerType.DEPARTMENT,
        "organization": KnowledgeOwnerType.ORGANIZATION,
    }
    if target_scope == "auto" or not target_id:
        target_owner_type_str, target_id = default_write_scope(role, user_id)
        owner_type = KnowledgeOwnerType(target_owner_type_str)
    else:
        owner_type = scope_map.get(target_scope, KnowledgeOwnerType.DEPARTMENT)
    if not may_write(role, owner_type.value, target_id, user_id):
        return "权限不足：系统已按企业 IM 组织架构校验，你不能升级到该知识范围"
    promoted = service.promote_entry(
        entry,
        target_owner_type=owner_type,
        target_owner_id=target_id,
        new_entry_id=f"{entry.id}-promoted-{target_scope}",
        extra_tags=["promoted"],
    )
    return f"已将知识条目 {entry_id} 升级为 {owner_type_label(owner_type.value)} / {target_id}（新ID: {promoted.id}）"


def update_knowledge_tool(args: dict[str, Any]) -> str:
    from src.knowledge.acl import may_write, resolve_role
    from src.knowledge.repository_factory import build_knowledge_repository

    entry_id = str(args.get("entry_id", ""))
    new_content = str(args.get("content", ""))
    user_id = str(args.get("user_id", ""))
    if not entry_id or not new_content:
        return "请提供 entry_id 和 content"
    if not user_id:
        return "请提供用户ID"

    repo = build_knowledge_repository()
    entry = repo.get(entry_id)
    if entry is None:
        return f"未找到知识条目：{entry_id}"
    role = resolve_role(user_id)
    if not may_write(role, entry.owner_type.value, entry.owner_id, user_id):
        return "权限不足：你不能编辑该知识条目"

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
    from src.knowledge.acl import Role, resolve_role
    from src.knowledge.company_guides import import_company_guides
    from src.knowledge.repository_factory import build_knowledge_repository

    user_id = str(args.get("user_id", ""))
    if not user_id:
        return "请提供用户ID"
    if resolve_role(user_id) < Role.admin:
        return "权限不足：公司级说明书只能由企业 IM 管理员导入"
    entries = import_company_guides(build_knowledge_repository())
    titles = [str(item.metadata.get("title", item.id)) for item in entries]
    return f"已导入 {len(entries)} 份公司级说明书到公司知识库：\n" + "\n".join(f"- {title}" for title in titles)

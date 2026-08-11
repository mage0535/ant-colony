from __future__ import annotations

from pathlib import Path

from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

_GUIDE_FILES = [
    (
        "company-guide-user-manual",
        "企业 AI 助手使用总入口",
        "docs/user-manual.md",
        [
            "guide",
            "manual",
            "user-manual",
            "ai助手",
            "企业AI助手",
            "使用总入口",
            "功能说明",
            "功能操作",
            "逐步操作",
            "详细步骤",
            "使用步骤",
            "错误处理",
            "常见错误",
            "没回复",
            "没有反应",
            "不会用",
            "怎么用",
            "如何操作",
            "使用说明",
            "公共数据",
            "公共数据订阅",
            "天气提醒",
            "空气质量提醒",
            "汇率提醒",
            "流程通知",
            "流程状态变更",
            "审批流程自动通知",
            "知识库搜索",
            "文档分析",
            "模板生成",
            "任务管理",
            "通讯录搜索",
            "日程查询",
            "会议室查询",
            "邮箱未读统计",
            "货运",
            "航班",
            "航班数据源",
            "航班查询",
            "航班API",
            "航班接口",
            "供应链价格",
            "供应链价格数据源",
            "金属价格",
            "镍价格",
            "铬价格",
            "数据源管理",
            "公共数据源管理",
            "填入推荐模板",
            "授权API",
            "互联网检索",
            "联网搜索",
            "网页读取",
            "信息源发现",
            "RSS发现",
            "SearXNG",
            "Jina",
            "公开信息调研",
        ],
    ),
    (
        "company-guide-wecom-activation",
        "企业微信 AI 助手激活说明书",
        "docs/wecom-ai-assistant-activation-guide.md",
        ["guide", "manual", "wecom", "activation", "ai助手", "企业微信", "机器人", "激活"],
    ),
    (
        "company-guide-wecom-features",
        "企业微信 AI 助手功能与操作说明书",
        "docs/wecom-ai-assistant-feature-guide.md",
        ["guide", "manual", "wecom", "feature", "usage", "ai助手", "企业微信", "功能", "操作", "说明书"],
    ),
    (
        "company-guide-knowledge-base",
        "企业知识库分级建设与管理说明书",
        "docs/knowledge-base-operations-guide.md",
        ["guide", "manual", "knowledge", "knowledge-base", "管理", "知识库", "说明书", "company", "organization"],
    ),
    (
        "company-guide-role-operation-leave-approval",
        "企业 AI 助手审批假期与流程通知分角色操作说明书",
        "docs/role-operation-guide-leave-approval-ai-assistant.md",
        [
            "guide",
            "manual",
            "role-operation",
            "审批假期",
            "请假",
            "加班",
            "调休",
            "假期额度",
            "人事专员",
            "管理员",
            "普通员工",
            "流程通知",
            "审批状态",
            "负数假期",
            "WeCom",
            "企业微信",
        ],
    ),
]


def build_company_guide_entries() -> list[KnowledgeEntry]:
    project_root = Path(__file__).resolve().parents[2]
    entries: list[KnowledgeEntry] = []
    for entry_id, title, relative_path, tags in _GUIDE_FILES:
        path = project_root / relative_path
        content = path.read_text(encoding="utf-8")
        normalized_content = f"{title}\n\n关键词：{' '.join(tags)}\n\n{content}"
        entries.append(
            KnowledgeEntry(
                id=entry_id,
                owner_type=KnowledgeOwnerType.ORGANIZATION,
                owner_id="*",
                content=normalized_content,
                tags=tags,
                metadata={
                    "title": title,
                    "source_type": "builtin_company_guide",
                    "source_path": relative_path,
                    "stable": True,
                },
                read_roles=["*"],
                write_roles=["admin"],
            )
        )
    return entries


def import_company_guides(repo) -> list[KnowledgeEntry]:
    entries = build_company_guide_entries()
    saved: list[KnowledgeEntry] = []
    for entry in entries:
        saved.append(repo.save(entry))
    return saved

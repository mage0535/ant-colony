from __future__ import annotations

import re
from typing import Any

from src.models.contracts import AgentResponse, MessageContext


def run_phase1_shortcut(user_id: str, text: str, context: MessageContext) -> AgentResponse | None:
    """Deterministic Bot entries for mature Phase 1 office capabilities."""
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return None

    if _looks_simple_greeting(normalized):
        return AgentResponse(text="你好，我在。你可以直接告诉我要处理的事情，例如查资料、汇总邮件、查询审批、打开知识库、生成文档或起草回复。")

    if _looks_capability_overview(normalized):
        return AgentResponse(text=_phase1_capability_overview())

    args = _base_args(user_id, context)

    if _looks_explicit_knowledge_search(normalized):
        from src.tools.knowledge_tools import search_knowledge_tool

        query = _strip_words(
            normalized,
            ("搜索知识库", "查知识库", "查询知识库", "知识库搜索", "知识库查询", "搜知识库", "查找知识库"),
        )
        return AgentResponse(text=search_knowledge_tool({**args, "query": query or normalized}))

    if _looks_contact_search(normalized):
        from src.tools.basic_tool_modules import contact_search_tool

        query = _extract_contact_query(normalized)
        return AgentResponse(text=contact_search_tool({**args, "query": query or normalized}))

    if _looks_calendar_lookup(normalized):
        from src.tools.basic_tool_modules import calendar_agenda_tool

        return AgentResponse(text=calendar_agenda_tool({**args, "days": _extract_days(normalized)}))

    if _looks_leave_application_or_balance(normalized):
        return AgentResponse(text=_leave_application_or_balance_reply(args))

    if _looks_mail_reply_drafting(normalized):
        return AgentResponse(text=_mail_reply_drafting_reply())

    if _looks_mail_summary(normalized):
        from src.tools.platform_capability_tools import mail_summary_tool

        query = _strip_words(normalized, ("邮件", "邮箱", "摘要", "汇总", "总结", "今天", "最近", "帮我", "查询", "查看"))
        return AgentResponse(text=mail_summary_tool({**args, "query": query}))

    if _looks_unified_search(normalized):
        from src.platform.unified_search_service import search_workspace

        query = _strip_words(normalized, ("统一搜索", "综合搜索", "全局搜索", "帮我搜索", "搜索"))
        return AgentResponse(text=search_workspace(user_id=user_id, platform=str(args["platform"]), query=query or normalized))

    subscription_response = _run_subscription_shortcut(normalized, args)
    if subscription_response:
        return AgentResponse(text=subscription_response)

    task_response = _run_task_shortcut(normalized, args)
    if task_response:
        return AgentResponse(text=task_response)

    return None


def _base_args(user_id: str, context: MessageContext) -> dict[str, Any]:
    metadata = dict(context.metadata or {})
    return {
        "user_id": user_id,
        "from": user_id,
        "platform": str(metadata.get("provider") or metadata.get("platform") or "wecom"),
        "_source_provider": str(metadata.get("provider") or metadata.get("platform") or "wecom"),
        "_source_transport": str(metadata.get("transport") or ""),
        "scope": context.space_type.value if hasattr(context.space_type, "value") else str(context.space_type),
        "scope_id": context.space_id,
        "dept_id": context.dept_id or "",
        "project_id": context.project_id or "",
        "source_chat_id": str(metadata.get("source_chat_id") or ""),
    }


def _looks_capability_overview(text: str) -> bool:
    direct = {
        "你能做什么",
        "你有哪些功能",
        "功能介绍",
        "办公功能",
        "企业AI助手功能",
        "企业 AI 助手功能",
        "阶段一功能",
    }
    return text in direct or ("能做什么" in text and "AI" in text.upper())


def _looks_simple_greeting(text: str) -> bool:
    normalized = re.sub(r"[。！!？?，,\s]+", "", text).lower()
    return normalized in {"你好", "您好", "在吗", "在不在", "hello", "hi", "hey"}


def _phase1_capability_overview() -> str:
    return (
        "企业 AI 助手当前已落地的高频办公能力：\n"
        "1. 知识库问答：例如“搜索知识库 车间通行制度”。\n"
        "2. 文档生成和制度起草：例如“帮我起草一份会议管理办法”。\n"
        "3. 任务闭环：例如“创建任务 本周完成设备巡检”“查询任务列表”。\n"
        "4. 通讯录搜索：例如“找张三联系方式”“通讯录搜索 生产部负责人”。\n"
        "5. 日程和会议协同：例如“查今天日程”“安排一次部门会议”。\n"
        "6. 邮件摘要：例如“汇总今天邮件”“查找合同相关邮件”。\n"
        "7. 企业应用查询：例如“查询我所有审批的状态”“三号会议室有人申请吗”。\n\n"
        "如果某项能力提示未配置，说明对应企业应用权限或后端凭据尚未开通；这不是员工操作错误。"
    )


def _looks_explicit_knowledge_search(text: str) -> bool:
    return "知识库" in text and any(word in text for word in ("搜索", "查询", "查找", "查", "搜"))


def _looks_contact_search(text: str) -> bool:
    if any(word in text for word in ("通讯录", "联系人", "联系方式", "手机号", "电话", "找人")):
        return any(word in text for word in ("查", "找", "搜索", "查询", "看看", "谁"))
    return bool(re.match(r"^找[\u4e00-\u9fffA-Za-z0-9_ -]{2,30}(?:联系方式|电话|手机号)?$", text))


def _extract_contact_query(text: str) -> str:
    query = _strip_words(
        text,
        ("通讯录", "联系人", "联系方式", "手机号", "电话", "找人", "搜索", "查询", "查找", "查看", "帮我", "找"),
    )
    query = re.sub(r"(的)?(联系方式|手机号|电话)$", "", query).strip()
    return query


def _looks_calendar_lookup(text: str) -> bool:
    if "会议室" in text:
        return False
    calendar_words = ("日程", "日历", "安排", "行程")
    query_words = ("查", "查询", "查看", "今天", "明天", "本周", "最近", "有哪些", "列表")
    return any(word in text for word in calendar_words) and any(word in text for word in query_words)


def _looks_leave_application_or_balance(text: str) -> bool:
    if any(word in text for word in ("请假记录", "审批记录", "流程状态", "审批状态", "我的审批", "我的申请")):
        return False
    leave_terms = ("请假", "休假", "年假", "病假", "事假", "调休", "假期", "欠假", "欠休")
    balance_terms = ("余额", "剩余", "还剩", "剩几天", "几天假", "可申请", "可用", "欠")
    application_terms = ("我要", "想", "准备", "打算", "怎么", "如何", "申请", "发起", "提交", "请假前", "休假前")
    return any(term in text for term in leave_terms) and (
        any(term in text for term in balance_terms) or any(term in text for term in application_terms)
    )


def _leave_application_or_balance_reply(args: dict[str, Any]) -> str:
    from src.platform.leave_quota_service import build_employee_leave_form_notice

    try:
        notice = build_employee_leave_form_notice(platform=str(args.get("platform") or "wecom"), user_id=str(args["user_id"]))
    except Exception as exc:
        notice = f"暂时没有读取到你的实时假期余额，原因：{exc}。请稍后再试，或联系人事专员核对。"
    return (
        f"{notice}\n\n"
        "请假操作建议：\n"
        "1. 先看上面的“真实假期余额提示”，它包含公司后台记录的真实余额、欠假、审批中占用和企微可申请额度。\n"
        "2. 再到企业微信打开“审批 - 请假”，按企微页面正常提交请假申请。\n"
        "3. 如果企微请假页显示可申请额度为 0，但这里提示存在欠假或待冲抵，请先联系人事专员确认，不要反复提交。\n"
        "4. 企微请假表单里的说明字段是模板静态说明；你的个人动态余额以 AI 助手这里返回的内容和人事后台台账为准。"
    )


def _looks_mail_reply_drafting(text: str) -> bool:
    return any(word in text for word in ("回邮", "回复邮件", "回邮件", "邮件回复", "帮我回", "代回邮件"))


def _mail_reply_drafting_reply() -> str:
    return (
        "可以帮你起草回邮内容，但我不会替你直接发送邮件或代你回复邮件。\n\n"
        "你可以这样操作：\n"
        "1. 如果是刚收到的新邮件，直接说“帮我起草回复上一封邮件”。\n"
        "2. 如果有多封邮件，先说“汇总今天邮件”，再告诉我要回复哪一封。\n"
        "3. 你也可以把邮件内容粘贴给我，并说明回复口径，例如“语气正式、确认收到、下午给进度”。\n\n"
        "我会帮你整理一段可复制到邮箱里的中文或英文回复。"
    )


def _looks_mail_summary(text: str) -> bool:
    return any(word in text for word in ("邮件", "邮箱")) and any(
        word in text for word in ("摘要", "汇总", "总结", "查", "查询", "搜索", "今天", "最近")
    )


def _looks_unified_search(text: str) -> bool:
    return any(marker in text for marker in ("统一搜索", "综合搜索", "全局搜索"))


def _run_subscription_shortcut(text: str, args: dict[str, Any]) -> str:
    from src.platform.public_data_service import create_subscription, delete_subscription, list_subscriptions, set_subscription_enabled

    user_id = str(args["user_id"])
    platform = str(args["platform"])
    if any(marker in text for marker in ("查看我的订阅", "查询我的订阅", "订阅列表")):
        subscriptions = list_subscriptions(user_id=user_id, platform=platform)
        if not subscriptions:
            return "你还没有公共数据订阅。可以说“订阅天气 上海”或“订阅汇率 USD/CNY”。"
        lines = ["【我的公共数据订阅】"]
        for item in subscriptions:
            status = "已启用" if item["enabled"] else "已暂停"
            lines.append(f"{item['id']}：{item['kind']} {item['query']}，{status}，频率 {item['schedule']}")
        return "\n".join(lines)
    match = re.match(r"^(暂停|恢复|删除)订阅\s+([A-Za-z0-9_-]+)$", text)
    if match:
        action, sub_id = match.groups()
        try:
            if action == "删除":
                result = delete_subscription(sub_id, actor_user_id=user_id)
                return "订阅已删除。" if result["deleted"] else "未找到该订阅。"
            result = set_subscription_enabled(sub_id, action == "恢复", actor_user_id=user_id)
            return "订阅已恢复。" if result["enabled"] else "订阅已暂停。"
        except PermissionError:
            return "你只能管理自己的订阅。"
        except ValueError:
            return "未找到该订阅，请先发送“查看我的订阅”确认编号。"
    match = re.match(r"^订阅(天气|空气质量|汇率|节假日|新闻|RSS)\s*(.*)$", text, flags=re.I)
    if match:
        label, query = match.groups()
        kind = {"天气": "weather", "空气质量": "air_quality", "汇率": "exchange_rate", "节假日": "holiday", "新闻": "rss", "RSS": "rss"}[label]
        result = create_subscription(platform=platform, user_id=user_id, kind=kind, query=query.strip(), schedule="every 1d")
        return f"已创建订阅：{label} {query.strip() or '默认内容'}。订阅编号：{result['id']}。默认每天检查一次；可发送“查看我的订阅”管理。"
    return ""


def _run_task_shortcut(text: str, args: dict[str, Any]) -> str:
    if not any(word in text for word in ("任务", "待办事项", "事项")):
        return ""

    if any(word in text for word in ("创建", "新增", "安排", "加一个", "建立")):
        from src.tools.task_tools import create_draft_tool

        title = _strip_words(text, ("创建任务", "新增任务", "安排任务", "创建", "新增", "安排", "加一个", "建立", "任务", "待办事项", "事项"))
        if not title:
            return "请说明要创建的任务标题，例如：创建任务 本周完成设备巡检。"
        return create_draft_tool({**args, "title": title})

    if any(word in text for word in ("列表", "有哪些", "查询", "查看", "我的任务", "任务清单")):
        from src.tools.task_tools import query_tasks_tool

        return query_tasks_tool(args)

    if any(word in text for word in ("搜索", "查找", "找一下")):
        from src.tools.task_tools import search_tasks_tool

        keyword = _strip_words(text, ("搜索任务", "查找任务", "找一下任务", "搜索", "查找", "找一下", "任务"))
        return search_tasks_tool({**args, "keyword": keyword})

    if any(word in text for word in ("完成", "关闭", "取消", "阻塞", "进行中")):
        from src.tools.task_tools import transition_task_tool

        task_id = _extract_task_id(text)
        if not task_id:
            return "请提供任务 ID，例如：完成任务 task-123。"
        return transition_task_tool({**args, "task_id": task_id, "status": _extract_task_status(text)})

    return ""


def _extract_task_id(text: str) -> str:
    match = re.search(r"\btask-[A-Za-z0-9_-]+\b", text, flags=re.I)
    return match.group(0) if match else ""


def _extract_task_status(text: str) -> str:
    if "完成" in text or "关闭" in text:
        return "done"
    if "取消" in text:
        return "cancelled"
    if "阻塞" in text:
        return "blocked"
    return "in_progress"


def _extract_days(text: str) -> int:
    if "今天" in text:
        return 1
    if "明天" in text:
        return 2
    if "本周" in text or "最近" in text:
        return 7
    match = re.search(r"(\d{1,2})\s*天", text)
    if match:
        return max(1, min(int(match.group(1)), 30))
    return 7


def _strip_words(text: str, words: tuple[str, ...]) -> str:
    result = text
    for word in words:
        result = result.replace(word, " ")
    result = re.sub(r"[，。！？:：；;]+", " ", result)
    return re.sub(r"\s+", " ", result).strip()

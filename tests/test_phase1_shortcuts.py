from __future__ import annotations

from unittest.mock import patch

from src.agents.phase1_shortcuts import run_phase1_shortcut
from src.models.contracts import MessageContext, SpaceType


def _context() -> MessageContext:
    return MessageContext(
        space_type=SpaceType.DEPARTMENT,
        space_id="dept-1",
        dept_id="dept-1",
        metadata={"provider": "wecom", "transport": "bot"},
    )


def test_phase1_simple_greeting_is_deterministic() -> None:
    result = run_phase1_shortcut("u1", "你好", _context())

    assert result is not None
    assert "你好，我在" in result.text
    assert "查资料" in result.text


def test_phase1_capability_overview_is_deterministic() -> None:
    result = run_phase1_shortcut("u1", "你能做什么", _context())

    assert result is not None
    assert "知识库问答" in result.text
    assert "文档生成和制度起草" in result.text
    assert "通讯录搜索" in result.text
    assert "企业应用查询" in result.text


def test_phase1_explicit_knowledge_search_uses_knowledge_tool() -> None:
    with patch("src.tools.knowledge_tools.search_knowledge_tool", return_value="知识库结果") as search:
        result = run_phase1_shortcut("u1", "搜索知识库 车间通行制度", _context())

    assert result is not None
    assert result.text == "知识库结果"
    assert search.call_args.args[0]["query"] == "车间通行制度"
    assert search.call_args.args[0]["user_id"] == "u1"


def test_phase1_contact_search_uses_contact_tool() -> None:
    with patch("src.tools.basic_tool_modules.contact_search_tool", return_value="张三 | 13800000000") as search:
        result = run_phase1_shortcut("u1", "找张三联系方式", _context())

    assert result is not None
    assert "张三" in result.text
    assert search.call_args.args[0]["query"] == "张三"


def test_phase1_calendar_lookup_uses_calendar_tool() -> None:
    with patch("src.tools.basic_tool_modules.calendar_agenda_tool", return_value="今天 10:00 部门会") as calendar:
        result = run_phase1_shortcut("u1", "查今天日程", _context())

    assert result is not None
    assert "部门会" in result.text
    assert calendar.call_args.args[0]["days"] == 1


def test_phase1_leave_application_returns_dynamic_employee_notice() -> None:
    with patch(
        "src.platform.leave_quota_service.build_employee_leave_form_notice",
        return_value="【真实假期余额提示】\n年假：可用 3 天；企微可申请额度 3 天",
    ) as notice:
        result = run_phase1_shortcut("u1", "我要请假", _context())

    assert result is not None
    assert "【真实假期余额提示】" in result.text
    assert "企业微信打开“审批 - 请假”" in result.text
    assert "企微请假表单里的说明字段是模板静态说明" in result.text
    assert notice.call_args.kwargs == {"platform": "wecom", "user_id": "u1"}


def test_phase1_leave_balance_query_returns_dynamic_employee_notice() -> None:
    with patch(
        "src.platform.leave_quota_service.build_employee_leave_form_notice",
        return_value="【真实假期余额提示】\n调休假：欠公司 1 天，待后续加班调休冲抵",
    ):
        result = run_phase1_shortcut("u1", "我的调休还剩几天", _context())

    assert result is not None
    assert "调休假：欠公司 1 天" in result.text
    assert "你的个人动态余额以 AI 助手这里返回的内容" in result.text


def test_phase1_mail_summary_uses_mail_tool() -> None:
    with patch("src.tools.platform_capability_tools.mail_summary_tool", return_value="当前有 2 封未读邮件") as mail:
        result = run_phase1_shortcut("u1", "查看未读邮件", _context())

    assert result is not None
    assert result.text == "当前有 2 封未读邮件"
    assert mail.call_args.args[0]["user_id"] == "u1"


def test_phase1_mail_reply_request_drafts_only_and_does_not_call_mail_tool() -> None:
    with patch("src.tools.platform_capability_tools.mail_summary_tool") as mail:
        result = run_phase1_shortcut("u1", "你可以帮我回邮吗", _context())

    assert result is not None
    assert "可以帮你起草回邮内容" in result.text
    assert "不会替你直接发送邮件" in result.text
    mail.assert_not_called()


def test_phase1_task_create_and_query_use_task_tools() -> None:
    with patch("src.tools.task_tools.create_draft_tool", return_value="任务已创建") as create:
        created = run_phase1_shortcut("u1", "创建任务 本周完成设备巡检", _context())

    assert created is not None
    assert created.text == "任务已创建"
    assert create.call_args.args[0]["title"] == "本周完成设备巡检"

    with patch("src.tools.task_tools.query_tasks_tool", return_value="任务列表") as query:
        listed = run_phase1_shortcut("u1", "查询任务列表", _context())

    assert listed is not None
    assert listed.text == "任务列表"
    assert query.call_args.args[0]["user_id"] == "u1"


def test_phase1_task_status_update_requires_task_id() -> None:
    result = run_phase1_shortcut("u1", "完成任务", _context())

    assert result is not None
    assert "请提供任务 ID" in result.text


def test_phase1_task_status_update_uses_transition_tool() -> None:
    with patch("src.tools.task_tools.transition_task_tool", return_value="任务状态已更新") as transition:
        result = run_phase1_shortcut("u1", "完成任务 task-123", _context())

    assert result is not None
    assert result.text == "任务状态已更新"
    assert transition.call_args.args[0]["task_id"] == "task-123"
    assert transition.call_args.args[0]["status"] == "done"

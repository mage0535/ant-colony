from __future__ import annotations

from unittest.mock import patch


def test_single_domain_query_calls_only_meeting_room_capability() -> None:
    from src.platform.enterprise_query_service import execute_enterprise_query

    with patch("src.platform.invoke_capability", return_value="[企业微信] 三号会议室已占用") as invoke:
        result = execute_enterprise_query(
            "三号会议室有人申请吗？",
            {"user_id": "u1", "platform": "wecom"},
        )

    assert "三号会议室已占用" in result
    assert [call.args[0] for call in invoke.call_args_list] == ["meeting.room.query"]


def test_explicit_cross_domain_query_calls_each_requested_domain() -> None:
    from src.platform.enterprise_query_service import execute_enterprise_query

    with patch("src.platform.invoke_capability", return_value="result") as invoke:
        execute_enterprise_query(
            "汇总我今天的会议、审批和日程",
            {"user_id": "u1", "platform": "wecom"},
        )

    assert [call.args[0] for call in invoke.call_args_list] == [
        "meeting.list",
        "approval.list",
        "calendar.list",
    ]


def test_non_application_question_returns_empty_result() -> None:
    from src.platform.enterprise_query_service import execute_enterprise_query

    with patch("src.platform.invoke_capability") as invoke:
        result = execute_enterprise_query(
            "目前车间通行是什么情况",
            {"user_id": "u1", "platform": "wecom"},
        )

    assert result == ""
    invoke.assert_not_called()

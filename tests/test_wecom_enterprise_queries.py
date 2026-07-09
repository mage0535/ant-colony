from __future__ import annotations

from unittest.mock import patch

from src.platform.capability_audit import CapabilityInvocationContext
from src.platform.api_wecom import WeComClient


def test_wecom_domain_secret_prefers_domain_specific_credential(monkeypatch) -> None:
    from src.platform.api_wecom import _resolve_domain_secret

    monkeypatch.setenv("WECOM_SECRET", "generic-secret")
    monkeypatch.setenv("WECOM_APPROVAL_SECRET", "approval-secret")

    assert _resolve_domain_secret("approval") == "approval-secret"
    assert _resolve_domain_secret("unknown") == "generic-secret"


def test_room_query_does_not_call_approval_domain() -> None:
    client = WeComClient()
    with patch.object(client, "query_meeting_room", return_value="三号会议室已占用"), patch.object(
        client, "list_approvals", return_value="付款审批"
    ) as approvals:
        result = client.query_enterprise_apps("三号会议室有人申请吗？")

    assert "三号会议室已占用" in result
    assert "付款审批" not in result
    approvals.assert_not_called()


def test_room_availability_is_computed_from_inventory_minus_bookings() -> None:
    client = WeComClient()
    inventory = {
        "meetingroom_list": [
            {"meetingroom_id": "r1", "name": "一号会议室"},
            {"meetingroom_id": "r2", "name": "三号会议室"},
        ]
    }
    bookings = {
        "booking_list": [
            {
                "room_id": "r2",
                "room_name": "三号会议室",
                "title": "生产例会",
                "start_time": 1893459600,
                "end_time": 1893463200,
            }
        ]
    }
    with patch(
        "src.platform.api_wecom._post_optional",
        return_value=inventory,
    ), patch(
        "src.platform.api_wecom._post_optional_diagnostic",
        side_effect=[(bookings, ""), (None, ""), (None, "")],
    ):
        result = client.query_meeting_room("哪个会议室今天可以申请")

    assert "一号会议室" in result
    assert "可申请" in result
    assert "三号会议室" in result
    assert "已占用时段" in result


def test_approval_query_filters_details_to_current_user() -> None:
    client = WeComClient()
    context = CapabilityInvocationContext(user_id="u1", platform="wecom")
    responses = {
        "oa/getapprovalinfo": {"sp_no_list": ["SP1", "SP2"]},
        "oa/getapprovaldetail:SP1": {
            "info": {
                "sp_no": "SP1",
                "sp_name": "进入车间申请",
                "sp_status": 1,
                "applyer": {"userid": "u1"},
            }
        },
        "oa/getapprovaldetail:SP2": {
            "info": {
                "sp_no": "SP2",
                "sp_name": "付款审批",
                "sp_status": 1,
                "applyer": {"userid": "u2"},
            }
        },
    }

    def fake_post(path, body, **kwargs):
        del kwargs
        if path == "oa/getapprovalinfo":
            return responses[path]
        if path == "oa/getapprovaldetail":
            return responses[f"{path}:{body['sp_no']}"]
        return None

    with patch(
        "src.platform.api_wecom._post_optional_diagnostic",
        return_value=(responses["oa/getapprovalinfo"], ""),
    ), patch("src.platform.api_wecom._post_optional", side_effect=fake_post):
        result = client.list_approvals(
            "所有",
            query="查询我所有审批的状态",
            capability_context=context,
        )

    assert "进入车间申请" in result
    assert "付款审批" not in result


def test_fuzzy_approval_query_matches_relevant_process() -> None:
    client = WeComClient()
    context = CapabilityInvocationContext(user_id="u1", platform="wecom")
    with patch.object(
        client,
        "_load_user_approval_details",
        return_value=[
            {"sp_no": "SP1", "name": "员工进入车间审批流程", "status": "审批中", "applicant": "u1"},
            {"sp_no": "SP2", "name": "付款审批", "status": "审批中", "applicant": "u1"},
        ],
    ):
        result = client.list_approvals(
            "pending",
            query="进入车间申请到哪了",
            capability_context=context,
        )

    assert "员工进入车间审批流程" in result
    assert "付款审批" not in result


def test_accessible_application_catalog_filters_by_current_user() -> None:
    client = WeComClient()
    context = CapabilityInvocationContext(user_id="u1", platform="wecom")
    agents = {
        "agentlist": [
            {
                "agentid": 1,
                "name": "会议室",
                "description": "会议室预订",
                "allow_userinfos": {"user": [{"userid": "u1"}]},
            },
            {
                "agentid": 2,
                "name": "财务系统",
                "description": "付款管理",
                "allow_userinfos": {"user": [{"userid": "u2"}]},
            },
        ]
    }
    with patch("src.platform.api_wecom._get", side_effect=[{"department": []}, agents]):
        result = client.list_accessible_applications(capability_context=context)

    assert "会议室" in result
    assert "财务系统" not in result


def test_approval_permission_failure_is_not_reported_as_empty_data() -> None:
    client = WeComClient()
    context = CapabilityInvocationContext(user_id="u1", platform="wecom")
    with patch(
        "src.platform.api_wecom._post_optional_diagnostic",
        return_value=(None, "WeCom API error 48002: api forbidden"),
    ):
        result = client.list_approvals(
            "all",
            query="查询我所有审批的状态",
            capability_context=context,
        )

    assert "48002" in result
    assert "权限" in result


def test_approval_auth_error_is_rendered_without_raw_developer_details() -> None:
    client = WeComClient()
    context = CapabilityInvocationContext(user_id="u1", platform="wecom")
    with patch(
        "src.platform.api_wecom._post_optional_diagnostic",
        return_value=(
            None,
            "WeCom API error (oa/getapprovalinfo): no approval auth, "
            "hint: [123], more info at https://open.work.weixin.qq.com/devtool/query?e=301055",
        ),
    ):
        result = client.list_approvals(
            "all",
            query="查询我所有审批的状态",
            capability_context=context,
        )

    assert "审批数据读取权限" in result
    assert "http" not in result
    assert "hint" not in result

from __future__ import annotations

from unittest.mock import patch

from src.platform.api_wecom import WeComClient


def test_wecom_document_search_returns_clickable_urls() -> None:
    response = {
        "item_list": [
            {
                "title": "车间管理规定",
                "creator_name": "张三",
                "url": "https://doc.weixin.qq.com/example",
            }
        ]
    }

    with patch("src.platform.api_wecom._post", return_value=response):
        result = WeComClient().search_docs("车间")

    assert result == "车间管理规定 | 创建者: 张三 | https://doc.weixin.qq.com/example"


def test_wecom_query_meeting_room_uses_available_room_payload() -> None:
    room_payload = {
        "meetingroom_list": [
            {"meetingroom_id": 1, "name": "三号会议室", "capacity": 10},
        ]
    }
    approval_info = {"sp_no_list": ["202607200001"]}
    approval_detail = {
        "info": {
            "sp_status": 2,
            "sp_name": "预定会议室",
            "applyer": {"userid": "AdminUser"},
            "apply_time": 1893459600,
            "apply_data": {
                "contents": [
                    {"control": "Selector", "value": {"selector": {"options": [{"value": [{"text": "三号会议室"}]}]}}},
                    {"control": "Text", "value": {"text": "7月20日 周日 14:00-16:00"}},
                    {"control": "Text", "value": {"text": "生产例会"}},
                ]
            },
        }
    }

    def side_effect(path, body=None, secret=None):
        if path == "oa/meetingroom/list":
            return room_payload
        if path == "oa/getapprovalinfo":
            return approval_info
        if path == "oa/getapprovaldetail":
            return approval_detail
        return None

    with patch("src.platform.api_wecom._post_optional", side_effect=side_effect), \
         patch("src.platform.api_wecom._post_optional_diagnostic", return_value=(None, "")):
        result = WeComClient().query_meeting_room("三号会议室有人申请吗")

    assert "三号会议室" in result
    assert "生产例会" in result


def test_wecom_query_enterprise_apps_keeps_room_query_in_room_domain() -> None:
    client = WeComClient()
    with patch.object(client, "query_meeting_room", return_value="三号会议室：09:30-10:30 生产例会"), \
         patch.object(client, "list_approvals", return_value="会议室申请 已通过"), \
         patch.object(client, "get_agenda", return_value="09:30 生产例会"):
        result = client.query_enterprise_apps("三号会议室有人申请吗")

    assert "【会议室】" in result
    assert "会议室申请 已通过" not in result


def test_wecom_list_process_events_extracts_current_handlers_and_summary() -> None:
    info_response = {"sp_no_list": ["202607170001"]}
    detail_response = {
        "info": {
            "sp_no": "202607170001",
            "sp_name": "请假审批",
            "sp_status": 1,
            "apply_time": 1784246400,
            "applyer": {"userid": "u-applicant"},
            "apply_data": {
                "contents": [
                    {"title": [{"text": "请假类型"}], "value": {"text": "年假"}},
                    {"title": [{"text": "请假事由"}], "value": {"text": "家中有事"}},
                ]
            },
            "sp_record": [
                {
                    "details": [
                        {"approver": {"userid": "u-manager"}, "sp_status": 1},
                        {"approver": {"userid": "u-finished"}, "sp_status": 2},
                    ]
                }
            ],
        }
    }

    with patch("src.platform.api_wecom._post_optional_diagnostic", return_value=(info_response, "")), \
         patch("src.platform.api_wecom._post_optional", return_value=detail_response), \
         patch("src.platform.api_wecom._batch_resolve_user_names", return_value={"u-applicant": "申请人"}), \
         patch("src.platform.api_wecom._is_approval_admin", return_value=True):
        events = WeComClient().list_process_events()

    assert len(events) == 1
    event = events[0]
    assert event["source"] == "approval"
    assert event["item_id"] == "202607170001"
    assert event["title"] == "请假审批"
    assert event["applicant_user_id"] == "u-applicant"
    assert event["applicant_name"] == "申请人"
    assert event["recipient_user_ids"] == ["u-manager"]
    assert "请假类型：年假" in event["content"]
    assert "请假事由：家中有事" in event["content"]


def test_wecom_list_process_events_only_uses_first_pending_node_handlers() -> None:
    info_response = {"sp_no_list": ["202607200003"]}
    detail_response = {
        "info": {
            "sp_no": "202607200003",
            "sp_name": "出差申请",
            "sp_status": 1,
            "apply_time": 1784516949,
            "applyer": {"userid": "u-applicant"},
            "apply_data": {"contents": [{"title": [{"text": "事由"}], "value": {"text": "客户拜访"}}]},
            "sp_record": [
                {
                    "sp_status": 1,
                    "approverattr": 2,
                    "details": [
                        {"approver": {"userid": "u-approved"}, "sp_status": 2, "sptime": 1784517000},
                        {"approver": {"userid": "u-current"}, "sp_status": 1, "sptime": 0},
                    ],
                },
                {
                    "sp_status": 1,
                    "approverattr": 1,
                    "details": [
                        {"approver": {"userid": "u-future"}, "sp_status": 1, "sptime": 0},
                    ],
                },
            ],
        }
    }

    with patch("src.platform.api_wecom._post_optional_diagnostic", return_value=(info_response, "")), \
         patch("src.platform.api_wecom._post_optional", return_value=detail_response), \
         patch("src.platform.api_wecom._batch_resolve_user_names", return_value={"u-applicant": "申请人", "u-current": "当前审批人", "u-future": "后续审批人"}), \
         patch("src.platform.api_wecom._is_approval_admin", return_value=True):
        events = WeComClient().list_process_events()

    assert len(events) == 1
    assert events[0]["recipient_user_ids"] == ["u-current"]
    assert events[0]["current_node"] == "当前审批人"
    assert "u-future" not in events[0]["recipient_user_ids"]


def test_wecom_list_process_events_does_not_notify_handlers_for_finished_or_revoked_flow() -> None:
    info_response = {"sp_no_list": ["202607090004"]}
    detail_response = {
        "info": {
            "sp_no": "202607090004",
            "sp_name": "工作餐申请",
            "sp_status": 4,
            "apply_time": 1783566501,
            "applyer": {"userid": "u-applicant"},
            "apply_data": {"contents": [{"title": [{"text": "原因"}], "value": {"text": "业务接待"}}]},
            "sp_record": [
                {"sp_status": 2, "details": [{"approver": {"userid": "u-done"}, "sp_status": 2, "sptime": 1783566544}]},
                {"sp_status": 1, "details": [{"approver": {"userid": "u-future-a"}, "sp_status": 1, "sptime": 0}]},
                {"sp_status": 1, "details": [{"approver": {"userid": "u-future-b"}, "sp_status": 1, "sptime": 0}]},
            ],
        }
    }

    with patch("src.platform.api_wecom._post_optional_diagnostic", return_value=(info_response, "")), \
         patch("src.platform.api_wecom._post_optional", return_value=detail_response), \
         patch("src.platform.api_wecom._batch_resolve_user_names", return_value={"u-applicant": "申请人"}), \
         patch("src.platform.api_wecom._is_approval_admin", return_value=True):
        events = WeComClient().list_process_events()

    assert len(events) == 1
    assert events[0]["status"] == "已撤销"
    assert events[0]["recipient_user_ids"] == []
    assert events[0]["current_node"] == ""


def test_wecom_list_process_events_filters_empty_json_form_values() -> None:
    info_response = {"sp_no_list": ["202607200004"]}
    empty_control = '{"tips": [], "members": [], "departments": [], "files": [], "children": [], "stat_field": []}'
    detail_response = {
        "info": {
            "sp_no": "202607200004",
            "sp_name": "工作餐申请",
            "sp_status": 1,
            "apply_time": 1784516949,
            "applyer": {"userid": "u-applicant"},
            "apply_data": {
                "contents": [
                    {"title": [{"text": "说明"}], "value": {"text": empty_control}},
                    {"title": [{"text": "类型"}], "value": {"text": empty_control}},
                    {"title": [{"text": "原因"}], "value": {"text": "处理型筒跳动问题"}},
                ]
            },
            "sp_record": [
                {"sp_status": 1, "details": [{"approver": {"userid": "u-current"}, "sp_status": 1, "sptime": 0}]},
            ],
        }
    }

    with patch("src.platform.api_wecom._post_optional_diagnostic", return_value=(info_response, "")), \
         patch("src.platform.api_wecom._post_optional", return_value=detail_response), \
         patch("src.platform.api_wecom._batch_resolve_user_names", return_value={"u-applicant": "申请人", "u-current": "当前审批人"}), \
         patch("src.platform.api_wecom._is_approval_admin", return_value=True):
        events = WeComClient().list_process_events()

    assert len(events) == 1
    assert events[0]["content"] == "原因：处理型筒跳动问题"
    assert "tips" not in events[0]["content"]
    assert "children" not in events[0]["content"]


def test_wecom_list_process_events_records_diagnostic_error() -> None:
    client = WeComClient()
    with patch(
        "src.platform.api_wecom._post_optional_diagnostic",
        return_value=(None, "WeCom token error: corpsecret missing"),
    ):
        events = client.list_process_events()

    assert events == []
    assert client.last_process_event_error == "WeCom token error: corpsecret missing"

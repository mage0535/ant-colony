from __future__ import annotations

from unittest.mock import patch

from src.platform.api_wecom import WeComClient


def test_wecom_document_search_returns_clickable_urls() -> None:
    response = {
        "item_list": [
            {
                "title": "车间管理规定",
                "creator_name": "马戈",
                "url": "https://doc.weixin.qq.com/example",
            }
        ]
    }

    with patch("src.platform.api_wecom._post", return_value=response):
        result = WeComClient().search_docs("车间")

    assert result == "车间管理规定 | 创建者: 马戈 | https://doc.weixin.qq.com/example"


def test_wecom_query_meeting_room_uses_available_room_payload() -> None:
    payload = {
        "booking_list": [
            {
                "room_name": "三号会议室",
                "title": "生产例会",
                "start_time": 1893459600,
                "end_time": 1893463200,
            }
        ]
    }

    with patch(
        "src.platform.api_wecom._post_optional_diagnostic",
        side_effect=[(payload, ""), (None, ""), (None, "")],
    ):
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

from __future__ import annotations

from unittest.mock import patch

from src.platform.api_wecom import WeComClient
from src.platform.internal_capability_provider import InternalCapabilityProvider


def test_enterprise_app_samples_are_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ANT_COLONY_ENABLE_SAMPLE_BUSINESS_DATA", raising=False)

    assert InternalCapabilityProvider().query_meeting_room("三号会议室") is None
    assert InternalCapabilityProvider().query_enterprise_apps("查询三号会议室") is None


def test_wecom_room_query_reports_permission_failure_without_fake_result() -> None:
    with patch(
        "src.platform.api_wecom._post_optional_diagnostic",
        return_value=(None, "WeCom API error 48002: api forbidden"),
    ), patch.object(WeComClient, "list_meetings", return_value=None), patch.object(
        WeComClient, "get_agenda", return_value=None
    ):
        result = WeComClient().query_meeting_room("三号会议室有人申请吗？")

    assert "48002" in result
    assert "真实占用数据" in result
    assert "没有查到" not in result


def test_wecom_room_query_keeps_diagnostic_when_legacy_fallback_raises() -> None:
    with patch(
        "src.platform.api_wecom._post_optional_diagnostic",
        return_value=(None, "WeCom API error 48002: api forbidden"),
    ), patch.object(
        WeComClient, "list_meetings", side_effect=RuntimeError("HTTP Error 404: Not Found")
    ), patch.object(
        WeComClient, "get_agenda", side_effect=RuntimeError("api unavailable")
    ):
        result = WeComClient().query_meeting_room("三号会议室有人申请吗？")

    assert "48002" in result
    assert "真实占用数据" in result


def test_enterprise_app_query_keeps_room_result_when_agenda_raises() -> None:
    client = WeComClient()
    with patch.object(client, "query_meeting_room", return_value="会议室权限不足 48002"), patch.object(
        client, "list_approvals", return_value=None
    ), patch.object(client, "get_agenda", side_effect=RuntimeError("HTTP Error 404: Not Found")):
        result = client.query_enterprise_apps("三号会议室有人申请吗？")

    assert "会议室权限不足 48002" in result

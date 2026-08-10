from __future__ import annotations

from scripts.validate_dingtalk_live import dingtalk_configuration_ok
from scripts.validate_external_runtime import runtime_validation_ok
from scripts.validate_feishu_live import feishu_configuration_ok
from scripts.validate_langsmith_cloud import langsmith_cloud_ok
from scripts.validate_wecom_document_workflow import document_workflow_ok
from scripts.validate_wecom_full_roundtrip import full_roundtrip_ok
from scripts.validate_wecom_live import wecom_configuration_ok
from scripts.validate_wecom_message_flow import outbound_flow_ok


def test_external_runtime_requires_wecom_and_service_ports() -> None:
    assert runtime_validation_ok(
        {
            "platforms": {"wecom": {"configured": True}},
            "ports": {
                "gateway": {"reachable": True},
                "callback": {"reachable": True},
                "dashboard": {"reachable": True},
                "gbrain": {"reachable": True},
                "hindsight": {"reachable": True},
                "embed": {"reachable": True},
            },
        }
    )
    assert not runtime_validation_ok(
        {
            "platforms": {"wecom": {"configured": True}},
            "ports": {
                "gateway": {"reachable": True},
                "callback": {"reachable": True},
                "dashboard": {"reachable": False},
                "gbrain": {"reachable": True},
                "hindsight": {"reachable": True},
                "embed": {"reachable": True},
            },
        }
    )
    assert not runtime_validation_ok({"platforms": {"wecom": {"configured": False}}, "ports": {}})


def test_live_platform_validation_helpers_reject_failed_reports() -> None:
    assert wecom_configuration_ok({"corp_api": {"ok": True}, "bot_ws": {"ok": True}})
    assert not wecom_configuration_ok({"corp_api": {"ok": True}, "bot_ws": {"ok": False}})
    assert feishu_configuration_ok({"api": {"ok": True}})
    assert not feishu_configuration_ok({"api": {"ok": False, "configured": True}})
    assert dingtalk_configuration_ok({"api": {"ok": True}})
    assert not dingtalk_configuration_ok({"api": {"ok": False, "configured": True}})


def test_wecom_workflow_validation_helpers_require_actual_delivery() -> None:
    assert outbound_flow_ok(
        {
            "configured": True,
            "text": {"ok": True},
            "file_card": {"ok": True},
            "file_send": {"ok": True},
        }
    )
    assert not outbound_flow_ok(
        {
            "configured": True,
            "text": {"ok": True},
            "file_card": {"ok": False},
            "file_send": {"ok": True},
        }
    )
    assert full_roundtrip_ok(
        {"configured": True, "uploaded": True, "bot_file": True, "pushed": True}
    )
    assert not full_roundtrip_ok(
        {"configured": True, "uploaded": True, "bot_file": True, "pushed": False}
    )
    assert document_workflow_ok({"configured": True, "pushed": True})
    assert not document_workflow_ok({"configured": True, "pushed": False})


def test_langsmith_validation_requires_project_ready_and_visible() -> None:
    assert langsmith_cloud_ok(
        {"configured": True, "project_ready": True, "project_visible": True}
    )
    assert not langsmith_cloud_ok(
        {"configured": True, "project_ready": True, "project_visible": False}
    )

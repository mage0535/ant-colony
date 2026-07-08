from __future__ import annotations


def test_platform_interface_report_marks_in_repo_integrations() -> None:
    from scripts.check_platform_interface_updates import build_report

    report = build_report()
    assert [item["platform"] for item in report["platforms"]] == ["wecom", "feishu", "dingtalk"]
    assert all(item["integration_mode"] == "in_repo_http_client" for item in report["platforms"])
    assert all(item["update_required"] is False for item in report["platforms"])


def test_platform_interface_report_has_no_external_sdk_dependencies() -> None:
    from scripts.check_platform_interface_updates import build_report

    report = build_report()
    for item in report["platforms"]:
        assert item["sdk_dependencies"] == []

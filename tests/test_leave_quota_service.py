from __future__ import annotations

from unittest.mock import patch


def test_negative_probe_restores_original_quota_when_wecom_accepts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant-colony.db"))
    from src.platform.leave_quota_service import probe_negative_leave_quota

    calls: list[tuple[str, int, int, str]] = []

    def fake_get(user_id: str):
        assert user_id == "u1"
        return {
            "lists": [
                {
                    "vacation_id": 101,
                    "vacationname": {"zh_CN": "年假"},
                    "leftduration": 86400,
                    "time_attr": 1,
                }
            ]
        }

    def fake_set(user_id: str, vacation_id: int, leftduration: int, *, time_attr: int, remarks: str):
        calls.append((user_id, vacation_id, leftduration, remarks))
        return {"errcode": 0, "errmsg": "ok"}

    with patch("src.platform.leave_quota_service.get_user_vacation_quota", side_effect=fake_get), \
         patch("src.platform.leave_quota_service.set_user_vacation_quota", side_effect=fake_set):
        result = probe_negative_leave_quota(
            platform="wecom",
            user_id="u1",
            vacation_id=101,
            negative_duration=-86400,
            confirm_live_write=True,
            operator_user_id="admin",
        )

    assert result["negative_supported"] is True
    assert result["restored"] is True
    assert calls[0][2] == -86400
    assert calls[1][2] == 86400


def test_negative_probe_records_unsupported_when_wecom_rejects(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant-colony.db"))
    from src.platform.leave_quota_service import list_negative_probe_results, probe_negative_leave_quota

    def fake_set(*args, **kwargs):
        raise RuntimeError("WeCom API error (oa/vacation/setoneuserquota): [301063] invalid leftduration")

    with patch("src.platform.leave_quota_service.get_user_vacation_quota", return_value={"lists": [{"vacation_id": 7, "leftduration": 3600, "time_attr": 2}]}), \
         patch("src.platform.leave_quota_service.set_user_vacation_quota", side_effect=fake_set):
        result = probe_negative_leave_quota(
            platform="wecom",
            user_id="u2",
            vacation_id=7,
            negative_duration=-3600,
            confirm_live_write=True,
            operator_user_id="admin",
        )

    assert result["negative_supported"] is False
    assert "invalid leftduration" in result["error"]
    history = list_negative_probe_results(platform="wecom")
    assert history[0]["user_id"] == "u2"
    assert history[0]["negative_supported"] is False


def test_local_negative_ledger_keeps_negative_balance_when_wecom_rejects(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant-colony.db"))
    from src.platform.leave_quota_service import apply_leave_balance_target, get_local_leave_balance

    with patch("src.platform.leave_quota_service.set_user_vacation_quota", side_effect=RuntimeError("negative rejected")):
        result = apply_leave_balance_target(
            platform="wecom",
            user_id="u3",
            vacation_id=9,
            vacation_name="调休假",
            target_leftduration=-7200,
            time_attr=2,
            operator_user_id="hr1",
            reason="欠调休 2 小时",
            allow_local_negative=True,
        )

    assert result["mode"] == "local_negative_ledger"
    assert result["target_leftduration"] == -7200
    balance = get_local_leave_balance(platform="wecom", user_id="u3", vacation_id=9)
    assert balance["leftduration"] == -7200
    assert balance["source"] == "local_negative_ledger"


def test_leave_workflow_notice_plan_appends_missing_tip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-template-plan.db"))
    from src.platform.leave_quota_service import plan_leave_workflow_notice_update

    template = {
        "template_id": "tpl1",
        "template_name": [{"text": "Leave", "lang": "en"}],
        "template_content": {"controls": [{"property": {"id": "Vacation-01", "control": "Vacation"}}]},
    }

    monkeypatch.setattr("src.platform.leave_quota_service.get_approval_template_detail", lambda template_id: template)

    result = plan_leave_workflow_notice_update(template_id="tpl1")

    assert result["needs_update"] is True
    controls = result["template_content"]["controls"]
    assert controls[-1]["property"]["id"] == "AntColony-LeaveCreditNotice"
    assert controls[-1]["property"]["control"] == "Tips"
    assert "假期额度说明" in controls[-1]["property"]["title"][0]["text"]
    assert len(template["template_content"]["controls"]) == 1


def test_leave_workflow_notice_plan_accepts_real_wecom_template_detail_shape(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-template-real-shape.db"))
    from src.platform.leave_quota_service import plan_leave_workflow_notice_update

    template = {
        "errcode": 0,
        "errmsg": "ok",
        "template_names": [{"text": "请假", "lang": "zh_CN"}],
        "template_content": {
            "controls": [
                {"property": {"control": "Vacation", "id": "vacation-1", "title": [{"text": "请假类型", "lang": "zh_CN"}]}}
            ]
        },
        "vacation_list": {"item": [{"id": 1, "name": [{"text": "年假", "lang": "zh_CN"}]}]},
    }
    monkeypatch.setattr("src.platform.leave_quota_service.get_approval_template_detail", lambda template_id: template)

    result = plan_leave_workflow_notice_update(template_id="tpl-real")

    assert result["template_id"] == "tpl-real"
    assert result["template_name"] == [{"text": "请假", "lang": "zh_CN"}]
    assert result["needs_update"] is True
    assert result["template_content"]["controls"][-1]["property"]["control"] == "Tips"


def test_leave_workflow_notice_plan_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-template-idempotent.db"))
    from src.platform.leave_quota_service import plan_leave_workflow_notice_update

    template = {
        "template_id": "tpl1",
        "template_name": [{"text": "Leave", "lang": "en"}],
        "template_content": {
            "controls": [
                {"property": {"id": "Vacation-01", "control": "Vacation"}},
                {"property": {"id": "AntColony-LeaveCreditNotice", "control": "Tips"}},
            ]
        },
    }

    monkeypatch.setattr("src.platform.leave_quota_service.get_approval_template_detail", lambda template_id: template)

    result = plan_leave_workflow_notice_update(template_id="tpl1")

    assert result["needs_update"] is False
    assert len(result["template_content"]["controls"]) == 2


def test_apply_leave_workflow_notice_updates_template(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-template-apply.db"))
    from src.platform.leave_quota_service import apply_leave_workflow_notice_update

    template = {
        "template_id": "tpl1",
        "template_name": [{"text": "Leave", "lang": "en"}],
        "template_content": {"controls": [{"property": {"id": "Vacation-01", "control": "Vacation"}}]},
    }
    updated: list[dict] = []

    monkeypatch.setattr("src.platform.leave_quota_service.get_approval_template_detail", lambda template_id: template)
    monkeypatch.setattr("src.platform.leave_quota_service.update_approval_template", lambda payload: updated.append(payload) or {"errcode": 0})

    result = apply_leave_workflow_notice_update(template_id="tpl1", operator_user_id="admin")

    assert result["applied"] is True
    assert result["needs_update"] is True
    assert updated[0]["template_id"] == "tpl1"
    assert updated[0]["template_content"]["controls"][-1]["property"]["control"] == "Tips"


def test_apply_leave_workflow_notice_returns_manual_steps_when_wecom_rejects_template_update(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-template-apply-reject.db"))
    from src.platform.leave_quota_service import apply_leave_workflow_notice_update

    template = {
        "errcode": 0,
        "errmsg": "ok",
        "template_names": [{"text": "请假", "lang": "zh_CN"}],
        "template_content": {
            "controls": [
                {"property": {"id": "vacation-1563793073898", "control": "Vacation"}},
            ]
        },
    }

    monkeypatch.setattr("src.platform.leave_quota_service.get_approval_template_detail", lambda template_id: template)

    def reject_update(payload):
        raise RuntimeError(
            "WeCom API error (oa/approval/update_template): "
            "[301086] invalid parameter:controlId doesn't match"
        )

    monkeypatch.setattr("src.platform.leave_quota_service.update_approval_template", reject_update)

    result = apply_leave_workflow_notice_update(template_id="tpl-real", operator_user_id="admin")

    assert result["applied"] is False
    assert result["update_failed"] is True
    assert result["template_id"] == "tpl-real"
    assert "企微拒绝自动更新请假模板" in result["message"]
    assert result["manual_steps"]
    assert "controlId doesn't match" in result["wecom_result"]["error"]


def test_discover_leave_workflow_template_from_recent_approval_details(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-template-discovery.db"))
    from src.platform.leave_quota_service import discover_leave_workflow_template

    monkeypatch.setattr(
        "src.platform.leave_quota_service._post_optional_diagnostic",
        lambda path, body, **kwargs: ({"sp_no_list": ["SP1", "SP2", "SP3"]}, ""),
    )

    def fake_detail(path, body, **kwargs):
        details = {
            "SP1": {"info": {"sp_no": "SP1", "sp_name": "加班", "template_id": "tpl-overtime", "apply_time": 1}},
            "SP2": {"info": {"sp_no": "SP2", "sp_name": "请假", "template_id": "tpl-leave", "apply_time": 2}},
            "SP3": {"info": {"sp_no": "SP3", "sp_name": "请假", "template_id": "tpl-leave", "apply_time": 3}},
        }
        return details[body["sp_no"]]

    monkeypatch.setattr("src.platform.leave_quota_service._post_optional", fake_detail)

    result = discover_leave_workflow_template(platform="wecom", template_name="请假")

    assert result["found"] is True
    assert result["template_id"] == "tpl-leave"
    assert result["candidates"][0]["count"] == 2


def test_resolve_leave_workflow_template_id_prefers_env(monkeypatch) -> None:
    from src.platform.leave_quota_service import resolve_leave_workflow_template_id

    monkeypatch.setenv("ANT_COLONY_WECOM_LEAVE_TEMPLATE_ID", "tpl-env")

    result = resolve_leave_workflow_template_id()

    assert result == {"template_id": "tpl-env", "source": "ANT_COLONY_WECOM_LEAVE_TEMPLATE_ID", "discovery": {}}


def test_build_employee_leave_form_notice_describes_negative_zero_and_positive_balances(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-form-notice.db"))
    from src.platform.leave_quota_service import (
        apply_leave_balance_target,
        build_employee_leave_form_notice,
        configure_leave_policy,
    )

    monkeypatch.setattr(
        "src.platform.leave_quota_service.set_user_vacation_quota",
        lambda *args, **kwargs: {"errcode": 0},
    )
    configure_leave_policy(platform="wecom", vacation_id=4, vacation_name="调休假", leave_kind="comp_time", time_attr=0, overtime_credit=True)
    configure_leave_policy(platform="wecom", vacation_id=1, vacation_name="年假", leave_kind="annual", time_attr=0)

    apply_leave_balance_target(
        platform="wecom",
        user_id="u1",
        vacation_id=4,
        vacation_name="调休假",
        target_leftduration=-2 * 86400,
        time_attr=0,
        operator_user_id="hr",
        reason="历史预支",
        allow_local_negative=True,
    )
    apply_leave_balance_target(
        platform="wecom",
        user_id="u1",
        vacation_id=1,
        vacation_name="年假",
        target_leftduration=3 * 86400,
        time_attr=0,
        operator_user_id="hr",
        reason="年假导入",
    )

    notice = build_employee_leave_form_notice(platform="wecom", user_id="u1")

    assert "调休假：欠公司 2 天，待后续加班调休冲抵" in notice
    assert "年假：可用 3 天" in notice
    assert "请以本提示为真实假期口径" in notice


def test_build_employee_leave_form_notice_bootstraps_from_wecom_quota_when_local_balance_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-form-wecom-bootstrap.db"))
    from src.platform.leave_quota_service import build_employee_leave_form_notice, configure_leave_policy, get_local_leave_balance

    configure_leave_policy(platform="wecom", vacation_id=1, vacation_name="年假", leave_kind="annual", time_attr=0)
    monkeypatch.setattr(
        "src.platform.leave_quota_service.get_user_vacation_quota",
        lambda user_id: {
            "errcode": 0,
            "lists": [
                {"id": 1, "vacationname": {"zh_CN": "年假"}, "leftduration": 5 * 86400, "time_attr": 0},
            ],
        },
    )

    notice = build_employee_leave_form_notice(platform="wecom", user_id="u1")

    assert "年假：可用 5 天" in notice
    assert get_local_leave_balance(platform="wecom", user_id="u1", vacation_id=1)["leftduration"] == 5 * 86400
    assert get_local_leave_balance(platform="wecom", user_id="u1", vacation_id=1)["time_attr"] == 0


def test_build_employee_leave_form_notice_does_not_report_zero_when_wecom_quota_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-form-wecom-unavailable.db"))
    from src.platform.leave_quota_service import build_employee_leave_form_notice, configure_leave_policy

    configure_leave_policy(platform="wecom", vacation_id=1, vacation_name="年假", leave_kind="annual", time_attr=0)
    monkeypatch.setattr(
        "src.platform.leave_quota_service.get_user_vacation_quota",
        lambda user_id: (_ for _ in ()).throw(RuntimeError("network timeout")),
    )

    notice = build_employee_leave_form_notice(platform="wecom", user_id="u1")

    assert "年假：暂未读取到企微余额" in notice
    assert "年假：当前无可用余额，也无欠假" not in notice


def test_approved_leave_consumes_true_balance_and_syncs_apply_quota(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-realtime.db"))
    from src.platform.leave_quota_service import (
        configure_leave_policy,
        get_local_leave_balance,
        process_realtime_approval_event,
    )

    synced: list[tuple[str, int, int]] = []
    monkeypatch.setattr(
        "src.platform.leave_quota_service.set_user_vacation_quota",
        lambda user_id, vacation_id, leftduration, **kwargs: synced.append((user_id, vacation_id, leftduration)) or {"errcode": 0},
    )
    configure_leave_policy(
        platform="wecom",
        vacation_id=9,
        vacation_name="调休",
        leave_kind="comp_time",
        advance_seconds=3 * 86400,
        time_attr=1,
    )

    result = process_realtime_approval_event(
        {
            "platform": "wecom",
            "sp_no": "SP-LEAVE-1",
            "template_name": "请假",
            "business_type": "leave",
            "approval_status": "approved",
            "applicant_user_id": "u1",
            "vacation_id": 9,
            "vacation_name": "调休",
            "duration_seconds": 86400,
            "event_time": "2026-07-31 09:00",
        }
    )

    assert result["action"] == "leave_consumed"
    assert get_local_leave_balance(platform="wecom", user_id="u1", vacation_id=9)["leftduration"] == -86400
    assert synced == [("u1", 9, 2 * 86400)]


def test_sync_wecom_apply_quota_preserves_zero_time_attr(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-time-attr-zero.db"))
    from src.platform.leave_quota_service import apply_leave_balance_target, configure_leave_policy, process_realtime_approval_event

    calls: list[dict[str, int]] = []
    monkeypatch.setattr(
        "src.platform.leave_quota_service.set_user_vacation_quota",
        lambda user_id, vacation_id, leftduration, **kwargs: calls.append({"leftduration": leftduration, "time_attr": kwargs["time_attr"]}) or {"errcode": 0},
    )
    configure_leave_policy(platform="wecom", vacation_id=1, vacation_name="年假", leave_kind="annual", time_attr=0)
    apply_leave_balance_target(
        platform="wecom",
        user_id="u1",
        vacation_id=1,
        vacation_name="年假",
        target_leftduration=3 * 86400,
        time_attr=0,
        operator_user_id="hr",
        reason="导入年假",
    )
    calls.clear()

    process_realtime_approval_event(
        {
            "platform": "wecom",
            "sp_no": "SP-ZERO-TIME-ATTR",
            "template_name": "请假",
            "business_type": "leave",
            "approval_status": "approved",
            "applicant_user_id": "u1",
            "vacation_id": 1,
            "vacation_name": "年假",
            "duration_seconds": 86400,
        }
    )

    assert calls[-1]["time_attr"] == 0


def test_overtime_credit_offsets_negative_comp_time_and_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-overtime.db"))
    from src.platform.leave_quota_service import (
        apply_leave_balance_target,
        configure_leave_policy,
        get_local_leave_balance,
        process_realtime_approval_event,
    )

    synced: list[int] = []
    monkeypatch.setattr(
        "src.platform.leave_quota_service.set_user_vacation_quota",
        lambda user_id, vacation_id, leftduration, **kwargs: synced.append(leftduration) or {"errcode": 0},
    )
    configure_leave_policy(
        platform="wecom",
        vacation_id=9,
        vacation_name="调休",
        leave_kind="comp_time",
        advance_seconds=0,
        time_attr=1,
        overtime_credit=True,
    )
    apply_leave_balance_target(
        platform="wecom",
        user_id="u1",
        vacation_id=9,
        vacation_name="调休",
        target_leftduration=-2 * 86400,
        time_attr=1,
        operator_user_id="hr",
        reason="initial negative balance",
        allow_local_negative=True,
    )
    synced.clear()

    event = {
        "platform": "wecom",
        "sp_no": "SP-OT-1",
        "template_name": "加班",
        "business_type": "overtime",
        "approval_status": "approved",
        "applicant_user_id": "u1",
        "vacation_id": 9,
        "vacation_name": "调休",
        "duration_seconds": 5 * 86400,
    }
    first = process_realtime_approval_event(event)
    second = process_realtime_approval_event(event)

    assert first["action"] == "overtime_credited"
    assert second["action"] == "duplicate_skipped"
    assert get_local_leave_balance(platform="wecom", user_id="u1", vacation_id=9)["leftduration"] == 3 * 86400
    assert synced == [3 * 86400]


def test_pending_leave_hold_reduces_wecom_apply_quota_and_releases_on_reject(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-hold.db"))
    from src.platform.leave_quota_service import (
        apply_leave_balance_target,
        configure_leave_policy,
        process_realtime_approval_event,
    )

    synced: list[int] = []
    monkeypatch.setattr(
        "src.platform.leave_quota_service.set_user_vacation_quota",
        lambda user_id, vacation_id, leftduration, **kwargs: synced.append(leftduration) or {"errcode": 0},
    )
    configure_leave_policy(
        platform="wecom",
        vacation_id=7,
        vacation_name="年假",
        leave_kind="annual",
        advance_seconds=0,
        time_attr=1,
    )
    apply_leave_balance_target(
        platform="wecom",
        user_id="u2",
        vacation_id=7,
        vacation_name="年假",
        target_leftduration=3 * 86400,
        time_attr=1,
        operator_user_id="hr",
        reason="initial balance",
    )
    synced.clear()

    pending = {
        "platform": "wecom",
        "sp_no": "SP-HOLD-1",
        "template_name": "请假",
        "business_type": "leave",
        "approval_status": "pending",
        "applicant_user_id": "u2",
        "vacation_id": 7,
        "vacation_name": "年假",
        "duration_seconds": 86400,
    }
    rejected = {**pending, "approval_status": "rejected"}

    assert process_realtime_approval_event(pending)["action"] == "leave_hold_recorded"
    assert process_realtime_approval_event(rejected)["action"] == "leave_hold_released"
    assert synced == [2 * 86400, 3 * 86400]


def test_run_realtime_leave_sync_polls_wecom_and_processes_leave_detail(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-sync.db"))
    from src.platform.leave_quota_service import configure_leave_policy, get_local_leave_balance, run_realtime_leave_sync

    configure_leave_policy(
        platform="wecom",
        vacation_id=9,
        vacation_name="调休",
        leave_kind="comp_time",
        advance_seconds=3 * 86400,
        time_attr=1,
    )
    detail = {
        "info": {
            "sp_no": "SP-SYNC-1",
            "sp_name": "请假",
            "sp_status": 2,
            "applyer": {"userid": "u1"},
            "apply_time": 1785488400,
            "apply_data": {
                "contents": [
                    {"title": [{"text": "请假类型"}], "value": {"text": "调休"}},
                    {"title": [{"text": "请假时长"}], "value": {"text": "1天"}},
                ]
            },
        }
    }
    synced: list[int] = []

    monkeypatch.setattr("src.platform.leave_quota_service._post_optional_diagnostic", lambda *args, **kwargs: ({"sp_no_list": ["SP-SYNC-1"]}, ""))
    monkeypatch.setattr("src.platform.leave_quota_service._post_optional", lambda *args, **kwargs: detail)
    monkeypatch.setattr("src.platform.leave_quota_service.set_user_vacation_quota", lambda user_id, vacation_id, leftduration, **kwargs: synced.append(leftduration) or {"errcode": 0})

    result = run_realtime_leave_sync(platform="wecom", window_seconds=600)

    assert result["processed"] == 1
    assert result["actions"] == {"leave_consumed": 1}
    assert get_local_leave_balance(platform="wecom", user_id="u1", vacation_id=9)["leftduration"] == -86400
    assert synced == [2 * 86400]


def test_run_realtime_leave_sync_overtime_offsets_negative_balance(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "overtime-sync.db"))
    from src.platform.leave_quota_service import (
        apply_leave_balance_target,
        configure_leave_policy,
        get_local_leave_balance,
        run_realtime_leave_sync,
    )

    configure_leave_policy(
        platform="wecom",
        vacation_id=9,
        vacation_name="调休",
        leave_kind="comp_time",
        time_attr=1,
        overtime_credit=True,
    )
    apply_leave_balance_target(
        platform="wecom",
        user_id="u1",
        vacation_id=9,
        vacation_name="调休",
        target_leftduration=-86400,
        time_attr=1,
        operator_user_id="hr",
        reason="initial",
        allow_local_negative=True,
    )
    detail = {
        "info": {
            "sp_no": "SP-OT-SYNC-1",
            "sp_name": "加班",
            "sp_status": 2,
            "applyer": {"userid": "u1"},
            "apply_data": {"contents": [{"title": [{"text": "加班时长"}], "value": {"text": "2天"}}]},
        }
    }
    synced: list[int] = []
    monkeypatch.setattr("src.platform.leave_quota_service._post_optional_diagnostic", lambda *args, **kwargs: ({"sp_no_list": ["SP-OT-SYNC-1"]}, ""))
    monkeypatch.setattr("src.platform.leave_quota_service._post_optional", lambda *args, **kwargs: detail)
    monkeypatch.setattr("src.platform.leave_quota_service.set_user_vacation_quota", lambda user_id, vacation_id, leftduration, **kwargs: synced.append(leftduration) or {"errcode": 0})

    result = run_realtime_leave_sync(platform="wecom", window_seconds=600)

    assert result["processed"] == 1
    assert result["actions"] == {"overtime_credited": 1}
    assert get_local_leave_balance(platform="wecom", user_id="u1", vacation_id=9)["leftduration"] == 86400
    assert synced[-1] == 86400


def test_sync_leave_policies_from_wecom_config_maps_company_vacations(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-policy-sync.db"))
    from src.platform.leave_quota_service import list_leave_realtime_status, sync_leave_policies_from_wecom_config

    monkeypatch.setattr(
        "src.platform.leave_quota_service.get_corp_vacation_config",
        lambda: {
            "errcode": 0,
            "lists": [
                {"id": 1, "name": "\u5e74\u5047", "time_attr": 0, "duration_type": 1},
                {"id": 3, "name": "\u75c5\u5047", "time_attr": 0, "duration_type": 0},
                {"id": 4, "name": "\u8c03\u4f11\u5047", "time_attr": 0, "duration_type": 1},
            ],
        },
    )

    result = sync_leave_policies_from_wecom_config(platform="wecom")

    assert result["synced"] == 3
    policies = {item["vacation_name"]: item for item in list_leave_realtime_status(platform="wecom")["policies"]}
    assert policies["\u5e74\u5047"]["leave_kind"] == "annual"
    assert policies["\u5e74\u5047"]["time_attr"] == 0
    assert policies["\u75c5\u5047"]["leave_kind"] == "sick"
    assert policies["\u8c03\u4f11\u5047"]["leave_kind"] == "comp_time"
    assert policies["\u8c03\u4f11\u5047"]["overtime_credit"] == 1


def test_run_realtime_leave_sync_bootstraps_policies_before_processing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "leave-policy-bootstrap.db"))
    from src.platform.leave_quota_service import get_local_leave_balance, run_realtime_leave_sync

    monkeypatch.setattr(
        "src.platform.leave_quota_service.get_corp_vacation_config",
        lambda: {"errcode": 0, "lists": [{"id": 4, "name": "\u8c03\u4f11\u5047", "time_attr": 0, "duration_type": 1}]},
    )
    detail = {
        "info": {
            "sp_no": "SP-AUTO-POLICY-1",
            "sp_name": "\u8bf7\u5047",
            "sp_status": 2,
            "applyer": {"userid": "u1"},
            "apply_data": {"contents": [{"title": [{"text": "\u8bf7\u5047\u7c7b\u578b"}], "value": {"text": "\u8c03\u4f11\u5047"}}, {"title": [{"text": "\u8bf7\u5047\u65f6\u957f"}], "value": {"text": "1\u5929"}}]},
        }
    }
    synced: list[int] = []
    monkeypatch.setattr("src.platform.leave_quota_service._post_optional_diagnostic", lambda *args, **kwargs: ({"sp_no_list": ["SP-AUTO-POLICY-1"]}, ""))
    monkeypatch.setattr("src.platform.leave_quota_service._post_optional", lambda *args, **kwargs: detail)
    monkeypatch.setattr("src.platform.leave_quota_service.set_user_vacation_quota", lambda user_id, vacation_id, leftduration, **kwargs: synced.append(leftduration) or {"errcode": 0})

    result = run_realtime_leave_sync(platform="wecom", window_seconds=600)

    assert result["policy_bootstrap"]["synced"] == 1
    assert result["processed"] == 1
    assert result["actions"] == {"leave_consumed": 1}
    assert get_local_leave_balance(platform="wecom", user_id="u1", vacation_id=4)["leftduration"] == -86400

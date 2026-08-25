from __future__ import annotations

import copy
import json
import os
import re
import sqlite3
import time
from typing import Any

from src.store.database import Database

LEAVE_WORKFLOW_NOTICE_CONTROL_ID = "AntColony-LeaveCreditNotice"
DEFAULT_LEAVE_WORKFLOW_NOTICE = (
    "【假期额度说明】本页显示的是企微可申请额度；企微不显示欠休负数。"
    "当员工存在欠调休、欠假期时，企业 AI 助手会按“欠公司 X 天，待后续加班调休冲抵”的口径提醒。"
    "Ant Colony 会按公司规则保存真实余额，并把企微可申请额度同步为不小于 0 的数值。"
    "提交请假前如看到可申请额度为 0，可能是余额已用完，也可能存在欠休待冲抵；"
    "如不确定，请联系人事专员核对。"
)


def get_corp_vacation_config() -> dict[str, Any]:
    from src.platform.api_wecom import _get, _resolve_domain_secret

    return _get("oa/vacation/getcorpconf", secret=_resolve_domain_secret("approval"))


def get_user_vacation_quota(user_id: str) -> dict[str, Any]:
    from src.platform.api_wecom import _post, _resolve_domain_secret

    return _post(
        "oa/vacation/getuservacationquota",
        {"userid": user_id},
        secret=_resolve_domain_secret("approval"),
    )


def set_user_vacation_quota(
    user_id: str,
    vacation_id: int,
    leftduration: int,
    *,
    time_attr: int,
    remarks: str = "",
) -> dict[str, Any]:
    from src.platform.api_wecom import _post, _resolve_domain_secret

    return _post(
        "oa/vacation/setoneuserquota",
        {
            "userid": user_id,
            "vacation_id": int(vacation_id),
            "leftduration": int(leftduration),
            "time_attr": int(time_attr),
            "remarks": remarks[:200],
        },
        secret=_resolve_domain_secret("approval"),
    )


def get_approval_template_detail(template_id: str) -> dict[str, Any]:
    from src.platform.api_wecom import _post, _resolve_domain_secret

    return _post(
        "oa/gettemplatedetail",
        {"template_id": template_id},
        secret=_resolve_domain_secret("approval"),
    )


def update_approval_template(payload: dict[str, Any]) -> dict[str, Any]:
    from src.platform.api_wecom import _post, _resolve_domain_secret

    return _post(
        "oa/approval/update_template",
        payload,
        secret=_resolve_domain_secret("approval"),
    )


def _post_optional_diagnostic(path: str, body: dict[str, Any], *, secret: str | None = None):
    from src.platform.api_wecom import _post_optional_diagnostic as post_optional_diagnostic

    return post_optional_diagnostic(path, body, secret=secret)


def _post_optional(path: str, body: dict[str, Any], *, secret: str | None = None):
    from src.platform.api_wecom import _post_optional as post_optional

    return post_optional(path, body, secret=secret)


def _resolve_wecom_approval_secret() -> str:
    from src.platform.api_wecom import _resolve_domain_secret

    return _resolve_domain_secret("approval")


def run_realtime_leave_sync(
    platform: str = "wecom",
    *,
    window_seconds: int = 600,
    limit: int = 100,
    dry_run: bool = False,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    if normalized_platform != "wecom":
        return {"platform": normalized_platform, "processed": 0, "actions": {}, "errors": ["unsupported_platform"]}
    policy_bootstrap = sync_leave_policies_from_wecom_config(platform=normalized_platform, only_when_empty=True)
    events, errors = fetch_recent_wecom_approval_events(window_seconds=window_seconds, limit=limit)
    actions: dict[str, int] = {}
    processed = 0
    for event in events:
        try:
            if dry_run:
                action = "dry_run"
            else:
                outcome = process_realtime_approval_event(event)
                action = str(outcome.get("action") or "unknown")
            actions[action] = actions.get(action, 0) + 1
            processed += 1
        except Exception as exc:
            errors.append(f"{event.get('sp_no') or 'unknown'}:{exc}")
    return {
        "platform": normalized_platform,
        "policy_bootstrap": policy_bootstrap,
        "processed": processed,
        "actions": actions,
        "errors": errors[:20],
    }


def fetch_recent_wecom_approval_events(*, window_seconds: int = 600, limit: int = 100) -> tuple[list[dict[str, Any]], list[str]]:
    from src.platform.api_wecom import _resolve_domain_secret

    now = int(time.time())
    start = now - max(60, int(window_seconds or 600))
    response, error = _post_optional_diagnostic(
        "oa/getapprovalinfo",
        {"starttime": start, "endtime": now + 60, "cursor": 0, "size": min(max(int(limit or 100), 1), 100)},
        secret=_resolve_domain_secret("approval"),
    )
    if not response:
        return [], [error] if error else []
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for sp_no in list(response.get("sp_no_list") or [])[:limit]:
        detail = _post_optional(
            "oa/getapprovaldetail",
            {"sp_no": sp_no},
            secret=_resolve_domain_secret("approval"),
        )
        if not detail:
            errors.append(f"{sp_no}:detail_unavailable")
            continue
        try:
            event = normalize_wecom_approval_detail(detail)
        except Exception as exc:
            errors.append(f"{sp_no}:{exc}")
            continue
        if event.get("business_type") in {"leave", "overtime"}:
            events.append(event)
    return events, errors


def process_wecom_approval_callback(payload: dict[str, Any]) -> dict[str, Any]:
    from src.platform.api_wecom import _resolve_domain_secret

    sp_no = _extract_callback_sp_no(payload)
    if not sp_no:
        return {"processed": 0, "skipped": "missing_sp_no"}
    detail = _post_optional(
        "oa/getapprovaldetail",
        {"sp_no": sp_no},
        secret=_resolve_domain_secret("approval"),
    )
    if not detail:
        return {"processed": 0, "error": "detail_unavailable", "sp_no": sp_no}
    event = normalize_wecom_approval_detail(detail)
    if event.get("business_type") not in {"leave", "overtime"}:
        return {"processed": 0, "skipped": "unsupported_business_type", "sp_no": sp_no}
    result = process_realtime_approval_event(event)
    return {"processed": 1, "sp_no": sp_no, "result": result}


def normalize_wecom_approval_detail(detail: dict[str, Any]) -> dict[str, Any]:
    conn = _conn()
    info = detail.get("info") or detail
    sp_no = str(info.get("sp_no") or "").strip()
    if not sp_no:
        raise ValueError("approval detail missing sp_no")
    template_name = str(info.get("sp_name") or info.get("template_name") or "")
    text = _flatten_text(info.get("apply_data") or {})
    business_type = _normalize_business_type(
        {"business_type": "", "template_name": template_name, "title": template_name, "content": text}
    )
    applicant_user_id = str((info.get("applyer") or {}).get("userid") or info.get("applicant_user_id") or "").strip()
    vacation = _infer_vacation_from_text(conn, "wecom", business_type, text, template_name)
    duration_seconds = _parse_duration_seconds(text)
    return {
        "platform": "wecom",
        "sp_no": sp_no,
        "template_name": template_name,
        "business_type": business_type,
        "approval_status": _normalize_approval_status(info.get("sp_status")),
        "applicant_user_id": applicant_user_id,
        "vacation_id": int(vacation.get("vacation_id") or 0),
        "vacation_name": str(vacation.get("vacation_name") or ""),
        "duration_seconds": duration_seconds,
        "event_time": str(info.get("apply_time") or ""),
        "content": text[:500],
    }


def plan_leave_workflow_notice_update(
    *,
    template_id: str,
    notice_text: str = DEFAULT_LEAVE_WORKFLOW_NOTICE,
) -> dict[str, Any]:
    if not template_id.strip():
        raise ValueError("missing template_id")
    requested_template_id = template_id.strip()
    template = get_approval_template_detail(requested_template_id)
    updated = _extract_template_update_payload(template, fallback_template_id=requested_template_id)
    content = copy.deepcopy(updated.get("template_content") or {})
    controls = list(content.get("controls") or [])
    has_notice = any(
        ((control.get("property") or {}).get("id") == LEAVE_WORKFLOW_NOTICE_CONTROL_ID)
        for control in controls
        if isinstance(control, dict)
    )
    if not has_notice:
        controls.append(_leave_workflow_notice_control(notice_text))
    content["controls"] = controls
    updated["template_content"] = content
    return {
        "template_id": updated["template_id"],
        "needs_update": not has_notice,
        "template_name": updated.get("template_name") or [],
        "template_content": content,
        "notice_control_id": LEAVE_WORKFLOW_NOTICE_CONTROL_ID,
        "notice_text": notice_text,
        "message": "already_configured" if has_notice else "ready_to_update",
    }


def discover_leave_workflow_template(
    *,
    platform: str = "wecom",
    template_name: str = "请假",
    window_seconds: int = 30 * 86400,
    limit: int = 100,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    if normalized_platform != "wecom":
        return {"platform": normalized_platform, "found": False, "candidates": [], "error": "unsupported_platform"}

    candidates: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for seconds in _approval_discovery_windows(window_seconds):
        response, error = _fetch_approval_ids_for_template_discovery(seconds, limit)
        if error:
            errors.append(f"{seconds}s:{error}")
            continue
        for sp_no in response.get("sp_no_list", []) or []:
            detail = _post_optional(
                "oa/getapprovaldetail",
                {"sp_no": sp_no},
                secret=_resolve_wecom_approval_secret(),
            )
            candidate = _extract_template_candidate(detail or {})
            if not candidate.get("template_id"):
                continue
            template_label = str(candidate.get("template_name") or "")
            if template_name and template_name not in template_label:
                continue
            template_id = str(candidate["template_id"])
            existing = candidates.setdefault(
                template_id,
                {
                    "template_id": template_id,
                    "template_name": template_label,
                    "sample_sp_no": candidate.get("sp_no") or sp_no,
                    "sample_apply_time": candidate.get("apply_time") or "",
                    "count": 0,
                },
            )
            existing["count"] += 1
        if candidates:
            break

    ordered = sorted(candidates.values(), key=lambda item: (int(item.get("count") or 0), str(item.get("sample_apply_time") or "")), reverse=True)
    return {
        "platform": normalized_platform,
        "found": bool(ordered),
        "template_name": template_name,
        "template_id": ordered[0]["template_id"] if ordered else "",
        "candidates": ordered,
        "errors": errors[:10],
    }


def resolve_leave_workflow_template_id(*, template_id: str = "", platform: str = "wecom", template_name: str = "请假") -> dict[str, Any]:
    explicit = (template_id or "").strip()
    if explicit:
        return {"template_id": explicit, "source": "request", "discovery": {}}
    for variable in ("ANT_COLONY_WECOM_LEAVE_TEMPLATE_ID", "WECOM_LEAVE_TEMPLATE_ID"):
        value = os.environ.get(variable, "").strip()
        if value:
            return {"template_id": value, "source": variable, "discovery": {}}
    discovery = discover_leave_workflow_template(platform=platform, template_name=template_name)
    if discovery.get("template_id"):
        return {"template_id": str(discovery["template_id"]), "source": "recent_approval_detail", "discovery": discovery}
    return {"template_id": "", "source": "not_found", "discovery": discovery}


def apply_leave_workflow_notice_update(
    *,
    template_id: str,
    notice_text: str = DEFAULT_LEAVE_WORKFLOW_NOTICE,
    operator_user_id: str = "",
) -> dict[str, Any]:
    plan = plan_leave_workflow_notice_update(template_id=template_id, notice_text=notice_text)
    if not plan["needs_update"]:
        return {**plan, "applied": False, "wecom_result": {"skipped": "already_configured"}}
    payload = {
        "template_id": plan["template_id"],
        "template_name": plan["template_name"],
        "template_content": plan["template_content"],
    }
    try:
        result = update_approval_template(payload)
    except Exception as exc:
        failure = _leave_template_update_failure(template_id=template_id, error=str(exc))
        _record_template_notice_update(
            platform="wecom",
            template_id=template_id,
            notice_control_id=LEAVE_WORKFLOW_NOTICE_CONTROL_ID,
            operator_user_id=operator_user_id,
            notice_text=notice_text,
            result=failure,
        )
        return {**plan, **failure}
    _record_template_notice_update(
        platform="wecom",
        template_id=template_id,
        notice_control_id=LEAVE_WORKFLOW_NOTICE_CONTROL_ID,
        operator_user_id=operator_user_id,
        notice_text=notice_text,
        result=result,
    )
    return {**plan, "applied": True, "wecom_result": result}


def probe_negative_leave_quota(
    *,
    platform: str,
    user_id: str,
    vacation_id: int,
    negative_duration: int,
    confirm_live_write: bool = False,
    operator_user_id: str = "",
) -> dict[str, Any]:
    _validate_probe_args(user_id, vacation_id, negative_duration)
    normalized_platform = _normalize_platform(platform)
    if not confirm_live_write:
        result = {
            "platform": normalized_platform,
            "user_id": user_id,
            "vacation_id": int(vacation_id),
            "negative_duration": int(negative_duration),
            "negative_supported": None,
            "dry_run": True,
            "restored": False,
            "error": "",
            "message": "dry_run_only; set confirm_live_write=true to run a reversible live probe",
        }
        _record_probe_result(result, operator_user_id=operator_user_id)
        return result

    quota = get_user_vacation_quota(user_id)
    current = _find_quota_item(quota, vacation_id)
    original_left = int(current.get("leftduration") or 0)
    time_attr = _int_with_default(current.get("time_attr"), 1)
    vacation_name = _vacation_name(current)
    result = {
        "platform": normalized_platform,
        "user_id": user_id,
        "vacation_id": int(vacation_id),
        "vacation_name": vacation_name,
        "original_leftduration": original_left,
        "negative_duration": int(negative_duration),
        "negative_supported": False,
        "dry_run": False,
        "restored": False,
        "error": "",
    }
    marker = (
        "Ant Colony negative leave quota probe; "
        f"operator={operator_user_id or 'unknown'}; will restore immediately"
    )
    try:
        set_user_vacation_quota(
            user_id,
            vacation_id,
            int(negative_duration),
            time_attr=time_attr,
            remarks=marker,
        )
        result["negative_supported"] = True
    except Exception as exc:
        result["error"] = str(exc)
        _record_probe_result(result, operator_user_id=operator_user_id)
        return result
    finally:
        if result["negative_supported"]:
            try:
                set_user_vacation_quota(
                    user_id,
                    vacation_id,
                    original_left,
                    time_attr=time_attr,
                    remarks=(
                        "Ant Colony restored quota after negative probe; "
                        f"operator={operator_user_id or 'unknown'}"
                    ),
                )
                result["restored"] = True
            except Exception as exc:
                result["restore_error"] = str(exc)
    _record_probe_result(result, operator_user_id=operator_user_id)
    return result


def apply_leave_balance_target(
    *,
    platform: str,
    user_id: str,
    vacation_id: int,
    vacation_name: str = "",
    target_leftduration: int,
    time_attr: int,
    operator_user_id: str,
    reason: str,
    allow_local_negative: bool = False,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    target_leftduration = int(target_leftduration)
    if target_leftduration < 0 and not allow_local_negative:
        raise ValueError("allow_local_negative is required when target_leftduration is negative")
    try:
        set_user_vacation_quota(
            user_id,
            int(vacation_id),
            target_leftduration,
            time_attr=int(time_attr),
            remarks=_adjustment_remark(operator_user_id, reason),
        )
        mode = "wecom"
        external_synced = True
        error = ""
    except Exception as exc:
        if target_leftduration >= 0 or not allow_local_negative:
            raise
        mode = "local_negative_ledger"
        external_synced = False
        error = str(exc)
    _upsert_local_balance(
        platform=normalized_platform,
        user_id=user_id,
        vacation_id=int(vacation_id),
        vacation_name=vacation_name,
        leftduration=target_leftduration,
        time_attr=int(time_attr),
        source=mode,
    )
    _record_adjustment(
        platform=normalized_platform,
        user_id=user_id,
        vacation_id=int(vacation_id),
        vacation_name=vacation_name,
        target_leftduration=target_leftduration,
        time_attr=int(time_attr),
        operator_user_id=operator_user_id,
        reason=reason,
        mode=mode,
        external_synced=external_synced,
        error=error,
    )
    return {
        "platform": normalized_platform,
        "user_id": user_id,
        "vacation_id": int(vacation_id),
        "vacation_name": vacation_name,
        "target_leftduration": target_leftduration,
        "time_attr": int(time_attr),
        "mode": mode,
        "external_synced": external_synced,
        "error": error,
    }


def configure_leave_policy(
    *,
    platform: str,
    vacation_id: int,
    vacation_name: str,
    leave_kind: str,
    advance_seconds: int = 0,
    time_attr: int = 1,
    overtime_credit: bool = False,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    conn = _conn()
    conn.execute(
        """
        INSERT INTO leave_policies
            (platform, vacation_id, vacation_name, leave_kind, advance_seconds, time_attr, overtime_credit, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, vacation_id) DO UPDATE SET
            vacation_name = excluded.vacation_name,
            leave_kind = excluded.leave_kind,
            advance_seconds = excluded.advance_seconds,
            time_attr = excluded.time_attr,
            overtime_credit = excluded.overtime_credit,
            updated_at = excluded.updated_at
        """,
        (
            normalized_platform,
            int(vacation_id),
            str(vacation_name or ""),
            str(leave_kind or ""),
            max(0, int(advance_seconds or 0)),
            int(time_attr) if time_attr is not None else 1,
            int(bool(overtime_credit)),
            time.time(),
        ),
    )
    conn.commit()
    return _get_leave_policy(conn, normalized_platform, int(vacation_id))


def sync_leave_policies_from_wecom_config(*, platform: str = "wecom", only_when_empty: bool = False) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    if normalized_platform != "wecom":
        return {"platform": normalized_platform, "synced": 0, "skipped": "unsupported_platform", "errors": []}
    conn = _conn()
    existing = _list_leave_policies(conn, normalized_platform)
    if only_when_empty and existing:
        return {"platform": normalized_platform, "synced": 0, "skipped": "already_configured", "existing": len(existing), "errors": []}
    try:
        config = get_corp_vacation_config()
    except Exception as exc:
        return {"platform": normalized_platform, "synced": 0, "skipped": "fetch_failed", "errors": [str(exc)]}
    rows = _extract_vacation_config_rows(config)
    synced = 0
    errors: list[str] = []
    for row in rows:
        try:
            vacation_id = int(row.get("vacation_id") or row.get("id") or 0)
            if vacation_id <= 0:
                continue
            vacation_name = _extract_vacation_name(row)
            if not vacation_name:
                continue
            kind = _infer_leave_kind(vacation_name)
            configure_leave_policy(
                platform=normalized_platform,
                vacation_id=vacation_id,
                vacation_name=vacation_name,
                leave_kind=kind,
                advance_seconds=_default_advance_seconds(kind),
                time_attr=int(row.get("time_attr") if row.get("time_attr") is not None else 1),
                overtime_credit=(kind == "comp_time"),
            )
            synced += 1
        except Exception as exc:
            errors.append(str(exc))
    return {"platform": normalized_platform, "synced": synced, "source_count": len(rows), "errors": errors[:20]}


def list_leave_realtime_status(*, platform: str = "wecom") -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    conn = _conn()
    policies = _list_leave_policies(conn, normalized_platform)
    sync_rows = conn.execute(
        """
        SELECT user_id, vacation_id, target_leftduration, true_leftduration,
               pending_hold_seconds, advance_seconds, success, error, created_at
        FROM leave_wecom_quota_sync_logs
        WHERE platform = ?
        ORDER BY created_at DESC
        LIMIT 50
        """,
        (normalized_platform,),
    ).fetchall()
    event_row = conn.execute(
        """
        SELECT COUNT(*) AS total, MAX(updated_at) AS latest
        FROM approval_events
        WHERE platform = ?
        """,
        (normalized_platform,),
    ).fetchone()
    pending_row = conn.execute(
        """
        SELECT COUNT(*) AS total, COALESCE(SUM(duration_seconds), 0) AS seconds
        FROM leave_pending_holds
        WHERE platform = ? AND status = 'active'
        """,
        (normalized_platform,),
    ).fetchone()
    return {
        "platform": normalized_platform,
        "policies": policies,
        "approval_events": {
            "total": int(event_row["total"] or 0),
            "latest_updated_at": float(event_row["latest"] or 0),
        },
        "active_holds": {
            "total": int(pending_row["total"] or 0),
            "duration_seconds": int(pending_row["seconds"] or 0),
        },
        "recent_sync_logs": [dict(row) for row in sync_rows],
    }


def process_realtime_approval_event(event: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_event(event)
    conn = _conn()
    _record_approval_event(conn, normalized)
    business_type = normalized["business_type"]
    status = normalized["approval_status"]
    if business_type == "leave":
        if status == "pending":
            return _record_leave_hold(conn, normalized)
        if status == "approved":
            return _consume_approved_leave(conn, normalized)
        if status in {"rejected", "cancelled"}:
            return _release_leave_hold(conn, normalized)
    if business_type == "overtime" and status == "approved":
        return _credit_approved_overtime(conn, normalized)
    return {"action": "ignored", "event": normalized}


def build_employee_leave_form_notice(*, platform: str = "wecom", user_id: str) -> str:
    """Build employee-facing leave balance wording for the bot and admin UI.

    WeCom native leave quota is kept non-negative. Negative true balances are
    stored locally and presented as owed leave to avoid blocking form display.
    """

    normalized_platform = _normalize_platform(platform)
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")

    conn = _conn()
    policies = _list_leave_policies(conn, normalized_platform)
    if not policies:
        return "当前未同步公司假期类型，请联系人事专员或管理员先同步企微假期类型。"
    _bootstrap_missing_user_balances_from_wecom(conn, normalized_platform, uid, policies)

    lines = [
        "【真实假期余额提示】",
        "请以本提示为真实假期口径；企微请假页显示的是可申请额度，不显示欠休负数。",
    ]
    for policy in policies:
        vacation_id = int(policy["vacation_id"])
        vacation_name = str(policy.get("vacation_name") or f"假期 {vacation_id}")
        local_balance = _get_local_balance_row(conn, normalized_platform, uid, vacation_id)
        if not local_balance:
            lines.append(f"{vacation_name}：暂未读取到企微余额；请稍后重试，或联系人事专员核对")
            continue
        true_balance = int(local_balance["leftduration"])
        hold_seconds = _active_hold_seconds(conn, normalized_platform, uid, vacation_id)
        advance_seconds = int(policy.get("advance_seconds") or 0)
        wecom_apply_quota = max(0, true_balance + advance_seconds - hold_seconds)

        details: list[str] = []
        if hold_seconds > 0:
            details.append(f"审批中占用 {_format_leave_duration(hold_seconds)}")
        if advance_seconds > 0:
            details.append(f"允许预支 {_format_leave_duration(advance_seconds)}")
        details.append(f"企微可申请额度 {_format_leave_duration(wecom_apply_quota)}")
        lines.append(f"{_format_employee_leave_balance(vacation_name, true_balance)}；{'；'.join(details)}")

    return "\n".join(lines)


def _format_employee_leave_balance(vacation_name: str, seconds: int) -> str:
    if seconds < 0:
        return f"{vacation_name}：欠公司 {_format_leave_duration(abs(seconds))}，待后续加班调休冲抵"
    if seconds == 0:
        return f"{vacation_name}：当前无可用余额，也无欠假"
    return f"{vacation_name}：可用 {_format_leave_duration(seconds)}"


def _format_leave_duration(seconds: int) -> str:
    value = abs(int(seconds or 0))
    if value % 86400 == 0:
        return f"{value // 86400} 天"
    if value % 3600 == 0:
        return f"{value // 3600} 小时"
    days = value / 86400
    rendered = f"{days:.2f}".rstrip("0").rstrip(".")
    return f"{rendered} 天"


def _int_with_default(value: Any, default: int) -> int:
    if value is None or value == "":
        return int(default)
    return int(value)


def _approval_discovery_windows(window_seconds: int) -> list[int]:
    requested = max(60, int(window_seconds or 0))
    windows = [min(requested, 30 * 86400), 14 * 86400, 7 * 86400, 24 * 3600]
    deduped: list[int] = []
    for seconds in windows:
        if seconds not in deduped:
            deduped.append(seconds)
    return deduped


def _fetch_approval_ids_for_template_discovery(window_seconds: int, limit: int) -> tuple[dict[str, Any], str]:
    now = int(time.time())
    response, error = _post_optional_diagnostic(
        "oa/getapprovalinfo",
        {
            "starttime": now - max(60, int(window_seconds or 0)),
            "endtime": now,
            "cursor": 0,
            "size": min(max(int(limit or 100), 1), 100),
        },
        secret=_resolve_wecom_approval_secret(),
    )
    return response or {}, error


def _extract_template_candidate(detail: dict[str, Any]) -> dict[str, Any]:
    info = detail.get("info") or detail or {}
    return {
        "sp_no": str(info.get("sp_no") or "").strip(),
        "template_id": str(info.get("template_id") or "").strip(),
        "template_name": str(info.get("sp_name") or info.get("template_name") or "").strip(),
        "apply_time": str(info.get("apply_time") or "").strip(),
    }


def _bootstrap_missing_user_balances_from_wecom(conn: Any, platform: str, user_id: str, policies: list[dict[str, Any]]) -> None:
    if platform != "wecom":
        return
    policy_by_id = {int(policy["vacation_id"]): policy for policy in policies}
    missing_ids = {
        vacation_id
        for vacation_id in policy_by_id
        if not conn.execute(
            """
            SELECT 1 FROM leave_local_balances
            WHERE platform = ? AND user_id = ? AND vacation_id = ?
            """,
            (platform, user_id, vacation_id),
        ).fetchone()
    }
    if not missing_ids:
        return
    try:
        quota = get_user_vacation_quota(user_id)
    except Exception:
        return
    for item in quota.get("lists", []) or []:
        vacation_id = _quota_item_vacation_id(item)
        if vacation_id not in missing_ids:
            continue
        policy = policy_by_id[vacation_id]
        _upsert_local_balance(
            platform=platform,
            user_id=user_id,
            vacation_id=vacation_id,
            vacation_name=_vacation_name(item) or policy.get("vacation_name") or "",
            leftduration=int(item.get("leftduration") or 0),
            time_attr=_int_with_default(item.get("time_attr"), _int_with_default(policy.get("time_attr"), 1)),
            source="wecom_quota_bootstrap",
        )


def get_local_leave_balance(*, platform: str, user_id: str, vacation_id: int) -> dict[str, Any]:
    conn = _conn()
    row = _get_local_balance_row(conn, _normalize_platform(platform), user_id, int(vacation_id))
    return dict(row) if row else {}


def _get_local_balance_row(conn: Any, platform: str, user_id: str, vacation_id: int) -> Any:
    return conn.execute(
        """
        SELECT platform, user_id, vacation_id, vacation_name, leftduration, time_attr, source, updated_at
        FROM leave_local_balances
        WHERE platform = ? AND user_id = ? AND vacation_id = ?
        """,
        (platform, user_id, int(vacation_id)),
    ).fetchone()


def list_negative_probe_results(*, platform: str = "wecom", limit: int = 20) -> list[dict[str, Any]]:
    conn = _conn()
    rows = conn.execute(
        """
        SELECT platform, user_id, vacation_id, vacation_name, negative_duration,
               negative_supported, dry_run, restored, error, operator_user_id, created_at
        FROM leave_negative_probe_results
        WHERE platform = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (_normalize_platform(platform), int(limit)),
    ).fetchall()
    return [_public_probe_row(row) for row in rows]


def _conn():
    conn = Database.get().connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_negative_probe_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            vacation_id INTEGER NOT NULL,
            vacation_name TEXT NOT NULL DEFAULT '',
            original_leftduration INTEGER NOT NULL DEFAULT 0,
            negative_duration INTEGER NOT NULL,
            negative_supported INTEGER,
            dry_run INTEGER NOT NULL DEFAULT 0,
            restored INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            restore_error TEXT NOT NULL DEFAULT '',
            operator_user_id TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_local_balances (
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            vacation_id INTEGER NOT NULL,
            vacation_name TEXT NOT NULL DEFAULT '',
            leftduration INTEGER NOT NULL,
            time_attr INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'local',
            updated_at REAL NOT NULL,
            PRIMARY KEY (platform, user_id, vacation_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_quota_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            vacation_id INTEGER NOT NULL,
            vacation_name TEXT NOT NULL DEFAULT '',
            target_leftduration INTEGER NOT NULL,
            time_attr INTEGER NOT NULL DEFAULT 1,
            operator_user_id TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL,
            external_synced INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_template_notice_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            template_id TEXT NOT NULL,
            notice_control_id TEXT NOT NULL,
            operator_user_id TEXT NOT NULL DEFAULT '',
            notice_text TEXT NOT NULL DEFAULT '',
            result_json TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_policies (
            platform TEXT NOT NULL,
            vacation_id INTEGER NOT NULL,
            vacation_name TEXT NOT NULL DEFAULT '',
            leave_kind TEXT NOT NULL DEFAULT '',
            advance_seconds INTEGER NOT NULL DEFAULT 0,
            time_attr INTEGER NOT NULL DEFAULT 1,
            overtime_credit INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (platform, vacation_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_events (
            platform TEXT NOT NULL,
            sp_no TEXT NOT NULL,
            business_type TEXT NOT NULL,
            approval_status TEXT NOT NULL,
            applicant_user_id TEXT NOT NULL,
            vacation_id INTEGER NOT NULL DEFAULT 0,
            duration_seconds INTEGER NOT NULL DEFAULT 0,
            event_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (platform, sp_no)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_pending_holds (
            platform TEXT NOT NULL,
            sp_no TEXT NOT NULL,
            user_id TEXT NOT NULL,
            vacation_id INTEGER NOT NULL,
            vacation_name TEXT NOT NULL DEFAULT '',
            duration_seconds INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (platform, sp_no, user_id, vacation_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_approval_consumptions (
            platform TEXT NOT NULL,
            sp_no TEXT NOT NULL,
            user_id TEXT NOT NULL,
            vacation_id INTEGER NOT NULL,
            vacation_name TEXT NOT NULL DEFAULT '',
            duration_seconds INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (platform, sp_no, user_id, vacation_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_overtime_credits (
            platform TEXT NOT NULL,
            sp_no TEXT NOT NULL,
            user_id TEXT NOT NULL,
            vacation_id INTEGER NOT NULL,
            vacation_name TEXT NOT NULL DEFAULT '',
            duration_seconds INTEGER NOT NULL,
            balance_before INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (platform, sp_no, user_id, vacation_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_credit_offsets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            sp_no TEXT NOT NULL,
            user_id TEXT NOT NULL,
            vacation_id INTEGER NOT NULL,
            offset_seconds INTEGER NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_wecom_quota_sync_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            vacation_id INTEGER NOT NULL,
            target_leftduration INTEGER NOT NULL,
            true_leftduration INTEGER NOT NULL,
            pending_hold_seconds INTEGER NOT NULL,
            advance_seconds INTEGER NOT NULL,
            success INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _record_template_notice_update(
    *,
    platform: str,
    template_id: str,
    notice_control_id: str,
    operator_user_id: str,
    notice_text: str,
    result: dict[str, Any],
) -> None:
    import json

    conn = _conn()
    _execute_write_with_retry(
        conn,
        """
        INSERT INTO leave_template_notice_updates
            (platform, template_id, notice_control_id, operator_user_id, notice_text, result_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            platform,
            template_id,
            notice_control_id,
            operator_user_id,
            notice_text,
            json.dumps(result, ensure_ascii=False),
            time.time(),
        ),
    )


def _execute_write_with_retry(conn, sql: str, params: tuple[Any, ...], *, attempts: int = 5) -> None:
    for index in range(max(1, attempts)):
        try:
            conn.execute(sql, params)
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or index >= attempts - 1:
                raise
            try:
                conn.rollback()
            except Exception:
                pass
            time.sleep(0.1 * (index + 1))


def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    platform = _normalize_platform(str(event.get("platform") or "wecom"))
    sp_no = str(event.get("sp_no") or event.get("item_id") or "").strip()
    if not sp_no:
        raise ValueError("missing sp_no")
    user_id = str(event.get("applicant_user_id") or event.get("user_id") or "").strip()
    if not user_id:
        raise ValueError("missing applicant_user_id")
    status = _normalize_approval_status(event.get("approval_status") or event.get("status"))
    business_type = _normalize_business_type(event)
    duration_seconds = max(0, int(event.get("duration_seconds") or 0))
    vacation_id = int(event.get("vacation_id") or 0)
    if business_type in {"leave", "overtime"}:
        if vacation_id <= 0:
            raise ValueError("missing vacation_id")
        if duration_seconds <= 0:
            raise ValueError("missing duration_seconds")
    return {
        **event,
        "platform": platform,
        "sp_no": sp_no,
        "applicant_user_id": user_id,
        "approval_status": status,
        "business_type": business_type,
        "vacation_id": vacation_id,
        "vacation_name": str(event.get("vacation_name") or ""),
        "duration_seconds": duration_seconds,
    }


def _normalize_approval_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"approved", "pass", "passed", "2", "已通过", "通过", "审批通过"}:
        return "approved"
    if raw in {"rejected", "reject", "3", "驳回", "已驳回", "审批驳回"}:
        return "rejected"
    if raw in {"cancelled", "canceled", "4", "撤销", "已撤销", "取消"}:
        return "cancelled"
    return "pending"


def _normalize_business_type(event: dict[str, Any]) -> str:
    raw = str(event.get("business_type") or "").strip().lower()
    if raw in {"leave", "overtime"}:
        return raw
    text = f"{event.get('template_name') or ''} {event.get('title') or ''} {event.get('content') or ''}"
    if "加班" in text:
        return "overtime"
    if "请假" in text or "销假" in text or "调休" in text or "年假" in text or "病假" in text:
        return "leave"
    return raw or "other"


def _record_approval_event(conn: Any, event: dict[str, Any]) -> None:
    now = time.time()
    conn.execute(
        """
        INSERT INTO approval_events
            (platform, sp_no, business_type, approval_status, applicant_user_id,
             vacation_id, duration_seconds, event_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, sp_no) DO UPDATE SET
            business_type = excluded.business_type,
            approval_status = excluded.approval_status,
            applicant_user_id = excluded.applicant_user_id,
            vacation_id = excluded.vacation_id,
            duration_seconds = excluded.duration_seconds,
            event_json = excluded.event_json,
            updated_at = excluded.updated_at
        """,
        (
            event["platform"],
            event["sp_no"],
            event["business_type"],
            event["approval_status"],
            event["applicant_user_id"],
            int(event["vacation_id"]),
            int(event["duration_seconds"]),
            json.dumps(event, ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.commit()


def _record_leave_hold(conn: Any, event: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    conn.execute(
        """
        INSERT INTO leave_pending_holds
            (platform, sp_no, user_id, vacation_id, vacation_name, duration_seconds, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
        ON CONFLICT(platform, sp_no, user_id, vacation_id) DO UPDATE SET
            vacation_name = excluded.vacation_name,
            duration_seconds = excluded.duration_seconds,
            status = 'active',
            updated_at = excluded.updated_at
        """,
        (
            event["platform"],
            event["sp_no"],
            event["applicant_user_id"],
            int(event["vacation_id"]),
            event["vacation_name"],
            int(event["duration_seconds"]),
            now,
            now,
        ),
    )
    conn.commit()
    sync = _sync_wecom_apply_quota(conn, event["platform"], event["applicant_user_id"], int(event["vacation_id"]))
    return {"action": "leave_hold_recorded", "sync": sync}


def _release_leave_hold(conn: Any, event: dict[str, Any]) -> dict[str, Any]:
    conn.execute(
        """
        UPDATE leave_pending_holds
        SET status = 'released', updated_at = ?
        WHERE platform = ? AND sp_no = ? AND user_id = ? AND vacation_id = ? AND status = 'active'
        """,
        (time.time(), event["platform"], event["sp_no"], event["applicant_user_id"], int(event["vacation_id"])),
    )
    conn.commit()
    sync = _sync_wecom_apply_quota(conn, event["platform"], event["applicant_user_id"], int(event["vacation_id"]))
    return {"action": "leave_hold_released", "sync": sync}


def _consume_approved_leave(conn: Any, event: dict[str, Any]) -> dict[str, Any]:
    duplicate = conn.execute(
        """
        SELECT 1 FROM leave_approval_consumptions
        WHERE platform = ? AND sp_no = ? AND user_id = ? AND vacation_id = ?
        """,
        (event["platform"], event["sp_no"], event["applicant_user_id"], int(event["vacation_id"])),
    ).fetchone()
    if duplicate:
        return {"action": "duplicate_skipped"}
    current = _current_true_balance(conn, event["platform"], event["applicant_user_id"], int(event["vacation_id"]))
    balance_after = current - int(event["duration_seconds"])
    policy = _get_leave_policy(conn, event["platform"], int(event["vacation_id"]))
    _upsert_local_balance(
        platform=event["platform"],
        user_id=event["applicant_user_id"],
        vacation_id=int(event["vacation_id"]),
        vacation_name=event["vacation_name"] or policy.get("vacation_name") or "",
        leftduration=balance_after,
        time_attr=_int_with_default(policy.get("time_attr"), 1),
        source="approval_consumption",
    )
    conn.execute(
        """
        INSERT INTO leave_approval_consumptions
            (platform, sp_no, user_id, vacation_id, vacation_name, duration_seconds, balance_after, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["platform"],
            event["sp_no"],
            event["applicant_user_id"],
            int(event["vacation_id"]),
            event["vacation_name"] or policy.get("vacation_name") or "",
            int(event["duration_seconds"]),
            balance_after,
            time.time(),
        ),
    )
    conn.execute(
        """
        UPDATE leave_pending_holds
        SET status = 'consumed', updated_at = ?
        WHERE platform = ? AND sp_no = ? AND user_id = ? AND vacation_id = ? AND status = 'active'
        """,
        (time.time(), event["platform"], event["sp_no"], event["applicant_user_id"], int(event["vacation_id"])),
    )
    conn.commit()
    sync = _sync_wecom_apply_quota(conn, event["platform"], event["applicant_user_id"], int(event["vacation_id"]))
    return {"action": "leave_consumed", "balance_after": balance_after, "sync": sync}


def _credit_approved_overtime(conn: Any, event: dict[str, Any]) -> dict[str, Any]:
    duplicate = conn.execute(
        """
        SELECT 1 FROM leave_overtime_credits
        WHERE platform = ? AND sp_no = ? AND user_id = ? AND vacation_id = ?
        """,
        (event["platform"], event["sp_no"], event["applicant_user_id"], int(event["vacation_id"])),
    ).fetchone()
    if duplicate:
        return {"action": "duplicate_skipped"}
    current = _current_true_balance(conn, event["platform"], event["applicant_user_id"], int(event["vacation_id"]))
    balance_after = current + int(event["duration_seconds"])
    policy = _get_leave_policy(conn, event["platform"], int(event["vacation_id"]))
    if current < 0:
        conn.execute(
            """
            INSERT INTO leave_credit_offsets
                (platform, sp_no, user_id, vacation_id, offset_seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event["platform"],
                event["sp_no"],
                event["applicant_user_id"],
                int(event["vacation_id"]),
                min(abs(current), int(event["duration_seconds"])),
                time.time(),
            ),
        )
    _upsert_local_balance(
        platform=event["platform"],
        user_id=event["applicant_user_id"],
        vacation_id=int(event["vacation_id"]),
        vacation_name=event["vacation_name"] or policy.get("vacation_name") or "",
        leftduration=balance_after,
        time_attr=_int_with_default(policy.get("time_attr"), 1),
        source="overtime_credit",
    )
    conn.execute(
        """
        INSERT INTO leave_overtime_credits
            (platform, sp_no, user_id, vacation_id, vacation_name, duration_seconds,
             balance_before, balance_after, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["platform"],
            event["sp_no"],
            event["applicant_user_id"],
            int(event["vacation_id"]),
            event["vacation_name"] or policy.get("vacation_name") or "",
            int(event["duration_seconds"]),
            current,
            balance_after,
            time.time(),
        ),
    )
    conn.commit()
    sync = _sync_wecom_apply_quota(conn, event["platform"], event["applicant_user_id"], int(event["vacation_id"]))
    return {"action": "overtime_credited", "balance_after": balance_after, "sync": sync}


def _sync_wecom_apply_quota(conn: Any, platform: str, user_id: str, vacation_id: int) -> dict[str, Any]:
    policy = _get_leave_policy(conn, platform, vacation_id)
    true_balance = _current_true_balance(conn, platform, user_id, vacation_id)
    hold_seconds = _active_hold_seconds(conn, platform, user_id, vacation_id)
    advance_seconds = int(policy.get("advance_seconds") or 0)
    target = max(0, true_balance + advance_seconds - hold_seconds)
    error = ""
    success = False
    try:
        set_user_vacation_quota(
            user_id,
            vacation_id,
            target,
            time_attr=_int_with_default(policy.get("time_attr"), 1),
            remarks="Ant Colony synced apply quota from local leave ledger",
        )
        success = True
    except Exception as exc:
        error = str(exc)
    conn.execute(
        """
        INSERT INTO leave_wecom_quota_sync_logs
            (platform, user_id, vacation_id, target_leftduration, true_leftduration,
             pending_hold_seconds, advance_seconds, success, error, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (platform, user_id, vacation_id, target, true_balance, hold_seconds, advance_seconds, int(success), error, time.time()),
    )
    conn.commit()
    return {
        "target_leftduration": target,
        "true_leftduration": true_balance,
        "pending_hold_seconds": hold_seconds,
        "advance_seconds": advance_seconds,
        "success": success,
        "error": error,
    }


def _current_true_balance(conn: Any, platform: str, user_id: str, vacation_id: int) -> int:
    row = conn.execute(
        """
        SELECT leftduration FROM leave_local_balances
        WHERE platform = ? AND user_id = ? AND vacation_id = ?
        """,
        (platform, user_id, int(vacation_id)),
    ).fetchone()
    return int(row["leftduration"]) if row else 0


def _active_hold_seconds(conn: Any, platform: str, user_id: str, vacation_id: int) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(duration_seconds), 0) AS total
        FROM leave_pending_holds
        WHERE platform = ? AND user_id = ? AND vacation_id = ? AND status = 'active'
        """,
        (platform, user_id, int(vacation_id)),
    ).fetchone()
    return int(row["total"] or 0)


def _get_leave_policy(conn: Any, platform: str, vacation_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT platform, vacation_id, vacation_name, leave_kind, advance_seconds, time_attr, overtime_credit
        FROM leave_policies
        WHERE platform = ? AND vacation_id = ?
        """,
        (platform, int(vacation_id)),
    ).fetchone()
    if row:
        return dict(row)
    return {
        "platform": platform,
        "vacation_id": int(vacation_id),
        "vacation_name": "",
        "leave_kind": "",
        "advance_seconds": 0,
        "time_attr": 1,
        "overtime_credit": 0,
    }


def _list_leave_policies(conn: Any, platform: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT platform, vacation_id, vacation_name, leave_kind, advance_seconds, time_attr, overtime_credit
        FROM leave_policies
        WHERE platform = ?
        ORDER BY vacation_id
        """,
        (platform,),
    ).fetchall()
    return [dict(row) for row in rows]


def _extract_vacation_config_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("lists", "list", "vacation_list", "vacations"):
        value = config.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _extract_vacation_name(row: dict[str, Any]) -> str:
    for key in ("name", "vacation_name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    nested = row.get("vacationname") or row.get("vacation_name_i18n") or row.get("name_i18n")
    if isinstance(nested, dict):
        for key in ("zh_CN", "zh", "name", "text", "en"):
            value = str(nested.get(key) or "").strip()
            if value:
                return value
    return ""


def _infer_leave_kind(vacation_name: str) -> str:
    name = str(vacation_name or "").strip().lower()
    mapping = (
        ("annual", ("\u5e74\u5047", "annual")),
        ("sick", ("\u75c5\u5047", "sick")),
        ("personal", ("\u4e8b\u5047", "personal")),
        ("comp_time", ("\u8c03\u4f11", "\u5012\u4f11", "comp")),
        ("marriage", ("\u5a5a\u5047", "marriage")),
        ("maternity", ("\u4ea7\u5047", "\u4ea7\u68c0", "\u966a\u4ea7", "\u54fa\u4e73", "\u80b2\u513f", "maternity")),
        ("bereavement", ("\u4e27\u5047", "bereavement")),
        ("work_injury", ("\u5de5\u4f24",)),
    )
    for kind, tokens in mapping:
        if any(token in name for token in tokens):
            return kind
    return "other"


def _default_advance_seconds(leave_kind: str) -> int:
    if leave_kind != "comp_time":
        return 0
    raw = os.environ.get("ANT_COLONY_DEFAULT_COMP_TIME_ADVANCE_DAYS", "0").strip()
    try:
        days = max(0.0, float(raw or "0"))
    except ValueError:
        days = 0.0
    return int(days * 86400)


def _infer_vacation_from_text(conn: Any, platform: str, business_type: str, text: str, template_name: str = "") -> dict[str, Any]:
    policies = _list_leave_policies(conn, platform)
    haystack = f"{template_name}\n{text}"
    if business_type == "overtime":
        for policy in policies:
            if bool(policy.get("overtime_credit")):
                return policy
    for policy in policies:
        name = str(policy.get("vacation_name") or "")
        kind = str(policy.get("leave_kind") or "")
        if name and name in haystack:
            return policy
        if kind and kind in haystack:
            return policy
    if len(policies) == 1:
        return policies[0]
    return {}


def _parse_duration_seconds(text: str) -> int:
    raw = str(text or "")
    total = 0.0
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(天|日|小时|小時|h|H)", raw):
        value = float(match.group(1))
        unit = match.group(2)
        if unit in {"天", "日"}:
            total += value * 86400
        else:
            total += value * 3600
    if total:
        return int(total)
    seconds_match = re.search(r"duration_seconds[^\d]*(\d+)", raw)
    if seconds_match:
        return int(seconds_match.group(1))
    return 0


def _flatten_text(value: Any) -> str:
    parts: list[str] = []

    def walk(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, (str, int, float)):
            text = str(item).strip()
            if text:
                parts.append(text)
            return
        if isinstance(item, list):
            for child in item:
                walk(child)
            return
        if isinstance(item, dict):
            for key in ("text", "value", "title", "name", "control", "selector", "options", "contents", "children"):
                if key in item:
                    walk(item.get(key))
            for key, child in item.items():
                if key not in {"text", "value", "title", "name", "control", "selector", "options", "contents", "children"}:
                    walk(child)

    walk(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part not in seen:
            seen.add(part)
            deduped.append(part)
    return " ".join(deduped)


def _extract_callback_sp_no(payload: dict[str, Any]) -> str:
    for key in ("SpNo", "sp_no", "ApprovalNo", "ThirdNo"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    blob = "\n".join(str(value or "") for value in payload.values())
    match = re.search(r"<(?:SpNo|sp_no)><!\[CDATA\[(.*?)\]\]></(?:SpNo|sp_no)>", blob)
    if match:
        return match.group(1).strip()
    match = re.search(r"<(?:SpNo|sp_no)>(.*?)</(?:SpNo|sp_no)>", blob)
    if match:
        return match.group(1).strip()
    return ""


def _record_probe_result(result: dict[str, Any], *, operator_user_id: str) -> None:
    conn = _conn()
    supported = result.get("negative_supported")
    conn.execute(
        """
        INSERT INTO leave_negative_probe_results
            (platform, user_id, vacation_id, vacation_name, original_leftduration,
             negative_duration, negative_supported, dry_run, restored, error,
             restore_error, operator_user_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.get("platform") or "wecom",
            result.get("user_id") or "",
            int(result.get("vacation_id") or 0),
            result.get("vacation_name") or "",
            int(result.get("original_leftduration") or 0),
            int(result.get("negative_duration") or 0),
            None if supported is None else int(bool(supported)),
            int(bool(result.get("dry_run"))),
            int(bool(result.get("restored"))),
            str(result.get("error") or ""),
            str(result.get("restore_error") or ""),
            operator_user_id,
            time.time(),
        ),
    )
    conn.commit()


def _record_adjustment(**payload: Any) -> None:
    conn = _conn()
    conn.execute(
        """
        INSERT INTO leave_quota_adjustments
            (platform, user_id, vacation_id, vacation_name, target_leftduration,
             time_attr, operator_user_id, reason, mode, external_synced, error, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["platform"],
            payload["user_id"],
            int(payload["vacation_id"]),
            payload.get("vacation_name") or "",
            int(payload["target_leftduration"]),
            int(payload["time_attr"]),
            payload.get("operator_user_id") or "",
            payload.get("reason") or "",
            payload["mode"],
            int(bool(payload["external_synced"])),
            payload.get("error") or "",
            time.time(),
        ),
    )
    conn.commit()


def _upsert_local_balance(**payload: Any) -> None:
    conn = _conn()
    conn.execute(
        """
        INSERT INTO leave_local_balances
            (platform, user_id, vacation_id, vacation_name, leftduration, time_attr, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, user_id, vacation_id) DO UPDATE SET
            vacation_name = excluded.vacation_name,
            leftduration = excluded.leftduration,
            time_attr = excluded.time_attr,
            source = excluded.source,
            updated_at = excluded.updated_at
        """,
        (
            payload["platform"],
            payload["user_id"],
            int(payload["vacation_id"]),
            payload.get("vacation_name") or "",
            int(payload["leftduration"]),
            int(payload["time_attr"]),
            payload.get("source") or "local",
            time.time(),
        ),
    )
    conn.commit()


def _find_quota_item(quota: dict[str, Any], vacation_id: int) -> dict[str, Any]:
    for item in quota.get("lists", []) or []:
        if _quota_item_vacation_id(item) == int(vacation_id):
            return item
    raise ValueError(f"vacation quota not found: vacation_id={vacation_id}")


def _quota_item_vacation_id(item: dict[str, Any]) -> int:
    return int(item.get("vacation_id") or item.get("id") or 0)


def _extract_template_update_payload(template: dict[str, Any], *, fallback_template_id: str = "") -> dict[str, Any]:
    template_id = str(template.get("template_id") or "").strip()
    if not template_id:
        template_id = str((template.get("template") or {}).get("template_id") or "").strip()
    if not template_id:
        template_id = str(fallback_template_id or "").strip()
    if not template_id:
        raise ValueError("template detail does not include template_id")
    template_name = template.get("template_name")
    if template_name is None:
        template_name = template.get("template_names")
    if template_name is None:
        template_name = (template.get("template") or {}).get("template_name")
    if template_name is None:
        template_name = (template.get("template") or {}).get("template_names")
    template_content = template.get("template_content")
    if template_content is None:
        template_content = (template.get("template") or {}).get("template_content")
    if not isinstance(template_content, dict):
        raise ValueError("template detail does not include template_content")
    return {
        "template_id": template_id,
        "template_name": copy.deepcopy(template_name or []),
        "template_content": copy.deepcopy(template_content),
    }


def _leave_workflow_notice_control(notice_text: str) -> dict[str, Any]:
    return {
        "property": {
            "control": "Tips",
            "id": LEAVE_WORKFLOW_NOTICE_CONTROL_ID,
            "title": [{"text": notice_text, "lang": "zh_CN"}],
            "placeholder": [{"text": "", "lang": "zh_CN"}],
            "require": 0,
            "un_print": 1,
        },
        "config": {},
    }


def _leave_template_update_failure(*, template_id: str, error: str) -> dict[str, Any]:
    manual_steps = [
        "进入企业微信管理后台。",
        "打开“应用管理 - 审批 - 请假”模板。",
        "在表单中新增“说明/提示”类字段，标题填写“假期额度说明”。",
        f"说明内容填写：{DEFAULT_LEAVE_WORKFLOW_NOTICE}",
        "保存并发布模板后，用员工账号打开企业微信请假页面，确认能看到该说明。",
    ]
    return {
        "applied": False,
        "update_failed": True,
        "wecom_result": {"error": error},
        "message": (
            "企微拒绝自动更新请假模板，通常是当前租户的原生请假模板不允许通过 API "
            "原样回写既有假勤控件。系统已保留模板 ID 和失败审计，请按 manual_steps "
            "在企微后台手工添加说明。"
        ),
        "template_id": template_id,
        "manual_steps": manual_steps,
    }


def _vacation_name(item: dict[str, Any]) -> str:
    raw_name = item.get("vacationname") or item.get("name") or ""
    if isinstance(raw_name, dict):
        return str(raw_name.get("zh_CN") or raw_name.get("zh") or raw_name.get("en") or "unnamed_leave")
    return str(raw_name or "unnamed_leave")


def _validate_probe_args(user_id: str, vacation_id: int, negative_duration: int) -> None:
    if not user_id:
        raise ValueError("missing user_id")
    if int(vacation_id) <= 0:
        raise ValueError("missing valid vacation_id")
    if int(negative_duration) >= 0:
        raise ValueError("negative_duration must be less than 0")


def _adjustment_remark(operator_user_id: str, reason: str) -> str:
    text = (
        "Ant Colony leave quota adjustment; "
        f"operator={operator_user_id or 'unknown'}; reason={reason or 'not provided'}"
    )
    return text[:200]


def _normalize_platform(platform: str) -> str:
    return (platform or "wecom").strip().lower()


def _public_probe_row(row: Any) -> dict[str, Any]:
    return {
        "platform": row["platform"],
        "user_id": row["user_id"],
        "vacation_id": row["vacation_id"],
        "vacation_name": row["vacation_name"],
        "negative_duration": row["negative_duration"],
        "negative_supported": None if row["negative_supported"] is None else bool(row["negative_supported"]),
        "dry_run": bool(row["dry_run"]),
        "restored": bool(row["restored"]),
        "error": row["error"],
        "operator_user_id": row["operator_user_id"],
        "created_at": row["created_at"],
    }

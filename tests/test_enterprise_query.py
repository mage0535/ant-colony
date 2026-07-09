from __future__ import annotations

from datetime import date


def test_room_booking_question_stays_inside_meeting_room_domain() -> None:
    from src.platform.enterprise_query import plan_enterprise_query

    plan = plan_enterprise_query("三号会议室有人申请吗？")

    assert plan.domains == ("meeting_room",)
    assert plan.operation == "occupancy"
    assert plan.entities == ("三号会议室",)


def test_room_availability_question_is_not_treated_as_named_room() -> None:
    from src.platform.enterprise_query import plan_enterprise_query

    plan = plan_enterprise_query("哪个会议室今天可以申请")

    assert plan.domains == ("meeting_room",)
    assert plan.operation == "availability"
    assert plan.entities == ()
    assert plan.start_date == date.today().isoformat()


def test_personal_approval_query_uses_self_scope_only() -> None:
    from src.platform.enterprise_query import plan_enterprise_query

    plan = plan_enterprise_query("查询我所有审批的状态")

    assert plan.domains == ("approval",)
    assert plan.operation == "list"
    assert plan.user_scope == "self"


def test_explicit_summary_can_cross_domains() -> None:
    from src.platform.enterprise_query import plan_enterprise_query

    plan = plan_enterprise_query("汇总我今天的会议、审批和日程")

    assert plan.cross_domain is True
    assert plan.domains == ("meeting", "approval", "calendar")


def test_fuzzy_application_alias_resolves_to_approval() -> None:
    from src.platform.enterprise_query import plan_enterprise_query

    plan = plan_enterprise_query("查一下进入车间申批到哪了")

    assert plan.domains == ("approval",)
    assert plan.operation == "status"
    assert "进入车间" in plan.query_terms


def test_plain_workshop_access_question_is_not_forced_into_enterprise_apps() -> None:
    from src.platform.enterprise_query import plan_enterprise_query

    plan = plan_enterprise_query("目前车间通行是什么情况")

    assert plan.domains == ()


def test_workshop_entry_application_status_is_recognized_as_approval() -> None:
    from src.platform.enterprise_query import plan_enterprise_query

    plan = plan_enterprise_query("目前进入车间申请是什么情况")

    assert plan.domains == ("approval",)
    assert "进入车间" in plan.query_terms

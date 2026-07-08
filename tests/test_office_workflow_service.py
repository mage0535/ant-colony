from __future__ import annotations

from unittest.mock import patch

from src.models.contracts import MessageContext, SpaceType


def _context() -> MessageContext:
    return MessageContext(space_type=SpaceType.DEPARTMENT, space_id="dept-1", dept_id="dept-1", metadata={"provider": "wecom"})


def test_approval_followup_workflow_composes_capabilities_and_records_artifacts() -> None:
    from src.workflows.office_workflow_service import OfficeWorkflowService

    with patch("src.workflows.office_workflow_service.invoke_capability", side_effect=["审批列表", "邮件摘要"]), \
         patch("src.workflows.office_workflow_service.invoke_capability_first", side_effect=["审批详情", "制度内容"]), \
         patch("src.workflows.office_workflow_service._record_artifacts") as record:
        result = OfficeWorkflowService().approval_followup("u1", "付款审批卡在哪", _context())

    assert "审批列表" in result.content
    assert "审批详情" in result.content
    assert "邮件摘要" in result.content
    record.assert_called_once()


def test_meeting_coordination_workflow_composes_capabilities() -> None:
    from src.workflows.office_workflow_service import OfficeWorkflowService

    with patch("src.workflows.office_workflow_service.invoke_capability", side_effect=["日程列表", "会议列表"]), \
         patch("src.workflows.office_workflow_service.invoke_capability_first", return_value="会议资料"), \
         patch("src.workflows.office_workflow_service._record_artifacts"):
        result = OfficeWorkflowService().meeting_coordination("u1", "安排一次部门会议", _context())

    assert "日程列表" in result.content
    assert "会议列表" in result.content
    assert "会议资料" in result.content


def test_workorder_analysis_workflow_uses_business_capabilities() -> None:
    from src.workflows.office_workflow_service import OfficeWorkflowService

    with patch("src.workflows.office_workflow_service.invoke_capability_first", side_effect=['{"id":"WO-1001"}', "高风险", "制度内容"]), \
         patch("src.workflows.office_workflow_service._record_artifacts"):
        result = OfficeWorkflowService().workorder_analysis("u1", "分析工单 WO-1001", _context())

    assert "WO-1001" in result.content
    assert "高风险" in result.content

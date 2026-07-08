from __future__ import annotations

from typing import Any

from src.models.contracts import MessageContext, SpaceType
from src.workflows.office_workflow_service import OfficeWorkflowService


def _context_from_args(args: dict[str, Any]) -> MessageContext:
    space_type = SpaceType.PROJECT if str(args.get("scope") or args.get("space_type") or "project") == "project" else SpaceType.DEPARTMENT
    return MessageContext(
        space_type=space_type,
        space_id=str(args.get("scope_id") or args.get("space_id") or "default"),
        dept_id=str(args.get("dept_id") or "") or None,
        project_id=str(args.get("project_id") or "") or None,
        metadata={
            "provider": str(args.get("_source_provider") or args.get("platform") or "wecom"),
            "transport": str(args.get("_source_transport") or args.get("transport") or ""),
            "source_chat_id": str(args.get("source_chat_id") or ""),
        },
    )


def approval_followup_workflow_tool(args: dict[str, Any]) -> str:
    result = OfficeWorkflowService().approval_followup(str(args.get("user_id") or args.get("from") or ""), str(args.get("query") or args.get("content") or ""), _context_from_args(args))
    return result.content


def meeting_coordination_workflow_tool(args: dict[str, Any]) -> str:
    result = OfficeWorkflowService().meeting_coordination(str(args.get("user_id") or args.get("from") or ""), str(args.get("query") or args.get("content") or ""), _context_from_args(args))
    return result.content


def policy_drafting_workflow_tool(args: dict[str, Any]) -> str:
    result = OfficeWorkflowService().policy_drafting(str(args.get("user_id") or args.get("from") or ""), str(args.get("query") or args.get("content") or ""), _context_from_args(args))
    return result.content


def workorder_analysis_workflow_tool(args: dict[str, Any]) -> str:
    result = OfficeWorkflowService().workorder_analysis(str(args.get("user_id") or args.get("from") or ""), str(args.get("query") or args.get("content") or ""), _context_from_args(args))
    return result.content

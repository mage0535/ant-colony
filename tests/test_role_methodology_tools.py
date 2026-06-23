from __future__ import annotations
import unittest
from unittest.mock import patch


class TestRoleMethodologyTools(unittest.TestCase):
    def test_select_role_tool_returns_role_name_and_content(self) -> None:
        from src.tools.role_methodology_tools import select_role_tool

        fake_role = type("Role", (), {"name": "安全工程师", "content": "role-content"})
        with patch("src.platform.role_manager.select_role", return_value={"role": fake_role}):
            result = select_role_tool({"query": "安全审计"})

        self.assertIn("安全工程师", result)
        self.assertIn("role-content", result)

    def test_list_roles_tool_lists_categories(self) -> None:
        from src.tools.role_methodology_tools import list_roles_tool

        fake_role = type("Role", (), {"name": "前端开发者", "description": "做前端", "tags": ["react", "ui"]})
        with (
            patch("src.platform.role_manager.list_roles", return_value=[fake_role]),
            patch("src.platform.role_manager.list_categories", return_value=["engineering"]),
        ):
            result = list_roles_tool({})

        self.assertIn("前端开发者", result)
        self.assertIn("engineering", result)

    def test_set_role_tool_validates_name(self) -> None:
        from src.tools.role_methodology_tools import set_role_tool

        self.assertEqual(set_role_tool({"name": ""}), "请指定角色名称")

    def test_methodology_tools_delegate(self) -> None:
        from src.tools.role_methodology_tools import (
            investigate_tool,
            office_hours_tool,
            retro_tool,
            review_doc_tool,
            spec_tool_handler,
        )

        with (
            patch("src.tools.gstack_skills.office_hours", return_value="office-hours") as mock_office,
            patch("src.tools.gstack_skills.review_doc", return_value="review") as mock_review,
            patch("src.tools.gstack_skills.investigate", return_value="investigate") as mock_investigate,
            patch("src.tools.gstack_skills.spec_tool", return_value="spec") as mock_spec,
            patch("src.tools.gstack_skills.retro_tool", return_value="retro") as mock_retro,
        ):
            self.assertEqual(office_hours_tool({"goal": "g", "context": "c"}), "office-hours")
            self.assertEqual(review_doc_tool({"type": "code", "content": "x"}), "review")
            self.assertEqual(investigate_tool({"issue": "bug", "context": "ctx"}), "investigate")
            self.assertEqual(spec_tool_handler({"goal": "spec-goal"}), "spec")
            self.assertEqual(retro_tool({"period": "本周", "data": "x"}), "retro")

        mock_office.assert_called_once_with(goal="g", context="c")
        mock_review.assert_called_once_with(doc_type="code", content="x")
        mock_investigate.assert_called_once_with(issue="bug", context="ctx")
        mock_spec.assert_called_once_with(goal="spec-goal")
        mock_retro.assert_called_once_with(period="本周", data="x")

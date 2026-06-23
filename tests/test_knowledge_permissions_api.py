from __future__ import annotations

import unittest
from unittest.mock import patch


class TestKnowledgePermissionsApi(unittest.TestCase):
    def test_permissions_route_reports_leader_capabilities(self) -> None:
        from src.web.dashboard import knowledge_permissions

        fake_profile = {
            "departments": ["dept-2"],
            "leader_departments": ["dept-2"],
            "is_admin": False,
        }

        with patch("src.knowledge.acl.resolve_role") as mock_role, \
             patch("src.knowledge.acl.visible_scopes", return_value=[("organization", "*"), ("department", "dept-2")]), \
             patch("src.platform.org_graph.OrgGraphService.get_user_profile", return_value=fake_profile):
            mock_role.return_value = type("RoleValue", (), {"name": "leader", "value": 3})()
            result = knowledge_permissions("u-leader")

        self.assertEqual(result["role"], "leader")
        self.assertTrue(result["can_manage_organization"])
        self.assertIn("dept-2", result["managed_departments"])


if __name__ == "__main__":
    unittest.main()

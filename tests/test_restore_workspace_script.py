from __future__ import annotations

import unittest


class TestRestoreWorkspaceScript(unittest.TestCase):
    def test_iter_restore_paths_uses_defaults(self) -> None:
        from scripts.restore_workspace_from_server import DEFAULT_PATHS, iter_restore_paths

        self.assertEqual(iter_restore_paths(None), DEFAULT_PATHS)

    def test_iter_restore_paths_deduplicates_and_normalizes(self) -> None:
        from scripts.restore_workspace_from_server import iter_restore_paths

        result = iter_restore_paths(["src\\tools", "src/tools", " docs "])

        self.assertEqual(result, ["src/tools", "docs"])

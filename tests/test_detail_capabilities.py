from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch


class TestInternalDetailCapabilities(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mktemp(suffix=".db")
        os.environ["ANT_COLONY_DB_PATH"] = self.tmp

    def tearDown(self) -> None:
        from src.store.database import Database

        Database.get(self.tmp).close()
        Database._instances.pop(self.tmp, None)  # type: ignore[attr-defined]
        try:
            os.remove(self.tmp)
        except OSError:
            pass
        os.environ.pop("ANT_COLONY_DB_PATH", None)

    def test_read_drive_doc_uses_knowledge_repo(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        class FakeEntry:
            content = "制度正文"

        with patch("src.platform.internal_capability_provider.FtsKnowledgeRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.search.return_value = [FakeEntry()]
            result = InternalCapabilityProvider().read_drive_doc("制度")

        self.assertIn("制度正文", result)

    def test_read_docs_document_uses_knowledge_repo(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        class FakeEntry:
            content = "在线文档内容"

        with patch("src.platform.internal_capability_provider.FtsKnowledgeRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.search.return_value = [FakeEntry()]
            result = InternalCapabilityProvider().read_docs_document("沟通管理办法")

        self.assertIn("在线文档内容", result)


class TestPlatformDetailTools(unittest.TestCase):
    def test_read_drive_tool_uses_backend(self) -> None:
        from src.tools.platform_capability_tools import read_drive_tool

        with patch("src.platform.invoke_capability_first", return_value="drive-content") as mock_first:
            result = read_drive_tool({"query": "制度", "user_id": "u1"})

        self.assertEqual(mock_first.call_args.args[:2], ("drive.read", "制度"))
        self.assertEqual(result, "drive-content")

    def test_read_docs_tool_uses_backend(self) -> None:
        from src.tools.platform_capability_tools import read_docs_tool

        with patch("src.platform.invoke_capability_first", return_value="doc-content") as mock_first:
            result = read_docs_tool({"query": "流程"})

        self.assertEqual(mock_first.call_args.args[:2], ("docs.read", "流程"))
        self.assertEqual(result, "doc-content")

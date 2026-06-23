from __future__ import annotations
import unittest
from unittest.mock import patch


class TestDocumentPromptHelpers(unittest.TestCase):
    def test_build_requirement_spec_delegates(self) -> None:
        from src.tools.document_prompt_helpers import build_requirement_spec_helper

        with patch("src.tools.document_requirements.build_requirement_spec", return_value={"title": "x"}) as mock_build:
            result = build_requirement_spec_helper("t", "tpl", "req")

        mock_build.assert_called_once_with("t", "tpl", "req")
        self.assertEqual(result, {"title": "x"})

    def test_build_policy_fallback_content_delegates(self) -> None:
        from src.tools.document_prompt_helpers import build_policy_fallback_content_helper

        with patch("src.tools.document_requirements.build_policy_fallback_content", return_value="content") as mock_build:
            result = build_policy_fallback_content_helper("制度", "条目")

        mock_build.assert_called_once_with("制度", "条目")
        self.assertEqual(result, "content")

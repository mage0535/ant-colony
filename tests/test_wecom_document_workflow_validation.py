from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestWeComDocumentWorkflowValidation(unittest.TestCase):
    def test_validate_document_workflow_requires_probe_user(self) -> None:
        from scripts.validate_wecom_document_workflow import validate_document_workflow

        with patch("scripts.validate_wecom_document_workflow.pick_probe_user", return_value=""):
            report = validate_document_workflow()

        self.assertFalse(report["configured"])

    def test_validate_document_workflow_reports_push_success(self) -> None:
        from scripts.validate_wecom_document_workflow import validate_document_workflow

        with tempfile.TemporaryDirectory() as td:
            fake_template = Path(td) / "template.docx"
            fake_template.write_bytes(b"fake")
            with (
                patch("scripts.validate_wecom_document_workflow.pick_probe_user", return_value="u1"),
                patch("scripts.validate_wecom_document_workflow._default_template_path", return_value=str(fake_template)),
                patch("scripts.validate_wecom_document_workflow.prepare_template_candidate", return_value={"template_path": "/tmp/t.docx"}),
                patch("scripts.validate_wecom_document_workflow.generate_document", return_value=""),
            ):
                report = validate_document_workflow()

        self.assertTrue(report["configured"])
        self.assertTrue(report["pushed"])

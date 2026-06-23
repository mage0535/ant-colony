from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestInternalOfficeCapabilityProvider(unittest.TestCase):
    def test_healthcheck_office_returns_ready_when_officecli_exists(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.platform.internal_capability_provider.os.path.isfile", return_value=True):
            result = InternalCapabilityProvider().healthcheck_office()

        self.assertIn("officecli-ready", result)

    def test_generate_docx_document_uses_document_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.document_tool.generate_report", return_value="/tmp/report.docx") as mock_generate:
            result = InternalCapabilityProvider().generate_docx_document("Title", "Body", "/tmp/template.docx")

        mock_generate.assert_called_once_with("Title", "Body", "docx", template_path="/tmp/template.docx")
        self.assertEqual(result, "/tmp/report.docx")

    def test_generate_xlsx_document_uses_document_tool(self) -> None:
        from src.platform.officecli_provider import OfficeCliProvider

        with patch("src.tools.document_tool.generate_report", return_value="/tmp/report.xlsx") as mock_generate:
            result = OfficeCliProvider().generate_xlsx_document("Title", "Body", "/tmp/template.xlsx")

        mock_generate.assert_called_once_with("Title", "Body", "xlsx", template_path="/tmp/template.xlsx")
        self.assertEqual(result, "/tmp/report.xlsx")

    def test_generate_pptx_document_uses_document_tool(self) -> None:
        from src.platform.officecli_provider import OfficeCliProvider

        with patch("src.tools.document_tool.generate_report", return_value="/tmp/report.pptx") as mock_generate:
            result = OfficeCliProvider().generate_pptx_document("Title", "Body", "/tmp/template.pptx")

        mock_generate.assert_called_once_with("Title", "Body", "pptx", template_path="/tmp/template.pptx")
        self.assertEqual(result, "/tmp/report.pptx")

    def test_extract_docx_template_outline_uses_document_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.document_tool.extract_docx_template_outline", return_value={"paragraphs": [], "tables": []}) as mock_outline:
            result = InternalCapabilityProvider().extract_docx_template_outline("/tmp/template.docx")

        mock_outline.assert_called_once_with("/tmp/template.docx")
        self.assertEqual(result, {"paragraphs": [], "tables": []})

    def test_extract_xlsx_template_outline_uses_document_tool(self) -> None:
        from src.platform.officecli_provider import OfficeCliProvider

        with patch("src.tools.document_tool.extract_xlsx_template_outline", return_value={"sheets": []}) as mock_outline:
            result = OfficeCliProvider().extract_xlsx_template_outline("/tmp/template.xlsx")

        mock_outline.assert_called_once_with("/tmp/template.xlsx")
        self.assertEqual(result, {"sheets": []})

    def test_extract_pptx_template_outline_uses_document_tool(self) -> None:
        from src.platform.officecli_provider import OfficeCliProvider

        with patch("src.tools.document_tool.extract_pptx_template_outline", return_value={"slides": []}) as mock_outline:
            result = OfficeCliProvider().extract_pptx_template_outline("/tmp/template.pptx")

        mock_outline.assert_called_once_with("/tmp/template.pptx")
        self.assertEqual(result, {"slides": []})

    def test_read_docx_document_uses_provider(self) -> None:
        from src.platform.officecli_provider import OfficeCliProvider

        fake_doc = MagicMock()
        fake_doc.paragraphs = [MagicMock(text="First"), MagicMock(text="Second")]
        with patch("docx.Document", return_value=fake_doc):
            result = OfficeCliProvider().read_docx_document("/tmp/a.docx")

        self.assertIn("First", result)
        self.assertIn("Second", result)

    def test_read_xlsx_document_uses_provider(self) -> None:
        from src.platform.officecli_provider import OfficeCliProvider

        fake_ws = MagicMock()
        fake_ws.title = "Sheet1"
        fake_ws.iter_rows.return_value = [["A1", "B1"]]
        fake_wb = MagicMock()
        fake_wb.worksheets = [fake_ws]
        with patch("openpyxl.load_workbook", return_value=fake_wb):
            result = OfficeCliProvider().read_xlsx_document("/tmp/a.xlsx")

        self.assertIn("A1", result)
        self.assertIn("B1", result)

    def test_read_pptx_document_uses_provider(self) -> None:
        from src.platform.officecli_provider import OfficeCliProvider
        import sys
        import types

        shape = MagicMock()
        shape.has_text_frame = True
        shape.text = "Slide text"
        slide = MagicMock()
        slide.shapes = [shape]
        prs = MagicMock()
        prs.slides = [slide]
        fake_pptx = types.SimpleNamespace(Presentation=MagicMock(return_value=prs))
        with patch.dict(sys.modules, {"pptx": fake_pptx}):
            result = OfficeCliProvider().read_pptx_document("/tmp/a.pptx")

        self.assertIn("Slide text", result)


class TestPlatformOfficeCapabilityWrappers(unittest.TestCase):
    def test_office_service_status_uses_capability_backend(self) -> None:
        from src.platform import office_service_status

        backend = MagicMock()
        backend.invoke.return_value = [MagicMock(provider_label="系统能力", content="officecli-ready")]
        backend.format_results.return_value = "[系统能力] officecli-ready"

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = office_service_status()

        backend.invoke.assert_called_once_with("files.office.service_status")
        self.assertEqual(result, "[系统能力] officecli-ready")

    def test_generate_docx_uses_capability_backend(self) -> None:
        from src.platform import generate_docx

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="/tmp/report.docx")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = generate_docx("Title", "Body", "/tmp/template.docx")

        backend.invoke_first.assert_called_once_with("files.docx.generate", "Title", "Body", "/tmp/template.docx")
        self.assertEqual(result, "/tmp/report.docx")

    def test_generate_xlsx_uses_capability_backend(self) -> None:
        from src.platform import generate_xlsx

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="/tmp/report.xlsx")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = generate_xlsx("Title", "Body", "/tmp/template.xlsx")

        backend.invoke_first.assert_called_once_with("files.xlsx.generate", "Title", "Body", "/tmp/template.xlsx")
        self.assertEqual(result, "/tmp/report.xlsx")

    def test_generate_pptx_uses_capability_backend(self) -> None:
        from src.platform import generate_pptx

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="/tmp/report.pptx")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = generate_pptx("Title", "Body", "/tmp/template.pptx")

        backend.invoke_first.assert_called_once_with("files.pptx.generate", "Title", "Body", "/tmp/template.pptx")
        self.assertEqual(result, "/tmp/report.pptx")

    def test_docx_template_outline_uses_capability_backend(self) -> None:
        from src.platform import docx_template_outline

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content={"paragraphs": [], "tables": []})

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = docx_template_outline("/tmp/template.docx")

        backend.invoke_first.assert_called_once_with("files.docx.template_outline", "/tmp/template.docx")
        self.assertEqual(result, {"paragraphs": [], "tables": []})

    def test_xlsx_template_outline_uses_capability_backend(self) -> None:
        from src.platform import xlsx_template_outline

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content={"sheets": []})

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = xlsx_template_outline("/tmp/template.xlsx")

        backend.invoke_first.assert_called_once_with("files.xlsx.template_outline", "/tmp/template.xlsx")
        self.assertEqual(result, {"sheets": []})

    def test_pptx_template_outline_uses_capability_backend(self) -> None:
        from src.platform import pptx_template_outline

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content={"slides": []})

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = pptx_template_outline("/tmp/template.pptx")

        backend.invoke_first.assert_called_once_with("files.pptx.template_outline", "/tmp/template.pptx")
        self.assertEqual(result, {"slides": []})

    def test_read_docx_uses_capability_backend(self) -> None:
        from src.platform import read_docx

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="docx-text")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = read_docx("/tmp/a.docx")

        backend.invoke_first.assert_called_once_with("files.docx.read", "/tmp/a.docx")
        self.assertEqual(result, "docx-text")

    def test_read_xlsx_uses_capability_backend(self) -> None:
        from src.platform import read_xlsx

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="xlsx-text")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = read_xlsx("/tmp/a.xlsx")

        backend.invoke_first.assert_called_once_with("files.xlsx.read", "/tmp/a.xlsx")
        self.assertEqual(result, "xlsx-text")

    def test_read_pptx_uses_capability_backend(self) -> None:
        from src.platform import read_pptx

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="pptx-text")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = read_pptx("/tmp/a.pptx")

        backend.invoke_first.assert_called_once_with("files.pptx.read", "/tmp/a.pptx")
        self.assertEqual(result, "pptx-text")


class TestBuiltinOfficeCapabilityTools(unittest.TestCase):
    def test_office_service_status_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _office_service_status_tool

        with patch("src.platform.invoke_capability", return_value="office-status") as mock_invoke:
            result = _office_service_status_tool({})

        self.assertEqual(mock_invoke.call_args.args[:1], ("files.office.service_status",))
        self.assertEqual(result, "office-status")

    def test_docx_template_outline_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _docx_template_outline_tool

        with patch("src.platform.invoke_capability_first", return_value={"paragraphs": [], "tables": []}) as mock_invoke:
            result = _docx_template_outline_tool({"path": "/tmp/template.docx"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("files.docx.template_outline", "/tmp/template.docx"))
        self.assertEqual(result, {"paragraphs": [], "tables": []})

    def test_xlsx_template_outline_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _xlsx_template_outline_tool

        with patch("src.platform.invoke_capability_first", return_value={"sheets": []}) as mock_invoke:
            result = _xlsx_template_outline_tool({"path": "/tmp/template.xlsx"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("files.xlsx.template_outline", "/tmp/template.xlsx"))
        self.assertEqual(result, {"sheets": []})

    def test_pptx_template_outline_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _pptx_template_outline_tool

        with patch("src.platform.invoke_capability_first", return_value={"slides": []}) as mock_invoke:
            result = _pptx_template_outline_tool({"path": "/tmp/template.pptx"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("files.pptx.template_outline", "/tmp/template.pptx"))
        self.assertEqual(result, {"slides": []})

    def test_read_docx_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _read_docx_tool

        with patch("src.platform.invoke_capability_first", return_value="docx-text") as mock_invoke:
            result = _read_docx_tool({"path": "/tmp/a.docx"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("files.docx.read", "/tmp/a.docx"))
        self.assertEqual(result, "docx-text")

    def test_read_xlsx_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _read_xlsx_tool

        with patch("src.platform.invoke_capability_first", return_value="xlsx-text") as mock_invoke:
            result = _read_xlsx_tool({"path": "/tmp/a.xlsx"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("files.xlsx.read", "/tmp/a.xlsx"))
        self.assertEqual(result, "xlsx-text")

    def test_read_pptx_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _read_pptx_tool

        with patch("src.platform.invoke_capability_first", return_value="pptx-text") as mock_invoke:
            result = _read_pptx_tool({"path": "/tmp/a.pptx"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("files.pptx.read", "/tmp/a.pptx"))
        self.assertEqual(result, "pptx-text")

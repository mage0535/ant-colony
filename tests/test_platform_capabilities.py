from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestPlatformCapabilityWrappers(unittest.TestCase):
    def test_drive_search_uses_capability_backend(self) -> None:
        from src.platform import drive_search

        backend = MagicMock()
        backend.invoke.return_value = [MagicMock(provider_label="企业微信", content="file-a")]
        backend.format_results.return_value = "[企业微信] file-a"

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = drive_search("template")

        backend.invoke.assert_called_once_with("drive.search", "template")
        self.assertEqual(result, "[企业微信] file-a")

    def test_mail_summary_uses_capability_backend(self) -> None:
        from src.platform import mail_summary

        backend = MagicMock()
        backend.invoke.return_value = [MagicMock(provider_label="飞书", content="mail-summary")]
        backend.format_results.return_value = "[飞书] mail-summary"

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = mail_summary("today")

        backend.invoke.assert_called_once_with("mail.summary", "today")
        self.assertEqual(result, "[飞书] mail-summary")

    def test_mail_summary_returns_empty_message_when_backend_empty(self) -> None:
        from src.platform import mail_summary

        backend = MagicMock()
        backend.invoke.return_value = []
        backend.format_results.return_value = "暂无可用邮箱能力（待接入企业邮箱能力）"

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = mail_summary("")

        backend.invoke.assert_called_once_with("mail.summary", "")
        self.assertEqual(result, "暂无可用邮箱能力（待接入企业邮箱能力）")

    def test_list_capabilities_formats_backend_descriptions(self) -> None:
        from src.platform import list_capabilities

        backend = MagicMock()
        backend.list_capabilities.return_value = ["contacts.search", "mail.summary"]
        backend.describe_capability.side_effect = [
            {"capability_id": "contacts.search", "method_name": "search_user", "providers": ["企业微信", "飞书"]},
            {"capability_id": "mail.summary", "method_name": "summarize_mailbox", "providers": ["系统能力"]},
        ]

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = list_capabilities()

        self.assertIn("contacts.search", result)
        self.assertIn("企业微信, 飞书", result)
        self.assertIn("mail.summary", result)
        self.assertIn("系统能力", result)

    def test_merge_pdfs_uses_capability_backend(self) -> None:
        from src.platform import merge_pdfs

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="merged-result")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = merge_pdfs(["a.pdf", "b.pdf"], "merged.pdf")

        backend.invoke_first.assert_called_once_with("files.pdf.merge", ["a.pdf", "b.pdf"], "merged.pdf")
        self.assertEqual(result, "merged-result")

    def test_protect_pdf_uses_capability_backend(self) -> None:
        from src.platform import protect_pdf

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="protected-result")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = protect_pdf("a.pdf", "pwd", "out.pdf")

        backend.invoke_first.assert_called_once_with("files.pdf.protect", "a.pdf", "pwd", "out.pdf")
        self.assertEqual(result, "protected-result")

    def test_read_pdf_uses_capability_backend(self) -> None:
        from src.platform import read_pdf

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="pdf-text")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = read_pdf("a.pdf")

        backend.invoke_first.assert_called_once_with("files.pdf.read", "a.pdf")
        self.assertEqual(result, "pdf-text")

    def test_extract_pdf_images_uses_capability_backend(self) -> None:
        from src.platform import extract_pdf_images

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="images-result")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = extract_pdf_images("a.pdf", "out-dir")

        backend.invoke_first.assert_called_once_with("files.pdf.extract_images", "a.pdf", "out-dir")
        self.assertEqual(result, "images-result")

    def test_watermark_pdf_uses_capability_backend(self) -> None:
        from src.platform import watermark_pdf

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="watermarked-result")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = watermark_pdf("a.pdf", "CONFIDENTIAL", "out.pdf")

        backend.invoke_first.assert_called_once_with("files.pdf.watermark", "a.pdf", "CONFIDENTIAL", "out.pdf")
        self.assertEqual(result, "watermarked-result")

    def test_pdf_service_status_uses_capability_backend(self) -> None:
        from src.platform import pdf_service_status

        backend = MagicMock()
        backend.invoke.return_value = [MagicMock(provider_label="Stirling-PDF", content="UP")]
        backend.format_results.return_value = "[Stirling-PDF] UP"

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = pdf_service_status()

        backend.invoke.assert_called_once_with("files.pdf.service_status")
        self.assertEqual(result, "[Stirling-PDF] UP")

    def test_ocr_pdf_uses_capability_backend(self) -> None:
        from src.platform import ocr_pdf

        backend = MagicMock()
        backend.invoke_first.return_value = MagicMock(content="ocr-result")

        with patch("src.platform.get_capability_backend", return_value=backend):
            result = ocr_pdf("a.pdf", "out.pdf", "chi_sim+eng")

        backend.invoke_first.assert_called_once_with("files.pdf.ocr", "a.pdf", "out.pdf", "chi_sim+eng")
        self.assertEqual(result, "ocr-result")


class TestBuiltinCapabilityTools(unittest.TestCase):
    def test_drive_search_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _drive_search_tool

        with patch("src.platform.invoke_capability", return_value="drive-result") as mock_invoke:
            result = _drive_search_tool({"query": "template", "user_id": "u1", "_source_provider": "wecom_bot"})

        mock_invoke.assert_called_once()
        self.assertEqual(mock_invoke.call_args.args[:2], ("drive.search", "template"))
        self.assertEqual(mock_invoke.call_args.kwargs["context"]["user_id"], "u1")
        self.assertEqual(result, "drive-result")

    def test_mail_summary_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _mail_summary_tool

        with patch("src.platform.invoke_capability", return_value="mail-result") as mock_invoke:
            result = _mail_summary_tool({"query": "today"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("mail.summary", "today"))
        self.assertEqual(result, "mail-result")

    def test_list_capabilities_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _list_capabilities_tool

        with patch("src.platform.list_capabilities", return_value="capability-list") as mock_list:
            result = _list_capabilities_tool({})

        mock_list.assert_called_once_with()
        self.assertEqual(result, "capability-list")

    def test_merge_pdfs_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _merge_pdfs_tool

        with patch("src.platform.invoke_capability_first", return_value="merged-result") as mock_invoke:
            result = _merge_pdfs_tool({"paths": "a.pdf,b.pdf", "output": "merged.pdf"})

        self.assertEqual(mock_invoke.call_args.args[:3], ("files.pdf.merge", ["a.pdf", "b.pdf"], "merged.pdf"))
        self.assertEqual(result, "merged-result")

    def test_protect_pdf_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _protect_pdf_tool

        with patch("src.platform.invoke_capability_first", return_value="protected-result") as mock_invoke:
            result = _protect_pdf_tool({"path": "a.pdf", "password": "pwd", "output": "out.pdf"})

        self.assertEqual(mock_invoke.call_args.args[:4], ("files.pdf.protect", "a.pdf", "pwd", "out.pdf"))
        self.assertEqual(result, "protected-result")

    def test_read_pdf_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _read_pdf_tool

        with patch("src.platform.invoke_capability_first", return_value="pdf-text") as mock_invoke:
            result = _read_pdf_tool({"path": "a.pdf"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("files.pdf.read", "a.pdf"))
        self.assertEqual(result, "pdf-text")

    def test_extract_pdf_images_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _extract_pdf_images_tool

        with patch("src.platform.invoke_capability_first", return_value="images-result") as mock_invoke:
            result = _extract_pdf_images_tool({"path": "a.pdf", "output_dir": "out-dir"})

        self.assertEqual(mock_invoke.call_args.args[:3], ("files.pdf.extract_images", "a.pdf", "out-dir"))
        self.assertEqual(result, "images-result")

    def test_watermark_pdf_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _watermark_pdf_tool

        with patch("src.platform.invoke_capability_first", return_value="watermarked-result") as mock_invoke:
            result = _watermark_pdf_tool({"path": "a.pdf", "watermark": "CONFIDENTIAL", "output": "out.pdf"})

        self.assertEqual(mock_invoke.call_args.args[:4], ("files.pdf.watermark", "a.pdf", "CONFIDENTIAL", "out.pdf"))
        self.assertEqual(result, "watermarked-result")

    def test_pdf_service_status_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _pdf_service_status_tool

        with patch("src.platform.invoke_capability", return_value="status-result") as mock_invoke:
            result = _pdf_service_status_tool({})

        self.assertEqual(mock_invoke.call_args.args[:1], ("files.pdf.service_status",))
        self.assertEqual(result, "status-result")

    def test_ocr_pdf_tool_delegates_to_platform(self) -> None:
        from src.tools.builtin import _ocr_pdf_tool

        with patch("src.platform.invoke_capability_first", return_value="ocr-result") as mock_invoke:
            result = _ocr_pdf_tool({"path": "a.pdf", "output": "out.pdf", "language": "chi_sim+eng"})

        self.assertEqual(mock_invoke.call_args.args[:4], ("files.pdf.ocr", "a.pdf", "out.pdf", "chi_sim+eng"))
        self.assertEqual(result, "ocr-result")


class TestExtendedCapabilityTools(unittest.TestCase):
    def test_email_capability_tools_use_backend(self) -> None:
        from src.tools.email_capability_tools import get_email_tool, list_emails_tool, search_emails_tool, send_email_tool

        with patch("src.platform.invoke_capability_first", return_value="sent") as mock_first:
            result = send_email_tool({"to": "a@test.local", "subject": "s", "body": "b", "cc": "c@test.local"})
        self.assertEqual(mock_first.call_args.args[:5], ("mail.send", "a@test.local", "s", "b", "c@test.local"))
        self.assertEqual(result, "sent")

        with patch("src.platform.invoke_capability", return_value="listed") as mock_invoke:
            result = list_emails_tool({"limit": 5})
        self.assertEqual(mock_invoke.call_args.args[:2], ("mail.list", 5))
        self.assertEqual(result, "listed")

        with patch("src.platform.invoke_capability", return_value="searched") as mock_invoke:
            result = search_emails_tool({"query": "invoice"})
        self.assertEqual(mock_invoke.call_args.args[:2], ("mail.search", "invoice"))
        self.assertEqual(result, "searched")

        with patch("src.platform.invoke_capability_first", return_value="body") as mock_first:
            result = get_email_tool({"uid": "42"})
        self.assertEqual(mock_first.call_args.args[:2], ("mail.get", "42"))
        self.assertEqual(result, "body")

    def test_knowledge_drive_tools_use_backend_for_list_and_sync(self) -> None:
        from src.tools.knowledge_tools import list_cloud_drives_tool, sync_from_cloud_tool

        with patch("src.platform.invoke_capability", return_value="drive-list") as mock_invoke:
            result = list_cloud_drives_tool({"user_id": "u1"})
        self.assertEqual(mock_invoke.call_args.args[:1], ("drive.list",))
        self.assertEqual(result, "drive-list")

        with patch("src.platform.invoke_capability_first", return_value="synced") as mock_first:
            result = sync_from_cloud_tool({"drive_id": "d1", "remote_path": "/r", "local_path": "/l", "user_id": "u1"})
        self.assertEqual(mock_first.call_args.args[:4], ("drive.sync", "d1", "/r", "/l"))
        self.assertEqual(result, "synced")

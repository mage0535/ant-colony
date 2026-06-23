from __future__ import annotations

import unittest
from unittest.mock import patch


class TestInternalCapabilityProvider(unittest.TestCase):
    def test_generate_docx_document_uses_document_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.document_tool.generate_report", return_value="/tmp/report.docx") as mock_generate:
            result = InternalCapabilityProvider().generate_docx_document("Title", "Body", "/tmp/template.docx")

        mock_generate.assert_called_once_with("Title", "Body", "docx", template_path="/tmp/template.docx")
        self.assertEqual(result, "/tmp/report.docx")

    def test_generate_xlsx_document_uses_document_tool_with_template(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.document_tool.generate_report", return_value="/tmp/report.xlsx") as mock_generate:
            result = InternalCapabilityProvider().generate_xlsx_document("Title", "Body", "/tmp/template.xlsx")

        mock_generate.assert_called_once_with("Title", "Body", "xlsx", template_path="/tmp/template.xlsx")
        self.assertEqual(result, "/tmp/report.xlsx")

    def test_generate_pptx_document_uses_document_tool_with_template(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.document_tool.generate_report", return_value="/tmp/report.pptx") as mock_generate:
            result = InternalCapabilityProvider().generate_pptx_document("Title", "Body", "/tmp/template.pptx")

        mock_generate.assert_called_once_with("Title", "Body", "pptx", template_path="/tmp/template.pptx")
        self.assertEqual(result, "/tmp/report.pptx")

    def test_extract_docx_template_outline_uses_document_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.document_tool.extract_docx_template_outline", return_value={"paragraphs": []}) as mock_outline:
            result = InternalCapabilityProvider().extract_docx_template_outline("/tmp/template.docx")

        mock_outline.assert_called_once_with("/tmp/template.docx")
        self.assertEqual(result, {"paragraphs": []})

    def test_extract_xlsx_template_outline_uses_document_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.document_tool.extract_xlsx_template_outline", return_value={"sheets": []}) as mock_outline:
            result = InternalCapabilityProvider().extract_xlsx_template_outline("/tmp/template.xlsx")

        mock_outline.assert_called_once_with("/tmp/template.xlsx")
        self.assertEqual(result, {"sheets": []})

    def test_extract_pptx_template_outline_uses_document_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.document_tool.extract_pptx_template_outline", return_value={"slides": []}) as mock_outline:
            result = InternalCapabilityProvider().extract_pptx_template_outline("/tmp/template.pptx")

        mock_outline.assert_called_once_with("/tmp/template.pptx")
        self.assertEqual(result, {"slides": []})

    def test_read_docx_document_uses_officecli_provider(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.platform.officecli_provider.OfficeCliProvider.read_docx_document", return_value="docx-text") as mock_read:
            result = InternalCapabilityProvider().read_docx_document("/tmp/a.docx")

        mock_read.assert_called_once_with("/tmp/a.docx")
        self.assertEqual(result, "docx-text")

    def test_read_xlsx_document_uses_officecli_provider(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.platform.officecli_provider.OfficeCliProvider.read_xlsx_document", return_value="xlsx-text") as mock_read:
            result = InternalCapabilityProvider().read_xlsx_document("/tmp/a.xlsx")

        mock_read.assert_called_once_with("/tmp/a.xlsx")
        self.assertEqual(result, "xlsx-text")

    def test_read_pptx_document_uses_officecli_provider(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.platform.officecli_provider.OfficeCliProvider.read_pptx_document", return_value="pptx-text") as mock_read:
            result = InternalCapabilityProvider().read_pptx_document("/tmp/a.pptx")

        mock_read.assert_called_once_with("/tmp/a.pptx")
        self.assertEqual(result, "pptx-text")

    def test_search_drive_docs_uses_cloud_drive_listing(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.knowledge.cloud_drive.list_drives", return_value="已配置云盘\nDrive-A (OneDrive)") as mock_list:
            result = InternalCapabilityProvider().search_drive_docs("Drive")

        mock_list.assert_called_once_with(user_id="")
        self.assertIn("Drive-A", result)

    def test_search_drive_docs_filters_out_non_matching_query(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.knowledge.cloud_drive.list_drives", return_value="已配置云盘\nDrive-A (OneDrive)"):
            result = InternalCapabilityProvider().search_drive_docs("Drive-B")

        self.assertIn("未找到", result)

    def test_summarize_mailbox_uses_list_inbox_without_query(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.email_tool.list_inbox", return_value="[1] Subject A") as mock_list_inbox:
            result = InternalCapabilityProvider().summarize_mailbox("")

        mock_list_inbox.assert_called_once_with(limit=10)
        self.assertIn("Subject A", result)

    def test_summarize_mailbox_uses_search_with_query(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.email_tool.search_emails", return_value="[2] Subject B") as mock_search:
            result = InternalCapabilityProvider().summarize_mailbox("today")

        mock_search.assert_called_once_with("today")
        self.assertIn("Subject B", result)

    def test_list_drive_docs_uses_cloud_drive_listing(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.knowledge.cloud_drive.list_drives", return_value="Drive-A") as mock_list:
            result = InternalCapabilityProvider().list_drive_docs()

        mock_list.assert_called_once_with(user_id="")
        self.assertEqual(result, "Drive-A")

    def test_sync_drive_docs_uses_cloud_drive_sync(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.knowledge.cloud_drive.sync_from_cloud", return_value="synced") as mock_sync:
            result = InternalCapabilityProvider().sync_drive_docs("d1", "/remote", "/local")

        mock_sync.assert_called_once_with(drive_id="d1", remote_path="/remote", local_path="/local", user_id="")
        self.assertEqual(result, "synced")

    def test_list_mail_messages_uses_email_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.email_tool.list_inbox", return_value="mail-list") as mock_list:
            result = InternalCapabilityProvider().list_mail_messages(limit=5)

        mock_list.assert_called_once_with(limit=5)
        self.assertEqual(result, "mail-list")

    def test_get_mail_message_uses_email_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.email_tool.get_email", return_value="mail-body") as mock_get:
            result = InternalCapabilityProvider().get_mail_message("42")

        mock_get.assert_called_once_with(uid="42")
        self.assertEqual(result, "mail-body")

    def test_send_mail_message_uses_email_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.email_tool.send_email", return_value="sent") as mock_send:
            result = InternalCapabilityProvider().send_mail_message("a@test.local", "s", "b", "c@test.local")

        mock_send.assert_called_once_with(to="a@test.local", subject="s", body="b", cc="c@test.local")
        self.assertEqual(result, "sent")

    def test_merge_pdf_documents_uses_pdf_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.pdf_tool.merge_pdfs", return_value="merged") as mock_merge:
            result = InternalCapabilityProvider().merge_pdf_documents(["a.pdf", "b.pdf"], "merged.pdf")

        mock_merge.assert_called_once_with(["a.pdf", "b.pdf"], "merged.pdf")
        self.assertEqual(result, "merged")

    def test_split_pdf_document_uses_pdf_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.pdf_tool.split_pdf", return_value="split") as mock_split:
            result = InternalCapabilityProvider().split_pdf_document("a.pdf", "1-2", "split.pdf")

        mock_split.assert_called_once_with("a.pdf", "1-2", "split.pdf")
        self.assertEqual(result, "split")

    def test_compress_pdf_document_uses_pdf_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.pdf_tool.compress_pdf", return_value="compressed") as mock_compress:
            result = InternalCapabilityProvider().compress_pdf_document("a.pdf", "compressed.pdf")

        mock_compress.assert_called_once_with("a.pdf", "compressed.pdf")
        self.assertEqual(result, "compressed")

    def test_protect_pdf_document_uses_pdf_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.pdf_tool.protect_pdf", return_value="protected") as mock_protect:
            result = InternalCapabilityProvider().protect_pdf_document("a.pdf", "pwd", "protected.pdf")

        mock_protect.assert_called_once_with("a.pdf", "pwd", "protected.pdf")
        self.assertEqual(result, "protected")

    def test_read_pdf_document_uses_pdf_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.pdf_tool.read_pdf", return_value="pdf text") as mock_read:
            result = InternalCapabilityProvider().read_pdf_document("a.pdf")

        mock_read.assert_called_once_with("a.pdf")
        self.assertEqual(result, "pdf text")

    def test_extract_pdf_images_uses_pdf_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.pdf_tool.extract_images", return_value="images") as mock_extract:
            result = InternalCapabilityProvider().extract_pdf_images("a.pdf", "out-dir")

        mock_extract.assert_called_once_with("a.pdf", "out-dir")
        self.assertEqual(result, "images")

    def test_watermark_pdf_document_uses_pdf_tool(self) -> None:
        from src.platform.internal_capability_provider import InternalCapabilityProvider

        with patch("src.tools.pdf_tool.add_watermark", return_value="watermarked") as mock_watermark:
            result = InternalCapabilityProvider().watermark_pdf_document("a.pdf", "CONFIDENTIAL", "out.pdf")

        mock_watermark.assert_called_once_with("a.pdf", "CONFIDENTIAL", "out.pdf")
        self.assertEqual(result, "watermarked")

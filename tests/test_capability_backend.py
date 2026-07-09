from __future__ import annotations

import unittest


class TestCapabilityBackend(unittest.TestCase):
    def test_call_all_collects_multiple_provider_results(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider

        class ClientA:
            def search_user(self, query: str) -> str:
                return f"A:{query}"

        class ClientB:
            def search_user(self, query: str) -> str:
                return f"B:{query}"

        backend = CapabilityBackend(
            [
                CapabilityProvider("a", "A", lambda: ClientA()),
                CapabilityProvider("b", "B", lambda: ClientB()),
            ]
        )

        results = backend.call_all("search_user", "mage")

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].content, "A:mage")
        self.assertEqual(results[1].content, "B:mage")

    def test_call_all_filters_by_provider(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider

        class ClientA:
            def search_user(self, query: str) -> str:
                return f"A:{query}"

        class ClientB:
            def search_user(self, query: str) -> str:
                return f"B:{query}"

        backend = CapabilityBackend(
            [
                CapabilityProvider("a", "A", lambda: ClientA()),
                CapabilityProvider("b", "B", lambda: ClientB()),
            ]
        )

        results = backend.call_all("search_user", "mage", providers={"b"})

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].provider, "b")

    def test_format_results_returns_empty_message_when_no_result(self) -> None:
        from src.platform.capability_backend import CapabilityBackend

        backend = CapabilityBackend([])

        self.assertEqual(backend.format_results([], "empty"), "empty")

    def test_invoke_uses_registered_capability_spec(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider

        class ClientA:
            def search_user(self, query: str) -> str:
                return f"A:{query}"

        backend = CapabilityBackend(
            [
                CapabilityProvider("a", "A", lambda: ClientA()),
            ]
        )

        results = backend.invoke("contacts.search", "mage")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "A:mage")

    def test_invoke_respects_capability_provider_filter(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider, CapabilitySpec

        class ClientA:
            def create_doc(self, title: str, content: str = "") -> str:
                return f"A:{title}"

        class ClientB:
            def create_doc(self, title: str, content: str = "") -> str:
                return f"B:{title}"

        backend = CapabilityBackend(
            [
                CapabilityProvider("a", "A", lambda: ClientA()),
                CapabilityProvider("b", "B", lambda: ClientB()),
            ],
            capabilities={
                "docs.create": CapabilitySpec("docs.create", "create_doc", frozenset({"b"})),
            },
        )

        results = backend.invoke("docs.create", "report", "")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].provider, "b")

    def test_invoke_first_prefers_successful_provider_result(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider, CapabilitySpec

        class BrokenClient:
            def merge_pdf_documents(self, paths, output):
                raise RuntimeError("provider-a failed")

        class WorkingClient:
            def merge_pdf_documents(self, paths, output):
                return "provider-b ok"

        backend = CapabilityBackend(
            [
                CapabilityProvider("a", "A", lambda: BrokenClient()),
                CapabilityProvider("b", "B", lambda: WorkingClient()),
            ],
            capabilities={
                "files.pdf.merge": CapabilitySpec("files.pdf.merge", "merge_pdf_documents", frozenset({"a", "b"})),
            },
        )

        result = backend.invoke_first("files.pdf.merge", ["a.pdf"], "out.pdf")

        self.assertIsNotNone(result)
        self.assertEqual(result.provider, "b")
        self.assertTrue(result.success)
        self.assertEqual(result.content, "provider-b ok")

    def test_failed_provider_errors_are_not_formatted_for_users(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, PlatformCapabilityResult

        backend = CapabilityBackend([])
        text = backend.format_results(
            [PlatformCapabilityResult("wecom", "企业微信", "HTTP Error 404: Not Found", success=False)],
            "empty",
        )

        self.assertEqual(text, "empty")

    def test_supports_reports_known_capability(self) -> None:
        from src.platform.capability_backend import CapabilityBackend

        backend = CapabilityBackend([])

        self.assertTrue(backend.supports("contacts.search"))
        self.assertFalse(backend.supports("unknown.capability"))

    def test_list_capabilities_returns_sorted_capability_ids(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilitySpec

        backend = CapabilityBackend(
            [],
            capabilities={
                "docs.search": CapabilitySpec("docs.search", "search_docs"),
                "calendar.list": CapabilitySpec("calendar.list", "get_agenda"),
            },
        )

        self.assertEqual(backend.list_capabilities(), ["calendar.list", "docs.search"])

    def test_describe_capability_includes_provider_labels(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider, CapabilitySpec

        backend = CapabilityBackend(
            [
                CapabilityProvider("internal", "系统能力", lambda: object()),
                CapabilityProvider("wecom", "企业微信", lambda: object()),
            ],
            capabilities={
                "docs.create": CapabilitySpec("docs.create", "create_doc", frozenset({"wecom"})),
                "mail.summary": CapabilitySpec("mail.summary", "summarize_mailbox"),
            },
        )

        self.assertEqual(
            backend.describe_capability("docs.create"),
            {
                "capability_id": "docs.create",
                "method_name": "create_doc",
                "providers": ["企业微信"],
            },
        )
        self.assertEqual(
            backend.describe_capability("mail.summary"),
            {
                "capability_id": "mail.summary",
                "method_name": "summarize_mailbox",
                "providers": ["系统能力", "企业微信"],
            },
        )

    def test_describe_capability_includes_metadata_fields_when_present(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider, CapabilitySpec

        backend = CapabilityBackend(
            [CapabilityProvider("wecom", "企业微信", lambda: object())],
            capabilities={
                "docs.create": CapabilitySpec(
                    "docs.create",
                    "create_doc",
                    frozenset({"wecom"}),
                    risk_level="medium",
                    domain="docs",
                    requires_user_context=True,
                    audit_scope="sensitive",
                ),
            },
        )

        self.assertEqual(
            backend.describe_capability("docs.create"),
            {
                "capability_id": "docs.create",
                "method_name": "create_doc",
                "providers": ["企业微信"],
                "risk_level": "medium",
                "domain": "docs",
                "requires_user_context": True,
                "audit_scope": "sensitive",
            },
        )

    def test_pdf_capabilities_registered_to_internal_provider(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider

        backend = CapabilityBackend(
            [
                CapabilityProvider("stirling", "Stirling-PDF", lambda: object()),
                CapabilityProvider("internal", "系统能力", lambda: object()),
                CapabilityProvider("wecom", "企业微信", lambda: object()),
            ]
        )

        self.assertTrue(backend.supports("files.pdf.merge"))
        self.assertEqual(
            backend.describe_capability("files.pdf.merge"),
            {
                "capability_id": "files.pdf.merge",
                "method_name": "merge_pdf_documents",
                "providers": ["Stirling-PDF", "系统能力"],
            },
        )
        self.assertEqual(
            backend.describe_capability("files.pdf.read"),
            {
                "capability_id": "files.pdf.read",
                "method_name": "read_pdf_document",
                "providers": ["Stirling-PDF", "系统能力"],
            },
        )
        self.assertEqual(
            backend.describe_capability("files.pdf.compress"),
            {
                "capability_id": "files.pdf.compress",
                "method_name": "compress_pdf_document",
                "providers": ["Stirling-PDF", "系统能力"],
            },
        )
        self.assertEqual(
            backend.describe_capability("files.pdf.split"),
            {
                "capability_id": "files.pdf.split",
                "method_name": "split_pdf_document",
                "providers": ["Stirling-PDF", "系统能力"],
            },
        )
        self.assertEqual(
            backend.describe_capability("files.pdf.protect"),
            {
                "capability_id": "files.pdf.protect",
                "method_name": "protect_pdf_document",
                "providers": ["Stirling-PDF", "系统能力"],
            },
        )
        self.assertEqual(
            backend.describe_capability("files.pdf.extract_images"),
            {
                "capability_id": "files.pdf.extract_images",
                "method_name": "extract_pdf_images",
                "providers": ["Stirling-PDF", "系统能力"],
            },
        )

    def test_pdf_service_status_capability_registered(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider

        backend = CapabilityBackend(
            [
                CapabilityProvider("stirling", "Stirling-PDF", lambda: object()),
                CapabilityProvider("internal", "系统能力", lambda: object()),
            ]
        )

        self.assertEqual(
            backend.describe_capability("files.pdf.service_status"),
            {
                "capability_id": "files.pdf.service_status",
                "method_name": "healthcheck",
                "providers": ["Stirling-PDF", "系统能力"],
            },
        )

    def test_pdf_ocr_capability_registered(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider

        backend = CapabilityBackend(
            [
                CapabilityProvider("ocrmypdf", "OCRmyPDF", lambda: object()),
                CapabilityProvider("internal", "系统能力", lambda: object()),
            ]
        )

        self.assertEqual(
            backend.describe_capability("files.pdf.ocr"),
            {
                "capability_id": "files.pdf.ocr",
                "method_name": "ocr_pdf_document",
                "providers": ["OCRmyPDF"],
            },
        )

    def test_office_capabilities_registered_to_officecli_provider(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider

        backend = CapabilityBackend(
            [
                CapabilityProvider("officecli", "OfficeCLI", lambda: object()),
                CapabilityProvider("internal", "系统能力", lambda: object()),
            ]
        )

        self.assertEqual(
            backend.describe_capability("files.office.service_status"),
            {
                "capability_id": "files.office.service_status",
                "method_name": "healthcheck_office",
                "providers": ["OfficeCLI", "系统能力"],
            },
        )
        self.assertEqual(
            backend.describe_capability("files.docx.generate"),
            {
                "capability_id": "files.docx.generate",
                "method_name": "generate_docx_document",
                "providers": ["OfficeCLI", "系统能力"],
            },
        )
        self.assertEqual(
            backend.describe_capability("files.xlsx.read"),
            {
                "capability_id": "files.xlsx.read",
                "method_name": "read_xlsx_document",
                "providers": ["OfficeCLI", "系统能力"],
            },
        )
        self.assertEqual(
            backend.describe_capability("files.pptx.template_outline"),
            {
                "capability_id": "files.pptx.template_outline",
                "method_name": "extract_pptx_template_outline",
                "providers": ["OfficeCLI", "系统能力"],
            },
        )

    def test_office_capabilities_fall_back_to_internal_provider(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider, CapabilitySpec

        class BrokenOfficeCli:
            def generate_xlsx_document(self, title: str, content: str, template_path: str | None = None) -> str:
                raise RuntimeError("officecli unavailable")

        class InternalProvider:
            def generate_xlsx_document(self, title: str, content: str, template_path: str | None = None) -> str:
                return f"internal:{title}:{template_path}"

        backend = CapabilityBackend(
            [
                CapabilityProvider("officecli", "OfficeCLI", lambda: BrokenOfficeCli()),
                CapabilityProvider("internal", "绯荤粺鑳藉姏", lambda: InternalProvider()),
            ],
            capabilities={
                "files.xlsx.generate": CapabilitySpec(
                    "files.xlsx.generate",
                    "generate_xlsx_document",
                    frozenset({"officecli", "internal"}),
                )
            },
        )

        result = backend.invoke_first("files.xlsx.generate", "Title", "Body", "/tmp/template.xlsx")

        self.assertIsNotNone(result)
        self.assertEqual(result.provider, "internal")
        self.assertTrue(result.success)
        self.assertEqual(result.content, "internal:Title:/tmp/template.xlsx")

    def test_extended_internal_productivity_capabilities_are_registered(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider

        backend = CapabilityBackend([CapabilityProvider("internal", "系统能力", lambda: object())])

        self.assertEqual(
            backend.describe_capability("drive.list"),
            {
                "capability_id": "drive.list",
                "method_name": "list_drive_docs",
                "providers": ["系统能力"],
                "domain": "drive",
            },
        )
        self.assertEqual(
            backend.describe_capability("drive.sync"),
            {
                "capability_id": "drive.sync",
                "method_name": "sync_drive_docs",
                "providers": ["系统能力"],
                "risk_level": "medium",
                "domain": "drive",
                "requires_user_context": True,
            },
        )
        self.assertEqual(
            backend.describe_capability("mail.send"),
            {
                "capability_id": "mail.send",
                "method_name": "send_mail_message",
                "providers": ["系统能力"],
                "risk_level": "medium",
                "domain": "mail",
                "requires_user_context": True,
                "audit_scope": "sensitive",
            },
        )
        self.assertEqual(
            backend.describe_capability("im.entry.menu"),
            {
                "capability_id": "im.entry.menu",
                "method_name": "build_entry_menu",
                "providers": ["系统能力"],
                "domain": "im",
                "requires_user_context": True,
            },
        )
        self.assertEqual(
            backend.describe_capability("im.entry.payloads"),
            {
                "capability_id": "im.entry.payloads",
                "method_name": "build_entry_payloads",
                "providers": ["系统能力"],
                "domain": "im",
                "requires_user_context": True,
            },
        )
        self.assertEqual(
            backend.describe_capability("ops.workorder.lookup"),
            {
                "capability_id": "ops.workorder.lookup",
                "method_name": "lookup_workorder",
                "providers": ["系统能力"],
                "domain": "operations",
                "requires_user_context": True,
            },
        )
        self.assertEqual(
            backend.describe_capability("ops.workorder.analyze"),
            {
                "capability_id": "ops.workorder.analyze",
                "method_name": "analyze_workorder",
                "providers": ["系统能力"],
                "domain": "operations",
                "requires_user_context": True,
            },
        )
        self.assertEqual(
            backend.describe_capability("apps.query"),
            {
                "capability_id": "apps.query",
                "method_name": "query_enterprise_apps",
                "providers": ["系统能力"],
                "domain": "apps",
                "requires_user_context": True,
            },
        )
        self.assertEqual(
            backend.describe_capability("meeting.room.query"),
            {
                "capability_id": "meeting.room.query",
                "method_name": "query_meeting_room",
                "providers": ["系统能力"],
                "domain": "meeting",
                "requires_user_context": True,
            },
        )
        self.assertEqual(
            backend.describe_capability("mail.get"),
            {
                "capability_id": "mail.get",
                "method_name": "get_mail_message",
                "providers": ["系统能力"],
                "risk_level": "medium",
                "domain": "mail",
                "requires_user_context": True,
            },
        )

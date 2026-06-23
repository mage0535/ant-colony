from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestCapabilityAudit(unittest.TestCase):
    def test_invoke_records_audit_with_context(self) -> None:
        from src.platform.capability_backend import CapabilityBackend, CapabilityProvider

        class Client:
            def search_user(self, query: str) -> str:
                return f"A:{query}"

        with tempfile.TemporaryDirectory() as td:
            audit_db = Path(td) / "audit.sqlite3"
            with patch("src.platform.capability_audit._AUDIT_DIR", Path(td)), patch(
                "src.platform.capability_audit._AUDIT_DB_FILE", audit_db
            ):
                backend = CapabilityBackend([CapabilityProvider("a", "A", lambda: Client())])
                results = backend.invoke(
                    "contacts.search",
                    "mage",
                    context={"user_id": "u1", "platform": "wecom_bot", "scope": "personal"},
                )

                self.assertEqual(len(results), 1)
                from src.platform.capability_audit import iter_capability_audit_records

                payload = iter_capability_audit_records()[0]
                self.assertEqual(payload["capability_id"], "contacts.search")
                self.assertEqual(payload["provider_id"], "a")
                self.assertEqual(payload["context"]["user_id"], "u1")
                self.assertEqual(payload["context"]["platform"], "wecom_bot")

    def test_record_capability_audit_rotates_large_file(self) -> None:
        from src.platform.capability_audit import CapabilityInvocationContext, record_capability_audit

        with tempfile.TemporaryDirectory() as td:
            audit_dir = Path(td)
            audit_file = audit_dir / "capability_invocations.jsonl"
            rotated_file = audit_dir / "capability_invocations.jsonl.1"
            audit_file.write_text("x" * 1024, encoding="utf-8")
            with (
                patch("src.platform.capability_audit._AUDIT_DIR", audit_dir),
                patch("src.platform.capability_audit._AUDIT_FILE", audit_file),
                patch("src.platform.capability_audit._LEGACY_AUDIT_FILE", audit_file),
                patch("src.platform.capability_audit._AUDIT_DB_FILE", audit_dir / "audit.sqlite3"),
                patch("src.platform.capability_audit._MAX_AUDIT_BYTES", 16),
            ):
                record_capability_audit(
                    "contacts.search",
                    "a",
                    "A",
                    True,
                    CapabilityInvocationContext(user_id="u1"),
                    {"method_name": "search_user"},
                )

            self.assertTrue(rotated_file.exists())
            self.assertTrue((audit_dir / "audit.sqlite3").exists())

    def test_iter_capability_audit_records_filters_by_capability(self) -> None:
        from src.platform.capability_audit import iter_capability_audit_records

        with tempfile.TemporaryDirectory() as td:
            audit_db = Path(td) / "audit.db"
            with patch("src.platform.capability_audit._AUDIT_DB_FILE", audit_db):
                from src.platform.capability_audit import CapabilityInvocationContext, record_capability_audit

                record_capability_audit("contacts.search", "a", "A", True, CapabilityInvocationContext(user_id="u1"))
                record_capability_audit("docs.search", "b", "B", False, CapabilityInvocationContext(user_id="u2"))
                rows = list(iter_capability_audit_records(capability_id="contacts.search"))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider_id"], "a")

    def test_iter_capability_audit_records_filters_by_success(self) -> None:
        from src.platform.capability_audit import CapabilityInvocationContext, iter_capability_audit_records, record_capability_audit

        with tempfile.TemporaryDirectory() as td:
            audit_db = Path(td) / "audit.db"
            with patch("src.platform.capability_audit._AUDIT_DB_FILE", audit_db):
                record_capability_audit("contacts.search", "a", "A", True, CapabilityInvocationContext(user_id="u1"))
                record_capability_audit("contacts.search", "a", "A", False, CapabilityInvocationContext(user_id="u1"))
                rows = list(iter_capability_audit_records(capability_id="contacts.search", success=False))

        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["success"])

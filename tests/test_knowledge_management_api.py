from __future__ import annotations

import unittest
from io import BytesIO
from unittest.mock import patch

from starlette.datastructures import UploadFile
from fastapi import Request, Response


class TestKnowledgeManagementApi(unittest.TestCase):
    def test_search_knowledge_route_prefers_accessible_search_when_user_present(self) -> None:
        from src.web.dashboard import search_knowledge
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

        entry = KnowledgeEntry(
            id="k1",
            owner_type=KnowledgeOwnerType.ORGANIZATION,
            owner_id="*",
            content="企业微信 AI 助手激活说明书\n\n正文",
            tags=["guide"],
            metadata={"title": "企业微信 AI 助手激活说明书"},
        )
        fake_repo = type("Repo", (), {"search_accessible": lambda self, query, user_id="", space_id="", limit=20: [entry]})()

        with patch("src.web.dashboard.get_knowledge_repo", return_value=fake_repo):
            result = search_knowledge("激活", user_id="u1", space_id="", limit=10)

        self.assertEqual(result["results"][0]["title"], "企业微信 AI 助手激活说明书")
        self.assertIn("/api/v1/knowledge/k1/open", result["results"][0]["open_url"])

    def test_import_company_guides_api_returns_imported_entries(self) -> None:
        from src.web.dashboard import import_company_guides_api
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

        entries = [
            KnowledgeEntry(
                id="company-guide-wecom-activation",
                owner_type=KnowledgeOwnerType.ORGANIZATION,
                owner_id="*",
                content="content",
                tags=["guide"],
                metadata={"title": "企业微信 AI 助手激活说明书"},
            )
        ]

        from src.knowledge.acl import Role

        with patch("src.knowledge.acl.resolve_role", return_value=Role.admin), \
             patch("src.web.dashboard.get_knowledge_repo", return_value=object()), \
             patch("src.knowledge.company_guides.import_company_guides", return_value=entries):
            result = import_company_guides_api(user_id="u-admin")

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["entries"][0]["title"], "企业微信 AI 助手激活说明书")

    def test_open_knowledge_entry_renders_html(self) -> None:
        from src.web.dashboard import open_knowledge_entry
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

        entry = KnowledgeEntry(
            id="k1",
            owner_type=KnowledgeOwnerType.ORGANIZATION,
            owner_id="*",
            content="企业微信 AI 助手激活说明书\n\n正文内容",
            tags=["guide"],
            metadata={"title": "企业微信 AI 助手激活说明书"},
        )
        fake_repo = type("Repo", (), {"get": lambda self, entry_id: entry})()

        with patch("src.web.dashboard.get_knowledge_repo", return_value=fake_repo):
            response = open_knowledge_entry("k1")

        self.assertIn("企业微信 AI 助手激活说明书", response.body.decode("utf-8"))

    def test_collect_knowledge_uses_auto_owner_from_org_permissions(self) -> None:
        from src.web.dashboard import KnowledgeCollectRequest, collect_knowledge
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

        saved: dict[str, str] = {}

        class FakeCollector:
            def __init__(self, repo) -> None:
                self.repo = repo

            def collect_text(self, text, title, owner_type="project", owner_id="*", tags=None):
                saved["owner_type"] = owner_type
                saved["owner_id"] = owner_id
                return KnowledgeEntry(
                    id="k-auto",
                    owner_type=KnowledgeOwnerType(owner_type),
                    owner_id=owner_id,
                    content=text,
                    tags=tags or [],
                    metadata={"title": title},
                )

        with patch("src.web.dashboard.get_knowledge_repo", return_value=object()), \
             patch("src.web.dashboard.KnowledgeCollector", FakeCollector), \
             patch("src.web.dashboard._resolve_auto_knowledge_owner", return_value=("department", "dept-2")), \
             patch("src.knowledge.acl.resolve_role", return_value=type("RoleValue", (), {"value": 3})()), \
             patch("src.knowledge.acl.may_write", return_value=True):
            result = collect_knowledge(KnowledgeCollectRequest(text="hello", title="title", user_id="u-leader"))

        self.assertEqual(saved, {"owner_type": "department", "owner_id": "dept-2"})
        self.assertEqual(result["owner_type"], "department")

    def test_upload_file_uses_auto_owner_and_indexes_document(self) -> None:
        from src.web.dashboard import upload_file

        saved: dict[str, str] = {}

        class FakeStore:
            _base = "unused"

            def write(self, user_id: str, space_id: str, filename: str, content: bytes) -> str:
                saved["stored_user"] = user_id
                saved["stored_space"] = space_id
                saved["stored_filename"] = filename
                saved["stored_content"] = content.decode("utf-8")
                return "u1/demo.txt"

        class FakeCollector:
            def __init__(self, repo) -> None:
                self.repo = repo

            def collect_file(self, filepath: str, owner_type: str = "project", owner_id: str = "*", tags=None):
                saved["owner_type"] = owner_type
                saved["owner_id"] = owner_id
                return type("Entry", (), {"id": "file-indexed"})()

        upload = UploadFile(file=BytesIO("文档内容".encode("utf-8")), filename="demo.txt")
        with patch("src.web.dashboard._get_file_store", return_value=FakeStore()), \
             patch("src.web.dashboard.os.path.join", return_value="unused/u1/demo.txt"), \
             patch("src.web.dashboard.KnowledgeCollector", FakeCollector), \
             patch("src.web.dashboard.build_knowledge_repository", return_value=object()), \
             patch("src.web.dashboard._resolve_auto_knowledge_owner", return_value=("department", "dept-2")), \
             patch("src.knowledge.acl.resolve_role", return_value=type("RoleValue", (), {"value": 3})()), \
             patch("src.knowledge.acl.may_write", return_value=True):
            result = upload_file(
                file=upload,
                user_id="u1",
                space_id="",
                knowledge_owner_type="auto",
                knowledge_owner_id="",
            )

        self.assertEqual(result["indexed"], "file-indexed")
        self.assertEqual(result["knowledge_owner_type"], "department")
        self.assertEqual(result["knowledge_owner_id"], "dept-2")
        self.assertEqual(saved["owner_type"], "department")
        self.assertEqual(saved["owner_id"], "dept-2")

    def test_knowledge_manage_page_is_public_shell_but_admin_apis_stay_protected(self) -> None:
        import asyncio
        from src.web.dashboard import auth_and_rate_limit

        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/knowledge/manage",
                "raw_path": b"/knowledge/manage",
                "query_string": b"",
                "headers": [],
                "client": ("10.0.0.8", 12345),
                "server": ("127.0.0.1", 18092),
            }
        )

        async def call_next(_: Request) -> Response:
            return Response("ok")

        with patch("src.web.dashboard.require_auth") as auth, patch("src.web.dashboard.check_rate_limit"):
            response = asyncio.run(auth_and_rate_limit(request, call_next))

        self.assertEqual(response.status_code, 200)
        auth.assert_not_called()


if __name__ == "__main__":
    unittest.main()

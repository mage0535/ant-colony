from __future__ import annotations

import asyncio
import io
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request, Response, UploadFile

from src.web.dashboard import auth_and_rate_limit, system_health, upload_file
from src.web.middleware import require_auth


def _request(path: str = "/api/v1/tasks", host: str = "10.0.0.8", authorization: str = "") -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": headers,
            "client": (host, 12345),
            "server": ("127.0.0.1", 18092),
        }
    )


def test_remote_request_fails_closed_when_auth_token_is_missing() -> None:
    with patch("src.web.middleware.AUTH_TOKEN", ""):
        with pytest.raises(HTTPException) as exc_info:
            require_auth(_request())

    assert exc_info.value.status_code == 503


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_loopback_request_remains_available_without_auth_token(host: str) -> None:
    with patch("src.web.middleware.AUTH_TOKEN", ""):
        require_auth(_request(host=host))


def test_configured_auth_token_requires_matching_bearer_token() -> None:
    with patch("src.web.middleware.AUTH_TOKEN", "secret-token"):
        require_auth(_request(authorization="Bearer secret-token"))
        with pytest.raises(HTTPException) as exc_info:
            require_auth(_request(authorization="Bearer wrong-token"))

    assert exc_info.value.status_code == 403


def test_get_api_route_runs_authentication() -> None:
    request = _request(path="/api/v1/messages")

    async def call_next(_: Request) -> Response:
        return Response("ok")

    with patch("src.web.dashboard.require_auth") as auth, patch("src.web.dashboard.check_rate_limit"):
        response = asyncio.run(auth_and_rate_limit(request, call_next))

    assert response.status_code == 200
    auth.assert_called_once_with(request)


def test_health_response_does_not_report_stale_test_counts() -> None:
    repo = type("Repo", (), {"list_tasks": lambda self: []})()
    spaces = type("Spaces", (), {"stats": lambda self: {}})()
    agents = type("Agents", (), {"stats": lambda self: {}})()

    with (
        patch("src.web.dashboard.get_repo", return_value=repo),
        patch("src.web.dashboard.get_space_registry", return_value=spaces),
        patch("src.web.dashboard.agent_pool", agents),
    ):
        result = system_health()

    assert "tests_passed" not in result


def test_upload_rejects_oversized_file_before_storage() -> None:
    upload = UploadFile(filename="large.docx", file=io.BytesIO(b"x" * 11))

    with (
        patch("src.web.dashboard.MAX_UPLOAD_BYTES", 10, create=True),
        patch("src.web.dashboard._get_file_store") as get_store,
    ):
        with pytest.raises(HTTPException) as exc_info:
            upload_file(file=upload, user_id="u1", space_id="s1")

    assert exc_info.value.status_code == 413
    get_store.assert_not_called()


def test_upload_indexes_to_project_scope_by_default() -> None:
    upload = UploadFile(filename="demo.docx", file=io.BytesIO(b"hello"))
    fake_store = type("Store", (), {"_base": "/tmp/files", "write": lambda self, user_id, space_id, filename, content: "s1/demo.docx"})()
    fake_entry = type("Entry", (), {"id": "entry-1"})()
    fake_collector = MagicMock()
    fake_collector.collect_file.return_value = fake_entry

    with (
        patch("src.web.dashboard._get_file_store", return_value=fake_store),
        patch("src.web.dashboard.Database.get") as get_db,
        patch("src.web.dashboard.FtsKnowledgeRepository"),
        patch("src.web.dashboard.KnowledgeCollector", return_value=fake_collector),
    ):
        get_db.return_value.connect.return_value = object()
        result = upload_file(file=upload, user_id="u1", space_id="proj-1")

    assert result["indexed"] == "entry-1"
    assert result["knowledge_owner_type"] == "project"
    assert result["knowledge_owner_id"] == "proj-1"
    fake_collector.collect_file.assert_called_once_with(
        os.path.join("/tmp/files", "s1/demo.docx"),
        owner_type="project",
        owner_id="proj-1",
    )


def test_upload_can_index_to_organization_scope() -> None:
    upload = UploadFile(filename="notice.pdf", file=io.BytesIO(b"hello"))
    fake_store = type("Store", (), {"_base": "/tmp/files", "write": lambda self, user_id, space_id, filename, content: "dept-1/notice.pdf"})()
    fake_entry = type("Entry", (), {"id": "entry-2"})()
    fake_collector = MagicMock()
    fake_collector.collect_file.return_value = fake_entry

    with (
        patch("src.web.dashboard._get_file_store", return_value=fake_store),
        patch("src.web.dashboard.Database.get") as get_db,
        patch("src.web.dashboard.FtsKnowledgeRepository"),
        patch("src.web.dashboard.KnowledgeCollector", return_value=fake_collector),
    ):
        get_db.return_value.connect.return_value = object()
        result = upload_file(
            file=upload,
            user_id="u1",
            space_id="dept-1",
            knowledge_owner_type="organization",
        )

    assert result["indexed"] == "entry-2"
    assert result["knowledge_owner_type"] == "organization"
    assert result["knowledge_owner_id"] == "*"
    fake_collector.collect_file.assert_called_once_with(
        os.path.join("/tmp/files", "dept-1/notice.pdf"),
        owner_type="organization",
        owner_id="*",
    )


def test_upload_rejects_invalid_knowledge_owner_type() -> None:
    upload = UploadFile(filename="demo.docx", file=io.BytesIO(b"hello"))
    fake_store = type("Store", (), {"_base": "/tmp/files", "write": lambda self, user_id, space_id, filename, content: "s1/demo.docx"})()

    with patch("src.web.dashboard._get_file_store", return_value=fake_store):
        with pytest.raises(HTTPException) as exc_info:
            upload_file(
                file=upload,
                user_id="u1",
                space_id="proj-1",
                knowledge_owner_type="invalid-scope",
            )

    assert exc_info.value.status_code == 400

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DOC_URL_ENV = "WECOM_ROBOT_DOC_MCP_URL"
TODO_URL_ENV = "WECOM_ROBOT_TODO_MCP_URL"
_ENV_FILE = Path("infra/.env.wecom")


@dataclass(slots=True)
class McpTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None


class StreamableHttpMcpClient:
    """Small Streamable HTTP MCP client for provider-owned app tools."""

    def __init__(self, url: str, *, timeout: float = 20.0) -> None:
        self.url = url.strip()
        if not self.url:
            raise ValueError("missing MCP URL")
        self.timeout = timeout
        self._session_id = ""
        self._initialized = False
        self._id = int(time.time() * 1000)

    def list_tools(self) -> list[McpTool]:
        self._ensure_initialized()
        result = self._request("tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        return [
            McpTool(
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                input_schema=item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else {},
            )
            for item in tools
            if item.get("name")
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self._ensure_initialized()
        return self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        result = self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "ant-colony", "version": "0.1.0"},
            },
            initialize=True,
        )
        if not isinstance(result, dict):
            raise RuntimeError("invalid MCP initialize response")
        self._notify_initialized()
        self._initialized = True

    def _notify_initialized(self) -> None:
        try:
            self._post_json(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                expect_response=False,
            )
        except Exception as exc:
            logger.debug("MCP initialized notification ignored: %s", exc)

    def _request(self, method: str, params: dict[str, Any], *, initialize: bool = False) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }
        data = self._post_json(payload)
        if isinstance(data, dict) and data.get("error"):
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(f"MCP {method} error: {message}")
        if not isinstance(data, dict) or "result" not in data:
            if initialize and isinstance(data, dict):
                return data
            raise RuntimeError(f"MCP {method} returned invalid response")
        return data["result"]

    def _post_json(self, payload: dict[str, Any], *, expect_response: bool = True) -> Any:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            try:
                response = client.post(self.url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                raise RuntimeError(f"MCP HTTP request failed: {_mask_url(str(exc))}") from exc
        if response.headers.get("Mcp-Session-Id"):
            self._session_id = response.headers["Mcp-Session-Id"]
        if not expect_response or response.status_code == 202:
            return {}
        if response.is_error:
            raise RuntimeError(f"MCP HTTP {response.status_code}: {_mask_url(self.url)}")
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return _parse_sse_json(response.text)
        return response.json()

    def _next_id(self) -> int:
        self._id += 1
        return self._id


class WeComRobotMcpProvider:
    provider_id = "wecom_robot_mcp"
    provider_label = "企业微信机器人 MCP"

    def __init__(self, *, doc_url: str = "", todo_url: str = "") -> None:
        self.doc_url = doc_url.strip() or _read_config_value(DOC_URL_ENV)
        self.todo_url = todo_url.strip() or _read_config_value(TODO_URL_ENV)

    def is_configured(self) -> bool:
        return bool(self.doc_url or self.todo_url)

    def status(self, *, discover: bool = False) -> dict[str, Any]:
        status = {
            "doc": _server_status("文档", self.doc_url),
            "todo": _server_status("待办", self.todo_url),
        }
        if discover:
            for kind, url in (("doc", self.doc_url), ("todo", self.todo_url)):
                if not url:
                    continue
                try:
                    status[kind]["tools"] = [tool.name for tool in StreamableHttpMcpClient(url).list_tools()]
                    status[kind]["reachable"] = True
                except Exception as exc:
                    status[kind]["reachable"] = False
                    status[kind]["error"] = _sanitize_error(exc)
        return status

    def list_mcp_tools(self, kind: str = "all") -> str | None:
        rows: list[str] = []
        for label, url in self._servers(kind):
            tools = StreamableHttpMcpClient(url).list_tools()
            tool_names = ", ".join(tool.name for tool in tools) or "-"
            rows.append(f"{label}：{tool_names}")
        return "\n".join(rows) if rows else None

    def create_doc(self, title: str, content: str = "", capability_context=None) -> str | None:
        del capability_context
        client = self._doc_client()
        result = self._call_with_schema(
            client,
            "create_doc",
            {
                "title": title,
                "doc_title": title,
                "doc_name": title,
                "name": title,
                "type": "doc",
                "doc_type": 3,
                "content": content,
            },
        )
        result_text = _mcp_result_to_text(result)
        if content:
            doc_id = _extract_value(result, "doc_id", "document_id", "docid", "id") or _extract_value_from_text(result_text, "doc_id", "document_id", "docid", "id")
            doc_url = _extract_value(result, "url", "link") or _extract_value_from_text(result_text, "url", "link")
            if doc_id or doc_url:
                try:
                    edit_result = self.edit_doc_content(doc_id or doc_url, content)
                    return f"{result_text}\n\n已写入内容：{edit_result}"
                except Exception as exc:
                    return f"{result_text}\n\n文档已创建，但写入正文失败：{exc}"
        return result_text

    def smartpage_create(self, title: str, content: str = "", capability_context=None) -> str | None:
        del capability_context
        result = self._call_with_schema(
            self._doc_client(),
            "smartpage_create",
            {
                "title": title,
                "doc_title": title,
                "name": title,
                "content": content,
                "markdown": content,
                "content_type": 1,
                "pages": [{"page_title": title, "content_type": 1, "page_content": content}] if content else [{"page_title": title}],
            },
        )
        return _mcp_result_to_text(result)

    def edit_doc_content(self, doc_id: str, content: str, capability_context=None) -> str | None:
        del capability_context
        target = str(doc_id or "").strip()
        is_url = target.startswith("http://") or target.startswith("https://")
        result = self._call_with_schema(
            self._doc_client(),
            "edit_doc_content",
            {
                "doc_id": "" if is_url else target,
                "document_id": "" if is_url else target,
                "docid": "" if is_url else target,
                "id": "" if is_url else target,
                "url": target if is_url else "",
                "content": content,
                "content_type": 1,
                "markdown": content,
            },
        )
        return _mcp_result_to_text(result)

    def sheet_append_data(self, doc_id: str, values: list[Any] | str, capability_context=None) -> str | None:
        del capability_context
        parsed_values = _coerce_values(values)
        result = self._call_with_schema(
            self._doc_client(),
            "sheet_append_data",
            {
                "doc_id": doc_id,
                "document_id": doc_id,
                "spreadsheet_id": doc_id,
                "values": parsed_values,
                "rows": parsed_values,
                "data": parsed_values,
            },
        )
        return _mcp_result_to_text(result)

    def create_todo(
        self,
        title: str,
        due_time: str = "",
        participants: list[str] | str | None = None,
        capability_context=None,
    ) -> str | None:
        user_id = str(getattr(capability_context, "user_id", "") or "")
        participant_list = _coerce_participants(participants)
        if not participant_list and user_id:
            participant_list = [user_id]
        result = self._call_with_schema(
            self._todo_client(),
            "create_todo",
            {
                "title": title,
                "content": title,
                "summary": title,
                "due_time": due_time,
                "deadline": due_time,
                "end_time": _normalize_time_string(due_time),
                "participants": participant_list,
                "participant_userids": participant_list,
                "userids": participant_list,
                "follower_list": {
                    "followers": [{"follower_id": item} for item in participant_list]
                } if participant_list else {},
                "creator": user_id,
            },
        )
        return _mcp_result_to_text(result)

    def list_todos(self, query: str = "", capability_context=None) -> str | None:
        user_id = str(getattr(capability_context, "user_id", "") or "")
        result = self._call_with_schema(
            self._todo_client(),
            "get_todo_list",
            {
                "query": query,
                "keyword": query,
                "userid": user_id,
                "user_id": user_id,
                "follower_id": user_id,
                "limit": 10,
            },
        )
        return _mcp_result_to_text(result)

    def get_todo_detail(self, todo_id: str, capability_context=None) -> str | None:
        del capability_context
        result = self._call_with_schema(
            self._todo_client(),
            "get_todo_detail",
            {"todo_id": todo_id, "id": todo_id},
        )
        return _mcp_result_to_text(result)

    def update_todo(self, todo_id: str, title: str = "", status: str = "", due_time: str = "", capability_context=None) -> str | None:
        del capability_context
        result = self._call_with_schema(
            self._todo_client(),
            "update_todo",
            {
                "todo_id": todo_id,
                "id": todo_id,
                "title": title,
                "content": title,
                "status": status,
                "todo_status": _todo_status_value(status),
                "due_time": due_time,
                "deadline": due_time,
                "end_time": _normalize_time_string(due_time),
            },
        )
        return _mcp_result_to_text(result)

    def delete_todo(self, todo_id: str, capability_context=None) -> str | None:
        del capability_context
        result = self._call_with_schema(
            self._todo_client(),
            "delete_todo",
            {"todo_id": todo_id, "id": todo_id},
        )
        return _mcp_result_to_text(result)

    def search_todo_userid(self, query: str, capability_context=None) -> str | None:
        del capability_context
        result = self._call_with_schema(
            self._todo_client(),
            "search_todo_userid",
            {"query": query, "keyword": query, "name": query},
        )
        return _mcp_result_to_text(result)

    def change_todo_user_status(self, todo_id: str, status: str, userid: str = "", capability_context=None) -> str | None:
        user_id = userid or str(getattr(capability_context, "user_id", "") or "")
        result = self._call_with_schema(
            self._todo_client(),
            "change_todo_user_status",
            {
                "todo_id": todo_id,
                "id": todo_id,
                "status": status,
                "userid": user_id,
                "user_id": user_id,
            },
        )
        return _mcp_result_to_text(result)

    def _doc_client(self) -> StreamableHttpMcpClient:
        if not self.doc_url:
            raise RuntimeError("企业微信文档 MCP URL 未配置")
        return StreamableHttpMcpClient(self.doc_url)

    def _todo_client(self) -> StreamableHttpMcpClient:
        if not self.todo_url:
            raise RuntimeError("企业微信待办 MCP URL 未配置")
        return StreamableHttpMcpClient(self.todo_url)

    def _servers(self, kind: str) -> list[tuple[str, str]]:
        normalized = str(kind or "all").lower()
        servers: list[tuple[str, str]] = []
        if normalized in {"all", "doc", "docs"} and self.doc_url:
            servers.append(("文档", self.doc_url))
        if normalized in {"all", "todo", "todos"} and self.todo_url:
            servers.append(("待办", self.todo_url))
        return servers

    def _call_with_schema(self, client: StreamableHttpMcpClient, tool_name: str, candidates: dict[str, Any]) -> Any:
        arguments = _filter_arguments(client, tool_name, candidates)
        return client.call_tool(tool_name, arguments)


def build_wecom_robot_mcp_provider() -> WeComRobotMcpProvider | None:
    provider = WeComRobotMcpProvider()
    return provider if provider.is_configured() else None


def get_wecom_robot_mcp_status(*, discover: bool = False) -> dict[str, Any]:
    return WeComRobotMcpProvider().status(discover=discover)


def save_wecom_robot_mcp_urls(doc_url: str = "", todo_url: str = "", *, env_file: str | Path = _ENV_FILE) -> dict[str, Any]:
    from src.platform.bot_setup import write_env_values

    env_map: dict[str, str] = {}
    if doc_url.strip():
        env_map[DOC_URL_ENV] = doc_url.strip()
    if todo_url.strip():
        env_map[TODO_URL_ENV] = todo_url.strip()
    if env_map:
        write_env_values(env_file, env_map)
    return {
        "saved_keys": sorted(env_map),
        "env_file": str(env_file),
        "restart_required": any(os.environ.get(key, "") != value for key, value in env_map.items()),
        "status": get_wecom_robot_mcp_status(discover=False),
    }


def _filter_arguments(client: StreamableHttpMcpClient, tool_name: str, candidates: dict[str, Any]) -> dict[str, Any]:
    try:
        tools = client.list_tools()
    except Exception:
        return {key: value for key, value in candidates.items() if _has_value(value)}
    tool = next((item for item in tools if item.name == tool_name), None)
    if not tool or not tool.input_schema:
        return {key: value for key, value in candidates.items() if _has_value(value)}
    properties = tool.input_schema.get("properties", {})
    if not isinstance(properties, dict) or not properties:
        return {key: value for key, value in candidates.items() if _has_value(value)}
    return {
        key: value
        for key, value in candidates.items()
        if key in properties and _has_value(value)
    }


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _parse_sse_json(text: str) -> Any:
    last_data = ""
    for line in text.splitlines():
        if line.startswith("data:"):
            last_data = line.partition(":")[2].strip()
    if not last_data:
        raise RuntimeError("empty MCP SSE response")
    return json.loads(last_data)


def _mcp_result_to_text(result: Any) -> str:
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            if parts:
                return "\n".join(parts)
        if "structuredContent" in result:
            return json.dumps(result["structuredContent"], ensure_ascii=False, indent=2)
        return json.dumps(result, ensure_ascii=False, indent=2)
    if isinstance(result, list):
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


def _extract_value(payload: Any, *keys: str) -> str:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value:
                return str(value)
        for value in payload.values():
            nested = _extract_value(value, *keys)
            if nested:
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = _extract_value(item, *keys)
            if nested:
                return nested
    return ""


def _extract_value_from_text(text: str, *keys: str) -> str:
    stripped = str(text or "").strip()
    if not stripped:
        return ""
    try:
        parsed = json.loads(stripped)
    except Exception:
        return ""
    return _extract_value(parsed, *keys)


def _coerce_values(values: list[Any] | str) -> list[Any]:
    if isinstance(values, list):
        return values
    try:
        parsed = json.loads(values)
        return parsed if isinstance(parsed, list) else [parsed]
    except Exception:
        return [part.strip() for part in str(values).split(",") if part.strip()]


def _coerce_participants(participants: list[str] | str | None) -> list[str]:
    if participants is None:
        return []
    if isinstance(participants, list):
        return [str(item).strip() for item in participants if str(item).strip()]
    return [part.strip() for part in str(participants).replace("，", ",").split(",") if part.strip()]


def _normalize_time_string(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 16 and text[4] == "-" and text[7] == "-" and text[10] == " ":
        return f"{text}:00"
    return text


def _todo_status_value(value: str) -> int | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"done", "complete", "completed", "0", "已完成", "完成"}:
        return 0
    if normalized in {"pending", "active", "doing", "in_progress", "1", "进行中", "未完成"}:
        return 1
    return None


def _server_status(label: str, url: str) -> dict[str, Any]:
    return {
        "label": label,
        "configured": bool(url),
        "url_masked": _mask_url(url),
    }


def _read_config_value(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if value:
        return value
    values = _read_env_file(_ENV_FILE)
    return values.get(key, "").strip()


def _read_env_file(env_file: str | Path) -> dict[str, str]:
    path = Path(env_file)
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _mask_url(url: str) -> str:
    if not url:
        return ""
    if "apikey=" not in url:
        return url[:24] + "..." if len(url) > 28 else url
    prefix, _, key = url.partition("apikey=")
    if len(key) <= 12:
        masked = "***"
    else:
        masked = f"{key[:6]}...{key[-4:]}"
    return f"{prefix}apikey={masked}"


def _sanitize_error(exc: Exception) -> str:
    return _mask_url(str(exc))

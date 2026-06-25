from __future__ import annotations

from unittest.mock import patch


def test_knowledge_command_returns_signed_user_link() -> None:
    from src.gateway.entry_links import build_entry_link_reply

    with patch.dict(
        "os.environ",
        {"ANT_COLONY_PUBLIC_BASE_URL": "http://example.test", "ANT_COLONY_ADMIN_SESSION_SECRET": "secret"},
        clear=False,
    ):
        reply = build_entry_link_reply("wecom", "u1", "打开知识库")

    assert reply is not None
    assert "知识库管理入口" in reply
    assert "http://example.test/knowledge/user?" in reply
    assert "platform=wecom" in reply
    assert "user_id=u1" in reply
    assert "user_token=" in reply


def test_admin_command_requires_platform_admin() -> None:
    from src.gateway.entry_links import build_entry_link_reply

    with patch.dict(
        "os.environ",
        {"ANT_COLONY_PUBLIC_BASE_URL": "http://example.test", "ANT_COLONY_ADMIN_SESSION_SECRET": "secret"},
        clear=False,
    ), patch("src.web.admin_auth.is_platform_admin", return_value=False):
        reply = build_entry_link_reply("wecom", "u1", "打开管理员控制台")

    assert reply is not None
    assert "没有管理员权限" in reply
    assert "/admin/console" not in reply


def test_admin_command_returns_signed_admin_console_link_for_admin() -> None:
    from src.gateway.entry_links import build_entry_link_reply

    with patch.dict(
        "os.environ",
        {"ANT_COLONY_PUBLIC_BASE_URL": "http://example.test", "ANT_COLONY_ADMIN_SESSION_SECRET": "secret"},
        clear=False,
    ), patch("src.web.admin_auth.is_platform_admin", return_value=True):
        reply = build_entry_link_reply("wecom", "u-admin", "进入后台")

    assert reply is not None
    assert "管理员控制台" in reply
    assert "http://example.test/admin/console?" in reply
    assert "platform=wecom" in reply
    assert "user_id=u-admin" in reply
    assert "admin_token=" in reply


def test_non_entry_text_returns_none() -> None:
    from src.gateway.entry_links import build_entry_link_reply

    assert build_entry_link_reply("wecom", "u1", "帮我总结一下这个制度") is None


def test_platform_entry_menu_contains_user_and_admin_items() -> None:
    from src.gateway.entry_links import build_platform_entry_menu

    with patch.dict(
        "os.environ",
        {"ANT_COLONY_PUBLIC_BASE_URL": "http://example.test", "ANT_COLONY_ADMIN_SESSION_SECRET": "secret"},
        clear=False,
    ):
        menu = build_platform_entry_menu("feishu", "u-admin", is_admin=True)

    assert menu["platform"] == "feishu"
    titles = [item["title"] for item in menu["items"]]
    assert "知识库管理" in titles
    assert "上传文档入库" in titles
    assert "管理员控制台" in titles
    urls = [item["url"] for item in menu["items"]]
    assert any("/knowledge/user?" in url for url in urls)
    assert any("/admin/console?" in url for url in urls)


def test_entry_link_uses_document_base_url_when_public_base_missing() -> None:
    from src.gateway.entry_links import build_entry_link_reply

    with patch.dict(
        "os.environ",
        {
            "ANT_COLONY_PUBLIC_BASE_URL": "",
            "ANT_COLONY_DASHBOARD_BASE_URL": "",
            "ANT_COLONY_DOCUMENT_BASE_URL": "http://docs.example.test",
            "ANT_COLONY_ADMIN_SESSION_SECRET": "secret",
        },
        clear=False,
    ):
        reply = build_entry_link_reply("wecom", "u1", "打开知识库")

    assert reply is not None
    assert "http://docs.example.test/knowledge/user?" in reply

from __future__ import annotations

from unittest.mock import patch


def _reset_db(db_path: str) -> None:
    from src.store.database import Database

    Database.get(db_path).close()
    Database._instances.pop(db_path, None)  # type: ignore[attr-defined]


def test_unified_search_aggregates_only_current_user_context() -> None:
    from src.platform.unified_search_service import search_workspace

    calls: list[tuple[str, str]] = []

    def fake_invoke(capability_id, query, *, context, empty_message=""):
        calls.append((capability_id, context.user_id))
        return {"docs.search": "制度文件 A", "drive.search": "网盘文件 B", "mail.search": "邮件 C"}[capability_id]

    with patch("src.platform.unified_search_service.search_knowledge_tool", return_value="搜索 '设备巡检' 找到 1 条结果:\n[公司知识] 设备巡检制度"), \
         patch("src.platform.unified_search_service.invoke_capability", side_effect=fake_invoke):
        result = search_workspace(user_id="u1", platform="wecom", query="设备巡检")

    assert "【知识库】" in result
    assert "【企业文档】" in result
    assert "【网盘】" in result
    assert "【邮件】" in result
    assert calls == [("docs.search", "u1"), ("drive.search", "u1"), ("mail.search", "u1")]


def test_subscription_can_pause_resume_and_delete_with_audit(tmp_path) -> None:
    from src.platform import public_data_service as svc

    db_path = str(tmp_path / "subscriptions.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False):
        _reset_db(db_path)
        created = svc.create_subscription(platform="wecom", user_id="u1", kind="weather", query="上海")
        paused = svc.set_subscription_enabled(created["id"], False, actor_user_id="u1")
        resumed = svc.set_subscription_enabled(created["id"], True, actor_user_id="u1")
        deleted = svc.delete_subscription(created["id"], actor_user_id="u1")
        audit = svc.list_subscription_audit(user_id="u1", platform="wecom")

    assert paused["enabled"] is False
    assert resumed["enabled"] is True
    assert deleted["deleted"] is True
    assert [item["action"] for item in audit] == ["delete", "resume", "pause", "create"]

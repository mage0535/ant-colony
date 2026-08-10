from __future__ import annotations


def test_hr_specialist_service_sets_lists_and_removes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant-colony.db"))

    from src.platform.hr_specialist_service import (
        bulk_set_hr_specialists,
        is_hr_specialist,
        list_hr_specialists,
        set_hr_specialist,
    )

    assert is_hr_specialist("wecom", "UserA") is False

    result = set_hr_specialist(platform="wecom", user_id="UserA", enabled=True, granted_by="AdminUser")
    assert result["enabled"] is True
    assert is_hr_specialist("wecom", "UserA") is True
    assert list_hr_specialists("wecom")[0]["user_id"] == "UserA"

    batch = bulk_set_hr_specialists(platform="wecom", user_ids=["UserB", " "], enabled=True, granted_by="AdminUser")
    assert batch["updated"] == 1
    assert is_hr_specialist("wecom", "UserB") is True

    removed = set_hr_specialist(platform="wecom", user_id="UserA", enabled=False, granted_by="AdminUser")
    assert removed["enabled"] is False
    assert is_hr_specialist("wecom", "UserA") is False

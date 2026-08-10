from __future__ import annotations


def test_entry_link_files_do_not_contain_mojibake() -> None:
    from scripts.check_user_visible_text import DEFAULT_PATHS, find_mojibake

    assert find_mojibake(list(DEFAULT_PATHS)) == []


def test_bot_entry_command_validator_passes() -> None:
    from scripts.validate_bot_entry_commands import validate_entry_commands

    checks = validate_entry_commands()

    assert "管理后台" in checks
    assert "知识库后台" in checks
    assert "non-entry passthrough" in checks

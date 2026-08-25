from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@contextmanager
def _validation_env():
    with patch.dict(
        os.environ,
        {
            "ANT_COLONY_PUBLIC_BASE_URL": "http://example.test",
            "ANT_COLONY_ADMIN_SESSION_SECRET": "validation-secret",
        },
        clear=False,
    ), patch("src.web.admin_auth.is_platform_admin", return_value=True):
        yield


def _assert_contains(text: str | None, expected: str, command: str) -> None:
    if text is None or expected not in text:
        raise AssertionError(f"{command!r} should include {expected!r}, got {text!r}")


def validate_entry_commands() -> list[str]:
    from src.gateway.entry_links import build_entry_link_reply

    checks: list[str] = []
    with _validation_env():
        for command in ("管理后台", "管理员后台", "进入后台", "打开管理员控制台"):
            reply = build_entry_link_reply("wecom_bot", "AdminUser", command)
            _assert_contains(reply, "管理员控制台入口", command)
            _assert_contains(reply, "/admin/console?", command)
            checks.append(command)

        for command in ("知识库后台", "打开知识库", "上传文档入库"):
            reply = build_entry_link_reply("wecom_bot", "AdminUser", command)
            _assert_contains(reply, "知识库管理入口", command)
            _assert_contains(reply, "/knowledge/user?", command)
            if "/admin/console?" in str(reply):
                raise AssertionError(f"{command!r} should prefer knowledge link over admin console")
            checks.append(command)

        reply = build_entry_link_reply("wecom_bot", "AdminUser", "菜单")
        _assert_contains(reply, "可用入口", "菜单")
        checks.append("菜单")

        irrelevant = build_entry_link_reply("wecom_bot", "AdminUser", "帮我总结这个制度")
        if irrelevant is not None:
            raise AssertionError(f"non-entry message should not be intercepted, got {irrelevant!r}")
        checks.append("non-entry passthrough")
    return checks


def main() -> int:
    try:
        checks = validate_entry_commands()
    except Exception as exc:
        print(f"Bot 入口命令回归检查失败：{type(exc).__name__}: {exc}")
        return 1
    print(f"Bot 入口命令回归检查通过：{len(checks)} 项。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

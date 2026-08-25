"""Perform a real, read-only mailbox test for one configured employee."""
from __future__ import annotations

import argparse

from src.platform.mail_account_service import summarize_user_mailbox
from src.web.dashboard import _mail_test_succeeded


def main() -> int:
    parser = argparse.ArgumentParser(description="测试已保存的员工邮箱读取配置")
    parser.add_argument("--platform", default="wecom")
    parser.add_argument("--user-id", required=True)
    args = parser.parse_args()
    result = summarize_user_mailbox(args.platform, args.user_id, limit=3)
    print(result)
    return 0 if _mail_test_succeeded(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())

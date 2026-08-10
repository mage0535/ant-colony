"""Print mailbox bindings for safe operational diagnosis; passwords are never exposed."""
from __future__ import annotations

import json

from src.platform.mail_account_service import list_mail_accounts


def main() -> int:
    accounts = list_mail_accounts().get("accounts", [])
    print(json.dumps({"count": len(accounts), "accounts": accounts}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

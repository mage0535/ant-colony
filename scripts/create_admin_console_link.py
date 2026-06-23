from __future__ import annotations

import argparse
import urllib.parse

from src.web.admin_auth import create_admin_console_token


def build_admin_console_link(
    *,
    base_url: str,
    platform: str,
    user_id: str,
    ttl_seconds: int,
) -> str:
    token = create_admin_console_token(platform=platform, user_id=user_id, ttl_seconds=ttl_seconds)
    query = urllib.parse.urlencode(
        {
            "platform": platform,
            "user_id": user_id,
            "admin_token": token,
        }
    )
    return f"{base_url.rstrip('/')}/admin/console?{query}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a signed admin console link for an enterprise IM admin.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18092")
    parser.add_argument("--platform", default="wecom", choices=["wecom", "feishu", "dingtalk"])
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--ttl-seconds", type=int, default=3600)
    args = parser.parse_args()
    print(
        build_admin_console_link(
            base_url=args.base_url,
            platform=args.platform,
            user_id=args.user_id,
            ttl_seconds=args.ttl_seconds,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

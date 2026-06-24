from __future__ import annotations

import argparse
from urllib.parse import urlencode

from src.web.admin_auth import create_im_user_token


def build_knowledge_user_link(
    *,
    base_url: str,
    platform: str,
    user_id: str,
    ttl_seconds: int = 86400,
) -> str:
    token = create_im_user_token(platform=platform, user_id=user_id, ttl_seconds=ttl_seconds)
    query = urlencode({"platform": platform, "user_id": user_id, "user_token": token})
    return f"{base_url.rstrip('/')}/knowledge/user?{query}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a signed employee knowledge management link.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--platform", default="wecom", choices=["wecom", "feishu", "dingtalk"])
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--ttl-seconds", type=int, default=86400)
    args = parser.parse_args()
    print(
        build_knowledge_user_link(
            base_url=args.base_url,
            platform=args.platform,
            user_id=args.user_id,
            ttl_seconds=args.ttl_seconds,
        )
    )


if __name__ == "__main__":
    main()

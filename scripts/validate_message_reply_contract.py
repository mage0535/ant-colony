from __future__ import annotations

import argparse
import json
import sys
import urllib.request


CASES = (
    ("hello", "你好", 20),
    ("admin", "管理后台", 20),
    ("knowledge", "打开知识库", 20),
    ("reply_mail", "你可以帮我回邮吗", 20),
    ("mail_summary", "汇总今天邮件", 80),
)


def validate(base_url: str, user_id: str) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for name, content, timeout in CASES:
        payload = json.dumps(
            {
                "from_user_id": user_id,
                "content": content,
                "msg_type": "text",
                "is_direct": True,
                "provider": "wecom_bot",
            },
            ensure_ascii=True,
        ).encode("utf-8")
        req = urllib.request.Request(
            base_url.rstrip("/") + "/",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
        reply = str(data.get("reply") or "")
        results.append(
            {
                "case": name,
                "status": resp.status,
                "has_reply": bool(reply.strip()),
                "fallback": bool(data.get("fallback")),
                "preview": reply[:160].replace("\n", " | "),
            }
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate direct Bot messages always receive visible replies.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18090", help="Gateway base URL.")
    parser.add_argument("--user-id", default="UserA", help="Enterprise IM user ID used for validation.")
    args = parser.parse_args(argv)

    try:
        results = validate(args.base_url, args.user_id)
    except Exception as exc:
        print(f"消息回复契约检查失败：{type(exc).__name__}: {exc}")
        return 1
    failed = [item for item in results if item["status"] != 200 or not item["has_reply"]]
    for item in results:
        print(json.dumps(item, ensure_ascii=False))
    if failed:
        print(f"消息回复契约检查失败：{len(failed)} 项没有可见回复。")
        return 1
    print(f"消息回复契约检查通过：{len(results)} 项均返回可见回复。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any


PLATFORM_SDK_HINTS = {
    "wecom": ["wechatpy", "weworkapi", "qywx", "wecom"],
    "feishu": ["feishu", "lark", "larksuite"],
    "dingtalk": ["dingtalk", "dingding"],
}


def _load_dependencies() -> list[str]:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    return [str(item) for item in deps]


def _sdk_matches(platform: str, deps: list[str]) -> list[str]:
    hints = PLATFORM_SDK_HINTS[platform]
    matches: list[str] = []
    for dep in deps:
        lowered = dep.lower()
        if any(hint in lowered for hint in hints):
            matches.append(dep)
    return matches


def build_report() -> dict[str, Any]:
    deps = _load_dependencies()
    return {
        "platforms": [
            {
                "platform": "wecom",
                "integration_mode": "in_repo_http_client",
                "adapter": "src/gateway/wecom_bot_bridge.py",
                "api_client": "src/platform/api_wecom.py",
                "sdk_dependencies": _sdk_matches("wecom", deps),
                "official_update_source": "https://developer.work.weixin.qq.com/document",
                "update_required": False,
                "reason": "当前没有独立外部企微接口项目或 SDK 依赖，接入层是仓库内自写实现。",
            },
            {
                "platform": "feishu",
                "integration_mode": "in_repo_http_client",
                "adapter": "src/gateway/adapter_feishu.py",
                "api_client": "src/platform/api_feishu.py",
                "sdk_dependencies": _sdk_matches("feishu", deps),
                "official_update_source": "https://open.feishu.cn/changelog?lang=zh-CN",
                "update_required": False,
                "reason": "当前没有独立外部飞书接口项目或 SDK 依赖，接入层是仓库内自写实现。",
            },
            {
                "platform": "dingtalk",
                "integration_mode": "in_repo_http_client",
                "adapter": "src/gateway/adapter_dingtalk.py",
                "api_client": "src/platform/api_dingtalk.py",
                "sdk_dependencies": _sdk_matches("dingtalk", deps),
                "official_update_source": "https://open.dingtalk.com/document/isvapp/application-development-update-log-1692847475701",
                "update_required": False,
                "reason": "当前没有独立外部钉钉接口项目或 SDK 依赖，接入层是仓库内自写实现。",
            },
        ]
    }


def main() -> int:
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.platform.bot_setup import (
    PLATFORM_SPECS,
    dingtalk_qr_register,
    feishu_qr_register,
    normalize_registration_result,
    wecom_qr_scan_for_bot_info,
    write_env_values,
)


def _prompt(label: str, secret: bool = False) -> str:
    return getpass.getpass(f"{label}: ") if secret else input(f"{label}: ").strip()


def _manual_credentials(platform: str) -> dict[str, str]:
    spec = PLATFORM_SPECS[platform]
    values: dict[str, str] = {}
    for env_key, label in zip(spec["env_keys"], spec["labels"]):
        values[env_key] = _prompt(label, secret="SECRET" in env_key)
    if platform == "feishu":
        domain = _prompt("Domain (feishu/lark)") or "feishu"
        values["FEISHU_DOMAIN"] = domain
    return values


def _scan_credentials(platform: str) -> dict[str, str] | None:
    if platform == "wecom":
        result = wecom_qr_scan_for_bot_info()
    elif platform == "feishu":
        result = feishu_qr_register()
    elif platform == "dingtalk":
        result = dingtalk_qr_register()
    else:
        raise ValueError(f"Unsupported platform: {platform}")
    if not result:
        return None
    return normalize_registration_result(platform, result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up platform bot credentials for Ant Colony.")
    parser.add_argument("--platform", choices=["wecom", "feishu", "dingtalk"], required=True)
    parser.add_argument("--method", choices=["scan", "manual"], default="scan")
    parser.add_argument("--env-file", default="infra/.env.wecom")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    values = _scan_credentials(args.platform) if args.method == "scan" else None
    if not values:
        print("Automatic setup did not complete. Falling back to manual input.\n")
        values = _manual_credentials(args.platform)

    write_env_values(env_path, values)
    print(f"\nSaved credentials for {args.platform} to {env_path}")


if __name__ == "__main__":
    main()

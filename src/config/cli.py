from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from src.config import (
    AdminSettingsRecord,
    LLMProvider,
    PlatformType,
    build_settings_service,
)
from src.config.exporter import apply_openvort_env_overlay, export_openvort_env, write_openvort_env_file
from src.config.importer import seed_from_openvort_env_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage runtime settings for ant colony.")
    parser.add_argument(
        "--file",
        default="./data/runtime_settings.json",
        help="Path to the runtime settings JSON file.",
    )
    parser.add_argument(
        "--openvort-env-file",
        default="./data/openvort_runtime.env",
        help="Path to the generated OpenVort env file.",
    )
    parser.add_argument(
        "--openvort-target-env",
        default="./external/openvort/source/.env",
        help="Path to the target OpenVort .env file for overlay application.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize default settings file.")

    subparsers.add_parser("show", help="Show the current runtime settings snapshot.")
    subparsers.add_parser("audit", help="Audit whether current settings are ready for runtime use.")
    subparsers.add_parser("export-openvort-env", help="Export current settings as OpenVort-compatible env values.")
    subparsers.add_parser("write-openvort-env-file", help="Write exported OpenVort env values into a file.")
    apply_env = subparsers.add_parser("apply-openvort-env", help="Apply exported OpenVort env values onto a target .env file.")
    apply_env.add_argument(
        "--target-env",
        dest="target_env",
        default=None,
        help="Override target OpenVort .env file path for this command.",
    )

    seed_env = subparsers.add_parser("seed-from-openvort-env", help="Seed runtime settings from an OpenVort .env file.")
    seed_env.add_argument(
        "--env-file",
        default="./external/openvort/source/.env",
        help="Path to the source OpenVort .env file.",
    )
    seed_env.add_argument(
        "--reset",
        action="store_true",
        help="Reset current settings before seeding.",
    )

    llm = subparsers.add_parser("set-llm", help="Create or update an LLM profile.")
    llm.add_argument("--profile-id", required=True)
    llm.add_argument("--provider", required=True, choices=[item.value for item in LLMProvider])
    llm.add_argument("--model-name", required=True)
    llm.add_argument("--api-key")
    llm.add_argument("--api-base")
    llm.add_argument("--max-tokens", type=int)
    llm.add_argument("--timeout-seconds", type=int)
    llm.add_argument("--enabled", choices=["true", "false"])

    admin = subparsers.add_parser("set-admin", help="Create or update admin settings.")
    admin.add_argument("--admin-user-ids", default="")
    admin.add_argument("--web-default-password")
    admin.add_argument("--pause-command-enabled", choices=["true", "false"])
    admin.add_argument("--handoff-command-enabled", choices=["true", "false"])
    admin.add_argument("--task-confirmation-required", choices=["true", "false"])

    platform = subparsers.add_parser("set-platform", help="Create or update platform settings.")
    platform.add_argument("--platform", required=True, choices=[item.value for item in PlatformType])
    platform.add_argument("--enabled", choices=["true", "false"])
    platform.add_argument(
        "--set",
        dest="settings_items",
        action="append",
        default=[],
        help="Key-value pair in the format key=value. Can be provided multiple times.",
    )

    return parser


def run_cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    service = build_settings_service(Path(args.file))

    if args.command == "init":
        snapshot = service.ensure_defaults()
        _print_json(_snapshot_to_payload(snapshot, service))
        return 0

    if args.command == "show":
        snapshot = service.build_runtime_snapshot()
        _print_json(_snapshot_to_payload(snapshot, service))
        return 0

    if args.command == "audit":
        report = service.audit_readiness()
        _print_json(
            {
                "ready": report.ready,
                "issues": [asdict(issue) for issue in report.issues],
            }
        )
        return 0

    if args.command == "export-openvort-env":
        snapshot = service.build_runtime_snapshot()
        _print_json(export_openvort_env(snapshot))
        return 0

    if args.command == "write-openvort-env-file":
        snapshot = service.build_runtime_snapshot()
        path = write_openvort_env_file(snapshot, Path(args.openvort_env_file))
        print(f"Wrote exported OpenVort env to {path}")
        return 0

    if args.command == "apply-openvort-env":
        snapshot = service.build_runtime_snapshot()
        target_env = Path(args.target_env) if args.target_env else Path(args.openvort_target_env)
        path = apply_openvort_env_overlay(snapshot, target_env)
        print(f"Applied exported OpenVort env values into {path}")
        return 0

    if args.command == "seed-from-openvort-env":
        if args.reset:
            service.reset()
        seed_from_openvort_env_file(service, Path(args.env_file))
        snapshot = service.build_runtime_snapshot()
        _print_json(_snapshot_to_payload(snapshot, service))
        return 0

    if args.command == "set-llm":
        service.upsert_llm_profile(
            profile_id=args.profile_id,
            provider=LLMProvider(args.provider),
            model_name=args.model_name,
            api_key=args.api_key,
            api_base=args.api_base,
            max_tokens=args.max_tokens,
            timeout_seconds=args.timeout_seconds,
            enabled=_parse_optional_bool(args.enabled),
        )
        snapshot = service.build_runtime_snapshot()
        _print_json(_snapshot_to_payload(snapshot, service))
        return 0

    if args.command == "set-admin":
        service.upsert_admin_settings(
            admin_user_ids=[item for item in args.admin_user_ids.split(",") if item],
            web_default_password=args.web_default_password,
            pause_command_enabled=_parse_optional_bool(args.pause_command_enabled),
            handoff_command_enabled=_parse_optional_bool(args.handoff_command_enabled),
            task_confirmation_required=_parse_optional_bool(args.task_confirmation_required),
        )
        snapshot = service.build_runtime_snapshot()
        _print_json(_snapshot_to_payload(snapshot, service))
        return 0

    if args.command == "set-platform":
        service.upsert_platform_settings(
            platform=PlatformType(args.platform),
            enabled=_parse_optional_bool(args.enabled),
            settings=_parse_settings_items(args.settings_items),
        )
        snapshot = service.build_runtime_snapshot()
        _print_json(_snapshot_to_payload(snapshot, service))
        return 0

    raise AssertionError(f"Unsupported command: {args.command}")


def _parse_optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value == "true"


def _parse_settings_items(items: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator:
            raise ValueError(f"Invalid settings item: {item}")
        parsed[key] = value
    return parsed


def _snapshot_to_payload(snapshot, service) -> dict:
    admin_settings = snapshot.admin_settings
    return {
        "llm_profiles": [asdict(view) for view in service.build_llm_views()],
        "admin_settings": asdict(admin_settings) if admin_settings else None,
        "platforms": [asdict(view) for view in service.build_platform_views()],
    }


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))

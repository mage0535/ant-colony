from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch


def test_acceptance_script_is_safe_to_import() -> None:
    _assert_script_safe_to_import("scripts/acceptance_test.py", "acceptance_test_module")


def test_integration_script_is_safe_to_import() -> None:
    _assert_script_safe_to_import("scripts/integration_test.py", "integration_test_module")


def test_e2e_script_is_safe_to_import() -> None:
    _assert_script_safe_to_import("scripts/e2e_test.py", "e2e_test_module")


def test_bot_e2e_regression_script_is_safe_to_import() -> None:
    _assert_script_safe_to_import("scripts/run_bot_e2e_regression.py", "bot_e2e_regression_module")


def test_gateway_entrypoint_is_safe_to_import() -> None:
    _assert_service_entrypoint_safe_to_import(
        "run_gateway.py",
        "gateway_entrypoint_module",
        "src.gateway.webhook_server.serve",
    )


def test_callback_entrypoint_is_safe_to_import() -> None:
    _assert_service_entrypoint_safe_to_import(
        "run_callback.py",
        "callback_entrypoint_module",
        "src.gateway.wecom_callback_server.serve",
    )


def test_wecom_bot_entrypoint_is_safe_to_import() -> None:
    _assert_service_entrypoint_safe_to_import(
        "run_wecom_bot.py",
        "wecom_bot_entrypoint_module",
        "src.gateway.wecom_bot_bridge.run_wecom_bot_bridge",
    )


def test_dashboard_entrypoint_is_safe_to_import() -> None:
    _assert_script_safe_to_import("run_dashboard.py", "dashboard_entrypoint_module")


def _assert_script_safe_to_import(script_path_text: str, module_name: str) -> None:
    script_path = Path(script_path_text)
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    with patch("urllib.request.urlopen", side_effect=AssertionError("urlopen should not run during import")):
        spec.loader.exec_module(module)

    assert callable(module.main)


def _assert_service_entrypoint_safe_to_import(
    script_path_text: str,
    module_name: str,
    service_target: str,
) -> None:
    script_path = Path(script_path_text)
    assert script_path.is_file(), f"missing service entrypoint: {script_path}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    with patch(service_target, side_effect=AssertionError("service should not start during import")):
        spec.loader.exec_module(module)

    assert callable(module.main)

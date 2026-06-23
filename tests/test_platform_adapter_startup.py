from __future__ import annotations
import os
import types
import unittest
from unittest.mock import patch


class _FakeThread:
    def __init__(self, target=None, daemon=None, name=None):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False

    def start(self) -> None:
        self.started = True


class TestPlatformAdapterStartup(unittest.TestCase):
    def test_start_platform_adapters_starts_feishu_and_dingtalk_when_env_present(self) -> None:
        from src.gateway.platform_adapters import start_platform_adapters

        created_adapters: list[tuple[str, str]] = []

        class FakeFeishuAdapter:
            def __init__(self, gateway_url: str) -> None:
                created_adapters.append(("feishu", gateway_url))

            def start(self) -> None:
                return None

        class FakeDingTalkAdapter:
            def __init__(self, gateway_url: str) -> None:
                created_adapters.append(("dingtalk", gateway_url))

            def start(self) -> None:
                return None

        fake_modules = {
            "src.gateway.adapter_feishu": types.SimpleNamespace(FeishuAdapter=FakeFeishuAdapter),
            "src.gateway.adapter_dingtalk": types.SimpleNamespace(DingTalkAdapter=FakeDingTalkAdapter),
        }

        with (
            patch.dict(
                os.environ,
                {
                    "FEISHU_APP_ID": "app-id",
                    "FEISHU_APP_SECRET": "app-secret",
                    "DINGTALK_CLIENT_ID": "client-id",
                    "DINGTALK_CLIENT_SECRET": "client-secret",
                },
                clear=False,
            ),
            patch.dict("sys.modules", fake_modules),
            patch("src.gateway.platform_adapters.threading.Thread", _FakeThread),
        ):
            threads = start_platform_adapters("http://gateway.test/webhook")

        self.assertEqual(len(threads), 2)
        self.assertEqual(created_adapters[0], ("feishu", "http://gateway.test/webhook"))
        self.assertEqual(created_adapters[1], ("dingtalk", "http://gateway.test/webhook"))
        self.assertTrue(all(thread.started for thread in threads))

    def test_start_platform_adapters_skips_unconfigured_platforms(self) -> None:
        from src.gateway.platform_adapters import start_platform_adapters

        with patch.dict(
            os.environ,
            {
                "FEISHU_APP_ID": "",
                "FEISHU_APP_SECRET": "",
                "DINGTALK_CLIENT_ID": "",
                "DINGTALK_CLIENT_SECRET": "",
                "TELEGRAM_BOT_TOKEN": "",
            },
            clear=False,
        ):
            threads = start_platform_adapters("http://gateway.test/webhook")

        self.assertEqual(threads, [])

from __future__ import annotations

from unittest.mock import patch


class _Entry:
    def __init__(self, title: str) -> None:
        self.metadata = {"title": title}


def test_phase2_runtime_validation_requires_company_guide_search_hit() -> None:
    from scripts.validate_phase2_runtime import build_validation_result

    with patch("scripts.validate_phase2_runtime.search_knowledge_entries", return_value=[]):
        result = build_validation_result()

    assert result["daily_brief_cron_allowed"] is True
    assert result["required_routes_ready"] is True
    assert result["guide_search_ready"] is False
    assert result["guide_search_titles"] == []


def test_phase2_runtime_validation_accepts_company_guide_search_hit() -> None:
    from scripts.validate_phase2_runtime import build_validation_result

    with patch(
        "scripts.validate_phase2_runtime.search_knowledge_entries",
        return_value=[_Entry("企业 AI 助手使用总入口")],
    ):
        result = build_validation_result()

    assert result["guide_search_ready"] is True
    assert result["guide_search_titles"] == ["企业 AI 助手使用总入口"]


def test_phase2_runtime_validation_explains_local_connection_refused() -> None:
    from scripts.validate_phase2_runtime import build_validation_result

    with patch("scripts.validate_phase2_runtime.search_knowledge_entries", side_effect=RuntimeError("WinError 10061")):
        result = build_validation_result()

    assert result["guide_search_ready"] is False
    assert "测试服务器" in result["diagnostic_hint"]


def test_phase2_runtime_validation_explains_bad_gateway() -> None:
    from scripts.validate_phase2_runtime import build_validation_result

    with patch("scripts.validate_phase2_runtime.search_knowledge_entries", side_effect=RuntimeError("HTTP Error 502: Bad Gateway")):
        result = build_validation_result()

    assert result["guide_search_ready"] is False
    assert "502" in result["diagnostic_hint"]

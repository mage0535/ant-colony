from __future__ import annotations


def test_internal_provider_reads_sample_workorder() -> None:
    from src.platform.internal_capability_provider import InternalCapabilityProvider

    result = InternalCapabilityProvider().lookup_workorder("WO-1001")

    assert result is not None
    assert "WO-1001" in result
    assert "blocked" in result


def test_internal_provider_analyzes_sample_workorder() -> None:
    from src.platform.internal_capability_provider import InternalCapabilityProvider

    result = InternalCapabilityProvider().analyze_workorder("WO-1002")

    assert result is not None
    assert "风险等级" in result
    assert "待料风险" in result

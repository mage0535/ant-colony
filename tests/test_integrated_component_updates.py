from __future__ import annotations

from unittest.mock import patch


def test_build_report_aggregates_component_update_state() -> None:
    from scripts.check_integrated_component_updates import build_report

    with patch("scripts.check_integrated_component_updates._officecli_report", return_value={"name": "OfficeCLI", "update_available": True}), \
         patch("scripts.check_integrated_component_updates._stirling_report", return_value={"name": "Stirling-PDF", "update_available": False}), \
         patch("scripts.check_integrated_component_updates._ocrmypdf_report", return_value={"name": "OCRmyPDF", "update_available": False}), \
         patch("scripts.check_integrated_component_updates._searxng_report", return_value={"name": "SearXNG"}):
        report = build_report()

    names = [item["name"] for item in report["components"]]
    assert names == ["OfficeCLI", "Stirling-PDF", "OCRmyPDF", "SearXNG"]


def test_stirling_report_compares_against_pinned_version() -> None:
    from scripts.check_integrated_component_updates import _stirling_report

    with patch(
        "scripts.check_integrated_component_updates._fetch_json",
        return_value={"tag_name": "v2.14.1"},
    ):
        report = _stirling_report()

    assert report["configured_image"] == "stirlingtools/stirling-pdf:v2.14.1"
    assert report["update_available"] is False

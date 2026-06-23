from __future__ import annotations

from unittest.mock import patch

import pytest


def test_attendance_token_request_requires_environment_credentials() -> None:
    from src.tools import attendance_tool

    with (
        patch.object(attendance_tool, "_WECOM_CORP_ID", ""),
        patch.object(attendance_tool, "_WECOM_SECRET", ""),
        patch("urllib.request.urlopen") as urlopen,
    ):
        with pytest.raises(RuntimeError, match="WECOM_CORP_ID"):
            attendance_tool._wecom_access_token()

    urlopen.assert_not_called()


def test_tushare_request_requires_environment_token() -> None:
    from src.tools import tushare_mcp

    with patch.object(tushare_mcp, "TUSHARE_TOKEN", ""), patch("urllib.request.urlopen") as urlopen:
        result = tushare_mcp.call_tushare("daily", {})

    assert "TUSHARE_TOKEN" in result
    urlopen.assert_not_called()

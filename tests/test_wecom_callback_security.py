from __future__ import annotations

import pytest

from src.gateway.wecom_callback_server import ET
from unittest.mock import patch


def test_callback_xml_parser_rejects_entity_declarations() -> None:
    xml = '<!DOCTYPE xml [<!ENTITY injected "unexpected">]><xml>&injected;</xml>'

    with pytest.raises(Exception):
        ET.fromstring(xml)


def test_wecom_callback_routes_approval_event_without_llm_forwarding() -> None:
    from src.gateway.wecom_callback_server import try_handle_approval_event

    payload = {
        "MsgType": "event",
        "Event": "open_approval_change",
        "SpNo": "SP-CB-1",
    }

    with patch("src.platform.leave_quota_service.process_wecom_approval_callback", return_value={"processed": 1}) as process:
        assert try_handle_approval_event(payload) is True

    process.assert_called_once_with(payload)

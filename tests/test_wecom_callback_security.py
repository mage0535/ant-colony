from __future__ import annotations

import pytest

from src.gateway.wecom_callback_server import ET


def test_callback_xml_parser_rejects_entity_declarations() -> None:
    xml = '<!DOCTYPE xml [<!ENTITY injected "unexpected">]><xml>&injected;</xml>'

    with pytest.raises(Exception):
        ET.fromstring(xml)

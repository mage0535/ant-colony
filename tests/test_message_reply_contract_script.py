from __future__ import annotations

import io
import json
from unittest.mock import patch


def test_message_reply_contract_validator_requires_reply() -> None:
    from scripts.validate_message_reply_contract import validate

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"reply": "ok"}, ensure_ascii=False).encode("utf-8")

    with patch("scripts.validate_message_reply_contract.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
        results = validate("http://gateway.test", "u1")

    assert len(results) == 5
    assert all(item["has_reply"] for item in results)
    assert urlopen.call_count == 5


def test_message_reply_contract_main_fails_when_reply_is_empty() -> None:
    from scripts import validate_message_reply_contract

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"reply": ""}).encode("utf-8")

    with patch("scripts.validate_message_reply_contract.urllib.request.urlopen", return_value=FakeResponse()), \
         patch("sys.stdout", new_callable=io.StringIO):
        code = validate_message_reply_contract.main(["--base-url", "http://gateway.test", "--user-id", "u1"])

    assert code == 1

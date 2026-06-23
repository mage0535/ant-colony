from __future__ import annotations

from unittest.mock import patch

from src.platform.api_wecom import WeComClient


def test_wecom_document_search_returns_clickable_urls() -> None:
    response = {
        "item_list": [
            {
                "title": "车间管理规定",
                "creator_name": "马戈",
                "url": "https://doc.weixin.qq.com/example",
            }
        ]
    }

    with patch("src.platform.api_wecom._post", return_value=response):
        result = WeComClient().search_docs("车间")

    assert result == "车间管理规定 | 创建者: 马戈 | https://doc.weixin.qq.com/example"

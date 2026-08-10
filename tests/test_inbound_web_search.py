from unittest.mock import MagicMock, patch


def _service():
    from src.gateway.dispatcher import Dispatcher
    from src.gateway.inbound_service import InboundGatewayService

    service = InboundGatewayService(dispatcher=Dispatcher(), batch_processor=MagicMock())
    fake_convo = MagicMock(get_context=MagicMock(return_value=""), add=MagicMock())
    service._conversations = MagicMock()
    service._conversations.get.return_value = fake_convo
    service._conversations.save_all = MagicMock()
    service.get_or_create_agent = MagicMock()
    return service


def _payload(content: str) -> dict[str, object]:
    return {
        "from_user_id": "u123",
        "msg_type": "text",
        "content": content,
        "is_direct": True,
        "provider": "wecom_bot",
        "transport": "wecom_bot_ws",
    }


def test_general_web_search_request_bypasses_llm_and_uses_paged_aggregate_search() -> None:
    from src.gateway.inbound_service import _file_buffer, _text_buffer, _web_search_page_cache

    _text_buffer.clear()
    _file_buffer.clear()
    _web_search_page_cache.clear()
    service = _service()

    try:
        with patch("src.tools.web_research_service.web_search_aggregate_page", return_value="多源搜索结果") as mock_search:
            result = service.handle_wecom_payload(_payload("上网查找关于异构体金属加工的资料"))
    finally:
        _text_buffer.clear()
        _file_buffer.clear()
        _web_search_page_cache.clear()

    assert result.route_kind == "personal"
    assert "联网检索：异构体金属加工" in result.response.text
    assert "多源搜索结果" in result.response.text
    assert not service.get_or_create_agent.called
    mock_search.assert_called_once_with("异构体金属加工", page=1, page_size=20, max_total=80)


def test_more_web_search_results_uses_cached_query_and_next_page() -> None:
    from src.gateway.inbound_service import _file_buffer, _text_buffer, _web_search_page_cache

    _text_buffer.clear()
    _file_buffer.clear()
    _web_search_page_cache.clear()
    service = _service()

    try:
        with patch("src.tools.web_research_service.web_search_aggregate_page", return_value="分页搜索结果") as mock_search:
            service.handle_wecom_payload(_payload("上网查找关于异构体金属加工的资料"))
            mock_search.reset_mock()
            result = service.handle_wecom_payload(_payload("查看更多"))
    finally:
        _text_buffer.clear()
        _file_buffer.clear()
        _web_search_page_cache.clear()

    assert "联网检索：异构体金属加工" in result.response.text
    assert "分页搜索结果" in result.response.text
    mock_search.assert_called_once_with("异构体金属加工", page=2, page_size=20, max_total=80)


def test_more_web_search_results_without_cache_returns_guidance() -> None:
    from src.gateway.inbound_service import _file_buffer, _text_buffer, _web_search_page_cache

    _text_buffer.clear()
    _file_buffer.clear()
    _web_search_page_cache.clear()
    service = _service()

    try:
        result = service.handle_wecom_payload(_payload("查看更多"))
    finally:
        _text_buffer.clear()
        _file_buffer.clear()
        _web_search_page_cache.clear()

    assert "没有可继续查看的上一轮联网检索结果" in result.response.text

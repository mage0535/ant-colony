from __future__ import annotations

from unittest.mock import patch


def _reset_db(db_path: str) -> None:
    from src.store.database import Database

    Database.get(db_path).close()
    Database._instances.pop(db_path, None)  # type: ignore[attr-defined]


def test_public_data_exchange_query_formats_result() -> None:
    from src.platform import public_data_service as svc

    def fake_json_get(url: str, params: dict):
        assert "frankfurter" in url
        return {"base": "USD", "date": "2026-07-13", "rates": {"CNY": 7.18, "EUR": 0.92}}

    with patch.object(svc, "_json_get", side_effect=fake_json_get):
        result = svc.query_public_data("exchange_rate", params={"base": "USD", "symbols": "CNY,EUR"})

    assert result["kind"] == "exchange_rate"
    assert "USD 汇率" in result["content"]
    assert "CNY: 7.18" in result["content"]


def test_public_data_exchange_query_parses_currency_pair() -> None:
    from src.platform import public_data_service as svc

    def fake_json_get(url: str, params: dict):
        assert params["base"] == "USD"
        assert params["symbols"] == "CNY"
        return {"base": "USD", "date": "2026-07-13", "rates": {"CNY": 7.18}}

    with patch.object(svc, "_json_get", side_effect=fake_json_get):
        result = svc.query_public_data("exchange_rate", query="USD/CNY")

    assert "CNY: 7.18" in result["content"]


def test_public_data_exchange_query_falls_back_to_open_endpoint() -> None:
    from src.platform import public_data_service as svc

    def fake_json_get(url: str, params: dict):
        if "frankfurter" in url:
            raise TimeoutError("timeout")
        assert "open.er-api.com" in url
        return {"time_last_update_utc": "Mon, 27 Jul 2026 00:00:00 +0000", "rates": {"CNY": 7.2}}

    with patch.object(svc, "_json_get", side_effect=fake_json_get):
        result = svc.query_public_data("exchange_rate", query="USD/CNY")

    assert "ExchangeRate-API open endpoint" in result["content"]
    assert "CNY: 7.2" in result["content"]


def test_public_data_weather_uses_known_chinese_city_without_geocoding() -> None:
    from src.platform import public_data_service as svc

    def fake_json_get(url: str, params: dict):
        assert params["latitude"] == 39.9042
        assert params["longitude"] == 116.4074
        return {
            "current": {"temperature_2m": 26, "apparent_temperature": 27, "relative_humidity_2m": 60, "wind_speed_10m": 6, "precipitation": 0},
            "daily": {"time": ["2026-07-13"], "temperature_2m_min": [21], "temperature_2m_max": [30], "precipitation_probability_max": [10]},
        }

    with patch.object(svc, "_json_get", side_effect=fake_json_get):
        result = svc.query_public_data("weather", query="北京")

    assert "北京天气" in result["content"]


def test_public_data_subscription_notifies_only_after_first_snapshot(tmp_path) -> None:
    from src.platform import public_data_service as svc

    db_path = str(tmp_path / "public-data.db")
    sent: list[tuple[str, str, str]] = []
    values = [
        {"base": "USD", "date": "2026-07-13", "rates": {"CNY": 7.18}},
        {"base": "USD", "date": "2026-07-14", "rates": {"CNY": 7.20}},
    ]

    def fake_json_get(url: str, params: dict):
        return values[0]

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch.object(svc, "_json_get", side_effect=fake_json_get), \
         patch("src.platform.public_data_service.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append((p, u, t)) or True):
        _reset_db(db_path)
        sub = svc.create_subscription(
            platform="wecom",
            user_id="u1",
            kind="exchange_rate",
            query="USD/CNY",
            schedule="every 1d",
            params={"base": "USD", "symbols": "CNY"},
        )
        first = svc.run_public_data_subscriptions()
        svc._conn().execute("UPDATE public_data_subscriptions SET last_checked_at = 0")
        svc._conn().commit()
        values.pop(0)
        second = svc.run_public_data_subscriptions()
        listed = svc.list_subscriptions(user_id="u1", platform="wecom")

    assert sub["user_id"] == "u1"
    assert first["checked"] == 1
    assert first["notified"] == 0
    assert second["notified"] == 1
    assert sent[0][0:2] == ("wecom", "u1")
    assert "公共数据订阅更新" in sent[0][2]
    assert listed[0]["last_result"]


def test_public_data_catalog_covers_all_planned_phases() -> None:
    from src.platform.public_data_service import connector_catalog

    ids = {item["id"]: item for item in connector_catalog()}

    for required in [
        "weather",
        "air_quality",
        "exchange_rate",
        "holiday",
        "rss",
        "wikidata",
        "openalex",
        "gdelt",
        "shipment",
        "flight",
        "supply_price",
    ]:
        assert required in ids
    assert ids["shipment"]["status"] == "needs_provider"
    assert ids["flight"]["status"] == "needs_provider"
    assert ids["supply_price"]["status"] == "needs_provider"


def test_public_data_configured_provider_supports_supply_chain_sources() -> None:
    from src.platform import public_data_service as svc

    config = {
        "supply_price": {
            "label": "镍价",
            "url": "https://example.test/price?symbol={query}",
            "type": "json",
            "fields": ["symbol", "price", "currency"],
        }
    }

    def fake_json_get(url: str, params: dict):
        assert url == "https://example.test/price?symbol=NI"
        return {"symbol": "NI", "price": 123456, "currency": "CNY/t"}

    with patch.dict("os.environ", {"PUBLIC_DATA_PROVIDER_CONFIG_JSON": __import__("json").dumps(config)}, clear=False), \
         patch.object(svc, "_json_get", side_effect=fake_json_get):
        result = svc.query_public_data("supply_price", query="NI")

    assert "镍价" in result["content"]
    assert "price: 123456" in result["content"]


def test_public_data_source_config_can_be_saved_and_tested(tmp_path) -> None:
    from src.platform import public_data_service as svc

    db_path = str(tmp_path / "public-data-source.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False):
        _reset_db(db_path)
        saved = svc.save_data_source_config(
            {
                "kind": "flight",
                "label": "航班查询",
                "source": "test",
                "url": "https://example.test/flight?q={query}&key={secret}",
                "type": "json",
                "secret": "secret-1",
                "fields": ["items.0.flight_no:航班号", "items.0.status:状态"],
            }
        )

        def fake_json_get(url: str, params: dict):
            assert url == "https://example.test/flight?q=%E6%98%8E%E5%A4%A9%E5%8E%BB%E5%8C%97%E4%BA%AC%E7%9A%84%E8%88%AA%E7%8F%AD&key=secret-1"
            return {"items": [{"flight_no": "CA1000", "status": "计划"}]}

        with patch.object(svc, "_json_get", side_effect=fake_json_get):
            result = svc.test_data_source("flight", query="明天去北京的航班")
        listed = svc.list_data_source_configs()

    assert saved["secret_configured"] is True
    assert result["ok"] is True
    assert "航班号: CA1000" in result["result"]
    assert any(item["kind"] == "flight" and item["configured"] for item in listed)


def test_public_data_builtin_tools_create_and_list_subscription(tmp_path) -> None:
    from src.tools.builtin import _list_public_data_subscriptions_tool, _subscribe_public_data_tool

    db_path = str(tmp_path / "public-data-tools.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False):
        _reset_db(db_path)
        created = _subscribe_public_data_tool(
            {
                "_source_provider": "wecom_bot",
                "from": "u1",
                "kind": "weather",
                "query": "上海",
                "schedule": "every 1d",
            }
        )
        listed = _list_public_data_subscriptions_tool({"_source_provider": "wecom_bot", "from": "u1"})

    assert "已创建公共数据订阅" in created
    assert "weather 上海" in listed

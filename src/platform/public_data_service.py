from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

from src.gateway import provider_outbound
from src.orchestrator.cron_job import _parse_schedule
from src.store.database import Database


CONNECTOR_CATALOG: dict[str, dict[str, str]] = {
    "weather": {"label": "天气", "source": "Open-Meteo", "status": "ready"},
    "air_quality": {"label": "空气质量", "source": "Open-Meteo Air Quality", "status": "ready"},
    "exchange_rate": {"label": "汇率", "source": "Frankfurter", "status": "ready"},
    "holiday": {"label": "节假日/工作日历", "source": "Nager.Date", "status": "ready"},
    "rss": {"label": "RSS/公告", "source": "RSS/Atom", "status": "ready"},
    "wikidata": {"label": "Wikidata 公共知识", "source": "Wikidata Action API", "status": "ready"},
    "openalex": {"label": "OpenAlex 学术/机构知识", "source": "OpenAlex", "status": "ready"},
    "gdelt": {"label": "GDELT 新闻/舆情", "source": "GDELT DOC 2.0", "status": "ready"},
    "fred": {"label": "宏观指标", "source": "FRED", "status": "needs_api_key"},
    "shipment": {"label": "货运/运单", "source": "Karrio/承运商 API", "status": "needs_provider"},
    "flight": {"label": "航班", "source": "航司/机场/聚合 API", "status": "needs_provider"},
    "supply_price": {"label": "供应链价格", "source": "交易所/商业行情/企业配置源", "status": "needs_provider"},
    "industry": {"label": "行业监测", "source": "RSS/GDELT/自定义站点", "status": "ready"},
}

MANAGED_SOURCE_KINDS = {"shipment", "flight", "supply_price", "fred"}


def query_public_data(kind: str, query: str = "", params: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = _normalize_kind(kind)
    payload = _prepare_query_params(normalized, query, dict(params or {}))
    if query:
        payload.setdefault("query", query)
    meta = CONNECTOR_CATALOG.get(normalized, {"label": normalized, "status": "unknown"})
    try:
        if normalized == "weather":
            result = _query_weather(payload)
        elif normalized == "air_quality":
            result = _query_air_quality(payload)
        elif normalized == "exchange_rate":
            result = _query_exchange_rate(payload)
        elif normalized == "holiday":
            result = _query_holiday(payload)
        elif normalized == "rss":
            result = _query_rss(payload)
        elif normalized == "wikidata":
            result = _query_wikidata(payload)
        elif normalized == "openalex":
            result = _query_openalex(payload)
        elif normalized in {"gdelt", "industry"}:
            result = _query_gdelt(payload)
        elif normalized == "fred":
            result = _query_fred(payload)
        elif normalized in {"shipment", "flight", "supply_price"}:
            result = _query_configured_provider(normalized, payload)
        else:
            result = f"{meta.get('label', normalized)}连接器已登记，但需要配置可用数据源或 API 凭据后才能查询。"
    except Exception as exc:
        result = f"{meta.get('label', normalized)}查询暂时失败：{exc}。请稍后重试，或让管理员检查网络、API Key、数据源权限和接口限流。"
    return {
        "kind": normalized,
        "label": CONNECTOR_CATALOG.get(normalized, {}).get("label", normalized),
        "query": payload,
        "content": result,
        "fingerprint": _fingerprint(result),
    }


def create_subscription(
    *,
    platform: str,
    user_id: str,
    kind: str,
    query: str = "",
    schedule: str = "every 1d",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conn = _conn()
    now = time.time()
    sub_id = hashlib.sha256(f"{platform}:{user_id}:{kind}:{query}:{json.dumps(params or {}, sort_keys=True, ensure_ascii=False)}".encode("utf-8")).hexdigest()[:16]
    conn.execute(
        """
        INSERT INTO public_data_subscriptions
            (id, platform, user_id, kind, query, schedule, params_json, enabled, last_fingerprint, last_result, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, '', '', ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            schedule = excluded.schedule,
            params_json = excluded.params_json,
            enabled = 1,
            updated_at = excluded.updated_at
        """,
        (
            sub_id,
            _normalize_platform(platform),
            user_id.strip(),
            _normalize_kind(kind),
            query.strip(),
            _normalize_schedule(schedule),
            json.dumps(params or {}, ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.commit()
    _record_subscription_audit(conn, sub_id, _normalize_platform(platform), user_id.strip(), "create", "已创建或恢复订阅")
    return get_subscription(sub_id) or {}


def list_subscriptions(user_id: str = "", platform: str = "") -> list[dict[str, Any]]:
    conn = _conn()
    normalized_platform = _normalize_platform(platform) if platform else ""
    rows = conn.execute(
        """
        SELECT id, platform, user_id, kind, query, schedule, params_json, enabled, last_fingerprint, last_result, last_checked_at, created_at, updated_at
        FROM public_data_subscriptions
        WHERE (? = '' OR user_id = ?) AND (? = '' OR platform = ?)
        ORDER BY updated_at DESC
        LIMIT 200
        """,
        (user_id, user_id, normalized_platform, normalized_platform),
    ).fetchall()
    return [_row_to_subscription(row) for row in rows]


def get_subscription(sub_id: str) -> dict[str, Any] | None:
    conn = _conn()
    row = conn.execute(
        """
        SELECT id, platform, user_id, kind, query, schedule, params_json, enabled, last_fingerprint, last_result, last_checked_at, created_at, updated_at
        FROM public_data_subscriptions
        WHERE id = ?
        """,
        (sub_id,),
    ).fetchone()
    return _row_to_subscription(row) if row else None


def set_subscription_enabled(sub_id: str, enabled: bool, *, actor_user_id: str = "") -> dict[str, Any]:
    conn = _conn()
    subscription = get_subscription(sub_id)
    if not subscription:
        raise ValueError("未找到该订阅")
    if actor_user_id and actor_user_id != subscription["user_id"]:
        raise PermissionError("只能管理自己的公共数据订阅")
    conn.execute(
        "UPDATE public_data_subscriptions SET enabled = ?, updated_at = ? WHERE id = ?",
        (1 if enabled else 0, time.time(), sub_id),
    )
    conn.commit()
    _record_subscription_audit(conn, sub_id, subscription["platform"], subscription["user_id"], "resume" if enabled else "pause", "用户修改订阅状态")
    return get_subscription(sub_id) or {}


def delete_subscription(sub_id: str, *, actor_user_id: str = "") -> dict[str, Any]:
    conn = _conn()
    subscription = get_subscription(sub_id)
    if not subscription:
        return {"id": sub_id, "deleted": False}
    if actor_user_id and actor_user_id != subscription["user_id"]:
        raise PermissionError("只能删除自己的公共数据订阅")
    conn.execute("DELETE FROM public_data_subscriptions WHERE id = ?", (sub_id,))
    conn.commit()
    _record_subscription_audit(conn, sub_id, subscription["platform"], subscription["user_id"], "delete", "用户删除订阅")
    return {"id": sub_id, "deleted": True}


def list_subscription_audit(user_id: str = "", platform: str = "") -> list[dict[str, Any]]:
    normalized_platform = _normalize_platform(platform) if platform else ""
    rows = _conn().execute(
        "SELECT subscription_id, platform, user_id, action, detail, created_at FROM public_data_subscription_audit "
        "WHERE (? = '' OR user_id = ?) AND (? = '' OR platform = ?) ORDER BY created_at DESC LIMIT 200",
        (user_id, user_id, normalized_platform, normalized_platform),
    ).fetchall()
    return [dict(row) for row in rows]


def run_public_data_subscriptions() -> dict[str, Any]:
    conn = _conn()
    rows = conn.execute(
        """
        SELECT id, platform, user_id, kind, query, schedule, params_json, enabled, last_fingerprint, last_result, last_checked_at, created_at, updated_at
        FROM public_data_subscriptions
        WHERE enabled = 1
        ORDER BY updated_at ASC
        LIMIT 500
        """
    ).fetchall()
    checked = 0
    notified = 0
    errors: list[str] = []
    now = time.time()
    for row in rows:
        sub = _row_to_subscription(row)
        if not _is_subscription_due(sub, now):
            continue
        try:
            result = query_public_data(sub["kind"], sub["query"], sub["params"])
            checked += 1
            if result["fingerprint"] != sub.get("last_fingerprint"):
                _update_subscription_result(conn, sub["id"], result)
                if sub.get("last_fingerprint"):
                    sent = provider_outbound.send_platform_text(
                        sub["platform"],
                        sub["user_id"],
                        f"【公共数据订阅更新】{result['label']}\n{result['content']}",
                    )
                    _record_subscription_audit(conn, sub["id"], sub["platform"], sub["user_id"], "notify" if sent else "notify_failed", result["label"])
                    notified += int(bool(sent))
            else:
                _touch_subscription_checked(conn, sub["id"], now)
        except Exception as exc:
            errors.append(f"{sub['id']}:{exc}")
    return {"checked": checked, "notified": notified, "errors": errors[:20]}


def connector_catalog() -> list[dict[str, str]]:
    configs = _load_external_source_config()
    catalog: list[dict[str, str]] = []
    for key, value in sorted(CONNECTOR_CATALOG.items()):
        item = {"id": key, **value}
        if key in configs:
            item["status"] = "configured" if configs[key].get("enabled", True) else "disabled"
            item["source"] = str(configs[key].get("source") or configs[key].get("label") or value.get("source") or "")
        catalog.append(item)
    return catalog


def list_data_source_configs() -> list[dict[str, Any]]:
    configs = _load_external_source_config()
    rows: list[dict[str, Any]] = []
    for item in connector_catalog():
        kind = item["id"]
        config = configs.get(kind) if isinstance(configs.get(kind), dict) else {}
        rows.append(_public_config_view(kind, config, item))
    return rows


def save_data_source_config(config: dict[str, Any]) -> dict[str, Any]:
    kind = _normalize_kind(str(config.get("kind") or ""))
    if not kind:
        raise ValueError("缺少数据源类型")
    if kind not in CONNECTOR_CATALOG:
        raise ValueError(f"不支持的数据源类型：{kind}")
    now = time.time()
    conn = _conn()
    existing = _load_db_source_config(kind)
    secret = str(config.get("secret") or "")
    headers = config.get("headers") if isinstance(config.get("headers"), dict) else {}
    params = config.get("params") if isinstance(config.get("params"), dict) else {}
    body = config.get("body") if isinstance(config.get("body"), dict) else {}
    fields = config.get("fields") if isinstance(config.get("fields"), list) else []
    normalized = {
        "kind": kind,
        "label": str(config.get("label") or CONNECTOR_CATALOG[kind]["label"]).strip(),
        "source": str(config.get("source") or CONNECTOR_CATALOG[kind]["source"]).strip(),
        "url": str(config.get("url") or "").strip(),
        "method": str(config.get("method") or "GET").upper(),
        "type": str(config.get("type") or "json").lower(),
        "headers": headers,
        "params": params,
        "body": body,
        "fields": fields,
        "enabled": bool(config.get("enabled", True)),
        "notes": str(config.get("notes") or "").strip(),
    }
    if secret:
        normalized["secret"] = secret
    elif existing and existing.get("secret"):
        normalized["secret"] = existing["secret"]
    if normalized["method"] not in {"GET", "POST"}:
        raise ValueError("请求方式只支持 GET 或 POST")
    conn.execute(
        """
        INSERT INTO public_data_source_configs
            (kind, label, source, url, method, parser_type, headers_json, params_json, body_json, fields_json, secret, enabled, notes, last_test_ok, last_test_result, last_test_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', 0, ?)
        ON CONFLICT(kind) DO UPDATE SET
            label = excluded.label,
            source = excluded.source,
            url = excluded.url,
            method = excluded.method,
            parser_type = excluded.parser_type,
            headers_json = excluded.headers_json,
            params_json = excluded.params_json,
            body_json = excluded.body_json,
            fields_json = excluded.fields_json,
            secret = excluded.secret,
            enabled = excluded.enabled,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        (
            kind,
            normalized["label"],
            normalized["source"],
            normalized["url"],
            normalized["method"],
            normalized["type"],
            json.dumps(headers, ensure_ascii=False),
            json.dumps(params, ensure_ascii=False),
            json.dumps(body, ensure_ascii=False),
            json.dumps(fields, ensure_ascii=False),
            normalized.get("secret", ""),
            1 if normalized["enabled"] else 0,
            normalized["notes"],
            now,
        ),
    )
    conn.commit()
    return _public_config_view(kind, _load_db_source_config(kind) or {}, CONNECTOR_CATALOG[kind])


def delete_data_source_config(kind: str) -> dict[str, Any]:
    normalized = _normalize_kind(kind)
    _conn().execute("DELETE FROM public_data_source_configs WHERE kind = ?", (normalized,))
    _conn().commit()
    return {"kind": normalized, "deleted": True}


def test_data_source(kind: str, query: str = "", params: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = _normalize_kind(kind)
    start = time.time()
    result = query_public_data(normalized, query=query or _sample_query_for_kind(normalized), params=params or {})
    ok = not any(marker in result["content"] for marker in ["需要管理员配置", "配置缺少", "查询暂时失败", "需要先在服务器配置"])
    elapsed_ms = int((time.time() - start) * 1000)
    conn = _conn()
    if normalized in MANAGED_SOURCE_KINDS:
        conn.execute(
            "UPDATE public_data_source_configs SET last_test_ok = ?, last_test_result = ?, last_test_at = ? WHERE kind = ?",
            (1 if ok else 0, result["content"][:2000], time.time(), normalized),
        )
        conn.commit()
    return {"kind": normalized, "ok": ok, "elapsed_ms": elapsed_ms, "result": result["content"], "query": result["query"]}


def _conn():
    conn = Database.get().connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_data_subscriptions (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            query TEXT NOT NULL DEFAULT '',
            schedule TEXT NOT NULL DEFAULT 'every 1d',
            params_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            last_fingerprint TEXT NOT NULL DEFAULT '',
            last_result TEXT NOT NULL DEFAULT '',
            last_checked_at REAL NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(public_data_subscriptions)").fetchall()}
    if "last_checked_at" not in cols:
        conn.execute("ALTER TABLE public_data_subscriptions ADD COLUMN last_checked_at REAL NOT NULL DEFAULT 0")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_data_subscription_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subscription_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_data_source_configs (
            kind TEXT PRIMARY KEY,
            label TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            method TEXT NOT NULL DEFAULT 'GET',
            parser_type TEXT NOT NULL DEFAULT 'json',
            headers_json TEXT NOT NULL DEFAULT '{}',
            params_json TEXT NOT NULL DEFAULT '{}',
            body_json TEXT NOT NULL DEFAULT '{}',
            fields_json TEXT NOT NULL DEFAULT '[]',
            secret TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            notes TEXT NOT NULL DEFAULT '',
            last_test_ok INTEGER NOT NULL DEFAULT 0,
            last_test_result TEXT NOT NULL DEFAULT '',
            last_test_at REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    return conn


def _row_to_subscription(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "platform": row["platform"],
        "user_id": row["user_id"],
        "kind": row["kind"],
        "query": row["query"],
        "schedule": row["schedule"],
        "params": json.loads(row["params_json"] or "{}"),
        "enabled": bool(row["enabled"]),
        "last_fingerprint": row["last_fingerprint"],
        "last_result": row["last_result"],
        "last_checked_at": row["last_checked_at"] if "last_checked_at" in row.keys() else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _update_subscription_result(conn: Any, sub_id: str, result: dict[str, Any]) -> None:
    conn.execute(
        """
        UPDATE public_data_subscriptions
        SET last_fingerprint = ?, last_result = ?, last_checked_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (result["fingerprint"], result["content"], time.time(), time.time(), sub_id),
    )
    conn.commit()


def _touch_subscription_checked(conn: Any, sub_id: str, checked_at: float) -> None:
    conn.execute(
        """
        UPDATE public_data_subscriptions
        SET last_checked_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (checked_at, time.time(), sub_id),
    )
    conn.commit()


def _record_subscription_audit(conn: Any, sub_id: str, platform: str, user_id: str, action: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO public_data_subscription_audit (subscription_id, platform, user_id, action, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (sub_id, platform, user_id, action, detail[:1000], time.time()),
    )
    conn.commit()


def _query_weather(params: dict[str, Any]) -> str:
    lat, lon, name = _resolve_location(params)
    data = _json_get(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 3,
            "timezone": "auto",
        },
    )
    current = data.get("current", {})
    daily = data.get("daily", {})
    lines = [
        f"{name}天气：{current.get('temperature_2m', '-')}°C，体感 {current.get('apparent_temperature', '-')}°C，湿度 {current.get('relative_humidity_2m', '-')}%，风速 {current.get('wind_speed_10m', '-')} km/h。",
        f"当前降水：{current.get('precipitation', 0)} mm。",
    ]
    dates = daily.get("time", [])[:3]
    for index, day in enumerate(dates):
        lines.append(
            f"{day}：{daily.get('temperature_2m_min', ['-'])[index]}-{daily.get('temperature_2m_max', ['-'])[index]}°C，降水概率 {daily.get('precipitation_probability_max', ['-'])[index]}%。"
        )
    return "\n".join(lines)


def _query_air_quality(params: dict[str, Any]) -> str:
    lat, lon, name = _resolve_location(params)
    data = _json_get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        {
            "latitude": lat,
            "longitude": lon,
            "current": "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,uv_index,european_aqi,us_aqi",
            "timezone": "auto",
        },
    )
    current = data.get("current", {})
    return (
        f"{name}空气质量：欧标 AQI {current.get('european_aqi', '-')}，美标 AQI {current.get('us_aqi', '-')}。\n"
        f"PM2.5 {current.get('pm2_5', '-')}，PM10 {current.get('pm10', '-')}，O3 {current.get('ozone', '-')}，NO2 {current.get('nitrogen_dioxide', '-')}，UV {current.get('uv_index', '-')}。"
    )


def _query_exchange_rate(params: dict[str, Any]) -> str:
    base = str(params.get("base") or "USD").upper()
    if params.get("symbols"):
        symbols = str(params.get("symbols") or "CNY,EUR,JPY").upper()
    else:
        raw_symbols = str(params.get("query") or "CNY,EUR,JPY").upper().replace("/", ",")
        parts = [part.strip() for part in raw_symbols.split(",") if part.strip()]
        if "," in raw_symbols and len(parts) >= 2:
            base = parts[0]
            symbols = ",".join(part for part in parts[1:] if part != base) or "CNY"
        else:
            symbols = "CNY" if raw_symbols == base else raw_symbols
    try:
        data = _json_get("https://api.frankfurter.dev/v1/latest", {"base": base, "symbols": symbols})
        rates = data.get("rates", {})
        source = "Frankfurter"
        date = data.get("date", "")
    except Exception:
        data = _json_get(f"https://open.er-api.com/v6/latest/{base}", {})
        all_rates = data.get("rates", {})
        rates = {symbol: all_rates.get(symbol) for symbol in symbols.split(",") if symbol in all_rates}
        source = "ExchangeRate-API open endpoint"
        date = data.get("time_last_update_utc", "")
    if not rates:
        return f"未查询到 {base} -> {symbols} 汇率。"
    return f"{date} {base} 汇率（{source}）：" + "，".join(f"{key}: {value}" for key, value in rates.items())


def _query_holiday(params: dict[str, Any]) -> str:
    country = str(params.get("country") or params.get("query") or "CN").upper()
    year = int(params.get("year") or datetime.now().year)
    data = _json_get(f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country}", {})
    lines = [f"{country} {year} 节假日："]
    for item in data[:12] if isinstance(data, list) else []:
        lines.append(f"{item.get('date', '')} {item.get('localName') or item.get('name')}")
    return "\n".join(lines) if len(lines) > 1 else f"未查询到 {country} {year} 节假日。"


def _query_rss(params: dict[str, Any]) -> str:
    url = str(params.get("url") or params.get("query") or "")
    if not url:
        return "请提供 RSS/Atom 地址。"
    raw = _text_get(url)
    root = ET.fromstring(raw)
    items = root.findall(".//item") or root.findall("{http://www.w3.org/2005/Atom}entry")
    lines = ["RSS 最新内容："]
    for item in items[:5]:
        title = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "无标题"
        link = item.findtext("link") or ""
        lines.append(f"- {title}" + (f" {link}" if link else ""))
    return "\n".join(lines)


def _query_wikidata(params: dict[str, Any]) -> str:
    query = str(params.get("query") or "")
    if not query:
        return "请提供要查询的机构、人物、概念或主题。"
    data = _json_get(
        "https://www.wikidata.org/w/api.php",
        {"action": "wbsearchentities", "search": query, "language": "zh", "format": "json", "limit": 5},
    )
    lines = [f"Wikidata 查询：{query}"]
    for item in data.get("search", [])[:5]:
        lines.append(f"- {item.get('label', '')}（{item.get('id', '')}）：{item.get('description', '')}")
    return "\n".join(lines)


def _query_openalex(params: dict[str, Any]) -> str:
    query = str(params.get("query") or "")
    if not query:
        return "请提供论文、机构、作者或研究主题关键词。"
    request_params = {"search": query, "per-page": 5}
    if os.environ.get("OPENALEX_MAILTO"):
        request_params["mailto"] = os.environ["OPENALEX_MAILTO"]
    data = _json_get("https://api.openalex.org/works", request_params)
    lines = [f"OpenAlex 查询：{query}"]
    for item in data.get("results", [])[:5]:
        year = item.get("publication_year", "")
        title = item.get("display_name", "")
        cited = item.get("cited_by_count", 0)
        lines.append(f"- {year} {title}，引用 {cited}")
    return "\n".join(lines)


def _query_gdelt(params: dict[str, Any]) -> str:
    query = str(params.get("query") or "")
    if not query:
        return "请提供新闻/行业监测关键词。"
    data = _json_get(
        "https://api.gdeltproject.org/api/v2/doc/doc",
        {"query": query, "mode": "ArtList", "format": "json", "maxrecords": 5, "sort": "HybridRel"},
    )
    lines = [f"GDELT 新闻监测：{query}"]
    for item in data.get("articles", [])[:5]:
        lines.append(f"- {item.get('title', '')} {item.get('url', '')}")
    return "\n".join(lines)


def _query_fred(params: dict[str, Any]) -> str:
    config = _load_external_source_config().get("fred") or {}
    api_key = str(config.get("secret") or os.environ.get("FRED_API_KEY", ""))
    if not api_key:
        return "FRED 宏观指标需要先在服务器配置 FRED_API_KEY。"
    series_id = str(params.get("series_id") or params.get("query") or "DFF").upper()
    data = _json_get(
        "https://api.stlouisfed.org/fred/series/observations",
        {"series_id": series_id, "api_key": api_key, "file_type": "json", "sort_order": "desc", "limit": 3},
    )
    lines = [f"FRED {series_id}："]
    for item in data.get("observations", [])[:3]:
        lines.append(f"- {item.get('date')}: {item.get('value')}")
    return "\n".join(lines)


def _query_configured_provider(kind: str, params: dict[str, Any]) -> str:
    config = _load_external_source_config().get(kind) or {}
    if not config:
        return _query_unconfigured_provider_fallback(kind, params)
    if config.get("enabled") is False:
        label = str(config.get("label") or CONNECTOR_CATALOG.get(kind, {}).get("label", kind))
        return f"{label}数据源已配置但当前处于停用状态。"
    template = str(config.get("url") or "")
    if not template:
        return f"{kind} 数据源配置缺少 url。"
    query = str(params.get("query") or params.get("tracking_no") or params.get("flight_no") or params.get("symbol") or "")
    request_params = _merge_template_params(config.get("params"), {**params, "query": query}, quote_values=False)
    format_params = {key: urllib.parse.quote(str(value), safe="") for key, value in {**request_params, **params, "query": query}.items()}
    format_params.setdefault("secret", urllib.parse.quote(str(config.get("secret") or ""), safe=""))
    url = _safe_format(template, format_params)
    parser = str(config.get("type") or "text").lower()
    label = str(config.get("label") or CONNECTOR_CATALOG.get(kind, {}).get("label", kind))
    method = str(config.get("method") or "GET").upper()
    headers = _merge_template_params(config.get("headers"), {**params, "query": query, "secret": config.get("secret", "")}, quote_values=False)
    if config.get("secret") and not any(str(config.get("secret")) in str(value) for value in list(headers.values()) + [url]):
        headers.setdefault("Authorization", f"Bearer {config.get('secret')}")
    body = _merge_template_params(config.get("body"), {**params, "query": query, "secret": config.get("secret", "")}, quote_values=False)
    if parser == "json":
        if method == "GET" and not headers and not body:
            data = _json_get(url, request_params)
        else:
            data = _json_request(url, method=method, headers=headers, params=request_params if method == "GET" else {}, body=body if method == "POST" else None)
        fields = config.get("fields") if isinstance(config.get("fields"), list) else []
        if fields:
            lines = [f"{label}："]
            for field in fields[:12]:
                field_path, field_label = _split_field(str(field))
                value = _extract_json_path(data, field_path)
                lines.append(f"- {field_label}: {value}")
            return "\n".join(lines)
        return f"{label}：{json.dumps(data, ensure_ascii=False)[:1200]}"
    if parser == "rss":
        return _query_rss({"url": url})
    text = _text_request(url, method=method, headers=headers, params=request_params if method == "GET" else {}, body=body if method == "POST" else None).strip()
    return f"{label}：{text[:1200] if text else '数据源未返回内容'}"


def _load_external_source_config() -> dict[str, Any]:
    configs = _load_db_source_configs()
    raw = os.environ.get("PUBLIC_DATA_PROVIDER_CONFIG_JSON", "").strip()
    if not raw:
        path = os.environ.get("PUBLIC_DATA_PROVIDER_CONFIG_FILE", "").strip()
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
    if not raw:
        return configs
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return configs
    if isinstance(data, dict):
        configs.update(data)
    return configs


def _load_db_source_configs() -> dict[str, Any]:
    try:
        conn = _conn()
        rows = conn.execute("SELECT * FROM public_data_source_configs").fetchall()
    except Exception:
        return {}
    return {row["kind"]: _row_to_source_config(row, include_secret=True) for row in rows}


def _load_db_source_config(kind: str) -> dict[str, Any] | None:
    try:
        row = _conn().execute("SELECT * FROM public_data_source_configs WHERE kind = ?", (_normalize_kind(kind),)).fetchone()
    except Exception:
        return None
    return _row_to_source_config(row, include_secret=True) if row else None


def _row_to_source_config(row: Any, *, include_secret: bool) -> dict[str, Any]:
    config = {
        "kind": row["kind"],
        "label": row["label"],
        "source": row["source"],
        "url": row["url"],
        "method": row["method"],
        "type": row["parser_type"],
        "headers": _json_loads_obj(row["headers_json"], {}),
        "params": _json_loads_obj(row["params_json"], {}),
        "body": _json_loads_obj(row["body_json"], {}),
        "fields": _json_loads_obj(row["fields_json"], []),
        "enabled": bool(row["enabled"]),
        "notes": row["notes"],
        "last_test_ok": bool(row["last_test_ok"]),
        "last_test_result": row["last_test_result"],
        "last_test_at": row["last_test_at"],
        "updated_at": row["updated_at"],
        "secret_configured": bool(row["secret"]),
    }
    if include_secret:
        config["secret"] = row["secret"]
    return config


def _public_config_view(kind: str, config: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    view = dict(config)
    view.pop("secret", None)
    view.setdefault("kind", kind)
    view.setdefault("label", catalog.get("label", kind))
    view.setdefault("source", catalog.get("source", ""))
    view.setdefault("status", catalog.get("status", "unknown"))
    view.setdefault("enabled", bool(config) and config.get("enabled", True))
    view.setdefault("configured", bool(config))
    view["configured"] = bool(config)
    view["secret_configured"] = bool(config.get("secret_configured") or config.get("secret"))
    if not view.get("url") and kind in {"weather", "air_quality", "exchange_rate", "holiday", "rss", "wikidata", "openalex", "gdelt", "industry"}:
        view["builtin"] = True
    return view


def _json_loads_obj(raw: str, fallback: Any) -> Any:
    try:
        data = json.loads(raw or "")
    except Exception:
        return fallback
    return data


def _query_unconfigured_provider_fallback(kind: str, params: dict[str, Any]) -> str:
    label = CONNECTOR_CATALOG.get(kind, {}).get("label", kind)
    query = _build_external_search_query(kind, params)
    if not query:
        return f"{label}连接器已登记，但需要管理员配置企业可用数据源后才能查询。"
    try:
        from src.tools.web_research_service import web_search_aggregate

        result = web_search_aggregate(query, max_results=10)
        if "未找到高相关搜索结果" in result or "未找到可用搜索结果" in result:
            from src.tools.web_research_service import web_search

            result = web_search(query, max_results=10)
        curated = _curated_public_lookup_links(kind, params, query)
        if curated and kind == "flight":
            result = curated
        elif curated and _looks_low_quality_search_result(result):
            result = curated
        elif curated:
            result = f"{curated}\n\n公开搜索结果参考：\n{result}"
        return (
            f"{label}暂无已授权的企业实时数据源，已改用联网检索兜底。\n"
            "注意：以下结果来自公开网页/搜索源，不等同于企业授权接口的实时准确数据；涉及订票、物流签收、行情交易前请以官方系统为准。\n\n"
            f"{result}"
        )
    except Exception as exc:
        return f"{label}连接器已登记，但企业实时数据源未配置，联网检索兜底也暂时失败：{exc}。"


def _prepare_query_params(kind: str, query: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = dict(params or {})
    text = str(query or payload.get("query") or "").strip()
    if text:
        payload.setdefault("query", text)
    if kind == "flight":
        payload.update({k: v for k, v in _parse_flight_query(text).items() if v and not payload.get(k)})
    elif kind == "shipment":
        payload.update({k: v for k, v in _parse_shipment_query(text).items() if v and not payload.get(k)})
    elif kind == "supply_price":
        payload.update({k: v for k, v in _parse_supply_price_query(text).items() if v and not payload.get(k)})
    elif kind == "fred":
        payload.update({k: v for k, v in _parse_fred_query(text).items() if v and not payload.get(k)})
    return payload


def _parse_flight_query(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    today = datetime.now()
    if "明天" in text:
        result["date"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "后天" in text:
        result["date"] = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    elif match := re_search_date(text):
        result["date"] = match
    flight_match = re_search(r"\b([A-Z]{2}\d{2,5}|[A-Z0-9]{2}\d{3,5})\b", text.upper())
    if flight_match:
        result["flight_no"] = flight_match
    if "北京" in text:
        result["arrival_city"] = "北京"
        result["arrival_iata"] = "BJS"
    if "上海" in text:
        if "到上海" in text or "去上海" in text:
            result["arrival_city"] = "上海"
            result["arrival_iata"] = "SHA"
        else:
            result.setdefault("departure_city", "上海")
            result.setdefault("departure_iata", "SHA")
    if "烟台" in text:
        result.setdefault("departure_city", "烟台")
        result.setdefault("departure_iata", "YNT")
    return result


def _parse_shipment_query(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if match := re_search(r"\b([A-Z0-9]{8,30})\b", text.upper()):
        result["tracking_no"] = match
    for carrier in ["顺丰", "京东", "德邦", "中通", "圆通", "申通", "韵达", "EMS", "DHL", "FedEx", "UPS"]:
        if carrier.lower() in text.lower():
            result["carrier"] = carrier
            break
    return result


def _parse_supply_price_query(text: str) -> dict[str, str]:
    mapping = {
        "镍": "NI",
        "铬": "CR",
        "铜": "CU",
        "铝": "AL",
        "锌": "ZN",
        "锡": "SN",
        "铅": "PB",
        "不锈钢": "SS",
    }
    for keyword, symbol in mapping.items():
        if keyword in text:
            return {"symbol": symbol, "commodity": keyword}
    if match := re_search(r"\b(NI|CR|CU|AL|ZN|SN|PB|SS)\b", text.upper()):
        return {"symbol": match}
    return {}


def _parse_fred_query(text: str) -> dict[str, str]:
    mapping = {
        "联邦基金利率": "DFF",
        "美国失业率": "UNRATE",
        "美国cpi": "CPIAUCSL",
        "美元指数": "DTWEXBGS",
    }
    lowered = text.lower()
    for keyword, series_id in mapping.items():
        if keyword.lower() in lowered:
            return {"series_id": series_id}
    return {}


def _build_external_search_query(kind: str, params: dict[str, Any]) -> str:
    query = str(params.get("query") or "").strip()
    if kind == "flight":
        original = str(params.get("query") or "")
        date = str(params.get("date") or "")
        arrival = str(params.get("arrival_city") or params.get("arrival_iata") or "")
        departure = str(params.get("departure_city") or params.get("departure_iata") or "")
        flight_no = str(params.get("flight_no") or "")
        parts = [original, flight_no, departure, arrival, date, "航班 动态 时刻表 机场 官方"]
        return " ".join(part for part in parts if part).strip() or query
    if kind == "shipment":
        tracking = str(params.get("tracking_no") or "")
        carrier = str(params.get("carrier") or "")
        return " ".join(part for part in [carrier, tracking, "物流 轨迹 查询 官方"] if part).strip() or query
    if kind == "supply_price":
        commodity = str(params.get("commodity") or params.get("symbol") or query)
        return f"{commodity} 价格 行情 LME 市场 今日"
    return query


def _curated_public_lookup_links(kind: str, params: dict[str, Any], query: str) -> str:
    encoded_query = urllib.parse.quote(query, safe="")
    if kind == "flight":
        departure = str(params.get("departure_city") or "")
        arrival = str(params.get("arrival_city") or "")
        date = str(params.get("date") or "")
        route = f"{departure or '出发地'} -> {arrival or '目的地'}"
        lines = [
            "未配置企业授权航班 API 时，建议先通过以下公开入口核对；如果要让 AI 助手直接返回准确班期，请在后台配置企业差旅平台、航司、机场或航班聚合 API。",
            f"解析到的条件：{route}，日期：{date or '未识别'}。",
        ]
        if not departure:
            lines.append("当前问题缺少出发城市。请补充类似“明天从烟台去北京的航班”。也可以在后台设置供应商接口后由接口自行处理模糊条件。")
        lines.extend(
            [
                f"- 必应搜索： https://www.bing.com/search?q={encoded_query}",
                f"- 携程机票： https://flights.ctrip.com/online/channel/domestic",
                f"- 去哪儿机票： https://flight.qunar.com/",
                f"- 飞常准/航班动态： https://www.variflight.com/",
            ]
        )
        return "\n".join(lines)
    if kind == "shipment":
        tracking_no = str(params.get("tracking_no") or "")
        lines = [
            "未配置企业授权物流 API 时，建议先通过承运商官网或聚合查询入口核对；如果要自动推送物流状态，请在后台配置 Karrio 或承运商 API。",
            f"- 搜索查询： https://www.bing.com/search?q={encoded_query}",
        ]
        if tracking_no:
            lines.append(f"- 快递100 查询入口： https://www.kuaidi100.com/?nu={urllib.parse.quote(tracking_no, safe='')}")
        return "\n".join(lines)
    if kind == "supply_price":
        return "\n".join(
            [
                "未配置企业授权行情 API 时，公开网页只能作为参考，不能作为采购、交易或合同定价依据。",
                f"- 搜索查询： https://www.bing.com/search?q={encoded_query}",
                "- LME 官方入口： https://www.lme.com/",
                "- 上海有色网入口： https://www.smm.cn/",
                "- Metals-API： https://metals-api.com/",
                "- Metals.Dev： https://metals.dev/",
            ]
        )
    return ""


def _looks_low_quality_search_result(result: str) -> bool:
    lowered = result.lower()
    if "未找到高相关搜索结果" in result or "未找到可用搜索结果" in result:
        return True
    bad_markers = ["how to get help in windows", "microsoft support", "windows help and learning"]
    return any(marker in lowered for marker in bad_markers)


def _merge_template_params(template_values: Any, values: dict[str, Any], *, quote_values: bool) -> dict[str, str]:
    if not isinstance(template_values, dict):
        return {}
    result: dict[str, str] = {}
    replacements = {key: str(value) for key, value in values.items() if value is not None}
    if quote_values:
        replacements = {key: urllib.parse.quote(value, safe="") for key, value in replacements.items()}
    for key, value in template_values.items():
        result[str(key)] = _safe_format(str(value), replacements)
    return result


def _safe_format(template: str, values: dict[str, Any]) -> str:
    class _SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return ""

    try:
        return template.format_map(_SafeDict({k: str(v) for k, v in values.items()}))
    except Exception:
        return template


def _split_field(field: str) -> tuple[str, str]:
    if ":" in field:
        path, label = field.split(":", 1)
        return path.strip(), label.strip() or path.strip()
    return field.strip(), field.strip()


def _sample_query_for_kind(kind: str) -> str:
    return {
        "weather": "北京",
        "air_quality": "北京",
        "exchange_rate": "USD,CNY",
        "holiday": "CN",
        "rss": "https://www.gov.cn/rss/ywdt.xml",
        "wikidata": "北京",
        "openalex": "hydrogen reformer tube defect",
        "gdelt": "制造业",
        "industry": "制造业",
        "fred": "DFF",
        "shipment": "SF1234567890",
        "flight": "明天去北京的航班",
        "supply_price": "镍",
    }.get(kind, "测试")


def re_search(pattern: str, text: str) -> str:
    import re

    match = re.search(pattern, text)
    return match.group(1) if match else ""


def re_search_date(text: str) -> str:
    import re

    match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if not match:
        return ""
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _extract_json_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _resolve_location(params: dict[str, Any]) -> tuple[float, float, str]:
    if params.get("latitude") and params.get("longitude"):
        return float(params["latitude"]), float(params["longitude"]), str(params.get("name") or params.get("query") or "当前位置")
    name = str(params.get("city") or params.get("query") or "Shanghai")
    city = _known_city_location(name)
    if city:
        return city
    data = _json_get(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": name, "count": 1, "language": "zh", "format": "json"},
    )
    results = data.get("results", [])
    if not results:
        raise ValueError(f"未找到地点：{name}")
    item = results[0]
    label = item.get("name") or name
    country = item.get("country") or ""
    return float(item["latitude"]), float(item["longitude"]), f"{label}{'/' + country if country else ''}"


def _known_city_location(name: str) -> tuple[float, float, str] | None:
    text = str(name or "").lower()
    cities = {
        "北京": (39.9042, 116.4074, "北京"),
        "beijing": (39.9042, 116.4074, "北京"),
        "上海": (31.2304, 121.4737, "上海"),
        "shanghai": (31.2304, 121.4737, "上海"),
        "烟台": (37.4638, 121.4479, "烟台"),
        "yantai": (37.4638, 121.4479, "烟台"),
        "济南": (36.6512, 117.1201, "济南"),
        "jinan": (36.6512, 117.1201, "济南"),
        "青岛": (36.0671, 120.3826, "青岛"),
        "qingdao": (36.0671, 120.3826, "青岛"),
        "广州": (23.1291, 113.2644, "广州"),
        "guangzhou": (23.1291, 113.2644, "广州"),
        "深圳": (22.5431, 114.0579, "深圳"),
        "shenzhen": (22.5431, 114.0579, "深圳"),
        "杭州": (30.2741, 120.1551, "杭州"),
        "hangzhou": (30.2741, 120.1551, "杭州"),
        "南京": (32.0603, 118.7969, "南京"),
        "nanjing": (32.0603, 118.7969, "南京"),
        "成都": (30.5728, 104.0668, "成都"),
        "chengdu": (30.5728, 104.0668, "成都"),
    }
    for key, value in cities.items():
        if key in text:
            return value
    return None


def _json_get(url: str, params: dict[str, Any]) -> Any:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in ("", None)})
    full_url = f"{url}?{query}" if query else url
    raw = _text_get(full_url)
    return json.loads(raw)


def _text_get(url: str) -> str:
    return _text_request(url)


def _json_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    return json.loads(_text_request(url, method=method, headers=headers, params=params, body=body))


def _text_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> str:
    request_headers = {"User-Agent": "Ant-Colony-AI-Assistant/1.0", **(headers or {})}
    data = None
    final_url = url
    if method.upper() == "GET" and params:
        separator = "&" if "?" in final_url else "?"
        final_url = f"{final_url}{separator}{urllib.parse.urlencode({k: v for k, v in params.items() if v not in ('', None)})}"
    if method.upper() == "POST":
        data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(final_url, data=data, headers=request_headers, method=method.upper())
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def _fingerprint(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _is_subscription_due(sub: dict[str, Any], now: float) -> bool:
    last_checked = float(sub.get("last_checked_at") or 0)
    if last_checked <= 0:
        return True
    try:
        return now >= _parse_schedule(str(sub.get("schedule") or "every 1d"), base=last_checked)
    except Exception:
        return now - last_checked >= 86400


def _normalize_schedule(schedule: str) -> str:
    value = str(schedule or "").strip().lower()
    if not value:
        return "every 1d"
    replacements = {
        "每天": "every 1d",
        "每日": "every 1d",
        "一天一次": "every 1d",
        "每小时": "every 1h",
        "每半小时": "every 30 min",
        "每30分钟": "every 30 min",
        "每 30 分钟": "every 30 min",
        "每周": "every 7d",
    }
    for needle, normalized in replacements.items():
        if needle in value:
            return normalized
    return value


def _normalize_kind(kind: str) -> str:
    aliases = {
        "weather_alert": "weather",
        "air": "air_quality",
        "fx": "exchange_rate",
        "exchange": "exchange_rate",
        "macro": "fred",
        "news": "gdelt",
        "holiday_calendar": "holiday",
        "logistics": "shipment",
    }
    lowered = str(kind or "").strip().lower()
    return aliases.get(lowered, lowered or "weather")


def _normalize_platform(platform: str) -> str:
    lowered = str(platform or "wecom").strip().lower()
    return {"wecom_bot": "wecom", "wecom_bot_ws": "wecom", "企微": "wecom", "企业微信": "wecom"}.get(lowered, lowered or "wecom")

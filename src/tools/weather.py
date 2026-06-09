"""Weather tool — fetches real-time weather data via wttr.in with Chinese output."""
from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

_WEATHER_CN = {
    "Sunny": "晴", "Clear": "晴", "Clear ": "晴",
    "Partly cloudy": "多云", "Partly Cloudy": "多云",
    "Cloudy": "阴", "Overcast": "阴",
    "Mist": "薄雾", "Fog": "雾", "Haze": "霾",
    "Light rain": "小雨", "Light Rain": "小雨",
    "Moderate rain": "中雨", "Heavy rain": "大雨", "Heavy Rain": "大雨",
    "Light rain shower": "小阵雨", "Patchy rain possible": "局部有雨",
    "Thundery outbreaks possible": "雷阵雨", "Thunderstorm": "雷暴",
    "Snow": "雪", "Light snow": "小雪", "Heavy snow": "大雪",
    "Sleet": "雨夹雪", "Drizzle": "毛毛雨",
    "Windy": "大风", "Blizzard": "暴风雪",
}


def _cn(text: str) -> str:
    if not text:
        return ""
    for en, cn in _WEATHER_CN.items():
        if text.strip() == en:
            return cn
    return text


def weather_forecast(city: str) -> str:
    if not city or len(city.strip()) < 1:
        return "请输入城市名称"

    city = city.strip()

    try:
        url = f"https://wttr.in/{urllib.request.quote(city)}?format=j1&lang=zh"
        req = urllib.request.Request(url, headers={
            "User-Agent": "curl/8.0",
            "Accept": "application/json",
        })
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode("utf-8"))

        current = data.get("current_condition", [{}])[0]
        if not current:
            return f"未找到{city}的天气数据"

        temp = current.get("temp_C", "N/A")
        feel = current.get("FeelsLikeC", "N/A")
        humidity = current.get("humidity", "N/A")
        wind_speed = current.get("windspeedKmph", "N/A")
        raw_desc = current.get("weatherDesc", [{}])[0].get("value", "")
        desc = _cn(raw_desc)

        forecast = data.get("weather", [])
        forecast_lines = []
        for day in forecast[:3]:
            date = day.get("date", "")
            maxt = day.get("maxtempC", "")
            mint = day.get("mintempC", "")
            desc_day = ""
            if day.get("hourly"):
                for h in day["hourly"]:
                    h_en = h.get("weatherDesc", [{}])[0].get("value", "")
                    if h_en:
                        desc_day = _cn(h_en)
                        break
            forecast_lines.append(f"  {date}: {mint}~{maxt}°C, {desc_day}")

        lines = [
            f"{city} 当前天气",
            f"  温度: {temp}°C（体感 {feel}°C）",
        ]
        if desc:
            lines.append(f"  天气: {desc}")
        lines += [
            f"  湿度: {humidity}%",
            f"  风力: {wind_speed} km/h",
            "",
            "未来三天预报:",
        ]
        lines += forecast_lines
        return "\n".join(lines)

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"未找到城市「{city}」，请检查名称是否正确"
        return f"天气查询失败(HTTP {e.code})"
    except Exception as e:
        logger.warning("Weather fetch failed: %s", e)
        return f"天气查询失败：{e}"

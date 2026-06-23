"""Tushare client — stock market data via Tushare Pro REST API."""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
TUSHARE_API = "https://api.tushare.pro"


def call_tushare(method: str, params: dict[str, Any] | None = None) -> str:
    if not TUSHARE_TOKEN:
        return "Tushare 未配置：请设置 TUSHARE_TOKEN 环境变量"
    if not params:
        params = {}
    
    payload = {
        "api_name": method,
        "token": TUSHARE_TOKEN,
        "params": params,
    }
    
    try:
        data = json.dumps(payload, ensure_ascii=False).encode()
        req = urllib.request.Request(
            TUSHARE_API,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
        
        if resp.get("code") != 0:
            return f"Tushare 错误: {resp.get('msg', 'unknown')}"
        
        result = resp.get("data", {})
        items = result if isinstance(result, list) else result.get("items", [])
        fields = result.get("fields", []) if isinstance(result, dict) else []
        
        if not items:
            return f"Tushare {method}: 无数据"
        
        max_show = 10
        total = len(items)
        show_items = items[:max_show]
        
        lines = [f"Tushare {method} (最近 {min(total, max_show)}/{total} 条):"]
        for i, item in enumerate(show_items):
            if fields and isinstance(item, list):
                parts = [f"{fields[j]}={item[j]}" for j in range(min(len(fields), len(item))) if j < len(item)]
                lines.append(f"  {i+1}. {' '.join(parts[:8])}")
            elif isinstance(item, dict):
                parts = [f"{k}={v}" for k, v in list(item.items())[:6]]
                lines.append(f"  {i+1}. {' '.join(parts)}")
            else:
                lines.append(f"  {i+1}. {item}")
        if total > max_show:
            lines.append(f"  ... 还有 {total - max_show} 条")
        return "\n".join(lines)
    
    except urllib.error.HTTPError as e:
        return f"Tushare HTTP 错误: {e.code}"
    except Exception as e:
        return f"Tushare 调用失败: {e}"

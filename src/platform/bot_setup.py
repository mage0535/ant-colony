from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PLATFORM_SPECS: dict[str, dict[str, Any]] = {
    "wecom": {
        "env_keys": ("WECOM_BOT_ID", "WECOM_BOT_SECRET"),
        "labels": ("Bot ID", "Bot Secret"),
    },
    "feishu": {
        "env_keys": ("FEISHU_APP_ID", "FEISHU_APP_SECRET"),
        "labels": ("App ID", "App Secret"),
    },
    "dingtalk": {
        "env_keys": ("DINGTALK_CLIENT_ID", "DINGTALK_CLIENT_SECRET"),
        "labels": ("Client ID", "Client Secret"),
    },
    "wecom_callback": {
        "env_keys": ("WECOM_CORP_ID", "WECOM_SECRET"),
        "labels": ("Corp ID", "App Secret"),
    },
}

_WECOM_QR_GENERATE_URL = "https://work.weixin.qq.com/ai/qc/generate"
_WECOM_QR_QUERY_URL = "https://work.weixin.qq.com/ai/qc/query_result"
_WECOM_QR_CODE_PAGE = "https://work.weixin.qq.com/ai/qc/gen?source=ant-colony&scode="

_FEISHU_ACCOUNTS_URLS = {
    "feishu": "https://accounts.feishu.cn",
    "lark": "https://accounts.larksuite.com",
}
_FEISHU_OPEN_URLS = {
    "feishu": "https://open.feishu.cn",
    "lark": "https://open.larksuite.com",
}
_FEISHU_REGISTRATION_PATH = "/open-apis/authen/v1/index"

_DINGTALK_REGISTRATION_BASE_URL = "https://oapi.dingtalk.com"


def normalize_registration_result(platform: str, result: dict[str, Any]) -> dict[str, str]:
    platform = platform.strip().lower()
    if platform == "wecom":
        return {
            "WECOM_BOT_ID": str(result.get("bot_id") or result.get("botid") or "").strip(),
            "WECOM_BOT_SECRET": str(result.get("secret") or "").strip(),
        }
    if platform == "feishu":
        values = {
            "FEISHU_APP_ID": str(result.get("app_id") or result.get("client_id") or "").strip(),
            "FEISHU_APP_SECRET": str(result.get("app_secret") or result.get("client_secret") or "").strip(),
        }
        domain = str(result.get("domain") or "").strip()
        if domain:
            values["FEISHU_DOMAIN"] = domain
        return values
    if platform == "dingtalk":
        return {
            "DINGTALK_CLIENT_ID": str(result.get("client_id") or "").strip(),
            "DINGTALK_CLIENT_SECRET": str(result.get("client_secret") or "").strip(),
        }
    raise ValueError(f"Unsupported platform: {platform}")


def write_env_values(env_path: str | Path, values: dict[str, str]) -> None:
    path = Path(env_path)
    existing_lines = []
    existing_map: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            existing_lines.append(line)
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                existing_map[key.strip()] = value

    for key, value in values.items():
        if value:
            existing_map[key] = value

    seen: set[str] = set()
    output_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output_lines.append(line)
            continue
        key, _, _ = line.partition("=")
        key = key.strip()
        if key in existing_map:
            output_lines.append(f"{key}={existing_map[key]}")
            seen.add(key)
        else:
            output_lines.append(line)

    for key, value in existing_map.items():
        if key not in seen:
            output_lines.append(f"{key}={value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")


def render_qr_to_terminal(url: str) -> bool:
    try:
        import qrcode
    except ImportError:
        return False

    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=1, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    try:
        qr.print_ascii(invert=True)
        return True
    except UnicodeEncodeError:
        # Windows terminals sometimes still use GBK; fall back to UTF-8 stdout.
        import sys

        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
                qr.print_ascii(invert=True)
                return True
            except Exception:
                return False
        return False


def wecom_qr_scan_for_bot_info(timeout_seconds: int = 300) -> dict[str, str] | None:
    req = urllib.request.Request(f"{_WECOM_QR_GENERATE_URL}?source=ant-colony", headers={"User-Agent": "AntColony/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    data = raw.get("data") or {}
    scode = str(data.get("scode") or "").strip()
    auth_url = str(data.get("auth_url") or "").strip()
    if not scode or not auth_url:
        return None

    render_qr_to_terminal(auth_url)
    page_url = f"{_WECOM_QR_CODE_PAGE}{urllib.parse.quote(scode)}"
    print(f"\nScan the QR code above, or open this URL directly:\n{page_url}\n")

    deadline = time.monotonic() + timeout_seconds
    query_url = f"{_WECOM_QR_QUERY_URL}?scode={urllib.parse.quote(scode)}"
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(query_url, headers={"User-Agent": "AntColony/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except Exception:
            time.sleep(3)
            continue
        result_data = result.get("data") or {}
        if str(result_data.get("status") or "").lower() == "success":
            bot_info = result_data.get("bot_info") or {}
            bot_id = str(bot_info.get("botid") or bot_info.get("bot_id") or "").strip()
            secret = str(bot_info.get("secret") or "").strip()
            if bot_id and secret:
                return {"bot_id": bot_id, "secret": secret}
            return None
        time.sleep(3)
    return None


def feishu_qr_register(initial_domain: str = "feishu", timeout_seconds: int = 600) -> dict[str, str] | None:
    _feishu_init_registration(initial_domain)
    begin = _feishu_begin_registration(initial_domain)
    qr_url = begin["qr_url"]
    render_qr_to_terminal(qr_url)
    print(f"\nScan the QR code above, or open this URL directly:\n{qr_url}\n")
    result = _feishu_poll_registration(
        device_code=begin["device_code"],
        interval=begin["interval"],
        expire_in=min(begin["expire_in"], timeout_seconds),
        domain=initial_domain,
    )
    if not result:
        return None
    return result


def dingtalk_qr_register() -> dict[str, str] | None:
    reg = _dingtalk_begin_registration()
    url = reg["verification_uri_complete"]
    render_qr_to_terminal(url)
    print(f"\nScan the QR code above, or open this URL directly:\n{url}\n")
    return _dingtalk_wait_for_registration_success(
        reg["device_code"],
        interval=reg["interval"],
        expires_in=reg["expires_in"],
    )


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_form(url: str, body: dict[str, str]) -> dict[str, Any]:
    data = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _feishu_accounts_base_url(domain: str) -> str:
    return _FEISHU_ACCOUNTS_URLS.get(domain, _FEISHU_ACCOUNTS_URLS["feishu"])


def _feishu_init_registration(domain: str) -> None:
    url = f"{_feishu_accounts_base_url(domain)}{_FEISHU_REGISTRATION_PATH}"
    res = _post_form(url, {"action": "init"})
    methods = res.get("supported_auth_methods") or []
    if "client_secret" not in methods:
        raise RuntimeError(f"Feishu/Lark registration unsupported auth methods: {methods}")


def _feishu_begin_registration(domain: str) -> dict[str, Any]:
    url = f"{_feishu_accounts_base_url(domain)}{_FEISHU_REGISTRATION_PATH}"
    res = _post_form(
        url,
        {
            "action": "begin",
            "archetype": "PersonalAgent",
            "auth_method": "client_secret",
            "request_user_info": "open_id",
        },
    )
    return {
        "device_code": res["device_code"],
        "qr_url": res["verification_uri_complete"],
        "interval": int(res.get("interval") or 5),
        "expire_in": int(res.get("expire_in") or 600),
    }


def _feishu_poll_registration(device_code: str, interval: int, expire_in: int, domain: str) -> dict[str, str] | None:
    deadline = time.monotonic() + expire_in
    current_domain = domain
    while time.monotonic() < deadline:
        url = f"{_feishu_accounts_base_url(current_domain)}{_FEISHU_REGISTRATION_PATH}"
        try:
            res = _post_form(url, {"action": "poll", "device_code": device_code, "tp": "ob_app"})
        except Exception:
            time.sleep(interval)
            continue
        user_info = res.get("user_info") or {}
        if user_info.get("tenant_brand") == "lark":
            current_domain = "lark"
        if res.get("client_id") and res.get("client_secret"):
            return {
                "app_id": str(res["client_id"]),
                "app_secret": str(res["client_secret"]),
                "domain": current_domain,
            }
        if str(res.get("error") or "") in {"access_denied", "expired_token"}:
            return None
        time.sleep(interval)
    return None


def _dingtalk_api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_DINGTALK_REGISTRATION_BASE_URL}{path}"
    res = _post_json(url, payload)
    if int(res.get("errcode", -1)) != 0:
        raise RuntimeError(f"DingTalk API error: {res}")
    return res


def _dingtalk_begin_registration() -> dict[str, Any]:
    init_data = _dingtalk_api_post("/app/registration/init", {"source": "ant-colony"})
    nonce = str(init_data.get("nonce") or "").strip()
    begin_data = _dingtalk_api_post("/app/registration/begin", {"nonce": nonce})
    return {
        "device_code": str(begin_data["device_code"]),
        "verification_uri_complete": str(begin_data["verification_uri_complete"]),
        "expires_in": int(begin_data.get("expires_in") or 7200),
        "interval": max(int(begin_data.get("interval") or 3), 2),
    }


def _dingtalk_wait_for_registration_success(device_code: str, interval: int, expires_in: int) -> dict[str, str] | None:
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            res = _dingtalk_api_post("/app/registration/poll", {"device_code": device_code})
        except Exception:
            continue
        status = str(res.get("status") or "").upper()
        if status == "SUCCESS":
            client_id = str(res.get("client_id") or "").strip()
            client_secret = str(res.get("client_secret") or "").strip()
            if client_id and client_secret:
                return {"client_id": client_id, "client_secret": client_secret}
            return None
        if status in {"FAIL", "EXPIRED"}:
            return None
    return None

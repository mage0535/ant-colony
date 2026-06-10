from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"

def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    # Try known locations for env file
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "infra", ".env.wecom"),
        os.path.expanduser("~/ant-colony-probe/infra/.env.wecom"),
        "/home/codexcheck/ant-colony-probe/infra/.env.wecom",
    ]
    for env_file in candidates:
        if os.path.isfile(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()
            break
    # Fallback to os.environ
    for k in ("WECOM_CORP_ID", "WECOM_SECRET", "WECOM_CALLBACK_TOKEN", "WECOM_CALLBACK_AES_KEY"):
        if k not in env:
            val = os.environ.get(k, "")
            if val:
                env[k] = val
    return env

_ENV = _load_env()

def _get_token() -> str:
    corpid = _ENV.get("WECOM_CORP_ID", "")
    secret = _ENV.get("WECOM_CONTACT_SECRET", "") or _ENV.get("WECOM_SECRET", "")
    url = f"{WECOM_API}/gettoken?corpid={corpid}&corpsecret={secret}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"WeCom token error: {data.get('errmsg')}")
    return data["access_token"]


class OrgSynchronizer:
    """Sync WeChat Work department and member structure.
    
    Fetches org data from WeCom API and stores it in the space registry
    and sidecar memory for each user.
    """

    def __init__(self, space_registry: Any = None, memory_dir: str = "./data/memory") -> None:
        self._space_registry = space_registry
        self._memory_dir = memory_dir
        self._token: str | None = None

    @property
    def token(self) -> str:
        if self._token is None:
            self._token = _get_token()
        return self._token

    def fetch_departments(self, parent_id: int = 1) -> list[dict[str, Any]]:
        try:
            url = f"{WECOM_API}/department/list?access_token={self.token}"
            with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
                data = json.loads(resp.read())
            if data.get("errcode", 0) != 0:
                return []
            return data.get("department", [])
        except Exception:
            return []

    def fetch_users(self, department_id: int = 1, fetch_child: bool = True) -> list[dict[str, Any]]:
        try:
            url = f"{WECOM_API}/user/list_id?access_token={self.token}&department_id={department_id}"
            with urllib.request.urlopen(urllib.request.Request(url, data=b'{}', headers={"Content-Type":"application/json"}, method="POST"), timeout=15) as resp:
                data = json.loads(resp.read())
            if data.get("errcode", 0) != 0:
                return []
            return data.get("dept_user", data.get("userid_list", []))
        except Exception:
            return []

    def sync_all(self) -> dict[str, Any]:
        try:
            depts = self.fetch_departments()
            users = self.fetch_users()
        except Exception as e:
            logger.exception("Org sync failed")
            return {"error": str(e), "departments": 0, "users": 0}

        # Register departments from user data if API failed
        collected_depts: set[str] = set()
        if not depts and users:
            for u in users:
                if isinstance(u, dict):
                    dept_id = u.get("department", 0)
                    if dept_id:
                        if isinstance(dept_id, list):
                            for d in dept_id:
                                collected_depts.add(f"dept-{d}")
                        else:
                            collected_depts.add(f"dept-{dept_id}")

        if self._space_registry:
            for d_id in collected_depts:
                self._space_registry.register(d_id, name=d_id, space_type="department")
            for d in depts:
                dept_name = d.get("name", str(d.get("id", "")))
                dept_id = f"dept-{d.get('id')}"
                self._space_registry.register(dept_id, name=dept_name, space_type="department")

        # Write sidecar memory for each user
        os.makedirs(self._memory_dir, exist_ok=True)
        for u in users:
            if isinstance(u, dict):
                user_id = u.get("userid", "")
                dept_ids = u.get("department", 0)
                if isinstance(dept_ids, int):
                    dept_ids = [str(dept_ids)]
                else:
                    dept_ids = [str(d) for d in (dept_ids or [])]
            else:
                user_id = str(u)
                dept_ids = []
            if not user_id:
                continue
            mem = {
                "role": "",
                "department": ", ".join(dept_ids),
                "name": user_id,
                "responsibilities": [],
            }
            path = os.path.join(self._memory_dir, f"agent_{user_id}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(mem, f, ensure_ascii=False, indent=2)
            logger.debug("Sidecar memory written for %s", user_id)

        logger.info("Org sync: %d departments, %d users", len(depts), len(users))
        return {"departments": len(depts), "users": len(users)}

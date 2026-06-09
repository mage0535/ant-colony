"""Cloud Drive Manager — cloud storage integration with ACL-based access control.

Three-tier scope model:
  organization — visible to all, managed by admin + company leader
  department   — visible to dept members, managed by admin + dept leader
  project      — visible to project members, managed by admin + project member

Each cloud drive registration specifies its scope, and access is checked
against the user's role via ACL.

Uses rclone as the sync backend (optional; falls back gracefully when not installed).

Integration with Knowledge Base:
  sync_from_cloud(drive_id, path) → document_converter → gbrain_repo.save()
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime
from typing import Any

from src.knowledge.acl import resolve_role, Role

logger = logging.getLogger(__name__)

# Supported cloud drive types (from KMM cloud sync)
DRIVER_TYPES = {
    "onedrive":     {"name": "OneDrive",       "auth": "oauth"},
    "googledrive":  {"name": "Google Drive",   "auth": "oauth"},
    "aliyundrive":  {"name": "阿里云盘",         "auth": "token"},
    "baidu":        {"name": "百度云盘",         "auth": "oauth"},
    "dropbox":      {"name": "Dropbox",        "auth": "oauth"},
    "mega":         {"name": "Mega",           "auth": "password"},
    "jianguo":      {"name": "坚果云",           "auth": "password"},
    "nextcloud":    {"name": "Nextcloud",      "auth": "password"},
    "icloud":       {"name": "iCloud",         "auth": "oauth+2fa"},
    "tianyi":       {"name": "天翼云盘",         "auth": "password"},
    "p115":         {"name": "115 网盘",        "auth": "cookie"},
    "quark":        {"name": "夸克网盘",         "auth": "token"},
}

SCOPE_CONFIG = {
    "organization": {"min_role": Role.leader, "label": "公司"},
    "department":   {"min_role": Role.leader, "label": "部门"},
    "project":      {"min_role": Role.admin,  "label": "项目"},
}

# Default sync base directory
SYNC_BASE = os.environ.get("CLOUD_SYNC_DIR", "./data/cloud_sync")

_init_done = False


def _ensure_table():
    global _init_done
    if _init_done:
        return
    from src.store.database import Database
    conn = Database.get().connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cloud_drives (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            driver_type TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}',
            scope TEXT NOT NULL DEFAULT 'organization',
            scope_id TEXT NOT NULL DEFAULT '*',
            rclone_remote TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL DEFAULT (cast(strftime('%s','now') as real)),
            updated_at REAL NOT NULL DEFAULT (cast(strftime('%s','now') as real)),
            last_sync_at REAL DEFAULT 0
        )
    """)
    conn.commit()
    _init_done = True


def _query(sql: str, params: tuple = ()) -> list[dict]:
    _ensure_table()
    from src.store.database import Database
    """Query the cloud_drives table, returning rows as dicts."""
    from src.store.database import Database
    db = Database.get()
    conn = db.connect()
    conn.row_factory = _dict_factory
    rows = conn.execute(sql, params).fetchall()
    return rows


def _execute(sql: str, params: tuple = ()) -> None:
    """Execute a write statement."""
    from src.store.database import Database
    db = Database.get()
    conn = db.connect()
    conn.execute(sql, params)
    conn.commit()


def _dict_factory(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def _rclone_available() -> bool:
    try:
        subprocess.run(["rclone", "version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def register_drive(
    name: str,
    driver_type: str,
    config: dict[str, Any],
    scope: str = "organization",
    scope_id: str = "*",
    rclone_remote: str = "",
    user_id: str = "",
) -> str:
    """Register a cloud drive. ACL-checked against user role + scope."""
    role = resolve_role(user_id)
    scope_req = SCOPE_CONFIG.get(scope, SCOPE_CONFIG["organization"])
    if role < scope_req["min_role"]:
        raise PermissionError(
            f"权限不足: 添加 {scope_req['label']} 级云盘需要 {scope_req['min_role'].name} 角色"
        )

    if driver_type not in DRIVER_TYPES:
        raise ValueError(f"不支持的云盘类型: {driver_type}，可选: {', '.join(DRIVER_TYPES.keys())}")

    drive_id = f"cd-{uuid.uuid4().hex[:12]}"
    _execute(
        "INSERT INTO cloud_drives (id, name, driver_type, config_json, scope, scope_id, rclone_remote, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (drive_id, name, driver_type, json.dumps(config), scope, scope_id, rclone_remote, user_id),
    )
    logger.info("Cloud drive registered: %s (%s, scope=%s, by=%s)", name, driver_type, scope, user_id)
    return drive_id


def list_drives(scope: str = "", user_id: str = "") -> str:
    rows = _query("SELECT * FROM cloud_drives ORDER BY created_at DESC")

    results = []
    for r in rows:
        d = dict(r)
        d["config_json"] = json.loads(d.get("config_json", "{}"))
        name = d.get("name", "")
        dtype = DRIVER_TYPES.get(d.get("driver_type", ""), {}).get("name", d["driver_type"])
        scope_label = SCOPE_CONFIG.get(d["scope"], {}).get("label", d["scope"])
        last_sync = d.get("last_sync_at", 0)
        sync_str = datetime.fromtimestamp(last_sync).strftime("%Y-%m-%d %H:%M") if last_sync else "从未同步"
        results.append(f"{name} ({dtype}) [{scope_label}] 最近同步: {sync_str}")

    if not results:
        return "未配置云盘（需管理员/负责人添加）"
    return "已配置云盘:\n" + "\n".join(results)


def sync_from_cloud(drive_id: str, remote_path: str, local_path: str = "", user_id: str = "") -> str:
    rows = _query("SELECT * FROM cloud_drives WHERE id = ?", (drive_id,))
    if not rows:
        return f"云盘 {drive_id} 不存在"
    drive = rows[0]

    role = resolve_role(user_id)
    if role < Role.member:
        return "权限不足: 需要至少 project member 角色"

    rclone_remote = drive.get("rclone_remote", "") or drive["name"]
    target_dir = local_path or os.path.join(SYNC_BASE, drive["id"], os.path.basename(remote_path or ""))
    os.makedirs(target_dir, exist_ok=True)

    if _rclone_available():
        try:
            result = subprocess.run(
                ["rclone", "copy", f"{rclone_remote}:{remote_path}", target_dir, "--progress"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                return f"同步失败: {result.stderr[:200]}"
        except subprocess.TimeoutExpired:
            return "同步超时（>5分钟）"
        except Exception as e:
            return f"同步失败: {e}"
    else:
        return f"rclone 未安装，无法执行同步。已创建目标目录: {target_dir}（手动放入文件后可使用 search_knowledge 搜索）"

    # Index synced files into gbrain knowledge base
    from src.knowledge.gbrain_repo import GbrainKnowledgeRepository
    from src.knowledge.collector import KnowledgeCollector
    import os as _os

    repo = GbrainKnowledgeRepository()
    collector = KnowledgeCollector(repo)
    indexed = 0
    for fname in _os.listdir(target_dir):
        fpath = _os.path.join(target_dir, fname)
        if _os.path.isfile(fpath):
            try:
                entry = collector.collect_file(
                    fpath, owner_type=drive["scope"], owner_id=drive.get("scope_id", "*"),
                    tags=[drive["scope"], drive["name"], "cloud_sync"],
                )
                if entry:
                    indexed += 1
            except Exception as e:
                logger.warning("Failed to index %s: %s", fname, e)

    # Update last_sync timestamp
    _execute("UPDATE cloud_drives SET last_sync_at = ? WHERE id = ?", (time.time(), drive_id))

    return f"从 {drive['name']} 同步完成，已索引 {indexed} 个文件到知识库（归属: {drive['scope']}）"


def delete_drive(drive_id: str, user_id: str = "") -> bool:
    """Delete a cloud drive registration. Admin only."""
    role = resolve_role(user_id)
    if role < Role.admin:
        raise PermissionError("仅管理员可删除云盘配置")
    # Check exists
    existing = _query("SELECT id FROM cloud_drives WHERE id = ?", (drive_id,))
    if not existing:
        return False
    _execute("DELETE FROM cloud_drives WHERE id = ?", (drive_id,))
    return True

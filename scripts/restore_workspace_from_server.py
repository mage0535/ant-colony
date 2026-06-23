from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import paramiko


DEFAULT_PATHS = [
    "docs",
    "tests",
    "src/agents",
    "src/config",
    "src/engine",
    "src/gateway",
    "src/guard",
    "src/knowledge",
    "src/models",
    "src/orchestrator",
    "src/platform",
    "src/store",
    "src/tools",
    "src/web",
]


def iter_restore_paths(paths: list[str] | None) -> list[str]:
    values = [p.strip().replace("\\", "/") for p in (paths or DEFAULT_PATHS) if p.strip()]
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def restore_path(sftp: "paramiko.SFTPClient", remote_root: str, local_root: Path, rel_path: str) -> int:
    restored = 0

    def walk(remote_dir: str, local_dir: Path) -> None:
        nonlocal restored
        local_dir.mkdir(parents=True, exist_ok=True)
        for entry in sftp.listdir_attr(remote_dir):
            rpath = f"{remote_dir}/{entry.filename}"
            lpath = local_dir / entry.filename
            if entry.st_mode & 0o40000:
                walk(rpath, lpath)
            else:
                sftp.get(rpath, str(lpath))
                restored += 1
                print(f"restored {lpath}")

    remote_path = f"{remote_root}/{rel_path}"
    local_path = local_root / rel_path
    walk(remote_path, local_path)
    return restored


def main() -> int:
    import paramiko

    parser = argparse.ArgumentParser(description="Restore local workspace paths from the synced server copy.")
    parser.add_argument("--host", default="")
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--remote-root", default="/opt/ant-colony")
    parser.add_argument("--local-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--paths", nargs="*", help="Relative paths to restore. Defaults to critical source/docs/tests roots.")
    args = parser.parse_args()

    if not args.host or not args.user or not args.password:
        raise SystemExit("Missing required connection arguments. Please provide --host --user --password explicitly.")

    local_root = Path(args.local_root)
    restore_paths = iter_restore_paths(args.paths)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=args.host, username=args.user, password=args.password, timeout=20)
    try:
        sftp = client.open_sftp()
        try:
            restored = 0
            for rel in restore_paths:
                restored += restore_path(sftp, args.remote_root, local_root, rel)
            print(f"TOTAL_RESTORED {restored}")
        finally:
            sftp.close()
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

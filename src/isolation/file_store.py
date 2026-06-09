from __future__ import annotations

import os
import shutil
from datetime import datetime


class PathSanitizer:
    def __init__(self, base_dir: str) -> None:
        self._base = os.path.realpath(base_dir)

    def sanitize(self, path: str) -> str:
        if ".." in path:
            raise ValueError(f"Path traversal blocked: {path!r}")
        joined = os.path.realpath(os.path.join(self._base, path))
        base_real = os.path.realpath(self._base)
        if os.path.commonpath([base_real, joined]) != base_real:
            raise ValueError(f"Path traversal blocked: {path!r}")
        return joined


class IsolatedFileStore:
    def __init__(self, base_dir: str) -> None:
        self._base = base_dir
        self._sanitizer = PathSanitizer(base_dir)

    def _validate_component(self, value: str, name: str) -> None:
        if not value:
            raise ValueError(f"{name} must not be empty")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} contains invalid characters: {value!r}")

    def _file_path(self, user_id: str, space_id: str, filename: str) -> str:
        self._validate_component(space_id, "space_id")
        self._validate_component(user_id, "user_id")
        return self._sanitizer.sanitize(os.path.join(space_id, user_id, filename))

    def _space_dir(self, space_id: str) -> str:
        self._validate_component(space_id, "space_id")
        return self._sanitizer.sanitize(space_id)

    def _user_dir(self, user_id: str, space_id: str) -> str:
        self._validate_component(space_id, "space_id")
        self._validate_component(user_id, "user_id")
        return self._sanitizer.sanitize(os.path.join(space_id, user_id))

    def write(self, user_id: str, space_id: str, filename: str, content: bytes) -> str:
        full_path = self._file_path(user_id, space_id, filename)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(content)
        return os.path.relpath(full_path, self._base)

    def read(self, user_id: str, space_id: str, filename: str) -> bytes:
        full_path = self._file_path(user_id, space_id, filename)
        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"File not found: {filename!r}")
        with open(full_path, "rb") as f:
            return f.read()

    def list_files(self, space_id: str) -> list[dict]:
        space_dir = self._space_dir(space_id)
        if not os.path.isdir(space_dir):
            return []
        results: list[dict] = []
        for user_dirname in os.listdir(space_dir):
            user_path = os.path.join(space_dir, user_dirname)
            if not os.path.isdir(user_path):
                continue
            for fname in os.listdir(user_path):
                fpath = os.path.join(user_path, fname)
                if not os.path.isfile(fpath):
                    continue
                st = os.stat(fpath)
                results.append({
                    "filename": fname,
                    "user_id": user_dirname,
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                })
        return sorted(results, key=lambda r: (r["user_id"], r["filename"]))

    def list_user_files(self, user_id: str, space_id: str) -> list[dict]:
        user_dir = self._user_dir(user_id, space_id)
        if not os.path.isdir(user_dir):
            return []
        results: list[dict] = []
        for fname in os.listdir(user_dir):
            fpath = os.path.join(user_dir, fname)
            if not os.path.isfile(fpath):
                continue
            st = os.stat(fpath)
            results.append({
                "filename": fname,
                "user_id": user_id,
                "size": st.st_size,
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
            })
        return sorted(results, key=lambda r: r["filename"])

    def delete(self, user_id: str, space_id: str, filename: str) -> bool:
        full_path = self._file_path(user_id, space_id, filename)
        if not os.path.isfile(full_path):
            return False
        os.remove(full_path)
        return True

    def disk_usage(self) -> shutil._ntuple_diskusage:
        return shutil.disk_usage(self._base)

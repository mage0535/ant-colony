from __future__ import annotations

import argparse
import sys
from pathlib import Path


DEFAULT_PATHS = (
    Path("src/gateway/entry_links.py"),
    Path("tests/test_entry_link_commands.py"),
    Path("tests/test_inbound_entry_links.py"),
)

MOJIBAKE_MARKERS = (
    "\ufffd",
    "鐭",
    "绠",
    "鎵",
    "鍚",
    "鍙",
    "寮",
    "杩",
    "鏂",
    "涓",
    "鑿",
    "甯",
    "浼",
    "閽",
    "椋",
)


def find_mojibake(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.exists():
            findings.append(f"{path}: missing file")
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            marker = next((item for item in MOJIBAKE_MARKERS if item in line), None)
            if marker is not None:
                snippet = line.strip()
                if len(snippet) > 160:
                    snippet = f"{snippet[:157]}..."
                findings.append(f"{path}:{line_number}: contains mojibake marker {marker!r}: {snippet}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check critical user-visible Chinese text for mojibake.")
    parser.add_argument("paths", nargs="*", help="Optional files to scan. Defaults to critical bot entry files.")
    args = parser.parse_args(argv)

    paths = [Path(item) for item in args.paths] if args.paths else list(DEFAULT_PATHS)
    findings = find_mojibake(paths)
    if findings:
        print("用户可见中文文本检查失败：发现疑似乱码。")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print(f"用户可见中文文本检查通过：{len(paths)} 个关键文件未发现疑似乱码。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

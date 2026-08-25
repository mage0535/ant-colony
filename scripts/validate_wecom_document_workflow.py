from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from scripts.validate_wecom_message_flow import pick_probe_user
from src.gateway.wecom_file_handler import prepare_template_candidate
from src.tools.document_generation_service import generate_document


def _default_template_path() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        repo_root / "src" / "data" / "documents" / "测试标题.docx",
        repo_root / "src" / "data" / "documents" / "测试报告.docx",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    raise FileNotFoundError("no built-in template candidate found")


def validate_document_workflow() -> dict[str, Any]:
    target_user = pick_probe_user()
    if not target_user:
        return {"configured": False, "reason": "no probe target user found"}

    template_source = _default_template_path()
    with tempfile.TemporaryDirectory(prefix="wecom-doc-workflow-") as td:
        work_template = Path(td) / Path(template_source).name
        shutil.copyfile(template_source, work_template)
        template_meta = prepare_template_candidate(str(work_template), work_template.name, target_user)
        result = generate_document(
            {
                "title": "企微文档工作流验证",
                "content": "企微文档工作流验证",
                "from": target_user,
                "format": "docx",
                "_context_text": (
                    "=== 【模板文件内容】===\n企业内部沟通管理办法模板\n\n"
                    "=== 【用户要求】===\n请生成一份《企微文档工作流验证》，"
                    "内容包含目的、适用范围、处理流程、验证结论四部分。"
                ),
                "_template_path": template_meta.get("template_path", ""),
            }
        )

    return {
        "configured": True,
        "target_user": target_user,
        "template_path": template_meta.get("template_path", ""),
        "pushed": result == "",
        "result": result,
    }


def document_workflow_ok(report: dict[str, Any]) -> bool:
    return bool(report.get("configured") and report.get("pushed"))


def main() -> int:
    report = validate_document_workflow()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if document_workflow_ok(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())

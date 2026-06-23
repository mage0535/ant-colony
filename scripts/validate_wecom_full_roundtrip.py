from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from scripts.validate_wecom_message_flow import pick_probe_user
from src.gateway.dispatcher import Dispatcher
from src.gateway.inbound_service import InboundGatewayService
from src.gateway.wecom_outbound import send_file, send_file_card, upload_file
from src.orchestrator.batch_processor import BatchProcessor


def validate_full_roundtrip() -> dict[str, Any]:
    target_user = pick_probe_user()
    if not target_user:
        return {"configured": False, "reason": "no probe target user found"}

    repo_root = Path(__file__).resolve().parents[1]
    template_source = repo_root / "src" / "data" / "documents" / "测试标题.docx"
    if not template_source.is_file():
        return {"configured": False, "reason": f"template not found: {template_source}"}

    media_id = upload_file(str(template_source))
    if not media_id:
        return {"configured": True, "target_user": target_user, "uploaded": False, "reason": "media upload failed"}

    service = InboundGatewayService(dispatcher=Dispatcher(), batch_processor=BatchProcessor())
    service._conversations = type("Convos", (), {"get": lambda self, _: type("C", (), {"add": lambda *a, **k: None, "get_context": lambda *a, **k: ""})(), "save_all": lambda *a, **k: None})()
    service.get_or_create_agent = lambda *_args, **_kwargs: None  # generation path bypasses it

    file_result = service.handle_wecom_payload(
        {
            "from_user_id": target_user,
            "msg_type": "file",
            "media_id": media_id,
            "content": template_source.name,
            "is_direct": True,
            "provider": "wecom_bot",
            "transport": "roundtrip_probe",
        }
    )
    text_result = service.handle_wecom_payload(
        {
            "from_user_id": target_user,
            "msg_type": "text",
            "content": "请根据模板生成《企微完整回推验证》，包含目的、范围、流程、结论四部分。",
            "is_direct": True,
            "provider": "wecom_bot",
            "transport": "roundtrip_probe",
        }
    )

    pushed = False
    metadata: dict[str, Any] = {}
    reply_text = text_result.response.text if text_result.response else ""
    if reply_text.startswith("[BOT_FILE]"):
        metadata = json.loads(reply_text[len("[BOT_FILE]"):])
        pushed = send_file_card(target_user, metadata["filename"], metadata["download_url"])
        if pushed:
            send_file(target_user, metadata["path"])

    return {
        "configured": True,
        "target_user": target_user,
        "uploaded": bool(media_id),
        "file_ack": file_result.response.text if file_result.response else "",
        "bot_file": bool(metadata),
        "pushed": pushed,
        "filename": metadata.get("filename", ""),
    }


def main() -> int:
    print(json.dumps(validate_full_roundtrip(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

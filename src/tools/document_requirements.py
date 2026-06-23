from __future__ import annotations

import re
from typing import Any


SECTION_NUMERALS = "一二三四五六七八九十"
GENERIC_MARKER_RE = re.compile(r"^===.*?===\s*$", re.MULTILINE)


def split_template_and_request(content: str) -> tuple[str, str]:
    markers = list(GENERIC_MARKER_RE.finditer(content))
    if len(markers) >= 2:
        template_text = content[markers[0].end() : markers[1].start()]
        request_text = content[markers[1].end() :]
        return template_text.strip(), request_text.strip()

    parts = content.strip().split("\n\n")
    template_text = "\n\n".join(parts[:-1]) if len(parts) > 1 else content
    request_text = parts[-1] if len(parts) > 1 else ""
    return template_text.strip(), request_text.strip()


def build_template_excerpt(template_text: str, max_chars: int = 1200) -> str:
    lines: list[str] = []
    total = 0
    for raw in template_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("---"):
            continue
        lines.append(line)
        total += len(line)
        if total >= max_chars:
            break
    excerpt = "\n".join(lines).strip()
    return excerpt[:max_chars]


def build_template_prompt_block(template_path: str | None, fallback_template_text: str) -> str:
    from src.tools.document_tool import extract_docx_template_outline

    template_excerpt = build_template_excerpt(fallback_template_text)
    if not template_path:
        return template_excerpt[:2500]

    try:
        outline = extract_docx_template_outline(template_path)
        lines = ["模板结构摘要："]
        for para in outline.get("paragraphs", [])[:40]:
            text = str(para.get("text", "")).strip()
            if not text:
                continue
            style = str(para.get("style", "")).strip() or "Normal"
            lines.append(f"- [{style}] {text[:80]}")
        for idx, table in enumerate(outline.get("tables", [])[:5], start=1):
            first_row = table.get("cells", [[]])[0] if table.get("cells") else []
            lines.append(
                f"- [TABLE {idx}] {table.get('rows', 0)}x{table.get('cols', 0)} "
                f"header={first_row}"
            )
        if template_excerpt:
            lines.extend(["", "Template excerpt:", template_excerpt])
        block = "\n".join(lines).strip()
        return block[:2500] if block else template_excerpt[:2500]
    except Exception:
        return template_excerpt[:2500]


def normalize_request_lines(request_text: str) -> list[str]:
    lines: list[str] = []
    for raw in request_text.splitlines():
        line = raw.strip().strip("；;，,。")
        if line:
            lines.append(line)
    return lines


def strip_policy_marker(text: str) -> str:
    stripped = text.strip()
    patterns = [
        r"^[一二三四五六七八九十]+[、.\uff0e]?\s*",
        r"^\d+[、.\uff0e]?\s*",
        r"^[a-zA-Z][、.\uff0e]?\s*",
        r"^[（(]\d+[)）]\s*",
        r"^[（(][a-zA-Z][)）]\s*",
    ]
    for pattern in patterns:
        updated = re.sub(pattern, "", stripped, count=1)
        if updated != stripped:
            stripped = updated.strip()
            break
    return stripped


def is_policy_primary_item(line: str) -> bool:
    return bool(re.match(r"^\d+[、.\uff0e]?\s*\S+", line.strip()))


def is_policy_sub_item(line: str) -> bool:
    stripped = line.strip()
    return bool(
        re.match(r"^[a-zA-Z][、.\uff0e]?\s*\S+", stripped)
        or re.match(r"^[（(][a-zA-Z0-9][)）]\s*\S+", stripped)
    )


def is_policy_section_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^[一二三四五六七八九十]+[、.\uff0e]?\s*\S+", stripped):
        return True
    if is_policy_primary_item(stripped) or is_policy_sub_item(stripped):
        return False
    return (" " not in stripped) and (len(stripped) <= 40)


def canonical_policy_section_heading(section_title: str) -> str:
    title = strip_policy_marker(section_title)
    if "通行" in title:
        return "车间通行管理要求"
    if "通讯" in title or "通信" in title or "对讲机" in title:
        return "车间通讯管理要求"
    if title in {"补充要求", "其他要求"}:
        return "补充管理要求"
    return title if title.endswith("要求") else f"{title}管理要求"


def build_requirement_spec(title: str, template_text: str, request_text: str) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None
    current_item: dict[str, Any] | None = None
    has_attachment_hint = False

    def ensure_section(raw_title: str) -> dict[str, Any]:
        nonlocal current_section
        clean_title = strip_policy_marker(raw_title) or "补充要求"
        if clean_title == raw_title and raw_title[:1] in SECTION_NUMERALS:
            clean_title = raw_title[1:].strip() or clean_title
        if current_section and current_section["raw_title"] == clean_title:
            return current_section
        current_section = {
            "raw_title": clean_title,
            "heading": canonical_policy_section_heading(clean_title),
            "items": [],
        }
        sections.append(current_section)
        return current_section

    def commit_item() -> None:
        nonlocal current_item, has_attachment_hint
        if not current_item or not current_section:
            current_item = None
            return
        current_item["main"] = current_item["main"].strip("；;，,。 ")
        current_item["sub_items"] = [
            item.strip("；;，,。 ")
            for item in current_item["sub_items"]
            if item.strip("；;，,。 ")
        ]
        item_texts = [current_item["main"], *current_item["sub_items"]]
        current_item["attachment_hint"] = any(("后附" in item or "附件" in item) for item in item_texts)
        has_attachment_hint = has_attachment_hint or current_item["attachment_hint"]
        current_section["items"].append(current_item)
        current_item = None

    ensure_section("补充要求")
    for line in normalize_request_lines(request_text):
        if line.startswith(("我需要你", "请你", "帮我", "你来")):
            continue
        section_heading = is_policy_section_heading(line) or (
            current_item is not None
            and not is_policy_primary_item(line)
            and not is_policy_sub_item(line)
            and (" " not in line)
            and (len(line) <= 40)
        )
        if section_heading:
            commit_item()
            ensure_section(line)
            continue
        if is_policy_primary_item(line):
            commit_item()
            ensure_section(current_section["raw_title"] if current_section else "补充要求")
            current_item = {"main": strip_policy_marker(line), "sub_items": []}
            continue
        if is_policy_sub_item(line):
            ensure_section(current_section["raw_title"] if current_section else "补充要求")
            if current_item is None:
                current_item = {"main": "", "sub_items": []}
            current_item["sub_items"].append(strip_policy_marker(line))
            continue
        ensure_section(current_section["raw_title"] if current_section else "补充要求")
        clean_line = strip_policy_marker(line)
        if current_item is None:
            current_item = {"main": clean_line, "sub_items": []}
        elif current_item["sub_items"]:
            current_item["sub_items"][-1] = f"{current_item['sub_items'][-1]}；{clean_line}"
        else:
            current_item["main"] = f"{current_item['main']}；{clean_line}".strip("；")

    commit_item()
    sections = [section for section in sections if section["items"]]
    return {
        "title": title.strip() or "文档",
        "template_excerpt": build_template_excerpt(template_text),
        "sections": sections,
        "has_attachment_hint": has_attachment_hint,
    }


def formalize_policy_item(section_title: str, item: str) -> str:
    text = strip_policy_marker(item.strip().lstrip("-").strip())
    if not text:
        return ""
    if text.endswith("。"):
        return text
    if "；其中，" in text:
        return f"{text}，相关部门应结合岗位分工细化执行措施，并纳入日常检查和责任追溯范围。"
    if "通行" in section_title:
        return f"{text}，相关责任人员应严格按照指定通道、权限范围和现场秩序要求组织实施，不得擅自变更或规避。"
    if "通讯" in section_title or "通信" in section_title:
        return f"{text}，各相关人员应按照本规定落实日常管理、保管维护和使用要求，确保现场沟通安全、及时、可控。"
    if "后附" in text or "附件" in text:
        return f"{text}，相关清单、台账或附属说明应作为本规定附件同步发布并保持版本和内容一致。"
    return f"{text}，并纳入本规定统一执行。"


def formalize_policy_spec_item(section_title: str, item: dict[str, Any]) -> str:
    text = item.get("main", "").strip()
    sub_items = [part.strip() for part in item.get("sub_items", []) if str(part).strip()]
    if sub_items:
        text = f"{text}；其中，" + "；".join(sub_items)
    return formalize_policy_item(section_title, text)


def build_policy_fallback_content(title: str, request_text: str) -> str:
    spec = build_requirement_spec(title, "", request_text)
    if not spec["sections"]:
        spec["sections"] = [
            {
                "raw_title": "补充要求",
                "heading": "补充管理要求",
                "items": [{"main": request_text.strip(), "sub_items": [], "attachment_hint": False}],
            }
        ]

    parts = [
        title,
        "1目的",
        f"为规范{title.replace('规定', '').replace('制度', '').strip()}相关管理要求，明确执行标准、责任边界和监督要求，保障现场管理有序、安全、可追溯，特制定本规定。",
        "2适用范围",
        "本规定适用于涉及车间通行、作业区域出入、车间内通讯工具使用以及相关协同管理的全部人员，包括办公室人员、车间现场人员及外来人员。",
        "3管理原则",
        "坚持安全第一、权限明确、流程统一、责任到人、违规必究的原则，确保各项要求在实际管理中可执行、可检查、可追责。",
    ]

    chapter_no = 4
    for section in spec["sections"]:
        section_title = section["raw_title"]
        heading = section["heading"]
        parts.append(f"{chapter_no}{heading}")
        item_no = 1
        for item in section["items"]:
            clean_item = item.get("main", "").strip()
            parts.append(f"{chapter_no}.{item_no} {clean_item}")
            formal = formalize_policy_spec_item(section_title, item)
            if formal:
                parts.append(formal)
            item_no += 1
        chapter_no += 1

    parts.extend(
        [
            f"{chapter_no}监督与处罚",
            f"{chapter_no}.1 各部门负责人应对本规定执行情况进行日常监督检查，发现问题应及时纠正并形成记录。",
            f"{chapter_no}.2 对违反本规定、造成管理风险、安全隐患或越权通行、违规通讯等行为的人员，公司将依据情节轻重予以通报、考核或纪律处理；涉及共同责任的，对相关责任人员一并追责。",
            f"{chapter_no + 1}附则",
            f"{chapter_no + 1}.1 本规定由公司相关管理部门负责解释，并根据实际执行情况适时修订完善。",
            f"{chapter_no + 1}.2 各部门对讲机频道清单等附属信息可作为本规定附件，与正文具有同等管理效力。",
        ]
    )
    return "\n\n".join(parts)


def build_notice_fallback_content(title: str, request_text: str) -> str:
    body = request_text.strip() or "请有关部门按要求执行。"
    parts = [
        title,
        "各部门：",
        body,
        "请各部门结合实际立即组织落实，并在规定时限内反馈执行结果。执行过程中如有问题，及时向管理部门报告。",
        "特此通知。",
    ]
    return "\n\n".join(parts)


def build_memo_fallback_content(title: str, request_text: str) -> str:
    body = request_text.strip() or "请结合实际补充备忘事项。"
    parts = [
        title,
        "一、事项背景",
        "为便于后续跟进和执行留痕，现将本次事项的背景、当前情况和后续安排整理如下。",
        "二、当前情况",
        body,
        "三、后续安排",
        "请相关责任部门根据备忘内容持续跟进，明确责任人、完成时限和反馈节点，并在下一周期内同步整改及落实进展。",
        "四、备注",
        "本备忘录用于内部协同、过程跟踪和事项复盘，后续如有新增情况应及时补充更新。",
    ]
    return "\n\n".join(parts)


def infer_document_family(title: str, request_text: str) -> str:
    joined = f"{title}\n{request_text}"
    if any(keyword in joined for keyword in ("备忘录", "纪要", "备忘")):
        return "memo"
    if any(keyword in joined for keyword in ("通知", "通告", "公告")):
        return "notice"
    return "policy"


def build_fallback_content(title: str, request_text: str, family: str | None = None) -> str:
    resolved_family = family or infer_document_family(title, request_text)
    if resolved_family == "memo":
        return build_memo_fallback_content(title, request_text)
    if resolved_family == "notice":
        return build_notice_fallback_content(title, request_text)
    return build_policy_fallback_content(title, request_text)

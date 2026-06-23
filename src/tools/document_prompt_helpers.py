from __future__ import annotations

from typing import Any


def split_template_and_request_helper(content: str) -> tuple[str, str]:
    from src.tools.document_requirements import split_template_and_request

    return split_template_and_request(content)


def build_template_excerpt_helper(template_text: str, max_chars: int = 1200) -> str:
    from src.tools.document_requirements import build_template_excerpt

    return build_template_excerpt(template_text, max_chars=max_chars)


def build_template_prompt_block_helper(template_path: str | None, fallback_template_text: str) -> str:
    from src.tools.document_requirements import build_template_prompt_block

    return build_template_prompt_block(template_path, fallback_template_text)


def normalize_request_lines_helper(request_text: str) -> list[str]:
    from src.tools.document_requirements import normalize_request_lines

    return normalize_request_lines(request_text)


def strip_policy_marker_helper(text: str) -> str:
    from src.tools.document_requirements import strip_policy_marker

    return strip_policy_marker(text)


def is_policy_section_heading_helper(line: str) -> bool:
    from src.tools.document_requirements import is_policy_section_heading

    return is_policy_section_heading(line)


def is_policy_primary_item_helper(line: str) -> bool:
    from src.tools.document_requirements import is_policy_primary_item

    return is_policy_primary_item(line)


def is_policy_sub_item_helper(line: str) -> bool:
    from src.tools.document_requirements import is_policy_sub_item

    return is_policy_sub_item(line)


def canonical_policy_section_heading_helper(section_title: str) -> str:
    from src.tools.document_requirements import canonical_policy_section_heading

    return canonical_policy_section_heading(section_title)


def build_requirement_spec_helper(title: str, template_text: str, request_text: str) -> dict[str, Any]:
    from src.tools.document_requirements import build_requirement_spec

    return build_requirement_spec(title, template_text, request_text)


def formalize_policy_item_helper(section_title: str, item: str) -> str:
    from src.tools.document_requirements import formalize_policy_item

    return formalize_policy_item(section_title, item)


def formalize_policy_spec_item_helper(section_title: str, item: dict[str, Any]) -> str:
    from src.tools.document_requirements import formalize_policy_spec_item

    return formalize_policy_spec_item(section_title, item)


def build_policy_fallback_content_helper(title: str, request_text: str) -> str:
    from src.tools.document_requirements import build_policy_fallback_content

    return build_policy_fallback_content(title, request_text)

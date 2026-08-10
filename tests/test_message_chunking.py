from __future__ import annotations


def _restore_numbered_chunks(chunks: list[str]) -> str:
    return "".join(chunk.split("\n", 1)[-1] for chunk in chunks)


def test_split_text_for_im_keeps_short_text_single_chunk() -> None:
    from src.gateway.message_chunking import split_text_for_im

    chunks = split_text_for_im("hello", hard_limit=4000, soft_limit=1200)

    assert chunks == ["hello"]


def test_split_text_for_im_adds_page_numbers_for_all_long_text_chunks() -> None:
    from src.gateway.message_chunking import split_text_for_im

    text = ("第一段内容。" * 300) + "\n\n" + ("第二段内容。" * 300)
    chunks = split_text_for_im(text, hard_limit=4000, soft_limit=1200)

    assert len(chunks) >= 2
    assert chunks[0].startswith("（1/")
    assert chunks[1].startswith("（2/")
    assert "第二段内容。" in _restore_numbered_chunks(chunks)


def test_split_text_for_im_respects_utf8_byte_limit_for_chinese_text() -> None:
    from src.gateway.message_chunking import split_text_for_im

    text = "企业 AI 助手已开通。" * 300
    chunks = split_text_for_im(text, hard_limit=2048, soft_limit=1200)

    assert len(chunks) >= 2
    assert _restore_numbered_chunks(chunks) == text
    assert all(len(chunk.encode("utf-8")) <= 2048 for chunk in chunks)

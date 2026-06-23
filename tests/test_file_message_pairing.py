from __future__ import annotations

import unittest


class TestFileMessagePairingService(unittest.TestCase):
    def test_build_combined_content_includes_template_and_request_sections(self) -> None:
        from src.gateway.file_message_pairing import build_combined_file_message_content

        result = build_combined_file_message_content(
            "用户发送了文件：模板.docx\n\n以下是文件内容：\n---\n第一章 总则\n---",
            "请根据这个模板生成正式制度",
        )

        self.assertIn("【系统提示】", result)
        self.assertIn("=== 【模板文件内容】===", result)
        self.assertIn("=== 【用户要求】===", result)
        self.assertIn("第一章 总则", result)
        self.assertIn("请根据这个模板生成正式制度", result)

    def test_should_buffer_text_detects_file_referential_prompt(self) -> None:
        from src.gateway.file_message_pairing import should_buffer_text_for_file_pairing

        self.assertTrue(should_buffer_text_for_file_pairing("分析这个文档并优化内容"))
        self.assertTrue(should_buffer_text_for_file_pairing("按这个模板生成制度"))
        self.assertFalse(should_buffer_text_for_file_pairing("今天天气怎么样"))

    def test_should_generate_document_requires_generation_and_document_tokens(self) -> None:
        from src.gateway.file_message_pairing import (
            looks_document_generation_request,
            should_generate_document_from_content,
        )

        self.assertTrue(
            should_generate_document_from_content(
                "用户发送了文件：模板.docx\n\n我需要你帮我生成一个车间通行管理规定"
            )
        )
        self.assertTrue(looks_document_generation_request("我需要你帮我生成一个车间通行管理规定"))
        self.assertFalse(
            should_generate_document_from_content(
                "用户发送了文件：模板.docx\n\n请分析这个文档并提炼重点"
            )
        )

    def test_infer_document_title_extracts_specific_document_name(self) -> None:
        from src.gateway.file_message_pairing import infer_document_title

        title = infer_document_title("我需要你帮我生成一个车间通行和通讯管理规定，按模板输出")

        self.assertEqual(title, "车间通行和通讯管理规定")

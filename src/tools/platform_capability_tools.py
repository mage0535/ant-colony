from __future__ import annotations


def _context_from_args(args: dict[str, str]) -> dict[str, str | dict]:
    user_id = str(args.get("user_id") or args.get("from") or "")
    platform = str(args.get("_source_provider", "") or args.get("platform", ""))
    transport = str(args.get("_source_transport", "") or args.get("transport", ""))
    scope = str(args.get("scope", ""))
    scope_id = str(args.get("scope_id", ""))
    source_chat_id = str(args.get("source_chat_id", ""))
    return {
        "user_id": user_id,
        "platform": platform,
        "transport": transport,
        "scope": scope,
        "scope_id": scope_id,
        "source_chat_id": source_chat_id,
        "metadata": {},
    }


def merge_pdfs_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    paths = [part.strip() for part in str(args.get("paths", "")).split(",") if part.strip()]
    output = str(args.get("output", "merged.pdf"))
    return invoke_capability_first(
        "files.pdf.merge",
        paths,
        output,
        context=_context_from_args(args),
        empty_message="暂无可用 PDF 合并能力",
    )


def split_pdf_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.pdf.split",
        str(args.get("path", "")),
        str(args.get("pages", "")),
        str(args.get("output", "split.pdf")),
        context=_context_from_args(args),
        empty_message="暂无可用 PDF 拆分能力",
    )


def compress_pdf_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.pdf.compress",
        str(args.get("path", "")),
        str(args.get("output", "compressed.pdf")),
        context=_context_from_args(args),
        empty_message="暂无可用 PDF 压缩能力",
    )


def protect_pdf_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.pdf.protect",
        str(args.get("path", "")),
        str(args.get("password", "")),
        str(args.get("output", "protected.pdf")),
        context=_context_from_args(args),
        empty_message="暂无可用 PDF 加密能力",
    )


def read_pdf_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.pdf.read",
        str(args.get("path", "")),
        context=_context_from_args(args),
        empty_message="暂无可用 PDF 读取能力",
    )


def extract_pdf_images_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.pdf.extract_images",
        str(args.get("path", "")),
        str(args.get("output_dir", "pdf_images")),
        context=_context_from_args(args),
        empty_message="暂无可用 PDF 图片提取能力",
    )


def watermark_pdf_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.pdf.watermark",
        str(args.get("path", "")),
        str(args.get("watermark", "")),
        str(args.get("output", "watermarked.pdf")),
        context=_context_from_args(args),
        empty_message="暂无可用 PDF 水印能力",
    )


def pdf_service_status_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability

    return invoke_capability(
        "files.pdf.service_status",
        context=_context_from_args(args),
        empty_message="暂无可用 PDF 服务状态信息",
    )


def ocr_pdf_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.pdf.ocr",
        str(args.get("path", "")),
        str(args.get("output", "ocr.pdf")),
        str(args.get("language", "chi_sim+eng")),
        context=_context_from_args(args),
        empty_message="暂无可用 PDF OCR 能力",
    )


def office_service_status_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability

    return invoke_capability(
        "files.office.service_status",
        context=_context_from_args(args),
        empty_message="暂无可用 Office 文档服务状态信息",
    )


def docx_template_outline_tool(args: dict[str, str]):
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.docx.template_outline",
        str(args.get("path", "")),
        context=_context_from_args(args),
        empty_message={},
    )


def xlsx_template_outline_tool(args: dict[str, str]):
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.xlsx.template_outline",
        str(args.get("path", "")),
        context=_context_from_args(args),
        empty_message={},
    )


def pptx_template_outline_tool(args: dict[str, str]):
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.pptx.template_outline",
        str(args.get("path", "")),
        context=_context_from_args(args),
        empty_message={},
    )


def read_docx_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.docx.read",
        str(args.get("path", "")),
        context=_context_from_args(args),
        empty_message="暂无可用 DOCX 读取能力",
    )


def read_xlsx_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.xlsx.read",
        str(args.get("path", "")),
        context=_context_from_args(args),
        empty_message="暂无可用 XLSX 读取能力",
    )


def read_pptx_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "files.pptx.read",
        str(args.get("path", "")),
        context=_context_from_args(args),
        empty_message="暂无可用 PPTX 读取能力",
    )


def doc_search_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability
    from src.tools.knowledge_tools import search_knowledge_tool

    query = str(args.get("query", ""))
    if not query:
        return "请提供搜索关键词"
    knowledge_result = search_knowledge_tool({"query": query, "user_id": args.get("user_id", "")})
    if knowledge_result and not knowledge_result.startswith("未找到关于"):
        return knowledge_result
    doc_result = invoke_capability("docs.search", query, context=_context_from_args(args), empty_message="")
    if not doc_result:
        return f"本地知识库和企业在线文档中都未找到与“{query}”匹配的内容"
    if "HTTP Error 404" in doc_result or "Not Found" in doc_result:
        return (
            f"本地知识库中未找到与“{query}”匹配的内容；"
            "当前企业微信在线文档搜索接口不可用或未开放给当前应用，请先将文档导入本地知识库后再搜索。"
        )
    return doc_result


def read_docs_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first
    from src.tools.knowledge_tools import search_knowledge_tool

    query = str(args.get("query", ""))
    if not query:
        return "请提供文档名称或关键词"
    knowledge_result = search_knowledge_tool({"query": query, "user_id": args.get("user_id", "")})
    if knowledge_result and not knowledge_result.startswith("未找到关于"):
        return knowledge_result
    result = invoke_capability_first("docs.read", query, context=_context_from_args(args), empty_message="")
    if not result:
        return f"本地知识库和企业在线文档中都未找到与“{query}”匹配的内容"
    if "HTTP Error 404" in result or "Not Found" in result:
        return (
            f"本地知识库中未找到与“{query}”匹配的内容；"
            "当前企业微信在线文档读取能力不可用或权限不足，请先将文档导入本地知识库。"
        )
    return result


def approval_detail_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    query = str(args.get("query", "") or args.get("status", "pending"))
    return invoke_capability_first("approval.detail", query, context=_context_from_args(args), empty_message="未找到审批详情")


def drive_search_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability

    query = str(args.get("query", ""))
    if not query:
        return "请提供网盘搜索关键词"
    return invoke_capability("drive.search", query, context=_context_from_args(args), empty_message="未找到匹配的网盘文件（待接入企业网盘能力）")


def read_drive_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    query = str(args.get("query", ""))
    if not query:
        return "请提供网盘文件名称或关键词"
    return invoke_capability_first("drive.read", query, context=_context_from_args(args), empty_message="未找到可读取的网盘文件内容")


def meeting_detail_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    query = str(args.get("query", ""))
    return invoke_capability_first("meeting.get", query, context=_context_from_args(args), empty_message="未找到会议信息详情")


def calendar_detail_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    query = str(args.get("query", ""))
    return invoke_capability_first("calendar.detail", query, context=_context_from_args(args), empty_message="未找到日程详情")


def mail_summary_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability

    result = invoke_capability("mail.summary", str(args.get("query", "")), context=_context_from_args(args), empty_message="暂无可用邮箱能力（待接入企业邮箱能力）")
    normalized = result.lower()
    if "email not configured" in normalized or "missing env var" in normalized:
        return "当前企业 IM 账号尚未配置邮箱未读统计。请管理员优先在后台为当前员工配置邮箱接收协议、服务器、账号和授权码；其他员工的邮箱配置不会共享。"
    return result


def list_capabilities_tool(args: dict[str, str]) -> str:
    del args
    from src.platform import list_capabilities

    return list_capabilities()


def approval_list_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability

    return invoke_capability("approval.list", str(args.get("status", "pending")), context=_context_from_args(args), empty_message="无待审批事项或当前平台审批权限未开放")


def enterprise_app_query_tool(args: dict[str, str]) -> str:
    from src.platform.enterprise_query_service import execute_enterprise_query

    query = str(
        args.get("query", "")
        or args.get("_context_text", "")
        or args.get("content", "")
        or args.get("text", "")
    )
    if not query:
        return "请提供要查询的企业应用、流程、会议室、审批或第三方系统问题"
    return execute_enterprise_query(query, _context_from_args(args)) or "未查询到企业应用数据，或当前 AI 助手尚未获得对应应用权限"


def enterprise_app_action_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    action = str(args.get("action", ""))
    if not action:
        return "请提供要执行的企业应用动作，例如 meeting.create 或 calendar.create"
    payload = {
        key: value
        for key, value in args.items()
        if key not in {"action", "user_id", "_source_provider", "_source_transport", "platform", "transport"}
    }
    return invoke_capability_first("apps.action", action, payload, context=_context_from_args(args), empty_message="当前企业应用动作无法执行，可能是权限不足或动作暂未接入")


def calendar_create_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability

    summary = str(args.get("summary", ""))
    start = str(args.get("start", ""))
    end = str(args.get("end", ""))
    if not summary or not start or not end:
        return "请提供日程标题、开始时间和结束时间"
    return invoke_capability("calendar.create", summary, start, end, context=_context_from_args(args), empty_message="创建日程失败（需配置飞书/钉钉/企微凭证）")


def create_doc_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    title = str(args.get("title", ""))
    if not title:
        return "请提供文档标题"
    result = invoke_capability_first("docs.create", title, str(args.get("content", "")), context=_context_from_args(args), empty_message="需配置企业微信凭证")
    return result or "文档创建成功"


def smartpage_create_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    title = str(args.get("title", ""))
    if not title:
        return "请提供智能文档标题"
    return invoke_capability_first(
        "docs.smartpage.create",
        title,
        str(args.get("content", "")),
        context=_context_from_args(args),
        empty_message="企业微信智能文档 MCP 尚未配置或不可用",
    )


def edit_doc_content_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    doc_id = str(args.get("doc_id", "") or args.get("document_id", ""))
    content = str(args.get("content", ""))
    if not doc_id or not content:
        return "请提供文档 ID 和要写入的内容"
    return invoke_capability_first(
        "docs.edit",
        doc_id,
        content,
        context=_context_from_args(args),
        empty_message="企业微信文档编辑 MCP 尚未配置或不可用",
    )


def sheet_append_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    doc_id = str(args.get("doc_id", "") or args.get("document_id", ""))
    values = args.get("values", "") or args.get("data", "")
    if not doc_id or not values:
        return "请提供表格文档 ID 和要追加的数据"
    return invoke_capability_first(
        "sheet.append",
        doc_id,
        values,
        context=_context_from_args(args),
        empty_message="企业微信表格 MCP 尚未配置或不可用",
    )


def todo_create_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    title = str(args.get("title", "") or args.get("content", ""))
    if not title:
        return "请提供待办主题"
    return invoke_capability_first(
        "todo.create",
        title,
        str(args.get("due_time", "") or args.get("deadline", "")),
        str(args.get("participants", "") or args.get("userids", "")),
        context=_context_from_args(args),
        empty_message="企业微信待办 MCP 尚未配置或不可用",
    )


def todo_list_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "todo.list",
        str(args.get("query", "")),
        context=_context_from_args(args),
        empty_message="未查询到待办，或企业微信待办 MCP 尚未配置",
    )


def todo_update_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    todo_id = str(args.get("todo_id", "") or args.get("id", ""))
    if not todo_id:
        return "请提供待办 ID"
    return invoke_capability_first(
        "todo.update",
        todo_id,
        str(args.get("title", "") or args.get("content", "")),
        str(args.get("status", "")),
        str(args.get("due_time", "") or args.get("deadline", "")),
        context=_context_from_args(args),
        empty_message="企业微信待办更新 MCP 尚未配置或不可用",
    )


def todo_user_search_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability_first

    query = str(args.get("query", "") or args.get("name", ""))
    if not query:
        return "请提供要搜索的成员姓名或别名"
    return invoke_capability_first(
        "todo.user.search",
        query,
        context=_context_from_args(args),
        empty_message="未找到成员，或企业微信待办成员搜索 MCP 尚未配置",
    )


def list_meetings_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability

    return invoke_capability("meeting.list", context=_context_from_args(args), empty_message="未找到会议信息（需配置企微/钉钉凭证）")


def create_meeting_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability

    title = str(args.get("title", ""))
    start = str(args.get("start", ""))
    end = str(args.get("end", ""))
    attendees = str(args.get("attendees", ""))
    if not title or not start or not end:
        return "请提供会议标题、开始时间和结束时间"
    attendee_list = [part.strip() for part in attendees.split(",") if part.strip()] if attendees else []
    return invoke_capability("meeting.create", title, start, end, attendee_list, context=_context_from_args(args), empty_message="创建会议失败（需配置企微凭证）")


def who_is_admin_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability

    results = invoke_capability("org.admins", context=_context_from_args(args), empty_message="未配置平台管理员信息")
    return results


def who_is_leader_tool(args: dict[str, str]) -> str:
    from src.platform import invoke_capability

    return invoke_capability("org.leaders", context=_context_from_args(args), empty_message="未查询到部门负责人信息（需配置企微凭证）")

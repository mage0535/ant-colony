# 项目交接状态 — 2026-06-10

## 当前状态
- 项目已完成全部功能开发 + 扩展，进入维护运营阶段
- Dashboard 已完全移除，全部功能通过聊天前端（企微/飞书/钉钉/Telegram）操作
- 6 个 systemd 服务运行中（gateway/callback/dashboard-api/cron/gbrain/hindsight）
- >60 个内置 Agent 工具
- 252 个 AI 专家角色

## 已完成的重大变更

### 架构层
1. **仪表盘移除** — 全部改为聊天命令
2. **知识库存储迁移** — SQLite FTS5 → gbrain/PostgreSQL
3. **三平台消息适配器** — 飞书/钉钉/Telegram
4. **三平台 API 客户端** — 零依赖，urllib 实现
5. **插件架构** — Tier 1/2/3 分层 + 自动发现

### 权限体系
6. **知识库 ACL 分级** — admin/leader/member/self 四层角色
7. **平台管理员 vs 部门负责人分离** — who_is_admin / who_is_leader 独立查询
8. **管理员管理** — 企微通过聊天添加（add_admin/remove_admin），飞书钉钉自动识别

### 功能扩展
9. **215 个 AI 专家角色** — 来自 agency-agents-zh，自动匹配
10. **GStack 方法论** — YC Office Hours/Review/Investigate/Spec/Retro
11. **12+ 云盘同步** — ACL 分级，自动索引到知识库
12. **邮件/PDF 工具** — 发送邮件、PDF 操作
13. **DuckDuckGo 搜索** — 搜索链第三级降级
14. **OCR 引擎升级** — pymupdf + marker-pdf 多级降级

## 已知 Bug：企微文件推送（send_file）

### 现象
`src/gateway/wecom_outbound.py` 中的 `send_file()` 调用 WeCom `message/send` API（`msgtype=file`）后：
- API 返回 `errcode=0`（成功）
- 日志显示 `File sent to MaGe via WeCom`
- **但用户收不到文件** — 企微聊天窗口中没有任何文件消息

而 `send_text()` 使用同一个 API 同一个 `agentid`，`msgtype=text`，正常投递到聊天窗口。

### 调用链路

```
用户发消息 → callback(:18091) 接收 → POST / → gateway(:18090) 
→ inbound_service → PersonalAgent → engine → LLM
→ LLM 返回 <tool_call>builtin:generate_document(...)>
→ _execute_tool_calls → _dispatch_tool → _generate_report_handler
→ generate_report() 存盘到 data/documents/
→ send_file(user_id, filepath)  → upload_file() → 拿到 media_id
→ message/send API (msgtype=file) → errcode=0 → 日志成功
→ 但用户未收到
```

### 尝试过的方法

| 尝试 | 文件 | 结果 |
|------|------|------|
| 原始 `send_file` — `msgtype=file`，无额外参数 | `wecom_outbound.py:122` | API 成功，用户收不到 |
| 加 `safe=0`, `enable_duplicate_check=0` | `wecom_outbound.py:136-137` | 同上 |
| 改用 `msgtype=textcard` 带下载按钮 | `wecom_outbound.py:149-172` | 投递成功（用户可见卡片） |
| 通过 callback 同步响应返回 file XML | 未实现（见下文分析） | — |

### 根因分析（推测）

**最可能的根因**：企微 `message/send` API 的 `msgtype=file` 对 自建应用（非第三方应用）的行为不一致。

具体来说，企微的会话回调流程：
1. 用户向企微 App 发消息 → 企微 POST 到我们的回调服务器（:18091）
2. 回调服务器必须在 **5 秒内** 返回加密 XML 响应
3. 该响应如果是 `MsgType=file` + `MediaId` = 企微在聊天窗口显示文件
4. 如果响应是纯文本（如 "success"），企微显示原消息（用户看到自己的消息被"回显"）

目前回调服务器的设计（`wecom_callback_server.py:129-131`）：
```python
self._respond_text(200, "success")  # 立即返回
t = threading.Thread(target=self._forward_and_reply, args=(msg_dict,), daemon=True)
t.start()  # 后台异步处理
```

即**先同步返回 "success"，再在后台异步转发给 Gateway**。Gateway 的处理包括 LLM 调用（5～10s），远超企微 5s 超时，所以无法同步等待。

后台线程中，`_forward_and_reply` 拿到 Gateway 回复文本后，调用 `send_text(user_id, reply)` — 这走的是 `message/send` API，不是 callback 响应。`send_text` 的 `msgtype=text` 投递正常。

**同理**：如果后台线程调 `send_file`（`msgtype=file`），走的也是 `message/send` API，不是 callback 响应。企微对同一个 API 的 `msgtype=file` 似乎不投递到聊天窗口（但 text 会）。

### 当前方案

已改用 `send_file_card(user_id, filename, download_url)` — 发送 `msgtype=textcard` 带下载按钮。企微确认投递到聊天窗口，用户点击"下载文档"按钮 → 内置浏览器 → 下载文件。

**代码**：
- `wecom_outbound.py:149-172` — `send_file_card()` 新函数
- `builtin.py:_generate_report_handler` — 优先调 `send_file_card`，其次 `send_file` 做兜底

### 如果后续想继续修 `msgtype=file`

需理解并解决的方案（按复杂度排序）：

**方案 A：callback 同步返回 file XML**
- 不改异步架构，而是：Gateway 返回的文件 media_id 存储下来 → Gateway 额外推送一条 "已生成文件" 的消息 → 回调服务器拿到后来一次再次调用 callback API 推送文件
- 问题：企微 callback 是 WeCom → Server 单向推送，Server 不能主动发起

**方案 B：改为同步处理 + 短超时**
- Gateway 内部设定 4 秒 timeout，4 秒内 LLM 未返回则 fallback 到 "正在生成..."
- 如果 LLM 提前返回且有文件 media_id，同步构造 file XML 响应
- 问题：LLM 调用通常 5-10s，4 秒 cutoff 大概率触发 fallback

**方案 C：使用企微"应用推送"的另一个接口**
- 尝试 `cgi-bin/externalcontact/message/send`（外部联系人消息）
- 尝试 `cgi-bin/corp_group/corp/...`（企业群机器人）
- 尝试上传到"素材管理"（`media/upload` 用 `type=attachment`）后通过素材消息发送

**方案 D：开放下载 URL + 前端逻辑**
- 当前 textcard 方案已经是这个思路的成熟版

### 其他修复记录

#### 1. JSON 参数解析崩溃
`_lenient_parse_args()` 在 `base.py:61-84`，当 Agent 的 `<tool_call>` 中 JSON 含特殊字符时降级为正则提取。

## 已知 Bug 2：文档内容未参照模板生成

### 现象
用户向企微发送 .docx 模板文件 + 文字要求（如"生成车间通行管理规定"）后，Agent 生成的文档只有简单排版/格式化，没有参照模板的章节结构、标题层级、编号格式来展开和充实内容。

### 完整流程

```
用户 → 发模板 docx + 文字
  → WeCom 回调服务器 → 下载 docx → 提取纯文本（格式丢失）
  → 文字转发 → 合并文件文本 + 用户文字 → Agent
  → Agent 生成 <tool_call>generate_document(content=...)>
  → _generate_report_handler:
      1. content 太短 → 用 _context_text（合并后的原始文本）替补
      2. 调用 Zen API 丰富内容
      3. generate_report() → OfficeCLI 生成 docx
      4. send_file_card() 投递
  → 用户收到 docx，但内容没按模板走
```

### 尝试过的方法

| 尝试 | 代码 | 结果 |
|------|------|------|
| 原始提示词："生成一份格式规范、结构完整的正式文档，如果内容中提到了格式要求或模板参考，请严格遵守" | 旧版 `builtin.py` | LLM 只做格式化排版，不做内容充实 |
| 丰富提示词改为 5 条指令：继承模板层级 / 展开占位符 / 保留编号 / 正式语言 / 输出完整正文 | `builtin.py:926-935` | 仍然不理想，LLM 将模板和用户要求混为一谈 |
| 提示词分为 `【模板】` + `【要求】` 双块 | `builtin.py:927-948` | 最新版，待充分验证。理论上让 LLM 区分模板结构和用户指令 |
| `max_tokens` 4096 → 16384, timeout 60s → 120s | `builtin.py:939-940` | 允许长文档完整生成 |
| 丰富阈值从 `len(enriched) > original` 改为 `>= 20` | `builtin.py:943` | 只要 API 返回有意义结果就采用 |

### 根因分析

**根本原因**：docx 模板在下载后被提取为纯文本，**所有格式信息丢失**（字号/加粗/表格/页眉页脚/样式等）。`python-docx` 提取的文本只有基础段落内容，没有层级关系。LLM 收到的是：

```
第一章 总则
第一条 为了...
第二章 具体规定
...
```

LLM 无法从纯文本中重建模板的视觉格式。而且旧版提示词把所有文本混在一起，没有区分"这是模板你要继承"和"这是用户你要响应"。

### 当前方案

1. **提示词双块结构** — `【模板】`（需继承的章节框架）和 `【要求】`（用户具体指令），用 `\n\n` 分割启发式区分
2. **提取原文直接作为 content** — 当 Agent 的 content 太短时，从对话历史取出完整用户消息（含文件内容）作为 document content
3. **OfficeCLI 直接按章节写 docx** — `_build_docx()` 将内容按 `\n\n` 分段，首段 Heading1、短行 Heading2

### 后续攻坚方向

1. **使用模板 docx 作为基底**（推荐）
   - 不提取文本重新生成，而是保留模板 .docx 文件
   - 用 OfficeCLI 的 `set` / `add` 在模板基础上修改特定占位符
   - 需要解决：如何识别模板中的占位符（`{title}`, `{{content}}` 等）
   - 或者：用 `python-docx` 直接操作模板的段落替换

2. **提取模板的结构化大纲**
   - 用 `python-docx` 提取精确的层级结构（Heading 1/2/3, numbered lists, tables）
   - 作为结构模板传给 LLM→LLM 按此结构生成内容→OfficeCLI 按此结构写 docx

3. **OfficeCLI 样式复制**
   - 用 OfficeCLI 读取模板的样式定义 → 应用到新文档的对应段落
   - 需要探索 OfficeCLI 是否支持跨文档样式复制

#### 3. 文件消息空回复
`webhook_server.py:114-117` 增加 `and result.response.text` 检查，避免文件消息的空 `AgentResponse(text="")` 被当做回复发送到企微。

#### 4. Tool call 中 from 字段为空
`base.py:209-210` 在 `_execute_tool_calls` 中自动注入 `_latest_user_id`，确保 `generate_document` 的 `from` 参数始终有值。

#### 5. 丰富阈值过高
`builtin.py:943` 从 `len(enriched) > len(original)` 改为 `len(enriched.strip()) >= 20`，只要 API 返回有意义内容就采用。

## 当前阻塞
- **WeCom send_file 不可靠**：`message/send` API 的 `msgtype=file` 返回成功但用户收不到。**
  当前使用 textcard（带下载按钮）作为替代方案**，文件托管在网关 HTTP 端口（:18092/api/v1/documents/）。
  如需真正的文件推送，需进一步研究企微协议（见上述方案分析）。
- **文档内容未参照模板生成**：docx 模板提取为纯文本后格式丢失，LLM 丰富阶段无法恢复章节结构/标题层级。**
  当前使用提示词双块结构（`【模板】` + `【要求】`）作为替代方案**，后续最佳方案是用模板 docx 作为操作基底（见 Bug 2 分析）。

## 下一步建议（按优先级）
1. ⭐ **解决文档模板参照问题** — 最佳方向：保留模板 docx 文件，用 OfficeCLI 在模板基础上修改占位符，而非从文本重新生成（见 Bug 2 后续攻坚方向 1）
2. ⭐ 解决 WeCom `msgtype=file` 不投递问题（根因分析见 Bug 1）
3. 为飞书/钉钉/Telegram 在 systemd 中配置 env 凭证并测试
4. 完善企微文档/日程/会议的 API 端点测试（部分端点返回 404）
5. 为具体业务场景添加审批模板匹配
6. 编写第三方插件开发文档
7. 压力测试 — 多用户并发场景

## 环境配置清单
- Gateway service 已添加 `EnvironmentFile=/home/[test-user]/ant-colony-probe/infra/.env.wecom`
- 管理员识别：企微需在 `.env.wecom` 配置凭据，通过聊天命令动态添加
- 知识库存储：gbrain-bridge (PostgreSQL) 端口 8787
- Python 包：PyMuPDF, python-docx, python-pptx, openpyxl 已安装

## 关键文件索引

| 文件 | 说明 |
|------|------|
| `src/gateway/wecom_outbound.py` | 企微推送：send_text / send_file / send_file_card |
| `src/gateway/wecom_callback_server.py` | 回调接收：异步 `_forward_and_reply` |
| `src/gateway/webhook_server.py` | 网关 HTTP：路由 + 回复构建 |
| `src/gateway/inbound_service.py` | 入站处理：文件缓冲 + 消息合并 |
| `src/gateway/wecom_file_handler.py` | 文件下载 + docx/PDF/图片文本提取 |
| `src/engine/base.py` | 引擎核心：`_execute_tool_calls` / `_lenient_parse_args` / 系统提示词 |
| `src/tools/builtin.py` | 工具注册：`_generate_report_handler` 丰富 + 推送 |
| `src/tools/document_tool.py` | OfficeCLI 文档生成：`_build_docx` / `_build_xlsx` / `_build_pptx` |
| `src/agents/personal_agent.py` | 个人 Agent：设置 `_latest_user_id` |


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

#### 2. 文档内容未按模板生成
`builtin.py:_generate_report_handler` 丰富阶段提示词分为 `【模板】` 和 `【要求】` 双块，避免 LLM 混为一谈只做格式化。

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

## 下一步建议（按优先级）
1. ⭐ 解决 WeCom `msgtype=file` 不投递问题（根因分析见上）
2. 为飞书/钉钉/Telegram 在 systemd 中配置 env 凭证并测试
3. 完善企微文档/日程/会议的 API 端点测试（部分端点返回 404）
4. 为具体业务场景添加审批模板匹配
5. 编写第三方插件开发文档
6. 压力测试 — 多用户并发场景

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
| `src/engine/base.py` | 引擎核心：`_execute_tool_calls` / `_lenient_parse_args` |
| `src/tools/builtin.py` | 工具注册：`_generate_report_handler` 丰富 + 推送 |
| `src/tools/document_tool.py` | OfficeCLI 文档生成 |


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

## 2026-06-11 补充分析（Codex）

### 对 Bug 1 的复核结论：现象已确认，根因仍需与企微协议继续对齐

- 代码现状与记录一致：
  - `src/gateway/wecom_callback_server.py:127-132` 先同步返回 `success`，再异步线程调用 Gateway
  - `src/gateway/wecom_outbound.py:122-145` 的 `send_file()` 走 `message/send` + `msgtype=file`
  - `src/gateway/wecom_outbound.py:151-177` 的 `send_file_card()` 走 `message/send` + `msgtype=textcard`
- 当前可以确定的是：
  - 现网架构下不可能通过 callback 同步回包直接返回 file XML
  - 异步 `message/send` 的文本消息可达，文件消息在当前环境下不可见
- 当前**不能完全确定**的是：
  - 是否为企微平台对自建应用 `msgtype=file` 的固有限制
  - 还是当前请求参数/媒体类型/可见范围/接口使用方式存在遗漏
- 额外观察：
  - `src/tools/builtin.py:977-980` 中 `send_file_card()` 成功后仍会继续调用一次 `send_file()`
  - 这不会影响 textcard 兜底，但会制造噪音日志和额外 API 调用，增加排障干扰

### 对 Bug 2 的复核结论：这不是单纯 prompt 问题，而是链路前半段已丢模板结构

- `src/knowledge/document_converter.py:252-263`
  - 对 `.docx` 只提取 `doc.paragraphs` 纯文本
  - 标题样式、编号格式、表格、页眉页脚、签字栏等模板信息全部丢失
- `src/gateway/wecom_file_handler.py:73-81`
  - 只向后续流程提供前 5000 字预览
  - 长模板存在被截断的风险
- `src/tools/builtin.py:926-943`
  - 目前靠“按空行切块，最后一块当要求，其余当模板”的启发式拆分
  - 容易把正文误判为用户要求，稳定性不足
- `src/tools/document_tool.py:44-79`
  - 生成时是新建空白 docx，再用首段 `Heading1`、短段 `Heading2` 的启发式补样式
  - 这决定了即便 LLM 理解了模板，也无法忠实还原原模板结构

### 建议优先级（供讨论）

1. 优先推进 Bug 2，而不是继续重投入 Bug 1
   - Bug 2 是确定性的架构缺陷，收益和确定性都更高
   - Bug 1 当前已有 `textcard + 下载链接` 可工作的业务替代方案
2. Bug 2 推荐方向：保留模板 docx 本体，而不是“抽纯文本后重建”
   - 理想链路：上传模板 → 保存原文件 → 提取结构化大纲/占位符 → 在模板基底上填充
   - 不建议继续主要依赖 prompt 强化来“猜回”模板结构
3. Bug 1 短期建议先收敛，不强行改 5 秒同步架构
   - 保留 `textcard` 作为正式兜底方案
   - 给 `send_file()` 补更完整的响应日志，便于继续核对企微协议
   - 若 `send_file_card()` 已成功，则不再追加调用 `send_file()`
4. 补测试
   - 当前缺少 `wecom_outbound`、`wecom_file_handler`、模板文档生成链路的专门测试
   - 后续讨论若形成方案，建议先补回归测试再动主链路

### Bug 2 讨论稿

- 已补充独立方案文档：`docs/bug2-template-document-plan.md`
- 该文档将 Bug 2 拆为：
  - 最小可行版：保留模板 + 提取结构化大纲 + 按大纲生成
  - 稳妥版：区分“可填充模板”和“结构模板”
  - 完整版：以原始模板 docx 作为实例化基底
- 当前建议的团队推进顺序：
  1. 先做最小可行版
  2. 再补模板分类
  3. 最后只对高价值模板做完整版

## 2026-06-11 补充回复（opencode 复核）

### 对 Codex 分析的总体评价

Codex 比前一轮追溯更深一层——不仅确认了症状，还精确定位了**格式信息在链路前半段已经丢失**的具体代码点（`document_converter.py`、`wecom_file_handler.py`、`document_tool.py`）。这三个发现是关键性的，之前未被充分重视。整体判断完全正确：**继续在 prompt 上死磕是低杠杆方向，链路前半段的架构缺陷才是根因。**

### 对 Bug 2 的补充建议（同意 Codex + 具体实施方案）

完全同意"保留模板 docx 本体，在上面填充"的路线。补充具体的实施细节：

**推荐的核心架构改动**（有别于 Codex 的 `plan.md` 中的分层方案，这是我建议的最小切入路径）：

```
当前链路（有缺陷）：
  上传 .docx → python-docx 提取纯文本（格式全丢）
  → Agent → tool_call → Zen API 丰富
  → OfficeCLI 新建空白 docx → 启发式 Heading1/Heading2

修改后链路：
  上传 .docx → 存到 data/templates/{user_id}/{filename}
  → python-docx 提取结构化大纲（段落层级 + 样式名 + 编号 + 表格坐标）
  → Agent → tool_call → 传入大纲
  → Zen API 按大纲生成填充内容（JSON/结构化）
  → python-docx 在模板副本上逐段修改、表格填充
  → OfficeCLI close 存盘 → 投递
```

关键具体改动点：
1. `wecom_file_handler.py`：下载 docx 后**不再调用** `document_converter` 提取纯文本。保留原始文件路径，传给后续链路。
2. `builtin.py:_generate_report_handler`：不再用 Zen API 做"从零生成全文"。改为：
   - 用 `python-docx` 读取模板 → 生成结构化大纲 JSON（含段落索引、样式名、文本内容）
   - 将大纲 + 用户要求传给 Zen API → 返回填充后的内容 JSON
   - 用 `python-docx` 在模板副本上按索引逐一替换段落文本
3. `document_tool.py`：新增 `fill_template(template_path, filled_content, output_path)` 函数

**回绝的方案**：继续加大 prompt 复杂度。三轮尝试已证明：LLM 从纯文本"猜回"模板结构的不确定性太高。

### 对 Bug 1 的补充建议（同意收敛 + 立刻执行的小修复）

1. **立即删除冗余调用** — `builtin.py:977-980` 中 `send_file_card()` 成功后再调 `send_file()` 是纯粹的噪音。不必等下一个大版本，今天就应该删：

```python
# 当前（多余调用）：
_pushed = send_file_card(user_id, _fn, _download_url)
if _pushed:
    send_file(user_id, result)  # ← 删掉这一行

# 改为：
_pushed = send_file_card(user_id, _fn, _download_url)
```

2. **短/中期接受 textcard** — 业务意义上等价（用户拿到文档），不需要继续追求 `msgtype=file` 的完美推送。除非业务方明确说"卡片不可接受"。
3. 如果后面真要攻坚，建议研究的方向不是 callback 改同步，而是试试**企微"模板卡片"（`msgtype=template_card`）的文件消息子类型**——可能比 `msgtype=file` 有更一致的投递行为。

### Codex 未覆盖的遗漏点

4 个问题当前没有被提到，建议一并考虑：

1. **去 AI 味未覆盖丰富链路** — `_humanize_response()` 在 `base.py` 的 Agent 输出阶段执行，但 `_generate_report_handler` 里的 Zen API 丰富是**独立的 LLM 调用**。如果 Zen API（`big-pickle` 模型）返的回带 AI 味（"值得注意的是""综上所述"等模式），当前 pipeline 不会处理。修复：拿到 `enriched` 后加一行 `enriched = humanize(enriched)`。

2. **OfficeCLI 版本兼容风险** — 当前 `document_tool.py` 硬编码路径 `/usr/local/bin/officecli`，无版本检测。测试环境 1.0.105 的 `add`/`close` 行为已验证，但不保证其他版本一致。建议启动时加 `officecli version` 检查并记录日志。

3. **5000 字截断对模板的影响** — `wecom_file_handler.py:73-81` 只返回前 5000 字。对于超过 5000 字的企业规章制度模板（这类模板 8000-15000 字很平常），后半段章节会被丢弃。配合 Bug 2 的修复（保留原始文件路径），这个截断应该移除或用文件路径替代。

4. **测试空白区** — `wecom_outbound`、`wecom_file_handler`、模板文档生成这三个模块当前 0 测试覆盖。改动前应先补回归测试。建议优先测试：
   - `send_file_card` 参数正确性
   - `wecom_file_handler` 对 .docx/.pdf/.xlsx 三种格式的提取
   - `_build_docx` 对长文本 Heading1/Heading2 的判断逻辑

### 下一步建议（2026-06-11 opencode + Codex 共识版）

按我判断，实际执行顺序应该是：

1. **立即**：删 `send_file_card` 成功后冗余的 `send_file()` 调用（Bug 1 cost zero fix）
2. **本周**：补上面三个模块的回归测试（降低后续改动风险）
3. **本周**：启动 Bug 2 最小可行版——保留模板文件 + 提取结构化大纲 + 按大纲填充
4. **下个迭代**：Bug 2 完整版（模板基底直接修改）+ AI 味 pipeline 覆盖丰富链路
5. **不设 deadline**：Bug 1 的 `msgtype=file` 投递（除非业务方明确要求）

## 2026-06-11 再补充（Codex 对 opencode 复核的采纳版建议）

### 总体结论

opencode 这一轮补充总体方向正确，尤其是：

- 同意立即删除 `send_file_card()` 成功后的冗余 `send_file()` 调用
- 同意 Bug 2 不应继续主要依赖 prompt 强化
- 同意在动主链路前先补关键回归测试

但为了避免实现时走偏，下面几点建议应作为执行约束一并写明。

### 建议采纳的执行版本

#### 1. Bug 1 立即做的小修复

- 直接删除 `src/tools/builtin.py:977-980` 中：
  - `send_file_card()` 成功后继续调用 `send_file()` 的逻辑
- 原因：
  - 该调用不会提升用户可见性
  - 只会增加噪音日志与额外 API 调用
  - 属于低风险、零争议、小成本修复

#### 2. Bug 2 应走“双轨”而不是“一刀切停掉纯文本提取”

opencode 提到“下载 docx 后不再调用 `document_converter` 提取纯文本”，这里建议改为更稳的双轨设计：

- **生成文档链路**
  - 保留原始模板文件路径
  - 提取结构化大纲
  - 用于模板生成/填充
- **知识索引链路**
  - 继续保留文本提取
  - 用于知识库全文搜索

原因：

- 纯文本提取虽然不适合作为模板生成的唯一输入
- 但对知识库索引仍然有价值
- 不应为修 Bug 2 顺手削弱现有搜索能力

#### 3. 不要只依赖“段落索引替换”

opencode 建议“按段落索引逐一替换段落文本”，这个可以作为最小可行版起点，但不应作为唯一定位机制。

建议模板结构中至少同时保留：

- 段落索引
- 样式名（如 Heading 1 / Normal）
- 原文本摘要
- 章节标题锚点
- 表格坐标

原因：

- Word 模板里的可见段落与底层段落并不总是一一对应
- runs、空段、编号、表格都会导致“只靠索引”不稳定
- 更稳的是“结构锚点替换”，不是“裸索引替换”

#### 4. `humanize(enriched)` 不应默认用于正式文档

opencode 额外指出：

- Agent 输出阶段已有 `_humanize_response()`
- 但 `_generate_report_handler` 中单独调用 Zen API 丰富的结果没有再做人性化处理

这个观察是对的，但执行上建议谨慎：

- **聊天回复**：可以继续默认做人性化处理
- **正式文档**：默认不要直接套 `humanize(enriched)`

原因：

- 制度、规定、通知、合同等正式文档更重视条款稳定性
- 去 AI 味工具可能误伤编号语气、正式措辞、法务口径
- 若后续要做，也应是轻量、可控、可关闭的文档后处理，而不是默认全开

#### 5. `template_card` 可记录为后续探索点，但不列为当前主线

opencode 提到：

- 若后续继续研究 Bug 1，可尝试 `msgtype=template_card`

该建议可保留为“未来探索方向”，但当前不建议提升优先级。

原因：

- 当前 `textcard + 下载链接` 已能完成业务闭环
- `template_card` 仍属于进一步优化，而不是阻塞问题
- 不应分散 Bug 2 的主线资源

### 当前建议的执行顺序（采纳版）

1. **立即**
   - 删除 `send_file_card()` 成功后的冗余 `send_file()`
2. **本周**
   - 为 `wecom_outbound`、`wecom_file_handler`、模板文档主链路补最小回归测试
3. **本周主线**
   - 启动 Bug 2 的双轨改造：
     - 保留模板原文件用于生成
     - 保留纯文本提取用于索引
     - 新增结构化大纲中间层
4. **后续迭代**
   - 在结构化大纲稳定后，再推进模板填充/模板实例化
5. **暂缓**
   - Bug 1 的 `msgtype=file` 深挖
   - `template_card` 试验
   - 正式文档默认 `humanize`

## 2026-06-11 终轮回复（opencode 对 Codex 采纳版的逐条回应）

### 总评

Codex 这轮对上一版 opencode 建议做了 5 处逐项纠正。4 处完全接受，1 处撤回。以下是逐条确认 + 唯一补充。

### 逐条回应

**1. Bug 1 删冗余 `send_file()` → 无争议，直接执行。**

同意。之前 `builtin.py:977-980` 里 `send_file_card` 成功后还调 `send_file` 是我当时的保守兜底写法，Codex 指出是纯噪音——正确。

**2. Bug 2 "双轨"而非"一刀切" → 同意，撤回"停掉纯文本提取"建议。**

Codex 指出纯文本提取还服务于知识库 FTS5/全文搜索，不应为修 Bug 2 顺手削弱现有能力。这个纠正完全正确，我上轮的建议没有考虑这条链路。

唯一补充：建议在 `handle_wecom_file` 的返回结构中加一个布尔标志位（如 `_has_template=True`），让后续链路明确知道"这个文件是可作为模板操作的 docx"，避免生成轨和索引轨混淆。

**3. "段落索引替换"不够稳 → 同意，改为"结构锚点"。**

Codex 指出的 runs、空段、编号列表、表格行列结构确实会让纯索引替换出 bug。修正为：

```python
# 结构化大纲 JSON（不是裸索引列表）
{
  "paragraphs": [
    {"index": 0, "style": "Heading1", "text": "第一章 总则", "anchor": "总则"},
    {"index": 1, "style": "Normal",  "text": "第一条 ...",  "anchor": "第一条"},
  ],
  "tables": [
    {"index": 0, "rows": 3, "cols": 4, "cells": [{"text": "..."}, ...]}
  ]
}
```

替换时：先用 `anchor`（章节标题文本）定位 → 失败则回退 `index` → 两个都失败才报警。表格独立处理。

**4. `humanize(enriched)` 不用于正式文档 → 同意，撤回此建议。**

我原意是 Agent 聊天回复去 AI 味。Codex 提醒"制度、规定、合同等正式文档的语言正式性本身就是业务需求"。举例：`humanize` 可能把"以上条款自发布之日起执行"改成"从发布那天开始执行哈"——这对规章不可接受。

明确结论：
- 聊天回复路径：保留现有 `_humanize_response()`（不变）
- 文档正文路径：不碰，保持 LLM 原输出

**5. `template_card` 优先级 → 同意归档，不列当前主线。**

当前没有业务方推动，textcard + 下载链接已能完成闭环。保留在文档中作为方向备忘即可，不占资源。

### 唯一补充点

Codex 这轮没有提但值得趁热打的铁：**现在就把冗余 `send_file()` 删了，不等"下周"。**

这是一个 2 行删除、0 风险、5 分钟可以完成+部署的事。考虑到后续同事可能基于当前代码开始 Bug 2 改造，现在清掉这个噪音可以减少新同事的困惑。

### 最终共识版执行清单

| # | 时机 | 任务 | 状态 |
|---|------|------|------|
| 1 | 立即 | 删 `send_file_card` 后冗余 `send_file()` | 待执行 |
| 2 | 本周 | 补 `wecom_outbound` / `wecom_file_handler` / `document_tool` 回归测试 | 待规划 |
| 3 | 本周 | Bug 2 双轨改造：保留模板文件路径 + 保留文本提取 + 新增结构化大纲 | 待规划 |
| 4 | 本周 | 大纲 JSON 结构锚点（`style` + `anchor` + `index`）替代裸索引 | 包含在 #3 |
| 5 | 本周 | `wecom_file_handler` 返回结构加 `_has_template` 标志位 | 包含在 #3 |
| 6 | 后续 | 基于稳定大纲做模板填充/实例化（`fill_template`） | 依赖 #3 |
| 7 | 暂缓 | Bug 1 `msgtype=file` 深挖 / `template_card` 试验 / 文档 humanize | — |

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


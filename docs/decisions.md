# Architecture Decisions

## 已采纳

### 2026-06-22：`src/platform/__init__.py` 定位为兼容 facade，不再承载能力实现

- **决策**：`src/platform/__init__.py` 保留为兼容门面，但默认只做三件事：
  - provider 装配
  - capability backend 薄包装
  - 供旧调用方过渡的 facade
- **新增约束**：
  - 新的工具层代码优先走显式 capability ID
  - 新的上下文与审计链路优先走 `invoke_capability(...)` / `invoke_capability_first(...)`
- **原因**：
  - 项目仍有较多历史调用点，直接删除 facade 风险大
  - 但继续把能力逻辑堆在 facade 里，会重新回到“散函数入口”模式
- **影响**：
  - capability backend 继续作为真正执行面
  - facade 被保留，但默认不再增长业务实现

### 2026-06-22：能力调用开始记录统一身份上下文与审计

- **决策**：在 capability backend 层新增统一调用上下文与集中式本地审计落点；当前实现为 SQLite，并保留 legacy JSONL 迁移能力
- **上下文字段**：
  - `user_id`
  - `platform`
  - `transport`
  - `scope`
  - `scope_id`
  - `source_chat_id`
- **原因**：
  - 架构目标已明确要求“用户身份贯穿调用链”
  - 审计不应散落在单个平台分支里
- **影响**：
  - 工具层可带上下文调用 capability backend
  - 审计记录默认落在 `data/audit/capability_audit.sqlite3`
  - 旧 JSONL 审计文件可由迁移逻辑导入 SQLite 后端

### ADR-001：AgentEngine 独立实现，不依赖 Hermes

- **上下文**：Hermes `conversation_loop.py` 有 4892 行，深度耦合 17k 文件 Hermes 运行时
- **决策**：自建 ~70 行 `src/engine/base.py`，支持 OpenAI 兼容和 Anthropic SDK
- **理由**：M1 范围只需 LLM 文字 + 工具调用，无需 Hermes 全量能力

### ADR-002：工具调用采用 `<tool_call>` XML 标签协议

- **上下文**：OpenAI function calling 绑定供应商，增加测试复杂度
- **决策**：`<tool_call>tool_id(json_args)</tool_call>` 正则匹配 + 执行替换
- **理由**：供应商无关、可测试、LLM（DeepSeek/Claude/GPT）均可自然输出

### ADR-003：Gateway 基于 stdlib http.server，无 Flask/FastAPI

- **上下文**：M1 需要最小依赖，OpenVort 负责 WeCom 回调接收
- **决策**：单文件 `src/gateway/webhook_server.py`，端口 18090
- **理由**：零额外依赖，OpenVort 直接 HTTP POST 转发

### ADR-004：Gateway 自动创建 PersonalAgent

- **上下文**：不要求用户预注册
- **决策**：`InboundGatewayService._get_or_create_agent()` 按需创建
- **理由**：多用户无需管理注册流程，对协作系统友好

### ADR-005：侧车记忆采用文件 JSON 存储

- **上下文**：M1 需要简单持久化，避免引入数据库
- **决策**：`SidecarMemory` 读写 `data/memory/agent_{id}.json`
- **理由**：低复杂度，零外部依赖，可随时升级到数据库

### ADR-006：无 space_id 视为直发消息

- **上下文**：使用方可能不传 space_id
- **决策**：`wecom_adapter.py` 中检测 payload 是否有 `space_id`/`project_id`/`dept_id`，无则 `is_direct=True`
- **理由**：减少调用方配置错误，保持向后兼容

### ADR-007：BatchFlusher 后台线程周期冲洗

- **上下文**：空间消息需要自动汇聚后触发任务识别
- **决策**：`BatchFlusher` 每 30s 检查缓冲，达到 `min_batch_size=2` 即冲刷
- **理由**：简单可靠，无需外部调度器或消息队列

### ADR-008：ProjectAgent 用独立 engine 实例

- **上下文**：PersonalAgent 和 ProjectAgent 需要不同的 system prompt 和工具集合
- **决策**：`serve()` 中创建 `engine`（personal）和 `project_engine`（project）两个独立实例
- **理由**：角色独立、工具集合可不同，避免串扰

### ADR-009：ThreadingHTTPServer 替代单线程 HTTPServer

- **上下文**：长 LLM 调用（10-30s）会阻塞后续请求，导致任务板加载等待
- **决策**：在 `webhook_server.py` 中使用 `socketserver.ThreadingMixIn` 混合类
- **理由**：零额外依赖、简单有效、单次 LLM 调用不再阻塞并发请求

### ADR-010：Systemd Timer 驱动自动继续

- **上下文**：需要无人值守推进开发阶段
- **决策**：`auto-continue.timer` 每 5 分钟触发 `auto-continue.service`，检测网关空闲 → 执行下一阶段
- **理由**：无需外部 CI/CD，可在受限网络环境中运行

### ADR-011：Privoxy 桥接 SOCKS5 → HTTP 代理

- **上下文**：Docker daemon 原生不支持 SOCKS5 代理（仅 HTTP/HTTPS）
- **决策**：`privoxy` 作为 HTTP 代理（:8118），`forward-socks5 / 127.0.0.1:1080 .` 转发到 v2ray
- **理由**：Docker 标准支持 HTTP_PROXY，无需修改 Docker 源码或使用非标准方案

### ADR-012：跳过 Docker Compose 部署（直接 Python 运行）

- **上下文**：Docker Hub 通过代理拉取镜像极慢（CloudFront CDN ~5KB/s），而服务器已有 Python 3.12 + pip 可用
- **决策**：放弃 docker_pull/docker_compose_up 阶段，systemd 直接运行 Python
- **理由**：容器化是部署方式而非功能需求，M1 阶段无需容器隔离

### ADR-013：SSE 事件总线替代 DB 轮询

- **上下文**：仪表盘 SSE 通过 3 秒轮询 DB checksum 检测变更，延迟高且无法区分事件类型
- **决策**：`src/web/sse_bus.py` 内存事件总线，写操作 emit typed event，SSE 实时推送
- **理由**：推送延迟从 ~3s 降至 ~10ms；前端可根据 `draft_generated`/`task_created`/`reminder_fired` 等事件类型针对性处理

### ADR-014：M1 范围收敛至"开工建议-最终版"

- **上下文**：原"融合计划"含四项目全融合（OpenVort + Hermes + Memory Sidecar + KMM），但 gbrain/pgvector/视频处理等依赖过于复杂
- **决策**：M1 仅实现最小协作闭环"聊天→任务→催办"，四项目融合推迟到 M2-M4
- **理由**：避免基础设施依赖阻塞开发进度，先验证核心协作价值

## 待讨论

- ✅ ~~任务草案确认流程：当前只通过 callback log 输出，未回写到聊天流~~ — 已实现 Chat 确认/驳回
- ✅ ~~空间/项目动态创建：当前 hardcode `proj-1`~~ — 已实现自动创建
- ✅ ~~WeCom 出站消息打不通~~ — 2026-06-09 催办通知接入 send_text()
- ✅ ~~组织架构手动同步~~ — 2026-06-09 systemd daily timer
- 记忆持久化升级：从文件 JSON → 数据库（M2）
- Embedded DuckDuckGo：测试服务器到 Python `duckduckgo_search` 库的网络被墙，DuckDuckGo 后端不可用 → 降级链跳过该步骤

### ADR-018：SearXNG 从 Docker Hub 迁移至 GHCR

- **上下文**：Docker Hub 通过系统代理 (privoxy:8118 → v2ray SOCKS5) 拉取需 600MB+ blob，CloudFront CDN 限速导致失败
- **决策**：改用 `ghcr.io/searxng/searxng:latest`，该 registry 直连（无代理）15 秒完成拉取。拉取前临时移除 `/etc/docker/daemon.json` 代理配置 + 重启 dockerd，拉完后立即恢复
- **理由**：GHCR 在国内网络可达，无需等待 Docker Hub 问题修复

### ADR-019：SearXNG 容器 `network_mode: host` 直通代理

- **上下文**：系统代理 `privoxy` 仅侦听 127.0.0.1:8118，容器隔离网络无法访问；修改 privoxy 监听接口引入额外变更
- **决策**：Docker `network_mode: host` 使容器直接使用宿主机网络栈
- **理由**：单容器服务无端口冲突风险，配置简单，`127.0.0.1:8118` 可直接访问

### ADR-020：SearXNG `doi_resolvers` 为 dict（非 list）

- **上下文**：SearXNG v2026.6.8 中 `settings.yml` 的 `doi_resolvers` 为 YAML mapping（短名 → URL 映射），代码 `list(settings['doi_resolvers'])` 取其 keys；`default_doi_resolver` 须用带引号的字符串 `'oadoi.org'`
- **决策**：复制默认 settings.yml 的 `doi_resolvers` dict 格式，保留全部 5 个 resolver（oadoi.org, doi.org, sci-hub.se/st/ru）
- **理由**：msgspec 强类型验证，错误格式导致 ValidationException（HTTP 500）

### ADR-015：Tool call 边界解析替代正则

- **上下文**：`<tool_call>name({"text":"带}的内容"})</tool_call>` 中 JSON 含 `}` 时正则截断
- **决策**：按 `<tool_call>` / `</tool_call>` 标签边界解析，取 `name(...)` 中括号内容
- **理由**：无需平衡括号计数，天然正确处理 `</tool_call>` 之前的任何内容

### ADR-016：LLM 指数退避重试

- **上下文**：生产环境 DeepSeek/Zen API 偶发 5xx 或 rate limit
- **决策**：`_retry_llm()` 3 次退避 (1s/2s/4s)，全部失败返回错误消息
- **理由**：简单可靠，覆盖 99% 的瞬时故障

### ADR-017：BatchProcessor 按消息 ID 去重

- **上下文**：恢复消息 + webhook 消息可能相同 ID 重复提交
- **决策**：`submit()` 维护 `_seen_ids` set 跳过重复
- **理由**：避免重复识别任务草案

### 2026-06-11：关于两个现网 Bug 的分析边界

- **Bug 1（WeCom send_file）**
  - 已确认：当前异步 `message/send` + `msgtype=file` 在测试服务器环境下“API 成功但聊天窗不可见”
  - 未确认：这是否等同于“企微自建应用天然不支持该路径”
  - 因此后续讨论中，应将“现象已复现”和“平台限制已定性”严格分开
- **Bug 2（模板文档生成）**
  - 已确认：当前问题的核心不在 prompt，而在 `.docx` 模板进入系统后已被降级为纯文本
  - 因此后续修复方向优先考虑“保留模板本体并提取结构”，而不是继续单独强化提示词
# 技术决策记录

## 2026-06-16 — 系统总方向切换为 Bot First, Capability Backend

### 决策

项目后续统一采用：

- Bot 作为员工唯一前端入口
- 平台应用 / 官方 API / 第三方连接器 / 插件作为 Bot 背后的能力后端

不再继续把“每个平台都做一个独立前端应用”作为默认推进方向。

### 原因

- 项目最早定位是“企业多智能体协作系统”，不是单一工作台应用
- 员工更容易接受“找 Bot 说话”，而不是“进入某个平台应用页面”
- 平台应用更适合作为通讯录、审批、日历、在线文档、网盘、邮箱等能力来源
- 这种模式更利于跨企微 / 飞书 / 钉钉统一架构

### 影响

- 交互层统一为 Bot
- 编排层统一调度 Agent / Tool / Task / Memory / Knowledge
- 能力层需要逐步抽象成统一能力协议
- `src/platform/__init__.py` 的散函数聚合模式将逐步迁移到统一能力后端
- 第一版统一能力后端已落到 `src/platform/capability_backend.py`

### 后续执行约束

后续新增功能时，优先判断：

1. 能否作为 Bot 背后的能力层扩展？
2. 能否归入统一能力域，而不是新增平台专属前端？
3. 是否带上了用户身份和权限上下文？

## 2026-06-17 — 企业文档处理默认采用本地私有部署

### 决策

对于 PDF / Office / OCR 等企业文档处理能力：

- 默认优先本地服务器私有部署
- 不将外部托管 API 作为主处理链路
- 允许内部 provider 与本地部署服务 provider 并存

### 原因

- 企业文档数量大，存在持续同步和并发处理需求
- 企业文档往往涉及敏感信息，不适合默认出域
- 本地部署更适合高并发、批处理和流水线化接入
- 更符合当前项目“Bot 前台 + 企业能力后端”的企业级定位

### 影响

- 当前 `pdf_tool.py` / internal provider 作为短期实现继续保留
- 后续新增 `stirling_pdf_provider.py` 时，默认按本地私有部署方式接入
- `OCRmyPDF` 若后续接入，也按本地 OCR provider 处理

## 2026-06-17 — Office 文档主后端优先采用 OfficeCLI

### 决策

对于 `docx/xlsx/pptx` 本地文档处理能力：

- 当前主后端优先采用 `OfficeCLI`
- `ONLYOFFICE Docs` 作为后续协作式文档补充
- Microsoft 官方 Office AI / Skills 仅作为研究参考

### 原因

- `OfficeCLI` 已与当前项目 `document_tool.py` 直接兼容
- 更适合作为 Bot 背后的结构化 Office 文档处理后端
- 比协作文档服务器更适合当前阶段的能力后端定位
- 比云侧 Office AI 体系更符合本地私有部署约束

### 影响

- `files.office.service_status`、`files.docx.generate`、`files.xlsx.generate`、`files.pptx.generate`、`files.docx.template_outline` 默认围绕 OfficeCLI 演进
- 后续若需要在线编辑与多人协作，再评估接入 `ONLYOFFICE Docs`

## 2026-06-15 — docx 模板生成从“重建正文”切换为“克隆模板段落骨架”

### 决策

`src/tools/document_tool.py` 的 docx 模板生成逻辑不再以 `add_paragraph()` 为主重建正文，而是优先：

1. 保留模板前言元素
2. 克隆模板段落本体
3. 在克隆段落上替换文本
4. 对审批/修订类前置表格只做单元格回填

### 原因

- 仅复制样式名无法保留 Word 的段落级直接格式
- 重新建段会丢失对齐、缩进、段前后距、编号骨架等关键信息
- 之前前言节点被追加到 `sectPr` 后方，导致模板首页元素实际未进入正常正文流

### 影响

- 模板版式延续性显著提升
- 审批表不再重复追加
- 后续可继续往“结构锚点原位替换”演进

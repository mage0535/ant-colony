# Architecture Decisions

## 已采纳

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

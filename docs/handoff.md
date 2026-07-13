# 项目交接状态 - 当前页

## 先看这个

历史连续开发记录已归档到：

- `docs/handoff-archive-2026-06.md`

当前页只保留：

- 当前架构结论
- 最新完成状态
- 最新验证证据
- 下一步建议

## 当前架构结论

- 主方向：`Bot First, Capability Backend`
- 用户前台：Bot
- 后端能力：平台 API / 本地能力 / 第三方连接器
- 文件能力：一级能力，覆盖模板、解析、生成、回推
- 本地文档后端：
  - `OfficeCLI`
  - `internal provider`
  - `Stirling-PDF`
  - `OCRmyPDF`

## 当前代码状态

### 1. 文件消息编排

- 已统一到 `src/gateway/file_message_pairing.py`
- `InboundGatewayService` 和 `WeComBotBridge` 共用同一套：
  - 文件+文本拼接规则
  - 文件引用文本检测
  - 文档生成意图检测
  - 标题推断

### 2. 工具层拆分

- `src/tools/builtin.py` 仍是工具注册中心，但主要领域已拆出：
  - `src/tools/platform_capability_tools.py`
  - `src/tools/task_tools.py`
  - `src/tools/knowledge_tools.py`
  - `src/tools/org_admin_tools.py`
  - `src/tools/email_capability_tools.py`
  - `src/tools/role_methodology_tools.py`
  - `src/tools/document_prompt_helpers.py`

### 3. 平台能力入口

- `src/platform/__init__.py` 明确保留为 compatibility facade
- 新代码优先走：
  - `invoke_capability(...)`
  - `invoke_capability_first(...)`
  - `build_capability_context(...)`
- 真实执行面仍是：
  - `src/platform/capability_backend.py`

### 4. 身份上下文与审计

- capability backend 已支持统一上下文透传：
  - `user_id`
  - `platform`
  - `transport`
  - `scope`
  - `scope_id`
  - `source_chat_id`
- 当前审计落点：
  - `data/audit/capability_audit.sqlite3`
- 当前已支持：
  - 追加记录
  - 文件权限限制
  - legacy JSONL 迁移
  - 轮转
  - 查询过滤

### 4.1 LangSmith Cloud 观测

当前已新增：

- `src/observability/langsmith_support.py`
- `scripts/validate_langsmith_cloud.py`
- `scripts/langsmith_run_report.py`

已接入 tracing 的关键链路：

- `handle_wecom_payload`
- `generate_document`
- `build_memory_context`
- `capability_invoke`
- `capability_invoke_first`
- `identify_project_tasks`
- OpenAI / Anthropic client wrappers

服务器验证结果：

- LangSmith Cloud 已连通
- `ant-colony` 项目已存在并可见
- 已生成真实 traces，可拉取最近 run 报告

### 5. 扩展后的能力域

当前除原有能力外，已新增并接入统一 capability backend：

- `drive.list`
- `drive.sync`
- `mail.list`
- `mail.search`
- `mail.get`
- `mail.send`
- `drive.read`
- `docs.read`
- `approval.detail`
- `meeting.get`
- `calendar.detail`

其中当前 provider 主要为 `internal`，用于把现有本地云盘/邮箱动作正式纳入统一能力协议。

### 6. 平台适配层

- WeCom 主链路可用
- Feishu / DingTalk 已补本地契约测试，覆盖：
  - 签名/验证
  - URL verify
  - 群消息过滤
  - 非文本消息忽略
  - 出站 payload
  - gateway 重试逻辑
- Feishu / DingTalk 当前无真实账号和群场景，新增无凭据本地模拟验收脚本：
  - `scripts/simulate_platform_adapter_contracts.py`
  - 覆盖直聊文本入站、转发到 gateway、出站回复、群消息未 @ 忽略

### 7. 动态组织图谱与权限

当前已新增：

- `src/platform/org_graph.py`

能力包括：

- 按平台存储部门、用户、成员关系
- 存储部门负责人和平台管理员标记
- 供 ACL、组织同步、任务指派共同复用

当前已接入：

- `src/knowledge/acl.py`
  - 角色解析直接基于动态组织图谱
  - 部门读写权限按真实部门成员/负责人判断
  - 项目读写权限按真实空间成员判断
- `src/orchestrator/org_sync.py`
  - 组织同步会把部门成员同步到 `SpaceRegistry`
  - 部门空间会写入平台、部门 ID、父部门 ID 元数据
- `src/agents/project_agent.py`
  - 基础任务指派已支持按部门空间成员姓名匹配 assignee

### 8. 多层记忆作用域

当前已新增：

- `src/memory/scoped_store.py`

能力包括：

- 个人 / 部门 / 项目 / 群组 作用域记忆存储
- 作用域级检索
- `MemoryContextBuilder` 已接入 scoped memory 召回
- `InboundGatewayService` 已按 personal/department/project/group 组装检索作用域

### 9. 详情能力层

当前已把以下“从列表走向详情”的能力正式接入统一 capability backend：

- `drive.read`
- `docs.read`
- `approval.detail`
- `meeting.get`
- `calendar.detail`

说明：

- 当前 `internal provider` 已提供可用的 `drive.read` / `docs.read`
- 平台 API provider 对 `approval.detail` / `meeting.get` / `calendar.detail` 已补齐基础兼容入口
- 后续可继续将这些能力从“兼容入口”增强到“真实详情语义”

### 10. 知识 / 记忆升级流

当前已新增：

- `KnowledgeService.promote_entry(...)`
- `ScopedMemoryStore.promote(...)`

能力包括：

- 项目知识 -> 部门知识 / 企业公共知识的升级
- 个人记忆 -> 项目/部门记忆的升级
- 为后续企业经验沉淀提供明确升级接口

## 最新完成状态

### 2026-06-22 current completed step

本轮完成了本地代码的第二阶段结构与治理收口：

- 继续拆分 `builtin.py`
- 进一步压缩 `platform/__init__.py` 的重复 wrapper
- 为 `CapabilitySpec` 增加治理元数据：
  - `risk_level`
  - `domain`
  - `requires_user_context`
  - `audit_scope`
- 为 capability audit 增加：
  - 轮转
  - 过滤查询
- 新增 Bot E2E 回归脚本：
  - `scripts/run_bot_e2e_regression.py`
- 恢复启动协议所需文档：
  - `docs/m1-plan.md`
  - `docs/user-manual.md`

### 2026-06-23 user-facing manuals

本轮补齐了面向全公司的用户说明书与知识库说明书：

- `docs/user-manual.md`
- `docs/wecom-ai-assistant-activation-guide.md`
- `docs/wecom-ai-assistant-feature-guide.md`
- `docs/knowledge-base-operations-guide.md`

同时补充了后台文件上传接口的知识归属参数，支持将上传文件显式索引到：

- `personal`
- `project`
- `department`
- `organization`

### 2026-06-23 knowledge management and guide import

本轮补齐了企业知识库的统一读写与管理能力：

- 新增公司级说明书导入：
  - `scripts/import_company_guides.py`
  - `src/knowledge/company_guides.py`
- 三份说明书现在可按稳定 ID、稳定标题、稳定关键词导入到公司级知识库
- 机器人文档检索策略已调整为：
  - 先查本地知识库 `search_knowledge`
  - 本地无结果再尝试 `docs.search`
  - WeCom 在线文档搜索返回 `HTTP 404` 时不再直接把底层错误暴露给用户
- 新增知识库统一仓库层：
  - `src/knowledge/repository_factory.py`
  - 机器人搜索、后台管理、文件索引、说明书导入统一走同一套仓库接口
- 新增后台知识库管理能力：
  - `GET /api/v1/knowledge/accessible`
  - `GET /api/v1/knowledge/permissions`
  - `PUT /api/v1/knowledge/{entry_id}`
  - `POST /api/v1/knowledge/promote`
  - `POST /api/v1/knowledge/import/company-guides`
  - `GET /knowledge/manage`
- 管理页现在会按用户ID上下文显示：
  - 当前角色
  - 可见范围
  - 是否可管理公司/部门/项目知识
  - 条目级是否可更新/删除

### 2026-06-23 collaboration observation and trace quality analysis

本轮继续推进三块验证能力：

- WeCom 多人协作/权限/跨空间联动观测脚本：
  - `scripts/validate_wecom_collaboration_observation.py`
- Feishu / DingTalk 更深本地模拟覆盖：
  - 群 @ 正向转发
  - 非 @ 群消息忽略
  - 文件消息忽略
  - 直聊文本回复
- LangSmith traces 质量分析脚本：
  - `scripts/langsmith_quality_report.py`
  - 支持识别：
    - 慢链路
    - 失败链路
    - 低质量文档生成候选

### 2026-06-23 centralized bot activation and direct knowledge file delivery

本轮继续补齐两块企业可用性能力：

- 平台统一开通 BOT：
  - 新增 `src/platform/activation_service.py`
  - 新增 `src/web/admin_auth.py`
  - 新增管理员控制台 `GET /admin/console`
  - 新增管理员签名链接脚本 `scripts/create_admin_console_link.py`
  - 新增后台入口 `GET /platform/bots/manage`
  - 新增接口：
    - `GET /api/v1/admin/profile`
    - `GET /api/v1/admin/platform/bots`
    - `POST /api/v1/admin/platform/bots/{platform}/activate`
    - `POST /api/v1/admin/knowledge/import/company-guides`
    - `GET /api/v1/admin/runtime/status`
    - `GET /api/v1/platform/bots`
    - `POST /api/v1/platform/bots/{platform}/activate`
  - 当前原则：
    - 普通员工不自行创建 BOT
    - 不让员工自己配置回调 URL / Token / AESKey
    - 企微 / 飞书 / 钉钉 BOT 由平台统一接管和配置
  - 管理员控制台鉴权：
    - 页面 URL 携带 `platform/user_id/admin_token`
    - `admin_token` 由服务端 HMAC 签名并带过期时间
    - API 层会二次校验企业 IM 用户是否在组织图谱或管理员注册表中具备管理员权限
  - 管理员控制台已按 Material Design 3 风格重做：
    - `GET /admin/console`
    - 平台 Bot 开通改为逐字段表单，不再要求管理员粘贴 JSON
    - 状态区显示中文状态、缺少配置、是否需要重启和下一步动作
  - 新增员工 AI 助手分配能力：
    - `src/platform/employee_bot_service.py`
    - `GET /api/v1/admin/employee-bots`
    - `POST /api/v1/admin/employee-bots/activate`
    - `POST /api/v1/admin/employee-bots/deactivate`
    - 企微下会真实尝试向员工发送开通通知
    - 飞书/钉钉无真实凭据时保留模拟/待联调通知状态
  - 知识库管理页已按 Material Design 3 风格重做：
    - `GET /knowledge/manage`
    - 按企业 IM 用户权限自适配查询、创建、编辑、删除、升级和说明书导入
    - 管理员控制台打开时会透传 `platform/user_id/admin_token`
  - 统一开通已补充必填凭据校验：
    - 企微：`bot_id`、`bot_secret`
    - 飞书：`app_id`、`app_secret`
    - 钉钉：`client_id`、`client_secret`、`robot_code`
  - 管理状态已补充：
    - 中文平台名称
    - 缺少配置
    - 当前进程缺少环境变量
    - 是否需要重启
    - 下一步动作提示
  - 钉钉开通会同时写入 `DINGTALK_CLIENT_ID/CLIENT_SECRET` 与兼容旧配置的 `DINGTALK_APP_KEY/APP_SECRET`
- 知识命中文件直接推送：
  - 当 WeCom Bot 命中单个知识条目且条目有源文件时
  - 机器人直接返回 `BOT_FILE`
  - 会话中直接推送文件，而不是只给链接

## 最新验证证据

- 全量本地单测：
  - `python -m pytest -q`
  - 结果：`545 passed`
- Bot 回归脚本：
  - `python scripts/run_bot_e2e_regression.py`
  - 当前覆盖已包含 WeCom/document 主链路、Feishu/DingTalk adapter 契约与本地模拟验收
  - 结果：`76 passed`
- 编译检查：
  - `python -m compileall -q src tests scripts`
  - 结果：通过
- diff 质量检查：
  - `git diff --check`
  - 结果：通过（仅 CRLF 换行提示，无格式错误）

## 测试环境验证

- 验证环境：独立测试服务器
- 部署目录：项目部署根目录
- 同步前应先做好独立备份
- 已同步本地最新代码与测试文件到服务器
- 服务器 Bot 回归脚本：
  - `PYTHONPATH=. python3 scripts/run_bot_e2e_regression.py`
  - 结果：`63 passed`
- 服务器全量单测：
  - `PYTHONPATH=. python3 -m pytest -q`
  - 结果：`545 passed`
- 服务器外部环境验证脚本：
  - `PYTHONPATH=. python3 scripts/validate_external_runtime.py`
  - 结果：
    - 核心服务端口全部可达
    - WeCom 运行时凭据已在本地环境文件中配置
    - Feishu 运行时凭据缺失
    - DingTalk 运行时凭据缺失
  - 结论：
    - 企微已具备真实联调条件
    - 飞书和钉钉当前仍缺运行时凭据

- 服务器企微真实 smoke test：
  - `PYTHONPATH=. python3 scripts/validate_wecom_live.py`
  - 结果：
    - `corp_api.ok = true`
    - `bot_ws.ok = true`
  - 结论：
    - 企微应用凭据有效
    - 企微 Bot WebSocket 凭据有效
    - 当前代码与服务器配置已满足真实企微链路联调前置条件

- 服务器企微真实出站消息链路 probe：
  - `PYTHONPATH=. python3 scripts/validate_wecom_message_flow.py`
  - 结果：
    - `text.ok = true`
    - `file_card.ok = true`
    - `file_send.ok = true`
  - 结论：
    - 企微真实文本消息发送正常
    - 企微真实文件卡片发送正常
    - 企微真实文件消息发送正常
    - 当前企微 Bot 的真实出站主链路已通过自动化验证

- 服务器企微完整文档工作流验证：
  - `PYTHONPATH=. python3 scripts/validate_wecom_document_workflow.py`
  - 结果：
    - `configured = true`
    - `template_path` 已生成并保留到用户模板目录
    - `pushed = true`
    - `result = ""`
  - 结论：
    - 模板保留链路正常
    - 文档生成链路正常
    - 文件卡片推送正常
    - 文件消息推送正常
    - 企微“模板 -> 要求 -> 生成 -> 回推”自动化验证已通过

- 服务器企微完整 roundtrip 验证：
  - `PYTHONPATH=. python3 scripts/validate_wecom_full_roundtrip.py`
  - 结果：
    - `configured = true`
    - `uploaded = true`
    - `file_ack` 为“已收到文件……请继续发送你的要求……”
    - `bot_file = true`
    - `pushed = true`
  - 结论：
    - 企微文件上传下载链路正常
    - 企微入站文件识别正常
    - 企微文档生成返回 BOT_FILE 正常
    - 企微完整“上传 -> 应答 -> 生成 -> 回推”自动化 roundtrip 已通过

- 服务器 LangSmith Cloud 验证：
  - `PYTHONPATH=. python3 scripts/validate_langsmith_cloud.py`
  - 结果：
    - `configured = true`
    - `project = ant-colony`
    - `project_ready = true`
    - `project_visible = true`

- 服务器 LangSmith run 报告：
  - `PYTHONPATH=. python3 scripts/langsmith_run_report.py`
  - 当前报告显示：
    - `run_count = 50`
    - `run_types` 包含 `tool / chain / retriever / llm`
    - 当前 Top traces 包括：
      - `identify_project_tasks`
      - `generate_document`
      - `handle_wecom_payload`
      - `build_memory_context`
      - `capability_invoke`

- 服务器飞书 / 钉钉 live 验证准备脚本：
  - `PYTHONPATH=. python3 scripts/validate_feishu_live.py`
  - `PYTHONPATH=. python3 scripts/validate_dingtalk_live.py`
  - 无凭据模拟验收脚本：
    - `PYTHONPATH=. python3 scripts/simulate_platform_adapter_contracts.py`
  - 当前结果：
    - Feishu: `configured = false`
    - DingTalk: `configured = false`
  - 结论：
    - 两个平台的真实联调准备脚本已就绪
    - 当前真实联调阻塞仍是凭据缺失
    - 无凭据阶段可通过本地模拟验收覆盖 adapter 最小闭环

- 动态组织图谱相关回归：
  - 本地与服务器全量测试均通过
  - 当前本地总结果：`418 passed`
  - 当前服务器总结果：`415 passed`
- 服务器首次失败点已处理：
  - 原因：部署目录缺少 `.gitignore`
  - 处理：补同步 `.gitignore`
  - 结论：属于同步环境差异，不是代码行为缺陷

## 当前最值得继续推进的事项

1. 企微完整 roundtrip 已通过，下一步更适合补"真实人工群聊/多人场景"观测而不是基础链路修复
2. 飞书 / 钉钉当前按"模拟验收 + live 脚本待凭据"处理；补齐凭据后沿同一路径做真实联调
3. LangSmith Cloud 已接入，下一步可开始基于 traces 做系统性质量分析和回归评估
4. capability audit 已升级为 SQLite 集中式本地后端，下一步可评估是否迁到共享数据库或日志平台
5. 协作编排增强：
   - 自动升级
   - 自动催办
   - 跨群组互通规则
6. `src/tools/builtin.py` 已收缩到约 2000 行，后续只建议做小步精简，不建议大规模重构
7. 如果后续新增能力，默认要求：
   - capability ID 明确
   - user context 明确
   - audit scope 明确
8. 完成 6 个企微阻塞点修复：会议室跨天查询、日历 cal_id、文档搜索 404、一次性链接 JTI、项目空间注册、飞书/钉钉文档（缺凭据）
9. 管理员控制台链接刷新机制已就绪（refresh-token API + JS 按钮），但令牌仍是 24h TTL，未实现浏览器级 session_id 黑名单

## 当前下一步最值得扩展的能力

1. 知识/记忆升级流
   - 个人 -> 项目/部门 -> 企业公共
2. 协作编排增强
   - 自动分配
   - 自动升级
   - 群组互通规则
3. 真实多人协作场景联调
   - 部门群 / 项目群 / 跨空间 linked space 场景
4. 飞书 / 钉钉真实联调
   - 当前代码和模拟测试已就绪，仅缺凭据

## 2026-06-24 管理员控制台点击无响应修复

- 用户反馈：
  - 管理员控制台显示“未验证”
  - 页面内任意按钮点击无反应
- 根因：
  - `/admin/console` 页面内联 JavaScript 存在语法错误
  - `deactivateEmployeeBot()` 后多了孤立 `}`
  - 多处中文状态拼接和模板字符串在页面脚本中不够稳健，导致整段脚本无法执行
- 修复：
  - 重写管理员控制台脚本的 DOM 工具函数、表格渲染、chip 渲染和 API 错误处理
  - 去掉依赖浏览器全局 `id` 变量的表单读取方式，统一改为 `document.getElementById`
  - 对动态输出统一做 HTML 转义，避免状态字段污染页面
  - 员工 AI 助手开通/停用增加前端必填校验，未填员工 user_id 时直接提示中文错误
- 防回归：
  - `tests/test_admin_console.py` 新增脚本语法检查
  - 有 Node 环境时会对 `/admin/console` 和 `/knowledge/manage` 的内联脚本执行 `node --check`
- 验证：
  - 本地全量测试：`461 passed`
  - 服务器定向测试：`13 passed`
  - 服务器 `ant-colony-dashboard` 已重启，状态 `active`
  - 新管理台链接请求：HTTP 200
  - `/api/v1/admin/profile` 请求：HTTP 200，`can_activate_bots=true`

## 2026-06-24 小白化自动开通与知识库自动权限修复

- 用户反馈：
  - 平台 Bot 开通仍提示“企业微信统一开通缺少必填凭据：bot_id, bot_secret”
  - 管理员和普通用户都应按小白逻辑处理，尽量自动采集数据，只让用户审核确认
  - 知识范围应根据企业 IM 组织架构和权限自动分配，不应让管理员手动指定
  - 企业 IM 组织架构变化后，知识权限应及时同步
  - “知识库管理入口”点击后无法打开
  - 公司说明书不应作为独立项目存在，只应作为公司知识库中的普通文档
- 根因：
  - `activate_platform_bot` 只读取页面提交的 credentials，没有自动合并当前服务环境变量、`infra/.env.wecom` 和历史平台配置
  - `/knowledge/manage` 没有加入公开页面白名单，页面跳转会先被 Dashboard 鉴权中间件拦截
  - 知识库管理页仍暴露 `owner_type/owner_id` 让管理员手填
- 修复：
  - 平台 Bot 开通改为自动采集顺序：页面确认输入 -> 当前服务环境变量 -> `infra/.env.wecom` -> 历史平台配置
  - 只有所有来源都找不到必填项时，才提示管理员补充一次高级配置
  - 管理台按钮改为“确认自动接管企业微信/飞书/钉钉”
  - 知识库管理入口改为同窗口跳转，避免浏览器弹窗拦截
  - `/knowledge/manage` 加入公开页面白名单；页面内 API 仍使用 admin token / user_id 鉴权
  - `knowledge_permissions` 返回 `visible_scopes`、`writable_scopes` 和 `default_write_scope`
  - 新增知识默认 `owner_type=auto`，后端根据用户角色、部门、负责人关系自动写入个人/部门/项目/公司知识库
  - 自动升级知识条目同样使用后端自动目标范围
  - `OrgGraphService.sync_if_stale()` 按 TTL 自动刷新企微通讯录，管理员页面提供“同步组织架构”按钮
  - 公司说明书仍保存为 `organization/*` 范围下的普通知识条目，不作为项目空间存在
- 验证：
  - 本地全量测试：`465 passed`
  - 服务器定向测试：`26 passed`
  - 服务器 `ant-colony-dashboard` 已重启，状态 `active`
  - `/knowledge/manage?...` 请求：HTTP 200
  - `/api/v1/admin/knowledge/permissions?...` 请求：HTTP 200，`default_write_scope=organization/*`
  - 空 credentials 调用 `/api/v1/admin/platform/bots/wecom/activate?...`：HTTP 200，`missing_keys=[]`，`restart_required=false`

## 2026-06-24 IM 组织权限强制收敛复核

- 用户要求：
  - 后台管理必须自动获取企业 IM 中的用户角色、部门、负责人和管理员身份
  - 员工开通 AI 助手时，管理员只确认开通，不手动指定知识范围或权限
  - 用户管理知识库时，系统按 IM 组织架构自动匹配个人/部门/项目/公司知识范围
  - 公司说明书不能作为独立类目，只能作为公司知识库中的普通文档统一管理
- 复核发现：
  - 员工 AI 助手开通接口仍接受并保存外部传入的 `scope` 和 `permissions`
  - 管理员控制台仍展示“知识范围”和“权限”输入框，容易让管理员误配
  - 部门负责人曾可读取任意部门知识、写入公司级知识库，权限边界过宽
  - Bot 工具层的知识新增/升级/更新存在绕过页面 ACL 的可能
- 修复：
  - `activate_employee_bot()` 现在忽略外部传入的 `scope/permissions`，统一调用 ACL 从 IM 组织架构自动派生默认范围和权限
  - 管理员控制台移除员工知识范围/权限输入，只保留平台、员工 user_id、显示名称和确认按钮
  - ACL 收紧为：公司级写入仅管理员；部门级读取仅本部门成员/负责人；部门级写入仅对应部门负责人；管理员仍拥有全局权限
  - 知识新增、升级、更新工具统一调用 `default_write_scope()`、`may_read()`、`may_write()` 校验，避免 Bot 侧绕过权限
  - 公司说明书导入必须带用户身份并校验管理员；用户可见文案改为“普通公司级文档导入公司知识库”
- 防回归：
  - 新增/更新测试覆盖员工开通忽略手工范围、部门负责人不能管理公司知识库、部门负责人不能读写非负责部门、管理页不再出现 `employeeScope/employeePermissions`
- 验证：
  - 本地定向测试：`25 passed`
  - 本地编译检查：`python -m compileall -q src tests scripts`
  - 本地 diff 检查：`git diff --check`

## 2026-06-24 知识库管理页组织目录、文档上传和员工入口增强

- 用户反馈：
  - 知识库列表没有按组织架构分目录/分权限显示
  - 知识库管理页不能直接上传文档文件并立即索引
  - 员工需要一个单独链接直接管理自己权限范围内的知识库
  - 说明书需要按真实页面操作验证
  - 飞书、钉钉虽然暂无真实环境，也要按企微同构适配并做模拟测试
- 修复：
  - `/knowledge/manage` 页面新增“组织目录”，按当前用户 `visible_scopes` 和 `writable_scopes` 显示公司/部门/项目/个人目录、只读/可维护状态和条目数量
  - 页面新增“上传文档入库”，上传后调用本地文档解析和知识库索引，默认使用后端自动归属范围
  - 新增员工入口 `/knowledge/user`，用于员工通过企业 IM 身份令牌直接访问自己的知识库管理页
  - 新增员工签名令牌 `create_im_user_token()` 和脚本 `scripts/create_knowledge_user_link.py`
  - 新增 `/api/v1/user/knowledge/*` 员工专用 API，使用 `user_token` 校验身份，不依赖管理员令牌
  - 上传文件接口默认 `knowledge_owner_type=auto`，并在写入前调用 ACL 校验；公司级文件写入仅管理员可执行
  - ACL 部门成员/负责人判断增加 `platform` 参数，飞书/钉钉模拟组织图可走同一权限链路
  - 说明书更新为：管理员用 `/knowledge/manage`，员工用 `/knowledge/user`；不再要求小白用户手填 `owner_type/owner_id`
- 验证：
  - 本地全量测试：`468 passed`
  - 本地编译检查：`python -m compileall -q src tests scripts`
  - 本地 diff 检查：`git diff --check`
  - 服务器定向测试：`32 passed`
  - 服务器 `/knowledge/user?...`：HTTP 200，页面包含“上传文档入库”和组织目录 `scopeTree`
  - 服务器管理员上传文档：返回 `indexed=file-ced8137036a4`，搜索关键词可命中，归属 `organization/*`
  - 服务器飞书/钉钉模拟员工入口：HTTP 200，默认写入范围分别为 `personal:mock-feishu-user`、`personal:mock-dingtalk-user`
  - 公司说明书已重新导入公司级知识库，确保知识库内说明与页面功能一致

## 2026-06-25 企业 IM 前端入口指令

- 用户确认：
  - 企业微信 Bot 没有可用的固定菜单能力，不应把企微菜单作为主入口方案
  - 飞书可后续接机器人菜单，钉钉可后续接互动卡片/工作台入口
  - 三个平台都需要消息指令兜底
- 实现：
  - 新增 `src/gateway/entry_links.py`
  - 支持识别“打开知识库 / 知识库管理 / 上传文档入库 / 打开管理员控制台 / 进入后台”等入口指令
  - 普通入口生成 `/knowledge/user?...user_token=...`
  - 管理员入口先校验企业 IM 管理员身份，再生成 `/admin/console?...admin_token=...`
  - 非管理员请求管理员控制台时返回中文拒绝提示
  - `InboundGatewayService` 在进入 LLM 前拦截入口指令，直接返回链接，避免消耗模型
  - 飞书/钉钉 adapter 转发的 `platform` 字段已通过 `wecom_adapter` 保留，链接会生成对应平台参数
  - `build_platform_entry_menu()` 提供统一菜单/卡片数据，后续飞书菜单和钉钉互动卡片直接复用
- 验证：
  - 本地入口指令测试：`8 passed`
  - 本地全量测试：`476 passed`
  - 服务器已配置 `ANT_COLONY_PUBLIC_BASE_URL=<dashboard-public-base-url>`
  - 服务器入口指令 HTTP 验证：
    - 企微模拟“打开知识库”返回 `/knowledge/user?platform=wecom...`
    - 企微管理员模拟“打开管理员控制台”返回 `/admin/console?platform=wecom...`
    - 飞书模拟“打开知识库”返回 `/knowledge/user?platform=feishu...`
    - 钉钉模拟“上传文档入库”返回 `/knowledge/user?platform=dingtalk...`

## 2026-07-08 三端一致更新

- 本轮目标：
  - 不再只做“企微可用、飞书/钉钉模拟”，而是把三端入口协议、结构化菜单载荷和文件消息最小行为对齐
- 完成内容：
  - 入口命令中心继续收敛到 `src/gateway/entry_links.py`
  - 新增统一菜单触发词：
    - `菜单`
    - `帮助`
    - `入口`
    - `后台入口`
  - 新增统一菜单/卡片数据输出：
    - `build_platform_entry_menu(...)`
    - `build_platform_entry_payloads(...)`
  - 新增统一入口 API：
    - `GET /api/v1/admin/entry-menu`
    - `GET /api/v1/admin/entry-payloads`
    - `GET /api/v1/user/entry-menu`
    - `GET /api/v1/user/entry-payloads`
  - 飞书和钉钉现在不再把文件消息直接忽略：
    - 会转为“用户发送了文件：xxx”占位文本进入统一 gateway
    - 用户仍可继续发送要求，交互链路与企微对齐
  - 企微仍保持文本链接主方案；飞书/钉钉的结构化菜单/卡片 payload 已生成，但是否真正挂载到平台侧，仍取决于真实租户配置
- 验证：
  - 本地全量测试：`484 passed`
  - 本地模拟脚本：`python scripts/simulate_platform_adapter_contracts.py` 通过
  - 当前模拟结果显示：
    - Feishu 直聊、群 @、文件占位文本、回复链路全部通过
    - DingTalk 直聊、群 @、文件占位文本、回复链路全部通过
  - 当前追加完成：
    - 飞书 / 钉钉收到 `菜单 / 帮助 / 入口` 时，会直接发送结构化入口卡片
    - 新增 `src/gateway/provider_outbound.py`
    - 新增 `src/gateway/provider_file_ingestion.py`
    - capability backend 新增：
      - `im.entry.menu`
      - `im.entry.payloads`
    - `InternalCapabilityProvider` 新增：
      - `build_entry_menu(...)`
      - `build_entry_payloads(...)`
    - 飞书文件消息若带 `file_key`，会优先尝试真实文件下载并进入统一解析链路
    - 钉钉文件消息若带 `downloadCode + robotCode`，会优先尝试真实文件下载并进入统一解析链路
    - 飞书 / 钉钉统一入口卡片不再只停留在 `/api/v1/*/entry-payloads`，运行时菜单命令已经直接消费 payload 并发送卡片
  - 当前最新验证：
    - 本地全量测试：`495 passed`
    - 本地模拟脚本：`python scripts/simulate_platform_adapter_contracts.py` 通过
    - 模拟脚本新增通过场景：
      - `menu_command_sends_entry_card`

## 下一步建议

1. 飞书真实租户侧菜单 / 欢迎卡片挂载
   - 当前代码和 payload 已就绪
   - 剩余工作是把 `feishu_card` 挂到真实租户配置
2. 钉钉真实租户侧入口卡片挂载
   - 当前 payload 已就绪
   - 剩余工作是把 `dingtalk_card` 挂到真实单聊 / 群聊入口
3. 飞书 / 钉钉真实文件权限与样本联调
   - 当前代码已支持真实下载路径
   - 剩余工作是用真实凭据和真实文件消息样本验证 file_key / downloadCode 字段是否与文档一致
4. 统一 outbound 继续下沉
   - 当前已补 provider-aware outbound 起点
   - 后续可把普通文本、文件回推、入口卡片进一步统一收敛到同一出站服务

## 2026-07-08 集成组件更新审计

- 本轮审计对象：
  - `OfficeCLI`
  - `Stirling-PDF`
  - `OCRmyPDF`
  - `SearXNG`
- 代码侧新增：
  - `scripts/check_integrated_component_updates.py`
  - `tests/test_integrated_component_updates.py`
- 配置侧调整：
  - `infra/stirling-pdf.compose.yml`
  - 从 `stirlingtools/stirling-pdf:latest` 改为 `stirlingtools/stirling-pdf:v2.14.1`
  - 目的：避免 `latest` 漂移，固定到已核对的当前上游版本
- 服务器实际结果：
  - `OfficeCLI`
    - 更新前：`1.0.105`
    - 更新后：`1.0.131`
    - 已完成实际替换安装并验证 `--version`
  - `SearXNG`
    - 当前仍使用 `ghcr.io/searxng/searxng:latest`
    - 服务器 `docker pull` 时访问 `ghcr.io` 返回 EOF
    - 本轮未能完成镜像刷新，阻塞点是外部 registry 连通性
  - `Stirling-PDF`
    - 代码配置已升级到 `v2.14.1`
    - 服务器 `docker pull stirlingtools/stirling-pdf:v2.14.1` 时访问 Docker Hub 出现 TLS handshake timeout
    - 本轮未能完成镜像拉取与容器刷新，阻塞点是外部 registry 连通性
  - `OCRmyPDF`
    - 服务器当前未安装
    - 同时缺少 `tesseract` / `ghostscript` 可执行程序
    - 本轮未直接安装，原因是它不是单一二进制更新，而是完整 OCR 依赖链新增
- 建议后续动作：
  1. 先恢复服务器到 `ghcr.io` / `docker.io` 的稳定拉取能力
  2. 再执行 `docker compose pull && docker compose up -d`
3. 单独评估是否要在测试服务器正式安装 OCRmyPDF 依赖链

## 2026-07-08 三平台接口项目更新审计

- 审计结论：
  - 当前飞书、企微、钉钉接入层都不是“外部接口项目集成”
  - 也没有独立的第三方 SDK 包在 `pyproject.toml` 中被集成
  - 当前三平台都是仓库内自写 HTTP client / adapter：
    - `src/platform/api_wecom.py`
    - `src/platform/api_feishu.py`
    - `src/platform/api_dingtalk.py`
    - `src/gateway/wecom_bot_bridge.py`
    - `src/gateway/adapter_feishu.py`
    - `src/gateway/adapter_dingtalk.py`
- 代码侧新增：
  - `scripts/check_platform_interface_updates.py`
  - `tests/test_platform_interface_updates.py`
- 结果：
  - 企微：无可同步升级的外部接口项目
  - 飞书：无可同步升级的外部接口项目
  - 钉钉：无可同步升级的外部接口项目
- 当前同步内容：
  - 没有做 SDK 升级，因为项目内不存在对应 SDK 依赖
  - 已把官方更新源整理进审计脚本，便于后续人工核对：
    - 企业微信：`https://developer.work.weixin.qq.com/document`
    - 飞书：`https://open.feishu.cn/changelog?lang=zh-CN`
    - 钉钉：`https://open.dingtalk.com/document/isvapp/application-development-update-log-1692847475701`

## 2026-07-08 企业办公工作流助手落地

- 本轮新增四类可直接触发的工作流助手：
  - 审批跟踪助手
  - 会议组织助手
  - 制度 / 周报起草助手
  - 工单分析助手
- 代码侧新增：
  - `src/workflows/office_workflow_service.py`
  - `src/tools/workflow_assistant_tools.py`
  - `data/business_systems/sample_workorders.json`
- 已接入内容：
  - `PersonalAgent` 对典型办公中文意图做快捷路由，不完全依赖模型自由选择工具
  - 工作流结果会同时沉淀到：
    - `ScopedMemoryStore`
    - 知识库条目（通过 `KnowledgeCollector.collect_text(...)`）
  - capability backend 新增：
    - `ops.workorder.lookup`
    - `ops.workorder.analyze`
  - `InternalCapabilityProvider` 新增：
    - `lookup_workorder(...)`
    - `analyze_workorder(...)`
- 当前工作流编排：
  - 审批跟踪会组合：
    - `approval.list`
    - `approval.detail`
    - `docs.read`
    - `mail.summary`
  - 会议组织会组合：
    - `calendar.list`
    - `meeting.list`
    - `docs.read`
  - 制度 / 周报起草会组合：
    - `docs.search`
    - `drive.read`
  - 工单分析会组合：
    - `ops.workorder.lookup`
    - `ops.workorder.analyze`
    - `docs.read`
- 验证：
  - 新增测试：
    - `tests/test_office_workflow_service.py`
    - `tests/test_internal_business_system_provider.py`
  - `tests/test_engine.py` 已覆盖个人 Agent 快捷触发
  - 本地全量测试：`502 passed`
  - 服务器定向测试：
    - `tests/test_office_workflow_service.py`
    - `tests/test_internal_business_system_provider.py`
    - `tests/test_engine.py`
    - `tests/test_capability_backend.py`
    - 共 `49 passed`
  - 服务器用户侧 webhook 话术回归已验证：
    - `帮我跟踪一下付款审批进度`
    - `安排一次部门会议并给我议程建议`
    - `帮我起草一个车间通行管理制度`
    - `分析工单 WO-1001 的异常`
  - 当前表现：
    - 审批 / 会议能力若平台接口未开放，会优雅降级为“暂无能力”而不是返回原始 HTTP 404
    - 工单分析样板已能返回真实样板数据、风险等级和下一步建议

## 2026-07-09 企业应用数据聚合、后台用户管理与模型管理

- 本轮用户反馈：
  - Bot 查询企业微信内置应用数据仍会暴露 `[企业微信] HTTP Error 404: Not Found`，典型场景是“三号会议室有人申请吗？”
  - 需要真正打通企微内置应用、审批流程、第三方应用/内部系统数据，并能汇总多应用结果。
  - 管理员后台需要新增用户管理二级页面：按通讯录组织架构展示用户、在线/活跃状态、AI 助手开通状态、权限角色、日/周/月/年 token 估算，并支持单人/批量开通、暂停、关闭员工 AI 助手。
  - 管理员后台首页需要新增模型管理：配置服务商 URL、API Key、模型名，支持 OpenAI 和 Anthropic SDK 格式，能自动读取模型清单时自动加载，否则允许手工录入。
- 本轮实现：
  - capability backend 新增：
    - `apps.query`
    - `apps.action`
    - `meeting.room.query`
  - `approval.list` 已纳入企微 provider，不再只过滤到飞书/钉钉。
  - `CapabilityBackend.format_results(...)` 现在只把成功 provider 结果返回给用户；失败仍进入 capability audit，但不会把底层 `HTTP 404` 等异常文本直接发给 Bot 用户。
  - `WeComClient` 新增企业应用聚合能力：
    - `query_meeting_room(...)`
    - `query_enterprise_apps(...)`
    - `run_enterprise_app_action(...)`
    - `list_approvals(...)`
  - 飞书/钉钉客户端补齐同名企业应用查询/动作接口，当前无真实租户时可走模拟和已有日程/审批/文档能力。
  - `InternalCapabilityProvider` 新增本地企业应用样例闭环，数据文件：
    - `data/business_systems/sample_enterprise_apps.json`
  - `OfficeWorkflowService` 新增 `enterprise_app_query(...)`，用于把会议室、审批、内置应用、第三方系统查询汇总为一个可读结果。
  - `PersonalAgent` 对“会议室/审批流程/第三方应用/内置应用 + 查询/状态/占用/申请”等意图做快捷路由，优先走企业应用聚合能力。
  - 工具层新增：
    - `builtin:enterprise_app_query`
    - `builtin:enterprise_app_action`
  - 后台新增用户管理服务：
    - `src/platform/user_management_service.py`
    - `GET /api/v1/admin/users`
    - `POST /api/v1/admin/employee-bots/status`
    - `POST /api/v1/admin/employee-bots/batch`
  - 员工 AI 助手状态支持：
    - `active`
    - `paused`
    - `disabled`
  - 后台新增模型管理服务：
    - `src/platform/model_management_service.py`
    - `GET /api/v1/admin/models`
    - `POST /api/v1/admin/models`
    - `POST /api/v1/admin/models/discover`
  - `/admin/console` 新增两个真实可交互标签：
    - `用户管理`
    - `模型管理`
  - `.gitignore` 新增 `.omx/`，避免本地自动化上下文进入可发布代码。
- 验证：
  - 定向测试：
    - `python -m pytest tests/test_capability_backend.py tests/test_wecom_platform_api.py tests/test_office_workflow_service.py tests/test_admin_console.py tests/test_admin_user_and_model_services.py tests/test_engine.py tests/test_platform_capability_tools.py -q`
    - 结果：`85 passed`
  - 本地编译：
    - `python -m compileall -q src tests scripts`
    - 结果：通过
  - 本地全量测试：
    - `python -m pytest -q`
    - 结果：`514 passed`
  - diff 检查：
    - `git diff --check`
    - 结果：通过，仅存在 Git 换行提示
- 真实环境注意事项：
  - 企微会议室、审批和部分第三方应用 API 是否可返回真实数据，仍取决于企业微信后台是否给当前 AI 助手应用授予对应应用/流程的数据读取权限。
  - 代码侧已做到：有权限时走真实 provider，无权限或接口不可用时记录审计并返回中文可操作提示，不再向用户暴露原始 HTTP 404。
## 2026-07-09 卡住任务恢复与真实数据边界修正

- 已恢复并完成上次中断的企微企业应用、用户管理和模型管理任务验证。
- 修正了企业应用样例数据可能在生产环境被误当成真实结果的问题：
  - `InternalCapabilityProvider` 的会议室、审批和第三方应用样例数据默认关闭。
  - 仅在显式设置 `ANT_COLONY_ENABLE_SAMPLE_BUSINESS_DATA=true` 时用于本地或飞书/钉钉模拟测试。
  - 生产环境不会用样例数据替代真实企业应用结果。
- 企微会议室查询现在保留接口诊断：
  - 真实接口有数据时返回真实占用记录。
  - 企业应用缺少权限并返回 `48002 api forbidden` 时，向用户明确说明缺少会议室/会议/日程只读权限。
  - 租户没有可用接口时明确说明未获得真实数据，不再错误回答“没有占用记录”。
- 本地恢复验证：
  - 定向测试 `48 passed`。
  - 最终本地完整回归 `518 passed`。
  - 测试服务器完整回归 `518 passed`。
  - 测试服务器网关和管理后台健康检查通过。
  - 真实网关消息“`三号会议室有人申请吗？`”已验证：不再返回 HTTP 404，不使用样例数据；当前租户因企微应用权限不足返回准确的 `48002` 诊断。
  - 企微后台补充会议室、会议和日程只读权限后，同一链路会直接返回真实数据，无需再次修改代码。
## 2026-07-09 企业应用领域化查询与用户权限过滤

- 根因：
  - 用户实际连接的 `ant-colony-wecom-bot.service` 自 7 月 8 日起未重启，仍运行旧代码，因此继续返回本地样例会议室和付款审批数据。
  - 旧规则把通用词“申请”同时路由到会议室和审批，造成跨应用数据污染。
  - 会议室名称正则把“哪个会议室”误识别成具体房间，无法正确执行可用性查询。
  - 所有企微领域共用 `WECOM_SECRET`，无法适配审批、会议/日程、文档、通讯录分别授权的实际情况。
- 新增统一查询组件：
  - `src/platform/enterprise_query.py`
  - `src/platform/application_registry.py`
  - `src/platform/enterprise_query_service.py`
- 当前行为：
  - 每次请求结构化为领域、操作、实体、日期、用户范围和是否允许跨域。
  - 单领域请求只调用对应 capability；只有“汇总、综合、所有应用、跨应用”等明确表达才跨域。
  - 支持“申批”等常见错字和“进入车间申请是什么情况”等模糊表达。
  - “哪个会议室今天可以申请”使用会议室清单和预订记录计算并显示已占用时段，不再依赖文字样例。
  - 审批先获取审批编号与详情，再按当前用户是申请人、审批人或企业管理员过滤。
  - 企业应用目录按用户和部门可见范围过滤。
  - 查询结果包含 provider 来源和查询时间；权限不足、无匹配数据和接口失败分别反馈。
  - 生产环境样例应用数据仍默认关闭。
- 分领域企微凭据：
  - 审批：`WECOM_APPROVAL_SECRET`
  - 会议：`WECOM_MEETING_SECRET`
  - 日程：`WECOM_CALENDAR_SECRET`
  - 文档：`WECOM_DOCS_SECRET`
  - 通讯录：`WECOM_CONTACT_SECRET`
  - 应用目录：`WECOM_APPLICATION_SECRET`
  - 对应专用凭据缺失时回退 `WECOM_SECRET`。
- 权限边界：
  - 平台应用 Secret 决定 AI 平台能否调用某领域接口。
  - 当前 IM 用户、部门和角色决定返回数据的可见范围。
  - 代码不能绕过企业管理员尚未授予的企微接口权限，也不能用一个通用 API 读取任意第三方应用内部数据。
  - 第三方应用必须提供开放 API 并登记 connector；未接入时只显示应用可见性，不伪造业务数据。
- 服务器真实回放：
  - “三号会议室有人申请吗？”只进入会议室领域，不再包含付款审批或样例数据。
  - “哪个会议室今天可以申请”与具体会议室查询使用同一真实数据源；当前因接口权限不足均准确返回 `48002`。
  - “目前进入车间申请是什么情况”正确进入审批领域。
  - “查询我所有审批的状态”只进入审批领域。
  - 当前服务器审批 API 返回 `no approval auth`，已转换为中文权限提示，不再暴露开发者 URL。
- 服务重启：
  - `ant-colony-gateway.service`
  - `ant-colony-callback.service`
  - `ant-colony-wecom-bot.service`
  - `ant-colony-dashboard.service`
- 最终验证：
  - 领域查询与三端定向回归：`134 passed`
  - 本地完整回归：`545 passed`
  - 测试服务器完整回归：`545 passed`
  - 服务器四个服务状态：`active`
  - 真实网关回放不再出现 `[系统能力]` 样例应用数据，不再混入未请求领域。
  - 真实网关回放不再出现 [系统能力] 样例应用数据，不再混入未请求领域。

## 2026-07-09 完整工作日志

### 架构决策要点

- **LLM 理解取代死词匹配**：入口指令不再用关键词预拦截（仅保留<=3字清晰命令），改为 LLM 自然理解 + get_entry_link 工具
- **用户上下文全局注入**：所有工具调用都注入 from + user_id（原仅 generate_document）
- **管理员范围区分**："我的审批"过滤本人记录，"所有审批"管理员可看全部
- **Fluent Design UI**：三个后台页面改用 Win11 Fluent Design（#0078d4 主色）
- **令牌时效 1h 改为 24h**：避免管理员会话中途过期

### 1. 企微接口权限打通

完成授权：应用管理->会议室，协作->日程/会议，审批接口->开启。审批返回 10 条真实数据，会议室返回 5 间真实房间。

### 2. 会议室代码修复（api_wecom.py）

- query_meeting_room() 重写：新增 oa/meetingroom/list 调用，房间名模糊匹配
- 新增 _extract_numbers() 和 _fuzzy_name_match()（字符集重叠匹配，允许一字之差）
- 修复 _format_room_payload/availability 缺少 meetingroom_list 键
- 修复 list_meetings() 接口路径：404 -> meeting/list

### 3. 审批姓名解析（api_wecom.py）

- WeCom 审批 API 只返回 userid，不返回中文名
- 新增 _batch_resolve_user_names() 通过 user/get 批量翻译 userid 到中文名
- 修复 Secret 选择：user/get 用通用 WECOM_SECRET

### 4. 管理员个人/全部审批区分（api_wecom.py）

- list_approvals() 新增 force_personal："我的审批"只看本人
- _approval_matches() 增加 target_userid 参数和字符集模糊匹配
- 修复空 applicant_uid 导致的 "" in text 永远为 True 的 bug

### 5. 用户上下文全局注入（engine/base.py + org_admin_tools.py）

- 引擎 _execute_tool_calls() 改为所有工具调用都注入 from + user_id
- org_admin_tools.py 新增 _resolve_user_id()，修复全部 6 个函数

### 6. 知识库管理页功能增强（dashboard.py）

- 组织目录节点可点击，点击后过滤对应范围的知识文档
- 新增入库范围下拉框（动态填充用户可写范围）
- 文件上传支持批量选择，显示标签、摘要、入库范围
- API 新增 tags / content_preview / owner_type / owner_id 字段

### 7. 管理员控制台增强（dashboard.py）

- 用户管理：搜索框（部门/姓名/user_id），表头点击排序
- 员工 AI 助手：按姓名检索用户 + 专属 rename API（不重置 scope/permissions）
- 员工列表显示中文名，乱码名自动检测修复，通知列中文状态码

### 8. 全页 UI 升级：Win11 Fluent Design

覆盖 /knowledge/manage, /knowledge/user, /admin/console, /platform/bots/manage
- 色板 #0078d4（主色），按钮 4px 圆角矩形（原 999px 胶囊）
- 导航栏 acrylic 毛玻璃，输入框聚焦蓝色光晕
- 表格 2px 表头 + hover 高亮行

### 9. 入口链接 LLM 化（gateway/ + builtin.py）

- inbound_service.py：删除硬编码关键词预拦截，仅拦截<=3字命令
- builtin.py：新增 get_entry_link 工具（target=admin/knowledge/menu）
- base.py：提示词第 5 条告知 LLM 入口请求时调用 get_entry_link

### 10. 服务器目录清理

- 清理 14 项畸形残留，磁盘从 ~500MB 降至 111MB

### 验证状态

- 本地全量测试：545 passed
- 服务器全量测试：545 passed
- 管理员令牌验证通过，HMAC 签名，24h TTL
- 企微真实出站：text/file_card/file_send 均正常

### 待解决问题

1. 会议室预定 API bookinfo/get 需 booking_id + meetingroom_id，跨天查询不支持（已修复：当日时间范围）
2. 文档搜索 404 — doc/search 已弃用，已改为 wedoc/create_doc 路径
3. 日历 API 缺 cal_id — 已修复：`_get_app_calendar_id()` 懒创建默认日历
4. 项目知识库需将群聊注册为 SpaceRegistry 的 project 空间 — 已提供 `POST /api/v1/admin/projects/register`
5. 飞书/钉钉缺真实凭据（代码就绪，文档已标注）
6. 令牌非真正一次性：基于 TTL（24h），非浏览器会话级（`session_id`+ 服务端黑名单待实现）
7. 会议 API `meeting/list` 返回 730007（可能企业未开通会议功能）
8. 管理员控制台首次访问，用户要先从 Bot 获取最新链接，或打开过期链接后点击"刷新链接"恢复

### 后续建议

1. 调查会议室预定 API 600018（时区/专用 Secret）
2. 修复文档搜索和日历 API 路径
3. 管理员将协作群注册为项目空间
4. 实现 session_id + 服务端黑名单的一次性链接
5. 准备飞书/钉钉真实凭据做三端联调

## 2026-07-10 全链路修复：6 个阻塞点 + 链接刷新 + 工具调用格式容错

### 阻塞点修复

| # | 阻塞点 | 根因 | 修复 |
|---|--------|------|------|
| 1 | 会议室 600018 | WeCom API 不支持跨天查询 | 改为当日 0:00-23:59 + meetingroom_id |
| 2 | 日历 cal_id | 无默认日历 | `_get_app_calendar_id()` 懒创建 "AI 助手日程" 并缓存 |
| 3 | 文档搜索 404 | doc/search 路径过时 | create_doc 改为 wedoc/create_doc |
| 4 | 链接一次性 | 令牌无 jti | 所有令牌加 UUID + `_revoked_jtis` 服务端黑名单 |
| 5 | 项目空间 | 缺注册入口 | `POST /api/v1/admin/projects/register` |
| 6 | 飞书/钉钉 | 缺真实凭据 | 代码就绪，文档标注 |

### 管理员控制台鉴权修复

管理员控制台显示"未验证"的完整诊断流程：

1. `platform_admins` 表有 3 人（MaGe/cherryyu/LiuKeFeng），`ANT_COLONY_ADMIN_SESSION_SECRET` 已配置
2. 服务端 Python 验证：token 生成→`_verify_admin_console_token`→签名匹配→`is_platform_admin`→True——全链路通过
3. 用户问题：浏览器持旧链接过期（令牌 TTL=24h），刷新页面后 JS init 调用 `/api/v1/admin/profile` 返回 401
4. 原 JS catch 只显示"验证失败"，无恢复手段

修复：

- `POST /api/v1/admin/refresh-token`：接受已到期但 HMAC 有效的旧令牌，签发新令牌
- JS init catch 块新增"刷新链接"按钮，点击自动请求 refresh-token 并用新令牌重载页面
- `admin_auth.py` 新增 `decode_and_refresh_admin_token()`

### 工具调用格式容错

用户反馈 Bot 返回 `<tool_call>{"target": "admin"}` 原始文本而非执行结果。

- 根因：`_extract_tool_calls` 要求 `<tool_call>工具id(json参数)</tool_call>` 格式，LLM 只输 JSON 省了工具名，解析失败后原样回传
- 修复：
  - 提示词示例强化：增加带参数格式示例 `builtin:get_entry_link({"target": "admin"})`
  - `process_text` 新增自动重试：检测到未解析的 `<tool_call>` 标签时，将正确格式反馈给 LLM 重新生成
  - `_inject_tools` 明确提示 "工具id必须写完整，括号和参数不能省略"

### 安全补丁

- `_get_entry_link_tool()` 增加 `is_platform_admin` 检查：非管理员请求 admin 控制台时返回中文拒绝提示
- `_execute_tool_calls()` 增加 `_source_provider` 和 `_source_transport` 注入：原仅 `generate_document` 工具获得平台信息，其他工具（如 `get_entry_link`）只能兜底 `wecom`

### 数据库环境勘误

- 服务器数据库路径为 `data/ant-colony.db` 而非 `data/colony.db`（后者在任何服务中均未使用）
- `platform_admins` 表包含 3 名注册管理员

### 验证

- 本地全量测试：545 passed
- 服务器全量测试：545 passed
- auth 服务端自验：token 生成→验证签名→is_platform_admin→True→API 返回 `can_activate_bots: true`

## 2026-07-10 管理员控制台入口 wecom_bot 平台别名修复

- 现象：
  - 用户在企微 Bot 中发送“管理员控制台”后，Bot 返回工具执行失败：
    - `400: 不支持的平台：wecom_bot`
  - 报错链路：
    - `builtin:get_entry_link`
    - `is_platform_admin(platform, user_id)`
    - `admin_auth._normalize_platform("wecom_bot")`
- 根因：
  - WeCom Bot 通道在消息上下文里传入的是通道标识 `wecom_bot`。
  - `entry_links._normalize_platform()` 和 `capability_backend._platform_provider_id()` 已支持 `wecom_bot -> wecom`。
  - 但 `src/web/admin_auth.py` 的 `_normalize_platform()` 只接受 `wecom/feishu/dingtalk`，导致管理员权限判断和 token 生成失败。
  - 第一轮修复后发现 URL query 仍保留 `platform=wecom_bot`，浏览器打开后台后仍可能在后续 API 鉴权中失败。
- 修复：
  - `src/web/admin_auth.py`
    - `_normalize_platform()` 增加平台通道别名：
      - `wecom_bot/wecom_bot_ws/wecom_callback/企业微信/企微 -> wecom`
      - `feishu_bot/lark/lark_bot/飞书 -> feishu`
      - `dingtalk_bot/钉钉 -> dingtalk`
  - `src/gateway/entry_links.py`
    - `_admin_reply()`、`_knowledge_reply()`、`_menu_reply()`、`_admin_url()`、`_knowledge_url()` 在生成链接前统一归一化平台。
    - 确保 Bot 工具传入 `_source_provider=wecom_bot` 时，最终链接 query 为 `platform=wecom`。
  - `tests/test_entry_link_commands.py`
    - 新增回归测试 `test_builtin_entry_link_accepts_wecom_bot_provider_alias`。
    - 精确解析 URL query，确认 `platform == wecom`。
- 本地验证：
  - `python -m pytest tests/test_entry_link_commands.py tests/test_inbound_entry_links.py tests/test_admin_console.py tests/test_web_auth.py -q`
  - 结果：`41 passed`
  - `python -m pytest tests/test_engine.py tests/test_basic_tool_modules.py tests/test_capability_backend.py -q`
  - 结果：`53 passed`
  - `python -m compileall -q src tests`
  - 结果：通过
- 服务器验证：
  - 已同步：
    - `src/web/admin_auth.py`
    - `src/gateway/entry_links.py`
    - `tests/test_entry_link_commands.py`
  - 远端定向测试：
    - `python3 -m pytest tests/test_entry_link_commands.py::test_builtin_entry_link_accepts_wecom_bot_provider_alias -q`
    - 结果：`1 passed`
  - 远端工具模拟：
    - `_source_provider=wecom_bot` 生成链接：
      - `<dashboard-public-base-url>/admin/console?platform=wecom&user_id=<admin-user-id>...`
  - 已重启：
    - `ant-colony-dashboard.service`
    - `ant-colony-wecom-bot.service`
    - `ant-colony-gateway.service`
  - 服务状态：
    - 三个服务均为 `active`

## 2026-07-10 管理员控制台仍显示“未验证”的最终兜底修复
- 现象：
  - `/api/v1/admin/profile` 用 Bot 返回链接中的 `platform/user_id/admin_token` 调用已经返回 HTTP 200。
  - 但用户在企业微信内置浏览器打开 `/admin/console?...` 后仍看到“未验证”，页面按钮不可用。
- 进一步根因：
  - 后端 token、管理员权限和 systemd 环境已经正常。
  - 页面首屏原本依赖前端 JS 调用 `/api/v1/admin/profile` 后再把“未验证”改成已验证身份。
  - 企业微信内置浏览器可能因为旧 WebView、缓存或主脚本解析失败，导致没有发出 profile 请求，页面停留在初始“未验证”。
- 修复：
  - `src/web/dashboard.py`
    - `/admin/console` 路由增加服务端首屏验证。
    - 读取 URL query 中的 `platform/user_id/admin_token`，直接调用 `require_admin_context_from_request()`。
    - 验证通过时，服务端返回的 HTML 初始身份区域直接渲染为 `platform / user_id / role`，不再依赖浏览器 JS 执行。
    - 保留 ES5 `XMLHttpRequest` 预验证脚本作为前端二次兜底，兼容不支持 `fetch/async/const` 的旧 WebView。
    - `request` 参数保持测试兼容，单元测试直接调用页面函数时仍返回默认页面。
- 本地验证：
  - `python -m pytest tests/test_admin_console.py tests/test_entry_link_commands.py tests/test_inbound_entry_links.py tests/test_web_auth.py -q`
  - 结果：`43 passed`
  - `python -m compileall -q src tests`
  - 结果：通过
- 服务器验证：
  - 已同步并重启：
    - `ant-colony-dashboard.service`
  - 服务器内真实链路：
    - POST `http://127.0.0.1:18090/`，payload 为 `content=管理员控制台`、`provider=wecom_bot`。
    - 返回链接为 `<dashboard-public-base-url>/admin/console?platform=wecom&user_id=<admin-user-id>&admin_token=...`。
    - 打开该链接对应页面时，HTML 首屏已包含 `wecom / MaGe / admin`。
    - 页面不再包含 `<div id="identity" class="chip">未验证</div>`。
    - `/api/v1/admin/profile` 返回 HTTP 200，`platform=wecom`、`user_id=MaGe`、`role=admin`。
  - 服务器回归：
    - `python3 -m pytest tests/test_admin_console.py tests/test_entry_link_commands.py tests/test_inbound_entry_links.py tests/test_web_auth.py -q`
    - 结果：`43 passed`
    - `python3 -m compileall -q src tests`
    - 结果：通过
- 后续注意：
  - 如果用户仍看到旧“未验证”，优先让用户从 Bot 重新发送“管理员控制台”获取新链接，不要复用旧缓存页面。
  - 当前首屏验证已经不依赖 JS；若仍异常，应检查企业微信是否打开了旧缓存 URL 或网络代理是否访问到旧服务实例。

## 2026-07-10 管理员控制台打开后“未验证”修复

- 现象：
  - Bot 已能返回管理员控制台链接。
  - 浏览器打开 `/admin/console?...` 后页面显示“未验证”，按钮不可操作。
- 根因：
  - `ant-colony-gateway.service` 和 `ant-colony-wecom-bot.service` 加载了：
    - `<server-workdir>/infra/.env.wecom`
  - `ant-colony-dashboard.service` 未加载该 EnvironmentFile。
  - `infra/.env.wecom` 中存在 `ANT_COLONY_ADMIN_SESSION_SECRET`。
  - 因此 Bot/网关生成 admin token 时使用一个 secret，Dashboard 验证 token 时进程环境里没有同一个 secret，导致 `/api/v1/admin/profile` 返回 401，页面显示“未验证”。
- 修复：
  - `src/web/admin_auth.py`
    - `_admin_secret()` 在进程环境变量为空时，自动读取：
      - `./infra/.env.wecom`
      - `$ANT_COLONY_HOME/infra/.env.wecom`
      - `~/ant-colony/infra/.env.wecom`
    - 支持读取 `ANT_COLONY_ADMIN_SESSION_SECRET` 或 `ANT_COLONY_AUTH_TOKEN`。
  - `tests/test_admin_console.py`
    - 新增 `test_admin_console_token_uses_wecom_env_file_when_process_env_missing`，覆盖 Dashboard 进程缺环境变量、仅有 `infra/.env.wecom` 的验证场景。
  - 服务器 systemd：
    - `/etc/systemd/system/ant-colony-dashboard.service` 增加：
      - `EnvironmentFile=<server-workdir>/infra/.env.wecom`
    - 已执行 `systemctl daemon-reload` 并重启 dashboard/gateway/wecom-bot。
- 本地验证：
  - `python -m pytest tests/test_admin_console.py tests/test_entry_link_commands.py tests/test_inbound_entry_links.py tests/test_web_auth.py -q`
  - 结果：`43 passed`
  - `python -m compileall -q src tests`
  - 结果：通过
- 服务器验证：
  - 服务状态：
    - `ant-colony-dashboard.service`: `active`
    - `ant-colony-gateway.service`: `active`
    - `ant-colony-wecom-bot.service`: `active`
  - 真实链路：
    - POST `http://127.0.0.1:18090/` 生成管理员控制台链接。
    - 用该链接中的 `platform/user_id/admin_token` 调用：
      - `http://127.0.0.1:18092/api/v1/admin/profile`
    - 返回：
      - HTTP `200`
      - `platform=wecom`
      - `user_id=MaGe`
      - `role=admin`
      - `can_activate_bots=True`
  - 远端回归：
    - `python3 -m pytest tests/test_admin_console.py tests/test_entry_link_commands.py tests/test_inbound_entry_links.py tests/test_web_auth.py -q`
    - 结果：`43 passed`
  - 远端编译：
    - `python3 -m compileall -q src tests`
    - 结果：通过

## 2026-07-10 管理员控制台入口无响应修复

- 现象：
  - 用户在企微 Bot 中再次发送“管理员控制台”后，聊天窗口没有收到回复。
- 日志证据：
  - `ant-colony-gateway.service` 17:24 已收到“管理员控制台”。
  - 旧链路先做知识库预检索，再进入 LLM。
  - 17:25 LLM 返回空文本：
    - `[ENGINE] LLM reply len=0 tool_call=False first100=`
  - 网关 `POST /` 返回 200，但由于 response text 为空，企微侧没有可发送内容。
- 根因：
  - `src/gateway/inbound_service.py` 只前置拦截 `菜单` 这类 1-3 字命令。
  - `管理员控制台`、`打开知识库` 等入口命令被放给 LLM 自然理解。
  - 管理入口属于确定性系统命令，不应依赖模型工具调用或模型返回稳定性。
- 修复：
  - `src/gateway/inbound_service.py`
    - 对个人消息先调用 `build_entry_link_reply(...)`。
    - 只要匹配管理员控制台、知识库、菜单等入口命令，立即返回链接。
    - 不创建 PersonalAgent，不进入知识库预检索，不调用 LLM。
  - `tests/test_inbound_entry_links.py`
    - 新增“管理员控制台”不走 LLM 的回归测试。
    - 新增“打开知识库”不走 LLM 的回归测试。
- 本地验证：
  - `python -m pytest tests/test_inbound_entry_links.py tests/test_entry_link_commands.py tests/test_admin_console.py tests/test_web_auth.py -q`
  - 结果：`42 passed`
  - `python -m compileall -q src tests`
  - 结果：通过
- 服务器验证：
  - 已同步：
    - `src/gateway/inbound_service.py`
    - `tests/test_inbound_entry_links.py`
  - 远端测试：
    - `python3 -m pytest tests/test_inbound_entry_links.py tests/test_entry_link_commands.py -q`
    - 结果：`12 passed`
  - 远端真实网关模拟：
    - POST `http://127.0.0.1:18090/`
    - payload:
      - `from_user_id=MaGe`
      - `content=管理员控制台`
      - `provider=wecom_bot`
    - 返回：
      - `route_kind=personal`
      - `reply=管理员控制台入口：...platform=wecom&user_id=MaGe...`
  - 已重启：
    - `ant-colony-gateway.service`
    - `ant-colony-wecom-bot.service`
    - `ant-colony-dashboard.service`
  - 服务状态：
    - 三个服务均为 `active`
## 2026-07-13 企业微信机器人 MCP 文档/待办能力集成
- 背景：
  - 企业微信测试机器人已开通“文档”和“待办”可使用权限。
  - 两个能力均通过企业微信提供的 MCP Streamable HTTP URL 调用。
  - URL 中包含 apikey，属于敏感凭据；本地代码、GitHub 代码、说明文档和交接文档均不得记录真实 URL。
- 本次实现：
  - 新增 `src/platform/wecom_robot_mcp_provider.py`
    - 实现轻量 Streamable HTTP MCP 客户端。
    - 支持 `initialize`、`notifications/initialized`、`tools/list`、`tools/call`。
    - 支持 JSON 和 `text/event-stream` 响应解析。
    - 所有 HTTP 错误和状态展示均对 `apikey` 脱敏，避免写入页面、日志或 capability audit。
  - 扩展 `src/platform/capability_backend.py`
    - 新增文档能力：
      - `docs.edit`
      - `docs.smartpage.create`
      - `sheet.append`
    - 新增待办能力：
      - `todo.create`
      - `todo.list`
      - `todo.detail`
      - `todo.update`
      - `todo.delete`
      - `todo.user.search`
      - `todo.user_status.change`
    - `docs.create` 现在支持 `wecom_robot_mcp`，并保留旧企微 API fallback。
    - 企微平台请求会把 `wecom_robot_mcp` 纳入平台作用域 provider。
  - 扩展 `src/platform/__init__.py`
    - 新增 `wecom_robot_mcp` provider。
    - provider 顺序调整为 `wecom_robot_mcp` 优先，旧 `wecom` provider 作为 fallback。
  - 扩展 `src/tools/platform_capability_tools.py` 与 `src/tools/builtin.py`
    - 新增 Bot 工具：
      - `builtin:smartpage_create`
      - `builtin:edit_doc_content`
      - `builtin:sheet_append`
      - `builtin:todo_create`
      - `builtin:todo_list`
      - `builtin:todo_update`
      - `builtin:todo_user_search`
  - 扩展管理员后台 `src/web/dashboard.py`
    - 新增“企微 MCP”页签。
    - 支持查看文档/待办 MCP 配置状态。
    - 支持管理员粘贴 StreamableHttp URL 并保存到服务器配置。
    - 支持“发现 MCP 工具”，用于检查真实工具清单。
    - 页面包含获取 URL 的操作引导和 apikey 安全提示。
  - 新增/更新测试：
    - `tests/test_wecom_robot_mcp_provider.py`
    - `tests/test_capability_backend.py`
    - `tests/test_admin_console.py`
- 服务器配置：
  - 真实 MCP URL 已仅写入测试服务器：
    - `<server-workdir>/infra/.env.wecom`
  - 使用的环境变量名：
    - `WECOM_ROBOT_DOC_MCP_URL`
    - `WECOM_ROBOT_TODO_MCP_URL`
  - 已重启：
    - `ant-colony-dashboard.service`
    - `ant-colony-gateway.service`
    - `ant-colony-wecom-bot.service`
  - 三个服务状态均为 `active`。
- 真实服务器验证：
  - MCP 工具发现成功：
    - 文档工具包括 `create_doc`、`edit_doc_content`、`smartpage_create`、`sheet_append_data`、智能表格相关工具等。
    - 待办工具包括 `get_todo_list`、`create_todo`、`update_todo`、`get_todo_detail`、`delete_todo`、`change_todo_user_status`、`search_todo_userid`。
  - `todo.list` 真实调用成功，返回 `errcode=0`。
  - `docs.create` 真实调用成功，返回企业微信在线文档链接和 `docid`。
  - `docs.create` 后续调用 `edit_doc_content` 写入正文成功，返回 `errcode=0`。
  - `todo.create` 真实创建测试待办成功，随后 `todo.delete` 删除成功，均返回 `errcode=0`。
- 回归验证：
  - 本地：
    - `python -m pytest tests/test_wecom_robot_mcp_provider.py tests/test_capability_backend.py tests/test_admin_console.py tests/test_entry_link_commands.py tests/test_inbound_entry_links.py tests/test_web_auth.py -q`
    - 结果：`69 passed`
    - `python -m compileall -q src tests`
    - 结果：通过
  - 服务器：
    - `python3 -m pytest tests/test_wecom_robot_mcp_provider.py tests/test_capability_backend.py tests/test_admin_console.py tests/test_entry_link_commands.py tests/test_inbound_entry_links.py tests/test_web_auth.py -q`
    - 结果：`69 passed`
    - `python3 -m compileall -q src tests`
    - 结果：通过
- 后续注意：
  - 不要把真实 MCP URL 写入 GitHub。
  - 如果 MCP URL 泄露，应在企业微信机器人权限页面重置配置，并通过管理员后台“企微 MCP”页签重新导入。
  - 后续可进一步增强自然语言参数抽取，例如把“明天下午 3 点”标准化为 `YYYY-MM-DD HH:mm:ss` 后再调用 `todo.create`。

## 2026-07-13 管理员页面补充企微 MCP 使用说明
- 用户反馈：
  - 需要在管理页面直接说明“企微文档 MCP”和“企微待办 MCP”启用后机器人可以做什么，以及用户应该如何向机器人发起指令。
- 本次更新：
  - `src/web/dashboard.py`
    - 在管理员控制台“企微 MCP”页签补充文档能力交互示例：
      - 创建企微在线文档。
      - 创建企业微信智能文档。
      - 向企微表格追加数据。
    - 补充待办能力交互示例：
      - 创建待办。
      - 查询本人待办。
      - 修改待办状态。
      - 搜索待办参与人 userid。
    - 补充当前测试服务器已验证能力：
      - 文档 MCP 可创建企微在线文档并写入正文。
      - 待办 MCP 可查询、创建和删除机器人创建的待办。
    - 补充时间格式提示：
      - 当前建议优先使用 `YYYY-MM-DD HH:mm` 等明确时间。
      - 后续可继续增强“明天下午3点”等口语时间解析。
- 验证：
  - 本地：
    - `python -m pytest tests/test_admin_console.py -q`
    - 结果：`23 passed`
    - `python -m compileall -q src/web/dashboard.py`
    - 结果：通过
  - 服务器：
    - 已同步 `src/web/dashboard.py`
    - 已重启 `ant-colony-dashboard.service`
    - 页面源码确认包含新增说明。
    - `python3 -m pytest tests/test_admin_console.py -q`
    - 结果：`23 passed`

## 2026-07-13 管理员控制台身份通过但菜单无响应修复

- 用户反馈：
  - 管理员控制台身份和权限认证已经通过。
  - 首页其他模块一直显示“等待加载”。
  - 左侧菜单点击没有反应。
- 诊断结果：
  - 服务器日志显示 `/admin/console` 和 `/api/v1/admin/profile` 均返回 `200`。
  - profile 之后没有继续请求 `/api/v1/admin/platform/bots`、`/api/v1/admin/employee-bots`、`/api/v1/admin/users` 等初始化接口。
  - Playwright 打开真实服务器页面后捕获到浏览器错误：
    - `Invalid regular expression: /[^�-]/: Range out of order in character class`
    - 后续点击左侧菜单又触发 `showTab is not defined`
  - 根因是 `src/web/dashboard.py` 内联脚本中用于判断乱码显示名的 `/[^\x00-\x7F]/` 正则被 Python 三引号字符串转义成了实际控制字符，Chrome / 企业微信内置浏览器解析正则失败，导致主脚本整体中断。
- 修复内容：
  - `src/web/dashboard.py`
    - 新增 `hasNonAscii(value)`，通过 `charCodeAt(0) > 127` 判断非 ASCII 字符。
    - 将乱码判断从正则改为 `!hasNonAscii(displayName)`，避免 HTML 内联脚本中出现控制字符。
  - `tests/test_admin_console.py`
    - 在内联脚本语法检查测试中增加 `"\x00" not in body` 断言，防止再次把控制字符写入页面脚本。
- 验证结果：
  - 本地：
    - `python -m pytest tests/test_admin_console.py -q`
    - 结果：`23 passed`
    - `python -m compileall -q src/web/dashboard.py`
    - 结果：通过
  - 服务器：
    - 已同步 `src/web/dashboard.py`
    - 已同步 `tests/test_admin_console.py`
    - `python3 -m pytest tests/test_admin_console.py -q`
    - 结果：`23 passed`
    - `python3 -m compileall -q src/web/dashboard.py`
    - 结果：通过
    - 已重启 `ant-colony-dashboard.service`
  - 真实浏览器验证：
    - 使用 Playwright + 本机 Chrome 打开测试服务器管理员控制台。
    - `identity = wecom / MaGe / admin`
    - `platformSummary = 已启用平台：1 / 总平台：3`
    - `runtimeSummary = 可达端口：4 / healthy`
    - `userStats = 总计 129 人 / 已开通 3`
    - `window.showTab` 已恢复为 `function`
    - 点击左侧“用户管理”后，active section 正确切换为 `users`。

## 2026-07-13 全面扫描复查与管理员控制台二次加固

- 本轮目标：
  - 对本地代码做一次广度和深度复查，确认是否还有可直接修复的 bug 和明确优化项。
  - 重点检查管理员控制台、企业微信 MCP、三端入口、能力后端、知识库和公开文档。
- 已执行检查：
  - `git status --short`
    - 结果：开始扫描前工作区干净。
  - `python -m compileall -q src tests`
    - 结果：通过。
  - `python -m pytest -q`
    - 结果：`556 passed`。
  - 敏感信息扫描：
    - 检查 `github_pat_`、`lsv2_`、真实 `apikey`、测试服务器 IP、服务器绝对路径等。
    - 结果：代码和说明文档中未发现真实 GitHub / LangSmith / MCP key；仅测试文件保留 fake apikey。
- 已修复问题 1：管理员控制台动态按钮参数转义不完整
  - 风险：
    - 用户 ID、员工姓名、模型 ID 中如果包含单引号、双引号等特殊字符，原来通过字符串拼接写入 `onclick`，可能造成按钮点击失败或前端脚本注入风险。
  - 修复：
    - `src/web/dashboard.py`
      - 新增 `jsString(value)`，用 `JSON.stringify` 生成 JS 字符串字面量。
      - 新增 `jsAttr(value)`，在写入 HTML 属性前再做 HTML attribute escape。
      - 修复员工 AI 助手编辑、用户管理单人开通/暂停/关闭、模型选择、按姓名选择员工等动态按钮。
      - 修复错误提示颜色变量，从不存在的 `--md-error/--md-muted` 改为现有 `--error/--text-secondary`。
    - `tests/test_admin_console.py`
      - 增加 `test_admin_console_dynamic_actions_use_js_string_arguments`，防止重新退回不安全拼接。
  - 浏览器专项验证：
    - 使用 Playwright + Chrome 构造 `user_id = u'bad"id`、`name = 张'三"`。
    - 生成的按钮属性为合法 `setOneUserBot("u'bad\\\"id",'active')`。
    - 点击后能进入后端请求阶段，未再触发脚本语法错误。
- 已修复问题 2：公开交接文档仍包含测试服务器部署信息
  - 风险：
    - `docs/handoff.md` 中仍存在测试服务器 IP、服务器绝对路径和具体用户路径，不适合发布到 GitHub。
  - 修复：
    - 将具体测试服务器公开访问地址替换为 `<dashboard-public-base-url>`。
    - 将具体服务器工作目录替换为 `<server-workdir>`。
    - 保留运维语义，不暴露具体私有部署信息。
- 本地验证：
  - `python -m pytest tests/test_admin_console.py -q`
    - 结果：`24 passed`
  - `python -m compileall -q src tests`
    - 结果：通过
  - `python -m pytest -q`
    - 结果：`556 passed`
  - 敏感信息复扫：
    - 仅测试文件仍包含 fake apikey。
- 服务器验证：
  - 已同步：
    - `src/web/dashboard.py`
    - `tests/test_admin_console.py`
    - `docs/handoff.md`
  - 远端测试：
    - `python3 -m pytest tests/test_admin_console.py -q`
    - 结果：`24 passed`
    - `python3 -m compileall -q src/web/dashboard.py tests/test_admin_console.py`
    - 结果：通过
  - 已重启：
    - `ant-colony-dashboard.service`
  - 真实浏览器验证：
    - `identity = wecom / MaGe / admin`
    - `platformSummary = 已启用平台：1 / 总平台：3`
    - `runtimeSummary = 可达端口：4 / healthy`
    - 点击“用户管理”后 active section 正确切换为 `users`
    - `window.showTab = function`
    - 浏览器仅剩 favicon `503`，不影响业务功能。
- 仍建议后续优化：
  - 将 `src/web/dashboard.py` 中的大段内联 HTML/JS 拆出为静态模板和静态 JS，降低继续出现字符串转义问题的概率。
  - 增加 CI 级 secret scan，禁止测试服务器 IP、绝对路径、真实 token、真实 MCP URL 进入 GitHub。
  - 为管理员控制台增加 Playwright 回归脚本，覆盖首屏加载、菜单切换、特殊字符用户、模型选择、MCP 状态页。
  - MCP 调用链路后续可增加更细的超时、重试和用户可见降级提示，避免真实企微 MCP 偶发慢响应时影响 Bot 体验。

## 2026-07-13 员工 AI 助手列表展示修复

- 用户反馈：
  - 管理员控制台「员工AI助手」-「已开通员工」中，「员工」列应显示员工中文名 + 账号。
  - 「AI助手名称」列把默认名称「企业 AI 助手」标记为「需修复」。
- 根因：
  - 页面初始化时先调用 `loadEmployeeBots()`，后调用 `loadAdminUsers(false)`，导致员工机器人列表首次渲染时没有通讯录中文名映射，只能显示账号。
  - 原前端把空 `display_name` 也归入损坏名称分支，展示默认名称时同时显示「需修复」，造成误报。
  - 测试服务器存在历史脏数据：个别员工机器人 `display_name` 已被写成 `?? AI ??`，只修前端会继续在兜底默认名称旁显示「需修复」。
- 修复：
  - `src/web/dashboard.py`
    - 新增 `ensureAdminUsersLoaded()`，员工机器人列表渲染前确保已加载通讯录用户清单。
    - 初始化顺序调整为先 `loadAdminUsers(false)`，再 `loadEmployeeBots()`。
    - 员工列改为优先显示通讯录中文名，中文名存在且不同于账号时，在下一行显示账号。
    - 新增 `defaultEmployeeBotName(platform)` 和 `isDamagedDisplayName(value)`。
    - 空名称使用平台默认 AI 助手名，不再标记「需修复」；只有实际存在乱码特征时才显示「需修复」。
  - `src/platform/employee_bot_service.py`
    - 新增 `_normalize_display_name()` 和 `_is_damaged_display_name()`。
    - 新写入或重命名员工 AI 助手时，空值和损坏值统一归一化为平台默认中文名称。
    - 读取员工机器人列表或单条记录时自动修复历史损坏名称，并回写数据库。
  - `tests/test_admin_console.py`
    - 增加员工机器人列表加载顺序回归测试。
    - 增加默认 AI 助手名称不误判为损坏名称的回归测试。
  - `tests/test_employee_bot_service.py`
    - 增加历史 `?? AI ??` 损坏名称自动修复并回写数据库的回归测试。
- 本地验证：
  - `python -m pytest tests/test_employee_bot_service.py tests/test_admin_console.py -q`
  - 结果：`29 passed`
  - `python -m compileall -q src tests`
  - 结果：通过
  - `python -m pytest -q`
  - 结果：`559 passed`
- 后续注意：
  - 如果后续继续扩展管理员控制台，涉及依赖通讯录名称的页面，应统一先通过通讯录同步数据建立用户映射，再渲染业务列表。
  - 空值、默认值、乱码值要分开判断，避免用兜底展示值触发「需修复」类告警。

## 2026-07-13 员工 AI 助手前台激活与欢迎通知增强

- 用户反馈：
  - 管理员已在后台给韩斌、于林开通员工 AI 助手，但员工手机企业微信前台搜索不到「企业 AI 助手」。
  - 希望管理员点一下即可自动发开通通知，员工侧收到可搜索名称、操作提示，并由机器人主动介绍自己能做什么。
- 判断：
  - 企微侧是否能把机器人强制加入员工通讯录或搜索结果，取决于企业微信机器人/应用的官方可见范围能力。
  - 当前代码侧可稳定落地的是：后台开通或重发欢迎时，主动向员工发送企微应用消息；员工可直接在该消息会话中回复 `你好`，也可按消息里的名称搜索进入。
- 修复：
  - `src/platform/employee_bot_service.py`
    - 新增 `send_employee_bot_welcome()`，支持管理员对单个员工重复发送欢迎/激活指引。
    - 开通员工 AI 助手时复用同一套欢迎消息逻辑。
    - 欢迎消息包含：已开通提示、可搜索机器人名称、直接回复入口、知识库/文档/企业应用/待办等能力介绍。
    - 发送成功后回写 `notify_status`，便于后台看到通知状态。
  - `src/web/dashboard.py`
    - 新增 `POST /api/v1/admin/employee-bots/welcome`。
    - 「已开通员工」列表每行增加「重发欢迎」按钮。
    - 按姓名选择员工时，不再把员工姓名误填为 AI 助手名称，改为平台默认机器人名称。
  - `tests/test_employee_bot_service.py`
    - 增加欢迎消息正文、通知状态回写的回归测试。
  - `tests/test_admin_console.py`
    - 增加欢迎接口鉴权和管理台按钮存在性测试。
- 本地验证：
  - `python -m pytest tests/test_employee_bot_service.py tests/test_admin_console.py -q`
  - 结果：`32 passed`
  - `python -m compileall -q src tests`
  - 结果：通过
  - `python -m pytest -q`
  - 结果：`562 passed`
- 后续注意：
  - 如果员工仍无法通过企微顶部搜索框搜到机器人，应继续排查企业微信后台机器人/应用的真实可见范围，而不是只看本系统的员工授权表。
  - 对企微来说，主动消息本身就是最稳定的员工前台入口；员工收到欢迎消息后，可以直接在该会话中回复使用。

## 2026-07-13 企业 AI 助手统一身份口径收敛

- 用户确认方向：
  - 后端可以保留多个企业微信能力通道，但前端员工体验必须统一为一个“企业 AI 助手”。
  - 员工不应感知“企微应用消息”和“Bot 机器人”是两个助手。
- 本次调整：
  - `src/platform/employee_bot_service.py`
    - 欢迎消息明确说明：员工看到的入口统一叫企业 AI 助手。
    - 消息提示系统会在后台自动选择应用通知、Bot 会话、群聊 @、文档/待办等能力通道。
    - 员工可直接回复欢迎消息，也可搜索或在群里 @ 同名企业 AI 助手。
  - `src/web/dashboard.py`
    - 管理台菜单从“平台 Bot 开通”改为“平台通道接入”。
    - 管理台菜单从“员工 AI 助手”改为“员工助手开通”。
    - 管理台菜单从“企微 MCP”改为“文档/待办能力”。
    - 管理台总说明改为：员工侧只看到一个助手，后台自动协同应用通知、Bot 前台、群聊 @、文档/待办 MCP 和知识库能力。
  - `docs/user-manual.md`
    - 更新管理员操作步骤和文档/待办能力说明，统一为企业 AI 助手口径。
  - `docs/wecom-ai-assistant-activation-guide.md`
    - 员工激活步骤改为搜索企业 AI 助手名称或直接回复欢迎消息。
    - 管理员步骤改为“平台通道接入”和“员工助手开通”。
  - `docs/wecom-ai-assistant-feature-guide.md`
    - 将“机器人可做的事”统一改为“企业 AI 助手可做的事”。
- 验证：
  - `python -m pytest tests/test_employee_bot_service.py tests/test_admin_console.py -q`
  - 结果：`32 passed`
  - `python -m compileall -q src tests`
  - 结果：通过
  - `python -m pytest -q`
  - 结果：`562 passed`
- 后续注意：
  - 代码和文档中仍可在管理员诊断语境使用 Bot、MCP、应用通道等词，但员工侧说明、欢迎消息、日常功能说明应统一叫企业 AI 助手。

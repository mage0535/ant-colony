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
  - 结果：`418 passed`
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
  - 结果：`415 passed`
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

1. 企微完整 roundtrip 已通过，下一步更适合补“真实人工群聊/多人场景”观测而不是基础链路修复
2. 飞书 / 钉钉当前按“模拟验收 + live 脚本待凭据”处理；补齐凭据后沿同一路径做真实联调
3. LangSmith Cloud 已接入，下一步可开始基于 traces 做系统性质量分析和回归评估
4. capability audit 已升级为 SQLite 集中式本地后端，下一步可评估是否迁到共享数据库或日志平台
5. 协作编排增强：
   - 自动升级
   - 自动催办
   - 跨群组互通规则
6. `src/tools/builtin.py` 已收缩到约 2000 行，后续只建议做小步精简，不再建议大规模重构
7. 如果后续新增能力，默认要求：
   - capability ID 明确
   - user context 明确
   - audit scope 明确

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
  - 服务器已配置 `ANT_COLONY_PUBLIC_BASE_URL=http://10.12.254.122:18092`
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

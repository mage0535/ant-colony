# M1 技术规格草案

## 目标

为 P-1 通过后的 M1 开发提供最小但明确的技术规格。

## 当前状态

- 状态：`草案待补`
- 当前优先：先补接口与数据结构，再补消息卡片流程
- 当前已有：`./src/` 契约层占位实现与 `./tests/test_contracts_smoke.py` 最小 smoke test

## 核心接口

### PersonalAgent

```python
process_message(user_id: str, text: str, context: MessageContext) -> AgentResponse
```

### ProjectAgent

```python
identify_tasks(project_id: str, messages: list[Message]) -> list[TaskDraft]
create_draft_task(project_id: str, draft: TaskDraft) -> Task
check_blocked_tasks(project_id: str) -> list[BlockedTask]
generate_reminder(task_id: str, reason: str) -> Reminder
summarize_phase(project_id: str, summary_builder) -> str
```

### Orchestrator

```python
submit(message: Message) -> None
on_batch(project_id: str, messages: list[Message]) -> list[OrchestratorAction]
apply(action: OrchestratorAction) -> ActionOutcome
```

### Gateway

```python
route(message: Message) -> RouteDecision
adapt_wecom_payload(payload: dict) -> AdaptedInboundMessage
handle_wecom_payload(payload: dict) -> InboundResult
render_task_draft_card(task: Task) -> dict
parse_task_card_action(payload: dict) -> TaskCardAction
send(message: OutboundMessage) -> None
handle_task_card_callback(payload: dict) -> ConfirmationOutcome
```

### Guard

```python
evaluate(action: OrchestratorAction, context: GuardContext) -> GuardDecision
```

### Config Management

```python
save_llm_profile(record: LLMSettingsRecord) -> LLMSettingsRecord
get_llm_profile(profile_id: str) -> LLMSettingsRecord | None
list_llm_profiles(enabled_only: bool = False) -> list[LLMSettingsRecord]
save_admin_settings(record: AdminSettingsRecord) -> AdminSettingsRecord
get_admin_settings() -> AdminSettingsRecord | None
save_platform_settings(record: PlatformSettingsRecord) -> PlatformSettingsRecord
get_platform_settings(platform: PlatformType) -> PlatformSettingsRecord | None
list_platform_settings(enabled_only: bool = False) -> list[PlatformSettingsRecord]
build_runtime_snapshot() -> RuntimeSettingsSnapshot
build_engine_config(profile_id: str, agent_role: str) -> AgentEngineConfig
build_settings_from_snapshot() -> Settings
```

当前实现分层：

- `InMemorySettingsRepository`
- `JsonFileSettingsRepository`
- `SettingsManagementService`
- `build_settings_service()` 默认持久化入口

当前已具备的管理行为：

- 默认配置初始化
- LLM 配置 upsert
- 管理员配置 upsert
- 接入平台配置 upsert
- LLM 脱敏视图
- 接入平台缺失字段视图
- 默认 JSON 配置文件引导
- 本地 CLI 配置管理入口
- OpenVort 环境变量导出
- 运行时设置到 `openvort_runtime.env` 的文件导出脚本
- OpenVort `.env` 目标文件覆盖应用
- Linux 服务器隔离目录中的实际 `.env` 应用验证
- 配置 readiness 审计
- 从现有 OpenVort `.env` 反向接管设置
- `seed-from-openvort-env --reset` 重置后导入

## 待定义的数据结构

### Message

- `id`
- `space_id`
- `sender_user_id`
- `content`
- `msg_type`
- `created_at`
- `metadata`

### MessageContext

- `space_type`
- `space_id`
- `dept_id`
- `project_id`
- `mentions`
- `metadata`

### AgentResponse

- `text`
- `visible_to_user`
- `metadata`

### TaskDraft

- `title`
- `description`
- `project_id`
- `source_message_ids`
- `assignee_user_id`
- `collaborator_ids`
- `due_at`
- `confidence`
- `metadata`

### Task

- `id`
- `title`
- `description`
- `project_id`
- `status`
- `assignee_user_id`
- `collaborator_ids`
- `source_message_ids`
- `due_at`
- `blocked_reason`
- `metadata`

### BlockedTask

- `task_id`
- `project_id`
- `reason`
- `suggested_next_steps`
- `metadata`

### Reminder

- `task_id`
- `reason`
- `text`
- `metadata`

### OrchestratorAction

- `kind`
- `space_id`
- `payload`

### GuardDecision

- `decision`
- `reason`
- `metadata`

### LLMSettingsRecord

- `provider`
- `profile_id`
- `model_name`
- `api_key`
- `api_base`
- `max_tokens`
- `timeout_seconds`
- `enabled`
- `metadata`

### AdminSettingsRecord

- `admin_user_ids`
- `web_default_password`
- `pause_command_enabled`
- `handoff_command_enabled`
- `task_confirmation_required`
- `metadata`

### PlatformSettingsRecord

- `platform`
- `enabled`
- `settings`
- `metadata`

### RuntimeSettingsSnapshot

- `llm_profiles`
- `admin_settings`
- `platforms`

## 待补内容

1. 任务草案字段定义
2. 草案确认状态流
3. 消息卡片交互流程
4. 治理指令最小集合
5. M1 数据模型与 DDL 映射
6. 批处理窗口和去重规则
7. 测试与验证命令
8. LLM / 管理员 / 接入平台设置的持久化方式

## 当前测试入口

- 最小 smoke test：`./tests/test_contracts_smoke.py`
- 本地执行脚本：`./scripts/run_smoke_test.ps1`

## 最小知识域边界（M1）

M1 当前先冻结两层可调用边界：

1. 个人知识域
2. 项目知识域

组织知识域、部门知识域和真实 RAG 接入推迟到后续阶段。

### 当前目标

- 让个人 agent 和项目 agent 不再共用一个模糊的“知识池”
- 先用内存仓储固定调用边界
- 后续再把底层替换成 Sidecar / RAG / 数据库

### 当前实现位置

- 契约：`./src/knowledge/contracts.py`
- 服务：`./src/knowledge/service.py`

### 当前最小能力

- 保存个人知识条目
- 保存项目知识条目
- 分别列出个人知识条目
- 分别列出项目知识条目
- 基于项目知识条目生成最小项目摘要

### 当前摘要能力

当前先提供最小的、非 LLM 的项目摘要能力：

- 读取项目知识域中的前几条条目
- 生成阶段摘要文本
- 由 `ProjectAgent.summarize_phase()` 调用摘要服务

当前实现位置：

- `./src/knowledge/project_summary_service.py`
- `./src/agents/project_agent.py`

## 批处理窗口与去重规则（M1 建议）

### 当前建议

群消息在 M1 先采用“批量分析优先”的策略：

1. 个人直聊消息：直接路由到个人 agent
2. 群消息：进入 BatchProcessor
3. 同一空间内按批次分析，不逐条调用 LLM

### 当前最小路由规则

- `metadata.is_direct = True` → 个人消息
- 其余 → 空间批处理消息

### 当前入站适配规则

M1 当前先冻结一条最小原则：

- 外部 IM 提供商事件先适配为内部 `Message` + `MessageContext`
- 后续所有路由、编排、治理都基于内部契约运行

当前最小企微适配位置：

- `./src/gateway/wecom_adapter.py`

当前最小字段映射：

- `from_user_id` → `message.sender_user_id`
- `content` → `message.content`
- `msg_id` → `message.id`
- `dept_id` → `context.dept_id`
- `project_id` → `context.project_id`
- `is_direct` → `message.metadata.is_direct`

### M1 去重原则

当前只冻结原则，不冻结复杂实现：

1. 同一批次不重复生成完全相同标题的任务草案
2. 已有草案未确认前，不重复生成明显相同的草案
3. 闲聊、确认类短消息优先不过度触发分析

### 当前实现位置

- 路由层：`./src/gateway/dispatcher.py`
- 入站适配层：`./src/gateway/wecom_adapter.py`
- 入站服务层：`./src/gateway/inbound_service.py`
- 批处理层：`./src/orchestrator/batch_processor.py`
- 编排层：`./src/orchestrator/task_orchestrator.py`

## 编排层当前最小行为（M1）

当前 `TaskOrchestrator` 的最小职责冻结为：

1. 接收同一空间的一批消息
2. 先识别治理命令
3. 再识别任务草案
4. 对同一批次中标题明显相同的草案做最小去重
5. 输出统一的 `OrchestratorAction` 列表

### 当前动作类型

- `governance_command_detected`
- `task_draft_identified`

## 草案确认链路（M1 当前实现到达位置）

当前最小链路已到达：

1. 群消息进入批处理
2. `TaskOrchestrator` 产出 `task_draft_identified`
3. `OrchestratorActionService` 根据草案创建 `draft` 状态任务
4. `render_task_draft_card()` 可将 `draft` 状态任务渲染为最小确认卡片载荷
5. `TaskConfirmationService` 可处理最小确认动作并把 `draft` 状态推进到 `confirmed`
6. `NotificationService` 可把内部任务对象翻译为 provider-agnostic 外发消息
7. `CardCallbackService` 可将 provider 回调映射为最小确认结果

### 当前尚未完成

- `@相关人` 的真实消息卡片发送交互
- 完整的 provider 回调到确认动作映射
- 治理命令的真实执行链路

### 当前实现位置

- 动作应用层：`./src/orchestrator/action_service.py`
- 卡片渲染层：`./src/gateway/card_renderer.py`
- 卡片动作解析：`./src/gateway/card_actions.py`
- 确认动作服务：`./src/orchestrator/confirmation_service.py`
- 外发通知契约：`./src/gateway/outbound.py`
- 通知构建服务：`./src/orchestrator/notification_service.py`
- 回调入口服务：`./src/gateway/callback_service.py`

## 任务状态流（M1）

当前建议冻结的最小任务状态流：

```text
TaskDraft
  └─ 生成草案
      ↓
Task(status=draft)
  └─ 轻确认通过
      ↓
confirmed
  ├─ 开始执行 → in_progress
  ├─ 确认卡住 → blocked
  └─ 直接完成 → done

in_progress
  ├─ 卡住 → blocked
  └─ 完成 → done

blocked
  ├─ 恢复推进 → in_progress
  └─ 完成收口 → done
```

### 当前实现位置

- 状态流函数：`./src/models/task_flow.py`
- 最小仓储：`./src/models/task_repository.py`
- 生命周期服务：`./src/orchestrator/task_service.py`

## M1 治理指令最小集合

当前建议 M1 先支持以下最小治理集合：

1. `pause`
2. `not_a_task`
3. `handoff_to_human`

### 当前实现位置

- 解析器：`./src/guard/governance_parser.py`

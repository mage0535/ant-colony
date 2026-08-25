# 项目交接状态

## 当前架构结论

- 主方向：`Bot First, Capability Backend`。
- 用户前台统一为企业 IM Bot。
- 后端能力包括平台 API、本地能力、第三方连接器和现场业务系统连接器。
- 管理后台用于管理员配置、观测、授权和故障恢复，不作为普通员工主入口。

## 当前完成状态

- 后台管理菜单已按职责域重新整理：
  - 总览与状态。
  - 工具与集成中心。
  - 用户与权限管理。
  - 员工助手快速开通。
  - 审批假期管理。
  - 组织通知。
  - 知识库管理。
  - 邮箱配置。
  - 文档/待办能力。
  - 平台通道接入。
  - 模型管理。
  - 公共数据源。
  - 运行验证。
  - 业务系统对接。
  - 操作说明。
- 已补后台菜单搜索、稳定 `data-tab` 跳转和权限角色隐藏逻辑。
- 已补人事专员授权、审批假期管理、负数假期台账、企微请假表单静态说明写入能力。
- 已补企业邮箱多账号配置、IMAP/POP3/Exchange 配置模型、邮箱未读统计、轮询提醒和后台测试能力。
- 已补业务系统待办采集、通知去重、通道状态、自动恢复和后台人工恢复说明。
- 已补企业应用状态变化通知、审批/流程用户边界控制、消息分段发送和消息无回复兜底。
- 已补统一工具与集成管理中心、公共数据源管理、联网检索聚合和搜索结果翻页能力。
- 已补企业知识库说明书和面向小白用户的操作手册。
- 已补模型管理测试按钮，以及默认模型变更后的前台个人 Agent engine 热刷新能力。

## 最新验证

- 本地全量测试：`872 passed`。
- 测试服务器全量测试：`872 passed`。
- 测试服务器服务状态：
  - `ant-colony-dashboard` active。
  - `ant-colony-gateway` active。
  - `ant-colony-wecom-bot` active。
  - `ant-colony-cron` active。
- 后台页面和网关健康检查通过。

## 2026-08-25 默认模型热刷新

- 问题：后台“模型管理”保存或切换默认模型后，管理后台测试可立即使用新模型，但企微前台已有个人会话中的 `PersonalAgent` 会继续持有服务启动时创建的旧 `engine`，导致用户仍可能看到旧模型的 429 错误。
- 处理：`InboundGatewayService.get_or_create_agent()` 在每条个人消息进入前检查当前默认模型签名；当 `profile_id/provider/model/api_base/max_tokens/updated_at` 变化时，自动重建个人 `engine`，并替换所有已缓存个人 Agent 的 `engine`。
- 效果：管理员保存并设为默认模型后，无需手动重启 gateway/wecom-bot；下一条个人前台消息会自动切换到新默认模型。
- 边界：该机制面向个人前台消息链路；批量项目消息的 project engine 仍按服务启动时配置运行，如后续需要群/项目批处理也热刷新，可扩展同样签名机制到 `BatchFlusher`。
- 测试：
  - `python -m pytest -q tests/test_gateway_model_refresh.py`：1 passed。
  - `python -m pytest -q tests/test_gateway_model_refresh.py tests/test_contracts_smoke.py tests/test_document_pipeline.py tests/test_inbound_entry_links.py tests/test_inbound_web_search.py tests/test_admin_user_and_model_services.py tests/test_admin_console.py`：159 passed。
  - `python -m pytest -q`：872 passed。

## 发布注意事项

- 本文件为公开仓库可发布摘要，不记录客户现场 IP、账号、路径、真实邮箱、真实密钥或现场数据库名。
- 客户现场实施细节应保存在私有部署记录或私有知识库中，不应提交到公开 GitHub 仓库。
- 运行配置必须通过环境变量、私有 `.env`、数据库或管理员后台保存。
- 新增连接器时应提供通用占位配置和测试用例，不提交真实凭据。

## 后续建议

- 将业务系统连接器继续抽象为通用 workflow connector，避免客户现场命名进入核心代码。
- 将后台页面继续拆分为更小的组件或模板，降低 `dashboard.py` 体积。
- 增加发布前自动脱敏检查脚本，作为 GitHub 推送前的强制检查。
- 对真实企微审批回调、邮箱轮询、业务系统采集器建立定期健康巡检和告警。
## 2026-08-10 假期管理按部门批量调整与姓名匹配

- 后台“审批假期管理”新增“按部门选择员工”区域，直接复用企业 IM 通讯录数据，按 `department_path` 分组展示员工。
- 人事专员可在假期管理中按部门、姓名或用户 ID 搜索员工，支持“选择当前筛选结果”“取消当前筛选结果”和“批量调整已选员工”。
- 新增 `/api/v1/admin/leave/balance-target/batch`，对已选员工去重后逐人调用真实假期额度调整逻辑，返回成功/失败明细，适合整部门统一补录加班、调休或临时假期额度。
- 单人假期调整、动态假期提示、负数能力验证、员工 AI 助手开通/停用、人事专员授权、业务系统人员绑定等用户输入入口统一支持“姓名或企业 IM 用户 ID”；同名员工会提示改填用户 ID。
- 本次变更不改变权限边界：假期管理仍由管理员或人事专员访问；批量调整仍写入同一套假期台账和企微同步逻辑。
- 已补回归测试：姓名解析动态假期提示、批量假期调整去重执行、管理页面部门批量选择控件存在性。

### 验证

- `python -m py_compile src\web\dashboard.py`
- `python -m pytest -q tests/test_admin_console.py`：60 passed

## 2026-08-10 人事专员真实权限验证

- 测试服务器已读取到 2 名人事专员，均存在于企业 IM 通讯录，且员工 AI 助手状态为 active。
- 以两位人事专员各自身份调用真实后台接口验证：
  - `/api/v1/admin/profile` 返回 `can_manage_leave=true`。
  - `/api/v1/admin/users` 可返回通讯录员工清单，当前 129 名员工均带 `department_path`，可支撑按部门筛选和批量选择。
  - `/api/v1/admin/leave/realtime-sync` 可读取假期类型与实时同步状态。
  - `/api/v1/admin/leave/form-notice` 可读取员工真实假期余额提示。
  - `/api/v1/admin/leave/balance-target/batch` 以空员工列表调用时返回“请至少选择一名员工”，证明已通过权限校验并进入参数校验。
- 使用临时测试用户调用批量假期调整接口，去重后成功处理 2 个测试用户；企微真实接口确认负数 `leftduration` 不支持，系统按设计写入本地负数台账。测试完成后已清理 `leave_local_balances` 和 `leave_quota_adjustments` 中的临时测试记录，清理后剩余 0 条。
- 以两位人事专员各自身份打开 `/admin/console`，页面包含“审批假期管理”“按部门选择员工”“批量调整已选员工”“员工姓名或用户 ID”和 `applyLeaveBalanceTargetBatch`，页面入口已可见。

### 结论

- 当前人事专员权限、通讯录部门筛选、动态假期提示和批量调整接口均已真实可用。
- 暂未发现需要代码修复的问题；后续真实业务使用时重点关注企微正数额度同步是否因租户权限、假期类型 ID 或 `time_attr` 配置错误被拒绝。

## 2026-08-11 邮件主动提醒内容简化

- 邮件主动提醒不再推送来源邮箱、到达时间、发件人、标题、正文摘要和附件名。
- 新主动提醒统一为：
  - `【新邮件提醒】`
  - `你有一封新邮件到达。`
  - `可回复“查看未读邮件”了解当前未读数量。AI 助手只提醒和查询，不读取正文摘要、不代发邮件或回复邮件。`
- 该变更只影响新邮件主动推送；用户主动询问“查看未读邮件”时，只返回当前未读邮件数量。

### 验证

- `python -m pytest -q tests/test_mail_account_service.py`：36 passed。

## 2026-08-11 关闭邮件摘要，仅保留未读统计

- 对员工关闭邮件摘要功能：不再通过 AI 助手展示邮件到达时间、发件人、标题、正文摘要、附件名，也不再读取邮件正文做摘要。
- 保留新邮件主动提醒：只提示“你有一封新邮件到达”，并引导回复“查看未读邮件”。
- 保留邮箱查询能力：员工可发送“查看未读邮件”“我有几封未读邮件”，IMAP 邮箱通过 `UNSEEN` 返回服务端未读数量，不拉取正文；POP3 协议无法读取服务器真实未读状态，系统统计“AI 助手已提醒但员工未确认”的本地新邮件提醒数；员工处理完邮箱后可回复“清空邮件提醒”归零；Exchange 当前提示需启用 EWS/Graph 未读统计能力。
- 管理后台文案已从“员工邮箱摘要配置”改为“员工邮箱未读统计配置”。

### 验证

- `python -m pytest -q tests/test_mail_account_service.py`：37 passed。

## 2026-08-11 POP3 邮箱未读统计落地

- 背景：企业邮箱只支持 POP3 时，POP3 协议没有服务端“未读”标记，无法像 IMAP 一样读取真实未读邮件。
- 处理：新增本地新邮件提醒台账，POP3 查询“查看未读邮件”时返回“当前有 N 封未确认的新邮件提醒”，不登录 POP3 拉正文，也不展示邮件头。
- 员工操作：处理完邮箱后可回复“清空邮件提醒”或“标记邮件提醒已读”，系统只清空 AI 助手本地计数，不修改邮箱服务器状态。
- 数据：`mail_notification_events` 新增 `acknowledged_at` 字段；`delivery_status='sent' AND acknowledged_at=0` 作为 POP3 本地未确认提醒数。
- 测试：`python -m pytest -q tests/test_mail_account_service.py tests/test_phase1_shortcuts.py`，结果 `51 passed`。

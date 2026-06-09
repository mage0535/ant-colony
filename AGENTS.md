# Ant Colony 企业多智能体协作系统 — 新同事入职指南

## 项目定位

本项目是一个**企业多智能体协作系统**，不是单一聊天机器人，也不是单一项目管理工具。

核心概念：
- **个人 Agent** → 员工的专属 AI 助手，记住你的角色/职责
- **项目 Agent** → 项目空间中的推进核心，自动识别任务、催办、关阻塞
- **聊天流 + 任务板** → 双核协作结构：群聊讨论 → 自动提取任务 → 仪表盘管理

---

## 项目定位

```
用户访问层
├── 企业微信 (IM 入口)
│   └── [production-domain]:443/dyhj/ant/callback
│       └── Nginx 反代 → 测试服务器 :18091 (回调服务)
└── Dashboard (Web 界面)
    └── 测试服务器 :18092 (FastAPI + SSE)

服务层 (测试服务器 systemd)
├── ant-colony-gateway    :18090  消息路由 + Agent引擎
├── ant-colony-callback    :18091  WeCom 回调 + 加解密
├── ant-colony-dashboard   :18092  仪表盘 + API
├── gbrain-bridge          :8787   知识图谱 (PostgreSQL)
├── hindsight-bridge       :8890   事实记忆 + 召回
└── embed-service          :8766   语义向量 (384d)

数据层
├── PostgreSQL 16 (sidecar 数据库)
│   ├── gbrain_pages      知识图谱节点
│   ├── hindsight_memories 事实记忆
│   └── gbrain_timeline/links 关系
└── SQLite (ant-colony.db)
    ├── tasks/task_drafts  任务系统
    ├── space_messages     消息历史
    ├── reminders          催办记录
    └── knowledge_fts      FTS5 全文索引
```

---

## 源代码目录结构

```
ant-colony-probe/
├── src/
│   ├── agents/          Agent 实现
│   │   ├── personal_agent.py   员工个人助手
│   │   ├── project_agent.py    项目助手
│   │   ├── host_agent.py       主持人（会议纪要+行动项）
│   │   └── work_journal.py     工作日志
│   ├── gateway/         消息网关
│   │   ├── webhook_server.py      HTTP 网关 (:18090)
│   │   ├── wecom_callback_server.py  企微回调 (:18091)
│   │   ├── inbound_service.py    入站消息处理
│   │   ├── dispatcher.py         消息路由
│   │   └── wecom_adapter.py      企微字段适配
│   ├── web/             Dashboard
│   │   ├── dashboard.py           FastAPI 服务 (:18092)
│   │   ├── templates/dashboard.html Bootstrap 5 界面
│   │   ├── sse_bus.py             实时事件推送
│   │   └── middleware.py           认证+限流
│   ├── engine/          LLM 引擎
│   │   ├── base.py                 AgentEngine (OpenAI/Anthropic)
│   │   └── factory.py              引擎工厂
│   ├── orchestrator/    编排层
│   │   ├── task_orchestrator.py    任务识别编排
│   │   ├── batch_flusher.py       批量冲刷
│   │   ├── batch_processor.py     消息缓冲
│   │   ├── deadline_tracker.py    截止日期追踪
│   │   ├── task_analytics.py      任务统计
│   │   └── org_sync.py            组织架构同步 (WeCom)
│   ├── memory/          记忆体
│   │   ├── sidecar.py              Hot 层 (文件)
│   │   ├── conversation.py         对话记忆
│   │   ├── warm_store.py           Warm 层 (SQLite)
│   │   ├── cold_store.py           Cold 层 (图谱)
│   │   ├── gbrain_bridge.py        gbrain HTTP API
│   │   ├── hindsight_bridge.py     Hindsight HTTP API
│   │   ├── embed_service.py        语义嵌入服务
│   │   ├── context_builder.py      三层上下文融合
│   │   └── maintenance.py          记忆维护周期
│   ├── knowledge/       知识库
│   │   ├── fts_repo.py             FTS5 搜索+ACL
│   │   ├── gbrain_repo.py       gbrain/PostgreSQL 知识仓储
│   │   ├── cloud_drive.py       12+云盘 ACL 管理器
│   │   ├── acl.py               知识库角色权限解析器
│   │   ├── collector.py            URL抓取/文本导入
│   │   ├── contracts.py            知识域契约
│   │   └── service.py              知识服务
│   ├── store/           持久层
│   │   ├── database.py             SQLite 连接管理
│   │   └── task_repo.py            任务仓储
│   ├── models/          数据模型
│   │   └── contracts.py            Task/Message/Status 等
│   ├── tools/           内置工具
│   │   ├── builtin.py              5 个工具 (now/echo/query/create_draft/search)
│   │   └── registry.py             工具注册
│   ├── analysis/        分析引擎
│   │   └── role_analyzer.py        角色识别 (9 关键词)
│   ├── pool/            Agent 池
│   │   └── agent_pool.py           池化管理
│   ├── rooms/           空间注册
│   │   └── space_registry.py       空间 CRUD
│   ├── isolation/       隔离系统
│   │   └── file_store.py           目录沙箱
│   ├── platform/        跨平台 API 客户端 + 角色管理
│   │   ├── __init__.py      统一路由 + 工具函数
│   │   ├── api_feishu.py    飞书 OpenAPI
│   │   ├── api_dingtalk.py  钉钉 OpenAPI
│   │   ├── api_wecom.py     企微 OpenAPI
│   │   ├── admin_registry.py  管理员注册表
│   │   ├── role_manager.py  215 角色管理器
│   │   ├── plugin_base.py   第三方插件基类
│   │   ├── plugins/         插件目录
│   │   └── bridges/         Tier-2 桥接通道
│   └── guard/           治理
│       └── governance_parser.py    治理指令
├── scripts/
│   ├── acceptance_test.py   验收测试
│   ├── integration_test.py  集成测试
│   ├── e2e_test.py          E2E 测试
│   └── db_backup.sh        数据库备份
├── tests/
│   └── test_store.py        122 个单元测试
├── infra/
│   └── .env.wecom           WeCom 凭据配置
├── external/
│   ├── sidecar/source/      Memory Sidecar v3.1.0 源码
│   ├── openvort/source/     OpenVort 企微通道源码
│   └── hermes/source/       Hermes Agent 引擎源码
└── docs/
    ├── handoff.md           当前状态+交接记录
    ├── decisions.md         技术决策记录
    ├── m1-plan.md           M1 计划
    ├── m1-spec.md           M1 技术规格
    ├── p1-verification.md   P-1 验证记录
    ├── architecture.md      架构文档
    └── user-manual.md       使用手册
```

---

## 服务管理

系统由以下服务组成（启动方式见 `infra/*.service`）：

| 服务 | 端口 | 说明 |
|------|------|------|
| ant-colony-gateway | 18090 | 消息路由 + Agent 引擎 |
| ant-colony-callback | 18091 | WeCom 回调 + 加解密 |
| ant-colony-dashboard | 18092 | REST API（后端管理接口） |
| gbrain-bridge | 8787 | 知识图谱 (PostgreSQL) |
| hindsight-bridge | 8890 | 事实记忆 + 召回 |
| embed-service | 8766 | 语义向量 (384d) |

查看服务状态：
```bash
systemctl status ant-colony-gateway
```

查看日志：
```bash
journalctl -u ant-colony-gateway -n 50
```

---

## 关键配置

### 平台凭据 (`infra/.env.wecom`)

| 变量 | 说明 |
|------|------|
| WECOM_CORP_ID | 企业微信 CorpID |
| WECOM_AGENT_ID | AgentId |
| WECOM_SECRET | 应用 Secret |
| WECOM_CALLBACK_TOKEN | 回调 Token |
| WECOM_CALLBACK_AES_KEY | 回调 AES Key |
| WECOM_CONTACT_SECRET | 通讯录同步 Secret |

### LLM API Key

配置文件：`data/runtime_settings.json`。安装时通过 `scripts/setup.py` 配置。

---

## 测试

```bash
python3 -m pytest tests/ -q --tb=short
```

当前测试覆盖：**122 unit + 24 acceptance + 12 integration + 12 E2E = 170 tests**

---

## 架构图

```
                          ┌──────────────┐
                          │  企业微信用户  │
                          └──────┬───────┘
                                 │
                    ┌────────────┴────────────┐
                    │  消息网关 (:18090)       │
                    │  Agent 引擎 + 工具注册    │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                   ▼
    ┌────────────────┐ ┌────────────────┐ ┌──────────────────┐
    │ 回调服务(:18091) │ │  网关(:18090)   │ │ Dashboard(:18092) │
    │ WeCom 加解密    │ │ 消息路由       │ │ REST API 服务     │
    │ → Gateway      │ │ Agent 引擎     │ │ (无前端界面)       │
    └────────────────┘ └───────┬────────┘ └──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │ gbrain(:8787)│ │Hindsight(:8890)│ │Embedding(:8766)│
    │ 知识图谱     │ │ 事实记忆      │ │ 语义向量      │
    │ PostgreSQL   │ │ PostgreSQL    │ │ 384d模型      │
    └──────────────┘ └──────────────┘ └──────────────┘
              │                │
              ▼                ▼
        ┌──────────────────────────┐
        │    PostgreSQL 16         │
        │  + pgvector 扩展         │
        └──────────────────────────┘
        ┌──────────────────────────┐
        │    SQLite (ant-colony.db)│
        │  任务/消息/知识/空间     │
        └──────────────────────────┘
```

---

## 功能清单（已全部完成）

| 类别 | 功能 | 说明 |
|------|------|------|
| **聊天流** | 企微消息接入 | 自动同步企微群聊到系统 |
| | 消息路由 | 直发→个人Agent / 群→项目Agent |
| | 任务草案识别 | LLM 自动分析对话提取待办 |
| **任务系统** | 状态流转 | 草案→待开始→进行中→完成/阻塞 |
| | 优先级 | 高/中/低 |
| | 截止日期 | 到期自动催办 |
| | 任务依赖 | 阻塞链 + 级联解阻塞 |
| | 批量操作 | 多选批量状态修改 |
| | 搜索导出 | 关键词 + CSV/JSON |
| **仪表盘** | SSE 实时推送 | 数据变更自动刷新 |
| | 统计面板 | 完成率/逾期/依赖链统计 |
| | 角色分析 | 自动识别角色 |
| | 工作日志 | 按用户查看任务 |
| | 知识搜索 | FTS5 全文搜索 |
| | 文件管理 | 上传/列表/删除 |
| **知识库** | FTS5 索引 | 知识即搜即得 |
| | URL 抓取 | 自动爬取入库 |
| | 文本导入 | 粘贴文本入库 |
| | 151 营销技能 | 内置文档 |
| **Agent** | 个人助手 | 记忆角色信息 |
| | 项目助手 | 自动识别任务 |
| | 主持人 | 会议纪要+行动项 |
| | 5 工具 | 查询/搜索/创建 |
| **记忆体** | Warm (Hindsight) | 事实留存+召回 |
| | Cold (gbrain) | 知识图谱 |
| | Embedding | 语义向量 384d |
| **组织架构** | WeCom 同步 | 一键同步部门和成员 |
| | Sidecar 记忆 | 自动创建成员文件 |
| **基础设施** | 6 systemd 服务 | 自启+自愈 |
| | PostgreSQL+pgvector | 持久化 |
| | Nginx 反代 | 生产 HTTPS |
| | DB 备份 | 每日凌晨 3 点 |
| | 认证中间件 | Token 认证+限流 |

---

## 最新更新 (2026-06-09)

### 仪表盘移除，全会话运营
- 已删除 `dashboard.html` / `drafts.html` / SSE 端点
- 所有功能通过聊天命令完成（任务管理/知识搜索/文档生成/统计/审批/日程等）
- 表格盘端口 :18092 仅保留 REST API 供内部服务使用

### 三平台消息适配器
| 适配器 | 文件 | 触发条件 |
|--------|------|----------|
| 飞书 | `src/gateway/adapter_feishu.py` | 设置 `FEISHU_APP_ID` + `FEISHU_APP_SECRET` |
| 钉钉 | `src/gateway/adapter_dingtalk.py` | 设置 `DINGTALK_CLIENT_ID` + `DINGTALK_CLIENT_SECRET` |
| Telegram | `src/gateway/adapter_telegram.py` | 设置 `TELEGRAM_BOT_TOKEN` |
| 平台感知 | `src/gateway/platform_adapters.py` | 网关启动时自动加载已配适配器 |

### 跨平台统一工具 (src/platform/)
飞书/钉钉/企微 三平台的统一 API 客户端，零外部 SDK 依赖。自动检测已配平台后激活对应工具：
- `contact_search` — 查找联系人
- `calendar_agenda` — 查看日程/会议
- `calendar_create` — 创建日程
- `doc_search` — 搜索企业文档
- `approval_list` — 查看审批待办
- `create_doc` — 创建企业文档 (WeCom)
- `list_meetings` / `create_meeting` — 会议管理
- `who_is_admin` — 查看平台管理员（与部门负责人分离）
- `who_is_leader` — 查看部门负责人列表

### 知识库 ACL 分级权限 (src/knowledge/acl.py)
四层角色 + 四级知识库范围访问控制：
- admin (平台管理员) — 全部权限
- leader (部门负责人) — 公司/部门库可写
- member (项目成员) — 项目库可写
- self (个人) — 仅个人库可读写

知识库范围：公司(全员可读)、部门(部门可读)、项目(成员可读)、个人(本人+admin)

管理员管理：
- 企微管理员通过聊天命令动态添加（`添加管理员 马戈`），无 API 限制
- 飞书管理员通过 `is_tenant_manager` 自动识别
- 钉钉管理员通过 admin list API 自动识别

### 插件与桥接架构
- Tier 1: 官方 API（`src/platform/api_*.py`）
- Tier 2: 替代通道（`src/platform/bridges/`）
- Tier 3: 自定义插件（`src/platform/plugin_base.py` + `src/platform/plugins/`）

### AI 角色系统 (src/platform/role_manager.py)
- 内置 215 个来自 agency-agents-zh 的 AI 专家角色
- 自动匹配：Agent 根据用户请求调用 select_role 匹配最佳专家
- 可切换：用户说"换一个/不对"即可切换角色
- 252 个角色定义文件存储在 data/roles/

### GStack 方法论工具 (src/tools/gstack_skills.py)
- `office_hours` — YC Office Hours 产品探索（6 强制问题）
- `review_doc` — 系统性审查方法论
- `investigate` — 根因排查协议
- `spec` — 5 阶段需求规格化
- `retro` — 团队回顾框架

### 新增工具汇总 (>60 个)
考勤/股票/天气/搜索/任务管理/邮件/PDF操作/DuckDuckGo/平台联系人/日程/文档/审批/会议/管理员识别/角色系统/GStack方法论

---

## 六项自建模块完成状态

| 模块 | 优先级 | 状态 |
|------|--------|------|
| 组织架构同步器 | P0 | ✅ 已同步 136 用户 + 24 部门 |
| Worker Pool 管理器 | P0 | ✅ AgentPool + API |
| 聊天室引擎 | P0 | ✅ SpaceRegistry |
| 多角色分析引擎 | P1 | ✅ RoleAnalyzer |
| 目录隔离系统 | P1 | ✅ PathSanitizer + FileStore |
| RAG 分层 ACL | P2 | ✅ FtsKnowledgeRepository |

---

## 数据库

### PostgreSQL (三层记忆体)

```
数据库: sidecar
用户:   sidecar
密码:   [db-password]
扩展:   vector (pgvector)
```

### SQLite (任务系统)

```
路径: data/ant-colony.db
备份: data/backups/ant-colony-YYYYMMDD_HHMMSS.db.gz (每日3点)
```

---

## 连续开发协议

### 启动规则

新会话按以下顺序读取项目状态：

1. `./README.md`
2. `./AGENTS.md`
3. `./data/heartbeat-state.json`
4. `./docs/handoff.md`
5. `./docs/decisions.md`
6. `./docs/m1-plan.md`
7. `./docs/user-manual.md`

### 会话内自循环

完成一个任务后 → 立即读 handoff.md 下一步 → **不等待确认** → 直接继续。

### 严禁行为

- ❌ 问"要继续吗？""选哪个方向？" 
- ❌ 列一堆选项让用户选择
- ❌ 停下手头工作等指令
- ✅ 直接取最优选项开始
- ✅ 全阻塞时停止并报告原因

### 中断前更新

可能中断前完成：
1. 更新 `./docs/handoff.md`
2. 记录决策到 `./docs/decisions.md`
3. 写明当前阻塞和下一步

---

## 当前状态

**项目已完成全部功能开发**。6 服务运行中，170 测试通过，企微回调已验证。组织架构已同步 136 用户。

详情见 `./docs/handoff.md` 和 `./docs/user-manual.md`。

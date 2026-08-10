# Ant Colony 企业多智能体协作系统 — 新同事入职指南

## 项目定位

本项目是一个**企业多智能体协作系统**，不是单一聊天机器人，也不是单一工作台应用。

当前已正式收敛的总方向是：

**Bot First, Capability Backend**

即：

- 员工前端统一为 Bot
- 员工只在企业 IM 中和 Bot 交互
- 平台应用、开放 API、第三方连接器、内部系统全部作为 Bot 背后的能力后端
- 个人 Agent / 项目 Agent / 专家 Agent 负责理解、编排和调用能力

一句话理解：

**用户只找 Bot，Bot 再替用户调用企业能力。**

---

## 当前主架构

```text
交互层
├── WeCom Bot
├── Feishu Bot
├── DingTalk Bot
└── 其他消息入口（后续可扩）

编排层
├── Gateway / Dispatcher
├── PersonalAgent / ProjectAgent
├── Tool Orchestrator
├── Task / Memory / Knowledge
└── File & Document Pipeline

能力层
├── 平台官方 API（企微 / 飞书 / 钉钉）
├── 平台应用能力
├── 第三方连接器
├── 本地内部能力（云盘 / 邮箱等）
└── 后续内部业务系统
```

当前原则：

- 不再把“每个平台都做一个独立前端应用”作为默认方向
- 不再把 Dashboard / Web 页面作为主交互入口
- 自建应用保留为企业能力后端，而不是主前端

---

## 关键认知

### 1. Bot 是前台，不是平台应用

后续新增功能时，默认先问：

1. 这个能力能不能由 Bot 在后台调用？
2. 这个功能有没有必要让用户直接进入某个平台应用页面？
3. 这个能力是不是应该沉到统一能力层？

如果没有强理由，默认答案应是：

- **Bot 前台**
- **能力后端**

### 2. 文件能力是一级能力

本项目不只是问答系统，文件链路是主线能力：

- 上传模板
- 读取附件
- 解析 docx/xlsx/pptx/pdf
- 按模板生成正式文档
- 回推文件

### 3. 平台能力要走统一协议

不要继续在工具函数或业务逻辑里堆平台分支。

当前已经开始统一的能力协议包括：

- `contacts.search`
- `calendar.list`
- `calendar.create`
- `docs.search`
- `docs.create`
- `approval.list`
- `meeting.list`
- `meeting.create`
- `org.admins`
- `org.leaders`
- `drive.search`
- `mail.summary`

对应代码入口：

- `src/platform/capability_backend.py`
- `src/platform/__init__.py`
- `src/platform/internal_capability_provider.py`

---

## 当前源代码重点目录

```text
src/
├── agents/                Agent 实现
├── gateway/               消息入口、路由、Bot/回调桥接
├── engine/                LLM 引擎
├── orchestrator/          编排、批处理、任务推进
├── memory/                会话记忆与多层记忆
├── knowledge/             知识库、文档、云盘
├── tools/                 Bot 可调用工具
├── platform/              统一能力后端（平台 API / 内部 provider / 插件）
├── store/                 持久层
├── models/                数据模型
└── web/                   保留的后端接口，不是主前端
```

当前与主线最相关的文件：

- `src/gateway/wecom_bot_bridge.py`
- `src/gateway/inbound_service.py`
- `src/gateway/wecom_file_handler.py`
- `src/tools/builtin.py`
- `src/tools/document_tool.py`
- `src/platform/capability_backend.py`
- `src/platform/internal_capability_provider.py`

---

## 服务现状

测试服务器当前主要服务：

| 服务 | 端口 | 说明 |
|------|------|------|
| `ant-colony-gateway` | 18090 | 主消息网关 + Agent 编排 |
| `ant-colony-callback` | 18091 | 旧 WeCom callback 通道（保留兼容） |
| `ant-colony-dashboard` | 18092 | 后端 REST / 文件访问接口 |
| `gbrain-bridge` | 8787 | 知识图谱 |
| `hindsight-bridge` | 8890 | 事实记忆 |
| `embed-service` | 8766 | 向量服务 |

注意：

- `18092` 现在是后端接口和文件访问端口，不是主前端
- 主交互面应理解为 Bot，而不是 dashboard

---

## 连续开发协议

### 启动规则

新会话按以下顺序读取项目状态：

1. `./README.md`
2. `./AGENTS.md`
3. `./docs/current-handoff-summary.md`
4. `./data/heartbeat-state.json`（如果存在；不存在不算异常）
5. `./docs/handoff.md` 最新部分
6. `./docs/decisions.md`
7. `./docs/architecture.md`
8. `./docs/m1-plan.md`
9. `./docs/user-manual.md`

说明：

- `docs/current-handoff-summary.md` 是干净交接摘要，应作为新同事第一阅读入口。
- `docs/handoff.md` 是完整连续开发流水，包含历史长记录和部分不可逆乱码段；默认只读最新部分，追溯历史原因时再深入阅读。

### 会话内自循环

完成一个任务后：

- 立即回读 `docs/handoff.md`
- 找当前建议的下一步
- **不等待确认**
- 直接继续推进

### 严禁行为

- 不要默认新增新的前端入口
- 不要默认把 AI 主入口迁回自建应用
- 不要把平台差异继续写死在业务逻辑里
- 不要只靠 prompt 修复模板结构问题

### 建议默认行为

- Bot 作为唯一用户前台
- 平台应用/API作为后端能力层
- 能力按域抽象
- 文件能力作为一级能力建设
- 长任务优先考虑异步回推

---

## 当前主线工作

### A. 统一能力后端

目标：

- 让 Bot 只依赖能力协议，而不依赖具体平台实现
- 把平台 API provider、内部 provider、第三方 provider 接到统一后端

当前已完成：

- `capability_backend.py` 骨架
- internal provider
- capability discovery

### B. 文档模板链路

目标：

- 模板保留
- 模板结构提取
- 模板实例化生成

当前已完成：

- 模板格式继承主链修复
- 前言 / 审批表保留
- 模板元数据贯穿生成链路
- 内容超时兜底

### C. 企业后端能力扩展

当前优先级建议：

1. 在线文档 / 网盘
2. 邮箱
3. 日历 / 会议深化
4. 审批 / 待办
5. 第三方系统 / 内部业务系统

---

## 当前状态文件

### `data/heartbeat-state.json`

该文件现在仅作为“最近一次连续开发方向快照”的占位状态文件使用。

它的作用：

- 告诉后续同事当前主线方向
- 避免启动规则引用到不存在文件

它不是系统运行时强依赖。

---

## 你接手时应该怎么理解项目

如果你是新同事，请用下面这句话理解项目：

**Ant Colony 不是“企业微信里的一个 AI 应用”，而是“企业 IM 原生的多智能体协作操作层”。**

所以你后续做任何设计时，先想：

- 员工是否只需要和 Bot 说话？
- Bot 背后是否已有能力层可以接？
- 这个能力是否应归入统一协议？

如果答案是“可以”，就不要再反过来做成“用户去找应用页面”。

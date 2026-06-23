# Ant Colony

企业多智能体协作系统，采用 **Bot First, Capability Backend** 架构。

> [English](README.en.md) · [安装指南](docs/installation-guide.md) · [使用手册](docs/user-manual.md)

---

## 项目是什么

Ant Colony 不是一个单纯的聊天机器人，也不是一个单独的工作台应用。

它是一个面向企业协作场景的多智能体系统，核心目标是：

- 员工只需要在企业 IM 中找 Bot
- Bot 负责理解意图、调度 Agent、调用企业能力
- 平台应用、开放 API、第三方连接器和内部系统都作为 Bot 背后的能力后端

一句话：

**用户只与 Bot 交互，Bot 再替用户调用企业能力。**

---

## 当前架构方向

项目已正式收敛为：

**Bot First, Capability Backend**

### 前端

- WeCom Bot
- Feishu Bot
- DingTalk Bot

员工主入口统一是 Bot，而不是多个平台分别做前端页面。

### 中间编排层

- Gateway / Dispatcher
- PersonalAgent / ProjectAgent / 专家角色
- Tool Orchestrator
- Task / Memory / Knowledge
- File & Document Pipeline

### 后端能力层

- 平台官方 API
- 平台应用能力
- 第三方连接器
- 本地内部能力（如云盘、邮箱）
- 后续内部业务系统

---

## 核心理念

| 传统模式 | Ant Colony 模式 |
|------|------|
| 员工在多个系统间切换 | 员工只找 Bot |
| 平台应用直接面向用户 | 平台能力退到 Bot 后端 |
| 文件、审批、通讯录、日程分散 | 统一由 Bot 调用能力层 |
| 知识、任务、沟通分离 | 聊天、任务、知识、文件在同一协作流里 |

---

## 当前能力面

### Agent 层

- 个人 Agent
- 项目 Agent
- 专家角色 Agent

### 文件与文档

- 上传模板
- 解析附件
- 结构化文档生成
- 模板保留与格式继承

### 企业能力域

当前统一能力协议已开始落地：

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

对应入口代码：

- `src/platform/capability_backend.py`
- `src/platform/internal_capability_provider.py`
- `src/platform/__init__.py`

---

## 当前目录重点

```text
src/
├── agents/                Agent 实现
├── gateway/               消息入口、路由、Bot/回调桥接
├── engine/                LLM 引擎
├── orchestrator/          编排、批处理、任务推进
├── memory/                会话记忆与多层记忆
├── knowledge/             知识库、文档、云盘
├── tools/                 Bot 可调用工具
├── platform/              统一能力后端
├── store/                 持久层
├── models/                数据模型
└── web/                   保留的后端接口
```

特别说明：

- `web/` 当前不是主前端
- 主交互面应理解为企业 IM 中的 Bot

---

## 运行与服务

测试服务器当前主要服务：

| 服务 | 端口 | 说明 |
|------|------|------|
| `ant-colony-gateway` | 18090 | 主网关 + Agent 编排 |
| `ant-colony-callback` | 18091 | 旧 WeCom callback 通道（兼容保留） |
| `ant-colony-dashboard` | 18092 | REST / 文件访问接口 |
| `gbrain-bridge` | 8787 | 知识图谱 |
| `hindsight-bridge` | 8890 | 事实记忆 |
| `embed-service` | 8766 | 向量服务 |

---

## 快速开始

```bash
git clone https://github.com/[your]/ant-colony.git
cd ant-colony
python scripts/setup.py
python run_gateway.py
```

首次安装请先阅读：

- [安装指南](docs/installation-guide.md)
- [使用手册](docs/user-manual.md)

---

## 后续同事先看哪些文档

建议顺序：

1. `README.md`
2. `AGENTS.md`
3. `docs/handoff.md`
4. `docs/decisions.md`
5. `docs/architecture.md`

如果你接手开发，请优先接受这条项目主线：

**不要新增新的前端入口，优先把能力接到 Bot 后端。**

---

## 相关文档

- [AGENTS.md](AGENTS.md)
- [docs/handoff.md](docs/handoff.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/decisions.md](docs/decisions.md)
- [docs/user-manual.md](docs/user-manual.md)
- [docs/wecom-ai-assistant-activation-guide.md](docs/wecom-ai-assistant-activation-guide.md)
- [docs/wecom-ai-assistant-feature-guide.md](docs/wecom-ai-assistant-feature-guide.md)
- [docs/knowledge-base-operations-guide.md](docs/knowledge-base-operations-guide.md)
- [docs/installation-guide.md](docs/installation-guide.md)

---

## License

MIT

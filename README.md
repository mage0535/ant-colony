# Ant Colony 🐜 — 企业多智能体协作系统

> [English](README.en.md) · [安装指南](docs/installation-guide.md) · [使用手册](docs/user-manual.md)

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/platform-WeCom%20%7C%20Feishu%20%7C%20DingTalk%20%7C%20Telegram-brightgreen" alt="Platforms">
  <img src="https://img.shields.io/badge/agents-215%20expert%20roles-orange" alt="215 Expert Roles">
  <img src="https://img.shields.io/badge/tools-57%20integrated-yellow" alt="57 Tools">
</p>

---

## 📋 项目简介

**Ant Colony（蚁群）** 是一个企业级多智能体协作系统。它不是简单的聊天机器人，而是一个**完整的 AI 劳动力平台**——每个员工拥有自己的 AI 助手，每个项目有专属的项目 Agent，所有助手在聊天中协同工作。

### 🎯 核心理念

| 传统模式 | Ant Colony 模式 |
|---------|----------------|
| 员工在各个系统间切换操作 | 🤖 在聊天中一句话完成所有操作 |
| 知识散落在文档、网盘、邮件里 | 🧠 统一知识库，按权限分级访问 |
| 任务靠人工跟踪推进 | 📋 AI 自动识别任务、催办、关阻塞 |
| 每个平台需要单独学习 | 🔌 统一 API 接入企微/飞书/钉钉/Telegram |

### 🏗 架构

```
用户 → 企业微信/飞书/钉钉/Telegram
         │
         ▼
   消息网关 (Gateway) :18090
         │
    ┌────┴────┐
    ▼         ▼
  LLM 引擎  工具注册表 (57 工具)
    │         │
    ▼         ▼
  记忆体 ──→ 知识库 (PostgreSQL + ACL)
   (gbrain)   │
              ├─ 公司知识库 (全员可读)
              ├─ 部门知识库 (部门可读)
              ├─ 项目知识库 (成员可读)
              └─ 个人知识库 (仅本人+管理员)
```

---

## ✨ 功能总览

### 🤖 215 个 AI 专家角色

系统内置 **215 个即插即用的 AI 专家角色**，覆盖工程、设计、营销、产品、安全、金融等 18 个领域。AI 助手会根据你的问题**自动匹配**最合适的专家身份。

```
你：帮我写一篇小红书种草笔记
AI：我将以 **小红书运营专家** 的身份来协助你...
```

如果角色不合适，说"换一个角色"即可切换。

> 角色库源自 [agency-agents-zh](https://github.com/jnMetaCode/agency-agents-zh)（MIT 协议）并深度集成。

### 🛠 57 个内置工具（完整清单）

<details>
<summary><b>📋 任务管理 (8个)</b></summary>

| 工具 | 触发语句 |
|------|---------|
| `create_draft` | 创建任务 [标题] |
| `query_tasks` | 查看我的任务 |
| `search_tasks` | 搜索任务 [关键词] |
| `transition_task` | 完成任务 / 开始任务 / 阻塞任务 |
| `task_analytics` | 查看任务统计 |
| `work_journal` | 查看工作日志 |
| `list_spaces` | 查看项目空间 |
| `set_priority` | 把[任务]设为高优先级 |
</details>

<details>
<summary><b>🧠 知识库 (3个) — ACL 分级权限</b></summary>

| 范围 | 可读 | 可写 |
|------|------|------|
| 公司 (organization) | 全员 | admin + 公司负责人 |
| 部门 (department) | 部门成员 | admin + 部门负责人 |
| 项目 (project) | 项目成员 | admin + 项目成员 |
| 个人 (personal) | 本人 + admin | 本人 + admin |

| 工具 | 触发语句 |
|------|---------|
| `search_knowledge` | 搜索知识 [关键词] |
| `list_knowledge` | 查看知识库 |
| `add_document` | 添加文档 归属:公司 标题:xxx 内容:xxx |
</details>

<details>
<summary><b>👥 平台工具 (8个) — 跨企微/飞书/钉钉</b></summary>

| 工具 | 触发语句 | 企微 | 飞书 | 钉钉 |
|------|---------|------|------|------|
| `contact_search` | 查找联系人 [姓名] | ✅ | ✅ | ✅ |
| `calendar_agenda` | 查看日程 | ✅ | ✅ | ✅ |
| `calendar_create` | 创建日程 [标题] [时间] | ✅ | ✅ | ✅ |
| `doc_search` | 搜索文档 [关键词] | ✅ | ✅ | ✅ |
| `create_doc` | 创建文档 [标题] | ✅ | — | — |
| `approval_list` | 查看待审批 | — | ✅ | ✅ |
| `who_is_admin` | 谁是平台管理员？ | ✅ | ✅ | ✅ |
| `who_is_leader` | 谁是部门负责人？ | ✅ | — | — |
</details>

<details>
<summary><b>📄 文档与生产力 (9个)</b></summary>

| 工具 | 触发语句 |
|------|---------|
| `send_email` | 发送邮件到 [地址] 主题 [主题] |
| `list_emails` | 查看收件箱 |
| `search_emails` | 搜索邮件 [关键词] |
| `get_email` | 查看邮件详情 [UID] |
| `merge_pdfs` | 合并PDF [文件列表] |
| `split_pdf` | 拆分PDF [文件] 页数 [范围] |
| `compress_pdf` | 压缩PDF [文件] |
| `protect_pdf` | 加密PDF [文件] 密码 [密码] |
| `generate_document` | 生成报告 [标题] [内容] |
</details>

<details>
<summary><b>🔍 搜索 (3个)</b></summary>

| 工具 | 触发语句 | 说明 |
|------|---------|------|
| `anysearch` | 搜索 [关键词] | 互联网搜索（主搜索引擎） |
| `ddg_search` | 用DuckDuckGo搜索 [关键词] | 备选搜索引擎 |
| `weather` | 天气 [城市] | 实时天气查询 |
</details>

<details>
<summary><b>🎭 AI 角色系统 (3个)</b></summary>

| 工具 | 触发语句 |
|------|---------|
| `select_role` | 自动调用（根据请求匹配最佳角色） |
| `list_roles` | 有哪些角色？ |
| `set_role` | 切换到 [角色名] |
</details>

<details>
<summary><b>🔧 GStack 方法论 (5个)</b></summary>

| 工具 | 触发语句 | 来源 |
|------|---------|------|
| `office_hours` | 帮我分析需求 [描述] | YC Office Hours |
| `review_doc` | 审查 [内容] | Staff Engineer Review |
| `investigate` | 排查 [问题] | 根因排查协议 |
| `spec` | 写需求文档 [目标] | 规格化方法论 |
| `retro` | 做回顾 | 团队回顾框架 |
</details>

<details>
<summary><b>☁️ 云盘同步 (4个) — ACL 分级</b></summary>

| 范围 | 谁可以配置 | 支持的云盘 |
|------|-----------|-----------|
| 公司级 | admin + 公司负责人 | OneDrive / Google Drive / 阿里云盘 / 百度云盘 |
| 部门级 | admin + 部门负责人 | Dropbox / Mega / 坚果云 / Nextcloud |
| 项目级 | admin | iCloud / 天翼云盘 / 115 / 夸克网盘 |

| 工具 | 触发语句 |
|------|---------|
| `register_cloud_drive` | 添加云盘 [名称] [类型] |
| `list_cloud_drives` | 查看云盘 |
| `sync_from_cloud` | 同步云盘 |
| `delete_cloud_drive` | 删除云盘 [ID] |
</details>

<details>
<summary><b>📊 考勤查询 (6个)</b></summary>

| 工具 | 触发语句 |
|------|---------|
| `query_attendance` | 查看考勤 |
| `query_leave` | 查看请假记录 |
| `leave_balance` | 年假还剩几天？ |
| `query_dept` | 查看部门考勤 |
| `query_subordinate` | 查[姓名]的考勤 |
| `query_subordinate_balance` | 查[姓名]的假期余额 |
</details>

<details>
<summary><b>💰 金融与系统 (10个)</b></summary>

| 工具 | 触发语句 |
|------|---------|
| `tushare` | 查股票 [代码] |
| `now` | 现在几点？ |
| `echo` | 回声测试 |
| `cron_list` | 查看定时任务 |
| `add_admin` | 添加管理员 [姓名] |
| `remove_admin` | 移除管理员 [姓名] |
| `who_is_leader` | 谁是部门负责人？ |
| `who_is_admin` | 谁是平台管理员？ |
| `list_roles` | 有哪些角色？ |
| `select_role` | 自动调用（角色匹配） |
</details>

---

## 🧩 借鉴的开源项目

Ant Colony 站在巨人的肩膀上。以下开源项目为本项目提供了关键能力：

| 项目 | 用途 | 协议 |
|------|------|------|
| [agency-agents-zh](https://github.com/jnMetaCode/agency-agents-zh) | 215 个 AI 专家角色定义 | MIT |
| [gstack](https://github.com/garrytan/gstack) | YC Office Hours / Review / Investigate / Spec / Retro 方法论 | MIT |
| [crew44](https://github.com/getcrew44/crew44) | 多 Agent 编排与 Handover 协议架构参考 | MIT |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | OCR/文档提取、邮件、PDF 工具架构参考 | MIT |
| [SkillsBot](https://www.skillsbot.cn) | 技能定义格式参考 | — |

致谢所有维护者和贡献者 🙏

---

## 🚀 快速开始

```bash
git clone https://github.com/[your]/ant-colony.git
cd ant-colony
python scripts/setup.py      # 交互式安装引导
python run_gateway.py        # 启动系统
```

首次安装请参考 [安装引导文档](docs/installation-guide.md)。

### 前置要求

- Python 3.10+
- PostgreSQL 16+（含 pgvector 扩展）
- 至少一个 IM 平台的开发者账号（企微/飞书/钉钉/Telegram）

---

## 📖 文档

| 文档 | 语言 | 说明 |
|------|------|------|
| [安装引导](docs/installation-guide.md) | 中文 | 小白向的详细安装步骤 |
| [使用手册](docs/user-manual.md) | 中文 | 员工使用指南 |
| [Installation Guide](docs/installation-guide.en.md) | English | Beginner-friendly setup |
| [AGENTS.md](AGENTS.md) | 中文 | 开发者/维护者文档 |
| [handoff.md](docs/handoff.md) | 中文 | 项目交接状态 |

---

## 🔑 环境变量

| 变量 | 平台 | 说明 |
|------|------|------|
| `WECOM_CORP_ID` | 企业微信 | CorpID |
| `WECOM_AGENT_ID` | 企业微信 | 应用 AgentId |
| `WECOM_SECRET` | 企业微信 | 应用 Secret |
| `WECOM_CALLBACK_TOKEN` | 企业微信 | 回调 Token（可选） |
| `WECOM_CALLBACK_AES_KEY` | 企业微信 | 回调 AES Key（可选） |
| `WECOM_CONTACT_SECRET` | 企业微信 | 通讯录同步 Secret |
| `FEISHU_APP_ID` | 飞书 | App ID |
| `FEISHU_APP_SECRET` | 飞书 | App Secret |
| `FEISHU_DOMAIN` | 飞书 | cn=中国版 / intl=国际版Lark |
| `DINGTALK_CLIENT_ID` | 钉钉 | Client ID (AppKey) |
| `DINGTALK_CLIENT_SECRET` | 钉钉 | Client Secret (AppSecret) |
| `TELEGRAM_BOT_TOKEN` | Telegram | Bot Token |
| `GBRAIN_DB_URL` | PostgreSQL | 数据库连接（默认 `postgresql://sidecar:sidecar123@localhost:5432/sidecar`） |

---

## 📄 许可证

[MIT License](LICENSE)

---

## 🔗 SEO 关键词

`企业AI助手` `多智能体协作` `企业微信AI` `飞书机器人` `钉钉AI` `AI Agent` `Multi-Agent System` `Enterprise AI` `知识库ACL` `AI专家角色` `企业级AI平台` `智能体编排` `Multi-Agent Orchestration` `AI助理` `企业知识管理` `LLM应用` `AI工作流` `Chatbot Enterprise` `AI Collaboration` `Agent Platform`

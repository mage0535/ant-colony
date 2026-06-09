# Ant Colony 🐜 — Enterprise Multi-Agent Collaboration System

> [中文](README.md) · [Installation Guide](docs/installation-guide.en.md) · [User Manual](docs/user-manual.md)

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/platform-WeCom%20%7C%20Feishu%20%7C%20DingTalk%20%7C%20Telegram-brightgreen" alt="Platforms">
  <img src="https://img.shields.io/badge/agents-215%20expert%20roles-orange" alt="215 Expert Roles">
  <img src="https://img.shields.io/badge/tools-57%20integrated-yellow" alt="57 Tools">
</p>

---

## 📋 Overview

**Ant Colony** is an enterprise-grade multi-agent collaboration system. It is not a simple chatbot — it is a **complete AI workforce platform**. Every employee gets their own AI assistant, every project has a dedicated project agent, and all assistants collaborate through chat.

### 🎯 Core Architecture

```
Users → WeCom / Feishu / DingTalk / Telegram
         │
         ▼
   Message Gateway (Port :18090)
         │
    ┌────┴────┐
    ▼         ▼
  LLM Engine  Tool Registry (57 tools)
    │         │
    ▼         ▼
  Memory  ──→ Knowledge Base (PostgreSQL + ACL)
   (gbrain)   │
              ├─ Company KB (all employees)
              ├─ Department KB (dept members)
              ├─ Project KB (project members)
              └─ Personal KB (self + admin)
```

---

## ✨ Features

### 🤖 215 AI Expert Roles

Built-in **215 plug-and-play AI expert roles** covering engineering, design, marketing, product, security, finance and 12+ more domains. The AI assistant **auto-matches** the best expert for your request.

```
You: Write a React component with TypeScript
AI: I will assist you as a **Frontend Developer**
```

> Role library from [agency-agents-zh](https://github.com/jnMetaCode/agency-agents-zh) (MIT) with deep integration.

### 🛠 57 Built-in Tools

| Category | Count | Tools |
|----------|-------|-------|
| **Task Management** | 8 | Create, query, search, transition, analytics, journal, spaces, priority |
| **Knowledge Base** | 3 | Search, list, add documents (ACL controlled) |
| **Platform Tools** | 8 | Contacts, calendar, docs, approvals, meetings (WeCom/Feishu/DingTalk) |
| **Productivity** | 9 | Email, PDF merge/split/compress/encrypt, document generation |
| **Search** | 3 | Web search, DuckDuckGo, weather |
| **AI Roles** | 3 | Auto-select, list, switch roles |
| **GStack Methods** | 5 | Office Hours, Review, Investigate, Spec, Retro |
| **Cloud Drive** | 4 | Register, list, sync, delete (ACL scoped) |
| **Attendance** | 6 | Check-in, leave, balance, department, subordinates |
| **Admin & System** | 8 | Add/remove admins, cron, stocks, who_is_admin, who_is_leader |

### 🔐 Knowledge Base ACL

| Scope | Readable By | Writable By |
|-------|-------------|-------------|
| Organization | Everyone | Admin + Company Leader |
| Department | Dept Members | Admin + Dept Leader |
| Project | Project Members | Admin + Project Members |
| Personal | Self + Admin | Self + Admin |

---

## 🧩 Open Source Acknowledgements

Ant Colony stands on the shoulders of giants. These open-source projects contributed key capabilities:

| Project | Used For | License |
|---------|----------|---------|
| [agency-agents-zh](https://github.com/jnMetaCode/agency-agents-zh) | 215 AI expert role definitions | MIT |
| [gstack](https://github.com/garrytan/gstack) | YC Office Hours / Review / Investigate / Spec / Retro methods | MIT |
| [crew44](https://github.com/getcrew44/crew44) | Multi-agent orchestration architecture reference | MIT |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | OCR/document extraction, email, PDF tool architecture | MIT |
| [SkillsBot](https://www.skillsbot.cn) | Skill definition format reference | — |

Thanks to all maintainers and contributors 🙏

---

## 🚀 Quick Start

```bash
git clone https://github.com/[your]/ant-colony.git
cd ant-colony
python scripts/setup.py      # Interactive installation wizard
python run_gateway.py        # Start the system
```

For first-time setup, see the [Installation Guide](docs/installation-guide.en.md).

### Prerequisites

- Python 3.10+
- PostgreSQL 16+ (with pgvector extension)
- At least one IM platform developer account (WeCom / Feishu / DingTalk / Telegram)

---

## 📖 Documentation

| Document | Language | Description |
|----------|----------|-------------|
| [Installation Guide](docs/installation-guide.en.md) | English | Step-by-step beginner setup |
| [User Manual](docs/user-manual.md) | Chinese | Employee usage guide |
| [安装引导](docs/installation-guide.md) | 中文 | 小白安装步骤 |
| [AGENTS.md](AGENTS.md) | Chinese | Developer/maintainer docs |
| [handoff.md](docs/handoff.md) | Chinese | Project handoff status |

---

## 🔑 Environment Variables

| Variable | Platform | Description |
|----------|----------|-------------|
| `WECOM_CORP_ID` | WeCom | Corp ID |
| `WECOM_AGENT_ID` | WeCom | App Agent ID |
| `WECOM_SECRET` | WeCom | App Secret |
| `WECOM_CALLBACK_TOKEN` | WeCom | Callback Token (optional) |
| `WECOM_CALLBACK_AES_KEY` | WeCom | Callback AES Key (optional) |
| `WECOM_CONTACT_SECRET` | WeCom | Contact Sync Secret |
| `FEISHU_APP_ID` | Feishu | App ID |
| `FEISHU_APP_SECRET` | Feishu | App Secret |
| `FEISHU_DOMAIN` | Feishu | cn=China / intl=Lark |
| `DINGTALK_CLIENT_ID` | DingTalk | Client ID (AppKey) |
| `DINGTALK_CLIENT_SECRET` | DingTalk | Client Secret (AppSecret) |
| `TELEGRAM_BOT_TOKEN` | Telegram | Bot Token |
| `GBRAIN_DB_URL` | PostgreSQL | Database URL (default: `postgresql://sidecar:[db-password]@localhost:5432/sidecar`) |

---

## 📄 License

[MIT License](LICENSE)

---

## 🔗 Keywords

`Multi-Agent System` `Enterprise AI` `AI Agent` `Knowledge Base ACL` `AI Expert Roles` `Multi-Agent Orchestration` `Enterprise Knowledge Management` `LLM Application` `AI Workflow` `Agent Platform` `企业AI助手` `多智能体协作` `企业微信AI` `飞书机器人` `钉钉AI`

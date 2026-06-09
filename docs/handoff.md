# 项目交接状态 — 2026-06-09

## 当前状态
- 项目已完成全部功能开发 + 扩展，进入维护运营阶段
- Dashboard 已完全移除，全部功能通过聊天前端（企微/飞书/钉钉/Telegram）操作
- 6 个 systemd 服务运行中（gateway/callback/dashboard-api/cron/gbrain/hindsight）
- >60 个内置 Agent 工具
- 252 个 AI 专家角色

## 已完成的重大变更

### 架构层
1. **仪表盘移除** — 全部改为聊天命令
2. **知识库存储迁移** — SQLite FTS5 → gbrain/PostgreSQL
3. **三平台消息适配器** — 飞书/钉钉/Telegram
4. **三平台 API 客户端** — 零依赖，urllib 实现
5. **插件架构** — Tier 1/2/3 分层 + 自动发现

### 权限体系
6. **知识库 ACL 分级** — admin/leader/member/self 四层角色
7. **平台管理员 vs 部门负责人分离** — who_is_admin / who_is_leader 独立查询
8. **管理员管理** — 企微通过聊天添加（add_admin/remove_admin），飞书钉钉自动识别

### 功能扩展
9. **215 个 AI 专家角色** — 来自 agency-agents-zh，自动匹配
10. **GStack 方法论** — YC Office Hours/Review/Investigate/Spec/Retro
11. **12+ 云盘同步** — ACL 分级，自动索引到知识库
12. **邮件/PDF 工具** — 发送邮件、PDF 操作
13. **DuckDuckGo 搜索** — 搜索链第三级降级
14. **OCR 引擎升级** — pymupdf + marker-pdf 多级降级

## 当前无阻塞

## 下一步建议（按优先级）
1. 为飞书/钉钉/Telegram 在 systemd 中配置 env 凭证并测试
2. 完善企微文档/日程/会议的 API 端点测试（部分端点返回 404）
3. 为具体业务场景添加审批模板匹配
4. 编写第三方插件开发文档
5. 压力测试 — 多用户并发场景

## 环境配置清单
- Gateway service 已添加 `EnvironmentFile=/home/[test-user]/ant-colony-probe/infra/.env.wecom`
- 管理员识别：企微需在 .env.wecom 配置凭据，通过聊天命令动态添加
- 知识库存储：gbrain-bridge (PostgreSQL) 端口 8787
- Python 包：PyMuPDF, python-docx, python-pptx, openpyxl 已安装

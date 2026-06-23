# 架构说明

## 当前总方向

项目已从“多平台分别做前端入口”的思路，统一收敛为：

**Bot First, Capability Backend**

即：

- 前端统一是 Bot
- 员工只在企业 IM 中和 Bot 交互
- 平台应用、开放 API、第三方连接器、自建插件全部下沉为 Bot 背后的能力层
- 个人 Agent / 项目 Agent / 专家 Agent 负责意图理解、任务编排和能力调用

这一定义覆盖：

- 企业微信 AI Bot
- 飞书 Bot
- 钉钉 Bot
- 后续可扩 Telegram / Slack / Teams 等消息入口

## 为什么这样设计

项目最早定位不是“企业里的一个聊天机器人”，也不是“工作台中的单个应用”，而是：

- 企业多智能体协作系统
- 聊天即入口
- 从会话中识别任务、协作、文档处理和知识调用
- 让员工像找同事一样找 AI

因此：

- Bot 更适合作为员工直面的前端
- 应用更适合作为企业能力后端

## 三层结构

### 1. 交互层

职责：

- 接收员工消息
- 接收群聊 @Bot
- 接收文件、模板、附件
- 回推文本、卡片、文件和异步结果

入口：

- WeCom Bot
- Feishu Bot
- DingTalk Bot

原则：

- 不让员工直接理解“平台应用能力”
- 不让员工自己切换多个前端入口

### 2. 编排层

职责：

- 路由消息到 PersonalAgent / ProjectAgent / 专家角色
- 决策是否调用能力层
- 管理多轮会话上下文
- 管理记忆、知识、任务、文件处理
- 管理同步任务和异步任务

核心模块：

- `src/gateway/`
- `src/agents/`
- `src/engine/`
- `src/orchestrator/`
- `src/tools/`

### 3. 能力层

职责：

- 以统一接口提供企业平台能力
- 屏蔽企业微信 / 飞书 / 钉钉各自接口差异
- 把应用能力、官方 API、第三方连接器统一抽象成能力后端

能力来源：

- 平台自建应用 API
- 平台官方开放 API
- 第三方应用 / SaaS
- 内部业务系统
- 自建插件

## 能力域划分

建议长期固定为以下 8 个能力域：

### 1. 组织域

- 通讯录
- 部门架构
- 负责人
- 管理员
- 用户身份映射

### 2. 协同域

- 日历
- 会议
- 待办
- 审批
- 任务

### 3. 文档域

- 在线文档
- 企业文档
- 知识库
- 网盘
- 模板文件
- PDF 文档
- 表格 / 幻灯片

### 4. 通信域

- 企业邮箱
- 群通知
- 公告
- 订阅消息

### 5. 业务系统域

- OA
- ERP
- CRM
- MES
- HR
- 财务系统

### 6. 文件处理域

- 文件下载
- OCR
- 模板实例化
- PDF 读取 / 提取 / 合并 / 拆分 / 压缩 / 加密
- docx/xlsx/pptx/pdf 导出

### 7. 权限与审计域

- 用户权限上下文
- 调用审计
- 敏感数据访问日志
- 越权防护

当前代码落点补充：

- capability backend 已开始接收统一调用上下文
- 平台工具层会透传 `user_id / platform / transport / scope / source_chat_id`
- 调用审计当前落到本地 SQLite 后端 `data/audit/capability_audit.sqlite3`，并保留 legacy JSONL 迁移能力

### 8. 插件扩展域

- 第三方连接器
- MCP / 插件
- 内部服务适配器

## 统一能力协议

后续代码不应再继续沿用“每个平台直接暴露一组散函数”的方式，而应逐步统一为能力协议，例如：

- `contacts.search`
- `calendar.list`
- `calendar.create`
- `docs.search`
- `docs.create`
- `drive.search`
- `drive.read`
- `mail.summary`
- `approval.list`
- `meeting.list`
- `meeting.create`

各平台只是这些能力协议的不同实现。

当前已落地的第一版包括：

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
- `files.office.*`
- `drive.search`
- `mail.summary`
- `files.pdf.*`

并且已经支持两类 provider：

- 平台 API provider
- 内部能力 provider（如本地云盘、邮箱）

当前本地文档后端的明确分工：

- `OfficeCLI`：本地 Office 文档主后端
- `internal provider`：本地 Python 工具链兜底与补充；当前已补齐 Office 读/写/模板摘要 fallback
- `Stirling-PDF`：本地 PDF 服务后端（已承接 merge/split/compress/protect/read/extract-images/watermark 等真实能力）
- `OCRmyPDF`：本地 OCR 专项 provider

## 关键原则

### 原则 1：Bot 永远是前台

- 用户只找 Bot
- 用户不需要理解应用边界
- 应用能力应由 Bot 在后台调用

### 原则 2：用户身份贯穿调用链

Bot 不应使用“系统级默认权限”替用户查询全部数据。

必须带着：

- 平台身份
- 用户 ID
- 部门 / 角色
- 可见范围

去访问能力层。

### 原则 3：长任务异步化

以下能力应默认支持异步回推：

- 长文档生成
- 大范围知识检索
- 文件模板实例化
- 邮件汇总
- 审批统计

### 原则 4：文件是一级能力

本项目不是纯问答系统，文件流是核心能力链路：

- 上传模板
- 读取附件
- 解析 docx/xlsx/pptx/pdf
- 生成正式文档
- 回推文件

## 当前代码映射

### 现状

当前 `src/platform/__init__.py` 仍然是“按平台尝试调用”的轻聚合函数集合。

这是可工作的第一版，但不利于后续扩展：

- 平台差异暴露过多
- 缺少统一能力模型
- 不利于后续接邮箱、网盘、在线文档、第三方系统

### 新方向

应逐步演进为：

- `src/platform/capability_backend.py`
- `src/platform/api_*.py`
- `src/platform/internal_capability_provider.py`
- `src/platform/bridges/*`
- `src/platform/plugins/*`

其中：

- `capability_backend.py` 负责统一能力接口
- `internal_capability_provider.py` 负责挂接本地已有内部能力（如云盘、邮箱）
- `api_*.py` 负责各平台官方 API
- `bridges/*` 负责替代接入通道
- `plugins/*` 负责第三方或内部系统扩展

## 分阶段实施建议

### 阶段 1：统一方向与代码入口

- 文档统一改为 Bot First
- 新增统一能力后端入口
- 保持旧工具函数兼容

### 阶段 2：能力域化

- 把联系人 / 日历 / 文档 / 审批等工具迁移到统一能力协议
- 补测试和调用审计

### 阶段 3：文件与文档能力深化

- 模板探测
- 模板填充
- 模板校验
- 跨 docx/xlsx/pptx 统一模板能力
- 将 PDF 能力纳入统一文档协议，而不是只作为零散工具存在

### 阶段 4：企业系统外延扩展

- 邮箱
- 网盘
- 在线文档
- PDF 文档工作流
- 第三方 SaaS
- 内部系统

### 阶段 5：治理与运营

- 审计
- 敏感调用策略
- 角色能力矩阵
- 租户 / 部门 / 项目级范围控制

## 后续同事接手时的默认理解

后续任何新功能，都应优先按以下问题判断：

1. 这个能力是不是应该先作为 Bot 能调用的后端能力？
2. 这个功能是不是不应该直接暴露成一个新前端入口？
3. 这个能力能否归入某个统一能力域？
4. 这个调用是否带上了用户身份和权限上下文？
5. 这个任务是否应该同步执行，还是异步回推？

如果以上问题没有回答清楚，不建议直接新增平台耦合代码。

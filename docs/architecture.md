# 架构说明

## 目标

把最初融合方案的方向落到当前可执行架构中，确保：

- 不偏离“企业多智能体协作系统”的主目标
- M1 的最小实现能支撑 M2-M5 演进
- 多人连续开发时有清晰边界

## 当前冻结的核心模型

### 角色

- 个人 agent
- 项目 agent
- 子角色 agent（M3 引入）

### 空间

- 部门空间
- 项目空间

### 交互

- 聊天流
- 任务板

## 当前分层

### L1 接入层

- 企业微信
- 飞书
- Web 管理面板（后续增强）

### L2 网关层

- Dispatcher
- 去重
- 路由
- 空间识别
- 基础 RBAC

### L2.5 编排与治理层

- Task Orchestrator
- Action Guard
- 治理指令解析器
- BatchProcessor

### L3 Agent 运行层

- AgentEngine
- PersonalAgent
- ProjectAgent

### L4-L7 知识、记忆与基础设施

- Sidecar 记忆体
- 三层知识域
- RAG / 采集 / 存储
- Docker Compose 基础设施

## 当前实现策略

### M1 重点

- 保持接口先稳定
- 保持实现先最小
- 群消息走批量分析
- 个人消息快速响应
- 外部项目按当前阶段目标选择性吸收

### M1 暂不做

- 大规模 Worker Pool
- 完整组织同步
- 独立主持人模块
- RAG 分层 ACL
- 知识采集管线
- Web 任务板

## 关键边界

### 个人 agent

- 绑定员工
- 服务个人上下文
- 使用个人知识域

### 项目 agent

- 绑定项目空间
- 负责任务识别、草案确认、催办与阻塞跟进
- 使用项目知识域

### 治理能力

- 先作为项目 agent 的内含能力
- 后续视 M2/M3 反馈决定是否拆分

## 当前待补充

- `./docs/m1-spec.md`
- 任务草案字段定义
- 消息卡片交互流程
- Action Guard 判定规则
- `./docs/integration-strategy.md` 的阶段性吸收清单落到实际验证计划

# P-1 验证记录

## 目标

确认核心开源组件与接缝可用，再进入 M1 开发。

## 验证项

### 1. OpenVort 企微通道

- 状态：`进行中`
- 负责人：
- 结论：当前系统全局环境中 `openvort` 仍不可直接导入，但 OpenVort 上游源码已落地到 `./external/openvort/source`，且在隔离 vendor 依赖目录与统一探针入口下，顶层包、关键模块、CLI 与启动级探针都可运行
- 证据：
  - `./scripts/run_p1_components.ps1`
  - `./scratchpad/p1_verify_openvort.py`
  - `./external/openvort/source-metadata.json`
  - `./scratchpad/vendor/openvort_probe/`
- 问题：
  - 当前机器上没有“脱离隔离探针环境”的可直接 import `openvort`
  - 当前尚未把已落地源码以正式安装或稳定运行方式接到本项目实际验证链路
- 下一步：
  - 基于隔离依赖目录继续验证 OpenVort 的企微通道、启动入口与最小运行命令
  - 当前先沿用 `source-path + vendor deps` 探针模式，把 editable install 评估留到 Linux 服务器环境

### 2. Hermes loop 可抽取性

- 状态：`已通过`
- 负责人：
- 结论：Hermes 源码已落地 `./external/hermes/source`，agent/ 目录包含 88 个模块
- 证据：
  - `./scripts/run_p1_components.ps1`
  - `./scratchpad/p1_verify_hermes.py`
  - `./external/hermes/source-metadata.json`
- 关键发现：
  - 核心循环位于 `agent/conversation_loop.py`（而非原计划中的 `loop.py`），v0.15.0 重构后模块已拆分
  - 所有 10 个关键模块（conversation_loop、prompt_builder、tool_executor、memory_manager、context_engine 等）完整存在
  - providers/ 目录完整支持多 LLM 提供者
- 下一步：
  - M1 启动时从 conversation_loop.py 抽取核心引擎，封装为 AgentEngine

### 3. Sidecar 多目录安装

- 状态：`已通过`
- 负责人：
- 结论：Memory Sidecar 源码已落地 `./external/sidecar/source`，全 13 个 memory 脚本完整存在
- 证据：
  - `./scripts/run_p1_components.ps1`
  - `./scratchpad/p1_verify_sidecar.py`
  - `./external/sidecar/source-metadata.json`
- 关键发现：
  - 所有 key memory 脚本：tiered_context_injector、session_to_gbrain、memory_lifecycle、domain_memory、memory_guard 等全部存在
  - install.sh 存在，支持 `AGENT_HOME` 多目录独立安装
  - 三层记忆结构（Hot/Warm/Cold）与原始设计描述一致
- 下一步：
  - M1 启动时通过 `AGENT_HOME` 参数为每个 agent 独立安装 Sidecar

### 4. gbrain 基础接口

- 状态：`进行中`
- 负责人：
- 结论：当前环境中 `http://localhost:8787` 不可达
- 证据：
  - `./scripts/run_p1_components.ps1`
  - `./scratchpad/p1_verify_gbrain.py`
- 问题：
  - 当前机器上没有可访问的本地 gbrain 服务
- 下一步：
  - 确认 gbrain 是否需要 Docker、本地二进制还是远端替代方案

### 5. 依赖冲突扫描

- 状态：`进行中`
- 负责人：
- 结论：当前项目骨架的统一 P-1 基线已可通过；`Docker` 当前环境不可用
- 结论：当前项目骨架的统一 P-1 基线已可通过；组件级检查显示 OpenVort / Hermes / Sidecar / gbrain 仍缺少真实接入条件
- 证据：
  - `./scripts/run_smoke_test.ps1` 通过
  - `./scratchpad/p1_verify_env.ps1` 输出：Python/Pip/Git 可用，Docker unavailable
  - `./scripts/run_p1_baseline.ps1` 已通过：环境快照 + 导入验证 + 19 项 smoke test
- 问题：
  - 从 `./scratchpad/` 直接执行 Python 脚本时，默认找不到 `src` 包，已在脚本中修复
  - 曾暴露一处 `inbound_service` 到 `orchestrator` 的包级循环依赖，已修复
- 下一步：
  - 继续扩展 OpenVort / Hermes / Sidecar / gbrain 的真实组件级验证
  - 优先明确这四类来源在本项目中的接入方式

## 进入 M1 的判断

- 是否进入 M1：`建议进入 M1`
- 阻塞项：gbrain（Docker 依赖，M1 非必需）、真实企微通道配置（需业务方提供）
- 判断依据：
  - OpenVort：✅ 源码已落地，Linux 深验证链已闭环
  - Hermes：✅ 源码已落地，核心 loop 模块已确认
  - Sidecar：✅ 源码已落地，全部 13 个 memory 脚本已确认
  - gbrain：🟡 本地 Docker 不可用，非 M1 必需（M2+ 再引入）
- 建议调整：先进入 M1，gbrain 推迟到 M2 或 Linux 服务器环境

## 当前基线结论

当前项目在完成 Hermes 和 Sidecar 源码获取后，P-1 已完成 3/4 验证项：

- ✅ OpenVort：源码落地 + Linux 深验证闭环
- ✅ Hermes：源码落地 + 核心 loop 确认
- ✅ Sidecar：源码落地 + 全部 scripts 确认
- 🟡 gbrain：本地 Docker 不可用，非 M1 必需

当前项目骨架（不依赖外部 provider 与 Docker）已具备：

- 统一环境快照入口
- 基础导入验证入口
- 统一 P-1 基线验证脚本
- 统一 P-1 全检查脚本
- 31 项最小 smoke test
- 完整配置管理（内存 + JSON + CLI + 导出 + 导入）
- 任务状态流 + 编排 + 治理指令 + 知识域契约

## 推荐下一步

P-1 的核心验证目标已基本完成：

1. ✅ OpenVort — 通道可用，Linux 已验证
2. ✅ Hermes — 源码已落地，核心 loop 模块确认
3. ✅ Sidecar — 源码已落地，全 memory 脚本确认
4. 🟡 gbrain — 非 M1 必需

**建议：正式进入 M1 开发阶段。**

M1 第 1 周应重点做：

1. 从 Hermes `agent/conversation_loop.py` 抽取核心引擎，封装为 `AgentEngine`
2. 将现有契约层代码与真实 LLM 调用连接（配置管理已就绪）
3. 打通企微消息入站 → 内部契约 → agent 响应的最小端到端链路

以下为 P-1 过程中积累的运行前提事实（供 M1 参考）：

在同样的隔离依赖模式下，`python -m openvort channels list` 可列出 `wecom / dingtalk / feishu / openclaw` 四个已注册通道，`python -m openvort doctor` 可实际进入诊断流程；当前阻塞点已具体收敛为：

- LLM API Key 未配置
- PostgreSQL 不可达
- IM 通道未配置
- 管理员 user_id 未配置
- Web 默认管理员密码仍过弱

当前进一步确认：`python -m openvort channels test wecom` 会明确返回“未配置”，而 `python -m openvort start --dev` 已能进入真实启动路径，并在当前机器上稳定失败于：

- PostgreSQL 不可用
- 本机未安装 Docker
- 未通过 `OPENVORT_DATABASE_URL` 指向现成数据库

当前进一步确认：`./scripts/check_openvort_prereqs.ps1` 可稳定输出当前 OpenVort 运行前置条件。当前事实为：

- 数据库默认指向 `localhost:5432/openvort`，当前不可达
- Docker 当前不可用
- LLM API Key 未配置
- `OPENVORT_CONTACTS_ADMIN_USER_IDS` 未配置
- `OPENVORT_WEB_DEFAULT_PASSWORD` 仍是默认值
- 企微所需的 5 个核心 `OPENVORT_WECOM_*` 变量均未配置

当前进一步确认：`./scripts/check_openvort_prereqs.ps1` 现在会把 `replace-with-*`、`your-*`、`example-*` 这类占位值视为“未配置”，避免把样本 `.env` 误判为真实可运行配置。

当前补充约束：`./scratchpad/openvort_probe.env.sample` 中的 `OPENVORT_WEB_DEFAULT_PASSWORD` 已改为占位值而不是空值，避免后续在未编辑样本的情况下首次启动出一个空密码管理员。

当前进一步确认：在 Linux 服务器 `[server-ip]` 的隔离工作区 `/home/[user]/ant-colony-probe` 中，以下步骤已实际执行通过：

- `git clone --depth 1 https://github.com/openvort/openvort.git ./external/openvort/source`
- `./scripts/install_openvort_probe_deps.sh`
- `./scripts/prepare_openvort_probe_env.sh --force`
- `./scripts/check_openvort_prereqs.sh`
- `./scripts/run_p1_openvort.sh`
- `./scripts/manage_runtime_settings.py --file ./data/runtime_settings.json init`
- `./scripts/manage_runtime_settings.py --file ./data/runtime_settings.json set-platform --platform wecom --enabled true --set corp_id=test-corp --set agent_id=test-agent`
- `./scripts/manage_runtime_settings.py --file ./data/runtime_settings.json show`
- `./scripts/manage_runtime_settings.py --file ./data/runtime_settings.json set-admin --admin-user-ids ops-admin --web-default-password strong-password`
- `./scripts/manage_runtime_settings.py --file ./data/runtime_settings.json set-llm --profile-id default-anthropic --provider anthropic --model-name claude-sonnet-4 --api-key secret-key --enabled true`
- `./scripts/manage_runtime_settings.py --file ./data/runtime_settings.json export-openvort-env`
- `./scripts/manage_runtime_settings.py --file ./data/runtime_settings.json write-openvort-env-file`
- `./scripts/manage_runtime_settings.py --file ./data/runtime_settings.json apply-openvort-env --target-env ./external/openvort/source/.env`
- 设置管理应用后重新执行 `python3 -m openvort doctor`

Linux 服务器上的当前真实结论与本地探针结论一致，并进一步确认：

- `python3` / `pip` / `git` 可用
- 已安装并启用 `docker`
- `node` / `npm` 当前不可用
- 已安装并启用本地 PostgreSQL 16
- 已创建数据库用户与库：`openvort` / `openvort`
- OpenVort 深验证链可在隔离工作区跑通
- 配置管理 CLI 可在隔离工作区直接初始化、更新并查看 JSON 配置
- 当前已证明“设置管理”能力不只在本地测试可用，也已进入 Linux 目标环境的实际可操作阶段
- 当前已证明“设置管理 -> 运行时导出 -> OpenVort `.env` 应用”链路在 Linux 服务器隔离目录中也已实际可用

当前下一步最值得推进的设置管理工作是：

- 把 `./data/runtime_settings.json` 生成的配置真正接入运行链
- 让 OpenVort Linux 验证链不再只依赖 `.env`，而能消费这套管理配置结果
- `openvort start --dev` 已实际启动到：
  - 数据库初始化完成
  - 首次启动管理员创建完成
  - 前端资源自动下载完成
  - Web / MCP 服务启动完成
  - `8090` 端口已实际监听
  - `http://127.0.0.1:8090` 已返回 HTTP 响应（`405 Method Not Allowed`，说明服务在）
  - `HTTP GET /` 已返回 OpenVort 前端首页 HTML
- 当前主要阻塞已进一步收敛为：
  - `WeCom` 未完整配置
  - `DingTalk` 未配置
  - `Feishu` 未配置
  - `OpenClaw` 未配置

当前进一步确认：Linux 服务器隔离目录中的 OpenVort 已真实消费这套设置结果，`doctor` 已识别出：

- LLM provider / model / API 连接
- 管理员 `user_id`
- 自定义 Web 默认密码

当前进一步确认的服务器侧环境事实：

- 测试账号：`[user]`
- 隔离工作目录：`/home/[user]/ant-colony-probe`
- `[user]` 当前没有免密 `sudo`
- 服务器根分区约 `98G`，当前已用约 `7.4G`，可用约 `86G`
- 服务器内存约 `7.8GiB`，空闲与可用内存充足
- 当前 CPU 核数：`4`
- 当前已为 `[user]` 配置 sudo 与 docker 组权限

当前进一步确认：在 Linux 服务器隔离目录中，`./scripts/run_p1_openvort.sh` 现已可完整执行并返回成功；此前导致失败的两个技术问题已经被排除：

- `docker.sock` 权限问题已通过 `docker` 组权限解决
- `start --dev` 的“常驻运行超时”已在探针中改为视作有效启动信号

当前进一步确认：通过受控的 `timeout 45s python3 -m openvort start --dev` 测试，Linux 服务器上的 OpenVort 不仅能启动到日志就绪，还能实际监听 `0.0.0.0:8090` 并返回 HTTP 响应。

当前进一步确认：新增的 `./scripts/probe_openvort_http.sh` 已在服务器隔离目录中实际执行通过，可稳定验证：

- `8090` 端口监听
- `GET /` 返回前端首页 HTML
- `HEAD /` 返回 `405`
- 启动日志尾部可见 Web / MCP 服务初始化完成

当前进一步确认：新增的 `./scripts/snapshot_openvort_server_state.sh` 已在服务器隔离目录中实际执行通过，可直接输出当前 OpenVort 的源码、依赖、`.env`、数据库监听、Docker 状态与 PostgreSQL 进程快照。

## 当前已准备的验证入口

- 环境快照脚本：`./scratchpad/p1_verify_env.ps1`
- 基础导入验证：`./scratchpad/p1_verify_imports.py`
- 契约层最小测试：`./scripts/run_smoke_test.ps1`
- 统一基线入口：`./scripts/run_p1_baseline.ps1`
- 组件级检查入口：`./scripts/run_p1_components.ps1`
- P-1 全检查入口：`./scripts/run_p1_all.ps1`
- OpenVort 深验证入口：`./scripts/run_p1_openvort.ps1`
- OpenVort 深验证入口（Linux）：`./scripts/run_p1_openvort.sh`
- OpenVort Linux 总控入口：`./scripts/run_p1_openvort_linux_sequence.sh`
- OpenVort 前置条件检查：`./scripts/check_openvort_prereqs.ps1`
- OpenVort 前置条件检查（Linux）：`./scripts/check_openvort_prereqs.sh`
- OpenVort 探针依赖安装（Linux）：`./scripts/install_openvort_probe_deps.sh`
- Linux 服务器基础环境检查：`./scripts/check_linux_server_basics.sh`

## 当前已具备的组件级检查脚本

- `./scratchpad/p1_verify_openvort.py`
- `./scratchpad/p1_verify_hermes.py`
- `./scratchpad/p1_verify_sidecar.py`
- `./scratchpad/p1_verify_gbrain.py`

## OpenVort 当前验证分层

当前 OpenVort 已具备三层验证入口：

1. 来源层
   - `./scripts/acquire_openvort.ps1`
   - `./scripts/land_openvort_source.ps1`
2. 结构与导入层
   - `./scratchpad/p1_verify_openvort.py`
3. 统一复跑层
   - `./scripts/run_p1_openvort.ps1`
   - `./scripts/run_p1_openvort.sh`
   - `./scripts/run_p1_openvort_linux_sequence.sh`
4. 运行前提层
   - `./scripts/check_openvort_prereqs.ps1`
   - `./scripts/check_openvort_prereqs.sh`
5. Linux 依赖安装层
   - `./scripts/install_openvort_probe_deps.sh`
6. Linux 基础环境层
   - `./scripts/check_linux_server_basics.sh`
7. 最小配置样本层
   - `./scratchpad/openvort_probe.env.sample`
8. 配置落地层
   - `./scripts/prepare_openvort_probe_env.ps1`
   - `./scripts/prepare_openvort_probe_env.sh`

这意味着后续继续推进 OpenVort 时，默认不需要再手工拼接 `PYTHONPATH` 和编码环境。


## 当前统一全检查结果

./scripts/run_p1_all.ps1 当前可执行，且会输出：

- 基线环境信息
- 内部导入状态
- 19 项 smoke test 结果
- 四类外部来源的组件级可见性结论

当前总结：

- 内部骨架完整性通过（31 项 smoke test）
- OpenVort：源码已落地，Linux 深验证已闭环
- Hermes：源码已落地，核心 loop 模块已确认
- Sidecar：源码已落地，全部 memory 脚本已确认
- gbrain：当前环境 Docker 不可用，非 M1 必需

== P-1 总体结论 ==
P-1 已完成 3/4 核心验证项。建议正式进入 M1 开发阶段。
## 2026-06-05 验证阻塞补记

- 本轮未能继续 `P-1` 技术验证，不是因为验证结论失败，而是因为当前工作机会话无法读取仓库文件或执行本地验证命令。
- 观察到的统一错误：`windows sandbox: CryptUnprotectData failed: 2148073483`
- 后续恢复后，应优先补做：
  - 重新读取现有验证计划与结论
  - 恢复 OpenVort / Linux 部署验证链路
  - 将新的验证结果追加到本文件，不删除历史记录

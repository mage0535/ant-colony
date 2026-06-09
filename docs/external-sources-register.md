# 外部来源登记表

## 目标

为所有进入 `ant colony` 工作区的外部来源建立统一登记，避免后续出现：

- 不知道某个外部源码从哪里来
- 不知道某个安装包是哪个版本
- 不知道某个本地服务如何启动
- 不知道不同协作者使用的来源是否一致

---

## 使用规则

每当以下任一情况发生时，都应更新本文件：

1. 新接入一个外部项目或外部服务
2. 外部来源的获取方式变化
3. 版本变化
4. 路径变化
5. 启动方式变化

---

## 当前登记项

### 1. OpenVort

- 状态：`已获取，待接缝验证`
- 获取方式：`源码接入（当前工作区默认）`
- 建议方式：`通过 ./scripts/acquire_openvort.ps1 与 ./scripts/land_openvort_source.ps1 拉取上游仓库`
- 当前工作区落点：`./external/openvort/source`
- 版本：`master @ 7beee903f1f8558c1a5d590d33cb6fbfd4cc1438`
- 启动/验证方式：`./scratchpad/p1_verify_openvort.py`
- 当前负责人：`待定`
- 备注：
  - 当前环境探针结论：`openvort` 仍不可直接导入
  - 当前获取探测结论：`pip index versions openvort` 未找到可用分发
  - 当前已确认可访问的上游仓库：`https://github.com/openvort/openvort.git`
  - 当前已确认的远端默认分支：`master`
  - 当前探测到的远端 HEAD commit：`7beee903f1f8558c1a5d590d33cb6fbfd4cc1438`
  - 当前本地已生成元数据文件：`./external/openvort/source-metadata.json`
  - 当前已验证：在 `./scratchpad/vendor/openvort_probe/` 提供隔离依赖后，关键模块可通过 source-path import 成功导入
  - 当前已验证：通过 `./scripts/run_p1_openvort.ps1` 提供的统一环境，`openvort` 顶层包可导入
  - 当前已验证：在同样的隔离依赖模式下，`python -m openvort --help` 可成功输出 CLI 命令树
  - 当前已验证：`python -m openvort channels list` 可列出 4 个已注册通道，`python -m openvort doctor` 可进入真实诊断流程
  - 当前已验证：`python -m openvort channels test wecom` 会直接暴露“未配置”状态，`python -m openvort start --dev` 会稳定失败在 PostgreSQL / Docker 前置条件
  - 当前 `doctor` 暴露的主要阻塞：LLM API Key 未配置、PostgreSQL 不可达、IM 通道未配置、管理员 user_id 未配置、Web 默认管理员密码过弱
  - 当前 `./scripts/check_openvort_prereqs.ps1` 暴露的主要阻塞：数据库默认地址不可达、Docker 不可用、LLM key 未配、管理员 user_id 未配、Web 默认密码未改、企微 5 个核心变量未配
  - 当前 `./scripts/check_openvort_prereqs.ps1` 已按占位值规则校正，不会把样本配置误判为真实可运行配置
  - 当前 Linux 服务器验证补充事实：`codexcheck` 无免密 sudo，服务器未发现现成 PostgreSQL / Docker / Node / npm
  - 下一步应基于当前源码 checkout 做更深的启动与通道验证，而不是继续停留在获取阶段

### 2. Hermes Agent

- 状态：`已获取，待接缝验证`
- 获取方式：`源码接入（git clone --depth 1）`
- 建议方式：`./external/hermes/source`
- 当前工作区落点：`./external/hermes/source`
- 版本 / commit：`main @ 150687447bc9e01a028c3dedf9589406cc321a4f`
- 启动/验证方式：`./scratchpad/p1_verify_hermes.py`
- 当前负责人：`待定`
- 备注：
  - 当前已验证：源码目录存在，元数据文件存在
  - 当前已验证：agent/conversation_loop.py 核心循环可用
  - 当前已验证：全 10 个关键 agent 模块（conversation_loop、prompt_builder、tool_executor、memory_manager、context_engine、system_prompt 等）全部存在
  - 当前已验证：providers/、gateway/ 等关键目录存在
  - 当前已验证：pyproject.toml 与 setup.py 存在，可用于依赖提取
  - 当前已验证：agent/ 目录总计 88 个模块，结构完整
  - 下一步：将核心 loop 抽取为独立引擎供 M1 使用

### 3. Memory Sidecar

- 状态：`已获取，待接缝验证`
- 获取方式：`源码接入（git clone --depth 1）`
- 建议方式：`./external/sidecar/source`
- 当前工作区落点：`./external/sidecar/source`
- 版本 / commit：`main @ 432bfba91789e358b754bf7fb5f0e3f533b9dfb2`
- 启动/验证方式：`./scratchpad/p1_verify_sidecar.py`
- 当前负责人：`待定`
- 备注：
  - 当前已验证：源码目录存在，元数据文件存在
  - 当前已验证：全 13 个关键 memory 脚本（tiered_context_injector、session_to_gbrain、memory_lifecycle、domain_memory、memory_guard、compact_memory 等）全部存在
  - 当前已验证：install.sh 存在，支持多目录独立安装
  - 当前已验证：config/、skills/、templates/、tests/ 目录均存在
  - 下一步：验证多目录安装隔离，确认单人 Sidecar 可独立初始化

### 4. gbrain

- 状态：`待启动`
- 获取方式：`待确认`
- 建议方式：`本地服务启动`
- 当前工作区落点：`未落地`
- 版本：`未确认`
- 启动/验证方式：`./scratchpad/p1_verify_gbrain.py`
- 当前负责人：`待定`
- 备注：
  - 当前环境探针结论：`http://localhost:8787` 不可达
  - 当前环境附加结论：`Docker` 不可用，需先明确 gbrain 运行方式

---

## 当前统一状态摘要

基于当前 P-1 组件级探针：

- OpenVort：源码已落地 `./external/openvort/source`，Linux 深验证链已闭环
- Hermes：源码已落地 `./external/hermes/source`，核心 10 个 agent 模块已确认
- Memory Sidecar：源码已落地 `./external/sidecar/source`，全 13 个 memory 脚本已确认
- gbrain：当前环境 Docker 不可用，本地服务不可达（需在 M2 或 Linux 服务器上解决）

这意味着当前最需要优先做的，不是继续增加更多探针，而是：

1. 明确四类来源的获取方式
2. 明确源码或服务在工作区中的稳定落点
3. 基于已落地的 OpenVort 源码继续推进更深验证

---

## 一句话要求

**没有写进这个登记表的外部来源，不应默认视为团队已统一接入。**

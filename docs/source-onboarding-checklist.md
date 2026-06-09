# 外部来源落地清单

## 目标

把“外部来源优先级”进一步变成可执行的落地动作，降低后续协作者开始真正接入 OpenVort、Hermes、Memory Sidecar、gbrain 的启动成本。

---

## 总体顺序

当前默认顺序：

1. OpenVort
2. Hermes
3. Memory Sidecar
4. gbrain

---

## 1. OpenVort 落地清单

### 目标

确认 `openvort` 能否以最小成本进入当前工作区并支持后续通道验证。

### 待做

- [x] 确认是否存在可用的 `pip` 安装来源
- [x] 如果不存在或不可控，转为源码接入方案
- [x] 如转为源码接入，优先落到 `./external/openvort/source`
- [x] 将获取方式写入 `./docs/external-sources-register.md`
- [x] 补充对应的验证脚本或安装脚本
- [x] 增加统一深验证入口：`./scripts/run_p1_openvort.ps1`
- [x] 增加统一前置条件入口：`./scripts/check_openvort_prereqs.ps1`
- [x] 增加 Linux 深验证入口：`./scripts/run_p1_openvort.sh`
- [x] 增加 Linux 总控入口：`./scripts/run_p1_openvort_linux_sequence.sh`
- [x] 增加 Linux 前置条件入口：`./scripts/check_openvort_prereqs.sh`
- [x] 增加 Linux 依赖安装入口：`./scripts/install_openvort_probe_deps.sh`
- [x] 增加 Linux 服务器基础环境检查入口：`./scripts/check_linux_server_basics.sh`
- [x] 增加最小配置样本：`./scratchpad/openvort_probe.env.sample`
- [x] 增加配置落地脚本：`./scripts/prepare_openvort_probe_env.ps1`
- [x] 增加 Linux 配置落地脚本：`./scripts/prepare_openvort_probe_env.sh`
- [x] 当前 P-1 阶段先冻结为 `source-path + vendor deps` 模式，editable install 留待 Linux 服务器环境再评估
- [ ] 为 OpenVort 准备可达 PostgreSQL，或提供替代 `OPENVORT_DATABASE_URL`
- [x] 准备最小 WeCom 配置样本，用于真实通道级验证

### 完成标准

- 至少有一种可复现的获取方式
- 当前机器或目标机器上可验证其存在
- 当前工作区内可复跑“深验证 + 前置条件检查”
- 当前 Linux 服务器路径上已有“基础环境 -> 依赖安装 -> 配置落地 -> 前置条件 -> 深验证”的顺序化入口

---

## 2. Hermes 落地清单

### 目标

为后续 `AgentEngine` 与 loop 抽取提供稳定源码来源。

### 待做

- [ ] 决定采用 `subtree`、`vendor` 还是外部引用
- [ ] 如采用源码落地，优先放到 `./external/hermes/`
- [ ] 在登记表中记录来源、commit、负责人
- [ ] 拿到源码后补充“loop 可抽取性”验证脚本

### 完成标准

- 当前工作区中存在统一的 Hermes 来源
- 后续协作者不需要猜 Hermes 在哪

---

## 3. Memory Sidecar 落地清单

### 目标

为后续个人/项目知识域与记忆体接入提供稳定来源。

### 待做

- [ ] 决定采用 `subtree`、`vendor` 还是固定安装脚本
- [ ] 如采用源码落地，优先放到 `./external/sidecar/`
- [ ] 记录后续多目录安装验证方式
- [ ] 在登记表中更新来源与负责人

### 完成标准

- 当前工作区中存在统一的 Sidecar 来源或固定安装方案
- 多目录安装验证具备起点

---

## 4. gbrain 落地清单

### 目标

确认 gbrain 的真实运行方式和验证环境。

### 待做

- [ ] 确认当前机器是否必须依赖 Docker
- [ ] 如果当前机器不适合运行，明确替代验证环境
- [ ] 记录启动方式、端口、验证方式
- [ ] 在登记表中更新服务获取与运行方式

### 完成标准

- 至少明确 gbrain 该在哪种环境中被验证
- 不再停留在“localhost 不可达”的模糊状态

---

## 当前最重要的一句话

**下一步不是继续扩写更多骨架，而是先把 OpenVort 的获取方式真正落地。**

# OpenVort Linux Validation

## 目标

在最终目标环境 `Linux 服务器` 上，对 `./external/openvort/source` 做最小可复现的 P-1 验证。

这份说明只关注当前已经脚本化的内容，不展开生产部署细节。

## 当前适用范围

- 已获取 OpenVort 源码到 `./external/openvort/source`
- 准备在 Linux 服务器上验证：
  - 探针依赖能否安装
  - `.env` 能否落地
  - PostgreSQL / Docker / LLM / WeCom 前置条件是否满足
  - OpenVort 深验证链能否跑通

## 当前说明边界

- 当前 `.sh` 脚本已经补齐到项目中：
  - `./scripts/install_openvort_probe_deps.sh`
  - `./scripts/check_openvort_prereqs.sh`
  - `./scripts/prepare_openvort_probe_env.sh`
  - `./scripts/run_p1_openvort.sh`
- 这些脚本的目标是 Linux 服务器环境
- 当前 Windows 本地工作机没有 `bash`，因此这些 `.sh` 入口目前属于“已编写、待 Linux 服务器验证”，不应误读为“已在本机执行通过”

## 推荐顺序

1. 检查 Linux 服务器基础环境
   - 运行 `./scripts/check_linux_server_basics.sh`
2. 准备源码
   - 确认 `./external/openvort/source` 已存在
3. 安装 Linux 探针依赖
   - 运行 `./scripts/install_openvort_probe_deps.sh`
4. 准备最小配置文件
   - 运行 `./scripts/prepare_openvort_probe_env.sh`
5. 填写真实配置
   - 编辑 `./external/openvort/source/.env`
6. 检查前置条件
   - 运行 `./scripts/check_openvort_prereqs.sh`
7. 执行深验证
   - 运行 `./scripts/run_p1_openvort.sh`

## 当前闭环状态

当前项目内已经具备 Linux 服务器验证闭环的脚本入口：

1. `./scripts/check_linux_server_basics.sh`
2. `./scripts/install_openvort_probe_deps.sh`
3. `./scripts/prepare_openvort_probe_env.sh`
4. `./scripts/check_openvort_prereqs.sh`
5. `./scripts/run_p1_openvort.sh`

这意味着下一位接手者在 Linux 服务器上不需要先自行设计验证顺序，只需要按上面的顺序推进即可。

如果希望一条命令顺序执行当前闭环，可直接使用：

- `./scripts/run_p1_openvort_linux_sequence.sh`

如果希望快速确认服务器当前已经做到哪里，可直接使用：

- `./scripts/snapshot_openvort_server_state.sh`

如果希望短时间内验证 Web 入口是否真实响应，可直接使用：

- `./scripts/probe_openvort_http.sh`

## 当前预期阻塞

如果直接使用样本配置，当前大概率仍会卡在：

- PostgreSQL 不可达
- Docker 不可用或未安装
- `OPENVORT_LLM_API_KEY` 未配置
- `OPENVORT_CONTACTS_ADMIN_USER_IDS` 未配置
- `OPENVORT_WEB_DEFAULT_PASSWORD` 仍是占位值
- `OPENVORT_WECOM_*` 核心字段未配置

这些属于环境与配置阻塞，不属于源码结构阻塞。

## 当前已确认的服务器事实

基于当前对 `[server-ip]` 上测试账号 `[user]` 的只读探测：

- 系统：`Ubuntu 24.04.4 LTS`
- Python：`python3` 可用
- `pip` / `git` 可用
- `docker` 当前不可用
- `node` / `npm` 当前不可用
- 账号当前没有免密 `sudo`
- 已存在隔离验证目录：`/home/[user]/ant-colony-probe`
- 当前未发现现成 PostgreSQL 客户端、服务进程或 `5432` 监听

因此当前更适合继续做“隔离工作区验证 + 配置准备”，而不应假设服务器已经具备 OpenVort 的完整运行依赖。

## 当前推荐路径

基于当前服务器事实，推荐优先级如下：

1. 优先提供一个可达的现成 PostgreSQL
   - 原因：
     - `[user]` 当前没有免密 `sudo`
     - 服务器未安装 Docker
     - 不需要先改系统级运行环境
2. 其次再考虑安装 Docker
   - 适用条件：
     - 你确认这台机器允许新增 Docker，且不会影响现有业务
     - 能接受 OpenVort 通过 Docker 自动拉起 PostgreSQL 的路径
3. 当前不优先推进前端相关依赖
   - 原因：
     - `node` / `npm` 当前缺失
     - P-1 现阶段的关键阻塞不在前端

一句话：

**当前最短路径不是先补全整台服务器的依赖，而是先拿到一个可达 PostgreSQL，把 OpenVort 从“环境阻塞”推进到“真实业务接缝验证”。**

## 当前脚本职责

- `./scripts/check_linux_server_basics.sh`
  - 检查 Linux 服务器上是否具备 Python / pip / git / Docker / Node / npm
- `./scripts/install_openvort_probe_deps.sh`
  - 安装 OpenVort 探针依赖到 `./scratchpad/vendor/openvort_probe`
- `./scripts/prepare_openvort_probe_env.sh`
  - 将 `./scratchpad/openvort_probe.env.sample` 复制到 `./external/openvort/source/.env`
- `./scripts/check_openvort_prereqs.sh`
  - 检查数据库、Docker、LLM、管理员、Web 密码与 WeCom 核心字段
- `./scripts/run_p1_openvort.sh`
  - 复跑当前 OpenVort 深验证链
- `./scripts/run_p1_openvort_linux_sequence.sh`
  - 串联执行当前 Linux 服务器上的 OpenVort P-1 验证闭环
- `./scripts/snapshot_openvort_server_state.sh`
  - 查看当前服务器上的 OpenVort 部署现状快照
- `./scripts/probe_openvort_http.sh`
  - 临时拉起 `start --dev` 并探测 `8090` 的 HTTP 响应

## 记录要求

如果 Linux 服务器上完成了新的验证结论，至少同步更新：

- `./docs/p1-verification.md`
- `./docs/external-sources-register.md`
- `./docs/handoff.md`

## 一句话结论

当前 Windows 本地环境已经把 OpenVort 验证链脚本化；Linux 服务器上的下一步重点不是重做来源获取，而是按这份顺序验证真实环境与配置是否满足运行条件。

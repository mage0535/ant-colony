#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== OpenVort Linux P-1 sequence =="
echo "1/5 基础环境检查"
bash ./scripts/check_linux_server_basics.sh

echo
echo "2/5 安装探针依赖"
bash ./scripts/install_openvort_probe_deps.sh

echo
echo "3/5 准备最小配置"
bash ./scripts/prepare_openvort_probe_env.sh

echo
echo "4/5 检查运行前置条件"
bash ./scripts/check_openvort_prereqs.sh

echo
echo "5/5 执行 OpenVort 深验证"
bash ./scripts/run_p1_openvort.sh

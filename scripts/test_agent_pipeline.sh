#!/bin/bash
# AgentEngine 端到端验证脚本
# 用法: bash scripts/test_agent_pipeline.sh
# 测试网关 API: 直接创建任务 + 查看列表 + 状态流转
set -e

BASE="http://127.0.0.1:18090"

echo "=== 1. 直接创建任务（POST /tasks）==="
curl -s -X POST "$BASE/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "登录模块重构",
    "project_id": "space-proj-1",
    "assignee_user_id": "lisi",
    "description": "下周五前完成前端+后端改造"
  }' | python3 -m json.tool

echo ""
echo "=== 2. 创建第二个任务 ==="
curl -s -X POST "$BASE/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "写单元测试",
    "project_id": "space-proj-1",
    "assignee_user_id": "zhangsan"
  }' | python3 -m json.tool

echo ""
echo "=== 3. 查看任务列表 ==="
curl -s "$BASE/tasks?space_id=space-proj-1" | python3 -m json.tool

echo ""
echo "=== 4. 开始第一个任务（PUT /transition）==="
TASK_ID=$(curl -s "$BASE/tasks?space_id=space-proj-1" | python3 -c "import sys,json; tasks=json.load(sys.stdin)['tasks']; print(tasks[0]['id'])")
echo "Task ID: $TASK_ID"
curl -s -X PUT "$BASE/transition" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$TASK_ID\", \"status\": \"in_progress\"}" | python3 -m json.tool

echo ""
echo "=== 5. 查看健康状态 ==="
curl -s "$BASE/health" | python3 -m json.tool

echo ""
echo "=== 完成: AgentEngine 最小可运行通过 ==="

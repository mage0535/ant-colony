# Ant Colony — 工具清单 (Tool Manifest)
> 所有员工共享的工具集。智能体工作前加载此清单确定可用工具。

---

## 一、内置工具（已注册，直接可用）

| 工具 ID | 触发词 | 说明 |
|---------|--------|------|
| `builtin:now` | "现在几点" | 返回当前时间 |
| `builtin:echo` | 测试 | 回声测试 |
| `builtin:create_draft` | "创建一个任务" | 创建任务并自动确认 |
| `builtin:search_knowledge` | "搜索知识库" | 全文搜索 FTS5 知识库 |
| `builtin:query_tasks` | "我的任务" | 查询任务列表 |
| `builtin:query_attendance` | "我的考勤" | 个人考勤打卡记录 |
| `builtin:query_leave` | "我的审批" | 个人请假/外出/审批记录 |
| `builtin:tushare` | "平安银行股票" / "上证指数" | A 股/港股行情、K 线数据 |
| `builtin:web_search` | "今天天气" / "搜索新闻" | Bing 互联网搜索 |
| `builtin:query_dept` | "部门考勤" | 部门负责人查下属全部数据 |
| `builtin:query_subordinate` | "马戈的考勤" | 部门负责人按姓名查特定下属 |

## 二、记忆体服务（后端就绪）

| 层 | 服务 | 端口 | 协议 |
|----|------|------|------|
| Hot | Sidecar 文件 | — | JSON 文件 |
| Warm | Hindsight | 8890 | HTTP REST API |
| Cold | gbrain | 8787 | JSON-RPC MCP API |
| Embedding | Embedding | 8766 | HTTP POST |

## 三、外部 MCP 服务器（需安装/配置）

| 工具 | 安装状态 | 所需 | 备注 |
|------|---------|------|------|
| scrapling | ✅ 已安装 | Python 包 | 网页爬虫/反爬 |
| Chrome DevTools | ❌ 未安装 | Chrome 浏览器 | 需安装 Chrome |
| AnySearch | ⏳ 密钥已存，域名不可达 | `ANYSEARCH_API_KEY` | 垂直搜索（端点待确认） |
| Tushare | ✅ 已接入 | `24d3...` | 股票行情/金融数据 |
| CodeGraph | ⏳ 需 Node.js | — | 代码分析 |
| headroom | ❌ 未安装 | — | 内容压缩 |
| Horizon | ❌ 未安装 | — | AI 科技资讯 |

## 四、脚本工具（部署在 external/sidecar/scripts/）

| 脚本 | 用途 |
|------|------|
| `session_to_gbrain.py` | 将会话归档到 gbrain 知识图谱 |
| `tiered_context_injector.py` | 三层记忆融合注入 |
| `memory_watermark.py` | 记忆体水位检测 |
| `memory_snapshot_backup.py` | 快照备份 |
| `memory_maintenance_cycle.py` | 完整记忆维护周期 |
| `memory_governance_rebuild.py` | 索引重建 |
| `sync_embeddings.py` | 向量同步 |
| `skill_forge.py` | 网站结构探测 |
| `book_cache_manager.py` | 书籍缓存管理 |
| `book_to_skill.py` | PDF→Skill 提取 |

## 五、工具预检

智能体开始工作前执行：
1. `curl -s http://localhost:8787/health` — gbrain 健康
2. `curl -s http://localhost:8890/health` — Hindsight 健康
3. `systemctl is-active gbrain-bridge hindsight-bridge` — 服务状态

## 六、安装待完成项

```bash
# Chrome DevTools (需 Chrome 浏览器)
sudo apt install -y google-chrome-stable

# AnySearch (需 API Key)
pip install anysearch-mcp

# Tushare (需 API Token)
pip install tushare-mcp

# CodeGraph (需 Node.js)
npm install -g @anthropic-ai/codegraph-mcp
```

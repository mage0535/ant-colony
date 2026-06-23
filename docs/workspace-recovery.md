# 本地工作区恢复说明

## 背景

当前项目在本地 OneDrive 环境下，曾出现工作区目录和文件被异常清空或部分缺失的情况。

已观察到的缺失范围包括：

- `src/*`
- `tests/*`
- `docs/*`

这类问题不应在残缺树上继续开发，而应优先恢复完整工作区。

## 当前恢复源

默认恢复源为你自己的同步服务器副本：

```text
/opt/ant-colony
```

## 当前恢复脚本

已提供：

- `scripts/restore_workspace_from_server.py`

默认恢复这些关键目录：

- `docs`
- `tests`
- `src/agents`
- `src/config`
- `src/engine`
- `src/gateway`
- `src/guard`
- `src/knowledge`
- `src/models`
- `src/orchestrator`
- `src/platform`
- `src/store`
- `src/tools`
- `src/web`

## 使用方式

### 1. 恢复默认关键目录

```bash
python scripts/restore_workspace_from_server.py --host <server-ip> --user <ssh-user> --password <ssh-password>
```

### 2. 只恢复特定目录

```bash
python scripts/restore_workspace_from_server.py --host <server-ip> --user <ssh-user> --password <ssh-password> --paths src/tools src/gateway tests
```

## 恢复原则

1. 优先恢复缺失目录和关键模块
2. 不在残缺工作区继续做功能开发
3. 恢复后应立即运行定向回归测试
4. 若本地 `.git` 元数据也异常，优先保全工作区内容，再单独处理版本库恢复

## 推荐恢复后动作

```bash
python -m pytest tests/test_document_pipeline.py -q
python -m pytest tests/test_platform_capabilities.py -q
```

## 当前结论

工作区恢复已经被正式脚本化。
后续同事如果再次遇到 OneDrive/本地同步导致的源码缺失，应优先执行恢复脚本，而不是先手工排查单个导入错误。

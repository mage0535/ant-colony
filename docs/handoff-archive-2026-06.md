# 项目交接状态 - 2026-06-16

## 先看这个

### 2026-06-22 current completed step: unified file pairing helpers, extracted platform capability tools, and added adapter startup tests

This round focused on three of the previously identified local-code hotspots without changing the Bot First architecture:

- duplicated file-pairing / document-trigger rules
- oversized `src/tools/builtin.py` platform-capability helper section
- missing regression coverage for Feishu / DingTalk adapter startup

Completed code changes:

- added `src/gateway/file_message_pairing.py`
  - now owns shared file-message assembly and intent rules
  - `InboundGatewayService` and `WeComBotBridge` both use the same helpers for:
    - combined template/request prompt construction
    - file-referential text detection
    - document-generation intent detection
    - document title inference
- added `src/tools/platform_capability_tools.py`
  - extracted platform-facing tool handlers out of `src/tools/builtin.py`
  - current extracted area includes:
    - platform docs / drive / mail / approval / meeting helpers
    - PDF / OCR helpers
    - Office service / template outline / read helpers
- `src/platform/__init__.py`
  - wrappers are now thinner via shared `_invoke_formatted(...)` and `_invoke_first_content(...)`
  - capability backend remains the actual execution path

Completed tests:

- added `tests/test_file_message_pairing.py`
- added `tests/test_platform_capability_tools.py`
- added `tests/test_platform_adapter_startup.py`
- adapter startup coverage now explicitly checks:
  - Feishu starts when credentials are present
  - DingTalk starts when credentials are present
  - unconfigured platforms are skipped cleanly

Important behavior note:

- document generation now keeps two distinct checks:
  - `looks_document_generation_request(...)` for "text first, file later" waiting behavior
  - `should_generate_document_from_content(...)` for "file content already attached" execution behavior
- this prevents a regression where WeCom Bot stopped waiting for late-arriving files after a generation request

Verification:

- focused regression set:
  - `tests/test_file_message_pairing.py`
  - `tests/test_platform_adapter_startup.py`
  - `tests/test_platform_capability_tools.py`
  - `tests/test_platform_capabilities.py`
  - `tests/test_capability_backend.py`
  - `tests/test_document_pipeline.py`
  - `tests/test_wecom_bot_bridge.py`
- result: `104 passed`

Recommended next step:

1. continue decomposing `src/tools/builtin.py` by non-platform domains (task / knowledge / org-admin)
2. decide whether `src/platform/__init__.py` should remain as a permanent compatibility facade or be reduced further
3. restore the missing `docs/m1-plan.md` and `docs/user-manual.md` referenced by the startup protocol, or update the protocol if those files are intentionally retired

### 2026-06-22 current completed step: second builtin split, facade decision, capability audit, adapter deep tests, and repeatable bot regression script

This round completed the remaining local-code follow-up items that were still open after the first split.

Completed structure work:

- `src/tools/builtin.py`
  - continued extraction by domain
  - added dedicated modules:
    - `src/tools/task_tools.py`
    - `src/tools/knowledge_tools.py`
    - `src/tools/org_admin_tools.py`
- `src/platform/__init__.py`
  - explicitly retained as a compatibility facade
  - new tool-layer code can now call:
    - `invoke_capability(...)`
    - `invoke_capability_first(...)`
    - `build_capability_context(...)`

Completed identity/audit work:

- added `src/platform/capability_audit.py`
- capability backend now accepts invocation context and records JSONL audit entries
- current audit context fields:
  - `user_id`
  - `platform`
  - `transport`
  - `scope`
  - `scope_id`
  - `source_chat_id`
- audit file permissions are restricted after writes

Completed platform regression work:

- added deeper adapter tests:
  - `tests/test_feishu_adapter.py`
  - `tests/test_dingtalk_adapter.py`
- covered:
  - Feishu signature verification
  - group-message filtering rules
  - adapter send-message payload shape
  - DingTalk URL verify behavior

Completed delivery/supporting work:

- restored startup-protocol docs:
  - `docs/m1-plan.md`
  - `docs/user-manual.md`
- added repeatable regression runner:
  - `scripts/run_bot_e2e_regression.py`
- added script import-safety coverage for the new runner

Fresh verification evidence:

- targeted structure/platform/audit/script set:
  - `56 passed`
- full local suite:
  - `338 passed`

Current highest-value external follow-up remains:

1. run the new regression runner on the Linux test server against the deployed environment
2. perform real Feishu / DingTalk sandbox callback verification
3. decide whether capability audit should remain file-backed or move to a centralized store

### 2026-06-19 current completed step: local quality and security hardening after build closure

This round performed a second full local audit after the build was already green. It focused on defects that passing unit tests did not previously expose.

Completed behavior fixes:

- Dashboard API access is now fail-closed for remote callers when `ANT_COLONY_AUTH_TOKEN` is missing
- loopback callers remain available for internal service-to-service operations
- every non-public Dashboard route, including GET data and document routes, now runs authentication
- cron parsing now safely handles empty input, compact intervals such as `every 2h`, and integer/wildcard five-field cron expressions with month and weekday matching
- generated document fallback URLs now use `ANT_COLONY_DOCUMENT_BASE_URL`, normalize trailing slashes, and URL-encode filenames
- WeCom online-document search results now include the official document URL
- health output no longer reports a stale hard-coded test count
- Dashboard and WeCom Bot file ingestion enforce `ANT_COLONY_MAX_FILE_BYTES` (default 50 MiB) before storage/parsing

Completed credential and file-security fixes:

- removed literal WeCom attendance credentials from source; use `WECOM_CORP_ID` and `WECOM_SECRET`
- removed the literal Tushare token from source; use `TUSHARE_TOKEN`
- removed weak default PostgreSQL credential URLs; set `GBRAIN_DB_URL` and `HINDSIGHT_DB_URL`
- JSON runtime settings and exported environment files are now restricted to owner read/write permissions (`0600`)
- added AST regression gates against literal secrets/tokens, credential-bearing URLs, and bare `except:` handlers
- removed tracked `.pytest_cache` artifacts and rebuilt the cache cleanly

Important credential action:

- the removed WeCom and Tushare credentials existed in the initial Git commit
- treat both values as exposed and rotate/revoke them before the next deployment
- current working tree and Git index no longer contain those literal assignments
- Git history was not rewritten automatically because that is destructive and requires repository-wide coordination

Local packaging improvement:

- core package dependencies now include the local Office/PDF stack:
  - `python-docx`
  - `openpyxl`
  - `python-pptx`
  - `PyMuPDF`
  - `requests`

Fresh verification evidence:

- `PYTHONPATH=. python -m pytest -q` -> `326 passed`
- compileall plus root entrypoint py_compile -> passed
- Ruff `E9,E722,F821,F823` gate -> passed
- Bandit high-severity scan -> no findings
- `pip-audit .` -> no known vulnerabilities
- `python -m pip check` -> no broken requirements
- isolated sdist -> wheel build -> passed
- wheel inspection -> 134 files, including the secure file-permission helper

Coverage audit:

- total measured line coverage before the final added tests was 44%
- main implemented boundaries were materially higher: capability backend 85%, internal provider 96%, document requirements 90%, document generation 84%
- remaining zero/low coverage is concentrated in external live adapters and legacy modules (Feishu/DingTalk/Telegram network adapters, org-sync real API, legacy department/attendance paths)
- do not treat mocked line coverage as a substitute for real platform sandbox tests

Required deployment environment variables introduced or enforced by this pass:

- `ANT_COLONY_AUTH_TOKEN` for non-loopback Dashboard access
- `ANT_COLONY_DOCUMENT_BASE_URL` when fallback download links must be externally reachable
- `ANT_COLONY_MAX_FILE_BYTES` to override the default 50 MiB upload/download limit
- `WECOM_CORP_ID` and `WECOM_SECRET` for attendance vacation queries
- `TUSHARE_TOKEN` for Tushare access
- `GBRAIN_DB_URL` and `HINDSIGHT_DB_URL` for PostgreSQL memory bridges

Highest-value remaining validation is external rather than local code repair:

1. real WeCom file upload -> instruction -> generated file pushback
2. Feishu and DingTalk sandbox API contract tests
3. Linux systemd restart and environment propagation validation


### 2026-06-19 current completed step: local build, entrypoint, cron, and security closure

This round completed a full local build and verification pass without changing the Bot First architecture.

Build and packaging:

- fixed the invalid setuptools backend in `pyproject.toml`
- fixed package discovery so wheels contain `src` and all nested packages
- packaged the four service launchers and registered console scripts:
  - `ant-colony-gateway`
  - `ant-colony-callback`
  - `ant-colony-dashboard`
  - `ant-colony-wecom-bot`
- declared the runtime dependencies needed by those service entrypoints
- restored the missing `run_wecom_bot.py`
- made all root service entrypoints safe to import
- verified editable installation, wheel, and sdist builds

Reliability and security:

- removed arbitrary shell execution from no-agent cron jobs
- restricted cron execution to explicit internal callables
- migrated the legacy default org-sync curl command to an internal HTTP callable
- fixed cron run-state restoration after process restart
- replaced shell-based systemd health checks with argument-list subprocess calls
- changed callback XML parsing to `defusedxml`
- marked WeCom protocol SHA-1 as non-security hashing
- restricted WeCom Bot attachment downloads to HTTPS URLs
- fixed module shadowing in subordinate vacation-balance lookup
- fixed the unresolved `WarmMemoryStore` type contract
- restored credential ignore rules and removed `infra/.env.wecom` from the Git index while preserving the local file

Fresh verification evidence:

- `PYTHONPATH=. python -m pytest -q` -> `304 passed`
- `python -m compileall -q src tests scripts` plus root entrypoint `py_compile` -> passed
- Ruff `F821,F823` undefined/shadowed-name gate -> passed
- Bandit high-severity scan -> no findings
- `pip-audit .` -> no known vulnerabilities
- isolated `python -m build` -> wheel and sdist succeeded
- wheel inspection -> 133 files including all service launchers and console-script metadata
- `python -m pip check` -> no broken requirements

Residual deployment watch item:

- `src/web/middleware.py` keeps historical compatibility behavior where an empty `ANT_COLONY_AUTH_TOKEN` disables dashboard API authentication. Do not expose port 18092 outside the trusted network without setting this token. A future fail-closed migration must coordinate internal callbacks and existing deployments.

External validation still required before production release:

- real WeCom upload -> instruction -> generated file pushback round trip
- Linux systemd service restart using the newly restored Bot entrypoint


### 2026-06-19 current completed step: cleaned builtin document dead code and closed bare pytest collection boundary

This round completed two maintenance items that were still affecting long-term stability:

- `src/tools/builtin.py`
  - removed the dead legacy document helper bodies left behind after wrapper delegation
  - document-related helper section is now thin wrappers only
- `pyproject.toml`
  - added `testpaths = ["tests"]`
  - added `norecursedirs` so bare `pytest` no longer walks `external/` or `scratchpad/`

Why this matters:
- the codebase now matches the new module boundaries more honestly
- server-side validation no longer depends on remembering to avoid third-party test trees manually
- local and server test commands are now aligned

Verification:
- local: `PYTHONPATH=. pytest -q`
- result: `286 passed`
- test server: `PYTHONPATH=. python3 -m pytest tests -q`
- result: `270 passed`
- test server: `PYTHONPATH=. python3 -m pytest -q`
- result: `270 passed`

Current highest-value remaining improvement directions:
1. continue decomposing `src/tools/builtin.py` by non-document domains
2. normalize legacy mojibake/source-text encoding in older files without changing behavior
3. add a real WeCom end-to-end regression script for file upload -> instruction -> generated file pushback


### 2026-06-19 current completed step: added memo family fallback on top of the extracted document pipeline

This round continued the same document pipeline after `notice` support:

- `src/tools/document_requirements.py`
  - added `memo` family fallback
  - document family inference now distinguishes:
    - `policy`
    - `notice`
    - `memo`
- this means the extracted pipeline is no longer tied to one single enterprise document shape

Verification:
- `PYTHONPATH=. pytest tests/test_document_pipeline.py tests/test_office_capabilities.py tests/test_internal_capability_provider.py tests/test_capability_backend.py tests/test_restore_workspace_script.py -q`
- result: `101 passed`
- `PYTHONPATH=. pytest -q`
- result: `286 passed`
- test server: `PYTHONPATH=. python3 -m pytest tests -q`
- result: `270 passed`

Recommended next step:
1. add `procedure` or `approval` as the fourth document family
2. remove dead legacy helper bodies left behind in `builtin.py`
3. if needed, add a dedicated `pytest` collection boundary so server-side bare `pytest` no longer walks `external/` and `scratchpad/vendor/`


### 2026-06-19 current completed step: extracted document generation orchestration and added notice family fallback

This round completed the next layer after extracting requirement parsing:

- added `src/tools/document_generation_service.py`
  - owns document generation orchestration
  - owns enrichment timeout fallback selection
  - owns file push / bot-file return behavior
- `src/tools/document_requirements.py`
  - now supports generic fallback entry `build_fallback_content(...)`
  - added initial second document family: `notice`
- `src/tools/builtin.py`
  - `_generate_report_handler` now delegates to the new service
  - document requirement helper entry points continue to work for existing callers

Why this matters:
- requirement parsing and generation orchestration are no longer both embedded in `builtin.py`
- the document pipeline now has two explicit boundaries:
  - `requirement parsing / fallback rendering`
  - `generation orchestration / push-back`
- this is enough structure to keep expanding more document families without turning the builtin tool file into the implementation center again

Verification:
- `PYTHONPATH=. pytest tests/test_document_pipeline.py tests/test_office_capabilities.py tests/test_internal_capability_provider.py tests/test_capability_backend.py tests/test_restore_workspace_script.py -q`
- result: `100 passed`
- `PYTHONPATH=. pytest -q`
- result: `285 passed`

Recommended next step:
1. add third document family on the same path: `memo` or `procedure`
2. move remaining dead legacy helper bodies out of `builtin.py` once the wrappers are stable
3. run one real WeCom file+instruction notice-generation roundtrip on the test server


### 2026-06-19 current completed step: extracted document requirement logic from builtin.py

This round completed the next cleanup step after stabilizing document fallback quality:

- added `src/tools/document_requirements.py`
  - owns template/request split
  - owns template excerpt + prompt block assembly
  - owns structured requirement parsing
  - owns policy fallback rendering
- `src/tools/builtin.py`
  - existing helper entry points now delegate to the new module
  - external behavior stays compatible for current gateway/tool callers
- tests now cover direct reuse of the extracted structured parser module

Why this matters:
- document generation logic is no longer only embedded inside `builtin.py`
- next step can extend more document families without growing the builtin tool file further
- this is the first code-level boundary for a future `requirement spec -> render` document pipeline

Verification:
- `PYTHONPATH=. pytest tests/test_document_pipeline.py tests/test_office_capabilities.py tests/test_internal_capability_provider.py tests/test_capability_backend.py tests/test_restore_workspace_script.py -q`
- result: `98 passed`
- `PYTHONPATH=. pytest -q`
- result: `283 passed`

Recommended next step:
1. move `generate_report_handler` orchestration into a dedicated document generation service module
2. add second document family support on top of the same parser/render flow: `notice` or `memo`
3. keep WeCom real roundtrip verification after each document-family expansion


### 2026-06-19 current completed step: structured requirement spec for document fallback

This round continued the document-content mainline and closed the next gap after template-style inheritance:

- `src/tools/builtin.py`
  - added structured requirement parsing for file-driven document requests
  - prompt block now keeps both template outline and template excerpt
  - fallback policy drafting now preserves section headings, primary items, sub-items, and attachment hints
  - short single-sentence requests now still generate a full policy skeleton

Verification:
- `PYTHONPATH=. pytest tests/test_document_pipeline.py tests/test_office_capabilities.py tests/test_internal_capability_provider.py tests/test_capability_backend.py -q`
- result: `95 passed`
- `PYTHONPATH=. pytest -q`
- result: `282 passed`

Recommended next step:
1. move `requirement spec -> render` into a smaller reusable helper/module
2. extend the same structured path to `notice / procedure / approval / memo` document families
3. verify one real WeCom file+instruction roundtrip on the test server


### 2026-06-19 当前已完成的第十二步：制度类文档 fallback 内容质量增强

本轮继续针对“文档内容处理质量”主线推进，重点修复了制度/规定类文档在 fallback 路径下的内容生成质量问题。

之前的真实问题：

- 用户要求中的层级条目（如 `一 / 1 / a / b`）容易被当作并列条目平铺
- 结果会出现类似：
  - `4.3 a xxx`
  - `4.4 b xxx`
- 这类输出虽然能“带上原文内容”，但不符合正式制度文本要求，属于低可用性内容

本轮已完成：

- `src/tools/builtin.py`
  - 重写制度类 fallback 解析与成文 helper
  - 现在会区分：
    - 章节标题
    - 主条目
    - 子条目
  - 子条目会并入父条款，不再作为孤立编号行平铺
  - `通行 / 通讯` 类章节会映射为更正式的章节标题
  - `后附 / 附件` 类提示会保留到正式正文与附则语境中

实际效果：

- fallback 路径不再只是“把原条目重新排版”
- 而是会把用户的结构化要求吸收到条款正文中
- 这更符合项目整体目标里“Bot 前台 + 本地能力后端 + 正式制度化成文”的定位

验证结果：

- `pytest -q`
- 结果：`279 passed`

下一阶段优先建议：

1. 继续把文档生成输入从“长文本”推进到“显式结构化条目”
2. 在模板摘要基础上继续往“模板锚点原位填充”演进
3. 将这套结构化成文能力扩展到更多制度/通知/办法类文档，而不是停留在单一车间场景

### 2026-06-19 当前已完成的第十一步：Stirling-PDF 剩余核心能力继续迁入

本轮继续沿着 “Bot First, Capability Backend” 主线，把已经协议化但仍主要依赖 internal provider 的 PDF 能力继续向本地私有 `Stirling-PDF` 服务迁移。

本轮新增到 `Stirling-PDF` provider 的能力：

- `split_pdf_document`
- `protect_pdf_document`
- `extract_pdf_images`

统一能力后端映射已调整为：

- `files.pdf.split` → `stirling -> internal`
- `files.pdf.protect` → `stirling -> internal`
- `files.pdf.extract_images` → `stirling -> internal`

当前这意味着：

- `files.pdf.merge`
- `files.pdf.split`
- `files.pdf.compress`
- `files.pdf.protect`
- `files.pdf.read`
- `files.pdf.extract_images`
- `files.pdf.watermark`

以上能力均已具备：

- 本地服务优先
- internal provider 兜底
- 统一 capability 协议入口

验证结果：

- `pytest -q`
- 结果：`277 passed`

当前对整体项目目标的进一步推进建议：

1. 优先继续提升“文档内容生成质量”，而不是新增前端入口
   - 当前模板格式继承和本地处理链已经基本成型
   - 下一段更值钱的是把生成输入从纯长文本继续收敛到“结构化条目 + 模板锚点填充”
2. 优先继续扩大“能力后端”的真实 provider 覆盖
   - PDF 已进入本地服务优先阶段
   - 下一批应优先考虑在线文档 / 网盘 / 邮箱，而不是新 UI
3. 保持所有能力都经过统一 capability backend
   - 不再接受新能力直接散落到单个平台分支或单个脚本

### 2026-06-19 当前已完成的第十步：Office 能力补齐 internal fallback

本轮补齐了统一 Office 能力后端中的一个真实缺口：

- 之前 `files.xlsx.generate` / `files.pptx.generate` 在 `internal provider` 中没有接收 `template_path`
- 之前 `internal provider` 缺少：
  - `extract_xlsx_template_outline`
  - `extract_pptx_template_outline`
  - `read_docx_document`
  - `read_xlsx_document`
  - `read_pptx_document`
- 之前统一能力协议里的 Office 能力默认只绑定 `officecli`，一旦 `OfficeCLI` 不可用，就不会自动回退到本地 Python 实现

本轮已完成：

- `src/platform/internal_capability_provider.py`
  - 补齐 `xlsx/pptx` 生成对 `template_path` 的透传
  - 补齐 `xlsx/pptx` 模板结构提取
  - 补齐 `docx/xlsx/pptx` 读取能力
- `src/platform/capability_backend.py`
  - 将以下能力改为 `officecli -> internal` 的统一 fallback 顺序：
    - `files.office.service_status`
    - `files.docx.generate`
    - `files.xlsx.generate`
    - `files.pptx.generate`
    - `files.docx.template_outline`
    - `files.xlsx.template_outline`
    - `files.pptx.template_outline`
    - `files.docx.read`
    - `files.xlsx.read`
    - `files.pptx.read`
- `src/platform/officecli_provider.py`
  - 增加 `healthcheck_office()`，避免 Office 服务状态探针错误复用通用 `healthcheck`

验证结果：

- `pytest tests -q`
- `pytest -q`
- 结果：`274 passed`

额外说明：

- 本轮同时已修复脚本型验收入口的模块副作用问题：
  - 改为标准 `main()` + `if __name__ == "__main__"` 形式
  - 已处理：
    - `scripts/acceptance_test.py`
    - `scripts/integration_test.py`
    - `scripts/e2e_test.py`
  - 现在导入这些脚本不会触发网络请求，也不会在 `pytest` 收集期直接 `sys.exit`
- 后续同事现在可直接使用：
  - `PYTHONPATH=. pytest -q`

项目总方向已正式收敛为：

**Bot First, Capability Backend**

即：

- 员工前端统一为 Bot（企微 / 飞书 / 钉钉）
- 各平台“应用 / 官方 API / 第三方连接器 / 插件”全部作为 Bot 背后的能力后端
- 后续不再继续朝“每个平台都做一个独立前端应用”的方向扩张

后续同事接手时，如遇到设计分歧，默认按这条原则判断：

1. 用户是否必须直接面对某个平台应用？
2. 这个能力能否改为由 Bot 在后台调用？
3. 这个能力是否应沉到统一能力层而不是写死在单个平台分支中？

## 当前状态

- 项目已从“聊天工具 + 局部平台接入”演进为“企业多智能体协作系统”
- Dashboard 已移除，当前主要交互面为聊天前端
- 企微 Bot 文档模板链路已基本可用，模板格式继承问题已大幅收敛
- 文档内容生成仍在持续优化中，当前已增加本地制度成文化兜底
- 测试服务器与本地代码已同步保存

## 当前架构结论

后续架构统一描述为：

- **交互层**：全 Bot 前端
- **编排层**：Agent / Tool / Task / Memory / Knowledge 编排
- **能力层**：平台应用 API、第三方连接器、插件、内部系统

员工只与 Bot 交互，Bot 再去联动：

- 通讯录
- 日历 / 会议
- 审批
- 企业文档
- 在线文档
- 网盘
- 邮箱
- 第三方 SaaS / 内部业务系统

详见：

- `docs/architecture.md`

## 已完成的近期关键工作

### 1. WeCom Bot 主链路已落地

- 新增 `src/gateway/wecom_bot_bridge.py`
- 新增 `run_wecom_bot.py`
- 新增 `infra/wecom-bot.service`
- 新增 `scripts/setup_platform_bots.py`
- 新增 `src/platform/bot_setup.py`

当前结论：

- 企微 AI 主交互入口应优先走 Bot
- 自建应用保留为企业能力后端，而不是主前端

### 2. 文档模板生成链路已升级

- `src/gateway/wecom_file_handler.py`
  - 模板文件保留
  - `latest_template.json` 指针机制
  - 现在返回模板元数据，供后续链路继续使用
- `src/gateway/inbound_service.py`
  - 文件缓冲已携带模板路径
  - 生成文档时会把模板路径传到文档工具链路
- `src/tools/document_tool.py`
  - 从“清空正文重建”升级为“克隆模板段落骨架 + 前言保留 + 前置表格回填”
- `src/tools/builtin.py`
  - 模板提示改用结构摘要而不是整段模板正文
  - 外部长文扩写超时时，增加制度成文化本地兜底

### 3. 测试与归档

已补回归测试：

- `tests/test_document_pipeline.py`
- `tests/test_document_download_path.py`
- `tests/test_wecom_bot_bridge.py`
- `tests/test_platform_bot_setup.py`

本地保存：

- git commit: `7f7678b`
- message: `feat: save bot and template generation updates`

测试服务器保存：

- `<backup-archive-path>`

## 当前代码层的第一步落点

当前 `src/platform/__init__.py` 仍然是“按平台尝试调用”的散函数聚合模式。

这能工作，但不是最终形态。后续要逐步迁移到：

- `src/platform/capability_backend.py`
- `src/platform/api_*.py`
- `src/platform/bridges/*`
- `src/platform/plugins/*`

其中：

- `capability_backend.py` 作为统一能力入口
- 旧工具函数继续保留兼容，避免大面积回归

### 2026-06-16 当前已完成的第一步代码改造

已新增：

- `src/platform/capability_backend.py`
- `tests/test_capability_backend.py`

并已将 `src/platform/__init__.py` 改为通过统一能力后端聚合：

- 联系人
- 日历
- 文档
- 审批
- 会议

这一步仍保持对现有 `builtin` 工具函数兼容，不要求一次性迁完全部平台能力。

当前第一版能力协议包括：

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
- `drive.search`（占位，待接企业网盘）
- `mail.summary`（占位，待接企业邮箱）
- `files.pdf.*`（待协议化，当前仍以零散 PDF 工具为主）

### 2026-06-16 当前已完成的第二步代码改造

已新增：

- `src/platform/internal_capability_provider.py`
- `tests/test_internal_capability_provider.py`
- `tests/test_platform_capabilities.py`

当前统一能力后端不再只依赖外部平台 API，还可以挂接内部企业能力：

- `drive.search`
  - 当前先走本地云盘注册信息与同步体系
- `mail.summary`
  - 当前先走本地邮箱工具（IMAP 搜索 / 收件箱汇总）

同时已明确：

- PDF 不再视为附属格式
- 后续文档域与文件处理域必须把 PDF 能力正式纳入统一能力协议

这意味着后续扩展能力域时，可以同时接：

- 平台官方能力
- 第三方连接器
- 本地已有内部工具

### 2026-06-17 当前已完成的第三步代码改造

统一能力后端已补充“能力发现”能力：

- `CapabilityBackend.list_capabilities()`
- `CapabilityBackend.describe_capability()`
- `src.platform.list_capabilities()`
- `builtin:list_capabilities`

作用：

- 可直接查看当前已注册能力协议
- 可查看每个能力协议由哪些 provider 提供
- 后续同事排查“某个能力为什么没生效”时，不必先翻代码

### 2026-06-17 当前已完成的第四步文档统一

已统一入口文档主叙事：

- `README.md`
- `AGENTS.md`
- `data/heartbeat-state.json`

当前统一后的结论是：

- README 对外主叙事已改为 Bot First
- AGENTS 对接手同事的默认架构认知已改为 Bot First
- `heartbeat-state.json` 已补为存在状态文件，避免启动规则引用到缺失文件

这意味着后续同事若按启动规则读取入口文档，不会再先看到旧的“多前端 / Dashboard / callback 主入口”心智。

### 2026-06-17 当前已完成的第五步 PDF 能力协议化

已将现有 PDF 零散工具正式接入统一能力后端第一版：

- `files.pdf.merge`
- `files.pdf.split`
- `files.pdf.compress`
- `files.pdf.protect`
- `files.pdf.read`
- `files.pdf.extract_images`
- `files.pdf.watermark`

当前落点：

- `src/platform/capability_backend.py`
- `src/platform/internal_capability_provider.py`
- `src/platform/__init__.py`
- `src/tools/builtin.py`

当前实现方式：

- 先由 internal provider 挂接本地 `pdf_tool`
- Bot 工具层不再直接依赖 `pdf_tool.py`
- 后续可继续向 `files.pdf.ocr` 扩展

### 2026-06-17 PDF 成熟项目选型结论

已补充选型文档：

- `docs/pdf-integration-evaluation.md`

当前结论：

- 主推荐项目：`Stirling-PDF`
- OCR 专项补充：`OCRmyPDF`
- 当前 internal provider 继续保留，作为短期可用实现

建议后续顺序：

1. 继续保留现有 internal provider
2. 下一阶段新增 `stirling_pdf_provider.py`
3. 再将 `files.pdf.ocr` 作为 OCRmyPDF 专项能力补齐

### 2026-06-17 当前已完成的第七步 OCRmyPDF provider 接入

已新增：

- `src/platform/ocrmypdf_provider.py`
- `tests/test_ocrmypdf_provider.py`

并已接入统一能力后端：

- `files.pdf.ocr`
- `src.platform.ocr_pdf()`
- `builtin:ocr_pdf`

当前定位：

- OCRmyPDF 作为本地 OCR provider
- 专门处理扫描型 PDF 的可搜索化
- 与现有 internal provider / Stirling-PDF provider 并行演进

同时已补：

- `docs/ocrmypdf-local-deployment.md`

后续同事若要在测试服务器或正式环境继续补齐本地 OCR 处理链，应优先参考该文档。

同时已补：

- `docs/ocrmypdf-local-deployment.md`

后续同事若要在测试服务器或正式环境继续补齐本地 OCR 处理链，应优先参考该文档。

### 2026-06-17 Office 本地集成项目选型结论

已补充选型文档：

- `docs/office-integration-evaluation.md`

当前结论：

- 主推荐项目：`OfficeCLI`
- 协作式补充：`ONLYOFFICE Docs`
- Microsoft 官方 Office AI / Skills 仅作为研究参考，不作为当前主实现

当前判断：

- OfficeCLI 与现有 `document_tool.py` 兼容度最高
- 最适合作为本地私有部署的 Office 主后端

### 2026-06-17 当前已完成的第八步 OfficeCLI 主后端收敛

已新增：

- `src/platform/officecli_provider.py`
- `tests/test_officecli_provider.py`
- `tests/test_office_capabilities.py`

当前统一能力后端已纳入：

- `files.office.service_status`
- `files.docx.generate`
- `files.xlsx.generate`
- `files.pptx.generate`
- `files.docx.template_outline`
- `files.xlsx.template_outline`
- `files.pptx.template_outline`

并已暴露给工具层：

- `builtin:office_service_status`
- `builtin:docx_template_outline`
- `builtin:xlsx_template_outline`
- `builtin:pptx_template_outline`

这意味着 Office 文档能力已不再只是 `document_tool.py` 的本地实现，而是进入统一能力协议体系。

当前已纳入统一能力后端的 Office 能力包括：

- `files.office.service_status`
- `files.docx.generate`
- `files.docx.read`
- `files.xlsx.generate`
- `files.xlsx.read`
- `files.pptx.generate`
- `files.pptx.read`
- `files.docx.template_outline`
- `files.xlsx.template_outline`
- `files.pptx.template_outline`

当前 `Office` 模板链路的最新状态：

- `docx` 模板保留与生成已可用
- `xlsx` 模板保留与生成已接入
- `pptx` 模板保留与生成已接入
- 模板指针已按 `docx/xlsx/pptx` 格式隔离，不再混用最近一次上传的错误模板
- 统一能力后端中的 `xlsx/pptx` 生成能力已支持携带模板路径，不再只支持无模板生成

同时已补：

- `docs/officecli-local-deployment.md`

后续同事若要在测试服务器或正式环境继续补齐 Office 本地处理链，应优先参考该文档。

### 2026-06-18 本地工作区完整性修复记录

本地工作区曾出现严重缺失：

- `src/gateway`
- `src/tools`
- `src/agents`
- `src/engine`
- `src/knowledge`
- `src/orchestrator`
- `src/store`
- `src/web`
- `tests`
- `docs`

以及若干子文件被 OneDrive/本地同步状态异常清空或缺失。

已采取的恢复方式：

- 以测试服务器上的项目部署目录为源
- 将缺失目录与文件同步回本地工作区
- 再继续进行后续开发

当前已补充恢复脚本与说明：

- `scripts/restore_workspace_from_server.py`
- `docs/workspace-recovery.md`

后续建议：

- 若再次出现本地大量目录缺失、导入失败、`.git` 元数据异常，不要在残缺树上继续开发
- 优先以测试服务器当前代码作为恢复源

### 2026-06-17 当前已完成的第六步本地 PDF 服务骨架

已新增：

- `src/platform/stirling_pdf_provider.py`
- `tests/test_stirling_pdf_provider.py`

并已接入统一能力后端的本地服务状态探针：

- `files.pdf.service_status`
- `src.platform.pdf_service_status()`
- `builtin:pdf_service_status`

当前作用：

- 检查本地 Stirling-PDF 服务是否处于可访问状态
- 作为后续真正接入 `Stirling-PDF` 本地能力族前的健康探针

同时已补：

- `infra/stirling-pdf.compose.yml`
- `docs/stirling-pdf-local-deployment.md`

后续同事若要在测试服务器或正式环境部署本地 PDF 服务，应优先参考这两份文件。

### 2026-06-18 当前已完成的第九步 Stirling-PDF 实际接入起点

当前 `Stirling-PDF` provider 已不再只是健康检查骨架，已补入第一批实际能力：

- `merge_pdf_documents`
- `read_pdf_document`
- `compress_pdf_document`
- `watermark_pdf_document`

当前统一能力后端中，以下能力已改为：

- `files.pdf.merge` → Stirling 优先，internal 兜底
- `files.pdf.read` → Stirling 优先，internal 兜底
- `files.pdf.compress` → Stirling 优先，internal 兜底
- `files.pdf.watermark` → Stirling 优先，internal 兜底

这意味着：

- 本地私有部署 PDF 服务已开始承接真实业务能力
- 后续可以按同样模式逐步把其他 PDF 能力迁入 Stirling provider

同时已补充统一能力后端的多 provider 选择逻辑：

- `invoke_first()` 现在优先返回成功 provider
- 若前置 provider 失败，会继续选择后续成功 provider
- 失败 provider 的结果仍保留用于诊断

这使得：

- `Stirling-PDF` / `internal provider`
- `OCRmyPDF` / 其他后续 provider

这类组合真正具备“服务优先、失败兜底”的行为。

## 当前建议的实施顺序

1. **先统一文档与代码入口**
   - Bot First 写入连续开发文档
   - 建立统一能力后端代码骨架
2. **再做能力域迁移**
   - 联系人 / 日历 / 文档 / 审批 / 会议统一走能力层
3. **再做文件与模板深化**
   - 模板探测 / 填充 / 校验三件套
   - 将 PDF 读取、提取、合并、拆分、压缩、加密统一纳入文档能力规划
4. **再扩企业后端能力**
   - 网盘 / 邮箱 / 在线文档 / 第三方系统
5. **最后补治理**
   - 审计 / 敏感能力 / 范围控制

## 当前未完成的主线工作

### A. 平台能力层统一

目标：

- 不再继续在工具函数里直接写平台分支
- 建立统一能力域入口
- 让 Bot 只依赖“能力协议”，不依赖具体平台实现

第一步建议：

- 先收敛联系人 / 日历 / 文档 / 审批 / 会议这几个已有能力

### B. 文档内容生成质量

当前状态：

- 模板格式问题已基本收敛
- 内容仍有继续提升空间

当前策略：

- 优先保模板
- 外部长文扩写成功时走扩写
- 扩写超时时走本地正式制度兜底

下一步建议：

- 把用户要求从“文本块”继续提升为“结构化条目”
- 逐步过渡到模板结构化填充

### C. 企业后端能力扩展

优先级建议：

1. 在线文档 / 网盘
2. 邮箱
3. PDF 文档工作流
4. 日历 / 会议深化
5. 审批与待办
6. 第三方与内部系统

## 接手同事注意事项

### 不建议再做的方向

- 不建议新增“平台专属前端页面”作为主线方案
- 不建议把 AI 交互主入口迁回自建应用
- 不建议继续主要依赖 prompt 强化来恢复模板结构

### 建议默认采用的方向

- Bot 作为唯一用户前台
- 应用 / API 作为后台能力层
- 能力按域抽象
- 文件能力作为一级能力建设
- 长任务默认支持异步回推

## 关键文件索引

### 架构与方向

- `docs/architecture.md`
- `docs/decisions.md`
- `docs/handoff.md`

### Bot 与平台能力

- `src/gateway/wecom_bot_bridge.py`
- `src/platform/bot_setup.py`
- `src/platform/__init__.py`
- `src/platform/api_wecom.py`
- `src/platform/api_feishu.py`
- `src/platform/api_dingtalk.py`

### 文档链路

- `src/gateway/wecom_file_handler.py`
- `src/gateway/inbound_service.py`
- `src/tools/builtin.py`
- `src/tools/document_tool.py`

### 测试

- `tests/test_document_pipeline.py`
- `tests/test_document_download_path.py`
- `tests/test_wecom_bot_bridge.py`
- `tests/test_platform_bot_setup.py`

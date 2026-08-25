# M1 Plan

## Scope

M1 is the smallest production-shaped slice of the current architecture:

- Bot as the only primary user entry
- unified capability backend behind the Bot
- file and document handling as first-class workflow
- local/private Office and PDF processing
- task, memory, and knowledge orchestration sufficient for day-to-day enterprise use

## Delivered Baseline

- WeCom Bot mainline available
- Feishu and DingTalk adapter entrypoints available
- capability backend and internal provider available
- local DOCX/XLSX/PPTX/PDF capabilities connected
- template-preserving document generation available
- local security and build hardening completed

## Current M1 Exit Standard

M1 should be considered locally complete when all of the following hold:

1. `python -m pytest -q` passes locally
2. Bot file -> instruction -> generated file pushback mainline is covered by regression tests
3. capability additions enter through the unified backend rather than platform-specific business branches
4. startup and handoff documents are sufficient for a new teammate to continue work without oral context

## Remaining M1-Level Follow-up

- finish decomposing legacy `src/tools/builtin.py`
- deepen Feishu / DingTalk file-message contract coverage and run live validation after credentials are available
- keep Bot-facing file workflows reproducible through scripted regression runs
- strengthen identity / scope / audit propagation for capability calls

## Non-Goals

- new primary web frontend
- per-platform user-facing application UI as the main interaction surface
- external hosted document processing as the default enterprise path

## Post-M1 Staged Roadmap

After the current M1 baseline is stable, the next capability expansion should follow three execution phases. Each phase is intended to be delivered as one coherent work package rather than scattered feature-by-feature changes.

### Phase 1: Make Existing Assistant Value Visible

Goal:

- turn already-built capabilities into stable, user-visible, frequently used assistant flows

Current status:

- completed as a local productization pass on 2026-07-16
- deterministic Bot-side shortcuts were added for the most common mature office entries
- the file-message workflow was guarded from being misrouted into entry-link commands
- reviewed again on 2026-07-17 with a Phase 1 readiness diagnostic API and admin-console card
- real local backends are separated from external tenant permission / edition limits

Scope:

- knowledge Q&A
- document generation
- policy drafting
- task lifecycle
- contact search
- calendar / meeting coordination
- mail summary
- personal assistant entry prompts and reusable usage patterns

Acceptance focus:

1. each capability has a clear Bot-side natural language entry
2. each capability is documented as "ready" only if it uses real data or a clearly bounded local backend
3. pilot users can complete daily work without opening additional admin-style pages
4. `/api/v1/admin/phase1/readiness` shows whether each Phase 1 capability is ready, degraded, needs configuration, or blocked

Implemented Bot entries:

- `你能做什么` / `企业 AI 助手功能`
- `搜索知识库 ...`
- `创建任务 ...` / `查询任务列表` / `完成任务 task-...`
- `找...联系方式` / `通讯录搜索 ...`
- `查今天日程`
- `查看未读邮件`
- existing enterprise queries such as `查询我所有审批的状态` and meeting-room questions keep priority over generic office shortcuts

Known external constraints:

- WeCom contact live API may still require tenant-side permission; local org cache is the fallback.
- WeCom meeting list may require a higher WeCom edition; meeting-room query remains the bounded supported path.
- Calendar data depends on tenant calendar permission and actual user-visible schedule data.
- 邮箱员工侧已关闭正文摘要；IMAP 使用 `UNSEEN` 做真实未读统计，POP3 使用本地未确认新邮件提醒台账，Exchange EWS and Microsoft 365 Graph require site-specific authorization.

### Phase 2: Active Reminder And Aggregation Layer

Goal:

- move from "ask-reply" to "assistant actively informs the user"

Scope:

- daily personal briefings
- leave balance reminders
- attendance anomaly summaries
- approval follow-up reminders
- unified search across knowledge / docs / mail / drive
- threshold-based alerts

Acceptance focus:

1. scheduled jobs are configurable, observable, and retryable
2. no repeated spam; every notification path has dedupe and cooldown
3. outputs are structured and scoped by real user permission context

Execution package:

1. Personal daily briefing
   - combine calendar, approvals, tasks, mail summary, weather, and subscription reminders into one morning push
   - one stable trigger window per user, with dedupe on the same day
2. Process and approval change notification hardening
   - move from polling-only alerts to state-diff snapshots with explicit cooldown
   - notify only the applicant by default
3. Unified retrieval entry
   - one Bot-side natural-language entry for knowledge, docs, drive, and mail aggregation
   - preserve permission scope and source labels in every result
4. Subscription center
   - manage weather, air quality, exchange rate, RSS, and other public-data subscriptions from a single backend
   - add enable, disable, pause, resume, and last-run status
5. Observability and audit
   - record why a reminder was sent, skipped, deduped, or failed
   - expose delivery status to admins before expanding message volume

Prerequisites:

- `phase1/readiness` should not show `needs_config` on the core data sources needed by the target reminder bundle
- mail summary should be configured for the pilot users if email is part of the push package
- approval and calendar scopes must be validated on the real tenant, not only in local tests

Suggested rollout order:

1. pilot with one manager account and one ordinary employee account
2. 默认只启用审批状态变更通知；每日工作简报保持停用，待内容范围和频率审核后再单独启用
3. expand to subscription reminders after dedupe and cooldown are verified
4. expand the unified retrieval entry after source labels and permission boundaries are stable

Done means:

1. 每日工作简报默认不主动投递，管理员可审计其停用状态
2. one approval state change produces exactly one correct notification to the applicant
3. admins can see why any planned notification was or was not sent
4. users can ask one aggregated retrieval question and get source-labeled results without crossing permission scope

### Phase 2 Delivery Status (2026-07-17)

Phase 2 is now implemented as a Bot-first delivery, with the following user-visible entries:

1. First-conversation identity setup
   - Every user receives a Chinese role introduction on the first conversation without blocking the original work request.
   - Users can set a remembered assistant name and common role, for example: `你的名字叫小智，角色选文档与制度顾问`.
2. Daily personal briefings
   - `daily-personal-brief` remains registered for audit and future controlled rollout, but is disabled by default and does not proactively message employees.
   - Employees can use the existing Bot queries to view their own calendar, approvals, tasks, and mail summaries on demand.
3. Process notification hardening
   - First polling result establishes a baseline and does not send historical notifications.
   - A changed approval is committed only after outbound delivery succeeds; failed delivery remains retryable.
   - Process notification audit records baseline, unchanged, sent, and delivery-failed decisions.
4. Unified retrieval
   - Bot entries: `统一搜索 ...`, `综合搜索 ...`, `全局搜索 ...`.
   - Results are labeled in Chinese and aggregate accessible knowledge, enterprise documents, drive, and mail.
5. Subscription center
   - Bot entries create, list, pause, resume, and delete weather, air-quality, exchange-rate, RSS/news, and holiday subscriptions.
   - The backend records create, pause, resume, delete, notification, and notification-failure actions.
6. Admin observability
   - `GET /api/v1/admin/phase2/notification-audit` returns daily briefing, process notification, and public subscription audit records.
   - User APIs under `/api/v1/user/subscriptions` allow authenticated client surfaces to list and manage the current user's subscriptions.

### Phase 3: Business-System Orchestration

Goal:

- extend the assistant from office support into enterprise workflow coordination

Scope:

- workorder closed-loop operations
- cross-system golden flows
- self-service BI / natural language metrics lookup
- fine-grained temporary authorization and data masking
- deep ecosystem integrations

Acceptance focus:

1. every workflow depends on real system integration, not sample fallback
2. authority boundaries, audit, and escalation paths are explicit
3. each launched workflow has business owner sign-off and rollback strategy

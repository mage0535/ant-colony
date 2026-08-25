# Enterprise Application Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build permission-aware, domain-bounded and fuzzy enterprise application querying for WeCom, Feishu and DingTalk.

**Architecture:** A query planner converts natural language into a typed plan. An application registry maps domains to capability IDs and permissions. The capability backend injects user context into providers, and providers return live data or explicit permission diagnostics without production sample fallback.

**Tech Stack:** Python 3.12+, dataclasses, existing capability backend, platform API clients, pytest.

---

### Task 1: Typed query planner

**Files:**
- Create: `src/platform/enterprise_query.py`
- Create: `tests/test_enterprise_query.py`

- [ ] Write failing tests for meeting-room boundaries, approval self-scope, availability intent, fuzzy aliases and explicit cross-domain requests.
- [ ] Run `python -m pytest -q tests/test_enterprise_query.py` and confirm missing-module failure.
- [ ] Implement `EnterpriseQueryPlan`, domain aliases, normalized fuzzy matching and time-range extraction.
- [ ] Run the query planner tests and confirm they pass.

### Task 2: Application capability registry

**Files:**
- Create: `src/platform/application_registry.py`
- Modify: `src/platform/capability_backend.py`
- Test: `tests/test_application_registry.py`

- [ ] Write failing tests proving each domain maps only to its own capability and required permissions.
- [ ] Implement registry entries for meeting rooms, approvals, calendar, docs, drive, mail, contacts and third-party apps.
- [ ] Add capability-context injection only for provider methods that declare `capability_context`.
- [ ] Verify existing provider methods remain backward compatible.

### Task 3: WeCom permission-aware providers

**Files:**
- Modify: `src/platform/api_wecom.py`
- Test: `tests/test_wecom_enterprise_queries.py`

- [ ] Write failing tests for room occupancy, room availability, approval self-filtering, fuzzy entity matching and independent domain failures.
- [ ] Implement typed plan execution and provenance metadata.
- [ ] Fetch approval numbers then details, filtering records by current user participation.
- [ ] Keep permission failures separate from empty results.

### Task 4: Agent and tool routing

**Files:**
- Modify: `src/workflows/office_workflow_service.py`
- Modify: `src/agents/personal_agent.py`
- Modify: `src/tools/platform_capability_tools.py`
- Test: `tests/test_office_workflow_service.py`
- Test: `tests/test_engine.py`

- [ ] Write failing regressions for the four reported conversations.
- [ ] Replace broad keyword branching with query-plan execution.
- [ ] Render domain-separated results and omit unrelated sections.
- [ ] Ensure missing tool arguments fall back to the original user query.

### Task 5: Simulation and three-platform contract

**Files:**
- Modify: `src/platform/api_feishu.py`
- Modify: `src/platform/api_dingtalk.py`
- Modify: `src/platform/internal_capability_provider.py`
- Test: `tests/test_platform_adapter_simulation.py`

- [ ] Add typed-plan contract tests for Feishu and DingTalk.
- [ ] Keep sample data available only behind `ANT_COLONY_ENABLE_SAMPLE_BUSINESS_DATA=true`.
- [ ] Verify production mode never returns `[系统能力]` sample application data.

### Task 6: Server rollout and validation

**Files:**
- Modify: `docs/handoff.md`

- [ ] Run targeted tests, then `python -m pytest -q`.
- [ ] Synchronize changed files to the test server.
- [ ] Restart gateway, callback and root WeCom Bot processes so all channels load identical code.
- [ ] Run the full server suite.
- [ ] Probe the four acceptance queries through port 18090 and inspect the real Bot process logs.
- [ ] Record exact permission limitations and results in `docs/handoff.md`.

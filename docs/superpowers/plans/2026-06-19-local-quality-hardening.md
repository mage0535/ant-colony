# Local Quality Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining evidence-backed local security, scheduling, and document-link defects without changing the Bot First architecture.

**Architecture:** Keep each fix within its existing boundary: request authorization in web middleware, schedule parsing in the cron model, and URL construction in the document generation service. Preserve loopback service compatibility and direct Bot file delivery.

**Tech Stack:** Python 3.12+, FastAPI/Starlette, pytest, setuptools.

---

### Task 1: Dashboard API Access Boundary

**Files:**
- Modify: `src/web/middleware.py`
- Modify: `src/web/dashboard.py`
- Create: `tests/test_web_auth.py`

- [ ] Write tests proving remote requests fail closed without a token, loopback requests remain allowed, valid Bearer tokens pass, and GET API routes invoke authentication.
- [ ] Run `python -m pytest tests/test_web_auth.py -q` and confirm the new tests fail for the current permissive behavior.
- [ ] Implement loopback-aware fail-closed authorization with constant-time token comparison and protect every non-public route.
- [ ] Re-run `python -m pytest tests/test_web_auth.py -q` and confirm all tests pass.

### Task 2: Cron Parser Correctness

**Files:**
- Modify: `src/orchestrator/cron_job.py`
- Modify: `tests/test_cron_security.py`

- [ ] Add tests for empty input, compact intervals, month matching, and weekday matching with fixed base timestamps.
- [ ] Run `python -m pytest tests/test_cron_security.py -q` and confirm failures expose the current parser gaps.
- [ ] Implement the smallest dependency-free next-minute matcher for integer-or-wildcard five-field cron expressions.
- [ ] Re-run the focused cron tests and confirm all pass.

### Task 3: Portable Document Links

**Files:**
- Modify: `src/tools/document_generation_service.py`
- Modify: `tests/test_document_pipeline.py`

- [ ] Add tests proving the configured base URL is used, trailing slashes are normalized, Chinese/spaced filenames are quoted, and Bot file responses remain direct.
- [ ] Run the focused tests and confirm the hard-coded URL causes failure.
- [ ] Add a small URL builder and route fallback/card URLs through it.
- [ ] Re-run the focused document tests and confirm all pass.

### Task 4: Full Verification and Handoff

**Files:**
- Modify: `docs/handoff.md`

- [ ] Run the full pytest suite, compile checks, Ruff `F821,F823`, Bandit high-severity scan, `pip-audit .`, and isolated wheel/sdist build.
- [ ] Review the final diff for behavior regressions, credential leakage, and unrelated edits.
- [ ] Record exact commands, results, and residual external validation limits in `docs/handoff.md`.

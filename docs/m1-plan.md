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

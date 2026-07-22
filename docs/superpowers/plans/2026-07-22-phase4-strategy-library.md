# Phase 4 Strategy Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add immutable, versioned built-in strategy definitions and bind new backtests to an explicit strategy version while preserving historical runs.

**Architecture:** Add one linear Alembic migration for strategy definitions/versions and a nullable BacktestRun foreign key. Keep strategy validation in a service, persistence in a repository, and expose explicit FastAPI routes. Existing embedded specs remain the compatibility source for legacy runs.

**Tech Stack:** Python, FastAPI, SQLite, Alembic, Pydantic, pytest, React/TypeScript only for later workspace work.

---

### Task 1: P0 validation

**Files:**
- Modify: `.gitignore` only if runtime cache is not ignored.
- Test: existing `backend/tests` and Phase 3 smoke harness.

- [ ] Run mypy with `--cache-dir .runtime/test-cache/mypy-phase4`.
- [ ] Run the existing backend suite and Alembic head checks.
- [ ] Execute the temporary calendar → dataset → profile → two backtests → restart smoke path.

### Task 2: Strategy persistence

**Files:**
- Create: `backend/alembic/versions/20260722_0008_create_strategy_library.py`
- Create: `backend/src/quant_lab/strategies/domain.py`
- Create: `backend/src/quant_lab/strategies/repository.py`
- Create: `backend/src/quant_lab/strategies/service.py`
- Test: `backend/tests/strategies/test_persistence.py`

- [ ] Write failing tests for immutable versions, transactional numbering, and archive behavior.
- [ ] Implement tables, unique constraints, foreign keys, and immutable triggers.
- [ ] Implement canonical spec validation for BUY_AND_HOLD and TOP_N_MOMENTUM_ROTATION.
- [ ] Run focused strategy tests.

### Task 3: Strategy API

**Files:**
- Create: `backend/src/quant_lab/api/strategy_schemas.py`
- Create: `backend/src/quant_lab/api/strategies.py`
- Modify: `backend/src/quant_lab/main.py`
- Test: `backend/tests/strategies/test_api.py`

- [ ] Add create/list/detail/version/archive routes with stable errors.
- [ ] Reject Python, expression, SQL, and unknown spec fields.
- [ ] Run API tests and OpenAPI route assertions.

### Task 4: Backtest version binding

**Files:**
- Modify: `backend/alembic/versions/20260722_0007_create_backtest_runs.py` only if a follow-up migration is required.
- Modify: `backend/src/quant_lab/backtest/repository.py`
- Modify: `backend/src/quant_lab/backtest/service.py`
- Modify: `backend/src/quant_lab/api/backtest_schemas.py`
- Modify: `backend/src/quant_lab/api/backtests.py`
- Test: `backend/tests/backtest/test_strategy_version_binding.py`

- [ ] Add a nullable `strategy_version_id` migration without rewriting old rows.
- [ ] Require explicit strategy version for new runs and copy its frozen spec into the run snapshot.
- [ ] Keep legacy runs readable and preserve succeeded-run immutability.
- [ ] Run focused backtest compatibility tests.

### Task 5: Acceptance

- [ ] Run full backend pytest, Ruff, isolated-cache mypy, frontend Vitest, TypeScript build, `git diff --check`, Alembic upgrade/downgrade checks, and the temporary integration smoke.
- [ ] Report changed files, tests, limitations, final HEAD, and clean worktree.

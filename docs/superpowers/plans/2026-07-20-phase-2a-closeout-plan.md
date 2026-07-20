# Phase 2A Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Phase 2A for local commit by making repeated import previews transactionally idempotent, completing runtime-file ignore/path coverage, and clarifying that vn.py remains an unimplemented candidate rather than the unique trading runtime.

**Architecture:** Add a stable SHA-256 identity for every persisted quality issue and enforce `(batch_id, issue_fingerprint)` with a new forward Alembic revision. Repository preview completion replaces one batch's issue set and statistics inside one SQLite transaction. Documentation-only changes preserve the approved conditional process boundary while leaving Phase 2B/2C sequencing and alternative QMT/XtQuant adapters unchanged.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, SQLite, FastAPI, pytest, PowerShell, React/TypeScript/Vitest.

---

### Task 1: Prove repeated preview is not idempotent

**Files:**
- Modify: `backend/tests/market_data/test_persistence.py`
- Modify: `backend/tests/market_data/test_import_api.py`

- [ ] **Step 1: Add a repository test** that completes one batch twice with the same `QualityIssue`, then asserts one stored issue and unchanged accepted/rejected/warning counts.
- [ ] **Step 2: Add an API test** that calls `POST /api/v1/data/imports/preview` twice for one batch, compares both response counts, and asserts `GET .../issues` has the same deterministic issue set.
- [ ] **Step 3: Run both tests and verify RED** because the second preview currently appends duplicate issue rows.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/market_data/test_persistence.py backend/tests/market_data/test_import_api.py -q
```

Expected: the new repository and API assertions fail with duplicate issue counts.

### Task 2: Add database-enforced quality issue identity

**Files:**
- Create: `backend/alembic/versions/20260720_0003_add_quality_issue_fingerprint.py`
- Modify: `backend/src/quant_lab/market_data/persistence.py`
- Modify: `backend/src/quant_lab/market_data/repository.py`

- [ ] **Step 1: Define canonical fingerprint input** as JSON over `row_number`, `symbol`, `field_name`, `severity`, `issue_code`, `message`, and `raw_value`, then SHA-256 encode it.
- [ ] **Step 2: Add `issue_fingerprint VARCHAR(64) NOT NULL`** to the ORM model and a unique database index on `(batch_id, issue_fingerprint)`.
- [ ] **Step 3: Add revision `20260720_0003`** without editing `0002`: add a nullable column, fingerprint existing rows, delete exact duplicates per batch, make the column non-null, and create the unique index. Downgrade drops the index and column.
- [ ] **Step 4: Make preview completion transactional** by updating batch counts, deleting the batch's existing issue rows, inserting the canonical deduplicated issue set, and committing once. Do not catch or suppress integrity/database failures.
- [ ] **Step 5: Run targeted tests and verify GREEN.**

### Task 3: Complete runtime path and ignore coverage

**Files:**
- Modify: `.gitignore`
- Modify: `backend/tests/test_config.py`
- Modify: `scripts/test_common.ps1`

- [ ] **Step 1: Add tests** proving a relative `QUANT_LAB_RUNTIME_ROOT` resolves under the project root in Python and PowerShell.
- [ ] **Step 2: Verify RED** for any missing assertion before changing implementation.
- [ ] **Step 3: Keep centralized path behavior unchanged if tests show it already satisfies the requirement; only add the missing coverage.**
- [ ] **Step 4: Ignore `*.duckdb.tmp` and `imports/staging/`, then verify with `git check-ignore -v --no-index`.**

### Task 4: Clarify candidate runtime and migrated path documentation

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `docs/ADR-0001-vnpy-runtime-boundary.md`
- Modify: `docs/VNPY_INTEGRATION_PLAN.md`
- Modify: `docs/VNPY_CAPABILITY_MATRIX.md`
- Modify: `docs/superpowers/specs/2026-07-20-phase-2a-data-foundation-design.md`

- [ ] **Step 1: State that vn.py is not installed, selected as the unique runtime, or approved for implementation.**
- [ ] **Step 2: Preserve only the conditional decision: if vn.py is adopted, it runs out of process.**
- [ ] **Step 3: State that direct official QMT/XtQuant adapters remain possible and Phase 2B/2C retain priority.**
- [ ] **Step 4: Replace the obsolete claim that the repository currently resides in OneDrive; retain OneDrive only as a generic deployment warning.**
- [ ] **Step 5: Document relative runtime-root semantics and non-destructive behavior.**

### Task 5: Verify migrations, runtime, and repository boundaries

**Files:**
- Test only; isolated runtime directory outside the repository.

- [ ] **Step 1: Run `git diff --check`, PowerShell PID tests, all backend tests, Ruff, mypy, frontend Vitest, TypeScript, and Vite build.**
- [ ] **Step 2: Verify empty database `upgrade head`.**
- [ ] **Step 3: Build a database at `20260720_0002`, seed duplicate legacy issues, upgrade to head, and confirm deduplication plus unique index.**
- [ ] **Step 4: Run `upgrade head` again and verify no-op success.**
- [ ] **Step 5: Start services with an isolated absolute runtime root, smoke-test health, frontend, CSV inspect, two previews, deterministic counts/issues, then stop safely.**
- [ ] **Step 6: Confirm ports 8000/5173 are closed and PID files removed.**
- [ ] **Step 7: Scan for old OneDrive paths, forbidden runtime dependencies/code, and accidentally tracked runtime artifacts.**

### Task 6: Create two local commits

**Files:**
- Commit 1: implementation, migration, configuration, tests, scripts, frontend.
- Commit 2: README, architecture, Phase 2A plans/specification, ADR and vn.py candidate documents.

- [ ] **Step 1: Display final status, file lists, diff stat, revision chain, test evidence, path review and limitations.**
- [ ] **Step 2: Stage only implementation files and commit:**

```powershell
git commit -m "feat(data): implement Phase 2A market data import preview"
```

- [ ] **Step 3: Stage only documentation files and commit:**

```powershell
git commit -m "docs(data): document Phase 2A architecture and future runtime boundaries"
```

- [ ] **Step 4: Verify clean `phase-2a-data-foundation`, unchanged `master`/`foundation`, and no merge/push/rebase.**

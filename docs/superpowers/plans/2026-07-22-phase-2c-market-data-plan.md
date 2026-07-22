# Phase 2C Market Data Consumption Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add versioned trading calendars, immutable MarketDataProfile bindings, deterministic market-data consumption/coverage APIs, and a minimal market-data UI without entering backtesting or broker work.

**Architecture:** Trading calendars are local CSV control-plane data in SQLite with immutable published versions. A MarketDataProfile explicitly binds one published DatasetVersion and one published CalendarVersion. MarketDataService resolves only through profiles, validates published-file integrity, queries Parquet through DuckDB, and computes coverage against explicit open trading sessions. Snapshot fingerprints freeze the selected profile/version identities without copying bars or Parquet files.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic SQLite control plane, DuckDB read-only Parquet queries, Pydantic, React/Vitest/TypeScript.

---

### Task 1: Publish existing Dataset query routes in OpenAPI

**Files:**
- Modify: `backend/src/quant_lab/api/datasets.py`
- Test: `backend/tests/datasets/test_dataset_api.py`

- [ ] Remove `include_in_schema=False` from summary and bars routes.
- [ ] Update the OpenAPI route assertion to include summary and bars plus publish.
- [ ] Run `python -m pytest backend/tests/datasets/test_dataset_api.py -q` and confirm the expected failure is replaced by a pass.
- [ ] Commit `fix(api): publish dataset query routes in openapi`.

### Task 2: Add versioned trading-calendar persistence and migration

**Files:**
- Create: `backend/alembic/versions/20260722_0005_create_trading_calendars.py`
- Create: `backend/src/quant_lab/market_data/calendar_persistence.py`
- Create: `backend/src/quant_lab/market_data/calendar_domain.py`
- Modify: `backend/src/quant_lab/datasets/persistence.py` only if shared immutable-trigger conventions are required
- Test: `backend/tests/market_data/test_calendar_repository.py`

- [ ] Write failing tests for calendar/version/session tables, unique `(calendar_id, version)`, unique `(calendar_version_id, session_date)`, and published immutability.
- [ ] Add the migration with a single `20260722_0005` head and foreign keys using `RESTRICT`.
- [ ] Add immutable SQL triggers that allow `FILES_COMMITTED`-style publication transitions but reject updates/deletes after `PUBLISHED`.
- [ ] Add SQLAlchemy models and `TradingCalendarRepository` methods for create/list/import/list versions/get version/list sessions.
- [ ] Keep `is_open=false` rows explicit and never infer sessions from bars.
- [ ] Run only `backend/tests/market_data/test_calendar_repository.py` until green.
- [ ] Commit `feat(data): add versioned trading calendars`.

### Task 3: Implement local CSV calendar import and API

**Files:**
- Create: `backend/src/quant_lab/market_data/calendar_service.py`
- Create: `backend/src/quant_lab/api/calendar_schemas.py`
- Create: `backend/src/quant_lab/api/calendars.py`
- Modify: `backend/src/quant_lab/main.py`
- Test: `backend/tests/market_data/test_calendar_import.py`
- Test: `backend/tests/api/test_calendar_api.py`

- [ ] Write failing tests for controlled CSV import, SHA-256, strict date/time parsing, duplicate-date rejection, deterministic fingerprint, explicit holidays, and relative-path-safe errors.
- [ ] Implement import from already staged local upload bytes; do not accept client filesystem paths or network URLs.
- [ ] Canonicalize sessions by date, serialize deterministic payload, and calculate SHA-256 fingerprint.
- [ ] Create a new immutable version for each distinct source/config; repeat identical import returns the existing version.
- [ ] Expose `POST /api/v1/market-calendars`, `GET /api/v1/market-calendars`, `POST /api/v1/market-calendars/{calendar_id}/versions/import`, `GET .../versions`, `GET .../versions/{version_id}`, and `GET .../sessions`.
- [ ] Run calendar repository/import/API tests until green.

### Task 4: Add immutable MarketDataProfile bindings

**Files:**
- Create: `backend/alembic/versions/20260722_0006_create_market_data_profiles.py`
- Create: `backend/src/quant_lab/market_data/profile_persistence.py`
- Create: `backend/src/quant_lab/market_data/profile_service.py`
- Create: `backend/src/quant_lab/api/profile_schemas.py`
- Create: `backend/src/quant_lab/api/profiles.py`
- Modify: `backend/src/quant_lab/main.py`
- Test: `backend/tests/market_data/test_profile_service.py`
- Test: `backend/tests/api/test_profile_api.py`

- [ ] Write failing tests proving only `PUBLISHED` and file-consistent DatasetVersion/CalendarVersion can be bound.
- [ ] Add `MarketDataProfile` with explicit dataset/calendar version IDs, status, timestamps, and audit records; support only `CN_A_SHARE_DAILY`.
- [ ] Ensure PATCH changes explicit version bindings only; never resolve a latest version implicitly.
- [ ] Add profile snapshot fields/methods needed for deterministic fingerprinting without copying data.
- [ ] Expose POST/GET profile APIs and immutable binding validation.
- [ ] Run profile tests until green.
- [ ] Commit `feat(data): bind immutable market data profiles`.

### Task 5: Implement MarketDataService, coverage, health, and snapshot

**Files:**
- Create: `backend/src/quant_lab/market_data/consumption.py`
- Create: `backend/src/quant_lab/api/market_data.py`
- Modify: `backend/src/quant_lab/api/datasets.py` only for shared response types if necessary
- Modify: `backend/src/quant_lab/main.py`
- Test: `backend/tests/market_data/test_consumption_service.py`
- Test: `backend/tests/api/test_market_data_api.py`

- [ ] Write failing tests for bars sorting/filtering/limit, explicit version IDs in results, instrument metadata lookup, calendar-based missing sessions, holiday exclusion, non-trading-day anomaly reporting, incomplete calendar coverage, health states, and stable snapshot fingerprints.
- [ ] Resolve all files only from DatasetFile metadata and the configured published root; reject traversal, missing files, hash/size mismatches, and non-published versions.
- [ ] Query Parquet using parameterized DuckDB statements only; never accept arbitrary SQL.
- [ ] Compute `missing = open calendar sessions without a bar`, and report out-of-calendar bars separately.
- [ ] Return `CALENDAR_REQUIRED`/`CALENDAR_COVERAGE_INCOMPLETE` rather than infer weekdays as sessions.
- [ ] Implement profile instruments, bars, coverage, health, and snapshot endpoints.
- [ ] Run consumption/API tests until green.
- [ ] Commit `feat(data): add market data coverage and query services`.

### Task 6: Add minimal market-data frontend

**Files:**
- Create: `frontend/src/pages/MarketDataPage.tsx`
- Create: `frontend/src/services/marketData.ts`
- Create: `frontend/src/types/marketData.ts`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/pages/MarketDataPage.test.tsx`

- [ ] Write 4-7 focused Vitest tests for calendar loading/import error, explicit published-version selection, health display, instrument filtering, and coverage missing-date display.
- [ ] Implement `/market-data` with existing visual language; keep controls simple and do not add charts, SQL, auto-repair, broker, strategy, or backtest UI.
- [ ] Run the focused frontend tests and build.
- [ ] Commit `feat(ui): add market data management page`.

### Task 7: Final integration, migrations, and acceptance

**Files:**
- Test: `backend/tests/market_data/test_phase_2c_integration.py`
- Test: `frontend/src/services/marketData.test.ts`

- [ ] Add only the minimum end-to-end tests for CSV calendar import, profile binding, bars/coverage/snapshot, restart reproducibility, no SQLite bar table, and relative paths.
- [ ] Verify empty database upgrade, `20260720_0004` to head upgrade, repeated upgrade, downgrade/upgrade, and single Alembic head.
- [ ] Run the official unified acceptance script once after all development changes.
- [ ] Run the temporary runtime-root integration flow using a local CSV/calendar and verify identical snapshot fingerprints after restart.
- [ ] Run `git diff --check`, verify clean worktree and no merge/push/rebase.
- [ ] Stop and report actual elapsed time, commits, test counts, acceptance results, limitations, and no Phase 3 work.
